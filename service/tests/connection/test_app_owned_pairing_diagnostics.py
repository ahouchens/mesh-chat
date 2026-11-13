"""Private EOF-only pairing observation on the normal app-owned status pipe."""

import io
from threading import Event, RLock, Thread
from types import SimpleNamespace

import pytest

from mesh_chat import app_owned_host as host
from mesh_chat import app_owned_diagnostics as diagnostics
from mesh_chat.connection.model import ConnectionKey, Resource
from mesh_chat.ipc import FrameWriter, decode_all, encode_frame
from test_pairing_runtime import native_pairing, run_until


def service_with_one_public_intent(*, capture=True, caller=diagnostics.APP_CALLER,
                                   record_id="secret-row-id"):
    identity = object()
    source = Resource("native", "private-source")
    context = {"id": "native-private-id", "runtime_epoch": "current-epoch",
               "identity_hash": "identity-hash", "identity": lambda: identity,
               "source": source, "role": "offer", "state": "retired"}
    row = {"caller": caller, "profile": "local", "pairing": "opaque-pairing",
           "native_id": context["id"], "runtime_epoch": context["runtime_epoch"],
           "identity_hash": context["identity_hash"], "terminal_state": "retired",
           "cancel_requested": False}
    calls = []

    def retirement(**arguments):
        calls.append(arguments)
        return {"phase": "wait_answer", "event": "failed", "reason": "transient"}

    owner = SimpleNamespace(_lock=RLock(), runtime_epoch="current-epoch",
                            pairing_retirement_diagnostic=retirement)
    store = SimpleNamespace(_lock=RLock(),
                            opaque_id=lambda *parts: "secret-row-id",
                            get=lambda kind, key: row if (kind, key) == (
                                "api_pairing_intent", record_id) else None)
    service = SimpleNamespace(_dispatch_lock=RLock(), _connection_runtime=SimpleNamespace(owner=owner),
                              _runtime_incarnation="current-epoch", _identity=identity,
                              _native_pairing_contexts={context["id"]: context}, store=store)
    service.native_pairing_status = lambda *_: pytest.fail("Diagnostic reconciled pairing status")
    service._native_pairing_profiles = lambda: pytest.fail("Diagnostic reconciled pairing profiles")
    if capture:
        diagnostics.capture_public_pairing(service, record_id, row, context)
    return service, context, row, calls


def test_actual_public_admission_captures_vault_and_supervisor_proof(native_pairing):
    from mesh_chat.errors import ValidationError
    from test_core_pairing_intents import public_client

    create, _ = native_pairing
    service, _, created, *_ = create()
    invoke, _, profile = public_client(service, caller=diagnostics.APP_CALLER)
    begun = invoke("peer.pairing_begin", {"profile": profile, "role": "offer"},
                   "owner-diagnostic-offer-key")
    assert begun["ok"]
    pairing = begun["result"]["pairing"]
    proof = service._app_owned_pairing_diagnostic_provenance
    assert type(proof) is diagnostics.PairingProvenance
    assert proof.service is service and proof.store is service.store
    assert service._native_pairing_contexts[proof.native_id] is proof.context
    assert proof.record_id == service.store.opaque_id(
        "core-pairing-intent:v1", diagnostics.APP_CALLER, "local", pairing)

    def state():
        reply = invoke("peer.pairing_query", {"profile": profile, "pairing": pairing})
        assert reply["ok"]
        return reply["result"]["state"]

    run_until(service, lambda: state() == "offer_ready")
    def rejected_answer(*_args, **_kwargs):
        raise ValidationError("PRIVATE_DOCUMENT_FAILURE")
    service.signal_fetch = rejected_answer
    run_until(service, lambda: state() == "retired")
    before = service.store._db.execute(
        "SELECT kind,record_id,sealed FROM records ORDER BY kind,record_id").fetchall()
    observation = diagnostics.observe_pairing(service)
    assert observation == {"status": "observed", "total_intents": 1, "intents": [
        {"role": "offer", "state": "retired", "retirement": {
            "phase": "wait_answer", "event": "failed", "reason": "invalid_document"}}]}
    assert service.store._db.execute(
        "SELECT kind,record_id,sealed FROM records ORDER BY kind,record_id").fetchall() == before
    assert len(created) == 1 and "PRIVATE" not in str(observation)


