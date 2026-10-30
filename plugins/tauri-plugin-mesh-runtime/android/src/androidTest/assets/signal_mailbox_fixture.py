"""Instrumentation-only peers: real signing, vault, HTTP, supervisor and JNI.

Roster/consent are seeded fixtures, not an invitation UI test. The injected
HTTP transport reaches the real local Worker over adb reverse. No fixture or
HTTP override is included in the production APK.
"""
import json
from pathlib import Path
import secrets
import threading
import time
from types import SimpleNamespace
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid

import RNS
from mesh_chat import signal_mailbox
from mesh_chat.background_reconnect import BackgroundReconnectSupervisor
from mesh_chat.call_settings import CallSettings
from mesh_chat.errors import ValidationError
from mesh_chat.reconnect_service import ReconnectServiceMixin
from mesh_chat.signal_crypto import encode, seal, unseal
from mesh_chat.vault import VaultStore
from mesh_chat.workspace_service import WorkspaceServiceMixin
from mesh_chat.workspace_reconnect import create_workspace_reconnect_capability
from mesh_chat.workspace_wire import WorkspaceWirePayload


class WorkerTransport:
    def __init__(self, url):
        parsed = urlsplit(url)
        assert parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
        self.url = url
        self.offline = False
        self.requests = 0
        self.original = signal_mailbox._open
        self.opener = urllib.request.build_opener(signal_mailbox._NoRedirect())

    def __enter__(self):
        signal_mailbox._open = self.open
        return self

    def open(self, request):
        if self.offline:
            raise urllib.error.URLError("synthetic connectivity loss")
        self.requests += 1
        if request.data:
            envelope = json.loads(request.data)
            assert set(envelope) == {"v", "ciphertext"} and envelope["v"] == 2
            assert b"fingerprint" not in request.data and b"signer" not in request.data
        assert request.get_header("User-agent") == signal_mailbox.USER_AGENT
        return self.opener.open(urllib.request.Request(
            self.url + urlsplit(request.full_url).path, data=request.data,
            headers=dict(request.header_items()), method=request.get_method()), timeout=10)

    def __exit__(self, *_):
        signal_mailbox._open = self.original


def encrypted_round_trip(url):
    secret = encode(bytes(range(32)))
    session = "a" * 40
    vector = "AAECAwQFBgcICQoLDA0ODwhO9MYGHUzAqsG7rMbbDMyAEmTI7Ph1Z8Hq8q1euHYuXYcg8UH7RmaGppOoaA_UeKZ-gw2WqFXz2_kDIASwIj0"
    assert unseal(json.dumps({"v": 2, "ciphertext": vector}).encode(), secret, session, "offer") == "mesh-chat signaling vector"
    with WorkerTransport(url):
        code = signal_mailbox.create_pairing(CallSettings().signal_mailbox_url)
        context = signal_mailbox.parse_pairing(code, CallSettings().signal_mailbox_url)
        signal_mailbox.publish(context["url"], "android-private-signal", "offer",
                               session=context["session"], token=context["token"], secret=context["secret"])
        assert signal_mailbox.fetch(context["url"], context["session"], "offer",
                                    token=context["token"], secret=context["secret"])["document"] == "android-private-signal"
        raw = seal("android-private-signal", context["secret"], context["session"], "offer")
        for key, room, role in ((secret, context["session"], "offer"),
                                (context["secret"], "b" * 40, "offer"),
                                (context["secret"], context["session"], "answer")):
            try:
                unseal(raw, key, room, role)
            except ValidationError:
                continue
            raise AssertionError("Substituted encryption context was accepted")
    return True


