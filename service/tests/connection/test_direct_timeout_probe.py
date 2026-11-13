"""Test-only attribution for a Direct worker that misses its existing reply bound."""
import json
from queue import Empty, Queue
from threading import Event, Lock, Thread
from types import SimpleNamespace

import pytest

import direct_timeout_probe as probe
from test_direct_recovery_pipeline import Peers


def _peers(shared, *, alive=True):
    peers = Peers.__new__(Peers)
    peers.commands = [Queue(), Queue()]
    peers.replies = [Queue(), Queue()]
    peers.processes = [SimpleNamespace(is_alive=lambda: alive), None]
    peers._timeout_probes = [shared, None]
    peers._command_sequences = [0, 0]
    return peers


def _note(error):
    notes = getattr(error, "__notes__", ())
    assert len(notes) == 1
    assert notes[0].startswith("direct_command_timeout:")
    return json.loads(notes[0].split(":", 1)[1])


@pytest.mark.parametrize("blocked_phase", ["waiting_dispatch", "executing"])
def test_real_call_and_worker_probe_distinguish_lock_wait_from_execution(blocked_phase):
    shared = probe.new_probe()
    peers = _peers(shared)
    lock, release, entered = Lock(), Event(), Event()
    if blocked_phase == "waiting_dispatch":
        lock.acquire()

    def worker():
        operation, payload = peers.commands[0].get(timeout=1)
        observer = probe.WorkerProbe(shared)
        try:
            observer.begin(probe.command_label(operation, payload))
            observer.waiting_dispatch()
            entered.set()
            with lock:
                observer.executing()
                if blocked_phase == "executing":
                    assert release.wait(1)
            peers.replies[0].put({"ok": True, "result": "ok"})
            observer.reply_queued()
        finally:
            observer.close()

    thread = Thread(target=worker)
    thread.start()
    try:
        with pytest.raises(Empty) as caught:
            peers.call(0, "command", _diagnostic_timeout=.15,
                       command="workspace_snapshot", payload={})
        assert entered.is_set()
        note = _note(caught.value)
        assert note["phase"] == blocked_phase
        assert note["command"] == "workspace_snapshot"
        assert note["liveness"] == "alive"
        assert note["site"]["file"] == "test_direct_timeout_probe"
        assert type(note["site"]["line"]) is int
        assert "payload" not in str(note)
    finally:
        release.set()
        if blocked_phase == "waiting_dispatch":
            lock.release()
        thread.join(2)
    assert not thread.is_alive()


def test_exited_worker_and_stale_command_never_claim_old_site():
    shared = probe.new_probe()
    observer = probe.WorkerProbe(shared)
    observer.begin("answer")
    observer.waiting_dispatch()
    observer.close()
    peers = _peers(shared, alive=False)
    with pytest.raises(Empty) as caught:
        peers.call(0, "command", _diagnostic_timeout=.01,
                   command="workspace_snapshot", payload={})
    note = _note(caught.value)
    assert note["liveness"] == "exited"
    assert note["phase"] == "unknown" and note["site"] == "unknown"


def test_cross_phase_site_is_rejected_even_for_matching_command():
    shared = probe.new_probe()
    observer = probe.WorkerProbe(shared, start_sampler=False)
    observer.begin("workspace_snapshot")
    observer.waiting_dispatch()
    observer.sample_once()
    observer.executing()
    note = probe.timeout_note(shared, 1, "workspace_snapshot", "alive")
    assert note["phase"] == "executing"
    assert note["site"] == "unknown"
    observer.close()


def test_live_stale_command_record_is_not_reused():
    shared = probe.new_probe()
    observer = probe.WorkerProbe(shared, start_sampler=False)
    observer.begin("workspace_snapshot")
    observer.waiting_dispatch()
    observer.sample_once()
    note = probe.timeout_note(shared, 2, "workspace_snapshot", "alive")
    assert note["phase"] == "unknown" and note["site"] == "unknown"
    observer.close()


