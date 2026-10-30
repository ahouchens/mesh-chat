from threading import Event
from time import monotonic

from mesh_chat.connection.model import Bridge, Execution, Phase, Result
from mesh_chat.connection.runtime import ConnectionRuntime


class Executor:
    def execute(self, work, cancellation):
        return Result(work.operation, monotonic(),
                      allocated=work.resource if work.phase in {
                          Phase.GATHER_OFFER, Phase.GATHER_ANSWER, Phase.CHECKING} else None,
                      verified=work.phase is Phase.CHECKING)

    def retire(self, resource):
        pass


def runtime():
    profile = {"id": "p", "local_device_id": "local", "remote_device_id": "remote",
               "contact_id": "c", "active": True, "auto_reconnect": True,
               "peer_auto_reconnect": True, "effective": {"ready": True, "preferred": True}}
    owner = ConnectionRuntime("test-epoch", lambda *_: Executor(),
        profiles=lambda: {"profiles": [profile]}, execution=lambda: Execution.AVAILABLE,
        stats=lambda _: {"attached": True, "ice_connection_state": "connected"},
        activate=lambda _: None)
    return owner, profile


def test_driver_executes_phases_and_fences_failed_persistent_stop():
    owner, profile = runtime()
    try:
        deadline = monotonic() + 3
        while monotonic() < deadline:
            owner.step()
            if owner.snapshots()["p"]["messaging_ready"]:
                break
            Event().wait(0.005)
        assert owner.snapshots()["p"]["messaging_ready"]
        # The store still reports enabled, as if a Stop transaction failed.
        owner.fence("c")
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


def test_runtime_projection_sequence_advances_on_observations():
    owner, _ = runtime()
    try:
        owner.synchronize()
        before = owner.snapshots()["p"]["sequence"]
        owner.fence("c")
        assert owner.snapshots()["p"]["sequence"] > before
    finally:
        owner.stop()
