"""Checkpoint a leased carrier through the private native and vault ports."""
from .carrier_journal import CarrierBinding
from .errors import ContactNotApproved, NativeUnavailable
from .native_carrier_evidence import description_hash, matches_binding, validate_inventory
from .carrier_recovery import recovered_binding


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
        recovered = recovered_binding(service, session, profile, peer)
        if recovered is None and (not local or not remote):
            raise NativeUnavailable("Carrier descriptions are incomplete")
        return dict(resource=service._native_resources.require(session), profile_id=profile_id,
                    adapter_epoch=recovered.adapter_epoch if recovered else None,
                    contact_id=profile["contact_id"], scope=profile.get("scope_kind", "contact"),
                    workspace_id=profile.get("workspace_id"), local_device=profile.get("local_device_id"),
                    remote_device=profile.get("remote_device_id"), peer_destination=peer["destination_hash"],
                    ice_policy=description.get("ice_policy"),
                    local_type=recovered.local_type if recovered else "answer" if description.get("remote_offer") else "offer",
                    local_hash=recovered.local_hash if recovered else description_hash(local),
                    remote_hash=recovered.remote_hash if recovered else description_hash(remote))


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
        if context["adapter_epoch"] not in (None, inventory["adapter_epoch"]):
            raise ContactNotApproved("Recovered carrier adapter changed")
        binding = CarrierBinding(**{**context, "adapter_epoch": inventory["adapter_epoch"]})
        if not matches_binding(binding, inventory["adapter_epoch"], resource):
            raise NativeUnavailable("Carrier checkpoint observation does not match its binding")
        journal.save(binding, revision)
