"""Runtime-level Core against the actual lifecycle port and encrypted vaults."""
from dataclasses import replace
import json
import os

from jsonschema import Draft202012Validator
import pytest

from mesh_chat.core_api.composition import bind_service_session
from mesh_chat.core_api.runtime_host import CoreRuntimeHost, RegisteredProfile
from mesh_chat.core_api.session import Grant
from mesh_chat.core_api.wire_codec import decode_frame, encode_frame
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore, RecordConflict
from mesh_chat.errors import StorageUnavailable
from test_core_sdk_distribution import run_consumer, installed_consumer
from test_core_sdk_upgrade import pinned_install, old_consumer

from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(MeshChatService, "_start_network", lambda *_: None)
    monkeypatch.setattr(MeshChatService, "_prepare_lan_fallback", lambda *_: None)
    keys = {name: os.urandom(32) for name in ("alpha", "beta")}
    opened, loads = [], []
    def opener(name):
        loads.append(name)  # Models an existing host key-slot read, never a Core parameter.
        root = tmp_path / name
        store = VaultStore(root, keys[name], allow_unprotected_for_tests=True)
        service = MeshChatService(store, root, lambda _: None)
        opened.append(service)
        if store.get("profile", "local") is None:
            service.create_profile(name)
            store.put("contact", "internal-peer", {"id": "internal-peer", "display_name": "Synthetic peer",
                "trust": "approved", "destination_hash": "ab" * 16})
        return service
    first = opener("alpha")
    second = opener("beta")
    handles = {"alpha": bytes.fromhex(first.store.opaque_id("core-api-handle-key", "v1")),
               "beta": bytes.fromhex(second.store.opaque_id("core-api-handle-key", "v1"))}
    second.close()
    meta_key = os.urandom(32)
    meta = VaultStore(tmp_path / "host-catalog", meta_key, allow_unprotected_for_tests=True)
    profiles = tuple(RegisteredProfile(name, name, handles[name], lambda name=name: opener(name)) for name in keys)
    published, clock, credential_authority = [], [100.0], [True]
    def build(active, selected="alpha", catalog=None, registered=None):
        return CoreRuntimeHost(catalog or meta, registered or profiles, selected=selected, publish=published.append,
            credential_authorizer=lambda *_: credential_authority[0], active=active, clock=lambda: clock[0])
    host = build(first)
    grants = [Grant("application-owner", frozenset({"observe", "read", "send", "profile_owner"}), ("alpha", "beta"))]
    stream = host.bind(lambda: grants[0])
    def invoke(operation, params=None, key=None, endpoint=None):
        value = {"api_version": 1, "request_id": "runtime:test", "operation": operation, "params": params or {}}
        if key is not None:
            value["idempotency_key"] = key
        return decode_frame((endpoint or stream).exchange(encode_frame(value)))
    caps = invoke("runtime.capabilities")
    assert caps["ok"], caps
    catalog = invoke("profile.catalog")["result"]
    by_name = {row["display_name"]: row["profile"] for row in catalog["profiles"]}
    yield {"host": host, "stream": stream, "invoke": invoke, "grants": grants, "profiles": by_name,
           "first": first, "meta": meta, "handles": handles, "keys": keys, "loads": loads,
           "opened": opened, "published": published, "clock": clock, "credential_authority": credential_authority,
           "build": build, "caps": caps, "meta_key": meta_key, "meta_root": tmp_path / "host-catalog"}
    stream.close()
    for service in opened:
        service.close()
    meta.close()


def test_runtime_preserves_existing_handles_and_only_actual_host_advertises_lifecycle(runtime):
    r = runtime
    original = bind_service_session(r["first"], lambda: Grant(r["grants"][0].caller,
        r["grants"][0].permissions, ("local",)))
    caps = original.request({"api_version": 1, "request_id": "old:1", "operation": "runtime.capabilities", "params": {}})
    assert caps["result"]["profiles"] == [r["profiles"]["alpha"]]
    assert "profile.catalog" not in caps["result"]["operations"]
    view = r["invoke"]("profile.query", {"profile": r["profiles"]["alpha"]})
    assert view["ok"] and view["result"]["display_name"] == "alpha"
    for response, schema in [(r["caps"], "observation-result-v1.schema.json"),
                             (r["invoke"]("profile.catalog"), "profile-catalog-result-v1.schema.json")]:
        Draft202012Validator(json.loads((ROOT / "contracts/core-api" / schema).read_text())).validate(response)


