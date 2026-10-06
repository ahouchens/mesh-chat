"""Real two-process direct-LAN invitation probe.

The two peers use independent profiles and have AutoInterface disabled. The
inviter's app-owned TCP listener is advertised as a signed invitation hint,
and the joining service must import that hint before any route can exist.

Loopback is used as the test-only LAN address so the harness is deterministic
on development machines and CI runners with no physical network adapter. The
production listener, invitation validation, TCP client attachment, RNS/LXMF
delivery, contact policy and encrypted stores are otherwise exercised intact.
"""

from __future__ import annotations

import argparse
import io
import json
import multiprocessing as mp
import os
import queue
import tempfile
import time
from pathlib import Path
from typing import Any

from mesh_chat.reticulum_config import NetworkSettings
from mesh_chat.ipc import encode_frame, read_frame
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore


def _peer(
    name: str,
    root_value: str,
    key: bytes,
    settings_value: dict[str, Any],
    commands: mp.Queue,
    responses: mp.Queue,
) -> None:
    # RNS normally filters loopback from LAN advertisements and admissions.
    # Keep that production behavior, but substitute loopback inside this
    # isolated topology so the test never depends on the host's Wi-Fi state.
    from mesh_chat import network as network_module

    network_module.lan_ipv4_addresses = lambda _rns=network_module.RNS, limit=3: [
        "127.0.0.1"
    ][:limit]
    network_module._source_is_on_lan = (
        lambda source, _rns=network_module.RNS: source in {"127.0.0.1", "::1"}
    )
    inbound_diagnostics: list[dict[str, Any]] = []
    original_network_inbound = network_module.ReticulumNetwork._on_inbound

    def traced_network_inbound(network: Any, message: Any) -> None:
        from mesh_chat.app_protocol import conversation_id, parse_payload
        from mesh_chat.invitations import verify_invitation

        diagnostic: dict[str, Any] = {
            "signature_validated": bool(getattr(message, "signature_validated", False)),
            "has_source": getattr(message, "source_hash", None) is not None,
            "has_destination": getattr(message, "destination_hash", None) is not None,
            "destination_matches_local": (
                getattr(message, "destination_hash", None)
                == network.delivery_destination.hash
            ),
        }
        try:
            app = parse_payload(message)
            diagnostic["payload_parsed"] = True
            diagnostic["kind"] = app.kind.value
            invitation = verify_invitation(app.invitation)
            diagnostic["invitation_verified"] = True
            diagnostic["source_matches_invitation"] = (
                getattr(message, "source_hash", None) == invitation.destination_hash
            )
            diagnostic["conversation_matches"] = app.conversation_id == conversation_id(
                network.delivery_destination.hash, invitation.destination_hash
            )
            identity = network_module.RNS.Identity(create_keys=False)
            loaded = identity.load_public_key(invitation.public_identity)
            packed = bytes(getattr(message, "packed", b""))
            prefix_length = 2 * network_module.LXMF.LXMessage.DESTINATION_LENGTH
            signature_length = network_module.LXMF.LXMessage.SIGNATURE_LENGTH
            packed_payload = packed[prefix_length + signature_length :]
            hashed_part = (
                bytes(message.destination_hash) + bytes(message.source_hash) + packed_payload
            )
            signed_part = hashed_part + network_module.RNS.Identity.full_hash(hashed_part)
            diagnostic["signature_valid_with_invitation_identity"] = bool(
                loaded and identity.validate(message.signature, signed_part)
            )
        except Exception as exc:
            diagnostic["precheck_error"] = f"{type(exc).__name__}: {exc}"
        inbound_diagnostics.append(diagnostic)
        original_network_inbound(network, message)

    network_module.ReticulumNetwork._on_inbound = traced_network_inbound

    root = Path(root_value)
    store = VaultStore(root, key, allow_unprotected_for_tests=True)
    store.put("settings", "network", settings_value)
    service = MeshChatService(store, root, lambda _event: None)

    def respond(action: str, **value: Any) -> None:
        responses.put({"ok": True, "action": action, **value})

    try:
        profile = service.create_profile(name)
        respond(
            "ready",
            profile=profile,
            settings=service.settings.to_dict(),
            network=service.snapshot()["network"],
        )
        running = True
        while running:
            command = commands.get()
            action = command.get("action")
            try:
                if action == "create_invitation":
                    formats = service.invitation()
                    respond(action, formats=formats)
                elif action == "accept_invitation":
                    contact = service.accept_invitation(command["invitation"])
                    respond(action, contact=contact)
                elif action == "approve_request":
                    contact = service.approve_request(command["contact_id"])
                    respond(action, contact=contact)
                elif action == "send_message":
                    message = service.send_message(command["contact_id"], command["text"])
                    respond(action, message=message)
                elif action == "framed_command":
                    # Exercise the same validated command envelope used by the
                    # desktop sidecar instead of calling the service method
                    # directly. Round-trip both sides through the production
                    # frame codec so this probe catches dispatch/serialization
                    # regressions as well as transport failures.
                    request_id = command["request_id"]
                    request = read_frame(
                        io.BytesIO(
                            encode_frame(
                                {
                                    "v": 1,
                                    "id": request_id,
                                    "command": command["service_command"],
                                    "payload": command["payload"],
                                }
                            )
                        )
                    )
                    dispatch_result, should_stop = service.dispatch(request)
                    if should_stop:
                        raise RuntimeError("Harness command unexpectedly stopped the service")
                    response = read_frame(
                        io.BytesIO(
                            encode_frame(
                                {
                                    "type": "response",
                                    "id": request_id,
                                    **dispatch_result,
                                }
                            )
                        )
                    )
                    respond(action, frame=response, result=response.get("result"))
                elif action == "send_group_message":
                    message = service.send_group_message(command["group_id"], command["text"])
                    respond(action, message=message)
                elif action == "create_group":
                    group = service.create_group(
                        command["title"], [command["contact_id"]], "members"
                    )
                    respond(action, group=group)
                elif action == "accept_group_invitation":
                    group = service.accept_group_invitation(command["invitation_id"])
                    respond(action, group=group)
                elif action == "snapshot":
                    respond(
                        action,
                        snapshot=service.snapshot(),
                        inbound_diagnostics=list(inbound_diagnostics),
                    )
                elif action == "wait_for":
                    deadline = time.monotonic() + float(command.get("timeout", 45))
                    match: dict[str, Any] | None = None
                    wanted = command["state"]
                    while time.monotonic() < deadline and match is None:
                        snapshot = service.snapshot()
                        if wanted == "pending_request":
                            match = next(
                                (
                                    contact
                                    for contact in snapshot["contacts"]
                                    if contact["trust"] == "pending_request"
                                ),
                                None,
                            )
                        elif wanted == "approved":
                            contact_id = command.get("contact_id")
                            match = next(
                                (
                                    contact
                                    for contact in snapshot["contacts"]
                                    if contact["trust"] in {"approved", "verified"}
                                    and (contact_id is None or contact["id"] == contact_id)
                                ),
                                None,
                            )
                        elif wanted in {"inbound_chat", "outbound_delivered"}:
                            direction = "inbound" if wanted == "inbound_chat" else "outbound"
                            expected_state = None if wanted == "inbound_chat" else "delivered"
                            match = next(
                                (
                                    message
                                    for message in snapshot["messages"]
                                    if message["direction"] == direction
                                    and message["text"] == command["text"]
                                    and (
                                        expected_state is None
                                        or message["state"] == expected_state
                                    )
                                ),
                                None,
                            )
                        elif wanted == "group_invitation":
                            match = next(
                                (
                                    invitation
                                    for invitation in snapshot.get("group_invitations", [])
                                    if invitation["title"] == command["title"]
                                ),
                                None,
                            )
                        elif wanted == "group_invite_ready":
                            group_id = command["group_id"]
                            group = next(
                                (
                                    item
                                    for item in snapshot.get("groups", [])
                                    if item["id"] == group_id
                                ),
                                None,
                            )
                            if group is not None:
                                match = next(
                                    (
                                        member
                                        for member in group["members"]
                                        if member.get("status") == "invited"
                                        and member.get("invite_delivery_state") == "delivered"
                                    ),
                                    None,
                                )
                        elif wanted == "group_active":
                            group_id = command["group_id"]
                            match = next(
                                (
                                    group
                                    for group in snapshot.get("groups", [])
                                    if group["id"] == group_id
                                    and group.get("status") == "active"
                                    and sum(
                                        member.get("status") == "active"
                                        for member in group.get("members", [])
                                    ) >= 2
                                ),
                                None,
                            )
                        elif wanted in {"group_inbound", "group_outbound_delivered"}:
                            direction = (
                                "inbound" if wanted == "group_inbound" else "outbound"
                            )
                            match = next(
                                (
                                    message
                                    for message in snapshot.get("group_messages", [])
                                    if message["direction"] == direction
                                    and message["group_id"] == command["group_id"]
                                    and message["text"] == command["text"]
                                    and (
                                        command.get("message_id") is None
                                        or message["id"] == command["message_id"]
                                    )
                                    and (
                                        wanted == "group_inbound"
                                        or (
                                            message.get("delivery_summary")
                                            == {
                                                "total": 1,
                                                "delivered": 1,
                                                "pending": 0,
                                                "failed": 0,
                                                "expired": 0,
                                            }
                                            and message.get("deliveries")
                                            == [
                                                {
                                                    "recipient_destination": command[
                                                        "recipient_destination"
                                                    ],
                                                    "recipient_display_name": command[
                                                        "recipient_display_name"
                                                    ],
                                                    "state": "delivered",
                                                }
                                            ]
                                        )
                                    )
                                ),
                                None,
                            )
                        else:
                            raise ValueError(f"Unsupported wait state: {wanted}")
                        if match is None:
                            time.sleep(0.2)
                    if match is None:
                        raise TimeoutError(
                            f"Timed out waiting for {wanted}; snapshot={snapshot!r}"
                        )
                    respond(action, state=wanted, match=match)
                elif action == "stop":
                    respond(action)
                    running = False
                else:
                    raise ValueError(f"Unsupported harness action: {action}")
            except Exception as exc:
                responses.put(
                    {
                        "ok": False,
                        "action": action,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
    except Exception as exc:
        responses.put(
            {
                "ok": False,
                "action": "startup",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
    finally:
        service.close()


def _receive(responses: mp.Queue, expected: str, timeout: float) -> dict[str, Any]:
    try:
        response = responses.get(timeout=timeout)
    except queue.Empty as exc:
        raise TimeoutError(f"Peer did not answer {expected}") from exc
    if response.get("action") != expected:
        raise RuntimeError(f"Expected {expected}, received {response!r}")
    if not response.get("ok"):
        raise RuntimeError(response.get("error", f"{expected} failed"))
    return response


def _call(
    commands: mp.Queue,
    responses: mp.Queue,
    action: str,
    *,
    response_timeout: float = 60,
    **payload: Any,
) -> dict[str, Any]:
    commands.put({"action": action, **payload})
    return _receive(responses, action, response_timeout)


def run(
    timeout: float = 60,
    *,
    joiner_lan_fallback: bool = True,
) -> dict[str, Any]:
    """Run the signed-hint-only contact and message flow."""

    context = mp.get_context("spawn")
    marker = f"direct-lan-{os.urandom(8).hex()}"
    with tempfile.TemporaryDirectory(prefix="mesh-chat-direct-lan-") as temporary:
        root = Path(temporary)
        peers: dict[str, dict[str, Any]] = {}

        def launch(name: str, settings: NetworkSettings) -> dict[str, Any]:
            commands = context.Queue()
            responses = context.Queue()
            process = context.Process(
                target=_peer,
                args=(
                    name,
                    str(root / name.lower()),
                    os.urandom(32),
                    settings.to_dict(),
                    commands,
                    responses,
                ),
                name=f"mesh-direct-lan-{name.lower()}",
            )
            process.start()
            peer = {"commands": commands, "responses": responses, "process": process}
            peers[name] = peer
            peer["ready"] = _receive(responses, "ready", 30)
            return peer

        try:
            inviter = launch(
                "Alex",
                NetworkSettings(nearby_discovery=False, lan_fallback=True),
            )
            invitation_result = _call(
                inviter["commands"], inviter["responses"], "create_invitation"
            )
            formats = invitation_result["formats"]
            invitation_value = json.loads(formats["file"])
            hints = invitation_value["hints"]
            if len(hints) != 1 or hints[0]["type"] != "tcp":
                raise RuntimeError(f"Automatic invitation did not contain one TCP hint: {hints!r}")

            joiner = launch(
                "Blair",
                # Both real devices advertise a signed return route. The
                # inviter must apply Blair's reverse hint while approving the
                # request, which is the path exercised by desktop + phone.
                NetworkSettings(
                    nearby_discovery=False,
                    lan_fallback=joiner_lan_fallback,
                ),
            )
            accepted = _call(
                joiner["commands"],
                joiner["responses"],
                "accept_invitation",
                invitation=formats["text"],
            )
            joiner_contact = accepted["contact"]

            try:
                pending = _call(
                    inviter["commands"],
                    inviter["responses"],
                    "wait_for",
                    response_timeout=timeout + 10,
                    timeout=timeout,
                    state="pending_request",
                )["match"]
            except Exception as exc:
                inviter_diagnostic = _call(
                    inviter["commands"], inviter["responses"], "snapshot"
                )
                joiner_diagnostic = _call(
                    joiner["commands"], joiner["responses"], "snapshot"
                )
                raise RuntimeError(
                    "Contact request did not arrive; "
                    f"inviter={inviter_diagnostic!r}; joiner={joiner_diagnostic!r}"
                ) from exc
            approval_started = time.monotonic()
            _call(
                inviter["commands"],
                inviter["responses"],
                "approve_request",
                contact_id=pending["id"],
            )
            approval_elapsed = time.monotonic() - approval_started
            approved = _call(
                joiner["commands"],
                joiner["responses"],
                "wait_for",
                response_timeout=timeout + 10,
                timeout=timeout,
                state="approved",
                contact_id=joiner_contact["id"],
            )["match"]

            # Match the physical Android report exactly. The outbound-only
            # joiner sends the first chat and waits for its application
            # receipt. Only then does the desktop inviter reply over that same
            # established full-duplex connection. Both sends use framed
            # dispatch instead of the harness' direct method shortcuts.
            phone_first_marker = f"{marker}-phone-first"
            phone_first_started = time.monotonic()
            phone_first_command = _call(
                joiner["commands"],
                joiner["responses"],
                "framed_command",
                response_timeout=20,
                request_id=f"{marker}-phone-command",
                service_command="send_message",
                payload={"contact_id": approved["id"], "text": phone_first_marker},
            )
            phone_first_elapsed = time.monotonic() - phone_first_started
            phone_first_received = _call(
                inviter["commands"],
                inviter["responses"],
                "wait_for",
                response_timeout=timeout + 10,
                timeout=timeout,
                state="inbound_chat",
                text=phone_first_marker,
            )["match"]
            phone_first_delivered = _call(
                joiner["commands"],
                joiner["responses"],
                "wait_for",
                response_timeout=timeout + 10,
                timeout=timeout,
                state="outbound_delivered",
                text=phone_first_marker,
            )["match"]

            desktop_reply_marker = f"{marker}-desktop-reply"
            desktop_reply_started = time.monotonic()
            desktop_reply_command = _call(
                inviter["commands"],
                inviter["responses"],
                "framed_command",
                response_timeout=20,
                request_id=f"{marker}-desktop-command",
                service_command="send_message",
                payload={"contact_id": pending["id"], "text": desktop_reply_marker},
            )
            desktop_reply_elapsed = time.monotonic() - desktop_reply_started
            desktop_reply_received = _call(
                joiner["commands"],
                joiner["responses"],
                "wait_for",
                response_timeout=timeout + 10,
                timeout=timeout,
                state="inbound_chat",
                text=desktop_reply_marker,
            )["match"]
            desktop_reply_delivered = _call(
                inviter["commands"],
                inviter["responses"],
                "wait_for",
                response_timeout=timeout + 10,
                timeout=timeout,
                state="outbound_delivered",
                text=desktop_reply_marker,
            )["match"]

            group_title = f"Harness group {marker[-8:]}"
            created_group = _call(
                inviter["commands"],
                inviter["responses"],
                "create_group",
                contact_id=pending["id"],
                title=group_title,
            )["group"]
            incoming_group_invitation = _call(
                joiner["commands"],
                joiner["responses"],
                "wait_for",
                response_timeout=timeout + 10,
                timeout=timeout,
                state="group_invitation",
                title=group_title,
            )["match"]
            invite_ready = _call(
                inviter["commands"],
                inviter["responses"],
                "wait_for",
                response_timeout=timeout + 10,
                timeout=timeout,
                state="group_invite_ready",
                group_id=created_group["id"],
            )["match"]
            _call(
                joiner["commands"],
                joiner["responses"],
                "accept_group_invitation",
                invitation_id=incoming_group_invitation["id"],
            )
            joined_group = _call(
                joiner["commands"],
                joiner["responses"],
                "wait_for",
                response_timeout=timeout + 10,
                timeout=timeout,
                state="group_active",
                group_id=created_group["id"],
            )["match"]

            group_marker = f"{marker}-group"
            sent_group_message = _call(
                inviter["commands"],
                inviter["responses"],
                "send_group_message",
                group_id=created_group["id"],
                text=group_marker,
            )["message"]
            group_received = _call(
                joiner["commands"],
                joiner["responses"],
                "wait_for",
                response_timeout=timeout + 10,
                timeout=timeout,
                state="group_inbound",
                group_id=created_group["id"],
                text=group_marker,
                message_id=sent_group_message["id"],
            )["match"]
            group_delivered = _call(
                inviter["commands"],
                inviter["responses"],
                "wait_for",
                response_timeout=timeout + 10,
                timeout=timeout,
                state="group_outbound_delivered",
                group_id=created_group["id"],
                text=group_marker,
                message_id=sent_group_message["id"],
                recipient_destination=joiner["ready"]["profile"]["destination_hash"],
                recipient_display_name="Blair",
            )["match"]

            after_group_marker = f"{marker}-after-group"
            _call(
                joiner["commands"],
                joiner["responses"],
                "send_message",
                contact_id=approved["id"],
                text=after_group_marker,
            )
            after_group_received = _call(
                inviter["commands"],
                inviter["responses"],
                "wait_for",
                response_timeout=timeout + 10,
                timeout=timeout,
                state="inbound_chat",
                text=after_group_marker,
            )["match"]
            after_group_delivered = _call(
                joiner["commands"],
                joiner["responses"],
                "wait_for",
                response_timeout=timeout + 10,
                timeout=timeout,
                state="outbound_delivered",
                text=after_group_marker,
            )["match"]

            inviter_config = (root / "alex" / "reticulum" / "config").read_text(
                encoding="utf-8"
            )
            joiner_config = (root / "blair" / "reticulum" / "config").read_text(
                encoding="utf-8"
            )
            return {
                "route": "signed_tcp_hint_only",
                "hint": hints[0],
                "inviter_nearby_discovery": inviter["ready"]["settings"][
                    "nearby_discovery"
                ],
                "joiner_nearby_discovery": joiner["ready"]["settings"][
                    "nearby_discovery"
                ],
                "inviter_auto_interface": "AutoInterface" in inviter_config,
                "joiner_auto_interface": "AutoInterface" in joiner_config,
                "inviter_tcp_server": "TCPServerInterface" in inviter_config,
                "inviter_tcp_client": "TCPClientInterface" in inviter_config,
                "joiner_tcp_server": "TCPServerInterface" in joiner_config,
                "joiner_tcp_client": "TCPClientInterface" in joiner_config,
                "pending_request": pending["trust"] == "pending_request",
                "acceptance_returned": approved["trust"] in {"approved", "verified"},
                "approval_elapsed_seconds": approval_elapsed,
                "message_received": after_group_received["text"]
                == after_group_marker,
                "sender_delivered": after_group_delivered["state"] == "delivered",
                "phone_first_command_ok": phone_first_command["frame"].get("ok")
                is True,
                "phone_first_command_elapsed_seconds": phone_first_elapsed,
                "phone_first_command_id_preserved": phone_first_command["frame"].get(
                    "id"
                )
                == f"{marker}-phone-command",
                "phone_first_received": phone_first_received["text"]
                == phone_first_marker,
                "phone_first_sender_delivered": phone_first_delivered["state"]
                == "delivered",
                "phone_first_message_id_preserved": phone_first_command["result"]["id"]
                == phone_first_received["id"]
                == phone_first_delivered["id"],
                "desktop_reply_command_ok": desktop_reply_command["frame"].get("ok")
                is True,
                "desktop_reply_command_elapsed_seconds": desktop_reply_elapsed,
                "desktop_reply_command_id_preserved": desktop_reply_command["frame"].get(
                    "id"
                )
                == f"{marker}-desktop-command",
                "desktop_reply_received": desktop_reply_received["text"]
                == desktop_reply_marker,
                "desktop_reply_sender_delivered": desktop_reply_delivered["state"]
                == "delivered",
                "desktop_reply_message_id_preserved": desktop_reply_command["result"]["id"]
                == desktop_reply_received["id"]
                == desktop_reply_delivered["id"],
                # Preserve the older result names for downstream callers. The
                # pre-group direct leg is now the desktop return message.
                "direct_before_group_received": desktop_reply_received["text"]
                == desktop_reply_marker,
                "direct_before_group_delivered": desktop_reply_delivered["state"]
                == "delivered",
                "direct_after_group_received": after_group_received["text"]
                == after_group_marker,
                "direct_after_group_delivered": after_group_delivered["state"]
                == "delivered",
                "group_invitation_received": incoming_group_invitation["group_id"]
                == created_group["id"],
                "group_invitation_receipted": invite_ready["invite_delivery_state"]
                == "delivered",
                "group_joined": joined_group["status"] == "active",
                "group_message_received": group_received["text"] == group_marker,
                "group_message_id_preserved": group_received["id"]
                == sent_group_message["id"]
                == group_delivered["id"],
                "group_sender_delivered": group_delivered["delivery_summary"]
                == {
                    "total": 1,
                    "delivered": 1,
                    "pending": 0,
                    "failed": 0,
                    "expired": 0,
                },
                "group_single_recipient": group_delivered["deliveries"]
                == [
                    {
                        "recipient_destination": joiner["ready"]["profile"][
                            "destination_hash"
                        ],
                        "recipient_display_name": "Blair",
                        "state": "delivered",
                    }
                ],
            }
        finally:
            for peer in peers.values():
                process = peer["process"]
                if process.is_alive():
                    try:
                        _call(
                            peer["commands"],
                            peer["responses"],
                            "stop",
                            response_timeout=10,
                        )
                    except Exception:
                        pass
            for peer in peers.values():
                process = peer["process"]
                process.join(timeout=10)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    result = run(timeout=args.timeout)
    print(json.dumps(result, indent=2))
    success = (
        result["route"] == "signed_tcp_hint_only"
        and result["inviter_nearby_discovery"] is False
        and result["joiner_nearby_discovery"] is False
        and result["inviter_auto_interface"] is False
        and result["joiner_auto_interface"] is False
        and result["inviter_tcp_server"] is True
        and result["inviter_tcp_client"] is True
        and result["joiner_tcp_server"] is True
        and result["joiner_tcp_client"] is True
        and result["pending_request"] is True
        and result["acceptance_returned"] is True
        and result["approval_elapsed_seconds"] < 20
        and result["message_received"] is True
        and result["sender_delivered"] is True
        and result["phone_first_command_ok"] is True
        and result["phone_first_command_id_preserved"] is True
        and result["phone_first_received"] is True
        and result["phone_first_sender_delivered"] is True
        and result["phone_first_message_id_preserved"] is True
        and result["desktop_reply_command_ok"] is True
        and result["desktop_reply_command_id_preserved"] is True
        and result["desktop_reply_received"] is True
        and result["desktop_reply_sender_delivered"] is True
        and result["desktop_reply_message_id_preserved"] is True
        and result["direct_before_group_received"] is True
        and result["direct_before_group_delivered"] is True
        and result["direct_after_group_received"] is True
        and result["direct_after_group_delivered"] is True
        and result["group_invitation_received"] is True
        and result["group_invitation_receipted"] is True
        and result["group_joined"] is True
        and result["group_message_received"] is True
        and result["group_message_id_preserved"] is True
        and result["group_sender_delivered"] is True
        and result["group_single_recipient"] is True
    )
    return 0 if success else 1


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
