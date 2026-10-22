from __future__ import annotations

import json
import time
import uuid
from typing import Any, Callable

import RNS

from .errors import IdentityMismatch, ValidationError
from .webrtc_signaling import (
    create_call_answer,
    create_call_candidate,
    create_call_hangup,
    create_call_invite,
    create_call_renegotiate,
    next_call_state,
    verify_call_answer,
    verify_call_candidate,
    verify_call_hangup,
    verify_call_invite,
    verify_call_renegotiate,
)

ACTIVE_STATES = {"dialing", "ringing", "connecting", "in_call"}
MAX_CANDIDATES = 32
RING_SECONDS = 45
CALLS_PER_MINUTE = 3
CALLS_PER_HOUR = 20
CALL_HISTORY_SECONDS = 24 * 60 * 60


class CallManager:
    """Call signaling without owning the media device.

    The manager signs and verifies call documents, stores call state (sealed in
    the vault by default, or memory-only when configured), and hands outgoing
    documents to the service transport. The WebRTC media adapter supplies
    SDP/fingerprints and attaches or reads audio separately.
    """

    def __init__(
        self,
        store: Any,
        send_document: Callable[[str, str], None],
        *,
        now: Callable[[], float] = time.time,
        new_id: Callable[[], str] | None = None,
        persist: bool = True,
    ) -> None:
        self.store = store
        self.send_document = send_document
        self.now = now
        self.new_id = new_id or (lambda: uuid.uuid4().hex)
        self.persist = bool(persist)
        # Active records are always available in memory so calls keep working
        # when sealed call-signaling storage is disabled.
        self._memory: dict[str, dict[str, Any]] = {}

    def set_persist(self, persist: bool) -> None:
        """Change whether new/updated call records are written to the vault.

        Disabling does not delete existing sealed records; it stops reading and
        writing them. Enabling adopts records created in memory while disabled.
        """

        enabled = bool(persist)
        was_enabled = self.persist
        self.persist = enabled
        if enabled and not was_enabled:
            for record in self._memory.values():
                self.store.put("call", record["id"], record)

    def _write(self, record: dict[str, Any]) -> None:
        self._memory[record["id"]] = record
        if self.persist:
            self.store.put("call", record["id"], record)

    def _get(self, call_id: str) -> dict[str, Any] | None:
        record = self._memory.get(call_id)
        if record is not None:
            return record
        if not self.persist:
            return None
        stored = self.store.get("call", call_id)
        if stored is not None:
            self._memory[call_id] = stored
        return stored

    def _list(self) -> list[dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        if self.persist:
            for record in self.store.list("call"):
                records[record["id"]] = record
        records.update(self._memory)
        return list(records.values())

    def _delete(self, call_id: str) -> None:
        self._memory.pop(call_id, None)
        if self.persist:
            self.store.delete("call", call_id)

    def start(
        self,
        identity: RNS.Identity,
        contact: dict[str, Any],
        *,
        media: str,
        sdp: str,
        dtls_fingerprint: str,
    ) -> dict[str, Any]:
        self._require_approved(contact)
        self._prune_history()
        self._enforce_rate_limit(contact["id"])
        call_id = self.new_id()
        invite = create_call_invite(
            identity,
            call_id=call_id,
            callee_destination=contact["destination_hash"],
            media=media,
            sdp=sdp,
            dtls_fingerprint=dtls_fingerprint,
            now=int(self.now()),
        )
        record = {
            "id": call_id,
            "contact_id": contact["id"],
            "peer_destination": contact["destination_hash"].lower(),
            "role": "caller",
            "media": media,
            "state": "dialing",
            "direction": "outbound",
            "invite": invite,
            "answer": None,
            "local_sdp": sdp,
            "remote_sdp": None,
            "candidates": [],
            "generation": 1,
            "restart_offer": None,
            "restart_answer": None,
            "created_at": self.now(),
            "updated_at": self.now(),
            "expires_at": int(self.now()) + 600,
            "ring_expires_at": self.now() + RING_SECONDS,
        }
        self._write(record)
        self.send_document(contact["id"], invite)
        return self.public(record)

    def receive(
        self,
        identity: RNS.Identity,
        contact: dict[str, Any],
        document: str,
    ) -> dict[str, Any] | None:
        self._require_approved(contact)
        kind = _document_type(document)
        local_destination = _destination(identity)
        if kind == "call_invite":
            invite = verify_call_invite(
                document, expected_callee_destination=local_destination, now=int(self.now())
            )
            if invite.caller_destination != contact["destination_hash"].lower():
                raise IdentityMismatch("Call invitation signer does not match the contact")
            existing = self._get(invite.call_id)
            if existing is not None:
                return None
            record = {
                "id": invite.call_id,
                "contact_id": contact["id"],
                "peer_destination": invite.caller_destination,
                "role": "callee",
                "media": invite.media,
                "state": "ringing",
                "direction": "inbound",
                "invite": document,
                "answer": None,
                "local_sdp": None,
                "remote_sdp": invite.sdp,
                "candidates": [],
                "generation": 1,
                "restart_offer": None,
                "restart_answer": None,
                "created_at": self.now(),
                "updated_at": self.now(),
                "expires_at": invite.expires_at,
                "ring_expires_at": min(self.now() + RING_SECONDS, invite.expires_at),
            }
            self._write(record)
            return self.public(record)

        if kind == "call_answer":
            call_id = _document_call_id(document)
            record = self._require_call(call_id)
            if record["contact_id"] != contact["id"] or record["role"] != "caller":
                raise IdentityMismatch("Call answer is for a different contact")
            invite = verify_call_invite(
                record["invite"],
                expected_callee_destination=record["peer_destination"],
                now=int(self.now()),
            )
            answer = verify_call_answer(document, invite, now=int(self.now()))
            if answer.callee_destination != record["peer_destination"]:
                raise IdentityMismatch("Call answer signer does not match the contact")
            record.update(
                answer=document,
                remote_sdp=answer.sdp,
                state=_advance(record["state"], "answer"),
                updated_at=self.now(),
            )
            self._write(record)
            return self.public(record)

        if kind == "call_candidate":
            call_id = _document_call_id(document)
            record = self._require_call(call_id)
            if record["contact_id"] != contact["id"]:
                raise IdentityMismatch("Call candidate is for a different contact")
            candidate = verify_call_candidate(
                document,
                call_id=call_id,
                expected_signer_destination=record["peer_destination"],
                now=int(self.now()),
            )
            if len(record["candidates"]) >= MAX_CANDIDATES:
                record["candidates"] = record["candidates"][-MAX_CANDIDATES + 1 :]
            record["candidates"].append(candidate.candidate)
            record["updated_at"] = self.now()
            self._write(record)
            return self.public(record)

        if kind == "call_renegotiate":
            call_id = _document_call_id(document)
            record = self._require_call(call_id)
            if record["contact_id"] != contact["id"]:
                raise IdentityMismatch("Call renegotiation is for a different contact")
            update = verify_call_renegotiate(
                document,
                call_id=call_id,
                expected_signer_destination=record["peer_destination"],
                now=int(self.now()),
            )
            if update.role == "offer":
                if record["role"] != "callee":
                    raise IdentityMismatch("Only the callee receives a renegotiation offer")
                if update.generation <= int(record.get("generation", 1)):
                    raise IdentityMismatch("Call renegotiation offer is stale")
                record["restart_offer"] = document
                record["remote_sdp"] = update.sdp
            else:
                if record["role"] != "caller":
                    raise IdentityMismatch("Only the caller receives a renegotiation answer")
                if update.generation != int(record.get("generation", 1)):
                    raise IdentityMismatch("Call renegotiation answer is stale")
                record["restart_answer"] = document
                record["remote_sdp"] = update.sdp
            record["generation"] = update.generation
            record["state"] = "connecting"
            record["updated_at"] = self.now()
            self._write(record)
            return self.public(record)

        if kind == "call_hangup":
            call_id = _document_call_id(document)
            record = self._require_call(call_id)
            if record["contact_id"] != contact["id"]:
                raise IdentityMismatch("Call hangup is for a different contact")
            hangup = verify_call_hangup(
                document,
                call_id=call_id,
                expected_signer_destination=record["peer_destination"],
                now=int(self.now()),
            )
            record["state"] = _hangup_state(hangup.reason)
            record["updated_at"] = self.now()
            self._write(record)
            return self.public(record)

        raise ValidationError("Call document type is unsupported")

    def answer(
        self,
        identity: RNS.Identity,
        call_id: str,
        *,
        sdp: str,
        dtls_fingerprint: str,
    ) -> dict[str, Any]:
        record = self._require_call(call_id)
        if record["role"] != "callee" or record["state"] != "ringing":
            raise ValidationError("This call is not awaiting an answer")
        if self.now() > float(record.get("ring_expires_at", 0)):
            record["state"] = "no_answer"
            record["updated_at"] = self.now()
            self._write(record)
            raise ValidationError("This call invitation has expired")
        invite = verify_call_invite(
            record["invite"],
            expected_callee_destination=_destination(identity),
            now=int(self.now()),
        )
        answer = create_call_answer(
            identity,
            invite,
            sdp=sdp,
            dtls_fingerprint=dtls_fingerprint,
            now=int(self.now()),
        )
        record.update(
            answer=answer,
            local_sdp=sdp,
            remote_sdp=invite.sdp,
            state=_advance(record["state"], "accept"),
            updated_at=self.now(),
        )
        self._write(record)
        self.send_document(record["contact_id"], answer)
        return self.public(record)

    def restart(
        self,
        identity: RNS.Identity,
        call_id: str,
        *,
        sdp: str,
        dtls_fingerprint: str,
    ) -> dict[str, Any]:
        record = self._require_call(call_id)
        if record["role"] != "caller" or record["state"] not in {"connecting", "in_call"}:
            raise ValidationError("This call cannot start an ICE restart")
        generation = int(record.get("generation", 1)) + 1
        document = create_call_renegotiate(
            identity,
            call_id=call_id,
            role="offer",
            generation=generation,
            sdp=sdp,
            dtls_fingerprint=dtls_fingerprint,
            now=int(self.now()),
        )
        record.update(
            generation=generation,
            local_sdp=sdp,
            restart_offer=None,
            restart_answer=None,
            state="connecting",
            updated_at=self.now(),
        )
        self._write(record)
        self.send_document(record["contact_id"], document)
        return self.public(record)

    def answer_restart(
        self,
        identity: RNS.Identity,
        call_id: str,
        *,
        sdp: str,
        dtls_fingerprint: str,
    ) -> dict[str, Any]:
        record = self._require_call(call_id)
        if record["role"] != "callee" or not record.get("restart_offer"):
            raise ValidationError("This call has no pending ICE restart")
        offer = verify_call_renegotiate(
            record["restart_offer"],
            call_id=call_id,
            expected_signer_destination=record["peer_destination"],
            now=int(self.now()),
        )
        document = create_call_renegotiate(
            identity,
            call_id=call_id,
            role="answer",
            generation=offer.generation,
            sdp=sdp,
            dtls_fingerprint=dtls_fingerprint,
            now=int(self.now()),
        )
        record.update(
            generation=offer.generation,
            local_sdp=sdp,
            remote_sdp=offer.sdp,
            restart_offer=None,
            state="connecting",
            updated_at=self.now(),
        )
        self._write(record)
        self.send_document(record["contact_id"], document)
        return self.public(record)

    def add_candidate(        self,
        identity: RNS.Identity,
        call_id: str,
        candidate: str,
    ) -> dict[str, Any]:
        record = self._require_call(call_id)
        document = create_call_candidate(
            identity,
            call_id=call_id,
            role=record["role"],
            candidate=candidate,
            now=int(self.now()),
        )
        record["candidates"].append(candidate)
        record["updated_at"] = self.now()
        self._write(record)
        self.send_document(record["contact_id"], document)
        return self.public(record)

    def end(self, identity: RNS.Identity, call_id: str, reason: str = "completed") -> dict[str, Any]:
        record = self._require_call(call_id)
        document = create_call_hangup(
            identity, call_id=call_id, reason=reason, now=int(self.now())
        )
        record["state"] = _hangup_state(reason)
        record["updated_at"] = self.now()
        self._write(record)
        self.send_document(record["contact_id"], document)
        return self.public(record)

    def _prune_history(self) -> None:
        cutoff = self.now() - CALL_HISTORY_SECONDS
        for record in self._list():
            if record.get("state") in ACTIVE_STATES:
                continue
            if float(record.get("updated_at", 0)) < cutoff:
                self._delete(record["id"])

    def _enforce_rate_limit(self, contact_id: str) -> None:
        calls = [
            record
            for record in self.store.list("call")
            if record.get("contact_id") == contact_id and record.get("direction") == "outbound"
        ]
        now = self.now()
        minute = sum(1 for record in calls if now - float(record.get("created_at", 0)) < 60)
        hour = sum(1 for record in calls if now - float(record.get("created_at", 0)) < 3600)
        if minute >= CALLS_PER_MINUTE or hour >= CALLS_PER_HOUR:
            raise ValidationError("Too many call attempts; wait before trying again")

    def active(self) -> list[dict[str, Any]]:
        calls = []
        for record in self._list():
            if record.get("state") not in ACTIVE_STATES:
                continue
            if (
                record.get("state") in {"dialing", "ringing"}
                and self.now() > float(record.get("ring_expires_at", 0))
            ):
                record["state"] = "no_answer"
                record["updated_at"] = self.now()
                self._write(record)
                continue
            calls.append(record)
        calls.sort(key=lambda record: record.get("updated_at", 0), reverse=True)
        return [self.public(record) for record in calls]

    def get(self, call_id: str) -> dict[str, Any]:
        return self.public(self._require_call(call_id))

    def public(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": record["id"],
            "contact_id": record["contact_id"],
            "role": record["role"],
            "media": record["media"],
            "state": record["state"],
            "direction": record["direction"],
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
            "expires_at": record["expires_at"],
            "ring_expires_at": record.get("ring_expires_at"),
            "candidate_count": len(record.get("candidates", [])),
            "has_local_sdp": bool(record.get("local_sdp")),
            "has_remote_sdp": bool(record.get("remote_sdp")),
        }

    def _require_call(self, call_id: str) -> dict[str, Any]:
        if not isinstance(call_id, str):
            raise ValidationError("Call ID is invalid")
        record = self._get(call_id)
        if record is None:
            raise ValidationError("Call is unknown")
        return record

    @staticmethod
    def _require_approved(contact: dict[str, Any]) -> None:
        if contact.get("trust") not in {"approved", "verified", "workspace"}:
            raise ValidationError("Calls require an approved contact")


def _destination(identity: RNS.Identity) -> str:
    return RNS.Destination.hash(identity, "lxmf", "delivery").hex()


def _document_type(document: str) -> str:
    try:
        value = json.loads(document)
    except Exception as exc:
        raise ValidationError("Call document is invalid") from exc
    kind = value.get("type") if isinstance(value, dict) else None
    if kind not in {
        "call_invite", "call_answer", "call_candidate", "call_hangup", "call_renegotiate"
    }:
        raise ValidationError("Call document type is unsupported")
    return kind


def _document_call_id(document: str) -> str:
    try:
        value = json.loads(document)
    except Exception as exc:
        raise ValidationError("Call document is invalid") from exc
    call_id = value.get("call_id") if isinstance(value, dict) else None
    if not isinstance(call_id, str):
        raise ValidationError("Call ID is invalid")
    return call_id


def _advance(state: str, event: str) -> str:
    try:
        return next_call_state(state, event)
    except ValidationError:
        return state


def _hangup_state(reason: str) -> str:
    return {
        "declined": "declined",
        "busy": "busy",
        "failed": "failed",
        "cancelled": "ended",
        "completed": "ended",
    }.get(reason, "ended")
