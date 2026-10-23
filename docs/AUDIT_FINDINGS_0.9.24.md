# Whole-project audit findings, 0.9.24

Scope: Python service, renderer commands, Tauri command boundary, retry/recovery
workers, workspace and group delivery paths, and their tests.

## Fixed issues

### 1. Retry worker decrypted all retained personal-message history

`_retry_loop()` called `store.list("message")` every three seconds. The vault
decrypts every record before returning it, so retained history was decrypted
continuously even when only a few messages were queued.

Fixed with an insertion-ordered in-memory retry queue primed once at startup and
maintained on creation and state transitions. The worker now reads only
outstanding records by ID.

### 2. Group delivery retry decrypted all group history

The same scan existed for `store.list("group_delivery")`.

Fixed with a corresponding bounded group retry queue and per-ID processing.

### 3. Group retry could lose a record during its commit

A group delivery is queued by `_delivery_record()` before the caller commits it.
A fast retry tick could observe no record yet and drop the ID permanently.

Fixed with one grace cycle for a missing group delivery; a second missing
observation drops the stale ID.

### 4. Retry queue ordering was nondeterministic

The queues were Python sets, so backlog order and dispatch-lock yielding were
arbitrary. This produced flaky, occasionally failing backlog tests.

Fixed by using insertion-ordered dictionaries.

### 5. Workspace search was rejected by the service command gate

The renderer called `search_workspace`, the Tauri shell allowed it, but
`MeshChatService.COMMANDS` did not include it. Every workspace search invocation
was rejected before dispatch.

Fixed by adding the command to `COMMANDS` and `UNCACHED_COMMANDS` (large search
responses must not enter the idempotency cache).

### 6. Contact management was blocked by the Tauri allowlist

The renderer exposes contact update, rename, delete, verify/unverify, and
unblock actions. `verify_contact` and `block_contact` were allowed, but
`src-tauri/src/lib.rs` did not allow:

- `update_contact`
- `rename_contact`
- `delete_contact`
- `unverify_contact`
- `unblock_contact`

Those actions failed at the shell boundary even though the Python service
implemented them.

Fixed by adding all five missing commands to the renderer allowlist.

### 7. No conformance test protected the command boundary

Existing frontend tests mocked the service, so missing Rust/service commands were
invisible.

Added `service/tests/test_command_allowlists.py`, which:

- parses the Rust allowlist;
- verifies every renderer-allowed command exists in `MeshChatService.COMMANDS`;
- scans every non-test renderer source file for literal `serviceCommand` names;
- verifies each one is allowed by Rust and known to the service;
- explicitly covers contact management and workspace search.

### 8. Backlog tests modeled a different system

The dispatch-lock backlog tests manually wrote queue records without registering
them in the new retry queues, and relied on timing between threads.

Fixed by seeding the queues explicitly and using a deterministic command-lock
handshake instead of timing inference.

## Residual risks

- Startup recovery still performs one full outbox/group scan to prime queues.
- `_flush_contact` scans direct messages when a contact is approved.
- `_ensure_receipt` scans for an existing receipt on inbound receipt creation.
- Workspace delivery retry remains a separate queue/path.
- Physical-device qualification is still not claimed.
