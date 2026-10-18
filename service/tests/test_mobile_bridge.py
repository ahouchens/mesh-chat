from __future__ import annotations

import base64
import json
import os
import sqlite3
import subprocess
import sys
import textwrap
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import RNS

from mesh_chat import mobile_bridge
from mesh_chat.invitations import create_invitation
from mesh_chat.network import EmbeddedRuntimeTermination, install_embedded_runtime_guards
from mesh_chat.vault import VaultStore, protect_workspace


def test_mobile_protection_rejects_desktop_runtime(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="app-private mobile profile"):
        protect_workspace(tmp_path / "profile", native_mobile_protection="android")


def test_mobile_bridge_rejects_unknown_initialization_fields() -> None:
    response = json.loads(mobile_bridge.initialize(json.dumps({"unexpected": True})))
    assert response == {"ok": False, "error": {"code": "invalid_request"}}


def test_mobile_bridge_requires_initialization() -> None:
    mobile_bridge.shutdown()
    response = json.loads(
        mobile_bridge.command(json.dumps({"command": "snapshot", "payload": {}}))
    )
    assert response == {"ok": False, "error": {"code": "invalid_request"}}


def test_only_public_document_commands_receive_larger_mobile_envelopes(monkeypatch):
    calls = []
    class Service:
        def dispatch(self, request):
            calls.append(request)
            return {"ok":True,"result":{}}, False
    monkeypatch.setattr(mobile_bridge,"_service",Service())
    document = "x"*(80*1024)
    for command in ("preview_direct_connection","prepare_direct_answer","prepare_direct_ready",
                    "accept_direct_ready","connect_direct_setup"):
        assert json.loads(mobile_bridge.command(json.dumps({"command":command,"payload":{"document":document}})))["ok"]
    count = len(calls)
    assert not json.loads(mobile_bridge.command(json.dumps({"command":"snapshot","payload":{"document":document}})))["ok"]
    assert not json.loads(mobile_bridge.direct_exchange(json.dumps({"responses":[document]})))["ok"]
    assert not json.loads(mobile_bridge.command(json.dumps({"command":"preview_direct_connection",
        "payload":{"document":"x"*(2*1024*1024)}})))["ok"]
    assert len(calls) == count


def test_mobile_workspace_preview_and_submit_share_invitation_size_limit(monkeypatch):
    dispatched = []

    class Service:
        def dispatch(self, request):
            dispatched.append(request)
            return {"ok": True, "result": {}}, False

    monkeypatch.setattr(mobile_bridge, "_service", Service())
    preview = {
        "command": "preview_workspace_invitation",
        "payload": {"invitation": "MESHWORKSPACE4:"},
    }
    overhead = len(json.dumps(preview, separators=(",", ":")).encode("utf-8"))
    invitation = "MESHWORKSPACE4:" + "a" * (64 * 1024 - overhead)
    preview["payload"]["invitation"] = invitation
    submit = {
        "command": "submit_workspace_join",
        "payload": {"invitation": invitation, "operation_id": str(uuid.uuid4())},
    }
    preview_raw = json.dumps(preview, separators=(",", ":"))
    submit_raw = json.dumps(submit, separators=(",", ":"))
    assert len(preview_raw.encode("utf-8")) == 64 * 1024
    assert len(submit_raw.encode("utf-8")) > 64 * 1024

    assert json.loads(mobile_bridge.command(preview_raw))["ok"]
    assert json.loads(mobile_bridge.command(submit_raw))["ok"]
    assert [request["command"] for request in dispatched] == [
        "preview_workspace_invitation", "submit_workspace_join",
    ]
    assert dispatched[0]["payload"] == preview["payload"]
    assert dispatched[1]["payload"] == submit["payload"]


