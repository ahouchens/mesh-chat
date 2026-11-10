"""Independent Core/catalog regressions; native authority is a component boundary.

No OS proof, native attachment wiring, renderer recovery or platform capability
is established here. Effects run through the actual lifecycle and sealed vault.
"""
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from mesh_chat.core_api.errors import ApiFailure
from mesh_chat.core_api.profile_intents import NativeOrigin
from mesh_chat.core_api.runtime_host import CoreRuntimeHost
from mesh_chat.core_api.wire_codec import decode_frame, encode_frame
from mesh_chat.errors import NativeUnavailable, StorageUnavailable
from mesh_chat.vault import VaultStore
from test_core_runtime_host import runtime
from test_mobile_profile_host import platform_host
from test_pairing_runtime import native_pairing


class NativeBoundary:
    """Test authority with separate document revocation and one-use proofs."""
    def __init__(self):
        self.binding = NativeOrigin("independent-provider", "independent-catalog", "independent-native")
        self.documents, self.proofs, self.claims = {}, {}, []
        self.on_claim = None

    def document(self, caller):
        document = object()
        self.documents[document] = caller
        return document

    def capture(self, attachment, **context):
        self.validate(attachment, expected=self.binding, phase="prepare", **context)
        return self.binding

    def validate(self, attachment, *, caller, profile_id, expected, phase):
        if self.documents.get(attachment) != caller or expected != self.binding or profile_id not in {"alpha", "beta"}:
            raise ApiFailure("forbidden")

    def claim_dispatch(self, attachment, *, request, **context):
        self.validate(attachment, phase="dispatch", **context)
        self.claims.append(request)
        if self.on_claim is not None:
            self.on_claim()
        return object()

    def consume_authorization(self, proof, **context):
        return self.proofs.pop(proof, None) == context


@pytest.fixture
def protected(runtime):
    r = runtime
    native = NativeBoundary()
    authority = [r["grants"][0]]
    host = CoreRuntimeHost(r["meta"], tuple(r["host"].profiles.values()), selected="alpha",
        publish=r["published"].append, credential_authorizer=lambda *_: True, active=r["first"],
        clock=lambda: r["clock"][0], intent_origin=native, intent_auth=native, intent_binding=native.binding)
    endpoints = []

    def endpoint(grant):
        stream = host.bind(grant)
        endpoints.append(stream)
        def request(operation, params=None, key=None):
            frame = {"api_version": 1, "request_id": "independent:test", "operation": operation, "params": params or {}}
            if key is not None: frame["idempotency_key"] = key
            return decode_frame(stream.exchange(encode_frame(frame)))
        assert request("runtime.capabilities")["ok"]
        handles = {row["display_name"]: row["profile"] for row in request("profile.catalog")["result"]["profiles"]}
        return request, handles

    request, handles = endpoint(lambda: authority[0])
    document = native.document(authority[0].caller)
    intents = host.profile_intents

    def prepare(action="lock", key="independent-original-key-0001", target="alpha"):
        return intents.prepare(lambda: authority[0], action=action, profile=handles[target],
            original_key=key, attachment=document)

    def resume(ticket, attachment=None, token=None):
        return intents.resume(lambda: authority[0], intent_ref=ticket["intent_ref"],
            attachment=document if attachment is None else attachment, credential_handle=token)

    def credential(ticket, attachment=None, lifetime=60):
        attachment = document if attachment is None else attachment
        row = r["meta"].get("host_profile_operation", ticket["intent_ref"])
        proof = object()
        native.proofs[proof] = dict(caller=authority[0].caller, profile_id=row["profile"], intent_ref=ticket["intent_ref"],
            origin=native.binding, attachment=attachment, core_host_incarnation=row["host_incarnation"],
            expected_revision=row["expected_revision"])
        return host.issue_bound_unlock_credential(lambda: authority[0], intent_ref=ticket["intent_ref"],
            attachment=attachment, proof=proof, lifetime_seconds=lifetime)

    try:
        yield SimpleNamespace(base=r, host=host, native=native, authority=authority, document=document,
            intents=intents, request=request, handles=handles, endpoint=endpoint, prepare=prepare,
            resume=resume, credential=credential, meta=r["meta"])
    finally:
        for stream in endpoints: stream.close()


