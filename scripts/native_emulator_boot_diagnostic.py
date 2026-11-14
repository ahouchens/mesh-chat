"""One declared old/current emulator-launch pair; no app or native qualification.

The control preserves b8e3e20's inherited stdin and discarded output. The observed
case preserves 82c3364's flags and pipe. Only a fresh AVD is booted in each case;
no APK, profile, credential, network impairment or product host is installed.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

from native_interop_android_system import LOG_TAGS
from native_interop_peers import AndroidEmulator, PeerFailure
from native_interop_android_observation import process_observation


ROOT = Path(__file__).resolve().parents[1]
VARIANTS = ("baseline_b8", "observed_82")
BOOT_SECONDS = 600
CAP = 65535
PATTERNS = {
    "kernel_boot": b"Linux version ",
    "disk_full": b"No space left on device",
    "disk_insufficient": b"Not enough disk space",
    "unknown_option": b"unknown option:",
    "invalid_option": b"invalid option",
    "kvm_unavailable": b"Could not access KVM kernel module",
    "kvm_permission": b"Could not open /dev/kvm",
    "kvm_initialization": b"failed to initialize kvm",
    "acceleration_required": b"requires hardware acceleration",
    "avd_unknown": b"Unknown AVD name",
    "avd_path": b"Broken AVD system path",
    "qt_platform": b"no Qt platform plugin could be initialized",
    "gpu_initialization": b"Could not initialize OpenglES emulation",
    "stdio_conflict": b"cannot use stdio by multiple character devices",
    "serial_backend": b"could not connect serial device",
    "stdio_unavailable": b"cannot set up stdio",
    "property_too_long": b"property value too long",
}


class BootConsole:
    """Drain to EOF; keep counts of fixed signatures, never arbitrary text."""
    def __init__(self):
        self.counts = Counter()
        self.lines = self.oversized = 0
        self.eof = self.failed = False
        self.thread = None

    def consume(self, stream):
        discarding = False
        try:
            while line := stream.readline(8193):
                if len(line) > 8192 or discarding:
                    if not discarding:
                        self.oversized = min(CAP, self.oversized + 1)
                    discarding = not line.endswith(b"\n")
                    continue
                self.lines = min(CAP, self.lines + 1)
                for label, pattern in PATTERNS.items():
                    if pattern.lower() in line.lower():
                        self.counts[label] = min(CAP, self.counts[label] + 1)
            self.eof = True
        except Exception:
            self.failed = True

    def start(self, stream):
        self.thread = threading.Thread(target=self.consume, args=(stream,), daemon=True)
        self.thread.start()

    def finish(self, stream):
        if self.thread is not None and self.thread.ident is not None:
            self.thread.join(2)
            if self.thread.is_alive():
                raise PeerFailure("emulator_observer_retirement_failed")
        stream.close()

    def snapshot(self):
        # Only called after join or when retaining a failed retirement. Counts
        # are independent signature observations, not an atomic guest timeline.
        return {"lines": self.lines, "oversized_lines": self.oversized,
                "counts": {label: self.counts[label] for label in PATTERNS},
                "reader_eof": self.eof, "reader_failed": self.failed}


def launch_command(emulator, variant):
    if variant not in VARIANTS:
        raise ValueError("Unknown declared variant")
    command = [str(emulator.sdk / "emulator/emulator"), "-avd", emulator.name,
        "-port", "5554", "-no-window", "-gpu", "swiftshader_indirect", "-accel", "on",
        "-no-snapshot", "-noaudio", "-no-boot-anim", "-camera-back", "none", "-camera-front", "none"]
    options = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "start_new_session": True}
    if variant == "observed_82":
        command += ["-show-kernel", "-logcat", LOG_TAGS]
        options.update(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return command, options


def checked_failure(error):
    known = {"PeerFailure", "ValueError", "RuntimeError", "CalledProcessError", "TimeoutExpired", "OSError"}
    result = {"exception_kind": type(error).__name__ if type(error).__name__ in known else "other"}
    if isinstance(error, PeerFailure):
        allowed = {"unowned_android_device_present", "avdmanager_unavailable", "emulator_exited_during_boot",
                   "emulator_boot_deadline", "emulator_retirement_failed", "emulator_observer_retirement_failed",
                   "emulator_cleanup_path_changed", "linux_kvm_ci_required"}
        result["error_code"] = error.code if error.code in allowed else "other"
    return result


def prepare_avd(emulator):
    devices = subprocess.check_output([str(emulator.sdk / "platform-tools/adb"), "devices"],
                                      stderr=subprocess.DEVNULL, text=True, timeout=15)
    if any(line.strip() for line in devices.splitlines()[1:]):
        raise PeerFailure("unowned_android_device_present")
    emulator.root.mkdir(exist_ok=False)
    for key, value in {"ANDROID_AVD_HOME": str(emulator.root), "ANDROID_SERIAL": emulator.serial}.items():
        emulator.old_environment[key] = os.environ.get(key)
        os.environ[key] = value
    manager = shutil.which("avdmanager")
    if not manager:
        raise PeerFailure("avdmanager_unavailable")
    subprocess.run([manager, "create", "avd", "--name", emulator.name, "--package", emulator.IMAGE],
                   input=b"no\n", check=True, capture_output=True, timeout=120)


def retire(emulator, console):
    """Keep exact process/reader/AVD custody when any retirement is unresolved."""
    process = emulator.process
    if process is not None:
        if process.poll() is None:
            try:
                emulator._adb("emu", "kill")
                process.wait(timeout=30)
            except Exception:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=15)
        if process.poll() is None:
            raise PeerFailure("emulator_retirement_failed")
        if process.stdout is not None:
            console.finish(process.stdout)
        emulator.process = None
    if emulator.root.parent != Path(os.environ["RUNNER_TEMP"]).resolve() or emulator.root.name != emulator.name:
        raise PeerFailure("emulator_cleanup_path_changed")
    if emulator.root.exists():
        shutil.rmtree(emulator.root)
    for key, previous in emulator.old_environment.items():
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def run_case(variant, update):
    result = {"variant": variant, "status": "running", "booted": False, "cleanup_failures": []}
    emulator = None
    console = BootConsole()

    def stage(name):
        result["stage"] = name
        update(result)

    try:
        stage("avd_prepare")
        emulator = AndroidEmulator()
        prepare_avd(emulator)
        stage("launch")
        command, options = launch_command(emulator, variant)
        emulator.process = subprocess.Popen(command, **options)
        if emulator.process.stdout is not None:
            console.start(emulator.process.stdout)
        stage("boot")
        deadline = time.monotonic() + BOOT_SECONDS
        while time.monotonic() < deadline:
            if emulator.process.poll() is not None:
                raise PeerFailure("emulator_exited_during_boot")
            try:
                if emulator._adb("shell", "getprop", "sys.boot_completed", timeout=5) == "1":
                    result["booted"] = True
                    break
            except Exception:
                pass
            time.sleep(1)
        if not result["booted"]:
            raise PeerFailure("emulator_boot_deadline")
    except Exception as error:
        result["primary_failure"] = {"stage": result["stage"], **checked_failure(error)}
    finally:
        result["process_before_cleanup"] = process_observation(emulator.process if emulator else None)
        try:
            stage("cleanup")
        finally:
            if emulator is not None:
                try:
                    retire(emulator, console)
                except Exception as error:
                    result["cleanup_failures"].append(checked_failure(error))
            result["console"] = console.snapshot() if variant == "observed_82" else {"capture": "discarded_as_baseline"}
            result["status"] = "completed"
            result["passed"] = result["booted"] and not result["cleanup_failures"] and "primary_failure" not in result
            update(result)
    return result


def git(*arguments):
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True,
                                   stderr=subprocess.DEVNULL, timeout=15).strip()


def binding(expected):
    if not re.fullmatch(r"[a-f0-9]{40}", expected) or git("rev-parse", "HEAD") != expected:
        raise ValueError("Wrong diagnostic source")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise ValueError("Modified diagnostic source")
    names = ("scripts/native_emulator_boot_diagnostic.py", "scripts/native_interop_peers.py",
             "scripts/native_interop_android_system.py", ".github/workflows/native-restart-diagnostic.yml",
             ".github/workflows/android-webrtc.yml")
    return {"source_commit": expected, "source_tree": git("rev-parse", "HEAD^{tree}"),
            "source_blobs": {name: git("rev-parse", "HEAD:" + name) for name in names}}


def package_versions():
    sdk = Path(os.environ.get("ANDROID_SDK_ROOT") or os.environ["ANDROID_HOME"])
    result = {}
    for name in ("emulator", "system-images/android-35/google_apis/x86_64"):
        data = (sdk / name / "source.properties").read_bytes()
        match = re.search(rb"(?m)^Pkg.Revision\s*=\s*([0-9.]+)\s*$", data)
        if not match:
            raise ValueError("Package revision missing")
        result[name] = {"revision": match[1].decode("ascii"), "metadata_sha256": hashlib.sha256(data).hexdigest()}
    return result


def write_report(output, report):
    encoded = json.dumps(report, indent=2) + "\n"
    if len(encoded.encode()) > 65536:
        raise ValueError("Diagnostic report bound exceeded")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(output)


def run(expected, output):
    report = {"v": 1, "passed": False, "diagnostic_only": True,
              "evidence_level": "emulator_boot_launch_comparison_only", "status": "running",
              "scope": "One baseline/current boot pair; no APK, profile, product host, receipt or qualification",
              "declared_pairs": 1, "declared_order": list(VARIANTS), "attempts": []}
    write_report(output, report)
    try:
        if (sys.platform != "linux" or os.environ.get("GITHUB_ACTIONS") != "true"
                or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
                or os.environ.get("GITHUB_JOB") != "android_restart_diagnostic"
                or os.environ.get("GITHUB_SHA") != expected):
            raise RuntimeError("Manual Linux diagnostic context required")
        report.update(binding(expected))
        report["run"] = {"run_id": int(os.environ["GITHUB_RUN_ID"]),
                         "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"])}
        report["packages"] = package_versions()
        report["environment"] = {"image": AndroidEmulator.IMAGE, "port": 5554, "kvm": True,
                                 "boot_seconds": BOOT_SECONDS, "gateway": "ordinary_runner_not_qualification_namespace"}
        for variant in VARIANTS:
            report["attempts"].append({"variant": variant, "status": "running"})
            def update(result):
                report["attempts"][-1] = result
                write_report(output, report)
            result = run_case(variant, update)
            if result["cleanup_failures"]:
                for remaining in VARIANTS[len(report["attempts"]):]:
                    report["attempts"].append({"variant": remaining, "status": "not_run",
                        "reason": "prior_cleanup_unresolved", "passed": False})
                break
        if binding(expected) != {key: report[key] for key in ("source_commit", "source_tree", "source_blobs")}:
            raise ValueError("Source changed during diagnostic")
        if package_versions() != report["packages"]:
            raise ValueError("Emulator package changed during diagnostic")
        report["passed"] = all(item.get("passed") is True for item in report["attempts"])
    except Exception as error:
        report["runner_failure"] = checked_failure(error)
    report["status"] = "completed"
    write_report(output, report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.expected_source, args.output)
    print("Emulator boot launch comparison " + ("passed" if report["passed"] else "failed"))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
