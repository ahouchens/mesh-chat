# Experimental Android client

`com.meshchat:core-client:0.3.0-experimental` packages `CoreClient`,
`CoreExchangeTransport`, and the public `IMeshCoreApi` Binder interface. The AAR
contains no Python runtime, native transport, vault, or host implementation.
It is an unpublished component, not yet a supported M5 release.
The AAR includes the project's MIT license in `classes.jar/META-INF/LICENSE`.
The SDK never opens or owns a vault, profile directory or key. It provides no
profile export, key export or uninstall-erasure guarantee.

Client and AIDL sources now live entirely under this SDK directory. The runtime
host consumes the client module as a dependency. Its package names and Binder
exchange interface remain compatible with 0.2 clients. Composer methods require
API minor 1, all three composer operations and the nine positive composer limits;
an older host returns local `unsupported_operation` before a mutation is sent.

With the generated Android Gradle project initialized, build and stage locally:

```sh
cd src-tauri/gen/android
./gradlew :mesh-core-client:assembleRelease :mesh-core-client:publishReleasePublicationToStagingRepository
```

The AAR is `sdk/kotlin/build/outputs/aar/mesh-core-client-release.aar`; the local
Maven repository is `sdk/kotlin/build/repository`. The staging task does not
publish to a remote repository. Run `python scripts/verify_kotlin_distribution.py
<aar>` to check its contents and calculate its digest.

Bind an explicitly selected host's `com.meshchat.runtime.MeshCoreApiService`
using Android's service binding API. The host requires the signature permission
`com.meshchat.runtime.permission.CORE_API`. An external consumer must be signed
with a certificate accepted by that host; possession of the AAR grants no access.
The host captures the OS caller UID before dispatch and grants external packages
consumer permissions. Only its own UID receives owner permissions.

After `onServiceConnected`, on a background thread:

```kotlin
val remote = IMeshCoreApi.Stub.asInterface(binder)
val client = CoreClient.open(CoreExchangeTransport { remote.exchange(it) })
val profile = client.capabilities.getJSONArray("profiles").getString(0)
val snapshot = client.profileQuery(profile)
client.close()
```

Use one calling thread per client. Requests and replies must each fit in 256 KiB
including the terminating LF. The transport validates UTF-8 and exactly one
frame. Host admission failures preserve their typed error and close the client
when no request ID could be correlated. Closing the client detaches local transport state; unbind the service
connection separately. Neither action is an owner-stop command. A failed or
timed-out mutation has an unknown outcome: do not blindly retry it; use the
operation's idempotency key and durable status where available.
Binder calls are blocking; the host enforces its dispatch bounds. The SDK does
not cancel a remotely committed operation or retry a timed-out caller task.
Use an application-owned bounded worker task and resolve unknown outcomes
through Core before explicitly retrying the original identity.

First composer mutation raises host vault format 1 to 2 atomically. Old format-1
hosts must refuse migrated storage; binary downgrade is unsupported. API minor
compatibility does not imply storage downgrade safety. The experimental pair is
API1.0/source174728e with SDK0.2 versus candidate API1.1/SDK0.3.0-experimental.
Python's first standalone wheel uses PEP440 version0.3.0.dev0 for this cohort.
Android ABI/API-level and actual packaged evidence belong to each CI artifact
manifest; staging declares no supported upgrade window.

Profile catalog/lock/select/unlock helpers require all four lifecycle operations
and four positive profile limits. Only the runtime-level host advertises them.
Unlock accepts an expiring, single-use opaque credential reference from trusted
platform authentication. The SDK never issues credentials or reads Keystore
keys. Selection and reconciliation do not unlock a profile implicitly.

`createGroup` and `sendGroup` accept an optional final caller key. Explicit keyed
calls require the operation in `optional_keyed_operations` and all three
positive optional-key limits. Legacy no-key calls preserve repeatable behavior;
they have no replay guarantee. The SDK never invents keys or falls back to an
unkeyed call. Keyed send acceptance is a durable local enqueue, not delivery.

The [independent example](../../examples/android-core-consumer/README.md) compiles
outside the checkout against this AAR. CI records its APKs, SDK digest, and
cross-UID Binder checks. Durable peer messaging, restart/partition recovery,
multi-client lifetime, upgrade fixtures, compatibility support windows, and
redistribution documentation remain release requirements.