def test_async_authority_revocation_does_not_detach_or_wait_for_renderer_request_lock(runtime):
    from threading import Thread
    r = runtime
    assert r["invoke"]("profile.query", {"profile": r["profiles"]["alpha"]})["ok"]
    outer = r["stream"]._session
    current_grant = outer._inner._authorize
    r["grants"][0] = replace(r["grants"][0], caller="different-current-caller")
    results = []
    def resolve():
        with r["first"]._dispatch_lock:
            results.append(current_grant())
    with outer._lock:
        worker = Thread(target=resolve)
        worker.start()
        worker.join(timeout=1)
        completed_without_request_lock = not worker.is_alive()
    worker.join(timeout=2)
    assert completed_without_request_lock and results == [None]
    assert not outer._closed  # The callback only reports authority; it cannot detach.
    assert r["invoke"]("profile.query", {"profile": r["profiles"]["alpha"]})["error"]["code"] == "unauthenticated"


def test_lock_keeps_runtime_binding_alive_and_unlock_reads_original_slot_fresh(runtime):
    r = runtime
    invoke, profile = r["invoke"], r["profiles"]["alpha"]
    old_inner = r["stream"]._session._inner
    assert invoke("profile.lock", {"profile": profile}, "runtime-lock-key-0001")["ok"]
    assert r["first"]._store_closed and r["first"].store._key is None and r["first"].store._cipher is None
    assert old_inner._closed
    assert r["published"][-1] is None
    assert invoke("profile.query", {"profile": profile})["error"]["code"] == "locked"
    assert invoke("profile.catalog")["result"]["profiles"][0]["state"] == "locked"
    before = len(r["loads"])
    credential = r["host"].issue_unlock_credential(r["grants"][0].caller, "alpha")
    assert invoke("profile.unlock", {"profile": profile, "credential_handle": credential}, "runtime-unlock-key-0001")["ok"]
    assert len(r["loads"]) == before + 1
    assert invoke("profile.query", {"profile": profile})["result"]["display_name"] == "alpha"
    assert r["host"].lifecycle.active is not r["first"]


def test_selection_is_durable_but_does_not_open_without_explicit_unlock(runtime):
    r = runtime
    before = len(r["loads"])
    assert r["invoke"]("profile.select", {"profile": r["profiles"]["beta"]}, "runtime-select-key-0001")["ok"]
    assert r["meta"].get("host_profile_catalog", "selection") == {"selected": "beta"}
    assert r["host"].lifecycle.active is None and len(r["loads"]) == before
    r["host"].lifecycle.reconcile()
    assert len(r["loads"]) == before
    assert r["first"]._store_closed


@pytest.mark.parametrize("fault", ["permission", "profile", "caller"])
def test_replay_rechecks_current_host_authority(runtime, fault):
    r = runtime
    params = {"profile": r["profiles"]["alpha"]}
    assert r["invoke"]("profile.lock", params, "runtime-authority-key-0001")["ok"]
    original = r["grants"][0]
    r["grants"][0] = replace(original, **({"permissions": frozenset({"observe"})} if fault == "permission"
        else {"profiles": ("beta",)} if fault == "profile" else {"caller": "different-caller"}))
    assert r["invoke"]("profile.lock", params, "runtime-authority-key-0001")["error"]["code"] in {"forbidden", "unauthenticated"}
    assert r["host"].lifecycle.active is None


def test_catalog_filters_current_scope_and_no_request_can_supply_keys_or_paths(runtime):
    r = runtime
    r["grants"][0] = replace(r["grants"][0], profiles=("alpha",))
    assert len(r["invoke"]("profile.catalog")["result"]["profiles"]) == 1
    assert r["invoke"]("profile.select", {"profile": r["profiles"]["beta"]}, "runtime-scope-key-0001")["error"]["code"] == "forbidden"
    assert r["invoke"]("profile.unlock", {"profile": r["profiles"]["alpha"], "vault_key": "untrusted", "profile_dir": "untrusted"}, "runtime-json-key-0001")["error"]["code"] == "invalid_request"
    assert r["meta"].list("host_profile_operation") == []


