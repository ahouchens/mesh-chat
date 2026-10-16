"""Two isolated real services using the private packet adapter.

Local source mode uses bounded inherited queues to qualify RNS integration.
CI native mode replaces ONLY the packet carrier with a two-peer QUIC process.
Neither mode opens a local control listener or changes shipping settings.
"""
from __future__ import annotations

import argparse
import base64
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue
import struct
import subprocess
import tempfile
import threading
import time
import uuid

import RNS

from mesh_chat.direct_binding import AcceptedBinding, BindingAuthority, create_binding, verify_binding
from mesh_chat.reticulum_config import NetworkSettings
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore
from mesh_chat.workspace_protocol import _destination_for, _identity_from_public_key, find_device, verify_workspace_invitation, workspace_document_digest
from tools.direct_lan_harness import _call, _receive
from tools.remote_access_harness import _framed, _wait
from tools.direct_packet_adapter import MeshDirectInterface, ProfileBudget, scoped_message_allowed
from tools.direct_packet_policy import PacketPolicy


def _worker(name, root, commands, responses, incoming, outgoing):
    store = VaultStore(Path(root), os.urandom(32), allow_unprotected_for_tests=True)
    store.put("settings", "network", NetworkSettings(nearby_discovery=False, lan_fallback=False).to_dict())
    service = MeshChatService(store, Path(root), lambda _: None)
    interface = None
    stop = threading.Event()
    session = object()
    authorized = False
    pending = True
    peer_destination = None
    authorized_workspace = None
    lease_deadline = 0
    thread = None
    budget = ProfileBudget()
    try:
        profile = service.create_profile(name)
        network = service.network
        def scoped_inbound(message):
            if scoped_message_allowed(message, peer_destination, authorized_workspace, pending=pending):
                network._on_inbound(message)
        network.router.register_delivery_callback(scoped_inbound)
        interface = MeshDirectInterface(RNS.Transport, budget=budget)
        network.reticulum._add_interface(interface, mode=interface.MODE_POINT_TO_POINT)

        def pump(interface, session):
            while not stop.is_set():
                try:
                    packet = incoming.get(timeout=0.01)
                    if packet is None:
                        interface.engine_lost(session)
                        return
                    interface.receive(session, packet)
                except queue.Empty:
                    pass
                while (packet := interface.take_outgoing(session)) is not None:
                    try:
                        outgoing.put_nowait(packet)
                    except queue.Full:
                        break  # Unreliable DATAGRAM semantics; RNS owns retries.

        thread = threading.Thread(target=pump, args=(interface, session), daemon=True)
        thread.start()
        responses.put({"ok": True, "action": "ready", "profile": profile})
        while True:
            request = commands.get()
            action = request["action"]
            try:
                result = {}
                if action == "stop":
                    responses.put({"ok": True, "action": action})
                    break
                if action == "framed_command":
                    value, should_stop = service.dispatch({"v": 1, "id": request["request_id"],
                        "command": request["service_command"], "payload": request["payload"]})
                    if should_stop or not value.get("ok"):
                        raise RuntimeError(value)
                    result = {"result": value["result"]}
                elif action in {"sign_binding", "verify_binding"}:
                    authority = BindingAuthority(
                        base64.urlsafe_b64decode(request["issuer"]), bytes.fromhex(request["audience"]),
                        request["scope"], request["expires_at"], bytes.fromhex(request["challenge"]))
                    if authority.scope["kind"] == "workspace":
                        workspace = service._require_workspace(authority.scope["workspace_id"])
                        if workspace["state"] != "active":
                            raise ValueError("Workspace is not active")
                        manifest = service._workspace_current_manifest(workspace)
                        issuer = find_device(manifest, authority.scope["issuer_device_id"])
                        audience = find_device(manifest, authority.scope["audience_device_id"])
                        if (issuer is None or audience is None or issuer[0].status != "active"
                                or audience[0].status != "active"
                                or issuer[1].public_identity != authority.issuer_public_identity
                                or audience[1].destination_hash != authority.audience_destination):
                            raise ValueError("Binding does not match admitted devices")
                    cert = bytes.fromhex(request["certificate"])
                    now = int(time.time())
                    if action == "sign_binding":
                        raw = create_binding(network.identity, authority, cert,
                            session_id=str(uuid.uuid4()), challenge=authority.challenge, generation=request["generation"],
                            candidates=[{"host": "8.8.8.8", "port": 12345, "expires_at": authority.expires_at}],
                            issued_at=now, expires_at=authority.expires_at)
                        result = {"binding": raw}
                    else:
                        if authority.audience_destination != network.destination_hash:
                            raise ValueError("Wrong local audience")
                        previous = store.get("direct_proof", "accepted")
                        accepted = verify_binding(request["binding"], authority, cert, now=now,
                            previous=AcceptedBinding(**previous) if previous else None)
                        # Proof only: persist before activation. Shipping runtime
                        # still needs transactional scope/generation reconciliation.
                        store.put("direct_proof", "accepted", {
                            "generation": accepted.generation, "digest": accepted.digest})
                        authorized = True
                        pending = authority.scope["kind"] == "invitation"
                        peer_destination = _destination_for(_identity_from_public_key(authority.issuer_public_identity))
                        authorized_workspace = request["workspace_id"]
                        lease_deadline = time.monotonic() + max(0, authority.expires_at - time.time())
                elif action == "reset":
                    if interface.online:
                        raise ValueError("Old path must be closed before proof reset")
                    thread.join(timeout=2)
                    if thread.is_alive():
                        raise RuntimeError("Old packet pump did not stop")
                    RNS.Transport.interfaces.remove(interface)
                    for link in list(RNS.Transport.active_links) + list(RNS.Transport.pending_links):
                        link.teardown()
                    for packets in (incoming, outgoing):
                        while True:
                            try:
                                packets.get_nowait()
                            except queue.Empty:
                                break
                    authorized = False
                    session = object()
                    interface = MeshDirectInterface(RNS.Transport, budget=budget)
                    network.reticulum._add_interface(interface, mode=interface.MODE_POINT_TO_POINT)
                    thread = threading.Thread(target=pump, args=(interface, session), daemon=True)
                    thread.start()
                elif action == "activate":
                    if not authorized:
                        raise ValueError("No verified peer binding")
                    interface.packet_policy = PacketPolicy(network.destination_hash, peer_destination)
                    interface.activate(session, expires_at=lease_deadline, pending=pending)
                    network.interface_start_failed = False
                    network.router.announce(network.destination_hash)
                elif action == "state":
                    result = {"online": interface.check_health(), "received_bytes": interface.rxb,
                        "sent_bytes": interface.txb, "interfaces": len(RNS.Transport.interfaces),
                        "routing": RNS.Reticulum.transport_enabled(),
                        "ratchet_ready": network.recipient_ready(bytes.fromhex(request["peer"]))}
                else:
                    raise ValueError("Unknown proof action")
                responses.put({"ok": True, "action": action, **result})
            except Exception as exc:
                responses.put({"ok": False, "action": action, "error": f"{type(exc).__name__}: {exc}"})
    except Exception as exc:
        responses.put({"ok": False, "action": "ready", "error": f"{type(exc).__name__}: {exc}"})
    finally:
        stop.set()
        if interface:
            interface.detach()
        if thread:
            thread.join(timeout=2)
        service.close()


