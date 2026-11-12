"""Private, fail-closed route admission for a disposable Android emulator link."""

import json
import re
import shlex


class LinkScopeError(ValueError):
    REASONS = frozenset({"route_unavailable", "alternate_link", "unsupported_route",
        "unsupported_policy", "conflicting_qdisc", "capability_unavailable",
        "initial_inventory_unavailable", "initial_kind_unproven", "initial_stack_unsupported",
        "initial_link_limit", "recheck_link_set_changed", "recheck_link_identity_changed",
        "recheck_uncovered_route", "collision_ifb", "collision_ingress_filter",
        "profile_egress_mismatch", "profile_ingress_mismatch", "profile_counter_regression",
        "guard_capability_unavailable", "guard_chain_collision", "guard_jump_collision",
        "guard_install_incomplete", "guard_current_mismatch", "guard_input_path_unverified",
        "guard_input_drop", "guard_output_drop", "group_inventory_unavailable",
        "group_policy_conflict", "group_collision", "group_capability_unavailable",
        "group_assignment_mismatch", "recheck_group_identity_changed", "group_restore_incomplete"})

    def __init__(self, reason):
        if reason not in self.REASONS:
            raise ValueError("Unknown link-scope failure")
        self.reason = reason
        super().__init__("Disposable emulator link admission failed: " + reason)


def link_names(links):
    names = {}
    if not links.strip():
        raise LinkScopeError("route_unavailable")
    for line in links.splitlines():
        match = re.fullmatch(r"\s*[0-9]+:\s+([A-Za-z0-9_.-]{1,15})(?:@[^:]+)?:\s+<([^>]*)>.*", line)
        if match is None or match[1] in names:
            raise LinkScopeError("unsupported_route")
        names[match[1]] = set(match[2].split(","))
    if "lo" not in names:
        raise LinkScopeError("route_unavailable")
    return names


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise LinkScopeError("initial_inventory_unavailable")
        result[key] = value
    return result


def _numeric_group(value):
    # Android can expose the high bit as a signed negative sysfs value.
    if type(value) is int and 0 <= value <= 0x7fffffff:
        return value
    if value == "default":
        return 0
    if type(value) is str and re.fullmatch(r"[0-9]{1,10}", value):
        result = int(value)
        if result <= 0x7fffffff:
            return result
    raise LinkScopeError("group_inventory_unavailable")


def covered_links(links, route4, route6, rule4, rule6, metadata, *, owned_ifbs=()):
    """Admit a bounded complete link set, including explicitly denied sinks."""
    try:
        raw = json.loads(links, object_pairs_hook=_unique_object)
    except (TypeError, ValueError) as error:
        raise LinkScopeError("initial_inventory_unavailable") from error
    if type(raw) is not list or not 1 <= len(raw) <= 32 or type(metadata) is not dict:
        raise LinkScopeError("initial_inventory_unavailable")
    parsed = {}
    for item in raw:
        if (type(item) is not dict or type(item.get("ifindex")) is not int
                or item["ifindex"] <= 0 or type(item.get("ifname")) is not str
                or re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", item["ifname"]) is None
                or type(item.get("flags")) is not list
                or any(type(flag) is not str for flag in item["flags"])
                or type(item.get("link_type")) is not str):
            raise LinkScopeError("initial_inventory_unavailable")
        name = item["ifname"]
        if name in parsed or any(value["ifindex"] == item["ifindex"] for value in parsed.values()):
            raise LinkScopeError("initial_inventory_unavailable")
        kind_data = item.get("linkinfo", {})
        if type(kind_data) is not dict:
            raise LinkScopeError("initial_kind_unproven")
        if "UP" in item["flags"] and name != "lo" and set(kind_data) - {"info_kind"}:
            raise LinkScopeError("initial_kind_unproven")
        kind = kind_data.get("info_kind")
        group = _numeric_group(item.get("group"))
        details = metadata.get(name)
        if (type(details) is not tuple or len(details) != 5
                or any(type(number) is not int for number in details[:3] + details[4:])
                or type(details[3]) is not bool or details[1] != item["ifindex"]
                or details[4] != group):
            raise LinkScopeError("group_inventory_unavailable")
        parsed[name] = {"name": name, "ifindex": item["ifindex"], "group": group,
                        "kind": kind, "flags": frozenset(item["flags"]),
                        "link_type": item["link_type"], "master": item.get("master"),
                        "link_index": item.get("link_index")}
    if "lo" not in parsed or "UP" not in parsed["lo"]["flags"]:
        raise LinkScopeError("route_unavailable")
    if any(name not in parsed for name in owned_ifbs):
        raise LinkScopeError("collision_ifb")
    external, sinks = [], []
    for name, item in parsed.items():
        if name == "lo" or name in owned_ifbs or "UP" not in item["flags"]:
            continue
        details = metadata.get(name)
        if (type(details) is not tuple or len(details) != 5
                or any(type(number) is not int for number in details[:3])
                or type(details[3]) is not bool or details[0] != 1
                or details[1] != item["ifindex"]):
            raise LinkScopeError("initial_kind_unproven")
        if (details[2] != item["ifindex"] or details[3]
                or item["master"] is not None
                or item["link_index"] not in (None, item["ifindex"])):
            raise LinkScopeError("initial_stack_unsupported")
        if item["kind"] == "dummy":
            sinks.append(item)
        elif item["link_type"] == "ether" and item["kind"] in (None, "virt_wifi"):
            external.append(item)
        else:
            raise LinkScopeError("initial_stack_unsupported")
    if not 1 <= len(external) + len(sinks) <= 4:
        raise LinkScopeError("initial_link_limit")
    allowed = {item["name"] for item in external}
    denied = {item["name"] for item in sinks}
    routed = set()
    for rules in (rule4, rule6):
        if not rules.strip():
            raise LinkScopeError("route_unavailable")
        for line in rules.splitlines():
            if (re.fullmatch(r"\s*[0-9]+:\s+from\s+.+", line) is None
                    or not re.search(r"\b(?:lookup|table|unreachable|prohibit|blackhole)\b", line)
                    or re.search(r"\b(?:goto|nat|l3mdev|suppress_prefixlength|suppress_ifgroup)\b", line)):
                raise LinkScopeError("unsupported_policy")
    for routes in (route4, route6):
        for line in routes.splitlines():
            parts = line.split()
            if not parts or parts[0] in {"unreachable", "blackhole", "prohibit", "throw"}:
                continue
            if parts.count("dev") != 1 or parts.index("dev") + 1 >= len(parts):
                raise LinkScopeError("unsupported_route")
            device = parts[parts.index("dev") + 1]
            if device not in parsed or (device != "lo" and device not in allowed | denied):
                raise LinkScopeError("unsupported_route")
            if device in allowed and parts[0] not in {"local", "broadcast", "anycast"}:
                routed.add(device)
    if not routed:
        raise LinkScopeError("route_unavailable")
    return {"external": tuple(external), "sinks": tuple(sinks), "all": parsed}


