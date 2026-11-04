"""Exact native-session retirement when a contact is deleted."""

from threading import RLock

from mesh_chat.service import MeshChatService


def test_retire_native_peer_closes_only_matching_live_sessions():
    service = object.__new__(MeshChatService)
    service._native_webrtc_lock = RLock()
    service._native_webrtc_peers = {
        "first": "aa" * 16,
        "other": "bb" * 16,
        "second": "aa" * 16,
        "retired": "aa" * 16,
    }
    service._native_webrtc_live = {"first", "other", "second"}
    closed = []
    service.native_webrtc_close = lambda session: closed.append(session)
    assert service.retire_native_peer("aa" * 16) == ["first", "second"]
    assert closed == ["first", "second"]
    assert service._native_webrtc_peers["other"] == "bb" * 16
    assert service.retire_native_peer("cc" * 16) == []
