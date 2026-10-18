"""Protected email setup lifecycle; public methods return no native controls.

Document preparation is independent of hosting success. Accepted documents alone
are not permission to attach the bootstrap adapter or claim remote receipt.
"""
from __future__ import annotations

import hashlib
import socket
import threading
import time

from .direct_binding import BindingAuthority, create_binding
from .direct_candidates import prepare_candidates
from .direct_documents import export_connection_document, verify_connection_document
from .direct_exchange import create_answer, create_ready
from .direct_offer import OfferAuthority, create_offer
from .errors import ValidationError
from .workspace_protocol import _destination_for, _identity_from_public_key


class DirectSetup:
    def __init__(self, service):
        self.service = service
        self._lock = threading.Lock()
        self._prepared = {}
        self._carriers = {}
        self._retiring = 0
        self._closed = False
        self._epoch = 0
        self._inflight = 0

    def _available(self):
        self.service._check_direct_runtime_available()
        if self.service._direct_native is None:
            raise ValidationError("Native direct transport is unavailable")
        with self._lock:
            if self._closed:
                raise ValidationError("Direct setup is closed")

    def _id(self, role, identifier):
        return self.service.store.opaque_id("direct-setup", role+":"+identifier)

    def _prepare(self, setup_id, generation, expires_at, family=None):
        self._available()
        with self._lock:
            active = setup_id in self._carriers
        if active:
            self.cancel(setup_id)
        with self._lock:
            if len(self._prepared)+self._retiring+self._inflight >= 8:
                raise ValidationError("Direct setup capacity exhausted")
            epoch = self._epoch
            self._inflight += 1
        try:
            prepared = prepare_candidates(self.service._direct_native, generation=generation, expires_at=expires_at, family=family)
        except BaseException:
            with self._lock:
                self._inflight -= 1
            raise
        with self._lock:
            self._inflight -= 1
            retired = self._closed or self._epoch != epoch
            previous = None
            if not retired:
                previous = self._prepared.get(setup_id)
                self._prepared[setup_id] = prepared
        if retired:
            prepared.close()
            raise ValidationError("Direct setup was retired")
        if previous is not None:
            previous.close()
        return prepared

    def _state(self, setup_id, state, kind, workspace_id, fields, text=None):
        value = {"setup_id":setup_id,"state":state,"kind":kind,"workspace_id":workspace_id,
                 "expires_at":fields["expires_at"],"candidate_count":len(fields["candidates"])}
        self.service.store.put("direct_setup", setup_id, value)
        self.service._changed()
        return {**value, **({"text":text} if text is not None else {})}

    def status(self, setup_id):
        if not isinstance(setup_id, str):
            raise ValidationError("Direct setup identifier is invalid")
        value = self.service.store.get("direct_setup", setup_id)
        if value is None:
            raise ValidationError("Direct setup is unavailable")
        with self._lock:
            retained = setup_id in self._prepared
        if value["state"] != "cancelled" and (value["expires_at"] <= time.time() or not retained):
            return {**value, "state":"refresh_required",
                    "reason":"details_expired" if value["expires_at"] <= time.time() else "socket_not_retained"}
        return value

    def preview(self, document):
        return verify_connection_document(document).preview()

    @staticmethod
    def _family(checked):
        from .direct_binding import _parse
        candidates = _parse(checked.offer)["candidates"]
        if not candidates and checked.answer is not None:
            candidates = _parse(checked.answer)["binding"]["candidates"]
        if not candidates:
            return None
        return socket.AF_INET6 if ":" in candidates[0]["host"] else socket.AF_INET

    def offer(self, invitation_id):
        self._available()
        service = self.service
        invite, owner = service._direct_owner_invitation(invitation_id)
        setup_id = self._id("owner", invitation_id)
        now = int(time.time())
        prior = service.store.get("direct_pending", invitation_id)
        expiry = min(now+240, invite.expires_at)
        if prior is None:
            record = service._prepare_direct_invitation(invitation_id, expiry)
        elif prior["expires_at"] <= now:
            record = service._replace_direct_invitation(invitation_id, prior["challenge"], expiry)
        else:
            record = prior
        generation = max(record.get("offer_accepted", {}).get("generation", 0),
                         record.get("ready_accepted", {}).get("generation", 0)) + 1
        prepared = self._prepare(setup_id, generation, record["expires_at"])
        try:
            fields = prepared.document_fields()
            authority = OfferAuthority(owner.public_identity, record["scope"], record["expires_at"], bytes.fromhex(record["challenge"]))
            raw = create_offer(service._identity, authority, fields["certificate"],
                session_id=fields["session_id"], generation=generation, candidates=fields["candidates"],
                issued_at=int(time.time()), expires_at=fields["expires_at"], version=2)
            service._save_direct_offer(invitation_id, raw, fields["certificate"])
            prepared.document_fields()
            text = export_connection_document(invite.serialized, raw, fields["certificate"])
            return self._state(setup_id, "waiting_for_reply", "offer", invite.workspace_id, fields, text)
        except Exception:
            self.cancel(setup_id)
            raise

    def answer(self, document, operation_id):
        self._available()
        checked = verify_connection_document(document)
        if checked.kind != "offer":
            raise ValidationError("A connection Offer is required")
        service, invite = self.service, checked.invitation
        workspace = service.store.get("workspace", service._workspace_record_id(invite.workspace_id))
        if workspace is None:
            service.submit_workspace_join(invite.serialized, operation_id)
        # Existing joining records are rechecked against the exact signed invitation.
        owner = _destination_for(_identity_from_public_key(checked.offer_authority.issuer_public_identity))
        local = _destination_for(service._identity)
        expected = BindingAuthority(checked.offer_authority.issuer_public_identity, local,
            checked.offer_authority.scope, checked.offer_authority.expires_at, checked.offer_authority.challenge)
        service._direct_join_binding_authority(invite.workspace_id, expected)
        previous = service.store.get("direct_join_exchange", service._workspace_record_id(invite.workspace_id))
        generation = (previous or {}).get("answer_accepted", {}).get("generation", 0)+1
        setup_id = self._id("joiner", invite.workspace_id)
        prepared = self._prepare(setup_id, generation, expected.expires_at, self._family(checked))
        try:
            fields = prepared.document_fields()
            authority = BindingAuthority(service._identity.get_public_key(), owner, expected.scope,
                expected.expires_at, expected.challenge)
            binding = create_binding(service._identity, authority, fields["certificate"],
                session_id=fields["session_id"], challenge=expected.challenge, generation=generation,
                candidates=fields["candidates"], issued_at=int(time.time()), expires_at=fields["expires_at"], version=2)
            answer = create_answer(service._identity, binding, checked.offer)
            accepted = service._save_direct_join_answer(invite.workspace_id, checked.offer, checked.offer_certificate,
                answer, fields["certificate"], expected)
            service._direct_native.request("arm", id=prepared.handle, session=fields["session_id"],
                generation=generation, digest=accepted.digest)
            prepared.document_fields()
            text = export_connection_document(invite.serialized, checked.offer, checked.offer_certificate,
                answer=answer, answer_certificate=fields["certificate"])
            return self._state(setup_id, "waiting_for_ready", "answer", invite.workspace_id, fields, text)
        except Exception:
            self.cancel(setup_id)
            raise

    def ready(self, document):
        self._available()
        checked = verify_connection_document(document)
        if checked.kind != "answer":
            raise ValidationError("A connection Answer is required")
        service, invite = self.service, checked.invitation
        invitation_id = service._workspace_invitation_record_id(invite.nonce)
        accepted = service._accept_direct_answer(invitation_id, checked.answer, checked.answer_authority, checked.answer_certificate)
        record = service.store.get("direct_pending", invitation_id)
        generation = max(record["offer_accepted"]["generation"], record.get("ready_accepted", {}).get("generation", 0))+1
        setup_id = self._id("owner", invitation_id)
        # The owner refreshes its key; the joiner retains its exact Answer socket.
        from .direct_binding import _parse
        expiry = min(record["expires_at"], _parse(checked.answer)["binding"]["expires_at"], _parse(checked.offer)["expires_at"])
        prepared = self._prepare(setup_id, generation, expiry, self._family(checked))
        try:
            fields = prepared.document_fields()
            peer = _destination_for(_identity_from_public_key(checked.answer_authority.issuer_public_identity))
            authority = BindingAuthority(service._identity.get_public_key(), peer, record["scope"],
                expiry, bytes.fromhex(record["challenge"]))
            binding = create_binding(service._identity, authority, fields["certificate"],
                session_id=fields["session_id"], challenge=authority.challenge, generation=generation,
                candidates=fields["candidates"], issued_at=int(time.time()), expires_at=fields["expires_at"], version=2)
            ready = create_ready(service._identity, binding, checked.answer)
            service._save_direct_owner_ready(invitation_id, ready, fields["certificate"])
            service._direct_native.request("arm", id=prepared.handle, session=fields["session_id"],
                generation=generation, digest=accepted.digest)
            prepared.document_fields()
            text = export_connection_document(invite.serialized, checked.offer, checked.offer_certificate,
                answer=checked.answer, answer_certificate=checked.answer_certificate,
                ready=ready, ready_certificate=fields["certificate"])
            return self._state(setup_id, "ready_to_share", "ready", invite.workspace_id, fields, text)
        except Exception:
            self.cancel(setup_id)
            raise

    def accept_ready(self, document):
        self._available()
        checked = verify_connection_document(document)
        if checked.kind != "ready":
            raise ValidationError("A connection Ready document is required")
        service, workspace_id = self.service, checked.invitation.workspace_id
        setup_id = self._id("joiner", workspace_id)
        with self._lock:
            prepared = self._prepared.get(setup_id)
        if prepared is None:
            raise ValidationError("Answer socket was not retained; create a fresh reply")
        fields = prepared.document_fields()
        if fields["certificate"] != checked.answer_certificate:
            raise ValidationError("Ready does not match the retained Answer socket")
        accepted = service._accept_direct_ready(workspace_id, checked.ready, checked.ready_certificate)
        service._direct_native.request("rearm", id=prepared.handle,
            answer=hashlib.sha256(checked.answer.encode()).hexdigest(), generation=accepted.generation, ready=accepted.digest)
        return self._state(setup_id, "ready_received", "ready", workspace_id, fields)

    def cancel(self, setup_id):
        if not isinstance(setup_id, str):
            raise ValidationError("Direct setup identifier is invalid")
        with self._lock:
            prepared = self._prepared.pop(setup_id, None)
            carrier = self._carriers.pop(setup_id, None)
        if carrier is not None:
            if hasattr(carrier,"expected"):
                from .direct_relationship import relationship_id
                self.service._direct_recovery.pause(relationship_id(self.service.store,carrier.expected))
            carrier.close()
        if prepared is not None:
            prepared.close()
        value = self.service.store.get("direct_setup", setup_id)
        if value is not None:
            self.service.store.put("direct_setup", setup_id, {**value,"state":"cancelled"})
        return {"setup_id":setup_id,"state":"cancelled"}

    def connect(self, setup_id, document):
        from .direct_binding import _parse
        from .direct_bootstrap_authority import BootstrapAuthority
        from .direct_bootstrap_carrier import BootstrapCarrier
        from .direct_path import native_parameters
        from .direct_handoff import AdmissionHandoff
        from .invitations import canonical_bytes
        self._available()
        checked = verify_connection_document(document)
        if checked.kind != "ready":
            raise ValidationError("A complete Ready chain is required")
        service = self.service
        public = service._identity.get_public_key()
        owner = public == checked.offer_authority.issuer_public_identity
        if not owner and public != checked.answer_authority.issuer_public_identity:
            raise ValidationError("Direct documents address a different device")
        expected_id = self._id("owner", service._workspace_invitation_record_id(checked.invitation.nonce)) if owner else self._id("joiner", checked.invitation.workspace_id)
        if setup_id != expected_id:
            raise ValidationError("Direct setup identifier does not match this exchange")
        with self._lock:
            prepared = self._prepared.get(setup_id)
            existing = self._carriers.get(setup_id)
        if existing is not None:
            if existing.authority.checked.serialized != checked.serialized:
                raise ValidationError("A different bootstrap exchange is active")
            return self.status(setup_id)
        if prepared is None:
            raise ValidationError("Direct socket was not retained; refresh connection details")
        fields = prepared.document_fields()
        if fields["certificate"] != (checked.ready_certificate if owner else checked.answer_certificate):
            raise ValidationError("Direct documents do not match the retained socket")
        authority = BootstrapAuthority(service, checked, owner=owner)
        peer_binding = _parse(checked.answer if owner else checked.ready)["binding"]
        if not fields["candidates"] and not peer_binding["candidates"]:
            return self._state(setup_id, "existing_routes_only", "ready", checked.invitation.workspace_id, fields)
        parameters = native_parameters(service._identity, fields["candidates"],
            canonical_bytes(peer_binding).decode(), checked.answer_certificate if owner else checked.ready_certificate)
        parameters["remaining_ms"] = min(parameters["remaining_ms"], int((fields["expires_at"]-time.time())*1000))
        def changed(state):
            with service._dispatch_lock:
                if service._shutdown.is_set():
                    return
                with self._lock:
                    if self._carriers.get(setup_id) is not carrier:
                        return
                self._state(setup_id, state, "ready", checked.invitation.workspace_id, fields)
        def promoted(admitted, state):
            with service._dispatch_lock:
                if state == "admitted_path":
                    service._check_direct_runtime_available()
                elif service._shutdown.is_set():
                    return
                with self._lock:
                    current = self._carriers.get(setup_id)
                    if state == "admitted_path":
                        if current is not carrier:
                            raise ValidationError("Bootstrap promotion was retired")
                        self._carriers[setup_id] = admitted
                        self._prepared[setup_id] = admitted.prepared
                    elif current is not admitted:
                        return
                self._state(setup_id, state, "ready", checked.invitation.workspace_id,
                    {"expires_at":admitted.prepared.expires_at,"candidates":admitted.prepared._candidates})
        handoff = AdmissionHandoff(service, authority, promoted)
        carrier = BootstrapCarrier(service, prepared, authority, parameters, state_changed=changed,
                                   control_received=handoff.receive)
        with self._lock:
            if self._closed or self._prepared.get(setup_id) is not prepared:
                retired = True
            else:
                retired = False
                self._carriers[setup_id] = carrier
        if retired:
            carrier.close()
            raise ValidationError("Direct setup was retired")
        state = self._state(setup_id, "connecting", "ready", checked.invitation.workspace_id, fields)
        carrier.start()
        handoff.start(carrier)
        return state

    def retire(self, *, close=False):
        with self._lock:
            self._closed = self._closed or close
            self._epoch += 1
            prepared, self._prepared = list(self._prepared.values()), {}
            carriers, self._carriers = list(self._carriers.values()), {}
            self._retiring += len(prepared)
        def cleanup():
            for carrier in carriers:
                try:
                    carrier.close()
                except Exception:
                    pass
            for item in prepared:
                try:
                    item.close()
                except Exception:
                    # One failed cleanup must not strand the remaining sockets.
                    pass
                finally:
                    with self._lock:
                        self._retiring -= 1
        if prepared:
            threading.Thread(target=cleanup, daemon=True, name="mesh-chat-direct-cleanup").start()
