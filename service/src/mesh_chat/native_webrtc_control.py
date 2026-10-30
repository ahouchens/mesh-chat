"""Service-owned, identity-bound control for native WebRTC sessions.

Reconnect channels exchange capabilities only. Onboarding still requires the
person's explicit invitation/approval actions; background control grants none.
"""
from __future__ import annotations

import json
import time

from .errors import ContactNotApproved, IdentityMismatch, ValidationError
from .webrtc_onboarding import verify_onboarding_answer, verify_onboarding_offer
from .native_carrier_evidence import normalized_sdp

MAX_CONTROL_LENGTH = 16_384


def profile_binding(profile):
    return (profile.get("scope_kind", "contact"), profile.get("id"),
            profile.get("local_device_id"), profile.get("remote_device_id"))


def bind_control_profile(state, profile):
    if not profile.get("id") or not profile.get("local_device_id") or not profile.get("remote_device_id"):
        raise IdentityMismatch("Native control profile identity is incomplete")
    binding = profile_binding(profile)
    if state.get("profile_binding") not in (None, binding):
        raise IdentityMismatch("Native control is already bound to another profile or device")
    state["profile_id"] = profile["id"]
    state["profile_binding"] = binding


class NativeWebRTCControlMixin:
    def native_webrtc_bind_onboarding(self, session_id, offer_document, answer_document=None):
        offer = verify_onboarding_offer(offer_document)
        answer = verify_onboarding_answer(answer_document, offer) if answer_document else None
        with self._native_webrtc_lock:
            description = self._native_webrtc_descriptions.get(session_id)
            if session_id not in self._native_webrtc_live or not description:
                raise ValidationError("Native onboarding session is no longer live")
            if any(current == session_id for current in self._native_webrtc_profile_sessions.values()):
                raise ValidationError("Reconnect sessions cannot become onboarding sessions")
            # Bind the signed signaling to this actual peer, including ICE
            # credentials, not just an identity supplied by the renderer.
            if description.get("remote_offer") is not None:
                if normalized_sdp(offer.sdp) != normalized_sdp(description["remote_offer"]):
                    raise IdentityMismatch("Offer does not belong to this native session")
                peer = offer.signer_destination
                remote = offer.sdp
            else:
                if not answer or normalized_sdp(offer.sdp) != normalized_sdp(description["local"]):
                    raise IdentityMismatch("Answer does not belong to this native session")
                peer = answer.signer_destination
                remote = answer.sdp
                applied = description.get("remote_answer")
                if applied and normalized_sdp(applied) != normalized_sdp(remote):
                    raise IdentityMismatch("Signed answer does not match the applied native answer")
            previous_sdp = description.get("bound_remote_sdp")
            if previous_sdp and previous_sdp != normalized_sdp(remote):
                raise IdentityMismatch("Native session is already bound to another exchange")
            previous = self._native_webrtc_peers.get(session_id)
            if previous and previous != peer:
                raise IdentityMismatch("Native session is already bound to another peer")
            self._native_webrtc_peers[session_id] = peer
            description["bound_remote_sdp"] = normalized_sdp(remote)
            if "answer_wait_until" in description:
                description["answer_wait_until"] = min(
                    description["answer_wait_until"],
                    time.monotonic() + max(0, offer.expires_at - time.time()),
                )
        return {"peer_destination": peer}

    def claim_native_reconnect_carrier(self, profile_id, local_device_id, remote_device_id):
        """Private ownership transfer; public JSON cannot supply binding evidence."""
        with self._dispatch_lock, self._native_webrtc_lock:
            if getattr(self, "_connection_policy", "legacy") != "shared-native":
                return None
            profile = self._reconnect_profile(profile_id)
            if (profile.get("local_device_id") != local_device_id
                    or (profile.get("remote_device_id") or None) != remote_device_id
                    or not remote_device_id):
                raise ContactNotApproved("Carrier adoption authority is unavailable")
            session_id = self._authorized_manual_native_carrier(profile)
            if profile_id in self._native_webrtc_profile_sessions:
                return None
            if session_id is not None:
                self._native_webrtc_profile_sessions[profile_id] = session_id
                self._native_webrtc_descriptions[session_id].pop("answer_wait_until", None)
            return session_id

    def native_manual_carrier_authorized(self, profile_id):
        """Private domain query; it grants no permission to negotiate a new peer."""
        with self._dispatch_lock, self._native_webrtc_lock:
            if getattr(self, "_connection_policy", "legacy") != "shared-native":
                return False
            try:
                return self._authorized_manual_native_carrier(self._reconnect_profile(profile_id)) is not None
            except (ContactNotApproved, ValidationError):
                return False

    def _authorized_manual_native_carrier(self, profile):
        contact = self._reconnect_contact(profile["contact_id"])
        public = self._reconnect_profile_public(profile)
        reasons = set(public["effective"].get("reasons") or ())
        # These preferences govern replacement negotiation, not a manually
        # established, signed and currently authorized messaging carrier.
        automatic_only = {"mailbox_not_configured", "consent_missing", "peer_consent_missing"}
        if (profile.get("state") == "stopped" or not profile.get("remote_device_id")
                or reasons - automatic_only):
            raise ContactNotApproved("Manual carrier authority is unavailable")
        for session_id, peer in self._native_webrtc_peers.items():
            description = self._native_webrtc_descriptions.get(session_id, {})
            actual_remote = description.get("remote_offer") or description.get("remote_answer")
            from .carrier_recovery import recovered_binding
            recovered = recovered_binding(self, session_id, profile, contact)
            other_owner = any(current == session_id and owner != profile["id"]
                              for owner, current in self._native_webrtc_profile_sessions.items())
            if (session_id not in self._native_webrtc_live
                    or session_id in self._native_webrtc_creating or other_owner
                    or peer != contact["destination_hash"]
                    or self._native_webrtc_controls.get(session_id, {}).get("profile_id") != profile["id"]
                    or self._native_webrtc_controls.get(session_id, {}).get("profile_binding") != profile_binding(profile)
                    or (recovered is None and (not actual_remote
                        or description.get("bound_remote_sdp") != normalized_sdp(actual_remote)))
                    or (not profile.get("allow_direct_ip_disclosure")
                        and description.get("ice_policy") != "relay")):
                continue
            return session_id
        return None

    def _native_control_contact(self, session_id):
        if session_id not in self._native_webrtc_live:
            return None
        for profile_id, current in list(self._native_webrtc_profile_sessions.items()):
            if current == session_id:
                profile = self._reconnect_profile(profile_id)
                return profile["contact_id"]
        peer = self._native_webrtc_peers.get(session_id)
        contact = self._contact_by_destination(peer) if peer else None
        return contact["id"] if contact else None

    def _native_control_receive(self, session_id, label, text):
        if len(text) > 65_536 or session_id not in self._native_webrtc_live:
            return
        # Only sessions bound by signed signaling or a verified reconnect
        # profile may update capabilities.
        contact_id = self._native_control_contact(session_id)
        peer = self._native_webrtc_peers.get(session_id)
        if not contact_id and not peer:
            return
        try:
            message = json.loads(text)
            if not isinstance(message, dict):
                return
            if label == "mesh-onboarding" and message.get("type") == "contact_invitation":
                # Save before emitting the renderer event: the WebView may be
                # suspended or its invitation dialog may already be closed.
                self.receive_contact_invitation(message.get("document"), peer, message.get("workspace_document"))
                return
            if len(text) > MAX_CONTROL_LENGTH:
                return
            state = self._native_webrtc_controls.setdefault(session_id, {})
            if message.get("type") == "connection_capabilities_request":
                if not state.get("requested"):
                    state["requested"] = True
                    state["last_sent"] = None
                    self._native_control_refresh(session_id, label)
                return
            document = message.get("document") if message.get("type") == "connection_capabilities" else None
            if label == "mesh-onboarding" and message.get("type") in {"invitation_accepted", "invitation_approved"}:
                document = message.get("capabilities")
            if isinstance(document, str) and document and len(document) <= MAX_CONTROL_LENGTH and document != state.get("last_received"):
                stored = self.reconnect_capabilities_store(document, expected_contact_id=contact_id,
                                                           expected_peer_destination=peer)
                profile = (stored or {}).get("profile") or {}
                if label == "mesh-onboarding" and profile.get("id"):
                    bind_control_profile(state, profile)
                state["last_received"] = document
        except Exception:
            # Malformed, stale, blocked and wrong-peer capabilities never grant
            # trust or tear down an otherwise usable messaging connection.
            return

    def _native_control_refresh(self, session_id, label):
        contact_id = self._native_control_contact(session_id)
        if not contact_id or contact_id.startswith("workspace:"):
            return
        state = self._native_webrtc_controls.setdefault(session_id, {})
        # A pre-contact capability was held pending. Once approval creates the
        # device profile, bind this manual session to that specific device.
        if label == "mesh-onboarding" and state.get("last_received") and not state.get("profile_id"):
            stored = self.reconnect_capabilities_store(state["last_received"], expected_contact_id=contact_id,
                expected_peer_destination=self._native_webrtc_peers.get(session_id))
            profile = (stored or {}).get("profile") or {}
            if profile.get("id"):
                bind_control_profile(state, profile)
        result = self.reconnect_capabilities_get(contact_id)
        document = result.get("local_capabilities")
        if isinstance(document, str) and document and len(document) <= MAX_CONTROL_LENGTH and document != state.get("last_sent"):
            sent = self.native_webrtc_control(session_id, label, json.dumps({"type": "connection_capabilities", "document": document}))
            if sent.get("accepted"):
                state["last_sent"] = document

    def _maintain_native_controls(self):
        # Runs independently of WebView timers and compares the current signed
        # document, so consent/token changes propagate on an existing channel.
        now = time.monotonic()
        if now < getattr(self, "_native_control_next", 0):
            return
        self._native_control_next = now + 3
        for session_id, state in list(self._native_webrtc_controls.items()):
            if session_id not in self._native_webrtc_live:
                continue
            label = state.get("label")
            if not label:
                continue
            try:
                if not state.get("request_sent"):
                    state["request_sent"] = self.native_webrtc_control(session_id, label,
                        '{"type":"connection_capabilities_request"}').get("accepted")
                self._native_control_refresh(session_id, label)
            except Exception:
                pass

    def _native_onboarding_approval(self, contact, approved, capabilities=None):
        for session_id, peer in list(self._native_webrtc_peers.items()):
            if peer != contact["destination_hash"] or session_id not in self._native_webrtc_live:
                continue
            if approved:
                try:
                    self._native_control_refresh(session_id, "mesh-onboarding")
                except Exception:
                    pass
            message = {"type": "invitation_approved" if approved else "invitation_denied"}
            if approved and capabilities:
                message["capabilities"] = capabilities
            try:
                self.native_webrtc_control(session_id, "mesh-onboarding", json.dumps(message))
            except Exception:
                pass

    def _share_native_capabilities(self, contact_id, document):
        if not isinstance(document, str) or not document or len(document) > MAX_CONTROL_LENGTH:
            return False
        shared = False
        for session_id, state in list(self._native_webrtc_controls.items()):
            try:
                if self._native_control_contact(session_id) != contact_id or not state.get("label"):
                    continue
                sent = self.native_webrtc_control(session_id, state["label"], json.dumps({
                    "type": "connection_capabilities", "document": document}))
                if sent.get("accepted"):
                    state["last_sent"] = document
                    shared = True
            except Exception:
                pass
        return shared
