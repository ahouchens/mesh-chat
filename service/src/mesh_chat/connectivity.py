from __future__ import annotations

import http.client
import ipaddress
import random
import socket
import struct
import time
from dataclasses import dataclass
from html import escape
from typing import Any
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


@dataclass(frozen=True, slots=True)
class MappingResult:
    method: str
    external_host: str
    external_port: int
    internal_host: str
    internal_port: int
    lifetime: int
    cleanup: dict[str, Any]

    def endpoint(self) -> dict[str, Any]:
        return {
            "host": self.external_host,
            "port": self.external_port,
            "path": self.method,
        }

    def record(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "external_host": self.external_host,
            "external_port": self.external_port,
            "internal_host": self.internal_host,
            "internal_port": self.internal_port,
            "lifetime": self.lifetime,
            "cleanup": dict(self.cleanup),
        }


def select_available_port(*, ipv6: bool = False) -> int:
    family = socket.AF_INET6 if ipv6 else socket.AF_INET
    host = "::" if ipv6 else "0.0.0.0"
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return int(probe.getsockname()[1])


def global_ipv6_addresses(*, limit: int = 2, rns_module: Any = RNS) -> list[str]:
    addresses: list[str] = []
    try:
        netinfo = rns_module.Interfaces.netinfo
        for interface_name in netinfo.interfaces():
            for value in netinfo.ifaddresses(interface_name).get(netinfo.AF_INET6, []):
                raw = str(value.get("addr", "")).split("%", 1)[0]
                try:
                    address = ipaddress.ip_address(raw)
                except ValueError:
                    continue
                if (
                    isinstance(address, ipaddress.IPv6Address)
                    and address.is_global
                    and not address.is_multicast
                    and address.compressed not in addresses
                ):
                    addresses.append(address.compressed)
                    if len(addresses) >= limit:
                        return addresses
    except Exception:
        return []
    return addresses


def _private_ipv4_entries(rns_module: Any = RNS) -> list[tuple[str, int]]:
    entries: list[tuple[str, int]] = []
    try:
        netinfo = rns_module.Interfaces.netinfo
        for interface_name in netinfo.interfaces():
            for value in netinfo.ifaddresses(interface_name).get(netinfo.AF_INET, []):
                try:
                    address = ipaddress.ip_address(value.get("addr"))
                    prefix = int(value.get("prefix", 32))
                except (TypeError, ValueError):
                    continue
                if (
                    isinstance(address, ipaddress.IPv4Address)
                    and (address.is_private or address in ipaddress.ip_network("100.64.0.0/10"))
                    and not address.is_loopback
                    and 1 <= prefix <= 30
                ):
                    item = (address.compressed, prefix)
                    if item not in entries:
                        entries.append(item)
    except Exception:
        return []
    return entries


def gateway_candidates(rns_module: Any = RNS) -> list[str]:
    """Return bounded on-link gateway guesses without querying outside the LAN."""

    candidates: list[str] = []
    for local, prefix in _private_ipv4_entries(rns_module):
        network = ipaddress.ip_network(f"{local}/{prefix}", strict=False)
        if network.num_addresses < 4:
            continue
        for address in (network.network_address + 1, network.broadcast_address - 1):
            text = address.compressed
            if text != local and text not in candidates:
                candidates.append(text)
    return candidates[:8]


def _local_address_for(remote_host: str, port: int) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect((remote_host, port))
        return str(probe.getsockname()[0])


def _bounded_http(
    method: str,
    url: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float,
) -> tuple[int, bytes]:
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.username or parsed.password or parsed.fragment:
        raise OSError("unsupported local control URL")
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
    except ValueError as exc:
        raise OSError("local control URL must use an IP address") from exc
    if not isinstance(address, ipaddress.IPv4Address) or not (
        address.is_private or address.is_link_local
    ):
        raise OSError("local control URL is not on a private network")
    port = parsed.port or 80
    target = parsed.path or "/"
    if parsed.query:
        target += f"?{parsed.query}"
    connection = http.client.HTTPConnection(address.compressed, port, timeout=timeout)
    request_headers = {"Host": parsed.netloc, "Connection": "close", **(headers or {})}
    try:
        connection.request(method, target, body=body, headers=request_headers)
        response = connection.getresponse()
        length = response.getheader("Content-Length")
        if length is not None and int(length) > MAX_HTTP_BYTES:
            raise OSError("local control response is too large")
        payload = response.read(MAX_HTTP_BYTES + 1)
        if len(payload) > MAX_HTTP_BYTES:
            raise OSError("local control response is too large")
        return response.status, payload
    finally:
        connection.close()