def row(p, ticket):
    return p.meta.get("host_profile_operation", ticket["intent_ref"])


def lose_catalog_return(p, monkeypatch, state, *, committed):
    """Inject only the storage return boundary; successful writes are real CAS."""
    original = p.meta.conditional_put_and_delete
    def write(expected, records, *args, **kwargs):
        records = list(records)
        if any(kind == "host_profile_operation" and value.get("state") == state for kind, _, value in records):
            if committed: original(expected, records, *args, **kwargs)
            raise StorageUnavailable("independent lost catalog return")
        return original(expected, records, *args, **kwargs)
    monkeypatch.setattr(p.meta, "conditional_put_and_delete", write)
    return original


def blocked_alternatives(p):
    before = p.host.lifecycle.query(), p.meta.list("host_profile_operation")
    other = replace(p.authority[0], caller="independent-other-caller")
    request, handles = p.endpoint(lambda: other)
    for call, profiles, caller in ((p.request, p.handles, p.authority[0].caller), (request, handles, other.caller)):
        for action in ("lock", "select", "unlock"):
            params = {"profile": profiles["beta" if action == "select" else "alpha"]}
            if action == "unlock": params["credential_handle"] = p.host.issue_unlock_credential(caller, "alpha")
            result = call("profile." + action, params, "independent-alternate-key-" + action)
            assert not result["ok"] and result["error"]["code"] == "unavailable"
    assert (p.host.lifecycle.query(), p.meta.list("host_profile_operation")) == before


def test_framed_reserved_alias_cannot_be_retargeted_or_dispatched_without_native_context(protected):
    p = protected
    ticket = p.prepare()
    for operation, target, code in (("profile.lock", "alpha", "forbidden"),
            ("profile.unlock", "alpha", "idempotency_conflict"), ("profile.select", "beta", "idempotency_conflict")):
        params = {"profile": p.handles[target]}
        if operation == "profile.unlock": params["credential_handle"] = "untrusted-credential"
        answer = p.request(operation, params, "independent-original-key-0001")
        assert not answer["ok"] and answer["error"]["code"] == code
    other = replace(p.authority[0], caller="independent-other-caller")
    with pytest.raises(ApiFailure, match="not_found"):
        p.intents.observe(lambda: other, intent_ref=ticket["intent_ref"], attachment=p.document)
    assert row(p, ticket)["state"] == "prepared" and not p.base["first"]._store_closed
    assert len(p.meta.list("host_profile_operation")) == len(p.meta.list("host_profile_alias")) == 1


@pytest.mark.parametrize("target", ["alpha", "beta"])
def test_real_generic_receipt_cannot_be_adopted_as_private_recovery(protected, target):
    p = protected
    key = "independent-existing-generic-key"
    assert p.request("profile.lock", {"profile": p.handles["alpha"]}, key)["ok"]
    before = p.meta.list("host_profile_operation")
    with pytest.raises(ApiFailure, match="idempotency_conflict"):
        p.prepare(action="select", key=key, target=target)
    assert p.meta.list("host_profile_operation") == before
    assert not p.meta.list("host_profile_alias")
    assert p.request("profile.select", {"profile": p.handles["beta"]}, "independent-fresh-select-key")["ok"]


