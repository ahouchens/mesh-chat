"""Hidden trusted-host profile recovery foundation, never a public operation.

The sealed operation row is the only outcome authority. Aliases only locate it;
the dispatch slot protects the native lifecycle's exact completion custody.
Native attachment wiring and platform qualification are deliberately separate.
"""
from dataclasses import asdict, dataclass
from typing import Protocol

from .errors import ApiFailure
from .requests import IDEMPOTENCY_KEY

OPERATIONS = "host_profile_operation"
ALIASES = "host_profile_alias"
DISPATCH = "host_profile_dispatch"
POLICY = "host_profile_admission_policy"
PROTECTED = {"version": 1, "mode": "protected"}
TERMINAL = frozenset({"complete", "withdrawn", "rejected_no_effect"})


@dataclass(frozen=True)
class NativeOrigin:
    provider_binding_id: str
    catalog_binding_id: str
    native_host_generation: str

    def __post_init__(self):
        if any(not isinstance(value, str) or not 1 <= len(value) <= 256
               for value in asdict(self).values()):
            raise ValueError("Invalid trusted native origin")


@dataclass(frozen=True)
class CredentialRevocationAck:
    core_host_incarnation: str
    native_host_generation: str
    attachment: object
    cleanup_epoch: int


class OriginPort(Protocol):
    def capture(self, attachment, *, caller, profile_id) -> NativeOrigin: ...
    def validate(self, attachment, *, caller, profile_id, expected, phase) -> None: ...
    def claim_dispatch(self, attachment, *, caller, profile_id, expected, request) -> object: ...


class AuthPort(Protocol):
    def consume_authorization(self, proof, *, caller, profile_id, intent_ref, origin,
                              attachment, core_host_incarnation, expected_revision) -> bool: ...


@dataclass(frozen=True)
class IntentConfiguration:
    origin: OriginPort
    auth: AuthPort
    binding: NativeOrigin


