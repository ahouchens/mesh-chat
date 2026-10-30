"""Explicit first-time contact approval through two frozen service entrypoints."""
import json
from time import sleep

from packaged_transport_probe import Controller, seed_profiles, start, connect, ready, exchange_message, fixture_directory
from mesh_chat.vault import VaultStore


def exercise(controller, directory):
    fixtures = seed_profiles(directory)
    for path, key, contact in fixtures:
        store = VaultStore(path, key)
        try:
            store.delete("contact", contact)
        finally:
            store.close()
    try:
        for slot in range(2): start(controller, slot, fixtures[slot])
        sleep(1)  # Private inventory completes before manual allocation is admitted.
        connect(controller, fixtures, configure_contacts=False)
        controller.phase = "invitation"
        invitation = controller.call(0, "create_invitation", connection_mode="webrtc")
        controller.wait(lambda: controller.call(0, "native_webrtc_control", session_id="manual-peer-zero",
            label="mesh-onboarding", text=json.dumps({"type": "contact_invitation", "document": invitation["file"]}))["accepted"])
        controller.wait(lambda: len(controller.call(1, "snapshot")["contact_invitations"]) == 1)
        # Receipt of a signed invitation alone must create no approved contact.
        if controller.call(0, "snapshot")["contacts"] or controller.call(1, "snapshot")["contacts"]:
            raise AssertionError("An invitation silently created contact authority")
        controller.phase = "explicit_acceptance"
        received = controller.call(1, "snapshot")["contact_invitations"][0]
        accepted = controller.call(1, "decide_contact_invitation", invitation_id=received["id"], accept=True)
        if accepted["trust"] != "awaiting_consent":
            raise AssertionError("Acceptance silently granted remote approval")
        controller.phase = "contact_request"
        controller.wait(lambda: any(contact["trust"] == "pending_request" for contact in controller.call(0, "snapshot")["contacts"]))
        controller.phase = "explicit_approval"
        controller.call(0, "approve_request", contact_id=fixtures[0][2])
        controller.wait(lambda: all(any(contact["trust"] == "approved" for contact in controller.call(slot, "snapshot")["contacts"])
            for slot in range(2)))
        controller.checks.append("explicit_pairing_without_preapproved_contacts")
        if any(controller.call(slot, "reconnect_path_status", contact_id=fixture[2])["ready"]
                for slot, fixture in enumerate(fixtures)):
            raise AssertionError("Pairing granted direct-IP messaging without consent")
        negotiations = [controller.action(slot, "counts") for slot in range(2)]
        if (negotiations[0].get("createOffer") != 1 or negotiations[0].get("applyAnswer") != 1
                or negotiations[1].get("acceptOffer") != 1):
            raise AssertionError("Host did not observe the pairing negotiation")
        # Both people separately opt into direct-IP messaging after approval.
        for slot, (_, _, contact_id) in enumerate(fixtures):
            controller.call(slot, "reconnect_consent_set", contact_id=contact_id,
                auto_reconnect=False, allow_direct_ip_disclosure=True)
        controller.phase = "approved_path"
        try:
            ready(controller, fixtures)
        except TimeoutError:
            states = []
            for slot in range(2):
                profiles = controller.call(slot, "reconnect_profiles")["profiles"]
                connection = profiles[0].get("connection") or {} if profiles else {}
                carrier = connection.get("carrier", "absent")
                bridge = connection.get("bridge", "detached")
                if carrier not in {"absent", "open", "suspect", "closing"}: carrier = "unknown"
                if bridge not in {"detached", "attaching", "path_pending", "ready", "restoring"}: bridge = "unknown"
                states.append(f"p{slot}_{carrier}_{bridge}")
            controller.error_code = "_".join(states)
            raise
        controller.phase = "receipt_from_inviter"
        exchange_message(controller, fixtures, 0)
        controller.phase = "receipt_from_acceptor"
        exchange_message(controller, fixtures, 1)
        controller.checks.append("paired_bidirectional_authenticated_receipts")
        for slot in range(2):
            counts = controller.action(slot, "counts")
            for operation in ("createOffer", "acceptOffer", "applyAnswer", "close"):
                if counts.get(operation, 0) != negotiations[slot].get(operation, 0):
                    raise AssertionError("Pairing replaced its initial carrier")
        controller.checks.append("continuous_pairing_carrier_transfer")
        for slot in range(2): controller.call(slot, "shutdown")
    finally:
        for slot in range(2): controller.action(slot, "stop")


def main():
    controller = Controller()
    try:
        with fixture_directory(controller, "mesh-packaged-pairing-") as directory:
            exercise(controller, directory)
        result = {"ok": True, "checks": controller.checks}
    except Exception as error:
        result = {"ok": False, "checks": controller.checks, "phase": controller.phase,
                  "error_type": controller.error_code or type(error).__name__}
    controller.writer.write({"action": "finish", "scenario": "explicit_pairing", "counts": controller.counts, **result})


if __name__ == "__main__": main()
