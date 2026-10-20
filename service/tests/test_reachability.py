import pytest

from mesh_chat import reachability
from mesh_chat.errors import ValidationError


def test_plan_distinguishes_public_ipv6_ipv4_and_router_mapping():
    candidates = [
        {"host": "2606:4700:4700::1111", "port": 45000, "expires_at": 200},
        {"host": "93.184.216.34", "port": 45001, "expires_at": 200},
    ]
    sources = {
        ("2606:4700:4700::1111", 45000): "local_global",
        ("93.184.216.34", 45001): "upnp",
    }
    plan = reachability.build_plan(
        candidates=candidates, sources=sources,
        mapping_attempts=[
            {"method": "pcp", "state": "failed", "reason": "pcp_no_response"},
            {"method": "upnp", "state": "prepared", "reason": "mapping_prepared"},
        ],
        ipv6_pinhole={"state": "failed", "reason": "upnp_no_discovery"},
        manual=None, firewall=None, has_route=True, route_available=True,
        local_host="192.168.1.20", local_port=45002, now=100,
    )
    steps = {step["id"]: step for step in plan["steps"]}
    assert plan["state"] == "prepared"
    assert steps["ipv6"]["state"] == "prepared"
    assert steps["ipv6_pinhole"]["state"] == "failed"
    assert steps["public_ipv4"]["state"] == "unavailable"
    assert steps["pcp"]["state"] == "failed"
    assert steps["pcp"]["reason"] == "pcp_no_response"
    assert steps["upnp"]["state"] == "prepared"
    assert steps["nat_pmp"]["state"] == "not_tried"
    assert plan["candidate_sources"]["ipv6"] == 1
    assert plan["candidate_sources"]["ipv4"] == 1
    assert plan["candidate_sources"]["upnp"] == 1
    assert plan["manual_forward"] == {"local_host": "192.168.1.20", "local_port": 45002}


def test_carrier_nat_blocks_manual_forward():
    plan = reachability.build_plan(
        candidates=[], sources={},
        mapping_attempts=[
            {"method": "upnp", "state": "failed", "reason": "upnp_wan_shared"},
        ],
        ipv6_pinhole=None, manual=None, firewall=None,
        has_route=True, route_available=True,
        local_host="192.168.1.20", local_port=45002, now=100,
    )
    assert plan["state"] == "blocked"
    assert plan["blockers"] == ["carrier_nat"]
    assert plan["primary_action"]["kind"] == "change_network"
    steps = {item["id"]: item for item in plan["steps"]}
    assert steps["upstream_nat"]["state"] == "blocked"
    assert steps["upstream_nat"]["reason"] == "upnp_wan_shared"
    assert steps["manual"]["state"] == "unavailable"
    assert steps["manual"]["reason"] == "upstream_nat"
    assert plan["upstream_nat"] == {
        "state": "carrier_nat", "port_forward": "no", "reason": "upnp_wan_shared",
    }


def test_double_nat_allows_a_manual_forward_with_both_routers():
    plan = reachability.build_plan(
        candidates=[], sources={},
        mapping_attempts=[
            {"method": "upnp", "state": "failed", "reason": "upnp_wan_private"},
        ],
        ipv6_pinhole=None, manual=None, firewall=None,
        has_route=True, route_available=True,
        local_host="192.168.1.20", local_port=45002, now=100,
    )
    assert plan["state"] == "needs_action"
    assert plan["blockers"] == ["double_nat"]
    assert plan["primary_action"] == {
        "kind": "manual_forward", "label": "Set up manual UDP forward (both routers)",
    }
    steps = {item["id"]: item for item in plan["steps"]}
    assert steps["manual"]["state"] == "not_tried"
    assert steps["manual"]["reason"] == "manual_forward_available"
    assert plan["upstream_nat"] == {
        "state": "double_nat", "port_forward": "maybe", "reason": "upnp_wan_private",
    }


