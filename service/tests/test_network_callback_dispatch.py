from __future__ import annotations

import threading
import time
from collections import deque
from types import SimpleNamespace

import LXMF
import RNS

from mesh_chat.models import DeliveryState
from mesh_chat.network import ReticulumNetwork
from mesh_chat.service import MeshChatService


def _configure_dispatcher(
    network: ReticulumNetwork, *, capacity: int = 256, start: bool = True
) -> None:
    network._callback_capacity = capacity
    network._callback_items = deque()
    network._callback_condition = threading.Condition()
    network._callback_accepting = True
    network._callback_cancelled = False
    network._callback_dropped_inbound = 0
    network._callback_dropped_status = 0
    network._callback_thread = threading.Thread(
        target=network._dispatch_callbacks,
        daemon=True,
    )
    if start:
        network._callback_thread.start()


def _stop_dispatcher(network: ReticulumNetwork) -> None:
    assert network._stop_callback_dispatcher()
    assert not network._callback_thread.is_alive()


def test_native_failure_returns_without_waiting_for_service_lock() -> None:
    """LXMF callbacks must not wait on send or service lock ownership."""

    network = ReticulumNetwork.__new__(ReticulumNetwork)
    network._send_lock = threading.RLock()
    network._message_lock = threading.RLock()
    message = SimpleNamespace(hash=b"native-hash", message_id=b"native-id")
    network._messages = {"logical": [message]}
    _configure_dispatcher(network)
    service_lock = threading.Lock()
    callback_finished = threading.Event()
    native_returned = threading.Event()
    observed: list[tuple[str, DeliveryState, str | None]] = []

    def status_callback(
        logical_id: str, state: DeliveryState, native_id: str | None
    ) -> None:
        with service_lock:
            observed.append((logical_id, state, native_id))
            callback_finished.set()

    network._status_callback = status_callback
    service_lock.acquire()
    network._send_lock.acquire()
    try:
        native_thread = threading.Thread(
            target=lambda: (
                network._on_native_failure("logical", message),
                native_returned.set(),
            )
        )
        native_thread.start()

        # The worker is intentionally blocked on the simulated service lock,
        # but the LXMF/native thread must already have returned to release its
        # own outbound-processing lock.
        assert native_returned.wait(1)
        assert not callback_finished.is_set()
        assert "logical" not in network._messages
    finally:
        network._send_lock.release()
        service_lock.release()

    native_thread.join(timeout=1)
    assert callback_finished.wait(1)
    assert observed == [
        ("logical", DeliveryState.QUEUED, b"native-hash".hex())
    ]
    _stop_dispatcher(network)


def test_cancel_outbound_releases_every_native_attempt_for_logical_id() -> None:
    # Even two distinct LXMessage objects with the same packed ID must each be
    # cancelled; LXMRouter.cancel_outbound selects one matching object per call.
    first = SimpleNamespace(hash=b"first-hash", message_id=b"same-id")
    second = SimpleNamespace(hash=b"second-hash", message_id=b"same-id")

    class Router:
        def __init__(self) -> None:
            self.pending_outbound = [first, second]
            self.cancelled: list[bytes] = []

        def cancel_outbound(self, message_id: bytes) -> None:
            self.cancelled.append(message_id)
            match = next(
                (
                    message
                    for message in reversed(self.pending_outbound)
                    if message.message_id == message_id
                ),
                None,
            )
            if match is not None:
                self.pending_outbound.remove(match)

    network = ReticulumNetwork.__new__(ReticulumNetwork)
    network._send_lock = threading.RLock()
    network._message_lock = threading.RLock()
    network._messages = {
        "logical": [first, second]
    }
    network.router = Router()

    assert network.cancel_outbound({"logical"}) == 2
    assert network._messages == {}
    assert network.router.pending_outbound == []
    assert network.router.cancelled == [b"same-id", b"same-id"]


def test_native_delivery_releases_plaintext_reference_at_transport_handoff() -> None:
    network = ReticulumNetwork.__new__(ReticulumNetwork)
    network._send_lock = threading.RLock()
    network._message_lock = threading.RLock()
    message = SimpleNamespace(
        hash=b"native-hash",
        message_id=b"native-id",
        method=LXMF.LXMessage.DIRECT,
        state=LXMF.LXMessage.DELIVERED,
    )
    network._messages = {"logical": [message]}
    observed: list[tuple[str, DeliveryState, str | None]] = []
    network._status_callback = lambda *args: observed.append(args)
    network._defer_callback = lambda callback, *args, **_kwargs: callback(*args)

    network._on_native_delivery("logical", message)

    assert network._messages == {}
    assert observed == [
        ("logical", DeliveryState.RECEIVED_BY_ENDPOINT, b"native-hash".hex())
    ]


def test_inbound_callback_returns_without_waiting_for_service_lock() -> None:
    network = ReticulumNetwork.__new__(ReticulumNetwork)
    network.delivery_destination = SimpleNamespace(hash=b"local")
    _configure_dispatcher(network)
    service_lock = threading.Lock()
    callback_finished = threading.Event()
    native_returned = threading.Event()
    message = SimpleNamespace(
        destination_hash=b"local",
        signature_validated=True,
    )

    def inbound_callback(received: object) -> None:
        with service_lock:
            assert received is message
            callback_finished.set()

    network._inbound_callback = inbound_callback
    service_lock.acquire()
    try:
        native_thread = threading.Thread(
            target=lambda: (network._on_inbound(message), native_returned.set())
        )
        native_thread.start()
        assert native_returned.wait(1)
        assert not callback_finished.is_set()
    finally:
        service_lock.release()

    native_thread.join(timeout=1)
    assert callback_finished.wait(1)
    _stop_dispatcher(network)