class OperationLedger:
    def __init__(self, host, limits):
        self.host, self.store, self.limits = host, host.store, limits

    def alias_id(self, caller, key):
        return self.store.opaque_id("host-profile-alias", caller, key)

    def alias(self, caller, key):
        return self.store.get(ALIASES, self.alias_id(caller, key))

    def slot(self):
        return self.store.get(DISPATCH, "current")

    @staticmethod
    def private_evidence(snapshots):
        return bool(snapshots[ALIASES]) or any(row.get("version") == 2 for row in snapshots[OPERATIONS].values())

    def initialize_policy(self, configured, expected, records):
        snapshots = self.snapshots()
        marker, slot = self.store.get(POLICY, "current"), self.slot()
        if marker is not None and marker != PROTECTED:
            raise ApiFailure("unavailable")
        protected = configured or marker is not None or slot is not None or self.private_evidence(snapshots)
        expected.update({(POLICY, "current"): marker, (DISPATCH, "current"): slot})
        if protected and marker is None:
            records.append((POLICY, "current", dict(PROTECTED)))
        return not protected, snapshots

    def policy_read_set(self, snapshots):
        marker, slot = self.store.get(POLICY, "current"), self.slot()
        if self.host._ordinary_catalog:
            if marker is not None or slot is not None or self.private_evidence(snapshots):
                raise ApiFailure("unavailable")
        elif marker != PROTECTED:
            raise ApiFailure("unavailable")
        if not self.host._ordinary_catalog:
            self.validate_aliases(snapshots)
        return {(POLICY, "current"): marker, (DISPATCH, "current"): slot}, slot

    def validate_aliases(self, snapshots):
        for alias_id, alias in snapshots[ALIASES].items():
            row = snapshots[OPERATIONS].get(alias.get("identity"))
            if (row is None or row.get("version") != 2 or row.get("caller") != alias.get("caller")
                    or alias_id != self.alias_id(row["caller"], row.get("original_key", ""))):
                raise ApiFailure("unavailable")
        for identity, row in snapshots[OPERATIONS].items():
            if row.get("version") == 2:
                alias = snapshots[ALIASES].get(self.alias_id(row["caller"], row.get("original_key", "")))
                if alias != {"identity": identity, "caller": row["caller"]}:
                    raise ApiFailure("unavailable")

    def guard_ordinary(self):
        if self.host._ordinary_catalog:
            self.policy_read_set(self.snapshots())

    def check_slot(self, identity):
        if self.host._ordinary_catalog:
            self.guard_ordinary()
            return
        slot = self.slot()
        if slot is not None and slot["identity"] != identity:
            raise ApiFailure("unavailable")
        # Include legacy admitted rows: an upgrade cannot abandon their proof.
        for candidate, row in self.store.items(OPERATIONS, limit=self.limits()[0] + 1):
            if candidate != identity and row.get("state") == "intent":
                raise ApiFailure("unavailable")

    def snapshots(self):
        maximum, _ = self.limits()
        return {kind: dict(self.store.items(kind, limit=maximum + 1)) for kind in (OPERATIONS, ALIASES)}

    def check_capacity(self, snapshots, caller, profile_id):
        maximum, per_profile = self.limits()
        rows = snapshots[OPERATIONS]
        if (len(rows) >= maximum or len(snapshots[ALIASES]) >= maximum or sum(
                row.get("caller") == caller and row.get("profile") == profile_id
                for row in rows.values()) >= per_profile):
            raise ApiFailure("resource_exhausted")

    def reserve(self, identity, row, alias_id):
        snapshots = self.snapshots()
        policy, _ = self.policy_read_set(snapshots)
        if any(self.store.opaque_id("host-profile-operation", row["caller"], profile_id, row["original_key"])
               in snapshots[OPERATIONS] for profile_id in self.host.profiles):
            raise ApiFailure("idempotency_conflict")
        self.check_capacity(snapshots, row["caller"], row["profile"])
        if any(prior.get("version") == 2 and prior.get("caller") == row["caller"]
               and prior.get("state") not in TERMINAL for prior in snapshots[OPERATIONS].values()):
            raise ApiFailure("conflict")
        selection = self.store.get("host_profile_catalog", "selection")
        if selection != {"selected": row["selected_profile"]}:
            raise ApiFailure("resync_required")
        self.store.conditional_put_and_delete(
            {**policy, (OPERATIONS, identity): None, (ALIASES, alias_id): None,
             ("host_profile_catalog", "selection"): selection},
            [(OPERATIONS, identity, row), (ALIASES, alias_id, {"identity": identity, "caller": row["caller"]})],
            expected_collections=snapshots)

    def admit(self, identity, previous, row, *, key):
        self.check_slot(identity)
        snapshots = self.snapshots()
        policy, slot = self.policy_read_set(snapshots)
        # Validate the *same* read set that the transaction will compare. A
        # second host can change admission after the optimistic initial check.
        if not self.host._ordinary_catalog and ((slot is not None and slot["identity"] != identity) or any(
                candidate != identity and value.get("state") == "intent"
                for candidate, value in snapshots[OPERATIONS].items())):
            raise ApiFailure("unavailable")
        alias = snapshots[ALIASES].get(self.alias_id(row["caller"], key))
        if alias is not None and (alias["identity"] != identity or row.get("version") != 2):
            raise ApiFailure("idempotency_conflict")
        if previous is None:
            self.check_capacity(snapshots, row["caller"], row["profile"])
        self.store.conditional_put_and_delete(
            {**policy, (OPERATIONS, identity): previous},
            [(OPERATIONS, identity, row)] + ([] if self.host._ordinary_catalog else
                [(DISPATCH, "current", {"identity": identity})]),
            expected_collections=snapshots)

    def finish(self, identity, previous, row):
        snapshots = self.snapshots()
        policy, slot = self.policy_read_set(snapshots)
        if slot is not None and slot["identity"] != identity:
            raise ApiFailure("unavailable")
        self.store.conditional_put_and_delete(
            {**policy, (OPERATIONS, identity): previous},
            [(OPERATIONS, identity, row)],
            [(DISPATCH, "current")] if slot is not None else (), expected_collections=snapshots)


