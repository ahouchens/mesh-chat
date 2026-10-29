from __future__ import annotations

import io
import json
import queue
from types import SimpleNamespace

import pytest

from mesh_chat.crash_diagnostics import PREFIX, failure_record, report_failure
from mesh_chat.direct_native import NativeChannel, NativeFrameReader
from mesh_chat.ipc import encode_frame


def test_queue_overflow_reports_capacity_and_source_without_request_data(capsys):
    secret = "PRIVATE-MESSAGE-TURN-PASSWORD"
    stream = io.BytesIO(encode_frame({"command": "webrtc_packet", "payload": {"data": secret}}) * 9)
    reader = NativeFrameReader(stream, NativeChannel())
    reader._thread.join(2)
    with pytest.raises(queue.Full) as error:
        reader.read()
    report_failure("read_command", error.value, "webrtc_packet", reader)
    raw = capsys.readouterr().err
    assert secret not in raw
    value = json.loads(raw.removeprefix(PREFIX))
    assert value["category"] == "command_queue_full"
    assert value["pending_commands"] == value["queue_capacity"] == 8
    assert any(frame["module"] == "direct_native" for frame in value["frames"])
    assert all(set(frame) == {"module", "line"} for frame in value["frames"])
    reader.close()


@pytest.mark.parametrize("error,category", [(MemoryError("secret"), "out_of_memory"),
                                          (BrokenPipeError("secret"), "broken_pipe"),
                                          (RuntimeError("secret"), "runtime_error")])
def test_failure_categories_never_export_exception_text(error, category):
    record = failure_record("secret-stage", error, "secret-command")
    assert record["category"] == category
    assert record["stage"] == "unknown"
    assert record["last_command"] == "other"
    assert "secret" not in json.dumps(record)


def test_fatal_main_error_retains_exit_three_and_records_failure_stage(monkeypatch, capsys):
    from mesh_chat import __main__ as main
    import threading
    previous = threading.excepthook
    closed = []
    class Reader:
        def __init__(self, *_args):
            self._requests = queue.Queue(maxsize=8)
        def read(self):
            raise queue.Full("sensitive payload")
        def close(self):
            closed.append("reader")
    fake = SimpleNamespace(_direct_native=None, snapshot=lambda: {}, close=lambda: closed.append("service"))
    monkeypatch.setattr(main, "NativeFrameReader", Reader)
    monkeypatch.setattr(main, "_initialize", lambda *_args: fake)
    monkeypatch.setattr(main.sys, "argv", ["mesh-chat-service"])
    monkeypatch.setattr(main.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(encode_frame({"v": 1, "id": "secret", "command": "initialize"}))))
    monkeypatch.setattr(main.sys, "stdout", SimpleNamespace(buffer=io.BytesIO()))
    assert main.main() == 3
    raw = capsys.readouterr().err
    assert "sensitive" not in raw and "secret" not in raw
    assert json.loads(raw.removeprefix(PREFIX))["stage"] == "read_command"
    assert closed == ["reader", "service"]
    assert threading.excepthook is previous
