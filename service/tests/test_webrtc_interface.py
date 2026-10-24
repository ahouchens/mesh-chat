from __future__ import annotations

import base64
import threading
from types import MethodType, SimpleNamespace

import pytest
import RNS
from RNS.Interfaces.Interface import Interface
from RNS.Transport import IDX_PT_RVCD_IF

from mesh_chat.errors import NetworkUnavailable
from mesh_chat.service import MeshChatService
from mesh_chat.webrtc_interface import WebRTCInterface


class Owner:
    def __init__(self) -> None:
        self.packets: list[bytes] = []

    def inbound(self, data: bytes, interface) -> None:
        assert interface is not None
        self.packets.append(data)


@pytest.fixture
def reticulum(monkeypatch):
    # Only supply configuration defaults, without starting RNS's global
    # transport threads. Keep the real constructor and registration code.
    defaults = {name: getattr(Interface, name.upper()) for name in (
        "ic_burst_hold", "ic_burst_freq_new", "ic_burst_freq",
        "ic_pr_burst_freq_new", "ic_pr_burst_freq", "ic_new_time",
        "ic_burst_penalty", "ic_held_release_interval", "ec_pr_freq", "egress_control",
    )}
    defaults["ic_max_held_announces"] = Interface.MAX_HELD_ANNOUNCES
    defaults["gravity"] = Interface.DEFAULT_GRAVITY
    configured = SimpleNamespace(
        is_connected_to_shared_instance=False,
        **{f"_default_{name}": lambda value=value: value for name, value in defaults.items()},
    )
    configured._add_interface = MethodType(RNS.Reticulum._add_interface, configured)
    monkeypatch.setattr(RNS.Reticulum, "get_instance", lambda: configured)
    monkeypatch.setattr(RNS.Transport, "interfaces", [])
    monkeypatch.setattr(RNS.Transport, "pending_links", [])
    monkeypatch.setattr(RNS.Transport, "active_links", [])
    monkeypatch.setattr(RNS.Transport, "pending_links_map", {})
    monkeypatch.setattr(RNS.Transport, "active_links_map", {})
    monkeypatch.setattr(RNS.Transport, "path_table", {})
    return configured


def _interface() -> tuple[WebRTCInterface, Owner, list[bytes]]:
    owner = Owner()
    sent: list[bytes] = []
    interface = WebRTCInterface(owner, sent.append, name="test")
    return interface, owner, sent


def test_incoming_and_outgoing_packets_are_bounded(reticulum) -> None:
    interface, owner, sent = _interface()
    assert interface.HW_MTU == WebRTCInterface.HW_MTU == 1064
    interface.process_incoming(b"packet")
    interface.process_outgoing(b"out")
    assert owner.packets == [b"packet"]
    assert sent == [b"out"]
    assert interface.rxb == 6
    assert interface.txb == 3

    interface.process_incoming(b"x" * (WebRTCInterface.HW_MTU + 1))
    interface.process_outgoing(b"y" * (WebRTCInterface.HW_MTU + 1))
    assert owner.packets == [b"packet"]
    assert sent == [b"out"]

    # The upper bound itself must remain usable in both directions.
    incoming = b"x" * interface.HW_MTU
    outgoing = b"y" * interface.HW_MTU
    interface.process_incoming(incoming)
    interface.process_outgoing(outgoing)
    interface.process_incoming(b"")
    interface.process_outgoing(b"")
    assert owner.packets == [b"packet", incoming]
    assert sent == [b"out", outgoing]
    assert interface.rxb == 6 + interface.HW_MTU
    assert interface.txb == 3 + interface.HW_MTU


def test_detach_stops_both_directions(reticulum) -> None:
    interface, owner, sent = _interface()
    reticulum._add_interface(interface, mode=Interface.MODE_POINT_TO_POINT)
    assert interface in RNS.Transport.interfaces
    interface.detach()
    interface.process_incoming(b"packet")
    interface.process_outgoing(b"out")
    assert owner.packets == []
    assert sent == []
    assert interface.online is False
    assert interface.receives is False
    assert interface not in RNS.Transport.interfaces


