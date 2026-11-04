"""Durable message and receipt delivery over the native WebRTC datachannel.

Each peer runs in its own process because Reticulum owns process-global state.
The native host is the only packet carrier; there is no in-memory relay. This is
component integration, not Android/Windows interoperability or physical proof.
"""

from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
import queue
import time
import traceback
from typing import Any
import uuid

import pytest

ICE = {"iceServers": [], "iceTransportPolicy": "all"}
CHANNELS = [{"label": "mesh-reticulum", "binary": True, "ordered": True}]


def _native_peer(root: str, commands: Any, replies: Any, vault_key: bytes) -> None:
    from mesh_chat.native_windows_webrtc import WindowsNativeWebRTCHost
    from mesh_chat.reticulum_config import NetworkSettings
    from mesh_chat.service import MeshChatService
    from mesh_chat.vault import VaultStore

    class FaultyHost(WindowsNativeWebRTCHost):
        """Test-only packet impairment at the native host send boundary."""

        def __init__(self, notify):
            super().__init__(notify)
            self.fault = "pass"
            self.sent = 0

        def send(self, resource, packet):
            self.sent += 1
            if self.fault == "drop":
                return True
            if self.fault == "loss" and self.sent % 2 == 0:
                return True
            accepted = super().send(resource, packet)
            if self.fault == "duplicate":
                super().send(resource, packet)
            return accepted

    service = None
    host = None
    try:
        store = VaultStore(Path(root), vault_key, allow_unprotected_for_tests=True)
        store.put("settings", "network",
                  NetworkSettings(nearby_discovery=False, lan_fallback=False).to_dict())
        service_holder = [None]
        host = FaultyHost(
            lambda *event: service_holder[0].native_webrtc_event(*event)
            if service_holder[0] is not None else None)
        service = MeshChatService(store, Path(root), lambda _: None,
                                  native_webrtc_host=host)
        service_holder[0] = service
        profile = (store.get("profile", "local")
                   or service.create_profile(Path(root).name))
        assert service.network is not None, service._network_error
        replies.put({"ok": True, "result": profile})
        while True:
            operation, payload = commands.get()
            if operation == "close":
                break
            with service._dispatch_lock:
                if operation == "native_offer":
                    result = service.native_webrtc_offer(
                        payload["session_id"], ICE, CHANNELS)
                elif operation == "native_accept":
                    result = service.native_webrtc_accept(
                        payload["session_id"], payload["offer_sdp"], ICE, CHANNELS)
                elif operation == "native_apply":
                    result = service.native_webrtc_apply_answer(
                        payload["session_id"], payload["answer_sdp"])
                elif operation == "fault":
                    host.fault = payload["mode"]
                    result = {"mode": host.fault}
                elif operation == "native_close":
                    result = service.native_webrtc_close(payload["session_id"])
                elif operation == "stats":
                    result = service.native_webrtc_stats(payload["session_id"])
                else:
                    response, should_stop = service.dispatch({
                        "v": 1, "id": str(uuid.uuid4()), **payload})
                    assert response["ok"] and not should_stop, response
                    result = response["result"]
                replies.put({"ok": True, "result": result})
    except BaseException:
        replies.put({"ok": False, "traceback": traceback.format_exc()})
        raise
    finally:
        if host is not None:
            host.shutdown()
        if service is not None:
            service.close()


