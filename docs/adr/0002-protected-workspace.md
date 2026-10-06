# ADR 0002: Protect the whole library workspace

Status: accepted cross-platform boundary; Windows verified, macOS/Linux native release tests pending.

SQL-level encryption alone cannot protect RNS/LXMF ratchet, ticket,
propagation and cache files. The service therefore verifies inherited OS
encryption on the profile directory before constructing SQLite, RNS or LXMF
objects.

- Windows enables and verifies NTFS EFS on the profile directory.
- macOS requires `fdesetup isactive` to verify FileVault and requires the
  profile to remain on the local user-home volume.
- Linux accepts the inherited fscrypt flag, a recursively detected dm-crypt or
  LUKS device-mapper layer, or a recognized eCryptfs/gocryptfs/CryFS mount.

Each adapter is read-only except for Windows applying EFS to the new profile.
Mesh Chat does not enable whole-disk encryption, handle recovery keys, or
silently relocate data. Failure or an unknown platform stops startup before
the reference libraries can write.

The platform checks follow Apple's FileVault volume-encryption model and the
Linux kernel's documented fscrypt flag and dm-crypt device layer:

- [Apple Platform Security: Managing FileVault](https://support.apple.com/guide/security/sec8447f5049/web)
- [Linux kernel fscrypt documentation](https://docs.kernel.org/filesystems/fscrypt.html)
- [Linux kernel dm-crypt documentation](https://docs.kernel.org/admin-guide/device-mapper/dm-crypt.html)

Application records are additionally sealed with AES-256-GCM under a random key stored by the Tauri shell in the native credential store. This separates renderer compromise from key retrieval and authenticates individual records.

Plaintext staging, encrypt-on-shutdown, broad monkey-patching and silent
unprotected fallback remain rejected. Native macOS and Linux packaging and
full-tree plaintext scans are release evidence still to be collected on those
operating systems; unit tests alone do not establish those gates.
