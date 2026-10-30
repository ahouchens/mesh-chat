"""Require frozen Windows process lifecycle execution, with exact build inputs."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from time import monotonic
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
LEVEL = "windows_packaged_service_lifecycle_empty_adapter"
CHECKS = ("default_shutdown", "shared_shutdown", "shared_crash_reopen")
COUNTS = {"processes_started": 4, "clean_shutdowns": 3, "forced_exits": 1, "private_epochs": 3}
TARGET = "x86_64-pc-windows-msvc"


def verify_report(record, source, tree):
    fields = {"v", "passed", "source_commit", "source_tree", "evidence_level", "run_id", "sidecar_sha256",
              "build_input_sha256", "checks", "counts", "duration_seconds"}
    if (not isinstance(record, dict) or set(record) != fields or type(record.get("v")) is not int
            or record["v"] != 1 or record["passed"] is not True or record["source_commit"] != source
            or record["source_tree"] != tree or record["evidence_level"] != LEVEL
            or record["checks"] != list(CHECKS)):
        raise ValueError("Packaged lifecycle evidence is incomplete or belongs to another source")
    counts = record["counts"]
    if (not isinstance(counts, dict) or set(counts) != set(COUNTS)
            or any(type(counts[key]) is not int or counts[key] != value for key, value in COUNTS.items())):
        raise ValueError("Packaged process execution is incomplete")
    for field, length in (("run_id", 32), ("sidecar_sha256", 64), ("build_input_sha256", 64)):
        if not isinstance(record[field], str) or not re.fullmatch("[a-f0-9]{" + str(length) + "}", record[field]):
            raise ValueError("Packaged artifact or run binding is invalid")
    duration = record["duration_seconds"]
    if type(duration) not in {int, float} or not math.isfinite(duration) or duration < 0:
        raise ValueError("Packaged execution duration is invalid")
    return record


def source_identity(expected):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()
    source, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
    if source != expected or git("status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("Packaged qualification requires the exact clean source revision")
    return source, tree


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/reports/packaged-lifecycle.json")
    args = parser.parse_args()
    result = {"v": 1, "passed": False, "evidence_level": LEVEL}
    phase = "build_binding"
    try:
        from build_sidecar import BINARIES, _build_fingerprint, _cache_is_current
        if sys.platform != "win32": raise RuntimeError("Windows packaged qualification is required")
        source, tree = source_identity(args.expected_source)
        binary = BINARIES / f"mesh-chat-service-{TARGET}.exe"
        manifest = BINARIES / f".mesh-chat-service-{TARGET}.build.json"
        fingerprint = _build_fingerprint(TARGET)
        if not _cache_is_current(manifest, binary, fingerprint):
            raise RuntimeError("Packaged artifact does not match the source build inputs")
        digest = hashlib.sha256(binary.read_bytes()).hexdigest()
        sys.path[:0] = [str(ROOT / "service/src"), str(ROOT / "service")]
        from tools.connection_harness.packaged_lifecycle import exercise
        phase = "process_lifecycle"
        started = monotonic()
        with tempfile.TemporaryDirectory(prefix="mesh-packaged-lifecycle-") as directory:
            counts = exercise(binary, Path(directory))
        phase = "result_binding"
        if (source_identity(source) != (source, tree) or hashlib.sha256(binary.read_bytes()).hexdigest() != digest
                or _build_fingerprint(TARGET) != fingerprint):
            raise RuntimeError("Packaged qualification inputs changed during execution")
        result = verify_report({"v": 1, "passed": True, "source_commit": source, "source_tree": tree,
            "evidence_level": LEVEL, "run_id": uuid4().hex, "sidecar_sha256": digest,
            "build_input_sha256": fingerprint.lower(), "checks": list(CHECKS), "counts": counts,
            "duration_seconds": monotonic() - started}, source, tree)
    except Exception as error:
        result.update(failure_type=type(error).__name__, phase=phase)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
