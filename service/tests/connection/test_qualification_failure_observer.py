"""Same-frame private diagnostics through the actual mobile/Core framing path."""
import base64
import contextvars
import hashlib
import json
import socket
import ssl
import threading
import weakref
from contextlib import contextmanager
from urllib.error import HTTPError, URLError

import pytest

from mesh_chat import mobile_bridge as mobile
from mesh_chat.core_api import android_host, qualification_host as qualification
from mesh_chat.core_api.wire_codec import decode_frame, encode_frame
from mesh_chat.errors import NetworkUnavailable
from mesh_chat import _qualification_failure_observer as observer, turn_credentials as turn
from mesh_chat.core_api import session as core, wire
from mesh_chat.core_api.errors import ApiFailure
from mesh_chat.core_api.calls import CallIceObservation
from mesh_chat.errors import ValidationError, StorageUnavailable
from test_core_messages import host, request


class Sink:
    def __init__(self):
        self.value = None

    def set(self, value):
        assert self.value is None
        self.value = value


@pytest.fixture
def published(host, monkeypatch):
    service = host()
    android_host.close_all()
    monkeypatch.setattr(mobile, "_service", service)
    monkeypatch.setattr(mobile, "_profile_host", None)
    monkeypatch.setattr(mobile, "_profile_installing", False)
    monkeypatch.setattr(mobile, "_service_binding", ("synthetic",))
    monkeypatch.setattr(mobile, "_event_incarnation", "a" * 32)
    monkeypatch.setattr(qualification, "_android_service", weakref.ref(service))
    monkeypatch.setattr(qualification, "_android_own_uid", lambda: None)
    capture = getattr(qualification, "_capture_android_publication", lambda: None)
    monkeypatch.setattr(qualification, "_android_publication", capture(), raising=False)
    incarnation = service._runtime_incarnation
    binding = incarnation + hashlib.sha256((incarnation + service._identity.hash.hex()).encode("ascii")).hexdigest()[:32]
    yield service, binding
    android_host.close_all()


def exchange(value, binding=None, sink=None):
    frame = base64.b64encode(encode_frame(value)).decode("ascii")
    if sink is None:
        return mobile.core_exchange("qualification", frame, "owner")
    observed = getattr(qualification, "android_observed_core_exchange",
                       lambda caller, frame, scope, binding, sink: mobile.core_exchange(caller, frame, scope))
    return observed("qualification", frame, "owner", binding, sink)


def reply(encoded):
    return decode_frame(base64.b64decode(encoded))


def profile():
    return reply(exchange(request("runtime.capabilities")))["result"]["profiles"][0]


def test_actual_core_internal_observation_preserves_bytes_and_calls_once(published, monkeypatch):
    service, binding = published
    handle = profile()
    calls = []

    def fail():
        calls.append(1)
        raise NetworkUnavailable("PRIVATE broker credential sentinel")

    monkeypatch.setattr(service, "call_ice_servers", fail)
    value = request("call.ice_servers", profile=handle)
    ordinary = exchange(value)
    sink = Sink()
    observed = exchange(value, binding, sink)
    assert observed == ordinary
    assert calls == [1, 1]
    assert reply(observed)["error"]["code"] == "internal"
    assert json.loads(sink.value) == {"v": 1, "request_id": "request:1", "operation": "call.ice_servers",
        "error_code": "internal", "stage": "ice_service", "category": "network_unavailable", "cause": "none"}


def test_private_publication_is_captured_only_after_successful_existing_initialize(published, monkeypatch, tmp_path):
    service, binding = published
    mobile._service = None
    monkeypatch.setattr(qualification, "reserve_fresh_profile", lambda value: None)
    monkeypatch.setattr(qualification, "mark_initialized_profile", lambda value: None)

    def initialize(raw):
        mobile._service = service
        return json.dumps({"ok": True, "result": {"already": "existing"}})

    monkeypatch.setattr(mobile, "initialize_native", initialize)
    raw = json.dumps({"profile_dir": str(tmp_path / "mesh-qualification-capture"),
                      "vault_key": base64.b64encode(b"x" * 32).decode("ascii"),
                      "display_name": "Mesh qualification", "platform": "android"})
    assert json.loads(qualification.android_initialize(raw)) == {"ok": True, "result": {"already": "existing"}}
    assert qualification._android_publication.binding == binding
    assert qualification._android_publication.current()


