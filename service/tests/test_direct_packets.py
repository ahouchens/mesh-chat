import queue
import threading

import pytest

from mesh_chat.direct_packets import PacketRuntime
from mesh_chat.errors import ValidationError


class Interface:
    def __init__(self):
        self.online = True
        self.detached = False
        self.received = []
        self.retired = threading.Event()
        self.output = queue.Queue()

    def check_health(self):
        return self.online

    def receive(self, session, packet):
        self.received.append(packet)

    def take_outgoing(self, session):
        try:
            return self.output.get_nowait()
        except queue.Empty:
            return None

    def engine_lost(self, session):
        self.online = False
        self.detached = True
        self.retired.set()


def open_pump(runtime, interface, *, authority=lambda: True, incoming=None, outgoing=None):
    lost, cancel = threading.Event(), threading.Event()
    pump = runtime.open(interface, object(), incoming or queue.Queue(maxsize=1),
                        outgoing or queue.Queue(maxsize=1), lost, cancel, authority)
    return pump, lost, cancel


@pytest.mark.parametrize("failure", ["authority", "authority-error", "channel", "eof", "carrier", "health"])
def test_packet_failures_retire_interface_and_signal_cancellation(failure):
    runtime, interface = PacketRuntime(), Interface()
    incoming = queue.Queue(maxsize=1)
    def authority():
        if failure == "authority-error":
            raise RuntimeError("private authority error")
        return failure != "authority"
    if failure == "channel":
        class BrokenQueue:
            def get(self, **kwargs):
                raise OSError("pipe closed")
        incoming = BrokenQueue()
    elif failure == "eof":
        incoming.put(None)
    elif failure == "health":
        interface.check_health = lambda: False
    pump, lost, cancel = open_pump(runtime, interface, incoming=incoming, authority=authority)
    try:
        if failure == "carrier":
            lost.set()
        assert cancel.wait(2)
        pump.join(2)
        assert not pump.is_alive() and interface.detached
    finally:
        runtime.retire_all(close=True)


def test_close_does_not_wait_for_authority_or_deliver_queued_packet():
    runtime, interface = PacketRuntime(), Interface()
    entered, release = threading.Event(), threading.Event()
    incoming = queue.Queue(maxsize=1)
    incoming.put(b"must not deliver after close")
    def authority():
        entered.set()
        assert release.wait(3)
        return True
    pump, _, cancel = open_pump(runtime, interface, incoming=incoming, authority=authority)
    try:
        assert entered.wait(2)
        runtime.retire_all(close=True)
        assert cancel.is_set()
        with pytest.raises(ValidationError):
            open_pump(runtime, Interface())
    finally:
        release.set()
        pump.join(2)
    assert interface.retired.is_set() and interface.received == []


def test_full_output_queue_does_not_block_retirement():
    runtime, interface = PacketRuntime(), Interface()
    outgoing = queue.Queue(maxsize=1)
    outgoing.put(b"already full")
    for _ in range(128):
        interface.output.put(b"packet")
    pump, _, cancel = open_pump(runtime, interface, outgoing=outgoing)
    runtime.retire_all()
    assert cancel.wait(2)
    pump.join(2)
    assert not pump.is_alive() and interface.retired.is_set()
    assert outgoing.get_nowait() == b"already full"


def test_suspension_keeps_budget_until_blocked_pumps_exit():
    runtime = PacketRuntime()
    release = threading.Event()
    entered = [threading.Event() for _ in range(runtime.MAX_PUMPS)]
    interfaces = [Interface() for _ in entered]
    pumps = []
    try:
        for interface, event in zip(interfaces, entered):
            def authority(event=event):
                event.set()
                assert release.wait(5)
                return True
            pumps.append(open_pump(runtime, interface, authority=authority)[0])
            assert event.wait(2)
        runtime.retire_all()
        with pytest.raises(ValidationError):
            open_pump(runtime, Interface())
    finally:
        release.set()
        for pump in pumps:
            pump.join(2)
    fresh, _, _ = open_pump(runtime, Interface())
    runtime.retire_all(close=True)
    fresh.join(2)
    assert not fresh.is_alive()


def test_interface_cannot_have_competing_packet_readers():
    runtime, interface = PacketRuntime(), Interface()
    pump, _, _ = open_pump(runtime, interface)
    try:
        with pytest.raises(ValidationError, match="packet owner"):
            open_pump(runtime, interface)
    finally:
        runtime.retire_all(close=True)
        pump.join(2)
