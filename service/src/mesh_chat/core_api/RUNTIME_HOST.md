# Runtime-level profile host

`CoreRuntimeHost` binds Core independently of a profile service. It composes the
production `ProfileRuntimeLifecycle` with a separate protected `VaultStore` for
the host catalog/admission journal and trusted `RegisteredProfile` openers.
Each opener must fetch the **existing platform OS key slot afresh**, construct
the correct service, and transfer exact cleanup ownership on failure. The host
must not capture a profile decrypt key in a long-lived opener closure. Existing
Tauri keyring and Android Keystore slots remain authoritative. This module does
not create a second DPAPI copy or migrate a key slot implicitly.

Register at most eight slots in trusted host code. Preserve each existing
`bytes.fromhex(store.opaque_id("core-api-handle-key", "v1"))` as its derived
handle key. The host catalog seals that derived key separately from the profile
vault. It cannot decrypt profile data, and retains opaque profile/message handles
and operation IDs across lock/reopen. A supplied active service and every newly
opened service must match the registered derived key. A wrong-slot opener is
retained for exact retirement rather than published. The separate host catalog
must stay open while profile stores close; the host owns its final lifetime.

`bind(authorize, ...)` accepts a current trusted `Grant` callback. Its profile
scope contains registered slot IDs; no such ID is accepted from request JSON.
The wrapper rechecks caller identity, profile scope and permission for every
operation/replay, and converts only the selected authorized slot to the existing
service-local scope. `profile.catalog` returns authorized opaque handles,
display names, selection, lock state and a revision. `profile.lock`,
`profile.select` and `profile.unlock` use caller keys. Ordinary service bindings
do not advertise these operations. A locked runtime still supports catalog and
lifecycle requests, and selecting/reconciling never opens a profile implicitly.

Capabilities require all four operations and these positive integer limits:
`profile_slots=8`, `profile_lifecycle_keys_per_host=4096`,
`profile_lifecycle_keys_per_caller_profile=256`, `profile_unlock_credentials=128`.
SDK0.3 helpers gate the feature locally. API major/minor remains1.1; peer wire
and private IPC remain unchanged. The capability operation schema bound is256.
Actual pinned0.2 Python/TypeScript SDKs negotiate this wrapper and enqueue in
component tests; old schema-document validation is a separate compatibility
property. These checks do not establish a supported upgrade window.

Only trusted host authentication calls `issue_unlock_credential(caller, slot)`.
The injected platform authorizer must affirm that authorization. Tokens are
random opaque handles bound to caller, profile, runtime epoch and lifecycle
revision, expire after60 seconds by default (maximum300), and are single use.
Public catalog queries never issue credentials or reveal paths, keys or slots.
The credential reference is refreshed authorization, excluded from the logical
mutation fingerprint: pending work can require a newly authorized credential
without changing its caller key. An already completed same-key retry needs no
new open. A lost completion-journal write after a successful open resolves that
same port result without using the credential or opening again. Superseded or
old-host-epoch keys return `resync_required` before opening.

The bounded journal persists first-admission runtime epoch/revision before
lifecycle effects. It never silently evicts an old key: capacity rejects new
identities. Key conflicts are global across these lifecycle commands for a
caller/profile; profile-vault operations retain their existing domain journals.
The broader mutation-key audit remains open and is not qualified by this host.
Fresh profile creation is enabled only by the separate trusted
`private_profile_bootstrap=True` port. Its durable service receipt prevents a
second identity if the subsequent host-label update fails and is retried.

Publication detaches cached service sessions immediately before platform
publication of `None`. C owns exact worker drain; only completed store close
drops cryptographic references. No immutable-Python-byte zeroization guarantee
is made. Client detach closes only that client's session, not the host.

Current evidence is encrypted-storage/component execution, including installed
SDK consumers and the actual lifecycle port. Packaged Windows/Android platform
installation of existing OS-slot openers is a separate integration requirement;
merely importing this class is not a completed app lifecycle binding.
