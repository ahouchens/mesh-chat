# Ordinary app-owned Android Core consumer

This experimental application installs the versioned `com.meshchat:core-runtime-host`
and `com.meshchat:core-client` `0.3.0-experimental` Maven artifacts. Its Application
starts the normal host only in its main process. It binds its own Android service
through the public SDK and has no Tauri dependency, seeded host fixture, private
dispatcher, checkout source dependency or qualification override.

`scripts/test_android_independent_consumer.sh` publishes the producer artifacts,
copies this example and the exact Maven artifacts outside the checkout, builds
there, installs the two APKs on the required emulator and runs both cases in order.
The second case follows an actual force-stop and observes the registered profile
as locked and compares the new process ID with the stored prior process ID.
The app-private observations contain only public opaque handles, the public
destination and that process ID; they confer no unlock authority.

The required cases cover ordinary startup, explicit identity creation, original-key replay,
conflict rejection, SDK detach/rebind, public locking, real shutdown, cold locked
startup and invalid credential rejection. It does not establish successful OS
credential confirmation, authenticated peer receipts, media, physical hardware,
background availability or a supported SDK/runtime release.

The producer retains both AAR/POM/module/sources-JAR publications and both APKs.
Packaging checks validate the Gradle API/runtime dependency variants, every
advertised artifact hash, Python service assets, native libraries and merged
service permissions. Component tests of these checks are separate from actual
publication assembly, installation and instrumentation evidence in CI.

The separate `scripts/check_android_independent_public_session.py` runner uses
the verified APKs in `dist/android-independent-consumer`. It clears the installed
app, starts one long-lived main-process instrumentation method, connects over a
nonce-protected loopback port and exercises multiple requests through one own
Binder `CoreClient`. The first executable phases prove fresh public state,
profile creation, profile query, and explicit runtime shutdown. It writes
`dist/reports/android-independent-public-session.json` with source and artifact
hashes, phase results and cleanup status. Invoke it with `--expected-source`
set to the exact checkout commit and `--disposable-emulator-serial` set to the
explicit ADB emulator serial. It verifies the emulator before changing installed
packages. This runner requires the staged distribution report; it does not build
APKs. The normal owner grant exposes one stable public profile handle before
identity creation; the empty application snapshot establishes fresh identity.

The test-only port accepts length-prefixed UTF-8 JSON objects. After
`{"id":"auth","action":"authenticate","nonce":"<64 lowercase hex>"}`,
send monotonically numbered `request` objects with `id`, `step`, `operation`,
`params` and an `idempotency_key` when the public operation requires one.
`finish` carries the next step and ends the session. Frames are limited to
65,536 bytes and 127 public requests, reserving the next step for `finish`.
The operation allowlist includes public
pairing begin/query/cancel, contact invitation and approval decisions,
connection snapshot/start, and message enqueue/query/received for a later
Windows peer controller. Those peer and message phases still need same-run
installed Android and Windows evidence; this first runner makes no such claim.

The Python runner also exposes `AndroidPublicSession(expected_source, serial)`
for a later same-run controller. Use it as a context manager, issue only
`request(operation, params, key)` calls from the existing public allowlist,
and call `finish()` before the context ends. `finish()` returns only after the
instrumentation exits successfully and the runtime shutdown is observed;
leaving the context early retires the owned test process and reports no success.
If cleanup fails during a normal context exit, the adapter raises a fixed
cleanup error; a pending request failure remains the primary exception.
The adapter keeps the same source, emulator, frame and total time limits as the
standalone smoke command.
