"""Hidden producer evidence with real sealed storage; native ports are doubles."""
from dataclasses import replace

import pytest

from mesh_chat.core_api import runtime_host
from mesh_chat.core_api.errors import ApiFailure
from mesh_chat.core_api.profile_intents import NativeOrigin, OPERATIONS, ALIASES, DISPATCH, POLICY, PROTECTED
from mesh_chat.errors import NativeUnavailable
from mesh_chat.vault import RecordConflict
from test_core_runtime_host import runtime


class OriginDouble:
    def __init__(self, binding):
        self.binding, self.ready, self.reject_claim = binding, set(), False

    def capture(self, attachment, *, caller, profile_id):
        self.validate(attachment, caller=caller, profile_id=profile_id, expected=self.binding, phase="prepare")
        return self.binding

    def validate(self, attachment, *, caller, profile_id, expected, phase):
        if attachment not in self.ready or expected != self.binding:
            raise ApiFailure("forbidden")

    def claim_dispatch(self, attachment, *, caller, profile_id, expected, request):
        self.validate(attachment, caller=caller, profile_id=profile_id, expected=expected, phase="claim")
        if self.reject_claim:
            raise ApiFailure("forbidden")
        return object()


class AuthDouble:
    def __init__(self):
        self.proofs = {}

    def consume_authorization(self, proof, **binding):
        expected = self.proofs.pop(proof, None)
        return expected == binding


@pytest.fixture
def producer(runtime):
    base = runtime
    binding = NativeOrigin("provider-install", "sealed-catalog", "native-generation")
    origin, auth, attachment = OriginDouble(binding), AuthDouble(), object()
    origin.ready.add(attachment)
    host = base["build"](base["first"], intent_origin=origin, intent_auth=auth, intent_binding=binding)
    stream = host.bind(lambda: base["grants"][0])
    def invoke(operation, params=None, key=None):
        return base["invoke"](operation, params, key, endpoint=stream)
    assert invoke("runtime.capabilities")["ok"]
    r = {**base, "host": host, "stream": stream, "invoke": invoke}
    intents = host.profile_intents
    authorize = lambda: r["grants"][0]

    def prepare(action="lock", key="private-original-key-0001", profile="alpha", document=None):
        return intents.prepare(authorize, action=action, profile=r["profiles"][profile], original_key=key,
                               attachment=attachment if document is None else document)

    def issue(ref, document=None):
        document = attachment if document is None else document
        row = host.store.get(OPERATIONS, ref)
        proof = object()
        auth.proofs[proof] = {"caller": authorize().caller, "profile_id": row["profile"], "intent_ref": ref,
            "origin": binding, "attachment": document, "core_host_incarnation": row["host_incarnation"],
            "expected_revision": row["expected_revision"]}
        return host.issue_bound_unlock_credential(authorize, intent_ref=ref, attachment=document, proof=proof)

    try:
        yield {**r, "intents": intents, "origin": origin, "auth": auth, "attachment": attachment,
               "binding": binding, "authorize": authorize, "prepare": prepare, "issue": issue}
    finally:
        stream.close()


def resume(r, ticket, **kwargs):
    return r["intents"].resume(r["authorize"], intent_ref=ticket["intent_ref"],
                               attachment=r["attachment"], **kwargs)


def test_missing_trusted_ports_and_public_capability_remain_unavailable(runtime):
    r = runtime
    assert not r["host"].profile_intents.available
    with pytest.raises(ApiFailure, match="unsupported_operation"):
        r["host"].profile_intents.prepare(lambda: r["grants"][0], action="lock", profile=r["profiles"]["alpha"],
            original_key="private-original-key-0001", attachment=object())
    assert not any("intent" in operation for operation in r["caps"]["result"]["operations"])


def test_prepare_and_observe_are_pure_and_safe_on_sealed_catalog(producer, monkeypatch):
    r = producer
    def forbidden(*_args, **_kwargs):
        pytest.fail("observation performed lifecycle/auth effects")
    monkeypatch.setattr(r["host"].lifecycle, "mutate", forbidden)
    monkeypatch.setattr(r["host"].lifecycle, "reconcile", forbidden)
    monkeypatch.setattr(r["auth"], "consume_authorization", forbidden)
    before = len(r["loads"]), len(r["published"])
    ticket = r["prepare"]()
    assert r["intents"].observe(r["authorize"], intent_ref=ticket["intent_ref"], attachment=r["attachment"]) == ticket
    assert r["intents"].list(r["authorize"], attachment=r["attachment"])["intents"] == [ticket]
    assert (len(r["loads"]), len(r["published"])) == before
    assert set(ticket) == {"intent_ref", "action", "profile", "dispatch", "historical_outcome",
                           "replay_eligible", "reason", "acknowledged"}
    for path in r["meta_root"].glob("mesh-chat.vault*"):
        assert b"private-original-key-0001" not in path.read_bytes()


