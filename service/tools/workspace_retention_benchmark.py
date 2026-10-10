"""Reproducible Increment 9 retained-history benchmark.

The fixture writes the same independently sealed record shapes consumed by the
workspace service.  It deliberately uses a bulk seeder instead of 50,000
user-facing sends: the benchmark is about an already-retained device, and a
real send for every fixture event would add 50,000 FULL-sync command commits to
the setup time without changing the read/prune workload under test.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import math
import os
import platform
import shutil
import sys
import tempfile
import time
import tracemalloc
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT / "src"))

import RNS

from mesh_chat.errors import StaleCursor, ValidationError
from mesh_chat.invitations import readable_fingerprint
from mesh_chat.models import DeliveryState
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore


NAMESPACE = uuid.UUID("d8ba2ddb-8c80-4ea8-a48f-a43e4a9bb5c7")
DAY = 24 * 60 * 60
PAGE_SIZE = 100
SEED_BATCH = 1_000


class NoRouteNetwork:
    """Network adapter that records any accidental route attempt."""

    interface_available = True

    def __init__(self) -> None:
        self.route_attempts = 0

    def invitation_hints(self) -> list[dict[str, Any]]:
        return []

    def remember_contact(self, _public_key: bytes, _destination: bytes) -> None:
        self.route_attempts += 1

    def recipient_ready(self, _destination: bytes) -> bool:
        self.route_attempts += 1
        return False

    def path_known(self, _destination: bytes) -> bool:
        self.route_attempts += 1
        return False

    def request_path(self, _destination: bytes) -> None:
        self.route_attempts += 1

    def send_with_fields(self, **_value: Any) -> str:
        self.route_attempts += 1
        raise AssertionError("send command attempted a route before returning")

    def apply_connection_settings(self, _settings: Any) -> None:
        return None

    def cancel_outbound(self, _logical_ids: set[str]) -> int:
        return 0

    def snapshot(self) -> dict[str, Any]:
        return {"interface_available": True, "interfaces": []}

    def shutdown(self) -> None:
        return None


class BatchWriter:
    def __init__(self, store: VaultStore, size: int = SEED_BATCH):
        self.store = store
        self.size = size
        self.pending: list[tuple[str, str, dict[str, Any]]] = []

    def add(self, *records: tuple[str, str, dict[str, Any]]) -> None:
        self.pending.extend(records)
        if len(self.pending) >= self.size:
            self.flush()

    def flush(self) -> None:
        if self.pending:
            self.store.put_many(self.pending)
            self.pending.clear()


def stable_uuid(label: str) -> str:
    return str(uuid.uuid5(NAMESPACE, label))


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def profile_record(identity: RNS.Identity, display_name: str) -> dict[str, Any]:
    public_key = identity.get_public_key()
    destination = RNS.Destination.hash(identity, "lxmf", "delivery")
    return {
        "display_name": display_name,
        "public_identity": base64.urlsafe_b64encode(public_key).decode("ascii"),
        "identity_hash": identity.hash.hex(),
        "destination_hash": destination.hex(),
        "fingerprint": readable_fingerprint(public_key),
        "created_at": time.time(),
    }


def open_service(
    profile_dir: Path,
    key: bytes,
    identity: RNS.Identity,
    *,
    initialize_profile: bool = False,
) -> tuple[MeshChatService, NoRouteNetwork]:
    store = VaultStore(profile_dir, key, allow_unprotected_for_tests=True)
    if initialize_profile:
        service = MeshChatService(store, profile_dir, lambda _event: None)
        store.put_many(
            [
                (
                    "identity",
                    "local",
                    {
                        "private_key": base64.urlsafe_b64encode(
                            identity.get_private_key()
                        ).decode("ascii")
                    },
                ),
                ("profile", "local", profile_record(identity, "Benchmark owner")),
            ]
        )
        service._identity = identity
    else:
        # Avoid starting Reticulum or touching host network configuration while
        # retaining the production constructor's encrypted startup reads.
        original_prepare = MeshChatService._prepare_lan_fallback
        original_start = MeshChatService._start_network
        MeshChatService._prepare_lan_fallback = lambda self: None  # type: ignore[method-assign]
        MeshChatService._start_network = lambda self, _name: None  # type: ignore[method-assign]
        try:
            service = MeshChatService(store, profile_dir, lambda _event: None)
        finally:
            MeshChatService._prepare_lan_fallback = original_prepare
            MeshChatService._start_network = original_start
    service._shutdown.set()
    service._retry_thread.join(timeout=1)
    service._identity = identity
    network = NoRouteNetwork()
    service.network = network  # type: ignore[assignment]
    return service, network


def close_service(service: MeshChatService) -> None:
    service._shutdown.set()
    service._retry_thread.join(timeout=1)
    service.network = None
    service.store.close()


def realistic_text(index: int) -> str:
    sizes = (96, 180, 320, 640, 1_280)
    prefix = f"Field report {index:05d}: "
    sentence = (
        "North relay stable; battery nominal; visibility mixed; check the "
        "watershed marker after the next scheduled pass. "
    )
    wanted = sizes[index % len(sizes)]
    return (prefix + sentence * (wanted // len(sentence) + 1))[:wanted]


def fake_members(workspace: dict[str, Any]) -> list[dict[str, Any]]:
    members = [dict(workspace["members"][0])]
    members[0]["device"] = dict(members[0]["device"])
    owner_public = hashlib.sha256(b"benchmark-owner-public").digest()
    members[0]["device"].setdefault(
        "public_identity", base64.urlsafe_b64encode(owner_public).decode("ascii")
    )
    for index in range(1, 8):
        member_id = stable_uuid(f"member-{index}")
        device_id = stable_uuid(f"device-{index}-0")
        public = hashlib.sha256(f"member-public-{index}".encode()).digest()
        destination = hashlib.sha256(f"member-destination-{index}".encode()).digest()[:16]
        members.append(
            {
                "id": member_id,
                "display_name": f"Member {index + 1}",
                "role": "member",
                "status": "active",
                "short_id": member_id.replace("-", "")[:6],
                "device": {
                    "id": device_id,
                    "destination_hash": destination.hex(),
                    "public_identity": base64.urlsafe_b64encode(public).decode("ascii"),
                    "fingerprint": readable_fingerprint(public),
                },
            }
        )
    return members


def record_counts(store: VaultStore) -> dict[str, int]:
    rows = store._db.execute(  # benchmark-only ciphertext metadata query
        "SELECT kind, COUNT(*) FROM records GROUP BY kind ORDER BY kind"
    ).fetchall()
    return {str(kind): int(count) for kind, count in rows}


def vault_stats(store: VaultStore, vault_path: Path) -> dict[str, int]:
    page_count = int(store._db.execute("PRAGMA page_count").fetchone()[0])
    free_pages = int(store._db.execute("PRAGMA freelist_count").fetchone()[0])
    return {
        "bytes": vault_path.stat().st_size,
        "page_count": page_count,
        "free_pages": free_pages,
    }


def working_set_bytes() -> int | None:
    if os.name != "nt":
        try:
            import resource
        except ImportError:
            return None

        try:
            peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        except (OSError, ValueError):
            return None
        return _unix_max_rss_bytes(peak_rss, sys.platform)

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    get_memory = ctypes.windll.psapi.GetProcessMemoryInfo  # type: ignore[attr-defined]
    get_memory.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(Counters),
        ctypes.c_ulong,
    ]
    get_memory.restype = ctypes.c_int
    ok = get_memory(
        ctypes.windll.kernel32.GetCurrentProcess(),  # type: ignore[attr-defined]
        ctypes.byref(counters),
        counters.cb,
    )
    return int(counters.PeakWorkingSetSize) if ok else None


def _unix_max_rss_bytes(max_rss: int | float, platform_name: str) -> int:
    """Normalize getrusage().ru_maxrss to bytes across Unix platforms."""

    # macOS reports bytes; Linux and the BSDs report kibibytes.
    multiplier = 1 if platform_name == "darwin" else 1024
    return int(max_rss) * multiplier


def physical_memory_bytes() -> int | None:
    if os.name != "nt":
        return None

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(status)
    ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))  # type: ignore[attr-defined]
    return int(status.ullTotalPhys) if ok else None


def add_retention_entry(
    service: MeshChatService,
    writer: BatchWriter,
    workspace_id: str,
    state: dict[str, Any],
    entry: dict[str, Any],
) -> str:
    page = state.get("page")
    if page is None or len(page["entries"]) >= PAGE_SIZE:
        if page is not None:
            writer.add(("workspace_retention_index", state["page_id"], page))
        page_id = service._workspace_retention_page_id(workspace_id, entry["event_id"])
        page = {
            "workspace_id": workspace_id,
            "previous_page": state.get("page_id"),
            "entries": [],
        }
        state["page"] = page
        state["page_id"] = page_id
    page["entries"].append(entry)
    return str(state["page_id"])


def seed_fixture(
    service: MeshChatService,
    workspace: dict[str, Any],
    channels: list[dict[str, Any]],
    event_count: int,
    *,
    history_age_days: int = 120,
) -> dict[str, Any]:
    if event_count < 2_000:
        raise ValueError("benchmark fixture requires at least 2,000 events")
    writer = BatchWriter(service.store)
    workspace_id = workspace["id"]
    members = fake_members(workspace)
    workspace = dict(workspace)
    workspace["members"] = members
    service.store.put("workspace", service._workspace_record_id(workspace_id), workspace)

    replies = int(event_count * 0.06)
    edits = int(event_count * 0.04)
    reactions = int(event_count * 0.04)
    deletes = int(event_count * 0.02)
    roots = event_count - replies - edits - reactions - deletes
    old_start = time.time() - history_age_days * DAY
    channel_by_id = {item["id"]: item for item in channels}
    roots_by_index: list[tuple[str, str]] = []
    root_message_records: dict[str, dict[str, Any]] = {}
    conversation_state: dict[str, dict[str, Any]] = {
        item["id"]: {
            "page": None,
            "page_id": None,
            "count": 0,
            "high_water": 0,
        }
        for item in channels
    }
    retention: dict[str, Any] = {"page": None, "page_id": None, "count": 0}
    stream_heads: dict[tuple[str, str], dict[str, Any]] = {}
    delivery_pending: list[dict[str, Any]] = []
    delivery_total = min(4_000, max(400, event_count // 10))

    def append_event(
        ordinal: int,
        *,
        event_type: str,
        conversation_id: str,
        target_event_id: str | None = None,
        thread_root: str | None = None,
        text: str | None = None,
        revision: int = 0,
        emoji: str | None = None,
        active: bool | None = None,
        revision_page_id: str | None = None,
        tombstone_page_id: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        event_id = stable_uuid(f"event-{ordinal}")
        member = members[ordinal % len(members)]
        author_device = member["device"]["id"]
        stream_key = (conversation_id, author_device)
        previous = stream_heads.get(stream_key)
        sequence = 1 if previous is None else int(previous["high_water"]) + 1
        event_digest = digest(f"event-digest-{ordinal}")
        channel_digest = channel_by_id[conversation_id]["head_hash"]
        created_at = old_start + ordinal
        serialized = json.dumps(
            {
                "type": "workspace_event",
                "id": event_id,
                "event_type": event_type,
                "text": text,
                "padding": realistic_text(ordinal),
            },
            separators=(",", ":"),
        )
        record = {
            "id": event_id,
            "workspace_id": workspace_id,
            "conversation_id": conversation_id,
            "author_member_id": member["id"],
            "author_device_id": author_device,
            "author_destination": member["device"]["destination_hash"],
            "event_type": event_type,
            "sequence": sequence,
            "previous_event_digest": None if previous is None else previous["head_digest"],
            "manifest_digest": workspace["manifest_hash"],
            "channel_digest": channel_digest,
            "conversation_kind": "channel",
            "audience_member_ids": [],
            "mention_member_ids": [],
            "thread_root": thread_root,
            "target_event_id": target_event_id,
            "base_revision": max(0, revision - 1),
            "revision": revision,
            "digest": event_digest,
            "serialized": serialized,
            "created_at": created_at,
        }
        if event_type == "edit":
            record["text"] = text
        if event_type == "reaction":
            record["emoji"] = emoji
            record["active"] = active
        if revision_page_id is not None:
            record["revision_page_id"] = revision_page_id
        if tombstone_page_id is not None:
            record["tombstone_page_id"] = tombstone_page_id
        retention_page_id = add_retention_entry(
            service,
            writer,
            workspace_id,
            retention,
            {
                "event_id": event_id,
                "event_record_id": service._workspace_event_record_id(event_id),
                "conversation_id": conversation_id,
                "event_type": event_type,
                "target_event_id": target_event_id,
                "thread_root": thread_root,
                "created_at": created_at,
            },
        )
        retention["count"] = int(retention["count"]) + 1
        record["retention_page_id"] = retention_page_id
        sequence_id = service._workspace_stream_sequence_id(
            workspace_id, conversation_id, author_device, sequence
        )
        writer.add(
            ("workspace_event", service._workspace_event_record_id(event_id), record),
            (
                "workspace_stream_coverage",
                sequence_id,
                {
                    "workspace_id": workspace_id,
                    "conversation_id": conversation_id,
                    "device_id": author_device,
                    "sequence": sequence,
                    "event_digest": event_digest,
                    "event_id": event_id,
                },
            ),
        )
        stream_heads[stream_key] = {
            "workspace_id": workspace_id,
            "conversation_id": conversation_id,
            "device_id": author_device,
            "high_water": sequence,
            "head_digest": event_digest,
            "channel_version": 1,
            "retained_floor": 1,
            "gaps": [],
        }
        return event_id, record

    for ordinal in range(roots):
        channel = channels[ordinal % len(channels)]
        conversation_id = channel["id"]
        text = realistic_text(ordinal)
        event_id, event_record = append_event(
            ordinal,
            event_type="message",
            conversation_id=conversation_id,
            text=text,
        )
        roots_by_index.append((event_id, conversation_id))
        page_state = conversation_state[conversation_id]
        page = page_state.get("page")
        if page is None or len(page["entries"]) >= PAGE_SIZE:
            if page is not None:
                writer.add(
                    ("workspace_conversation_index", page_state["page_id"], page)
                )
            page_id = service._workspace_page_record_id(
                workspace_id, conversation_id, event_id
            )
            page = {
                "workspace_id": workspace_id,
                "conversation_id": conversation_id,
                "previous_page": page_state.get("page_id"),
                "entries": [],
                "encoded_bytes": 0,
            }
            page_state["page"] = page
            page_state["page_id"] = page_id
        entry = {
            "event_id": event_id,
            "event_record_id": service._workspace_event_record_id(event_id),
            "message_record_id": service._workspace_message_record_id(event_id),
            "created_at": event_record["created_at"],
        }
        page["entries"].append(entry)
        page["encoded_bytes"] += len(
            json.dumps(entry, separators=(",", ":")).encode("utf-8")
        )
        page_state["count"] += 1
        page_state["high_water"] += 1
        member = members[ordinal % len(members)]
        direction = "outbound" if ordinal % 8 == 0 else "inbound"
        message = {
            "id": event_id,
            "workspace_id": workspace_id,
            "conversation_id": conversation_id,
            "direction": direction,
            "author_member_id": member["id"],
            "author_display_name": member["display_name"],
            "text": text,
            "original_text": text,
            "revision": 0,
            "deleted": False,
            "deletion_revision": None,
            "mutation_conflict": False,
            "mutation_frozen": False,
            "mutation_candidates": [],
            "reactions": [],
            "reaction_state_ids": [],
            "mention_member_ids": [],
            "thread_root": None,
            "sequence": event_record["sequence"],
            "event_digest": event_record["digest"],
            "conversation_kind": "channel",
            "created_at": event_record["created_at"],
            "conversation_index_page_id": page_state["page_id"],
        }
        if direction == "outbound":
            message["delivery_summary"] = {
                "people_total": 1 if ordinal < delivery_total else 0,
                "people_reached": 1 if ordinal < delivery_total and ordinal % 2 == 0 else 0,
                "people_partial": 0,
                "people_pending": 1 if ordinal < delivery_total and ordinal % 2 == 1 else 0,
                "people_failed": 0,
                "devices_total": 1 if ordinal < delivery_total else 0,
                "devices_reached": 1 if ordinal < delivery_total and ordinal % 2 == 0 else 0,
                "devices_pending": 1 if ordinal < delivery_total and ordinal % 2 == 1 else 0,
                "devices_failed": 0,
                "devices_expired": 0,
                "devices_cancelled": 0,
            }
        root_message_records[event_id] = message
        if ordinal < delivery_total:
            delivery_id = service.store.opaque_id("benchmark-delivery", event_id)
            recipient = members[(ordinal + 1) % len(members)]
            linked_device = stable_uuid(f"linked-device-{ordinal % 16}")
            pending = ordinal % 2 == 1
            delivery = {
                "id": delivery_id,
                "workspace_id": workspace_id,
                "event_id": event_id,
                "conversation_id": conversation_id,
                "kind": "workspace_event",
                "document": event_record["serialized"],
                "recipient_member_id": recipient["id"],
                "recipient_display_name": recipient["display_name"],
                "recipient_device_id": linked_device,
                "recipient_destination": recipient["device"]["destination_hash"],
                "recipient_public_identity": recipient["device"]["public_identity"],
                "recipient_hints": [],
                "state": (
                    DeliveryState.QUEUED.value
                    if pending
                    else DeliveryState.RECEIVED_BY_ENDPOINT.value
                ),
                "priority": 2,
                "attempt_count": 0,
                "created_at": event_record["created_at"],
                "next_attempt_at": time.time() + DAY,
                "expires_at": time.time() + 7 * DAY,
            }
            event_record["delivery_ids"] = [delivery_id]
            writer.add(
                (
                    "workspace_event",
                    service._workspace_event_record_id(event_id),
                    event_record,
                ),
                ("workspace_delivery", delivery_id, delivery),
            )
            if pending:
                delivery_pending.append(delivery)
        writer.add(
            (
                "workspace_message_state",
                service._workspace_message_record_id(event_id),
                message,
            )
        )

    # One-level thread replies are kept in root-scoped pages, not conversation
    # root pages.  One hundred roots produce a realistic active thread set.
    thread_roots = roots_by_index[: min(100, len(roots_by_index))]
    thread_entries: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for offset in range(replies):
        ordinal = roots + offset
        root_id, conversation_id = thread_roots[offset % len(thread_roots)]
        text = realistic_text(ordinal)
        event_id, event_record = append_event(
            ordinal,
            event_type="message",
            conversation_id=conversation_id,
            thread_root=root_id,
            text=text,
        )
        entries = thread_entries[root_id]
        position = len(entries) + 1
        page_seed = stable_uuid(
            f"thread-page-{root_id}-{(position - 1) // PAGE_SIZE}"
        )
        page_id = service._workspace_thread_page_id(
            workspace_id, root_id, page_seed
        )
        member = members[ordinal % len(members)]
        writer.add(
            (
                "workspace_message_state",
                service._workspace_message_record_id(event_id),
                {
                    "id": event_id,
                    "workspace_id": workspace_id,
                    "conversation_id": conversation_id,
                    "direction": "inbound",
                    "author_member_id": member["id"],
                    "author_display_name": member["display_name"],
                    "text": text,
                    "original_text": text,
                    "revision": 0,
                    "deleted": False,
                    "deletion_revision": None,
                    "mutation_conflict": False,
                    "mutation_frozen": False,
                    "mutation_candidates": [],
                    "reactions": [],
                    "reaction_state_ids": [],
                    "mention_member_ids": [],
                    "thread_root": root_id,
                    "thread_position": position,
                    "thread_index_page_id": page_id,
                    "sequence": event_record["sequence"],
                    "event_digest": event_record["digest"],
                    "conversation_kind": "channel",
                    "created_at": event_record["created_at"],
                },
            )
        )
        entries.append(
            {
                "event_id": event_id,
                "message_record_id": service._workspace_message_record_id(event_id),
                "position": position,
                "created_at": event_record["created_at"],
                "page_id": page_id,
            }
        )

    activity_entries: dict[str, dict[str, Any]] = {}
    activity_position = 0
    for root_id, entries in thread_entries.items():
        pages: list[list[dict[str, Any]]] = [
            entries[index : index + PAGE_SIZE]
            for index in range(0, len(entries), PAGE_SIZE)
        ]
        previous_page: str | None = None
        for page_entries in pages:
            page_id = str(page_entries[0]["page_id"])
            clean_entries = [
                {key: value for key, value in item.items() if key != "page_id"}
                for item in page_entries
            ]
            writer.add(
                (
                    "workspace_thread_index",
                    page_id,
                    {
                        "workspace_id": workspace_id,
                        "conversation_id": root_message_records[root_id][
                            "conversation_id"
                        ],
                        "root_event_id": root_id,
                        "previous_page": previous_page,
                        "entries": clean_entries,
                        "encoded_bytes": len(
                            json.dumps(clean_entries, separators=(",", ":")).encode(
                                "utf-8"
                            )
                        ),
                    },
                )
            )
            previous_page = page_id
        conversation_id = root_message_records[root_id]["conversation_id"]
        writer.add(
            (
                "workspace_thread_index",
                service._workspace_thread_index_id(workspace_id, root_id),
                {
                    "workspace_id": workspace_id,
                    "conversation_id": conversation_id,
                    "root_event_id": root_id,
                    "head_page": previous_page,
                    "count": len(entries),
                    "high_water": len(entries),
                    "authorization_generation": workspace["authorization_generation"],
                    "retention_generation": workspace["retention_generation"],
                },
            )
        )
        root_message = root_message_records[root_id]
        root_message["reply_count"] = len(entries)
        root_message["thread_unread_count"] = 0
        root_message["latest_reply_at"] = entries[-1]["created_at"]
        writer.add(
            (
                "workspace_message_state",
                service._workspace_message_record_id(root_id),
                root_message,
            ),
            (
                "workspace_thread",
                service._workspace_thread_record_id(workspace_id, root_id),
                {
                    "workspace_id": workspace_id,
                    "conversation_id": conversation_id,
                    "conversation_kind": "channel",
                    "root_event_id": root_id,
                    "reply_count": len(entries),
                    "unread_count": 0,
                    "high_water": len(entries),
                    "created_at": root_message["created_at"],
                    "updated_at": entries[-1]["created_at"],
                },
            ),
        )
        activity_position += 1
        activity_entries[root_id] = {
            "root_event_id": root_id,
            "conversation_id": conversation_id,
            "conversation_kind": "channel",
            "position": activity_position,
            "updated_at": entries[-1]["created_at"],
        }
    writer.add(
        (
            "workspace_thread_activity_index",
            service._workspace_thread_activity_id(workspace_id),
            {
                "workspace_id": workspace_id,
                "high_water": activity_position,
                "entries": activity_entries,
                "authorization_generation": workspace["authorization_generation"],
                "retention_generation": workspace["retention_generation"],
            },
        )
    )

    mutation_start = roots + replies
    mutation_specs: list[tuple[str, str, str, str | None, bool | None]] = []
    for offset in range(edits):
        target, conversation = roots_by_index[offset % roots]
        mutation_specs.append(("edit", target, conversation, None, None))
    for offset in range(reactions):
        target, conversation = roots_by_index[offset % roots]
        mutation_specs.append(("reaction", target, conversation, "👍", True))
    for offset in range(deletes):
        target, conversation = roots_by_index[(edits + offset) % roots]
        mutation_specs.append(("delete", target, conversation, None, None))

    revisions_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    tombstones_by_conversation: dict[str, list[dict[str, Any]]] = defaultdict(list)
    reaction_ids_by_target: dict[str, list[str]] = defaultdict(list)
    for offset, (event_type, target, conversation_id, emoji, active) in enumerate(
        mutation_specs
    ):
        ordinal = mutation_start + offset
        event_id = stable_uuid(f"event-{ordinal}")
        revision_page_id = service._workspace_revision_page_id(
            workspace_id, target, event_id
        )
        tombstone_page_id = (
            service._workspace_tombstone_page_id(
                workspace_id, conversation_id, event_id
            )
            if event_type == "delete"
            else None
        )
        text = realistic_text(ordinal) if event_type == "edit" else None
        event_id, event_record = append_event(
            ordinal,
            event_type=event_type,
            conversation_id=conversation_id,
            target_event_id=target,
            text=text,
            revision=1,
            emoji=emoji,
            active=active,
            revision_page_id=revision_page_id,
            tombstone_page_id=tombstone_page_id,
        )
        revision_entry = {
            "event_id": event_id,
            "event_record_id": service._workspace_event_record_id(event_id),
            "event_type": event_type,
            "revision": 1,
            "author_member_id": event_record["author_member_id"],
            "emoji": emoji,
            "active": active,
            "created_at": event_record["created_at"],
            "position": len(revisions_by_target[target]) + 1,
        }
        revisions_by_target[target].append(revision_entry)
        if event_type == "reaction":
            reaction_id = service._workspace_reaction_record_id(
                workspace_id, target, event_record["author_member_id"], str(emoji)
            )
            reaction_ids_by_target[target].append(reaction_id)
            writer.add(
                (
                    "workspace_reaction_state",
                    reaction_id,
                    {
                        "id": reaction_id,
                        "workspace_id": workspace_id,
                        "target_event_id": target,
                        "member_id": event_record["author_member_id"],
                        "emoji": emoji,
                        "active": True,
                        "revision": 1,
                        "mutation_frozen": False,
                        "updated_at": event_record["created_at"],
                    },
                )
            )
        elif event_type == "delete":
            tombstones_by_conversation[conversation_id].append(
                {
                    "event_id": event_id,
                    "event_record_id": service._workspace_event_record_id(event_id),
                    "target_event_id": target,
                    "message_record_id": service._workspace_message_record_id(target),
                    "position": len(tombstones_by_conversation[conversation_id]) + 1,
                    "created_at": event_record["created_at"],
                }
            )

    for target, entries in revisions_by_target.items():
        previous_page: str | None = None
        for page_entries in (
            entries[index : index + PAGE_SIZE]
            for index in range(0, len(entries), PAGE_SIZE)
        ):
            page_id = service._workspace_revision_page_id(
                workspace_id, target, page_entries[0]["event_id"]
            )
            writer.add(
                (
                    "workspace_revision_index",
                    page_id,
                    {
                        "workspace_id": workspace_id,
                        "conversation_id": root_message_records[target][
                            "conversation_id"
                        ],
                        "target_event_id": target,
                        "previous_page": previous_page,
                        "entries": page_entries,
                    },
                )
            )
            previous_page = page_id
        writer.add(
            (
                "workspace_revision_index",
                service._workspace_revision_index_id(workspace_id, target),
                {
                    "workspace_id": workspace_id,
                    "conversation_id": root_message_records[target][
                        "conversation_id"
                    ],
                    "target_event_id": target,
                    "head_page": previous_page,
                    "count": len(entries),
                    "high_water": len(entries),
                },
            )
        )
    for conversation_id, entries in tombstones_by_conversation.items():
        previous_page = None
        for page_entries in (
            entries[index : index + PAGE_SIZE]
            for index in range(0, len(entries), PAGE_SIZE)
        ):
            page_id = service._workspace_tombstone_page_id(
                workspace_id, conversation_id, page_entries[0]["event_id"]
            )
            writer.add(
                (
                    "workspace_tombstone_index",
                    page_id,
                    {
                        "workspace_id": workspace_id,
                        "conversation_id": conversation_id,
                        "previous_page": previous_page,
                        "entries": page_entries,
                    },
                )
            )
            previous_page = page_id
        writer.add(
            (
                "workspace_tombstone_index",
                service._workspace_tombstone_index_id(
                    workspace_id, conversation_id
                ),
                {
                    "workspace_id": workspace_id,
                    "conversation_id": conversation_id,
                    "head_page": previous_page,
                    "count": len(entries),
                    "high_water": len(entries),
                },
            )
        )

    # Apply mutation summaries only after all event/index records are staged.
    changed_targets = set(reaction_ids_by_target)
    changed_targets.update(
        item[1] for item in mutation_specs if item[0] == "delete"
    )
    for target in changed_targets:
        stored = service.store.get(
            "workspace_message_state", service._workspace_message_record_id(target)
        ) or root_message_records[target]
        stored = dict(stored)
        if target in reaction_ids_by_target:
            stored["reaction_state_ids"] = sorted(reaction_ids_by_target[target])
            stored["reactions"] = [
                {"emoji": "👍", "count": len(reaction_ids_by_target[target]), "reacted_by_self": False}
            ]
        if any(kind == "delete" and candidate == target for kind, candidate, *_ in mutation_specs):
            tombstone = next(
                entry
                for entries in tombstones_by_conversation.values()
                for entry in entries
                if entry["target_event_id"] == target
            )
            stored["text"] = ""
            stored["deleted"] = True
            stored["deletion_revision"] = 1
            stored["revision"] = 1
            stored["tombstone_event_id"] = tombstone["event_id"]
            stored["tombstone_retain_until"] = old_start + 7 * DAY
        writer.add(
            (
                "workspace_message_state",
                service._workspace_message_record_id(target),
                stored,
            )
        )

    for conversation_id, page_state in conversation_state.items():
        page = page_state.get("page")
        if page is not None:
            writer.add(
                ("workspace_conversation_index", page_state["page_id"], page)
            )
        writer.add(
            (
                "workspace_conversation_index",
                service._workspace_index_record_id(workspace_id, conversation_id),
                {
                    "workspace_id": workspace_id,
                    "conversation_id": conversation_id,
                    "head_page": page_state.get("page_id"),
                    "count": page_state["count"],
                    "high_water": page_state["high_water"],
                    "authorization_generation": workspace["authorization_generation"],
                    "retention_generation": workspace["retention_generation"],
                },
            )
        )
    if retention.get("page") is not None:
        writer.add(
            (
                "workspace_retention_index",
                retention["page_id"],
                retention["page"],
            )
        )
    writer.add(
        (
            "workspace_retention_index",
            service._workspace_retention_index_id(workspace_id),
            {
                "workspace_id": workspace_id,
                "head_page": retention.get("page_id"),
                "count": retention["count"],
                "high_water": retention["count"],
                "retention_generation": workspace["retention_generation"],
            },
        )
    )
    for (conversation_id, device_id), head in stream_heads.items():
        writer.add(
            (
                "workspace_stream_coverage",
                service._workspace_stream_head_id(
                    workspace_id, conversation_id, device_id
                ),
                head,
            )
        )
    due_by_shard: dict[int, dict[str, float]] = defaultdict(dict)
    for delivery in delivery_pending:
        due_by_shard[service._due_shard(delivery["id"])][delivery["id"]] = float(
            delivery["next_attempt_at"]
        )
    for shard, entries in due_by_shard.items():
        writer.add(
            (
                "workspace_due_work_index",
                service._due_record_id(shard),
                {"shard": shard, "entries": entries},
            )
        )
    writer.flush()
    return {
        "events": event_count,
        "roots": roots,
        "thread_replies": replies,
        "edits": edits,
        "reactions": reactions,
        "tombstones": deletes,
        "members": 8,
        "channels": len(channels),
        "linked_device_delivery_legs": delivery_total,
        "pending_queue_depth": len(delivery_pending),
        "revision_target": roots_by_index[0][0],
        "thread_root": thread_roots[0][0],
        "archived_channel": channels[-1]["id"],
    }


def audit_startup(service: MeshChatService) -> tuple[dict[str, Any], dict[str, int]]:
    counts: dict[str, int] = defaultdict(int)
    original_get = service.store.get
    original_list = service.store.list
    original_items = service.store.items

    def tracked_get(kind: str, record_id: str) -> dict[str, Any] | None:
        counts[f"get:{kind}"] += 1
        return original_get(kind, record_id)

    def tracked_list(kind: str) -> list[dict[str, Any]]:
        counts[f"list:{kind}"] += 1
        return original_list(kind)

    def tracked_items(kind: str) -> list[tuple[str, dict[str, Any]]]:
        counts[f"items:{kind}"] += 1
        return original_items(kind)

    service.store.get = tracked_get  # type: ignore[method-assign]
    service.store.list = tracked_list  # type: ignore[method-assign]
    service.store.items = tracked_items  # type: ignore[method-assign]
    try:
        snapshot = service.workspace_snapshot()
    finally:
        service.store.get = original_get  # type: ignore[method-assign]
        service.store.list = original_list  # type: ignore[method-assign]
        service.store.items = original_items  # type: ignore[method-assign]
    forbidden = {
        key: value
        for key, value in counts.items()
        if "workspace_event" in key or "workspace_delivery" in key
    }
    if forbidden:
        raise AssertionError(f"startup touched event/delivery bodies: {forbidden}")
    return snapshot, dict(sorted(counts.items()))


def run_benchmark(
    profile_dir: Path,
    *,
    event_count: int,
    samples: int,
) -> dict[str, Any]:
    def progress(message: str) -> None:
        print(f"[increment9-benchmark] {message}", file=sys.stderr, flush=True)

    key = hashlib.sha256(b"mesh-chat-increment-9-benchmark-key").digest()
    identity = RNS.Identity()
    tracemalloc.start()
    started = time.perf_counter()
    service, network = open_service(
        profile_dir, key, identity, initialize_profile=True
    )
    workspace = service.create_workspace(
        stable_uuid("create-workspace-operation"),
        "Increment 9 benchmark",
        "50,000-event retained local history fixture",
    )
    channels = [
        service._require_workspace_channel(
            workspace["id"], workspace["general_channel_id"]
        )
    ]
    for index in range(1, 32):
        channels.append(
            service.create_workspace_channel(
                workspace["id"],
                f"channel-{index:02d}",
                f"Benchmark stream {index:02d}",
                stable_uuid(f"create-channel-operation-{index}"),
            )
        )
    for channel in channels[-4:]:
        stored = service._require_workspace_channel(workspace["id"], channel["id"])
        stored["state"] = "archived"
        service.store.put(
            "workspace_channel",
            service._workspace_channel_record_id(channel["id"]),
            stored,
        )
        channel["state"] = "archived"
    vault_path = profile_dir / "mesh-chat.vault"
    base_stats = vault_stats(service.store, vault_path)
    progress(f"seeding {event_count:,} encrypted canonical events")
    seed_started = time.perf_counter()
    fixture = seed_fixture(service, workspace, channels, event_count)
    seed_seconds = time.perf_counter() - seed_started
    seeded_stats = vault_stats(service.store, vault_path)
    seeded_counts = record_counts(service.store)
    progress(f"seed complete in {seed_seconds:.3f}s; auditing startup")

    snapshot_started = time.perf_counter()
    snapshot, startup_reads = audit_startup(service)
    startup_ms = (time.perf_counter() - snapshot_started) * 1_000
    if len(snapshot["workspace_channels"]) != 32:
        raise AssertionError("startup summary did not return 32 bounded channel records")

    workspace_id = workspace["id"]
    general_id = workspace["general_channel_id"]
    retained = service.list_workspace_messages(workspace_id, general_id, limit=50)
    if len(retained["messages"]) != 50 or retained["next_cursor"] is None:
        raise AssertionError("latest retained page was not bounded to 50 messages")
    archived = service.list_workspace_messages(
        workspace_id, fixture["archived_channel"], limit=50
    )
    if len(archived["messages"]) != 50:
        raise AssertionError("archived retained history did not page")
    revisions = service.list_workspace_message_revisions(
        workspace_id, fixture["revision_target"], limit=50
    )
    if not revisions["revisions"]:
        raise AssertionError("revision history fixture was not readable")
    thread = service.list_workspace_thread_messages(
        workspace_id, fixture["thread_root"], limit=50
    )
    if not thread["replies"]:
        raise AssertionError("thread history fixture was not readable")
    tombstones = service.list_workspace_tombstones(workspace_id, general_id, limit=50)
    if not tombstones["tombstones"]:
        raise AssertionError("tombstone history fixture was not readable")

    warm_ms: list[float] = []
    progress(f"running {samples} warm latest-50 samples")
    for _ in range(samples):
        sample_started = time.perf_counter()
        page = service.list_workspace_messages(workspace_id, general_id, limit=50)
        warm_ms.append((time.perf_counter() - sample_started) * 1_000)
        if len(page["messages"]) != 50:
            raise AssertionError("warm sample returned an incomplete page")
    cursor_before_policy = retained["next_cursor"]
    pending_before_restart = fixture["pending_queue_depth"]
    close_service(service)

    cold_ms: list[float] = []
    progress(f"running {samples} process-cold latest-50 samples")
    for _ in range(samples):
        sample_service, _ = open_service(profile_dir, key, identity)
        sample_started = time.perf_counter()
        page = sample_service.list_workspace_messages(
            workspace_id, general_id, limit=50
        )
        cold_ms.append((time.perf_counter() - sample_started) * 1_000)
        if len(page["messages"]) != 50:
            raise AssertionError("process-cold sample returned an incomplete page")
        close_service(sample_service)

    service, network = open_service(profile_dir, key, identity)
    progress("changing signed retention policy and pruning bounded batches")
    service.update_workspace_retention(
        workspace_id, 30, stable_uuid("retention-policy-operation")
    )
    try:
        service.list_workspace_messages(
            workspace_id, general_id, cursor=cursor_before_policy, limit=50
        )
    except StaleCursor:
        stale_cursor = True
    else:
        raise AssertionError("retention change did not invalidate the old cursor")

    prune_started = time.perf_counter()
    prune_calls = 0
    prune_result: dict[str, Any] = {}
    while True:
        prune_result = service.prune_workspace_history(
            workspace_id,
            stable_uuid(f"prune-operation-{prune_calls}"),
            1_000,
        )
        prune_calls += 1
        progress(
            f"prune batch {prune_calls}: {prune_result['pruned']:,}/{event_count:,} events"
        )
        if not prune_result["needs_more"]:
            break
        if prune_calls > math.ceil(event_count / 100) + 5:
            raise AssertionError("bounded pruning did not converge")
    prune_seconds = time.perf_counter() - prune_started
    if prune_result["pruned"] != event_count:
        raise AssertionError(
            f"expected {event_count} pruned events, got {prune_result['pruned']}"
        )
    after_prune_stats = vault_stats(service.store, vault_path)
    after_prune_counts = record_counts(service.store)
    post_prune_page = service.list_workspace_messages(
        workspace_id, general_id, limit=50
    )
    if post_prune_page["messages"] or post_prune_page["history_status"] != "pruned":
        raise AssertionError("pruned conversation implied retained history was complete")
    close_service(service)

    service, network = open_service(profile_dir, key, identity)
    progress("verifying restart queue recovery and post-prune send")
    service._retry_workspace_outbox()
    pending_after_restart = int(
        service.store._db.execute(
            "SELECT COUNT(*) FROM records WHERE kind='workspace_delivery'"
        ).fetchone()[0]
    )
    if pending_after_restart != pending_before_restart:
        raise AssertionError("restart duplicated or discarded pending delivery work")
    send_event_id = stable_uuid("post-prune-chat-event")
    send_started = time.perf_counter()
    sent = service.send_workspace_message(
        workspace_id,
        general_id,
        "Chat continues after retained-history pruning and restart.",
        send_event_id,
        stable_uuid("post-prune-chat-operation"),
    )
    send_ms = (time.perf_counter() - send_started) * 1_000
    if sent["id"] != send_event_id or network.route_attempts:
        raise AssertionError("send did not commit independently of route attempts")
    continued = service.list_workspace_messages(workspace_id, general_id, limit=50)
    if [message["id"] for message in continued["messages"]] != [send_event_id]:
        raise AssertionError("post-prune chat did not resume from retained floor")
    try:
        service.send_workspace_message(
            workspace_id,
            general_id,
            "Attempt to resurrect a pruned event ID.",
            stable_uuid("event-0"),
            stable_uuid("resurrection-attempt-operation"),
        )
    except ValidationError:
        resurrection_blocked = True
    else:
        raise AssertionError("a pruned event ID was resurrected")

    final_stats = vault_stats(service.store, vault_path)
    final_counts = record_counts(service.store)
    _current, traced_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    elapsed = time.perf_counter() - started
    close_service(service)
    progress("benchmark complete")
    result = {
        "schema": "mesh-chat-increment-9-benchmark-v1",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "profile": {
            "os": platform.platform(),
            "processor": platform.processor(),
            "architecture": platform.machine(),
            "logical_cpu_count": os.cpu_count(),
            "physical_memory_bytes": physical_memory_bytes(),
            "python": platform.python_version(),
            "vault": "SQLite DELETE/FULL + per-record AES-256-GCM",
            "cold_definition": "new VaultStore and service instance; OS file cache not flushed",
        },
        "fixture": fixture,
        "measurements": {
            "total_seconds": round(elapsed, 3),
            "seed_seconds": round(seed_seconds, 3),
            "startup_summary_ms": round(startup_ms, 3),
            "latest_50_warm_ms": [round(value, 3) for value in warm_ms],
            "latest_50_warm_p95_ms": round(percentile(warm_ms, 0.95), 3),
            "latest_50_cold_ms": [round(value, 3) for value in cold_ms],
            "latest_50_cold_p95_ms": round(percentile(cold_ms, 0.95), 3),
            "send_commit_ms": round(send_ms, 3),
            "prune_seconds": round(prune_seconds, 3),
            "prune_calls": prune_calls,
            "python_tracemalloc_peak_bytes": traced_peak,
            "process_peak_working_set_bytes": working_set_bytes(),
            "vault": {
                "base": base_stats,
                "seeded": seeded_stats,
                "after_prune": after_prune_stats,
                "final": final_stats,
                "seed_growth_bytes": seeded_stats["bytes"] - base_stats["bytes"],
            },
            "record_counts": {
                "seeded": seeded_counts,
                "after_prune": after_prune_counts,
                "final": final_counts,
            },
        },
        "startup_read_audit": startup_reads,
        "assertions": {
            "startup_did_not_read_event_or_delivery_bodies": True,
            "latest_50_warm_p95_under_500_ms": percentile(warm_ms, 0.95) < 500,
            "latest_50_cold_p95_under_500_ms": percentile(cold_ms, 0.95) < 500,
            "archived_history_paged": len(archived["messages"]) == 50,
            "revision_history_paged": bool(revisions["revisions"]),
            "tombstone_history_paged": bool(tombstones["tombstones"]),
            "thread_history_paged": bool(thread["replies"]),
            "retention_cursor_became_stale": stale_cursor,
            "all_expired_events_pruned": prune_result["pruned"] == event_count,
            "permanent_pruned_status_preserved": post_prune_page["history_status"]
            == "pruned",
            "pending_work_restored_without_duplication": pending_after_restart
            == pending_before_restart,
            "pending_work_not_false_delivered": pending_after_restart
            == pending_before_restart,
            "send_returned_without_route_attempt": network.route_attempts == 0,
            "chat_continued_after_restart": True,
            "pruned_event_resurrection_blocked": resurrection_blocked,
        },
    }
    if not all(result["assertions"].values()):
        raise AssertionError(f"benchmark assertion failed: {result['assertions']}")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=int, default=50_000)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--keep-profile", action="store_true")
    return parser.parse_args()


def removable_benchmark_profile(profile_dir: Path) -> bool:
    """Limit --force cleanup to clearly named disposable benchmark profiles."""

    allowed_roots = (
        (SERVICE_ROOT.parent / ".test-tmp").resolve(),
        Path(tempfile.gettempdir()).resolve(),
    )
    if not profile_dir.name.startswith(("increment9-", "mesh-chat-increment9-")):
        return False
    return any(profile_dir.is_relative_to(root) for root in allowed_roots)


def main() -> int:
    args = parse_args()
    if args.samples < 30:
        raise SystemExit("--samples must be at least 30")
    temporary = args.profile is None
    profile_dir = (
        Path(tempfile.mkdtemp(prefix="mesh-chat-increment9-"))
        if temporary
        else args.profile.resolve()
    )
    if not temporary and profile_dir.exists():
        if not args.force:
            raise SystemExit("benchmark profile exists; pass --force to replace it")
        if not removable_benchmark_profile(profile_dir):
            raise SystemExit(
                "refusing to replace a profile outside a named Increment 9 "
                "benchmark directory under .test-tmp or the system temp directory"
            )
        shutil.rmtree(profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = run_benchmark(
            profile_dir, event_count=args.events, samples=args.samples
        )
        rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
    finally:
        if temporary and not args.keep_profile:
            shutil.rmtree(profile_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
