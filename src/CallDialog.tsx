import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { Mic, MicOff, Phone, PhoneOff, RefreshCw, Video, VideoOff } from "lucide-react";
import { loadCallIceServers, requestMediaPermission, runtimePlatform } from "./api";
import { acquireCallAudio, releaseCallAudio } from "./call-audio";
import { fetchCallMedia, incomingCallProfile, submitCallControl } from "./call-core";
import { CallOperation, callRecovery } from "./call-operation";
import { useProfileLifetime } from "./profile-lifetime";
import { connectionPath, waitForCandidates } from "./webrtc-peer";
import { errorMessage } from "./errors";
import { Dialog } from "./Dialog";
import { Button } from "./Button";
import type { CallIceConfiguration, CallMedia, CallSummary } from "./types";

function callFingerprint(sdp: string): string {
  for (const line of sdp.split(/\r?\n/)) {
    if (line.startsWith("a=fingerprint:")) return line.slice("a=fingerprint:".length).trim();
  }
  throw new Error("The call could not be secured (no DTLS fingerprint).");
}

function callHasNetworkCandidate(sdp: string): boolean {
  return /(?:^|\r?\n)a=candidate:/u.test(sdp);
}

export type CallPeer = { id: string; display_name: string };

function useCallOperation(name: string, incoming?: CallSummary) {
  const lifetime = useProfileLifetime();
  const [generation] = useState(() => lifetime?.active ? lifetime.capture() : -1);
  const [controls] = useState(() => new CallOperation(name, incoming?.id,
    incoming ? () => incomingCallProfile(incoming) : undefined,
    (ticket, retiring) => lifetime ? lifetime.mutate(generation, () => submitCallControl(ticket), retiring) : submitCallControl(ticket)));
  return { controls, lifetime, generation };
}

export function IncomingCallPrompt({ call, name, onReview, onChanged }: {
  call: CallSummary; name: string; onReview: () => void; onChanged: () => Promise<void>;
}) {
  const { controls, lifetime, generation } = useCallOperation(name, call);
  const operationView = useSyncExternalStore(controls.subscribe, controls.getSnapshot, controls.getSnapshot);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const decline = async () => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await controls.control("end", { call_id: call.id, reason: "declined" });
      await onChanged();
    } catch {
      setError("The call could not be dismissed. Try again.");
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    const unregister = lifetime?.register(generation, () => controls.getSnapshot().pending ? controls.retireForProfile() : Promise.resolve());
    return () => {
      if (controls.getSnapshot().pending) void controls.cancel("declined").then(unregister);
      else unregister?.();
    };
  }, [controls, lifetime, generation]);
  // Keep the alert above Settings and an invitation dialog which may still be
  // open. Receiving an invitation never starts microphone or camera capture.
  return createPortal(<Dialog title={`Incoming ${call.media === "video" ? "video" : "audio"} call`} onClose={() => void decline()}>
    <p>{name} is calling.</p>
    {error && <p className="form-error" role="alert">{error}</p>}
    {operationView.uncertain && <div role="alert"><p>The decline response was not confirmed.</p><Button disabled={operationView.busy} onClick={() => { void controls.retry(); }}>Resolve previous call operation</Button></div>}
    <div className="dialog-actions">
      <Button variant="secondary" disabled={busy} onClick={() => void decline()}>Decline</Button>
      <Button disabled={busy} onClick={onReview}>Review</Button>
    </div>
  </Dialog>, document.body);
}