@pytest.mark.parametrize(("command", "maximum"), [
    ("preview_direct_connection", 2 * 1024 * 1024),
    ("prepare_direct_answer", 2 * 1024 * 1024),
    ("prepare_direct_ready", 2 * 1024 * 1024),
    ("accept_direct_ready", 2 * 1024 * 1024),
    ("connect_direct_setup", 2 * 1024 * 1024),
    ("preview_workspace_device_link", 700 * 1024),
    ("submit_workspace_device_link", 700 * 1024),
    ("preview_workspace_invitation", 600 * 1024),
    ("submit_workspace_join", 600 * 1024),
    ("create_connection_reply", 600 * 1024),
    ("preview_connection_reply", 41 * 1024),
    ("connect_using_reply", 41 * 1024),
    ("preview_route_update", 25 * 1024),
    ("apply_route_update", 25 * 1024),
    ("send_message", 32 * 1024),
])
def test_mobile_command_matches_native_payload_bounds(monkeypatch, command, maximum):
    dispatched = []

    class Service:
        def dispatch(self, request):
            dispatched.append(request)
            return {"ok": True, "result": {}}, False

    monkeypatch.setattr(mobile_bridge, "_service", Service())
    # This boundary test isolates the bridge from the service's schema checks.
    # Non-ASCII text ensures limits apply to UTF-8 bytes, not character counts.
    overhead = len(json.dumps({"document": ""}, separators=(",", ":")).encode("utf-8"))
    padding_bytes = maximum - overhead
    payload = {"document": "é" * (padding_bytes // 2) + "x" * (padding_bytes % 2)}
    assert len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) == maximum
    request = {"command": command, "payload": payload}
    raw = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
    assert len(raw.encode("utf-8")) > maximum
    assert json.loads(mobile_bridge.command(raw))["ok"]

    payload["document"] += "x"
    oversized = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
    assert json.loads(mobile_bridge.command(oversized)) == {
        "ok": False, "error": {"code": "invalid_request"},
    }
    assert json.loads(mobile_bridge.command(raw + " " * 1024)) == {
        "ok": False, "error": {"code": "invalid_request"},
    }
    assert len(dispatched) == 1


def test_mobile_bridge_command_does_not_block_worker_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A service command may synchronously wait for an RNS callback thread."""

    callback_finished = threading.Event()

    class CallbackService:
        def dispatch(self, _request: dict[str, object]) -> tuple[dict[str, object], bool]:
            def callback() -> None:
                mobile_bridge._emit({"type": "event", "event": "state_changed"})
                callback_finished.set()

            worker = threading.Thread(target=callback)
            worker.start()
            assert callback_finished.wait(1), "bridge event callback was lock-blocked"
            worker.join(timeout=1)
            return {"ok": True, "result": {"completed": True}}, False

    monkeypatch.setattr(mobile_bridge, "_service", CallbackService())
    response = json.loads(
        mobile_bridge.command(json.dumps({"command": "snapshot", "payload": {}}))
    )

    assert response == {"ok": True, "result": {"completed": True}}
    assert json.loads(mobile_bridge.drain_events())["result"] == [
        {"type": "event", "event": "state_changed"}
    ]


def test_mobile_bridge_persists_invalidation_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OverflowService:
        def __init__(self) -> None:
            self.overflows = 0

        def _mark_workspace_invalidation_overflow(self) -> None:
            self.overflows += 1

    service = OverflowService()
    monkeypatch.setattr(mobile_bridge, "_service", service)
    monkeypatch.setattr(mobile_bridge, "_events", mobile_bridge.deque(maxlen=2))
    monkeypatch.setattr(mobile_bridge, "_event_overflow", False)

    mobile_bridge._emit({"event": "first"})
    mobile_bridge._emit({"event": "second"})
    mobile_bridge._emit({"event": "third"})

    assert service.overflows == 1
    assert json.loads(mobile_bridge.drain_events())["result"] == [
        {
            "type": "event",
            "event": "state_changed",
            "resource_kind": "event_overflow",
            "overflow": True,
        },
        {"event": "third"},
    ]
    assert json.loads(mobile_bridge.drain_events())["result"] == []


def test_mobile_bridge_preserves_direct_send_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Android raw-JSON boundary must not drop direct-message fields."""

    dispatched: list[dict[str, object]] = []

    class CapturingService:
        def dispatch(self, request: dict[str, object]) -> tuple[dict[str, object], bool]:
            dispatched.append(request)
            payload = request["payload"]
            assert isinstance(payload, dict)
            return {
                "ok": True,
                "result": {
                    "contact_id": payload["contact_id"],
                    "text": payload["text"],
                },
            }, False

    monkeypatch.setattr(mobile_bridge, "_service", CapturingService())
    response = json.loads(
        mobile_bridge.command(
            json.dumps(
                {
                    "command": "send_message",
                    "payload": {
                        "contact_id": "phone-contact",
                        "text": "Message from Android",
                    },
                }
            )
        )
    )

    assert response == {
        "ok": True,
        "result": {
            "contact_id": "phone-contact",
            "text": "Message from Android",
        },
    }
    assert len(dispatched) == 1
    assert dispatched[0]["v"] == mobile_bridge.IPC_VERSION
    assert uuid.UUID(str(dispatched[0]["id"]))
    assert dispatched[0]["command"] == "send_message"
    assert dispatched[0]["payload"] == {
        "contact_id": "phone-contact",
        "text": "Message from Android",
    }


def test_embedded_runtime_guard_isolates_interface_panics() -> None:
    fake_module = SimpleNamespace()

    class FakeInterface:
        detached = False

        def detach(self) -> None:
            self.detached = True

    failed_interface = FakeInterface()

    class FakeTransport:
        interfaces = []

        @classmethod
        def remove_interface(cls, interface: FakeInterface) -> None:
            cls.interfaces.remove(interface)

    class FakeReticulum:
        def _synthesize_interface(self) -> None:
            FakeTransport.interfaces.append(failed_interface)
            fake_module.panic()

    fake_module.Reticulum = FakeReticulum
    fake_module.Transport = FakeTransport
    fake_module.panic = lambda: None
    fake_module.exit = lambda _code=0: None
    install_embedded_runtime_guards(fake_module)

    instance = FakeReticulum()
    assert instance._synthesize_interface() is None
    assert instance._mesh_chat_interface_start_failed is True
    assert failed_interface.detached is True
    assert FakeTransport.interfaces == []
    with pytest.raises(EmbeddedRuntimeTermination, match="reticulum_exit_blocked"):
        fake_module.exit(255)


def test_mobile_vault_round_trip_is_authenticated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "android")
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))
    profile = tmp_path / "files" / "mesh-chat" / "profile-v1"
    key = bytes(range(32))

    with VaultStore(profile, key, native_mobile_protection="android") as store:
        store.put("contact", "alice", {"display_name": "Alice", "secret": "not-plaintext"})
        assert store.get("contact", "alice") == {
            "display_name": "Alice",
            "secret": "not-plaintext",
        }

    with sqlite3.connect(profile / "mesh-chat.vault") as database:
        sealed = database.execute(
            "SELECT sealed FROM records WHERE kind='contact' AND record_id='alice'"
        ).fetchone()[0]
    assert sealed.startswith(b"\x02")
    assert b"not-plaintext" not in sealed

    with VaultStore(profile, key, native_mobile_protection="android") as reopened:
        assert reopened.get("contact", "alice")["display_name"] == "Alice"


