"""Real four-process Reticulum/LXMF topology probe.

This is deliberately not an in-memory simulation. Each peer has an isolated
Reticulum profile with shared instances and AutoInterface disabled. The only
connections are A->B, B->C and C->D TCP interfaces.
"""

from __future__ import annotations

import argparse
import base64
import json
import multiprocessing as mp
import os
import queue
import socket
import tempfile
import time
from pathlib import Path
from typing import Any

import LXMF
import RNS

from mesh_chat.reticulum_config import NetworkSettings, write_config
from mesh_chat.vault import protect_workspace


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def peer(
    name: str,
    root_value: str,
    private_key: bytes,
    settings_value: dict[str, Any],
    commands: mp.Queue,
    events: mp.Queue,
) -> None:
    root = Path(root_value)
    settings = NetworkSettings.from_dict(settings_value)
    write_config(root / "rns", settings)
    RNS.Reticulum(configdir=str(root / "rns"), loglevel=RNS.LOG_ERROR, logdest=lambda _: None)
    identity = RNS.Identity.from_bytes(private_key)
    router = LXMF.LXMRouter(
        identity=identity,
        storagepath=str(root / "lxmf-state"),
        autopeer=False,
        from_static_only=True,
        enforce_ratchets=True,
        propagation_limit=64,
        delivery_limit=64,
        sync_limit=128,
        max_peers=4,
    )
    delivery = router.register_delivery_identity(identity, display_name=name)

    def inbound(message: LXMF.LXMessage) -> None:
        events.put(
            {
                "peer": name,
                "event": "inbound",
                "text": message.content_as_string(),
                "signature_validated": message.signature_validated,
                "source": message.source_hash.hex(),
                "method": message.method,
            }
        )

    router.register_delivery_callback(inbound)
    router.announce(delivery.hash)
    events.put({"peer": name, "event": "ready", "destination": delivery.hash.hex()})
    running = True
    while running:
        try:
            command = commands.get(timeout=0.25)
        except queue.Empty:
            continue
        action = command["action"]
        if action == "announce":
            router.announce(delivery.hash)
        elif action == "send":
            target_hash = bytes.fromhex(command["destination"])
            target_public = base64.b64decode(command["public_identity"])
            if RNS.Identity.recall(target_hash) is None:
                RNS.Identity.remember(os.urandom(32), target_hash, target_public)
            RNS.Transport.request_path(target_hash)
            deadline = time.time() + command.get("timeout", 35)
            while time.time() < deadline:
                recalled = RNS.Identity.recall(target_hash)
                ratchet = RNS.Identity.get_ratchet(target_hash)
                if RNS.Transport.has_path(target_hash) and recalled and ratchet:
                    break
                time.sleep(0.2)
            recalled = RNS.Identity.recall(target_hash)
            ready = bool(RNS.Transport.has_path(target_hash) and recalled and RNS.Identity.get_ratchet(target_hash))
            events.put(
                {
                    "peer": name,
                    "event": "route",
                    "ready": ready,
                    "hops": RNS.Transport.hops_to(target_hash) if RNS.Transport.has_path(target_hash) else None,
                    "ratchet": RNS.Identity.current_ratchet_id(target_hash).hex()
                    if RNS.Identity.current_ratchet_id(target_hash)
                    else None,
                }
            )
            if ready:
                target = RNS.Destination(
                    recalled,
                    RNS.Destination.OUT,
                    RNS.Destination.SINGLE,
                    "lxmf",
                    "delivery",
                )
                message = LXMF.LXMessage(
                    target,
                    delivery,
                    content=command["text"],
                    desired_method=LXMF.LXMessage.DIRECT,
                )
                message.register_delivery_callback(
                    lambda delivered: events.put(
                        {
                            "peer": name,
                            "event": "native_delivery",
                            "state": delivered.state,
                            "method": delivered.method,
                        }
                    )
                )
                message.register_failed_callback(
                    lambda failed: events.put(
                        {"peer": name, "event": "native_failure", "state": failed.state}
                    )
                )
                router.handle_outbound(message)
        elif action == "stop":
            running = False
    router.exit_handler()
    RNS.Reticulum.exit_handler()


