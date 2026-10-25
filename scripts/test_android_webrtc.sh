#!/usr/bin/env bash
# CI-only real Android WebRTC proof. Always preserve device diagnostics.
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$task_root/dist/reports/android-webrtc"
trap 'adb logcat -d -v threadtime > "$task_root/dist/reports/android-webrtc/logcat.txt" || true' EXIT
cd "$task_root/src-tauri/gen/android"
./gradlew :tauri-plugin-mesh-runtime:connectedDebugAndroidTest \
  -PmeshRuntimeAbis=x86_64 --no-configuration-cache
