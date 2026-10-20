import time
import threading
import uuid
import socket

import pytest
import RNS

from mesh_chat import direct_setup
from mesh_chat import connectivity as connectivity_module
from mesh_chat import firewall as firewall_module
from mesh_chat.direct_candidates import prepare_candidates
from mesh_chat.direct_documents import verify_connection_document
from mesh_chat.errors import IdentityMismatch, NativeUnavailable, ValidationError, WorkspaceAlreadyKnown
from test_workspace_service import _service, _op


class Native:
    def __init__(self, label):
        self.label, self.next = label, 1
        self.owned, self.calls, self.closed = {}, [], False

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
        self.closed = True

    def retire(self):
        self.owned.clear()


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
    assert preview["existing_workspace"] is None
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


def test_resume_uses_saved_reply_and_refuses_to_export_after_socket_loss(peers):
    owner, joiner, workspace, invite = peers
    offer = owner._direct_setup.offer(invite["id"])
    answer = joiner._direct_setup.answer(offer["text"], _op(98002))
    before = joiner.store.list("workspace_join_delivery")
    restored = joiner._direct_setup.resume(workspace["id"])
    assert restored["text"] == answer["text"]
    joiner._direct_setup.retire()
    restored = joiner._direct_setup.resume(workspace["id"])
    assert restored["state"] == "refresh_required"
    assert "text" not in restored
    assert joiner.store.list("workspace_join_delivery") == before


def test_owner_resume_keeps_the_exact_live_offer_and_rejects_mixed_identifiers(peers):
    owner, _, workspace, invite = peers
    offer = owner._direct_setup.offer(invite["id"])
    restored = owner._execute("resume_direct_setup", {"invitation_id":invite["id"]})
    assert restored["text"] == offer["text"]
    assert restored["setup_id"] == offer["setup_id"]
    with pytest.raises(ValidationError):
        owner._execute("resume_direct_setup", {"workspace_id":workspace["id"], "invitation_id":invite["id"]})
    owner._direct_setup.retire()
    restored = owner._execute("resume_direct_setup", {"invitation_id":invite["id"]})
    assert restored["state"] == "refresh_required"
    assert "text" not in restored


@pytest.mark.parametrize("native_state", [0, 1, 2])
def test_owner_resume_after_activation_reads_state_without_inspecting_or_draining_packets(peers, native_state):
    from types import SimpleNamespace
    owner, joiner, _, invite = peers
    offer = owner._direct_setup.offer(invite["id"])
    answer = joiner._direct_setup.answer(offer["text"], _op(98002))
    ready = owner._direct_setup.ready(answer["text"])
    setup = owner._direct_setup
    identifier = ready["setup_id"]
    prepared = setup._prepared[identifier]
    setup._state(identifier, "connecting", "ready", ready["workspace_id"], prepared.document_fields())
    setup._carriers[identifier] = SimpleNamespace(prepared=prepared, _stop=threading.Event())
    original = owner._direct_native.request
    def request(operation, **payload):
        assert operation not in {"inspect", "inspect_paths", "poll"}
        if operation == "connection_state": return {"state":native_state}
        return original(operation, **payload)
    owner._direct_native.request = request
    try:
        restored = setup.resume(invitation_id=invite["id"])
        if native_state == 0:
            assert restored["text"] == ready["text"]
        else:
            assert "text" not in restored
            assert restored["state"] == ("bootstrap_connected" if native_state == 1 else "refresh_required")
    finally:
        setup._carriers.pop(identifier)
        owner._direct_native.request = original


def test_diagnostic_clear_preserves_request_and_encrypted_state(peers):
    owner, joiner, workspace, invite = peers
    offer = owner._direct_setup.offer(invite["id"])
    joiner._direct_setup.answer(offer["text"], _op(98002))
    before = {kind:joiner.store.list(kind) for kind in ("workspace", "workspace_join_delivery", "direct_join_exchange")}
    report = joiner._execute("connection_diagnostics", {})
    assert report["events"]
    assert offer["text"] not in str(report)
    assert not joiner._execute("clear_connection_diagnostics", {})["events"]
    assert {kind:joiner.store.list(kind) for kind in before} == before


