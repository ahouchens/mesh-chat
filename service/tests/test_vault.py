from __future__ import annotations

import os
import threading
from types import SimpleNamespace

import pytest

from mesh_chat.errors import ProfileInUse, StorageUnavailable
from mesh_chat import vault
from mesh_chat.vault import ProfileLock, VaultStore


def test_transaction_begin_failure_releases_the_vault_lock() -> None:
    begin_error = RuntimeError("begin failed")

    class FailingBeginDatabase:
        def execute(self, statement: str) -> None:
            assert statement == "BEGIN IMMEDIATE"
            raise begin_error

    lock = threading.Lock()
    transaction = VaultStore._Transaction(
        SimpleNamespace(_lock=lock, _db=FailingBeginDatabase())
    )

    with pytest.raises(RuntimeError) as caught:
        with transaction:
            pytest.fail("a failed BEGIN must not enter the transaction body")

    assert caught.value is begin_error
    assert lock.acquire(blocking=False)
    lock.release()


def test_transaction_commit_failure_rolls_back_and_leaves_store_usable(tmp_path) -> None:
    commit_error = RuntimeError("commit failed")
    with VaultStore(
        tmp_path, os.urandom(32), allow_unprotected_for_tests=True
    ) as store:
        database = store._db

        class FailFirstCommit:
            def __init__(self) -> None:
                self.failed = False
                self.statements: list[str] = []

            def execute(self, statement: str, *args, **kwargs):
                self.statements.append(statement)
                if statement == "COMMIT" and not self.failed:
                    self.failed = True
                    raise commit_error
                return database.execute(statement, *args, **kwargs)

            def __getattr__(self, name: str):
                return getattr(database, name)

        wrapped = FailFirstCommit()
        store._db = wrapped

        with pytest.raises(RuntimeError) as caught:
            store.put("message", "rolled-back", {"text": "must not commit"})

        assert caught.value is commit_error
        assert wrapped.statements[-2:] == ["COMMIT", "ROLLBACK"]
        assert database.in_transaction is False
        assert store.get("message", "rolled-back") is None

        store.put("message", "after-recovery", {"text": "committed"})
        assert store.get("message", "after-recovery") == {"text": "committed"}


def test_sensitive_values_are_not_plaintext_on_disk(tmp_path) -> None:
    secret = "a uniquely searchable private message"
    key = os.urandom(32)
    with VaultStore(tmp_path, key, allow_unprotected_for_tests=True) as store:
        store.put("message", "one", {"text": secret, "contact": "Alex"})
        assert store.get("message", "one") == {"text": secret, "contact": "Alex"}

    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert secret.encode() not in path.read_bytes()


def test_wrong_key_cannot_open_record(tmp_path) -> None:
    first_key = os.urandom(32)
    with VaultStore(tmp_path, first_key, allow_unprotected_for_tests=True) as store:
        store.put("identity", "local", {"private_key": "super-secret"})
    with VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True) as store:
        with pytest.raises(StorageUnavailable):
            store.get("identity", "local")


def test_duplicate_command_response_is_stable(tmp_path) -> None:
    with VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True) as store:
        response = {"ok": True, "result": {"id": "logical-message"}}
        store.remember_command("command-1", response)
        store.remember_command("command-1", {"ok": False})
        assert store.command_response("command-1") == response


def test_vault_commits_writes_and_secure_deletions_together(tmp_path) -> None:
    with VaultStore(
        tmp_path, os.urandom(32), allow_unprotected_for_tests=True
    ) as store:
        store.put("message", "old", {"text": "remove me"})
        store.remember_command(
            "old-send", {"ok": True, "result": {"text": "remove me"}}
        )

        store.put_and_delete(
            [("conversation_hidden", "direct:alex", {"id": "direct:alex"})],
            [("message", "old")],
            redact_command_cache=True,
        )

        assert store.get("message", "old") is None
        assert store.get("conversation_hidden", "direct:alex") == {
            "id": "direct:alex"
        }
        assert store.command_response("old-send") == {
            "ok": False,
            "error": {
                "code": "command_result_deleted",
                "message": "Cached command result was deleted locally",
            },
        }


