"""Exact artifact binding for required packaged native control qualification."""

import hashlib
import json
import math
from pathlib import Path
import re
import sys
from time import monotonic
from uuid import uuid4

from build_sidecar import BINARIES, _build_fingerprint
from test_packaged_lifecycle import TARGET, source_identity

LEVELS = {
    "control": "windows_packaged_native_datachannel_control",
    "lifecycle": "windows_packaged_native_datachannel_lifecycle",
}
CHECKS = {
    "control": ("native_pair_open", "native_control_received", "no_webview_children", "clean_shutdown"),
    "lifecycle": ("100_native_pair_cycles", "100_native_controls_received", "3_cold_starts",
                  "closed_resources_unavailable", "no_webview_children", "clean_shutdown"),
}
COUNTS = {
    "control": {"processes_started": 2, "channel_pairs": 1, "controls_received": 1,
                "clean_exits": 2, "webview_processes": 0},
    "lifecycle": {"processes_started": 5, "channel_pairs": 100, "controls_received": 100,
                  "cold_starts": 3, "clean_exits": 5, "webview_processes": 0},
}
SCOPE = "Packaged native control and resource lifecycle only; no product pairing, durable message/receipt, Windows-Android, impairment or media qualification"


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_binding(expected_source, sidecar=None):
    if sys.platform != "win32":
        raise RuntimeError("Required packaged native qualification environment is Windows")
    source, tree = source_identity(expected_source)
    binary = Path(sidecar) if sidecar is not None else BINARIES / f"mesh-chat-service-{TARGET}.exe"
    if binary.name != f"mesh-chat-service-{TARGET}.exe" or not binary.is_file():
        raise RuntimeError("Required target packaged sidecar is unavailable")
    manifest = binary.parent / f".mesh-chat-service-{TARGET}.build.json"
    if manifest.stat().st_size > 16 * 1024:
        raise ValueError("Sidecar build manifest exceeds its budget")
    value = json.loads(manifest.read_text(encoding="utf-8"))
    fingerprint = _build_fingerprint(TARGET)
    output = sha256(binary)
    if (not isinstance(value, dict) or set(value) != {"schema_version", "input_sha256", "output_sha256", "output"}
            or type(value.get("schema_version")) is not int or value["schema_version"] != 1
            or value.get("output") != binary.name or value.get("input_sha256") != fingerprint
            or value.get("output_sha256") != output.upper()):
        raise ValueError("Packaged sidecar does not match the exact source build inputs and binary digest")
    return binary, {"source_commit": source, "source_tree": tree, "sidecar_sha256": output,
                    "build_input_sha256": fingerprint.lower(), "build_manifest_sha256": sha256(manifest)}


def require_unchanged(binary, binding):
    _, current = artifact_binding(binding["source_commit"], binary)
    if current != binding:
        raise ValueError("Packaged qualification source or artifacts changed during execution")


def verify_report(record, source, tree, kind):
    fields = {"v", "passed", "source_commit", "source_tree", "evidence_level", "run_id",
              "sidecar_sha256", "build_input_sha256", "build_manifest_sha256", "checks",
              "counts", "duration_seconds", "scope"}
    if kind == "lifecycle":
        fields.add("timings_ms")
    if (not isinstance(record, dict) or set(record) != fields or type(record.get("v")) is not int
            or record["v"] != 1 or record.get("passed") is not True
            or record.get("source_commit") != source or record.get("source_tree") != tree
            or record.get("evidence_level") != LEVELS[kind] or record.get("scope") != SCOPE
            or record.get("checks") != list(CHECKS[kind])):
        raise ValueError("Native packaged evidence has the wrong source, scope or check inventory")
    counts = record["counts"]
    if (not isinstance(counts, dict) or set(counts) != set(COUNTS[kind])
            or any(type(counts[key]) is not int or counts[key] != value for key, value in COUNTS[kind].items())):
        raise ValueError("Native packaged execution inventory is incomplete")
    for field, length in (("run_id", 32), ("sidecar_sha256", 64), ("build_input_sha256", 64), ("build_manifest_sha256", 64)):
        if not isinstance(record[field], str) or re.fullmatch("[a-f0-9]{" + str(length) + "}", record[field]) is None:
            raise ValueError("Native packaged artifact or run identity is invalid")
    duration = record["duration_seconds"]
    if type(duration) not in {float, int} or not math.isfinite(duration) or duration < 0:
        raise ValueError("Native packaged execution duration is invalid")
    if kind == "lifecycle":
        timings = record["timings_ms"]
        if (not isinstance(timings, dict) or set(timings) != {"open_max", "control_max", "control_p95"}
                or any(type(value) not in {float, int} or not math.isfinite(value) or value < 0 for value in timings.values())
                or timings["open_max"] >= 20_000 or timings["control_max"] >= 30_000
                or timings["control_p95"] > timings["control_max"]):
            raise ValueError("Native lifecycle timings are invalid or exceed the execution budget")
    return record


def qualify(kind, expected_source, sidecar, exercise):
    result = {"v": 1, "passed": False, "evidence_level": LEVELS[kind], "scope": SCOPE}
    phase = "build_binding"
    try:
        binary, binding = artifact_binding(expected_source, sidecar)
        phase = "native_execution"
        started = monotonic()
        execution = exercise(binary)
        phase = "result_binding"
        require_unchanged(binary, binding)
        result = verify_report({"v": 1, "passed": True, **binding, "evidence_level": LEVELS[kind],
                                "run_id": uuid4().hex, "checks": list(CHECKS[kind]),
                                "duration_seconds": monotonic() - started, "scope": SCOPE, **execution},
                               binding["source_commit"], binding["source_tree"], kind)
    except Exception as error:
        # Preserve the failure class and phase, never raw service logs or payloads.
        result.update(failure_type=type(error).__name__, phase=phase)
    return result


def write_result(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record))
    return 0 if record["passed"] else 1
