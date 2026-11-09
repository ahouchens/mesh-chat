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
