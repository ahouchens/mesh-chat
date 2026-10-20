from __future__ import annotations

import pytest
import RNS

from mesh_chat.call_manager import CallManager
from mesh_chat.errors import IdentityMismatch, ValidationError

NOW = 1_800_000_000
FINGERPRINT = "sha-256 " + ":".join(["AB"] * 32)
SDP = "\r\n".join(
    [
        "v=0",
        "o=- 1 2 IN IP4 127.0.0.1",
        "s=-",
        "t=0 0",
        "a=fingerprint:" + FINGERPRINT,
        "m=audio 9 UDP/TLS/RTP/SAVPF 111",
        "a=mid:0",
    ]
) + "\r\n"


class MemoryStore:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, dict]] = {}

    def put(self, kind: str, record_id: str, value: dict) -> None:
        self.data.setdefault(kind, {})[record_id] = value

    def get(self, kind: str, record_id: str) -> dict | None:
        return self.data.get(kind, {}).get(record_id)

    def list(self, kind: str) -> list[dict]:
        return list(self.data.get(kind, {}).values())


def _destination(identity: RNS.Identity) -> str:
    return RNS.Destination.hash(identity, "lxmf", "delivery").hex()


def _contact(identity: RNS.Identity, contact_id: str = "contact-1") -> dict:
    return {
        "id": contact_id,
        "destination_hash": _destination(identity),
        "trust": "approved",
    }


def _manager(sent: list[tuple[str, str]]) -> CallManager:
    return CallManager(
        MemoryStore(),
        lambda contact_id, document: sent.append((contact_id, document)),
        now=lambda: NOW,
        new_id=lambda: "call_0123456789abcdef",
    )


def test_outgoing_invite_and_incoming_answer() -> None:
    caller = RNS.Identity()
    callee = RNS.Identity()
    caller_contact = _contact(callee)
    callee_contact = _contact(caller)
    sent: list[tuple[str, str]] = []
    caller_manager = _manager(sent)
    callee_manager = _manager(sent)

    outgoing = caller_manager.start(
        caller,
        caller_contact,
        media="audio",
        sdp=SDP,
        dtls_fingerprint=FINGERPRINT,
    )
    assert outgoing["state"] == "dialing"
    assert len(sent) == 1
    invite = sent[0][1]

    incoming = callee_manager.receive(callee, callee_contact, invite)
    assert incoming is not None
    assert incoming["state"] == "ringing"
    assert incoming["role"] == "callee"

    answered = callee_manager.answer(
        callee, incoming["id"], sdp=SDP, dtls_fingerprint=FINGERPRINT
    )
    assert answered["state"] == "connecting"
    answer_doc = sent[-1][1]

    caller_state = caller_manager.receive(caller, caller_contact, answer_doc)
    assert caller_state is not None
    assert caller_state["state"] == "connecting"
    assert caller_state["has_remote_sdp"] is True

    updated = caller_manager.get(outgoing["id"])
    assert updated["has_remote_sdp"] is True
    assert "sdp" not in updated


def test_candidate_and_hangup_are_scoped() -> None:
    caller = RNS.Identity()
    callee = RNS.Identity()
    sent: list[tuple[str, str]] = []
    caller_manager = _manager(sent)
    callee_contact = _contact(callee)
    caller_contact = _contact(caller)

    outgoing = caller_manager.start(
        caller, callee_contact, media="audio", sdp=SDP, dtls_fingerprint=FINGERPRINT
    )
    callee_manager = _manager(sent)
    incoming = callee_manager.receive(callee, caller_contact, sent[0][1])
    assert incoming is not None
    callee_manager.answer(callee, incoming["id"], sdp=SDP, dtls_fingerprint=FINGERPRINT)
    caller_manager.receive(caller, callee_contact, sent[-1][1])

    callee_manager.add_candidate(callee, incoming["id"], "candidate:1 1 UDP 1 192.0.2.1 5000 typ host")
    candidate_doc = sent[-1][1]
    updated = caller_manager.receive(caller, callee_contact, candidate_doc)
    assert updated is not None
    assert updated["candidate_count"] == 1

    ended = caller_manager.end(caller, outgoing["id"], "completed")
    assert ended["state"] == "ended"
    remote = callee_manager.receive(callee, caller_contact, sent[-1][1])
    assert remote is not None
    assert remote["state"] == "ended"