@pytest.mark.parametrize("key", ["a" * 15, "a" * 129, "not allowed key with spaces", "é" * 16, True])
def test_prepare_uses_existing_key_bounds(producer, key):
    with pytest.raises(ApiFailure, match="invalid_request"):
        producer["prepare"](key=key)
    assert producer["meta"].list(OPERATIONS) == []


def test_one_alias_identity_and_durable_withdrawal_tombstone(producer):
    r = producer
    ticket = r["prepare"]()
    assert r["prepare"]() == ticket
    for changed in ({"profile": "beta"}, {"action": "unlock"}):
        with pytest.raises(ApiFailure, match="idempotency_conflict"):
            r["prepare"](**changed)
    assert len(r["meta"].list(OPERATIONS)) == len(r["meta"].list(ALIASES)) == 1
    withdrawn = r["intents"].withdraw(r["authorize"], intent_ref=ticket["intent_ref"], attachment=r["attachment"])
    assert withdrawn["historical_outcome"] == "rejected_no_effect"
    with pytest.raises(ApiFailure, match="conflict"):
        resume(r, ticket)
    assert r["intents"].acknowledge(r["authorize"], intent_ref=ticket["intent_ref"], attachment=r["attachment"])["acknowledged"]
    assert len(r["meta"].list(OPERATIONS)) == len(r["meta"].list(ALIASES)) == 1
    assert r["invoke"]("profile.lock", {"profile": r["profiles"]["alpha"]}, "private-original-key-0001")["error"]["code"] == "forbidden"


def test_generic_route_cannot_dispatch_prepared_key_or_change_target(producer):
    r = producer
    ticket = r["prepare"]()
    assert r["invoke"]("profile.lock", {"profile": r["profiles"]["alpha"]}, "private-original-key-0001")["error"]["code"] == "forbidden"
    assert r["invoke"]("profile.lock", {"profile": r["profiles"]["beta"]}, "private-original-key-0001")["error"]["code"] == "idempotency_conflict"
    assert r["meta"].get(OPERATIONS, ticket["intent_ref"])["state"] == "prepared"
    assert not r["first"]._store_closed


def test_trusted_generic_reserved_route_preserves_catalog_response_contract(producer):
    import json
    from jsonschema import Draft202012Validator
    from test_core_runtime_host import ROOT
    r = producer
    ticket = r["prepare"]()
    result = r["host"].mutate(r["authorize"], r["authorize"](), "profile.lock",
        {"profile": r["profiles"]["alpha"]}, "private-original-key-0001", attachment=r["attachment"])
    response = {"api_version": 1, "request_id": "private:generic", "ok": True, "result": result}
    Draft202012Validator(json.loads((ROOT / "contracts/core-api/profile-catalog-result-v1.schema.json").read_text())).validate(response)
    assert r["intents"].observe(r["authorize"], intent_ref=ticket["intent_ref"], attachment=r["attachment"])["historical_outcome"] == "applied"


def test_intervening_revision_never_rebases_prepared_intent(producer):
    r = producer
    ticket = r["prepare"]()
    assert r["invoke"]("profile.lock", {"profile": r["profiles"]["alpha"]}, "intervening-lock-key-0001")["ok"]
    original = r["meta"].get(OPERATIONS, ticket["intent_ref"])
    with pytest.raises(ApiFailure, match="resync_required"):
        resume(r, ticket)
    assert r["meta"].get(OPERATIONS, ticket["intent_ref"]) == original


@pytest.mark.parametrize("target", ["alpha", "beta"])
def test_prepare_never_adopts_any_existing_generic_key(producer, target):
    r = producer
    key = "already-generic-key-0001"
    assert r["invoke"]("profile.lock", {"profile": r["profiles"]["alpha"]}, key)["ok"]
    with pytest.raises(ApiFailure, match="idempotency_conflict"):
        r["prepare"](key=key, profile=target)
    assert not r["meta"].list(ALIASES)


