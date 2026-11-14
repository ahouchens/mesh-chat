"""Portable contract tests for the opt-in app-owned pipe admission callback."""

from dataclasses import replace

from mesh_chat.app_owned_admission import AppOwnedAdmission, ProcessIdentity
from mesh_chat.app_owned_control import encode_helper_preface
from mesh_chat.app_owned_host import AppOwnedPipeAdmission


IMAGE = r"C:\Apps\Node\node.exe"


class Handle:
    def __init__(self, identity):
        self.identity = identity
        self.alive = True
        self.closed = False
        self.close_failures = 0
        self.closes = 0

    def is_alive(self):
        return self.alive and not self.closed

    def close(self):
        self.closes += 1
        if self.close_failures:
            self.close_failures -= 1
            raise OSError("close pending")
        assert not self.closed
        self.closed = True


class Port:
    def __init__(self, identities):
        self.identities = identities
        self.opened = []
        self.next_close_failures = 0
        self.retire_calls = 0
        self.retire_ready = True

    def open(self, pid):
        handle = Handle(self.identities[pid])
        handle.close_failures = self.next_close_failures
        self.next_close_failures = 0
        self.opened.append(handle)
        return handle

    def retire(self):
        self.retire_calls += 1
        return self.retire_ready


class Stream:
    def __init__(self, line=b""):
        self.line = line
        self.reads = []

    def readline(self, limit, *, deadline):
        self.reads.append((limit, deadline))
        return self.line


def fixture():
    owner_identity = ProcessIdentity(41, 100, IMAGE)
    helper_identity = ProcessIdentity(42, 200, IMAGE)
    outsider_identity = ProcessIdentity(43, 300, IMAGE)
    owner = Handle(owner_identity)
    port = Port({41: owner_identity, 42: helper_identity, 43: outsider_identity})
    clock = [1000.0]
    roster = AppOwnedAdmission(owner, IMAGE, port, clock=lambda: clock[0],
                               secret=b"s" * 32)
    callback = AppOwnedPipeAdmission(roster, port)
    return callback, roster, owner, port, clock


def test_owner_needs_exact_process_identity_and_no_preface():
    callback, roster, owner, port, _ = fixture()
    stream = Stream()
    lease = callback(41, stream)
    assert lease is not None and lease.authorize() is True
    assert not stream.reads and port.opened[-1].closed
    port.identities[41] = replace(owner.identity, creation_time=101)
    assert callback(41, stream) is None
    assert lease.authorize() is True
    lease.release()
    lease.release()
    assert lease.authorize() is False
    assert callback.retire() and not owner.closed
    assert roster.retire() and owner.closed


def test_unknown_and_wrong_generation_are_rejected_before_preface_read():
    callback, roster, owner, port, _ = fixture()
    stream = Stream(b"untrusted")
    assert callback(43, stream) is None
    invitation = roster.register_helper(42)
    assert callback(43, stream) is None
    port.identities[42] = replace(port.identities[42], creation_time=201)
    assert callback(42, stream) is None
    assert not stream.reads
    port.identities[42] = replace(port.identities[42], creation_time=200)
    lease = callback(42, Stream(encode_helper_preface(invitation.token)))
    assert lease is not None and lease.authorize()
    lease.release()
    assert callback.retire() and roster.retire() and owner.closed


def test_helper_proof_is_bounded_single_use_and_revoked_by_roster_fence():
    callback, roster, owner, port, _ = fixture()
    invitation = roster.register_helper(42)
    malformed = Stream(b"MESH-HELPER/1 " + b"0" * 64 + b"\n")
    assert callback(42, malformed) is None
    assert len(malformed.reads) == 1 and malformed.reads[0][0] == 79
    valid = Stream(encode_helper_preface(invitation.token))
    lease = callback(42, valid)
    assert lease is not None and lease.authorize()
    assert callback(42, valid) is None
    roster.fence()
    assert not lease.authorize()
    lease.release()
    assert callback.retire() and not owner.closed
    assert roster.retire() and owner.closed


def test_expired_helper_proof_and_temporary_close_failure_keep_custody():
    callback, roster, owner, port, clock = fixture()
    invitation = roster.register_helper(42)
    clock[0] += 10
    assert callback(42, Stream(encode_helper_preface(invitation.token))) is None
    port.next_close_failures = 2
    assert callback(41, Stream()) is None
    temporary = port.opened[-1]
    assert temporary.closes == 1 and not temporary.closed
    assert callback(41, Stream()) is None  # Pending exact handle blocks admission.
    port.retire_ready = False
    assert callback.retire() is False
    assert temporary.closes == 2 and port.retire_calls == 1
    port.retire_ready = True
    assert callback.retire() is True
    assert temporary.closed and temporary.closes == 3
    assert roster.retire() and owner.closed
