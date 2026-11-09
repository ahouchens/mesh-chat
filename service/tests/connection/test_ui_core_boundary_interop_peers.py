"""Bounded local control framing is distinct from product traffic evidence."""

from io import BytesIO
import json
import os
from pathlib import Path
import socket
import struct
import sys
import threading
import queue
from types import SimpleNamespace

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


def test_windows_peer_pipe_is_unique_and_accepted_by_the_actual_host_policy():
    from mesh_chat.core_api.pipe_policy import pipe_name
    first, second = peers.windows_pipe_name(), peers.windows_pipe_name()
    assert first != second
    assert pipe_name(first) == first and pipe_name(second) == second
    assert first.startswith(r"\\.\pipe\mesh-chat-native-qualification-")
    with pytest.raises(ValueError):
        pipe_name(r"\\.\pipe\mesh-native-qualification-" + "a" * 32)


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


def windows_fixture(monkeypatch):
    peer = object.__new__(peers.WindowsPeer)
    peer.clean_exits = peer.forced_exits = 0
    peer._sequence = 0
    peer._exchange_lock = threading.Lock()
    peer._pending_worker = None
    peer._poisoned = False
    peer._responses = queue.Queue()
    streams = [BytesIO() for _ in range(3)]
    state = {"exit": None, "kills": 0, "waits": 0, "client_closed": False}
    def kill(process):
        assert process is peer.process
        state.update(exit=-9, kills=state["kills"] + 1)
    def wait(timeout):
        state["waits"] += 1
        if state["exit"] is None:
            raise peers.subprocess.TimeoutExpired("owned-child", timeout)
        return state["exit"]
    peer.process = SimpleNamespace(stdin=streams[0], stdout=streams[1], stderr=streams[2],
                                   poll=lambda: state["exit"], wait=wait)
    peer.client = SimpleNamespace(close=lambda: state.update(client_closed=True))
    peer._reader = peer._stderr = SimpleNamespace(join=lambda timeout: None, is_alive=lambda: False)
    monkeypatch.setattr(peer, "_kill_tree", kill)
    return peer, streams, state


def test_windows_shutdown_failure_still_retires_owned_tree_and_every_stream(monkeypatch):
    peer, streams, state = windows_fixture(monkeypatch)
    def fail(*args): raise peers.PeerFailure("original_shutdown_error")
    monkeypatch.setattr(peer, "private", fail)
    with pytest.raises(peers.PeerFailure, match="original_shutdown_error"):
        peer.stop()
    assert state["kills"] == 1 and state["client_closed"]
    assert peer.process is peer.client is None
    assert all(stream.closed for stream in streams)
    assert peer.clean_exits == 0


def test_failed_kill_retains_exact_process_and_does_not_close_active_buffered_stream(monkeypatch):
    peer, streams, state = windows_fixture(monkeypatch)
    process = peer.process
    active = SimpleNamespace(join=lambda timeout: None, is_alive=lambda: True)
    peer._reader = active
    peer._poisoned = True
    def kill_failed(process): raise OSError("own process kill failed")
    monkeypatch.setattr(peer, "_kill_tree", kill_failed)
    with pytest.raises(peers.PeerFailure, match="peer_poisoned"):
        peer.stop()
    assert peer.process is process and peer._reader is active and peer._poisoned
    assert not any(stream.closed for stream in streams)
    assert not state["client_closed"] and peer.clean_exits == 0
    with pytest.raises(peers.PeerFailure, match="peer_already_started"):
        peer.start()
    # Exact retained ownership may retire later; cleanup then closes safely.
    state["exit"] = -9
    peer._reader = SimpleNamespace(join=lambda timeout: None, is_alive=lambda: False)
    with pytest.raises(peers.PeerFailure, match="peer_poisoned"):
        peer.stop()
    assert peer.process is None and all(stream.closed for stream in streams)


def test_overlapping_windows_exchange_is_rejected_before_another_host_write(monkeypatch):
    peer, _, _ = windows_fixture(monkeypatch)
    peer._exchange_lock.acquire()
    calls = []
    try:
        with pytest.raises(peers.PeerFailure, match="peer_exchange_in_progress"):
            peer._bounded(lambda: calls.append(True))
    finally:
        peer._exchange_lock.release()
    assert calls == []


