#!/usr/bin/env bash
# Required Android Binder qualification: run each scenario once through the real
# instrumentation runner and bind the evidence to this exact source and APK.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
report_dir="$root/dist/reports/android-core_api"
test_apk="plugins/tauri-plugin-mesh-runtime/android/build/outputs/apk/androidTest/debug/tauri-plugin-mesh-runtime-debug-androidTest.apk"
app_id="com.meshchat.runtime.test"

# The WebRTC smoke app also includes the library and therefore defines the same
# signature permission. Only one package may own it on a device, and that suite
# has already finished, so remove its installation before this APK declares it.
adb uninstall com.meshchat.runtime.smoke >/dev/null 2>&1 || true
adb uninstall "$app_id" >/dev/null 2>&1 || true

(cd src-tauri/gen/android && \
  ./gradlew :mesh-core-client:testDebugUnitTest :tauri-plugin-mesh-runtime:testDebugUnitTest \
    -PmeshRuntimeAbis=x86_64 --no-configuration-cache)

(cd src-tauri/gen/android && \
  ./gradlew :tauri-plugin-mesh-runtime:assembleDebugAndroidTest \
    -PmeshRuntimeAbis=x86_64 --no-configuration-cache)

mkdir -p "$report_dir"
run_id="$(python scripts/android_qualification.py prepare --suite core_api)"
python scripts/android_qualification.py list --suite core_api > "$report_dir/cases.tsv"
timeout 120s adb install -r "$test_apk"
result=0
mapfile -t case_lines < "$report_dir/cases.tsv"
for line in "${case_lines[@]}"; do
  IFS=$'\t' read -r method test_class phase <<< "$line"
  timeout 15s adb shell am force-stop "$app_id" || true
  printf 'MESH_QUALIFICATION_RUN=%s\n' "$run_id" > "$report_dir/$method.txt"
  if ! timeout --signal=INT --kill-after=10s 180s adb shell am instrument -w -r \
      -e class "com.meshchat.runtime.$test_class#$method" \
      "$app_id/androidx.test.runner.AndroidJUnitRunner" </dev/null | tee -a "$report_dir/$method.txt"; then
    result=1
  fi
  if ! grep -Fq 'OK (1 test)' "$report_dir/$method.txt"; then result=1; fi
done
timeout 15s adb shell am force-stop "$app_id" || true
exit "$result"