@pytest.mark.parametrize("committed", [False, True])
def test_admission_write_loss_never_runs_lifecycle_and_fences_only_uncertain_admission(protected, monkeypatch, committed):
    p = protected
    ticket = p.prepare()
    before = p.host.lifecycle.query(), len(p.base["loads"]), len(p.base["published"])
    original = lose_catalog_return(p, monkeypatch, "intent", committed=committed)
    with pytest.raises(StorageUnavailable): p.resume(ticket)
    monkeypatch.setattr(p.meta, "conditional_put_and_delete", original)
    assert not p.native.claims
    assert (p.host.lifecycle.query(), len(p.base["loads"]), len(p.base["published"])) == before
    assert not p.base["first"]._store_closed
    if committed:
        blocked_alternatives(p)
        assert row(p, ticket)["state"] == "intent"
        assert p.resume(ticket)["historical_outcome"] == "applied"
    else:
        assert row(p, ticket)["state"] == "prepared"
        assert p.meta.get("host_profile_dispatch", "current") is None
        p.intents.withdraw(lambda: p.authority[0], intent_ref=ticket["intent_ref"], attachment=p.document)
        assert p.request("profile.lock", {"profile": p.handles["alpha"]}, "independent-after-rejection-key")["ok"]


@pytest.mark.parametrize("committed", [False, True])
def test_lost_unlock_completion_preserves_exact_open_and_pure_observation(protected, monkeypatch, committed):
    p = protected
    assert p.request("profile.lock", {"profile": p.handles["alpha"]}, "independent-initial-lock-key")["ok"]
    ticket = p.prepare(action="unlock")
    token = p.credential(ticket)
    loads = len(p.base["loads"])
    original = lose_catalog_return(p, monkeypatch, "complete", committed=committed)
    with pytest.raises(StorageUnavailable): p.resume(ticket, token=token)
    monkeypatch.setattr(p.meta, "conditional_put_and_delete", original)
    assert len(p.base["loads"]) == loads + 1
    opened = p.host.lifecycle.active
    assert opened is not None and not opened._store_closed
    if not committed: blocked_alternatives(p)
    before = p.meta._db.total_changes, row(p, ticket), p.meta.get("host_profile_dispatch", "current"), len(p.base["published"])
    observed = p.intents.observe(lambda: p.authority[0], intent_ref=ticket["intent_ref"], attachment=p.document)
    assert observed["historical_outcome"] == "applied"
    assert p.intents.list(lambda: p.authority[0], attachment=p.document)["intents"] == [observed]
    assert (p.meta._db.total_changes, row(p, ticket), p.meta.get("host_profile_dispatch", "current"), len(p.base["published"])) == before
    assert p.resume(ticket)["historical_outcome"] == "applied"  # No fresh credential or opener.
    assert len(p.base["loads"]) == loads + 1 and p.host.lifecycle.active is opened
    assert p.meta.get("host_profile_dispatch", "current") is None
    assert p.request("profile.lock", {"profile": p.handles["alpha"]}, "independent-after-completion-key")["ok"]


@pytest.mark.parametrize("denial", ["claim", "grant", "document"])
def test_later_denial_cannot_erase_real_earlier_close_uncertainty(protected, monkeypatch, denial):
    p = protected
    ticket = p.prepare()
    close = p.base["first"].close
    def closed_but_return_lost():
        close()
        raise NativeUnavailable("independent service close return lost")
    monkeypatch.setattr(p.base["first"], "close", closed_but_return_lost)
    with pytest.raises(NativeUnavailable): p.resume(ticket)
    assert p.base["first"]._store_closed  # Actual effect happened; not a mocked lifecycle result.
    original = row(p, ticket)
    owner = p.authority[0]
    def deny():
        if denial == "claim": raise ApiFailure("forbidden")
        if denial == "grant": p.authority[0] = replace(owner, permissions=frozenset())
        else: del p.native.documents[p.document]
    p.native.on_claim = deny
    with pytest.raises(ApiFailure, match="forbidden"): p.resume(ticket)
    assert row(p, ticket) == original and row(p, ticket)["ever_dispatched"] is True
    p.authority[0] = owner
    replacement = p.native.document(owner.caller) if denial == "document" else p.document
    assert p.intents.observe(lambda: p.authority[0], intent_ref=ticket["intent_ref"], attachment=replacement)["historical_outcome"] == "unknown"
    blocked_alternatives(p)
    monkeypatch.setattr(p.base["first"], "close", close)
    p.native.on_claim = None
    assert p.resume(ticket, attachment=replacement)["historical_outcome"] == "applied"


