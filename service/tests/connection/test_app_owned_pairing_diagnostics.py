"""Private EOF-only pairing observation on the normal app-owned status pipe."""

import io
from threading import Event, RLock, Thread
from types import SimpleNamespace

import pytest

from mesh_chat import app_owned_host as host
from mesh_chat.connection.model import ConnectionKey, Resource
from mesh_chat.ipc import FrameWriter, decode_all, encode_frame


def service_with_one_public_intent():
    identity = object()
    source = Resource("native", "private-source")
    context = {"id": "native-private-id", "runtime_epoch": "current-epoch",
               "identity_hash": "identity-hash", "identity": lambda: identity,
               "source": source, "role": "offer", "state": "retired"}
    row = {"caller": "installed-app", "profile": "local", "pairing": "opaque-pairing",
           "native_id": context["id"], "runtime_epoch": context["runtime_epoch"],
           "identity_hash": context["identity_hash"], "terminal_state": "retired",
           "cancel_requested": False}
    calls = []

    def retirement(**arguments):
        calls.append(arguments)
        return {"phase": "wait_answer", "event": "failed", "reason": "transient"}

    owner = SimpleNamespace(_lock=RLock(), runtime_epoch="current-epoch",
                            pairing_retirement_diagnostic=retirement)
    store = SimpleNamespace(_lock=RLock(), items=lambda kind, limit: [("secret-row-id", row)])
    service = SimpleNamespace(_dispatch_lock=RLock(), _connection_runtime=SimpleNamespace(owner=owner),
                              _runtime_incarnation="current-epoch", _identity=identity,
                              _native_pairing_contexts={context["id"]: context}, store=store)
    service.native_pairing_status = lambda *_: pytest.fail("Diagnostic reconciled pairing status")
    service._native_pairing_profiles = lambda: pytest.fail("Diagnostic reconciled pairing profiles")
    return service, context, row, calls


def launch(tmp_path, monkeypatch, service, flag=None):
    monkeypatch.setattr(host, "_require_windows", lambda: None)
    environment = {"MESH_CHAT_APP_DATA_DIRECTORY": str(tmp_path),
                   "MESH_CHAT_CORE_API_PIPE": r"\\.\pipe\mesh-chat-independent-test",
                   "MESH_CHAT_CORE_API_CLIENT_IMAGE": r"C:\App\node.exe",
                   "MESH_CHAT_APP_PARENT_PID": "42"}
    if flag is not None:
        environment["MESH_CHAT_APP_PAIRING_DIAGNOSTICS"] = flag
    messages, closes = [], []

    def runtime_factory(_):
        def close():
            closes.append(tuple(message["type"] for message in messages))
            return True
        return SimpleNamespace(service=service, close=close)

    status = host.run(io.BytesIO(), SimpleNamespace(write=messages.append),
                      watch_parent=lambda _: None, environment=environment,
                      runtime_factory=runtime_factory)
    return status, messages, closes


def test_default_and_explicit_off_keep_lifetime_stream_unchanged(tmp_path, monkeypatch):
    service, _, _, calls = service_with_one_public_intent()
    for flag in (None, "0"):
        status, messages, closes = launch(tmp_path, monkeypatch, service, flag)
        assert status == 0
        assert [message["type"] for message in messages] == ["runtime_started", "runtime_stopped"]
        assert closes == [("runtime_started",)]
    assert calls == []


def test_opt_in_reports_exact_cause_before_cleanup_without_private_identifiers(tmp_path, monkeypatch):
    service, context, _, calls = service_with_one_public_intent()
    context["reason"] = "ineligible"  # Current actor state must not replace first cause.
    status, messages, closes = launch(tmp_path, monkeypatch, service, "1")
    assert status == 0
    assert [message["type"] for message in messages] == [
        "runtime_started", "runtime_pairing_diagnostics", "runtime_stopped"]
    observation = messages[1]["observation"]
    assert observation == {"status": "observed", "total_intents": 1, "intents": [
        {"role": "offer", "state": "retired", "retirement": {
            "phase": "wait_answer", "event": "failed", "reason": "transient"}}]}
    assert closes == [("runtime_started", "runtime_pairing_diagnostics")]
    assert len(calls) == 1
    assert calls[0] == {"key": ConnectionKey("pairing", context["id"],
                                            context["identity_hash"], None),
                        "runtime_epoch": "current-epoch", "source": context["source"]}
    assert all(private not in str(messages[1]) for private in (
        "native-private-id", "private-source", "secret-row-id", "identity-hash", "opaque-pairing"))


@pytest.mark.parametrize("change", ["foreign_id", "stale_epoch", "foreign_identity",
                                  "unknown_cause", "malformed_cause", "foreign_role",
                                  "missing_source", "foreign_source",
                                  "too_many_contexts", "too_many_rows"])
