"""Private startup reconciliation; restored carriers still need a new owner lease."""
from collections import Counter
from uuid import uuid4

from .errors import ContactNotApproved, NativeUnavailable, ValidationError
from .native_carrier_evidence import matches_binding, validate_inventory


def matches_profile(binding, profile, contact):
    return (binding.profile_id == profile.get("id") and binding.contact_id == profile.get("contact_id")
            and binding.scope == profile.get("scope_kind", "contact")
            and binding.workspace_id == profile.get("workspace_id")
            and binding.local_device == profile.get("local_device_id")
            and binding.remote_device == profile.get("remote_device_id")
            and binding.peer_destination == contact.get("destination_hash")
            and (profile.get("allow_direct_ip_disclosure") or binding.ice_policy == "relay"))


def recovered_binding(service, session, profile, contact):
    binding = getattr(service, "_native_recovered_bindings", {}).get(session)
    journal = getattr(service, "_carrier_journal", None)
    if (binding is not None and journal is not None and matches_profile(binding, profile, contact)
            and service._native_resources.current(session, binding.resource) and binding in journal.bindings()):
        return binding
    return None


def _eligible(service, binding, admit):
    try:
        profile = service._reconnect_profile(binding.profile_id)
        contact = service._reconnect_contact(profile["contact_id"])
        reasons = set(service._reconnect_profile_public(profile)["effective"].get("reasons") or ())
        automatic_only = {"mailbox_not_configured", "consent_missing", "peer_consent_missing"}
        return bool(profile.get("state") != "stopped" and not reasons - automatic_only
                    and matches_profile(binding, profile, contact) and admit(profile))
    except (ContactNotApproved, ValidationError, KeyError):
        return False


def _install(service, binding, observation):
    from .native_webrtc_control import bind_control_profile
    session = "recovered-" + uuid4().hex
    with service._native_webrtc_lock:
        service._native_resources.restore(session, binding.resource)
        service._native_webrtc_live.add(session)
        service._native_webrtc_descriptions[session] = {"ice_policy": binding.ice_policy}
        service._native_webrtc_peers[session] = binding.peer_destination
        control = {}
        bind_control_profile(control, service._reconnect_profile(binding.profile_id))
        label = next((channel["label"] for channel in observation["channels"]
                      if channel["label"] in {"mesh-onboarding", "meshchat-reconnect"} and channel["state"] == "open"), None)
        if label is not None:
            control["label"] = label
        service._native_webrtc_controls[session] = control
        service._native_recovered_bindings[session] = binding


def _close_resources(host, resources):
    failure = None
    for resource in resources:
        try:
            host.close(resource)
        except Exception as error:
            failure = error
    if failure is not None:
        raise NativeUnavailable("Orphan carrier retirement failed") from None


def reconcile_carriers(service, admit):
    """One bounded startup pass, including orphans with no remaining profile."""
    journal = service._carrier_journal
    host = service._native_webrtc_host()
    try:
        with service._dispatch_lock:
            bindings = journal.bindings()
        inventory = validate_inventory(host.inventory())
        resources = {value["resource"]: value for value in inventory["resources"]}
        profiles = Counter(binding.profile_id for binding in bindings)
        with service._dispatch_lock:
            if host is not service._native_webrtc_host():
                raise ContactNotApproved("Carrier recovery binding changed")
            current = journal.bindings()
            candidates = [binding for binding in bindings if profiles[binding.profile_id] == 1
                          and binding in current
                          and matches_binding(binding, inventory["adapter_epoch"], resources.get(binding.resource))
                          and _eligible(service, binding, admit)]
        selected = {binding.resource for binding in candidates}
        _close_resources(host, resources.keys() - selected)
        with service._dispatch_lock:
            if host is not service._native_webrtc_host():
                raise ContactNotApproved("Carrier recovery host changed")
            revision = journal.revision()
            current = journal.bindings()
            retained = [binding for binding in candidates if binding in current and _eligible(service, binding, admit)]
            journal.reconcile(retained, revision)
            for binding in retained:
                _install(service, binding, resources[binding.resource])
        _close_resources(host, selected - {binding.resource for binding in retained})
    except Exception:
        # No partially restored set can become usable after an unknown outcome.
        # The platform host owns final disposal when the private pipe is lost.
        host.shutdown()
        raise
