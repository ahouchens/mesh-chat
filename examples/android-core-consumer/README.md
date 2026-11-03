# Independent Binder consumer qualification

This standalone Android project depends on `libs/mesh-core-client.aar`, Android,
and AndroidX instrumentation. It has no repository project dependencies, Python,
or private runtime imports. Supply the experimental public AAR at that path and
build with Gradle 9.6.1, Java 21 or newer, and Android SDK 36:

```sh
gradle assembleDebug assembleDebugAndroidTest
```

The application and test APKs appear under `app/build/outputs/apk`. The example
targets the separate CI host `com.meshchat.core.hostfixture`. Its signature
permission requires all three APKs to use the same accepted signing certificate;
their application IDs and Linux UIDs remain distinct.

From the repository, `bash scripts/test_android_core_consumer.sh` builds the
public SDK and CI host, copies this example and the AAR into a temporary directory
outside the checkout, builds and installs the three APKs on the disposable
emulator, and runs every required case. The host owns a private encrypted profile
and seeds a real workspace through normal domain commands. The consumer can query
it, but cannot create a channel with owner authority or inject private controls.
The script also checks detach/reattach, and force-stops the fixture packages.

The host fixture uses the existing app runtime composition. These checks qualify
SDK packaging and Binder authority; they do not establish shared-policy native
recovery, two-peer messaging and receipts, physical-device behavior, or the full
M5 independent application acceptance criteria.
