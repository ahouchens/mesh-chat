"""Strict cold-start inventory comparisons and redacted failure progress."""

import re


STAGES = frozenset({"restart", "identity_receipt", "readiness", "exchange", "exact_path", "accounting", "evidence"})
RELATIONS = frozenset({"unread", "retired", "current", "changed", "invalid", "unavailable", "deadline"})
OWNERS = frozenset({"authorized", "unadopted", "pending_adoption", "pending_negotiation", "unavailable"})


def _inventory(value):
    if type(value) is not dict or value.get("v") != 1 or type(value.get("v")) is not int:
        return False
    if value.get("qualification_only") is not True:
        return False
    for name in ("service_incarnation", "profile_incarnation"):
        if type(value.get(name)) is not str or re.fullmatch(r"[a-f0-9]{32}", value[name]) is None:
            return False
    rows = value.get("resources")
    if type(rows) is not list or len(rows) > 256:
        return False
    logical, physical = set(), set()
    for row in rows:
        if type(row) is not dict or type(row.get("adopted")) is not bool:
            return False
        if type(row.get("owner_state")) is not str or row["owner_state"] not in OWNERS:
            return False
        for name in ("logical_session", "physical_resource"):
            if type(row.get(name)) is not str or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", row[name]) is None:
                return False
        if row["logical_session"] in logical or row["physical_resource"] in physical:
            return False
        logical.add(row["logical_session"])
        physical.add(row["physical_resource"])
    return True


def inventory_relation(before, resource, after):
    """Only positive same-incarnation absence permits fresh discovery."""
    if not _inventory(before) or not _inventory(after) or type(resource) is not dict:
        return "invalid"
    if resource not in before["resources"] or resource.get("owner_state") != "authorized" or resource.get("adopted") is not True:
        return "invalid"
    if any(before[name] != after[name] for name in ("service_incarnation", "profile_incarnation")):
        return "changed"
    if any(row["physical_resource"] == resource["physical_resource"] for row in after["resources"]):
        return "current"
    return "retired"


def failure_snapshot(value):
    fields = {"iteration", "completed", "stage", "restarted", "path_recheck", "retired_reads", "retired_reads_capped"}
    if type(value) is not dict or set(value) != fields:
        return None
    if (type(value["iteration"]) is not int or not 1 <= value["iteration"] <= 100
            or type(value["completed"]) is not int or value["completed"] != value["iteration"] - 1
            or type(value["stage"]) is not str or value["stage"] not in STAGES
            or type(value["restarted"]) is not bool
            or type(value["path_recheck"]) is not str or value["path_recheck"] not in RELATIONS
            or type(value["retired_reads"]) is not int or not 0 <= value["retired_reads"] <= 512
            or type(value["retired_reads_capped"]) is not bool
            or value["retired_reads_capped"] and value["retired_reads"] != 512):
        return None
    return dict(value)
