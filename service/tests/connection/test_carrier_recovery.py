"""Startup reconciliation uses protected bindings and current domain authority."""
from copy import deepcopy
from dataclasses import replace
from threading import Event, RLock
from time import monotonic
from types import SimpleNamespace

import pytest

from mesh_chat.carrier_journal import CarrierBinding, CarrierJournal
from mesh_chat.carrier_recovery import reconcile_carriers
from mesh_chat.errors import ContactNotApproved, NativeUnavailable, ValidationError
from mesh_chat.native_resource_registry import NativeResourceRegistry
from mesh_chat.native_webrtc_service import NativeWebRTCServiceMixin
from mesh_chat.vault import VaultStore


@pytest.fixture
def recovery(tmp_path):
    with VaultStore(tmp_path, b"x" * 32, allow_unprotected_for_tests=True) as store:
        service = NativeWebRTCServiceMixin()
        service._connection_policy = "shared-native"
        service._dispatch_lock = RLock()
        service._native_webrtc_lock = RLock()
        service._native_resources = NativeResourceRegistry()
        for name in ("profile_sessions", "descriptions", "peers", "controls", "sessions"):
            setattr(service, "_native_webrtc_" + name, {})
        service._native_webrtc_live = set()
        service._native_webrtc_creating = set()
        service._native_recovered_bindings = {}
        service._carrier_journal = CarrierJournal(store)
        service.store = store
        service.profile = dict(id="profile", contact_id="contact", local_device_id="local", remote_device_id="remote", state="waiting_for_peer", allow_direct_ip_disclosure=False)
        service.contact = dict(destination_hash="b" * 32)
        service._reconnect_profile = lambda _: service.profile
        service._reconnect_contact = lambda _: service.contact
        service._reconnect_profile_public = lambda _: {"effective": {"reasons": ["mailbox_not_configured", "consent_missing"]}}
        binding = CarrierBinding("native-survivor", "a" * 32, "profile", "contact", "contact", None,
                                 "local", "remote", "b" * 32, "relay", "offer", "c" * 64, "d" * 64)
        service._carrier_journal.save(binding, service._carrier_journal.revision())
        observation = dict(resource=binding.resource, ice_policy="relay", pending=False,
                           ice_connection_state="connected", signaling_state="stable", data_channel_state="open",
                           channels=[dict(label="mesh-reticulum", state="open"), dict(label="mesh-onboarding", state="open")],
                           local_type="offer", remote_type="answer", local_sdp_sha256=binding.local_hash, remote_sdp_sha256=binding.remote_hash)
        inventory = dict(v=1, adapter_epoch=binding.adapter_epoch, resources=[observation])
        closed, faults = [], []
        service._native_host = SimpleNamespace(inventory=lambda: deepcopy(inventory), close=closed.append, shutdown=lambda: faults.append(True))
        service.activated = []
        service._native_host.activate = service.activated.append
        yield service, binding, inventory, closed, faults


def test_reconciled_resource_still_requires_supervisor_adoption_and_a_fresh_lease(recovery):
    service, binding, _, closed, faults = recovery
    reconcile_carriers(service, lambda _: True)
    session = service._native_resources.resolve(binding.resource)
    assert session and session != binding.resource
    assert service.native_manual_carrier_authorized("profile")
    assert not service._native_webrtc_profile_sessions
    assert service.claim_native_reconnect_carrier("profile", "local", "remote") == session
    assert service._native_webrtc_descriptions[session] == {"ice_policy": "relay"}
    service._connection_runtime = SimpleNamespace(permits_carrier=lambda *_: False)
    with pytest.raises(ContactNotApproved): service.webrtc_attach_native(session)
    assert not service.activated
    service._connection_runtime.permits_carrier = lambda *_: True
    attached = []
    service._attach_native_bridge = attached.append
    service.webrtc_attach_native(session)
    assert attached == [session]
    assert service.activated == [binding.resource]
    assert service._carrier_journal.bindings() == (binding,)
    assert not closed and not faults


