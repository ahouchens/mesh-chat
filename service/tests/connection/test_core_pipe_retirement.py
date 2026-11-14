"""Portable custody regressions for the Windows pipe worker boundary."""

import ctypes
import io
from threading import Event, Lock, Thread
from types import SimpleNamespace

import pytest

import mesh_chat.__main__ as service_main
from mesh_chat.core_api import pipe_endpoint as pipe


class Kernel:
    def __init__(self):
        self.calls = []
        self.close_failures = 0

    def CancelIoEx(self, handle, _overlapped):
        self.calls.append(("cancel", handle))
        return True

    def DisconnectNamedPipe(self, handle):
        self.calls.append(("disconnect", handle))
        return True

    def CloseHandle(self, handle):
        self.calls.append(("close", handle))
        if self.close_failures:
            self.close_failures -= 1
            return False
        return True


class Worker:
    def __init__(self, alive=True):
        self.alive = alive
        self.budgets = []

    def join(self, timeout):
        self.budgets.append(timeout)

    def is_alive(self):
        return self.alive


def endpoint(kernel, handles=(71,), workers=()):
    value = object.__new__(pipe.PipeEndpoint)
    value.kernel = kernel
    value._stop = Event()
    value._lock = Lock()
    value._handles = set(handles)
    value._query_handles = set()
    value._admissions = set()
    value._threads = list(workers)
    value.failure = None
    return value