def test_reserved_tombstones_share_existing_quota(producer, monkeypatch):
    r = producer
    monkeypatch.setattr(runtime_host, "MAX_CALLER_OPERATIONS", 1)
    ticket = r["prepare"]()
    r["intents"].withdraw(r["authorize"], intent_ref=ticket["intent_ref"], attachment=r["attachment"])
    with pytest.raises(ApiFailure, match="resource_exhausted"):
        r["prepare"](key="second-private-key-0001")
    assert r["invoke"]("profile.lock", {"profile": r["profiles"]["alpha"]}, "ordinary-after-quota-key")["error"]["code"] == "resource_exhausted"
    assert len(r["meta"].list(OPERATIONS)) == len(r["meta"].list(ALIASES)) == 1


def test_host_quota_cannot_be_bypassed_by_another_caller_or_profile(producer, monkeypatch):
    r = producer
    monkeypatch.setattr(runtime_host, "MAX_HOST_OPERATIONS", 1)
    ticket = r["prepare"]()
    r["intents"].withdraw(r["authorize"], intent_ref=ticket["intent_ref"], attachment=r["attachment"])
    r["grants"][0] = replace(r["grants"][0], caller="another-caller")
    profile = r["host"]._profile_handle("another-caller", "beta")
    with pytest.raises(ApiFailure, match="resource_exhausted"):
        r["intents"].prepare(r["authorize"], action="select", profile=profile, original_key="different-caller-new-key",
                             attachment=r["attachment"])
    assert len(r["meta"].list(OPERATIONS)) == len(r["meta"].list(ALIASES)) == 1


def test_reservation_collection_cas_prevents_phantom_admission(producer, monkeypatch):
    r = producer
    original = r["meta"].conditional_put_and_delete
    def race(expected, records, *args, **kwargs):
        r["meta"].put(OPERATIONS, "competing-row", {"caller": "other", "profile": "alpha", "state": "complete"})
        return original(expected, records, *args, **kwargs)
    monkeypatch.setattr(r["meta"], "conditional_put_and_delete", race)
    with pytest.raises(RecordConflict):
        r["prepare"]()
    assert not r["meta"].list(ALIASES)


def test_generic_admission_rechecks_alias_in_transaction_snapshot(producer, monkeypatch):
    r = producer
    ticket = r["prepare"]()
    # Models an optimistic alias read racing a completed private reservation.
    monkeypatch.setattr(r["intents"].ledger, "alias", lambda *_: None)
    assert r["invoke"]("profile.select", {"profile": r["profiles"]["beta"]}, "private-original-key-0001")["error"]["code"] == "idempotency_conflict"
    assert len(r["meta"].list(OPERATIONS)) == 1
    assert r["meta"].get(OPERATIONS, ticket["intent_ref"])["state"] == "prepared"
    assert r["invoke"]("profile.lock", {"profile": r["profiles"]["alpha"]}, "private-original-key-0001")["error"]["code"] == "unavailable"
    assert not r["first"]._store_closed


def test_generic_admission_cannot_overwrite_slot_changed_after_initial_check(producer, monkeypatch):
    r = producer
    ledger = r["intents"].ledger
    original = ledger.snapshots
    identity, row = r["host"]._operation_record(r["authorize"]().caller, r["host"].profiles["alpha"],
                                                "profile.lock", "racing-admitted-other-key")
    def raced_snapshot():
        r["meta"].put_many([(OPERATIONS, identity, row), (DISPATCH, "current", {"identity": identity})])
        return original()
    monkeypatch.setattr(ledger, "snapshots", raced_snapshot)
    assert r["invoke"]("profile.lock", {"profile": r["profiles"]["alpha"]}, "must-not-overwrite-slot-key")["error"]["code"] == "unavailable"
    assert ledger.slot() == {"identity": identity}
    assert not r["first"]._store_closed


def test_lost_reservation_return_reuses_original_identity(producer, monkeypatch):
    r = producer
    original = r["meta"].conditional_put_and_delete
    def lost(expected, records, *args, **kwargs):
        original(expected, records, *args, **kwargs)
        raise OSError("lost reserve return")
    monkeypatch.setattr(r["meta"], "conditional_put_and_delete", lost)
    with pytest.raises(OSError):
        r["prepare"]()
    monkeypatch.setattr(r["meta"], "conditional_put_and_delete", original)
    ticket = r["prepare"]()
    assert len(r["meta"].list(OPERATIONS)) == 1
    assert ticket["dispatch"] == "not_dispatched"