def test_completed_setup_survives_socket_expiry_and_cancel_pauses_saved_relationship(peers,monkeypatch):
    owner,_,workspace,invite=peers
    setup=owner._direct_setup
    offer=setup.offer(invite["id"])
    carrier=object()
    setup._carriers[offer["setup_id"]]=carrier
    identifier="opaque-relationship"
    owner.store.put("direct_relationship",identifier,{"version":1})
    setup.relationship_ready(carrier,identifier)
    setup._carriers.clear(); setup._prepared.clear()  # Restart drops runtime ownership.
    value=owner.store.get("direct_setup",offer["setup_id"])
    owner.store.put("direct_setup",offer["setup_id"],{**value,"expires_at":1})
    assert setup.status(offer["setup_id"])["state"]=="relationship_active"
    paused=[]
    monkeypatch.setattr(owner._direct_recovery,"pause",paused.append)
    setup.cancel(offer["setup_id"])
    assert paused==[identifier]
    assert setup.status(offer["setup_id"])["state"]=="cancelled"


def test_reply_diagnostics_distinguish_a_new_invitation_from_the_saved_request(peers):
    owner, joiner, workspace, invite = peers
    first = owner._direct_setup.offer(invite["id"])
    joiner._direct_setup.answer(first["text"], _op(99120))
    saved = joiner._require_workspace(workspace["id"])
    deliveries = joiner.store.list("workspace_delivery")
    replacement = owner.create_workspace_invitation_command(workspace["id"], _op(99121))
    fresh = owner._direct_setup.offer(replacement["id"])
    preview = joiner._execute("preview_direct_connection", {"document":fresh["text"]})
    assert preview["kind"] == "offer"
    assert preview["existing_workspace"]["can_continue"] is False
    assert preview["existing_workspace"]["reason"] == "invitation_mismatch"
    with pytest.raises(WorkspaceAlreadyKnown) as caught:
        joiner._execute("prepare_direct_answer", {"document":fresh["text"], "operation_id":_op(99122)})
    assert caught.value.reason == "invitation_mismatch"
    report = joiner._execute("connection_diagnostics", {})
    failure = report["last_failure"]
    assert (failure["command"], failure["error_code"], failure["failure_stage"],
            failure["failure_reason"], failure["workspace_state"]) == (
        "prepare_direct_answer", "workspace_already_known", "join_authorization",
        "invitation_mismatch", "joining")
    assert fresh["text"] not in str(report)
    assert joiner._require_workspace(workspace["id"]) == saved
    assert joiner.store.list("workspace_delivery") == deliveries


def test_owner_answer_preview_is_not_rerouted_to_the_active_saved_workspace(peers):
    owner, joiner, _, invite = peers
    offer = owner._direct_setup.offer(invite["id"])
    answer = joiner._direct_setup.answer(offer["text"], _op(99134))
    preview = owner._execute("preview_direct_connection", {"document":answer["text"]})
    assert preview["kind"] == "answer"
    assert preview["existing_workspace"] is None
    ready = owner._execute("prepare_direct_ready", {"document":answer["text"]})
    assert ready["state"] == "ready_to_share"
    assert ready["text"]


def test_preview_reports_the_saved_workspace_without_mutating_or_retaining_sockets(peers):
    owner, joiner, workspace, invite = peers
    offer = owner._direct_setup.offer(invite["id"])
    answer = joiner._direct_setup.answer(offer["text"], _op(99125))
    saved = joiner._require_workspace(workspace["id"])
    before = {kind:joiner.store.list(kind) for kind in ("workspace", "workspace_delivery",
        "workspace_invitation", "direct_join_exchange")}
    owned = dict(joiner._direct_native.owned)
    preview = joiner._execute("preview_direct_connection", {"document":offer["text"]})
    assert preview["existing_workspace"] == {"id":workspace["id"], "name":"Direct setup",
        "state":"joining", "can_continue":True, "reason":None}
    # The exact saved invitation can reuse the request; the preview itself
    # still creates no socket and changes no saved record.
    assert dict(joiner._direct_native.owned) == owned
    assert {kind:joiner.store.list(kind) for kind in before} == before
    assert joiner._require_workspace(workspace["id"]) == saved
    assert answer["setup_id"] in joiner._direct_setup._prepared


