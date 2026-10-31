import base64
import json
import os

import pytest

from mesh_chat.errors import StorageUnavailable, ValidationError
from mesh_chat.vault import VaultStore


@pytest.mark.parametrize("mobile", [None, "android"])
def test_private_cursor_uses_existing_cipher_and_binds_its_scope(tmp_path, mobile):
    payload = {"v": 1, "g": "g" * 32, "a": "a" * 64, "p": "snapshot",
               "h": 9007199254740991, "k": "h" * 64, "x": 10000000000}
    with VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True,
                    native_mobile_protection=mobile) as store:
        token = store.seal_private_cursor("caller-profile-purpose", payload)
        assert len(token) <= 1024
        assert store.open_private_cursor("caller-profile-purpose", token) == payload
        encrypted = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        assert b"snapshot" not in encrypted and json.dumps(payload).encode() not in encrypted
        with pytest.raises(StorageUnavailable): store.open_private_cursor("another-caller", token)
        tampered = ("A" if token[0] != "A" else "B") + token[1:]
        with pytest.raises(StorageUnavailable): store.open_private_cursor("caller-profile-purpose", tampered)
        with pytest.raises(ValidationError): store.open_private_cursor("caller-profile-purpose", token + "=")


def test_bounded_keyset_reads_preserve_unbounded_maintenance_behavior(tmp_path):
    with VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True) as store:
        store.put_many(("example", key, {"key": key}) for key in ("", "a", "b", "c"))
        assert [key for key, _ in store.items("example")] == ["", "a", "b", "c"]
        assert [key for key, _ in store.items("example", after="a", limit=1)] == ["b"]
