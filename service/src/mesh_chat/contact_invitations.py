"""Durable, explicitly reviewed WebRTC invitations in the encrypted vault."""
from __future__ import annotations

import hashlib
import json
import time
import uuid

from .errors import IdentityMismatch, ValidationError
from .invitations import verify_invitation
from .workspace_protocol import verify_workspace_invitation


class ContactInvitationsMixin:
    def receive_contact_invitation(self, document, peer_destination, workspace_document=None):
        if not isinstance(document, str) or not isinstance(peer_destination, str):
            raise ValidationError("Contact invitation must be text with a verified peer")
        if workspace_document is not None and not isinstance(workspace_document, str):
            raise ValidationError("Workspace invitation must be text")
        if len(document.encode()) + len((workspace_document or "").encode()) > 65_536:
            raise ValidationError("Contact invitation is too large")
        invitation = verify_invitation(document)
        if invitation.destination_hash.hex() != peer_destination:
            raise IdentityMismatch("Invitation does not match the connected peer")
        if peer_destination == self._require_profile()["destination_hash"]:
            raise ValidationError("Cannot connect to the local identity")
        contact = self._contact_by_destination(peer_destination)
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
        if existing:
            return self._public_contact_invitation(existing)
        now = time.time()
        records = self.store.list("contact_invitation")
        for record in records:
            if record["expires_at"] <= now:
                self.store.delete("contact_invitation", record["id"])
        records = [record for record in records if record["expires_at"] > now]
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
        self.store.put("contact_invitation", record_id, record)
        self._changed()
        return self._public_contact_invitation(record)

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
