#!/usr/bin/env bash
# Run both independent suites and preserve either failure in the final result.
set -uo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
result=0
bash scripts/test_android_webrtc.sh || result=1
bash scripts/test_android_signaling.sh || result=1
bash scripts/test_android_core_api.sh || result=1
python scripts/android_qualification.py report --status "$result" || result=1
exit "$result"