def test_mobile_bridge_initializes_inside_private_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mobile_bridge.shutdown()
    monkeypatch.setattr(sys, "platform", "android")
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))
    profile = tmp_path / "files" / "mesh-chat" / "profile-v1"
    response = json.loads(
        mobile_bridge.initialize(
            json.dumps(
                {
                    "profile_dir": str(profile),
                    "vault_key": base64.b64encode(bytes(range(32))).decode("ascii"),
                    "display_name": None,
                    "platform": "android",
                }
            )
        )
    )
    try:
        assert response["ok"] is True
        assert response["result"]["profile"] is None
        invitation = create_invitation(RNS.Identity(), "Phone sender")["text"]
        prefix, token = invitation.split(":", 1)
        preview = json.loads(
            mobile_bridge.command(
                json.dumps(
                    {
                        "command": "preview_invitation",
                        "payload": {"invitation": f"{prefix}:\n{token}"},
                    }
                )
            )
        )
        assert preview["ok"] is True
        assert preview["result"]["display_name"] == "Phone sender"
    finally:
        mobile_bridge.shutdown()


def test_mobile_profile_join_and_restart_survive_interface_failure(tmp_path: Path) -> None:
    """Exercise the profile-created crash path in isolated Python processes."""

    probe = textwrap.dedent(
        """
        import base64
        import json
        import os
        import sys
        from concurrent.futures import ThreadPoolExecutor
        from pathlib import Path

        import RNS
        from RNS.Interfaces.AutoInterface import AutoInterface
        from mesh_chat import mobile_bridge
        from mesh_chat.invitations import create_invitation

        root = Path(os.environ["MESH_CHAT_PROBE_HOME"])
        profile = root / "files" / "mesh-chat" / "profile-v1"
        profile.mkdir(parents=True, exist_ok=True)
        Path.home = classmethod(lambda _cls: root)
        sys.platform = "android"

        def fail_interface(_self):
            raise OSError("synthetic mobile interface failure")

        AutoInterface.final_init = fail_interface
        request = json.dumps({
            "profile_dir": str(profile),
            "vault_key": base64.b64encode(bytes(range(32))).decode("ascii"),
            "display_name": None,
            "platform": "android",
        })

        with ThreadPoolExecutor(max_workers=1) as executor:
            initialized = json.loads(executor.submit(mobile_bridge.initialize, request).result())
            assert initialized["ok"] is True, initialized
            if os.environ["MESH_CHAT_PROBE_MODE"] == "create":
                created = json.loads(executor.submit(
                    mobile_bridge.command,
                    json.dumps({"command": "create_profile", "payload": {"display_name": "Phone"}}),
                ).result())
                assert created["ok"] is True, created
                invitation = create_invitation(RNS.Identity(), "Desktop peer")["text"]
                accepted = json.loads(executor.submit(
                    mobile_bridge.command,
                    json.dumps({"command": "accept_invitation", "payload": {"invitation": invitation}}),
                ).result())
                assert accepted["ok"] is True, accepted
                # Retrying the interrupted two-step onboarding is idempotent.
                retried = json.loads(executor.submit(
                    mobile_bridge.command,
                    json.dumps({"command": "create_profile", "payload": {"display_name": "Phone"}}),
                ).result())
                assert retried["ok"] is True, retried
            snapshot = json.loads(executor.submit(
                mobile_bridge.command,
                json.dumps({"command": "snapshot", "payload": {}}),
            ).result())
            assert snapshot["ok"] is True, snapshot
            assert snapshot["result"]["profile"]["display_name"] == "Phone"
            assert len(snapshot["result"]["contacts"]) == 1
        """
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    environment["MESH_CHAT_PROBE_HOME"] = str(tmp_path)
    for mode in ("create", "reopen"):
        environment["MESH_CHAT_PROBE_MODE"] = mode
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            env=environment,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout
