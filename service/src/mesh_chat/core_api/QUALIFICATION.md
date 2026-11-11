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

The private v2 owner-retirement producer `3172d02` and controller `b3751ae`
are implemented and source-reviewed together at `6459710`. Reviewed composition
`ce4b9c4` passes 28 controls with actual Windows localhost native hosts for both
role labels, including late commit and raw closed delivery after mapping release.
Approval/Reticulum boundaries remain modeled. This is not Android/JNI, full
controller/path-case or packaged acceptance. Combined local qualification at
`30c9e4d` passes 5,311 policy cases, 1,657 Python UI + 12 rendered cases, nine
Windows boundary cases and all 28 composition controls. Full run `42886878229`
passes all non-native families but fails native initialization: Android reports
`PeerFailure/internal`, Windows later `RendezvousUnavailable`. The phase spans
several setup calls and the initial key exchange; the failing Android operation
and inner cause remain unidentified. No full native acceptance is established.
Reviewed controller diagnostics `7058909` now label ten existing initialization
call sites on failure. The original exception, calls, budgets and cleanup remain
unchanged; 1,093 focused component cases pass. Labels expose no payload or raw
exception text and do not identify the SDK's implicit capability request versus
the requested Core operation. Exact-source `379e38a` local gates pass
5,406 policy cases, 1,752 Python UI + 12 rendered cases and nine Windows
boundary cases. Full run `42899863270` passes all non-native families but
fails native initialization: Android `initialize_ice_servers/internal`, Windows
`initialize_key_wait/RendezvousUnavailable`. The inner capability-versus-ICE
operation and cause remain unknown. No full native acceptance or expansion of
public SDK support follows. Private same-exchange diagnostics are integrated
from producer `c6a31bb`/`6246303` and consumer `364eb313`, with inventory
registration `a996252`. Focused evidence passes 285 producer and 903 consumer
Python cases, 24 JVM cases and 239 inventory cases. Four compiled Android
local Binder/Chaquopy controls raise the required optimized inventory to 56.
At `fed31cc`, all four pass within 54 verified Android case reports and 83 JVM
passes, but full run `42926669465` fails: the separately packaged runtime host
omits the private observation-state source and cannot compile. Independent
consumer execution and cross-platform native interoperability do not run.
Windows direct recovery separately fails its address-loss delivery wait
(nine other recovery cases pass); its cause is unestablished. The narrow
packaging correction `e552dd9` has isolated compiler RED/GREEN and 32 existing
boundary passes, independent review approval and integration at `10d08c3`.
Full run `42932168650` at `6b3fb8e` confirms the correction with 56 Android
cases, 83 JVM cases and 17 distribution hashes. Native Android then fails the
actual ICE broker open with a name-resolution observation; Windows waits for
its unpublished partner key. Separately, Windows direct recovery passes all ten
cases but two setup cases time out awaiting the joining workspace's general
channel. Neither underlying DNS configuration nor channel-delivery defect is
yet established. No full native acceptance follows. Prior full local results
retain their `fed31cc` source; targeted current-source compile and 410 boundary
cases pass.
Only fixed operation/stage/category/cause enums may accompany the same
correlated internal failure, under the original local caller and initialized
publication. Public Core responses, SDK surface, grants, call counts and
deadlines remain unchanged. This does not establish the CI failure cause. The
`qualification.retire_carrier` request has exactly `action`, `operation_id`,
`request_id`, `logical_session`, `expected_physical`,
`expected_service_incarnation` and `expected_adapter_epoch`. Action is exactly
`prepare` or `commit`; missing/unknown actions reject, with no legacy fallback
or wire abort. The pairing operation identifies this caller's existing
transferred case; request and epoch values compare against current trusted state
and do not confer authority. The request nonce is 32 lowercase hexadecimal
characters. Current synthetic-profile/key, caller, service, identity, host and
owner bindings are rechecked. Source/run verification remains in the trusted
controller launch; the profile marker does not attest a source SHA or run.

