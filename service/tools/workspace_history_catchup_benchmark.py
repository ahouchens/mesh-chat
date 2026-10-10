"""Reproducible Increment 11 peer-history catch-up benchmark.

The benchmark keeps the maintained Increment 9 50,000-event encrypted fixture
as its scale floor, then runs a second production-shaped pair of independently
encrypted profiles through signed request, bounded response, verification,
durable commit, replay rejection, and restart/resume paths.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import tracemalloc
import uuid
from pathlib import Path
from typing import Any, Callable

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT / "src"))

import LXMF
import RNS

from mesh_chat.invitations import readable_fingerprint
from mesh_chat.errors import ContactNotApproved
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore
from mesh_chat.workspace_protocol import (
    MAX_HISTORY_EVENTS,
    MAX_HISTORY_RESPONSE_BYTES,
    create_workspace_history_request,
    create_workspace_history_response,
    verify_workspace_history_request,
    verify_workspace_history_response,
    workspace_direct_conversation_id,
)
from mesh_chat.workspace_wire import parse_workspace_payload

import workspace_retention_benchmark as base


class RecordingNetwork(base.NoRouteNetwork):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[dict[str, Any]] = []

    def recipient_ready(self, _destination: bytes) -> bool:
        return True

    def path_known(self, _destination: bytes) -> bool:
        return True

    def send_with_fields(self, **value: Any) -> str:
        self.route_attempts += 1
        self.sent.append(value)
        return f"history-native-{len(self.sent)}"


def profile(identity: RNS.Identity, name: str) -> dict[str, Any]:
    public_key = identity.get_public_key()
    destination = RNS.Destination.hash(identity, "lxmf", "delivery")
    return {
        "display_name": name,
        "public_identity": base64.urlsafe_b64encode(public_key).decode("ascii"),
        "identity_hash": identity.hash.hex(),
        "destination_hash": destination.hex(),
        "fingerprint": readable_fingerprint(public_key),
        "created_at": time.time(),
    }


def open_profile(
    root: Path, identity: RNS.Identity, name: str, key: bytes
) -> tuple[MeshChatService, RecordingNetwork]:
    store = VaultStore(root, key, allow_unprotected_for_tests=True)
    if store.get("identity", "local") is not None:
        store.delete("identity", "local")
    if store.get("profile", "local") is not None:
        store.delete("profile", "local")
    service = MeshChatService(store, root, lambda _event: None)
    store.put_many([
        ("identity", "local", {
            "private_key": base64.urlsafe_b64encode(
                identity.get_private_key()
            ).decode("ascii")
        }),
        ("profile", "local", profile(identity, name)),
    ])
    service._identity = identity
    service._shutdown.set()
    service._retry_thread.join(timeout=1)
    network = RecordingNetwork()
    service.network = network  # type: ignore[assignment]
    return service, network


def native(
    sent: dict[str, Any], source: dict[str, Any], destination: dict[str, Any]
) -> LXMF.LXMessage:
    return LXMF.LXMessage(
        None,
        None,
        content=sent["text"],
        fields=sent["fields"],
        desired_method=LXMF.LXMessage.DIRECT,
        source_hash=bytes.fromhex(source["destination_hash"]),
        destination_hash=bytes.fromhex(destination["destination_hash"]),
    )


def deliver(
    recipient: MeshChatService,
    sent: dict[str, Any],
    source: dict[str, Any],
    destination: dict[str, Any],
) -> None:
    recipient._on_inbound_locked(native(sent, source, destination))


def flush(service: MeshChatService, network: RecordingNetwork) -> list[dict[str, Any]]:
    before = len(network.sent)
    service._retry_workspace_outbox()
    return network.sent[before:]


def operation(label: str) -> str:
    return str(uuid.uuid5(base.NAMESPACE, f"increment11-{label}"))


def joined_pair(root: Path) -> tuple[Any, ...]:
    owner_identity = RNS.Identity()
    member_identity = RNS.Identity()
    owner_key = hashlib.sha256(b"increment11-owner-vault").digest()
    member_key = hashlib.sha256(b"increment11-member-vault").digest()
    owner, owner_network = open_profile(root / "owner", owner_identity, "Owner", owner_key)
    member, member_network = open_profile(root / "member", member_identity, "Member", member_key)
    owner_profile = owner._require_profile()
    member_profile = member._require_profile()
    workspace = owner.create_workspace(operation("create"), "Increment 11", "Peer catch-up")
    invitation = owner.create_workspace_invitation_command(
        workspace["id"], operation("invite")
    )
    member.submit_workspace_join(invitation["text"], operation("join"))
    for packet in flush(member, member_network):
        deliver(owner, packet, member_profile, owner_profile)
    request = owner.workspace_snapshot()["workspace_join_requests"][0]
    owner.approve_workspace_join(workspace["id"], request["id"], operation("approve"))
    controls = flush(owner, owner_network)
    controls.sort(key=lambda packet: 0 if parse_workspace_payload(
        native(packet, owner_profile, member_profile)
    ).kind == "workspace_manifest_root" else 1)
    for packet in controls:
        deliver(member, packet, owner_profile, member_profile)
    return (
        owner, owner_network, owner_profile, owner_identity, owner_key,
        member, member_network, member_profile, member_identity, member_key,
        workspace,
    )


def timed(samples: int, callback: Callable[[int], Any]) -> list[float]:
    values: list[float] = []
    for index in range(samples):
        started = time.perf_counter()
        callback(index)
        values.append((time.perf_counter() - started) * 1000)
    return values


def command_version(command: list[str]) -> str | None:
    try:
        lines = subprocess.check_output(
            command, text=True, stderr=subprocess.STDOUT, timeout=10
        ).splitlines()
        return lines[-1] if lines else None
    except Exception:
        return None


def tool_version(name: str, fallback: list[str]) -> str | None:
    candidates: list[list[str]] = []
    if name == "node":
        configured = os.environ.get("MESH_CHAT_NODE")
        if configured:
            candidates.append([configured, "--version"])
        candidates.append([
            str(Path.home() / ".cache" / "codex-runtimes" /
                "codex-primary-runtime" / "dependencies" / "node" /
                "bin" / ("node.exe" if os.name == "nt" else "node")),
            "--version",
        ])
    elif name == "rustc":
        candidates.append([
            str(Path.home() / ".cargo" / "bin" /
                ("rustc.exe" if os.name == "nt" else "rustc")),
            "--version",
        ])
    candidates.append(fallback)
    for candidate in candidates:
        version = command_version(candidate)
        if version is not None:
            return version
    return None


def run(profile_dir: Path, events: int, samples: int) -> dict[str, Any]:
    tracemalloc.start()
    started = time.perf_counter()

    # Scale fixture: exact maintained Increment 9 encrypted shapes, eight
    # members, 32 control chains, roots/replies/mutations/tombstones and queues.
    fixture_identity = RNS.Identity()
    fixture_service, _ = base.open_service(
        profile_dir / "fixture",
        hashlib.sha256(b"increment11-fixture-vault").digest(),
        fixture_identity,
        initialize_profile=True,
    )
    fixture_workspace = fixture_service.create_workspace(
        operation("fixture-create"), "Increment 11 scale", "50k retained events"
    )
    channels = [fixture_service._require_workspace_channel(
        fixture_workspace["id"], fixture_workspace["general_channel_id"]
    )]
    for index in range(1, 32):
        channels.append(fixture_service.create_workspace_channel(
            fixture_workspace["id"], f"channel-{index:02d}", "history fixture",
            operation(f"fixture-channel-{index}"),
        ))
    fixture = base.seed_fixture(
        fixture_service, fixture_workspace, channels, events, history_age_days=120
    )
    fixture_vault_bytes = (profile_dir / "fixture" / "mesh-chat.vault").stat().st_size
    base.close_service(fixture_service)
    fixture_service.store.close()

    (
        owner, owner_network, owner_profile, owner_identity, _owner_key,
        member, member_network, member_profile, member_identity, member_key,
        workspace,
    ) = joined_pair(profile_dir / "real-pair")
    workspace_id = workspace["id"]
    conversation_id = workspace["general_channel_id"]
    owner_vault = profile_dir / "real-pair" / "owner" / "mesh-chat.vault"
    member_vault = profile_dir / "real-pair" / "member" / "mesh-chat.vault"
    owner_vault_before = owner_vault.stat().st_size
    member_vault_before = member_vault.stat().st_size
    original_documents: list[str] = []
    live_delivery_ids: list[str] = []
    for index in range(MAX_HISTORY_EVENTS):
        sent = owner.send_workspace_message(
            workspace_id,
            conversation_id,
            f"offline retained event {index:02d} older than seven days",
            operation(f"send-{index}"),
            operation(f"event-{index}"),
        )
        record = owner.store.get(
            "workspace_event", owner._workspace_event_record_id(sent["id"])
        )
        assert record is not None
        original_documents.append(record["serialized"])
        live_delivery_ids.extend(
            delivery_id
            for delivery_id in record.get("delivery_ids", ())
            if isinstance(delivery_id, str)
        )
    # Simulate a requester that remained offline past the independent seven-day
    # live-delivery window.  The canonical bodies stay retained, while every
    # ordinary delivery leg is durably expired and removed from the due queue
    # before any history request is created.
    expired_live_delivery_legs = 0
    expired_records: list[tuple[str, str, dict[str, Any]]] = []
    for delivery_id in live_delivery_ids:
        delivery = owner.store.get("workspace_delivery", delivery_id)
        if delivery is None:
            continue
        delivery["state"] = "expired"
        delivery["expires_at"] = time.time() - 1
        expired_records.append(("workspace_delivery", delivery_id, delivery))
        expired_records.extend(owner._due_records(remove=[delivery_id]))
        expired_live_delivery_legs += 1
    owner.store.put_many(expired_records)
    member_workspace = member._require_workspace(workspace_id)
    manifest = member._workspace_current_manifest(member_workspace)
    scope = member._workspace_history_scope(member_workspace, conversation_id)[0]
    streams = member._workspace_history_streams(
        member_workspace,
        scope,
        member._workspace_channel_by_digest(scope["channel_digest"]),
    )

    request_documents: list[Any] = []
    request_ms = timed(samples, lambda index: request_documents.append(
        verify_workspace_history_request(
            create_workspace_history_request(
                member_identity,
                workspace_id=workspace_id,
                request_id=operation(f"sample-request-{index}"),
                requester_member_id=member_workspace["local_member_id"],
                requester_device_id=member_workspace["local_device_id"],
                manifest_digest=manifest.digest,
                scope=scope,
                streams=streams,
                event_limit=MAX_HISTORY_EVENTS,
                byte_limit=MAX_HISTORY_RESPONSE_BYTES,
                nonce=hashlib.sha256(f"nonce-{index}".encode()).digest(),
                replay_key=operation(f"sample-replay-{index}"),
            ),
            manifest=manifest,
        )
    ))
    owner_manifest = owner._workspace_current_manifest(owner._require_workspace(workspace_id))
    response_documents: list[str] = []
    response_ms = timed(samples, lambda index: response_documents.append(
        create_workspace_history_response(
            owner_identity,
            request=request_documents[index],
            response_id=operation(f"sample-response-{index}"),
            responder_member_id=owner._require_workspace(workspace_id)["local_member_id"],
            responder_device_id=owner._require_workspace(workspace_id)["local_device_id"],
            page_index=0,
            previous_response_digest=None,
            events=original_documents,
            complete=True,
        )
    ))
    response_verify_ms = timed(samples, lambda index: verify_workspace_history_response(
        response_documents[index], manifest=owner_manifest,
        request=request_documents[index],
    ))

    private_channel = owner.create_workspace_channel(
        workspace_id,
        "owner-only",
        "confidential denial probe",
        operation("private-denial-channel"),
        "private",
        [owner._require_workspace(workspace_id)["local_member_id"]],
    )
    member_id = member_workspace["local_member_id"]
    other_member_id = operation("nonparticipant")
    dm_participants = sorted([member_id, other_member_id])

    def denial_request(index: int, kind: str) -> None:
        if kind == "private":
            denial_scope = {
                "kind": "private",
                "conversation_id": private_channel["id"],
                "channel_digest": private_channel["head_hash"],
                "participant_member_ids": [],
            }
        else:
            denial_scope = {
                "kind": "direct",
                "conversation_id": workspace_direct_conversation_id(
                    workspace_id, dm_participants
                ),
                "channel_digest": None,
                "participant_member_ids": dm_participants,
            }
        raw = create_workspace_history_request(
            member_identity,
            workspace_id=workspace_id,
            request_id=operation(f"{kind}-denial-request-{index}"),
            requester_member_id=member_id,
            requester_device_id=member_workspace["local_device_id"],
            manifest_digest=manifest.digest,
            scope=denial_scope,
            streams=streams,
            event_limit=MAX_HISTORY_EVENTS,
            byte_limit=MAX_HISTORY_RESPONSE_BYTES,
            nonce=hashlib.sha256(f"{kind}-denial-{index}".encode()).digest(),
            replay_key=operation(f"{kind}-denial-replay-{index}"),
        )
        checked = verify_workspace_history_request(raw, manifest=manifest)
        try:
            owner._workspace_history_request_authorized(
                owner._require_workspace(workspace_id), checked
            )
        except ContactNotApproved:
            return
        raise AssertionError(f"{kind} disclosure probe was authorized")

    private_denial_ms = timed(samples, lambda index: denial_request(index, "private"))
    dm_denial_ms = timed(samples, lambda index: denial_request(index, "direct"))

    catchup_started = time.perf_counter()
    member.start_workspace_history(
        workspace_id, conversation_id, operation("catchup-start")
    )
    request_packet = next(packet for packet in flush(member, member_network)
        if parse_workspace_payload(native(packet, member_profile, owner_profile)).kind
        == "workspace_history_request")
    deliver(owner, request_packet, member_profile, owner_profile)
    response_packet = next(packet for packet in flush(owner, owner_network)
        if parse_workspace_payload(native(packet, owner_profile, member_profile)).kind
        == "workspace_history_response")
    response_packets = [response_packet]
    first_page_started = time.perf_counter()
    deliver(member, response_packet, owner_profile, member_profile)
    first_page_ms = (time.perf_counter() - first_page_started) * 1000
    continuation_started = time.perf_counter()
    while member.get_workspace_history_status(
        workspace_id, conversation_id
    )["job"]["status"] not in {"complete_known", "peer_limited", "failed"}:
        continuation_requests = [
            packet for packet in flush(member, member_network)
            if parse_workspace_payload(native(
                packet, member_profile, owner_profile
            )).kind == "workspace_history_request"
        ]
        if not continuation_requests:
            break
        deliver(owner, continuation_requests[0], member_profile, owner_profile)
        continuation_responses = [
            packet for packet in flush(owner, owner_network)
            if parse_workspace_payload(native(
                packet, owner_profile, member_profile
            )).kind == "workspace_history_response"
        ]
        if not continuation_responses:
            break
        response_packets.append(continuation_responses[0])
        deliver(member, continuation_responses[0], owner_profile, member_profile)
    continuation_ms = (time.perf_counter() - continuation_started) * 1000
    total_catchup_ms = (time.perf_counter() - catchup_started) * 1000
    status = member.get_workspace_history_status(workspace_id, conversation_id)
    before_replay = status["job"]["recovered_events"]
    replay_started = time.perf_counter()
    deliver(member, response_packet, owner_profile, member_profile)
    replay_ms = (time.perf_counter() - replay_started) * 1000
    replay_unchanged = member.get_workspace_history_status(
        workspace_id, conversation_id
    )["job"]["recovered_events"] == before_replay
    recovered = [
        member.store.get("workspace_event", member._workspace_event_record_id(
            json.loads(raw)["event_id"]
        ))["serialized"]
        for raw in original_documents
    ]
    response_bytes = sum(len(parse_workspace_payload(
        native(packet, owner_profile, member_profile)
    ).document.encode("utf-8")) for packet in response_packets)
    member_vault_bytes = member_vault.stat().st_size
    owner_vault_bytes = owner_vault.stat().st_size

    # Restart the encrypted requester and verify accepted bytes and job state
    # remain durable without replaying or re-materialising the page.
    member.close()
    restart_started = time.perf_counter()
    member, _ = open_profile(
        profile_dir / "real-pair" / "member",
        member_identity,
        "Member",
        member_key,
    )
    restart_ms = (time.perf_counter() - restart_started) * 1000
    restart_status = member.get_workspace_history_status(workspace_id, conversation_id)
    current, peak_python = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    owner.close()
    member.close()

    duration = time.perf_counter() - started
    return {
        "host": {
            "os": platform.platform(),
            "cpu": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER"),
            "python": platform.python_version(),
            "rust": tool_version("rustc", ["rustc", "--version"]),
            "node": tool_version("node", ["node", "--version"]),
            "physical_memory_bytes": base.physical_memory_bytes(),
        },
        "limits": {
            "event_count_per_response": MAX_HISTORY_EVENTS,
            "encoded_bytes_per_response": MAX_HISTORY_RESPONSE_BYTES,
            "samples": samples,
        },
        "fixture": {**fixture, "vault_bytes": fixture_vault_bytes},
        "timings_ms": {
            "request_sign_verify_p50": base.percentile(request_ms, 0.50),
            "request_sign_verify_p95": base.percentile(request_ms, 0.95),
            "bounded_response_build_p50": base.percentile(response_ms, 0.50),
            "bounded_response_build_p95": base.percentile(response_ms, 0.95),
            "response_verify_p50": base.percentile(response_verify_ms, 0.50),
            "response_verify_p95": base.percentile(response_verify_ms, 0.95),
            "private_denial_p95": base.percentile(private_denial_ms, 0.95),
            "dm_denial_p95": base.percentile(dm_denial_ms, 0.95),
            "first_response_commit": first_page_ms,
            "total_catchup": total_catchup_ms,
            "duplicate_rejection": replay_ms,
            "continuation_processing": continuation_ms,
            "restart_resume": restart_ms,
        },
        "transfer": {
            "responses": len(response_packets),
            "total_bytes": response_bytes,
            "useful_events": before_replay,
            "events_per_second": before_replay / max(total_catchup_ms / 1000, 0.000001),
            "route_attempts": owner_network.route_attempts + member_network.route_attempts,
            "requester_vault_bytes": member_vault_bytes,
            "requester_vault_growth_bytes": max(
                0, member_vault_bytes - member_vault_before
            ),
            "serving_vault_bytes": owner_vault_bytes,
            "serving_vault_growth_bytes": max(
                0, owner_vault_bytes - owner_vault_before
            ),
            "peak_python_bytes": peak_python,
            "peak_working_set_bytes": base.working_set_bytes(),
            "python_current_bytes": current,
            "job_depth": 1,
            "validation_pages": 1,
            "transactions": 1,
            "prerequisite_controls": len(json.loads(
                parse_workspace_payload(native(
                    response_packet, owner_profile, member_profile
                )).document
            )["controls"]),
            "expired_live_delivery_legs": expired_live_delivery_legs,
            "permanent_gaps": restart_status["job"]["permanent_gaps"],
            "local_prune_gaps": sum(
                max(0, int(stream["retained_floor"]) - 1)
                for stream in restart_status["streams"]
            ),
            "peer_limited": restart_status["job"]["peer_limited"],
        },
        "assertions": {
            "full_size_fixture": fixture["events"] == events,
            "eight_members": fixture["members"] == 8,
            "thirty_two_channels": fixture["channels"] == 32,
            "older_than_live_window": (
                expired_live_delivery_legs == len(live_delivery_ids)
                and expired_live_delivery_legs >= MAX_HISTORY_EVENTS
            ),
            "exact_canonical_bytes": recovered == original_documents,
            "bounded_page": before_replay == MAX_HISTORY_EVENTS,
            "replay_rejected": replay_unchanged,
            "private_nonmember_denied": bool(private_denial_ms),
            "dm_nonparticipant_denied": bool(dm_denial_ms),
            "restart_durable": restart_status["job"]["recovered_events"] == before_replay,
            "complete_only_with_signed_heads": restart_status["job"]["status"] == "complete_known",
        },
        "duration_seconds": duration,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-dir", type=Path)
    parser.add_argument("--events", type=int, default=50_000)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    temporary = args.profile_dir is None
    profile_dir = args.profile_dir or Path(tempfile.mkdtemp(prefix="mesh-history-bench-"))
    try:
        result = run(profile_dir, args.events, args.samples)
        encoded = json.dumps(result, indent=2, sort_keys=True)
        if args.output:
            args.output.write_text(encoded + "\n", encoding="utf-8")
        print(encoded)
        return 0 if all(result["assertions"].values()) else 1
    finally:
        if temporary:
            shutil.rmtree(profile_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