def fail_write(r, monkeypatch, state, *, after=False):
    original = r["meta"].conditional_put_and_delete
    def failure(expected, records, *args, **kwargs):
        records = list(records)
        if records and records[0][2].get("state") == state:
            if after:
                original(expected, records, *args, **kwargs)
            raise OSError("synthetic lost metadata return")
        return original(expected, records, *args, **kwargs)
    monkeypatch.setattr(r["meta"], "conditional_put_and_delete", failure)
    return original


def test_ambiguous_admission_keeps_fence_without_lifecycle_effect(producer, monkeypatch):
    r = producer
    ticket = r["prepare"]()
    original = fail_write(r, monkeypatch, "intent", after=True)
    with pytest.raises(OSError):
        resume(r, ticket)
    monkeypatch.setattr(r["meta"], "conditional_put_and_delete", original)
    assert not r["first"]._store_closed
    assert r["invoke"]("profile.lock", {"profile": r["profiles"]["alpha"]}, "cannot-overtake-key-0001")["error"]["code"] == "unavailable"
    before = r["meta"].get(OPERATIONS, ticket["intent_ref"])
    assert r["intents"].observe(r["authorize"], intent_ref=ticket["intent_ref"], attachment=r["attachment"])["historical_outcome"] == "unknown"
    assert r["meta"].get(OPERATIONS, ticket["intent_ref"]) == before
    assert resume(r, ticket)["historical_outcome"] == "applied"


def test_completion_write_failure_blocks_every_caller_and_retry_records_exact_fact(producer, monkeypatch):
    r = producer
    ticket = r["prepare"]()
    original = fail_write(r, monkeypatch, "complete")
    with pytest.raises(OSError):
        resume(r, ticket)
    assert r["first"]._store_closed
    status = r["host"].lifecycle.query()
    r["grants"][0] = replace(r["grants"][0], caller="different-caller")
    params = {"profile": r["host"]._profile_handle("different-caller", "alpha")}
    with pytest.raises(ApiFailure, match="unavailable"):
        r["host"].mutate(r["authorize"], r["grants"][0], "profile.lock", params, "different-caller-key-001")
    r["grants"][0] = replace(r["grants"][0], caller="application-owner")
    assert r["host"].lifecycle.query() == status
    with pytest.raises(ApiFailure, match="conflict"):
        r["intents"].withdraw(r["authorize"], intent_ref=ticket["intent_ref"], attachment=r["attachment"])
    monkeypatch.setattr(r["meta"], "conditional_put_and_delete", original)
    monkeypatch.setattr(r["host"].lifecycle, "mutate", lambda *_a, **_k: pytest.fail("exact completion replay invoked lifecycle"))
    assert resume(r, ticket)["historical_outcome"] == "applied"
    assert r["intents"].ledger.slot() is None


def test_first_claim_rejection_is_no_effect_but_later_rejection_preserves_unknown(producer, monkeypatch):
    r = producer
    ticket = r["prepare"]()
    r["origin"].reject_claim = True
    with pytest.raises(ApiFailure, match="forbidden"):
        resume(r, ticket)
    assert r["meta"].get(OPERATIONS, ticket["intent_ref"])["state"] == "rejected_no_effect"
    assert r["intents"].ledger.slot() is None
    r["origin"].reject_claim = False
    second = r["prepare"](key="second-uncertain-key-0001")
    def uncertain(*_a, **_k):
        raise NativeUnavailable("synthetic uncertain effect")
    monkeypatch.setattr(r["host"].lifecycle, "mutate", uncertain)
    with pytest.raises(NativeUnavailable):
        resume(r, second)
    r["origin"].reject_claim = True
    with pytest.raises(ApiFailure, match="forbidden"):
        resume(r, second)
    row = r["meta"].get(OPERATIONS, second["intent_ref"])
    assert row["state"] == "intent" and row["ever_dispatched"]
    assert r["intents"].ledger.slot()["identity"] == second["intent_ref"]


