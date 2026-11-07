"""Virtual-time execution of the production supervisor, with an ownership oracle."""

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from random import Random

from mesh_chat.connection.model import (
    Adopted, Authority, Bridge, Cancel, ConnectionKey, ConnectionState, ContextChanged,
    Desired, Failed, Failure, Health, Phase, Resource, Result, Retire, Work,
)
from mesh_chat.connection.supervisor import ConnectionSupervisor


def implementation_digest():
    root = Path(__file__).resolve().parents[2] / "src" / "mesh_chat" / "connection"
    digest = sha256()
    for name in ("model.py", "reducer.py", "supervisor.py"):
        digest.update(name.encode())
        digest.update((root / name).read_text(encoding="utf-8").encode())
    digest.update(Path(__file__).read_text(encoding="utf-8").encode())
    return digest.hexdigest()


def replay(report):
    """Replay a bounded qualification trace; never a shipping event endpoint."""
    sim = Simulation()
    if not isinstance(report, dict):
        raise ValueError("Trace report must be an object")
    # Canonicalize in-memory tuples and persisted JSON arrays in one place.
    policy = json.loads(json.dumps(asdict(sim.owner.policy)))
    if (report.get("trace_version") != 1 or report.get("contract_version") != 1
            or report.get("implementation_digest") != implementation_digest()
            or json.loads(json.dumps(report.get("policy"))) != policy):
        raise ValueError("Trace requires matching schema, policy and implementation")
    trace = report.get("trace")
    if not isinstance(trace, list) or not 1 <= len(trace) <= 10000:
        raise ValueError("Trace is empty or exceeds the action budget")
    for action in trace:
        _replay_action(sim, action)
    sim.assert_safe()
    if sim.allocated or sim.pending:
        raise ValueError("Trace did not finish resource cleanup")
    return {**report, "cleanup": "passed", "replayed": True}


def _replay_action(sim, action):
    if not isinstance(action, dict):
        raise ValueError("Invalid trace action")
    kind = action.get("type")
    if kind == "advance" and set(action) == {"type", "seconds"}:
        seconds = action["seconds"]
        if type(seconds) not in {int, float} or not 0 <= seconds <= 3600:
            raise ValueError("Invalid virtual clock advance")
        sim.advance(seconds)
    elif kind in {"intent", "network"}:
        field = "enabled" if kind == "intent" else "available"
        if set(action) != {"type", field} or type(action[field]) is not bool:
            raise ValueError("Invalid context action")
        getattr(sim, kind)(action[field])
    elif kind == "complete" and set(action) == {"type", "index", "fail", "duplicate", "adopt"}:
        if (type(action["index"]) is not int or not 0 <= action["index"] < len(sim.pending)
                or any(type(action[field]) is not bool for field in ("fail", "duplicate", "adopt"))):
            raise ValueError("Invalid completion action")
        sim.complete(action["index"], action["fail"], action["duplicate"], action["adopt"])
    else:
        raise ValueError("Unknown or malformed trace action")