export function CallDialog({
  contact,
  initialCall,
  onClose,
  onChanged,
}: {
  contact: CallPeer;
  initialCall?: CallSummary;
  onClose: () => void;
  onChanged: () => Promise<void>;
}) {
  const { controls, lifetime, generation } = useCallOperation(contact.display_name, initialCall);
  const operationView = useSyncExternalStore(controls.subscribe, controls.getSnapshot, controls.getSnapshot);
  const pendingCleanup = useSyncExternalStore(callRecovery.subscribe, callRecovery.getSnapshot, callRecovery.getSnapshot);
  const [call, setCall] = useState<CallSummary | undefined>(initialCall);
  const [media, setMedia] = useState<CallMedia | null>(null);
  const [phase, setPhase] = useState<"idle" | "preparing" | "calling" | "ringing" | "connecting" | "in_call" | "ended" | "error">(
    initialCall?.direction === "inbound" && initialCall.state === "ringing" ? "ringing" : "idle",
  );
  const [muted, setMuted] = useState(false);
  const [cameraEnabled, setCameraEnabled] = useState(initialCall?.media === "video");
  const [path, setPath] = useState<"direct" | "relay" | "unknown">("unknown");
  const [quality, setQuality] = useState<"good" | "fair" | "poor" | "unknown">("unknown");
  const [error, setError] = useState("");
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const remoteStreamRef = useRef<MediaStream | null>(null);
  const restartTimerRef = useRef<number | null>(null);
  const qualityTimerRef = useRef<number | null>(null);
  const audioOwnerRef = useRef<object | null>(null);
  const mediaOperationRef = useRef(0);
  const mediaOperationPendingRef = useRef(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const localVideoRef = useRef<HTMLVideoElement | null>(null);
  const remoteVideoRef = useRef<HTMLVideoElement | null>(null);
  const callIdRef = useRef<string | undefined>(initialCall?.id);
  const callHandleRef = useRef<string | undefined>(initialCall?.core_handle);
  const roleRef = useRef<"caller" | "callee" | undefined>(initialCall?.role);
  const remoteSetRef = useRef(false);
  const pollRef = useRef<number | null>(null);
  const pollBusyRef = useRef<object | null>(null);
  const restartInFlightRef = useRef(false);
  const restartAnswerInFlightRef = useRef(false);
  const lastRestartOfferRef = useRef("");
  const lastRestartAnswerRef = useRef("");
  const restartRef = useRef<() => void>(() => undefined);

  const cleanup = useCallback(() => {
    mediaOperationRef.current += 1;
    mediaOperationPendingRef.current = false;
    pollBusyRef.current = null;
    restartInFlightRef.current = false;
    restartAnswerInFlightRef.current = false;
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    remoteStreamRef.current = null;
    for (const timer of [restartTimerRef, qualityTimerRef]) {
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = null;
    }
    const pc = pcRef.current;
    pcRef.current = null;
    if (pc) {
      pc.ontrack = null;
      pc.onconnectionstatechange = null;
      pc.close();
    }
    if (audioRef.current) audioRef.current.srcObject = null;
    if (localVideoRef.current) localVideoRef.current.srcObject = null;
    if (remoteVideoRef.current) remoteVideoRef.current.srcObject = null;
    if (audioOwnerRef.current) {
      const owner = audioOwnerRef.current;
      audioOwnerRef.current = null;
      void releaseCallAudio(owner).catch(() => undefined);
    }
  }, []);

  const failCall = useCallback((message: string) => {
    cleanup();
    void controls.cancel().then(() => onChanged()).catch(() => undefined);
    setError(message);
    setPhase("error");
  }, [cleanup, controls, onChanged]);

  useEffect(() => {
    const unregister = lifetime?.register(generation, () => { cleanup(); return controls.retireForProfile(); });
    return () => { cleanup(); void controls.cancel().then(unregister); };
  }, [cleanup, controls, lifetime, generation]);

  useEffect(() => {
    if (phase !== "ringing" || !call?.id) return;
    let active = true;
    let busy = false;
    const timer = window.setInterval(async () => {
      if (busy) return;
      busy = true;
      try {
        const latest = await fetchCallMedia(call);
        if (!active) return;
        if (["ended", "declined", "busy", "no_answer", "failed"].includes(latest.state)) {
          controls.observeEnded();
          cleanup();
          setPhase(latest.state === "failed" ? "error" : "ended");
          if (latest.state === "failed") setError("The call ended unexpectedly.");
        }
      } catch {
        // Keep the invitation visible through a transient service read error.
      } finally {
        busy = false;
      }
    }, 1000);
    return () => { active = false; window.clearInterval(timer); };
  }, [call?.id, cleanup, controls, phase]);

  useEffect(() => {
    const onOnline = () => {
      const pc = pcRef.current;
      if (!callIdRef.current || !pc) return;
      if (restartTimerRef.current !== null) window.clearTimeout(restartTimerRef.current);
      restartTimerRef.current = window.setTimeout(() => {
        restartTimerRef.current = null;
        if (pcRef.current === pc) restartRef.current();
      }, 1000);
    };
    window.addEventListener("online", onOnline);
    return () => window.removeEventListener("online", onOnline);
  }, []);

  const inspectPath = useCallback(async (pc: RTCPeerConnection) => {
    const path = await connectionPath(pc);
    if (pcRef.current === pc) setPath(path === "relayed" ? "relay" : path);
  }, []);

  const inspectQuality = useCallback(async (pc: RTCPeerConnection) => {
    try {
      const stats = await pc.getStats();
      if (pcRef.current !== pc) return;
      let lost = 0;
      let received = 0;
      let jitter = 0;
      stats.forEach((report) => {
        const value = report as unknown as Record<string, unknown>;
        if (value.type !== "inbound-rtp") return;
        lost += Number(value.packetsLost ?? 0);
        received += Number(value.packetsReceived ?? 0);
        jitter = Math.max(jitter, Number(value.jitter ?? 0));
      });
      const total = lost + received;
      const loss = total > 0 ? lost / total : 0;
      setQuality(loss > 0.08 || jitter > 0.08 ? "poor" : loss > 0.02 || jitter > 0.03 ? "fair" : total > 0 ? "good" : "unknown");
    } catch {
      if (pcRef.current === pc) setQuality("unknown");
    }
  }, []);

  const attachPeer = useCallback((configuration: CallIceConfiguration) => {
    const pc = new RTCPeerConnection({
      iceServers: configuration.iceServers,
      iceTransportPolicy: configuration.iceTransportPolicy,
    });
    pc.ontrack = (event) => {
      if (pcRef.current !== pc) return;
      const stream = remoteStreamRef.current ?? event.streams[0] ?? new MediaStream();
      if (!stream.getTracks().includes(event.track)) stream.addTrack(event.track);
      remoteStreamRef.current = stream;
      if (audioRef.current) {
        audioRef.current.srcObject = stream;
        void audioRef.current.play().catch(() => undefined);
      }
      if (event.track.kind === "video" && remoteVideoRef.current) {
        remoteVideoRef.current.srcObject = stream;
        void remoteVideoRef.current.play().catch(() => undefined);
      }
    };
    pc.onconnectionstatechange = () => {
      if (pcRef.current !== pc) return;
      if (pc.connectionState === "connected") {
        if (restartTimerRef.current !== null) window.clearTimeout(restartTimerRef.current);
        restartTimerRef.current = null;
        setPhase("in_call");
        setError("");
        void inspectPath(pc);
        void inspectQuality(pc);
        if (qualityTimerRef.current !== null) window.clearTimeout(qualityTimerRef.current);
        qualityTimerRef.current = window.setTimeout(() => {
          qualityTimerRef.current = null;
          if (pcRef.current === pc) void inspectQuality(pc);
        }, 3000);
      }
      if (pc.connectionState === "disconnected") {
        setPhase("connecting");
        if (restartTimerRef.current === null) {
          restartTimerRef.current = window.setTimeout(() => {
            restartTimerRef.current = null;
            if (pcRef.current === pc) restartRef.current();
          }, 1500);
        }
      }
      if (pc.connectionState === "failed") {
        failCall("The media path could not be established.");
      }
    };
    pcRef.current = pc;
    return pc;
  }, [failCall, inspectPath, inspectQuality]);

  const startPolling = useCallback((callId: string) => {
    if (pollRef.current !== null) window.clearInterval(pollRef.current);
    pollRef.current = window.setInterval(async () => {
      const pc = pcRef.current;
      if (!pc || callIdRef.current !== callId || pollBusyRef.current) return;
      const operation = mediaOperationRef.current;
      const current = () => pcRef.current === pc && callIdRef.current === callId && mediaOperationRef.current === operation;
      const poll = {};
      pollBusyRef.current = poll;
      try {
        let latest: CallMedia;
        try {
          latest = await fetchCallMedia({ id: callId, core_handle: callHandleRef.current }, await controls.bindIncomingScope());
        } catch {
          // A transient service read can be retried on the next poll.
          return;
        }
        if (!current()) return;
        callHandleRef.current = latest.core_handle;
        setMedia(latest);
        setCall((current) => current ? { ...current, ...latest } : current);
        if (["ended", "declined", "busy", "no_answer", "failed"].includes(latest.state)) {
          controls.observeEnded();
          cleanup();
          setPhase(latest.state === "failed" ? "error" : "ended");
          if (latest.state === "failed") setError("The call ended unexpectedly.");
          return;
        }
        if (
          latest.restart_answer &&
          lastRestartAnswerRef.current !== latest.restart_answer &&
          pc.signalingState === "have-local-offer"
        ) {
          await pc.setRemoteDescription({ type: "answer", sdp: latest.restart_answer });
          if (!current()) return;
          lastRestartAnswerRef.current = latest.restart_answer;
          remoteSetRef.current = true;
          setPhase(pc.connectionState === "connected" ? "in_call" : "connecting");
          void inspectPath(pc);
        }
        if (
          latest.restart_offer &&
          roleRef.current === "callee" &&
          lastRestartOfferRef.current !== latest.restart_offer &&
          !restartAnswerInFlightRef.current
          && !controls.getSnapshot().pending
        ) {
          restartAnswerInFlightRef.current = true;
          try {
            if (current()) {
              await pc.setRemoteDescription({ type: "offer", sdp: latest.restart_offer });
              if (!current()) return;
              const answer = await pc.createAnswer();
              if (!current()) return;
              await pc.setLocalDescription(answer);
              if (!current()) return;
              await waitForCandidates(pc);
              if (!current()) return;
              const sdp = pc.localDescription?.sdp;
              if (sdp) {
                await controls.control("answer_restart", {
                  call_id: callId,
                  sdp,
                  dtls_fingerprint: callFingerprint(sdp),
                });
                if (!current()) return;
                lastRestartOfferRef.current = latest.restart_offer;
                setPhase(pc.connectionState === "connected" ? "in_call" : "connecting");
              }
            }
          } catch (reason) {
            if (current()) failCall(errorMessage(reason));
            return;
          } finally {
            if (current()) restartAnswerInFlightRef.current = false;
          }
        }
        if (latest.remote_sdp && !remoteSetRef.current && pc.signalingState === "have-local-offer") {
          await pc.setRemoteDescription({ type: "answer", sdp: latest.remote_sdp });
          if (!current()) return;
          remoteSetRef.current = true;
          setPhase(pc.connectionState === "connected" ? "in_call" : "connecting");
        }
        if (latest.state === "in_call" && pc.connectionState === "connected") setPhase("in_call");
      } catch (reason) {
        if (current()) failCall(errorMessage(reason));
      } finally {
        if (pollBusyRef.current === poll) pollBusyRef.current = null;
      }
    }, 1000);
  }, [cleanup, controls, failCall, inspectPath]);

  const prepareMedia = useCallback(async (media: "audio" | "video") => {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("This device does not expose a microphone to Mesh Chat.");
    }
    if (await runtimePlatform() !== "desktop") {
      const permission = await requestMediaPermission(media);
      if (!permission.audio || (media === "video" && !permission.camera)) {
        throw new Error(media === "video" ? "Microphone and camera access are required for a video call." : "Microphone access is required for an audio call.");
      }
    }
    if (lifetime && !lifetime.isCurrent(generation)) throw new Error("The profile changed before media capture.");
    if (callRecovery.getSnapshot().length > 0) throw new Error("Finish the previous call cleanup before starting media.");
    return navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      video: media === "video" ? { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } } : false,
    });
  }, [lifetime, generation]);

  const attemptRestart = useCallback(async () => {
    const callId = callIdRef.current;
    const pc = pcRef.current;
    if (!callId || !pc || restartInFlightRef.current || controls.getSnapshot().pending) return;
    if (roleRef.current !== "caller" || pc.signalingState !== "stable" ||
        !["disconnected", "failed"].includes(pc.connectionState)) return;
    const operation = mediaOperationRef.current;
    const current = () => pcRef.current === pc && callIdRef.current === callId && mediaOperationRef.current === operation;
    restartInFlightRef.current = true;
    try {
      setPhase("connecting");
      const offer = await pc.createOffer({ iceRestart: true });
      if (!current()) return;
      await pc.setLocalDescription(offer);
      if (!current()) return;
      await waitForCandidates(pc);
      if (!current()) return;
      const sdp = pc.localDescription?.sdp;
      if (!sdp) throw new Error("The reconnecting call offer could not be created.");
      if (!callHasNetworkCandidate(sdp)) throw new Error("No call network candidate was found. Check the connection or configure TURN.");
      await controls.control("restart", {
        call_id: callId,
        sdp,
        dtls_fingerprint: callFingerprint(sdp),
      });
      if (!current()) return;
      setPhase(pc.connectionState === "connected" ? "in_call" : "connecting");
    } catch (reason) {
      if (current()) failCall(errorMessage(reason));
    } finally {
      if (current()) restartInFlightRef.current = false;
    }
  }, [controls, failCall, waitForCandidates]);
  restartRef.current = () => { void attemptRestart(); };

  const configureVideoSender = useCallback(async (pc: RTCPeerConnection, stream: MediaStream) => {
    const track = stream.getVideoTracks()[0];
    if (!track) return;
    const sender = pc.getSenders().find((candidate) => candidate.track === track);
    if (!sender) return;
    try {
      const capabilities = RTCRtpSender.getCapabilities("video");
      if (capabilities) {
        const codecs = [...capabilities.codecs].sort((left, right) => {
          const score = (mime: string) => mime === "video/VP8" ? 0 : mime === "video/VP9" ? 1 : 2;
          return score(left.mimeType) - score(right.mimeType);
        });
        pc.getTransceivers().find((transceiver) => transceiver.sender === sender)?.setCodecPreferences(codecs);
      }
    } catch {
      // The platform may not expose codec preferences; keep its default.
    }
    try {
      const parameters = sender.getParameters();
      if (parameters.encodings[0]) {
        parameters.encodings[0].maxBitrate = 500_000;
        await sender.setParameters(parameters);
      }
    } catch {
      // Bitrate shaping is best-effort; the call still proceeds.
    }
  }, []);

  const startCall = useCallback(async (media: "audio" | "video") => {
    if (mediaOperationPendingRef.current || !controls.reset()) return;
    mediaOperationPendingRef.current = true;
    const operation = ++mediaOperationRef.current;
    const current = () => operation === mediaOperationRef.current;
    let stream: MediaStream | null = null;
    const audioOwner = {};
    callIdRef.current = undefined;
    callHandleRef.current = undefined;
    roleRef.current = undefined;
    remoteSetRef.current = false;
    lastRestartOfferRef.current = "";
    lastRestartAnswerRef.current = "";
    setCall(undefined);
    setMedia(null);
    setMuted(false);
    setPath("unknown");
    setQuality("unknown");
    setError("");
    setPhase("preparing");
    try {
      const capturedStream = await prepareMedia(media);
      stream = capturedStream;
      if (!current()) throw new Error("Call cancelled.");
      streamRef.current = capturedStream;
      if (localVideoRef.current) localVideoRef.current.srcObject = capturedStream;
      audioOwnerRef.current = audioOwner;
      const focus = await acquireCallAudio(audioOwner, media);
      if (!current()) throw new Error("Call cancelled.");
      if (!focus.granted) throw new Error("Android could not take call-audio focus.");
      const configuration = await loadCallIceServers() as unknown as CallIceConfiguration;
      if (!current()) throw new Error("Call cancelled.");
      const pc = attachPeer(configuration);
      capturedStream.getTracks().forEach((track) => pc.addTrack(track, capturedStream));
      void configureVideoSender(pc, capturedStream);
      const offer = await pc.createOffer();
      if (!current()) throw new Error("Call cancelled.");
      await pc.setLocalDescription(offer);
      if (!current()) throw new Error("Call cancelled.");
      await waitForCandidates(pc);
      if (!current()) throw new Error("Call cancelled.");
      const sdp = pc.localDescription?.sdp;
      if (!sdp) throw new Error("The call offer could not be created.");
      if (!callHasNetworkCandidate(sdp)) throw new Error("No call network candidate was found. Check the connection or configure TURN.");
      const result = await controls.control("start", {
        contact_id: contact.id,
        media,
        sdp,
        dtls_fingerprint: callFingerprint(sdp),
      }) as unknown as CallSummary;
      if (!current()) {
        throw new Error("Call cancelled.");
      }
      callIdRef.current = result.id;
      callHandleRef.current = result.core_handle;
      roleRef.current = result.role;
      setCall(result);
      setCameraEnabled(media === "video");
      setPhase(pc.connectionState === "connected" ? "in_call" : "calling");
      startPolling(result.id);
      await onChanged().catch(() => undefined);
    } catch (reason) {
      if (!current()) {
        stream?.getTracks().forEach((track) => track.stop());
        void releaseCallAudio(audioOwner).catch(() => undefined);
        return;
      }
      failCall(errorMessage(reason));
    } finally {
      if (current()) mediaOperationPendingRef.current = false;
    }
  }, [attachPeer, configureVideoSender, contact.id, controls, failCall, onChanged, prepareMedia, startPolling, waitForCandidates]);

  const acceptCall = useCallback(async () => {
    if (!call || mediaOperationPendingRef.current || controls.getSnapshot().pending || callRecovery.getSnapshot().length > 0) return;
    mediaOperationPendingRef.current = true;
    const operation = ++mediaOperationRef.current;
    const current = () => operation === mediaOperationRef.current;
    let stream: MediaStream | null = null;
    const audioOwner = {};
    setError("");
    setPhase("preparing");
    try {
      const details = await fetchCallMedia(call, await controls.bindIncomingScope());
      if (!current()) throw new Error("Call cancelled.");
      if (callRecovery.getSnapshot().length > 0) throw new Error("Finish the previous call cleanup before accepting this call.");
      callHandleRef.current = details.core_handle;
      if (!details.remote_sdp) throw new Error("This call invitation has no media description.");
      const capturedStream = await prepareMedia(call.media);
      stream = capturedStream;
      if (!current()) throw new Error("Call cancelled.");
      streamRef.current = capturedStream;
      if (localVideoRef.current) localVideoRef.current.srcObject = capturedStream;
      audioOwnerRef.current = audioOwner;
      const focus = await acquireCallAudio(audioOwner, call.media);
      if (!current()) throw new Error("Call cancelled.");
      if (!focus.granted) throw new Error("Android could not take call-audio focus.");
      const configuration = await loadCallIceServers() as unknown as CallIceConfiguration;
      if (!current()) throw new Error("Call cancelled.");
      const pc = attachPeer(configuration);
      await pc.setRemoteDescription({ type: "offer", sdp: details.remote_sdp });
      if (!current()) throw new Error("Call cancelled.");
      capturedStream.getTracks().forEach((track) => pc.addTrack(track, capturedStream));
      void configureVideoSender(pc, capturedStream);
      const answer = await pc.createAnswer();
      if (!current()) throw new Error("Call cancelled.");
      await pc.setLocalDescription(answer);
      if (!current()) throw new Error("Call cancelled.");
      await waitForCandidates(pc);
      if (!current()) throw new Error("Call cancelled.");
      const sdp = pc.localDescription?.sdp;
      if (!sdp) throw new Error("The call answer could not be created.");
      if (!callHasNetworkCandidate(sdp)) throw new Error("No call network candidate was found. Check the connection or configure TURN.");
      const result = await controls.control("answer", {
        call_id: call.id,
        sdp,
        dtls_fingerprint: callFingerprint(sdp),
      }) as unknown as CallSummary;
      if (!current()) throw new Error("Call cancelled.");
      setCall(result);
      roleRef.current = result.role;
      setMedia(details);
      setCameraEnabled(call.media === "video");
      setPhase(pc.connectionState === "connected" ? "in_call" : "connecting");
      startPolling(call.id);
      await onChanged().catch(() => undefined);
    } catch (reason) {
      if (!current()) {
        stream?.getTracks().forEach((track) => track.stop());
        void releaseCallAudio(audioOwner).catch(() => undefined);
        return;
      }
      failCall(errorMessage(reason));
    } finally {
      if (current()) mediaOperationPendingRef.current = false;
    }
  }, [attachPeer, call, configureVideoSender, controls, failCall, onChanged, prepareMedia, startPolling, waitForCandidates]);

  const hangup = useCallback(async (reason: "completed" | "declined" | "cancelled") => {
    cleanup();
    void controls.cancel(reason).then(() => onChanged()).catch(() => undefined);
    setPhase("ended");
    onClose();
  }, [cleanup, controls, onChanged, onClose]);

  const closeCall = useCallback(() => {
    if (phase === "idle" || phase === "ended" || phase === "error") {
      cleanup();
      controls.cancel();
      onClose();
      return;
    }
    void hangup("cancelled");
  }, [cleanup, controls, hangup, onClose, phase]);

  const toggleMute = useCallback(() => {
    const next = !muted;
    streamRef.current?.getAudioTracks().forEach((track) => { track.enabled = !next; });
    setMuted(next);
  }, [muted]);

  const toggleCamera = useCallback(() => {
    const next = !cameraEnabled;
    streamRef.current?.getVideoTracks().forEach((track) => { track.enabled = next; });
    setCameraEnabled(next);
  }, [cameraEnabled]);

  const incoming = call?.direction === "inbound";
  const active = phase === "in_call";

  return createPortal(
    <Dialog title={incoming ? `Call from ${contact.display_name}` : `Call ${contact.display_name}`} onClose={closeCall}>
      <div className="stack">
        {operationView.uncertain && !operationView.cancelling && <div role="alert">
          <p>{operationView.errorCode === "resync_required"
            ? "The call runtime changed. The previous operation is kept for review; close the call to stop local media."
            : "The call response was not confirmed. Resolve the previous operation before changing the call."}</p>
          <Button disabled={operationView.busy} onClick={() => { void controls.retry(); }}>Resolve previous call operation</Button>
        </div>}
        <audio ref={audioRef} autoPlay playsInline hidden />
        <video ref={localVideoRef} className="call-video call-video--local" autoPlay muted playsInline hidden={!cameraEnabled || phase === "ended" || phase === "error"} />
        <video ref={remoteVideoRef} className="call-video" autoPlay muted playsInline hidden={call?.media !== "video" || phase === "ended" || phase === "error"} />
        {phase === "idle" && (
          <>
            <p className="muted">Audio and video are sent directly to {contact.display_name} over the authenticated call path. Your microphone and camera start only after you choose a call.</p>
            <div className="dialog-actions">
              <Button variant="secondary" onClick={onClose}>Cancel</Button>
              <Button disabled={pendingCleanup.length > 0} onClick={() => void startCall("audio")}><Phone size={17} /> Audio call</Button>
              <Button disabled={pendingCleanup.length > 0} onClick={() => void startCall("video")}><Video size={17} /> Video call</Button>
            </div>
          </>
        )}
        {phase === "ringing" && (
          <>
            <p className="direct-host-status" role="status"><Phone size={17} /> Incoming {call?.media === "video" ? "video" : "audio"} call</p>
            <p className="muted">Your microphone and camera stay off until you accept.</p>
            <div className="dialog-actions">
              <Button variant="danger" onClick={() => void hangup("declined")}>Decline</Button>
              <Button disabled={pendingCleanup.length > 0} onClick={() => void acceptCall()}><Phone size={17} /> Accept</Button>
            </div>
          </>
        )}
        {(phase === "preparing" || phase === "calling" || phase === "connecting") && (
          <>
            <p className="direct-host-status" role="status">
              <RefreshCw size={17} /> {phase === "preparing" ? "Preparing media…" : phase === "calling" ? "Calling and waiting for an answer…" : "Connecting the media path…"}
            </p>
            <p className="muted">The call uses the signed Reticulum signaling path; the media path is direct when the network allows it.</p>
            <div className="dialog-actions">
              <Button variant="secondary" onClick={() => void hangup("cancelled")}>Cancel</Button>
            </div>
          </>
        )}
        {active && (
          <>
            <p className="direct-host-status" role="status"><Phone size={17} /> In call · {path === "relay" ? "Relayed via TURN" : path === "direct" ? "Direct media" : "Checking media path"} · {quality === "unknown" ? "Measuring quality" : quality === "good" ? "Good quality" : quality === "fair" ? "Fair quality" : "Poor quality"}</p>
            <div className="dialog-actions">
              <Button variant="secondary" onClick={toggleMute}>{muted ? <MicOff size={17} /> : <Mic size={17} />} {muted ? "Unmute" : "Mute"}</Button>
              {call?.media === "video" && <Button variant="secondary" onClick={toggleCamera}>{cameraEnabled ? <Video size={17} /> : <VideoOff size={17} />} {cameraEnabled ? "Camera off" : "Camera on"}</Button>}
              <Button variant="danger" onClick={() => void hangup("completed")}><PhoneOff size={17} /> Hang up</Button>
            </div>
          </>
        )}
        {phase === "ended" && <><p className="muted">Call ended.</p><div className="dialog-actions"><Button onClick={closeCall}>Close</Button></div></>}
        {phase === "error" && <p className="form-error" role="alert">{error || "The call could not connect."}</p>}
        {media && active && <p className="muted">{media.candidate_count} network candidate{media.candidate_count === 1 ? "" : "s"} exchanged.</p>}
        {phase === "error" && <div className="dialog-actions">{call && <Button disabled={pendingCleanup.length > 0} onClick={() => void startCall(call.media)}>Try again</Button>}<Button variant="secondary" onClick={closeCall}>Close</Button></div>}
      </div>
    </Dialog>, document.body
  );
}

