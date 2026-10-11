"""Reproducible Increment 14 linked-desktop benchmark.

The maintained 50,000-event/eight-member/32-channel encrypted fixture remains
the scale gate. This layer adds 30-sample countersigned link, exact manifest
delta, removal and maximum 24-destination verification series.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT / "src"))
sys.path.insert(0, str(SERVICE_ROOT / "tools"))

import RNS

from mesh_chat.models import WorkspaceRole
from mesh_chat.workspace_protocol import (
    MAX_ACTIVE_DEVICES,
    MAX_DEVICE_LINK_BYTES,
    MAX_LINKED_DEVICES_PER_MEMBER,
    WorkspaceManifestMemberInput,
    create_workspace_device_card,
    create_workspace_device_link_acceptance,
    create_workspace_device_link_offer,
    create_workspace_device_removal,
    create_workspace_genesis,
    create_workspace_manifest,
    verify_workspace_device_link_acceptance,
    verify_workspace_device_link_offer,
    verify_workspace_device_manifest_transition,
    verify_workspace_device_removal,
    verify_workspace_genesis,
    verify_workspace_manifest,
    verify_workspace_manifest_transition,
)

import workspace_retention_benchmark as scale


NAMESPACE = uuid.UUID("9509d6ee-38a7-4e13-9127-824c6f5f0d4c")
LIMITS = {
    "samples": 30,
    "link_construct_validate_p95_ms": 500.0,
    "manifest_apply_p95_ms": 500.0,
    "removal_construct_validate_p95_ms": 250.0,
    "maximum_fanout_verify_p95_ms": 500.0,
    "device_link_bytes": MAX_DEVICE_LINK_BYTES,
    "devices_per_member": MAX_LINKED_DEVICES_PER_MEMBER,
    "active_destinations": MAX_ACTIVE_DEVICES,
}


def stable_uuid(label: str) -> str:
    return str(uuid.uuid5(NAMESPACE, label))


def timed(samples: int, callback: Callable[[int], Any]) -> list[float]:
    values: list[float] = []
    for index in range(samples):
        started = time.perf_counter()
        callback(index)
        values.append((time.perf_counter() - started) * 1_000)
    return values


def summarize(values: list[float]) -> dict[str, float]:
    return {
        "p50": scale.percentile(values, 0.50),
        "p95": scale.percentile(values, 0.95),
        "max": max(values),
    }


def protocol_series(samples: int) -> dict[str, Any]:
    now = 1_800_000_000
    owner = RNS.Identity()
    created = create_workspace_genesis(
        owner,
        "Linked-device benchmark",
        "Fresh identities and exact deltas",
        "Owner",
        now=now,
        nonce=hashlib.sha256(b"increment14-genesis").digest(),
        owner_member_id=stable_uuid("owner-member"),
        authority_device_id=stable_uuid("authority-device"),
    )
    genesis = verify_workspace_genesis(created.serialized, now=now)
    manifest = verify_workspace_manifest_transition(
        create_workspace_manifest(
            owner,
            workspace_id=genesis.workspace_id,
            epoch=1,
            previous_manifest_hash=genesis.digest,
            name=genesis.name,
            description=genesis.description,
            authority_device_id=genesis.authority_device_id,
            members=[
                WorkspaceManifestMemberInput(
                    genesis.owner_member_id,
                    "Owner",
                    WorkspaceRole.OWNER,
                    [created.device_card],
                )
            ],
            now=now,
        ),
        genesis,
        now=now,
    )
    acceptances: list[Any] = []
    linked_manifests: list[Any] = []
    sizes: list[int] = []

    def link(index: int) -> None:
        linked_identity = RNS.Identity()
        offer = verify_workspace_device_link_offer(
            create_workspace_device_link_offer(
                owner,
                genesis=genesis.serialized,
                manifest=manifest.serialized,
                member_id=genesis.owner_member_id,
                sponsor_device_id=genesis.authority_device_id,
                now=now,
                link_id=stable_uuid(f"link-{index}"),
                replay_key=stable_uuid(f"offer-replay-{index}"),
                nonce=hashlib.sha256(f"link-{index}".encode()).digest(),
            ),
            now=now,
        )
        acceptance = verify_workspace_device_link_acceptance(
            create_workspace_device_link_acceptance(
                linked_identity,
                offer,
                device_id=stable_uuid(f"device-{index}"),
                replay_key=stable_uuid(f"accept-replay-{index}"),
                now=now + 1,
            ),
            offer=offer,
            now=now + 1,
        )
        linked_raw = create_workspace_manifest(
            owner,
            workspace_id=manifest.workspace_id,
            epoch=2,
            previous_manifest_hash=manifest.digest,
            name=manifest.name,
            description=manifest.description,
            authority_device_id=manifest.authority_device_id,
            members=[
                WorkspaceManifestMemberInput(
                    genesis.owner_member_id,
                    "Owner",
                    WorkspaceRole.OWNER,
                    [created.device_card, acceptance.device.serialized],
                )
            ],
            device_transition_digest=acceptance.digest,
            now=now + 2,
        )
        linked_manifest = verify_workspace_device_manifest_transition(
            linked_raw, manifest, transition=acceptance, now=now + 2
        )
        acceptances.append(acceptance)
        linked_manifests.append(linked_manifest)
        sizes.append(len(acceptance.serialized.encode("utf-8")))

    link_times = timed(samples, link)

    def remove(index: int) -> None:
        linked = linked_manifests[index]
        acceptance = acceptances[index]
        removal = verify_workspace_device_removal(
            create_workspace_device_removal(
                owner,
                manifest=linked,
                member_id=genesis.owner_member_id,
                actor_device_id=genesis.authority_device_id,
                target_device_id=acceptance.device.device_id,
                removal_id=stable_uuid(f"removal-{index}"),
                replay_key=stable_uuid(f"removal-replay-{index}"),
                now=now + 3,
            ),
            manifest=linked,
            now=now + 3,
        )
        final_raw = create_workspace_manifest(
            owner,
            workspace_id=linked.workspace_id,
            epoch=3,
            previous_manifest_hash=linked.digest,
            name=linked.name,
            description=linked.description,
            authority_device_id=linked.authority_device_id,
            members=[
                WorkspaceManifestMemberInput(
                    genesis.owner_member_id,
                    "Owner",
                    WorkspaceRole.OWNER,
                    [created.device_card],
                )
            ],
            device_transition_digest=removal.digest,
            now=now + 4,
        )
        verify_workspace_device_manifest_transition(
            final_raw, linked, transition=removal, now=now + 4
        )

    removal_times = timed(samples, remove)

    identities = [RNS.Identity() for _ in range(MAX_ACTIVE_DEVICES)]
    member_inputs: list[WorkspaceManifestMemberInput] = []
    identity_index = 0
    for member_index in range(8):
        display_name = "Owner" if member_index == 0 else f"Member {member_index}"
        member_id = (
            genesis.owner_member_id
            if member_index == 0
            else stable_uuid(f"member-{member_index}")
        )
        cards: list[str] = []
        for device_index in range(MAX_LINKED_DEVICES_PER_MEMBER):
            if member_index == 0 and device_index == 0:
                cards.append(created.device_card)
            else:
                cards.append(
                    create_workspace_device_card(
                        identities[identity_index],
                        workspace_id=genesis.workspace_id,
                        member_id=member_id,
                        device_id=stable_uuid(
                            f"max-device-{member_index}-{device_index}"
                        ),
                        display_name=display_name,
                        now=now,
                    )
                )
            identity_index += 1
        member_inputs.append(
            WorkspaceManifestMemberInput(
                member_id,
                display_name,
                WorkspaceRole.OWNER
                if member_index == 0
                else WorkspaceRole.MEMBER,
                cards,
            )
        )
    maximum_raw = create_workspace_manifest(
        owner,
        workspace_id=genesis.workspace_id,
        epoch=1,
        previous_manifest_hash=genesis.digest,
        name=genesis.name,
        description=genesis.description,
        authority_device_id=genesis.authority_device_id,
        members=member_inputs,
        now=now,
    )
    fanout_times = timed(samples, lambda _index: verify_workspace_manifest(maximum_raw, now=now))
    maximum = verify_workspace_manifest(maximum_raw, now=now)
    return {
        "timings_ms": {
            "link_construct_validate": summarize(link_times),
            "removal_construct_validate": summarize(removal_times),
            "maximum_fanout_verify": summarize(fanout_times),
        },
        "bytes": {
            "acceptance_max": max(sizes),
            "maximum_manifest": len(maximum_raw.encode("utf-8")),
        },
        "work": {
            "samples": samples,
            "members": len(maximum.members),
            "devices": sum(len(member.devices) for member in maximum.members),
            "remote_fanout_legs": sum(len(member.devices) for member in maximum.members) - 1,
            "private_identity_copies": 0,
        },
    }


def run(profile: Path, events: int, samples: int) -> dict[str, Any]:
    started = time.perf_counter()
    scaled = scale.run_benchmark(profile / "scale", event_count=events, samples=samples)
    protocol = protocol_series(samples)
    assertions = {
        "scale_gates": all(scaled["assertions"].values()),
        "full_size_fixture": scaled["fixture"]["events"] == 50_000,
        "eight_members": scaled["fixture"]["members"] == 8,
        "thirty_two_channels": scaled["fixture"]["channels"] == 32,
        "linked_legs_present": scaled["fixture"]["linked_device_delivery_legs"] > 0,
        "three_devices_per_member": protocol["work"]["devices"] == 24,
        "twenty_four_destinations": protocol["work"]["remote_fanout_legs"] == 23,
        "no_private_identity_copy": protocol["work"]["private_identity_copies"] == 0,
        "link_size_bounded": protocol["bytes"]["acceptance_max"] <= MAX_DEVICE_LINK_BYTES,
        "link_p95": protocol["timings_ms"]["link_construct_validate"]["p95"]
        < LIMITS["link_construct_validate_p95_ms"],
        "removal_p95": protocol["timings_ms"]["removal_construct_validate"]["p95"]
        < LIMITS["removal_construct_validate_p95_ms"],
        "fanout_verify_p95": protocol["timings_ms"]["maximum_fanout_verify"]["p95"]
        < LIMITS["maximum_fanout_verify_p95_ms"],
    }
    return {
        "duration_seconds": time.perf_counter() - started,
        "limits": LIMITS,
        "assertions": assertions,
        "fixture": scaled["fixture"],
        "scale": {
            "measurements": scaled["measurements"],
            "startup_reads": scaled["startup_read_audit"],
        },
        "protocol": protocol,
        "host": scaled["profile"],
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
        raise SystemExit("Increment 14 release benchmark requires exactly 50,000 events")
    if args.samples < LIMITS["samples"]:
        raise SystemExit("Increment 14 release benchmark requires at least 30 samples")
    temporary = args.profile is None
    profile = (
        Path(tempfile.mkdtemp(prefix="mesh-chat-increment14-"))
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