class Simulation:
    def __init__(self, seed=42):
        self.random = Random(seed)
        self.now = 0.0
        self.owner = ConnectionSupervisor("simulation-epoch")
        self.key = ConnectionKey("test", "test-profile", "test-local", "test-remote")
        self.owner.register(ConnectionState(self.key, self.owner.runtime_epoch,
                            Authority(1, True, True, True), Desired.ENABLED))
        self.pending = []
        self.allocated = set()
        self.trace = []

    def advance(self, seconds):
        self.now += seconds
        self.trace.append({"type": "advance", "seconds": seconds})
        self.owner.tick(self.now)
        self.drain()

    def intent(self, enabled):
        desired = Desired.ENABLED if enabled else Desired.STOPPED
        self.trace.append({"type": "intent", "enabled": enabled})
        self.owner.dispatch(self.key, ContextChanged(self.now, desired=desired))
        self.drain()

    def network(self, available):
        self.trace.append({"type": "network", "available": available})
        self.owner.dispatch(self.key, ContextChanged(self.now, network_available=available))
        self.drain()

    def complete(self, index=0, fail=False, duplicate=False, adopt=False):
        if not self.pending:
            return
        index %= len(self.pending)
        work = self.pending.pop(index)
        allocated = (work.resource if work.phase in {
            Phase.GATHER_OFFER, Phase.GATHER_ANSWER, Phase.CHECKING} else None)
        if adopt and work.phase is Phase.DISCOVER:
            allocated = Resource(work.resource.adapter_epoch, "manual-" + work.resource.resource_id)
        if allocated:
            self.allocated.add(allocated)
        event = (Failed(work.operation, self.now, Failure.TRANSIENT, allocated=allocated)
                 if fail else Result(work.operation, self.now, allocated=allocated,
                                     verified=work.phase is Phase.CHECKING,
                                     observed_health=Health.OPEN if work.phase is Phase.INSPECT else None,
                                     observed_bridge=Bridge.READY if work.phase is Phase.INSPECT else None))
        if adopt and work.phase is Phase.DISCOVER and not fail:
            event = Adopted(work.operation, self.now, allocated)
        self.trace.append({"type": "complete", "index": index, "fail": fail,
                           "duplicate": duplicate, "adopt": adopt})
        self.owner.dispatch(self.key, event)
        self.drain()
        if duplicate:
            self.owner.dispatch(self.key, event)
            self.drain()

    def drain(self):
        for effect in self.owner.drain():
            if isinstance(effect, Work):
                self.pending.append(effect)
            elif isinstance(effect, Retire):
                self.allocated.discard(effect.resource)
                self.owner.resource_released(effect.resource)
            elif not isinstance(effect, Cancel):
                raise AssertionError("Unknown effect")
        self.assert_safe()

    def assert_safe(self):
        state = self.owner.snapshot(self.key)
        assert len(self.pending) <= self.owner.policy.max_workers
        assert len({work.operation for work in self.pending}) == len(self.pending)
        if state.desired is Desired.STOPPED or not state.authority.authorized:
            assert state.carrier is None
            assert state.negotiation is None
        if state.carrier:
            assert state.carrier.resource in self.allocated
            assert state.carrier.policy_revision == state.authority.revision
        # Resource accounting is independent of state transition expectations:
        # every allocated handle has a carrier, candidate, or pending completion.
        owned = {work.resource for work in self.pending}
        if state.carrier:
            owned.add(state.carrier.resource)
        if state.negotiation:
            owned.add(state.negotiation.resource)
        assert self.allocated <= owned

    def recover(self):
        self.intent(True)
        self.network(True)
        for _ in range(100):
            if self.pending:
                self.complete()
            else:
                self.advance(1)
            state = self.owner.snapshot(self.key)
            if state.carrier and state.carrier.bridge is Bridge.READY:
                return
        raise AssertionError("No progress after faults stopped")

    def close(self):
        self.intent(False)
        while self.pending:
            self.complete()
        assert not self.allocated


def scenario(name, seed=42, steps=100):
    sim = Simulation(seed)
    sim.advance(0)
    if name == "stale_completion":
        sim.intent(False)
        sim.complete(duplicate=True)
    elif name == "partition_30s":
        sim.recover()
        sim.network(False)
        sim.advance(30)
        sim.network(True)
    elif name == "fault_sequence":
        for _ in range(steps):
            action = sim.random.randrange(5)
            if action == 0:
                sim.advance(sim.random.randrange(60))
            elif action == 1:
                sim.intent(bool(sim.random.randrange(2)))
            elif action == 2:
                sim.network(bool(sim.random.randrange(2)))
            else:
                sim.complete(sim.random.randrange(2), fail=action == 3, duplicate=action == 4)
    else:
        raise ValueError("Unknown simulation scenario")
    sim.recover()
    sim.close()
    return {"scenario": name, "seed": seed, "evidence": "simulated",
            "policy": asdict(sim.owner.policy), "trace": sim.trace,
            "cleanup": "passed", "contract_version": 1, "trace_version": 1,
            "implementation_digest": implementation_digest()}