@pytest.mark.parametrize("fault", ["expired", "wrong_caller", "wrong_profile"])
def test_invalid_credential_cannot_admit_or_open(runtime, fault):
    r = runtime
    profile = r["profiles"]["alpha"]
    assert r["invoke"]("profile.lock", {"profile": profile}, "runtime-lock-cred-key-0001")["ok"]
    credential = r["host"].issue_unlock_credential("different" if fault == "wrong_caller" else r["grants"][0].caller,
                                                   "beta" if fault == "wrong_profile" else "alpha", lifetime_seconds=1)
    if fault == "expired":
        r["clock"][0] += 2
    before = len(r["meta"].list("host_profile_operation")), len(r["loads"])
    result = r["invoke"]("profile.unlock", {"profile": profile, "credential_handle": credential}, "runtime-invalid-cred-key-0001")
    assert result["error"]["code"] == "forbidden"
    assert (len(r["meta"].list("host_profile_operation")), len(r["loads"])) == before


def test_credential_is_single_use_but_same_completed_identity_replays_without_open(runtime):
    r = runtime
    profile = r["profiles"]["alpha"]
    assert r["invoke"]("profile.lock", {"profile": profile}, "runtime-lock-replay-key-0001")["ok"]
    credential = r["host"].issue_unlock_credential(r["grants"][0].caller, "alpha")
    params = {"profile": profile, "credential_handle": credential}
    first = r["invoke"]("profile.unlock", params, "runtime-credential-key-0001")
    assert first["ok"]
    before = len(r["loads"])
    assert r["invoke"]("profile.unlock", params, "runtime-credential-key-0001") == first
    assert r["invoke"]("profile.unlock", params, "runtime-credential-key-0002")["error"]["code"] == "forbidden"
    assert len(r["loads"]) == before


@pytest.mark.parametrize("phase", ["admit_after", "complete_before", "complete_after"])
def test_lost_metadata_commit_return_resolves_same_profile_lock(runtime, phase, monkeypatch):
    r = runtime
    original, failed = r["meta"].conditional_put_and_delete, []
    def fail(expected, records, *args, **kwargs):
        records = list(records)
        state = records[0][2].get("state")
        matches = not failed and state == ("intent" if phase == "admit_after" else "complete")
        if matches and phase == "complete_before":
            failed.append(True)
            raise OSError("injected before completion")
        result = original(expected, records, *args, **kwargs)
        if matches:
            failed.append(True)
            raise OSError("injected lost commit return")
        return result
    monkeypatch.setattr(r["meta"], "conditional_put_and_delete", fail)
    params = {"profile": r["profiles"]["alpha"]}
    assert r["invoke"]("profile.lock", params, "runtime-lost-lock-key-0001")["error"]["code"] == "unavailable"
    replay = r["invoke"]("profile.lock", params, "runtime-lost-lock-key-0001")
    assert replay["ok"] and r["first"]._store_closed
    assert len(r["meta"].list("host_profile_operation")) == 1
    assert r["invoke"]("profile.select", {"profile": r["profiles"]["alpha"]}, "runtime-lost-lock-key-0001")["error"]["code"] == "idempotency_conflict"


def test_unlock_completion_failure_reuses_consumed_credential_without_second_open(runtime, monkeypatch):
    r = runtime
    profile = r["profiles"]["alpha"]
    assert r["invoke"]("profile.lock", {"profile": profile}, "runtime-lock-fault-key-0001")["ok"]
    credential = r["host"].issue_unlock_credential(r["grants"][0].caller, "alpha")
    original, failed = r["meta"].conditional_put_and_delete, []
    def fail(expected, records, *args, **kwargs):
        records = list(records)
        if not failed and records[0][2].get("state") == "complete":
            failed.append(True)
            raise OSError("injected completion failure after open")
        return original(expected, records, *args, **kwargs)
    monkeypatch.setattr(r["meta"], "conditional_put_and_delete", fail)
    params = {"profile": profile, "credential_handle": credential}
    assert r["invoke"]("profile.unlock", params, "runtime-unlock-fault-key-0001")["error"]["code"] == "unavailable"
    before = len(r["loads"])
    assert r["invoke"]("profile.unlock", params, "runtime-unlock-fault-key-0001")["ok"]
    assert len(r["loads"]) == before


