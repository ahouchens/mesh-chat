"""Bounded local control framing is distinct from product traffic evidence."""

from io import BytesIO
import json
from pathlib import Path
import socket
import struct
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_peers as peers


def test_real_socket_control_roundtrip_preserves_core_payload_and_correlation():
    controller, host = socket.socketpair()
    controller.settimeout(2)
    host.settimeout(2)
    peer = peers.AndroidPeer(b"k" * 32)
    peer.socket = controller
    requests = []
    def serve():
        request = peers.receive(host.recv)
        requests.append(request)
        host.sendall(peers.encode({"id": request["id"], "ok": True, "result": {"accepted": True}}))
    worker = threading.Thread(target=serve)
    worker.start()
    try:
        params = {"profile": "a" * 40, "recipient": "b" * 40, "kind": "text", "text": "controller fixture"}
        assert peer.core("message.enqueue", params, "caller-chosen-key-0001") == {"accepted": True}
        worker.join(2)
        assert not worker.is_alive()
        assert requests[0]["action"] == "core"
        assert requests[0]["payload"] == {"operation": "message.enqueue", "params": params, "idempotency_key": "caller-chosen-key-0001"}
    finally:
        controller.close()
        host.close()


def test_partial_stream_reads_do_not_change_framed_setup():
    frame = peers.encode({"id": "qualification:1", "ok": True, "result": {"public": True}})
    stream = BytesIO(frame)
    assert peers.receive(lambda count: stream.read(min(count, 1)))["result"] == {"public": True}


@pytest.mark.parametrize("frame", [b"", b"\x00", struct.pack(">I", 1) + b"x",
    struct.pack(">I", peers.MAX_FRAME + 1), struct.pack(">I", 2) + b"[1",
    struct.pack(">I", 2) + b"[]", struct.pack(">I", 2) + b"\xff\xff"])
def test_malformed_or_unbounded_local_frames_fail_without_raw_diagnostics(frame):
    with pytest.raises(peers.PeerFailure) as failure:
        peers.receive(BytesIO(frame).read)
    assert str(failure.value) in {"peer_closed", "peer_frame_budget", "invalid_peer_frame"}


@pytest.mark.parametrize("value", [None, [], {"id": "other", "ok": True}, {"id": "expected", "ok": 1},
    {"id": "expected", "ok": False, "error": {"code": "raw signed SDP secret"}}])
def test_response_identity_and_typed_errors_never_expose_raw_setup(value):
    with pytest.raises(peers.PeerFailure) as failure:
        peers.checked_reply(value, "expected")
    assert "secret" not in str(failure.value)


def test_product_process_never_inherits_artifact_or_repository_bearers():
    assert peers.child_environment({"GITHUB_TOKEN": "secret", "ACTIONS_RUNTIME_TOKEN": "secret",
        "INPUT_ROLE": "windows", "PATH": "public", "SYSTEMROOT": "C:/Windows"}) == {"PATH": "public", "SYSTEMROOT": "C:/Windows"}


@pytest.mark.parametrize("leaf", ["../existing", "absolute/path", "a" * 31, "g" * 32])
def test_android_controller_cannot_choose_arbitrary_existing_profile_paths(leaf):
    with pytest.raises(peers.PeerFailure, match="invalid_profile_leaf"):
        peers.AndroidPeer(b"k" * 32, directory_id=leaf)


def test_windows_crash_targets_the_exact_launched_pyinstaller_tree(monkeypatch):
    calls = []
    monkeypatch.setattr(peers.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    peers.WindowsPeer._kill_tree(type("OwnProcess", (), {"pid": 1234})())
    assert calls[0][0][0] == ["taskkill.exe", "/PID", "1234", "/T", "/F"]
    assert calls[0][1]["check"] and calls[0][1]["timeout"] == 15


def test_packaged_drivers_do_not_construct_a_source_service_or_import_vault():
    source = Path(peers.__file__).read_text()
    assert "MeshChatService" not in source and "VaultStore" not in source
    assert '"--qualification-native-webrtc"' in source
    android = (peers.ROOT / "plugins/tauri-plugin-mesh-runtime/android/src/androidTest/java/com/meshchat/runtime/PackagedNativeInteropBoundaryTest.kt").read_text()
    assert 'qualification.callAttr("android_initialize"' in android
    assert "CoreApiBridge.typedCommand" in android
    assert "_start_network" not in android and 'store.put(' not in android