def link_metadata(command, links):
    """Read the three fixed sysfs integers and stack links for validated names."""
    try:
        raw = json.loads(links, object_pairs_hook=_unique_object)
    except (TypeError, ValueError) as error:
        raise LinkScopeError("initial_inventory_unavailable") from error
    if type(raw) is not list or len(raw) > 32:
        raise LinkScopeError("initial_inventory_unavailable")
    result = {}
    for item in raw:
        if type(item) is not dict or type(item.get("ifname")) is not str:
            raise LinkScopeError("initial_inventory_unavailable")
        name = item["ifname"]
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", name) is None or name in result:
            raise LinkScopeError("initial_inventory_unavailable")
        info = item.get("linkinfo")
        root = "/sys/class/net/" + name
        try:
            numbers = tuple(int(command("cat", root + "/" + field))
                            for field in ("type", "ifindex", "iflink"))
            group = int(command("cat", root + "/netdev_group"))
            script = ("for p in " + root + "/master " + root + "/lower_* "
                      + root + "/upper_*; do if [ -e \"$p\" ]; then echo 1; exit; fi; done; echo 0")
            stacked = command("sh", "-c", shlex.quote(script))
        except Exception as error:
            raise LinkScopeError("initial_kind_unproven") from error
        if not 0 <= group <= 0x7fffffff:
            raise LinkScopeError("group_inventory_unavailable")
        if stacked not in {"0", "1"}:
            raise LinkScopeError("initial_kind_unproven")
        result[name] = (*numbers, stacked == "1", group)
    return result


def covered_link(links, route4, route6, rule4, rule6, *, owned_ifb=None):
    names = link_names(links)
    for rules in (rule4, rule6):
        if not rules.strip():
            raise LinkScopeError("route_unavailable")
        for line in rules.splitlines():
            if (re.fullmatch(r"\s*[0-9]+:\s+from\s+.+", line) is None
                    or not re.search(r"\b(?:lookup|table|unreachable|prohibit|blackhole)\b", line)
                    or re.search(r"\b(?:goto|nat|l3mdev|suppress_prefixlength|suppress_ifgroup)\b", line)):
                raise LinkScopeError("unsupported_policy")
    devices = set()
    for routes in (route4, route6):
        for line in routes.splitlines():
            parts = line.split()
            if not parts:
                continue
            if parts[0] in {"unreachable", "blackhole", "prohibit", "throw"}:
                continue
            if parts.count("dev") != 1 or parts.index("dev") + 1 >= len(parts):
                raise LinkScopeError("unsupported_route")
            device = parts[parts.index("dev") + 1]
            if device not in names:
                raise LinkScopeError("unsupported_route")
            if device != "lo" and parts[0] not in {"local", "broadcast", "anycast"}:
                devices.add(device)
    if not devices:
        raise LinkScopeError("route_unavailable")
    if len(devices) != 1:
        raise LinkScopeError("alternate_link")
    device = next(iter(devices))
    if "UP" not in names[device]:
        raise LinkScopeError("route_unavailable")
    for name, flags in names.items():
        if name != "lo" and name != device and name != owned_ifb and "UP" in flags:
            raise LinkScopeError("alternate_link")
    return device


def snapshot(command):
    """Read both families and all tables; never infer coverage from one lookup."""
    return (command("ip", "-j", "-d", "link", "show"),
        command("ip", "-4", "route", "show", "table", "all"),
        command("ip", "-6", "route", "show", "table", "all"),
        command("ip", "-4", "rule", "show"),
        command("ip", "-6", "rule", "show"))