def test_generic_completion_uncertainty_fences_new_lifecycle_identity(runtime, monkeypatch):
    r = runtime
    original = r["meta"].conditional_put_and_delete
    def fail_completion(expected, records, *args, **kwargs):
        records = list(records)
        if records and records[0][2].get("state") == "complete":
            raise OSError("completion custody remains in lifecycle")
        return original(expected, records, *args, **kwargs)
    monkeypatch.setattr(r["meta"], "conditional_put_and_delete", fail_completion)
    params = {"profile": r["profiles"]["alpha"]}
    assert r["invoke"]("profile.lock", params, "generic-fenced-original-key")["error"]["code"] == "unavailable"
    status = r["host"].lifecycle.query()
    target = {"profile": r["profiles"]["beta"]}
    assert r["invoke"]("profile.select", target, "generic-overtaking-new-key")["error"]["code"] == "unavailable"
    assert r["host"].lifecycle.query() == status
    monkeypatch.setattr(r["meta"], "conditional_put_and_delete", original)
    assert r["invoke"]("profile.lock", params, "generic-fenced-original-key")["ok"]
    assert r["invoke"]("profile.select", target, "generic-overtaking-new-key")["ok"]


@pytest.mark.parametrize("operation", ["profile.lock", "profile.unlock"])
def test_new_wrong_selected_target_is_rejected_before_admission(runtime, operation):
    r = runtime
    before = r["host"].lifecycle.query()
    params = {"profile": r["profiles"]["beta"]}
    if operation == "profile.unlock":
        params["credential_handle"] = r["host"].issue_unlock_credential(r["grants"][0].caller, "beta")
    assert r["invoke"](operation, params, "wrong-unselected-target-key")["error"]["code"] == "invalid_request"
    assert r["host"].lifecycle.query() == before
    assert not r["meta"].list("host_profile_operation")
    assert r["host"].profile_intents.ledger.slot() is None
    assert r["invoke"]("profile.lock", {"profile": r["profiles"]["alpha"]}, "later-valid-alpha-lock-key")["ok"]
    assert r["invoke"]("profile.select", {"profile": r["profiles"]["beta"]}, "later-valid-beta-select-key")["ok"]


def test_new_post_admission_grant_denial_records_no_effect_and_releases_slot(runtime, monkeypatch):
    r = runtime
    original = r["meta"].conditional_put_and_delete
    revoked = []
    original_grant = r["grants"][0]
    before = r["host"].lifecycle.query()
    def revoke_after_admission(expected, records, *args, **kwargs):
        records = list(records)
        result = original(expected, records, *args, **kwargs)
        if not revoked and records and records[0][2].get("state") == "intent":
            revoked.append(True)
            r["grants"][0] = replace(original_grant, permissions=frozenset())
        return result
    monkeypatch.setattr(r["meta"], "conditional_put_and_delete", revoke_after_admission)
    params = {"profile": r["profiles"]["alpha"]}
    assert r["invoke"]("profile.lock", params, "revoked-before-first-effect")["error"]["code"] == "forbidden"
    assert r["host"].lifecycle.query() == before and not r["first"]._store_closed
    assert r["meta"].list("host_profile_operation")[0]["state"] == "rejected_no_effect"
    assert r["host"].profile_intents.ledger.slot() is None
    r["grants"][0] = original_grant
    assert r["invoke"]("profile.lock", params, "revoked-before-first-effect")["error"]["code"] == "forbidden"
    assert r["invoke"]("profile.lock", params, "different-valid-effect-key")["ok"]


