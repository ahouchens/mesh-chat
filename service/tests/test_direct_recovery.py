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