def test_command_phase_change_during_site_read_cannot_publish_old_site(monkeypatch):
    rows = iter(((1, probe._COMMAND["workspace_snapshot"],
                  probe._PHASE["waiting_dispatch"], 2),
                 (1, 2, 3, 42, 0, 0, 0),
                 (1, probe._COMMAND["workspace_snapshot"],
                  probe._PHASE["executing"], 3)))
    monkeypatch.setattr(probe, "_read_row", lambda *_: next(rows))
    note = probe.timeout_note(object(), 1, "workspace_snapshot", "alive")
    assert note["phase"] == "unknown" and note["site"] == "unknown"


def test_throwing_timeout_observer_preserves_original_empty(monkeypatch):
    shared = probe.new_probe()
    peers = _peers(shared)
    original = Empty()
    peers.replies[0] = SimpleNamespace(get=lambda **_: (_ for _ in ()).throw(original))
    monkeypatch.setattr(probe, "timeout_note", lambda *args: (_ for _ in ()).throw(RuntimeError("PRIVATE")))
    with pytest.raises(Empty) as caught:
        peers.call(0, "command", _diagnostic_timeout=.01,
                   command="workspace_snapshot", payload={})
    assert caught.value is original
    assert not getattr(caught.value, "__notes__", None)


def _spawn_observed_worker(commands, replies, shared, ready, entered, release):
    ready.set()
    operation, payload = commands.get(timeout=3)
    observer = probe.WorkerProbe(shared)
    try:
        observer.begin(probe.command_label(operation, payload))
        observer.waiting_dispatch()
        observer.executing()
        entered.set()
        assert release.wait(3)
        replies.put({"ok": True, "result": "done"})
        observer.reply_queued()
    finally:
        observer.close()


def test_spawned_worker_publication_reaches_real_parent_timeout():
    from multiprocessing import get_context

    context = get_context("spawn")
    shared = probe.new_probe()
    commands, replies = context.Queue(), context.Queue()
    ready, entered, release = context.Event(), context.Event(), context.Event()
    process = context.Process(target=_spawn_observed_worker,
                              args=(commands, replies, shared, ready, entered, release))
    peers = _peers(shared)
    peers.commands[0], peers.replies[0], peers.processes[0] = commands, replies, process
    process.start()
    try:
        assert ready.wait(5)
        with pytest.raises(Empty) as caught:
            peers.call(0, "command", _diagnostic_timeout=.5,
                       command="workspace_snapshot", payload={})
        assert entered.is_set()
        note = _note(caught.value)
        assert note["phase"] == "executing" and note["liveness"] == "alive"
        assert note["site"]["file"] == "test_direct_timeout_probe"
    finally:
        release.set()
        process.join(5)
        if process.is_alive():
            process.terminate()
            process.join(2)
        commands.close()
        replies.close()
    assert process.exitcode == 0


def test_normal_reply_and_legacy_worker_shape_are_unchanged():
    import inspect
    from test_direct_setup_pipeline import _service_worker

    assert inspect.signature(_service_worker).parameters["timeout_probe"].default is None
    shared = probe.new_probe()
    peers = _peers(shared)
    sent = []

    def worker():
        operation, payload = peers.commands[0].get(timeout=1)
        sent.append((operation, payload))
        observer = probe.WorkerProbe(shared)
        try:
            observer.begin(probe.command_label(operation, payload))
            observer.waiting_dispatch()
            observer.executing()
            peers.replies[0].put({"ok": True, "result": {"value": 1}})
            observer.reply_queued()
        finally:
            observer.close()

    thread = Thread(target=worker)
    thread.start()
    assert peers.call(0, "command", command="workspace_snapshot", payload={}) == {"value": 1}
    thread.join(2)
    assert sent == [("command", {"command": "workspace_snapshot", "payload": {}})]


def test_actual_optional_service_worker_keeps_normal_reply(tmp_path):
    peers = Peers(tmp_path, None)
    try:
        peers.start(0)
        assert peers.call(0, "diagnostic") == {"native_count": 0, "interfaces": 0}
    finally:
        peers.close()
