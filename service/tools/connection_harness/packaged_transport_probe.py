"""Real frozen peers and WebView2; pre-approved fixture, not pairing evidence.

Only fixture setup reads/writes vault records. All running-peer interactions use
ordinary service commands through the production host. No alternate network
route is configured. Keys, SDP, identities and message contents stay local.
"""
import base64
from contextlib import contextmanager
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep, time
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import RNS
from mesh_chat.carrier_journal import CarrierJournal
from mesh_chat.invitations import readable_fingerprint
from mesh_chat.ipc import FrameWriter, read_frame
from mesh_chat.models import Contact, Profile, TrustState
from mesh_chat.reticulum_config import NetworkSettings
from mesh_chat.vault import VaultStore


class Controller:
    def __init__(self):
        self.writer = FrameWriter(sys.stdout.buffer)
        self.phase = "fixture"
        self.checks = []
        self.error_code = None
        self.counts = {"processes_started": 0, "forced_exits": 0, "authenticated_receipts": 0}

    def _response(self, slot, action, **arguments):
        request_id = uuid4().hex
        self.writer.write({"id": request_id, "slot": slot, "action": action, **arguments})
        response = read_frame(sys.stdin.buffer)
        if (not isinstance(response, dict) or response.get("id") != request_id
                or type(response.get("ok")) is not bool):
            raise RuntimeError("Host response is invalid")
        return response

    def _failed(self, response):
        code = response.get("error")
        if isinstance(code, str) and len(code) <= 64 and code.isidentifier():
            self.error_code = code
        raise RuntimeError("Host command failed")

    def action(self, slot, action, **arguments):
        response = self._response(slot, action, **arguments)
        if not response["ok"]:
            self._failed(response)
        if action == "start": self.counts["processes_started"] += 1
        if action == "crash": self.counts["forced_exits"] += 1
        return response["result"]

    def call(self, slot, command, **payload):
        return self.action(slot, "call", command=command, payload=payload)

    def reject(self, slot, command, expected_error, **payload):
        response = self._response(slot, "call", command=command, payload=payload)
        if response["ok"] or response.get("error") != expected_error:
            self._failed(response)

    def wait(self, predicate, seconds=30):
        deadline = monotonic() + seconds
        while not predicate():
            if monotonic() >= deadline:
                raise TimeoutError("Qualification condition did not arrive")
            sleep(.2)


def cleanup_directory(directory, *, clock=monotonic, pause=sleep):
    deadline = clock() + 8
    while True:
        try:
            directory.cleanup()
            return
        except PermissionError:
            # Windows releases exited-process file handles asynchronously.
            # This retries only fixture cleanup; scenario failures are never retried.
            if clock() >= deadline: raise
            pause(.1)


@contextmanager
def fixture_directory(controller, prefix):
    directory = TemporaryDirectory(prefix=prefix)
    try:
        yield Path(directory.name)
    finally:
        if sys.exc_info()[0] is None: controller.phase = "cleanup"
        cleanup_directory(directory)


def seed_profiles(directory):
    identities = [RNS.Identity(), RNS.Identity()]
    profiles = []
    for index, identity in enumerate(identities):
        profiles.append(Profile(f"Packaged peer {index}",
            base64.urlsafe_b64encode(identity.get_public_key()).decode(), identity.hash.hex(),
            RNS.Destination.hash(identity, "lxmf", "delivery").hex(),
            readable_fingerprint(identity.get_public_key()), time()))
    fixtures = []
    for index, identity in enumerate(identities):
        peer = profiles[1 - index]
        contact_id = str(UUID(bytes=RNS.Identity.full_hash(
            b"mesh-chat:contact:" + bytes.fromhex(peer.destination_hash))[:16]))
        contact = Contact(contact_id, peer.display_name, peer.public_identity,
            peer.identity_hash, peer.destination_hash, peer.fingerprint, TrustState.APPROVED,
            created_at=time(), updated_at=time())
        path, key = directory / str(index), os.urandom(32)
        store = VaultStore(path, key)
        try:
            store.put_many([
                ("identity", "local", {"private_key": base64.urlsafe_b64encode(identity.get_private_key()).decode()}),
                ("profile", "local", profiles[index].to_dict()),
                ("contact", contact_id, contact.to_dict()),
                ("settings", "network", NetworkSettings(nearby_discovery=False, lan_fallback=False).to_dict()),
            ])
        finally:
            store.close()
        fixtures.append((path, key, contact_id))
    return fixtures


def start(controller, slot, fixture):
    path, key, _ = fixture
    controller.action(slot, "start")
    controller.call(slot, "initialize", profile_dir=str(path),
        vault_key=base64.b64encode(key).decode(), display_name=f"Packaged peer {slot}",
        parent_pid=int(sys.argv[1]))


