"""Bounded exact-carrier facts from existing final-path inventory requests."""

import re
from uuid import UUID


EVENTS = frozenset("tick context_changed result failed adopted observed unknown".split())
PHASES = frozenset(("discover request wait_request wait_offer gather_offer gather_answer publish_offer "
    "publish_answer wait_answer apply_answer checking attach path inspect none unknown").split())
REASONS = frozenset(("carrier_lost phase_timeout ineligible context_changed network_unavailable transient "
    "rate_limited configuration invalid_document revoked unsupported internal wrong_resource invalid_adoption "
    "invalid_handoff invalid_pending unverified_resource missing_handoff stale_completion observed unknown").split())
HEALTH = frozenset("absent open suspect closing unknown".split())
CLOSE = frozenset("not_observed local_request callback_without_local_request callback_after_local_request unavailable".split())
ORDER = frozenset("not_observed owner_first native_first unknown".split())
OWNERS = frozenset("authorized pending_adoption unadopted unavailable unknown".split())
SCENARIOS = frozenset({"turn_tcp", "turn_tls", "impaired"})


def label(value, allowed):
    return type(value) is str and value in allowed


def carrier_target(value):
    fields = {"operation_id", "logical_session", "expected_physical",
              "expected_service_incarnation", "expected_profile_incarnation"}
    if type(value) is not dict or set(value) != fields:
        return None
    operation = value["operation_id"]
    if type(operation) is not str or len(operation) != 36:
        return None
    try:
        if str(UUID(operation)) != operation: return None
    except ValueError:
        return None
    for name in ("logical_session", "expected_physical"):
        if type(value[name]) is not str or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value[name]) is None:
            return None
    for name in ("expected_service_incarnation", "expected_profile_incarnation"):
        if type(value[name]) is not str or re.fullmatch(r"[a-f0-9]{32}", value[name]) is None:
            return None
    return dict(value)


def loss_fact(value, *, loss=False):
    if value is None: return None
    fields = {"event": EVENTS, "phase": PHASES, "reason": REASONS}
    if loss: fields["prior_health"] = HEALTH
    if type(value) is not dict or set(value) != set(fields) or any(
            not label(value[name], allowed) for name, allowed in fields.items()):
        raise ValueError("Invalid carrier observation")
    return dict(value)


def carrier_cause(value):
    fields = {"availability", "owner_loss", "suspect_precursor", "native_close", "order"}
    if (type(value) is not dict or set(value) != fields
            or not label(value["availability"], {"selected", "unavailable"})
            or not label(value["native_close"], CLOSE) or not label(value["order"], ORDER)):
        return None
    try:
        result = {**value, "owner_loss": loss_fact(value["owner_loss"], loss=True),
                  "suspect_precursor": loss_fact(value["suspect_precursor"])}
    except ValueError:
        return None
    if value["availability"] == "unavailable":
        if (value["owner_loss"] is not None or value["suspect_precursor"] is not None
                or value["native_close"] != "unavailable" or value["order"] != "unknown"):
            return None
    else:
        if value["native_close"] == "unavailable": return None
        owner, native = value["owner_loss"] is not None, value["native_close"] != "not_observed"
        allowed = {"owner_first", "native_first"} if owner and native else {"unknown"} if owner or native else {"not_observed"}
        if value["order"] not in allowed: return None
    return result


def unavailable_cause():
    return {"availability": "unavailable", "owner_loss": None, "suspect_precursor": None,
            "native_close": "unavailable", "order": "unknown"}


def bounded_count(value):
    return min(value, 16), value > 16


def inventory_fact(inventory, target):
    rows = inventory["resources"]
    matching = [row for row in rows if row["logical_session"] == target["logical_session"]]
    count, capped = bounded_count(len(matching))
    total, total_capped = bounded_count(len(rows))
    row = matching[0] if len(matching) == 1 else {}
    owner, adopted = row.get("owner_state"), row.get("adopted")
    same_service = inventory.get("service_incarnation") == target["expected_service_incarnation"]
    same_profile = inventory.get("profile_incarnation") == target["expected_profile_incarnation"]
    cause = carrier_cause(inventory.get("carrier_observation")) if same_service and same_profile else None
    return {"matching_resources": count, "matching_capped": capped, "total_resources": total,
        "total_capped": total_capped, "owner_state": owner if label(owner, OWNERS) else "unknown",
        "adopted": adopted if type(adopted) is bool else None,
        "expected_physical": row.get("physical_resource") == target["expected_physical"] if row else None,
        "same_service": same_service, "same_profile": same_profile,
        "carrier_observation": cause or unavailable_cause()}