class Native:
    def __init__(self):
        from java import jclass
        self.host = jclass("com.meshchat.runtime.NativeWebRtcHost")
        self.timings = []

    def invoke(self, method, *args):
        started = time.monotonic()
        result = json.loads(str(getattr(self.host, method)(*args)))
        if method != "stats":
            self.timings.append((method, round(time.monotonic() - started, 2)))
            self.timings = self.timings[-12:]
        assert result.get("ok"), "Native WebRTC operation failed: " + method
        if method in ("createOffer", "acceptOffer"):
            # These fixture peers use local candidates and no STUN/TURN server.
            # A non-trickle description must finish gathering, rather than
            # silently returning at the native host's gathering timeout.
            stats = json.loads(str(self.host.stats(args[0])))["result"]
            assert stats["ice_gathering_state"] == "complete", "Native ICE gathering did not complete"
            assert "a=candidate:" in result["sdp"], "Native description has no ICE candidate"
        return result.get("result", result)

    def stats(self, session):
        try:
            value = self.invoke("stats", session)
            return {**value, "attached": value.get("data_channel_state") == "open"}
        except AssertionError:
            return {"attached": False, "ice_connection_state": "closed"}

    def close(self, session):
        self.host.close(session)

    def send(self, session):
        return bool(self.host.send(session, b"\x01\x02\x03"))


class Peer(ReconnectServiceMixin, WorkspaceServiceMixin):
    def __init__(self, path, key, device, native, platform="android"):
        self.path, self.key, self.device, self.native = Path(path), key, device, native
        self.store = VaultStore(self.path, key, native_mobile_protection=platform,
                                allow_unprotected_for_tests=platform is None)
        saved = self.store.get("fixture", "identity")
        self.identity = RNS.Identity.from_bytes(bytes.fromhex(saved["private"])) if saved else RNS.Identity()
        if not saved:
            self.store.put("fixture", "identity", {"private": self.identity.get_private_key().hex()})
        self.destination = RNS.Destination.hash(self.identity, "lxmf", "delivery").hex()
        self.store.put("profile", "local", {"destination_hash": self.destination})
        self.store.put("reconnect_device", "local", {"device_id": device})
        self._call_settings = CallSettings(turn_broker_url=None)
        self._shutdown = threading.Event()
        self.lifecycle = "background_available"
        self.manifests = {}
        self.created = 0

    def _call_identity(self): return self.identity
    def _require_profile(self): return self.store.get("profile", "local")
    def _changed(self): pass
    def _workspace_changed(self, *_args, **_kwargs): pass
    def _workspace_lifecycle_state(self): return {"state": self.lifecycle}
    def _require_workspace(self, workspace_id):
        return self.store.get("workspace", self._workspace_record_id(workspace_id))
    def _workspace_current_manifest(self, workspace): return self.manifests[workspace["id"]]
    def native_reconnect_session(self, _profile_id): return None
    def call_ice_servers(self): return {"iceServers": [], "iceTransportPolicy": "all"}
    def native_webrtc_stats(self, session): return self.native.stats(session)
    def native_webrtc_close(self, session): self.native.close(session)
    def _contact_by_destination(self, destination):
        return next((c for c in self.store.list("contact") if c["destination_hash"] == destination), None)

    def native_webrtc_offer(self, session, ice, channels, *_args, **_kwargs):
        self.created += 1
        return self.native.invoke("createOffer", session, json.dumps(ice), json.dumps(channels))

    def native_webrtc_accept(self, session, sdp, ice, channels, *_args, **_kwargs):
        self.created += 1
        return self.native.invoke("acceptOffer", session, sdp, json.dumps(ice), json.dumps(channels))

    def native_webrtc_apply_answer(self, session, sdp):
        return self.native.invoke("applyAnswer", session, sdp)

    def seed_relationship(self, other, workspace_id):
        if not workspace_id:
            if not self.store.get("contact", other.device):
                self.store.put("contact", other.device, {"id": other.device, "trust": "approved",
                    "destination_hash": other.destination, "display_name": "Synthetic peer"})
            return other.device
        record_id = self._workspace_record_id(workspace_id)
        if not self.store.get("workspace", record_id):
            self.store.put("workspace", record_id, {"id": workspace_id, "name": "Synthetic workspace",
                "state": "active", "local_member_id": self.device, "local_device_id": "ws-" + self.device})
        self.manifests[workspace_id] = SimpleNamespace(members=[SimpleNamespace(
            member_id=p.device, status="active", display_name="Synthetic peer",
            devices=[SimpleNamespace(device_id="ws-" + p.device, destination_hash=bytes.fromhex(p.destination))]
        ) for p in (self, other)])
        return f"workspace:{workspace_id}:{other.device}:ws-{other.device}"