def test_later_pre_effect_denial_does_not_release_earlier_generic_uncertainty(runtime, monkeypatch):
    r = runtime
    original = r["meta"].conditional_put_and_delete
    original_grant = r["grants"][0]
    attempts = []
    def uncertain_then_revoke(expected, records, *args, **kwargs):
        records = list(records)
        result = original(expected, records, *args, **kwargs)
        if records and records[0][2].get("state") == "intent":
            attempts.append(True)
            if len(attempts) == 1:
                raise OSError("admission committed but return lost")
            r["grants"][0] = replace(original_grant, permissions=frozenset())
        return result
    monkeypatch.setattr(r["meta"], "conditional_put_and_delete", uncertain_then_revoke)
    params = {"profile": r["profiles"]["alpha"]}
    key = "earlier-ambiguous-admission"
    assert r["invoke"]("profile.lock", params, key)["error"]["code"] == "unavailable"
    assert r["invoke"]("profile.lock", params, key)["error"]["code"] == "forbidden"
    assert r["meta"].list("host_profile_operation")[0]["state"] == "intent"
    assert r["host"].profile_intents.ledger.slot() is not None
    r["grants"][0] = original_grant
    monkeypatch.setattr(r["meta"], "conditional_put_and_delete", original)
    assert r["invoke"]("profile.select", {"profile": r["profiles"]["beta"]}, "must-not-discard-uncertainty")["error"]["code"] == "unavailable"
    assert r["invoke"]("profile.lock", params, key)["ok"]


def test_superseded_or_old_host_epoch_receipt_never_reopens(runtime):
    r = runtime
    profile = r["profiles"]["alpha"]
    assert r["invoke"]("profile.lock", {"profile": profile}, "runtime-old-key-0001")["ok"]
    before = len(r["loads"])
    replacement = r["build"](None)
    stream = replacement.bind(lambda: r["grants"][0])
    try:
        assert r["invoke"]("runtime.capabilities", endpoint=stream)["ok"]
        assert r["invoke"]("profile.lock", {"profile": profile}, "runtime-old-key-0001", endpoint=stream)["error"]["code"] == "resync_required"
        assert len(r["loads"]) == before
    finally:
        stream.close()


@pytest.mark.parametrize("language", ["python", "typescript"])
@pytest.mark.parametrize("selected", ["alpha", "beta"])
def test_actual_pinned_old_sdk_negotiates_runtime_host_capabilities_and_enqueues(runtime, pinned_install, language, selected):
    r = runtime
    if selected == "beta":
        profile = r["profiles"]["beta"]
        assert r["invoke"]("profile.select", {"profile": profile}, "runtime-old-sdk-select-key-0001")["ok"]
        credential = r["host"].issue_unlock_credential(r["grants"][0].caller, "beta")
        assert r["invoke"]("profile.unlock", {"profile": profile, "credential_handle": credential}, "runtime-old-sdk-unlock-key-0001")["ok"]
    stream = r["host"].bind(lambda: r["grants"][0])
    report = run_consumer(old_consumer(pinned_install, language), None, "--old", session=stream)
    assert report["accepted"] and report["api_minor"] == 1
    assert len(r["host"].lifecycle.active.store.list("message")) == 1
    assert not r["host"].lifecycle.active._store_closed


def test_credential_cannot_cross_an_intervening_lifecycle_revision(runtime):
    r = runtime
    credential = r["host"].issue_unlock_credential(r["grants"][0].caller, "alpha")
    profile = r["profiles"]["alpha"]
    assert r["invoke"]("profile.lock", {"profile": profile}, "runtime-credential-revision-key-0001")["ok"]
    assert r["invoke"]("profile.unlock", {"profile": profile, "credential_handle": credential}, "runtime-credential-revision-key-0002")["error"]["code"] == "forbidden"


def test_deferred_lock_detaches_before_worker_drain_and_reconcile_never_opens(runtime, monkeypatch):
    r = runtime
    original = r["first"].close
    monkeypatch.setattr(r["first"], "close", lambda: None)
    before = len(r["loads"])
    result = r["invoke"]("profile.lock", {"profile": r["profiles"]["alpha"]}, "runtime-deferred-key-0001")
    assert result["ok"] and result["result"]["profiles"][0]["state"] == "retiring"
    assert not r["first"]._store_closed and r["first"].store._key is not None
    assert r["stream"]._session._inner is None and r["published"][-1] is None
    monkeypatch.setattr(r["first"], "close", original)
    r["host"].lifecycle.reconcile()
    assert r["first"]._store_closed and r["first"].store._key is None
    assert r["host"].lifecycle.active is None and len(r["loads"]) == before