@pytest.mark.parametrize("revocation", ["grant", "document"])
def test_fresh_revocation_after_claim_has_positive_no_effect_and_releases_fence(protected, revocation):
    p = protected
    ticket = p.prepare()
    owner = p.authority[0]
    def revoke():
        if revocation == "grant": p.authority[0] = replace(owner, permissions=frozenset())
        else: del p.native.documents[p.document]
    p.native.on_claim = revoke
    with pytest.raises(ApiFailure, match="forbidden"): p.resume(ticket)
    assert not p.base["first"]._store_closed and p.host.lifecycle.query()["revision"] == 0
    p.authority[0], p.native.on_claim = owner, None
    replacement = p.native.document(owner.caller) if revocation == "document" else p.document
    observed = p.intents.observe(lambda: p.authority[0], intent_ref=ticket["intent_ref"], attachment=replacement)
    assert observed["historical_outcome"] == "rejected_no_effect"
    assert p.meta.get("host_profile_dispatch", "current") is None
    with pytest.raises(ApiFailure, match="conflict"): p.resume(ticket, attachment=replacement)
    assert p.request("profile.lock", {"profile": p.handles["alpha"]}, "independent-new-intent-after-denial")["ok"]
    assert len(p.native.claims) == 1


def test_lost_prepare_return_recovers_one_sealed_reservation_without_effect(protected, monkeypatch):
    p = protected
    original = lose_catalog_return(p, monkeypatch, "prepared", committed=True)
    with pytest.raises(StorageUnavailable): p.prepare()
    monkeypatch.setattr(p.meta, "conditional_put_and_delete", original)
    before = p.meta.list("host_profile_operation"), p.meta.list("host_profile_alias")
    ticket = p.prepare()
    assert p.meta.list("host_profile_operation") == before[0] and p.meta.list("host_profile_alias") == before[1]
    assert len(before[0]) == len(before[1]) == 1 and before[0][0]["original_key"] == "independent-original-key-0001"
    assert ticket["dispatch"] == "not_dispatched" and not p.native.claims and not p.base["first"]._store_closed


def test_cold_catalog_observation_cannot_open_repair_or_expose_authority(protected):
    p = protected
    assert p.request("profile.lock", {"profile": p.handles["alpha"]}, "independent-cold-observation-key")["ok"]
    ticket = p.prepare(action="unlock")
    assert p.base["first"].store._key is None
    before = p.meta._db.total_changes, len(p.base["loads"]), len(p.base["published"]), p.host.lifecycle.query()
    for _ in range(3):
        assert p.intents.observe(lambda: p.authority[0], intent_ref=ticket["intent_ref"], attachment=p.document) == ticket
        assert p.intents.list(lambda: p.authority[0], attachment=p.document)["intents"] == [ticket]
    assert (p.meta._db.total_changes, len(p.base["loads"]), len(p.base["published"]), p.host.lifecycle.query()) == before
    selected = json.dumps(ticket)
    for private in ("independent-original-key-0001", p.native.binding.provider_binding_id,
                    p.native.binding.catalog_binding_id, p.native.binding.native_host_generation,
                    row(p, ticket)["operation_id"], row(p, ticket)["host_incarnation"]):
        assert private not in selected
    for path in p.base["meta_root"].glob("mesh-chat.vault*"):
        assert b"independent-original-key-0001" not in path.read_bytes()
    assert not p.intents.available
    assert not any("intent" in operation for operation in p.request("runtime.capabilities")["result"]["operations"])


