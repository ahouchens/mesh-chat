from types import SimpleNamespace

import pytest
import RNS
from RNS.Interfaces.Interface import Interface

from tools.direct_packet_adapter import MeshDirectInterface, ProfileBudget, scoped_message_allowed


@pytest.fixture
def adapter(monkeypatch):
    defaults = {name: getattr(Interface, name.upper()) for name in (
        "ic_burst_hold", "ic_burst_freq_new", "ic_burst_freq", "ic_pr_burst_freq_new",
        "ic_pr_burst_freq", "ic_new_time", "ic_burst_penalty", "ic_held_release_interval",
        "ec_pr_freq", "egress_control",
    )}
    defaults["ic_max_held_announces"] = Interface.MAX_HELD_ANNOUNCES
    monkeypatch.setattr(RNS.Reticulum, "get_instance", lambda: SimpleNamespace(**{
        f"_default_{name}": lambda value=value: value for name, value in defaults.items()
    }))
    monkeypatch.setattr(RNS.Reticulum, "transport_enabled", lambda: False)
    monkeypatch.setattr(RNS.Transport, "interfaces", [])
    received, clock = [], [100.0]
    interface = MeshDirectInterface(SimpleNamespace(inbound=lambda data, _: received.append(data)), budget=ProfileBudget(), clock=lambda: clock[0])
    yield interface, object(), received, clock
    interface.detach()


def test_authentication_health_and_stale_callback_boundary(adapter):
    interface, session, received, clock = adapter
    assert not interface.receive(session, b"before authentication")
    interface.activate(session, expires_at=200)
    assert not interface.receive(object(), b"different peer")
    assert interface.receive(session, b"one packet")
    assert received == [b"one packet"]
    interface.engine_lost(object())
    assert interface.online
    interface.engine_lost(session)
    assert not interface.online
    assert not interface.receive(session, b"stale callback")
    with pytest.raises(ValueError):
        interface.activate(object(), expires_at=200)


def test_packet_and_queue_bounds_and_reclaimed_capacity(adapter):
    interface, session, _, _ = adapter
    interface.activate(session, expires_at=200)
    for packet in (b"", b"a" * 517):
        assert not interface.receive(session, packet)
        interface.process_outgoing(packet)
    for _ in range(129):
        interface.process_outgoing(b"x")
    assert len(interface._packets) == 128
    assert interface.take_outgoing(object()) is None
    for _ in range(128):
        assert interface.take_outgoing(session) == b"x"
    assert interface._bytes == 0
    for _ in range(128):
        interface.process_outgoing(b"y" * 516)
    assert interface._bytes <= 64 * 1024
    interface.detach()
    assert interface._bytes == 0 and not interface._packets


def test_pending_refuses_other_interfaces_and_transport(adapter, monkeypatch):
    interface, session, _, _ = adapter
    monkeypatch.setattr(RNS.Transport, "interfaces", [object()])
    with pytest.raises(ValueError):
        interface.activate(session, expires_at=200, pending=True)
    monkeypatch.setattr(RNS.Transport, "interfaces", [])
    monkeypatch.setattr(RNS.Reticulum, "transport_enabled", lambda: True)
    with pytest.raises(ValueError):
        interface.activate(session, expires_at=200, pending=True)


def test_pending_closes_if_routing_changes_and_at_deadline(adapter, monkeypatch):
    interface, session, _, clock = adapter
    interface.activate(session, expires_at=1000, pending=True)
    assert interface._deadline == 400
    monkeypatch.setattr(RNS.Transport, "interfaces", [interface, object()])
    assert not interface.receive(session, b"must not enter router")
    assert interface.detached


def test_pending_rate_budget_and_expiry(adapter):
    interface, session, received, clock = adapter
    interface.activate(session, expires_at=101, pending=True)
    for _ in range(32):
        assert interface.receive(session, b"packet")
    assert not interface.receive(session, b"too fast")
    clock[0] += 0.5
    assert interface.receive(session, b"refilled")
    interface.process_outgoing(b"queued")
    clock[0] = 101
    assert interface.take_outgoing(session) is None
    assert interface.detached and not interface.online


def test_scoped_bootstrap_rejects_chat_foreign_peers_and_other_workspaces():
    import time
    import uuid
    from mesh_chat.workspace_wire import build_workspace_fields
    peer, other_peer = b"a" * 16, b"b" * 16
    workspace, other_workspace = str(uuid.uuid4()), str(uuid.uuid4())
    def message(kind, source=peer, scope=workspace):
        fields = build_workspace_fields(kind=kind, logical_id=str(uuid.uuid4()),
            workspace_id=scope, expires_at=int(time.time()) + 60, document="{}")
        return SimpleNamespace(source_hash=source, content=b"", get_fields=lambda: fields)
    assert scoped_message_allowed(message("workspace_join"), peer, workspace, pending=True)
    assert not scoped_message_allowed(message("workspace_join", other_peer), peer, workspace, pending=True)
    assert not scoped_message_allowed(message("workspace_join", scope=other_workspace), peer, workspace, pending=True)
    assert not scoped_message_allowed(message("workspace_event"), peer, workspace, pending=True)
    assert scoped_message_allowed(message("workspace_event"), peer, workspace, pending=False)
    assert not scoped_message_allowed(message("workspace_event", other_peer), peer, workspace, pending=False)


@pytest.mark.parametrize("size,maximum", [(1, 4096), (516, (2 * 1024 * 1024) // 516)])
def test_pending_cumulative_packet_and_byte_budgets(adapter, size, maximum):
    interface, session, received, clock = adapter
    interface.activate(session, expires_at=1000, pending=True)
    for index in range(maximum):
        if index % 32 == 0:
            clock[0] += 1
        assert interface.receive(session, b"x" * size)
    clock[0] += 1
    assert not interface.receive(session, b"x" * size)
    assert len(received) == maximum


def test_profile_budget_is_shared_and_reclaimed_on_pop_and_engine_loss(adapter):
    original, _, _, clock = adapter
    pool = ProfileBudget(max_sessions=2, max_bytes=600)
    a = MeshDirectInterface(original.owner, budget=pool, clock=lambda: clock[0])
    b = MeshDirectInterface(original.owner, budget=pool, clock=lambda: clock[0])
    c = MeshDirectInterface(original.owner, budget=pool, clock=lambda: clock[0])
    sa, sb = object(), object()
    try:
        a.activate(sa, expires_at=200)
        b.activate(sb, expires_at=200)
        with pytest.raises(ValueError):
            c.activate(object(), expires_at=200)
        a.process_outgoing(b"a" * 500)
        b.process_outgoing(b"b" * 200)
        assert pool.queued_bytes == 500 and not b._packets
        assert a.take_outgoing(sa) == b"a" * 500
        b.process_outgoing(b"b" * 200)
        assert pool.queued_bytes == 200
        b.engine_lost(sb)
        assert pool.queued_bytes == 0
        c.activate(object(), expires_at=200)
        b.detach()  # repeated teardown cannot release someone else's credits
        assert len(pool._owners) == 2
    finally:
        for interface in (a, b, c):
            interface.detach()
    assert pool.queued_bytes == 0 and not pool._owners
