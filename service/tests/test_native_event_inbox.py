from queue import Empty

import pytest

from mesh_chat.native_webrtc_events import NativeEventInbox


def test_packet_saturation_does_not_delay_terminal_control():
    inbox = NativeEventInbox(data_count=1)
    inbox.put_nowait(("message", "session", "packet"))
    inbox.put_nowait(("message", "session", "dropped"))
    inbox.put_nowait(("closed", "session", ""))
    assert inbox.get_nowait() == ("closed", "session", "")
    assert inbox.get_nowait() == ("message", "session", "packet")
    assert inbox.statistics()["packet_drops"] == 1


def test_lifecycle_overflow_fails_closed_and_retains_shutdown_admission():
    inbox = NativeEventInbox(control_count=1)
    inbox.put_nowait(("open", "one", ""))
    inbox.put_nowait(("open", "two", ""))
    assert inbox.get_nowait() == ("overflow", "", "")
    inbox.put_nowait(("message", "one", "discarded after failure"))
    with pytest.raises(Empty):
        inbox.get_nowait()
    assert inbox.statistics()["failed"]
    inbox.put_nowait(None)
    assert inbox.get_nowait() is None


def test_duplicate_facts_coalesce_but_terminal_fact_is_not_lost():
    inbox = NativeEventInbox(control_count=2)
    for _ in range(100):
        inbox.put_nowait(("ice", "session", "connected"))
    inbox.put_nowait(("ice", "session", "closed"))
    assert inbox.statistics()["lifecycle_count"] == 2
    assert inbox.get_nowait()[2] == "connected"
    assert inbox.get_nowait()[2] == "closed"


def test_byte_limits_apply_and_lost_consent_control_fails_closed():
    inbox = NativeEventInbox(data_bytes=40)
    inbox.put_nowait(("control", "session", "too large"))
    assert inbox.get_nowait()[0] == "overflow"
    assert inbox.statistics()["data_bytes"] == 0


def test_draining_releases_byte_budget():
    inbox = NativeEventInbox(data_count=1, data_bytes=50)
    for _ in range(3):
        inbox.put_nowait(("message", "s", "packet"))
        assert inbox.get_nowait()[2] == "packet"
        assert inbox.statistics()["data_bytes"] == 0
    assert inbox.statistics()["packet_drops"] == 0
