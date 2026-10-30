#!/usr/bin/env bash
# CI-only real Android WebRTC proof. Always preserve device diagnostics.
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
report_dir="$task_root/dist/reports/android-webrtc"
apk_dir="$task_root/plugins/tauri-plugin-mesh-runtime/android/webrtc-smoke/build/outputs/apk"
app_id="com.meshchat.runtime.smoke"
mkdir -p "$report_dir"
# Persist diagnostics continuously, including when the outer CI job is stopped.
adb logcat -c
adb logcat -v threadtime > "$report_dir/logcat.txt" &
logcat_pid=$!
trap 'kill "$logcat_pid" 2>/dev/null || true' EXIT
timeout 90s adb install -r "$apk_dir/release/webrtc-smoke-release.apk"
timeout 90s adb install -r "$apk_dir/androidTest/release/webrtc-smoke-release-androidTest.apk"
timeout 15s adb shell pm grant "$app_id" android.permission.POST_NOTIFICATIONS
result=0
# RNS, CPython and WebView are process-wide runtimes. Each direction starts
# with a fresh instrumentation process, just as a fresh app launch does.
run_test() {
  local method="$1" test_class="${2:-NativeWebRtcInteropTest}"
  timeout 15s adb shell am force-stop "$app_id"
  # Run the already-built APKs directly so a Gradle/UTP hang cannot conceal
  # instrumentation output or prevent the next scenario from running.
  if ! timeout --signal=INT --kill-after=10s 240s adb shell am instrument -w -r \
      -e class "com.meshchat.runtime.$test_class#$method" \
      "$app_id.test/androidx.test.runner.AndroidJUnitRunner" | tee "$report_dir/$method.txt"; then
    result=1
  fi
  # `am instrument` can exit zero for failed tests or an aborted process.
  # Require one actual passing test, not merely a successful ADB invocation.
  if ! grep -Fq 'OK (1 test)' "$report_dir/$method.txt"; then result=1; fi
}
run_test saturatedMetadataQueueStillAdmitsExactDisposal NativeCallbackQueueTest
for method in cancellationRetainsCapacityUntilCreationAndDisposalFinish cancelledCreationCannotRetryOrReplaceItsReservation replacementWaitsForExactPhysicalDisposal concurrentCreatorsCannotOverbookOrReplaceAnId; do
  run_test "$method" NativeSessionReservationsTest
done
for method in chromiumOfferCanBeAcceptedThroughTheRealPythonBridge chromiumOfferSurvivesEarlyIceFailureDuringManualAnswerExchange nativeOfferCanConnectToChromiumWithReconnectControl repeatedChromiumMediaCallsPreserveNativeMessaging repeatedChromiumMediaCallsPreserveNativeOfferedMessaging backgroundRuntimeCanInitializeNativeWebRtc backgroundDefaultResumesAfterUnlockAndPreservesAnExplicitOffChoice queuedAvailabilityStartHonorsStopWithoutCrashingOrOpeningTheRuntime optedInServiceRestoresAndKeepsNativeTrafficWhileActivityIsStopped; do
  run_test "$method"
done
run_test productionDesktopTransportOffersToNative
run_test productionDesktopTransportAnswersNative
timeout 15s adb shell am force-stop "$app_id" || true
exit "$result"