@pytest.mark.parametrize("host_limit", [2, 8])
def test_real_terminal_reservations_charge_one_shared_logical_quota(protected, monkeypatch, host_limit):
    from mesh_chat.core_api import runtime_host
    p = protected
    monkeypatch.setattr(runtime_host, "MAX_HOST_OPERATIONS", host_limit)
    monkeypatch.setattr(runtime_host, "MAX_CALLER_OPERATIONS", 2)
    for number in range(2):
        ticket = p.prepare(key=f"independent-quota-key-{number:04}")
        p.intents.withdraw(lambda: p.authority[0], intent_ref=ticket["intent_ref"], attachment=p.document)
    assert len(p.meta.list("host_profile_operation")) == len(p.meta.list("host_profile_alias")) == 2
    with pytest.raises(ApiFailure, match="resource_exhausted"): p.prepare(key="independent-over-quota-key")
    result = p.request("profile.lock", {"profile": p.handles["alpha"]}, "independent-generic-over-quota")
    assert not result["ok"] and result["error"]["code"] == "resource_exhausted"
    assert not p.native.claims and not p.base["first"]._store_closed


@pytest.mark.parametrize("action", ["lock", "unlock"])
def test_new_invalid_nonselected_generic_action_cannot_strand_ordinary_lifecycle(protected, action):
    p = protected
    params = {"profile": p.handles["beta"]}
    if action == "unlock": params["credential_handle"] = p.host.issue_unlock_credential(p.authority[0].caller, "beta")
    bad = p.request("profile." + action, params, "independent-invalid-target-key")
    assert not bad["ok"]
    assert not p.base["first"]._store_closed and not p.native.claims
    assert p.request("profile.lock", {"profile": p.handles["alpha"]}, "independent-valid-after-invalid-key")["ok"]


def test_exact_revoked_expired_attachment_cleanup_does_not_revoke_current_credential(protected):
    p = protected
    assert p.request("profile.lock", {"profile": p.handles["alpha"]}, "independent-lock-before-credential")["ok"]
    ticket = p.prepare(action="unlock")
    old = p.credential(ticket, lifetime=1)
    current = p.native.document(p.authority[0].caller)
    fresh = p.credential(ticket, attachment=current, lifetime=300)
    p.base["clock"][0] += 2
    del p.native.documents[p.document]
    owner = p.authority[0]
    p.authority[0] = replace(owner, permissions=frozenset())
    with pytest.raises(ApiFailure, match="forbidden"):
        p.host.revoke_attachment_credentials(origin=replace(p.native.binding, native_host_generation="unrelated-native"),
            attachment=p.document, cleanup_epoch=23)
    assert old in p.host._credentials and fresh in p.host._credentials
    with pytest.raises(ApiFailure, match="forbidden"):
        p.host.revoke_bound_unlock_credential(token=fresh, intent_ref=ticket["intent_ref"],
            origin=p.native.binding, attachment=p.document)
    with pytest.raises(ApiFailure, match="forbidden"):
        p.host.revoke_bound_unlock_credential(token=fresh, intent_ref="0" * 64,
            origin=p.native.binding, attachment=current)
    ack = p.host.revoke_attachment_credentials(origin=p.native.binding, attachment=p.document, cleanup_epoch=23)
    assert ack.attachment is p.document and ack.cleanup_epoch == 23
    assert old not in p.host._credentials and fresh in p.host._credentials
    assert p.document not in p.native.documents and current in p.native.documents
    p.authority[0] = owner
    before = len(p.base["loads"])
    with pytest.raises(ApiFailure, match="forbidden"): p.resume(ticket, token=old)
    assert len(p.base["loads"]) == before
    assert p.resume(ticket, attachment=current, token=fresh)["historical_outcome"] == "applied"
    assert len(p.base["loads"]) == before + 1


