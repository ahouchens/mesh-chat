# Independent public consumer qualification proposal

Status: the original proposal below is partly implemented. Public pairing
intents, normal app-owned hosts and independent distribution inputs exist.
Checkpoint `902b12d` independently verifies installed Windows bootstrap, public
pairing and two authenticated receipts; its full run `42796005344` failed native
Android root preflight. The later `1b3a2be` run `42802755780` passes bootstrap but
fails installed public pairing, with its original work failure masked by final
cleanup failure. Native interoperability was skipped. Neither run is aggregate
Windows–Android qualification. The private topology controller remains a
separate transport test.

The installed Windows lifetime slice passed at `902b12d`: two SDK sessions in one Node
application, session close/reattach, concurrent-owner refusal with positive child
exit, and original pending-message/key preservation across trusted owner
stop/reopen. It does not prove separate consumer-process exit,
caller/cross-user/multi-app isolation, isolated-helper retirement or delivery of
that pending message after restart.
Successful Android credential UI, independent cross-platform receipts, native
helper cleanup, media coexistence and the supported release matrix remain open.

The later `c0b3cf7` full run `42810308484` again passes installed Windows
bootstrap, public pairing, two receipts and the same-application lifetime slice
described above. Native Windows fails receiving the approval acknowledgment;
Android reaches a direct-receipt scenario deadline. Full cross-platform native
acceptance remains unfulfilled; these separate failures do not identify a common
cause or explain the earlier installed invitation failure. The next diagnostic
change preserves transport failure while selecting only safe origin metadata.

Checkpoint `5e6d0da` full repeat `42824231976` passes the same installed Windows
public pairing/receipt/lifetime slice plus the Android and other component suites.
Both actual native peers fail later at a direct-case native lease-retirement
deadline. The controller requests a compatibility close which deliberately returns
managed for an adopted supervisor-owned carrier. The reviewed follow-up adds
private owner retirement with correlated cleanup acknowledgment and later-case
admission, plus signed cold-start consent exchange after the final manual zero
gate. The public API, managed-close guard and strict zero-lease acceptance remain
unchanged. Combined qualification is pending; no full cross-platform or
isolated-helper acceptance follows from the component tests.

Checkpoint `ccd3b51` has passing exact-source local SDK/types, 5,068 required
policy cases, 1,482 Python UI + 12 rendered cases, nine Windows boundary cases,
and broader local service execution (6,298 pass/49 optional-platform skips).
First full run `42857623266` fails Windows public-SDK invitation waiting and skips
native interoperability; its first cause remains unresolved. The unchanged full
retry `42862760087` passes Windows public pairing/lifetime and all non-native
gates but fails native Android under TURN TCP negative-control phase with an
unclassified `ValueError`; Windows later reports TURN TLS wait-answer timeout.
No full native acceptance, isolated-helper completion, separate-caller/process,
physical or media qualification is inferred. Failure-only diagnostics `b7f323e`
are reviewed and integrated, with 739 focused component cases passing (667 prior
cases preserved plus 72 new) and three meaningful original-source failures.
An original two-controller reproduction demonstrates measurement/cleanup
overtaking under scripted native boundaries; it does not identify the CI cause.
The private prepare/completion/commit replacement contract is frozen, with
implementation, real composition proof and full qualification still pending.
No public API/grant, timeout, authority or negative-control relaxation is assigned.

Checkpoint `36466e0` full run `42843336931` again verifies the installed Windows
public-SDK pairing, receipt and same-caller lifetime slice and all required
Android component suites. General verification fails two loopback composition
fixture setups; native interoperability is skipped. A test-only serialization
correction `c4e6036` is reviewed with 18 local controls passing; fresh full
qualification is pending. These results do not expand the public-consumer or
cross-platform acceptance scope.

## Gaps observed when this proposal was written

The following observations motivated the implementation; they are historical,
not a statement that the implemented Windows host and public pairing are absent.

