"""Real Reticulum/LXMF peers over the renderer's base64 packet event boundary.

Only the DataChannel carrier is replaced by an in-memory relay. Each peer has
its own process because Reticulum owns process-global state. This does not
exercise browser ICE/DTLS or an Android device.
"""
from __future__ import annotations

import base64
import multiprocessing
import os
from pathlib import Path
import queue
import time
import traceback
from typing import Any, Callable
import uuid

import pytest


def _webrtc_peer(root: str, commands: Any, replies: Any, events: Any) -> None:
    import RNS

    from mesh_chat.reticulum_config import NetworkSettings
    from mesh_chat.service import MeshChatService
    from mesh_chat.vault import VaultStore

    service = None
    try:
        store = VaultStore(Path(root), os.urandom(32), allow_unprotected_for_tests=True)
        store.put(
            "settings", "network",
            NetworkSettings(nearby_discovery=False, lan_fallback=False).to_dict(),
        )
        service = MeshChatService(store, Path(root), events.put)
        profile = service.create_profile(Path(root).name)
        assert service.network is not None, service._network_error
        assert RNS.Transport.interfaces == []
        replies.put({"ok": True, "result": profile})
        while True:
            operation, payload = commands.get()
            if operation == "close":
                break
            with service._dispatch_lock:
                if operation == "packet":
                    # Use the same public IPC command as the renderer, including
                    # its decoding, bridge lookup and actual interface ingress.
                    response, _ = service.dispatch({
                        "v": 1, "id": str(uuid.uuid4()),
                        "command": "webrtc_packet", "payload": payload,
                    })
                    assert response["ok"], response
                    continue
                if operation == "diagnostic":
                    destination = bytes.fromhex(payload["destination"])
                    interface = service._webrtc_bridges[payload["bridge_id"]]
                    result = {
                        "path_known": service.network.path_known(destination),
                        "recipient_ready": service.network.recipient_ready(destination),
                        "uses_bridge": RNS.Transport.next_hop_interface(destination) is interface,
                        "interface_count": len(RNS.Transport.interfaces),
                        "rxb": interface.rxb,
                        "txb": interface.txb,
                    }
                elif operation == "transport_state":
                    result = {
                        "path_known": service.network.path_known(bytes.fromhex(payload["destination"])),
                        "interface_count": len(RNS.Transport.interfaces),
                        "live_link_count": sum(
                            link.status != RNS.Link.CLOSED
                            for link in list(RNS.Transport.pending_links) + list(RNS.Transport.active_links)
                        ),
                        "retired_cached_link_count": sum(
                            link.attached_interface not in RNS.Transport.interfaces
                            for link in list(service.network.router.direct_links.values())
                            + list(service.network.router.backchannel_links.values())
                        ),
                    }
                elif operation == "receipts":
                    result = [
                        row for row in store.list("message")
                        if row.get("receipt_for") == payload["message_id"]
                    ]
                else:
                    assert operation == "command"
                    response, should_stop = service.dispatch({
                        "v": 1, "id": str(uuid.uuid4()), **payload,
                    })
                    assert response["ok"] and not should_stop, response
                    result = response["result"]
                replies.put({"ok": True, "result": result})
    except BaseException:
        replies.put({"ok": False, "traceback": traceback.format_exc()})
        raise
    finally:
        if service is not None:
            service.close()


