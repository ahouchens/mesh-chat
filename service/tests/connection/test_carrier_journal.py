"""Protected recovery bookkeeping cannot revive authority after an ABA change."""
from dataclasses import replace
import os

import pytest

from mesh_chat.carrier_journal import CarrierBinding, CarrierJournal
from mesh_chat.errors import ContactNotApproved, NativeUnavailable, StorageUnavailable
from mesh_chat.vault import VaultStore


def binding(index=0, workspace=None):
    return CarrierBinding(resource=f"native-{index}", adapter_epoch="a" * 32,
                          profile_id=f"profile-{index}", contact_id=f"contact-{index}",
                          scope="workspace" if workspace else "contact", workspace_id=workspace,
                          local_device="local", remote_device="remote", peer_destination="b" * 32,
                          ice_policy="relay", local_type="offer", local_hash="c" * 64,
                          remote_hash="d" * 64)


@pytest.fixture
def journal(tmp_path):
    with VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True) as store:
        yield CarrierJournal(store), store


def test_encrypted_bindings_survive_vault_reopen_without_claiming_readiness(tmp_path):
    key = os.urandom(32)
    with VaultStore(tmp_path, key, allow_unprotected_for_tests=True) as store:
        journal = CarrierJournal(store)
        revision = journal.revision()
        journal.save(binding(), revision)
    assert b"peer_destination" not in (tmp_path / "mesh-chat.vault").read_bytes()
    with VaultStore(tmp_path, key, allow_unprotected_for_tests=True) as store:
        journal = CarrierJournal(store)
        assert journal.bindings() == (binding(),)
        assert journal.revision() == revision


@pytest.mark.parametrize("authority", ["profile-0", "contact-0", ("workspace", "team")])
def test_authority_invalidation_survives_restart_and_preserves_other_scopes(journal, authority):
    journal, store = journal
    revision = journal.revision()
    journal.save(binding(workspace="team"), revision)
    journal.save(binding(1, workspace="other"), revision)
    journal.invalidate(authority)
    reopened = CarrierJournal(store)
    assert reopened.bindings() == (binding(1, workspace="other"),)
    with pytest.raises(ContactNotApproved):
        reopened.save(binding(workspace="team"), revision)


def test_exact_retirement_cannot_erase_another_resource(journal):
    journal, _ = journal
    revision = journal.revision()
    for index in range(2): journal.save(binding(index), revision)
    journal.retire("native-0")
    assert journal.bindings() == (binding(1),)
    with pytest.raises(ContactNotApproved): journal.save(binding(), revision)


def test_global_invalidation_blocks_pending_writes_even_before_first_record(journal):
    journal, _ = journal
    revision = journal.revision()
    journal.invalidate()
    with pytest.raises(ContactNotApproved): journal.save(binding(), revision)
    assert not journal.bindings()


def test_binding_capacity_and_resource_identity_are_not_overwritten(journal):
    journal, _ = journal
    revision = journal.revision()
    for index in range(16): journal.save(binding(index), revision)
    journal.save(binding(), revision)  # Exact replay is idempotent.
    with pytest.raises(NativeUnavailable): journal.save(binding(16), revision)
    with pytest.raises(ContactNotApproved): journal.save(replace(binding(), remote_device="replacement"), revision)
    assert len(journal.bindings()) == 16


def test_failed_checkpoint_does_not_claim_durable_acceptance(journal, monkeypatch):
    journal, store = journal
    revision = journal.revision()
    def fail(*_): raise OSError("sealed write failed")
    monkeypatch.setattr(store, "_seal", fail)
    with pytest.raises(OSError): journal.save(binding(), revision)
    assert not journal.bindings()


def test_new_private_adapter_incarnation_replaces_only_obsolete_host_records(journal):
    journal, _ = journal
    revision = journal.revision()
    for index in range(16): journal.save(binding(index), revision)
    replacement = replace(binding(17), adapter_epoch="e" * 32)
    journal.save(replacement, revision)
    assert journal.bindings() == (replacement,)


@pytest.mark.parametrize("value", [{"v": 2}, {"v": True}, {"v": 1, "revision": "a" * 32, "bindings": [{"connected": True}]}])
def test_unknown_or_malformed_records_fail_closed(journal, value):
    journal, store = journal
    store.put("native_carrier_recovery", "current", value)
    with pytest.raises(StorageUnavailable): journal.bindings()
