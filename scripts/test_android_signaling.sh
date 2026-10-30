#!/usr/bin/env bash
# Isolated emulator/test host only. Never force-stop the installed Mesh Chat app.
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
report_dir="$task_root/dist/reports/android-signaling"
apk_dir="$task_root/plugins/tauri-plugin-mesh-runtime/android/webrtc-smoke/build/outputs/apk"
app_id="com.meshchat.runtime.smoke"
mkdir -p "$report_dir"
cd "$task_root"
setsid pnpm dlx wrangler@4.154.0 dev --local --ip 127.0.0.1 --port 8789 \
  --log-level error --config deploy/cloudflare-signal/wrangler.toml > "$report_dir/worker.txt" 2>&1 &
worker_pid=$!
cleanup() {
  adb reverse --remove tcp:8789 >/dev/null 2>&1 || true
  timeout 15s adb shell am force-stop "$app_id" || true
  kill -- "-$worker_pid" 2>/dev/null || true
}
trap cleanup EXIT
node --input-type=module -e '
for(let n=0;n<60;n++) {
  try { const r=await fetch("http://127.0.0.1:8789/health");
    if(r.ok && (await r.json()).protocol===2) process.exit(0); } catch {}
  await new Promise(resolve=>setTimeout(resolve,1000));
} process.exit(1);'
timeout 90s adb install -r "$apk_dir/release/webrtc-smoke-release.apk"
timeout 90s adb install -r "$apk_dir/androidTest/release/webrtc-smoke-release-androidTest.apk"
adb reverse tcp:8789 tcp:8789
result=0
run_test() {
  local method="$1" phase="${2:-none}" report="$report_dir/$1-${2:-none}.txt"
  timeout 15s adb shell am force-stop "$app_id"
  if ! timeout --signal=INT --kill-after=10s 480s adb shell am instrument -w -r \
    -e class "com.meshchat.runtime.SignalMailboxAndroidTest#$method" \
    -e mailboxUrl http://127.0.0.1:8789 -e restartPhase "$phase" \
    "$app_id.test/androidx.test.runner.AndroidJUnitRunner" | tee "$report"; then result=1; fi
  if ! grep -Fq 'OK (1 test)' "$report"; then result=1; fi
}
run_test embeddedDefaultAndChoicesSurviveProcessRestart seed
run_test embeddedDefaultAndChoicesSurviveProcessRestart verify
run_test packagedAndroidCryptoExchangesCiphertextWithWorker
run_test personalMailboxRecoversAfterLossRestartAndLifecycleChanges
run_test workspaceMailboxRecoversAfterLossRestartAndLifecycleChanges
run_test sharedRuntimeOwnsNativeRecoveryAcrossLifecycle
run_test sharedRuntimeAdoptsVerifiedManualNativeCarrierWithoutMailbox
run_test sharedRuntimeAdoptsManualCarrierWithAutomaticReconnectDisabled
exit "$result"
