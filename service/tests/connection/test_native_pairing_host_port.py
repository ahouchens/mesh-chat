"""Actual private pairing admission; injected native/mailbox, no platform proof."""
import base64
import inspect
import json
import os
from types import SimpleNamespace
from uuid import uuid4
import weakref

import pytest

from mesh_chat import __main__ as sidecar
from mesh_chat.call_manager import CallOutcomeRequiresResync
from mesh_chat.core_api import qualification_host as private
from mesh_chat.errors import ContactNotApproved, ValidationError
from test_pairing_runtime import native_pairing, run_until


@pytest.fixture
def pairing_port(native_pairing, tmp_path):
    create, documents = native_pairing
    directory = tmp_path / "mesh-qualification-native-pairing"
    key = os.urandom(32)
    initial = {"v": 1, "command": "initialize", "payload": {"profile_dir": str(directory),
        "vault_key": base64.b64encode(key).decode(), "display_name": "Mesh qualification", "parent_pid": os.getpid()}}
    private.reserve_fresh_profile(initial)
    service, host, created, closed, controls, _ = create(directory, key)
    private.mark_initialized_profile(initial)
    current, allowed = [service], [True]
    port = private.QualificationControl(lambda: current[0], authorize=lambda: allowed[0])
    return port, service, host, created, closed, documents, current, allowed


def test_private_host_begin_status_cancel_uses_production_owner_and_binds_controller_profile_key(pairing_port):
    port, service, _, created, closed, *_ = pairing_port
    operation = str(uuid4())
    first = port.dispatch("qualification.pairing_begin", {"operation_id": operation, "role": "offer"})
    assert set(first) == {"operation_id", "state", "expires_at", "pairing_code"}
    assert first["operation_id"] == operation and first["pairing_code"] is None
    run_until(service, lambda: bool(port.dispatch("qualification.pairing_status", {"operation_id": operation})["pairing_code"]))
    internal = next(iter(service._native_pairing_contexts))
    assert internal != operation and len(created) == 1
    assert port.dispatch("qualification.pairing_begin", {"operation_id": operation, "role": "offer"})["pairing_code"]
    assert len(created) == 1
    assert port.dispatch("qualification.pairing_cancel", {"operation_id": operation})["state"] == "retiring"
    run_until(service, lambda: created[0][0] in closed)


@pytest.mark.parametrize("change", ["caller", "service", "epoch", "marker", "authority"])
def test_host_binding_revocation_denies_old_status_and_late_native_result(pairing_port, change):
    port, service, host, created, closed, documents, current, allowed = pairing_port
    operation = str(uuid4())
    if change == "caller":
        port.dispatch("qualification.pairing_begin", {"operation_id": operation, "role": "offer"})
        other = private.QualificationControl(lambda: service, caller="another-trusted-controller")
        with pytest.raises(CallOutcomeRequiresResync):
            other.dispatch("qualification.pairing_status", {"operation_id": operation})
        return
    original = host.createOffer
    def changed(*args):
        result = original(*args)
        if change == "service": current[0] = None
        elif change == "epoch": service._runtime_incarnation = uuid4().hex
        elif change == "marker": (service.store.profile_dir / private.MARKER).unlink()
        else: allowed[0] = False
        return result
    host.createOffer = changed
    port.dispatch("qualification.pairing_begin", {"operation_id": operation, "role": "offer"})
    run_until(service, lambda: bool(created) and created[0][0] in closed)
    assert len(created) == 1 and not documents
    with pytest.raises((ContactNotApproved, ValidationError)):
        port.dispatch("qualification.pairing_status", {"operation_id": operation})


@pytest.mark.parametrize("payload", [
    {"role": "offer"}, {"operation_id": "not-a-uuid", "role": "offer"},
    {"role": "offer", "authorized": True}, {"role": "offer", "sdp": "renderer-selected"},
    {"role": "offer", "ice": {}}, {"role": "offer", "resource": "chosen"},
    {"role": "offer", "pairing_code": None}, {"role": "answer"},
    {"role": ["offer"]}, {"role": "answer", "pairing_code": "x" * 2049},
    {"role": "offer", "allow_direct_ip_disclosure": 1},
])
def test_pairing_host_exact_shape_rejects_factories_or_caller_asserted_authority(pairing_port, payload):
    port, _, _, created, *_ = pairing_port
    request = {"operation_id": str(uuid4()), **payload}
    if payload == {"role": "offer"}: request.pop("operation_id")
    with pytest.raises(ValidationError):
        port.dispatch("qualification.pairing_begin", request)
    assert not created


def test_pairing_requires_marked_synthetic_profile_even_with_trusted_host_object(native_pairing):
    create, _ = native_pairing
    service, _, created, *_ = create()
    port = private.QualificationControl(lambda: service)
    with pytest.raises(ContactNotApproved):
        port.dispatch("qualification.pairing_begin", {"operation_id": str(uuid4()), "role": "offer"})
    assert not created


def test_android_private_pairing_checks_own_uid_and_current_instance_for_each_effect(pairing_port, monkeypatch):
    from mesh_chat import mobile_bridge
    _, service, _, created, *_ = pairing_port
    monkeypatch.setattr(mobile_bridge, "_service", service)
    monkeypatch.setattr(private, "_android_service", weakref.ref(service))
    monkeypatch.setattr(private, "_android_own_uid", lambda: None)
    operation = str(uuid4())
    raw = json.dumps({"command": "qualification.pairing_begin", "payload": {"operation_id": operation, "role": "offer"}})
    assert json.loads(private.android_control(raw))["ok"]
    # A change after admission also revokes the captured worker capability.
    monkeypatch.setattr(mobile_bridge, "_service", None)
    service._connection_runtime.step()
    assert created == []
    assert not json.loads(private.android_control(json.dumps({"command": "qualification.pairing_status", "payload": {"operation_id": operation}})))["ok"]


def test_sidecar_drops_bootstrap_key_aliases_before_entering_request_loop(monkeypatch):
    initial = {"v": 1, "id": "bootstrap", "command": "initialize", "payload": {"vault_key": "must-not-retain"}}
    alias = initial["payload"]
    service = SimpleNamespace(snapshot=lambda: {}, _direct_native=None,
        dispatch=lambda _: ({"ok": True, "result": None}, True), close=lambda: None)
    writer = SimpleNamespace(write=lambda _: None)
    monkeypatch.setattr(sidecar, "sys", SimpleNamespace(argv=["mesh-chat"], stdin=SimpleNamespace(buffer=None), stdout=SimpleNamespace(buffer=None)))
    monkeypatch.setattr(sidecar, "interruptible_input", lambda _: None)
    monkeypatch.setattr(sidecar, "FrameWriter", lambda _: writer)
    monkeypatch.setattr(sidecar, "read_frame", lambda _: initial)
    monkeypatch.setattr(sidecar, "_initialize", lambda *_: service)
    monkeypatch.setattr(sidecar, "_start_core_api_endpoint", lambda *_: None)
    class Reader:
        def __init__(self, *_args, **_kwargs):
            assert inspect.currentframe().f_back.f_locals["initial"] is None
            assert initial == {} and "vault_key" not in alias
        def read(self): return {"id": "stop", "command": "shutdown", "payload": {}}
        def close(self): pass
    monkeypatch.setattr(sidecar, "NativeFrameReader", Reader)
    assert sidecar.main() == 0


def test_sidecar_private_dispatch_uses_qualification_port_command_inventory():
    assert "qualification.pairing_begin" in private.QualificationControl.commands
    assert "command in qualification_control.commands" in inspect.getsource(sidecar.main)
