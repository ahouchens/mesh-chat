import { useCallback, useEffect, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { Check, Copy, Phone, RefreshCw, X } from "lucide-react";

import { desktopServiceHealth, serviceCommand, onServiceEvent, type ServiceEvent } from "./api";
import { attachWebRTCBridge, isWindowsWebRTCPlatform, shouldAutoCloseWebRTCOnboarding, webRTCWindowsChecklist, type WebRTCBridge } from "./webrtc-onboarding";
import { isNativeWebRTCPlatform, nativeWebRTCAccept, nativeWebRTCApplyAnswer, nativeWebRTCClose, nativeWebRTCControl, nativeWebRTCOffer, nativeWebRTCStats, type NativeChannelSpec } from "./native-webrtc";
import { rememberWebRTCDiagnostics } from "./webrtc-diagnostics";
import { startPeerTrace, type PeerTrace } from "./webrtc-trace";
import { getWebRTCSessionByKey, removeWebRTCSession, setWebRTCSession, updateWebRTCSessionApprovalPending, updateWebRTCSessionContact, type WebRTCSessionPath } from "./webrtc-session";
import { clearPairingResume, savePairingResume } from "./pairing-resume";
import { resendReconnectCapabilities, storeReconnectCapabilities } from "./reconnect-control";
import {
  connectionPath,
  fingerprint,
  peerDiagnostics,
  summarizeIce,
  waitForCandidates,
  waitForOpen,
  withEndOfCandidates,
} from "./webrtc-peer";
import type {
  CallIceConfiguration,
  CallSettings,
  InvitationFormats,
  InvitationPreview,
  ContactInvitation,
  WorkspaceInvitationFormats,
  WorkspaceInvitationPreview,
} from "./types";

const NATIVE_ONBOARDING_CHANNELS: NativeChannelSpec[] = [
  { label: "mesh-reticulum", binary: true, ordered: true },
  { label: "mesh-onboarding", binary: false, ordered: true },
];

export function normalizeWebRTCOfferInput(raw: string): string {
  const value = raw.trim();
  const prefix = "meshchat://pair/";
  return value.startsWith(prefix) ? value.slice(prefix.length).trim() : value;
}

// Leave headroom below the version 40 byte limits. SDP documents can exceed
// those limits; the complete signed text always remains available to copy.
const MAX_WEBRTC_QR_BYTES = { L: 2_800, M: 2_200 };

function WebRTCQrCode({ value, size = 190, level = "L" }: { value: string; size?: number; level?: "L" | "M" }) {
  const [expanded, setExpanded] = useState(false);
  if (!value || new TextEncoder().encode(value).byteLength > MAX_WEBRTC_QR_BYTES[level]) return null;
  return <div>
    <button className="button button--ghost" type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? "Hide QR code" : "Show QR code"}</button>
    {expanded && <div className="webrtc-qr"><QRCodeSVG value={value} size={size} level={level} boostLevel={false} /></div>}
  </div>;
}

interface OnboardingOfferResult {
  document: string;
  session_id: string;
  expires_at: number;
}

interface OnboardingOfferPreview {
  document: string;
  session_id: string;
  sdp: string;
  dtls_fingerprint: string;
  expires_at: number;
  signer_destination: string;
}

interface OnboardingAnswerResult {
  document: string;
  session_id: string;
  signer_destination: string;
  expires_at: number;
}

interface OnboardingAnswerPreview {
  document: string;
  session_id: string;
  sdp: string;
  dtls_fingerprint: string;
  expires_at: number;
  signer_destination: string;
}

type Phase = "choose" | "creating" | "waiting-answer" | "review" | "waiting-owner" | "connecting" | "connected" | "error";

type OnboardingState = "idle" | "sending" | "sent" | "preview" | "waiting-approval" | "approved" | "declined" | "error";

// ICE checks can time out before a person returns the signed answer. Keep the
// answerer's TURN allocations alive so checks from the offerer can revive ICE.
const ANSWER_EXCHANGE_TIMEOUT_MS = 120_000;

type ControlMessage =
  | { type: "contact_invitation"; document: string; workspace_document?: string }
  | { type: "invitation_accepted"; capabilities?: string }
  | { type: "invitation_declined" }
  | { type: "invitation_approved"; capabilities?: string }
  | { type: "invitation_denied" }
  | { type: "connection_capabilities_request" }
  | { type: "connection_capabilities"; document: string };

function documentType(value: string): string {
  try {
    const parsed = JSON.parse(value) as { type?: unknown };
    return typeof parsed.type === "string" ? parsed.type : "";
  } catch {
    return "";
  }
}

function offerErrorMessage(reason: unknown, offerVerified = false, operation = ""): string {
  const code = reason && typeof reason === "object" && "code" in reason
    ? String((reason as { code?: unknown }).code ?? "")
    : "";
  if (operation === "signal_fetch") {
    if (code === "mailbox_not_configured") return "Signaling mailbox is off on this device. Use the default mailbox or set the same mailbox as the other device in Settings, then try this code again.";
    if (code === "mailbox_rate_limited") return "The signaling mailbox is busy. Wait a little before trying this code again.";
    if (code === "mailbox_unauthorized") return "The mailbox rejected this pairing code. Ask the other device to create a fresh invitation and copy its complete code.";
    if (code === "network_unavailable") return "The offer could not be retrieved from the mailbox. Check your internet connection and try again; if the code expired, ask for a fresh invitation.";
    if (code === "invitation_expired") return "The offer in the mailbox has expired. Ask the other device to create a fresh invitation.";
    return "The mailbox code could not be opened. Check that both devices use the same mailbox, then copy a fresh, complete code from the other device.";
  }
  if (code === "identity_mismatch") {
    return offerVerified
      ? "The verified offer could not be bound to this WebRTC session. Create a fresh offer and try again."
      : "The offer signature could not be verified. Copy the complete current offer from the device that created it; if it was regenerated, use the new offer.";
  }
  if (code === "invalid_request") {
    return offerVerified
      ? "The offer was verified, but this device could not create an answer. Create a fresh offer and try again."
      : "The signed WebRTC offer could not be verified. Create a fresh offer and copy it again.";
  }
  return reason instanceof Error ? reason.message : "The WebRTC offer could not be verified.";
}

function answerErrorMessage(reason: unknown): string {
  const code = reason && typeof reason === "object" && "code" in reason
    ? String((reason as { code?: unknown }).code ?? "")
    : "";
  if (code === "identity_mismatch") {
    return "This answer belongs to a different WebRTC offer. Generate a new answer from the current offer.";
  }
  if (code === "invalid_request") {
    return "This is not a complete signed WebRTC answer. Copy the entire answer document.";
  }
  return reason instanceof Error ? reason.message : "The WebRTC answer could not be verified.";
}

function errorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : "The WebRTC onboarding step failed.";
}

function diagnosticErrorCode(reason: unknown): string {
  const value = reason && typeof reason === "object" && "code" in reason
    ? String(reason.code) : "";
  return /^[a-z0-9_]{1,80}$/.test(value) ? value : "unavailable";
}

