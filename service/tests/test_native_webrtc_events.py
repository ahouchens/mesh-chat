from __future__ import annotations

import queue
import threading
import time

from mesh_chat.service import MeshChatService


def test_native_callback_enqueues_without_taking_dispatch_lock() -> None:
    service = object.__new__(MeshChatService)
    service._shutdown = threading.Event()
    service._native_webrtc_events = queue.Queue()
    service._dispatch_lock = threading.RLock()
    service._dispatch_lock.acquire()
    try:
        # This is what a WebRTC callback thread does while a command that called
        # into native WebRTC still holds the dispatch lock.
        service.native_webrtc_event("message", "session-1", "cGFja2V0")
        queued = service._native_webrtc_events.get_nowait()
        assert queued == ("message", "session-1", "cGFja2V0")
    finally:
        service._dispatch_lock.release()


def test_native_event_worker_drains_in_order() -> None:
    class Host(object):
        def __init__(self) -> None:
            self.seen: list[tuple[str, str, str]] = []

    host = Host()
    service = object.__new__(MeshChatService)
    service._shutdown = threading.Event()
    service._native_webrtc_events = queue.Queue()
    service._handle_native_webrtc_event = lambda event, session_id, data: host.seen.append(
        (event, session_id, data)
    )
    thread = threading.Thread(target=service._native_webrtc_event_loop, daemon=True)
    thread.start()
    try:
        service.native_webrtc_event("open", "session-1")
        service.native_webrtc_event("message", "session-1", "cGFja2V0")
        deadline = time.monotonic() + 2
        while len(host.seen) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert host.seen == [
            ("open", "session-1", ""),
            ("message", "session-1", "cGFja2V0"),
        ]
    finally:
        service._shutdown.set()
        service._native_webrtc_events.put_nowait(None)
        thread.join(timeout=1)
