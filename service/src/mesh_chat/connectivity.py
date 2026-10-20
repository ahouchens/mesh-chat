from __future__ import annotations

import http.client
import ipaddress
import json
import os
import platform
import random
import secrets
import socket
import struct
import subprocess
import time
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

import RNS

from .remote import address_is_public

SSDP_ADDRESS = ("239.255.255.250", 1900)
GATEWAY_PORT = 5351
DEFAULT_MAPPING_LIFETIME = 2 * 60 * 60
MAX_HTTP_BYTES = 256 * 1024
UPNP_SERVICES = (
    "urn:schemas-upnp-org:service:WANIPConnection:2",
    "urn:schemas-upnp-org:service:WANIPConnection:1",
    "urn:schemas-upnp-org:service:WANPPPConnection:1",
)
UPNP_IPV6_FIREWALL_SERVICE = "urn:schemas-upnp-org:service:WANIPv6FirewallControl:1"
MAPPING_RETRY_DELAYS = (0.25, 0.5, 1.0, 2.0)

DIAGNOSTIC_PHASES = {
    "precondition", "ipv6", "upnp", "nat_pmp", "pcp", "firewall", "listener"
}
DIAGNOSTIC_RESULTS = {
    "available", "unavailable", "blocked", "unsupported", "prepared_unverified"
}
DIAGNOSTIC_REASONS = {
    "ready_to_prepare", "no_default_route", "no_global_ipv4", "no_global_ipv6",
    "upnp_no_discovery", "upnp_wan_private", "upnp_wan_shared",
    "upnp_mapping_denied", "upnp_unsupported_lease", "nat_pmp_no_response",
    "nat_pmp_mapping_denied", "pcp_no_response", "pcp_mapping_denied",
    "upstream_nat_detected", "listener_bind_failed", "windows_firewall_blocked",
    "windows_firewall_permission_required", "firewall_check_unsupported", "session_limit",
    "direct_public_ipv4", "global_ipv6_available", "mapping_prepared",
    "router_state_changed", "manual_setup_required",
}
DIAGNOSTIC_ACTIONS = {
    "retry", "continue", "prepare_direct", "share_invitation",
    "wait_for_recipient", "connect_to_internet", "try_router_mapping",
    "try_another_method", "check_host_firewall", "check_active_network_profile",
    "configure_firewall_after_prepare", "follow_guided_firewall_instructions",
    "use_ipv6_firewall_instructions", "configure_upstream_router_or_bridge_mode",
    "contact_provider_or_use_approved_access_point",
    "set_up_manual_forward_or_choose_explicit_fallback",
    "stop_an_active_invitation", "retry_or_check_firewall", "restart_app",
}


class ConnectivityError(OSError):
    """A local-network failure represented only by an allowlisted reason."""

    def __init__(
        self, phase: str, reason: str, *, result: str = "unavailable",
        recommended_action: str = "retry",
    ) -> None:
        self.phase = phase if phase in DIAGNOSTIC_PHASES else "precondition"
        self.reason = reason if reason in DIAGNOSTIC_REASONS else "no_default_route"
        self.result = result if result in DIAGNOSTIC_RESULTS else "unavailable"
        self.recommended_action = (
            recommended_action if recommended_action in DIAGNOSTIC_ACTIONS else "retry"
        )
        super().__init__(self.reason)

    def diagnostic(self) -> dict[str, str]:
        return diagnostic_step(
            self.phase, self.result, self.reason, self.recommended_action
        )


def diagnostic_step(
    phase: str, result: str, reason: str, recommended_action: str
) -> dict[str, str]:
    return {
        "phase": phase if phase in DIAGNOSTIC_PHASES else "precondition",
        "result": result if result in DIAGNOSTIC_RESULTS else "unavailable",
        "reason": reason if reason in DIAGNOSTIC_REASONS else "no_default_route",
        "recommended_action": (
            recommended_action if recommended_action in DIAGNOSTIC_ACTIONS else "retry"
        ),
    }


@dataclass(frozen=True, slots=True)
class RouteInfo:
    family: int
    interface: str
    gateway: str | None
    local_address: str | None
    metric: int = 0


@dataclass(frozen=True, slots=True)
class MappingResult:
    method: str
    external_host: str
    external_port: int
    internal_host: str
    internal_port: int
    lifetime: int
    cleanup: dict[str, Any]
    protocol: str = "tcp"

    def __post_init__(self) -> None:
        _mapping_protocol(self.protocol)

    def endpoint(self) -> dict[str, Any]:
        if self.protocol != "tcp":
            raise ValueError("UDP mappings cannot be used as legacy TCP invitation endpoints")
        return {"host": self.external_host, "port": self.external_port, "path": self.method}

    def record(self) -> dict[str, Any]:
        return {
            "method": self.method, "external_host": self.external_host,
            "external_port": self.external_port, "internal_host": self.internal_host,
            "internal_port": self.internal_port, "lifetime": self.lifetime,
            "cleanup": dict(self.cleanup), "protocol": self.protocol,
        }


def _mapping_protocol(protocol: str) -> int:
    if protocol not in ("tcp", "udp"):
        raise ValueError("Mapping protocol must be tcp or udp")
    return 6 if protocol == "tcp" else 17


def classify_address(value: str) -> str:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return "invalid"
    if address.is_loopback:
        return "loopback"
    if address.is_link_local:
        return "link_local"
    if address.is_multicast:
        return "multicast"
    if address.is_unspecified:
        return "unspecified"
    if isinstance(address, ipaddress.IPv4Address):
        if address in ipaddress.ip_network("100.64.0.0/10"):
            return "shared"
        if any(address in network for network in (
            ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
        )):
            return "rfc1918"
        if address.is_global:
            return "public_ipv4"
    else:
        if address in ipaddress.ip_network("fc00::/7"):
            return "ula"
        if address.is_global:
            return "public_ipv6"
    if address.is_reserved:
        return "reserved"
    if address.is_private:
        return "private"
    return "non_public"


