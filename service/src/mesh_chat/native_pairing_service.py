"""Private, user-admitted native pairing effects for the shared supervisor.

The trusted host supplies current caller authority. Public JSON cannot supply
that capability, physical leases, documents, or reducer events through this port.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import time
from weakref import ref
from uuid import UUID, uuid4, uuid5

from .call_manager import CallOutcomeRequiresResync
from .connection.diagnostics import (
    gather_failure_at_deadline, gather_failure_at_result, validated_checking_observation,
    validated_gather_for_retirement,
)
from .connection.pairing_ice_diagnostics import (
    ice_diagnostic, ufrag_pair, unavailable_ice_diagnostic, validated_pairing_ice_diagnostic,
)
from .connection.model import Phase, Resource
from .connection.reconcile import authority_signature, connection_key
from .errors import ContactNotApproved, NativeUnavailable, ValidationError
from .signal_mailbox import parse_pairing

CHANNELS = [
    {"label": "mesh-reticulum", "binary": True, "ordered": True},
    {"label": "mesh-onboarding", "binary": False, "ordered": True},
]


@dataclass(frozen=True)
class _CarrierRetirement:
    request: tuple
    ticket: object
    runtime: object
    host: object
    identity: object


class NativePairingServiceMixin:
    native_pairing_public_intents = True

    def _native_retirement_context(self, operation_id):
        context = getattr(self, "_native_pairing_contexts", {}).get(operation_id)
        try:
            valid = (context is not None and context["state"] == "transferred" and context["admitted"]
                     and context["runtime_epoch"] == self._runtime_incarnation
                     and context["identity"]() is self._identity
                     and context["host"] is self._native_webrtc_host()
                     and context["authorized"]() is True)
        except Exception:
            valid = False
        if not valid:
            self.native_pairing_invalidate_retirement(operation_id)
            raise ContactNotApproved("Carrier retirement context is unavailable")
        return context

    def native_pairing_invalidate_retirement(self, operation_id):
        with self._dispatch_lock:
            context = getattr(self, "_native_pairing_contexts", {}).get(operation_id)
            record = context.get("carrier_retirement") if context is not None else None
            if record is not None:
                record.runtime.invalidate_carrier_retirement(record.ticket)

    def _native_retirement_record(self, context):
        record = context.get("carrier_retirement")
        if record is None:
            raise NativeUnavailable("Carrier retirement request is unavailable")
        if (record.runtime is not self._connection_runtime or record.host is not self._native_webrtc_host()
                or record.identity is not self._identity):
            record.runtime.invalidate_carrier_retirement(record.ticket)
            raise NativeUnavailable("Carrier retirement request changed")
        if not record.ticket.acknowledged:
            try:
                _, logical, physical, incarnation, epoch = record.request
                current = self._native_resources.physical(logical)
                sequence = getattr(self, "_native_path_sequences", {}).get(physical)
                profile = self._reconnect_profile(record.ticket.key.profile_id)
                public = self._reconnect_profile_public(profile)
                signature = authority_signature({**public, "manual_carrier_authorized":
                    self.native_manual_carrier_authorized(profile["id"])})
                valid = (incarnation == self._runtime_incarnation
                         and (context["session"], context["physical"]) == (logical, physical)
                         and logical not in getattr(self, "_native_recovered_bindings", {})
                         and current in (physical, None)
                         and (record.ticket.close_started or current == physical)
                         and (sequence is not None or record.ticket.close_started)
                         and (sequence is None or sequence[0] == epoch)
                         and connection_key(profile) == record.ticket.key
                         and profile.get("contact_id") == record.ticket.contact_id
                         and profile.get("state") != "stopped"
                         and ((record.ticket.projection_revision is None and signature == record.ticket.signature) or (
                             record.ticket.close_started and signature == record.ticket.cleared_signature)))
            except Exception:
                self._native_pairing_retirement_proof_failed(record)
                raise
            if not valid:
                self._native_pairing_retirement_proof_failed(record)
                raise ContactNotApproved("Carrier retirement authority changed")
        return record

    @staticmethod
    def _native_pairing_retirement_proof_failed(record):
        try:
            record.runtime.invalidate_carrier_retirement(record.ticket)
        except Exception:
            # A proof observer must never prevent exact native disposal. The
            # request remains unusable even if its guard release also failed.
            if not record.ticket.acknowledged:
                record.ticket.invalidated = True

    def native_pairing_retire_carrier(self, operation_id, *, action, request_id, logical_session,
                                     expected_physical, expected_service_incarnation,
                                     expected_adapter_epoch):
        with self._dispatch_lock, self._native_webrtc_lock:
            if type(action) is not str or action not in {"prepare", "commit"}:
                raise ValidationError("Carrier retirement action is invalid")
            context = self._native_retirement_context(operation_id)
            request = (request_id, logical_session, expected_physical,
                       expected_service_incarnation, expected_adapter_epoch)
            previous = context.get("carrier_retirement")
            if previous is not None:
                if previous.request != request:
                    raise ValidationError("Carrier retirement request changed")
                record = self._native_retirement_record(context)
                if action == "commit" and not record.ticket.committed and not record.ticket.acknowledged:
                    try:
                        record.runtime.commit_carrier_retirement(record.ticket)
                    except ValueError as error:
                        raise NativeUnavailable("Carrier retirement owner changed") from error
                    return {"request_id": request_id, "state": "pending"}
                return self.native_pairing_retirement_observation(operation_id, request_id)
            if action != "prepare":
                raise NativeUnavailable("Carrier retirement preparation is unavailable")
            self._require_native_work()
            if (expected_service_incarnation != self._runtime_incarnation
                    or context["session"] != logical_session or context["physical"] != expected_physical
                    or logical_session not in self._native_webrtc_live
                    or logical_session in self._native_webrtc_creating
                    or logical_session in getattr(self, "_native_recovered_bindings", {})
                    or not self._native_resources.current(logical_session, expected_physical)
                    or getattr(self, "_native_path_sequences", {}).get(expected_physical, (None,))[0]
                       != expected_adapter_epoch):
                raise NativeUnavailable("Carrier retirement resource changed")
            profiles = [profile for profile, session in self._native_webrtc_profile_sessions.items()
                        if session == logical_session]
            if len(profiles) != 1:
                raise NativeUnavailable("Carrier retirement owner is ambiguous")
            profile = self._reconnect_profile(profiles[0])
            control = self._native_webrtc_controls.get(logical_session, {})
            from .native_webrtc_control import profile_binding
            if (profile.get("scope_kind", "contact") != "contact"
                    or profile.get("auto_reconnect") is not False
                    or control.get("profile_id") != profile["id"]
                    or control.get("profile_binding") != profile_binding(profile)
                    or not self._native_carrier_authorized(logical_session)
                    or self._authorized_manual_native_carrier(profile) != logical_session):
                raise ContactNotApproved("Carrier retirement owner is unavailable")
            runtime = self._connection_runtime
            key = connection_key(profile)
            state = runtime.owner.snapshot(key)
            try:
                ticket = runtime.prepare_carrier_retirement(
                    key, Resource("native", expected_physical), state.generation, state.authority.revision,
                    contact_id=profile["contact_id"],
                    signature=authority_signature({**self._reconnect_profile_public(profile),
                                                   "manual_carrier_authorized": True}))
            except ValueError as error:
                raise NativeUnavailable("Carrier retirement owner changed") from error
            context["carrier_retirement"] = _CarrierRetirement(
                request, ticket, runtime, context["host"], self._identity)
            return {"request_id": request_id, "state": "prepared"}

    def native_pairing_retirement_observation(self, operation_id, request_id):
        with self._dispatch_lock:
            context = self._native_retirement_context(operation_id)
            record = self._native_retirement_record(context)
            if record.request[0] != request_id:
                raise NativeUnavailable("Carrier retirement request is unavailable")
            try:
                return {"request_id": request_id,
                        "state": record.runtime.carrier_retirement_status(record.ticket)}
            except ValueError as error:
                raise NativeUnavailable("Carrier retirement request is unavailable") from error

    def native_pairing_carrier_observation(self, operation_id, logical_session, expected_physical,
                                           expected_service_incarnation, expected_profile_incarnation):
        """Read one exact transferred resource after its live registry may be gone."""
        from .connection.carrier_observation import carrier_projection
        unavailable = carrier_projection(None)
        try:
            with self._dispatch_lock, self._native_webrtc_lock:
                context = getattr(self, "_native_pairing_contexts", {}).get(operation_id)
                matches = [item for item in getattr(self, "_native_pairing_contexts", {}).values()
                           if item.get("state") == "transferred"
                           and item.get("session") == logical_session
                           and item.get("physical") == expected_physical]
                if (context is None or len(matches) != 1 or matches[0] is not context
                        or context.get("state") != "transferred" or not context.get("admitted")
                        or context.get("session") != logical_session
                        or context.get("physical") != expected_physical
                        or context.get("runtime_epoch") != expected_service_incarnation
                        or self._runtime_incarnation != expected_service_incarnation
                        or context["identity"]() is not self._identity
                        or context.get("host") is not self._native_webrtc_host()
                        or context["authorized"]() is not True):
                    return unavailable
                identity = self._identity
                profile_incarnation = sha256((self._runtime_incarnation + identity.hash.hex()).encode("ascii")).hexdigest()[:32]
                if profile_incarnation != expected_profile_incarnation:
                    return unavailable
                anchor = context.get("carrier_observation_anchor")
                if anchor is None:
                    return unavailable
                target, resource, runtime, owner, trace = anchor
                if (resource != Resource("native", expected_physical)
                        or runtime is not self._connection_runtime
                        or owner is not runtime.owner
                        or target.scope != "contact" or target.profile_id == context["id"]
                        or trace is None or trace.key != target or trace.resource != resource
                        or trace.runtime_epoch != expected_service_incarnation):
                    return unavailable
                return owner.carrier_observation(trace)
        except Exception:
            return unavailable

    def _native_pairing_carrier_edge(self, logical_session, physical, kind):
        """Called under service dispatch/native locks before exact registry release."""
        try:
            contexts = tuple(getattr(self, "_native_pairing_contexts", {}).values())
        except Exception:
            return
        for context in contexts:
            try:
                anchor = context.get("carrier_observation_anchor")
                if (anchor is None or context.get("state") != "transferred"
                        or context.get("session") != logical_session
                        or context.get("physical") != physical
                        or context.get("runtime_epoch") != self._runtime_incarnation
                        or context["identity"]() is not self._identity
                        or context.get("host") is not self._native_webrtc_host()):
                    continue
                target, resource, runtime, owner, trace = anchor
                if (resource == Resource("native", physical)
                        and runtime is self._connection_runtime and owner is runtime.owner):
                    owner.native_carrier_observation(trace, kind)
            except Exception:
                # An optional observer must not affect native disposal.
                try:
                    context["carrier_observation_anchor"] = None
                except Exception:
                    pass

    def native_pairing_retirement_pending(self):
        with self._dispatch_lock:
            return any(record is not None and not record.ticket.acknowledged
                       for context in getattr(self, "_native_pairing_contexts", {}).values()
                       for record in (context.get("carrier_retirement"),))

    def _native_pairing_retirement_edge(self, physical, *, closed=False):
        """Trusted exact physical lifecycle edge; never infer it from absence."""
        for context in getattr(self, "_native_pairing_contexts", {}).values():
            record = context.get("carrier_retirement")
            if record is None or record.request[2] != physical or record.ticket.acknowledged:
                continue
            try:
                self._native_retirement_context(context["id"])
                record = self._native_retirement_record(context)
                if closed:
                    record.runtime.carrier_retirement_native_closed(record.ticket)
                else:
                    record.runtime.carrier_retirement_close_started(record.ticket)
            except Exception:
                self._native_pairing_retirement_proof_failed(record)

    def _native_pairing_retirement_projections(self):
        projections = []
        for context in getattr(self, "_native_pairing_contexts", {}).values():
            record = context.get("carrier_retirement")
            if record is None or record.ticket.acknowledged or record.ticket.invalidated:
                continue
            try:
                self._native_retirement_context(context["id"])
                self._native_retirement_record(context)
                if record.ticket.close_started:
                    projections.append(record.ticket)
            except Exception:
                self._native_pairing_retirement_proof_failed(record)
        return tuple(projections)

    def _native_pairing_retirement_clearances(self):
        """Fresh local absence facts; only runtime cleanup results acknowledge disposal."""
        runtime = self._connection_runtime
        acknowledged = runtime.cleanup_acknowledged_retirements()
        clearances = []
        for context in getattr(self, "_native_pairing_contexts", {}).values():
            record = context.get("carrier_retirement")
            if (record is None or record.ticket not in acknowledged or record.runtime is not runtime
                    or record.host is not self._native_webrtc_host() or record.identity is not self._identity
                    or context["runtime_epoch"] != self._runtime_incarnation):
                continue
            try:
                self._native_retirement_context(context["id"])
                self._native_retirement_record(context)
                if self._native_retirement_cleared(record):
                    clearances.append(record.ticket)
            except Exception:
                pass  # An unknown local projection cannot acknowledge retirement.
        return tuple(clearances)

    def _native_retirement_cleared(self, record):
        _, logical, physical, _, _ = record.request
        with self._native_webrtc_lock:
            if (self._native_resources.physical(logical) is not None
                    or self._native_resources.resolve(physical) is not None
                    or logical in self._native_webrtc_live or logical in self._native_webrtc_creating
                    or logical in self._native_webrtc_descriptions
                    or record.ticket.key.profile_id in self._native_webrtc_profile_sessions):
                return False
        journal = getattr(self, "_carrier_journal", None)
        if journal is not None and any(binding.resource == physical for binding in journal.bindings()):
            return False
        return not self.native_manual_carrier_authorized(record.ticket.key.profile_id)

    def native_pairing_begin(self, operation_id, *, role, authorized,
                             pairing_code=None, allow_direct_ip_disclosure=False,
                             cancel_requested=None, on_terminal=None, expires_at=None):
        """Trusted host admission; A binds caller/key before invoking this port."""
        with self._dispatch_lock:
            if (getattr(self, "_connection_policy", "legacy") != "shared-native"
                    or not callable(authorized) or not authorized()
                    or (cancel_requested is not None and not callable(cancel_requested))
                    or (on_terminal is not None and not callable(on_terminal))):
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
            if expires_at is not None:
                if (type(expires_at) not in (int, float) or not math.isfinite(expires_at)
                        or not 0 < expires_at <= time.time() + 300):
                    raise ValidationError("Native pairing deadline is invalid")
                expires_at = float(expires_at)
            inputs = {
                "role": role, "pairing_digest": sha256((pairing_code or "").encode()).hexdigest(),
                "allow_direct_ip_disclosure": allow_direct_ip_disclosure}
            if expires_at is not None:
                inputs["expires_at"] = expires_at
            operation_id, digest, replay = self._workspace_operation("native.pairing", operation_id, inputs)
            contexts = self._native_pairing_contexts = getattr(self, "_native_pairing_contexts", {})
            if replay is not None:
                context = contexts.get(operation_id)
                if (replay.get("runtime_epoch") != self._runtime_incarnation or context is None
                        or replay.get("identity_hash") != profile["identity_hash"]):
                    raise CallOutcomeRequiresResync("Native pairing intent requires a fresh runtime")
                self._native_pairing_check(context, terminal=True)
                self._native_pairing_notify_terminal(context)
                return self._native_pairing_projection(context)
            if len(contexts) >= 32 or any(context.get("state") not in {"retired", "transferred"}
                                          for context in contexts.values()):
                raise NativeUnavailable("Native pairing capacity reached")
            context = {"id": operation_id, "role": role, "authorized": authorized,
                       "cancel_requested": cancel_requested, "on_terminal": on_terminal,
                       "runtime_epoch": self._runtime_incarnation, "identity": ref(self._identity),
                       "identity_hash": profile["identity_hash"], "mailbox_url": base,
                       "session": "pairing-" + uuid4().hex, "code": pairing_code,
                       "expires_at": min(time.time() + 300, expires_at if expires_at is not None else float("inf"),
                                         imported["expires_at"] if imported else float("inf")),
                       "direct": allow_direct_ip_disclosure, "state": "reserved", "admitted": False,
                       "physical": None, "source": None, "allocation_attempted": False,
                       "gather_work": None, "gather_stages": (), "gather_exception": None}
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
        if not terminal and self._native_pairing_reconcile_cancel(context):
            raise ContactNotApproved("Native pairing cancellation is committed")
        if (not context.get("admitted") or self._identity is not context["identity"]()
                or self._runtime_incarnation != context["runtime_epoch"]
                or self._call_settings.signal_mailbox_url != context["mailbox_url"]
                or (context.get("physical") is not None and self._native_webrtc_host() is not context.get("host"))
                or time.time() >= context["expires_at"] or not context["authorized"]()
                or (not terminal and context["state"] in {"retired", "retiring", "transferred"})):
            raise ContactNotApproved("Native pairing authority is no longer current")

    @staticmethod
    def _native_pairing_notify_terminal(context):
        state = context["state"]
        callback = context.get("on_terminal")
        if (state in {"retired", "transferred"} and callback is not None
                and context.get("terminal_checkpoint") != state):
            callback(state)
            context["terminal_checkpoint"] = state

    def _native_pairing_cancel_context(self, context):
        with self._dispatch_lock:
            if context["state"] not in {"retired", "transferred"}:
                self._connection_runtime.fence(context["id"])
                context["state"] = "retiring" if context["source"] is not None else "retired"
                context["code"] = None
            self._native_pairing_notify_terminal(context)

    def _native_pairing_reconcile_cancel(self, context):
        callback = context.get("cancel_requested")
        if context["state"] in {"retired", "transferred"}:
            return False
        if time.time() >= context["expires_at"]:
            self._native_pairing_cancel_context(context)
            return True
        if callback is None:
            return False
        try:
            cancelled = callback()
            if type(cancelled) is not bool:
                cancelled = True
        except Exception:
            cancelled = True
        if cancelled:
            self._native_pairing_cancel_context(context)
        return cancelled

    def native_pairing_status(self, operation_id):
        with self._dispatch_lock:
            context = getattr(self, "_native_pairing_contexts", {}).get(operation_id)
            if context is None:
                raise CallOutcomeRequiresResync("Native pairing intent is unavailable")
            self._native_pairing_check(context, terminal=True)
            self._native_pairing_notify_terminal(context)
            return self._native_pairing_projection(context)

    def native_pairing_qualification_status(self, operation_id):
        """Private fresh-profile qualification only; ordinary status is unchanged."""
        with self._dispatch_lock:
            result = self.native_pairing_status(operation_id)
            if result["state"] in {"retiring", "retired"}:
                context = self._native_pairing_contexts[operation_id]
                try:
                    bound_source = self._native_pairing_ice_bound_source(context)
                except Exception:
                    bound_source = False
                if not bound_source:
                    context["ice_diagnostic_snapshot"] = unavailable_ice_diagnostic()
                key = connection_key({"id": context["id"], "scope_kind": "pairing",
                                      "local_device_id": context["identity_hash"]})
                result["retirement"] = self._connection_runtime.owner.pairing_retirement_diagnostic(
                    key=key, runtime_epoch=context["runtime_epoch"], source=context["source"])
                if result["retirement"] == {"phase": "checking", "event": "tick", "reason": "phase_timeout"}:
                    if "ice_diagnostic_snapshot" not in context:
                        try:
                            context["ice_diagnostic_snapshot"] = self._native_pairing_ice_diagnostic(
                                operation_id, context)
                        except Exception:
                            context["ice_diagnostic_snapshot"] = unavailable_ice_diagnostic()
                    try:
                        selected = validated_pairing_ice_diagnostic(context["ice_diagnostic_snapshot"])
                        if (selected is None or not self._native_pairing_ice_bound_source(context)
                                or self._native_pairing_ice_conflict(context, selected)):
                            context["ice_diagnostic_snapshot"] = unavailable_ice_diagnostic()
                            selected = unavailable_ice_diagnostic()
                        result["ice_diagnostic"] = selected
                    except Exception:
                        context["ice_diagnostic_snapshot"] = unavailable_ice_diagnostic()
                        result["ice_diagnostic"] = unavailable_ice_diagnostic()
                gather = self._native_pairing_gather_failure_snapshot(context, result["retirement"])
                if gather is not None:
                    result["gather_failure"] = gather
            return result

    def _native_pairing_gather_failure_snapshot(self, context, retirement):
        """Select only the exact source-custodied gather result from in-memory state."""
        if "gather_failure_snapshot" not in context:
            try:
                phase = "gather_offer" if context["role"] == "offer" else "gather_answer"
                observed = None
                if retirement.get("phase") == phase:
                    key = connection_key({"id": context["id"], "scope_kind": "pairing",
                                          "local_device_id": context["identity_hash"]})
                    owner = self._connection_runtime.owner
                    args = {"key": key, "runtime_epoch": context["runtime_epoch"], "source": context["source"]}
                    custody = owner.pairing_gather_deadline_diagnostic(**args)
                    if custody is not None:
                        work, deadline = custody
                        same_work = (context.get("gather_work") is work if phase == "gather_offer"
                                     else context.get("gather_work") == work)
                        stages = context["gather_stages"] if same_work else None
                        observed = gather_failure_at_deadline(deadline,
                            self._connection_runtime.runner.gather_milestones(work), stages, phase=phase)
                    else:
                        custody = owner.pairing_gather_failed_diagnostic(**args)
                        if custody is not None:
                            work, cutoff = custody
                            same_work = (context.get("gather_work") is work if phase == "gather_offer"
                                         else context.get("gather_work") == work)
                            stages = context["gather_stages"] if same_work else None
                            marker = context.get("gather_exception")
                            if phase == "gather_offer":
                                matched = (type(marker) is tuple and len(marker) == 3 and marker[0] is work)
                                kind, code = marker[1:] if matched else ("unknown", "unknown")
                                if not matched:
                                    stages = None
                            else:
                                kind, code = (marker[1:] if marker is not None and marker[0] == work
                                              else ("unknown", "unknown"))
                            observed = gather_failure_at_result(cutoff,
                                self._connection_runtime.runner.gather_milestones(work), stages,
                                kind, code, phase=phase)
                context["gather_failure_snapshot"] = validated_gather_for_retirement(retirement, observed)
            except Exception:
                context["gather_failure_snapshot"] = None
        selected = context["gather_failure_snapshot"]
        return dict(selected) if selected is not None else None

    def _native_pairing_ice_diagnostic(self, operation_id, context):
        """One retained-SDP snapshot for the exact admitted terminal pairing."""
        unavailable = unavailable_ice_diagnostic()
        contexts = getattr(self, "_native_pairing_contexts", {})
        if (type(contexts) is not dict or len(contexts) > 32 or contexts.get(operation_id) is not context
                or context.get("id") != operation_id or context.get("state") not in {"retiring", "retired"}
                or not context.get("admitted") or context.get("runtime_epoch") != self._runtime_incarnation
                or context["identity"]() is not self._identity
                or context.get("host") is not self._native_webrtc_host()
                or context["authorized"]() is not True
                or getattr(getattr(self, "_connection_runtime", None), "owner", None) is None
                or self._connection_runtime.owner.runtime_epoch != context["runtime_epoch"]
                or not self._native_pairing_ice_bound_source(context)
                or type(context.get("session")) is not str):
            return unavailable
        physical = self._native_resources.physical(context["session"])
        if physical is not None and physical != context["physical"]:
            return unavailable
        pair = self._native_pairing_retained_sdp_pair(context)
        if pair is None or context.get("role") not in {"offer", "answer"}:
            return unavailable
        local, remote = (pair if context["role"] == "offer" else pair[::-1])
        selected = ice_diagnostic(local, remote)
        if selected["availability"] != "selected":
            return unavailable
        return unavailable if self._native_pairing_ice_conflict(context, selected) else selected

    @staticmethod
    def _native_pairing_ice_bound_source(context):
        physical = context.get("physical")
        source = context.get("source")
        return (type(physical) is str and type(source) is Resource
                and source.adapter_epoch == "native"
                and context.get("ice_source_binding") == (context.get("id"), context.get("runtime_epoch"),
                    source, context.get("session"), physical))

    def _native_pairing_retained_sdp_pair(self, context):
        """Verify both retained signed documents without consulting native state."""
        offer, answer = context.get("offer"), context.get("answer")
        if type(offer) is not dict or type(answer) is not dict:
            return None
        offer_doc, answer_doc = offer.get("document"), answer.get("document")
        if type(offer_doc) is not str or type(answer_doc) is not str:
            return None
        try:
            verified_offer = self.verify_webrtc_onboarding_offer(offer_doc)
            verified_answer = self.verify_webrtc_onboarding_answer(offer_doc, answer_doc)
        except Exception:
            return None
        offer_sdp, answer_sdp = verified_offer.get("sdp"), verified_answer.get("sdp")
        if (type(offer_sdp) is not str or type(answer_sdp) is not str
                or ("sdp" in offer and offer["sdp"] != offer_sdp)
                or ("sdp" in answer and answer["sdp"] != answer_sdp)):
            return None
        return offer_sdp, answer_sdp

    def _native_pairing_ice_conflict(self, context, selected):
        if selected["availability"] != "selected":
            return False
        contexts = getattr(self, "_native_pairing_contexts", {})
        if type(contexts) is not dict or len(contexts) > 32:
            return True
        target_pair = frozenset(selected["correlation"].values())
        if len(target_pair) != 2:
            return True
        for other in contexts.values():
            if other is context or type(other) is not dict or not other.get("admitted"):
                continue
            if type(other.get("offer")) is not dict or type(other.get("answer")) is not dict:
                continue
            other_sdp = self._native_pairing_retained_sdp_pair(other)
            other_pair = ufrag_pair(*other_sdp) if other_sdp is not None else None
            if other_pair is None or other_pair == target_pair:
                return True
        return False

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
            self._native_pairing_cancel_context(context)
            return {"intent": operation_id, "state": context["state"]}

    def _native_pairing_profiles(self):
        with self._dispatch_lock:
            result = []
            for context in getattr(self, "_native_pairing_contexts", {}).values():
                try:
                    self._native_pairing_notify_terminal(context)
                    self._native_pairing_reconcile_cancel(context)
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

    def _native_pairing_mark_gather_work(self, context, work):
        """Bind the exact admitted gather work without a lock or host call."""
        try:
            expected = Phase.GATHER_OFFER if context["role"] == "offer" else Phase.GATHER_ANSWER
            if (work.phase is expected
                    and work.operation.key.scope == "pairing"
                    and work.operation.key.profile_id == context["id"]
                    and work.operation.key.local_device == context["identity_hash"]
                    and work.operation.runtime_epoch == context["runtime_epoch"]
                    and work.resource == context["source"]
                    and context.get("gather_work") in (None, work)):
                context["gather_work"] = work
        except Exception:
            pass

    def _native_pairing_mark_gather_failure(self, context, work, kind, code):
        """Retain only fixed labels bound to this exact gather Work."""
        try:
            expected = Phase.GATHER_OFFER if context["role"] == "offer" else Phase.GATHER_ANSWER
            if (context.get("gather_work") == work and work.phase is expected
                    and work.operation.runtime_epoch == context["runtime_epoch"]
                    and work.resource == context["source"]
                    and context.get("gather_exception") is None):
                context["gather_exception"] = (work, kind, code)
        except Exception:
            pass

    def _native_pairing_stage(self, context, label, state):
        try:
            allowed = ({"ice_config", "native_offer", "offer_sign", "complete"}
                       if context["role"] == "offer" else
                       {"ice_config", "native_accept", "answer_sign", "bind_onboarding", "complete"})
            if (context.get("gather_work") is not None and
                    label in allowed
                    and state in {"entered", "completed"}):
                history = context["gather_stages"]
                if history is not None and len(history) < 9:
                    context["gather_stages"] = (*history, (label, state, self._connection_runtime.now()))
        except Exception:
            self._native_pairing_invalidate_stage(context)

    def _native_pairing_invalidate_stage(self, context):
        try:
            history = context["gather_stages"]
            if history is not None and len(history) < 9:
                try:
                    when = self._connection_runtime.now()
                except Exception:
                    when = None
                context["gather_stages"] = (*history, ("invalid", "invalid", when))
            else:
                context["gather_stages"] = None
        except Exception:
            pass

    def _native_pairing_note_stage(self, context, label, state):
        try:
            self._native_pairing_stage(context, label, state)
        except Exception:
            self._native_pairing_invalidate_stage(context)

    def _native_pairing_allocation_reserved(self, session, physical):
        # Called immediately after registry reservation, before the native call.
        for context in getattr(self, "_native_pairing_contexts", {}).values():
            if context["session"] == session:
                context["physical"] = physical
                if "ice_source_binding" not in context:
                    context["ice_source_binding"] = (context["id"], context["runtime_epoch"],
                        context["source"], session, physical)
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
        self._native_pairing_note_stage(context, "ice_config", "entered")
        ice = self.call_ice_servers()
        self._native_pairing_note_stage(context, "ice_config", "completed")
        self._native_pairing_check(context)
        if not context["direct"]:
            ice = {**ice, "iceTransportPolicy": "relay"}
        if context["role"] == "offer":
            self._native_pairing_note_stage(context, "native_offer", "entered")
            native = self.native_webrtc_offer(context["session"], ice, CHANNELS)
            self._native_pairing_note_stage(context, "native_offer", "completed")
            self._native_pairing_check(context)
            self._native_pairing_note_stage(context, "offer_sign", "entered")
            document = self.webrtc_onboarding_offer(native["sdp"], native["fingerprint"])
            self._native_pairing_note_stage(context, "offer_sign", "completed")
            context["offer"] = document
            self._native_pairing_note_stage(context, "complete", "completed")
        else:
            self._native_pairing_note_stage(context, "native_accept", "entered")
            native = self.native_webrtc_accept(context["session"], context["offer"]["sdp"], ice, CHANNELS)
            self._native_pairing_note_stage(context, "native_accept", "completed")
            self._native_pairing_check(context)
            self._native_pairing_note_stage(context, "answer_sign", "entered")
            context["answer"] = self.webrtc_onboarding_answer(context["offer"]["document"], native["sdp"], native["fingerprint"])
            self._native_pairing_note_stage(context, "answer_sign", "completed")
            self._native_pairing_check(context)
            self._native_pairing_note_stage(context, "bind_onboarding", "entered")
            self.native_webrtc_bind_onboarding(context["session"], context["offer"]["document"], context["answer"]["document"])
            self._native_pairing_note_stage(context, "bind_onboarding", "completed")
            self._native_pairing_note_stage(context, "complete", "completed")
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
            self._native_pairing_note_checking(context, "missing", "not_checked")
            return None
        profile_id = self._native_webrtc_controls.get(context["session"], {}).get("profile_id")
        if not profile_id:
            self._native_pairing_note_checking(context, "current", "unbound")
            return None
        try:
            profile = self._reconnect_profile(profile_id)
        except (ContactNotApproved, ValidationError):
            self._native_pairing_note_checking(context, "current", "unavailable")
            return None
        try:
            session = self._authorized_manual_native_carrier(profile, allow_pairing_session=context["session"])
        except (ContactNotApproved, ValidationError):
            self._native_pairing_note_checking(context, "current", "denied")
            return None
        stats = self.native_webrtc_stats(context["session"])
        self._native_pairing_note_checking(context, "current",
            "authorized" if session == context["session"] else "denied",
            "connected" if stats.get("ice_connection_state") in {"connected", "completed"} else "not_connected",
            "open" if stats.get("data_channel_state") == "open" else "not_open")
        if (session != context["session"] or stats.get("ice_connection_state") not in {"connected", "completed"}
                or stats.get("data_channel_state") != "open"):
            return None
        return connection_key(profile)

    def _native_pairing_note_checking(self, context, resource, profile, ice="not_checked", channel="not_checked"):
        """Retain fixed last-poll labels under the existing exact source custody."""
        try:
            context["checking_observation"] = (
                (context["id"], context["runtime_epoch"], context["source"],
                 context["session"], context["physical"]),
                {"as_of": "last_checking_poll", "resource": resource, "profile": profile,
                 "ice": ice, "channel": channel})
        except Exception:
            pass  # Optional observation cannot affect pairing.

    def _native_pairing_checking_observation_snapshot(self, context, retirement):
        try:
            binding, observed = context["checking_observation"]
            if binding != (context["id"], context["runtime_epoch"], context["source"],
                           context["session"], context["physical"]):
                return None
            return validated_checking_observation(retirement, observed)
        except Exception:
            return None

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
            profile = self._reconnect_profile(target.profile_id)
            if connection_key(profile) != target:
                raise ContactNotApproved("Native pairing target changed")
            if not commit(Resource("native", context["physical"]), target, contact_id=profile["contact_id"]):
                raise NativeUnavailable("Native pairing transfer lease changed")
            # A failed return after this assignment is safe: the supervisor
            # owns pending physical custody until the exact target adopts it.
            context["state"] = "transferred"
            context["code"] = None
            try:
                runtime = self._connection_runtime
                owner = runtime.owner
                resource = Resource("native", context["physical"])
                trace = owner.watch_carrier_observation(target, resource)
                context["carrier_observation_anchor"] = (target, resource, runtime, owner, trace)
            except Exception:
                context["carrier_observation_anchor"] = None
            self._native_pairing_notify_terminal(context)

    def _native_pairing_retire(self, context, resource):
        if resource == context["source"] and context["state"] == "transferred":
            self._native_pairing_notify_terminal(context)
            return
        if context["state"] == "retired":
            self._native_pairing_notify_terminal(context)
            return
        physical = context.get("physical")
        if physical is not None:
            if self._native_resources.current(context["session"], physical):
                self.native_webrtc_close(context["session"], expected_physical=physical)
            else:
                # A failed create can release the logical registry reservation
                # while its exact native close still needs acknowledgement.
                context["host"].close(physical)
        if context["state"] != "transferred":
            context["state"] = "retired"
            context["code"] = None
        self._native_pairing_notify_terminal(context)
