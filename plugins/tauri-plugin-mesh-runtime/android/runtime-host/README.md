# App-owned Android Core runtime

Experimental coordinate: `com.meshchat:core-runtime-host:0.3.0-experimental`.
This host AAR embeds the production Python service and native WebRTC adapter;
the thin SDK remains `com.meshchat:core-client:0.3.0-experimental`. The host
reuses selected production sources and has no Tauri project or plugin dependency.
Only one [Chaquopy module](https://www.chaquo.com/chaquopy/doc/current/android.html)
may be embedded in an application. Do not also install the Tauri runtime library.

## Bootstrap and bind

Install both versioned artifacts from the provided Maven staging repository:

```kotlin
dependencies {
    implementation("com.meshchat:core-runtime-host:0.3.0-experimental")
    implementation("com.meshchat:core-client:0.3.0-experimental")
}
```

From your native `Application`, first check `MeshCoreRuntime.isMainProcess(this)`;
call `MeshCoreRuntime.start(applicationContext)` only in the declared main process.
Android also runs `Application.onCreate` in the isolated bootstrap process. The
runtime itself rejects secondary-process startup before starting Python or
reading keys. The `:mesh_bootstrap` name is reserved for its isolated service.
It returns `CompletableFuture<MeshCoreRuntime.State>` and does the blocking work
on the host's bounded worker. `State` is `UNLOCKED`, `LOCKED` or `RETIRING`.
Never wait for the future on Android's main thread. Errors are
`MeshCoreRuntimeException` with a stable `code`, including `unavailable`,
`resource_exhausted` and `forbidden`.

After startup completes, bind using the normal Android service API and explicit
`ComponentName(context.packageName, "com.meshchat.runtime.MeshCoreApiService")`.
The generated `com.meshchat.runtime.IMeshCoreApi` interface comes from the installed
SDK. Adapt it with `CoreClient.open(CoreExchangeTransport { api.exchange(it) })`.
This is the public Core protocol; no fixture, qualification marker or private
command dispatcher participates.

The manifest merges these services:

- `com.meshchat.runtime.MeshCoreApiService`, exported behind the signature
  permission `${applicationId}.permission.MESH_CORE_API`.
- `com.meshchat.runtime.BootstrapService`, non-exported in `:mesh_bootstrap`.

The application's actual UID receives owner grants. External callers require the
app-scoped signature permission and keep consumer grants. Caller identity and
permissions never come from request JSON. The host's public session does not
advertise `native.command` or legacy renderer compatibility operations.

A fresh installation starts with an empty vault and no identity or contacts.
Nearby discovery and LAN fallback start disabled, before identity creation;
existing app-owned preferences survive reopen. Supported public settings can
change them explicitly.
The application explicitly calls
`client.request("profile.create", JSONObject().put("display_name", name), originalCallerKey)`
with its own idempotency key. Pairing, contact decisions, settings and messages
must use the operations actually advertised by `runtime.capabilities`. Missing
features remain unsupported; there is no private fallback.

## Keys and profile lifecycle

This application owns `filesDir/mesh-core-runtime/profile-v1` and a separate
catalog beneath `filesDir/mesh-core-runtime/host-v1`. Independent profile and
catalog keys use separate Android Keystore aliases and wrapped preference
records. The original Mesh Chat application's `mesh-chat/profile-v1` directory
and original key aliases remain unchanged.

A registered cold start returns `LOCKED` without loading the profile decrypt
key. Public Core catalog and capability queries remain available. To unlock,
the native application calls
`MeshCoreRuntime.confirmUnlock(activity: ComponentActivity, profile: String)`
for the current opaque Core profile handle. A secure device credential and the
actual OS confirmation UI are required. The future returns a `Credential` with:

| Property | Type |
| --- | --- |
| `credentialHandle` | `String`, opaque and single-use |
| `expiresInMillis` | `Long` |
| `revision` | `Long` |
| `hostGeneration` | `String`, opaque |

Then call public `client.unlockProfile(profile, credential.credentialHandle,
originalCallerKey)`. Obtaining the credential does not open the profile. Native
confirmation uses a dedicated activity-result registration; cancellation,
activity destruction, expiry and a changed host lifetime reject late results.
Canceling the future also cancels that confirmation. An unsecured device returns
`authentication_unavailable`; it never authorizes a silent unlock.

Use public `profile.lock` for the profile lifetime. `MeshCoreRuntime.shutdown()`
returns `CompletableFuture<Unit>` and completes successfully only after actual
native/store retirement. An incomplete shutdown returns a typed failure while
the host retains custody; it does not issue a new unlock or replacement intent.
SDK transport closure only detaches that client. Android may terminate the app
process; this AAR does not promise persistent background execution or provide
foreground availability/media services.

## Producer staging

Build this directory as an independent Gradle project using the repository's
Gradle 9.6.1 wrapper, Android API 36, Kotlin 2.2.10 and Chaquopy 17.0.0:

```text
gradlew -p plugins/tauri-plugin-mesh-runtime/android/runtime-host \
  publishReleasePublicationToStagingRepository \
  :mesh-core-client:publishReleasePublicationToStagingRepository
```

The default ABI is `arm64-v8a`; CI can explicitly build `-PmeshRuntimeAbis=x86_64`
or a comma-separated set. Python is 3.13, requirements come from the pinned
`service/requirements-mobile.lock`, and WebRTC is pinned to 150.7871.01.

Combine the two generated Maven repositories for outside-checkout consumers:

- `runtime-host/build/repository/com/meshchat/core-runtime-host/0.3.0-experimental/`
- `sdk/kotlin/build/repository/com/meshchat/core-client/0.3.0-experimental/`

Retain the AAR, POM, module metadata, source identity and hashes. Ordinary
consumers resolve the versioned coordinate and must not read producer sources
or use a `project(...)` dependency into this checkout.

Source compilation and component tests do not qualify this distribution. Actual
AAR/POM assembly, merged manifest/ABI/Python asset checks, installation outside
the checkout, real OS confirmation and authenticated receipt traffic remain
separate required platform evidence. This is not a supported release declaration.
