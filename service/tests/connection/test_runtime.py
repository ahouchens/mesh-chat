from threading import Event
from time import monotonic

import pytest

from mesh_chat.connection.model import Bridge, Execution, Health, Phase, Resource, Result, Retire
from mesh_chat.connection.runtime import ConnectionRuntime


class Executor:
    def execute(self, work, cancellation):
        return Result(work.operation, monotonic(),
                      allocated=work.resource if work.phase in {
                          Phase.GATHER_OFFER, Phase.GATHER_ANSWER, Phase.CHECKING} else None,
                      verified=work.phase is Phase.CHECKING,
                      observed_health=Health.OPEN if work.phase is Phase.INSPECT else None,
                      observed_bridge=Bridge.READY if work.phase is Phase.INSPECT else None)

    def retire(self, resource):
        pass


def runtime():
    profile = {"id": "p", "local_device_id": "local", "remote_device_id": "remote",
               "contact_id": "c", "active": True, "auto_reconnect": True,
               "peer_auto_reconnect": True, "effective": {"ready": True, "preferred": True}}
    owner = ConnectionRuntime("test-epoch", lambda *_: Executor(),
        profiles=lambda: {"profiles": [profile]}, execution=lambda: Execution.AVAILABLE,
        activate=lambda _: None)
    return owner, profile


@pytest.mark.parametrize("revocation", ["stop", "workspace"])
def test_driver_executes_phases_and_fences_failed_persistent_authority_write(revocation):
    owner, profile = runtime()
    if revocation == "workspace":
        profile.update(scope_kind="workspace", workspace_id="w")
    try:
        deadline = monotonic() + 3
        while monotonic() < deadline:
            owner.step()
            if owner.snapshots()["p"]["messaging_ready"]:
                break
            Event().wait(0.005)
        assert owner.snapshots()["p"]["messaging_ready"]
        carrier = owner.owner.snapshots()[0].carrier.resource
        assert owner.permits_carrier("p", carrier)
        # The store still reports enabled, as if a Stop transaction failed.
        if revocation == "workspace":
            owner.begin_authority_change(("workspace", "w"))
        else:
            owner.fence("c")
        assert not owner.permits_carrier("p", carrier)
        owner.step()
        assert owner.snapshots()["p"]["desired"] == "stopped"
        assert not owner.snapshots()["p"]["messaging_ready"]
        assert profile["active"]
    finally:
        owner.stop()
        owner.wait()


def test_explicit_stopped_profile_is_not_automatically_activated():
    owner, profile = runtime()
    profile.update(active=False, state="stopped")
    called = []
    owner.activate = called.append
    try:
        owner.step()
        assert not called
        assert owner.snapshots()["p"]["desired"] == "stopped"
        assert owner.runner.idle
    finally:
        owner.stop()


def test_authority_write_fences_until_matching_commit_without_overriding_stop():
    owner, profile = runtime()
    try:
        owner.synchronize()
        first = owner.begin_authority_change("c")
        owner.synchronize()
        assert owner.snapshots()["p"]["desired"] == "stopped"
        second = owner.begin_authority_change("c")
        owner.commit_authority_change("c", first)
        owner.synchronize()
        assert owner.snapshots()["p"]["desired"] == "stopped"
        owner.commit_authority_change("c", second)
        owner.synchronize()
        assert owner.snapshots()["p"]["desired"] == "enabled"
        token = owner.begin_authority_change("c")
        owner.fence("c")
        owner.commit_authority_change("c", token)
        owner.synchronize()
        assert owner.snapshots()["p"]["desired"] == "stopped"
    finally:
        owner.stop()


def test_scan_started_before_authority_commit_cannot_restore_stale_permission():
    owner, profile = runtime()
    try:
        owner.synchronize()
        def old_scan():
            stale = {**profile}
            token = owner.begin_authority_change("c")
            profile["effective"] = {"ready": False, "reasons": ["contact_blocked"]}
            owner.commit_authority_change("c", token)
            return {"profiles": [stale]}
        owner.profiles = old_scan
        owner.synchronize()
        assert owner.snapshots()["p"]["desired"] == "stopped"
        owner.profiles = lambda: {"profiles": [profile]}
        owner.synchronize()
        assert not owner.owner.snapshots()[0].authority.authorized
    finally:
        owner.stop()


def test_runtime_projection_sequence_advances_on_observations():
    owner, _ = runtime()
    try:
        owner.synchronize()
        before = owner.snapshots()["p"]["sequence"]
        owner.fence("c")
        assert owner.snapshots()["p"]["sequence"] > before
    finally:
        owner.stop()