def ordinary_request_with_lost_result(r, monkeypatch, loss):
    caps = r.request("runtime.capabilities")
    assert caps["ok"]
    profile = caps["result"]["profiles"][0]
    original = lose_catalog_return(r, monkeypatch, "intent" if loss == "admission" else "complete",
        committed=loss == "admission")
    result = r.request("profile.lock", {"profile": profile}, "independent-native-reopen-original")
    assert not result["ok"] and result["error"]["code"] == "unavailable"
    monkeypatch.setattr(r.meta, "conditional_put_and_delete", original)
    history = r.meta.list("host_profile_operation")
    assert len(history) == 1 and history[0]["state"] == "intent"
    assert r.active._store_closed is (loss == "completion")
    return profile, history


def native_credential(r, host, profile):
    challenge = host.begin_authentication(profile)["challenge"]
    r.proof.add(challenge)  # Explicit OS-authorizer boundary double, not platform proof.
    return host.complete_authentication(challenge)["credential_handle"]


@pytest.mark.parametrize("loss", ["admission", "completion"])
@pytest.mark.parametrize("action", ["lock", "select", "unlock"])
def test_acknowledged_native_owner_close_allows_fresh_actions_without_rewriting_unknown_history(platform_host, monkeypatch, loss, action):
    r = platform_host
    assert r.host.core.profile_intents.origin is None and r.host.core.profile_intents.binding is None
    assert r.meta.get("host_profile_admission_policy", "current") is None
    profile, history = ordinary_request_with_lost_result(r, monkeypatch, loss)
    previous = r.host.context()["host_generation"], r.host.core.lifecycle.query()["host_incarnation"]
    r.host.close()  # Real production close: drain lifecycle, deny old admission, close catalog.
    assert r.host._closed and r.active._store_closed and r.meta._key is None
    assert not r.request("runtime.capabilities")["ok"]
    catalog = VaultStore(r.meta_root, r.meta_key, allow_unprotected_for_tests=True)
    reopened = None
    try:
        assert catalog.list("host_profile_operation") == history
        reopened = r.build(None, catalog)
        assert reopened.core.profile_intents.origin is None and reopened.core.profile_intents.binding is None
        assert reopened.context()["host_generation"] != previous[0]
        assert reopened.core.lifecycle.query()["host_incarnation"] != previous[1]
        assert reopened.context()["state"] == "locked" and not r.loads
        caps = r.request("runtime.capabilities", target=reopened)
        assert caps["ok"] and caps["result"]["profiles"][0] == profile
        old = r.request("profile.lock", {"profile": profile}, "independent-native-reopen-original", target=reopened)
        assert not old["ok"] and old["error"]["code"] == "resync_required"
        params = {"profile": profile}
        if action == "unlock": params["credential_handle"] = native_credential(r, reopened, profile)
        fresh = r.request("profile." + action, params, "independent-native-reopen-fresh", target=reopened)
        assert all(item in catalog.list("host_profile_operation") for item in history)
        assert fresh["ok"], fresh  # Old custody ended; historical uncertainty has not.
    finally:
        if reopened is not None: reopened.close()
        else: catalog.close()


@pytest.mark.parametrize("loss", ["admission", "completion"])
def test_same_live_configured_owner_retains_uncertain_ordinary_custody(protected, monkeypatch, loss):
    p = protected
    original = lose_catalog_return(p, monkeypatch, "intent" if loss == "admission" else "complete",
        committed=loss == "admission")
    result = p.request("profile.lock", {"profile": p.handles["alpha"]}, "independent-live-owner-original")
    assert not result["ok"] and result["error"]["code"] == "unavailable"
    monkeypatch.setattr(p.meta, "conditional_put_and_delete", original)
    history = p.meta.list("host_profile_operation")
    slot = p.meta.get("host_profile_dispatch", "current")
    assert len(history) == 1 and history[0]["state"] == "intent" and slot is not None
    assert p.host.profile_intents.origin is p.native
    blocked_alternatives(p)
    assert p.meta.list("host_profile_operation") == history
    assert p.meta.get("host_profile_dispatch", "current") == slot


