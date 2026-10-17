import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from mesh_chat.direct_runtime import SessionRegistry
from mesh_chat.errors import ValidationError


@pytest.mark.parametrize("remaining", [0, -1, 3601, True, None, "30", float("inf"), float("nan")])
def test_runtime_rejects_invalid_lifetimes(remaining):
    with pytest.raises(ValidationError):
        SessionRegistry().open(remaining, lambda: None)


def test_runtime_expiry_and_authority_loss_are_terminal():
    now = [10.0]
    registry = SessionRegistry(clock=lambda: now[0])
    valid = [True]
    def authority():
        if not valid[0]:
            raise RuntimeError("private failure details")
    expired = registry.open(5, authority)
    assert expired.check()
    now[0] = 15
    assert not expired.check() and expired.reason == "expired"
    now[0] = 0  # Even a backwards test clock cannot revive a retired lease.
    assert not expired.check()
    revoked = registry.open(5, authority)
    valid[0] = False
    assert not revoked.check() and revoked.reason == "authority_unavailable"
    valid[0] = True
    assert not revoked.check()
    assert registry.open(5, authority).check()


def test_runtime_session_capacity_is_shared_and_released():
    registry = SessionRegistry()
    with ThreadPoolExecutor(max_workers=12) as pool:
        def acquire(_):
            try:
                return registry.open(30, lambda: None)
            except ValidationError:
                return None
        leases = [lease for lease in pool.map(acquire, range(12)) if lease is not None]
    assert len(leases) == 8
    leases[0].cancel()
    leases[0].cancel()
    replacement = registry.open(30, lambda: None)
    assert replacement.check()
    with pytest.raises(ValidationError):
        registry.open(30, lambda: None)
    registry.retire_all("suspended")
    assert all(lease.cancelled for lease in leases) and replacement.cancelled
    assert replacement.reason == "suspended"
    fresh = registry.open(30, lambda: None)
    registry.retire_all("closed", close=True)
    assert fresh.cancelled and fresh.reason == "closed"
    with pytest.raises(ValidationError):
        registry.open(30, lambda: None)


def test_runtime_close_wins_registration_race_without_waiting_for_authority():
    registry = SessionRegistry()
    entered, release = threading.Event(), threading.Event()
    def authority():
        entered.set()
        assert release.wait(5)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(registry.open, 30, authority)
        try:
            assert entered.wait(2)
            registry.retire_all("closed", close=True)
        finally:
            release.set()
        with pytest.raises(ValidationError, match="closed"):
            pending.result(timeout=2)


def test_runtime_validation_time_cannot_extend_expiry():
    now = [0]
    registry = SessionRegistry(clock=lambda: now[0])
    def slow_authority():
        now[0] = 10
    with pytest.raises(ValidationError, match="expired"):
        registry.open(5, slow_authority)


def test_runtime_suspension_wins_inflight_registration():
    registry = SessionRegistry()
    entered, release = threading.Event(), threading.Event()
    def authority():
        entered.set()
        assert release.wait(5)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(registry.open, 30, authority)
        try:
            assert entered.wait(2)
            registry.retire_all("suspended")
        finally:
            release.set()
        with pytest.raises(ValidationError, match="retired during registration"):
            pending.result(timeout=2)
    assert registry.open(30, lambda: None).check()