class NativePeers:
    def __init__(self, root: Path):
        self.root = root
        self.commands: list[multiprocessing.Queue] = []
        self.replies: list[multiprocessing.Queue] = []
        self.processes = []
        self.keys: list[bytes] = []
        self.directories: list[Path] = []

    def _launch(self, index: int):
        while len(self.commands) <= index:
            self.commands.append(None)
            self.replies.append(None)
            self.processes.append(None)
        commands, replies = multiprocessing.Queue(), multiprocessing.Queue()
        process = multiprocessing.Process(
            target=_native_peer,
            args=(str(self.directories[index]), commands, replies, self.keys[index]),
            daemon=True,
        )
        process.start()
        self.commands[index] = commands
        self.replies[index] = replies
        self.processes[index] = process
        return self.response(index)

    def start(self):
        profiles = []
        for index in range(2):
            directory = self.root / f"peer-{index}"
            directory.mkdir()
            self.directories.append(directory)
            self.keys.append(os.urandom(32))
            profiles.append(self._launch(index))
        return profiles

    def restart(self, index: int):
        self.commands[index].put(("close", {}))
        process = self.processes[index]
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(5)
        assert not process.is_alive(), "peer did not stop for restart"
        return self._launch(index)

    def call(self, index: int, operation: str, **payload: Any) -> Any:
        self.commands[index].put((operation, payload))
        return self.response(index)

    def command(self, index: int, command: str, **payload: Any) -> Any:
        return self.call(index, "command", command=command, payload=payload)

    def response(self, index: int) -> Any:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                response = self.replies[index].get(timeout=0.05)
            except queue.Empty:
                assert self.processes[index].is_alive(), (
                    index, self.processes[index].exitcode)
                continue
            assert response["ok"], response
            return response["result"]
        raise AssertionError(f"peer {index} did not reply")

    def wait(self, description: str, probe, timeout: float = 30) -> Any:
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            last = probe()
            if last:
                return last
            time.sleep(0.05)
        raise AssertionError(f"timed out waiting for {description}: {last}")

    def close(self):
        for commands in self.commands:
            commands.put(("close", {}))
        for process in self.processes:
            process.join(10)
            if process.is_alive():
                process.terminate()
                process.join(5)
            assert not process.is_alive(), "native test peer survived cleanup"


def _attached(peers, index, session):
    stats = peers.call(index, "stats", session_id=session)
    return (stats.get("attached") and stats.get("data_channel_state") == "open"
            and stats.get("ice_connection_state") in {"connected", "completed"})


def _attach_native_pair(peers, left_session, right_session):
    offer = peers.call(0, "native_offer", session_id=left_session)
    answer = peers.call(1, "native_accept", session_id=right_session,
                        offer_sdp=offer["sdp"])
    peers.call(0, "native_apply", session_id=left_session,
               answer_sdp=answer["sdp"])
    peers.wait("both native bridges attached",
               lambda: _attached(peers, 0, left_session)
               and _attached(peers, 1, right_session), timeout=40)


def _approve_contacts(peers):
    invitation = peers.command(0, "create_invitation", connection_mode="webrtc")
    peers.command(1, "accept_invitation", invitation=invitation["text"])

    def contact(index, trust):
        return next((row for row in peers.command(index, "snapshot")["contacts"]
                     if row["trust"] == trust), None)

    pending = peers.wait("the contact request",
                         lambda: contact(0, "pending_request"), timeout=30)
    left = peers.command(0, "approve_request", contact_id=pending["id"])
    right = peers.wait("the acceptance",
                       lambda: contact(1, "approved"), timeout=30)
    return {0: left, 1: right}


def _message(peers, index, identifier, direction):
    return next((row for row in peers.command(index, "snapshot")["messages"]
                 if row["id"] == identifier and row["direction"] == direction
                 and row["state"] == "delivered"), None)


def _exchange(peers, contacts, sender, text):
    recipient = 1 - sender
    sent = peers.command(sender, "send_message",
                         contact_id=contacts[sender]["id"], text=text)
    received = peers.wait("recipient message",
                          lambda: _message(peers, recipient, sent["id"], "inbound"))
    delivered = peers.wait("sender receipt",
                           lambda: _message(peers, sender, sent["id"], "outbound"))
    assert received["text"] == delivered["text"] == text
    assert delivered["native_message_id"]
    copies = [row for row in peers.command(recipient, "snapshot")["messages"]
              if row["id"] == sent["id"] and row["direction"] == "inbound"]
    assert len(copies) == 1
    return sent


def _start_connected(tmp_path: Path):
    peers = NativePeers(tmp_path)
    profiles = peers.start()
    _attach_native_pair(peers, "native-left", "native-right")
    return peers, _approve_contacts(peers), profiles


@pytest.mark.integration
def test_native_datachannel_delivers_durable_messages_and_receipts(tmp_path: Path) -> None:
    peers, contacts, _ = _start_connected(tmp_path)
    try:
        _exchange(peers, contacts, 0, "Native durable message from peer 0")
        _exchange(peers, contacts, 1, "Native durable message from peer 1")
        started = time.monotonic()
        for index in range(100):
            _exchange(peers, contacts, index % 2,
                      f"Native receipt soak message {index}")
        elapsed = time.monotonic() - started
        assert elapsed < 300, f"100-message receipt soak took {elapsed:.1f}s"
    finally:
        peers.close()
    assert all(process.exitcode == 0 for process in peers.processes)