def test_retiring_mobile_service_clears_only_its_initialized_publication(published):
    service, binding = published
    publication = qualification._android_publication
    qualification._forget_android_publication(object())
    assert qualification._android_publication is publication
    assert json.loads(mobile.shutdown())["ok"]
    assert qualification._android_service is None and qualification._android_publication is None


def fail_with(error):
    def fail(*args, **kwargs):
        raise error
    return fail


@pytest.mark.parametrize("fault", ["setup", "enter", "caught", "classify", "snapshot", "close", "reset", "sink"])
def test_observer_faults_keep_actual_primary_once(published, monkeypatch, fault):
    service, binding = published
    value = request("call.ice_servers", profile=profile())
    monkeypatch.setattr(service, "call_ice_servers", fail_with(NetworkUnavailable("PRIVATE")))
    ordinary = exchange(value)
    called = []
    original = mobile.core_exchange

    def counted(*args):
        primary = original(*args)
        called.append(primary)
        return primary

    monkeypatch.setattr(mobile, "core_exchange", counted)
    broken = fail_with(RuntimeError("PRIVATE diagnostic failure"))
    sink = Sink()
    if fault == "setup":
        monkeypatch.setattr(qualification, "_android_own_uid", broken)
    elif fault in {"enter", "reset"}:
        monkeypatch.setattr(observer, fault, broken)
    elif fault == "classify":
        monkeypatch.setattr(observer, "_classify_cause", broken)
    elif fault == "sink":
        monkeypatch.setattr(sink, "set", broken)
    else:
        monkeypatch.setattr(observer.Invocation, fault, broken)
    result = exchange(value, binding, sink)
    assert len(called) == 1 and result is called[0] and result == ordinary
    assert sink.value is None
    assert observer._ACTIVE.get() is None


def test_original_escape_rethrows_same_exception_without_retry(published, monkeypatch):
    _, binding = published
    error = RuntimeError("PRIVATE primary escape")
    calls = []

    def fail(*args):
        calls.append(1)
        raise error

    monkeypatch.setattr(mobile, "core_exchange", fail)
    with pytest.raises(RuntimeError) as caught:
        exchange(request("runtime.capabilities"), binding, Sink())
    assert caught.value is error and calls == [1]
    assert observer._ACTIVE.get() is None


def test_failed_reset_and_clear_leave_only_a_closed_context(published, monkeypatch):
    service, binding = published
    value = request("call.ice_servers", profile=profile())
    monkeypatch.setattr(service, "call_ice_servers", fail_with(NetworkUnavailable("PRIVATE")))
    token = observer._ACTIVE.set(None)
    try:
        monkeypatch.setattr(observer, "reset", fail_with(RuntimeError()))
        monkeypatch.setattr(observer, "clear", fail_with(RuntimeError()))
        sink = Sink()
        assert reply(exchange(value, binding, sink))["error"]["code"] == "internal"
        stale = observer._ACTIVE.get()
        assert stale.closed and stale.leaf is None and stale.outcome is None and stale.publication is None
        observer.note("caught", RuntimeError("PRIVATE later"), "ice_service")
        assert stale.leaf is None and sink.value is None
    finally:
        observer._ACTIVE.reset(token)


@pytest.mark.parametrize("change", ["binding", "publication_equal_tuple", "event", "identity", "incarnation",
                                    "store", "detached", "profile_installing", "missing_initialization"])
