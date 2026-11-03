# Experimental Android client

`com.meshchat:core-client:0.2.0-experimental` packages `CoreClient`,
`CoreExchangeTransport`, and the public `IMeshCoreApi` Binder interface. The AAR
contains no Python runtime, native transport, vault, or host implementation.
It is an unpublished component, not yet a supported M5 release.

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
frame. Closing the client detaches local transport state; unbind the service
connection separately. Neither action is an owner-stop command. A failed or
timed-out mutation has an unknown outcome: do not blindly retry it; use the
operation's idempotency key and durable status where available.

The [independent example](../../examples/android-core-consumer/README.md) compiles
outside the checkout against this AAR. CI records its APKs, SDK digest, and
cross-UID Binder checks. Durable peer messaging, restart/partition recovery,
multi-client lifetime, upgrade fixtures, compatibility support windows, and
redistribution documentation remain release requirements.
