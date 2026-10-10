from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import unicodedata
import uuid
from collections import defaultdict
from typing import Any, Callable, Iterable

import RNS

from .errors import (
    ContactNotApproved,
    HistoryPruned,
    MeshChatError,
    StaleCursor,
    ValidationError,
)
from .invitations import canonical_bytes
from .models import (
    DeliveryState,
    WorkspaceChannelCreationPolicy,
    WorkspaceInvitationPolicy,
    WorkspacePostingPolicy,
    WorkspaceRole,
)
from .workspace_protocol import (
    DEFAULT_INVITATION_LIFETIME_SECONDS,
    MAX_ACTIVE_MEMBERS,
    MAX_INVITATION_LIFETIME_SECONDS,
    MAX_ADMIN_REQUEST_LIFETIME_SECONDS,
    MAX_HISTORY_CHECKPOINTS,
    MAX_HISTORY_EVENTS,
    MAX_HISTORY_RANGES,
    MAX_HISTORY_REQUEST_LIFETIME_SECONDS,
    MAX_HISTORY_RESPONSE_BYTES,
    MAX_HISTORY_STREAMS,
    MAX_MESSAGE_TEXT_BYTES,
    MAX_PUBLIC_CHANNELS,
    MAX_CHANNEL_FETCH_CONTROLS,
    MAX_CHANNEL_SUMMARY_ENTRIES,
    MAX_RETAINED_PUBLIC_CHANNELS,
    VerifiedWorkspaceChannel,
    VerifiedWorkspaceAdminRequest,
    VerifiedWorkspaceEvent,
    VerifiedWorkspaceHistoryRequest,
    VerifiedWorkspaceManifest,
    WorkspaceManifestMemberInput,
    active_members,
    channel_name_key,
    create_workspace_channel_fetch,
    create_workspace_admin_decision,
    create_workspace_admin_request,
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
    create_workspace_event_checkpoint,
    create_workspace_history_request,
    create_workspace_history_response,
    create_workspace_mutation_event,
    create_workspace_genesis,
    create_workspace_invitation,
    create_workspace_join,
    create_workspace_leave_request,
    create_workspace_manifest,
    find_device,
    find_member,
    verify_workspace_channel_record,
    verify_workspace_admin_decision,
    verify_workspace_admin_request,
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
    verify_workspace_event_checkpoint,
    verify_workspace_history_request,
    verify_workspace_history_response,
    verify_workspace_genesis,
    verify_workspace_invitation,
    verify_workspace_join,
    verify_workspace_leave_request,
    verify_workspace_manifest,
    verify_workspace_manifest_transition,
    workspace_direct_conversation_id,
    workspace_invitation_formats,
    workspace_document_digest,
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
THREAD_ACTIVITY_MAX_ROOTS = 1024
RETENTION_PRUNE_BATCH_DEFAULT = 500
RETENTION_PRUNE_BATCH_MAX = 1000
RETENTION_INDEX_PAGE_ENTRIES = 100
SEARCH_PAGE_DEFAULT = 25
SEARCH_PAGE_MAX = 50
SEARCH_QUERY_MAX_CHARS = 256
SEARCH_QUERY_MAX_BYTES = 1024
SEARCH_QUERY_MAX_TOKENS = 8
SEARCH_TOKEN_MIN_CHARS = 2
SEARCH_TOKEN_MAX_CHARS = 64
SEARCH_DOCUMENT_MAX_TOKENS = 512
SEARCH_TOKEN_PAGE_ENTRIES = 100
SEARCH_SHARD_PAGE_MAX = 8
SEARCH_CANDIDATE_MAX = 256
SEARCH_REBUILD_BATCH = 128
SEARCH_INDEX_REFERENCE_MAX = 2_000_000
MAX_PENDING_EVENTS = 256
MAX_PENDING_EVENTS_PER_SENDER = 64
MAX_PENDING_EVENT_BYTES = 16 * 1024 * 1024
MAX_PENDING_CONTROLS = 32
MAX_FUTURE_MANIFESTS = 8
MAX_PENDING_JOINS = 32
MAX_PENDING_JOINS_PER_SOURCE = 4
MAX_PENDING_CHANNEL_TRANSFERS = 32
MAX_PENDING_ADMIN_REQUESTS_PER_WORKSPACE = 128
MAX_ADMIN_REQUESTS_PER_PROFILE = 512
MAX_ADMIN_REQUESTS_PER_SOURCE = 32
MAX_ADMIN_REQUEST_PAGE = 100
DEFAULT_ADMIN_REQUEST_PAGE = 50
MAX_INERT_ADMIN_DECISIONS = 64
ADMIN_REPLAY_RETENTION_SECONDS = 90 * 24 * 60 * 60
MAX_HISTORY_JOBS_PER_WORKSPACE = 2
MAX_HISTORY_JOBS_PER_PROFILE = 4
MAX_HISTORY_SEQUENCE_PROBES = 256
MAX_HISTORY_GAP_PAGE = 64
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


def normalize_workspace_search_text(value: str) -> str:
    """Return the frozen Increment 10 search comparison form.

    NFKC is applied before Unicode default case folding, followed by NFC so
    canonically equivalent input always produces the same keyed token IDs.
    """

    if not isinstance(value, str):
        raise ValidationError("Workspace search text is invalid")
    return unicodedata.normalize(
        "NFC", unicodedata.normalize("NFKC", value).casefold()
    )


def tokenize_workspace_search_text(value: str) -> tuple[str, ...]:
    """Split normalized text into unique Unicode letter/number tokens.

    Punctuation, symbols, separators, and controls are boundaries. Combining
    marks stay attached to a preceding letter or number. Tokens shorter than
    two characters or longer than 64 characters are deliberately not indexed.
    Duplicate tokens collapse in first-occurrence order.
    """

    normalized = normalize_workspace_search_text(value)
    tokens: list[str] = []
    current: list[str] = []

    def finish() -> None:
        if not current:
            return
        token = "".join(current)
        current.clear()
        if SEARCH_TOKEN_MIN_CHARS <= len(token) <= SEARCH_TOKEN_MAX_CHARS:
            tokens.append(token)

    for character in normalized:
        category = unicodedata.category(character)
        if category[0] in {"L", "N"} or (category[0] == "M" and current):
            current.append(character)
        else:
            finish()
    finish()
    return tuple(dict.fromkeys(tokens))


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
        workspace = self.store.get(
            "workspace", self._workspace_record_id(workspace_id)
        )
        if workspace is not None:
            unread = self._workspace_mention_unread_count(workspace)
            if int(workspace.get("mention_unread_count", -1)) != unread:
                workspace["mention_unread_count"] = unread
            thread_unread = self._workspace_thread_unread_count(workspace)
            if int(workspace.get("thread_unread_count", -1)) != thread_unread:
                workspace["thread_unread_count"] = thread_unread
            self.store.put(
                "workspace", self._workspace_record_id(workspace_id), workspace
            )
            catalog = self.store.get(
                "workspace_search_catalog",
                self._workspace_search_catalog_id(workspace_id),
            ) or {}
            channel_ids = {
                item
                for item in catalog.get("channel_ids", ())
                if isinstance(item, str)
            }
            if isinstance(conversation_id, str):
                channel_ids.add(conversation_id)
            search_channels = [
                channel
                for channel_id in sorted(channel_ids)
                if (
                    channel := self.store.get(
                        "workspace_channel",
                        self._workspace_channel_record_id(channel_id),
                    )
                )
                is not None
            ]
            self._sync_workspace_search_directory(workspace, search_channels)
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

    def _workspace_direct_record_id(self, conversation_id: str) -> str:
        return self.store.opaque_id("workspace-direct", conversation_id)

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

    def _workspace_mention_index_id(self, workspace_id: str) -> str:
        return self.store.opaque_id("workspace-mention-index", workspace_id)

    def _workspace_mention_page_id(self, workspace_id: str, seed: str) -> str:
        return self.store.opaque_id("workspace-mention-page", workspace_id, seed)

    def _workspace_mention_read_id(self, workspace_id: str) -> str:
        return self.store.opaque_id("workspace-read-state", workspace_id, "mentions")

    def _workspace_revision_index_id(
        self, workspace_id: str, target_event_id: str
    ) -> str:
        return self.store.opaque_id(
            "workspace-revision-index", workspace_id, target_event_id
        )

    def _workspace_revision_page_id(
        self, workspace_id: str, target_event_id: str, seed: str
    ) -> str:
        return self.store.opaque_id(
            "workspace-revision-page", workspace_id, target_event_id, seed
        )

    def _workspace_tombstone_index_id(
        self, workspace_id: str, conversation_id: str
    ) -> str:
        return self.store.opaque_id(
            "workspace-tombstone-index", workspace_id, conversation_id
        )

    def _workspace_tombstone_page_id(
        self, workspace_id: str, conversation_id: str, seed: str
    ) -> str:
        return self.store.opaque_id(
            "workspace-tombstone-page", workspace_id, conversation_id, seed
        )

    def _workspace_retention_index_id(self, workspace_id: str) -> str:
        return self.store.opaque_id("workspace-retention-index", workspace_id)

    def _workspace_retention_page_id(self, workspace_id: str, seed: str) -> str:
        return self.store.opaque_id(
            "workspace-retention-page", workspace_id, seed
        )

    def _workspace_retention_state_id(self, workspace_id: str) -> str:
        return self.store.opaque_id("workspace-retention-state", workspace_id)

    def _workspace_search_state_id(self, workspace_id: str) -> str:
        return self.store.opaque_id("workspace-search-state", workspace_id)

    def _workspace_search_catalog_id(self, workspace_id: str) -> str:
        return self.store.opaque_id("workspace-search-catalog", workspace_id)

    def _workspace_search_document_id(
        self, workspace_id: str, category: str, entity_id: str
    ) -> str:
        return self.store.opaque_id(
            "workspace-search-document", workspace_id, category, entity_id
        )

    def _workspace_search_token_id(self, workspace_id: str, token: str) -> str:
        return self.store.opaque_id("workspace-search-token", workspace_id, token)

    def _workspace_search_token_page_id(
        self, workspace_id: str, token_id: str, seed: str
    ) -> str:
        return self.store.opaque_id(
            "workspace-search-token-page", workspace_id, token_id, seed
        )

    def _workspace_search_base_state(self, workspace: dict[str, Any]) -> dict[str, Any]:
        workspace_id = str(workspace["id"])
        retention = self.store.get(
            "workspace_retention_index",
            self._workspace_retention_index_id(workspace_id),
        ) or {}
        retained_count = int(retention.get("count", 0))
        return {
            "workspace_id": workspace_id,
            "schema": 1,
            "status": "rebuilding" if retained_count else "ready",
            "search_generation": 1,
            "indexed_events": 0,
            "target_events": retained_count,
            "rebuild_page_id": retention.get("head_page"),
            "rebuild_offset": 0,
            "index_references": 0,
            "truncated_documents": 0,
            "growth_limited": False,
            "pruned_count": 0,
            "updated_at": time.time(),
        }

    def _workspace_search_staged_get(
        self,
        staged: dict[tuple[str, str], dict[str, Any]],
        kind: str,
        record_id: str,
    ) -> dict[str, Any] | None:
        value = staged.get((kind, record_id))
        if value is not None:
            return value
        stored = self.store.get(kind, record_id)
        return None if stored is None else dict(stored)

    def _workspace_search_document_records(
        self,
        workspace: dict[str, Any],
        *,
        category: str,
        entity_id: str,
        text: str,
        active: bool,
        sort_at: float = 0,
        conversation_id: str | None = None,
        thread_root_id: str | None = None,
        staged: dict[tuple[str, str], dict[str, Any]] | None = None,
    ) -> list[tuple[str, str, dict[str, Any]]]:
        """Replace one sealed search document and its exact token references.

        The document remembers the opaque page used for every token, so edits,
        deletion, hide, and pruning remove references without a token-page scan.
        """

        if category not in {"message", "thread", "person", "channel"}:
            raise ValidationError("Workspace search category is invalid")
        workspace_id = str(workspace["id"])
        own_staged = staged is None
        changed = staged if staged is not None else {}
        state_id = self._workspace_search_state_id(workspace_id)
        state = self._workspace_search_staged_get(
            changed, "workspace_search_state", state_id
        ) or self._workspace_search_base_state(workspace)
        document_id = self._workspace_search_document_id(
            workspace_id, category, entity_id
        )
        existing = self._workspace_search_staged_get(
            changed, "workspace_search_document", document_id
        )
        normalized = normalize_workspace_search_text(text)
        all_tokens = list(tokenize_workspace_search_text(text))
        truncated = len(all_tokens) > SEARCH_DOCUMENT_MAX_TOKENS
        tokens = all_tokens[:SEARCH_DOCUMENT_MAX_TOKENS] if active else []
        token_ids = [
            self._workspace_search_token_id(workspace_id, token) for token in tokens
        ]
        signature = hashlib.sha256(
            canonical_bytes(
                {
                    "active": bool(active),
                    "category": category,
                    "content": normalized,
                    "conversation_id": conversation_id,
                    "entity_id": entity_id,
                    "sort_at": float(sort_at),
                    "thread_root_id": thread_root_id,
                    "token_ids": token_ids,
                    "truncated": truncated,
                }
            )
        ).hexdigest()
        if existing is not None and existing.get("signature") == signature:
            return []

        old_pages = existing.get("token_pages", {}) if existing else {}
        if isinstance(old_pages, dict):
            for token_id, page_id in old_pages.items():
                if not isinstance(token_id, str) or not isinstance(page_id, str):
                    continue
                index = self._workspace_search_staged_get(
                    changed, "workspace_search_index", token_id
                )
                page = self._workspace_search_staged_get(
                    changed, "workspace_search_index", page_id
                )
                if index is None or page is None:
                    continue
                entries = list(page.get("entries", ()))
                kept = [
                    item for item in entries if item.get("document_id") != document_id
                ]
                if len(kept) == len(entries):
                    continue
                page["entries"] = kept
                index["count"] = max(0, int(index.get("count", 0)) - 1)
                state["index_references"] = max(
                    0, int(state.get("index_references", 0)) - 1
                )
                changed[("workspace_search_index", page_id)] = page
                changed[("workspace_search_index", token_id)] = index

        generation = int(existing.get("generation", 0) if existing else 0) + 1
        token_pages: dict[str, str] = {}
        available = max(
            0,
            SEARCH_INDEX_REFERENCE_MAX - int(state.get("index_references", 0)),
        )
        if len(token_ids) > available:
            token_ids = token_ids[:available]
            state["growth_limited"] = True
            truncated = True
        for token_id in token_ids:
            index = self._workspace_search_staged_get(
                changed, "workspace_search_index", token_id
            ) or {
                "workspace_id": workspace_id,
                "head_page": None,
                "count": 0,
                "high_water": 0,
            }
            page_id = index.get("head_page")
            page = (
                self._workspace_search_staged_get(
                    changed, "workspace_search_index", page_id
                )
                if isinstance(page_id, str)
                else None
            )
            if page is None or len(page.get("entries", ())) >= SEARCH_TOKEN_PAGE_ENTRIES:
                page_id = self._workspace_search_token_page_id(
                    workspace_id, token_id, f"{document_id}:{generation}"
                )
                page = {
                    "workspace_id": workspace_id,
                    "previous_page": index.get("head_page"),
                    "entries": [],
                }
                index["head_page"] = page_id
            page["entries"] = [
                *page.get("entries", ()),
                {
                    "document_id": document_id,
                    "document_generation": generation,
                    "sort_at": float(sort_at),
                },
            ]
            index["count"] = int(index.get("count", 0)) + 1
            index["high_water"] = int(index.get("high_water", 0)) + 1
            state["index_references"] = int(state.get("index_references", 0)) + 1
            token_pages[token_id] = str(page_id)
            changed[("workspace_search_index", token_id)] = index
            changed[("workspace_search_index", str(page_id))] = page

        if existing is not None and bool(existing.get("truncated")) != truncated:
            state["truncated_documents"] = max(
                0,
                int(state.get("truncated_documents", 0))
                + (1 if truncated else -1),
            )
        elif existing is None and truncated:
            state["truncated_documents"] = int(
                state.get("truncated_documents", 0)
            ) + 1
        document = {
            "workspace_id": workspace_id,
            "category": category,
            "entity_id": entity_id,
            "active": bool(active),
            "generation": generation,
            "signature": signature,
            "token_ids": token_ids,
            "token_pages": token_pages,
            "sort_at": float(sort_at),
            "conversation_id": conversation_id,
            "thread_root_id": thread_root_id,
            "truncated": truncated,
        }
        state["search_generation"] = int(state.get("search_generation", 0)) + 1
        state["updated_at"] = time.time()
        changed[("workspace_search_document", document_id)] = document
        changed[("workspace_search_state", state_id)] = state
        if not own_staged:
            return []
        return [(kind, record_id, value) for (kind, record_id), value in changed.items()]

    def _workspace_search_directory_records(
        self,
        workspace: dict[str, Any],
        channels: Iterable[dict[str, Any]],
    ) -> list[tuple[str, str, dict[str, Any]]]:
        workspace_id = str(workspace["id"])
        checked_channels = [
            item for item in channels if item.get("workspace_id") == workspace_id
        ]
        local_member_id = str(workspace.get("local_member_id", ""))
        former_archive = workspace.get("state") in {"left", "removed", "closed", "forked"}
        people = [
            item
            for item in workspace.get("members", ())
            if isinstance(item.get("id"), str)
        ]
        visible_channels = [
            item
            for item in checked_channels
            if item.get("state") in {"active", "archived", "leaving", "left"}
            and (
                item.get("visibility") == "public"
                or local_member_id in item.get("member_ids", ())
                or former_archive
            )
        ]
        signature = hashlib.sha256(
            canonical_bytes(
                {
                    "authorization_generation": int(
                        workspace.get("authorization_generation", 1)
                    ),
                    "channels": [
                        {
                            "id": item.get("id"),
                            "members": item.get("member_ids", []),
                            "name": item.get("name"),
                            "state": item.get("state"),
                            "topic": item.get("topic"),
                            "visibility": item.get("visibility"),
                        }
                        for item in sorted(visible_channels, key=lambda value: str(value.get("id")))
                    ],
                    "people": [
                        {
                            "display_name": item.get("display_name"),
                            "id": item.get("id"),
                            "status": item.get("status"),
                        }
                        for item in sorted(people, key=lambda value: str(value.get("id")))
                    ],
                }
            )
        ).hexdigest()
        catalog_id = self._workspace_search_catalog_id(workspace_id)
        existing = self.store.get("workspace_search_catalog", catalog_id)
        if existing is not None and existing.get("signature") == signature:
            return []
        staged: dict[tuple[str, str], dict[str, Any]] = {}
        old_people = set(existing.get("member_ids", ())) if existing else set()
        old_channels = set(existing.get("channel_ids", ())) if existing else set()
        new_people = {str(item["id"]) for item in people}
        new_channels = {str(item["id"]) for item in visible_channels}
        for member_id in sorted(old_people - new_people):
            self._workspace_search_document_records(
                workspace,
                category="person",
                entity_id=member_id,
                text="",
                active=False,
                staged=staged,
            )
        for channel_id in sorted(old_channels - new_channels):
            self._workspace_search_document_records(
                workspace,
                category="channel",
                entity_id=channel_id,
                text="",
                active=False,
                staged=staged,
            )
        for member in people:
            self._workspace_search_document_records(
                workspace,
                category="person",
                entity_id=str(member["id"]),
                text=str(member.get("display_name", "")),
                active=member.get("status") == "active",
                staged=staged,
            )
        for channel in visible_channels:
            self._workspace_search_document_records(
                workspace,
                category="channel",
                entity_id=str(channel["id"]),
                text=f"{channel.get('name', '')} {channel.get('topic', '')}",
                active=True,
                sort_at=float(channel.get("updated_at", channel.get("created_at", 0))),
                conversation_id=str(channel["id"]),
                staged=staged,
            )
        staged[("workspace_search_catalog", catalog_id)] = {
            "workspace_id": workspace_id,
            "signature": signature,
            "member_ids": sorted(new_people),
            "channel_ids": sorted(new_channels),
            "updated_at": time.time(),
        }
        return [(kind, record_id, value) for (kind, record_id), value in staged.items()]

    def _sync_workspace_search_directory(
        self, workspace: dict[str, Any], channels: Iterable[dict[str, Any]]
    ) -> None:
        records = self._workspace_search_directory_records(workspace, channels)
        if records:
            self.store.put_many(records)

    def _workspace_event_tombstone_id(self, workspace_id: str, event_id: str) -> str:
        return self.store.opaque_id(
            "workspace-event-tombstone", workspace_id, event_id
        )

    def _workspace_event_id_is_retired(
        self, workspace_id: str, event_id: str
    ) -> bool:
        return self.store.get(
            "workspace_event_tombstone",
            self._workspace_event_tombstone_id(workspace_id, event_id),
        ) is not None

    def _workspace_thread_record_id(self, workspace_id: str, root_event_id: str) -> str:
        return self.store.opaque_id("workspace-thread", workspace_id, root_event_id)

    def _workspace_thread_index_id(self, workspace_id: str, root_event_id: str) -> str:
        return self.store.opaque_id("workspace-thread-index", workspace_id, root_event_id)

    def _workspace_thread_page_id(
        self, workspace_id: str, root_event_id: str, seed: str
    ) -> str:
        return self.store.opaque_id(
            "workspace-thread-page", workspace_id, root_event_id, seed
        )

    def _workspace_thread_activity_id(self, workspace_id: str) -> str:
        return self.store.opaque_id("workspace-thread-activity", workspace_id)

    def _workspace_thread_read_id(self, workspace_id: str, root_event_id: str) -> str:
        return self.store.opaque_id(
            "workspace-read-state", workspace_id, "thread", root_event_id
        )

    def _workspace_notification_preference_id(
        self, workspace_id: str, conversation_id: str
    ) -> str:
        return self.store.opaque_id(
            "workspace-notification-preference", workspace_id, conversation_id
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

    def _workspace_history_job_id(self, workspace_id: str, conversation_id: str) -> str:
        return self.store.opaque_id(
            "workspace-history-job", workspace_id, conversation_id
        )

    def _workspace_history_request_id(self, request_id: str) -> str:
        return self.store.opaque_id("workspace-history-request", request_id)

    def _workspace_history_replay_id(self, workspace_id: str, replay_key: str) -> str:
        return self.store.opaque_id(
            "workspace-history-replay", workspace_id, replay_key
        )

    def _workspace_history_response_id(self, response_id: str) -> str:
        return self.store.opaque_id("workspace-history-response", response_id)

    def _workspace_history_continuation_id(self, continuation: str) -> str:
        return self.store.opaque_id("workspace-history-continuation", continuation)

    def _workspace_history_scheduler_id(self) -> str:
        return self.store.opaque_id("workspace-history-scheduler", "profile")

    def _workspace_admin_request_id(self, workspace_id: str, request_id: str) -> str:
        return self.store.opaque_id(
            "workspace-admin-request", workspace_id, request_id
        )

    def _workspace_admin_replay_id(self, workspace_id: str, replay_key: str) -> str:
        return self.store.opaque_id(
            "workspace-admin-replay", workspace_id, replay_key
        )

    def _workspace_admin_decision_id(self, workspace_id: str, digest: str) -> str:
        return self.store.opaque_id(
            "workspace-admin-decision", workspace_id, digest
        )

    def _workspace_admin_profile_index_id(self) -> str:
        return self.store.opaque_id("workspace-admin-profile-index", "v1")

    def _workspace_admin_workspace_index_id(self, workspace_id: str) -> str:
        return self.store.opaque_id("workspace-admin-workspace-index", workspace_id)

    def _workspace_admin_aux_index_id(self) -> str:
        return self.store.opaque_id("workspace-admin-aux-index", "v1")

    def _workspace_admin_index(
        self, workspace_id: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        profile_id = self._workspace_admin_profile_index_id()
        workspace_index_id = self._workspace_admin_workspace_index_id(workspace_id)
        profile = self.store.get("workspace_admin_profile_index", profile_id) or {
            "request_ids": [],
        }
        workspace_index = self.store.get(
            "workspace_admin_workspace_index", workspace_index_id
        ) or {
            "workspace_id": workspace_id,
            "request_ids": [],
        }
        return profile, workspace_index

    def _workspace_admin_index_records(
        self,
        workspace_id: str,
        request_id: str,
        *,
        aux: tuple[str, str, float] | None = None,
    ) -> list[tuple[str, str, dict[str, Any]]]:
        profile, workspace_index = self._workspace_admin_index(workspace_id)
        profile_ids = list(profile.get("request_ids", []))
        workspace_ids = list(workspace_index.get("request_ids", []))
        if request_id not in profile_ids:
            profile_ids.append(request_id)
        if request_id not in workspace_ids:
            workspace_ids.append(request_id)
        if len(profile_ids) > MAX_ADMIN_REQUESTS_PER_PROFILE:
            raise ValidationError("The administrative request profile limit is reached")
        records = [
            (
                "workspace_admin_profile_index",
                self._workspace_admin_profile_index_id(),
                {"request_ids": profile_ids},
            ),
            (
                "workspace_admin_workspace_index",
                self._workspace_admin_workspace_index_id(workspace_id),
                {"workspace_id": workspace_id, "request_ids": workspace_ids},
            ),
        ]
        if aux is not None:
            kind, record_id, expires_at = aux
            aux_id = self._workspace_admin_aux_index_id()
            aux_index = self.store.get("workspace_admin_aux_index", aux_id) or {
                "entries": [],
            }
            entries = [
                item for item in aux_index.get("entries", [])
                if item.get("id") != record_id
            ]
            entries.append({
                "kind": kind,
                "id": record_id,
                "workspace_id": workspace_id,
                "expires_at": float(expires_at),
            })
            records.append(("workspace_admin_aux_index", aux_id, {"entries": entries}))
        return records

    def _workspace_admin_records(self, workspace_id: str) -> list[dict[str, Any]]:
        _, workspace_index = self._workspace_admin_index(workspace_id)
        records: list[dict[str, Any]] = []
        for record_id in workspace_index.get("request_ids", []):
            if not isinstance(record_id, str):
                continue
            record = self.store.get("workspace_admin_request", record_id)
            if record is not None and record.get("workspace_id") == workspace_id:
                records.append(record)
        return records

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

    def _require_workspace_direct(
        self, workspace_id: str, conversation_id: str
    ) -> dict[str, Any]:
        direct = self.store.get(
            "workspace_direct", self._workspace_direct_record_id(conversation_id)
        )
        if direct is None or direct.get("workspace_id") != workspace_id:
            raise ValidationError("Workspace direct message does not exist")
        participants = direct.get("participant_member_ids")
        workspace = self._require_workspace(workspace_id)
        if (
            not isinstance(participants, list)
            or workspace.get("local_member_id") not in participants
        ):
            raise ContactNotApproved("Workspace direct message is unavailable")
        return direct

    def _require_workspace_conversation(
        self, workspace_id: str, conversation_id: str
    ) -> tuple[str, dict[str, Any]]:
        channel = self.store.get(
            "workspace_channel", self._workspace_channel_record_id(conversation_id)
        )
        if channel is not None and channel.get("workspace_id") == workspace_id:
            return "channel", channel
        return "direct", self._require_workspace_direct(workspace_id, conversation_id)

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
        previous_retention = workspace.get("retention_days", 90)
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
        if previous_retention != manifest.retention_days:
            workspace["retention_generation"] = int(
                workspace.get("retention_generation", 0)
            ) + 1
            workspace["retention_pruning_state"] = (
                "disabled" if manifest.retention_days is None else "pending"
            )
            workspace["retention_pruning_updated_at"] = time.time()
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
        replacement_role: WorkspaceRole | str | None = None,
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
                    (
                        replacement_role
                        if replacing and replacement_role is not None
                        else member.role
                    ),
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

    def _validate_workspace_mentions(
        self,
        workspace: dict[str, Any],
        conversation_id: str,
        value: Any,
    ) -> tuple[str, ...]:
        if value is None:
            return ()
        if not isinstance(value, list) or len(value) > MAX_ACTIVE_MEMBERS:
            raise ValidationError("Workspace mentions are invalid")
        try:
            checked = [str(uuid.UUID(item)) for item in value]
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValidationError("Workspace mentions are invalid") from exc
        if any(checked_item != item for checked_item, item in zip(checked, value)):
            raise ValidationError("Workspace mentions are invalid")
        mentions = tuple(sorted(set(checked)))
        if len(mentions) != len(value):
            raise ValidationError("Workspace mentions are not canonical")
        manifest = self._workspace_current_manifest(workspace)
        kind, conversation = self._require_workspace_conversation(
            workspace["id"], conversation_id
        )
        if kind == "direct":
            entitled = set(conversation.get("participant_member_ids", ()))
        elif conversation.get("visibility") == "private":
            entitled = set(conversation.get("member_ids", ()))
        else:
            entitled = {
                member.member_id
                for member in active_members(manifest)
            }
        if any(
            member_id not in entitled
            or (member := find_member(manifest, member_id)) is None
            or member.status != "active"
            for member_id in mentions
        ):
            raise ContactNotApproved(
                "A workspace mention target cannot read this conversation"
            )
        return mentions

    def _workspace_mentions_muted(
        self, workspace_id: str, conversation_id: str
    ) -> bool:
        preference = self.store.get(
            "workspace_notification_preference",
            self._workspace_notification_preference_id(
                workspace_id, conversation_id
            ),
        )
        return bool(preference and preference.get("mentions_muted"))

    def _workspace_draft_for_snapshot(
        self,
        draft: dict[str, Any],
        workspaces: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        workspace_id = draft.get("workspace_id")
        conversation_id = draft.get("conversation_id")
        if not isinstance(workspace_id, str) or not isinstance(
            conversation_id, str
        ):
            return None
        workspace = workspaces.get(workspace_id)
        if workspace is None:
            return None
        manifest = self._workspace_current_manifest(workspace)
        local_member_id = str(workspace.get("local_member_id", ""))
        local_member = find_member(manifest, local_member_id)
        if local_member is None or local_member.status != "active":
            return None
        if workspace.get("state") not in {"active", "incomplete_sync"}:
            return None
        try:
            kind, conversation = self._require_workspace_conversation(
                workspace_id, conversation_id
            )
        except (ContactNotApproved, ValidationError):
            return None
        if kind == "direct":
            entitled = set(conversation.get("participant_member_ids", ()))
            if (
                conversation.get("workspace_id") != workspace_id
                or local_member_id not in entitled
            ):
                return None
        elif conversation.get("visibility") == "private":
            entitled = set(conversation.get("member_ids", ()))
            if (
                conversation.get("state") not in {"active", "archived"}
                or local_member_id not in entitled
            ):
                return None
        else:
            if conversation.get("state") not in {"active", "archived"}:
                return None
            entitled = {member.member_id for member in active_members(manifest)}
        visible_mentions = sorted(
            member_id
            for member_id in draft.get("mention_member_ids", ())
            if member_id in entitled
            and (member := find_member(manifest, member_id)) is not None
            and member.status == "active"
        )
        public = {
            "workspace_id": workspace_id,
            "conversation_id": conversation_id,
            "text": str(draft.get("text", "")),
        }
        thread_root_id = draft.get("thread_root_id")
        if thread_root_id is not None:
            if not isinstance(thread_root_id, str):
                return None
            try:
                self._workspace_thread_access_descriptor(
                    workspace,
                    thread_root_id,
                    conversation_id,
                    require_writable=True,
                    root_channel_digest=draft.get("root_channel_digest"),
                    root_author_member_id=draft.get("root_author_member_id"),
                )
            except (ContactNotApproved, ValidationError):
                return None
            public["thread_root_id"] = thread_root_id
        if visible_mentions:
            public["mention_member_ids"] = visible_mentions
        return public

    def _workspace_mention_visible(
        self,
        workspace: dict[str, Any],
        entry: dict[str, Any],
        message: dict[str, Any],
        cache: dict[str, dict[str, Any]] | None = None,
    ) -> bool:
        local_member_id = str(workspace.get("local_member_id", ""))
        if (
            local_member_id not in message.get("mention_member_ids", ())
            or message.get("deleted")
            or not self._workspace_message_is_visible(workspace, message, cache)
            or workspace.get("state") not in {"active", "incomplete_sync"}
            or self.store.get(
                "workspace_message_hidden",
                self.store.opaque_id(
                    "workspace-message-hidden", workspace["id"], message["id"]
                ),
            )
            is not None
        ):
            return False
        if int(entry.get("position", 0)) != int(
            message.get("mention_position", 0)
        ):
            return False
        thread_root = message.get("thread_root")
        if isinstance(thread_root, str):
            try:
                root, _kind, _conversation = self._workspace_thread_context(
                    workspace, thread_root
                )
            except (ContactNotApproved, ValidationError):
                return False
            if root.get("conversation_id") != message.get("conversation_id"):
                return False
        manifest = self._workspace_current_manifest(workspace)
        local_member = find_member(manifest, local_member_id)
        if local_member is None or local_member.status != "active":
            return False
        conversation_id = str(entry.get("conversation_id", ""))
        if entry.get("conversation_kind") == "direct":
            direct = self.store.get(
                "workspace_direct", self._workspace_direct_record_id(conversation_id)
            )
            return bool(
                direct
                and direct.get("workspace_id") == workspace["id"]
                and not direct.get("hidden")
                and local_member_id in direct.get("participant_member_ids", ())
            )
        channel = self.store.get(
            "workspace_channel", self._workspace_channel_record_id(conversation_id)
        )
        if (
            channel is None
            or channel.get("workspace_id") != workspace["id"]
            or channel.get("state") not in {"active", "archived"}
            or (
                channel.get("visibility") == "private"
                and local_member_id not in channel.get("member_ids", ())
            )
            or self._workspace_mentions_muted(workspace["id"], conversation_id)
        ):
            return False
        return True

    def _workspace_mention_authorization_digest(
        self, workspace: dict[str, Any]
    ) -> str:
        channel_state = []
        for channel in self.store.list("workspace_channel"):
            if channel.get("workspace_id") != workspace["id"]:
                continue
            channel_state.append(
                {
                    "id": channel.get("id"),
                    "head": channel.get("head_hash"),
                    "state": channel.get("state"),
                    "members": channel.get("member_ids", []),
                    "mentions_muted": self._workspace_mentions_muted(
                        workspace["id"], str(channel.get("id", ""))
                    ),
                }
            )
        return hashlib.sha256(
            canonical_bytes(
                {
                    "manifest": workspace.get("manifest_hash"),
                    "channels": sorted(channel_state, key=lambda item: str(item["id"])),
                }
            )
        ).hexdigest()

    def _workspace_mention_unread_count(
        self,
        workspace: dict[str, Any],
        read_high_water_override: int | None = None,
    ) -> int:
        index = self.store.get(
            "workspace_mention_index",
            self._workspace_mention_index_id(workspace["id"]),
        )
        if index is None:
            return 0
        read = self.store.get(
            "workspace_read_state", self._workspace_mention_read_id(workspace["id"])
        )
        read_high_water = (
            read_high_water_override
            if read_high_water_override is not None
            else int(read.get("high_water", 0)) if read else 0
        )
        unread = 0
        visibility_cache: dict[str, dict[str, Any]] = {}
        page_id = index.get("head_page")
        while isinstance(page_id, str):
            page = self.store.get("workspace_mention_index", page_id)
            if page is None:
                break
            stop = False
            for entry in reversed(page.get("entries", ())):
                if int(entry.get("position", 0)) <= read_high_water:
                    stop = True
                    break
                message = self.store.get(
                    "workspace_message_state", entry.get("message_record_id")
                )
                if message is not None and self._workspace_mention_visible(
                    workspace, entry, message, visibility_cache
                ):
                    unread += 1
            if stop:
                break
            page_id = page.get("previous_page")
        return unread

    def _workspace_thread_context(
        self,
        workspace: dict[str, Any],
        root_event_id: str,
        *,
        require_writable: bool = False,
        visibility_cache: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], str, dict[str, Any]]:
        """Return a root and its currently authorized conversation.

        Thread indexes are local conveniences, never grants. Every entry point
        rechecks the root, local hide state, current workspace state, and the
        channel/DM disclosure boundary before returning a body.
        """

        try:
            checked_root = str(uuid.UUID(root_event_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValidationError("Workspace thread root is invalid") from exc
        if checked_root != root_event_id:
            raise ValidationError("Workspace thread root is invalid")
        root = self.store.get(
            "workspace_message_state", self._workspace_message_record_id(root_event_id)
        )
        root_event = self.store.get(
            "workspace_event", self._workspace_event_record_id(root_event_id)
        )
        if (
            root is None
            or root_event is None
            or root.get("workspace_id") != workspace.get("id")
            or root_event.get("event_type", "message") != "message"
            or root_event.get("thread_root") is not None
            or root.get("thread_root") is not None
            or self.store.get(
                "workspace_message_hidden",
                self.store.opaque_id(
                    "workspace-message-hidden", workspace["id"], root_event_id
                ),
            )
            is not None
        ):
            raise ContactNotApproved("Workspace thread is unavailable")
        if not self._workspace_message_is_visible(
            workspace, root, visibility_cache
        ):
            raise ContactNotApproved("Workspace thread is unavailable")
        conversation_id = str(root.get("conversation_id", ""))
        kind, conversation = self._workspace_thread_access_descriptor(
            workspace,
            root_event_id,
            conversation_id,
            require_writable=require_writable,
            root_channel_digest=root_event.get("channel_digest"),
            root_author_member_id=root_event.get("author_member_id"),
        )
        return root, kind, conversation

    def _workspace_thread_access_descriptor(
        self,
        workspace: dict[str, Any],
        root_event_id: str,
        conversation_id: str,
        *,
        require_writable: bool = False,
        root_channel_digest: Any = None,
        root_author_member_id: Any = None,
    ) -> tuple[str, dict[str, Any]]:
        """Authorize encrypted thread metadata without opening a message body."""

        try:
            checked_root = str(uuid.UUID(root_event_id))
            checked_conversation = str(uuid.UUID(conversation_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValidationError("Workspace thread metadata is invalid") from exc
        if checked_root != root_event_id or checked_conversation != conversation_id:
            raise ValidationError("Workspace thread metadata is invalid")
        if workspace.get("state") not in {
            "active",
            "incomplete_sync",
            "closed",
            "left",
            "removed",
            "forked",
        }:
            raise ContactNotApproved("Workspace thread is unavailable")
        if self.store.get(
            "workspace_message_hidden",
            self.store.opaque_id(
                "workspace-message-hidden", workspace["id"], root_event_id
            ),
        ) is not None:
            raise ContactNotApproved("Workspace thread is unavailable")
        kind, conversation = self._require_workspace_conversation(
            workspace["id"], conversation_id
        )
        local_member_id = str(workspace.get("local_member_id", ""))
        former_archive = workspace.get("state") in {
            "left",
            "removed",
            "closed",
            "forked",
        }
        if kind == "direct":
            if conversation.get("hidden") or local_member_id not in conversation.get(
                "participant_member_ids", ()
            ):
                raise ContactNotApproved("Workspace thread is unavailable")
            if require_writable and self._public_workspace_direct(conversation)["state"] != "open":
                raise ContactNotApproved("Workspace thread is read-only")
        else:
            state = conversation.get("state")
            if state not in {"active", "archived"}:
                raise ContactNotApproved("Workspace thread is unavailable")
            if (
                conversation.get("visibility") == "private"
                and local_member_id not in conversation.get("member_ids", ())
                and not former_archive
            ):
                raise ContactNotApproved("Workspace thread is unavailable")
            if require_writable and state != "active":
                raise ContactNotApproved("Workspace thread is read-only")
            if conversation.get("visibility") == "private" and not former_archive:
                current_channel = self._workspace_channel_by_digest(
                    str(conversation.get("head_hash", ""))
                )
                event_channel = (
                    self._workspace_channel_by_digest(root_channel_digest)
                    if isinstance(root_channel_digest, str)
                    else None
                )
                admission_version = (
                    self._private_channel_admission_version(
                        current_channel, local_member_id
                    )
                    if current_channel is not None
                    else None
                )
                if (
                    current_channel is None
                    or event_channel is None
                    or not isinstance(root_author_member_id, str)
                    or admission_version is None
                    or event_channel.version < admission_version
                    or not self._private_event_is_currently_entitled(
                        current_channel,
                        event_channel,
                        local_member_id=local_member_id,
                        author_member_id=root_author_member_id,
                    )
                ):
                    raise ContactNotApproved("Workspace thread is unavailable")
        return kind, conversation

    def _workspace_thread_unread_count(self, workspace: dict[str, Any]) -> int:
        unread = 0
        activity = self.store.get(
            "workspace_thread_activity_index",
            self._workspace_thread_activity_id(str(workspace.get("id", ""))),
        )
        entries = activity.get("entries", {}) if activity else {}
        if not isinstance(entries, dict):
            return 0
        for root_event_id, entry in list(entries.items())[:THREAD_ACTIVITY_MAX_ROOTS]:
            if not isinstance(root_event_id, str) or not isinstance(entry, dict):
                continue
            summary = self.store.get(
                "workspace_thread",
                self._workspace_thread_record_id(workspace["id"], root_event_id),
            )
            if summary is None or summary.get("workspace_id") != workspace.get("id"):
                continue
            try:
                self._workspace_thread_access_descriptor(
                    workspace,
                    root_event_id,
                    str(summary.get("conversation_id", "")),
                    root_channel_digest=summary.get("root_channel_digest"),
                    root_author_member_id=summary.get("root_author_member_id"),
                )
            except (ContactNotApproved, ValidationError):
                continue
            unread += int(summary.get("unread_count", 0))
        return unread

    def _workspace_thread_authorization_digest(
        self, workspace: dict[str, Any]
    ) -> str:
        channels = [
            {
                "id": channel.get("id"),
                "head": channel.get("head_hash"),
                "state": channel.get("state"),
                "members": channel.get("member_ids", []),
            }
            for channel in self.store.list("workspace_channel")
            if channel.get("workspace_id") == workspace.get("id")
        ]
        directs = [
            {
                "id": direct.get("id"),
                "participants": direct.get("participant_member_ids", []),
                "hidden": bool(direct.get("hidden")),
            }
            for direct in self.store.list("workspace_direct")
            if direct.get("workspace_id") == workspace.get("id")
        ]
        return hashlib.sha256(
            canonical_bytes(
                {
                    "manifest": workspace.get("manifest_hash"),
                    "state": workspace.get("state"),
                    "channels": sorted(channels, key=lambda item: str(item["id"])),
                    "directs": sorted(directs, key=lambda item: str(item["id"])),
                }
            )
        ).hexdigest()

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
        public["mention_unread_count"] = int(
            workspace.get("mention_unread_count", 0)
        )
        public["thread_unread_count"] = int(
            workspace.get("thread_unread_count", 0)
        )
        search_state = self.store.get(
            "workspace_search_state",
            self._workspace_search_state_id(str(workspace.get("id", ""))),
        )
        public["search_index"] = {
            "status": str(search_state.get("status", "indexing")) if search_state else "indexing",
            "indexed_events": int(search_state.get("indexed_events", 0)) if search_state else 0,
            "target_events": int(search_state.get("target_events", 0)) if search_state else 0,
            "incomplete": bool(
                search_state
                and (
                    search_state.get("growth_limited")
                    or int(search_state.get("truncated_documents", 0)) > 0
                    or search_state.get("status") not in {"ready", "rebuilding"}
                )
            ),
        }
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
        public["mentions_muted"] = self._workspace_mentions_muted(
            workspace_id, channel_id
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

    def _public_workspace_direct(
        self, direct: dict[str, Any]
    ) -> dict[str, Any]:
        workspace = self._require_workspace(str(direct.get("workspace_id", "")))
        manifest = self._workspace_current_manifest(workspace)
        local_member_id = str(workspace.get("local_member_id", ""))
        participants = tuple(direct.get("participant_member_ids", ()))
        peer_member_id = next(
            (member_id for member_id in participants if member_id != local_member_id),
            "",
        )
        peer = find_member(manifest, peer_member_id)
        local = find_member(manifest, local_member_id)
        active = bool(
            workspace.get("state") in {"active", "incomplete_sync"}
            and local is not None
            and local.status == "active"
            and peer is not None
            and peer.status == "active"
        )
        return {
            "id": direct["id"],
            "workspace_id": direct["workspace_id"],
            "participant_member_ids": list(participants),
            "peer_member_id": peer_member_id,
            "peer_display_name": (
                peer.display_name
                if peer is not None
                else str(direct.get("peer_display_name", "Former member"))
            ),
            "peer_short_id": _short_id(peer_member_id) if peer_member_id else "",
            "state": "open" if active else "read_only",
            "unread_count": int(direct.get("unread_count", 0)),
            "created_at": float(direct.get("created_at", 0)),
            "updated_at": float(direct.get("updated_at", 0)),
        }

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
        for private_key in (
            "mutation_candidates",
            "original_text",
            "deletion_revision",
            "conversation_index_page_id",
            "thread_index_page_id",
            "mention_index_page_id",
            "reaction_state_ids",
            "tombstone_event_id",
            "tombstone_retain_until",
        ):
            public.pop(private_key, None)
        public["reactions"] = [dict(item) for item in message.get("reactions", ())]
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

    def _workspace_message_is_visible(
        self,
        workspace: dict[str, Any],
        message: dict[str, Any],
        cache: dict[str, dict[str, Any]] | None = None,
    ) -> bool:
        """Recheck current access and the event's historical entitlement."""

        visibility_cache = cache if cache is not None else {}

        def cached(
            section: str, key: str, loader: Callable[[], Any]
        ) -> Any:
            values = visibility_cache.setdefault(section, {})
            if key not in values:
                values[key] = loader()
            return values[key]

        if message.get("workspace_id") != workspace.get("id"):
            return False
        event_id = message.get("id")
        if not isinstance(event_id, str):
            return False
        event = self.store.get(
            "workspace_event", self._workspace_event_record_id(event_id)
        )
        if event is None or event.get("event_type", "message") != "message":
            return False
        local_member_id = str(workspace.get("local_member_id", ""))
        historical_digest = str(event.get("manifest_digest", ""))
        historical_manifest = cached(
            "manifest",
            historical_digest,
            lambda: self._workspace_manifest_by_digest(historical_digest),
        )
        historical_member = (
            find_member(historical_manifest, local_member_id)
            if historical_manifest is not None
            else None
        )
        if historical_member is None or historical_member.status != "active":
            return False
        workspace_state = str(workspace.get("state", ""))
        former_archive = workspace_state in {"left", "removed", "closed", "forked"}
        if event.get("channel_digest") is None:
            audience = tuple(event.get("audience_member_ids", ()))
            if local_member_id not in audience or len(audience) != 2:
                return False
            direct_id = str(event.get("conversation_id", ""))
            direct = cached(
                "direct",
                direct_id,
                lambda: self.store.get(
                    "workspace_direct", self._workspace_direct_record_id(direct_id)
                ),
            )
            if direct is None or direct.get("hidden"):
                return False
            if former_archive:
                return True
            current_manifest = cached(
                "current_manifest",
                workspace["id"],
                lambda: self._workspace_current_manifest(workspace),
            )
            return all(
                (member := find_member(current_manifest, member_id)) is not None
                and member.status == "active"
                for member_id in audience
            )
        event_channel_digest = str(event.get("channel_digest", ""))
        event_channel = cached(
            "channel_control",
            event_channel_digest,
            lambda: self._workspace_channel_by_digest(event_channel_digest),
        )
        if event_channel is None:
            return False
        conversation_id = str(event.get("conversation_id", ""))
        channel_record = cached(
            "channel_record",
            conversation_id,
            lambda: self.store.get(
                "workspace_channel", self._workspace_channel_record_id(conversation_id)
            ),
        )
        if channel_record is None or channel_record.get("workspace_id") != workspace["id"]:
            return False
        if event_channel.visibility == "public":
            if former_archive:
                return True
            current_manifest = cached(
                "current_manifest",
                workspace["id"],
                lambda: self._workspace_current_manifest(workspace),
            )
            current_member = find_member(current_manifest, local_member_id)
            return bool(current_member is not None and current_member.status == "active")
        if (
            local_member_id not in event_channel.member_ids
            or local_member_id not in event.get("audience_member_ids", ())
        ):
            return False
        if former_archive:
            return True
        if (
            channel_record.get("state") not in {"active", "archived"}
            or local_member_id not in channel_record.get("member_ids", ())
        ):
            return False
        current_channel_digest = str(channel_record.get("head_hash", ""))
        current_channel = cached(
            "channel_control",
            current_channel_digest,
            lambda: self._workspace_channel_by_digest(current_channel_digest),
        )
        admission_version = (
            self._private_channel_admission_version(current_channel, local_member_id)
            if current_channel is not None
            else None
        )
        return bool(
            current_channel is not None
            and admission_version is not None
            and event_channel.version >= admission_version
            and self._private_event_is_currently_entitled(
                current_channel,
                event_channel,
                local_member_id=local_member_id,
                author_member_id=str(event.get("author_member_id", "")),
            )
        )

    def _workspace_reaction_record_id(
        self, workspace_id: str, target_event_id: str, member_id: str, emoji: str
    ) -> str:
        return self.store.opaque_id(
            "workspace-reaction-state", workspace_id, target_event_id, member_id, emoji
        )

    def _workspace_public_reactions(
        self,
        workspace_id: str,
        target_event_id: str,
        overlay: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        workspace = self.store.get("workspace", self._workspace_record_id(workspace_id))
        local_member_id = None if workspace is None else workspace.get("local_member_id")
        message = self.store.get(
            "workspace_message_state", self._workspace_message_record_id(target_event_id)
        )
        reaction_ids = None if message is None else message.get("reaction_state_ids")
        if isinstance(reaction_ids, list):
            states = [
                state
                for record_id in reaction_ids
                if isinstance(record_id, str)
                and (state := self.store.get("workspace_reaction_state", record_id))
                is not None
            ]
        else:
            # One compatibility read is retained for pre-Increment-9 messages.
            # Every new or subsequently reacted-to message carries the exact
            # opaque reaction record IDs and therefore never scans the table.
            states = [
                state
                for state in self.store.list("workspace_reaction_state")
                if state.get("workspace_id") == workspace_id
                and state.get("target_event_id") == target_event_id
            ]
        if overlay is not None:
            states = [state for state in states if state.get("id") != overlay.get("id")]
            states.append(overlay)
        counts: dict[str, int] = defaultdict(int)
        self_emojis: set[str] = set()
        for state in states:
            if state.get("active") is not True:
                continue
            emoji = state.get("emoji")
            if not isinstance(emoji, str):
                continue
            counts[emoji] += 1
            if state.get("member_id") == local_member_id:
                self_emojis.add(emoji)
        return [
            {
                "emoji": emoji,
                "count": counts[emoji],
                "reacted_by_self": emoji in self_emojis,
            }
            for emoji in sorted(counts)
        ]

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
                or member.role in {WorkspaceRole.OWNER, WorkspaceRole.ADMIN}
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
                or member.role in {WorkspaceRole.OWNER, WorkspaceRole.ADMIN}
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
            "mention_unread_count": 0,
            "thread_unread_count": 0,
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
                *self._workspace_search_directory_records(
                    workspace, [channel_record]
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

    def _annotate_workspace_event_retention(
        self,
        records: list[tuple[str, str, dict[str, Any]]],
        event_id: str,
        deliveries: Iterable[dict[str, Any]],
        operation_id: str,
    ) -> None:
        """Bind otherwise opaque delivery and operation records to one event."""

        event_record_id = self._workspace_event_record_id(event_id)
        for kind, record_id, value in records:
            if kind == "workspace_event" and record_id == event_record_id:
                value["delivery_ids"] = [
                    item["id"] for item in deliveries if isinstance(item.get("id"), str)
                ]
                value["operation_record_id"] = self.store.opaque_id(
                    "workspace-operation", operation_id
                )
                return

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
            conversation_id = stored.get("conversation_id")
            direct = (
                self.store.get(
                    "workspace_direct",
                    self._workspace_direct_record_id(conversation_id),
                )
                if isinstance(conversation_id, str)
                else None
            )
            direct_involves_member = bool(
                direct is not None
                and member_id in direct.get("participant_member_ids", [])
            )
            if (
                stored.get("workspace_id") != workspace_id
                or (
                    stored.get("recipient_member_id") != member_id
                    and not direct_involves_member
                )
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
            "mention_unread_count": 0,
            "thread_unread_count": 0,
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

    def _workspace_mention_index_records(
        self,
        *,
        workspace_id: str,
        event_id: str,
        conversation_id: str,
        conversation_kind: str,
        created_at: float,
        message_record_id: str,
        message: dict[str, Any],
    ) -> list[tuple[str, str, dict[str, Any]]]:
        mention_index_id = self._workspace_mention_index_id(workspace_id)
        mention_index = self.store.get(
            "workspace_mention_index", mention_index_id
        ) or {
            "workspace_id": workspace_id,
            "head_page": None,
            "count": 0,
            "high_water": 0,
        }
        mention_page_id = mention_index.get("head_page")
        mention_page = (
            self.store.get("workspace_mention_index", mention_page_id)
            if isinstance(mention_page_id, str)
            else None
        )
        mention_position = int(mention_index.get("high_water", 0)) + 1
        mention_entry = {
            "event_id": event_id,
            "message_record_id": message_record_id,
            "conversation_id": conversation_id,
            "conversation_kind": conversation_kind,
            "position": mention_position,
            "created_at": created_at,
        }
        mention_size = len(
            json.dumps(mention_entry, separators=(",", ":")).encode("utf-8")
        )
        if (
            mention_page is None
            or len(mention_page.get("entries", [])) >= MESSAGE_PAGE_ENTRIES
            or int(mention_page.get("encoded_bytes", 0)) + mention_size
            > MESSAGE_PAGE_MAX_BYTES
        ):
            mention_page_id = self._workspace_mention_page_id(
                workspace_id, event_id
            )
            mention_page = {
                "workspace_id": workspace_id,
                "previous_page": mention_index.get("head_page"),
                "entries": [],
                "encoded_bytes": 0,
            }
            mention_index["head_page"] = mention_page_id
        mention_page["entries"] = [
            *mention_page.get("entries", []),
            mention_entry,
        ]
        mention_page["encoded_bytes"] = int(
            mention_page.get("encoded_bytes", 0)
        ) + mention_size
        mention_index["count"] = int(mention_index.get("count", 0)) + 1
        mention_index["high_water"] = mention_position
        message["mention_position"] = mention_position
        message["mention_index_page_id"] = mention_page_id
        return [
            ("workspace_mention_index", mention_index_id, mention_index),
            ("workspace_mention_index", mention_page_id, mention_page),
        ]

    def _workspace_retention_index_records(
        self,
        workspace: dict[str, Any],
        event: VerifiedWorkspaceEvent,
        event_record: dict[str, Any],
    ) -> list[tuple[str, str, dict[str, Any]]]:
        """Append one canonical event to the bounded sealed pruning index."""

        workspace_id = event.workspace_id
        index_id = self._workspace_retention_index_id(workspace_id)
        index = self.store.get("workspace_retention_index", index_id) or {
            "workspace_id": workspace_id,
            "head_page": None,
            "count": 0,
            "high_water": 0,
            "retention_generation": int(workspace.get("retention_generation", 1)),
        }
        page_id = index.get("head_page")
        page = (
            self.store.get("workspace_retention_index", page_id)
            if isinstance(page_id, str)
            else None
        )
        if page is None or len(page.get("entries", ())) >= RETENTION_INDEX_PAGE_ENTRIES:
            page_id = self._workspace_retention_page_id(workspace_id, event.event_id)
            page = {
                "workspace_id": workspace_id,
                "previous_page": index.get("head_page"),
                "entries": [],
            }
            index["head_page"] = page_id
        entry = {
            "event_id": event.event_id,
            "event_record_id": self._workspace_event_record_id(event.event_id),
            "conversation_id": event.conversation_id,
            "event_type": event.event_type,
            "target_event_id": event.target_event_id,
            "thread_root": event.thread_root,
            "created_at": float(event.created_at),
        }
        page["entries"] = [*page.get("entries", ()), entry]
        index["count"] = int(index.get("count", 0)) + 1
        index["high_water"] = int(index.get("high_water", 0)) + 1
        index["retention_generation"] = int(
            workspace.get("retention_generation", 1)
        )
        event_record["retention_page_id"] = page_id
        return [
            ("workspace_retention_index", index_id, index),
            ("workspace_retention_index", str(page_id), page),
        ]

    def _workspace_mutation_index_records(
        self,
        workspace: dict[str, Any],
        event: VerifiedWorkspaceEvent,
        event_record: dict[str, Any],
        message: dict[str, Any],
    ) -> list[tuple[str, str, dict[str, Any]]]:
        assert event.target_event_id is not None
        index_id = self._workspace_revision_index_id(
            event.workspace_id, event.target_event_id
        )
        index = self.store.get("workspace_revision_index", index_id) or {
            "workspace_id": event.workspace_id,
            "conversation_id": event.conversation_id,
            "target_event_id": event.target_event_id,
            "head_page": None,
            "count": 0,
            "high_water": 0,
        }
        page_id = index.get("head_page")
        page = (
            self.store.get("workspace_revision_index", page_id)
            if isinstance(page_id, str)
            else None
        )
        if page is None or len(page.get("entries", ())) >= MESSAGE_PAGE_ENTRIES:
            page_id = self._workspace_revision_page_id(
                event.workspace_id, event.target_event_id, event.event_id
            )
            page = {
                "workspace_id": event.workspace_id,
                "conversation_id": event.conversation_id,
                "target_event_id": event.target_event_id,
                "previous_page": index.get("head_page"),
                "entries": [],
            }
            index["head_page"] = page_id
        position = int(index.get("high_water", 0)) + 1
        entry = {
            "event_id": event.event_id,
            "event_record_id": self._workspace_event_record_id(event.event_id),
            "event_type": event.event_type,
            "revision": event.revision,
            "author_member_id": event.author_member_id,
            "emoji": event.reaction_emoji,
            "active": event.reaction_active,
            "created_at": float(event.created_at),
            "position": position,
        }
        page["entries"] = [*page.get("entries", ()), entry]
        index["count"] = int(index.get("count", 0)) + 1
        index["high_water"] = position
        event_record["revision_page_id"] = page_id
        records: list[tuple[str, str, dict[str, Any]]] = [
            ("workspace_revision_index", index_id, index),
            ("workspace_revision_index", str(page_id), page),
        ]
        if event.event_type == "delete":
            tombstone_index_id = self._workspace_tombstone_index_id(
                event.workspace_id, event.conversation_id
            )
            tombstone_index = self.store.get(
                "workspace_tombstone_index", tombstone_index_id
            ) or {
                "workspace_id": event.workspace_id,
                "conversation_id": event.conversation_id,
                "head_page": None,
                "count": 0,
                "high_water": 0,
            }
            tombstone_page_id = tombstone_index.get("head_page")
            tombstone_page = (
                self.store.get("workspace_tombstone_index", tombstone_page_id)
                if isinstance(tombstone_page_id, str)
                else None
            )
            if (
                tombstone_page is None
                or len(tombstone_page.get("entries", ())) >= MESSAGE_PAGE_ENTRIES
            ):
                tombstone_page_id = self._workspace_tombstone_page_id(
                    event.workspace_id, event.conversation_id, event.event_id
                )
                tombstone_page = {
                    "workspace_id": event.workspace_id,
                    "conversation_id": event.conversation_id,
                    "previous_page": tombstone_index.get("head_page"),
                    "entries": [],
                }
                tombstone_index["head_page"] = tombstone_page_id
            tombstone_position = int(tombstone_index.get("high_water", 0)) + 1
            tombstone_page["entries"] = [
                *tombstone_page.get("entries", ()),
                {
                    "event_id": event.event_id,
                    "event_record_id": self._workspace_event_record_id(event.event_id),
                    "target_event_id": event.target_event_id,
                    "message_record_id": self._workspace_message_record_id(
                        event.target_event_id
                    ),
                    "position": tombstone_position,
                    "created_at": float(event.created_at),
                },
            ]
            tombstone_index["count"] = int(tombstone_index.get("count", 0)) + 1
            tombstone_index["high_water"] = tombstone_position
            event_record["tombstone_page_id"] = tombstone_page_id
            message["tombstone_event_id"] = event.event_id
            message["tombstone_retain_until"] = max(
                float(message.get("tombstone_retain_until", 0)),
                time.time() + DELIVERY_WINDOW_SECONDS,
            )
            records.extend(
                [
                    (
                        "workspace_tombstone_index",
                        tombstone_index_id,
                        tombstone_index,
                    ),
                    (
                        "workspace_tombstone_index",
                        str(tombstone_page_id),
                        tombstone_page,
                    ),
                ]
            )
        return records

    def _workspace_thread_reply_records(
        self,
        workspace: dict[str, Any],
        event: VerifiedWorkspaceEvent,
        message_record_id: str,
        message: dict[str, Any],
        *,
        direction: str,
    ) -> list[tuple[str, str, dict[str, Any]]]:
        assert event.thread_root is not None
        root_record_id = self._workspace_message_record_id(event.thread_root)
        root = self.store.get("workspace_message_state", root_record_id)
        root_event = self.store.get(
            "workspace_event", self._workspace_event_record_id(event.thread_root)
        )
        if root is None or root_event is None:
            raise ValidationError("Workspace thread root is unavailable")
        index_id = self._workspace_thread_index_id(
            event.workspace_id, event.thread_root
        )
        index = self.store.get("workspace_thread_index", index_id) or {
            "workspace_id": event.workspace_id,
            "conversation_id": event.conversation_id,
            "root_event_id": event.thread_root,
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
            self.store.get("workspace_thread_index", page_id)
            if isinstance(page_id, str)
            else None
        )
        position = int(index.get("high_water", 0)) + 1
        entry = {
            "event_id": event.event_id,
            "message_record_id": message_record_id,
            "position": position,
            "created_at": float(event.created_at),
        }
        encoded_size = len(json.dumps(entry, separators=(",", ":")).encode("utf-8"))
        if (
            page is None
            or len(page.get("entries", [])) >= MESSAGE_PAGE_ENTRIES
            or int(page.get("encoded_bytes", 0)) + encoded_size
            > MESSAGE_PAGE_MAX_BYTES
        ):
            page_id = self._workspace_thread_page_id(
                event.workspace_id, event.thread_root, event.event_id
            )
            page = {
                "workspace_id": event.workspace_id,
                "conversation_id": event.conversation_id,
                "root_event_id": event.thread_root,
                "previous_page": index.get("head_page"),
                "entries": [],
                "encoded_bytes": 0,
            }
            index["head_page"] = page_id
        page["entries"] = [*page.get("entries", []), entry]
        page["encoded_bytes"] = int(page.get("encoded_bytes", 0)) + encoded_size
        index["count"] = int(index.get("count", 0)) + 1
        index["high_water"] = position
        message["thread_position"] = position
        message["thread_index_page_id"] = page_id

        summary_id = self._workspace_thread_record_id(
            event.workspace_id, event.thread_root
        )
        summary = self.store.get("workspace_thread", summary_id) or {
            "id": summary_id,
            "workspace_id": event.workspace_id,
            "conversation_id": event.conversation_id,
            "conversation_kind": message["conversation_kind"],
            "root_event_id": event.thread_root,
            "root_channel_digest": root_event.get("channel_digest"),
            "root_author_member_id": root_event.get("author_member_id"),
            "reply_count": 0,
            "unread_count": 0,
            "high_water": 0,
            "created_at": float(root.get("created_at", event.created_at)),
        }
        summary["reply_count"] = int(summary.get("reply_count", 0)) + 1
        summary["high_water"] = position
        summary["updated_at"] = float(event.created_at)
        if direction == "inbound":
            summary["unread_count"] = int(summary.get("unread_count", 0)) + 1

        root = dict(root)
        root["reply_count"] = int(summary["reply_count"])
        root["thread_unread_count"] = int(summary.get("unread_count", 0))
        root["latest_reply_at"] = float(event.created_at)

        activity_id = self._workspace_thread_activity_id(event.workspace_id)
        activity = self.store.get("workspace_thread_activity_index", activity_id) or {
            "workspace_id": event.workspace_id,
            "high_water": 0,
            "entries": {},
            "authorization_generation": int(
                workspace.get("authorization_generation", 1)
            ),
            "retention_generation": int(workspace.get("retention_generation", 1)),
        }
        activity_position = int(activity.get("high_water", 0)) + 1
        entries = dict(activity.get("entries", {}))
        if event.thread_root not in entries and len(entries) >= THREAD_ACTIVITY_MAX_ROOTS:
            oldest = min(
                entries,
                key=lambda root_id: int(entries[root_id].get("position", 0)),
            )
            entries.pop(oldest, None)
        entries[event.thread_root] = {
            "root_event_id": event.thread_root,
            "conversation_id": event.conversation_id,
            "conversation_kind": message["conversation_kind"],
            "position": activity_position,
            "updated_at": float(event.created_at),
        }
        activity["entries"] = entries
        activity["high_water"] = activity_position
        return [
            ("workspace_thread_index", index_id, index),
            ("workspace_thread_index", str(page_id), page),
            ("workspace_thread", summary_id, summary),
            ("workspace_thread_activity_index", activity_id, activity),
            ("workspace_message_state", root_record_id, root),
        ]

    def _append_workspace_event_records(
        self,
        workspace: dict[str, Any],
        event: VerifiedWorkspaceEvent,
        *,
        direction: str,
        author_display_name: str,
    ) -> tuple[list[tuple[str, str, dict[str, Any]]], dict[str, Any] | None]:
        event_record_id = self._workspace_event_record_id(event.event_id)
        event_record = {
            "id": event.event_id,
            "workspace_id": event.workspace_id,
            "conversation_id": event.conversation_id,
            "author_member_id": event.author_member_id,
            "author_device_id": event.author_device_id,
            "author_destination": event.author_destination.hex(),
            "event_type": event.event_type,
            "sequence": event.sequence,
            "previous_event_digest": event.previous_event_digest,
            "manifest_digest": event.manifest_digest,
            "channel_digest": event.channel_digest,
            "conversation_kind": (
                "direct" if event.channel_digest is None else "channel"
            ),
            "audience_member_ids": list(event.audience_member_ids),
            "mention_member_ids": list(event.mentions),
            "thread_root": event.thread_root,
            "target_event_id": event.target_event_id,
            "base_revision": event.base_revision,
            "revision": event.revision,
            "digest": event.digest,
            "serialized": event.serialized,
            "created_at": float(event.created_at),
        }
        if event.event_type == "edit":
            event_record["text"] = event.text
        elif event.event_type == "reaction":
            event_record["emoji"] = event.reaction_emoji
            event_record["active"] = event.reaction_active
        stream_head_id = self._workspace_stream_head_id(
            event.workspace_id, event.conversation_id, event.author_device_id
        )
        event_channel = (
            self._workspace_channel_by_digest(event.channel_digest)
            if event.channel_digest is not None
            else None
        )
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
        records = [
            ("workspace_event", event_record_id, event_record),
            ("workspace_stream_coverage", stream_head_id, stream_head),
            ("workspace_stream_coverage", sequence_id, sequence),
        ]
        records.extend(
            self._workspace_retention_index_records(workspace, event, event_record)
        )
        if event.event_type != "message":
            return records, None
        message_record_id = self._workspace_message_record_id(event.event_id)
        message = {
            "id": event.event_id,
            "workspace_id": event.workspace_id,
            "conversation_id": event.conversation_id,
            "direction": direction,
            "author_member_id": event.author_member_id,
            "author_display_name": author_display_name,
            "text": event.text,
            "original_text": event.text,
            "revision": 0,
            "deleted": False,
            "deletion_revision": None,
            "mutation_conflict": False,
            "mutation_frozen": False,
            "mutation_candidates": [],
            "reactions": [],
            "reaction_state_ids": [],
            "mention_member_ids": list(event.mentions),
            "thread_root": event.thread_root,
            "sequence": event.sequence,
            "event_digest": event.digest,
            "conversation_kind": (
                "direct" if event.channel_digest is None else "channel"
            ),
            "created_at": float(event.created_at),
        }
        records.extend(
            self._workspace_search_document_records(
                workspace,
                category="thread" if event.thread_root is not None else "message",
                entity_id=event.event_id,
                text=event.text,
                active=True,
                sort_at=float(event.created_at),
                conversation_id=event.conversation_id,
                thread_root_id=event.thread_root,
            )
        )
        if event.thread_root is not None:
            records.append(("workspace_message_state", message_record_id, message))
            records.extend(
                self._workspace_thread_reply_records(
                    workspace,
                    event,
                    message_record_id,
                    message,
                    direction=direction,
                )
            )
            if workspace.get("local_member_id") in event.mentions:
                records.extend(
                    self._workspace_mention_index_records(
                        workspace_id=event.workspace_id,
                        event_id=event.event_id,
                        conversation_id=event.conversation_id,
                        conversation_kind=message["conversation_kind"],
                        created_at=float(event.created_at),
                        message_record_id=message_record_id,
                        message=message,
                    )
                )
            return records, message
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
        message["conversation_index_page_id"] = page_id
        records.extend(
            [
                ("workspace_message_state", message_record_id, message),
                ("workspace_conversation_index", index_id, index),
                ("workspace_conversation_index", page_id, page),
            ]
        )
        if workspace.get("local_member_id") in event.mentions:
            records.extend(
                self._workspace_mention_index_records(
                    workspace_id=event.workspace_id,
                    event_id=event.event_id,
                    conversation_id=event.conversation_id,
                    conversation_kind=message["conversation_kind"],
                    created_at=float(event.created_at),
                    message_record_id=message_record_id,
                    message=message,
                )
            )
        return records, message

    def _workspace_mutation_context(
        self,
        workspace: dict[str, Any],
        target_event: dict[str, Any],
    ) -> tuple[
        VerifiedWorkspaceManifest,
        VerifiedWorkspaceChannel | None,
        tuple[str, ...],
    ]:
        """Resolve current entitlement without widening the target's old audience."""

        manifest = self._workspace_current_manifest(workspace)
        if target_event.get("conversation_kind") == "direct":
            audience = tuple(target_event.get("audience_member_ids", ()))
            if (
                len(audience) != 2
                or tuple(sorted(audience)) != audience
                or any(
                    (member := find_member(manifest, member_id)) is None
                    or member.status != "active"
                    for member_id in audience
                )
            ):
                raise ContactNotApproved(
                    "Workspace direct-message mutations require two active participants"
                )
            return manifest, None, audience
        channel_record = self._require_workspace_channel(
            workspace["id"], target_event.get("conversation_id")
        )
        if channel_record.get("state") != "active":
            raise ContactNotApproved("Workspace channel is not active")
        channel = self._workspace_channel_by_digest(channel_record["head_hash"])
        if channel is None:
            raise ValidationError("Workspace channel control is unavailable")
        old_audience = tuple(target_event.get("audience_member_ids", ()))
        if old_audience:
            if channel.visibility != "private":
                raise ValidationError("Workspace message audience changed kind")
            audience = tuple(
                sorted(set(old_audience).intersection(channel.member_ids))
            )
            if not audience:
                raise ContactNotApproved("No current member retains this message")
        else:
            if channel.visibility != "public":
                raise ValidationError("Workspace message audience changed kind")
            audience = ()
        return manifest, channel, audience

    @staticmethod
    def _workspace_mutation_candidate(event: VerifiedWorkspaceEvent) -> dict[str, Any]:
        candidate = {
            "event_id": event.event_id,
            "event_digest": event.digest,
            "event_type": event.event_type,
            "base_revision": event.base_revision,
            "revision": event.revision,
            "signer_destination": event.author_destination.hex(),
            "created_at": float(event.created_at),
        }
        if event.event_type == "edit":
            candidate["text"] = event.text
            candidate["mention_member_ids"] = list(
                getattr(event, "mentions", ())
            )
        elif event.event_type == "reaction":
            candidate["active"] = event.reaction_active
        return candidate

    @staticmethod
    def _workspace_mutation_content(candidate: dict[str, Any]) -> tuple[Any, ...]:
        return (
            candidate.get("event_type"),
            candidate.get("base_revision"),
            candidate.get("text"),
            tuple(candidate.get("mention_member_ids", ())),
            candidate.get("active"),
        )

    def _apply_workspace_message_mutation(
        self, message: dict[str, Any], event: VerifiedWorkspaceEvent
    ) -> dict[str, Any]:
        candidates = list(message.get("mutation_candidates", ()))
        if any(item.get("event_digest") == event.digest for item in candidates):
            return message
        candidate = self._workspace_mutation_candidate(event)
        equivocated = any(
            item.get("signer_destination") == candidate["signer_destination"]
            and item.get("revision") == candidate["revision"]
            and self._workspace_mutation_content(item)
            != self._workspace_mutation_content(candidate)
            for item in candidates
        )
        candidates.append(candidate)
        winner = max(
            candidates,
            key=lambda item: (
                int(item.get("revision", 0)),
                str(item.get("signer_destination", "")),
                str(item.get("event_digest", "")),
            ),
        )
        highest = int(winner["revision"])
        highest_candidates = {
            self._workspace_mutation_content(item)
            for item in candidates
            if int(item.get("revision", 0)) == highest
        }
        updated = dict(message)
        updated["mutation_candidates"] = candidates
        updated["revision"] = highest
        updated["mutation_conflict"] = len(highest_candidates) > 1
        updated["mutation_frozen"] = bool(
            message.get("mutation_frozen") or equivocated
        )
        # A signed author deletion is a durable tombstone. Later edits cannot
        # make already-deleted plaintext visible again on another device.
        deleted = bool(message.get("deleted")) or any(
            item.get("event_type") == "delete" for item in candidates
        )
        updated["deleted"] = deleted
        deletion_revisions = [
            int(item["revision"])
            for item in candidates
            if item.get("event_type") == "delete"
        ]
        updated["deletion_revision"] = (
            min(deletion_revisions) if deletion_revisions else message.get("deletion_revision")
        )
        updated["edited_at"] = float(winner.get("created_at", event.created_at))
        if deleted:
            updated["text"] = ""
        elif winner.get("pruned"):
            updated["text"] = str(message.get("text", ""))
        else:
            updated["text"] = str(winner.get("text", ""))
        if (
            not deleted
            and winner.get("event_type") == "edit"
            and not winner.get("pruned")
        ):
            updated["mention_member_ids"] = list(
                winner.get("mention_member_ids", ())
            )
        return updated

    def _apply_workspace_reaction_mutation(
        self,
        event: VerifiedWorkspaceEvent,
        existing: dict[str, Any] | None,
    ) -> dict[str, Any]:
        assert event.reaction_emoji is not None
        record_id = self._workspace_reaction_record_id(
            event.workspace_id,
            str(event.target_event_id),
            event.author_member_id,
            event.reaction_emoji,
        )
        state = existing or {
            "id": record_id,
            "workspace_id": event.workspace_id,
            "target_event_id": event.target_event_id,
            "member_id": event.author_member_id,
            "emoji": event.reaction_emoji,
            "revision": 0,
            "active": False,
            "mutation_conflict": False,
            "mutation_frozen": False,
            "mutation_candidates": [],
        }
        candidates = list(state.get("mutation_candidates", ()))
        if any(item.get("event_digest") == event.digest for item in candidates):
            return state
        candidate = self._workspace_mutation_candidate(event)
        equivocated = any(
            item.get("signer_destination") == candidate["signer_destination"]
            and item.get("revision") == candidate["revision"]
            and self._workspace_mutation_content(item)
            != self._workspace_mutation_content(candidate)
            for item in candidates
        )
        candidates.append(candidate)
        winner = max(
            candidates,
            key=lambda item: (
                int(item.get("revision", 0)),
                str(item.get("signer_destination", "")),
                str(item.get("event_digest", "")),
            ),
        )
        highest = int(winner["revision"])
        updated = dict(state)
        updated.update(
            {
                "mutation_candidates": candidates,
                "revision": highest,
                "active": bool(winner.get("active")),
                "mutation_conflict": len(
                    {
                        self._workspace_mutation_content(item)
                        for item in candidates
                        if int(item.get("revision", 0)) == highest
                    }
                )
                > 1,
                "mutation_frozen": bool(
                    state.get("mutation_frozen") or equivocated
                ),
                "updated_at": float(event.created_at),
            }
        )
        return updated

    def _workspace_mutation_records(
        self,
        event: VerifiedWorkspaceEvent,
        message: dict[str, Any],
    ) -> tuple[list[tuple[str, str, dict[str, Any]]], dict[str, Any]]:
        message_id = self._workspace_message_record_id(message["id"])
        if event.event_type in {"edit", "delete"}:
            updated = self._apply_workspace_message_mutation(message, event)
            records = [("workspace_message_state", message_id, updated)]
            local_member_id = str(
                self._require_workspace(event.workspace_id).get(
                    "local_member_id", ""
                )
            )
            was_mentioned = local_member_id in message.get(
                "mention_member_ids", ()
            )
            is_mentioned = (
                not updated.get("deleted")
                and local_member_id in updated.get("mention_member_ids", ())
            )
            if is_mentioned and not was_mentioned:
                records.extend(
                    self._workspace_mention_index_records(
                        workspace_id=event.workspace_id,
                        event_id=event.event_id,
                        conversation_id=event.conversation_id,
                        conversation_kind=str(message["conversation_kind"]),
                        created_at=float(event.created_at),
                        message_record_id=message_id,
                        message=updated,
                    )
                )
            elif was_mentioned and not is_mentioned:
                updated.pop("mention_position", None)
            workspace = self._require_workspace(event.workspace_id)
            records.extend(
                self._workspace_search_document_records(
                    workspace,
                    category=(
                        "thread"
                        if isinstance(updated.get("thread_root"), str)
                        else "message"
                    ),
                    entity_id=str(updated["id"]),
                    text=str(updated.get("text", "")),
                    active=not bool(updated.get("deleted")),
                    sort_at=float(updated.get("created_at", 0)),
                    conversation_id=str(updated.get("conversation_id", "")),
                    thread_root_id=(
                        str(updated["thread_root"])
                        if isinstance(updated.get("thread_root"), str)
                        else None
                    ),
                )
            )
            return records, updated
        assert event.reaction_emoji is not None
        reaction_id = self._workspace_reaction_record_id(
            event.workspace_id,
            message["id"],
            event.author_member_id,
            event.reaction_emoji,
        )
        reaction = self._apply_workspace_reaction_mutation(
            event, self.store.get("workspace_reaction_state", reaction_id)
        )
        updated = dict(message)
        updated["reactions"] = self._workspace_public_reactions(
            event.workspace_id, message["id"], reaction
        )
        reaction_state_ids = {
            item
            for item in message.get("reaction_state_ids", ())
            if isinstance(item, str)
        }
        reaction_state_ids.add(reaction_id)
        updated["reaction_state_ids"] = sorted(reaction_state_ids)
        if reaction.get("mutation_frozen"):
            updated["mutation_frozen"] = True
        return [
            ("workspace_reaction_state", reaction_id, reaction),
            ("workspace_message_state", message_id, updated),
        ], updated

    def _workspace_mutation_deliveries(
        self,
        manifest: VerifiedWorkspaceManifest,
        event: VerifiedWorkspaceEvent,
    ) -> list[dict[str, Any]]:
        audience = set(event.audience_member_ids)
        deliveries: list[dict[str, Any]] = []
        for member in active_members(manifest):
            if audience and member.member_id not in audience:
                continue
            for device in member.devices:
                if device.device_id == event.author_device_id:
                    continue
                deliveries.append(
                    self._workspace_delivery_record(
                        workspace_id=event.workspace_id,
                        recipient_member_id=member.member_id,
                        recipient_device=device,
                        kind="workspace_event",
                        document=event.serialized,
                        event_id=event.event_id,
                        conversation_id=event.conversation_id,
                    )
                )
        return deliveries

    def _workspace_checkpoint_records_and_deliveries(
        self,
        workspace: dict[str, Any],
        event: VerifiedWorkspaceEvent,
        event_deliveries: Iterable[dict[str, Any]],
    ) -> tuple[list[tuple[str, str, dict[str, Any]]], list[dict[str, Any]]]:
        identity = self._identity
        if identity is None or event.author_device_id != workspace.get("local_device_id"):
            return [], []
        raw = create_workspace_event_checkpoint(
            identity,
            workspace_id=event.workspace_id,
            checkpoint_id=_new_id(),
            author_member_id=event.author_member_id,
            author_device_id=event.author_device_id,
            manifest_digest=event.manifest_digest,
            streams=[{
                "conversation_id": event.conversation_id,
                "channel_digest": event.channel_digest,
                "high_water": event.sequence,
                "head_digest": event.digest,
            }],
        )
        manifest = self._workspace_manifest_by_digest(event.manifest_digest)
        if manifest is None:
            return [], []
        checkpoint = verify_workspace_event_checkpoint(raw, manifest=manifest)
        checkpoint_record_id = self.store.opaque_id(
            "workspace-event-checkpoint", checkpoint.digest
        )
        head_id = self.store.opaque_id(
            "workspace-checkpoint-head", checkpoint.workspace_id,
            checkpoint.author_device_id, event.conversation_id,
        )
        catalog_id = self.store.opaque_id(
            "workspace-checkpoint-catalog",
            checkpoint.workspace_id,
            checkpoint.author_device_id,
        )
        catalog = self.store.get("workspace_checkpoint_catalog", catalog_id) or {
            "workspace_id": checkpoint.workspace_id,
            "author_device_id": checkpoint.author_device_id,
            "entries": [],
        }
        entries = [
            item for item in catalog.get("entries", ())
            if item.get("conversation_id") != event.conversation_id
        ]
        entries.append({
            "conversation_id": event.conversation_id,
            "channel_digest": event.channel_digest,
            "high_water": event.sequence,
            "checkpoint_digest": checkpoint.digest,
        })
        entries.sort(key=lambda item: item["conversation_id"])
        catalog["entries"] = entries[-MAX_HISTORY_STREAMS:]
        # Checkpoints are durable local history controls and are returned only
        # inside an explicitly authorised history response.  Sending a second
        # live packet for every ordinary event would leak stream activity and
        # double the normal delivery workload.
        del event_deliveries
        return ([
            ("workspace_event_checkpoint", checkpoint_record_id, {
                "workspace_id": checkpoint.workspace_id,
                "checkpoint_id": checkpoint.checkpoint_id,
                "author_member_id": checkpoint.author_member_id,
                "author_device_id": checkpoint.author_device_id,
                "manifest_digest": checkpoint.manifest_digest,
                "streams": list(checkpoint.streams),
                "digest": checkpoint.digest,
                "serialized": checkpoint.serialized,
                "created_at": checkpoint.created_at,
            }),
            ("workspace_checkpoint_head", head_id, {
                "workspace_id": checkpoint.workspace_id,
                "conversation_id": event.conversation_id,
                "author_device_id": checkpoint.author_device_id,
                "high_water": event.sequence,
                "checkpoint_digest": checkpoint.digest,
            }),
            ("workspace_checkpoint_catalog", catalog_id, catalog),
        ], [])

    def _send_workspace_mutation(
        self,
        command: str,
        workspace_id: Any,
        target_event_id: Any,
        event_id: Any,
        operation_id: Any,
        *,
        text: Any = None,
        mention_member_ids: Any = None,
        emoji: Any = None,
        active: Any = None,
    ) -> dict[str, Any]:
        event_type = {
            "edit_workspace_message": "edit",
            "delete_workspace_message": "delete",
            "set_workspace_reaction": "reaction",
        }[command]
        payload = {
            "workspace_id": workspace_id,
            "target_event_id": target_event_id,
            "event_id": event_id,
        }
        if event_type == "edit":
            payload["text"] = text
            payload["mention_member_ids"] = mention_member_ids or []
        elif event_type == "reaction":
            payload.update({"emoji": emoji, "active": active})
        operation_id, digest, replay = self._workspace_operation(
            command, operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if workspace.get("state") != "active":
            raise ContactNotApproved("Workspace is not active")
        try:
            checked_target_id = str(uuid.UUID(target_event_id))
            checked_event_id = str(uuid.UUID(event_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValidationError("Workspace event ID is invalid") from exc
        if checked_target_id != target_event_id or checked_event_id != event_id:
            raise ValidationError("Workspace event ID is invalid")
        if self.store.get(
            "workspace_event", self._workspace_event_record_id(event_id)
        ) or self._workspace_event_id_is_retired(workspace_id, event_id):
            raise ValidationError("Workspace event ID was already used")
        message = self.store.get(
            "workspace_message_state", self._workspace_message_record_id(target_event_id)
        )
        target_event = self.store.get(
            "workspace_event", self._workspace_event_record_id(target_event_id)
        )
        if (
            message is None
            or target_event is None
            or target_event.get("event_type", "message") != "message"
            or message.get("workspace_id") != workspace_id
        ):
            raise ValidationError("Workspace message does not exist")
        if message.get("mutation_frozen"):
            raise ContactNotApproved("Workspace message mutations are frozen")
        local_member_id = workspace["local_member_id"]
        if event_type in {"edit", "delete"} and message.get("author_member_id") != local_member_id:
            raise ContactNotApproved("Only the message author can change it")
        if message.get("deleted"):
            raise ContactNotApproved("Workspace message was deleted")
        thread_root = target_event.get("thread_root")
        if isinstance(thread_root, str):
            self._workspace_thread_context(
                workspace, thread_root, require_writable=True
            )
        elif self.store.get(
            "workspace_thread",
            self._workspace_thread_record_id(workspace_id, target_event_id),
        ) is not None:
            self._workspace_thread_context(
                workspace, target_event_id, require_writable=True
            )
        manifest, channel, audience = self._workspace_mutation_context(
            workspace, target_event
        )
        local_member = find_member(manifest, local_member_id)
        if local_member is None or local_member.status != "active":
            raise ContactNotApproved("Local member is not active")
        if audience and local_member_id not in audience:
            raise ContactNotApproved("Local member no longer has message access")
        if event_type == "edit" and (
            not isinstance(text, str)
            or not text.strip()
            or len(text.encode("utf-8")) > MAX_MESSAGE_TEXT_BYTES
        ):
            raise ValidationError("Workspace message is empty or too large")
        mentions = (
            self._validate_workspace_mentions(
                workspace, message["conversation_id"], mention_member_ids
            )
            if event_type == "edit"
            else ()
        )
        if event_type == "reaction" and not isinstance(active, bool):
            raise ValidationError("Workspace reaction state is invalid")
        if event_type == "reaction":
            reaction_id = self._workspace_reaction_record_id(
                workspace_id, target_event_id, local_member_id, str(emoji)
            )
            reaction = self.store.get("workspace_reaction_state", reaction_id)
            if reaction is not None and reaction.get("mutation_frozen"):
                raise ContactNotApproved("Workspace reaction mutations are frozen")
            base_revision = int(reaction.get("revision", 0)) if reaction else 0
        else:
            base_revision = int(message.get("revision", 0))
        stream_head = self.store.get(
            "workspace_stream_coverage",
            self._workspace_stream_head_id(
                workspace_id, message["conversation_id"], workspace["local_device_id"]
            ),
        )
        sequence = int(stream_head.get("high_water", 0)) + 1 if stream_head else 1
        identity = self._identity
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        raw = create_workspace_mutation_event(
            identity,
            workspace_id=workspace_id,
            conversation_id=message["conversation_id"],
            event_id=event_id,
            event_type=event_type,
            author_member_id=local_member_id,
            author_device_id=workspace["local_device_id"],
            sequence=sequence,
            previous_event_digest=stream_head.get("head_digest") if stream_head else None,
            manifest_digest=manifest.digest,
            channel_digest=None if channel is None else channel.digest,
            target_event_id=target_event_id,
            base_revision=base_revision,
            revision=base_revision + 1,
            text=text if event_type == "edit" else None,
            mention_member_ids=mentions if event_type == "edit" else None,
            emoji=emoji if event_type == "reaction" else None,
            active=active if event_type == "reaction" else None,
            thread_root=target_event.get("thread_root"),
            audience_member_ids=audience or None,
        )
        event = verify_workspace_event(
            raw,
            manifest=manifest,
            channel=channel,
            direct_member_ids=audience if channel is None else None,
        )
        records, _ = self._append_workspace_event_records(
            workspace, event, direction="outbound", author_display_name=local_member.display_name
        )
        mutation_records, updated_message = self._workspace_mutation_records(event, message)
        records.extend(mutation_records)
        event_record = next(
            value
            for kind, record_id, value in records
            if kind == "workspace_event"
            and record_id == self._workspace_event_record_id(event.event_id)
        )
        records.extend(
            self._workspace_mutation_index_records(
                workspace, event, event_record, updated_message
            )
        )
        deliveries = self._workspace_mutation_deliveries(manifest, event)
        checkpoint_records, checkpoint_deliveries = (
            self._workspace_checkpoint_records_and_deliveries(
                workspace, event, deliveries
            )
        )
        all_deliveries = [*deliveries, *checkpoint_deliveries]
        records.extend(checkpoint_records)
        records.extend(("workspace_delivery", item["id"], item) for item in all_deliveries)
        records.extend(self._due_records(add=all_deliveries))
        self._annotate_workspace_event_retention(
            records, event.event_id, deliveries, operation_id
        )
        public = dict(self._public_workspace_message(updated_message))
        if event_type == "reaction":
            reaction_overlay = next(
                value for kind, _record_id, value in mutation_records
                if kind == "workspace_reaction_state"
            )
            public["reactions"] = self._workspace_public_reactions(
                workspace_id, target_event_id, reaction_overlay
            )
        committed = self.store.commit_operation(
            operation_id, digest, public, records
        )
        self._workspace_changed(
            workspace_id,
            conversation_id=message["conversation_id"],
            resource_kind="message_mutation",
        )
        return committed

    def edit_workspace_message(
        self, workspace_id: Any, event_id: Any, text: Any,
        mutation_event_id: Any, operation_id: Any,
        mention_member_ids: Any = None,
    ) -> dict[str, Any]:
        return self._send_workspace_mutation(
            "edit_workspace_message", workspace_id, event_id,
            mutation_event_id, operation_id, text=text,
            mention_member_ids=mention_member_ids,
        )

    def delete_workspace_message(
        self, workspace_id: Any, event_id: Any,
        mutation_event_id: Any, operation_id: Any
    ) -> dict[str, Any]:
        return self._send_workspace_mutation(
            "delete_workspace_message", workspace_id, event_id,
            mutation_event_id, operation_id
        )

    def set_workspace_reaction(
        self, workspace_id: Any, event_id: Any, emoji: Any, active: Any,
        mutation_event_id: Any, operation_id: Any
    ) -> dict[str, Any]:
        return self._send_workspace_mutation(
            "set_workspace_reaction", workspace_id, event_id,
            mutation_event_id, operation_id, emoji=emoji, active=active
        )

    def send_workspace_message(
        self,
        workspace_id: Any,
        channel_id: Any,
        text: Any,
        event_id: Any,
        operation_id: Any,
        mention_member_ids: Any = None,
    ) -> dict[str, Any]:
        payload = {
            "workspace_id": workspace_id,
            "channel_id": channel_id,
            "text": text,
            "event_id": event_id,
        }
        if mention_member_ids:
            payload["mention_member_ids"] = mention_member_ids
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
        mentions = self._validate_workspace_mentions(
            workspace, channel_id, mention_member_ids
        )
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
        if existing_event is not None or self._workspace_event_id_is_retired(
            workspace_id, event_id
        ):
            raise ValidationError("Workspace event ID was already used")
        identity = self._identity
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        manifest = self._workspace_current_manifest(workspace)
        local_member = find_member(manifest, workspace["local_member_id"])
        if local_member is None or local_member.status != "active":
            raise ContactNotApproved("Local member is not active")
        if not self._posting_allowed(manifest, local_member):
            raise ContactNotApproved(
                "Workspace posting is restricted to owners and administrators"
            )
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
            mention_member_ids=mentions,
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
            if (
                channel.visibility == "private"
                and member.member_id not in channel.member_ids
            ):
                continue
            for device in member.devices:
                if device.device_id == workspace["local_device_id"]:
                    continue
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
        checkpoint_records, checkpoint_deliveries = (
            self._workspace_checkpoint_records_and_deliveries(
                workspace, event, deliveries
            )
        )
        all_deliveries = [*deliveries, *checkpoint_deliveries]
        records.extend(checkpoint_records)
        records.extend(
            ("workspace_delivery", item["id"], item) for item in all_deliveries
        )
        records.extend(self._due_records(add=all_deliveries))
        self._annotate_workspace_event_retention(
            records, event.event_id, deliveries, operation_id
        )
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

    def open_workspace_direct(
        self, workspace_id: Any, member_id: Any, operation_id: Any
    ) -> dict[str, Any]:
        payload = {"workspace_id": workspace_id, "member_id": member_id}
        operation_id, digest, replay = self._workspace_operation(
            "open_workspace_direct", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if workspace.get("state") != "active":
            raise ContactNotApproved("Workspace is not active")
        manifest = self._workspace_current_manifest(workspace)
        local_member_id = workspace["local_member_id"]
        if not isinstance(member_id, str) or member_id == local_member_id:
            raise ValidationError("Workspace direct-message member is invalid")
        local = find_member(manifest, local_member_id)
        peer = find_member(manifest, member_id)
        if (
            local is None
            or local.status != "active"
            or peer is None
            or peer.status != "active"
        ):
            raise ContactNotApproved(
                "Workspace direct messages require two active members"
            )
        participants = sorted([local_member_id, member_id])
        conversation_id = workspace_direct_conversation_id(
            workspace_id, participants
        )
        record_id = self._workspace_direct_record_id(conversation_id)
        direct = self.store.get("workspace_direct", record_id)
        now = time.time()
        records: list[tuple[str, str, dict[str, Any]]] = []
        if direct is None:
            direct = {
                "id": conversation_id,
                "workspace_id": workspace_id,
                "participant_member_ids": participants,
                "peer_display_name": peer.display_name,
                "hidden": False,
                "unread_count": 0,
                "created_at": now,
                "updated_at": now,
            }
            index = {
                "workspace_id": workspace_id,
                "conversation_id": conversation_id,
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
            records.extend(
                [
                    (
                        "workspace_conversation_index",
                        self._workspace_index_record_id(
                            workspace_id, conversation_id
                        ),
                        index,
                    ),
                    (
                        "workspace_read_state",
                        self.store.opaque_id(
                            "workspace-read-state", workspace_id, conversation_id
                        ),
                        {
                            "workspace_id": workspace_id,
                            "conversation_id": conversation_id,
                            "high_water": 0,
                        },
                    ),
                ]
            )
        elif direct.get("participant_member_ids") != participants:
            raise ValidationError("Stored workspace direct-message participants changed")
        direct["hidden"] = False
        direct["peer_display_name"] = peer.display_name
        direct["updated_at"] = now
        records.insert(0, ("workspace_direct", record_id, direct))
        outcome = self._public_workspace_direct(direct)
        committed = self.store.commit_operation(
            operation_id, digest, outcome, records
        )
        self._workspace_changed(
            workspace_id,
            conversation_id=conversation_id,
            resource_kind="direct",
        )
        return committed

    def hide_workspace_direct(
        self, workspace_id: Any, conversation_id: Any, operation_id: Any
    ) -> dict[str, Any]:
        payload = {
            "workspace_id": workspace_id,
            "conversation_id": conversation_id,
        }
        operation_id, digest, replay = self._workspace_operation(
            "hide_workspace_direct", operation_id, payload
        )
        if replay is not None:
            return replay
        if not isinstance(conversation_id, str):
            raise ValidationError("Workspace direct-message identifier is invalid")
        direct = self._require_workspace_direct(workspace_id, conversation_id)
        direct["hidden"] = True
        direct["updated_at"] = time.time()
        outcome = {
            "workspace_id": workspace_id,
            "conversation_id": conversation_id,
            "hidden": True,
        }
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [
                (
                    "workspace_direct",
                    self._workspace_direct_record_id(conversation_id),
                    direct,
                )
            ],
        )
        self._workspace_changed(
            workspace_id,
            conversation_id=conversation_id,
            resource_kind="direct_visibility",
        )
        return committed

    def send_workspace_direct_message(
        self,
        workspace_id: Any,
        conversation_id: Any,
        text: Any,
        event_id: Any,
        operation_id: Any,
        mention_member_ids: Any = None,
    ) -> dict[str, Any]:
        payload = {
            "workspace_id": workspace_id,
            "conversation_id": conversation_id,
            "text": text,
            "event_id": event_id,
        }
        if mention_member_ids:
            payload["mention_member_ids"] = mention_member_ids
        operation_id, digest, replay = self._workspace_operation(
            "send_workspace_direct_message", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if workspace.get("state") != "active":
            raise ContactNotApproved("Workspace is not active")
        if not isinstance(conversation_id, str):
            raise ValidationError("Workspace direct-message identifier is invalid")
        direct = self._require_workspace_direct(workspace_id, conversation_id)
        mentions = self._validate_workspace_mentions(
            workspace, conversation_id, mention_member_ids
        )
        if (
            not isinstance(text, str)
            or not text.strip()
            or len(text.encode("utf-8")) > MAX_MESSAGE_TEXT_BYTES
        ):
            raise ValidationError("Workspace message is empty or too large")
        if not isinstance(event_id, str):
            raise ValidationError("Workspace event ID is invalid")
        try:
            if str(uuid.UUID(event_id)) != event_id:
                raise ValueError
        except (ValueError, AttributeError) as exc:
            raise ValidationError("Workspace event ID is invalid") from exc
        if self.store.get(
            "workspace_event", self._workspace_event_record_id(event_id)
        ) is not None or self._workspace_event_id_is_retired(workspace_id, event_id):
            raise ValidationError("Workspace event ID was already used")
        manifest = self._workspace_current_manifest(workspace)
        participants = tuple(direct.get("participant_member_ids", ()))
        if (
            len(participants) != 2
            or tuple(sorted(participants)) != participants
            or workspace["local_member_id"] not in participants
            or workspace_direct_conversation_id(workspace_id, participants)
            != conversation_id
        ):
            raise ValidationError("Workspace direct-message participants are invalid")
        participant_members = [find_member(manifest, item) for item in participants]
        if any(member is None or member.status != "active" for member in participant_members):
            raise ContactNotApproved(
                "Workspace direct messages stop after either participant leaves"
            )
        local_member = find_member(manifest, workspace["local_member_id"])
        if local_member is None or local_member.status != "active":
            raise ContactNotApproved("Local member is not active")
        identity = self._identity
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        stream_head_id = self._workspace_stream_head_id(
            workspace_id, conversation_id, workspace["local_device_id"]
        )
        stream_head = self.store.get("workspace_stream_coverage", stream_head_id)
        sequence = int(stream_head.get("high_water", 0)) + 1 if stream_head else 1
        previous = stream_head.get("head_digest") if stream_head else None
        raw = create_workspace_event(
            identity,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            event_id=event_id,
            author_member_id=workspace["local_member_id"],
            author_device_id=workspace["local_device_id"],
            sequence=sequence,
            previous_event_digest=previous,
            manifest_digest=manifest.digest,
            channel_digest=None,
            text=text,
            mention_member_ids=mentions,
            audience_member_ids=participants,
        )
        event = verify_workspace_event(
            raw,
            manifest=manifest,
            channel=None,
            direct_member_ids=participants,
        )
        records, message = self._append_workspace_event_records(
            workspace,
            event,
            direction="outbound",
            author_display_name=local_member.display_name,
        )
        deliveries: list[dict[str, Any]] = []
        for member in participant_members:
            assert member is not None
            for device in member.devices:
                if device.device_id == workspace["local_device_id"]:
                    continue
                deliveries.append(
                    self._workspace_delivery_record(
                        workspace_id=workspace_id,
                        recipient_member_id=member.member_id,
                        recipient_device=device,
                        kind="workspace_event",
                        document=event.serialized,
                        event_id=event.event_id,
                        conversation_id=conversation_id,
                    )
                )
        checkpoint_records, checkpoint_deliveries = (
            self._workspace_checkpoint_records_and_deliveries(
                workspace, event, deliveries
            )
        )
        all_deliveries = [*deliveries, *checkpoint_deliveries]
        records.extend(checkpoint_records)
        records.extend(
            ("workspace_delivery", item["id"], item) for item in all_deliveries
        )
        records.extend(self._due_records(add=all_deliveries))
        self._annotate_workspace_event_retention(
            records, event.event_id, deliveries, operation_id
        )
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
        direct["hidden"] = False
        direct["updated_at"] = time.time()
        records.append(
            (
                "workspace_direct",
                self._workspace_direct_record_id(conversation_id),
                direct,
            )
        )
        outcome = self._public_workspace_message(message)
        committed = self.store.commit_operation(
            operation_id, digest, outcome, records
        )
        self._workspace_changed(
            workspace_id,
            conversation_id=conversation_id,
            resource_kind="message",
        )
        return committed

    def send_workspace_thread_reply(
        self,
        workspace_id: Any,
        conversation_id: Any,
        thread_root_id: Any,
        text: Any,
        event_id: Any,
        operation_id: Any,
        mention_member_ids: Any = None,
    ) -> dict[str, Any]:
        payload = {
            "workspace_id": workspace_id,
            "conversation_id": conversation_id,
            "thread_root_id": thread_root_id,
            "text": text,
            "event_id": event_id,
            "mention_member_ids": mention_member_ids or [],
        }
        operation_id, digest, replay = self._workspace_operation(
            "send_workspace_thread_reply", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if workspace.get("state") != "active":
            raise ContactNotApproved("Workspace is not active")
        if not isinstance(conversation_id, str):
            raise ValidationError("Workspace conversation is invalid")
        root, conversation_kind, conversation = self._workspace_thread_context(
            workspace, thread_root_id, require_writable=True
        )
        if root.get("conversation_id") != conversation_id:
            raise ValidationError("Workspace thread belongs to another conversation")
        if (
            not isinstance(text, str)
            or not text.strip()
            or len(text.encode("utf-8")) > MAX_MESSAGE_TEXT_BYTES
        ):
            raise ValidationError("Workspace message is empty or too large")
        try:
            checked_event_id = str(uuid.UUID(event_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValidationError("Workspace event ID is invalid") from exc
        if checked_event_id != event_id or self.store.get(
            "workspace_event", self._workspace_event_record_id(event_id)
        ) is not None or self._workspace_event_id_is_retired(workspace_id, event_id):
            raise ValidationError("Workspace event ID was already used or is invalid")
        mentions = self._validate_workspace_mentions(
            workspace, conversation_id, mention_member_ids
        )
        manifest = self._workspace_current_manifest(workspace)
        local_member = find_member(manifest, workspace["local_member_id"])
        if local_member is None or local_member.status != "active":
            raise ContactNotApproved("Local member is not active")
        channel: VerifiedWorkspaceChannel | None = None
        if conversation_kind == "direct":
            audience = tuple(conversation.get("participant_member_ids", ()))
            if (
                len(audience) != 2
                or tuple(sorted(audience)) != audience
                or any(
                    (member := find_member(manifest, member_id)) is None
                    or member.status != "active"
                    for member_id in audience
                )
            ):
                raise ContactNotApproved("Workspace thread participants are not active")
        else:
            if not self._posting_allowed(manifest, local_member):
                raise ContactNotApproved(
                    "Workspace posting is restricted to owners and administrators"
                )
            channel = self._workspace_channel_by_digest(conversation["head_hash"])
            if channel is None:
                raise ValidationError("Workspace channel control is unavailable")
            audience = (
                tuple(channel.member_ids) if channel.visibility == "private" else ()
            )
        identity = self._identity
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        stream_head_id = self._workspace_stream_head_id(
            workspace_id, conversation_id, workspace["local_device_id"]
        )
        stream_head = self.store.get("workspace_stream_coverage", stream_head_id)
        sequence = int(stream_head.get("high_water", 0)) + 1 if stream_head else 1
        raw = create_workspace_event(
            identity,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            event_id=event_id,
            author_member_id=workspace["local_member_id"],
            author_device_id=workspace["local_device_id"],
            sequence=sequence,
            previous_event_digest=stream_head.get("head_digest") if stream_head else None,
            manifest_digest=manifest.digest,
            channel_digest=None if channel is None else channel.digest,
            text=text,
            thread_root=thread_root_id,
            mention_member_ids=mentions,
            audience_member_ids=audience or None,
        )
        event = verify_workspace_event(
            raw,
            manifest=manifest,
            channel=channel,
            direct_member_ids=audience if channel is None else None,
        )
        records, message = self._append_workspace_event_records(
            workspace,
            event,
            direction="outbound",
            author_display_name=local_member.display_name,
        )
        assert message is not None
        deliveries: list[dict[str, Any]] = []
        for member in active_members(manifest):
            if audience and member.member_id not in audience:
                continue
            for device in member.devices:
                if device.device_id == workspace["local_device_id"]:
                    continue
                deliveries.append(
                    self._workspace_delivery_record(
                        workspace_id=workspace_id,
                        recipient_member_id=member.member_id,
                        recipient_device=device,
                        kind="workspace_event",
                        document=event.serialized,
                        event_id=event.event_id,
                        conversation_id=conversation_id,
                    )
                )
        checkpoint_records, checkpoint_deliveries = (
            self._workspace_checkpoint_records_and_deliveries(
                workspace, event, deliveries
            )
        )
        all_deliveries = [*deliveries, *checkpoint_deliveries]
        records.extend(checkpoint_records)
        records.extend(("workspace_delivery", item["id"], item) for item in all_deliveries)
        records.extend(self._due_records(add=all_deliveries))
        self._annotate_workspace_event_retention(
            records, event.event_id, deliveries, operation_id
        )
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
                message if kind == "workspace_message_state" and record_id == self._workspace_message_record_id(event_id) else value,
            )
            for kind, record_id, value in records
        ]
        outcome = self._public_workspace_message(message)
        committed = self.store.commit_operation(operation_id, digest, outcome, records)
        self._workspace_changed(
            workspace_id,
            conversation_id=conversation_id,
            resource_kind="thread",
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

    def _accept_workspace_event(
        self,
        wire: WorkspaceWirePayload,
        *,
        drain_pending: bool = True,
        history_checkpoint_digests: set[str] | None = None,
    ) -> bool:
        try:
            raw_value = json.loads(wire.document)
            if not isinstance(raw_value, dict):
                return False
            manifest_digest = raw_value.get("manifest_digest")
            channel_digest = raw_value.get("channel_digest")
            if not isinstance(manifest_digest, str) or not (
                channel_digest is None or isinstance(channel_digest, str)
            ):
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
            channel = (
                self._workspace_channel_by_digest(channel_digest)
                if isinstance(channel_digest, str)
                else None
            )
            if manifest is None or (
                isinstance(channel_digest, str) and channel is None
            ):
                self._store_pending_workspace_event(wire, "missing_controls")
                return False
            direct_member_ids = (
                untrusted_audience
                if channel_digest is None and isinstance(untrusted_audience, list)
                else None
            )
            event = verify_workspace_event(
                wire.document,
                manifest=manifest,
                channel=channel,
                direct_member_ids=direct_member_ids,
            )
            if event.workspace_id != wire.workspace_id:
                return False
            if workspace.get("state") not in {"active", "incomplete_sync"}:
                return False
            if event.channel_digest is None:
                current_manifest = self._workspace_current_manifest(workspace)
                if (
                    len(event.audience_member_ids) != 2
                    or workspace.get("local_member_id")
                    not in event.audience_member_ids
                    or any(
                        (member := find_member(current_manifest, member_id)) is None
                        or member.status != "active"
                        for member_id in event.audience_member_ids
                    )
                ):
                    return False
                if event.thread_root is not None:
                    try:
                        checked_root, _root_kind, _root_conversation = (
                            self._workspace_thread_context(workspace, event.thread_root)
                        )
                    except (ContactNotApproved, ValidationError):
                        return False
                    if checked_root.get("conversation_id") != event.conversation_id:
                        return False
            elif event.audience_member_ids:
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
            if event.event_type == "message" and event.thread_root is not None:
                root_message = self.store.get(
                    "workspace_message_state",
                    self._workspace_message_record_id(event.thread_root),
                )
                root_event = self.store.get(
                    "workspace_event", self._workspace_event_record_id(event.thread_root)
                )
                if root_message is None or root_event is None:
                    self._store_pending_workspace_event(wire, "missing_thread_root")
                    return False
                if (
                    root_event.get("event_type", "message") != "message"
                    or root_event.get("thread_root") is not None
                    or root_message.get("workspace_id") != event.workspace_id
                    or root_message.get("conversation_id") != event.conversation_id
                    or self.store.get(
                        "workspace_message_hidden",
                        self.store.opaque_id(
                            "workspace-message-hidden",
                            event.workspace_id,
                            event.thread_root,
                        ),
                    )
                    is not None
                ):
                    return False
                try:
                    authorized_root, _root_kind, _root_conversation = (
                        self._workspace_thread_context(workspace, event.thread_root)
                    )
                except (ContactNotApproved, ValidationError):
                    return False
                if authorized_root.get("conversation_id") != event.conversation_id:
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
            pruned_event = self.store.get(
                "workspace_event_tombstone",
                self._workspace_event_tombstone_id(
                    event.workspace_id, event.event_id
                ),
            )
            if pruned_event is not None:
                if pruned_event.get("digest") == event.digest:
                    return True
                workspace["state"] = "forked"
                workspace["security_error"] = "pruned_event_id_equivocation"
                self.store.put(
                    "workspace", self._workspace_record_id(workspace["id"]), workspace
                )
                self._workspace_changed(event.workspace_id, resource_kind="security")
                return False
            current = self._workspace_current_manifest(workspace)
            current_device = find_device(current, event.author_device_id)
            if current_device is None or current_device[0].status != "active":
                # A forwarder cannot revive an inactive signer.  History may
                # cross the removal boundary only when the complete canonical
                # chain supplied in this response terminates at a checkpoint
                # explicitly committed by the applicable removal control.
                if (
                    event.channel_digest is None
                    or history_checkpoint_digests is None
                    or event.digest not in history_checkpoint_digests
                ):
                    head_id = self._workspace_stream_head_id(
                        event.workspace_id,
                        event.conversation_id,
                        event.author_device_id,
                    )
                    head = self.store.get("workspace_stream_coverage", head_id) or {
                        "workspace_id": event.workspace_id,
                        "conversation_id": event.conversation_id,
                        "device_id": event.author_device_id,
                        "high_water": 0,
                        "head_digest": None,
                        "channel_version": 0,
                        "retained_floor": 1,
                        "gaps": [],
                    }
                    gaps = list(head.get("gaps", ()))
                    gap = [event.sequence, event.sequence]
                    if gap not in gaps and len(gaps) < MAX_HISTORY_RANGES:
                        gaps.append(gap)
                        gaps.sort()
                        head["gaps"] = gaps
                        self.store.put("workspace_stream_coverage", head_id, head)
                    return False
            author = find_member(manifest, event.author_member_id)
            if (
                author is None
                or author.status != "active"
                or (
                    event.event_type == "message"
                    and
                    event.channel_digest is not None
                    and not self._posting_allowed(manifest, author)
                )
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
                if channel is None:
                    self._store_pending_workspace_event(wire, "missing_predecessor")
                    return False
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
            target_message: dict[str, Any] | None = None
            if event.event_type != "message":
                target_message = self.store.get(
                    "workspace_message_state",
                    self._workspace_message_record_id(event.target_event_id),
                )
                target_event = self.store.get(
                    "workspace_event", self._workspace_event_record_id(event.target_event_id)
                )
                if target_message is None or target_event is None:
                    self._store_pending_workspace_event(wire, "missing_mutation_target")
                    return False
                if (
                    target_message.get("workspace_id") != event.workspace_id
                    or target_message.get("conversation_id") != event.conversation_id
                    or target_event.get("event_type", "message") != "message"
                    or target_event.get("thread_root") != event.thread_root
                ):
                    return False
                try:
                    if isinstance(event.thread_root, str):
                        authorized_root, _root_kind, _root_conversation = (
                            self._workspace_thread_context(workspace, event.thread_root)
                        )
                        if (
                            authorized_root.get("conversation_id")
                            != event.conversation_id
                        ):
                            return False
                    elif self.store.get(
                        "workspace_thread",
                        self._workspace_thread_record_id(
                            event.workspace_id, str(event.target_event_id)
                        ),
                    ) is not None:
                        self._workspace_thread_context(
                            workspace, str(event.target_event_id)
                        )
                except (ContactNotApproved, ValidationError):
                    return False
                if target_message.get("mutation_frozen"):
                    return False
                deletion_revision = target_message.get("deletion_revision")
                if target_message.get("deleted") and (
                    event.event_type == "reaction"
                    or not isinstance(deletion_revision, int)
                    or not isinstance(event.revision, int)
                    or event.revision > deletion_revision
                ):
                    return False
                if (
                    event.event_type in {"edit", "delete"}
                    and target_message.get("author_member_id") != event.author_member_id
                ):
                    return False
                _current_manifest, current_channel, current_audience = (
                    self._workspace_mutation_context(workspace, target_event)
                )
                if current_channel is None:
                    if event.audience_member_ids != current_audience:
                        return False
                elif current_audience:
                    old_audience = set(target_event.get("audience_member_ids", ()))
                    if (
                        not event.audience_member_ids
                        or not set(event.audience_member_ids).issubset(old_audience)
                        or workspace.get("local_member_id") not in event.audience_member_ids
                        or event.author_member_id not in event.audience_member_ids
                    ):
                        return False
                elif event.audience_member_ids:
                    return False
                if event.event_type == "reaction":
                    assert event.reaction_emoji is not None
                    reaction_id = self._workspace_reaction_record_id(
                        event.workspace_id,
                        str(event.target_event_id),
                        event.author_member_id,
                        event.reaction_emoji,
                    )
                    reaction_state = self.store.get(
                        "workspace_reaction_state", reaction_id
                    )
                    if reaction_state is not None and reaction_state.get("mutation_frozen"):
                        return False
                    current_revision = (
                        int(reaction_state.get("revision", 0)) if reaction_state else 0
                    )
                else:
                    current_revision = int(target_message.get("revision", 0))
                assert event.base_revision is not None
                if event.base_revision > current_revision:
                    self._store_pending_workspace_event(wire, "missing_mutation_base")
                    return False
            records, _message = self._append_workspace_event_records(
                workspace,
                event,
                direction="inbound",
                author_display_name=author.display_name,
            )
            if event.event_type != "message":
                assert target_message is not None
                mutation_records, _updated_message = self._workspace_mutation_records(
                    event, target_message
                )
                records.extend(mutation_records)
                event_record = next(
                    value
                    for kind, record_id, value in records
                    if kind == "workspace_event"
                    and record_id == self._workspace_event_record_id(event.event_id)
                )
                records.extend(
                    self._workspace_mutation_index_records(
                        workspace, event, event_record, _updated_message
                    )
                )
            elif event.thread_root is not None:
                # Reply unread state belongs to the thread summary, never the
                # containing channel or DM badge.
                pass
            elif event.channel_digest is None:
                direct_id = self._workspace_direct_record_id(event.conversation_id)
                direct = self.store.get("workspace_direct", direct_id)
                current_manifest = self._workspace_current_manifest(workspace)
                peer_member_id = next(
                    member_id
                    for member_id in event.audience_member_ids
                    if member_id != workspace["local_member_id"]
                )
                peer = find_member(current_manifest, peer_member_id)
                now = time.time()
                if direct is None:
                    direct = {
                        "id": event.conversation_id,
                        "workspace_id": event.workspace_id,
                        "participant_member_ids": list(
                            event.audience_member_ids
                        ),
                        "peer_display_name": (
                            peer.display_name if peer is not None else "Member"
                        ),
                        "hidden": False,
                        "unread_count": 0,
                        "created_at": now,
                        "updated_at": now,
                    }
                elif direct.get("participant_member_ids") != list(
                    event.audience_member_ids
                ):
                    return False
                direct["hidden"] = False
                direct["unread_count"] = int(direct.get("unread_count", 0)) + 1
                direct["updated_at"] = now
                records.append(("workspace_direct", direct_id, direct))
            else:
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
            if drain_pending:
                self._drain_workspace_pending_events(event.workspace_id)
            self._workspace_changed(
                event.workspace_id,
                conversation_id=event.conversation_id,
                resource_kind=(
                    "message" if event.event_type == "message" else "message_mutation"
                ),
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
            newly_inactive_member_ids = {
                member.member_id
                for member in current.members
                if member.status == "active"
                and (
                    (next_member := find_member(checked, member.member_id)) is None
                    or next_member.status != "active"
                )
            }
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
            changed_member_ids = [
                member.member_id
                for member in current.members
                if (
                    (next_member := find_member(checked, member.member_id)) is not None
                    and (
                        next_member.role != member.role
                        or next_member.status != member.status
                    )
                )
            ]
            admin_request_updates = self._admin_request_state_records_after_manifest(
                workspace["id"],
                "",
                changed_member_ids[0] if len(changed_member_ids) == 1 else None,
            )
            cancelled_records: list[tuple[str, str, dict[str, Any]]] = []
            cancelled_ids: set[str] = set()
            for member_id in newly_inactive_member_ids:
                member_records, member_cancelled_ids = (
                    self._cancel_workspace_member_deliveries(
                        workspace["id"], member_id
                    )
                )
                cancelled_records.extend(member_records)
                cancelled_ids.update(member_cancelled_ids)
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
                    *admin_request_updates,
                    *cancelled_records,
                    *self._due_records(remove=cancelled_ids),
                ]
            )
            network = getattr(self, "network", None)
            if network is not None and cancelled_ids:
                network.cancel_outbound(cancelled_ids)
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
                elif wire.kind == "workspace_admin_request":
                    applied = self._receive_workspace_admin_request(wire)
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
            if self._accept_workspace_event(wire, drain_pending=False):
                self.store.delete("workspace_pending_event", pending["id"])
        self._clear_workspace_sync_issue_if_resolved(workspace_id)

    def _advance_workspace_search_rebuild(
        self, workspace: dict[str, Any], max_events: int = SEARCH_REBUILD_BATCH
    ) -> dict[str, Any]:
        """Resume a metadata-bounded search migration without startup scanning."""

        workspace_id = str(workspace["id"])
        state_id = self._workspace_search_state_id(workspace_id)
        state = self.store.get("workspace_search_state", state_id)
        if state is None:
            state = self._workspace_search_base_state(workspace)
            self.store.put("workspace_search_state", state_id, state)
        if state.get("status") != "rebuilding":
            if state.get("status") == "ready":
                retention = self.store.get(
                    "workspace_retention_index",
                    self._workspace_retention_index_id(workspace_id),
                ) or {}
                retained_count = int(retention.get("count", 0))
                if (
                    int(state.get("target_events", 0)) != retained_count
                    or int(state.get("indexed_events", 0)) != retained_count
                ):
                    state["target_events"] = retained_count
                    state["indexed_events"] = retained_count
                    state["updated_at"] = time.time()
                    self.store.put("workspace_search_state", state_id, state)
            return state
        if (
            isinstance(max_events, bool)
            or not isinstance(max_events, int)
            or not 1 <= max_events <= SEARCH_REBUILD_BATCH
        ):
            raise ValidationError("Workspace search rebuild batch is invalid")
        retention = self.store.get(
            "workspace_retention_index",
            self._workspace_retention_index_id(workspace_id),
        ) or {}
        staged: dict[tuple[str, str], dict[str, Any]] = {
            ("workspace_search_state", state_id): dict(state)
        }
        state = staged[("workspace_search_state", state_id)]
        state["target_events"] = int(retention.get("count", 0))
        page_id = state.get("rebuild_page_id")
        offset = int(state.get("rebuild_offset", 0))
        processed = 0
        while isinstance(page_id, str) and processed < max_events:
            page = self.store.get("workspace_retention_index", page_id)
            if page is None or page.get("workspace_id") != workspace_id:
                state["status"] = "incomplete"
                state["incomplete_reason"] = "retention_page_unavailable"
                page_id = None
                break
            entries = page.get("entries", ())
            if not isinstance(entries, list) or offset > len(entries):
                state["status"] = "incomplete"
                state["incomplete_reason"] = "retention_page_invalid"
                page_id = None
                break
            position = len(entries) - 1 - offset
            while position >= 0 and processed < max_events:
                entry = entries[position]
                processed += 1
                offset += 1
                state["indexed_events"] = int(state.get("indexed_events", 0)) + 1
                if entry.get("event_type") == "message":
                    event_id = entry.get("event_id")
                    if isinstance(event_id, str):
                        message = self.store.get(
                            "workspace_message_state",
                            self._workspace_message_record_id(event_id),
                        )
                        if message is not None:
                            hidden = self.store.get(
                                "workspace_message_hidden",
                                self.store.opaque_id(
                                    "workspace-message-hidden", workspace_id, event_id
                                ),
                            )
                            self._workspace_search_document_records(
                                workspace,
                                category=(
                                    "thread"
                                    if isinstance(message.get("thread_root"), str)
                                    else "message"
                                ),
                                entity_id=event_id,
                                text=str(message.get("text", "")),
                                active=hidden is None and not bool(message.get("deleted")),
                                sort_at=float(message.get("created_at", 0)),
                                conversation_id=str(message.get("conversation_id", "")),
                                thread_root_id=(
                                    str(message["thread_root"])
                                    if isinstance(message.get("thread_root"), str)
                                    else None
                                ),
                                staged=staged,
                            )
                position -= 1
            if position < 0:
                page_id = page.get("previous_page")
                offset = 0
        state = staged[("workspace_search_state", state_id)]
        state["rebuild_page_id"] = page_id
        state["rebuild_offset"] = offset
        state["updated_at"] = time.time()
        if page_id is None and state.get("status") == "rebuilding":
            state["status"] = "ready"
            state["indexed_events"] = int(state.get("target_events", 0))
            state.pop("incomplete_reason", None)
        self.store.put_many(
            (kind, record_id, value)
            for (kind, record_id), value in staged.items()
        )
        return state

    @staticmethod
    def _workspace_search_snippet(text: str, limit: int = 240) -> str:
        collapsed = " ".join(str(text).split())
        return collapsed if len(collapsed) <= limit else f"{collapsed[: limit - 1].rstrip()}…"

    def _workspace_search_result(
        self,
        workspace: dict[str, Any],
        document: dict[str, Any],
        query_tokens: tuple[str, ...],
        query_token_ids: set[str],
        scope_categories: set[str],
        visibility_cache: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        category = document.get("category")
        if category not in scope_categories or document.get("active") is not True:
            return None
        if not query_token_ids.issubset(set(document.get("token_ids", ()))):
            return None
        entity_id = document.get("entity_id")
        if not isinstance(entity_id, str):
            return None
        if category in {"message", "thread"}:
            message = self.store.get(
                "workspace_message_state", self._workspace_message_record_id(entity_id)
            )
            if (
                message is None
                or message.get("workspace_id") != workspace.get("id")
                or message.get("deleted")
                or self.store.get(
                    "workspace_message_hidden",
                    self.store.opaque_id(
                        "workspace-message-hidden", workspace["id"], entity_id
                    ),
                )
                is not None
                or not self._workspace_message_is_visible(
                    workspace, message, visibility_cache
                )
            ):
                return None
            retention_days = workspace.get("retention_days", 90)
            if retention_days is not None and float(message.get("created_at", 0)) < (
                time.time() - int(retention_days) * 24 * 60 * 60
            ):
                return None
            current_tokens = set(
                tokenize_workspace_search_text(str(message.get("text", "")))
            )
            if not set(query_tokens).issubset(current_tokens):
                return None
            conversation_id = str(message.get("conversation_id", ""))
            try:
                conversation_kind, conversation = self._require_workspace_conversation(
                    workspace["id"], conversation_id
                )
                thread_root = message.get("thread_root")
                if isinstance(thread_root, str):
                    root, _root_kind, _root_conversation = self._workspace_thread_context(
                        workspace, thread_root, visibility_cache=visibility_cache
                    )
                    if root.get("conversation_id") != conversation_id:
                        return None
            except (ContactNotApproved, ValidationError):
                return None
            conversation_model = self._workspace_thread_conversation_model(
                workspace, conversation_kind, conversation
            )
            current_author = next(
                (
                    item
                    for item in workspace.get("members", ())
                    if item.get("id") == message.get("author_member_id")
                ),
                None,
            )
            return {
                "id": entity_id,
                "kind": category,
                "title": str(
                    current_author.get("display_name")
                    if current_author is not None
                    else message.get("author_display_name", "Member")
                ),
                "snippet": self._workspace_search_snippet(str(message.get("text", ""))),
                "created_at": float(message.get("created_at", 0)),
                "conversation": conversation_model,
                "event_id": entity_id,
                "is_reply": isinstance(message.get("thread_root"), str),
                "thread_root_id": message.get("thread_root"),
                "_sort": (
                    0 if category == "message" else 1,
                    -float(message.get("created_at", 0)),
                    entity_id,
                ),
            }
        if category == "person":
            member = next(
                (
                    item
                    for item in workspace.get("members", ())
                    if item.get("id") == entity_id and item.get("status") == "active"
                ),
                None,
            )
            if member is None or not set(query_tokens).issubset(
                set(tokenize_workspace_search_text(str(member.get("display_name", ""))))
            ):
                return None
            return {
                "id": entity_id,
                "kind": "person",
                "title": str(member.get("display_name", "Member")),
                "snippet": f"{member.get('role', 'member')} · {member.get('short_id', _short_id(entity_id))}",
                "member_id": entity_id,
                "_sort": (2, 0, entity_id),
            }
        channel = self.store.get(
            "workspace_channel", self._workspace_channel_record_id(entity_id)
        )
        local_member_id = str(workspace.get("local_member_id", ""))
        former_archive = workspace.get("state") in {"left", "removed", "closed", "forked"}
        if (
            channel is None
            or channel.get("workspace_id") != workspace.get("id")
            or channel.get("state") not in {"active", "archived", "leaving", "left"}
            or (
                channel.get("visibility") == "private"
                and local_member_id not in channel.get("member_ids", ())
                and not former_archive
            )
            or not set(query_tokens).issubset(
                set(
                    tokenize_workspace_search_text(
                        f"{channel.get('name', '')} {channel.get('topic', '')}"
                    )
                )
            )
        ):
            return None
        public_channel = self._public_workspace_channel(channel)
        return {
            "id": entity_id,
            "kind": "channel",
            "title": f"#{public_channel.get('display_name') or public_channel.get('name', 'channel')}",
            "snippet": self._workspace_search_snippet(
                str(
                    channel.get("topic")
                    or (
                        "Private channel"
                        if channel.get("visibility") == "private"
                        else "Public channel"
                    )
                )
            ),
            "conversation": {
                "id": entity_id,
                "kind": "channel",
                "name": str(public_channel.get("display_name") or channel.get("name", "channel")),
                "visibility": str(channel.get("visibility", "public")),
                "state": str(channel.get("state", "active")),
            },
            "_sort": (3, 0, entity_id),
        }

    def search_workspace(
        self,
        workspace_id: Any,
        query: Any,
        scope: Any = "all",
        cursor: Any = None,
        limit: Any = SEARCH_PAGE_DEFAULT,
    ) -> dict[str, Any]:
        workspace = self._require_workspace(workspace_id)
        if workspace.get("state") not in {
            "active", "incomplete_sync", "leaving", "left", "removed", "closed", "forked"
        }:
            raise ContactNotApproved("Workspace search is unavailable in this state")
        if (
            not isinstance(query, str)
            or not 1 <= len(query) <= SEARCH_QUERY_MAX_CHARS
            or len(query.encode("utf-8")) > SEARCH_QUERY_MAX_BYTES
        ):
            raise ValidationError("Workspace search query is invalid")
        normalized_query = normalize_workspace_search_text(query).strip()
        tokens = tokenize_workspace_search_text(query)
        if (
            len(normalized_query) < SEARCH_TOKEN_MIN_CHARS
            or not tokens
            or len(tokens) > SEARCH_QUERY_MAX_TOKENS
        ):
            raise ValidationError(
                "Workspace search requires one to eight tokens of 2–64 characters"
            )
        scope_map = {
            "all": {"message", "thread", "person", "channel"},
            "messages": {"message"},
            "threads": {"thread"},
            "people": {"person"},
            "channels": {"channel"},
        }
        if scope not in scope_map:
            raise ValidationError("Workspace search scope is invalid")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= SEARCH_PAGE_MAX
        ):
            raise ValidationError("Workspace search page size is invalid")

        state = self._advance_workspace_search_rebuild(workspace)
        token_ids = [
            self._workspace_search_token_id(workspace_id, token) for token in tokens
        ]
        token_indexes: list[tuple[int, str, dict[str, Any]]] = []
        for token_id in token_ids:
            index = self.store.get("workspace_search_index", token_id)
            if index is None:
                token_indexes = []
                break
            token_indexes.append((int(index.get("count", 0)), token_id, index))
        selected_token_id: str | None = None
        selected_index: dict[str, Any] | None = None
        if token_indexes:
            _count, selected_token_id, selected_index = min(
                token_indexes, key=lambda item: (item[0], item[1])
            )
        query_digest = self.store.opaque_id(
            "workspace-search-query", workspace_id, "\x1f".join(tokens)
        )
        filter_digest = self.store.opaque_id(
            "workspace-search-filter", workspace_id, str(scope)
        )
        head_page = selected_index.get("head_page") if selected_index else None
        result_offset = 0
        if cursor is not None:
            if not isinstance(cursor, str):
                raise ValidationError("Workspace search cursor is invalid")
            value = self.store.open_cursor(cursor)
            expected = {
                "v": 1,
                "view": "workspace_search",
                "workspace_id": workspace_id,
                "query_digest": query_digest,
                "filter_digest": filter_digest,
                "authorization_generation": int(workspace.get("authorization_generation", 1)),
                "retention_generation": int(workspace.get("retention_generation", 1)),
                "search_generation": int(state.get("search_generation", 1)),
                "token_shard_id": selected_token_id,
                "page_id": head_page,
            }
            if any(value.get(key) != expected_value for key, expected_value in expected.items()):
                raise StaleCursor("Workspace search cursor is stale")
            result_offset = value.get("offset")
            if (
                isinstance(result_offset, bool)
                or not isinstance(result_offset, int)
                or result_offset < 0
            ):
                raise ValidationError("Workspace search cursor is invalid")

        candidates: list[dict[str, Any]] = []
        seen_documents: set[str] = set()
        page_id = head_page
        pages_opened = 0
        candidate_limit_reached = False
        while (
            isinstance(page_id, str)
            and pages_opened < SEARCH_SHARD_PAGE_MAX
            and len(candidates) < SEARCH_CANDIDATE_MAX
        ):
            page = self.store.get("workspace_search_index", page_id)
            if page is None or page.get("workspace_id") != workspace_id:
                raise ValidationError("Workspace search shard is unavailable")
            entries = page.get("entries", ())
            if not isinstance(entries, list) or len(entries) > SEARCH_TOKEN_PAGE_ENTRIES:
                raise ValidationError("Workspace search shard is invalid")
            for entry in reversed(entries):
                document_id = entry.get("document_id")
                if not isinstance(document_id, str) or document_id in seen_documents:
                    continue
                seen_documents.add(document_id)
                document = self.store.get("workspace_search_document", document_id)
                if (
                    document is None
                    or int(document.get("generation", 0))
                    != int(entry.get("document_generation", -1))
                ):
                    continue
                candidates.append(document)
                if len(candidates) >= SEARCH_CANDIDATE_MAX:
                    candidate_limit_reached = True
                    break
            page_id = page.get("previous_page")
            pages_opened += 1
        if isinstance(page_id, str):
            candidate_limit_reached = True

        visibility_cache: dict[str, dict[str, Any]] = {}
        query_token_id_set = set(token_ids)
        results = [
            result
            for document in candidates
            if (
                result := self._workspace_search_result(
                    workspace,
                    document,
                    tokens,
                    query_token_id_set,
                    scope_map[str(scope)],
                    visibility_cache,
                )
            )
            is not None
        ]
        results.sort(key=lambda item: item["_sort"])
        page_results = results[result_offset : result_offset + limit]
        for item in page_results:
            item.pop("_sort", None)
        next_offset = result_offset + len(page_results)
        next_cursor = None
        if next_offset < len(results):
            next_cursor = self.store.seal_cursor(
                {
                    "v": 1,
                    "view": "workspace_search",
                    "workspace_id": workspace_id,
                    "query_digest": query_digest,
                    "filter_digest": filter_digest,
                    "authorization_generation": int(workspace.get("authorization_generation", 1)),
                    "retention_generation": int(workspace.get("retention_generation", 1)),
                    "search_generation": int(state.get("search_generation", 1)),
                    "token_shard_id": selected_token_id,
                    "page_id": head_page,
                    "offset": next_offset,
                }
            )
        if state.get("status") == "rebuilding":
            coverage = "indexing"
        elif int(state.get("pruned_count", 0)) > 0:
            coverage = "pruned"
        elif (
            state.get("status") != "ready"
            or state.get("growth_limited")
            or int(state.get("truncated_documents", 0)) > 0
            or candidate_limit_reached
        ):
            coverage = "incomplete"
        else:
            coverage = "retained"
        return {
            "results": page_results,
            "next_cursor": next_cursor,
            "scope": scope,
            "coverage": coverage,
            "indexing": state.get("status") == "rebuilding",
            "indexed_events": int(state.get("indexed_events", 0)),
            "target_events": int(state.get("target_events", 0)),
            "candidate_count": len(candidates),
            "candidate_limit_reached": candidate_limit_reached,
            "shard_pages_opened": pages_opened,
            "search_generation": int(state.get("search_generation", 1)),
        }

    def list_workspace_thread_messages(
        self,
        workspace_id: Any,
        thread_root_id: Any,
        cursor: Any = None,
        limit: Any = MESSAGE_PAGE_DEFAULT,
    ) -> dict[str, Any]:
        workspace = self._require_workspace(workspace_id)
        visibility_cache: dict[str, dict[str, Any]] = {}
        root, conversation_kind, conversation = self._workspace_thread_context(
            workspace, thread_root_id, visibility_cache=visibility_cache
        )
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MESSAGE_PAGE_MAX:
            raise ValidationError("Workspace thread page size is invalid")
        index_id = self._workspace_thread_index_id(workspace_id, thread_root_id)
        index = self.store.get("workspace_thread_index", index_id)
        high_water = int(index.get("high_water", 0)) if index else 0
        page_id = index.get("head_page") if index else None
        offset = 0
        if cursor is not None:
            if not isinstance(cursor, str):
                raise ValidationError("Workspace thread cursor is invalid")
            value = self.store.open_cursor(cursor)
            expected = {
                "v": 1,
                "workspace_id": workspace_id,
                "thread_root_id": thread_root_id,
                "authorization_digest": self._workspace_thread_authorization_digest(
                    workspace
                ),
                "authorization_generation": int(
                    workspace.get("authorization_generation", 1)
                ),
                "retention_generation": int(workspace.get("retention_generation", 1)),
                "high_water": high_water,
            }
            if any(value.get(key) != item for key, item in expected.items()):
                raise StaleCursor("Workspace thread cursor is stale")
            page_id = value.get("page_id")
            offset = value.get("offset")
            if not isinstance(page_id, str) or isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
                raise ValidationError("Workspace thread cursor is invalid")
        replies: list[dict[str, Any]] = []
        next_page: str | None = None
        next_offset = 0
        while isinstance(page_id, str) and len(replies) < limit:
            page = self.store.get("workspace_thread_index", page_id)
            if (
                page is None
                or page.get("workspace_id") != workspace_id
                or page.get("root_event_id") != thread_root_id
                or page.get("conversation_id") != root.get("conversation_id")
            ):
                raise ValidationError("Workspace thread page is unavailable")
            entries = page.get("entries", [])
            if not isinstance(entries, list) or offset > len(entries):
                raise ValidationError("Workspace thread page is invalid")
            position = len(entries) - 1 - offset
            while position >= 0 and len(replies) < limit:
                entry = entries[position]
                reply = self.store.get(
                    "workspace_message_state", entry.get("message_record_id")
                )
                hidden = self.store.get(
                    "workspace_message_hidden",
                    self.store.opaque_id(
                        "workspace-message-hidden", workspace_id, entry.get("event_id", "")
                    ),
                )
                if (
                    reply is not None
                    and hidden is None
                    and reply.get("thread_root") == thread_root_id
                    and reply.get("conversation_id") == root.get("conversation_id")
                    and self._workspace_message_is_visible(
                        workspace, reply, visibility_cache
                    )
                ):
                    replies.append(self._public_workspace_message(reply))
                position -= 1
                offset += 1
            if len(replies) >= limit and position >= 0:
                next_page = page_id
                next_offset = offset
                break
            page_id = page.get("previous_page")
            offset = 0
            if len(replies) >= limit and isinstance(page_id, str):
                next_page = page_id
                break
        next_cursor = None
        if next_page is not None:
            next_cursor = self.store.seal_cursor(
                {
                    "v": 1,
                    "workspace_id": workspace_id,
                    "thread_root_id": thread_root_id,
                    "authorization_digest": self._workspace_thread_authorization_digest(
                        workspace
                    ),
                    "authorization_generation": int(
                        workspace.get("authorization_generation", 1)
                    ),
                    "retention_generation": int(
                        workspace.get("retention_generation", 1)
                    ),
                    "high_water": high_water,
                    "page_id": next_page,
                    "offset": next_offset,
                }
            )
        replies.reverse()
        return {
            "root": self._public_workspace_message(root),
            "replies": replies,
            "next_cursor": next_cursor,
            "high_water": high_water,
            "unread_count": int(
                (
                    self.store.get(
                        "workspace_thread",
                        self._workspace_thread_record_id(workspace_id, thread_root_id),
                    )
                    or {}
                ).get("unread_count", 0)
            ),
            "conversation": self._workspace_thread_conversation_model(
                workspace, conversation_kind, conversation
            ),
        }

    def _workspace_thread_conversation_model(
        self,
        workspace: dict[str, Any],
        conversation_kind: str,
        conversation: dict[str, Any],
    ) -> dict[str, Any]:
        if conversation_kind == "direct":
            public = self._public_workspace_direct(conversation)
            return {
                "id": public["id"],
                "kind": "direct",
                "name": public["peer_display_name"],
                "visibility": "direct",
                "state": public["state"],
            }
        return {
            "id": conversation["id"],
            "kind": "channel",
            "name": conversation.get("name", "channel"),
            "visibility": conversation.get("visibility", "public"),
            "state": conversation.get("state", "active"),
        }

    def list_workspace_threads(
        self,
        workspace_id: Any,
        cursor: Any = None,
        limit: Any = MESSAGE_PAGE_DEFAULT,
    ) -> dict[str, Any]:
        workspace = self._require_workspace(workspace_id)
        visibility_cache: dict[str, dict[str, Any]] = {}
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MESSAGE_PAGE_MAX:
            raise ValidationError("Workspace thread activity page size is invalid")
        activity = self.store.get(
            "workspace_thread_activity_index",
            self._workspace_thread_activity_id(workspace_id),
        ) or {"entries": {}, "high_water": 0}
        high_water = int(activity.get("high_water", 0))
        offset = 0
        if cursor is not None:
            if not isinstance(cursor, str):
                raise ValidationError("Workspace thread activity cursor is invalid")
            value = self.store.open_cursor(cursor)
            expected = {
                "v": 1,
                "workspace_id": workspace_id,
                "authorization_digest": self._workspace_thread_authorization_digest(
                    workspace
                ),
                "authorization_generation": int(
                    workspace.get("authorization_generation", 1)
                ),
                "retention_generation": int(workspace.get("retention_generation", 1)),
                "high_water": high_water,
            }
            if any(value.get(key) != item for key, item in expected.items()):
                raise StaleCursor("Workspace thread activity cursor is stale")
            offset = value.get("offset")
            if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
                raise ValidationError("Workspace thread activity cursor is invalid")
        entries = sorted(
            (
                item
                for item in activity.get("entries", {}).values()
                if isinstance(item, dict)
            ),
            key=lambda item: (int(item.get("position", 0)), str(item.get("root_event_id", ""))),
            reverse=True,
        )
        results: list[dict[str, Any]] = []
        scanned = offset
        while scanned < len(entries) and len(results) < limit:
            entry = entries[scanned]
            scanned += 1
            root_event_id = str(entry.get("root_event_id", ""))
            try:
                root, kind, conversation = self._workspace_thread_context(
                    workspace,
                    root_event_id,
                    visibility_cache=visibility_cache,
                )
            except (ContactNotApproved, ValidationError):
                continue
            summary = self.store.get(
                "workspace_thread",
                self._workspace_thread_record_id(workspace_id, root_event_id),
            )
            if summary is None or summary.get("conversation_id") != root.get("conversation_id"):
                continue
            results.append(
                {
                    "root": self._public_workspace_message(root),
                    "conversation": self._workspace_thread_conversation_model(
                        workspace, kind, conversation
                    ),
                    "reply_count": int(summary.get("reply_count", 0)),
                    "unread_count": int(summary.get("unread_count", 0)),
                    "high_water": int(summary.get("high_water", 0)),
                    "updated_at": float(summary.get("updated_at", 0)),
                }
            )
        next_cursor = None
        if scanned < len(entries):
            next_cursor = self.store.seal_cursor(
                {
                    "v": 1,
                    "workspace_id": workspace_id,
                    "authorization_digest": self._workspace_thread_authorization_digest(
                        workspace
                    ),
                    "authorization_generation": int(
                        workspace.get("authorization_generation", 1)
                    ),
                    "retention_generation": int(
                        workspace.get("retention_generation", 1)
                    ),
                    "high_water": high_water,
                    "offset": scanned,
                }
            )
        return {
            "threads": results,
            "next_cursor": next_cursor,
            "high_water": high_water,
            "unread_count": self._workspace_thread_unread_count(workspace),
        }

    def list_workspace_messages(
        self,
        workspace_id: Any,
        channel_id: Any,
        cursor: Any = None,
        limit: Any = MESSAGE_PAGE_DEFAULT,
    ) -> dict[str, Any]:
        workspace = self._require_workspace(workspace_id)
        visibility_cache: dict[str, dict[str, Any]] = {}
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
        self._require_workspace_conversation(workspace_id, channel_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MESSAGE_PAGE_MAX:
            raise ValidationError("Workspace message page size is invalid")
        index_id = self._workspace_index_record_id(workspace_id, channel_id)
        index = self.store.get("workspace_conversation_index", index_id)
        if index is None:
            return {
                "messages": [],
                "next_cursor": None,
                "high_water": 0,
                "history_status": "complete",
                "pruned_count": 0,
                "permanent_gaps": [],
            }
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
                raise StaleCursor("Workspace message cursor is stale")
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
                if (
                    message is not None
                    and hidden is None
                    and self._workspace_message_is_visible(
                        workspace, message, visibility_cache
                    )
                ):
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
            "history_status": (
                "permanent_gap"
                if index.get("permanent_gaps")
                else "pruned"
                if int(index.get("pruned_count", 0)) > 0
                else "complete"
            ),
            "pruned_count": int(index.get("pruned_count", 0)),
            "permanent_gaps": list(index.get("permanent_gaps", ()))[:32],
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
        workspace = self._require_workspace(workspace_id)
        conversation_kind, conversation = self._require_workspace_conversation(
            workspace_id, channel_id
        )
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
        conversation["unread_count"] = max(0, maximum - high_water)
        conversation["updated_at"] = time.time()
        outcome = {
            "workspace_id": workspace_id,
            "conversation_id": channel_id,
            "high_water": high_water,
        }
        if conversation_kind == "channel":
            outcome["channel_id"] = channel_id
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [
                (
                    (
                        "workspace_channel"
                        if conversation_kind == "channel"
                        else "workspace_direct"
                    ),
                    (
                        self._workspace_channel_record_id(channel_id)
                        if conversation_kind == "channel"
                        else self._workspace_direct_record_id(channel_id)
                    ),
                    conversation,
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

    def list_workspace_message_revisions(
        self,
        workspace_id: Any,
        event_id: Any,
        cursor: Any = None,
        limit: Any = MESSAGE_PAGE_DEFAULT,
    ) -> dict[str, Any]:
        workspace = self._require_workspace(workspace_id)
        if not isinstance(event_id, str):
            raise ValidationError("Workspace message ID is invalid")
        message = self.store.get(
            "workspace_message_state", self._workspace_message_record_id(event_id)
        )
        if message is None:
            if self._workspace_event_id_is_retired(workspace_id, event_id):
                raise HistoryPruned("Workspace message history was pruned locally")
            raise ValidationError("Workspace message does not exist")
        if not self._workspace_message_is_visible(workspace, message):
            raise ContactNotApproved("Workspace message history is unavailable")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MESSAGE_PAGE_MAX
        ):
            raise ValidationError("Workspace revision page size is invalid")
        index = self.store.get(
            "workspace_revision_index",
            self._workspace_revision_index_id(workspace_id, event_id),
        )
        if index is None:
            return {
                "message": self._public_workspace_message(message),
                "revisions": [],
                "next_cursor": None,
                "high_water": 0,
                "history_status": "complete",
            }
        high_water = int(index.get("high_water", 0))
        page_id = index.get("head_page")
        offset = 0
        if cursor is not None:
            if not isinstance(cursor, str):
                raise ValidationError("Workspace revision cursor is invalid")
            value = self.store.open_cursor(cursor)
            expected = {
                "v": 1,
                "workspace_id": workspace_id,
                "target_event_id": event_id,
                "authorization_generation": int(
                    workspace.get("authorization_generation", 1)
                ),
                "retention_generation": int(
                    workspace.get("retention_generation", 1)
                ),
                "high_water": high_water,
            }
            if any(value.get(key) != item for key, item in expected.items()):
                raise StaleCursor("Workspace revision cursor is stale")
            page_id = value.get("page_id")
            offset = value.get("offset")
            if (
                not isinstance(page_id, str)
                or isinstance(offset, bool)
                or not isinstance(offset, int)
                or offset < 0
            ):
                raise ValidationError("Workspace revision cursor is invalid")
        revisions: list[dict[str, Any]] = []
        next_page: str | None = None
        next_offset = 0
        while isinstance(page_id, str) and len(revisions) < limit:
            page = self.store.get("workspace_revision_index", page_id)
            if (
                page is None
                or page.get("workspace_id") != workspace_id
                or page.get("target_event_id") != event_id
            ):
                raise ValidationError("Workspace revision page is unavailable")
            entries = page.get("entries", [])
            if not isinstance(entries, list) or offset > len(entries):
                raise ValidationError("Workspace revision page is invalid")
            position = len(entries) - 1 - offset
            while position >= 0 and len(revisions) < limit:
                entry = entries[position]
                record = self.store.get(
                    "workspace_event", str(entry.get("event_record_id", ""))
                )
                if record is not None:
                    revision = {
                        "event_id": record.get("id"),
                        "event_type": record.get("event_type"),
                        "revision": record.get("revision"),
                        "author_member_id": record.get("author_member_id"),
                        "created_at": record.get("created_at"),
                    }
                    if record.get("event_type") == "edit":
                        revision["text"] = record.get("text", "")
                        revision["mention_member_ids"] = list(
                            record.get("mention_member_ids", ())
                        )
                    elif record.get("event_type") == "reaction":
                        revision["emoji"] = record.get("emoji")
                        revision["active"] = bool(record.get("active"))
                    revisions.append(revision)
                position -= 1
                offset += 1
            if len(revisions) >= limit and position >= 0:
                next_page = page_id
                next_offset = offset
                break
            page_id = page.get("previous_page")
            offset = 0
            if len(revisions) >= limit and isinstance(page_id, str):
                next_page = page_id
                break
        next_cursor = None
        if next_page is not None:
            next_cursor = self.store.seal_cursor(
                {
                    "v": 1,
                    "workspace_id": workspace_id,
                    "target_event_id": event_id,
                    "authorization_generation": int(
                        workspace.get("authorization_generation", 1)
                    ),
                    "retention_generation": int(
                        workspace.get("retention_generation", 1)
                    ),
                    "high_water": high_water,
                    "page_id": next_page,
                    "offset": next_offset,
                }
            )
        return {
            "message": self._public_workspace_message(message),
            "revisions": revisions,
            "next_cursor": next_cursor,
            "high_water": high_water,
            "history_status": (
                "pruned" if int(index.get("pruned_count", 0)) else "complete"
            ),
        }

    def list_workspace_tombstones(
        self,
        workspace_id: Any,
        conversation_id: Any,
        cursor: Any = None,
        limit: Any = MESSAGE_PAGE_DEFAULT,
    ) -> dict[str, Any]:
        workspace = self._require_workspace(workspace_id)
        visibility_cache: dict[str, dict[str, Any]] = {}
        self._require_workspace_conversation(workspace_id, conversation_id)
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MESSAGE_PAGE_MAX
        ):
            raise ValidationError("Workspace tombstone page size is invalid")
        index = self.store.get(
            "workspace_tombstone_index",
            self._workspace_tombstone_index_id(workspace_id, conversation_id),
        )
        if index is None:
            return {
                "tombstones": [],
                "next_cursor": None,
                "high_water": 0,
                "history_status": "complete",
            }
        high_water = int(index.get("high_water", 0))
        page_id = index.get("head_page")
        offset = 0
        if cursor is not None:
            if not isinstance(cursor, str):
                raise ValidationError("Workspace tombstone cursor is invalid")
            value = self.store.open_cursor(cursor)
            expected = {
                "v": 1,
                "workspace_id": workspace_id,
                "conversation_id": conversation_id,
                "authorization_generation": int(
                    workspace.get("authorization_generation", 1)
                ),
                "retention_generation": int(
                    workspace.get("retention_generation", 1)
                ),
                "high_water": high_water,
            }
            if any(value.get(key) != item for key, item in expected.items()):
                raise StaleCursor("Workspace tombstone cursor is stale")
            page_id = value.get("page_id")
            offset = value.get("offset")
            if (
                not isinstance(page_id, str)
                or isinstance(offset, bool)
                or not isinstance(offset, int)
                or offset < 0
            ):
                raise ValidationError("Workspace tombstone cursor is invalid")
        tombstones: list[dict[str, Any]] = []
        next_page: str | None = None
        next_offset = 0
        while isinstance(page_id, str) and len(tombstones) < limit:
            page = self.store.get("workspace_tombstone_index", page_id)
            if (
                page is None
                or page.get("workspace_id") != workspace_id
                or page.get("conversation_id") != conversation_id
            ):
                raise ValidationError("Workspace tombstone page is unavailable")
            entries = page.get("entries", [])
            if not isinstance(entries, list) or offset > len(entries):
                raise ValidationError("Workspace tombstone page is invalid")
            position = len(entries) - 1 - offset
            while position >= 0 and len(tombstones) < limit:
                entry = entries[position]
                message = self.store.get(
                    "workspace_message_state", str(entry.get("message_record_id", ""))
                )
                if (
                    message is not None
                    and message.get("deleted")
                    and self._workspace_message_is_visible(
                        workspace, message, visibility_cache
                    )
                ):
                    tombstones.append(
                        {
                            "position": int(entry.get("position", 0)),
                            "deleted_at": float(entry.get("created_at", 0)),
                            "message": self._public_workspace_message(message),
                        }
                    )
                position -= 1
                offset += 1
            if len(tombstones) >= limit and position >= 0:
                next_page = page_id
                next_offset = offset
                break
            page_id = page.get("previous_page")
            offset = 0
            if len(tombstones) >= limit and isinstance(page_id, str):
                next_page = page_id
                break
        next_cursor = None
        if next_page is not None:
            next_cursor = self.store.seal_cursor(
                {
                    "v": 1,
                    "workspace_id": workspace_id,
                    "conversation_id": conversation_id,
                    "authorization_generation": int(
                        workspace.get("authorization_generation", 1)
                    ),
                    "retention_generation": int(
                        workspace.get("retention_generation", 1)
                    ),
                    "high_water": high_water,
                    "page_id": next_page,
                    "offset": next_offset,
                }
            )
        return {
            "tombstones": tombstones,
            "next_cursor": next_cursor,
            "high_water": high_water,
            "history_status": (
                "pruned" if int(index.get("pruned_count", 0)) else "complete"
            ),
        }

    def mark_workspace_thread_read(
        self,
        workspace_id: Any,
        thread_root_id: Any,
        high_water: Any,
        operation_id: Any,
    ) -> dict[str, Any]:
        payload = {
            "workspace_id": workspace_id,
            "thread_root_id": thread_root_id,
            "high_water": high_water,
        }
        operation_id, digest, replay = self._workspace_operation(
            "mark_workspace_thread_read", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        root, _kind, _conversation = self._workspace_thread_context(
            workspace, thread_root_id
        )
        index = self.store.get(
            "workspace_thread_index",
            self._workspace_thread_index_id(workspace_id, thread_root_id),
        )
        maximum = int(index.get("high_water", 0)) if index else 0
        if (
            isinstance(high_water, bool)
            or not isinstance(high_water, int)
            or high_water != maximum
        ):
            raise ValidationError("Workspace thread read position is stale")
        read_id = self._workspace_thread_read_id(workspace_id, thread_root_id)
        previous = self.store.get("workspace_read_state", read_id)
        if previous is not None and high_water < int(previous.get("high_water", 0)):
            raise ValidationError("Workspace thread read position cannot move backwards")
        summary_id = self._workspace_thread_record_id(workspace_id, thread_root_id)
        summary = self.store.get("workspace_thread", summary_id)
        records: list[tuple[str, str, dict[str, Any]]] = [
            (
                "workspace_read_state",
                read_id,
                {
                    "workspace_id": workspace_id,
                    "conversation_id": root["conversation_id"],
                    "thread_root_id": thread_root_id,
                    "high_water": high_water,
                },
            )
        ]
        if summary is not None:
            summary["unread_count"] = 0
            records.append(("workspace_thread", summary_id, summary))
        root = dict(root)
        root["thread_unread_count"] = 0
        records.append(
            (
                "workspace_message_state",
                self._workspace_message_record_id(thread_root_id),
                root,
            )
        )
        outcome = {
            "workspace_id": workspace_id,
            "thread_root_id": thread_root_id,
            "high_water": high_water,
            "unread_count": 0,
        }
        committed = self.store.commit_operation(
            operation_id, digest, outcome, records
        )
        self._workspace_changed(
            workspace_id,
            conversation_id=root["conversation_id"],
            resource_kind="thread_read_state",
        )
        return committed

    def list_workspace_mentions(
        self,
        workspace_id: Any,
        cursor: Any = None,
        limit: Any = MESSAGE_PAGE_DEFAULT,
    ) -> dict[str, Any]:
        workspace = self._require_workspace(workspace_id)
        visibility_cache: dict[str, dict[str, Any]] = {}
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MESSAGE_PAGE_MAX:
            raise ValidationError("Workspace mention page size is invalid")
        index = self.store.get(
            "workspace_mention_index", self._workspace_mention_index_id(workspace_id)
        )
        if index is None:
            return {
                "mentions": [],
                "next_cursor": None,
                "high_water": 0,
                "unread_count": 0,
            }
        authorization_digest = self._workspace_mention_authorization_digest(
            workspace
        )
        page_id = index.get("head_page")
        offset = 0
        if cursor is not None:
            if not isinstance(cursor, str):
                raise ValidationError("Workspace mention cursor is invalid")
            value = self.store.open_cursor(cursor)
            expected = {
                "v": 1,
                "workspace_id": workspace_id,
                "authorization_digest": authorization_digest,
                "retention_generation": int(
                    workspace.get("retention_generation", 1)
                ),
                "high_water": int(index.get("high_water", 0)),
            }
            if any(value.get(key) != item for key, item in expected.items()):
                raise StaleCursor("Workspace mention cursor is stale")
            page_id = value.get("page_id")
            offset = value.get("offset")
            if (
                not isinstance(page_id, str)
                or isinstance(offset, bool)
                or not isinstance(offset, int)
                or offset < 0
            ):
                raise ValidationError("Workspace mention cursor is invalid")
        read = self.store.get(
            "workspace_read_state", self._workspace_mention_read_id(workspace_id)
        )
        read_high_water = int(read.get("high_water", 0)) if read else 0
        results: list[dict[str, Any]] = []
        next_page: str | None = None
        next_offset = 0
        while isinstance(page_id, str) and len(results) < limit:
            page = self.store.get("workspace_mention_index", page_id)
            if page is None or page.get("workspace_id") != workspace_id:
                raise ValidationError("Workspace mention page is unavailable")
            entries = page.get("entries", [])
            if not isinstance(entries, list) or offset > len(entries):
                raise ValidationError("Workspace mention page is invalid")
            position = len(entries) - 1 - offset
            while position >= 0 and len(results) < limit:
                entry = entries[position]
                message = self.store.get(
                    "workspace_message_state", entry.get("message_record_id")
                )
                if message is not None and self._workspace_mention_visible(
                    workspace, entry, message, visibility_cache
                ):
                    conversation_id = str(entry["conversation_id"])
                    if entry.get("conversation_kind") == "direct":
                        direct = self.store.get(
                            "workspace_direct",
                            self._workspace_direct_record_id(conversation_id),
                        )
                        public_direct = (
                            self._public_workspace_direct(direct)
                            if direct is not None
                            else None
                        )
                        conversation = {
                            "id": conversation_id,
                            "kind": "direct",
                            "name": (
                                public_direct.get("peer_display_name", "Member")
                                if public_direct is not None
                                else "Member"
                            ),
                            "visibility": "direct",
                        }
                    else:
                        channel = self.store.get(
                            "workspace_channel",
                            self._workspace_channel_record_id(conversation_id),
                        )
                        conversation = {
                            "id": conversation_id,
                            "kind": "channel",
                            "name": (
                                str(channel.get("name", "channel"))
                                if channel is not None
                                else "channel"
                            ),
                            "visibility": (
                                str(channel.get("visibility", "public"))
                                if channel is not None
                                else "public"
                            ),
                        }
                    mention_position = int(entry.get("position", 0))
                    result = {
                            "position": mention_position,
                            "read": mention_position <= read_high_water,
                            "conversation": conversation,
                            "message": self._public_workspace_message(message),
                        }
                    if isinstance(message.get("thread_root"), str):
                        result["thread_root_id"] = message["thread_root"]
                    results.append(result)
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
                    "authorization_digest": authorization_digest,
                    "retention_generation": int(
                        workspace.get("retention_generation", 1)
                    ),
                    "high_water": int(index.get("high_water", 0)),
                    "page_id": next_page,
                    "offset": next_offset,
                }
            )
        return {
            "mentions": results,
            "next_cursor": next_cursor,
            "high_water": int(index.get("high_water", 0)),
            "unread_count": self._workspace_mention_unread_count(workspace),
        }

    def mark_workspace_mentions_read(
        self,
        workspace_id: Any,
        high_water: Any,
        operation_id: Any,
    ) -> dict[str, Any]:
        payload = {"workspace_id": workspace_id, "high_water": high_water}
        operation_id, digest, replay = self._workspace_operation(
            "mark_workspace_mentions_read", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        index = self.store.get(
            "workspace_mention_index", self._workspace_mention_index_id(workspace_id)
        )
        maximum = int(index.get("high_water", 0)) if index else 0
        if (
            isinstance(high_water, bool)
            or not isinstance(high_water, int)
            or not 0 <= high_water <= maximum
        ):
            raise ValidationError("Workspace mention read position is invalid")
        read_id = self._workspace_mention_read_id(workspace_id)
        previous = self.store.get("workspace_read_state", read_id)
        if previous is not None and high_water < int(previous.get("high_water", 0)):
            raise ValidationError("Workspace mention read position cannot move backwards")
        outcome = {
            "workspace_id": workspace_id,
            "high_water": high_water,
            "unread_count": self._workspace_mention_unread_count(
                workspace, high_water
            ),
        }
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [
                (
                    "workspace_read_state",
                    read_id,
                    {
                        "workspace_id": workspace_id,
                        "scope": "mentions",
                        "high_water": high_water,
                    },
                )
            ],
        )
        self._workspace_changed(workspace_id, resource_kind="mention_read_state")
        return committed

    def set_workspace_channel_mentions_muted(
        self,
        workspace_id: Any,
        channel_id: Any,
        muted: Any,
        operation_id: Any,
    ) -> dict[str, Any]:
        payload = {
            "workspace_id": workspace_id,
            "channel_id": channel_id,
            "muted": muted,
        }
        operation_id, digest, replay = self._workspace_operation(
            "set_workspace_channel_mentions_muted", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        channel = self._require_workspace_channel(workspace_id, channel_id)
        if not isinstance(muted, bool):
            raise ValidationError("Workspace mention preference is invalid")
        if workspace.get("state") not in {"active", "incomplete_sync"}:
            raise ContactNotApproved("Workspace mention preferences cannot change now")
        if (
            channel.get("visibility") == "private"
            and workspace.get("local_member_id") not in channel.get("member_ids", ())
        ):
            raise ContactNotApproved("Local member is not in this private channel")
        preference_id = self._workspace_notification_preference_id(
            workspace_id, channel_id
        )
        outcome = {
            "workspace_id": workspace_id,
            "channel_id": channel_id,
            "mentions_muted": muted,
        }
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [
                (
                    "workspace_notification_preference",
                    preference_id,
                    {
                        "workspace_id": workspace_id,
                        "conversation_id": channel_id,
                        "mentions_muted": muted,
                    },
                )
            ],
        )
        self._workspace_changed(
            workspace_id,
            conversation_id=channel_id,
            resource_kind="mention_preference",
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
        workspace = self._require_workspace(workspace_id)
        message = self.store.get(
            "workspace_message_state", self._workspace_message_record_id(event_id)
        )
        if message is None or message.get("workspace_id") != workspace_id:
            raise ValidationError("Workspace message does not exist")
        marker_id = self.store.opaque_id(
            "workspace-message-hidden", workspace_id, event_id
        )
        existing_marker = self.store.get("workspace_message_hidden", marker_id)
        outcome = {"workspace_id": workspace_id, "event_id": event_id, "hidden": True}
        records: list[tuple[str, str, dict[str, Any]]] = [
            (
                "workspace_message_hidden",
                marker_id,
                {"workspace_id": workspace_id, "event_id": event_id},
            )
        ]
        records.extend(
            self._workspace_search_document_records(
                workspace,
                category=(
                    "thread"
                    if isinstance(message.get("thread_root"), str)
                    else "message"
                ),
                entity_id=str(message["id"]),
                text="",
                active=False,
                sort_at=float(message.get("created_at", 0)),
                conversation_id=str(message.get("conversation_id", "")),
                thread_root_id=(
                    str(message["thread_root"])
                    if isinstance(message.get("thread_root"), str)
                    else None
                ),
            )
        )
        thread_root_id = message.get("thread_root")
        if isinstance(thread_root_id, str):
            summary_id = self._workspace_thread_record_id(
                workspace_id, thread_root_id
            )
            summary = self.store.get("workspace_thread", summary_id)
            read = self.store.get(
                "workspace_read_state",
                self._workspace_thread_read_id(workspace_id, thread_root_id),
            )
            if (
                summary is not None
                and existing_marker is None
                and message.get("direction") == "inbound"
                and int(message.get("thread_position", 0))
                > int(read.get("high_water", 0) if read else 0)
            ):
                summary["unread_count"] = max(
                    0, int(summary.get("unread_count", 0)) - 1
                )
                records.append(("workspace_thread", summary_id, summary))
        else:
            summary_id = self._workspace_thread_record_id(workspace_id, event_id)
            summary = self.store.get("workspace_thread", summary_id)
            if summary is not None:
                summary["unread_count"] = 0
                records.append(("workspace_thread", summary_id, summary))
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            records,
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
        mention_member_ids: Any = None,
    ) -> dict[str, Any]:
        payload = {
            "workspace_id": workspace_id,
            "channel_id": channel_id,
            "text": text,
        }
        if mention_member_ids:
            payload["mention_member_ids"] = mention_member_ids
        operation_id, digest, replay = self._workspace_operation(
            "save_workspace_draft", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        self._require_workspace_conversation(workspace_id, channel_id)
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_MESSAGE_TEXT_BYTES:
            raise ValidationError("Workspace draft is invalid")
        mentions = self._validate_workspace_mentions(
            workspace, channel_id, mention_member_ids
        )
        record_id = self.store.opaque_id(
            "workspace-draft", workspace_id, channel_id
        )
        outcome = {
            "workspace_id": workspace_id,
            "conversation_id": channel_id,
            "text": text,
        }
        if mentions:
            outcome["mention_member_ids"] = list(mentions)
        empty = text == "" and not mentions
        records = [] if empty else [("workspace_draft", record_id, outcome)]
        deletions = [("workspace_draft", record_id)] if empty else []
        committed = self.store.commit_operation(
            operation_id, digest, outcome, records, deletions
        )
        self._workspace_changed(
            workspace_id, conversation_id=channel_id, resource_kind="draft"
        )
        return committed

    def save_workspace_thread_draft(
        self,
        workspace_id: Any,
        conversation_id: Any,
        thread_root_id: Any,
        text: Any,
        operation_id: Any,
        mention_member_ids: Any = None,
    ) -> dict[str, Any]:
        payload = {
            "workspace_id": workspace_id,
            "conversation_id": conversation_id,
            "thread_root_id": thread_root_id,
            "text": text,
            "mention_member_ids": mention_member_ids or [],
        }
        operation_id, digest, replay = self._workspace_operation(
            "save_workspace_thread_draft", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        root, _kind, _conversation = self._workspace_thread_context(
            workspace, thread_root_id, require_writable=True
        )
        if root.get("conversation_id") != conversation_id:
            raise ValidationError("Workspace thread belongs to another conversation")
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_MESSAGE_TEXT_BYTES:
            raise ValidationError("Workspace draft is invalid")
        mentions = self._validate_workspace_mentions(
            workspace, conversation_id, mention_member_ids
        )
        record_id = self.store.opaque_id(
            "workspace-thread-draft", workspace_id, thread_root_id
        )
        outcome = {
            "workspace_id": workspace_id,
            "conversation_id": conversation_id,
            "thread_root_id": thread_root_id,
            "text": text,
        }
        root_event = self.store.get(
            "workspace_event", self._workspace_event_record_id(thread_root_id)
        )
        if root_event is None:
            raise ContactNotApproved("Workspace thread is unavailable")
        if mentions:
            outcome["mention_member_ids"] = list(mentions)
        stored_draft = {
            **outcome,
            "root_channel_digest": root_event.get("channel_digest"),
            "root_author_member_id": root_event.get("author_member_id"),
        }
        empty = text == "" and not mentions
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [] if empty else [("workspace_draft", record_id, stored_draft)],
            [("workspace_draft", record_id)] if empty else [],
        )
        self._workspace_changed(
            workspace_id,
            conversation_id=conversation_id,
            resource_kind="thread_draft",
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
                "Workspace channel creation is restricted to owners and administrators"
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

    def _workspace_removal_checkpoint_digests(
        self,
        workspace_id: str,
        member: Any,
        *,
        conversation_id: str | None = None,
    ) -> list[str]:
        digests: set[str] = set()
        for device in member.devices:
            catalog = self.store.get(
                "workspace_checkpoint_catalog",
                self.store.opaque_id(
                    "workspace-checkpoint-catalog", workspace_id, device.device_id
                ),
            )
            if catalog is None:
                continue
            for entry in catalog.get("entries", ())[:MAX_HISTORY_STREAMS]:
                if (
                    conversation_id is not None
                    and entry.get("conversation_id") != conversation_id
                ):
                    continue
                digest = entry.get("checkpoint_digest")
                if isinstance(digest, str):
                    digests.add(digest)
        return sorted(digests)[:32]

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
        removed = set(previous.member_ids) - set(checked_members)
        removal_checkpoints: list[str] = []
        for removed_member_id in sorted(removed):
            removed_member = find_member(manifest, removed_member_id)
            if removed_member is None:
                continue
            removal_checkpoints.extend(
                self._workspace_removal_checkpoint_digests(
                    workspace_id, removed_member, conversation_id=channel_id
                )
            )
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
            removal_checkpoint_digests=sorted(set(removal_checkpoints))[:32],
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
        invitation_requests: Any = None,
    ) -> dict[str, Any]:
        payload = {
            "workspace_id": workspace_id,
            "channel_creation": channel_creation,
            "posting": posting,
        }
        if invitation_requests is not None:
            payload["invitation_requests"] = invitation_requests
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
            invitation_policy = (
                self._workspace_current_manifest(workspace).invitation_requests
                if invitation_requests is None
                else WorkspaceInvitationPolicy(invitation_requests)
            )
        except (TypeError, ValueError) as exc:
            raise ValidationError("Workspace policy is invalid") from exc
        current = self._workspace_current_manifest(workspace)
        if (
            current.channel_creation == creation_policy
            and current.posting == posting_policy
            and current.invitation_requests == invitation_policy
        ):
            raise ValidationError("Workspace policies are unchanged")
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
            invitation_requests=invitation_policy,
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
        admin_request_updates = self._admin_request_state_records_after_manifest(
            workspace_id, "", None
        )
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
                *admin_request_updates,
                *[
                    ("workspace_delivery", delivery["id"], delivery)
                    for delivery in deliveries
                ],
                *self._due_records(add=deliveries),
            ],
        )
        self._workspace_changed(workspace_id, resource_kind="policy")
        return committed

    def update_workspace_retention(
        self,
        workspace_id: Any,
        retention_days: Any,
        operation_id: Any,
    ) -> dict[str, Any]:
        payload = {
            "workspace_id": workspace_id,
            "retention_days": retention_days,
        }
        operation_id, digest, replay = self._workspace_operation(
            "update_workspace_retention", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if (
            workspace.get("state") != "active"
            or workspace.get("local_role") != WorkspaceRole.OWNER.value
        ):
            raise ContactNotApproved(
                "Workspace retention changes require the active owner authority"
            )
        if retention_days not in {30, 90, 365, None}:
            raise ValidationError("Workspace retention preference is invalid")
        current = self._workspace_current_manifest(workspace)
        if current.retention_days == retention_days:
            raise ValidationError("Workspace retention preference is unchanged")
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
            retention_days=retention_days,
            channel_creation=current.channel_creation,
            posting=current.posting,
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
        state_id = self._workspace_retention_state_id(workspace_id)
        admin_request_updates = self._admin_request_state_records_after_manifest(
            workspace_id, "", None
        )
        state = {
            "workspace_id": workspace_id,
            "policy_generation": int(workspace.get("retention_generation", 1)),
            "status": "disabled" if retention_days is None else "pending",
            "cutoff": None,
            "page_id": None,
            "scanned": 0,
            "pruned": 0,
            "updated_at": time.time(),
        }
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
                *admin_request_updates,
                ("workspace_retention_state", state_id, state),
                *[
                    ("workspace_delivery", delivery["id"], delivery)
                    for delivery in deliveries
                ],
                *self._due_records(add=deliveries),
            ],
        )
        self._workspace_changed(workspace_id, resource_kind="retention_policy")
        return committed

    @staticmethod
    def _workspace_add_pruned_sequence(
        stream_head: dict[str, Any], sequence: int
    ) -> dict[str, Any]:
        ranges = [
            [int(item[0]), int(item[1])]
            for item in stream_head.get("pruned_ranges", ())
            if isinstance(item, list)
            and len(item) == 2
            and all(isinstance(value, int) for value in item)
        ]
        ranges.append([sequence, sequence])
        ranges.sort()
        merged: list[list[int]] = []
        for start, end in ranges:
            if merged and start <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        updated = dict(stream_head)
        updated["pruned_ranges"] = merged
        floor = int(updated.get("retained_floor", 1))
        for start, end in merged:
            if start <= floor <= end:
                floor = end + 1
        updated["retained_floor"] = floor
        return updated

    def _workspace_prune_index_entry(
        self,
        staged: dict[tuple[str, str], dict[str, Any]],
        *,
        kind: str,
        page_id: Any,
        event_id: str,
    ) -> bool:
        if not isinstance(page_id, str):
            return False
        key = (kind, page_id)
        page = staged.get(key)
        if page is None:
            stored = self.store.get(kind, page_id)
            if stored is None:
                return False
            page = dict(stored)
        entries = list(page.get("entries", ()))
        kept = [item for item in entries if item.get("event_id") != event_id]
        if len(kept) == len(entries):
            return False
        page["entries"] = kept
        if "encoded_bytes" in page:
            page["encoded_bytes"] = sum(
                len(json.dumps(item, separators=(",", ":")).encode("utf-8"))
                for item in kept
            )
        staged[key] = page
        return True

    def _workspace_prune_event(
        self,
        workspace: dict[str, Any],
        event: dict[str, Any],
        *,
        now: float,
        staged: dict[tuple[str, str], dict[str, Any]],
        deletions: set[tuple[str, str]],
        due_removals: set[str],
    ) -> bool:
        event_id = str(event.get("id", ""))
        if not event_id:
            return False
        event_type = str(event.get("event_type", "message"))
        target_id = event.get("target_event_id")
        message_id = target_id if event_type != "message" else event_id
        message_record_id = self._workspace_message_record_id(str(message_id))
        message = self.store.get("workspace_message_state", message_record_id)
        if (
            message is not None
            and message.get("deleted")
            and now < float(message.get("tombstone_retain_until", 0))
        ):
            return False
        deletions.add(("workspace_event", self._workspace_event_record_id(event_id)))
        operation_record_id = event.get("operation_record_id")
        if isinstance(operation_record_id, str):
            deletions.add(("workspace_operation", operation_record_id))
        for delivery_id in event.get("delivery_ids", ()):
            if not isinstance(delivery_id, str):
                continue
            delivery = self.store.get("workspace_delivery", delivery_id)
            if delivery is None:
                continue
            if (
                delivery.get("state") in FINAL_DELIVERY_STATES
                or float(delivery.get("expires_at", 0)) <= now
            ):
                deletions.add(("workspace_delivery", delivery_id))
                due_removals.add(delivery_id)
        sequence_id = self._workspace_stream_sequence_id(
            str(event.get("workspace_id", "")),
            str(event.get("conversation_id", "")),
            str(event.get("author_device_id", "")),
            int(event.get("sequence", 0)),
        )
        sequence = self.store.get("workspace_stream_coverage", sequence_id)
        if sequence is not None:
            staged[("workspace_stream_coverage", sequence_id)] = {
                "workspace_id": event.get("workspace_id"),
                "conversation_id": event.get("conversation_id"),
                "device_id": event.get("author_device_id"),
                "sequence": int(event.get("sequence", 0)),
                "event_digest": event.get("digest"),
                "pruned": True,
            }
        stream_head_id = self._workspace_stream_head_id(
            str(event.get("workspace_id", "")),
            str(event.get("conversation_id", "")),
            str(event.get("author_device_id", "")),
        )
        stream_head = staged.get(("workspace_stream_coverage", stream_head_id))
        if stream_head is None:
            stream_head = self.store.get("workspace_stream_coverage", stream_head_id)
        if stream_head is not None:
            staged[("workspace_stream_coverage", stream_head_id)] = (
                self._workspace_add_pruned_sequence(
                    stream_head, int(event.get("sequence", 0))
                )
            )
        staged[
            (
                "workspace_event_tombstone",
                self._workspace_event_tombstone_id(workspace["id"], event_id),
            )
        ] = {
            "workspace_id": workspace["id"],
            "event_id": event_id,
            "digest": event.get("digest"),
            "conversation_id": event.get("conversation_id"),
            "author_device_id": event.get("author_device_id"),
            "sequence": event.get("sequence"),
            "event_type": event_type,
            "target_event_id": target_id,
            "pruned_at": now,
        }
        if event_type == "message":
            if message is not None:
                self._workspace_search_document_records(
                    workspace,
                    category=(
                        "thread"
                        if isinstance(message.get("thread_root"), str)
                        else "message"
                    ),
                    entity_id=event_id,
                    text="",
                    active=False,
                    sort_at=float(message.get("created_at", 0)),
                    conversation_id=str(message.get("conversation_id", "")),
                    thread_root_id=(
                        str(message["thread_root"])
                        if isinstance(message.get("thread_root"), str)
                        else None
                    ),
                    staged=staged,
                )
                search_state_key = (
                    "workspace_search_state",
                    self._workspace_search_state_id(workspace["id"]),
                )
                search_state = staged.get(search_state_key)
                if search_state is not None:
                    search_state["pruned_count"] = int(
                        search_state.get("pruned_count", 0)
                    ) + 1
                if isinstance(message.get("thread_root"), str):
                    index_kind = "workspace_thread_index"
                    index_page = message.get("thread_index_page_id")
                    index_id = self._workspace_thread_index_id(
                        workspace["id"], str(message.get("thread_root"))
                    )
                else:
                    index_kind = "workspace_conversation_index"
                    index_page = message.get("conversation_index_page_id")
                    index_id = self._workspace_index_record_id(
                        workspace["id"], str(message.get("conversation_id", ""))
                    )
                if self._workspace_prune_index_entry(
                    staged,
                    kind=index_kind,
                    page_id=index_page,
                    event_id=event_id,
                ):
                    index_key = (index_kind, index_id)
                    index = staged.get(index_key) or self.store.get(index_kind, index_id)
                    if index is not None:
                        index = dict(index)
                        index["count"] = max(0, int(index.get("count", 0)) - 1)
                        index["pruned_count"] = int(index.get("pruned_count", 0)) + 1
                        staged[index_key] = index
                self._workspace_prune_index_entry(
                    staged,
                    kind="workspace_mention_index",
                    page_id=message.get("mention_index_page_id"),
                    event_id=event_id,
                )
                for reaction_id in message.get("reaction_state_ids", ()):
                    if isinstance(reaction_id, str):
                        deletions.add(("workspace_reaction_state", reaction_id))
                deletions.add(("workspace_message_state", message_record_id))
                deletions.add(
                    (
                        "workspace_message_hidden",
                        self.store.opaque_id(
                            "workspace-message-hidden", workspace["id"], event_id
                        ),
                    )
                )
                if message.get("thread_root") is None:
                    summary_id = self._workspace_thread_record_id(
                        workspace["id"], event_id
                    )
                    summary = self.store.get("workspace_thread", summary_id)
                    if summary is not None:
                        deletions.add(("workspace_thread", summary_id))
                        activity_id = self._workspace_thread_activity_id(workspace["id"])
                        activity_key = ("workspace_thread_activity_index", activity_id)
                        activity = staged.get(activity_key) or self.store.get(
                            "workspace_thread_activity_index", activity_id
                        )
                        if activity is not None:
                            activity = dict(activity)
                            entries = dict(activity.get("entries", {}))
                            entries.pop(event_id, None)
                            activity["entries"] = entries
                            staged[activity_key] = activity
        else:
            self._workspace_prune_index_entry(
                staged,
                kind="workspace_revision_index",
                page_id=event.get("revision_page_id"),
                event_id=event_id,
            )
            if event_type == "delete":
                self._workspace_prune_index_entry(
                    staged,
                    kind="workspace_tombstone_index",
                    page_id=event.get("tombstone_page_id"),
                    event_id=event_id,
                )
            if message is not None:
                updated_message = dict(message)
                candidates = []
                for candidate in message.get("mutation_candidates", ()):
                    candidate = dict(candidate)
                    if candidate.get("event_id") == event_id:
                        candidate.pop("text", None)
                        candidate.pop("mention_member_ids", None)
                        candidate["pruned"] = True
                    candidates.append(candidate)
                updated_message["mutation_candidates"] = candidates
                staged[("workspace_message_state", message_record_id)] = updated_message
        return True

    def _workspace_retention_batch_plan(
        self, workspace: dict[str, Any], max_events: int
    ) -> tuple[
        dict[str, Any],
        list[tuple[str, str, dict[str, Any]]],
        list[tuple[str, str]],
    ]:
        now = time.time()
        retention_days = workspace.get("retention_days", 90)
        state_id = self._workspace_retention_state_id(workspace["id"])
        existing_state = self.store.get("workspace_retention_state", state_id)
        index_id = self._workspace_retention_index_id(workspace["id"])
        retention_index = self.store.get("workspace_retention_index", index_id) or {
            "workspace_id": workspace["id"],
            "head_page": None,
            "count": 0,
            "high_water": 0,
        }
        if retention_days is None:
            state = {
                "workspace_id": workspace["id"],
                "policy_generation": int(workspace.get("retention_generation", 1)),
                "status": "disabled",
                "cutoff": None,
                "page_id": None,
                "scanned": 0,
                "pruned": 0,
                "updated_at": now,
            }
            workspace["retention_pruning_state"] = "disabled"
            return (
                {
                    "workspace_id": workspace["id"],
                    "status": "disabled",
                    "scanned": 0,
                    "pruned": 0,
                    "needs_more": False,
                },
                [
                    ("workspace", self._workspace_record_id(workspace["id"]), workspace),
                    ("workspace_retention_state", state_id, state),
                ],
                [],
            )
        policy_generation = int(workspace.get("retention_generation", 1))
        state = dict(existing_state or {})
        if (
            state.get("status") != "running"
            or state.get("policy_generation") != policy_generation
        ):
            state = {
                "workspace_id": workspace["id"],
                "policy_generation": policy_generation,
                "status": "running",
                "cutoff": now - int(retention_days) * 24 * 60 * 60,
                "page_id": retention_index.get("head_page"),
                "captured_high_water": int(retention_index.get("high_water", 0)),
                "scanned": 0,
                "pruned": 0,
                "updated_at": now,
            }
        else:
            state["status"] = "running"
        cutoff = float(state.get("cutoff", now))
        page_id = state.get("page_id")
        staged: dict[tuple[str, str], dict[str, Any]] = {}
        deletions: set[tuple[str, str]] = set()
        due_removals: set[str] = set()
        scanned_this_batch = 0
        pruned_this_batch = 0
        changed = False
        while isinstance(page_id, str):
            page = self.store.get("workspace_retention_index", page_id)
            if page is None or page.get("workspace_id") != workspace["id"]:
                state["status"] = "restart_required"
                state["page_id"] = None
                break
            entries = list(page.get("entries", ()))
            if scanned_this_batch and scanned_this_batch + len(entries) > max_events:
                break
            kept: list[dict[str, Any]] = []
            for entry in entries:
                scanned_this_batch += 1
                event = self.store.get(
                    "workspace_event", str(entry.get("event_record_id", ""))
                )
                if event is None:
                    continue
                if float(event.get("created_at", 0)) >= cutoff:
                    kept.append(entry)
                    continue
                if not self._workspace_prune_event(
                    workspace,
                    event,
                    now=now,
                    staged=staged,
                    deletions=deletions,
                    due_removals=due_removals,
                ):
                    kept.append(entry)
                    continue
                pruned_this_batch += 1
                changed = True
            page["entries"] = kept
            staged[("workspace_retention_index", page_id)] = page
            page_id = page.get("previous_page")
            state["page_id"] = page_id
            if scanned_this_batch >= max_events:
                break
        state["scanned"] = int(state.get("scanned", 0)) + scanned_this_batch
        state["pruned"] = int(state.get("pruned", 0)) + pruned_this_batch
        state["updated_at"] = now
        if not isinstance(state.get("page_id"), str):
            state["status"] = "complete"
            state["completed_at"] = now
            state["next_due_at"] = now + 24 * 60 * 60
        if changed:
            workspace["retention_generation"] = int(
                workspace.get("retention_generation", 1)
            ) + 1
            state["policy_generation"] = int(workspace["retention_generation"])
            retention_index["count"] = max(
                0, int(retention_index.get("count", 0)) - pruned_this_batch
            )
            retention_index["pruned_count"] = int(
                retention_index.get("pruned_count", 0)
            ) + pruned_this_batch
            retention_index["retention_generation"] = int(
                workspace["retention_generation"]
            )
            staged[("workspace_retention_index", index_id)] = retention_index
        workspace["retention_pruning_state"] = state["status"]
        workspace["retention_pruning_updated_at"] = now
        staged[("workspace", self._workspace_record_id(workspace["id"]))] = workspace
        staged[("workspace_retention_state", state_id)] = state
        for record in self._due_records(remove=due_removals):
            staged[(record[0], record[1])] = record[2]
        outcome = {
            "workspace_id": workspace["id"],
            "status": state["status"],
            "scanned": int(state.get("scanned", 0)),
            "pruned": int(state.get("pruned", 0)),
            "scanned_this_batch": scanned_this_batch,
            "pruned_this_batch": pruned_this_batch,
            "needs_more": state["status"] == "running",
            "retention_generation": int(workspace.get("retention_generation", 1)),
            "cutoff": cutoff,
        }
        return (
            outcome,
            [(kind, record_id, value) for (kind, record_id), value in staged.items()],
            sorted(deletions),
        )

    def prune_workspace_history(
        self,
        workspace_id: Any,
        operation_id: Any,
        max_events: Any = RETENTION_PRUNE_BATCH_DEFAULT,
    ) -> dict[str, Any]:
        payload = {"workspace_id": workspace_id, "max_events": max_events}
        operation_id, digest, replay = self._workspace_operation(
            "prune_workspace_history", operation_id, payload
        )
        if replay is not None:
            return replay
        if (
            isinstance(max_events, bool)
            or not isinstance(max_events, int)
            or not 100 <= max_events <= RETENTION_PRUNE_BATCH_MAX
        ):
            raise ValidationError("Workspace retention batch size is invalid")
        workspace = self._require_workspace(workspace_id)
        if workspace.get("state") not in {
            "active",
            "incomplete_sync",
            "closed",
            "left",
            "removed",
        }:
            raise ContactNotApproved("Workspace history cannot be pruned now")
        outcome, records, deletions = self._workspace_retention_batch_plan(
            workspace, max_events
        )
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            records,
            deletions,
            redact_command_cache=bool(deletions),
        )
        self._workspace_changed(workspace_id, resource_kind="retention_pruning")
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
        admin_request_updates = self._admin_request_state_records_after_manifest(
            workspace_id, "", None
        )
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
                *admin_request_updates,
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
        if self._member_manages_active_private_channel(workspace_id, member_id):
            raise ValidationError(
                "Transfer private-channel management before removing this member"
            )
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
            removal_checkpoint_digests=self._workspace_removal_checkpoint_digests(
                workspace_id, member
            ),
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
        admin_request_updates = self._admin_request_state_records_after_manifest(
            workspace_id, "", member_id
        )
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
                *admin_request_updates,
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

    def _member_manages_active_private_channel(
        self, workspace_id: str, member_id: str
    ) -> bool:
        return any(
            item.get("workspace_id") == workspace_id
            and item.get("visibility") == "private"
            and item.get("state") == "active"
            and item.get("manager_member_id") == member_id
            for item in self.store.list("workspace_channel")
        )

    def change_workspace_role(
        self,
        workspace_id: Any,
        member_id: Any,
        role: Any,
        operation_id: Any,
    ) -> dict[str, Any]:
        payload = {"workspace_id": workspace_id, "member_id": member_id, "role": role}
        operation_id, digest, replay = self._workspace_operation(
            "change_workspace_role", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if (
            workspace.get("state") != "active"
            or workspace.get("local_role") != WorkspaceRole.OWNER.value
        ):
            raise ContactNotApproved("Role changes require the active owner authority")
        try:
            requested_role = WorkspaceRole(role)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Workspace role is invalid") from exc
        if requested_role not in {WorkspaceRole.ADMIN, WorkspaceRole.MEMBER}:
            raise ValidationError("Only administrator and member roles may be assigned")
        current = self._workspace_current_manifest(workspace)
        member = find_member(current, member_id) if isinstance(member_id, str) else None
        if (
            member is None
            or member.status != "active"
            or member.role == WorkspaceRole.OWNER
            or member.role == requested_role
        ):
            raise ValidationError("Workspace member role cannot be changed")
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
            members=self._workspace_manifest_member_inputs(
                current,
                replacement_member_id=member_id,
                replacement_role=requested_role,
            ),
            retention_days=current.retention_days,
            channel_creation=current.channel_creation,
            posting=current.posting,
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
        admin_request_updates = self._admin_request_state_records_after_manifest(
            workspace_id, "", member_id
        )
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
                *admin_request_updates,
                *[("workspace_delivery", item["id"], item) for item in deliveries],
                *self._due_records(add=deliveries),
            ],
        )
        self._workspace_changed(workspace_id, resource_kind="role")
        return committed

    @staticmethod
    def _admin_request_terminal(state: Any) -> bool:
        return state in {
            "approved", "declined", "stale", "superseded", "expired",
            "cancelled", "failed",
        }

    def _public_workspace_admin_request(
        self, record: dict[str, Any], workspace: dict[str, Any]
    ) -> dict[str, Any]:
        members = {
            item.get("id"): item for item in workspace.get("members", [])
            if isinstance(item.get("id"), str)
        }
        requester = members.get(record.get("requester_member_id"), {})
        target = members.get(record.get("target_member_id"), {})
        public = {
            "id": record["id"],
            "workspace_id": record["workspace_id"],
            "direction": record.get("direction", "outgoing"),
            "request_kind": record["request_kind"],
            "state": record["state"],
            "requester_display_name": requester.get("display_name", "Member"),
            "requester_role": requester.get("role"),
            "target_member_id": record.get("target_member_id"),
            "target_display_name": target.get("display_name"),
            "effective_role": target.get("role"),
            "requested_role": record.get("requested_role"),
            "note": record.get("note", ""),
            "created_at": record.get("created_at", 0),
            "expires_at": record.get("expires_at", 0),
            "updated_at": record.get("updated_at", record.get("created_at", 0)),
            "dismissed": bool(record.get("dismissed", False)),
            "failure": record.get("failure"),
        }
        delivery_id = record.get("delivery_id")
        delivery = (
            self.store.get("workspace_delivery", delivery_id)
            if isinstance(delivery_id, str)
            else None
        )
        if record["state"] == "pending":
            if record.get("direction") == "incoming" or delivery is None:
                public["delivery_state"] = "delivered_to_owner"
            else:
                state = delivery.get("state")
                public["delivery_state"] = (
                    "delivered_to_owner"
                    if state in {
                        DeliveryState.RECEIVED_BY_ENDPOINT.value,
                        DeliveryState.DELIVERED.value,
                    }
                    else "waiting_for_route"
                    if state in {
                        DeliveryState.WAITING_FOR_KEYS.value,
                        DeliveryState.QUEUED.value,
                        DeliveryState.SENDING.value,
                        DeliveryState.STORED_FOR_DELIVERY.value,
                    }
                    else "failed_retryable"
                )
        if (
            record.get("state") == "approved"
            and record.get("result_kind") == "invitation"
            and isinstance(record.get("result_document"), str)
        ):
            public["invitation"] = workspace_invitation_formats(
                record["result_document"]
            )
        return public

    def _refresh_workspace_admin_requests(
        self, workspace: dict[str, Any]
    ) -> list[dict[str, Any]]:
        now = time.time()
        current_digest = workspace.get("manifest_hash")
        records: list[dict[str, Any]] = []
        changed: list[tuple[str, str, dict[str, Any]]] = []
        for original in self._workspace_admin_records(workspace["id"]):
            record_id = original["id"]
            record = dict(original)
            if record.get("state") == "pending":
                if float(record.get("expires_at", 0)) < now:
                    record["state"] = "expired"
                elif record.get("base_manifest_digest") != current_digest:
                    record["state"] = "stale"
                if record != original:
                    record["updated_at"] = now
                    changed.append(("workspace_admin_request", record_id, record))
            records.append(record)
        if changed:
            self.store.put_many(changed)
        return records

    def submit_workspace_admin_request(
        self,
        workspace_id: Any,
        request_kind: Any,
        operation_id: Any,
        target_member_id: Any = None,
        requested_role: Any = None,
        note: Any = "",
    ) -> dict[str, Any]:
        payload = {
            "workspace_id": workspace_id,
            "request_kind": request_kind,
            "target_member_id": target_member_id,
            "requested_role": requested_role,
            "note": note,
        }
        operation_id, digest, replay = self._workspace_operation(
            "submit_workspace_admin_request", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if workspace.get("state") != "active":
            raise ContactNotApproved("Workspace is not active")
        profile_index, _ = self._workspace_admin_index(workspace_id)
        if len(profile_index.get("request_ids", [])) >= MAX_ADMIN_REQUESTS_PER_PROFILE:
            raise ValidationError("The administrative request profile limit is reached")
        existing = self._refresh_workspace_admin_requests(workspace)
        if sum(item.get("state") == "pending" for item in existing) >= MAX_PENDING_ADMIN_REQUESTS_PER_WORKSPACE:
            raise ValidationError("The workspace pending-request limit is reached")
        if sum(
            item.get("state") == "pending"
            and item.get("requester_member_id") == workspace.get("local_member_id")
            for item in existing
        ) >= MAX_ADMIN_REQUESTS_PER_SOURCE:
            raise ValidationError("The requester pending-request limit is reached")
        if not isinstance(request_kind, str) or not isinstance(note, str):
            raise ValidationError("Workspace administrative request is invalid")
        identity = self._identity
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        manifest = self._workspace_current_manifest(workspace)
        raw = create_workspace_admin_request(
            identity,
            manifest=manifest,
            request_id=_new_id(),
            request_kind=request_kind,
            requester_member_id=workspace["local_member_id"],
            requester_device_id=workspace["local_device_id"],
            target_member_id=target_member_id,
            requested_role=requested_role,
            note=note,
        )
        request = verify_workspace_admin_request(raw, manifest=manifest)
        record_id = self._workspace_admin_request_id(workspace_id, request.request_id)
        authority = find_device(manifest, manifest.authority_device_id)
        if authority is None:
            raise ValidationError("Workspace authority is unavailable")
        deliveries = [] if workspace.get("local_role") == WorkspaceRole.OWNER.value else [
            self._workspace_delivery_record(
                workspace_id=workspace_id,
                recipient_member_id=authority[0].member_id,
                recipient_device=authority[1],
                kind="workspace_admin_request",
                document=request.serialized,
                priority=0,
            )
        ]
        record = {
            "id": record_id,
            "workspace_id": workspace_id,
            "protocol_request_id": request.request_id,
            "request_digest": request.digest,
            "request_kind": request.request_kind,
            "base_manifest_epoch": request.base_manifest_epoch,
            "base_manifest_digest": request.base_manifest_digest,
            "requester_member_id": request.requester_member_id,
            "requester_device_id": request.requester_device_id,
            "target_member_id": request.target_member_id,
            "requested_role": request.requested_role.value if request.requested_role else None,
            "note": request.note,
            "replay_key": request.replay_key,
            "document": request.serialized,
            "direction": "incoming" if workspace.get("local_role") == WorkspaceRole.OWNER.value else "outgoing",
            "state": "pending",
            "delivery_id": deliveries[0]["id"] if deliveries else None,
            "created_at": float(request.created_at),
            "expires_at": float(request.expires_at),
            "updated_at": time.time(),
        }
        replay_record = {
            "workspace_id": workspace_id,
            "request_digest": request.digest,
            "request_id": request.request_id,
            "created_at": time.time(),
            "expires_at": float(request.expires_at + ADMIN_REPLAY_RETENTION_SECONDS),
        }
        replay_id = self._workspace_admin_replay_id(
            workspace_id, request.replay_key
        )
        outcome = self._public_workspace_admin_request(record, workspace)
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [
                ("workspace_admin_request", record_id, record),
                (
                    "workspace_admin_replay",
                    replay_id,
                    replay_record,
                ),
                *self._workspace_admin_index_records(
                    workspace_id,
                    record_id,
                    aux=(
                        "workspace_admin_replay",
                        replay_id,
                        replay_record["expires_at"],
                    ),
                ),
                *[("workspace_delivery", item["id"], item) for item in deliveries],
                *self._due_records(add=deliveries),
            ],
        )
        self._workspace_changed(workspace_id, resource_kind="admin_request")
        return committed

    def list_workspace_admin_requests(
        self,
        workspace_id: Any,
        direction: Any,
        cursor: Any = None,
        limit: Any = DEFAULT_ADMIN_REQUEST_PAGE,
    ) -> dict[str, Any]:
        workspace = self._require_workspace(workspace_id)
        if direction not in {"incoming", "outgoing", "history"}:
            raise ValidationError("Administrative request list is invalid")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_ADMIN_REQUEST_PAGE:
            raise ValidationError("Administrative request page limit is invalid")
        if direction == "incoming" and workspace.get("local_role") != WorkspaceRole.OWNER.value:
            raise ContactNotApproved("Only the owner may review incoming requests")
        records = self._refresh_workspace_admin_requests(workspace)
        local_member_id = workspace.get("local_member_id")
        records = [
            item for item in records
            if (
                direction == "incoming"
                and item.get("direction") == "incoming"
                and item.get("state") == "pending"
            )
            or (
                direction == "outgoing"
                and item.get("requester_member_id") == local_member_id
                and not item.get("dismissed")
            )
            or (
                direction == "history"
                and self._admin_request_terminal(item.get("state"))
                and (
                    workspace.get("local_role") == WorkspaceRole.OWNER.value
                    or item.get("requester_member_id") == local_member_id
                )
            )
        ]
        records.sort(
            key=lambda item: (float(item.get("created_at", 0)), str(item.get("id", ""))),
            reverse=True,
        )
        offset = 0
        if cursor is not None:
            opened = self.store.open_cursor(str(cursor))
            if opened.get("kind") != "workspace_admin_requests" or opened.get("workspace_id") != workspace_id or opened.get("direction") != direction:
                raise StaleCursor("Administrative request cursor is stale")
            offset = int(opened.get("offset", 0))
        page = records[offset : offset + limit]
        next_cursor = None
        if offset + len(page) < len(records):
            next_cursor = self.store.seal_cursor({
                "kind": "workspace_admin_requests",
                "workspace_id": workspace_id,
                "direction": direction,
                "offset": offset + len(page),
            })
        return {
            "requests": [self._public_workspace_admin_request(item, workspace) for item in page],
            "next_cursor": next_cursor,
            "pending_count": sum(item.get("state") == "pending" for item in records),
        }

    def get_workspace_admin_request(
        self, workspace_id: Any, request_id: Any
    ) -> dict[str, Any]:
        workspace = self._require_workspace(workspace_id)
        if not isinstance(request_id, str):
            raise ValidationError("Administrative request ID is invalid")
        self._refresh_workspace_admin_requests(workspace)
        record = self.store.get("workspace_admin_request", request_id)
        if record is not None and record.get("workspace_id") != workspace_id:
            record = None
        if record is None:
            raise ValidationError("Administrative request does not exist")
        if (
            workspace.get("local_role") != WorkspaceRole.OWNER.value
            and record.get("requester_member_id") != workspace.get("local_member_id")
        ):
            raise ContactNotApproved("Administrative request is not visible")
        return self._public_workspace_admin_request(record, workspace)

    def _admin_request_state_records_after_manifest(
        self,
        workspace_id: str,
        approved_record_id: str,
        target_member_id: str | None,
    ) -> list[tuple[str, str, dict[str, Any]]]:
        now = time.time()
        changed: list[tuple[str, str, dict[str, Any]]] = []
        for original in self._workspace_admin_records(workspace_id):
            record_id = original["id"]
            if (
                record_id == approved_record_id
                or original.get("state") != "pending"
            ):
                continue
            record = dict(original)
            record["state"] = (
                "superseded"
                if target_member_id is not None
                and record.get("target_member_id") == target_member_id
                else "stale"
            )
            record["updated_at"] = now
            changed.append(("workspace_admin_request", record_id, record))
        return changed

    def decide_workspace_admin_request(
        self,
        workspace_id: Any,
        request_id: Any,
        approve: Any,
        operation_id: Any,
    ) -> dict[str, Any]:
        payload = {
            "workspace_id": workspace_id,
            "request_id": request_id,
            "approve": approve,
        }
        operation_id, digest, replay = self._workspace_operation(
            "decide_workspace_admin_request", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        if workspace.get("state") != "active" or workspace.get("local_role") != WorkspaceRole.OWNER.value:
            raise ContactNotApproved("Administrative decisions require the active owner authority")
        if not isinstance(request_id, str) or not isinstance(approve, bool):
            raise ValidationError("Administrative decision is invalid")
        record = self.store.get("workspace_admin_request", request_id)
        if record is None or record.get("workspace_id") != workspace_id or record.get("state") != "pending":
            raise ValidationError("Administrative request is no longer pending")
        base = self._workspace_manifest_by_digest(record.get("base_manifest_digest", ""))
        if base is None:
            raise ValidationError("Administrative request base manifest is unavailable")
        request = verify_workspace_admin_request(
            record["document"], manifest=base, allow_expired=True
        )
        current = self._workspace_current_manifest(workspace)
        if request.expires_at < int(time.time()):
            record["state"] = "expired"
            record["updated_at"] = time.time()
            return self.store.commit_operation(
                operation_id, digest,
                self._public_workspace_admin_request(record, workspace),
                [("workspace_admin_request", request_id, record)],
            )
        if current.digest != request.base_manifest_digest:
            record["state"] = "stale"
            record["updated_at"] = time.time()
            return self.store.commit_operation(
                operation_id, digest,
                self._public_workspace_admin_request(record, workspace),
                [("workspace_admin_request", request_id, record)],
            )
        # Revalidate the requester's current role and the exact target state.
        verify_workspace_admin_request(request.serialized, manifest=current)
        identity = self._identity
        if identity is None:
            raise ValidationError("Local identity is unavailable")
        requester = find_member(current, request.requester_member_id)
        if requester is None:
            raise ValidationError("Administrative requester is no longer active")
        result_kind = "no_change"
        result_document: str | None = None
        invitation_record: tuple[str, str, dict[str, Any]] | None = None
        next_manifest: VerifiedWorkspaceManifest | None = None
        cancelled_records: list[tuple[str, str, dict[str, Any]]] = []
        cancelled_ids: set[str] = set()
        if approve and request.request_kind == "invitation":
            if len(active_members(current)) >= MAX_ACTIVE_MEMBERS:
                raise ValidationError("A workspace supports at most eight people")
            manifest_record = self.store.get(
                "workspace_manifest", self._workspace_manifest_record_id(current.digest)
            )
            if manifest_record is None:
                raise ValidationError("Workspace manifest is unavailable")
            result_document = create_workspace_invitation(
                identity,
                genesis=workspace["genesis"],
                manifest=manifest_record["serialized"],
            )
            invitation = verify_workspace_invitation(result_document)
            invitation_id = self._workspace_invitation_record_id(invitation.nonce)
            invitation_record = (
                "workspace_invitation",
                invitation_id,
                {
                    "id": invitation_id,
                    "workspace_id": workspace_id,
                    "nonce": invitation.nonce.hex(),
                    "offered_manifest_digest": invitation.offered_manifest_digest,
                    "state": "active",
                    "document": invitation.serialized,
                    "created_at": float(invitation.created_at),
                    "expires_at": float(invitation.expires_at),
                    "admin_request_id": request_id,
                },
            )
            result_kind = "invitation"
        elif approve:
            target = find_member(current, request.target_member_id or "")
            if target is None or target.status != "active" or target.role == WorkspaceRole.OWNER:
                raise ValidationError("Administrative request target is stale")
            replacement_role = None
            replacement_status = None
            checkpoints: Iterable[str] = current.removal_checkpoint_digests
            if request.request_kind == "role_change":
                if request.requested_role is None or target.role == request.requested_role:
                    raise ValidationError("Administrative role request is stale")
                replacement_role = request.requested_role
            else:
                if self._member_manages_active_private_channel(workspace_id, target.member_id):
                    raise ValidationError("Transfer private-channel management before removing this member")
                replacement_status = "removed"
                checkpoints = self._workspace_removal_checkpoint_digests(
                    workspace_id, target
                )
            result_document = create_workspace_manifest(
                identity,
                workspace_id=workspace_id,
                epoch=current.epoch + 1,
                previous_manifest_hash=current.digest,
                name=current.name,
                description=current.description,
                authority_device_id=current.authority_device_id,
                members=self._workspace_manifest_member_inputs(
                    current,
                    replacement_member_id=target.member_id,
                    replacement_role=replacement_role,
                    replacement_status=replacement_status,
                ),
                retention_days=current.retention_days,
                channel_creation=current.channel_creation,
                posting=current.posting,
                invitation_requests=current.invitation_requests,
                removal_checkpoint_digests=checkpoints,
            )
            next_manifest = verify_workspace_manifest_transition(result_document, current)
            result_kind = "manifest"
            if replacement_status == "removed":
                cancelled_records, cancelled_ids = self._cancel_workspace_member_deliveries(
                    workspace_id, target.member_id
                )
        decision_raw = create_workspace_admin_decision(
            identity,
            authority_manifest=current,
            request=request,
            outcome="approved" if approve else "declined",
            result_kind=result_kind,
            result_document=result_document,
        )
        decision = verify_workspace_admin_decision(
            decision_raw, authority_manifest=current, request=request
        )
        requester_device = find_device(current, request.requester_device_id)
        if requester_device is None:
            raise ValidationError("Administrative requester device is unavailable")
        decision_deliveries = [] if request.requester_member_id == workspace.get("local_member_id") else [
            self._workspace_delivery_record(
                workspace_id=workspace_id,
                recipient_member_id=request.requester_member_id,
                recipient_device=requester_device[1],
                kind="workspace_admin_request",
                document=decision.serialized,
                priority=0,
            )
        ]
        manifest_deliveries: list[dict[str, Any]] = []
        extra_request_records: list[tuple[str, str, dict[str, Any]]] = []
        workspace_records: list[tuple[str, str, dict[str, Any]]] = []
        if next_manifest is not None:
            manifest_deliveries = self._workspace_manifest_deliveries(
                workspace_id,
                [next_manifest],
                self._workspace_manifest_recipients(
                    current,
                    excluding_member_id=workspace.get("local_member_id"),
                    include_member_ids={request.target_member_id or ""},
                ),
            )
            self._apply_manifest_to_workspace(workspace, next_manifest)
            self._apply_manifest_public_identities(workspace, next_manifest)
            workspace_records = [
                ("workspace", self._workspace_record_id(workspace_id), workspace),
                (
                    "workspace_manifest",
                    self._workspace_manifest_record_id(next_manifest.digest),
                    self._manifest_record(next_manifest),
                ),
                self._manifest_epoch_record(next_manifest),
            ]
            extra_request_records = self._admin_request_state_records_after_manifest(
                workspace_id, request_id, request.target_member_id
            )
        record["state"] = "approved" if approve else "declined"
        record["decision_digest"] = decision.digest
        record["result_kind"] = decision.result_kind
        record["result_digest"] = decision.result_digest
        record["result_document"] = decision.result_document
        record["updated_at"] = time.time()
        all_deliveries = [*decision_deliveries, *manifest_deliveries]
        outcome = self._public_workspace_admin_request(record, workspace)
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [
                *workspace_records,
                ("workspace_admin_request", request_id, record),
                (
                    "workspace_admin_decision",
                    self._workspace_admin_decision_id(workspace_id, decision.digest),
                    {
                        "workspace_id": workspace_id,
                        "request_id": request_id,
                        "request_digest": request.digest,
                        "decision_digest": decision.digest,
                        "document": decision.serialized,
                        "outcome": decision.outcome,
                        "result_kind": decision.result_kind,
                        "result_digest": decision.result_digest,
                        "created_at": float(decision.created_at),
                    },
                ),
                *([invitation_record] if invitation_record is not None else []),
                *extra_request_records,
                *cancelled_records,
                *[("workspace_delivery", item["id"], item) for item in all_deliveries],
                *self._due_records(add=all_deliveries, remove=cancelled_ids),
            ],
        )
        network = getattr(self, "network", None)
        if network is not None and cancelled_ids:
            network.cancel_outbound(cancelled_ids)
        self._workspace_changed(workspace_id, resource_kind="admin_request")
        return committed

    def cancel_workspace_admin_request(
        self, workspace_id: Any, request_id: Any, operation_id: Any
    ) -> dict[str, Any]:
        payload = {"workspace_id": workspace_id, "request_id": request_id}
        operation_id, digest, replay = self._workspace_operation(
            "cancel_workspace_admin_request", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        record = self.store.get("workspace_admin_request", request_id) if isinstance(request_id, str) else None
        if (
            record is None
            or record.get("workspace_id") != workspace_id
            or record.get("requester_member_id") != workspace.get("local_member_id")
            or record.get("state") != "pending"
        ):
            raise ValidationError("Administrative request cannot be cancelled")
        delivery_id = record.get("delivery_id")
        delivery = self.store.get("workspace_delivery", delivery_id) if isinstance(delivery_id, str) else None
        if delivery is None or delivery.get("native_message_id") or int(delivery.get("attempt_count", 0)) > 0:
            raise ValidationError("A handed-off administrative request cannot be cancelled")
        delivery["state"] = DeliveryState.CANCELLED.value
        record["state"] = "cancelled"
        record["updated_at"] = time.time()
        outcome = self._public_workspace_admin_request(record, workspace)
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [
                ("workspace_admin_request", request_id, record),
                ("workspace_delivery", delivery_id, delivery),
                *self._due_records(remove=[delivery_id]),
            ],
        )
        self._workspace_changed(workspace_id, resource_kind="admin_request")
        return committed

    def dismiss_workspace_admin_request(
        self, workspace_id: Any, request_id: Any, operation_id: Any
    ) -> dict[str, Any]:
        payload = {"workspace_id": workspace_id, "request_id": request_id}
        operation_id, digest, replay = self._workspace_operation(
            "dismiss_workspace_admin_request", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(workspace_id)
        record = self.store.get("workspace_admin_request", request_id) if isinstance(request_id, str) else None
        if (
            record is None
            or record.get("workspace_id") != workspace_id
            or not self._admin_request_terminal(record.get("state"))
            or (
                workspace.get("local_role") != WorkspaceRole.OWNER.value
                and record.get("requester_member_id") != workspace.get("local_member_id")
            )
        ):
            raise ValidationError("Administrative request cannot be dismissed")
        record["dismissed"] = True
        record["updated_at"] = time.time()
        outcome = self._public_workspace_admin_request(record, workspace)
        return self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [("workspace_admin_request", request_id, record)],
        )

    def _receive_workspace_admin_request(self, wire: WorkspaceWirePayload) -> bool:
        workspace = self.store.get("workspace", self._workspace_record_id(wire.workspace_id))
        if workspace is None:
            return False
        try:
            value = json.loads(wire.document)
            if not isinstance(value, dict):
                return False
            phase = value.get("phase")
            if phase == "request":
                if workspace.get("local_role") != WorkspaceRole.OWNER.value or workspace.get("state") != "active":
                    return False
                base_digest = value.get("base_manifest_digest")
                if not isinstance(base_digest, str):
                    return False
                base = self._workspace_manifest_by_digest(base_digest)
                if base is None:
                    self._store_pending_workspace_control(wire, "missing_manifest")
                    return False
                request = verify_workspace_admin_request(
                    wire.document, manifest=base, allow_expired=True
                )
                record_id = self._workspace_admin_request_id(
                    wire.workspace_id, request.request_id
                )
                existing = self.store.get("workspace_admin_request", record_id)
                if existing is not None:
                    if existing.get("request_digest") != request.digest:
                        workspace["security_error"] = "admin_request_conflict"
                        self.store.put("workspace", self._workspace_record_id(wire.workspace_id), workspace)
                    return existing.get("request_digest") == request.digest
                replay_id = self._workspace_admin_replay_id(
                    wire.workspace_id, request.replay_key
                )
                replay = self.store.get("workspace_admin_replay", replay_id)
                if replay is not None:
                    if replay.get("request_digest") != request.digest:
                        workspace["security_error"] = "admin_request_replay_conflict"
                        self.store.put("workspace", self._workspace_record_id(wire.workspace_id), workspace)
                    return replay.get("request_digest") == request.digest
                profile_index, _ = self._workspace_admin_index(wire.workspace_id)
                all_records = self._workspace_admin_records(wire.workspace_id)
                pending = [
                    item for item in all_records
                    if item.get("workspace_id") == wire.workspace_id
                    and item.get("state") == "pending"
                ]
                if (
                    len(profile_index.get("request_ids", [])) >= MAX_ADMIN_REQUESTS_PER_PROFILE
                    or len(pending) >= MAX_PENDING_ADMIN_REQUESTS_PER_WORKSPACE
                    or sum(item.get("requester_member_id") == request.requester_member_id for item in pending) >= MAX_ADMIN_REQUESTS_PER_SOURCE
                ):
                    return False
                current = self._workspace_current_manifest(workspace)
                state = (
                    "expired" if request.expires_at < int(time.time())
                    else "stale" if current.digest != request.base_manifest_digest
                    else "pending"
                )
                record = {
                    "id": record_id,
                    "workspace_id": wire.workspace_id,
                    "protocol_request_id": request.request_id,
                    "request_digest": request.digest,
                    "request_kind": request.request_kind,
                    "base_manifest_epoch": request.base_manifest_epoch,
                    "base_manifest_digest": request.base_manifest_digest,
                    "requester_member_id": request.requester_member_id,
                    "requester_device_id": request.requester_device_id,
                    "target_member_id": request.target_member_id,
                    "requested_role": request.requested_role.value if request.requested_role else None,
                    "note": request.note,
                    "replay_key": request.replay_key,
                    "document": request.serialized,
                    "direction": "incoming",
                    "state": state,
                    "created_at": float(request.created_at),
                    "expires_at": float(request.expires_at),
                    "updated_at": time.time(),
                }
                replay_expires_at = float(
                    request.expires_at + ADMIN_REPLAY_RETENTION_SECONDS
                )
                self.store.put_many([
                    ("workspace_admin_request", record_id, record),
                    (
                        "workspace_admin_replay",
                        replay_id,
                        {
                            "workspace_id": wire.workspace_id,
                            "request_id": request.request_id,
                            "request_digest": request.digest,
                            "created_at": time.time(),
                            "expires_at": replay_expires_at,
                        },
                    ),
                    *self._workspace_admin_index_records(
                        wire.workspace_id,
                        record_id,
                        aux=("workspace_admin_replay", replay_id, replay_expires_at),
                    ),
                ])
                self._workspace_changed(wire.workspace_id, resource_kind="admin_request")
                return True
            if phase != "decision":
                return False
            protocol_request_id = value.get("request_id")
            if not isinstance(protocol_request_id, str):
                return False
            record_id = self._workspace_admin_request_id(
                wire.workspace_id, protocol_request_id
            )
            record = self.store.get("workspace_admin_request", record_id)
            if record is None:
                aux_id = self._workspace_admin_aux_index_id()
                aux_index = self.store.get("workspace_admin_aux_index", aux_id) or {
                    "entries": [],
                }
                inert_count = sum(
                    item.get("kind") == "workspace_admin_inert_decision"
                    for item in aux_index.get("entries", [])
                )
                if inert_count < MAX_INERT_ADMIN_DECISIONS:
                    inert_id = self.store.opaque_id(
                        "workspace-admin-inert-decision",
                        wire.workspace_id,
                        workspace_document_digest(wire.document),
                    )
                    entries = [
                        item for item in aux_index.get("entries", [])
                        if item.get("id") != inert_id
                    ]
                    entries.append({
                        "kind": "workspace_admin_inert_decision",
                        "id": inert_id,
                        "workspace_id": wire.workspace_id,
                        "expires_at": float(wire.expires_at),
                    })
                    self.store.put_many([
                        ("workspace_admin_inert_decision", inert_id, {
                            "workspace_id": wire.workspace_id,
                            "protocol_request_id": protocol_request_id,
                            "document": wire.document,
                            "expires_at": float(wire.expires_at),
                            "created_at": time.time(),
                        }),
                        ("workspace_admin_aux_index", aux_id, {"entries": entries}),
                    ])
                return False
            base = self._workspace_manifest_by_digest(record.get("base_manifest_digest", ""))
            if base is None:
                self._store_pending_workspace_control(wire, "missing_manifest")
                return False
            request = verify_workspace_admin_request(
                record["document"], manifest=base, allow_expired=True
            )
            decision = verify_workspace_admin_decision(
                wire.document, authority_manifest=base, request=request
            )
            if record.get("decision_digest"):
                if record["decision_digest"] != decision.digest:
                    record["state"] = "failed"
                    record["failure"] = "conflicting_authority_results"
                    workspace["security_error"] = "admin_decision_conflict"
                    self.store.put_many([
                        ("workspace", self._workspace_record_id(wire.workspace_id), workspace),
                        ("workspace_admin_request", record_id, record),
                    ])
                    return False
                return True
            result_records: list[tuple[str, str, dict[str, Any]]] = []
            if decision.outcome == "approved" and decision.result_kind == "invitation":
                invitation = verify_workspace_invitation(decision.result_document or "")
                if invitation.workspace_id != wire.workspace_id or invitation.offered_manifest_digest != request.base_manifest_digest:
                    raise ValidationError("Administrative invitation result is not bound to the request")
                invitation_id = self._workspace_invitation_record_id(invitation.nonce)
                result_records.append(("workspace_invitation", invitation_id, {
                    "id": invitation_id,
                    "workspace_id": wire.workspace_id,
                    "nonce": invitation.nonce.hex(),
                    "offered_manifest_digest": invitation.offered_manifest_digest,
                    "state": "active",
                    "document": invitation.serialized,
                    "created_at": float(invitation.created_at),
                    "expires_at": float(invitation.expires_at),
                    "admin_request_id": record_id,
                }))
            elif decision.outcome == "approved" and decision.result_kind == "manifest":
                result_manifest = verify_workspace_manifest_transition(
                    decision.result_document or "", base
                )
                result_wire = WorkspaceWirePayload(
                    kind="workspace_manifest_root",
                    logical_id=wire.logical_id,
                    workspace_id=wire.workspace_id,
                    expires_at=wire.expires_at,
                    document=result_manifest.serialized,
                )
                self._receive_workspace_manifest(result_wire)
            record["state"] = "approved" if decision.outcome == "approved" else "declined"
            record["decision_digest"] = decision.digest
            record["result_kind"] = decision.result_kind
            record["result_digest"] = decision.result_digest
            record["result_document"] = decision.result_document
            record["updated_at"] = time.time()
            self.store.put_many([
                ("workspace_admin_request", record_id, record),
                (
                    "workspace_admin_decision",
                    self._workspace_admin_decision_id(wire.workspace_id, decision.digest),
                    {
                        "workspace_id": wire.workspace_id,
                        "request_id": record_id,
                        "request_digest": request.digest,
                        "decision_digest": decision.digest,
                        "document": decision.serialized,
                        "outcome": decision.outcome,
                        "result_kind": decision.result_kind,
                        "result_digest": decision.result_digest,
                        "created_at": float(decision.created_at),
                    },
                ),
                *result_records,
            ])
            self._workspace_changed(wire.workspace_id, resource_kind="admin_request")
            return True
        except (MeshChatError, json.JSONDecodeError, TypeError, ValueError):
            return False

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
            "workspace_direct",
            "workspace_channel_control",
            "workspace_channel_version",
            "workspace_channel_transfer",
            "workspace_channel_discovery",
            "workspace_event",
            "workspace_message_state",
            "workspace_reaction_state",
            "workspace_message_hidden",
            "workspace_delivery",
            "workspace_pending_event",
            "workspace_pending_control",
            "workspace_conversation_index",
            "workspace_mention_index",
            "workspace_revision_index",
            "workspace_tombstone_index",
            "workspace_retention_index",
            "workspace_retention_state",
            "workspace_event_tombstone",
            "workspace_search_state",
            "workspace_search_catalog",
            "workspace_search_document",
            "workspace_search_index",
            "workspace_thread",
            "workspace_thread_index",
            "workspace_thread_activity_index",
            "workspace_subscription",
            "workspace_notification_preference",
            "workspace_read_state",
            "workspace_stream_coverage",
            "workspace_event_checkpoint",
            "workspace_checkpoint_head",
            "workspace_checkpoint_catalog",
            "workspace_history_job",
            "workspace_history_request",
            "workspace_history_replay",
            "workspace_history_response_cache",
            "workspace_history_response_replay",
            "workspace_history_continuation",
            "workspace_history_peer_coverage",
            "workspace_draft",
        }
        deletions: list[tuple[str, str]] = []
        delivery_ids: list[str] = []
        admin_index_records: list[tuple[str, str, dict[str, Any]]] = []
        admin_workspace_index_id = self._workspace_admin_workspace_index_id(
            workspace_id
        )
        _, admin_workspace_index = self._workspace_admin_index(workspace_id)
        removed_admin_ids = {
            item for item in admin_workspace_index.get("request_ids", [])
            if isinstance(item, str)
        }
        for request_id in removed_admin_ids:
            request = self.store.get("workspace_admin_request", request_id)
            if request is None:
                continue
            deletions.append(("workspace_admin_request", request_id))
            decision_digest = request.get("decision_digest")
            if isinstance(decision_digest, str):
                deletions.append((
                    "workspace_admin_decision",
                    self._workspace_admin_decision_id(workspace_id, decision_digest),
                ))
        deletions.append((
            "workspace_admin_workspace_index", admin_workspace_index_id
        ))
        admin_profile_index_id = self._workspace_admin_profile_index_id()
        admin_profile_index = self.store.get(
            "workspace_admin_profile_index", admin_profile_index_id
        ) or {"request_ids": []}
        admin_index_records.append((
            "workspace_admin_profile_index",
            admin_profile_index_id,
            {
                "request_ids": [
                    item for item in admin_profile_index.get("request_ids", [])
                    if item not in removed_admin_ids
                ]
            },
        ))
        admin_aux_index_id = self._workspace_admin_aux_index_id()
        admin_aux_index = self.store.get(
            "workspace_admin_aux_index", admin_aux_index_id
        ) or {"entries": []}
        retained_admin_aux = []
        for entry in admin_aux_index.get("entries", []):
            if entry.get("workspace_id") == workspace_id:
                if isinstance(entry.get("kind"), str) and isinstance(entry.get("id"), str):
                    deletions.append((entry["kind"], entry["id"]))
            else:
                retained_admin_aux.append(entry)
        admin_index_records.append((
            "workspace_admin_aux_index",
            admin_aux_index_id,
            {"entries": retained_admin_aux},
        ))
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
        scheduler_id = self._workspace_history_scheduler_id()
        scheduler = self.store.get("workspace_history_scheduler", scheduler_id)
        scheduler_records: list[tuple[str, str, dict[str, Any]]] = []
        if scheduler is not None:
            deleted_ids = {
                record_id for kind, record_id in deletions
                if kind == "workspace_history_job"
            }
            scheduler["job_ids"] = [
                item for item in scheduler.get("job_ids", ())
                if item not in deleted_ids
            ]
            scheduler_records.append((
                "workspace_history_scheduler", scheduler_id, scheduler
            ))
        outcome = {"workspace_id": workspace_id, "removed": True}
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [
                *due_records,
                *operation_redactions,
                *scheduler_records,
                *admin_index_records,
            ],
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
        deletions: list[tuple[str, str]] = []
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
        profile_index_id = self._workspace_admin_profile_index_id()
        profile_index = self.store.get(
            "workspace_admin_profile_index", profile_index_id
        ) or {"request_ids": []}
        retained_request_ids: list[str] = []
        removed_by_workspace: dict[str, set[str]] = {}
        for record_id in profile_index.get("request_ids", []):
            if not isinstance(record_id, str):
                continue
            stored = self.store.get("workspace_admin_request", record_id)
            if stored is None:
                continue
            workspace_id = stored.get("workspace_id")
            if (
                self._admin_request_terminal(stored.get("state"))
                and float(stored.get("updated_at", stored.get("created_at", now)))
                + ADMIN_REPLAY_RETENTION_SECONDS
                <= now
            ):
                deletions.append(("workspace_admin_request", record_id))
                decision_digest = stored.get("decision_digest")
                if isinstance(workspace_id, str) and isinstance(decision_digest, str):
                    deletions.append((
                        "workspace_admin_decision",
                        self._workspace_admin_decision_id(
                            workspace_id, decision_digest
                        ),
                    ))
                if isinstance(workspace_id, str):
                    removed_by_workspace.setdefault(workspace_id, set()).add(record_id)
                continue
            retained_request_ids.append(record_id)
            if stored.get("state") != "pending" or float(stored.get("expires_at", 0)) > now:
                continue
            request = dict(stored)
            request["state"] = "expired"
            request["updated_at"] = now
            records.append(("workspace_admin_request", record_id, request))
            if isinstance(workspace_id, str):
                changed_workspaces.add(workspace_id)
        if retained_request_ids != profile_index.get("request_ids", []):
            records.append((
                "workspace_admin_profile_index",
                profile_index_id,
                {"request_ids": retained_request_ids},
            ))
        for workspace_id, removed_ids in removed_by_workspace.items():
            index_id = self._workspace_admin_workspace_index_id(workspace_id)
            workspace_index = self.store.get(
                "workspace_admin_workspace_index", index_id
            ) or {"workspace_id": workspace_id, "request_ids": []}
            records.append((
                "workspace_admin_workspace_index",
                index_id,
                {
                    "workspace_id": workspace_id,
                    "request_ids": [
                        item for item in workspace_index.get("request_ids", [])
                        if item not in removed_ids
                    ],
                },
            ))
        aux_index_id = self._workspace_admin_aux_index_id()
        aux_index = self.store.get("workspace_admin_aux_index", aux_index_id) or {
            "entries": [],
        }
        retained_aux = []
        for entry in aux_index.get("entries", []):
            if float(entry.get("expires_at", now + 1)) <= now:
                if isinstance(entry.get("kind"), str) and isinstance(entry.get("id"), str):
                    deletions.append((entry["kind"], entry["id"]))
            else:
                retained_aux.append(entry)
        if retained_aux != aux_index.get("entries", []):
            records.append((
                "workspace_admin_aux_index",
                aux_index_id,
                {"entries": retained_aux},
            ))
        if not records and not deletions:
            return
        self.store.put_and_delete(records, deletions)
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
        self._advance_workspace_retention_jobs()
        self._advance_workspace_search_jobs()
        self._advance_workspace_history_jobs()

    def _advance_workspace_search_jobs(self) -> None:
        """Advance one restart-safe 128-event search batch per scheduler tick."""

        for workspace in self.store.list("workspace")[:MAX_WORKSPACES]:
            state = self.store.get(
                "workspace_search_state",
                self._workspace_search_state_id(str(workspace.get("id", ""))),
            )
            if state is None or state.get("status") != "rebuilding":
                continue
            self._advance_workspace_search_rebuild(workspace)
            self._workspace_changed(
                str(workspace["id"]), resource_kind="search_index"
            )
            break

    def _advance_workspace_retention_jobs(self) -> None:
        """Advance at most one bounded local pruning batch per scheduler tick."""

        now = time.time()
        for workspace in self.store.list("workspace")[:MAX_WORKSPACES]:
            if workspace.get("retention_days") is None:
                continue
            state = self.store.get(
                "workspace_retention_state",
                self._workspace_retention_state_id(str(workspace.get("id", ""))),
            )
            if state is not None and state.get("status") == "complete" and float(
                state.get("next_due_at", 0)
            ) > now:
                continue
            outcome, records, deletions = self._workspace_retention_batch_plan(
                workspace, RETENTION_PRUNE_BATCH_DEFAULT
            )
            self.store.put_and_delete(
                records,
                deletions,
                redact_command_cache=bool(deletions),
            )
            if outcome.get("pruned_this_batch"):
                self._workspace_changed(
                    workspace["id"], resource_kind="retention_pruning"
                )
            break

    def _workspace_history_scope(
        self, workspace: dict[str, Any], conversation_id: str
    ) -> tuple[dict[str, Any], VerifiedWorkspaceChannel | None]:
        direct = self.store.get(
            "workspace_direct", self._workspace_direct_record_id(conversation_id)
        )
        if direct is not None:
            participants = sorted(
                str(item) for item in direct.get("participant_member_ids", ())
            )
            if (
                len(participants) != 2
                or workspace.get("local_member_id") not in participants
                or workspace_direct_conversation_id(workspace["id"], participants)
                != conversation_id
            ):
                raise ContactNotApproved("Workspace direct history is not available")
            return ({
                "kind": "direct",
                "conversation_id": conversation_id,
                "channel_digest": None,
                "participant_member_ids": participants,
            }, None)
        channel_record = self._require_workspace_channel(
            workspace["id"], conversation_id
        )
        head = channel_record.get("head_hash")
        channel = (
            self._workspace_channel_by_digest(head) if isinstance(head, str) else None
        )
        if channel is None or channel_record.get("state") == "forked":
            raise ValidationError("Workspace channel history is suspended")
        if (
            channel.visibility == "private"
            and workspace.get("local_member_id") not in channel.member_ids
        ):
            raise ContactNotApproved("Workspace channel history is not available")
        return ({
            "kind": channel.visibility,
            "conversation_id": conversation_id,
            "channel_digest": channel.digest,
            "participant_member_ids": [],
        }, channel)

    def _workspace_history_devices(
        self,
        workspace: dict[str, Any],
        scope: dict[str, Any],
        channel: VerifiedWorkspaceChannel | None,
    ) -> list[tuple[Any, Any]]:
        manifest = self._workspace_current_manifest(workspace)
        if scope["kind"] == "direct":
            allowed = set(scope["participant_member_ids"])
        elif channel is not None and channel.visibility == "private":
            allowed = set(channel.member_ids)
        else:
            allowed = {member.member_id for member in manifest.members}
        devices = [
            (member, device)
            for member in manifest.members
            if member.member_id in allowed
            for device in member.devices
        ]
        devices.sort(key=lambda item: item[1].device_id)
        return devices[:MAX_HISTORY_STREAMS]

    def _workspace_history_streams(
        self,
        workspace: dict[str, Any],
        scope: dict[str, Any],
        channel: VerifiedWorkspaceChannel | None,
    ) -> list[dict[str, Any]]:
        streams: list[dict[str, Any]] = []
        for _member, device in self._workspace_history_devices(
            workspace, scope, channel
        ):
            head = self.store.get(
                "workspace_stream_coverage",
                self._workspace_stream_head_id(
                    workspace["id"], scope["conversation_id"], device.device_id
                ),
            ) or {}
            high_water = max(0, int(head.get("high_water", 0)))
            if high_water >= (1 << 63) - 1:
                continue
            seen_ranges = [[1, high_water]] if high_water else []
            gaps = [
                [int(item[0]), int(item[1])]
                for item in head.get("gaps", ())[:MAX_HISTORY_RANGES]
                if isinstance(item, list)
                and len(item) == 2
                and all(isinstance(value, int) for value in item)
            ]
            streams.append({
                "author_device_id": device.device_id,
                "known_high_water": high_water,
                "retained_floor": max(1, int(head.get("retained_floor", 1))),
                "head_digest": head.get("head_digest") if high_water else None,
                "seen_ranges": seen_ranges,
                "gaps": gaps,
                "request_ranges": [[high_water + 1, (1 << 63) - 1]],
            })
        if not streams:
            raise ValidationError("No workspace history streams are eligible")
        return streams

    @staticmethod
    def _public_workspace_history_job(job: dict[str, Any]) -> dict[str, Any]:
        return {
            "workspace_id": job["workspace_id"],
            "conversation_id": job["conversation_id"],
            "conversation_kind": job["scope"]["kind"],
            "status": job.get("status", "waiting_peer"),
            "recovered_events": int(job.get("recovered_events", 0)),
            "verified_pages": int(job.get("verified_pages", 0)),
            "received_bytes": int(job.get("received_bytes", 0)),
            "peer_count": len(job.get("peers", ())),
            "peers_exhausted": int(job.get("peer_index", 0)),
            "missing_prerequisites": int(job.get("missing_prerequisites", 0)),
            "permanent_gaps": int(job.get("permanent_gaps", 0)),
            "peer_limited": bool(job.get("peer_limited", False)),
            "failure": job.get("failure"),
            "updated_at": float(job.get("updated_at", 0)),
            "known_complete": bool(job.get("known_complete", False)),
            "notice": (
                "Coverage is complete only within known signed stream heads. "
                "Other eligible peers may retain additional history."
            ),
        }

    def get_workspace_history_status(
        self, workspace_id: Any, conversation_id: Any
    ) -> dict[str, Any]:
        workspace = self._require_workspace(str(workspace_id))
        checked_conversation = str(uuid.UUID(str(conversation_id)))
        scope, channel = self._workspace_history_scope(
            workspace, checked_conversation
        )
        streams = self._workspace_history_streams(workspace, scope, channel)
        job = self.store.get(
            "workspace_history_job",
            self._workspace_history_job_id(workspace["id"], checked_conversation),
        )
        return {
            "workspace_id": workspace["id"],
            "conversation_id": checked_conversation,
            "conversation_kind": scope["kind"],
            "eligible": workspace.get("state") in {"active", "incomplete_sync"},
            "status": (
                self._public_workspace_history_job(job)["status"]
                if job is not None
                else "available"
            ),
            "job": self._public_workspace_history_job(job) if job is not None else None,
            "streams": [{
                "known_high_water": item["known_high_water"],
                "retained_floor": item["retained_floor"],
                "seen_ranges": item["seen_ranges"],
                "gaps": item["gaps"],
            } for item in streams],
            "known_complete": bool(job and job.get("known_complete")),
            "notice": (
                "Peers may have additional unknown retained history. Cooperative "
                "retention cannot guarantee remote availability or deletion. "
                "Locally pruned history and permanent gaps remain unavailable."
            ),
        }

    def start_workspace_history(
        self,
        workspace_id: Any,
        conversation_id: Any,
        operation_id: Any,
    ) -> dict[str, Any]:
        payload = {
            "workspace_id": workspace_id,
            "conversation_id": conversation_id,
        }
        operation_id, digest, replay = self._workspace_operation(
            "start_workspace_history", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(str(workspace_id))
        if workspace.get("state") not in {"active", "incomplete_sync"}:
            raise ContactNotApproved("Workspace history catch-up is unavailable")
        checked_conversation = str(uuid.UUID(str(conversation_id)))
        scope, channel = self._workspace_history_scope(
            workspace, checked_conversation
        )
        job_id = self._workspace_history_job_id(
            workspace["id"], checked_conversation
        )
        existing = self.store.get("workspace_history_job", job_id)
        if existing is not None and existing.get("status") not in {
            "cancelled", "dismissed", "failed", "peer_limited", "expired"
        }:
            outcome = self._public_workspace_history_job(existing)
            return self.store.commit_operation(operation_id, digest, outcome, [])
        scheduler_id = self._workspace_history_scheduler_id()
        scheduler = self.store.get("workspace_history_scheduler", scheduler_id) or {
            "job_ids": []
        }
        active_job_ids = [
            item for item in scheduler.get("job_ids", ()) if isinstance(item, str)
        ]
        workspace_job_ids = [
            item for item in workspace.get("history_job_ids", ()) if isinstance(item, str)
        ]
        if job_id not in active_job_ids and len(active_job_ids) >= MAX_HISTORY_JOBS_PER_PROFILE:
            raise ValidationError("This profile already has four active history jobs")
        if job_id not in workspace_job_ids and len(workspace_job_ids) >= MAX_HISTORY_JOBS_PER_WORKSPACE:
            raise ValidationError("This workspace already has two active history jobs")
        manifest = self._workspace_current_manifest(workspace)
        local_member_id = str(workspace["local_member_id"])
        local_device_id = str(workspace["local_device_id"])
        peers = [
            {
                "member_id": member.member_id,
                "device_id": device.device_id,
                "destination": device.destination_hash.hex(),
                "public_identity": _b64(device.public_identity),
                "hints": [dict(item) for item in device.hints[:2]],
            }
            for member, device in self._workspace_history_devices(
                workspace, scope, channel
            )
            if device.device_id != local_device_id and member.status == "active"
        ]
        streams = self._workspace_history_streams(workspace, scope, channel)
        now = int(time.time())
        job = {
            "id": job_id,
            "workspace_id": workspace["id"],
            "conversation_id": checked_conversation,
            "scope": scope,
            "streams": streams,
            "peers": peers,
            "peer_index": 0,
            "status": "waiting_peer" if not peers else "requesting",
            "recovered_events": 0,
            "verified_pages": 0,
            "received_bytes": 0,
            "missing_prerequisites": 0,
            "permanent_gaps": 0,
            "peer_limited": not peers,
            "known_complete": bool(peers),
            "expected_page": 0,
            "previous_response_digest": None,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        records: list[tuple[str, str, dict[str, Any]]] = []
        if peers:
            identity = self._identity
            if identity is None:
                raise ValidationError("Local identity is unavailable")
            request_id = _new_id()
            request_raw = create_workspace_history_request(
                identity,
                workspace_id=workspace["id"],
                request_id=request_id,
                requester_member_id=local_member_id,
                requester_device_id=local_device_id,
                manifest_digest=manifest.digest,
                scope=scope,
                streams=streams,
                event_limit=MAX_HISTORY_EVENTS,
                byte_limit=MAX_HISTORY_RESPONSE_BYTES,
                created_at=now,
                expires_at=now + MAX_HISTORY_REQUEST_LIFETIME_SECONDS,
            )
            request = verify_workspace_history_request(
                request_raw, manifest=manifest, now=now
            )
            peer = peers[0]
            found = find_device(manifest, peer["device_id"])
            if found is None:
                raise ValidationError("History peer is unavailable")
            delivery = self._workspace_delivery_record(
                workspace_id=workspace["id"],
                recipient_member_id=peer["member_id"],
                recipient_device=found[1],
                kind="workspace_history_request",
                document=request_raw,
                conversation_id=checked_conversation,
                priority=1,
            )
            delivery["expires_at"] = request.expires_at
            job.update({
                "request_id": request.request_id,
                "request_digest": request.digest,
                "request_replay_key": request.replay_key,
                "request_expires_at": request.expires_at,
                "current_delivery_id": delivery["id"],
            })
            records.extend([
                ("workspace_history_request", self._workspace_history_request_id(request.request_id), {
                    "workspace_id": workspace["id"],
                    "conversation_id": checked_conversation,
                    "job_id": job_id,
                    "peer_member_id": peer["member_id"],
                    "peer_device_id": peer["device_id"],
                    "serialized": request.serialized,
                    "digest": request.digest,
                    "expires_at": request.expires_at,
                    "page_index": 0,
                    "previous_response_digest": None,
                }),
                ("workspace_delivery", delivery["id"], delivery),
                *self._due_records(add=[delivery]),
            ])
        active_job_ids = [item for item in active_job_ids if item != job_id] + [job_id]
        workspace_job_ids = [item for item in workspace_job_ids if item != job_id] + [job_id]
        scheduler["job_ids"] = active_job_ids
        scheduler["updated_at"] = time.time()
        workspace["history_job_ids"] = workspace_job_ids
        workspace["updated_at"] = time.time()
        outcome = self._public_workspace_history_job(job)
        committed = self.store.commit_operation(
            operation_id,
            digest,
            outcome,
            [
                ("workspace_history_job", job_id, job),
                ("workspace_history_scheduler", scheduler_id, scheduler),
                ("workspace", self._workspace_record_id(workspace["id"]), workspace),
                *records,
            ],
        )
        self._workspace_changed(
            workspace["id"], conversation_id=checked_conversation,
            resource_kind="history",
        )
        return committed

    def cancel_workspace_history(
        self,
        workspace_id: Any,
        conversation_id: Any,
        operation_id: Any,
    ) -> dict[str, Any]:
        payload = {"workspace_id": workspace_id, "conversation_id": conversation_id}
        operation_id, digest, replay = self._workspace_operation(
            "cancel_workspace_history", operation_id, payload
        )
        if replay is not None:
            return replay
        workspace = self._require_workspace(str(workspace_id))
        checked_conversation = str(uuid.UUID(str(conversation_id)))
        job_id = self._workspace_history_job_id(workspace["id"], checked_conversation)
        job = self.store.get("workspace_history_job", job_id)
        if job is None:
            raise ValidationError("Workspace history job is unavailable")
        job["status"] = "cancelled"
        job["updated_at"] = time.time()
        scheduler_id = self._workspace_history_scheduler_id()
        scheduler = self.store.get("workspace_history_scheduler", scheduler_id) or {"job_ids": []}
        scheduler["job_ids"] = [item for item in scheduler.get("job_ids", ()) if item != job_id]
        workspace["history_job_ids"] = [item for item in workspace.get("history_job_ids", ()) if item != job_id]
        records: list[tuple[str, str, dict[str, Any]]] = [
            ("workspace_history_job", job_id, job),
            ("workspace_history_scheduler", scheduler_id, scheduler),
            ("workspace", self._workspace_record_id(workspace["id"]), workspace),
        ]
        delivery_id = job.get("current_delivery_id")
        if isinstance(delivery_id, str):
            delivery = self.store.get("workspace_delivery", delivery_id)
            if delivery is not None and delivery.get("state") not in FINAL_DELIVERY_STATES:
                delivery["state"] = DeliveryState.CANCELLED.value
                records.extend([
                    ("workspace_delivery", delivery_id, delivery),
                    *self._due_records(remove=[delivery_id]),
                ])
        outcome = self._public_workspace_history_job(job)
        committed = self.store.commit_operation(operation_id, digest, outcome, records)
        self._workspace_changed(workspace["id"], conversation_id=checked_conversation, resource_kind="history")
        return committed

    def list_workspace_history_gaps(
        self,
        workspace_id: Any,
        conversation_id: Any,
        cursor: Any = None,
        limit: Any = 32,
    ) -> dict[str, Any]:
        workspace = self._require_workspace(str(workspace_id))
        checked_conversation = str(uuid.UUID(str(conversation_id)))
        scope, channel = self._workspace_history_scope(workspace, checked_conversation)
        checked_limit = int(limit)
        if not 1 <= checked_limit <= MAX_HISTORY_GAP_PAGE:
            raise ValidationError("Workspace history gap limit is invalid")
        streams = self._workspace_history_streams(workspace, scope, channel)
        gaps = [
            {"kind": "permanent", "start": start, "end": end}
            for stream in streams
            for start, end in stream["gaps"]
        ] + [
            {"kind": "locally_pruned", "start": start, "end": end}
            for stream in streams
            for start, end in (
                self.store.get(
                    "workspace_stream_coverage",
                    self._workspace_stream_head_id(
                        workspace["id"], checked_conversation,
                        stream["author_device_id"],
                    ),
                ) or {}
            ).get("pruned_ranges", ())
        ]
        gaps.sort(key=lambda item: (item["start"], item["end"], item["kind"]))
        offset = 0
        if cursor is not None:
            opened = self.store.open_cursor(str(cursor))
            if opened.get("kind") != "workspace_history_gaps" or opened.get("workspace_id") != workspace["id"] or opened.get("conversation_id") != checked_conversation or opened.get("authorization_generation") != int(workspace.get("authorization_generation", 1)) or opened.get("retention_generation") != int(workspace.get("retention_generation", 1)):
                raise StaleCursor("Workspace history gap cursor is stale")
            offset = int(opened.get("offset", 0))
        page = gaps[offset:offset + checked_limit]
        next_cursor = None
        if offset + checked_limit < len(gaps):
            next_cursor = self.store.seal_cursor({
                "kind": "workspace_history_gaps",
                "workspace_id": workspace["id"],
                "conversation_id": checked_conversation,
                "authorization_generation": int(workspace.get("authorization_generation", 1)),
                "retention_generation": int(workspace.get("retention_generation", 1)),
                "offset": offset + checked_limit,
            })
        return {"gaps": page, "next_cursor": next_cursor}

    def _workspace_history_request_authorized(
        self,
        workspace: dict[str, Any],
        request: VerifiedWorkspaceHistoryRequest,
    ) -> tuple[VerifiedWorkspaceChannel | None, Any]:
        manifest = self._workspace_current_manifest(workspace)
        requester = find_device(manifest, request.requester_device_id)
        if (
            requester is None
            or requester[0].member_id != request.requester_member_id
            or requester[0].status != "active"
            or workspace.get("state") not in {"active", "incomplete_sync"}
        ):
            raise ContactNotApproved("Workspace history request is not authorized")
        scope = request.scope
        if scope["kind"] == "direct":
            participants = tuple(scope["participant_member_ids"])
            if (
                request.requester_member_id not in participants
                or workspace.get("local_member_id") not in participants
            ):
                raise ContactNotApproved("Workspace direct history is not authorized")
            return None, requester[1]
        channel_record = self.store.get(
            "workspace_channel",
            self._workspace_channel_record_id(scope["conversation_id"]),
        )
        current = (
            self._workspace_channel_by_digest(channel_record["head_hash"])
            if channel_record is not None
            and isinstance(channel_record.get("head_hash"), str)
            else None
        )
        if (
            current is None
            or current.digest != scope["channel_digest"]
            or current.visibility != scope["kind"]
            or channel_record.get("state") == "forked"
            or (
                current.visibility == "private"
                and request.requester_member_id not in current.member_ids
            )
        ):
            raise ContactNotApproved("Workspace channel history is not authorized")
        return current, requester[1]

    def _workspace_history_private_era_allows(
        self,
        current: VerifiedWorkspaceChannel,
        event_channel: VerifiedWorkspaceChannel,
        requester_member_id: str,
    ) -> bool:
        if (
            current.visibility != "private"
            or event_channel.visibility != "private"
            or current.channel_id != event_channel.channel_id
            or requester_member_id not in current.member_ids
            or requester_member_id not in event_channel.member_ids
        ):
            return False
        cursor = current
        for _ in range(MAX_CHANNEL_FETCH_CONTROLS):
            if cursor.digest == event_channel.digest:
                return True
            if not isinstance(cursor.previous_hash, str):
                return False
            predecessor = self._workspace_channel_by_digest(cursor.previous_hash)
            if (
                predecessor is None
                or requester_member_id not in predecessor.member_ids
            ):
                return False
            cursor = predecessor
        return False

    def _workspace_history_event_disclosable(
        self,
        request: VerifiedWorkspaceHistoryRequest,
        event: dict[str, Any],
        current_channel: VerifiedWorkspaceChannel | None,
    ) -> bool:
        if (
            event.get("workspace_id") != request.workspace_id
            or event.get("conversation_id") != request.scope["conversation_id"]
        ):
            return False
        if request.scope["kind"] == "direct":
            return (
                event.get("channel_digest") is None
                and tuple(event.get("audience_member_ids", ()))
                == tuple(request.scope["participant_member_ids"])
                and request.requester_member_id
                in request.scope["participant_member_ids"]
            )
        channel_digest = event.get("channel_digest")
        event_channel = (
            self._workspace_channel_by_digest(channel_digest)
            if isinstance(channel_digest, str)
            else None
        )
        if event_channel is None or current_channel is None:
            return False
        if request.scope["kind"] == "public":
            return (
                event_channel.visibility == "public"
                and event_channel.channel_id == current_channel.channel_id
            )
        return self._workspace_history_private_era_allows(
            current_channel, event_channel, request.requester_member_id
        )

    def _workspace_history_controls_for_events(
        self, events: Iterable[str]
    ) -> list[tuple[str, str]]:
        manifest_controls: dict[str, tuple[str, str]] = {}
        channel_controls: dict[str, tuple[str, str]] = {}
        for raw in events:
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            manifest_digest = event.get("manifest_digest")
            if isinstance(manifest_digest, str):
                record = self.store.get(
                    "workspace_manifest",
                    self._workspace_manifest_record_id(manifest_digest),
                )
                if record is not None and isinstance(record.get("serialized"), str):
                    manifest_controls[manifest_digest] = (
                        "workspace_manifest_root", record["serialized"]
                    )
            channel_digest = event.get("channel_digest")
            if isinstance(channel_digest, str):
                record = self.store.get(
                    "workspace_channel_control",
                    self._workspace_channel_control_id(channel_digest),
                )
                if record is not None and isinstance(record.get("serialized"), str):
                    kind = str(record.get("document_type", ""))
                    if kind in {
                        "workspace_channel_record", "workspace_channel_manifest",
                        "workspace_channel_transfer", "workspace_channel_recovery",
                    }:
                        channel_controls[channel_digest] = (kind, record["serialized"])
        return [
            *[manifest_controls[key] for key in sorted(manifest_controls)],
            *[channel_controls[key] for key in sorted(channel_controls)],
        ][:32]

    def _workspace_history_checkpoints_for_events(
        self, workspace_id: str, conversation_id: str, events: Iterable[str]
    ) -> list[str]:
        """Resolve checkpoint heads by opaque direct lookup, never a kind scan."""
        documents: dict[str, str] = {}
        for raw in events:
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                continue
            device_id = value.get("author_device_id")
            if not isinstance(device_id, str):
                continue
            head = self.store.get(
                "workspace_checkpoint_head",
                self.store.opaque_id(
                    "workspace-checkpoint-head",
                    workspace_id,
                    device_id,
                    conversation_id,
                ),
            )
            digest = head.get("checkpoint_digest") if head else None
            if not isinstance(digest, str):
                continue
            record = self.store.get(
                "workspace_event_checkpoint",
                self.store.opaque_id("workspace-event-checkpoint", digest),
            )
            if record is not None and isinstance(record.get("serialized"), str):
                documents[digest] = record["serialized"]
        return [documents[key] for key in sorted(documents)][:MAX_HISTORY_CHECKPOINTS]

    def _receive_workspace_history_request(
        self, wire: WorkspaceWirePayload, source_hash: Any
    ) -> bool:
        try:
            workspace = self._require_workspace(wire.workspace_id)
            current_manifest = self._workspace_current_manifest(workspace)
            request = verify_workspace_history_request(
                wire.document, manifest=current_manifest
            )
            current_channel, requester_device = (
                self._workspace_history_request_authorized(workspace, request)
            )
            if (
                not isinstance(source_hash, bytes)
                or requester_device.destination_hash != source_hash
            ):
                return False
            replay_id = self._workspace_history_replay_id(
                request.workspace_id, request.replay_key
            )
            if self.store.get("workspace_history_replay", replay_id) is not None:
                return False
            cursor_stream = 0
            cursor_range = 0
            cursor_sequence: int | None = None
            page_index = 0
            previous_response_digest = None
            continuation_record_id = None
            if request.continuation is not None:
                continuation_record_id = self._workspace_history_continuation_id(
                    request.continuation
                )
                state = self.store.get(
                    "workspace_history_continuation", continuation_record_id
                )
                if (
                    state is None
                    or state.get("consumed")
                    or float(state.get("expires_at", 0)) < time.time()
                    or state.get("requester_member_id") != request.requester_member_id
                    or state.get("requester_device_id") != request.requester_device_id
                    or state.get("source_hash") != source_hash.hex()
                    or state.get("scope") != request.scope
                    or state.get("streams") != list(request.streams)
                    or state.get("event_limit") != request.event_limit
                    or state.get("byte_limit") != request.byte_limit
                ):
                    return False
                cursor_stream = int(state.get("cursor_stream", 0))
                cursor_range = int(state.get("cursor_range", 0))
                cursor_sequence = int(state.get("cursor_sequence", 1))
                page_index = int(state.get("page_index", 0)) + 1
                previous_response_digest = state.get("response_digest")
            response_streams: list[dict[str, Any]] = []
            peer_heads: dict[str, int] = {}
            for stream in request.streams:
                head = self.store.get(
                    "workspace_stream_coverage",
                    self._workspace_stream_head_id(
                        request.workspace_id,
                        request.scope["conversation_id"],
                        stream["author_device_id"],
                    ),
                ) or {}
                high_water = max(0, int(head.get("high_water", 0)))
                floor = max(1, int(head.get("retained_floor", 1)))
                peer_heads[stream["author_device_id"]] = high_water
                available = [[floor, high_water]] if floor <= high_water else []
                gaps = [
                    [int(item[0]), int(item[1])]
                    for item in [
                        *head.get("gaps", ()), *head.get("pruned_ranges", ())
                    ][:MAX_HISTORY_RANGES]
                    if isinstance(item, list)
                    and len(item) == 2
                    and all(isinstance(value, int) for value in item)
                ]
                gaps.sort()
                merged_gaps: list[list[int]] = []
                for gap_start, gap_end in gaps:
                    if merged_gaps and gap_start <= merged_gaps[-1][1] + 1:
                        merged_gaps[-1][1] = max(merged_gaps[-1][1], gap_end)
                    else:
                        merged_gaps.append([gap_start, gap_end])
                response_streams.append({
                    "author_device_id": stream["author_device_id"],
                    "high_water": high_water,
                    "head_digest": head.get("head_digest") if high_water else None,
                    "retained_floor": floor,
                    "available_ranges": available,
                    "gaps": merged_gaps[:MAX_HISTORY_RANGES],
                })
            selected: list[str] = []
            selected_positions: list[tuple[int, int, int]] = []
            probes = 0
            stream_index = cursor_stream
            range_index = cursor_range
            sequence = cursor_sequence
            exhausted = False
            while probes < MAX_HISTORY_SEQUENCE_PROBES and len(selected) < request.event_limit:
                if stream_index >= len(request.streams):
                    exhausted = True
                    break
                stream = request.streams[stream_index]
                ranges = stream["request_ranges"]
                if range_index >= len(ranges):
                    stream_index += 1
                    range_index = 0
                    sequence = None
                    continue
                start, requested_end = ranges[range_index]
                peer_end = min(requested_end, peer_heads[stream["author_device_id"]])
                current_sequence = start if sequence is None else max(start, sequence)
                if current_sequence > peer_end:
                    range_index += 1
                    sequence = None
                    continue
                probes += 1
                sequence = current_sequence + 1
                coverage = self.store.get(
                    "workspace_stream_coverage",
                    self._workspace_stream_sequence_id(
                        request.workspace_id,
                        request.scope["conversation_id"],
                        stream["author_device_id"],
                        current_sequence,
                    ),
                )
                if coverage is None or coverage.get("pruned"):
                    continue
                event_id = coverage.get("event_id")
                event = (
                    self.store.get(
                        "workspace_event", self._workspace_event_record_id(event_id)
                    )
                    if isinstance(event_id, str)
                    else None
                )
                if (
                    event is None
                    or not isinstance(event.get("serialized"), str)
                    or not self._workspace_history_event_disclosable(
                        request, event, current_channel
                    )
                ):
                    continue
                selected.append(event["serialized"])
                selected_positions.append(
                    (stream_index, range_index, current_sequence)
                )
            if stream_index >= len(request.streams):
                exhausted = True
            identity = self._identity
            if identity is None:
                return False
            continuation = None if exhausted else hashlib.sha256(
                os.urandom(32) + request.digest.encode("ascii")
            ).hexdigest()
            while True:
                controls = self._workspace_history_controls_for_events(selected)
                checkpoints = self._workspace_history_checkpoints_for_events(
                    request.workspace_id,
                    request.scope["conversation_id"],
                    selected,
                )
                try:
                    response_raw = create_workspace_history_response(
                        identity,
                        request=request,
                        response_id=_new_id(),
                        responder_member_id=str(workspace["local_member_id"]),
                        responder_device_id=str(workspace["local_device_id"]),
                        page_index=page_index,
                        previous_response_digest=previous_response_digest,
                        streams=response_streams,
                        controls=controls,
                        checkpoints=checkpoints,
                        events=selected,
                        continuation=continuation,
                        complete=exhausted,
                    )
                    break
                except ValidationError as exc:
                    if "byte limit" not in str(exc) or not selected:
                        raise
                    popped_position = selected_positions.pop()
                    selected.pop()
                    stream_index, range_index, popped_sequence = popped_position
                    sequence = popped_sequence
                    exhausted = False
                    continuation = hashlib.sha256(
                        os.urandom(32) + request.digest.encode("ascii")
                    ).hexdigest()
            response = verify_workspace_history_response(
                response_raw, manifest=current_manifest, request=request
            )
            local_member = find_member(
                current_manifest, str(workspace["local_member_id"])
            )
            if local_member is None:
                return False
            delivery = self._workspace_delivery_record(
                workspace_id=workspace["id"],
                recipient_member_id=request.requester_member_id,
                recipient_device=requester_device,
                kind="workspace_history_response",
                document=response.serialized,
                conversation_id=request.scope["conversation_id"],
                priority=1,
            )
            delivery["expires_at"] = request.expires_at
            records: list[tuple[str, str, dict[str, Any]]] = [
                ("workspace_history_replay", replay_id, {
                    "workspace_id": request.workspace_id,
                    "request_digest": request.digest,
                    "expires_at": request.expires_at,
                    "created_at": time.time(),
                }),
                ("workspace_history_response_cache", self._workspace_history_response_id(response.response_id), {
                    "workspace_id": request.workspace_id,
                    "request_digest": request.digest,
                    "response_digest": response.digest,
                    "serialized": response.serialized,
                    "expires_at": request.expires_at,
                }),
                ("workspace_delivery", delivery["id"], delivery),
                *self._due_records(add=[delivery]),
            ]
            if continuation_record_id is not None:
                old_state = self.store.get(
                    "workspace_history_continuation", continuation_record_id
                )
                if old_state is not None:
                    old_state["consumed"] = True
                    records.append((
                        "workspace_history_continuation",
                        continuation_record_id,
                        old_state,
                    ))
            if continuation is not None:
                records.append((
                    "workspace_history_continuation",
                    self._workspace_history_continuation_id(continuation),
                    {
                        "workspace_id": request.workspace_id,
                        "requester_member_id": request.requester_member_id,
                        "requester_device_id": request.requester_device_id,
                        "source_hash": source_hash.hex(),
                        "scope": request.scope,
                        "streams": list(request.streams),
                        "event_limit": request.event_limit,
                        "byte_limit": request.byte_limit,
                        "cursor_stream": stream_index,
                        "cursor_range": range_index,
                        "cursor_sequence": sequence or 1,
                        "page_index": page_index,
                        "response_digest": response.digest,
                        "expires_at": request.expires_at,
                        "consumed": False,
                    },
                ))
            self.store.put_many(records)
            return True
        except (MeshChatError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return False

    def _receive_workspace_event_checkpoint(
        self, wire: WorkspaceWirePayload, source_hash: Any
    ) -> bool:
        try:
            value = json.loads(wire.document)
            manifest = self._workspace_manifest_by_digest(
                str(value.get("manifest_digest", ""))
            )
            if manifest is None:
                return False
            checkpoint = verify_workspace_event_checkpoint(
                wire.document, manifest=manifest
            )
            found = find_device(manifest, checkpoint.author_device_id)
            if (
                found is None
                or not isinstance(source_hash, bytes)
                or found[1].destination_hash != source_hash
            ):
                return False
            records: list[tuple[str, str, dict[str, Any]]] = [(
                "workspace_event_checkpoint",
                self.store.opaque_id(
                    "workspace-event-checkpoint", checkpoint.digest
                ),
                {
                    "workspace_id": checkpoint.workspace_id,
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "author_member_id": checkpoint.author_member_id,
                    "author_device_id": checkpoint.author_device_id,
                    "manifest_digest": checkpoint.manifest_digest,
                    "streams": list(checkpoint.streams),
                    "digest": checkpoint.digest,
                    "serialized": checkpoint.serialized,
                    "created_at": checkpoint.created_at,
                },
            )]
            for stream in checkpoint.streams:
                records.append((
                    "workspace_checkpoint_head",
                    self.store.opaque_id(
                        "workspace-checkpoint-head",
                        checkpoint.workspace_id,
                        checkpoint.author_device_id,
                        stream["conversation_id"],
                    ),
                    {
                        "workspace_id": checkpoint.workspace_id,
                        "conversation_id": stream["conversation_id"],
                        "author_device_id": checkpoint.author_device_id,
                        "high_water": stream["high_water"],
                        "checkpoint_digest": checkpoint.digest,
                    },
                ))
            self.store.put_many(records)
            return True
        except (MeshChatError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return False

    def _accept_workspace_history_control(
        self, workspace: dict[str, Any], kind: str, raw: str
    ) -> bool:
        value = json.loads(raw)
        if kind == "workspace_manifest_root":
            genesis = self._workspace_genesis(workspace)
            manifest = verify_workspace_manifest(
                raw,
                expected_workspace_id=workspace["id"],
                expected_authority_destination=genesis.owner_device.destination_hash,
            )
            current = self._workspace_current_manifest(workspace)
            if manifest.epoch > current.epoch:
                return False
            epoch_record = self.store.get(
                "workspace_manifest_epoch",
                self._workspace_manifest_epoch_id(workspace["id"], manifest.epoch),
            )
            if epoch_record is not None and epoch_record.get("digest") != manifest.digest:
                workspace["state"] = "forked"
                workspace["security_error"] = "manifest_fork"
                self.store.put(
                    "workspace", self._workspace_record_id(workspace["id"]), workspace
                )
                return False
            self.store.put_many([
                ("workspace_manifest", self._workspace_manifest_record_id(manifest.digest), self._manifest_record(manifest)),
                self._manifest_epoch_record(manifest),
            ])
            return True
        manifest_digest = (
            value.get("offer", {}).get("manifest_digest")
            if kind == "workspace_channel_transfer"
            and isinstance(value.get("offer"), dict)
            else value.get("manifest_digest")
        )
        if not isinstance(manifest_digest, str):
            return False
        manifest = self._workspace_manifest_by_digest(manifest_digest)
        if manifest is None:
            return False
        if kind == "workspace_channel_record":
            channel = verify_workspace_channel_record(raw, manifest=manifest)
        elif kind == "workspace_channel_manifest":
            channel = verify_workspace_channel_manifest(raw, manifest=manifest)
        elif kind in {"workspace_channel_transfer", "workspace_channel_recovery"}:
            predecessor_digest = (
                value.get("offer", {}).get("channel_head")
                if kind == "workspace_channel_transfer"
                else value.get("channel_head")
            )
            predecessor = (
                self._workspace_channel_by_digest(predecessor_digest)
                if isinstance(predecessor_digest, str)
                else None
            )
            if predecessor is None:
                return False
            channel = (
                verify_workspace_channel_transfer(
                    raw, channel=predecessor, manifest=manifest
                )
                if kind == "workspace_channel_transfer"
                else verify_workspace_channel_recovery(
                    raw, channel=predecessor, manifest=manifest
                )
            )
        else:
            return False
        version_id = self._workspace_channel_version_id(
            channel.workspace_id, channel.channel_id, channel.version
        )
        existing = self.store.get("workspace_channel_version", version_id)
        if existing is not None and existing.get("digest") != channel.digest:
            channel_summary = self.store.get(
                "workspace_channel",
                self._workspace_channel_record_id(channel.channel_id),
            )
            if channel_summary is not None:
                channel_summary["state"] = "forked"
                channel_summary["security_error"] = "channel_control_conflict"
                self.store.put(
                    "workspace_channel",
                    self._workspace_channel_record_id(channel.channel_id),
                    channel_summary,
                )
            return False
        self.store.put_many([
            ("workspace_channel_control", self._workspace_channel_control_id(channel.digest), self._workspace_channel_control_record(channel, document_type=kind)),
            self._workspace_channel_version_record(channel),
        ])
        return True

    def _queue_workspace_history_continuation(
        self,
        workspace: dict[str, Any],
        job: dict[str, Any],
        continuation: str | None,
        *,
        next_peer: bool = False,
    ) -> list[tuple[str, str, dict[str, Any]]]:
        peer_index = int(job.get("peer_index", 0)) + (1 if next_peer else 0)
        peers = job.get("peers", ())
        if peer_index >= len(peers):
            job["status"] = "complete_known" if job.get("known_complete") else "peer_limited"
            job["peer_limited"] = not bool(job.get("known_complete"))
            job["peer_index"] = peer_index
            job["updated_at"] = time.time()
            return [("workspace_history_job", job["id"], job)]
        identity = self._identity
        if identity is None:
            job["status"] = "failed"
            job["failure"] = "identity_unavailable"
            return [("workspace_history_job", job["id"], job)]
        manifest = self._workspace_current_manifest(workspace)
        streams = (
            self._workspace_history_streams(
                workspace,
                job["scope"],
                self._workspace_channel_by_digest(job["scope"]["channel_digest"])
                if isinstance(job["scope"].get("channel_digest"), str)
                else None,
            )
            if next_peer else list(job["streams"])
        )
        now = int(time.time())
        request_raw = create_workspace_history_request(
            identity,
            workspace_id=workspace["id"],
            request_id=_new_id(),
            requester_member_id=str(workspace["local_member_id"]),
            requester_device_id=str(workspace["local_device_id"]),
            manifest_digest=manifest.digest,
            scope=job["scope"],
            streams=streams,
            event_limit=MAX_HISTORY_EVENTS,
            byte_limit=MAX_HISTORY_RESPONSE_BYTES,
            continuation=continuation,
            created_at=now,
            expires_at=now + MAX_HISTORY_REQUEST_LIFETIME_SECONDS,
        )
        request = verify_workspace_history_request(
            request_raw, manifest=manifest, now=now
        )
        peer = peers[peer_index]
        found = find_device(manifest, peer["device_id"])
        if found is None or found[0].status != "active":
            job["peer_index"] = peer_index
            return self._queue_workspace_history_continuation(
                workspace, job, None, next_peer=True
            )
        delivery = self._workspace_delivery_record(
            workspace_id=workspace["id"],
            recipient_member_id=peer["member_id"],
            recipient_device=found[1],
            kind="workspace_history_request",
            document=request.serialized,
            conversation_id=job["conversation_id"],
            priority=1,
        )
        delivery["expires_at"] = request.expires_at
        job.update({
            "peer_index": peer_index,
            "streams": streams,
            "status": "requesting",
            "request_id": request.request_id,
            "request_digest": request.digest,
            "request_replay_key": request.replay_key,
            "request_expires_at": request.expires_at,
            "current_delivery_id": delivery["id"],
            "updated_at": time.time(),
        })
        return [
            ("workspace_history_job", job["id"], job),
            ("workspace_history_request", self._workspace_history_request_id(request.request_id), {
                "workspace_id": workspace["id"],
                "conversation_id": job["conversation_id"],
                "job_id": job["id"],
                "peer_member_id": peer["member_id"],
                "peer_device_id": peer["device_id"],
                "serialized": request.serialized,
                "digest": request.digest,
                "expires_at": request.expires_at,
                "page_index": int(job.get("expected_page", 0)),
                "previous_response_digest": job.get("previous_response_digest"),
            }),
            ("workspace_delivery", delivery["id"], delivery),
            *self._due_records(add=[delivery]),
        ]

    def _receive_workspace_history_response(
        self, wire: WorkspaceWirePayload, source_hash: Any
    ) -> bool:
        try:
            value = json.loads(wire.document)
            request_id = value.get("request_id")
            if not isinstance(request_id, str):
                return False
            stored_request = self.store.get(
                "workspace_history_request",
                self._workspace_history_request_id(request_id),
            )
            if stored_request is None or float(stored_request.get("expires_at", 0)) < time.time():
                return False
            workspace = self._require_workspace(wire.workspace_id)
            request_value = json.loads(stored_request["serialized"])
            request_manifest = self._workspace_manifest_by_digest(
                request_value.get("manifest_digest", "")
            )
            if request_manifest is None:
                return False
            request = verify_workspace_history_request(
                stored_request["serialized"], manifest=request_manifest,
                now=min(int(time.time()), int(stored_request["expires_at"])),
            )
            response = verify_workspace_history_response(
                wire.document,
                manifest=request_manifest,
                request=request,
            )
            responder = find_device(request_manifest, response.responder_device_id)
            if (
                responder is None
                or not isinstance(source_hash, bytes)
                or responder[1].destination_hash != source_hash
                or responder[0].member_id != stored_request.get("peer_member_id")
                or response.responder_device_id != stored_request.get("peer_device_id")
            ):
                return False
            replay_id = self._workspace_history_response_id(response.response_id)
            if self.store.get("workspace_history_response_replay", replay_id) is not None:
                return False
            job = self.store.get("workspace_history_job", stored_request["job_id"])
            if job is None or job.get("status") in {"cancelled", "dismissed"}:
                return False
            if (
                response.page_index != int(stored_request.get("page_index", 0))
                or response.previous_response_digest
                != stored_request.get("previous_response_digest")
            ):
                return False
            job["status"] = "verifying"
            self.store.put("workspace_history_job", job["id"], job)
            for kind, raw in response.controls:
                if not self._accept_workspace_history_control(workspace, kind, raw):
                    job["missing_prerequisites"] = int(job.get("missing_prerequisites", 0)) + 1
            checkpoint_records: list[tuple[str, str, dict[str, Any]]] = []
            anchored_heads: list[tuple[Any, dict[str, Any]]] = []
            current_manifest = self._workspace_current_manifest(workspace)
            current_channel = None
            if request.scope["kind"] in {"public", "private"}:
                channel_summary = self.store.get(
                    "workspace_channel",
                    self._workspace_channel_record_id(request.scope["conversation_id"]),
                )
                if channel_summary is not None:
                    current_channel = self._workspace_channel_by_digest(
                        str(channel_summary.get("head_hash", ""))
                    )
            permitted_checkpoint_digests = (
                set()
                if request.scope["kind"] == "direct"
                else set(current_manifest.removal_checkpoint_digests)
                if request.scope["kind"] == "public"
                else set(current_channel.removal_checkpoint_digests)
                if current_channel is not None
                else set()
            )
            for checkpoint_raw in response.checkpoints:
                checkpoint_value = json.loads(checkpoint_raw)
                checkpoint_manifest = self._workspace_manifest_by_digest(
                    str(checkpoint_value.get("manifest_digest", ""))
                )
                if checkpoint_manifest is None:
                    job["missing_prerequisites"] = int(job.get("missing_prerequisites", 0)) + 1
                    continue
                checkpoint = verify_workspace_event_checkpoint(
                    checkpoint_raw, manifest=checkpoint_manifest
                )
                matching_stream = next((
                    stream for stream in checkpoint.streams
                    if stream["conversation_id"] == request.scope["conversation_id"]
                ), None)
                if matching_stream is None:
                    continue
                checkpoint_record_id = self.store.opaque_id(
                    "workspace-event-checkpoint", checkpoint.digest
                )
                checkpoint_records.append((
                    "workspace_event_checkpoint",
                    checkpoint_record_id,
                    {
                        "workspace_id": checkpoint.workspace_id,
                        "checkpoint_id": checkpoint.checkpoint_id,
                        "author_member_id": checkpoint.author_member_id,
                        "author_device_id": checkpoint.author_device_id,
                        "manifest_digest": checkpoint.manifest_digest,
                        "streams": list(checkpoint.streams),
                        "digest": checkpoint.digest,
                        "serialized": checkpoint.serialized,
                        "created_at": checkpoint.created_at,
                    },
                ))
                checkpoint_records.append((
                    "workspace_checkpoint_head",
                    self.store.opaque_id(
                        "workspace-checkpoint-head",
                        checkpoint.workspace_id,
                        checkpoint.author_device_id,
                        matching_stream["conversation_id"],
                    ),
                    {
                        "workspace_id": checkpoint.workspace_id,
                        "conversation_id": matching_stream["conversation_id"],
                        "author_device_id": checkpoint.author_device_id,
                        "high_water": matching_stream["high_water"],
                        "checkpoint_digest": checkpoint.digest,
                    },
                ))
                catalog_id = self.store.opaque_id(
                    "workspace-checkpoint-catalog",
                    checkpoint.workspace_id,
                    checkpoint.author_device_id,
                )
                catalog = self.store.get("workspace_checkpoint_catalog", catalog_id) or {
                    "workspace_id": checkpoint.workspace_id,
                    "author_device_id": checkpoint.author_device_id,
                    "entries": [],
                }
                entries = [
                    item for item in catalog.get("entries", ())
                    if item.get("conversation_id") != matching_stream["conversation_id"]
                ]
                entries.append({
                    "conversation_id": matching_stream["conversation_id"],
                    "channel_digest": matching_stream["channel_digest"],
                    "high_water": matching_stream["high_water"],
                    "checkpoint_digest": checkpoint.digest,
                })
                entries.sort(key=lambda item: item["conversation_id"])
                catalog["entries"] = entries[-MAX_HISTORY_STREAMS:]
                checkpoint_records.append((
                    "workspace_checkpoint_catalog", catalog_id, catalog
                ))
                if checkpoint.digest in permitted_checkpoint_digests:
                    anchored_heads.append((checkpoint, matching_stream))
            # Prove each supplied inactive-author chain backwards from a
            # permitted checkpoint head.  Only events connected byte-for-byte
            # by predecessor digests inherit the anchor.
            response_events_by_digest: dict[str, dict[str, Any]] = {}
            for raw in response.events:
                value = json.loads(raw)
                response_events_by_digest[
                    hashlib.sha256(raw.encode("utf-8")).hexdigest()
                ] = value
            history_checkpoint_digests: set[str] = set()
            for checkpoint, stream in anchored_heads:
                digest_cursor: str | None = stream["head_digest"]
                expected_sequence = int(stream["high_water"])
                while digest_cursor is not None:
                    candidate = response_events_by_digest.get(digest_cursor)
                    if (
                        candidate is None
                        or candidate.get("author_device_id") != checkpoint.author_device_id
                        or candidate.get("conversation_id") != request.scope["conversation_id"]
                        or candidate.get("sequence") != expected_sequence
                    ):
                        break
                    history_checkpoint_digests.add(digest_cursor)
                    digest_cursor = candidate.get("previous_event_digest")
                    expected_sequence -= 1
                    if expected_sequence < 1:
                        break
            recovered = 0
            pending_before = len([
                item for item in self.store.list("workspace_pending_event")
                if item.get("workspace_id") == workspace["id"]
            ])
            for raw in response.events:
                event_value = json.loads(raw)
                event_id = event_value.get("event_id")
                if not isinstance(event_id, str):
                    continue
                accepted = self._accept_workspace_event(
                    WorkspaceWirePayload(
                        kind="workspace_event",
                        logical_id=event_id,
                        workspace_id=workspace["id"],
                        expires_at=request.expires_at,
                        document=raw,
                    ),
                    drain_pending=False,
                    history_checkpoint_digests=history_checkpoint_digests,
                )
                if accepted:
                    recovered += 1
            self._drain_workspace_pending_controls(workspace["id"])
            self._drain_workspace_pending_events(workspace["id"])
            pending_after = len([
                item for item in self.store.list("workspace_pending_event")
                if item.get("workspace_id") == workspace["id"]
            ])
            job["missing_prerequisites"] = int(job.get("missing_prerequisites", 0)) + max(0, pending_after - pending_before)
            peer_coverage_records = []
            advertised_complete = True
            for stream in response.streams:
                local = self.store.get(
                    "workspace_stream_coverage",
                    self._workspace_stream_head_id(
                        workspace["id"], job["conversation_id"],
                        stream["author_device_id"],
                    ),
                ) or {}
                advertised_complete = advertised_complete and int(local.get("high_water", 0)) >= int(stream["high_water"])
                peer_coverage_records.append((
                    "workspace_history_peer_coverage",
                    self.store.opaque_id(
                        "workspace-history-peer-coverage", workspace["id"],
                        job["conversation_id"], response.responder_device_id,
                        stream["author_device_id"],
                    ),
                    {
                        "workspace_id": workspace["id"],
                        "conversation_id": job["conversation_id"],
                        "peer_device_id": response.responder_device_id,
                        **stream,
                        "response_digest": response.digest,
                        "updated_at": time.time(),
                    },
                ))
            job["recovered_events"] = int(job.get("recovered_events", 0)) + recovered
            job["verified_pages"] = int(job.get("verified_pages", 0)) + 1
            job["received_bytes"] = int(job.get("received_bytes", 0)) + len(response.serialized.encode("utf-8"))
            job["expected_page"] = response.page_index + 1
            job["previous_response_digest"] = response.digest
            job["known_complete"] = bool(job.get("known_complete", True)) and advertised_complete
            job["updated_at"] = time.time()
            records: list[tuple[str, str, dict[str, Any]]] = [
                ("workspace_history_response_replay", replay_id, {
                    "workspace_id": workspace["id"],
                    "request_digest": request.digest,
                    "response_digest": response.digest,
                    "expires_at": request.expires_at,
                }),
                *checkpoint_records,
                *peer_coverage_records,
            ]
            if response.continuation is not None:
                records.extend(self._queue_workspace_history_continuation(
                    workspace, job, response.continuation
                ))
            else:
                records.extend(self._queue_workspace_history_continuation(
                    workspace, job, None, next_peer=True
                ))
            self.store.put_many(records)
            self._workspace_changed(
                workspace["id"], conversation_id=job["conversation_id"],
                resource_kind="history",
            )
            return True
        except (MeshChatError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return False

    def _advance_workspace_history_jobs(self) -> None:
        scheduler = self.store.get(
            "workspace_history_scheduler", self._workspace_history_scheduler_id()
        )
        if scheduler is None:
            return
        now = time.time()
        for job_id in list(scheduler.get("job_ids", ()))[:MAX_HISTORY_JOBS_PER_PROFILE]:
            job = self.store.get("workspace_history_job", job_id)
            if job is None or job.get("status") in {
                "cancelled", "dismissed", "complete_known", "peer_limited", "failed"
            }:
                continue
            if float(job.get("request_expires_at", now + 1)) >= now:
                continue
            workspace = self.store.get(
                "workspace", self._workspace_record_id(str(job.get("workspace_id", "")))
            )
            if workspace is None or workspace.get("state") not in {"active", "incomplete_sync"}:
                job["status"] = "authorization_changed"
                job["updated_at"] = now
                self.store.put("workspace_history_job", job_id, job)
                continue
            job["status"] = "expired"
            job["failure"] = "stale_request"
            records = self._queue_workspace_history_continuation(
                workspace, job, None, next_peer=True
            )
            self.store.put_many(records)
            self._workspace_changed(
                workspace["id"], conversation_id=job.get("conversation_id"),
                resource_kind="history",
            )
            break

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
        elif wire.kind == "workspace_event_checkpoint":
            self._receive_workspace_event_checkpoint(
                wire, getattr(native, "source_hash", None)
            )
        elif wire.kind == "workspace_history_request":
            self._receive_workspace_history_request(
                wire, getattr(native, "source_hash", None)
            )
        elif wire.kind == "workspace_history_response":
            self._receive_workspace_history_response(
                wire, getattr(native, "source_hash", None)
            )
        elif wire.kind == "workspace_admin_request":
            self._receive_workspace_admin_request(wire)
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
        stored_workspaces = self.store.list("workspace")
        for item in stored_workspaces:
            changed = False
            if "mention_unread_count" not in item:
                item["mention_unread_count"] = self._workspace_mention_unread_count(
                    item
                )
                changed = True
            # Increment 7 profiles cannot contain thread records, so their
            # one-time migration does not need to inspect any message body.
            if "thread_unread_count" not in item:
                item["thread_unread_count"] = 0
                changed = True
            if changed:
                self.store.put(
                    "workspace", self._workspace_record_id(item["id"]), item
                )
        workspaces_by_id = {
            item["id"]: item
            for item in stored_workspaces
            if isinstance(item.get("id"), str)
        }
        workspaces = [self._public_workspace(item) for item in stored_workspaces]
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
        # Increment 10 migration is metadata-bounded here: startup already
        # opens at most the retained workspace/member/channel summaries. Event
        # and message bodies are rebuilt later in restart-safe bounded batches.
        for workspace in stored_workspaces:
            self._sync_workspace_search_directory(workspace, stored_channels)
        workspaces = [self._public_workspace(item) for item in stored_workspaces]
        workspaces.sort(key=lambda item: (item["created_at"], item["id"]))
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
        directs = [
            self._public_workspace_direct(item)
            for item in self.store.list("workspace_direct")
            if not item.get("hidden")
            and workspace_local_members.get(item.get("workspace_id"))
            in item.get("participant_member_ids", [])
        ]
        directs.sort(
            key=lambda item: (
                item["workspace_id"],
                -float(item.get("updated_at", 0)),
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
        admin_requests: list[dict[str, Any]] = []
        owner_review_counts: dict[str, int] = defaultdict(int)
        for stored_workspace in stored_workspaces:
            for request in self._refresh_workspace_admin_requests(stored_workspace):
                if request.get("dismissed"):
                    continue
                if (
                    request.get("requester_member_id")
                    != stored_workspace.get("local_member_id")
                    and stored_workspace.get("local_role") != WorkspaceRole.OWNER.value
                ):
                    continue
                admin_requests.append(
                    self._public_workspace_admin_request(request, stored_workspace)
                )
                if (
                    stored_workspace.get("local_role") == WorkspaceRole.OWNER.value
                    and request.get("direction") == "incoming"
                    and request.get("state") == "pending"
                ):
                    owner_review_counts[stored_workspace["id"]] += 1
        admin_requests.sort(
            key=lambda item: (float(item.get("created_at", 0)), item["id"]),
            reverse=True,
        )
        for public_workspace in workspaces:
            public_workspace["pending_owner_review_count"] = owner_review_counts.get(
                public_workspace["id"], 0
            )
        return {
            "workspaces": workspaces,
            "workspace_channels": channels,
            "workspace_directs": directs,
            "workspace_channel_transfers": channel_transfers,
            "workspace_join_requests": requests,
            "workspace_display_name_requests": name_requests,
            "workspace_admin_requests": admin_requests,
            "workspace_invitations": invitations,
            "workspace_drafts": [
                visible
                for draft in self.store.list("workspace_draft")
                if (
                    visible := self._workspace_draft_for_snapshot(
                        draft, workspaces_by_id
                    )
                )
                is not None
            ],
        }
