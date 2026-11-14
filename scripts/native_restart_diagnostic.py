"""Manual packaged Android reopen probe; its output is never qualification."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from android_qualification import APKS
from native_interop_android_observation import PROCESS_STATES, android_lifecycle_snapshot, process_observation
from native_interop_android_start import KINDS as START_KINDS, start_failure_snapshot
from native_interop_android_system import system_snapshot
from native_interop_peers import AndroidEmulator, AndroidPeer, PeerFailure


ROOT = Path(__file__).resolve().parents[1]
STAGES = frozenset({"source_binding", "artifact_binding", "emulator_start", "peer_start",
                    "initial_profile", "old_stop", "peer_reopen", "reopened_profile",
                    "emulator_start_rollback", "peer_cleanup", "emulator_cleanup", "complete", "attempts", "postrun_binding",
                    "report_checkpoint"})
EXCEPTION_KINDS = frozenset({"PeerFailure", "ValueError", "RuntimeError", "CalledProcessError",
                             "TimeoutExpired", "OSError", "KeyError", "TypeError"})
SAFE_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
MAX_REPORT_BYTES = 256 * 1024
SCOPE = ("diagnostic_only: one packaged Android host opens, crash-stops and reopens; "
         "no paired message/receipt, path prefix, fault matrix or full native acceptance")


def git(*arguments):
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True,
                                   stderr=subprocess.DEVNULL, timeout=15).strip()


def source_binding(expected):
    if not re.fullmatch(r"[a-f0-9]{40}", expected):
        raise ValueError("Invalid expected source")
    source, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
    if source != expected or git("status", "--porcelain", "--untracked-files=no"):
        raise ValueError("Diagnostic checkout differs from the selected source")
    required = (".github/workflows/native-restart-diagnostic.yml",
                "scripts/native_restart_diagnostic.py", "scripts/native_interop_peers.py",
                "scripts/native_interop_android_system.py")
    return {"source_commit": source, "source_tree": tree,
            "source_blobs": {name: git("rev-parse", f"HEAD:{name}") for name in required}}


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact_binding():
    return {path.relative_to(ROOT).as_posix(): sha256_file(path) for path in APKS}


def write_report(path, report):
    """Replace one bounded JSON snapshot; a failed write keeps the prior snapshot."""
    encoded = (json.dumps(report, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(encoded) > MAX_REPORT_BYTES:
        raise ValueError("Diagnostic report exceeds its bounded artifact budget")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def emulator_start_snapshot(value):
    if type(value) is not dict or set(value) != {"process", "cleanup_exception_kind"}:
        return None
    process = value["process"]
    if (type(process) is not dict or set(process) != {"state", "exit_status"}
            or type(process["state"]) is not str or process["state"] not in PROCESS_STATES):
        return None
    status = process["exit_status"]
    if ((process["state"] == "exited") != (type(status) is int)
            or (type(status) is int and not -255 <= status <= 255)
            or (process["state"] != "exited" and status is not None)):
        return None
    cleanup = value["cleanup_exception_kind"]
    if cleanup is not None and (type(cleanup) is not str or cleanup not in START_KINDS):
        return None
    return {"process": dict(process), "cleanup_exception_kind": cleanup}


def failure(error, stage, peer=None, emulator=None):
    kind = type(error).__name__
    result = {"stage": stage if stage in STAGES else "attempts",
              "exception_kind": kind if kind in EXCEPTION_KINDS else "other"}
    if isinstance(error, PeerFailure):
        result["error_code"] = error.code if SAFE_CODE.fullmatch(error.code) else "peer_unavailable"
    if peer is not None:
        try:
            selected = start_failure_snapshot(peer.failure_start_observation(error))
            if selected is not None:
                result["android_start_failure"] = selected
        except Exception:
            pass
        try:
            selected = android_lifecycle_snapshot(peer.failure_lifecycle_observation(error))
            if selected is not None:
                result["android_lifecycle_failure"] = selected
        except Exception:
            pass
    if emulator is not None:
        try:
            provider = getattr(emulator, "failure_start_observation", None)
            selected = emulator_start_snapshot(provider(error)) if callable(provider) else None
            if selected is not None:
                result["emulator_start_failure"] = selected
        except Exception:
            pass
        try:
            selected = system_snapshot(emulator.observation.snapshot())
            if selected is not None:
                result["android_system_observation"] = selected
        except Exception:
            pass
        try:
            result["emulator_process"] = process_observation(emulator.process)
        except Exception:
            pass
    return result


def authority(peer):
    capabilities = peer.core("runtime.capabilities")
    profiles = capabilities.get("profiles") if type(capabilities) is dict else None
    snapshot = peer.core("application.snapshot")
    profile = snapshot.get("profile") if type(snapshot) is dict else None
    identity = profile.get("destination_hash") if type(profile) is dict else None
    if (type(profiles) is not list or len(profiles) != 1 or type(profiles[0]) is not str
            or type(identity) is not str or not identity):
        raise ValueError("Packaged caller-visible profile handle or identity unavailable")
    return profiles[0], identity


def run_attempt(index, emulator_factory=AndroidEmulator, peer_factory=AndroidPeer, observe=None):
    result = {"index": index, "passed": False, "stage": "emulator_start", "cleanup_failures": []}
    emulator = peer = None
    def mark(stage):
        result["stage"] = stage
        if observe is not None:
            selected = {"index": index, "stage": stage}
            if "primary_failure" in result:
                selected["primary_failure"] = result["primary_failure"]
            if result["cleanup_failures"]:
                selected["cleanup_failures"] = list(result["cleanup_failures"])
            observe(selected)
    mark("emulator_start")
    try:
        emulator = emulator_factory()
        emulator.start(APKS)
        mark("peer_start")
        peer = peer_factory(os.urandom(32))
        peer.system_observation = emulator.observation
        first_inventory = peer.start()
        mark("initial_profile")
        profile, identity = authority(peer)
        mark("old_stop")
        peer.stop(crash=True, _origin="old_stop")
        mark("peer_reopen")
        second_inventory = peer.start()
        mark("reopened_profile")
        reopened_profile, reopened_identity = authority(peer)
        if (second_inventory["service_incarnation"] == first_inventory["service_incarnation"]
                or reopened_profile != profile or reopened_identity != identity):
            raise ValueError("Reopen changed service, caller-visible profile handle or durable identity")
        result["reopen"] = {"service_replaced": True, "profile_handle_preserved": True,
                            "identity_preserved": True}
    except Exception as error:
        result["primary_failure"] = failure(error, result["stage"], peer, emulator)
        mark(result["stage"])
        startup = result["primary_failure"].get("emulator_start_failure", {})
        if startup.get("cleanup_exception_kind") is not None:
            result["cleanup_failures"].append({"stage": "emulator_start_rollback",
                                               "exception_kind": startup["cleanup_exception_kind"]})
            mark(result["stage"])
    finally:
        if peer is not None and peer.process is not None:
            try:
                mark("peer_cleanup")
                peer.stop(delete_profile=True)
                if peer.process is not None:
                    raise RuntimeError("Peer process remained after cleanup")
            except Exception as error:
                result["cleanup_failures"].append(failure(error, "peer_cleanup", peer, emulator))
                mark("peer_cleanup")
        if emulator is not None:
            try:
                mark("emulator_cleanup")
                emulator.close()
                if emulator.process is not None:
                    raise RuntimeError("Emulator process remained after cleanup")
            except Exception as error:
                result["cleanup_failures"].append(failure(error, "emulator_cleanup", peer, emulator))
                mark("emulator_cleanup")
        primary = result.get("primary_failure", {})
        start = primary.get("android_start_failure", {})
        result["retirement_verified"] = (not result["cleanup_failures"]
            and (peer is None or peer.process is None)
            and (emulator is None or emulator.process is None)
            and primary.get("stage") != "old_stop"
            and start.get("rollback_exception_kind") is None)
        result["passed"] = "primary_failure" not in result and not result["cleanup_failures"]
        result["stage"] = "complete" if result["passed"] else result.get("primary_failure", {}).get(
            "stage", result["cleanup_failures"][0]["stage"] if result["cleanup_failures"] else "complete")
    return result


def run(expected_source, repetitions, checkpoint=None):
    report = {"v": 1, "passed": False, "diagnostic_only": True,
              "evidence_level": "android_packaged_reopen_diagnostic_only", "scope": SCOPE,
              "declared_repetitions": repetitions, "attempts": [], "current_attempt": None}
    persistence_failed = False
    def save():
        nonlocal persistence_failed
        if checkpoint is None:
            return True
        try:
            checkpoint(report)
            return True
        except Exception:
            persistence_failed = True
            return False
    def block_remaining(first, reason):
        for index in range(first, repetitions + 1):
            report["attempts"].append({"index": index, "passed": False, "blocked": True,
                                       "reason": reason, "retirement_verified": False})
            report["current_attempt"] = None
            save()
    stage = "source_binding"
    try:
        if type(repetitions) is not int or not 1 <= repetitions <= 3:
            raise ValueError("Repetitions must be an integer from 1 to 3")
        if (sys.platform != "linux" or os.environ.get("GITHUB_ACTIONS") != "true"
                or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
                or os.environ.get("GITHUB_JOB") != "android_restart_diagnostic"
                or os.environ.get("GITHUB_SHA") != expected_source):
            raise RuntimeError("Manual Linux CI diagnostic context required")
        report.update(source_binding(expected_source))
        stage = "artifact_binding"
        report["run"] = {"repository": os.environ["GITHUB_REPOSITORY"],
                         "run_id": int(os.environ["GITHUB_RUN_ID"]),
                         "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"])}
        report["artifacts"] = artifact_binding()
        report["environment"] = {"image": AndroidEmulator.IMAGE, "api_level": 35,
                                 "abi": "x86_64", "host": "ubuntu-latest", "kvm": True}
        report["artifact_origin"] = {"source_commit": report["source_commit"],
                                     "build": "same_workflow_job", "qualification_verified": False}
        stage = "attempts"
        if not save():
            stage = "report_checkpoint"
            raise RuntimeError("Initial diagnostic checkpoint unavailable")
        for index in range(1, repetitions + 1):
            report["current_attempt"] = {"index": index, "stage": "emulator_start"}
            if not save():
                stage = "report_checkpoint"
                raise RuntimeError("Diagnostic checkpoint unavailable")
            def observe(current):
                report["current_attempt"] = current
                save()
            try:
                attempt = run_attempt(index, observe=observe)
            except Exception as error:
                attempt = {"index": index, "passed": False, "stage": "attempts",
                           "primary_failure": failure(error, "attempts"), "cleanup_failures": [],
                           "retirement_verified": False}
            report["attempts"].append(attempt)
            report["current_attempt"] = None
            save()
            if persistence_failed:
                stage = "report_checkpoint"
                report["runner_failure"] = {"stage": stage, "exception_kind": "other"}
                block_remaining(index + 1, "report_checkpoint_unavailable")
                break
            if attempt.get("retirement_verified") is not True:
                block_remaining(index + 1, "prior_retirement_unresolved")
                break
        stage = "postrun_binding"
        if source_binding(expected_source) != {key: report[key] for key in ("source_commit", "source_tree", "source_blobs")}:
            raise ValueError("Diagnostic source changed during execution")
        if artifact_binding() != report["artifacts"]:
            raise ValueError("Packaged APK changed during execution")
        report["passed"] = (not persistence_failed and len(report["attempts"]) == repetitions
                            and all(attempt["passed"] for attempt in report["attempts"]))
    except Exception as error:
        report.setdefault("runner_failure", failure(error, stage))
    save()
    if persistence_failed:
        report["passed"] = False
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--repetitions", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        repetitions = int(args.repetitions)
    except ValueError:
        repetitions = args.repetitions[:32]
    report = run(args.expected_source, repetitions, checkpoint=lambda value: write_report(args.output, value))
    if not args.output.is_file():
        try:
            write_report(args.output, report)
        except Exception:
            print("Android packaged reopen diagnostic report could not be retained")
            return 1
    print("Android packaged reopen diagnostic " + ("passed" if report["passed"] else "failed"))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
