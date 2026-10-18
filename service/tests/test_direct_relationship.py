import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
import RNS

from mesh_chat.direct_binding import BindingAuthority, accept_binding, create_binding
from mesh_chat.direct_relationship import accept_relationship, record_success, relationship_id
from mesh_chat.errors import IdentityMismatch, ValidationError
from mesh_chat.vault import VaultStore
from mesh_chat.workspace_protocol import _destination_for


@pytest.fixture
def pair():
    issuer, audience = RNS.Identity(), RNS.Identity()
    authority = BindingAuthority(issuer.get_public_key(), _destination_for(audience), {
        "kind": "workspace", "workspace_id": str(uuid.uuid4()),
        "issuer_device_id": str(uuid.uuid4()), "audience_device_id": str(uuid.uuid4()),
    }, 2000, b"c" * 32)
    def document(generation=1, certificate=b"certificate", **kwargs):
        return create_binding(issuer, authority, certificate, session_id=str(uuid.uuid4()),
            challenge=authority.challenge, generation=generation, candidates=[{
                "host": "8.8.8.8", "port": 12345, "expires_at": 2000,
            }], issued_at=1000, expires_at=2000, version=2, **kwargs)
    return authority, document


def accept(store, authority, raw, certificate=b"certificate", **kwargs):
    return accept_relationship(store, raw, authority, certificate,
        load_authority=kwargs.get("load", lambda: authority), clock=lambda: kwargs.get("now", 1100))


def test_restart_rotation_preserves_evidence_and_replay_floor(pair, tmp_path):
    authority, document = pair
    raw = document()
    with VaultStore(tmp_path, b"k" * 32, allow_unprotected_for_tests=True) as store:
        accepted = accept(store, authority, raw)
        record_success(store, authority, accepted, load_authority=lambda: authority, clock=lambda: 1101)
        assert accept(store, authority, raw) == accepted
        saved = store.get("direct_relationship", relationship_id(store, authority))
        assert saved["last_success"]["at"] == 1101
        assert set(saved) == {"version", "scope", "issuer", "audience", "last_success", "accepted",
                              "binding", "certificate", "candidates", "expires_at"}
    with VaultStore(tmp_path, b"k" * 32, allow_unprotected_for_tests=True) as store:
        fresh = accept(store, authority, document(2, b"fresh-key"), b"fresh-key")
        assert fresh.generation == 2
        with pytest.raises(ValidationError, match="stale"):
            accept(store, authority, raw)
        with pytest.raises(ValidationError, match="retired"):
            record_success(store, authority, accepted, load_authority=lambda: authority, clock=lambda: 1102)
        saved = store.get("direct_relationship", relationship_id(store, authority))
        assert saved["last_success"]["generation"] == 1
        assert saved["certificate"] == b"fresh-key".hex()


def test_upgrade_uses_existing_phase2_floor(pair, tmp_path):
    authority, document = pair
    raw = document(4)
    with VaultStore(tmp_path, b"k" * 32, allow_unprotected_for_tests=True) as store:
        accept_binding(store, raw, authority, b"certificate", load_authority=lambda: authority, clock=lambda: 1100)
        with pytest.raises(ValidationError):
            accept(store, authority, document(3))
        assert store.list("direct_relationship") == []
        assert accept(store, authority, raw).generation == 4


@pytest.mark.parametrize("failure", ["seal", "commit"])
def test_atomic_failure_cannot_split_replay_and_relationship(pair, tmp_path, monkeypatch, failure):
    authority, document = pair
    with VaultStore(tmp_path, b"k" * 32, allow_unprotected_for_tests=True) as store:
        original_seal, database = store._seal, store._db
        def seal(kind, *args):
            if kind == "direct_relationship":
                raise OSError("disk failure")
            return original_seal(kind, *args)
        class FailCommit:
            def execute(self, statement, *args):
                if statement == "COMMIT":
                    raise OSError("disk failure")
                return database.execute(statement, *args)
            def executemany(self, *args):
                return database.executemany(*args)
        with monkeypatch.context() as m:
            if failure == "seal":
                m.setattr(store, "_seal", seal)
            else:
                m.setattr(store, "_db", FailCommit())
            with pytest.raises(OSError, match="disk failure"):
                accept(store, authority, document())
        assert store.list("direct_binding") == store.list("direct_relationship") == []
        assert accept(store, authority, document()).generation == 1


def test_concurrent_conflicting_updates_have_one_durable_winner(pair, tmp_path):
    authority, document = pair
    with VaultStore(tmp_path, b"k" * 32, allow_unprotected_for_tests=True) as store:
        def attempt(raw):
            try:
                return accept(store, authority, raw)
            except ValidationError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, [document(), document()]))
        winners = [result for result in results if result]
        assert len(winners) == 1
        assert store.list("direct_binding")[0] == store.list("direct_relationship")[0]["accepted"]


