"""Trusted runtime binding whose profile authority survives a closed vault.

Platform hosts supply existing OS key-slot openers and a separate protected
catalog store. No profile decrypt key, path or opener comes from public JSON.
The catalog retains derived handle keys to preserve existing opaque handles.
"""
from dataclasses import dataclass, replace
import hashlib
import hmac
import json
import secrets
import threading
import time
import uuid
from weakref import WeakSet

from ..errors import NativeUnavailable, StorageUnavailable, ValidationError
from ..native_profile_lifecycle import ProfileRuntimeLifecycle, ProfileSlot
from .composition import bind_service_session
from .errors import ApiFailure
from .requests import COMPONENT_OPERATIONS, PROFILE_RUNTIME_OPERATIONS as RUNTIME_OPERATIONS, parse_request
from .session import Grant
from .wire import FramedSession
from .profile_intents import ProfileIntents, NativeOrigin, CredentialRevocationAck

MAX_HOST_OPERATIONS = 4096
MAX_CALLER_OPERATIONS = 256
MAX_CREDENTIALS = 128


@dataclass(frozen=True)
class RegisteredProfile:
    profile_id: str
    display_name: str
    handle_key: bytes
    open: object  # Trusted zero-argument opener; fetches existing OS slot afresh.


def _material(*parts):
    return json.dumps(parts, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def _handle(key, caller, kind, internal):
    return hmac.new(key, b"mesh-core-handle:v1:" + _material(caller, kind, "local", internal), hashlib.sha256).hexdigest()


class CoreRuntimeHost:
    def __init__(self, catalog_store, profiles, *, selected, publish, credential_authorizer,
                 active=None, clock=time.monotonic, intent_origin=None, intent_auth=None, intent_binding=None):
        profiles = tuple(profiles)
        if (not 1 <= len(profiles) <= 8 or len({p.profile_id for p in profiles}) != len(profiles)
                or selected not in {p.profile_id for p in profiles}
                or any(not isinstance(p, RegisteredProfile) or not isinstance(p.profile_id, str)
                       or not 1 <= len(p.profile_id) <= 80 or not isinstance(p.display_name, str)
                       or not 1 <= len(p.display_name) <= 80 or not isinstance(p.handle_key, bytes)
                       or len(p.handle_key) != 32 or not callable(p.open) for p in profiles)
                or not callable(publish) or not callable(credential_authorizer)):
            raise ValueError("Trusted profile catalog is invalid")
        if active is not None and catalog_store is active.store:
            raise ValueError("Host catalog must outlive the profile vault")
        self.store, self.profiles = catalog_store, {p.profile_id: p for p in profiles}
        self._publish_platform, self._credential_authorizer = publish, credential_authorizer
        self._clock, self._lock, self._credentials = clock, threading.RLock(), {}
        self._sessions, self._published, self._invocation = WeakSet(), active, None
        self._credential_bindings, self._intent_invocation = {}, None
        with self._lock:
            expected, records = {}, []
            for profile in profiles:
                value = {"display_name": profile.display_name, "handle_key": profile.handle_key.hex()}
                prior = self.store.get("host_profile", profile.profile_id)
                if prior is not None:
                    if (prior.get("handle_key") != value["handle_key"] or not isinstance(prior.get("display_name"), str)
                            or not 1 <= len(prior["display_name"]) <= 80):
                        raise ValueError("Existing profile handle authority cannot change")
                    value = prior
                    self.profiles[profile.profile_id] = replace(profile, display_name=prior["display_name"])
                expected[("host_profile", profile.profile_id)] = prior
                records.append(("host_profile", profile.profile_id, value))
            selection = self.store.get("host_profile_catalog", "selection")
            expected[("host_profile_catalog", "selection")] = selection
            if selection is None:
                records.append(("host_profile_catalog", "selection", {"selected": selected}))
            else:
                selected = selection.get("selected")
                if selected not in self.profiles:
                    raise ValueError("Persisted selection requires a registered host slot")
            if active is not None and bytes.fromhex(active.store.opaque_id("core-api-handle-key", "v1")) != self.profiles[selected].handle_key:
                raise ValueError("Active profile does not match persisted handle authority")
            self.store.conditional_put_and_delete(expected, records)
        self.lifecycle = ProfileRuntimeLifecycle(tuple(ProfileSlot(p.profile_id,
            lambda profile=p: self._open(profile)) for p in profiles), selected,
            publish=self._publish, remember_selection=self._remember_selection,
            read_selection=lambda: self.store.get("host_profile_catalog", "selection")["selected"], active=active)
        self.profile_intents = ProfileIntents(self, origin=intent_origin, auth=intent_auth, binding=intent_binding,
                                            limits=lambda: (MAX_HOST_OPERATIONS, MAX_CALLER_OPERATIONS))

    def _remember_selection(self, profile_id):
        self.store.put("host_profile_catalog", "selection", {"selected": profile_id})

    def _recheck_invocation(self):
        if self._invocation is None:
            raise ApiFailure("forbidden")
        authorize, caller, profile_id = self._invocation
        grant = authorize()
        if (not isinstance(grant, Grant) or grant.caller != caller
                or "profile_owner" not in grant.permissions or profile_id not in grant.profiles):
            raise ApiFailure("forbidden")
        if self._intent_invocation is not None:
            row, attachment = self._intent_invocation
            self.profile_intents._validate(grant, row, attachment, "open")

    def _open(self, profile):
        self._recheck_invocation()
        opened = profile.open()  # Existing OS key slot is authoritative; never cached here.
        if (opened is None or not callable(getattr(opened, "close", None))
                or not callable(getattr(getattr(opened, "_shutdown", None), "is_set", None))
                or type(getattr(opened, "_store_closed", None)) is not bool
                or not isinstance(getattr(opened, "_runtime_incarnation", None), str)):
            return opened  # The lifecycle port quarantines a malformed provider.
        try:
            if bytes.fromhex(opened.store.opaque_id("core-api-handle-key", "v1")) != profile.handle_key:
                raise NativeUnavailable("Profile opener returned a different key slot")
        except Exception as error:
            # Acquisition transferred custody. Preserve it for every validation
            # failure, including storage exceptions and malformed key material.
            error.retiring_service = opened
            raise
        return opened

    def _publish(self, service):
        if service is not None:
            self._recheck_invocation()
            if self._intent_invocation is not None:
                row, attachment = self._intent_invocation
                self.profile_intents._validate(self._invocation[0](), row, attachment, "publish")
        previous, self._published = self._published, None
        if previous is not None:
            for session in tuple(self._sessions):
                session.retire(previous)
            from .android_host import retire
            retire(previous)
        self._publish_platform(service)
        self._published = service

    def issue_unlock_credential(self, caller, profile_id, *, lifetime_seconds=60):
        """Trusted host-authentication hook, never a public request operation."""
        with self._lock:
            if (not isinstance(caller, str) or not 1 <= len(caller) <= 200 or profile_id not in self.profiles
                    or type(lifetime_seconds) is not int or not 1 <= lifetime_seconds <= 300
                    or self._credential_authorizer(caller, profile_id) is not True):
                raise ApiFailure("forbidden")
            now = self._clock()
            self._credentials = {key: value for key, value in self._credentials.items() if value[4] > now}
            if len(self._credentials) >= MAX_CREDENTIALS:
                raise ApiFailure("resource_exhausted")
            token = secrets.token_hex(32)
            status = self.lifecycle.query()
            self._credentials[token] = (caller, profile_id, status["host_incarnation"], status["revision"], now + lifetime_seconds)
            return token

    def _credential(self, token, caller, profile_id, *, consume=False, bound_identity=None):
        binding = self._credential_bindings.get(token)
        if binding is not None and binding[0] != bound_identity:
            raise ApiFailure("forbidden")
        value = self._credentials.get(token)
        status = self.lifecycle.query()
        expected = caller, profile_id, status["host_incarnation"], status["revision"]
        if value is None or value[:4] != expected or value[4] <= self._clock():
            raise ApiFailure("forbidden")
        if consume:
            del self._credentials[token]
            self._credential_bindings.pop(token, None)

    def issue_bound_unlock_credential(self, authorize, *, intent_ref, attachment, proof, lifetime_seconds=60):
        """Trusted native proof and document binding; no public credential route."""
        with self._lock:
            intents = self.profile_intents
            grant, row = intents._row(authorize, intent_ref)
            intents._validate(grant, row, attachment, "auth_issue")
            if (row["action"] != "unlock" or row["state"] not in {"prepared", "intent"}
                    or not intents._view(intent_ref, row)["replay_eligible"]
                    or type(lifetime_seconds) is not int or not 1 <= lifetime_seconds <= 300
                    or not callable(getattr(intents.auth, "consume_authorization", None))):
                raise ApiFailure("forbidden")
            status = self.lifecycle.query()
            if (status["host_incarnation"], status["revision"]) != (row["host_incarnation"], row["expected_revision"]):
                raise ApiFailure("resync_required")
            now = self._clock()
            self._credentials = {key: value for key, value in self._credentials.items() if value[4] > now}
            self._credential_bindings = {key: value for key, value in self._credential_bindings.items() if key in self._credentials}
            if len(self._credentials) >= MAX_CREDENTIALS:
                raise ApiFailure("resource_exhausted")
            if intents.auth.consume_authorization(proof, caller=grant.caller, profile_id=row["profile"],
                    intent_ref=intent_ref, origin=intents.binding, attachment=attachment,
                    core_host_incarnation=row["host_incarnation"], expected_revision=row["expected_revision"]) is not True:
                raise ApiFailure("forbidden")
            intents._current(authorize, grant, row["profile"])
            intents._validate(grant, row, attachment, "auth_issue")
            token = secrets.token_hex(32)
            self._credentials[token] = (grant.caller, row["profile"], row["host_incarnation"], row["expected_revision"], now + lifetime_seconds)
            self._credential_bindings[token] = (intent_ref, intents.binding, attachment)
            return token

    def revoke_attachment_credentials(self, *, origin, attachment, cleanup_epoch):
        # Denial-only cleanup accepts the exact *revoked* attachment. Readiness
        # and live grants are intentionally not consulted here.
        with self._lock:
            if (not isinstance(origin, NativeOrigin) or origin != self.profile_intents.binding
                    or type(cleanup_epoch) is not int or cleanup_epoch < 0):
                raise ApiFailure("forbidden")
            for token, (_, bound_origin, bound_attachment) in tuple(self._credential_bindings.items()):
                if origin == bound_origin and attachment is bound_attachment:
                    self._credentials.pop(token, None)
                    del self._credential_bindings[token]
            return CredentialRevocationAck(self.lifecycle.query()["host_incarnation"],
                                           origin.native_host_generation, attachment, cleanup_epoch)

    def revoke_bound_unlock_credential(self, *, token, intent_ref, origin, attachment):
        with self._lock:
            if origin != self.profile_intents.binding:
                raise ApiFailure("forbidden")
            binding = self._credential_bindings.get(token)
            if binding is None:
                if token in self._credentials:
                    raise ApiFailure("forbidden")
                return
            if binding[:2] != (intent_ref, origin) or binding[2] is not attachment:
                raise ApiFailure("forbidden")
            self._credentials.pop(token, None)
            del self._credential_bindings[token]

    def _bound_credential(self, token, identity, row, attachment, *, consume=False):
        binding = self._credential_bindings.get(token)
        if binding is None or binding[:2] != (identity, self.profile_intents.binding) or binding[2] is not attachment:
            raise ApiFailure("forbidden")
        self._credential(token, row["caller"], row["profile"], consume=consume, bound_identity=identity)

    def bind(self, authorize, *, private_native=False, private_composer_legacy=False, private_profile_bootstrap=False):
        if any(type(value) is not bool for value in (private_native, private_composer_legacy, private_profile_bootstrap)):
            raise ValueError("Private runtime ports require host booleans")
        session = RuntimeSession(self, authorize, private_native=private_native,
                                 private_composer_legacy=private_composer_legacy, private_profile_bootstrap=private_profile_bootstrap)
        self._sessions.add(session)
        return FramedSession(session)

    def remember_profile_label(self, profile_id, display_name):
        if not isinstance(display_name, str) or not 1 <= len(display_name) <= 80:
            raise ApiFailure("internal")
        previous = self.store.get("host_profile", profile_id)
        value = {**previous, "display_name": display_name}
        self.store.conditional_put_and_delete({("host_profile", profile_id): previous}, [("host_profile", profile_id, value)])
        self.profiles[profile_id] = replace(self.profiles[profile_id], display_name=display_name)

    def catalog(self, grant):
        status = self.lifecycle.query()
        values = []
        selected_handle = None
        for profile_id in sorted(set(grant.profiles) & set(self.profiles)):
            profile = self.profiles[profile_id]
            handle = _handle(profile.handle_key, grant.caller, "profile", "local")
            selected = profile_id == status["selected_profile"]
            if selected:
                selected_handle = handle
            values.append({"profile": handle, "display_name": profile.display_name,
                           "selected": selected, "state": status["state"] if selected else "locked"})
        return {"profiles": values, "selected_profile": selected_handle, "revision": status["revision"]}

    def _profile_handle(self, caller, profile_id):
        return _handle(self.profiles[profile_id].handle_key, caller, "profile", "local")

    def _target(self, grant, handle):
        target = next((p for p in self.profiles.values() if p.profile_id in grant.profiles
                       and self._profile_handle(grant.caller, p.profile_id) == handle), None)
        if target is None or "profile_owner" not in grant.permissions:
            raise ApiFailure("forbidden")
        return target

    def _operation_record(self, caller, target, operation, key):
        status = self.lifecycle.query()
        identity = self.store.opaque_id("host-profile-operation", caller, target.profile_id, key)
        digest = hmac.new(target.handle_key, b"mesh-core-operation:v1:" + _material(caller, "local", key), hashlib.sha256).digest()[:16]
        return identity, {"caller": caller, "profile": target.profile_id,
                          "input_digest": hashlib.sha256(_material(operation, target.profile_id)).hexdigest(),
                          "operation_id": str(uuid.UUID(bytes=digest)), "host_incarnation": status["host_incarnation"],
                          "expected_revision": status["revision"], "state": "intent"}

    def _lifecycle_request(self, row):
        from ..native_profile_lifecycle import LifecycleRequest
        return LifecycleRequest(operation_id=row["operation_id"], action=row["action"], profile_id=row["profile"],
                                core_host_incarnation=row["host_incarnation"], expected_revision=row["expected_revision"])

    def _finish_operation(self, identity, receipt, result):
        completed = {**receipt, "state": "complete", "revision": result["revision"],
                     "service_incarnation": result["service_incarnation"]}
        self.profile_intents.ledger.finish(identity, receipt, completed)
        return completed

    def _validate_new_transition(self, operation, profile_id, status):
        """Positive checks before a never-invoked request acquires custody."""
        if status["pending_action"] is not None:
            raise ApiFailure("unavailable")
        if operation != "profile.select" and profile_id != status["selected_profile"]:
            raise ApiFailure("invalid_request")

    def _reject_before_first_effect(self, identity, receipt, error):
        rejected = {**receipt, "state": "rejected_no_effect",
                    "rejection_code": error.code if isinstance(error, ApiFailure) else "unavailable"}
        if receipt.get("version") == 2:
            rejected["ever_dispatched"] = False
        self.profile_intents.ledger.finish(identity, receipt, rejected)

    def _dispatch_reserved(self, grant, identity, row, attachment, credential):
        intents, ledger = self.profile_intents, self.profile_intents.ledger
        intents._validate(grant, row, attachment, "observe")
        intents._origin(row)  # Replacement may observe history, never dispatch it.
        status = self.lifecycle.query()
        if row["state"] in {"withdrawn", "rejected_no_effect"}:
            raise ApiFailure("conflict")
        if row["host_incarnation"] != status["host_incarnation"]:
            raise ApiFailure("resync_required")
        if row["state"] == "complete":
            if not intents._view(identity, row)["replay_eligible"]:
                raise ApiFailure("resync_required")
            return intents._view(identity, row)
        ledger.check_slot(identity)
        request = self._lifecycle_request(row)
        fact = self.lifecycle.lookup_exact_completion(request)
        if fact.status == "applied":
            row = self._finish_operation(identity, row, {"revision": fact.result_revision,
                                                        "service_incarnation": fact.result_service_incarnation})
            return intents._view(identity, row)
        if status["revision"] != row["expected_revision"]:
            raise ApiFailure("resync_required")
        if row["state"] == "prepared" and (row["expected_revision"], row["selected_profile"]) != (status["revision"], status["selected_profile"]):
            raise ApiFailure("resync_required")
        if not row["ever_dispatched"]:
            self._validate_new_transition("profile." + row["action"], row["profile"], status)
        if row["action"] == "unlock":
            self._bound_credential(credential, identity, row, attachment)
        previously_dispatched = row["ever_dispatched"]
        admitted = {**row, "state": "intent", "ever_dispatched": True}
        ledger.admit(identity, row, admitted, key=row["original_key"])
        try:
            admission = intents.origin.claim_dispatch(attachment, caller=grant.caller, profile_id=row["profile"],
                                                      expected=intents._origin(row), request=request)
            if admission is None or admission is False:
                raise ApiFailure("forbidden")
            if row["action"] == "unlock":
                self._bound_credential(credential, identity, admitted, attachment, consume=True)
            self._intent_invocation = admitted, attachment
            self._recheck_invocation()
        except (ApiFailure, NativeUnavailable) as error:
            if not previously_dispatched:
                self._reject_before_first_effect(identity, admitted, error)
            raise
        result = self.lifecycle.mutate(row["action"], row["profile"], row["operation_id"],
                                       host_incarnation=row["host_incarnation"], expected_revision=row["expected_revision"])
        if result["pending_action"] is None:
            admitted = self._finish_operation(identity, admitted, result)
        return intents._view(identity, admitted)

    def mutate(self, authorize, grant, operation, params, key, *, attachment=None):
        with self._lock:
            target = self._target(grant, params["profile"])
            profile_id = target.profile_id
            self._invocation = authorize, grant.caller, profile_id
            try:
                self._recheck_invocation()
                identity, proposed = self._operation_record(grant.caller, target, operation, key)
                fingerprint = proposed["input_digest"]
                alias = self.profile_intents.ledger.alias(grant.caller, key)
                if alias is not None and alias["identity"] != identity:
                    raise ApiFailure("idempotency_conflict")
                receipt = self.store.get("host_profile_operation", identity)
                existing = receipt is not None
                status = self.lifecycle.query()
                if receipt is not None and receipt.get("input_digest") != fingerprint:
                    raise ApiFailure("idempotency_conflict")
                if receipt is not None and receipt.get("version") == 2 and alias is None:
                    raise ApiFailure("unavailable")  # Never downgrade a reserved receipt after a stale alias read.
                if alias is not None:
                    if receipt is None or receipt.get("version") != 2:
                        raise ApiFailure("internal")
                    self._dispatch_reserved(grant, identity, receipt, attachment, params.get("credential_handle"))
                    return self.catalog(grant)
                if receipt is None:
                    self._validate_new_transition(operation, profile_id, status)
                    if operation == "profile.unlock":
                        self._credential(params["credential_handle"], grant.caller, profile_id)
                    self.profile_intents.ledger.admit(identity, None, proposed, key=key)
                    receipt = proposed
                if receipt["host_incarnation"] != status["host_incarnation"]:
                    raise ApiFailure("resync_required")
                if receipt["state"] == "rejected_no_effect":
                    raise ApiFailure(receipt["rejection_code"])
                if receipt["state"] == "complete":
                    if (receipt["revision"], receipt["service_incarnation"]) != (status["revision"], status["service_incarnation"]):
                        raise ApiFailure("resync_required")
                    return self.catalog(grant)
                if existing:
                    self.profile_intents.ledger.admit(identity, receipt, receipt, key=key)
                try:
                    if operation == "profile.unlock":
                        completed_open = (existing and status["state"] == "unlocked" and status["selected_profile"] == profile_id
                                          and status["revision"] == receipt["expected_revision"] + 1)
                        if not completed_open:
                            self._credential(params["credential_handle"], grant.caller, profile_id, consume=True)
                    self._recheck_invocation()
                except ApiFailure as error:
                    # Only this fresh, successfully returned admission proves
                    # there was no earlier invocation. Existing/ambiguous rows
                    # retain custody even when the current attempt is denied.
                    if not existing:
                        self._reject_before_first_effect(identity, receipt, error)
                    raise
                result = self.lifecycle.mutate(operation.split(".")[1], profile_id, receipt["operation_id"],
                    host_incarnation=receipt["host_incarnation"], expected_revision=receipt["expected_revision"])
                if result["pending_action"] is None:
                    self._finish_operation(identity, receipt, result)
                return self.catalog(grant)
            finally:
                self._invocation = None
                self._intent_invocation = None


class RuntimeSession:
    def __init__(self, host, authorize, *, private_native, private_composer_legacy, private_profile_bootstrap):
        self.host, self.authorize = host, authorize
        self.private_native, self.private_composer_legacy = private_native, private_composer_legacy
        self.private_profile_bootstrap = private_profile_bootstrap
        self._caller, self._negotiated, self._closed, self._inner, self._service = None, False, False, None, None
        self._lock = threading.RLock()

    @property
    def stopped(self):
        return False

    def detach(self):
        with self._lock:
            self._closed = True
            if self._inner is not None:
                self._inner.detach()
            self._inner = self._service = None

    def retire(self, service):
        # Host serialization precedes session/dispatch work; no worker drain here.
        if self._service is service:
            if self._inner is not None:
                self._inner.detach()
            self._inner = self._service = None

    def _grant(self):
        grant = self.authorize()
        if self._closed or not isinstance(grant, Grant) or (self._caller is not None and self._caller != grant.caller):
            self.detach()
            raise ApiFailure("unauthenticated")
        self._caller = grant.caller
        return grant

    def _current_inner(self, grant):
        status = self.host.lifecycle.query()
        service = self.host.lifecycle.active
        profile_id = status["selected_profile"]
        if profile_id not in grant.profiles:
            raise ApiFailure("forbidden")
        if service is None:
            raise ApiFailure("locked")
        if self._service is not service:
            self.retire(self._service)
            def local_grant():
                # Also used by admitted asynchronous effects. Revocation must
                # not call detach() or wait for this session's request lock
                # while a service worker holds its dispatch lock.
                if self._closed:
                    return None
                current = self.authorize()
                if (not isinstance(current, Grant) or current.caller != self._caller
                        or profile_id not in current.profiles or service is not self.host.lifecycle.active):
                    return None
                return Grant(current.caller, current.permissions, ("local",))
            self._inner = bind_service_session(service, local_grant,
                private_native=self.private_native, private_composer_legacy=self.private_composer_legacy,
                private_profile_bootstrap=self.private_profile_bootstrap,
                handle_key=self.host.profiles[profile_id].handle_key)
            self._service = service
            self._inner.request({"api_version": 1, "request_id": "runtime:negotiate", "operation": "runtime.capabilities", "params": {}})
        return self._inner

    def request(self, value):
        identifier = value.get("request_id") if isinstance(value, dict) else None
        with self.host._lock, self._lock:
            try:
                grant = self._grant()
                operation, params = parse_request(value, tuple(COMPONENT_OPERATIONS) + RUNTIME_OPERATIONS)
                if operation != "runtime.capabilities" and not self._negotiated:
                    raise ApiFailure("negotiation_required")
                permission = "profile_owner" if operation in RUNTIME_OPERATIONS[1:] else "observe"
                if operation in RUNTIME_OPERATIONS + ("runtime.capabilities",) and permission not in grant.permissions:
                    raise ApiFailure("forbidden")
                if operation == "runtime.capabilities":
                    self._negotiated = True
                    result = {"api_major": 1, "api_minor": 1, "stability": "experimental",
                              "operations": ["runtime.capabilities", *RUNTIME_OPERATIONS], "limits": {
                                  "frame_bytes": 4194304, "request_json_depth": 16, "request_json_structural_tokens": 1024,
                                  "profiles": 256, "connections_per_profile": 256}}
                    if self.host.lifecycle.active is not None and self.host.lifecycle.query()["selected_profile"] in grant.profiles:
                        result = dict(self._current_inner(grant).request(value)["result"])
                        result["operations"] = sorted(set(result["operations"]) | set(RUNTIME_OPERATIONS))
                    catalog = self.host.catalog(grant)
                    result["profiles"] = ([catalog["selected_profile"]] if catalog["selected_profile"] is not None else []) + [
                        row["profile"] for row in catalog["profiles"] if row["profile"] != catalog["selected_profile"]]
                    result["limits"] = {**result["limits"], "profile_slots": 8, "profile_lifecycle_keys_per_host": MAX_HOST_OPERATIONS,
                        "profile_lifecycle_keys_per_caller_profile": MAX_CALLER_OPERATIONS, "profile_unlock_credentials": MAX_CREDENTIALS}
                elif operation == "profile.catalog":
                    result = self.host.catalog(grant)
                elif operation in RUNTIME_OPERATIONS:
                    result = self.host.mutate(self.authorize, grant, operation, params, value["idempotency_key"])
                else:
                    response = self._current_inner(grant).request(value)
                    if operation == "profile.create" and response.get("ok"):
                        self.host.remember_profile_label(self.host.lifecycle.query()["selected_profile"], response["result"]["display_name"])
                    return response
                return {"api_version": 1, "request_id": identifier, "ok": True, "result": result}
            except ApiFailure as error:
                code = error.code
            except NativeUnavailable:
                code = "unavailable"
            except (StorageUnavailable, OSError):
                code = "unavailable"
            except ValidationError as error:
                code = "resync_required" if getattr(error, "code", None) == "resync_required" else "invalid_request"
            except Exception:
                code = "internal"
        return {"api_version": 1, "request_id": identifier, "ok": False, "error": {"code": code, "retry_after_ms": None}}