def wait_until(predicate, description, seconds=120):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(0.1)
    raise AssertionError(description)


class ObservedSupervisor(BackgroundReconnectSupervisor):
    """Keep content-free failure locations when a scenario times out."""
    def __init__(self, service):
        super().__init__(service)
        self.errors = []

    def record_error(self, operation, error):
        trace = error.__traceback__
        while trace.tb_next: trace = trace.tb_next
        entry = f"{operation}:{type(error).__name__}:{Path(trace.tb_frame.f_code.co_filename).name}:{trace.tb_lineno}"
        if not self.errors or self.errors[-1] != entry:
            self.errors.append(entry)
        self.errors = self.errors[-12:]

    def _step(self, profile_id, operation, *args, **kwargs):
        try:
            return super()._step(profile_id, operation, *args, **kwargs)
        except Exception as error:
            self.record_error(operation.__name__, error)
            raise

    def _attempt(self, profile):
        try:
            return super()._attempt(profile)
        except Exception as error:
            self.record_error("attempt", error)
            raise


def run_shared_runtime_native(root, url):
    """Production shared policy with real signing/Worker/JNI, synthetic path.

    This is native adapter conformance, not Reticulum/application-receipt proof.
    The two fixture peers do not initialize process-global Reticulum runtimes.
    """
    from mesh_chat.connection.adapters.reconnect import NativePort, ReconnectExecutor, SignalingPort
    from mesh_chat.connection.model import Execution
    from mesh_chat.connection.runtime import ConnectionRuntime

    native = Native()
    peers, runtimes = [], []
    with WorkerTransport(url) as transport:
        try:
            peers.extend(Peer(Path(root) / str(i), secrets.token_bytes(32),
                              f"shared-{i}-{uuid.uuid4().hex}", native) for i in range(2))
            contacts = [p.seed_relationship(peers[1-i], None) for i, p in enumerate(peers)]
            caps = [p.reconnect_consent_set(contacts[i], True, True)["capabilities"]
                    for i, p in enumerate(peers)]
            for i, peer in enumerate(peers):
                peer.reconnect_capabilities_store(caps[1-i])
                peer.reconnect_start(contacts[i])

            def runtime(peer):
                def factory(current, profile):
                    signaling = SignalingPort(peer.reconnect_request_create, peer.reconnect_offer_create,
                        peer.reconnect_answer_create, peer.verify_reconnect_request,
                        peer.verify_reconnect_offer, peer.verify_reconnect_answer,
                        peer.reconnect_publish, peer.reconnect_fetch)
                    port = NativePort(peer.native_webrtc_offer, peer.native_webrtc_accept,
                        peer.native_webrtc_apply_answer, peer.native_webrtc_stats,
                        lambda _: {}, peer.native_webrtc_close)
                    return ReconnectExecutor(signaling, port, profile=profile, ice=peer.call_ice_servers,
                        path=lambda _: {"has_path": True, "ready": True}, current=current,
                        now=time.monotonic, wall_time=time.time)
                return ConnectionRuntime(uuid.uuid4().hex, factory, profiles=peer.reconnect_profiles,
                    execution=lambda: Execution.AVAILABLE,
                    activate=peer.reconnect_start)

            runtimes.extend(runtime(peer) for peer in peers)
            for owner in runtimes:
                owner.start()

            def sessions():
                return [state.carrier.resource.resource_id for owner in runtimes
                        for state in owner.owner.snapshots() if state.carrier]

            def connected():
                values = sessions()
                return len(values) == 2 and all(native.stats(s).get("attached") for s in values)

            def traffic():
                values = sessions()
                before = [native.stats(s).get("received_packets", 0) for s in values]
                assert all(native.send(s) for s in values)
                wait_until(lambda: all(native.stats(s).get("received_packets", 0) > before[i]
                                      for i, s in enumerate(values)), "Shared-runtime native traffic missing", 10)

            wait_until(connected, "Shared-runtime native negotiation failed")
            traffic()
            original = set(sessions())
            # Lifecycle transitions do not replace a healthy service-owned carrier.
            for peer in peers:
                peer.lifecycle = "foreground"
            time.sleep(1)
            assert original == set(sessions())
            traffic()
            # Native carrier loss is recovered by the same owner in foreground.
            for session in original:
                native.close(session)
            wait_until(lambda: connected() and original.isdisjoint(sessions()),
                       "Shared owner did not recover in foreground")
            traffic()
            last = sessions()
            for owner in runtimes:
                owner.stop()
                owner.wait()
            assert all(not native.stats(s).get("attached") for s in last)
            return True
        finally:
            for owner in runtimes:
                owner.stop()
                owner.wait()
            for peer in peers:
                peer.store.close()

