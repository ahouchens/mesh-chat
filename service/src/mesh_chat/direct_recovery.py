"""Bounded, service-owned admitted relationship recovery and replacement.

No membership, message, or receipt is created here. Every startup allocates new
native ownership. Durable local/remote tuples are hints, never socket handles.
"""
import hashlib
import secrets
import threading
import time
import uuid

from . import connectivity as c
from .direct_binding import create_binding, _parse
from .direct_candidates import prepare_candidates
from .direct_admitted_carrier import AdmittedCarrier
from .direct_relationship import relationship_id, record_success
from . import direct_recovery_protocol as protocol
from .errors import ValidationError
from .invitations import canonical_bytes
from .workspace_protocol import _destination_for, _identity_from_public_key
from .workspace_wire import build_workspace_fields

MAX_ATTEMPTS = 4
MAX_ACTIVE = 4
CONTENDED_SLOT_SECONDS = 300


def retry_delay(attempt, jitter):
    return min(300, 2 ** min(8, max(1, attempt))) * (.75 + .5*jitter)


class DirectRecovery:
    def __init__(self, service, *, clock=time.time, jitter=None):
        self.service, self.clock = service, clock
        self.jitter = jitter or (lambda: secrets.randbelow(10001)/10000)
        self._lock = threading.RLock()
        self._wake, self._stop = threading.Event(), threading.Event()
        self._active, self._pending, self._prepared = {}, {}, {}
        self._waiting_hints = set()
        self._native_seen = {}
        self._workers = set()
        self._epoch, self._cursor = 0, 0
        self._initialized = False
        self._route_signature = None
        self._route = None
        self._route_check_at = 0
        self._thread = threading.Thread(target=self._run, daemon=True, name="mesh-direct-recovery")

    def start(self):
        self._thread.start()

    def _authority(self, record):
        expected = protocol.authority(record, now=int(self.clock()))
        self.service._check_direct_runtime_available()
        return self.service._direct_workspace_binding_authority(expected)

    def _state(self, identifier):
        return self.service.store.get("direct_recovery", identifier) or {
            "version":1, "enabled":True, "state":"reconnecting", "attempts":0, "next_at":0,
            "local":None, "generation":0,
        }

    def _write(self, identifier, **changes):
        def update(previous):
            value = previous or self._state(identifier)
            if value.get("version") != 1:
                raise ValidationError("Unsupported recovery state version")
            return {**value, **changes}
        result = self.service.store.update_record("direct_recovery", identifier, update)
        if "state" in changes:
            from .connection_diagnostics import record
            record(self.service, "state", {"setup_id":identifier, "kind":"recovery",
                "state":result["state"], "expires_at":(result.get("local") or {}).get("expires_at",0)})
        return result

    def adopt(self, expected, carrier):
        """Keep the Phase 2 path usable while negotiating durable recovery."""
        identifier = relationship_id(self.service.store, expected)
        with self._lock:
            old = self._active.get(identifier)
            if old is not None or len(self._active) < MAX_ACTIVE:
                carrier.slot_started_at = self.clock()
                self._active[identifier] = carrier
        if old is not None and old is not carrier: old.close()
        self._write(identifier, enabled=True, state="reconnecting", next_at=self.clock())
        self.service._direct_setup.relationship_ready(carrier,identifier)
        self._wake.set()

    def _valid(self, identifier, token):
        with self._lock:
            return not self._stop.is_set() and self._pending.get(identifier) == token and token[0] == self._epoch

    def _reserve(self, identifier, record):
        expected = self._authority(record)
        own = protocol.outgoing_authority(self.service, expected, now=int(self.clock()))
        outgoing_id = self.service.store.opaque_id("direct-outgoing", canonical_bytes(own.scope).decode())
        rk, ok = ("direct_recovery", identifier), ("direct_outgoing", outgoing_id)
        def update(records):
            self._authority(record)
            state = records[rk] or self._state(identifier)
            if state.get("version") != 1 or not state["enabled"]:
                raise ValidationError("Recovery was cancelled")
            previous = records[ok] or {}
            generation = max(state.get("generation",0), previous.get("generation",0))+1
            if generation >= 2**63:
                raise ValidationError("Direct generation exhausted")
            attempt = min(8, state["attempts"]+1)
            return {rk:{**state, "generation":generation, "attempts":attempt,
                        "next_at":self.clock()+retry_delay(attempt,self.jitter()), "state":"reconnecting"},
                    ok:{**previous,"generation":generation}}
        values = self.service.store.update_records((rk,ok),update)
        return expected, own, values[rk]["generation"]

    def _save_local(self, identifier, record, prepared, fields, cleanup, *, reserve=False, token=None):
        with self.service._dispatch_lock:
            if token is not None and not self._valid(identifier,token):
                raise ValidationError("Recovery callback was retired")
            expected = self._authority(record)
            if reserve:
                _, own, generation = self._reserve(identifier,record)
            else:
                own = protocol.outgoing_authority(self.service,expected,now=int(self.clock()))
                generation = fields["generation"]
            raw = create_binding(self.service._identity, own, fields["certificate"],
                session_id=fields["session_id"],generation=generation,challenge=own.challenge,
                candidates=fields["candidates"],issued_at=int(self.clock()),expires_at=fields["expires_at"],version=3)
            local = {"binding":raw,"certificate":fields["certificate"].hex(),
                     "document":protocol.encode(raw, fields["certificate"]),
                     "expires_at":fields["expires_at"], "cleanup":cleanup,
                     "socket_hint":{"host":prepared._owned["host"],"port":prepared._owned["port"]},
                     "logical_id":str(uuid.uuid4())}
            state = self._state(identifier)
            previous = state.get("local") or {}
            orphans = [item for item in state.get("orphan_cleanup",[]) if item["expires_at"] > self.clock()]
            for mapping in previous.get("cleanup",[]):
                if mapping not in cleanup:
                    item = {"mapping":mapping,"expires_at":previous.get("cleanup_expires_at",previous["expires_at"])}
                    if item["expires_at"] > self.clock() and item not in orphans: orphans.append(item)
            if len(orphans)>32:
                raise ValidationError("Outstanding router cleanup budget exhausted")
            local["cleanup_expires_at"] = int(self.clock())+max([0]+[m["lifetime"] for m in cleanup])
            self._write(identifier,local=local,orphan_cleanup=orphans)
            return local

    def _send(self, record, local):
        """Same logical control ID on retries; ordinary messages are untouched."""
        with self.service._dispatch_lock:
            self._authority(record)
            peer = _destination_for(_identity_from_public_key(bytes.fromhex(record["issuer"])))
            if not self.service.network.recipient_ready(peer):
                return False
            try:
                self.service.network.send_with_fields(logical_id=local["logical_id"],
                    recipient_public_key=bytes.fromhex(record["issuer"]), recipient_destination=peer, text="",
                    fields=build_workspace_fields(kind="workspace_connection_update",logical_id=local["logical_id"],
                        workspace_id=record["scope"]["workspace_id"],expires_at=local["expires_at"],document=local["document"]))
                return True
            except Exception:
                return False

    def receive(self, document, *, source=None, workspace_id=None):
        raw, certificate, binding = protocol.decode(document)
        record = {"scope":binding["scope"],"issuer":binding["issuer_public_identity"],
                  "audience":binding["audience_destination"]}
        expected = self._authority(record)
        identifier = relationship_id(self.service.store,expected)
        if self.service.store.get("direct_relationship",identifier) is None:
            raise ValidationError("No established direct relationship for this update")
        if source is not None and source != bytes.fromhex(binding["issuer_destination"]):
            raise ValidationError("Connection update source mismatch")
        if workspace_id is not None and workspace_id != expected.scope["workspace_id"]:
            raise ValidationError("Connection update workspace mismatch")
        before = self.service.store.get("direct_relationship",identifier)["accepted"]
        accepted = self.service._accept_direct_workspace_binding(raw,expected,certificate)
        with self._lock: current = self._active.get(identifier)
        if self._state(identifier)["enabled"] and before["digest"] != accepted.digest and not (current and not current._stop.is_set() and current.certificate == certificate):
            self._write(identifier,next_at=self.clock(),state="reconnecting")
        # A listener with no peer hint cannot discover a second listener. An
        # explicit signed update restarts only that pending attempt; it retains
        # the local port hint and always reauthenticates a fresh transport key.
        with self._lock:
            waiting = (self._state(identifier)["enabled"] and before["digest"] != accepted.digest
                       and (identifier in self._waiting_hints or
                            source is None and identifier in self._pending and
                            (current is None or current._stop.is_set())))
            if waiting:
                self._pending.pop(identifier,None)
                self._waiting_hints.discard(identifier)
                prepared = self._prepared.pop(identifier,None)
        if waiting and prepared is not None: prepared.close()
        self._wake.set()
        return {"relationship_id":identifier,"state":self._state(identifier)["state"]}

    def _attempt(self, identifier, record, token):
        prepared = admitted = None
        promoted = False
        stage = "reserve"
        try:
            with self.service._dispatch_lock:
                if not self._valid(identifier,token): return
                expected, own, generation = self._reserve(identifier,record)
                state = self._state(identifier)
                attempted_peer = state.get("attempted_peer")
                saved = state.get("local") or {}
                hint = saved.get("socket_hint") or {}
                with self._lock:
                    old = self._active.get(identifier)
                # A live old socket remains owned. Its replacement needs a new
                # socket; restart may request the old port as a hint only.
                port = 0 if old and not old._stop.is_set() else hint.get("port",0)
                cleanup = saved.get("cleanup") or []
            stage = "prepare"
            prepared = prepare_candidates(self.service._direct_native,generation=generation,
                expires_at=int(self.clock())+3600,recovery=True,preferred_port=port,
                preferred_host=hint.get("host"), route_offset=max(0,state["attempts"]-1),
                preferred_external_port=cleanup[0]["external_port"] if cleanup and not (old and not old._stop.is_set()) else 0)
            with self.service._dispatch_lock:
                if not self._valid(identifier,token): return
                fields = prepared.document_fields()
                local = self._save_local(identifier,record,prepared,fields,prepared.cleanup_records())
                with self._lock: self._prepared[identifier] = prepared
            stage = "update"
            self._send(record,local)
            # Wait for the peer's replacement, not just any saved v3 binding.
            # A live old endpoint is still occupied by its old connection and
            # cannot authenticate this new attempt. Keep that path for updates.
            end = time.monotonic()+15
            resend_at = time.monotonic()+2
            while True:
                with self.service._dispatch_lock:
                    self._authority(record)
                    remote = self.service.store.get("direct_relationship",identifier)
                    updated = (_parse(remote["binding"])["v"] == 3 and
                               (old is None or old._stop.is_set() or
                                remote["certificate"] != old.certificate.hex() and remote["accepted"]["digest"] != attempted_peer))
                    if updated or time.monotonic() >= end:
                        break
                if not self._valid(identifier,token): return
                if time.monotonic() >= resend_at:
                    self._send(record,local)
                    resend_at = time.monotonic()+2
                self._stop.wait(.1)
            candidates = remote["candidates"]
            with self._lock:
                if not candidates and self._pending.get(identifier) == token:
                    self._waiting_hints.add(identifier)
            # Previously authenticated numeric addresses remain bounded hints
            # even when their advertised lease expires. New TLS/RNS authority is
            # mandatory; no application data or plaintext document is sent there.
            ours = fields["candidates"]
            peer = _destination_for(_identity_from_public_key(expected.issuer_public_identity))
            client = not ours if bool(ours) != bool(candidates) else self.service.network.destination_hash < peer
            if client and not candidates:
                raise ValidationError("No known usable peer address")
            if not ours and not candidates:
                raise ValidationError("Both endpoint addresses are unknown")
            prepared.document_fields()
            raw = local["binding"]
            stage = "native_start"
            with self.service._dispatch_lock:
                if not self._valid(identifier,token): return
                self._write(identifier,attempted_peer=remote["accepted"]["digest"])
            self.service._direct_native.request("arm",id=prepared.handle,session=fields["session_id"],
                generation=generation,digest=hashlib.sha256(raw.encode()).hexdigest())
            self.service._direct_native.request("recover",id=prepared.handle,
                capsule=protocol.capsule(expected.issuer_public_identity,raw).hex(),
                candidates=[f"[{c['host']}]:{c['port']}" if ':' in c['host'] else f"{c['host']}:{c['port']}" for c in candidates],
                client=client,remaining_ms=60000,lifetime_ms=max(1,int((prepared.expires_at-self.clock())*1000)))
            stage = "native_wait"
            end, approved = time.monotonic()+72, False
            peer_raw = peer_cert = accepted = None
            while self._valid(identifier,token) and time.monotonic() < end:
                polled = self.service._direct_native.request("poll",id=prepared.handle)
                with self._lock: self._native_seen[identifier] = time.monotonic()
                if polled["state"] == 2:
                    raise ValidationError("Recovery path unavailable")
                if polled["state"] == 3 and not approved:
                    evidence = self.service._direct_native.request("recovery_evidence",id=prepared.handle)
                    if not evidence: continue
                    if set(evidence) != {"capsule","certificate","token"}:
                        raise ValidationError("Invalid native recovery evidence")
                    stage = "peer_authorization"
                    peer_raw = protocol.open_capsule(self.service._identity,bytes.fromhex(evidence["capsule"]))
                    peer_cert = bytes.fromhex(evidence["certificate"])
                    with self.service._dispatch_lock:
                        if not self._valid(identifier,token): return
                        expected = self._authority(record)
                        accepted = self.service._accept_direct_workspace_binding(peer_raw,expected,peer_cert)
                    self.service._direct_native.request("authorize_recovery",id=prepared.handle,token=evidence["token"])
                    approved = True
                if polled["state"] == 1:
                    if not approved:
                        raise ValidationError("Native recovery bypassed authorization")
                    stage = "rns_attach"
                    def check():
                        with self.service._dispatch_lock:
                            self._authority(record)
                    lease = self.service._direct_sessions.open(min(3600,prepared.expires_at-self.clock()),check,
                        key=("recovery",identifier,prepared.handle))
                    admitted = AdmittedCarrier(self.service,prepared,peer_raw,expected,peer_cert,None,
                        lambda _:self._wake.set(),initial_packets=polled["packets"],runtime_lease=lease)
                    admitted.start()
                    stage = "rns_confirmation"
                    deadline = time.monotonic()+12
                    while not admitted.peer_seen.is_set() and time.monotonic()<deadline and self._valid(identifier,token):
                        if admitted._stop.wait(.05): break
                    if not admitted.peer_seen.is_set() or admitted._stop.is_set():
                        raise ValidationError("Recovered RNS peer is not ready")
                    with self.service._dispatch_lock:
                        if not self._valid(identifier,token): return
                        self._authority(record)
                        stage = "winner_commit"
                        latest = self.service.store.get("direct_relationship",identifier)
                        if latest["accepted"]["digest"] != accepted.digest and latest["certificate"] == peer_cert.hex():
                            # Same-key lease updates may arrive during RNS setup.
                            # Reverify the newer signed generation against the
                            # actual authenticated leaf; never promote another key.
                            expected = self._authority(record)
                            accepted = self.service._accept_direct_workspace_binding(latest["binding"],expected,peer_cert)
                        record_success(self.service.store,expected,accepted,
                            load_authority=lambda:self._authority(record),clock=lambda:int(self.clock()))
                        self._write(identifier,state="connected",attempts=0,next_at=self.clock()+3000,
                                    winner=accepted.digest,renew_at=self.clock()+min(1800,max(1,(fields["expires_at"]-self.clock())/2)))
                        with self._lock:
                            old = self._active.get(identifier)
                            admitted.slot_started_at = getattr(old,"slot_started_at",self.clock())
                            admitted.route_signature = self._route_signature
                            self._active[identifier] = admitted
                        promoted = True
                    if old and old is not admitted:
                        old.close()
                        self.service._direct_setup.release_carrier(old)
                        admitted.refresh_path()
                    return
                self._stop.wait(.05)
            raise ValidationError("Recovery attempt was retired")
        except Exception as exc:
            if not self._stop.is_set():
                with self.service._dispatch_lock:
                    if self._valid(identifier,token):
                        state = self._state(identifier)
                        self._write(identifier,state="connection_update_needed" if state["attempts"] >= 6 or not record["candidates"] else "reconnecting",
                                    failure_stage=stage,failure_type=type(exc).__name__)
        finally:
            if admitted is not None and not promoted: admitted.close()
            elif prepared is not None and not promoted: prepared.close()
            with self._lock:
                if self._prepared.get(identifier) is prepared and not promoted:
                    self._prepared.pop(identifier,None)
                if self._pending.get(identifier) == token:
                    self._pending.pop(identifier,None)
                    self._waiting_hints.discard(identifier)
                self._workers.discard(threading.current_thread())
            self._wake.set()

    def _renew(self, identifier, record, carrier, token):
        prepared = carrier.prepared
        def persist(fields,cleanup):
            if not self._valid(identifier,token):
                raise ValidationError("Renewal was retired")
            local = self._save_local(identifier,record,prepared,fields,cleanup,reserve=True,token=token)
            self._send(record,local)
        try:
            prepared.renew(persist)
            with self.service._dispatch_lock:
                if not self._valid(identifier,token): return
                self._write(identifier,state="connected",attempts=0,next_at=min(prepared.expires_at-60,self.clock()+3000),renew_at=self.clock()+max(1,min(1800,
                    (prepared.document_fields()["expires_at"]-self.clock())/2)))
        except Exception:
            self._wake.set()
        finally:
            with self._lock:
                if self._pending.get(identifier) == token:
                    self._pending.pop(identifier,None)
                    self._waiting_hints.discard(identifier)
                self._workers.discard(threading.current_thread())

    def _migrate(self, identifier, record, carrier, route, token):
        def persist(fields,cleanup):
            if not self._valid(identifier,token): raise ValidationError("Migration retired")
            local=self._save_local(identifier,record,carrier.prepared,fields,cleanup,reserve=True,token=token)
            self._send(record,local)
        try:
            with self.service._dispatch_lock:
                self._authority(record)
                if not self._valid(identifier,token): return
                self._write(identifier,state="reconnecting")
            carrier.prepared.migrate(route,persist)
            carrier.route_signature = (route.interface,route.local_address,route.gateway)
            carrier.peer_seen.clear()
            carrier.peer_seen_at=0
            self.service.network.router.announce(self.service.network.destination_hash)
            end=time.monotonic()+15
            while self._valid(identifier,token) and time.monotonic()<end and not carrier.peer_seen.is_set():
                if carrier._stop.wait(.05): break
            with self.service._dispatch_lock:
                if self._valid(identifier,token):
                    recovered=carrier.peer_seen.is_set() and not carrier._stop.is_set()
                    self._write(identifier,state="connected" if recovered else "reconnecting",
                        next_at=min(carrier.prepared.expires_at-60,self.clock()+3000) if recovered else self.clock())
        except Exception:
            with self.service._dispatch_lock:
                if self._valid(identifier,token):
                    carrier.route_signature = (route.interface,route.local_address,route.gateway)
                    self._write(identifier,state="reconnecting",next_at=self.clock())
        finally:
            with self._lock:
                if self._pending.get(identifier)==token: self._pending.pop(identifier,None)
                self._workers.discard(threading.current_thread())

    def _run(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                pass  # Redacted state; one peer cannot kill upkeep for the profile.
            self._wake.wait(1)
            self._wake.clear()

    def tick(self):
        service = self.service
        if service._direct_native is None or service.network is None: return
        route=self._route
        if time.monotonic() >= self._route_check_at:
            routes=[r for r in c.default_routes() if r.local_address and c.classify_address(r.local_address)
                    in {"public_ipv4","public_ipv6","rfc1918","shared"}]
            routes.sort(key=lambda r:(c.classify_address(r.local_address)!="public_ipv6",r.metric))
            route=routes[0] if routes else None
            signature=None if route is None else (route.interface,route.local_address,route.gateway)
            self._route_signature=signature
            self._route=route
            self._route_check_at=time.monotonic()+5
        with service._dispatch_lock:
            service._check_direct_runtime_available()
            records = service.store.items("direct_relationship")
            if not self._initialized:
                for identifier,_ in records:
                    state = self._state(identifier)
                    # A planned refresh for a formerly live socket is not a
                    # reconnect backoff. Ownership vanished on restart/resume.
                    next_at = (self.clock()+2*self.jitter() if state["state"] == "connected"
                               else min(self.clock()+300,state["next_at"]))
                    self._write(identifier,state="reconnecting" if state["enabled"] else "dormant",next_at=next_at)
                self._initialized = True
            if not records: return
            # Under contention, five-minute service slots rotate among due peers.
            # A slot retirement is explicit dormancy, not successful replacement.
            with self._lock:
                occupied = set(self._active) | set(self._pending)
                waiting = any(key not in occupied and self._state(key)["enabled"]
                              and self._state(key)["next_at"] <= self.clock() for key,_ in records)
                retiring = [(key,carrier) for key,carrier in self._active.items()
                    if waiting and key not in self._pending
                    and self.clock()-getattr(carrier,"slot_started_at",self.clock()) >= CONTENDED_SLOT_SECONDS]
            for key,carrier in retiring[:1]:
                self._write(key,state="dormant",next_at=self.clock()+30)
                with self._lock:
                    self._active.pop(key,None)
                    if self._prepared.get(key) is carrier.prepared: self._prepared.pop(key,None)
                carrier.close()
            start = self._cursor % len(records)
            self._cursor = (start+1) % len(records)
            for identifier,record in (records[start:]+records[:start])[:128]:
                state = self._state(identifier)
                if not state["enabled"]: continue
                # Revocation must cancel owned sockets even while a handshake
                # is pending or every worker slot is occupied.
                try: self._authority(record)
                except Exception:
                    self.pause(identifier,reason="authorization_unavailable")
                    continue
                with self._lock:
                    carrier = self._active.get(identifier)
                    if identifier in self._pending or len(self._workers) >= MAX_ATTEMPTS: continue
                live = carrier is not None and not carrier._stop.is_set()
                if carrier is not None and not live:
                    with self._lock: self._active.pop(identifier,None)
                    if state["state"] == "connected":
                        state=self._write(identifier,state="reconnecting",next_at=self.clock())
                if live and carrier.recovery and getattr(carrier,"route_signature",None) != self._route_signature and route is not None:
                    token=(self._epoch,object())
                    thread=threading.Thread(target=self._migrate,args=(identifier,record,carrier,route,token),daemon=True,name="mesh-direct-migrate")
                elif live and carrier.recovery and self.clock() >= state.get("renew_at",float("inf")):
                    token=(self._epoch,object())
                    thread=threading.Thread(target=self._renew,args=(identifier,record,carrier,token),daemon=True,name="mesh-direct-renew")
                elif self.clock() >= state["next_at"]:
                    with self._lock:
                        reserved = {key for key,c in self._active.items() if not c._stop.is_set()} | set(self._pending)
                        if identifier not in reserved and len(reserved) >= MAX_ACTIVE: continue
                    token=(self._epoch,object())
                    thread=threading.Thread(target=self._attempt,args=(identifier,record,token),daemon=True,name="mesh-direct-reconnect")
                else: continue
                with self._lock:
                    self._pending[identifier]=token
                    self._workers.add(thread)
                thread.start()

    def status(self):
        result=[]
        with self._lock:
            active=dict(self._active)
            native_seen=dict(self._native_seen)
        for identifier,record in self.service.store.items("direct_relationship")[:128]:
            state=self._state(identifier)
            carrier=active.get(identifier)
            live=bool(carrier and not carrier._stop.is_set())
            peer_live=bool(live and carrier.peer_seen_at > 0 and time.monotonic()-carrier.peer_seen_at < 15)
            native_at=max(native_seen.get(identifier,0),getattr(carrier,"native_seen_at",0))
            result.append({"relationship_id":identifier,"workspace_id":record["scope"]["workspace_id"],
                "peer_device_id":record["scope"]["issuer_device_id"],
                "state":"connected" if live and peer_live and state["enabled"] else state["state"] if state["state"] != "connected" else "reconnecting",
                "native_engine_healthy":native_at > 0 and time.monotonic()-native_at < 3,
                "authenticated_peer_live":peer_live,
                "rns_ready":bool(peer_live and self.service.network and self.service.network.recipient_ready(carrier._peer)
                                 and self.service.network.path_known(carrier._peer))})
        return result

    def pause(self, identifier, *, reason="dormant"):
        if self.service.store.get("direct_relationship",identifier) is None:
            raise ValidationError("Unknown direct relationship")
        self._write(identifier,enabled=False,state=reason)
        with self._lock:
            self._pending.pop(identifier,None)
            self._waiting_hints.discard(identifier)
            carrier=self._active.pop(identifier,None)
            prepared=self._prepared.pop(identifier,None)
        if carrier: carrier.close()
        if prepared: prepared.close()
        return {"relationship_id":identifier,"state":reason}

    def resume(self, identifier):
        record=self.service.store.get("direct_relationship",identifier)
        if record is None: raise ValidationError("Unknown direct relationship")
        self._authority(record)
        self._write(identifier,enabled=True,state="reconnecting",next_at=self.clock())
        self._wake.set()
        return {"relationship_id":identifier,"state":"reconnecting"}

    def export(self, identifier):
        record=self.service.store.get("direct_relationship",identifier)
        if record is None: raise ValidationError("Unknown direct relationship")
        self._authority(record)
        with self._lock: prepared=self._prepared.get(identifier)
        local=self._state(identifier).get("local")
        if prepared is None or not local or local["expires_at"] <= self.clock():
            self.resume(identifier)
            return {"relationship_id":identifier,"state":"preparing","text":None}
        prepared.document_fields()
        return {"relationship_id":identifier,"state":"ready","text":local["document"]}

    def retire(self, *, close=False):
        with self._lock:
            self._epoch += 1
            active,self._active=list(self._active.values()),{}
            prepared,self._prepared=list(self._prepared.values()),{}
            self._pending.clear()
            self._waiting_hints.clear()
            self._native_seen.clear()
            self._initialized=False
        if close: self._stop.set()
        for carrier in active: carrier.close()
        for item in prepared: item.close()
        self._wake.set()

    def wait(self, timeout=None):
        deadline=None if timeout is None else time.monotonic()+timeout
        with self._lock: workers=list(self._workers)
        for thread in [self._thread]+workers:
            if thread is threading.current_thread() or not thread.is_alive(): continue
            thread.join(None if deadline is None else max(0,deadline-time.monotonic()))
        return not any(t.is_alive() for t in [self._thread]+workers if t is not threading.current_thread())