def test_matching_saved_request_can_prepare_a_fresh_reply_without_replacing_the_request(peers):
    owner, joiner, workspace, invite = peers
    first = owner._direct_setup.offer(invite["id"])
    joiner._direct_setup.answer(first["text"], _op(99126))
    saved = joiner._require_workspace(workspace["id"])
    deliveries = joiner.store.list("workspace_delivery")
    exchange = joiner.store.get("direct_join_exchange", joiner._workspace_record_id(workspace["id"]))
    # The owner refreshes the same invitation's short-lived Offer. The joiner
    # keeps the exact saved join request and prepares a newer Answer generation.
    fresh = owner._direct_setup.offer(invite["id"])
    preview = joiner._execute("preview_direct_connection", {"document":fresh["text"]})
    assert preview["existing_workspace"]["can_continue"] is True
    reply = joiner._execute("prepare_direct_answer", {"document":fresh["text"], "operation_id":_op(99127)})
    assert reply["state"] == "waiting_for_ready"
    assert joiner.store.list("workspace_delivery") == deliveries
    assert joiner._require_workspace(workspace["id"])["join_delivery_id"] == saved["join_delivery_id"]
    updated = joiner.store.get("direct_join_exchange", joiner._workspace_record_id(workspace["id"]))
    assert updated["answer_accepted"]["generation"] > exchange["answer_accepted"]["generation"]
    assert updated["challenge"] == exchange["challenge"]
    assert verify_connection_document(reply["text"]).answer is not None


@pytest.mark.parametrize("state,reason", [("active", "workspace_active"), ("failed", "workspace_not_pending")])
def test_a_workspace_past_the_pending_state_is_never_replaced_by_a_new_invitation(peers, state, reason):
    owner, joiner, workspace, invite = peers
    first = owner._direct_setup.offer(invite["id"])
    joiner._direct_setup.answer(first["text"], _op(99128))
    record = dict(joiner._require_workspace(workspace["id"]))
    record["state"] = state
    joiner.store.put("workspace", joiner._workspace_record_id(workspace["id"]), record)
    replacement = owner.create_workspace_invitation_command(workspace["id"], _op(99129))
    fresh = owner._direct_setup.offer(replacement["id"])
    preview = joiner._execute("preview_direct_connection", {"document":fresh["text"]})
    assert preview["existing_workspace"]["can_continue"] is False
    assert preview["existing_workspace"]["reason"] == reason
    with pytest.raises(WorkspaceAlreadyKnown) as caught:
        joiner._execute("prepare_direct_answer", {"document":fresh["text"], "operation_id":_op(99130)})
    assert caught.value.reason == reason
    assert joiner._require_workspace(workspace["id"])["state"] == state
    assert joiner.store.list("workspace") == [record]


