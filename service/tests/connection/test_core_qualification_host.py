"""Private launch admission and actual inspector boundary, never public Core."""
import base64
import json
import os
from pathlib import Path
import threading
import weakref
from types import SimpleNamespace

import pytest

from mesh_chat.core_api.qualification_host import QualificationControl, reserve_fresh_profile, mark_initialized_profile
from mesh_chat.errors import ValidationError
from test_core_messages import host, client, request


def initial(path):
    return {"v": 1, "command": "initialize", "payload": {"profile_dir": str(path),
        "vault_key": base64.b64encode(os.urandom(32)).decode(),
        "display_name": "Mesh qualification", "parent_pid": os.getpid()}}


def test_qualification_requires_new_synthetic_profile(tmp_path):
    target = tmp_path / "mesh-qualification-controller"
    assert reserve_fresh_profile(initial(target)) == target
    assert target.is_dir()
    with pytest.raises(ValidationError):
        reserve_fresh_profile(initial(target))
    with pytest.raises(ValidationError):
        reserve_fresh_profile(initial(tmp_path / "existing-user-profile"))
    assert not (tmp_path / "existing-user-profile").exists()


def test_same_qualification_path_and_key_reopen_but_other_key_or_copied_marker_refused(tmp_path):
    target = tmp_path / "mesh-qualification-reopen"
    value = initial(target)
    reserve_fresh_profile(value)
    mark_initialized_profile(value)
    assert reserve_fresh_profile(value) == target
    with pytest.raises(ValidationError):
        reserve_fresh_profile(initial(target))
    other = tmp_path / "mesh-qualification-other"
    other.mkdir()
    (other / ".mesh-qualification-v1").write_bytes((target / ".mesh-qualification-v1").read_bytes())
    changed = {**value, "payload": {**value["payload"], "profile_dir": str(other)}}
    with pytest.raises(ValidationError):
        reserve_fresh_profile(changed)


@pytest.mark.parametrize("change", [{"display_name": "Personal"}, {"vault_key": "bad"},
    {"parent_pid": True}, {"private_native": True}, {"profile_dir": "mesh-qualification-relative"}])
def test_qualification_refuses_invalid_bootstrap_before_directory_creation(tmp_path, change):
    target = tmp_path / "mesh-qualification-invalid"
    value = initial(target)
    value["payload"].update(change)
    with pytest.raises(ValidationError):
        reserve_fresh_profile(value)
    assert not target.exists()


def test_inspector_resolves_current_service_each_call_and_forwards_exact_resource():
    calls = []
    first = SimpleNamespace(_shutdown=threading.Event(),
        native_webrtc_inspection_resources=lambda: {"resources": []},
        native_webrtc_path_evidence=lambda *args: calls.append(args) or {"status": "unavailable"})
    current = [first]
    port = QualificationControl(lambda: current[0])
    assert port.dispatch("qualification.inventory", {}) == {"resources": []}
    assert port.dispatch("qualification.path_evidence", {"logical_session": "logical", "expected_physical": "physical"}) == {"status": "unavailable"}
    assert calls == [("logical", "physical")]
    first._shutdown.set()
    with pytest.raises(ValidationError):
        port.dispatch("qualification.inventory", {})
    current[0] = None
    with pytest.raises(ValidationError):
        port.dispatch("qualification.inventory", {})


@pytest.mark.parametrize("command,payload", [("native.command", {}), ("qualification.inventory", {"caller": "owner"}),
    ("qualification.path_evidence", {"logical_session": "logical"}),
    ("qualification.path_evidence", {"logical_session": "x" * 129, "expected_physical": "physical"})])
def test_inspector_refuses_unknown_or_unbounded_input_before_native_call(command, payload):
    service = SimpleNamespace(_shutdown=threading.Event())
    with pytest.raises(ValidationError):
        QualificationControl(lambda: service).dispatch(command, payload)


def test_public_owner_cannot_discover_or_invoke_private_qualification(host):
    from mesh_chat.core_api.native_commands import NATIVE_COMMANDS
    service = host()
    session, _, profile, _ = client(service, permissions=frozenset({"observe", "read", "send", "approve"}))
    capabilities = session.request(request("runtime.capabilities"))["result"]
    assert not any(name.startswith("qualification.") for name in capabilities["operations"])
    assert not any(name.startswith("qualification.") for name in NATIVE_COMMANDS)
    result = session.request(request("qualification.inventory"))
    assert result["ok"] is False
    assert not service._store_closed


def test_android_private_control_requires_own_uid_and_exact_current_instance(host, monkeypatch):
    from mesh_chat import mobile_bridge
    from mesh_chat.core_api import qualification_host as private
    service = host()
    monkeypatch.setattr(mobile_bridge, "_service", service)
    monkeypatch.setattr(private, "_android_service", weakref.ref(service))
    def denied():
        raise ValidationError("Host UID is required")
    monkeypatch.setattr(private, "_android_own_uid", denied)
    raw = json.dumps({"command": "qualification.inventory", "payload": {}})
    assert json.loads(private.android_control(raw))["ok"] is False
    monkeypatch.setattr(private, "_android_own_uid", lambda: None)
    # An exact current service is required even for an empty inventory. This
    # fixture has no native runtime; don't report selected path/platform proof.
    monkeypatch.setattr(service, "native_webrtc_inspection_resources", lambda: {"resources": []})
    assert json.loads(private.android_control(raw))["result"] == {"resources": []}
    monkeypatch.setattr(mobile_bridge, "_service", None)
    assert json.loads(private.android_control(raw))["ok"] is False


def test_android_initialization_cannot_replace_an_existing_ordinary_host(host, monkeypatch, tmp_path):
    from mesh_chat import mobile_bridge
    from mesh_chat.core_api import qualification_host as private
    service = host()
    monkeypatch.setattr(mobile_bridge, "_service", service)
    monkeypatch.setattr(private, "_android_own_uid", lambda: None)
    target = tmp_path / "mesh-qualification-android"
    payload = initial(target)["payload"]
    payload.pop("parent_pid")
    payload["platform"] = "android"
    assert json.loads(private.android_initialize(json.dumps(payload)))["ok"] is False
    assert not target.exists()
    assert mobile_bridge._service is service
