"""Manual packaged Android reopen probe; its output is never qualification."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from android_qualification import APKS
from native_interop_android_observation import android_lifecycle_snapshot, process_observation
from native_interop_android_start import start_failure_snapshot
from native_interop_android_system import system_snapshot
from native_interop_peers import AndroidEmulator, AndroidPeer, PeerFailure


ROOT = Path(__file__).resolve().parents[1]
STAGES = frozenset({"source_binding", "artifact_binding", "emulator_start", "peer_start",
                    "initial_authority", "old_stop", "peer_reopen", "reopened_authority",
                    "peer_cleanup", "emulator_cleanup", "complete", "attempts", "postrun_binding"})
EXCEPTION_KINDS = frozenset({"PeerFailure", "ValueError", "RuntimeError", "CalledProcessError",
                             "TimeoutExpired", "OSError", "KeyError", "TypeError"})
SAFE_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
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
        raise ValueError("Packaged profile authority or identity unavailable")
    return profiles[0], identity


def run_attempt(index, emulator_factory=AndroidEmulator, peer_factory=AndroidPeer):
    result = {"index": index, "passed": False, "stage": "emulator_start", "cleanup_failures": []}
    emulator = peer = None
    try:
        emulator = emulator_factory()
        emulator.start(APKS)
        result["stage"] = "peer_start"
        peer = peer_factory(os.urandom(32))
        peer.system_observation = emulator.observation
        first_inventory = peer.start()
        result["stage"] = "initial_authority"
        profile, identity = authority(peer)
        result["stage"] = "old_stop"
        peer.stop(crash=True, _origin="old_stop")
        result["stage"] = "peer_reopen"
        second_inventory = peer.start()
        result["stage"] = "reopened_authority"
        reopened_profile, reopened_identity = authority(peer)
        if (second_inventory["service_incarnation"] == first_inventory["service_incarnation"]
                or reopened_profile != profile or reopened_identity != identity):
            raise ValueError("Reopen changed service, profile authority or durable identity")
        result["reopen"] = {"service_replaced": True, "profile_authority_preserved": True,
                            "identity_preserved": True}
    except Exception as error:
        result["primary_failure"] = failure(error, result["stage"], peer, emulator)
    finally:
        if peer is not None and peer.process is not None:
            try:
                result["stage"] = "peer_cleanup"
                peer.stop(delete_profile=True)
                if peer.process is not None:
                    raise RuntimeError("Peer process remained after cleanup")
            except Exception as error:
                result["cleanup_failures"].append(failure(error, "peer_cleanup", peer, emulator))
        if emulator is not None:
            try:
                result["stage"] = "emulator_cleanup"
                emulator.close()
                if emulator.process is not None:
                    raise RuntimeError("Emulator process remained after cleanup")
            except Exception as error:
                result["cleanup_failures"].append(failure(error, "emulator_cleanup", peer, emulator))
        result["passed"] = "primary_failure" not in result and not result["cleanup_failures"]
        result["stage"] = "complete" if result["passed"] else result.get("primary_failure", {}).get(
            "stage", result["cleanup_failures"][0]["stage"] if result["cleanup_failures"] else "complete")
    return result


def run(expected_source, repetitions):
    report = {"v": 1, "passed": False, "diagnostic_only": True,
              "evidence_level": "android_packaged_reopen_diagnostic_only", "scope": SCOPE,
              "declared_repetitions": repetitions, "attempts": []}
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
        for index in range(1, repetitions + 1):
            try:
                attempt = run_attempt(index)
            except Exception as error:
                attempt = {"index": index, "passed": False, "stage": "attempts",
                           "primary_failure": failure(error, "attempts"), "cleanup_failures": []}
            report["attempts"].append(attempt)
        stage = "postrun_binding"
        if source_binding(expected_source) != {key: report[key] for key in ("source_commit", "source_tree", "source_blobs")}:
            raise ValueError("Diagnostic source changed during execution")
        if artifact_binding() != report["artifacts"]:
            raise ValueError("Packaged APK changed during execution")
        report["passed"] = all(attempt["passed"] for attempt in report["attempts"])
    except Exception as error:
        report["runner_failure"] = failure(error, stage)
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
    report = run(args.expected_source, repetitions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Android packaged reopen diagnostic " + ("passed" if report["passed"] else "failed"))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