def test_manual_udp_forward_is_signed_and_reported_without_a_second_socket(peers, monkeypatch):
    owner, joiner, _, invite = peers
    route = connectivity_module.RouteInfo(socket.AF_INET, "wifi", "192.168.1.1", "192.168.1.20", 1)
    def prepare(native, **kwargs):
        return prepare_candidates(native, routes=[route], **kwargs)
    def unavailable(*args, **kwargs):
        raise connectivity_module.ConnectivityError("upnp", "upnp_no_discovery")
    monkeypatch.setattr(direct_setup, "prepare_candidates", prepare)
    monkeypatch.setattr(direct_setup.platform, "system", lambda: "Linux")
    monkeypatch.setattr(connectivity_module, "create_port_mapping", unavailable)
    monkeypatch.setattr(connectivity_module, "default_routes", lambda **kwargs: [route])
    offer = owner._direct_setup.offer(invite["id"], manual_host="93.184.216.34", manual_port=55000)
    assert offer["candidate_count"] == 1
    plan = offer["reachability"]
    steps = {item["id"]:item for item in plan["steps"]}
    assert steps["manual"]["state"] == "prepared"
    assert steps["upnp"]["state"] == "failed"
    assert plan["manual_forward"] == {"local_host":"192.168.1.20", "local_port":45001,
        "external_host":"93.184.216.34", "external_port":55000}
    assert plan["state"] == "prepared"
    checked = verify_connection_document(offer["text"])
    from mesh_chat.direct_binding import _parse
    assert _parse(checked.offer)["candidates"] == [
        {"host":"93.184.216.34","port":55000,"expires_at":offer["expires_at"]}]
    answer = joiner._direct_setup.answer(offer["text"], _op(99140),
        manual_host="93.184.216.34", manual_port=55001)
    assert answer["candidate_count"] == 1
    assert answer["reachability"]["manual_forward"]["external_port"] == 55001
    assert len(owner._direct_native.owned) == 1
    assert len(joiner._direct_native.owned) == 1


def test_configure_direct_firewall_is_exact_udp_and_removed_on_cancel(peers, monkeypatch):
    owner, _, _, invite = peers
    route = connectivity_module.RouteInfo(socket.AF_INET, "wifi", "192.168.1.1", "192.168.1.20", 1)
    def prepare(native, **kwargs):
        return prepare_candidates(native, routes=[route], **kwargs)
    def unavailable(*args, **kwargs):
        raise connectivity_module.ConnectivityError("upnp", "upnp_no_discovery")
    monkeypatch.setattr(direct_setup, "prepare_candidates", prepare)
    monkeypatch.setattr(direct_setup.platform, "system", lambda: "Windows")
    monkeypatch.setattr(connectivity_module, "create_port_mapping", unavailable)
    monkeypatch.setattr(connectivity_module, "default_routes", lambda **kwargs: [route])
    installed, removed = [], []
    def install(*args, **kwargs):
        installed.append((args, kwargs))
        return {"configured":True, "marker":"marker", "ready":"ready", "protocol":"UDP",
                "rule_name":"rule", "profiles":["private"]}
    monkeypatch.setattr(firewall_module, "install_temporary_windows_rule", install)
    monkeypatch.setattr(firewall_module, "remove_temporary_windows_rule", removed.append)
    offer = owner._direct_setup.offer(invite["id"], manual_host="93.184.216.34", manual_port=55000)
    steps = {item["id"]:item for item in offer["reachability"]["steps"]}
    assert steps["firewall"]["state"] == "needs_consent"
    value = owner._execute("configure_direct_firewall", {"setup_id":offer["setup_id"]})
    assert value["state"] == "prepared" and value["protocol"] == "udp"
    assert installed[0][1]["protocol"] == "UDP"
    status = owner._execute("check_direct_setup", {"setup_id":offer["setup_id"]})
    assert {item["id"]:item for item in status["reachability"]["steps"]}["firewall"]["state"] == "prepared"
    owner._execute("cancel_direct_setup", {"setup_id":offer["setup_id"]})
    assert removed == [{"configured":True, "marker":"marker", "ready":"ready", "protocol":"UDP",
        "rule_name":"rule", "profiles":["private"]}]


def test_closed_native_channel_is_reported_before_any_workspace_is_saved(peers):
    owner, joiner, _, invite = peers
    offer = owner._direct_setup.offer(invite["id"])
    joiner._direct_native.close()
    with pytest.raises(NativeUnavailable):
        joiner._execute("prepare_direct_answer", {"document":offer["text"], "operation_id":_op(99133)})
    failure = joiner._execute("connection_diagnostics", {})["last_failure"]
    assert (failure["command"], failure["error_code"], failure["failure_stage"]) == (
        "prepare_direct_answer", "native_unavailable", "runtime_check")
    assert joiner.store.list("workspace") == []