def test_unproven_or_unbounded_intent_is_unavailable(tmp_path, monkeypatch, change):
    service, context, row, calls = service_with_one_public_intent()
    if change == "foreign_id":
        row["native_id"] = "another-intent"
    elif change == "stale_epoch":
        row["runtime_epoch"] = "previous-epoch"
    elif change == "foreign_identity":
        context["identity"] = lambda: object()
    elif change == "unknown_cause":
        service._connection_runtime.owner.pairing_retirement_diagnostic = lambda **_: {
            "phase": "unknown", "event": "unknown", "reason": "unknown"}
    elif change == "malformed_cause":
        service._connection_runtime.owner.pairing_retirement_diagnostic = lambda **_: {
            "phase": "secret-path", "event": "failed", "reason": "transient"}
    elif change == "foreign_role":
        context["role"] = "private"
    elif change == "missing_source":
        context["source"] = None
    elif change == "foreign_source":
        context["source"] = Resource("foreign", "another-source")
    elif change == "too_many_contexts":
        service._native_pairing_contexts.update({str(index): {} for index in range(32)})
    else:
        service.store.items = lambda kind, limit: [(str(index), row) for index in range(33)]
    status, messages, closes = launch(tmp_path, monkeypatch, service, "1")
    assert status == 0
    assert messages[1] == {"v": 1, "type": "runtime_pairing_diagnostics",
                           "observation": {"status": "unavailable",
                                           "total_intents": 0 if change == "too_many_contexts" else 1,
                                           "intents": []}}
    assert closes == [("runtime_started", "runtime_pairing_diagnostics")]
    assert "secret-path" not in str(messages)


def test_malformed_flag_is_rejected_before_runtime_allocation(tmp_path, monkeypatch):
    service, _, _, _ = service_with_one_public_intent()
    status, messages, closes = launch(tmp_path, monkeypatch, service, "yes")
    assert status == 2
    assert [message["type"] for message in messages] == ["runtime_failed"]
    assert closes == []


def test_diagnostic_error_cannot_suppress_cleanup(tmp_path, monkeypatch):
    service, _, _, _ = service_with_one_public_intent()
    service.store.items = lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("secret"))
    status, messages, closes = launch(tmp_path, monkeypatch, service, "1")
    assert status == 0
    assert messages[1]["observation"] == {"status": "unavailable", "total_intents": 0,
                                          "intents": []}
    assert closes == [("runtime_started", "runtime_pairing_diagnostics")]
    assert "secret" not in str(messages)


def test_oversized_diagnostic_is_replaced_by_bounded_unavailable(tmp_path, monkeypatch):
    import mesh_chat.app_owned_diagnostics as diagnostics

    service, _, _, _ = service_with_one_public_intent()
    monkeypatch.setattr(diagnostics, "observe_pairing", lambda _: {"leak": "x" * 5000})
    status, messages, closes = launch(tmp_path, monkeypatch, service, "1")
    assert status == 0
    assert messages[1]["observation"] == {"status": "unavailable", "total_intents": 0,
                                          "intents": []}
    assert closes == [("runtime_started", "runtime_pairing_diagnostics")]


def test_opt_in_uses_one_bounded_inherited_frame(tmp_path, monkeypatch):
    monkeypatch.setattr(host, "_require_windows", lambda: None)
    service, _, _, _ = service_with_one_public_intent()
    environment = {"MESH_CHAT_APP_DATA_DIRECTORY": str(tmp_path),
                   "MESH_CHAT_CORE_API_PIPE": r"\\.\pipe\mesh-chat-independent-test",
                   "MESH_CHAT_CORE_API_CLIENT_IMAGE": r"C:\App\node.exe",
                   "MESH_CHAT_APP_PARENT_PID": "42",
                   "MESH_CHAT_APP_PAIRING_DIAGNOSTICS": "1"}
    output = io.BytesIO()
    runtime = SimpleNamespace(service=service, close=lambda: True)
    assert host.run(io.BytesIO(), FrameWriter(output), watch_parent=lambda _: None,
                    environment=environment, runtime_factory=lambda _: runtime) == 0
    frames = decode_all(output.getvalue())
    assert [frame["type"] for frame in frames] == [
        "runtime_started", "runtime_pairing_diagnostics", "runtime_stopped"]
    assert len(encode_frame(frames[1])) <= 4096


def test_nonempty_lifetime_stream_emits_no_diagnostic(tmp_path, monkeypatch):
    monkeypatch.setattr(host, "_require_windows", lambda: None)
    service, _, _, calls = service_with_one_public_intent()
    messages, closes = [], []
    environment = {"MESH_CHAT_APP_DATA_DIRECTORY": str(tmp_path),
                   "MESH_CHAT_CORE_API_PIPE": r"\\.\pipe\mesh-chat-independent-test",
                   "MESH_CHAT_CORE_API_CLIENT_IMAGE": r"C:\App\node.exe",
                   "MESH_CHAT_APP_PARENT_PID": "42",
                   "MESH_CHAT_APP_PAIRING_DIAGNOSTICS": "1"}
    runtime = SimpleNamespace(service=service, close=lambda: closes.append(True) or True)
    status = host.run(io.BytesIO(b"x"), SimpleNamespace(write=messages.append),
                      watch_parent=lambda _: None, environment=environment,
                      runtime_factory=lambda _: runtime)
    assert status == 2 and closes == [True]
    assert [message["type"] for message in messages] == [
        "runtime_started", "runtime_failed", "runtime_stopped"]
    assert calls == []


@pytest.mark.parametrize("lock_name", ["dispatch", "store", "owner"])
def test_busy_lock_returns_unavailable_without_waiting_for_owner(tmp_path, monkeypatch, lock_name):
    service, _, _, calls = service_with_one_public_intent()
    lock = {"dispatch": service._dispatch_lock, "store": service.store._lock,
            "owner": service._connection_runtime.owner._lock}[lock_name]
    entered = Event()
    release = Event()

    def hold():
        with lock:
            entered.set()
            release.wait(2)

    worker = Thread(target=hold)
    worker.start()
    try:
        assert entered.wait(1)
        status, messages, _ = launch(tmp_path, monkeypatch, service, "1")
        assert status == 0
        assert messages[1]["observation"]["status"] == "unavailable"
        assert calls == []
    finally:
        release.set()
        worker.join(2)