def _ssdp_locations(timeout: float) -> list[str]:
    request = (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 1\r\n"
        "ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n"
    ).encode("ascii")
    locations: list[str] = []
    deadline = time.monotonic() + timeout
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        sock.settimeout(min(0.25, timeout))
        sock.sendto(request, SSDP_ADDRESS)
        while time.monotonic() < deadline:
            try:
                payload, _source = sock.recvfrom(16 * 1024)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                text = payload.decode("iso-8859-1")
            except UnicodeDecodeError:
                continue
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


def _upnp_service(location: str, timeout: float) -> tuple[str, str]:
    status, body = _bounded_http("GET", location, timeout=timeout)
    if status != 200:
        raise OSError("gateway description was unavailable")
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise OSError("gateway description was invalid") from exc
    services: dict[str, str] = {}
    for service in root.iter():
        if not service.tag.endswith("service"):
            continue
        service_type = None
        control_url = None
        for child in service:
            if child.tag.endswith("serviceType"):
                service_type = (child.text or "").strip()
            elif child.tag.endswith("controlURL"):
                control_url = (child.text or "").strip()
        if service_type and control_url:
            services[service_type] = urljoin(location, control_url)
    for service_type in UPNP_SERVICES:
        if service_type in services:
            control = services[service_type]
            if urlsplit(control).hostname != urlsplit(location).hostname:
                raise OSError("gateway control URL changed host")
            return service_type, control
    raise OSError("gateway has no supported WAN service")


def _soap(
    control_url: str,
    service_type: str,
    action: str,
    arguments: dict[str, str],
    *,
    timeout: float,
) -> bytes:
    params = "".join(
        f"<{name}>{escape(value)}</{name}>" for name, value in arguments.items()
    )
    body = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        f'<s:Body><u:{action} xmlns:u="{service_type}">{params}'
        f"</u:{action}></s:Body></s:Envelope>"
    ).encode("utf-8")
    status, response = _bounded_http(
        "POST",
        control_url,
        body=body,
        headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": f'"{service_type}#{action}"',
            "Content-Length": str(len(body)),
        },
        timeout=timeout,
    )
    if status != 200:
        raise OSError(f"gateway rejected {action}")
    return response


def _xml_value(payload: bytes, name: str) -> str:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise OSError("gateway response was invalid") from exc
    for element in root.iter():
        if element.tag.endswith(name) and element.text:
            return element.text.strip()
    raise OSError(f"gateway response omitted {name}")


def map_upnp(
    internal_port: int,
    *,
    lifetime: int = DEFAULT_MAPPING_LIFETIME,
    timeout: float = 1.1,
    description: str = "MeshChat participant invite",
) -> MappingResult:
    for location in _ssdp_locations(timeout):
        try:
            service_type, control_url = _upnp_service(location, timeout)
            control_host = str(urlsplit(control_url).hostname)
            internal_host = _local_address_for(control_host, urlsplit(control_url).port or 80)
            external_payload = _soap(
                control_url,
                service_type,
                "GetExternalIPAddress",
                {},
                timeout=timeout,
            )
            external_host = ipaddress.ip_address(
                _xml_value(external_payload, "NewExternalIPAddress")
            ).compressed
            if not address_is_public(external_host):
                continue
            ports = [internal_port, *[random.randint(42000, 60999) for _ in range(4)]]
            for external_port in dict.fromkeys(ports):
                try:
                    _soap(
                        control_url,
                        service_type,
                        "AddPortMapping",
                        {
                            "NewRemoteHost": "",
                            "NewExternalPort": str(external_port),
                            "NewProtocol": "TCP",
                            "NewInternalPort": str(internal_port),
                            "NewInternalClient": internal_host,
                            "NewEnabled": "1",
                            "NewPortMappingDescription": description[:48],
                            "NewLeaseDuration": str(lifetime),
                        },
                        timeout=timeout,
                    )
                    return MappingResult(
                        "upnp",
                        external_host,
                        external_port,
                        internal_host,
                        internal_port,
                        lifetime,
                        {
                            "control_url": control_url,
                            "service_type": service_type,
                        },
                    )
                except OSError:
                    continue
        except (OSError, ValueError):
            continue
    raise OSError("UPnP port mapping is unavailable")


def _gateway_exchange(gateway: str, payload: bytes, size: int, timeout: float) -> bytes:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(payload, (gateway, GATEWAY_PORT))
        response, source = sock.recvfrom(256)
    if source[0] != gateway or len(response) < size:
        raise OSError("gateway mapping response was invalid")
    return response