@pytest.mark.parametrize("loss", ["admission", "completion"])
def test_new_core_uuid_and_missing_private_ports_cannot_drop_existing_private_custody(protected, monkeypatch, loss):
    p = protected
    ticket = p.prepare()
    original = lose_catalog_return(p, monkeypatch, "intent" if loss == "admission" else "complete",
        committed=loss == "admission")
    with pytest.raises(StorageUnavailable): p.resume(ticket)
    monkeypatch.setattr(p.meta, "conditional_put_and_delete", original)
    history, slot = row(p, ticket), p.meta.get("host_profile_dispatch", "current")
    # Deliberately no old-owner close/ack. A new UUID and dropping injected ports
    # cannot turn this still-owned protected reservation into ordinary admission.
    replacement = CoreRuntimeHost(p.meta, tuple(p.host.profiles.values()), selected="alpha",
        publish=p.base["published"].append, credential_authorizer=lambda *_: True)
    assert replacement.lifecycle.query()["host_incarnation"] != p.host.lifecycle.query()["host_incarnation"]
    stream = replacement.bind(lambda: p.authority[0])
    try:
        def call(operation, params, key=None):
            value = {"api_version": 1, "request_id": "independent:replacement", "operation": operation, "params": params}
            if key is not None: value["idempotency_key"] = key
            return decode_frame(stream.exchange(encode_frame(value)))
        assert call("runtime.capabilities", {})["ok"]
        result = call("profile.lock", {"profile": p.handles["alpha"]}, "independent-unproved-replacement")
        assert not result["ok"] and result["error"]["code"] == "unavailable"
        assert row(p, ticket) == history and p.meta.get("host_profile_dispatch", "current") == slot
    finally:
        stream.close()


def closed_catalog_successor(p):
    """Actual Core resource/store teardown; not proof of private native retirement."""
    with p.host._lock:
        assert p.host.lifecycle.retire_for_host_shutdown()["state"] == "locked"
        for session in tuple(p.host._sessions): session.detach()
        p.meta.close()
    catalog = VaultStore(p.base["meta_root"], p.base["meta_key"], allow_unprotected_for_tests=True)
    successor = CoreRuntimeHost(catalog, tuple(p.host.profiles.values()), selected="alpha",
        publish=p.base["published"].append, credential_authorizer=lambda *_: True)
    assert successor.lifecycle.query()["host_incarnation"] != p.host.lifecycle.query()["host_incarnation"]
    assert successor.profile_intents.origin is None and successor.profile_intents.binding is None
    return catalog, successor


def core_frames(host, authorize):
    stream = host.bind(authorize)
    def call(operation, params=None, key=None):
        frame = {"api_version": 1, "request_id": "independent:containment", "operation": operation, "params": params or {}}
        if key is not None: frame["idempotency_key"] = key
        return decode_frame(stream.exchange(encode_frame(frame)))
    assert call("runtime.capabilities")["ok"]
    return stream, call


@pytest.mark.parametrize("loss", ["admission", "completion"])
def test_configured_generic_custody_before_any_private_reservation_survives_port_removal(protected, monkeypatch, loss):
    p = protected
    assert not p.meta.list("host_profile_operation") and not p.meta.list("host_profile_alias")
    original = lose_catalog_return(p, monkeypatch, "intent" if loss == "admission" else "complete",
        committed=loss == "admission")
    key = "configured-generic-before-private-key"
    failed = p.request("profile.lock", {"profile": p.handles["alpha"]}, key)
    assert not failed["ok"] and failed["error"]["code"] == "unavailable"
    monkeypatch.setattr(p.meta, "conditional_put_and_delete", original)
    history, slot = p.meta.list("host_profile_operation"), p.meta.get("host_profile_dispatch", "current")
    assert len(history) == 1 and history[0]["state"] == "intent" and history[0].get("version") != 2
    assert slot is not None and not p.meta.list("host_profile_alias")
    catalog, successor = closed_catalog_successor(p)
    stream, call = core_frames(successor, lambda: p.authority[0])
    try:
        assert catalog.list("host_profile_operation") == history and not catalog.list("host_profile_alias")
        old = call("profile.lock", {"profile": p.handles["alpha"]}, key)
        assert not old["ok"] and old["error"]["code"] == "resync_required"
        denied = call("profile.lock", {"profile": p.handles["alpha"]}, "configured-generic-replacement-key")
        assert not denied["ok"] and denied["error"]["code"] == "unavailable"
        assert catalog.list("host_profile_operation") == history
        assert catalog.get("host_profile_dispatch", "current") == slot
    finally:
        stream.close()
        catalog.close()