def test_workspace_authority_fence_covers_all_devices_without_crossing_scopes():
    owner, personal = runtime()
    workspace = {**personal, "id": "workspace-peer", "contact_id": "workspace:w:member:device",
                 "scope_kind": "workspace", "workspace_id": "w"}
    second = {**workspace, "id": "workspace-second-device", "remote_device_id": "second"}
    other = {**workspace, "id": "other-workspace", "workspace_id": "other"}
    owner.profiles = lambda: {"profiles": [personal, workspace, second, other]}
    try:
        # A failed authority write can precede the first discovery of its peers.
        token = owner.begin_authority_change(("workspace", "w"))
        owner.synchronize()
        snapshots = owner.snapshots()
        assert snapshots["workspace-peer"]["desired"] == "stopped"
        assert snapshots["workspace-second-device"]["desired"] == "stopped"
        assert snapshots["p"]["desired"] == snapshots["other-workspace"]["desired"] == "enabled"
        owner.committed_start()
        owner.synchronize()
        assert owner.snapshots()["workspace-peer"]["desired"] == "stopped"
        owner.commit_authority_change(("workspace", "w"), token)
        owner.synchronize()
        assert owner.snapshots()["workspace-peer"]["desired"] == "enabled"
        owner.begin_authority_change(("workspace", "w"))
        assert owner.snapshots()["workspace-peer"]["desired"] == "stopped"
    finally:
        owner.stop()


@pytest.mark.parametrize("contact", [None, "c"])
def test_failed_stop_before_first_scan_still_fences_loaded_profiles(contact):
    owner, profile = runtime()
    owner.fence(contact)
    try:
        owner.step()
        assert owner.snapshots()["p"]["desired"] == "stopped"
        assert owner.runner.idle
        owner.committed_start("c")
        owner.synchronize()
        assert owner.snapshots()["p"]["desired"] == "enabled"
    finally:
        owner.stop()


def test_removed_profile_requires_explicit_restart_and_preserves_operation_generation():
    owner, profile = runtime()
    try:
        owner.synchronize()
        owner.owner.tick(monotonic())
        before = owner.owner.snapshots()[0].generation
        owner.profiles = lambda: {"profiles": []}
        owner.synchronize()
        owner.profiles = lambda: {"profiles": [profile]}
        owner.synchronize()
        assert owner.snapshots()["p"]["desired"] == "stopped"
        owner.committed_start("c")
        owner.synchronize()
        owner.owner.tick(monotonic())
        assert owner.owner.snapshots()[0].generation > before
    finally:
        owner.stop()
def test_private_preparation_runs_once_before_any_profile_or_effect():
    calls = []
    owner = ConnectionRuntime("epoch", lambda *_: Executor(),
        profiles=lambda: calls.append("profiles") or {"profiles": []},
        execution=lambda: Execution.AVAILABLE, activate=lambda _: None,
        prepare=lambda: calls.append("prepare"))
    try:
        owner.step()
        owner.step()
        assert calls == ["prepare", "profiles", "profiles"]
    finally: owner.stop()


def test_failed_private_preparation_quarantines_without_admitting_work():
    calls = []
    def fail():
        calls.append("prepare")
        raise OSError("private failure")
    owner = ConnectionRuntime("epoch", lambda *_: Executor(),
        profiles=lambda: pytest.fail("Failed recovery cannot scan or negotiate"),
        execution=lambda: Execution.AVAILABLE, activate=lambda _: None, prepare=fail)
    try:
        owner.step()
        owner.step()
        assert owner._failure == "adapter_quarantined"
        assert calls == ["prepare"] and owner.runner.idle
    finally: owner.stop()


def test_recovery_admission_observes_fences_before_an_actor_exists():
    owner, profile = runtime()
    try:
        assert owner.permits_recovery(profile)
        owner.fence("c")
        assert not owner.permits_recovery(profile)
        owner.committed_start("c")
        profile.update(scope_kind="workspace", workspace_id="w")
        owner.begin_authority_change(("workspace", "w"))
        assert not owner.permits_recovery(profile)
    finally: owner.stop()


@pytest.mark.parametrize("termination", ["quarantine", "shutdown"])
@pytest.mark.parametrize("target", [None, "c"])
@pytest.mark.parametrize("discovered", [False, True])
def test_start_cannot_restore_authority_in_a_terminal_runtime(termination, target, discovered):
    owner, profile = runtime()
    try:
        if discovered:
            owner.synchronize()
        if termination == "quarantine":
            owner.quarantine()
        else:
            assert owner.stop()
        profile["active"] = False
        owner.activate = lambda _: pytest.fail("Terminal runtime cannot activate stored intent")
        owner.committed_start(target)
        assert not owner.permits_recovery(profile)
        owner.synchronize()
        assert owner.snapshots()["p"]["desired"] == "stopped"
        assert not owner.permits_carrier("p", Resource("native", "old-carrier"))
        assert owner.runner.idle
    finally:
        owner.stop()