class WebRTCPeers:
    def __init__(self, root: Path) -> None:
        context = multiprocessing.get_context("spawn")
        self.commands = [context.Queue() for _ in range(2)]
        self.replies = [context.Queue() for _ in range(2)]
        self.events = [context.Queue() for _ in range(2)]
        self.processes = [
            context.Process(
                target=_webrtc_peer,
                args=(str(root / name), self.commands[i], self.replies[i], self.events[i]),
            )
            for i, name in enumerate(("Alex", "Blair"))
        ]
        self.bridges: list[dict[str, Any]] = []
        self.retired_bridges: set[str] = set()
        self.status_events: list[list[dict[str, Any]]] = [[], []]
        self.forwarded = [0, 0]
        self.relay_intervals = [0.0, 0.0]
        self.next_relay = [0.0, 0.0]
        self.drop_packets_until = 0.0
        self.dropped = [0, 0]

    def start(self) -> list[dict[str, Any]]:
        for process in self.processes:
            process.start()
        return [self.response(i) for i in range(2)]

    def relay(self) -> None:
        if len(self.bridges) != 2:
            return
        for sender in range(2):
            now = time.monotonic()
            if now < self.next_relay[sender]:
                continue
            self.next_relay[sender] = now + self.relay_intervals[sender]
            # Bound each drain so unexpected event churn cannot defeat timeouts.
            for _ in range(256):
                try:
                    event = self.events[sender].get_nowait()
                except queue.Empty:
                    break
                if event["event"] == "webrtc_packet":
                    if now < self.drop_packets_until:
                        self.dropped[sender] += 1
                        continue
                    # A closed DataChannel cannot deliver its queued packets
                    # into a replacement bridge, even if events arrive late.
                    if event["bridge_id"] in self.retired_bridges:
                        continue
                    recipient = 1 - sender
                    assert event["bridge_id"] == self.bridges[sender]["bridge_id"]
                    packet = base64.b64decode(event["data"], validate=True)
                    assert 0 < len(packet) <= self.bridges[sender]["max_packet"]
                    self.commands[recipient].put(("packet", {
                        "bridge_id": self.bridges[recipient]["bridge_id"],
                        "data": event["data"],
                    }))
                    self.forwarded[sender] += 1
                elif event["event"] == "message_status":
                    self.status_events[sender].append(event)

    def response(self, index: int) -> Any:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            self.relay()
            try:
                response = self.replies[index].get(timeout=0.02)
            except queue.Empty:
                assert self.processes[index].is_alive(), (
                    index, self.processes[index].exitcode,
                )
                continue
            assert response["ok"], response
            return response["result"]
        raise AssertionError(f"Peer {index} did not reply; forwarded={self.forwarded}")

    def call(self, index: int, operation: str, **payload: Any) -> Any:
        self.commands[index].put((operation, payload))
        return self.response(index)

    def command(self, index: int, command: str, **payload: Any) -> Any:
        return self.call(index, "command", command=command, payload=payload)

    def wait(self, description: str, probe: Callable[[], Any], timeout: float = 25) -> Any:
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            self.relay()
            last = probe()
            if last:
                return last
            time.sleep(0.02)
        raise AssertionError(f"Timed out waiting for {description}; forwarded={self.forwarded}, last={last}")

    def close(self) -> None:
        for i, process in enumerate(self.processes):
            if process.pid is not None and process.is_alive():
                self.commands[i].put(("close", {}))
        for process in self.processes:
            if process.pid is None:
                continue
            process.join(8)
            if process.is_alive():
                process.terminate()
                process.join(3)
        for channel in self.commands + self.replies + self.events:
            channel.close()
            channel.cancel_join_thread()