def run_manual_native_adoption(automatic=True):
    """Actual service/composition, signed control and JNI; synthetic path only.

    Approval is seeded. This proves ownership transfer and packet traffic,
    not invitation UI, a remote Reticulum path or authenticated LXMF receipts.
    The private selector is changed only at a quiescent test bootstrap.
    """
    from mesh_chat import mobile_bridge
    from mesh_chat.connection.composition import native_runtime
    from mesh_chat.connection.model import Execution
    from mesh_chat.reconnect import create_connection_capabilities
    from mesh_chat.webrtc_onboarding import create_onboarding_offer

    service = mobile_bridge._service
    assert service is not None and service.network is not None
    assert service._connection_runtime is None
    assert service._background_reconnect_supervisor is None
    assert not service._native_webrtc_live
    service._connection_policy = "shared-native"
    service._call_settings.signal_mailbox_url = None
    service._call_settings.turn_broker_url = None
    service._call_settings.stun_urls = []
    native = Native()
    identity = RNS.Identity()
    contact_id = "manual-" + uuid.uuid4().hex
    destination = RNS.Destination.hash(identity, "lxmf", "delivery").hex()
    service.store.put("contact", contact_id, {"id": contact_id, "trust": "approved",
        "destination_hash": destination, "display_name": "Synthetic manual peer"})
    remote_id, local_id = "remote-" + uuid.uuid4().hex, "local-" + uuid.uuid4().hex
    ice = {"iceServers": [], "iceTransportPolicy": "all"}
    channels = [{"label": "mesh-reticulum", "binary": True, "ordered": True},
                {"label": "mesh-onboarding", "binary": False, "ordered": True}]
    owner = None
    try:
        offer = native.invoke("createOffer", remote_id, json.dumps(ice), json.dumps(channels))
        document = create_onboarding_offer(identity, session_id=uuid.uuid4().hex,
            sdp=offer["sdp"], dtls_fingerprint=offer["fingerprint"])
        answer = service.native_webrtc_accept(local_id, offer["sdp"], ice, channels)
        local_physical = service._native_resources.require(local_id)
        service.native_webrtc_bind_onboarding(local_id, document)
        native.invoke("applyAnswer", remote_id, answer["sdp"])
        wait_until(lambda: all(native.stats(s).get("attached") for s in (local_physical, remote_id)),
                   "Manual native channels did not open")
        service.reconnect_consent_set(contact_id, automatic, True)
        capabilities = create_connection_capabilities(identity,
            peer_destination=service._require_profile()["destination_hash"],
            device_id="manual-" + uuid.uuid4().hex, transports=["webrtc"],
            auto_reconnect=automatic, allow_direct_ip_disclosure=True,
            persistent=True, encrypted=True)
        control = json.dumps({"type": "connection_capabilities", "document": capabilities})
        wait_until(lambda: bool(native.host.sendControl(remote_id, "mesh-onboarding", control)),
                   "Manual control channel did not open", 15)
        wait_until(lambda: service._native_webrtc_controls.get(local_id, {}).get("profile_id"),
                   "Signed native capabilities were not bound to a profile", 15)
        profile_id = service._native_webrtc_controls[local_id]["profile_id"]
        if automatic:
            service.reconnect_start(contact_id)
        owner = service._connection_runtime = native_runtime(service)
        # Instrumentation supplies execution availability and path readiness;
        # authority, native discovery, inspection and attachment stay real.
        owner.execution = lambda: Execution.AVAILABLE
        owner.executor.path = lambda _: {"has_path": True, "ready": True}
        owner.start()
        wait_until(lambda: owner.snapshots().get(profile_id, {}).get("messaging_ready"),
                   "Shared owner did not adopt the manual native carrier", 30)
        states = owner.owner.snapshots()
        assert len(states) == 1 and states[0].carrier.resource.resource_id == local_id
        if not automatic:
            profile = service._reconnect_profile(profile_id)
            assert not profile["auto_reconnect"] and not profile["remote_auto_reconnect"]
            assert not states[0].authority.signaling_available
        assert service._execute("native_webrtc_close", {"session_id": local_id}) == {"state": "managed"}
        before = {s: native.stats(s).get("received_packets", 0) for s in (local_physical, remote_id)}
        assert native.send(local_physical) and native.send(remote_id)
        wait_until(lambda: all(native.stats(s).get("received_packets", 0) > before[s]
                              for s in before), "Adopted native carrier did not pass traffic", 10)
        first_bridge = service._native_webrtc_sessions[local_id]
        service.webrtc_detach_native(local_id)
        wait_until(lambda: service._native_webrtc_sessions.get(local_id) not in (None, first_bridge),
                   "Shared owner did not restore the native bridge", 15)
        wait_until(lambda: owner.snapshots()[profile_id]["messaging_ready"],
                   "Restored bridge did not regain path readiness", 10)
        assert service._native_resources.require(local_id) == local_physical
        assert native.send(local_physical) and native.send(remote_id)
        # Simulate lost RNS registration while the service's bridge map and
        # actual JNI carrier survive. Stale metadata must not report readiness.
        with service._dispatch_lock:
            stale_bridge = service._native_webrtc_sessions[local_id]
            interface = service._webrtc_bridges[stale_bridge]
            RNS.Transport.interfaces.remove(interface)
            assert not service.native_webrtc_stats(local_id)["attached"]
        wait_until(lambda: service._native_webrtc_sessions.get(local_id) not in (None, stale_bridge),
                   "Shared owner retained an unregistered bridge", 15)
        wait_until(lambda: owner.snapshots()[profile_id]["messaging_ready"],
                   "Re-registered bridge did not regain path readiness", 10)
        assert service._native_resources.require(local_id) == local_physical
        service.reconnect_stop(contact_id)
        wait_until(lambda: local_id not in service._native_webrtc_live,
                   "Stop did not retire the adopted native carrier", 10)
        service.native_webrtc_offer(local_id, ice, channels)
        replacement = service._native_resources.require(local_id)
        assert replacement != local_physical
        # Inject a delayed terminal callback from the retired real JNI peer.
        service._handle_native_webrtc_event("closed", local_physical)
        assert service._native_resources.require(local_id) == replacement
        assert local_id in service._native_webrtc_live
        assert native.invoke("stats", replacement)["ice_connection_state"] != "closed"
        return True
    finally:
        if owner is not None:
            owner.stop()
            owner.wait()
        service.native_webrtc_close(local_id)
        native.close(remote_id)


