"""Deterministic deadline controls for the shipping Direct recovery fixture."""

import base64

import pytest

import test_direct_recovery_pipeline as pipeline
import mesh_chat.workspace_service as workspace_service
from mesh_chat.errors import NetworkUnavailable


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(pipeline.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(pipeline.time, "sleep", clock.sleep)
    return clock


def peer(command, call=None):
    result = pipeline.Peers.__new__(pipeline.Peers)
    result.command = command
    result.call = call or (lambda *args, **kwargs: {})
    result.workspace = {"id": "workspace", "general_channel_id": "general"}
    return result


def test_shared_deadline_expired_before_wait_rpc(clock):
    requests = []
    peers = peer(lambda *args, **kwargs: requests.append(args))
    clock.now = 226
    with pytest.raises(AssertionError):
        peers.wait(1, "list_workspace_messages", lambda _: True, timeout=None, deadline=225)
    assert requests == []


def test_shared_deadline_rejects_late_positive_wait_rpc(clock):
    requests = []

    def command(*args, **kwargs):
        requests.append(args)
        clock.now = 226
        return {"messages": [{"id": "event"}]}

    peers = peer(command)
    clock.now = 224
    with pytest.raises(AssertionError):
        peers.wait(1, "list_workspace_messages", lambda _: True, timeout=None, deadline=225)
    assert len(requests) == 1


def test_second_connected_peer_cannot_reset_shared_deadline(clock):
    requests = []

    def command(index, name, **kwargs):
        requests.append((index, name))
        if index == 1:
            clock.now = 226
        return [{"state": "connected", "authenticated_peer_live": True, "rns_ready": True}]

    def call(index, name, **kwargs):
        requests.append((index, name))
        return {"pending": 0, "paths": [{"recovery": True, "certificate": "fresh"}]}

    peers = peer(command, call)
    assert peers.connected(0, deadline=225)["paths"][0]["certificate"] == "fresh"
    clock.now = 224
    with pytest.raises(AssertionError):
        peers.connected(1, deadline=225)
    assert requests.count((1, "direct_recovery_status")) == 1
    assert (1, "recovery_diagnostic") not in requests


def test_shared_deadline_expired_before_connected_rpc(clock):
    requests = []
    peers = peer(lambda *args, **kwargs: requests.append(args))
    clock.now = 226
    with pytest.raises(AssertionError):
        peers.connected(0, deadline=225)
    assert requests == []


def test_shared_deadline_rejects_late_positive_connected_diagnostic(clock):
    requests = []

    def command(index, name, **kwargs):
        requests.append(name)
        return [{"state": "connected", "authenticated_peer_live": True, "rns_ready": True}]

    def call(index, name, **kwargs):
        requests.append(name)
        clock.now = 226
        return {"pending": 0, "paths": [{"recovery": True, "certificate": "fresh"}]}

    peers = peer(command, call)
    clock.now = 224
    with pytest.raises(AssertionError):
        peers.connected(0, deadline=225)
    assert requests == ["direct_recovery_status", "recovery_diagnostic"]


def test_queued_delivery_after_eighty_second_backoff_fits_shared_budget(clock):
    requests = []
    queued = {"id": "event"}

    def command(index, name, **kwargs):
        requests.append((index, clock.now))
        if index == 1 and clock.now < 155:
            return {"messages": []}
        message = {"id": "event", "delivery_summary": {"devices_reached": 1}}
        return {"messages": [message]}

    peers = peer(command)
    clock.now = 90
    peers.delivered(0, queued, deadline=225)
    assert clock.now >= 155
    assert clock.now < 225
    assert any(index == 1 for index, _ in requests)
    assert any(index == 0 for index, _ in requests)


def test_workspace_retry_due_index_waits_eighty_seconds_after_fifth_failed_send(clock, monkeypatch):
    class Store:
        def __init__(self):
            self.rows = {}

        def get(self, kind, identifier):
            return self.rows.get((kind, identifier))

        def put(self, kind, identifier, value):
            self.rows[(kind, identifier)] = value.copy()

        def put_many(self, records):
            for kind, identifier, value in records:
                self.put(kind, identifier, value)

        def opaque_id(self, *parts):
            return ":".join(parts)

    class Network:
        def __init__(self):
            self.calls = 0
            self.path = False

        def remember_contact(self, *args):
            pass

        def prefer_signed_route(self, *args, **kwargs):
            pass

        def recipient_ready_for_fields(self, *args):
            return True

        def path_known(self, *args):
            return self.path

        def send_with_fields(self, **kwargs):
            self.calls += 1
            if not self.path:
                raise NetworkUnavailable("No route")
            return "native-success"

    origin = 1_700_000_000.0
    monkeypatch.setattr(workspace_service.time, "time", lambda: origin + clock.now)
    service = workspace_service.WorkspaceServiceMixin()
    service.store = Store()
    service.network = Network()
    service.settings = type("Settings", (), {"tcp_clients": [], "approved_propagation_nodes": []})()
    service._connection_settings_dirty = False
    for name in (
        "_expire_workspace_invitations",
        "_advance_workspace_retention_jobs",
        "_advance_workspace_search_jobs",
        "_advance_workspace_history_jobs",
    ):
        setattr(service, name, lambda: None)

    delivery_id = "11111111-1111-4111-8111-111111111111"
    delivery = {
        "id": delivery_id,
        "workspace_id": "22222222-2222-4222-8222-222222222222",
        "kind": "workspace_event",
        "document": "opaque",
        "recipient_destination": "00" * 16,
        "recipient_public_identity": base64.b64encode(b"X" * 64).decode(),
        "recipient_hints": [],
        "state": "queued",
        "attempt_count": 0,
        "next_attempt_at": origin,
        "expires_at": origin + 1000,
    }
    service.store.put("workspace_delivery", delivery_id, delivery)
    service.store.put_many(service._due_records(add=[delivery]))
    expected = {0: (1, 5), 5: (2, 15), 15: (3, 35), 35: (4, 75), 75: (5, 155)}
    for elapsed, (attempts, next_due) in expected.items():
        clock.now = elapsed
        service._retry_workspace_outbox()
        current = service.store.get("workspace_delivery", delivery_id)
        assert (current["attempt_count"], current["next_attempt_at"] - origin) == (attempts, next_due)
    service.network.path = True
    for elapsed in (90, 135, 154):
        clock.now = elapsed
        service._retry_workspace_outbox()
        assert service.network.calls == 5
    clock.now = 155
    service._retry_workspace_outbox()
    assert service.network.calls == 6
    assert service.store.get("workspace_delivery", delivery_id)["native_message_id"] == "native-success"