def test_current_initialized_publication_required(published, monkeypatch, change):
    service, binding = published
    original_store = service.store
    value = request("call.ice_servers", profile=profile())
    monkeypatch.setattr(service, "call_ice_servers", fail_with(NetworkUnavailable("PRIVATE")))
    if change == "binding":
        binding = "0" * 64
    elif change == "publication_equal_tuple":
        monkeypatch.setattr(mobile, "_service_binding", tuple(list(mobile._service_binding)))
    elif change == "event":
        monkeypatch.setattr(mobile, "_event_incarnation", "b" * 32)
    elif change == "identity":
        from types import SimpleNamespace
        monkeypatch.setattr(service, "_identity", SimpleNamespace(hash=service._identity.hash))
    elif change == "incarnation":
        monkeypatch.setattr(service, "_runtime_incarnation", "b" * 32)
    elif change == "store":
        from types import SimpleNamespace
        monkeypatch.setattr(service, "store", SimpleNamespace())
    elif change == "detached":
        monkeypatch.setattr(mobile, "_service", None)
    elif change == "profile_installing":
        monkeypatch.setattr(mobile, "_profile_installing", True)
    else:
        monkeypatch.setattr(qualification, "_android_publication", None)
    ordinary = exchange(value)
    sink = Sink()
    assert exchange(value, binding, sink) == ordinary
    assert sink.value is None
    if change == "store":
        service.store = original_store


@pytest.mark.parametrize("seam", ["actual_route", "post_return"])
def test_publication_change_during_exchange_discards_metadata(published, monkeypatch, seam):
    service, binding = published
    value = request("call.ice_servers", profile=profile())
    calls = []
    original = mobile.core_exchange

    def fail():
        calls.append(1)
        if seam == "post_return":
            mobile._event_incarnation = "b" * 32
        raise NetworkUnavailable("PRIVATE")

    def changed(*args):
        if seam == "actual_route":
            mobile._event_incarnation = "b" * 32
        return original(*args)

    monkeypatch.setattr(service, "call_ice_servers", fail)
    monkeypatch.setattr(mobile, "core_exchange", changed)
    sink = Sink()
    assert reply(exchange(value, binding, sink))["error"]["code"] == "internal"
    assert calls == [1] and sink.value is None


@pytest.mark.parametrize("request_id", [None, "", "x" * 81, "PRIVATE\n", 1, True])
def test_invalid_or_null_correlation_never_exports(published, monkeypatch, request_id):
    service, binding = published
    value = request("call.ice_servers", profile=profile())
    value["request_id"] = request_id
    monkeypatch.setattr(service, "call_ice_servers", fail_with(NetworkUnavailable("PRIVATE")))
    ordinary = exchange(value)
    sink = Sink()
    assert exchange(value, binding, sink) == ordinary and sink.value is None


@pytest.mark.parametrize("error", [ValidationError("PRIVATE"), StorageUnavailable("PRIVATE"), ApiFailure("forbidden")])
def test_non_internal_outcomes_keep_original_mapping(published, monkeypatch, error):
    service, binding = published
    value = request("call.ice_servers", profile=profile())
    monkeypatch.setattr(service, "call_ice_servers", fail_with(error))
    ordinary = exchange(value)
    sink = Sink()
    assert exchange(value, binding, sink) == ordinary and sink.value is None
    assert reply(ordinary)["error"]["code"] != "internal"


def test_capabilities_failure_has_actual_body_witness(published, monkeypatch):
    _, binding = published
    monkeypatch.setattr(core.CoreSession, "_capabilities", fail_with(RuntimeError("PRIVATE")))
    sink = Sink()
    assert reply(exchange(request("runtime.capabilities"), binding, sink))["error"]["code"] == "internal"
    assert json.loads(sink.value)["stage"] == "capabilities"