@pytest.mark.parametrize("fault", ["stopped", "device", "peer", "scope", "expired", "removed", "adapter", "hash", "pending", "policy", "fenced"])
def test_invalid_survivor_is_retired_without_regaining_authority(recovery, fault):
    service, binding, inventory, closed, faults = recovery
    if fault == "stopped": service.profile["state"] = "stopped"
    elif fault == "device": service.profile["remote_device_id"] = "replacement"
    elif fault == "peer": service.contact["destination_hash"] = "e" * 32
    elif fault == "scope": service.profile.update(scope_kind="workspace", workspace_id="team")
    elif fault == "expired": service._reconnect_profile_public = lambda _: {"effective": {"reasons": ["capability_expired"]}}
    elif fault == "removed":
        def removed(_): raise ValidationError("Removed")
        service._reconnect_profile = removed
    elif fault == "adapter": inventory["adapter_epoch"] = "e" * 32
    elif fault == "hash": inventory["resources"][0]["remote_sdp_sha256"] = "e" * 64
    elif fault == "pending": inventory["resources"][0]["pending"] = True
    elif fault == "policy": inventory["resources"][0]["ice_policy"] = "all"
    reconcile_carriers(service, lambda _: fault != "fenced")
    assert closed == [binding.resource] and not faults
    assert not service._native_webrtc_live and not service._carrier_journal.bindings()


def test_activation_rechecks_authority_before_bridge_attachment(recovery):
    service, binding, _, _, _ = recovery
    reconcile_carriers(service, lambda _: True)
    session = service.claim_native_reconnect_carrier("profile", "local", "remote")
    service._connection_runtime = SimpleNamespace(permits_carrier=lambda *_: True)
    def activate(resource):
        assert resource == binding.resource
        assert not service._dispatch_lock._is_owned()
        service._connection_runtime.permits_carrier = lambda *_: False
    service._native_host.activate = activate
    with pytest.raises(ContactNotApproved): service.webrtc_attach_native(session)
    assert not service._native_webrtc_sessions


def test_orphans_are_retired_even_without_any_saved_profile(recovery):
    service, binding, _, closed, _ = recovery
    service._carrier_journal.invalidate()
    reconcile_carriers(service, lambda _: pytest.fail("No binding can imply a profile"))
    assert closed == [binding.resource]


def test_recovered_hashes_cannot_checkpoint_the_same_handle_in_another_adapter(recovery):
    service, binding, inventory, _, _ = recovery
    reconcile_carriers(service, lambda _: True)
    session = service.claim_native_reconnect_carrier("profile", "local", "remote")
    service._connection_runtime = SimpleNamespace(permits_carrier=lambda *_: True)
    service._attach_native_bridge = lambda _: pytest.fail("Changed adapter cannot attach")
    inventory["adapter_epoch"] = "e" * 32
    with pytest.raises(ContactNotApproved): service.webrtc_attach_native(session)
    assert service._carrier_journal.bindings() == (binding,)


def test_stop_and_start_while_inventory_is_pending_cannot_restore_old_checkpoint(recovery):
    service, binding, inventory, closed, faults = recovery
    def raced():
        service._carrier_journal.invalidate("contact")
        return deepcopy(inventory)
    service._native_host.inventory = raced
    reconcile_carriers(service, lambda _: True)
    assert closed == [binding.resource] and not faults and not service._native_webrtc_live


def test_ambiguous_same_profile_survivors_are_both_retired(recovery):
    service, binding, inventory, closed, _ = recovery
    second = replace(binding, resource="native-other")
    service._carrier_journal.save(second, service._carrier_journal.revision())
    inventory["resources"].append({**inventory["resources"][0], "resource": second.resource})
    reconcile_carriers(service, lambda _: True)
    assert set(closed) == {binding.resource, second.resource}
    assert not service._native_webrtc_live and not service._carrier_journal.bindings()


