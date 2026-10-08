from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from collections import defaultdict
from typing import Any, Iterable

import RNS

from .errors import ContactNotApproved, MeshChatError, ValidationError
from .invitations import canonical_bytes
from .models import (
    DeliveryState,
    WorkspaceChannelCreationPolicy,
    WorkspacePostingPolicy,
    WorkspaceRole,
)
from .workspace_protocol import (
    DEFAULT_INVITATION_LIFETIME_SECONDS,
    MAX_ACTIVE_MEMBERS,
    MAX_INVITATION_LIFETIME_SECONDS,
    MAX_MESSAGE_TEXT_BYTES,
    MAX_PUBLIC_CHANNELS,
    MAX_CHANNEL_FETCH_CONTROLS,
    MAX_CHANNEL_SUMMARY_ENTRIES,
    MAX_RETAINED_PUBLIC_CHANNELS,
    VerifiedWorkspaceChannel,
    VerifiedWorkspaceEvent,
    VerifiedWorkspaceManifest,
    WorkspaceManifestMemberInput,
    active_members,
    channel_name_key,
    create_workspace_channel_fetch,
    create_workspace_channel_leave_request,
    create_workspace_channel_manifest,
    create_workspace_channel_recovery,
    create_workspace_channel_record,
    create_workspace_channel_summary,
    create_workspace_channel_transfer,
    create_workspace_channel_transfer_offer,
    create_workspace_display_name_request,
    create_workspace_display_name_decision,
    create_workspace_event,
    create_workspace_genesis,
    create_workspace_invitation,
    create_workspace_join,
    create_workspace_leave_request,
    create_workspace_manifest,
    find_device,
    find_member,
    verify_workspace_channel_record,
    verify_workspace_channel_record_transition,
    verify_workspace_channel_fetch,
    verify_workspace_channel_leave_request,
    verify_workspace_channel_manifest,
    verify_workspace_channel_manifest_transition,
    verify_workspace_channel_recovery,
    verify_workspace_channel_summary,
    verify_workspace_channel_transfer,
    verify_workspace_channel_transfer_offer,
    verify_workspace_display_name_request,
    verify_workspace_display_name_decision,
    verify_workspace_event,
    verify_workspace_genesis,
    verify_workspace_invitation,
    verify_workspace_join,
    verify_workspace_leave_request,
    verify_workspace_manifest,
    verify_workspace_manifest_transition,
    workspace_invitation_formats,
)
from .workspace_wire import (
    DELIVERY_WINDOW_SECONDS,
    WorkspaceWirePayload,
    build_workspace_fields,
)


MAX_WORKSPACES = 16
MESSAGE_PAGE_DEFAULT = 50
MESSAGE_PAGE_MAX = 100
MESSAGE_PAGE_ENTRIES = 100
MESSAGE_PAGE_MAX_BYTES = 128 * 1024
MAX_PENDING_EVENTS = 256
MAX_PENDING_EVENTS_PER_SENDER = 64
MAX_PENDING_EVENT_BYTES = 16 * 1024 * 1024
MAX_PENDING_CONTROLS = 32
MAX_FUTURE_MANIFESTS = 8
MAX_PENDING_JOINS = 32
MAX_PENDING_JOINS_PER_SOURCE = 4
MAX_PENDING_CHANNEL_TRANSFERS = 32
WORKSPACE_RETRY_BASE_SECONDS = 5
WORKSPACE_RETRY_MAX_SECONDS = 5 * 60
DUE_SHARDS = 64
FINAL_DELIVERY_STATES = {
    DeliveryState.RECEIVED_BY_ENDPOINT.value,
    DeliveryState.DELIVERED.value,
    DeliveryState.EXPIRED.value,
    DeliveryState.FAILED.value,
    DeliveryState.CANCELLED.value,
}


def _new_id() -> str:
    return str(uuid.uuid4())


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value)
    except Exception as exc:
        raise ValidationError("Workspace public identity is invalid") from exc


def _canonical_digest(command: str, value: dict[str, Any]) -> str:
    return hashlib.sha256(
        canonical_bytes({"command": command, "payload": value})
    ).hexdigest()


def _canonical_transfer_offer(value: dict[str, Any]) -> str:
    return canonical_bytes(value).decode("utf-8")


def _short_id(value: str) -> str:
    return value.replace("-", "")[:6]