def test_catalog_and_original_admission_survive_actual_catalog_store_reopen(runtime):
    r = runtime
    profile = r["profiles"]["beta"]
    assert r["invoke"]("profile.select", {"profile": profile}, "runtime-persist-selection-key-0001")["ok"]
    r["stream"].close()
    r["meta"].close()
    catalog = VaultStore(r["meta_root"], r["meta_key"], allow_unprotected_for_tests=True)
    try:
        replacement = r["build"](None, catalog=catalog)
        assert replacement.lifecycle.query()["selected_profile"] == "beta"
        stream = replacement.bind(lambda: r["grants"][0])
        try:
            assert r["invoke"]("runtime.capabilities", endpoint=stream)["ok"]
            assert r["invoke"]("profile.catalog", endpoint=stream)["result"]["selected_profile"] == profile
            before = len(r["loads"])
            assert r["invoke"]("profile.select", {"profile": profile}, "runtime-persist-selection-key-0001", endpoint=stream)["error"]["code"] == "resync_required"
            assert len(r["loads"]) == before
            assert catalog.get("host_profile", "alpha")["handle_key"] == r["handles"]["alpha"].hex()
            assert catalog.get("host_profile", "alpha")["handle_key"] != r["keys"]["alpha"].hex()
        finally:
            stream.close()
    finally:
        catalog.close()


def test_capacity_refuses_new_identity_before_retiring_active_profile(runtime, monkeypatch):
    from mesh_chat.core_api import runtime_host
    r = runtime
    monkeypatch.setattr(runtime_host, "MAX_CALLER_OPERATIONS", 1)
    profile = r["profiles"]["alpha"]
    assert r["invoke"]("profile.select", {"profile": profile}, "runtime-capacity-key-0001")["ok"]
    assert r["invoke"]("profile.lock", {"profile": profile}, "runtime-capacity-key-0002")["error"]["code"] == "resource_exhausted"
    assert r["host"].lifecycle.active is r["first"] and not r["first"]._store_closed


def test_wrong_key_slot_opener_is_retained_then_drained_without_publication(runtime):
    r = runtime
    assert r["invoke"]("profile.select", {"profile": r["profiles"]["beta"]}, "runtime-wrong-slot-select-key-0001")["ok"]
    original = r["host"].profiles
    registered = (original["alpha"], replace(original["beta"], open=original["alpha"].open))
    host = r["build"](None, registered=registered)
    stream = host.bind(lambda: r["grants"][0])
    try:
        assert r["invoke"]("runtime.capabilities", endpoint=stream)["ok"]
        credential = host.issue_unlock_credential(r["grants"][0].caller, "beta")
        result = r["invoke"]("profile.unlock", {"profile": r["profiles"]["beta"], "credential_handle": credential}, "runtime-wrong-slot-open-key-0001", endpoint=stream)
        assert result["error"]["code"] == "unavailable"
        wrong = r["opened"][-1]
        assert host.lifecycle.active is None and wrong._shutdown.is_set()
        before = len(r["loads"])
        host.lifecycle.reconcile()
        assert wrong._store_closed and wrong.store._key is None
        assert len(r["loads"]) == before
    finally:
        stream.close()


def test_installed_sdk_locks_and_unlocks_through_runtime_host_without_storing_vault_keys(runtime, installed_consumer):
    r = runtime
    locked = run_consumer(installed_consumer, None, "--exercise-profile-lock", session=r["host"].bind(lambda: r["grants"][0]))
    assert locked["locked"] and locked["sdk_only"]
    assert r["first"]._store_closed and r["first"].store._key is None
    language, work, command, env, digest = installed_consumer
    credential = r["host"].issue_unlock_credential(r["grants"][0].caller, "alpha")
    before = len(r["loads"])
    installed = language, work, command, {**env, "MESH_CORE_TEST_UNLOCK_CREDENTIAL": credential}, digest
    unlocked = run_consumer(installed, None, "--exercise-profile-unlock", session=r["host"].bind(lambda: r["grants"][0]))
    assert unlocked["unlocked"] and unlocked["sdk_only"]
    assert len(r["loads"]) == before + 1