def wait_for(events: mp.Queue, predicate: Any, timeout: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    deadline = time.time() + timeout
    seen: list[dict[str, Any]] = []
    while time.time() < deadline:
        try:
            item = events.get(timeout=min(0.5, deadline - time.time()))
        except queue.Empty:
            continue
        seen.append(item)
        if predicate(item):
            return item, seen
    raise TimeoutError(f"Expected topology event was not observed; received {seen!r}")


def run(require_protected: bool) -> dict[str, Any]:
    ctx = mp.get_context("spawn")
    events = ctx.Queue()
    ports = {"b": free_port(), "c": free_port(), "d": free_port()}
    identities = {name: RNS.Identity() for name in "ABCD"}
    settings = {
        "D": NetworkSettings(
            nearby_discovery=False,
            tcp_listener={"host": "127.0.0.1", "port": ports["d"]},
        ),
        "C": NetworkSettings(
            nearby_discovery=False,
            help_route=True,
            tcp_listener={"host": "127.0.0.1", "port": ports["c"]},
            tcp_clients=[{"type": "tcp", "host": "127.0.0.1", "port": ports["d"]}],
        ),
        "B": NetworkSettings(
            nearby_discovery=False,
            help_route=True,
            tcp_listener={"host": "127.0.0.1", "port": ports["b"]},
            tcp_clients=[{"type": "tcp", "host": "127.0.0.1", "port": ports["c"]}],
        ),
        "A": NetworkSettings(
            nearby_discovery=False,
            tcp_clients=[{"type": "tcp", "host": "127.0.0.1", "port": ports["b"]}],
        ),
    }
    marker = f"mesh-three-hop-{os.urandom(8).hex()}"
    with tempfile.TemporaryDirectory(prefix="mesh-chat-topology-") as temporary:
        root = Path(temporary)
        if require_protected:
            protect_workspace(root)
        commands: dict[str, mp.Queue] = {}
        processes: dict[str, mp.Process] = {}
        try:
            for name in "DCBA":
                peer_root = root / name
                if require_protected:
                    protect_workspace(peer_root)
                commands[name] = ctx.Queue()
                process = ctx.Process(
                    target=peer,
                    args=(
                        name,
                        str(peer_root),
                        identities[name].get_private_key(),
                        settings[name].to_dict(),
                        commands[name],
                        events,
                    ),
                    name=f"mesh-peer-{name}",
                )
                process.start()
                processes[name] = process
                wait_for(events, lambda item, n=name: item.get("peer") == n and item.get("event") == "ready", 20)
                time.sleep(0.5)

            # Re-announce only after the full chain exists so A learns D's ratchet.
            for _ in range(3):
                commands["D"].put({"action": "announce"})
                time.sleep(1.5)
            d_destination = RNS.Destination.hash(identities["D"], "lxmf", "delivery")
            commands["A"].put(
                {
                    "action": "send",
                    "destination": d_destination.hex(),
                    "public_identity": base64.b64encode(
                        identities["D"].get_public_key()
                    ).decode("ascii"),
                    "text": marker,
                    "timeout": 45,
                }
            )
            route, route_events = wait_for(
                events,
                lambda item: item.get("peer") == "A" and item.get("event") == "route",
                50,
            )
            inbound, inbound_events = wait_for(
                events,
                lambda item: item.get("peer") == "D"
                and item.get("event") == "inbound"
                and item.get("text") == marker,
                50,
            )
        finally:
            for name, command_queue in commands.items():
                if processes.get(name) and processes[name].is_alive():
                    command_queue.put({"action": "stop"})
            for process in processes.values():
                process.join(timeout=10)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)

        leaked_to_intermediate = []
        marker_bytes = marker.encode("utf-8")
        for name in ("B", "C"):
            for path in (root / name).rglob("*"):
                if path.is_file():
                    try:
                        if marker_bytes in path.read_bytes():
                            leaked_to_intermediate.append(str(path.relative_to(root)))
                    except OSError:
                        pass
        return {
            "topology": "A->B->C->D",
            "route_ready": route["ready"],
            "reported_hops": route["hops"],
            "recipient_ratchet": bool(route["ratchet"]),
            "signature_validated": inbound["signature_validated"],
            "intermediate_plaintext_files": leaked_to_intermediate,
            "protected_workspace": require_protected,
            "events": route_events + inbound_events,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-protected-storage", action="store_true")
    args = parser.parse_args()
    result = run(args.require_protected_storage)
    print(json.dumps(result, indent=2))
    success = (
        result["route_ready"]
        and result["reported_hops"] == 3
        and result["recipient_ratchet"]
        and result["signature_validated"]
        and not result["intermediate_plaintext_files"]
    )
    return 0 if success else 1


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())