@pytest.mark.integration
def test_native_datachannel_recovers_queued_messages_after_bridge_replacement(
    tmp_path: Path,
) -> None:
    peers, contacts, _ = _start_connected(tmp_path)
    try:
        _exchange(peers, contacts, 0, "Before native bridge replacement")
        peers.call(0, "native_close", session_id="native-left")
        time.sleep(0.5)
        queued = peers.command(0, "send_message", contact_id=contacts[0]["id"],
                               text="Queued while the native bridge is absent")
        assert queued["state"] == "queued", queued
        _attach_native_pair(peers, "native-left-replacement", "native-right-replacement")
        received = peers.wait(
            "queued recipient message after replacement",
            lambda: _message(peers, 1, queued["id"], "inbound"), timeout=40)
        delivered = peers.wait(
            "queued sender receipt after replacement",
            lambda: _message(peers, 0, queued["id"], "outbound"), timeout=40)
        assert received["text"] == delivered["text"] == queued["text"]
        assert delivered["native_message_id"]
    finally:
        peers.close()
    assert all(process.exitcode == 0 for process in peers.processes)


def _partition_then_recover(peers, contacts, seconds: int, budget: float):
    peers.call(0, "fault", mode="drop")
    peers.call(1, "fault", mode="drop")
    interrupted = peers.command(
        0, "send_message", contact_id=contacts[0]["id"],
        text=f"Durable message during {seconds}-second native packet partition")
    time.sleep(seconds)
    peers.call(0, "fault", mode="pass")
    peers.call(1, "fault", mode="pass")
    started = time.monotonic()
    received = peers.wait(
        "partitioned recipient message",
        lambda: _message(peers, 1, interrupted["id"], "inbound"), timeout=budget)
    delivered = peers.wait(
        "partitioned sender receipt",
        lambda: _message(peers, 0, interrupted["id"], "outbound"), timeout=budget)
    elapsed = time.monotonic() - started
    assert received["text"] == delivered["text"] == interrupted["text"]
    assert elapsed < budget, f"partition recovery took {elapsed:.1f}s"
    copies = [row for row in peers.command(1, "snapshot")["messages"]
              if row["id"] == interrupted["id"] and row["direction"] == "inbound"]
    assert len(copies) == 1
    return elapsed


@pytest.mark.integration
def test_native_datachannel_recovers_after_packet_partition_and_duplication(
    tmp_path: Path,
) -> None:
    peers, contacts, _ = _start_connected(tmp_path)
    try:
        peers.call(0, "fault", mode="duplicate")
        peers.call(1, "fault", mode="duplicate")
        _exchange(peers, contacts, 0, "Duplicate delivery remains deduplicated")
        peers.call(0, "fault", mode="pass")
        peers.call(1, "fault", mode="pass")
        _partition_then_recover(peers, contacts, 5, 30)
    finally:
        peers.close()
    assert all(process.exitcode == 0 for process in peers.processes)


@pytest.mark.integration
def test_native_datachannel_recovers_within_the_thirty_second_partition_budget(
    tmp_path: Path,
) -> None:
    peers, contacts, _ = _start_connected(tmp_path)
    try:
        elapsed = _partition_then_recover(peers, contacts, 30, 240)
        assert elapsed < 240
    finally:
        peers.close()
    assert all(process.exitcode == 0 for process in peers.processes)


@pytest.mark.integration
def test_native_peer_restart_delivers_messages_queued_while_offline(
    tmp_path: Path,
) -> None:
    peers, contacts, profiles = _start_connected(tmp_path)
    try:
        _exchange(peers, contacts, 0, "Before peer restart")
        profile = peers.restart(1)
        assert profile["destination_hash"] == profiles[1]["destination_hash"]
        queued = peers.command(0, "send_message", contact_id=contacts[0]["id"],
                               text="Queued while the native peer process is offline")
        assert queued["state"] == "queued", queued
        _attach_native_pair(peers, "native-left-after-restart", "native-right-after-restart")
        received = peers.wait(
            "queued message after peer restart",
            lambda: _message(peers, 1, queued["id"], "inbound"), timeout=40)
        delivered = peers.wait(
            "receipt after peer restart",
            lambda: _message(peers, 0, queued["id"], "outbound"), timeout=40)
        assert received["text"] == delivered["text"] == queued["text"]
        assert delivered["native_message_id"]
    finally:
        peers.close()
    assert all(process.exitcode == 0 for process in peers.processes)

