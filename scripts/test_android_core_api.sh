#!/usr/bin/env bash
# The plugin library's instrumentation suite covers the Binder entry: exported
# signature permission, caller-derived identity, bounded frames and fail-closed
# typing before the embedded service is initialized.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
./gradlew -p src-tauri/gen/android \
  :tauri-plugin-mesh-runtime:connectedDebugAndroidTest \
  -PmeshRuntimeAbis=x86_64 \
  --no-configuration-cache \
  -Pandroid.testInstrumentationRunnerArguments.class=com.meshchat.runtime.MeshCoreApiServiceTest