After all local measurements and successful fault cleanup, both peers prepare,
publish then receive their exact sealed case completion marker, and commit the
same immutable tuple and nonce. First preparation returns
`{request_id,state:"prepared"}` without disposing the current carrier. First
commit returns `pending`, even if normal failure cleanup has already completed.
Correlated inventory accepts exactly `{operation_id,request_id}` and returns the
ordinary inventory plus `carrier_retirement:{request_id,state}`. It may report
`prepared` before commit; postcommit polling accepts only `pending` or
`acknowledged`. Ordinary inventory `{}` remains unchanged.

Commit invokes normal supervisor retirement without persisting Stop, changing
consent, bypassing the managed-close guard or directly calling native disposal.
Failed cleanup retains the existing exact-resource retry behavior. Per-case
success requires matching acknowledgment in the same service/profile scope,
empty logical inventory and complete zero native lease counts. The retained
case records `owner_retirement_acknowledged:true`, not private request or resource
identifiers. Existing polling, deadlines and retry budgets remain unchanged.
Terminal cleanup uses the current scoped Core `connection.stop`, followed by the
same zero-accounting checks and normal host shutdown. Its desired-state reply
is not cleanup completion.

Preparation preserves current traffic and health inspection, permits normal
failure cleanup and rejects replacement admission. Only a fresh transferred
pairing context allocated by the current service is eligible. Retained proof
requires its exact owner's actual retirement, the trusted native `closed` edge,
successful cleanup completion and fresh bound clearance. Capture the raw physical
closed edge before logical mapping lookup can discard it. This uses the existing
trusted in-process callback and nonreused fresh identity, not an independently
tagged JNI receipt; restored resources are excluded. The sole permitted authority
successor changes manual-carrier authorization from true to false after an
attested exact close start. Other active-ticket authority/lifecycle changes
invalidate irreversibly. An already-completed historical receipt grants no
authority over a later generation and cannot satisfy a different request nonce.

Markers are exactly `{completed:true}` at
`case_complete_<scenario>_<initiator>` for the six fixed full cases or the first
three quick cases. Existing source/run/role binding and deadlines remain. Full
uploads including reports become 17 Windows/15 Android; quick becomes eight each,
within the unchanged run inventory cap of 100. Any failure ends the case and uses
existing owned-host teardown; forced termination is never positive retirement
proof. The frozen contract SHA-256 is
`6ca4ca2ccd4807d66e38396258f0361f8721ac0cec255ed8a73b7516dbbd3fed`.

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

Before case-completion markers, cold-start setup alone added one setup artifact
per role (Windows ten setup artifacts plus one report, Android eight plus one;
quick four plus one each). With the six full/three quick completion markers,
the current totals are the 17/15 full and eight/eight quick counts above.
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

Checkpoint `ccd3b51` has passing exact-source local SDK/types, 5,068 required
policy cases, 1,482 Python UI + 12 rendered cases, nine Windows boundary cases,
and broader local service execution (6,298 pass/49 optional-platform skips).
First full run `42857623266` fails Windows public-SDK invitation waiting and skips
native interoperability; its first cause remains unresolved. The unchanged full
retry `42862760087` passes Windows public pairing/lifetime and all non-native
gates but fails native Android under TURN TCP negative-control phase with an
unclassified `ValueError`; Windows later reports TURN TLS wait-answer timeout.
No full native acceptance, isolated-helper completion, separate-caller/process,
physical or media qualification is inferred. Coordination/diagnostic follow-up
is under review; no timeout, authority or negative-control relaxation is assigned.

Checkpoint `36466e0` full run `42843336931` verifies 5,066 policy cases,
1,482 Python UI plus 12 rendered cases and the Windows/Android platform suites.
General verification fails two composition fixture setups before their test
bodies; native interoperability is skipped. The fixture bypasses production
serialization during consent/control setup. Reviewed fixture-only correction
`c4e6036` closes that finding; 18 local controls pass, including two deterministic
signed-capability races. Fresh full qualification is pending.
This run supplies no packaged owner-retirement or cold-start native acceptance.
