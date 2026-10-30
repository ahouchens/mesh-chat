from dataclasses import replace
import io
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from mesh_chat.core_api.wire import FramedSession
from test_core_messages import host, client, enqueue, request


def frame(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


class Session:
    def __init__(self):
        self.requests = []
        self.closed = False
    def request(self, value):
        self.requests.append(value)
        return {"api_version": 1, "request_id": value.get("request_id"), "ok": True, "result": {"value": "hello"}}
    def detach(self): self.closed = True


def test_frame_roundtrip_keeps_unicode_and_correlation_without_dispatching_an_envelope():
    session = Session()
    wire = FramedSession(session)
    value = request("message.enqueue", profile="p" * 64, text="Hello 🌍\nSecond line")
    result = wire.exchange(frame(value))
    assert json.loads(result)["request_id"] == "request:1"
    assert result.endswith(b"\n") and result.count(b"\n") == 1
    assert session.requests == [value] and not session.closed


@pytest.mark.parametrize("raw", [
    b'{"operation":"runtime.capabilities","operation":"message.enqueue"}\n',
    b'{"params":{"text":"first","text":"second"}}\n',
    b'{"operation":"a","oper\\u0061tion":"b"}\n',
    b'{"value":NaN}\n', b'{"value":Infinity}\n', b'{"value":-Infinity}\n',
    b'{"value":1e9999}\n', b'{"value":9007199254740992}\n',
    b'{"value":"\\ud800"}\n', b'{"\\udfff":1}\n',
    b'\xff\n', b'\xef\xbb\xbf{}\n', b'{}', b'{}\n{}\n', b'{} garbage\n', b'\n',
    b'[' * 17 + b']' * 17 + b'\n', b'[' + b'0,' * 1024 + b'0]\n',
])
def test_ambiguous_or_unbounded_frames_close_without_dispatch(raw):
    session = Session()
    wire = FramedSession(session)
    result = json.loads(wire.exchange(raw))
    assert result["error"]["code"] == "invalid_request" and result["request_id"] is None
    assert not session.requests and session.closed
    assert json.loads(wire.exchange(frame(request("runtime.capabilities"))))["error"]["code"] == "unauthenticated"


def test_frame_limit_includes_delimiter_and_overflow_closes_before_dispatch():
    from mesh_chat.core_api.limits import MAX_FRAME_BYTES
    session = Session()
    wire = FramedSession(session)
    body = frame(request("runtime.capabilities"))[:-1]
    exact = body + b" " * (MAX_FRAME_BYTES - len(body) - 1) + b"\n"
    assert json.loads(wire.exchange(exact))["ok"]
    assert json.loads(wire.exchange(exact[:-1] + b" \n"))["error"]["code"] == "invalid_request"
    assert len(session.requests) == 1 and session.closed


def test_brackets_and_commas_inside_strings_do_not_consume_structure_budget():
    session = Session()
    wire = FramedSession(session)
    value = request("message.enqueue", text='[' * 2048 + ',:{\\"' * 2048 + '🌍')
    assert json.loads(wire.exchange(frame(value)))["ok"]
    assert session.requests == [value]


def test_crlf_is_accepted_without_permitting_multiline_json():
    session = Session()
    wire = FramedSession(session)
    assert json.loads(wire.exchange(frame(request("runtime.capabilities"))[:-1] + b"\r\n"))["ok"]
    assert json.loads(wire.exchange(b'{\n"operation":"runtime.capabilities"}\n'))["error"]["code"] == "invalid_request"


def test_stream_reads_are_bounded_and_eof_detaches():
    from mesh_chat.core_api.limits import MAX_FRAME_BYTES
    session = Session()
    class Reader(io.BytesIO):
        def readline(self, size=-1):
            assert size == MAX_FRAME_BYTES + 1
            return super().readline(size)
    output = io.BytesIO()
    FramedSession(session).serve(Reader(frame(request("runtime.capabilities")) * 2), output)
    assert len(session.requests) == 2 and len(output.getvalue().splitlines()) == 2
    assert session.closed


def test_partial_frame_at_eof_is_never_dispatched():
    session = Session()
    output = io.BytesIO()
    FramedSession(session).serve(io.BytesIO(frame(request("runtime.capabilities"))[:-1]), output)
    assert json.loads(output.getvalue())["error"]["code"] == "invalid_request"
    assert session.closed and not session.requests


def test_malformed_frame_cannot_smuggle_a_later_command_on_the_same_stream():
    session = Session()
    output = io.BytesIO()
    FramedSession(session).serve(io.BytesIO(b'{"bad":NaN}\n' + frame(request("runtime.capabilities"))), output)
    assert len(output.getvalue().splitlines()) == 1
    assert session.closed and not session.requests


def test_short_writes_finish_one_response_before_reading_the_next_request():
    session = Session()
    class Writer(io.BytesIO):
        def write(self, value): return super().write(value[:3])
    output = Writer()
    FramedSession(session).serve(io.BytesIO(frame(request("runtime.capabilities")) * 2), output)
    assert len(output.getvalue().splitlines()) == 2
    assert all(json.loads(line)["ok"] for line in output.getvalue().splitlines())


@pytest.mark.parametrize("count", [0, None, -1, True, 10**9])
def test_failed_output_does_not_dispatch_another_request(count):
    session = Session()
    class Writer:
        def write(self, _): return count
        def flush(self): pass
    with pytest.raises(OSError):
        FramedSession(session).serve(io.BytesIO(frame(request("runtime.capabilities")) * 2), Writer())
    assert len(session.requests) == 1 and session.closed


def test_lost_enqueue_reply_is_recovered_by_the_same_key_without_reexecution(host):
    service = host()
    session, _, profile, peer = client(service)
    value = request("message.enqueue", profile=profile, recipient=peer, kind="text", text="Hello")
    value["idempotency_key"] = "enqueue-key-0001"
    class BrokenWriter:
        def write(self, _): raise BrokenPipeError("reply lost")
    with pytest.raises(BrokenPipeError):
        FramedSession(session).serve(io.BytesIO(frame(value)), BrokenWriter())
    assert len(service.store.list("message")) == 1
    again, _, _, _ = client(service)
    assert enqueue(again, profile, peer)["ok"]
    assert len(service.store.list("message")) == 1
    assert session.request(request("runtime.capabilities"))["error"]["code"] == "unauthenticated"


def test_current_grants_are_rechecked_for_each_framed_request(host):
    service = host()
    session, grants, profile, peer = client(service)
    wire = FramedSession(session)
    grants[0] = replace(grants[0], permissions=frozenset({"observe"}))
    value = request("message.enqueue", profile=profile, recipient=peer, kind="text", text="Hello")
    value["idempotency_key"] = "enqueue-key-0001"
    assert json.loads(wire.exchange(frame(value)))["error"]["code"] == "forbidden"
    assert not service.store.list("message")
    assert json.loads(wire.exchange(frame(request("runtime.capabilities"))))["ok"]


def test_client_fields_cannot_select_a_host_identity_or_private_command(host):
    service = host()
    session, _, _, _ = client(service)
    wire = FramedSession(session)
    value = request("runtime.capabilities")
    value["caller"] = "privileged-host"
    assert json.loads(wire.exchange(frame(value)))["error"]["code"] == "invalid_request"
    assert json.loads(wire.exchange(frame(request("native_webrtc_event"))))["error"]["code"] == "unsupported_operation"


def test_array_is_not_an_implicit_batch_of_mutations(host):
    service = host()
    session, _, _, _ = client(service)
    result = json.loads(FramedSession(session).exchange(frame([request("runtime.capabilities")])))
    assert result["error"]["code"] == "invalid_request"
    assert not service.store.list("message")


def test_transport_errors_follow_the_bounded_error_contract():
    result = json.loads(FramedSession(Session()).exchange(b'\xff\n'))
    root = Path(__file__).resolve().parents[3] / "contracts" / "core-api"
    Draft202012Validator(json.loads((root / "error-v1.schema.json").read_text())).validate(result)


@pytest.mark.parametrize("fault", ["read", "flush"])
def test_stream_faults_detach_without_dispatching_a_later_request(fault):
    session = Session()
    class Reader(io.BytesIO):
        def readline(self, size):
            if fault == "read": raise OSError("private stream path")
            return super().readline(size)
    class Writer(io.BytesIO):
        def flush(self): raise OSError("private stream path")
    with pytest.raises(OSError):
        FramedSession(session).serve(Reader(frame(request("runtime.capabilities")) * 2), Writer())
    assert session.closed
    assert len(session.requests) == (0 if fault == "read" else 1)


@pytest.mark.parametrize("value", [float("nan"), object(), "private" * 700000],
                         ids=["nonfinite", "unsupported_type", "oversized"])
def test_invalid_or_oversized_session_responses_close_with_a_selected_error(value):
    session = Session()
    session.request = lambda _: {"private": value}
    result = json.loads(FramedSession(session).exchange(frame(request("runtime.capabilities"))))
    assert result == {"api_version": 1, "request_id": "request:1", "ok": False,
                      "error": {"code": "internal", "retry_after_ms": None}}
    assert session.closed


def test_session_exception_does_not_export_its_details():
    session = Session()
    def fail(_): raise RuntimeError("private identity and key")
    session.request = fail
    wire = FramedSession(session)
    result = wire.exchange(frame(request("runtime.capabilities")))
    assert json.loads(result)["error"]["code"] == "internal"
    assert b"private" not in result and session.closed


def test_host_binding_keeps_blocking_io_outside_the_service_lock(host):
    from mesh_chat.core_api.composition import bind_service_stream
    service = host()
    _, grants, profile, _ = client(service)
    wire = bind_service_stream(service, lambda: grants[0])
    class Reader(io.BytesIO):
        def readline(self, size):
            assert not service._dispatch_lock._is_owned()
            return super().readline(size)
    class Writer(io.BytesIO):
        def write(self, value):
            assert not service._dispatch_lock._is_owned()
            return super().write(value)
        def flush(self): assert not service._dispatch_lock._is_owned()
    output = Writer()
    wire.serve(Reader(frame(request("runtime.capabilities")) + frame(request("profile.query", profile=profile))), output)
    assert all(json.loads(line)["ok"] for line in output.getvalue().splitlines())
    assert "bind_service_stream" not in service.COMMANDS


def test_response_backpressure_prevents_dispatch_of_another_command():
    session = Session()
    class Writer(io.BytesIO):
        def write(self, value):
            assert len(session.requests) == 1
            raise BrokenPipeError("blocked response")
    with pytest.raises(BrokenPipeError):
        FramedSession(session).serve(io.BytesIO(frame(request("runtime.capabilities")) * 2), Writer())
    assert len(session.requests) == 1


def test_valid_escaped_surrogate_pair_decodes_to_one_unicode_scalar():
    session = Session()
    result = FramedSession(session).exchange(b'{"request_id":"request:1","text":"\\ud83c\\udf0d"}\n')
    assert json.loads(result)["ok"]
    assert session.requests[0]["text"] == "🌍"