@pytest.mark.parametrize("earlier_uncertain", [False, True])
def test_post_claim_grant_denial_distinguishes_first_from_earlier_attempt(producer, monkeypatch, earlier_uncertain):
    r = producer
    ticket = r["prepare"]()
    lifecycle = r["host"].lifecycle
    original_mutate = lifecycle.mutate
    if earlier_uncertain:
        def uncertain(*_args, **_kwargs):
            raise NativeUnavailable("prior invocation outcome cannot be inferred")
        monkeypatch.setattr(lifecycle, "mutate", uncertain)
        with pytest.raises(NativeUnavailable):
            resume(r, ticket)
        monkeypatch.setattr(lifecycle, "mutate", original_mutate)
    original_claim = r["origin"].claim_dispatch
    original_grant = r["grants"][0]
    def revoke_after_claim(*args, **kwargs):
        admission = original_claim(*args, **kwargs)
        r["grants"][0] = replace(original_grant, permissions=frozenset())
        return admission
    monkeypatch.setattr(r["origin"], "claim_dispatch", revoke_after_claim)
    with pytest.raises(ApiFailure, match="forbidden"):
        resume(r, ticket)
    assert not r["first"]._store_closed
    row = r["meta"].get(OPERATIONS, ticket["intent_ref"])
    assert row["state"] == ("intent" if earlier_uncertain else "rejected_no_effect")
    assert (r["intents"].ledger.slot() is not None) == earlier_uncertain
    r["grants"][0] = original_grant
    monkeypatch.setattr(r["origin"], "claim_dispatch", original_claim)
    response = r["invoke"]("profile.lock", {"profile": r["profiles"]["alpha"]}, "another-post-denial-key")
    if earlier_uncertain:
        assert response["error"]["code"] == "unavailable"
        assert resume(r, ticket)["historical_outcome"] == "applied"
    else:
        assert response["ok"]


def test_wrong_target_prepared_action_cannot_acquire_dispatch_custody(producer):
    r = producer
    ticket = r["prepare"](profile="beta")
    assert not ticket["replay_eligible"]
    with pytest.raises(ApiFailure, match="invalid_request"):
        resume(r, ticket)
    assert r["meta"].get(OPERATIONS, ticket["intent_ref"])["state"] == "prepared"
    assert r["intents"].ledger.slot() is None
    r["intents"].withdraw(r["authorize"], intent_ref=ticket["intent_ref"], attachment=r["attachment"])
    assert r["invoke"]("profile.lock", {"profile": r["profiles"]["alpha"]}, "valid-after-bad-target-key")["ok"]


def test_bound_unlock_credential_is_intent_document_and_single_use_bound(producer):
    r = producer
    assert r["invoke"]("profile.lock", {"profile": r["profiles"]["alpha"]}, "initial-lock-for-auth-0001")["ok"]
    ticket = r["prepare"](action="unlock")
    token = r["issue"](ticket["intent_ref"])
    assert r["invoke"]("profile.unlock", {"profile": r["profiles"]["alpha"], "credential_handle": token},
                       "unreserved-cannot-steal-token")["error"]["code"] == "forbidden"
    other = object()
    r["origin"].ready.add(other)
    with pytest.raises(ApiFailure, match="forbidden"):
        r["intents"].resume(r["authorize"], intent_ref=ticket["intent_ref"], attachment=other, credential_handle=token)
    legacy = r["host"].issue_unlock_credential(r["authorize"]().caller, "alpha")
    with pytest.raises(ApiFailure, match="forbidden"):
        resume(r, ticket, credential_handle=legacy)
    before = len(r["loads"])
    assert resume(r, ticket, credential_handle=token)["historical_outcome"] == "applied"
    assert len(r["loads"]) == before + 1
    assert resume(r, ticket)["historical_outcome"] == "applied"
    assert len(r["loads"]) == before + 1


def test_revoked_attachment_cleanup_is_denial_only_and_cannot_touch_other_token(producer):
    r = producer
    assert r["invoke"]("profile.lock", {"profile": r["profiles"]["alpha"]}, "initial-lock-for-auth-0001")["ok"]
    ticket = r["prepare"](action="unlock")
    old = r["issue"](ticket["intent_ref"])
    current = object()
    r["origin"].ready.add(current)
    fresh = r["issue"](ticket["intent_ref"], current)
    with pytest.raises(ApiFailure, match="forbidden"):
        r["host"].revoke_attachment_credentials(origin=NativeOrigin("wrong", "sealed-catalog", "native-generation"),
                                               attachment=r["attachment"], cleanup_epoch=6)
    assert old in r["host"]._credentials and fresh in r["host"]._credentials
    r["origin"].ready.remove(r["attachment"])
    r["grants"][0] = replace(r["grants"][0], permissions=frozenset())
    ack = r["host"].revoke_attachment_credentials(origin=r["binding"], attachment=r["attachment"], cleanup_epoch=7)
    assert ack.cleanup_epoch == 7 and ack.attachment is r["attachment"]
    assert old not in r["host"]._credentials and fresh in r["host"]._credentials
    assert current in r["origin"].ready and r["attachment"] not in r["origin"].ready
    with pytest.raises(ApiFailure, match="forbidden"):
        r["host"].revoke_bound_unlock_credential(token=fresh, intent_ref=ticket["intent_ref"], origin=r["binding"], attachment=r["attachment"])
    assert fresh in r["host"]._credentials


