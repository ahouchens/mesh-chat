# Android signalling mailbox tests

`SignalMailboxAndroidTest` runs packaged CPython, Android crypto, sealed vault
storage and native WebRTC in the optimized `webrtc-smoke` host. It uses a real
local Cloudflare Worker through `adb reverse`, never the global deployment.

| Scenario | Assertions |
| --- | --- |
| Settings across process restart | The APK embeds the global URL. Fresh profiles use it; custom and disabled settings survive a force-stop and new process. |
| Encrypted mailbox | Packaged crypto decrypts the compatibility vector and exchanges ciphertext with the Worker. Wrong keys, room IDs and roles fail authentication. |
| Personal and workspace reconnect | Two authorized fixture peers establish native channels and exchange binary packets, recover after injected HTTP loss and closed channels, yield new negotiations in foreground, resume in background and reconnect after reopening sealed profiles without another capability exchange. |
| Shutdown | Stopping supervisors closes their native sessions and stops mailbox requests. |

The Python fixture is included only in the instrumentation APK's assets. The
production host APK contains neither the fixture nor its localhost override.
Approved contacts/workspace membership and signed reciprocal capabilities are
seeded; this does not drive invitation UI. Both peers run in one Android process.
Recovery reloads vaults and supervisors; the separate settings test performs an
actual process restart. Lifecycle transitions are controlled fixture states,
not real Android activity/service transitions. Native packet counts do not
establish Reticulum delivery receipts.

## Run on an isolated emulator or test device

Use Linux with Node/pnpm, Python, JDK, Android SDK, `adb`, `setsid` and `timeout`.
Install dependencies with `pnpm install --frozen-lockfile` and
`python -m pip install -r service/requirements-dev.lock`.
Start one emulator (CI uses API 35, Google APIs, x86_64), then build:

```sh
cd src-tauri/gen/android
./gradlew :webrtc-smoke:assembleRelease :webrtc-smoke:assembleReleaseAndroidTest \
  -PmeshWebRtcSmoke=true -PmeshRuntimeAbis=x86_64 --no-configuration-cache
cd ../../..
python scripts/verify_android_webrtc.py \
  plugins/tauri-plugin-mesh-runtime/android/webrtc-smoke/build/outputs/apk/release/webrtc-smoke-release.apk
bash scripts/test_android_signaling.sh
```

For ARM64, use `-PmeshRuntimeAbis=arm64-v8a`. The runner installs only
`com.meshchat.runtime.smoke` and its instrumentation package, starts Wrangler
4.154.0 on port 8789, forwards it with `adb reverse`, and invokes each test in
a fresh host process. It checks JUnit success text as well as shell exit status.
Cleanup removes forwarding and stops the test host and Worker. Reports go to
`dist/reports/android-signaling/`. Use a dedicated device: the test host is
force-stopped between tests. The installed Mesh Chat app is not stopped or cleared.

The [Android workflow](../.github/workflows/android-webrtc.yml) runs this suite
after native Chromium interoperability tests and uploads reports even on failure.

## Local emulator validation — 2026-10-28

The local Windows emulator is named `MeshMailbox_API35`: Android 15/API 35,
`aosp_atd` x86_64 revision 1, Emulator 37.2.12, WHPX acceleration, two virtual
cores and 2 GB RAM. The AVD remains available for later runs. Start it from
PowerShell with the installed SDK:

```powershell
& "$env:LOCALAPPDATA\Android\Sdk\emulator\emulator.exe" -avd MeshMailbox_API35 `
  -port 5556 -no-window -no-snapshot -no-audio -gpu swiftshader `
  -memory 2048 -cores 2 -no-boot-anim
```

Use `adb -s emulator-5556` when other devices are connected. First creation of
this AVD's 6 GB writable partition required about 7.7 GB free on the host.
The test host and instrumentation APK are separate from the installed Mesh Chat
application. Local instrumentation output and device logs are kept under
`dist/reports/android-signaling-emulator/`.

The optimized x86_64 host and instrumentation APK compile locally. Host-side
regressions cover request reuse after timeout so delayed peers can catch up,
and replacement of expired requests. The scenario fixture can also run against
the local Worker with a native transport double; that checks orchestration,
not JNI execution. Local validation passed the crypto round trip and both
personal/workspace recovery scenarios using that transport double. The 145
related service tests also passed, and APK inspection confirmed the fixture
is present only in the instrumentation package.

Android execution exposed two production issues: one shared 45-second deadline
could expire during native SDP creation, and continuous ICE gathering never
reported completion to the host's non-trickle signaling wait. Mailbox polls and
attachment now have separate bounded waits, and native descriptions gather one
complete candidate set. The fixture asserts completed gathering and candidate
presence; host regressions simulate slow native gathering in both reconnect roles.
The continuous-gathering behavior is also documented in
[libwebrtc's transport implementation](https://chromium.googlesource.com/external/webrtc/+/refs/heads/master/p2p/base/p2p_transport_channel.cc).

All five mailbox instrumentation invocations passed on this emulator: settings
seed, settings verification after force-stop, packaged crypto, personal recovery
and workspace recovery. The recovery cases used real JNI/WebRTC and exchanged
packets in both directions after each recovery; personal recovery took 267 seconds
and workspace recovery 188 seconds including the intentional outages and retries.
Three existing Chromium interoperability tests also passed: Chromium offer,
manual answer after early ICE failure, and native offer with reconnect control.
The emulator's WebView was `com.android.webview` 124.0.6367.219.

Results and device logs: `dist/reports/android-signaling-emulator/` and
`dist/reports/android-signaling-interop/`. APK SHA256 values:

- Optimized host: `C0DE85326CF2F1910B10A27D39354CB79C56EB8E5A91A02A5CFD4A5DE3F812E0`
- Instrumentation: `7176187D1D93F0D1115E27ABCEE0AB1971975722EFE51BFF9198226E5F334BB4`

This is emulator validation, not two-device physical qualification. Physical
devices still need network switching, cellular/NAT traversal, actual app process
kill, foreground-service/Doze behavior, revocation and end-to-end message receipt
checks. See [mailbox validation](../deploy/cloudflare-signal/VALIDATION.md).