class PacketCarrier:
    def __init__(self, peers, executable=None):
        self.peers = peers
        self.stop = threading.Event()
        self.controls = queue.Queue(maxsize=8)
        self.lock = threading.Lock()
        self.process = None
        self.threads = []
        if executable:
            self.process = subprocess.Popen([str(executable)], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self._thread(self._read)
            try:
                first, second = self.controls.get(timeout=20), self.controls.get(timeout=20)
                if first[0] != 3 or second[0] != 4:
                    raise RuntimeError("Native proof did not provide certificates")
                self.certificates = [first[1], second[1]]
            except Exception:
                self.close()
                raise
        else:
            self.certificates = [os.urandom(64), os.urandom(64)]

    def _thread(self, target, *args):
        thread = threading.Thread(target=target, args=args, daemon=True)
        thread.start()
        self.threads.append(thread)

    def _write(self, peer, packet):
        with self.lock:
            self.process.stdin.write(struct.pack("!BH", peer, len(packet)) + packet)
            self.process.stdin.flush()

    def _read(self):
        try:
            def exact(size):
                result = b""
                while len(result) < size:
                    part = self.process.stdout.read(size - len(result))
                    if not part:
                        raise EOFError("Native proof exited")
                    result += part
                return result
            while not self.stop.is_set():
                peer, size = struct.unpack("!BH", exact(3))
                if not 0 < size <= (516 if peer < 2 else 16384) or peer > 4:
                    raise ValueError("Invalid native proof frame")
                packet = exact(size)
                if peer < 2:
                    try:
                        self.peers[peer]["incoming"].put_nowait(packet)
                    except queue.Full:
                        pass
                else:
                    self.controls.put_nowait((peer, packet))
        except (EOFError, OSError, ValueError, queue.Full):
            self.stop.set()
            for peer in self.peers:
                try:
                    peer["incoming"].put(None, timeout=1)
                except queue.Full:
                    pass

    def _forward(self, index):
        while not self.stop.is_set():
            try:
                packet = self.peers[index]["outgoing"].get(timeout=0.1)
            except queue.Empty:
                continue
            if self.process:
                try:
                    self._write(index, packet)
                except (OSError, ValueError):
                    return
            else:
                try:
                    self.peers[1 - index]["incoming"].put_nowait(packet)
                except queue.Full:
                    pass

    def start(self):
        if self.process:
            self._write(2, b"authorized")
            if self.controls.get(timeout=15) != (2, b"ready"):
                raise RuntimeError("Native peers did not authenticate")
        for index in range(2):
            self._thread(self._forward, index)

    def close(self):
        self.stop.set()
        if self.process:
            self.process.terminate()
            self.process.wait(timeout=5)
        for peer in self.peers:
            try:
                peer["incoming"].put(None, timeout=1)
            except queue.Full:
                pass
        for thread in self.threads:
            thread.join(timeout=2)
        if self.process:
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                stream.close()


def run(*, executable=None, timeout=45):
    context = mp.get_context("spawn")
    peers = []
    carrier = None
    with tempfile.TemporaryDirectory(prefix="mesh-direct-fabric-") as root:
        try:
            for name in ("Owner", "Joiner"):
                commands, responses = context.Queue(), context.Queue()
                incoming, outgoing = context.Queue(maxsize=128), context.Queue(maxsize=128)
                process = context.Process(target=_worker, args=(name, str(Path(root) / name),
                    commands, responses, incoming, outgoing))
                process.start()
                peer = dict(commands=commands, responses=responses, process=process,
                            incoming=incoming, outgoing=outgoing)
                peers.append(peer)
                peer["profile"] = _receive(responses, "ready", 30)["profile"]
            owner, joiner = peers
            op = lambda: str(uuid.uuid4())
            workspace = _framed(owner, "create_workspace", {"name": "Direct proof",
                "description": "Private packet carrier", "operation_id": op()})
            invitation = _framed(owner, "create_workspace_invitation", {
                "workspace_id": workspace["id"], "operation_id": op()})
            verified = verify_workspace_invitation(invitation["text"])
            scope = {"kind": "invitation", "digest": workspace_document_digest(verified.serialized),
                     "expires_at": verified.expires_at}
            expiry, challenge = int(time.time()) + 240, os.urandom(32).hex()
            carrier = PacketCarrier(peers, executable)
            def authorize(scopes, generation):
                for index, peer in enumerate(peers):
                    other = peers[1 - index]
                    arguments = dict(issuer=peer["profile"]["public_identity"],
                        audience=other["profile"]["destination_hash"], scope=scopes[index], expires_at=expiry,
                        challenge=challenge, certificate=carrier.certificates[index].hex(), generation=generation,
                        workspace_id=workspace["id"])
                    signed = _call(peer["commands"], peer["responses"], "sign_binding", **arguments)
                    _call(other["commands"], other["responses"], "verify_binding", **arguments,
                          binding=signed["binding"])
                carrier.start()
                for peer in peers:
                    _call(peer["commands"], peer["responses"], "activate")
            authorize([scope, scope], 1)
            _framed(joiner, "submit_workspace_join", {"invitation": invitation["text"], "operation_id": op()})
            request = _wait(owner, "workspace_snapshot", {}, lambda snap: next((item
                for item in snap.get("workspace_join_requests", []) if item["state"] == "pending"), None),
                "direct join request", timeout)
            _wait(joiner, "workspace_snapshot", {}, lambda snap: next((item for item in snap["workspaces"]
                if item["state"] == "joining" and item.get("join_acknowledged")), None),
                "signed application receipt before approval", timeout)
            _framed(owner, "approve_workspace_join", {"workspace_id": workspace["id"],
                "request_id": request["id"], "operation_id": op()})
            _wait(joiner, "workspace_snapshot", {}, lambda snap: next((item for item in snap["workspaces"]
                if item["state"] == "active"), None), "workspace admission", timeout)
            _wait(joiner, "workspace_snapshot", {}, lambda snap: next((item
                for item in snap["workspace_channels"] if item["id"] == workspace["general_channel_id"]), None),
                "admitted general-channel bootstrap", timeout)
            # Retire invitation credentials. A second native carrier generates
            # fresh TLS keys; both services bind them to exact admitted devices.
            carrier.close()
            carrier = None
            workspaces = [next(item for item in _framed(peer, "workspace_snapshot", {})["workspaces"]
                               if item["id"] == workspace["id"]) for peer in peers]
            for peer in peers:
                _call(peer["commands"], peer["responses"], "reset")
            carrier = PacketCarrier(peers, executable)
            challenge = os.urandom(32).hex()
            authorize([{"kind": "workspace", "workspace_id": workspace["id"],
                        "issuer_device_id": workspaces[index]["local_device_id"],
                        "audience_device_id": workspaces[1-index]["local_device_id"]}
                       for index in range(2)], 2)
            for sender, recipient in ((owner, joiner), (joiner, owner)):
                sent = _framed(sender, "send_workspace_message", {"workspace_id": workspace["id"],
                    "channel_id": workspace["general_channel_id"], "text": "Real LXMF over direct packets",
                    "event_id": op(), "operation_id": op()})
                _wait(recipient, "list_workspace_messages", {"workspace_id": workspace["id"],
                    "channel_id": workspace["general_channel_id"], "limit": 50}, lambda page: next((
                        item for item in page["messages"] if item["id"] == sent["id"]), None),
                    "bidirectional workspace delivery", timeout)
                _wait(sender, "list_workspace_messages", {"workspace_id": workspace["id"],
                    "channel_id": workspace["general_channel_id"], "limit": 50}, lambda page: next((
                        item for item in page["messages"] if item["id"] == sent["id"]
                        and item.get("delivery_summary", {}).get("devices_reached") == 1), None),
                    "authenticated LXMF endpoint receipt", timeout)
            states = [_call(peer["commands"], peer["responses"], "state",
                peer=peers[1-index]["profile"]["destination_hash"]) for index, peer in enumerate(peers)]
            assert all(state["interfaces"] == 1 and not state["routing"] and state["online"]
                       and state["ratchet_ready"] and state["received_bytes"] > 0 for state in states)
            carrier.close()
            carrier = None
            for index, peer in enumerate(peers):
                deadline = time.monotonic() + 5
                while True:
                    state = _call(peer["commands"], peer["responses"], "state",
                                  peer=peers[1-index]["profile"]["destination_hash"])
                    if not state["online"]:
                        break
                    if time.monotonic() > deadline:
                        raise TimeoutError("Dead carrier remained online")
                    time.sleep(0.05)
            return {"carrier": "quic" if executable else "source-pipes", "join_acknowledged": True,
                    "admitted": True, "bidirectional_messages": True, "ratchets": True,
                    "engine_death_offline": True, "isolated": True, "admitted_key_rotation": True,
                    "endpoint_receipts": True}
        finally:
            if carrier:
                carrier.close()
            for peer in peers:
                try:
                    _call(peer["commands"], peer["responses"], "stop", response_timeout=5)
                except Exception:
                    pass
                peer["process"].join(timeout=5)
                if peer["process"].is_alive():
                    peer["process"].terminate()
                    peer["process"].join(timeout=5)
                for key in ("commands", "responses", "incoming", "outgoing"):
                    peer[key].cancel_join_thread()
                    peer[key].close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(run(executable=arguments.native)))