def test_success_clears_tentative_leaf_and_next_frame_isolated(published, monkeypatch):
    service, binding = published
    value = request("call.ice_servers", profile=profile())

    def recovered():
        observer.note("caught", NetworkUnavailable("PRIVATE recovered"), "broker_open")
        return {"iceServers": []}

    monkeypatch.setattr(service, "call_ice_servers", recovered)
    sink = Sink()
    assert reply(exchange(value, binding, sink))["ok"] and sink.value is None
    monkeypatch.setattr(service, "call_ice_servers", fail_with(RuntimeError("PRIVATE replacement")))
    assert reply(exchange(value, binding, sink))["error"]["code"] == "internal"
    assert json.loads(sink.value)["stage"] == "ice_service"


def test_actual_success_encode_failure_is_distinct_from_session_escape(published, monkeypatch):
    service, binding = published
    value = request("call.ice_servers", profile=profile())
    monkeypatch.setattr(service, "call_ice_servers", lambda: {"iceServers": [{"credential": float("nan")}]})
    sink = Sink()
    result = exchange(value, binding, sink)
    assert reply(result)["error"]["code"] == "internal"
    selected = json.loads(sink.value)
    assert (selected["stage"], selected["category"]) == ("frame_encode", "response_encoding")
    assert android_host.active_callers() == ["qualification"]
    assert android_host._sessions[("qualification", "owner")]._closed


def test_failed_encoding_of_domain_error_replaces_earlier_broker_leaf(published, monkeypatch):
    service, binding = published
    handle = profile()
    monkeypatch.setattr(service, "call_ice_servers", fail_with(NetworkUnavailable("PRIVATE old broker")))
    original = wire.encode_frame
    calls = []

    def fail_first(value):
        calls.append(1)
        if len(calls) == 1:
            raise UnicodeError("PRIVATE new encode failure")
        return original(value)

    monkeypatch.setattr(wire, "encode_frame", fail_first)
    sink = Sink()
    response = exchange(request("call.ice_servers", profile=handle), binding, sink)
    assert reply(response)["error"]["code"] == "internal" and calls == [1, 1]
    selected = json.loads(sink.value)
    assert (selected["stage"], selected["category"]) == ("frame_encode", "response_encoding")


def test_actual_core_admission_failure_only_claims_admission(published, monkeypatch):
    _, binding = published
    monkeypatch.setattr(core, "parse_request", fail_with(RuntimeError("PRIVATE parse failure")))
    sink = Sink()
    assert reply(exchange(request("runtime.capabilities"), binding, sink))["error"]["code"] == "internal"
    assert json.loads(sink.value)["stage"] == "core_admission"


def test_actual_ice_view_rejection_has_source_witnessed_invalid_observation(published, monkeypatch):
    _, binding = published
    handle = profile()
    from mesh_chat.core_api.service_calls import ServiceCallSettings
    monkeypatch.setattr(ServiceCallSettings, "ice", lambda self, profile: CallIceObservation("PRIVATE"))
    sink = Sink()
    assert reply(exchange(request("call.ice_servers", profile=handle), binding, sink))["error"]["code"] == "internal"
    selected = json.loads(sink.value)
    assert (selected["stage"], selected["category"]) == ("ice_view", "invalid_observation")


@pytest.mark.parametrize("scope, caller", [("consumer", "qualification"), ("owner", "")])
def test_foreign_scope_or_invalid_host_caller_never_exports(published, monkeypatch, scope, caller):
    service, binding = published
    monkeypatch.setattr(service, "call_ice_servers", fail_with(NetworkUnavailable("PRIVATE")))
    handle = profile()
    frame = base64.b64encode(encode_frame(request("call.ice_servers", profile=handle))).decode("ascii")
    ordinary = mobile.core_exchange(caller, frame, scope)
    sink = Sink()
    assert qualification.android_observed_core_exchange(caller, frame, scope, binding, sink) == ordinary
    assert sink.value is None