def test_detach_retires_only_its_links_and_routes(reticulum) -> None:
    interface, _, _ = _interface()
    replacement, _, _ = _interface()
    closed = []

    def link(via, name):
        value = SimpleNamespace(attached_interface=via, status=RNS.Link.ACTIVE, link_id=name.encode())
        def teardown():
            closed.append(name)
            value.status = RNS.Link.CLOSED
        value.teardown = teardown
        return value

    pending, active, other = link(interface, "pending"), link(interface, "active"), link(replacement, "other")
    RNS.Transport.pending_links.extend([pending, active, other])
    RNS.Transport.active_links.extend([active, other])
    RNS.Transport.pending_links_map.update({item.link_id: item for item in RNS.Transport.pending_links})
    RNS.Transport.active_links_map.update({item.link_id: item for item in RNS.Transport.active_links})
    for destination, via in ((b"retired", interface), (b"replacement", replacement)):
        entry = [None] * (IDX_PT_RVCD_IF + 1)
        entry[IDX_PT_RVCD_IF] = via
        RNS.Transport.path_table[destination] = entry

    interface.detach()

    assert closed == ["pending", "active"]
    assert not RNS.Transport.has_path(b"retired")
    assert RNS.Transport.next_hop_interface(b"replacement") is replacement
    assert replacement.online
    assert RNS.Transport.pending_links == RNS.Transport.active_links == [other]
    assert RNS.Transport.pending_links_map == RNS.Transport.active_links_map == {other.link_id: other}


@pytest.fixture
def bridge_service(reticulum, monkeypatch):
    service = object.__new__(MeshChatService)
    service._shutdown = threading.Event()
    service._webrtc_bridges = {}
    service.network = SimpleNamespace(reticulum=reticulum, reannounce=lambda: None)
    service._changed = lambda: None
    service.emit = lambda _event: None
    monkeypatch.setattr(
        "mesh_chat.service.threading.Thread",
        lambda **_kwargs: SimpleNamespace(start=lambda: None),
    )
    return service


def test_attach_registers_transport_defaults_before_announcing(bridge_service, monkeypatch) -> None:
    service = bridge_service
    emitted = []
    received = []
    service.emit = emitted.append
    monkeypatch.setattr(
        RNS.Transport, "inbound", lambda data, interface: received.append((data, interface))
    )

    def reannounce():
        interface = next(iter(service._webrtc_bridges.values()))
        assert interface in RNS.Transport.interfaces
        assert interface.HW_MTU == 1064
        assert interface.mode == Interface.MODE_POINT_TO_POINT
        assert interface.ifac_size == Interface.DEFAULT_IFAC_SIZE
        assert interface.ifac_netname is None
        assert interface.ifac_netkey is None
        assert interface.announce_rate_target is None
        assert interface.announce_rate_grace is None
        assert interface.announce_rate_penalty is None
        interface.process_outgoing(b"announce")

    service.network.reannounce = reannounce
    result = service.webrtc_attach()
    bridge_id = result["bridge_id"]
    interface = service._webrtc_bridges[bridge_id]
    assert result["max_packet"] == interface.HW_MTU
    assert emitted == [{
        "type": "event", "event": "webrtc_packet", "bridge_id": bridge_id,
        "data": base64.b64encode(b"announce").decode("ascii"),
    }]
    assert service.webrtc_packet(bridge_id, base64.b64encode(b"incoming").decode("ascii")) == {
        "accepted": 8,
    }
    assert received == [(b"incoming", interface)]
    assert service.webrtc_detach(bridge_id) == {"state": "closed"}
    assert not service._webrtc_bridges
    assert not RNS.Transport.interfaces


def test_attach_cleans_up_partial_registration(bridge_service, monkeypatch) -> None:
    failed = []

    def fail_final_init(interface):
        failed.append(interface)
        raise RuntimeError("final initialization failed")

    monkeypatch.setattr(WebRTCInterface, "final_init", fail_final_init)
    with pytest.raises(NetworkUnavailable, match="Could not attach"):
        bridge_service.webrtc_attach()
    assert not bridge_service._webrtc_bridges
    assert not RNS.Transport.interfaces
    assert len(failed) == 1
    assert failed[0].detached
    assert not failed[0].online


def test_attach_rejects_registration_skipped_by_shared_instance(bridge_service) -> None:
    bridge_service.network.reticulum.is_connected_to_shared_instance = True
    with pytest.raises(NetworkUnavailable, match="Could not attach"):
        bridge_service.webrtc_attach()
    assert not bridge_service._webrtc_bridges
    assert not RNS.Transport.interfaces


def test_service_detach_discards_only_retired_lxmf_link_cache(bridge_service) -> None:
    service = bridge_service
    retired = service.webrtc_attach()["bridge_id"]
    kept = service.webrtc_attach()["bridge_id"]
    old_link = SimpleNamespace(attached_interface=service._webrtc_bridges[retired])
    kept_link = SimpleNamespace(attached_interface=service._webrtc_bridges[kept])
    service.network.router = SimpleNamespace(
        outbound_processing_lock=threading.Lock(),
        direct_links={b"old": old_link, b"kept": kept_link},
        backchannel_links={b"old-back": old_link, b"kept-back": kept_link},
    )

    service.webrtc_detach(retired)

    assert service.network.router.direct_links == {b"kept": kept_link}
    assert service.network.router.backchannel_links == {b"kept-back": kept_link}
    assert service._webrtc_bridges[kept].online
