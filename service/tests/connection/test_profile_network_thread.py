"""Actual framed fresh-profile/RNS startup, without external interfaces."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("worker", [False, True], ids=["main-thread", "ipc-worker"])
def test_public_profile_create_starts_real_network_on_host_thread(tmp_path, worker):
    # RNS owns process-global state. Each case gets its own actual interpreter,
    # just as an app-owned runtime does. The vault explicitly uses test storage.
    source = Path(__file__).resolve().parents[2] / "src"
    code = r'''
import os, signal, sys, threading
from pathlib import Path
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore
from mesh_chat.reticulum_config import NetworkSettings
from mesh_chat.core_api.host import bind_host_stream, OWNER_PERMISSIONS
from mesh_chat.core_api.wire_codec import encode_frame, decode_frame

worker = sys.argv[2] == "worker"
directory = Path(sys.argv[1])
store = VaultStore(directory, os.urandom(32), allow_unprotected_for_tests=True)
store.put("settings", "network", NetworkSettings(nearby_discovery=False, lan_fallback=False).to_dict())
service = MeshChatService(store, directory, lambda _: None)
stream = bind_host_stream(service, caller="profile-thread-test", scope="owner",
    permissions=OWNER_PERMISSIONS | {"profile_owner"}, private_profile_bootstrap=True)
original_signal = signal.signal
original_handlers = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
results, failures = [], []
def request(operation, params, key=None):
    value = {"api_version": 1, "request_id": "thread:1", "operation": operation, "params": params}
    if key is not None: value["idempotency_key"] = key
    return decode_frame(stream.exchange(encode_frame(value)))
def create():
    try:
        assert request("runtime.capabilities", {})["ok"]
        results.append(request("profile.create", {"display_name": "Thread test"}, "thread-create-original-001"))
    except BaseException as error: failures.append(type(error).__name__)
try:
    if worker:
        thread = threading.Thread(target=create, name="mesh-core-api-pipe-test")
        thread.start(); thread.join(10)
        assert not thread.is_alive()
    else: create()
    assert not failures and len(results) == 1 and results[0]["ok"], results
    # Before the repair, the IPC worker reports successful profile creation
    # while _start_network swallows the actual RNS signal-registration failure.
    assert service.network is not None, service._network_error
    assert service.network.router is not None
    assert service.network.delivery_destination is not None
    assert service._network_error is None
    assert signal.signal is original_signal
    if worker:
        assert all(signal.getsignal(number) is handler for number, handler in original_handlers.items())
    else:
        # Existing standalone/main-thread behavior still delegates registration.
        assert signal.getsignal(signal.SIGTERM).__self__ is service.network.router
    # The ordinary process signal API still rejects worker-thread registration.
    rejected = []
    def standard_registration():
        try: signal.signal(signal.SIGTERM, lambda *_: None)
        except ValueError: rejected.append(True)
    thread = threading.Thread(target=standard_registration)
    thread.start(); thread.join(5)
    assert rejected == [True]
    print("actual profile and network startup passed")
finally:
    stream.close(); service.close()
assert service._store_closed
'''
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path), "worker" if worker else "main"],
        env={**os.environ, "PYTHONPATH": str(source), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "actual profile and network startup passed"
