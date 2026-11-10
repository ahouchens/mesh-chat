# Private packaged qualification control

Windows: launch the retained sidecar with sole flag
`--qualification-native-webrtc`. Use its existing private length-prefixed IPCv1
initialize envelope, with exact payload `profile_dir`, `vault_key` (base64),
`parent_pid`, `display_name` (literal `Mesh qualification`). The absolute profile
leaf must start `mesh-qualification-` under a controller-owned protected parent.
First boot requires a nonexistent leaf. After platform protection and successful
initialization, a local marker authenticates the path and a random nonce with
that vault key. Only the same marked path/key may reopen. An existing ordinary
vault, copied marker, wrong key or tampered marker fails before runtime startup.
Do not retain this key or marker in qualification artifacts.

Private commands are `qualification.inventory` with `{}` and
`qualification.path_evidence` with `{logical_session,expected_physical,sample_request}`. Replies
use the existing IPC `{type:"response",id,ok,result|error}` envelope. The latter
calls the production inspector with exact current resource fencing. These names
are absent from public Core, native commands and ordinary sidecar dispatch.

Android: actual host-UID instrumentation first calls
`NativeWebRtcBridge.attach(context)`, then directly imports the packaged
`mesh_chat.core_api.qualification_host` via Chaquopy. `android_initialize(raw)`
accepts exact JSON `{profile_dir,vault_key,display_name:"Mesh qualification",platform:"android"}`.
`android_control(raw)` accepts exact `{command,payload}` using the names above.
Both return JSON `{ok,result|error:{code}}`, check actual Binder calling UID
against process UID, and are outside all renderer/Core/mobile-command routes.
Initialization refuses an existing live runtime; shutdown through the normal
trusted host path before reopening. Control is fenced to the exact initialized
mobile instance. Ordinary host replacement cannot inherit qualification access.

Inspectors enforce their production 2-second sample deadline and 16KiB bound.
The controller generates a fresh 16-byte random `sample_request`, encoded as
exactly 32 lowercase hexadecimal characters, for each existing sampling call.
The private service forwards it to the native sampler and requires its exact
echo before accepting the observation or advancing the sequence. The native
coroutine or callback binds the challenge to that sampling invocation; neither
the service nor a wrapper may attach a new challenge or timestamp to cached data.
Missing or mismatched challenges and old private shapes fail closed.

The producer checks the original capture's age in its own monotonic clock
domain. Android encodes the original capture relative to its adapter's clock
origin. The controller treats `sampled_at_ms` as bounded opaque metadata, never
as a wall-clock timestamp or a tick count comparable to another device. It
requires the matching challenge, its own monotonic request-to-consumption span
of at most two seconds, the existing service elapsed bound and a 2000ms validity
window. Integer rounding must not extend the producer's deadline. These checks
bind freshness to the current invocation without synchronizing clocks or adding
another sampling call; they do not reinterpret internal WebRTC metric clocks.

Recheck service/profile/adapter/resource epoch
and sample sequence; discard after resource or epoch changes. Selected ICE alone
does not prove readiness or delivery. Restrict raw endpoint tuples to transient
controller memory/fault correlation; export only categories, availability,
hashes and truthful counters. Never export SDP, credentials, bearer documents,
vault keys or raw addresses. Unit admission tests are not packaged OS evidence.

The owner-retirement follow-up is implemented and source-reviewed, but full native
qualification is pending. Its private
`qualification.retire_carrier` request has exactly `operation_id`, `request_id`,
`logical_session`, `expected_physical`, `expected_service_incarnation` and
`expected_adapter_epoch`. The pairing operation identifies this caller's existing
transferred case; request and epoch values compare against current trusted state
and do not confer authority. The request nonce is 32 lowercase hexadecimal
characters. Current synthetic-profile/key, caller, service, identity, host and
owner bindings are rechecked. Source/run verification remains in the trusted
controller launch; the profile marker does not attest a source SHA or run.

An accepted request installs a temporary owner hold and invokes normal supervisor
retirement. It does not persist Stop, change consent, bypass the managed-close
guard or call native disposal directly. Failed cleanup retains the hold and
existing retry behavior. Only a real successful cleanup completion followed by
fresh, revision-checked removal of the old bindings may clear that hold; real
Stop, quarantine and authority-change fences remain independent.

Existing inventory polls may use exactly `{operation_id,request_id}` to obtain
the ordinary inventory plus `carrier_retirement:{request_id,state}`. State is
`pending` or `acknowledged`; ordinary inventory `{}` remains unchanged. Per-case
success requires matching acknowledgment in the same service/profile scope,
empty logical inventory and complete zero native lease counts. The retained
case records `owner_retirement_acknowledged:true`, not the private request or
resource identifiers. No additional poll, deadline or retry is introduced.
Terminal cleanup instead uses the current scoped Core `connection.stop`, followed
by the same zero-accounting checks and normal host shutdown. Its desired-state
reply is not cleanup completion. Full native qualification remains required.