def test_command_cache_is_bounded_by_most_recent_rows(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(vault, "COMMAND_CACHE_MAX_ROWS", 3)
    monkeypatch.setattr(vault, "COMMAND_CACHE_MAX_AGE_SECONDS", 10_000)
    with VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True) as store:
        for index in range(5):
            store.remember_command(
                f"command-{index}", {"ok": True, "result": {"index": index}}
            )

        assert store.command_response("command-0") is None
        assert store.command_response("command-1") is None
        assert store.command_response("command-2") is not None
        assert store.command_response("command-3") is not None
        assert store.command_response("command-4") is not None


def test_opening_existing_profile_prunes_command_cache(monkeypatch, tmp_path) -> None:
    key = os.urandom(32)
    monkeypatch.setattr(vault, "COMMAND_CACHE_MAX_ROWS", 10)
    monkeypatch.setattr(vault, "COMMAND_CACHE_MAX_AGE_SECONDS", 10_000)
    with VaultStore(tmp_path, key, allow_unprotected_for_tests=True) as store:
        for index in range(5):
            store.remember_command(
                f"command-{index}", {"ok": True, "result": {"index": index}}
            )
        with store._transaction():
            for index in range(5):
                store._db.execute(
                    "UPDATE commands SET created_at=? WHERE command_id=?",
                    (100.0 + index, f"command-{index}"),
                )

    monkeypatch.setattr(vault, "COMMAND_CACHE_MAX_ROWS", 3)
    monkeypatch.setattr(vault, "COMMAND_CACHE_MAX_AGE_SECONDS", 10**12)
    with VaultStore(tmp_path, key, allow_unprotected_for_tests=True) as store:
        assert store.command_response("command-0") is None
        assert store.command_response("command-1") is None
        assert store.command_response("command-2") is not None
        assert store.command_response("command-3") is not None
        assert store.command_response("command-4") is not None


def test_profile_lock_contention_has_a_distinct_error(tmp_path) -> None:
    first = ProfileLock(tmp_path / ".profile.lock")
    try:
        with pytest.raises(ProfileInUse) as caught:
            ProfileLock(tmp_path / ".profile.lock")
        assert caught.value.code == "profile_in_use"
        assert not isinstance(caught.value, StorageUnavailable)
    finally:
        first.close()


def test_macos_adapter_accepts_only_verified_filevault(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(vault.sys, "platform", "darwin")
    monkeypatch.setattr(vault, "_macos_filevault_protects", lambda _: True)
    vault.protect_workspace(tmp_path / "protected")

    monkeypatch.setattr(vault, "_macos_filevault_protects", lambda _: False)
    with pytest.raises(StorageUnavailable, match="FileVault"):
        vault.protect_workspace(tmp_path / "unprotected")


def test_linux_adapter_accepts_only_verified_encryption(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(vault.sys, "platform", "linux")
    monkeypatch.setattr(vault, "_linux_encrypted_workspace", lambda _: True)
    vault.protect_workspace(tmp_path / "protected")

    monkeypatch.setattr(vault, "_linux_encrypted_workspace", lambda _: False)
    with pytest.raises(StorageUnavailable, match="fscrypt.*dm-crypt/LUKS"):
        vault.protect_workspace(tmp_path / "unprotected")


@pytest.mark.skipif(os.name == "nt", reason="Windows paths cannot model /sys major:minor nodes")
def test_linux_dm_crypt_device_is_detected(monkeypatch, tmp_path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setattr(vault.os, "major", lambda _: 8, raising=False)
    monkeypatch.setattr(vault.os, "minor", lambda _: 1, raising=False)
    device_id = "8:1"
    sys_devices = tmp_path / "sys-devices"
    dm = sys_devices / device_id / "dm"
    dm.mkdir(parents=True)
    (dm / "uuid").write_text("CRYPT-LUKS2-test-device", encoding="ascii")

    assert vault._linux_dm_crypt_protects(profile, sys_devices) is True


def test_linux_encrypted_mount_type_is_detected(monkeypatch, tmp_path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setattr(vault.os, "major", lambda _: 8, raising=False)
    monkeypatch.setattr(vault.os, "minor", lambda _: 1, raising=False)
    device_id = "8:1"
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        f"42 21 {device_id} / /home/user rw - fuse.gocryptfs cipher rw\n",
        encoding="utf-8",
    )

    assert vault._linux_mount_type(profile, mountinfo) == "fuse.gocryptfs"


def test_unknown_platform_still_fails_closed(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(vault.sys, "platform", "plan9")
    with pytest.raises(StorageUnavailable, match="No verified"):
        vault.protect_workspace(tmp_path / "profile")
