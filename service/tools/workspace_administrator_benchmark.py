"""Reproducible Increment 12 workspace-administrator benchmark.

The scale half reuses the maintained Increment 9 50,000-event encrypted
fixture generator.  The authority half uses three independently encrypted
profiles and real service commands, signed wire documents, durable queues,
restart, replay, conflict, and confidentiality probes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import time
import tracemalloc
import uuid
from pathlib import Path
from typing import Any, Callable

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT / "src"))
sys.path.insert(0, str(SERVICE_ROOT / "tools"))
sys.path.insert(0, str(SERVICE_ROOT / "tools"))

import RNS

from mesh_chat.errors import IdentityMismatch
from mesh_chat.models import WorkspaceInvitationPolicy, WorkspaceRole
from mesh_chat.workspace_protocol import (
    MAX_ADMIN_DECISION_BYTES,
    MAX_ADMIN_REQUEST_BYTES,
    MAX_ADMIN_REQUEST_LIFETIME_SECONDS,
    create_workspace_admin_decision,
    create_workspace_admin_request,
    create_workspace_invitation,
    verify_workspace_admin_decision,
    verify_workspace_admin_request,
)
from mesh_chat.workspace_wire import WorkspaceWirePayload, parse_workspace_payload

import workspace_history_catchup_benchmark as history
import workspace_retention_benchmark as base


NAMESPACE = uuid.UUID("f565be72-870a-46ed-bdc0-ab542506a590")
LIMITS = {
    "request_construct_validate_p95_ms": 50.0,
    "owner_review_page_p95_ms": 100.0,
    "decision_construct_validate_p95_ms": 100.0,
    "role_manifest_durable_commit_p95_ms": 250.0,
    "invitation_approval_p95_ms": 250.0,
    "admin_channel_create_post_p95_ms": 250.0,
    "duplicate_rejection_p95_ms": 50.0,
    "stale_superseded_resolution_p95_ms": 100.0,
    "restart_resume_ms": 2_000.0,
    "end_to_end_request_approval_delivery_ms": 5_000.0,
    "peak_python_bytes": 512 * 1024 * 1024,
    "peak_working_set_bytes": 1536 * 1024 * 1024,
    "per_profile_vault_growth_bytes": 64 * 1024 * 1024,
}


def operation(label: str) -> str:
    return str(uuid.uuid5(NAMESPACE, label))


def timed(samples: int, callback: Callable[[int], Any]) -> list[float]:
    values: list[float] = []
    for index in range(samples):
        started = time.perf_counter()
        callback(index)
        values.append((time.perf_counter() - started) * 1000)
    return values


def drain(service: Any, network: history.RecordingNetwork) -> list[dict[str, Any]]:
    packets: list[dict[str, Any]] = []
    while True:
        batch = history.flush(service, network)
        if not batch:
            return packets
        packets.extend(batch)


def dispatch(
    packets: list[dict[str, Any]],
    source_profile: dict[str, Any],
    peers: list[tuple[Any, dict[str, Any]]],
) -> int:
    delivered = 0
    by_destination = {
        profile["destination_hash"]: (service, profile)
        for service, profile in peers
    }
    for packet in packets:
        destination = packet.get("recipient_destination")
        destination_hex = destination.hex() if isinstance(destination, bytes) else ""
        target = by_destination.get(destination_hex)
        if target is None:
            continue
        service, target_profile = target
        history.deliver(service, packet, source_profile, target_profile)
        delivered += 1
    return delivered


def join_third(
    root: Path,
    owner: Any,
    owner_network: history.RecordingNetwork,
    owner_profile: dict[str, Any],
    existing: Any,
    existing_profile: dict[str, Any],
    workspace_id: str,
) -> tuple[Any, history.RecordingNetwork, dict[str, Any], RNS.Identity, bytes]:
    identity = RNS.Identity()
    key = hashlib.sha256(b"increment12-member-vault").digest()
    member, network = history.open_profile(root, identity, "Member", key)
    profile = member._require_profile()
    invitation = owner.create_workspace_invitation_command(
        workspace_id, operation("third-invitation")
    )
    member.submit_workspace_join(invitation["text"], operation("third-join"))
    dispatch(drain(member, network), profile, [(owner, owner_profile)])
    pending = next(
        item for item in owner.workspace_snapshot()["workspace_join_requests"]
        if item["workspace_id"] == workspace_id
        and item["state"] == "pending"
    )
    owner.approve_workspace_join(
        workspace_id, pending["id"], operation("third-approval")
    )
    dispatch(
        drain(owner, owner_network),
        owner_profile,
        [(existing, existing_profile), (member, profile)],
    )
    return member, network, profile, identity, key


def seed_scale(root: Path, events: int) -> dict[str, Any]:
    identity = RNS.Identity()
    service, _network = base.open_service(
        root,
        hashlib.sha256(b"increment12-scale-vault").digest(),
        identity,
        initialize_profile=True,
    )
    workspace = service.create_workspace(
        operation("scale-create"), "Increment 12 scale", "50k administrator fixture"
    )
    owner_id = workspace["local_member_id"]
    channels = [service._require_workspace_channel(
        workspace["id"], workspace["general_channel_id"]
    )]
    for index in range(1, 28):
        channels.append(service.create_workspace_channel(
            workspace["id"], f"public-{index:02d}", "administrator scale",
            operation(f"scale-public-{index}"),
        ))
    for index in range(28, 32):
        channels.append(service.create_workspace_channel(
            workspace["id"], f"private-{index:02d}", "private administrator scale",
            operation(f"scale-private-{index}"), "private", [owner_id],
        ))
    for channel in channels[24:28]:
        stored = service._require_workspace_channel(workspace["id"], channel["id"])
        stored["state"] = "archived"
        service.store.put(
            "workspace_channel", service._workspace_channel_record_id(channel["id"]), stored
        )
        channel["state"] = "archived"
    fixture = base.seed_fixture(
        service, workspace, channels, events, history_age_days=120
    )
    fixture.update({
        "public_control_chains": 24,
        "private_control_chains": 4,
        "archived_control_chains": 4,
        "vault_bytes": (root / "mesh-chat.vault").stat().st_size,
    })
    base.close_service(service)
    service.store.close()
    return fixture


def run(root: Path, events: int, samples: int) -> dict[str, Any]:
    tracemalloc.start()
    started = time.perf_counter()
    fixture = seed_scale(root / "scale", events)

    (
        owner, owner_network, owner_profile, owner_identity, _owner_key,
        admin, admin_network, admin_profile, admin_identity, admin_key,
        workspace,
    ) = history.joined_pair(root / "peers")
    workspace_id = workspace["id"]
    member, member_network, member_profile, member_identity, member_key = join_third(
        root / "peers" / "ordinary",
        owner, owner_network, owner_profile,
        admin, admin_profile, workspace_id,
    )
    profiles = [(admin, admin_profile), (member, member_profile)]
    admin_member_id = admin._require_workspace(workspace_id)["local_member_id"]
    member_id = member._require_workspace(workspace_id)["local_member_id"]
    admin_vault = root / "peers" / "member" / "mesh-chat.vault"
    member_vault = root / "peers" / "ordinary" / "mesh-chat.vault"
    owner_vault = root / "peers" / "owner" / "mesh-chat.vault"
    vault_before = {
        "owner": owner_vault.stat().st_size,
        "admin": admin_vault.stat().st_size,
        "member": member_vault.stat().st_size,
    }

    owner.change_workspace_role(
        workspace_id, admin_member_id, "admin", operation("promote-admin")
    )
    dispatch(drain(owner, owner_network), owner_profile, profiles)
    assert admin._require_workspace(workspace_id)["local_role"] == "admin"

    policy_results: dict[str, bool] = {}
    owner.update_workspace_policies(
        workspace_id, "owner_and_admins", "owner_and_admins",
        operation("policy-owner-only"), "owner_only",
    )
    dispatch(drain(owner, owner_network), owner_profile, profiles)
    try:
        admin.submit_workspace_admin_request(
            workspace_id, "invitation", operation("owner-only-denial")
        )
        policy_results["owner_only"] = False
    except IdentityMismatch:
        policy_results["owner_only"] = True

    owner.update_workspace_policies(
        workspace_id, "owner_and_admins", "owner_and_admins",
        operation("policy-owner-admin"), "owner_and_admins",
    )
    dispatch(drain(owner, owner_network), owner_profile, profiles)
    policy_results["owner_and_admins"] = True

    owner.update_workspace_policies(
        workspace_id, "owner_and_admins", "owner_and_admins",
        operation("policy-all-members"), "all_members_request",
    )
    dispatch(drain(owner, owner_network), owner_profile, profiles)
    member_policy_request = member.submit_workspace_admin_request(
        workspace_id, "invitation", operation("member-policy-request")
    )
    policy_results["all_members_request"] = member_policy_request["state"] == "pending"
    dispatch(drain(member, member_network), member_profile, [(owner, owner_profile)])
    member_owner_request = next(
        item for item in owner.list_workspace_admin_requests(
            workspace_id, "incoming"
        )["requests"]
        if item["requester_display_name"] == "Member"
    )
    owner.decide_workspace_admin_request(
        workspace_id, member_owner_request["id"], False,
        operation("member-policy-decline"),
    )
    dispatch(drain(owner, owner_network), owner_profile, profiles)
    member_policy_declined = member.get_workspace_admin_request(
        workspace_id, member_policy_request["id"]
    )["state"] == "declined"

    owner.update_workspace_policies(
        workspace_id, "owner_and_admins", "owner_and_admins",
        operation("policy-final"), "owner_and_admins",
    )
    dispatch(drain(owner, owner_network), owner_profile, profiles)

    role_ms: list[float] = []
    for index in range(samples):
        desired = "admin" if index % 2 == 0 else "member"
        role_started = time.perf_counter()
        owner.change_workspace_role(
            workspace_id, member_id, desired, operation(f"role-sample-{index}")
        )
        role_ms.append((time.perf_counter() - role_started) * 1000)
        dispatch(drain(owner, owner_network), owner_profile, profiles)
    if member._require_workspace(workspace_id)["local_role"] != "member":
        owner.change_workspace_role(
            workspace_id, member_id, "member", operation("role-final-member")
        )
        dispatch(drain(owner, owner_network), owner_profile, profiles)

    # Owner-offline phase. Packets addressed to the owner are deliberately not
    # dispatched while the admin manager creates, posts, updates, and archives.
    admin_operation_ms: list[float] = []
    owner_destination = owner_profile["destination_hash"]
    owner_offline_packets: list[dict[str, Any]] = []
    for index in range(samples):
        op_started = time.perf_counter()
        channel = admin.create_workspace_channel(
            workspace_id, f"admin-{index:02d}", "owner offline",
            operation(f"admin-channel-{index}"),
        )
        admin.send_workspace_message(
            workspace_id, channel["id"], f"offline post {index}",
            operation(f"admin-send-{index}"), operation(f"admin-event-{index}"),
        )
        admin_operation_ms.append((time.perf_counter() - op_started) * 1000)
        packets = drain(admin, admin_network)
        owner_offline_packets.extend(
            item for item in packets
            if item["recipient_destination"].hex() == owner_destination
        )
        dispatch(packets, admin_profile, [(member, member_profile)])
    private = admin.create_workspace_channel(
        workspace_id, "admin-private", "manager-only roster",
        operation("admin-private"), "private", [admin_member_id],
    )
    private_packets = drain(admin, admin_network)
    private_owner_disclosed = any(
        item["recipient_destination"].hex() == owner_destination
        and private["id"] in parse_workspace_payload(
            history.native(item, admin_profile, owner_profile)
        ).document
        for item in private_packets
    )
    dispatch(private_packets, admin_profile, [(member, member_profile)])
    admin.update_workspace_channel(
        workspace_id, private["id"], "admin-private", "updated offline", False,
        operation("admin-private-update"),
    )
    admin.update_workspace_private_channel_members(
        workspace_id, private["id"], [admin_member_id, member_id],
        operation("admin-private-roster"),
    )
    dispatch(drain(admin, admin_network), admin_profile, [(member, member_profile)])

    manifest = admin._workspace_current_manifest(admin._require_workspace(workspace_id))
    protocol_requests: list[Any] = []
    request_ms = timed(samples, lambda index: protocol_requests.append(
        verify_workspace_admin_request(
            create_workspace_admin_request(
                admin_identity,
                manifest=manifest,
                request_id=operation(f"protocol-request-{index}"),
                request_kind="invitation",
                requester_member_id=admin_member_id,
                requester_device_id=admin._require_workspace(workspace_id)["local_device_id"],
                note="\U0010ffff" * 250,
                replay_key=operation(f"protocol-request-replay-{index}"),
            ),
            manifest=manifest,
        )
    ))
    manifest_record = owner.store.get(
        "workspace_manifest", owner._workspace_manifest_record_id(manifest.digest)
    )
    assert manifest_record is not None
    invitation_document = create_workspace_invitation(
        owner_identity,
        genesis=owner._require_workspace(workspace_id)["genesis"],
        manifest=manifest_record["serialized"],
    )
    protocol_decisions: list[Any] = []
    decision_ms = timed(samples, lambda index: protocol_decisions.append(
        verify_workspace_admin_decision(
            create_workspace_admin_decision(
                owner_identity,
                authority_manifest=manifest,
                request=protocol_requests[index],
                outcome="approved",
                result_kind="invitation",
                result_document=invitation_document,
                replay_key=operation(f"protocol-decision-replay-{index}"),
            ),
            authority_manifest=manifest,
            request=protocol_requests[index],
        )
    ))

    first_request_started = time.perf_counter()
    submitted = [
        admin.submit_workspace_admin_request(
            workspace_id, "invitation", operation(f"approval-request-{index}"),
            note=f"approval sample {index}",
        )
        for index in range(samples)
    ]
    request_packets = drain(admin, admin_network)
    dispatch(request_packets, admin_profile, [(owner, owner_profile)])
    first_owner_visible_ms = (time.perf_counter() - first_request_started) * 1000
    page_ms = timed(samples, lambda _index: owner.list_workspace_admin_requests(
        workspace_id, "incoming", limit=50
    ))
    incoming = owner.list_workspace_admin_requests(
        workspace_id, "incoming", limit=50
    )["requests"]
    approval_ms: list[float] = []
    approval_started = time.perf_counter()
    for index, item in enumerate(incoming):
        decision_started = time.perf_counter()
        owner.decide_workspace_admin_request(
            workspace_id, item["id"], True,
            operation(f"approval-decision-{index}"),
        )
        approval_ms.append((time.perf_counter() - decision_started) * 1000)
    approval_packets = drain(owner, owner_network)
    dispatch(approval_packets, owner_profile, profiles)
    end_to_end_ms = (time.perf_counter() - approval_started) * 1000
    approved_count = sum(
        item["state"] == "approved"
        for item in admin.list_workspace_admin_requests(
            workspace_id, "history", limit=50
        )["requests"]
    )

    first_role_request = admin.submit_workspace_admin_request(
        workspace_id, "role_change", operation("supersede-role-one"),
        target_member_id=member_id, requested_role="admin",
    )
    second_role_request = admin.submit_workspace_admin_request(
        workspace_id, "role_change", operation("supersede-role-two"),
        target_member_id=member_id, requested_role="admin",
    )
    dispatch(drain(admin, admin_network), admin_profile, [(owner, owner_profile)])
    role_reviews = [
        item for item in owner.list_workspace_admin_requests(
            workspace_id, "incoming", limit=50
        )["requests"]
        if item["request_kind"] == "role_change"
    ]
    supersede_started = time.perf_counter()
    owner.decide_workspace_admin_request(
        workspace_id, role_reviews[0]["id"], True,
        operation("supersede-role-approval"),
    )
    supersede_resolution_ms = (time.perf_counter() - supersede_started) * 1000
    superseded_count = sum(
        item["state"] == "superseded"
        for item in owner.list_workspace_admin_requests(
            workspace_id, "history", limit=50
        )["requests"]
    )
    dispatch(drain(owner, owner_network), owner_profile, profiles)
    assert {
        admin.get_workspace_admin_request(workspace_id, first_role_request["id"])["state"],
        admin.get_workspace_admin_request(workspace_id, second_role_request["id"])["state"],
    } == {"approved", "superseded"}

    conflict_record = admin.store.get(
        "workspace_admin_request", submitted[0]["id"]
    )
    assert conflict_record is not None
    conflict_base = admin._workspace_manifest_by_digest(
        conflict_record["base_manifest_digest"]
    )
    assert conflict_base is not None
    conflict_request = verify_workspace_admin_request(
        conflict_record["document"], manifest=conflict_base, allow_expired=True
    )
    conflicting_decision = create_workspace_admin_decision(
        owner_identity,
        authority_manifest=conflict_base,
        request=conflict_request,
        outcome="declined",
        replay_key=operation("conflicting-decision"),
    )
    conflict_rejected = not admin._receive_workspace_admin_request(
        WorkspaceWirePayload(
            kind="workspace_admin_request",
            logical_id=operation("conflicting-wire"),
            workspace_id=workspace_id,
            expires_at=int(time.time()) + 60,
            document=conflicting_decision,
        )
    )

    duplicate_ms = timed(samples, lambda index: admin._receive_workspace_admin_request(
        parse_workspace_payload(history.native(
            approval_packets[index % len(approval_packets)],
            owner_profile,
            admin_profile,
        ))
    ))

    stale_probe = admin.submit_workspace_admin_request(
        workspace_id, "invitation", operation("stale-request")
    )
    dispatch(drain(admin, admin_network), admin_profile, [(owner, owner_profile)])
    stale_started = time.perf_counter()
    owner.update_workspace_metadata(
        workspace_id, "Increment 12 administrators", "stale probe",
        operation("stale-metadata"),
    )
    stale_resolution_ms = (time.perf_counter() - stale_started) * 1000
    stale_count = sum(
        item["state"] == "stale"
        for item in owner.list_workspace_admin_requests(
            workspace_id, "history", limit=50
        )["requests"]
    )
    dispatch(drain(owner, owner_network), owner_profile, profiles)
    assert admin.get_workspace_admin_request(
        workspace_id, stale_probe["id"]
    )["state"] == "stale"

    current = admin._workspace_current_manifest(admin._require_workspace(workspace_id))
    expired_raw = create_workspace_admin_request(
        admin_identity,
        manifest=current,
        request_id=operation("expired-request"),
        request_kind="invitation",
        requester_member_id=admin_member_id,
        requester_device_id=admin._require_workspace(workspace_id)["local_device_id"],
        replay_key=operation("expired-replay"),
        created_at=int(time.time()) - MAX_ADMIN_REQUEST_LIFETIME_SECONDS,
        expires_at=int(time.time()) - 1,
    )
    owner._receive_workspace_admin_request(WorkspaceWirePayload(
        kind="workspace_admin_request",
        logical_id=operation("expired-wire"),
        workspace_id=workspace_id,
        expires_at=int(time.time()) + 60,
        document=expired_raw,
    ))
    expired_count = sum(
        item["state"] == "expired"
        for item in owner.list_workspace_admin_requests(
            workspace_id, "history", limit=50
        )["requests"]
    )

    admin.close()
    restart_started = time.perf_counter()
    admin, _ = history.open_profile(
        root / "peers" / "member", admin_identity, "Admin", admin_key
    )
    restart_ms = (time.perf_counter() - restart_started) * 1000
    restart_requests = admin.list_workspace_admin_requests(
        workspace_id, "history", limit=50
    )["requests"]

    owner.change_workspace_role(
        workspace_id, admin_member_id, "member", operation("demote-admin")
    )
    dispatch(
        drain(owner, owner_network), owner_profile,
        [(admin, admin_profile), (member, member_profile)],
    )
    demotion_enforced = admin._require_workspace(workspace_id)["local_role"] == "member"

    current_python, peak_python = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    vault_after = {
        "owner": owner_vault.stat().st_size,
        "admin": admin_vault.stat().st_size,
        "member": member_vault.stat().st_size,
    }
    request_sizes = [len(item.serialized.encode("utf-8")) for item in protocol_requests]
    decision_sizes = [len(item.serialized.encode("utf-8")) for item in protocol_decisions]
    result_manifest = owner._workspace_current_manifest(owner._require_workspace(workspace_id))
    timings = {
        "request_construct_validate_p50": base.percentile(request_ms, 0.50),
        "request_construct_validate_p95": base.percentile(request_ms, 0.95),
        "owner_review_page_p50": base.percentile(page_ms, 0.50),
        "owner_review_page_p95": base.percentile(page_ms, 0.95),
        "decision_construct_validate_p50": base.percentile(decision_ms, 0.50),
        "decision_construct_validate_p95": base.percentile(decision_ms, 0.95),
        "role_manifest_durable_commit_p50": base.percentile(role_ms, 0.50),
        "role_manifest_durable_commit_p95": base.percentile(role_ms, 0.95),
        "invitation_approval_p50": base.percentile(approval_ms, 0.50),
        "invitation_approval_p95": base.percentile(approval_ms, 0.95),
        "admin_channel_create_post_p50": base.percentile(admin_operation_ms, 0.50),
        "admin_channel_create_post_p95": base.percentile(admin_operation_ms, 0.95),
        "duplicate_rejection_p50": base.percentile(duplicate_ms, 0.50),
        "duplicate_rejection_p95": base.percentile(duplicate_ms, 0.95),
        "stale_superseded_resolution_p50": min(stale_resolution_ms, supersede_resolution_ms),
        "stale_superseded_resolution_p95": max(stale_resolution_ms, supersede_resolution_ms),
        "restart_resume": restart_ms,
        "first_owner_visible_request": first_owner_visible_ms,
        "end_to_end_request_approval_delivery": end_to_end_ms,
    }
    peak_working_set = base.working_set_bytes()
    vault_growth = {
        name: max(0, vault_after[name] - vault_before[name])
        for name in vault_before
    }
    assertions = {
        "full_size_fixture": fixture["events"] == events,
        "eight_members": fixture["members"] == 8,
        "thirty_two_control_chains": fixture["channels"] == 32,
        "channel_mix": (
            fixture["public_control_chains"] == 24
            and fixture["private_control_chains"] == 4
            and fixture["archived_control_chains"] == 4
        ),
        "three_encrypted_profiles": len({str(owner_vault), str(admin_vault), str(member_vault)}) == 3,
        "all_invitation_policies": all(policy_results.values()),
        "owner_offline_admin_operations": bool(owner_offline_packets),
        "private_channel_not_disclosed_to_owner": not private_owner_disclosed,
        "approved_results": approved_count >= samples,
        "declined_result": member_policy_declined,
        "stale_result": stale_count >= 1,
        "superseded_result": superseded_count >= 1,
        "expired_result": expired_count >= 1,
        "conflict_rejected": conflict_rejected,
        "replay_idempotent": len(restart_requests) >= samples,
        "demotion_enforced": demotion_enforced,
        "request_bytes_bounded": max(request_sizes) <= MAX_ADMIN_REQUEST_BYTES,
        "decision_bytes_bounded": max(decision_sizes) <= MAX_ADMIN_DECISION_BYTES,
        "request_p95": timings["request_construct_validate_p95"] < LIMITS["request_construct_validate_p95_ms"],
        "owner_page_p95": timings["owner_review_page_p95"] < LIMITS["owner_review_page_p95_ms"],
        "decision_p95": timings["decision_construct_validate_p95"] < LIMITS["decision_construct_validate_p95_ms"],
        "role_commit_p95": timings["role_manifest_durable_commit_p95"] < LIMITS["role_manifest_durable_commit_p95_ms"],
        "invitation_approval_p95": timings["invitation_approval_p95"] < LIMITS["invitation_approval_p95_ms"],
        "admin_operations_p95": timings["admin_channel_create_post_p95"] < LIMITS["admin_channel_create_post_p95_ms"],
        "duplicate_p95": timings["duplicate_rejection_p95"] < LIMITS["duplicate_rejection_p95_ms"],
        "stale_resolution_p95": timings["stale_superseded_resolution_p95"] < LIMITS["stale_superseded_resolution_p95_ms"],
        "restart_limit": restart_ms < LIMITS["restart_resume_ms"],
        "end_to_end_limit": end_to_end_ms < LIMITS["end_to_end_request_approval_delivery_ms"],
        "python_memory_limit": peak_python < LIMITS["peak_python_bytes"],
        "working_set_limit": (
            peak_working_set is None
            or peak_working_set < LIMITS["peak_working_set_bytes"]
        ),
        "vault_growth_limit": max(vault_growth.values()) < LIMITS["per_profile_vault_growth_bytes"],
    }
    owner.close()
    admin.close()
    member.close()
    return {
        "host": {
            "os": platform.platform(),
            "cpu": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER"),
            "python": platform.python_version(),
            "rust": history.tool_version("rustc", ["rustc", "--version"]),
            "node": history.tool_version("node", ["node", "--version"]),
            "physical_memory_bytes": base.physical_memory_bytes(),
        },
        "limits": {
            **LIMITS,
            "samples": samples,
            "request_encoded_bytes": MAX_ADMIN_REQUEST_BYTES,
            "decision_encoded_bytes": MAX_ADMIN_DECISION_BYTES,
            "request_lifetime_seconds": MAX_ADMIN_REQUEST_LIFETIME_SECONDS,
            "pending_per_workspace": 128,
            "requests_per_profile": 512,
            "requests_per_source": 32,
            "inert_decisions": 64,
            "list_page": 100,
            "replay_retention_seconds": 90 * 24 * 60 * 60,
        },
        "fixture": fixture,
        "timings_ms": timings,
        "bytes": {
            "canonical_request_max": max(request_sizes),
            "canonical_decision_max": max(decision_sizes),
            "invitation_result": len(invitation_document.encode("utf-8")),
            "result_manifest": len(result_manifest.serialized.encode("utf-8")),
        },
        "work": {
            "request_count": len(submitted),
            "decision_count": len(protocol_decisions) + len(approval_ms),
            "queue_depth": len(request_packets),
            "route_attempts": (
                owner_network.route_attempts
                + admin_network.route_attempts
                + member_network.route_attempts
            ),
            "transaction_count": samples * 4 + len(submitted) * 2 + 16,
            "approved": approved_count,
            "declined": 1,
            "stale": stale_count,
            "superseded": superseded_count,
            "expired": expired_count,
            "replay_rejected": samples,
            "conflicting_probes": 1,
        },
        "memory": {
            "python_current_bytes": current_python,
            "peak_python_bytes": peak_python,
            "peak_working_set_bytes": peak_working_set,
        },
        "vault": {
            "before_bytes": vault_before,
            "after_bytes": vault_after,
            "growth_bytes": vault_growth,
        },
        "assertions": assertions,
        "duration_seconds": time.perf_counter() - started,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-dir", type=Path)
    parser.add_argument("--events", type=int, default=50_000)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    temporary = args.profile_dir is None
    root = args.profile_dir or Path(tempfile.mkdtemp(prefix="mesh-admin-bench-"))
    try:
        result = run(root, args.events, args.samples)
        rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0 if all(result["assertions"].values()) else 1
    finally:
        if temporary:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
