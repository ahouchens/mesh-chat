"""Durable, explicitly reviewed WebRTC invitations in the encrypted vault."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .errors import IdentityMismatch, ValidationError
from .invitations import verify_invitation
from .workspace_protocol import verify_workspace_invitation


@dataclass(frozen=True)
class PreparedContactInvitation:
    operation_id: str | None
    input_fingerprint: str
    result: dict[str, Any]
    records: tuple[tuple[str, str, dict[str, Any]], ...]
    deletions: tuple[tuple[str, str], ...]
    expected: dict[tuple[str, str], dict[str, Any] | None]
    expected_collections: dict[str, dict[str, dict[str, Any]]]
    peer_destination: str
    personal_document: str | None = None
    workspace_document: str | None = None
    join_operation_id: str | None = None
    requires_adoption: bool = False


def _input_fingerprint(action, **params):
    return hashlib.sha256(json.dumps({"action": action, **params}, sort_keys=True,
                                    separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


class ContactInvitationsMixin:
    def receive_contact_invitation(self, document, peer_destination, workspace_document=None):
        prepared = self._prepare_contact_invitation_receive(document, peer_destination, workspace_document, None)
        if prepared.records or prepared.deletions:
            self.store.put_and_delete(prepared.records, prepared.deletions)
            self._changed()
        return dict(prepared.result)

    def _require_contact_invitation_identity(self):
        if self._identity is None or self._shutdown.is_set():
            raise ValidationError("Local profile is unavailable")
        return self._require_profile()

    @staticmethod
    def _validate_contact_invitation_operation(operation_id):
        try:
            if str(uuid.UUID(operation_id)) != operation_id:
                raise ValueError
        except (ValueError, TypeError, AttributeError) as error:
            raise ValidationError("Contact invitation operation ID is invalid") from error

    def validate_contact_invitation_receive(self, document, peer_destination, workspace_document=None):
        self._require_contact_invitation_identity()
        return self._prepare_contact_invitation_receive(document, peer_destination, workspace_document, None).result

    def prepare_contact_invitation_receive(self, document, peer_destination, workspace_document, operation_id):
        """Prepare digest, capacity and expiry changes; no writes or activation."""
        self._require_contact_invitation_identity()
        self._validate_contact_invitation_operation(operation_id)
        return self._prepare_contact_invitation_receive(document, peer_destination, workspace_document, operation_id)

    def _prepare_contact_invitation_receive(self, document, peer_destination, workspace_document, operation_id):
        if not isinstance(document, str) or not isinstance(peer_destination, str):
            raise ValidationError("Contact invitation must be text with a verified peer")
        if workspace_document is not None and not isinstance(workspace_document, str):
            raise ValidationError("Workspace invitation must be text")
        if len(document.encode()) + len((workspace_document or "").encode()) > 65_536:
            raise ValidationError("Contact invitation is too large")
        invitation = verify_invitation(document)
        if invitation.destination_hash.hex() != peer_destination:
            raise IdentityMismatch("Invitation does not match the connected peer")
        profile = self._require_profile()
        if peer_destination == profile["destination_hash"]:
            raise ValidationError("Cannot connect to the local identity")
        contacts = dict(self.store.items("contact"))
        contact = next((value for value in contacts.values() if value["destination_hash"] == peer_destination), None)
        if contact and contact.get("trust") in {"blocked", "identity_changed"}:
            raise ValidationError("This contact cannot send invitations")
        workspace = None
        if workspace_document is not None:
            workspace = verify_workspace_invitation(workspace_document).preview()
        digest = hashlib.sha256(invitation.serialized.encode()).hexdigest()
        # Include the optional workspace so accepting a personal invitation
        # does not silently consume a later, distinct workspace invitation.
        workspace_digest = hashlib.sha256((workspace_document or "").encode()).hexdigest()
        record_id = self.store.opaque_id("contact-invitation", digest, workspace_digest)
        existing = self.store.get("contact_invitation", record_id)
        fingerprint = _input_fingerprint("receive", document=document, peer_destination=peer_destination, workspace_document=workspace_document)
        expected = {("profile", "local"): deepcopy(profile), ("contact_invitation", record_id): deepcopy(existing)}
        expected_collections = {"contact": deepcopy(contacts)}
        if existing:
            return PreparedContactInvitation(
                operation_id=operation_id, input_fingerprint=fingerprint,
                result=deepcopy(self._public_contact_invitation(existing)), records=(), deletions=(),
                expected=expected, expected_collections=expected_collections, peer_destination=peer_destination)
        now = time.time()
        inbox = dict(self.store.items("contact_invitation"))
        expected_collections["contact_invitation"] = deepcopy(inbox)
        deletions = tuple(("contact_invitation", identifier) for identifier, record in inbox.items() if record["expires_at"] <= now)
        records = [record for record in inbox.values() if record["expires_at"] > now]
        # Keep decision tombstones until expiry to suppress replay. Never
        # evict a person's pending decision to make room for a new sender.
        if len(records) >= 256 or sum(record["state"] == "pending" for record in records) >= 32:
            raise ValidationError("Contact requests are full. Review existing invitations first.")
        record = {
            "id": record_id, "state": "pending", "received_at": now,
            "expires_at": min(invitation.expires_at, workspace["expires_at"] if workspace else invitation.expires_at),
            "preview": invitation.preview(), "workspace": workspace,
            "document": document, "workspace_document": workspace_document,
        }
        return PreparedContactInvitation(
            operation_id=operation_id, input_fingerprint=fingerprint,
            result=deepcopy(self._public_contact_invitation(record)),
            records=(("contact_invitation", record_id, record),), deletions=deletions,
            expected=expected, expected_collections=expected_collections, peer_destination=peer_destination)

    def validate_contact_invitation_decide(self, invitation_id, accept):
        self._require_contact_invitation_identity()
        record, _, contact, _ = self._contact_invitation_decision_context(invitation_id, accept)
        return {"id": record["id"], "state": record["state"], "contact": deepcopy(contact)}

    def _contact_invitation_decision_context(self, invitation_id, accept):
        if not isinstance(invitation_id, str) or not isinstance(accept, bool):
            raise ValidationError("Contact invitation decision is invalid")
        record = self.store.get("contact_invitation", invitation_id)
        if record is None:
            raise ValidationError("This contact invitation is no longer available")
        wanted = "accepted" if accept else "declined"
        if record["state"] not in {"pending", wanted}:
            raise ValidationError("This contact invitation has already been reviewed")
        peer = record["preview"]["destination_hash"]
        if peer == self._require_profile()["destination_hash"]:
            raise ValidationError("Cannot connect to the local identity")
        contacts = dict(self.store.items("contact"))
        contact = next((value for value in contacts.values() if value["destination_hash"] == peer), None)
        if accept:
            if contact and contact.get("trust") in {"blocked", "identity_changed"}:
                raise ValidationError("This contact cannot be accepted")
            if record["state"] == "pending":
                if record["expires_at"] <= time.time():
                    raise ValidationError("This invitation has expired. Ask for a new invitation.")
                invitation = verify_invitation(record["document"])
                if invitation.destination_hash.hex() != peer:
                    raise IdentityMismatch("Saved invitation peer binding changed")
                if record.get("workspace_document"):
                    verify_workspace_invitation(record["workspace_document"])
        return record, wanted, contact, contacts

    def prepare_contact_invitation_decide(self, invitation_id, accept, operation_id):
        """Prepare review, not adoption. Parent MUST compose adoption before commit.

        An accepted pending request requires C's prepared personal adoption and
        A's prepared workspace join/capability rows in the SAME transaction as
        these rows and the parent receipt. Never run legacy accept/join here.
        """
        profile = self._require_contact_invitation_identity()
        self._validate_contact_invitation_operation(operation_id)
        record, wanted, contact, contacts = self._contact_invitation_decision_context(invitation_id, accept)
        adopting = accept and record["state"] == "pending"
        personal = record.get("document") if adopting else None
        workspace = record.get("workspace_document") if adopting else None
        reviewed = {key: deepcopy(value) for key, value in record.items() if key not in {"document", "workspace_document"}}
        reviewed["state"] = wanted
        expected = {("profile", "local"): deepcopy(profile), ("contact_invitation", invitation_id): deepcopy(record)}
        result = deepcopy(contact) if accept and not adopting and contact else {}
        writes = (("contact_invitation", invitation_id, reviewed),) if record["state"] != wanted else ()
        return PreparedContactInvitation(
            operation_id=operation_id,
            input_fingerprint=_input_fingerprint("decide", invitation_id=invitation_id, accept=accept),
            result=result, records=writes, deletions=(), expected=expected,
            expected_collections={"contact": deepcopy(contacts)}, peer_destination=record["preview"]["destination_hash"],
            personal_document=personal, workspace_document=workspace,
            join_operation_id=str(uuid.uuid5(uuid.NAMESPACE_OID, "contact-invitation:" + invitation_id)) if workspace else None,
            requires_adoption=adopting)

    def finish_prepared_contact_invitation_receive(self, prepared: PreparedContactInvitation):
        if prepared.records and all(self.store.get(kind, identifier) == value for kind, identifier, value in prepared.records):
            try:
                self._changed()
            except Exception:
                pass

    def finish_prepared_contact_invitation_decide(self, prepared: PreparedContactInvitation, result=None):
        """Notify after the combined adoption/review receipt committed; no writes."""
        if not prepared.records:
            return
        try:
            self._require_contact_invitation_identity()
        except ValidationError:
            return
        reviewed = self.store.get("contact_invitation", prepared.records[0][1])
        if reviewed != prepared.records[0][2]:
            return
        if prepared.requires_adoption:
            contact = self._contact_by_destination(prepared.peer_destination)
            if contact is None or contact.get("trust") in {"blocked", "identity_changed"}:
                return
        message = {"type": "invitation_accepted" if reviewed["state"] == "accepted" else "invitation_declined"}
        if result and result.get("reconnect_capabilities"):
            message["capabilities"] = result["reconnect_capabilities"]
        for session, destination in list(getattr(self, "_native_webrtc_peers", {}).items()):
            if destination == prepared.peer_destination and session in self._native_webrtc_live:
                try:
                    self.native_webrtc_control(session, "mesh-onboarding", json.dumps(message))
                except Exception:
                    pass
        try:
            self._changed()
        except Exception:
            pass

    def _public_contact_invitation(self, record):
        peer = record["preview"]["destination_hash"]
        connected = any(
            destination == peer and session in getattr(self, "_native_webrtc_sessions", {})
            for session, destination in getattr(self, "_native_webrtc_peers", {}).items()
        )
        return {key: record[key] for key in ("id", "state", "received_at", "expires_at", "preview", "workspace")} | {
            "native_connected": connected, "expired": record["expires_at"] <= time.time(),
        }

    def contact_invitations(self):
        return [self._public_contact_invitation(record) for record in sorted(
            self.store.list("contact_invitation"), key=lambda item: item["received_at"], reverse=True
        ) if record["state"] == "pending"]

    def decide_contact_invitation(self, invitation_id, accept):
        if not isinstance(invitation_id, str) or not isinstance(accept, bool):
            raise ValidationError("Contact invitation decision is invalid")
        record = self.store.get("contact_invitation", invitation_id)
        if not record:
            raise ValidationError("This contact invitation is no longer available")
        wanted = "accepted" if accept else "declined"
        if record["state"] not in {"pending", wanted}:
            raise ValidationError("This contact invitation has already been reviewed")
        peer = record["preview"]["destination_hash"]
        result = {}
        if accept:
            contact = self._contact_by_destination(peer)
            if contact and contact.get("trust") in {"blocked", "identity_changed"}:
                raise ValidationError("This contact cannot be accepted")
            if record["state"] == "pending":
                if record["expires_at"] <= time.time():
                    raise ValidationError("This invitation has expired. Ask for a new invitation.")
                # Revalidate saved documents before doing any trust/route work.
                verify_invitation(record["document"])
                if record.get("workspace_document"):
                    verify_workspace_invitation(record["workspace_document"])
                result = dict(self.accept_invitation(record["document"]))
                if record.get("workspace_document"):
                    operation_id = str(uuid.uuid5(uuid.NAMESPACE_OID, "contact-invitation:" + invitation_id))
                    self.submit_workspace_join(record["workspace_document"], operation_id)
            elif contact:
                result = dict(contact)
            capabilities = self._contact_capabilities(self._contact_by_destination(peer)) if result else None
            if capabilities:
                result["reconnect_capabilities"] = capabilities
        record["state"] = wanted
        record.pop("document", None)
        record.pop("workspace_document", None)
        self.store.put("contact_invitation", invitation_id, record)
        message = {"type": "invitation_accepted" if accept else "invitation_declined"}
        if result.get("reconnect_capabilities"):
            message["capabilities"] = result["reconnect_capabilities"]
        for session, destination in list(getattr(self, "_native_webrtc_peers", {}).items()):
            if destination == peer and session in self._native_webrtc_live:
                try:
                    self.native_webrtc_control(session, "mesh-onboarding", json.dumps(message))
                except Exception:
                    pass  # The contact request is already durably queued.
        self._changed()
        return result
