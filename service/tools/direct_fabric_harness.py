"""Two isolated real services using the private packet adapter.

Local source mode uses bounded inherited queues to qualify RNS integration.
CI native mode replaces ONLY the packet carrier with a two-peer QUIC process.
Neither mode opens a local control listener or changes shipping settings.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
from functools import partial
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

from mesh_chat.direct_binding import BindingAuthority, create_binding
from mesh_chat.direct_offer import OfferAuthority, create_offer
from mesh_chat.direct_exchange import create_answer, create_ready
from mesh_chat.reticulum_config import NetworkSettings
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore
from mesh_chat.workspace_protocol import _destination_for, _identity_from_public_key, find_device, verify_workspace_invitation, workspace_document_digest
from tools.direct_lan_harness import _call, _receive
from tools.remote_access_harness import _framed, _wait
from tools.direct_packet_adapter import MeshDirectInterface, ProfileBudget, scoped_message_allowed
from tools.direct_packet_policy import PacketPolicy


def _worker(name, root, commands, responses, incoming, outgoing, revoked, carrier_lost, vault_key):
    store = VaultStore(Path(root), vault_key, allow_unprotected_for_tests=True)
    store.put("settings", "network", NetworkSettings(nearby_discovery=False, lan_fallback=False).to_dict())
    service = MeshChatService(store, Path(root), lambda _: None)
    interface = None
    stop = threading.Event()
    session = object()
    authorized = False
    authorization_check = None
    runtime_lease = None
    pending = True
    peer_destination = None
    authorized_workspace = None
    lease_deadline = 0
    thread = None
    budget = ProfileBudget()
    try:
        profile = service._require_profile() if store.get("profile", "local") else service.create_profile(name)
        network = service.network
        def scoped_inbound(message):
            if scoped_message_allowed(message, peer_destination, authorized_workspace, pending=pending):
                network._on_inbound(message)
        network.router.register_delivery_callback(scoped_inbound)
        interface = MeshDirectInterface(RNS.Transport, budget=budget)
        network.reticulum._add_interface(interface, mode=interface.MODE_POINT_TO_POINT)

        def pump(interface, session):
            next_authority_check = 0
            while not stop.is_set():
                if carrier_lost.is_set():
                    interface.engine_lost(session)
                    return
                if interface.online and time.monotonic() >= next_authority_check:
                    if runtime_lease is not None and not runtime_lease.check():
                        interface.engine_lost(session)
                        revoked.set()
                        return
                    next_authority_check = time.monotonic() + 0.25
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
                if action == "prepare_direct_invitation":
                    result = service._prepare_direct_invitation(request["invitation_id"], request["expires_at"])
                elif action == "framed_command":
                    value, should_stop = service.dispatch({"v": 1, "id": request["request_id"],
                        "command": request["service_command"], "payload": request["payload"]})
                    if should_stop or not value.get("ok"):
                        raise RuntimeError(value)
                    result = {"result": value["result"]}
                elif action in {"sign_binding", "verify_binding", "sign_ready", "verify_ready"}:
                    authority = BindingAuthority(
                        base64.urlsafe_b64decode(request["issuer"]), bytes.fromhex(request["audience"]),
                        request["scope"], request["expires_at"], bytes.fromhex(request["challenge"]))
                    def load_authority():
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
                        return authority
                    load_authority()
                    cert = bytes.fromhex(request["certificate"])
                    now = int(time.time())
                    if action in {"sign_binding", "sign_ready"}:
                        raw = create_binding(network.identity, authority, cert,
                            session_id=request["session_id"], challenge=authority.challenge, generation=request["generation"],
                            candidates=[{"host": "8.8.8.8", "port": 12345, "expires_at": authority.expires_at}],
                            issued_at=now, expires_at=authority.expires_at)
                        result = {"binding": raw}
                        if action == "sign_ready":
                            result["ready"] = create_ready(network.identity, raw, request["answer"])
                            service._save_direct_owner_ready(request["invitation_id"], result["ready"], cert)
                        elif authority.scope["kind"] == "invitation":
                            if service._require_workspace(request["workspace_id"])["state"] == "active":
                                fields = json.loads(raw)
                                offer = create_offer(network.identity, OfferAuthority(
                                    authority.issuer_public_identity, authority.scope, authority.expires_at, authority.challenge),
                                    cert, session_id=fields["session_id"], generation=fields["generation"],
                                    candidates=fields["candidates"], issued_at=fields["issued_at"], expires_at=fields["expires_at"])
                                service._save_direct_offer(request["invitation_id"], offer, cert)
                                result["offer"] = offer
                            else:
                                result["answer"] = create_answer(network.identity, raw, request["offer"])
                                offered = json.loads(request["offer"])
                                service._save_direct_join_answer(request["workspace_id"], request["offer"],
                                    bytes.fromhex(request["offer_certificate"]), result["answer"], cert,
                                    BindingAuthority(bytes.fromhex(offered["issuer_public_identity"]), network.destination_hash,
                                        authority.scope, authority.expires_at, authority.challenge))
                    else:
                        if authority.audience_destination != network.destination_hash:
                            raise ValueError("Wrong local audience")
                        # Recheck local workspace membership and persist the
                        # exact relationship generation under one vault transaction.
                        # Pending authority is reloaded from durable service records.
                        if action == "verify_ready":
                            check = partial(service._accept_direct_ready, request["workspace_id"], request["ready"], cert)
                        elif authority.scope["kind"] == "workspace":
                            check = partial(service._accept_direct_workspace_binding, request["binding"], authority, cert)
                        elif service._require_workspace(request["workspace_id"])["state"] == "joining":
                            check = partial(service._accept_direct_join_binding, request["workspace_id"], request["binding"], authority, cert)
                        else:
                            check = partial(service._accept_direct_answer, request["invitation_id"], request["answer"], authority, cert)
                        if interface.online:
                            raise ValueError("Retire the active path before replacing authorization")
                        if authority.scope["kind"] == "workspace":
                            runtime_lease = service._track_direct_workspace_session(request["binding"], authority, cert)
                        else:
                            check()
                        authorization_check = check
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
                    authorization_check = None
                    if runtime_lease is not None:
                        runtime_lease.cancel()
                    runtime_lease = None
                    revoked.clear()
                    carrier_lost.clear()
                    session = object()
                    interface = MeshDirectInterface(RNS.Transport, budget=budget)
                    network.reticulum._add_interface(interface, mode=interface.MODE_POINT_TO_POINT)
                    thread = threading.Thread(target=pump, args=(interface, session), daemon=True)
                    thread.start()
                elif action == "activate":
                    if not authorized or authorization_check is None:
                        raise ValueError("No verified peer binding")
                    with service._dispatch_lock:
                        try:
                            authorization_check()
                            if runtime_lease is not None and not runtime_lease.check():
                                raise ValueError("Direct runtime lease is retired")
                        except Exception:
                            authorized = False
                            authorization_check = None
                            interface.engine_lost(session)
                            raise
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
    def __init__(self, peers, executable=None, *, generation=1, expires_at):
        self.peers = peers
        self.stop = threading.Event()
        self.cancellation_requested = threading.Event()
        self.controls = queue.Queue(maxsize=8)
        self.lock = threading.Lock()
        self.process = None
        self.threads = []
        self.session_ids = [uuid.uuid4(), uuid.uuid4()]
        self.generation = generation
        self._refreshed_answer = None
        self._started = False
        remaining = min(240, int(expires_at - time.time()))
        if remaining <= 0:
            raise ValueError("Native session authorization has expired")
        if executable:
            self.process = subprocess.Popen([str(executable)], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self._thread(self._read)
            try:
                self._write(2, b"".join(session.bytes + struct.pack("!Q", generation) for session in self.session_ids)
                            + struct.pack("!I", remaining))
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
            self._mark_lost()

    def _mark_lost(self):
        # Lifecycle delivery must not compete with bounded packet capacity.
        self.stop.set()
        for peer in self.peers:
            peer["carrier_lost"].set()

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
                    self._mark_lost()
                    return
            else:
                try:
                    self.peers[1 - index]["incoming"].put_nowait(packet)
                except queue.Full:
                    pass

    def _watch_authority_owner(self):
        # A separate event cannot be dropped behind a full packet queue.
        while not self.stop.wait(0.05):
            if any(peer["revoked"].is_set()
                   or (peer.get("process") is not None and not peer["process"].is_alive())
                   for peer in self.peers):
                self.cancellation_requested.set()
                try:
                    if self.process:
                        self._write(2, b"cancel")
                except (OSError, ValueError):
                    pass  # Process loss is also terminal; close validates exit.
                finally:
                    self._mark_lost()
                return

    def refresh_owner(self, answer):
        if self._started or self.stop.is_set() or self._refreshed_answer is not None:
            raise ValueError("Owner refresh requires one pending owned attempt")
        digest = hashlib.sha256(answer.encode("utf-8")).digest()
        self.session_ids[0] = uuid.uuid4()
        if self.process:
            self._write(2, b"R" + self.session_ids[0].bytes + struct.pack("!Q", self.generation + 1) + digest)
            side, certificate = self.controls.get(timeout=15)
            if side != 3:
                raise RuntimeError("Native owner refresh did not provide its certificate")
            self.certificates[0] = certificate
        else:
            self.certificates[0] = os.urandom(64)
        self._refreshed_answer = digest
        return self.generation + 1

    def start(self, documents, *, ready_generation=None):
        if self._started or self.stop.is_set():
            raise ValueError("Carrier activation is terminal or already consumed")
        if len(documents) != 2:
            raise ValueError("Expected two authorized local session documents")
        digests = b"".join(hashlib.sha256(document.encode("utf-8")).digest() for document in documents)
        if self._refreshed_answer is not None:
            if ready_generation != self.generation + 1 or digests[32:] != self._refreshed_answer:
                raise ValueError("Ready must retain the exact owned Answer and fresh owner generation")
            digests += struct.pack("!Q", ready_generation)
        elif ready_generation is not None:
            raise ValueError("Ready requires refreshed owner credentials")
        self._started = True
        if self.process:
            self._write(2, digests)
            if self.controls.get(timeout=15) != (2, b"ready"):
                raise RuntimeError("Native peers did not authenticate")
        for index in range(2):
            self._thread(self._forward, index)
        self._thread(self._watch_authority_owner)

    def close(self, *, require_graceful=False):
        self._mark_lost()
        forced = False
        if self.process and self.process.poll() is None:
            try:
                self._write(2, b"cancel")
                self.process.wait(timeout=5)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                if self.process.poll() is None:
                    forced = True
                    self.process.terminate()
                    self.process.wait(timeout=5)
        for thread in self.threads:
            thread.join(timeout=2)
        if self.process:
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                try:
                    stream.close()
                except OSError:
                    # Windows can fail the buffered stdin flush after a killed
                    # reader exits. Still close the other handles; a nonzero
                    # process exit remains a failure for graceful qualification.
                    if self.process.poll() is None:
                        raise
        if require_graceful and self.process and (forced or self.process.returncode != 0):
            raise RuntimeError("Native bridge did not shut down gracefully")


def run(*, executable=None, timeout=45, failure="revocation"):
    if failure not in {"revocation", "service-crash", "engine-crash", "suspend-resume", "restart"}:
        raise ValueError("Unknown topology failure scenario")
    if failure == "engine-crash" and executable is None:
        raise ValueError("Native engine crash requires a native carrier")
    context = mp.get_context("spawn")
    peers = []
    carrier = None
    with tempfile.TemporaryDirectory(prefix="mesh-direct-fabric-") as root:
        try:
            for name in ("Owner", "Joiner"):
                commands, responses = context.Queue(), context.Queue()
                incoming, outgoing = context.Queue(maxsize=128), context.Queue(maxsize=128)
                revoked, carrier_lost = context.Event(), context.Event()
                vault_key = os.urandom(32)  # Python-only test custodian; never sent to Rust.
                process = context.Process(target=_worker, args=(name, str(Path(root) / name),
                    commands, responses, incoming, outgoing, revoked, carrier_lost, vault_key))
                process.start()
                peer = dict(commands=commands, responses=responses, process=process,
                            incoming=incoming, outgoing=outgoing, revoked=revoked, carrier_lost=carrier_lost,
                            vault_key=vault_key, root=str(Path(root) / name), name=name)
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
            negotiation = _call(owner["commands"], owner["responses"], "prepare_direct_invitation",
                                invitation_id=invitation["id"], expires_at=int(time.time()) + 240)
            expiry, challenge = negotiation["expires_at"], negotiation["challenge"]
            carrier = PacketCarrier(peers, executable, expires_at=expiry)
            def authorize(scopes, generation):
                offer = None
                documents = []
                if generation != carrier.generation:
                    raise ValueError("Native session generation mismatch")
                for index, peer in enumerate(peers):
                    other = peers[1 - index]
                    arguments = dict(issuer=peer["profile"]["public_identity"],
                        audience=other["profile"]["destination_hash"], scope=scopes[index], expires_at=expiry,
                        challenge=challenge, certificate=carrier.certificates[index].hex(), generation=generation,
                        workspace_id=workspace["id"], invitation_id=invitation["id"], offer=offer,
                        offer_certificate=carrier.certificates[0].hex(),
                        session_id=str(carrier.session_ids[index]))
                    signed = _call(peer["commands"], peer["responses"], "sign_binding", **arguments)
                    offer = signed.get("offer", offer)
                    _call(other["commands"], other["responses"], "verify_binding", **arguments,
                          binding=signed["binding"], answer=signed.get("answer"))
                    documents.append(signed.get("answer", signed.get("offer", signed["binding"])))
                ready_generation = None
                if scopes[0]["kind"] == "invitation":
                    old_owner_certificate = carrier.certificates[0]
                    answer_certificate, answer_session = carrier.certificates[1], carrier.session_ids[1]
                    ready_generation = carrier.refresh_owner(documents[1])
                    if (carrier.certificates[0] == old_owner_certificate
                            or carrier.certificates[1] != answer_certificate or carrier.session_ids[1] != answer_session):
                        raise AssertionError("Ready did not retain Answer ownership and rotate owner credentials")
                    arguments = dict(issuer=owner["profile"]["public_identity"],
                        audience=joiner["profile"]["destination_hash"], scope=scopes[0], expires_at=expiry,
                        challenge=challenge, certificate=carrier.certificates[0].hex(), generation=ready_generation,
                        workspace_id=workspace["id"], invitation_id=invitation["id"], answer=documents[1],
                        session_id=str(carrier.session_ids[0]))
                    signed = _call(owner["commands"], owner["responses"], "sign_ready", **arguments)
                    _call(joiner["commands"], joiner["responses"], "verify_ready", **arguments, ready=signed["ready"])
                    documents[0] = signed["ready"]
                carrier.start(documents, ready_generation=ready_generation)
                for peer in peers:
                    _call(peer["commands"], peer["responses"], "activate")
            _framed(joiner, "submit_workspace_join", {"invitation": invitation["text"], "operation_id": op()})
            authorize([scope, scope], 1)
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
            # Durable pending acceptance cannot be reused after admission.
            # Exercise the same activation command, without replacing its cache.
            for index, peer in enumerate(peers):
                peer["commands"].put({"action": "activate"})
                rejected = peer["responses"].get(timeout=5)
                if (rejected.get("action") != "activate" or rejected.get("ok")
                        or not rejected.get("error", "").startswith("ValidationError:")):
                    raise AssertionError("Retired invitation authorization was not rejected")
                state = _call(peer["commands"], peer["responses"], "state",
                              peer=peers[1-index]["profile"]["destination_hash"])
                if state["online"]:
                    raise AssertionError("Rejected activation left pending adapter online")
            # Retire invitation credentials. A second native carrier generates
            # fresh TLS keys; both services bind them to exact admitted devices.
            carrier.close(require_graceful=True)
            carrier = None
            workspaces = [next(item for item in _framed(peer, "workspace_snapshot", {})["workspaces"]
                               if item["id"] == workspace["id"]) for peer in peers]
            for peer in peers:
                _call(peer["commands"], peer["responses"], "reset")
            carrier = PacketCarrier(peers, executable, generation=2, expires_at=expiry)
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
            if failure == "revocation":
                _framed(owner, "remove_workspace_member", {"workspace_id": workspace["id"],
                    "member_id": workspaces[1]["local_member_id"], "operation_id": op()})
                deadline = time.monotonic() + 5
                while _call(owner["commands"], owner["responses"], "state",
                            peer=joiner["profile"]["destination_hash"])["online"]:
                    if time.monotonic() > deadline:
                        raise TimeoutError("Revoked peer adapter remained online")
                    time.sleep(0.05)
            elif failure in {"suspend-resume", "restart"}:
                _framed(owner, "mobile_lifecycle_transition", {"state": "suspended", "reason": "direct_proof"})
            elif failure == "service-crash":
                owner["process"].kill()
                owner["process"].join(timeout=5)
                if owner["process"].is_alive():
                    raise AssertionError("Fault injection did not stop the owner service")
            else:
                carrier.process.kill()
                carrier.process.wait(timeout=5)
                if carrier.process.returncode == 0:
                    raise AssertionError("Fault injection did not crash the native engine")
            # No explicit close or activation request triggers retirement.
            if failure != "engine-crash":
                if not carrier.cancellation_requested.wait(timeout=5):
                    raise AssertionError("Authority loss did not request carrier cancellation")
                if carrier.process and carrier.process.wait(timeout=5) != 0:
                    raise AssertionError("Orphaned native carrier did not exit gracefully")
            if not carrier.stop.wait(timeout=5):
                raise AssertionError("Failed carrier did not signal loss")
            for index, peer in enumerate(peers):
                if not peer["process"].is_alive():
                    if failure == "service-crash" and peer is owner:
                        continue
                    raise AssertionError("A surviving service unexpectedly stopped")
                deadline = time.monotonic() + 5
                while True:
                    state = _call(peer["commands"], peer["responses"], "state",
                                  peer=peers[1-index]["profile"]["destination_hash"])
                    if not state["online"]:
                        break
                    if time.monotonic() > deadline:
                        raise TimeoutError("Dead carrier remained online")
                    time.sleep(0.05)
            old_certificates, old_sessions = list(carrier.certificates), list(carrier.session_ids)
            carrier.close(require_graceful=failure != "engine-crash")
            carrier = None
            if failure in {"suspend-resume", "restart"}:
                queued = _framed(owner, "send_workspace_message", {"workspace_id": workspace["id"],
                    "channel_id": workspace["general_channel_id"], "text": "Queued during direct suspension",
                    "event_id": op(), "operation_id": op()})
                page = _framed(joiner, "list_workspace_messages", {"workspace_id": workspace["id"],
                    "channel_id": workspace["general_channel_id"], "limit": 50})
                if any(item["id"] == queued["id"] for item in page["messages"]):
                    raise AssertionError("Suspended carrier delivered a new message")
                if failure == "restart":
                    original_profile = dict(owner["profile"])
                    owner["process"].kill()
                    owner["process"].join(timeout=5)
                    if owner["process"].is_alive():
                        raise AssertionError("Restart fault did not stop the service")
                    # A killed Queue producer can leave partial frames. The new
                    # process receives fresh channels and cancellation events.
                    for key in ("commands", "responses", "incoming", "outgoing"):
                        owner[key].cancel_join_thread()
                        owner[key].close()
                        owner[key] = context.Queue(maxsize=128) if key in {"incoming", "outgoing"} else context.Queue()
                    owner["revoked"], owner["carrier_lost"] = context.Event(), context.Event()
                    owner["process"] = context.Process(target=_worker, args=(owner["name"], owner["root"],
                        owner["commands"], owner["responses"], owner["incoming"], owner["outgoing"],
                        owner["revoked"], owner["carrier_lost"], owner["vault_key"]))
                    owner["process"].start()
                    owner["profile"] = _receive(owner["responses"], "ready", 30)["profile"]
                    if any(owner["profile"][field] != original_profile[field]
                           for field in ("public_identity", "destination_hash")):
                        raise AssertionError("Restart replaced the durable identity")
                _framed(owner, "mobile_lifecycle_transition", {"state": "foreground", "reason": "direct_proof"})
                # Foreground reconciliation must not revive a retired lease.
                owner["commands"].put({"action": "activate"})
                rejected = owner["responses"].get(timeout=5)
                if rejected.get("action") != "activate" or rejected.get("ok"):
                    raise AssertionError("Resume reused a retired direct session")
                for peer in peers:
                    if failure != "restart" or peer is not owner:
                        _call(peer["commands"], peer["responses"], "reset")
                carrier = PacketCarrier(peers, executable, generation=3, expires_at=expiry)
                if (any(old == new for old, new in zip(old_certificates, carrier.certificates))
                        or any(old == new for old, new in zip(old_sessions, carrier.session_ids))):
                    raise AssertionError("Resume did not create fresh native credentials")
                challenge = os.urandom(32).hex()
                authorize([{"kind": "workspace", "workspace_id": workspace["id"],
                            "issuer_device_id": workspaces[index]["local_device_id"],
                            "audience_device_id": workspaces[1-index]["local_device_id"]}
                           for index in range(2)], 3)
                page = _wait(joiner, "list_workspace_messages", {"workspace_id": workspace["id"],
                    "channel_id": workspace["general_channel_id"], "limit": 50}, lambda page:
                    page if any(item["id"] == queued["id"] for item in page["messages"]) else None,
                    "queued message after fresh direct resume", timeout)
                if sum(item["id"] == queued["id"] for item in page["messages"]) != 1:
                    raise AssertionError("Resume duplicated the logical message")
                _wait(owner, "list_workspace_messages", {"workspace_id": workspace["id"],
                    "channel_id": workspace["general_channel_id"], "limit": 50}, lambda page: next((
                        item for item in page["messages"] if item["id"] == queued["id"]
                        and item.get("delivery_summary", {}).get("devices_reached") == 1), None),
                    "resumed message endpoint receipt", timeout)
                for index, peer in enumerate(peers):
                    resumed = next(item for item in _framed(peer, "workspace_snapshot", {})["workspaces"]
                                   if item["id"] == workspace["id"])
                    if (resumed["state"] != "active"
                            or resumed["local_device_id"] != workspaces[index]["local_device_id"]
                            or resumed["local_member_id"] != workspaces[index]["local_member_id"]):
                        raise AssertionError("Resume changed admitted identity")
                carrier.close(require_graceful=True)
                carrier = None
            return {"carrier": "quic" if executable else "source-pipes", "failure": failure,
                    "failure_retired_adapters": True, "join_acknowledged": True,
                    "admitted": True, "bidirectional_messages": True, "ratchets": True,
                    "engine_death_offline": failure == "engine-crash",
                    "service_crash_cancels_carrier": failure == "service-crash",
                    "suspension_recovered": failure == "suspend-resume",
                    "restart_recovered": failure == "restart",
                    "isolated": True, "admitted_key_rotation": True, "endpoint_receipts": True,
                    "stale_activation_rejected": True, "live_revocation_offline": failure == "revocation",
                    "revocation_cancels_carrier": failure == "revocation", "ready_retains_answer": True}
        finally:
            if carrier:
                carrier.close()
            for peer in peers:
                try:
                    if peer["process"].is_alive():
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