def run_recovery(root, url, workspace=False, native=None, platform="android"):
    native = native or Native()
    workspace_id = str(uuid.uuid4()) if workspace else None
    keys = [secrets.token_bytes(32), secrets.token_bytes(32)]
    devices = ["a-" + uuid.uuid4().hex, "b-" + uuid.uuid4().hex]
    peers, supervisors = [], []
    with WorkerTransport(url) as transport:
        try:
            def open_peers():
                peers.extend(Peer(Path(root) / str(i), keys[i], devices[i], native, platform) for i in range(2))
                return [peers[i].seed_relationship(peers[1-i], workspace_id) for i in range(2)]

            contacts = open_peers()
            caps = [p.reconnect_consent_set(contacts[i], True, True)["capabilities"] for i, p in enumerate(peers)]
            for i, peer in enumerate(peers):
                if workspace:
                    document = create_workspace_reconnect_capability(peers[1-i].identity,
                        workspace_id=workspace_id, manifest_digest="a" * 64, capability=caps[1-i])
                    peer._receive_workspace_reconnect_capability(WorkspaceWirePayload(
                        kind="workspace_reconnect_capability", logical_id=str(uuid.uuid4()),
                        workspace_id=workspace_id, expires_at=int(time.time()) + 600, document=document))
                else:
                    peer.reconnect_capabilities_store(caps[1-i])
            assert all(p.reconnect_profiles()["profiles"][0]["effective"]["ready"] for p in peers), \
                "Seeded signed capabilities did not authorize both fixture peers"

            def launch():
                supervisors.extend(ObservedSupervisor(p) for p in peers)
                for supervisor in supervisors: supervisor.start()

            def sessions():
                found = []
                for supervisor in supervisors:
                    with supervisor._sessions_lock:
                        found.extend(supervisor._sessions.values())
                return found

            def connected():
                values = sessions()
                return len(values) == 2 and all(native.stats(s).get("attached") for s in values)

            def traffic():
                values = sessions()
                before = [native.stats(s).get("received_packets", 0) for s in values]
                assert all(native.send(s) for s in values)
                wait_until(lambda: all(native.stats(s).get("received_packets", 0) > before[i]
                                      for i, s in enumerate(values)), "Bidirectional native traffic missing", 10)

            def stop():
                for supervisor in supervisors: supervisor.stop()
                for supervisor in supervisors:
                    with supervisor._sessions_lock: workers = list(supervisor._workers.values())
                    for worker in workers: worker.join(12)
                    assert not any(w.is_alive() for w in workers), "Reconnect worker did not stop"
                supervisors.clear()

            launch()
            wait_until(connected, "Initial automatic encrypted negotiation failed")
            traffic()
            first = set(sessions())
            # Deterministic connectivity loss: close real SCTP transports and
            # fail HTTP. No radio settings or personal device data are touched.
            transport.offline = True
            for session in first: native.close(session)
            wait_until(lambda: all(s._retry_at for s in supervisors), "Offline attempts did not back off")
            assert not connected()
            transport.offline = False
            wait_until(connected, "Automatic recovery after connectivity return failed")
            assert first.isdisjoint(sessions())
            traffic()
            # Foreground owns new negotiations; background must remain quiet.
            for peer in peers: peer.lifecycle = "foreground"
            for session in sessions(): native.close(session)
            count, created = transport.requests, sum(p.created for p in peers)
            time.sleep(6)
            assert transport.requests == count and sum(p.created for p in peers) == created
            for peer in peers: peer.lifecycle = "background_available"
            wait_until(connected, "Background resume did not recover")
            traffic()
            # Reload sealed capabilities without another consent/bootstrap step.
            persisted = [p.store.list("reconnect_profile")[0]["local_capabilities"] for p in peers]
            stop()
            for peer in peers: peer.store.close()
            peers.clear()
            open_peers()
            assert [p.store.list("reconnect_profile")[0]["local_capabilities"] for p in peers] == persisted
            assert all(p.store.list("reconnect_profile")[0]["local_capabilities_expires_at"] == 0 for p in peers)
            launch()
            wait_until(connected, "Restart required another manual capability exchange")
            traffic()
            # Stop/lock removes every native session and prohibits more HTTP.
            last = sessions()
            stop()
            count = transport.requests
            time.sleep(1)
            assert transport.requests == count and all(not native.stats(s).get("attached") for s in last)
            return True
        except AssertionError as error:
            locations = [s.errors for s in supervisors]
            raise AssertionError(f"{error}; attempt failure locations: {locations}; native timings: {getattr(native, 'timings', [])}") from None
        finally:
            for supervisor in supervisors: supervisor.stop()
            for supervisor in supervisors:
                with supervisor._sessions_lock: workers = list(supervisor._workers.values())
                for worker in workers: worker.join(12)
            for peer in peers: peer.store.close()
