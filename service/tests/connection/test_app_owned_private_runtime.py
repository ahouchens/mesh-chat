"""Opt-in owner control and positive retirement without a Windows kernel dependency."""

import io
from threading import RLock
from types import SimpleNamespace
import time

import pytest

from mesh_chat import app_owned_host as host
from mesh_chat.app_owned_admission import ProcessIdentity
from mesh_chat.app_owned_control import encode_helper_preface
from mesh_chat.core_api.pipe_endpoint import PipeRetirementPending


IMAGE = r"C:\App\node.exe"
PIPE = r"\\.\pipe\mesh-chat-private-test"


class Reader:
    def __init__(self, data):
        self.stream = io.BytesIO(data)
        self.cancelled = False

    def read(self, size):
        return self.stream.read(size)

    def cancel(self):
        self.cancelled = True


class Handle:
    def __init__(self, identity, events):
        self.identity = identity
        self.events = events
        self.closed = False

    def is_alive(self):
        return not self.closed

    def close(self):
        assert not self.closed
        self.events.append(f"pin:{self.identity.pid}")
        self.closed = True


class Port:
    def __init__(self, events):
        self.events = events
        self.identities = {41: ProcessIdentity(41, 100, IMAGE),
                           42: ProcessIdentity(42, 200, IMAGE)}
        self.handles = []

    def open(self, pid):
        handle = Handle(self.identities[pid], self.events)
        self.handles.append(handle)
        return handle

    def retire(self):
        self.events.append("port")
        return True


class Endpoint:
    def __init__(self, name, options, *, admit_client):
        self.name, self.options, self.admit_client = name, options, admit_client
        self.events = None
        self.fail_close = False

    def start(self, service):
        self.service = service

    def close(self):
        self.events.append("endpoint")
        if self.fail_close:
            self.fail_close = False
            raise PipeRetirementPending("worker still owns the pipe")


class Watcher:
    def __init__(self, owner, reader):
        self.owner, self.reader = owner, reader
        self.events = None

    def retire(self):
        self.events.append("watcher")
        assert not self.owner.closed
        return True


class Service:
    def __init__(self, store, events, *, dispatch_lock=True):
        self.store = store
        self.events = events
        if dispatch_lock:
            self._dispatch_lock = RLock()
        self._store_closed = False

    def close(self):
        self.events.append("service")
        self.store.close()
        self._store_closed = True


def private_runtime(tmp_path, reader, events, *, dispatch_lock=True):
    port = Port(events)
    created = []
    class Store:
        def get(self, *_): return {"disabled": True}
        def close(self): events.append("store")
    def endpoint(name, options, *, admit_client):
        value = Endpoint(name, options, admit_client=admit_client)
        value.events = events
        created.append(value)
        return value
    def watcher(owner, input_stream):
        value = Watcher(owner, input_stream)
        value.events = events
        return value
    def runtime(config, *, private_input):
        assert config.private_admission and private_input is reader
        value = host.AppOwnedRuntime(config, private_input=private_input,
            key_loader=lambda _: b"k" * 32, store_factory=lambda *_: Store(),
            service_factory=lambda store, *_args, **_kwargs: Service(store, events,
                dispatch_lock=dispatch_lock),
            host_factory=lambda _: SimpleNamespace(shutdown=lambda: events.append("native")),
            endpoint_factory=endpoint, process_port_factory=lambda: port,
            watcher_factory=watcher)
        created.append(value)
        return value
    environment = {"MESH_CHAT_APP_DATA_DIRECTORY": str(tmp_path),
        "MESH_CHAT_CORE_API_PIPE": PIPE, "MESH_CHAT_CORE_API_CLIENT_IMAGE": IMAGE,
        "MESH_CHAT_APP_PARENT_PID": "41", "MESH_CHAT_APP_PRIVATE_HELPER_ADMISSION": "1"}
    return runtime, created, port, environment


def test_private_control_registers_exact_helper_then_removes_before_retirement(tmp_path, monkeypatch):
    monkeypatch.setattr(host, "_require_windows", lambda: None)
    reader = Reader(b"REGISTER/1 00000001 42\nREMOVE/1 00000002 42\n")
    events, messages, accepted = [], [], []
    factory, created, port, environment = private_runtime(tmp_path, reader, events)
    def publish(value):
        messages.append(value)
        if value["type"] == "helper_registered":
            runtime = created[-1]
            line = encode_helper_preface(value["invitation"])
            stream = SimpleNamespace(readline=lambda limit, *, deadline: line)
            lease = runtime.pipe_admission(42, stream)
            assert lease is not None and lease.authorize()
            accepted.append(lease)
        if value["type"] == "helper_removed":
            assert not accepted[0].authorize()
    assert host.run(reader, SimpleNamespace(write=publish), watch_parent=lambda _: pytest.fail("legacy watcher"),
                    environment=environment, runtime_factory=factory) == 0
    assert [message["type"] for message in messages] == [
        "runtime_started", "helper_registered", "helper_removed", "runtime_stopped"]
    assert messages[1]["sequence"] == "00000001" and set(messages[1]) == {
        "v", "type", "sequence", "invitation"}
    assert messages[2] == {"v": 1, "type": "helper_removed", "sequence": "00000002"}
    assert events.index("endpoint") < events.index("watcher") < events.index("pin:41")
    assert events.index("pin:41") < events.index("service")
    assert all(handle.closed for handle in port.handles)


@pytest.mark.parametrize("data", [b"REGISTER/1 00000001 42", b"X" * 41 + b"\n",
    b"REGISTER/1 FFFFFFFF 42\n", b"REGISTER/1 00000001 0\n"])
def test_bad_private_control_has_no_ack_and_retires(tmp_path, monkeypatch, data):
    monkeypatch.setattr(host, "_require_windows", lambda: None)
    reader = Reader(data)
    events, messages = [], []
    factory, created, port, environment = private_runtime(tmp_path, reader, events)
    assert host.run(reader, SimpleNamespace(write=messages.append), watch_parent=lambda _: None,
                    environment=environment, runtime_factory=factory) == 2
    assert [value["type"] for value in messages] == [
        "runtime_started", "runtime_failed", "runtime_stopped"]
    assert all(handle.closed for handle in port.handles)


def test_endpoint_pending_keeps_watcher_and_owner_pin_until_retry(tmp_path):
    reader = Reader(b"")
    events = []
    factory, created, port, environment = private_runtime(tmp_path, reader, events)
    config = host.AppOwnedConfig.from_environment(environment)
    runtime = factory(config, private_input=reader)
    endpoint = runtime.endpoint
    endpoint.fail_close = True
    with pytest.raises(PipeRetirementPending):
        runtime.close()
    assert events == ["endpoint"]
    assert runtime.endpoint is endpoint and not port.handles[0].closed
    assert runtime.admission.candidate_role(port.handles[0].identity) is None
    assert runtime.close()
    assert events.index("endpoint") < events.index("watcher") < events.index("pin:41")


def test_private_owner_watch_cancels_input_on_exact_owner_exit_then_joins():
    events = []
    owner = Handle(ProcessIdentity(41, 100, IMAGE), events)
    reader = Reader(b"")
    watcher = host._PrivateOwnerWatcher(owner, reader)
    try:
        owner.closed = True  # The pinned process object now reports exit.
        deadline = time.monotonic() + 1
        while not reader.cancelled and time.monotonic() < deadline:
            time.sleep(.01)
        assert reader.cancelled
    finally:
        assert watcher.retire() is True


def test_owner_control_rejects_last_byte_crossing_its_deadline(monkeypatch):
    ticks = iter((0.0, 1.0, 6.0))
    monkeypatch.setattr(host, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    with pytest.raises(host.ValidationError, match="deadline"):
        host._owner_control_line(Reader(b"REGISTER/1 00000001 42\n"))


def test_rejected_owner_pin_stays_with_failed_startup_until_cleanup(tmp_path):
    reader = Reader(b"")
    events = []
    factory, created, port, environment = private_runtime(tmp_path, reader, events)
    port.identities[41] = ProcessIdentity(41, 100, r"C:\Other\node.exe")
    config = host.AppOwnedConfig.from_environment(environment)
    with pytest.raises(host.AppOwnedStartupIncomplete) as failure:
        factory(config, private_input=reader)
    runtime = failure.value.runtime
    assert len(port.handles) == 1 and not port.handles[0].closed
    assert runtime.close() is True
    assert port.handles[0].closed and events.index("pin:41") < events.index("service")


@pytest.mark.parametrize("failed_type", ["runtime_started", "helper_registered"])
def test_private_required_write_failure_retires_without_reporting_success(
        tmp_path, monkeypatch, failed_type):
    monkeypatch.setattr(host, "_require_windows", lambda: None)
    reader = Reader(b"REGISTER/1 00000001 42\n")
    events, messages = [], []
    factory, created, port, environment = private_runtime(tmp_path, reader, events)
    def write(value):
        if value["type"] == failed_type:
            raise OSError("status pipe unavailable")
        messages.append(value)
    assert host.run(reader, SimpleNamespace(write=write), watch_parent=lambda _: None,
                    environment=environment, runtime_factory=factory) == 2
    assert [value["type"] for value in messages] == (
        ["runtime_failed", "runtime_stopped"] if failed_type == "runtime_started"
        else ["runtime_started", "runtime_failed", "runtime_stopped"])
    assert all(handle.closed for handle in port.handles)
    assert events.index("endpoint") < events.index("watcher") < events.index("pin:41")


def test_missing_private_dispatch_lock_fails_before_process_pin_and_cleans_up(tmp_path):
    reader = Reader(b"")
    events = []
    factory, created, port, environment = private_runtime(
        tmp_path, reader, events, dispatch_lock=False)
    config = host.AppOwnedConfig.from_environment(environment)
    with pytest.raises(host.AppOwnedStartupIncomplete) as failure:
        factory(config, private_input=reader)
    assert port.handles == []
    assert failure.value.runtime.close() is True
    assert "service" in events and "native" in events


@pytest.mark.parametrize("value", ["true", "", "2", True, 1])
def test_private_selector_requires_exact_trusted_environment_value(tmp_path, value):
    environment = {"MESH_CHAT_APP_DATA_DIRECTORY": str(tmp_path),
        "MESH_CHAT_CORE_API_PIPE": PIPE, "MESH_CHAT_CORE_API_CLIENT_IMAGE": IMAGE,
        "MESH_CHAT_APP_PARENT_PID": "41", "MESH_CHAT_APP_PRIVATE_HELPER_ADMISSION": value}
    with pytest.raises(host.ValidationError):
        host.AppOwnedConfig.from_environment(environment)
