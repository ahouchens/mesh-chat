"""Private, user-admitted native pairing effects for the shared supervisor.

The trusted host supplies current caller authority. Public JSON cannot supply
that capability, physical leases, documents, or reducer events through this port.
"""
from __future__ import annotations

from hashlib import sha256
import json
import time
from weakref import ref
from uuid import UUID, uuid4, uuid5

from .call_manager import CallOutcomeRequiresResync
from .connection.model import Resource
from .connection.reconcile import connection_key
from .errors import ContactNotApproved, NativeUnavailable, ValidationError
from .signal_mailbox import parse_pairing

CHANNELS = [
    {"label": "mesh-reticulum", "binary": True, "ordered": True},
    {"label": "mesh-onboarding", "binary": False, "ordered": True},
]


class NativePairingServiceMixin:
    def native_pairing_begin(self, operation_id, *, role, authorized,
                             pairing_code=None, allow_direct_ip_disclosure=False):
        """Trusted host admission; A binds caller/key before invoking this port."""
        with self._dispatch_lock:
            if (getattr(self, "_connection_policy", "legacy") != "shared-native"
                    or not callable(authorized) or not authorized()):
                raise ContactNotApproved("Native pairing authority is unavailable")
            self._require_native_work()
            profile = self._require_profile()
            if role not in {"offer", "answer"} or type(allow_direct_ip_disclosure) is not bool:
                raise ValidationError("Native pairing intent is invalid")
            if (role == "offer" and pairing_code is not None) or (role == "answer" and not pairing_code):
                raise ValidationError("Native pairing invitation is invalid")
            base = self._call_settings.signal_mailbox_url
            if base is None:
                raise NativeUnavailable("Signaling mailbox is not configured")
            imported = parse_pairing(pairing_code, base) if role == "answer" else None
            operation_id, digest, replay = self._workspace_operation("native.pairing", operation_id, {
                "role": role, "pairing_digest": sha256((pairing_code or "").encode()).hexdigest(),
                "allow_direct_ip_disclosure": allow_direct_ip_disclosure})
            contexts = self._native_pairing_contexts = getattr(self, "_native_pairing_contexts", {})
            if replay is not None:
                context = contexts.get(operation_id)
                if (replay.get("runtime_epoch") != self._runtime_incarnation or context is None
                        or replay.get("identity_hash") != profile["identity_hash"]):
                    raise CallOutcomeRequiresResync("Native pairing intent requires a fresh runtime")
                self._native_pairing_check(context, terminal=True)
                return self._native_pairing_projection(context)
            if len(contexts) >= 32 or any(context.get("state") not in {"retired", "transferred"}
                                          for context in contexts.values()):
                raise NativeUnavailable("Native pairing capacity reached")
            context = {"id": operation_id, "role": role, "authorized": authorized,
                       "runtime_epoch": self._runtime_incarnation, "identity": ref(self._identity),
                       "identity_hash": profile["identity_hash"], "mailbox_url": base,
                       "session": "pairing-" + uuid4().hex, "code": pairing_code,
                       "expires_at": min(time.time() + 300, imported["expires_at"] if imported else float("inf")),
                       "direct": allow_direct_ip_disclosure, "state": "reserved", "admitted": False,
                       "physical": None, "source": None, "allocation_attempted": False}
            contexts[operation_id] = context
            intent = {"action": "native_pairing", "runtime_epoch": self._runtime_incarnation,
                      "identity_hash": profile["identity_hash"], "intent": operation_id,
                      "session": context["session"], "expires_at": context["expires_at"]}
            try:
                self.store.commit_operation(operation_id, digest, intent, ())
            except Exception:
                if self.store.operation_result(operation_id, digest) != intent:
                    contexts.pop(operation_id, None)
                    raise
            context["admitted"] = True
            self._native_pairing_check(context)
            return self._native_pairing_projection(context)

    def _native_pairing_check(self, context, *, terminal=False):
        self._require_native_work()
        if (not context.get("admitted") or self._identity is not context["identity"]()
                or self._runtime_incarnation != context["runtime_epoch"]
                or self._call_settings.signal_mailbox_url != context["mailbox_url"]
                or (context.get("physical") is not None and self._native_webrtc_host() is not context.get("host"))
                or time.time() >= context["expires_at"] or not context["authorized"]()
                or (not terminal and context["state"] in {"retired", "retiring", "transferred"})):
            raise ContactNotApproved("Native pairing authority is no longer current")

    def native_pairing_status(self, operation_id):
        with self._dispatch_lock:
            context = getattr(self, "_native_pairing_contexts", {}).get(operation_id)
            if context is None:
                raise CallOutcomeRequiresResync("Native pairing intent is unavailable")
            self._native_pairing_check(context, terminal=True)
            return self._native_pairing_projection(context)

    @staticmethod
    def _native_pairing_projection(context):
        # The pairing code is returned only by this authorized private port.
        return {"intent": context["id"], "state": context["state"],
                "expires_at": context["expires_at"],
                "pairing_code": context["code"] if context["state"] == "offer_ready" else None}

    def native_pairing_cancel(self, operation_id):
        with self._dispatch_lock:
            context = getattr(self, "_native_pairing_contexts", {}).get(operation_id)
            if context is None:
                raise CallOutcomeRequiresResync("Native pairing intent is unavailable")
            self._native_pairing_check(context, terminal=True)
            if context["state"] == "transferred":
                return {"intent": operation_id, "state": "transferred"}
            self._connection_runtime.fence(operation_id)
            context["state"] = "retiring" if context["source"] is not None else "retired"
            context["code"] = None
            return {"intent": operation_id, "state": context["state"]}

    def _native_pairing_profiles(self):
        with self._dispatch_lock:
            result = []
            for context in getattr(self, "_native_pairing_contexts", {}).values():
                try:
                    self._native_pairing_check(context)
                    active = context["state"] != "retiring"
                except Exception:
                    active = False
                result.append({"id": context["id"], "scope_kind": "pairing",
                    "local_device_id": context["identity_hash"], "active": active,
                    "state": "active" if active else "stopped", "trust": "pairing",
                    "effective": {"ready": active, "preferred": context["role"] == "offer"}})
            return result

    def _native_pairing_context(self, key):
        with self._dispatch_lock:
            context = getattr(self, "_native_pairing_contexts", {}).get(key.profile_id)
            if context is None or key.scope != "pairing" or key.local_device != context["identity_hash"]:
                raise ContactNotApproved("Native pairing intent is unavailable")
            self._native_pairing_check(context)
            return context

    def _native_pairing_reserve(self, context, resource):
        with self._dispatch_lock:
            self._native_pairing_check(context)
            if context["source"] not in (None, resource):
                raise CallOutcomeRequiresResync("Native pairing allocation cannot be replaced")
            context["source"] = resource

    def _native_pairing_allocation_reserved(self, session, physical):
        # Called immediately after registry reservation, before the native call.
        for context in getattr(self, "_native_pairing_contexts", {}).values():
            if context["session"] == session:
                context["physical"] = physical
                return

    def _native_pairing_owned(self, session):
        return any(context["session"] == session and context["state"] != "transferred"
                   for context in getattr(self, "_native_pairing_contexts", {}).values())

    def _native_pairing_blocks_profile(self, profile):
        """Approval cannot start a competing reconnect before initial handoff."""
        if profile["id"] in self._native_webrtc_profile_sessions:
            return False
        # This is a denial-only projection of host-derived profile data. Pending
        # contacts legitimately have device profiles before approval; requiring
        # reconnect authority here would fault and fence the entire runtime.
        destination = profile.get("destination_hash")
        return any(context["state"] not in {"transferred", "retired"}
                   and destination is not None
                   and self._native_webrtc_peers.get(context["session"]) == destination
                   for context in getattr(self, "_native_pairing_contexts", {}).values())

    def _native_pairing_gather(self, context):
        with self._dispatch_lock:
            self._native_pairing_check(context)
            if context["allocation_attempted"]:
                raise CallOutcomeRequiresResync("Native pairing allocation outcome requires resync")
            context["allocation_attempted"] = True
            context["host"] = self._native_webrtc_host()
        ice = self.call_ice_servers()
        self._native_pairing_check(context)
        if not context["direct"]:
            ice = {**ice, "iceTransportPolicy": "relay"}
        if context["role"] == "offer":
            native = self.native_webrtc_offer(context["session"], ice, CHANNELS)
            self._native_pairing_check(context)
            document = self.webrtc_onboarding_offer(native["sdp"], native["fingerprint"])
            context["offer"] = document
        else:
            native = self.native_webrtc_accept(context["session"], context["offer"]["sdp"], ice, CHANNELS)
            self._native_pairing_check(context)
            context["answer"] = self.webrtc_onboarding_answer(context["offer"]["document"], native["sdp"], native["fingerprint"])
            self._native_pairing_check(context)
            self.native_webrtc_bind_onboarding(context["session"], context["offer"]["document"], context["answer"]["document"])
        return False

    def _native_pairing_publish(self, context):
        self._native_pairing_check(context)
        role = context["role"]
        result = self.keyed_signal_publish(context[role]["document"], role,
                                          str(uuid5(UUID(context["id"]), "native-pairing-publish-" + role)))
        context["code"] = result["session_id"]
        context["state"] = "offer_ready" if role == "offer" else "awaiting_approval"
        return False

    def _native_pairing_fetch(self, context, role):
        self._native_pairing_check(context)
        fetched = self.signal_fetch(context["code"], role, pending=True)
        self._native_pairing_check(context)
        if not fetched.get("document"):
            return True
        verified = (self.verify_webrtc_onboarding_offer(fetched["document"]) if role == "offer"
                    else self.verify_webrtc_onboarding_answer(context["offer"]["document"], fetched["document"]))
        peer = verified["signer_destination"]
        contact = self._contact_by_destination(peer)
        if peer == self._require_profile()["destination_hash"] or (contact and contact.get("trust") == "blocked"):
            raise ContactNotApproved("Native pairing peer is unavailable")
        context[role] = verified
        return False

    def _native_pairing_apply(self, context):
        self._native_pairing_check(context)
        self.native_webrtc_bind_onboarding(context["session"], context["offer"]["document"], context["answer"]["document"])
        self._native_pairing_check(context)
        self.native_webrtc_apply_answer(context["session"], context["answer"]["sdp"])
        context["state"] = "awaiting_approval"
        return False

    def _native_pairing_target(self, context):
        self._native_pairing_check(context)
        if not self._native_resources.current(context["session"], context["physical"]):
            return None
        profile_id = self._native_webrtc_controls.get(context["session"], {}).get("profile_id")
        if not profile_id:
            return None
        try:
            profile = self._reconnect_profile(profile_id)
            session = self._authorized_manual_native_carrier(profile, allow_pairing_session=context["session"])
        except (ContactNotApproved, ValidationError):
            return None
        stats = self.native_webrtc_stats(context["session"])
        if (session != context["session"] or stats.get("ice_connection_state") not in {"connected", "completed"}
                or stats.get("data_channel_state") != "open"):
            return None
        return connection_key(profile)

    def _native_pairing_ready(self, context):
        with self._dispatch_lock, self._native_webrtc_lock:
            self._native_pairing_check(context)
            if context["role"] == "offer" and not context.get("invitation_sent"):
                if "invitation" not in context:
                    context["invitation"] = self.invitation(connection_mode="webrtc")["file"]
                self._native_pairing_check(context)
                context["invitation_sent"] = self.native_webrtc_control(context["session"], "mesh-onboarding",
                    json.dumps({"type": "contact_invitation", "document": context["invitation"]}))["accepted"]
            return self._native_pairing_target(context) is not None

    def _native_pairing_handoff(self, operation, source, commit):
        with self._dispatch_lock, self._native_webrtc_lock:
            context = self._native_pairing_context(operation.key)
            target = self._native_pairing_target(context)
            self._native_pairing_check(context)
            if context["source"] != source or target is None:
                raise ContactNotApproved("Native pairing transfer authority changed")
            if not commit(Resource("native", context["physical"]), target):
                raise NativeUnavailable("Native pairing transfer lease changed")
            # A failed return after this assignment is safe: the supervisor
            # owns pending physical custody until the exact target adopts it.
            context["state"] = "transferred"
            context["code"] = None

    def _native_pairing_retire(self, context, resource):
        if resource == context["source"] and context["state"] == "transferred":
            return
        physical = context.get("physical")
        if physical is not None:
            if self._native_resources.current(context["session"], physical):
                self.native_webrtc_close(context["session"], expected_physical=physical)
            else:
                # A failed create can release the logical registry reservation
                # while its exact native close still needs acknowledgement.
                context["host"].close(physical)
        context["state"] = "retired"
        context["code"] = None