def test_expired_or_orphan_revoked_token_cannot_admit_unlock(producer):
    r = producer
    assert r["invoke"]("profile.lock", {"profile": r["profiles"]["alpha"]}, "initial-lock-for-auth-0001")["ok"]
    ticket = r["prepare"](action="unlock")
    expired = r["issue"](ticket["intent_ref"])
    r["clock"][0] += 61
    with pytest.raises(ApiFailure, match="forbidden"):
        resume(r, ticket, credential_handle=expired)
    token = r["issue"](ticket["intent_ref"])
    r["host"].revoke_bound_unlock_credential(token=token, intent_ref=ticket["intent_ref"],
                                          origin=r["binding"], attachment=r["attachment"])
    with pytest.raises(ApiFailure, match="forbidden"):
        resume(r, ticket, credential_handle=token)
    assert r["meta"].get(OPERATIONS, ticket["intent_ref"])["state"] == "prepared"
    assert r["intents"].ledger.slot() is None


def test_observe_scope_and_historical_host_replacement_never_rebase(producer):
    r = producer
    ticket = r["prepare"]()
    r["grants"][0] = replace(r["grants"][0], caller="another-caller")
    with pytest.raises(ApiFailure, match="not_found"):
        r["intents"].observe(r["authorize"], intent_ref=ticket["intent_ref"], attachment=r["attachment"])
    r["grants"][0] = replace(r["grants"][0], caller="application-owner")
    replacement = r["build"](r["first"], intent_origin=r["origin"], intent_auth=r["auth"], intent_binding=r["binding"])
    observed = replacement.profile_intents.observe(r["authorize"], intent_ref=ticket["intent_ref"], attachment=r["attachment"])
    assert observed["historical_outcome"] == "unknown" and not observed["replay_eligible"]
    with pytest.raises(ApiFailure, match="resync_required"):
        replacement.profile_intents.resume(r["authorize"], intent_ref=ticket["intent_ref"], attachment=r["attachment"])


def test_grant_change_inside_capture_cannot_persist_reservation(producer, monkeypatch):
    r = producer
    original = r["origin"].capture
    def changed(*args, **kwargs):
        binding = original(*args, **kwargs)
        r["grants"][0] = replace(r["grants"][0], caller="changed-caller")
        return binding
    monkeypatch.setattr(r["origin"], "capture", changed)
    with pytest.raises(ApiFailure, match="forbidden"):
        r["prepare"]()
    assert not r["meta"].list(OPERATIONS) and not r["meta"].list(ALIASES)


def test_pre_dispatch_write_rejection_keeps_prepared_withdrawable(producer, monkeypatch):
    r = producer
    ticket = r["prepare"]()
    original = fail_write(r, monkeypatch, "intent")
    with pytest.raises(OSError):
        resume(r, ticket)
    monkeypatch.setattr(r["meta"], "conditional_put_and_delete", original)
    assert r["intents"].ledger.slot() is None
    assert r["intents"].withdraw(r["authorize"], intent_ref=ticket["intent_ref"], attachment=r["attachment"])["dispatch"] == "not_dispatched"


def test_single_unresolved_private_reservation_per_caller(producer):
    r = producer
    r["prepare"]()
    with pytest.raises(ApiFailure, match="conflict"):
        r["prepare"](key="second-private-key-0001", profile="beta")
    assert len(r["meta"].list(OPERATIONS)) == len(r["meta"].list(ALIASES)) == 1


