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

    service = None
    host = None
    try:
        store = VaultStore(Path(root), vault_key, allow_unprotected_for_tests=True)
        store.put("settings", "network",
                  NetworkSettings(nearby_discovery=False, lan_fallback=False).to_dict())
        service_holder = [None]
        host = WindowsNativeWebRTCHost(
            lambda *event: service_holder[0].native_webrtc_event(*event)
            if service_holder[0] is not None else None)
        service = MeshChatService(store, Path(root), lambda _: None,
                                  native_webrtc_host=host)
        service_holder[0] = service
        profile = service.create_profile(Path(root).name)
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

    def start(self):
        profiles = []
        for index in range(2):
            directory = self.root / f"peer-{index}"
            directory.mkdir()
            commands, replies = multiprocessing.Queue(), multiprocessing.Queue()
            process = multiprocessing.Process(
                target=_native_peer,
                args=(str(directory), commands, replies, os.urandom(32)),
                daemon=True,
            )
            process.start()
            self.commands.append(commands)
            self.replies.append(replies)
            self.processes.append(process)
            profiles.append(self.response(index))
        return profiles

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


@pytest.mark.integration
def test_native_datachannel_delivers_durable_messages_and_receipts(tmp_path: Path) -> None:
    peers = NativePeers(tmp_path)
    try:
        profiles = peers.start()
        left_session, right_session = "native-left", "native-right"
        offer = peers.call(0, "native_offer", session_id=left_session)
        answer = peers.call(1, "native_accept", session_id=right_session,
                            offer_sdp=offer["sdp"])
        peers.call(0, "native_apply", session_id=left_session,
                   answer_sdp=answer["sdp"])
        peers.wait("both native bridges attached",
                   lambda: _attached(peers, 0, left_session)
                   and _attached(peers, 1, right_session), timeout=40)

        invitation = peers.command(0, "create_invitation", connection_mode="webrtc")
        peers.command(1, "accept_invitation", invitation=invitation["text"])

        def contact(index, trust):
            return next((row for row in peers.command(index, "snapshot")["contacts"]
                         if row["trust"] == trust), None)

        pending = peers.wait("the contact request",
                            lambda: contact(0, "pending_request"), timeout=30)
        left_contact = peers.command(0, "approve_request", contact_id=pending["id"])
        right_contact = peers.wait("the acceptance",
                                  lambda: contact(1, "approved"), timeout=30)

        def message(index, identifier, direction):
            return next((row for row in peers.command(index, "snapshot")["messages"]
                         if row["id"] == identifier and row["direction"] == direction
                         and row["state"] == "delivered"), None)

        for sender, recipient in ((0, 1), (1, 0)):
            text = f"Native durable message from peer {sender}"
            contact = left_contact if sender == 0 else right_contact
            sent = peers.command(sender, "send_message", contact_id=contact["id"],
                                 text=text)
            received = peers.wait("recipient message",
                                  lambda: message(recipient, sent["id"], "inbound"))
            delivered = peers.wait("sender receipt",
                                   lambda: message(sender, sent["id"], "outbound"))
            assert received["text"] == delivered["text"] == text
            assert delivered["native_message_id"]
    finally:
        peers.close()
    assert all(process.exitcode == 0 for process in peers.processes)
