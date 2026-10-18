import json
import threading
import time
import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest
import RNS

from mesh_chat.direct_binding import BindingAuthority, create_binding, verify_binding
from mesh_chat import direct_recovery_protocol as p
from mesh_chat.direct_recovery import DirectRecovery, retry_delay
from mesh_chat.direct_relationship import accept_relationship, relationship_id
from mesh_chat.errors import ValidationError, IdentityMismatch
from mesh_chat.vault import VaultStore
from mesh_chat.workspace_protocol import _destination_for
from test_workspace_service import _joined_pair


@pytest.fixture
def pair(tmp_path):
    values=_joined_pair(tmp_path,base=700001)
    owner,_,_,member,_,_,workspace,_,identity=values
    owner._retry_thread.join(timeout=2)
    assert not owner._retry_thread.is_alive()
    owner._shutdown.clear()
    local=owner._require_workspace(workspace["id"])
    remote=member._require_workspace(workspace["id"])
    record={"scope":{"kind":"workspace","workspace_id":workspace["id"],
        "issuer_device_id":remote["local_device_id"],"audience_device_id":local["local_device_id"]},
        "issuer":identity.get_public_key().hex(),"audience":_destination_for(owner._identity).hex()}
    now=int(time.time())
    authority=p.authority(record,now=now)
    def document(generation=1,certificate=b"fresh native public certificate",expiry=None):
        raw=create_binding(identity,authority,certificate,session_id=str(uuid.uuid4()),generation=generation,
            challenge=authority.challenge,candidates=[{"host":"93.184.216.34","port":12345,"expires_at":now+300}],
            issued_at=now,expires_at=expiry or now+300,version=3)
        return raw,certificate,p.encode(raw,certificate)
    try:
        yield owner,member,record,authority,document
    finally:
        owner.close(); member.close()


def test_recovery_authority_is_membership_scoped_not_invitation_or_old_pin(pair):
    owner,member,record,authority,document=pair
    raw,cert,text=document()
    with pytest.raises(ValidationError,match="established"):
        owner._direct_recovery.receive(text)
    owner._accept_direct_workspace_binding(raw,authority,cert)
    identifier=relationship_id(owner.store,authority)
    raw2,cert2,text2=document(2,b"rotated native key")
    result=owner._direct_recovery.receive(text2)
    assert result["relationship_id"]==identifier
    assert owner.store.get("direct_relationship",identifier)["certificate"]==cert2.hex()
    with pytest.raises(ValidationError,match="stale"):
        owner._direct_recovery.receive(text)
    # The current member removal, not the stored binding's expiry, ends trust.
    workspace=member._require_workspace(record["scope"]["workspace_id"])
    owner.remove_workspace_member(record["scope"]["workspace_id"],workspace["local_member_id"],str(uuid.uuid4()))
    with pytest.raises((ValidationError,IdentityMismatch)):
        owner._direct_recovery.receive(text2)


def test_capsule_is_encrypted_to_exact_rns_identity_and_bound_to_tls_leaf(pair):
    owner,member,record,authority,document=pair
    raw,cert,_=document()
    encrypted=p.capsule(owner._identity.get_public_key(),raw)
    assert raw.encode() not in encrypted
    assert p.open_capsule(owner._identity,encrypted)==raw
    with pytest.raises(ValidationError): p.open_capsule(RNS.Identity(),encrypted)
    with pytest.raises((ValidationError,IdentityMismatch)):
        verify_binding(raw,authority,b"MITM leaf",now=int(time.time()))
    damaged=bytearray(encrypted); damaged[-1]^=1
    with pytest.raises(ValidationError): p.open_capsule(owner._identity,bytes(damaged))


@pytest.mark.parametrize("fault",["audience","workspace","issuer_device","challenge","certificate","source","wire_scope"])
def test_wrong_recovery_authority_or_channel_context_is_rejected(pair,fault):
    owner,member,record,authority,document=pair
    raw,cert,text=document()
    owner._accept_direct_workspace_binding(raw,authority,cert)
    if fault in {"source","wire_scope"}:
        kwargs={"source":b"x"*16} if fault=="source" else {"workspace_id":str(uuid.uuid4())}
        with pytest.raises(ValidationError): owner._direct_recovery.receive(text,**kwargs)
        return
    changed=authority
    if fault=="audience": changed=replace(changed,audience_destination=b"x"*16)
    if fault=="workspace": changed=replace(changed,scope={**changed.scope,"workspace_id":str(uuid.uuid4())})
    if fault=="issuer_device": changed=replace(changed,scope={**changed.scope,"issuer_device_id":str(uuid.uuid4())})
    if fault=="challenge": changed=replace(changed,challenge=b"x"*32)
    with pytest.raises((ValidationError,IdentityMismatch)):
        verify_binding(raw,changed,b"wrong" if fault=="certificate" else cert,now=int(time.time()))


