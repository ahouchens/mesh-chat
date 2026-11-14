#!/usr/bin/env bash
# CI-only real Android WebRTC proof. Always preserve device diagnostics.
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
report_dir="$task_root/dist/reports/android-webrtc"
apk_dir="$task_root/plugins/tauri-plugin-mesh-runtime/android/webrtc-smoke/build/outputs/apk"
app_id="com.meshchat.runtime.smoke"
mkdir -p "$report_dir"
run_id="$(python scripts/android_qualification.py prepare --suite webrtc)"
python scripts/android_qualification.py list --suite webrtc > "$report_dir/cases.tsv"
# Persist diagnostics continuously, including when the outer CI job is stopped.
adb logcat -c
adb logcat -v threadtime > "$report_dir/logcat.txt" &
logcat_pid=$!
collector_running() {
  jobs -pr | grep -Fxq "$logcat_pid"
}
exit_category() {
  if [[ "$1" == 0 ]]; then printf 'ok'
  elif [[ "$1" == 124 ]]; then printf 'timeout'
  elif [[ "$1" =~ ^[0-9]+$ ]] && (( "$1" < 128 )); then printf 'nonzero'
  else printf 'signal_or_unknown'
  fi
}
cleanup_logcat() {
  # An EXIT diagnostic must not replace the suite's original result.
  set +e
  local ownership=already_exited code=unknown state=unknown
  if collector_running; then
    ownership=owned_stop
    kill "$logcat_pid" 2>/dev/null
    for _ in {1..20}; do
      collector_running || break
      sleep 0.1
    done
    if collector_running; then kill -KILL "$logcat_pid" 2>/dev/null; fi
    for _ in {1..10}; do
      collector_running || break
      sleep 0.1
    done
  fi
  if ! collector_running; then
    wait "$logcat_pid"
    code=$?
    state="$(exit_category "$code")"
  fi
  printf 'v\t1\nrun\t%s\nserial\temulator-5554\nownership\t%s\nexit\t%s\ncategory\t%s\n' \
    "$run_id" "$ownership" "$code" "$state" > "$report_dir/logcat-collector.tsv" 2>/dev/null || true
  return 0
}
trap cleanup_logcat EXIT
timeout 90s adb install -r "$apk_dir/release/webrtc-smoke-release.apk"
timeout 90s adb install -r "$apk_dir/androidTest/release/webrtc-smoke-release-androidTest.apk"
timeout 15s adb shell pm grant "$app_id" android.permission.POST_NOTIFICATIONS
result=0
observe_transport() {
  local method="$1" test_class="$2" stage="$3" adb_exit="$4" tee_exit="$5"
  local state=unknown collector=not_running selected
  selected="$(timeout 5s adb -s emulator-5554 get-state </dev/null 2>/dev/null)" || selected=''
  case "$selected" in device|offline) state="$selected" ;; esac
  if collector_running; then collector=running; fi
  printf 'v\t1\nrun\t%s\nserial\temulator-5554\nclass\t%s\nmethod\t%s\nstage\t%s\nadb_exit\t%s\nadb_category\t%s\ntee_exit\t%s\ntee_category\t%s\nadb_state_after\t%s\nlogcat_before_cleanup\t%s\n' \
    "$run_id" "$test_class" "$method" "$stage" "$adb_exit" "$(exit_category "$adb_exit")" \
    "$tee_exit" "$(if [[ "$tee_exit" == not_run ]]; then printf 'not_run'; else exit_category "$tee_exit"; fi)" \
    "$state" "$collector" > "$report_dir/$method.transport.tsv" 2>/dev/null || true
}
# RNS, CPython and WebView are process-wide runtimes. Each direction starts
# with a fresh instrumentation process, just as a fresh app launch does.
run_test() {
  local method="$1" test_class="${2:-NativeWebRtcInteropTest}"
  printf 'MESH_QUALIFICATION_RUN=%s\n' "$run_id" > "$report_dir/$method.txt"
  local adb_exit tee_exit
  if timeout 15s adb shell am force-stop "$app_id"; then
    :
  else
    adb_exit=$?
    result=1
    observe_transport "$method" "$test_class" force_stop "$adb_exit" not_run
    return 0
  fi
  # Run the already-built APKs directly so a Gradle/UTP hang cannot conceal
  # instrumentation output or prevent the next scenario from running.
  set +e
  timeout --signal=INT --kill-after=10s 240s adb shell am instrument -w -r \
      -e class "com.meshchat.runtime.$test_class#$method" \
      "$app_id.test/androidx.test.runner.AndroidJUnitRunner" | tee -a "$report_dir/$method.txt"
  local statuses=("${PIPESTATUS[@]}")
  set -e
  adb_exit="${statuses[0]}"
  tee_exit="${statuses[1]}"
  local passed=0 stage=instrument_incomplete
  # `am instrument` can exit zero for failed tests or an aborted process.
  # Require one actual passing test, not merely a successful ADB invocation.
  if grep -Fq 'OK (1 test)' "$report_dir/$method.txt"; then passed=1; fi
  if [[ "$adb_exit" != 0 || "$tee_exit" != 0 || "$passed" != 1 ]]; then
    result=1
    if ! grep -Fq 'INSTRUMENTATION_STATUS:' "$report_dir/$method.txt"; then
      stage=instrument_no_status
    fi
    observe_transport "$method" "$test_class" "$stage" "$adb_exit" "$tee_exit"
  fi
}
while IFS=$'\t' read -r method test_class phase; do
  run_test "$method" "$test_class" </dev/null
done < "$report_dir/cases.tsv"
timeout 15s adb shell am force-stop "$app_id" || true
exit "$result"
