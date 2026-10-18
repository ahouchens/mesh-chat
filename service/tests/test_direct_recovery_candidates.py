import pytest
from mesh_chat import connectivity as c
from mesh_chat.direct_candidates import prepare_candidates
from mesh_chat.errors import ValidationError
from test_direct_candidates import Native, V4

class RecoveryNative(Native):
    def request(self,operation,**payload):
        return super().request("prepare" if operation=="prepare_recovery" else operation,**payload)


@pytest.mark.parametrize("busy",[3,100])
def test_saved_port_waits_for_local_quic_drain_with_bounded_fallback(monkeypatch,busy):
    native=RecoveryNative()
    original=native.request
    addresses=[]
    sleeps=[]
    def request(operation,**payload):
        if operation=="prepare_recovery":
            addresses.append(payload["address"])
            if payload["address"].endswith(":45678") and len(addresses)<=busy:
                raise ValidationError("Socket is still draining")
        return original(operation,**payload)
    native.request=request
    monkeypatch.setattr(c,"create_port_mapping",lambda *a,**k: (_ for _ in ()).throw(OSError()))
    prepared=prepare_candidates(native,generation=1,expires_at=4600,routes=[V4],recovery=True,
        preferred_port=45678,clock=lambda:1000,monotonic=lambda:100,sleep=sleeps.append)
    try:
        assert len(sleeps)==min(busy,20)
        assert sum(sleeps)<=5
        assert addresses[-1].endswith(":45678" if busy==3 else ":0")
        assert len(addresses)==(4 if busy==3 else 22)
    finally: prepared.close()


def setup(monkeypatch):
    native=RecoveryNative(); removed=[]
    old=c.MappingResult("pcp","93.184.216.34",55000,V4.local_address,45678,120,{"nonce":"old"},"udp")
    monkeypatch.setattr(c,"create_port_mapping",lambda *a,**k:old)
    monkeypatch.setattr(c,"remove_port_mapping",removed.append)
    prepared=prepare_candidates(native,generation=1,expires_at=4600,routes=[V4],recovery=True,
        clock=lambda:1000,monotonic=lambda:100)
    return native,prepared,removed


def test_renewal_signs_actual_changed_tuple_and_shortened_lease(monkeypatch):
    native,prepared,removed=setup(monkeypatch)
    saved=[]
    def renew(record,**kwargs):
        assert record["protocol"]=="udp" and record["internal_port"]==45678
        return c.MappingResult("pcp","93.184.216.35",55001,V4.local_address,45678,40,{"nonce":"new"},"udp")
    monkeypatch.setattr(c,"renew_port_mapping",renew)
    try:
        assert prepared.renew(lambda fields,cleanup:saved.append((fields,cleanup)))
        assert saved[0][0]["candidates"]==[{"host":"93.184.216.35","port":55001,"expires_at":1040}]
        assert saved[0][0]["expires_at"]==1040
        assert prepared.expires_at==4600
        assert removed[0]["external_port"]==55000
    finally: prepared.close()
    assert removed[-1]["external_port"]==55001


def test_renewing_same_tuple_does_not_delete_live_mapping(monkeypatch):
    _,prepared,removed=setup(monkeypatch)
    monkeypatch.setattr(c,"renew_port_mapping",lambda *a,**k:c.MappingResult("pcp","93.184.216.34",55000,
        V4.local_address,45678,240,{"nonce":"old","epoch":22},"udp"))
    try:
        assert prepared.renew(lambda *args:None)
        assert removed==[]
    finally: prepared.close()
    assert len(removed)==1


@pytest.mark.parametrize("fault",["unavailable","wrong_port","ownership_lost","persistence"])
def test_failed_renewal_cannot_advertise_unowned_or_uncommitted_mapping(monkeypatch,fault):
    native,prepared,removed=setup(monkeypatch)
    saved=[]
    def renew(*args,**kwargs):
        if fault=="unavailable": raise OSError("router unavailable")
        if fault=="ownership_lost": native.changed=True
        return c.MappingResult("pcp","93.184.216.35",55001,V4.local_address,
            45679 if fault=="wrong_port" else 45678,120,{},"udp")
    def persist(fields,cleanup):
        if fault=="persistence": raise OSError("disk full")
        saved.append(fields)
    monkeypatch.setattr(c,"renew_port_mapping",renew)
    try:
        if fault in {"ownership_lost","persistence"}:
            with pytest.raises((OSError,ValidationError)): prepared.renew(persist)
            assert prepared._closed
        else:
            assert not prepared.renew(persist)
            assert saved[-1]["candidates"]==[]
    finally: prepared.close()
    assert removed


def test_retirement_during_renewal_cleans_returned_mapping(monkeypatch):
    _,prepared,removed=setup(monkeypatch)
    def renew(*args,**kwargs):
        prepared.close()
        return c.MappingResult("pcp","93.184.216.35",55001,V4.local_address,45678,120,{},"udp")
    monkeypatch.setattr(c,"renew_port_mapping",renew)
    with pytest.raises(ValidationError): prepared.renew(lambda *args:pytest.fail("retired mapping exported"))
    assert {item["external_port"] for item in removed}=={55000,55001}
