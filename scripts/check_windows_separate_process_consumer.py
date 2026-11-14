"""Installed Windows public-SDK separate-process lifetime diagnostic only."""

import argparse
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
from uuid import uuid4

import check_independent_core_consumers as bootstrap
from native_windows_evidence import require_unchanged
from stage_core_sdk import tools
from stage_independent_core_consumers import ROOT, FILES, cleanup, digest, install_typescript, outside_directory
from windows_public_consumer_session import verified_inputs


REPORT = ROOT / "dist/reports/windows-independent-separate-process.json"
LEVEL = "windows_installed_public_sdk_separate_consumer_process_lifetime"
SCOPE = ("Outside-checkout Windows TypeScript public SDK and frozen normal owner with separate attach-only "
         "consumer processes, fresh EFS profile and positive owner/helper exits; no pairing, pending work, "
         "receipts, wrong-image, cross-app isolation, Android or SC22/SC26 acceptance")
FIXTURE_SCOPE = ("Installed Windows public SDK separate-process attach/detach and owner stop on one fresh "
                 "profile; no pairing, pending work, receipts, wrong-image, cross-app isolation, Android "
                 "or SC22/SC26 acceptance")
FIXTURE_CHECKS = {"normal_owners": 1, "distinct_helper_processes": 2, "clean_helper_detaches": 1,
                  "owner_survived_detach": True, "replacement_shared_fresh_state": True,
                  "positive_owner_stop": True, "post_stop_helper_request_rejected": True,
                  "bounded_helper_exit": True}
FIXTURE_FAILURE_PHASES = frozenset({"arguments", "owner_start", "fresh_profile",
    "first_helper_attach", "first_helper_detach", "replacement_helper_attach", "owner_stop",
    "helper_after_stop"})
CHECKS = {**FIXTURE_CHECKS, "efs_profile_directory": True, "efs_vault_file": True}
MAX_STDOUT = 4096
MAX_STDERR = 1024
TOTAL_SECONDS = 600
CHILD_SECONDS = 240


def _unique_object(pairs):
    selected = {}
    for key, value in pairs:
        if key in selected:
            raise ValueError("fixture_duplicate_field")
        selected[key] = value
    return selected


def _reject_constant(_value):
    raise ValueError("fixture_nonfinite")


def fixture_result(raw):
    """Accept one exact, bounded, content-free result from the installed app."""
    if (type(raw) is not bytes or not 0 < len(raw) <= MAX_STDOUT
            or raw.count(b"\n") != 1 or not raw.endswith(b"\n")):
        raise ValueError("fixture_frame")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if (type(value) is not dict or set(value) != {"v", "passed", "scope", "checks", "duration_ms"}
            or type(value["v"]) is not int or value["v"] != 1 or value["passed"] is not True
            or value["scope"] != FIXTURE_SCOPE or type(value["checks"]) is not dict
            or set(value["checks"]) != set(FIXTURE_CHECKS)
            or any(type(value["checks"][key]) is not type(expected) or value["checks"][key] != expected
                   for key, expected in FIXTURE_CHECKS.items())
            or type(value["duration_ms"]) is not int or not 0 <= value["duration_ms"] < CHILD_SECONDS * 1000):
        raise ValueError("fixture_result")
    return value


def fixture_failure(raw):
    """Select only an exact fixed failure phase; discard all other child output."""
    try:
        if (type(raw) is not bytes or not 0 < len(raw) <= MAX_STDOUT
                or raw.count(b"\n") != 1 or not raw.endswith(b"\n")):
            return None
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
        if (type(value) is dict and set(value) == {"v", "passed", "scope", "phase", "duration_ms"}
                and type(value["v"]) is int and value["v"] == 1 and value["passed"] is False
                and value["scope"] == FIXTURE_SCOPE and type(value["phase"]) is str
                and value["phase"] in FIXTURE_FAILURE_PHASES
                and type(value["duration_ms"]) is int and 0 <= value["duration_ms"] <= CHILD_SECONDS * 1000):
            return value["phase"]
    except (ValueError, UnicodeError, TypeError):
        pass
    return None


class FixtureExecutionFailure(ValueError):
    def __init__(self, failure_phase=None):
        super().__init__("fixture_process")
        self.failure_phase = failure_phase


