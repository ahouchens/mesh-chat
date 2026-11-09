"""Real Windows application pipe -> framed Core -> call/settings domain evidence."""

import base64
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest

if os.name != "nt":
    raise RuntimeError("Required Windows app boundary qualification needs Windows named pipes")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "service/src"))

import RNS
from mesh_chat.core_api.client import CoreClient
from mesh_chat.core_api.pipe_client import connect
from mesh_chat.core_api.pipe_endpoint import _bind, PROCESS_QUERY_LIMITED_INFORMATION
from mesh_chat.core_api.sidecar_host import start
from mesh_chat.reticulum_config import NetworkSettings
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore
from mesh_chat.webrtc_signaling import verify_call_invite, verify_call_hangup


def current_image():
    kernel, _ = _bind()
    process = kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, os.getpid())
    if not process:
        raise OSError(ctypes.get_last_error(), "Cannot resolve real test-client image")
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buffer))
        if not kernel.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(length)):
            raise OSError(ctypes.get_last_error(), "Cannot authenticate test-client image")
        return buffer.value[:length.value]
    finally:
        kernel.CloseHandle(process)


@pytest.fixture
def application_pipe(tmp_path, monkeypatch):
    monkeypatch.setattr(MeshChatService, "_start_network", lambda *_: None)
    monkeypatch.setattr(MeshChatService, "_prepare_lan_fallback", lambda *_: None)
    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    store.put("settings", "network", NetworkSettings(nearby_discovery=False, lan_fallback=False).to_dict())
    service = MeshChatService(store, tmp_path, lambda _: None)
    endpoint = duplex = None
    try:
        service.create_profile("Windows boundary owner")
        peer = RNS.Identity()
        contact = {"id": "windows-call-peer", "display_name": "Approved call fixture", "trust": "approved",
                   "destination_hash": RNS.Destination.hash(peer, "lxmf", "delivery").hex(),
                   "identity_hash": peer.hash.hex(),
                   "public_identity": base64.b64encode(peer.get_public_key()).decode("ascii")}
        store.put("contact", contact["id"], contact)
        name = rf"\\.\pipe\mesh-chat-boundary-{uuid4().hex[:16]}"
        endpoint = start(service, pipe_name=name, client_image=current_image())
        duplex = connect(name)
        client = CoreClient.open(duplex.readline, duplex.write)
        yield service, client, client.capabilities["profiles"][0], contact
    finally:
        if duplex is not None:
            duplex.close()
        if endpoint is not None:
            endpoint.close()
        service.close()


def test_windows_pipe_settings_mutations_read_back_from_vault(application_pipe):
    service, client, profile, _ = application_pipe
    client.request("settings.update", {"profile": profile, "settings": {
        "nearby_discovery": False, "lan_fallback": False, "help_route": True}})
    read = client.request("settings.query", {"profile": profile})
    assert read["settings"]["help_route"] is True
    assert service.store.get("settings", "network")["help_route"] is True
    client.request("call.settings_update", {"profile": profile, "settings": {
        "stun_urls": [], "turn_broker_url": None, "turn_broker_consent": False,
        "signal_mailbox_url": None, "relay_only": False, "store_call_signaling": False}})
    call_read = client.request("call.settings_query", {"profile": profile})
    assert call_read["settings"]["store_call_signaling"] is False
    assert call_read["settings"]["signal_mailbox_url"] is None
    assert service.call_settings()["store_call_signaling"] is False
    assert service.call_settings()["signal_mailbox_url"] is None


def test_windows_pipe_call_control_signs_and_retires_a_real_call(application_pipe):
    service, client, profile, contact = application_pipe
    fingerprint = "sha-256 " + ":".join(["AB"] * 32)
    sdp = f"v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=fingerprint:{fingerprint}\r\n"
    started = client.request("call.control", {"profile": profile, "action": "start",
        "contact_id": contact["id"], "media": "audio", "sdp": sdp,
        "dtls_fingerprint": fingerprint}, idempotency_key="windows-boundary-call-start-0001")["result"]
    call_id = started["id"]
    assert started["state"] == "dialing"
    record = service.store.get("call", call_id)
    assert record["state"] == "dialing" and record["media"] == "audio"
    invite = verify_call_invite(record["invite"], expected_callee_destination=contact["destination_hash"])
    assert invite.call_id == call_id
    assert invite.caller_destination == service._require_profile()["destination_hash"]
    signals = [row for row in service.store.list("message") if row["kind"] == "call_signal"]
    assert len(signals) == 1 and signals[0]["text"] == record["invite"]
    ended = client.request("call.control", {"profile": profile, "action": "end",
        "call_id": call_id, "reason": "completed"},
        idempotency_key="windows-boundary-call-end-0001")["result"]
    assert ended["id"] == call_id and ended["state"] == "ended"
    assert service.store.get("call", call_id)["state"] == "ended"
    signals = [row for row in service.store.list("message") if row["kind"] == "call_signal"]
    assert len(signals) == 2
    hangup = next(row for row in signals if row["text"] != record["invite"])
    verified = verify_call_hangup(hangup["text"], call_id=call_id,
                                 expected_signer_destination=service._require_profile()["destination_hash"])
    assert verified.reason == "completed"
    assert all(row["state"] != "delivered" for row in signals)