def test_unknown_upstream_nat_asks_for_the_router_wan_address():
    plan = reachability.build_plan(
        candidates=[], sources={},
        mapping_attempts=[
            {"method": "pcp", "state": "failed", "reason": "upstream_nat_detected"},
        ],
        ipv6_pinhole=None, manual=None, firewall=None,
        has_route=True, route_available=True,
        local_host="192.168.1.20", local_port=45002, now=100,
    )
    assert plan["state"] == "needs_action"
    assert plan["blockers"] == ["upstream_nat"]
    assert plan["primary_action"] == {
        "kind": "manual_forward", "label": "Check the router WAN, then try manual forward",
    }
    steps = {item["id"]: item for item in plan["steps"]}
    assert steps["manual"]["state"] == "not_tried"
    assert steps["manual"]["reason"] == "upstream_nat_unknown"
    assert plan["upstream_nat"] == {
        "state": "unknown", "port_forward": "unknown", "reason": "upstream_nat_detected",
    }


def test_no_route_and_no_candidate_are_distinct_blockers():
    no_route = reachability.build_plan(
        candidates=[], sources={}, mapping_attempts=[], ipv6_pinhole=None,
        manual=None, firewall=None, has_route=False, route_available=False,
        local_host=None, local_port=None, now=100,
    )
    assert no_route["state"] == "blocked"
    assert "no_route" in no_route["blockers"]
    no_candidate = reachability.build_plan(
        candidates=[], sources={}, mapping_attempts=[], ipv6_pinhole=None,
        manual=None, firewall=None, has_route=True, route_available=True,
        local_host="192.168.1.20", local_port=45002, now=100,
    )
    assert "no_public_candidate" in no_candidate["blockers"]
    assert no_candidate["primary_action"]["kind"] == "manual_forward"


def test_plan_requests_firewall_consent_for_a_prepared_candidate():
    plan = reachability.build_plan(
        candidates=[{"host": "93.184.216.34", "port": 45000, "expires_at": 200}],
        sources={("93.184.216.34", 45000): "pcp"}, mapping_attempts=[],
        ipv6_pinhole=None, manual=None,
        firewall={"state": "needs_consent", "reason": "firewall_permission_required"},
        has_route=True, route_available=True,
        local_host="192.168.1.20", local_port=45002, now=100,
    )
    assert plan["state"] == "needs_action"
    assert plan["primary_action"]["kind"] == "allow_firewall"
    assert {item["id"]: item for item in plan["steps"]}["firewall"]["state"] == "needs_consent"


def test_failed_firewall_can_be_retried_without_claiming_success():
    plan = reachability.build_plan(
        candidates=[{"host": "93.184.216.34", "port": 45000, "expires_at": 200}],
        sources={("93.184.216.34", 45000): "pcp"}, mapping_attempts=[],
        ipv6_pinhole=None, manual=None,
        firewall={"state": "failed", "reason": "windows_firewall_permission_required"},
        has_route=True, route_available=True,
        local_host=None, local_port=None, now=100,
    )
    assert plan["state"] == "needs_action"
    assert plan["primary_action"]["kind"] == "allow_firewall"
    assert "again" in plan["primary_action"]["label"]


def test_manual_candidate_requires_a_public_numeric_address_and_valid_port():
    assert reachability.manual_candidate("93.184.216.34", 55000, 200, now=100) == {
        "host": "93.184.216.34", "port": 55000, "expires_at": 200}
    assert reachability.manual_candidate("[2606:4700:4700::1111]", 55000, 200, now=100)["host"] == "2606:4700:4700::1111"
    for host, port in [
        ("192.168.1.20", 55000), ("100.64.0.1", 55000), ("127.0.0.1", 55000),
        ("evil.example", 55000), ("93.184.216.34", 0), ("93.184.216.34", 65536),
    ]:
        with pytest.raises(ValidationError):
            reachability.manual_candidate(host, port, 200, now=100)
    with pytest.raises(ValidationError):
        reachability.manual_candidate("93.184.216.34", 55000, 100, now=100)