def test_sink_runs_after_all_core_and_host_locks_are_released(published, monkeypatch):
    service, binding = published
    handle = profile()
    monkeypatch.setattr(service, "call_ice_servers", fail_with(NetworkUnavailable("PRIVATE")))

    class LockCheckingSink(Sink):
        def set(self, value):
            acquired = []

            def check():
                with mobile._service_lock, android_host._lock, service._dispatch_lock:
                    acquired.append(True)

            worker = threading.Thread(target=check)
            worker.start()
            worker.join(timeout=1)
            assert acquired == [True]
            super().set(value)

    sink = LockCheckingSink()
    assert reply(exchange(request("call.ice_servers", profile=handle), binding, sink))["error"]["code"] == "internal"
    assert sink.value is not None


def test_nested_observed_call_cannot_borrow_outer_failure_or_publish_either(published, monkeypatch):
    service, binding = published
    handle = profile()
    nested_sink = Sink()
    nested = []

    def ice():
        nested.append(exchange(request("runtime.capabilities"), binding, nested_sink))
        raise NetworkUnavailable("PRIVATE outer")

    monkeypatch.setattr(service, "call_ice_servers", ice)
    outer_sink = Sink()
    assert reply(exchange(request("call.ice_servers", profile=handle), binding, outer_sink))["error"]["code"] == "internal"
    assert len(nested) == 1 and reply(nested[0])["ok"]
    assert outer_sink.value is None and nested_sink.value is None


def test_copied_context_after_close_cannot_publish_a_late_record(published, monkeypatch):
    service, binding = published
    handle = profile()
    copied = []

    def ice():
        copied.append(contextvars.copy_context())
        raise NetworkUnavailable("PRIVATE")

    monkeypatch.setattr(service, "call_ice_servers", ice)
    sink = Sink()
    assert reply(exchange(request("call.ice_servers", profile=handle), binding, sink))["error"]["code"] == "internal"
    first = sink.value

    def late():
        active = observer._ACTIVE.get()
        assert active.closed and active.publication is None
        observer.note("caught", TimeoutError("PRIVATE late"), "broker_open")
        observer.note("seal", "request:1", "internal")
        assert active.snapshot() is None

    copied[0].run(late)
    assert sink.value == first


def test_profile_host_route_disables_observation(published, monkeypatch):
    _, binding = published
    calls = []

    class ProfileHost:
        def exchange(self, caller, frame, scope):
            calls.append((caller, scope))
            return encode_frame({"api_version": 1, "request_id": "request:1", "ok": False,
                                 "error": {"code": "internal", "retry_after_ms": None}})

    monkeypatch.setattr(mobile, "_profile_host", ProfileHost())
    value = request("call.ice_servers", profile="x" * 32)
    ordinary = exchange(value)
    sink = Sink()
    assert exchange(value, binding, sink) == ordinary
    assert calls == [("qualification", "owner"), ("qualification", "owner")]
    assert sink.value is None


def test_mobile_normalization_discards_selected_failure(published, monkeypatch):
    service, binding = published
    handle = profile()
    monkeypatch.setattr(service, "call_ice_servers", fail_with(NetworkUnavailable("PRIVATE")))
    frame = base64.b64encode(encode_frame(request("call.ice_servers", profile=handle))).decode("ascii")
    original = mobile.base64.b64encode
    calls = []

    def fail_first(value):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("PRIVATE later normalization")
        return original(value)

    monkeypatch.setattr(mobile.base64, "b64encode", fail_first)
    sink = Sink()
    result = qualification.android_observed_core_exchange("qualification", frame, "owner", binding, sink)
    assert calls == [1, 1]
    assert reply(result)["request_id"] is None and reply(result)["error"]["code"] == "invalid_request"
    assert sink.value is None


