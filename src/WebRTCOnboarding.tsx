import { useCallback, useEffect, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { Check, Copy, Phone, RefreshCw, X } from "lucide-react";

import { serviceCommand } from "./api";
import { attachWebRTCBridge, type WebRTCBridge } from "./webrtc-onboarding";
import { rememberWebRTCDiagnostics } from "./webrtc-diagnostics";
import { setWebRTCSession } from "./webrtc-session";
import type { CallIceConfiguration } from "./types";

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

function fingerprint(sdp: string): string {
  for (const line of sdp.split(/\r?\n/)) {
    if (line.startsWith("a=fingerprint:")) return line.slice("a=fingerprint:".length).trim();
  }
  throw new Error("The offer has no DTLS fingerprint.");
}

function errorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : "The WebRTC onboarding step failed.";
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

export function WebRTCOnboardingDialog({ onClose, onChanged, onConnected }: { onClose: () => void; onChanged: () => Promise<void>; onConnected?: () => void }) {
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
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const channelRef = useRef<RTCDataChannel | null>(null);
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

  const attach = useCallback(async (channel: RTCDataChannel) => {
    try {
      await waitForOpen(channel);
      const bridge = await attachWebRTCBridge(channel, { onError: (reason) => { setError(errorMessage(reason)); setPhase("error"); } });
      bridgeRef.current = bridge;
      const pc = pcRef.current;
      if (pc) {
        setWebRTCSession({ bridge, channel, pc });
        handedOffRef.current = true;
      }
      setPhase("connected");
      onConnected?.();
      await onChanged();
    } catch (reason) {
      const message = errorMessage(reason);
      void captureDiagnostics("attach-failed", message);
      setError(message);
      setPhase("error");
      cleanup();
    }
  }, [captureDiagnostics, cleanup, onChanged, onConnected]);

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
    setError(""); setPhase("creating");
    try {
      const ice = await serviceCommand<CallIceConfiguration>("call_ice_servers");
      iceSummaryRef.current = summarizeIce(ice);
      const pc = new RTCPeerConnection({ iceServers: ice.iceServers, iceTransportPolicy: ice.iceTransportPolicy });
      const channel = pc.createDataChannel("mesh-reticulum", { ordered: true });
      channel.binaryType = "arraybuffer";
      channel.onopen = () => { void attach(channel); };
      channel.onclose = () => cleanup();
      channel.onerror = () => { setError("The DataChannel failed."); setPhase("error"); };
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
      setPhase("waiting-answer");
    } catch (reason) {
      const message = errorMessage(reason);
      void captureDiagnostics("offer-failed", message).finally(cleanup);
      setError(message);
      setPhase("error");
    }
  }, [attach, captureDiagnostics, cleanup, watchPeer]);

  const connectAnswer = useCallback(async () => {
    setError(""); setPhase("connecting");
    try {
      if (!pcRef.current || !offerDocument) throw new Error("Create an offer first.");
      const preview = await serviceCommand<OnboardingAnswerPreview>("verify_webrtc_onboarding_answer", {
        offer_document: offerDocument,
        answer_document: answerInput.trim(),
      });
      setAnswerPreview(preview);
      await pcRef.current.setRemoteDescription({ type: "answer", sdp: preview.sdp });
      if (channelRef.current?.readyState === "open") await attach(channelRef.current);
    } catch (reason) {
      const message = errorMessage(reason);
      void captureDiagnostics("answer-failed", message);
      setError(message);
      setPhase("error");
    }
  }, [answerInput, attach, captureDiagnostics, offerDocument]);

  const reviewOffer = useCallback(async () => {
    setError(""); setPhase("review");
    try {
      const preview = await serviceCommand<OnboardingOfferPreview>("verify_webrtc_onboarding_offer", {
        document: offerInput.trim(),
      });
      setOfferPreview(preview);
      const ice = await serviceCommand<CallIceConfiguration>("call_ice_servers");
      iceSummaryRef.current = summarizeIce(ice);
      const pc = new RTCPeerConnection({ iceServers: ice.iceServers, iceTransportPolicy: ice.iceTransportPolicy });
      pc.ondatachannel = (event) => {
        const channel = event.channel;
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
      setAnswerPreview({ ...preview, sdp, dtls_fingerprint: fingerprint(sdp), document: result.document });
      setPhase("waiting-owner");
    } catch (reason) {
      const message = errorMessage(reason);
      void captureDiagnostics("offer-review-failed", message).finally(cleanup);
      setError(message);
      setPhase("error");
    }
  }, [attach, captureDiagnostics, cleanup, offerInput, watchPeer]);

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

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={close}>
      <section className="dialog dialog--wide" role="dialog" aria-modal="true" aria-labelledby="webrtc-onboarding-title" onMouseDown={(event) => event.stopPropagation()}>
        <div className="dialog__header"><h2 id="webrtc-onboarding-title">Connect with WebRTC</h2><button className="icon-button" onClick={close} aria-label="Close"><X size={20} /></button></div>
        <div className="stack">
          <p className="muted">WebRTC carries Reticulum packets over a direct or relayed DataChannel. The other person must review the signed offer and return a signed answer. This is experimental and does not approve a contact by itself.</p>
          {phase === "choose" && <div className="dialog-actions"><button className="button button--primary" onClick={() => void createOffer()}><Phone size={17} /> Create WebRTC invitation</button><button className="button button--secondary" onClick={() => { setPhase("review"); setOfferInput(""); }}>Join with WebRTC</button></div>}
          {phase === "creating" && <p className="direct-host-status" role="status"><RefreshCw size={17} /> Preparing the signed WebRTC offer…</p>}
          {phase === "waiting-answer" && <>
            <h3>Send this offer to the other person</h3>
            <div className="webrtc-qr"><QRCodeSVG value={offerDocument} size={190} level="L" /></div>
            <textarea className="webrtc-document" readOnly value={offerDocument} rows={5} aria-label="Signed WebRTC offer" />
            <div className="dialog-actions"><button className="button button--secondary" onClick={() => void copy(offerDocument, "offer")}>{copied === "offer" ? <Check size={17} /> : <Copy size={17} />} {copied === "offer" ? "Copied" : "Copy offer"}</button></div>
            <label className="field"><span>Paste their signed answer</span><textarea className="webrtc-document" value={answerInput} onChange={(event) => setAnswerInput(event.target.value)} rows={5} spellCheck={false} /></label>
            <div className="dialog-actions"><button className="button button--primary" disabled={!answerInput.trim()} onClick={() => void connectAnswer()}>Connect</button></div>
          </>}
          {phase === "review" && <>
            <label className="field"><span>Paste the signed WebRTC offer</span><textarea className="webrtc-document" value={offerInput} onChange={(event) => setOfferInput(event.target.value)} rows={5} spellCheck={false} placeholder="MESH-WEBRTC-OFFER..." /></label>
            <div className="dialog-actions"><button className="button button--secondary" onClick={() => setPhase("choose")}>Back</button><button className="button button--primary" disabled={!offerInput.trim()} onClick={() => void reviewOffer()}>Review and create answer</button></div>
          </>}
          {phase === "waiting-owner" && <>
            <h3>Send this answer back to the offerer</h3>
            <div className="webrtc-qr"><QRCodeSVG value={answerDocument} size={190} level="L" /></div>
            <textarea className="webrtc-document" readOnly value={answerDocument} rows={5} aria-label="Signed WebRTC answer" />
            <div className="dialog-actions"><button className="button button--secondary" onClick={() => void copy(answerDocument, "answer")}>{copied === "answer" ? <Check size={17} /> : <Copy size={17} />} {copied === "answer" ? "Copied" : "Copy answer"}</button></div>
            <p className="muted">Keep this open while the offerer pastes the answer. The DataChannel opens after both sides apply it.</p>
          </>}
          {phase === "connecting" && <><p className="direct-host-status" role="status"><RefreshCw size={17} /> Applying the signed answer and opening the DataChannel…</p><p className="muted">If this takes more than 30 seconds, Mesh Chat will stop and report the likely network cause.</p><div className="dialog-actions"><button className="button button--secondary" onClick={close}>Cancel</button></div></>}
          {phase === "connected" && <>
            <p className="direct-host-status" role="status"><Check size={17} /> WebRTC path connected</p>
            <p className="muted">Reticulum packets are now using this DataChannel. Continue with the normal invitation or workspace join; approval is still required.</p>
            <div className="dialog-actions"><button className="button button--secondary" onClick={() => void copyDiagnostics()}>{copied === "diagnostics" ? "Copied" : "Copy diagnostics"}</button><button className="button button--primary" onClick={close}>Close and continue</button></div>
          </>}
          {(offerPreview || answerPreview) && phase !== "choose" && <p className="muted">Offers are signed and expire automatically. Destination: <code>{(answerPreview?.signer_destination ?? offerPreview?.signer_destination ?? "").slice(0, 12)}</code>…</p>}
          {phase === "error" && <><p className="form-error" role="alert">{error}</p><div className="dialog-actions"><button className="button button--secondary" onClick={() => void copyDiagnostics()}>{copied === "diagnostics" ? "Copied" : "Copy diagnostics"}</button><button className="button button--secondary" onClick={() => setPhase("choose")}>Back</button><button className="button button--primary" onClick={close}>Close</button></div></>}
        </div>
      </section>
    </div>
  );
}
