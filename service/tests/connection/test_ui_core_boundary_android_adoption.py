"""Instrumentation adapter injection is component proof, not JNI/path evidence."""

from dataclasses import replace
from pathlib import Path
import runpy
from threading import Event
from types import SimpleNamespace

import pytest

from mesh_chat.connection.adapters.pairing import PairingAndReconnectExecutor
from mesh_chat.connection.model import Phase, Tick
from mesh_chat.connection.reducer import transition
from test_reconnect_adapter import Domain, initial


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
