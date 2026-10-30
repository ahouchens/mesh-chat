from threading import Event
from time import monotonic

import pytest

from mesh_chat.connection.model import Bridge, Execution, Health, Phase, Result
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