def test_actual_transaction_exit_escape_replaces_prior_leaf(published, monkeypatch):
    service, binding = published
    value = request("call.ice_servers", profile=profile())
    monkeypatch.setattr(service, "call_ice_servers", fail_with(NetworkUnavailable("PRIVATE old")))

    @contextmanager
    def replacement():
        yield
        raise PermissionError("PRIVATE exit")

    android_host._sessions[("qualification", "owner")]._session._transaction = replacement()
    sink = Sink()
    assert reply(exchange(value, binding, sink))["error"]["code"] == "internal"
    selected = json.loads(sink.value)
    assert (selected["stage"], selected["category"], selected["cause"]) == ("session_escape", "unexpected", "permission_denied")


def test_failed_fallback_encoding_normalizes_null_id_and_drops_prior_leaf(published, monkeypatch):
    service, binding = published
    value = request("call.ice_servers", profile=profile())
    monkeypatch.setattr(service, "call_ice_servers", fail_with(NetworkUnavailable("PRIVATE")))
    monkeypatch.setattr(wire, "encode_frame", fail_with(ValueError("PRIVATE encoding")))
    sink = Sink()
    result = reply(exchange(value, binding, sink))
    assert result["request_id"] is None and result["error"]["code"] == "invalid_request"
    assert sink.value is None


@pytest.mark.parametrize("result, stage, category", [(None, "ice_return", "invalid_observation")])
def test_invalid_return_has_only_source_witnessed_category(published, monkeypatch, result, stage, category):
    service, binding = published
    value = request("call.ice_servers", profile=profile())
    monkeypatch.setattr(service, "call_ice_servers", lambda: result)
    sink = Sink()
    assert reply(exchange(value, binding, sink))["error"]["code"] == "internal"
    selected = json.loads(sink.value)
    assert (selected["stage"], selected["category"]) == (stage, category)


@pytest.mark.parametrize("error, cause", [
    (ssl.SSLCertVerificationError("PRIVATE certificate"), "certificate_verification"),
    (ssl.SSLError("PRIVATE TLS"), "tls_other"), (socket.gaierror("PRIVATE address"), "name_resolution"),
    (TimeoutError("PRIVATE timeout"), "timeout"), (HTTPError("PRIVATE url", 403, "PRIVATE", {}, None), "http_error"),
    (json.JSONDecodeError("PRIVATE", "PRIVATE body", 0), "json_decode"),
    (FileNotFoundError("PRIVATE CA path"), "file_not_found"), (PermissionError("PRIVATE path"), "permission_denied"),
    (URLError(ssl.SSLCertVerificationError("PRIVATE")), "certificate_verification"),
    (RuntimeError("PRIVATE"), "none")])
def test_bounded_exact_known_cause_classes(error, cause):
    assert observer._classify_cause(error) == cause


def test_cause_classifier_never_reads_messages_context_or_arbitrary_reason():
    class Hostile(RuntimeError):
        def __getattribute__(self, name):
            raise AssertionError("PRIVATE attribute access")

        def __str__(self):
            raise AssertionError("PRIVATE text")

    error = Hostile()
    error.__context__ = TimeoutError("PRIVATE ignored context")
    assert observer._classify_cause(error) == "none"
    error.__cause__ = RuntimeError("PRIVATE")
    assert observer._classify_cause(error) == "other"
    first_cause = BaseException.__dict__["__cause__"].__get__(error, BaseException)
    first_cause.__cause__ = RuntimeError("PRIVATE")
    first_cause.__cause__.__cause__ = TimeoutError("PRIVATE too deep")
    assert observer._classify_cause(error) == "unknown"
    class UnknownTimeout(TimeoutError):
        pass
    assert observer._classify_cause(UnknownTimeout("PRIVATE")) == "none"


class BrokerResponse:
    status = 200
    body = b'{"iceServers":[{"urls":["turn:relay.invalid"]}]}'

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size):
        assert size == turn.MAX_RESPONSE_BYTES + 1
        return self.body


@pytest.mark.parametrize("stage", ["broker_url", "broker_request", "tls_context", "broker_open", "broker_status",
                                   "broker_read", "broker_size", "broker_json", "broker_validate"])
