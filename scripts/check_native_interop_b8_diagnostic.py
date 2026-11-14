"""Validate one same-run six-path/first-cold native diagnostic pair."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

import native_interop_evidence as evidence
from native_interop_artifacts import context_from_environment
from native_interop_workload import PATH_CASES
from test_packaged_lifecycle import source_identity


WORKLOAD = "b8_first_cold"
LEVEL = "packaged_windows_android_emulator_b8_first_cold_diagnostic_only"
SCOPE = evidence.required_workload(WORKLOAD)["scope"]
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_SUMMARY_BYTES = 16 * 1024
ROLE_NAMES = {role: f"native-interop-b8-first-cold-{role}.json"
              for role in ("windows", "android")}
SUMMARY_NAME = "native-interop-b8-first-cold-pair.json"


def _read_role(path, role):
    """Return a bounded parsed report and its byte identity, without raw data."""
    try:
        if path.name != ROLE_NAMES[role] or path.is_symlink() or not path.is_file():
            return None, None
        before = path.stat()
        if not 0 < before.st_size <= MAX_REPORT_BYTES:
            return None, None
        with path.open("rb") as stream:
            raw = stream.read(MAX_REPORT_BYTES + 1)
        after = path.stat()
        if (not 0 < len(raw) <= MAX_REPORT_BYTES or len(raw) != before.st_size
                or before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns):
            return None, None
        identity = {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
        try:
            report = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None, identity
        return report, identity
    except (OSError, ValueError):
        return None, None


def _write_summary(path, summary):
    encoded = (json.dumps(summary, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(encoded) > MAX_SUMMARY_BYTES:
        raise ValueError("Diagnostic summary exceeds its bound")
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--windows-report", type=Path, required=True)
    parser.add_argument("--android-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.name != SUMMARY_NAME or args.output.is_symlink():
        print("Native b8 diagnostic summary path is invalid")
        return 1

    roles = {"windows": args.windows_report, "android": args.android_report}
    parsed, identities = {}, {}
    for role, path in roles.items():
        parsed[role], identities[role] = _read_role(path, role)
    source = args.expected_source if re.fullmatch(r"[a-f0-9]{40}", args.expected_source) else None
    summary = {"v": 1, "passed": False, "evidence_level": LEVEL, "scope": SCOPE,
               "workload": WORKLOAD, "source_commit": source, "source_tree": None,
               "context": None, "reports": identities}
    failure_kind = "admission_invalid"
    try:
        if (source is None or os.environ.get("GITHUB_ACTIONS") != "true"
                or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
                or os.environ.get("GITHUB_JOB") != "b8_pair_check"
                or os.environ.get("GITHUB_SHA") != source):
            raise ValueError("Manual same-run diagnostic admission is unavailable")
        context = context_from_environment()
        if context["source_commit"] != source:
            raise ValueError("Diagnostic run source differs")
        summary["context"] = context
        failure_kind = "source_invalid"
        actual_source, tree = source_identity(source)
        if actual_source != source or re.fullmatch(r"[a-f0-9]{40}", tree) is None:
            raise ValueError("Diagnostic source tree differs")
        summary["source_tree"] = tree
        failure_kind = "report_invalid"
        if any(parsed[role] is None or identities[role] is None for role in roles):
            raise ValueError("Bounded role reports are incomplete")
        plan = evidence.required_workload(WORKLOAD)
        if (plan["name"] != WORKLOAD or plan["level"] != LEVEL or plan["scope"] != SCOPE
                or tuple(plan["paths"]) != PATH_CASES or plan["iterations"] != 1
                or plan["cold_start_every"] != 10):
            raise ValueError("Diagnostic workload differs from its fixed scope")
        failure_kind = "pair_invalid"
        evidence.verify_pair(parsed["windows"], parsed["android"], source, tree,
                             context=context, workload=WORKLOAD)
        summary.update(passed=True, path_cases=[list(case) for case in PATH_CASES],
                       receipt_iterations_per_role=1)
    except Exception:
        summary["failure_kind"] = failure_kind
    try:
        _write_summary(args.output, summary)
    except Exception:
        print("Native b8 diagnostic summary write failed")
        return 1
    print(json.dumps({"passed": summary["passed"], "evidence_level": LEVEL}))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