def test_list_is_bounded_and_terminal_tombstones_survive_catalog_reopen(producer):
    r = producer
    for number in range(3):
        ticket = r["prepare"](key=f"private-page-key-{number:04}")
        r["intents"].withdraw(r["authorize"], intent_ref=ticket["intent_ref"], attachment=r["attachment"])
    first = r["intents"].list(r["authorize"], attachment=r["attachment"], limit=2)
    second = r["intents"].list(r["authorize"], attachment=r["attachment"], after=first["next"], limit=2)
    assert len(first["intents"]) == 2 and len(second["intents"]) == 1 and second["next"] is None
    r["meta"].close()
    from mesh_chat.vault import VaultStore
    reopened = VaultStore(r["meta_root"], r["meta_key"], allow_unprotected_for_tests=True)
    replacement = r["build"](r["first"], catalog=reopened, intent_origin=r["origin"], intent_auth=r["auth"], intent_binding=r["binding"])
    try:
        rows = replacement.profile_intents.list(r["authorize"], attachment=r["attachment"])["intents"]
        assert len(rows) == 3 and all(item["historical_outcome"] == "rejected_no_effect" for item in rows)
        with pytest.raises(ApiFailure, match="conflict"):
            replacement.profile_intents.resume(r["authorize"], intent_ref=rows[0]["intent_ref"], attachment=r["attachment"])
    finally:
        reopened.close()


def test_native_origin_replacement_can_observe_but_never_admit_old_key(producer):
    r = producer
    ticket = r["prepare"]()
    previous = r["meta"].get(OPERATIONS, ticket["intent_ref"])
    changed = NativeOrigin("provider-install", "sealed-catalog", "replacement-generation")
    r["origin"].binding = changed
    replacement = r["build"](r["first"], intent_origin=r["origin"], intent_auth=r["auth"], intent_binding=changed)
    observed = replacement.profile_intents.observe(r["authorize"], intent_ref=ticket["intent_ref"], attachment=r["attachment"])
    assert not observed["replay_eligible"] and observed["reason"] == "resync_required"
    with pytest.raises(ApiFailure, match="resync_required"):
        replacement.profile_intents.resume(r["authorize"], intent_ref=ticket["intent_ref"], attachment=r["attachment"])
    assert r["meta"].get(OPERATIONS, ticket["intent_ref"]) == previous
    assert r["intents"].ledger.slot() is None


def test_configuration_is_constructor_bound_and_marker_precedes_generic_work(producer):
    r = producer
    assert r["meta"].get(POLICY, "current") == PROTECTED
    assert not r["meta"].list(OPERATIONS) and not r["meta"].list(ALIASES)
    with pytest.raises(AttributeError):
        r["host"].profile_intents = None
    with pytest.raises(AttributeError):
        r["intents"].binding = None
    assert not r["intents"].available


def test_partial_configuration_cannot_fall_back_to_ordinary(runtime):
    with pytest.raises(ValueError, match="complete"):
        runtime["build"](runtime["first"], intent_binding=NativeOrigin("p", "c", "n"))
    assert runtime["meta"].get(POLICY, "current") is None


@pytest.mark.parametrize("loss", ["admission", "completion"])
def test_configured_generic_first_custody_survives_missing_ports(producer, monkeypatch, loss):
    r = producer
    original = fail_write(r, monkeypatch, "intent" if loss == "admission" else "complete", after=loss == "admission")
    assert r["invoke"]("profile.lock", {"profile": r["profiles"]["alpha"]}, "generic-before-private-key")["error"]["code"] == "unavailable"
    monkeypatch.setattr(r["meta"], "conditional_put_and_delete", original)
    assert not r["meta"].list(ALIASES)
    before = r["meta"].list(OPERATIONS)
    assert all(row.get("version") != 2 for row in before)
    replacement = r["build"](None)
    with pytest.raises(ApiFailure, match="unavailable"):
        replacement.mutate(r["authorize"], r["authorize"](), "profile.lock", {"profile": r["profiles"]["alpha"]}, "new-uuid-no-ports-key")
    assert r["meta"].get(POLICY, "current") == PROTECTED
    assert r["meta"].list(OPERATIONS) == before


def test_completed_generic_history_keeps_successor_protected(producer, monkeypatch):
    r = producer
    assert r["invoke"]("profile.lock", {"profile": r["profiles"]["alpha"]}, "protected-complete-first-key")["ok"]
    assert r["intents"].ledger.slot() is None and not r["meta"].list(ALIASES)
    replacement = r["build"](None)
    assert not replacement._ordinary_catalog
    original = fail_write(r, monkeypatch, "complete")
    with pytest.raises(OSError):
        replacement.mutate(r["authorize"], r["authorize"](), "profile.lock", {"profile": r["profiles"]["alpha"]}, "successor-unknown-action")
    monkeypatch.setattr(r["meta"], "conditional_put_and_delete", original)
    successor = r["build"](None)
    with pytest.raises(ApiFailure, match="unavailable"):
        successor.mutate(r["authorize"], r["authorize"](), "profile.lock", {"profile": r["profiles"]["alpha"]}, "next-successor-action-key")


