"""Exercise the Android WebRTC runner's failure flow in a real Bash process."""

import os
from pathlib import Path
import shutil
import subprocess
import time

import pytest


RUN_ID = "a" * 32
SCRIPT = Path(__file__).resolve().parents[3] / "scripts/test_android_webrtc.sh"


def _fields(path: Path) -> dict[str, str]:
    return dict(line.split("\t", 1) for line in path.read_text().splitlines())


@pytest.mark.parametrize("collector_mode", ["running", "stopped"])
def test_transport_failures_keep_exact_case_inventory_and_original_result(tmp_path, collector_mode):
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    assert bash and Path(bash).is_file(), "This runner regression requires Bash"
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    runner = SCRIPT.read_text()
    if collector_mode == "stopped":
        # Pause the fixture runner after it records the actual owned job PID.
        # The test process then stops that PID before any scenario starts.
        marker = "logcat_pid=$!\n"
        assert marker in runner
        runner = runner.replace(marker, marker +
            "printf '%s\\n' \"$logcat_pid\" > collector-pid.txt\n"
            "while [[ ! -e collector-stopped.txt ]]; do sleep 0.01; done\n", 1)
    (scripts / SCRIPT.name).write_text(runner, encoding="utf-8", newline="\n")
    commands = tmp_path / "commands"
    commands.mkdir()
    (commands / "python").write_text(f'''#!/usr/bin/env bash
case "$*" in
  *'prepare --suite webrtc'*) printf '%s\\n' {RUN_ID} ;;
  *'list --suite webrtc'*) printf 'first\\tFirstTest\\tphase\\nsecond\\tSecondTest\\tphase\\nthird\\tThirdTest\\tphase\\n' ;;
  *) exit 2 ;;
esac
''', encoding="utf-8", newline="\n")
    (commands / "timeout").write_text(
        '#!/usr/bin/env bash\nwhile [[ "$1" == --* ]]; do shift; done\nshift\nexec "$@"\n',
        encoding="utf-8", newline="\n")
    (commands / "adb").write_text('''#!/usr/bin/env bash
[[ "$1" == -s && "$2" == emulator-5554 ]] || exit 3
shift 2
printf '%s\\n' "-s emulator-5554 $*" >> adb-calls.txt
case "$*" in
  'logcat -c'|'shell pm grant '*) exit 0 ;;
  'install -r '*) exit 0 ;;
  'logcat -v threadtime') exec sleep 30 ;;
  'shell am force-stop '*)
    count=0
    if [[ -f force-stop-count.txt ]]; then read -r count < force-stop-count.txt; fi
    count=$((count + 1))
    printf '%s\\n' "$count" > force-stop-count.txt
    if [[ "$count" == 2 ]]; then printf 'adb: device offline\\n' >&2; exit 1; fi
    exit 0 ;;
  'shell am instrument '* )
    if [[ "$*" == *'#first '* ]]; then exit 0; fi
    printf 'INSTRUMENTATION_STATUS: class=ThirdTest\\n'
    printf 'INSTRUMENTATION_STATUS: test=third\\n'
    printf 'OK (1 test)\\n'
    exit 0 ;;
  'get-state') printf '%0100d' 0; exit 1 ;;
  *) exit 2 ;;
esac
''', encoding="utf-8", newline="\n")
    for command in commands.iterdir():
        command.chmod(0o755)
    environment = {**os.environ, "FIXTURE_COMMANDS": commands.as_posix()}
    setup = '''if command -v cygpath >/dev/null; then
FIXTURE_COMMANDS=$(cygpath -u "$FIXTURE_COMMANDS")
fi
export PATH="$FIXTURE_COMMANDS:$PATH"
bash scripts/test_android_webrtc.sh'''
    if collector_mode == "running":
        completed = subprocess.run([bash, "-c", setup], cwd=tmp_path, env=environment,
                                   stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20)
    else:
        process = subprocess.Popen([bash, "-c", setup], cwd=tmp_path, env=environment,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        try:
            pid_file = tmp_path / "collector-pid.txt"
            deadline = time.monotonic() + 5
            while not pid_file.exists() and time.monotonic() < deadline:
                assert process.poll() is None, "Runner exited before collector synchronization"
                time.sleep(0.01)
            assert pid_file.exists(), "Runner never started its collector"
            subprocess.run([bash, "-c", 'kill -STOP "$1"', "bash", pid_file.read_text().strip()],
                           check=True, capture_output=True, text=True)
            (tmp_path / "collector-stopped.txt").touch()
            stdout, stderr = process.communicate(timeout=20)
            completed = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
    assert completed.returncode == 1, completed.stderr[-2000:]

    reports = tmp_path / "dist/reports/android-webrtc"
    marker = f"MESH_QUALIFICATION_RUN={RUN_ID}\n"
    assert (reports / "first.txt").read_text() == marker
    assert (reports / "second.txt").read_text() == marker
    assert (reports / "third.txt").read_text().startswith(marker)
    assert "OK (1 test)" in (reports / "third.txt").read_text()
    calls = (tmp_path / "adb-calls.txt").read_text().splitlines()
    assert all(call.startswith("-s emulator-5554 ") for call in calls)
    assert sum("shell am force-stop" in call for call in calls) == 4  # three cases plus final cleanup
    launches = [call for call in calls if "shell am instrument" in call]
    assert len(launches) == 2
    assert "FirstTest#first" in launches[0]
    assert "ThirdTest#third" in launches[1]
    assert sum(call == "-s emulator-5554 get-state" for call in calls) == 2

    first = _fields(reports / "first.transport.tsv")
    second = _fields(reports / "second.transport.tsv")
    expected = {"v": "1", "run": RUN_ID, "serial": "emulator-5554",
                "adb_state_after": "unknown"}
    assert {key: first[key] for key in expected} == expected
    assert {key: second[key] for key in expected} == expected
    collector_labels = {"active"} if collector_mode == "running" else {"active", "stopped"}
    assert first["logcat_before_cleanup"] in collector_labels
    assert second["logcat_before_cleanup"] in collector_labels
    assert {key: first[key] for key in ("class", "method", "stage", "adb_exit", "adb_category",
                                             "tee_exit", "tee_category")} == {
        "class": "FirstTest", "method": "first", "stage": "instrument_no_status",
        "adb_exit": "0", "adb_category": "ok", "tee_exit": "0", "tee_category": "ok"}
    assert {key: second[key] for key in ("class", "method", "stage", "adb_exit", "adb_category",
                                              "tee_exit", "tee_category")} == {
        "class": "SecondTest", "method": "second", "stage": "force_stop",
        "adb_exit": "1", "adb_category": "nonzero", "tee_exit": "not_run", "tee_category": "not_run"}
    assert not (reports / "third.transport.tsv").exists()
    collector = _fields(reports / "logcat-collector.tsv")
    assert {key: collector[key] for key in ("v", "run", "serial", "ownership", "category")} == {
        "v": "1", "run": RUN_ID, "serial": "emulator-5554",
        "ownership": "owned_stop", "category": "signal_or_unknown"}
    assert "adb: device offline" not in (reports / "second.transport.tsv").read_text()
    script = SCRIPT.read_text()
    assert 'timeout 5s adb -s "$device_serial" get-state' in script
    assert "| head -c 32" in script
    assert 'timeout 15s adb -s "$device_serial" shell am force-stop' in script
