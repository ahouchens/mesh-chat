"""Checkpoint integration with protected storage and controlled native observations."""
from copy import deepcopy
import os
from threading import Event, RLock, Thread
from types import SimpleNamespace

import pytest

from mesh_chat.carrier_journal import CarrierJournal
from mesh_chat.errors import ContactNotApproved, NativeUnavailable
from mesh_chat.native_carrier_evidence import description_hash
from mesh_chat.native_resource_registry import NativeResourceRegistry
from mesh_chat.native_webrtc_service import NativeWebRTCServiceMixin
from mesh_chat.reconnect_service import ReconnectServiceMixin
from mesh_chat.vault import VaultStore


@pytest.fixture
def carrier(tmp_path):
    with VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True) as store:
        service = NativeWebRTCServiceMixin()
        service._connection_policy = "shared-native"
        service._dispatch_lock = RLock()
        service._native_webrtc_lock = RLock()
        service._native_resources = NativeResourceRegistry()
        physical = service._native_resources.reserve("logical")
        service._native_webrtc_live = {"logical"}
        service._native_webrtc_creating = set()
        service._native_webrtc_profile_sessions = {"profile": "logical"}
        service._native_webrtc_descriptions = {"logical": {"local": "local-sdp", "remote_answer": "remote-sdp", "ice_policy": "relay"}}
        service._native_carrier_authorized = lambda _: True
        service.profile = {"id": "profile", "contact_id": "contact", "local_device_id": "local", "remote_device_id": "remote"}
        service._reconnect_profile = lambda _: service.profile
        service._reconnect_contact = lambda _: {"destination_hash": "b" * 32}
        service._carrier_journal = CarrierJournal(store)
        service.store = store
        attached = []
        service._attach_native_bridge = lambda session: attached.append(session)
        inventory = {"v": 1, "adapter_epoch": "a" * 32, "resources": [{
            "resource": physical, "ice_policy": "relay", "pending": False,
            "ice_connection_state": "connected", "signaling_state": "stable", "data_channel_state": "open",
            "channels": [{"label": "mesh-reticulum", "state": "open"}],
            "local_type": "offer", "remote_type": "answer", "local_sdp_sha256": description_hash("local-sdp"),
            "remote_sdp_sha256": description_hash("remote-sdp"),
        }]}
        service._native_host = SimpleNamespace(inventory=lambda: deepcopy(inventory))
        yield service, inventory, attached


def test_bridge_attach_checkpoints_the_current_lease_first(carrier):
    service, inventory, attached = carrier
    service.webrtc_attach_native("logical")
    binding, = service._carrier_journal.bindings()
    assert binding.resource == inventory["resources"][0]["resource"]
    assert binding.peer_destination == "b" * 32
    assert attached == ["logical"]


@pytest.mark.parametrize("fault", ["hash", "policy", "pending", "missing", "device", "authority", "aba", "storage", "host"])
def test_changed_observations_or_authority_cannot_checkpoint_or_attach(carrier, fault, monkeypatch):
    service, inventory, attached = carrier
    def changed():
        if fault == "hash": inventory["resources"][0]["remote_sdp_sha256"] = "e" * 64
        elif fault == "policy": inventory["resources"][0]["ice_policy"] = "all"
        elif fault == "pending": inventory["resources"][0]["pending"] = True
        elif fault == "missing": inventory["resources"] = []
        elif fault == "device": service.profile["remote_device_id"] = "other"
        elif fault == "authority": service._native_carrier_authorized = lambda _: False
        elif fault == "aba": service._carrier_journal.invalidate("contact")
        elif fault == "host": service._native_host = SimpleNamespace(inventory=lambda: deepcopy(inventory))
        elif fault == "storage":
            def fail(*_): raise OSError("vault write failed")
            monkeypatch.setattr(service.store, "_seal", fail)
        return deepcopy(inventory)
    service._native_host.inventory = changed
    with pytest.raises((ContactNotApproved, NativeUnavailable, OSError)):
        service.webrtc_attach_native("logical")
    assert not service._carrier_journal.bindings()
    assert not attached


def test_native_inventory_wait_does_not_block_authority_fencing(carrier):
    service, inventory, attached = carrier
    entered, resume = Event(), Event()
    failures = []
    def blocked():
        entered.set()
        assert resume.wait(3)
        return deepcopy(inventory)
    service._native_host.inventory = blocked
    def attach():
        try: service.webrtc_attach_native("logical")
        except Exception as error: failures.append(error)
    worker = Thread(target=attach)
    worker.start()
    try:
        assert entered.wait(3)
        assert service._dispatch_lock.acquire(timeout=0.5)
        try:
            service._native_carrier_authorized = lambda _: False
            service._carrier_journal.invalidate("contact")
        finally: service._dispatch_lock.release()
    finally:
        resume.set()
        worker.join(3)
    assert not worker.is_alive()
    assert len(failures) == 1 and isinstance(failures[0], ContactNotApproved)
    assert not attached


