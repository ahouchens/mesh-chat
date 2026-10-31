import threading

from mesh_chat.connection.effects import BoundedEffectRunner
from mesh_chat.connection.model import (
    Authority, Cancel, ConnectionKey, ConnectionState, Desired, Policy, Result,
    Retire, Tick,
)
from mesh_chat.connection.reducer import transition


def work():
    state = ConnectionState(ConnectionKey("personal", "p", "l", "r"), "e",
                            Authority(1, True, True, True), Desired.ENABLED)
    return transition(state, Tick(0)).effects[0]


class BlockingPort:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.closed = []

    def execute(self, operation, cancellation):
        self.entered.set()
        assert self.release.wait(2)
        return Result(operation.operation, 1, allocated=operation.resource)

    def retire(self, resource):
        self.closed.append(resource)


def test_cancel_does_not_release_work_slot_while_allocation_is_running():
    port = BlockingPort()
    runner = BoundedEffectRunner(port, Policy(max_workers=1), now=lambda: 0)
    operation = work()
    try:
        assert runner.submit(operation)
        assert port.entered.wait(2)
        assert runner.submit(Cancel(operation.operation))
        assert runner.active == 1
        assert not runner.submit(operation)
        port.release.set()
        event = runner.next_completion(timeout=2)
        assert event.operation == operation.operation
        assert event.allocated == operation.resource
        assert runner.active == 0
    finally:
        port.release.set()
        assert runner.close(timeout=2)


def test_exact_cleanup_and_duplicate_close():
    port = BlockingPort()
    runner = BoundedEffectRunner(port)
    resource = work().resource
    try:
        assert runner.submit(Retire(resource))
        result = runner.next_completion(timeout=2)
        assert result.resource == resource and result.succeeded
        assert port.closed == [resource]
        assert runner.submit(Retire(resource))
        assert runner.next_completion(timeout=2).succeeded
        assert port.closed == [resource, resource]
    finally:
        assert runner.close(timeout=2)


def test_shutdown_reports_live_work_instead_of_abandoning_it():
    port = BlockingPort()
    runner = BoundedEffectRunner(port, Policy(max_workers=1), now=lambda: 0)
    operation = work()
    assert runner.submit(operation)
    assert port.entered.wait(2)
    assert not runner.close(timeout=0)
    assert runner.active == 1
    assert not runner.submit(operation)
    port.release.set()
    assert runner.next_completion(timeout=2).allocated == operation.resource
    assert runner.close(timeout=2)


def test_work_byte_budget_rejects_before_execution():
    port = BlockingPort()
    runner = BoundedEffectRunner(port, Policy(max_effect_bytes=1), now=lambda: 0)
    try:
        assert not runner.submit(work())
        assert not port.entered.is_set()
        assert runner.idle
    finally:
        assert runner.close()


def test_stalled_work_is_reported_without_freeing_its_reservation():
    port = BlockingPort()
    now = [0]
    policy = Policy(max_workers=1)
    runner = BoundedEffectRunner(port, policy, now=lambda: now[0])
    operation = work()
    try:
        assert runner.submit(operation)
        assert port.entered.wait(2)
        now[0] = operation.deadline + policy.disconnect_grace
        assert runner.stalled()
        assert runner.active == 1
        assert not runner.close(0)
        port.release.set()
        runner.next_completion(timeout=2)
        assert not runner.stalled()
    finally:
        port.release.set()
        runner.close()