def test_failed_orphan_close_quarantines_instead_of_admitting_survivors(recovery):
    service, _, inventory, closed, faults = recovery
    inventory["resources"].append({**inventory["resources"][0], "resource": "orphan"})
    def fail(resource):
        closed.append(resource)
        raise NativeUnavailable("Close failed")
    service._native_host.close = fail
    with pytest.raises(NativeUnavailable): reconcile_carriers(service, lambda _: True)
    assert faults and not service._native_webrtc_live


def test_production_runtime_prepares_and_adopts_survivor_without_negotiating(recovery, monkeypatch):
    from mesh_chat.connection.composition import native_runtime
    import json
    service, binding, _, closed, faults = recovery
    service._carrier_recovery_pending = True
    service._shutdown = Event()
    service._identity = object()
    service._workspace_lifecycle_state = lambda: {"state": "foreground"}
    service._background_availability_enabled = lambda: True
    service.profile["active"] = False
    service.reconnect_profiles = lambda: {"profiles": [{**service.profile, "auto_reconnect": False,
        "peer_auto_reconnect": False, "trust": "approved", **service._reconnect_profile_public(service.profile)}]}
    def forbidden(*_args, **_kwargs): pytest.fail("Survivor recovery cannot negotiate or grant consent")
    for method in ("reconnect_start", "reconnect_request_create", "reconnect_offer_create", "reconnect_answer_create",
                   "verify_reconnect_request", "verify_reconnect_offer", "verify_reconnect_answer",
                   "reconnect_publish", "reconnect_fetch", "call_ice_servers"):
        setattr(service, method, forbidden)
    service.reconnect_path_status = lambda _: {"has_path": True, "ready": True}
    attached = []
    service._attach_native_bridge = attached.append
    service._native_bridge_attached = lambda session: session in attached
    service._native_host.stats = lambda _: json.dumps({"ok": True, "result": {"ice_connection_state": "connected", "data_channel_state": "open"}})
    service._native_startup_packets = SimpleNamespace(discard=lambda _: None)
    service.webrtc_detach_native = lambda _: None
    monkeypatch.setattr("mesh_chat.native_webrtc_service.connection_diagnostics.record", lambda *_: None)
    runtime = service._connection_runtime = native_runtime(service)
    try:
        deadline = monotonic() + 3
        while monotonic() < deadline:
            runtime.step()
            if runtime.snapshots().get("profile", {}).get("messaging_ready"):
                break
            Event().wait(0.005)
        assert runtime.snapshots()["profile"]["messaging_ready"]
        assert not service._carrier_recovery_pending
        assert runtime.owner.snapshots()[0].carrier.resource.resource_id == binding.resource
        assert len(attached) == 1 and not closed and not faults
        assert service.activated == [binding.resource]
    finally:
        runtime.stop()
        runtime.wait()
    assert closed == [binding.resource]
    assert not service._carrier_journal.bindings()


def test_authority_change_during_orphan_cleanup_preserves_an_unrelated_survivor(recovery):
    service, binding, inventory, closed, faults = recovery
    inventory["resources"].append({**inventory["resources"][0], "resource": "orphan"})
    def close(resource):
        closed.append(resource)
        service._carrier_journal.invalidate("unrelated-contact")
    service._native_host.close = close
    reconcile_carriers(service, lambda _: True)
    assert closed == ["orphan"] and not faults
    assert service._native_resources.resolve(binding.resource)


def test_revocation_during_orphan_cleanup_retires_the_previously_selected_survivor(recovery):
    service, binding, inventory, closed, faults = recovery
    inventory["resources"].append({**inventory["resources"][0], "resource": "orphan"})
    def close(resource):
        closed.append(resource)
        service._carrier_journal.invalidate("contact")
    service._native_host.close = close
    reconcile_carriers(service, lambda _: True)
    assert closed == ["orphan", binding.resource] and not faults
    assert not service._native_webrtc_live
