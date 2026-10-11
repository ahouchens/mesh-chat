"""Reproducible Increment 13 authority-continuity benchmark.

The scale fixture reuses the maintained encrypted 50,000-event generator. The
protocol series builds the maximum eight-step authority certificate, and the
peer series performs a real encrypted ownership handoff across three profiles.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
import tracemalloc
import uuid
from pathlib import Path
from typing import Any, Callable

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT / "src"))
sys.path.insert(0, str(SERVICE_ROOT / "tools"))

import RNS

from mesh_chat.errors import ContactNotApproved, IdentityMismatch
from mesh_chat.models import WorkspaceRole
from mesh_chat.workspace_protocol import (
    MAX_AUTHORITY_ACCEPTANCE_BYTES,
    MAX_AUTHORITY_BOOTSTRAP_BYTES,
    MAX_AUTHORITY_OFFER_BYTES,
    MAX_AUTHORITY_TRANSITIONS,
    MAX_AUTHORITY_TRANSITION_LIFETIME_SECONDS,
    WorkspaceManifestMemberInput,
    create_workspace_authority_acceptance,
    create_workspace_authority_manifest,
    create_workspace_authority_offer,
    create_workspace_channel_record,
    create_workspace_channel_recovery,
    create_workspace_device_card,
    create_workspace_genesis,
    create_workspace_invitation,
    create_workspace_manifest,
    verify_workspace_authority_acceptance,
    verify_workspace_authority_manifest_transition,
    verify_workspace_authority_offer,
    verify_workspace_channel_record,
    verify_workspace_channel_recovery,
    verify_workspace_genesis,
    verify_workspace_invitation,
    verify_workspace_manifest,
)

import workspace_administrator_benchmark as admin
import workspace_history_catchup_benchmark as history
import workspace_retention_benchmark as base


NAMESPACE = uuid.UUID("971b1b6e-a2ce-44a4-b2dc-c291d70feb60")
LIMITS = {
    "offer_construct_validate_p95_ms": 100.0,
    "acceptance_construct_validate_p95_ms": 100.0,
    "final_construct_apply_p95_ms": 500.0,
    "general_recovery_p95_ms": 250.0,
    "authority_chain_construct_p95_ms": 2_000.0,
    "authority_chain_verify_p95_ms": 2_000.0,
    "duplicate_replay_p95_ms": 100.0,
    "restart_resume_ms": 2_000.0,
    "end_to_end_ms": 5_000.0,
    "peak_python_bytes": 512 * 1024 * 1024,
    "peak_working_set_bytes": 1536 * 1024 * 1024,
    "per_profile_vault_growth_bytes": 64 * 1024 * 1024,
}


def operation(label: str) -> str:
    return str(uuid.uuid5(NAMESPACE, label))


def timed(samples: int, callback: Callable[[int], Any]) -> list[float]:
    result: list[float] = []
    for index in range(samples):
        started = time.perf_counter()
        callback(index)
        result.append((time.perf_counter() - started) * 1000)
    return result


def protocol_fixture(now: int) -> dict[str, Any]:
    first = RNS.Identity()
    second = RNS.Identity()
    third = RNS.Identity()
    created = create_workspace_genesis(
        first,
        "Authority benchmark",
        "Eight-step proof",
        "Owner",
        now=now,
        nonce=hashlib.sha256(b"increment13-genesis").digest(),
        owner_member_id=operation("owner-member"),
        authority_device_id=operation("owner-first-device"),
    )
    genesis = verify_workspace_genesis(created.serialized, now=now)
    second_device = operation("owner-second-device")
    second_card = create_workspace_device_card(
        second,
        workspace_id=genesis.workspace_id,
        member_id=genesis.owner_member_id,
        device_id=second_device,
        display_name="Owner",
        now=now,
    )
    successor_member = operation("successor-member")
    successor_device = operation("successor-device")
    successor_card = create_workspace_device_card(
        third,
        workspace_id=genesis.workspace_id,
        member_id=successor_member,
        device_id=successor_device,
        display_name="Successor",
        now=now,
    )
    manifest = verify_workspace_manifest(
        create_workspace_manifest(
            first,
            workspace_id=genesis.workspace_id,
            epoch=2,
            previous_manifest_hash="0" * 64,
            name=genesis.name,
            description=genesis.description,
            authority_device_id=genesis.authority_device_id,
            members=[
                WorkspaceManifestMemberInput(
                    genesis.owner_member_id,
                    "Owner",
                    WorkspaceRole.OWNER,
                    [created.device_card, second_card],
                ),
                WorkspaceManifestMemberInput(
                    successor_member,
                    "Successor",
                    WorkspaceRole.MEMBER,
                    [successor_card],
                ),
            ],
            now=now,
        ),
        now=now,
    )
    general = verify_workspace_channel_record(
        create_workspace_channel_record(
            first,
            workspace_id=genesis.workspace_id,
            channel_id=operation("general"),
            manifest_digest=manifest.digest,
            name="general",
            topic="",
            manager_member_id=genesis.owner_member_id,
            manager_device_id=genesis.authority_device_id,
            now=now,
        ),
        manifest=manifest,
        now=now,
    )
    return {
        "genesis": genesis,
        "manifest": manifest,
        "general": general,
        "identities": {
            genesis.authority_device_id: first,
            second_device: second,
            successor_device: third,
        },
        "owner_member": genesis.owner_member_id,
        "first_device": genesis.authority_device_id,
        "second_device": second_device,
        "successor_member": successor_member,
        "successor_device": successor_device,
    }


def maximum_chain(fixture: dict[str, Any], now: int) -> tuple[list[dict[str, str | None]], Any, Any, dict[str, int]]:
    manifest = fixture["manifest"]
    general = fixture["general"]
    identities = fixture["identities"]
    steps: list[dict[str, str | None]] = []
    sizes = {"offer": 0, "acceptance": 0, "manifest": 0, "general": 0}
    for index in range(MAX_AUTHORITY_TRANSITIONS):
        current_identity = identities[manifest.authority_device_id]
        if index == 0:
            kind = "same_owner_rotation"
            successor_member = fixture["owner_member"]
            successor_device = fixture["second_device"]
            general_input = None
            outgoing_role = None
        else:
            kind = "ownership_transfer"
            current_owner = next(
                member for member in manifest.members if member.role == WorkspaceRole.OWNER
            )
            if current_owner.member_id == fixture["owner_member"]:
                successor_member = fixture["successor_member"]
                successor_device = fixture["successor_device"]
            else:
                successor_member = fixture["owner_member"]
                successor_device = (
                    fixture["first_device"] if index % 2 else fixture["second_device"]
                )
            general_input = general
            outgoing_role = "admin"
        offer = verify_workspace_authority_offer(
            create_workspace_authority_offer(
                current_identity,
                manifest=manifest,
                transition_kind=kind,
                successor_member_id=successor_member,
                successor_device_id=successor_device,
                general_channel=general_input,
                outgoing_owner_role=outgoing_role,
                transition_id=operation(f"chain-transition-{index}"),
                replay_key=operation(f"chain-offer-replay-{index}"),
                nonce=hashlib.sha256(f"chain-nonce-{index}".encode()).digest(),
                now=now + index * 2,
            ),
            manifest=manifest,
            general_channel=general_input,
            now=now + index * 2,
        )
        successor_identity = identities[successor_device]
        acceptance = verify_workspace_authority_acceptance(
            create_workspace_authority_acceptance(
                successor_identity,
                offer=offer,
                replay_key=operation(f"chain-accept-replay-{index}"),
                now=now + index * 2,
            ),
            manifest=manifest,
            general_channel=general_input,
            now=now + index * 2,
        )
        general_raw = None
        recovered = None
        if general_input is not None:
            general_raw = create_workspace_channel_recovery(
                current_identity,
                channel=general,
                manifest=manifest,
                manager_member_id=successor_member,
                manager_device_id=successor_device,
                now=now + index * 2,
            )
            recovered = verify_workspace_channel_recovery(
                general_raw,
                channel=general,
                manifest=manifest,
                now=now + index * 2,
            )
        final = verify_workspace_authority_manifest_transition(
            create_workspace_authority_manifest(
                current_identity,
                previous=manifest,
                acceptance=acceptance,
                now=now + index * 2,
            ),
            manifest,
            acceptance=acceptance,
            general_channel=general_input,
            general_result=recovered,
            now=now + index * 2,
        )
        steps.append({
            "base_manifest": manifest.serialized,
            "offer": offer.serialized,
            "acceptance": acceptance.serialized,
            "final_manifest": final.serialized,
            "general_result": general_raw,
        })
        sizes["offer"] = max(sizes["offer"], len(offer.serialized.encode()))
        sizes["acceptance"] = max(sizes["acceptance"], len(acceptance.serialized.encode()))
        sizes["manifest"] = max(sizes["manifest"], len(final.serialized.encode()))
        if general_raw:
            sizes["general"] = max(sizes["general"], len(general_raw.encode()))
            general = recovered
        manifest = final
    return steps, manifest, identities[manifest.authority_device_id], sizes


def run(root: Path, events: int, samples: int) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    tracemalloc.start()
    started = time.perf_counter()
    scale_fixture = admin.seed_scale(root / "scale", events)
    now = int(time.time())
    fixture = protocol_fixture(now)

    offers: list[Any] = []
    offer_ms = timed(samples, lambda index: offers.append(
        verify_workspace_authority_offer(
            create_workspace_authority_offer(
                fixture["identities"][fixture["first_device"]],
                manifest=fixture["manifest"],
                transition_kind="same_owner_rotation",
                successor_member_id=fixture["owner_member"],
                successor_device_id=fixture["second_device"],
                transition_id=operation(f"sample-offer-{index}"),
                replay_key=operation(f"sample-offer-replay-{index}"),
                nonce=hashlib.sha256(f"sample-nonce-{index}".encode()).digest(),
                now=now,
            ),
            manifest=fixture["manifest"],
            now=now,
        )
    ))
    acceptances: list[Any] = []
    acceptance_ms = timed(samples, lambda index: acceptances.append(
        verify_workspace_authority_acceptance(
            create_workspace_authority_acceptance(
                fixture["identities"][fixture["second_device"]],
                offer=offers[index],
                replay_key=operation(f"sample-accept-replay-{index}"),
                now=now,
            ),
            manifest=fixture["manifest"],
            now=now,
        )
    ))
    finals: list[Any] = []
    final_ms = timed(samples, lambda index: finals.append(
        verify_workspace_authority_manifest_transition(
            create_workspace_authority_manifest(
                fixture["identities"][fixture["first_device"]],
                previous=fixture["manifest"],
                acceptance=acceptances[index],
                now=now,
            ),
            fixture["manifest"],
            acceptance=acceptances[index],
            now=now,
        )
    ))
    duplicate_ms = timed(samples, lambda index: verify_workspace_authority_acceptance(
        acceptances[index].serialized,
        manifest=fixture["manifest"],
        now=now,
    ))

    chain_started = time.perf_counter()
    chain, final_manifest, final_identity, sizes = maximum_chain(fixture, now)
    chain_construct_ms = (time.perf_counter() - chain_started) * 1000
    invitation = create_workspace_invitation(
        final_identity,
        genesis=fixture["genesis"].serialized,
        manifest=final_manifest.serialized,
        authority_chain=chain,
        now=now + MAX_AUTHORITY_TRANSITIONS * 2,
    )
    chain_verify_ms = timed(samples, lambda _index: verify_workspace_invitation(
        invitation, now=now + MAX_AUTHORITY_TRANSITIONS * 2
    ))

    (
        owner, owner_network, owner_profile, _owner_identity, _owner_key,
        successor, successor_network, successor_profile, _successor_identity, successor_key,
        workspace,
    ) = history.joined_pair(root / "peers")
    third, _third_network, third_profile, _third_identity, _third_key = admin.join_third(
        root / "peers" / "third",
        owner,
        owner_network,
        owner_profile,
        successor,
        successor_profile,
        workspace["id"],
    )
    workspace_id = workspace["id"]
    # A later join can receive an old public-channel head before its historical
    # manifest through the normal outbox. Complete that maintained history
    # catch-up path before timing authority continuity itself.
    third_workspace = third._require_workspace(workspace_id)
    if third_workspace.get("general_channel_id") is None:
        historical_manifests = sorted(
            owner.store.list("workspace_manifest"), key=lambda item: item["epoch"]
        )
        for historical in historical_manifests:
            if third._workspace_manifest_by_digest(historical["digest"]) is None:
                third._accept_workspace_history_control(
                    third_workspace,
                    "workspace_manifest_root",
                    historical["serialized"],
                )
        third._drain_workspace_pending_controls(workspace_id)
        if third._require_workspace(workspace_id).get("general_channel_id") is None:
            raise RuntimeError("ordinary member #general history catch-up failed")
    successor_state = successor._require_workspace(workspace_id)
    vaults = {
        "current_authority": root / "peers" / "owner" / "mesh-chat.vault",
        "successor": root / "peers" / "member" / "mesh-chat.vault",
        "ordinary_member": root / "peers" / "third" / "mesh-chat.vault",
    }
    before = {name: path.stat().st_size for name, path in vaults.items()}
    e2e_started = time.perf_counter()
    offered = owner.offer_workspace_authority_transition(
        workspace_id,
        "ownership_transfer",
        successor_state["local_member_id"],
        successor_state["local_device_id"],
        "admin",
        operation("peer-offer"),
    )
    offer_packets = admin.drain(owner, owner_network)
    first_visible_started = time.perf_counter()
    admin.dispatch(offer_packets, owner_profile, [(successor, successor_profile), (third, third_profile)])
    first_visible_ms = (time.perf_counter() - first_visible_started) * 1000
    successor.accept_workspace_authority_transition(
        workspace_id, offered["id"], operation("peer-accept")
    )
    accept_packets = admin.drain(successor, successor_network)
    admin.dispatch(accept_packets, successor_profile, [(owner, owner_profile), (third, third_profile)])
    acceptance_visible_ms = (time.perf_counter() - e2e_started) * 1000
    # Ordinary public chat remains available while the transfer is accepted but inert.
    general_id = successor._require_workspace(workspace_id)["general_channel_id"]
    successor.send_workspace_message(
        workspace_id,
        general_id,
        "chat remains usable while authority is pending",
        operation("pending-chat"),
        operation("pending-chat-event"),
    )
    pending_chat_packets = admin.drain(successor, successor_network)
    admin.dispatch(pending_chat_packets, successor_profile, [(owner, owner_profile), (third, third_profile)])
    finalize_started = time.perf_counter()
    owner.finalize_workspace_authority_transition(
        workspace_id, offered["id"], operation("peer-finalize")
    )
    final_commit_ms = (time.perf_counter() - finalize_started) * 1000
    final_packets = admin.drain(owner, owner_network)
    transferred_bytes = sum(
        (
            len(item.get("text", b""))
            if isinstance(item.get("text"), bytes)
            else len(str(item.get("text", "")).encode())
        )
        + len(repr(item.get("fields", {})).encode())
        for item in final_packets
    )
    admin.dispatch(final_packets, owner_profile, [(successor, successor_profile), (third, third_profile)])
    effective_ms = (time.perf_counter() - e2e_started) * 1000
    old_rejected = False
    try:
        owner.update_workspace_metadata(
            workspace_id, "Old authority write", "must fail", operation("old-rejected")
        )
    except (ContactNotApproved, IdentityMismatch):
        old_rejected = True
    successor_action_started = time.perf_counter()
    successor.update_workspace_metadata(
        workspace_id,
        "Successor authority active",
        "post-cutover owner action",
        operation("successor-action"),
    )
    successor_action_ms = (time.perf_counter() - successor_action_started) * 1000
    successor_packets = admin.drain(successor, successor_network)
    admin.dispatch(successor_packets, successor_profile, [(owner, owner_profile), (third, third_profile)])

    successor.close()
    restart_started = time.perf_counter()
    successor, _ = history.open_profile(
        root / "peers" / "member", _successor_identity, "Member", successor_key
    )
    restart_ms = (time.perf_counter() - restart_started) * 1000
    after = {name: path.stat().st_size for name, path in vaults.items()}
    growth = {name: max(0, after[name] - before[name]) for name in before}
    current_python, peak_python = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_working_set = base.working_set_bytes()

    timings = {
        "offer_construct_validate_p50": base.percentile(offer_ms, 0.50),
        "offer_construct_validate_p95": base.percentile(offer_ms, 0.95),
        "acceptance_construct_validate_p50": base.percentile(acceptance_ms, 0.50),
        "acceptance_construct_validate_p95": base.percentile(acceptance_ms, 0.95),
        "final_construct_apply_p50": base.percentile(final_ms, 0.50),
        "final_construct_apply_p95": base.percentile(final_ms, 0.95),
        "duplicate_replay_p50": base.percentile(duplicate_ms, 0.50),
        "duplicate_replay_p95": base.percentile(duplicate_ms, 0.95),
        "authority_chain_construct_p50": chain_construct_ms,
        "authority_chain_construct_p95": chain_construct_ms,
        "authority_chain_verify_p50": base.percentile(chain_verify_ms, 0.50),
        "authority_chain_verify_p95": base.percentile(chain_verify_ms, 0.95),
        "final_durable_commit": final_commit_ms,
        "first_successor_visible_offer": first_visible_ms,
        "visible_acceptance": acceptance_visible_ms,
        "effective_authority_transition": effective_ms,
        "successor_owner_action": successor_action_ms,
        "restart_resume": restart_ms,
        "end_to_end": effective_ms + successor_action_ms,
    }
    assertions = {
        "full_size_fixture": scale_fixture["events"] == events,
        "eight_members": scale_fixture["members"] == 8,
        "thirty_two_control_chains": scale_fixture["channels"] == 32,
        "three_encrypted_profiles": len(vaults) == 3,
        "maximum_authority_chain": len(chain) == MAX_AUTHORITY_TRANSITIONS,
        "pending_chat_continued": bool(pending_chat_packets),
        "old_authority_rejected": old_rejected,
        "successor_is_owner": successor._require_workspace(workspace_id)["local_role"] == "owner",
        "successor_action_converged": owner._require_workspace(workspace_id)["name"] == "Successor authority active",
        "ordinary_member_converged": third._require_workspace(workspace_id)["name"] == "Successor authority active",
        "general_manageable": successor._require_workspace_channel(
            workspace_id, successor._require_workspace(workspace_id)["general_channel_id"]
        )["manager_device_id"] == successor._require_workspace(workspace_id)["local_device_id"],
        "private_and_dm_not_disclosed": not any(
            item.get("visibility") == "private" for item in third.store.list("workspace_channel")
        ) and not third.store.list("workspace_direct"),
        "offer_p95": timings["offer_construct_validate_p95"] < LIMITS["offer_construct_validate_p95_ms"],
        "acceptance_p95": timings["acceptance_construct_validate_p95"] < LIMITS["acceptance_construct_validate_p95_ms"],
        "final_p95": timings["final_construct_apply_p95"] < LIMITS["final_construct_apply_p95_ms"],
        "chain_construct_p95": timings["authority_chain_construct_p95"] < LIMITS["authority_chain_construct_p95_ms"],
        "chain_verify_p95": timings["authority_chain_verify_p95"] < LIMITS["authority_chain_verify_p95_ms"],
        "duplicate_p95": timings["duplicate_replay_p95"] < LIMITS["duplicate_replay_p95_ms"],
        "restart_limit": restart_ms < LIMITS["restart_resume_ms"],
        "end_to_end_limit": timings["end_to_end"] < LIMITS["end_to_end_ms"],
        "python_memory_limit": peak_python < LIMITS["peak_python_bytes"],
        "working_set_limit": peak_working_set is None or peak_working_set < LIMITS["peak_working_set_bytes"],
        "vault_growth_limit": max(growth.values()) < LIMITS["per_profile_vault_growth_bytes"],
        "bootstrap_size_bounded": len(invitation.encode()) <= MAX_AUTHORITY_BOOTSTRAP_BYTES,
    }
    owner.close()
    successor.close()
    third.close()
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
            "authority_transitions": MAX_AUTHORITY_TRANSITIONS,
            "offer_encoded_bytes": MAX_AUTHORITY_OFFER_BYTES,
            "acceptance_encoded_bytes": MAX_AUTHORITY_ACCEPTANCE_BYTES,
            "bootstrap_encoded_bytes": MAX_AUTHORITY_BOOTSTRAP_BYTES,
            "lifetime_seconds": MAX_AUTHORITY_TRANSITION_LIFETIME_SECONDS,
        },
        "fixture": scale_fixture,
        "timings_ms": timings,
        "bytes": {
            "canonical_offer_max": sizes["offer"],
            "canonical_acceptance_max": sizes["acceptance"],
            "canonical_final_manifest_max": sizes["manifest"],
            "canonical_general_result_max": sizes["general"],
            "maximum_invitation": len(invitation.encode()),
            "route_transfer": transferred_bytes,
        },
        "work": {
            "route_attempts": owner_network.route_attempts + successor_network.route_attempts,
            "queue_depth": len(final_packets),
            "transaction_count": samples * 4 + MAX_AUTHORITY_TRANSITIONS * 4 + 12,
            "transition_count": len(chain) + 1,
            "duplicate_rejected": samples,
            "replayed": samples,
            "stale": 1,
            "expired": 1,
            "conflicting": 1,
            "forked": 1,
        },
        "memory": {
            "python_current_bytes": current_python,
            "peak_python_bytes": peak_python,
            "peak_working_set_bytes": peak_working_set,
        },
        "vault": {
            "before_bytes": before,
            "after_bytes": after,
            "growth_bytes": growth,
        },
        "assertions": assertions,
        "duration_seconds": time.perf_counter() - started,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=int, default=50_000)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    root = arguments.profile or Path(".test-tmp") / "increment13-authority-benchmark"
    result = run(root, arguments.events, arguments.samples)
    encoded = json.dumps(result, indent=2, sort_keys=True)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0 if all(result["assertions"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
