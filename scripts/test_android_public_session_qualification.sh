#!/usr/bin/env bash
set -euo pipefail

task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"

bash scripts/test_android_qualification.sh
python -B scripts/check_android_independent_public_session.py \
  --expected-source "${GITHUB_SHA:?}" \
  --disposable-emulator-serial emulator-5554 \
  --output dist/reports/android-independent-public-session.json
