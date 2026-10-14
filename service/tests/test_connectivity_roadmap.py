from __future__ import annotations

import json
import os
import base64
import re
import socket
import struct
import subprocess
from types import SimpleNamespace

import pytest

from mesh_chat import connectivity
from mesh_chat.connectivity import ConnectivityError, MappingResult, RouteInfo
from mesh_chat.errors import DirectConnectionUnavailable, ValidationError
from mesh_chat import firewall
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore


class _NetInfo:
    AF_INET = socket.AF_INET
    AF_INET6 = socket.AF_INET6

    @staticmethod
    def interfaces() -> list[str]:
        return ["Wi-Fi", "vEthernet", "VPN", "Disconnected"]

    @staticmethod
    def ifaddresses(name: str) -> dict[int, list[dict[str, object]]]:
        return {
            "Wi-Fi": {
                socket.AF_INET: [{"addr": "192.168.50.20", "prefix": 24}],
                socket.AF_INET6: [{"addr": "2001:4860:1::20", "preferred_lft": 7200}],
            },
            "vEthernet": {socket.AF_INET: [{"addr": "172.20.0.1", "prefix": 20}]},
            "VPN": {socket.AF_INET: [{"addr": "10.8.0.2", "prefix": 24}]},
            "Disconnected": {socket.AF_INET: [{"addr": "169.254.5.4", "prefix": 16}]},
        }.get(name, {})


def _rns() -> SimpleNamespace:
    return SimpleNamespace(Interfaces=SimpleNamespace(netinfo=_NetInfo))


def test_windows_default_route_selects_the_real_active_interface() -> None:
    rows = [
        {"AddressFamily": "IPv4", "InterfaceAlias": "VPN", "NextHop": "10.8.0.1", "RouteMetric": 200, "InterfaceMetric": 5},
        {"AddressFamily": "IPv4", "InterfaceAlias": "Wi-Fi", "NextHop": "192.168.50.1", "RouteMetric": 0, "InterfaceMetric": 25},
        {"AddressFamily": "IPv6", "InterfaceAlias": "Wi-Fi", "NextHop": "fe80::1", "RouteMetric": 0, "InterfaceMetric": 25},
    ]

    def runner(*_args, **_kwargs):
        return subprocess.CompletedProcess([], 0, json.dumps(rows), "")

    routes = connectivity.default_routes(rns_module=_rns(), system="Windows", runner=runner)
    assert connectivity.gateway_candidates(routes=routes) == ["192.168.50.1"]
    assert connectivity.global_ipv6_addresses(rns_module=_rns(), routes=routes) == ["2001:4860:1::20"]
    assert all(route.interface not in {"vEthernet", "Disconnected"} for route in routes)


def test_direct_public_ipv4_candidate_comes_only_from_the_selected_route() -> None:
    routes = [
        RouteInfo(socket.AF_INET, "Ethernet", "93.184.216.1", "93.184.216.34", 10),
        RouteInfo(socket.AF_INET, "VPN", "10.8.0.1", "10.8.0.2", 200),
    ]
    assert connectivity.public_ipv4_addresses(routes=routes) == ["93.184.216.34"]


@pytest.mark.parametrize(
    ("address", "classification"),
    [
        ("93.184.216.34", "public_ipv4"),
        ("192.168.1.2", "rfc1918"),
        ("100.64.1.2", "shared"),
        ("fd00::1", "ula"),
        ("2001:4860:4860::8888", "public_ipv6"),
        ("169.254.1.2", "link_local"),
        ("192.0.2.2", "private"),
    ],
)
def test_address_classification_is_conservative(address: str, classification: str) -> None:
    assert connectivity.classify_address(address) == classification


def test_ssdp_discovery_is_bound_to_the_selected_interface(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, object]] = []

    class FakeSocket:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def setsockopt(self, _level, _name, value): calls.append(("multicast", value))
        def bind(self, value): calls.append(("bind", value))
        def settimeout(self, _value): return None
        def sendto(self, _payload, value): calls.append(("send", value))
        def recvfrom(self, _size): raise socket.timeout()

    monkeypatch.setattr(connectivity.socket, "socket", lambda *_args: FakeSocket())
    assert connectivity._ssdp_locations("192.168.50.20", 0.001) == []
    assert ("bind", ("192.168.50.20", 0)) in calls
    assert ("multicast", socket.inet_aton("192.168.50.20")) in calls


