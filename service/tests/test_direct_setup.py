import time
import threading
import uuid
import socket

import pytest
import RNS

from mesh_chat import direct_setup
from mesh_chat.direct_candidates import prepare_candidates
from mesh_chat.direct_documents import verify_connection_document
from mesh_chat.errors import IdentityMismatch, ValidationError
from test_workspace_service import _service, _op


class Native:
    def __init__(self, label):
        self.label, self.next = label, 1
        self.owned, self.calls = {}, []

    def request(self, op, **payload):
        self.calls.append((op, payload))
        if op == "prepare":
            identifier = self.next
            self.next += 1
            value = {"id":identifier, "session":str(uuid.uuid4()),"generation":payload["generation"],
                "host":payload["address"].rsplit(":",1)[0].strip("[]"),"port":45000+identifier,
                "certificate":f"{self.label} certificate {identifier}".encode().hex()}
            self.owned[identifier] = value
            return dict(value)
        if op == "close":
            self.owned.pop(payload["id"], None)
            return None
        if op == "reset":
            self.owned.clear()
            return None
        value = self.owned[payload["id"]]
        if op == "inspect":
            return {key:value[key] for key in ("id","host","port","certificate")}
        if op == "arm":
            assert payload["session"] == value["session"] and payload["generation"] == value["generation"]
        return None

    def close(self):
        self.owned.clear()

    retire = close


@pytest.fixture
def peers(tmp_path, monkeypatch):
    owner, _ = _service(tmp_path/"owner", RNS.Identity(), "Owner")
    joiner, _ = _service(tmp_path/"joiner", RNS.Identity(), "Joiner")
    for service, label in ((owner,"owner"),(joiner,"joiner")):
        service._retry_thread.join(timeout=2)
        assert not service._retry_thread.is_alive()
        service._shutdown.clear()
        service._direct_native = Native(label)
    monkeypatch.setattr(direct_setup, "prepare_candidates", lambda native, **kw: prepare_candidates(native, routes=[], **kw))
    workspace = owner.create_workspace(_op(98000), "Direct setup", "")
    invitation = owner.create_workspace_invitation_command(workspace["id"], _op(98001))
    yield owner, joiner, workspace, invitation
    owner.close()
    joiner.close()


def test_public_offer_answer_ready_retains_answer_socket_without_hosting(peers):
    owner, joiner, workspace, invite = peers
    offer = owner._direct_setup.offer(invite["id"])
    assert offer["state"] == "waiting_for_reply" and offer["candidate_count"] == 0
    preview = joiner._direct_setup.preview(offer["text"])
    assert preview["workspace_id"] == workspace["id"]
    assert joiner.store.list("workspace") == []  # Preview has no membership effects.
    answer = joiner._direct_setup.answer(offer["text"], _op(98002))
    assert answer["state"] == "waiting_for_ready" and answer["candidate_count"] == 0
    assert joiner._require_workspace(workspace["id"])["state"] == "joining"
    original = dict(joiner._direct_native.owned)
    ready = owner._direct_setup.ready(answer["text"])
    assert ready["state"] == "ready_to_share"
    result = joiner._direct_setup.accept_ready(ready["text"])
    assert result["state"] == "ready_received" and "text" not in result
    assert joiner._direct_native.owned == original
    assert len(owner._direct_native.owned) == 1  # Old Offer socket retired.
    assert owner.store.list("workspace_join_request") == []
    assert all(call[0] != "activate" for call in joiner._direct_native.calls)
    assert joiner._direct_setup.accept_ready(ready["text"])["setup_id"] == answer["setup_id"]


