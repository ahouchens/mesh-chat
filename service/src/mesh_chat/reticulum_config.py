from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .invitations import validate_hints

INTERFACE_NAME = re.compile(r"^[A-Za-z0-9_. -]{1,64}$")

# A signed invitation gives the recipient an explicit TCP route to the peer.
# Reticulum otherwise keeps whichever equal-hop announce arrived first. On
# mobile that can leave a destination pinned to an AutoInterface path which was
# briefly usable during approval but cannot carry the later chat packet, even
# while the signed TCP connection is online. Give only outbound, explicitly
# configured TCP peers the minimum higher route gravity so an announce received
# over that explicitly signed hint replaces the earlier nearby-discovery route.
# The route is still authenticated by the destination's Reticulum identity;
# merely opening the TCP socket does not authenticate its peer. Keeping this at
# one also avoids unexpectedly outranking future interfaces with stronger
# operator-selected preferences.
#
# Do not apply this to the wildcard LAN listener: it accepts bounded on-link
# connections before Mesh Chat authenticates an application payload. Raising
# its gravity would let an unauthenticated LAN client attract preferred paths.
SIGNED_TCP_ROUTE_GRAVITY = 1


@dataclass(slots=True)
class NetworkSettings:
    nearby_discovery: bool = True
    lan_fallback: bool = True
    lan_listener_port: int | None = None
    allowed_interfaces: list[str] = field(default_factory=list)
    tcp_clients: list[dict[str, Any]] = field(default_factory=list)
    tcp_listener: dict[str, Any] | None = None
    help_route: bool = False
    store_for_offline: bool = False
    approved_propagation_nodes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "NetworkSettings":
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise ValidationError("Network settings must be an object")
        allowed_keys = {
            "nearby_discovery",
            "lan_fallback",
            "lan_listener_port",
            "allowed_interfaces",
            "tcp_clients",
            "tcp_listener",
            "help_route",
            "store_for_offline",
            "approved_propagation_nodes",
        }
        if set(value) - allowed_keys:
            raise ValidationError("Network settings contain unsupported fields")

        interfaces = value.get("allowed_interfaces", [])
        if not isinstance(interfaces, list) or len(interfaces) > 32:
            raise ValidationError("Allowed interfaces are invalid")
        for name in interfaces:
            if not isinstance(name, str) or not INTERFACE_NAME.fullmatch(name):
                raise ValidationError("Allowed interface name is invalid")

        clients = validate_hints(value.get("tcp_clients", []))
        lan_listener_port = value.get("lan_listener_port")
        if lan_listener_port is not None and (
            isinstance(lan_listener_port, bool)
            or not isinstance(lan_listener_port, int)
            or not 1 <= lan_listener_port <= 65535
        ):
            raise ValidationError("LAN listener port is invalid")
        listener = value.get("tcp_listener")
        if listener is not None:
            if not isinstance(listener, dict) or set(listener) != {"host", "port"}:
                raise ValidationError("TCP listener is invalid")
            # Reuse the strict host and port checks, then remove the client type.
            checked = validate_hints([{"type": "tcp", **listener}])[0]
            listener = {"host": checked["host"], "port": checked["port"]}

        nodes = value.get("approved_propagation_nodes", [])
        if not isinstance(nodes, list) or len(nodes) > 16:
            raise ValidationError("Propagation-node allowlist is invalid")
        for node in nodes:
            try:
                raw = bytes.fromhex(node)
            except (TypeError, ValueError) as exc:
                raise ValidationError("Propagation-node address is invalid") from exc
            if len(raw) != 16:
                raise ValidationError("Propagation-node address is invalid")

        def boolean(name: str, default: bool) -> bool:
            result = value.get(name, default)
            if not isinstance(result, bool):
                raise ValidationError(f"{name} must be boolean")
            return result

        return cls(
            nearby_discovery=boolean("nearby_discovery", True),
            lan_fallback=boolean("lan_fallback", True),
            lan_listener_port=lan_listener_port,
            allowed_interfaces=list(interfaces),
            tcp_clients=clients,
            tcp_listener=listener,
            help_route=boolean("help_route", False),
            store_for_offline=boolean("store_for_offline", False),
            approved_propagation_nodes=list(nodes),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "nearby_discovery": self.nearby_discovery,
            "lan_fallback": self.lan_fallback,
            "lan_listener_port": self.lan_listener_port,
            "allowed_interfaces": self.allowed_interfaces,
            "tcp_clients": self.tcp_clients,
            "tcp_listener": self.tcp_listener,
            "help_route": self.help_route,
            "store_for_offline": self.store_for_offline,
            "approved_propagation_nodes": self.approved_propagation_nodes,
        }


def write_config(config_dir: Path, settings: NetworkSettings) -> Path:
    config_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "[reticulum]",
        f"enable_transport = {'Yes' if settings.help_route else 'No'}",
        "share_instance = No",
        "discover_interfaces = No",
        "enable_remote_management = No",
        "respond_to_probes = No",
        "panic_on_interface_error = No",
        "",
        "[logging]",
        "loglevel = 1",
        "logtimestamps = No",
        "",
        "[interfaces]",
    ]
    if settings.nearby_discovery:
        lines.extend(
            [
                "  [[Nearby devices]]",
                "    type = AutoInterface",
                "    enabled = Yes",
                "    discovery_scope = link",
                "    multicast_address_type = temporary",
            ]
        )
        if settings.allowed_interfaces:
            lines.append(f"    devices = {','.join(settings.allowed_interfaces)}")

    for index, hint in enumerate(settings.tcp_clients):
        lines.extend(
            [
                f"  [[Private TCP peer {index + 1}]]",
                "    type = TCPClientInterface",
                "    enabled = Yes",
                f"    target_host = {hint['host']}",
                f"    target_port = {hint['port']}",
                "    connect_timeout = 5",
                f"    gravity = {SIGNED_TCP_ROUTE_GRAVITY}",
            ]
        )

    if settings.lan_fallback and settings.lan_listener_port is not None:
        lines.extend(
            [
                "  [[Mesh Chat LAN fallback]]",
                "    type = TCPServerInterface",
                "    enabled = Yes",
                "    listen_ip = 0.0.0.0",
                f"    listen_port = {settings.lan_listener_port}",
                "    ingress_control = Yes",
            ]
        )

    if settings.tcp_listener:
        lines.extend(
            [
                "  [[Private TCP listener]]",
                "    type = TCPServerInterface",
                "    enabled = Yes",
                f"    listen_ip = {settings.tcp_listener['host']}",
                f"    listen_port = {settings.tcp_listener['port']}",
            ]
        )

    if (
        not settings.nearby_discovery
        and not settings.tcp_clients
        and not settings.tcp_listener
        and not (settings.lan_fallback and settings.lan_listener_port is not None)
    ):
        lines.extend(
            [
                "  [[No network interfaces configured]]",
                "    type = AutoInterface",
                "    enabled = No",
            ]
        )

    config_path = config_dir / "config"
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return config_path
