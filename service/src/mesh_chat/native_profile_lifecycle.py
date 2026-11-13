"""Trusted host profile execution; keys, catalog and admission stay host-owned.

The Core host must admit each caller/key durably and retain the host incarnation
and revision from first admission. Replays use those original values. This port
never accepts a filesystem path, key, profile factory or private event from JSON.
"""
from dataclasses import dataclass
from threading import Lock, RLock
from typing import Callable, Any, Literal
from uuid import UUID, uuid4

from .errors import NativeUnavailable, ValidationError


class ProfileLifecycleResync(ValidationError):
    code = "resync_required"


class ProfileLifecycleIdentityConflict(ValidationError):
    """A retained canonical operation was queried with another identity."""


@dataclass(frozen=True)
class LifecycleRequest:
    operation_id: str
    action: Literal["lock", "select", "unlock"]
    profile_id: str
    core_host_incarnation: str
    expected_revision: int

    def __post_init__(self):
        try:
            valid_id = isinstance(self.operation_id, str) and str(UUID(self.operation_id)) == self.operation_id
        except (ValueError, TypeError, AttributeError):
            valid_id = False
        if (not valid_id or not isinstance(self.action, str) or self.action not in {"lock", "select", "unlock"}
                or not isinstance(self.profile_id, str) or not 1 <= len(self.profile_id) <= 80
                or not isinstance(self.core_host_incarnation, str) or not self.core_host_incarnation
                or type(self.expected_revision) is not int or self.expected_revision < 0):
            raise ValidationError("Profile lifecycle request identity is invalid")


@dataclass(frozen=True)
class CompletionFact:
    """Retained historical evidence, independent of current replay eligibility."""
    status: Literal["unknown", "pending", "applied"]
    request: LifecycleRequest | None = None
    result_revision: int | None = None
    result_service_incarnation: str | None = None

    def __post_init__(self):
        if self.status == "unknown":
            valid = self.request is None and self.result_revision is None and self.result_service_incarnation is None
        elif self.status == "pending":
            valid = (isinstance(self.request, LifecycleRequest) and self.result_revision is None
                     and self.result_service_incarnation is None)
        elif self.status == "applied":
            valid = (isinstance(self.request, LifecycleRequest) and type(self.result_revision) is int
                     and self.result_revision > self.request.expected_revision
                     and (self.result_service_incarnation is None or isinstance(self.result_service_incarnation, str)))
        else:
            valid = False
        if not valid:
            raise ValidationError("Profile lifecycle completion fact is invalid")


@dataclass(frozen=True)
class ProfileSlot:
    """Registered by the native host; open retrieves keys afresh on unlock."""
    profile_id: str
    open: Callable[[], Any]


