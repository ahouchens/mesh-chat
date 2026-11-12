"""Private, fail-closed route admission for a disposable Android emulator link."""

import re


class LinkScopeError(ValueError):
    REASONS = frozenset({"route_unavailable", "alternate_link", "unsupported_route",
        "unsupported_policy", "conflicting_qdisc", "capability_unavailable"})

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
    return (command("ip", "-o", "link", "show"),
        command("ip", "-4", "route", "show", "table", "all"),
        command("ip", "-6", "route", "show", "table", "all"),
        command("ip", "-4", "rule", "show"),
        command("ip", "-6", "rule", "show"))
