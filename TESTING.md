# Verification and release gates

Phase 2 direct-connectivity work has a separate
[evidence record](docs/DIRECT_CONNECTIVITY_PHASE2_EVIDENCE.md), distinguishing
local service checks, native CI and unfulfilled production/physical gates.

Production setup tests in `service/tests/test_direct_setup_pipeline.py` exercise
public commands, real protected services and isolated RNS/LXMF bootstrap workers.
The source carrier intentionally delays one admitted adapter after peer transport
authentication, reproducing the bootstrap-retirement race. Both-hosted and
unhosted-joiner cases require signed join acknowledgment, approval, fresh admitted
credentials, channel bootstrap, messages and receipts in both directions, followed
by cancellation, suspension or revocation with no remaining native handles/interfaces.

GitHub Actions builds `experiments/direct-app-host`, which imports the shipping
private native dispatcher directly. The same pipeline then uses real QUIC and
native socket/key ownership. Its test adapter translates one signed synthetic
public address to loopback while preserving the native port and certificate;
this is controlled evidence, not router reachability. Linux runs under the syscall
audit and retains endpoint-free provenance. Never build or run this native harness
locally. Frontend/package/native tests and Windows/Android builds run in Actions.
Physical execution follows the
[Phase 2 device checklist](docs/DIRECT_CONNECTIVITY_PHASE2_DEVICE_TEST.md).

## Workspace DM calls, 0.9.14

Phase 6 adds 1:1 calls from a workspace DM without creating a Personal contact.

Implemented:

- Workspace DM header exposes audio/video call actions.
- The selected workspace device is addressed as a synthetic
  `workspace:<workspace>:<member>:<device>` peer.
- Call invites, answers, ICE candidates, hangup, and restart documents travel as
  `workspace_call_signal` through the existing encrypted workspace delivery
  queue.
- The call manager accepts the synthetic `workspace` peer only while the
  workspace and both devices are active.
- Incoming workspace calls resolve to the workspace member name in the call UI.
- A service test covers starting a workspace call, the queued workspace control,
  and the recipient entering the ringing state.

Not implemented in this stage:

- group calls;
- physical Android/Windows audio/video, NAT/TURN, route-change, and lock
  qualification.

Validation:

```text
pytest service/tests:        1109 passed, 46 skipped, 0 failed (297.76 s)
node scripts/run-frontend-tests.mjs: 264 passed (18 files)
node --test deploy/cloudflare-signal/worker.test.mjs: 11 passed
packaged emoji artwork verification: 3 passed
node node_modules/typescript/bin/tsc -b: passed
node scripts/run-frontend-build.mjs: passed
```

The official report is
`dist/reports/0.9.14/20261022T215149Z-1fea5121/report.json` (git-ignored):
`status: passed`, 346.713 s, SHA-256
`38b9e3e251ca283313ee2fdcd9a395a08b2ea2af85f9170bf36dd4909f75718a`.
Gates: `automated: passed`; `physical_device: not-requested`;
`production_signing: not-requested`.

## Owner-offline admission grants, owner-return stage 0.9.13

Phase 5.2c adds owner-return normalization.

Implemented:

- A v1 manifest may carry `delegation_end: true` when it extends a delegated v2
  head.
- The normalization manifest must preserve membership, name, description,
  policies, retention, and authority; it returns the workspace to a normal
  owner-signed v1 head.
- Ending an accepted grant publishes this normalization manifest and revokes the
  grant. The selected admin receives both the v1 head and the revocation.
- Service tests cover the v2 admission, the v1 normalization, and the admin-side
  revocation state.

Not implemented in this stage:

- explicit fork-resolution UI;
- pre-v2 client fail-closed delivery;
- physical multi-device qualification.

Validation:

```text
pytest service/tests:        1108 passed, 46 skipped, 0 failed (294.73 s)
node scripts/run-frontend-tests.mjs: 264 passed (18 files)
node --test deploy/cloudflare-signal/worker.test.mjs: 11 passed
packaged emoji artwork verification: 3 passed
node node_modules/typescript/bin/tsc -b: passed
node scripts/run-frontend-build.mjs: passed
```

The official report is
`dist/reports/0.9.13/20261022T211937Z-ce2c999f/report.json` (git-ignored):
`status: passed`, 348.812 s, SHA-256
`130c3bc28e61f425e9a95e32e2aea6f0ab26da58b8e1f594156c254d6f8cc6ef`.
Gates: `automated: passed`; `physical_device: not-requested`;
`production_signing: not-requested`.

Publication: GitHub Actions
[CI run 39857200952](https://github.com/ahouchens/mesh-chat/actions/runs/39857200952)
and
[Release run 39857207211](https://github.com/ahouchens/mesh-chat/actions/runs/39857207211)
passed on the first attempt for `v0.9.13`. Release:
<https://github.com/ahouchens/mesh-chat/releases/tag/v0.9.13>.

| Artifact | Bytes | SHA-256 (verified by re-download) |
|---|---:|---|
| `Mesh-Chat_0.9.13_x64-setup.exe` | 27,889,336 | `e1239dbe79cc2893452ae57b666394733d39540a10e084eea1dd9601ba0edd42` |
| `Mesh-Chat_0.9.13_x64_en-US.msi` | 29,880,320 | `d1bdb703b0458fbc87be0d0cb5de9660430993d546a0b01ce73e9cd2ff316acd` |
| `mesh-chat-0.9.13-android-arm64-release.apk` | 34,387,732 | `1571096d96fbdf6bc2f19d4c531cbfd605f89791c1b2b20f5dce8195410538d9` |
| `SHA256SUMS.txt` | 303 | `3cba491786c309cf33d9400aaa94aa2ed5c73c7af6491a66eb676d9d388f86ea` |

The Android APK is debug-signed; it is not a production or upgrade identity.

## Owner-offline admission grants, revocation stage 0.9.12

Phase 5.2c adds owner revocation of an admission grant.

Implemented:

- `end_workspace_admission_grant` for the owner authority marks the grant
  revoked and delivers `workspace_admission_revocation` to the selected admin
  device.
- The admin marks the grant revoked and cannot approve further joins from it.
- Workspace settings shows **End delegation** for owners and **Revoked** state
  for both sides.
- A v2 delegated manifest can still be read/applied after owner revocation; the
  next owner semantic change extends the current head.

Not implemented in this stage:

- automatic owner-return normalization into a fresh v1 manifest;
- explicit fork-resolution UI;
- pre-v2 client fail-closed delivery;
- physical multi-device qualification.

Validation:

```text
pytest service/tests:        1108 passed, 46 skipped, 0 failed (264.58 s)
node scripts/run-frontend-tests.mjs: 264 passed (18 files)
node --test deploy/cloudflare-signal/worker.test.mjs: 11 passed
packaged emoji artwork verification: 3 passed
node node_modules/typescript/bin/tsc -b: passed
node scripts/run-frontend-build.mjs: passed
```

The official report is
`dist/reports/0.9.12/20261022T203012Z-5e1fe3bf/report.json` (git-ignored):
`status: passed`, 305.461 s, SHA-256
`fadeb8222539b24f0caf015e942b5b774bef53dd87a214739018d1aac5876228`.
Gates: `automated: passed`; `physical_device: not-requested`;
`production_signing: not-requested`.

Publication: GitHub Actions
[CI run 39850218352](https://github.com/ahouchens/mesh-chat/actions/runs/39850218352)
and
[Release run 39850225618](https://github.com/ahouchens/mesh-chat/actions/runs/39850225618)
passed on the first attempt for `v0.9.12`. Release:
<https://github.com/ahouchens/mesh-chat/releases/tag/v0.9.12>.

| Artifact | Bytes | SHA-256 (verified by re-download) |
|---|---:|---|
| `Mesh-Chat_0.9.12_x64-setup.exe` | 27,891,545 | `3523bb25b51012f098fdd2f06cafa8fdb340347a59863b5a5579ac2acfb71bab` |
| `Mesh-Chat_0.9.12_x64_en-US.msi` | 29,880,320 | `d60336bed86c5c37415209991b27ea4b856751bfb40cd7ab36c2937ce12cb9d1` |
| `mesh-chat-0.9.12-android-arm64-release.apk` | 34,387,687 | `9328411682317ceb43d70e55b3f16dda00de0826bf20fb49db5be6543e4f6d56` |
| `SHA256SUMS.txt` | 303 | `1e5a56c326ec04a516233bd927364947fd7bacff4246ff77cb5ad3d6207eaab1` |

The Android APK is debug-signed; it is not a production or upgrade identity.

## Owner-offline admission grants, UI stage 0.9.11

Phase 5.2c adds the workspace-settings grant/admission UI.

Implemented:

- **Owner-offline admission grants** section in Workspace settings for owners and
  admins.
- Owner selects an active admin member and device, creates a five-admission,
  seven-day grant, and sees offered/accepted state, uses, and expiry.
- Selected admin sees the received grant and can accept it.
- The existing pending-join Approve action now works for an admin with an
  accepted grant.
- Manifest, grant, and acceptance state continue to be signed and verified by
  the service.

Not implemented in this stage:

- owner-return normalization;
- fork/revocation/expiry UX beyond the displayed expiry;
- pre-v2 client fail-closed delivery;
- physical multi-device qualification.

Validation:

```text
pytest service/tests:        1108 passed, 46 skipped, 0 failed (259.54 s)
node scripts/run-frontend-tests.mjs: 264 passed (18 files)
node --test deploy/cloudflare-signal/worker.test.mjs: 11 passed
packaged emoji artwork verification: 3 passed
node node_modules/typescript/bin/tsc -b: passed
node scripts/run-frontend-build.mjs: passed
```

The official report is
`dist/reports/0.9.11/20261022T192008Z-b3793a4d/report.json` (git-ignored):
`status: passed`, 300.181 s, SHA-256
`b81e5edc5b5631e056ba5d4c7c53ae0fd64ed84bcb77c925201f275bf975786a`.
Gates: `automated: passed`; `physical_device: not-requested`;
`production_signing: not-requested`.

Publication: GitHub Actions
[CI run 39839958074](https://github.com/ahouchens/mesh-chat/actions/runs/39839958074)
and
[Release run 39839964028](https://github.com/ahouchens/mesh-chat/actions/runs/39839964028)
passed on the first attempt for `v0.9.11`. Release:
<https://github.com/ahouchens/mesh-chat/releases/tag/v0.9.11>.

| Artifact | Bytes | SHA-256 (verified by re-download) |
|---|---:|---|
| `Mesh-Chat_0.9.11_x64-setup.exe` | 27,888,415 | `0e0d0dd40f7d298cada22dd72ed78538f81391aa1810c6003cdeaead99b3ecf1` |
| `Mesh-Chat_0.9.11_x64_en-US.msi` | 29,880,320 | `993ddaa66a2e3a81ec35f3573af32d899702bd55a7c9892cd9dc6d421a78ea7a` |
| `mesh-chat-0.9.11-android-arm64-release.apk` | 34,387,598 | `443bc951e7f3285bb53a23de7ce64d69ec18e9f013ed44006a6238ee4396312b` |
| `SHA256SUMS.txt` | 303 | `7e7bfeb39db458aafe2617c75ca4daabb4ad355d67091d13b494424a81dec491` |

The Android APK is debug-signed; it is not a production or upgrade identity.

## Owner-offline admission grants, delegated backend 0.9.10

Phase 5.2b adds the delegated-admission backend. There is still no grant or
admission UI, and owner-offline admission is not exposed to users.

Implemented:

- owner forwards pending join requests plus their invitations to the accepted
  admin device as `workspace_admission_pending`;
- `approve_workspace_join` accepts an active admin holding a valid accepted
  grant, builds a chained v2 delegated manifest, verifies it, and advances the
  grant use count;
- v2 manifests are delivered as `workspace_manifest_delegated`, verified against
  the current manifest, applied by recipients, and recorded as the new epoch;
- invalid, stale, or fork-conflicting v2 manifests fail closed;
- the owner v1 approval path is unchanged.

Not implemented in this stage:

- grant/admission UI;
- owner-return normalization and fork/revocation UX;
- pre-v2 client fail-closed delivery handling;
- physical qualification.

Coverage includes a chained delegated manifest created from an accepted grant
and applied by a recipient as the new workspace epoch.

Validation:

```text
pytest service/tests:        1108 passed, 46 skipped, 0 failed (260.16 s)
node scripts/run-frontend-tests.mjs: 264 passed (18 files)
node --test deploy/cloudflare-signal/worker.test.mjs: 11 passed
packaged emoji artwork verification: 3 passed
node node_modules/typescript/bin/tsc -b: passed
node scripts/run-frontend-build.mjs: passed
```

The official report is
`dist/reports/0.9.10/20261022T184929Z-1ec2e3d8/report.json` (git-ignored):
`status: passed`, 296.412 s, SHA-256
`789138e3ff9e63a23b31b5a15362370883bddf1ae293b32466f140468e1420ec`.
Gates: `automated: passed`; `physical_device: not-requested`;
`production_signing: not-requested`.

Publication: GitHub Actions
[CI run 39835524059](https://github.com/ahouchens/mesh-chat/actions/runs/39835524059)
and
[Release run 39835530258](https://github.com/ahouchens/mesh-chat/actions/runs/39835530258)
passed on the first attempt for `v0.9.10`. Release:
<https://github.com/ahouchens/mesh-chat/releases/tag/v0.9.10>.

| Artifact | Bytes | SHA-256 (verified by re-download) |
|---|---:|---|
| `Mesh-Chat_0.9.10_x64-setup.exe` | 27,886,804 | `b7aae8ad147d900c5b12fde09cc9ee375123b6c6293dd5dc904cc6adb867a967` |
| `Mesh-Chat_0.9.10_x64_en-US.msi` | 29,880,320 | `a39177c06bd527e88918e5fd18adaa2cf4ba69cc87a624ae581aa1208e58dce8` |
| `mesh-chat-0.9.10-android-arm64-release.apk` | 34,387,668 | `08b35ad5676712dcbba198a62168c00d89fbd1a1c30c62f9104f97d5ea74f5c2` |
| `SHA256SUMS.txt` | 303 | `a8c1c05e67828a6bdc20f8fc8d026779ec3b16ab60e1228b716431bdb85e8eb0` |

The Android APK is debug-signed; it is not a production or upgrade identity.
There is still no grant/admission UI; owner-offline joins remain queued in the UI.

## Owner-offline admission grants, service stage 0.9.9

Phase 5.2a adds the **grant lifecycle service** on top of the 0.9.8 protocol
primitives. It does not enable owner-offline admission yet.

Implemented:

- `create_workspace_admission_grant` for the active owner authority: validates
  an active admin member/device, signs a grant, stores it, and queues it to that
  admin device.
- `workspace_admission_grant` delivery and receive handling, restricted to the
  selected admin device.
- `list_workspace_admission_grants` for owners/admins and
  `accept_workspace_admission_grant` for the selected admin device.
- Signed `workspace_admission_acceptance` delivery back to the owner authority
  and acceptance state visibility on both sides.
- Grant expiry, workspace/start-manifest binding, and admin device binding.

Not implemented in this stage:

- admin admission of a pending join;
- v2 delegated-manifest delivery/application;
- owner-return, fork/revocation UX;
- pre-v2 fail-closed delivery;
- any grant UI.

Owner-offline joins remain queued in 0.9.9.

Validation:

```text
pytest service/tests:        1108 passed, 46 skipped, 0 failed (262.27 s)
node scripts/run-frontend-tests.mjs: 264 passed (18 files)
node --test deploy/cloudflare-signal/worker.test.mjs: 11 passed
packaged emoji artwork verification: 3 passed
node node_modules/typescript/bin/tsc -b: passed
node scripts/run-frontend-build.mjs: passed
```

The official report is
`dist/reports/0.9.9/20261022T175145Z-e1cde8eb/report.json` (git-ignored):
`status: passed`, 328.207 s, SHA-256
`0aaaccd5f8fb547d67fb4c7250b591ed6a565210ba9bf8a99cc110b01bb33a75`.
Gates: `automated: passed`; `physical_device: not-requested`;
`production_signing: not-requested`.

Publication: GitHub Actions
[CI run 39827278444](https://github.com/ahouchens/mesh-chat/actions/runs/39827278444)
and
[Release run 39827287818](https://github.com/ahouchens/mesh-chat/actions/runs/39827287818)
passed on the first attempt for `v0.9.9`. Release:
<https://github.com/ahouchens/mesh-chat/releases/tag/v0.9.9>.

| Artifact | Bytes | SHA-256 (verified by re-download) |
|---|---:|---|
| `Mesh-Chat_0.9.9_x64-setup.exe` | 27,877,776 | `a5efa3d260ee71b3a6979a6c3c7f02445e5d33b1765dc81e3f263712d805f49f` |
| `Mesh-Chat_0.9.9_x64_en-US.msi` | 29,868,032 | `26dbd36b8049d8715a7aff6d1e66261c2e28c752ee9b7b98b951c27f451eb765` |
| `mesh-chat-0.9.9-android-arm64-release.apk` | 34,371,413 | `f7fe1a0e39c3a2d79ef0e8c9a35bcfdeefb85435ed3c99f3470dcf530268cc8a` |
| `SHA256SUMS.txt` | 300 | `138c46e1e6430aea6988151e3bc512977aded37c618231d222baaf5c0c48848d` |

The Android APK is debug-signed; it is not a production or upgrade identity.
No owner-offline admission UI or admission path is enabled in this release.

## Owner-offline admission grants, protocol stage 0.9.8

Phase 5.1 of the [workspace connectivity spec](docs/WORKSPACE_CONNECTIVITY_SPEC.md)
adds only protocol primitives and verifiers. The workspace service and UI do
**not** yet issue grants, accept them, deliver v2 delegated manifests, or admit
members while the owner is offline. Owner-offline joins remain queued in 0.9.8.

Protocol coverage:

- `workspace_admission_grant` round trip, owner signature, admin device-card
  binding, workspace/start-manifest binding, nonce, expiry, and tamper rejection.
- `workspace_admission_acceptance` binds the exact grant digest and admin
  destination; wrong admin/signature and tampered acceptance are rejected.
- `workspace_manifest_delegated` v2 full-snapshot creation and verification:
  owner/authority retention, admin signature, grant/acceptance checks, chained
  `grant_use` 1..5, and exactly one new active non-owner member.
- Existing members, devices, roles, status, name, description, policies,
  retention, and authority must remain unchanged; removal, policy changes, and
  new admins are rejected.
- Pre-v2 clients are not modified in this stage; the fail-closed delivery path is
  a Phase 5.2 integration requirement.

Validation:

```text
pytest service/tests:        1107 passed, 46 skipped, 0 failed (262.17 s)
node scripts/run-frontend-tests.mjs: 264 passed (18 files)
node --test deploy/cloudflare-signal/worker.test.mjs: 11 passed
packaged emoji artwork verification: 3 passed
node node_modules/typescript/bin/tsc -b: passed
node scripts/run-frontend-build.mjs: passed
```

The official report is
`dist/reports/0.9.8/20261022T165548Z-5bb539a9/report.json` (git-ignored):
`status: passed`, 297.105 s, SHA-256
`09856ca43dd06be3e04ca972dbad49d6a9e5143fa085337f80959c55db883bc0`.
Gates: `automated: passed`; `physical_device: not-requested`;
`production_signing: not-requested`.

Publication: GitHub Actions
[CI run 39818993817](https://github.com/ahouchens/mesh-chat/actions/runs/39818993817)
and
[Release run 39819005104](https://github.com/ahouchens/mesh-chat/actions/runs/39819005104)
passed on the first attempt for `v0.9.8`. Release:
<https://github.com/ahouchens/mesh-chat/releases/tag/v0.9.8>.

| Artifact | Bytes | SHA-256 (verified by re-download) |
|---|---:|---|
| `Mesh-Chat_0.9.8_x64-setup.exe` | 27,865,393 | `7f250d0fb6c2d3b5cc154201b7e1917385ff76414c1654f2df106207a2e520ff` |
| `Mesh-Chat_0.9.8_x64_en-US.msi` | 29,859,840 | `4245f4a9a9aa44e893bf69ead07b0f452a66cb011b2846962877837b2ef14b8f` |
| `mesh-chat-0.9.8-android-arm64-release.apk` | 34,371,328 | `70642f2a6593cef8597f371c767424c43633d5d223d861004f6039354f28ff75` |
| `SHA256SUMS.txt` | 300 | `be27f12fa21381e4a85f28029d701ef26357eaa54f6d08519a8328fb6443d94d` |

The Android APK is debug-signed; it is not a production or upgrade identity.
This release enables no owner-offline admission UI; the protocol is present but
the Phase 5.2 service/UI path is still required.

## One-hop workspace connection helper, 0.9.7

Phase 4 of the [workspace connectivity spec](docs/WORKSPACE_CONNECTIVITY_SPEC.md)
lets an opted-in active workspace device relay one existing signed
DirectRecovery connection update between two other active devices.

Service:

- Helper relaying is off by default (`workspace_helper_consent_set`). No member
  becomes a helper implicitly.
- `relay_workspace_connection_update` requires an established
  workspace/direct relationship owned by this device and an active helper that
  is neither the local nor the audience device. It wraps the existing exact
  `mesh-recover:` document; it does not create a new route, admission, or
  authority.
- `workspace_connection_relay` is a bounded workspace control with workspace ID,
  origin device, audience device, and the signed document. The first helper must
  see a native source equal to the origin and current active origin/audience
  devices; it forwards only to the audience and only when local helper consent is
  enabled.
- If this device is the audience, it applies the original document through
  DirectRecovery. A second helper sees a native source different from the origin
  and ignores the wrapper, bounding delivery to one hop.
- Helpers see connection endpoints/timing, not chat, history, receipts,
  membership, authority, or keys. The recipient verifies the original signature,
  scope, audience, expiry, and replay.

UI:

- **Workspace settings → Direct connections → One-hop helper relay** has the
  opt-in checkbox, a helper selector, and **Send via helper** per established
  relationship. Manual copy/import remains available.

Validation:

```text
pytest service/tests:        1105 passed, 46 skipped, 0 failed (280.14 s)
node scripts/run-frontend-tests.mjs: 264 passed (18 files)
node --test deploy/cloudflare-signal/worker.test.mjs: 11 passed
packaged emoji artwork verification: 3 passed
node node_modules/typescript/bin/tsc -b: passed
node scripts/run-frontend-build.mjs: passed
```

The official report is
`dist/reports/0.9.7/20261022T153658Z-bfd7ad5d/report.json` (git-ignored):
`status: passed`, 326.841 s, SHA-256
`47b23c16923940b30f0639a25ef6d110e89089b617cc2802dfcf833aed0dac5a`.
Gates: `automated: passed`; `physical_device: not-requested`;
`production_signing: not-requested`.

Publication: GitHub Actions
[CI run 39807416471](https://github.com/ahouchens/mesh-chat/actions/runs/39807416471)
and
[Release run 39807422024](https://github.com/ahouchens/mesh-chat/actions/runs/39807422024)
passed on the first attempt for `v0.9.7`. Release:
<https://github.com/ahouchens/mesh-chat/releases/tag/v0.9.7>.

| Artifact | Bytes | SHA-256 (verified by re-download) |
|---|---:|---|
| `Mesh-Chat_0.9.7_x64-setup.exe` | 27,863,970 | `ad5294a04c68a8263f38db00311291af82ee1010e8468fe68966f24f57fbb93b` |
| `Mesh-Chat_0.9.7_x64_en-US.msi` | 29,859,840 | `28e93a381d39ecff2b71bb0ac7aebec7b77934b7914874529d3797712de4bec6` |
| `mesh-chat-0.9.7-android-arm64-release.apk` | 34,354,838 | `7d07c55c7fef963e4eabdea245d0f3ff182c85ffcec168a57865bfa51c864367` |
| `SHA256SUMS.txt` | 300 | `e1b89abe5992b7cb5ace58afdee669b36f48f865fe8cf0554c722c740adcdac9` |

The Android APK is debug-signed; it is not a production or upgrade identity.

New coverage includes helper opt-in default/forwarding, source/origin binding,
helper-disabled behavior, audience-only forward, and one-hop stop. No physical
multi-device helper or DirectRecovery route test was performed.

## Workspace-scoped reconnect, 0.9.6

Phase 3 of the [workspace connectivity spec](docs/WORKSPACE_CONNECTIVITY_SPEC.md)
lets workspace-only devices use the existing opt-in mailbox/WebRTC reconnect
without creating a Personal contact.

Service:

- `MESHWSR1` wraps a signed pair `connection_capabilities` document with the
  exact workspace ID, manifest digest, wrapper signer, and expiry. The wrapper
  and inner capability must have the same current active signer, and the inner
  peer destination must be this device.
- Workspace reconnect profiles are keyed by
  `workspace:<workspace>:<member>:<device>` and default off. Enabling creates one
  profile per active peer device, issues a fresh pair token/capability, and
  queues a `workspace_reconnect_capability` control to each device.
- Inbound wrappers verify the active source, active workspace/device, signer,
  peer destination, and dates; they store only peer capabilities and never
  change local consent, membership, authority, or trust.
- `workspace_reconnect_status` and `workspace_reconnect_consent_set` expose the
  consent, ready/peer counts, and active revalidation state. Removing a
  member/device/workspace yields a non-ready profile rather than an
  authorization.
- The existing coordinator, request/offer/answer documents, mailbox TTL/rate
  limits, replay cache, glare control, and retry bounds are reused with
  synthetic workspace peer keys. No Personal contact is created.

UI:

- **Workspace settings → Automatic reconnect** has an off-by-default toggle and
  a separate direct-IP-disclosure choice, with ready/peer counts and guidance
  that both sides must enable, the mailbox must be configured, and the app must
  be open and unlocked.
- Saving stops/retries the coordinator's workspace profiles as appropriate.

Validation:

```text
pytest service/tests:        1104 passed, 46 skipped, 0 failed (280.32 s)
node scripts/run-frontend-tests.mjs: 264 passed (18 files)
node --test deploy/cloudflare-signal/worker.test.mjs: 11 passed
packaged emoji artwork verification: 3 passed
node node_modules/typescript/bin/tsc -b: passed
node scripts/run-frontend-build.mjs: passed
```

The official report is
`dist/reports/0.9.6/20261022T145501Z-b0e2c650/report.json` (git-ignored):
`status: passed`, 327.924 s, SHA-256
`bfe46ad697868b5860aa3a52f9a2a000e0904ef7bc28f1766c375c4fd38fbd19`.
Gates: `automated: passed`; `physical_device: not-requested`;
`production_signing: not-requested`.

Publication: GitHub Actions
[CI run 39800915424](https://github.com/ahouchens/mesh-chat/actions/runs/39800915424)
and
[Release run 39800923116](https://github.com/ahouchens/mesh-chat/actions/runs/39800923116)
passed on the first attempt for `v0.9.6`. Release:
<https://github.com/ahouchens/mesh-chat/releases/tag/v0.9.6>.

| Artifact | Bytes | SHA-256 (verified by re-download) |
|---|---:|---|
| `Mesh-Chat_0.9.6_x64-setup.exe` | 27,861,603 | `bf3925c81bb409466a20c96b5dc1f54793cde567b22521f7120995a2c02aee0f` |
| `Mesh-Chat_0.9.6_x64_en-US.msi` | 29,847,552 | `67c220fd35ddaf410ab72d2e0442d0671af1ff492bddcfd926bc08a1b230162e` |
| `mesh-chat-0.9.6-android-arm64-release.apk` | 34,354,896 | `bd6cbb4e0abcb30effd4c7acae0b7843d803a0a41e47725c90bcfbcd7e169a81` |
| `SHA256SUMS.txt` | 300 | `d53f7fa3ee814e100552e71535f838f5b509cb2a1756631744275a2b366f733a` |

The Android APK is debug-signed; it is not a production or upgrade identity.

New coverage includes wrapper round trip/verification, consent-off default,
per-device capability exchange, no-contact assertion, ready counts after both
sides enable, synthetic workspace request/offer/answer flow, and the renderer
consent save. No physical multi-device workspace reconnect, network-switch,
NAT/TURN, or Android suspension test was performed.

## Workspace access delivery, 0.9.5

Phase 2b of the [workspace connectivity spec](docs/WORKSPACE_CONNECTIVITY_SPEC.md)
adds per-device automatic delivery of the owner-signed access recommendation.
Receipt is not consent and does not attach anything by itself.

Service:

- `send_workspace_access_recommendation` requires the active owner authority
  device and a recommendation bound to the current local manifest. It queues one
  `workspace_access_recommendation` control delivery per active member device,
  excluding the local authority device, through the existing retry/expiry
  scheduler.
- Inbound control payloads verify the `MESHACCESS1` bytes, workspace ID, source
  activity, and expiry before storing only the signed document and safe summary.
  They do not attach a profile, change authority, or send a read receipt.
- `list_workspace_access_recommendations` exposes safe summaries and a stale
  flag; `preview_workspace_access_recommendation_by_id` and
  `apply_workspace_access_recommendation_by_id` preserve the preview/consent
  boundary, with `apply` requiring an explicit consent boolean.
- Commands are in the service and Rust allowlists.

UI:

- **Workspace settings → Workspace access point** now lists recommendations
  received for the workspace, with stale state and a Review action.
- The owner can **Send to workspace members** after creating a recommendation;
  the out-of-band copy remains available.
- Review shows the operator disclosure; attachment still requires explicit
  consent.

Validation:

```text
pytest service/tests:        1103 passed, 46 skipped, 0 failed (280.69 s)
node scripts/run-frontend-tests.mjs: 263 passed (18 files)
node --test deploy/cloudflare-signal/worker.test.mjs: 11 passed
packaged emoji artwork verification: 3 passed
node node_modules/typescript/bin/tsc -b: passed
node scripts/run-frontend-build.mjs: passed
```

The official report is
`dist/reports/0.9.5/20261022T135545Z-f0da3f70/report.json` (git-ignored):
`status: passed`, 327.258 s, SHA-256
`4530a16594d8168e5b7c1436830ddb5b14747a4e8cd8945f2c5b6147c90530a7`.
Gates: `automated: passed`; `physical_device: not-requested`;
`production_signing: not-requested`.

Publication: GitHub Actions
[CI run 39792160299](https://github.com/ahouchens/mesh-chat/actions/runs/39792160299)
and
[Release run 39792165966](https://github.com/ahouchens/mesh-chat/actions/runs/39792165966)
passed on the first attempt for `v0.9.5`. Release:
<https://github.com/ahouchens/mesh-chat/releases/tag/v0.9.5>.

| Artifact | Bytes | SHA-256 (verified by re-download) |
|---|---:|---|
| `Mesh-Chat_0.9.5_x64-setup.exe` | 27,848,502 | `8608f176f55cb89054c3d8f46ecf42644c5d2074bdba52b5e624745b11fdc394` |
| `Mesh-Chat_0.9.5_x64_en-US.msi` | 29,839,360 | `2091899abe90c0494bcc385cb3894c47d8d2381d7dc41d539997932388820ca1` |
| `mesh-chat-0.9.5-android-arm64-release.apk` | 34,338,520 | `9c97b6b37d449defcc8ecbe4082d834f304ebd4a2bdcb0964892b27fc510ec09` |
| `SHA256SUMS.txt` | 300 | `e6b09946895f0a052bf5e43d7c6136b8962de7ff2d257e4758ad3f85996665d4` |

The Android APK is debug-signed; it is not a production or upgrade identity.

Tests cover owner-only send, per-device delivery, inbound storage, stale state,
received preview/consent/apply, sender UI queueing, and the out-of-band fallback.
No physical multi-member access-point or suspension test was performed.

## Workspace access recommendations, 0.9.4

Phase 2a of the [workspace connectivity spec](docs/WORKSPACE_CONNECTIVITY_SPEC.md)
adds an owner-signed, out-of-band access-point recommendation. It is not a
workspace reconnect profile and does not make the owner a relay.

Service:

- `MESHACCESS1:` carries the workspace ID, exact current manifest digest, the
  canonical Remote Connection Profile, creation/expiry, authority public key,
  and signature over canonical bytes.
- `create_workspace_access_recommendation` is restricted to the active owner
  authority device. It fails for non-authority devices, inactive workspaces,
  expired profiles, invalid lifetimes, or profiles that fail canonical
  validation.
- `preview_workspace_access_recommendation` is network-free and requires the
  current manifest, the current authority destination, and an active local
  member. Tampered, stale, expired, wrong-authority, or non-member documents
  fail closed.
- `apply_workspace_access_recommendation` requires an explicit consent boolean
  and attaches the profile with workspace scope and origin `workspace_access`.
  It does not create a contact, approve a device, change membership/authority,
  enable transport, or make the owner a relay.
- Added to the service and Rust command allowlists.

UI:

- **Workspace settings → Workspace access point** lets the owner select an
  approved profile, create/copy a recommendation, and preview/apply one.
- Any active member can paste a recommendation, review the operator disclosure,
  consent, and attach it to the workspace.
- The panel explains that the recommendation is out-of-band and that an access
  point sees connection metadata, not message contents.

Validation:

```text
pytest service/tests:        1103 passed, 46 skipped, 0 failed (285.37 s)
node scripts/run-frontend-tests.mjs: 263 passed (18 files)
node --test deploy/cloudflare-signal/worker.test.mjs: 11 passed
packaged emoji artwork verification: 3 passed
node node_modules/typescript/bin/tsc -b: passed
node scripts/run-frontend-build.mjs: passed
```

The official report is
`dist/reports/0.9.4/20261022T131527Z-ded61ce3/report.json` (git-ignored):
`status: passed`, 334.417 s, SHA-256
`76eb0cdc64b4154a672ce7b9b11bc8d2a097acdedc823836cde9f1a755d22482`.
Gates: `automated: passed`; `physical_device: not-requested`;
`production_signing: not-requested`.

Publication: GitHub Actions
[CI run 39786125795](https://github.com/ahouchens/mesh-chat/actions/runs/39786125795)
and
[Release run 39786130122](https://github.com/ahouchens/mesh-chat/actions/runs/39786130122)
passed on the first attempt for `v0.9.4`. Release:
<https://github.com/ahouchens/mesh-chat/releases/tag/v0.9.4>.

| Artifact | Bytes | SHA-256 (verified by re-download) |
|---|---:|---|
| `Mesh-Chat_0.9.4_x64-setup.exe` | 27,845,872 | `26eaa81d33498dc420a0929e806ff897d72bb43478ec1ab0660984ade92d1d89` |
| `Mesh-Chat_0.9.4_x64_en-US.msi` | 29,839,360 | `0b2eec7051ba111e703e95056b668dc92e28f975039e05039f35ad9057320f82` |
| `mesh-chat-0.9.4-android-arm64-release.apk` | 34,318,405 | `e9620c4aa7b1d2f0d214df3329edcec914251d1b937bc9789632c342eda9524c` |
| `SHA256SUMS.txt` | 300 | `cca0d17880bdfb7b05b7101ac53cf1e5855e67d6c2ff07a56c5ef114b0662047` |

The Android APK is debug-signed; it is not a production or upgrade identity.

New tests cover document round trip, tamper/expiry/invalid fields, wrong
authority rejection, owner-only creation, member preview, consent enforcement,
workspace scope attachment, command dispatch, and the renderer
create/preview/consent/apply flow. No physical multi-member access-point test
was performed.

## Workspace connectivity diagnostics, 0.9.3

Phase 1 of the [workspace connectivity spec](docs/WORKSPACE_CONNECTIVITY_SPEC.md)
makes per-device workspace reachability visible and gives users an explicit,
bounded path request. It does not create a workspace reconnect profile or an
all-to-all topology.

Service:

- `workspace_connectivity` reads the current verified manifest and existing
  per-device delivery legs and returns advisory states (`local`, `reachable`,
  `recently_reached`, `store_and_forward`, `queued`, `unreachable`, `unknown`),
  safe route labels, pending/stored counts, and last evidence times.
- `workspace_request_paths` requests Reticulum paths only for active remote
  workspace devices whose path is not currently known, then returns a fresh
  status. It does not probe endpoints, open listeners, enable transport, or
  attach a profile.
- Neither command changes membership, trust, routes, settings, or delivery
  state. A path is not presence; a propagation proof is not delivery; a
  delivery is not a read receipt.
- Both commands are in the service and Rust command allowlists.

UI:

- **Workspace → People and administration → Connectivity** shows summary counts,
  one row per member device with a state badge, route label, pending count, and
  last-reached time, plus **Request missing paths**.
- The panel explains that membership is not a route, the owner is not a relay,
  and a shared access point or propagation node is a separate topology choice.
- The panel is shared with Android; physical multi-device path, NAT/TURN, and
  suspension behavior remain unverified.

Validation:

```text
pytest service/tests:        1099 passed, 46 skipped, 0 failed (281.13 s)
node scripts/run-frontend-tests.mjs: 262 passed (18 files)
node --test deploy/cloudflare-signal/worker.test.mjs: 11 passed
packaged emoji artwork verification: 3 passed
node node_modules/typescript/bin/tsc -b: passed
node scripts/run-frontend-build.mjs: passed
```

The official report is
`dist/reports/0.9.3/20261022T122749Z-59581113/report.json` (git-ignored):
`status: passed`, 326.593 s, SHA-256
`a091344d4d73eafba9b322f39eed68ce46438936d550dea33fbc85216aaf2957`.
Gates: `automated: passed`; `physical_device: not-requested`;
`production_signing: not-requested`.

Publication: GitHub Actions
[CI run 39779352782](https://github.com/ahouchens/mesh-chat/actions/runs/39779352782)
and
[Release run 39779358050](https://github.com/ahouchens/mesh-chat/actions/runs/39779358050)
passed on the first attempt for `v0.9.3`. Release:
<https://github.com/ahouchens/mesh-chat/releases/tag/v0.9.3>.

| Artifact | Bytes | SHA-256 (verified by re-download) |
|---|---:|---|
| `Mesh-Chat_0.9.3_x64-setup.exe` | 27,838,621 | `9f32fb0e5b76c4ef4a7763a2156d68e2399557bff17ba09c420d5c67f0c5799c` |
| `Mesh-Chat_0.9.3_x64_en-US.msi` | 29,827,072 | `46554660bed5b2904450cf199ed3046d0ea845de1da2cc74fa0939240275ee8b` |
| `mesh-chat-0.9.3-android-arm64-release.apk` | 34,318,322 | `4b4056510f62eef94326503caa8f8d4fb49a02ef63c5f67b107e0de19cf3e56a` |
| `SHA256SUMS.txt` | 300 | `7085ea3108ef1039106cfe91b678de3c8b27de699469f7c811bee17c3aa794fa` |

The Android APK is debug-signed, like 0.9.2; it is not a production or upgrade
identity.

New tests cover path-known and local/remote states, missing-path state after a
route disappears, command dispatch, and path requests only for active remote
devices. No physical multi-member workspace connection was tested.

## Configurable call signaling storage, 0.9.2

Call signaling records no longer have to be sealed in the vault. The new
`store_call_signaling` call setting defaults to **on** and preserves the shipped
behavior; disabling it keeps SDP and ICE candidates in service memory so calls
still work while the process is alive, but call history and restart state are
lost on a service restart. The toggle in **Settings → WebRTC calls** explains
that existing sealed records are not deleted when it is turned off.

Service changes:

- `CallSettings.store_call_signaling` defaults to true, validates as a boolean,
  and is included in the public settings payload and vault record.
- `CallManager` writes records to both its in-memory active table and the vault
  when enabled. When disabled, create/answer/candidate/restart/hangup still work
  from memory; reads, active-call listing, rate limiting, and history pruning
  only consult memory.
- Enabling storage later adopts records created in memory; disabling it stops
  new reads/writes of sealed records but does not delete them.
- `update_call_settings` applies the setting to the running manager and
  preserves the current choice when an older client omits the field.

Validation:

```text
pytest service/tests:        1098 passed, 46 skipped, 0 failed (284.06 s)
node scripts/run-frontend-tests.mjs: 262 passed (18 files)
node --test deploy/cloudflare-signal/worker.test.mjs: 11 passed
packaged emoji artwork verification: 3 passed
node node_modules/typescript/bin/tsc -b: passed
node scripts/run-frontend-build.mjs: passed
```

The official report is
`dist/reports/0.9.2/20261022T050230Z-d2628c93/report.json` (git-ignored):
`status: passed`, 329.207 s, SHA-256
`618f4762d27aaa1eda449fa611b29af276f05d00ed23057fcd436892c6926382`.
Gates: `automated: passed`; `physical_device: not-requested`;
`production_signing: not-requested`.

Publication: GitHub Actions
[CI run 39726333832](https://github.com/ahouchens/mesh-chat/actions/runs/39726333832)
and
[Release run 39726337610](https://github.com/ahouchens/mesh-chat/actions/runs/39726337610)
passed on the first attempt for `v0.9.2`. Release:
<https://github.com/ahouchens/mesh-chat/releases/tag/v0.9.2>.

| Artifact | Bytes | SHA-256 (verified by re-download) |
|---|---:|---|
| `Mesh-Chat_0.9.2_x64-setup.exe` | 27,836,166 | `68c2477080e6e08591726cdc00256e40be8b74640c57d0d2f8113d9e84b6d79c` |
| `Mesh-Chat_0.9.2_x64_en-US.msi` | 29,822,976 | `805ae0af8a1cd5f1007afeaa6a469c1605d805bd997e5a64090be0189a6f1347` |
| `mesh-chat-0.9.2-android-arm64-release.apk` | 34,302,211 | `e2a0a6efcdc59123e31a5092d689afe5a6308e141e31cb98b52a39e5c450b785` |
| `SHA256SUMS.txt` | 300 | `324249c3d9c751e14909a5eba6e3a396c9c2d6b2c269fa251aaf6593296aaad3` |

The Android APK is **debug-signed** (`CN=Android Debug`, certificate SHA-256
`d6dbff63834666bace3d75b49234726e97ccce26d2b9e9516309682e0a33143f`). It is a
sideload build, not a production or upgrade identity; `aapt2` reports version
0.9.2 (9002), min API 24, target API 36, ARM64 only.

New tests cover the default-on behavior, memory-only calls, adopting memory
records after enabling, stopping vault writes after disabling, explicit
true/false/omitted settings, and invalid values. No physical call, NAT/TURN, or
mobile lifecycle test was performed.

## Automatic reconnect hardening, 0.9.1

A code audit of the 0.9.0 checklist found four gaps; this release closes them:

- **No peer connection before authorization.** The probing device now creates
  and publishes its signed request first, verifies the peer's signed offer, and
  only then allocates an `RTCPeerConnection`. A blocked, deleted, or rejected
  peer fails before any transport resource exists. A test asserts that a
  rejected offer produces zero peers.
- **Capabilities are not lost when the dialog closes.** A verified capability
  that arrives before its contact record is held as a signed, expiring,
  peer-bound document and promoted only after a contact exists and is approved.
  Approval messages are sent whenever the control channel is bound to the
  contact, not only while the onboarding dialog is mounted and `approvalPending`
  is set. Holding never grants trust; blocked contacts are still rejected.
- **No request/offer thrash.** The prober reuses one attempt ID and one signed
  request across retries, so a responder's offer cannot be invalidated by a
  concurrent retry. The responder bounds its offer attempts and reports **Peer
  offline** instead of looping. A per-profile stop also cancels that profile's
  in-flight loop instead of letting it overwrite the stopped state.
- **Honest status.** The connected state reports whether a Reticulum path is
  ready, still pending, or unavailable, and **Reconnecting in Ns** re-renders
  once a second instead of showing a frozen number.

Validation on this tree (Node 24, Python 3.13, Windows):

```text
pytest service/tests:        1092 passed, 46 skipped, 0 failed (275.35 s)
node scripts/run-frontend-tests.mjs: 262 passed (18 files)
node --test deploy/cloudflare-signal/worker.test.mjs: 11 passed
packaged emoji artwork verification: 3 passed
node node_modules/typescript/bin/tsc -b: passed
node scripts/run-frontend-build.mjs: passed
```

The official report is
`dist/reports/0.9.1/20261022T035845Z-4852d91b/report.json` (git-ignored):
`status: passed`, 327.746 s, SHA-256
`d5d703f625f4c24a701d0a4ad6df6c72d0d188c208bbce4b549dfc7282898f79`.
Gates: `automated: passed`; `physical_device: not-requested`;
`production_signing: not-requested`.

Publication: GitHub Actions
[CI run 39720371674](https://github.com/ahouchens/mesh-chat/actions/runs/39720371674)
and
[Release run 39720375357](https://github.com/ahouchens/mesh-chat/actions/runs/39720375357)
passed on the first attempt for `v0.9.1`. Release:
<https://github.com/ahouchens/mesh-chat/releases/tag/v0.9.1>.

| Artifact | Bytes | SHA-256 (verified by re-download) |
|---|---:|---|
| `Mesh-Chat_0.9.1_x64-setup.exe` | 27,828,710 | `df06ce6dfcda4415bbee199afd5b4d9d4fbccf368a052099a917444c6f58bec0` |
| `Mesh-Chat_0.9.1_x64_en-US.msi` | 29,822,976 | `2162598caf728f833fadabcac3ebb23806fb56ca5d1630e76f711c99b27fd17f` |
| `mesh-chat-0.9.1-android-arm64-release.apk` | 34,302,211 | `9c33d6e48683b2ac6d84c3d68f188051e58af7fd39ec76f72727001febfa97b6` |
| `SHA256SUMS.txt` | 300 | `b34c1d8fa68adaca2d53bec93f83db623d453ed31d8e7c6643b40ef7cbbc1d47` |

New tests include the pending-capability hold/promote/approval flows, explicit
capability metadata (`transports`, issued/expiry), no-peer-on-rejection,
transport-failure retry, and the live reconnecting countdown. No installer
launch, physical-device, NAT/TURN, network-switch, or mobile-lifecycle test was
performed.

## Automatic reconnect, 0.9.0

Automatic reconnect is implemented for the open, unlocked app. The Python
service owns profiles, per-contact consent, signed capabilities, mailbox
publish/fetch, verification, and durable replay state; the renderer owns the
fresh `RTCPeerConnection`. There is no background daemon, push notification,
live session migration, or iOS/Android background execution.

What is covered:

- `ConnectionCapabilities` attach to contact/workspace invitation results when
  a peer destination is supplied, and are returned by invitation acceptance and
  owner approval. Auto-reconnect defaults to off; direct IP disclosure is a
  separate flag.
- Consent changes issue a new signed capability; mailbox changes rotate the
  pair token. New capabilities are shared over the authenticated WebRTC control
  channel and only when the channel is bound to that contact.
- The Cloudflare Worker pins a SHA-256 capability hash on first authenticated
  write, requires the token for reconnect reads and writes, supports
  holder-authorized rotation, enforces request/offer/answer type matching, and
  applies per-token/per-IP rate limits. The tokenless manual onboarding path
  still works.
- The renderer coordinator starts only while the unlocked Messenger shell is
  mounted, caps concurrency at two, uses 1/2/5/15/30/60-second jittered backoff,
  and stops on consent removal, blocked/deleted peers, rejected capabilities,
  or user cancellation. It never opens a dialog or asks for contact approval.
- Only the preferred device publishes a request; the other side creates the
  single offer. Simultaneous starts therefore produce one offer.
- After attach, `webrtc_attach` reannounces immediately and at 2 s and 6 s; the
  coordinator polls path status and distinguishes `path_not_ready` from
  `network_unavailable`.
- A missing mailbox reports **Manual reconnect required** and opens no peer
  connection.

Validation on this tree (Node 24, Python 3.13, Windows):

```text
pytest service/tests:        1089 passed, 46 skipped, 0 failed (270.66 s)
node scripts/run-frontend-tests.mjs: 260 passed (18 files)
node --test deploy/cloudflare-signal/worker.test.mjs: 11 passed
packaged emoji artwork verification: 3 passed
node node_modules/typescript/bin/tsc -b: passed
node scripts/run-frontend-build.mjs: passed
```

The service count includes 17 reconnect-service tests, 6 protocol tests, and 11
mailbox-token tests. The frontend count includes 9 coordinator tests, 5 control
channel tests, and 4 contact-panel tests. The full pipeline was run with
`MESH_CHAT_NODE` pointing at Node 24 because the machine's default `node` is
older than the project minimum. The run is recorded in
`dist/reports/final-test-090.log` (not committed). The six workspace-admission
failures previously reported in `test_direct_setup_pipeline.py` did not
reproduce in this run; the 46 skips are opt-in native/network harnesses.

The official pipeline report is
`dist/reports/0.9.0/20261022T024828Z-54433a88/report.json` (git-ignored):
`status: passed`, 304.822 s, report SHA-256
`9c7b833bfcab078f6334b93ef521ee9a78b6184bcf7647e7fbaeb3cbdd97e0b8`.
Gates: `automated: passed`; `physical_device: not-requested`;
`production_signing: not-requested`.

Publication: GitHub Actions
[CI run 39713907074](https://github.com/ahouchens/mesh-chat/actions/runs/39713907074)
and
[Release run 39713914888](https://github.com/ahouchens/mesh-chat/actions/runs/39713914888)
passed after retries. The early attempts failed before checkout in the
`Set up pnpm and Node.js` step with
`Could not reach https://registry.npmjs.org/... : timed out after 30s`; the same
step succeeded on retry and every test/build/publish job then passed. This was a
runner-to-registry fetch timeout, not a source or test failure. Release:
<https://github.com/ahouchens/mesh-chat/releases/tag/v0.9.0>.

| Artifact | Bytes | SHA-256 (verified by re-download) |
|---|---:|---|
| `Mesh-Chat_0.9.0_x64-setup.exe` | 27,831,976 | `5c805e678bd2ae43fe2ccd7d8d788d266222bc6b2fc6b99479b9647edd186a89` |
| `Mesh-Chat_0.9.0_x64_en-US.msi` | 29,822,976 | `d8ee753f9870a99688616a534a6a54f7f90fcc43a2d2998af8188237c5589ad5` |
| `mesh-chat-0.9.0-android-arm64-release.apk` | 34,302,180 | `3516527a138ac13e866cd8433b9cddc69f6e4ebd5a185ac975d62eb58913eed8` |
| `SHA256SUMS.txt` | 300 | `07cdecb3f104213ba93582b1fd9c54967e75f6324c68f0b386d52675f3a81705` |

Not performed for this change: installer launch, two physical devices, real
NAT/TURN traversal, network switching, Android/iOS lifecycle or battery
behavior, and any claim that reconnect works while an app is closed. The packages
are CI-built release artifacts, not device-tested builds.

## Copied workspace invitation regression, 2026-10-18

The follow-up already-saved-workspace screen includes the local public status in
invitation previews and offers **Open saved workspace** instead of a duplicate
join. The exact resumable request retains **Continue saved request** and return
connection recovery. Preview uses the same read-only validation as submission;
a fresh nonce or terminal request cannot overwrite the saved join. Regressions
cover active, pending, and failed workspaces, navigation to existing settings,
unchanged encrypted records, and rejection of mismatched saved requests.

`test_workspace_join_retry.py` covers a valid email-ready invitation followed by
join submission, retry after a lost response, reopening the encrypted profile,
and preservation of the original device, delivery, and signed receipt. Recovery
rejects a different invitation, mismatched local identity, and terminal requests.
Accepted profile names are normalized before signing the local join. Mobile bridge
tests cover the former 64 KiB preview/submit size mismatch and native payload bounds.
UI tests cover retaining the operation ID after a timeout and actionable errors
for an existing workspace or the workspace limit. These are source regressions;
the reported Android screenshot alone does not identify the exact validation
failure, and a rebuilt APK still requires testing on the affected device.

Local validation passed 195 tests across the join retry/receipt, workspace
service/protocol, mobile bridge, and email routing suites, plus 147 frontend
tests across App, invitation transfer, and API. TypeScript `--noEmit` and
`git diff --check` passed. No native or release build was performed.

## Android direct-reply failure diagnosis, 2026-10-18

The installed 0.2.63 build reported `build_commit: e361c70…`. That commit is a
strict descendant of the qualified application source `34d9927…` and differs
from it only by the LICENSE file, license metadata, and documentation:
`git diff --name-status 34d9927 e361c70` lists no `service/src`, `src`,
`src-tauri/src`, or protocol change. The branch base `7867e71` likewise has no
code difference from `34d9927`. The installed application code therefore
matches the qualified 0.2.63 source; the earlier “commit absent from local
objects” observation was a stale-clone problem, not evidence of a different
build. `service_version: unavailable` is expected because Android embeds
`service/src` without installing the service distribution metadata; it is not a
version mismatch.

Source reproduction established one concrete pre-setup failure. A **different**
invitation for a workspace that already has a saved join request passes
document-only preview, then fails the exact saved-invitation check inside
`prepare_direct_answer`. An active or terminal saved workspace behaves the same
way. Both now return `workspace_already_known` with an allowlisted reason
(`invitation_mismatch`, `workspace_active`, `request_stopped`, and so on)
instead of an opaque `identity_mismatch`. The saved request, identity, delivery,
receipt, and queued messages are unchanged; a matching invitation still
prepares a newer Answer generation against the same saved request.

Preview now supplies read-only saved-workspace evidence, and the wizard routes a
non-matching or already-active workspace to **Open saved workspace** rather than
offering a doomed **Prepare reply**. Diagnostics add `failure_reason`,
`workspace_state`, and up to 12 recent events to a summary copy. A closed native
channel now reports `native_unavailable` at `runtime_check` so an earlier
timeout/pump stop is distinguishable from document or persistence failures.

Validation at this revision:

```text
.venv\Scripts\python.exe -m pytest service/tests/test_direct_setup.py \
  service/tests/test_direct_native.py service/tests/test_connection_diagnostics.py \
  service/tests/test_mobile_bridge.py service/tests/test_service_process.py \
  service/tests/test_direct_documents.py service/tests/test_direct_readiness.py \
  service/tests/test_workspace_join_retry.py service/tests/test_workspace_join_receipt.py \
  service/tests/test_release_version.py service/tests/test_workspace_service.py \
  service/tests/test_service_invitation_refresh.py service/tests/test_workspace_protocol.py \
  -q
```

Result: **297 passed**. The full local service suite also passed **954 passed,
46 skipped** (opt-in native/packaged/network harnesses remain skipped). The
Windows checkout needed the tracked Twemoji manifest restored to LF so its
recorded hash matched; that is a line-ending-only working-copy artifact, not a
source change. The pre-change focused baseline was 43 passed. Frontend
regressions were added for the saved-workspace panel, reason-specific guidance,
input retention, and the new diagnostic fields; frontend/package execution,
TypeScript compilation, Windows/Android builds, and installation belong in
GitHub Actions. `git diff --check` passed locally.

The local cause of this specific device failure is still unconfirmed. A
distinct **0.2.64 / Android 2064** test build and its exact evidence-collection
procedure are described in
[the reply-failure device check](docs/DIRECT_REPLY_FAILURE_DEVICE_TEST.md).
No physical Windows-to-Android connectivity is claimed; the provenance check
above identifies the earlier artifact, not a successful connection.

## Reachability planner increment, 2026-10-19

The setup wizard now exposes an evidence-based plan instead of one opaque
"Check this device" result. The design and acceptance criteria are in
[REACHABILITY_PLANNER_SPEC.md](docs/REACHABILITY_PLANNER_SPEC.md). The
implementation adds:

- per-protocol PCP/UPnP/NAT-PMP attempt evidence and IPv6 pinhole evidence;
- explicit upstream-NAT/CGNAT blockers;
- a validated manual UDP endpoint in `prepare_direct_offer` and
  `prepare_direct_answer`, signed into the existing Offer/Answer;
- a temporary, exact **UDP** Windows firewall rule command
  (`configure_direct_firewall`) with protocol-specific cleanup;
- a wizard plan with one primary action, manual-forward form, firewall
  consent, and a terminal blocked explanation;
- allowlisted network failure reasons in diagnostics, still without
  addresses or invitation contents.

Validation:

```text
.venv\Scripts\python.exe -m pytest service/tests/test_reachability.py \
  service/tests/test_direct_setup.py service/tests/test_direct_candidates.py \
  service/tests/test_connectivity_roadmap.py service/tests/test_direct_readiness.py \
  service/tests/test_connection_diagnostics.py service/tests/test_direct_native.py \
  -q
```

Result: **127 passed**. The full local service suite, excluding the legacy
`test_production_setup_bootstrap_admission_and_fresh_workspace_path` cases,
passed **958 with 40 expected skips** (12 deselected). Those 12 source/native
pipeline cases also fail at preceding commit `203f1b4` on this machine before
these changes, so the failure is not attributed to this increment. Frontend
regressions were added for the plan, firewall action, manual form, and
diagnostic fields; frontend/TypeScript/package execution, Windows/Android
builds, and physical device validation remain in GitHub Actions.

The candidate is **0.2.65 / Android 2065**. GitHub Actions
[run 39200607637](https://github.com/ahouchens/mesh-chat/actions/runs/39200607637)
passed Verify, Windows packaging, and Android packaging. The Android APK is
34,049,543 bytes with SHA-256
`b463fb9415a6d04b06714a5fb1872a0d454634d5ca941711ef69851f38b772f2`;
the NSIS installer is SHA-256
`731649f59ba339795a357d6ad8bcdeb0de21d135a9da02cdd9d084da759fdc89`
and the MSI is
`2b6d45c3d4b65f2456c8cc9b03a8279c3b72cb4dc2635e098151e089d1b16bbf`.
The APK reports versionName 0.2.65, versionCode 2065, package
`com.meshchat.mobile`, arm64-v8a, target API 36, and the established
development certificate `d6dbff63834666bace3d75b49234726e97ccce26d2b9e9516309682e0a33143f`.
It has not been installed or executed here, and no physical connectivity result
is claimed.

## Windows default-route address fix, 2026-10-19

The 0.2.63 Windows diagnostic from the pairing test showed
`no_local_address`, `route: unavailable`, `mapping: not_needed`, and zero
candidates, even though the machine had an active Wi-Fi default route. The
cause was deterministic: Reticulum's `netinfo` exposed Windows interfaces as
GUIDs, while `Get-NetRoute` reported the friendly alias `Wi-Fi`. The local
address lookup used the alias as a dictionary key, so it returned `None`; the
service then bound `0.0.0.0`, skipped every router-mapping attempt, and exported
an invitation with no candidate.

`_windows_default_routes` now selects `InterfaceIndex` and resolves addresses
through `Get-NetIPAddress` by that stable index. The friendly alias remains a
fallback for existing tests and unusual environments. A regression with GUID
interface keys verifies that an active Wi-Fi route, a private IPv4 address, and
a global IPv6 address are all recovered.

After the fix, the same machine reports `route_available=True`,
`mapping_attempted=True`, then:

- PCP: `pcp_no_response`
- UPnP: `upnp_wan_shared`
- NAT-PMP: `nat_pmp_no_response`
- planner: `upstream_nat` blocked

That is a separate network fact, not a route bug: the router reports a shared
upstream address (carrier-grade or double NAT). A local router mapping cannot
make this Windows machine publicly reachable. The app now reports that honestly
instead of saying it found no local address. IPv6, a public IPv4/bridge mode,
an upstream forward, or an explicitly approved relay/access point are the
remaining options for this pair.

Validation: **115 focused tests passed**; the full local service suite passed
**960 with 40 expected skips** and the same 12 deselected legacy setup-pipeline
cases, which also fail at the preceding commit on this machine. Candidate:
**0.2.66 / Android 2066**.

GitHub Actions
[run 39322819112](https://github.com/ahouchens/mesh-chat/actions/runs/39322819112)
passed Verify, Windows packaging, and Android packaging. The Android APK is
34,049,597 bytes with SHA-256
`3a996a3399dca369082baaeb35b39544eb4ca08235884e9ecd4eab2c207c373b`;
the NSIS installer is SHA-256
`b63ad9e0ab6d2e3617e7bbc574c12ac0b78df5546ba480fa30cde9baad66e824`
and the MSI is
`88f3b875b79899da933dd9e48513658fc1416a008f71e06c58124b2582776a2b`.
The APK reports versionName 0.2.66, versionCode 2066, package
`com.meshchat.mobile`, arm64-v8a, target API 36, and the established
development certificate
`d6dbff63834666bace3d75b49234726e97ccce26d2b9e9516309682e0a33143f`.
It has not been installed or executed here, and no physical connectivity result
is claimed.

The upstream-NAT UI is corrected in **0.2.67 / Android 2067**. When a mapping
attempt reports a shared or upstream NAT, the plan now reports only the
`upstream_nat` blocker, marks manual forwarding unavailable, and points to
IPv6, another network, or an approved access point. The renderer hides the
manual-forward action and no longer advises restoring the Internet connection.
Validation: **107 focused tests** and **15 version/planner tests** passed. GitHub
Actions
[run 39325462261](https://github.com/ahouchens/mesh-chat/actions/runs/39325462261)
passed Verify, Windows packaging, and Android packaging. The APK is 34,049,529
bytes with SHA-256
`fa65bdaa93cd05e492df8b66ca4b4babc2dab8315186c1d95aefafcc4cfbdd0f`;
the NSIS installer is SHA-256
`5aaf194762c4901faf67a7a9004e1f3a254dea8adfce51d8e7db082f72de5413`
and the MSI is
`44f08297e5b5de34e6da17cdb6ad305309a89df123459984a029e936f825be76`.
The APK reports versionName 0.2.67, versionCode 2067, package
`com.meshchat.mobile`, arm64-v8a, target API 36, and the established
development certificate
`d6dbff63834666bace3d75b49234726e97ccce26d2b9e9516309682e0a33143f`.

The upstream classification and plan layout are extended in **0.2.68 / Android
2068**. A shared `100.64/10` UPnP WAN address is reported as carrier-grade NAT
with **UDP port forward: Not possible**; a private WAN address is reported as
double NAT with **UDP port forward: Maybe** and a manual-forward action for both
routers; unclassified upstream evidence asks for the router WAN address. The
plan rows now have padding, borders, and separated reason text, and the
upstream card is a distinct block. Validation: **109 focused tests** and the
full local service suite **962 passed, 40 expected skips, 12 deselected**.
GitHub Actions
[run 39328374254](https://github.com/ahouchens/mesh-chat/actions/runs/39328374254)
passed Verify, Windows packaging, and Android packaging. The APK is 34,049,645
bytes with SHA-256
`0f42b3be1202e06b6842c154e9800406030d578fe4315d891e4b19a6ef8006c3`;
the NSIS installer is SHA-256
`aa742c7fd1ac615281052db6fe0d6b9784615bdbfccf51f426db1eeac68807a1`
and the MSI is
`8bd1ece15e1e1e0a20a41f0c29c0dc7757cf2d4383de9add29d8706e85cbaf3c`.
The APK reports versionName 0.2.68, versionCode 2068, package
`com.meshchat.mobile`, arm64-v8a, target API 36, and the established
development certificate
`d6dbff63834666bace3d75b49234726e97ccce26d2b9e9516309682e0a33143f`.

## I2P foundation, 2026-10-19

The first I2P increment adds the opt-in Windows transport foundation described
in [I2P_SUPPORT_SPEC.md](docs/I2P_SUPPORT_SPEC.md):

- `NetworkSettings` fields for `i2p_enabled`, `i2p_connectable`, and up to four
  validated `*.b32.i2p` peer addresses;
- an additive `[[I2P]]` `I2PInterface` block written only when enabled;
- a renderer-safe `i2p_status` command and native allowlist entry;
- a Settings section with the relay disclosure, access-point input, connectable
  mode, and local access-point status.

This is **I1**, not a completed I2P feature. The machine used for this work has
no `i2pd` and no SAM listener on `127.0.0.1:7656`, so the I0 protocol spike and
physical I2P delivery were not executed here. No end-to-end I2P connectivity is
claimed. Invitation/workspace integration is I3 and remains unimplemented.

Validation: **974 service tests passed** with 40 expected skips and the same 12
deselected legacy setup-pipeline cases. GitHub Actions
[run 39333587879](https://github.com/ahouchens/mesh-chat/actions/runs/39333587879)
passed Verify, Windows packaging, and Android packaging. The APK is 34,049,525
bytes with SHA-256
`a932d7df7659eabd4812248a8b9b5e289a19b052ce805c4a2225693bd352c15e`;
the NSIS installer is SHA-256
`fef3b70ec98e8d6ebffebc977ed1ec69c0925f04c9d050c41e0ef588ba521d95`
and the MSI is
`d7bedcefab89b97aa78274641eb8f9c8ac081d49e4ec462a8b1a84babe86d1af`.
The APK reports versionName 0.2.69, versionCode 2069, package
`com.meshchat.mobile`, arm64-v8a, target API 36, and the established
development certificate
`d6dbff63834666bace3d75b49234726e97ccce26d2b9e9516309682e0a33143f`.

## I2P transport and managed router, 2026-10-19

I0 was executed on Windows with a real `i2pd` 2.61.0 and two independent
Reticulum instances:

- A was a `connectable` I2P access point with a stable `b32.i2p` address;
- B was a client-only peer configured with that address;
- B's I2P interface reached `online`, resolved a path to A's destination, and
  delivered a Reticulum packet;
- A received the exact payload.

This proves Reticulum transport over I2P, not full LXMF/workspace delivery.
LXMF and workspace join over I2P still need the I3 integration test.

I2 adds an opt-in managed Windows router:

- `I2PRouterManager` starts a local `i2pd` before Reticulum, waits for SAM on
  `127.0.0.1:7656`, and stops it on service shutdown;
- SAM is localhost-only; the web console, HTTP/SOCKS proxies, UPnP, and transit
  relaying are disabled; the router uses the low bandwidth profile;
- i2pd 2.61.0 and its BSD-3-Clause license are bundled as Windows resources;
- the Rust launcher passes the installed resource path to the sidecar.

The 0.2.70 MSI was administratively extracted without installation and
contained `_up_/vendor/i2pd.exe` plus its license. The manager started and
stopped that installed binary successfully. A path-only follow-up resolves both
`vendor/i2pd.exe` and `_up_/vendor/i2pd.exe`.

Validation: **978 service tests passed** with 40 expected skips and the same 12
deselected legacy setup-pipeline cases before the path-only follow-up;
**22 focused tests** passed for the follow-up. GitHub Actions
[run 39339281467](https://github.com/ahouchens/mesh-chat/actions/runs/39339281467)
built 0.2.70, and
[run 39341205361](https://github.com/ahouchens/mesh-chat/actions/runs/39341205361)
built the final **0.2.71** candidate. The APK is 34,049,462 bytes with SHA-256
`c5e1d166cd27aa8c927a397dced208128b9e1df4ab81a3cc224877539a2f5255`;
the NSIS installer is SHA-256
`2212f236c5bb62ba3a247159de0385227b91abf45698b09130a3d56e93c84b80`
and the MSI is
`e9ee8295636a1672030738019c9c0e1b6834c6bfec1ff457cf5d5fe9b1adf6aa`.
The APK reports versionName 0.2.71, versionCode 2071, package
`com.meshchat.mobile`, arm64-v8a, target API 36, and the established
development certificate
`d6dbff63834666bace3d75b49234726e97ccce26d2b9e9516309682e0a33143f`.
No physical installer run or end-to-end LXMF/workspace test is claimed.

## I2P invitation integration, 2026-10-19

0.2.72 adds an additive signed I2P wrapper around the existing personal and
workspace invitation:

- `MESHI2P1:` / `MESHI2P1W:` carry a canonical signed descriptor with the
  complete inner invitation, its SHA-256 digest, one validated `b32.i2p`
  access point, expiry, and the owner public key;
- verification binds the wrapper signer to the inner invitation owner and
  rejects altered descriptors, foreign signers, expired wrappers, and
  purpose mismatches;
- the personal and workspace invite dialogs offer an I2P access-point mode;
- join previews show the relay disclosure and b32;
- accepting or joining adopts the access point into I2P settings, which takes
  effect after restart. The saved request remains queued until then.

The inner signed invitation, single-use nonce, replay protection, and approval
semantics are unchanged. This is not yet a proven end-to-end workspace join
over I2P: the wrapper and settings adoption are tested, but no two-device
workspace approval/receipt test over I2P has been run.

Validation: **90 focused service tests passed**, including five wrapper tests.
GitHub Actions
[run 39343424932](https://github.com/ahouchens/mesh-chat/actions/runs/39343424932)
passed Verify, Windows packaging, and Android packaging. The APK is 34,066,003
bytes with SHA-256
`94d84d6ddcbcf569b224b7338e8db1a9430b113c8f86fd0b19e098f5a2cd77b3`;
the NSIS installer is SHA-256
`4df07e2e962ca3ed1368a9bce5b9a57bcdf089fb078cf8747c460a3f84bb8d2b`
and the MSI is
`1662f13177bc064463185529aefcbf0a641dba11c0c186f8df748c78eb159258`.
The APK reports versionName 0.2.72, versionCode 2072, package
`com.meshchat.mobile`, arm64-v8a, target API 36, and the established
development certificate
`d6dbff63834666bace3d75b49234726e97ccce26d2b9e9516309682e0a33143f`.

### Coverage expansion, 0.2.73

The I3 gap analysis added:

- service-level personal I2P creation → preview → accept → settings/config
  adoption;
- normal personal invitation regression;
- workspace I2P creation and preview;
- workspace foreign-signer and excess-expiry rejection;
- managed router SAM-timeout, process-exit, and shutdown cleanup;
- personal invite UI selection, b32 validation, and create payload.

Validation: **74 focused service tests passed**. GitHub Actions
[run 39344867270](https://github.com/ahouchens/mesh-chat/actions/runs/39344867270)
passed Verify, Windows packaging, and Android packaging. The APK is 34,065,900
bytes with SHA-256
`f7ed71f5172fa00adc378014ac5cbdce91171a4e7994ce66d0ce7703f6061c5e`;
the NSIS installer is SHA-256
`cb69f38eb1078790d125394b356f45c169f8efebc0b47d8a233a7b1bf2fdb9b4`
and the MSI is
`3eef3a7613ac4bfd794921a3b6241106b90f2a59f1e6f4dc1d730e99f2336aaa`.
The APK reports versionName 0.2.73, versionCode 2073, package
`com.meshchat.mobile`, arm64-v8a, target API 36, and the established
development certificate
`d6dbff63834666bace3d75b49234726e97ccce26d2b9e9516309682e0a33143f`.

Still missing: a real two-device workspace approval/receipt over I2P, Android
I2P router support, and a dedicated consent checkbox/service flag. No physical
installer run is claimed.

The consent gap is closed in **0.2.75 / Android 2075**: accepting an I2P
personal invitation or submitting an I2P workspace join now requires an
explicit `i2p_consent` flag, all three join views add the checkbox, and creating
an invitation adopts the access point on the inviter side when it is not the
connectable access point. Validation: **67 focused service tests passed**;
GitHub Actions
[run 39352529585](https://github.com/ahouchens/mesh-chat/actions/runs/39352529585)
passed Verify, Windows packaging, and Android packaging. The APK is 34,065,938
bytes with SHA-256
`562e18c14777c39982989e379c0a371c1e48ba9970f35d700c930fea0a78156c`;
the NSIS installer is SHA-256
`e9fb4d048ff2a66e1b6cb47400954e2e3719a18b4a70b42161bdf096af27fd3a`
and the MSI is
`436b6921a129bdfa1fe5cc88d106521a42570278090e2007c037e7f4e977448e`.
The APK reports versionName 0.2.75, versionCode 2075, package
`com.meshchat.mobile`, arm64-v8a, target API 36, and the established
development certificate
`d6dbff63834666bace3d75b49234726e97ccce26d2b9e9516309682e0a33143f`.
An intermediate 0.2.74 build failed five frontend assertions because normal
invitations carried `i2p_consent: false`; 0.2.75 sends the field only for I2P
previews.

## Durable Object signaling mailbox, 2026-10-21

- Replaced the KV signaling mailbox with one Durable Object per session.
- Strongly consistent offer/answer storage.
- Alarm-based expiry removes documents after ten minutes.
- Worker checks document type and size.
- No KV namespace required; `wrangler deploy` creates the SQLite-backed class.
- Worker syntax check passed.

This was the mailbox infrastructure baseline. The 0.9.0 follow-up added pair
capability tokens, request/offer/answer roles, token rotation, rate limits, the
service reconnect API, the renderer coordinator, and the per-contact UI; see
[Automatic reconnect, 0.9.0](#automatic-reconnect-090) above.

## Reconnect capabilities, 2026-10-21

- Added signed `ConnectionCapabilities` with transport list, mailbox
  capability, auto-reconnect/IP-disclosure consent, relay scope, and expiry.
- Added canonical signature verification, expected-signer binding, tamper
  rejection, and strict mailbox/expiry validation.
- Added deterministic initiator and bounded replay-cache primitives.
- Added signed reconnect request/offer/answer documents with sender,
  recipient, attempt, session, offer-digest, SDP, DTLS, and expiry binding.
- **6** reconnect tests passed.

The primitives were later wired to invitations, service persistence, the
renderer coordinator, and the contact UI in 0.9.0.

## Transport choices and pairing resume, 0.8.2

- Connect exposes Direct TCP, approved access point, WebRTC, and I2P choices.
- Direct/I2P open the invitation flow with a matching initial connection mode.
- Mailbox pairing codes persist for ten minutes and can be resumed after a
  restart.
- WebRTC transport close is exception-safe.

Validation: TypeScript and **242 frontend tests** passed.
GitHub Actions [run 39705263840](https://github.com/ahouchens/mesh-chat/actions/runs/39705263840)
passed. Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.8.2>.

| Artifact | SHA-256 |
|---|---|
| `Mesh-Chat_0.8.2_x64-setup.exe` | `98401dc55cb6e4cbf72181c734bbcdbe3e4d07cc8c5c4f4ee003fd1636cc462d` |
| `Mesh-Chat_0.8.2_x64_en-US.msi` | `a8e8c219cad37344a7bdc0bfcb23efa4561a027fc66da6bc557c0822a03271c8` |
| `mesh-chat-0.8.2-android-arm64-release.apk` | `a388ef44b409fca9ceb11664c7ed445190063982b81931a81cc6f8a767116562` |

## Pairing resume, 2026-10-21

- Mailbox pairing codes are persisted for ten minutes.
- Connect shows **Resume pairing** for a pending joiner-side code.
- Resuming reopens the WebRTC dialog with the saved code and re-fetches the
  signed offer.
- Approved pairings clear the saved code.
- Expired or malformed entries are discarded.

Validation: TypeScript and **242 frontend tests** passed.

## Transport choices, 2026-10-21

- Connect now exposes Direct TCP/same-network, approved access point, WebRTC,
  and I2P choices.
- Direct/I2P choices open the invitation flow with the matching initial
  connection mode.
- `ConnectionTransport` descriptor and WebRTC close-order tests added.

Validation: TypeScript and **239 frontend tests** passed.

## Connection fixes and entry consolidation, 0.8.1

- Removed the sidebar New chat button; invitations start at Connect.
- Removed the legacy WebRTC bridge option from invitation forms.
- Fixed mailbox settings persistence and relay-consent preservation.
- Gated approval acknowledgements on the pending WebRTC session.
- Made mailbox publish best-effort, reset stale pairing codes, and closed the
  control channel during cleanup.
- Synchronized an open offerer dialog after owner approval.
- Added service regression coverage for mailbox settings and publish/fetch.

Validation: TypeScript, **237 frontend tests**, and signal/settings tests
passed. The full service suite retains six pre-existing
`test_direct_setup_pipeline.py` workspace-admission failures, reproduced on
the 0.8.0 baseline.

GitHub Actions [run 39698761052](https://github.com/ahouchens/mesh-chat/actions/runs/39698761052)
passed. Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.8.1>.

| Artifact | SHA-256 |
|---|---|
| `Mesh-Chat_0.8.1_x64-setup.exe` | `a69bb5d5c775b3985537ed251c5057655009fbd652427839f055ba5be1259575` |
| `Mesh-Chat_0.8.1_x64_en-US.msi` | `a9d45b69358de9cc478b5ca2102e2a6eda80c4ee7bb39b03669a00d1542f7498` |
| `mesh-chat-0.8.1-android-arm64-release.apk` | `6f6444a61b08fbfb3a80456f02c19e716bda015e97854051b04014a6aca0262b` |

## Connect entry consolidation, 2026-10-21

- Removed the redundant sidebar **New chat** button; invitation entry now
  starts from **Connect → Invite someone**.
- Updated the 21 affected frontend test interactions.
- Owner approval also updates an open offerer WebRTC dialog via the
  `meshchat:approval` event, so it no longer stays on “waiting approval” when
  the approval happened outside the control-channel path.
- Control-channel acknowledgement remains gated on `approvalPending`.

Validation: TypeScript and **237 frontend tests** passed.

## Connection review fixes, 2026-10-21

Bugs found while auditing the mailbox/connection changes:

- `update_call_settings` rejected `signal_mailbox_url` because the command
  allowlist was not updated; the URL could never be saved.
- enabling relay from the WebRTC dialog rebuilt the settings payload without
  the mailbox URL, silently clearing it.
- approval acknowledgements were sent over whichever control channel happened
  to be open; they are now gated on the session’s `approvalPending` flag.
- mailbox publish failures made the whole offer/answer step fail even though
  the signed document was still usable; publishing is now best-effort.
- reviewing by mailbox code left `offerDocument` set to the code instead of
  the signed offer.
- dialog cleanup did not close the control DataChannel.
- mailbox codes could survive a new offer and fetch an old answer; they are
  reset when a new offer/review starts.
- pairing deep links could overwrite an already active offer; they now apply
  only when no peer connection exists.

Regression coverage added for accepting and preserving
`signal_mailbox_url` through a relay-consent update.

Validation: TypeScript, **237 frontend tests**, and the settings/service tests
passed.

## Connection UX release, 2026-10-21

**0.8.0 / Android 800** packages the connection improvements:

- unified Connect entry;
- inline relay consent and relay retry;
- approval acknowledgement over the control channel;
- Direct/Relayed path state and pending-request actions;
- optional Cloudflare signaling mailbox with short-code and QR pairing;
- `meshchat://pair/<code>` deep links;
- reconnect and diagnostics actions;
- `ConnectionTransport` boundary.

Validation: TypeScript, **237 frontend tests**, and production build passed.
GitHub Actions [run 39693211475](https://github.com/ahouchens/mesh-chat/actions/runs/39693211475) passed.
Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.8.0>.

| Artifact | SHA-256 |
|---|---|
| `Mesh-Chat_0.8.0_x64-setup.exe` | `5dbdb45aed2cd82eeac5e3bd829462512de2bff8bb35a6338814b36fdeab3361` |
| `Mesh-Chat_0.8.0_x64_en-US.msi` | `2d01ef5b2a19b17ffd1f6b09951f9d5f5ce883c8e13352318ef38a848c8d9f74` |
| `mesh-chat-0.8.0-android-arm64-release.apk` | `dbe8f5fa6e50d78e1ec94558a3512d227d3b0e9dceadecd5fffa1acd1d8e8522` |

## Signaling mailbox UI, 2026-10-21

**0.7.0 / Android 700** wires the optional mailbox into the WebRTC flow:

- Settings accepts a signaling mailbox URL.
- Creating an offer publishes it and shows a short pairing code.
- Joining accepts either the full offer or the pairing code.
- The answer is published automatically.
- The offerer can fetch the answer from the mailbox.
- Documents remain signed; the mailbox only stores them for ten minutes.

Validation: TypeScript, **237 frontend tests**, and production build passed.

Validation: TypeScript, **237 frontend tests**, and production build passed.
GitHub Actions
[run 39691011372](https://github.com/ahouchens/mesh-chat/actions/runs/39691011372)
passed Verify, Windows packaging, Android packaging, and Publish.
Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.7.0>.

| Artifact | SHA-256 |
|---|---|
| `Mesh-Chat_0.7.0_x64-setup.exe` | `4c237fe310a791fea6943f1bf729727866251a68333369231e62b199eb217a92` |
| `Mesh-Chat_0.7.0_x64_en-US.msi` | `26467983f56f219cca6ebb35dc0aa82eb797300d12b94296a0813c9ae420bb9b` |
| `mesh-chat-0.7.0-android-arm64-release.apk` | `6dd5b3097491f6cf9f95ff48f4629bf804b2a7bb90d0078fa2fd7df5489e785e` |

## Connection fallback action, 2026-10-21

**0.6.1 / Android 601** adds **Use invitation instead** to the WebRTC failure
state, opening the signed invitation flow without leaving the user at a dead
end.

Validation: TypeScript and **237 frontend tests** passed.
GitHub Actions
[run 39688768675](https://github.com/ahouchens/mesh-chat/actions/runs/39688768675)
passed Verify, Windows packaging, Android packaging, and Publish.
Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.6.1>.

| Artifact | SHA-256 |
|---|---|
| `Mesh-Chat_0.6.1_x64-setup.exe` | `520bbc3c40de0ff010843c1ea435200b3a887fd23ea80f254a8beee7abd7c009` |
| `Mesh-Chat_0.6.1_x64_en-US.msi` | `a64654e9ffa855f71a79554a7096c420707c2fbf4d6682be2802ea8dc14a1110` |
| `mesh-chat-0.6.1-android-arm64-release.apk` | `c0f444824a5060be04fc1e8071f3c3206c1cc029c1d19c8b80adbf4f9929c720` |

## Unified Connect entry, 2026-10-21

**0.6.0 / Android 600** adds a single **Connect** entry:

- Invite someone opens the existing signed invitation flow in Invite mode.
- I have an invitation opens it directly in Join mode.
- WebRTC direct or relay opens the signed offer/answer dialog.
- The connection card now includes **Review request** when a contact approval
  is pending, not just a count.
- Existing New chat/new group controls remain for compatibility.

Validation: TypeScript, **237 frontend tests**, and production build passed.
GitHub Actions
[run 39686945291](https://github.com/ahouchens/mesh-chat/actions/runs/39686945291)
passed Verify, Windows packaging, Android packaging, and Publish.
Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.6.0>.

| Artifact | SHA-256 |
|---|---|
| `Mesh-Chat_0.6.0_x64-setup.exe` | `3bb516392585a16c5e7dd23505093f9b959a401d51739688a289b43ef1708a46` |
| `Mesh-Chat_0.6.0_x64_en-US.msi` | `ec938c43fbf7a3ee37e754db5947fe4a7ed9aab1259cc78a34a67fe63db8d344` |
| `mesh-chat-0.6.0-android-arm64-release.apk` | `82aa618ee1f45cdb436f10132373ba1d22325c1109207e6fad946a53a5ee5f58` |

## Connection card path state, 2026-10-21

**0.5.1 / Android 501** adds path state to the persistent WebRTC connection:

- the session object records `direct`, `relayed`, or `unknown`;
- after the bridge connects, stats inspect the selected candidate pair and
  classify relayed paths;
- the persistent banner shows **Direct** or **Relayed**;
- the banner shows the number of pending contact approvals.

Validation: TypeScript, **237 frontend tests**, and production build passed.
GitHub Actions
[run 39684042623](https://github.com/ahouchens/mesh-chat/actions/runs/39684042623)
passed Verify, Windows packaging, Android packaging, and Publish.
Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.5.1>.

| Artifact | SHA-256 |
|---|---|
| `Mesh-Chat_0.5.1_x64-setup.exe` | `f78bc649aa528e1e895a5184fca8bc1765ec10c243bc47c68f9f0d528c3c6c53` |
| `Mesh-Chat_0.5.1_x64_en-US.msi` | `86f33a9a01b10f654545bfff895c9f8e7633aba79bb2ac405ae5e6e2005eb82d` |
| `mesh-chat-0.5.1-android-arm64-release.apk` | `aefe44ad67e433624698e8070456ae49f773d452cb5eb7e9b38c7d565a6f3b44` |

## Connection UX phase 1, 2026-10-21

**0.5.0 / Android 500** implements the first connection-UX phase:

- the WebRTC chooser shows an inline relay-consent card when the default
  broker is configured but not enabled;
- enabling relay from that card persists `turn_broker_consent` through the
  existing encrypted settings path;
- the joiner receives `invitation_approved` or `invitation_denied` over the
  authenticated `mesh-onboarding` control channel after owner action;
- the joiner’s waiting state resolves to **Contact approved. You can start
  messaging.** instead of waiting indefinitely;
- the spec is at `docs/CONNECTION_UX_ARCHITECTURE.md`.

Validation: TypeScript and **237 frontend tests** passed.
GitHub Actions
[run 39676192689](https://github.com/ahouchens/mesh-chat/actions/runs/39676192689)
passed Verify, Windows packaging, Android packaging, and Publish.
Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.5.0>.

| Artifact | SHA-256 |
|---|---|
| `Mesh-Chat_0.5.0_x64-setup.exe` | `187a640cb9c228ab857ff12b31937c95fc5f586a08cef745d46f9884468179c2` |
| `Mesh-Chat_0.5.0_x64_en-US.msi` | `9e69d0c1f2e8de1d177458eb08d21e736fe013c7bc512bb96d56de9ad94b0add` |
| `mesh-chat-0.5.0-android-arm64-release.apk` | `be52a4ec97c7fba3d66f836a67e02313987c525d4e9d09eb52a2907319220caf` |

## Role and document-type errors, 2026-10-21

**0.4.5 / Android 405** stops mislabeling offer failures as answer failures:

- offer verification errors now say the offer signature or document is invalid;
- answer verification errors remain answer-specific;
- both fields validate the signed document `type` before calling the service;
- pasting an offer into the answer field now says “That document is not a
  WebRTC answer”;
- pasting an answer into the offer field says “That document is not a WebRTC
  offer”;
- the chooser explains which device is offerer and which is joiner.

Validation: TypeScript and **237 frontend tests** passed.
GitHub Actions
[run 39661330663](https://github.com/ahouchens/mesh-chat/actions/runs/39661330663)
passed Verify, Windows packaging, Android packaging, and Publish.
Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.4.5>.

| Artifact | SHA-256 |
|---|---|
| `Mesh-Chat_0.4.5_x64-setup.exe` | `08115f9b8a24939e98b2d6f9ff1f001cd7499bb6d12d649fac321dd44e7f93db` |
| `Mesh-Chat_0.4.5_x64_en-US.msi` | `512e6befb5d58f5441ece785b96fb4802186624f15996d4b98390a81f0705d94` |
| `mesh-chat-0.4.5-android-arm64-release.apk` | `deea0b7ef21c53ca171266f8f8534ac3b72262885adf09a88243ec71d3c4b233` |

## Duplicate WebRTC operation guard, 2026-10-21

**0.4.4 / Android 404** closes a race that could produce zero ICE candidate
pairs:

- the review screen could be tapped repeatedly while it waited 15 seconds for
  ICE gathering;
- each tap created another `RTCPeerConnection` and answer, while one signed
  answer could carry ICE credentials from a different peer connection;
- the remote candidates then did not match the local ICE ufrag/pwd, producing
  `pairStates: {}` despite candidates in the SDP;
- create-offer, review-offer, and connect-answer are now single-flight guarded;
- the review button shows **Creating answer…** and is disabled while busy.

A real Chromium two-peer probe with the same Cloudflare TURN configuration
connected successfully with 100 candidate pairs, confirming relay-to-relay
works.

Validation: TypeScript, **237 frontend tests**, and production build passed.
GitHub Actions
[run 39642830953](https://github.com/ahouchens/mesh-chat/actions/runs/39642830953)
passed Verify, Windows packaging, Android packaging, and Publish.
Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.4.4>.

| Artifact | SHA-256 |
|---|---|
| `Mesh-Chat_0.4.4_x64-setup.exe` | `b4da34834173073cfbfc0a882442cdfd7323def50bbab3c3ec45377d1b6e27a1` |
| `Mesh-Chat_0.4.4_x64_en-US.msi` | `1a5c2d781c308b5b0e2a2c5431f6c5389280081048c072b439aa31bd2c5329fe` |
| `mesh-chat-0.4.4-android-arm64-release.apk` | `fd932043ef7adffaa64d458c80484fa8b8778d3f12d797f284ad37e295b11aa4` |

## WebRTC path announcement, 2026-10-21

**0.4.3 / Android 403** fixes the case where Android accepted the contact
invitation but Windows never received the request:

- each side announces its LXMF destination immediately when the WebRTC
  interface attaches;
- reannounces at 2 and 6 seconds to cover a peer that attached later;
- this provides the path and ratchet needed for the queued contact request to
  leave the outbox;
- the contact request retry worker then delivers it normally.

Validation: full service suite **1053 passed, 46 skipped**; targeted tests passed.
GitHub Actions
[run 39637023085](https://github.com/ahouchens/mesh-chat/actions/runs/39637023085)
passed Verify, Windows packaging, Android packaging, and Publish.
Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.4.3>.

| Artifact | SHA-256 |
|---|---|
| `Mesh-Chat_0.4.3_x64-setup.exe` | `53528370f6bbb48d006b8f2c9f7aa68ff81bc45985dac35ced1dd89a88bcc221` |
| `Mesh-Chat_0.4.3_x64_en-US.msi` | `5519adf1d818437fd20646eb35e48538592b7bbf527c7766ba61603e4b36d8e9` |
| `mesh-chat-0.4.3-android-arm64-release.apk` | `2e48422c995d626ed2ec2d271f58da4e547ca324abefb285def422105cc0fac7` |

## Answer binding precheck, 2026-10-21

**0.4.2 / Android 402** distinguishes a stale answer from a copy mistake:

- the offer and answer display a short session code;
- before calling the service, the app compares the answer's `session_id` with
  the current offer;
- it computes SHA-256 of the current offer and compares `offer_digest`;
- a mismatch now names the session or digest instead of returning generic
  `identity_mismatch`.

Validation: TypeScript and **237 frontend tests** passed.

## Stale WebRTC answer guidance, 2026-10-21

**0.4.1 / Android 401** makes a stale signed answer actionable:

- `identity_mismatch` during answer verification now says the answer belongs to
  a different or regenerated offer;
- creating a new offer clears any previously pasted answer;
- no TURN or identity change is required for this error.

Validation: TypeScript and **237 frontend tests** passed.
GitHub Actions
[run 39609800738](https://github.com/ahouchens/mesh-chat/actions/runs/39609800738)
passed Verify, Windows packaging, Android packaging, and Publish.
Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.4.2>.

| Artifact | SHA-256 |
|---|---|
| `Mesh-Chat_0.4.2_x64-setup.exe` | `263ea54eb680e248c8c2a68fc2dd00d743e6b9bc3e511f372d48e0a1fd253e8e` |
| `Mesh-Chat_0.4.2_x64_en-US.msi` | `3cd23ffc71d7924cf03582c9e319f060aecd21f4ecd517508a74ae39b6ebdc56` |
| `mesh-chat-0.4.2-android-arm64-release.apk` | `48805461d56b92a5ce36f0e8434500dfd9289d8f7174b5160f4fba05583eb608` |

## Inline contact and workspace onboarding, 2026-10-21

**0.4.0 / Android 400** removes the second invitation flow after WebRTC connects:

- adds a reliable `mesh-onboarding` DataChannel alongside `mesh-reticulum`;
- the offerer automatically creates and sends a signed personal invitation
  over the control channel;
- the joiner previews the identity/fingerprint and accepts inline;
- optional workspace invitation is sent and previewed in the same screen;
- existing owner approval still applies, but no QR/copy/paste is needed;
- ICE gathering waits up to 15 seconds and diagnostics include local/remote
  SDP candidate counts.

Validation: TypeScript, **237 frontend tests**, and production build passed.
GitHub Actions
[run 39599950154](https://github.com/ahouchens/mesh-chat/actions/runs/39599950154)
passed Verify, Windows packaging, Android packaging, and Publish.
Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.4.0>.

| Artifact | SHA-256 |
|---|---|
| `Mesh-Chat_0.4.0_x64-setup.exe` | `57c5566ec16292d51041ee1f09b88464371f1de4b34d26c0e98e6e648aff9dad` |
| `Mesh-Chat_0.4.0_x64_en-US.msi` | `4d5882e6e9bf0e2ba040ef2e5dcccba1fadf4ce3b13d28733fdf25e17fa681b6` |
| `mesh-chat-0.4.0-android-arm64-release.apk` | `0df2319bc8ac1881617399ad4713336a03446820fac2ccf0a3812f903f807e95` |

## ICE gathering and relay diagnostics, 2026-10-20

## ICE gathering and relay diagnostics, 2026-10-20

**0.3.2 / Android 302** fixes the relay candidate exchange window:

- waits up to **15 seconds** for ICE gathering to complete before signing the
  offer/answer, instead of 4 seconds;
- total connection timeout raised to 30 seconds;
- diagnostics now include local/remote SDP candidate counts, making it
  explicit when the remote side sent no relay candidate;
- the Android relay consent must be enabled independently of Windows.

Diagnostics from the relay-only failure showed Windows had six TURN URLs and
`local:relay`, but Android had not enabled the broker; both sides need TURN for
a fully relayed path.

Validation: TypeScript, **237 frontend tests**, and production build passed.
GitHub Actions
[run 39541470693](https://github.com/ahouchens/mesh-chat/actions/runs/39541470693)
passed Verify, Windows packaging, Android packaging, and Publish.
Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.3.2>.

| Artifact | SHA-256 |
|---|---|
| `Mesh-Chat_0.3.2_x64-setup.exe` | `b38a45e303f733613b9ed0bc1f4fd6f381fd0adf816aaacf2fb7443488945e21` |
| `Mesh-Chat_0.3.2_x64_en-US.msi` | `5b6639eb0d2304dabf3639b6217512517f61bc97d332411a6a4d725780e8a479` |
| `mesh-chat-0.3.2-android-arm64-release.apk` | `832b451cc6a94b994c72824a414cf3bfaaba9b5138a7519f80cae5d3436a9cf8` |

## TURN consent save fix, 2026-10-20

**0.3.1 / Android 301** fixes **“That information could not be validated”**
when saving the TURN broker consent.

Cause: `update_call_settings` accepted the new `CallSettings` fields internally,
but the service command allowlist still rejected `turn_broker_url` and
`turn_broker_consent`. The UI sent them, so every save failed and the relay
stayed disabled.

Fix:

- allow both fields in the `update_call_settings` command envelope;
- add a regression test for the exact payload;
- move the relay consent checkbox above the action buttons and show a
  “Relay is disabled” warning when it is off.

Validation: targeted service tests **19 passed**; full CI will verify packaging.
GitHub Actions
[run 39536091748](https://github.com/ahouchens/mesh-chat/actions/runs/39536091748)
passed Verify, Windows packaging, Android packaging, and Publish.
Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.3.1>.

| Artifact | SHA-256 |
|---|---|
| `Mesh-Chat_0.3.1_x64-setup.exe` | `1c7394b4bfa51248a43db8d44fa3f9a893c8614c6544afeede6871e501b0bbae` |
| `Mesh-Chat_0.3.1_x64_en-US.msi` | `e65316c2dcd4e93327d1acc75a507968cdc83c06f14de78677fa2d965eb8a462` |
| `mesh-chat-0.3.1-android-arm64-release.apk` | `2614e261220d9fbc28b6cd2f0f63ae2546cb3bf26d64deb70aab29ecfcd11c9d` |

## Persistent WebRTC diagnostics, 2026-10-20

**0.3.0 / Android 300** makes the last WebRTC diagnostics survive the dialog
closing:

- **Copy last WebRTC diagnostics** is available in Settings → WebRTC calls;
- diagnostics now include an ICE configuration summary: transport policy,
  count of STUN/TURN URLs, and whether credentials were present;
- the bundle still excludes SDP, TURN credentials, IP addresses, and message
  content.

This is intended to distinguish:

- `iceConfiguration.turn: 0` → TURN was not in the ICE configuration
  (consent unchecked or broker disabled);
- `turn > 0` with no `local:relay` candidate → TURN allocation failed;
- `local:relay` present but no selected pair → relay reachability failed.

Validation: TypeScript, **237 frontend tests**, and production build passed.
GitHub Actions
[run 39531450529](https://github.com/ahouchens/mesh-chat/actions/runs/39531450529)
passed Verify, Windows packaging, Android packaging, and Publish.
Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.3.0>.

| Artifact | SHA-256 |
|---|---|
| `Mesh-Chat_0.3.0_x64-setup.exe` | `9ae869baaa1b35be62bd4e66358ab64dfc04eb0adb669a27b83be08a0079ce30` |
| `Mesh-Chat_0.3.0_x64_en-US.msi` | `a223f0b4fcc0ea56ec4f6fc17b4f47cac0982126f809f1395fb00f43eb3df133` |
| `mesh-chat-0.3.0-android-arm64-release.apk` | `71a766e34692fbe9b83e48520807e1eaa3308fd1f448c259415bf39beb0d02d6` |

## Android certifi startup fix, 2026-10-20

**0.2.99 / Android 2099** fixes **“The mobile messaging runtime could not
start.”**

Cause: 0.2.98 imported `certifi` from `turn_credentials.py`, but the Chaquopy
mobile dependency lock did not include certifi. The import raised at service
startup before the runtime could initialize.

Fix:

- added `certifi==2026.10.19` to `service/requirements-mobile.lock`;
- made the certifi import optional so a missing CA bundle cannot stop the
  messaging runtime;
- broker TLS still uses certifi when present.

Validation: targeted service tests **22 passed**; mobile packaging and runtime
startup are verified by the Android CI build and the next device launch.
GitHub Actions
[run 39529227899](https://github.com/ahouchens/mesh-chat/actions/runs/39529227899)
passed Verify, Windows packaging, Android packaging, and Publish.
Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.2.99>.

| Artifact | SHA-256 |
|---|---|
| `Mesh-Chat_0.2.99_x64-setup.exe` | `bcf7b1c8a5fa0a3891d64b19e2205724a6c8a1b0d0023ac48039544c4e17f0fd` |
| `Mesh-Chat_0.2.99_x64_en-US.msi` | `9237eece13848e5efd07f4c6779ef9a13869959acbf839343ed59aefce471225` |
| `mesh-chat-0.2.99-android-arm64-release.apk` | `c88fa153913833b558e668e3388c33658bc2be38ab011fcbdbc467dd36849e61` |

## WebRTC diagnostics export, 2026-10-20

**0.2.98 / Android 2098** adds **Copy diagnostics** to the WebRTC onboarding
dialog on both success and failure.

The bundle contains:

- connection, ICE connection, and ICE gathering states;
- selected candidate pair types, protocol, relay protocol, bytes sent/received;
- local/remote candidate types;
- candidate-pair state counts;
- DataChannel state and counters;
- phase, timestamp, and visible error.

It excludes SDP, TURN credentials, IP addresses, and message content.

Validation:

- Frontend TypeScript: passed.
- Frontend tests: **237 passed**.
- Frontend production build: passed.
- Full service suite unchanged: **1051 passed, 46 skipped**.
- GitHub Actions
  [run 39527002432](https://github.com/ahouchens/mesh-chat/actions/runs/39527002432)
  passed Verify, Windows packaging, Android packaging, and Publish.
- Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.2.98>.

Published assets:

| Artifact | SHA-256 |
|---|---|
| `Mesh-Chat_0.2.98_x64-setup.exe` | `88ca6e583934fdd683982846d247f9d7d98197b89b7ef9a94e86a5f420a0aaa7` |
| `Mesh-Chat_0.2.98_x64_en-US.msi` | `f9a47751941c2c7041be0d5a619dd9364d91537ed17c71814b4f83ab7bbd17d4` |
| `mesh-chat-0.2.98-android-arm64-release.apk` | `84a878ed28bd3772391132fa3b6e2ce4fabad27dcd3dc705295e94ddc9f0a447` |

## Default Cloudflare TURN relay, 2026-10-20

**0.2.97 / Android 2097** makes the Cloudflare TURN broker a built-in default:

```text
https://staether.webtechalex.workers.dev/credentials
```

- calls do not use it until the user enables **Use this TURN broker for calls**;
- users can override the broker URL or disable it;
- the long-term Cloudflare TURN API token stays in the Worker;
- `certifi` is bundled for service HTTPS validation on Windows and Android;
- broker responses are cached for 50 minutes and refreshed before the TTL.

Validation:

- Live Worker response returned two ICE server entries, including TURN URLs.
- Service `fetch_ice_servers` returned TURN URLs through the new certifi SSL
  context.
- Full service suite: **1051 passed, 46 skipped**.
- Frontend TypeScript: passed.
- Frontend tests: **237 passed**.
- Frontend production build: passed.
- GitHub Actions
  [run 39522492785](https://github.com/ahouchens/mesh-chat/actions/runs/39522492785)
  passed Verify, Windows packaging, Android packaging, and Publish.
- Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.2.97>.

Published assets:

| Artifact | SHA-256 |
|---|---|
| `Mesh-Chat_0.2.97_x64-setup.exe` | `2f8a08a72d4a5839d57e4c63f269e0a0fc19ead85fc96b310099a5149e9fee65` |
| `Mesh-Chat_0.2.97_x64_en-US.msi` | `bdb6c0ecc0cfe532fe5e94fe64710a419fd1776bc6a90c5899b331f27a5956ec` |
| `mesh-chat-0.2.97-android-arm64-release.apk` | `70382576463fdd80f638e0587ff4af9561b091a60ae8b0676524acbdd1dc12b4` |

Still open: live Windows↔Android onboarding through Cloudflare TURN, Worker
rate limiting, and token rotation after the exposed token.

## Cloudflare TURN broker support, 2026-10-20

**0.2.96 / Android 2096** adds Cloudflare TURN as a credential-broker
provider:

- Cloudflare Worker in `deploy/cloudflare-turn` exchanges TURN Key ID + API
  token for short-lived `iceServers`;
- Mesh Chat stores only the HTTPS broker URL, never the TURN API token;
- Settings → WebRTC calls exposes the broker URL, a **Use global default**
  action, and **Disable TURN broker**;
- dynamic ICE servers are cached for 50 minutes and refreshed before the
  one-hour credential TTL;
- self-hosted coturn remains supported.

No global broker URL is shipped yet. The source defaults to no broker until a
Worker URL is configured with `MESH_CHAT_DEFAULT_TURN_BROKER`.

Validation:

- Full service suite: **1051 passed, 46 skipped**.
- Frontend TypeScript: passed.
- Frontend tests: **237 passed**.
- Frontend production build: passed.
- Worker syntax: `node --check` passed.
- GitHub Actions
  [run 39518026972](https://github.com/ahouchens/mesh-chat/actions/runs/39518026972)
  passed Verify, Windows packaging, Android packaging, and Publish.
- Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.2.96>.

Published assets:

| Artifact | SHA-256 |
|---|---|
| `Mesh-Chat_0.2.96_x64-setup.exe` | `c37dc681d871e50732a7de9dec73817358927298953d4353850fd4532cb8c9a9` |
| `Mesh-Chat_0.2.96_x64_en-US.msi` | `c35bdf1cf60b51648377118414d6010cf5f600bd78d5c2a534b5eacd5191b7bd` |
| `mesh-chat-0.2.96-android-arm64-release.apk` | `147697f4b8d9bc17f85079aa44fd210302beee496733f0a1872297639ad0e0ac` |

## TURN relay deployment kit, 2026-10-20

**0.2.95 / Android 2095** adds a least-friction TURN relay:

- `deploy/relay/install.sh` installs Docker, detects the VPS IPv4 address,
  generates credentials, opens ports, and starts coturn;
- TURN is exposed on TCP/UDP 443 as well as 3478, so it works through
  client-isolated Wi-Fi, CGNAT, and Windows inbound firewall blocks;
- call settings now accept `turn:host:443?transport=tcp`;
- `deploy/relay/README.md` documents capacity, privacy, rotation, and cloud
  security-group ports.

Validation:

- Full service suite: **1042 passed, 46 skipped**.
- Frontend TypeScript: passed.
- Frontend tests: **237 passed**.
- Frontend production build: passed.
- Installer shell syntax: `bash -n` passed.
- No VPS was available for a live relay allocation test.

## WebRTC connection timeout, 2026-10-20

**0.2.94 / Android 2094** fixes the indefinite **Applying the signed answer
and opening the DataChannel…** state.

- a 20-second timeout now fails with an actionable Wi-Fi/firewall/TURN message;
- ICE/peer connection failure transitions to the error state;
- a Cancel action is available while connecting;
- attach errors are surfaced instead of leaving the dialog stuck.

The likely physical causes on Windows↔Android Wi-Fi are access-point client
isolation, Windows Firewall blocking UDP, or mDNS-only host candidates. TURN is
the reliable workaround when client isolation is enabled.

Validation: frontend TypeScript, **237 frontend tests**, and production build
passed. GitHub Actions
[run 39501671842](https://github.com/ahouchens/mesh-chat/actions/runs/39501671842)
passed Verify, Windows packaging, Android packaging, and Publish.
Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.2.94>.

| Artifact | SHA-256 |
|---|---|
| `Mesh-Chat_0.2.94_x64-setup.exe` | `97428b877a346a6031d1e912a9395daab8df3d72e0a4c1eb27c4f6df3f199571` |
| `Mesh-Chat_0.2.94_x64_en-US.msi` | `26c2366d7ec6840b7517b572d7cdc7d036d9bb0d7449db4807ca17797b4f26cf` |
| `mesh-chat-0.2.94-android-arm64-release.apk` | `c6b150d593a4cfa4e27b085a103722f692dbfdfc4b622a59e4d6c96e2a5ee5ce` |

## C5d WebRTC invitation admission, 2026-10-20

**0.2.93 / Android 2093** adds **WebRTC bridge — connected** to the personal
and workspace invitation selectors. `connection_mode="webrtc"` returns the
normal signed invitation without starting participant-hosted direct setup, so
the existing join/approval/receipt flow runs over the attached DataChannel
interface.

Validation:

- Full service suite: **1040 passed, 46 skipped**.
- Frontend TypeScript: passed.
- Frontend tests: **237 passed**.
- Frontend production build: passed.
- GitHub Actions
  [run 39498341896](https://github.com/ahouchens/mesh-chat/actions/runs/39498341896)
  passed Verify, Windows packaging, Android packaging, and Publish.
- Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.2.93>.

Published assets:

| Artifact | Size | SHA-256 |
|---|---:|---|
| `Mesh-Chat_0.2.93_x64-setup.exe` | 27,533,191 | `04d9f2c656502894f990ae6d76e7df9ac4bc8dc44fe446f61926190ea8736887` |
| `Mesh-Chat_0.2.93_x64_en-US.msi` | 29,528,064 | `63d2034c407725604ee74d7b9a0041ecea302afb172a37723fdc1ab368173675` |
| `mesh-chat-0.2.93-android-arm64-release.apk` | 34,115,005 | `89734b08135815a0a05bb38506777a98bb04498fb7819499310b7c8bcd0de3b9` |

Still open: transferring the invitation automatically inside the WebRTC dialog
(it is still copied/pasted), reconnect/failure tests, and C5e physical
qualification.

## C5c WebRTC onboarding dialog, 2026-10-20

**0.2.92 / Android 2092** adds signed WebRTC onboarding offers/answers and a
**WebRTC** onboarding dialog with QR/copy, create/join, ICE settings, and a
persistent connected-session banner.

Validation:

- Full service suite: **1040 passed, 46 skipped**.
- Frontend TypeScript: passed.
- Frontend tests: **237 passed**.
- Frontend production build: passed.
- GitHub Actions
  [run 39459131402](https://github.com/ahouchens/mesh-chat/actions/runs/39459131402)
  passed Verify, Windows packaging, Android packaging, and Publish.
- Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.2.92>.

Published assets:

| Artifact | Size | SHA-256 |
|---|---:|---|
| `Mesh-Chat_0.2.92_x64-setup.exe` | 27,527,667 | `7b768db26246f5b22daf961e427e63f8fe795d400fd35ab322d7d4b5cc80c015` |
| `Mesh-Chat_0.2.92_x64_en-US.msi` | 29,528,064 | `4274bf38070ead4f722c68f214dfda54fa46949cdefaa9acb2a2f825bfd2a112` |
| `mesh-chat-0.2.92-android-arm64-release.apk` | 34,115,249 | `45c94c600d74d1f45c432505da2816f665bdf2675af48938b1d8c4473cf40d60` |

Still open: automatic contact/workspace admission over the bridge, physical
Windows↔Android cellular test with TURN, and relay/consent evidence.

## C5b renderer DataChannel pump, 2026-10-20

**0.2.90 / Android 2090** adds the renderer pump between the WebRTC
DataChannel and the Python Reticulum bridge:

- binary DataChannel messages become bounded `webrtc_packet` IPC;
- `webrtc_packet` service events become channel binary messages;
- 1064-byte MTU enforcement, close/error detach, and listener cleanup;
- Vitest coverage for base64 round-trip, both directions, MTU rejection, and
  detach.

Still missing: signed offer/answer QR/copy UI, onboarding admission over the
bridge, TURN-forced cellular test.

Validation:

- Frontend TypeScript: passed.
- Frontend tests: **237 passed**.
- Frontend production build: passed.
- Full service suite: **1037 passed, 46 skipped**.
- GitHub Actions
  [run 39454264862](https://github.com/ahouchens/mesh-chat/actions/runs/39454264862)
  passed Verify, Windows packaging, Android packaging, and Publish.
- Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.2.90>.

Published assets:

| Artifact | Size | SHA-256 |
|---|---:|---|
| `Mesh-Chat_0.2.90_x64-setup.exe` | 27,525,091 | `76b0600331255e8c81b6cb2b187fe0178feeed2df432866551557dbf31aef172` |
| `Mesh-Chat_0.2.90_x64_en-US.msi` | 29,515,776 | `c2e01c015dc697ea2190f231259339c3e452681553cafd0b02c8c6519cac734d` |
| `mesh-chat-0.2.90-android-arm64-release.apk` | 34,098,732 | `bff9c05253f360903539b557f702b8ea0ad5beb60ece4259686bdc3851ff262d` |

## C5a Reticulum DataChannel bridge, 2026-10-20

**0.2.89 / Android 2089** adds the C5a Python bridge:

- `WebRTCInterface` with 1064-byte packet bounds and detach-on-close;
- `webrtc_attach`, `webrtc_packet`, `webrtc_detach` service commands;
- base64 `webrtc_packet` service events for the renderer;
- bridge cleanup during service shutdown.

This is not the full C5 onboarding flow. The renderer packet pump, signed
QR/copy offer/answer UI, admission flow, and physical Windows↔Android test
remain open.

Validation:

- Full service suite: **1037 passed, 46 skipped**.
- Frontend TypeScript: passed.
- Frontend tests: **234 passed**.
- GitHub Actions
  [run 39449588664 attempt 2](https://github.com/ahouchens/mesh-chat/actions/runs/39449588664)
  passed Verify, Windows packaging, Android packaging, and Publish. Attempt 1
  failed while the runner downloaded a corrupted Android NDK zip; no release
  was published from it.
- Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.2.89>.

Published assets:

| Artifact | Size | SHA-256 |
|---|---:|---|
| `Mesh-Chat_0.2.89_x64-setup.exe` | 27,522,714 | `7268e7e9a3ae00e76b01537da2b78c1b3b9a06df26cde83f575c9ce1f864e45e` |
| `Mesh-Chat_0.2.89_x64_en-US.msi` | 29,515,776 | `fc829cd725efc911e61bde7ea64a603e77db296c8b627955b1390f16c06ab66e` |
| `mesh-chat-0.2.89-android-arm64-release.apk` | 34,098,872 | `f610b38bfdf284c1300bda0e71ff2d24fb47c652b0444e171366ba750c8afccf` |

Still open: renderer DataChannel pump, signed offer/answer QR/copy UI,
admission flow, TURN-forced physical test, and C5 acceptance criteria.

## STUN default, coturn, and C5 prototype, 2026-10-20

**0.2.88 / Android 2088** makes Google STUN
(`stun:stun.l.google.com:19302`) the default call ICE helper while keeping it
replaceable/clearable. It adds a self-hosted coturn recipe under `deploy/turn`
and starts C5 with a DataChannel onboarding prototype that exchanges a signed
invitation and a separately signed reply.

Validation:

- Full service suite: **1034 passed**, with one timing-sensitive administrator
  benchmark failing under the full run and passing in isolation; CI Verify
  passed.
- Frontend TypeScript: passed.
- Frontend tests: **234 passed**.
- Frontend production build: passed.
- C5 prototype: **PASS** — signed invitation and reply traversed the
  DataChannel.
- GitHub Actions
  [run 39440900966](https://github.com/ahouchens/mesh-chat/actions/runs/39440900966)
  passed Verify, Windows packaging, Android packaging, and Publish.
- Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.2.88>.

Published assets:

| Artifact | Size | SHA-256 |
|---|---:|---|
| `Mesh-Chat_0.2.88_x64-setup.exe` | 27,521,497 | `21cefe5ed48456e1123bad2a57c9a7cdb891ade9c2c80bab8b807e9a8774cbd9` |
| `Mesh-Chat_0.2.88_x64_en-US.msi` | 29,515,776 | `e036dd730a5a70fc871e5ab55d65980b4f4cc1b8b0bab41b55cc23dbb1af31ea` |
| `mesh-chat-0.2.88-android-arm64-release.apk` | 34,098,850 | `cfcb3364accee540885c43e8f8af95875cb8d4646e77f74459d04e07ea3a95e7` |

C5 remains a prototype: it is not exposed in the UI and does not yet bridge
DataChannel bytes into Reticulum/LXMF. Google provides STUN, not free TURN; the
coturn deployment is operator-controlled. Physical-device calls remain open.

## WebRTC video quality controls, 2026-10-19

**0.2.87 / Android 2087** prefers VP8 when the WebView exposes codec
preferences, caps the video sender at 500 kbps, shows a good/fair/poor media
indicator from inbound RTP loss/jitter, and retries the call media path when the
browser reports that it is online.

Validation:

- Full service suite: **1034 passed, 46 skipped**.
- Frontend TypeScript: passed.
- Frontend tests: **234 passed**.
- Frontend production build: passed.
- GitHub Actions
  [run 39382669387](https://github.com/ahouchens/mesh-chat/actions/runs/39382669387)
  passed Verify, Windows packaging, Android packaging, and Publish.
- Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.2.87>.

Published assets:

| Artifact | Size | SHA-256 |
|---|---:|---|
| `Mesh-Chat_0.2.87_x64-setup.exe` | 27,519,856 | `3e698e1f5e68604a8a38d52b2fcb507fbb445910fe938a9361c9635d2c987dea` |
| `Mesh-Chat_0.2.87_x64_en-US.msi` | 29,515,776 | `643cfd2f87e8c81727613fa9cbe433cdc0eea4b641eb18a26b597b8c42b3963c` |
| `mesh-chat-0.2.87-android-arm64-release.apk` | 34,098,770 | `6d56f324958fcbbf9654f79fe4c31176a9c046ba34e2fe1e3c84683eabc064ac` |

Still open: physical multi-device calls, Android foreground behavior on a
device, real video codec/thermal measurement, and C5.

## WebRTC call rate limits, 2026-10-19

**0.2.86 / Android 2086** adds per-contact outbound call rate limits (three per
minute, twenty per hour), prunes finished call records after 24 hours, and
records the TURN quota/abuse boundary in ADR 0022. TURN quotas remain the
operator's responsibility.

Validation:

- Full service suite: **1034 passed, 46 skipped**.
- Frontend TypeScript: passed.
- Frontend tests: **234 passed**.
- GitHub Actions
  [run 39381179215](https://github.com/ahouchens/mesh-chat/actions/runs/39381179215)
  passed Verify, Windows packaging, Android packaging, and Publish.
- Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.2.86>.

Published assets:

| Artifact | Size | SHA-256 |
|---|---:|---|
| `Mesh-Chat_0.2.86_x64-setup.exe` | 27,518,689 | `ce91ba3a395462dc09376ad27c04217bb7cd3caa9c4402943653409b4b17092b` |
| `Mesh-Chat_0.2.86_x64_en-US.msi` | 29,511,680 | `53670146d45c97cf35457bfb5ba485c89a4a38f8a3f0f0731d78a4da17ed5fbd` |
| `mesh-chat-0.2.86-android-arm64-release.apk` | 34,098,644 | `e00b48540bf1b0327daa9b65bca911cb529cf48b6043c1fc13112be864b850f6` |

Still open: physical multi-device calls, Android foreground/call behavior on a
device, video quality/thermal validation, and C5.

## Android foreground call service, 2026-10-19

**0.2.85 / Android 2085** adds a microphone/camera-typed foreground
`CallService` with a persistent in-call notification, started/stopped by the
audio-focus bridge. The service never reads the vault or messaging profile.

Validation:

- Full service suite: **1033 passed, 46 skipped**.
- Frontend TypeScript: passed.
- Frontend tests: **234 passed**.
- Frontend production build: passed.
- GitHub Actions
  [run 39379524979](https://github.com/ahouchens/mesh-chat/actions/runs/39379524979)
  passed Verify, Windows packaging, Android packaging, and Publish.
- Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.2.85>.

Published assets:

| Artifact | Size | SHA-256 |
|---|---:|---|
| `Mesh-Chat_0.2.85_x64-setup.exe` | 27,518,937 | `836052467b1e1ee61ba0ac1c78cffea278353f17f9c812fb3fa3dd1d944e238f` |
| `Mesh-Chat_0.2.85_x64_en-US.msi` | 29,515,776 | `cb2056767ed9cfa3da6d516c3f7d0b2130bc3ceb941a91ae1946102eba111d66` |
| `mesh-chat-0.2.85-android-arm64-release.apk` | 34,098,643 | `3c453228e9d0196f1c40292640f4dbde386a742d82ef702c39bfa4b87372f61f` |

Still open: physical Android call/foreground behavior, physical
Windows↔Android calls, TURN quotas, video quality, and C5.

## Android call-audio focus, 2026-10-19

**0.2.84 / Android 2084** adds Android call-audio focus and
`MODE_IN_COMMUNICATION` around media calls, released on hangup. The WebView
microphone/camera remains behind the runtime media permission bridge.

Validation:

- Full service suite: **1033 passed, 46 skipped**.
- Frontend TypeScript: passed.
- Frontend tests: **234 passed**.
- Frontend production build: passed.
- GitHub Actions
  [run 39378211532](https://github.com/ahouchens/mesh-chat/actions/runs/39378211532)
  passed Verify, Windows packaging, Android packaging, and Publish.
- Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.2.84>.

Published assets:

| Artifact | Size | SHA-256 |
|---|---:|---|
| `Mesh-Chat_0.2.84_x64-setup.exe` | 27,519,552 | `4bbd070f51336b6d1317b2a1e0e200c85fb9de71b032731166d1bb572f73eb03` |
| `Mesh-Chat_0.2.84_x64_en-US.msi` | 29,511,680 | `870d9de98b5a97a1a6bb7314144d1594430258b68ee1027f2386cde3cc83127c` |
| `mesh-chat-0.2.84-android-arm64-release.apk` | 34,098,631 | `688a77208aa4596e58f0f043e8f33dd015fa3cad9be14037a56836b131583c80` |

Still open: physical Android call/runtime-prompt behavior, foreground-service
notification, physical Windows↔Android calls, TURN quotas, video quality, and
C5.

## WebRTC SDP input hardening, 2026-10-19

**0.2.83 / Android 2083** hardens call SDP and candidate validation before
signing or verification: bounded lines/bytes, control-character rejection,
exactly one DTLS fingerprint, and audio/video-only media sections.

Validation:

- Full service suite: **1033 passed, 46 skipped**.
- Frontend TypeScript: passed.
- Frontend tests: **234 passed**.
- GitHub Actions
  [run 39376839336](https://github.com/ahouchens/mesh-chat/actions/runs/39376839336)
  passed Verify, Windows packaging, Android packaging, and Publish.
- Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.2.83>.

Published assets:

| Artifact | Size | SHA-256 |
|---|---:|---|
| `Mesh-Chat_0.2.83_x64-setup.exe` | 27,520,111 | `00adce61647d5d8a0b0552c88bf31eee22eec7ad7f7533ea89d23f6586dbf94a` |
| `Mesh-Chat_0.2.83_x64_en-US.msi` | 29,515,776 | `a12e0a2fe62b57230e592b6635ba831422f993b4fea1c0a2d58b650d89866da8` |
| `mesh-chat-0.2.83-android-arm64-release.apk` | 34,082,156 | `699805c68779c13697db7392a0181d8b566e0033bf4b9e263ecb4be9819dd0da` |

Still open: TURN quotas/abuse controls, physical multi-device calls, Android
audio focus/foreground behavior, video quality, and C5.

## WebRTC ICE restart, 2026-10-19

**0.2.82 / Android 2082** adds signed `call_renegotiate` documents, generation
and replay checks, manager restart/answer operations, and a call surface that
recreates the media path on disconnect without a new ring or contact approval.

Validation:

- Focused call tests: **19 passed**.
- Full service suite: **1027 passed, 46 skipped**.
- Frontend TypeScript: passed.
- Frontend tests: **234 passed**.
- Frontend production build: passed.
- GitHub Actions
  [run 39375134922](https://github.com/ahouchens/mesh-chat/actions/runs/39375134922)
  passed Verify, Windows packaging, Android packaging, and Publish.
- Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.2.82>.

Published assets:

| Artifact | Size | SHA-256 |
|---|---:|---|
| `Mesh-Chat_0.2.82_x64-setup.exe` | 27,517,075 | `22c736d73d53ff96ee54604fe3d904c2a7b77ffe2e7e7a7db95d4266c6527dae` |
| `Mesh-Chat_0.2.82_x64_en-US.msi` | 29,511,680 | `7b40c075e201d723fc4b69ecac3ce42d21a8b66a4adc4f189668c65c91de45bc` |
| `mesh-chat-0.2.82-android-arm64-release.apk` | 34,082,615 | `74f188af50cdd0490efdc78ebbff594465e7d506b1c60a9345f9b71a904226ae` |

Still open: TURN quotas/abuse controls, malformed-SDP/fuzz coverage, physical
Windows↔Android calls, Android audio focus/foreground, video quality, and C5.

## WebRTC call timeout and recovery, 2026-10-19

**0.2.81 / Android 2081** bounds unanswered calls to 45 seconds, removes expired
ringing calls from the active set, rejects late answers, and adds explicit
**Try again** recovery. The desktop release verifier now allows 60 seconds and
one retry for the Windows version probe after a transient CI timeout.

Validation:

- Focused call-manager/settings tests: **15 passed**.
- Frontend TypeScript: passed.
- Frontend tests: **234 passed**.
- GitHub Actions
  [run 39372079291 attempt 2](https://github.com/ahouchens/mesh-chat/actions/runs/39372079291)
  passed Verify, Windows packaging, Android packaging, and Publish. Attempt 1
  hit a transient PowerShell version-query timeout; no artifact was published
  from that attempt.
- Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.2.81>.

Published assets:

| Artifact | Size | SHA-256 |
|---|---:|---|
| `Mesh-Chat_0.2.81_x64-setup.exe` | 27,515,717 | `3861f0c4461ccaba0b21caa4661bfef86d1969ede53ca24c581a64b5f6f99fc4` |
| `Mesh-Chat_0.2.81_x64_en-US.msi` | 29,511,680 | `193be62ebe728819d95d654d47f3b6f4d6b429467dd785511a1f51fce288b8fb` |
| `mesh-chat-0.2.81-android-arm64-release.apk` | 34,082,565 | `0143de02878cb8c75dac3b30ac7f800ba84f95ceb43fbca20393c8f6b1d40a0d` |

The full service suite was last recorded at 1024 passed before the ring-timeout
change; the focused call-manager suite covers the new transition. Physical
calls, Android audio focus, ICE restart, and TURN quotas remain open.

## WebRTC Android media permission bridge, 2026-10-19

**0.2.80 / Android 2080** adds the mesh-runtime media permission alias and
`requestMediaPermission` bridge, requested before Android `getUserMedia`. The
APK declares microphone, camera, and audio-settings permissions; package
inspection confirms them.

Validation:

- Frontend TypeScript: passed.
- Frontend tests: **234 passed**.
- Frontend production build: passed.
- Full service suite: **1024 passed, 46 skipped**.
- GitHub Actions
  [run 39370718006](https://github.com/ahouchens/mesh-chat/actions/runs/39370718006)
  passed Verify, Windows packaging, Android packaging, and Publish.
- Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.2.80>.

Published assets:

| Artifact | Size | SHA-256 |
|---|---:|---|
| `Mesh-Chat_0.2.80_x64-setup.exe` | 27,510,915 | `435ac9b9f3e78fd30a39616076857ab2d54e8405130391d3380799551ef9a2a7` |
| `Mesh-Chat_0.2.80_x64_en-US.msi` | 29,511,680 | `eff89ca1701d677a2d3027bd2fb7027d76aad287d4924e202f777257222be217` |
| `mesh-chat-0.2.80-android-arm64-release.apk` | 34,082,515 | `fe5227c7f120e892482c1fa4bc435bbc15141ff4a8bc55de617c2523dd89e525` |

Still open: physical Android call/runtime prompt behavior, audio focus and
foreground service, physical Windows↔Android calls, ICE restart, TURN quotas,
video quality, and C5.

## WebRTC STUN/TURN settings, 2026-10-19

**0.2.79 / Android 2079** adds validated STUN/TURN settings, encrypted-at-rest
TURN credentials, relay-only mode, an active-call ICE handoff, and a
Direct/Relayed path badge.

Validation:

- Frontend TypeScript: passed.
- Frontend tests: **234 passed**.
- Frontend production build: passed.
- Full service suite: **1024 passed, 46 skipped**.
- GitHub Actions
  [run 39369294109](https://github.com/ahouchens/mesh-chat/actions/runs/39369294109)
  passed Verify, Windows packaging, Android packaging, and Publish.
- Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.2.79>.

Published assets:

| Artifact | Size | SHA-256 |
|---|---:|---|
| `Mesh-Chat_0.2.79_x64-setup.exe` | 27,512,952 | `6c4ae556d5477954453aefc44d5be3b294a8ac570ba7179689bd84780627cd55` |
| `Mesh-Chat_0.2.79_x64_en-US.msi` | 29,511,680 | `28e66977196deb857af3dca18c6f8ae446f1eeb947585f51a723411d1ce2239a` |
| `mesh-chat-0.2.79-android-arm64-release.apk` | 34,082,641 | `fae2365414b2c0dfb0c26f0026b6e61e1702acf20f065284df9929a11a909f15` |

Still open: ICE restart/reconnect, TURN quotas, physical multi-device calls,
Android runtime permission/audio focus, video quality, and C5.

## WebRTC video surface and Android call permissions, 2026-10-19

**0.2.78 / Android 2078** adds Audio call / Video call choices, camera capture,
local/remote video, camera on/off, and the Android `RECORD_AUDIO`,
`MODIFY_AUDIO_SETTINGS`, and `CAMERA` declarations. The C6 group-call decision
is recorded in ADR 0020; group calls are not implemented.

Validation:

- Frontend TypeScript: passed.
- Frontend tests: **234 passed**.
- Frontend production build: passed.
- Full service suite: **1014 passed, 46 skipped**.
- GitHub Actions
  [run 39367262608](https://github.com/ahouchens/mesh-chat/actions/runs/39367262608)
  passed Verify, Windows packaging, Android packaging, and Publish.
- Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.2.78>.
- APK package inspection: versionCode 2078, versionName 0.2.78, and the three
  call permissions are present.

Published assets:

| Artifact | Size | SHA-256 |
|---|---:|---|
| `Mesh-Chat_0.2.78_x64-setup.exe` | 27,508,927 | `cab5202ff8746b3afd57cd36d49482d46d4cb3065364e3029d104b20def1e149` |
| `Mesh-Chat_0.2.78_x64_en-US.msi` | 29,503,488 | `aa8e65e18baf67e38358d372fd8e2281a388ed76063348622fb87a8671c663c5` |
| `mesh-chat-0.2.78-android-arm64-release.apk` | 34,082,306 | `ee44e9710fe1e44e67304f40622da8999db35cefeb4a3c34c086a26e2c65e022` |

Still open: physical Windows↔Windows and Windows↔Android calls, Android
runtime microphone/camera permission, audio focus/foreground behavior,
STUN/TURN, physical video quality, C4 hardening, and C5.

## WebRTC 1:1 audio call surface, 2026-10-19

**0.2.77 / Android 2077** adds the first 1:1 audio call surface and durable
call transport:

- call button for approved contacts, incoming-call banner, Accept/Decline;
- WebView `RTCPeerConnection`/`getUserMedia` media with mute and hangup;
- signed `CALL_SIGNAL` documents over LXMF;
- `start_call`, `answer_call`, `add_call_candidate`, `call_media`, `end_call`.

Validation:

- Frontend TypeScript: passed.
- Frontend tests: **234 passed**.
- Frontend production build: passed.
- Full service suite: **1014 passed, 46 skipped**.
- GitHub Actions
  [run 39365694684](https://github.com/ahouchens/mesh-chat/actions/runs/39365694684)
  passed Verify, Windows packaging, Android packaging, and the published
  release step.
- Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.2.77>.

Published assets:

| Artifact | Size | SHA-256 |
|---|---:|---|
| `Mesh-Chat_0.2.77_x64-setup.exe` | 27,504,305 | `6c8538b49a65276694d8e24f3fbf74350ee47db5ec8a2a2d53c0c8525276018b` |
| `Mesh-Chat_0.2.77_x64_en-US.msi` | 29,507,584 | `043e0fb958e0fe68b953703d85cd93eff483c411e2cea83e998a6a4cef679f3f` |
| `mesh-chat-0.2.77-android-arm64-release.apk` | 34,082,283 | `59c3f7b98c9bd25e59ab9b313b8d215c44ac19135dc1e9eb1f9977ce90f97666` |

The isolated C0b synthetic loopback and C1 microphone device spikes still pass.
The direct WebView call path has not been qualified on two physical devices,
over the public Internet, over STUN/TURN, on Android background/audio-focus, or
with video. Those remain open.

## WebRTC calls foundation, 2026-10-19

**0.2.76 / Android 2076** adds the C0a signed call-signaling foundation and
keeps TCP access-point onboarding as the default connection path. No WebRTC
media stack, call UI, STUN/TURN configuration, or physical call is shipped.

Validation:

- `service/tests/test_webrtc_signaling.py`: **12 passed**.
- Full service suite: **1007 passed, 46 skipped**.
- GitHub Actions
  [run 39361103319](https://github.com/ahouchens/mesh-chat/actions/runs/39361103319)
  passed Verify, Windows packaging, Android packaging, and the published
  release step.
- Release: <https://github.com/ahouchens/mesh-chat/releases/tag/v0.2.76>.

Published assets:

| Artifact | Size | SHA-256 |
|---|---:|---|
| `Mesh-Chat_0.2.76_x64-setup.exe` | 27,487,550 | `58af920f25bcb7ef679838ab02755a5deeeb248b6e94ff96f752cbd8ace97981` |
| `Mesh-Chat_0.2.76_x64_en-US.msi` | 29,483,008 | `a12c13fe8f436786da947bc0ca652270818a50d012e4ef4a2fd6db9d011d0f26` |
| `mesh-chat-0.2.76-android-arm64-release.apk` | 34,065,822 | `7346b83efa4ef316e41adefb4a3d300c28d2921181e8bc7517bb1fce00821709` |

The isolated C0b spike (`experiments/webrtc-call/spike.py`) passed with
bidirectional decoded Opus audio and verified C0a signaling on host candidates.
The isolated C1 device spike (`experiments/webrtc-call/live.py`) captured the
real Windows microphone, decoded it over WebRTC/Opus, and passed with
microphone energy present; `--play` also passed on the selected output device.
These are local experiments, not shipping calls.

Still open: service/LXMF signaling transport, call persistence, call UI,
STUN/TURN, Windows↔Android calls, Android audio focus, video, and physical
device qualification.

## Direct connectivity increment, 2026-10-16

Native qualification now runs in GitHub Actions. At `cbcf659`,
[run 38854581893](https://github.com/ahouchens/mesh-chat/actions/runs/38854581893)
passed all three jobs: controlled peers on Windows and Linux, and an Android
ARM64 cross-compile with Rust 1.88.0. The desktop jobs include RNS-signed public
certificate authorization, mutual TLS, DATAGRAM boundary checks, retained socket
ownership, peer-key mismatch, engine death, queue limits, and real service traffic.
The native send-path regression fills the 128-item budget with tiny DATAGRAMs,
rejects the next send, drains the queue, and verifies that sending resumes.
The initial run passed both desktop jobs but failed Android SDK setup because
setup-android requested the obsolete `tools` package; selecting `platform-tools`
resolved that setup failure.

The real topology uses two isolated RNS/LXMF service processes with bounded
inherited packet channels and the GitHub-built native QUIC bridge. It verifies
join acknowledgment before approval, admission, fresh workspace-scoped transport
credentials, bidirectional messages, ratchets, endpoint receipts, and offline
state after carrier death. It has no TCP carrier, LAN discovery, relay, or public
discovery. Source mode replaces only the native packet carrier with inherited
queues so service and adapter behavior can be checked locally.

Run source mode with `MESH_CHAT_RUN_DIRECT_FABRIC_TESTS=1`. Set
`MESH_DIRECT_PROOF_BINARY` to the GitHub-built `packet_bridge` executable to run
the native variant. `MESH_DIRECT_BINDING_PYTHON=python` supplies the protected
service runtime for the Rust identity-binding integration test. RNS private keys
stay in Python; TLS private keys stay in Rust.

The adapter refuses pending activation with another RNS interface or transport
routing enabled and retires itself if either changes. Tests cover exact RNS
packet destinations, path requests, bounded Link/receipt tracking, stale session
callbacks, per-peer queues and shared profile adapter budgets. This is isolated
context evidence, not support for the shipping shared router. Full pipeline
resource accounting, platform embedding, public-Internet topology, Android
lifecycle/battery behavior, and physical device results remain release gates.

Local non-integration validation passed 573 tests with unhandled-thread warnings
treated as errors (7 skipped, 6 integration tests deselected). Skips require
packaged artifacts or non-Windows paths. The final source topology passed after
routed-packet filtering was tightened. UDP mapping tests cover TCP/UDP creation,
renewal and removal, wrong-protocol/version/zero-lease rejection, old TCP records,
and fallback. Existing connectivity and participant-invitation tests still pass.

Join-receipt tests cover atomic storage, forged/misbound receipts, replay, loss,
expiry/revocation, restart, upgrade and persistence before route setup. The
existing real RNS/LXMF remote-access harness also requires verified application
receipt before approval. The frontend suite passed 176 tests; subsequent focused
receipt checks and TypeScript `--noEmit` passed. `git diff --check` and native
source formatting passed.

Native, frontend/package and release builds run only in GitHub Actions, as
required by the roadmap. No native build was performed locally. A successful
proof or cross-compile is not a packaged application or physical-device test.

Transactional binding acceptance additionally passes concurrent conflicting-import,
exact-scope replay isolation, changed authority/challenge/expiry, encrypted write
failure, commit rollback, and reopen/rotation regression checks. The focused binding
and vault suite passed 54 tests (one platform skip), and the real two-service source
topology passed with transactional acceptance. This increment changes Python source;
the native qualification above identifies the earlier tested native commit.

The private admitted-workspace authority loader passes a real signed-admission
regression covering wrong issuer/audience, local identity loss/substitution,
inactive workspace states, a foreign signed manifest, and member removal. The
two-service source topology also passes using this service loader. GitHub runs
this regression on Windows and Linux; no renderer command was added.

The pending-join loader additionally rejects preview-only attempts, changed
issuer/audience/scope, revoked/expired/consumed invitation records, an expired
signed invitation, admission/decline/removal, substituted local identity, and a
missing or misdirected join delivery. The full run passed 545 other tests;
after correcting the expiry assertion to expect `InvitationExpired`, the new
regression passed separately (7 skips and 6 integration deselections unchanged).
The source topology passes with the join
saved before carrier authorization. The prior admitted-workspace increment
`41fb859` passed all native jobs in
[run 38855759048](https://github.com/ahouchens/mesh-chat/actions/runs/38855759048).

Owner pending negotiation tests cover preserved preparation retries, wrong
challenge, failed persistence before selection, competing valid responders,
reopening the vault, identical replay, conflicting/lower generations, expiry and
revocation. Selection leaves join-request storage and workspace membership
unchanged. The real source topology passes with the persisted owner challenge.
The prior joiner-loader increment `c692c14` passed all native jobs in
[run 38856186805](https://github.com/ahouchens/mesh-chat/actions/runs/38856186805).

Expired owner-negotiation replacement adds checks for active-attempt rejection,
stale compare-and-swap input, conflicting retries, failed-write rollback,
idempotence, preserved selected peer/generation, old-challenge rejection,
higher-generation recovery, reopening the vault and invitation revocation.
The workspace, binding and vault regression suite passed 101 tests with one
platform-specific skip. The source integration harness is unchanged by this
private control increment. The preceding owner-selection commit `37d6afe` passed
all native jobs in
[run 38900551953](https://github.com/ahouchens/mesh-chat/actions/runs/38900551953).

The initial Offer codec tests cover the absence of an audience, rejection as a
binding, generation rotation/conflicts, wrong authority/certificate/signature,
signed invalid fields, expiry, canonical encoding, duplicate keys and byte/depth
limits. Both Windows and Linux CI include this codec suite. It remains a pure
codec without an import or activation path. The preceding replacement commit
`0f40ad0` passed all native jobs in
[run 38901347792](https://github.com/ahouchens/mesh-chat/actions/runs/38901347792).

Answer/Ready codec regressions cover full-chain verification, identical replay,
conflicting generation, exact parent substitution, invalid signed envelopes,
forged signatures, certificate substitution, expiry, parent validity bounds,
wrong audience and non-advancing Ready generations. The exchange, Offer, binding
and workspace regression suite passed 131 tests. The preceding Offer commit
`0ee2130` passed all native jobs in
[run 38901917302](https://github.com/ahouchens/mesh-chat/actions/runs/38901917302).

Durable owner Answer acceptance passes the responder-selection regression in
both binding and envelope modes, including missing Offer, rollback, concurrency,
restart, replay and replacement-challenge cases. The targeted exchange, Offer,
binding, workspace and vault suites passed 145 tests with one platform skip.
The real two-service source topology passed using persisted Offer/Answer state.
The prior codec commit `771a365` passed all native jobs in
[run 38906448204](https://github.com/ahouchens/mesh-chat/actions/runs/38906448204).

Joiner Ready acceptance tests cover a missing saved Answer, failed-write rollback,
identical replay, restart, conflicting owner generation, Answer replacement,
obsolete-parent rejection, higher-generation recovery, expiry and post-admission
rejection. The exchange, Offer, binding, workspace and vault suites passed 146
tests with one platform skip; the final recovery assertion passed separately. The previous
durable Answer commit `8c33b54` passed all native jobs in
[run 38919767480](https://github.com/ahouchens/mesh-chat/actions/runs/38919767480).

Native `PreparedAttempt` tests now cover exact session/generation/Answer matching,
60-second windows, duplicate suppression, Ready generation conflicts, lifetime
expiry, fresh-process rejection and same-socket/key QUIC packet transfer. These
new Rust tests passed on Windows and Linux at `f797d01`, including the real
RNS/LXMF topology; Android ARM64 compilation also passed in
[run 38923294960](https://github.com/ahouchens/mesh-chat/actions/runs/38923294960).
The first run failed the transfer test because a temporary outbound path was
dropped immediately after sending. Both path handles now remain alive through
reception. No native build or native test ran locally.
The preceding Ready-acceptance commit `5ca44b5` passed all native jobs in
[run 38920216664](https://github.com/ahouchens/mesh-chat/actions/runs/38920216664).

The packet bridge now exercises `PreparedAttempt` on both peers before native
activation. Its private initialization frame binds session IDs, generations and
a bounded remaining lifetime; authorization carries the accepted local document
digests. Socket addresses must remain unchanged through activation. The updated
source topology passed with the joiner's Offer/Answer durably saved. Native CI
qualification passed on Windows/Linux (native tests and real RNS/LXMF topology)
and Android ARM64 compilation at `7824fd2` in
[run 38924221050](https://github.com/ahouchens/mesh-chat/actions/runs/38924221050).

Native cancellation regressions assert immediate socket/key release, idempotent
cancel, refusal to re-arm or activate cancelled state, address rebinding after
release, and expiry cleanup. The controlled native topology now requires graceful
cancellation at pending-to-admitted replacement and final teardown; forced process
termination cannot satisfy those assertions. Source topology passed. Native tests
and the strict teardown topology passed on Windows/Linux; Android ARM64 compilation
passed at `0c3884c` in
[run 38925223083](https://github.com/ahouchens/mesh-chat/actions/runs/38925223083).

Native carrier expiry probes now exercise pre-authorization and active-session
expiry without closing stdin or sending cancellation. They assert process exit
and offline notification to both consumers. Source validation passed its topology
and skipped these two native-only probes. Both probes and the real topology then
passed on Windows/Linux in GitHub; Android ARM64 compilation passed at `839b40a` in
[run 38926921146](https://github.com/ahouchens/mesh-chat/actions/runs/38926921146).

Activation-time revalidation now rejects both peers' old pending authorization
after admission, clears cached permission and marks adapters offline before fresh
admitted credentials are installed. The source topology passed this assertion and
subsequent messaging. Native tests/topology passed on Windows/Linux, and Android
ARM64 compilation passed at `0af3059` in
[run 38927826917](https://github.com/ahouchens/mesh-chat/actions/runs/38927826917). The two native expiry
probes remain skipped locally because they require the GitHub-built carrier.

## Commands

Focused service and UI checks:

```text
python scripts/test.py
```

`scripts/test.ps1` is the equivalent Windows helper used by the recorded build.

Sidecar packaging:

```text
python scripts/build_sidecar.py
```

The script derives the native Rust host triple, builds with the current Python
interpreter, and deliberately refuses cross-compilation. Run it on every
target operating system.

Real four-process mesh topology (opens loopback TCP listeners):

```sh
MESH_CHAT_RUN_NETWORK_TESTS=1 python -m pytest service/tests/test_topology_harness.py -v -s
```

PowerShell equivalent:

```powershell
$env:MESH_CHAT_RUN_NETWORK_TESTS = "1"
.\.venv\Scripts\python.exe -m pytest .\service\tests\test_topology_harness.py -v -s
```

Require the same topology to use the OS encrypted-workspace adapter:

```sh
MESH_CHAT_RUN_NETWORK_TESTS=1 MESH_CHAT_REQUIRE_PROTECTED_STORAGE=1 \
  python -m pytest service/tests/test_topology_harness.py -v -s
```

PowerShell equivalent:

```powershell
$env:MESH_CHAT_RUN_NETWORK_TESTS = "1"
$env:MESH_CHAT_REQUIRE_PROTECTED_STORAGE = "1"
.\.venv\Scripts\python.exe -m pytest .\service\tests\test_topology_harness.py -v -s
```

Rust/Tauri boundary:

```text
cargo check --locked --manifest-path src-tauri/Cargo.toml
python scripts/build_desktop.py
```

Windows toolchain helpers:

```powershell
.\scripts\cargo-check.cmd
.\scripts\desktop-build.cmd
```

Mobile packaging:

```text
python scripts/build_android.py
python3 scripts/build_ios.py  # macOS with Xcode and Apple signing only
```

Direct local fallback (opens a local TCP listener and launches two processes):

```sh
MESH_CHAT_RUN_DIRECT_LAN_TESTS=1 python -m pytest service/tests/test_direct_lan_harness.py -v -s
```

PowerShell equivalent:

```powershell
$env:MESH_CHAT_RUN_DIRECT_LAN_TESTS = "1"
.\.venv\Scripts\python.exe -m pytest .\service\tests\test_direct_lan_harness.py -v -s
```

Increment 12 administrator scale benchmark:

```powershell
.\.venv\Scripts\python.exe .\service\tools\workspace_administrator_benchmark.py `
  --events 50000 --samples 30 `
  --output .\docs\benchmarks\increment-12-workspace-administrators.json
```

Increment 14 linked-desktop scale benchmark:

```powershell
.\.venv\Scripts\python.exe .\service\tools\workspace_linked_device_benchmark.py `
  --events 50000 --samples 30 `
  --output .\docs\benchmarks\increment-14-linked-desktop-devices.json
```

The 0.2.7 harness runs two configurations. The first advertises signed TCP hints
from both peers, times reverse-route approval, then verifies direct chat,
application receipt, group invitation and join, a group message, and another
direct message after group activity. The second shapes the joining peer like a
phone: it opens the inviter's signed TCP hint but exposes no reverse listener,
then proves direct messages and receipts in both phases over that full-duplex
connection. Keep the always-on deterministic two-peer service flow and the
focused approval/direct-message regression file in the ordinary suite as well;
the opt-in real-network harness does not replace them.

## Private-group release gates

Passing ordinary one-to-one tests is not sufficient to release private groups
or announcement channels. Group verification must use the reference RNS/LXMF
stack and individual destinations; a test double or accidental
`RNS.Destination.GROUP` path cannot establish this gate.

Automated protocol and security coverage must include:

- canonical round trips for genesis, member cards, active and closed manifests,
  targeted invites, join and leave statements, every group payload kind, and
  the eight-member boundary;
- exact-field rejection, malformed encodings, oversize documents, signature
  substitution, identity/destination mismatch, group-ID re-derivation, duplicate
  members, unsorted manifests, multiple or missing owners, and unauthorized
  roles or posting policies;
- invitation expiry, wrong-target invitations, replayed acceptances, acceptance
  bound to the wrong nonce/manifest/group, and group-scoped consent that does
  not silently create ordinary direct-message trust;
- durable invitation delivery states, application-receipt promotion to
  **Invitation ready for review**, bounded automatic backoff, restart recovery,
  and owner-triggered **Retry invitation** using the contact's newest approved
  route hints without creating a duplicate invitation;
- manifest next-epoch and previous-hash enforcement, rollback, skipped epoch,
  two owner-signed manifests for one epoch, owner substitution, stale sender,
  removed sender, stale posting-policy attacks, owner leave rejection, and the
  terminal closed-state rule;
- strict group metadata kind combinations, logical child IDs versus the common
  group-message ID, sender-sequence bounds/replay, receipt source binding, and
  a receipt that attempts to update another member's delivery;
- exactly one child delivery for every other active recipient, with no copy for
  the sender, an invited-but-unaccepted person, a departed person, or a removed
  person;
- atomic creation of the logical message and complete child set, idempotent
  recovery after a process kill at every fan-out/handoff/receipt boundary, and
  no duplicate visible message after native retransmission or delivery-method
  change;
- no history backfill on admission, future-copy exclusion after removal, and
  honest aggregate states for all delivered, partial, pending, expired, and
  mixed outcomes; and
- encrypted-vault and full-profile marker scans covering group names, member
  display names, manifests, messages, drafts, outbox children, and receipts.

Real-network integration must exercise three-, five-, and eight-device groups
over direct and propagated LXMF. Partition at least one recipient, deliver to
the others, restart the sender mid-fan-out, reconnect the recipient, and prove
that only the missing child is retried. Repeat while rotating a route hint,
changing an IP address, suspending a mobile device, and making the owner
offline. A blind propagation node must store only recipient-encrypted objects;
scan its persistent files and capture traffic as release evidence.

The invitation test must not rely on Firebase, APNs, or any other central push
service. With propagation disabled, remove every Reticulum path and confirm the
owner remains honestly at **Invitation queued** or **Trying to find device**
and the recipient sees no invitation. Restore a permitted Reticulum path and
confirm that the same durable invitation arrives without creating a second
logical invitation. If an approved propagation node is tested, distinguish
**Stored securely for delivery** from endpoint receipt and application receipt.

Membership-partition testing must remove a disconnected member, deliver the
next signed epoch to the reachable members, and attempt both an old-epoch
message and an old invitation replay. The expected result is explicit eventual
revocation: updated members reject the removed sender, while a still-partitioned
endpoint may retain its last valid view until it receives the new epoch. No UI
may describe that transition as instantaneous global removal.

Physical-device release testing must cover Windows-to-Android and, when a
signed build is available, macOS-to-iOS creation, invitation, acceptance,
posting policy, partial delivery, suspend/resume, removal, and upgrade from a
profile containing only one-to-one chats. Test the eight-person limit and
screen-reader/keyboard announcements for group invitations, membership changes,
posting restrictions, and per-recipient delivery details.

Install the same current candidate build on every device in a physical group
test. Older group-unaware builds are not a compatibility result even when an
existing one-to-one chat still works. On Android, repeat invitation delivery
with Mesh Chat visibly in the foreground, local-network permission granted,
battery restrictions removed for the test, and both devices on the same
non-guest network for the default direct path. Then background/suspend the app,
verify that the UI makes no promise of cloud push delivery, return it to the
foreground, and verify recovery when a Reticulum path becomes available.

### Group invitation reliability procedure

For every release candidate, retain a timestamped screen recording and service
logs for this sequence:

1. Verify that the owner and invitee packages report the same current candidate
   version. Upgrade in place so the established contact and its signed route
   hints remain available.
2. With no usable path and no propagation node, create a two-person group.
   Confirm that **Members & security** shows **Invitation queued** or **Trying
   to find device**, and that the invitee receives no dialog.
3. Restore the intended Reticulum path with both apps running. Record the
   transitions through **Sending invitation** and, when applicable, **Reached
   device · confirming receipt**. Only the verified application receipt may
   produce **Invitation ready for review**.
4. Break the path again while the invitation is still pending. Use **Retry
   invitation** and prove that it starts an immediate attempt with current
   contact hints but does not falsely advance the state or create a duplicate.
   Restore the path and verify that automatic or manual retry delivers the
   original logical invitation once.
5. Keep the Android app in the foreground through **Accept invitation** and the
   owner's next signed membership epoch. Confirm that the owner does not count
   the invitee as an active recipient before that acceptance completes.
6. Exercise restart and Android suspend/resume at queued, endpoint-received,
   and application-receipted boundaries. State must recover from the encrypted
   outbox and must never be inferred merely from a network acknowledgment.
7. Exercise signed expiry. After expiry, **Retry invitation** must not revive
   the capability, and the invitee must be unable to accept it.

## Recorded 0.1.7 first-message layout hotfix verification — 2026-10-03

- Version 0.1.7 fixes the approved-conversation grid layout that could make the
  Windows and Android chat views look blank immediately after the first message
  replaced the larger empty-thread panel. The messaging transport and saved
  records remained active during the observed failure.
- Install 0.1.7 over 0.1.6 on **both** the Windows computer and Android phone.
  Do not uninstall either app and do not clear either app's data. Existing
  profiles, contacts, invitation relationships, and saved messages remain.
- Devices already connected on 0.1.6 do not need a new invitation after this
  hotfix upgrade. A new invitation is still required when establishing the
  direct-LAN relationship from an invitation created before 0.1.6.
- The Android package is
  `dist/mobile/mesh-chat-0.1.7-android-arm64-debug.apk`, with version name 0.1.7
  and version code 1007. The Windows packages are
  `Mesh Chat_0.1.7_x64-setup.exe` and `Mesh Chat_0.1.7_x64_en-US.msi`.
- The focused run passed 58 Python service/layout tests with three expected
  platform/opt-in skips, 12 renderer tests, TypeScript compilation, and the
  production Vite build. The regression coverage pins the optional connection
  banner, message list, and composer to named grid areas and exercises the
  first stored message, invalid timestamps, send failure recovery, and the
  top-level renderer recovery screen.
- A live Windows 0.1.7 run against the profile that exhibited the fault loaded
  the saved chat without clearing data. WebView geometry reported a collapsed
  0 px optional-banner row, a 624.61 px message row, and an 81.39 px composer;
  two saved messages rendered and no renderer exception occurred.
- The packaged Windows sidecar passed EFS-protected profile initialization,
  signed invitation creation with a direct-LAN hint, graceful shutdown, and
  stderr-redaction checks. The Windows app and NSIS installer report version
  0.1.7. The development installers are not Authenticode-signed.
- The Android arm64 APK reports minimum API 24 and target API 36. APK Signature
  Scheme v2 verification passed with the same debug certificate used by 0.1.6
  (certificate SHA-256
  `D6DBFF63834666BACE3D75B49234726E97CCCE26D2B9E9516309682E0A33143F`).
- A physical post-upgrade Windows-to-Android send-and-render retest remains
  open. The observed physical message delivery, persistence, application
  receipt, and both established TCP directions were confirmed during diagnosis;
  the new APK has not yet been installed on that phone.

| Artifact | SHA-256 |
| --- | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | `4474639F6772EEE6FD5E993086E4B35DAC6E396FFE0ECCA2835731A44681CBCA` |
| `mesh-chat.exe` | `5FBFAD8E4D006C0317F912353B8EEA4A3939C4FE4585C0892D5051D0709CDE11` |
| `Mesh Chat_0.1.7_x64_en-US.msi` | `D3E9A476B7F954299797AC9662470E54DCFB951ABD2DFCFB100DEFA29EE3C1B8` |
| `Mesh Chat_0.1.7_x64-setup.exe` | `4BE40433B346363E553DF4D52DE43C5CAF2159AA47458A85969E9032938464FE` |
| `mesh-chat-0.1.7-android-arm64-debug.apk` | `14A3E37EB184073F741067CB2815CFA07A84F06E56723FB2670690DC27D32CA5` |

## Recorded direct LAN fallback verification — 2026-10-03

- Version 0.1.6 adds a bounded local TCP listener and advertises concrete local
  addresses only through cryptographically signed invitation hints. It is a
  same-LAN fallback for blocked IPv6 multicast, not an Internet relay.
- The opt-in TCP-only harness passed with automatic nearby discovery disabled.
  Two isolated Mesh Chat service processes established the hinted TCP path,
  delivered a first contact request from an initially unknown identity,
  completed explicit acceptance, exchanged a chat message, and completed the
  application receipt flow.
- The first-contact bootstrap verifies both the signed invitation and the
  native LXMF message signature against the identity carried by that invitation
  before remembering the sender. Unknown or invalid messages remain rejected.
- Re-importing a new invitation for an existing contact refreshes its signed
  connection hints and retries an awaiting request without clearing either
  profile.
- **Upgrade/retest procedure:** install 0.1.6 over the existing Windows and
  Android apps, preserving their data; put both devices on the same non-guest
  LAN; create a NEW invitation/QR on the computer; scan or paste it on the
  phone; keep both apps open; and accept the foreground request on the computer.
  Invitations created by earlier versions do not contain this fallback hint.
- A physical Windows-to-Android 0.1.6 retest is still pending. The automated
  TCP-only pass proves the service path but does not substitute for Android OS,
  Wi-Fi access-point, and Windows firewall validation on the affected devices.
- The complete verification run passed 57 Python service tests and 8 renderer
  tests, followed by TypeScript compilation and the production web build. The
  opt-in direct-LAN harness also passed separately.
- The packaged Windows sidecar passed EFS-protected profile creation,
  initialization, invitation creation with a signed direct-LAN hint, graceful
  shutdown, and stderr-redaction checks. The Windows app and NSIS installer
  report version 0.1.6; the current development packages are not
  Authenticode-signed.
- The Android arm64 APK reports version 0.1.6 (version code 1006), minimum API
  24, and target API 36. APK Signature Scheme v2 verification passed with the
  same debug certificate as the prior package (certificate SHA-256
  `D6DBFF63834666BACE3D75B49234726E97CCCE26D2B9E9516309682E0A33143F`).

| Artifact | SHA-256 |
| --- | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | `837DB3659AD6BFE9388D07F0514979CB759AC879D40013A3EC955853E5E6E5DB` |
| `mesh-chat.exe` | `14CEAC2901F59AE215C94885F8EC572637D3CD07B3AB72A5D883FA0F64DDC904` |
| `Mesh Chat_0.1.6_x64_en-US.msi` | `52ABB7B65A4438EFD4D9646E3D8FCD215F09F0D185505DE7FC0201C35987557B` |
| `Mesh Chat_0.1.6_x64-setup.exe` | `F90DCC3441684C2BB95C982FF811A3B6C5F8815BD9E1E8063B169B252FC95263` |
| `mesh-chat-0.1.6-android-arm64-debug.apk` | `B05FB98D83D11BE2F83F573D15D4B1813F2FE26C89640D0F8489A2C1A1C6F104` |

## Recorded 0.1.5 connection-request regression verification — 2026-10-03

- Focused suite: 45 Python tests passed with 2 expected platform/opt-in skips;
  7 renderer tests, TypeScript compilation, and the production Vite build
  passed.
- An incoming request now opens a foreground **Connection request** prompt with
  Accept and Decline on the invitation-creating device. If the QR/invitation
  dialog is open, it remains mounted behind the request prompt so its state is
  preserved.
- Desktop request state is reconciled when the window regains focus, when it
  becomes visible, and on a short foreground interval. This covers a request
  that arrived before the renderer listener was attached or whose one-time
  event was otherwise missed.
- The joining device now distinguishes a locally queued request from endpoint
  evidence. It says **Trying to reach...** until the request reaches the other
  device, and says **Waiting for acceptance** only after endpoint receipt.
- Embedded-network startup cleanup, usable-interface reporting, and recovery
  are covered by regression tests. The app reports when no receiving
  AutoInterface is available instead of silently presenting a healthy state.
- The Windows packaged-sidecar smoke passed initialization, EFS-protected
  profile creation, signed invitation creation, graceful shutdown, and stderr
  redaction.
- Windows x64 executable, MSI, and NSIS bundles report version 0.1.5 and were
  linked successfully. These development installers are not Authenticode
  signed.
- Android arm64 APK version 0.1.5 was assembled with minimum API 24 and target
  API 36. APK Signature Scheme v2 verification passed, and the signing
  certificate matches the prior development build so it can be installed over
  the existing app without clearing its profile.
- A physical Windows-to-Android delivery test remains open. The previously
  observed phone request did not reach the running Windows Reticulum instance;
  local IPv6 multicast, firewall, or wireless client-isolation conditions
  still need to be checked on the affected network if 0.1.5 remains on
  **Trying to reach...**.

| Artifact | SHA-256 |
| --- | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | `4DB0335F04ECA0C0F6CF6E2B8069DBB98DE31238D663703A058AA261C042E96B` |
| `mesh-chat.exe` | `428AEE347210F43F6BE765E8862245EA2739EE768C27706FDDD2DCA89C642072` |
| `Mesh Chat_0.1.5_x64_en-US.msi` | `D4B3A4257F36AA4CB334B4B0432F1C993B285EA71CFB4F2FB6D572D030D7B5CA` |
| `Mesh Chat_0.1.5_x64-setup.exe` | `EBBCB5D53C8BAC0CBBA5E7370920C2534A9F87684B7DF99EEEF6CCBE7877DC53` |
| `mesh-chat-0.1.5-android-arm64-debug.apk` | `419E41FF14493AF6A55A8E92381157C37C14DB45AEB0EFDA479486F75B324D72` |

## Recorded Windows verification — 2026-10-02

Environment: Windows 10.0.19045 x64, Python 3.12.14, Rust 1.99.0,
RNS 1.5.5, LXMF 1.2.0, Node.js 24.19.0.

- Focused suite: 31 Python tests passed with the opt-in topology and the
  Linux-only `/sys` device-tree test skipped; 2 renderer tests passed;
  TypeScript and the production Vite build passed.
- Full protected integration suite: 27 tests passed, including the real
  four-process A→B→C→D topology. The destination reported exactly three hops,
  its ratchet was present before send, the LXMF signature validated, and no
  plaintext marker appeared in B or C persistent files.
- Packaged-sidecar smoke: initialize, EFS-protected profile creation, signed
  invitation generation, graceful shutdown, and stderr-redaction checks all
  passed through the built executable's framed stdin/stdout IPC.
- `cargo check --locked` passed. A release executable, MSI, and NSIS installer
  were linked and bundled successfully. Native visual automation was not
  available on the verification host, so manual UI and assistive-technology
  review remain open.
- Android arm64 debug packaging passed with minimum API 24 and target API 36.
  `apksigner` verified the APK Signature Scheme v2 signature. The merged
  manifest disables backup and cleartext traffic and includes the camera and
  Wi-Fi multicast permissions. A physical-device smoke test remains open.

Artifact hashes for this run:

| Artifact | SHA-256 |
| --- | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | `CC4EEEBB7CFC4A044ECE02DAFEC9516F0E0E4DDD2530EAB7A06C3720AF30C8AB` |
| `mesh-chat.exe` | `52DC68028A9B06755D387A0D7CF97B8D78084027E68759FEB90D51D27668CED0` |
| `Mesh Chat_0.1.0_x64_en-US.msi` | `843B49788ED705ED34D4E92075D7A5CD1011741500EDDFECD9F6B37ABB7326BB` |
| `Mesh Chat_0.1.0_x64-setup.exe` | `70A1C1119F33DB3967199396B45504733361FC926863D8B92263EA65D178D130` |

## Recorded Android regression verification — 2026-10-03

- Focused suite: 35 Python tests passed with 2 platform/opt-in tests skipped;
  2 renderer tests, TypeScript, and the production Vite build passed.
- Phone clipboard formatting tests cover wrapped tokens, invisible formatting
  characters, and an invitation embedded in ordinary shared text. Signature,
  destination, expiry, and identity checks remain authoritative.
- Android command payloads are forwarded as the original serialized JSON. This
  avoids Jackson's unsupported `JSONObject` field conversion, which previously
  replaced nested payloads such as `{ "invitation": "..." }` with an empty
  object before they reached the service.
- The mobile UI uses Tauri's native barcode-scanner plugin on Android and iOS;
  the browser camera path remains only as the desktop fallback.
- Both invitation-creation screens show the full shareable invitation first,
  along with its signed expiry, Copy, Share, Save, and QR options.
- A subprocess lifecycle regression now covers mobile profile creation,
  forced AutoInterface failure, invitation acceptance, idempotent retry, and a
  second-process reopen of the encrypted profile. The process remains alive
  and returns a structured network state instead of Reticulum's status-255
  process exit.
- The Android bridge now uses one process-long executor thread for Python
  initialization and every command. Embedded RNS process exits are converted
  to recoverable errors, while a failed optional interface is isolated.
- Android arm64 APK version 0.1.4 was assembled with minimum API 24 and target
  API 36. `apksigner` verified its v2 signature. The merged manifest includes
  camera access and continues to disable backup and cleartext traffic.

| Artifact | SHA-256 |
| --- | --- |
| `mesh-chat-0.1.4-android-arm64-debug.apk` | `8ACE8B42D4967B5A1E13723DCE9F2ED29FEAA1B4039B777F55C32BD8D83689D3` |

## Recorded Windows 0.1.3 packaging regression — 2026-10-03

- The focused suite passed with 33 Python tests, 2 expected skips, 2 renderer
  tests, TypeScript compilation, and the production Vite build.
- The Python messaging sidecar was rebuilt so `create_invitation` returns the
  signed expiry used by the updated invitation panel.
- The release executable reports product and file version 0.1.3. MSI and NSIS
  installers were linked successfully for Windows x64.
- Both invitation-creation screens place the complete shareable invitation at
  the top, followed by Copy, Share, Save, signed expiry, and QR options.
- These development installers are not Authenticode-signed. Windows may show
  an unknown-publisher warning until a production signing certificate is used.

| Artifact | SHA-256 |
| --- | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | `E4C540ACEE919E4C01DA17EC65480801D4E739B5384AB3308FAE1118C5FD3721` |
| `mesh-chat.exe` | `6BC4603D4971A2A9213F93D41E47A791B35DDAD7B76BC4E1640CF1A9C4ABAC75` |
| `Mesh Chat_0.1.3_x64_en-US.msi` | `703226D61F15C8183DF0957A79E54E8C724BCF360933E7A99D20EE4B3F7AA0E9` |
| `Mesh Chat_0.1.3_x64-setup.exe` | `9DB43D5299CBBE45724DCFC6BAD7C9BB71A4F5626D30F246ED869044A60876CE` |

## Recorded 0.2.0 private-group package verification — 2026-10-03

- The complete automated run passed **80 Python tests** with three documented
  platform/integration skips, **18 renderer tests**, TypeScript compilation,
  and the production Vite build.
- The opt-in real Reticulum/LXMF direct-LAN harness passed separately, as did
  the isolated four-process A→B→C→D topology harness.
- Eleven focused group-service tests passed, including simultaneous invitees,
  reversed membership-epoch arrival, replay after removal, remove/leave/close,
  old-epoch owner equivocation, restart recovery, application-receipt retry,
  and strict duplicate handling. Group protocol and IPC regressions bring the
  focused protocol/service/IPC total to 28 passing tests.
- The Windows x64 Rust release build completed. The NSIS and MSI packages both
  contain a sidecar whose SHA-256 exactly matches the newly built group-aware
  PyInstaller sidecar. The MSI reports product version 0.2.0.
- The Android arm64 APK reports version name 0.2.0, version code 2000, minimum
  API 24, and target API 36. `apksigner` verified its v2 Android debug
  signature. The packaged Chaquopy archive contains `group_protocol.pyc` and
  `group_service.pyc`; staged Android group sources are byte-identical to the
  service sources; and the packaged native library contains the complete group
  command allowlist.
- These Windows development packages are not Authenticode-signed, and the APK
  uses the Android debug certificate (certificate SHA-256
  `D6DBFF63834666BACE3D75B49234726E97CCCE26D2B9E9516309682E0A33143F`).
  Physical Windows↔Android multi-member group, suspend/resume, partition, and
  upgrade testing remains required before sensitive use.

| Artifact | SHA-256 |
| --- | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | `56BF76A316D11D18FB3AC04B48AA3BED388C39033B31CBC9FD6DA6902FB53C39` |
| `Mesh Chat_0.2.0_x64-setup.exe` | `84899608932B1DD80C7DF62C9909BC2E723A430C9E3EB7F5172BC184931AC8A6` |
| `Mesh Chat_0.2.0_x64_en-US.msi` | `53E93942B04763D216CFE1469B0184FA9AF28E504E5E00A62627A344B6327947` |
| `mesh-chat-0.2.0-android-arm64-debug.apk` | `DB8DE84EC8DCFD06BBE08284D1B29A5EE6A4B0DCC52FF4592CE82AFDCD663381` |

## Recorded 0.2.1 group-invitation reliability verification — 2026-10-03

- The complete automated run passed **82 Python tests** with three documented
  platform/integration skips and **19 renderer tests**. TypeScript compilation
  and the production Vite build also passed.
- The real two-process Reticulum/LXMF direct-LAN harness passed the complete
  contact invitation and approval, direct chat, group creation, targeted group
  invitation, recipient application receipt, and explicit group-acceptance
  sequence without a central relay or push service.
- Group-invitation reliability coverage verifies durable per-invite delivery
  state, application-confirmed **Invitation ready for review**, bounded
  automatic retry, restart recovery, manual `retry_group_invitation` with
  refreshed approved contact hints, signed expiry, and duplicate suppression.
- The Windows x64 executable, NSIS installer, and MSI report version 0.2.1.
  The installers contain the newly built invitation-reliability sidecar; the
  development packages remain unsigned by Authenticode.
- The Android arm64 APK reports version name 0.2.1, version code 2001, minimum
  API 24, and target API 36. `apksigner` verified its APK Signature Scheme v2
  debug signature.
- Packaged Python source hashes match the release source tree. The packaged
  native renderer-command allowlist contains `retry_group_invitation`, so the
  owner-side Retry control reaches the embedded service instead of being
  rejected at the native boundary.
- Physical Windows↔Android foreground/background, route-loss, and multi-member
  group testing remains required before sensitive operational use; the passing
  two-process harness does not substitute for Android lifecycle and Wi-Fi
  behavior.

| Artifact | SHA-256 |
| --- | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | `038EAA173698DC48C0F6EA342851F8A46526D073804DE5A6574E775DE4362E21` |
| `mesh-chat.exe` | `3EC66D870655698268C97C26CDA35AE2DD872EBC990EE89319853FC085CFD894` |
| `Mesh Chat_0.2.1_x64-setup.exe` | `D3057B8AE65D8757502F70141316D9E65DCAAD45AAF8040A1BD9196C1868F7F1` |
| `Mesh Chat_0.2.1_x64_en-US.msi` | `EF864D759D4C0D39C0FD60A34352049FF4FFA7D6E77A08460CD6E12DF266A07E` |
| `mesh-chat-0.2.1-android-arm64-debug.apk` | `B2C9E877CCBA22534097FE21FBBE39E17D2F17F4B5E92398F8BDA81AB08DF4EE` |

## Recorded 0.2.2 desktop lifecycle verification — 2026-10-04

- This is a historical record, not the current install recommendation. A later
  live 0.2.2 reproduction found that the PyInstaller supervisor and worker
  could survive a busy close. The worker retained the valid EFS-encrypted
  profile lock, and the lock-contention error was incorrectly presented as
  `protected_storage_unavailable`. The profile remained encrypted; no private
  data was lost and no plaintext fallback was used. Version 0.2.3 supersedes
  the lifecycle conclusion recorded here.
- The desktop close/relaunch failure was traced to the main Tauri window being
  destroyed without exiting the application. The headless process retained the
  single-instance endpoint and PyInstaller sidecars, so a later launch handed
  control to an instance with no window and appeared to do nothing. For an
  already affected 0.2.1 session, ending **Mesh Chat** and its
  `mesh-chat-service.exe` processes in Task Manager, or restarting Windows,
  releases that stale instance before launching 0.2.2.
- Version 0.2.2 changed desktop close to request application exit and attempted
  to release the messaging sidecar and single-instance endpoint. A launch handed to an
  already running instance now shows, restores, and focuses its main window.
  It forces a native hide/show refresh and recreates the configured main window
  when no live webview window remains.
  Exit cleanup uses a non-blocking service lock and a two-second process
  fail-safe. The later reproduction established that this was not sufficient
  to guarantee cleanup when a PyInstaller worker remained busy.
- The complete automated run passed **83 Python tests** with three documented
  platform/integration skips and **19 renderer tests**. TypeScript compilation
  and the production Vite build also passed.
- The Windows x64 Rust release compilation and full release build completed.
  All three Rust release unit tests passed, including the service-lock
  contention regression test for non-blocking exit cleanup.
  The executable, NSIS installer, and MSI report version 0.2.2, and both
  installers contain the matching rebuilt sidecar.
- That packaged Windows lifecycle smoke verified the exact sequence for its
  tested run: the first
  launch displayed the actual `Mesh Chat` Win32 title window; a second launch
  restored that window after both a raw native hide outside Tauri and a supported
  minimized state; an exact title-bar close terminated the host and every
  PyInstaller service process; and the following clean launch displayed the main
  window again. The final test close left no Mesh Chat GUI or service process.
  It did not reproduce the later busy-worker case and therefore did not prove
  cleanup for every close path.
- The matching Android arm64 debug APK reports version name 0.2.2 and version
  code 2002. Minimum API 24 and target API 36 remain unchanged.

| Artifact | SHA-256 |
| --- | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | `909F277F3FEB8548819B7F19AA4CAAF56CA8D40921084FECEACB0FCE39D5B3CD` |
| `mesh-chat.exe` | `E75E8A1D91B3CBD45FB0480241C04F3E6E594D41BA152A33EF8A31FE93A43668` |
| `Mesh Chat_0.2.2_x64-setup.exe` | `20722CEA3CCC9B7550EE7AA173E22B6418FF4E9B3947E3BC1B55D74785F1FABA` |
| `Mesh Chat_0.2.2_x64_en-US.msi` | `9B685D8D321DFFB820AACBC74CD0E6FFA2977571DCB6B30ABC58480D7241DED5` |
| `mesh-chat-0.2.2-android-arm64-debug.apk` | `75FB7EC1F8EAAF64724D683452B5694AF6C06C35B669CC2217E3AFF20ECCC5D0` |

## Recorded 0.2.3 profile-lock and desktop lifecycle verification — 2026-10-04

- The observed startup safety screen was traced to a stale 0.2.2 PyInstaller
  worker holding the profile lock, not to loss of NTFS EFS protection. The
  profile directory and private files remained EFS-encrypted, no private data
  was lost, and no plaintext fallback was used. Lock contention now has the
  distinct `profile_in_use` code and UI guidance; genuine protected-storage
  failures retain their fail-closed message.
- Invitation creation now has its own visible error state and **Retry
  invitation** action. A failed or timed-out attempt can be retried in the same
  dialog without discarding the rest of the UI state.
- Desktop initialization passes its exact `parent_pid` to the service. The
  service starts a parent-death watchdog before opening the vault, so a worker
  exits if its owning desktop disappears. Desktop close has an independent
  deadline: it first requests graceful shutdown, then terminates the recorded
  sidecar PID tree with the Windows system `taskkill` executable before exiting
  the host. Cleanup is bounded and ordered, and it never selects processes by
  executable name.
- The complete automated run passed **96 Python tests** with three documented
  skips, **22 renderer tests**, all **3 Rust release tests**, and the production
  frontend build. The packaged sidecar smoke passed EFS-protected profile
  initialization, signed invitation creation, connection-hint discovery, and
  shutdown.
- The live Windows lifecycle run created exactly three relevant processes: the
  desktop host plus the PyInstaller supervisor and worker. Closing the window
  left zero of those exact processes after **2,237 ms**. Immediate relaunch of
  the same encrypted profile succeeded, and the second close again left zero
  processes.
- The Windows executable, NSIS installer, and MSI report version 0.2.3. The MSI
  `File` table contains `mesh-chat.exe` at **4,760,064 bytes** and the matching
  sidecar at **18,147,673 bytes**. These development Windows packages are not
  Authenticode-signed.
- The Android arm64 debug APK reports version name 0.2.3, version code 2003,
  minimum API 24, and target API 36. It contains `arm64-v8a`, and APK Signature
  Scheme v2 verification passed with the development debug certificate.
- Install 0.2.3 directly over an existing release; do not uninstall the app or
  clear app data. To recover a stale pre-0.2.3 Windows process, restart Windows
  or use Task Manager to end **Mesh Chat** and every
  `mesh-chat-service.exe` process, then launch or install 0.2.3.

| Artifact | SHA-256 |
| --- | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | `36D1FF9EC2A88525C59068C4636C91E5698495DD1DE118D3D24841E1C0D3FB4F` |
| `mesh-chat.exe` | `42E63C5C8366653B77BF0E5CC73D5AAD8AA4D508809D7293293C95CA6B1D3A24` |
| `Mesh Chat_0.2.3_x64-setup.exe` | `B1158B7DDFF01790E03DD2471C41BB3974A22E493EE2F3D6F0181EC51C6975DC` |
| `Mesh Chat_0.2.3_x64_en-US.msi` | `D1E9E3F41BCF5D033746BE7AC73622A8AB41F0CB1C75D3825C44FD87E38CAD44` |
| `mesh-chat-0.2.3-android-arm64-debug.apk` | `C47BDC54472283AA9B113BCDBFEB6230FDEB116F06D2247592C2BC7BCFAC1ED2` |

## Recorded 0.2.4 one-to-one approval regression verification — 2026-10-04

- A physical Windows-to-Android run on the previous release reached the
  desktop **Connection request** dialog but failed after **Accept and open
  chat**. The group-route work caused approval to attach every signed reverse
  TCP route synchronously. Each unreachable address could consume Reticulum's
  connection timeout, so several valid hints could outlive the desktop command
  deadline even though the approval had already begun committing. The same
  approval path also attempted the durable `CONTACT_ACCEPT` once directly and
  again during its immediate outbox flush.
- Version 0.2.4 selects Reticulum's supported asynchronous TCP-client startup
  before configured or dynamically attached clients are constructed. It
  atomically commits the approved contact and exactly one retryable
  `CONTACT_ACCEPT`, then performs one outbox flush. Optional route-application
  failures remain contained, mark the settings dirty, and retry on a later
  send without creating another acceptance. This shared Python core is
  packaged in both the Windows desktop sidecar and Android APK.
- The complete automated run passed **106 Python tests** with three documented
  skips, **24 renderer tests**, and all **3 Rust tests**. The 21 focused group
  protocol/service tests remained green. All **9 tests** in
  `test_approval_regressions.py` passed, including eight reverse routes within
  the command budget, atomic approval/outbox persistence, exactly one
  `CONTACT_ACCEPT`, in-flight duplicate suppression, contained transport and
  route failures, dirty-route recovery, and retry without duplication. Renderer
  coverage also verifies that a timed-out approval is reconciled from a fresh
  service snapshot when it committed, while a truly pending request stays open
  with actionable retry guidance.
- The always-on deterministic two-peer service test completed profile and
  invitation creation, request delivery, approval, acceptance delivery,
  two-way trust, direct chat, application receipt, and delivered state while
  asserting that the one-to-one path created no group state.
- The opt-in real two-process Reticulum/LXMF direct-LAN harness advertised
  signed TCP hints in both directions. Approval completed in approximately
  **0.03 seconds**; direct chat and its application receipt passed, followed by
  group invitation and join, a group message, and another direct message after
  the group flow. This guards both one-to-one and group behavior in the same
  reference-stack run without a hosted relay.
- The packaged Windows sidecar smoke reported every EFS protection and command
  check true. Both the MSI and NSIS contained a sidecar whose SHA-256 matched
  the standalone release sidecar. The Windows development installers are not
  Authenticode-signed.
- The Android arm64 debug APK reports version name 0.2.4, version code 2004,
  minimum API 24, and target API 36. APK Signature Scheme v2 verification
  passed with development certificate SHA-256
  `D6DBFF63834666BACE3D75B49234726E97CCCE26D2B9E9516309682E0A33143F`.
  It contains only the `arm64-v8a` native architecture and packaged Python
  bytecode markers for atomic approval, dirty-route recovery, and asynchronous
  TCP startup.
- Install 0.2.4 directly over the existing Windows and Android apps. Do not
  uninstall either app or clear its data: package identities and the Android
  signing certificate are unchanged, so existing profiles, contacts, direct
  chats, groups, and saved messages are retained. A physical
  Windows-to-Android retest of these exact 0.2.4 packages remains pending and
  is still required before sensitive use.

| Artifact | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | 18,148,139 | `8BD4639B78A0F26F28BE481BA3E8C8B3924C856CC0F577967186B35C4AF059F8` |
| `mesh-chat.exe` | 4,760,064 | `E1CBFCD2615FB4DA052DB63EA7DA76ACEEDAC639380595DE0575172DEC1E373E` |
| `Mesh Chat_0.2.4_x64-setup.exe` | 19,624,480 | `7BC771E518E5ABA36737497BA949D8DAB27BCE3EA276B4629E65343E9F537675` |
| `Mesh Chat_0.2.4_x64_en-US.msi` | 20,373,504 | `63DBFE071984FFEA776728BC3262F337B6BFAD114FA6112264B34C44102080ED` |
| `mesh-chat-0.2.4-android-arm64-debug.apk` | 44,252,597 | `5AEC41364390FB73C96FB8B18F3C22FE8ABF11E8A74AB13EAFAE0C87FECBFFEE` |

## Recorded 0.2.5 first-message visibility and delivery-state verification — 2026-10-04

- A physical Windows-to-Android run on 0.2.4 connected both peers, but the
  first direct message did not appear in the conversation. Runtime metadata
  did not establish whether that particular chat command reached the sender's
  service. Separately, code analysis and a deterministic mobile regression
  reproduced a path where a durably saved send remained hidden: on mobile,
  where the desktop's periodic snapshot timer is not used, a stale snapshot
  already in flight could settle after the send event. A successful send could
  also be reported as unsent when only the separate saved-draft cleanup failed.
  Independently, synchronous or delayed direct-message callbacks could replace
  stronger delivery evidence with an older state or associate an old attempt's
  evidence with a newer retry.
- Version 0.2.5 queues a new snapshot after an older in-flight refresh for
  mutations and service events, including the no-timer mobile path. Direct and
  group sends refresh after the durable send, and draft-cleanup failure is
  reported without restoring the composer or inviting a duplicate submission.
  The service re-reads durable state after a native handoff, correlates callback
  evidence to the current native packet, and preserves the strongest state for
  that attempt. These changes retain the 0.2.4 non-blocking reverse-route and
  atomic one-to-one approval fixes.
- The complete automated run passed **116 Python tests** with three documented
  platform/opt-in skips, **27 renderer tests**, TypeScript checking and the
  production renderer build, and all **3 Rust tests**. Regression coverage
  includes a stale mobile refresh already in flight during the first send, a
  trailing mobile snapshot while a service event arrives during refresh,
  successful send with failed draft cleanup, synchronous endpoint/delivered
  callbacks before `send()` returns, a callback followed by a transport error,
  stale callbacks from a prior native attempt, and monotonic evidence for the
  current attempt.
- The opt-in real two-process Reticulum/LXMF direct-LAN harness passed with
  signed TCP hints in both directions. It delivered a direct message and
  application receipt before group activity, completed group invitation and
  join plus a group message, then delivered another direct message and receipt
  after the group flow. This guards the one-to-one/group boundary with the
  reference stack and no hosted relay.
- The Windows x64 executable, MSI, and NSIS package report release 0.2.5; the
  sidecar was built from service release 0.2.5. Extraction checks found that
  both installers contain a sidecar whose
  SHA-256 exactly matches the standalone release sidecar. The development
  installers are not Authenticode-signed.
- The Android arm64 debug APK reports version name 0.2.5, version code 2005,
  minimum API 24, and target API 36, and contains only `arm64-v8a` native
  libraries. APK Signature Scheme v2 verification passed with the unchanged
  development certificate SHA-256
  `D6DBFF63834666BACE3D75B49234726E97CCCE26D2B9E9516309682E0A33143F`.
  Inspection also verified that the embedded Python service contains the
  current direct-message retry, endpoint-evidence, and progress-ranking
  constants used by the 0.2.5 callback protections.
- Install 0.2.5 directly over the existing Windows and Android apps. Do not
  uninstall either app or clear its data: package identities and the Android
  signing certificate are unchanged, so existing profiles, contacts, direct
  chats, groups, drafts, and saved messages are retained. A physical
  Windows-to-Android retest using these exact 0.2.5 packages remains pending
  and is required before sensitive use.

| Artifact | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | 18,149,347 | `F905EF929DA65667E0274664ECB12A0EB79AE813366825ED2ADE712F987E60BE` |
| `mesh-chat.exe` | 4,760,064 | `01E7CA9173D77652E815BBCDA01598365694FD65ADDBA29EA4792A4139E0F500` |
| `Mesh Chat_0.2.5_x64-setup.exe` | 19,625,157 | `D5BF79342F2A3C89CCAF50C166EDF75C1BFDD0C38F744C479A6BC8BFC6A4A941` |
| `Mesh Chat_0.2.5_x64_en-US.msi` | 20,373,504 | `248E139BFA3EF4F2594E3434FCB9BF05D8C364895AB9CF5012E081DCD94110FC` |
| `mesh-chat-0.2.5-android-arm64-debug.apk` | 44,252,597 | `755F77029CE7D21EFBC74781DE56C30E0D2C973F36545C4DAD07FECF6B4FC510` |

## Recorded 0.2.6 phone-to-desktop route and mobile-send verification — 2026-10-04

- A physical Windows-to-Android run on 0.2.5 completed invitation delivery and
  explicit acceptance, but a chat submitted on the phone did not reach the
  desktop. The exact 0.2.6 Windows-to-Android package pair has not yet been
  physically retested, so the release remains gated on that run.
- The route audit reproduced a Reticulum selection condition relevant to the
  failure: an earlier equal-hop nearby-discovery announce can remain selected
  after the outbound TCP client imported from the signed invitation is online.
  This is especially important for a phone that can initiate that full-duplex
  TCP connection but does not accept an unsolicited reverse listener
  connection. Version 0.2.6 gives only explicitly configured, signed-hint TCP
  clients the minimum higher route gravity. Before a direct LXMF handoff it
  waits at most 0.75 seconds for an exact matching client and requests the
  destination only on that interface. It never raises the wildcard LAN
  listener's preference, still authenticates the destination with Reticulum's
  identity and recipient ratchet, and falls back to normal Reticulum routing if
  the signed path does not answer.
- The Android renderer no longer waits for a separate draft cleanup and
  snapshot before displaying a successful send. It immediately reconciles the
  authoritative message returned after the encrypted record is durable and
  keeps that result visible until a snapshot contains the same message ID.
  Direct and group draft persistence now coalesces rapid typing for 200 ms.
  Send cancels an unstarted stale draft save, waits for the sole active write,
  submits exactly once, and writes the empty draft last. The composer is held
  read-only while that ordered operation is active, and an Android IME
  composition Enter event cannot submit incomplete text.
- Mobile-bridge coverage verifies that the raw Android JSON boundary preserves
  both `contact_id` and `text` for `send_message`. Renderer regressions hold the
  draft-cleanup bridge call open while requiring the durable bubble to appear,
  submit three rapid input updates plus a duplicate form event while requiring
  exactly one send and one final empty-draft write, and exercise IME composition
  handling.
- The complete service suite passed **123 tests** with four expected skips: two
  opt-in direct-LAN runs, the opt-in four-peer topology, and the Windows
  `/sys`-topology limitation. The renderer suite passed **30 tests**. TypeScript
  checking, the production Vite build, and all **3 Rust release tests** passed.
- With the direct-LAN opt-in enabled, both real two-process Reticulum/LXMF tests
  passed. The original bidirectional signed-hint run retained approval, direct
  chat and receipt before and after group activity, and the intervening group
  invitation/join/message flow. The new phone-shaped run disabled the joining
  peer's listener and proved phone-to-desktop direct chat and application
  receipts over its single outbound, full-duplex signed-hint TCP client. A
  separate real-stack probe demonstrated the route transition from an earlier
  nearby path to `Private TCP peer 1` after the signed client announce.
- The Windows executable, MSI, and NSIS report version 0.2.6. Extraction checks
  found the same sidecar in both installers, with SHA-256
  `9901F7844739DABA0D0FF37B298A108C91B0305B504DE99C43AC9025D4EE4107`.
  A hidden packaged-desktop launch loaded the interface, started the live
  sidecar, and reported zero JavaScript exceptions. These development Windows
  packages are not Authenticode-signed.
- The Android arm64 debug APK reports version name 0.2.6, version code 2006,
  minimum API 24, and target API 36; contains only `arm64-v8a` native libraries;
  and passes APK Signature Scheme v2 verification with the unchanged debug
  certificate. Inspection also found the embedded signed-route preference
  markers in the packaged service.
- Install 0.2.6 directly over the existing Windows and Android apps. Do not
  uninstall either app or clear its data: package identities and the Android
  signing certificate are unchanged, so existing profiles, contacts, direct
  chats, groups, drafts, and saved messages are retained. A physical
  Windows-to-Android direct-message and group retest using these exact 0.2.6
  packages remains required before sensitive use.

| Artifact | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | 18,151,729 | `9901F7844739DABA0D0FF37B298A108C91B0305B504DE99C43AC9025D4EE4107` |
| `mesh-chat.exe` | 4,760,576 | `42A320E157B2C2743CA87127E00E8BB1E55E6C2DE8C7F80D9434307933908DCA` |
| `Mesh Chat_0.2.6_x64-setup.exe` | 19,627,219 | `FC613FCB06121172391E92DD7A95BFE7E92E3B60391BD82673A61D22BB79EE43` |
| `Mesh Chat_0.2.6_x64_en-US.msi` | 20,377,600 | `B70F6F5C268D44D9757D429743AF482DE52A129B336C3298E10454F9B7B0447D` |
| `mesh-chat-0.2.6-android-arm64-debug.apk` | 44,252,593 | `C67159232A3F45628F039E97E67914A47487C36BFE6B0ABB0C18EF4DD0441D44` |

## Recorded 0.2.7 desktop-reply concurrency verification — 2026-10-04

- A physical Windows-to-Android run using 0.2.6 successfully delivered the
  phone's first direct message to the desktop. After the desktop user entered a
  reply, the desktop reported **Something went wrong** and the reply did not
  appear on the phone. This is evidence about the 0.2.6 failure only: the exact
  0.2.7 Windows installer and Android APK have not yet been physically tested.
- A later attempted retest also ran 0.2.6, despite occurring after the 0.2.7
  package build. Process inspection proved that Windows was still running the
  raw workspace `src-tauri\target\release\mesh-chat.exe` with file/product
  version 0.2.6 and SHA-256 `42A320E1...`, plus its sibling 0.2.6 sidecar with
  SHA-256 `9901F784...`. Those are the exact recorded 0.2.6 hashes. No installed
  Mesh Chat entry or 0.2.7 program directory existed. The generic **Something
  went wrong** wording also belongs to the 0.2.6 renderer; 0.2.7 reports
  timeout/busy/stopped errors distinctly. This retest therefore reproduced the
  known 0.2.6 failure and is not evidence of a 0.2.7 send failure.
- Content-free runtime metadata showed that the phone's inbound chat and the
  desktop's application receipt were committed, but no outbound desktop chat
  record was created for the failed reply. The service processes remained
  alive while command processing stopped. Code tracing identified a lock
  inversion: LXMF can invoke a native delivery/failure or inbound callback
  while retaining its outbound-processing lock; the callback could wait for
  Mesh Chat's global dispatch lock while the background retry worker held the
  dispatch lock and waited for LXMF. Repeating the bounded signed-route wait
  for a historical backlog also allowed that retry cycle to monopolize the
  command lock beyond the desktop IPC deadline.
- The 0.2.7 network adapter places verified inbound and native status callbacks
  on one bounded dispatcher before they re-enter the service, allowing LXMF/RNS
  to release upstream locks first without waiting for service work or queue
  capacity. Inbound work is prioritized, status transitions retain their order,
  and explicit saturation behavior prevents unbounded memory growth. The durable
  retry loop locks one queued record
  at a time and yields between records, so an interactive renderer command or
  deferred callback can run between historical retries. The transport and
  cryptographic path remain Reticulum/LXMF; this is a concurrency and
  scheduling change, not a fallback protocol.
- The encrypted idempotency journal now retains at most 512 recent mutation
  responses for eight days and prunes pre-existing excess rows when a profile
  opens. Read-only `snapshot`, `search`, and `connection_help` commands are no
  longer journaled. Mutation retries retain their stable command-response
  behavior.
- Desktop timeout, busy, and stopped-service failures now have distinct
  guidance, while the direct-message composer keeps the exact text and tells
  the user to check the conversation before sending again. This avoids implying
  that a timed-out request definitely failed before its durable commit. The
  generic fallback remains for unrelated errors.
- Regression coverage includes native failure and inbound callbacks that must
  return without waiting for a simulated service lock, a historical two-record
  outbox that must yield to an interactive command between records, command
  cache cap and upgrade pruning, and renderer checks for the three actionable
  service errors with exact draft preservation. The phone-shaped real-stack
  harness now performs the reported order: phone-to-desktop chat and receipt
  first, followed by a desktop reply over the same outbound-client/no-listener
  connection; it verifies command IDs, logical message IDs, receipt state, and
  message text in both directions.
- The complete service suite passed **148 tests** with five expected skips: the
  two opt-in direct-LAN configurations, the opt-in exact-packaged-sidecar flow,
  the opt-in four-peer topology, and the Windows `/sys` topology limitation.
  The callback-dispatch suite includes
  exact lock inversion, saturation, delivery-then-failure ordering, bounded
  shutdown, and deferred exact-once vault closure. Python bytecode compilation
  passed. The renderer suite passed **33 tests**, TypeScript checking and the
  production Vite build passed, and all **3 Rust release tests** passed.
- With the direct-LAN opt-in enabled, both real two-process Reticulum/LXMF tests
  passed. The phone-shaped run sent from the outbound-only phone first, received
  its application receipt, then delivered the desktop reply over that same
  full-duplex signed route and received the return application receipt. Both
  framed service commands completed inside the production 20-second desktop
  deadline. The bidirectional-hint run still completed direct chat before and
  after group invitation, join, and group-message activity.
- A new release-only regression launched **two exact frozen 0.2.7 sidecar
  binaries** with separate EFS-protected profiles and communicated exclusively
  through production framed IPC. It completed invitation, approval,
  phone-to-desktop chat and application receipt, then desktop-to-phone reply and
  return application receipt; both send commands completed inside the 20-second
  desktop deadline, both logical message IDs were preserved, shutdown was
  clean, and stderr remained content-free. This closes the gap where the earlier
  real-stack test exercised source services but not the distributed binary.
- Desktop publishing now resolves the actual Cargo target directory, rejects
  inconsistent source versions, a stale executable version, a mismatched
  sidecar, missing version-matched MSI/NSIS files, unsafe target identifiers,
  same-version byte replacement, and post-publication tampering. It publishes
  the executable, sibling sidecar, and installers transactionally to
  `dist/desktop/releases/0.2.7/x86_64-pc-windows-msvc` and atomically updates
  `dist/desktop/current.json`. Seven focused release tests passed. The live raw
  0.2.6 developer output was deliberately left untouched while its process and
  possible draft remained open.
- Version metadata is 0.2.7 in the web package, Python service, Rust package,
  Tauri configuration, Cargo lock entry, renderer expectation, Windows bundle,
  and Android package. The packaged Windows sidecar passed EFS-protected profile
  initialization, signed invitation creation with a direct-LAN hint, graceful
  shutdown, and stderr-redaction checks. MSI and NSIS extraction found the exact
  same sidecar bytes as the standalone build, and both bundled desktop
  executables report file/product version 0.2.7. These development Windows
  packages are not Authenticode-signed.
- The Android arm64 debug APK reports version name 0.2.7, version code 2007,
  minimum API 24, and target/compile API 36; contains only `arm64-v8a` native
  code; and passes APK Signature Scheme v2 verification with the unchanged
  development certificate SHA-256
  `D6DBFF63834666BACE3D75B49234726E97CCCE26D2B9E9516309682E0A33143F`.
  Embedded-package inspection found the callback queue, deferred-close,
  bounded-journal, and signed-route markers in the packaged service bytecode.
- Install 0.2.7 directly over the existing Windows and Android apps. Do not
  uninstall either app or clear its data: package identities and the Android
  signing certificate are unchanged, so existing profiles, contacts, direct
  chats, groups, drafts, and saved messages are retained. The packaged desktop
  UI launch was not repeated while the affected 0.2.6 process remained open,
  deliberately preserving the user's unsent draft; installer extraction,
  version inspection, sidecar smoke testing, and automated UI/service tests
  passed. A physical Windows-to-Android reply retest using these exact 0.2.7
  packages remains required before sensitive use.

| Artifact | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | 18,156,375 | `2A974B58ECAB92FCDB703747AE92F2126FF39FCB8536F3CA620E9C0ED654FE6F` |
| Immutable release `mesh-chat.exe` | 4,760,576 | `B437EA0FBEFC145BF286D3AB9138C14F856C3202261ACAABE7A38E3377527AB4` |
| MSI payload `mesh-chat.exe` | 4,760,576 | `CD063F479087BE43E88C4DE10E78994040CD3CD3E1DC074F0B3F2B2EF1C2B6C3` |
| NSIS payload `mesh-chat.exe` | 4,760,576 | `9C75DD37D5B3320FBBEA183780414E1A331D865667A3523D3AFEFE42BEA04630` |
| `Mesh Chat_0.2.7_x64_en-US.msi` | 20,381,696 | `DABD29E59AA29C10C01F6294DAFE07BF7AE0793AE8CBF1F1AFE579EF6929229D` |
| `Mesh Chat_0.2.7_x64-setup.exe` | 19,633,234 | `7B5C2297AC9C20B43584FD21045476FE25D37C46B0759EE41A00022F2AC41179` |
| `mesh-chat-0.2.7-android-arm64-debug.apk` | 44,252,597 | `663D46518E861E89E0939A26E2FC91D0C1C1E0993F8A3F6DF16CC82B29FF859F` |

## 0.2.8 responsive UI and conversation-management verification — 2026-10-04

- Source metadata is set to 0.2.8 across the web package, Python service, Rust
  package, Tauri configuration, Cargo lock entry, renderer expectation, and
  desktop release-publisher expectation.
- The 0.2.8 verification scope covers Android system-bar-safe sizing and native
  Back navigation, independently scrollable conversation lists, local direct
  and group conversation deletion/restore, and the responsive desktop layout at
  its supported minimum window size. The existing one-to-one and group suites
  remain release gates so these UI and local-record changes cannot regress
  message delivery or membership behavior.
- The final automated run passed **170 Python tests** with five documented
  opt-in/platform skips, **43 renderer tests**, TypeScript compilation, Python
  bytecode compilation, the production Vite build, and all **4 Rust bridge
  tests**. The two signed direct-LAN scenarios and the real three-hop topology
  harness passed separately. The phone-shaped LAN case exposes no reverse
  listener and verifies phone-first delivery followed by a desktop reply over
  the same full-duplex route.
- Conversation-deletion coverage includes direct and group history, drafts,
  queued chat payloads, exact command-ID replay, fresh-inbound reopening,
  send/unhide transaction failure, native LXMF cancellation, trust and signed
  membership preservation, malformed commands, and failed BEGIN/COMMIT vault
  transactions. The exact frozen Windows sidecar also passed an EFS-protected
  two-peer run covering phone-first delivery, desktop reply, local deletion,
  retained contact trust, draft/history removal, fresh-inbound reopening,
  application receipts, and clean shutdown.
- The immutable Windows x64 release contains a 0.2.8 executable and the freshly
  built matching sidecar. Both the NSIS and MSI were extracted: each payload
  reports FileVersion and ProductVersion 0.2.8 and contains the same sidecar
  SHA-256 as the immutable release. The portable ZIP was expanded and its two
  executable hashes were rechecked.
- The Android arm64 APK reports package `com.meshchat.mobile`, version name
  0.2.8, version code 2008, minimum API 24, target/compile API 36, and only the
  `arm64-v8a` native architecture. `apksigner` verifies APK Signature Scheme v2.
  Its certificate SHA-256 is unchanged from 0.2.7:
  `D6DBFF63834666BACE3D75B49234726E97CCCE26D2B9E9516309682E0A33143F`,
  so an in-place upgrade preserves the installed app identity and data.
- Physical Android and Windows checks are pending. They must include portrait
  and landscape sizing, modal/conversation/root Back behavior, a long scrolling
  list, direct and group deletion plus search-based restoration, small desktop
  windows, and bidirectional direct messaging with the exact 0.2.8 packages.

| Artifact | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | 18,163,361 | `2D6B89A23721778EC04DC5873FB18F4D783BF11B68516370BAA6FDE1FC6679A3` |
| Immutable release `mesh-chat.exe` | 4,763,136 | `D6A87789BE4738295A04EBD2C5CA6C1487A5F43CE149DC650FB276BF3C722091` |
| MSI payload `mesh-chat.exe` | 4,763,136 | `48F768BF6BCDBC6ABA0D8D2C7CF8C1B629438B7B4F48B69766057623A124AEF4` |
| NSIS payload `mesh-chat.exe` | 4,763,136 | `2A93FE66FD29F8940EEAACF95074DA4BB154F168F81DF1F6720D6C6B4639ABCE` |
| `Mesh Chat_0.2.8_x64_en-US.msi` | 20,389,888 | `D9E963264FCAE92DADDC4643038AC99B1DC7F2DD93B0393B6A685D2D33F97388` |
| `Mesh Chat_0.2.8_x64-setup.exe` | 19,642,155 | `C9401D5250EFC709DE29572BE65695D8054FECF80B464D1D1C8AA09AB62306DA` |
| `mesh-chat-0.2.8-windows-x64-portable.zip` | 20,141,161 | `C475956801516B3764B740BBDEE3F22801DF58D8043D0F551DD20E8C5DC9B875` |
| `mesh-chat-0.2.8-android-arm64-debug.apk` | 44,268,965 | `7977CC17810AFCC8AE77A652D7D4E878226C7F05F2A46FCDC3681ACD2EC0C56D` |

## 0.2.9 encrypted emoji reactions verification — 2026-10-05

- Source metadata is set to 0.2.9 across the web package, Python service, Rust
  package, Tauri configuration, Cargo lock entry, renderer expectation, and
  desktop release-publisher expectation. Android uses version name 0.2.9 and
  version code 2009.
- The reaction extension supports exactly ðŸ‘, â¤ï¸, ðŸ˜‚, ðŸ˜®, ðŸ˜¢, and ðŸŽ‰ in direct
  chats, private groups, and announcement channels. Each actor has at most one
  active reaction per message. Choosing another emoji replaces it; choosing the
  current emoji again removes it. Active announcement-channel readers may
  react even though only the owner may post messages.
- Reaction state, retries, and inactive tombstones are stored in authenticated
  encrypted records. Network updates remain authenticated, individually
  encrypted Reticulum/LXMF traffic; the extension adds no hosted service or
  fallback protocol. The native source determines the actor, and group updates
  require both current active membership and entitlement to the target
  message's historical membership manifest.
- The complete Python suite passed **205 tests** with **5 documented skips**.
  An independent focused reaction/deletion audit passed **86 tests** with **2
  documented skips**. Python bytecode compilation also passed.
- The renderer suite passed **47 tests**, including keyboard-accessible picker
  behavior, replacement/removal, direct/group/channel permissions, Android
  Back handling, and a 320Ã—480 clipping regression. TypeScript checking and the
  production Vite build passed.
- All **4 Rust release tests** passed. Both opt-in signed direct-LAN scenarios
  passed (**2 tests**), and the opt-in real three-hop topology passed (**1
  test**).
- Delivery of a reaction is best effort after authenticated endpoint evidence.
  An old peer, crash, overload, or group-manifest ordering race may therefore
  cause a reaction update to be missed without weakening ordinary message
  delivery. A malicious same-actor, same-revision equivocation is
  first-seen-wins; a later higher revision restores convergence.
- The exact frozen 0.2.9 Windows sidecar passed the EFS-protected two-peer
  packaged harness (**2 tests passed**). Through production framed IPC and the
  native network path it completed bidirectional chat and receipts, phone ðŸ‘
  add, desktop ðŸ˜‚ add, desktop replacement with â¤ï¸, phone removal, convergence
  after every update, local deletion/reopen, content-free stderr, and clean
  shutdown.
- The immutable Windows executable, sidecar, MSI, NSIS, and portable ZIP were
  inspected and hashed. The immutable, MSI-payload, and NSIS-payload
  executables all report file/product version 0.2.9. Both installers contain
  the exact immutable sidecar bytes. The bundle-specific executable hashes
  differ because Tauri patches bundle-type metadata. The development
  executable and installers are not Authenticode-signed.
- The clean Android APK reports package `com.meshchat.mobile`, version name
  0.2.9, version code 2009, compile/target API 36, minimum API 24, and only
  `arm64-v8a` native code. APK Signature Scheme v2 verification passed with the
  existing debug certificate SHA-256
  `D6DBFF63834666BACE3D75B49234726E97CCCE26D2B9E9516309682E0A33143F`.
  Inspection of its Chaquopy `app.imy` found the new `mesh_chat/reactions.pyc`,
  the `set_message_reaction` command allowlist/dispatch, group-reaction code,
  and reaction snapshot aggregation.
- **Pending — physical devices:** test the exact 0.2.9 Windows and Android
  packages in both directions for direct, group, and announcement-channel
  reaction add/replace/remove, compact counts, picker placement, Back behavior,
  offline recovery, and continued ordinary chat with an older peer. A signed
  iOS package and physical iOS test still require macOS/Xcode.

| 0.2.9 artifact | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | 18,182,181 | `34E0A2B7DF8BAD5503EA8D0F40AD73DAB16EDA3A255875A726426FAE3EF891A6` |
| Immutable release `mesh-chat.exe` | 4,766,720 | `3A8C69CF8762560EB9364E0146260C91E481F3DFACC39708A90AC9703701BCA7` |
| MSI payload `mesh-chat.exe` | 4,766,720 | `65C4388B7D39B786C5CE695223FAA6709EB4654C410D5BCD4F8DC73E59C1AB02` |
| NSIS payload `mesh-chat.exe` | 4,766,720 | `4F6516D48C4FE8F08C250A57E9DBA710F3B4CDB8AEB72379CD40D4C3BE9BFCD2` |
| `Mesh Chat_0.2.9_x64_en-US.msi` | 20,414,464 | `B5F97E3DDA5A5F45BCACA7821EE03946145A1EB8221D508E322DD1F8020204CD` |
| `Mesh Chat_0.2.9_x64-setup.exe` | 19,663,792 | `1AB486BCFE9BDC5C44A27C6795219A4D4DF15D4849B0AE17659DE03A65E81443` |
| `mesh-chat-0.2.9-windows-x64-portable.zip` | 20,164,196 | `79E9B343EE094FB4A42E67EE845EDAA0A1DA6564B79E3650A23590A920CC4017` |
| `mesh-chat-0.2.9-android-arm64-debug.apk` | 44,318,285 | `6BFE002A17A9EB4F6A098ABCD144F5D60C0072AF358089A808911B3D29171A83` |

## 0.2.10 expanded Unicode emoji reactions verification — 2026-10-05

- Source metadata is set to 0.2.10 across the web package, Python service,
  Rust package, Tauri configuration, Cargo lock entry, renderer expectation,
  and desktop release-publisher expectation. The Android package reports
  version name 0.2.10 and version code 2010.
- The six familiar quick reactions remain one click away. **More emojis** opens
  eight searchable categories with 253 unique common choices, and **Use emoji
  keyboard** accepts any official fully-qualified Unicode Emoji 18.0 sequence.
  The picker is viewport-clamped and independently scrollable, including with
  the Android keyboard open, and Android Back closes the nested catalog before
  the reaction picker and conversation.
- The renderer and service carry the same exact 3,963-entry catalog in official
  source order. Independent comparison against Unicode's Emoji 18.0
  `emoji-test.txt` found zero missing and zero extra entries. The source SHA-256
  is `8F3735CDA1F92A779D78AF67CF86066BB1F07143DC22F2AC29394D9BC57AB21A`;
  the newline-joined catalog SHA-256 is
  `D4F4B496CF4A6F621575353540A4F778F3461535AEEBB62DE408369BD40608F9`.
  Exact membership, a 16-codepoint limit, and a 64-byte UTF-8 limit reject
  component-only, unqualified, minimally-qualified, text-presentation,
  adjacent-emoji, redundant-selector, invented joiner, and invented tag
  sequences instead of normalizing or repairing them.
- Direct, private-group, and announcement-channel authorization and encryption
  are unchanged. Reactions still use authenticated, individually encrypted
  Reticulum/LXMF traffic and encrypted local state; there is no hosted reaction
  service or fallback protocol. Snapshot aggregation now counts arbitrary
  supported emoji deterministically while keeping legacy quick reactions first.
- The complete Python suite passed **258 tests** with **6 documented skips**,
  and Python bytecode compilation passed. Coverage includes command, protocol,
  storage, pending/replay, direct, group, announcement, replacement/removal,
  invalid-catalog, and dynamic snapshot cases.
- The renderer suite passed **55 tests** across four files. It iterates every
  one of the 3,963 valid entries, checks the generated-catalog fingerprint,
  rejects adversarial near-matches, and covers search, categories, custom
  entry, focus/keyboard behavior, Android Back, and compact mobile layouts.
  TypeScript checking and the production Vite build passed with 1,817 modules.
- All **4 Rust release tests** passed. The two opt-in signed direct-LAN
  scenarios passed (**2 tests**), and the opt-in real three-hop topology passed
  (**1 test**).
- The exact frozen 0.2.10 Windows sidecar passed the EFS-protected packaged
  two-peer harness (**2 tests passed**). Through production framed IPC and the
  native network path it completed phone-first and desktop-reply chat plus
  application receipts; a multi-code-point ðŸ‘©ðŸ½â€ðŸŒ¾ reaction; desktop ðŸ˜‚ add and
  replacement with â¤ï¸; removal and convergence; local deletion/reopen;
  content-free stderr; and clean shutdown.
- The frozen 0.2.10 sidecar also passed the EFS-protected mixed-version harness
  against the exact 0.2.9 sidecar (**3 packaged tests passed** when run together).
  Ordinary chat remained bidirectional before and after reaction traffic, the
  original six reactions interoperated in both directions, 0.2.9 safely ignored
  an expanded ðŸ‘©ðŸ½â€ðŸŒ¾ reaction, and both peers stayed alive and shut down
  cleanly without private stderr output.
- The immutable Windows application, sidecar, MSI, NSIS, and portable ZIP were
  published and hashed. The application and NSIS executable report file and
  product version 0.2.10; the MSI file table reports application version
  0.2.10.0. The immutable sidecar equals the freshly built external binary.
  The release, MSI, and portable ZIP contain the 2,401-byte Unicode notice.
  The Windows development artifacts are not Authenticode-signed.
- The Android APK reports package `com.meshchat.mobile`, version name 0.2.10,
  version code 2010, compile/target API 36, minimum API 24, and only
  `arm64-v8a` native code. APK Signature Scheme v2 verifies with the unchanged
  debug-certificate SHA-256
  `D6DBFF63834666BACE3D75B49234726E97CCCE26D2B9E9516309682E0A33143F`.
  Its Chaquopy archive contains the exact Emoji 18 validator, dynamic reaction
  aggregation, and command path. Its native library is from the fresh Android
  web/Rust build, and the APK embeds `assets/THIRD_PARTY_NOTICES.md`.
- Compatibility is additive: 0.2.9 peers continue exchanging the original six
  reactions but ignore other Emoji 18 choices; earlier peers ignore reactions;
  ordinary chat continues. Install 0.2.10 on every participating device for
  the expanded set.
- **Pending — physical devices:** test the exact 0.2.10 Windows and Android
  packages in both directions for catalog/search/custom entry, direct, group,
  and announcement reaction add/replace/remove, compact counts, picker
  placement, nested Back behavior, offline recovery, and 0.2.9 compatibility.
  A signed iOS package and physical iOS test still require macOS/Xcode.

| 0.2.10 artifact | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | 18,199,655 | `DEBC7A9704978794BD4B2D383AC959AD94BDD4BBB1909D6A28006B5DF9310EBB` |
| Immutable release `mesh-chat.exe` | 4,778,496 | `8677B02B191E2BADDA909F6FACE76A6BC8B8E8B5A100139A00B83A04873842C7` |
| `Mesh Chat_0.2.10_x64_en-US.msi` | 20,443,136 | `BF6CD5FE81840BCD08A433A8D651D33E1A5B04898941A64F4FD3E0C4C1BE8986` |
| `Mesh Chat_0.2.10_x64-setup.exe` | 19,695,613 | `6B39A87B69167E0C0059AF64FF1AE5E4B340E8EC9AC8D682B1FD5D6ED705ACD3` |
| `mesh-chat-0.2.10-windows-x64-portable.zip` | 20,208,096 | `F41157EE015C486E7036F7DE9E496723D3D1DBB5A60D95714D8B3D265176CA45` |
| `mesh-chat-0.2.10-android-arm64-debug.apk` | 44,368,811 | `8C20E7297D22F1ABB0818A0782590C5DC7C59F36C63A08060A8D11BC4C506B44` |
| `THIRD_PARTY_NOTICES.md` | 2,401 | `987A3B010A0ECB5FFA13D3F4504E5D0F1251895A8C4172E1A91ED0626B520DF8` |

## 0.2.11 bundled offline emoji artwork verification — 2026-10-05

- Source metadata is set to 0.2.11 across the web package, Python service,
  Rust package, Tauri configuration, Cargo lock entry, renderer expectation,
  and desktop release-publisher expectation. The Android release target uses
  version name 0.2.11 and version code 2011.
- Reaction identity and compatibility are unchanged from 0.2.10: the exact
  fully-qualified Unicode Emoji 18.0 sequence remains the value validated,
  counted, encrypted in the vault, and transported through Reticulum/LXMF.
  No artwork path, sprite coordinate, or vendor identifier enters protocol or
  persistent reaction state.
- The renderer now uses local palette-optimized sprite sheets derived from
  Twemoji 17.0.3 at pinned commit
  `b6b55fef1e8636b540a6d016a4729ca8cdf2e60b`. One 16Ã—16 curated sheet covers
  all **253 of 253** picker choices. Eight 32Ã—16 general sheets cover another
  3,691 sequences, for **3,944 of 3,963** fully-qualified Emoji 18 sequences
  with bundled pictorial artwork.
- The remaining 19 sequences are new Emoji 18 entries not present in that
  pinned Twemoji release. Each has a generated catalog name and deterministically
  renders as a neutral tile marked **18**. Loading, local-image failure, and
  forced-colors behavior retain a neutral fallback rather than exposing a tofu
  glyph. The fallback does not alter or collapse the underlying Unicode value.
- All artwork URLs produced by the generated lookup are app-local. No Twemoji
  CDN, font download, analytics request, or other artwork network path is used.
  Settings displays **Emoji artwork: Twemoji (CC BY 4.0)**. The source tree
  includes `ATTRIBUTION.txt`, the complete graphics license, pinned source
  metadata, and the Twemoji section in `THIRD_PARTY_NOTICES.md`.
- The frontend suite passed **64 tests across 6 files**. It covers all 253
  picker mappings; the exact 3,944-artwork/19-fallback partition across all
  3,963 accepted sequences; local-only URLs and sprite bounds; source/version
  pins; deterministic loading, missing, error, and accessible-name fallbacks;
  reaction-chip fallback labeling; and the Settings attribution. TypeScript
  checking and the production Vite build also passed.
- The package-artwork verifier passed **3 tests**. It rejects missing logical
  asset paths, matches Brotli-decoded package bytes to the source assets, and
  can verify a final stripped native binary without retaining its Cargo build
  directory.
- The Python service suite passed **261 tests** with **6 documented skips**.
  Its artwork tests independently verify the manifest, the expected 1+8 PNG
  set, every recorded file size and SHA-256, sprite dimensions, generated
  metadata fingerprint, attribution, and third-party notice. The service and
  protocol tests continue to cover all 3,963 Unicode reaction values and do not
  treat artwork coverage as a transport allowlist.
- All **4 Rust release library tests** passed with the serialized release test
  command. The exact frozen 0.2.11 Windows sidecar then passed the
  EFS-protected package harness against itself and the mixed-version harness
  against the exact 0.2.9 sidecar (**3 packaged tests passed**). Phone-first
  delivery, the desktop reply, application receipts, reaction add/replace/
  remove convergence, deletion/reopen, legacy expanded-reaction handling,
  content-free stderr, and clean shutdown all passed through production IPC.
- The Windows x64 application, sidecar, MSI, NSIS installer, and portable ZIP
  were built and published under the immutable 0.2.11 release directory. The
  release manifest and `current.json` hashes validate; raw, MSI, NSIS, and
  portable application payloads report file/product version 0.2.11; their
  sidecars and notices match the immutable files. The packages are development
  builds and are not Authenticode-signed.
- The package-artwork verifier decoded and matched all **12** local artwork
  files (**1,947,195 source bytes**) in the immutable Windows executable and
  the application extracted independently from the MSI, NSIS installer, and
  portable ZIP. Those files are the nine sprite sheets plus the integrity
  manifest, attribution, and full graphics license. Source and production
  renderer inspection found no Twemoji CDN or other remote artwork reference.
- The Android arm64 APK reports package `com.meshchat.mobile`, version name
  0.2.11, version code 2011, compile/target API 36, minimum API 24, and only
  `arm64-v8a` native code. APK Signature Scheme v2 verifies with the unchanged
  debug-certificate SHA-256
  `D6DBFF63834666BACE3D75B49234726E97CCCE26D2B9E9516309682E0A33143F`.
  Its packaged notice exactly matches the source notice. The verifier decoded
  and matched all 12 artwork files directly from the stripped native library
  extracted from the exact APK; that library is 14,258,592 bytes with SHA-256
  `0FB9B99AECB1E61C3D4848704D5F41793B5D7BA79A22AAFC5601F2EC55A7687B`.
- **Pending — physical devices:** test the exact 0.2.11 Windows and Android
  packages for quick-picker, searchable catalog, reaction-chip, 19-entry
  fallback, loading/error, compact layout, forced-colors where available, and
  direct/group/announcement add-replace-remove flows in both directions. The
  signed iOS build and physical iOS rendering test still require macOS/Xcode.

| 0.2.11 artifact | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | 18,199,967 | `2322827C7A0EB9602A92E6C8516B1CDCCC4AFE8B8F8FD5FDA827506C41640C64` |
| Immutable release `mesh-chat.exe` | 6,702,080 | `6DC69994FE4AEDB7A4C2DE0C0F8A7B0E620CE5D3BF3C2C16C0C420CD366C8AB3` |
| `Mesh Chat_0.2.11_x64_en-US.msi` | 22,364,160 | `D7396792D706CAF799C93EE9D6ADC191A9B37732847172DCF7D8A66F6AA820BD` |
| `Mesh Chat_0.2.11_x64-setup.exe` | 21,626,898 | `00C084262B106C81F5D645F32C5B578887D8E0286C34CAA09BEF34F8026C67CD` |
| `mesh-chat-0.2.11-windows-x64-portable.zip` | 22,127,373 | `0B96FEF68D887AAA0F7E1717BB54697AFD3B9D30F9570864AAE52E1169882337` |
| `mesh-chat-0.2.11-android-arm64-debug.apk` | 46,300,720 | `59B0DC9D6C516AED846E72C908C400C0571FB014E8AC0F55E438FE947C08DC75` |
| Packaged `THIRD_PARTY_NOTICES.md` | 3,239 | `D663E6E7B26D12B33F5042B7C9F413BA57CABF331A6D0B0C37693F2B3D125D44` |

## 0.2.12 contact management verification — 2026-10-06

- Source metadata is set to 0.2.12 across the web package, Python service,
  Rust package, Tauri configuration, Cargo lock entry, renderer expectation,
  desktop release-publisher expectation, and generated Android metadata.
  Android uses version name 0.2.12 and version code 2012.
- The shared responsive Contacts dialog searches saved contacts and supports
  local rename, mark/remove verification, block/unblock, open conversation,
  and confirmed contact deletion. Desktop and mobile use the same React bundle;
  the mobile Back path closes the dialog before leaving the app.
- Service commands cover update, verify/unverify, block/unblock, and delete.
  Deletion removes the direct conversation, messages, drafts, receipts, and
  contact record atomically, retains group identity/membership, and refuses a
  contact still referenced by a pending group invitation. Blocking preserves
  the preceding trust state so unblocking restores it.
- The complete frontend suite passed: 6 files and 66 tests. The complete
  service suite passed: 265 tests, with 6 environment-gated tests skipped.
  This includes the dedicated contact-management service tests and Contacts UI
  interaction coverage.
- Windows x64 release packaging produced and immutably published the EXE,
  sidecar, MSI, and NSIS installer at
  `dist/desktop/releases/0.2.12/x86_64-pc-windows-msvc`. The release manifest
  hash is
  `787E9DA2E44364DA1FE827590E8379A89A93D90417C8DC26D930EAA957D5783F`.
  The NSIS update installed successfully over 0.2.11 without clearing the
  profile; the installed executable reports product version 0.2.12 and was
  launched from `%LOCALAPPDATA%\Mesh Chat`. The stale Start-menu shortcut was
  corrected to that installation.
- The Android arm64 debug APK reports package `com.meshchat.mobile`, version
  name 0.2.12, version code 2012, minimum API 24, target/compile API 36, and only
  `arm64-v8a` native code. APK Signature Scheme v2 verifies with the unchanged
  debug-certificate SHA-256
  `D6DBFF63834666BACE3D75B49234726E97CCCE26D2B9E9516309682E0A33143F`,
  so it can upgrade the prior debug build in place. The stripped native library
  is 14,266,024 bytes with SHA-256
  `C73777847ED3C485ADA9ADDD0CDB660D5906807C1CADE1BFFDE8C6BA141D62BA`.
- Package inspection matched the exact compressed JavaScript asset containing
  `Search contacts`, `Delete contact`, and `0.2.12` inside the APK native
  library. The artwork verifier also decoded and matched all 12 local artwork
  and notice files from that exact library. The Android helper now requests
  `--split-per-abi`, matching the arm64 artifact path it publishes and
  preventing reuse of a stale split APK.
- **Pending — physical devices:** no Android device was attached, so the exact
  APK still needs an in-place `adb install -r` and a physical Windows↔Android
  contact-management/interoperability run. The APK is debug-signed for direct
  testing; a production AAB still requires a private release keystore. macOS,
  Linux, and iOS native package validation also remain pending.

| 0.2.12 artifact | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `mesh-chat-service-x86_64-pc-windows-msvc.exe` | 18,203,625 | `D8F5457F43777D6289E3A1F80A2DAE7CDEBAB9BA4EA222E05F930E43A9D0FE00` |
| Immutable release `mesh-chat.exe` | 6,704,128 | `A4266B18A30BA5984406F95C162825B2E3A51897FAEBE0362EA5E2D0AD55DD0A` |
| `Mesh Chat_0.2.12_x64_en-US.msi` | 22,372,352 | `5081825AA72F99882671A4EA88C33C484D50C184FC2F773438737619FC72F479` |
| `Mesh Chat_0.2.12_x64-setup.exe` | 21,633,130 | `451A8DE7DDC082FD7918BDD8E3AE31954F425ED7C5EDF6038500A1C23A2056AD` |
| `mesh-chat-0.2.12-android-arm64-debug.apk` | 46,300,716 | `51D4C98F29CC601B7461B008C246D365B9FE816AE4E167927DB389528B290963` |
| Packaged `THIRD_PARTY_NOTICES.md` | 3,239 | `D663E6E7B26D12B33F5042B7C9F413BA57CABF331A6D0B0C37693F2B3D125D44` |

## Automated focused coverage

- IPC frame boundaries, concatenation, malformed JSON and truncation.
- Invitation link/text/file equivalence, signatures, destination binding, expiry, and hint validation.
- Authenticated local record round trips, plaintext scanning, wrong-key
  failure, mutation command deduplication, bounded command-journal retention,
  and upgrade-time pruning.
- Mobile bridge validation plus authenticated mobile record round trips and plaintext scanning.
- App payload rules, conversation-ID stability, and receipt constraints.
- Full deterministic two-peer one-to-one flow from invitation through approval,
  direct chat, application receipt, and delivered state, with an assertion that
  no group records are created.
- Approval regressions covering asynchronous attachment of up to eight signed
  reverse TCP routes, atomic trust/acceptance persistence, exactly one
  `CONTACT_ACCEPT`, in-flight handoff suppression, contained route/transport
  failures, dirty-route retry, and bounded signed-route preference before the
  first direct-chat handoff.
- Concurrency regressions covering deferred native status/inbound callbacks
  that cannot retain an LXMF/RNS lock while waiting on the service, plus
  per-record retry locking and a scheduling yield between queued records.
- First-message regressions covering a stale snapshot already in flight on the
  no-timer mobile path, a trailing refresh for a concurrent service event,
  durable send versus draft-cleanup failure, synchronous callback-before-return
  ordering, immediate reconciliation of the durable send result, bounded draft
  coalescing, duplicate-submit suppression, Android IME composition, callback-
  then-error handling, native-attempt correlation, and monotonic endpoint/
  delivery evidence.
- Group-document canonicalization, signature and destination binding, manifest
  membership/role limits, targeted invite/join consent, and strict group
  application-field combinations.
- Reaction coverage includes exact membership in the 3,963 fully-qualified
  Unicode Emoji 18.0 sequences, independent codepoint/byte bounds, adversarial
  near-match rejection, native-source actor binding, direct/group namespace separation, historical group-message
  entitlement, active-member and announcement-reader permissions, one-state
  replacement/removal, monotonic revisions, encrypted tombstones, bounded
  pending work, receipt compaction, restart/offline replay, old-peer rejection,
  and snapshot indexing that avoids per-message record scans.
- Offline artwork coverage verifies the pinned Twemoji source and CC BY 4.0
  attribution, every sprite sheet against its manifest size/hash/dimensions,
  all 253 curated picker choices, all 3,944 locally illustrated Emoji 18
  sequences, the complementary 19 named neutral fallbacks, local-only asset
  URLs, deterministic sprite coordinates, loading/error behavior, and Settings
  disclosure. The dedicated package verifier also matches every decoded asset
  in the final Windows and Android native binaries; physical rendering remains
  a separate release gate.
- In-process group-service flows cover targeted invitation, join acceptance,
  owner epoch advancement, recipient fan-out, inbound commit, recipient-specific
  application receipts, two simultaneous invitees with reversed epoch arrival,
  accepted-invite replay after removal, remove/leave/close, old-epoch
  equivocation freeze, restart terminal-state preservation, application-level
  retry, and strict duplicate metadata. These use recording network doubles and
  do not replace the real-network group gates above.
- Native status mapping that distinguishes propagation storage, endpoint proof, and application delivery.
- RNS profile isolation, no inherited/public interface, and independent role settings.
- UI wording distinctions for delivery and contact consent.
- Optional real two-process RNS/LXMF direct-LAN flows with signed TCP hints:
  the bidirectional route with timed approval, direct chat before and after a
  group invitation/join/message flow, and application receipts; plus a
  phone-shaped joining peer with an outbound client and no reverse listener
  that sends the first chat and then receives a desktop reply with application
  delivery confirmed in both directions.
- Optional exact-package flow using two frozen sidecars, protected profiles,
  production framed IPC, phone-first delivery, and the desktop reply inside the
  real command deadline.
- Real-stack route-preference probing in which an earlier equal-hop nearby path
  remains selected at equal gravity, then is replaced by the exact signed TCP
  client after its minimally preferred announce.
- Optional real RNS/LXMF A→B→C→D delivery using only A–B, B–C and C–D interfaces, with ratchet presence, three-hop assertion, signature validation, and intermediate persistent-file plaintext scan.

## Deterministic delivery pipeline verification — 2026-10-06

- `python scripts/release.py check --expected-version v0.2.12` passed and
  reported consistent npm, Tauri, Cargo, Cargo-lock, Python, and Android version
  metadata. It also selected Node 24.19.0 and pnpm 11.19.0 without relying on
  the host's obsolete default Node installation.
- The complete maintained verification command passed: 277 Python tests, 6
  intentionally skipped environment/device tests, 66 frontend tests, 3 package
  artwork-verifier tests, TypeScript compilation, and the production web build.
- The new version-transaction, Android immutable-publisher, and desktop
  publisher suites contributed 19 focused passing tests. They cover invalid and
  inconsistent versions, Android version-code derivation, root-only Cargo.lock
  mutation, preservation of unrelated metadata, same-version/different-byte
  rejection, manifest/current pointers, and tamper detection.
- The first sidecar run populated the content-addressed PyInstaller cache in
  about 34 seconds. The immediately repeated build verified and reused it in
  about 4 seconds instead of running PyInstaller again.
- The initial Vite production bundle completed in 4.86 seconds. The immediately
  repeated build reused its input digest and completed in under one second.
- The existing 0.2.12 Android APK was adopted into the new immutable layout at
  `dist/mobile/releases/0.2.12/android-arm64-debug`; its versioned manifest,
  checksum, current pointer, and documented top-level alias all verified.
- The generated Android Gradle launcher no longer contains a developer-specific
  absolute Node path. Repeated generated-project preparation produced the same
  native input digest, confirming that unchanged files are not rewritten.
- CI and tag/manual release workflows are present and use the same repository
  release driver. The release job tests once, then packages desktop and Android
  concurrently with pnpm, pip, Rust, Gradle, SDK, and NDK caches. They have not
  run remotely because this workspace currently has no commit history or Git
  remote; that remains an external activation prerequisite rather than an LLM
  build step.

## Workspace increment 2 verification — 2026-10-07

- The complete Python suite passed with **290 tests passed and 6 intentional
  environment/device skips**. Thirteen focused workspace tests cover deterministic
  canonical fixtures, tamper and noncanonical rejection, profile isolation,
  verified unknown-source join admission, two-service join and chat, reversed
  control arrival, bounded paging, stale cursors, receipt aggregation without
  delivery scans, operation replay, genesis/checkpoint authority pinning,
  active-source admission, fork resistance, scoped join decisions, actionable
  sync state, close invalidation, and destructive local-data redaction. The
  increment-two topology test admits seven people from concurrent invitations
  referencing the same checkpoint, proves ordered catch-up to all eight
  replicas, propagates metadata and approved display-name changes, returns a
  signed name-request decline, removes one member, materializes a cancelled
  delivery leg, and delivers a member-authored event to the remaining peers
  while the owner process is offline. The sender then restarts with its
  committed event and frozen delivery legs intact, and the restarted owner
  receives the withheld canonical event after reconnect.
- The six frontend source suites passed with **76 tests**, including the
  disclosure-first workspace create flow, bounded message loading, attachment
  button/drop/paste rejection, paused-state action gating, close confirmation,
  scoped invalidation, and stable retry event and operation IDs. The workspace
  refresh regression test verifies that desktop polling and draft invalidations
  do not reload the open `#general` page, while message invalidations update it
  in the background without clearing visible messages. TypeScript project
  compilation and the Vite production build also passed. Increment-two UI
  coverage verifies independent invitation revocation/creation, owner removal
  and display-name decisions, member name requests, opt-in propagation-node
  consent, per-person/per-device delivery disclosure, and replacement of a
  removed member when eight historical member records remain.
- The Rust library suite passed with **6 tests**, including every workspace
  renderer command, mobile workspace rejection classification, and workspace
  deep-link admission. `cargo fmt --check` passed.
- The maintained release driver built and immutably published desktop 0.2.16.
  WiX `light.exe` completed CAB creation, MSI database generation, and ICE
  validation when the build had Windows Installer access; no ICE suppression or
  alternate packaging path was used. The earlier `LGHT0217` failure was isolated
  to ICE validation being unable to access Windows Installer from a restricted
  process; CAB creation and MSI database generation had already succeeded. It
  was an execution-environment failure, not a malformed MSI source. The final
  run published a 22,478,848-byte MSI with SHA-256
  `21D590178B248A8C6D0366B527BC5403D50C315B17619714B6580E4EE329BA98`
  and a 21,739,441-byte NSIS installer with SHA-256
  `E3199396A213E46F054563A2724C6226B99D6D5EAE7E2C5DA76B5854C845052D`.
- The immutable portable `mesh-chat.exe` was launched with its sibling sidecar;
  process inspection confirmed product version 0.2.16 and both processes came
  from the 0.2.16 release directory. Windows automation found the running Mesh
  Chat window, but the capture helper failed its initial attempt and one fresh
  window retry with `0x80004002`, so this run does not claim an interactive
  native-window walkthrough. Renderer and eight-service workspace flows passed.
- Physical two-install delivery, restart at injected commit boundaries,
  partition recovery, package extraction, and protected-profile plaintext scans
  remain release gates; automated tests do not claim those device results.

## Workspace increment 3 verification — 2026-10-07

- The maintained suite passed **295 Python tests with 6 intentional
  environment/device skips**, **79 frontend tests**, all 3 package-artwork
  verifier tests, TypeScript compilation, and the Vite production build. The
  Rust release suite passed all **6 tests**, and `cargo fmt --check` passed.
- Protocol and service coverage exercises public-channel creation, browsing,
  subscription, rename/topic changes, two-party management transfer, authority
  recovery, terminal archive, active-channel capacity recovery, retained-channel
  summary paging, exact policy enforcement, unauthorized signed events, stale
  and forked controls, stable duplicate-name disambiguation, unread persistence,
  restart, partitions, reversed control/event arrival, quarantine draining, and
  eventual signed-chain fetch convergence. Existing canonical fixtures and wire
  kinds remain byte-for-byte unchanged; new kinds are additive and bounded.
- The opt-in network topology harness passed its isolated peer run, and both
  direct-LAN harness scenarios passed. The exact immutable 0.2.17 packaged
  sidecar passed the process-level phone-first/desktop-reply test under Windows
  protected storage. The full three-test packaged compatibility harness also
  passed against its intended pre-expanded-reaction 0.2.9 baseline.
- The first release attempt stopped before native packaging while pnpm rebuilt a
  partially reconciled `node_modules` tree without registry access. Restoring
  the lockfile-pinned tree resolved that environment failure. A later restricted
  run linked the application but stopped when WiX `light.exe` could not access
  Windows Installer for ICE validation. The same maintained pipeline then ran
  with Windows Installer access and completed both formats with ICE checks still
  enabled; no WiX source, validation flag, or alternate packaging path was used.
- The maintained release driver immutably published desktop **0.2.17**. The MSI
  is 22,511,616 bytes with SHA-256
  `2FF6554841148AA6EF57A803F3BE0ABCC07E43CC2BA2DB9C214BCA41190EEA33`.
  The NSIS installer is 21,775,013 bytes with SHA-256
  `30A72CEEC05FA54C8B3F1F0910EDB9239546BD30D8296214BACE1A83CD9F40B6`.
  The portable application reports product/file version 0.2.17, and the current
  pointer records manifest SHA-256
  `831CBC1AC975C042F8477B418814754B4FC101BEF1BC8554EA98CD4AC87D966D`.
  Immutable 0.2.16 artifacts remain present and were not overwritten.
- This run exercised the packaged service processes but did not stop the user's
  existing 0.2.16 single-instance desktop session, install either 0.2.17
  installer, or obtain a successful native-window capture. It therefore does
  not claim an interactive walkthrough. Production signing, physical
  multi-install discovery/delivery, real-device restart and partition recovery,
  packet capture, protected-profile plaintext scans, and Windows-to-Android
  workspace validation remain release gates.

## Workspace increment 4 verification — 2026-10-07

- The complete maintained verification passed **298 Python tests with 6
  intentional environment/package skips**, **80 frontend tests**, all 3
  package-artwork verifier tests, TypeScript compilation, and the Vite
  production build. The Rust boundary passed `cargo check`, `cargo fmt
  --check`, and all **6 release-profile tests**.
- Private-channel protocol and service coverage now exercises canonical signed
  rosters, exact private audiences, one-to-eight member bounds, creation,
  manager-only roster changes, member admission without predecessor metadata or
  message backfill, control-before-event quarantine across restart, duplicate
  and delayed delivery, unread persistence, metadata changes with delayed
  historical events, member-only transfer, owner recovery only from inside the
  roster, voluntary leave, scoped pending-leg cancellation, terminal archive,
  nonmember storage/snapshot exclusion, and a valid channel-local fork that
  leaves the workspace active. Renderer coverage creates a private channel,
  manages its signed roster, and gates leave, transfer, recovery, archive and
  read-only states.
- The opt-in isolated three-hop RNS/LXMF topology passed. Both direct-LAN
  scenarios passed: bidirectional signed hints and the phone-shaped outbound
  client with no reverse listener. The exact immutable 0.2.18 packaged sidecar
  passed the phone-first/desktop-reply harness and its current-versus-0.2.9
  compatibility flow. A restricted first attempt correctly failed closed with
  `protected_storage_unavailable`; the required native EFS run passed all 3
  packaged-harness tests.
- The maintained release driver published desktop **0.2.18** with WiX ICE
  validation and NSIS packaging enabled. The 22,528,000-byte MSI has SHA-256
  `9E180DA9581B266C2C3F0C29474F0B1E54FDB31037B65837AEEA72DA3E3749DE`.
  The 21,790,733-byte NSIS installer has SHA-256
  `95ECD02F768DCECDDDAD2B8F7C84CB76D8251247790EBB14F5D836178212E113`.
  The portable application reports file/product version 0.2.18 and hashes to
  `B074D515455A54714BDCDA6D63B99F5A8B79E6C786A0384005221B488288B263`;
  the sidecar hashes to
  `C78EA75F111939C2D4483A50512C897819EEE8FF620774347FB496F4C54DE8B7`.
  The immutable manifest hashes to
  `1B4A9A6263973BD9E1BD0FE1A9050FD710BFB4A78875FF9B2E197B3CFE6DCA45`.
- No installer was launched and no existing Mesh Chat process or profile was
  altered. Production signing, in-place installation, interactive native-window
  walkthrough, physical multi-install private-channel partition/reconnect,
  packet capture, and protected-profile plaintext scans remain release gates.

## Workspace increment 5 verification — 2026-10-08

- The complete maintained verification passed **300 Python tests with 6
  intentional environment/package skips**, **81 frontend tests**, all 3
  package-artwork verifier tests, TypeScript compilation, and the Vite
  production build. The Rust boundary passed `cargo fmt --check` and all **6
  release-profile tests**.
- Protocol and service coverage verifies the deterministic workspace-scoped
  two-member conversation UUID, null channel digest, exact sorted audience,
  author and current-participant authorization, participant-only fan-out,
  independent sealed paging/drafts/unread state, local hide and People-based
  reopen, restart persistence, bidirectional delivery, removal-driven read-only
  state, and cancellation of unhanded DM legs. Both endpoints retain empty
  global Contact lists. Renderer coverage opens from People, sends, hides,
  reopens, and confirms the Contacts view remains unchanged.
- The opt-in isolated three-hop RNS/LXMF topology and both direct-LAN scenarios
  passed. The exact immutable 0.2.20 packaged sidecar passed the
  phone-first/desktop-reply harness and the current-versus-0.2.9 compatibility
  flow under native Windows EFS; all 3 packaged-harness tests passed. The final
  application executable also matched all 12 bundled artwork, metadata, and
  license files.
- The maintained release driver immutably published desktop **0.2.20** with WiX
  ICE validation and NSIS packaging enabled. The 22,536,192-byte MSI has
  SHA-256
  `7C22F0FE9B8E4A9C78B259E8FECFFC12DEF1054604144544E28BB94527C48D00`.
  The 21,799,832-byte NSIS installer has SHA-256
  `5E5C85C39F582DE6ED32450F84ED3FBCB1EAA31249B149D69D0F7E86C9D74D95`.
  The portable application reports file/product version 0.2.20 and hashes to
  `D90D5DBB3B184F8983DBEEE46EA73D1177F1BB9B2076A0BE3DE49DB1EFAE190E`;
  the sidecar hashes to
  `184D9809CB83AF9B3E1605B0D503A14ACE3E248102F9491D6589AE19790FA148`.
  The immutable manifest hashes to
  `0850FFFAD09E8EA9EE3DDAED129DC6A8A66BA8CD8FDD1E98809C5825318DC773`.
  The earlier immutable 0.2.19 build was superseded before installation after
  the final authorization review established that channel posting policy must
  not suppress active-participant workspace DMs; 0.2.20 contains that fix.
- No installer was launched and no existing Mesh Chat process or profile was
  altered. Production signing, in-place installation, interactive native-window
  walkthrough, physical multi-install DM partition/reconnect, packet capture,
  and protected-profile plaintext scans remain release gates.

## Workspace increment 5 corrective verification — 2026-10-08

- Final review found that confirmed local workspace removal did not include the
  new sealed `workspace_direct` summary records, and that cancellation of a DM
  leg after removing its sender could relabel the remaining recipient in local
  delivery details. Version **0.2.21** deletes the DM summaries with the rest of
  the workspace, preserves the actual recipient identity in cancelled delivery
  state, rejects a delayed unseen DM after removal, and adds regressions for all
  three behaviors. The renderer also rejects pasted attachments in DMs and uses
  accurate read-only wording for workspace-wide paused states.
- The complete maintained verification passed **300 Python tests with 6
  intentional environment/package skips**, **81 frontend tests**, all 3
  package-artwork verifier tests, TypeScript compilation, and the Vite
  production build. `cargo fmt --check`, the locked Rust release check, and all
  **6 release-profile tests** passed. The opt-in protected three-hop topology
  and both direct-LAN scenarios passed, as did all **3** exact packaged-sidecar
  and 0.2.9 interoperability tests. The final application executable matched
  all **12** bundled artwork, metadata, and license files.
- The maintained release driver immutably published desktop **0.2.21** without
  changing the verified 0.2.20 release. The 22,540,288-byte MSI has SHA-256
  `F7316C13C9B7A24EA6ED0953500B4EC48711DBFE567A21F1FCE31CD623C98C40`.
  The 21,800,652-byte NSIS installer has SHA-256
  `C9B8538923FB0F04F6F5C34E099652F1195C8D8B66187197BDCA7493F5AC6569`.
  The portable application reports file/product version 0.2.21 and hashes to
  `FEFEB0253F4426288645E00D9B4B64DDC5F3827FB9EC67F81A07928D1F1E1AC0`;
  the sidecar hashes to
  `0C2FF802C4E21721D7D9624C92202416DD21BE52BE9C499871EEF30DBCD8B0DE`.
  The immutable manifest hashes to
  `2804AE21DE4860CCB6FAC90087C5CE8135B33287A8931B4430636653E5546299`.
- A first follow-up Rust check/test attempt exhausted the nearly full system
  drive while creating an additional debug tree after packaging. Only
  reproducible Cargo and PyInstaller intermediates were removed; immutable
  releases were preserved. The release tests then passed from a clean serial
  build, followed by the locked release-profile check. No installer was
  launched and no existing Mesh Chat process or profile was altered.
- Production signing, in-place installation, interactive native-window
  walkthrough, physical multi-install DM partition/reconnect, packet capture,
  and protected-profile plaintext scans remain release gates.

## Workspace increment 6 verification — 2026-10-08

- Protocol coverage preserves the exact Increment 5 message envelope and adds
  exact-field signed edit, delete, and reaction events with target UUIDs, base
  revisions, next revisions, bounded payloads, and canonical verification.
- Service coverage exercises author-only edits/deletes, durable deletion and
  inactive-reaction tombstones, multiple emojis per member, reactions under an
  owner-only posting policy, unauthorized-author rejection, deterministic
  concurrent winners, visible conflict resolution, same-device equivocation
  freeze, exact replay, reversed stream delivery, automatic pending drain, and
  encrypted restart durability. Public channels, private channels, and
  participant-only workspace DMs are all covered without creating Personal
  Contacts or extra timeline rows.
- Renderer coverage edits inline, confirms deletion, presents tombstones,
  displays conflict/security state, and uses the local Emoji 18 picker with
  independent workspace reactions. Rust and Python expose only the three named
  mutation commands.
- The complete maintained verification passed **304 Python tests with 6
  intentional environment/package skips**, **82 frontend tests**, all **3**
  package-artwork verifier tests, TypeScript compilation, and the Vite
  production build. `cargo fmt --check`, the locked Rust release check, and all
  **6 release-profile tests** passed. The protected four-process topology and
  both direct-LAN scenarios passed, as did all **3** exact 0.2.22
  packaged-sidecar and 0.2.9 interoperability tests. The final executable
  matched all **12** bundled artwork, metadata, and license files.
- The maintained release driver immutably published desktop **0.2.22** without
  changing prior releases. The 22,552,576-byte MSI has SHA-256
  `62CC4897C9A88DE826022322E873C5FAAA33CB8F9DEBD4F0AE81EC6C17DC5FA4`.
  The 21,812,216-byte NSIS installer has SHA-256
  `73FA42E3B2BCDA29CBEDAF7392F52B6BBAC08B6F5DD7E2746E401D8B0B9A8CCC`.
  The portable application reports file/product version 0.2.22 and hashes to
  `48A5914D0A580EFF26959CABBC0BA16E564E5BEC19C1A2A0BACC55DB617D92A3`;
  the sidecar hashes to
  `6B5AC3183DBC53CA632D40C78307C5D5626DFCCFCB51DC7EEC3C98EA6D1C9891`.
  The immutable manifest hashes to
  `9A1E0D6D9057B1F5476145916CAA34614BB58060F75B4A11CED08937832960B8`.
- No installer was launched and no existing Mesh Chat process or user profile
  was modified.
- Physical concurrent-device partition/reconnect, interactive native-window
  accessibility, packet capture, protected-profile plaintext scanning,
  production signing, and in-place installation remain release gates.

## Workspace increment 7 verification — 2026-10-09

- Increment 7 adds canonical structured workspace mentions to messages and
  edits. Protocol coverage verifies stable sorted member UUIDs, the eight-target
  limit, exact signed-field validation, raw `@name` text remaining inert,
  active-member authorization, private-channel and DM audience binding, and
  edit/non-edit mention semantics.
- Service coverage exercises mention delivery from unsubscribed public
  channels, private-channel visibility, edit-time add/remove/re-add behavior,
  stale-index suppression, independent encrypted paging/read state, per-channel
  mention mute, encrypted draft mention IDs, restart durability, and removal or
  local-leave filtering. Renderer coverage exercises the compose and edit
  pickers, mention chips, highlighted messages, the paged Mentions inbox,
  mark-all-read, mute controls, unread indicators, and stale-draft filtering.
- The complete maintained verification passed **306 Python tests with 6
  intentional environment/package skips**, **84 frontend tests**, all **3**
  package-artwork verifier tests, TypeScript compilation, and the Vite
  production build. `cargo fmt --check`, the locked Rust release check, and all
  **6 release-profile tests** passed. The protected four-process topology and
  both direct-LAN scenarios passed, as did all **3** exact 0.2.25
  packaged-sidecar and 0.2.9 interoperability tests. The final executable
  matched all **12** bundled artwork, metadata, and license files.
- The maintained release driver immutably published desktop **0.2.25** without
  changing prior releases. The 22,564,864-byte MSI has SHA-256
  `AFBC45AB6339BC164E9DCAA0AFA3BAF4EC153BD28B4B3D43592F33153A2E7808`.
  The 21,824,074-byte NSIS installer has SHA-256
  `C59031E1A26A046924E53AA99E21EDC3019BEC9985372C1B01A87A03DDA0C4B9`.
  The portable application reports file/product version 0.2.25 and hashes to
  `41B6F21ED568A32C05BE4D51ABDD67F979E2027A8204906852490A1262730345`;
  the sidecar hashes to
  `B4649D04C799452566DF370B0580F8F5A3723E2A35FCB33A4AA6DBE4052F2C2C`.
  The immutable manifest hashes to
  `4AF385BDAB447916E3F29ECB89F90D3A7E62FBBDC0F2C6E74430D84D634F76D9`.
  The immutable 0.2.23 and 0.2.24 builds remain preserved but were superseded
  before installation. Final review found that hiding a workspace DM did not
  suppress its otherwise inaccessible Mentions row. Version 0.2.24 corrected
  that and filtered stale draft/edit mention targets, but its startup snapshot
  still derived the mention badge by reading unread message bodies. Version
  0.2.25 persists the derived count, migrates older records once, and verifies
  that ordinary startup snapshots do not read message bodies.
- No installer was launched and no existing Mesh Chat process or user profile
  was modified. Physical concurrent-device mention partition/reconnect,
  interactive native-window accessibility, packet capture, protected-profile
  plaintext scanning, production signing, and in-place installation remain
  release gates.

## Workspace increment 8 verification — 2026-10-09

- Increment 8 activates the existing signed `thread_root` field while
  preserving the canonical bytes of ordinary messages and mutations. Protocol
  and service coverage verifies retained same-conversation roots, rejection of
  nested replies, exact public/private/DM authorization, private removal and
  re-admission gaps, participant removal, local hides, archived or left
  channels, tombstones, retention invalidation, bounded encrypted reply and
  activity indexes, independent read high-waters and drafts, and stale-cursor
  rejection.
- Delayed reply-before-root delivery, duplicated and reversed events,
  mutations, reactions, controls, restart recovery, structured reply mentions,
  deterministic conflict resolution, and thread-specific unread/read state are
  automated. Renderer coverage opens a mentioned reply directly into the
  dedicated root-context thread view, pages replies, persists the encrypted
  draft, sends a reply, marks only that thread read, and exposes the bounded
  Threads activity view. Startup regression coverage verifies that ordinary
  snapshots use persisted bounded thread summaries and authorization metadata
  without decrypting message bodies or scanning the complete event/delivery
  collections. Global Contacts and Personal/group protocol state remain
  isolated.
- The complete maintained verification passed **309 Python tests with 6
  intentional environment/package skips**, **85 frontend tests**, all **3**
  package-artwork verifier tests, TypeScript compilation, and the Vite
  production build. `cargo fmt --check` and all **6 release-profile Rust
  tests** passed. The protected four-process/three-hop topology and both
  direct-LAN scenarios passed, as did all **3** exact 0.2.28 packaged-sidecar
  and frozen 0.2.9 interoperability tests under native Windows EFS. The final
  application executable matched all **12** bundled artwork, metadata, and
  license files (1,947,195 source bytes).
- The maintained release driver immutably published desktop **0.2.28** without
  changing the preserved 0.2.23, 0.2.24, 0.2.25, 0.2.26, 0.2.27, or any
  earlier release. The
  22,581,248-byte MSI has SHA-256
  `676B0BF354F93EF131A201B40EF562C2E4A790D0926582A21A9803AC3EE15376`.
  The 21,841,451-byte NSIS installer has SHA-256
  `195E798F7076055EB2AB4B88DF9389BC79EA90E47F2AEC30AB1F71D533216E7E`.
  The 6,724,608-byte portable application reports file/product version 0.2.28
  and hashes to
  `3C9184E591563C55310ADEE78AB92852B4B7C9395CD7844A0632EA5991A5FB22`;
  the 18,393,761-byte sidecar hashes to
  `15859086925CE4D3F429491562D0C4AEFF050EBF629E9D2132B2AAC33AC13F28`.
  The 3,239-byte release notice hashes to
  `D663E6E7B26D12B33F5042B7C9F413BA57CABF331A6D0B0C37693F2B3D125D44`.
  The immutable manifest hashes to
  `411E531D96786425027E041BB612B47CC71FE73125CEC55521741AE4170AD356`,
  and `dist/desktop/current.json` selects that manifest. The successful release
  report is
  `dist/reports/0.2.28/20261010T005138Z-0d94f736/report.json`. The immutable
  0.2.26 review build was superseded before installation after final review
  found that an inbound reply or mutation signed after private-channel
  re-admission could reference a locally retained root from the member's prior
  admission era. Version 0.2.27 applies the same root-era/current-access check
  to inbound replies and reply/root mutations and includes hostile regression
  coverage for both cases. The immutable 0.2.27 review build was then
  superseded before installation because repeated local hide operations could
  decrement the derived unread summary for the same reply more than once.
  Version 0.2.28 makes that derived update idempotent and verifies that hiding
  one of two unread replies twice leaves the other reply unread.
- No installer or application executable was launched and no existing Mesh
  Chat process or user profile was modified. Physical concurrent-device thread
  partition/reconnect, interactive native-window accessibility, packet capture,
  protected-profile plaintext scanning, production signing, and in-place
  installation remain release gates.

## Workspace increment 9 verification — 2026-10-09

- Increment 9 adds retained encrypted local history for active and archived
  conversations, per-message revisions and reactions, author-signed deletion
  tombstones, durable sequence floors and permanent gaps, and restart-safe
  bounded pruning. The owner may publish a signed cooperative retention value
  of 30, 90, or 365 days, or indefinite retention. It is not remote erasure:
  peers can retain exports, backups, screenshots, or modified-client copies.
- Protocol and service coverage verifies authority-only retention transitions,
  stale-cursor rejection after policy changes, bounded revision and tombstone
  views, pruning across restart, retired-event replay rejection, the independent
  seven-day live-delivery window, former-member read-only archives, private
  re-admission gaps, workspace-DM participant isolation, and owner non-access
  to other members' DMs. Renderer coverage exercises the retention selector,
  cooperative-policy warning, manual bounded prune progress/restart state,
  per-message History view, deleted-message history, and explicit pruned/gap
  states.
- The complete maintained verification passed **318 Python tests with 6
  intentional environment/package skips**, **87 frontend tests**, all **3**
  package-artwork verifier tests, TypeScript compilation, and the Vite
  production build. `cargo fmt --check`, the locked Rust release check, and all
  **6 release-profile tests** passed. The protected four-process/three-hop
  topology and both direct-LAN scenarios passed. All **3** tests against the
  exact immutable 0.2.29 sidecar passed, including the frozen 0.2.9
  interoperability run. The final application executable matched all **12**
  bundled artwork files (1,947,195 source bytes). The maintained verification
  report is
  `dist/reports/0.2.29/20261010T021333Z-b7520d86/report.json`.
- The reproducible `service/tools/workspace_retention_benchmark.py` fixture ran
  on Windows 10.0.19045, Python 3.13.15, a 12-logical-CPU Intel Family 6 Model
  158 host with 17,019,686,912 bytes of physical memory, and a SQLite
  DELETE/FULL vault with per-record AES-256-GCM. It retained **50,000** events
  across 8 synthetic members and 32 channels: 42,000 roots, 3,000 replies,
  2,000 edits, 2,000 reactions, 1,000 tombstones, 4,000 linked-device delivery
  legs, and a 2,000-item pending queue. Startup summary took **36.374 ms** and
  read no event or delivery bodies. Latest-50 warm p95 was **78.886 ms** over 30
  samples; process-cold p95 was **71.872 ms** over 30 samples, where
  process-cold means a new `VaultStore` and service instance without flushing
  the OS file cache. Send commit returned in **22.043 ms** with zero route
  attempts. Fifty restart-safe batches of 1,000 pruned all expired events in
  **233.816 s**; a restart recovered exactly 2,000 pending items without false
  delivery or duplication, chatting continued, and replay of a pruned event ID
  was rejected. Peak working set was 226,795,520 bytes and Python tracemalloc
  peak was 99,413,606 bytes. The seeded vault grew 531,517,440 bytes; after
  pruning its 531,918,848-byte file contained 109,814 reusable SQLite free
  pages rather than claiming physical compaction. All benchmark assertions
  passed in **378.225 s** total.
- The maintained release driver immutably published desktop **0.2.29** without
  changing 0.2.28 or any earlier release. The 22,282,240-byte MSI has SHA-256
  `86232CA3647C69D23DE39BCB6F3DD4445D780E21CED8A863D476969265E55741`.
  The 21,548,937-byte NSIS installer has SHA-256
  `357DA13F386534C672F90BA60687814B8C7B190B82B327A620A140E751A196E5`.
  The 6,725,632-byte portable application reports file/product version 0.2.29
  and hashes to
  `D5C00874A3FC4CCD48D4F1A2E5D26FB1246465344BE4F2CE4307C943C316D0DA`;
  the 18,065,086-byte sidecar hashes to
  `91D6EC6D477DF257FD2BACEA608C5291023F377E4E237FC8AC8AF153ED1D0568`.
  The 3,239-byte release notice hashes to
  `D663E6E7B26D12B33F5042B7C9F413BA57CABF331A6D0B0C37693F2B3D125D44`.
  The immutable manifest hashes to
  `A8ABA27F3CE65BD2B2A645EAC55E514A4899BEF3DABB123106B67A6C9A2A25FC`,
  and `dist/desktop/current.json` selects that manifest. The successful release
  report is
  `dist/reports/0.2.29/20261010T023701Z-4a2f1ca1/report.json`.
- Three earlier delivery attempts are retained as failure evidence. The first
  stopped in preflight with only 0.84 GiB free; the second hit a transient pnpm
  EPERM while restoring `node_modules`; and the third linked the application
  but WiX failed under tight disk pressure. After restoring dependencies,
  deleting only disposable generated compiler symbols, and successfully
  exercising Tauri's bundle-only path, the full maintained release entry point
  completed and transactionally published the immutable candidate.
- No installer or application executable was launched and no existing Mesh
  Chat process or user profile was modified. Physical concurrent-device
  retention/prune partition and reconnect, interactive native-window
  accessibility, packet capture, protected-profile plaintext scanning,
  production signing, in-place installation, and Windows-to-Android validation
  remain release gates.

## Workspace increment 10 verification — 2026-10-09

- Increment 10 adds encrypted local exact-token search over retained workspace
  message roots, thread replies, current permitted people names, and visible
  channel names/topics. Frozen NFKC/default-casefold/NFC normalization feeds
  workspace-keyed HMAC token IDs and sealed 100-reference pages. Queries are
  capped at 256 characters, 1,024 UTF-8 bytes, and eight tokens; execution is
  capped at eight shard pages, 256 decrypted candidates, and 50 results.
  Authenticated cursors contain opaque query/scope digests and bind access,
  retention, search generation, shard, page, and offset. They never carry raw
  queries.
- Service/protocol coverage verifies normalization and punctuation, token/query
  limits, deterministic ordering and duplicate-free pagination, cursor MAC
  tampering and cross-query/scope/generation staleness, incremental edit
  replacement, reaction non-indexing, deletion/hide/prune suppression, bounded
  shards/candidates/pages, 0.2.29 migration and restart recovery, roots/replies,
  people/channels, former-member read-only archives, private removal and
  re-admission gaps, owner/nonparticipant workspace-DM isolation, no whole-kind
  query scan, encrypted-at-rest representative markers, and SQLite-safe keyed
  metadata. Renderer coverage exercises All/Messages/Threads/People/Channels,
  debounce/loading/pagination, accessible labels and focus, and exact thread
  navigation. Rust coverage verifies the desktop-only command allowlist.
- The complete maintained verification passed **322 Python tests with 6
  intentional environment/package skips**, **88 frontend tests**, all **3**
  package-artwork verifier tests, TypeScript compilation, and the Vite
  production build. `cargo fmt --check`, the locked Rust release check, and all
  **6 release-profile tests** passed. The protected four-process/three-hop
  topology and both direct-LAN scenarios passed. All **3** tests against the
  exact immutable 0.2.30 sidecar passed, including frozen 0.2.9
  interoperability. The final application matched all **12** bundled artwork
  files (1,947,195 source bytes). The maintained verification report is
  `dist/reports/0.2.30/20261010T032511Z-61d71b79/report.json`.
- The reproducible `service/tools/workspace_search_benchmark.py` ran on Windows
  10.0.19045, Python 3.13.15, a 12-logical-CPU Intel Family 6 Model 158 host
  with 17,019,686,912 bytes of physical memory. Its Increment 9-derived fixture
  retained **50,000** events for 8 synthetic members and 32 public channel
  chains plus one private authorization probe: 42,000 roots, 3,000 replies,
  2,000 edits, 2,000 reactions, 1,000 tombstones, 4,000 linked-device delivery
  legs, and 2,000 pending items. Metadata-only startup took **76.582 ms** and
  opened no event/message bodies or whole message collection. Restart-safe
  indexing covered 50,000 event positions in **190.148 s** across **391**
  transactions, producing 45,041 search documents and 95,226 keyed index/page
  records without reference duplication after restart.
- Over 30 samples per series, first-page p95 was **728.881 ms** for a common
  message query, **13.699 ms** rare, **1.437 ms** no-result, **16.365 ms**
  thread, **4.123 ms** person, **3.404 ms** channel, **786.925 ms** warm, and
  **773.836 ms** process-cold. Process-cold means a new `VaultStore` and service
  instance without flushing the OS file cache. All remained below the 2-second
  desktop target. The common query opened 256 candidates and three shard pages;
  ordinary send committed in **111.378 ms** with zero route attempts. Peak
  working set was 970,940,416 bytes and Python tracemalloc peak was 897,159,730
  bytes for the combined seed/rebuild/timing process. The encrypted index grew
  the vault by 364,130,304 bytes; the final benchmark vault was 896,327,680
  bytes. All access, mutation, cursor, prune/restart, no-scan, and plaintext
  absence assertions passed. The 10,637-byte evidence JSON hashes to
  `6A25C46812A4921CD2EED77975AE24D49112D149ED962D130A9E3371A228C05E`
  at `dist/reports/0.2.30/increment10-search-benchmark.json`.
- The first full benchmark attempt stopped during index growth with SQLite
  `database or disk is full` when only 4 MiB remained. No release or user data
  changed. Three validated temporary benchmark profiles and the disposable
  generated Rust release cache were removed, restoring 3.3 GB, and the full
  rerun above passed. An initial unscoped `vitest run` also collected the
  separate Node `node:test` artwork file and reported “no test suite”; the
  maintained scoped frontend runner then passed all 88 Vitest tests and the
  separate Node runner passed its 3 artwork tests. A direct shell `cargo`
  lookup was absent from `PATH`; the pinned `~/.cargo/bin/cargo.exe` toolchain
  completed all required Rust gates.
- The maintained release driver immutably published desktop **0.2.30** without
  changing 0.2.29 or any earlier release. The 22,302,720-byte MSI has SHA-256
  `B573C7E457FB69411890A8B36293EE1F1DD18E5B4D6DFD1A2EB4A129B109B158`.
  The 21,569,391-byte NSIS installer hashes to
  `2B8ADB16FD3F2623ECDD95925E1FC667F7C5B92BBB8FF0AEBEBC527E6C524DEE`.
  The 6,727,680-byte portable application reports file/product version 0.2.30
  and hashes to
  `8BC26948ADE1B4FC93C2CE20DD84D2B002DF78E5A5677BD66DCFEC66B84B4320`;
  the 18,082,474-byte sidecar hashes to
  `B87B171E1553EB9BD3609C1D2E4CE58AE5D425DCAE2FC72BCEAA0CC13DAE86C7`.
  The immutable manifest hashes to
  `05F773EFFF28FF231AC33B86131B01B39BBB08AAD7C026EB1EEA10624C44C530`,
  and `dist/desktop/current.json` selects it. The successful release report is
  `dist/reports/0.2.30/20261010T032654Z-daea9a5a/report.json`.
- No installer or application executable was launched and no existing Mesh
  Chat user profile was modified. Physical concurrent-device search under
  private removal/re-admission and retention partition/reconnect, interactive
  native-window keyboard/screen-reader review, packet capture, protected-profile
  full-tree plaintext scanning, production signing, in-place installation, and
  Windows-to-Android validation remain release gates.

## Workspace increment 11 verification — 2026-10-10

- Increment 11 adds peer-to-peer workspace history catch-up without a server,
  relay, or global archive. Canonical signed requests and bounded signed
  responses are tied to opaque request IDs, requester/responder device IDs,
  exact public/private-era/DM scope, request nonce, continuation, prior-page
  digest, retention policy, and access state. Responses carry prerequisite
  controls and signed author checkpoints before ordinary events, expose signed
  heads and floors, and distinguish permanent/local-prune gaps from peer-limited
  coverage. Requests are capped at 32 streams and 64 ranges; a response is
  capped at 32 controls, 32 checkpoints, 32 events, and 128 KiB.
- Protocol/service coverage verifies canonical bytes, signature and field
  binding, nonce and page replay rejection, exact continuation chaining,
  count/byte/range bounds, public/private-era/DM disclosure, inactive-author
  checkpoint commitments at removal, direct indexed responder lookup, exact
  canonical event recovery between two independently encrypted profiles,
  durable restart, checkpoint-first validation, permanent-gap recording, honest
  `complete_known`/`peer_limited` status, and erasure of jobs, caches, coverage,
  nonces, and checkpoints. Scheduler state is sealed, allows at most two jobs
  per workspace and four per profile, and caps a pass at 256 sequence probes.
  Renderer and Rust coverage verify the History & retention sync status,
  start/cancel/refresh controls, accessible live updates, exact desktop command
  allowlisting, and explicit peer-unavailable, local-prune, and permanent-gap
  states. Ordinary live delivery still emits one event packet; checkpoints are
  retained for authenticated history disclosure rather than doubling traffic.
- The complete maintained verification passed **337 Python tests with 6
  intentional environment/package skips**, **88 frontend tests**, all **3**
  package-artwork source tests, TypeScript compilation, and the Vite production
  build. `cargo fmt --check`, the locked Rust release check, and all **6**
  release-profile tests passed. The protected four-process/three-hop topology
  and both direct-LAN scenarios passed. All **3** tests against the exact
  immutable 0.2.31 sidecar passed, including frozen 0.2.9 interoperability;
  all **7** desktop release tests passed with an isolated pytest base temp. The
  final application matched all **12** bundled artwork files (1,947,195 source
  bytes). The maintained verification report is
  `dist/reports/0.2.31/20261010T140647Z-7a8673ff/report.json`.
- The reproducible `service/tools/workspace_history_catchup_benchmark.py` ran
  on Windows 10.0.19045 with Python 3.13.15, Node 24.19.0, Rust 1.99.0, a
  12-logical-CPU Intel Family 6 Model 158 host, and 17,019,686,912 bytes of
  physical memory. Its Increment 9-derived encrypted fixture retained **50,000**
  events for 8 members and 32 channels: 42,000 roots, 3,000 replies, 2,000
  edits, 2,000 reactions, 1,000 tombstones, 4,000 linked-device delivery legs,
  and 2,000 pending items. The fixture vault was 532,119,552 bytes. A real
  independently encrypted requester recovered 32 exact canonical events after
  all 32 ordinary delivery legs were durably expired beyond the independent
  live-delivery window. Recovery used two responses totaling 35,446 bytes,
  including two prerequisite controls and checkpoint validation.
- Across 30 samples, request sign/verify p95 was **2.045 ms**, bounded response
  construction p95 **1.679 ms**, and response verification p95 **7.469 ms**.
  First-response commit took **987.224 ms**, continuation processing
  **80.008 ms**, total catch-up **1,288.147 ms**, duplicate rejection
  **12.666 ms**, private-nonmember denial p95 **11.211 ms**, DM-nonparticipant
  denial p95 **7.863 ms**, and restart/resume **8.560 ms**. Throughput was
  24.842 useful events/s; peak working set was 225,460,224 bytes and Python
  tracemalloc peak was 99,626,288 bytes. The requester vault grew 479,232 bytes
  to 544,768 bytes, and the serving vault grew 1,171,456 bytes to 1,265,664
  bytes. All boundary, authorization, canonical-byte, expired-live-leg, replay,
  signed-head completion, restart, and full-size-fixture assertions passed in
  **111.390 s**. The 2,665-byte evidence JSON hashes to
  `15E1E687C73E26EC27D8885E27DE61E1AFA3A311E27D12739BC28D48A1C4B514`
  at `dist/reports/0.2.31/increment11-history-benchmark.json`.
- The maintained release driver immutably published desktop **0.2.31** without
  changing 0.2.30 or earlier releases. The 22,347,776-byte MSI hashes to
  `498418B04CFD9CE5DFAC8D56F5FD8DB3ECFE29C70AC7A017AE4BE4D7D4818A38`;
  the 21,614,129-byte NSIS installer hashes to
  `DB092CB491241ACD98CF405BA8B3D58CA3D1257703286BD2E7EBED1BF28CB1E8`.
  The 6,728,704-byte portable application reports file/product version 0.2.31
  and hashes to
  `D397F3DE2C85D506C23A2E5E8C32888F18A368F63CEBFBA878236DB9CAEAF813`;
  the 18,126,664-byte sidecar hashes to
  `56CD521282D9FE87A626C94F1AE1C4E1882E2878F7DE656C537B8A825BE0568B`.
  The immutable manifest hashes to
  `FBAED26CF0A298F0132D3D3960D2A21927DFDC703E8BF93A78A5B8B45753B142`,
  and `dist/desktop/current.json` selects it. The successful release report is
  `dist/reports/0.2.31/20261010T141349Z-1aca514c/report.json`.
- Failure evidence was retained while converging. Early checkpoint delivery
  doubled live packets and broke seven workspace expectations; checkpoints were
  moved to history disclosure and the full suite passed. One guessed pytest
  filename selected no tests. The first final Python run found a renderer
  wording mismatch, then passed after the status copy and assertion agreed.
  Early frontend attempts hit the system Node 14 shim and one pnpm sandbox
  `EPERM`; the pinned Node 24 runner passed. Benchmark smoke runs first found a
  missing `local_pruned` metric and then the required empty terminal page; both
  were corrected. A full benchmark rerun later reached reporting before a
  mistyped working-set field failed; the corrected full rerun above passed.
  Exact disposable benchmark-profile cleanup once required a scoped elevated
  retry. A combined package/desktop pytest run passed the three package tests
  but hit seven setup errors from an inaccessible stale global temp directory;
  rerunning the seven desktop tests with a unique base temp passed. Three
  artwork-verifier invocations used, in turn, a missing flag, a stale Node path,
  and a wrong executable subdirectory; the final exact-binary run passed.
- No installer or application executable was launched and no existing Mesh
  Chat process or user profile was modified. Physical concurrent-device
  catch-up across partition/removal/re-admission, hostile peer fault injection,
  native-window keyboard/screen-reader review, packet capture,
  protected-profile full-tree plaintext scanning, production signing, in-place
  installation, and Windows-to-Android validation remain release gates.

## Workspace increment 12 verification — 2026-10-10

- Increment 12 adds effective `owner`, `admin`, and `member` roles, exact
  `all_members|owner_and_admins` channel/posting policies, and exact
  `owner_only|owner_and_admins|all_members_request` invitation-request policy.
  Administrators can create/post and manage channels for which they hold the
  signed manager role while the owner is offline. They gain no manifest key,
  global policy/retention/closure authority, arbitrary channel control,
  private-channel discovery/recovery, or third-party DM access.
- ADR 0011 freezes the 4 KiB request and 48 KiB decision phases of
  `workspace_admin_request`, seven-day lifetime, 250-character note, replay and
  result bindings, one-target invitation/removal/role workflows, and
  pending/approved/declined/stale/superseded/expired/safe-cancel lifecycle.
  Sealed HMAC-addressed indexes cap pending requests at 128 per workspace, 512
  per profile and 32 per requester/source; pages are at most 100 rows, inert
  decisions at most 64, and terminal replay/audit retention 90 days. Role
  manifests change exactly one active nonowner between member/admin and cannot
  combine another mutation.
- Protocol/service tests cover canonical and worst-case Unicode serialization,
  byte/field/signature/workspace/base/target/role/result binding, every
  invitation policy, unauthorized members and administrators, duplicate and
  conflicting results, safe cancellation, direct owner transitions,
  supersession/staleness/expiry, restart durability, demotion enforcement,
  owner-only operations, manager-transfer constraints, private/DM isolation,
  erasure and bounded indexed paging. Renderer tests cover effective versus
  requested roles, owner review warnings and confirmation, destructive removal,
  outgoing outcomes, pending counts, and immediate control changes. Rust tests
  cover every new desktop-only command.
- The maintained verification passed **347 Python tests with 8 intentional
  environment/package skips**, **90 frontend tests**, all **3** standalone
  package-artwork verifier tests, TypeScript project compilation, and the Vite
  production build. `cargo fmt --check`, locked Rust release check and all
  **6 release-profile tests** passed. The Windows protected four-process,
  three-hop topology passed. All three direct-LAN scenarios passed, including
  the two-real-process administrator owner-offline flow. The exact immutable
  0.2.32 package passed phone-first/direct/reaction/delete/reopen and
  administrator flows. Exact 0.2.31 interoperability converged its supported
  expanded reaction; frozen 0.2.9 safely ignored it and continued bidirectional
  chat. Final app artwork matched all **12** bundled files (1,947,195 source
  bytes). The successful maintained report is
  `dist/reports/0.2.32/20261010T172636Z-6519e129/report.json` and the successful
  delivery report is
  `dist/reports/0.2.32/20261010T173233Z-0abbc471/report.json`.
- The reproducible administrator benchmark ran on Windows 10.0.19045,
  Intel64 Family 6 Model 158, Python 3.13.15, Rust 1.99.0, Node 24.19.0 and
  17,019,686,912 bytes physical memory. Its encrypted fixture held 50,000
  events, 8 members, 24 public/4 private/4 archived control chains, 42,000
  roots, 3,000 replies, 2,000 edits, 2,000 reactions, 1,000 tombstones, 4,000
  linked-device legs and 2,000 pending items across independent owner/admin/
  member profiles. Over 30 samples, request p50/p95 was **2.509/2.683 ms**,
  owner-page **7.407/8.132 ms**, decision **4.386/4.802 ms**, role commit
  **26.814/30.432 ms**, invitation approval **54.088/57.892 ms**, owner-offline
  admin create/post **80.455/98.869 ms**, duplicate rejection
  **0.480/0.758 ms**, and stale/superseded resolution **70.278/87.311 ms**.
  Restart was **12.454 ms**, first owner-visible request **2,635.476 ms**, and
  end-to-end 30-request approval/result delivery **4,754.499 ms**.
- The benchmark observed 1,686-byte maximum canonical requests, 5,248-byte
  decisions, 4,063-byte invitations and 2,576-byte result manifests; 62 queued
  packets, 1,447 route attempts and 196 modeled transactions; 99,636,650-byte
  peak Python allocation and 228,233,216-byte peak working set. Vault growth was
  3,063,808 owner, 3,022,848 admin and 987,136 member bytes. All 31 policy,
  state, replay, conflict, demotion, private confidentiality, resource and
  timing assertions passed in 142.669 seconds. The 4,917-byte evidence file is
  `docs/benchmarks/increment-12-workspace-administrators.json`, SHA-256
  `90D6A5F18E1D45E3AA54E2334CB4F88597DEBEF2C97995F6E8CF3449E98DF379`.
- The release driver immutably published desktop **0.2.32** without changing an
  earlier release. The 22,380,544-byte MSI hashes to
  `2E9417144762F9C74046FDE0B4FEDAA1B567B9D6D37E961A06D440F290B52909`;
  the 21,644,516-byte NSIS installer hashes to
  `7A06986FC4174A685E8A59B524460E34932858EA77CEED02FE404487AEAC9590`.
  The 6,730,752-byte portable app reports file/product 0.2.32 and hashes to
  `850C8004FD9A3498943F9560AFDF33874C81E894A05027B83F95B33BF5F5A740`;
  the 18,156,246-byte sidecar hashes to
  `407AE337232FEBC83D90566766A47CEFDFF5C3868CE12D6DB04978A337891CF2`.
  The immutable manifest is 1,345 bytes, hashes to
  `B17156AAC0D1A6E6D33AA7F293FBA67974A8E98CE26AE524B276EC55A727EEFD`,
  and is selected by `dist/desktop/current.json`.
- Transient failures were preserved honestly. A full Cargo debug test first
  exhausted the host disk/PDB allocator; after deleting only the exact
  disposable target, single-job non-incremental release check/test passed with
  debug symbols disabled. An unscoped Vitest run collected the separate Node
  artwork test until the dedicated config was scoped. The first full benchmark
  confidentiality probe counted unrelated retried public packets by destination
  until it was narrowed to the exact private channel document; the corrected
  50K run passed. Initial direct-LAN probes used an overlong IPC request ID and
  then matched a snake-case error instead of the typed `ContactNotApproved`;
  the exact flow passed after those harness fixes. The first maintained verify
  run found a widened Vite `minify` type; restoring `UserConfig` passed. The
  first package build hit pnpm sandbox `EPERM`; the identical elevated retry
  reused the sidecar, repaired local dependencies, and passed. A mixed 0.2.31
  assertion initially expected old-peer ignore behavior; capability-aware
  0.2.31 convergence and exact 0.2.9 ignore gates both passed.
- No installer or application was launched and no existing Mesh Chat process
  or user profile was modified. Physical concurrent-device admin partitions,
  hostile request floods/fault injection, native-window keyboard/screen-reader
  review, packet capture, protected-profile full-tree plaintext scanning,
  production signing, in-place installation, and Windows-to-Android validation
  remain manual/physical release gates. Permanent owner-authority loss remains
  intentionally unresolved until Increment 13.

## Workspace increment 13 verification — 2026-10-11

- Increment 13 adds canonical current-authority offers, exact named-successor
  acceptances, and predecessor-authority-signed final manifests for same-owner
  authority rotation and ownership transfer. Offers and acceptances remain
  inert. Ownership transfer freezes the outgoing owner's exact `admin` or
  `member` role in the offer and commits the final manifest with the exact
  signed `#general` recovery result. Remote peers stage that recovery until the
  final manifest validates. The old authority is rejected immediately after
  cutover; the successor signs later ordinary manifests.
- ADR 0012 freezes 8 KiB offers, 16 KiB acceptances, a seven-day lifetime, 32
  pending transitions, eight authority-certificate steps, and a 256 KiB total
  invitation bootstrap bound. Existing empty chains and historical manifest
  bytes remain valid. Complete invitation proofs validate every base manifest,
  offer, acceptance, optional `#general` result, final manifest, owner change,
  and signer change from genesis to the offered checkpoint. Permanent authority
  loss freezes authority-dependent administration and presents only the honest
  replacement-workspace path; ordinary authorized chat remains available.
- The maintained release verification passed **355 Python tests with 9
  intentional environment/package skips**, **91 frontend tests**, all **3**
  standalone package-artwork tests, TypeScript compilation, and the Vite
  production build. `cargo fmt --check`, locked Cargo release check, and all
  **6 release-profile Rust tests** passed. The protected four-process topology
  and all three direct-LAN scenarios passed (**4/4**). The exact immutable
  0.2.33 sidecar passed its phone-first/direct/reaction/delete/reopen,
  administrator, and complete ownership-transfer workflows (**4 passed, 1
  intentional legacy skip**). The packaged authority run proved inert offer and
  acceptance states, chat during the pending transition, final owner/role
  cutover, old-authority rejection, successor manifest publication, and
  `#general` manager continuity. Exact
  0.2.32 and 0.2.31 mixed runs converged, and frozen 0.2.9 safely ignored the
  expanded reaction while bidirectional traffic continued. The successful
  maintained report is
  `dist/reports/0.2.33/20261011T183531Z-eaaf8910/report.json`; the successful
  delivery report is
  `dist/reports/0.2.33/20261011T182603Z-a82d78b3/report.json`.
- The reproducible authority-continuity benchmark ran on Windows 10.0.19045,
  Intel64 Family 6 Model 158, Python 3.13.15, Rust 1.99.0, Node 24.19.0, and
  17,019,686,912 bytes physical memory. Its encrypted fixture held 50,000
  events, 8 members, 24 public/4 private/4 archived control chains, 42,000
  roots, 3,000 replies, 2,000 edits, 2,000 reactions, 1,000 tombstones, 4,000
  linked-device legs, and 2,000 pending items. It used three independently
  encrypted authority/successor/member profiles and built the maximum
  eight-step certificate plus one live ownership transfer.
- Across 30 samples, offer construction/validation p50/p95 was
  **1.191/1.485 ms**, acceptance **2.254/2.476 ms**, final-manifest
  construction/validation **6.283/6.545 ms**, duplicate validation
  **1.803/2.018 ms**, and full eight-step invitation-chain verification
  **122.872/135.657 ms**. Chain construction was **88.520 ms**, durable final
  commit **30.596 ms**, first successor-visible offer **14.514 ms**, visible
  acceptance **131.839 ms**, effective three-peer cutover **435.423 ms**,
  successor owner action **24.635 ms**, end-to-end **460.058 ms**, and restart
  **8.722 ms**. All limits passed.
- Maximum canonical sizes were 1,174-byte offer, 2,211-byte acceptance,
  2,602-byte final manifest, 559-byte `#general` result, and 76,904-byte
  maximum-depth invitation. The live route used 52 attempts, 10,162 bytes for
  final controls, queue depth 6, and 164 modeled transactions. Peak Python
  allocation was 99,661,990 bytes and process working set 232,132,608 bytes.
  Vault growth was 110,592 bytes for the current authority, 122,880 for the
  successor, and 65,536 for the ordinary member. Every correctness,
  confidentiality, convergence, old-authority rejection, pending-chat,
  resource, and timing assertion passed in 113.835 seconds. The 4,542-byte
  evidence file is `docs/benchmarks/increment-13-authority-continuity.json`,
  SHA-256
  `E0B901776A1D16419F022B64C4A1AAC69AC6916C0F815A24B3EC3AF96C9CD036`.
- The release driver immutably published desktop **0.2.33** without modifying
  an earlier release. The 23,437,312-byte MSI hashes to
  `3D9B389B0BA7964B57E662FDF949D42172A1400D486073AF69F820A7615B7F8A`;
  the 22,712,141-byte NSIS installer hashes to
  `2AF90B7B68BC59870552F76D25692E1C0B24E98A0A7A1C2C205FE5882DACAF4F`.
  The 6,732,800-byte portable application reports file/product 0.2.33 and
  hashes to
  `C4A24E1B101F5CCD9AA1CFF0DB922AD19AE4FB6AD92F15ED747BF7A03F4F4176`;
  the 19,217,540-byte sidecar hashes to
  `37AA24AD6488E5B65E708FBC85D6702D7ECB75D92C830E29DB45D1D6B66D870D`.
  The 1,345-byte immutable manifest hashes to
  `1039BFC791DF4227ABBA8FAE5015A67CD9A7BE86DF34211EBE2FB3D013422980`
  and is selected by `dist/desktop/current.json`.
- Transient failures were preserved honestly. A system-Node `pnpm build` used
  Node 14 and failed on modern syntax; the pinned Node 24 runner passed. One
  sandboxed Vite build could not read the repository root; the identical
  approved build passed. The first benchmark smoke used too few fixture events,
  then exposed and fixed the valid successive-transition chain rule; later
  smoke runs exposed and fixed successor acceptance fan-out and the ordinary
  member's prerequisite history catch-up. The first release preflight found
  pnpm 11.25 while metadata still pinned 11.19; metadata and documented
  prerequisites were synchronized. An interrupted sandbox package attempt
  removed frontend links while pnpm could not reach its metadata endpoint; the
  exact frozen-lockfile set was restored from the local content-addressed store
  and the deterministic build passed. The first packaged-sidecar run inside
  the filesystem sandbox failed closed with `protected_storage_unavailable`;
  the EFS-capable exact-binary rerun passed.
  A first task-generated 0.2.33 candidate exposed an incomplete
  permanent-authority-loss freeze during final review. A second exposed that
  same-owner acceptance fan-out excluded the entire owner member instead of
  only the sending device. Both were rejected before commit or distribution;
  the centralized authority-operation gate, exact-device fan-out, and seeded
  multi-device regression were added before the immutable candidate was
  rebuilt. Its first exact-package authority run then found a readiness race
  in the harness itself (`#general` had not arrived); the predicate was bounded
  to the channel checkpoint and the full 4-pass packaged rerun succeeded.
  The first pushed CI run then failed before dependency installation because
  its workflow still explicitly selected pnpm 11.19 while `package.json`
  selected 11.25. All CI and release workflow setup blocks were synchronized
  to 11.25 before the maintained verifier and replacement CI run.
- No installer or application was launched and no existing Mesh Chat process
  or user profile was modified. Physical concurrent-device authority
  partitions and kill-point testing, hostile transition flood/fault injection,
  native-window keyboard/screen-reader review, packet capture,
  protected-profile full-tree plaintext scanning, production signing,
  in-place installation, and Windows-to-Android validation remain manual or
  physical release gates.

## Workspace increment 14 verification — 2026-10-11

- Increment 14 adds a countersigned, 15-minute, single-use device-link proof.
  An existing active device signs the genesis/current-manifest bootstrap; the
  new desktop generates a fresh RNS identity and countersigns its new device
  card; only the owner authority's exact one-card manifest delta grants access.
  Historical ordinary and authority manifest paths remain strict and reject
  device-transition fields. Enrollment is capped at three devices per member
  and 24 active destinations.
- Channels and workspace DMs already froze per-device destinations at event
  commit, including the sender's other devices. Increment 14 exposes the
  maintained link/review/removal lifecycle, sends authorized public/private
  controls to the new endpoint, and uses bounded authenticated history for
  canonical recovery. Removal cancels only the lost endpoint's pending legs,
  rejects its newly seen traffic once learned, and requires authority rotation
  before the authority endpoint can be removed. Optional read hints are
  encrypted same-member controls, opt-in, exact-head-bound, and never social
  receipts. ADR 0013 freezes the schemas and partition semantics.
- The automated two-desktop flow uses independent private identities and proves
  link creation, unknown-source acceptance binding, visible owner approval,
  manifest convergence after the workspace has advanced beyond epoch one,
  authority-endorsed historical checkpoint installation, authorized
  `#general` control delivery, pre-link canonical history recovery, private
  read-hint convergence, authority-removal rejection, endpoint-only
  cancellation, and terminal `device_removed` convergence.
  Protocol coverage also proves ordinary-path rejection, exact one-card deltas,
  stale/expiry/signature bounds, one remaining device, and the three/24 caps.
- The final source verification passed **359 Python tests with 10 intentional
  environment/package skips**. All **91 frontend tests**, TypeScript
  compilation, the production Vite build, all **6 locked release-profile
  Rust/Tauri tests**, the 3-test standalone packaged-artwork verifier, and the
  protected topology/direct-LAN matrix (**4/4**) passed. Final package
  verification is recorded below after immutable publication.
- The reproducible encrypted scale run used Windows 10.0.19045, Intel64 Family
  6 Model 158, Python 3.13.15, 17,019,686,912 bytes physical memory, 50,000
  events, 8 members, 32 channels, 42,000 roots, 3,000 replies, 2,000 edits,
  2,000 reactions, 1,000 tombstones, 4,000 linked-device legs and 2,000 queued
  legs. Startup did not enumerate event or delivery bodies; all inherited
  paging, pruning, restart, no-duplicate, no-false-delivered and route-independent
  commit assertions passed.
- Across 30 samples, countersigned link construction plus validation measured
  **6.333 ms p50 / 6.955 ms p95**, removal plus exact final-delta validation
  **1.227 / 1.725 ms**, and maximum 24-device manifest verification **6.331 /
  7.131 ms**. Warm/cold latest-50 paging measured **56.474 / 52.867 ms p95**;
  send commit was **34.718 ms**. Peak Python allocation was 99,376,371 bytes
  and peak working set 230,199,296 bytes. The largest acceptance was 4,016
  bytes and the 24-device manifest 13,978 bytes. All 12 Increment 14 assertions
  passed in 300.874 seconds with zero copied private identities.
- The 8,882-byte evidence file is
  `docs/benchmarks/increment-14-linked-desktop-devices.json`, SHA-256
  `BDF539042A64D91950178033B5987C2D95C448A614CA0698F84BB12BBD11469D`.
  The first complete scale workload passed but the new wrapper referenced three
  prior-schema report keys and failed before writing output. The reporting keys
  were corrected and the complete workload was rerun; this recorded run passed.
  A sandboxed system-Node build also failed because PATH selected Node 14; the
  pinned Node 24 TypeScript and Vitest runners passed. Final review found that
  a device linked after epoch one could receive the epoch-one `#general`
  control without its referenced manifest. The candidate was not released in
  that state: bounded authority-endorsed bootstrap checkpoints and a late-link
  regression were added, then the full suite, benchmark and package workflow
  were rerun successfully.
- The release driver immutably published desktop **0.2.34** without changing
  0.2.33 or any earlier release. The 23,470,080-byte MSI hashes to
  `84618601465F0D890F83FFF39EC289BEB554E9C8638369010E86C7FAD23256A0`;
  the 22,744,517-byte NSIS installer hashes to
  `B5AC805640B7ADAC1802AB267916E853A5078FBB66074C2319598F8AD83F21EA`.
  The 6,735,872-byte application reports file/product 0.2.34 and hashes to
  `19E723169AFB34D60913323A7C7BC8EBB1BB3F150A45B5A871C6D6EE6B126E80`;
  the 19,247,657-byte sidecar hashes to
  `03478DE167141D042FD9F01BD47FAC0762ACB40550E044128C4AC0394E51BCFD`.
  The 1,345-byte manifest hashes to
  `E1C3C268FB789C64561249EC3DE347B44EF12B2D43952E43562B982248ABB429`
  and is selected by `dist/desktop/current.json`. The successful build report
  is `dist/reports/0.2.34/20261011T193149Z-2c518e5e/report.json`; the final
  maintained verification report is
  `dist/reports/0.2.34/20261011T193939Z-9a1fc03e/report.json`.
- The exact immutable 0.2.34 sidecar passed direct/reaction/delete/reopen,
  administrator, authority-continuity and linked-device workflows (**5
  passed**, with the separately exercised legacy case intentionally skipped).
  The linked-device run proved distinct private identities, inert linking,
  exact owner approval, post-epoch-one `#general` bootstrap, pre-link history
  recovery, live fan-out and terminal device removal. Mixed exact-binary runs
  with 0.2.33, 0.2.32 and 0.2.31 converged; frozen 0.2.9 safely ignored the
  expanded reaction while ordinary traffic continued. The final application
  contains all 12 expected artwork/license files (1,947,195 source bytes).
- No installer or application was launched and no existing Mesh Chat profile
  was modified. Physical multi-device partitions, native-window accessibility,
  packet capture, protected-profile full-tree plaintext scanning, production
  signing and in-place installation remain manual release gates.

## Increment 15 mobile lifecycle and local-notification verification — 2026-10-11

- Source metadata was advanced transactionally to **0.2.35** (Android version
  code **2035**). The pre-release 0.2.34 desktop manifest still hashes to
  `E1C3C268FB789C64561249EC3DE347B44EF12B2D43952E43562B982248ABB429`,
  and the Android 0.2.12 manifest still hashes to
  `DE1B606E17FB64F46243C4676A69488B40433661E92A0C896B15A9B745416574`.
- Increment 15 reuses the exact Increment 14 sponsor/new-device/owner-authority
  exchange. Mobile keeps a fresh private identity and vault; no identity,
  private key, counter, or sealed profile is copied. The renderer workspace
  command allowlist is now cross-platform, while notification drain,
  acknowledgment, permission-state, and native lifecycle commands remain
  native-only.
- Live authorized message acceptance atomically records the derived message,
  unread/delivery state, sealed notification decision ledger, opaque route,
  bounded native work, and queue reference. The native Android/iOS worker
  drains this service queue directly without React polling. Same-member sends,
  edits, reactions, deletions, controls, duplicates, replays, historical
  catch-up, hidden or unauthorized content, inactive/forked state, foreground
  presentation, muted scopes, and unstructured `@name` text remain quiet.
  Structured mentions can pass an unsubscribed public channel under the frozen
  preference precedence. Notification taps re-authorize current state and do
  not mark read or change delivery state.
- Android implements API-33 `POST_NOTIFICATIONS`, pre-33 notification settings
  state, an explicit one-time permission request, settings recovery, stable
  default/high-importance channels, opaque tags/groups/intents, 80/160
  character and 1,024-byte native bounds, and a 750 ms direct native pump. The
  global sealed hide-preview setting emits only **Mesh Chat / New message**.
  Lifecycle callbacks persist foreground/background/suspended generations;
  foreground reconciliation drains bounded prerequisite and due-work indexes,
  suppresses stale pending presentation, clears overflow only after refresh,
  and never enumerates the event or delivery collections.
- The final maintained source run passed **367 Python tests**, with **11**
  intentional opt-in/platform/package skips after adding the packaged native
  notification probe. All **93 frontend tests**, TypeScript compilation, the
  Vite production build, **3** packaged-artwork verifier tests, Cargo formatting,
  the locked release check, and all **6** release-profile Rust/Tauri tests
  passed. The isolated protected topology and all three direct-LAN scenarios
  passed **4/4**. Android `assembleArm64Debug` succeeded; the exact arm Gradle
  unit-test variant also succeeded after compiling the app/plugin sources and
  reported `NO-SOURCE` for JVM unit classes.
- The exact immutable 0.2.35 sidecar passed direct/reaction/delete/reopen,
  administrator, authority-continuity, linked-device, and packaged
  notification/lifecycle IPC workflows, plus the 0.2.34 mixed-binary flow
  (**7 passed** across the maintained packaged file and focused native-command
  probe). Exact mixed runs with 0.2.33, 0.2.32, and 0.2.31 each converged;
  frozen 0.2.9 safely ignored the expanded additive reaction while ordinary
  bidirectional traffic continued.
- The final 50,000-event encrypted benchmark used Windows 10.0.19045, Intel64
  Family 6 Model 158, 12 logical CPUs, 17,019,686,912 bytes physical memory,
  Python 3.13.15, Rust 1.99.0, Node 24.19.0, Java 25.0.3, Gradle 9.6.1, Android
  SDK API 36, eight members, 32 public/private/archived channel chains, three
  independent protected profiles, and the 24-destination linked-device bound.
  All **29** assertions passed. Startup and resume recorded no whole-event or
  whole-delivery scan; 50,000 historical policy probes produced no notification
  storm; queue depth stopped at 128; hidden previews, denial purge, duplicate
  suppression, removed-device/fork failure, and no-notification-as-read or
  delivery semantics all passed.
- Across 30 samples, p50/p95 milliseconds were: notification policy
  **2.252/3.936**, durable enqueue **7.393/9.426**, authorized 16-item native
  dispatch **352.521/436.448**, duplicate suppression **0.220/0.374**,
  background transition **3.077/4.562**, no-change resume **33.945/36.621**,
  overflow resume **35.413/50.374**, network restoration **34.983/40.360**,
  notification-open authorization **11.339/12.590**, preference update
  **180.246/195.387**, pending-work restart **21.644/24.492**, and accepted
  live event to native request **20.597/23.619**. Peak Python allocation was
  99,399,669 bytes, peak working set 234,172,416 bytes, seeded vault growth
  531,374,080 bytes, notification-probe growth 2,293,760 bytes, and final vault
  size 534,274,048 bytes. The 9,361-byte evidence file is
  `docs/benchmarks/increment-15-mobile-lifecycle-notifications.json`, SHA-256
  `A90AE80C845D04ADD3BD74955102DE8C5CAD1AB4A714F3C32840F1F14ED54DF8`.
- Android package inspection found package `com.meshchat.mobile`, version
  0.2.35/2035, minimum API 24, target/compile API 36, arm64-v8a only,
  `POST_NOTIFICATIONS`, backup disabled, cleartext disabled, the embedded
  Python notification/lifecycle commands, both native channel identifiers,
  and the opaque notification deep-link marker. APK Signature Scheme v2
  verifies with the retained Android Debug certificate SHA-256
  `D6DBFF63834666BACE3D75B49234726E97CCCE26D2B9E9516309682E0A33143F`.
  The first signature invocation omitted `JAVA_HOME` and failed before reading
  the APK; the exact rerun with Android Studio's JBR passed.
- The immutable Android APK is 46,812,020 bytes with SHA-256
  `8D440768DBE40A633CD9A5BC35CF31F2B342E038C2A53545D5F80A8CA9ED6951`;
  its 473-byte manifest hashes to
  `C3B9BB31430C3F9B8298A2937B3088E77E8363ACF61A09C696224981BA6FF94E`.
  The Windows MSI is 23,486,464 bytes / `5B141C28785C5197314D60D92C6882D54C0BB76FF023960EA6E1F8D9C18EFDA3`;
  NSIS is 22,761,094 bytes / `B91A257D9181E52C21F0D07D6C0D8A974877A2DD32D2C8DFB98065C47D2E3BE9`;
  application is 6,739,456 bytes / `BE60E29078398F89D2AE27F78529B23BAC8A387A56AF94055874FCD176FF41EA`;
  sidecar is 19,261,868 bytes / `33E790488D15F3EE008684A7C855D8FF64AF4E796114BBF0C41F188DDFACA185`.
  The 1,345-byte desktop manifest hashes to
  `DBAB5A574DBE711E3840F129E117A615BCE1244B9FC39BAD3DDBD1AD166D4494`.
  All 12 desktop artwork/license files (1,947,195 source bytes) and all 15
  Android launcher foreground/standard/round density assets verified byte-for-byte.
  Delivery and final verification reports are
  `dist/reports/0.2.35/20261011T203714Z-1953882f/report.json` and
  `dist/reports/0.2.35/20261011T204438Z-82ebad0c/report.json`.
- Transient candidate failures were retained honestly: a system Node 14 build
  could not parse modern Vite syntax; the pinned Node 24 path passed. A first
  plain `python -m pytest` selected a system interpreter without pytest; the
  maintained virtual environment passed. The first notification mock had an
  incompatible generic and then lacked the native-open export; both were fixed
  before all 93 frontend tests passed. Direct Gradle initially lacked
  `tauri.settings.gradle`, then Tauri
  generated it. Windows rejected Tauri's convenience symlink after Cargo
  succeeded; the maintained content-verified copy/direct-Gradle fallback built
  the APK. The generic Gradle unit-test task was ambiguous and an invocation
  lacked `JAVA_HOME`; the exact arm variant with the configured JBR passed. A
  provisional 250 ms full-batch dispatch limit measured 439.960 ms p95; the ADR
  now distinguishes the 16-item authorized batch (750 ms limit) from the
  user-visible single live-event path (250 ms), and the complete benchmark was
  rerun successfully. An earlier benchmark was intentionally stopped before
  evidence publication when foreground suppression semantics changed.
- `adb devices -l` reported no attached device. Therefore no APK was installed,
  no existing profile was opened, Android battery/memory/lock-screen evidence
  was fabricated, or physical allow/deny/settings, background/screen-off,
  suspension/process-death, 0.2.12 in-place upgrade, link/removal, and tap-route
  matrix was claimed. Windows cannot build/sign iOS; macOS/Xcode/signing and a
  physical iOS device remain mandatory. Increment 15 is automated/package
  complete but **not physically complete on an advertised mobile platform**.

## Android parity increment verification — 2026-10-11

- The source audit and strict five-state matrix are recorded in
  `docs/ANDROID_PARITY.md`. Shared renderer/service code is classified as
  implemented but hardware-unverified unless Android-native evidence exists.
  The matrix explicitly records Personal, groups/announcements, every workspace
  family, OS ingress, lifecycle, notifications, protected storage, packaging,
  upgrades, accessibility, and the physical test backlog.
- The maintained Python run completed **374 passed, 11 skipped** in 51.74 s.
  Skips were the opt-in direct-LAN/topology/package harnesses and one Windows
  `/sys` storage-model test. A final focused source/release/mobile-bridge run
  completed **20 passed**. Personal direct, private-group, announcement,
  workspace channel/DM/thread/mention, mutation suppression, duplicate,
  foreground, open-time reauthorization, and local-erasure notification cases
  are included in those service tests.
- Final renderer verification completed **98 passed** across seven files,
  including Android device-neutral wording, cold/warm/delayed invitation
  handoff, foreground reconciliation overlap, trailing refresh, and Personal
  notification routing. TypeScript project compilation passed. The production
  Vite build completed 1,820 transformed modules. All **3** packaged emoji
  artwork tests passed.
- Rust/Tauri library tests completed **7 passed**, including strict desktop
  invitation validation and payload limits. Android Gradle
  `:app:testArm64DebugUnitTest` completed **2 passed** for supported and
  malformed/oversized native launch values. Gradle's no-secret
  `:app:validateReleaseSigning` task failed as required and named the absent
  keystore path, keystore password, alias, and key password. The release-AAB
  immutable publisher is covered with non-secret fixture bytes; no signing
  credential or certificate was created or committed.
- A current ARM64 debug APK compiled successfully through Rust, Kotlin,
  Chaquopy, and Gradle at
  `src-tauri/gen/android/app/build/outputs/apk/arm64/debug/app-arm64-debug.apk`.
  It is **61,210,794 bytes**, SHA-256
  `2919890141445E1E726DE3418BA6F2D96D923A0789D5AB61F538679AACB1D3B0`.
  `aapt2` reports package `com.meshchat.mobile`, version 0.2.35/2035,
  minimum API 24, target/compile API 36, and only `arm64-v8a` native code. The
  merged manifest retains backup disabled and cleartext disabled, declares
  `singleTask`, the three `meshchat:` launch families, and a VIEW-only bounded
  `.meshchat` content association. The APK contains the embedded Python runtime,
  `libmesh_chat_lib.so`, third-party notice, and launcher density assets.
  `apksigner` verifies APK Signature Scheme v2 with the existing Android Debug
  certificate SHA-256
  `D6DBFF63834666BACE3D75B49234726E97CCCE26D2B9E9516309682E0A33143F`.
- The current APK was deliberately **not published** over
  `dist/mobile/releases/0.2.35/android-arm64-debug`: the immutable publisher
  detected that version 0.2.35 already contains different bytes and required a
  version bump. The retained published 0.2.35 APK remains 46,812,020 bytes with
  SHA-256 `8D440768DBE40A633CD9A5BC35CF31F2B342E038C2A53545D5F80A8CA9ED6951`.
  The newly built Gradle output is therefore an unpublished verification
  candidate, not a replacement release. No APK/AAB release build was attempted
  with invented credentials and no AAB is claimed.
- Transient failures are retained: the first maintained frontend run found two
  new tests waiting on an empty-state heading despite fixtures that auto-opened
  a contact; the assertions were corrected and all 98 tests passed. The first
  Android Rust attempt encountered stale generated Tauri API cache directories;
  only the two verified generated cache copies were removed. A sandboxed retry
  could not recreate them outside the workspace, while the approved build did.
  Tauri then reached the known Windows developer-mode symlink restriction and
  the maintained content-verified copy/direct-Gradle fallback built the APK.
- `adb devices -l` reported no attached device. No APK was installed and no
  physical deep-link/file-provider, QR/camera/clipboard/share, lifecycle,
  notification permission/lock-screen/tap, process-death, linked-device,
  storage, accessibility, battery/memory, or upgrade result is claimed. The
  exact required physical matrix remains in `docs/ANDROID_PARITY.md`.

## Remote connectivity 0.2.39 verification — 2026-10-14

The implementation and records below cover desktop and Android source-supported paths. No authorized physical Android device was attached, so the physical release matrix remains open and no physical Android completion is claimed. iOS was not modified, built, tested, or included in this release evidence.

Commands and results:

- `python -m pytest service/tests` — **396 passed, 12 skipped** after the direct/live-default follow-up. This includes strict v1/v2 formats, proof that merely configuring a remote profile does not change default v1 invitation generation, signer/digest/profile tampering, unsafe literals, DNS mixed-answer rebinding defense, preview-without-network, durable explicit consent, separate propagation consent/removal, bounded retry backoff, scope reference counting, existing invitation/workspace/replay/ratchet/outbox regressions, and the environment-gated real-network case.
- `$env:MESH_CHAT_RUN_DIRECT_LAN_TESTS='1'; python -m pytest service/tests/test_direct_lan_harness.py -v` — **3 passed** after the follow-up. The isolated topology used no shared transport node and verified the signed direct invitation route, a phone-shaped joiner with no reverse listener, and workspace administrator messaging while the owner was offline after admission.
- `$env:MESH_CHAT_RUN_REMOTE_NETWORK_TESTS='1'; python -m pytest service/tests/test_remote_access_harness.py -v` — **1 passed**. The harness launched three isolated processes: one standard Reticulum TCP transport and two Mesh Chat clients with AutoInterface, LAN fallback, and shared-instance shortcuts disabled. Both clients had only outbound TCP access to the same node. It proved network-free preview; signed v2 consent; Personal request, approval, DM, and authenticated application receipt; workspace invitation, join, owner approval, channel message, and workspace DM. Both reported route kind `remote`.
- `pnpm test` — **110 passed across 7 files**. Coverage includes the direct/live no-transport default for personal and workspace invitations even when an approved remote profile exists, explicit remote selection, first-run and existing-profile privacy disclosure with required consent, sanitized settings state/actions, propagation's separate approval/removal, route labels without raw transport data, progress/error wording, and narrow/accessibility interactions.
- `pnpm exec tsc --noEmit` and `pnpm build` — both passed; the Vite production build completed.
- `cargo test --lib` in `src-tauri` — **7 passed**, including strict native v1/v2 launch/file parsing and byte bounds.
- `gradlew.bat :app:testArm64DebugUnitTest -x rustBuildArm64Debug --no-configuration-cache` in `src-tauri/gen/android` — **BUILD SUCCESSFUL, 96 tasks**. Native Android tests cover accepted and rejected v1/v2 deep links/files, malformed/extra fields, UTF-8, and size limits.
- `python scripts/build_android.py` — built and immutably published `dist/mobile/mesh-chat-0.2.39-android-arm64-debug.apk`, 46,882,848 bytes, SHA-256 `FC25A99B7C8500165BE035283461C0F563EBB1BBA58F2BCFF8CE32A2CEFFD281`.
- `python scripts/build_android.py --release` with all signing inputs pointing to a disposable 30-day test certificate — built and immutably published the optimized `dist/mobile/mesh-chat-0.2.39-android-arm64-release.apk`, 31,721,626 bytes, SHA-256 `CBA7D5AB3EC338B9201B06426250EB77E54A120CA15B758B6714C9704445C5BD`. The temporary keystore was deleted. `apksigner` verified v2/v3 signatures and one 3072-bit RSA signer; certificate SHA-256 was `6001C702631C3B5710DD00A45FF930BD7509B707FC06FB0709F31E0B04CC6EBC`. This is test signing, not a production or upgrade identity.
- Android package inspection reported `com.meshchat.mobile`, version `0.2.39` / code `2039`, minimum API 24, target API 36, arm64-v8a only, backup disabled, full-backup content disabled, and cleartext traffic disabled.
- `python scripts/release.py build --platform desktop --expected-version 0.2.39 --skip-tests` — completed the Windows release build and immutable publication. The x64 MSI is 23,531,520 bytes with SHA-256 `5A28B41F970F1EF45D68BE6DEDFE38413AD36A7B551FDC19E0D3DFD8F0A3A8C2`; the NSIS installer is 22,804,113 bytes with SHA-256 `4C6FB9FBB7AC78733973C62A1CDDEF0DDF9DFB79C540E688715B8BF24895BC80`; the sidecar SHA-256 is `AC2141FC1944CBF4A057F2142C526D6EA228212E15FF20F7876A821A142BD614`.

The real topology proves the definition-of-done exchange through standard Reticulum with no client listener or port forwarding. Unit/integration coverage additionally proves retry-state persistence, bounded backoff/jitter, endpoint failover selection, route gravity separation, scope cleanup, DNS revalidation, and signature/ratchet enforcement. The gateway is never accepted as identity, join, manifest, message, or receipt authority.

Still-open release evidence is explicit: no physical Android install, Android↔desktop unrelated-carrier run, Android↔Android unrelated-network run, Wi-Fi/cellular handoff, suspension/process-death timing, propagation-store offline/later-retrieval topology, packet capture, battery/memory measurement, protected-tree/SQLite/log/intent/notification inspection, TalkBack/large-text/rotation matrix, production signing, or in-place production upgrade was performed. The core real harness also did not physically interrupt the access point mid-message or introduce a simultaneous nearby path; those behaviors are covered at the adapter/configuration level rather than claimed as real-topology evidence.

## Participant-hosted Internet invitations 0.2.40 verification — 2026-10-13

This increment changes the default Internet invitation from nearby-only v1 to participant-hosted v3 while retaining nearby v1 and explicitly approved access-point v2. It adds no managed service. The verification below proves canonical/security behavior and platform integration; it does not claim that a real home router or mobile carrier accepted a mapping.

- `.venv\Scripts\python.exe -m pytest service\tests -q` — **404 passed, 12 skipped**. New coverage verifies personal and workspace v3 creation/parse across raw, text, and link forms; signer/operator/inner-authority binding; tamper failure; public-endpoint policy; service hosting without a remote profile; IFAC listener/client generation; mapping cleanup and empty-listener application on close; NAT-PMP response handling; and all existing identity, ratchet, workspace, remote-profile, notification-ingress, and outbox regressions.
- Bundled Node 24 TypeScript project build — passed with no diagnostics.
- Bundled Node 24 Vitest — **116 passed across 7 files**. New coverage verifies direct-first personal/workspace creation, explicit nearby and approved-access-point choices, honest router-failure fallback, participant preview without third-party consent, v3 personal/workspace ingress routing, stale mapping-response cancellation, active-host settings and stop action, share/file naming, and the existing responsive/accessibility flows.
- Bundled Node 24 Vite production build — passed; 1,820 modules transformed. The existing single-chunk size warning remains non-blocking.
- `gradlew.bat :app:testArm64DebugUnitTest -x rustBuildArm64Debug --no-configuration-cache` — **BUILD SUCCESSFUL, 96 tasks**. Android source/JVM coverage accepts exact v3 text/raw/deep-link values, retains v1/v2 and legacy file compatibility, rejects malformed values, and registers `.meshchat-invite` without enabling SEND intents.
- `cargo check --locked` with incremental compilation disabled and debug info removed — passed from a clean generated target.
- `cargo test --lib --locked` under the same bounded build settings — **7 passed**. Native validation accepts exact v3 personal/workspace families and the new file extension while retaining command allowlisting and payload bounds.
- `.venv\Scripts\python.exe scripts\release.py verify` — passed for version **0.2.40**, repeating the 404/12 Python result, 116 frontend tests, three decoded-asset verification tests, and the content-addressed production frontend bundle. Report: `dist/reports/0.2.40/20261014T035447Z-8fdc0df7/report.json`.
- `git diff --check` — passed; only the repository's existing Windows line-ending notices were emitted.

The implementation does not call STUN, TURN, rendezvous, public-IP discovery, account, signaling, or managed relay services. Automatic candidates come from global local IPv6 or the participant's local router through UPnP IGD, NAT-PMP, or PCP. The signed invitation carries a fresh, short-lived IFAC credential; off-LAN listening remains separate from the LAN listener, is not a Reticulum transport/propagation role, and is removed with its router mapping on stop, expiry reconciliation, revocation, or clean shutdown.

Open physical gates are material: no real UPnP/NAT-PMP/PCP router, inbound IPv6 firewall, CGNAT/symmetric-NAT failure case, Windows-on-Wi-Fi ↔ Android-on-carrier exchange, Android host mode, invitation-channel share sheet, abrupt-crash lease expiry, packet capture, resource measurement, or production package was exercised. Router mapping success is not treated as independent reachability proof; the invitee remains the first external check. A 0.2.40 release artifact is not claimed by this source/test increment.

## Direct-connectivity diagnostics and home-router hardening 0.2.41 — 2026-10-14

This patch keeps participant-hosted v3 as the explicit default and adds no server, rendezvous, public-IP lookup, STUN/TURN, telemetry, account, or silent fallback. Opening an invitation dialog no longer starts hosting. The real invitation-bound listener binds first on a kernel-assigned port; only then may the service prepare direct public IPv4/IPv6, PCP, UPnP, NAT-PMP, or manual candidates. A prepared route remains unverified until an authenticated recipient attaches.

- `.venv\Scripts\python.exe scripts\release.py verify --expected-version 0.2.41` — **passed**. Python: **432 passed, 12 skipped**. Frontend: **118 passed across 7 files**. Decoded assets: **3 passed**. TypeScript project compilation and the production Vite bundle passed; the existing non-blocking chunk-size warning remains. Report: `dist/reports/0.2.41/20261014T150016Z-9fd60d56/report.json`.
- `.venv\Scripts\python.exe scripts\release.py build --platform all --expected-version 0.2.41 --skip-tests` — **passed** after the independently recorded verification run above. The immutable Windows x64 release contains a 23,711,744-byte MSI with SHA-256 `43CD1BEC710516F9F4E6323EBCD48E45DBDD66D6C19FB15CC9F6C053F47DEE8A` and a 22,982,893-byte NSIS installer with SHA-256 `57C16952BA8A402F14EA721E578467FD3C93CB43932ADB1126BECCEEACF581C0`. The immutable Android ARM64 debug APK is 46,964,796 bytes with SHA-256 `F454870743360A64A7002C4209EC1F923E95DF44FF72A00989910177D3E4DBF4`. Build report: `dist/reports/0.2.41/20261014T151006Z-cadc469f/report.json`.
- Package inspection confirmed Windows application `FileVersion` and `ProductVersion` 0.2.41 plus exact sidecar matching. Android `aapt2` inspection confirmed package `com.meshchat.mobile`, version code 2041/name 0.2.41, API 24/36, ARM64-only native code, backup disabled, cleartext disabled, and the embedded third-party notice. `apksigner` verified the APK v2 debug signature and `zipalign -c -v 4` passed. This is a debug-signed sideload artifact, not a production-signed release.
- New service coverage exercises selected Windows default routes across physical/VPN/Hyper-V/APIPA/disconnected interfaces; public/RFC1918/shared/ULA/special-use classification; stable active-route IPv4/IPv6 selection; source-bound SSDP; IGD2 any-port mapping and IPv6 pinholes; UPnP fault classes; PCP/NAT-PMP retransmission, result codes, secure nonces, epoch/uptime regression, renewal, and cleanup; kernel-bound listener allocation; listener/firewall failures; manual v3 invitations; DNS-before-probe validation; sanitized diagnostic IPC; prepared-versus-authenticated state; and redacted snapshots.
- New renderer coverage proves explicit prepare, no silent nearby or first-access-point selection, unshared-host cleanup, manual-forward guidance, `participant_direct` route display, prepared wording, effective workspace-host expiry, and safe per-candidate failure reporting. Desktop and Android use the same React/Python implementation and command allowlist.

No physical networking claim is made by this automation. A Windows device on ordinary home Wi-Fi and an ARM64 Android device on cellular must still exercise real PCP/UPnP/NAT-PMP routers, directly assigned IPv4, native IPv6 and router/host firewall policy, the Windows elevation prompt and cleanup, manual forwarding, mapping renewal, router reboot/address change, invitation expiry, timeout/refusal/no-IPv6-route results, and an authenticated Personal/workspace exchange. Provider/shared NAT, unconfigurable upstream NAT, and restrictive ISP/enterprise firewalls can remain impossible without provider/router cooperation or an explicitly selected participant-operated access point.

## Immutable package rebuild 0.2.42 — 2026-10-14

Version 0.2.42 contains the tested 0.2.41 direct-connectivity implementation with synchronized release metadata. The patch version was advanced because the immutable publisher correctly refused to replace the already-published 0.2.41 package bytes during a fresh build.

- `.venv\Scripts\python.exe scripts\release.py build --platform all --expected-version 0.2.42` — **passed**. Python: **432 passed, 12 skipped**. Frontend: **118 passed across 7 files**. Decoded assets: **3 passed**. TypeScript, production Vite bundles, Windows packaging, Android packaging, and immutable publication passed. Report: `dist/reports/0.2.42/20261014T155828Z-b181d35e/report.json`.
- Windows x64 MSI: 23,711,744 bytes, SHA-256 `9D9B8FFA80766C142BED3C0B605523AD01D52B6BA8D391E534CFC220CB5D0E89`. Windows x64 NSIS: 22,982,966 bytes, SHA-256 `8825638DC1037015CA860AACF37C6D5617B8A8D733ED89BC65FA4B2E607AE428`.
- Android ARM64 debug APK: 46,964,796 bytes, SHA-256 `A25435832164A10EE50A143C5607BFF2BF3ABCB1262A2FD86643DCF041DE1B84`. `aapt2` confirmed package `com.meshchat.mobile`, version code 2042/name 0.2.42, API 24/36, and ARM64-only native code. `apksigner` verified its v2 Android Debug signature; `zipalign` and embedded-notice inspection passed.
- The build report records the source as dirty because the approved 0.2.42 version/documentation update was intentionally not committed before packaging. No application code changed after commit `1a099e481f3bac30e818324f7516048df9fc3b0a`; no install, launch, physical-network test, production signing, push, or publication outside the local immutable artifact directories is claimed.

## Acceptance matrix

| Gate | Current evidence |
| --- | --- |
| No infrastructure | Config and code automated; direct TCP-only two-process harnesses passed both bidirectional-hint chat/group/chat and phone-shaped outbound-client/no-listener direct chat without a relay; two-device disconnected-LAN packet capture not yet run |
| Real mesh | Protected four-process A→B→C→D run passed with exactly three reported hops |
| Intermediate confidentiality | B/C persistent-file marker scan passed; process-memory inspection not yet run |
| Offline propagation | Adapter implemented; end-to-end offline retrieval not yet proven |
| Propagation independence | Not yet proven |
| Unavailable path | Durable state, contained route failure, dirty-route marking, and later-send recovery unit-covered; isolated real-peer recovery run pending |
| Cryptographic mode policy | Invitation binding and recipient-ratchet gating passed in the real path; altered-ciphertext full-path test pending |
| Receipt semantics | Mapping, validation, and packaged IPC covered; crash matrix pending |
| Group cryptographic documents | Canonical document and payload validation unit-covered; independent review and hostile-input fuzzing pending |
| Group fan-out and receipts | Three-endpoint in-process simultaneous-invite/catch-up plus invite/join/chat/receipt flows passed; real two-process bidirectional-hint invite/join/message and post-group direct chat passed; real 3/5/8-device direct and propagated runs pending |
| Group membership changes | Service-level remove, signed leave, terminal close, accepted-invite replay rejection, reversed epoch catch-up, and old-epoch equivocation suspension passed; partitioned real-device removal, owner-loss, and upgrade runs pending |
| Group history boundary | No-backfill behavior requires service integration and encrypted-profile marker scans |
| Duplicates/order | Logical mutation deduplication implemented with a bounded encrypted response journal; one-to-one approval commits and submits exactly one durable `CONTACT_ACCEPT`; direct-message retries correlate native attempt IDs and reject stale callbacks while retaining stronger endpoint evidence; native callbacks are deferred outside upstream locks, retry records yield to live commands, and renderer duplicate-submit/stale-draft ordering regressions are present; broader network fault-injection run pending |
| Crash consistency | Transaction boundaries implemented; kill-point matrix pending |
| At-rest protection | Encrypted-record scan, Windows protected topology/sidecar, and mobile Token round-trip tests passed; macOS/Linux adapters unit-covered, Android device and iOS native full-tree scans pending |
| Isolation/process safety | Config and IPC parser covered; local hostile-process run pending |
| Abuse/limits | Static caps implemented; stress/flood run pending |
| Emoji reactions | Direct, group, and announcement-channel authorization, encrypted durability, bounds, replay/tombstone behavior, old-peer compatibility, and desktop/mobile renderer behavior passed coverage. The 0.2.11 local artwork mapping covers 253/253 picker choices and partitions the full catalog into 3,944 sprites plus 19 named fallbacks; all 12 artwork/metadata/license files were decoded and matched in the final Windows and Android binaries. Physical Windows↔Android/iOS rendering validation remains pending. Delivery is best effort after authenticated endpoint evidence and same-revision equivocation is first-seen-wins |
| One-to-one approval | Always-on deterministic full flow and prior real bidirectional-hint Reticulum/LXMF runs passed; the phone-shaped harness covers phone-first delivery followed by the desktop reply on the same connection. Exact 0.2.12 physical Windows↔Android validation remains pending |
| Contact management | Rename, verification toggling, block/unblock trust restoration, deletion cleanup, active-group identity retention, pending-group-invitation refusal, search, confirmations, mobile Back handling, and responsive dialog layout are covered. The shared UI was matched inside the exact Android APK; physical desktop/phone interaction remains pending |
| Reconnection/interoperability | Upstream format preserved; bidirectional direct-LAN attachment, dirty-route retry, signed-client route replacement, deferred callback re-entry, and phone-shaped full-duplex return traffic are covered; reference-client and suspend/resume runs pending |
| Platform packaging | Windows x64 0.2.42 MSI/NSIS and Android ARM64 debug 0.2.42 packages were built, hashed, and inspected; exact application/sidecar versions, API 24/36, ARM64-only native code, `POST_NOTIFICATIONS`, backup/cleartext policy, APK v2 debug signature, ZIP alignment, and the embedded notice verified. Neither app nor installer was launched. Physical Windows↔Android direct-connectivity/lifecycle/notification validation, macOS/Linux/iOS native package runs, and production signing remain pending |
| First-message usability | 0.2.12 retains desktop timeout guidance, exact draft preservation, callback/retry concurrency regressions, and the phone-first/desktop-reply harness together with durable-result, bounded-draft, duplicate-submit, IME, stale-refresh, delivery-state, and responsive-layout coverage. Exact 0.2.12 physical Windows↔Android validation and a broader human study remain open |
| Invitation entry points | UI and validation implemented; installed-app OS matrix pending |
| Common flow without technical setup | UI implemented; fresh/returning human run pending |
| Connection help | State/action mapping implemented; recovery scenarios pending |
| Accessible joining | Labels, focus, keyboard, contrast and live regions implemented; assistive-tech audit pending |
| Workspace increment 3 | Increment 2 coverage remains green. Public-channel signed chains, paged summaries/fetches, explicit incomplete discovery, duplicate names, policy enforcement, management transfer/recovery/archive, subscriptions, unread persistence, reversed controls, channel-scoped forks, Tauri allowlisting, and manager/member UI denial paths are automated. Isolated and direct-LAN process topologies plus the immutable packaged sidecar passed; physical eight-install restart/kill-point/partition runs and a native-window walkthrough remain release gates |
| Workspace increment 5 | Increment 4 coverage remains green. Deterministic participant-only workspace DMs, canonical authorization, independent encrypted local state, bidirectional delivery, hide/reopen, restart, removal gating/cancellation, desktop command allowlisting, and Contacts isolation are automated. Isolated, direct-LAN, packaged-current, and 0.2.9 compatibility paths passed; physical multi-install DM partition/reconnect, native-window, and plaintext-scan gates remain open |
| Workspace increment 6 | Canonical edits, author deletion tombstones, per-member/per-emoji reactions, inactive tombstones, target/base revision binding, deterministic concurrent resolution, same-device equivocation freeze, out-of-order pending/drain, restart durability, current/historical audience authorization, posting-policy independence, desktop command allowlisting, and public/private/DM renderer/service paths are automated. Immutable package verification passed; physical concurrent-device partition/reconnect, native-window interaction, packet capture, and protected-profile plaintext scanning remain release gates |
| Workspace increment 7 | Canonical structured mentions, exact audience authorization, edit add/remove/re-add semantics, encrypted mention index/paging/read/mute/draft state, unsubscribed-public delivery, private/DM isolation, stale-index and stale-draft filtering, desktop command allowlisting, and compose/edit/inbox renderer paths are automated. Protected topology, direct-LAN, immutable packaged-current, 0.2.9 compatibility, and final artwork verification passed; physical concurrent-device mention partition/reconnect, native-window accessibility, packet capture, and protected-profile plaintext scanning remain release gates |
| Workspace increment 8 | One-level signed-root replies, non-thread canonical-byte compatibility, exact public/private/DM authorization, nested-reply rejection, mutations/reactions/mentions/tombstones, deterministic out-of-order recovery, encrypted bounded paging/activity/read/draft/cursor state, metadata-only startup summaries, current-access and private re-admission filtering, desktop command allowlisting, mentioned-thread navigation, reply composition, and thread-specific unread behavior are automated. Protected topology, direct-LAN, immutable packaged-current, frozen 0.2.9 compatibility, and final artwork verification passed; physical concurrent-device thread partition/reconnect, native-window accessibility, packet capture, and protected-profile plaintext scanning remain release gates |
| Workspace increment 9 | Signed cooperative 30/90/365-day or indefinite retention, bounded encrypted history/revision/tombstone indexes, stale-cursor invalidation, restart-safe pruning, seven-day live-delivery preservation, durable floors and gaps, replay-resistant retired event IDs, historical/current entitlement checks, former-member read-only archives, and desktop retention/history/prune states are automated. The reproducible 50,000-event benchmark, protected topology, direct-LAN, immutable packaged-current, frozen 0.2.9 compatibility, and final artwork verification passed; physical concurrent-device retention/prune partition/reconnect, native-window accessibility, packet capture, protected-profile plaintext scanning, production signing, and in-place installation remain release gates |
| Workspace increment 10 | Encrypted workspace-keyed exact-token search, bounded shard/candidate/result execution, authenticated query/access/retention/search cursors, incremental atomic mutation updates, restart-safe migration, current plus historical authorization, private-era and DM isolation, honest indexing/pruned/incomplete states, desktop filters/navigation, and SQLite plaintext absence are automated. The reproducible 50,000-event benchmark, protected topology, direct-LAN, immutable 0.2.30 package, frozen 0.2.9 compatibility, and final artwork verification passed; physical concurrent-device access/retention partitions, native-window accessibility, packet capture, protected-profile plaintext scanning, production signing, and in-place installation remain release gates |
| Workspace increment 11 | Canonical signed history requests/responses, bounded streams/ranges/pages/bytes, replay-safe continuation binding, prerequisite controls, signed author checkpoints, removal commitments, encrypted restart-safe jobs/caches/nonces/coverage, direct indexed disclosure, exact canonical-byte acceptance, public/private-era/DM authorization, honest complete/peer-limited/pruned/permanent-gap states, scheduling bounds, erasure, desktop status/actions, and command allowlisting are automated. The reproducible 50,000-event benchmark, protected topology, direct-LAN, immutable 0.2.31 package, frozen 0.2.9 compatibility, and final artwork verification passed; physical concurrent-device partition/removal/re-admission, hostile peer fault injection, native-window accessibility, packet capture, protected-profile plaintext scanning, production signing, and in-place installation remain release gates |
| Workspace increment 12 | Effective owner/admin/member roles, exact role-aware channel/posting/invitation-request policies, signed bounded owner-approved invitation/removal/role requests, exact one-member manifest transitions, sealed indexed lifecycle/replay/audit state, owner-offline channel operation, private/DM isolation, accessible owner review/outgoing history, demotion enforcement, and command allowlisting are automated. The reproducible 50,000-event benchmark, protected topology, all direct-LAN scenarios, immutable 0.2.32 package administrator flow, exact 0.2.31 and frozen 0.2.9 compatibility, and final artwork verification passed; physical concurrent-device admin partitions, hostile request floods/fault injection, native-window accessibility, packet capture, protected-profile plaintext scanning, production signing, and in-place installation remain release gates |
| Workspace increment 13 | Canonical authority offers, exact successor acceptances, final predecessor-authority manifests, same-owner rotation fixtures, exact ownership/role cutover, atomic local and staged remote #general recovery, old-authority rejection, successor manifest authority, bounded eight-step invitation proofs, fork suspension, permanent-loss freeze diagnostics, encrypted lifecycle state, desktop confirmation/review, and command allowlisting are automated. The reproducible 50,000-event benchmark, protected topology, all direct-LAN scenarios, immutable 0.2.33 package workflows, exact 0.2.32/0.2.31 and frozen 0.2.9 compatibility, and artwork verification passed; physical concurrent-device authority partitions and kill points, hostile transition floods/fault injection, native-window accessibility, packet capture, protected-profile plaintext scanning, production signing, and in-place installation remain release gates |
| Workspace increment 14 | Fresh per-device identities, sponsor/new-device countersignatures, exact authority admission, three-device/24-destination caps, authority-endorsed historical channel checkpoints, sender-other-device fan-out, per-person/per-device delivery detail, bounded canonical history recovery, optional exact-head same-member read hints, nonauthority lost-device removal, terminal revocation state, desktop review/removal UI, deep links, and command allowlisting are automated. The reproducible 50,000-event benchmark, protected topology, all direct-LAN scenarios, exact immutable 0.2.34 package workflow, exact 0.2.33/0.2.32/0.2.31 and frozen 0.2.9 compatibility, and artwork verification passed; physical concurrent-device partitions/replacement, hostile link floods/fault injection, native-window accessibility, packet capture, protected-profile plaintext scanning, production signing, and in-place installation remain release gates |
| Workspace increment 15 | Increment 14 linking is unchanged and now available through the mobile UI. Atomic durable local-notification decisions, bounded service-to-native work, permission/denial/settings recovery, sealed preview and conversation preferences, structured mention/thread precedence, opaque re-authorized routes, lifecycle generations, bounded overflow/resume reconciliation, restart deduplication, and historical-storm suppression are automated. The final 50,000-event benchmark, protected topology/direct-LAN matrix, exact immutable 0.2.35 desktop/Android packages, 0.2.34/0.2.33/0.2.32/0.2.31 and frozen 0.2.9 compatibility, APK/source markers, and artwork checks passed. No authorized Android device or macOS/iOS environment was available, so physical lifecycle/permission/lock-screen/upgrade evidence remains a blocking completion gate |

Do not mark a release complete from unit tests alone. Store packet captures, topology configs, full-tree scans, package hashes, platform versions, human timing sheets, and failure notes with the release evidence.


The controlled direct-fabric topology also verifies live admitted-member revocation:
after bidirectional messages and receipts, the owner removes the peer and its
adapter goes offline while the carrier remains running, without reactivation.
The source topology passed (1 passed, 2 native-only tests skipped). Windows/Linux
native tests and Android ARM64 compilation passed at `88094ec` in
[run 38928825216](https://github.com/ahouchens/mesh-chat/actions/runs/38928825216).
Authority is polled every 250 ms. The subsequent increment below adds automatic
controller-driven native cancellation.
This does not qualify shipping revocation or pending-invitation lifecycle integration.


Automatic revocation cancellation passed at `7bce7d9` in
[run 38929519471](https://github.com/ahouchens/mesh-chat/actions/runs/38929519471):
Windows/Linux native tests and Android ARM64 compilation. The topology requires
the native process to exit successfully after member removal before explicit
cleanup. A dedicated process event carries revocation independently of packet
queues; a source test verifies cancellation with full queues. Local validation:
2 passed, 2 native-only skips. Shipping IPC and pending-invitation lifecycle
integration remain open.


Carrier-loss delivery with full packet queues passed at `3f159e7` in
[run 38930632785](https://github.com/ahouchens/mesh-chat/actions/runs/38930632785)
on Windows/Linux native CI and Android ARM64 compilation. Dedicated process
events retire workers independently of packet capacity, including EOF and repeated
close. Source validation: 3 passed, 2 native-only skips.


Owner Ready persistence passed 6 targeted authority tests and 112 direct-boundary
tests locally. Windows/Linux native tests and Android ARM64 compilation passed at
`15c002e` in [run 38931048072](https://github.com/ahouchens/mesh-chat/actions/runs/38931048072).
Coverage includes selected-chain/certificate mismatch, failed writes, restart,
replay, expiry, revocation and child-document invalidation without resetting replay history.


The retained-Answer Ready topology and native expiry probes passed on Windows/Linux,
with Android ARM64 compilation, at `fa5186e` in
[run 38931467624](https://github.com/ahouchens/mesh-chat/actions/runs/38931467624).
The owner refreshes native credentials; the joiner retains its original Answer
socket/key and re-arms only after durable Ready acceptance. Source topology and
controller checks also pass. This remains a controlled proof, not shipped email setup.


Crash and native control rejection qualification passed at `42d85ca` in
[run 38931951270](https://github.com/ahouchens/mesh-chat/actions/runs/38931951270):
Windows/Linux native tests and Android ARM64 compilation. Real topologies inject
service and native-engine kills after messaging and require surviving services
to retire adapters before cleanup. Native Ready rejects conflicting Answer digests,
wrong generations, repeated refresh, early packets and oversized frames. Source
revocation/service-crash cases and controller tests passed (5 passed; 10 native-only
cases skipped locally).

Service-owned admitted leases, dead-process stream cleanup, and controlled fresh
recovery after suspension/restart passed on Windows/Linux native CI and Android
ARM64 compilation at `956e3c9` in
[run 38934040766](https://github.com/ahouchens/mesh-chat/actions/runs/38934040766).
These use known controlled paths and a test coordinator, not automatic discovery.

Pending joiner leases now check the exact saved exchange and current join authority.
Source tests cover certificate substitution, saved-chain replacement, admission,
suspension, shutdown and a retirement race during registration. The non-integration
suite passed: 614 passed, 7 environment-dependent skips, 19 integration deselections.
The source topology/controller suite passed: 8 passed, 10 native-only skips,
including revocation, service crash, suspension/resume and process restart.
The real topology now requires automatic pending-carrier cancellation after
admission and finishes channel bootstrap over fresh admitted credentials. Native
qualification passed on Windows/Linux with Android ARM64 compilation at `ec482d0`
in [run 39042273906](https://github.com/ahouchens/mesh-chat/actions/runs/39042273906).
Owner pending lifecycle and shipping
IPC are still open; these results do not qualify physical mobile lifecycle behavior.

The adapter/policy and packet-pump lifecycle now run from the protected service
package. New tests cover authority rejection/errors, broken channels, EOF, carrier
loss, health failure, full outgoing queues, competing readers, retained capacity
for blocked workers, cancellation before queued-packet delivery, and deferred
vault closure during a running authority callback. The controlled topology uses
the service pump and profile budget. It creates pumps at activation, so reopening
a suspended profile can complete startup before the explicit foreground transition.
Local validation passed: 625 non-integration tests, 7 environment-dependent skips,
19 integration deselections; source topology/controller suite 8 passed, 10
native-only skips. Windows/Linux native qualification and Android ARM64 compilation
passed at `b0f0962` in
[run 39043434010](https://github.com/ahouchens/mesh-chat/actions/runs/39043434010).
This does not enable shipping
native IPC or default direct interfaces.

### Direct-connectivity Phase 1 completion

The roadmap's controlled protocol-and-adapter proof is complete at `de110a8` in
[run 39072458622](https://github.com/ahouchens/mesh-chat/actions/runs/39072458622).
Both Windows and Linux passed 158 service-boundary tests, 10 workspace/pending
authority tests, 11 native unit tests, 1 cross-language certificate-binding test,
and 25 native topology/controller tests. Android ARM64 compilation passed.
Local validation passed 639 non-integration tests (7 environment-dependent skips)
and 11 source topology/controller tests (14 native-only skips).

New qualification includes an independent local UDP injector before/after TLS,
both deterministic QUIC client roles including retained-Answer Ready refresh,
per-scope runtime deduplication and inherited channels capped below 64 KiB payload.
The full Linux native topology ran under `strace -f`: the endpoint-free report
records 0 external addresses, 1264 loopback address observations and 1040 network
send calls. The checker rejects non-loopback attempts even if they fail, undecoded
Internet endpoints, raw network sockets and named local proxy connections.
See [the retained report](https://github.com/ahouchens/mesh-chat/actions/runs/39072458622/artifacts/12115383045)
and the [criterion-by-criterion evidence](docs/DIRECT_CONNECTIVITY_PHASE1_EVIDENCE.md).
This is controlled-run evidence, not a shipping feature, Windows network capture,
physical Android test, Internet traversal measurement or production IPC approval.

## Phase 3 atomic relationship increment

`service/tests/test_direct_relationship.py` exercises encrypted atomic
acceptance, restart/rotation/replay, prior-floor migration, concurrent conflicts,
revocation/scope/expiry checks, storage failure and stale success callbacks.
The source and shipping-native setup pipelines assert matching durable
relationship and signed-RNS route evidence after bidirectional message receipts.
No test treats this as restart or network-switch recovery. Full remaining
criteria and exact-commit results belong in the
[Phase 3 evidence record](docs/DIRECT_CONNECTIVITY_PHASE3_EVIDENCE.md).


## Phase 3 production recovery qualification

The current suite extends the historical acceptance increment above:

- `test_direct_recovery.py`: current RNS authority, encrypted capsules, replay and
  pause, generation reservation failure, stale callbacks, bounded fair scheduling,
  cleanup evidence, distinct liveness signals, and replacement failures before/after
  native authorization and vault confirmation.
- `test_direct_recovery_candidates.py`: same-socket renewal, changed actual tuples,
  shortened leases, failed renewal, ownership loss, retirement during router I/O,
  durable-write failure, cleanup, and bounded saved-port binding during QUIC drain.
- `test_direct_recovery_pipeline.py`: CI-only real QUIC through the shipping native
  dispatcher with separate RNS service processes and encrypted profile reopening.
  Scenarios cover client/server/both process death, suspension/resume, concurrent
  replacement, route change, blocked targets and lost hints/manual signed updates.
  Tests check fresh keys where required, unchanged identities/member/device IDs,
  no duplicate admission, queued logical IDs, bidirectional endpoint receipts and
  zero retained native/interface resources after explicit pause.
- Rust recovery tests enforce preauthorization packet rejection, wrong exporter
  rejection, both-service approval, certificate rotation, client migration, server
  migration rejection, original ownership/arming expiry and recovery via the
  remaining known address.
- Renderer tests separate liveness from receipts and exercise workspace-bound import,
  fresh-only export, verification failure and pause/resume controls.

Native/frontend/package execution remains GitHub Actions only. Linux production
recovery runs under the existing no-external-address syscall audit. Exact tested
SHAs, results and unresolved limits are in
[the Phase 3 evidence record](docs/DIRECT_CONNECTIVITY_PHASE3_EVIDENCE.md).

Physical qualification remains separate. On the Windows/Android pair, preserve
the existing admission and queue a message before restart, sleep, process kill,
and each network switch. Record the unchanged member/device and message IDs,
fresh authentication after ownership loss, and actual endpoint receipts after
restoration. Test each side moving independently, then both losing their known
addresses and exchanging explicit connection updates. Capture router lease
renewal/cleanup and foreground battery/traffic evidence; compilation and loopback
tests cannot establish those results. Do not infer Android background availability.

## Invitation recovery explanation — 0.2.49

Saved-workspace invitation previews report why recovery is unavailable without
replacing the original signed request. Backend regression cases cover changed
invitations, stopped/expired delivery and identity mismatches; renderer cases
check the changed-invitation and stopped-request explanations.

Validation: 127 focused Python tests (workspace join retry, receipt, service and
email direct routing), 151 renderer/API/invitation tests, TypeScript app check,
and release version consistency check passed. A browser fixture using the actual
stylesheet confirmed vertically stacked warning content and no section/dialog
horizontal overflow at widths 360, 393 and 591px; the 393px render was inspected.
This fixture is a layout check, not Android device qualification. Cellular join
receipt and owner approval remain unverified on the physical devices.

## Windows single-stack route detection — 0.2.50

Query all Windows routes and filter active default prefixes in the pipeline.
Get-NetRoute's multi-prefix lookup previously terminated when IPv6 had no default
route, discarding a working IPv4 route. Reproduced the original missing-IPv6
error on Windows; the corrected query returned the active Wi-Fi IPv4 route.

Validation: 38 connectivity-roadmap and participant-invitation tests passed,
including two Windows PowerShell regressions for IPv4-only and IPv6-only route
tables with unrelated and inactive routes. Tests execute the production pipeline
against a Get-NetRoute fixture reproducing absent-prefix errors. This establishes
route detection, not successful router mapping or physical cellular delivery.