def test_actual_fetch_stage_witnesses_without_network(published, monkeypatch, stage):
    service, binding = published
    value = request("call.ice_servers", profile=profile())
    response = BrokerResponse()
    context = object()
    monkeypatch.setattr(turn.ssl, "create_default_context", lambda **kwargs: context)

    def opened(*args, **kwargs):
        assert kwargs == {"timeout": 8.0, "context": context}
        return response

    monkeypatch.setattr(turn.urllib.request, "urlopen", opened)
    error = RuntimeError("PRIVATE username credential URL CA sentinel")
    if stage == "broker_url":
        monkeypatch.setattr(turn, "validate_broker_url", fail_with(error))
    elif stage == "broker_request":
        monkeypatch.setattr(turn.urllib.request, "Request", fail_with(error))
    elif stage == "tls_context":
        monkeypatch.setattr(turn.ssl, "create_default_context", fail_with(error))
    elif stage == "broker_open":
        monkeypatch.setattr(turn.urllib.request, "urlopen", fail_with(URLError(ssl.SSLCertVerificationError("PRIVATE"))))
    elif stage == "broker_status":
        response.status = 403
    elif stage == "broker_read":
        response.read = fail_with(error)
    elif stage == "broker_size":
        response.body = b"x" * (turn.MAX_RESPONSE_BYTES + 1)
    elif stage == "broker_json":
        response.body = b"PRIVATE invalid body"
    elif stage == "broker_validate":
        response.body = b"{}"

    def ice():
        return {"iceServers": turn.fetch_ice_servers("https://relay.invalid/credentials")}

    monkeypatch.setattr(service, "call_ice_servers", ice)
    ordinary = exchange(value)
    sink = Sink()
    assert exchange(value, binding, sink) == ordinary
    selected = json.loads(sink.value)
    assert selected["stage"] == stage
    assert "PRIVATE" not in sink.value and len(sink.value.encode("utf-8")) <= 1024
    assert selected["category"] == ("unexpected" if stage in {"broker_url", "broker_request"} else "network_unavailable")
    if stage == "broker_open":
        assert selected["cause"] == "certificate_verification"


@pytest.mark.parametrize("affine", [True, False])
def test_leaf_requires_final_exception_identity_or_explicit_cause(published, monkeypatch, affine):
    service, binding = published
    value = request("call.ice_servers", profile=profile())
    leaf = TimeoutError("PRIVATE leaf")

    def ice():
        observer.note("caught", leaf, "broker_read")
        replacement = NetworkUnavailable("PRIVATE replacement")
        if affine:
            raise replacement from leaf
        raise replacement

    monkeypatch.setattr(service, "call_ice_servers", ice)
    sink = Sink()
    assert reply(exchange(value, binding, sink))["error"]["code"] == "internal"
    assert json.loads(sink.value)["stage"] == ("broker_read" if affine else "ice_service")


@pytest.mark.parametrize("replacement", ["bad_stage", "bad_category", "bad_cause", "bad_pair"])
def test_invalid_selected_literals_never_reach_sink(published, monkeypatch, replacement):
    service, binding = published
    handle = profile()
    monkeypatch.setattr(service, "call_ice_servers", fail_with(NetworkUnavailable("PRIVATE")))
    original = observer.Invocation.failure

    def tampered(self, error, code):
        original(self, error, code)
        if self.outcome is None:
            return
        token, stage, category, cause = self.outcome
        if replacement == "bad_stage":
            stage = "PRIVATE"
        elif replacement == "bad_category":
            category = "PRIVATE"
        elif replacement == "bad_cause":
            cause = "PRIVATE"
        else:
            category = "response_encoding"
        self.outcome = (token, stage, category, cause)

    monkeypatch.setattr(observer.Invocation, "failure", tampered)
    sink = Sink()
    assert reply(exchange(request("call.ice_servers", profile=handle), binding, sink))["error"]["code"] == "internal"
    assert sink.value is None
