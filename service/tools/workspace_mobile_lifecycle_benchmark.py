"""Reproducible Increment 15 mobile lifecycle and notification benchmark.

The release gate seeds the maintained 50,000-event, eight-member, 32-channel
encrypted fixture and adds bounded notification/lifecycle probes without ever
starting a renderer or invoking a platform notification API.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tracemalloc
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = SERVICE_ROOT.parent
sys.path.insert(0, str(SERVICE_ROOT / "src"))
sys.path.insert(0, str(SERVICE_ROOT / "tools"))

import RNS

from mesh_chat.workspace_service import (
    MAX_NOTIFICATION_BATCH,
    MAX_NOTIFICATION_BODY_CHARS,
    MAX_NOTIFICATION_NATIVE_BYTES,
    MAX_NOTIFICATION_QUEUE,
    MAX_NOTIFICATION_TITLE_CHARS,
)

import workspace_linked_device_benchmark as linked
import workspace_retention_benchmark as scale


LIMITS = {
    "samples": 30,
    "notification_policy_p95_ms": 25.0,
    "durable_enqueue_p95_ms": 100.0,
    # This is a complete bounded 16-item batch, including current sealed-state
    # authorization for every route. The separate live-event latency limit
    # below covers the single-notification user-visible path.
    "native_dispatch_p95_ms": 750.0,
    "duplicate_suppression_p95_ms": 25.0,
    "background_transition_p95_ms": 100.0,
    "resume_no_change_p95_ms": 500.0,
    "resume_overflow_p95_ms": 750.0,
    "network_restore_p95_ms": 750.0,
    "notification_open_p95_ms": 100.0,
    "preference_update_p95_ms": 250.0,
    "restart_pending_work_p95_ms": 2_000.0,
    "accepted_to_native_request_p95_ms": 250.0,
    "notification_queue": MAX_NOTIFICATION_QUEUE,
    "notification_batch": MAX_NOTIFICATION_BATCH,
    "native_signal_bytes": MAX_NOTIFICATION_NATIVE_BYTES,
    "title_characters": MAX_NOTIFICATION_TITLE_CHARS,
    "body_characters": MAX_NOTIFICATION_BODY_CHARS,
}


def timed(samples: int, callback: Callable[[int], Any]) -> list[float]:
    values: list[float] = []
    for index in range(samples):
        started = time.perf_counter()
        callback(index)
        values.append((time.perf_counter() - started) * 1_000)
    return values


def summary(values: list[float]) -> dict[str, float]:
    return {
        "p50": round(scale.percentile(values, 0.50), 3),
        "p95": round(scale.percentile(values, 0.95), 3),
        "max": round(max(values), 3),
    }


def tool_output(command: list[str], environment: dict[str, str] | None = None) -> str | None:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    return output or None


def tool_version(
    command: list[str],
    environment: dict[str, str] | None = None,
    *,
    marker: str | None = None,
) -> str | None:
    output = tool_output(command, environment)
    if output is None:
        return None
    lines = output.splitlines()
    if marker is not None:
        matched = next((line.strip() for line in lines if marker in line), None)
        if matched is not None:
            return matched
    return lines[0].strip() if lines else None


def host_profile() -> dict[str, Any]:
    java = Path("C:/Program Files/Android/Android Studio/jbr/bin/java.exe")
    gradle_properties = (
        REPOSITORY
        / "src-tauri"
        / "gen"
        / "android"
        / "gradle"
        / "wrapper"
        / "gradle-wrapper.properties"
    )
    gradle_match = re.search(
        r"gradle-([0-9.]+)-",
        gradle_properties.read_text(encoding="utf-8")
        if gradle_properties.is_file()
        else "",
    )
    sdk = Path(os.environ.get("ANDROID_HOME", Path.home() / "AppData/Local/Android/Sdk"))
    api_levels = sorted(
        (item.name for item in (sdk / "platforms").glob("android-*") if item.is_dir()),
        reverse=True,
    )
    adb = sdk / "platform-tools" / "adb.exe"
    devices = tool_output([str(adb), "devices", "-l"]) if adb.is_file() else None
    return {
        "os": platform.platform(),
        "processor": platform.processor(),
        "architecture": platform.machine(),
        "logical_cpu_count": os.cpu_count(),
        "physical_memory_bytes": scale.physical_memory_bytes(),
        "python": platform.python_version(),
        "rust": tool_version(["rustc", "--version"]),
        "cargo": tool_version(["cargo", "--version"]),
        "node": tool_version([os.environ.get("MESH_CHAT_NODE", "node"), "--version"]),
        "java": tool_version([str(java), "-version"]) if java.is_file() else None,
        "gradle": f"Gradle {gradle_match.group(1)}" if gradle_match else None,
        "android_sdk": str(sdk) if sdk.is_dir() else None,
        "android_api_levels": api_levels,
        "android_devices": devices,
        "physical_android_battery": None,
        "physical_android_battery_reason": "No authorized disposable physical device was attached.",
        "vault": "SQLite DELETE/FULL + per-record AES-256-GCM",
    }


def notification_event(
    event: dict[str, Any],
    *,
    event_id: str | None = None,
    digest: str | None = None,
    mentions: tuple[str, ...] = (),
) -> SimpleNamespace:
    return SimpleNamespace(
        workspace_id=event["workspace_id"],
        conversation_id=event["conversation_id"],
        event_id=event_id or event["id"],
        digest=digest or event["digest"],
        event_type="message",
        author_member_id=event["author_member_id"],
        channel_digest=event["channel_digest"],
        thread_root=event.get("thread_root"),
        mentions=mentions,
    )


def run(profile: Path, event_count: int, samples: int) -> dict[str, Any]:
    if event_count < 2_000:
        raise ValueError("benchmark fixture requires at least 2,000 events")
    key = hashlib.sha256(b"mesh-chat-increment-15-primary-profile").digest()
    identity = RNS.Identity()
    tracemalloc.start()
    started = time.perf_counter()
    service, _network = scale.open_service(
        profile / "primary", key, identity, initialize_profile=True
    )
    workspace = service.create_workspace(
        scale.stable_uuid("increment15-create-workspace"),
        "Increment 15 benchmark",
        "Mobile lifecycle and local notifications",
    )
    workspace_id = workspace["id"]
    local_member_id = workspace["local_member_id"]
    channels = [
        service._require_workspace_channel(workspace_id, workspace["general_channel_id"])
    ]
    for index in range(1, 32):
        private = index % 4 == 0
        channels.append(
            service.create_workspace_channel(
                workspace_id,
                f"channel-{index:02d}",
                f"Lifecycle stream {index:02d}",
                scale.stable_uuid(f"increment15-channel-operation-{index}"),
                "private" if private else "public",
                [local_member_id] if private else None,
            )
        )
    for channel in channels[-4:]:
        stored = service._require_workspace_channel(workspace_id, channel["id"])
        stored["state"] = "archived"
        service.store.put(
            "workspace_channel",
            service._workspace_channel_record_id(channel["id"]),
            stored,
        )
        channel["state"] = "archived"

    vault_path = profile / "primary" / "mesh-chat.vault"
    vault_before = scale.vault_stats(service.store, vault_path)
    fixture = scale.seed_fixture(service, workspace, channels, event_count)
    vault_seeded = scale.vault_stats(service.store, vault_path)
    workspace = service._require_workspace(workspace_id)
    event_id = scale.stable_uuid("event-1")
    event_record = service.store.get(
        "workspace_event", service._workspace_event_record_id(event_id)
    )
    message_record = service.store.get(
        "workspace_message_state", service._workspace_message_record_id(event_id)
    )
    if event_record is None or message_record is None:
        raise AssertionError("benchmark notification source event is missing")
    # The no-change resume series must not accidentally benchmark a due
    # retention job. Due outbox/history work has separate fixture coverage.
    service.store.put(
        "workspace_retention_state",
        service._workspace_retention_state_id(workspace_id),
        {
            "workspace_id": workspace_id,
            "status": "complete",
            "next_due_at": time.time() + 24 * 60 * 60,
        },
    )

    # Two additional protected profiles prove independent profile keys; no key,
    # identity, counter, or sealed record is copied from the primary profile.
    independent_profile_hashes = [hashlib.sha256(identity.get_public_key()).hexdigest()]
    for index in (2, 3):
        extra_key = hashlib.sha256(f"increment15-profile-{index}".encode()).digest()
        extra_identity = RNS.Identity()
        extra, _ = scale.open_service(
            profile / f"profile-{index}",
            extra_key,
            extra_identity,
            initialize_profile=True,
        )
        independent_profile_hashes.append(
            hashlib.sha256(extra_identity.get_public_key()).hexdigest()
        )
        scale.close_service(extra)

    service.set_native_notification_state("android", True, "allowed")
    service.mobile_lifecycle_transition("background", "benchmark_background")
    base_event = notification_event(event_record)
    message_record = dict(message_record)
    _startup_snapshot, startup_reads = scale.audit_startup(service)

    # Freeze preference precedence on an unsubscribed public channel. Plain
    # text which resembles a mention never substitutes for the signed mention
    # member list, while a structured mention may pass mentions-only mode.
    subscription_id = service.store.opaque_id(
        "workspace-subscription", workspace_id, event_record["conversation_id"]
    )
    service.store.put(
        "workspace_subscription",
        subscription_id,
        {
            "workspace_id": workspace_id,
            "channel_id": event_record["conversation_id"],
            "subscribed": False,
        },
    )
    service.set_workspace_notification_preference(
        workspace_id,
        event_record["conversation_id"],
        "mentions_only",
        scale.stable_uuid("increment15-mentions-only-probe"),
    )
    structured = service._workspace_notification_records(
        workspace,
        notification_event(
            event_record,
            event_id=scale.stable_uuid("structured-mention-probe"),
            digest=hashlib.sha256(b"structured-mention-probe").hexdigest(),
            mentions=(local_member_id,),
        ),
        message_record,
        historical=False,
    )
    plain = service._workspace_notification_records(
        workspace,
        notification_event(
            event_record,
            event_id=scale.stable_uuid("plain-mention-probe"),
            digest=hashlib.sha256(b"plain-mention-probe").hexdigest(),
        ),
        dict(message_record, text="@Owner is only plain text"),
        historical=False,
    )
    service.set_workspace_channel_mentions_muted(
        workspace_id,
        event_record["conversation_id"],
        True,
        scale.stable_uuid("increment15-mention-mute-probe"),
    )
    muted = service._workspace_notification_records(
        workspace,
        notification_event(
            event_record,
            event_id=scale.stable_uuid("muted-mention-probe"),
            digest=hashlib.sha256(b"muted-mention-probe").hexdigest(),
            mentions=(local_member_id,),
        ),
        message_record,
        historical=False,
    )
    service.set_workspace_channel_mentions_muted(
        workspace_id,
        event_record["conversation_id"],
        False,
        scale.stable_uuid("increment15-mention-unmute-probe"),
    )
    service.set_workspace_notification_preference(
        workspace_id,
        event_record["conversation_id"],
        "all",
        scale.stable_uuid("increment15-all-probe"),
    )
    service.store.put(
        "workspace_subscription",
        subscription_id,
        {
            "workspace_id": workspace_id,
            "channel_id": event_record["conversation_id"],
            "subscribed": True,
        },
    )
    preference_precedence = {
        "structured_unsubscribed_notifies": any(kind == "workspace_notification_work" for kind, _record_id, _value in structured),
        "plain_text_does_not_mention": not any(kind == "workspace_notification_work" for kind, _record_id, _value in plain),
        "mention_mute_wins": not any(kind == "workspace_notification_work" for kind, _record_id, _value in muted),
    }

    policy_ms = timed(
        samples,
        lambda index: service._workspace_notification_records(
            workspace,
            notification_event(
                event_record,
                event_id=scale.stable_uuid(f"policy-{index}"),
                digest=hashlib.sha256(f"policy-{index}".encode()).hexdigest(),
            ),
            message_record,
            historical=False,
        ),
    )

    enqueued_ids: list[str] = []
    enqueued_events: list[tuple[str, str]] = []

    def durable_enqueue(index: int) -> None:
        live_id = scale.stable_uuid(f"notification-live-{index}")
        live_digest = hashlib.sha256(f"notification-live-{index}".encode()).hexdigest()
        event = dict(event_record, id=live_id, digest=live_digest)
        message = dict(message_record, id=live_id, event_digest=live_digest)
        verified = notification_event(event, event_id=live_id, digest=live_digest)
        records = service._workspace_notification_records(
            workspace, verified, message, historical=False
        )
        service.store.put_many(
            [
                ("workspace_event", service._workspace_event_record_id(live_id), event),
                (
                    "workspace_message_state",
                    service._workspace_message_record_id(live_id),
                    message,
                ),
                *records,
            ]
        )
        enqueued_ids.append(service._workspace_notification_id(workspace_id, live_id))
        enqueued_events.append((live_id, live_digest))

    enqueue_ms = timed(samples, durable_enqueue)
    dispatch_attempts = 0

    def dispatch(_index: int) -> None:
        nonlocal dispatch_attempts
        items = service.drain_native_notification_work(MAX_NOTIFICATION_BATCH)["items"]
        if not items:
            raise AssertionError("native dispatch lost pending work")
        dispatch_attempts += len(items)

    dispatch_ms = timed(samples, dispatch)
    duplicate_event_id, duplicate_digest = enqueued_events[0]
    duplicate_event = notification_event(
        event_record, event_id=duplicate_event_id, digest=duplicate_digest
    )
    duplicate_message = dict(
        message_record, id=duplicate_event_id, event_digest=duplicate_digest
    )
    duplicate_ms = timed(
        samples,
        lambda _index: service._workspace_notification_records(
            workspace, duplicate_event, duplicate_message, historical=False
        ),
    )
    if service._workspace_notification_records(
        workspace, duplicate_event, duplicate_message, historical=False
    ):
        raise AssertionError("duplicate notification was not suppressed")

    background_ms = timed(
        samples,
        lambda _index: service.mobile_lifecycle_transition(
            "background", "benchmark_background"
        ),
    )

    access_counts: dict[str, int] = defaultdict(int)
    original_list = service.store.list
    original_items = service.store.items

    def tracked_list(kind: str) -> list[dict[str, Any]]:
        access_counts[f"list:{kind}"] += 1
        return original_list(kind)

    def tracked_items(kind: str) -> list[tuple[str, dict[str, Any]]]:
        access_counts[f"items:{kind}"] += 1
        return original_items(kind)

    service.store.list = tracked_list  # type: ignore[method-assign]
    service.store.items = tracked_items  # type: ignore[method-assign]
    try:
        resume_ms = timed(
            samples,
            lambda _index: service.mobile_lifecycle_transition(
                "foreground", "benchmark_resume"
            ),
        )
        service._mark_workspace_invalidation_overflow()
        overflow_ms = timed(
            samples,
            lambda _index: service.mobile_lifecycle_transition(
                "foreground", "invalidation_overflow"
            ),
        )
        network_restore_ms = timed(
            samples,
            lambda _index: service.mobile_lifecycle_transition(
                "foreground", "network_restored"
            ),
        )
    finally:
        service.store.list = original_list  # type: ignore[method-assign]
        service.store.items = original_items  # type: ignore[method-assign]
    whole_collection_scans = {
        key: count
        for key, count in access_counts.items()
        if "workspace_event" in key or "workspace_delivery" in key
    }

    service.mobile_lifecycle_transition("background", "benchmark_dispatch")
    valid_notification_id = enqueued_ids[0]
    unread_before_open = service._require_workspace_channel(
        workspace_id, event_record["conversation_id"]
    ).get("unread_count", 0)
    delivery_id = next(iter(event_record.get("delivery_ids", ())), None)
    delivery_before_open = (
        service.store.get("workspace_delivery", delivery_id).get("state")
        if isinstance(delivery_id, str)
        and service.store.get("workspace_delivery", delivery_id) is not None
        else None
    )
    open_ms = timed(
        samples,
        lambda _index: service.open_notification_target(valid_notification_id),
    )
    unread_after_open = service._require_workspace_channel(
        workspace_id, event_record["conversation_id"]
    ).get("unread_count", 0)
    delivery_after_open = (
        service.store.get("workspace_delivery", delivery_id).get("state")
        if isinstance(delivery_id, str)
        and service.store.get("workspace_delivery", delivery_id) is not None
        else None
    )
    preference_ms = timed(
        samples,
        lambda index: service.set_workspace_notification_preference(
            workspace_id,
            channels[index % len(channels)]["id"],
            ("all", "mentions_only", "muted")[index % 3],
            scale.stable_uuid(f"increment15-preference-{index}"),
        ),
    )
    service.set_workspace_notification_preference(
        workspace_id,
        event_record["conversation_id"],
        "all",
        scale.stable_uuid("increment15-post-preference-reset"),
    )

    # Resume deliberately suppresses stale pending presentation. Create one
    # fresh background item to measure a crash/restart before native display.
    service.mobile_lifecycle_transition("background", "restart_pending_probe")
    durable_enqueue(9_000)
    queue_depth_before_restart = service.notification_state()["pending_native_count"]

    # Keep one pending item across each cold service reconstruction.
    scale.close_service(service)
    restart_ms: list[float] = []
    pending_after_restart = 0
    for _index in range(samples):
        sample_started = time.perf_counter()
        service, _network = scale.open_service(profile / "primary", key, identity)
        service.mobile_lifecycle_transition("background", "process_restart")
        pending = service.drain_native_notification_work(1)["items"]
        restart_ms.append((time.perf_counter() - sample_started) * 1_000)
        if not pending:
            raise AssertionError("restart lost pending native work")
        pending_after_restart = service.notification_state()["pending_native_count"]
        scale.close_service(service)

    service, _network = scale.open_service(profile / "primary", key, identity)
    service.mobile_lifecycle_transition("background", "latency_probe")
    for notification_id in enqueued_ids:
        service.acknowledge_native_notification(notification_id, "accepted")

    accepted_to_native_ms: list[float] = []
    native_payload_bytes: list[int] = []
    for index in range(samples):
        sample_started = time.perf_counter()
        durable_enqueue(samples + index)
        item = service.drain_native_notification_work(1)["items"][0]
        accepted_to_native_ms.append((time.perf_counter() - sample_started) * 1_000)
        native_payload_bytes.append(len(json.dumps(item).encode("utf-8")))
        service.acknowledge_native_notification(item["notification_id"], "accepted")

    service.set_hide_notification_previews(
        True, scale.stable_uuid("increment15-hide-previews")
    )
    hidden_id = scale.stable_uuid("increment15-hidden-preview")
    hidden_digest = hashlib.sha256(b"increment15-hidden-preview").hexdigest()
    hidden_event_record = dict(event_record, id=hidden_id, digest=hidden_digest)
    hidden_message = dict(
        message_record,
        id=hidden_id,
        event_digest=hidden_digest,
        text="private benchmark preview that must not escape",
    )
    hidden_records = service._workspace_notification_records(
        workspace,
        notification_event(hidden_event_record),
        hidden_message,
        historical=False,
    )
    service.store.put_many(
        [
            (
                "workspace_event",
                service._workspace_event_record_id(hidden_id),
                hidden_event_record,
            ),
            (
                "workspace_message_state",
                service._workspace_message_record_id(hidden_id),
                hidden_message,
            ),
            *hidden_records,
        ]
    )
    hidden_item = service.drain_native_notification_work(1)["items"][0]
    no_preview_leakage = hidden_item["title"] == "Mesh Chat" and hidden_item["body"] == "New message"
    service.acknowledge_native_notification(hidden_item["notification_id"], "accepted")

    # Historical catch-up policy evaluation is deliberately queue-free even
    # across the complete retained fixture.
    before_history = service.notification_state()["pending_native_count"]
    for _index in range(event_count):
        if service._workspace_notification_records(
            workspace, base_event, message_record, historical=True
        ):
            raise AssertionError("historical catch-up created notification work")
    after_history = service.notification_state()["pending_native_count"]

    # Removed-device and fork state both fail closed once the relevant sealed
    # state is known. Restore active state only to finish the isolated resource
    # accounting and permission-denial probe.
    active_workspace = service._require_workspace(workspace_id)
    forked_workspace = dict(active_workspace, state="forked")
    service.store.put(
        "workspace", service._workspace_record_id(workspace_id), forked_workspace
    )
    forked_records = service._workspace_notification_records(
        forked_workspace,
        notification_event(
            event_record,
            event_id=scale.stable_uuid("forked-notification-probe"),
            digest=hashlib.sha256(b"forked-notification-probe").hexdigest(),
        ),
        message_record,
        historical=False,
    )
    removed_workspace = dict(active_workspace, state="device_removed")
    service.store.put(
        "workspace", service._workspace_record_id(workspace_id), removed_workspace
    )
    removed_open = service.open_notification_target(valid_notification_id)
    service.store.put(
        "workspace", service._workspace_record_id(workspace_id), active_workspace
    )

    # Exercise the exact queue cap and overflow suppression before denial
    # purges all pending native work.
    service.set_native_notification_state("android", True, "allowed")
    service.mobile_lifecycle_transition("background", "queue_bound_probe")
    for index in range(MAX_NOTIFICATION_QUEUE + 5):
        durable_enqueue(10_000 + index)
    queue_depth_peak = service.notification_state()["pending_native_count"]

    # Permission denial atomically purges pending native work. Re-enable only
    # after capturing denial behavior; a denied state never prompts itself.
    service.set_native_notification_state("android", True, "denied")
    denied_queue_empty = service.notification_state()["pending_native_count"] == 0
    permission_state_after_denial = service.notification_state()["permission_state"]

    vault_final = scale.vault_stats(service.store, vault_path)
    record_counts = scale.record_counts(service.store)
    _current, peak_python = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    scale.close_service(service)
    protocol = linked.protocol_series(samples)

    timings = {
        "notification_policy": summary(policy_ms),
        "durable_enqueue": summary(enqueue_ms),
        "service_to_native_dispatch": summary(dispatch_ms),
        "duplicate_suppression": summary(duplicate_ms),
        "foreground_to_background": summary(background_ms),
        "resume_no_change": summary(resume_ms),
        "resume_after_overflow": summary(overflow_ms),
        "network_restoration": summary(network_restore_ms),
        "notification_open": summary(open_ms),
        "preference_update": summary(preference_ms),
        "process_restart_pending_work": summary(restart_ms),
        "accepted_to_native_request": summary(accepted_to_native_ms),
    }
    assertions = {
        "full_size_fixture": event_count == 50_000,
        "eight_members": fixture["members"] == 8,
        "thirty_two_channels": fixture["channels"] == 32,
        "public_private_archived_chains": sum(item["visibility"] == "private" for item in channels) > 0 and sum(item["state"] == "archived" for item in channels) == 4,
        "three_independent_profiles": len(set(independent_profile_hashes)) == 3,
        "three_devices_per_selected_member": protocol["work"]["devices"] == 24,
        "twenty_four_destination_cap": protocol["work"]["remote_fanout_legs"] == 23,
        "no_whole_event_or_delivery_scan": not whole_collection_scans,
        "historical_catch_up_no_storm": before_history == after_history,
        "preview_hidden": no_preview_leakage,
        "preference_precedence": all(preference_precedence.values()),
        "fork_fails_closed": not any(kind == "workspace_notification_work" for kind, _record_id, _value in forked_records),
        "removed_device_open_fails_closed": removed_open.get("available") is False,
        "queue_is_bounded": queue_depth_peak == MAX_NOTIFICATION_QUEUE,
        "permission_denied_queue_empty": denied_queue_empty,
        "permission_denied_is_stable": permission_state_after_denial == "denied",
        "native_payload_bounded": max(native_payload_bytes) <= MAX_NOTIFICATION_NATIVE_BYTES,
        "notification_policy_p95": timings["notification_policy"]["p95"] < LIMITS["notification_policy_p95_ms"],
        "durable_enqueue_p95": timings["durable_enqueue"]["p95"] < LIMITS["durable_enqueue_p95_ms"],
        "native_dispatch_p95": timings["service_to_native_dispatch"]["p95"] < LIMITS["native_dispatch_p95_ms"],
        "duplicate_p95": timings["duplicate_suppression"]["p95"] < LIMITS["duplicate_suppression_p95_ms"],
        "background_p95": timings["foreground_to_background"]["p95"] < LIMITS["background_transition_p95_ms"],
        "resume_p95": timings["resume_no_change"]["p95"] < LIMITS["resume_no_change_p95_ms"],
        "overflow_p95": timings["resume_after_overflow"]["p95"] < LIMITS["resume_overflow_p95_ms"],
        "network_restore_p95": timings["network_restoration"]["p95"] < LIMITS["network_restore_p95_ms"],
        "notification_open_p95": timings["notification_open"]["p95"] < LIMITS["notification_open_p95_ms"],
        "preference_p95": timings["preference_update"]["p95"] < LIMITS["preference_update_p95_ms"],
        "restart_p95": timings["process_restart_pending_work"]["p95"] < LIMITS["restart_pending_work_p95_ms"],
        "accepted_to_native_p95": timings["accepted_to_native_request"]["p95"] < LIMITS["accepted_to_native_request_p95_ms"],
    }
    return {
        "schema": "mesh-chat-increment-15-mobile-lifecycle-v1",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_seconds": round(time.perf_counter() - started, 3),
        "limits": LIMITS,
        "host": host_profile(),
        "fixture": {
            **fixture,
            "profiles": 3,
            "public_channels": sum(item["visibility"] == "public" for item in channels),
            "private_channels": sum(item["visibility"] == "private" for item in channels),
            "archived_channels": sum(item["state"] == "archived" for item in channels),
        },
        "timings_ms": timings,
        "work": {
            "samples": samples,
            "queue_depth_before_restart": queue_depth_before_restart,
            "queue_depth_after_restart": pending_after_restart,
            "queue_depth_peak": queue_depth_peak,
            "native_dispatch_attempts": dispatch_attempts + samples + 1,
            "duplicate_probes": samples,
            "historical_suppressed": event_count,
            "permission_denied": 1,
            "invalidation_overflow_probes": samples,
            "resume_record_access": dict(sorted(access_counts.items())),
            "startup_record_access": startup_reads,
            "whole_collection_scans": whole_collection_scans,
            "transaction_model": "event + derived message + decision + ledger + native work + queue in one put_many transaction",
        },
        "resources": {
            "python_tracemalloc_peak_bytes": peak_python,
            "process_peak_working_set_bytes": scale.working_set_bytes(),
            "vault": {
                "before": vault_before,
                "seeded": vault_seeded,
                "final": vault_final,
                "seed_growth_bytes": vault_seeded["bytes"] - vault_before["bytes"],
                "notification_growth_bytes": vault_final["bytes"] - vault_seeded["bytes"],
            },
            "record_counts": record_counts,
            "battery": "not measured: no authorized disposable physical Android device",
        },
        "correctness": {
            "no_preview_leakage": no_preview_leakage,
            "no_historical_notification_storm": before_history == after_history,
            "preference_precedence": preference_precedence,
            "no_false_read_receipt": unread_before_open == unread_after_open,
            "no_notification_as_delivery": delivery_before_open == delivery_after_open,
            "private_identity_copies": protocol["work"]["private_identity_copies"],
        },
        "linked_device_protocol": protocol,
        "assertions": assertions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=int, default=50_000)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--keep-profile", action="store_true")
    args = parser.parse_args()
    if args.events != 50_000:
        raise SystemExit("Increment 15 release benchmark requires exactly 50,000 events")
    if args.samples < LIMITS["samples"]:
        raise SystemExit("Increment 15 release benchmark requires at least 30 samples")
    temporary = args.profile is None
    profile = (
        Path(tempfile.mkdtemp(prefix="mesh-chat-increment15-"))
        if temporary
        else args.profile.resolve()
    )
    profile.mkdir(parents=True, exist_ok=True)
    try:
        result = run(profile, args.events, args.samples)
        encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        return 0 if all(result["assertions"].values()) else 1
    finally:
        if temporary and not args.keep_profile:
            shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