def test_generation_reservation_failure_has_no_native_effect_and_restart_never_resets(pair,monkeypatch):
    owner,_,record,authority,document=pair
    raw,cert,_=document()
    owner._accept_direct_workspace_binding(raw,authority,cert)
    identifier=relationship_id(owner.store,authority)
    recovery=owner._direct_recovery
    _,_,first=recovery._reserve(identifier,record)
    fresh=DirectRecovery(owner)
    _,_,second=fresh._reserve(identifier,record)
    assert second>first
    original=owner.store._seal
    def failed(*args): raise OSError("disk full")
    monkeypatch.setattr(owner.store,"_seal",failed)
    with pytest.raises(OSError): fresh._reserve(identifier,record)
    monkeypatch.setattr(owner.store,"_seal",original)
    assert fresh._reserve(identifier,record)[2]==second+1
    assert owner.store.get("direct_recovery",identifier)["attempts"]==3


def test_replayed_update_does_not_reset_retry_budget_or_revive_paused_work(pair):
    owner,_,record,authority,document=pair
    raw,cert,text=document()
    owner._accept_direct_workspace_binding(raw,authority,cert)
    identifier=relationship_id(owner.store,authority)
    recovery=owner._direct_recovery
    recovery._reserve(identifier,record)
    before=recovery._state(identifier)
    recovery.receive(text)
    assert recovery._state(identifier)==before
    recovery.pause(identifier)
    recovery.receive(text)
    assert recovery._state(identifier)["enabled"] is False
    assert recovery.status()[0]["state"]=="dormant"
    assert recovery.status()[0]["authenticated_peer_live"] is False


def test_restart_export_never_replays_a_saved_document_without_socket_ownership(pair):
    owner,_,record,authority,document=pair
    raw,cert,text=document()
    owner._accept_direct_workspace_binding(raw,authority,cert)
    identifier=relationship_id(owner.store,authority)
    owner._direct_recovery._write(identifier,local={"document":text,"expires_at":int(time.time())+100})
    fresh=DirectRecovery(owner)
    result=fresh.export(identifier)
    assert result=={"relationship_id":identifier,"state":"preparing","text":None}
    assert set(fresh.status()[0])=={"relationship_id","workspace_id","peer_device_id","state",
        "native_engine_healthy","authenticated_peer_live","rns_ready"}


@pytest.mark.parametrize("attempt",[1,2,6,8,1000000])
def test_retry_jitter_is_bounded(attempt):
    assert 1.5<=retry_delay(attempt,0)<=retry_delay(attempt,.5)<=retry_delay(attempt,1)<=320


def test_retirement_invalidates_old_callbacks_without_reviving_ownership(pair):
    owner,_,record,authority,document=pair
    raw,cert,_=document(); owner._accept_direct_workspace_binding(raw,authority,cert)
    identifier=relationship_id(owner.store,authority)
    recovery=owner._direct_recovery
    old=(recovery._epoch,object()); recovery._pending[identifier]=old
    assert recovery._valid(identifier,old)
    recovery.retire()
    assert not recovery._valid(identifier,old)
    new=(recovery._epoch,object()); recovery._pending[identifier]=new
    assert recovery._valid(identifier,new) and not recovery._valid(identifier,old)


def test_unknown_document_shape_is_rejected(pair):
    _,_,_,_,document=pair
    _,_,text=document()
    value=json.loads(text[len(p.PREFIX):]); value["native_handle"]=123
    from mesh_chat.invitations import canonical_bytes
    with pytest.raises(ValidationError): p.decode(p.PREFIX+canonical_bytes(value).decode())
    with pytest.raises(ValidationError): p.decode(text+" ")
    with pytest.raises(ValidationError): p.decode("mesh-direct:"+text)


def test_retired_renewal_cannot_reserve_or_overwrite_new_generation(pair):
    owner,_,record,authority,document=pair
    raw,cert,_=document(); owner._accept_direct_workspace_binding(raw,authority,cert)
    recovery=owner._direct_recovery; identifier=relationship_id(owner.store,authority)
    token=(recovery._epoch,object()); recovery._pending[identifier]=token
    recovery._reserve(identifier,record)
    before=recovery._state(identifier)
    recovery.retire()
    with pytest.raises(ValidationError,match="retired"):
        recovery._save_local(identifier,record,None,{},[],reserve=True,token=token)
    assert recovery._state(identifier)==before


