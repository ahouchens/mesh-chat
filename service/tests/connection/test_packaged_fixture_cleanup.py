from types import SimpleNamespace

import pytest

from tools.connection_harness.packaged_transport_probe import cleanup_directory


def test_cleanup_waits_for_exiting_windows_handles():
    calls = []
    def cleanup():
        calls.append(True)
        if len(calls) < 3: raise PermissionError("Exited process still releasing handles")
    now = [0.0]
    cleanup_directory(SimpleNamespace(cleanup=cleanup), clock=lambda: now[0], pause=lambda value: now.__setitem__(0, now[0] + value))
    assert len(calls) == 3


def test_persistent_cleanup_failure_still_fails_qualification():
    def cleanup(): raise PermissionError("Handle remains open")
    now = [0.0]
    with pytest.raises(PermissionError):
        cleanup_directory(SimpleNamespace(cleanup=cleanup), clock=lambda: now[0], pause=lambda value: now.__setitem__(0, now[0] + value))
    assert 8 <= now[0] < 8.2