def test_quarantine_survives_failed_cleanup_and_retries_exact_resource_on_schedule():
    clock, attempts, work = [0.0], [], []
    resource = Resource("native-epoch", "failed-disposal")

    class FailingDisposal(Executor):
        def execute(self, operation, cancellation):
            work.append(operation)
            return super().execute(operation, cancellation)

        def retire(self, value):
            attempts.append(value)
            if len(attempts) == 1:
                raise OSError("disposal unavailable")

    owner = ConnectionRuntime("epoch", lambda *_: FailingDisposal(),
        profiles=lambda: pytest.fail("Quarantine must not rediscover or activate profiles"),
        execution=lambda: Execution.AVAILABLE, activate=lambda _: None, now=lambda: clock[0])
    try:
        owner.quarantine()
        owner.step()
        assert owner.runner.submit(Retire(resource))
        deadline = monotonic() + 2
        while not owner.runner.idle and monotonic() < deadline:
            owner.step()
            Event().wait(.001)
        assert owner.runner.idle
        assert owner._failure == "adapter_quarantined"
        assert attempts == [resource]
        owner.committed_start()
        owner.step()
        assert attempts == [resource]
        clock[0] = owner.owner.policy.poll_interval
        owner.step()
        deadline = monotonic() + 2
        while not owner.runner.idle and monotonic() < deadline:
            owner.step()
            Event().wait(.001)
        assert owner.runner.idle and attempts == [resource, resource]
        assert owner._failure == "adapter_quarantined" and not work
        assert owner.stop()
    finally:
        owner.stop()
        owner.wait()


def test_late_allocation_after_a_stall_is_retired_without_restarting_the_adapter():
    from dataclasses import replace

    clock = [monotonic()]
    entered, release = Event(), Event()
    allocations, retired = [], []
    _, profile = runtime()

    class StalledAllocation(Executor):
        def execute(self, work, cancellation):
            if work.phase in {Phase.GATHER_OFFER, Phase.GATHER_ANSWER}:
                allocations.append(work)
                entered.set()
                if not release.wait(3):
                    raise TimeoutError("Test did not release allocation")
            return replace(super().execute(work, cancellation), now=clock[0])

        def retire(self, resource):
            retired.append(resource)

    owner = ConnectionRuntime("epoch", lambda *_: StalledAllocation(),
        profiles=lambda: {"profiles": [profile]}, execution=lambda: Execution.AVAILABLE,
        activate=lambda _: None, now=lambda: clock[0])
    try:
        deadline = monotonic() + 2
        while not entered.is_set() and monotonic() < deadline:
            owner.step()
            Event().wait(.001)
        assert entered.is_set()
        work = allocations[0]
        clock[0] = work.deadline + owner.owner.policy.disconnect_grace
        owner.step()
        assert owner._failure == "adapter_quarantined"
        assert owner.runner.active == 1  # A deadline is not proof the native call stopped.
        owner.committed_start("c")
        assert not owner.permits_recovery(profile)
        release.set()
        deadline = monotonic() + 2
        while (not owner.runner.idle or not retired) and monotonic() < deadline:
            owner.step()
            Event().wait(.001)
        assert retired and all(resource == work.resource for resource in retired)
        assert owner.runner.idle
        owner.committed_start()
        clock[0] += 3600
        owner.step()
        assert allocations == [work]
        assert not owner.permits_carrier("p", work.resource)
        assert not owner.snapshots()["p"]["messaging_ready"]
        assert owner.snapshots()["p"]["runtime_failure"] == "adapter_quarantined"
    finally:
        release.set()
        owner.stop()
        owner.wait()


@pytest.mark.parametrize("termination", ["quarantine", "shutdown"])
def test_terminal_runtime_does_not_begin_startup_reconciliation(termination):
    owner = ConnectionRuntime("epoch", lambda *_: Executor(),
        profiles=lambda: pytest.fail("Terminal runtime cannot scan"),
        execution=lambda: Execution.AVAILABLE, activate=lambda _: None,
        prepare=lambda: pytest.fail("Terminal runtime cannot reconcile native inventory"))
    try:
        if termination == "quarantine": owner.quarantine()
        else: owner.stop()
        owner.step()
        assert owner.runner.idle
    finally:
        owner.stop()
