#!/usr/bin/env bash
# CI-only real Android WebRTC proof. Always preserve device diagnostics.
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$task_root/dist/reports/android-webrtc"
trap 'adb logcat -d -v threadtime > "$task_root/dist/reports/android-webrtc/logcat.txt" || true' EXIT
cd "$task_root/src-tauri/gen/android"
result=0
# RNS, CPython and WebView are process-wide runtimes. Each direction starts
# with a fresh instrumentation process, just as a fresh app launch does.
for method in chromiumOfferCanBeAcceptedThroughTheRealPythonBridge nativeOfferCanConnectToChromiumWithReconnectControl; do
  ./gradlew :tauri-plugin-mesh-runtime:connectedDebugAndroidTest \
    -PmeshRuntimeAbis=x86_64 --no-configuration-cache \
    "-Pandroid.testInstrumentationRunnerArguments.class=com.meshchat.runtime.NativeWebRtcInteropTest#$method" || result=1
  cp -R "$task_root/plugins/tauri-plugin-mesh-runtime/android/build/reports/androidTests" \
    "$task_root/dist/reports/android-webrtc/$method" || true
done
exit "$result"
