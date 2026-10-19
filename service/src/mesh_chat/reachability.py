"""Server-free reachability evidence for the direct connection wizard.

This module only describes what the two devices and their local routers can
prove. A prepared mapping is never reachability; an authenticated peer check
is the only verification. It never contacts an observer, rendezvous, relay or
third device.
"""
from __future__ import annotations

import ipaddress
import time

from . import connectivity as c
from .errors import ValidationError

STEP_LABELS = {
    "existing_path": "Existing Mesh route",
    "ipv6": "IPv6",
    "ipv6_pinhole": "IPv6 pinhole",
    "public_ipv4": "Public IPv4",
    "pcp": "PCP",
    "upnp": "UPnP",
    "nat_pmp": "NAT-PMP",
    "manual": "Manual UDP forward",
    "firewall": "Windows firewall",
    "upstream_nat": "Upstream NAT",
}
MAPPING_METHODS = ("pcp", "upnp", "nat_pmp")
UPSTREAM_REASONS = frozenset({"upstream_nat_detected", "upnp_wan_private", "upnp_wan_shared"})
PUBLIC_KINDS = frozenset({"public_ipv4", "public_ipv6"})


def manual_candidate(host: object, port: object, expires_at: object, *, now: int | None = None) -> dict:
    """Validate one user-declared public UDP endpoint for the exact socket."""
    now = int(time.time()) if now is None else int(now)
    if not isinstance(host, str):
        raise ValidationError("Manual forward address is invalid")
    value = host.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValidationError("Manual forward address is invalid") from exc
    kind = c.classify_address(value)
    if address.is_unspecified or kind not in PUBLIC_KINDS:
        raise ValidationError("Manual forward address must be publicly routable")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValidationError("Manual forward port is invalid")
    if type(expires_at) is not int or expires_at <= now:
        raise ValidationError("Manual forward expired")
    return {"host": value, "port": port, "expires_at": expires_at}


def _step(identifier: str, state: str, reason: str | None = None) -> dict:
    return {"id": identifier, "label": STEP_LABELS[identifier], "state": state, "reason": reason}


def build_plan(
    *,
    candidates: list[dict],
    sources: dict,
    mapping_attempts: list[dict],
    ipv6_pinhole: dict | None,
    manual: dict | None,
    firewall: dict | None,
    has_route: bool,
    route_available: bool,
    local_host: str | None,
    local_port: int | None,
    now: int | None = None,
) -> dict:
    """Build a deterministic, address-free-except-local-evidence plan."""
    now = int(time.time()) if now is None else int(now)
    current = [item for item in candidates if item.get("expires_at", 0) > now]
    steps: list[dict] = []
    blockers: list[str] = []

    def source(item):
        return sources.get((item["host"], item["port"]), "local_global")

    ipv6 = [item for item in current if ":" in item["host"]]
    if ipv6:
        steps.append(_step("ipv6", "prepared", "ipv6_candidate_prepared"))
    elif not has_route:
        steps.append(_step("ipv6", "unavailable", "no_route"))
    elif not route_available:
        steps.append(_step("ipv6", "unavailable", "no_eligible_route"))
    else:
        steps.append(_step("ipv6", "unavailable", "no_global_ipv6_address"))
    if ipv6_pinhole:
        steps.append(_step("ipv6_pinhole", ipv6_pinhole.get("state", "unavailable"),
                           ipv6_pinhole.get("reason")))
    elif ipv6:
        steps.append(_step("ipv6_pinhole", "not_tried", "ipv6_pinhole_unavailable"))

    public_v4 = [item for item in current if ":" not in item["host"] and source(item) == "local_global"]
    if public_v4:
        steps.append(_step("public_ipv4", "prepared", "public_ipv4_prepared"))
    else:
        steps.append(_step("public_ipv4", "unavailable", "no_public_ipv4"))

    attempts_by_method: dict[str, list[dict]] = {method: [] for method in MAPPING_METHODS}
    for attempt in mapping_attempts:
        method = attempt.get("method")
        if method in attempts_by_method:
            attempts_by_method[method].append(attempt)
    for method in MAPPING_METHODS:
        attempts = attempts_by_method[method]
        prepared = [item for item in current if source(item) == method]
        if prepared:
            steps.append(_step(method, "prepared", "mapping_prepared"))
            continue
        failures = [item for item in attempts if item.get("state") == "failed"]
        if failures:
            steps.append(_step(method, "failed", failures[-1].get("reason") or "mapping_failed"))
        elif attempts:
            steps.append(_step(method, "failed", attempts[-1].get("reason") or "mapping_failed"))
        else:
            steps.append(_step(method, "not_tried", "mapping_not_attempted"))

    if manual:
        steps.append(_step("manual", "prepared", "manual_forward_configured"))
    else:
        steps.append(_step("manual", "not_tried",
                           "manual_forward_available" if has_route else "no_route"))

    if firewall:
        steps.append(_step("firewall", firewall.get("state", "skipped"), firewall.get("reason")))
    else:
        steps.append(_step("firewall", "skipped", "firewall_not_checked"))

    upstream = [item for item in mapping_attempts if item.get("reason") in UPSTREAM_REASONS]
    if upstream:
        steps.append(_step("upstream_nat", "blocked", upstream[-1]["reason"]))
        blockers.append("upstream_nat")

    candidate_sources = {key: 0 for key in ("ipv4", "ipv6", "local_global", "pcp", "upnp", "nat_pmp", "manual")}
    for item in current:
        key = source(item)
        if key in candidate_sources:
            candidate_sources[key] += 1
        candidate_sources["ipv6" if ":" in item["host"] else "ipv4"] += 1

    if not current:
        if not has_route:
            blockers.append("no_route")
        elif not route_available:
            blockers.append("no_eligible_route")
        else:
            blockers.append("no_public_candidate")
        if "upstream_nat" in blockers and len(blockers) == 1:
            blockers.append("no_public_candidate")

    if current:
        state = "needs_action" if firewall and firewall.get("state") in {"needs_consent", "failed"} else "prepared"
    else:
        state = "blocked"

    primary_action = None
    if state == "needs_action":
        label = "Try Windows Firewall permission again" if firewall and firewall.get("state") == "failed" else "Allow UDP in Windows Firewall"
        primary_action = {"kind": "allow_firewall", "label": label}
    elif state == "blocked":
        if "upstream_nat" in blockers:
            primary_action = {"kind": "change_network", "label": "Try another network or IPv6"}
        elif has_route and route_available:
            primary_action = {"kind": "manual_forward", "label": "Set up manual UDP forward"}
        else:
            primary_action = {"kind": "change_network", "label": "Check this device's Internet connection"}

    manual_forward = None
    if local_host and local_port:
        manual_forward = {"local_host": local_host, "local_port": int(local_port)}
        if manual:
            manual_forward.update({"external_host": manual["host"], "external_port": manual["port"]})

    return {
        "state": state,
        "steps": steps,
        "candidate_count": len(current),
        "candidate_sources": candidate_sources,
        "primary_action": primary_action,
        "blockers": blockers,
        "manual_forward": manual_forward,
    }