def connect(controller, fixtures, *, configure_contacts=True):
    for slot, (_, _, contact_id) in enumerate(fixtures if configure_contacts else []):
        controller.call(slot, "reconnect_consent_set", contact_id=contact_id,
            auto_reconnect=False, allow_direct_ip_disclosure=True)
        controller.wait(lambda: any(profile.get("connection") is not None
            for profile in controller.call(slot, "reconnect_profiles")["profiles"]))
    ice = {"iceServers": [], "iceTransportPolicy": "all"}
    channels = [{"label": "mesh-reticulum", "ordered": True, "binary": True},
                {"label": "mesh-onboarding", "ordered": True, "binary": False}]
    controller.phase = "offer"
    offer = controller.call(0, "native_webrtc_offer", session_id="manual-peer-zero", ice=ice, channels=channels)
    signed_offer = controller.call(0, "webrtc_onboarding_offer", sdp=offer["sdp"], dtls_fingerprint=offer["fingerprint"])
    controller.phase = "answer"
    answer = controller.call(1, "native_webrtc_accept", session_id="manual-peer-one", offer_sdp=offer["sdp"], ice=ice, channels=channels)
    controller.phase = "sign_answer"
    signed_answer = controller.call(1, "webrtc_onboarding_answer", offer_document=signed_offer["document"],
        sdp=answer["sdp"], dtls_fingerprint=answer["fingerprint"])
    controller.phase = "bind_answerer"
    controller.call(1, "native_webrtc_bind_onboarding", session_id="manual-peer-one", offer_document=signed_offer["document"])
    controller.phase = "bind_offerer"
    controller.call(0, "native_webrtc_bind_onboarding", session_id="manual-peer-zero",
        offer_document=signed_offer["document"], answer_document=signed_answer["document"])
    controller.phase = "apply_answer"
    controller.call(0, "native_webrtc_apply_answer", session_id="manual-peer-zero", answer_sdp=answer["sdp"])


def ready(controller, fixtures):
    controller.wait(lambda: all(controller.call(slot, "reconnect_path_status", contact_id=fixture[2])["ready"]
        for slot, fixture in enumerate(fixtures)))


def exchange_message(controller, fixtures, sender):
    message = controller.call(sender, "send_message", contact_id=fixtures[sender][2], text="Packaged qualification " + uuid4().hex)
    def delivered():
        outgoing = controller.call(sender, "snapshot")["messages"]
        incoming = controller.call(1 - sender, "snapshot")["messages"]
        return (any(item["id"] == message["id"] and item["state"] == "delivered" for item in outgoing)
            and sum(item["id"] == message["id"] and item["direction"] == "inbound" for item in incoming) == 1)
    controller.wait(delivered)
    controller.counts["authenticated_receipts"] += 1
    return message["id"]


def stopped_bindings(fixture):
    store = VaultStore(fixture[0], fixture[1])
    try:
        bindings = CarrierJournal(store).bindings()
        if len(bindings) != 1:
            raise AssertionError("Expected one durable carrier binding")
        return bindings
    finally:
        store.close()


def exercise(controller, directory):
    fixtures = seed_profiles(directory)
    try:
        for slot in range(2):
            controller.phase = f"initialize_{slot}"
            start(controller, slot, fixtures[slot])
        connect(controller, fixtures)
        controller.phase = "messaging_ready"
        ready(controller, fixtures)
        controller.phase = "receipts_before_crash"
        original = exchange_message(controller, fixtures, 0)
        exchange_message(controller, fixtures, 1)
        controller.checks.append("bidirectional_authenticated_receipts")
        counts = controller.action(0, "counts")
        if counts.get("createOffer") != 1 or counts.get("applyAnswer") != 1:
            raise AssertionError("Host did not observe the initial negotiation")
        controller.phase = "crash"
        controller.action(0, "crash")
        controller.phase = "initial_checkpoint"
        bindings = stopped_bindings(fixtures[0])
        controller.phase = "restart"
        start(controller, 0, fixtures[0])
        ready(controller, fixtures)
        controller.phase = "receipt_after_restart"
        exchange_message(controller, fixtures, 0)
        messages = controller.call(0, "snapshot")["messages"]
        if sum(item["id"] == original and item["state"] == "delivered" for item in messages) != 1:
            raise AssertionError("Durable message was lost or duplicated")
        controller.checks.append("durable_messages_and_receipts_after_crash")
        current = controller.action(0, "counts")
        for operation in ("createOffer", "acceptOffer", "applyAnswer"):
            if current.get(operation, 0) != counts.get(operation, 0):
                raise AssertionError("Recovery negotiated a replacement carrier")
        controller.action(0, "crash")
        controller.phase = "recovered_checkpoint"
        if stopped_bindings(fixtures[0]) != bindings:
            raise AssertionError("Recovery replaced the physical binding")
        controller.checks.append("exact_carrier_reuse")
        controller.phase = "shutdown"
        controller.call(1, "shutdown")
    finally:
        for slot in range(2):
            controller.action(slot, "stop")


def main():
    controller = Controller()
    try:
        with fixture_directory(controller, "mesh-packaged-transport-") as directory:
            exercise(controller, directory)
        result = {"ok": True, "checks": controller.checks}
    except Exception as error:
        result = {"ok": False, "checks": controller.checks, "phase": controller.phase,
                  "error_type": controller.error_code or type(error).__name__}
    controller.writer.write({"action": "finish", "counts": controller.counts, **result})


if __name__ == "__main__":
    main()
