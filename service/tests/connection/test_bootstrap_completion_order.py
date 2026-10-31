from collections import deque
import queue
from types import SimpleNamespace

from mesh_chat.isolated_bootstrap import IsolatedBootstrapEngine


def engine_with_packets(packets):
    engine = object.__new__(IsolatedBootstrapEngine)
    engine.events = queue.Queue()
    engine._pending_event = None
    engine._check = lambda **_: None
    engine.session, engine.peer = object(), b"peer"
    engine.network = SimpleNamespace(recipient_ready=lambda _: True)
    outgoing = deque(packets)
    engine.interface = SimpleNamespace(take_outgoing=lambda _: outgoing.popleft() if outgoing else None)
    return engine, outgoing


def test_completion_arriving_after_packet_drain_waits_for_its_causal_proof():
    engine, packets = engine_with_packets([])
    event = {"kind": "inbound", "packed": b"contact acceptance"}

    def take(_):
        if packets:
            return packets.popleft()
        if engine.events.empty():
            packets.append(b"proof")
            engine.events.put(event)
        return None

    engine.interface.take_outgoing = take
    first = engine.exchange([])
    assert first["events"] == []
    engine.interface.take_outgoing = lambda _: packets.popleft() if packets else None
    second = engine.exchange([])
    assert second["packets"] == [b"proof"]
    assert second["events"] == [event]


def test_completion_waits_until_all_preceding_packets_fit_the_bounded_response():
    engine, _ = engine_with_packets([b"data"] * 32 + [b"proof"])
    event = {"kind": "inbound", "packed": b"contact acceptance"}
    engine.events.put(event)
    first = engine.exchange([])
    assert len(first["packets"]) == 32
    assert first["events"] == []
    second = engine.exchange([])
    assert second["packets"] == [b"proof"]
    assert second["events"] == [event]
    assert engine.exchange([])["events"] == []
