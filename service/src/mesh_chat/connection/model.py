"""Immutable policy values; no service, clocks, transport, or storage imports."""

from dataclasses import dataclass
from enum import Enum


class Desired(str, Enum):
    ENABLED = "enabled"
    STOPPED = "stopped"


class Execution(str, Enum):
    AVAILABLE = "available"
    PAUSED = "paused"
    LOCKED = "locked"
    SHUTTING_DOWN = "shutting_down"


class Phase(str, Enum):
    DISCOVER = "discover"
    REQUEST = "request"
    WAIT_REQUEST = "wait_request"
    WAIT_OFFER = "wait_offer"
    GATHER_OFFER = "gather_offer"
    GATHER_ANSWER = "gather_answer"
    PUBLISH_OFFER = "publish_offer"
    PUBLISH_ANSWER = "publish_answer"
    WAIT_ANSWER = "wait_answer"
    APPLY_ANSWER = "apply_answer"
    CHECKING = "checking"
    ATTACH = "attach"
    PATH = "path"
    INSPECT = "inspect"


class Health(str, Enum):
    ABSENT = "absent"
    OPEN = "open"
    SUSPECT = "suspect"
    CLOSING = "closing"


class Bridge(str, Enum):
    DETACHED = "detached"
    ATTACHING = "attaching"
    PATH_PENDING = "path_pending"
    READY = "ready"
    RESTORING = "restoring"


class Failure(str, Enum):
    TRANSIENT = "transient"
    RATE_LIMITED = "rate_limited"
    CONFIGURATION = "configuration"
    INVALID_DOCUMENT = "invalid_document"
    REVOKED = "revoked"
    UNSUPPORTED = "unsupported"
    INTERNAL = "internal"


@dataclass(frozen=True)
class ConnectionKey:
    scope: str
    profile_id: str
    local_device: str
    remote_device: str | None

    def __post_init__(self) -> None:
        values = (self.scope, self.profile_id, self.local_device)
        if any(not value or len(value.encode("utf-8")) > 256 for value in values):
            raise ValueError("Connection identity is empty or oversized")
        if self.remote_device is not None and len(self.remote_device.encode("utf-8")) > 256:
            raise ValueError("Remote device identity is oversized")


@dataclass(frozen=True)
class Authority:
    revision: int
    authorized: bool
    signaling_available: bool
    preferred: bool


@dataclass(frozen=True)
class Resource:
    adapter_epoch: str
    resource_id: str

    def __post_init__(self) -> None:
        if any(not value or len(value.encode("utf-8")) > 128
               for value in (self.adapter_epoch, self.resource_id)):
            raise ValueError("Resource identity is empty or oversized")


@dataclass(frozen=True)
class Operation:
    runtime_epoch: str
    key: ConnectionKey
    generation: int
    policy_revision: int
    sequence: int

    def __post_init__(self) -> None:
        if not self.runtime_epoch or len(self.runtime_epoch.encode("utf-8")) > 64:
            raise ValueError("Runtime epoch is empty or oversized")


@dataclass(frozen=True)
class Carrier:
    resource: Resource
    policy_revision: int
    health: Health
    bridge: Bridge
    observed_at: float


@dataclass(frozen=True)
class Step:
    phase: Phase
    resource: Resource
    deadline: float
    poll_at: float
    operation: Operation | None


@dataclass(frozen=True)
class Policy:
    phase_timeout: float = 45.0
    gather_timeout: float = 25.0
    poll_interval: float = 5.0
    disconnect_grace: float = 10.0
    backoff: tuple[float, ...] = (1, 2, 5, 15, 30, 60)
    max_actors: int = 256
    max_workers: int = 2
    max_effects: int = 64
    max_effect_bytes: int = 262144
    max_diagnostics: int = 256
    jitter_fraction: float = 0.2

    def __post_init__(self) -> None:
        if (min(self.phase_timeout, self.gather_timeout, self.poll_interval,
                self.disconnect_grace, self.max_actors, self.max_workers,
                self.max_effects, self.max_effect_bytes, self.max_diagnostics) <= 0
                or not self.backoff or min(self.backoff) <= 0):
            raise ValueError("Connection policy limits must be positive")
        if not 0 <= self.jitter_fraction <= 1:
            raise ValueError("Connection jitter must be bounded")


@dataclass(frozen=True)
class ConnectionState:
    key: ConnectionKey
    runtime_epoch: str
    authority: Authority
    desired: Desired = Desired.STOPPED
    execution: Execution = Execution.AVAILABLE
    network_available: bool = True
    adapter_epoch: str = "native"
    generation: int = 0
    sequence: int = 0
    negotiation: Step | None = None
    carrier: Carrier | None = None
    failures: int = 0
    retry_at: float = 0
    inspect_at: float = 0
    blocked: bool = False
    reason: str = "idle"
    policy: Policy = Policy()


@dataclass(frozen=True)
class Tick:
    now: float
    jitter: float = 0


@dataclass(frozen=True)
class ContextChanged:
    now: float
    authority: Authority | None = None
    desired: Desired | None = None
    execution: Execution | None = None
    network_available: bool | None = None


@dataclass(frozen=True)
class Result:
    operation: Operation
    now: float
    pending: bool = False
    allocated: Resource | None = None
    verified: bool = False
    observed_health: Health | None = None
    observed_bridge: Bridge | None = None


@dataclass(frozen=True)
class Adopted:
    """Private effect completion after domain authority transfers a carrier."""
    operation: Operation
    now: float
    allocated: Resource


@dataclass(frozen=True)
class Failed:
    operation: Operation
    now: float
    failure: Failure
    retry_after: float = 0
    allocated: Resource | None = None
    jitter: float = 0


@dataclass(frozen=True)
class Observed:
    resource: Resource
    now: float
    health: Health
    bridge: Bridge


Event = Tick | ContextChanged | Result | Failed | Adopted | Observed


@dataclass(frozen=True)
class Work:
    operation: Operation
    phase: Phase
    resource: Resource
    deadline: float


@dataclass(frozen=True)
class Cancel:
    operation: Operation


@dataclass(frozen=True)
class Retire:
    resource: Resource


Effect = Work | Cancel | Retire


@dataclass(frozen=True)
class Transition:
    state: ConnectionState
    effects: tuple[Effect, ...] = ()
    reason: str = "no_change"
