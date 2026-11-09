"""Actual Windows DPAPI and image-authenticated pipe component checks.

The Vault storage bypass in the composition test is explicit. This is not EFS,
packaged application, public installed SDK, or transport qualification.
"""
import json
import os
import uuid

import pytest

if os.name != "nt":
    pytest.skip("Windows DPAPI and named pipes are required", allow_module_level=True)

from mesh_chat.app_owned_host import AppOwnedConfig, AppOwnedRuntime
from mesh_chat.core_api.pipe_client import connect
from mesh_chat.errors import NativeUnavailable
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore
from mesh_chat.windows_app_key import KEY_FILE, load_key
from test_core_pipe_windows import current_image


def test_actual_dpapi_key_reopens_and_is_bound_to_its_own_app_directory(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    key = load_key(first)
    packed = (first / KEY_FILE).read_bytes()
    assert len(key) == 32 and key not in packed
    assert load_key(first) == key
    (second / KEY_FILE).write_bytes(packed)
    with pytest.raises(NativeUnavailable): load_key(second)
    assert (first / KEY_FILE).read_bytes() == packed


@pytest.mark.parametrize("packed", [b"", b"unknown-key-format", b"mesh-core-app-key-v1\0broken"])
def test_corrupted_key_is_never_silently_replaced(tmp_path, packed):
    (tmp_path / KEY_FILE).write_bytes(packed)
    with pytest.raises(NativeUnavailable): load_key(tmp_path)
    assert (tmp_path / KEY_FILE).read_bytes() == packed


def test_missing_original_app_key_does_not_generate_a_replacement_for_an_existing_vault(tmp_path):
    directory = tmp_path / "profile-v1"
    directory.mkdir()
    (directory / "mesh-chat.vault").write_bytes(b"existing encrypted vault")
    with pytest.raises(NativeUnavailable): load_key(tmp_path)
    assert not (tmp_path / KEY_FILE).exists()


def test_ordinary_host_uses_real_dpapi_and_pipe_without_private_core_commands(tmp_path, monkeypatch):
    monkeypatch.setattr(MeshChatService, "_start_network", lambda *_: None)
    monkeypatch.setattr(MeshChatService, "_prepare_lan_fallback", lambda *_: None)
    config = AppOwnedConfig(tmp_path, rf"\\.\pipe\mesh-chat-independent-{uuid.uuid4().hex[:16]}",
        current_image(), os.getpid())
    runtime = AppOwnedRuntime(config,
        store_factory=lambda *args: VaultStore(*args, allow_unprotected_for_tests=True))
    client = None
    try:
        assert runtime.service._identity is None
        client = connect(config.pipe)
        def request(operation, params=None, key=None):
            value = {"api_version": 1, "request_id": "ordinary:windows", "operation": operation,
                "params": params or {}}
            if key is not None: value["idempotency_key"] = key
            client.write(json.dumps(value).encode() + b"\n")
            return json.loads(client.readline())
        capabilities = request("runtime.capabilities")
        assert capabilities["ok"] and "profile.create" in capabilities["result"]["operations"]
        assert "native.command" not in capabilities["result"]["operations"]
        assert request("profile.create", {"display_name": "Independent"}, "original-profile-key")["ok"]
        identity = runtime.store.get("identity", "local")
        assert runtime.endpoint.accepted == 1 and runtime.store.list("contact") == []
    finally:
        if client is not None: client.close()
        assert runtime.close()
    assert runtime.store._key is None
    reopened = AppOwnedRuntime(config,
        store_factory=lambda *args: VaultStore(*args, allow_unprotected_for_tests=True))
    try:
        assert reopened.store.get("identity", "local") == identity
    finally:
        assert reopened.close()