class FinalCarrierObservation:
    def __init__(self, target, scenario, phase, started):
        self.target = target
        self.scenario, self.phase, self.started = scenario, phase, started
        self.first = self.last = None
        self.polls = self.transitions = 0
        self.polls_capped = self.transitions_capped = False
        self.first_missing_ms = None

    def matches(self, phase, pairing, logical, scenario):
        return (phase == self.phase and pairing == self.target["operation_id"]
                and logical == self.target["logical_session"] and scenario == self.scenario)

    def observe(self, inventory, now):
        value = inventory_fact(inventory, self.target)
        if self.polls == 512: self.polls_capped = True
        else: self.polls += 1
        if self.first is None: self.first = value
        if self.last is not None and value != self.last:
            if self.transitions == 512: self.transitions_capped = True
            else: self.transitions += 1
        self.last = value
        if value["matching_resources"] == 0 and self.first_missing_ms is None:
            self.first_missing_ms = min(90000, max(0, int((now - self.started) * 1000)))

    def snapshot(self):
        if not self.polls: return None
        # Reproject retained facts, rather than allowing arbitrary dictionaries
        # or private target fields to reach the failure report.
        return final_carrier_snapshot({"scenario": self.scenario, "polls": self.polls,
            "polls_capped": self.polls_capped, "transitions": self.transitions,
            "transitions_capped": self.transitions_capped, "first_missing_ms": self.first_missing_ms,
            "first": self.first, "last": self.last})


def checked_inventory_fact(value):
    fields = {"matching_resources", "matching_capped", "total_resources", "total_capped", "owner_state",
              "adopted", "expected_physical", "same_service", "same_profile", "carrier_observation"}
    if type(value) is not dict or set(value) != fields: return None
    for count, capped in (("matching_resources", "matching_capped"), ("total_resources", "total_capped")):
        if (type(value[count]) is not int or not 0 <= value[count] <= 16 or type(value[capped]) is not bool
                or (value[capped] and value[count] != 16)): return None
    if value["matching_resources"] > value["total_resources"]: return None
    if not label(value["owner_state"], OWNERS): return None
    if any(value[name] is not None and type(value[name]) is not bool for name in ("adopted", "expected_physical")):
        return None
    if any(type(value[name]) is not bool for name in ("same_service", "same_profile")): return None
    if value["matching_resources"] != 1 and any(
            value[name] != expected for name, expected in (("owner_state", "unknown"), ("adopted", None), ("expected_physical", None))):
        return None
    cause = carrier_cause(value["carrier_observation"])
    if (cause is not None and cause["availability"] == "selected"
            and not (value["same_service"] and value["same_profile"])):
        return None
    return {**value, "carrier_observation": cause} if cause is not None else None


def final_carrier_snapshot(value):
    fields = {"scenario", "polls", "polls_capped", "transitions", "transitions_capped", "first_missing_ms", "first", "last"}
    if type(value) is not dict or set(value) != fields or not label(value["scenario"], SCENARIOS): return None
    for count, capped in (("polls", "polls_capped"), ("transitions", "transitions_capped")):
        if (type(value[count]) is not int or not 0 <= value[count] <= 512 or type(value[capped]) is not bool
                or (value[capped] and value[count] != 512)): return None
    if not value["polls"]: return None
    missing = value["first_missing_ms"]
    if missing is not None and (type(missing) is not int or not 0 <= missing <= 90000): return None
    first, last = checked_inventory_fact(value["first"]), checked_inventory_fact(value["last"])
    return {**value, "first": first, "last": last} if first is not None and last is not None else None