def test_live_worker_retains_exact_pipe_handle_until_later_positive_join(monkeypatch):
    kernel = Kernel()
    worker = Worker()
    server = endpoint(kernel, workers=(worker,))
    clock = iter((0.0, 0.1, 0.2, 10.0, 10.1, 10.2))
    monkeypatch.setattr(pipe, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    with pytest.raises(pipe.PipeRetirementPending):
        server.close()
    assert server._handles == {71}
    assert ("close", 71) not in kernel.calls
    assert worker.budgets == [pytest.approx(4.9)]
    worker.alive = False
    server.close()
    assert server._handles == set()
    assert kernel.calls.count(("close", 71)) == 1


def test_all_workers_share_one_join_budget(monkeypatch):
    kernel = Kernel()
    first, second = Worker(), Worker()
    server = endpoint(kernel, workers=(first, second))
    clock = iter((0.0, 2.0, 6.0))
    monkeypatch.setattr(pipe, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    with pytest.raises(pipe.PipeRetirementPending):
        server.close()
    assert first.budgets == [3.0]
    assert second.budgets == [0.0]
    assert server._handles == {71} and ("close", 71) not in kernel.calls


def test_failed_close_retains_exact_handle_and_retries_without_double_close():
    kernel = Kernel()
    kernel.close_failures = 1
    server = endpoint(kernel)
    with pytest.raises(pipe.PipeRetirementPending):
        server.close()
    assert server._handles == {71}
    server.close()
    assert server._handles == set()
    assert kernel.calls.count(("close", 71)) == 2
    server.close()
    assert kernel.calls.count(("close", 71)) == 2


def test_process_query_handle_and_admission_release_require_positive_retry():
    kernel = Kernel()
    kernel.close_failures = 1
    server = endpoint(kernel, handles=())
    server._query_handles.add(83)
    attempts = []
    def release():
        attempts.append(True)
        if len(attempts) == 1:
            raise OSError("pending")
    admission = pipe.PipeClientAdmission(lambda: True, release)
    server._admissions.add(admission)
    with pytest.raises(pipe.PipeRetirementPending):
        server.close()
    assert server._query_handles == {83} and server._admissions == {admission}
    server.close()
    assert server._query_handles == server._admissions == set()
    assert len(attempts) == 2 and kernel.calls.count(("close", 83)) == 2


def test_preface_reader_enforces_absolute_deadline_and_exact_line_ceiling(monkeypatch):
    stream = pipe._Duplex(Kernel(), 71, Event(), 300)
    stream._read = lambda _size, *, deadline: b"x" * 79 + b"\n"
    with pytest.raises(ValueError, match="ceiling"):
        stream.readline(79, deadline=10**12)
    stream = pipe._Duplex(Kernel(), 71, Event(), 300)
    stream._read = lambda _size, *, deadline: b"x"
    ticks = iter((0.0, 0.1, 2.0))
    monkeypatch.setattr(pipe, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    with pytest.raises(TimeoutError):
        stream.readline(79, deadline=1.0)


def test_worker_preserves_primary_serve_failure_when_handle_close_fails(monkeypatch):
    kernel = Kernel()
    kernel.close_failures = 1
    server = endpoint(kernel)
    monkeypatch.setattr(server, "_connect", lambda _: (_ for _ in ()).throw(OSError("primary read")))
    server._serve_client(SimpleNamespace(), 71)
    assert "primary read" in server.failure
    assert server._handles == {71}
    server.close()
    assert server._handles == set() and kernel.calls.count(("close", 71)) == 2


def test_unexpected_serve_error_is_not_suppressed_by_failed_handle_close(monkeypatch):
    kernel = Kernel()
    kernel.close_failures = 1
    server = endpoint(kernel)
    monkeypatch.setattr(server, "_connect", lambda _: (_ for _ in ()).throw(RuntimeError("primary")))
    with pytest.raises(RuntimeError, match="primary"):
        server._serve_client(SimpleNamespace(), 71)
    assert server._handles == {71}
    server.close()
    assert server._handles == set()


def test_canceled_read_waits_for_overlapped_completion_before_event_close(monkeypatch):
    calls = []
    class ReadKernel(Kernel):
        def CreateEventW(self, *_): return 81
        def ReadFile(self, *_): calls.append("read"); return False
        def WaitForSingleObject(self, *_): calls.append("wait"); return pipe.WAIT_TIMEOUT
        def CancelIoEx(self, *_): calls.append("cancel"); return True
        def GetOverlappedResult(self, _handle, _overlapped, _read, wait):
            calls.append(("completion", wait)); return False
        def CloseHandle(self, handle): calls.append(("close", handle)); return True
    stop = Event()
    stop.set()
    monkeypatch.setattr(ctypes, "get_last_error", lambda: pipe.ERROR_IO_PENDING)
    stream = pipe._Duplex(ReadKernel(), 71, stop, 30)
    assert stream._read(1) == b""
    assert calls == ["read", "wait", "cancel", ("completion", True), ("close", 81)]


@pytest.mark.parametrize("operation", ["read", "write", "connect"])
def test_cancel_return_does_not_release_pending_operation_or_handle(monkeypatch, operation):
    canceled, completed = Event(), Event()
    calls = []
    class PendingKernel(Kernel):
        def CreateEventW(self, *_): return 81
        def ReadFile(self, *_): return False
        def WriteFile(self, *_): return False
        def ConnectNamedPipe(self, *_): return False
        def WaitForSingleObject(self, *_): return pipe.WAIT_TIMEOUT
        def CancelIoEx(self, *_): calls.append("cancel"); canceled.set(); return True
        def GetOverlappedResult(self, _handle, _overlapped, _read, wait):
            assert wait is True
            calls.append("completion_start")
            assert completed.wait(2)
            calls.append("completion_end")
            return False
        def CloseHandle(self, handle): calls.append(("close", handle)); return True
    kernel = PendingKernel()
    monkeypatch.setattr(ctypes, "get_last_error", lambda: pipe.ERROR_IO_PENDING)
    stop = Event()
    stop.set()
    server = endpoint(kernel)
    server._stop.set()
    stream = pipe._Duplex(kernel, 71, stop, 30)
    outcome = []
    def run():
        try:
            outcome.append({"read": lambda: stream._read(1),
                            "write": lambda: stream.write(b"x"),
                            "connect": lambda: server._connect(71)}[operation]())
        except OSError:
            outcome.append("canceled")
    worker = Thread(target=run)
    worker.start()
    try:
        assert canceled.wait(2)
        assert worker.is_alive() and ("close", 81) not in calls
        server._threads = [worker]
        monkeypatch.setattr(pipe, "RETIRE_JOIN_SECONDS", 0.01)
        with pytest.raises(pipe.PipeRetirementPending):
            server.close()
        assert server._handles == {71} and ("close", 71) not in calls
    finally:
        completed.set()
        worker.join(2)
    assert not worker.is_alive()
    assert calls.index("completion_end") < calls.index(("close", 81))
    server.close()
    assert server._handles == set() and ("close", 71) in calls
    assert outcome == ([b""] if operation == "read" else ["canceled"])


@pytest.mark.parametrize("operation", ["read", "write", "connect"])
def test_failed_wait_cancels_and_completes_before_event_close(monkeypatch, operation):
    calls = []
    class FailedWaitKernel(Kernel):
        def CreateEventW(self, *_): return 81
        def ReadFile(self, *_): return False
        def WriteFile(self, *_): return False
        def ConnectNamedPipe(self, *_): return False
        def WaitForSingleObject(self, *_): return pipe.WAIT_FAILED
        def CancelIoEx(self, *_): calls.append("cancel"); return True
        def GetOverlappedResult(self, _handle, _overlapped, _read, wait):
            calls.append(("completion", wait)); return False
        def CloseHandle(self, handle): calls.append(("close", handle)); return True
    kernel = FailedWaitKernel()
    monkeypatch.setattr(ctypes, "get_last_error", lambda: pipe.ERROR_IO_PENDING)
    stream = pipe._Duplex(kernel, 71, Event(), 30)
    server = endpoint(kernel)
    with pytest.raises(OSError):
        {"read": lambda: stream._read(1),
         "write": lambda: stream.write(b"x"),
         "connect": lambda: server._connect(71)}[operation]()
    assert calls == ["cancel", ("completion", True), ("close", 81)]


@pytest.mark.parametrize("primary_error,expected_status", [(False, 0), (True, 3)])
def test_main_retries_pending_pipe_before_dependent_shutdown_and_preserves_primary(
    monkeypatch, primary_error, expected_status
) -> None:
    events = []
    original_hook = service_main.threading.excepthook
    initial = {"v": 1, "id": "start", "command": "initialize", "payload": {}}
    service = SimpleNamespace(_direct_native=None, snapshot=lambda: {},
                              close=lambda: events.append("service"))
    class Endpoint:
        calls = 0
        def close(self):
            self.calls += 1
            events.append("endpoint")
            if self.calls == 1:
                raise pipe.PipeRetirementPending("worker still active")
    endpoint = Endpoint()
    class Reader:
        def __init__(self, *_args, **_kwargs): pass
        def read(self):
            if primary_error:
                raise OSError("primary command failure")
            raise EOFError()
        def close(self): events.append("reader")
    monkeypatch.setattr(service_main.sys, "argv", ["mesh-chat-service"])
    monkeypatch.setattr(service_main.sys, "stdin", SimpleNamespace(buffer=io.BytesIO()))
    monkeypatch.setattr(service_main.sys, "stdout", SimpleNamespace(buffer=io.BytesIO()))
    monkeypatch.setattr(service_main, "interruptible_input", lambda value: value)
    monkeypatch.setattr(service_main, "FrameWriter", lambda _: SimpleNamespace(write=lambda value: None))
    monkeypatch.setattr(service_main, "read_frame", lambda _: initial)
    monkeypatch.setattr(service_main, "_initialize", lambda *_: service)
    monkeypatch.setattr(service_main, "_start_core_api_endpoint", lambda _: endpoint)
    monkeypatch.setattr(service_main, "NativeFrameReader", Reader)
    monkeypatch.setattr(service_main, "report_failure", lambda stage, error, *_:
                        events.append((stage, str(error))))
    monkeypatch.setattr(service_main.time, "sleep", lambda _: events.append("backoff"))
    assert service_main.main() == expected_status
    assert endpoint.calls == 2
    assert events[-3:] == ["endpoint", "reader", "service"]
    assert events.index("service") > events.index("reader")
    assert ("shutdown", "worker still active") in events
    if primary_error:
        assert events[0] == ("read_command", "primary command failure")
    assert service_main.threading.excepthook is original_hook
