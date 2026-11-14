"""Portable contract tests for the unwired app-owned process roster."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest

from mesh_chat.app_owned_admission import (
    AdmissionDenied, AppOwnedAdmission, ProcessIdentity,
)


IMAGE = r"C:\Apps\Node\node.exe"
OTHER = r"C:\Apps\Other\node.exe"


class Handle:
    def __init__(self, pid, birth, image=IMAGE):
        self._identity = ProcessIdentity(pid, birth, image)
        self.alive = True
        self.close_failures = 0
        self.closed = False
        self.closes = 0
        self.identity_error = False

    @property
    def identity(self):
        if self.identity_error:
            raise OSError("identity unavailable")
        return self._identity

    def is_alive(self):
        return self.alive and not self.closed

    def close(self):
        self.closes += 1
        if self.close_failures:
            self.close_failures -= 1
            raise OSError("close pending")
        assert not self.closed, "one exact handle must close only once"
        self.closed = True


class Port:
    def __init__(self):
        self.handles = {}

    def open(self, pid):
        return self.handles[pid]


def roster(*, max_helpers=1, max_sessions=2, seconds=10.0):
    owner = Handle(41, 100)
    helper = Handle(42, 200)
    port = Port()
    port.handles[42] = helper
    clock = [1000.0]
    admission = AppOwnedAdmission(owner, IMAGE, port, max_helpers=max_helpers,
                                  max_sessions=max_sessions, invitation_seconds=seconds,
                                  clock=lambda: clock[0], secret=b"s" * 32)
    return admission, owner, helper, port, clock


def test_original_owner_is_pinned_and_an_unregistered_same_image_pid_is_denied():
    admission, owner, helper, _, _ = roster()
    first = admission.admit(owner.identity)
    second = admission.admit(replace(owner.identity, image=IMAGE.upper()))
    assert first.role == second.role == "owner"
    assert admission.authorize(first) and admission.authorize(second)
    with pytest.raises(AdmissionDenied):
        admission.admit(helper.identity)
    with pytest.raises(AdmissionDenied):
        admission.admit(owner.identity, "unrequested")
    admission.release(first)
    assert not admission.authorize(first) and admission.authorize(second)
    assert admission.retire() and owner.closed and not helper.closed


def test_helper_requires_one_matching_unexpired_invitation_and_exact_os_identity():
    admission, owner, helper, _, _ = roster()
    invitation = admission.register_helper(helper.identity.pid)
    assert invitation.pid == helper.identity.pid
    assert len(invitation.token) == 64 and invitation.token not in repr(invitation)
    for identity, token in (
        (helper.identity, None),
        (helper.identity, "0" * 64),
        (helper.identity, "é" * 64),
        (helper.identity, "0" * 65536),
        (replace(helper.identity, pid=43), invitation.token),
        (replace(helper.identity, creation_time=201), invitation.token),
        (replace(helper.identity, image=OTHER), invitation.token),
    ):
        with pytest.raises(AdmissionDenied):
            admission.admit(identity, token)
    owner_lease = admission.admit(owner.identity)
    helper_lease = admission.admit(helper.identity, invitation.token)
    assert helper_lease.role == "helper" and admission.authorize(helper_lease)
    assert not admission.authorize(replace(helper_lease, role="owner"))
    assert not admission.authorize(replace(helper_lease, identity=owner.identity))
    with pytest.raises(AdmissionDenied):
        admission.admit(helper.identity, invitation.token)
    admission.release(helper_lease)
    assert not admission.authorize(helper_lease)
    with pytest.raises(AdmissionDenied):
        admission.admit(helper.identity, invitation.token)
    assert admission.authorize(owner_lease)
    assert admission.retire() and owner.closed and helper.closed


def test_expiry_replay_and_new_process_generation_are_refused():
    admission, owner, helper, port, clock = roster(seconds=2)
    expired = admission.register_helper(42)
    clock[0] += 2
    with pytest.raises(AdmissionDenied):
        admission.admit(helper.identity, expired.token)
    assert helper.closed
    replacement = Handle(42, 300)
    port.handles[42] = replacement
    current = admission.register_helper(42)
    assert current.token != expired.token
    with pytest.raises(AdmissionDenied):
        admission.admit(helper.identity, current.token)
    with pytest.raises(AdmissionDenied):
        admission.admit(replacement.identity, expired.token)
    lease = admission.admit(replacement.identity, current.token)
    assert admission.authorize(lease)
    assert admission.retire() and owner.closed and replacement.closed


def test_failed_helper_queries_keep_exact_handle_custody_and_helper_slot():
    admission, owner, helper, port, _ = roster()
    helper.identity_error = True
    helper.close_failures = 2
    with pytest.raises(AdmissionDenied):
        admission.register_helper(42)
    assert not helper.closed
    port.handles[43] = Handle(43, 210)
    with pytest.raises(AdmissionDenied):
        admission.register_helper(43)
    assert not port.handles[43].closed  # The full slot refuses before opening.
    assert admission.remove_helper(42)
    assert helper.closed and helper.closes == 3
    lease = admission.register_helper(43)
    assert lease.pid == 43
    assert admission.retire() and owner.closed and port.handles[43].closed


@pytest.mark.parametrize("pid,birth,image,alive", [
    (99, 200, IMAGE, True), (42, 90, IMAGE, True),
    (42, 200, OTHER, True), (42, 200, IMAGE, False),
])
def test_wrong_or_dead_registered_process_is_rejected_and_closed(pid, birth, image, alive):
    admission, owner, helper, port, _ = roster()
    candidate = Handle(pid, birth, image)
    candidate.alive = alive
    port.handles[42] = candidate
    with pytest.raises(AdmissionDenied):
        admission.register_helper(42)
    assert candidate.closed
    assert admission.retire() and owner.closed and not helper.closed


def test_budgets_and_active_session_count_fail_closed():
    admission, owner, helper, port, _ = roster(max_helpers=1, max_sessions=2)
    first = admission.admit(owner.identity)
    second = admission.admit(owner.identity)
    with pytest.raises(AdmissionDenied):
        admission.admit(owner.identity)
    admission.release(first)
    invitation = admission.register_helper(42)
    port.handles[43] = Handle(43, 210)
    with pytest.raises(AdmissionDenied):
        admission.register_helper(43)
    helper_lease = admission.admit(helper.identity, invitation.token)
    assert admission.authorize(helper_lease) and admission.authorize(second)
    assert admission.retire()


def test_helper_exit_and_explicit_removal_revoke_existing_lease():
    admission, owner, helper, _, _ = roster()
    token = admission.register_helper(42).token
    lease = admission.admit(helper.identity, token)
    helper.alive = False
    assert not admission.authorize(lease) and helper.closed
    assert admission.remove_helper(42)
    assert not admission.authorize(lease)
    assert admission.retire() and owner.closed


def test_owner_exit_revokes_all_leases_and_retry_retains_failed_closes():
    admission, owner, helper, _, _ = roster()
    owner_lease = admission.admit(owner.identity)
    helper_lease = admission.admit(helper.identity, admission.register_helper(42).token)
    helper.close_failures = 3
    owner.close_failures = 3
    owner.alive = False
    assert not admission.authorize(owner_lease)
    assert not admission.authorize(helper_lease)
    assert not admission.retire()
    assert admission.retire() and owner.closed and helper.closed
    with pytest.raises(AdmissionDenied):
        admission.register_helper(42)


def test_concurrent_invitation_use_admits_at_most_one_session():
    admission, owner, helper, _, _ = roster()
    token = admission.register_helper(42).token
    barrier = Barrier(3)
    def attempt():
        barrier.wait()
        try:
            return admission.admit(helper.identity, token)
        except AdmissionDenied:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = [pool.submit(attempt) for _ in range(2)]
        barrier.wait()
        leases = [call.result(timeout=2) for call in calls]
    accepted = [lease for lease in leases if lease is not None]
    assert len(accepted) == 1 and admission.authorize(accepted[0])
    assert admission.retire() and owner.closed and helper.closed


def test_removal_racing_admission_never_leaves_a_valid_helper_lease():
    admission, owner, helper, _, _ = roster()
    token = admission.register_helper(42).token
    barrier = Barrier(3)
    def attach():
        barrier.wait()
        try:
            return admission.admit(helper.identity, token)
        except AdmissionDenied:
            return None
    def remove():
        barrier.wait()
        return admission.remove_helper(42)
    with ThreadPoolExecutor(max_workers=2) as pool:
        attached, removed = pool.submit(attach), pool.submit(remove)
        barrier.wait()
        lease = attached.result(timeout=2)
        assert removed.result(timeout=2)
    assert helper.closed
    assert lease is None or not admission.authorize(lease)
    assert admission.retire() and owner.closed


@pytest.mark.parametrize("field,value", [
    ("max_helpers", 0), ("max_helpers", True), ("max_helpers", 3),
    ("max_sessions", 0), ("max_sessions", 9),
    ("invitation_seconds", 0), ("invitation_seconds", 31),
    ("invitation_seconds", True), ("secret", b"short"),
])
def test_invalid_constructor_fails_before_owner_custody(field, value):
    owner = Handle(41, 100)
    with pytest.raises(ValueError):
        AppOwnedAdmission(owner, IMAGE, Port(), **{field: value})
    assert not owner.closed


def test_dead_owner_cannot_be_registered_and_stays_with_constructor_caller():
    owner = Handle(41, 100)
    owner.alive = False
    with pytest.raises(AdmissionDenied):
        AppOwnedAdmission(owner, IMAGE, Port())
    assert not owner.closed


def test_wrong_owner_image_and_unavailable_helper_handle_fail_closed():
    wrong_owner = Handle(41, 100, OTHER)
    with pytest.raises(AdmissionDenied):
        AppOwnedAdmission(wrong_owner, IMAGE, Port())
    assert not wrong_owner.closed
    admission, owner, _, port, _ = roster()
    del port.handles[42]
    with pytest.raises(AdmissionDenied):
        admission.register_helper(42)
    assert admission.retire() and owner.closed