def test_trusted_fresh_slot_bootstrap_and_lost_catalog_label_commit_do_not_duplicate_identity(runtime, tmp_path, monkeypatch):
    r = runtime
    key = os.urandom(32)
    def open_blank():
        root = tmp_path / "new-profile"
        service = MeshChatService(VaultStore(root, key, allow_unprotected_for_tests=True), root, lambda _: None)
        r["opened"].append(service)
        return service
    blank = open_blank()
    derived = bytes.fromhex(blank.store.opaque_id("core-api-handle-key", "v1"))
    blank.close()
    meta = VaultStore(tmp_path / "new-host-catalog", os.urandom(32), allow_unprotected_for_tests=True)
    try:
        host = CoreRuntimeHost(meta, (RegisteredProfile("new", "New profile", derived, open_blank),),
            selected="new", publish=lambda _: None, credential_authorizer=lambda *_: True)
        grant = Grant("application-owner", r["grants"][0].permissions, ("new",))
        stream = host.bind(lambda: grant, private_profile_bootstrap=True)
        try:
            caps = r["invoke"]("runtime.capabilities", endpoint=stream)
            profile = caps["result"]["profiles"][0]
            credential = host.issue_unlock_credential(grant.caller, "new")
            assert r["invoke"]("profile.unlock", {"profile": profile, "credential_handle": credential}, "runtime-new-unlock-key-0001", endpoint=stream)["ok"]
            original, failed = meta.conditional_put_and_delete, []
            def fail(expected, records, *args, **kwargs):
                records = list(records)
                if records[0][0] == "host_profile" and not failed:
                    failed.append(True)
                    raise OSError("injected label commit failure after profile creation")
                return original(expected, records, *args, **kwargs)
            monkeypatch.setattr(meta, "conditional_put_and_delete", fail)
            params = {"display_name": "Created profile"}
            assert r["invoke"]("profile.create", params, "runtime-new-create-key-0001", endpoint=stream)["error"]["code"] == "unavailable"
            service = host.lifecycle.active
            identity = service.store.get("identity", "local")
            assert r["invoke"]("profile.create", params, "runtime-new-create-key-0001", endpoint=stream)["ok"]
            assert service.store.get("identity", "local") == identity
            assert len(service.store.list("workspace_operation")) == 1
            assert r["invoke"]("profile.catalog", endpoint=stream)["result"]["profiles"][0]["display_name"] == "Created profile"
            assert r["invoke"]("profile.lock", {"profile": profile}, "runtime-new-lock-key-0001", endpoint=stream)["ok"]
            assert service.store._key is None
        finally:
            stream.close()
    finally:
        meta.close()


def test_persisted_selection_cannot_rebind_other_active_vault_under_its_handles(runtime):
    r = runtime
    r["meta"].put("host_profile_catalog", "selection", {"selected": "beta"})
    before = r["meta"].list("host_profile"), list(r["published"]), len(r["loads"])
    with pytest.raises(ValueError, match="persisted handle authority"):
        r["build"](r["first"], selected="alpha")
    assert (r["meta"].list("host_profile"), r["published"], len(r["loads"])) == before
    assert not r["first"]._store_closed
    assert r["first"].store.get("profile", "local")["display_name"] == "alpha"


def test_active_authority_matches_final_persisted_selection_not_startup_default(runtime):
    r = runtime
    assert r["invoke"]("profile.select", {"profile": r["profiles"]["beta"]}, "runtime-persisted-beta-key-0001")["ok"]
    active_beta = r["host"].profiles["beta"].open()
    replacement = r["build"](active_beta, selected="alpha")
    stream = replacement.bind(lambda: r["grants"][0])
    try:
        assert r["invoke"]("runtime.capabilities", endpoint=stream)["ok"]
        assert r["invoke"]("profile.query", {"profile": r["profiles"]["beta"]}, endpoint=stream)["result"]["display_name"] == "beta"
        assert r["invoke"]("profile.query", {"profile": r["profiles"]["alpha"]}, endpoint=stream)["error"]["code"] == "forbidden"
    finally:
        stream.close()


