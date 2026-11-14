#!/usr/bin/env bash
# CI-only real Android WebRTC proof. Always preserve device diagnostics.
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
report_dir="$task_root/dist/reports/android-webrtc"
apk_dir="$task_root/plugins/tauri-plugin-mesh-runtime/android/webrtc-smoke/build/outputs/apk"
app_id="com.meshchat.runtime.smoke"
device_serial=emulator-5554
mkdir -p "$report_dir"
run_id="$(python scripts/android_qualification.py prepare --suite webrtc)"
python scripts/android_qualification.py list --suite webrtc > "$report_dir/cases.tsv"
# Persist diagnostics continuously, including when the outer CI job is stopped.
adb -s "$device_serial" logcat -c
adb -s "$device_serial" logcat -v threadtime > "$report_dir/logcat.txt" &
logcat_pid=$!
collector_running() {
  jobs -pr | grep -Fxq "$logcat_pid"
}
collector_stopped() {
  jobs -ps | grep -Fxq "$logcat_pid"
}
collector_active() {
  # jobs -pr omits stopped children; jobs -p includes completed jobs.
  collector_running || collector_stopped
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
  if collector_active; then
    ownership=owned_stop
    # A stopped child cannot act on TERM until continued. Some noninteractive
    # shells still classify a stopped process as running in jobs -pr.
    kill -CONT "$logcat_pid" 2>/dev/null
    kill "$logcat_pid" 2>/dev/null
    for _ in {1..20}; do
      collector_active || break
      sleep 0.1
    done
    if collector_active; then kill -KILL "$logcat_pid" 2>/dev/null; fi
    for _ in {1..10}; do
      collector_active || break
      sleep 0.1
    done
  fi
  # wait is nonblocking only after the owned job has reached a terminal state.
  if ! collector_active; then
    wait "$logcat_pid"
    code=$?
    state="$(exit_category "$code")"
  fi
  printf 'v\t1\nrun\t%s\nserial\t%s\nownership\t%s\nexit\t%s\ncategory\t%s\n' \
    "$run_id" "$device_serial" "$ownership" "$code" "$state" > "$report_dir/logcat-collector.tsv" 2>/dev/null || true
  return 0
}
trap cleanup_logcat EXIT
timeout 90s adb -s "$device_serial" install -r "$apk_dir/release/webrtc-smoke-release.apk"
timeout 90s adb -s "$device_serial" install -r "$apk_dir/androidTest/release/webrtc-smoke-release-androidTest.apk"
timeout 15s adb -s "$device_serial" shell pm grant "$app_id" android.permission.POST_NOTIFICATIONS
result=0
observe_transport() {
  local method="$1" test_class="$2" stage="$3" adb_exit="$4" tee_exit="$5"
  local state=unknown collector=not_active selected
  selected="$(timeout 5s adb -s "$device_serial" get-state </dev/null 2>/dev/null | head -c 32)" || selected=''
  case "$selected" in device|offline) state="$selected" ;; esac
  if collector_running; then collector=active; fi
  if collector_stopped; then collector=stopped; fi
  printf 'v\t1\nrun\t%s\nserial\t%s\nclass\t%s\nmethod\t%s\nstage\t%s\nadb_exit\t%s\nadb_category\t%s\ntee_exit\t%s\ntee_category\t%s\nadb_state_after\t%s\nlogcat_before_cleanup\t%s\n' \
    "$run_id" "$device_serial" "$test_class" "$method" "$stage" "$adb_exit" "$(exit_category "$adb_exit")" \
    "$tee_exit" "$(if [[ "$tee_exit" == not_run ]]; then printf 'not_run'; else exit_category "$tee_exit"; fi)" \
    "$state" "$collector" > "$report_dir/$method.transport.tsv" 2>/dev/null || true
}
# RNS, CPython and WebView are process-wide runtimes. Each direction starts
# with a fresh instrumentation process, just as a fresh app launch does.
run_test() {
  local method="$1" test_class="${2:-NativeWebRtcInteropTest}"
  printf 'MESH_QUALIFICATION_RUN=%s\n' "$run_id" > "$report_dir/$method.txt"
  local adb_exit tee_exit
  if timeout 15s adb -s "$device_serial" shell am force-stop "$app_id"; then
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
  timeout --signal=INT --kill-after=10s 240s adb -s "$device_serial" shell am instrument -w -r \
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
timeout 15s adb -s "$device_serial" shell am force-stop "$app_id" || true
exit "$result"