def test_unhosted_owner_ready_uses_ipv6_reply_family_and_retains_answer(peers, monkeypatch):
    from mesh_chat import connectivity as c
    owner, joiner, _, invite = peers
    offer = owner._direct_setup.offer(invite["id"])
    assert offer["candidate_count"] == 0
    def no_pinhole(*args, **kwargs):
        raise OSError("Controlled unavailable router")
    monkeypatch.setattr(c, "map_upnp_ipv6_pinhole", no_pinhole)
    def prepare(native, **kw):
        routes = [c.RouteInfo(socket.AF_INET6,"controlled",None,"2606:4700:4700::1111",1)] if native is joiner._direct_native else []
        return prepare_candidates(native,routes=routes,**kw)
    monkeypatch.setattr(direct_setup,"prepare_candidates",prepare)
    answer = joiner._direct_setup.answer(offer["text"], _op(98002))
    assert answer["candidate_count"] == 1
    retained = dict(joiner._direct_native.owned)
    ready = owner._direct_setup.ready(answer["text"])
    assert ready["candidate_count"] == 0
    assert next(iter(owner._direct_native.owned.values()))["host"] == "::"
    joiner._direct_setup.accept_ready(ready["text"])
    assert joiner._direct_native.owned == retained


def test_restart_or_suspend_requires_fresh_answer_instead_of_recreating_socket(peers):
    owner, joiner, _, invite = peers
    offer = owner._direct_setup.offer(invite["id"])
    answer = joiner._direct_setup.answer(offer["text"], _op(98002))
    ready = owner._direct_setup.ready(answer["text"])
    joiner._direct_setup.retire()
    assert joiner._direct_setup.status(answer["setup_id"])["state"] == "refresh_required"
    with pytest.raises(ValidationError, match="fresh reply"):
        joiner._direct_setup.accept_ready(ready["text"])
    replacement = joiner._direct_setup.answer(offer["text"], _op(98003))
    assert verify_connection_document(replacement["text"]).answer != verify_connection_document(answer["text"]).answer
    with pytest.raises(ValidationError, match="retained Answer"):
        joiner._direct_setup.accept_ready(ready["text"])


def test_failed_vault_write_never_exports_or_leaks_prepared_socket(peers, monkeypatch):
    owner, _, _, invite = peers
    owner._prepare_direct_invitation(invite["id"], int(time.time())+240)
    def fail(*args, **kwargs):
        raise OSError("injected persistence failure")
    monkeypatch.setattr(owner, "_save_direct_offer", fail)
    with pytest.raises(OSError):
        owner._direct_setup.offer(invite["id"])
    assert not owner._direct_native.owned


def test_selected_offer_substitution_and_revocation_fail(peers):
    owner, joiner, workspace, invite = peers
    offer = owner._direct_setup.offer(invite["id"])
    answer = joiner._direct_setup.answer(offer["text"], _op(98002))
    replacement = owner._direct_setup.offer(invite["id"])
    assert replacement["text"] != offer["text"]
    with pytest.raises(IdentityMismatch):
        owner._direct_setup.ready(answer["text"])
    owner.revoke_workspace_invitation(workspace["id"], invite["id"], _op(98003))
    with pytest.raises(ValidationError):
        owner._direct_setup.offer(invite["id"])


def test_expired_setup_and_expired_email_have_explicit_refresh(peers, monkeypatch):
    owner, joiner, _, invite = peers
    offer = owner._direct_setup.offer(invite["id"])
    with monkeypatch.context() as clock:
        clock.setattr(time, "time", lambda: offer["expires_at"]+1)
        assert owner._direct_setup.status(offer["setup_id"])["reason"] == "details_expired"
        with pytest.raises(ValidationError):
            joiner._direct_setup.answer(offer["text"], _op(98002))
    assert joiner.store.list("workspace") == []


def test_retirement_during_candidate_collection_closes_unpublished_socket(peers, monkeypatch):
    owner, _, _, _ = peers
    entered, proceed = threading.Event(), threading.Event()
    original = direct_setup.prepare_candidates
    def collect(*args, **kwargs):
        prepared = original(*args, **kwargs)
        entered.set()
        assert proceed.wait(2)
        return prepared
    monkeypatch.setattr(direct_setup, "prepare_candidates", collect)
    errors = []
    def run():
        try:
            owner._direct_setup._prepare("inflight", 1, int(time.time())+120)
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    assert entered.wait(2)
    owner._direct_setup.retire()
    proceed.set()
    thread.join(2)
    assert not thread.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], ValidationError)
    assert not owner._direct_native.owned
    assert not owner._direct_setup._prepared
    assert owner._direct_setup._inflight == 0