def test_wrong_signer_is_rejected() -> None:
    caller = RNS.Identity()
    callee = RNS.Identity()
    stranger = RNS.Identity()
    sent: list[tuple[str, str]] = []
    caller_manager = _manager(sent)
    caller_manager.start(
        caller,
        _contact(callee),
        media="audio",
        sdp=SDP,
        dtls_fingerprint=FINGERPRINT,
    )
    callee_manager = _manager(sent)

    with pytest.raises(IdentityMismatch):
        callee_manager.receive(callee, _contact(stranger), sent[0][1])


def test_unapproved_contact_cannot_start() -> None:
    caller = RNS.Identity()
    callee = RNS.Identity()
    manager = _manager([])
    contact = _contact(callee)
    contact["trust"] = "pending_request"

    with pytest.raises(ValidationError):
        manager.start(
            caller,
            contact,
            media="audio",
            sdp=SDP,
            dtls_fingerprint=FINGERPRINT,
        )


def test_outbound_call_attempts_are_rate_limited() -> None:
    caller = RNS.Identity()
    callee = RNS.Identity()
    counter = iter(range(100))
    manager = CallManager(
        MemoryStore(),
        lambda _contact_id, _document: None,
        now=lambda: float(NOW),
        new_id=lambda: f"call_rate_{next(counter):08d}",
    )
    contact = _contact(callee)
    for _ in range(3):
        manager.start(
            caller,
            contact,
            media="audio",
            sdp=SDP,
            dtls_fingerprint=FINGERPRINT,
        )
    with pytest.raises(ValidationError):
        manager.start(
            caller,
            contact,
            media="audio",
            sdp=SDP,
            dtls_fingerprint=FINGERPRINT,
        )


def test_ice_restart_renegotiates_without_a_new_ring() -> None:
    caller = RNS.Identity()
    callee = RNS.Identity()
    sent: list[tuple[str, str]] = []
    caller_manager = _manager(sent)
    callee_contact = _contact(callee)
    caller_contact = _contact(caller)

    outgoing = caller_manager.start(
        caller, callee_contact, media="audio", sdp=SDP, dtls_fingerprint=FINGERPRINT
    )
    callee_manager = _manager(sent)
    incoming = callee_manager.receive(callee, caller_contact, sent[0][1])
    assert incoming is not None
    callee_manager.answer(callee, incoming["id"], sdp=SDP, dtls_fingerprint=FINGERPRINT)
    caller_manager.receive(caller, callee_contact, sent[-1][1])

    restarted = caller_manager.restart(
        caller, outgoing["id"], sdp=SDP, dtls_fingerprint=FINGERPRINT
    )
    assert restarted["state"] == "connecting"
    offer_doc = sent[-1][1]
    remote = callee_manager.receive(callee, caller_contact, offer_doc)
    assert remote is not None
    assert remote["state"] == "connecting"

    callee_manager.answer_restart(
        callee, incoming["id"], sdp=SDP, dtls_fingerprint=FINGERPRINT
    )
    final = caller_manager.receive(caller, callee_contact, sent[-1][1])
    assert final is not None
    assert final["state"] == "connecting"
    assert caller_manager.get(outgoing["id"])["candidate_count"] == 0


def test_ringing_call_times_out_and_is_not_active() -> None:
    caller = RNS.Identity()
    callee = RNS.Identity()
    clock = [float(NOW)]
    manager = CallManager(
        MemoryStore(),
        lambda _contact_id, _document: None,
        now=lambda: clock[0],
        new_id=lambda: "call_ring_timeout_01",
    )
    manager.start(
        caller,
        _contact(callee),
        media="audio",
        sdp=SDP,
        dtls_fingerprint=FINGERPRINT,
    )
    clock[0] += 46
    assert manager.active() == []
    assert manager.get("call_ring_timeout_01")["state"] == "no_answer"
