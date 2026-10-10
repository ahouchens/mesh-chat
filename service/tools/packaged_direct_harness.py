"""Exercise a complete one-to-one exchange through two packaged sidecars.

Unlike ``direct_lan_harness.py``, this probe does not import or construct the
service under test. It launches the exact frozen sidecar artifact twice and
talks to each process only through the production framed IPC protocol. The
temporary directory supplied by the caller must inherit the platform's
required protected-storage property (EFS on Windows).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from mesh_chat.ipc import encode_frame, read_frame


COMMAND_TIMEOUT_SECONDS = 20.0
DELIVERY_TIMEOUT_SECONDS = 45.0


class PackagedPeer:
    def __init__(self, binary: Path, profile: Path, display_name: str):
        self.process = subprocess.Popen(
            [str(binary)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._responses: queue.Queue[dict[str, Any]] = queue.Queue()
        self._events: list[dict[str, Any]] = []
        self._reader_error: BaseException | None = None
        self._sequence = 0
        self._reader = threading.Thread(
            target=self._read_frames,
            name=f"packaged-peer-reader-{display_name}",
            daemon=True,
        )
        self._reader.start()
        initialized, elapsed = self.call(
            "initialize",
            {
                "profile_dir": str(profile),
                "vault_key": base64.b64encode(os.urandom(32)).decode("ascii"),
                "display_name": display_name,
                "parent_pid": os.getpid(),
            },
            request_id=f"initialize-{display_name}",
            timeout=30.0,
        )
        if initialized.get("profile") is None:
            raise RuntimeError("Packaged sidecar did not create a profile")
        self.initialize_elapsed = elapsed

    def _read_frames(self) -> None:
        assert self.process.stdout is not None
        try:
            while True:
                frame = read_frame(self.process.stdout)
                if frame.get("type") == "response":
                    self._responses.put(frame)
                elif frame.get("type") == "event":
                    self._events.append(frame)
        except EOFError:
            return
        except BaseException as exc:  # surfaced by call() without message data
            self._reader_error = exc

    def call(
        self,
        command: str,
        payload: dict[str, Any] | None = None,
        *,
        request_id: str | None = None,
        timeout: float = COMMAND_TIMEOUT_SECONDS,
    ) -> tuple[Any, float]:
        if self.process.poll() is not None:
            raise RuntimeError(f"Packaged sidecar exited with {self.process.returncode}")
        self._sequence += 1
        command_id = request_id or f"package-{self._sequence}-{uuid.uuid4().hex}"
        frame = {
            "v": 1,
            "id": command_id,
            "command": command,
            "payload": payload or {},
        }
        assert self.process.stdin is not None
        started = time.monotonic()
        self.process.stdin.write(encode_frame(frame))
        self.process.stdin.flush()
        deadline = started + timeout
        deferred: list[dict[str, Any]] = []
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"Packaged {command} command exceeded {timeout:g}s")
                try:
                    response = self._responses.get(timeout=remaining)
                except queue.Empty as exc:
                    if self._reader_error is not None:
                        raise RuntimeError("Packaged sidecar frame reader failed") from self._reader_error
                    raise TimeoutError(
                        f"Packaged {command} command exceeded {timeout:g}s"
                    ) from exc
                if response.get("id") != command_id:
                    deferred.append(response)
                    continue
                if response.get("ok") is not True:
                    code = response.get("error", {}).get("code", "unknown_error")
                    raise RuntimeError(f"Packaged {command} failed: {code}")
                return response.get("result"), time.monotonic() - started
        finally:
            for response in deferred:
                self._responses.put(response)

    def wait_for(
        self,
        predicate: Callable[[dict[str, Any]], Any],
        *,
        description: str,
        timeout: float = DELIVERY_TIMEOUT_SECONDS,
    ) -> Any:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            snapshot, _elapsed = self.call("snapshot")
            match = predicate(snapshot)
            if match is not None:
                return match
            time.sleep(0.2)
        raise TimeoutError(f"Timed out waiting for {description}")

    def close(self) -> dict[str, Any]:
        clean = False
        try:
            if self.process.poll() is None:
                self.call("shutdown", timeout=5.0)
                self.process.wait(timeout=10.0)
                clean = self.process.returncode == 0
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=5.0)
        stderr = self.process.stderr.read() if self.process.stderr else b""
        return {
            "clean": clean,
            "stderr_content_free": b"Packaging Desktop" not in stderr
            and b"Packaging Phone" not in stderr,
        }


def _contact(snapshot: dict[str, Any], states: set[str]) -> dict[str, Any] | None:
    return next(
        (item for item in snapshot.get("contacts", []) if item.get("trust") in states),
        None,
    )


def _message(
    snapshot: dict[str, Any],
    *,
    text: str,
    direction: str,
    state: str | None = None,
) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in snapshot.get("messages", [])
            if item.get("text") == text
            and item.get("direction") == direction
            and (state is None or item.get("state") == state)
        ),
        None,
    )


def _message_with_reactions(
    snapshot: dict[str, Any],
    *,
    text: str,
    direction: str,
    reactions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    message = _message(snapshot, text=text, direction=direction)
    if message is None or message.get("reactions") != reactions:
        return None
    return message


def run(binary: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="mesh-chat-packaged-direct-") as temporary:
        root = Path(temporary)
        desktop = PackagedPeer(binary, root / "desktop", "Packaging Desktop")
        phone = PackagedPeer(binary, root / "phone", "Packaging Phone")
        result: dict[str, Any] = {}
        close_results: list[dict[str, Any]] = []
        try:
            invitation, _ = desktop.call("create_invitation")
            phone_contact, _ = phone.call(
                "accept_invitation", {"invitation": invitation["file"]}
            )
            pending = desktop.wait_for(
                lambda snapshot: _contact(snapshot, {"pending_request"}),
                description="desktop connection request",
            )
            desktop.call("approve_request", {"contact_id": pending["id"]})
            phone.wait_for(
                lambda snapshot: next(
                    (
                        item
                        for item in snapshot.get("contacts", [])
                        if item.get("id") == phone_contact["id"]
                        and item.get("trust") in {"approved", "verified"}
                    ),
                    None,
                ),
                description="phone approval",
            )

            phone_text = f"packaged-phone-first-{uuid.uuid4().hex}"
            phone_sent, phone_elapsed = phone.call(
                "send_message",
                {"contact_id": phone_contact["id"], "text": phone_text},
            )
            desktop_received = desktop.wait_for(
                lambda snapshot: _message(
                    snapshot, text=phone_text, direction="inbound"
                ),
                description="packaged phone message",
            )
            phone_delivered = phone.wait_for(
                lambda snapshot: _message(
                    snapshot,
                    text=phone_text,
                    direction="outbound",
                    state="delivered",
                ),
                description="packaged phone application receipt",
            )

            desktop_text = f"packaged-desktop-reply-{uuid.uuid4().hex}"
            desktop_sent, desktop_elapsed = desktop.call(
                "send_message",
                {"contact_id": pending["id"], "text": desktop_text},
            )
            phone_received = phone.wait_for(
                lambda snapshot: _message(
                    snapshot, text=desktop_text, direction="inbound"
                ),
                description="packaged desktop reply",
            )
            desktop_delivered = desktop.wait_for(
                lambda snapshot: _message(
                    snapshot,
                    text=desktop_text,
                    direction="outbound",
                    state="delivered",
                ),
                description="packaged desktop application receipt",
            )

            # Exercise direct reactions through the same frozen IPC and native
            # network path as chat. The phone first reacts to the desktop's
            # reply, then the desktop adds and replaces its own reaction. Both
            # peers must agree on counts while independently marking only their
            # own reaction. Finally, removing the phone reaction must converge
            # without disturbing the desktop reaction.
            phone_reaction, phone_reaction_elapsed = phone.call(
                "set_message_reaction",
                {
                    "kind": "direct",
                    "message_id": phone_received["id"],
                    "emoji": "👩🏽‍🌾",
                    "active": True,
                },
            )
            phone_reaction_local = phone.wait_for(
                lambda snapshot: _message_with_reactions(
                    snapshot,
                    text=desktop_text,
                    direction="inbound",
                    reactions=[
                        {"emoji": "👩🏽‍🌾", "count": 1, "reacted_by_self": True}
                    ],
                ),
                description="phone reaction in its local conversation",
            )
            phone_reaction_remote = desktop.wait_for(
                lambda snapshot: _message_with_reactions(
                    snapshot,
                    text=desktop_text,
                    direction="outbound",
                    reactions=[
                        {"emoji": "👩🏽‍🌾", "count": 1, "reacted_by_self": False}
                    ],
                ),
                description="phone reaction on desktop",
            )

            desktop.call(
                "set_message_reaction",
                {
                    "kind": "direct",
                    "message_id": desktop_sent["id"],
                    "emoji": "😂",
                    "active": True,
                },
            )
            desktop_reaction_added = desktop.wait_for(
                lambda snapshot: _message_with_reactions(
                    snapshot,
                    text=desktop_text,
                    direction="outbound",
                    reactions=[
                        {"emoji": "😂", "count": 1, "reacted_by_self": True},
                        {"emoji": "👩🏽‍🌾", "count": 1, "reacted_by_self": False},
                    ],
                ),
                description="desktop reaction in its local conversation",
            )
            phone_saw_desktop_reaction = phone.wait_for(
                lambda snapshot: _message_with_reactions(
                    snapshot,
                    text=desktop_text,
                    direction="inbound",
                    reactions=[
                        {"emoji": "😂", "count": 1, "reacted_by_self": False},
                        {"emoji": "👩🏽‍🌾", "count": 1, "reacted_by_self": True},
                    ],
                ),
                description="desktop reaction on phone",
            )

            desktop.call(
                "set_message_reaction",
                {
                    "kind": "direct",
                    "message_id": desktop_sent["id"],
                    "emoji": "❤️",
                    "active": True,
                },
            )
            desktop_reaction_replaced = desktop.wait_for(
                lambda snapshot: _message_with_reactions(
                    snapshot,
                    text=desktop_text,
                    direction="outbound",
                    reactions=[
                        {"emoji": "❤️", "count": 1, "reacted_by_self": True},
                        {"emoji": "👩🏽‍🌾", "count": 1, "reacted_by_self": False},
                    ],
                ),
                description="replacement desktop reaction locally",
            )
            phone_saw_replacement = phone.wait_for(
                lambda snapshot: _message_with_reactions(
                    snapshot,
                    text=desktop_text,
                    direction="inbound",
                    reactions=[
                        {"emoji": "❤️", "count": 1, "reacted_by_self": False},
                        {"emoji": "👩🏽‍🌾", "count": 1, "reacted_by_self": True},
                    ],
                ),
                description="replacement desktop reaction on phone",
            )

            phone.call(
                "set_message_reaction",
                {
                    "kind": "direct",
                    "message_id": phone_received["id"],
                    "emoji": "👩🏽‍🌾",
                    "active": False,
                },
            )
            phone_reaction_removed = phone.wait_for(
                lambda snapshot: _message_with_reactions(
                    snapshot,
                    text=desktop_text,
                    direction="inbound",
                    reactions=[
                        {"emoji": "❤️", "count": 1, "reacted_by_self": False}
                    ],
                ),
                description="phone reaction removal locally",
            )
            desktop_saw_removal = desktop.wait_for(
                lambda snapshot: _message_with_reactions(
                    snapshot,
                    text=desktop_text,
                    direction="outbound",
                    reactions=[
                        {"emoji": "❤️", "count": 1, "reacted_by_self": True}
                    ],
                ),
                description="phone reaction removal on desktop",
            )

            # Exercise local deletion through the exact frozen command
            # boundary. Trust stays intact, visible history and the saved draft
            # disappear, and a genuinely fresh inbound chat reopens the thread.
            deleted_draft = f"packaged-deleted-draft-{uuid.uuid4().hex}"
            desktop.call(
                "save_draft",
                {"contact_id": pending["id"], "text": deleted_draft},
            )
            desktop.call(
                "delete_conversation",
                {"kind": "direct", "id": pending["id"]},
            )
            deleted_snapshot, _ = desktop.call("snapshot")
            hidden_after_delete = {
                (item.get("kind"), item.get("id"))
                for item in deleted_snapshot.get("hidden_conversations", [])
            }

            reappear_text = f"packaged-reappear-{uuid.uuid4().hex}"
            reappear_sent, _ = phone.call(
                "send_message",
                {"contact_id": phone_contact["id"], "text": reappear_text},
            )
            reappear_received = desktop.wait_for(
                lambda snapshot: _message(
                    snapshot, text=reappear_text, direction="inbound"
                ),
                description="fresh chat reopening a deleted conversation",
            )
            reappear_delivered = phone.wait_for(
                lambda snapshot: _message(
                    snapshot,
                    text=reappear_text,
                    direction="outbound",
                    state="delivered",
                ),
                description="fresh chat receipt after local deletion",
            )
            reopened_snapshot, _ = desktop.call("snapshot")
            hidden_after_reopen = {
                (item.get("kind"), item.get("id"))
                for item in reopened_snapshot.get("hidden_conversations", [])
            }

            result = {
                "phone_send_within_desktop_deadline": phone_elapsed
                < COMMAND_TIMEOUT_SECONDS,
                "desktop_reply_within_desktop_deadline": desktop_elapsed
                < COMMAND_TIMEOUT_SECONDS,
                "phone_message_id_preserved": phone_sent["id"]
                == desktop_received["id"]
                == phone_delivered["id"],
                "desktop_reply_id_preserved": desktop_sent["id"]
                == phone_received["id"]
                == desktop_delivered["id"],
                "phone_message_delivered": phone_delivered["state"] == "delivered",
                "desktop_reply_delivered": desktop_delivered["state"] == "delivered",
                "phone_reaction_within_desktop_deadline": phone_reaction_elapsed
                < COMMAND_TIMEOUT_SECONDS,
                "phone_reaction_command_preserved_target": phone_reaction["message_id"]
                == phone_received["id"],
                "phone_reaction_converged": phone_reaction_local["id"]
                == phone_reaction_remote["id"]
                == desktop_sent["id"],
                "desktop_reaction_add_converged": desktop_reaction_added["id"]
                == phone_saw_desktop_reaction["id"]
                == desktop_sent["id"],
                "desktop_reaction_replace_converged": desktop_reaction_replaced["id"]
                == phone_saw_replacement["id"]
                == desktop_sent["id"],
                "reaction_remove_converged": phone_reaction_removed["id"]
                == desktop_saw_removal["id"]
                == desktop_sent["id"],
                "delete_kept_contact": any(
                    item.get("id") == pending["id"]
                    for item in deleted_snapshot.get("contacts", [])
                ),
                "delete_removed_visible_history": not any(
                    item.get("contact_id") == pending["id"]
                    for item in deleted_snapshot.get("messages", [])
                ),
                "delete_removed_saved_draft": not any(
                    item.get("contact_id") == pending["id"]
                    for item in deleted_snapshot.get("drafts", [])
                ),
                "delete_hid_conversation": ("direct", pending["id"])
                in hidden_after_delete,
                "fresh_inbound_reopened_conversation": ("direct", pending["id"])
                not in hidden_after_reopen,
                "fresh_inbound_id_preserved": reappear_sent["id"]
                == reappear_received["id"]
                == reappear_delivered["id"],
            }
        finally:
            close_results.extend([phone.close(), desktop.close()])
        result["clean_shutdown"] = all(item["clean"] for item in close_results)
        result["stderr_content_free"] = all(
            item["stderr_content_free"] for item in close_results
        )
        return result


def run_workspace_admin(binary: Path) -> dict[str, Any]:
    """Exercise Increment 12 through two exact packaged sidecars."""

    with tempfile.TemporaryDirectory(prefix="mesh-chat-packaged-admin-") as temporary:
        root = Path(temporary)
        owner = PackagedPeer(binary, root / "owner", "Packaged Owner")
        admin = PackagedPeer(binary, root / "admin", "Packaged Admin")
        close_results: list[dict[str, Any]] = []
        result: dict[str, Any] = {}

        def op() -> str:
            return str(uuid.uuid4())

        try:
            # Establish the real encrypted route first; workspace traffic then
            # crosses the same production LXMF and framed-IPC boundaries.
            invitation, _ = owner.call("create_invitation")
            admin_contact, _ = admin.call(
                "accept_invitation", {"invitation": invitation["file"]}
            )
            owner_contact = owner.wait_for(
                lambda snap: _contact(snap, {"pending_request"}),
                description="packaged admin route request",
            )
            owner.call("approve_request", {"contact_id": owner_contact["id"]})
            admin.wait_for(
                lambda snap: next(
                    (
                        item for item in snap.get("contacts", [])
                        if item.get("id") == admin_contact["id"]
                        and item.get("trust") in {"approved", "verified"}
                    ),
                    None,
                ),
                description="packaged admin route approval",
            )

            workspace, _ = owner.call(
                "create_workspace",
                {
                    "name": "Packaged administrators",
                    "description": "Exact candidate flow",
                    "operation_id": op(),
                },
            )
            workspace_id = workspace["id"]
            workspace_invitation, _ = owner.call(
                "create_workspace_invitation",
                {"workspace_id": workspace_id, "operation_id": op()},
            )
            admin.call(
                "submit_workspace_join",
                {"invitation": workspace_invitation["text"], "operation_id": op()},
            )
            join_request = owner.wait_for(
                lambda snap: next(
                    (
                        item for item in snap.get("workspace_join_requests", [])
                        if item.get("workspace_id") == workspace_id
                        and item.get("state") == "pending"
                    ),
                    None,
                ),
                description="packaged workspace join request",
            )
            owner.call(
                "approve_workspace_join",
                {
                    "workspace_id": workspace_id,
                    "request_id": join_request["id"],
                    "operation_id": op(),
                },
            )
            joined = admin.wait_for(
                lambda snap: next(
                    (
                        item for item in snap.get("workspaces", [])
                        if item.get("id") == workspace_id
                        and item.get("state") == "active"
                    ),
                    None,
                ),
                description="packaged active workspace",
            )
            admin_member_id = joined["local_member_id"]
            owner.call(
                "change_workspace_role",
                {
                    "workspace_id": workspace_id,
                    "member_id": admin_member_id,
                    "role": "admin",
                    "operation_id": op(),
                },
            )
            admin.wait_for(
                lambda snap: next(
                    (
                        item for item in snap.get("workspaces", [])
                        if item.get("id") == workspace_id
                        and item.get("local_role") == "admin"
                    ),
                    None,
                ),
                description="packaged administrator promotion",
            )
            owner.call(
                "update_workspace_policies",
                {
                    "workspace_id": workspace_id,
                    "channel_creation": "owner_and_admins",
                    "posting": "owner_and_admins",
                    "invitation_requests": "owner_and_admins",
                    "operation_id": op(),
                },
            )
            admin.wait_for(
                lambda snap: next(
                    (
                        item for item in snap.get("workspaces", [])
                        if item.get("id") == workspace_id
                        and item.get("policies", {}).get("posting")
                        == "owner_and_admins"
                    ),
                    None,
                ),
                description="packaged administrator policy",
            )

            channel, _ = admin.call(
                "create_workspace_channel",
                {
                    "workspace_id": workspace_id,
                    "name": "packaged-admin-offline",
                    "topic": "Owner command path idle",
                    "visibility": "public",
                    "member_ids": [],
                    "operation_id": op(),
                },
            )
            message, _ = admin.call(
                "send_workspace_message",
                {
                    "workspace_id": workspace_id,
                    "channel_id": channel["id"],
                    "text": "Packaged administrator message",
                    "event_id": op(),
                    "operation_id": op(),
                },
            )
            owner.wait_for(
                lambda snap: next(
                    (
                        item for item in snap.get("workspace_channels", [])
                        if item.get("id") == channel["id"]
                    ),
                    None,
                ),
                description="packaged administrator channel convergence",
            )
            owner_message = owner.wait_for(
                lambda _snap: next(
                    (
                        item
                        for item in owner.call(
                            "list_workspace_messages",
                            {
                                "workspace_id": workspace_id,
                                "channel_id": channel["id"],
                                "limit": 50,
                            },
                        )[0].get("messages", [])
                        if item.get("id") == message["id"]
                    ),
                    None,
                ),
                description="packaged administrator message convergence",
            )

            removal, _ = admin.call(
                "submit_workspace_admin_request",
                {
                    "workspace_id": workspace_id,
                    "request_kind": "member_removal",
                    "target_member_id": admin_member_id,
                    "requested_role": None,
                    "note": "Packaged decline",
                    "operation_id": op(),
                },
            )
            owner_removal = owner.wait_for(
                lambda snap: next(
                    (
                        item for item in snap.get("workspace_admin_requests", [])
                        if item.get("request_kind") == "member_removal"
                        and item.get("state") == "pending"
                    ),
                    None,
                ),
                description="packaged removal request",
            )
            owner.call(
                "decline_workspace_admin_request",
                {
                    "workspace_id": workspace_id,
                    "request_id": owner_removal["id"],
                    "operation_id": op(),
                },
            )
            declined = admin.wait_for(
                lambda snap: next(
                    (
                        item for item in snap.get("workspace_admin_requests", [])
                        if item.get("id") == removal["id"]
                        and item.get("state") == "declined"
                    ),
                    None,
                ),
                description="packaged declined removal",
            )

            demotion, _ = admin.call(
                "submit_workspace_admin_request",
                {
                    "workspace_id": workspace_id,
                    "request_kind": "role_change",
                    "target_member_id": admin_member_id,
                    "requested_role": "member",
                    "note": "Packaged demotion",
                    "operation_id": op(),
                },
            )
            owner_demotion = owner.wait_for(
                lambda snap: next(
                    (
                        item for item in snap.get("workspace_admin_requests", [])
                        if item.get("request_kind") == "role_change"
                        and item.get("state") == "pending"
                    ),
                    None,
                ),
                description="packaged demotion request",
            )
            owner.call(
                "approve_workspace_admin_request",
                {
                    "workspace_id": workspace_id,
                    "request_id": owner_demotion["id"],
                    "operation_id": op(),
                },
            )
            demoted = admin.wait_for(
                lambda snap: next(
                    (
                        item for item in snap.get("workspaces", [])
                        if item.get("id") == workspace_id
                        and item.get("local_role") == "member"
                    ),
                    None,
                ),
                description="packaged administrator demotion",
            )
            result = {
                "admin_channel_converged": channel["id"] is not None,
                "admin_message_converged": owner_message["id"] == message["id"],
                "decline_no_effect": declined["state"] == "declined",
                "approved_demotion_converged": demoted["local_role"] == "member",
                "demotion_request_audited": demotion["state"] == "pending",
            }
        finally:
            close_results.extend([admin.close(), owner.close()])
        result["clean_shutdown"] = all(item["clean"] for item in close_results)
        result["stderr_content_free"] = all(
            item["stderr_content_free"] for item in close_results
        )
        return result


def run_mixed(current_binary: Path, legacy_binary: Path) -> dict[str, Any]:
    """Exercise the 0.2.10/0.2.9 direct-chat compatibility boundary.

    The current sidecar acts as the desktop invitation owner and the legacy
    sidecar acts as the phone.  Keep this separate from ``run`` so the normal
    same-version release probe remains unchanged.

    A current-only Emoji 18 reaction is followed by ordinary messages in both
    directions.  Those messages are a liveness/ordering barrier: once they
    have crossed the same established link, the legacy snapshot must still
    contain only the original-six reaction state it understands.
    """

    with tempfile.TemporaryDirectory(prefix="mesh-chat-packaged-mixed-") as temporary:
        root = Path(temporary)
        desktop = PackagedPeer(
            current_binary, root / "current-desktop", "Packaging Desktop"
        )
        phone = PackagedPeer(legacy_binary, root / "legacy-phone", "Packaging Phone")
        result: dict[str, Any] = {}
        close_results: list[dict[str, Any]] = []
        try:
            invitation, _ = desktop.call("create_invitation")
            phone_contact, _ = phone.call(
                "accept_invitation", {"invitation": invitation["file"]}
            )
            desktop_contact = desktop.wait_for(
                lambda snapshot: _contact(snapshot, {"pending_request"}),
                description="mixed-version desktop connection request",
            )
            desktop.call("approve_request", {"contact_id": desktop_contact["id"]})
            phone.wait_for(
                lambda snapshot: next(
                    (
                        item
                        for item in snapshot.get("contacts", [])
                        if item.get("id") == phone_contact["id"]
                        and item.get("trust") in {"approved", "verified"}
                    ),
                    None,
                ),
                description="mixed-version phone approval",
            )

            initial_phone_text = f"mixed-legacy-phone-first-{uuid.uuid4().hex}"
            initial_phone_sent, _ = phone.call(
                "send_message",
                {"contact_id": phone_contact["id"], "text": initial_phone_text},
            )
            initial_desktop_received = desktop.wait_for(
                lambda snapshot: _message(
                    snapshot, text=initial_phone_text, direction="inbound"
                ),
                description="initial legacy phone message on current desktop",
            )
            initial_phone_delivered = phone.wait_for(
                lambda snapshot: _message(
                    snapshot,
                    text=initial_phone_text,
                    direction="outbound",
                    state="delivered",
                ),
                description="initial legacy phone application receipt",
            )

            initial_desktop_text = f"mixed-current-desktop-reply-{uuid.uuid4().hex}"
            initial_desktop_sent, _ = desktop.call(
                "send_message",
                {
                    "contact_id": desktop_contact["id"],
                    "text": initial_desktop_text,
                },
            )
            initial_phone_received = phone.wait_for(
                lambda snapshot: _message(
                    snapshot, text=initial_desktop_text, direction="inbound"
                ),
                description="initial current desktop reply on legacy phone",
            )
            initial_desktop_delivered = desktop.wait_for(
                lambda snapshot: _message(
                    snapshot,
                    text=initial_desktop_text,
                    direction="outbound",
                    state="delivered",
                ),
                description="initial current desktop application receipt",
            )

            # Prove that the original-six wire format remains bidirectionally
            # compatible before testing a reaction the legacy validator does
            # not know.  Each actor owns one reaction per target.
            phone.call(
                "set_message_reaction",
                {
                    "kind": "direct",
                    "message_id": initial_phone_received["id"],
                    "emoji": "👍",
                    "active": True,
                },
            )
            phone_quick_local = phone.wait_for(
                lambda snapshot: _message_with_reactions(
                    snapshot,
                    text=initial_desktop_text,
                    direction="inbound",
                    reactions=[
                        {"emoji": "👍", "count": 1, "reacted_by_self": True}
                    ],
                ),
                description="legacy phone quick reaction locally",
            )
            phone_quick_remote = desktop.wait_for(
                lambda snapshot: _message_with_reactions(
                    snapshot,
                    text=initial_desktop_text,
                    direction="outbound",
                    reactions=[
                        {"emoji": "👍", "count": 1, "reacted_by_self": False}
                    ],
                ),
                description="legacy phone quick reaction on current desktop",
            )

            desktop.call(
                "set_message_reaction",
                {
                    "kind": "direct",
                    "message_id": initial_desktop_sent["id"],
                    "emoji": "😂",
                    "active": True,
                },
            )
            desktop_quick_local = desktop.wait_for(
                lambda snapshot: _message_with_reactions(
                    snapshot,
                    text=initial_desktop_text,
                    direction="outbound",
                    reactions=[
                        {"emoji": "👍", "count": 1, "reacted_by_self": False},
                        {"emoji": "😂", "count": 1, "reacted_by_self": True},
                    ],
                ),
                description="current desktop quick reaction locally",
            )
            desktop_quick_remote = phone.wait_for(
                lambda snapshot: _message_with_reactions(
                    snapshot,
                    text=initial_desktop_text,
                    direction="inbound",
                    reactions=[
                        {"emoji": "👍", "count": 1, "reacted_by_self": True},
                        {"emoji": "😂", "count": 1, "reacted_by_self": False},
                    ],
                ),
                description="current desktop quick reaction on legacy phone",
            )

            # Remove the current actor's legacy reaction first.  The remaining
            # thumbs-up gives the ignore check an exact, non-empty baseline.
            desktop.call(
                "set_message_reaction",
                {
                    "kind": "direct",
                    "message_id": initial_desktop_sent["id"],
                    "emoji": "😂",
                    "active": False,
                },
            )
            desktop_quick_removed = desktop.wait_for(
                lambda snapshot: _message_with_reactions(
                    snapshot,
                    text=initial_desktop_text,
                    direction="outbound",
                    reactions=[
                        {"emoji": "👍", "count": 1, "reacted_by_self": False}
                    ],
                ),
                description="current quick reaction removal locally",
            )
            phone_saw_quick_removal = phone.wait_for(
                lambda snapshot: _message_with_reactions(
                    snapshot,
                    text=initial_desktop_text,
                    direction="inbound",
                    reactions=[
                        {"emoji": "👍", "count": 1, "reacted_by_self": True}
                    ],
                ),
                description="current quick reaction removal on legacy phone",
            )

            expanded_emoji = "👩🏽‍🌾"
            expanded, _ = desktop.call(
                "set_message_reaction",
                {
                    "kind": "direct",
                    "message_id": initial_desktop_sent["id"],
                    "emoji": expanded_emoji,
                    "active": True,
                },
            )
            expanded_local = desktop.wait_for(
                lambda snapshot: _message_with_reactions(
                    snapshot,
                    text=initial_desktop_text,
                    direction="outbound",
                    reactions=[
                        {"emoji": "👍", "count": 1, "reacted_by_self": False},
                        {
                            "emoji": expanded_emoji,
                            "count": 1,
                            "reacted_by_self": True,
                        },
                    ],
                ),
                description="expanded Emoji 18 reaction on current desktop",
            )

            # Cross ordinary messages in both directions after the unsupported
            # reaction.  Besides proving continued chat interoperability, this
            # ensures the final legacy snapshot is taken only after traffic on
            # the same established link has continued successfully.
            post_desktop_text = f"mixed-current-after-emoji-{uuid.uuid4().hex}"
            post_desktop_sent, _ = desktop.call(
                "send_message",
                {"contact_id": desktop_contact["id"], "text": post_desktop_text},
            )
            post_phone_received = phone.wait_for(
                lambda snapshot: _message(
                    snapshot, text=post_desktop_text, direction="inbound"
                ),
                description="current chat after expanded reaction on legacy phone",
            )
            post_desktop_delivered = desktop.wait_for(
                lambda snapshot: _message(
                    snapshot,
                    text=post_desktop_text,
                    direction="outbound",
                    state="delivered",
                ),
                description="current chat receipt after expanded reaction",
            )

            post_phone_text = f"mixed-legacy-after-emoji-{uuid.uuid4().hex}"
            post_phone_sent, _ = phone.call(
                "send_message",
                {"contact_id": phone_contact["id"], "text": post_phone_text},
            )
            post_desktop_received = desktop.wait_for(
                lambda snapshot: _message(
                    snapshot, text=post_phone_text, direction="inbound"
                ),
                description="legacy chat after expanded reaction on current desktop",
            )
            post_phone_delivered = phone.wait_for(
                lambda snapshot: _message(
                    snapshot,
                    text=post_phone_text,
                    direction="outbound",
                    state="delivered",
                ),
                description="legacy chat receipt after expanded reaction",
            )

            legacy_final, _ = phone.call("snapshot")
            current_final, _ = desktop.call("snapshot")
            legacy_target = _message_with_reactions(
                legacy_final,
                text=initial_desktop_text,
                direction="inbound",
                reactions=[
                    {"emoji": "👍", "count": 1, "reacted_by_self": True}
                ],
            )
            legacy_expanded_target = _message_with_reactions(
                legacy_final,
                text=initial_desktop_text,
                direction="inbound",
                reactions=[
                    {"emoji": "👍", "count": 1, "reacted_by_self": True},
                    {
                        "emoji": expanded_emoji,
                        "count": 1,
                        "reacted_by_self": False,
                    },
                ],
            )
            current_target = _message_with_reactions(
                current_final,
                text=initial_desktop_text,
                direction="outbound",
                reactions=[
                    {"emoji": "👍", "count": 1, "reacted_by_self": False},
                    {
                        "emoji": expanded_emoji,
                        "count": 1,
                        "reacted_by_self": True,
                    },
                ],
            )

            result = {
                "initial_phone_message_id_preserved": initial_phone_sent["id"]
                == initial_desktop_received["id"]
                == initial_phone_delivered["id"],
                "initial_phone_message_delivered": initial_phone_delivered["state"]
                == "delivered",
                "initial_desktop_message_id_preserved": initial_desktop_sent["id"]
                == initial_phone_received["id"]
                == initial_desktop_delivered["id"],
                "initial_desktop_message_delivered": initial_desktop_delivered["state"]
                == "delivered",
                "legacy_quick_reaction_converged": phone_quick_local["id"]
                == phone_quick_remote["id"]
                == initial_desktop_sent["id"],
                "current_quick_reaction_converged": desktop_quick_local["id"]
                == desktop_quick_remote["id"]
                == initial_desktop_sent["id"],
                "current_quick_reaction_removal_converged": desktop_quick_removed[
                    "id"
                ]
                == phone_saw_quick_removal["id"]
                == initial_desktop_sent["id"],
                "expanded_reaction_command_preserved_target": expanded["message_id"]
                == initial_desktop_sent["id"],
                "expanded_reaction_visible_on_current": expanded_local["id"]
                == initial_desktop_sent["id"],
                "legacy_safely_ignored_expanded_reaction": legacy_target is not None
                and current_target is not None,
                "legacy_expanded_reaction_converged": legacy_expanded_target is not None
                and current_target is not None,
                "post_emoji_desktop_message_id_preserved": post_desktop_sent["id"]
                == post_phone_received["id"]
                == post_desktop_delivered["id"],
                "post_emoji_desktop_message_delivered": post_desktop_delivered["state"]
                == "delivered",
                "post_emoji_phone_message_id_preserved": post_phone_sent["id"]
                == post_desktop_received["id"]
                == post_phone_delivered["id"],
                "post_emoji_phone_message_delivered": post_phone_delivered["state"]
                == "delivered",
                "current_alive_after_expanded_reaction": desktop.process.poll() is None,
                "legacy_alive_after_expanded_reaction": phone.process.poll() is None,
            }
        finally:
            close_results.extend([phone.close(), desktop.close()])
        result["clean_shutdown"] = all(item["clean"] for item in close_results)
        result["stderr_content_free"] = all(
            item["stderr_content_free"] for item in close_results
        )
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    args = parser.parse_args()
    result = run(args.binary.resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if all(result.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
