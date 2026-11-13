"""Explicit first-time contact approval through two frozen service entrypoints."""
import json
from time import sleep

from packaged_transport_probe import Controller, seed_profiles, start, connect, ready, exchange_message, fixture_directory
from mesh_chat.vault import VaultStore


def unapproved_invitation(controller, invitation_id):
    snapshots = [controller.call(slot, "snapshot") for slot in range(2)]
    if any(snapshot["contacts"] or snapshot["messages"] for snapshot in snapshots):
        raise AssertionError("Unapproved pairing created contact or message authority")
    invitations = snapshots[1]["contact_invitations"]
    if (len(invitations) != 1 or invitations[0]["id"] != invitation_id
            or invitations[0]["state"] != "pending" or invitations[0]["expired"]):
        raise AssertionError("Pending invitation was lost or changed without approval")


def retired_sessions(controller):
    for slot, session in enumerate(("manual-peer-zero", "manual-peer-one")):
        controller.reject(slot, "native_webrtc_stats", "native_unavailable", session_id=session)
        controller.reject(slot, "native_webrtc_control", "native_unavailable", session_id=session,
                          label="mesh-onboarding", text='{"type":"connection_capabilities_request"}')


def cancel_and_restart(controller, fixtures, invitation_id):
    controller.phase = "cancel_unapproved_pairing"
    for slot, session in enumerate(("manual-peer-zero", "manual-peer-one")):
        if controller.call(slot, "native_webrtc_close", session_id=session) != {"state": "closed"}:
            raise AssertionError("Unapproved carrier was not released")
    retired_sessions(controller)
    unapproved_invitation(controller, invitation_id)
    for slot in range(2):
        if controller.action(slot, "counts").get("close", 0) < 1:
            raise AssertionError("Host did not execute native disposal")
    controller.checks.append("cancelled_pairing_retires_native_sessions")

    controller.phase = "restart_unapproved_pairing"
    controller.action(1, "crash")
    start(controller, 1, fixtures[1])
    retired_sessions(controller)
    unapproved_invitation(controller, invitation_id)
    controller.checks.append("pending_invitation_survives_restart_without_approval")
    sleep(1)  # Replacement service completes its private inventory before allocation.
    connect(controller, fixtures, configure_contacts=False)
    unapproved_invitation(controller, invitation_id)


def approved_path(controller, fixtures):
    controller.phase = "approved_path"
    try:
        ready(controller, fixtures)
    except TimeoutError:
        # Keep both strings within the existing host's 64-character, identifier
        # only diagnostic boundary. No raw stats, identities, SDP or paths leave
        # this process. dN is channel state (wait/close/missing abbreviations);
        # aN is attachment (1/0/u), cN counts host close calls, sN is the one
        # outbound contact_accept state (q/s/r/d/f/e/n/m/u: queued/sending/
        # endpoint/delivered/failed/expired/none/multiple/unknown).
        # calls. The error code retains authoritative carrier/bridge categories.
        states, native = [], []
        for slot, session in enumerate(("manual-peer-zero", "manual-peer-one")):
            carrier, bridge, channel, attached, closes, acceptance = "unknown", "unknown", "unknown", "u", "u", "u"
            try:
                profiles = controller.call(slot, "reconnect_profiles")["profiles"]
                profile = next((item for item in profiles if item.get("contact_id") == fixtures[slot][2]), {})
                connection = profile.get("connection") or {}
                carrier = connection.get("carrier", "absent")
                bridge = connection.get("bridge", "detached")
            except Exception:
                pass
            try:
                stats = controller.call(slot, "native_webrtc_stats", session_id=session)
                channel = stats.get("data_channel_state", "unknown")
                if type(stats.get("attached")) is bool: attached = str(int(stats["attached"]))
            except Exception:
                channel = "unavailable"
            try:
                count = controller.action(slot, "counts").get("close", 0)
                if type(count) is int and count >= 0: closes = str(min(count, 999))
            except Exception:
                pass
            try:
                messages = controller.call(slot, "snapshot")["messages"]
                accepts = [item for item in messages if item.get("kind") == "contact_accept" and item.get("direction") == "outbound"]
                if not accepts: acceptance = "n"
                elif len(accepts) > 1: acceptance = "m"
                else:
                    state = accepts[0].get("state")
                    if isinstance(state, str):
                        acceptance = {"queued": "q", "sending": "s", "received_by_endpoint": "r",
                            "delivered": "d", "failed": "f", "expired": "e"}.get(state, "u")
            except Exception:
                pass
            if not isinstance(carrier, str) or carrier not in {"absent", "open", "suspect", "closing"}: carrier = "unknown"
            if not isinstance(bridge, str) or bridge not in {"detached", "attaching", "path_pending", "ready", "restoring"}: bridge = "unknown"
            if not isinstance(channel, str) or channel not in {"open", "connecting", "closing", "closed", "unavailable"}: channel = "unknown"
            channel = {"connecting": "wait", "closing": "close", "unavailable": "missing"}.get(channel, channel)
            states.append(f"p{slot}_{carrier}_{bridge}")
            native.append(f"d{slot}{channel}_a{slot}{attached}_c{slot}{closes}_s{slot}{acceptance}")
        controller.phase = "approved_path_" + "_".join(native)
        controller.error_code = "_".join(states)
        raise


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
        received = controller.call(1, "snapshot")["contact_invitations"][0]
        unapproved_invitation(controller, received["id"])
        cancel_and_restart(controller, fixtures, received["id"])
        controller.phase = "explicit_acceptance"
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
        if (negotiations[0].get("createOffer") != 2 or negotiations[0].get("applyAnswer") != 2
                or negotiations[1].get("acceptOffer") != 2):
            raise AssertionError("Host did not observe the pairing negotiation")
        # Both people separately opt into direct-IP messaging after approval.
        for slot, (_, _, contact_id) in enumerate(fixtures):
            controller.call(slot, "reconnect_consent_set", contact_id=contact_id,
                auto_reconnect=False, allow_direct_ip_disclosure=True)
        approved_path(controller, fixtures)
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