def _interface_addresses(rns_module: Any = RNS) -> dict[str, list[dict[str, Any]]]:
    values: dict[str, list[dict[str, Any]]] = {}
    try:
        netinfo = rns_module.Interfaces.netinfo
        for name in netinfo.interfaces():
            entries: list[dict[str, Any]] = []
            by_family = netinfo.ifaddresses(name)
            for family in (netinfo.AF_INET, netinfo.AF_INET6):
                for item in by_family.get(family, []):
                    raw = str(item.get("addr", "")).split("%", 1)[0]
                    try:
                        normalized = ipaddress.ip_address(raw).compressed
                    except ValueError:
                        continue
                    entries.append({**dict(item), "family": family, "address": normalized})
            values[str(name)] = entries
    except Exception:
        return {}
    return values


def _windows_interface_addresses(
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[tuple[int, str], list[str]]:
    """Resolve interface addresses by Windows InterfaceIndex.

    Reticulum's netinfo may expose GUIDs while Get-NetRoute reports friendly
    aliases such as ``Wi-Fi``. The index is the stable join key.
    """
    command = [
        "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
        "$ErrorActionPreference='Stop'; Get-NetIPAddress -ErrorAction SilentlyContinue "
        "| Select-Object InterfaceIndex,AddressFamily,IPAddress "
        "| ConvertTo-Json -Compress",
    ]
    try:
        completed = runner(
            command, capture_output=True, text=True, timeout=3, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode or not completed.stdout.strip():
            return {}
        parsed = json.loads(completed.stdout)
        rows = parsed if isinstance(parsed, list) else [parsed]
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return {}
    values: dict[tuple[int, str], list[str]] = {}
    for row in rows:
        try:
            index = int(row["InterfaceIndex"])
            family_value = str(row.get("AddressFamily", "")).strip().lower()
            family = "ipv6" if family_value in {"23", "ipv6", "internetworkv6"} or "ipv6" in family_value else "ipv4"
            address = str(row.get("IPAddress", "")).split("%", 1)[0]
            kind = classify_address(address)
            if kind not in {"public_ipv4", "public_ipv6", "rfc1918", "shared"}:
                continue
            values.setdefault((index, family), []).append(ipaddress.ip_address(address).compressed)
        except (KeyError, TypeError, ValueError):
            continue
    priority = {"public_ipv4": 0, "public_ipv6": 0, "rfc1918": 1, "shared": 2}
    for key in values:
        values[key].sort(key=lambda item: priority.get(classify_address(item), 3))
    return values


def _windows_default_routes(
    interfaces: dict[str, list[dict[str, Any]]],
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[RouteInfo]:
    command = [
        "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
        "$ErrorActionPreference='Stop'; Get-NetRoute "
        "| Where-Object {$_.DestinationPrefix -in @('0.0.0.0/0','::/0') -and $_.State -eq 'Alive'} "
        "| Sort-Object RouteMetric,InterfaceMetric "
        "| Select-Object AddressFamily,InterfaceAlias,InterfaceIndex,NextHop,RouteMetric,InterfaceMetric "
        "| ConvertTo-Json -Compress",
    ]
    try:
        completed = runner(
            command, capture_output=True, text=True, timeout=3, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode or not completed.stdout.strip():
            return []
        parsed = json.loads(completed.stdout)
        rows = parsed if isinstance(parsed, list) else [parsed]
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []
    routes: list[RouteInfo] = []
    by_index: dict[tuple[int, str], list[str]] | None = None
    for row in rows:
        try:
            family_value = str(row["AddressFamily"]).strip().lower()
            family = (
                socket.AF_INET6
                if family_value in {"23", "ipv6", "internetworkv6"} or "ipv6" in family_value
                else socket.AF_INET
            )
            interface = str(row.get("InterfaceAlias", ""))
            interface_index = int(row["InterfaceIndex"]) if row.get("InterfaceIndex") is not None else None
            local = next((
                str(item["address"]) for item in interfaces.get(interface, [])
                if (family == socket.AF_INET6) == (":" in str(item["address"]))
                and classify_address(str(item["address"])) not in {"loopback", "link_local"}
            ), None)
            if local is None and interface_index is not None:
                if by_index is None:
                    by_index = _windows_interface_addresses(runner)
                candidates = by_index.get(
                    (interface_index, "ipv6" if family == socket.AF_INET6 else "ipv4"), []
                )
                local = candidates[0] if candidates else None
            raw_gateway = str(row.get("NextHop", ""))
            gateway = None if raw_gateway in {"", "0.0.0.0", "::"} else raw_gateway.split("%", 1)[0]
            metric = int(row.get("RouteMetric", 0)) + int(row.get("InterfaceMetric", 0))
            routes.append(RouteInfo(family, interface, gateway, local, metric))
        except (KeyError, TypeError, ValueError):
            continue
    return routes


def _linux_default_routes(interfaces: dict[str, list[dict[str, Any]]]) -> list[RouteInfo]:
    routes: list[RouteInfo] = []
    try:
        lines = Path("/proc/net/route").read_text(encoding="ascii").splitlines()[1:]
    except OSError:
        lines = []
    for line in lines:
        fields = line.split()
        if len(fields) < 8 or fields[1] != "00000000" or fields[7] != "00000000":
            continue
        try:
            if not int(fields[3], 16) & 1:
                continue
            gateway_value = socket.inet_ntoa(struct.pack("<I", int(fields[2], 16)))
            gateway = None if gateway_value == "0.0.0.0" else gateway_value
            interface = fields[0]
            local = next((
                str(item["address"]) for item in interfaces.get(interface, [])
                if ":" not in str(item["address"])
                and classify_address(str(item["address"])) not in {"loopback", "link_local"}
            ), None)
            routes.append(RouteInfo(socket.AF_INET, interface, gateway, local, int(fields[6])))
        except (OSError, ValueError):
            continue
    try:
        lines = Path("/proc/net/ipv6_route").read_text(encoding="ascii").splitlines()
    except OSError:
        lines = []
    for line in lines:
        fields = line.split()
        if len(fields) < 10 or fields[0] != "0" * 32 or fields[1] != "00000000":
            continue
        try:
            interface = fields[-1]
            gateway_value = ipaddress.IPv6Address(bytes.fromhex(fields[4])).compressed
            gateway = None if gateway_value == "::" else gateway_value
            local = next((
                str(item["address"]) for item in interfaces.get(interface, [])
                if classify_address(str(item["address"])) == "public_ipv6"
            ), None)
            routes.append(RouteInfo(socket.AF_INET6, interface, gateway, local, int(fields[5], 16)))
        except ValueError:
            continue
    return routes


def _bsd_default_route(
    family: int, interfaces: dict[str, list[dict[str, Any]]],
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> RouteInfo | None:
    command = ["route", "-n", "get", *( ["-inet6"] if family == socket.AF_INET6 else []), "default"]
    try:
        completed = runner(command, capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    fields: dict[str, str] = {}
    for line in completed.stdout.splitlines() if completed.returncode == 0 else []:
        name, separator, value = line.partition(":")
        if separator:
            fields[name.strip()] = value.strip().split("%", 1)[0]
    interface = fields.get("interface", "")
    local = next((
        str(item["address"]) for item in interfaces.get(interface, [])
        if (family == socket.AF_INET6) == (":" in str(item["address"]))
        and classify_address(str(item["address"])) not in {"loopback", "link_local"}
    ), None)
    return RouteInfo(family, interface, fields.get("gateway"), local) if interface else None


def default_routes(
    *, rns_module: Any = RNS, system: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[RouteInfo]:
    """Read actual OS default routes; never infer a gateway from subnet edges."""

    interfaces = _interface_addresses(rns_module)
    selected_system = (system or platform.system()).lower()
    if selected_system == "windows":
        routes = _windows_default_routes(interfaces, runner)
    elif selected_system in {"linux", "android"} or os.path.exists("/proc/net/route"):
        routes = _linux_default_routes(interfaces)
    else:
        routes = [route for route in (
            _bsd_default_route(socket.AF_INET, interfaces, runner),
            _bsd_default_route(socket.AF_INET6, interfaces, runner),
        ) if route is not None]
    filtered = [route for route in routes if route.interface and (
        route.local_address is None or classify_address(route.local_address)
        not in {"link_local", "loopback", "unspecified"}
    )]
    return sorted(filtered, key=lambda route: (route.family, route.metric, route.interface))


def _best_routes(routes: Iterable[RouteInfo], family: int) -> list[RouteInfo]:
    candidates = [route for route in routes if route.family == family]
    if not candidates:
        return []
    metric = min(route.metric for route in candidates)
    return [route for route in candidates if route.metric == metric]


def gateway_candidates(
    rns_module: Any = RNS, *, routes: list[RouteInfo] | None = None
) -> list[str]:
    selected = default_routes(rns_module=rns_module) if routes is None else routes
    candidates: list[str] = []
    for route in _best_routes(selected, socket.AF_INET):
        if route.gateway and route.gateway not in candidates:
            candidates.append(route.gateway)
    return candidates[:4]


def public_ipv4_addresses(*, routes: list[RouteInfo] | None = None) -> list[str]:
    selected = default_routes() if routes is None else routes
    return list(dict.fromkeys(
        route.local_address for route in _best_routes(selected, socket.AF_INET)
        if route.local_address and classify_address(route.local_address) == "public_ipv4"
    ))[:2]


def global_ipv6_addresses(
    *, limit: int = 2, rns_module: Any = RNS, routes: list[RouteInfo] | None = None,
) -> list[str]:
    selected = default_routes(rns_module=rns_module) if routes is None else routes
    active_names = {route.interface for route in _best_routes(selected, socket.AF_INET6)}
    interfaces = _interface_addresses(rns_module)
    candidates: list[tuple[int, int, str]] = []
    for name in active_names:
        for value in interfaces.get(name, []):
            raw = str(value.get("address", ""))
            if classify_address(raw) != "public_ipv6":
                continue
            flags = str(value.get("flags", "")).lower()
            if "deprecated" in flags or bool(value.get("deprecated", False)):
                continue
            try:
                valid = int(value.get("valid_lft", value.get("valid_lifetime", 86400)))
                preferred = int(value.get("preferred_lft", value.get("preferred_lifetime", valid)))
            except (TypeError, ValueError):
                valid = preferred = 86400
            if valid <= 120 or preferred <= 60:
                continue
            temporary = "temporary" in flags or bool(value.get("temporary", False))
            candidates.append((1 if temporary else 0, -preferred, raw))
    values: list[str] = []
    for _temporary, _lifetime, address in sorted(candidates):
        if address not in values:
            values.append(address)
        if len(values) >= limit:
            break
    return values


def select_available_port(*, ipv6: bool = False) -> int:
    family = socket.AF_INET6 if ipv6 else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        probe.bind(("::" if ipv6 else "0.0.0.0", 0))
        return int(probe.getsockname()[1])


def _local_address_for(remote_host: str, port: int) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect((remote_host, port))
        return str(probe.getsockname()[0])


def _bounded_http(
    method: str, url: str, *, body: bytes | None = None,
    headers: dict[str, str] | None = None, timeout: float,
    source_address: str | None = None,
) -> tuple[int, bytes]:
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.username or parsed.password or parsed.fragment:
        raise ConnectivityError("upnp", "upnp_no_discovery")
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
    except ValueError as exc:
        raise ConnectivityError("upnp", "upnp_no_discovery") from exc
    if not isinstance(address, ipaddress.IPv4Address) or classify_address(address.compressed) not in {
        "rfc1918", "shared", "link_local"
    }:
        raise ConnectivityError("upnp", "upnp_no_discovery")
    target = parsed.path or "/"
    if parsed.query:
        target += f"?{parsed.query}"
    connection = http.client.HTTPConnection(
        address.compressed, parsed.port or 80, timeout=timeout,
        source_address=(source_address, 0) if source_address else None,
    )
    try:
        connection.request(
            method, target, body=body,
            headers={"Host": parsed.netloc, "Connection": "close", **(headers or {})},
        )
        response = connection.getresponse()
        length = response.getheader("Content-Length")
        if length is not None:
            try:
                if int(length) > MAX_HTTP_BYTES:
                    raise ConnectivityError("upnp", "upnp_no_discovery")
            except ValueError as exc:
                raise ConnectivityError("upnp", "upnp_no_discovery") from exc
        payload = response.read(MAX_HTTP_BYTES + 1)
        if len(payload) > MAX_HTTP_BYTES:
            raise ConnectivityError("upnp", "upnp_no_discovery")
        return response.status, payload
    finally:
        connection.close()


def _ssdp_locations(local_address: str | float, timeout: float | None = None) -> list[str]:
    # The one-argument form is retained for older callers/tests, but discovery
    # is route-bound in production.
    if timeout is None:
        timeout = float(local_address)
        route = next(iter(_best_routes(default_routes(), socket.AF_INET)), None)
        if route is None or not route.local_address:
            return []
        local_address = route.local_address
    request = (
        "M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\nMX: 1\r\n'
        "ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n"
    ).encode("ascii")
    locations: list[str] = []
    deadline = time.monotonic() + timeout
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(str(local_address)))
        sock.bind((str(local_address), 0))
        sock.settimeout(min(0.25, timeout))
        sock.sendto(request, SSDP_ADDRESS)
        while time.monotonic() < deadline:
            try:
                payload, _source = sock.recvfrom(16 * 1024)
            except socket.timeout:
                continue
            except OSError:
                break
            text = payload.decode("iso-8859-1", errors="ignore")
            for line in text.splitlines()[1:]:
                name, separator, value = line.partition(":")
                if separator and name.strip().lower() == "location":
                    location = value.strip()
                    if location not in locations:
                        locations.append(location)
                    break
            if len(locations) >= 4:
                break
    return locations


def _upnp_services(
    location: str, timeout: float, *, source_address: str | None = None
) -> dict[str, str]:
    status, body = _bounded_http(
        "GET", location, timeout=timeout, source_address=source_address
    )
    if status != 200:
        raise ConnectivityError("upnp", "upnp_no_discovery")
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise ConnectivityError("upnp", "upnp_no_discovery") from exc
    services: dict[str, str] = {}
    for service in root.iter():
        if not service.tag.endswith("service"):
            continue
        service_type = next((
            (child.text or "").strip() for child in service
            if child.tag.endswith("serviceType")
        ), None)
        control_url = next((
            (child.text or "").strip() for child in service
            if child.tag.endswith("controlURL")
        ), None)
        if service_type and control_url:
            services[service_type] = urljoin(location, control_url)
    location_host = urlsplit(location).hostname
    for control in services.values():
        if urlsplit(control).hostname != location_host:
            raise ConnectivityError("upnp", "upnp_no_discovery")
    return services


def _upnp_service(
    location: str, timeout: float, *, source_address: str | None = None
) -> tuple[str, str]:
    services = _upnp_services(location, timeout, source_address=source_address)
    for service_type in UPNP_SERVICES:
        if service_type in services:
            return service_type, services[service_type]
    raise ConnectivityError("upnp", "upnp_no_discovery", result="unsupported")


def _soap_fault_reason(payload: bytes) -> str:
    try:
        root = ElementTree.fromstring(payload)
        code = next(((item.text or "").strip() for item in root.iter()
                     if item.tag.endswith("errorCode")), "")
    except ElementTree.ParseError:
        code = ""
    return "upnp_unsupported_lease" if code in {"725", "726"} else "upnp_mapping_denied"


def _soap(
    control_url: str, service_type: str, action: str, arguments: dict[str, str],
    *, timeout: float, source_address: str | None = None,
) -> bytes:
    params = "".join(f"<{name}>{escape(value)}</{name}>" for name, value in arguments.items())
    body = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        f'<s:Body><u:{action} xmlns:u="{service_type}">{params}'
        f"</u:{action}></s:Body></s:Envelope>"
    ).encode("utf-8")
    status, response = _bounded_http(
        "POST", control_url, body=body,
        headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": f'"{service_type}#{action}"',
            "Content-Length": str(len(body)),
        }, timeout=timeout, source_address=source_address,
    )
    if status != 200:
        raise ConnectivityError("upnp", _soap_fault_reason(response), result="blocked")
    return response


def _xml_value(payload: bytes, name: str) -> str:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise ConnectivityError("upnp", "upnp_no_discovery") from exc
    for element in root.iter():
        if element.tag.endswith(name) and element.text:
            return element.text.strip()
    raise ConnectivityError("upnp", "upnp_no_discovery")


def _upnp_uptime(
    control_url: str, service_type: str, *, timeout: float,
    source_address: str | None,
) -> int | None:
    try:
        return max(0, int(_xml_value(_soap(
            control_url, service_type, "GetStatusInfo", {}, timeout=timeout,
            source_address=source_address,
        ), "NewUptime")))
    except (ConnectivityError, TypeError, ValueError):
        return None


def _upnp_locations_by_route(routes: list[RouteInfo], timeout: float) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for route in _best_routes(routes, socket.AF_INET):
        if not route.local_address:
            continue
        try:
            for location in _ssdp_locations(route.local_address, timeout):
                if (route.local_address, location) not in found:
                    found.append((route.local_address, location))
        except OSError:
            continue
    return found[:8]


def _upnp_external(
    routes: list[RouteInfo], timeout: float
) -> tuple[str, str, str, str]:
    locations = _upnp_locations_by_route(routes, timeout)
    if not locations:
        raise ConnectivityError("upnp", "upnp_no_discovery", result="unsupported")
    last: ConnectivityError | None = None
    for local, location in locations:
        try:
            service_type, control_url = _upnp_service(location, timeout, source_address=local)
            external_host = ipaddress.ip_address(_xml_value(_soap(
                control_url, service_type, "GetExternalIPAddress", {}, timeout=timeout,
                source_address=local,
            ), "NewExternalIPAddress")).compressed
            classification = classify_address(external_host)
            if classification == "shared":
                raise ConnectivityError(
                    "upnp", "upnp_wan_shared", result="blocked",
                    recommended_action="contact_provider_or_use_approved_access_point",
                )
            if classification != "public_ipv4":
                raise ConnectivityError(
                    "upnp", "upnp_wan_private", result="blocked",
                    recommended_action="configure_upstream_router_or_bridge_mode",
                )
            return local, service_type, control_url, external_host
        except ConnectivityError as exc:
            last = exc
    raise last or ConnectivityError("upnp", "upnp_no_discovery")


def inspect_upnp(
    *, routes: list[RouteInfo] | None = None, timeout: float = 0.8
) -> dict[str, str]:
    _upnp_external(default_routes() if routes is None else routes, timeout)
    return diagnostic_step("upnp", "available", "ready_to_prepare", "prepare_direct")


def map_upnp(
    internal_port: int, *, lifetime: int = DEFAULT_MAPPING_LIFETIME,
    timeout: float = 1.1, description: str = "MeshChat participant invite",
    routes: list[RouteInfo] | None = None, preferred_external_port: int = 0,
    protocol: str = "tcp",
) -> MappingResult:
    _mapping_protocol(protocol)
    local, service_type, control_url, external_host = _upnp_external(
        default_routes() if routes is None else routes, timeout
    )
    if service_type.endswith(":2") and not preferred_external_port:
        try:
            payload = _soap(
                control_url, service_type, "AddAnyPortMapping", {
                    "NewRemoteHost": "", "NewExternalPort": "0", "NewProtocol": protocol.upper(),
                    "NewInternalPort": str(internal_port), "NewInternalClient": local,
                    "NewEnabled": "1", "NewPortMappingDescription": description[:48],
                    "NewLeaseDuration": str(lifetime),
                }, timeout=timeout, source_address=local,
            )
            reserved = int(_xml_value(payload, "NewReservedPort"))
            if 1 <= reserved <= 65535:
                cleanup = {
                    "control_url": control_url, "service_type": service_type,
                    "source_address": local,
                }
                uptime = _upnp_uptime(
                    control_url, service_type, timeout=timeout, source_address=local
                )
                if uptime is not None:
                    cleanup["uptime"] = uptime
                return MappingResult(
                    "upnp", external_host, reserved, local, internal_port, lifetime,
                    cleanup, protocol,
                )
        except (ConnectivityError, ValueError):
            pass
    last: ConnectivityError | None = None
    ports = [
        *([preferred_external_port] if 1 <= preferred_external_port <= 65535 else []),
        internal_port,
        *[random.SystemRandom().randint(42000, 60999) for _ in range(4)],
    ]
    for external_port in dict.fromkeys(ports):
        try:
            _soap(
                control_url, service_type, "AddPortMapping", {
                    "NewRemoteHost": "", "NewExternalPort": str(external_port),
                    "NewProtocol": protocol.upper(), "NewInternalPort": str(internal_port),
                    "NewInternalClient": local, "NewEnabled": "1",
                    "NewPortMappingDescription": description[:48],
                    "NewLeaseDuration": str(lifetime),
                }, timeout=timeout, source_address=local,
            )
            cleanup = {
                "control_url": control_url, "service_type": service_type,
                "source_address": local,
            }
            uptime = _upnp_uptime(
                control_url, service_type, timeout=timeout, source_address=local
            )
            if uptime is not None:
                cleanup["uptime"] = uptime
            return MappingResult(
                "upnp", external_host, external_port, local, internal_port, lifetime,
                cleanup, protocol,
            )
        except ConnectivityError as exc:
            last = exc
    raise last or ConnectivityError("upnp", "upnp_mapping_denied", result="blocked")


def map_upnp_ipv6_pinhole(
    internal_host: str, internal_port: int, *,
    lifetime: int = DEFAULT_MAPPING_LIFETIME, timeout: float = 1.1,
    routes: list[RouteInfo] | None = None, protocol: str = "tcp",
) -> MappingResult:
    """Open an IGD:2 IPv6 firewall pinhole when the router advertises it."""

    ip_protocol = _mapping_protocol(protocol)
    if classify_address(internal_host) != "public_ipv6":
        raise ConnectivityError("ipv6", "no_global_ipv6", result="unsupported")
    selected = default_routes() if routes is None else routes
    locations = _upnp_locations_by_route(selected, timeout)
    if not locations:
        raise ConnectivityError("upnp", "upnp_no_discovery", result="unsupported")
    last: ConnectivityError | None = None
    for source_address, location in locations:
        try:
            services = _upnp_services(
                location, timeout, source_address=source_address
            )
            control_url = services.get(UPNP_IPV6_FIREWALL_SERVICE)
            if not control_url:
                continue
            status = _soap(
                control_url, UPNP_IPV6_FIREWALL_SERVICE, "GetFirewallStatus", {},
                timeout=timeout, source_address=source_address,
            )
            if (
                _xml_value(status, "FirewallEnabled") not in {"1", "true"}
                or _xml_value(status, "InboundPinholeAllowed") not in {"1", "true"}
            ):
                raise ConnectivityError(
                    "ipv6", "upnp_mapping_denied", result="blocked",
                    recommended_action="use_ipv6_firewall_instructions",
                )
            response = _soap(
                control_url, UPNP_IPV6_FIREWALL_SERVICE, "AddPinhole", {
                    "RemoteHost": "", "RemotePort": "0",
                    "InternalClient": internal_host,
                    "InternalPort": str(internal_port), "Protocol": str(ip_protocol),
                    "LeaseTime": str(lifetime),
                }, timeout=timeout, source_address=source_address,
            )
            unique_id = int(_xml_value(response, "UniqueID"))
            if not 0 <= unique_id <= 65535:
                raise ValueError("invalid pinhole id")
            return MappingResult(
                "upnp_ipv6", internal_host, internal_port, internal_host,
                internal_port, lifetime, {
                    "control_url": control_url,
                    "service_type": UPNP_IPV6_FIREWALL_SERVICE,
                    "source_address": source_address,
                    "unique_id": unique_id,
                }, protocol,
            )
        except ConnectivityError as exc:
            last = exc
        except (TypeError, ValueError):
            last = ConnectivityError(
                "ipv6", "upnp_mapping_denied", result="blocked",
                recommended_action="use_ipv6_firewall_instructions",
            )
    if last is not None:
        raise last
    raise ConnectivityError("upnp", "upnp_no_discovery", result="unsupported")


def _gateway_exchange(
    gateway: str, payload: bytes, size: int, timeout: float,
    *, source_address: str | None = None,
) -> bytes:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        if source_address:
            sock.bind((source_address, 0))
        sock.settimeout(timeout)
        sock.sendto(payload, (gateway, GATEWAY_PORT))
        response, source = sock.recvfrom(256)
    if source[0] != gateway or len(response) < size:
        raise OSError("invalid gateway response")
    return response


def _retry_gateway_exchange(
    gateway: str, payload: bytes, size: int, *, source_address: str | None,
    delays: Iterable[float] = MAPPING_RETRY_DELAYS,
) -> bytes:
    last: OSError | None = None
    for timeout in delays:
        try:
            return _gateway_exchange(
                gateway, payload, size, timeout, source_address=source_address
            )
        except TypeError:
            # Preserve compatibility with small test fakes for the old helper.
            try:
                return _gateway_exchange(gateway, payload, size, timeout)
            except OSError as exc:
                last = exc
        except OSError as exc:
            last = exc
    raise last or OSError("gateway did not respond")


def _gateway_routes(routes: list[RouteInfo] | None = None) -> list[RouteInfo]:
    if routes is not None:
        return [route for route in _best_routes(routes, socket.AF_INET) if route.gateway]
    # gateway_candidates remains a seam for older tests while the production
    # implementation now returns only configured default-route gateways.
    selected = default_routes()
    by_gateway = {route.gateway: route for route in _best_routes(selected, socket.AF_INET)}
    values: list[RouteInfo] = []
    for gateway in gateway_candidates():
        route = by_gateway.get(gateway)
        values.append(route or RouteInfo(socket.AF_INET, "default", gateway, None, 0))
    return values


def _public_from_nat_pmp(response: bytes) -> tuple[str, int]:
    version, opcode, result, epoch, public_raw = struct.unpack("!BBHII", response[:12])
    if version != 0 or opcode != 128 or result != 0:
        raise ConnectivityError("nat_pmp", "nat_pmp_mapping_denied", result="blocked")
    return socket.inet_ntoa(struct.pack("!I", public_raw)), epoch


def inspect_nat_pmp(
    *, routes: list[RouteInfo] | None = None, timeout: float | None = None
) -> dict[str, str]:
    delays = (timeout,) if timeout is not None else MAPPING_RETRY_DELAYS
    for route in _gateway_routes(routes):
        assert route.gateway is not None
        try:
            external, _epoch = _public_from_nat_pmp(_retry_gateway_exchange(
                route.gateway, b"\x00\x00", 12, source_address=route.local_address,
                delays=delays,
            ))
            classification = classify_address(external)
            if classification != "public_ipv4":
                raise ConnectivityError(
                    "nat_pmp", "upstream_nat_detected", result="blocked",
                    recommended_action=(
                        "contact_provider_or_use_approved_access_point"
                        if classification == "shared" else "configure_upstream_router_or_bridge_mode"
                    ),
                )
            return diagnostic_step("nat_pmp", "available", "ready_to_prepare", "prepare_direct")
        except ConnectivityError:
            raise
        except (OSError, struct.error, ValueError):
            continue
    raise ConnectivityError("nat_pmp", "nat_pmp_no_response", result="unsupported")


def map_nat_pmp(
    internal_port: int, *, lifetime: int = DEFAULT_MAPPING_LIFETIME,
    timeout: float | None = None, routes: list[RouteInfo] | None = None,
    preferred_external_port: int = 0, protocol: str = "tcp",
) -> MappingResult:
    _mapping_protocol(protocol)
    mapping_opcode = 2 if protocol == "tcp" else 1
    delays = (timeout,) if timeout is not None else MAPPING_RETRY_DELAYS
    for route in _gateway_routes(routes):
        assert route.gateway is not None
        try:
            external_host, public_epoch = _public_from_nat_pmp(_retry_gateway_exchange(
                route.gateway, b"\x00\x00", 12,
                source_address=route.local_address, delays=delays,
            ))
            if classify_address(external_host) != "public_ipv4":
                raise ConnectivityError(
                    "nat_pmp", "upstream_nat_detected", result="blocked",
                    recommended_action="configure_upstream_router_or_bridge_mode",
                )
            requested = preferred_external_port if 1 <= preferred_external_port <= 65535 else 0
            request = struct.pack("!BBHHHI", 0, mapping_opcode, 0, internal_port, requested, lifetime)
            response = _retry_gateway_exchange(
                route.gateway, request, 16, source_address=route.local_address, delays=delays
            )
            version, opcode, result, epoch, returned, external_port, lease = struct.unpack(
                "!BBHIHHI", response[:16]
            )
            if version != 0 or opcode != 128 + mapping_opcode or returned != internal_port:
                continue
            if result != 0:
                raise ConnectivityError("nat_pmp", "nat_pmp_mapping_denied", result="blocked")
            if external_port == 0 or lease == 0:
                continue
            internal_host = route.local_address or _local_address_for(route.gateway, GATEWAY_PORT)
            return MappingResult(
                "nat_pmp", external_host, external_port, internal_host, internal_port,
                int(lease), {"gateway": route.gateway, "epoch": min(public_epoch, epoch)}, protocol,
            )
        except ConnectivityError:
            raise
        except (OSError, struct.error, ValueError):
            continue
    raise ConnectivityError("nat_pmp", "nat_pmp_no_response", result="unsupported")


def _pcp_request(
    internal_host: str, internal_port: int, lifetime: int, nonce: bytes,
    *, external_port: int = 0, protocol: str = "tcp",
) -> bytes:
    client_ip = b"\x00" * 10 + b"\xff\xff" + socket.inet_aton(internal_host)
    return (
        struct.pack("!BBHI", 2, 1, 0, lifetime) + client_ip + nonce
        + struct.pack("!B3sHH", _mapping_protocol(protocol), b"\x00" * 3, internal_port, external_port)
        + b"\x00" * 16
    )


def inspect_pcp(*, routes: list[RouteInfo] | None = None) -> dict[str, str]:
    for route in _gateway_routes(routes):
        assert route.gateway is not None
        try:
            response = _retry_gateway_exchange(
                route.gateway, struct.pack("!BBHI", 2, 0, 0, 0) + b"\x00" * 16,
                24, source_address=route.local_address,
            )
            if response[0] == 2 and response[1] == 0x80:
                if response[3] == 0:
                    return diagnostic_step("pcp", "available", "ready_to_prepare", "prepare_direct")
                raise ConnectivityError("pcp", "pcp_mapping_denied", result="blocked")
        except ConnectivityError:
            raise
        except (OSError, IndexError):
            continue
    raise ConnectivityError("pcp", "pcp_no_response", result="unsupported")


def map_pcp(
    internal_port: int, *, lifetime: int = DEFAULT_MAPPING_LIFETIME,
    timeout: float | None = None, routes: list[RouteInfo] | None = None,
    preferred_external_port: int = 0, protocol: str = "tcp",
) -> MappingResult:
    ip_protocol = _mapping_protocol(protocol)
    delays = (timeout,) if timeout is not None else MAPPING_RETRY_DELAYS
    for route in _gateway_routes(routes):
        assert route.gateway is not None
        try:
            internal_host = route.local_address or _local_address_for(route.gateway, GATEWAY_PORT)
            nonce = secrets.token_bytes(12)
            response = _retry_gateway_exchange(
                route.gateway, _pcp_request(
                    internal_host, internal_port, lifetime, nonce, protocol=protocol,
                    external_port=(
                        preferred_external_port
                        if 1 <= preferred_external_port <= 65535 else 0
                    ),
                ),
                60, source_address=internal_host, delays=delays,
            )
            version, opcode, _reserved, result, lease = struct.unpack("!BBBBI", response[:8])
            if version != 2 or opcode != 0x81 or response[24:36] != nonce:
                continue
            if result != 0:
                raise ConnectivityError("pcp", "pcp_mapping_denied", result="blocked")
            returned_protocol = response[36]
            returned, external_port = struct.unpack("!HH", response[40:44])
            address = ipaddress.ip_address(response[44:60])
            if address.ipv4_mapped is not None:
                address = address.ipv4_mapped
            external_host = address.compressed
            classification = classify_address(external_host)
            if classification in {"shared", "rfc1918", "ula", "private"}:
                raise ConnectivityError(
                    "pcp", "upstream_nat_detected", result="blocked",
                    recommended_action="configure_upstream_router_or_bridge_mode",
                )
            if returned_protocol != ip_protocol or returned != internal_port or not external_port or not lease or not address_is_public(external_host):
                continue
            epoch = struct.unpack("!I", response[8:12])[0]
            return MappingResult(
                "pcp", external_host, external_port, internal_host, internal_port,
                int(lease), {"gateway": route.gateway, "nonce": nonce.hex(), "epoch": epoch}, protocol,
            )
        except ConnectivityError:
            raise
        except (OSError, struct.error, ValueError, IndexError):
            continue
    raise ConnectivityError("pcp", "pcp_no_response", result="unsupported")


def create_port_mapping(
    internal_port: int, *, lifetime: int = DEFAULT_MAPPING_LIFETIME,
    routes: list[RouteInfo] | None = None, preferred_external_port: int = 0,
    protocol: str = "tcp", attempts: list[ConnectivityError] | None = None,
) -> MappingResult:
    _mapping_protocol(protocol)
    failures: list[ConnectivityError] = []
    for mapper in (map_pcp, map_upnp, map_nat_pmp):
        try:
            return mapper(
                internal_port, lifetime=lifetime, routes=routes,
                preferred_external_port=preferred_external_port, protocol=protocol,
            )
        except ConnectivityError as exc:
            failures.append(exc)
            if attempts is not None:
                attempts.append(exc)
        except OSError:
            failure = ConnectivityError("precondition", "no_default_route")
            failures.append(failure)
            if attempts is not None:
                attempts.append(failure)
    for reason in ("upstream_nat_detected", "upnp_wan_shared", "upnp_wan_private"):
        failure = next((item for item in failures if item.reason == reason), None)
        if failure:
            raise failure
    raise failures[-1] if failures else ConnectivityError("precondition", "no_default_route")


def renew_port_mapping(
    record: dict[str, Any], *, lifetime: int = DEFAULT_MAPPING_LIFETIME
) -> MappingResult:
    method = str(record.get("method", ""))
    protocol = record.get("protocol", "tcp")
    ip_protocol = _mapping_protocol(protocol)
    internal_port = int(record["internal_port"])
    external_port = int(record["external_port"])
    external_host = str(record["external_host"])
    internal_host = str(record["internal_host"])
    cleanup = dict(record.get("cleanup", {}))
    try:
        if method == "upnp_ipv6":
            _soap(
                str(cleanup["control_url"]), str(cleanup["service_type"]),
                "UpdatePinhole", {
                    "UniqueID": str(int(cleanup["unique_id"])),
                    "NewLeaseTime": str(lifetime),
                }, timeout=1.0,
                source_address=str(cleanup.get("source_address", "")) or None,
            )
            return MappingResult(
                method, external_host, external_port, internal_host, internal_port,
                lifetime, cleanup, protocol,
            )
        if method == "upnp":
            control_url = str(cleanup["control_url"])
            service_type = str(cleanup["service_type"])
            source = str(cleanup.get("source_address", internal_host))
            uptime = _upnp_uptime(
                control_url, service_type, timeout=1.0, source_address=source
            )
            if (
                uptime is not None and "uptime" in cleanup
                and uptime < int(cleanup["uptime"])
            ):
                raise ConnectivityError("precondition", "router_state_changed")
            current = ipaddress.ip_address(_xml_value(_soap(
                control_url, service_type, "GetExternalIPAddress", {}, timeout=1.0,
                source_address=source,
            ), "NewExternalIPAddress")).compressed
            if current != external_host:
                raise ConnectivityError("precondition", "router_state_changed")
            _soap(
                control_url, service_type, "AddPortMapping", {
                    "NewRemoteHost": "", "NewExternalPort": str(external_port),
                    "NewProtocol": protocol.upper(), "NewInternalPort": str(internal_port),
                    "NewInternalClient": internal_host, "NewEnabled": "1",
                    "NewPortMappingDescription": "MeshChat participant invite",
                    "NewLeaseDuration": str(lifetime),
                }, timeout=1.0, source_address=source,
            )
            if uptime is not None:
                cleanup["uptime"] = uptime
            return MappingResult(
                method, external_host, external_port, internal_host, internal_port,
                lifetime, cleanup, protocol,
            )
        gateway = str(cleanup["gateway"])
        if _local_address_for(gateway, GATEWAY_PORT) != internal_host:
            raise ConnectivityError("precondition", "router_state_changed")
        if method == "nat_pmp":
            current, public_epoch = _public_from_nat_pmp(_retry_gateway_exchange(
                gateway, b"\x00\x00", 12, source_address=internal_host
            ))
            response = _retry_gateway_exchange(
                gateway, struct.pack(
                    "!BBHHHI", 0, 2 if protocol == "tcp" else 1, 0, internal_port, external_port, lifetime
                ), 16, source_address=internal_host,
            )
            _version, _opcode, result, epoch, returned, mapped_port, lease = struct.unpack(
                "!BBHIHHI", response[:16]
            )
            if (
                _version != 0 or _opcode != (130 if protocol == "tcp" else 129)
                or lease == 0 or current != external_host or result != 0 or returned != internal_port
                or mapped_port != external_port
                or min(public_epoch, epoch) < int(cleanup.get("epoch", 0))
            ):
                raise ConnectivityError("precondition", "router_state_changed")
            cleanup["epoch"] = min(public_epoch, epoch)
            return MappingResult(
                method, external_host, external_port, internal_host, internal_port,
                int(lease), cleanup, protocol,
            )
        if method == "pcp":
            nonce = bytes.fromhex(str(cleanup["nonce"]))
            response = _retry_gateway_exchange(
                gateway, _pcp_request(
                    internal_host, internal_port, lifetime, nonce,
                    external_port=external_port, protocol=protocol,
                ), 60, source_address=internal_host,
            )
            _version, _opcode, _reserved, result, lease = struct.unpack("!BBBBI", response[:8])
            returned, mapped_port = struct.unpack("!HH", response[40:44])
            address = ipaddress.ip_address(response[44:60])
            if address.ipv4_mapped is not None:
                address = address.ipv4_mapped
            epoch = struct.unpack("!I", response[8:12])[0]
            if (
                _version != 2 or _opcode != 0x81 or response[36] != ip_protocol or lease == 0
                or result != 0 or response[24:36] != nonce or returned != internal_port
                or mapped_port != external_port or address.compressed != external_host
                or epoch < int(cleanup.get("epoch", 0))
            ):
                raise ConnectivityError("precondition", "router_state_changed")
            cleanup["epoch"] = epoch
            return MappingResult(
                method, external_host, external_port, internal_host, internal_port,
                int(lease), cleanup, protocol,
            )
    except ConnectivityError:
        raise
    except (KeyError, OSError, ValueError, struct.error, IndexError) as exc:
        raise ConnectivityError("precondition", "router_state_changed") from exc
    raise ConnectivityError("precondition", "router_state_changed")


def remove_port_mapping(record: dict[str, Any], *, timeout: float = 0.5) -> None:
    try:
        protocol = record.get("protocol", "tcp")
        _mapping_protocol(protocol)
        method = record["method"]
        internal_port = int(record["internal_port"])
        external_port = int(record["external_port"])
        cleanup = record["cleanup"]
        if method == "upnp_ipv6":
            _soap(
                cleanup["control_url"], cleanup["service_type"], "DeletePinhole",
                {"UniqueID": str(int(cleanup["unique_id"]))}, timeout=timeout,
                source_address=cleanup.get("source_address"),
            )
        elif method == "upnp":
            _soap(
                cleanup["control_url"], cleanup["service_type"], "DeletePortMapping",
                {"NewRemoteHost": "", "NewExternalPort": str(external_port),
                 "NewProtocol": protocol.upper()}, timeout=timeout,
                source_address=cleanup.get("source_address"),
            )
        elif method == "nat_pmp":
            _gateway_exchange(
                cleanup["gateway"],
                struct.pack("!BBHHHI", 0, 2 if protocol == "tcp" else 1, 0, internal_port, external_port, 0),
                16, timeout, source_address=record.get("internal_host"),
            )
        elif method == "pcp":
            internal_host = str(record["internal_host"])
            _gateway_exchange(
                cleanup["gateway"], _pcp_request(
                    internal_host, internal_port, 0, bytes.fromhex(cleanup["nonce"]),
                    external_port=external_port, protocol=protocol,
                ), 60, timeout, source_address=internal_host,
            )
    except Exception:
        return


def candidate_connection_result(host: str, port: int, *, timeout: float = 1.5) -> str:
    """Return only a coarse, copy-safe recipient connection outcome."""

    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return "unresolved"
    outcomes: list[str] = []
    for family, socktype, protocol, _canonical, address in addresses[:8]:
        try:
            with socket.socket(family, socktype, protocol) as probe:
                probe.settimeout(timeout)
                result = probe.connect_ex(address)
            if result == 0:
                return "connected"
            if result in {10061, 111, 61}:
                outcomes.append("refused")
            elif family == socket.AF_INET6 and result in {10051, 10065, 101, 113}:
                outcomes.append("no_ipv6_route")
            else:
                outcomes.append("timed_out")
        except TimeoutError:
            outcomes.append("timed_out")
        except OSError as exc:
            if family == socket.AF_INET6 and getattr(exc, "errno", None) in {10051, 10065, 101, 113}:
                outcomes.append("no_ipv6_route")
            else:
                outcomes.append("timed_out")
    for preferred in ("refused", "no_ipv6_route", "timed_out"):
        if preferred in outcomes:
            return preferred
    return "timed_out"
