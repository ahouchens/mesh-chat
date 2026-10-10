"""Reproducible Increment 10 encrypted local-search benchmark.

This reuses the 50,000-event Increment 9 retained-history fixture, then removes
only derived search records to model a 0.2.29 upgrade.  Indexing is advanced by
the production 128-event restart-safe migration.  Search timings are measured
only after the migration reports ready.
"""

from __future__ import annotations

import argparse
import gc
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
from pathlib import Path
from typing import Any, Callable

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT / "src"))

import RNS

from mesh_chat.errors import StaleCursor

import workspace_retention_benchmark as base


def clear_derived_search(service: Any) -> None:
    for kind in (
        "workspace_search_state",
        "workspace_search_catalog",
        "workspace_search_document",
        "workspace_search_index",
    ):
        for record_id, _value in list(service.store.items(kind)):
            service.store.delete(kind, record_id)


def time_samples(
    samples: int, operation: Callable[[], dict[str, Any]]
) -> tuple[list[float], dict[str, Any]]:
    timings: list[float] = []
    last: dict[str, Any] = {}
    for _ in range(samples):
        started = time.perf_counter()
        last = operation()
        timings.append((time.perf_counter() - started) * 1_000)
    return timings, last


def add_hostile_candidates(
    service: Any, workspace: dict[str, Any], private_channel: dict[str, Any]
) -> dict[str, bool]:
    """Put unauthorized candidates behind real keyed index entries.

    The records deliberately model a corrupt/stale derived index.  Search must
    still enforce the canonical event audience and current conversation rule.
    """

    workspace_id = workspace["id"]
    local_member_id = workspace["local_member_id"]
    foreign_a = base.stable_uuid("hostile-foreign-a")
    foreign_b = base.stable_uuid("hostile-foreign-b")
    manifest_digest = workspace["manifest_hash"]
    now = time.time()
    cases = (
        (
            "dm",
            "dmleak sentinel",
            base.stable_uuid("hostile-dm-event"),
            base.stable_uuid("hostile-dm-conversation"),
            None,
            [foreign_a, foreign_b],
        ),
        (
            "private",
            "privateleak sentinel",
            base.stable_uuid("hostile-private-event"),
            private_channel["id"],
            private_channel["head_hash"],
            [],
        ),
    )
    for label, text, event_id, conversation_id, channel_digest, audience in cases:
        event = {
            "id": event_id,
            "workspace_id": workspace_id,
            "conversation_id": conversation_id,
            "author_member_id": foreign_a,
            "author_device_id": base.stable_uuid(f"hostile-{label}-device"),
            "event_type": "message",
            "sequence": 1,
            "previous_event_digest": None,
            "manifest_digest": manifest_digest,
            "channel_digest": channel_digest,
            "conversation_kind": "direct" if label == "dm" else "channel",
            "audience_member_ids": audience,
            "mention_member_ids": [],
            "thread_root": None,
            "digest": base.digest(f"hostile-{label}-digest"),
            "serialized": "encrypted-benchmark-placeholder",
            "created_at": now,
        }
        message = {
            "id": event_id,
            "workspace_id": workspace_id,
            "conversation_id": conversation_id,
            "direction": "inbound",
            "author_member_id": foreign_a,
            "author_display_name": "Unauthorized candidate",
            "text": text,
            "revision": 0,
            "deleted": False,
            "mention_member_ids": [],
            "thread_root": None,
            "sequence": 1,
            "event_digest": event["digest"],
            "conversation_kind": event["conversation_kind"],
            "created_at": now,
        }
        records = [
            (
                "workspace_event",
                service._workspace_event_record_id(event_id),
                event,
            ),
            (
                "workspace_message_state",
                service._workspace_message_record_id(event_id),
                message,
            ),
            *service._workspace_search_document_records(
                workspace,
                category="message",
                entity_id=event_id,
                text=text,
                active=True,
                sort_at=now,
                conversation_id=conversation_id,
            ),
        ]
        if label == "dm":
            records.append(
                (
                    "workspace_direct",
                    service._workspace_direct_record_id(conversation_id),
                    {
                        "id": conversation_id,
                        "workspace_id": workspace_id,
                        "participant_member_ids": [foreign_a, foreign_b],
                        "state": "open",
                        "hidden": False,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            )
        service.store.put_many(records)
    return {
        "workspace_owner_is_not_dm_participant": local_member_id
        not in [foreign_a, foreign_b],
        "dm_candidate_filtered": service.search_workspace(
            workspace_id, "dmleak", scope="messages"
        )["results"]
        == [],
        "private_candidate_filtered": service.search_workspace(
            workspace_id, "privateleak", scope="messages"
        )["results"]
        == [],
    }


def run_benchmark(
    profile_dir: Path, *, event_count: int, samples: int
) -> dict[str, Any]:
    def progress(message: str) -> None:
        print(f"[increment10-search] {message}", file=sys.stderr, flush=True)

    key = hashlib.sha256(b"mesh-chat-increment-10-search-benchmark-key").digest()
    identity = RNS.Identity()
    tracemalloc.start()
    total_started = time.perf_counter()
    service, network = base.open_service(
        profile_dir, key, identity, initialize_profile=True
    )
    workspace = service.create_workspace(
        base.stable_uuid("increment10-create-workspace"),
        "Increment 10 benchmark",
        "Encrypted local search over retained workspace data",
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
                base.stable_uuid(f"increment10-create-channel-{index}"),
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
    private_channel = service.create_workspace_channel(
        workspace["id"],
        "private-benchmark",
        "Private authorization probe",
        base.stable_uuid("increment10-create-private-channel"),
        "private",
        [workspace["local_member_id"]],
    )

    vault_path = profile_dir / "mesh-chat.vault"
    before_seed = base.vault_stats(service.store, vault_path)
    progress(f"seeding {event_count:,} retained encrypted events")
    seed_started = time.perf_counter()
    fixture = base.seed_fixture(
        service,
        workspace,
        channels,
        event_count,
        history_age_days=40,
    )
    seed_seconds = time.perf_counter() - seed_started
    before_index = base.vault_stats(service.store, vault_path)

    clear_derived_search(service)
    startup_started = time.perf_counter()
    snapshot, startup_reads = base.audit_startup(service)
    startup_ms = (time.perf_counter() - startup_started) * 1_000
    if snapshot["workspaces"][0]["search_index"]["status"] != "rebuilding":
        raise AssertionError("upgrade did not expose rebuilding state")
    if any(
        key.startswith(("list:workspace_message", "items:workspace_message"))
        for key in startup_reads
    ):
        raise AssertionError("startup scanned message state")

    progress("rebuilding keyed token shards in 128-event transactions")
    rebuild_started = time.perf_counter()
    rebuild_calls = 0
    while True:
        stored_workspace = service._require_workspace(workspace["id"])
        state = service._advance_workspace_search_rebuild(stored_workspace)
        rebuild_calls += 1
        if state["status"] != "rebuilding":
            break
        if rebuild_calls == 10:
            checkpoint = (state["rebuild_page_id"], state["rebuild_offset"], state["indexed_events"])
            base.close_service(service)
            service, network = base.open_service(profile_dir, key, identity)
            resumed_state = service.store.get(
                "workspace_search_state",
                service._workspace_search_state_id(workspace["id"]),
            )
            if resumed_state is None or (
                resumed_state["rebuild_page_id"],
                resumed_state["rebuild_offset"],
                resumed_state["indexed_events"],
            ) != checkpoint:
                raise AssertionError("restart did not preserve the rebuild cursor")
        if rebuild_calls > math.ceil(event_count / 128) + 2:
            raise AssertionError("bounded search rebuild did not converge")
    rebuild_seconds = time.perf_counter() - rebuild_started
    after_index = base.vault_stats(service.store, vault_path)
    indexed_counts = base.record_counts(service.store)
    relay_index = service.store.get(
        "workspace_search_index",
        service._workspace_search_token_id(workspace["id"], "relay"),
    )
    if relay_index is None:
        raise AssertionError("common token shard was not built")
    relay_count_before_restart = int(relay_index["count"])
    base.close_service(service)
    service, network = base.open_service(profile_dir, key, identity)
    relay_after_restart = service.store.get(
        "workspace_search_index",
        service._workspace_search_token_id(workspace["id"], "relay"),
    )
    if relay_after_restart is None or int(relay_after_restart["count"]) != relay_count_before_restart:
        raise AssertionError("restart duplicated keyed token references")

    workspace_id = workspace["id"]
    rare_token = f"{int(fixture['roots']) - 1:05d}"
    thread_token = f"{int(fixture['roots']):05d}"
    query_specs = {
        "common_message": ("relay stable", "messages"),
        "rare_message": (rare_token, "messages"),
        "no_result": ("obsidian nebula", "all"),
        "thread": (thread_token, "threads"),
        "person": ("Member", "people"),
        "channel": ("channel 31", "channels"),
    }
    timings: dict[str, list[float]] = {}
    search_examples: dict[str, dict[str, Any]] = {}
    progress(f"running {samples} warm samples for six query classes")
    for name, (query, scope) in query_specs.items():
        timings[name], search_examples[name] = time_samples(
            samples,
            lambda query=query, scope=scope: service.search_workspace(
                workspace_id, query, scope=scope, limit=25
            ),
        )
    timings["warm_first_page"], _warm = time_samples(
        samples,
        lambda: service.search_workspace(
            workspace_id, "relay stable", scope="messages", limit=25
        ),
    )
    if not search_examples["common_message"]["results"]:
        raise AssertionError("common message query returned no retained results")
    if len(search_examples["rare_message"]["results"]) != 1:
        raise AssertionError("rare message query did not return exactly one result")
    if search_examples["no_result"]["results"]:
        raise AssertionError("no-result query returned a candidate")
    if search_examples["thread"]["results"][0]["kind"] != "thread":
        raise AssertionError("thread query did not identify a reply")
    if search_examples["person"]["results"][0]["kind"] != "person":
        raise AssertionError("person query did not use the current display name")
    if search_examples["channel"]["results"][0]["kind"] != "channel":
        raise AssertionError("channel query did not return a channel model")

    common_page = service.search_workspace(
        workspace_id, "relay stable", scope="messages", limit=25
    )
    second_page = service.search_workspace(
        workspace_id,
        "relay stable",
        scope="messages",
        cursor=common_page["next_cursor"],
        limit=25,
    )
    first_ids = {item["id"] for item in common_page["results"]}
    second_ids = {item["id"] for item in second_page["results"]}
    pagination_unique = bool(first_ids and second_ids and first_ids.isdisjoint(second_ids))
    cursor_before_mutation = common_page["next_cursor"]

    whole_kind_calls: list[str] = []
    original_list = service.store.list
    original_items = service.store.items

    def reject_list(kind: str) -> list[dict[str, Any]]:
        whole_kind_calls.append(f"list:{kind}")
        raise AssertionError(f"query attempted list({kind})")

    def reject_items(kind: str) -> list[tuple[str, dict[str, Any]]]:
        whole_kind_calls.append(f"items:{kind}")
        raise AssertionError(f"query attempted items({kind})")

    service.store.list = reject_list  # type: ignore[method-assign]
    service.store.items = reject_items  # type: ignore[method-assign]
    try:
        service.search_workspace(workspace_id, rare_token, scope="messages")
    finally:
        service.store.list = original_list  # type: ignore[method-assign]
        service.store.items = original_items  # type: ignore[method-assign]

    progress(f"running {samples} process-cold first-page samples")
    base.close_service(service)
    cold_ms: list[float] = []
    for _ in range(samples):
        cold_service, _cold_network = base.open_service(profile_dir, key, identity)
        started = time.perf_counter()
        cold_page = cold_service.search_workspace(
            workspace_id, "relay stable", scope="messages", limit=25
        )
        cold_ms.append((time.perf_counter() - started) * 1_000)
        if len(cold_page["results"]) != 25:
            raise AssertionError("process-cold first page was incomplete")
        base.close_service(cold_service)
    service, network = base.open_service(profile_dir, key, identity)

    progress("checking mutation, access, pruning, and route-independent send behavior")
    send_started = time.perf_counter()
    editable = service.send_workspace_message(
        workspace_id,
        workspace["general_channel_id"],
        "obsoleteword live marker",
        base.stable_uuid("increment10-editable-event"),
        base.stable_uuid("increment10-editable-send"),
    )
    send_commit_ms = (time.perf_counter() - send_started) * 1_000
    service.edit_workspace_message(
        workspace_id,
        editable["id"],
        "winningword live marker",
        base.stable_uuid("increment10-edit-operation"),
        base.stable_uuid("increment10-edit-mutation"),
    )
    edit_replaced_old_term = (
        service.search_workspace(workspace_id, "obsoleteword")["results"] == []
        and service.search_workspace(workspace_id, "winningword")["results"][0]["id"]
        == editable["id"]
    )
    search_state_id = service._workspace_search_state_id(workspace_id)
    before_reaction_generation = service.store.get(
        "workspace_search_state", search_state_id
    )["search_generation"]
    service.set_workspace_reaction(
        workspace_id,
        editable["id"],
        "👍",
        True,
        base.stable_uuid("increment10-reaction-operation"),
        base.stable_uuid("increment10-reaction-mutation"),
    )
    after_reaction_generation = service.store.get(
        "workspace_search_state", search_state_id
    )["search_generation"]
    reaction_did_not_reindex_text = before_reaction_generation == after_reaction_generation
    service.hide_workspace_message(
        workspace_id,
        editable["id"],
        base.stable_uuid("increment10-hide-operation"),
    )
    hide_suppressed = service.search_workspace(workspace_id, "winningword")["results"] == []

    deletable = service.send_workspace_message(
        workspace_id,
        workspace["general_channel_id"],
        "deleteword live marker",
        base.stable_uuid("increment10-delete-event"),
        base.stable_uuid("increment10-delete-send"),
    )
    service.delete_workspace_message(
        workspace_id,
        deletable["id"],
        base.stable_uuid("increment10-delete-operation"),
        base.stable_uuid("increment10-delete-mutation"),
    )
    delete_suppressed = service.search_workspace(workspace_id, "deleteword")["results"] == []
    hostile = add_hostile_candidates(
        service,
        service._require_workspace(workspace_id),
        private_channel,
    )
    if cursor_before_mutation is None:
        raise AssertionError("common query did not produce a cursor")
    try:
        service.search_workspace(
            workspace_id,
            "relay stable",
            scope="messages",
            cursor=cursor_before_mutation,
            limit=25,
        )
    except StaleCursor:
        stale_cursor_failed = True
    else:
        stale_cursor_failed = False

    service.update_workspace_retention(
        workspace_id, 30, base.stable_uuid("increment10-retention-operation")
    )
    prune_result = service.prune_workspace_history(
        workspace_id,
        base.stable_uuid("increment10-prune-operation"),
        max_events=1_000,
    )
    expired_suppressed = service.search_workspace(
        workspace_id, rare_token, scope="messages"
    )["results"] == []
    base.close_service(service)
    service, network = base.open_service(profile_dir, key, identity)
    continued = service.send_workspace_message(
        workspace_id,
        workspace["general_channel_id"],
        "postprune beacon",
        base.stable_uuid("increment10-postprune-event"),
        base.stable_uuid("increment10-postprune-send"),
    )
    continued_search = service.search_workspace(workspace_id, "postprune")
    search_after_prune_restart = continued_search["results"][0]["id"] == continued["id"]

    raw_vault = vault_path.read_bytes()
    sqlite_plaintext_absent = all(
        marker not in raw_vault
        for marker in (
            b"relay stable",
            b"obsidian nebula",
            b"Member",
            b"channel-31",
            b"postprune beacon",
        )
    )
    final_stats = base.vault_stats(service.store, vault_path)
    final_counts = base.record_counts(service.store)
    _current_memory, traced_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    total_seconds = time.perf_counter() - total_started
    route_attempts = network.route_attempts
    base.close_service(service)

    p95 = {name: base.percentile(values, 0.95) for name, values in timings.items()}
    p95["process_cold_first_page"] = base.percentile(cold_ms, 0.95)
    assertions = {
        "all_first_page_p95_under_2_seconds": all(value < 2_000 for value in p95.values()),
        "startup_metadata_bounded": not any(
            "workspace_event" in key or "workspace_message_state" in key
            for key in startup_reads
        ),
        "query_used_no_whole_kind_scan": whole_kind_calls == [],
        "candidate_bound_observed": common_page["candidate_count"] <= 256,
        "shard_bound_observed": common_page["shard_pages_opened"] <= 8,
        "result_page_bound_observed": len(common_page["results"]) <= 50,
        "pagination_has_no_duplicates": pagination_unique,
        "restart_resumed_without_duplicate_references": int(relay_after_restart["count"])
        == relay_count_before_restart,
        "edit_replaced_old_term": edit_replaced_old_term,
        "reaction_did_not_reindex_text": reaction_did_not_reindex_text,
        "delete_suppressed_result": delete_suppressed,
        "local_hide_suppressed_result": hide_suppressed,
        "expired_or_pruned_result_suppressed": expired_suppressed,
        "stale_cursor_failed_explicitly": stale_cursor_failed,
        "search_survived_prune_and_restart": search_after_prune_restart,
        "ordinary_send_returned_without_route_attempt": route_attempts == 0,
        "sqlite_visible_plaintext_absent": sqlite_plaintext_absent,
        **hostile,
    }
    result = {
        "schema": "mesh-chat-increment-10-search-benchmark-v1",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "profile": {
            "os": platform.platform(),
            "processor": platform.processor(),
            "architecture": platform.machine(),
            "logical_cpu_count": os.cpu_count(),
            "physical_memory_bytes": base.physical_memory_bytes(),
            "python": platform.python_version(),
            "vault": "SQLite DELETE/FULL + per-record AES-256-GCM",
            "cold_definition": "new VaultStore and service instance; OS file cache not flushed",
        },
        "fixture": {
            **fixture,
            "real_channel_control_chains": len(channels) + 1,
            "private_authorization_probe": True,
            "hostile_nonparticipant_dm_candidate": True,
        },
        "measurements": {
            "total_seconds": round(total_seconds, 3),
            "seed_seconds": round(seed_seconds, 3),
            "startup_summary_ms": round(startup_ms, 3),
            "rebuild_seconds": round(rebuild_seconds, 3),
            "rebuild_transactions": rebuild_calls,
            "indexed_events": int(state["indexed_events"]),
            "query_samples_ms": {
                name: [round(value, 3) for value in values]
                for name, values in timings.items()
            },
            "query_p95_ms": {name: round(value, 3) for name, value in p95.items()},
            "process_cold_first_page_ms": [round(value, 3) for value in cold_ms],
            "send_commit_ms": round(send_commit_ms, 3),
            "common_candidate_count": common_page["candidate_count"],
            "common_shard_pages_opened": common_page["shard_pages_opened"],
            "pruned_this_batch": prune_result["pruned_this_batch"],
            "python_tracemalloc_peak_bytes": traced_peak,
            "process_peak_working_set_bytes": base.working_set_bytes(),
            "vault": {
                "before_seed": before_seed,
                "before_index": before_index,
                "after_index": after_index,
                "final": final_stats,
                "index_growth_bytes": after_index["bytes"] - before_index["bytes"],
            },
            "record_counts": {
                "after_index": indexed_counts,
                "final": final_counts,
            },
        },
        "startup_read_audit": startup_reads,
        "assertions": assertions,
    }
    if not all(assertions.values()):
        raise AssertionError(f"benchmark assertion failed: {assertions}")
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


def removable_profile(profile_dir: Path) -> bool:
    allowed_roots = (
        (SERVICE_ROOT.parent / ".test-tmp").resolve(),
        Path(tempfile.gettempdir()).resolve(),
    )
    return profile_dir.name.startswith(
        ("increment10-search-", "mesh-chat-increment10-search-")
    ) and any(profile_dir.is_relative_to(root) for root in allowed_roots)


def main() -> int:
    args = parse_args()
    if args.samples < 30:
        raise SystemExit("--samples must be at least 30")
    if args.events < 2_000:
        raise SystemExit("--events must be at least 2,000")
    temporary = args.profile is None
    profile_dir = (
        Path(tempfile.mkdtemp(prefix="mesh-chat-increment10-search-"))
        if temporary
        else args.profile.resolve()
    )
    if not temporary and profile_dir.exists():
        if not args.force:
            raise SystemExit("benchmark profile exists; pass --force to replace it")
        if not removable_profile(profile_dir):
            raise SystemExit("refusing to replace a non-benchmark profile")
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
            # A failed SQLite write can keep the connection alive until the
            # unwound benchmark frame is collected on Windows.
            gc.collect()
            shutil.rmtree(profile_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
