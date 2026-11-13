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
import inspect
from dataclasses import dataclass, field
import time
from importlib.metadata import version
from uuid import uuid4

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from .native_path_evidence import SAMPLE_TIMEOUT, candidate, endpoint, observation, pair_token, validate_observation, validate_sample_request

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
    received_bytes: int = 0
    enqueued_packets: int = 0
    enqueued_controls: int = 0
    enqueued_bytes: int = 0
    sample_sequence: int = 0
    local_type: str | None = None
    remote_type: str | None = None


@dataclass
class _Lease:
    resource: str
    creating: bool = True
    started: bool = False
    cancelled: bool = False
    session: _Session | None = None
    task: object = None
    notified: bool = False
    created: object = field(default_factory=asyncio.Event)
    disposal: object = field(default_factory=asyncio.Lock)


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
        self._leases = {}
        self._retire_futures = {}
        self._adapter_epoch = uuid4().hex
        self._sampling = {}
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
        if self._closed or self._loop.is_closed() or not self._thread.is_alive():
            coroutine.close()
            raise _HostFailure("native_webrtc_unavailable")
        try:
            future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        except BaseException:
            coroutine.close()
            raise
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
            if resource in self._leases or len(self._leases) >= MAX_SESSIONS:
                raise _HostFailure("native_webrtc_session_limit")
            self._reservations.add(resource)
            lease = self._leases[resource] = _Lease(resource)
            return lease

    def _release_finished(self, lease):
        with self._lock:
            if self._leases.get(lease.resource) is not lease:
                return
            if not lease.creating:
                self._reservations.discard(lease.resource)
            if lease.cancelled and not lease.creating and lease.session is None:
                del self._leases[lease.resource]

    def _publish(self, lease, session):
        with self._lock:
            if self._leases.get(session.resource) is not lease or lease.cancelled or self._closed:
                raise _HostFailure("native_webrtc_session_closed")
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
        session.received_bytes += len(encoded)
        payload = base64.b64encode(encoded).decode("ascii")
        if label == "mesh-reticulum":
            session.received_packets += 1
            self._emit("message", session, payload)
        else:
            session.received_controls += 1
            self._emit("control", session, f"{label}:{payload}")

    async def _open_session(self, lease, ice_json, specs, offer=None, expected=None):
        resource = lease.resource
        session = _Session(resource, None, frozenset(expected or (label for label, _, _ in specs)))
        pc = None
        succeeded = False
        try:
            with self._lock:
                lease.started = True
                lease.task = asyncio.current_task()
                if self._leases.get(resource) is not lease or lease.cancelled or self._closed:
                    raise _HostFailure("native_webrtc_session_closed")
            pc = RTCPeerConnection(self._configure(ice_json))
            session.pc = pc
            with self._lock:
                lease.session = session
            if offer is None:
                # aiortc 1.13 defaults to legacy sctpmap SDP. The signed
                # onboarding protocol and Android host use modern sctp-port SDP.
                pc._sctpLegacySdp = False
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
            if not _has_candidate(sdp):
                raise _HostFailure("native_webrtc_no_candidates")
            self._publish(lease, session)
            for channel in session.channels.values():
                self._channel_state(session, channel, channel.label)
            succeeded = True
            return _success(sdp)
        except BaseException as exc:
            with self._lock:
                lease.cancelled = True
                session.closed = True
                if self._sessions.get(resource) is session:
                    self._sessions.pop(resource, None)
            try:
                await self._dispose_lease(lease)
            except BaseException:
                # Keep the exact peer and capacity after failed/cancelled
                # disposal. Explicit close can retry this same lease.
                pass
            if isinstance(exc, _HostFailure):
                raise
            raise _HostFailure("native_webrtc_creation_failed") from exc
        finally:
            with self._lock:
                lease.creating = False
                lease.task = None
                if not succeeded:
                    lease.cancelled = True
                lease.created.set()
                self._release_finished(lease)

    def _create(self, resource, ice_json, channels_json, offer=None):
        lease, coroutine = None, None
        try:
            specs = _channels(channels_json)
            lease = self._reserve(resource)
            coroutine = self._open_session(lease, ice_json, specs, offer=offer)
            return self._submit(coroutine)
        except Exception as error:
            if lease is not None:
                with self._lock:
                    lease.cancelled = True
                    if lease.session is not None:
                        lease.session.closed = True
                        if self._sessions.get(resource) is lease.session:
                            self._sessions.pop(resource, None)
                    # Only a known never-submitted coroutine releases its own
                    # reservation. Unknown timeout keeps custody until finish.
                    if not lease.started and coroutine is not None and (
                            inspect.getcoroutinestate(coroutine) == inspect.CORO_CLOSED
                            or (isinstance(error, _HostFailure) and error.code == "native_webrtc_unavailable")):
                        coroutine.close()
                        lease.creating = False
                        lease.created.set()
                    self._release_finished(lease)
                if not lease.started and coroutine is not None and not self._loop.is_closed():
                    # ConcurrentFuture.cancel() is not task completion. Once
                    # scheduling resumes, observe the actual coroutine/task
                    # termination, including cancellation before its first step.
                    try:
                        self._loop.call_soon_threadsafe(self._watch_creation, lease, coroutine)
                    except RuntimeError:
                        pass  # Keep custody if task termination is unobservable.
            return _error(error.code if isinstance(error, _HostFailure) else "native_webrtc_creation_failed")

    def _watch_creation(self, lease, coroutine):
        if lease.started:
            return
        def acknowledged(_=None):
            with self._lock:
                if (self._leases.get(lease.resource) is lease and not lease.started
                        and inspect.getcoroutinestate(coroutine) == inspect.CORO_CLOSED):
                    lease.creating = False
                    lease.task = None
                    lease.created.set()
                    self._release_finished(lease)
        if inspect.getcoroutinestate(coroutine) == inspect.CORO_CLOSED:
            acknowledged()
            return
        task = next((task for task in asyncio.all_tasks(self._loop)
                     if task.get_coro() is coroutine), None)
        if task is not None:
            task.add_done_callback(acknowledged)

    def createOffer(self, resource, ice_json, channels_json):
        return self._create(resource, ice_json, channels_json)

    def acceptOffer(self, resource, offer_sdp, ice_json, channels_json):
        return self._create(resource, ice_json, channels_json,
                            RTCSessionDescription(sdp=offer_sdp, type="offer"))

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
        session.enqueued_bytes += len(payload.encode("utf-8") if isinstance(payload, str) else payload)
        if label == "mesh-reticulum":
            session.enqueued_packets += 1
        else:
            session.enqueued_controls += 1
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

    def pathEvidence(self, resource, sample_request):
        """Private current mechanism evidence, separate from ordinary stats."""
        coroutine = token = None
        try:
            validate_sample_request(sample_request)
            started_ns = time.monotonic_ns()
            session = self._require(resource)
            with self._lock:
                if resource in self._sampling:
                    raise _HostFailure("native_webrtc_inspection_busy")
                token = self._sampling[resource] = object()
            coroutine = self._path_evidence(session, token, sample_request, started_ns)
            return self._submit(coroutine, timeout=SAMPLE_TIMEOUT)
        except _HostFailure as failure:
            if failure.code != "native_webrtc_timeout":
                self._release_unscheduled_sample(resource, token, coroutine)
            return _error(failure.code)
        except Exception:
            self._release_unscheduled_sample(resource, token, coroutine)
            return _error("native_webrtc_inspection_failed")

    def _release_unscheduled_sample(self, resource, token, coroutine):
        if coroutine is not None and inspect.getcoroutinestate(coroutine) == inspect.CORO_CREATED:
            coroutine.close()
        if coroutine is None or inspect.getcoroutinestate(coroutine) == inspect.CORO_CLOSED:
            with self._lock:
                if self._sampling.get(resource) is token:
                    self._sampling.pop(resource, None)

    async def _path_evidence(self, session, token, sample_request, started_ns):
        try:
            with self._lock:
                if not self._current(session) or self._sampling.get(session.resource) is not token:
                    raise _HostFailure("native_webrtc_session_missing")
            captured_ns = time.monotonic_ns()
            sampled_at_ms = captured_ns // 1_000_000
            session.sample_sequence += 1
            sequence = session.sample_sequence
            pc = session.pc
            ice_state = str(pc.iceConnectionState).lower()
            dtls = getattr(getattr(pc, "sctp", None), "transport", None)
            pair, status = None, "not_selected"
            # This is a deliberately version-bound private seam. The normal
            # WebRTC transport remains usable if inspection is unsupported.
            if (version("aiortc"), version("aioice")) != ("1.13.0", "0.10.2"):
                status = "unsupported"
            elif ice_state in {"connected", "completed"}:
                connection = getattr(getattr(dtls, "transport", None), "_connection", None)
                nominated = getattr(connection, "_nominated", None)
                if not isinstance(nominated, dict):
                    status = "unsupported"
                elif set(nominated) == {1}:
                    pair = self._selected_pair(session, nominated[1])
                    status = "selected" if pair is not None else "unavailable"
            value = observation(session.resource, self._adapter_epoch, sequence,
                sampled_at_ms, sample_request=sample_request, status=status, ice_state=ice_state,
                dtls_state=str(getattr(dtls, "state", "unknown")).lower(),
                channel_state=(session.channels["mesh-reticulum"].readyState
                               if "mesh-reticulum" in session.channels else "missing"), pair=pair,
                application={key: getattr(session, key) for key in (
                    "enqueued_packets", "enqueued_controls", "enqueued_bytes",
                    "received_packets", "received_controls", "received_bytes")})
            value = validate_observation(value, session.resource, sample_request)
            raw = json.dumps({"ok": True, "result": value}, separators=(",", ":"))
            with self._lock:
                if not self._current(session) or self._sampling.get(session.resource) is not token:
                    raise _HostFailure("native_webrtc_session_missing")
            now_ns = time.monotonic_ns()
            if (value["sampled_at_ms"] != sampled_at_ms
                    or value["adapter_epoch"] != self._adapter_epoch or value["sample_sequence"] != sequence
                    or not 0 <= captured_ns - started_ns <= int(SAMPLE_TIMEOUT * 1_000_000_000)
                    or not 0 <= now_ns - captured_ns <= int(SAMPLE_TIMEOUT * 1_000_000_000)
                    or not 0 <= now_ns - started_ns <= int(SAMPLE_TIMEOUT * 1_000_000_000)):
                raise _HostFailure("native_webrtc_inspection_stale")
            return raw
        finally:
            with self._lock:
                if self._sampling.get(session.resource) is token:
                    self._sampling.pop(session.resource, None)

    def _selected_pair(self, session, pair):
        if not pair.nominated or pair.state.name != "SUCCEEDED":
            return None
        local = candidate(pair.local_candidate.host, pair.local_candidate.port,
                          pair.local_candidate.type, pair.local_candidate.transport.lower())
        remote = candidate(pair.remote_candidate.host, pair.remote_candidate.port,
                           pair.remote_candidate.type, pair.remote_candidate.transport.lower())
        protocol, socket = "not_applicable", None
        if local["type"] == "relay":
            protocol, socket = self._relay_socket(pair.protocol.transport)
        return {"token": pair_token(self._adapter_epoch, session.resource, local, remote),
                "local": local, "remote": remote, "nominated": True,
                "relay_protocol": protocol, "relay_socket": socket,
                "bytes_sent": None, "bytes_received": None, "rtt_ms": None}

    @staticmethod
    def _relay_socket(transport):
        from aioice.turn import TurnClientTcpProtocol, TurnClientUdpProtocol, TurnTransport
        if not isinstance(transport, TurnTransport):
            return "unknown", None
        inner = getattr(transport, "_TurnTransport__inner_protocol", None)
        if isinstance(inner, TurnClientTcpProtocol):
            protocol = "tls" if inner.transport.get_extra_info("ssl_object") is not None else "tcp"
        elif isinstance(inner, TurnClientUdpProtocol):
            protocol = "udp"
        else:
            return "unknown", None
        local, remote = inner.transport.get_extra_info("sockname"), inner.transport.get_extra_info("peername")
        if not local or not remote:
            return protocol, None
        return protocol, {"local": endpoint(local[0], local[1]), "remote": endpoint(remote[0], remote[1]), "protocol": protocol}

    def activate(self, resource):
        self._require(resource)

    def resourceAccounting(self):
        """Private snapshot of actual creation/disposal capacity custody."""
        with self._lock:
            leases = tuple(self._leases.values())
            counts = {"capacity": MAX_SESSIONS, "reserved_count": len(leases),
                      "creating_count": sum(lease.creating for lease in leases),
                      "allocated_count": sum(lease.session is not None for lease in leases),
                      "active_count": sum(lease.session is not None and not lease.cancelled for lease in leases),
                      "retiring_count": sum(lease.session is not None and lease.cancelled for lease in leases)}
            result = {"v": 1, "complete": True, "semantics": "native_allocation_leases",
                      **counts, "availability": dict.fromkeys(counts, True)}
        return json.dumps({"ok": True, "result": result}, separators=(",", ":"))

    def close(self, resource):
        with self._lock:
            lease = self._leases.get(resource)
        if lease is None:
            return
        try:
            self._retirement(lease).result(timeout=OPERATION_TIMEOUT)
        except Exception as error:
            # Do not cancel disposal on caller timeout. It retains its exact
            # lease and one future until actual acknowledgement or retry.
            raise _HostFailure("native_webrtc_cleanup_pending") from error

    def _retirement(self, lease):
        with self._lock:
            lease.cancelled = True
            if lease.session is not None:
                lease.session.closed = True
                if self._sessions.get(lease.resource) is lease.session:
                    self._sessions.pop(lease.resource, None)
            task = lease.task
            if task is not None:
                def cancel_creation():
                    # A second cancel can interrupt the creation task's own
                    # disposal. Its first cancellation already fences publish.
                    if not task.done() and not task.cancelling():
                        task.cancel()
                self._loop.call_soon_threadsafe(cancel_creation)
            pending = self._retire_futures.get(lease.resource)
            if pending is not None and pending[0] is lease and not pending[1].done():
                return pending[1]
            if self._loop.is_closed() or not self._thread.is_alive():
                raise _HostFailure("native_webrtc_unavailable")
            coroutine = self._retire_lease(lease)
            try:
                future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
            except BaseException:
                coroutine.close()
                raise
            self._retire_futures[lease.resource] = lease, future
            def completed(_):
                with self._lock:
                    current = self._retire_futures.get(lease.resource)
                    if current is not None and current[1] is future:
                        self._retire_futures.pop(lease.resource, None)
            future.add_done_callback(completed)
            return future

    async def _retire_lease(self, lease):
        await lease.created.wait()
        await self._dispose_lease(lease)

    async def _dispose_lease(self, lease):
        async with lease.disposal:
            session = lease.session
            if session is not None:
                await self._close_session(session)
                with self._lock:
                    if lease.session is session:
                        lease.session = None
                    if not lease.notified:
                        lease.notified = True
                        self._emit("closed", session, "")
            self._release_finished(lease)

    async def _close_session(self, session):
        for channel in list(session.channels.values()):
            try:
                channel.close()
            except Exception:
                pass
        session.channels.clear()
        await session.pc.close()

    def shutdown(self):
        with self._lock:
            self._closed = True
            leases = tuple(self._leases.values())
        deadline = time.monotonic() + 5
        pending = [self._retirement(lease) for lease in leases]
        for future in pending:
            try:
                future.result(timeout=max(0, deadline - time.monotonic()))
            except Exception:
                pass
        with self._lock:
            if self._leases:
                # Keep the loop alive for pending disposal and a bounded retry;
                # a stopped loop cannot substantiate physical cleanup.
                raise _HostFailure("native_webrtc_cleanup_pending")
        if not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            raise _HostFailure("native_webrtc_cleanup_pending")

    def closeAll(self):
        self.shutdown()