class WorkspaceServiceMixin:
    """Workspace service for the bounded eight-person public-channel increment."""

    store: Any
    network: Any
    settings: Any
    _identity: RNS.Identity | None

    def _workspace_changed(
        self,
        workspace_id: str,
        *,
        conversation_id: str | None = None,
        resource_kind: str = "workspace",
    ) -> None:
        self.emit(
            {
                "type": "event",
                "event": "workspace_changed",
                "workspace_id": workspace_id,
                "conversation_id": conversation_id,
                "resource_kind": resource_kind,
                "generation": time.monotonic_ns(),
            }
        )

    def _workspace_operation(
        self, command: str, operation_id: Any, payload: dict[str, Any]
    ) -> tuple[str, str, dict[str, Any] | None]:
        if not isinstance(operation_id, str):
            raise ValidationError("Operation ID is invalid")
        try:
            if str(uuid.UUID(operation_id)) != operation_id:
                raise ValueError
        except (ValueError, AttributeError) as exc:
            raise ValidationError("Operation ID is invalid") from exc
        digest = _canonical_digest(command, payload)
        return operation_id, digest, self.store.operation_result(operation_id, digest)

    def _workspace_record_id(self, workspace_id: str) -> str:
        return self.store.opaque_id("workspace", workspace_id)

    def _workspace_manifest_record_id(self, digest: str) -> str:
        return self.store.opaque_id("workspace-manifest", digest)

    def _workspace_manifest_epoch_id(self, workspace_id: str, epoch: int) -> str:
        return self.store.opaque_id(
            "workspace-manifest-epoch", workspace_id, str(epoch)
        )

    def _workspace_channel_record_id(self, channel_id: str) -> str:
        return self.store.opaque_id("workspace-channel", channel_id)

    def _workspace_channel_control_id(self, digest: str) -> str:
        return self.store.opaque_id("workspace-channel-control", digest)

    def _workspace_channel_version_id(
        self, workspace_id: str, channel_id: str, version: int
    ) -> str:
        return self.store.opaque_id(
            "workspace-channel-version", workspace_id, channel_id, str(version)
        )

    def _workspace_channel_transfer_id(self, digest: str) -> str:
        return self.store.opaque_id("workspace-channel-transfer", digest)

    def _workspace_channel_discovery_id(
        self, workspace_id: str, device_id: str
    ) -> str:
        return self.store.opaque_id(
            "workspace-channel-discovery", workspace_id, device_id
        )

    def _workspace_invitation_record_id(self, nonce: bytes) -> str:
        return self.store.opaque_id("workspace-invitation", nonce.hex())

    def _workspace_message_record_id(self, event_id: str) -> str:
        return self.store.opaque_id("workspace-message", event_id)

    def _workspace_event_record_id(self, event_id: str) -> str:
        return self.store.opaque_id("workspace-event", event_id)

    def _workspace_index_record_id(self, workspace_id: str, conversation_id: str) -> str:
        return self.store.opaque_id(
            "workspace-conversation-index", workspace_id, conversation_id
        )

    def _workspace_page_record_id(
        self, workspace_id: str, conversation_id: str, seed: str
    ) -> str:
        return self.store.opaque_id(
            "workspace-conversation-page", workspace_id, conversation_id, seed
        )

    def _workspace_stream_head_id(
        self, workspace_id: str, conversation_id: str, device_id: str
    ) -> str:
        return self.store.opaque_id(
            "workspace-stream-head", workspace_id, conversation_id, device_id
        )

    def _workspace_stream_sequence_id(
        self,
        workspace_id: str,
        conversation_id: str,
        device_id: str,
        sequence: int,
    ) -> str:
        return self.store.opaque_id(
            "workspace-stream-sequence",
            workspace_id,
            conversation_id,
            device_id,
            str(sequence),
        )

    def _due_record_id(self, shard: int) -> str:
        return self.store.opaque_id("workspace-due-shard", str(shard))

    @staticmethod
    def _due_shard(delivery_id: str) -> int:
        return hashlib.sha256(delivery_id.encode("ascii")).digest()[0] % DUE_SHARDS

    def _due_records(
        self,
        *,
        add: Iterable[dict[str, Any]] = (),
        remove: Iterable[str] = (),
    ) -> list[tuple[str, str, dict[str, Any]]]:
        additions = list(add)
        removals = list(remove)
        affected = {
            self._due_shard(item["id"]) for item in additions
        } | {self._due_shard(item) for item in removals}
        if not affected:
            return []
        by_shard: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for item in additions:
            by_shard[self._due_shard(item["id"])].append(item)
        removed_by_shard: dict[int, list[str]] = defaultdict(list)
        for delivery_id in removals:
            removed_by_shard[self._due_shard(delivery_id)].append(delivery_id)
        records: list[tuple[str, str, dict[str, Any]]] = []
        for shard in sorted(affected):
            record_id = self._due_record_id(shard)
            current = self.store.get("workspace_due_work_index", record_id) or {
                "shard": shard,
                "entries": {},
                "generation": 0,
            }
            entries = dict(current.get("entries", {}))
            for delivery_id in removed_by_shard[shard]:
                entries.pop(delivery_id, None)
            for delivery in by_shard[shard]:
                entries[delivery["id"]] = float(delivery["next_attempt_at"])
            current["entries"] = entries
            current["generation"] = int(current.get("generation", 0)) + 1
            records.append(("workspace_due_work_index", record_id, current))
        return records

    def _require_workspace(self, workspace_id: str) -> dict[str, Any]:
        if not isinstance(workspace_id, str):
            raise ValidationError("Workspace ID is invalid")
        workspace = self.store.get("workspace", self._workspace_record_id(workspace_id))
        if workspace is None:
            raise ValidationError("Workspace does not exist")
        return workspace

    def _require_workspace_channel(
        self, workspace_id: str, channel_id: str
    ) -> dict[str, Any]:
        channel = self.store.get(
            "workspace_channel", self._workspace_channel_record_id(channel_id)
        )
        if channel is None or channel.get("workspace_id") != workspace_id:
            raise ValidationError("Workspace channel does not exist")
        return channel

    def _workspace_manifest_by_digest(
        self, digest: str
    ) -> VerifiedWorkspaceManifest | None:
        record = self.store.get(
            "workspace_manifest", self._workspace_manifest_record_id(digest)
        )
        if record is None:
            return None
        manifest = verify_workspace_manifest(record["serialized"])
        if manifest.digest != digest:
            raise ValidationError("Stored workspace manifest digest changed")
        return manifest

    def _workspace_current_manifest(
        self, workspace: dict[str, Any]
    ) -> VerifiedWorkspaceManifest:
        manifest = self._workspace_manifest_by_digest(workspace["manifest_hash"])
        if manifest is None:
            raise ValidationError("Workspace manifest is unavailable")
        return manifest

    def _workspace_manifest_at_epoch(
        self, workspace_id: str, epoch: int
    ) -> VerifiedWorkspaceManifest | None:
        epoch_record = self.store.get(
            "workspace_manifest_epoch",
            self._workspace_manifest_epoch_id(workspace_id, epoch),
        )
        if epoch_record is None or not isinstance(epoch_record.get("digest"), str):
            return None
        return self._workspace_manifest_by_digest(epoch_record["digest"])

    def _workspace_genesis(self, workspace: dict[str, Any]) -> Any:
        raw = workspace.get("genesis")
        if not isinstance(raw, str):
            raise ValidationError("Workspace genesis is unavailable")
        genesis = verify_workspace_genesis(
            raw, expected_workspace_id=workspace.get("id")
        )
        if genesis.digest != workspace.get("genesis_digest"):
            raise ValidationError("Stored workspace genesis digest changed")
        return genesis

    def _workspace_source_is_active(
        self, workspace_id: str, source_hash: Any
    ) -> bool:
        if not isinstance(source_hash, bytes):
            return False
        workspace = self.store.get(
            "workspace", self._workspace_record_id(workspace_id)
        )
        if workspace is None:
            return False
        # This sealed summary is derived only from a validated manifest and is
        # intentionally retained while a referenced historical manifest is
        # temporarily missing. Using it here lets an admitted peer deliver the
        # missing control without opening the path to an unrelated contact.
        return any(
            member.get("status") == "active"
            and member.get("device", {}).get("destination_hash")
            == source_hash.hex()
            for member in workspace.get("members", [])
        )

    def _set_workspace_sync_issue(
        self, workspace_id: str, reason: str, *, incomplete: bool = False
    ) -> None:
        workspace = self.store.get(
            "workspace", self._workspace_record_id(workspace_id)
        )
        if workspace is None or workspace.get("state") not in {
            "active",
            "incomplete_sync",
            "joining",
        }:
            return
        workspace["sync_issue"] = reason
        if incomplete and workspace.get("state") == "active":
            workspace["state"] = "incomplete_sync"
        workspace["updated_at"] = time.time()
        self.store.put("workspace", self._workspace_record_id(workspace_id), workspace)
        self._workspace_changed(workspace_id, resource_kind="sync_state")

    def _clear_workspace_sync_issue_if_resolved(self, workspace_id: str) -> None:
        workspace = self.store.get(
            "workspace", self._workspace_record_id(workspace_id)
        )
        if (
            workspace is None
            or workspace.get("state") == "incomplete_sync"
            or "sync_issue" not in workspace
        ):
            return
        has_pending = any(
            item.get("workspace_id") == workspace_id
            for kind in ("workspace_pending_control", "workspace_pending_event")
            for item in self.store.list(kind)
        )
        if has_pending:
            return
        workspace.pop("sync_issue", None)
        workspace["updated_at"] = time.time()
        self.store.put("workspace", self._workspace_record_id(workspace_id), workspace)
        self._workspace_changed(workspace_id, resource_kind="sync_state")

    def _workspace_channel_by_digest(
        self, digest: str, *, _depth: int = 0
    ) -> VerifiedWorkspaceChannel | None:
        if _depth >= MAX_CHANNEL_FETCH_CONTROLS:
            raise ValidationError("Workspace channel control chain is too deep")
        control = self.store.get(
            "workspace_channel_control",
            self._workspace_channel_control_id(digest),
        )
        if control is None:
            return None
        manifest = self._workspace_manifest_by_digest(control["manifest_digest"])
        if manifest is None:
            return None
        try:
            document_type = json.loads(control["serialized"]).get("type")
        except (TypeError, json.JSONDecodeError):
            raise ValidationError("Stored workspace channel control is invalid")
        if document_type == "workspace_channel_record":
            channel = verify_workspace_channel_record(
                control["serialized"], manifest=manifest
            )
        elif document_type == "workspace_channel_manifest" and (
            not control.get("previous_hash")
            or control.get("admission_checkpoint") is True
        ):
            channel = verify_workspace_channel_manifest(
                control["serialized"], manifest=manifest
            )
        else:
            previous_hash = control.get("previous_hash")
            if not isinstance(previous_hash, str):
                raise ValidationError("Stored workspace channel predecessor is invalid")
            previous = self._workspace_channel_by_digest(
                previous_hash, _depth=_depth + 1
            )
            if previous is None:
                return None
            if document_type == "workspace_channel_transfer":
                channel = verify_workspace_channel_transfer(
                    control["serialized"], channel=previous, manifest=manifest
                )
            elif document_type == "workspace_channel_recovery":
                channel = verify_workspace_channel_recovery(
                    control["serialized"], channel=previous, manifest=manifest
                )
            elif document_type == "workspace_channel_manifest":
                channel = verify_workspace_channel_manifest_transition(
                    control["serialized"], previous, manifest=manifest
                )
            else:
                raise ValidationError("Stored workspace channel control type is invalid")
        if channel.digest != digest:
            raise ValidationError("Stored workspace channel digest changed")
        return channel

    def _workspace_channel_control_record(
        self,
        channel: VerifiedWorkspaceChannel,
        *,
        document_type: str,
        admission_checkpoint: bool = False,
    ) -> dict[str, Any]:
        record = {
            "workspace_id": channel.workspace_id,
            "channel_id": channel.channel_id,
            "manifest_digest": channel.manifest_digest,
            "digest": channel.digest,
            "version": channel.version,
            "previous_hash": channel.previous_hash,
            "document_type": document_type,
            "serialized": channel.serialized,
        }
        if admission_checkpoint:
            record["admission_checkpoint"] = True
        return record

    def _private_event_is_currently_entitled(
        self,
        current: VerifiedWorkspaceChannel,
        event_channel: VerifiedWorkspaceChannel,
        *,
        local_member_id: str,
        author_member_id: str,
    ) -> bool:
        if (
            current.visibility != "private"
            or event_channel.visibility != "private"
            or current.channel_id != event_channel.channel_id
            or local_member_id not in current.member_ids
            or local_member_id not in event_channel.member_ids
            or author_member_id not in current.member_ids
        ):
            return False
        cursor = current
        for _ in range(MAX_CHANNEL_FETCH_CONTROLS):
            if cursor.digest == event_channel.digest:
                return True
            if not isinstance(cursor.previous_hash, str):
                return False
            predecessor = self._workspace_channel_by_digest(cursor.previous_hash)
            if predecessor is None:
                return False
            cursor = predecessor
        return False

    def _private_channel_admission_version(
        self, channel: VerifiedWorkspaceChannel, member_id: str
    ) -> int | None:
        if channel.visibility != "private" or member_id not in channel.member_ids:
            return None
        current = channel
        admission_version = current.version
        while isinstance(current.previous_hash, str):
            previous = self._workspace_channel_by_digest(current.previous_hash)
            if (
                previous is None
                or previous.visibility != "private"
                or member_id not in previous.member_ids
            ):
                break
            admission_version = previous.version
            current = previous
        return admission_version

    def _workspace_channel_version_record(
        self, channel: VerifiedWorkspaceChannel
    ) -> tuple[str, str, dict[str, Any]]:
        return (
            "workspace_channel_version",
            self._workspace_channel_version_id(
                channel.workspace_id, channel.channel_id, channel.version
            ),
            {
                "workspace_id": channel.workspace_id,
                "channel_id": channel.channel_id,
                "version": channel.version,
                "digest": channel.digest,
            },
        )

    def _workspace_public_channel_entries(
        self, workspace_id: str
    ) -> list[tuple[str, int, str]]:
        entries = [
            (item["id"], int(item["version"]), item["head_hash"])
            for item in self.store.list("workspace_channel")
            if item.get("workspace_id") == workspace_id
            and item.get("visibility") == "public"
            and item.get("state") != "forked"
        ]
        entries.sort()
        if len(entries) > MAX_RETAINED_PUBLIC_CHANNELS:
            raise ValidationError("Workspace public channel directory is too large")
        return entries

    def _workspace_channel_summary_documents(
        self,
        workspace: dict[str, Any],
        manifest: VerifiedWorkspaceManifest,
        identity: RNS.Identity,
        session_id: str,
    ) -> list[str]:
        entries = self._workspace_public_channel_entries(workspace["id"])
        pages = [
            entries[index : index + MAX_CHANNEL_SUMMARY_ENTRIES]
            for index in range(0, len(entries), MAX_CHANNEL_SUMMARY_ENTRIES)
        ] or [[]]
        return [
            create_workspace_channel_summary(
                identity,
                manifest=manifest,
                member_id=workspace["local_member_id"],
                device_id=workspace["local_device_id"],
                session_id=session_id,
                entries=page,
                page_index=index,
                page_count=len(pages),
            )
            for index, page in enumerate(pages)
        ]

    def _workspace_channel_summary_deliveries(
        self,
        workspace: dict[str, Any],
        manifest: VerifiedWorkspaceManifest,
        identity: RNS.Identity,
        session_id: str,
        recipients: Iterable[tuple[str, Any]],
    ) -> list[dict[str, Any]]:
        documents = self._workspace_channel_summary_documents(
            workspace, manifest, identity, session_id
        )
        return [
            self._workspace_delivery_record(
                workspace_id=workspace["id"],
                recipient_member_id=member_id,
                recipient_device=device,
                kind="workspace_channel_summary",
                document=document,
                priority=1,
            )
            for member_id, device in recipients
            for document in documents
        ]

    def _workspace_channel_control_chain(
        self,
        channel: dict[str, Any],
        *,
        known_head: str | None = None,
        limit: int = MAX_CHANNEL_FETCH_CONTROLS,
    ) -> list[dict[str, Any]]:
        controls: list[dict[str, Any]] = []
        digest: str | None = channel.get("head_hash")
        seen: set[str] = set()
        while isinstance(digest, str) and digest != known_head:
            if digest in seen or len(controls) >= limit:
                raise ValidationError("Workspace channel control chain is unavailable")
            seen.add(digest)
            control = self.store.get(
                "workspace_channel_control",
                self._workspace_channel_control_id(digest),
            )
            if control is None:
                raise ValidationError("Workspace channel control chain is unavailable")
            controls.append(control)
            digest = control.get("previous_hash")
        if known_head is not None and digest != known_head:
            raise ValidationError("Known workspace channel head is not an ancestor")
        controls.reverse()
        return controls

    def _mark_workspace_channel_discovery_incomplete(self, workspace_id: str) -> None:
        workspace = self.store.get(
            "workspace", self._workspace_record_id(workspace_id)
        )
        if workspace is None:
            return
        workspace["channel_discovery"] = "incomplete"
        workspace["updated_at"] = time.time()
        self.store.put("workspace", self._workspace_record_id(workspace_id), workspace)

    def _recompute_workspace_channel_discovery(self, workspace_id: str) -> None:
        workspace = self._require_workspace(workspace_id)
        if workspace.get("state") not in {"active", "incomplete_sync"}:
            return
        manifest = self._workspace_current_manifest(workspace)
        expected_devices = {
            device.device_id
            for member in active_members(manifest)
            if member.member_id != workspace["local_member_id"]
            for device in member.devices
        }
        local_entries = self._workspace_public_channel_entries(workspace_id)
        converged = True
        for device_id in expected_devices:
            record = self.store.get(
                "workspace_channel_discovery",
                self._workspace_channel_discovery_id(workspace_id, device_id),
            )
            if (
                record is None
                or record.get("manifest_digest") != manifest.digest
                or not record.get("complete")
            ):
                converged = False
                break
            remote_entries = [tuple(item) for item in record.get("entries", [])]
            if remote_entries != local_entries:
                converged = False
                break
        state = "converged" if converged else "incomplete"
        if workspace.get("channel_discovery") == state:
            return
        workspace["channel_discovery"] = state
        workspace["updated_at"] = time.time()
        self.store.put("workspace", self._workspace_record_id(workspace_id), workspace)
        self._workspace_changed(workspace_id, resource_kind="channel_discovery")

    @staticmethod
    def _member_summary(member: Any) -> dict[str, Any]:
        device = member.devices[0]
        return {
            "id": member.member_id,
            "display_name": member.display_name,
            "role": member.role.value,
            "status": member.status,
            "short_id": _short_id(member.member_id),
            "device": {
                "id": device.device_id,
                "destination_hash": device.destination_hash.hex(),
                "fingerprint": device.fingerprint,
            },
        }

    def _apply_manifest_to_workspace(
        self, workspace: dict[str, Any], manifest: VerifiedWorkspaceManifest
    ) -> dict[str, Any]:
        previous_state = workspace.get("state")
        local_member = find_member(manifest, workspace["local_member_id"])
        workspace["name"] = manifest.name
        workspace["description"] = manifest.description
        workspace["epoch"] = manifest.epoch
        workspace["manifest_hash"] = manifest.digest
        workspace["authority_device_id"] = manifest.authority_device_id
        workspace["retention_days"] = manifest.retention_days
        workspace["policies"] = {
            "channel_creation": manifest.channel_creation.value,
            "posting": manifest.posting.value,
            "invitation_requests": manifest.invitation_requests.value,
        }
        workspace["members"] = [self._member_summary(item) for item in manifest.members]
        workspace["channel_discovery"] = (
            "converged" if len(active_members(manifest)) <= 1 else "incomplete"
        )
        workspace["authorization_generation"] = int(
            workspace.get("authorization_generation", 0)
        ) + 1
        workspace["updated_at"] = time.time()
        if manifest.status == "closed":
            workspace["state"] = "closed"
        elif local_member is None or local_member.status == "removed":
            workspace["state"] = "removed"
        elif local_member.status == "left":
            workspace["state"] = "left"
        elif previous_state == "incomplete_sync":
            workspace["state"] = "incomplete_sync"
            workspace["local_role"] = local_member.role.value
        else:
            workspace["state"] = "active"
            workspace["local_role"] = local_member.role.value
        return workspace

    @staticmethod
    def _workspace_manifest_member_inputs(
        manifest: VerifiedWorkspaceManifest,
        *,
        replacement_member_id: str | None = None,
        replacement_display_name: str | None = None,
        replacement_device: str | None = None,
        replacement_status: str | None = None,
    ) -> list[WorkspaceManifestMemberInput]:
        inputs: list[WorkspaceManifestMemberInput] = []
        for member in manifest.members:
            replacing = member.member_id == replacement_member_id
            inputs.append(
                WorkspaceManifestMemberInput(
                    member.member_id,
                    (
                        replacement_display_name
                        if replacing and replacement_display_name is not None
                        else member.display_name
                    ),
                    member.role,
                    (
                        [replacement_device]
                        if replacing and replacement_device is not None
                        else [device.serialized for device in member.devices]
                    ),
                    (
                        replacement_status
                        if replacing and replacement_status is not None
                        else member.status
                    ),
                )
            )
        return inputs

    @staticmethod
    def _workspace_manifest_recipients(
        manifest: VerifiedWorkspaceManifest,
        *,
        excluding_member_id: str | None,
        include_member_ids: set[str] | None = None,
    ) -> list[tuple[str, Any]]:
        recipients: list[tuple[str, Any]] = []
        included = include_member_ids or set()
        for member in manifest.members:
            if member.member_id == excluding_member_id:
                continue
            if member.status != "active" and member.member_id not in included:
                continue
            recipients.extend((member.member_id, device) for device in member.devices)
        return recipients

    def _workspace_manifest_deliveries(
        self,
        workspace_id: str,
        manifests: Iterable[VerifiedWorkspaceManifest],
        recipients: Iterable[tuple[str, Any]],
    ) -> list[dict[str, Any]]:
        checked_manifests = list(manifests)
        checked_recipients = list(recipients)
        return [
            self._workspace_delivery_record(
                workspace_id=workspace_id,
                recipient_member_id=member_id,
                recipient_device=device,
                kind="workspace_manifest_root",
                document=manifest.serialized,
                priority=0,
            )
            for member_id, device in checked_recipients
            for manifest in checked_manifests
        ]

    def _workspace_manifest_chain_after(
        self,
        workspace_id: str,
        epoch: int,
        final_manifest: VerifiedWorkspaceManifest,
    ) -> list[VerifiedWorkspaceManifest]:
        manifests: list[VerifiedWorkspaceManifest] = []
        for next_epoch in range(epoch + 1, final_manifest.epoch):
            manifest = self._workspace_manifest_at_epoch(workspace_id, next_epoch)
            if manifest is None:
                raise ValidationError("Workspace manifest catch-up chain is unavailable")
            manifests.append(manifest)
        manifests.append(final_manifest)
        return manifests

    def _apply_manifest_public_identities(
        self, workspace: dict[str, Any], manifest: VerifiedWorkspaceManifest
    ) -> None:
        for member in workspace["members"]:
            verified = find_member(manifest, member["id"])
            if verified is not None:
                member["device"]["public_identity"] = _b64(
                    verified.devices[0].public_identity
                )

    @staticmethod
    def _manifest_record(manifest: VerifiedWorkspaceManifest) -> dict[str, Any]:
        return {
            "workspace_id": manifest.workspace_id,
            "epoch": manifest.epoch,
            "digest": manifest.digest,
            "previous_manifest_hash": manifest.previous_manifest_hash,
            "serialized": manifest.serialized,
        }

    def _manifest_epoch_record(
        self, manifest: VerifiedWorkspaceManifest
    ) -> tuple[str, str, dict[str, Any]]:
        return (
            "workspace_manifest_epoch",
            self._workspace_manifest_epoch_id(manifest.workspace_id, manifest.epoch),
            {
                "workspace_id": manifest.workspace_id,
                "epoch": manifest.epoch,
                "digest": manifest.digest,
            },
        )

    @staticmethod
    def _channel_record(channel: VerifiedWorkspaceChannel) -> dict[str, Any]:
        return {
            "id": channel.channel_id,
            "workspace_id": channel.workspace_id,
            "name": channel.name,
            "name_key": channel_name_key(channel.name),
            "topic": channel.topic,
            "visibility": channel.visibility,
            "state": "archived" if channel.archived else "active",
            "manager_member_id": channel.manager_member_id,
            "manager_device_id": channel.manager_device_id,
            "member_ids": list(channel.member_ids),
            "version": channel.version,
            "head_hash": channel.digest,
            "manifest_digest": channel.manifest_digest,
            "unread_count": 0,
            "short_id": _short_id(channel.channel_id),
            "created_at": float(channel.created_at),
            "updated_at": float(channel.created_at),
        }

    def _public_workspace(self, workspace: dict[str, Any]) -> dict[str, Any]:
        public = {
            key: value
            for key, value in workspace.items()
            if key
            not in {
                "genesis",
                "pending_invitation",
                "next_sender_sequence",
                "last_event_digest",
                "members",
            }
        }
        public["members"] = [
            {
                **{key: value for key, value in member.items() if key != "device"},
                "device": {
                    key: value
                    for key, value in member.get("device", {}).items()
                    if key != "public_identity"
                },
            }
            for member in workspace.get("members", [])
        ]
        public.setdefault(
            "channel_discovery",
            "converged"
            if sum(
                member.get("status") == "active"
                for member in workspace.get("members", [])
            )
            <= 1
            else "incomplete",
        )
        return public

    def _public_workspace_channel(
        self,
        channel: dict[str, Any],
        *,
        duplicate_name: bool = False,
    ) -> dict[str, Any]:
        public = dict(channel)
        workspace_id = str(channel.get("workspace_id", ""))
        channel_id = str(channel.get("id", ""))
        workspace = self.store.get(
            "workspace", self._workspace_record_id(workspace_id)
        )
        is_general = bool(
            workspace is not None
            and workspace.get("general_channel_id") == channel_id
        )
        public.setdefault(
            "name_key", channel_name_key(str(channel.get("name", "")))
        )
        public.setdefault("short_id", _short_id(channel_id))
        subscription = self.store.get(
            "workspace_subscription",
            self.store.opaque_id(
                "workspace-subscription", workspace_id, channel_id
            ),
        )
        public["is_general"] = is_general
        public["subscribed"] = is_general or bool(
            subscription and subscription.get("subscribed")
        )
        public["duplicate_name"] = duplicate_name
        public["display_name"] = (
            f"{channel.get('name', '')} · {channel.get('short_id', _short_id(channel_id))}"
            if duplicate_name
            else channel.get("name", "")
        )
        if not public["subscribed"]:
            public["unread_count"] = 0
        return public

    def _workspace_delivery_summary(
        self,
        event_id: str,
    ) -> dict[str, int]:
        # Compatibility fallback for a message written before materialized
        # per-device state existed. New receipt handling never calls this scan.
        deliveries = [
            item
            for item in self.store.list("workspace_delivery")
            if item.get("event_id") == event_id
            and item.get("kind") == "workspace_event"
        ]
        return self._workspace_delivery_summary_from_devices(
            {
                item["recipient_device_id"]: {
                    "member_id": item["recipient_member_id"],
                    "state": item["state"],
                }
                for item in deliveries
            }
        )

    @staticmethod
    def _workspace_delivery_summary_from_devices(
        devices: dict[str, dict[str, str]],
    ) -> dict[str, int]:
        people: dict[str, list[str]] = defaultdict(list)
        for item in devices.values():
            people[item["member_id"]].append(item["state"])
        reached_states = {
            DeliveryState.RECEIVED_BY_ENDPOINT.value,
            DeliveryState.DELIVERED.value,
        }
        terminal_failure_states = {
            DeliveryState.FAILED.value,
            DeliveryState.EXPIRED.value,
            DeliveryState.CANCELLED.value,
        }
        reached_people = sum(
            any(state in reached_states for state in states)
            for states in people.values()
        )
        partial_people = sum(
            any(state in reached_states for state in states)
            and not all(state in reached_states for state in states)
            for states in people.values()
        )
        failed_people = sum(
            not any(state in reached_states for state in states)
            and all(state in terminal_failure_states for state in states)
            for states in people.values()
        )
        reached_devices = sum(
            item["state"]
            in reached_states
            for item in devices.values()
        )
        failed_devices = sum(
            item["state"] == DeliveryState.FAILED.value
            for item in devices.values()
        )
        expired_devices = sum(
            item["state"] == DeliveryState.EXPIRED.value
            for item in devices.values()
        )
        cancelled_devices = sum(
            item["state"] == DeliveryState.CANCELLED.value
            for item in devices.values()
        )
        return {
            "people_total": len(people),
            "people_reached": reached_people,
            "people_partial": partial_people,
            "people_pending": max(0, len(people) - reached_people - failed_people),
            "people_failed": failed_people,
            "devices_total": len(devices),
            "devices_reached": reached_devices,
            "devices_pending": max(
                0,
                len(devices)
                - reached_devices
                - failed_devices
                - expired_devices
                - cancelled_devices,
            ),
            "devices_failed": failed_devices,
            "devices_expired": expired_devices,
            "devices_cancelled": cancelled_devices,
        }

    def _public_workspace_message(self, message: dict[str, Any]) -> dict[str, Any]:
        public = dict(message)
        delivery_devices = public.pop("delivery_devices", None)
        if isinstance(delivery_devices, dict):
            public["deliveries"] = [
                {
                    "member_id": item["member_id"],
                    "member_display_name": item.get(
                        "member_display_name", "Member"
                    ),
                    "device_id": device_id,
                    "device_short_id": _short_id(device_id),
                    "state": item["state"],
                }
                for device_id, item in sorted(delivery_devices.items())
            ]
        if message.get("direction") == "outbound" and "delivery_summary" not in public:
            public["delivery_summary"] = self._workspace_delivery_summary(message["id"])
        return public

    def _workspace_hints(self) -> list[dict[str, Any]]:
        network = getattr(self, "network", None)
        return [] if network is None else network.invitation_hints()[:2]

    def _remember_workspace_devices(self, workspace: dict[str, Any]) -> None:
        network = getattr(self, "network", None)
        if network is None:
            return
        for member in workspace.get("members", []):
            device = member.get("device", {})
            destination = device.get("destination_hash")
            public_identity = device.get("public_identity")
            if not isinstance(destination, str) or not isinstance(public_identity, str):
                continue
            try:
                network.remember_contact(_unb64(public_identity), bytes.fromhex(destination))
            except Exception:
                continue

    def _workspace_channel_deliveries(
        self,
        manifest: VerifiedWorkspaceManifest,
        *,
        excluding_member_id: str,
        kind: str,
        document: str,
        priority: int = 1,
        recipients: Iterable[tuple[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            value = json.loads(document)
            conversation_id = value.get("channel_id")
            if conversation_id is None and isinstance(value.get("offer"), dict):
                conversation_id = value["offer"].get("channel_id")
        except (TypeError, json.JSONDecodeError):
            conversation_id = None
        targets = (
            list(recipients)
            if recipients is not None
            else self._workspace_manifest_recipients(
                manifest, excluding_member_id=excluding_member_id
            )
        )
        return [
            self._workspace_delivery_record(
                workspace_id=manifest.workspace_id,
                recipient_member_id=member_id,
                recipient_device=device,
                kind=kind,
                document=document,
                conversation_id=(
                    conversation_id if isinstance(conversation_id, str) else None
                ),
                priority=priority,
            )
            for member_id, device in targets
        ]

    @staticmethod
    def _workspace_private_recipients(
        manifest: VerifiedWorkspaceManifest,
        member_ids: Iterable[str],
        *,
        excluding_member_id: str | None = None,
    ) -> list[tuple[str, Any]]:
        allowed = set(member_ids)
        return [
            (member.member_id, device)
            for member in active_members(manifest)
            if member.member_id in allowed
            and member.member_id != excluding_member_id
            for device in member.devices
        ]

    def _workspace_channel_recipients(
        self,
        manifest: VerifiedWorkspaceManifest,
        channel: VerifiedWorkspaceChannel,
        *,
        excluding_member_id: str | None = None,
    ) -> list[tuple[str, Any]]:
        if channel.visibility == "private":
            return self._workspace_private_recipients(
                manifest,
                channel.member_ids,
                excluding_member_id=excluding_member_id,
            )
        return self._workspace_manifest_recipients(
            manifest,
            excluding_member_id=excluding_member_id,
        )

    @staticmethod
    def _channel_creation_allowed(
        manifest: VerifiedWorkspaceManifest, member: Any
    ) -> bool:
        return (
            member.status == "active"
            and (
                manifest.channel_creation
                == WorkspaceChannelCreationPolicy.ALL_MEMBERS
                or member.role == WorkspaceRole.OWNER
            )
        )

    @staticmethod
    def _posting_allowed(
        manifest: VerifiedWorkspaceManifest, member: Any
    ) -> bool:
        return (
            member.status == "active"
            and (
                manifest.posting == WorkspacePostingPolicy.ALL_MEMBERS
                or member.role == WorkspaceRole.OWNER
            )
        )

    def create_workspace(
        self,
        operation_id: Any,
        name: Any,
        description: Any = "",
    ) -> dict[str, Any]:
        payload = {"name": name, "description": description}
        operation_id, digest, replay = self._workspace_operation(
            "create_workspace", operation_id, payload
        )
        if replay is not None:
            return replay
        if len(self.store.list("workspace")) >= MAX_WORKSPACES:
            raise ValidationError("This profile already has 16 workspaces")
        profile = self._require_profile()
        identity = self._identity
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        created = create_workspace_genesis(
            identity,
            name,
            description,
            profile["display_name"],
            owner_hints=self._workspace_hints(),
        )
        genesis = verify_workspace_genesis(created.serialized)
        manifest_raw = create_workspace_manifest(
            identity,
            workspace_id=genesis.workspace_id,
            epoch=1,
            previous_manifest_hash=genesis.digest,
            name=genesis.name,
            description=genesis.description,
            authority_device_id=genesis.authority_device_id,
            members=[
                WorkspaceManifestMemberInput(
                    genesis.owner_member_id,
                    genesis.owner_device.display_name,
                    WorkspaceRole.OWNER,
                    [created.device_card],
                )
            ],
        )
        manifest = verify_workspace_manifest_transition(manifest_raw, genesis)
        channel_id = _new_id()
        channel_raw = create_workspace_channel_record(
            identity,
            workspace_id=genesis.workspace_id,
            channel_id=channel_id,
            manifest_digest=manifest.digest,
            name="general",
            topic="",
            manager_member_id=genesis.owner_member_id,
            manager_device_id=genesis.authority_device_id,
        )
        channel = verify_workspace_channel_record(channel_raw, manifest=manifest)
        now = time.time()
        workspace = {
            "id": genesis.workspace_id,
            "name": manifest.name,
            "description": manifest.description,
            "state": "active",
            "local_role": WorkspaceRole.OWNER.value,
            "local_member_id": genesis.owner_member_id,
            "local_device_id": genesis.authority_device_id,
            "owner_member_id": genesis.owner_member_id,
            "authority_device_id": genesis.authority_device_id,
            "epoch": manifest.epoch,
            "manifest_hash": manifest.digest,
            "genesis_digest": genesis.digest,
            "genesis": genesis.serialized,
            "general_channel_id": channel.channel_id,
            "channel_discovery": "converged",
            "retention_days": manifest.retention_days,
            "policies": {
                "channel_creation": manifest.channel_creation.value,
                "posting": manifest.posting.value,
                "invitation_requests": manifest.invitation_requests.value,
            },
            "members": [self._member_summary(item) for item in manifest.members],
            "authorization_generation": 1,
            "retention_generation": 1,
            "created_at": now,
            "updated_at": now,
        }
        # Keep network material sealed with the member summary, but never expose
        # it through the presentation model.
        workspace["members"][0]["device"]["public_identity"] = _b64(
            genesis.owner_device.public_identity
        )
        channel_record = self._channel_record(channel)
        index_id = self._workspace_index_record_id(workspace["id"], channel.channel_id)
        index = {
            "workspace_id": workspace["id"],
            "conversation_id": channel.channel_id,
            "head_page": None,
            "count": 0,
            "high_water": 0,
            "authorization_generation": 1,
            "retention_generation": 1,
        }
        subscription_id = self.store.opaque_id(
            "workspace-subscription", workspace["id"], channel.channel_id
        )
        outcome = self._public_workspace(workspace)
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [
                ("workspace", self._workspace_record_id(workspace["id"]), workspace),
                (
                    "workspace_manifest",
                    self._workspace_manifest_record_id(manifest.digest),
                    self._manifest_record(manifest),
                ),
                self._manifest_epoch_record(manifest),
                (
                    "workspace_channel",
                    self._workspace_channel_record_id(channel.channel_id),
                    channel_record,
                ),
                (
                    "workspace_channel_control",
                    self._workspace_channel_control_id(channel.digest),
                    self._workspace_channel_control_record(
                        channel, document_type="workspace_channel_record"
                    ),
                ),
                self._workspace_channel_version_record(channel),
                ("workspace_conversation_index", index_id, index),
                (
                    "workspace_subscription",
                    subscription_id,
                    {
                        "workspace_id": workspace["id"],
                        "conversation_id": channel.channel_id,
                        "subscribed": True,
                    },
                ),
                (
                    "workspace_read_state",
                    self.store.opaque_id(
                        "workspace-read-state", workspace["id"], channel.channel_id
                    ),
                    {
                        "workspace_id": workspace["id"],
                        "conversation_id": channel.channel_id,
                        "high_water": 0,
                    },
                ),
            ],
        )
        self._workspace_changed(workspace["id"])
        return committed

    def create_workspace_invitation_command(
        self,
        workspace_id: Any,
        operation_id: Any,
        lifetime_days: Any = 7,
    ) -> dict[str, Any]:
        payload = {"workspace_id": workspace_id, "lifetime_days": lifetime_days}
        operation_id, digest, replay = self._workspace_operation(
            "create_workspace_invitation", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if workspace.get("state") != "active" or workspace.get("local_role") != "owner":
            raise ContactNotApproved("Only the active workspace owner can invite members")
        if len(self._workspace_current_manifest(workspace).members) >= MAX_ACTIVE_MEMBERS:
            raise ValidationError("A workspace supports at most eight people")
        now = time.time()
        expired_records: list[tuple[str, str, dict[str, Any]]] = []
        for record_id, existing in self.store.items("workspace_invitation"):
            if (
                existing.get("workspace_id") != workspace_id
                or existing.get("state") != "active"
            ):
                continue
            if float(existing.get("expires_at", 0)) <= now:
                existing = dict(existing)
                existing["state"] = "expired"
                existing["updated_at"] = now
                expired_records.append(("workspace_invitation", record_id, existing))
                continue
        if (
            isinstance(lifetime_days, bool)
            or not isinstance(lifetime_days, int)
            or not 1 <= lifetime_days <= 30
        ):
            raise ValidationError("Workspace invitation lifetime is invalid")
        identity = self._identity
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        manifest_record = self.store.get(
            "workspace_manifest",
            self._workspace_manifest_record_id(workspace["manifest_hash"]),
        )
        if manifest_record is None:
            raise ValidationError("Workspace manifest is unavailable")
        raw = create_workspace_invitation(
            identity,
            genesis=workspace["genesis"],
            manifest=manifest_record["serialized"],
            lifetime_seconds=min(
                lifetime_days * 24 * 60 * 60, MAX_INVITATION_LIFETIME_SECONDS
            ),
        )
        invite = verify_workspace_invitation(raw)
        invitation_id = self._workspace_invitation_record_id(invite.nonce)
        record = {
            "id": invitation_id,
            "workspace_id": workspace["id"],
            "nonce": invite.nonce.hex(),
            "offered_manifest_digest": invite.offered_manifest_digest,
            "state": "active",
            "document": invite.serialized,
            "created_at": float(invite.created_at),
            "expires_at": float(invite.expires_at),
        }
        outcome = {
            "id": invitation_id,
            "workspace_id": workspace["id"],
            **workspace_invitation_formats(raw),
        }
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [*expired_records, ("workspace_invitation", invitation_id, record)],
        )
        self._workspace_changed(workspace["id"], resource_kind="invitation")
        return committed

    def preview_workspace_invitation(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, str):
            raise ValidationError("Workspace invitation must be text")
        return verify_workspace_invitation(raw).preview()

    def revoke_workspace_invitation(
        self, workspace_id: Any, invitation_id: Any, operation_id: Any
    ) -> dict[str, Any]:
        payload = {"workspace_id": workspace_id, "invitation_id": invitation_id}
        operation_id, digest, replay = self._workspace_operation(
            "revoke_workspace_invitation", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if workspace.get("local_role") != "owner" or workspace.get("state") != "active":
            raise ContactNotApproved("Only the active workspace owner can revoke invitations")
        if not isinstance(invitation_id, str):
            raise ValidationError("Workspace invitation ID is invalid")
        invitation = self.store.get("workspace_invitation", invitation_id)
        if invitation is None or invitation.get("workspace_id") != workspace_id:
            raise ValidationError("Workspace invitation does not exist")
        if invitation.get("state") == "consumed":
            raise ValidationError("Workspace invitation was already used")
        invitation["state"] = "revoked"
        invitation["updated_at"] = time.time()
        outcome = {"id": invitation_id, "workspace_id": workspace_id, "state": "revoked"}
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [("workspace_invitation", invitation_id, invitation)],
        )
        self._workspace_changed(workspace_id, resource_kind="invitation")
        return committed

    def _workspace_delivery_record(
        self,
        *,
        workspace_id: str,
        recipient_member_id: str,
        recipient_device: Any,
        kind: str,
        document: str,
        event_id: str | None = None,
        conversation_id: str | None = None,
        priority: int = 2,
    ) -> dict[str, Any]:
        now = time.time()
        return {
            "id": _new_id(),
            "workspace_id": workspace_id,
            "recipient_member_id": recipient_member_id,
            "recipient_device_id": recipient_device.device_id,
            "recipient_display_name": recipient_device.display_name,
            "recipient_destination": recipient_device.destination_hash.hex(),
            "recipient_public_identity": _b64(recipient_device.public_identity),
            "recipient_hints": [dict(item) for item in recipient_device.hints[:2]],
            "kind": kind,
            "document": document,
            "event_id": event_id,
            "conversation_id": conversation_id,
            "priority": priority,
            "state": DeliveryState.QUEUED.value,
            "attempt_count": 0,
            "next_attempt_at": now,
            "created_at": now,
            "expires_at": now + DELIVERY_WINDOW_SECONDS,
        }

    def _cancel_workspace_member_deliveries(
        self, workspace_id: str, member_id: str
    ) -> tuple[
        list[tuple[str, str, dict[str, Any]]], set[str]
    ]:
        now = time.time()
        records: list[tuple[str, str, dict[str, Any]]] = []
        cancelled_ids: list[str] = []
        outbound_ids: set[str] = set()
        changed_messages: dict[str, dict[str, Any]] = {}
        for delivery_id, stored in self.store.items("workspace_delivery"):
            if (
                stored.get("workspace_id") != workspace_id
                or stored.get("recipient_member_id") != member_id
                or stored.get("state") in FINAL_DELIVERY_STATES
            ):
                continue
            delivery = dict(stored)
            delivery["state"] = DeliveryState.CANCELLED.value
            delivery["cancelled_at"] = now
            records.append(("workspace_delivery", delivery_id, delivery))
            cancelled_ids.append(delivery_id)
            outbound_ids.add(delivery_id)
            event_id = delivery.get("event_id")
            if not isinstance(event_id, str):
                continue
            message_id = self._workspace_message_record_id(event_id)
            message = changed_messages.get(message_id)
            if message is None:
                stored_message = self.store.get("workspace_message_state", message_id)
                if stored_message is None:
                    continue
                message = dict(stored_message)
            devices = dict(message.get("delivery_devices", {}))
            existing = dict(devices.get(delivery["recipient_device_id"], {}))
            existing.update(
                {
                    "member_id": member_id,
                    "member_display_name": delivery.get(
                        "recipient_display_name", "Member"
                    ),
                    "state": DeliveryState.CANCELLED.value,
                }
            )
            devices[delivery["recipient_device_id"]] = existing
            message["delivery_devices"] = devices
            message["delivery_summary"] = (
                self._workspace_delivery_summary_from_devices(devices)
            )
            changed_messages[message_id] = message
        records.extend(
            ("workspace_message_state", message_id, message)
            for message_id, message in changed_messages.items()
        )
        return records, outbound_ids

    def _cancel_private_channel_member_deliveries(
        self, workspace_id: str, channel_id: str, member_ids: set[str]
    ) -> tuple[list[tuple[str, str, dict[str, Any]]], set[str]]:
        now = time.time()
        records: list[tuple[str, str, dict[str, Any]]] = []
        cancelled_ids: list[str] = []
        outbound_ids: set[str] = set()
        changed_messages: dict[str, dict[str, Any]] = {}
        for delivery_id, stored in self.store.items("workspace_delivery"):
            if (
                stored.get("workspace_id") != workspace_id
                or stored.get("conversation_id") != channel_id
                or stored.get("recipient_member_id") not in member_ids
                or stored.get("state") in FINAL_DELIVERY_STATES
            ):
                continue
            delivery = dict(stored)
            delivery["state"] = DeliveryState.CANCELLED.value
            delivery["cancelled_at"] = now
            records.append(("workspace_delivery", delivery_id, delivery))
            cancelled_ids.append(delivery_id)
            outbound_ids.add(delivery_id)
            event_id = delivery.get("event_id")
            if not isinstance(event_id, str):
                continue
            message_id = self._workspace_message_record_id(event_id)
            message = changed_messages.get(message_id)
            if message is None:
                stored_message = self.store.get("workspace_message_state", message_id)
                if stored_message is None:
                    continue
                message = dict(stored_message)
            devices = dict(message.get("delivery_devices", {}))
            existing = dict(devices.get(delivery["recipient_device_id"], {}))
            existing.update(
                {
                    "member_id": delivery["recipient_member_id"],
                    "member_display_name": delivery.get(
                        "recipient_display_name", "Member"
                    ),
                    "state": DeliveryState.CANCELLED.value,
                }
            )
            devices[delivery["recipient_device_id"]] = existing
            message["delivery_devices"] = devices
            message["delivery_summary"] = (
                self._workspace_delivery_summary_from_devices(devices)
            )
            changed_messages[message_id] = message
        records.extend(
            ("workspace_message_state", message_id, message)
            for message_id, message in changed_messages.items()
        )
        records.extend(self._due_records(remove=cancelled_ids))
        return records, outbound_ids

    def submit_workspace_join(
        self, invitation: Any, operation_id: Any
    ) -> dict[str, Any]:
        payload = {"invitation": invitation}
        operation_id, digest, replay = self._workspace_operation(
            "submit_workspace_join", operation_id, payload
        )
        if replay is not None:
            return replay
        if not isinstance(invitation, str):
            raise ValidationError("Workspace invitation must be text")
        invite = verify_workspace_invitation(invitation)
        if self.store.get("workspace", self._workspace_record_id(invite.workspace_id)) is not None:
            raise ValidationError("This workspace is already known on this device")
        if len(self.store.list("workspace")) >= MAX_WORKSPACES:
            raise ValidationError("This profile already has 16 workspaces")
        profile = self._require_profile()
        identity = self._identity
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        join_raw = create_workspace_join(
            identity,
            invite,
            profile["display_name"],
            hints=self._workspace_hints(),
        )
        join = verify_workspace_join(join_raw, invitation=invite)
        owner = find_device(invite.offered_manifest, invite.offered_manifest.authority_device_id)
        if owner is None:
            raise ValidationError("Workspace authority is unavailable")
        delivery = self._workspace_delivery_record(
            workspace_id=invite.workspace_id,
            recipient_member_id=owner[0].member_id,
            recipient_device=owner[1],
            kind="workspace_join",
            document=join.serialized,
            priority=0,
        )
        now = time.time()
        workspace = {
            "id": invite.workspace_id,
            "name": invite.offered_manifest.name,
            "description": invite.offered_manifest.description,
            "state": "joining",
            "local_role": WorkspaceRole.MEMBER.value,
            "local_member_id": join.member_id,
            "local_device_id": join.device.device_id,
            "owner_member_id": invite.genesis.owner_member_id,
            "authority_device_id": invite.offered_manifest.authority_device_id,
            "epoch": invite.offered_manifest.epoch,
            "manifest_hash": invite.offered_manifest.digest,
            "genesis_digest": invite.genesis.digest,
            "genesis": invite.genesis.serialized,
            "general_channel_id": None,
            "channel_discovery": "incomplete",
            "retention_days": invite.offered_manifest.retention_days,
            "policies": {
                "channel_creation": invite.offered_manifest.channel_creation.value,
                "posting": invite.offered_manifest.posting.value,
                "invitation_requests": invite.offered_manifest.invitation_requests.value,
            },
            "members": [
                self._member_summary(item) for item in invite.offered_manifest.members
            ]
            + [
                {
                    "id": join.member_id,
                    "display_name": join.device.display_name,
                    "role": WorkspaceRole.MEMBER.value,
                    "status": "joining",
                    "short_id": _short_id(join.member_id),
                    "device": {
                        "id": join.device.device_id,
                        "destination_hash": join.device.destination_hash.hex(),
                        "fingerprint": join.device.fingerprint,
                        "public_identity": _b64(join.device.public_identity),
                    },
                }
            ],
            "authorization_generation": 1,
            "retention_generation": 1,
            "created_at": now,
            "updated_at": now,
        }
        for member in workspace["members"]:
            if member["id"] == owner[0].member_id:
                member["device"]["public_identity"] = _b64(owner[1].public_identity)
        local_invitation_id = self._workspace_invitation_record_id(invite.nonce)
        invitation_record = {
            "id": local_invitation_id,
            "workspace_id": invite.workspace_id,
            "nonce": invite.nonce.hex(),
            "state": "submitted",
            "document": invite.serialized,
            "join_document": join.serialized,
            "created_at": float(invite.created_at),
            "expires_at": float(invite.expires_at),
        }
        outcome = self._public_workspace(workspace)
        records = [
            ("workspace", self._workspace_record_id(workspace["id"]), workspace),
            (
                "workspace_manifest",
                self._workspace_manifest_record_id(invite.offered_manifest.digest),
                self._manifest_record(invite.offered_manifest),
            ),
            self._manifest_epoch_record(invite.offered_manifest),
            ("workspace_invitation", local_invitation_id, invitation_record),
            ("workspace_delivery", delivery["id"], delivery),
            *self._due_records(add=[delivery]),
        ]
        committed = self.store.commit_operation(
            operation_id, digest, outcome, records
        )
        network = getattr(self, "network", None)
        if network is not None:
            network.remember_contact(owner[1].public_identity, owner[1].destination_hash)
        self._workspace_changed(workspace["id"])
        return committed

    def _receive_workspace_join(
        self, wire: WorkspaceWirePayload, source_hash: Any = None
    ) -> None:
        join = verify_workspace_join(wire.document)
        if (
            join.workspace_id != wire.workspace_id
            or not isinstance(source_hash, bytes)
            or join.device.destination_hash != source_hash
        ):
            return
        workspace = self.store.get(
            "workspace", self._workspace_record_id(join.workspace_id)
        )
        if workspace is None or workspace.get("state") != "active" or workspace.get(
            "local_role"
        ) != "owner":
            return
        invitation_id = self._workspace_invitation_record_id(join.invite_nonce)
        invitation = self.store.get("workspace_invitation", invitation_id)
        if (
            invitation is None
            or invitation.get("state") != "active"
            or invitation.get("document") != join.invitation.serialized
            or float(invitation.get("expires_at", 0)) < time.time()
        ):
            return
        pending = [
            item
            for item in self.store.list("workspace_join_request")
            if item.get("workspace_id") == join.workspace_id
            and item.get("state") == "pending"
        ]
        if len(pending) >= MAX_PENDING_JOINS:
            return
        if sum(
            1
            for item in pending
            if item.get("source_fingerprint") == join.device.fingerprint
        ) >= MAX_PENDING_JOINS_PER_SOURCE:
            return
        request_id = self.store.opaque_id("workspace-join", join.digest)
        if self.store.get("workspace_join_request", request_id) is not None:
            return
        record = {
            "id": request_id,
            "workspace_id": join.workspace_id,
            "member_id": join.member_id,
            "display_name": join.device.display_name,
            "device_id": join.device.device_id,
            "destination_hash": join.device.destination_hash.hex(),
            "fingerprint": join.device.fingerprint,
            "source_fingerprint": join.device.fingerprint,
            "public_identity": _b64(join.device.public_identity),
            "invitation_id": invitation_id,
            "document": join.serialized,
            "state": "pending",
            "created_at": float(join.created_at),
        }
        self.store.put("workspace_join_request", request_id, record)
        network = getattr(self, "network", None)
        if network is not None:
            network.remember_contact(join.device.public_identity, join.device.destination_hash)
        self._workspace_changed(join.workspace_id, resource_kind="join_request")

    def approve_workspace_join(
        self,
        workspace_id: Any,
        request_id: Any,
        operation_id: Any,
    ) -> dict[str, Any]:
        payload = {"workspace_id": workspace_id, "request_id": request_id}
        operation_id, digest, replay = self._workspace_operation(
            "approve_workspace_join", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if workspace.get("state") != "active" or workspace.get("local_role") != "owner":
            raise ContactNotApproved("Only the active workspace owner can approve joins")
        if not isinstance(request_id, str):
            raise ValidationError("Workspace join request ID is invalid")
        request = self.store.get("workspace_join_request", request_id)
        if (
            request is None
            or request.get("workspace_id") != workspace_id
            or request.get("state") != "pending"
        ):
            raise ValidationError("Workspace join request is no longer pending")
        invitation = self.store.get(
            "workspace_invitation", request["invitation_id"]
        )
        if invitation is None or invitation.get("state") != "active":
            raise ValidationError("Workspace invitation is no longer active")
        join = verify_workspace_join(
            request["document"], invitation=invitation["document"]
        )
        checked_invitation = verify_workspace_invitation(invitation["document"])
        current = self._workspace_current_manifest(workspace)
        if len(active_members(current)) >= MAX_ACTIVE_MEMBERS:
            raise ValidationError("A workspace supports at most eight active people")
        if find_member(current, join.member_id) is not None:
            raise ValidationError("Workspace member ID is already present")
        identity = self._identity
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        member_inputs = self._workspace_manifest_member_inputs(current)
        member_inputs.append(
            WorkspaceManifestMemberInput(
                join.member_id,
                join.device.display_name,
                WorkspaceRole.MEMBER,
                [join.device.serialized],
            )
        )
        next_raw = create_workspace_manifest(
            identity,
            workspace_id=workspace_id,
            epoch=current.epoch + 1,
            previous_manifest_hash=current.digest,
            name=current.name,
            description=current.description,
            authority_device_id=current.authority_device_id,
            members=member_inputs,
            retention_days=current.retention_days,
            channel_creation=current.channel_creation,
            posting=current.posting,
            invitation_requests=current.invitation_requests,
        )
        next_manifest = verify_workspace_manifest_transition(next_raw, current)
        existing_recipients = self._workspace_manifest_recipients(
            current, excluding_member_id=workspace["local_member_id"]
        )
        self._apply_manifest_to_workspace(workspace, next_manifest)
        self._apply_manifest_public_identities(workspace, next_manifest)
        request["state"] = "approved"
        request["updated_at"] = time.time()
        invitation["state"] = "consumed"
        invitation["consumed_by_member_id"] = join.member_id
        invitation["updated_at"] = time.time()
        public_channels = sorted(
            (
                item
                for item in self.store.list("workspace_channel")
                if item.get("workspace_id") == workspace_id
                and item.get("visibility") == "public"
                and item.get("state") != "forked"
            ),
            key=lambda item: item["id"],
        )
        channel_controls = [
            control
            for public_channel in public_channels
            for control in self._workspace_channel_control_chain(public_channel)
        ]
        manifest_deliveries = self._workspace_manifest_deliveries(
            workspace_id,
            [next_manifest],
            existing_recipients,
        )
        manifest_deliveries.extend(
            self._workspace_manifest_deliveries(
                workspace_id,
                self._workspace_manifest_chain_after(
                    workspace_id,
                    checked_invitation.offered_manifest.epoch,
                    next_manifest,
                ),
                [(join.member_id, join.device)],
            )
        )
        channel_deliveries = [
            self._workspace_delivery_record(
                workspace_id=workspace_id,
                recipient_member_id=join.member_id,
                recipient_device=join.device,
                kind=control.get("document_type", "workspace_channel_record"),
                document=control["serialized"],
                priority=1,
            )
            for control in channel_controls
        ]
        outcome = {
            "request_id": request_id,
            "state": "approved",
            "workspace": self._public_workspace(workspace),
        }
        records = [
            ("workspace", self._workspace_record_id(workspace_id), workspace),
            (
                "workspace_manifest",
                self._workspace_manifest_record_id(next_manifest.digest),
                self._manifest_record(next_manifest),
            ),
            self._manifest_epoch_record(next_manifest),
            ("workspace_join_request", request_id, request),
            ("workspace_invitation", request["invitation_id"], invitation),
            *[
                ("workspace_delivery", delivery["id"], delivery)
                for delivery in manifest_deliveries
            ],
            *[
                ("workspace_delivery", delivery["id"], delivery)
                for delivery in channel_deliveries
            ],
            *self._due_records(add=[*manifest_deliveries, *channel_deliveries]),
        ]
        committed = self.store.commit_operation(
            operation_id, digest, outcome, records
        )
        self._workspace_changed(workspace_id)
        return committed

    def decline_workspace_join(
        self,
        workspace_id: Any,
        request_id: Any,
        operation_id: Any,
    ) -> dict[str, Any]:
        payload = {"workspace_id": workspace_id, "request_id": request_id}
        operation_id, digest, replay = self._workspace_operation(
            "decline_workspace_join", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if workspace.get("local_role") != "owner" or workspace.get("state") != "active":
            raise ContactNotApproved("Only the active workspace owner can decline joins")
        if not isinstance(request_id, str):
            raise ValidationError("Workspace join request ID is invalid")
        request = self.store.get("workspace_join_request", request_id)
        if (
            request is None
            or request.get("workspace_id") != workspace_id
            or request.get("state") != "pending"
        ):
            raise ValidationError("Workspace join request is no longer pending")
        request["state"] = "declined"
        request["updated_at"] = time.time()
        outcome = {"request_id": request_id, "state": "declined"}
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [("workspace_join_request", request_id, request)],
        )
        self._workspace_changed(workspace_id, resource_kind="join_request")
        return committed

    def _append_workspace_event_records(
        self,
        workspace: dict[str, Any],
        event: VerifiedWorkspaceEvent,
        *,
        direction: str,
        author_display_name: str,
    ) -> tuple[list[tuple[str, str, dict[str, Any]]], dict[str, Any]]:
        event_record_id = self._workspace_event_record_id(event.event_id)
        message_record_id = self._workspace_message_record_id(event.event_id)
        message = {
            "id": event.event_id,
            "workspace_id": event.workspace_id,
            "conversation_id": event.conversation_id,
            "direction": direction,
            "author_member_id": event.author_member_id,
            "author_display_name": author_display_name,
            "text": event.text,
            "sequence": event.sequence,
            "event_digest": event.digest,
            "created_at": float(event.created_at),
        }
        event_record = {
            "id": event.event_id,
            "workspace_id": event.workspace_id,
            "conversation_id": event.conversation_id,
            "author_member_id": event.author_member_id,
            "author_device_id": event.author_device_id,
            "sequence": event.sequence,
            "previous_event_digest": event.previous_event_digest,
            "manifest_digest": event.manifest_digest,
            "channel_digest": event.channel_digest,
            "audience_member_ids": list(event.audience_member_ids),
            "digest": event.digest,
            "serialized": event.serialized,
            "created_at": float(event.created_at),
        }
        index_id = self._workspace_index_record_id(
            event.workspace_id, event.conversation_id
        )
        index = self.store.get("workspace_conversation_index", index_id) or {
            "workspace_id": event.workspace_id,
            "conversation_id": event.conversation_id,
            "head_page": None,
            "count": 0,
            "high_water": 0,
            "authorization_generation": int(
                workspace.get("authorization_generation", 1)
            ),
            "retention_generation": int(workspace.get("retention_generation", 1)),
        }
        page_id = index.get("head_page")
        page = (
            self.store.get("workspace_conversation_index", page_id)
            if isinstance(page_id, str)
            else None
        )
        entry = {
            "event_id": event.event_id,
            "event_record_id": event_record_id,
            "message_record_id": message_record_id,
            "created_at": float(event.created_at),
        }
        encoded_size = len(json.dumps(entry, separators=(",", ":")).encode("utf-8"))
        if (
            page is None
            or len(page.get("entries", [])) >= MESSAGE_PAGE_ENTRIES
            or int(page.get("encoded_bytes", 0)) + encoded_size > MESSAGE_PAGE_MAX_BYTES
        ):
            new_page_id = self._workspace_page_record_id(
                event.workspace_id, event.conversation_id, event.event_id
            )
            page = {
                "workspace_id": event.workspace_id,
                "conversation_id": event.conversation_id,
                "previous_page": page_id,
                "entries": [],
                "encoded_bytes": 0,
            }
            page_id = new_page_id
            index["head_page"] = page_id
        page["entries"] = [*page.get("entries", []), entry]
        page["encoded_bytes"] = int(page.get("encoded_bytes", 0)) + encoded_size
        index["count"] = int(index.get("count", 0)) + 1
        index["high_water"] = int(index.get("high_water", 0)) + 1
        stream_head_id = self._workspace_stream_head_id(
            event.workspace_id, event.conversation_id, event.author_device_id
        )
        event_channel = self._workspace_channel_by_digest(event.channel_digest)
        stream_head = {
            "workspace_id": event.workspace_id,
            "conversation_id": event.conversation_id,
            "device_id": event.author_device_id,
            "high_water": event.sequence,
            "head_digest": event.digest,
            "channel_version": (
                event_channel.version if event_channel is not None else 0
            ),
            "retained_floor": 1,
            "gaps": [],
        }
        sequence_id = self._workspace_stream_sequence_id(
            event.workspace_id,
            event.conversation_id,
            event.author_device_id,
            event.sequence,
        )
        sequence = {
            "workspace_id": event.workspace_id,
            "conversation_id": event.conversation_id,
            "device_id": event.author_device_id,
            "sequence": event.sequence,
            "event_digest": event.digest,
            "event_id": event.event_id,
        }
        return (
            [
                ("workspace_event", event_record_id, event_record),
                ("workspace_message_state", message_record_id, message),
                ("workspace_conversation_index", index_id, index),
                ("workspace_conversation_index", page_id, page),
                ("workspace_stream_coverage", stream_head_id, stream_head),
                ("workspace_stream_coverage", sequence_id, sequence),
            ],
            message,
        )

    def send_workspace_message(
        self,
        workspace_id: Any,
        channel_id: Any,
        text: Any,
        event_id: Any,
        operation_id: Any,
    ) -> dict[str, Any]:
        payload = {
            "workspace_id": workspace_id,
            "channel_id": channel_id,
            "text": text,
            "event_id": event_id,
        }
        operation_id, digest, replay = self._workspace_operation(
            "send_workspace_message", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if workspace.get("state") != "active":
            raise ContactNotApproved("Workspace is not active")
        channel_record = self._require_workspace_channel(workspace_id, channel_id)
        if channel_record.get("state") != "active":
            raise ContactNotApproved("Workspace channel is not active")
        if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > MAX_MESSAGE_TEXT_BYTES:
            raise ValidationError("Workspace message is empty or too large")
        if not isinstance(event_id, str):
            raise ValidationError("Workspace event ID is invalid")
        try:
            if str(uuid.UUID(event_id)) != event_id:
                raise ValueError
        except (ValueError, AttributeError) as exc:
            raise ValidationError("Workspace event ID is invalid") from exc
        existing_event = self.store.get(
            "workspace_event", self._workspace_event_record_id(event_id)
        )
        if existing_event is not None:
            raise ValidationError("Workspace event ID was already used")
        identity = self._identity
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        manifest = self._workspace_current_manifest(workspace)
        local_member = find_member(manifest, workspace["local_member_id"])
        if local_member is None or local_member.status != "active":
            raise ContactNotApproved("Local member is not active")
        if not self._posting_allowed(manifest, local_member):
            raise ContactNotApproved("Workspace posting is restricted to the owner")
        channel = self._workspace_channel_by_digest(channel_record["head_hash"])
        if channel is None:
            raise ValidationError("Workspace channel control is unavailable")
        if (
            channel.visibility == "private"
            and workspace["local_member_id"] not in channel.member_ids
        ):
            raise ContactNotApproved("Local member is not in this private channel")
        stream_head_id = self._workspace_stream_head_id(
            workspace_id, channel_id, workspace["local_device_id"]
        )
        stream_head = self.store.get("workspace_stream_coverage", stream_head_id)
        sequence = int(stream_head.get("high_water", 0)) + 1 if stream_head else 1
        previous = stream_head.get("head_digest") if stream_head else None
        raw = create_workspace_event(
            identity,
            workspace_id=workspace_id,
            conversation_id=channel_id,
            event_id=event_id,
            author_member_id=workspace["local_member_id"],
            author_device_id=workspace["local_device_id"],
            sequence=sequence,
            previous_event_digest=previous,
            manifest_digest=manifest.digest,
            channel_digest=channel.digest,
            text=text,
            audience_member_ids=(
                channel.member_ids if channel.visibility == "private" else None
            ),
        )
        event = verify_workspace_event(raw, manifest=manifest, channel=channel)
        records, message = self._append_workspace_event_records(
            workspace,
            event,
            direction="outbound",
            author_display_name=local_member.display_name,
        )
        deliveries: list[dict[str, Any]] = []
        for member in active_members(manifest):
            if member.member_id == workspace["local_member_id"]:
                continue
            if (
                channel.visibility == "private"
                and member.member_id not in channel.member_ids
            ):
                continue
            for device in member.devices:
                deliveries.append(
                    self._workspace_delivery_record(
                        workspace_id=workspace_id,
                        recipient_member_id=member.member_id,
                        recipient_device=device,
                        kind="workspace_event",
                        document=event.serialized,
                        event_id=event.event_id,
                        conversation_id=event.conversation_id,
                    )
                )
        records.extend(
            ("workspace_delivery", item["id"], item) for item in deliveries
        )
        records.extend(self._due_records(add=deliveries))
        message["delivery_devices"] = {
            item["recipient_device_id"]: {
                "member_id": item["recipient_member_id"],
                "member_display_name": item["recipient_display_name"],
                "state": item["state"],
            }
            for item in deliveries
        }
        message["delivery_summary"] = self._workspace_delivery_summary_from_devices(
            message["delivery_devices"]
        )
        records = [
            (
                kind,
                record_id,
                message if kind == "workspace_message_state" else value,
            )
            for kind, record_id, value in records
        ]
        outcome = self._public_workspace_message(message)
        committed = self.store.commit_operation(
            operation_id, digest, outcome, records
        )
        self._workspace_changed(
            workspace_id, conversation_id=channel_id, resource_kind="message"
        )
        return committed

    def _store_pending_workspace_event(
        self, wire: WorkspaceWirePayload, reason: str
    ) -> None:
        pending_id = self.store.opaque_id(
            "workspace-pending-event", wire.workspace_id, wire.logical_id
        )
        if self.store.get("workspace_pending_event", pending_id) is not None:
            return
        try:
            raw = json.loads(wire.document)
            author_device_id = raw.get("author_device_id")
            if not isinstance(author_device_id, str):
                return
            author_device_id = str(uuid.UUID(author_device_id))
        except (json.JSONDecodeError, ValueError, AttributeError):
            return
        all_pending = self.store.list("workspace_pending_event")
        pending = [
            item
            for item in all_pending
            if item.get("workspace_id") == wire.workspace_id
        ]
        encoded_bytes = len(wire.document.encode("utf-8"))
        pending_profile_bytes = sum(
            int(item.get("encoded_bytes", len(str(item.get("document", "")).encode("utf-8"))))
            for item in all_pending
        )
        sender_count = sum(
            item.get("author_device_id") == author_device_id for item in pending
        )
        if (
            len(pending) >= MAX_PENDING_EVENTS
            or sender_count >= MAX_PENDING_EVENTS_PER_SENDER
            or pending_profile_bytes + encoded_bytes > MAX_PENDING_EVENT_BYTES
        ):
            self._set_workspace_sync_issue(
                wire.workspace_id, "queue_pressure", incomplete=True
            )
            return
        self.store.put(
            "workspace_pending_event",
            pending_id,
            {
                "id": pending_id,
                "workspace_id": wire.workspace_id,
                "logical_id": wire.logical_id,
                "document": wire.document,
                "expires_at": wire.expires_at,
                "reason": reason,
                "author_device_id": author_device_id,
                "encoded_bytes": encoded_bytes,
                "created_at": time.time(),
            },
        )
        self._set_workspace_sync_issue(wire.workspace_id, reason)

    def _accept_workspace_event(self, wire: WorkspaceWirePayload) -> bool:
        try:
            raw_value = json.loads(wire.document)
            if not isinstance(raw_value, dict):
                return False
            manifest_digest = raw_value.get("manifest_digest")
            channel_digest = raw_value.get("channel_digest")
            if not isinstance(manifest_digest, str) or not isinstance(channel_digest, str):
                return False
            workspace = self._require_workspace(wire.workspace_id)
            untrusted_audience = raw_value.get("audience_member_ids")
            if (
                untrusted_audience is not None
                and (
                    not isinstance(untrusted_audience, list)
                    or workspace.get("local_member_id") not in untrusted_audience
                )
            ):
                return False
            manifest = self._workspace_manifest_by_digest(manifest_digest)
            channel = self._workspace_channel_by_digest(channel_digest)
            if manifest is None or channel is None:
                self._store_pending_workspace_event(wire, "missing_controls")
                return False
            event = verify_workspace_event(
                wire.document, manifest=manifest, channel=channel
            )
            if event.workspace_id != wire.workspace_id:
                return False
            if workspace.get("state") not in {"active", "incomplete_sync"}:
                return False
            if event.audience_member_ids:
                channel_record = self.store.get(
                    "workspace_channel",
                    self._workspace_channel_record_id(event.conversation_id),
                )
                current_channel = (
                    self._workspace_channel_by_digest(channel_record["head_hash"])
                    if channel_record is not None
                    and isinstance(channel_record.get("head_hash"), str)
                    else None
                )
                if (
                    workspace.get("local_member_id") not in event.audience_member_ids
                    or channel_record is None
                    or channel_record.get("visibility") != "private"
                    or channel_record.get("state") != "active"
                    or current_channel is None
                    or not self._private_event_is_currently_entitled(
                        current_channel,
                        channel,
                        local_member_id=str(workspace.get("local_member_id")),
                        author_member_id=event.author_member_id,
                    )
                ):
                    return False
            existing_event = self.store.get(
                "workspace_event", self._workspace_event_record_id(event.event_id)
            )
            if existing_event is not None:
                if existing_event.get("digest") == event.digest:
                    return True
                workspace["state"] = "forked"
                workspace["security_error"] = "event_id_equivocation"
                self.store.put(
                    "workspace", self._workspace_record_id(workspace["id"]), workspace
                )
                self._workspace_changed(event.workspace_id, resource_kind="security")
                return False
            current = self._workspace_current_manifest(workspace)
            current_device = find_device(current, event.author_device_id)
            if current_device is None or current_device[0].status != "active":
                return False
            author = find_member(manifest, event.author_member_id)
            if (
                author is None
                or author.status != "active"
                or not self._posting_allowed(manifest, author)
            ):
                return False
            sequence_id = self._workspace_stream_sequence_id(
                event.workspace_id,
                event.conversation_id,
                event.author_device_id,
                event.sequence,
            )
            existing = self.store.get("workspace_stream_coverage", sequence_id)
            if existing is not None:
                if existing.get("event_digest") == event.digest:
                    return True
                workspace["state"] = "forked"
                workspace["security_error"] = "event_sequence_equivocation"
                self.store.put(
                    "workspace", self._workspace_record_id(workspace["id"]), workspace
                )
                self._workspace_changed(event.workspace_id, resource_kind="security")
                return False
            stream_head = self.store.get(
                "workspace_stream_coverage",
                self._workspace_stream_head_id(
                    event.workspace_id,
                    event.conversation_id,
                    event.author_device_id,
                ),
            )
            expected_sequence = int(stream_head.get("high_water", 0)) + 1 if stream_head else 1
            expected_previous = stream_head.get("head_digest") if stream_head else None
            if event.sequence != expected_sequence or event.previous_event_digest != expected_previous:
                admission_version = self._private_channel_admission_version(
                    channel, str(workspace.get("local_member_id"))
                )
                stream_channel_version = (
                    int(stream_head.get("channel_version", 0)) if stream_head else 0
                )
                if (
                    admission_version is None
                    or admission_version <= 1
                    or stream_channel_version >= admission_version
                ):
                    self._store_pending_workspace_event(wire, "missing_predecessor")
                    return False
            records, _message = self._append_workspace_event_records(
                workspace,
                event,
                direction="inbound",
                author_display_name=author.display_name,
            )
            channel_record = self._require_workspace_channel(
                event.workspace_id, event.conversation_id
            )
            subscription = self.store.get(
                "workspace_subscription",
                self.store.opaque_id(
                    "workspace-subscription",
                    event.workspace_id,
                    event.conversation_id,
                ),
            )
            if subscription is not None and subscription.get("subscribed"):
                channel_record["unread_count"] = int(
                    channel_record.get("unread_count", 0)
                ) + 1
            channel_record["updated_at"] = time.time()
            records.append(
                (
                    "workspace_channel",
                    self._workspace_channel_record_id(event.conversation_id),
                    channel_record,
                )
            )
            self.store.put_many(records)
            self._workspace_changed(
                event.workspace_id,
                conversation_id=event.conversation_id,
                resource_kind="message",
            )
            return True
        except (MeshChatError, json.JSONDecodeError):
            return False

    def _store_pending_workspace_control(
        self, wire: WorkspaceWirePayload, reason: str
    ) -> None:
        digest = hashlib.sha256(wire.document.encode("utf-8")).hexdigest()
        record_id = self.store.opaque_id(
            "workspace-pending-control", wire.workspace_id, wire.kind, digest
        )
        if self.store.get("workspace_pending_control", record_id) is not None:
            return
        pending = [
            item
            for item in self.store.list("workspace_pending_control")
            if item.get("workspace_id") == wire.workspace_id
        ]
        future_manifests = sum(
            item.get("kind") == "workspace_manifest_root" for item in pending
        )
        if len(pending) >= MAX_PENDING_CONTROLS or (
            wire.kind == "workspace_manifest_root"
            and future_manifests >= MAX_FUTURE_MANIFESTS
        ):
            self._set_workspace_sync_issue(
                wire.workspace_id, "queue_pressure", incomplete=True
            )
            return
        self.store.put(
            "workspace_pending_control",
            record_id,
            {
                "id": record_id,
                "workspace_id": wire.workspace_id,
                "kind": wire.kind,
                "logical_id": wire.logical_id,
                "expires_at": wire.expires_at,
                "document": wire.document,
                "reason": reason,
                "created_at": time.time(),
            },
        )
        self._set_workspace_sync_issue(wire.workspace_id, reason)

    def _receive_workspace_manifest(
        self, wire: WorkspaceWirePayload, *, drain_pending: bool = True
    ) -> bool:
        workspace = self.store.get(
            "workspace", self._workspace_record_id(wire.workspace_id)
        )
        if workspace is None or workspace.get("state") in {"closed", "forked"}:
            return False
        try:
            incoming = verify_workspace_manifest(wire.document)
            if incoming.workspace_id != wire.workspace_id:
                return False
            existing_same_epoch = self.store.get(
                "workspace_manifest_epoch",
                self._workspace_manifest_epoch_id(wire.workspace_id, incoming.epoch),
            )
            if existing_same_epoch is not None:
                predecessor = (
                    self._workspace_genesis(workspace)
                    if incoming.epoch == 1
                    else self._workspace_manifest_at_epoch(
                        wire.workspace_id, incoming.epoch - 1
                    )
                )
                if predecessor is None:
                    return False
                # A manifest is conflicting only after its signer and hash link
                # validate against the already pinned predecessor. A merely
                # self-consistent outsider manifest must not be able to force a
                # workspace-wide denial of service.
                checked_same_epoch = verify_workspace_manifest_transition(
                    wire.document, predecessor
                )
                if existing_same_epoch.get("digest") != incoming.digest:
                    workspace["state"] = "forked"
                    workspace["security_error"] = "manifest_fork"
                    self.store.put(
                        "workspace", self._workspace_record_id(wire.workspace_id), workspace
                    )
                    self._workspace_changed(wire.workspace_id, resource_kind="security")
                    return False
                return checked_same_epoch.digest == incoming.digest
            current = self._workspace_current_manifest(workspace)
            if incoming.epoch > current.epoch + 1:
                self._store_pending_workspace_control(wire, "missing_manifest_predecessor")
                return False
            if incoming.epoch <= current.epoch:
                return False
            checked = verify_workspace_manifest_transition(wire.document, current)
            self._apply_manifest_to_workspace(workspace, checked)
            self._apply_manifest_public_identities(workspace, checked)
            resolved_name_requests: list[
                tuple[str, str, dict[str, Any]]
            ] = []
            for request_id, request in self.store.items(
                "workspace_display_name_request"
            ):
                if (
                    request.get("workspace_id") != workspace["id"]
                    or request.get("state") != "pending"
                ):
                    continue
                member = find_member(checked, request.get("member_id"))
                if member is not None and member.display_name == request.get(
                    "display_name"
                ):
                    request["state"] = "approved"
                    request["updated_at"] = time.time()
                    resolved_name_requests.append(
                        (
                            "workspace_display_name_request",
                            request_id,
                            request,
                        )
                    )
            self.store.put_many(
                [
                    ("workspace", self._workspace_record_id(workspace["id"]), workspace),
                    (
                        "workspace_manifest",
                        self._workspace_manifest_record_id(checked.digest),
                        self._manifest_record(checked),
                    ),
                    self._manifest_epoch_record(checked),
                    *resolved_name_requests,
                ]
            )
            self._remember_workspace_devices(workspace)
            if drain_pending:
                self._drain_workspace_pending_controls(workspace["id"])
            self._drain_workspace_pending_events(workspace["id"])
            self._workspace_changed(workspace["id"])
            return True
        except MeshChatError:
            return False

    def _receive_workspace_channel(self, wire: WorkspaceWirePayload) -> bool:
        try:
            raw = json.loads(wire.document)
            if not isinstance(raw, dict) or not isinstance(raw.get("manifest_digest"), str):
                return False
            manifest = self._workspace_manifest_by_digest(raw["manifest_digest"])
            if manifest is None:
                self._store_pending_workspace_control(wire, "missing_manifest")
                return False
            channel = verify_workspace_channel_record(wire.document, manifest=manifest)
            if channel.workspace_id != wire.workspace_id:
                return False
            workspace = self._require_workspace(wire.workspace_id)
            if workspace.get("state") in {"closed", "forked", "removed", "left"}:
                return False
            existing_channel = self.store.get(
                "workspace_channel", self._workspace_channel_record_id(channel.channel_id)
            )
            current_manifest = self._workspace_current_manifest(workspace)
            is_general = channel.name == "general"
            if existing_channel is None:
                if (
                    channel.version != 1
                    or channel.previous_hash is not None
                    or channel.visibility != "public"
                    or channel.archived
                ):
                    self._store_pending_workspace_control(
                        wire, "missing_channel_predecessor"
                    )
                    return False
                if is_general:
                    genesis = self._workspace_genesis(workspace)
                    initial_manifest = self._workspace_manifest_at_epoch(
                        wire.workspace_id, 1
                    )
                    if (
                        initial_manifest is None
                        or channel.manifest_digest != initial_manifest.digest
                        or channel.manager_member_id != genesis.owner_member_id
                        or channel.manager_device_id != genesis.authority_device_id
                    ):
                        return False
                    if workspace.get("general_channel_id") not in {
                        None,
                        channel.channel_id,
                    }:
                        workspace["state"] = "forked"
                        workspace["security_error"] = "general_channel_conflict"
                        self.store.put(
                            "workspace",
                            self._workspace_record_id(workspace["id"]),
                            workspace,
                        )
                        self._workspace_changed(
                            workspace["id"], resource_kind="security"
                        )
                        return False
                    workspace["general_channel_id"] = channel.channel_id
                else:
                    if channel_name_key(channel.name) == "general":
                        return False
                    creator = find_member(manifest, channel.manager_member_id)
                    current_creator = find_member(
                        current_manifest, channel.manager_member_id
                    )
                    if (
                        creator is None
                        or not self._channel_creation_allowed(manifest, creator)
                        or current_creator is None
                        or current_creator.status != "active"
                    ):
                        return False
                    known_channels = [
                        item
                        for item in self.store.list("workspace_channel")
                        if item.get("workspace_id") == workspace["id"]
                    ]
                    known_public_channels = [
                        item
                        for item in known_channels
                        if item.get("visibility") == "public"
                    ]
                    if sum(
                        item.get("state") == "active" for item in known_channels
                    ) >= MAX_PUBLIC_CHANNELS:
                        self._set_workspace_sync_issue(
                            workspace["id"], "channel_directory_full", incomplete=True
                        )
                        return False
                    if len(known_public_channels) >= MAX_RETAINED_PUBLIC_CHANNELS:
                        self._set_workspace_sync_issue(
                            workspace["id"], "channel_directory_full", incomplete=True
                        )
                        return False
                channel_record = self._channel_record(channel)
                index_id = self._workspace_index_record_id(
                    workspace["id"], channel.channel_id
                )
                index = {
                    "workspace_id": workspace["id"],
                    "conversation_id": channel.channel_id,
                    "head_page": None,
                    "count": 0,
                    "high_water": 0,
                    "authorization_generation": int(
                        workspace.get("authorization_generation", 1)
                    ),
                    "retention_generation": int(
                        workspace.get("retention_generation", 1)
                    ),
                }
                subscribed = is_general
                workspace["channel_discovery"] = "incomplete"
                workspace["updated_at"] = time.time()
                self.store.put_many(
                    [
                        (
                            "workspace",
                            self._workspace_record_id(workspace["id"]),
                            workspace,
                        ),
                        (
                            "workspace_channel",
                            self._workspace_channel_record_id(channel.channel_id),
                            channel_record,
                        ),
                        (
                            "workspace_channel_control",
                            self._workspace_channel_control_id(channel.digest),
                            self._workspace_channel_control_record(
                                channel, document_type="workspace_channel_record"
                            ),
                        ),
                        self._workspace_channel_version_record(channel),
                        ("workspace_conversation_index", index_id, index),
                        (
                            "workspace_subscription",
                            self.store.opaque_id(
                                "workspace-subscription",
                                workspace["id"],
                                channel.channel_id,
                            ),
                            {
                                "workspace_id": workspace["id"],
                                "conversation_id": channel.channel_id,
                                "subscribed": subscribed,
                            },
                        ),
                        (
                            "workspace_read_state",
                            self.store.opaque_id(
                                "workspace-read-state",
                                workspace["id"],
                                channel.channel_id,
                            ),
                            {
                                "workspace_id": workspace["id"],
                                "conversation_id": channel.channel_id,
                                "high_water": 0,
                            },
                        ),
                    ]
                )
            else:
                if existing_channel.get("head_hash") == channel.digest:
                    return True
                if (
                    channel.channel_id == workspace.get("general_channel_id")
                    and (
                        channel.manager_member_id
                        != existing_channel.get("manager_member_id")
                        or channel.manager_device_id
                        != existing_channel.get("manager_device_id")
                    )
                ):
                    return False
                current_version = int(existing_channel.get("version", 0))
                if channel.version > current_version + 1:
                    self._store_pending_workspace_control(
                        wire, "missing_channel_predecessor"
                    )
                    return False
                if channel.version <= current_version:
                    known_control = self.store.get(
                        "workspace_channel_control",
                        self._workspace_channel_control_id(channel.digest),
                    )
                    if (
                        known_control is not None
                        and known_control.get("serialized") == channel.serialized
                    ):
                        return True
                    version_record = self.store.get(
                        "workspace_channel_version",
                        self._workspace_channel_version_id(
                            workspace["id"], channel.channel_id, channel.version
                        ),
                    )
                    if version_record is not None and version_record.get(
                        "digest"
                    ) == channel.digest:
                        return True
                    if channel.version == 1:
                        if channel.channel_id == workspace.get(
                            "general_channel_id"
                        ):
                            initial_manifest = self._workspace_manifest_at_epoch(
                                workspace["id"], 1
                            )
                            if (
                                channel.previous_hash is not None
                                or initial_manifest is None
                                or channel.manifest_digest
                                != initial_manifest.digest
                            ):
                                return False
                        else:
                            creator = find_member(
                                manifest, channel.manager_member_id
                            )
                            current_creator = find_member(
                                current_manifest, channel.manager_member_id
                            )
                            if (
                                channel.previous_hash is not None
                                or channel_name_key(channel.name) == "general"
                                or creator is None
                                or not self._channel_creation_allowed(
                                    manifest, creator
                                )
                                or current_creator is None
                                or current_creator.status != "active"
                            ):
                                return False
                    else:
                        previous = self._workspace_channel_by_digest(
                            channel.previous_hash or ""
                        )
                        if previous is None:
                            return False
                        verify_workspace_channel_record_transition(
                            wire.document, previous, manifest=manifest
                        )
                    existing_channel["state"] = "forked"
                    existing_channel["security_error"] = "channel_control_conflict"
                    self.store.put(
                        "workspace_channel",
                        self._workspace_channel_record_id(channel.channel_id),
                        existing_channel,
                    )
                    self._workspace_changed(
                        workspace["id"],
                        conversation_id=channel.channel_id,
                        resource_kind="security",
                    )
                    return False
                previous = self._workspace_channel_by_digest(
                    existing_channel["head_hash"]
                )
                if previous is None or channel.manifest_digest != current_manifest.digest:
                    return False
                channel = verify_workspace_channel_record_transition(
                    wire.document, previous, manifest=manifest
                )
                updated = self._channel_record(channel)
                updated["unread_count"] = int(
                    existing_channel.get("unread_count", 0)
                )
                updated["created_at"] = float(
                    existing_channel.get("created_at", channel.created_at)
                )
                updated["updated_at"] = time.time()
                workspace["channel_discovery"] = "incomplete"
                workspace["updated_at"] = time.time()
                self.store.put_many(
                    [
                        (
                            "workspace",
                            self._workspace_record_id(workspace["id"]),
                            workspace,
                        ),
                        (
                            "workspace_channel",
                            self._workspace_channel_record_id(channel.channel_id),
                            updated,
                        ),
                        (
                            "workspace_channel_control",
                            self._workspace_channel_control_id(channel.digest),
                            self._workspace_channel_control_record(
                                channel, document_type="workspace_channel_record"
                            ),
                        ),
                        self._workspace_channel_version_record(channel),
                    ]
                )
            self._drain_workspace_pending_events(workspace["id"])
            self._workspace_changed(
                workspace["id"],
                conversation_id=channel.channel_id,
                resource_kind="channel",
            )
            return True
        except (MeshChatError, json.JSONDecodeError):
            return False

    def _receive_workspace_channel_leave_request(
        self, wire: WorkspaceWirePayload
    ) -> bool:
        try:
            value = json.loads(wire.document)
            if not isinstance(value, dict):
                return False
            channel_id = value.get("channel_id")
            channel_head = value.get("channel_head")
            manifest_digest = value.get("manifest_digest")
            if not all(
                isinstance(item, str)
                for item in (channel_id, channel_head, manifest_digest)
            ):
                return False
            workspace = self._require_workspace(wire.workspace_id)
            stored = self._require_workspace_channel(wire.workspace_id, channel_id)
            if stored.get("state") != "active" or stored.get("head_hash") != channel_head:
                return False
            channel = self._workspace_channel_by_digest(channel_head)
            manifest = self._workspace_manifest_by_digest(manifest_digest)
            identity = self._identity
            if (
                channel is None
                or manifest is None
                or identity is None
                or channel.visibility != "private"
                or channel.manager_member_id != workspace.get("local_member_id")
                or channel.manager_device_id != workspace.get("local_device_id")
                or manifest.digest != workspace.get("manifest_hash")
            ):
                return False
            request = verify_workspace_channel_leave_request(
                wire.document, channel=channel, manifest=manifest
            )
            request_id = self.store.opaque_id(
                "workspace-channel-leave-request", request.digest
            )
            if self.store.get("workspace_channel_leave_request", request_id) is not None:
                return True
            remaining = [
                member_id
                for member_id in channel.member_ids
                if member_id != request.member_id
            ]
            raw = create_workspace_channel_manifest(
                identity,
                workspace_id=wire.workspace_id,
                channel_id=channel.channel_id,
                manifest_digest=manifest.digest,
                name=channel.name,
                topic=channel.topic,
                manager_member_id=channel.manager_member_id,
                manager_device_id=channel.manager_device_id,
                member_ids=remaining,
                version=channel.version + 1,
                previous_hash=channel.digest,
            )
            next_channel = verify_workspace_channel_manifest_transition(
                raw, channel, manifest=manifest
            )
            updated = self._channel_record(next_channel)
            updated["unread_count"] = int(stored.get("unread_count", 0))
            updated["created_at"] = float(stored.get("created_at", channel.created_at))
            updated["updated_at"] = time.time()
            new_control = self._workspace_channel_control_record(
                next_channel, document_type="workspace_channel_manifest"
            )
            recipients = self._workspace_channel_recipients(
                manifest,
                next_channel,
                excluding_member_id=workspace["local_member_id"],
            )
            deliveries = [
                self._workspace_delivery_record(
                    workspace_id=wire.workspace_id,
                    recipient_member_id=member_id,
                    recipient_device=device,
                    kind=control.get(
                        "document_type", "workspace_channel_manifest"
                    ),
                    document=control["serialized"],
                    conversation_id=channel.channel_id,
                    priority=0,
                )
                for member_id, device in recipients
                for control in [new_control]
            ]
            cancellation_records, outbound_ids = (
                self._cancel_private_channel_member_deliveries(
                    wire.workspace_id, channel.channel_id, {request.member_id}
                )
            )
            self.store.put_many(
                [
                    (
                        "workspace_channel",
                        self._workspace_channel_record_id(channel.channel_id),
                        updated,
                    ),
                    (
                        "workspace_channel_control",
                        self._workspace_channel_control_id(next_channel.digest),
                        new_control,
                    ),
                    self._workspace_channel_version_record(next_channel),
                    (
                        "workspace_channel_leave_request",
                        request_id,
                        {
                            "id": request_id,
                            "workspace_id": wire.workspace_id,
                            "channel_id": channel.channel_id,
                            "member_id": request.member_id,
                            "digest": request.digest,
                            "state": "applied",
                            "created_at": float(request.created_at),
                        },
                    ),
                    *cancellation_records,
                    *[("workspace_delivery", item["id"], item) for item in deliveries],
                    *self._due_records(add=deliveries),
                ]
            )
            network = getattr(self, "network", None)
            if network is not None and outbound_ids:
                network.cancel_outbound(outbound_ids)
            self._workspace_changed(
                wire.workspace_id,
                conversation_id=channel.channel_id,
                resource_kind="channel",
            )
            return True
        except (MeshChatError, json.JSONDecodeError, KeyError, TypeError):
            return False

    def _receive_workspace_private_channel(
        self, wire: WorkspaceWirePayload, *, drain_pending: bool = True
    ) -> bool:
        """Validate and store a member-scoped private-channel control.

        The untrusted roster is checked for the local member before any pending
        record is written. This keeps even a delayed or malicious private
        channel identifier out of a nonmember's encrypted profile and
        diagnostics.
        """
        try:
            value = json.loads(wire.document)
            if not isinstance(value, dict):
                return False
            raw_members = value.get("member_ids")
            if not isinstance(raw_members, list):
                return False
            workspace = self._require_workspace(wire.workspace_id)
            local_member_id = workspace.get("local_member_id")
            channel_id = value.get("channel_id")
            if not isinstance(channel_id, str):
                return False
            if local_member_id not in raw_members:
                return False
            manifest_digest = value.get("manifest_digest")
            if not isinstance(manifest_digest, str):
                return False
            manifest = self._workspace_manifest_by_digest(manifest_digest)
            if manifest is None:
                self._store_pending_workspace_control(wire, "missing_manifest")
                return False
            incoming = verify_workspace_channel_manifest(
                wire.document, manifest=manifest
            )
            if incoming.workspace_id != wire.workspace_id:
                return False
            if workspace.get("state") in {"closed", "forked", "removed", "left"}:
                return False
            current_manifest = self._workspace_current_manifest(workspace)
            local_current = find_member(current_manifest, local_member_id)
            if local_current is None or local_current.status != "active":
                return False
            record_id = self._workspace_channel_record_id(incoming.channel_id)
            existing = self.store.get("workspace_channel", record_id)
            if existing is None:
                creator = find_member(manifest, incoming.manager_member_id)
                current_creator = find_member(
                    current_manifest, incoming.manager_member_id
                )
                current_creator_device = find_device(
                    current_manifest, incoming.manager_device_id
                )
                known_channels = [
                    item
                    for item in self.store.list("workspace_channel")
                    if item.get("workspace_id") == wire.workspace_id
                ]
                admission_checkpoint = incoming.version > 1
                if (
                    (
                        incoming.version == 1
                        and incoming.previous_hash is not None
                    )
                    or (
                        incoming.version > 1
                        and incoming.previous_hash is None
                    )
                    or incoming.archived
                    or channel_name_key(incoming.name) == "general"
                    or creator is None
                    or not self._channel_creation_allowed(manifest, creator)
                    or current_creator is None
                    or current_creator.status != "active"
                    or current_creator_device is None
                    or current_creator_device[0].member_id
                    != incoming.manager_member_id
                    or sum(item.get("state") == "active" for item in known_channels)
                    >= MAX_PUBLIC_CHANNELS
                ):
                    return False
                channel_record = self._channel_record(incoming)
                index_id = self._workspace_index_record_id(
                    wire.workspace_id, incoming.channel_id
                )
                index = {
                    "workspace_id": wire.workspace_id,
                    "conversation_id": incoming.channel_id,
                    "head_page": None,
                    "count": 0,
                    "high_water": 0,
                    "authorization_generation": int(
                        workspace.get("authorization_generation", 1)
                    ),
                    "retention_generation": int(
                        workspace.get("retention_generation", 1)
                    ),
                }
                self.store.put_many(
                    [
                        ("workspace_channel", record_id, channel_record),
                        (
                            "workspace_channel_control",
                            self._workspace_channel_control_id(incoming.digest),
                            self._workspace_channel_control_record(
                                incoming,
                                document_type="workspace_channel_manifest",
                                admission_checkpoint=admission_checkpoint,
                            ),
                        ),
                        self._workspace_channel_version_record(incoming),
                        ("workspace_conversation_index", index_id, index),
                        (
                            "workspace_subscription",
                            self.store.opaque_id(
                                "workspace-subscription",
                                wire.workspace_id,
                                incoming.channel_id,
                            ),
                            {
                                "workspace_id": wire.workspace_id,
                                "conversation_id": incoming.channel_id,
                                "subscribed": True,
                            },
                        ),
                        (
                            "workspace_read_state",
                            self.store.opaque_id(
                                "workspace-read-state",
                                wire.workspace_id,
                                incoming.channel_id,
                            ),
                            {
                                "workspace_id": wire.workspace_id,
                                "conversation_id": incoming.channel_id,
                                "high_water": 0,
                            },
                        ),
                    ]
                )
            else:
                if existing.get("visibility") != "private":
                    return False
                if existing.get("head_hash") == incoming.digest:
                    return True
                current_version = int(existing.get("version", 0))
                admission_checkpoint = incoming.version > current_version + 1
                if incoming.version <= current_version:
                    known = self.store.get(
                        "workspace_channel_control",
                        self._workspace_channel_control_id(incoming.digest),
                    )
                    if known is not None and known.get("serialized") == incoming.serialized:
                        return True
                    version_record = self.store.get(
                        "workspace_channel_version",
                        self._workspace_channel_version_id(
                            wire.workspace_id, incoming.channel_id, incoming.version
                        ),
                    )
                    if version_record is not None and version_record.get("digest") == incoming.digest:
                        return True
                    if incoming.version == current_version:
                        current = self._workspace_channel_by_digest(existing["head_hash"])
                        predecessor = (
                            self._workspace_channel_by_digest(current.previous_hash)
                            if current is not None
                            and isinstance(current.previous_hash, str)
                            else None
                        )
                        if incoming.version == 1:
                            valid_fork = incoming.previous_hash is None
                        else:
                            valid_fork = predecessor is not None
                            if valid_fork:
                                verify_workspace_channel_manifest_transition(
                                    wire.document, predecessor, manifest=manifest
                                )
                        if valid_fork:
                            existing["state"] = "forked"
                            existing["security_error"] = "channel_control_conflict"
                            self.store.put("workspace_channel", record_id, existing)
                            self._workspace_changed(
                                wire.workspace_id,
                                conversation_id=incoming.channel_id,
                                resource_kind="security",
                            )
                    return False
                previous = self._workspace_channel_by_digest(existing["head_hash"])
                if admission_checkpoint:
                    if (
                        previous is None
                        or incoming.manager_member_id
                        != previous.manager_member_id
                        or incoming.manager_device_id
                        != previous.manager_device_id
                        or incoming.created_at < previous.created_at
                    ):
                        return False
                else:
                    if previous is None:
                        self._store_pending_workspace_control(
                            wire, "missing_channel_predecessor"
                        )
                        return False
                    incoming = verify_workspace_channel_manifest_transition(
                        wire.document, previous, manifest=manifest
                    )
                if incoming.manifest_digest != current_manifest.digest:
                    return False
                updated = self._channel_record(incoming)
                updated["unread_count"] = int(existing.get("unread_count", 0))
                updated["created_at"] = float(
                    existing.get("created_at", incoming.created_at)
                )
                updated["updated_at"] = time.time()
                self.store.put_many(
                    [
                        ("workspace_channel", record_id, updated),
                        (
                            "workspace_channel_control",
                            self._workspace_channel_control_id(incoming.digest),
                            self._workspace_channel_control_record(
                                incoming,
                                document_type="workspace_channel_manifest",
                                admission_checkpoint=admission_checkpoint,
                            ),
                        ),
                        self._workspace_channel_version_record(incoming),
                    ]
                )
            if drain_pending:
                self._drain_workspace_pending_controls(wire.workspace_id)
            self._drain_workspace_pending_events(wire.workspace_id)
            self._workspace_changed(
                wire.workspace_id,
                conversation_id=incoming.channel_id,
                resource_kind="channel",
            )
            return True
        except (MeshChatError, json.JSONDecodeError, KeyError, TypeError):
            return False

    def _receive_workspace_channel_transfer_offer(
        self, wire: WorkspaceWirePayload
    ) -> bool:
        try:
            value = json.loads(wire.document)
            if not isinstance(value, dict):
                return False
            channel_id = value.get("channel_id")
            manifest_digest = value.get("manifest_digest")
            channel_head = value.get("channel_head")
            if not all(
                isinstance(item, str)
                for item in (channel_id, manifest_digest, channel_head)
            ):
                return False
            workspace = self._require_workspace(wire.workspace_id)
            existing = self.store.get(
                "workspace_channel", self._workspace_channel_record_id(channel_id)
            )
            if existing is None or existing.get("workspace_id") != wire.workspace_id:
                return False
            manifest = self._workspace_manifest_by_digest(manifest_digest)
            channel = self._workspace_channel_by_digest(channel_head)
            stored = self._require_workspace_channel(wire.workspace_id, channel_id)
            if (
                manifest is None
                or channel is None
                or manifest.digest != workspace.get("manifest_hash")
                or stored.get("head_hash") != channel.digest
                or stored.get("state") != "active"
            ):
                return False
            offer = verify_workspace_channel_transfer_offer(
                wire.document, channel=channel, manifest=manifest
            )
            record_id = self._workspace_channel_transfer_id(offer.digest)
            if self.store.get("workspace_channel_transfer", record_id) is not None:
                return True
            pending = [
                item
                for item in self.store.list("workspace_channel_transfer")
                if item.get("workspace_id") == wire.workspace_id
                and item.get("state") == "offered"
            ]
            if len(pending) >= MAX_PENDING_CHANNEL_TRANSFERS:
                self._set_workspace_sync_issue(
                    wire.workspace_id, "queue_pressure", incomplete=True
                )
                return False
            self.store.put(
                "workspace_channel_transfer",
                record_id,
                {
                    "id": record_id,
                    "workspace_id": wire.workspace_id,
                    "channel_id": offer.channel_id,
                    "channel_head": offer.channel_head,
                    "manifest_digest": offer.manifest_digest,
                    "manager_member_id": offer.manager_member_id,
                    "successor_member_id": offer.successor_member_id,
                    "successor_device_id": offer.successor_device_id,
                    "state": "offered",
                    "document": offer.serialized,
                    "created_at": float(offer.created_at),
                    "expires_at": float(offer.expires_at),
                },
            )
            self._workspace_changed(
                wire.workspace_id, resource_kind="channel_transfer"
            )
            return True
        except (MeshChatError, json.JSONDecodeError):
            return False

    def _receive_workspace_channel_head_transition(
        self, wire: WorkspaceWirePayload
    ) -> bool:
        try:
            value = json.loads(wire.document)
            if not isinstance(value, dict):
                return False
            if wire.kind == "workspace_channel_transfer":
                offer = value.get("offer")
                if not isinstance(offer, dict):
                    return False
                channel_id = offer.get("channel_id")
                manifest_digest = offer.get("manifest_digest")
                previous_hash = offer.get("channel_head")
            else:
                channel_id = value.get("channel_id")
                manifest_digest = value.get("manifest_digest")
                previous_hash = value.get("channel_head")
            if not all(
                isinstance(item, str)
                for item in (channel_id, manifest_digest, previous_hash)
            ):
                return False
            workspace = self._require_workspace(wire.workspace_id)
            existing = self.store.get(
                "workspace_channel", self._workspace_channel_record_id(channel_id)
            )
            if existing is None or existing.get("workspace_id") != wire.workspace_id:
                return False
            manifest = self._workspace_manifest_by_digest(manifest_digest)
            previous = self._workspace_channel_by_digest(previous_hash)
            if manifest is None:
                self._store_pending_workspace_control(wire, "missing_manifest")
                return False
            if previous is None:
                self._store_pending_workspace_control(
                    wire, "missing_channel_predecessor"
                )
                return False
            if manifest.digest != workspace.get("manifest_hash"):
                return False
            incoming = (
                verify_workspace_channel_transfer(
                    wire.document, channel=previous, manifest=manifest
                )
                if wire.kind == "workspace_channel_transfer"
                else verify_workspace_channel_recovery(
                    wire.document, channel=previous, manifest=manifest
                )
            )
            if (
                incoming.visibility == "private"
                and workspace.get("local_member_id") not in incoming.member_ids
            ):
                return False
            if existing.get("state") == "archived":
                return False
            if int(existing.get("version", 0)) >= incoming.version:
                version_record = self.store.get(
                    "workspace_channel_version",
                    self._workspace_channel_version_id(
                        wire.workspace_id, incoming.channel_id, incoming.version
                    ),
                )
                if version_record is not None and version_record.get(
                    "digest"
                ) == incoming.digest:
                    return True
                existing["state"] = "forked"
                existing["security_error"] = "channel_control_conflict"
                self.store.put(
                    "workspace_channel",
                    self._workspace_channel_record_id(incoming.channel_id),
                    existing,
                )
                self._workspace_changed(
                    wire.workspace_id,
                    conversation_id=incoming.channel_id,
                    resource_kind="security",
                )
                return False
            if (
                incoming.version != int(existing.get("version", 0)) + 1
                or existing.get("head_hash") != incoming.previous_hash
            ):
                self._store_pending_workspace_control(
                    wire, "missing_channel_predecessor"
                )
                return False
            updated = self._channel_record(incoming)
            updated["unread_count"] = int(existing.get("unread_count", 0))
            updated["created_at"] = float(
                existing.get("created_at", incoming.created_at)
            )
            updated["updated_at"] = time.time()
            if incoming.visibility == "public":
                workspace["channel_discovery"] = "incomplete"
            workspace["updated_at"] = time.time()
            records: list[tuple[str, str, dict[str, Any]]] = [
                ("workspace", self._workspace_record_id(workspace["id"]), workspace),
                (
                    "workspace_channel",
                    self._workspace_channel_record_id(incoming.channel_id),
                    updated,
                ),
                (
                    "workspace_channel_control",
                    self._workspace_channel_control_id(incoming.digest),
                    self._workspace_channel_control_record(
                        incoming, document_type=wire.kind
                    ),
                ),
                self._workspace_channel_version_record(incoming),
            ]
            if wire.kind == "workspace_channel_transfer":
                offer = verify_workspace_channel_transfer_offer(
                    _canonical_transfer_offer(value["offer"]),
                    channel=previous,
                    manifest=manifest,
                )
                transfer_id = self._workspace_channel_transfer_id(offer.digest)
                transfer = self.store.get("workspace_channel_transfer", transfer_id)
                if transfer is not None:
                    transfer["state"] = "accepted"
                    transfer["accepted_at"] = time.time()
                    records.append(
                        ("workspace_channel_transfer", transfer_id, transfer)
                    )
            self.store.put_many(records)
            self._drain_workspace_pending_events(wire.workspace_id)
            self._workspace_changed(
                wire.workspace_id,
                conversation_id=incoming.channel_id,
                resource_kind="channel",
            )
            return True
        except (MeshChatError, json.JSONDecodeError):
            return False

    def _receive_workspace_channel_summary(
        self, wire: WorkspaceWirePayload
    ) -> bool:
        try:
            workspace = self._require_workspace(wire.workspace_id)
            manifest = self._workspace_current_manifest(workspace)
            summary = verify_workspace_channel_summary(
                wire.document, manifest=manifest
            )
            if summary.device_id == workspace.get("local_device_id"):
                return False
            remote_entries = list(summary.entries)
            local_entries = self._workspace_public_channel_entries(wire.workspace_id)
            discovery_id = self._workspace_channel_discovery_id(
                wire.workspace_id, summary.device_id
            )
            previous_discovery = self.store.get(
                "workspace_channel_discovery", discovery_id
            )
            first_page_for_session = (
                previous_discovery is None
                or previous_discovery.get("session_id") != summary.session_id
            )
            if first_page_for_session:
                pages: dict[str, list[list[Any]]] = {}
            else:
                if (
                    previous_discovery.get("manifest_digest")
                    != summary.manifest_digest
                    or previous_discovery.get("member_id") != summary.member_id
                    or previous_discovery.get("page_count") != summary.page_count
                ):
                    return False
                pages = dict(previous_discovery.get("pages", {}))
            page_key = str(summary.page_index)
            encoded_page = [list(item) for item in remote_entries]
            if page_key in pages and pages[page_key] != encoded_page:
                self._mark_workspace_channel_discovery_incomplete(wire.workspace_id)
                return False
            pages[page_key] = encoded_page
            complete = len(pages) == summary.page_count and all(
                str(index) in pages for index in range(summary.page_count)
            )
            combined_entries = (
                [
                    item
                    for index in range(summary.page_count)
                    for item in pages[str(index)]
                ]
                if complete
                else []
            )
            if complete and (
                combined_entries != sorted(combined_entries)
                or len({item[0] for item in combined_entries})
                != len(combined_entries)
            ):
                self._mark_workspace_channel_discovery_incomplete(wire.workspace_id)
                return False
            self.store.put(
                "workspace_channel_discovery",
                discovery_id,
                {
                    "workspace_id": wire.workspace_id,
                    "device_id": summary.device_id,
                    "member_id": summary.member_id,
                    "manifest_digest": summary.manifest_digest,
                    "session_id": summary.session_id,
                    "page_count": summary.page_count,
                    "pages": pages,
                    "complete": complete,
                    "entries": combined_entries,
                    "updated_at": time.time(),
                },
            )
            local_by_id = {entry[0]: entry for entry in local_entries}
            requests = [
                (
                    channel_id,
                    local_by_id[channel_id][1]
                    if channel_id in local_by_id
                    else 0,
                    local_by_id[channel_id][2]
                    if channel_id in local_by_id
                    else None,
                )
                for channel_id, version, head_hash in remote_entries
                if channel_id not in local_by_id
                or local_by_id[channel_id][1] < version
                or local_by_id[channel_id][2] != head_hash
            ]
            identity = self._identity
            signer = find_device(manifest, summary.device_id)
            deliveries: list[dict[str, Any]] = []
            if requests and identity is not None and signer is not None:
                raw = create_workspace_channel_fetch(
                    identity,
                    manifest=manifest,
                    member_id=workspace["local_member_id"],
                    device_id=workspace["local_device_id"],
                    session_id=summary.session_id,
                    requests=requests,
                )
                deliveries.append(
                    self._workspace_delivery_record(
                        workspace_id=wire.workspace_id,
                        recipient_member_id=summary.member_id,
                        recipient_device=signer[1],
                        kind="workspace_channel_fetch",
                        document=raw,
                        priority=1,
                    )
                )
                self._mark_workspace_channel_discovery_incomplete(
                    wire.workspace_id
                )
            if (
                identity is not None
                and signer is not None
                and first_page_for_session
            ):
                deliveries.extend(
                    self._workspace_channel_summary_deliveries(
                        workspace,
                        manifest,
                        identity,
                        summary.session_id,
                        [(summary.member_id, signer[1])],
                    )
                )
            if deliveries:
                self.store.put_many(
                    [
                        *[
                            ("workspace_delivery", delivery["id"], delivery)
                            for delivery in deliveries
                        ],
                        *self._due_records(add=deliveries),
                    ]
                )
            self._recompute_workspace_channel_discovery(wire.workspace_id)
            return True
        except (MeshChatError, json.JSONDecodeError):
            return False

    def _receive_workspace_channel_fetch(
        self, wire: WorkspaceWirePayload
    ) -> bool:
        try:
            workspace = self._require_workspace(wire.workspace_id)
            manifest = self._workspace_current_manifest(workspace)
            fetch = verify_workspace_channel_fetch(wire.document, manifest=manifest)
            requester = find_device(manifest, fetch.device_id)
            identity = self._identity
            if requester is None or identity is None:
                return False
            controls: list[dict[str, Any]] = []
            for channel_id, _known_version, known_head in fetch.requests:
                channel = self.store.get(
                    "workspace_channel",
                    self._workspace_channel_record_id(channel_id),
                )
                if (
                    channel is None
                    or channel.get("workspace_id") != wire.workspace_id
                    or channel.get("visibility") != "public"
                    or channel.get("state") == "forked"
                ):
                    continue
                try:
                    chain = self._workspace_channel_control_chain(
                        channel,
                        known_head=known_head,
                        limit=fetch.max_controls - len(controls),
                    )
                except ValidationError:
                    chain = self._workspace_channel_control_chain(
                        channel, limit=fetch.max_controls - len(controls)
                    )
                controls.extend(chain)
                if len(controls) >= fetch.max_controls:
                    break
            deliveries = [
                self._workspace_delivery_record(
                    workspace_id=wire.workspace_id,
                    recipient_member_id=fetch.member_id,
                    recipient_device=requester[1],
                    kind=control.get(
                        "document_type", "workspace_channel_record"
                    ),
                    document=control["serialized"],
                    priority=0,
                )
                for control in controls
            ]
            deliveries.extend(
                self._workspace_channel_summary_deliveries(
                    workspace,
                    manifest,
                    identity,
                    fetch.session_id,
                    [(fetch.member_id, requester[1])],
                )
            )
            self.store.put_many(
                [
                    *[
                        ("workspace_delivery", delivery["id"], delivery)
                        for delivery in deliveries
                    ],
                    *self._due_records(add=deliveries),
                ]
            )
            return True
        except (MeshChatError, json.JSONDecodeError):
            return False

    def _drain_workspace_pending_controls(self, workspace_id: str) -> None:
        pending_controls = [
            item
            for item in self.store.list("workspace_pending_control")
            if item.get("workspace_id") == workspace_id
        ][:MAX_PENDING_CONTROLS]

        def order(item: dict[str, Any]) -> tuple[int, int, float]:
            if item.get("kind") == "workspace_manifest_root":
                try:
                    epoch = int(json.loads(item["document"]).get("epoch", 0))
                except (TypeError, ValueError, json.JSONDecodeError):
                    epoch = 0
                return (0, epoch, float(item.get("created_at", 0)))
            if item.get("kind") in {
                "workspace_channel_record",
                "workspace_channel_manifest",
            }:
                try:
                    version = int(json.loads(item["document"]).get("version", 0))
                except (TypeError, ValueError, json.JSONDecodeError):
                    version = 0
                return (1, version, float(item.get("created_at", 0)))
            return (2, 0, float(item.get("created_at", 0)))

        pending_controls.sort(key=order)
        while pending_controls:
            made_progress = False
            for pending in list(pending_controls):
                if float(pending.get("expires_at", 0)) <= time.time():
                    self.store.delete("workspace_pending_control", pending["id"])
                    pending_controls.remove(pending)
                    made_progress = True
                    continue
                wire = WorkspaceWirePayload(
                    kind=pending["kind"],
                    logical_id=pending["logical_id"],
                    workspace_id=workspace_id,
                    expires_at=int(pending["expires_at"]),
                    document=pending["document"],
                )
                if wire.kind == "workspace_manifest_root":
                    applied = self._receive_workspace_manifest(
                        wire, drain_pending=False
                    )
                elif wire.kind == "workspace_channel_record":
                    applied = self._receive_workspace_channel(wire)
                elif wire.kind == "workspace_channel_manifest":
                    applied = self._receive_workspace_private_channel(
                        wire, drain_pending=False
                    )
                elif wire.kind in {
                    "workspace_channel_transfer",
                    "workspace_channel_recovery",
                }:
                    applied = self._receive_workspace_channel_head_transition(wire)
                else:
                    applied = False
                if applied:
                    self.store.delete("workspace_pending_control", pending["id"])
                    pending_controls.remove(pending)
                    made_progress = True
            if not made_progress:
                break
        self._clear_workspace_sync_issue_if_resolved(workspace_id)

    def _drain_workspace_pending_events(self, workspace_id: str) -> None:
        for pending in self.store.list("workspace_pending_event")[:MAX_PENDING_EVENTS]:
            if pending.get("workspace_id") != workspace_id:
                continue
            if float(pending.get("expires_at", 0)) <= time.time():
                self.store.delete("workspace_pending_event", pending["id"])
                continue
            wire = WorkspaceWirePayload(
                kind="workspace_event",
                logical_id=pending["logical_id"],
                workspace_id=workspace_id,
                expires_at=int(pending["expires_at"]),
                document=pending["document"],
            )
            if self._accept_workspace_event(wire):
                self.store.delete("workspace_pending_event", pending["id"])
        self._clear_workspace_sync_issue_if_resolved(workspace_id)

    def list_workspace_messages(
        self,
        workspace_id: Any,
        channel_id: Any,
        cursor: Any = None,
        limit: Any = MESSAGE_PAGE_DEFAULT,
    ) -> dict[str, Any]:
        workspace = self._require_workspace(workspace_id)
        if workspace.get("state") not in {
            "active",
            "leaving",
            "closed",
            "left",
            "removed",
            "forked",
            "incomplete_sync",
        }:
            raise ContactNotApproved("Workspace history is unavailable in this state")
        self._require_workspace_channel(workspace_id, channel_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MESSAGE_PAGE_MAX:
            raise ValidationError("Workspace message page size is invalid")
        index_id = self._workspace_index_record_id(workspace_id, channel_id)
        index = self.store.get("workspace_conversation_index", index_id)
        if index is None:
            return {"messages": [], "next_cursor": None, "high_water": 0}
        page_id = index.get("head_page")
        offset = 0
        if cursor is not None:
            if not isinstance(cursor, str):
                raise ValidationError("Workspace message cursor is invalid")
            value = self.store.open_cursor(cursor)
            expected = {
                "v": 1,
                "workspace_id": workspace_id,
                "conversation_id": channel_id,
                "authorization_generation": int(
                    workspace.get("authorization_generation", 1)
                ),
                "retention_generation": int(workspace.get("retention_generation", 1)),
                "high_water": int(index.get("high_water", 0)),
            }
            if any(value.get(key) != item for key, item in expected.items()):
                raise ValidationError("Workspace message cursor is stale")
            page_id = value.get("page_id")
            offset = value.get("offset")
            if not isinstance(page_id, str) or isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
                raise ValidationError("Workspace message cursor is invalid")
        results: list[dict[str, Any]] = []
        next_page: str | None = None
        next_offset = 0
        while isinstance(page_id, str) and len(results) < limit:
            page = self.store.get("workspace_conversation_index", page_id)
            if (
                page is None
                or page.get("workspace_id") != workspace_id
                or page.get("conversation_id") != channel_id
            ):
                raise ValidationError("Workspace message page is unavailable")
            entries = page.get("entries", [])
            if not isinstance(entries, list) or offset > len(entries):
                raise ValidationError("Workspace message page is invalid")
            position = len(entries) - 1 - offset
            while position >= 0 and len(results) < limit:
                entry = entries[position]
                message = self.store.get(
                    "workspace_message_state", entry["message_record_id"]
                )
                hidden = self.store.get(
                    "workspace_message_hidden",
                    self.store.opaque_id(
                        "workspace-message-hidden", workspace_id, entry["event_id"]
                    ),
                )
                if message is not None and hidden is None:
                    results.append(self._public_workspace_message(message))
                position -= 1
                offset += 1
            if len(results) >= limit and position >= 0:
                next_page = page_id
                next_offset = offset
                break
            page_id = page.get("previous_page")
            offset = 0
            if len(results) >= limit and isinstance(page_id, str):
                next_page = page_id
                next_offset = 0
                break
        next_cursor = None
        if next_page is not None:
            next_cursor = self.store.seal_cursor(
                {
                    "v": 1,
                    "workspace_id": workspace_id,
                    "conversation_id": channel_id,
                    "authorization_generation": int(
                        workspace.get("authorization_generation", 1)
                    ),
                    "retention_generation": int(
                        workspace.get("retention_generation", 1)
                    ),
                    "high_water": int(index.get("high_water", 0)),
                    "page_id": next_page,
                    "offset": next_offset,
                }
            )
        results.reverse()
        return {
            "messages": results,
            "next_cursor": next_cursor,
            "high_water": int(index.get("high_water", 0)),
        }

    def mark_workspace_read(
        self,
        workspace_id: Any,
        channel_id: Any,
        high_water: Any,
        operation_id: Any,
    ) -> dict[str, Any]:
        payload = {
            "workspace_id": workspace_id,
            "channel_id": channel_id,
            "high_water": high_water,
        }
        operation_id, digest, replay = self._workspace_operation(
            "mark_workspace_read", operation_id, payload
        )
        if replay is not None:
            return replay
        self._require_workspace(workspace_id)
        channel = self._require_workspace_channel(workspace_id, channel_id)
        index = self.store.get(
            "workspace_conversation_index",
            self._workspace_index_record_id(workspace_id, channel_id),
        )
        maximum = int(index.get("high_water", 0)) if index else 0
        if isinstance(high_water, bool) or not isinstance(high_water, int) or not 0 <= high_water <= maximum:
            raise ValidationError("Workspace read position is invalid")
        read_id = self.store.opaque_id(
            "workspace-read-state", workspace_id, channel_id
        )
        previous = self.store.get("workspace_read_state", read_id)
        if previous is not None and high_water < int(previous.get("high_water", 0)):
            raise ValidationError("Workspace read position cannot move backwards")
        channel["unread_count"] = max(0, maximum - high_water)
        outcome = {"workspace_id": workspace_id, "channel_id": channel_id, "high_water": high_water}
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [
                (
                    "workspace_channel",
                    self._workspace_channel_record_id(channel_id),
                    channel,
                ),
                (
                    "workspace_read_state",
                    read_id,
                    {
                        "workspace_id": workspace_id,
                        "conversation_id": channel_id,
                        "high_water": high_water,
                    },
                ),
            ],
        )
        self._workspace_changed(
            workspace_id, conversation_id=channel_id, resource_kind="read_state"
        )
        return committed

    def hide_workspace_message(
        self, workspace_id: Any, event_id: Any, operation_id: Any
    ) -> dict[str, Any]:
        payload = {"workspace_id": workspace_id, "event_id": event_id}
        operation_id, digest, replay = self._workspace_operation(
            "hide_workspace_message", operation_id, payload
        )
        if replay is not None:
            return replay
        self._require_workspace(workspace_id)
        message = self.store.get(
            "workspace_message_state", self._workspace_message_record_id(event_id)
        )
        if message is None or message.get("workspace_id") != workspace_id:
            raise ValidationError("Workspace message does not exist")
        marker_id = self.store.opaque_id(
            "workspace-message-hidden", workspace_id, event_id
        )
        outcome = {"workspace_id": workspace_id, "event_id": event_id, "hidden": True}
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [
                (
                    "workspace_message_hidden",
                    marker_id,
                    {"workspace_id": workspace_id, "event_id": event_id},
                )
            ],
        )
        self._workspace_changed(
            workspace_id,
            conversation_id=message.get("conversation_id"),
            resource_kind="message_visibility",
        )
        return committed

    def save_workspace_draft(
        self,
        workspace_id: Any,
        channel_id: Any,
        text: Any,
        operation_id: Any,
    ) -> dict[str, Any]:
        payload = {
            "workspace_id": workspace_id,
            "channel_id": channel_id,
            "text": text,
        }
        operation_id, digest, replay = self._workspace_operation(
            "save_workspace_draft", operation_id, payload
        )
        if replay is not None:
            return replay
        self._require_workspace(workspace_id)
        self._require_workspace_channel(workspace_id, channel_id)
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_MESSAGE_TEXT_BYTES:
            raise ValidationError("Workspace draft is invalid")
        record_id = self.store.opaque_id(
            "workspace-draft", workspace_id, channel_id
        )
        outcome = {
            "workspace_id": workspace_id,
            "conversation_id": channel_id,
            "text": text,
        }
        records = [] if text == "" else [("workspace_draft", record_id, outcome)]
        deletions = [("workspace_draft", record_id)] if text == "" else []
        committed = self.store.commit_operation(
            operation_id, digest, outcome, records, deletions
        )
        self._workspace_changed(
            workspace_id, conversation_id=channel_id, resource_kind="draft"
        )
        return committed

    def create_workspace_channel(
        self,
        workspace_id: Any,
        name: Any,
        topic: Any,
        operation_id: Any,
        visibility: Any = "public",
        member_ids: Any = None,
    ) -> dict[str, Any]:
        payload = {"workspace_id": workspace_id, "name": name, "topic": topic}
        if visibility != "public" or member_ids is not None:
            payload.update({"visibility": visibility, "member_ids": member_ids})
        operation_id, digest, replay = self._workspace_operation(
            "create_workspace_channel", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if workspace.get("state") != "active":
            raise ContactNotApproved("Workspace is not active")
        manifest = self._workspace_current_manifest(workspace)
        local_member = find_member(manifest, workspace["local_member_id"])
        if local_member is None or not self._channel_creation_allowed(
            manifest, local_member
        ):
            raise ContactNotApproved(
                "Workspace channel creation is restricted to the owner"
            )
        if visibility not in {"public", "private"}:
            raise ValidationError("Workspace channel visibility is invalid")
        channels = [
            item
            for item in self.store.list("workspace_channel")
            if item.get("workspace_id") == workspace_id
        ]
        if sum(item.get("state") == "active" for item in channels) >= MAX_PUBLIC_CHANNELS:
            raise ValidationError("A workspace supports at most 32 active channels")
        public_channels = [
            item for item in channels if item.get("visibility") == "public"
        ]
        if visibility == "public" and len(public_channels) >= MAX_RETAINED_PUBLIC_CHANNELS:
            raise ValidationError("The retained public channel directory is full")
        if isinstance(name, str) and channel_name_key(name) == "general":
            raise ValidationError("The general channel name is reserved")
        identity = self._identity
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        if visibility == "private":
            requested_members = (
                [workspace["local_member_id"]]
                if member_ids is None
                else member_ids
            )
            if not isinstance(requested_members, list):
                raise ValidationError("Private channel members are invalid")
            if any(not isinstance(member_id, str) for member_id in requested_members):
                raise ValidationError("Private channel members are invalid")
            checked_members = sorted(set(requested_members))
            if workspace["local_member_id"] not in checked_members:
                checked_members.append(workspace["local_member_id"])
                checked_members.sort()
            if not checked_members or len(checked_members) > MAX_ACTIVE_MEMBERS:
                raise ValidationError("A private channel supports one to eight members")
            if any(
                (member := find_member(manifest, member_id)) is None
                or member.status != "active"
                for member_id in checked_members
            ):
                raise ValidationError("Private channel members must be active workspace members")
            channel_raw = create_workspace_channel_manifest(
                identity,
                workspace_id=workspace_id,
                channel_id=_new_id(),
                manifest_digest=manifest.digest,
                name=name,
                topic=topic,
                manager_member_id=workspace["local_member_id"],
                manager_device_id=workspace["local_device_id"],
                member_ids=checked_members,
            )
            channel = verify_workspace_channel_manifest(
                channel_raw, manifest=manifest
            )
            control_kind = "workspace_channel_manifest"
            recipients = self._workspace_channel_recipients(
                manifest,
                channel,
                excluding_member_id=workspace["local_member_id"],
            )
        else:
            channel_raw = create_workspace_channel_record(
                identity,
                workspace_id=workspace_id,
                channel_id=_new_id(),
                manifest_digest=manifest.digest,
                name=name,
                topic=topic,
                manager_member_id=workspace["local_member_id"],
                manager_device_id=workspace["local_device_id"],
            )
            channel = verify_workspace_channel_record(channel_raw, manifest=manifest)
            control_kind = "workspace_channel_record"
            recipients = self._workspace_manifest_recipients(
                manifest, excluding_member_id=workspace["local_member_id"]
            )
        channel_record = self._channel_record(channel)
        deliveries = self._workspace_channel_deliveries(
            manifest,
            excluding_member_id=workspace["local_member_id"],
            kind=control_kind,
            document=channel.serialized,
            priority=0,
            recipients=recipients,
        )
        if visibility == "public":
            workspace["channel_discovery"] = (
                "converged" if not deliveries else "incomplete"
            )
        workspace["updated_at"] = time.time()
        index = {
            "workspace_id": workspace_id,
            "conversation_id": channel.channel_id,
            "head_page": None,
            "count": 0,
            "high_water": 0,
            "authorization_generation": int(
                workspace.get("authorization_generation", 1)
            ),
            "retention_generation": int(workspace.get("retention_generation", 1)),
        }
        subscription_id = self.store.opaque_id(
            "workspace-subscription", workspace_id, channel.channel_id
        )
        public = dict(channel_record)
        public.update(
            {
                "is_general": False,
                "subscribed": True,
                "duplicate_name": False,
                "display_name": channel.name,
            }
        )
        committed = self.store.commit_operation(
            operation_id,
            digest,
            public,
            [
                ("workspace", self._workspace_record_id(workspace_id), workspace),
                (
                    "workspace_channel",
                    self._workspace_channel_record_id(channel.channel_id),
                    channel_record,
                ),
                (
                    "workspace_channel_control",
                    self._workspace_channel_control_id(channel.digest),
                    self._workspace_channel_control_record(
                        channel, document_type=control_kind
                    ),
                ),
                self._workspace_channel_version_record(channel),
                (
                    "workspace_conversation_index",
                    self._workspace_index_record_id(
                        workspace_id, channel.channel_id
                    ),
                    index,
                ),
                (
                    "workspace_subscription",
                    subscription_id,
                    {
                        "workspace_id": workspace_id,
                        "conversation_id": channel.channel_id,
                        "subscribed": True,
                    },
                ),
                (
                    "workspace_read_state",
                    self.store.opaque_id(
                        "workspace-read-state", workspace_id, channel.channel_id
                    ),
                    {
                        "workspace_id": workspace_id,
                        "conversation_id": channel.channel_id,
                        "high_water": 0,
                    },
                ),
                *[
                    ("workspace_delivery", delivery["id"], delivery)
                    for delivery in deliveries
                ],
                *self._due_records(add=deliveries),
            ],
        )
        self._workspace_changed(
            workspace_id,
            conversation_id=channel.channel_id,
            resource_kind="channel",
        )
        return committed

    def update_workspace_channel(
        self,
        workspace_id: Any,
        channel_id: Any,
        name: Any,
        topic: Any,
        archived: Any,
        operation_id: Any,
    ) -> dict[str, Any]:
        payload = {
            "workspace_id": workspace_id,
            "channel_id": channel_id,
            "name": name,
            "topic": topic,
            "archived": archived,
        }
        operation_id, digest, replay = self._workspace_operation(
            "update_workspace_channel", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if workspace.get("state") != "active":
            raise ContactNotApproved("Workspace is not active")
        stored_channel = self._require_workspace_channel(workspace_id, channel_id)
        if stored_channel.get("state") != "active":
            raise ContactNotApproved("Workspace channel is not active")
        if (
            stored_channel.get("manager_member_id") != workspace["local_member_id"]
            or stored_channel.get("manager_device_id") != workspace["local_device_id"]
        ):
            raise ContactNotApproved("Only the current channel manager can update it")
        if not isinstance(archived, bool):
            raise ValidationError("Workspace channel archive state is invalid")
        previous = self._workspace_channel_by_digest(stored_channel["head_hash"])
        if previous is None:
            raise ValidationError("Workspace channel control is unavailable")
        manifest = self._workspace_current_manifest(workspace)
        identity = self._identity
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        if previous.visibility == "private":
            raw = create_workspace_channel_manifest(
                identity,
                workspace_id=workspace_id,
                channel_id=channel_id,
                manifest_digest=manifest.digest,
                name=name,
                topic=topic,
                manager_member_id=previous.manager_member_id,
                manager_device_id=previous.manager_device_id,
                member_ids=previous.member_ids,
                version=previous.version + 1,
                previous_hash=previous.digest,
                archived=archived,
            )
            channel = verify_workspace_channel_manifest_transition(
                raw, previous, manifest=manifest
            )
            control_kind = "workspace_channel_manifest"
        else:
            raw = create_workspace_channel_record(
                identity,
                workspace_id=workspace_id,
                channel_id=channel_id,
                manifest_digest=manifest.digest,
                name=name,
                topic=topic,
                manager_member_id=previous.manager_member_id,
                manager_device_id=previous.manager_device_id,
                version=previous.version + 1,
                previous_hash=previous.digest,
                archived=archived,
            )
            channel = verify_workspace_channel_record_transition(
                raw, previous, manifest=manifest
            )
            control_kind = "workspace_channel_record"
        updated = self._channel_record(channel)
        updated["unread_count"] = int(stored_channel.get("unread_count", 0))
        updated["created_at"] = float(stored_channel.get("created_at", channel.created_at))
        updated["updated_at"] = time.time()
        deliveries = self._workspace_channel_deliveries(
            manifest,
            excluding_member_id=workspace["local_member_id"],
            kind=control_kind,
            document=channel.serialized,
            priority=0,
            recipients=self._workspace_channel_recipients(
                manifest,
                channel,
                excluding_member_id=workspace["local_member_id"],
            ),
        )
        if channel.visibility == "public":
            workspace["channel_discovery"] = (
                "converged" if not deliveries else "incomplete"
            )
        workspace["updated_at"] = time.time()
        public = self._public_workspace_channel(updated)
        committed = self.store.commit_operation(
            operation_id,
            digest,
            public,
            [
                ("workspace", self._workspace_record_id(workspace_id), workspace),
                (
                    "workspace_channel",
                    self._workspace_channel_record_id(channel_id),
                    updated,
                ),
                (
                    "workspace_channel_control",
                    self._workspace_channel_control_id(channel.digest),
                    self._workspace_channel_control_record(
                        channel, document_type=control_kind
                    ),
                ),
                self._workspace_channel_version_record(channel),
                *[
                    ("workspace_delivery", delivery["id"], delivery)
                    for delivery in deliveries
                ],
                *self._due_records(add=deliveries),
            ],
        )
        self._workspace_changed(
            workspace_id, conversation_id=channel_id, resource_kind="channel"
        )
        return committed

    def update_workspace_private_channel_members(
        self,
        workspace_id: Any,
        channel_id: Any,
        member_ids: Any,
        operation_id: Any,
    ) -> dict[str, Any]:
        payload = {
            "workspace_id": workspace_id,
            "channel_id": channel_id,
            "member_ids": member_ids,
        }
        operation_id, digest, replay = self._workspace_operation(
            "update_workspace_private_channel_members", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        stored = self._require_workspace_channel(workspace_id, channel_id)
        if workspace.get("state") != "active" or stored.get("state") != "active":
            raise ContactNotApproved("Private channel is not active")
        previous = self._workspace_channel_by_digest(stored["head_hash"])
        if previous is None or previous.visibility != "private":
            raise ValidationError("Private channel control is unavailable")
        if (
            previous.manager_member_id != workspace.get("local_member_id")
            or previous.manager_device_id != workspace.get("local_device_id")
        ):
            raise ContactNotApproved(
                "Only the current private-channel manager can change its roster"
            )
        if not isinstance(member_ids, list):
            raise ValidationError("Private channel members are invalid")
        if any(not isinstance(member_id, str) for member_id in member_ids):
            raise ValidationError("Private channel members are invalid")
        checked_members = sorted(set(member_ids))
        if (
            not checked_members
            or len(checked_members) > MAX_ACTIVE_MEMBERS
            or previous.manager_member_id not in checked_members
        ):
            raise ValidationError(
                "A private channel requires one to eight members including its manager"
            )
        manifest = self._workspace_current_manifest(workspace)
        if any(
            (member := find_member(manifest, member_id)) is None
            or member.status != "active"
            for member_id in checked_members
        ):
            raise ValidationError("Private channel members must be active workspace members")
        if tuple(checked_members) == previous.member_ids:
            raise ValidationError("Private channel roster is unchanged")
        identity = self._identity
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        raw = create_workspace_channel_manifest(
            identity,
            workspace_id=workspace_id,
            channel_id=channel_id,
            manifest_digest=manifest.digest,
            name=previous.name,
            topic=previous.topic,
            manager_member_id=previous.manager_member_id,
            manager_device_id=previous.manager_device_id,
            member_ids=checked_members,
            version=previous.version + 1,
            previous_hash=previous.digest,
        )
        channel = verify_workspace_channel_manifest_transition(
            raw, previous, manifest=manifest
        )
        updated = self._channel_record(channel)
        updated["unread_count"] = int(stored.get("unread_count", 0))
        updated["created_at"] = float(stored.get("created_at", previous.created_at))
        updated["updated_at"] = time.time()
        new_control = self._workspace_channel_control_record(
            channel, document_type="workspace_channel_manifest"
        )
        recipients = self._workspace_channel_recipients(
            manifest,
            channel,
            excluding_member_id=workspace["local_member_id"],
        )
        deliveries = [
            self._workspace_delivery_record(
                workspace_id=workspace_id,
                recipient_member_id=member_id,
                recipient_device=device,
                kind=control.get("document_type", "workspace_channel_manifest"),
                document=control["serialized"],
                conversation_id=channel_id,
                priority=0,
            )
            for member_id, device in recipients
            for control in [new_control]
        ]
        removed = set(previous.member_ids) - set(channel.member_ids)
        cancellation_records, outbound_ids = (
            self._cancel_private_channel_member_deliveries(
                workspace_id, channel_id, removed
            )
            if removed
            else ([], set())
        )
        outcome = self._public_workspace_channel(updated)
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [
                ("workspace_channel", self._workspace_channel_record_id(channel_id), updated),
                (
                    "workspace_channel_control",
                    self._workspace_channel_control_id(channel.digest),
                    new_control,
                ),
                self._workspace_channel_version_record(channel),
                *cancellation_records,
                *[("workspace_delivery", item["id"], item) for item in deliveries],
                *self._due_records(add=deliveries),
            ],
        )
        network = getattr(self, "network", None)
        if network is not None and outbound_ids:
            network.cancel_outbound(outbound_ids)
        self._workspace_changed(
            workspace_id, conversation_id=channel_id, resource_kind="channel"
        )
        return committed

    def leave_workspace_private_channel(
        self, workspace_id: Any, channel_id: Any, operation_id: Any
    ) -> dict[str, Any]:
        payload = {"workspace_id": workspace_id, "channel_id": channel_id}
        operation_id, digest, replay = self._workspace_operation(
            "leave_workspace_private_channel", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        stored = self._require_workspace_channel(workspace_id, channel_id)
        if workspace.get("state") != "active" or stored.get("state") != "active":
            raise ContactNotApproved("Private channel is not active")
        channel = self._workspace_channel_by_digest(stored["head_hash"])
        manifest = self._workspace_current_manifest(workspace)
        identity = self._identity
        if channel is None or identity is None or channel.visibility != "private":
            raise ValidationError("Private channel control is unavailable")
        if channel.manager_member_id == workspace.get("local_member_id"):
            raise ContactNotApproved(
                "Transfer private-channel management before leaving"
            )
        raw = create_workspace_channel_leave_request(
            identity,
            channel=channel,
            manifest=manifest,
            member_id=workspace["local_member_id"],
            device_id=workspace["local_device_id"],
        )
        request = verify_workspace_channel_leave_request(
            raw, channel=channel, manifest=manifest
        )
        manager = find_device(manifest, channel.manager_device_id)
        if manager is None:
            raise ValidationError("Private channel manager is unavailable")
        delivery = self._workspace_delivery_record(
            workspace_id=workspace_id,
            recipient_member_id=channel.manager_member_id,
            recipient_device=manager[1],
            kind="workspace_channel_leave_request",
            document=request.serialized,
            conversation_id=channel_id,
            priority=0,
        )
        stored["state"] = "leaving"
        stored["updated_at"] = time.time()
        outcome = self._public_workspace_channel(stored)
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [
                ("workspace_channel", self._workspace_channel_record_id(channel_id), stored),
                ("workspace_delivery", delivery["id"], delivery),
                *self._due_records(add=[delivery]),
            ],
        )
        self._workspace_changed(
            workspace_id, conversation_id=channel_id, resource_kind="channel"
        )
        return committed

    def set_workspace_channel_subscription(
        self,
        workspace_id: Any,
        channel_id: Any,
        subscribed: Any,
        operation_id: Any,
    ) -> dict[str, Any]:
        payload = {
            "workspace_id": workspace_id,
            "channel_id": channel_id,
            "subscribed": subscribed,
        }
        operation_id, digest, replay = self._workspace_operation(
            "set_workspace_channel_subscription", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        channel = self._require_workspace_channel(workspace_id, channel_id)
        if not isinstance(subscribed, bool):
            raise ValidationError("Workspace channel subscription is invalid")
        if channel_id == workspace.get("general_channel_id") and not subscribed:
            raise ContactNotApproved("The general channel is always subscribed")
        if workspace.get("state") not in {"active", "incomplete_sync"}:
            raise ContactNotApproved("Workspace subscriptions cannot change now")
        index = self.store.get(
            "workspace_conversation_index",
            self._workspace_index_record_id(workspace_id, channel_id),
        )
        high_water = int(index.get("high_water", 0)) if index else 0
        channel["unread_count"] = 0
        result = {
            "workspace_id": workspace_id,
            "channel_id": channel_id,
            "subscribed": subscribed,
            "high_water": high_water,
        }
        committed = self.store.commit_operation(
            operation_id,
            digest,
            result,
            [
                (
                    "workspace_channel",
                    self._workspace_channel_record_id(channel_id),
                    channel,
                ),
                (
                    "workspace_subscription",
                    self.store.opaque_id(
                        "workspace-subscription", workspace_id, channel_id
                    ),
                    {
                        "workspace_id": workspace_id,
                        "conversation_id": channel_id,
                        "subscribed": subscribed,
                    },
                ),
                (
                    "workspace_read_state",
                    self.store.opaque_id(
                        "workspace-read-state", workspace_id, channel_id
                    ),
                    {
                        "workspace_id": workspace_id,
                        "conversation_id": channel_id,
                        "high_water": high_water,
                    },
                ),
            ],
        )
        self._workspace_changed(
            workspace_id, conversation_id=channel_id, resource_kind="subscription"
        )
        return committed

    def offer_workspace_channel_transfer(
        self,
        workspace_id: Any,
        channel_id: Any,
        successor_member_id: Any,
        operation_id: Any,
    ) -> dict[str, Any]:
        payload = {
            "workspace_id": workspace_id,
            "channel_id": channel_id,
            "successor_member_id": successor_member_id,
        }
        operation_id, digest, replay = self._workspace_operation(
            "offer_workspace_channel_transfer", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        channel_record = self._require_workspace_channel(workspace_id, channel_id)
        if channel_id == workspace.get("general_channel_id"):
            raise ContactNotApproved(
                "General channel management follows workspace ownership"
            )
        if (
            workspace.get("state") != "active"
            or channel_record.get("state") != "active"
            or channel_record.get("manager_member_id")
            != workspace.get("local_member_id")
            or channel_record.get("manager_device_id")
            != workspace.get("local_device_id")
        ):
            raise ContactNotApproved("Only the active channel manager can transfer it")
        manifest = self._workspace_current_manifest(workspace)
        successor = find_member(manifest, successor_member_id)
        if successor is None or successor.status != "active":
            raise ValidationError("Workspace channel successor is not active")
        channel = self._workspace_channel_by_digest(channel_record["head_hash"])
        identity = self._identity
        if channel is None or identity is None:
            raise ValidationError("Workspace channel control is unavailable")
        raw = create_workspace_channel_transfer_offer(
            identity,
            channel=channel,
            manifest=manifest,
            successor_member_id=successor.member_id,
            successor_device_id=successor.devices[0].device_id,
        )
        offer = verify_workspace_channel_transfer_offer(
            raw, channel=channel, manifest=manifest
        )
        record_id = self._workspace_channel_transfer_id(offer.digest)
        record = {
            "id": record_id,
            "workspace_id": workspace_id,
            "channel_id": channel_id,
            "channel_head": offer.channel_head,
            "manifest_digest": offer.manifest_digest,
            "manager_member_id": offer.manager_member_id,
            "successor_member_id": offer.successor_member_id,
            "successor_device_id": offer.successor_device_id,
            "state": "offered",
            "document": offer.serialized,
            "created_at": float(offer.created_at),
            "expires_at": float(offer.expires_at),
        }
        deliveries = self._workspace_channel_deliveries(
            manifest,
            excluding_member_id=workspace["local_member_id"],
            kind="workspace_channel_transfer_offer",
            document=offer.serialized,
            priority=0,
            recipients=self._workspace_channel_recipients(
                manifest,
                channel,
                excluding_member_id=workspace["local_member_id"],
            ),
        )
        outcome = {key: value for key, value in record.items() if key != "document"}
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [
                ("workspace_channel_transfer", record_id, record),
                *[
                    ("workspace_delivery", delivery["id"], delivery)
                    for delivery in deliveries
                ],
                *self._due_records(add=deliveries),
            ],
        )
        self._workspace_changed(workspace_id, resource_kind="channel_transfer")
        return committed

    def accept_workspace_channel_transfer(
        self, workspace_id: Any, transfer_id: Any, operation_id: Any
    ) -> dict[str, Any]:
        payload = {"workspace_id": workspace_id, "transfer_id": transfer_id}
        operation_id, digest, replay = self._workspace_operation(
            "accept_workspace_channel_transfer", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if not isinstance(transfer_id, str):
            raise ValidationError("Workspace channel transfer ID is invalid")
        transfer = self.store.get("workspace_channel_transfer", transfer_id)
        if (
            transfer is None
            or transfer.get("workspace_id") != workspace_id
            or transfer.get("state") != "offered"
        ):
            raise ValidationError("Workspace channel transfer is unavailable")
        if (
            transfer.get("successor_member_id") != workspace.get("local_member_id")
            or transfer.get("successor_device_id") != workspace.get("local_device_id")
        ):
            raise ContactNotApproved("Only the named successor can accept this transfer")
        channel_record = self._require_workspace_channel(
            workspace_id, transfer["channel_id"]
        )
        channel = self._workspace_channel_by_digest(channel_record["head_hash"])
        manifest = self._workspace_current_manifest(workspace)
        identity = self._identity
        if channel is None or identity is None:
            raise ValidationError("Workspace channel control is unavailable")
        offer = verify_workspace_channel_transfer_offer(
            transfer["document"], channel=channel, manifest=manifest
        )
        raw = create_workspace_channel_transfer(identity, offer=offer)
        next_channel = verify_workspace_channel_transfer(
            raw, channel=channel, manifest=manifest
        )
        updated = self._channel_record(next_channel)
        updated["unread_count"] = int(channel_record.get("unread_count", 0))
        updated["created_at"] = float(channel_record.get("created_at", channel.created_at))
        updated["updated_at"] = time.time()
        transfer["state"] = "accepted"
        transfer["accepted_at"] = time.time()
        deliveries = self._workspace_channel_deliveries(
            manifest,
            excluding_member_id=workspace["local_member_id"],
            kind="workspace_channel_transfer",
            document=next_channel.serialized,
            priority=0,
            recipients=self._workspace_channel_recipients(
                manifest,
                next_channel,
                excluding_member_id=workspace["local_member_id"],
            ),
        )
        if next_channel.visibility == "public":
            workspace["channel_discovery"] = (
                "converged" if not deliveries else "incomplete"
            )
        outcome = self._public_workspace_channel(updated)
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [
                ("workspace", self._workspace_record_id(workspace_id), workspace),
                (
                    "workspace_channel",
                    self._workspace_channel_record_id(next_channel.channel_id),
                    updated,
                ),
                (
                    "workspace_channel_control",
                    self._workspace_channel_control_id(next_channel.digest),
                    self._workspace_channel_control_record(
                        next_channel, document_type="workspace_channel_transfer"
                    ),
                ),
                self._workspace_channel_version_record(next_channel),
                ("workspace_channel_transfer", transfer_id, transfer),
                *[
                    ("workspace_delivery", delivery["id"], delivery)
                    for delivery in deliveries
                ],
                *self._due_records(add=deliveries),
            ],
        )
        self._workspace_changed(
            workspace_id,
            conversation_id=next_channel.channel_id,
            resource_kind="channel",
        )
        return committed

    def recover_workspace_channel(
        self, workspace_id: Any, channel_id: Any, operation_id: Any
    ) -> dict[str, Any]:
        payload = {"workspace_id": workspace_id, "channel_id": channel_id}
        operation_id, digest, replay = self._workspace_operation(
            "recover_workspace_channel", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if workspace.get("state") != "active" or workspace.get("local_role") != "owner":
            raise ContactNotApproved("Only the active workspace owner can recover a channel")
        channel_record = self._require_workspace_channel(workspace_id, channel_id)
        if channel_record.get("state") != "active":
            raise ContactNotApproved("Forked or archived channels cannot be recovered")
        channel = self._workspace_channel_by_digest(channel_record["head_hash"])
        manifest = self._workspace_current_manifest(workspace)
        identity = self._identity
        if channel is None or identity is None:
            raise ValidationError("Workspace channel control is unavailable")
        if (
            channel.visibility == "private"
            and workspace["local_member_id"] not in channel.member_ids
        ):
            raise ContactNotApproved(
                "A workspace owner can recover a private channel only as a current member"
            )
        if (
            channel.manager_member_id == workspace["local_member_id"]
            and channel.manager_device_id == workspace["local_device_id"]
        ):
            raise ValidationError("Workspace channel is already managed by the owner")
        raw = create_workspace_channel_recovery(
            identity,
            channel=channel,
            manifest=manifest,
            manager_member_id=workspace["local_member_id"],
            manager_device_id=workspace["local_device_id"],
        )
        next_channel = verify_workspace_channel_recovery(
            raw, channel=channel, manifest=manifest
        )
        updated = self._channel_record(next_channel)
        updated["unread_count"] = int(channel_record.get("unread_count", 0))
        updated["created_at"] = float(channel_record.get("created_at", channel.created_at))
        updated["updated_at"] = time.time()
        deliveries = self._workspace_channel_deliveries(
            manifest,
            excluding_member_id=workspace["local_member_id"],
            kind="workspace_channel_recovery",
            document=next_channel.serialized,
            priority=0,
            recipients=self._workspace_channel_recipients(
                manifest,
                next_channel,
                excluding_member_id=workspace["local_member_id"],
            ),
        )
        if next_channel.visibility == "public":
            workspace["channel_discovery"] = (
                "converged" if not deliveries else "incomplete"
            )
        outcome = self._public_workspace_channel(updated)
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [
                ("workspace", self._workspace_record_id(workspace_id), workspace),
                (
                    "workspace_channel",
                    self._workspace_channel_record_id(channel_id),
                    updated,
                ),
                (
                    "workspace_channel_control",
                    self._workspace_channel_control_id(next_channel.digest),
                    self._workspace_channel_control_record(
                        next_channel, document_type="workspace_channel_recovery"
                    ),
                ),
                self._workspace_channel_version_record(next_channel),
                *[
                    ("workspace_delivery", delivery["id"], delivery)
                    for delivery in deliveries
                ],
                *self._due_records(add=deliveries),
            ],
        )
        self._workspace_changed(
            workspace_id, conversation_id=channel_id, resource_kind="channel"
        )
        return committed

    def sync_workspace_channels(
        self, workspace_id: Any, operation_id: Any
    ) -> dict[str, Any]:
        payload = {"workspace_id": workspace_id}
        operation_id, digest, replay = self._workspace_operation(
            "sync_workspace_channels", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if workspace.get("state") not in {"active", "incomplete_sync"}:
            raise ContactNotApproved("Workspace channel discovery cannot run now")
        manifest = self._workspace_current_manifest(workspace)
        identity = self._identity
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        recipients = self._workspace_manifest_recipients(
            manifest,
            excluding_member_id=workspace["local_member_id"],
        )
        deliveries = self._workspace_channel_summary_deliveries(
            workspace,
            manifest,
            identity,
            operation_id,
            recipients,
        )
        workspace["channel_discovery"] = (
            "converged" if not deliveries else "incomplete"
        )
        workspace["updated_at"] = time.time()
        outcome = {
            "workspace_id": workspace_id,
            "session_id": operation_id,
            "state": workspace["channel_discovery"],
            "peer_count": len({member_id for member_id, _device in recipients}),
        }
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [
                ("workspace", self._workspace_record_id(workspace_id), workspace),
                *[
                    ("workspace_delivery", delivery["id"], delivery)
                    for delivery in deliveries
                ],
                *self._due_records(add=deliveries),
            ],
        )
        self._workspace_changed(workspace_id, resource_kind="channel_discovery")
        return committed

    def update_workspace_policies(
        self,
        workspace_id: Any,
        channel_creation: Any,
        posting: Any,
        operation_id: Any,
    ) -> dict[str, Any]:
        payload = {
            "workspace_id": workspace_id,
            "channel_creation": channel_creation,
            "posting": posting,
        }
        operation_id, digest, replay = self._workspace_operation(
            "update_workspace_policies", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if workspace.get("state") != "active" or workspace.get("local_role") != "owner":
            raise ContactNotApproved("Workspace policy changes wait for the active owner")
        try:
            creation_policy = WorkspaceChannelCreationPolicy(channel_creation)
            posting_policy = WorkspacePostingPolicy(posting)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Workspace channel policy is invalid") from exc
        current = self._workspace_current_manifest(workspace)
        if (
            current.channel_creation == creation_policy
            and current.posting == posting_policy
        ):
            raise ValidationError("Workspace channel policies are unchanged")
        identity = self._identity
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        raw = create_workspace_manifest(
            identity,
            workspace_id=workspace_id,
            epoch=current.epoch + 1,
            previous_manifest_hash=current.digest,
            name=current.name,
            description=current.description,
            authority_device_id=current.authority_device_id,
            members=self._workspace_manifest_member_inputs(current),
            retention_days=current.retention_days,
            channel_creation=creation_policy,
            posting=posting_policy,
            invitation_requests=current.invitation_requests,
        )
        next_manifest = verify_workspace_manifest_transition(raw, current)
        deliveries = self._workspace_manifest_deliveries(
            workspace_id,
            [next_manifest],
            self._workspace_manifest_recipients(
                current, excluding_member_id=workspace["local_member_id"]
            ),
        )
        self._apply_manifest_to_workspace(workspace, next_manifest)
        self._apply_manifest_public_identities(workspace, next_manifest)
        outcome = self._public_workspace(workspace)
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [
                ("workspace", self._workspace_record_id(workspace_id), workspace),
                (
                    "workspace_manifest",
                    self._workspace_manifest_record_id(next_manifest.digest),
                    self._manifest_record(next_manifest),
                ),
                self._manifest_epoch_record(next_manifest),
                *[
                    ("workspace_delivery", delivery["id"], delivery)
                    for delivery in deliveries
                ],
                *self._due_records(add=deliveries),
            ],
        )
        self._workspace_changed(workspace_id, resource_kind="policy")
        return committed

    def update_workspace_metadata(
        self,
        workspace_id: Any,
        name: Any,
        description: Any,
        operation_id: Any,
    ) -> dict[str, Any]:
        payload = {
            "workspace_id": workspace_id,
            "name": name,
            "description": description,
        }
        operation_id, digest, replay = self._workspace_operation(
            "update_workspace_metadata", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if (
            workspace.get("state") != "active"
            or workspace.get("local_role") != WorkspaceRole.OWNER.value
        ):
            raise ContactNotApproved(
                "Workspace metadata changes wait for the active owner"
            )
        identity = self._identity
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        current = self._workspace_current_manifest(workspace)
        raw = create_workspace_manifest(
            identity,
            workspace_id=workspace_id,
            epoch=current.epoch + 1,
            previous_manifest_hash=current.digest,
            name=name,
            description=description,
            authority_device_id=current.authority_device_id,
            members=self._workspace_manifest_member_inputs(current),
            retention_days=current.retention_days,
            channel_creation=current.channel_creation,
            posting=current.posting,
            invitation_requests=current.invitation_requests,
        )
        next_manifest = verify_workspace_manifest_transition(raw, current)
        recipients = self._workspace_manifest_recipients(
            current, excluding_member_id=workspace["local_member_id"]
        )
        deliveries = self._workspace_manifest_deliveries(
            workspace_id, [next_manifest], recipients
        )
        self._apply_manifest_to_workspace(workspace, next_manifest)
        self._apply_manifest_public_identities(workspace, next_manifest)
        outcome = self._public_workspace(workspace)
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [
                ("workspace", self._workspace_record_id(workspace_id), workspace),
                (
                    "workspace_manifest",
                    self._workspace_manifest_record_id(next_manifest.digest),
                    self._manifest_record(next_manifest),
                ),
                self._manifest_epoch_record(next_manifest),
                *[
                    ("workspace_delivery", delivery["id"], delivery)
                    for delivery in deliveries
                ],
                *self._due_records(add=deliveries),
            ],
        )
        self._workspace_changed(workspace_id, resource_kind="metadata")
        return committed

    def remove_workspace_member(
        self, workspace_id: Any, member_id: Any, operation_id: Any
    ) -> dict[str, Any]:
        payload = {"workspace_id": workspace_id, "member_id": member_id}
        operation_id, digest, replay = self._workspace_operation(
            "remove_workspace_member", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if (
            workspace.get("state") != "active"
            or workspace.get("local_role") != WorkspaceRole.OWNER.value
        ):
            raise ContactNotApproved("Member removal waits for the active owner")
        if not isinstance(member_id, str):
            raise ValidationError("Workspace member ID is invalid")
        identity = self._identity
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        current = self._workspace_current_manifest(workspace)
        member = find_member(current, member_id)
        if (
            member is None
            or member.role == WorkspaceRole.OWNER
            or member.status != "active"
        ):
            raise ValidationError("Workspace member cannot be removed")
        raw = create_workspace_manifest(
            identity,
            workspace_id=workspace_id,
            epoch=current.epoch + 1,
            previous_manifest_hash=current.digest,
            name=current.name,
            description=current.description,
            authority_device_id=current.authority_device_id,
            members=self._workspace_manifest_member_inputs(
                current,
                replacement_member_id=member_id,
                replacement_status="removed",
            ),
            retention_days=current.retention_days,
            channel_creation=current.channel_creation,
            posting=current.posting,
            invitation_requests=current.invitation_requests,
        )
        next_manifest = verify_workspace_manifest_transition(raw, current)
        recipients = self._workspace_manifest_recipients(
            current,
            excluding_member_id=workspace["local_member_id"],
            include_member_ids={member_id},
        )
        deliveries = self._workspace_manifest_deliveries(
            workspace_id, [next_manifest], recipients
        )
        cancelled_records, cancelled_ids = self._cancel_workspace_member_deliveries(
            workspace_id, member_id
        )
        self._apply_manifest_to_workspace(workspace, next_manifest)
        self._apply_manifest_public_identities(workspace, next_manifest)
        outcome = self._public_workspace(workspace)
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [
                ("workspace", self._workspace_record_id(workspace_id), workspace),
                (
                    "workspace_manifest",
                    self._workspace_manifest_record_id(next_manifest.digest),
                    self._manifest_record(next_manifest),
                ),
                self._manifest_epoch_record(next_manifest),
                *cancelled_records,
                *[
                    ("workspace_delivery", delivery["id"], delivery)
                    for delivery in deliveries
                ],
                *self._due_records(add=deliveries, remove=cancelled_ids),
            ],
        )
        network = getattr(self, "network", None)
        if network is not None and cancelled_ids:
            network.cancel_outbound(cancelled_ids)
        self._workspace_changed(workspace_id, resource_kind="membership")
        return committed

    def request_workspace_display_name(
        self, workspace_id: Any, display_name: Any, operation_id: Any
    ) -> dict[str, Any]:
        payload = {"workspace_id": workspace_id, "display_name": display_name}
        operation_id, digest, replay = self._workspace_operation(
            "request_workspace_display_name", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if workspace.get("state") != "active":
            raise ContactNotApproved("Workspace is not active")
        identity = self._identity
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        manifest = self._workspace_current_manifest(workspace)
        raw = create_workspace_display_name_request(
            identity,
            manifest=manifest,
            member_id=workspace["local_member_id"],
            device_id=workspace["local_device_id"],
            display_name=display_name,
            hints=self._workspace_hints(),
        )
        request = verify_workspace_display_name_request(raw, manifest=manifest)
        request_id = self.store.opaque_id(
            "workspace-display-name-request", request.digest
        )
        record = {
            "id": request_id,
            "workspace_id": workspace_id,
            "manifest_digest": request.manifest_digest,
            "request_digest": request.digest,
            "member_id": request.member_id,
            "device_id": request.device_id,
            "display_name": request.display_name,
            "document": request.serialized,
            "state": "pending",
            "created_at": float(request.created_at),
        }
        deliveries: list[dict[str, Any]] = []
        if workspace.get("local_role") != WorkspaceRole.OWNER.value:
            authority = find_device(manifest, manifest.authority_device_id)
            if authority is None:
                raise ValidationError("Workspace authority is unavailable")
            deliveries.append(
                self._workspace_delivery_record(
                    workspace_id=workspace_id,
                    recipient_member_id=authority[0].member_id,
                    recipient_device=authority[1],
                    kind="workspace_display_name_request",
                    document=request.serialized,
                    priority=0,
                )
            )
        outcome = {
            key: value for key, value in record.items() if key != "document"
        }
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [
                ("workspace_display_name_request", request_id, record),
                *[
                    ("workspace_delivery", delivery["id"], delivery)
                    for delivery in deliveries
                ],
                *self._due_records(add=deliveries),
            ],
        )
        self._workspace_changed(workspace_id, resource_kind="display_name_request")
        return committed

    def _receive_workspace_display_name_request(
        self, wire: WorkspaceWirePayload
    ) -> None:
        workspace = self.store.get(
            "workspace", self._workspace_record_id(wire.workspace_id)
        )
        if (
            workspace is None
            or workspace.get("state") != "active"
            or workspace.get("local_role") != WorkspaceRole.OWNER.value
        ):
            return
        try:
            raw_value = json.loads(wire.document)
            if not isinstance(raw_value, dict) or not isinstance(
                raw_value.get("manifest_digest"), str
            ):
                return
            manifest = self._workspace_manifest_by_digest(
                raw_value["manifest_digest"]
            )
            if manifest is None:
                return
            request = verify_workspace_display_name_request(
                wire.document, manifest=manifest
            )
            request_id = self.store.opaque_id(
                "workspace-display-name-request", request.digest
            )
            if self.store.get("workspace_display_name_request", request_id):
                return
            self.store.put(
                "workspace_display_name_request",
                request_id,
                {
                    "id": request_id,
                    "workspace_id": request.workspace_id,
                    "manifest_digest": request.manifest_digest,
                    "request_digest": request.digest,
                    "member_id": request.member_id,
                    "device_id": request.device_id,
                    "display_name": request.display_name,
                    "document": request.serialized,
                    "state": "pending",
                    "created_at": float(request.created_at),
                },
            )
            self._workspace_changed(
                request.workspace_id, resource_kind="display_name_request"
            )
        except (MeshChatError, json.JSONDecodeError):
            return

    def _receive_workspace_display_name_decision(
        self, wire: WorkspaceWirePayload
    ) -> None:
        workspace = self.store.get(
            "workspace", self._workspace_record_id(wire.workspace_id)
        )
        if workspace is None or workspace.get("state") not in {
            "active",
            "incomplete_sync",
        }:
            return
        try:
            value = json.loads(wire.document)
            if not isinstance(value, dict) or not isinstance(
                value.get("request_digest"), str
            ):
                return
            matched = next(
                (
                    (record_id, record)
                    for record_id, record in self.store.items(
                        "workspace_display_name_request"
                    )
                    if record.get("workspace_id") == wire.workspace_id
                    and record.get("request_digest") == value["request_digest"]
                    and record.get("state") == "pending"
                ),
                None,
            )
            if matched is None:
                return
            request_id, record = matched
            base = self._workspace_manifest_by_digest(record["manifest_digest"])
            if base is None:
                return
            request = verify_workspace_display_name_request(
                record["document"], manifest=base
            )
            decision = verify_workspace_display_name_decision(
                wire.document, manifest=base, request=request
            )
            if decision.member_id != workspace["local_member_id"]:
                return
            record["state"] = "approved" if decision.approved else "declined"
            record["updated_at"] = time.time()
            self.store.put(
                "workspace_display_name_request", request_id, record
            )
            self._workspace_changed(
                workspace["id"], resource_kind="display_name_request"
            )
        except (MeshChatError, json.JSONDecodeError):
            return

    def decide_workspace_display_name(
        self,
        workspace_id: Any,
        request_id: Any,
        approve: bool,
        operation_id: Any,
    ) -> dict[str, Any]:
        payload = {
            "workspace_id": workspace_id,
            "request_id": request_id,
            "approve": approve,
        }
        operation_id, digest, replay = self._workspace_operation(
            "decide_workspace_display_name", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if (
            workspace.get("state") != "active"
            or workspace.get("local_role") != WorkspaceRole.OWNER.value
        ):
            raise ContactNotApproved(
                "Display-name decisions wait for the active owner"
            )
        if not isinstance(request_id, str) or not isinstance(approve, bool):
            raise ValidationError("Workspace display-name decision is invalid")
        record = self.store.get("workspace_display_name_request", request_id)
        if (
            record is None
            or record.get("workspace_id") != workspace_id
            or record.get("state") != "pending"
        ):
            raise ValidationError("Workspace display-name request is no longer pending")
        identity = self._identity
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        base = self._workspace_manifest_by_digest(record["manifest_digest"])
        if base is None:
            raise ValidationError("Display-name request base manifest is unavailable")
        request = verify_workspace_display_name_request(
            record["document"], manifest=base
        )
        if not approve:
            current = self._workspace_current_manifest(workspace)
            member = find_member(current, request.member_id)
            if member is None or member.status != "active":
                raise ValidationError("Workspace display-name request is stale")
            decision_raw = create_workspace_display_name_decision(
                identity,
                manifest=base,
                request=request,
                approved=False,
            )
            deliveries = (
                []
                if member.member_id == workspace["local_member_id"]
                else [
                    self._workspace_delivery_record(
                        workspace_id=workspace_id,
                        recipient_member_id=member.member_id,
                        recipient_device=member.devices[0],
                        kind="workspace_display_name_decision",
                        document=decision_raw,
                        priority=0,
                    )
                ]
            )
            record["state"] = "declined"
            record["updated_at"] = time.time()
            outcome = {"id": request_id, "state": "declined"}
            committed = self.store.commit_operation(
                operation_id,
                digest,
                outcome,
                [
                    ("workspace_display_name_request", request_id, record),
                    *[
                        ("workspace_delivery", delivery["id"], delivery)
                        for delivery in deliveries
                    ],
                    *self._due_records(add=deliveries),
                ],
            )
            self._workspace_changed(
                workspace_id, resource_kind="display_name_request"
            )
            return committed
        current = self._workspace_current_manifest(workspace)
        member = find_member(current, request.member_id)
        if (
            member is None
            or member.status != "active"
            or member.devices[0].device_id != request.device_id
            or member.devices[0].public_identity
            != request.replacement_device.public_identity
        ):
            raise ValidationError("Workspace display-name request is stale")
        raw = create_workspace_manifest(
            identity,
            workspace_id=workspace_id,
            epoch=current.epoch + 1,
            previous_manifest_hash=current.digest,
            name=current.name,
            description=current.description,
            authority_device_id=current.authority_device_id,
            members=self._workspace_manifest_member_inputs(
                current,
                replacement_member_id=request.member_id,
                replacement_display_name=request.display_name,
                replacement_device=request.replacement_device.serialized,
            ),
            retention_days=current.retention_days,
            channel_creation=current.channel_creation,
            posting=current.posting,
            invitation_requests=current.invitation_requests,
        )
        next_manifest = verify_workspace_manifest_transition(raw, current)
        recipients = self._workspace_manifest_recipients(
            current, excluding_member_id=workspace["local_member_id"]
        )
        deliveries = self._workspace_manifest_deliveries(
            workspace_id, [next_manifest], recipients
        )
        self._apply_manifest_to_workspace(workspace, next_manifest)
        self._apply_manifest_public_identities(workspace, next_manifest)
        record["state"] = "approved"
        record["updated_at"] = time.time()
        outcome = {
            "id": request_id,
            "state": "approved",
            "workspace": self._public_workspace(workspace),
        }
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [
                ("workspace", self._workspace_record_id(workspace_id), workspace),
                (
                    "workspace_manifest",
                    self._workspace_manifest_record_id(next_manifest.digest),
                    self._manifest_record(next_manifest),
                ),
                self._manifest_epoch_record(next_manifest),
                ("workspace_display_name_request", request_id, record),
                *[
                    ("workspace_delivery", delivery["id"], delivery)
                    for delivery in deliveries
                ],
                *self._due_records(add=deliveries),
            ],
        )
        self._workspace_changed(workspace_id, resource_kind="membership")
        return committed

    def leave_workspace(self, workspace_id: Any, operation_id: Any) -> dict[str, Any]:
        payload = {"workspace_id": workspace_id}
        operation_id, digest, replay = self._workspace_operation(
            "leave_workspace", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if workspace.get("state") != "active":
            raise ValidationError("Workspace is not active")
        if workspace.get("local_role") == "owner":
            raise ValidationError("Workspace owner cannot leave before transferring ownership")
        identity = self._identity
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        manifest = self._workspace_current_manifest(workspace)
        raw = create_workspace_leave_request(
            identity,
            manifest=manifest,
            member_id=workspace["local_member_id"],
            device_id=workspace["local_device_id"],
        )
        authority = find_device(manifest, manifest.authority_device_id)
        if authority is None:
            raise ValidationError("Workspace authority is unavailable")
        delivery = self._workspace_delivery_record(
            workspace_id=workspace_id,
            recipient_member_id=authority[0].member_id,
            recipient_device=authority[1],
            kind="workspace_leave_request",
            document=raw,
            priority=0,
        )
        workspace["state"] = "leaving"
        workspace["updated_at"] = time.time()
        outcome = self._public_workspace(workspace)
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [
                ("workspace", self._workspace_record_id(workspace_id), workspace),
                ("workspace_delivery", delivery["id"], delivery),
                *self._due_records(add=[delivery]),
            ],
        )
        self._workspace_changed(workspace_id)
        return committed

    def _receive_workspace_leave_request(self, wire: WorkspaceWirePayload) -> None:
        workspace = self.store.get(
            "workspace", self._workspace_record_id(wire.workspace_id)
        )
        if workspace is None or workspace.get("local_role") != "owner" or workspace.get("state") != "active":
            return
        try:
            current = self._workspace_current_manifest(workspace)
            request = verify_workspace_leave_request(wire.document, manifest=current)
            identity = self._identity
            if identity is None:
                return
            leaving_member = find_member(current, request.member_id)
            if leaving_member is None:
                return
            inputs = self._workspace_manifest_member_inputs(
                current,
                replacement_member_id=request.member_id,
                replacement_status="left",
            )
            raw = create_workspace_manifest(
                identity,
                workspace_id=workspace["id"],
                epoch=current.epoch + 1,
                previous_manifest_hash=current.digest,
                name=current.name,
                description=current.description,
                authority_device_id=current.authority_device_id,
                members=inputs,
                retention_days=current.retention_days,
                channel_creation=current.channel_creation,
                posting=current.posting,
                invitation_requests=current.invitation_requests,
            )
            next_manifest = verify_workspace_manifest_transition(raw, current)
            self._apply_manifest_to_workspace(workspace, next_manifest)
            self._apply_manifest_public_identities(workspace, next_manifest)
            recipients = self._workspace_manifest_recipients(
                current,
                excluding_member_id=workspace["local_member_id"],
                include_member_ids={request.member_id},
            )
            deliveries = self._workspace_manifest_deliveries(
                workspace["id"], [next_manifest], recipients
            )
            cancelled_records, cancelled_ids = (
                self._cancel_workspace_member_deliveries(
                    workspace["id"], request.member_id
                )
            )
            self.store.put_many(
                [
                    ("workspace", self._workspace_record_id(workspace["id"]), workspace),
                    (
                        "workspace_manifest",
                        self._workspace_manifest_record_id(next_manifest.digest),
                        self._manifest_record(next_manifest),
                    ),
                    self._manifest_epoch_record(next_manifest),
                    *cancelled_records,
                    *[
                        ("workspace_delivery", delivery["id"], delivery)
                        for delivery in deliveries
                    ],
                    *self._due_records(
                        add=deliveries, remove=cancelled_ids
                    ),
                ]
            )
            network = getattr(self, "network", None)
            if network is not None and cancelled_ids:
                network.cancel_outbound(cancelled_ids)
            self._workspace_changed(workspace["id"])
        except MeshChatError:
            return

    def close_workspace(self, workspace_id: Any, operation_id: Any) -> dict[str, Any]:
        payload = {"workspace_id": workspace_id}
        operation_id, digest, replay = self._workspace_operation(
            "close_workspace", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if workspace.get("state") != "active" or workspace.get("local_role") != "owner":
            raise ContactNotApproved("Only the active workspace owner can close it")
        identity = self._identity
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        current = self._workspace_current_manifest(workspace)
        raw = create_workspace_manifest(
            identity,
            workspace_id=workspace_id,
            epoch=current.epoch + 1,
            previous_manifest_hash=current.digest,
            name=current.name,
            description=current.description,
            authority_device_id=current.authority_device_id,
            members=[
                WorkspaceManifestMemberInput(
                    member.member_id,
                    member.display_name,
                    member.role,
                    [item.serialized for item in member.devices],
                    member.status,
                )
                for member in current.members
            ],
            status="closed",
            retention_days=current.retention_days,
            channel_creation=current.channel_creation,
            posting=current.posting,
            invitation_requests=current.invitation_requests,
        )
        closed = verify_workspace_manifest_transition(raw, current)
        self._apply_manifest_to_workspace(workspace, closed)
        for member in workspace["members"]:
            verified = find_member(closed, member["id"])
            if verified is not None:
                member["device"]["public_identity"] = _b64(
                    verified.devices[0].public_identity
                )
        deliveries = [
            self._workspace_delivery_record(
                workspace_id=workspace_id,
                recipient_member_id=member.member_id,
                recipient_device=device,
                kind="workspace_manifest_root",
                document=closed.serialized,
                priority=0,
            )
            for member in current.members
            for device in member.devices
            if member.member_id != workspace["local_member_id"] and member.status == "active"
        ]
        invalidated_records: list[tuple[str, str, dict[str, Any]]] = []
        for record_id, invitation in self.store.items("workspace_invitation"):
            if (
                invitation.get("workspace_id") == workspace_id
                and invitation.get("state") == "active"
            ):
                invitation["state"] = "closed"
                invitation["updated_at"] = time.time()
                invalidated_records.append(
                    ("workspace_invitation", record_id, invitation)
                )
        for record_id, request in self.store.items("workspace_join_request"):
            if (
                request.get("workspace_id") == workspace_id
                and request.get("state") == "pending"
            ):
                request["state"] = "closed"
                request["updated_at"] = time.time()
                invalidated_records.append(
                    ("workspace_join_request", record_id, request)
                )
        outcome = self._public_workspace(workspace)
        records = [
            ("workspace", self._workspace_record_id(workspace_id), workspace),
            (
                "workspace_manifest",
                self._workspace_manifest_record_id(closed.digest),
                self._manifest_record(closed),
            ),
            self._manifest_epoch_record(closed),
            *invalidated_records,
            *[("workspace_delivery", item["id"], item) for item in deliveries],
            *self._due_records(add=deliveries),
        ]
        committed = self.store.commit_operation(
            operation_id, digest, outcome, records
        )
        self._workspace_changed(workspace_id)
        return committed

    def remove_workspace_data(
        self, workspace_id: Any, confirmation: Any, operation_id: Any
    ) -> dict[str, Any]:
        payload = {"workspace_id": workspace_id, "confirmation": confirmation}
        operation_id, digest, replay = self._workspace_operation(
            "remove_workspace_data", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if workspace.get("state") not in {"left", "removed", "closed"}:
            raise ValidationError("Leave or close the workspace before removing its data")
        if confirmation != workspace_id:
            raise ValidationError("Workspace removal confirmation does not match")
        scoped_kinds = {
            "workspace",
            "workspace_manifest",
            "workspace_manifest_epoch",
            "workspace_invitation",
            "workspace_join_request",
            "workspace_display_name_request",
            "workspace_channel",
            "workspace_channel_control",
            "workspace_channel_version",
            "workspace_channel_transfer",
            "workspace_channel_discovery",
            "workspace_event",
            "workspace_message_state",
            "workspace_message_hidden",
            "workspace_delivery",
            "workspace_pending_event",
            "workspace_pending_control",
            "workspace_conversation_index",
            "workspace_subscription",
            "workspace_read_state",
            "workspace_stream_coverage",
            "workspace_draft",
        }
        deletions: list[tuple[str, str]] = []
        delivery_ids: list[str] = []
        for kind in scoped_kinds:
            for record_id, value in self.store.items(kind):
                if value.get("workspace_id") == workspace_id or (
                    kind == "workspace" and value.get("id") == workspace_id
                ):
                    deletions.append((kind, record_id))
                    if kind == "workspace_delivery" and isinstance(value.get("id"), str):
                        delivery_ids.append(value["id"])
        operation_redactions: list[tuple[str, str, dict[str, Any]]] = []
        for record_id, operation in self.store.items("workspace_operation"):
            stored_outcome = operation.get("outcome")
            if not isinstance(stored_outcome, dict):
                continue
            nested_workspace = stored_outcome.get("workspace")
            scoped = stored_outcome.get("workspace_id") == workspace_id or (
                isinstance(nested_workspace, dict)
                and nested_workspace.get("id") == workspace_id
            )
            scoped = scoped or (
                stored_outcome.get("id") == workspace_id
                and "manifest_hash" in stored_outcome
            )
            if scoped:
                operation["outcome"] = {
                    "workspace_id": workspace_id,
                    "removed": True,
                }
                operation_redactions.append(
                    ("workspace_operation", record_id, operation)
                )
        due_records = self._due_records(remove=delivery_ids)
        outcome = {"workspace_id": workspace_id, "removed": True}
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [*due_records, *operation_redactions],
            deletions,
            redact_command_cache=True,
        )
        network = getattr(self, "network", None)
        if network is not None and delivery_ids:
            network.cancel_outbound(set(delivery_ids))
        self._workspace_changed(workspace_id, resource_kind="local_removal")
        return committed

    def _attempt_workspace_delivery(self, delivery_id: str) -> None:
        delivery = self.store.get("workspace_delivery", delivery_id)
        if delivery is None or delivery.get("state") in FINAL_DELIVERY_STATES:
            return
        now = time.time()
        if float(delivery.get("expires_at", 0)) <= now:
            delivery["state"] = DeliveryState.EXPIRED.value
            delivery["expired_at"] = now
            records = [
                ("workspace_delivery", delivery_id, delivery),
                *self._due_records(remove=[delivery_id]),
            ]
            message = (
                self.store.get(
                    "workspace_message_state",
                    self._workspace_message_record_id(delivery["event_id"]),
                )
                if isinstance(delivery.get("event_id"), str)
                else None
            )
            if message is not None:
                devices = dict(message.get("delivery_devices", {}))
                existing = dict(
                    devices.get(delivery["recipient_device_id"], {})
                )
                existing.update(
                    {
                        "member_id": delivery["recipient_member_id"],
                        "member_display_name": delivery.get(
                            "recipient_display_name", "Member"
                        ),
                        "state": DeliveryState.EXPIRED.value,
                    }
                )
                devices[delivery["recipient_device_id"]] = existing
                message["delivery_devices"] = devices
                message["delivery_summary"] = (
                    self._workspace_delivery_summary_from_devices(devices)
                )
                records.append(
                    (
                        "workspace_message_state",
                        self._workspace_message_record_id(delivery["event_id"]),
                        message,
                    )
                )
            self.store.put_many(records)
            self._workspace_changed(
                delivery["workspace_id"],
                conversation_id=(
                    message.get("conversation_id") if message is not None else None
                ),
                resource_kind="delivery",
            )
            return
        if float(delivery.get("next_attempt_at", 0)) > now:
            return
        network = getattr(self, "network", None)
        if network is None:
            return
        destination = bytes.fromhex(delivery["recipient_destination"])
        public_identity = _unb64(delivery["recipient_public_identity"])
        try:
            network.remember_contact(public_identity, destination)
        except Exception:
            delivery["state"] = DeliveryState.FAILED.value
            delivery["failure_code"] = "identity_binding_invalid"
            self.store.put_many(
                [
                    ("workspace_delivery", delivery_id, delivery),
                    *self._due_records(remove=[delivery_id]),
                ]
            )
            return
        hints = delivery.get("recipient_hints", [])
        if hints and any(hint not in self.settings.tcp_clients for hint in hints):
            self._apply_contact_hints({"connection_hints": hints})
        if not network.recipient_ready(destination):
            delivery["state"] = DeliveryState.WAITING_FOR_KEYS.value
            delivery["next_attempt_at"] = now + WORKSPACE_RETRY_BASE_SECONDS
            self.store.put_many(
                [
                    ("workspace_delivery", delivery_id, delivery),
                    *self._due_records(add=[delivery]),
                ]
            )
            network.request_path(destination)
            return
        attempts = int(delivery.get("attempt_count", 0)) + 1
        delay = min(
            WORKSPACE_RETRY_MAX_SECONDS,
            WORKSPACE_RETRY_BASE_SECONDS * (2 ** min(attempts - 1, 5)),
        )
        delivery["attempt_count"] = attempts
        delivery["last_attempt_at"] = now
        delivery["next_attempt_at"] = now + delay
        delivery["state"] = DeliveryState.SENDING.value
        self.store.put_many(
            [
                ("workspace_delivery", delivery_id, delivery),
                *self._due_records(add=[delivery]),
            ]
        )
        fields = build_workspace_fields(
            kind=delivery["kind"],
            logical_id=delivery["id"],
            workspace_id=delivery["workspace_id"],
            expires_at=int(delivery["expires_at"]),
            document=delivery["document"],
        )
        try:
            native_id = network.send_with_fields(
                logical_id=delivery_id,
                recipient_public_key=public_identity,
                recipient_destination=destination,
                text="",
                fields=fields,
                propagated=bool(self.settings.approved_propagation_nodes)
                and not network.path_known(destination),
            )
            current = self.store.get("workspace_delivery", delivery_id)
            if current is not None and current.get("state") not in FINAL_DELIVERY_STATES:
                current["native_message_id"] = native_id
                self.store.put("workspace_delivery", delivery_id, current)
        except MeshChatError as exc:
            current = self.store.get("workspace_delivery", delivery_id)
            if current is None or current.get("state") in FINAL_DELIVERY_STATES:
                return
            current["state"] = (
                DeliveryState.WAITING_FOR_KEYS.value
                if exc.code == "recipient_keys_unavailable"
                else DeliveryState.QUEUED.value
            )
            current["failure_code"] = "transport_unavailable"
            self.store.put_many(
                [
                    ("workspace_delivery", delivery_id, current),
                    *self._due_records(add=[current]),
                ]
            )
        except Exception:
            current = self.store.get("workspace_delivery", delivery_id)
            if current is None or current.get("state") in FINAL_DELIVERY_STATES:
                return
            current["state"] = DeliveryState.QUEUED.value
            current["failure_code"] = "transport_error"
            self.store.put_many(
                [
                    ("workspace_delivery", delivery_id, current),
                    *self._due_records(add=[current]),
                ]
            )

    def _expire_workspace_invitations(self) -> None:
        now = time.time()
        records: list[tuple[str, str, dict[str, Any]]] = []
        changed_workspaces: set[str] = set()
        for record_id, stored in self.store.items("workspace_invitation"):
            if (
                stored.get("state") != "active"
                or float(stored.get("expires_at", 0)) > now
            ):
                continue
            invitation = dict(stored)
            invitation["state"] = "expired"
            invitation["updated_at"] = now
            records.append(("workspace_invitation", record_id, invitation))
            if isinstance(invitation.get("workspace_id"), str):
                changed_workspaces.add(invitation["workspace_id"])
        if not records:
            return
        self.store.put_many(records)
        for workspace_id in changed_workspaces:
            self._workspace_changed(workspace_id, resource_kind="invitation")

    def _retry_workspace_outbox(self) -> None:
        self._expire_workspace_invitations()
        now = time.time()
        candidates: list[tuple[float, int, str]] = []
        for shard in range(DUE_SHARDS):
            record = self.store.get(
                "workspace_due_work_index", self._due_record_id(shard)
            )
            if record is None:
                continue
            entries = record.get("entries", {})
            if not isinstance(entries, dict):
                continue
            for delivery_id, due_at in entries.items():
                if isinstance(delivery_id, str) and isinstance(due_at, (int, float)) and due_at <= now:
                    delivery = self.store.get("workspace_delivery", delivery_id)
                    priority = int(delivery.get("priority", 2)) if delivery else 2
                    candidates.append((float(due_at), priority, delivery_id))
        for _due, _priority, delivery_id in sorted(
            candidates, key=lambda item: (item[1], item[0], item[2])
        )[:16]:
            self._attempt_workspace_delivery(delivery_id)

    def _on_workspace_native_status(
        self, logical_id: str, state: DeliveryState, native_id: str | None
    ) -> bool:
        delivery = self.store.get("workspace_delivery", logical_id)
        if delivery is None:
            return False
        if delivery.get("state") in FINAL_DELIVERY_STATES:
            return True
        if (
            native_id
            and delivery.get("native_message_id")
            and delivery["native_message_id"] != native_id
        ):
            return True
        if state in {DeliveryState.RECEIVED_BY_ENDPOINT, DeliveryState.DELIVERED}:
            delivery["state"] = DeliveryState.RECEIVED_BY_ENDPOINT.value
            delivery["reached_at"] = time.time()
            records = [
                ("workspace_delivery", logical_id, delivery),
                *self._due_records(remove=[logical_id]),
            ]
        elif state in {
            DeliveryState.EXPIRED,
            DeliveryState.FAILED,
            DeliveryState.CANCELLED,
        }:
            delivery["state"] = state.value
            records = [
                ("workspace_delivery", logical_id, delivery),
                *self._due_records(remove=[logical_id]),
            ]
        else:
            delivery["state"] = state.value
            if native_id:
                delivery["native_message_id"] = native_id
            records = [
                ("workspace_delivery", logical_id, delivery),
                *self._due_records(add=[delivery]),
            ]
        if native_id:
            delivery["native_message_id"] = native_id
            records[0] = ("workspace_delivery", logical_id, delivery)
        conversation_id = None
        event_id = delivery.get("event_id")
        if isinstance(event_id, str):
            message_record_id = self._workspace_message_record_id(event_id)
            message = self.store.get("workspace_message_state", message_record_id)
            if message is not None:
                conversation_id = message.get("conversation_id")
                devices = dict(message.get("delivery_devices", {}))
                existing = dict(
                    devices.get(delivery["recipient_device_id"], {})
                )
                existing.update(
                    {
                        "member_id": delivery["recipient_member_id"],
                        "member_display_name": delivery.get(
                            "recipient_display_name", "Member"
                        ),
                        "state": delivery["state"],
                    }
                )
                devices[delivery["recipient_device_id"]] = existing
                message["delivery_devices"] = devices
                message["delivery_summary"] = (
                    self._workspace_delivery_summary_from_devices(devices)
                )
                records.append(
                    ("workspace_message_state", message_record_id, message)
                )
        self.store.put_many(records)
        self._workspace_changed(
            delivery["workspace_id"],
            conversation_id=conversation_id,
            resource_kind="delivery",
        )
        return True

    def _receive_workspace_payload(
        self, native: Any, wire: WorkspaceWirePayload
    ) -> None:
        if wire.kind == "workspace_join":
            self._receive_workspace_join(wire, getattr(native, "source_hash", None))
            return
        if not self._workspace_source_is_active(
            wire.workspace_id, getattr(native, "source_hash", None)
        ):
            return
        if wire.kind == "workspace_manifest_root":
            self._receive_workspace_manifest(wire)
        elif wire.kind == "workspace_channel_record":
            self._receive_workspace_channel(wire)
        elif wire.kind == "workspace_channel_manifest":
            self._receive_workspace_private_channel(wire)
        elif wire.kind == "workspace_channel_leave_request":
            self._receive_workspace_channel_leave_request(wire)
        elif wire.kind == "workspace_channel_transfer_offer":
            self._receive_workspace_channel_transfer_offer(wire)
        elif wire.kind in {
            "workspace_channel_transfer",
            "workspace_channel_recovery",
        }:
            self._receive_workspace_channel_head_transition(wire)
        elif wire.kind == "workspace_channel_summary":
            self._receive_workspace_channel_summary(wire)
        elif wire.kind == "workspace_channel_fetch":
            self._receive_workspace_channel_fetch(wire)
        elif wire.kind == "workspace_event":
            self._accept_workspace_event(wire)
        elif wire.kind == "workspace_leave_request":
            self._receive_workspace_leave_request(wire)
        elif wire.kind == "workspace_display_name_request":
            self._receive_workspace_display_name_request(wire)
        elif wire.kind == "workspace_display_name_decision":
            self._receive_workspace_display_name_decision(wire)

    def workspace_snapshot(self) -> dict[str, Any]:
        now = time.time()
        invitations: list[dict[str, Any]] = []
        for item in self.store.list("workspace_invitation"):
            if (
                item.get("state") == "active"
                and float(item.get("expires_at", 0)) > now
            ):
                invitations.append(
                    {
                        key: value
                        for key, value in item.items()
                        if key not in {"document", "join_document", "nonce"}
                    }
                )
        workspaces = [
            self._public_workspace(item) for item in self.store.list("workspace")
        ]
        workspaces.sort(key=lambda item: (item["created_at"], item["id"]))
        workspace_local_members = {
            item["id"]: item.get("local_member_id")
            for item in self.store.list("workspace")
            if isinstance(item.get("id"), str)
        }
        stored_channels = [
            item
            for item in self.store.list("workspace_channel")
            if item.get("visibility") != "private"
            or workspace_local_members.get(item.get("workspace_id"))
            in item.get("member_ids", [])
            or item.get("state") in {"leaving", "left", "removed"}
        ]
        name_counts: dict[tuple[str, str], int] = defaultdict(int)
        for item in stored_channels:
            name_counts[
                (
                    str(item.get("workspace_id", "")),
                    str(
                        item.get("name_key")
                        or channel_name_key(str(item.get("name", "")))
                    ),
                )
            ] += 1
        channels = [
            self._public_workspace_channel(
                item,
                duplicate_name=name_counts[
                    (
                        str(item.get("workspace_id", "")),
                        str(
                            item.get("name_key")
                            or channel_name_key(str(item.get("name", "")))
                        ),
                    )
                ]
                > 1,
            )
            for item in stored_channels
        ]
        channels.sort(
            key=lambda item: (
                item["workspace_id"],
                item.get("name_key", ""),
                item["id"],
            )
        )
        channel_transfers = [
            {key: value for key, value in item.items() if key != "document"}
            for item in self.store.list("workspace_channel_transfer")
            if item.get("state") == "offered"
            and float(item.get("expires_at", 0)) > now
            and any(
                channel.get("id") == item.get("channel_id")
                for channel in stored_channels
            )
        ]
        requests = [
            {
                key: value
                for key, value in item.items()
                if key not in {"document", "public_identity"}
            }
            for item in self.store.list("workspace_join_request")
            if item.get("state") == "pending"
        ]
        name_requests = [
            {
                key: value
                for key, value in item.items()
                if key != "document"
            }
            for item in self.store.list("workspace_display_name_request")
            if item.get("state") == "pending"
        ]
        invitations.sort(key=lambda item: (item["created_at"], item["id"]))
        requests.sort(key=lambda item: (item.get("created_at", 0), item["id"]))
        name_requests.sort(
            key=lambda item: (item.get("created_at", 0), item["id"])
        )
        return {
            "workspaces": workspaces,
            "workspace_channels": channels,
            "workspace_channel_transfers": channel_transfers,
            "workspace_join_requests": requests,
            "workspace_display_name_requests": name_requests,
            "workspace_invitations": invitations,
            "workspace_drafts": self.store.list("workspace_draft"),
        }
