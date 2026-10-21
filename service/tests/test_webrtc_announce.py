from __future__ import annotations

import threading
from types import SimpleNamespace

from mesh_chat.service import MeshChatService


def test_webrtc_attach_reannounces_only_for_live_bridge() -> None:
    service = object.__new__(MeshChatService)
    service._shutdown = threading.Event()
    service._webrtc_bridges = {"live": object()}
    calls: list[str] = []
    service.network = SimpleNamespace(reannounce=lambda: calls.append("announce"))

    service._webrtc_announce_later("live", 0)
    service._webrtc_announce_later("closed", 0)

    assert calls == ["announce"]
