import { useCallback, useEffect, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { Check, Copy, Phone, RefreshCw, X } from "lucide-react";

import { serviceCommand } from "./api";
import { attachWebRTCBridge, type WebRTCBridge } from "./webrtc-onboarding";
import { rememberWebRTCDiagnostics } from "./webrtc-diagnostics";
import { setWebRTCSession, type WebRTCSessionPath } from "./webrtc-session";
import type {
  CallIceConfiguration,
  CallSettings,
  InvitationFormats,
  InvitationPreview,
  WorkspaceInvitationFormats,
  WorkspaceInvitationPreview,
} from "./types";

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

type ControlMessage =
  | { type: "contact_invitation"; document: string; workspace_document?: string }
  | { type: "invitation_accepted" }
  | { type: "invitation_declined" }
  | { type: "invitation_approved" }
  | { type: "invitation_denied" };

function fingerprint(sdp: string): string {
  for (const line of sdp.split(/\r?\n/)) {
    if (line.startsWith("a=fingerprint:")) return line.slice("a=fingerprint:".length).trim();
  }
  throw new Error("The offer has no DTLS fingerprint.");
}

function documentType(value: string): string {
  try {
    const parsed = JSON.parse(value) as { type?: unknown };
    return typeof parsed.type === "string" ? parsed.type : "";
  } catch {
    return "";
  }
}

function offerErrorMessage(reason: unknown): string {
  const code = reason && typeof reason === "object" && "code" in reason
    ? String((reason as { code?: unknown }).code ?? "")
    : "";
  if (code === "identity_mismatch") {
    return "The offer signature could not be verified. Copy the complete current offer from the device that created it; if it was regenerated, use the new offer.";
  }
  if (code === "invalid_request") {
    return "This is not a complete signed WebRTC offer. Copy the entire offer document, including its outer JSON braces.";
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

async function waitForCandidates(pc: RTCPeerConnection, timeoutMs = 15000): Promise<void> {
  if (pc.iceGatheringState === "complete") return;
  await new Promise<void>((resolve) => {
    const timeout = window.setTimeout(resolve, timeoutMs);
    const onChange = () => {
      if (pc.iceGatheringState === "complete") {
        window.clearTimeout(timeout);
        pc.removeEventListener("icegatheringstatechange", onChange);
        resolve();
      }
    };
    pc.addEventListener("icegatheringstatechange", onChange);
  });
}

async function connectionPath(pc: RTCPeerConnection): Promise<WebRTCSessionPath> {
  try {
    const stats = await pc.getStats();
    const candidates = new Map<string, string>();
    let selected = "";
    stats.forEach((report) => {
      const value = report as unknown as Record<string, unknown>;
      if (value.type === "local-candidate" || value.type === "remote-candidate") {
        candidates.set(String(value.id), String(value.candidateType ?? ""));
      }
      if (value.type === "transport" && value.selectedCandidatePairId) {
        selected = String(value.selectedCandidatePairId);
      }
      if (value.type === "candidate-pair" && value.nominated === true && value.state === "succeeded" && !selected) {
        selected = String(value.id);
      }
    });
    if (!selected) return "unknown";
    let relayed = false;
    stats.forEach((report) => {
      const value = report as unknown as Record<string, unknown>;
      if (value.type !== "candidate-pair" || String(value.id) !== selected) return;
      const local = candidates.get(String(value.localCandidateId));
      const remote = candidates.get(String(value.remoteCandidateId));
      if (local === "relay" || remote === "relay") relayed = true;
    });
    return relayed ? "relayed" : "direct";
  } catch {
    return "unknown";
  }
}

async function waitForOpen(channel: RTCDataChannel): Promise<void> {
  if (channel.readyState === "open") return;
  await new Promise<void>((resolve, reject) => {
    const timeout = window.setTimeout(() => reject(new Error("The DataChannel did not open.")), 20000);
    channel.addEventListener("open", () => { window.clearTimeout(timeout); resolve(); }, { once: true });
    channel.addEventListener("error", () => { window.clearTimeout(timeout); reject(new Error("The DataChannel failed.")); }, { once: true });
  });
}

function summarizeIce(ice: CallIceConfiguration): Record<string, unknown> {
  const urls = ice.iceServers.flatMap((server) =>
    Array.isArray(server.urls) ? server.urls : [server.urls],
  );
  return {
    transportPolicy: ice.iceTransportPolicy,
    stun: urls.filter((url) => url.startsWith("stun:") || url.startsWith("stuns:")).length,
    turn: urls.filter((url) => url.startsWith("turn:") || url.startsWith("turns:")).length,
    credentialPresent: ice.iceServers.some((server) => Boolean(server.credential)),
  };
}

async function peerDiagnostics(
  pc: RTCPeerConnection,
  phase: string,
  error: string,
  iceSummary: Record<string, unknown> | null,
): Promise<string> {
  const stats = await pc.getStats();
  const candidates = new Map<string, Record<string, unknown>>();
  const pairs: Array<Record<string, unknown>> = [];
  let selectedPairId = "";
  let dataChannel: Record<string, unknown> | null = null;
  stats.forEach((report) => {
    const value = report as unknown as Record<string, unknown>;
    const type = value.type;
    if (type === "local-candidate" || type === "remote-candidate") {
      candidates.set(String(value.id), {
        side: type === "local-candidate" ? "local" : "remote",
        candidateType: value.candidateType,
        protocol: value.protocol,
        relayProtocol: value.relayProtocol,
        networkType: value.networkType,
      });
    } else if (type === "candidate-pair") {
      pairs.push({
        id: value.id,
        state: value.state,
        nominated: value.nominated,
        bytesSent: value.bytesSent,
        bytesReceived: value.bytesReceived,
        localCandidateId: value.localCandidateId,
        remoteCandidateId: value.remoteCandidateId,
      });
    } else if (type === "transport" && value.selectedCandidatePairId) {
      selectedPairId = String(value.selectedCandidatePairId);
    } else if (type === "data-channel") {
      dataChannel = {
        state: value.state,
        messagesSent: value.messagesSent,
        messagesReceived: value.messagesReceived,
        bytesSent: value.bytesSent,
        bytesReceived: value.bytesReceived,
      };
    }
  });
  const selected = pairs.find((pair) => pair.id === selectedPairId)
    ?? pairs.find((pair) => pair.nominated === true && pair.state === "succeeded")
    ?? pairs.find((pair) => pair.state === "succeeded")
    ?? null;
  const selectedPair = selected ? {
    state: selected.state,
    nominated: selected.nominated,
    bytesSent: selected.bytesSent,
    bytesReceived: selected.bytesReceived,
    local: candidates.get(String(selected.localCandidateId)) ?? null,
    remote: candidates.get(String(selected.remoteCandidateId)) ?? null,
  } : null;
  const countCandidates = (sdp?: string) =>
    (sdp?.match(/^a=candidate:/gm) ?? []).length;
  return JSON.stringify({
    timestamp: new Date().toISOString(),
    phase,
    error: error || undefined,
    connectionState: pc.connectionState,
    iceConnectionState: pc.iceConnectionState,
    iceGatheringState: pc.iceGatheringState,
    iceConfiguration: iceSummary,
    localSdpCandidates: countCandidates(pc.localDescription?.sdp),
    remoteSdpCandidates: countCandidates(pc.remoteDescription?.sdp),
    selectedPair,
    candidateTypes: [...new Set([...candidates.values()].map((candidate) => `${candidate.side}:${candidate.candidateType}`))],
    pairStates: pairs.reduce<Record<string, number>>((counts, pair) => {
      const state = String(pair.state ?? "unknown");
      counts[state] = (counts[state] ?? 0) + 1;
      return counts;
    }, {}),
    dataChannel,
  }, null, 2);
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
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const channelRef = useRef<RTCDataChannel | null>(null);
  const controlRef = useRef<RTCDataChannel | null>(null);
  const controlDocumentRef = useRef("");
  const workspaceDocumentRef = useRef("");
  const roleRef = useRef<"offer" | "join" | null>(null);
  const invitationStartedRef = useRef(false);
  const createOfferBusyRef = useRef(false);
  const reviewOfferBusyRef = useRef(false);
  const connectAnswerBusyRef = useRef(false);
  const bridgeRef = useRef<WebRTCBridge | null>(null);
  const handedOffRef = useRef(false);
  const iceSummaryRef = useRef<Record<string, unknown> | null>(null);

  const captureDiagnostics = useCallback(async (phase: string, message: string): Promise<string> => {
    const pc = pcRef.current;
    if (!pc) return "";
    try {
      const text = await peerDiagnostics(pc, phase, message, iceSummaryRef.current);
      setDiagnostics(text);
      rememberWebRTCDiagnostics(text);
      return text;
    } catch {
      return "";
    }
  }, []);

  const cleanup = useCallback(() => {
    void bridgeRef.current?.close().catch(() => undefined);
    bridgeRef.current = null;
    channelRef.current?.close();
    channelRef.current = null;
    pcRef.current?.close();
    pcRef.current = null;
  }, []);

  useEffect(() => () => {
    if (!handedOffRef.current) cleanup();
  }, [cleanup]);

  useEffect(() => {
    void serviceCommand<CallSettings>("call_settings")
      .then(setRelaySettings)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (initialPairingCode) {
      setOfferInput(initialPairingCode);
      setPhase("review");
    }
  }, [initialPairingCode]);

  useEffect(() => {
    if (phase !== "connecting") return;
    const timer = window.setTimeout(() => {
      const message = "The WebRTC path did not open. On Wi-Fi, check that the access point allows client-to-client traffic and that Windows Firewall permits Mesh Chat on private networks. If the network isolates clients, configure TURN.";
      void captureDiagnostics("timeout", message).finally(() => {
        setError(message);
        setPhase("error");
        cleanup();
      });
    }, 30000);
    return () => window.clearTimeout(timer);
  }, [captureDiagnostics, cleanup, phase]);

  const sendInvitation = useCallback(async () => {
    if (roleRef.current !== "offer" || invitationStartedRef.current || !bridgeRef.current) return;
    const control = controlRef.current;
    if (!control || control.readyState !== "open" || !channelRef.current || channelRef.current.readyState !== "open") return;
    invitationStartedRef.current = true;
    setOnboarding("sending");
    setOnboardingError("");
    try {
      const created = await serviceCommand<InvitationFormats>("create_invitation", { connection_mode: "webrtc" });
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
      control.send(JSON.stringify({ type: "contact_invitation", document: created.file, workspace_document: workspaceDocument }));
      setOnboarding("sent");
    } catch (reason) {
      invitationStartedRef.current = false;
      setOnboardingError(errorMessage(reason));
      setOnboarding("error");
    }
  }, [selectedWorkspaceId]);

  const handleControlMessage = useCallback(async (raw: string) => {
    let message: ControlMessage;
    try {
      message = JSON.parse(raw) as ControlMessage;
    } catch {
      return;
    }
    if (message.type === "contact_invitation" && roleRef.current === "join") {
      if (typeof message.document !== "string" || !message.document) return;
      try {
        const preview = await serviceCommand<InvitationPreview>("preview_invitation", { invitation: message.document });
        controlDocumentRef.current = message.document;
        setContactInvitation(preview);
        if (typeof message.workspace_document === "string" && message.workspace_document) {
          const workspace = await serviceCommand<WorkspaceInvitationPreview>("preview_workspace_invitation", {
            invitation: message.workspace_document,
          });
          workspaceDocumentRef.current = message.workspace_document;
          setWorkspaceInvitation(workspace);
        } else {
          workspaceDocumentRef.current = "";
          setWorkspaceInvitation(null);
        }
        setOnboardingError("");
        setOnboarding("preview");
      } catch (reason) {
        setOnboardingError(errorMessage(reason));
        setOnboarding("error");
      }
    } else if (message.type === "invitation_accepted" && roleRef.current === "offer") {
      setOnboarding("waiting-approval");
      await onChanged();
    } else if (message.type === "invitation_approved" && roleRef.current === "join") {
      setOnboarding("approved");
      await onChanged();
    } else if (message.type === "invitation_denied" && roleRef.current === "join") {
      setOnboarding("declined");
    } else if (message.type === "invitation_declined" && roleRef.current === "offer") {
      setOnboarding("declined");
    }
  }, [onChanged]);

  const setupControl = useCallback((control: RTCDataChannel) => {
    controlRef.current = control;
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
    try {
      await waitForOpen(channel);
      const bridge = await attachWebRTCBridge(channel, { onError: (reason) => { setError(errorMessage(reason)); setPhase("error"); } });
      bridgeRef.current = bridge;
      const pc = pcRef.current;
      if (pc) {
        const path = await connectionPath(pc);
        setWebRTCSession({ bridge, channel, pc, control: controlRef.current, path, createdAt: Date.now() });
        handedOffRef.current = true;
        onConnected?.(path);
      }
      setPhase("connected");
      void sendInvitation();
      await onChanged();
    } catch (reason) {
      const message = errorMessage(reason);
      void captureDiagnostics("attach-failed", message);
      setError(message);
      setPhase("error");
      cleanup();
    }
  }, [captureDiagnostics, cleanup, onChanged, onConnected, sendInvitation]);

  const watchPeer = useCallback((pc: RTCPeerConnection) => {
    const failed = () => {
      const message = "The WebRTC network path failed. On Wi-Fi, check client isolation and Windows Firewall. If the access point isolates clients, configure TURN.";
      void captureDiagnostics("ice-failed", message).finally(() => {
        setError(message);
        setPhase("error");
        cleanup();
      });
    };
    pc.onconnectionstatechange = () => {
      if (pc.connectionState === "failed") failed();
    };
    pc.oniceconnectionstatechange = () => {
      if (pc.iceConnectionState === "failed") failed();
    };
  }, [captureDiagnostics, cleanup]);

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
    createOfferBusyRef.current = true;
    setError(""); setPhase("creating");
    setAnswerInput(""); setAnswerDocument(""); setAnswerPreview(null);
    try {
      const ice = await serviceCommand<CallIceConfiguration>("call_ice_servers");
      iceSummaryRef.current = summarizeIce(ice);
      const pc = new RTCPeerConnection({ iceServers: ice.iceServers, iceTransportPolicy: ice.iceTransportPolicy });
      roleRef.current = "offer";
      const channel = pc.createDataChannel("mesh-reticulum", { ordered: true });
      channel.binaryType = "arraybuffer";
      channel.onopen = () => { void attach(channel); };
      channel.onclose = () => cleanup();
      channel.onerror = () => { setError("The DataChannel failed."); setPhase("error"); };
      const control = pc.createDataChannel("mesh-onboarding", { ordered: true });
      setupControl(control);
      pcRef.current = pc;
      channelRef.current = channel;
      watchPeer(pc);
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await waitForCandidates(pc);
      const sdp = pc.localDescription?.sdp;
      if (!sdp) throw new Error("Could not create the WebRTC offer.");
      const result = await serviceCommand<OnboardingOfferResult>("webrtc_onboarding_offer", {
        sdp,
        dtls_fingerprint: fingerprint(sdp),
      });
      setOfferDocument(result.document);
      if (relaySettings?.signal_mailbox_url) {
        const published = await serviceCommand<{ session_id: string }>("signal_publish", { document: result.document, role: "offer" });
        setMailboxCode(published.session_id);
      }
      setPhase("waiting-answer");
    } catch (reason) {
      const message = errorMessage(reason);
      void captureDiagnostics("offer-failed", message).finally(cleanup);
      setError(message);
      setPhase("error");
    } finally {
      createOfferBusyRef.current = false;
    }
  }, [attach, captureDiagnostics, cleanup, relaySettings, setupControl, watchPeer]);

  const connectAnswer = useCallback(async () => {
    if (connectAnswerBusyRef.current) return;
    connectAnswerBusyRef.current = true;
    setError(""); setPhase("connecting");
    try {
      if (!pcRef.current || !offerDocument) throw new Error("Create an offer first.");
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
      setAnswerPreview(preview);
      await pcRef.current.setRemoteDescription({ type: "answer", sdp: preview.sdp });
      if (channelRef.current?.readyState === "open") await attach(channelRef.current);
    } catch (reason) {
      const message = answerErrorMessage(reason);
      void captureDiagnostics("answer-failed", message);
      setError(message);
      setPhase("error");
    } finally {
      connectAnswerBusyRef.current = false;
    }
  }, [answerInput, attach, captureDiagnostics, offerDocument]);

  const reviewOffer = useCallback(async () => {
    if (reviewOfferBusyRef.current) return;
    reviewOfferBusyRef.current = true;
    setReviewBusy(true);
    setError(""); setPhase("review");
    try {
      let rawOffer = offerInput.trim();
      if (!rawOffer.includes("\"type\"")) {
        const fetched = await serviceCommand<{ document: string }>("signal_fetch", { session_id: rawOffer, role: "offer" });
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
      const preview = await serviceCommand<OnboardingOfferPreview>("verify_webrtc_onboarding_offer", {
        document: rawOffer,
      });
      setOfferPreview(preview);
      const ice = await serviceCommand<CallIceConfiguration>("call_ice_servers");
      iceSummaryRef.current = summarizeIce(ice);
      const pc = new RTCPeerConnection({ iceServers: ice.iceServers, iceTransportPolicy: ice.iceTransportPolicy });
      roleRef.current = "join";
      pc.ondatachannel = (event) => {
        const channel = event.channel;
        if (channel.label === "mesh-onboarding") {
          setupControl(channel);
          return;
        }
        if (channel.label !== "mesh-reticulum") return;
        channel.binaryType = "arraybuffer";
        channelRef.current = channel;
        channel.onopen = () => { void attach(channel); };
        channel.onclose = () => cleanup();
        channel.onerror = () => { setError("The DataChannel failed."); setPhase("error"); };
      };
      pcRef.current = pc;
      watchPeer(pc);
      await pc.setRemoteDescription({ type: "offer", sdp: preview.sdp });
      const answer = await pc.createAnswer();
      await pc.setLocalDescription(answer);
      await waitForCandidates(pc);
      const sdp = pc.localDescription?.sdp;
      if (!sdp) throw new Error("Could not create the WebRTC answer.");
      const result = await serviceCommand<OnboardingAnswerResult>("webrtc_onboarding_answer", {
        offer_document: preview.document,
        sdp,
        dtls_fingerprint: fingerprint(sdp),
      });
      setAnswerDocument(result.document);
      if (relaySettings?.signal_mailbox_url) {
        const published = await serviceCommand<{ session_id: string }>("signal_publish", { document: result.document, role: "answer" });
        setMailboxCode(published.session_id);
      }
      setAnswerPreview({ ...preview, sdp, dtls_fingerprint: fingerprint(sdp), document: result.document });
      setPhase("waiting-owner");
    } catch (reason) {
      const message = offerErrorMessage(reason);
      void captureDiagnostics("offer-review-failed", message).finally(cleanup);
      setError(message);
      setPhase("error");
    } finally {
      reviewOfferBusyRef.current = false;
      setReviewBusy(false);
    }
  }, [attach, captureDiagnostics, cleanup, offerInput, relaySettings, setupControl, watchPeer]);

  const acceptContact = async () => {
    setOnboardingBusy(true);
    setOnboardingError("");
    try {
      if (!controlDocumentRef.current) throw new Error("No contact invitation is available.");
      await serviceCommand("accept_invitation", { invitation: controlDocumentRef.current });
      if (workspaceDocumentRef.current) {
        await serviceCommand("submit_workspace_join", {
          operation_id: crypto.randomUUID(),
          invitation: workspaceDocumentRef.current,
        });
      }
      controlRef.current?.send(JSON.stringify({ type: "invitation_accepted" }));
      setOnboarding("waiting-approval");
      await onChanged();
    } catch (reason) {
      setOnboardingError(errorMessage(reason));
      setOnboarding("error");
    } finally {
      setOnboardingBusy(false);
    }
  };

  const declineContact = () => {
    controlRef.current?.send(JSON.stringify({ type: "invitation_declined" }));
    setOnboarding("declined");
  };

  const fetchAnswer = async () => {
    const session = mailboxCode;
    if (!session) return;
    try {
      const fetched = await serviceCommand<{ document: string }>("signal_fetch", { session_id: session, role: "answer" });
      setAnswerInput(fetched.document);
    } catch (reason) {
      setError(errorMessage(reason));
      setPhase("error");
    }
  };

  const close = () => {
    if (!handedOffRef.current) cleanup();
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
        relay_only: relaySettings.relay_only,
      });
      setRelaySettings(updated);
    } catch (reason) {
      setRelayError(errorMessage(reason));
    } finally {
      setRelayBusy(false);
    }
  };

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={close}>
      <section className="dialog dialog--wide" role="dialog" aria-modal="true" aria-labelledby="webrtc-onboarding-title" onMouseDown={(event) => event.stopPropagation()}>
        <div className="dialog__header"><h2 id="webrtc-onboarding-title">Connect with WebRTC</h2><button className="icon-button" onClick={close} aria-label="Close"><X size={20} /></button></div>
        <div className="stack">
          <p className="muted">WebRTC carries Reticulum packets over a direct or relayed DataChannel. The other person must review the signed offer and return a signed answer. This is experimental and does not approve a contact by itself.</p>
          <p className="muted">Create invitation: this device makes the offer. Join with WebRTC: this device pastes an offer. Use only one role per attempt.</p>
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
            {mailboxCode && <div className="remote-consent"><p>Signaling mailbox code: <code>{mailboxCode}</code></p><div className="webrtc-qr"><QRCodeSVG value={`meshchat://pair/${mailboxCode}`} size={150} level="M" /></div><p className="muted">Give this link or code to the other person instead of the full offer. This device creates one answer per code.</p><div className="dialog-actions"><button className="button button--secondary" onClick={() => void copy(mailboxCode, "code")}>{copied === "code" ? "Copied" : "Copy code"}</button><button className="button button--secondary" onClick={() => void copy(`meshchat://pair/${mailboxCode}`, "link")}>{copied === "link" ? "Copied" : "Copy link"}</button><button className="button button--secondary" onClick={() => void fetchAnswer()}>Fetch answer</button></div></div>}
            <div className="webrtc-qr"><QRCodeSVG value={offerDocument} size={190} level="L" /></div>
            <textarea className="webrtc-document" readOnly value={offerDocument} rows={5} aria-label="Signed WebRTC offer" />
            <div className="dialog-actions"><button className="button button--secondary" onClick={() => void copy(offerDocument, "offer")}>{copied === "offer" ? <Check size={17} /> : <Copy size={17} />} {copied === "offer" ? "Copied" : "Copy offer"}</button></div>
            <label className="field"><span>Paste their signed answer</span><textarea className="webrtc-document" value={answerInput} onChange={(event) => setAnswerInput(event.target.value)} rows={5} spellCheck={false} /></label>
            <div className="dialog-actions"><button className="button button--primary" disabled={!answerInput.trim()} onClick={() => void connectAnswer()}>Connect</button></div>
          </>}
          {phase === "review" && <>
            <label className="field"><span>Paste the signed WebRTC offer or mailbox code</span><textarea className="webrtc-document" value={offerInput} onChange={(event) => setOfferInput(event.target.value)} rows={5} spellCheck={false} placeholder="MESH-WEBRTC-OFFER... or mailbox code" /></label>
            <div className="dialog-actions"><button className="button button--secondary" onClick={() => setPhase("choose")}>Back</button><button className="button button--primary" disabled={!offerInput.trim() || reviewBusy} onClick={() => void reviewOffer()}>{reviewBusy ? "Creating answer…" : "Review and create answer"}</button></div>
          </>}
          {phase === "waiting-owner" && <>
            <h3>Send this answer back to the offerer</h3>
            <p className="muted">Answer session: <code>{sessionCode(answerDocument)}</code>. It must match the offer session.</p>
            <div className="webrtc-qr"><QRCodeSVG value={answerDocument} size={190} level="L" /></div>
            <textarea className="webrtc-document" readOnly value={answerDocument} rows={5} aria-label="Signed WebRTC answer" />
            <div className="dialog-actions"><button className="button button--secondary" onClick={() => void copy(answerDocument, "answer")}>{copied === "answer" ? <Check size={17} /> : <Copy size={17} />} {copied === "answer" ? "Copied" : "Copy answer"}</button></div>
            <p className="muted">Keep this open while the offerer pastes the answer. The DataChannel opens after both sides apply it.</p>
          </>}
          {phase === "connecting" && <><p className="direct-host-status" role="status"><RefreshCw size={17} /> Applying the signed answer and opening the DataChannel…</p><p className="muted">If this takes more than 30 seconds, Mesh Chat will stop and report the likely network cause.</p><div className="dialog-actions"><button className="button button--secondary" onClick={close}>Cancel</button></div></>}
          {phase === "connected" && <>
            <p className="direct-host-status" role="status"><Check size={17} /> WebRTC path connected</p>
            {onboarding === "preview" && contactInvitation ? <div className="remote-consent">
              <h3>Contact invitation</h3>
              <p><strong>{contactInvitation.display_name}</strong> wants to connect over this WebRTC path.</p>
              {workspaceInvitation && <p>Workspace invitation: <strong>{workspaceInvitation.name}</strong> · {workspaceInvitation.member_count} {workspaceInvitation.member_count === 1 ? "member" : "members"}</p>}
              <p>Fingerprint: <code>{contactInvitation.fingerprint}</code></p>
              <p>This accepts the signed invitation and sends a request. The other person must still approve it.</p>
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
          {phase === "error" && <><p className="form-error" role="alert">{error}</p><div className="dialog-actions"><button className="button button--secondary" onClick={() => void copyDiagnostics()}>{copied === "diagnostics" ? "Copied" : "Copy diagnostics"}</button>{relaySettings?.turn_broker_configured && !relaySettings.turn_broker_consent && <button className="button button--secondary" disabled={relayBusy} onClick={() => { void enableRelay().then(() => setPhase("choose")); }}>{relayBusy ? "Enabling…" : "Enable relay and retry"}</button>}{onFallback && <button className="button button--secondary" onClick={() => { close(); onFallback(); }}>Use invitation instead</button>}<button className="button button--secondary" onClick={() => setPhase("choose")}>Back</button><button className="button button--primary" onClick={close}>Close</button></div></>}
        </div>
      </section>
    </div>
  );
}
