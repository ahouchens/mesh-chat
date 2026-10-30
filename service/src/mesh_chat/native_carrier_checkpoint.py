"""Checkpoint a leased carrier through the private native and vault ports."""
from .carrier_journal import CarrierBinding
from .errors import ContactNotApproved, NativeUnavailable
from .native_carrier_evidence import description_hash, validate_inventory


def _binding_context(service, session):
    if not service._native_carrier_authorized(session):
        raise ContactNotApproved("Carrier checkpoint has no current lease")
    with service._native_webrtc_lock:
        if session not in service._native_webrtc_live or session in service._native_webrtc_creating:
            raise NativeUnavailable("Carrier checkpoint is unavailable")
        profile_id = next((key for key, value in service._native_webrtc_profile_sessions.items() if value == session), None)
        if profile_id is None:
            raise ContactNotApproved("Carrier checkpoint has no profile")
        profile = service._reconnect_profile(profile_id)
        peer = service._reconnect_contact(profile["contact_id"])
        description = service._native_webrtc_descriptions.get(session, {})
        local = description.get("local")
        remote = description.get("remote_offer") or description.get("remote_answer")
        if not local or not remote:
            raise NativeUnavailable("Carrier descriptions are incomplete")
        return dict(resource=service._native_resources.require(session), profile_id=profile_id,
                    contact_id=profile["contact_id"], scope=profile.get("scope_kind", "contact"),
                    workspace_id=profile.get("workspace_id"), local_device=profile.get("local_device_id"),
                    remote_device=profile.get("remote_device_id"), peer_destination=peer["destination_hash"],
                    ice_policy=description.get("ice_policy"), local_type="answer" if description.get("remote_offer") else "offer",
                    local_hash=description_hash(local), remote_hash=description_hash(remote))


def checkpoint_carrier(service, session, journal):
    with service._dispatch_lock:
        context = _binding_context(service, session)
        revision = journal.revision()
        host = service._native_webrtc_host()
    # Native I/O must not hold the dispatch lock: Stop and revocation can fence
    # the lease while the inventory is blocked in the private transport pipe.
    inventory = validate_inventory(host.inventory())
    with service._dispatch_lock:
        if host is not service._native_webrtc_host() or context != _binding_context(service, session):
            raise ContactNotApproved("Carrier checkpoint binding changed")
        resource = next((value for value in inventory["resources"] if value["resource"] == context["resource"]), None)
        if (resource is None or resource["pending"] or resource["data_channel_state"] != "open"
                or resource["ice_connection_state"] not in {"connected", "completed"}
                or resource["signaling_state"] != "stable"
                or resource["ice_policy"] != context["ice_policy"]
                or resource["local_type"] != context["local_type"]
                or resource["remote_type"] != ("answer" if context["local_type"] == "offer" else "offer")
                or resource["local_sdp_sha256"] != context["local_hash"]
                or resource["remote_sdp_sha256"] != context["remote_hash"]):
            raise NativeUnavailable("Carrier checkpoint observation does not match its binding")
        journal.save(CarrierBinding(adapter_epoch=inventory["adapter_epoch"], **context), revision)
