"""Browser-free Windows WebRTC data channels for durable messaging.

The protected service owns consent, signaling policy and messaging state. This
module is a mechanism adapter: it creates native peer connections, exposes the
same method contract as the Android host, and reports observations through a
bounded callback. It never chooses peers, verifies signed documents or decides
retry behavior.

Only data channels are created. Audio/video calls remain in the WebView2 UI and
share no peer connection, track or cleanup path with this host.
"""

import asyncio
import base64
import json
import re
import threading
from dataclasses import dataclass, field
import time

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription

MESSAGE_LIMIT = 1064
CONTROL_LIMIT = 65_536
MAX_SESSIONS = 16
GATHER_TIMEOUT = 20.0
OPERATION_TIMEOUT = 30.0
CHANNEL_LABELS = frozenset({"mesh-reticulum", "mesh-onboarding", "meshchat-reconnect"})
FINGERPRINT = re.compile(r"(?im)^a=fingerprint:sha-256\s+([0-9a-f:]{95})\s*$")


class _HostFailure(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass
class _Session:
    resource: str
    pc: object
    expected: frozenset = frozenset()
    channels: dict = field(default_factory=dict)
    closed: bool = False
    received_packets: int = 0
    received_controls: int = 0
    local_type: str | None = None
    remote_type: str | None = None


def _error(code):
    return json.dumps({"ok": False, "error": code}, separators=(",", ":"))


def _success(sdp):
    match = FINGERPRINT.search(sdp)
    fingerprint = f"sha-256 {match.group(1).upper()}" if match else ""
    return json.dumps({"ok": True, "sdp": sdp, "fingerprint": fingerprint},
                      separators=(",", ":"))


def _channels(raw):
    try:
        values = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise _HostFailure("native_webrtc_missing_data_channel") from exc
    if not isinstance(values, list):
        raise _HostFailure("native_webrtc_missing_data_channel")
    specs = []
    for item in values:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        if label not in CHANNEL_LABELS:
            continue
        specs.append((label, bool(item.get("binary", label == "mesh-reticulum")),
                      bool(item.get("ordered", True))))
    if not any(label == "mesh-reticulum" and binary for label, binary, _ in specs):
        raise _HostFailure("native_webrtc_missing_data_channel")
    return specs


def _ice_servers(raw):
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise _HostFailure("native_webrtc_ice_invalid") from exc
    servers = []
    for item in value.get("iceServers", []) if isinstance(value, dict) else []:
        if not isinstance(item, dict):
            continue
        urls = item.get("urls")
        if isinstance(urls, str):
            urls = [urls]
        if not isinstance(urls, list):
            continue
        accepted = [url for url in urls if isinstance(url, str)
                    and url.startswith(("stun:", "turn:", "turns:"))]
        if accepted:
            servers.append(RTCIceServer(
                urls=accepted, username=item.get("username") or None,
                credential=item.get("credential") or None))
    return servers


def _relay_only(raw):
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return False
    return isinstance(value, dict) and value.get("iceTransportPolicy") == "relay"


def _relay_filtered(sdp):
    kept = []
    for line in sdp.splitlines():
        if line.startswith("a=candidate:") and " typ relay" not in line:
            continue
        kept.append(line)
    return "\r\n".join(kept) + "\r\n"


def _has_candidate(sdp):
    return any(line.startswith("a=candidate:") for line in sdp.splitlines())


def _sha256_only(sdp):
    """The signed protocol carries exactly one accepted DTLS fingerprint."""
    kept = [line for line in sdp.splitlines()
            if not line.startswith("a=fingerprint:") or line.startswith("a=fingerprint:sha-256")]
    return "\r\n".join(kept) + "\r\n"


class WindowsNativeWebRTCHost:
    """Data-only peer connections owned by the protected service process."""

    def __init__(self, notify):
        if not callable(notify):
            raise ValueError("Native WebRTC notification callback is required")
        self._notify = notify
        self._lock = threading.RLock()
        self._sessions = {}
        self._reservations = set()
        self._loop = asyncio.new_event_loop()
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="mesh-chat-native-webrtc",
                                        daemon=True)
        self._thread.start()

    def _run(self):
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True))
            self._loop.close()

    def _submit(self, coroutine, timeout=OPERATION_TIMEOUT):
        if self._closed:
            raise _HostFailure("native_webrtc_unavailable")
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        try:
            return future.result(timeout)
        except TimeoutError as exc:
            future.cancel()
            raise _HostFailure("native_webrtc_timeout") from exc

    def _emit(self, event, session, data=""):
        try:
            self._notify(event, session.resource, data)
        except Exception:
            pass

    def _current(self, session):
        return (not session.closed and self._sessions.get(session.resource) is session)

    def _reserve(self, resource):
        with self._lock:
            if self._closed:
                raise _HostFailure("native_webrtc_unavailable")
            if (resource in self._reservations or resource in self._sessions
                    or len(self._reservations) + len(self._sessions) >= MAX_SESSIONS):
                raise _HostFailure("native_webrtc_session_limit")
            self._reservations.add(resource)

    def _release_reservation(self, resource):
        with self._lock:
            self._reservations.discard(resource)

    def _publish(self, session):
        with self._lock:
            if session.resource not in self._reservations or self._closed:
                raise _HostFailure("native_webrtc_session_closed")
            self._reservations.discard(session.resource)
            self._sessions[session.resource] = session

    async def _gather(self, pc):
        deadline = time.monotonic() + GATHER_TIMEOUT
        while time.monotonic() < deadline:
            state = getattr(pc, "iceGatheringState", "new")
            if state == "complete" and _has_candidate(pc.localDescription.sdp):
                return
            await asyncio.sleep(0.02)
        raise _HostFailure("native_webrtc_no_candidates")

    def _configure(self, ice_json):
        return RTCConfiguration(iceServers=_ice_servers(ice_json))

    def _attach_channel(self, session, channel, label):
        channel.on("open", lambda: self._channel_state(session, channel, label))
        channel.on("close", lambda: self._channel_state(session, channel, label))
        channel.on("message", lambda data: self._message(session, label, data))
        if channel.readyState == "open":
            self._channel_state(session, channel, label)

    def _channel_state(self, session, channel, label):
        if not self._current(session):
            return
        state = channel.readyState
        self._emit("channel", session, f"{label}:{state}")
        if label == "mesh-reticulum" and state == "open":
            self._emit("open", session, label)

    def _message(self, session, label, data):
        if not self._current(session):
            return
        limit = MESSAGE_LIMIT if label == "mesh-reticulum" else CONTROL_LIMIT
        encoded = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        if not encoded or len(encoded) > limit:
            return
        payload = base64.b64encode(encoded).decode("ascii")
        if label == "mesh-reticulum":
            session.received_packets += 1
            self._emit("message", session, payload)
        else:
            session.received_controls += 1
            self._emit("control", session, f"{label}:{payload}")

    async def _open_session(self, resource, ice_json, specs, offer=None, expected=None):
        session = _Session(resource, None, frozenset(expected or (label for label, _, _ in specs)))
        pc = None
        try:
            pc = RTCPeerConnection(self._configure(ice_json))
            session.pc = pc
            if offer is None:
                for label, _binary, ordered in specs:
                    channel = pc.createDataChannel(label, ordered=ordered)
                    session.channels[label] = channel
                    self._attach_channel(session, channel, label)
            else:
                def on_datachannel(channel, current=session):
                    if not self._current(current) or channel.label not in current.expected:
                        channel.close()
                        return
                    current.channels[channel.label] = channel
                    self._attach_channel(current, channel, channel.label)
                pc.on("datachannel", on_datachannel)
            pc.on("iceconnectionstatechange",
                  lambda: self._current(session) and self._emit("ice", session, pc.iceConnectionState))
            pc.on("signalingstatechange",
                  lambda: self._current(session) and self._emit("signaling", session, pc.signalingState))
            pc.on("icegatheringstatechange",
                  lambda: self._current(session) and self._emit("gathering", session, pc.iceGatheringState))
            if offer is None:
                await pc.setLocalDescription(await pc.createOffer())
                session.local_type = "offer"
            else:
                await pc.setRemoteDescription(offer)
                await pc.setLocalDescription(await pc.createAnswer())
                session.local_type = "answer"
                session.remote_type = "offer"
            await self._gather(pc)
            sdp = _sha256_only(pc.localDescription.sdp)
            if _relay_only(ice_json):
                sdp = _relay_filtered(sdp)
            self._publish(session)
            for channel in session.channels.values():
                self._channel_state(session, channel, channel.label)
            return _success(sdp)
        except BaseException as exc:
            if pc is not None:
                try:
                    await pc.close()
                except Exception:
                    pass
            if isinstance(exc, _HostFailure):
                raise
            raise _HostFailure("native_webrtc_creation_failed") from exc

    def createOffer(self, resource, ice_json, channels_json):
        try:
            specs = _channels(channels_json)
            self._reserve(resource)
            return self._submit(self._open_session(resource, ice_json, specs))
        except _HostFailure as failure:
            self._release_reservation(resource)
            return _error(failure.code)
        except Exception:
            self._release_reservation(resource)
            return _error("native_webrtc_creation_failed")

    def acceptOffer(self, resource, offer_sdp, ice_json, channels_json):
        try:
            specs = _channels(channels_json)
            self._reserve(resource)
            return self._submit(self._open_session(
                resource, ice_json, specs,
                offer=RTCSessionDescription(sdp=offer_sdp, type="offer")))
        except _HostFailure as failure:
            self._release_reservation(resource)
            return _error(failure.code)
        except Exception:
            self._release_reservation(resource)
            return _error("native_webrtc_answer_failed")

    def applyAnswer(self, resource, answer_sdp):
        try:
            session = self._require(resource)
            self._submit(self._apply_answer(session, answer_sdp))
            return json.dumps({"ok": True}, separators=(",", ":"))
        except _HostFailure as failure:
            return _error(failure.code)
        except Exception:
            return _error("native_webrtc_apply_failed")

    async def _apply_answer(self, session, sdp):
        await session.pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="answer"))
        session.remote_type = "answer"

    def _require(self, resource):
        with self._lock:
            session = self._sessions.get(resource)
        if session is None or session.closed:
            raise _HostFailure("native_webrtc_session_missing")
        return session

    async def _send_async(self, session, label, payload):
        channel = session.channels.get(label)
        if channel is None or channel.readyState != "open":
            return False
        channel.send(payload)
        return True

    def send(self, resource, packet):
        if not isinstance(packet, (bytes, bytearray)) or not 1 <= len(packet) <= MESSAGE_LIMIT:
            return False
        try:
            session = self._require(resource)
            return bool(self._submit(self._send_async(
                session, "mesh-reticulum", bytes(packet))))
        except Exception:
            return False

    def sendControl(self, resource, label, text):
        if (label not in {"mesh-onboarding", "meshchat-reconnect"}
                or not isinstance(text, str) or not 1 <= len(text) <= CONTROL_LIMIT):
            return False
        try:
            session = self._require(resource)
            return bool(self._submit(self._send_async(session, label, text)))
        except Exception:
            return False

    def stats(self, resource):
        try:
            session = self._require(resource)
            result = {
                "ice_connection_state": str(session.pc.iceConnectionState).lower(),
                "ice_gathering_state": str(session.pc.iceGatheringState).lower(),
                "data_channel_state": (session.channels.get("mesh-reticulum").readyState
                                       if "mesh-reticulum" in session.channels else "missing"),
                "channels": sorted(session.channels),
                "received_packets": session.received_packets,
                "received_controls": session.received_controls,
            }
            return json.dumps({"ok": True, "result": result}, separators=(",", ":"))
        except _HostFailure as failure:
            return _error(failure.code)
        except Exception:
            return _error("native_webrtc_stats_failed")

    def activate(self, resource):
        self._require(resource)

    def close(self, resource):
        with self._lock:
            self._reservations.discard(resource)
            session = self._sessions.pop(resource, None)
        if session is None:
            return
        session.closed = True
        self._emit("closed", session, "")
        try:
            self._submit(self._close_session(session))
        except Exception:
            pass

    async def _close_session(self, session):
        for channel in list(session.channels.values()):
            try:
                channel.close()
            except Exception:
                pass
        session.channels.clear()
        try:
            await session.pc.close()
        except Exception:
            pass

    def shutdown(self):
        with self._lock:
            self._closed = True
            sessions = list(self._sessions.values())
            self._sessions.clear()
            self._reservations.clear()
        for session in sessions:
            session.closed = True
            self._emit("closed", session, "")
        if sessions and not self._loop.is_closed():
            pending = [asyncio.run_coroutine_threadsafe(
                self._close_session(session), self._loop) for session in sessions]
            for future in pending:
                try:
                    future.result(timeout=5)
                except Exception:
                    pass
        if not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)

    def closeAll(self):
        self.shutdown()