- The TypeScript archive and Kotlin AAR contain thin protocol clients, not an
  independently usable app-owned runtime host. The normal frozen Windows
  `--native-webrtc` mode requires a trusted initializer to provide a vault key;
  the sidecar can expose an image-authenticated pipe when its launcher asks.
- The Android example is an external UID bound to `core-api-host`. That CI host
  seeds a profile, workspace and fabricated approved contact. These are useful
  packaging/denial checks, but cannot qualify independent pairing and receipts.
- Native offer/answer admission currently exists only behind
  `QualificationControl`, with a qualification profile marker and private
  commands. The existing public signed-invitation operations do not admit that
  production native negotiation actor. `connection.start` starts reconnect for
  an existing relationship; it does not replace onboarding.
- The production Android runtime library currently has Tauri project
  dependencies and service Python source paths. The independent client build
  cannot use that project dependency as a versioned runtime distribution.

## A: public pairing intent, not a native command port

Add a bounded public pairing intent family, backed by C's existing actor:

| Operation | Request | Result and authority |
| --- | --- | --- |
| `peer.pairing_begin` | `profile`, `role: offer|answer`, optional `pairing_code` (answer only, 1..2048 UTF-8 bytes), optional `allow_direct_ip_disclosure` (boolean, default false); required caller envelope idempotency key | `profile`, caller/profile-scoped opaque `pairing` handle, `state`, `expires_at`, nullable `pairing_code`; requires current approve permission |
| `peer.pairing_query` | `profile`, `pairing` | Same selected projection, including shareable code; current approve permission plus original caller/profile binding |
| `peer.pairing_cancel` | `profile`, `pairing`; required explicit caller envelope idempotency key | Same projection; approve permission; durable cancellation of this exact intent |

Use actual actor states: reserved, offer_ready, awaiting_approval, transferred,
retiring, retired. Offer codes are shareable admission material, not SDP. An
answer must supply a code; an offer must omit it. A transferred intent remains
transferred on cancellation and cannot reclaim the adopted carrier.

Derive the actor operation UUID with the existing keyed-action namespace from
the host-derived caller, profile and caller key; never accept an internal
operation UUID or caller identity in JSON. Bind a live authorization callback
to the exact service incarnation and profile identity. Recheck authority on
begin replay, query, cancel and each asynchronous effect. Preserve the existing
actor's resync requirement after an interrupted runtime; do not invent an
automatic fresh intent. Advertise only when the concrete native actor is bound.
Bind cancellation's own caller key and input digest durably before returning
success, and recheck current authority before replay. A cancellation key cannot
be reused for another pairing target or the begin action. Replaying an accepted
cancellation must not cancel a replacement intent or an adopted carrier.
Document the actual 32-intent bound, one active onboarding intent, 300-second
maximum expiry and byte limit. SDKs must require the advertised feature and
limits, with no retries or replacement keys.

Existing public `application.snapshot`, `peer.approve` and `contact.invitation`
can supply explicit contact decisions for this first owner-app consumer. No
new public raw native, SDP, signaling HTTP, reducer-event, vault-key or grant
operation is needed. Disclosure consent remains explicit. Later reconnect uses
the existing public connection intent and consent semantics.

A file boundary: `contracts/core-api/operations-v1.json`,
`contracts/core-api/request-v1.schema.json`, `service/src/mesh_chat/core_api/requests.py`,
`session.py`, `views.py`, `pairing.py`, `service_pairing.py`, `composition.py`,
the relevant keyed-action/capability implementation, and thin helpers/types in
`sdk/typescript/src/` and `sdk/kotlin/src/main/java/com/meshchat/runtime/core/`.
A owns producer contract/authority/idempotency tests. This is an additive
experimental API feature, not an API stability declaration.

## C: ordinary app-owned bootstrap and host distribution

