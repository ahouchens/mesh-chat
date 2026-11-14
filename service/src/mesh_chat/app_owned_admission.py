"""Host-private process admission for an application-owned Windows runtime.

The Windows adapter supplies pinned process handles and the OS-observed pipe
client identity. Public Core requests never carry identities or invitations.
The caller must serialize roster revocation with Core request dispatch when
wiring this component into a live endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
import secrets
from threading import RLock
import time
from typing import Callable, Protocol

from .core_api.pipe_policy import allowed_images, image_allowed


MAX_PID = 0xFFFFFFFF
MAX_CREATION_TIME = 0xFFFFFFFFFFFFFFFF
MAX_INVITATION_COUNTER = 0xFFFFFFFFFFFFFFFF


class AdmissionDenied(Exception):
    """A process did not satisfy the private host admission contract."""


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    creation_time: int
    image: str

    def __post_init__(self):
        if (type(self.pid) is not int or not 1 <= self.pid <= MAX_PID
                or type(self.creation_time) is not int
                or not 1 <= self.creation_time <= MAX_CREATION_TIME):
            raise ValueError("Process identity is invalid")
        allowed_images((self.image,))


class ProcessHandle(Protocol):
    """A stable OS process object; close must raise if custody remains."""

    @property
    def identity(self) -> ProcessIdentity: ...

    def is_alive(self) -> bool: ...

    def close(self) -> None: ...


class ProcessPort(Protocol):
    """Open a fresh owned handle for the requested live process identifier."""

    def open(self, pid: int) -> ProcessHandle: ...

    def retire(self) -> bool: ...


@dataclass(frozen=True)
class Invitation:
    pid: int
    token: str = field(repr=False)


@dataclass(frozen=True, eq=False)
class AdmissionLease:
    identity: ProcessIdentity
    role: str
    _ticket: object = field(repr=False)


@dataclass(eq=False)
class _Entry:
    handle: ProcessHandle
    identity: ProcessIdentity
    role: str
    pid: int
    invitation: str | None = None
    expires_at: float | None = None
    tickets: set[object] = field(default_factory=set)
    revoked: bool = False


class AppOwnedAdmission:
    """Bounded owner/helper roster with exact process-handle custody.

    A successfully constructed roster owns ``owner``. A rejected constructor
    leaves that handle with its caller. A failed close retains the exact handle
    for a later remove/retire attempt and consumes its helper slot until then.
    """

    def __init__(self, owner: ProcessHandle, expected_image: str, processes: ProcessPort,
                 *, max_helpers: int = 1, max_sessions: int = 2,
                 invitation_seconds: float = 10.0,
                 clock: Callable[[], float] = time.monotonic,
                 secret: bytes | None = None):
        allowed_images((expected_image,))
        if type(max_helpers) is not int or not 1 <= max_helpers <= 2:
            raise ValueError("Helper budget is invalid")
        if type(max_sessions) is not int or not 1 <= max_sessions <= 8:
            raise ValueError("Session budget is invalid")
        if (type(invitation_seconds) not in (int, float)
                or not 0.1 <= invitation_seconds <= 30.0):
            raise ValueError("Invitation lifetime is invalid")
        if secret is None:
            secret = secrets.token_bytes(32)
        if type(secret) is not bytes or len(secret) != 32:
            raise ValueError("Invitation secret is invalid")
        identity = owner.identity
        if (not isinstance(identity, ProcessIdentity)
                or not image_allowed(identity.image, (expected_image,))
                or not self._live(owner)):
            raise AdmissionDenied()
        self._owner = _Entry(owner, identity, "owner", identity.pid)
        self._processes = processes
        self._expected_image = expected_image
        self._max_helpers = max_helpers
        self._max_sessions = max_sessions
        self._invitation_seconds = float(invitation_seconds)
        self._clock = clock
        self._secret = secret
        self._counter = 0
        self._helpers: dict[int, _Entry] = {}
        self._leases: dict[object, _Entry] = {}
        self._retained: list[_Entry] = []
        self._retired = False
        self._lock = RLock()

    @staticmethod
    def _live(handle: ProcessHandle) -> bool:
        try:
            return handle.is_alive() is True
        except Exception:
            return False

    @staticmethod
    def _same(left: ProcessIdentity, right: ProcessIdentity) -> bool:
        return (left.pid == right.pid and left.creation_time == right.creation_time
                and left.image.casefold() == right.image.casefold())

    def _drain(self) -> None:
        for entry in tuple(self._retained):
            try:
                entry.handle.close()
            except Exception:
                continue
            self._retained.remove(entry)

    def _fence_entry(self, entry: _Entry) -> None:
        if entry.revoked:
            return
        entry.revoked = True
        entry.invitation = None
        entry.expires_at = None
        for ticket in entry.tickets:
            self._leases.pop(ticket, None)
        entry.tickets.clear()
        if entry.role == "helper":
            self._helpers.pop(entry.pid, None)
        self._retained.append(entry)

    def _revoke(self, entry: _Entry) -> None:
        self._fence_entry(entry)
        self._drain()

    def _fence(self) -> None:
        self._retired = True
        for entry in tuple(self._helpers.values()):
            self._fence_entry(entry)
        self._fence_entry(self._owner)

    def _retire(self) -> None:
        self._fence()
        self._drain()

    def _require_owner(self) -> None:
        if self._retired:
            raise AdmissionDenied()
        if not self._live(self._owner.handle):
            self._fence()
            raise AdmissionDenied()

    def _prune_helpers(self) -> None:
        now = self._clock()
        for entry in tuple(self._helpers.values()):
            if (not self._live(entry.handle)
                    or (entry.invitation is not None and entry.expires_at is not None
                        and now >= entry.expires_at)):
                self._revoke(entry)
        self._drain()

    def register_helper(self, pid: int) -> Invitation:
        """Register only from a separately authenticated owner control stream."""
        if type(pid) is not int or not 1 <= pid <= MAX_PID:
            raise AdmissionDenied()
        with self._lock:
            self._require_owner()
            self._prune_helpers()
            held_helpers = sum(entry.role == "helper" for entry in self._retained)
            if (pid == self._owner.identity.pid or pid in self._helpers
                    or len(self._helpers) + held_helpers >= self._max_helpers
                    or self._counter == MAX_INVITATION_COUNTER):
                raise AdmissionDenied()
            try:
                handle = self._processes.open(pid)
            except Exception as error:
                raise AdmissionDenied() from error
            entry = _Entry(handle, self._owner.identity, "helper", pid)
            try:
                identity = handle.identity
                if (not isinstance(identity, ProcessIdentity) or identity.pid != pid
                        or identity.creation_time <= self._owner.identity.creation_time
                        or not image_allowed(identity.image, (self._expected_image,))
                        or not self._live(handle)):
                    raise AdmissionDenied()
                entry.identity = identity
                self._counter += 1
                token = hmac.new(self._secret, self._counter.to_bytes(8, "big"),
                                 hashlib.sha256).hexdigest()
                entry.invitation = token
                entry.expires_at = self._clock() + self._invitation_seconds
                self._helpers[pid] = entry
                return Invitation(pid, token)
            except Exception:
                self._retained.append(entry)
                self._drain()
                raise AdmissionDenied() from None

    def admit(self, observed: ProcessIdentity, invitation: str | None = None) -> AdmissionLease:
        """Check the OS-observed pipe client before any public Core negotiation."""
        if not isinstance(observed, ProcessIdentity):
            raise AdmissionDenied()
        with self._lock:
            self._require_owner()
            self._prune_helpers()
            if len(self._leases) >= self._max_sessions:
                raise AdmissionDenied()
            if self._same(observed, self._owner.identity):
                if invitation is not None:
                    raise AdmissionDenied()
                entry = self._owner
            else:
                entry = self._helpers.get(observed.pid)
                if (entry is None or not self._same(observed, entry.identity)
                        or not self._live(entry.handle)
                        or type(invitation) is not str or len(invitation) != 64
                        or not invitation.isascii() or entry.invitation is None
                        or not hmac.compare_digest(invitation, entry.invitation)
                        or entry.expires_at is None or self._clock() >= entry.expires_at):
                    raise AdmissionDenied()
                entry.invitation = None  # One connection consumes the proof.
                entry.expires_at = None
            ticket = object()
            entry.tickets.add(ticket)
            self._leases[ticket] = entry
            return AdmissionLease(entry.identity, entry.role, ticket)

    def candidate_role(self, observed: ProcessIdentity) -> str | None:
        """Identify an expected process without reading or consuming a proof."""
        if not isinstance(observed, ProcessIdentity):
            return None
        with self._lock:
            try:
                self._require_owner()
            except AdmissionDenied:
                return None
            self._prune_helpers()
            if self._same(observed, self._owner.identity):
                return "owner"
            entry = self._helpers.get(observed.pid)
            if (entry is not None and entry.invitation is not None
                    and self._same(observed, entry.identity) and self._live(entry.handle)):
                return "helper"
            return None

    def authorize(self, lease: AdmissionLease) -> bool:
        """Recheck a previously admitted session before each Core operation."""
        if not isinstance(lease, AdmissionLease):
            return False
        with self._lock:
            try:
                self._require_owner()
            except AdmissionDenied:
                return False
            entry = self._leases.get(lease._ticket)
            if (entry is None or entry.revoked or not self._same(lease.identity, entry.identity)
                    or lease.role != entry.role):
                return False
            if not self._live(entry.handle):
                if entry.role == "owner":
                    self._fence()
                else:
                    self._revoke(entry)
                return False
            return True

    def release(self, lease: AdmissionLease) -> None:
        """Forget a detached session; helper proof stays consumed."""
        if not isinstance(lease, AdmissionLease):
            return
        with self._lock:
            entry = self._leases.pop(lease._ticket, None)
            if entry is not None:
                entry.tickets.discard(lease._ticket)

    def remove_helper(self, pid: int) -> bool:
        """Revoke immediately and retry closing any retained exact handle."""
        if type(pid) is not int or not 1 <= pid <= MAX_PID:
            raise ValueError("Helper process identifier is invalid")
        with self._lock:
            entry = self._helpers.get(pid)
            if entry is not None:
                self._revoke(entry)
            self._drain()
            return not any(item.role == "helper" and item.pid == pid
                           for item in self._retained)

    def retire(self) -> bool:
        """Revoke all leases; return true only after every handle is closed."""
        with self._lock:
            self._retire()
            return not self._retained

    def fence(self) -> None:
        """Revoke every grant while workers/watchers still hold process pins."""
        with self._lock:
            self._fence()