def test_stale_physical_attachment_cannot_touch_replacement(carrier):
    service, _, attached = carrier
    with pytest.raises(NativeUnavailable):
        service.webrtc_attach_native("logical", expected_physical="retired-resource")
    assert not attached and not service._carrier_journal.bindings()


def test_answering_role_checkpoints_its_exact_remote_offer(carrier):
    service, inventory, attached = carrier
    description = service._native_webrtc_descriptions["logical"]
    description["remote_offer"] = description.pop("remote_answer")
    inventory["resources"][0].update(local_type="answer", remote_type="offer")
    service.webrtc_attach_native("logical")
    assert service._carrier_journal.bindings()[0].local_type == "answer"
    assert attached == ["logical"]


def test_failed_retirement_bookkeeping_still_closes_the_exact_native_resource(carrier, monkeypatch):
    service, inventory, _ = carrier
    physical = inventory["resources"][0]["resource"]
    closed, detached = [], []
    service._native_host.close = closed.append
    service._native_startup_packets = SimpleNamespace(discard=lambda _: None)
    service._release_native_session = lambda _: None
    service.webrtc_detach_native = detached.append
    monkeypatch.setattr("mesh_chat.native_webrtc_service.connection_diagnostics.record", lambda *_: None)
    def fail(*_): raise OSError("retirement write failed")
    monkeypatch.setattr(service._carrier_journal, "retire", fail)
    with pytest.raises(OSError): service.native_webrtc_close("logical")
    assert closed == [physical] and detached == ["logical"]
    assert not service._native_webrtc_live


def test_native_closed_callback_removes_its_checkpoint_and_exact_reservation(carrier, monkeypatch):
    service, inventory, _ = carrier
    service.webrtc_attach_native("logical")
    physical = inventory["resources"][0]["resource"]
    service._native_startup_packets = SimpleNamespace(discard=lambda _: None)
    service._native_webrtc_peers = {}
    service._native_webrtc_controls = {}
    detached = []
    service.webrtc_detach_native = detached.append
    service.emit = lambda _: None
    monkeypatch.setattr("mesh_chat.native_webrtc_service.connection_diagnostics.record", lambda *_: None)
    service._handle_native_webrtc_event("closed", physical)
    assert not service._carrier_journal.bindings()
    assert not service._native_webrtc_live
    assert service._native_resources.resolve(physical) is None
    assert detached == ["logical"]


@pytest.mark.parametrize("failed_write", [False, True])
def test_stop_invalidates_recovery_before_reporting_durable_intent(carrier, monkeypatch, failed_write):
    service, _, _ = carrier
    service.webrtc_attach_native("logical")
    fenced = []
    service._connection_runtime = SimpleNamespace(fence=fenced.append)
    service._reconnect_profiles_raw = lambda: [dict(service.profile)]
    service.retire_unmanaged_native_connections = lambda _: None
    service._changed = lambda: None
    service.reconnect_status = lambda: {}
    original_put = service.store.put
    def write(kind, identity, value):
        assert not service._carrier_journal.bindings()
        if failed_write: raise OSError("intent write failed")
        original_put(kind, identity, value)
    monkeypatch.setattr(service.store, "put", write)
    if failed_write:
        with pytest.raises(OSError): ReconnectServiceMixin.reconnect_stop(service, "contact")
        assert service.store.get("reconnect_profile", "profile") is None
    else:
        ReconnectServiceMixin.reconnect_stop(service, "contact")
        assert service.store.get("reconnect_profile", "profile")["state"] == "stopped"
    assert fenced == ["contact"]
    assert not CarrierJournal(service.store).bindings()


def test_failed_authority_write_keeps_durable_invalidation_and_memory_fence(carrier):
    service, _, _ = carrier
    service.webrtc_attach_native("logical")
    calls = []
    service._connection_runtime = SimpleNamespace(
        begin_authority_change=lambda identity: calls.append(("fence", identity)),
        commit_authority_change=lambda *args: calls.append(("commit", args)))
    with pytest.raises(OSError):
        with ReconnectServiceMixin._connection_authority_update(service, "contact"):
            assert not service._carrier_journal.bindings()
            raise OSError("authority write failed")
    assert calls == [("fence", "contact")]
    assert not CarrierJournal(service.store).bindings()


def test_failed_invalidation_prevents_the_authority_write_and_keeps_memory_fence(carrier, monkeypatch):
    service, _, _ = carrier
    calls = []
    service._connection_runtime = SimpleNamespace(
        begin_authority_change=lambda identity: calls.append(("fence", identity)),
        commit_authority_change=lambda *args: calls.append(("commit", args)))
    def fail(*_): raise OSError("invalidation failed")
    monkeypatch.setattr(service._carrier_journal, "invalidate", fail)
    with pytest.raises(OSError):
        with ReconnectServiceMixin._connection_authority_update(service, "contact"):
            pytest.fail("Authority mutation cannot begin after failed invalidation")
    assert calls == [("fence", "contact")]