def test_capture_failure_does_not_change_public_admission(native_pairing, monkeypatch):
    from mesh_chat.core_api import service_pairing_intents
    from test_core_pairing_intents import public_client

    create, _ = native_pairing
    service, *_ = create()
    invoke, _, profile = public_client(service, caller=diagnostics.APP_CALLER)
    monkeypatch.setattr(service_pairing_intents, "capture_public_pairing",
                        lambda *_: (_ for _ in ()).throw(OSError("diagnostic unavailable")))
    begun = invoke("peer.pairing_begin", {"profile": profile, "role": "offer"},
                   "diagnostic-failure-offer-key")
    assert begun["ok"]
    assert begun["result"]["state"] in {"reserved", "offer_ready"}


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
                                  "too_many_contexts", "substituted_context"])
def test_unproven_or_unbounded_intent_is_unavailable(tmp_path, monkeypatch, change):
    service, context, row, calls = service_with_one_public_intent()
    if change == "foreign_id":
        context["id"] = "another-intent"
    elif change == "stale_epoch":
        context["runtime_epoch"] = "previous-epoch"
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
        service._native_pairing_contexts[context["id"]] = dict(context)
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
    service._connection_runtime.owner.pairing_retirement_diagnostic = (
        lambda **_: (_ for _ in ()).throw(OSError("secret")))
    status, messages, closes = launch(tmp_path, monkeypatch, service, "1")
    assert status == 0
    assert messages[1]["observation"] == {"status": "unavailable", "total_intents": 0,
                                          "intents": []}
    assert closes == [("runtime_started", "runtime_pairing_diagnostics")]
    assert "secret" not in str(messages)


def test_eof_observation_never_reads_the_vault(tmp_path, monkeypatch):
    service, context, row, _ = service_with_one_public_intent(capture=False)
    def forbidden(*_args, **_kwargs):
        pytest.fail("Diagnostic reread the vault")
    service.store.get = forbidden
    service.store.items = forbidden
    diagnostics.capture_public_pairing(service, "secret-row-id", row, context)
    service.store.opaque_id = forbidden
    status, messages, _ = launch(tmp_path, monkeypatch, service, "1")
    assert status == 0
    assert messages[1]["observation"]["status"] == "observed"


@pytest.mark.parametrize("unproven", ["wrong_caller", "wrong_record_key", "wrong_index"])
def test_admission_cannot_capture_unproven_record(tmp_path, monkeypatch, unproven):
    service, context, row, _ = service_with_one_public_intent(
        capture=False, caller="foreign-app" if unproven == "wrong_caller" else diagnostics.APP_CALLER)
    record_id = "wrong-key" if unproven == "wrong_record_key" else "secret-row-id"
    if unproven == "wrong_index":
        service.store.opaque_id = lambda *parts: "another-index"
    diagnostics.capture_public_pairing(service, record_id, row, context)
    _, messages, _ = launch(tmp_path, monkeypatch, service, "1")
    assert messages[1]["observation"] == {
        "status": "unavailable", "total_intents": 1, "intents": []}


def test_replay_of_same_intent_keeps_proof_but_distinct_intent_is_ambiguous():
    service, context, row, _ = service_with_one_public_intent()
    first = service._app_owned_pairing_diagnostic_provenance
    diagnostics.capture_public_pairing(service, "secret-row-id", row, context)
    assert service._app_owned_pairing_diagnostic_provenance is first
    second = {**row, "pairing": "different-pairing"}
    service.store.get = lambda kind, key: second
    diagnostics.capture_public_pairing(service, "secret-row-id", second, context)
    assert diagnostics.observe_pairing(service)["status"] == "unavailable"


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


@pytest.mark.parametrize("lock_name", ["dispatch", "owner"])
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
