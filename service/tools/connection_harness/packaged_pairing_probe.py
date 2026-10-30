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
        # Both people separately opt into direct-IP messaging after approval.
        # Replacing the limited onboarding scope preserves that consent boundary.
        for slot, session in enumerate(("manual-peer-zero", "manual-peer-one")):
            controller.call(slot, "native_webrtc_close", session_id=session)
        connect(controller, fixtures)
        controller.phase = "approved_messaging"
        ready(controller, fixtures)
        exchange_message(controller, fixtures, 0)
        exchange_message(controller, fixtures, 1)
        controller.checks.append("paired_bidirectional_authenticated_receipts")
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