def test_terminal_saved_request_is_reported_without_replacement(peers):
    owner, joiner, workspace, invite = peers
    offer = owner._direct_setup.offer(invite["id"])
    joiner._direct_setup.answer(offer["text"], _op(99131))
    delivery_id = joiner._require_workspace(workspace["id"])["join_delivery_id"]
    delivery = dict(joiner.store.get("workspace_delivery", delivery_id))
    delivery["state"] = "failed"
    joiner.store.put("workspace_delivery", delivery_id, delivery)
    saved = joiner._require_workspace(workspace["id"])
    preview = joiner._execute("preview_direct_connection", {"document":offer["text"]})
    assert preview["existing_workspace"]["can_continue"] is False
    assert preview["existing_workspace"]["reason"] == "request_stopped"
    with pytest.raises(WorkspaceAlreadyKnown) as caught:
        joiner._execute("prepare_direct_answer", {"document":offer["text"], "operation_id":_op(99132)})
    assert caught.value.reason == "request_stopped"
    assert joiner._require_workspace(workspace["id"]) == saved
    assert joiner.store.get("workspace_delivery", delivery_id) == delivery


@pytest.mark.parametrize("stage", ["runtime_check", "save_join_request", "prepare_candidates", "save_reply", "arm_socket"])
def test_reply_failure_preserves_original_exception_and_records_its_stage(peers, monkeypatch, stage):
    owner, joiner, workspace, invite = peers
    offer = owner._direct_setup.offer(invite["id"])
    secret = "private-failure-address-192.0.2.99"
    failure = ValidationError(secret)
    def fail(*args, **kwargs):
        raise failure
    setup = joiner._direct_setup
    if stage == "runtime_check":
        monkeypatch.setattr(setup, "_available", fail)
    elif stage == "save_join_request":
        monkeypatch.setattr(joiner, "submit_workspace_join", fail)
    elif stage == "prepare_candidates":
        monkeypatch.setattr(setup, "_prepare", fail)
    elif stage == "save_reply":
        monkeypatch.setattr(joiner, "_save_direct_join_answer", fail)
    else:
        native_request = joiner._direct_native.request
        def request(op, **payload):
            return fail() if op == "arm" else native_request(op, **payload)
        monkeypatch.setattr(joiner._direct_native, "request", request)
    with pytest.raises(ValidationError) as caught:
        joiner._execute("prepare_direct_answer", {"document":offer["text"], "operation_id":_op(99123)})
    assert caught.value is failure
    report = joiner._execute("connection_diagnostics", {})
    assert report["last_failure"]["failure_stage"] == stage
    assert report["last_failure"]["error_code"] == "invalid_request"
    assert report["last_failure"]["command"] == "prepare_direct_answer"
    assert secret not in str(report) and offer["text"] not in str(report)
    assert not joiner._direct_native.owned
    saved = joiner.store.get("workspace", joiner._workspace_record_id(workspace["id"]))
    assert (saved is not None) == (stage not in {"runtime_check", "save_join_request"})


def test_reply_failure_after_preview_records_document_expiry(peers, monkeypatch):
    owner, joiner, _, invite = peers
    offer = owner._direct_setup.offer(invite["id"])
    assert joiner._execute("preview_direct_connection", {"document":offer["text"]})["kind"] == "offer"
    monkeypatch.setattr(time, "time", lambda: offer["expires_at"] + 1)
    with pytest.raises(ValidationError):
        joiner._execute("prepare_direct_answer", {"document":offer["text"], "operation_id":_op(99124)})
    report = joiner._execute("connection_diagnostics", {})
    assert report["last_failure"]["failure_stage"] == "document_verification"
    assert not joiner.store.list("workspace")