class ProfileRuntimeLifecycle:
    def __init__(self, slots: tuple[ProfileSlot, ...], selected: str, *,
                 publish: Callable[[Any | None], None], remember_selection: Callable[[str], None],
                 active=None, read_selection: Callable[[], str] | None = None):
        if not 1 <= len(slots) <= 8 or len({slot.profile_id for slot in slots}) != len(slots):
            raise ValidationError("Profile slot capacity is invalid")
        if any(not isinstance(slot.profile_id, str) or not 1 <= len(slot.profile_id) <= 80
               or not callable(slot.open) for slot in slots):
            raise ValidationError("Profile slot is invalid")
        self._slots = {slot.profile_id: slot for slot in slots}
        if selected not in self._slots:
            raise ValidationError("Selected profile is not registered")
        self._selected = selected
        self._publish, self._remember_selection = publish, remember_selection
        self._read_selection = read_selection
        self._active, self._retiring = active, None
        self._pending = None
        self._last: CompletionFact | None = None
        self._revision = 0
        self._provider_fault = False
        self._incarnation = uuid4().hex
        self._lock = RLock()
        self._transition_lock = Lock()

    @property
    def active(self):
        with self._lock:
            return self._active if self._usable(self._active) else None

    @staticmethod
    def _usable(service):
        return service is not None and not service._shutdown.is_set() and not service._store_closed

    def query(self):
        with self._lock:
            current = self._active
            state = "unlocked" if self._usable(current) else "locked"
            if (self._provider_fault or self._retiring is not None
                    or (current is not None and not current._store_closed and not self._usable(current))):
                state = "retiring"
            return {"v": 1, "host_incarnation": self._incarnation, "revision": self._revision,
                    "selected_profile": self._selected, "profiles": sorted(self._slots), "state": state,
                    "service_incarnation": current._runtime_incarnation if state == "unlocked" else None,
                    "pending_action": self._pending[1] if self._pending is not None else None}

    def mutate(self, action, profile_id, operation_id, *, host_incarnation, expected_revision):
        """One admitted action; caller must revalidate authority on every call."""
        if not self._transition_lock.acquire(blocking=False):
            raise NativeUnavailable("A profile transition is already running")
        try:
            return self._mutate(action, profile_id, operation_id, host_incarnation, expected_revision)
        finally:
            self._transition_lock.release()

    def _request_identity(self, request) -> LifecycleRequest:
        operation_id, action, profile_id, revision = request
        return LifecycleRequest(operation_id, action, profile_id, self._incarnation, revision)

    def lookup_exact_completion(self, request: LifecycleRequest) -> CompletionFact:
        """Read exact retained evidence; never advance or repair a transition."""
        if not isinstance(request, LifecycleRequest):
            raise ValidationError("Profile lifecycle request identity is invalid")
        with self._lock:
            pending = self._request_identity(self._pending) if self._pending is not None else None
            if pending is not None and pending.operation_id == request.operation_id:
                if pending != request:
                    raise ProfileLifecycleIdentityConflict("Operation ID was already used with different input")
                return CompletionFact("pending", pending)
            last = self._last
            if last is not None and last.request is not None and last.request.operation_id == request.operation_id:
                if last.request != request:
                    raise ProfileLifecycleIdentityConflict("Operation ID was already used with different input")
                return last
            if request.profile_id not in self._slots:
                raise ValidationError("Profile is not registered")
            return CompletionFact("unknown")

    def _mutate(self, action, profile_id, operation_id, host_incarnation, expected_revision):
        with self._lock:
            if (not isinstance(action, str) or not isinstance(profile_id, str)
                    or action not in {"lock", "select", "unlock"} or profile_id not in self._slots):
                raise ValidationError("Profile lifecycle action is invalid")
            try:
                if str(UUID(operation_id)) != operation_id:
                    raise ValueError
            except (ValueError, TypeError, AttributeError) as error:
                raise ValidationError("Profile lifecycle operation ID is invalid") from error
            if host_incarnation != self._incarnation or type(expected_revision) is not int:
                raise ProfileLifecycleResync("Profile host incarnation changed")
            request = operation_id, action, profile_id, expected_revision
            last = self._last
            previous = last.request if last is not None else None
            if last is not None and previous is not None and previous.operation_id == operation_id:
                if (previous.operation_id, previous.action, previous.profile_id, previous.expected_revision) != request:
                    raise ValidationError("Operation ID was already used with different input")
                current = self.query()
                if last.result_revision != self._revision or last.result_service_incarnation != current["service_incarnation"]:
                    raise ProfileLifecycleResync("Profile lifecycle result is no longer current")
                return current
            if self._pending is not None:
                if self._pending[0] == operation_id and self._pending != request:
                    raise ValidationError("Operation ID was already used with different input")
                if self._pending != request:
                    raise NativeUnavailable("A profile transition is still retiring")
            elif expected_revision != self._revision:
                raise ProfileLifecycleResync("Profile lifecycle revision changed")
            else:
                if action != "select" and profile_id != self._selected:
                    raise ValidationError("Profile is not selected")
                self._pending = request
        return self._advance(authorized=True)

    def reconcile(self):
        """Retry retirement only; opening needs a freshly authorized invocation."""
        if not self._transition_lock.acquire(blocking=False):
            return self.query()
        try:
            return self._advance(authorized=False)
        finally:
            self._transition_lock.release()

    def retire_for_host_shutdown(self):
        """Trusted lifetime teardown; never opens or commits a selection.

        Host termination cannot depend on capacity for a new mutation receipt.
        The host must fence new Core admission and discard its incarnation
        after this port acknowledges retirement.
        """
        if not self._transition_lock.acquire(blocking=False):
            raise NativeUnavailable("A profile transition is already running")
        try:
            self._retire_active()
            self._drain_retirement()
            return self.query()
        finally:
            self._transition_lock.release()

    def _retire_active(self):
        with self._lock:
            if self._active is not None:
                self._retiring, self._active = self._active, None
                self._retiring._shutdown.set()

    def _drain_retirement(self):
        if self._retiring is None:
            return True
        service = self._retiring
        failure = None
        try:
            self._publish(None)
        except Exception as error:
            failure = error
        try:
            service.close()
        except Exception as error:
            failure = failure or error
        if failure is not None:
            raise NativeUnavailable("Profile retirement is incomplete") from failure
        if not service._store_closed:
            return False
        with self._lock:
            self._retiring = None
        return True

    def _advance(self, *, authorized):
        if self._provider_fault:
            raise NativeUnavailable("Profile opener violated its ownership contract")
        request = self._pending
        if request is None:
            self._drain_retirement()
            return self.query()
        _, action, target, _ = request
        changing = action == "select" and target != self._selected
        if action == "lock" or changing or (self._active is not None and not self._usable(self._active)):
            self._retire_active()
        if not self._drain_retirement():
            return self.query()
        if changing:
            if not authorized:
                return self.query()
            try:
                self._remember_selection(target)
            except Exception as error:
                try:
                    confirmed = self._read_selection is not None and self._read_selection() == target
                except Exception:
                    confirmed = False
                if not confirmed:
                    raise NativeUnavailable("Profile selection could not be committed") from error
            with self._lock:
                self._selected = target
        if action == "unlock" and self._active is None:
            if not authorized:
                return self.query()
            try:
                opened = self._slots[target].open()
            except Exception as error:
                with self._lock:
                    self._retiring = getattr(error, "retiring_service", None)
                    if self._retiring is not None:
                        self._retiring._shutdown.set()
                raise NativeUnavailable("Profile opening is incomplete") from error
            if (opened is None or not callable(getattr(opened, "close", None))
                    or not callable(getattr(getattr(opened, "_shutdown", None), "is_set", None))
                    or type(getattr(opened, "_store_closed", None)) is not bool
                    or not isinstance(getattr(opened, "_runtime_incarnation", None), str)):
                with self._lock:
                    self._provider_fault = True
                raise NativeUnavailable("Profile opener violated its ownership contract")
            if not self._usable(opened):
                with self._lock:
                    self._retiring = opened
                    opened._shutdown.set()
                raise NativeUnavailable("Profile opener returned a retiring runtime")
            try:
                self._publish(opened)
            except Exception as error:
                with self._lock:
                    self._retiring = opened
                    opened._shutdown.set()
                raise NativeUnavailable("Profile opening publication is incomplete") from error
            with self._lock:
                self._active = opened
        with self._lock:
            self._revision += 1
            self._pending = None
            result = self.query()
            self._last = CompletionFact("applied", self._request_identity(request), self._revision,
                                        result["service_incarnation"])
            return result
