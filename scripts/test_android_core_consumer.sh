#!/usr/bin/env bash
# Build the consumer outside the checkout from the public AAR and example only.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
output="$root/dist/android-core-consumer"
reports="$root/dist/reports/android-core_consumer"
stage="$(mktemp -d)"
cleanup() {
  for package in com.meshchat.core.consumer com.meshchat.core.consumer.test com.meshchat.core.hostfixture; do
    timeout 15s adb shell am force-stop "$package" || true
  done
  # stage is the exact directory just created by mktemp, never a user profile.
  rm -rf -- "$stage"
}
trap cleanup EXIT

(cd src-tauri/gen/android && ./gradlew :mesh-core-client:assembleRelease \
  :mesh-core-client:publishReleasePublicationToStagingRepository :core-api-host:assembleDebug \
  -PmeshCoreConsumerQualification=true -PmeshRuntimeAbis=x86_64 --no-configuration-cache)
mkdir -p "$output" "$reports" "$stage/libs"
cp sdk/kotlin/build/outputs/aar/mesh-core-client-release.aar "$output/mesh-core-client.aar"
python scripts/verify_kotlin_distribution.py "$output/mesh-core-client.aar"
cp -R examples/android-core-consumer/. "$stage/"
cp "$output/mesh-core-client.aar" "$stage/libs/"
"$root/src-tauri/gen/android/gradlew" -p "$stage" assembleDebug assembleDebugAndroidTest --no-configuration-cache
cp "$stage/app/build/outputs/apk/debug/app-debug.apk" "$output/consumer.apk"
cp "$stage/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk" "$output/consumer-test.apk"
cp plugins/tauri-plugin-mesh-runtime/android/core-api-host/build/outputs/apk/debug/core-api-host-debug.apk "$output/host.apk"

# Only one package can own the signature permission on the disposable emulator.
for package in com.meshchat.runtime.test com.meshchat.core.consumer com.meshchat.core.consumer.test com.meshchat.core.hostfixture; do
  adb uninstall "$package" >/dev/null 2>&1 || true
done
for apk in host consumer consumer-test; do timeout 120s adb install -r "$output/$apk.apk"; done
run_id="$(python scripts/android_qualification.py prepare --suite core_consumer)"
python scripts/android_qualification.py list --suite core_consumer > "$reports/cases.tsv"
result=0
while IFS=$'\t' read -r method test_class phase; do
  printf 'MESH_QUALIFICATION_RUN=%s\n' "$run_id" > "$reports/$method.txt"
  if ! timeout --signal=INT --kill-after=10s 180s adb shell am instrument -w -r \
    -e class "com.meshchat.runtime.$test_class#$method" \
    com.meshchat.core.consumer.test/androidx.test.runner.AndroidJUnitRunner </dev/null | tee -a "$reports/$method.txt"; then
    result=1
  fi
  if ! grep -Fq 'OK (1 test)' "$reports/$method.txt"; then result=1; fi
done < "$reports/cases.tsv"
exit "$result"