def test_failed_kill_cleanup_returns_while_real_buffered_reader_remains_blocked(monkeypatch):
    peer, streams, state = windows_fixture(monkeypatch)
    process = peer.process
    read_fd, write_fd = os.pipe()
    reader_stream, writer_stream = os.fdopen(read_fd, "rb"), os.fdopen(write_fd, "wb", buffering=0)
    process.stdout = reader_stream
    entered = threading.Event()
    def read():
        entered.set()
        reader_stream.read(1)
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    assert entered.wait(1)
    join = reader.join
    monkeypatch.setattr(reader, "join", lambda timeout: join(min(timeout, 0.025)))
    peer._reader = reader
    peer._poisoned = True
    def denied(process): raise OSError("simulated own-child kill failure")
    monkeypatch.setattr(peer, "_kill_tree", denied)
    finished, errors = threading.Event(), []
    def cleanup():
        try: peer.stop()
        except peers.PeerFailure as error: errors.append(error.code)
        finally: finished.set()
    cleanup_worker = threading.Thread(target=cleanup, daemon=True)
    cleanup_worker.start()
    completed_without_unblocking_reader = finished.wait(1)
    try:
        assert completed_without_unblocking_reader
        assert peer.process is process and peer._poisoned
        assert not reader_stream.closed and reader.is_alive()
        assert errors == ["peer_poisoned"]
    finally:
        writer_stream.write(b"x")
        writer_stream.close()
        join(2)
        cleanup_worker.join(2)
        state["exit"] = -9
        try: peer.stop()
        except peers.PeerFailure: pass
        if not reader_stream.closed: reader_stream.close()


def test_windows_exit_timeout_kills_tree_and_never_counts_clean_exit(monkeypatch):
    peer, streams, state = windows_fixture(monkeypatch)
    monkeypatch.setattr(peer, "private", lambda *args: None)
    with pytest.raises(peers.PeerFailure, match="windows_shutdown_failed"):
        peer.stop()
    assert state["kills"] == 1 and state["waits"] == 2
    assert all(stream.closed for stream in streams) and peer.process is None
    assert peer.clean_exits == 0


@pytest.mark.parametrize("blocked", ["write", "core_read"])
def test_whole_windows_exchange_deadline_covers_blocked_write_or_core_read(monkeypatch, blocked):
    peer, _, state = windows_fixture(monkeypatch)
    peer.EXCHANGE_TIMEOUT = 0.025
    released = threading.Event()
    original_kill = peer._kill_tree
    def kill(process):
        original_kill(process)
        released.set()
    monkeypatch.setattr(peer, "_kill_tree", kill)
    def hang(*args, **kwargs):
        assert released.wait(2), "The bounded exchange must retire its exact host"
        raise OSError("raw private setup must never escape the timeout")
    if blocked == "write":
        peer.process.stdin = SimpleNamespace(write=hang)
        call = lambda: peer.private("qualification.inventory")
    else:
        peer.client.request = hang
        call = lambda: peer.core("application.snapshot")
    with pytest.raises(peers.PeerFailure, match="peer_deadline"):
        call()
    assert state["kills"] == 1 and not state["client_closed"]
    with pytest.raises(peers.PeerFailure, match="peer_poisoned"):
        peer._bounded(lambda: None)


def test_android_controller_is_explicitly_excluded_from_all_ordinary_required_suites():
    import android_qualification
    assert peers.AndroidPeer.TEST.rsplit(".", 1)[1] in android_qualification.CONTROLLER_ONLY_CLASSES
    for suite in ("webrtc", "signaling", "core_api", "core_consumer"):
        assert all(item["class"] != "PackagedNativeInteropBoundaryTest" for item in android_qualification.cases(suite))
    for name in ("test_android_webrtc.sh", "test_android_signaling.sh", "test_android_core_api.sh"):
        script = (peers.ROOT / "scripts" / name).read_text()
        assert "-e class" in script and "android_qualification.py list" in script


def test_packaged_drivers_do_not_construct_a_source_service_or_import_vault():
    source = Path(peers.__file__).read_text()
    assert "MeshChatService" not in source and "VaultStore" not in source
    assert '"--qualification-native-webrtc"' in source
    android = (peers.ROOT / "plugins/tauri-plugin-mesh-runtime/android/src/androidTest/java/com/meshchat/runtime/PackagedNativeInteropBoundaryTest.kt").read_text()
    assert 'qualification.callAttr("android_initialize"' in android
    assert "CoreApiBridge.typedCommand" in android
    assert "_start_network" not in android and 'store.put(' not in android
