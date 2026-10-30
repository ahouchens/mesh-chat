import pytest

from mesh_chat.errors import NativeUnavailable
from mesh_chat.native_resource_registry import NativeResourceRegistry


def test_reused_logical_handle_has_new_native_identity_and_old_callbacks_are_orphans():
    registry = NativeResourceRegistry()
    first = registry.reserve("ui-session")
    assert registry.resolve(first) == "ui-session"
    registry.release("ui-session", first)
    second = registry.reserve("ui-session")
    assert first != second
    assert registry.resolve(first) is None
    assert not registry.release("ui-session", first)
    assert registry.physical("ui-session") == second


def test_reservations_are_bounded_and_cannot_replace_live_native_handles():
    registry = NativeResourceRegistry(limit=1)
    first = registry.reserve("one")
    with pytest.raises(NativeUnavailable):
        registry.reserve("one")
    with pytest.raises(NativeUnavailable):
        registry.reserve("two")
    assert registry.physical("one") == first
    assert registry.resolve("one") is None
    assert registry.release("one", first)
    assert registry.reserve("two") != first
