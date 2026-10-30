"""Source-bound frozen peers over the real WebView2 private transport host."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
from time import monotonic
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
LEVEL = "windows_packaged_webview2_preapproved_peers"
CHECKS = ("bidirectional_authenticated_receipts", "durable_messages_and_receipts_after_crash", "exact_carrier_reuse")
COUNTS = {"processes_started": 3, "forced_exits": 2, "authenticated_receipts": 3}
PAIRING_LEVEL = "windows_packaged_webview2_explicit_pairing"
PAIRING_CHECKS = ("explicit_pairing_without_preapproved_contacts", "paired_bidirectional_authenticated_receipts",
                  "continuous_pairing_carrier_transfer")
PAIRING_COUNTS = {"processes_started": 2, "forced_exits": 0, "authenticated_receipts": 2}


class ScenarioFailure(RuntimeError):
    def __init__(self, result):
        super().__init__("Packaged transport scenario failed")
        self.diagnostics = {}
        if isinstance(result, dict):
            for field in ("phase", "error_type"):
                value = result.get(field)
                if isinstance(value, str) and len(value) <= 64 and value.isidentifier():
                    self.diagnostics[field] = value


def verify_report(record, source, tree):
    return _verify_record(record, source, tree, LEVEL, CHECKS, COUNTS)


def verify_pairing_report(record, source, tree):
    return _verify_record(record, source, tree, PAIRING_LEVEL, PAIRING_CHECKS, PAIRING_COUNTS)


def _verify_record(record, source, tree, level, checks, expected_counts):
    fields = {"v", "passed", "source_commit", "source_tree", "evidence_level", "run_id", "sidecar_sha256",
              "native_binary_sha256", "build_input_sha256", "checks", "counts", "duration_seconds"}
    if (not isinstance(record, dict) or set(record) != fields or type(record.get("v")) is not int
            or record["v"] != 1 or record["passed"] is not True or record["source_commit"] != source
            or record["source_tree"] != tree or record["evidence_level"] != level
            or record["checks"] != list(checks)):
        raise ValueError("Packaged transport evidence is incomplete or belongs to another source")
    counts = record["counts"]
    if (not isinstance(counts, dict) or set(counts) != set(expected_counts)
            or any(type(counts[key]) is not int or counts[key] != value for key, value in expected_counts.items())):
        raise ValueError("Packaged transport execution is incomplete")
    for field, length in (("run_id", 32), ("sidecar_sha256", 64), ("native_binary_sha256", 64), ("build_input_sha256", 64)):
        if not isinstance(record[field], str) or not re.fullmatch("[a-f0-9]{" + str(length) + "}", record[field]):
            raise ValueError("Packaged artifact or run binding is invalid")
    duration = record["duration_seconds"]
    if type(duration) not in {int, float} or not math.isfinite(duration) or duration < 0:
        raise ValueError("Packaged execution duration is invalid")
    return record


def host_result(process, source, level=LEVEL):
    records = [json.loads(line) for line in process.stdout.splitlines() if line.startswith('{"')]
    if len(records) != 1 or not isinstance(records[0], dict):
        raise RuntimeError("Host did not produce exactly one result")
    record = records[0]
    if (set(record) != {"v", "source_commit", "evidence_level", "result"}
            or type(record["v"]) is not int or record["v"] != 1
            or record["source_commit"] != source or record["evidence_level"] != level):
        raise RuntimeError("Host was not built from the required source")
    result = record["result"]
    if process.returncode != 0 or not isinstance(result, dict) or result.get("ok") is not True:
        raise ScenarioFailure(result)
    return result


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--pairing", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    level = PAIRING_LEVEL if args.pairing else LEVEL
    verify = verify_pairing_report if args.pairing else verify_report
    probe = "packaged_pairing_probe.py" if args.pairing else "packaged_transport_probe.py"
    output = args.output or ROOT / "dist/reports" / ("packaged-pairing.json" if args.pairing else "packaged-transport.json")
    result = {"v": 1, "passed": False, "evidence_level": level}
    phase = "build_binding"
    try:
        from build_sidecar import BINARIES, _build_fingerprint, _cache_is_current
        from test_packaged_lifecycle import TARGET, source_identity
        if sys.platform != "win32": raise RuntimeError("Windows packaged qualification is required")
        source, tree = source_identity(args.expected_source)
        host = ROOT / "src-tauri/target/debug/mesh-transport-qualification.exe"
        binary = BINARIES / f"mesh-chat-service-{TARGET}.exe"
        manifest = BINARIES / f".mesh-chat-service-{TARGET}.build.json"
        fingerprint = _build_fingerprint(TARGET)
        if not _cache_is_current(manifest, binary, fingerprint):
            raise RuntimeError("Frozen service does not match the source build inputs")
        artifacts = {"native_binary_sha256": digest(host), "sidecar_sha256": digest(binary)}
        phase = "packaged_transport"
        started = monotonic()
        process = subprocess.run([str(host), "--packaged", sys.executable,
            str(ROOT / "service/tools/connection_harness" / probe), str(binary)],
            cwd=ROOT, capture_output=True, text=True, timeout=260, creationflags=subprocess.CREATE_NO_WINDOW)
        observed = host_result(process, source, level)
        phase = "result_binding"
        if (source_identity(source) != (source, tree) or digest(host) != artifacts["native_binary_sha256"]
                or digest(binary) != artifacts["sidecar_sha256"] or _build_fingerprint(TARGET) != fingerprint):
            raise RuntimeError("Qualification inputs changed during execution")
        result = verify({"v": 1, "passed": True, "source_commit": source, "source_tree": tree,
            "evidence_level": level, "run_id": uuid4().hex, **artifacts, "build_input_sha256": fingerprint.lower(),
            "checks": observed.get("checks"), "counts": observed.get("counts"),
            "duration_seconds": monotonic() - started}, source, tree)
    except Exception as error:
        result.update(failure_type=type(error).__name__, phase=phase)
        if isinstance(error, ScenarioFailure): result["scenario"] = error.diagnostics
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