@pytest.mark.integration
def test_real_webrtc_bridge_learns_routes_and_delivers_messages_with_receipts(tmp_path: Path) -> None:
    peers = WebRTCPeers(tmp_path)
    try:
        profiles = peers.start()
        for index in range(2):
            peers.bridges.append(peers.command(index, "webrtc_attach"))

        def routes_ready() -> bool:
            diagnostics = [
                peers.call(i, "diagnostic", destination=profiles[1 - i]["destination_hash"],
                           bridge_id=peers.bridges[i]["bridge_id"])
                for i in range(2)
            ]
            return all(
                row["path_known"] and row["recipient_ready"] and row["uses_bridge"]
                and row["interface_count"] == 1 and row["rxb"] > 0 and row["txb"] > 0
                for row in diagnostics
            )

        # No identity injection, manual route table updates or synthetic announce.
        # Only the announcements triggered by the real attach can establish this.
        peers.wait("both destinations to learn routes over WebRTC", routes_ready, timeout=12)
        invitation = peers.command(0, "create_invitation", connection_mode="webrtc")
        peers.command(1, "accept_invitation", invitation=invitation["text"])

        def contact(index: int, trust: str) -> dict[str, Any] | None:
            return next((
                row for row in peers.command(index, "snapshot")["contacts"]
                if row["trust"] == trust
            ), None)

        pending = peers.wait("the real contact request", lambda: contact(0, "pending_request"))
        alex_contact = peers.command(0, "approve_request", contact_id=pending["id"])
        blair_contact = peers.wait("the real acceptance", lambda: contact(1, "approved"))
        contacts = [alex_contact, blair_contact]

        def message(index: int, identifier: str, direction: str) -> dict[str, Any] | None:
            return next((
                row for row in peers.command(index, "snapshot")["messages"]
                if row["id"] == identifier and row["direction"] == direction
                and row["state"] == "delivered"
            ), None)

        def exchange(label: str) -> None:
            for sender in range(2):
                text = f"{label}: WebRTC packet delivery from {profiles[sender]['display_name']}"
                sent = peers.command(sender, "send_message", contact_id=contacts[sender]["id"], text=text)
                received = peers.wait("recipient plaintext", lambda: message(1 - sender, sent["id"], "inbound"))
                delivered = peers.wait("sender application receipt", lambda: message(sender, sent["id"], "outbound"))
                assert received["text"] == delivered["text"] == text
                assert received["conversation_id"] == delivered["conversation_id"]
                assert delivered["native_message_id"]
                receipts = peers.call(1 - sender, "receipts", message_id=sent["id"])
                assert len(receipts) == 1
                assert receipts[0]["kind"] == "receipt" and receipts[0]["native_message_id"]

                def delivered_event() -> bool:
                    return any(
                        event["message_id"] == sent["id"] and event["state"] == "delivered"
                        for event in peers.status_events[sender]
                    )

                peers.wait("the UI delivery-status event", delivered_event)

        exchange("Initial connection")
        for index in range(2):
            state = peers.call(index, "transport_state", destination=profiles[1 - index]["destination_hash"])
            assert state["live_link_count"] > 0
        old_bridges, peers.bridges = peers.bridges, []
        for index, bridge in enumerate(old_bridges):
            peers.retired_bridges.add(bridge["bridge_id"])
            peers.command(index, "webrtc_detach", bridge_id=bridge["bridge_id"])
            assert peers.call(index, "transport_state", destination=profiles[1 - index]["destination_hash"]) == {
                "path_known": False, "interface_count": 0, "live_link_count": 0,
                "retired_cached_link_count": 0,
            }
        # Reproduce an existing conversation sending after its only carrier
        # disappeared. These durable messages must resume without the user
        # pressing Send again or restarting either service.
        offline_messages = [
            peers.command(index, "send_message", contact_id=contacts[index]["id"],
                          text=f"Saved during bridge outage from peer {index}")
            for index in range(2)
        ]
        assert all(row["state"] == "queued" for row in offline_messages)
        for index in range(2):
            peers.bridges.append(peers.command(index, "webrtc_attach"))
        peers.wait("replacement bridge routes", routes_ready, timeout=12)
        for sender, saved in enumerate(offline_messages):
            received = peers.wait("outage message plaintext after reconnect",
                                  lambda: message(1 - sender, saved["id"], "inbound"))
            delivered = peers.wait("outage message application receipt",
                                   lambda: message(sender, saved["id"], "outbound"))
            assert received["text"] == delivered["text"] == saved["text"]
            copies = [row for row in peers.command(1 - sender, "snapshot")["messages"]
                      if row["id"] == saved["id"] and row["direction"] == "inbound"]
            assert len(copies) == 1
        exchange("After reconnect")
        for index in range(2):
            assert peers.call(index, "transport_state", destination=profiles[1 - index]["destination_hash"])["retired_cached_link_count"] == 0
        assert all(count > 0 for count in peers.forwarded)
    finally:
        peers.close()
    assert all(process.exitcode == 0 for process in peers.processes)