def test_manual_hint_interrupts_only_waiting_listener_not_authenticated_path(pair):
    owner,_,record,authority,document=pair
    raw,cert,_=document(); owner._accept_direct_workspace_binding(raw,authority,cert)
    recovery=owner._direct_recovery; identifier=relationship_id(owner.store,authority)
    token=(recovery._epoch,object()); recovery._pending[identifier]=token
    recovery._waiting_hints.add(identifier)
    closed=[]
    recovery._prepared[identifier]=SimpleNamespace(close=lambda:closed.append(True))
    _,_,text=document(2)
    recovery.receive(text)
    assert closed==[True] and not recovery._valid(identifier,token)
    assert identifier not in recovery._waiting_hints


def test_crash_cleanup_references_remain_bounded_until_lease_expiry(pair):
    owner,_,record,authority,document=pair
    raw,cert,_=document(); owner._accept_direct_workspace_binding(raw,authority,cert)
    recovery=owner._direct_recovery; identifier=relationship_id(owner.store,authority)
    prepared=SimpleNamespace(_owned={"host":"192.168.1.2","port":45000})
    fields={"certificate":cert,"session_id":str(uuid.uuid4()),"generation":1,
        "candidates":[],"expires_at":int(time.time())+100}
    mapping={"lifetime":50,"protocol":"udp","cleanup":{"nonce":"owned-only"}}
    recovery._save_local(identifier,record,prepared,fields,[mapping])
    recovery._save_local(identifier,record,prepared,fields,[],reserve=True)
    state=recovery._state(identifier)
    assert state["orphan_cleanup"][0]["mapping"]==mapping
    assert state["orphan_cleanup"][0]["expires_at"]<=int(time.time())+50
    # A restart retains evidence, never sends blind deletion for an unowned tuple.
    fresh=DirectRecovery(owner)
    assert fresh._state(identifier)["orphan_cleanup"]==state["orphan_cleanup"]
    recovery.clock=lambda:time.time()+60
    fields["expires_at"]=int(time.time())+100
    recovery._save_local(identifier,record,prepared,fields,[],reserve=True)
    assert recovery._state(identifier)["orphan_cleanup"]==[]


def test_scheduler_reserves_profile_capacity_and_rotates_fairly(monkeypatch):
    from copy import deepcopy
    from mesh_chat import direct_recovery as module
    class Store:
        def __init__(self): self.values={}
        def get(self,kind,key): return deepcopy(self.values.get((kind,key)))
        def update_record(self,kind,key,update):
            value=update(self.get(kind,key)); self.values[kind,key]=deepcopy(value); return value
        def items(self,kind): return [(str(i),{}) for i in range(8)]
    service=SimpleNamespace(store=Store(),_dispatch_lock=threading.RLock(),_direct_native=object(),network=object(),_check_direct_runtime_available=lambda:None)
    recovery=DirectRecovery(service); recovery._initialized=True
    recovery._authority=lambda record:None
    recovery._route_check_at=float("inf")
    started=[]
    class Worker:
        def __init__(self,*,target,args,**kwargs): self.args=args
        def start(self): started.append(self.args[0])
    monkeypatch.setattr(module.threading,"Thread",Worker)
    carrier=lambda:SimpleNamespace(_stop=threading.Event(),recovery=False)
    recovery._active={str(i):carrier() for i in range(3)}
    for identifier in recovery._active: recovery._write(identifier,next_at=float("inf"))
    recovery.tick()
    assert len(started)==1 and len(recovery._pending)==1  # Three active + one reserved.
    recovery._active.clear()
    for i in range(8): recovery._write(str(i),next_at=0)
    seen=set()
    for _ in range(8):
        recovery._pending.clear(); recovery._workers.clear(); started.clear()
        recovery.tick()
        assert len(started)==4
        seen.update(started)
    assert seen=={str(i) for i in range(8)}
    # Cancelled-but-blocked router workers retain their worker budget.
    recovery._pending.clear(); started.clear(); recovery.tick()
    assert started==[]


def test_new_update_preserves_explicit_pause(pair):
    owner,_,record,authority,document=pair
    raw,cert,_=document(); owner._accept_direct_workspace_binding(raw,authority,cert)
    recovery=owner._direct_recovery; identifier=relationship_id(owner.store,authority)
    recovery.pause(identifier)
    _,_,text=document(2)
    recovery.receive(text)
    assert recovery.status()[0]["state"]=="dormant"
    assert not recovery._state(identifier)["enabled"]


def test_server_migration_failure_schedules_reconnection_instead_of_retrying_rebind(pair):
    owner,_,record,authority,document=pair
    raw,cert,_=document(); owner._accept_direct_workspace_binding(raw,authority,cert)
    recovery=owner._direct_recovery; identifier=relationship_id(owner.store,authority)
    token=(recovery._epoch,object()); recovery._pending[identifier]=token
    def unsupported(*args): raise ValidationError("server rebind unsupported")
    carrier=SimpleNamespace(prepared=SimpleNamespace(migrate=unsupported),route_signature=None)
    route=SimpleNamespace(interface="new",local_address="192.168.2.2",gateway="192.168.2.1")
    recovery._migrate(identifier,record,carrier,route,token)
    assert carrier.route_signature==("new","192.168.2.2","192.168.2.1")
    assert recovery._state(identifier)["next_at"]<=time.time()
    assert identifier not in recovery._pending