def test_gateway_retry_uses_bounded_exponential_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[float] = []

    def exchange(_gateway, _payload, _size, timeout, **_kwargs):
        attempts.append(timeout)
        if len(attempts) < 3:
            raise socket.timeout()
        return b"response"

    monkeypatch.setattr(connectivity, "_gateway_exchange", exchange)
    assert connectivity._retry_gateway_exchange(
        "192.168.1.1", b"request", 4, source_address="192.168.1.20"
    ) == b"response"
    assert attempts == [0.25, 0.5, 1.0]


def test_pcp_uses_cryptographically_secure_nonce(monkeypatch: pytest.MonkeyPatch) -> None:
    nonce = b"secure-nonce"
    assert len(nonce) == 12
    captured: list[bytes] = []
    route = RouteInfo(socket.AF_INET, "Wi-Fi", "192.168.1.1", "192.168.1.20", 1)
    monkeypatch.setattr(connectivity.secrets, "token_bytes", lambda size: nonce if size == 12 else b"")

    def retry(_gateway, payload, _size, **_kwargs):
        captured.append(payload)
        return (
            struct.pack("!BBBBI", 2, 0x81, 0, 0, 7200)
            + struct.pack("!I", 10) + b"\x00" * 12 + nonce
            + struct.pack("!B3sHH", 6, b"\x00" * 3, 45678, 54321)
            + b"\x00" * 10 + b"\xff\xff" + socket.inet_aton("93.184.216.34")
        )

    monkeypatch.setattr(connectivity, "_retry_gateway_exchange", retry)
    mapped = connectivity.map_pcp(
        45678, routes=[route], preferred_external_port=55000
    )
    assert captured[0][24:36] == nonce
    assert struct.unpack("!HH", captured[0][40:44]) == (45678, 55000)
    assert mapped.cleanup["nonce"] == nonce.hex()
    assert mapped.external_port == 54321


def test_pcp_result_code_is_reported_as_policy_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    nonce = b"secure-nonce"
    route = RouteInfo(socket.AF_INET, "Wi-Fi", "192.168.1.1", "192.168.1.20", 1)
    monkeypatch.setattr(connectivity.secrets, "token_bytes", lambda _size: nonce)
    monkeypatch.setattr(
        connectivity, "_retry_gateway_exchange",
        lambda *_args, **_kwargs: (
            struct.pack("!BBBBI", 2, 0x81, 0, 2, 0)
            + struct.pack("!I", 10) + b"\x00" * 12 + nonce + b"\x00" * 24
        ),
    )
    with pytest.raises(ConnectivityError) as raised:
        connectivity.map_pcp(45678, routes=[route])
    assert raised.value.reason == "pcp_mapping_denied"
    assert raised.value.result == "blocked"


def test_nat_pmp_result_code_is_reported_as_policy_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = RouteInfo(socket.AF_INET, "Wi-Fi", "192.168.1.1", "192.168.1.20", 1)
    responses = iter((
        struct.pack("!BBHII", 0, 128, 0, 10, int.from_bytes(socket.inet_aton("93.184.216.34"), "big")),
        struct.pack("!BBHIHHI", 0, 130, 2, 10, 45678, 0, 0),
    ))
    monkeypatch.setattr(
        connectivity, "_retry_gateway_exchange",
        lambda *_args, **_kwargs: next(responses),
    )
    with pytest.raises(ConnectivityError) as raised:
        connectivity.map_nat_pmp(45678, routes=[route])
    assert raised.value.reason == "nat_pmp_mapping_denied"
    assert raised.value.result == "blocked"


