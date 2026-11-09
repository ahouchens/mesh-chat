#!/usr/bin/env bash
# Ordinary app-owned host, published coordinates, outside-checkout application.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
stage="$(mktemp -d)"
reports="$root/dist/reports/android-core_independent"
output="$root/dist/android-independent-consumer"
cleanup() {
  timeout 15s adb shell am force-stop com.meshchat.core.independent || true
  timeout 15s adb shell am force-stop com.meshchat.core.independent.test || true
  rm -rf -- "$stage"
}
trap cleanup EXIT
"$root/src-tauri/gen/android/gradlew" -p plugins/tauri-plugin-mesh-runtime/android/runtime-host \
  publishReleasePublicationToStagingRepository :mesh-core-client:publishReleasePublicationToStagingRepository \
  -PmeshRuntimeAbis=x86_64 --no-configuration-cache
python scripts/stage_android_independent_consumer.py --stage "$stage"
"$root/src-tauri/gen/android/gradlew" -p "$stage" assembleDebug assembleDebugAndroidTest --no-configuration-cache
python scripts/verify_android_independent_consumer.py --stage "$stage"
mkdir -p "$reports"
for package in com.meshchat.core.independent com.meshchat.core.independent.test; do
  adb uninstall "$package" >/dev/null 2>&1 || true
done
for apk in consumer consumer-test; do timeout 120s adb install -r "$output/$apk.apk"; done
run_id="$(python scripts/android_qualification.py prepare --suite core_independent)"
python scripts/android_qualification.py list --suite core_independent > "$reports/cases.tsv"
result=0
mapfile -t case_lines < "$reports/cases.tsv"
for line in "${case_lines[@]}"; do
  IFS=$'\t' read -r method test_class phase <<< "$line"
  # Prove there are no surviving main or bootstrap processes before each case.
  timeout 15s adb shell am force-stop com.meshchat.core.independent </dev/null
  processes="$(timeout 15s adb shell ps -A </dev/null)"
  header="${processes%%$'\n'*}"
  if [[ ! "$header" =~ NAME|CMD ]]; then exit 1; fi
  if grep -Eq '[[:space:]]com\.meshchat\.core\.independent(:[^[:space:]]*)?$' <<< "$processes"; then exit 1; fi
  printf 'MESH_QUALIFICATION_RUN=%s\n' "$run_id" > "$reports/$method.txt"
  if ! timeout --signal=INT --kill-after=10s 240s adb shell am instrument -w -r \
    -e class "com.meshchat.runtime.$test_class#$method" \
    com.meshchat.core.independent.test/androidx.test.runner.AndroidJUnitRunner </dev/null | tee -a "$reports/$method.txt"; then
    result=1
  fi
  if ! grep -Fq 'OK (1 test)' "$reports/$method.txt"; then result=1; fi
done
exit "$result"