@pytest.mark.parametrize("fault",[None,"wrong_leaf","success_commit","winner_commit","stale_callback"])
def test_replacement_requires_current_authentication_and_durable_winner_before_old_retirement(pair,monkeypatch,fault):
    from mesh_chat import direct_recovery as module
    owner,_,record,authority,document=pair
    raw,cert,_=document(); owner._accept_direct_workspace_binding(raw,authority,cert)
    identifier=relationship_id(owner.store,authority)
    owner._direct_recovery.retire(close=True); owner._direct_recovery.wait(2)
    recovery=DirectRecovery(owner); owner._direct_recovery=recovery
    token=(recovery._epoch,object()); recovery._pending[identifier]=token
    record=owner.store.get("direct_relationship",identifier)
    peer_raw,peer_cert,_=document(2,b"fresh peer key")
    events=[]
    class Prepared:
        handle=7
        expires_at=time.time()+300
        _owned={"host":"93.184.216.34","port":45678}
        def document_fields(self): return {"certificate":b"our fresh key","session_id":str(uuid.uuid4()),
            "generation":self.generation,"expires_at":int(self.expires_at),"candidates":[{"host":"93.184.216.34","port":45678,"expires_at":int(self.expires_at)}]}
        def cleanup_records(self): return []
        def close(self): events.append("new_closed")
    prepared=Prepared()
    def prepare(*args,**kwargs): prepared.generation=kwargs["generation"]; return prepared
    monkeypatch.setattr(module,"prepare_candidates",prepare)
    owner.network.destination_hash = _destination_for(owner._identity)
    class Native:
        authorized=False
        def close(self): pass
        def request(self,name,**payload):
            if name=="poll": return {"state":1 if self.authorized else 3,"packets":[]}
            if name=="recovery_evidence": return {"capsule":p.capsule(owner._identity.get_public_key(),peer_raw).hex(),
                "certificate":(b"wrong leaf" if fault=="wrong_leaf" else peer_cert).hex(),"token":"bound exporter"}
            if name=="authorize_recovery":
                assert payload["token"]=="bound exporter"
                self.authorized=True; events.append("native_authorized")
    owner._direct_native=Native()
    old=SimpleNamespace(_stop=threading.Event(),close=lambda:events.append("old_closed"))
    recovery._active[identifier]=old
    class Carrier:
        def __init__(self,*args,**kwargs):
            self.prepared=prepared; self._stop=threading.Event(); self.peer_seen=threading.Event()
            self.peer_seen.set(); self.lease=kwargs["runtime_lease"]
        def start(self):
            events.append("peer_confirmed")
            if fault=="stale_callback": recovery._pending[identifier]=(recovery._epoch,object())
        def close(self): self._stop.set(); self.lease.cancel(); prepared.close()
    monkeypatch.setattr(module,"AdmittedCarrier",Carrier)
    recovery._send=lambda *args:False
    original_success=module.record_success
    def success(*args,**kwargs):
        if fault=="success_commit": raise OSError("vault unavailable")
        result=original_success(*args,**kwargs); events.append("success_saved"); return result
    monkeypatch.setattr(module,"record_success",success)
    original_write=recovery._write
    def write(identifier,**changes):
        if "winner" in changes:
            if fault=="winner_commit": raise OSError("vault unavailable")
            events.append("winner_saved")
        return original_write(identifier,**changes)
    recovery._write=write
    recovery._attempt(identifier,record,token)
    if fault:
        assert "old_closed" not in events and "new_closed" in events
        assert recovery._active[identifier] is old
    else:
        assert events==["native_authorized","peer_confirmed","success_saved","winner_saved","old_closed"]
        assert recovery._active[identifier] is not old
    # Test native is deliberately minimal; ordinary profile cleanup has no IPC.
    owner._direct_native=None


def test_native_reply_does_not_claim_peer_liveness_or_application_receipt(pair):
    owner,_,_,authority,document=pair
    raw,cert,_=document(); owner._accept_direct_workspace_binding(raw,authority,cert)
    recovery=owner._direct_recovery; identifier=relationship_id(owner.store,authority)
    recovery._native_seen[identifier]=time.monotonic()
    status=recovery.status()[0]
    assert status["native_engine_healthy"]
    assert not status["authenticated_peer_live"] and not status["rns_ready"]
    assert status["state"]!="connected"