The cold-start setup follow-up is implemented and source-reviewed. After the final manual
acknowledgment/zero gate, each peer performs the existing local auto-reconnect
consent update, publishes its returned signed capabilities in the sealed
`reconnect_capabilities` setup phase, then receives and imports the peer's document.
The phase accepts exactly `{capabilities:<nonempty string>}`, at most 16KiB of
UTF-8 text and within the existing 48KiB canonical plaintext bound. Other setup
schemas, envelope provenance, expiration and one-shot rules remain unchanged.
Both peers publish before receiving. Each must persist the import through the
existing signature/recipient/expected-peer validation and check the same contact,
profile and device association plus mutual consent before its own first crash.
Publishing alone is insufficient. Capability plaintext contains credentials and
must not appear in retained reports or logs. Manual cases keep consent disabled;
the cold-start workload, deadlines and receipt requirements remain unchanged.

This adds one setup artifact per role: full Windows uses ten setup artifacts plus
one final report, Android eight plus one; quick mode uses four plus one each.
The run inventory bound remains 100. GitHub's
[artifact platform release](https://github.blog/changelog/2024-02-12-github-actions-artifacts-v4-is-now-generally-available/)
and [current upload action documentation](https://github.com/actions/upload-artifact#number-of-artifacts)
document 500 artifacts per job. The toolkit README's conflicting ten-artifact
wording is retained in the audit; lock-verified SDK 6.3.1 upload/client/config
source showed no ten-artifact guard. No SDK or workflow update is required.

The `902b12d` full qualification run `42796005344` executed all 18 native-path
JVM controls (71 JVM cases overall), all 52 required Android emulator cases and
the installed Windows platform suites successfully. Its cross-platform native
Android role failed earlier at checked `adb root` preflight; the original cause
is unknown because command output was not retained. These passing component/
platform results do not qualify the full Windows–Android sample/receipt matrix.

The later `1b3a2be` full run `42802755780` passes 4,563 policy cases,
1,130 Python UI plus 12 rendered cases, nine Windows boundary cases, installed
Windows bootstrap, 52 Android emulator and 71 JVM cases, and all controlled
direct suites. Installed Windows public pairing fails; final cleanup masks the
original work failure. Native interop is skipped, so no current pairing,
shared-host lifetime or Windows–Android acceptance is inferred from this run.
The earlier Windows lifetime pass remains bound to `902b12d`.

The later `c0b3cf7` full run `42810308484` passes 4,651 policy cases,
1,130 Python UI plus 12 rendered cases, nine Windows boundary cases, installed
Windows bootstrap/public pairing/two receipts and same-app lifetime checks,
52 Android emulator and 71 JVM cases, and all controlled direct suites. Native
Windows fails at `rendezvous_receive` / `approval_acknowledgment` with
`RendezvousUnavailable`; Android fails during `direct_authenticated_receipts`
with `PeerFailure` / `scenario_deadline`. Windows reached initial local readiness
validation, but that is not retained scenario-specific sample/receipt acceptance.
The exact transport branch is unrecorded. Full native qualification and isolated
helper retirement remain unfulfilled; no timeout/retry/authority relaxation is
authorized by these passing component/platform checks.

Checkpoint `5e6d0da` full repeat `42824231976` passes all non-native suites,
including 4,760 policy, 1,239 Python UI plus 12 rendered cases, installed Windows
pairing/lifetime, 52 Android emulator and 71 JVM cases. Both actual native roles
fail at `direct_native_lease_retirement` with a scenario deadline. The compatibility
native close is deliberately non-authoritative for adopted supervisor-owned
carriers (`state:managed`); the controller ignores that reply before waiting for
zero leases. Existing protected owner Stop has durable later-admission consequences.
The guard, exact-resource custody and strict empty accounting must remain intact;
no full native or isolated-helper qualification is established by this checkpoint.

Checkpoint `36466e0` full run `42843336931` verifies 5,066 policy cases,
1,482 Python UI plus 12 rendered cases and the Windows/Android platform suites.
General verification fails two composition fixture setups before their test
bodies; native interoperability is skipped. The fixture bypasses production
serialization during consent/control setup. Reviewed fixture-only correction
`c4e6036` closes that finding; 18 local controls pass, including two deterministic
signed-capability races. Fresh full qualification is pending.
This run supplies no packaged owner-retirement or cold-start native acceptance.