Windows: add a documented normal packaged host launch mode that creates/reopens
one app-owned data directory and retrieves its vault key through Windows
protection inside the runtime. The trusted launcher provides the owned directory,
unique pipe and exact client image outside public request JSON. The runtime
returns only pipe/startup status, never keys. Admit that app's owner operations
without exposing private native controls to its public SDK session. Start empty;
the app's explicit `profile.create` request creates the identity. Reuse the
existing frozen native host, same-user image authentication and exact shutdown
ownership. Do not add an unprotected network daemon or attach to the user's
installed Mesh Chat profile. Proposed C paths: a new production app-owned host
composition module under `service/src/mesh_chat/`, its `__main__.py` launch route,
and existing platform key/provider glue. Coordinate the public endpoint binding
with A's `core_api/sidecar_host.py` / `pipe_endpoint.py` ownership.

Android: provide a documented trusted host bootstrap API, for example
`MeshCoreRuntime.start(context)`, which owns that application's private directory,
Keystore wrapping and native host initialization. The app then uses the installed
Kotlin SDK against its own real Binder service/UID. Keep external packages at
their existing consumer grants. The API must not accept owner UID, grant, raw
vault key or private command in JSON. A separate versioned runtime-host AAR/POM
should package the existing production host sources, Python assets, ABI inputs
and declared dependencies without a Tauri project dependency. A small new Gradle
host module can reuse the production files; no replacement transport or service
implementation. Proposed C paths: new `MeshCoreRuntime.kt` and runtime-host module
under `plugins/tauri-plugin-mesh-runtime/android/`; existing
`NativeWebRtcBridge.kt`, `MeshCoreApiService.kt`, `mobile_bridge.py` and platform
key/provider code only as needed. C retains native-pairing/custody tests and
proves normal shutdown acknowledges actual native/store retirement.

The host bootstrap is part of the installing application's trust boundary,
separate from the thin SDK. It must work through documented distribution inputs;
no qualification marker, Python reflection, seed fixture or test dispatcher is
available to the consumer app.

## D: independent apps and source-bound qualification

After the reviewed A/C contracts are available, build both consumer applications
outside the checkout with access only to versioned SDK/runtime artifacts and
public documentation. The TypeScript app launches its normal frozen host; the
Kotlin app initializes its installed runtime-host library and binds normally.
Create fresh identities, disable alternate LAN/discovery paths through supported
settings, explicitly exchange offer code and consent decisions, and enqueue
messages in both directions with caller keys. Query actual authenticated receipt
state and verify one durable message per logical identity. Repeat with swapped
platform initiators, then add real restart/reopen, caller isolation and event
recovery cases as separate declared inventories.

D owns NEW `examples/typescript-independent-consumer/` and
`examples/android-independent-consumer/`, consumer packaging/orchestration scripts,
native workflow wiring and strict
source/artifact/run evidence. Test infrastructure can terminate processes or
impair networking externally, but cannot initialize product internals or supply
private authority. Retain installed SDK/runtime/APK hashes and actual case
identities. Missing supported bootstrap/pairing fails the required qualification;
component archive/import/Binder checks never stand in for receipt traffic.

Planned exact D files: `examples/typescript-independent-consumer/package.json`,
`consumer.mjs`, `README.md`; `examples/android-independent-consumer/settings.gradle.kts`,
`build.gradle.kts`, `gradle.properties`, `README.md`, `app/build.gradle.kts`,
`app/src/main/AndroidManifest.xml`,
`app/src/main/java/com/meshchat/core/independent/ConsumerApplication.kt`,
`app/src/androidTest/java/com/meshchat/core/independent/IndependentConsumerTest.kt`;
`scripts/stage_independent_core_consumers.py`,
`scripts/verify_independent_core_consumers.py`, and
`scripts/check_independent_core_consumers.py`. A retains the existing
TypeScript/Python consumer examples. Existing Android Binder consumer remains
unchanged as its separate cross-UID component inventory.

This first traffic batch does not close physical qualification, a supported
release/upgrade matrix, the full SC21–SC26 inventory, UI media or the separate
30-second impaired partition requirement.
