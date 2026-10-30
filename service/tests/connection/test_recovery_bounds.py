from types import SimpleNamespace

import pytest

from mesh_chat.core_api.messages import MessageObservation
from mesh_chat.core_api.recovery import EventPage, ListedMessage, MessagePage
from test_core_messages import host, client
from test_core_replay import snapshot, poll


@pytest.mark.parametrize("page", [
    MessagePage((), "short", None),
    MessagePage((), None, None),
    MessagePage((), "x" * 64, "y" * 64),
    MessagePage((ListedMessage("raw-id", MessageObservation("peer", "hi", "queued", 1)),), None, "x" * 64),
    MessagePage(tuple(ListedMessage("m" * 64, MessageObservation("peer", "hi", "queued", 1)) for _ in range(129)), None, "x" * 64),
    MessagePage(tuple(ListedMessage("m" * 64, MessageObservation("peer", "\x01" * 16384, "queued", 1)) for _ in range(128)), None, "x" * 64),
], ids=["short_cursor", "no_continuation", "ambiguous_continuation", "private_handle", "count", "bytes"])
def test_facade_rejects_invalid_or_unbounded_snapshot_port_results(host, page):
    session, _, profile, _ = client(host())
    session._recovery = SimpleNamespace(snapshot=lambda *_: page)
    assert snapshot(session, profile)["error"]["code"] == "internal"


@pytest.mark.parametrize("page", [EventPage((), "x" * 1025, False), EventPage((), "x" * 64, "false")])
def test_facade_rejects_malformed_replay_metadata(host, page):
    session, _, profile, _ = client(host())
    session._recovery = SimpleNamespace(poll=lambda *_: page)
    assert poll(session, profile, "x" * 64)["error"]["code"] == "internal"