def test_ambiguous_pre_marker_slot_is_not_reinterpreted_or_deleted(runtime):
    r = runtime
    identity, row = r["host"]._operation_record(r["grants"][0].caller, r["host"].profiles["alpha"],
                                               "profile.lock", "old-experimental-slot-key")
    r["meta"].put_many([(OPERATIONS, identity, row), (DISPATCH, "current", {"identity": identity})])
    assert r["meta"].get(POLICY, "current") is None
    replacement = r["build"](None)
    with pytest.raises(ApiFailure, match="unavailable"):
        replacement.mutate(lambda: r["grants"][0], r["grants"][0], "profile.lock", {"profile": r["profiles"]["alpha"]}, "not-a-migration-waiver-key")
    assert r["meta"].get(OPERATIONS, identity) == row
    assert r["meta"].get(DISPATCH, "current") == {"identity": identity}
    assert r["meta"].get(POLICY, "current") == PROTECTED


@pytest.mark.parametrize("after", [False, True])
def test_lost_marker_commit_never_exposes_configured_host_or_resets_policy(runtime, monkeypatch, after):
    r = runtime
    original = r["meta"].conditional_put_and_delete
    def failure(expected, records, *args, **kwargs):
        records = list(records)
        if any(kind == POLICY for kind, _, _ in records):
            if after:
                original(expected, records, *args, **kwargs)
            raise OSError("marker write return unavailable")
        return original(expected, records, *args, **kwargs)
    monkeypatch.setattr(r["meta"], "conditional_put_and_delete", failure)
    native = OriginDouble(NativeOrigin("p", "c", "n"))
    with pytest.raises(OSError):
        r["build"](r["first"], intent_origin=native, intent_auth=AuthDouble(), intent_binding=native.binding)
    monkeypatch.setattr(r["meta"], "conditional_put_and_delete", original)
    assert r["meta"].get(POLICY, "current") == (PROTECTED if after else None)
    response = r["invoke"]("profile.lock", {"profile": r["profiles"]["alpha"]}, "ordinary-after-marker-loss")
    if after:
        assert response.get("error", {}).get("code") == "unavailable"
    else:
        assert response["ok"]


@pytest.mark.parametrize("after", [False, True])
def test_ordinary_admission_racing_first_marker_cannot_open_or_downgrade(runtime, monkeypatch, after):
    r = runtime
    original = r["meta"].conditional_put_and_delete
    injected = []
    def race(expected, records, *args, **kwargs):
        records = list(records)
        if not injected and records and records[0][2].get("state") == "intent":
            injected.append(True)
            if after:
                original(expected, records, *args, **kwargs)
            r["meta"].put(POLICY, "current", dict(PROTECTED))
            if after:
                return
        return original(expected, records, *args, **kwargs)
    monkeypatch.setattr(r["meta"], "conditional_put_and_delete", race)
    response = r["invoke"]("profile.lock", {"profile": r["profiles"]["alpha"]}, "ordinary-race-arming-key")
    assert not response["ok"] and not r["first"]._store_closed
    assert r["meta"].get(POLICY, "current") == PROTECTED
    assert len(r["meta"].list(OPERATIONS)) == int(after)


@pytest.mark.parametrize("private_shape", ["alias", "row"])
def test_orphan_private_evidence_without_marker_cannot_downgrade(runtime, private_shape):
    r = runtime
    if private_shape == "alias":
        r["meta"].put(ALIASES, "orphan-private-index", {"identity": "missing", "caller": "application-owner"})
    else:
        r["meta"].put(OPERATIONS, "orphan-private-row", {"version": 2, "caller": "application-owner", "original_key": "orphan-private-key-0001", "state": "prepared"})
    replacement = r["build"](None)
    with pytest.raises(ApiFailure, match="unavailable"):
        replacement.mutate(lambda: r["grants"][0], r["grants"][0], "profile.lock", {"profile": r["profiles"]["alpha"]}, "cannot-ignore-private-evidence")
    assert r["meta"].get(POLICY, "current") == PROTECTED
