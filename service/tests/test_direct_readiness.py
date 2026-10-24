"""Wizard capability evidence is separate from authenticated peer reachability."""
import socket
import threading
from types import SimpleNamespace
import pytest
from mesh_chat import connectivity as c, direct_setup
from mesh_chat.direct_candidates import prepare_candidates
from test_direct_setup import peers
from test_workspace_service import _op

PUBLIC = c.RouteInfo(socket.AF_INET, "test", "93.184.216.1", "93.184.216.34", 1)
PRIVATE = c.RouteInfo(socket.AF_INET, "test", "192.168.1.1", "192.168.1.2", 1)

@pytest.fixture
def routes(peers, monkeypatch):
    current = [PUBLIC]
    monkeypatch.setattr(c, "default_routes", lambda: list(current))
    monkeypatch.setattr(direct_setup, "prepare_candidates", prepare_candidates)
    monkeypatch.setattr("mesh_chat.firewall.active_windows_profiles", lambda: ["private"])
    def unavailable(*args, **kwargs): raise OSError("No mapping response")
    monkeypatch.setattr(c, "create_port_mapping", unavailable)
    return current

def test_prepared_address_is_not_verified_and_export_checks_socket(peers, routes):
    owner, _, _, invite = peers
    value = owner._direct_setup.offer(invite["id"])
    result = owner._direct_setup.readiness(value["setup_id"])
    assert result["readiness"] == "address_prepared" and result["can_share"]
    assert not result["peer_verified"]
    owner._direct_native.owned.clear()
    result = owner._direct_setup.readiness(value["setup_id"])
    assert result["readiness"] == "refresh_required" and "text" not in result

def test_no_route_then_retry_preserves_invitation(peers, routes):
    owner, _, _, invite = peers
    routes.clear()
    value = owner._direct_setup.offer(invite["id"])
    assert owner._direct_setup.readiness(value["setup_id"])["readiness"] == "no_route"
    routes.append(PUBLIC)
    fresh = owner._direct_setup.retry(value["setup_id"])
    assert fresh["setup_id"] == value["setup_id"]
    assert owner._direct_setup.readiness(value["setup_id"])["can_share"]

def test_one_sided_candidate_allows_reply_without_reachability_claim(peers, routes):
    owner, joiner, _, invite = peers
    offer = owner._direct_setup.offer(invite["id"])
    routes[:] = [PRIVATE]
    answer = joiner._direct_setup.answer(offer["text"], _op(99101))
    result = joiner._direct_setup.readiness(answer["setup_id"])
    assert result["readiness"] == "no_local_address" and result["can_share"]
    assert result["peer_candidate_count"] == 1
    assert result["mapping"] == "unavailable" and not result["peer_verified"]

def test_both_empty_stops_before_reply_export_and_retry_keeps_join(peers, routes):
    owner, joiner, workspace, invite = peers
    routes[:] = [PRIVATE]
    offer = owner._direct_setup.offer(invite["id"])
    answer = joiner._direct_setup.answer(offer["text"], _op(99102))
    original = joiner._require_workspace(workspace["id"])
    result = joiner._direct_setup.readiness(answer["setup_id"])
    assert result["readiness"] == "both_no_address"
    assert not result["can_share"] and "text" not in result
    routes[:] = [PUBLIC]
    assert joiner._direct_setup.readiness(answer["setup_id"])["readiness"] == "network_changed"
    fresh = joiner._direct_setup.retry(answer["setup_id"])
    assert fresh["setup_id"] == answer["setup_id"]
    assert joiner._require_workspace(workspace["id"]) == original
    assert joiner._direct_setup.readiness(fresh["setup_id"])["can_share"]

@pytest.mark.parametrize("progress, phase", [(0,"testing"),(1,"peer_verified"),(2,"test_failed")])
def test_only_live_authenticated_peer_is_verified_and_route_change_invalidates(peers, routes, monkeypatch, progress, phase):
    owner, _, _, invite = peers
    value = owner._direct_setup.offer(invite["id"])
    setup = owner._direct_setup
    prepared = setup._prepared[value["setup_id"]]
    carrier = SimpleNamespace(prepared=prepared, _stop=threading.Event(), close=lambda:None)
    setup._carriers[value["setup_id"]] = carrier
    original = owner._direct_native.request
    monkeypatch.setattr(owner._direct_native, "request", lambda op, **kw: {"state":progress} if op == "connection_state" else original(op, **kw))
    result = setup.readiness(value["setup_id"])
    assert result["readiness"] == phase
    assert result["peer_verified"] == (progress == 1)
    assert "blocked" not in result["readiness"]
    routes[:] = [PRIVATE]
    result = setup.readiness(value["setup_id"])
    assert not result["peer_verified"] and not result["can_share"]
    setup._carriers.clear()

def test_expired_preparation_is_not_exportable(peers, routes):
    owner, _, _, invite = peers
    value = owner._direct_setup.offer(invite["id"])
    owner._direct_setup._prepared[value["setup_id"]].expires_at = 0
    result = owner._direct_setup.readiness(value["setup_id"])
    assert not result["can_share"] and "text" not in result


def test_repeated_expired_readiness_polls_record_one_complete_failure(peers, routes):
    owner, _, _, invite = peers
    offer = owner._direct_setup.offer(invite["id"])
    saved = owner.store.get("direct_setup", offer["setup_id"])
    owner.store.put("direct_setup", offer["setup_id"], {**saved, "expires_at": 1})
    owner._execute("clear_connection_diagnostics", {})
    for _ in range(4):
        result = owner._execute("check_direct_setup", {"setup_id": offer["setup_id"]})
        assert result["readiness"] == "refresh_required"
    events = owner._execute("connection_diagnostics", {})["events"]
    assert len(events) == 1
    assert events[0]["phase"] == "refresh_required"
    assert events[0]["firewall"] == "udp_permission_unverified"
    # A separate status request still records the state when used on its own.
    owner._execute("clear_connection_diagnostics", {})
    owner._execute("direct_setup_status", {"setup_id": offer["setup_id"]})
    assert owner._execute("connection_diagnostics", {})["last_failure"]["phase"] == "refresh_required"