def test_configured_catalog_remains_protected_without_private_history_or_current_slot(protected, monkeypatch):
    p = protected
    assert p.request("profile.lock", {"profile": p.handles["alpha"]}, "configured-complete-generic-key")["ok"]
    history = p.meta.list("host_profile_operation")
    assert len(history) == 1 and history[0]["state"] == "complete" and history[0].get("version") != 2
    assert not p.meta.list("host_profile_alias") and p.meta.get("host_profile_dispatch", "current") is None
    catalog, successor = closed_catalog_successor(p)
    stream, call = core_frames(successor, lambda: p.authority[0])
    try:
        boundary = SimpleNamespace(meta=catalog)
        original = lose_catalog_return(boundary, monkeypatch, "intent", committed=True)
        failed = call("profile.lock", {"profile": p.handles["alpha"]}, "configured-after-port-removal-key")
        assert not failed["ok"] and failed["error"]["code"] == "unavailable"
        monkeypatch.setattr(catalog, "conditional_put_and_delete", original)
        assert catalog.get("host_profile_dispatch", "current") is not None
        before = catalog.list("host_profile_operation")
        blocked = call("profile.lock", {"profile": p.handles["alpha"]}, "configured-cannot-overtake-new-key")
        assert not blocked["ok"] and blocked["error"]["code"] == "unavailable"
        assert catalog.list("host_profile_operation") == before and all(item in before for item in history)
    finally:
        stream.close()
        catalog.close()


def test_existing_premarking_ordinary_slot_never_auto_migrates_to_unprotected_admission(runtime, monkeypatch):
    r = runtime
    assert r["host"].profile_intents.origin is None and r["host"].profile_intents.binding is None
    p = SimpleNamespace(host=r["host"], meta=r["meta"], base=r)
    assert p.meta.get("host_profile_admission_policy", "current") is None
    original = lose_catalog_return(p, monkeypatch, "intent", committed=True)
    failed = r["invoke"]("profile.lock", {"profile": r["profiles"]["alpha"]}, "ambiguous-premarking-original")
    assert not failed["ok"] and failed["error"]["code"] == "unavailable"
    monkeypatch.setattr(p.meta, "conditional_put_and_delete", original)
    entries = list(p.meta.items("host_profile_operation"))
    assert len(entries) == 1 and entries[0][1]["state"] == "intent" and entries[0][1].get("version") != 2
    identity, receipt = entries[0]
    # Exact pre-marker protocol fixture: persist the old slot with real CAS,
    # without rewriting the unknown receipt, deleting authority or claiming effects.
    slot = {"identity": identity}
    p.meta.conditional_put_and_delete(
        {("host_profile_operation", identity): receipt,
         ("host_profile_dispatch", "current"): p.meta.get("host_profile_dispatch", "current")},
        [("host_profile_dispatch", "current", slot)])
    assert not p.meta.list("host_profile_alias")
    catalog, successor = closed_catalog_successor(p)
    stream, call = core_frames(successor, lambda: r["grants"][0])
    try:
        denied = call("profile.lock", {"profile": r["profiles"]["alpha"]}, "ambiguous-premarking-fresh-key")
        assert not denied["ok"] and denied["error"]["code"] == "unavailable"
        assert catalog.get("host_profile_operation", identity) == receipt
        assert catalog.get("host_profile_dispatch", "current") == slot
    finally:
        stream.close()
        catalog.close()