class ProfileIntents:
    # This foundation is not a platform feature/capability advertisement.
    available = False

    def __init__(self, host, *, origin=None, auth=None, binding=None, limits):
        supplied = (origin is not None, auth is not None, binding is not None)
        if any(supplied) and (not all(supplied) or not isinstance(binding, NativeOrigin)
                or not all(callable(getattr(origin, name, None)) for name in ("capture", "validate", "claim_dispatch"))
                or not callable(getattr(auth, "consume_authorization", None))):
            raise ValueError("Private intent configuration must be complete")
        self.host = host
        self._configuration = IntentConfiguration(origin, auth, binding) if all(supplied) else None
        self.ledger = OperationLedger(host, limits)

    @property
    def origin(self):
        return self._configuration.origin if self._configuration is not None else None

    @property
    def auth(self):
        return self._configuration.auth if self._configuration is not None else None

    @property
    def binding(self):
        return self._configuration.binding if self._configuration is not None else None

    def _ports(self):
        if (not isinstance(self.binding, NativeOrigin) or self.origin is None
                or not all(callable(getattr(self.origin, name, None)) for name in
                           ("capture", "validate", "claim_dispatch"))):
            raise ApiFailure("unsupported_operation")

    def _grant(self, authorize, profile_id=None):
        from .session import Grant
        grant = authorize()
        if (not isinstance(grant, Grant) or "profile_owner" not in grant.permissions
                or (profile_id is not None and profile_id not in grant.profiles)):
            raise ApiFailure("forbidden")
        return grant

    def _row(self, authorize, intent_ref):
        grant = self._grant(authorize)
        valid_ref = isinstance(intent_ref, str) and len(intent_ref) == 64 and all(c in "0123456789abcdef" for c in intent_ref)
        row = self.host.store.get(OPERATIONS, intent_ref) if valid_ref else None
        if (row is None or row.get("version") != 2 or row["caller"] != grant.caller
                or row["profile"] not in grant.profiles):
            raise ApiFailure("not_found")
        return grant, row

    def _current(self, authorize, grant, profile_id):
        current = self._grant(authorize, profile_id)
        if current.caller != grant.caller:
            raise ApiFailure("forbidden")

    def _origin(self, row):
        value = NativeOrigin(**row["origin"])
        if value != self.binding:
            raise ApiFailure("resync_required")
        return value

    def _validate(self, grant, row, attachment, phase):
        self._ports()
        self.origin.validate(attachment, caller=grant.caller, profile_id=row["profile"],
                             expected=self.binding if phase == "observe" else self._origin(row), phase=phase)

    def prepare(self, authorize, *, action, profile, original_key, attachment):
        with self.host._lock:
            self._ports()
            grant = self._grant(authorize)
            if action not in {"lock", "select", "unlock"} or not isinstance(original_key, str) or IDEMPOTENCY_KEY.fullmatch(original_key) is None:
                raise ApiFailure("invalid_request")
            target = self.host._target(grant, profile)
            origin = self.origin.capture(attachment, caller=grant.caller, profile_id=target.profile_id)
            if origin != self.binding:
                raise ApiFailure("resync_required")
            alias_id = self.ledger.alias_id(grant.caller, original_key)
            alias = self.ledger.alias(grant.caller, original_key)
            identity, receipt = self.host._operation_record(grant.caller, target, "profile." + action, original_key)
            if alias is not None:
                if alias["identity"] != identity:
                    raise ApiFailure("idempotency_conflict")
                _, row = self._row(authorize, identity)
                if row["input_digest"] != receipt["input_digest"]:
                    raise ApiFailure("idempotency_conflict")
                self._validate(grant, row, attachment, "prepare")
                self._current(authorize, grant, row["profile"])
                return self._view(identity, row)
            if self.host.store.get(OPERATIONS, identity) is not None:
                raise ApiFailure("idempotency_conflict")  # Legacy keys cannot be reconstructed.
            self.ledger.check_slot(identity)
            row = {**receipt, "version": 2, "state": "prepared", "original_key": original_key,
                   "action": action, "origin": asdict(origin), "selected_profile": self.host.lifecycle.query()["selected_profile"],
                   "ever_dispatched": False}
            self._current(authorize, grant, target.profile_id)
            self.ledger.reserve(identity, row, alias_id)
            return self._view(identity, row)

    def _view(self, identity, row):
        status = self.host.lifecycle.query()
        historical = {"complete": "applied", "withdrawn": "rejected_no_effect",
                      "rejected_no_effect": "rejected_no_effect"}.get(row["state"], "unknown")
        same_host = row["host_incarnation"] == status["host_incarnation"] and NativeOrigin(**row["origin"]) == self.binding
        eligible = same_host and row["state"] not in {"withdrawn", "rejected_no_effect"}
        unrecorded_completion = False
        if row["state"] == "intent" and same_host:
            fact = self.host.lifecycle.lookup_exact_completion(self.host._lifecycle_request(row))
            if fact.status == "applied":
                historical, unrecorded_completion = "applied", True
                eligible = (fact.result_revision, fact.result_service_incarnation) == (status["revision"], status["service_incarnation"])
            else:
                eligible = status["revision"] == row["expected_revision"]
        if row["state"] == "prepared":
            eligible = eligible and (row["expected_revision"], row["selected_profile"]) == (status["revision"], status["selected_profile"])
            eligible = eligible and (row["action"] == "select" or row["profile"] == status["selected_profile"])
        if row["state"] == "complete":
            eligible = eligible and (row["revision"], row["service_incarnation"]) == (status["revision"], status["service_incarnation"])
        return {"intent_ref": identity, "action": row["action"],
                "profile": self.host._profile_handle(row["caller"], row["profile"]),
                "dispatch": "may_have_dispatched" if row["ever_dispatched"] else "not_dispatched",
                "historical_outcome": historical, "replay_eligible": bool(eligible),
                "reason": "completion_unrecorded" if unrecorded_completion else None if eligible else "resync_required" if not same_host else "not_replayable",
                "acknowledged": row.get("acknowledged", False)}

    def observe(self, authorize, *, intent_ref, attachment):
        with self.host._lock:
            grant, row = self._row(authorize, intent_ref)
            self._validate(grant, row, attachment, "observe")
            self._current(authorize, grant, row["profile"])
            return self._view(intent_ref, row)

    def list(self, authorize, *, attachment, after=None, limit=32):
        with self.host._lock:
            self._ports()
            grant = self._grant(authorize)
            if type(limit) is not int or not 1 <= limit <= 64 or (after is not None and (
                    not isinstance(after, str) or len(after) != 64 or any(c not in "0123456789abcdef" for c in after))):
                raise ApiFailure("invalid_request")
            rows = sorted(self.host.store.items(OPERATIONS, limit=self.ledger.limits()[0] + 1))
            result = []
            for identity, row in rows:
                if (row.get("version") != 2 or row["caller"] != grant.caller or row["profile"] not in grant.profiles
                        or (after is not None and identity <= after)):
                    continue
                self._validate(grant, row, attachment, "observe")
                self._current(authorize, grant, row["profile"])
                result.append(self._view(identity, row))
                if len(result) == limit + 1:
                    break
            return {"intents": result[:limit], "next": result[limit - 1]["intent_ref"] if len(result) > limit else None}

    def withdraw(self, authorize, *, intent_ref, attachment):
        with self.host._lock:
            grant, row = self._row(authorize, intent_ref)
            self._validate(grant, row, attachment, "observe")
            self._current(authorize, grant, row["profile"])
            if row["state"] != "prepared" or row["ever_dispatched"]:
                raise ApiFailure("conflict")
            self.ledger.check_slot(intent_ref)
            updated = {**row, "state": "withdrawn"}
            self.ledger.finish(intent_ref, row, updated)
            return self._view(intent_ref, updated)

    def acknowledge(self, authorize, *, intent_ref, attachment):
        with self.host._lock:
            grant, row = self._row(authorize, intent_ref)
            self._validate(grant, row, attachment, "observe")
            self._current(authorize, grant, row["profile"])
            if row["state"] not in TERMINAL:
                raise ApiFailure("conflict")
            updated = {**row, "acknowledged": True}
            snapshots = self.ledger.snapshots()
            policy, _ = self.ledger.policy_read_set(snapshots)
            self.host.store.conditional_put_and_delete({**policy, (OPERATIONS, intent_ref): row},
                [(OPERATIONS, intent_ref, updated)], expected_collections=snapshots)
            return self._view(intent_ref, updated)

    def resume(self, authorize, *, intent_ref, attachment, credential_handle=None):
        with self.host._lock:
            grant, row = self._row(authorize, intent_ref)
            self._validate(grant, row, attachment, "observe")
            self.host.mutate(authorize, grant, "profile." + row["action"],
                             {"profile": self.host._profile_handle(grant.caller, row["profile"]),
                              "credential_handle": credential_handle}, row["original_key"], attachment=attachment)
            return self.observe(authorize, intent_ref=intent_ref, attachment=attachment)