def test_constructor_selection_change_before_commit_refuses_stale_active_binding(runtime, monkeypatch):
    r = runtime
    original = r["meta"].conditional_put_and_delete
    def race(expected, records, *args, **kwargs):
        r["meta"].put("host_profile_catalog", "selection", {"selected": "beta"})
        return original(expected, records, *args, **kwargs)
    monkeypatch.setattr(r["meta"], "conditional_put_and_delete", race)
    with pytest.raises(RecordConflict):
        r["build"](r["first"], selected="alpha")
    assert not r["published"]
    assert not r["first"]._store_closed


@pytest.mark.parametrize("fault", ["storage_failure", "malformed_key", "missing_store"])
def test_post_open_authority_check_failure_retains_exact_service_until_drain(runtime, monkeypatch, fault):
    r = runtime
    profile = r["profiles"]["alpha"]
    assert r["invoke"]("profile.lock", {"profile": profile}, "runtime-authority-open-lock-key-0001")["ok"]
    original_registration = r["host"].profiles["alpha"]
    acquired = []
    def opener():
        service = original_registration.open()
        store = service.store
        acquired.append((service, service.close, store, store.opaque_id))
        def fail(*_):
            if fault == "storage_failure":
                raise StorageUnavailable("injected authority storage failure")
            return "malformed"
        if fault == "missing_store":
            monkeypatch.setattr(service, "store", None)
        else:
            monkeypatch.setattr(service.store, "opaque_id", fail)
        monkeypatch.setattr(service, "close", lambda: None)
        return service
    host = r["build"](None, registered=(replace(original_registration, open=opener), r["host"].profiles["beta"]))
    stream = host.bind(lambda: r["grants"][0])
    try:
        assert r["invoke"]("runtime.capabilities", endpoint=stream)["ok"]
        credential = host.issue_unlock_credential(r["grants"][0].caller, "alpha")
        params = {"profile": profile, "credential_handle": credential}
        assert r["invoke"]("profile.unlock", params, "runtime-authority-open-key-0001", endpoint=stream)["error"]["code"] == "unavailable"
        service, close, store, opaque = acquired[0]
        assert host.lifecycle._retiring is service and host.lifecycle.active is None
        assert service._shutdown.is_set() and not service._store_closed
        credential = host.issue_unlock_credential(r["grants"][0].caller, "alpha")
        pending = r["invoke"]("profile.unlock", {"profile": profile, "credential_handle": credential}, "runtime-authority-open-key-0001", endpoint=stream)
        assert pending["ok"] and pending["result"]["profiles"][0]["state"] == "retiring"
        assert len(acquired) == 1
        monkeypatch.setattr(service, "store", store)
        monkeypatch.setattr(store, "opaque_id", opaque)
        monkeypatch.setattr(service, "close", close)
        host.lifecycle.reconcile()
        assert service._store_closed and service.store._key is None
        assert len(acquired) == 1 and host.lifecycle.active is None
    finally:
        stream.close()


def test_malformed_opener_quarantine_prevents_a_second_unknown_open(runtime):
    r = runtime
    profile = r["profiles"]["alpha"]
    assert r["invoke"]("profile.lock", {"profile": profile}, "runtime-malformed-lock-key-0001")["ok"]
    calls = []
    original = r["host"].profiles["alpha"]
    host = r["build"](None, registered=(replace(original, open=lambda: calls.append(True)), r["host"].profiles["beta"]))
    stream = host.bind(lambda: r["grants"][0])
    try:
        assert r["invoke"]("runtime.capabilities", endpoint=stream)["ok"]
        for _ in range(2):
            credential = host.issue_unlock_credential(r["grants"][0].caller, "alpha")
            result = r["invoke"]("profile.unlock", {"profile": profile, "credential_handle": credential}, "runtime-malformed-open-key-0001", endpoint=stream)
            assert result["error"]["code"] == "unavailable"
        assert calls == [True] and host.lifecycle.query()["state"] == "retiring"
    finally:
        stream.close()