def test_shutdown_does_not_wait_indefinitely_for_callback_worker(
    monkeypatch,
) -> None:
    network = ReticulumNetwork.__new__(ReticulumNetwork)
    network.router = SimpleNamespace(exit_handler=lambda: None)
    _configure_dispatcher(network)
    callback_started = threading.Event()
    release_callback = threading.Event()
    cancelled_callback_ran = threading.Event()

    def blocked_callback() -> None:
        callback_started.set()
        release_callback.wait(2)

    monkeypatch.setattr(RNS.Reticulum, "exit_handler", lambda: None)
    network._defer_callback(blocked_callback)
    assert callback_started.wait(1)
    network._defer_callback(cancelled_callback_ran.set)

    started = time.monotonic()
    stopped = network.shutdown()
    elapsed = time.monotonic() - started

    assert elapsed < 1.5
    assert stopped is False
    assert network._callback_thread.is_alive()
    assert not cancelled_callback_ran.is_set()
    assert not network._callback_items
    release_callback.set()
    network._callback_thread.join(timeout=2)
    assert not network._callback_thread.is_alive()
    assert not cancelled_callback_ran.is_set()


def test_status_callbacks_preserve_delivery_then_failure_order() -> None:
    network = ReticulumNetwork.__new__(ReticulumNetwork)
    _configure_dispatcher(network, capacity=2, start=False)
    observed: list[str] = []

    assert network._defer_callback(
        observed.append, "delivered", kind="status"
    )
    assert network._defer_callback(
        observed.append, "later-failure", kind="status"
    )
    assert len(network._callback_items) == 2

    network._callback_thread.start()
    _stop_dispatcher(network)
    assert observed == ["delivered", "later-failure"]
    assert network._callback_dropped_status == 0


def test_inbound_displaces_status_and_runs_first_at_capacity() -> None:
    network = ReticulumNetwork.__new__(ReticulumNetwork)
    _configure_dispatcher(network, capacity=2, start=False)
    observed: list[str] = []

    assert network._defer_callback(
        observed.append, "old-status", kind="status"
    )
    assert network._defer_callback(
        observed.append, "new-status", kind="status"
    )
    assert network._defer_callback(observed.append, "inbound", kind="inbound")

    network._callback_thread.start()
    _stop_dispatcher(network)
    assert observed == ["inbound", "new-status"]
    assert network._callback_dropped_status == 1
    assert network._callback_dropped_inbound == 0


def test_all_inbound_saturation_is_bounded_and_producer_returns() -> None:
    network = ReticulumNetwork.__new__(ReticulumNetwork)
    _configure_dispatcher(network, capacity=2, start=False)

    assert network._defer_callback(lambda: None, kind="inbound")
    assert network._defer_callback(lambda: None, kind="inbound")
    returned: list[bool] = []
    producer = threading.Thread(
        target=lambda: returned.append(
            network._defer_callback(lambda: None, kind="inbound")
        )
    )
    producer.start()
    producer.join(timeout=0.25)

    assert not producer.is_alive()
    assert returned == [False]
    assert len(network._callback_items) == 2
    assert network._callback_dropped_inbound == 1


def test_clean_shutdown_drains_accepted_callbacks(monkeypatch) -> None:
    network = ReticulumNetwork.__new__(ReticulumNetwork)
    network.router = SimpleNamespace(exit_handler=lambda: None)
    _configure_dispatcher(network, start=False)
    observed: list[str] = []
    network._defer_callback(observed.append, "accepted", kind="inbound")
    network._callback_thread.start()
    monkeypatch.setattr(RNS.Reticulum, "exit_handler", lambda: None)

    assert network.shutdown() is True
    assert observed == ["accepted"]
    assert not network._callback_thread.is_alive()


def test_service_close_defers_vault_close_until_active_callback_finishes(
    monkeypatch,
) -> None:
    network = ReticulumNetwork.__new__(ReticulumNetwork)
    network.router = SimpleNamespace(exit_handler=lambda: None)
    _configure_dispatcher(network)
    callback_started = threading.Event()
    release_callback = threading.Event()

    def blocked_callback() -> None:
        callback_started.set()
        release_callback.wait(2)

    network._defer_callback(blocked_callback)
    assert callback_started.wait(1)
    monkeypatch.setattr(RNS.Reticulum, "exit_handler", lambda: None)

    service = MeshChatService.__new__(MeshChatService)
    service._shutdown = threading.Event()
    service._dispatch_lock = threading.RLock()
    service._close_lock = threading.Lock()
    service._close_started = False
    service._store_closed = False
    service._close_finalizer = None
    service._retry_thread = threading.Thread(target=lambda: None)
    service.network = network
    close_count = 0
    closed = threading.Event()

    def close_store() -> None:
        nonlocal close_count
        close_count += 1
        closed.set()

    service.store = SimpleNamespace(close=close_store)
    service.close()

    assert service._shutdown.is_set()
    assert not closed.is_set()
    assert service._close_finalizer is not None
    release_callback.set()
    assert closed.wait(2)
    service._close_finalizer.join(timeout=2)
    assert not service._close_finalizer.is_alive()

    # A repeated lifecycle close cannot close the vault a second time.
    service.close()
    assert close_count == 1


def test_service_close_closes_vault_after_workers_stop() -> None:
    service = MeshChatService.__new__(MeshChatService)
    service._shutdown = threading.Event()
    service._dispatch_lock = threading.RLock()
    service._close_lock = threading.Lock()
    service._close_started = False
    service._store_closed = False
    service._close_finalizer = None
    service._retry_thread = threading.Thread(target=lambda: None)
    service.network = SimpleNamespace(shutdown=lambda: True)
    closed = threading.Event()
    service.store = SimpleNamespace(close=closed.set)

    service.close()

    assert closed.is_set()