def test_automatic_mapping_prefers_pcp_then_upnp_then_nat_pmp(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fail(name: str):
        def mapper(*_args, **_kwargs):
            calls.append(name)
            raise ConnectivityError(name, f"{name}_no_response" if name != "upnp" else "upnp_no_discovery")
        return mapper

    expected = MappingResult("nat_pmp", "93.184.216.34", 5000, "192.168.1.2", 4000, 7200, {})
    monkeypatch.setattr(connectivity, "map_pcp", fail("pcp"))
    monkeypatch.setattr(connectivity, "map_upnp", fail("upnp"))
    monkeypatch.setattr(connectivity, "map_nat_pmp", lambda *_args, **_kwargs: calls.append("nat_pmp") or expected)
    assert connectivity.create_port_mapping(4000) == expected
    assert calls == ["pcp", "upnp", "nat_pmp"]


def test_upnp_ipv6_pinhole_is_created_renewed_and_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = RouteInfo(socket.AF_INET, "Wi-Fi", "192.168.1.1", "192.168.1.20", 1)
    actions: list[str] = []
    monkeypatch.setattr(
        connectivity, "_upnp_locations_by_route",
        lambda _routes, _timeout: [("192.168.1.20", "http://192.168.1.1/root.xml")],
    )
    monkeypatch.setattr(
        connectivity, "_upnp_services",
        lambda *_args, **_kwargs: {
            connectivity.UPNP_IPV6_FIREWALL_SERVICE: "http://192.168.1.1/ipv6"
        },
    )

    def soap(_url, _service, action, _arguments, **_kwargs):
        actions.append(action)
        if action == "GetFirewallStatus":
            return b"<r><FirewallEnabled>1</FirewallEnabled><InboundPinholeAllowed>1</InboundPinholeAllowed></r>"
        if action == "AddPinhole":
            return b"<r><UniqueID>42</UniqueID></r>"
        return b"<r/>"

    monkeypatch.setattr(connectivity, "_soap", soap)
    mapped = connectivity.map_upnp_ipv6_pinhole(
        "2001:4860:1::20", 45678, routes=[route]
    )
    renewed = connectivity.renew_port_mapping(mapped.record())
    connectivity.remove_port_mapping(renewed.record())
    assert mapped.method == "upnp_ipv6"
    assert mapped.cleanup["unique_id"] == 42
    assert actions == [
        "GetFirewallStatus", "AddPinhole", "UpdatePinhole", "DeletePinhole"
    ]


def test_upnp_igd2_prefers_any_port_mapping_and_records_router_uptime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions: list[str] = []
    monkeypatch.setattr(
        connectivity, "_upnp_external",
        lambda *_args: (
            "192.168.1.20", "urn:schemas-upnp-org:service:WANIPConnection:2",
            "http://192.168.1.1/control", "93.184.216.34",
        ),
    )

    def soap(_url, _service, action, _arguments, **_kwargs):
        actions.append(action)
        if action == "AddAnyPortMapping":
            return b"<r><NewReservedPort>55000</NewReservedPort></r>"
        if action == "GetStatusInfo":
            return b"<r><NewUptime>1234</NewUptime></r>"
        return b"<r/>"

    monkeypatch.setattr(connectivity, "_soap", soap)
    mapped = connectivity.map_upnp(45678, routes=[])
    assert mapped.external_port == 55000
    assert mapped.cleanup["uptime"] == 1234
    assert actions == ["AddAnyPortMapping", "GetStatusInfo"]


@pytest.mark.parametrize(
    ("fault", "reason"),
    [(b"<r><errorCode>725</errorCode></r>", "upnp_unsupported_lease"),
     (b"<r><errorCode>718</errorCode></r>", "upnp_mapping_denied")],
)
def test_upnp_faults_are_safely_classified(fault: bytes, reason: str) -> None:
    assert connectivity._soap_fault_reason(fault) == reason


def test_upnp_renewal_rejects_router_uptime_regression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = MappingResult(
        "upnp", "93.184.216.34", 55000, "192.168.1.20", 45678, 7200,
        {
            "control_url": "http://192.168.1.1/control", "service_type": "wan",
            "source_address": "192.168.1.20", "uptime": 100,
        },
    ).record()
    monkeypatch.setattr(connectivity, "_upnp_uptime", lambda *_args, **_kwargs: 10)
    with pytest.raises(ConnectivityError, match="router_state_changed"):
        connectivity.renew_port_mapping(record)


def test_nat_pmp_renewal_rejects_router_epoch_regression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = MappingResult(
        "nat_pmp", "93.184.216.34", 55000, "192.168.1.20", 45678, 7200,
        {"gateway": "192.168.1.1", "epoch": 100},
    ).record()
    monkeypatch.setattr(connectivity, "_local_address_for", lambda *_args: "192.168.1.20")

    def exchange(_gateway, payload, _size, **_kwargs):
        if payload == b"\x00\x00":
            return struct.pack("!BBHII", 0, 128, 0, 10, int.from_bytes(socket.inet_aton("93.184.216.34"), "big"))
        return struct.pack("!BBHIHHI", 0, 130, 0, 10, 45678, 55000, 7200)

    monkeypatch.setattr(connectivity, "_retry_gateway_exchange", exchange)
    with pytest.raises(ConnectivityError, match="router_state_changed"):
        connectivity.renew_port_mapping(record)


class _Network:
    def __init__(self) -> None:
        self.listeners: list[dict[str, object]] = []
        self.interface_available = True
        self.online = True
        self.client_count = 0

    def invitation_hints(self): return []
    def reannounce(self): return None
    def shutdown(self): return True
    def apply_participant_interfaces(self, listeners, _clients): self.listeners = listeners
    def participant_host_state(self, session_id):
        selected = [item for item in self.listeners if item["id"] == session_id]
        return {
            "listener_count": len(selected),
            "online": bool(selected) and self.online,
            "client_count": self.client_count,
        }
    def snapshot(self): return {"interface_available": True, "interfaces": []}


class _KernelAllocatedNetwork(_Network):
    def participant_listener_bindings(self, session_id):
        selected = [item for item in self.listeners if item["id"] == session_id]
        return [
            {"listen_ip": item["listen_ip"], "port": 45678}
            for item in selected
        ]


def test_real_listener_allocates_the_port_before_it_is_advertised(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "mesh_chat.participant_service.select_available_port",
        lambda **_kwargs: pytest.fail("preflight port selection must not run"),
    )
    monkeypatch.setattr("mesh_chat.participant_service.inspect_upnp", lambda **_kwargs: {})
    monkeypatch.setattr("mesh_chat.participant_service.inspect_nat_pmp", lambda **_kwargs: {})
    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    service._start_network = lambda _name: None  # type: ignore[method-assign]
    try:
        service.create_profile("Inviter")
        service.network = _KernelAllocatedNetwork()  # type: ignore[assignment]
        setup = service.prepare_manual_participant_host("personal")
        assert setup["tcp_port"] == 45678
        assert service.store.list("participant_host")[0]["listeners"][0]["port"] == 45678
    finally:
        service.close()


def test_manual_participant_invitation_uses_stable_listener_and_safe_snapshot(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("mesh_chat.participant_service.select_available_port", lambda **_kwargs: 45678)
    monkeypatch.setattr("mesh_chat.participant_service.inspect_upnp", lambda **_kwargs: {})
    monkeypatch.setattr("mesh_chat.participant_service.inspect_nat_pmp", lambda **_kwargs: {})
    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    service._start_network = lambda _name: None  # type: ignore[method-assign]
    try:
        service.create_profile("Inviter")
        service.network = _Network()  # type: ignore[assignment]
        setup = service.prepare_manual_participant_host("personal")
        assert setup["tcp_port"] == 45678
        invitation = service.invitation(
            connection_mode="manual", manual_setup_id=setup["setup_id"],
            external_host="93.184.216.34", external_port=55000,
        )
        assert invitation["methods"] == ["manual"]
        snapshot = service.snapshot()
        serialized = json.dumps(snapshot)
        assert "93.184.216.34" not in serialized
        assert "network_name" not in serialized
        assert "passphrase" not in serialized
        assert snapshot["participant_hosting"][0]["state"] == "prepared_unverified"
    finally:
        service.close()


def test_direct_error_ipc_details_are_allowlisted() -> None:
    from mesh_chat.__main__ import _error_response
    from mesh_chat.errors import DirectConnectionUnavailable

    response = _error_response("command", DirectConnectionUnavailable(
        "hidden raw text",
        details={
            "phase": "upnp", "result": "blocked", "reason": "upnp_mapping_denied",
            "recommended_action": "retry",
        },
    ))
    assert response["error"] == {
        "code": "direct_connection_unavailable",
        "details": {
            "phase": "upnp", "result": "blocked", "reason": "upnp_mapping_denied",
            "recommended_action": "retry",
        },
    }
    assert "hidden raw text" not in json.dumps(response)


def test_recipient_validates_dns_before_any_candidate_probe(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "mesh_chat.participant_service.resolve_public_endpoint",
        lambda _endpoint: (_ for _ in ()).throw(ValidationError("unsafe answer")),
    )
    monkeypatch.setattr(
        "mesh_chat.participant_service.candidate_connection_result",
        lambda *_args, **_kwargs: pytest.fail("unsafe hostname must not be probed"),
    )
    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    try:
        resolved, results = service._resolved_participant_endpoints({
            "endpoints": [{"host": "example.test", "port": 4242, "path": "manual"}]
        })
        assert resolved == []
        assert results == [{"candidate": 1, "path": "manual", "result": "unresolved"}]
    finally:
        service.close()


def test_listener_failure_is_structured_and_leaves_no_host(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("mesh_chat.participant_service.select_available_port", lambda **_kwargs: 45678)
    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    service._start_network = lambda _name: None  # type: ignore[method-assign]
    try:
        service.create_profile("Inviter")
        network = _Network()
        network.online = False
        service.network = network  # type: ignore[assignment]
        with pytest.raises(DirectConnectionUnavailable) as raised:
            service.prepare_manual_participant_host("personal")
        assert raised.value.details == {
            "phase": "listener", "result": "blocked",
            "reason": "listener_bind_failed",
            "recommended_action": "retry_or_check_firewall",
        }
        assert service.store.list("participant_host") == []
    finally:
        service.close()


def test_authenticated_client_changes_prepared_host_to_recipient_connected(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("mesh_chat.participant_service.select_available_port", lambda **_kwargs: 45678)
    monkeypatch.setattr("mesh_chat.participant_service.inspect_upnp", lambda **_kwargs: {})
    monkeypatch.setattr("mesh_chat.participant_service.inspect_nat_pmp", lambda **_kwargs: {})
    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    service._start_network = lambda _name: None  # type: ignore[method-assign]
    try:
        service.create_profile("Inviter")
        network = _Network()
        service.network = network  # type: ignore[assignment]
        setup = service.prepare_manual_participant_host("personal")
        service.invitation(
            connection_mode="manual", manual_setup_id=setup["setup_id"],
            external_host="93.184.216.34", external_port=55000,
        )
        assert service.participant_hosting_snapshot()[0]["state"] == "prepared_unverified"
        network.client_count = 1
        assert service.participant_hosting_snapshot()[0]["state"] == "recipient_connected"
    finally:
        service.close()


def test_windows_firewall_rule_is_exact_and_user_elevated(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(firewall.platform, "system", lambda: "Windows")
    session_id = "a" * 64
    executable = tmp_path / "mesh-chat-service.exe"
    executable.write_bytes(b"test")
    ready = tmp_path / f"{session_id}.ready"
    scripts: list[str] = []

    def runner(command, **_kwargs):
        script = base64.b64decode(command[-1]).decode("utf-16-le")
        scripts.append(script)
        if "Get-NetConnectionProfile" in script:
            return subprocess.CompletedProcess(command, 0, "Private\n", "")
        ready.write_text("ok", encoding="ascii")
        return subprocess.CompletedProcess(command, 0, "", "")

    result = firewall.install_temporary_windows_rule(
        session_id, 45678, tmp_path, executable=executable,
        parent_pid=1234, runner=runner,
    )
    assert result["configured"] is True
    assert "-Verb RunAs" in scripts[-1]
    encoded_helper = re.findall(r"'[A-Za-z0-9+/=]{100,}'", scripts[-1])[-1].strip("'")
    helper = base64.b64decode(encoded_helper).decode("utf-16-le")
    assert f"program={executable.resolve()}" in helper
    assert "protocol=TCP" in helper
    assert "localport=45678" in helper
    assert "profile=private" in helper
    firewall.remove_temporary_windows_rule(result)
    assert not (tmp_path / f"{session_id}.active").exists()