function sessionCode(document: string): string {
  try {
    const value = JSON.parse(document) as { session_id?: unknown };
    return typeof value.session_id === "string" ? value.session_id.slice(0, 8) : "?";
  } catch {
    return "?";
  }
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function WebRTCOnboardingDialog({ onClose, onChanged, onConnected, onFallback, workspaces = [], initialPairingCode = "" }: {
  onClose: () => void;
  onChanged: () => Promise<void>;
  onConnected?: (path: WebRTCSessionPath) => void;
  onFallback?: () => void;
  workspaces?: Array<{ id: string; name: string }>;
  initialPairingCode?: string;
}) {
  const [phase, setPhase] = useState<Phase>("choose");
  const [offerDocument, setOfferDocument] = useState("");
  const [answerDocument, setAnswerDocument] = useState("");
  const [offerInput, setOfferInput] = useState("");
  const [answerInput, setAnswerInput] = useState("");
  const [offerPreview, setOfferPreview] = useState<OnboardingOfferPreview | null>(null);
  const [answerPreview, setAnswerPreview] = useState<OnboardingAnswerPreview | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState("");
  const [diagnostics, setDiagnostics] = useState("");
  const failureContextRef = useRef<{ operation: string; error_code: string; offer_verified: boolean } | null>(null);
  const [onboarding, setOnboarding] = useState<OnboardingState>("idle");
  const [onboardingError, setOnboardingError] = useState("");
  const [contactInvitation, setContactInvitation] = useState<InvitationPreview | null>(null);
  const [workspaceInvitation, setWorkspaceInvitation] = useState<WorkspaceInvitationPreview | null>(null);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState("");
  const [onboardingBusy, setOnboardingBusy] = useState(false);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [relaySettings, setRelaySettings] = useState<CallSettings | null>(null);
  const [relayBusy, setRelayBusy] = useState(false);
  const [relayError, setRelayError] = useState("");
  const [mailboxCode, setMailboxCode] = useState("");
  const [fetchingAnswer, setFetchingAnswer] = useState(false);
  const answerFetchRef = useRef(0);
  const answerFetchBusyRef = useRef(false);
  const capabilityRequestPendingRef = useRef(false);
  const phaseRef = useRef(phase);
  phaseRef.current = phase;
  useEffect(() => () => { answerFetchRef.current += 1; }, []);
  const windowsPlatform = isWindowsWebRTCPlatform(typeof navigator === "undefined" ? "" : navigator.userAgent);
  const nativeMode = isNativeWebRTCPlatform(typeof navigator === "undefined" ? "" : navigator.userAgent);
  const nativeSessionRef = useRef<string | null>(null);
  const handleControlMessageRef = useRef<((raw: string) => Promise<void>) | null>(null);
  const sendInvitationRef = useRef<(() => Promise<void>) | null>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const peerDestinationRef = useRef<string | undefined>(undefined);
  const channelRef = useRef<RTCDataChannel | null>(null);
  const controlRef = useRef<RTCDataChannel | null>(null);
  const contactInvitationIdRef = useRef("");
  const roleRef = useRef<"offer" | "join" | null>(null);
  const invitationStartedRef = useRef(false);
  const createOfferBusyRef = useRef(false);
  const reviewOfferBusyRef = useRef(false);
  const connectAnswerBusyRef = useRef(false);
  const bridgeRef = useRef<WebRTCBridge | null>(null);
  const attachmentRef = useRef<RTCDataChannel | null>(null);
  const handedOffRef = useRef(false);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const iceSummaryRef = useRef<Record<string, unknown> | null>(null);
  const failureCapturedRef = useRef(false);
  const traceRef = useRef<PeerTrace | null>(null);
  const answerWaitRef = useRef<{ pc: RTCPeerConnection; timer: number } | null>(null);
  const attemptRef = useRef(0);

  const stopAnswerWait = useCallback(() => {
    if (answerWaitRef.current) window.clearTimeout(answerWaitRef.current.timer);
    answerWaitRef.current = null;
  }, []);

  const sendControlText = useCallback(async (text: string): Promise<boolean> => {
    if (nativeMode) {
      const sessionId = nativeSessionRef.current;
      if (!sessionId) return false;
      try {
        const result = await nativeWebRTCControl(sessionId, "mesh-onboarding", text);
        return result.accepted;
      } catch {
        return false;
      }
    }
    const control = controlRef.current;
    if (!control || control.readyState !== "open") return false;
    try {
      control.send(text);
      return true;
    } catch {
      return false;
    }
  }, [nativeMode]);

  const waitNativeOpen = useCallback(async (sessionId: string, timeoutMs = 20_000): Promise<void> => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (nativeSessionRef.current !== sessionId) throw new Error("Native WebRTC pairing was cancelled.");
      try {
        const stats = await nativeWebRTCStats(sessionId);
        if (stats.attached && nativeSessionRef.current === sessionId) return;
      } catch {
        // Native session or Python bridge is still starting.
      }
      await new Promise((resolve) => window.setTimeout(resolve, 250));
    }
    throw new Error("The native WebRTC DataChannel did not open.");
  }, []);

  const captureDiagnostics = useCallback(async (phase: string, message: string): Promise<string> => {
    const nativeSession = nativeMode ? nativeSessionRef.current : null;
    const attempt = attemptRef.current;
    const context = failureContextRef.current ?? {};
    const save = (detail: Record<string, unknown>) => {
      const text = JSON.stringify({ phase, message, ...context, ...detail }, null, 2);
      if (attemptRef.current === attempt) {
        setDiagnostics(text);
        rememberWebRTCDiagnostics(text);
      }
      return text;
    };
    if (nativeMode) {
      const detail = { native: true, native_session: nativeSession ? "requested" : "not_requested" };
      // Save a useful report before any optional stats query can fail or yield
      // to cleanup. A native session is independent of the browser's pcRef.
      const fallback = save({ ...detail, native_stats: "unavailable" });
      if (!nativeSession) return fallback;
      try {
        const stats = await nativeWebRTCStats(nativeSession);
        return save({ ...detail, native_stats: "available", ...stats });
      } catch (reason) {
        return save({ ...detail, native_stats: "unavailable", native_stats_error: diagnosticErrorCode(reason) });
      }
    }
    const pc = pcRef.current;
    if (!pc) {
      // ICE configuration can fail before a peer connection exists. Preserve
      // that failure so the error screen still has something useful to copy.
      const host = await desktopServiceHealth().catch(() => null);
      return save({ peer_connection: "not_created", desktop_service: host });
    }
    const trace = traceRef.current;
    try {
      const detail = await peerDiagnostics(pc, phase, message, iceSummaryRef.current);
      const text = JSON.stringify({ ...JSON.parse(detail), ...context, timeline: trace?.snapshot() ?? [] }, null, 2);
      if (pcRef.current !== pc) return text;
      setDiagnostics(text);
      rememberWebRTCDiagnostics(text);
      return text;
    } catch {
      return "";
    }
  }, [nativeMode]);

  const cleanup = useCallback(() => {
    attemptRef.current += 1;
    answerFetchRef.current += 1;
    answerFetchBusyRef.current = false;
    setFetchingAnswer(false);
    capabilityRequestPendingRef.current = false;
    stopAnswerWait();
    traceRef.current?.stop();
    traceRef.current = null;
    const nativeSession = nativeSessionRef.current;
    nativeSessionRef.current = null;
    if (nativeSession) void nativeWebRTCClose(nativeSession).catch(() => undefined);
    const bridge = bridgeRef.current;
    const channel = channelRef.current;
    const control = controlRef.current;
    const pc = pcRef.current;
    // Retire ownership before close events or pending async work can run.
    bridgeRef.current = null;
    attachmentRef.current = null;
    channelRef.current = null;
    controlRef.current = null;
    pcRef.current = null;
    peerDestinationRef.current = undefined;
    if (pc) pc.onconnectionstatechange = pc.oniceconnectionstatechange = pc.ondatachannel = null;
    if (channel) channel.onopen = channel.onclose = channel.onerror = null;
    if (control) control.onopen = control.onclose = control.onmessage = null;
    void bridge?.close().catch(() => undefined);
    channel?.close();
    control?.close();
    pc?.close();
  }, [stopAnswerWait]);

  const reportFailure = useCallback((phase: string, message: string) => {
    if (failureCapturedRef.current) return;
    if (nativeMode && nativeSessionRef.current) {
      const sessionId = nativeSessionRef.current;
      failureCapturedRef.current = true;
      void captureDiagnostics(phase, message).finally(() => {
        if (nativeSessionRef.current !== sessionId) return;
        setError(message);
        setPhase("error");
        cleanup();
      });
      return;
    }
    const pc = pcRef.current;
    if (!pc) return;
    failureCapturedRef.current = true;
    // Capture while the peer connection still exists. Cleanup closes it and
    // would otherwise erase remote candidates and candidate-pair state.
    void captureDiagnostics(phase, message).finally(() => {
      if (pcRef.current !== pc) return;
      setError(message);
      setPhase("error");
      cleanup();
    });
  }, [captureDiagnostics, cleanup, nativeMode]);

  useEffect(() => () => {
    if (!handedOffRef.current) cleanup();
    else traceRef.current?.stop();
  }, [cleanup]);

  useEffect(() => {
    if (!nativeMode) return;
    let active = true;
    let unlisten: (() => void) | null = null;
    void onServiceEvent((event: ServiceEvent) => {
      if (!active || event.session_id !== nativeSessionRef.current) return;
      if (event.event === "webrtc_control" && event.label === "mesh-onboarding" && typeof event.data === "string") {
        void handleControlMessageRef.current?.(event.data);
      }
      if (event.event === "webrtc_control_open") {
        void sendInvitationRef.current?.();
      }
    }).then((stop) => {
      if (active) unlisten = stop;
      else stop();
    }).catch(() => undefined);
    return () => {
      active = false;
      unlisten?.();
    };
  }, [nativeMode]);

  useEffect(() => {
    void serviceCommand<CallSettings>("call_settings")
      .then(setRelaySettings)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const onApproval = (event: Event) => {
      if (roleRef.current !== "offer") return;
      const detail = (event as CustomEvent<{ approved?: boolean; destination?: string }>).detail;
      if (!peerDestinationRef.current || detail?.destination !== peerDestinationRef.current) return;
      const approved = Boolean(detail?.approved);
      if (approved) clearPairingResume();
      const bridge = bridgeRef.current;
      if (bridge) updateWebRTCSessionApprovalPending(false, `onboarding:${bridge.bridgeId}`);
      setOnboarding(approved ? "approved" : "declined");
    };
    window.addEventListener("meshchat:approval", onApproval);
    return () => window.removeEventListener("meshchat:approval", onApproval);
  }, []);

  useEffect(() => {
    if (initialPairingCode && !pcRef.current) {
      savePairingResume(initialPairingCode, "answer");
      setOfferInput(initialPairingCode);
      setPhase("review");
    }
  }, [initialPairingCode]);

  useEffect(() => {
    if (!shouldAutoCloseWebRTCOnboarding(phase, onboarding, handedOffRef.current)) return;
    // The global WebRTC banner is the durable status surface once the session
    // is connected and pending work is handed off.
    const timer = window.setTimeout(() => onCloseRef.current(), 1500);
    return () => window.clearTimeout(timer);
  }, [onboarding, phase]);

  const relayEnabled = Boolean(
    relaySettings?.turn_configured ||
      (relaySettings?.turn_broker_configured && relaySettings.turn_broker_consent),
  );
  const pathFailureMessage = relayEnabled
    ? "The WebRTC network path failed even though TURN is configured. Copy diagnostics and verify that relay candidates were gathered and that the TURN host is reachable from this network."
    : "The WebRTC network path failed. On Wi-Fi, check client isolation and Windows Firewall. If the access point isolates clients, configure TURN.";

  useEffect(() => {
    if (phase !== "connecting") return;
    const timer = window.setTimeout(() => {
      reportFailure("timeout", pathFailureMessage);
    }, 30000);
    return () => window.clearTimeout(timer);
  }, [pathFailureMessage, phase, reportFailure]);

  const sendInvitation = useCallback(async () => {
    if (roleRef.current !== "offer" || invitationStartedRef.current) return;
    if (nativeMode) {
      if (!nativeSessionRef.current) return;
    } else {
      if (!bridgeRef.current || !channelRef.current || channelRef.current.readyState !== "open") return;
    }
    invitationStartedRef.current = true;
    const attempt = attemptRef.current;
    setOnboarding("sending");
    setOnboardingError("");
    try {
      const created = await serviceCommand<InvitationFormats>("create_invitation", { connection_mode: "webrtc" });
      if (attemptRef.current !== attempt) return;
      let workspaceDocument: string | undefined;
      if (selectedWorkspaceId) {
        const workspace = await serviceCommand<WorkspaceInvitationFormats>("create_workspace_invitation", {
          operation_id: crypto.randomUUID(),
          workspace_id: selectedWorkspaceId,
          lifetime_days: 7,
          connection_mode: "webrtc",
        });
        workspaceDocument = workspace.value;
      }
      if (attemptRef.current !== attempt) return;
      if (!(await sendControlText(JSON.stringify({ type: "contact_invitation", document: created.file, workspace_document: workspaceDocument })))) {
        throw new Error("The native control channel is not open.");
      }
      setOnboarding("sent");
    } catch (reason) {
      invitationStartedRef.current = false;
      setOnboardingError(errorMessage(reason));
      setOnboarding("error");
    }
  }, [nativeMode, selectedWorkspaceId, sendControlText]);
  sendInvitationRef.current = sendInvitation;

  const handleControlMessage = useCallback(async (raw: string) => {
    const control = controlRef.current;
    const attempt = attemptRef.current;
    const current = () => nativeMode
      ? attemptRef.current === attempt && nativeSessionRef.current !== null
      : control !== null && controlRef.current === control &&
        control.readyState === "open" && attemptRef.current === attempt;
    if (!current()) return;
    let message: ControlMessage;
    try {
      message = JSON.parse(raw) as ControlMessage;
    } catch {
      return;
    }
    if (message.type === "contact_invitation" && roleRef.current === "join") {
      if (typeof message.document !== "string" || !message.document) return;
      try {
        const saved = await serviceCommand<ContactInvitation>("receive_contact_invitation", {
          document: message.document,
          peer_destination: peerDestinationRef.current,
          ...(typeof message.workspace_document === "string" && message.workspace_document
            ? { workspace_document: message.workspace_document } : {}),
        });
        await onChanged();
        if (!current()) return;
        if (saved.state !== "pending") {
          setOnboarding(saved.state === "accepted" ? "waiting-approval" : "declined");
          return;
        }
        contactInvitationIdRef.current = saved.id;
        setContactInvitation(saved.preview);
        setWorkspaceInvitation(saved.workspace);
        setOnboardingError("");
        setOnboarding("preview");
      } catch (reason) {
        if (!current()) return;
        setOnboardingError(errorMessage(reason));
        setOnboarding("error");
      }
    } else if (message.type === "invitation_accepted" && roleRef.current === "offer") {
      const bridge = bridgeRef.current;
      const sessionKey = bridge ? `onboarding:${bridge.bridgeId}` : null;
      if (typeof message.capabilities === "string" && message.capabilities) {
        // The joiner's signed capability arrives with its acceptance. The
        // service holds it until approval if the contact request has not
        // arrived yet; storing it never approves the contact.
        const stored = await storeReconnectCapabilities(message.capabilities, sessionKey ? getWebRTCSessionByKey(sessionKey)?.contactId : undefined, peerDestinationRef.current).catch(() => undefined);
        if (!current()) return;
        if (stored?.profile?.contact_id && sessionKey) {
          updateWebRTCSessionContact(stored.profile.contact_id, sessionKey);
        }
      }
      if (sessionKey) updateWebRTCSessionApprovalPending(true, sessionKey);
      setOnboarding("waiting-approval");
      await onChanged();
    } else if (message.type === "invitation_approved" && roleRef.current === "join") {
      if (typeof message.capabilities === "string" && message.capabilities) {
        const bridge = bridgeRef.current;
        const contactId = bridge ? getWebRTCSessionByKey(`onboarding:${bridge.bridgeId}`)?.contactId : undefined;
        await storeReconnectCapabilities(message.capabilities, contactId, peerDestinationRef.current).catch(() => undefined);
        if (!current()) return;
      }
      clearPairingResume();
      setOnboarding("approved");
      await onChanged();
    } else if (message.type === "invitation_denied" && roleRef.current === "join") {
      setOnboarding("declined");
    } else if (message.type === "connection_capabilities") {
      if (typeof message.document === "string" && message.document) {
        const bridge = bridgeRef.current;
        const contactId = bridge ? getWebRTCSessionByKey(`onboarding:${bridge.bridgeId}`)?.contactId : undefined;
        const stored = await storeReconnectCapabilities(message.document, contactId, peerDestinationRef.current).catch(() => undefined);
        if (current() && bridge && stored?.profile?.contact_id) {
          updateWebRTCSessionContact(stored.profile.contact_id, `onboarding:${bridge.bridgeId}`);
        }
      }
    } else if (message.type === "connection_capabilities_request") {
      const bridge = bridgeRef.current;
      const session = bridge ? getWebRTCSessionByKey(`onboarding:${bridge.bridgeId}`) : null;
      if (session) {
        capabilityRequestPendingRef.current = false;
        await resendReconnectCapabilities(session);
      } else capabilityRequestPendingRef.current = true;
    } else if (message.type === "invitation_declined" && roleRef.current === "offer") {
      const bridge = bridgeRef.current;
      if (bridge) updateWebRTCSessionApprovalPending(false, `onboarding:${bridge.bridgeId}`);
      setOnboarding("declined");
    }
  }, [nativeMode, onChanged]);
  handleControlMessageRef.current = handleControlMessage;

  const setupControl = useCallback((control: RTCDataChannel) => {
    controlRef.current = control;
    const bridge = bridgeRef.current;
    const session = bridge ? getWebRTCSessionByKey(`onboarding:${bridge.bridgeId}`) : null;
    // The two incoming DataChannels can open in either order. A transport
    // already handed to the registry must gain its late control channel too.
    if (session && session.pc === pcRef.current) {
      session.control = control;
      setWebRTCSession(session);
    }
    control.onopen = () => { void sendInvitation(); };
    control.onmessage = (event) => {
      if (typeof event.data === "string") void handleControlMessage(event.data);
    };
    control.onclose = () => {
      if (onboarding === "preview") setOnboarding("error");
    };
    if (control.readyState === "open") void sendInvitation();
  }, [handleControlMessage, onboarding, sendInvitation]);

  const attach = useCallback(async (channel: RTCDataChannel) => {
    if (channelRef.current !== channel) return;
    const pc = pcRef.current;
    if (!pc || attachmentRef.current === channel) return;
    attachmentRef.current = channel;
    stopAnswerWait();
    traceRef.current?.record("datachannel-open");
    try {
      await waitForOpen(channel);
      if (pcRef.current !== pc) return;
      const bridge = await attachWebRTCBridge(channel, { isCurrent: () => pcRef.current === pc, peerDestination: () => peerDestinationRef.current, onError: (reason) => { setError(errorMessage(reason)); setPhase("error"); }, onClosed: (bridgeId) => removeWebRTCSession(`onboarding:${bridgeId}`) });
      if (pcRef.current !== pc) {
        await bridge.close();
        return;
      }
      bridgeRef.current = bridge;
      if (pc) {
        const path = await connectionPath(pc);
        if (pcRef.current !== pc) return;
        if (channel.readyState !== "open") throw new Error("The DataChannel closed before the connection completed.");
        setWebRTCSession({ key: `onboarding:${bridge.bridgeId}`, bridge, channel, pc, control: controlRef.current, controlPurpose: "onboarding", peerDestination: peerDestinationRef.current, path, createdAt: Date.now(), approvalPending: false });
        if (capabilityRequestPendingRef.current) void handleControlMessageRef.current?.('{"type":"connection_capabilities_request"}');
        handedOffRef.current = true;
        onConnected?.(path);
      }
      setPhase("connected");
      void sendInvitation();
      // Snapshot refreshes do not own the transport handed to the registry.
      await onChanged().catch(() => undefined);
    } catch (reason) {
      if (pcRef.current !== pc) return;
      const message = errorMessage(reason);
      void captureDiagnostics("attach-failed", message);
      setError(message);
      setPhase("error");
      cleanup();
    }
  }, [captureDiagnostics, cleanup, onChanged, onConnected, sendInvitation, stopAnswerWait]);

  const watchPeer = useCallback((pc: RTCPeerConnection) => {
    traceRef.current = startPeerTrace(pc);
    const failed = () => {
      if (pcRef.current !== pc) return;
      if (answerWaitRef.current?.pc === pc) {
        traceRef.current?.record("ice-failed-awaiting-answer-exchange");
        return;
      }
      reportFailure("ice-failed", pathFailureMessage);
    };
    pc.onconnectionstatechange = () => {
      if (pc.connectionState === "failed") failed();
    };
    pc.oniceconnectionstatechange = () => {
      if (pc.iceConnectionState === "failed") failed();
    };
  }, [pathFailureMessage, reportFailure]);

  const copy = useCallback(async (value: string, label: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(label);
      window.setTimeout(() => setCopied(""), 1500);
    } catch {
      setError("Could not copy. Select the text and copy it manually.");
    }
  }, []);

  const createOffer = useCallback(async () => {
    if (createOfferBusyRef.current) return;
    failureContextRef.current = null;
    cleanup();
    handedOffRef.current = false;
    invitationStartedRef.current = false;
    const attempt = attemptRef.current;
    createOfferBusyRef.current = true;
    failureCapturedRef.current = false;
    setMailboxCode("");
    setOfferDocument("");
    setError(""); setPhase("creating");
    setAnswerInput(""); setAnswerDocument(""); setAnswerPreview(null);
    setDiagnostics("");
    try {
      const ice = await serviceCommand<CallIceConfiguration>("call_ice_servers");
      if (attemptRef.current !== attempt) return;
      iceSummaryRef.current = summarizeIce(ice);
      if (nativeMode) {
        roleRef.current = "offer";
        const sessionId = `onboarding-${crypto.randomUUID()}`;
        nativeSessionRef.current = sessionId;
        const native = await nativeWebRTCOffer(sessionId, ice, NATIVE_ONBOARDING_CHANNELS);
        if (attemptRef.current !== attempt) return;
        const sdp = withEndOfCandidates(native.sdp);
        const result = await serviceCommand<OnboardingOfferResult>("webrtc_onboarding_offer", {
          sdp,
          dtls_fingerprint: native.fingerprint || fingerprint(sdp),
        });
        if (attemptRef.current !== attempt) return;
        setOfferDocument(result.document);
        if (relaySettings?.signal_mailbox_url) {
          try {
            const published = await serviceCommand<{ session_id: string }>("signal_publish", { document: result.document, role: "offer" });
            if (attemptRef.current !== attempt) return;
            setMailboxCode(published.session_id);
            savePairingResume(published.session_id, "offer");
          } catch {
            // The signed offer remains usable without the mailbox.
          }
        }
        setPhase("waiting-answer");
        return;
      }
      const pc = new RTCPeerConnection({ iceServers: ice.iceServers, iceTransportPolicy: ice.iceTransportPolicy });
      roleRef.current = "offer";
      const channel = pc.createDataChannel("mesh-reticulum", { ordered: true });
      channel.binaryType = "arraybuffer";
      channel.onopen = () => { void attach(channel); };
      channel.onclose = () => {
        if (pcRef.current !== pc) return;
        if (!handedOffRef.current) reportFailure("channel-closed", "The WebRTC DataChannel closed before the connection completed.");
        else cleanup();
      };
      channel.onerror = () => { setError("The DataChannel failed."); setPhase("error"); };
      const control = pc.createDataChannel("mesh-onboarding", { ordered: true });
      setupControl(control);
      pcRef.current = pc;
      channelRef.current = channel;
      watchPeer(pc);
      const offer = await pc.createOffer();
      if (pcRef.current !== pc) return;
      await pc.setLocalDescription(offer);
      await waitForCandidates(pc);
      if (pcRef.current !== pc) return;
      const gathered = pc.localDescription?.sdp;
      if (!gathered) throw new Error("Could not create the WebRTC offer.");
      const sdp = withEndOfCandidates(gathered);
      const result = await serviceCommand<OnboardingOfferResult>("webrtc_onboarding_offer", {
        sdp,
        dtls_fingerprint: fingerprint(sdp),
      });
      if (pcRef.current !== pc) return;
      traceRef.current?.record("signed-offer-ready");
      setOfferDocument(result.document);
      if (relaySettings?.signal_mailbox_url) {
        try {
          const published = await serviceCommand<{ session_id: string }>("signal_publish", { document: result.document, role: "offer" });
          if (pcRef.current !== pc) return;
          setMailboxCode(published.session_id);
          savePairingResume(published.session_id, "offer");
        } catch {
          // The full signed offer remains usable; the mailbox is optional.
        }
      }
      if (pcRef.current !== pc) return;
      setPhase("waiting-answer");
    } catch (reason) {
      if (attemptRef.current !== attempt) return;
      const message = errorMessage(reason);
      void captureDiagnostics("offer-failed", message).finally(() => {
        if (attemptRef.current === attempt) cleanup();
      });
      setError(message);
      setPhase("error");
    } finally {
      createOfferBusyRef.current = false;
    }
  }, [attach, captureDiagnostics, cleanup, nativeMode, relaySettings, reportFailure, setupControl, watchPeer]);

  const connectAnswer = useCallback(async () => {
    if (connectAnswerBusyRef.current) return;
    failureContextRef.current = null;
    connectAnswerBusyRef.current = true;
    failureCapturedRef.current = false;
    setError(""); setPhase("connecting");
    const pc = pcRef.current;
    const attempt = attemptRef.current;
    try {
      if (nativeMode) {
        const sessionId = nativeSessionRef.current;
        if (!sessionId || !offerDocument) throw new Error("Create an offer first.");
        let localOffer: { session_id?: unknown } = {};
        let answerValue: { type?: unknown; session_id?: unknown; offer_digest?: unknown } = {};
        try {
          localOffer = JSON.parse(offerDocument) as { session_id?: unknown };
          answerValue = JSON.parse(answerInput.trim()) as { type?: unknown; session_id?: unknown; offer_digest?: unknown };
        } catch {
          throw new Error("The answer is not valid JSON. Copy the complete signed answer.");
        }
        if (answerValue.type !== "webrtc_onboarding_answer") {
          throw new Error("That document is not a WebRTC answer. On the other device, choose Join with WebRTC, paste the offer, and copy the answer it creates.");
        }
        if (answerValue.session_id !== localOffer.session_id) {
          throw new Error(`This answer is for session ${String(answerValue.session_id ?? "?").slice(0, 8)}, but the current offer is ${String(localOffer.session_id ?? "?").slice(0, 8)}. Generate a new answer from the current offer.`);
        }
        if (answerValue.offer_digest !== await sha256Hex(offerDocument)) {
          throw new Error("This answer binds a different offer digest. The offer was regenerated; generate a new answer from the current offer.");
        }
        const preview = await serviceCommand<OnboardingAnswerPreview>("verify_webrtc_onboarding_answer", {
          offer_document: offerDocument,
          answer_document: answerInput.trim(),
        });
        if (attemptRef.current !== attempt) return;
        peerDestinationRef.current = preview.signer_destination;
        setAnswerPreview(preview);
        await serviceCommand("native_webrtc_bind_onboarding", {
          session_id: sessionId, offer_document: offerDocument, answer_document: answerInput.trim(),
        });
        if (nativeSessionRef.current !== sessionId) return;
        await nativeWebRTCApplyAnswer(sessionId, preview.sdp);
        await waitNativeOpen(sessionId);
        if (nativeSessionRef.current !== sessionId) return;
        handedOffRef.current = true;
        void sendInvitationRef.current?.();
        onConnected?.("unknown");
        setPhase("connected");
        await onChanged().catch(() => undefined);
        return;
      }
      if (!pc || !offerDocument) throw new Error("Create an offer first.");
      let localOffer: { session_id?: unknown } = {};
      let answerValue: { type?: unknown; session_id?: unknown; offer_digest?: unknown } = {};
      try {
        localOffer = JSON.parse(offerDocument) as { session_id?: unknown };
        answerValue = JSON.parse(answerInput.trim()) as { type?: unknown; session_id?: unknown; offer_digest?: unknown };
      } catch {
        throw new Error("The answer is not valid JSON. Copy the complete signed answer.");
      }
      if (answerValue.type !== "webrtc_onboarding_answer") {
        throw new Error("That document is not a WebRTC answer. On the other device, choose Join with WebRTC, paste the offer, and copy the answer it creates.");
      }
      if (answerValue.session_id !== localOffer.session_id) {
        throw new Error(`This answer is for session ${String(answerValue.session_id ?? "?").slice(0, 8)}, but the current offer is ${String(localOffer.session_id ?? "?").slice(0, 8)}. Generate a new answer from the current offer.`);
      }
      if (answerValue.offer_digest !== await sha256Hex(offerDocument)) {
        throw new Error("This answer binds a different offer digest. The offer was regenerated; generate a new answer from the current offer.");
      }
      const preview = await serviceCommand<OnboardingAnswerPreview>("verify_webrtc_onboarding_answer", {
        offer_document: offerDocument,
        answer_document: answerInput.trim(),
      });
      if (pcRef.current !== pc) return;
      peerDestinationRef.current = preview.signer_destination;
      const bridge = bridgeRef.current;
      const session = bridge ? getWebRTCSessionByKey(`onboarding:${bridge.bridgeId}`) : null;
      if (session?.pc === pc) {
        session.peerDestination = preview.signer_destination;
        setWebRTCSession(session);
      }
      setAnswerPreview(preview);
      traceRef.current?.record("applying-remote-answer");
      await pc.setRemoteDescription({ type: "answer", sdp: preview.sdp });
      if (pcRef.current !== pc) return;
      traceRef.current?.record("remote-answer-applied");
      if (channelRef.current?.readyState === "open") await attach(channelRef.current);
    } catch (reason) {
      if (nativeMode) {
        if (attemptRef.current !== attempt) return;
        const message = answerErrorMessage(reason);
        void captureDiagnostics("answer-failed", message);
        setError(message);
        setPhase("error");
        cleanup();
        return;
      }
      if (pcRef.current !== pc) return;
      const message = answerErrorMessage(reason);
      void captureDiagnostics("answer-failed", message);
      setError(message);
      setPhase("error");
    } finally {
      connectAnswerBusyRef.current = false;
    }
  }, [answerInput, attach, captureDiagnostics, cleanup, nativeMode, offerDocument, waitNativeOpen]);

  const reviewOffer = useCallback(async () => {
    if (reviewOfferBusyRef.current) return;
    cleanup();
    handedOffRef.current = false;
    invitationStartedRef.current = false;
    const attempt = attemptRef.current;
    reviewOfferBusyRef.current = true;
    failureCapturedRef.current = false;
    setReviewBusy(true);
    setMailboxCode("");
    setError(""); setPhase("review");
    setDiagnostics("");
    failureContextRef.current = null;
    let offerVerified = false;
    let operation = "parse_offer";
    try {
      let rawOffer = normalizeWebRTCOfferInput(offerInput);
      if (!rawOffer.includes("\"type\"")) {
        operation = "signal_fetch";
        const fetched = await serviceCommand<{ document: string }>("signal_fetch", { session_id: rawOffer, role: "offer" });
        if (attemptRef.current !== attempt) return;
        rawOffer = fetched.document;
        setOfferInput(rawOffer);
      }
      let parsedOffer: { type?: unknown } = {};
      try {
        parsedOffer = JSON.parse(rawOffer) as { type?: unknown };
      } catch {
        throw new Error("The offer is not valid JSON. Copy the complete signed offer or paste the pairing code.");
      }
      if (parsedOffer.type !== "webrtc_onboarding_offer") {
        throw new Error("That document is not a WebRTC offer. Paste the offer created on the other device, not an answer.");
      }
      operation = "verify_webrtc_onboarding_offer";
      const preview = await serviceCommand<OnboardingOfferPreview>("verify_webrtc_onboarding_offer", {
        document: rawOffer,
      });
      if (attemptRef.current !== attempt) return;
      offerVerified = true;
      peerDestinationRef.current = preview.signer_destination;
      setOfferPreview(preview);
      operation = "call_ice_servers";
      const ice = await serviceCommand<CallIceConfiguration>("call_ice_servers");
      if (attemptRef.current !== attempt) return;
      iceSummaryRef.current = summarizeIce(ice);
      if (nativeMode) {
        roleRef.current = "join";
        const sessionId = `onboarding-${crypto.randomUUID()}`;
        nativeSessionRef.current = sessionId;
        operation = "native_webrtc_accept";
        const native = await nativeWebRTCAccept(sessionId, preview.sdp, ice, NATIVE_ONBOARDING_CHANNELS);
        if (attemptRef.current !== attempt) return;
        operation = "native_webrtc_bind_onboarding";
        await serviceCommand("native_webrtc_bind_onboarding", { session_id: sessionId, offer_document: preview.document });
        if (attemptRef.current !== attempt) return;
        const sdp = withEndOfCandidates(native.sdp);
        operation = "webrtc_onboarding_answer";
        const result = await serviceCommand<OnboardingAnswerResult>("webrtc_onboarding_answer", {
          offer_document: preview.document,
          sdp,
          dtls_fingerprint: native.fingerprint || fingerprint(sdp),
        });
        if (attemptRef.current !== attempt) return;
        setOfferDocument(rawOffer);
        setAnswerDocument(result.document);
        setAnswerPreview({ ...preview, sdp, dtls_fingerprint: native.fingerprint || fingerprint(sdp), document: result.document });
        if (relaySettings?.signal_mailbox_url) {
          try {
            const published = await serviceCommand<{ session_id: string }>("signal_publish", { document: result.document, role: "answer" });
            if (attemptRef.current !== attempt) return;
            setMailboxCode(published.session_id);
            savePairingResume(published.session_id, "answer");
          } catch {
            // The signed answer remains usable without the mailbox.
          }
        }
        setPhase("waiting-owner");
        void waitNativeOpen(sessionId, 120_000).then(async () => {
          if (attemptRef.current !== attempt) return;
          handedOffRef.current = true;
          onConnected?.("unknown");
          setPhase("connected");
          await onChanged().catch(() => undefined);
        }).catch((reason) => {
          if (attemptRef.current !== attempt) return;
          setError(errorMessage(reason));
          setPhase("error");
          cleanup();
        });
        return;
      }
      operation = "create_peer_connection";
      const pc = new RTCPeerConnection({ iceServers: ice.iceServers, iceTransportPolicy: ice.iceTransportPolicy });
      roleRef.current = "join";
      pc.ondatachannel = (event) => {
        if (pcRef.current !== pc) return;
        const channel = event.channel;
        if (channel.label === "mesh-onboarding") {
          setupControl(channel);
          return;
        }
        if (channel.label !== "mesh-reticulum") return;
        channel.binaryType = "arraybuffer";
        channelRef.current = channel;
        channel.onopen = () => { void attach(channel); };
        channel.onclose = () => {
          if (pcRef.current !== pc) return;
          if (!handedOffRef.current) reportFailure("channel-closed", "The WebRTC DataChannel closed before the connection completed.");
          else cleanup();
        };
        channel.onerror = () => { setError("The DataChannel failed."); setPhase("error"); };
      };
      pcRef.current = pc;
      watchPeer(pc);
      const waitMs = Math.max(0, Math.min(ANSWER_EXCHANGE_TIMEOUT_MS, preview.expires_at * 1000 - Date.now()));
      answerWaitRef.current = {
        pc,
        timer: window.setTimeout(() => {
          if (pcRef.current !== pc) return;
          stopAnswerWait();
          reportFailure("answer-exchange-timeout", "The answer exchange did not connect in time. Create a fresh offer, return the answer, and press Connect on the offerer's device while keeping both windows open.");
        }, waitMs),
      };
      traceRef.current?.record("applying-remote-offer");
      operation = "set_remote_offer";
      await pc.setRemoteDescription({ type: "offer", sdp: preview.sdp });
      if (pcRef.current !== pc) return;
      traceRef.current?.record("remote-offer-applied");
      operation = "create_answer";
      const answer = await pc.createAnswer();
      if (pcRef.current !== pc) return;
      operation = "set_local_answer";
      await pc.setLocalDescription(answer);
      operation = "gather_answer_candidates";
      await waitForCandidates(pc);
      if (pcRef.current !== pc) return;
      const gathered = pc.localDescription?.sdp;
      if (!gathered) throw new Error("Could not create the WebRTC answer.");
      const sdp = withEndOfCandidates(gathered);
      operation = "webrtc_onboarding_answer";
      const result = await serviceCommand<OnboardingAnswerResult>("webrtc_onboarding_answer", {
        offer_document: preview.document,
        sdp,
        dtls_fingerprint: fingerprint(sdp),
      });
      if (pcRef.current !== pc) return;
      traceRef.current?.record("signed-answer-ready");
      setAnswerDocument(result.document);
      if (relaySettings?.signal_mailbox_url) {
        try {
          const published = await serviceCommand<{ session_id: string }>("signal_publish", { document: result.document, role: "answer" });
          if (pcRef.current !== pc) return;
          setMailboxCode(published.session_id);
          savePairingResume(published.session_id, "answer");
        } catch {
          // The full signed answer remains usable; the mailbox is optional.
        }
      }
      if (pcRef.current !== pc) return;
      setOfferDocument(rawOffer);
      setAnswerPreview({ ...preview, sdp, dtls_fingerprint: fingerprint(sdp), document: result.document });
      setPhase("waiting-owner");
    } catch (reason) {
      if (attemptRef.current !== attempt) return;
      failureContextRef.current = { operation, error_code: diagnosticErrorCode(reason), offer_verified: offerVerified };
      const message = offerErrorMessage(reason, offerVerified, operation);
      void captureDiagnostics("offer-review-failed", message).finally(() => {
        if (attemptRef.current === attempt) cleanup();
      });
      setError(message);
      setPhase("error");
    } finally {
      reviewOfferBusyRef.current = false;
      setReviewBusy(false);
    }
  }, [attach, captureDiagnostics, cleanup, nativeMode, offerInput, relaySettings, reportFailure, setupControl, stopAnswerWait, waitNativeOpen, watchPeer]);

  const acceptContact = async () => {
    setOnboardingBusy(true);
    setOnboardingError("");
    try {
      if (!contactInvitationIdRef.current) throw new Error("No contact invitation is available.");
      const accepted = await serviceCommand<{ id?: string; reconnect_capabilities?: string }>(
        "decide_contact_invitation",
        { invitation_id: contactInvitationIdRef.current, accept: true },
      );
      if (accepted.id) updateWebRTCSessionContact(accepted.id, bridgeRef.current ? `onboarding:${bridgeRef.current.bridgeId}` : undefined);
      await sendControlText(JSON.stringify({
        type: "invitation_accepted",
        ...(accepted.reconnect_capabilities
          ? { capabilities: accepted.reconnect_capabilities }
          : {}),
      })).catch(() => undefined);
      setOnboarding("waiting-approval");
      await onChanged();
    } catch (reason) {
      setOnboardingError(errorMessage(reason));
      setOnboarding("error");
    } finally {
      setOnboardingBusy(false);
    }
  };

  const declineContact = async () => {
    setOnboardingBusy(true);
    try {
      await serviceCommand("decide_contact_invitation", { invitation_id: contactInvitationIdRef.current, accept: false });
      await sendControlText(JSON.stringify({ type: "invitation_declined" })).catch(() => undefined);
      setOnboarding("declined");
      await onChanged();
    } catch (reason) {
      setOnboardingError(errorMessage(reason));
    } finally {
      setOnboardingBusy(false);
    }
  };

  const fetchAnswer = async () => {
    const session = mailboxCode;
    if (!session || answerFetchBusyRef.current) return;
    const attempt = attemptRef.current;
    const fetch = ++answerFetchRef.current;
    const current = () => answerFetchRef.current === fetch && attemptRef.current === attempt && phaseRef.current === "waiting-answer";
    answerFetchBusyRef.current = true;
    setFetchingAnswer(true);
    try {
      const fetched = await serviceCommand<{ document: string }>("signal_fetch", { session_id: session, role: "answer" });
      if (!current()) return;
      setAnswerInput(fetched.document);
    } catch (reason) {
      if (!current()) return;
      setError(errorMessage(reason));
      setPhase("error");
    } finally {
      if (answerFetchRef.current === fetch) {
        answerFetchBusyRef.current = false;
        setFetchingAnswer(false);
      }
    }
  };

  const close = () => {
    answerFetchRef.current += 1;
    if (!handedOffRef.current) cleanup();
    else traceRef.current?.stop();
    onClose();
  };

  const copyDiagnostics = async () => {
    const text = diagnostics || await captureDiagnostics(phase, error);
    if (!text) {
      setError("No WebRTC diagnostics are available. The connection may already be closed.");
      return;
    }
    await copy(text, "diagnostics");
  };

  const enableRelay = async () => {
    if (!relaySettings || relayBusy) return;
    setRelayBusy(true);
    setRelayError("");
    try {
      const updated = await serviceCommand<CallSettings>("update_call_settings", {
        stun_urls: relaySettings.stun_urls,
        turn_url: relaySettings.turn_url ?? null,
        turn_username: relaySettings.turn_username ?? null,
        turn_credential: null,
        turn_broker_url: relaySettings.turn_broker_url ?? null,
        turn_broker_consent: true,
        signal_mailbox_url: relaySettings.signal_mailbox_url ?? null,
        relay_only: relaySettings.relay_only,
      });
      setRelaySettings(updated);
    } catch (reason) {
      setRelayError(errorMessage(reason));
    } finally {
      setRelayBusy(false);
    }
  };

  const enableDefaultMailbox = async () => {
    if (!relaySettings?.signal_mailbox_default_url || relayBusy) return;
    const attempt = attemptRef.current;
    setRelayBusy(true);
    setRelayError("");
    try {
      const updated = await serviceCommand<CallSettings>("update_call_settings", {
        stun_urls: relaySettings.stun_urls,
        turn_url: relaySettings.turn_url ?? null,
        turn_username: relaySettings.turn_username ?? null,
        turn_credential: null,
        turn_broker_url: relaySettings.turn_broker_url ?? null,
        turn_broker_consent: relaySettings.turn_broker_consent,
        signal_mailbox_url: relaySettings.signal_mailbox_default_url,
        relay_only: relaySettings.relay_only,
        store_call_signaling: relaySettings.store_call_signaling ?? true,
      });
      if (attemptRef.current !== attempt) return;
      setRelaySettings(updated);
      setError("");
      setPhase("review");
    } catch {
      if (attemptRef.current === attempt) setRelayError("The mailbox setting could not be saved. Try again or enable it in Settings.");
    } finally {
      setRelayBusy(false);
    }
  };

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={close}>
      <section className="dialog dialog--wide webrtc-onboarding" role="dialog" aria-modal="true" aria-labelledby="webrtc-onboarding-title" onMouseDown={(event) => event.stopPropagation()}>
        <div className="dialog__header"><h2 id="webrtc-onboarding-title">Connect with WebRTC</h2><button className="icon-button" onClick={close} aria-label="Close"><X size={20} /></button></div>
        <div className="stack">
          <p className="muted">WebRTC carries Reticulum packets over a direct or relayed DataChannel. The other person must review the signed offer and return a signed answer. This is experimental and does not approve a contact by itself.</p>
          <p className="muted">Create invitation: this device makes the offer. Join with WebRTC: this device pastes an offer. Use only one role per attempt.</p>
          {windowsPlatform && phase === "choose" && <div className="direct-help__note" role="note"><strong>Windows network access</strong><p>If this connection fails, set this Wi-Fi network to Private and allow Mesh Chat plus msedgewebview2.exe on Private networks for UDP and TCP. Then create a fresh offer.</p></div>}
          {phase === "choose" && <>
            {relaySettings?.turn_broker_configured && !relaySettings.turn_broker_consent && <div className="remote-consent">
              <h3>Internet relay is available</h3>
              <p>The built-in community relay can connect devices that cannot reach each other directly. Its operator can see IP addresses, timing, and encrypted traffic; it does not receive message plaintext.</p>
              <div className="dialog-actions"><button className="button button--primary" disabled={relayBusy} onClick={() => void enableRelay()}>{relayBusy ? "Enabling…" : "Use the relay"}</button></div>
              {relayError && <p className="form-error" role="alert">{relayError}</p>}
            </div>}
            {workspaces.length > 0 && <label className="field"><span>Also invite to workspace <small>Optional; the contact invitation is still sent</small></span><select value={selectedWorkspaceId} onChange={(event) => setSelectedWorkspaceId(event.target.value)}><option value="">Personal contact only</option>{workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}</select></label>}
            <div className="dialog-actions"><button className="button button--primary" onClick={() => void createOffer()}><Phone size={17} /> Create WebRTC invitation</button><button className="button button--secondary" onClick={() => { setPhase("review"); setOfferInput(""); }}>Join with WebRTC</button></div>
          </>}
          {phase === "creating" && <p className="direct-host-status" role="status"><RefreshCw size={17} /> Preparing the signed WebRTC offer…</p>}
          {phase === "waiting-answer" && <>
            <h3>Send this offer to the other person</h3>
            <p className="muted">Offer session: <code>{sessionCode(offerDocument)}</code>. The answer must carry the same session.</p>
            {mailboxCode && <div className="remote-consent"><p>Signaling mailbox code: <code>{mailboxCode}</code></p><p className="muted">Give this link or code to the other person instead of the full offer. This device creates one answer per code.</p><div className="dialog-actions"><button className="button button--secondary" onClick={() => void copy(mailboxCode, "code")}>{copied === "code" ? "Copied" : "Copy code"}</button><button className="button button--secondary" onClick={() => void copy(`meshchat://pair/${mailboxCode}`, "link")}>{copied === "link" ? "Copied" : "Copy link"}</button><button className="button button--secondary" disabled={fetchingAnswer} onClick={() => void fetchAnswer()}>{fetchingAnswer ? "Fetching…" : "Fetch answer"}</button></div><WebRTCQrCode key={mailboxCode} value={`meshchat://pair/${mailboxCode}`} size={150} level="M" /></div>}
            <textarea className="webrtc-document" readOnly value={offerDocument} rows={5} aria-label="Signed WebRTC offer" />
            <div className="dialog-actions"><button className="button button--secondary" onClick={() => void copy(offerDocument, "offer")}>{copied === "offer" ? <Check size={17} /> : <Copy size={17} />} {copied === "offer" ? "Copied" : "Copy offer"}</button></div>
            <WebRTCQrCode key={offerDocument} value={offerDocument} />
            <label className="field"><span>Paste their signed answer</span><textarea className="webrtc-document" value={answerInput} onChange={(event) => { answerFetchRef.current += 1; answerFetchBusyRef.current = false; setFetchingAnswer(false); setAnswerInput(event.target.value); }} rows={5} spellCheck={false} /></label>
            <div className="dialog-actions"><button className="button button--primary" disabled={!answerInput.trim()} onClick={() => void connectAnswer()}>Connect</button></div>
          </>}
          {phase === "review" && <>
            <label className="field"><span>Paste the signed WebRTC offer or mailbox code</span><textarea className="webrtc-document" value={offerInput} onChange={(event) => setOfferInput(event.target.value)} rows={5} spellCheck={false} placeholder="MESH-WEBRTC-OFFER... or mailbox code" /></label>
            <div className="dialog-actions"><button className="button button--secondary" onClick={() => setPhase("choose")}>Back</button><button className="button button--primary" disabled={!offerInput.trim() || reviewBusy} onClick={() => void reviewOffer()}>{reviewBusy ? "Creating answer…" : "Review and create answer"}</button></div>
          </>}
          {phase === "waiting-owner" && <>
            <h3>Send this answer back to the offerer</h3>
            <p className="muted">Answer session: <code>{sessionCode(answerDocument)}</code>. It must match the offer session.</p>
            <textarea className="webrtc-document" readOnly value={answerDocument} rows={5} aria-label="Signed WebRTC answer" />
            <div className="dialog-actions"><button className="button button--secondary" onClick={() => void copy(answerDocument, "answer")}>{copied === "answer" ? <Check size={17} /> : <Copy size={17} />} {copied === "answer" ? "Copied" : "Copy answer"}</button></div>
            <WebRTCQrCode key={answerDocument} value={answerDocument} />
            <p className="muted">Keep both windows open. The offerer must paste this answer and press Connect. This device waits up to two minutes from starting the answer, or until the offer expires.</p>
          </>}
          {phase === "connecting" && <><p className="direct-host-status" role="status"><RefreshCw size={17} /> Applying the signed answer and opening the DataChannel…</p><p className="muted">If this takes more than 30 seconds, Mesh Chat will stop and report the likely network cause.</p><div className="dialog-actions"><button className="button button--secondary" onClick={close}>Cancel</button></div></>}
          {phase === "connected" && <>
            <p className="direct-host-status" role="status"><Check size={17} /> WebRTC path connected</p>
            <p className="muted">You can return to saved invitations and approvals from Contact requests in your conversation list.</p>
            <p className="muted">Automatic reconnect is on by default for new approved contacts. When setup is ready, Mesh Chat reconnects quietly when both apps are open and unlocked. Check readiness or turn it off in the contact’s Automatic reconnect settings. Your direct IP and relay choices still apply.</p>
            {onboarding === "preview" && contactInvitation ? <div className="remote-consent">
              <h3>Contact invitation</h3>
              <p><strong>{contactInvitation.display_name}</strong> wants to connect over this WebRTC path.</p>
              {workspaceInvitation && <p>Workspace invitation: <strong>{workspaceInvitation.name}</strong> · {workspaceInvitation.member_count} {workspaceInvitation.member_count === 1 ? "member" : "members"}</p>}
              <p>Fingerprint: <code>{contactInvitation.fingerprint}</code></p>
              <p>This accepts the signed invitation and sends a request. The other person must still approve it. Automatic reconnect is enabled for new approved contacts; existing contact settings are preserved.</p>
              <div className="dialog-actions"><button className="button button--primary" disabled={onboardingBusy} onClick={() => void acceptContact()}>{onboardingBusy ? "Accepting…" : "Accept contact"}</button><button className="button button--secondary" disabled={onboardingBusy} onClick={declineContact}>Decline</button></div>
            </div> : onboarding === "waiting-approval" ? <p className="muted">Contact request sent. Waiting for the other person to approve it. Keep this WebRTC path connected.</p>
              : onboarding === "approved" ? <p className="direct-host-status" role="status"><Check size={17} /> Contact approved. You can start messaging.</p>
                : onboarding === "sent" ? <p className="muted">Signed contact invitation sent. Waiting for the other person to accept it.</p>
                : onboarding === "declined" ? <p className="muted">The contact invitation was declined. No contact was added.</p>
                  : onboarding === "error" ? <p className="form-error" role="alert">{onboardingError}</p>
                    : <p className="muted">Exchanging a signed contact invitation over this WebRTC path. Approval is still required.</p>}
            <div className="dialog-actions"><button className="button button--secondary" onClick={() => void copyDiagnostics()}>{copied === "diagnostics" ? "Copied" : "Copy diagnostics"}</button><button className="button button--primary" onClick={close}>Close</button></div>
          </>}
          {(offerPreview || answerPreview) && phase !== "choose" && <p className="muted">Offers are signed and expire automatically. Destination: <code>{(answerPreview?.signer_destination ?? offerPreview?.signer_destination ?? "").slice(0, 12)}</code>…</p>}
          {phase === "error" && <><p className="form-error" role="alert">{error}</p>{failureContextRef.current?.operation === "signal_fetch" && !relaySettings?.signal_mailbox_url && relaySettings?.signal_mailbox_default_url && <section className="remote-consent"><p>The default mailbox exchanges encrypted connection details so you can connect using a code.</p><button className="button button--primary" disabled={relayBusy} onClick={() => void enableDefaultMailbox()}>{relayBusy ? "Saving…" : "Use default mailbox"}</button>{relayError && <p className="form-error" role="alert">{relayError}</p>}</section>}{windowsPlatform && <div className="direct-help__note" role="note"><strong>Windows firewall checklist</strong><ul>{webRTCWindowsChecklist(roleRef.current).map((item) => <li key={item}>{item}</li>)}</ul><p>Copy diagnostics to see whether any relay candidates or a selected candidate pair were present.</p></div>}<div className="dialog-actions"><button className="button button--secondary" onClick={() => void copyDiagnostics()}>{copied === "diagnostics" ? "Copied" : "Copy diagnostics"}</button>{relaySettings?.turn_broker_configured && !relaySettings.turn_broker_consent && <button className="button button--secondary" disabled={relayBusy} onClick={() => { void enableRelay().then(() => setPhase("choose")); }}>{relayBusy ? "Enabling…" : "Enable relay and retry"}</button>}{onFallback && <button className="button button--secondary" onClick={() => { close(); onFallback(); }}>Use invitation instead</button>}<button className="button button--secondary" onClick={() => setPhase("choose")}>Try again</button><button className="button button--primary" onClick={close}>Close</button></div></>}
        </div>
      </section>
    </div>
  );
}
