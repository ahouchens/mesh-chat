"""Real isolated MeshChat clients connected through one outbound-only TCP node.

The clients have AutoInterface, LAN listeners, and signed direct TCP hints
disabled. Both attach an approved Remote Connection Profile to a third
Reticulum transport process. Personal and workspace invitations, trust gates,
ratchet readiness, delivery receipts, and workspace membership then run through
the production service and LXMF implementations.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import queue
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import RNS

from mesh_chat.reticulum_config import NetworkSettings, write_config
from tools.direct_lan_harness import _call, _peer, _receive
from tools.topology_harness import free_port


def _access_point(root_value: str, port: int, commands: mp.Queue, events: mp.Queue) -> None:
    root = Path(root_value)
    write_config(
        root / "rns",
        NetworkSettings(
            nearby_discovery=False,
            help_route=True,
            tcp_listener={"host": "127.0.0.1", "port": port},
        ),
    )
    RNS.Reticulum(
        configdir=str(root / "rns"), loglevel=RNS.LOG_ERROR, logdest=lambda _: None
    )
    events.put({"event": "ready"})
    commands.get()
    RNS.Reticulum.exit_handler()


def _framed(peer: dict[str, Any], command: str, payload: dict[str, Any]) -> Any:
    return _call(
        peer["commands"],
        peer["responses"],
        "framed_command",
        response_timeout=40,
        request_id=str(uuid.uuid4()),
        service_command=command,
        payload=payload,
    )["result"]


def _wait(
    peer: dict[str, Any],
    command: str,
    payload: dict[str, Any],
    predicate: Callable[[Any], Any],
    description: str,
    timeout: float,
) -> Any:
    deadline = time.monotonic() + timeout
    latest: Any = None
    while time.monotonic() < deadline:
        latest = _framed(peer, command, payload)
        match = predicate(latest)
        if match is not None and match is not False:
            return match
        time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for {description}; latest={latest!r}")


def run(timeout: float = 70) -> dict[str, Any]:
    context = mp.get_context("spawn")
    port = free_port()
    marker = f"remote-access-{os.urandom(6).hex()}"
    peers: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="mesh-chat-remote-access-") as temporary:
        root = Path(temporary)
        relay_commands = context.Queue()
        relay_events = context.Queue()
        relay = context.Process(
            target=_access_point,
            args=(str(root / "relay"), port, relay_commands, relay_events),
            name="mesh-remote-access-node",
        )
        relay.start()
        try:
            try:
                ready = relay_events.get(timeout=20)
            except queue.Empty as exc:
                raise TimeoutError("Remote access node did not start") from exc
            if ready.get("event") != "ready":
                raise RuntimeError(f"Unexpected access-point event: {ready!r}")

            def launch(name: str) -> dict[str, Any]:
                commands = context.Queue()
                responses = context.Queue()
                process = context.Process(
                    target=_peer,
                    args=(
                        name,
                        str(root / name.lower()),
                        os.urandom(32),
                        NetworkSettings(
                            nearby_discovery=False, lan_fallback=False
                        ).to_dict(),
                        commands,
                        responses,
                    ),
                    name=f"mesh-remote-{name.lower()}",
                )
                process.start()
                peer = {"commands": commands, "responses": responses, "process": process}
                peer["ready"] = _receive(responses, "ready", 30)
                peers[name] = peer
                return peer

            alex = launch("Alex")
            alex_profile = _framed(
                alex,
                "create_manual_remote_profile",
                {
                    "label": "Isolated access point",
                    "endpoints": [{"host": "remote.test", "port": port}],
                    "propagation_node": None,
                    "allow_private": False,
                },
            )
            _wait(
                alex,
                "list_remote_profiles",
                {},
                lambda value: next(
                    (item for item in value["profiles"] if item["state"] == "connected"),
                    None,
                ),
                "Alex remote connection",
                timeout,
            )
            invitation = _call(
                alex["commands"],
                alex["responses"],
                "create_invitation",
                profile_id=alex_profile["id"],
            )["formats"]
            if not invitation["text"].startswith("MESHCHAT2:"):
                raise RuntimeError("Personal invitation was not remote profile v2")

            blair = launch("Blair")
            before_preview = _framed(blair, "list_remote_profiles", {})
            preview = _framed(
                blair, "preview_invitation", {"invitation": invitation["text"]}
            )
            after_preview = _framed(blair, "list_remote_profiles", {})
            accepted = _call(
                blair["commands"],
                blair["responses"],
                "accept_invitation",
                invitation=invitation["text"],
            )["contact"]
            _wait(
                blair,
                "list_remote_profiles",
                {},
                lambda value: next(
                    (item for item in value["profiles"] if item["state"] == "connected"),
                    None,
                ),
                "Blair remote connection",
                timeout,
            )
            pending = _call(
                alex["commands"],
                alex["responses"],
                "wait_for",
                response_timeout=timeout + 10,
                timeout=timeout,
                state="pending_request",
            )["match"]
            _call(
                alex["commands"], alex["responses"], "approve_request", contact_id=pending["id"]
            )
            _call(
                blair["commands"],
                blair["responses"],
                "wait_for",
                response_timeout=timeout + 10,
                timeout=timeout,
                state="approved",
                contact_id=accepted["id"],
            )

            direct_text = f"{marker}-personal"
            _call(
                blair["commands"],
                blair["responses"],
                "send_message",
                contact_id=accepted["id"],
                text=direct_text,
            )
            personal_received = _call(
                alex["commands"],
                alex["responses"],
                "wait_for",
                response_timeout=timeout + 10,
                timeout=timeout,
                state="inbound_chat",
                text=direct_text,
            )["match"]
            direct_delivered = _call(
                blair["commands"],
                blair["responses"],
                "wait_for",
                response_timeout=timeout + 10,
                timeout=timeout,
                state="outbound_delivered",
                text=direct_text,
            )["match"]

            op = lambda suffix: str(uuid.uuid5(uuid.NAMESPACE_URL, f"{marker}-{suffix}"))
            workspace = _framed(
                alex,
                "create_workspace",
                {
                    "name": "Remote topology",
                    "description": "Outbound access-point probe",
                    "operation_id": op("create-workspace"),
                },
            )
            workspace_invitation = _framed(
                alex,
                "create_workspace_invitation",
                {
                    "workspace_id": workspace["id"],
                    "operation_id": op("workspace-invite"),
                    "remote_profile_id": alex_profile["id"],
                },
            )
            if not workspace_invitation["text"].startswith("MESHWORKSPACE2:"):
                raise RuntimeError("Workspace invitation was not remote profile v2")
            workspace_preview = _framed(
                blair,
                "preview_workspace_invitation",
                {"invitation": workspace_invitation["text"]},
            )
            _framed(
                blair,
                "submit_workspace_join",
                {
                    "invitation": workspace_invitation["text"],
                    "operation_id": op("workspace-join"),
                },
            )
            request = _wait(
                alex,
                "workspace_snapshot",
                {},
                lambda snap: next(
                    (
                        item
                        for item in snap.get("workspace_join_requests", [])
                        if item.get("workspace_id") == workspace["id"]
                        and item.get("state") == "pending"
                    ),
                    None,
                ),
                "workspace join request",
                timeout,
            )
            acknowledged = _wait(
                blair, "workspace_snapshot", {},
                lambda snap: next((
                    item for item in snap.get("workspaces", [])
                    if item.get("id") == workspace["id"]
                    and item.get("state") == "joining"
                    and item.get("join_acknowledged") is True
                ), None),
                "authenticated workspace join receipt before approval", timeout,
            )
            _framed(
                alex,
                "approve_workspace_join",
                {
                    "workspace_id": workspace["id"],
                    "request_id": request["id"],
                    "operation_id": op("approve-workspace-join"),
                },
            )
            joined = _wait(
                blair,
                "workspace_snapshot",
                {},
                lambda snap: next(
                    (
                        item
                        for item in snap.get("workspaces", [])
                        if item.get("id") == workspace["id"]
                        and item.get("state") == "active"
                    ),
                    None,
                ),
                "active workspace",
                timeout,
            )
            workspace_text = f"{marker}-workspace"
            sent = _framed(
                alex,
                "send_workspace_message",
                {
                    "workspace_id": workspace["id"],
                    "channel_id": workspace["general_channel_id"],
                    "text": workspace_text,
                    "event_id": op("workspace-event"),
                    "operation_id": op("workspace-message"),
                },
            )
            received = _wait(
                blair,
                "list_workspace_messages",
                {
                    "workspace_id": workspace["id"],
                    "channel_id": workspace["general_channel_id"],
                    "limit": 50,
                },
                lambda page: next(
                    (item for item in page.get("messages", []) if item.get("id") == sent["id"]),
                    None,
                ),
                "workspace message",
                timeout,
            )
            owner_state = _framed(alex, "workspace_snapshot", {})
            owner_workspace = next(
                item for item in owner_state["workspaces"] if item["id"] == workspace["id"]
            )
            remote_member_id = next(
                item["id"]
                for item in owner_workspace["members"]
                if item["id"] != owner_workspace["local_member_id"]
            )
            direct = _framed(
                alex,
                "open_workspace_direct",
                {
                    "workspace_id": workspace["id"],
                    "member_id": remote_member_id,
                    "operation_id": op("open-workspace-direct"),
                },
            )
            direct_text = f"{marker}-workspace-direct"
            direct_sent = _framed(
                alex,
                "send_workspace_direct_message",
                {
                    "workspace_id": workspace["id"],
                    "conversation_id": direct["id"],
                    "text": direct_text,
                    "event_id": op("workspace-direct-event"),
                    "operation_id": op("workspace-direct-message"),
                },
            )
            _wait(
                blair,
                "workspace_snapshot",
                {},
                lambda snap: next(
                    (
                        item
                        for item in snap.get("workspace_directs", [])
                        if item.get("id") == direct["id"]
                    ),
                    None,
                ),
                "workspace direct conversation",
                timeout,
            )
            direct_received = _wait(
                blair,
                "list_workspace_direct_messages",
                {
                    "workspace_id": workspace["id"],
                    "conversation_id": direct["id"],
                    "limit": 50,
                },
                lambda page: next(
                    (
                        item
                        for item in page.get("messages", [])
                        if item.get("id") == direct_sent["id"]
                    ),
                    None,
                ),
                "workspace direct message",
                timeout,
            )
            alex_snapshot = _call(alex["commands"], alex["responses"], "snapshot")["snapshot"]
            blair_snapshot = _call(blair["commands"], blair["responses"], "snapshot")["snapshot"]
            return {
                "relay_only": all(
                    not item["ready"]["settings"]["nearby_discovery"]
                    and not item["ready"]["settings"]["lan_fallback"]
                    for item in (alex, blair)
                ),
                "preview_did_not_connect": before_preview["profiles"] == after_preview["profiles"] == [],
                "personal_v2": invitation["text"].startswith("MESHCHAT2:"),
                "personal_consent_disclosed": bool(preview.get("requires_network_consent")),
                "personal_received": personal_received["id"] == direct_delivered["id"],
                "personal_delivered": direct_delivered["state"] == "delivered",
                "workspace_v2": workspace_invitation["text"].startswith("MESHWORKSPACE2:"),
                "workspace_consent_disclosed": bool(workspace_preview.get("requires_network_consent")),
                "workspace_joined": joined["state"] == "active",
                "workspace_join_acknowledged": acknowledged["join_acknowledged"] is True,
                "workspace_received": received["id"] == sent["id"],
                "workspace_direct_received": direct_received["id"] == direct_sent["id"],
                "alex_route": next(item["route_kind"] for item in alex_snapshot["contacts"] if item["id"] == pending["id"]),
                "blair_route": next(item["route_kind"] for item in blair_snapshot["contacts"] if item["id"] == accepted["id"]),
            }
        finally:
            for peer in peers.values():
                if peer["process"].is_alive():
                    try:
                        _call(peer["commands"], peer["responses"], "stop", response_timeout=8)
                    except Exception:
                        pass
                peer["process"].join(timeout=8)
                if peer["process"].is_alive():
                    peer["process"].terminate()
                    peer["process"].join(timeout=4)
            if relay.is_alive():
                relay_commands.put({"action": "stop"})
                relay.join(timeout=8)
            if relay.is_alive():
                relay.terminate()
                relay.join(timeout=4)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=70)
    args = parser.parse_args()
    result = run(args.timeout)
    print(json.dumps(result, indent=2))
    expected = {
        "relay_only",
        "preview_did_not_connect",
        "personal_v2",
        "personal_consent_disclosed",
        "personal_received",
        "personal_delivered",
        "workspace_v2",
        "workspace_consent_disclosed",
        "workspace_joined",
        "workspace_join_acknowledged",
        "workspace_received",
        "workspace_direct_received",
    }
    return 0 if all(result.get(key) is True for key in expected) and result.get("alex_route") == result.get("blair_route") == "remote" else 1


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
