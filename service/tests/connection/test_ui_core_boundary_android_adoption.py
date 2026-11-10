"""Instrumentation adapter injection is component proof, not JNI/path evidence."""

import ast
from dataclasses import replace
import inspect
import json
from pathlib import Path
import runpy
import socket
from threading import Event, Thread
from types import SimpleNamespace
import urllib.request

import pytest

from mesh_chat.connection.adapters.pairing import PairingAndReconnectExecutor
from mesh_chat.connection.composition import _NativeBindings
from mesh_chat.connection.model import Phase, Tick
from mesh_chat.connection.reducer import transition
from mesh_chat.errors import NativeUnavailable
from test_native_profile_lifecycle import profile_runtime
from test_pairing_runtime import SDP
from test_reconnect_adapter import Domain, initial


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    attempts = []
    def denied(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("Offline Android retirement control attempted external I/O")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", denied)
    yield
    assert not attempts


@pytest.fixture
def allocation(profile_runtime):
    create, host = profile_runtime
    service = create()
    service.create_profile("Synthetic retirement")
    created = []
    def offer(physical, *args):
        created.append(physical)
        return json.dumps({"ok": True, "sdp": SDP})
    host.createOffer, host.close = offer, lambda _: None
    logical = "manual-retirement"
    ice = {"iceServers": []}
    channels = [{"label": "mesh-reticulum", "binary": True, "ordered": True}]
    service.native_webrtc_offer(logical, ice, channels)
    return service, host, logical, service._native_resources.require(logical), ice, channels, created


@pytest.fixture
def instrumentation():
    path = Path(__file__).resolve().parents[3] / (
        "plugins/tauri-plugin-mesh-runtime/android/src/androidTest/assets/signal_mailbox_fixture.py")
    return runpy.run_path(str(path))


@pytest.mark.parametrize("wrapped", [False, True])
def test_instrumentation_synthetic_path_changes_actual_executed_port_and_native_adapter(instrumentation, wrapped):
    domain = Domain(True)
    state = initial()
    adapter = domain.executor(state)
    adapter.path = lambda _: {"has_path": True, "ready": False}
    executor = PairingAndReconnectExecutor(object(), adapter) if wrapped else adapter
    owner = SimpleNamespace(executor=executor)
    work = replace(transition(state, Tick(0)).effects[0], phase=Phase.PATH)
    assert executor.execute(work, Event()).pending is True
    selected, original = instrumentation["install_synthetic_manual_path"](owner)
    try:
        assert selected is adapter and executor.execute(work, Event()).pending is False
        assert instrumentation["reconnect_executor"](owner) is adapter
        # The startup-retention fixture uses this same selector for its delayed
        # native attachment. Verify the real work dispatcher reaches that port.
        port = selected.native
        calls = []
        selected.native = replace(port, attach=lambda resource: calls.append(resource))
        try:
            executor.execute(replace(work, phase=Phase.ATTACH), Event())
            assert calls == [work.resource.resource_id]
        finally:
            selected.native = port
        if wrapped:
            assert not hasattr(executor, "path") and not hasattr(executor, "native")
    finally:
        selected.path = original
    assert executor.execute(work, Event()).pending is True


def test_unknown_executor_shape_fails_instead_of_creating_unused_fixture_attributes(instrumentation):
    unknown = SimpleNamespace()
    with pytest.raises(AssertionError, match="Unexpected native reconnect adapter"):
        instrumentation["install_synthetic_manual_path"](SimpleNamespace(executor=unknown))
    assert not vars(unknown)


def manual_retirement_wait(instrumentation, service, logical, physical):
    """Exercise the actual post-Stop callback without unrelated JNI setup."""
    function, = ast.parse(inspect.getsource(instrumentation["run_manual_native_adoption"])).body
    block = next(statement for statement in function.body if isinstance(statement, ast.Try)).body
    stop = next(index for index, statement in enumerate(block)
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Attribute) and statement.value.func.attr == "reconnect_stop")
    call = block[stop + 1].value
    assert isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "wait_until"
    assert ast.literal_eval(call.args[2]) == 10
    environment = {**instrumentation, "service": service, "local_id": logical, "local_physical": physical}
    return eval(compile(ast.Expression(call.args[0]), "<actual-retirement-wait>", "eval"), environment)


def test_exact_retirement_wait_rejects_live_only_reuse_during_real_adapter_close(instrumentation, allocation):
    """Actual service/registry/close adapter, with native disposal explicitly gated."""
    service, host, logical, physical, ice, channels, created = allocation
    entered, release = Event(), Event()
    failures = []
    def close(resource):
        if resource == physical:
            entered.set()
            assert release.wait(3), "Bounded native disposal gate exceeded"
    host.close = close
    def retire():
        try:
            _NativeBindings(service).close(physical)
        except Exception as error:
            failures.append(type(error).__name__)
    worker = Thread(target=retire, daemon=True)
    worker.start()
    try:
        assert entered.wait(1)
        assert logical not in service._native_webrtc_live  # Original fixture already proceeds.
        assert logical not in service._native_webrtc_creating
        assert len(service._native_resources._logical) == 1 < service._native_resources._limit
        assert service._native_resources.current(logical, physical)
        with pytest.raises(NativeUnavailable, match="Native resource reservation unavailable"):
            service.native_webrtc_offer(logical, ice, channels)
        assert created == [physical]  # No replacement native allocation occurred.
        assert service._native_resources.current(logical, physical)
        predicate = manual_retirement_wait(instrumentation, service, logical, physical)
        assert not predicate()
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive() and failures == []
    assert predicate()
    service.native_webrtc_offer(logical, ice, channels)
    replacement = service._native_resources.require(logical)
    assert replacement != physical and created == [physical, replacement]
    service._handle_native_webrtc_event("closed", physical)
    assert service._native_resources.current(logical, replacement)
    assert logical in service._native_webrtc_live
    assert service.store.list("contact") == []
    assert not service._native_webrtc_profile_sessions


@pytest.mark.parametrize("state", [
    "live", "creating", "unconfirmed", "old_reverse_mapping", "replacement", "unrelated", "close_failure",
])
def test_exact_retirement_predicate_rejects_incomplete_or_foreign_cleanup_without_mutation(instrumentation, allocation, state):
    service, host, logical, physical, _, _, _ = allocation
    registry = service._native_resources
    if state in {"live", "creating", "old_reverse_mapping", "replacement"}:
        registry.release(logical, physical)
    if state != "live":
        service._native_webrtc_live.discard(logical)
    if state == "creating":
        service._native_webrtc_creating.add(logical)
    elif state == "old_reverse_mapping":
        registry.restore("foreign-owner", physical)
    elif state == "replacement":
        registry.reserve(logical)
    elif state == "unrelated":
        other = registry.reserve("unrelated")
        _NativeBindings(service).close(other)
    elif state == "close_failure":
        def failed(_):
            raise NativeUnavailable("Synthetic disposal failure")
        host.close = failed
        with pytest.raises(NativeUnavailable):
            _NativeBindings(service).close(physical)
        host.close = lambda _: None
    def facts():
        return (set(service._native_webrtc_live), set(service._native_webrtc_creating),
                dict(registry._logical), dict(registry._physical), set(registry._closed), registry._sequence)
    before = facts()
    try:
        assert not instrumentation["native_allocation_retired"](service, logical, physical)
        assert facts() == before
    finally:
        service._native_webrtc_creating.discard(logical)


def test_exact_retirement_query_acquires_dispatch_then_native_lock(instrumentation, allocation):
    service, _, logical, physical, _, _, _ = allocation
    observed = []
    class Lock:
        def __init__(self, name, lock): self.name, self.lock = name, lock
        def __enter__(self):
            self.lock.acquire()
            observed.append(self.name)
        def __exit__(self, *args): self.lock.release()
    dispatch, native = service._dispatch_lock, service._native_webrtc_lock
    try:
        service._dispatch_lock, service._native_webrtc_lock = Lock("dispatch", dispatch), Lock("native", native)
        assert not instrumentation["native_allocation_retired"](service, logical, physical)
        assert observed == ["dispatch", "native"]
    finally:
        service._dispatch_lock, service._native_webrtc_lock = dispatch, native


def test_retirement_wait_timeout_does_not_release_or_accept_pending_allocation(instrumentation, allocation):
    service, _, logical, physical, _, _, created = allocation
    with pytest.raises(AssertionError, match="Exact retirement still pending"):
        instrumentation["wait_until"](
            lambda: instrumentation["native_allocation_retired"](service, logical, physical),
            "Exact retirement still pending", 0.01)
    assert service._native_resources.current(logical, physical)
    assert created == [physical]
