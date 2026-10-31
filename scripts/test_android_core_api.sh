#!/usr/bin/env bash
# The plugin library's instrumentation suite covers the Binder entry: exported
# signature permission, caller-derived identity, bounded frames and fail-closed
# typing before the embedded service is initialized.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root/src-tauri/gen/android"

# The earlier WebRTC smoke app also includes this library, so it defines the same
# signature permission. Only one package may own a permission on a device; the
# smoke suite has already finished, so drop that installation before the plugin
# test app defines the permission as its own.
adb uninstall com.meshchat.runtime.smoke >/dev/null 2>&1 || true
adb uninstall com.meshchat.runtime.test >/dev/null 2>&1 || true

status=0
./gradlew :tauri-plugin-mesh-runtime:connectedDebugAndroidTest \
  -PmeshRuntimeAbis=x86_64 \
  --no-configuration-cache \
  -Pandroid.testInstrumentationRunnerArguments.class=com.meshchat.runtime.MeshCoreApiServiceTest || status=$?

if [[ "$status" -ne 0 ]]; then
  echo "::group::Plugin instrumentation results"
  find "/plugins/tauri-plugin-mesh-runtime/android/build/outputs/androidTest-results" \
    -name '*.xml' -type f -print -exec sed -n '1,220p' {} \; 2>/dev/null || true
  echo "::endgroup::"
fi
exit "$status"