class _Capture:
    def __init__(self, limit, fault):
        self.limit = limit
        self.fault = fault
        self.data = bytearray()
        self.overflow = False
        self.failed = False

    def drain(self, stream):
        try:
            while chunk := stream.read(4096):
                allowed = max(0, self.limit - len(self.data))
                self.data.extend(chunk[:allowed])
                if len(chunk) > allowed:
                    self.overflow = True
                    self.fault.set()
        except Exception:
            self.failed = True
            self.fault.set()
        finally:
            try: stream.close()
            except Exception:
                self.failed = True
                self.fault.set()


def run_fixture(node, directory, runtime, data, overall_deadline):
    """Own exactly one child, its bounded readers and one monotonic retirement window."""
    started = time.monotonic()
    deadline = min(overall_deadline, started + CHILD_SECONDS)
    if deadline <= started:
        raise TimeoutError("fixture_deadline")
    retirement_reserve = min(10, max(0.05, (deadline - started) / 4))
    work_deadline = deadline - retirement_reserve
    if work_deadline <= started:
        raise TimeoutError("fixture_deadline")
    process = None
    readers = []
    fault = threading.Event()
    output = _Capture(MAX_STDOUT, fault)
    error = _Capture(MAX_STDERR, fault)
    try:
        process = subprocess.Popen([node, "separate-process-check.mjs", "--runtime", str(runtime),
            "--data-directory", str(data)], cwd=directory,
            env=bootstrap.application_environment(os.environ), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        for capture, stream in ((output, process.stdout), (error, process.stderr)):
            reader = threading.Thread(target=capture.drain, args=(stream,), daemon=True)
            reader.start()
            readers.append(reader)
        while process.poll() is None:
            if fault.is_set():
                raise ValueError("fixture_output_budget")
            remaining = work_deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("fixture_deadline")
            time.sleep(min(0.05, remaining))
        for reader in readers:
            reader.join(timeout=max(0, work_deadline - time.monotonic()))
            if reader.is_alive():
                raise TimeoutError("fixture_reader_deadline")
        if time.monotonic() >= work_deadline:
            raise TimeoutError("fixture_deadline")
        if fault.is_set() or output.overflow or error.overflow or output.failed or error.failed:
            raise ValueError("fixture_process")
        if process.returncode != 0:
            raise FixtureExecutionFailure(fixture_failure(bytes(output.data)) if not error.data else None)
        if error.data:
            raise ValueError("fixture_process")
        return bytes(output.data)
    finally:
        if process is not None:
            if process.poll() is None:
                try: process.kill()
                except OSError: pass
            try: process.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired: pass
            for reader in readers:
                reader.join(timeout=max(0, deadline - time.monotonic()))


def verify_report(record, source, tree):
    fields = {"v", "passed", "evidence_level", "scope", "source_commit", "source_tree",
              "sidecar_sha256", "build_input_sha256", "build_manifest_sha256", "sdk_sha256",
              "sdk_artifact", "bootstrap_report_sha256", "application", "runtime_installed_outside_checkout",
              "run_id", "checks", "fixture_duration_ms", "duration_seconds", "cleanup"}
    if type(record) is not dict or set(record) != fields:
        raise ValueError("separate_process_report_shape")
    try: bootstrap.verify_binding(record, source, tree)
    except (ValueError, AttributeError, TypeError, KeyError):
        raise ValueError("separate_process_report_binding") from None
    application = record["application"]
    entry = application.get("installed_sdk_entry") if type(application) is dict else None
    if (record["evidence_level"] != LEVEL or record["scope"] != SCOPE
            or type(record["checks"]) is not dict or set(record["checks"]) != set(CHECKS)
            or any(type(record["checks"][key]) is not type(expected) or record["checks"][key] != expected
                   for key, expected in CHECKS.items())
            or type(record["fixture_duration_ms"]) is not int
            or not 0 <= record["fixture_duration_ms"] < CHILD_SECONDS * 1000
            or type(record["duration_seconds"]) not in {int, float}
            or not math.isfinite(record["duration_seconds"])
            or not 0 <= record["duration_seconds"] < TOTAL_SECONDS
            or type(record["bootstrap_report_sha256"]) is not str
            or re.fullmatch(r"[a-f0-9]{64}", record["bootstrap_report_sha256"]) is None
            or type(application) is not dict
            or set(application) != {"application_files", "installed_sdk_entry",
                                    "installed_outside_checkout", "imports_public_package"}
            or type(entry) is not str
            or not entry.startswith("node_modules/@mesh-chat/core-client/")
            or ".." in entry.split("/")
            or record["cleanup"] != "passed"):
        raise ValueError("separate_process_report_scope")
    return record


def run(expected_source, *, bootstrap_report=None, temporary_root=None):
    started = time.monotonic()
    deadline = started + TOTAL_SECONDS
    prior_report = Path(bootstrap_report or ROOT / "dist/reports/windows-independent-bootstrap.json")
    parent = Path(temporary_root or os.environ.get("RUNNER_TEMP") or tempfile.gettempdir())
    result = {"v": 1, "passed": False, "evidence_level": LEVEL, "scope": SCOPE}
    directory = None
    phase = "source_artifact_binding"
    try:
        binary, binding, sdk, report_hash = verified_inputs(expected_source, prior_report)
        sdk_hash = digest(sdk)
        node, npm = tools()
        if time.monotonic() >= deadline:
            raise TimeoutError("producer_deadline")
        phase = "outside_checkout_installation"
        directory = outside_directory(parent)
        installed = install_typescript(directory, sdk, node, npm)
        runtime = directory / binary.name
        shutil.copy2(binary, runtime)
        if (digest(runtime) != binding["sidecar_sha256"] or digest(sdk) != sdk_hash
                or any(digest(directory / name) != value for name, value in installed["application_files"].items())):
            raise ValueError("installed_inputs_changed")
        require_unchanged(binary, binding)
        if time.monotonic() >= deadline:
            raise TimeoutError("producer_deadline")
        phase = "separate_process_execution"
        data = directory / "app-data"
        observed = fixture_result(run_fixture(node, directory, runtime, data, deadline))
        phase = "protected_profile"
        protection = bootstrap.protected_profile(data)
        phase = "final_artifact_binding"
        require_unchanged(binary, binding)
        if (digest(runtime) != binding["sidecar_sha256"] or digest(sdk) != sdk_hash
                or digest(prior_report) != report_hash
                or any(digest(directory / name) != value for name, value in installed["application_files"].items())):
            raise ValueError("installed_inputs_changed")
        if time.monotonic() >= deadline:
            raise TimeoutError("producer_deadline")
        candidate = {"v": 1, "passed": True, "evidence_level": LEVEL, "scope": SCOPE,
                     **binding, "sdk_sha256": sdk_hash, "sdk_artifact": bootstrap.SDK_ARTIFACT,
                     "bootstrap_report_sha256": report_hash, "application": installed,
                     "runtime_installed_outside_checkout": True, "run_id": uuid4().hex,
                     "checks": {**observed["checks"], **protection},
                     "fixture_duration_ms": observed["duration_ms"],
                     "duration_seconds": time.monotonic() - started, "cleanup": "passed"}
        verify_report(candidate, binding["source_commit"], binding["source_tree"])
        phase = "owned_workspace_cleanup"
        if deadline - time.monotonic() < 30:
            raise TimeoutError("producer_cleanup_reserve")
        cleanup(directory, parent)
        candidate["duration_seconds"] = time.monotonic() - started
        if candidate["duration_seconds"] >= TOTAL_SECONDS:
            raise TimeoutError("producer_deadline")
        verify_report(candidate, binding["source_commit"], binding["source_tree"])
        result = candidate
    except Exception as failure:
        result.update(phase=phase, failure_type=type(failure).__name__,
                      workspace_retained=directory is not None and directory.is_dir(),
                      duration_seconds=min(max(0, time.monotonic() - started), TOTAL_SECONDS + 60))
        if isinstance(failure, FixtureExecutionFailure) and failure.failure_phase is not None:
            result["fixture_failure"] = failure.failure_phase
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--bootstrap-report", type=Path)
    parser.add_argument("--output", type=Path, default=REPORT)
    args = parser.parse_args()
    result = run(args.expected_source, bootstrap_report=args.bootstrap_report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "phase": result.get("phase")}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