@pytest.mark.parametrize("change", ["identity", "audience", "scope", "revoked", "expiry", "challenge"])
def test_current_authority_reloaded_before_persistence(pair, tmp_path, change):
    authority, document = pair
    current = {
        "identity": replace(authority, issuer_public_identity=RNS.Identity().get_public_key()),
        "audience": replace(authority, audience_destination=b"x" * 16),
        "scope": replace(authority, scope={**authority.scope, "workspace_id": str(uuid.uuid4())}),
        "expiry": replace(authority, expires_at=1099),
        "challenge": replace(authority, challenge=b"x" * 32),
    }.get(change)
    def load():
        if change == "revoked":
            raise ValidationError("revoked")
        return current
    with VaultStore(tmp_path, b"k" * 32, allow_unprotected_for_tests=True) as store:
        with pytest.raises((ValidationError, IdentityMismatch)):
            accept(store, authority, document(), load=load)
        assert store.list("direct_relationship") == store.list("direct_binding") == []


def test_expired_and_wrong_certificate_fail_without_writes(pair, tmp_path):
    authority, document = pair
    with VaultStore(tmp_path, b"k" * 32, allow_unprotected_for_tests=True) as store:
        for certificate, now in [(b"wrong", 1100), (b"certificate", 2000)]:
            with pytest.raises((ValidationError, IdentityMismatch)):
                accept(store, authority, document(), certificate, now=now)
        assert store.list("direct_relationship") == []


def test_invitation_cannot_become_durable_membership(pair, tmp_path):
    authority, document = pair
    pending = replace(authority, scope={"kind": "invitation", "digest": "ab" * 32, "expires_at": 2000})
    with VaultStore(tmp_path, b"k" * 32, allow_unprotected_for_tests=True) as store:
        with pytest.raises(ValidationError, match="membership"):
            accept(store, pending, document())
        assert store.list("direct_relationship") == []


def test_success_is_idempotent_and_expiry_is_not_live_evidence(pair, tmp_path):
    authority, document = pair
    with VaultStore(tmp_path, b"k" * 32, allow_unprotected_for_tests=True) as store:
        accepted = accept(store, authority, document())
        first = record_success(store, authority, accepted, load_authority=lambda: authority, clock=lambda: 1100)
        second = record_success(store, authority, accepted, load_authority=lambda: authority, clock=lambda: 1200)
        assert first == second
        with pytest.raises(ValidationError, match="retired"):
            record_success(store, authority, accepted, load_authority=lambda: authority, clock=lambda: 2000)


def test_newer_legacy_floor_retires_success_callback(pair, tmp_path):
    authority, document = pair
    with VaultStore(tmp_path, b"k" * 32, allow_unprotected_for_tests=True) as store:
        accepted = accept(store, authority, document())
        accept_binding(store, document(2), authority, b"certificate",
                       load_authority=lambda: authority, clock=lambda: 1100)
        with pytest.raises(ValidationError, match="retired"):
            record_success(store, authority, accepted, load_authority=lambda: authority, clock=lambda: 1101)


def test_unknown_record_version_cannot_be_overwritten(pair, tmp_path):
    authority, document = pair
    with VaultStore(tmp_path, b"k" * 32, allow_unprotected_for_tests=True) as store:
        accept(store, authority, document())
        identifier = relationship_id(store, authority)
        record = store.get("direct_relationship", identifier)
        store.put("direct_relationship", identifier, {**record, "version": 2})
        with pytest.raises(ValidationError, match="version"):
            accept(store, authority, document(2))
        assert store.list("direct_binding")[0]["generation"] == 1


def test_sqlite_contains_no_plaintext_relationship_material(pair, tmp_path):
    authority, document = pair
    raw = document()
    with VaultStore(tmp_path, b"k" * 32, allow_unprotected_for_tests=True) as store:
        accept(store, authority, raw)
        rows = store._db.execute("SELECT record_id, sealed FROM records WHERE kind='direct_relationship'").fetchall()
        assert len(rows) == 1
        identifier, ciphertext = rows[0]
        assert len(identifier) == 64
        for secret in [authority.scope["workspace_id"], authority.issuer_public_identity.hex(), "8.8.8.8", raw]:
            assert secret.encode() not in bytes(ciphertext)


def test_atomic_mutation_rejects_key_substitution_and_duplicates(tmp_path):
    with VaultStore(tmp_path, b"k" * 32, allow_unprotected_for_tests=True) as store:
        with pytest.raises(ValidationError):
            store.update_records((("test", "one"),), lambda _: {("test", "two"): {}})
        with pytest.raises(ValidationError):
            store.update_records((("test", "one"), ("test", "one")), lambda _: {})
        assert store.list("test") == []
