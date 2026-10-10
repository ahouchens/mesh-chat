from __future__ import annotations

import ctypes
import array
import base64
import errno
import hashlib
import hmac
import json
import os
import sqlite3
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterable

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:  # Mobile packages intentionally use RNS's pure-Python provider.
    AESGCM = None  # type: ignore[assignment,misc]

from .errors import ProfileInUse, StorageUnavailable, ValidationError

FILE_ATTRIBUTE_ENCRYPTED = 0x4000
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
SCHEMA_VERSION = 1
COMMAND_CACHE_MAX_ROWS = 512
COMMAND_CACHE_MAX_AGE_SECONDS = 8 * 24 * 60 * 60
REDACTED_COMMAND_RESPONSE = {
    "ok": False,
    "error": {
        "code": "command_result_deleted",
        "message": "Cached command result was deleted locally",
    },
}
FS_ENCRYPT_FL = 0x00000800
LINUX_ENCRYPTED_FILESYSTEMS = frozenset(
    {"ecryptfs", "fuse.gocryptfs", "fuse.cryfs"}
)


class ProfileLock:
    """Single-process profile lock held for the service lifetime."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("a+b")
        if self._handle.tell() == 0:
            self._handle.write(b"0")
            self._handle.flush()
        try:
            if os.name == "nt":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._handle.close()
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise ProfileInUse("Profile is already open") from exc
            raise

    def close(self) -> None:
        if self._handle.closed:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()


def _protect_windows_workspace(path: Path) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    encrypt_file = advapi32.EncryptFileW
    encrypt_file.argtypes = [ctypes.c_wchar_p]
    encrypt_file.restype = ctypes.c_int
    get_attributes = kernel32.GetFileAttributesW
    get_attributes.argtypes = [ctypes.c_wchar_p]
    get_attributes.restype = ctypes.c_uint32

    target = str(path.resolve())
    attributes = get_attributes(target)
    if attributes == INVALID_FILE_ATTRIBUTES:
        return False
    if not attributes & FILE_ATTRIBUTE_ENCRYPTED:
        if not encrypt_file(target):
            return False
        attributes = get_attributes(target)
    return attributes != INVALID_FILE_ATTRIBUTES and bool(
        attributes & FILE_ATTRIBUTE_ENCRYPTED
    )


def _macos_filevault_protects(path: Path) -> bool:
    """Verify FileVault for the local user-data volume without changing it."""

    try:
        # Tauri places application data below the user's home directory. Refuse
        # redirected/network homes because fdesetup describes the startup APFS
        # volume group, not an arbitrary external volume.
        if os.stat(path).st_dev != os.stat(Path.home()).st_dev:
            return False
        result = subprocess.run(
            ["/usr/bin/fdesetup", "isactive"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=5,
            env={
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "LANG": "C",
                "LC_ALL": "C",
            },
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def _linux_fscrypt_protects(path: Path) -> bool:
    """Check the inherited Linux fscrypt flag on the profile directory."""

    try:
        import fcntl

        # FS_IOC_GETFLAGS is _IOR('f', 1, long). Linux documents
        # FS_ENCRYPT_FL as a suitable encryption-presence check on supported
        # filesystems. Calculate the request for 32- and 64-bit userspace.
        long_size = struct.calcsize("l")
        request = (2 << 30) | (long_size << 16) | (ord("f") << 8) | 1
        flags = array.array("l", [0])
        open_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        open_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, open_flags)
        try:
            fcntl.ioctl(descriptor, request, flags, True)
        finally:
            os.close(descriptor)
        return bool(flags[0] & FS_ENCRYPT_FL)
    except (ImportError, OSError, ValueError):
        return False


def _linux_mount_type(path: Path, mountinfo: Path = Path("/proc/self/mountinfo")) -> str | None:
    try:
        device = os.stat(path).st_dev
        device_id = f"{os.major(device)}:{os.minor(device)}"
        for line in mountinfo.read_text(encoding="utf-8").splitlines():
            left, separator, right = line.partition(" - ")
            fields = left.split()
            filesystem = right.split()
            if separator and len(fields) >= 5 and fields[2] == device_id and filesystem:
                return filesystem[0]
    except (OSError, ValueError):
        pass
    return None


def _linux_dm_crypt_protects(
    path: Path, sys_devices: Path = Path("/sys/dev/block")
) -> bool:
    """Walk device-mapper parents and require a dm-crypt/LUKS layer."""

    try:
        device = os.stat(path).st_dev
        pending = [f"{os.major(device)}:{os.minor(device)}"]
        visited: set[str] = set()
        while pending:
            device_id = pending.pop()
            if device_id in visited:
                continue
            visited.add(device_id)
            node = (sys_devices / device_id).resolve()
            uuid_path = node / "dm" / "uuid"
            if uuid_path.is_file():
                dm_uuid = uuid_path.read_text(encoding="ascii").strip().upper()
                if dm_uuid.startswith("CRYPT-"):
                    return True
            slaves = node / "slaves"
            if slaves.is_dir():
                for slave in slaves.iterdir():
                    child_device = slave.resolve() / "dev"
                    if child_device.is_file():
                        pending.append(child_device.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return False
    return False


def _linux_encrypted_workspace(path: Path) -> bool:
    return (
        _linux_fscrypt_protects(path)
        or _linux_dm_crypt_protects(path)
        or _linux_mount_type(path) in LINUX_ENCRYPTED_FILESYSTEMS
    )


def _mobile_app_sandbox_protects(path: Path, platform_name: str) -> bool:
    """Accept only an app-private mobile sandbox selected by native code.

    Android and iOS protect app-private files with their platform data-protection
    facilities.  The native bridge creates the directory below the application's
    private home and, on iOS, applies ``NSFileProtectionComplete`` before Python
    opens the database.  Keeping this check here prevents a future bridge change
    from silently moving RNS/LXMF state to shared or removable storage.
    """

    if platform_name not in {"android", "ios"} or sys.platform != platform_name:
        return False
    try:
        home = Path.home().resolve(strict=True)
        resolved = path.resolve(strict=True)
        return resolved != home and resolved.is_relative_to(home)
    except (OSError, RuntimeError):
        return False


def protect_workspace(
    path: Path,
    *,
    allow_unprotected_for_tests: bool = False,
    native_mobile_protection: str | None = None,
) -> None:
    """Require verified at-rest protection before RNS or LXMF can write.

    The test-only bypass is an explicit in-process parameter and is never
    accepted over IPC. Production always verifies a native storage boundary.
    """

    path.mkdir(parents=True, exist_ok=True)
    if allow_unprotected_for_tests:
        return
    if native_mobile_protection is not None:
        protected = _mobile_app_sandbox_protects(path, native_mobile_protection)
        guidance = "Use the app-private mobile profile with native data protection"
    elif sys.platform == "win32":
        protected = _protect_windows_workspace(path)
        guidance = "Windows EFS is unavailable for the app profile"
    elif sys.platform == "darwin":
        protected = _macos_filevault_protects(path)
        guidance = "Enable FileVault on the local user-data volume"
    elif sys.platform.startswith("linux"):
        protected = _linux_encrypted_workspace(path)
        guidance = "Place the profile on fscrypt or a dm-crypt/LUKS-backed filesystem"
    else:
        protected = False
        guidance = f"No verified encrypted workspace adapter for {sys.platform}"
    if not protected:
        raise StorageUnavailable(guidance)


class VaultStore:
    """SQLite journal whose application records are independently AES-GCM sealed."""

    def __init__(
        self,
        profile_dir: Path,
        key: bytes,
        *,
        allow_unprotected_for_tests: bool = False,
        native_mobile_protection: str | None = None,
    ):
        if len(key) != 32:
            raise ValidationError("Vault key must be exactly 32 bytes")
        self.profile_dir = profile_dir.resolve()
        protect_workspace(
            self.profile_dir,
            allow_unprotected_for_tests=allow_unprotected_for_tests,
            native_mobile_protection=native_mobile_protection,
        )
        self._profile_lock = ProfileLock(self.profile_dir / ".profile.lock")
        self._key = key
        self._mobile_cipher = native_mobile_protection is not None
        if self._mobile_cipher:
            # RNS ships an authenticated, pure-Python Fernet-like Token
            # construction.  Using it on mobile avoids an extra native wheel,
            # which is especially important for App Store-compliant iOS
            # packaging.  The master key still lives only in Keychain/Keystore.
            from RNS.Cryptography.Token import Token

            self._token_type = Token
            self._cipher = None
        else:
            if AESGCM is None:
                raise StorageUnavailable("The desktop vault cipher is unavailable")
            self._token_type = None
            self._cipher = AESGCM(key)
        self._lock = threading.RLock()
        try:
            self._db = sqlite3.connect(
                self.profile_dir / "mesh-chat.vault",
                isolation_level=None,
                check_same_thread=False,
                timeout=10,
            )
            self._configure()
            self._migrate()
        except Exception:
            self._profile_lock.close()
            raise

    def _configure(self) -> None:
        self._db.execute("PRAGMA journal_mode=DELETE")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA temp_store=MEMORY")
        self._db.execute("PRAGMA secure_delete=ON")
        self._db.execute("PRAGMA foreign_keys=ON")

    def _migrate(self) -> None:
        with self._transaction():
            self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    name TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS records (
                    kind TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    sealed BLOB NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (kind, record_id)
                ) WITHOUT ROWID
                """
            )
            self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS commands (
                    command_id TEXT PRIMARY KEY,
                    sealed_response BLOB NOT NULL,
                    created_at REAL NOT NULL
                ) WITHOUT ROWID
                """
            )
            current = self._db.execute(
                "SELECT value FROM meta WHERE name='schema_version'"
            ).fetchone()
            if current is None:
                self._db.execute(
                    "INSERT INTO meta(name, value) VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
            elif int(current[0]) != SCHEMA_VERSION:
                raise StorageUnavailable("Unsupported vault schema")
            # Read-only polling used to cache a large encrypted snapshot every
            # few seconds.  Bound existing profiles during startup as well as
            # new writes so an upgrade immediately sheds that historical
            # growth without touching application records.
            self._prune_command_cache_locked(time.time())

    def _prune_command_cache_locked(self, now: float) -> None:
        """Prune the idempotency cache while the caller owns a transaction."""

        self._db.execute(
            "DELETE FROM commands WHERE created_at < ?",
            (now - COMMAND_CACHE_MAX_AGE_SECONDS,),
        )
        self._db.execute(
            """
            DELETE FROM commands
            WHERE command_id IN (
                SELECT command_id
                FROM commands
                ORDER BY created_at DESC, command_id DESC
                LIMIT -1 OFFSET ?
            )
            """,
            (COMMAND_CACHE_MAX_ROWS,),
        )

    class _Transaction:
        def __init__(self, store: "VaultStore"):
            self.store = store

        def __enter__(self) -> None:
            self.store._lock.acquire()
            try:
                self.store._db.execute("BEGIN IMMEDIATE")
            except BaseException:
                # ``__exit__`` is not invoked when ``__enter__`` fails.  Give
                # another command a chance to recover or report the storage
                # error instead of stranding the vault lock permanently.
                self.store._lock.release()
                raise

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            try:
                if exc_type:
                    # SQLite may already have rolled back a failed write (for
                    # example after SQLITE_FULL). Preserve the original body
                    # exception if no transaction remains to roll back.
                    try:
                        self.store._db.execute("ROLLBACK")
                    except BaseException:
                        pass
                else:
                    try:
                        self.store._db.execute("COMMIT")
                    except BaseException:
                        # SQLite can leave a transaction open when COMMIT
                        # fails (for example on an I/O error).  Roll it back so
                        # this connection does not expose uncommitted state and
                        # its next mutation can begin normally.  Preserve the
                        # original COMMIT exception even if rollback also fails.
                        try:
                            self.store._db.execute("ROLLBACK")
                        except BaseException:
                            pass
                        raise
            finally:
                self.store._lock.release()

    def _transaction(self) -> "VaultStore._Transaction":
        return VaultStore._Transaction(self)

    @staticmethod
    def _aad(kind: str, record_id: str) -> bytes:
        return f"mesh-chat:v1:{kind}:{record_id}".encode("utf-8")

    def _seal(self, kind: str, record_id: str, value: dict[str, Any]) -> bytes:
        plaintext = json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        aad = self._aad(kind, record_id)
        if self._mobile_cipher:
            record_key = hmac.new(self._key, aad, hashlib.sha256).digest()
            return b"\x02" + self._token_type(record_key).encrypt(plaintext)
        nonce = os.urandom(12)
        return nonce + self._cipher.encrypt(nonce, plaintext, aad)

    def _open(self, kind: str, record_id: str, sealed: bytes) -> dict[str, Any]:
        try:
            aad = self._aad(kind, record_id)
            if self._mobile_cipher:
                if not sealed.startswith(b"\x02"):
                    raise ValueError("Unexpected mobile vault record format")
                record_key = hmac.new(self._key, aad, hashlib.sha256).digest()
                plaintext = self._token_type(record_key).decrypt(sealed[1:])
            else:
                plaintext = self._cipher.decrypt(sealed[:12], sealed[12:], aad)
            value = json.loads(plaintext.decode("utf-8"))
        except Exception as exc:
            raise StorageUnavailable("Vault record authentication failed") from exc
        if not isinstance(value, dict):
            raise StorageUnavailable("Vault record has an invalid type")
        return value

    def put(self, kind: str, record_id: str, value: dict[str, Any]) -> None:
        self.put_many([(kind, record_id, value)])

    def put_many(self, records: Iterable[tuple[str, str, dict[str, Any]]]) -> None:
        self.put_and_delete(records)

    def put_and_delete(
        self,
        records: Iterable[tuple[str, str, dict[str, Any]]],
        deletions: Iterable[tuple[str, str]] = (),
        *,
        redact_command_cache: bool = False,
    ) -> None:
        """Commit sealed writes and secure deletions as one vault mutation."""

        now = time.time()
        prepared = [
            (kind, record_id, self._seal(kind, record_id, value), now, now)
            for kind, record_id, value in records
        ]
        removed = list(deletions)
        with self._transaction():
            if redact_command_cache:
                # Cached mutation responses can contain a full message or, on
                # profiles upgraded from older releases, a snapshot. A local
                # history deletion must remove those encrypted duplicate
                # plaintext copies in the same commit as the primary records.
                # Keep each command ID as a content-free idempotency tombstone:
                # deleting the row would let a delayed bridge retry execute an
                # old send or draft write again after the conversation vanished.
                command_ids = [
                    row[0]
                    for row in self._db.execute(
                        "SELECT command_id FROM commands"
                    ).fetchall()
                ]
                redacted = [
                    (
                        self._seal(
                            "command", command_id, REDACTED_COMMAND_RESPONSE
                        ),
                        command_id,
                    )
                    for command_id in command_ids
                ]
                self._db.executemany(
                    "UPDATE commands SET sealed_response=? WHERE command_id=?",
                    redacted,
                )
            self._db.executemany(
                "DELETE FROM records WHERE kind=? AND record_id=?", removed
            )
            self._db.executemany(
                """
                INSERT INTO records(kind, record_id, sealed, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(kind, record_id) DO UPDATE SET
                    sealed=excluded.sealed,
                    updated_at=excluded.updated_at
                """,
                prepared,
            )

    def opaque_id(self, namespace: str, *parts: str) -> str:
        """Return a local keyed identifier safe to expose to SQLite indexes."""

        if (
            not isinstance(namespace, str)
            or not namespace
            or any(not isinstance(part, str) for part in parts)
        ):
            raise ValidationError("Opaque record identifier input is invalid")
        material = "\x1f".join((namespace, *parts)).encode("utf-8")
        return hmac.new(
            self._key, b"mesh-chat:opaque-id:v1:" + material, hashlib.sha256
        ).hexdigest()

    def seal_cursor(self, value: dict[str, Any]) -> str:
        body = json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        if not body or len(body) > 4096:
            raise ValidationError("Cursor payload is invalid")
        signature = hmac.new(
            self._key, b"mesh-chat:cursor:v1:" + body, hashlib.sha256
        ).digest()
        return ".".join(
            base64.urlsafe_b64encode(part).rstrip(b"=").decode("ascii")
            for part in (body, signature)
        )

    def open_cursor(self, token: str) -> dict[str, Any]:
        if not isinstance(token, str) or not 1 <= len(token) <= 8192:
            raise ValidationError("Cursor is invalid")
        encoded_body, separator, encoded_signature = token.partition(".")
        if not separator:
            raise ValidationError("Cursor is invalid")
        try:
            body = base64.urlsafe_b64decode(
                encoded_body + "=" * (-len(encoded_body) % 4)
            )
            signature = base64.urlsafe_b64decode(
                encoded_signature + "=" * (-len(encoded_signature) % 4)
            )
        except Exception as exc:
            raise ValidationError("Cursor is invalid") from exc
        canonical_body = base64.urlsafe_b64encode(body).rstrip(b"=").decode("ascii")
        canonical_signature = (
            base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
        )
        if encoded_body != canonical_body or encoded_signature != canonical_signature:
            raise ValidationError("Cursor is invalid")
        expected = hmac.new(
            self._key, b"mesh-chat:cursor:v1:" + body, hashlib.sha256
        ).digest()
        if len(body) > 4096 or not hmac.compare_digest(signature, expected):
            raise ValidationError("Cursor is invalid")
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("Cursor is invalid") from exc
        if not isinstance(value, dict):
            raise ValidationError("Cursor is invalid")
        return value

    def operation_result(
        self, operation_id: str, input_digest: str
    ) -> dict[str, Any] | None:
        record_id = self.opaque_id("workspace-operation", operation_id)
        operation = self.get("workspace_operation", record_id)
        if operation is None:
            return None
        if operation.get("input_digest") != input_digest:
            raise ValidationError("Operation ID was already used with different input")
        outcome = operation.get("outcome")
        if not isinstance(outcome, dict):
            raise StorageUnavailable("Workspace operation record is invalid")
        return outcome

    def commit_operation(
        self,
        operation_id: str,
        input_digest: str,
        outcome: dict[str, Any],
        records: Iterable[tuple[str, str, dict[str, Any]]],
        deletions: Iterable[tuple[str, str]] = (),
        *,
        redact_command_cache: bool = False,
    ) -> dict[str, Any]:
        """Commit one workspace mutation and its replay result atomically."""

        if (
            not isinstance(operation_id, str)
            or not 1 <= len(operation_id) <= 80
            or not isinstance(input_digest, str)
            or len(input_digest) != 64
            or input_digest != input_digest.lower()
            or not isinstance(outcome, dict)
        ):
            raise ValidationError("Workspace operation is invalid")
        try:
            if len(bytes.fromhex(input_digest)) != 32:
                raise ValueError
        except ValueError as exc:
            raise ValidationError("Workspace operation digest is invalid") from exc
        operation_record_id = self.opaque_id("workspace-operation", operation_id)
        now = time.time()
        operation = {
            "id": operation_id,
            "input_digest": input_digest,
            "outcome": outcome,
            "created_at": now,
        }
        values = [*records, ("workspace_operation", operation_record_id, operation)]
        prepared = [
            (kind, record_id, self._seal(kind, record_id, value), now, now)
            for kind, record_id, value in values
        ]
        removed = list(deletions)
        with self._transaction():
            existing = self._db.execute(
                "SELECT sealed FROM records WHERE kind=? AND record_id=?",
                ("workspace_operation", operation_record_id),
            ).fetchone()
            if existing is not None:
                stored = self._open(
                    "workspace_operation", operation_record_id, existing[0]
                )
                if stored.get("input_digest") != input_digest:
                    raise ValidationError(
                        "Operation ID was already used with different input"
                    )
                stored_outcome = stored.get("outcome")
                if not isinstance(stored_outcome, dict):
                    raise StorageUnavailable("Workspace operation record is invalid")
                return stored_outcome
            if redact_command_cache:
                command_ids = [
                    row[0]
                    for row in self._db.execute(
                        "SELECT command_id FROM commands"
                    ).fetchall()
                ]
                redacted = [
                    (
                        self._seal(
                            "command", command_id, REDACTED_COMMAND_RESPONSE
                        ),
                        command_id,
                    )
                    for command_id in command_ids
                ]
                self._db.executemany(
                    "UPDATE commands SET sealed_response=? WHERE command_id=?",
                    redacted,
                )
            self._db.executemany(
                "DELETE FROM records WHERE kind=? AND record_id=?", removed
            )
            self._db.executemany(
                """
                INSERT INTO records(kind, record_id, sealed, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(kind, record_id) DO UPDATE SET
                    sealed=excluded.sealed,
                    updated_at=excluded.updated_at
                """,
                prepared,
            )
        return outcome

    def get(self, kind: str, record_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT sealed FROM records WHERE kind=? AND record_id=?",
                (kind, record_id),
            ).fetchone()
        return None if row is None else self._open(kind, record_id, row[0])

    def list(self, kind: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT record_id, sealed FROM records WHERE kind=? ORDER BY created_at",
                (kind,),
            ).fetchall()
        return [self._open(kind, record_id, sealed) for record_id, sealed in rows]

    def items(self, kind: str) -> list[tuple[str, dict[str, Any]]]:
        """Return record IDs and opened values for bounded maintenance work."""

        with self._lock:
            rows = self._db.execute(
                "SELECT record_id, sealed FROM records WHERE kind=? ORDER BY record_id",
                (kind,),
            ).fetchall()
        return [
            (record_id, self._open(kind, record_id, sealed))
            for record_id, sealed in rows
        ]

    def delete(self, kind: str, record_id: str) -> None:
        with self._transaction():
            self._db.execute(
                "DELETE FROM records WHERE kind=? AND record_id=?", (kind, record_id)
            )

    def command_response(self, command_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT sealed_response FROM commands WHERE command_id=?", (command_id,)
            ).fetchone()
        return None if row is None else self._open("command", command_id, row[0])

    def remember_command(self, command_id: str, response: dict[str, Any]) -> None:
        sealed = self._seal("command", command_id, response)
        now = time.time()
        with self._transaction():
            self._db.execute(
                "INSERT OR IGNORE INTO commands(command_id, sealed_response, created_at) VALUES(?, ?, ?)",
                (command_id, sealed, now),
            )
            self._prune_command_cache_locked(now)

    def close(self) -> None:
        with self._lock:
            self._db.close()
        self._profile_lock.close()

    def __enter__(self) -> "VaultStore":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