def test_inflight_preparations_reserve_capacity_and_failure_releases_it(peers, monkeypatch):
    owner, _, _, _ = peers
    setup = owner._direct_setup
    entered, proceed = threading.Barrier(9), threading.Event()
    def collect(*args, **kwargs):
        entered.wait(timeout=3)
        assert proceed.wait(3)
        raise OSError("injected router failure")
    monkeypatch.setattr(direct_setup, "prepare_candidates", collect)
    failures = []
    def run(index):
        try:
            setup._prepare(str(index), 1, int(time.time())+120)
        except OSError:
            failures.append(index)
    threads = [threading.Thread(target=run, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    entered.wait(timeout=3)
    try:
        with pytest.raises(ValidationError, match="capacity"):
            setup._prepare("ninth", 1, int(time.time())+120)
    finally:
        proceed.set()
        for thread in threads:
            thread.join(3)
    assert len(failures) == 8 and setup._inflight == 0


def test_cleanup_failure_does_not_strand_other_preparations(peers):
    owner, _, _, _ = peers
    closed = threading.Event()
    class Broken:
        def close(self):
            raise OSError("injected cleanup failure")
    class Healthy:
        def close(self):
            closed.set()
    setup = owner._direct_setup
    setup._prepared = {"one": Broken(), "two": Healthy()}
    setup.retire(close=True)
    assert closed.wait(2)
    with pytest.raises(ValidationError, match="closed"):
        setup._available()


@pytest.mark.parametrize("method", ["_save_direct_join_answer", "_save_direct_owner_ready"])
def test_failed_child_persistence_releases_socket_and_exports_nothing(peers, monkeypatch, method):
    owner, joiner, _, invite = peers
    offer = owner._direct_setup.offer(invite["id"])
    if method == "_save_direct_owner_ready":
        answer = joiner._direct_setup.answer(offer["text"], _op(98002))
        service, operation = owner, lambda: owner._direct_setup.ready(answer["text"])
    else:
        service, operation = joiner, lambda: joiner._direct_setup.answer(offer["text"], _op(98002))
    def fail(*args, **kwargs):
        raise OSError("injected persistence failure")
    monkeypatch.setattr(service, method, fail)
    with pytest.raises(OSError):
        operation()
    assert not service._direct_native.owned


def test_public_setup_commands_do_not_replay_dead_exports_from_command_cache(peers):
    owner, _, _, invite = peers
    request = {"v":1,"id":"reused-request-id","command":"prepare_direct_offer","payload":{"invitation_id":invite["id"]}}
    first, _ = owner.dispatch(request)
    second, _ = owner.dispatch(request)
    assert first["result"]["text"] != second["result"]["text"]
    assert owner.store.command_response(request["id"]) is None
    status, _ = owner.dispatch({"v":1,"id":"status","command":"direct_setup_status",
                                "payload":{"setup_id":second["result"]["setup_id"]}})
    assert set(status["result"]) == {"setup_id","state","kind","workspace_id","expires_at","candidate_count"}


@pytest.mark.parametrize("field", ["id","packets","certificate","private_key","client"])
def test_public_setup_payload_cannot_supply_private_native_controls(peers, field):
    owner, _, _, invite = peers
    with pytest.raises(ValidationError):
        owner.dispatch({"v":1,"id":"bad","command":"prepare_direct_offer",
                        "payload":{"invitation_id":invite["id"],field:"forbidden"}})


def test_no_candidates_uses_existing_route_queue_without_claiming_direct_connection(peers):
    owner, joiner, _, invite = peers
    offer = owner._direct_setup.offer(invite["id"])
    answer = joiner._direct_setup.answer(offer["text"],_op(98002))
    ready = owner._direct_setup.ready(answer["text"])
    joiner._direct_setup.accept_ready(ready["text"])
    for service, setup in ((owner,ready),(joiner,answer)):
        value = service._direct_setup.connect(setup["setup_id"],ready["text"])
        assert value["state"] == "existing_routes_only"
        assert not any(op == "activate" for op,_ in service._direct_native.calls)
