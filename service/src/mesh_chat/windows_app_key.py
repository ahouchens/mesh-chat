"""One independent application's Windows DPAPI key, never an installed vault key."""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path

from .errors import NativeUnavailable

KEY_FILE = "runtime-key.dpapi"
MAGIC = b"mesh-core-app-key-v1\0"
MAX_PROTECTED_BYTES = 16_384


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(payload, entropy, *, protect):
    if os.name != "nt":
        raise NativeUnavailable("App-owned key protection requires Windows")
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
    operation.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    operation.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    source = ctypes.create_string_buffer(payload)
    salt = ctypes.create_string_buffer(entropy)
    incoming = _Blob(len(payload), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
    optional = _Blob(len(entropy), ctypes.cast(salt, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = _Blob()
    try:
        # Current-user DPAPI only; no machine-wide authority or prompt fallback.
        if not operation(ctypes.byref(incoming), None, ctypes.byref(optional), None, None,
                         1, ctypes.byref(outgoing)):  # CRYPTPROTECT_UI_FORBIDDEN
            raise NativeUnavailable("App-owned key protection is unavailable")
        if not 1 <= outgoing.size <= MAX_PROTECTED_BYTES:
            raise NativeUnavailable("App-owned protected key has an invalid size")
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        ctypes.memset(source, 0, len(payload))
        if outgoing.data:
            ctypes.memset(outgoing.data, 0, outgoing.size)
            kernel.LocalFree(outgoing.data)


def load_key(directory: Path):
    """Caller holds the directory's exclusive runtime lock throughout use."""
    directory = directory.resolve(strict=True)
    path = directory / KEY_FILE
    if path.is_symlink() or path.is_junction():
        raise NativeUnavailable("App-owned key storage changed")
    entropy = hashlib.sha256(b"mesh-core:app-owned-key:v1\0" +
        str(directory).casefold().encode("utf-8")).digest()
    try:
        with path.open("rb") as source:
            packed = source.read(MAX_PROTECTED_BYTES + 1)
    except FileNotFoundError:
        if (directory / "profile-v1" / "mesh-chat.vault").exists():
            raise NativeUnavailable("Existing app-owned vault key is missing") from None
        key = os.urandom(32)
        packed = MAGIC + _dpapi(key, entropy, protect=True)
        if len(packed) > MAX_PROTECTED_BYTES:
            raise NativeUnavailable("App-owned protected key has an invalid size")
        # Never replace an existing key, including a partial/unknown prior write.
        with path.open("xb") as target:
            target.write(packed)
            target.flush()
            os.fsync(target.fileno())
        return key
    if not packed.startswith(MAGIC) or not len(MAGIC) < len(packed) <= MAX_PROTECTED_BYTES:
        raise NativeUnavailable("App-owned protected key is invalid")
    key = _dpapi(packed[len(MAGIC):], entropy, protect=False)
    if len(key) != 32:
        raise NativeUnavailable("App-owned protected key is invalid")
    return key
