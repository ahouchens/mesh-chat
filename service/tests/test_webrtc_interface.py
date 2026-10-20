from __future__ import annotations

from mesh_chat.webrtc_interface import WebRTCInterface


class Owner:
    def __init__(self) -> None:
        self.packets: list[bytes] = []

    def inbound(self, data: bytes, interface) -> None:
        assert interface is not None
        self.packets.append(data)


def _interface() -> tuple[WebRTCInterface, Owner, list[bytes]]:
    interface = object.__new__(WebRTCInterface)
    interface.owner = Owner()
    sent: list[bytes] = []
    interface._send_packet = sent.append
    interface.name = "test"
    interface.online = True
    interface.receives = True
    interface.rxb = 0
    interface.txb = 0
    interface.detached = False
    return interface, interface.owner, sent


def test_incoming_and_outgoing_packets_are_bounded() -> None:
    interface, owner, sent = _interface()
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


def test_detach_stops_both_directions() -> None:
    interface, owner, sent = _interface()
    interface.detach()
    interface.process_incoming(b"packet")
    interface.process_outgoing(b"out")
    assert owner.packets == []
    assert sent == []
    assert interface.online is False
    assert interface.receives is False