def map_nat_pmp(
    internal_port: int,
    *,
    lifetime: int = DEFAULT_MAPPING_LIFETIME,
    timeout: float = 0.3,
) -> MappingResult:
    for gateway in gateway_candidates():
        try:
            public = _gateway_exchange(gateway, b"\x00\x00", 12, timeout)
            version, opcode, result, _epoch, public_raw = struct.unpack("!BBHII", public[:12])
            if version != 0 or opcode != 128 or result != 0:
                continue
            external_host = socket.inet_ntoa(struct.pack("!I", public_raw))
            if not address_is_public(external_host):
                continue
            request = struct.pack("!BBHHHI", 0, 2, 0, internal_port, 0, lifetime)
            mapped = _gateway_exchange(gateway, request, 16, timeout)
            version, opcode, result, _epoch, returned_internal, external_port, lease = struct.unpack(
                "!BBHIHHI", mapped[:16]
            )
            if (
                version != 0
                or opcode != 130
                or result != 0
                or returned_internal != internal_port
                or external_port == 0
            ):
                continue
            return MappingResult(
                "nat_pmp",
                external_host,
                external_port,
                _local_address_for(gateway, GATEWAY_PORT),
                internal_port,
                int(lease),
                {"gateway": gateway},
            )
        except (OSError, struct.error, ValueError):
            continue
    raise OSError("NAT-PMP port mapping is unavailable")


def map_pcp(
    internal_port: int,
    *,
    lifetime: int = DEFAULT_MAPPING_LIFETIME,
    timeout: float = 0.3,
) -> MappingResult:
    for gateway in gateway_candidates():
        try:
            internal_host = _local_address_for(gateway, GATEWAY_PORT)
            client_ip = b"\x00" * 10 + b"\xff\xff" + socket.inet_aton(internal_host)
            nonce = random.randbytes(12)
            request = (
                struct.pack("!BBHI", 2, 1, 0, lifetime)
                + client_ip
                + nonce
                + struct.pack("!B3sHH", 6, b"\x00" * 3, internal_port, 0)
                + b"\x00" * 16
            )
            response = _gateway_exchange(gateway, request, 60, timeout)
            version, opcode, _reserved, result, lease = struct.unpack("!BBBBI", response[:8])
            if version != 2 or opcode != 0x81 or result != 0 or response[24:36] != nonce:
                continue
            protocol = response[36]
            returned_internal, external_port = struct.unpack("!HH", response[40:44])
            address = ipaddress.ip_address(response[44:60])
            if address.ipv4_mapped is not None:
                address = address.ipv4_mapped
            external_host = address.compressed
            if (
                protocol != 6
                or returned_internal != internal_port
                or external_port == 0
                or not address_is_public(external_host)
            ):
                continue
            return MappingResult(
                "pcp",
                external_host,
                external_port,
                internal_host,
                internal_port,
                int(lease),
                {"gateway": gateway, "nonce": nonce.hex()},
            )
        except (OSError, struct.error, ValueError):
            continue
    raise OSError("PCP port mapping is unavailable")


def create_port_mapping(
    internal_port: int,
    *,
    lifetime: int = DEFAULT_MAPPING_LIFETIME,
) -> MappingResult:
    """Try common local-router standards without contacting an Internet service."""

    failures: list[Exception] = []
    for mapper in (map_upnp, map_nat_pmp, map_pcp):
        try:
            return mapper(internal_port, lifetime=lifetime)
        except OSError as exc:
            failures.append(exc)
    raise OSError("No automatic participant-hosted Internet path is available") from failures[-1]


def remove_port_mapping(record: dict[str, Any], *, timeout: float = 0.5) -> None:
    try:
        method = record["method"]
        internal_port = int(record["internal_port"])
        external_port = int(record["external_port"])
        cleanup = record["cleanup"]
        if method == "upnp":
            _soap(
                cleanup["control_url"],
                cleanup["service_type"],
                "DeletePortMapping",
                {
                    "NewRemoteHost": "",
                    "NewExternalPort": str(external_port),
                    "NewProtocol": "TCP",
                },
                timeout=timeout,
            )
        elif method == "nat_pmp":
            request = struct.pack(
                "!BBHHHI", 0, 2, 0, internal_port, external_port, 0
            )
            _gateway_exchange(cleanup["gateway"], request, 16, timeout)
        elif method == "pcp":
            gateway = cleanup["gateway"]
            internal_host = _local_address_for(gateway, GATEWAY_PORT)
            client_ip = b"\x00" * 10 + b"\xff\xff" + socket.inet_aton(internal_host)
            nonce = bytes.fromhex(cleanup["nonce"])
            request = (
                struct.pack("!BBHI", 2, 1, 0, 0)
                + client_ip
                + nonce
                + struct.pack(
                    "!B3sHH", 6, b"\x00" * 3, internal_port, external_port
                )
                + b"\x00" * 16
            )
            _gateway_exchange(gateway, request, 60, timeout)
    except Exception:
        # Router cleanup is best effort. Leases are intentionally short and
        # expire even if the app is terminated before this request completes.
        return