@pytest.mark.integration
def test_repeated_call_signaling_preserves_webrtc_message_delivery(tmp_path: Path) -> None:
    peers = WebRTCPeers(tmp_path)
    peers.relay_intervals = [0.0, 0.75]
    fingerprint = "sha-256 " + ":".join(["AB"] * 32)
    sdp = ("v=0\r\no=- 1 2 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\n"
           f"a=fingerprint:{fingerprint}\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
           "a=mid:0\r\n" + "a=x-test:" + "x" * 6000 + "\r\n")
    try:
        profiles = peers.start()
        for index in range(2):
            peers.bridges.append(peers.command(index, "webrtc_attach"))
        invitation = peers.command(0, "create_invitation", connection_mode="webrtc")
        peers.command(1, "accept_invitation", invitation=invitation["text"])

        def contact(index: int, trust: str) -> dict[str, Any] | None:
            return next((row for row in peers.command(index, "snapshot")["contacts"]
                         if row["trust"] == trust), None)

        pending = peers.wait("contact request", lambda: contact(0, "pending_request"))
        left = peers.command(0, "approve_request", contact_id=pending["id"])
        right = peers.wait("contact acceptance", lambda: contact(1, "approved"))
        contacts = [left, right]
        for attempt, media in enumerate(("audio", "video")):
            call = peers.command(1, "start_call", contact_id=right["id"], media=media,
                                 sdp=sdp, dtls_fingerprint=fingerprint)

            def ringing():
                return next((row for row in peers.command(0, "snapshot")["calls"]
                             if row["id"] == call["id"] and row["state"] == "ringing"), None)

            assert peers.wait("incoming call invitation", ringing)["media"] == media
            peers.command(1, "end_call", call_id=call["id"], reason="cancelled")
            peers.wait("remote cancellation", lambda: not peers.command(0, "snapshot")["calls"])
            for sender in range(2):
                sent = peers.command(sender, "send_message", contact_id=contacts[sender]["id"],
                                     text=f"Message after call attempt {attempt} from {sender}")
                peers.wait("post-call message and receipt", lambda: all(
                    any(row["id"] == sent["id"] and row["state"] == "delivered"
                        for row in peers.command(index, "snapshot")["messages"])
                    for index in range(2)))
                state = peers.call(sender, "diagnostic",
                                   destination=profiles[1 - sender]["destination_hash"],
                                   bridge_id=peers.bridges[sender]["bridge_id"])
                assert state["uses_bridge"] and state["interface_count"] == 1
        incoming = peers.command(0, "connection_diagnostics")
        outgoing = peers.command(1, "connection_diagnostics")
        assert incoming["current_calls"]["peers_with_route"] == 1
        assert outgoing["current_calls"]["peers_with_route"] == 1
        assert any(row["event"] == "call_inbound" and row["signal"] == "call_invite"
                   and row["phase"] == "ringing" for row in incoming["events"])
        assert any(row["event"] == "call_outbound" and row["signal"] == "call_invite"
                   and row["phase"] == "received_by_endpoint" for row in outgoing["events"])
        assert sdp not in str(incoming) and sdp not in str(outgoing)
    finally:
        peers.close()
    assert all(process.exitcode == 0 for process in peers.processes)


@pytest.mark.integration
def test_manual_pairing_recovers_lost_initial_announces_with_mobile_polling(tmp_path: Path) -> None:
    peers = WebRTCPeers(tmp_path)
    # Android's native packet events are polled in batches every 750 ms;
    # desktop receives an event as soon as the service emits it.
    peers.relay_intervals = [0.0, 0.75]
    try:
        profiles = peers.start()
        invitation = peers.command(0, "create_invitation", connection_mode="webrtc")
        peers.command(1, "accept_invitation", invitation=invitation["text"])
        # Lose all announcements from attach and its 2s/6s retries, as when
        # the renderer/event bridge is not ready yet. Endpoints attach at
        # different times; the service must recover through ordinary path
        # discovery once packets begin flowing, without synthetic identities.
        peers.drop_packets_until = time.monotonic() + 8.0
        peers.bridges.append(peers.command(0, "webrtc_attach"))
        time.sleep(0.8)
        peers.bridges.append(peers.command(1, "webrtc_attach"))

        def contact(index: int, trust: str) -> dict[str, Any] | None:
            return next((row for row in peers.command(index, "snapshot")["contacts"]
                         if row["trust"] == trust), None)

        pending = peers.wait("contact request after dropped initial announces",
                             lambda: contact(0, "pending_request"), timeout=40)
        left = peers.command(0, "approve_request", contact_id=pending["id"])
        right = peers.wait("contact acceptance with mobile polling",
                           lambda: contact(1, "approved"))
        assert all(count > 0 for count in peers.dropped)
        for sender, target in enumerate((left, right)):
            row = peers.call(sender, "diagnostic", destination=profiles[1 - sender]["destination_hash"],
                             bridge_id=peers.bridges[sender]["bridge_id"])
            assert row["path_known"] and row["recipient_ready"] and row["uses_bridge"]
            sent = peers.command(sender, "send_message", contact_id=target["id"],
                                 text=f"Mobile-batched delivery from {sender}")

            def delivered() -> bool:
                return all(any(row["id"] == sent["id"] and row["state"] == "delivered"
                               for row in peers.command(index, "snapshot")["messages"])
                           for index in range(2))

            peers.wait("message plaintext and application receipt with mobile polling", delivered)
    finally:
        peers.close()
    assert all(process.exitcode == 0 for process in peers.processes)
