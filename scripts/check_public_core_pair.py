"""Strict same-run public Windows/Android fresh-pair diagnostic evidence.

This checker qualifies only the declared fresh-pair diagnostic. It cannot promote
native transport policy or establish restart, partition, media or physical parity.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

from check_independent_core_consumers import verify_report as verify_windows_bootstrap
from stage_independent_core_consumers import APPLICATION, FILES, digest
from test_packaged_lifecycle import source_identity
from verify_android_independent_consumer import verify_record as verify_android_distribution
from verify_android_independent_consumer import verify_source_inputs


LEVEL = "installed_public_windows_android_fresh_pair_diagnostic"
SCOPE = "Public SDK fresh pairing, explicit approval and one message with receipt each direction; no restart, partition, media, physical or full SC21 acceptance"
MAX_REPORT = 128 * 1024
MAX_SUMMARY = 16 * 1024
ROLES = ("windows", "android")
JOBS = {"verification", "android", "windows_public", "android_public"}
FLOW_FIELDS = {"v", "role", "pair_id", "self_destination_sha256", "peer_destination_sha256",
    "explicit_decision", "contact_count", "contact_trust", "messaging_ready", "pairing_transferred",
    "cancel_preserved_transferred", "outbound_text_sha256", "outbound_message_count",
    "outbound_delivered", "inbound_text_sha256", "inbound_message_count", "public_request_count"}
REPORT_FIELDS = {"v", "passed", "evidence_level", "scope", "role", "context", "source_tree",
                 "flow", "inputs", "session", "duration_seconds"}


def hex_value(value, size=64):
    return type(value) is str and re.fullmatch(r"[a-f0-9]{" + str(size) + "}", value) is not None


def pair_id_for(fields):
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(b"public-core-pair:v1:" + canonical.encode("ascii")).hexdigest()[:32]


def checked_context(value):
    fields = {"repository", "repository_id", "run_id", "run_attempt", "source_commit", "pair_id"}
    if (type(value) is not dict or set(value) != fields
            or type(value["repository"]) is not str
            or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value["repository"]) is None
            or any(part in {".", ".."} for part in value["repository"].split("/"))
            or any(type(value[key]) is not int or value[key] <= 0
                   for key in ("repository_id", "run_id", "run_attempt"))
            or not hex_value(value["source_commit"], 40) or not hex_value(value["pair_id"], 32)
            or value["pair_id"] != pair_id_for({key: item for key, item in value.items() if key != "pair_id"})):
        raise ValueError("public_pair_context")
    return dict(value)


def text_digest(pair_id, role):
    return hashlib.sha256(f"public-core-pair:v1:{pair_id}:{role}".encode("utf-8")).hexdigest()


def verify_flow(value, role, pair_id):
    if (type(value) is not dict or set(value) != FLOW_FIELDS
            or type(value["v"]) is not int or value["v"] != 1
            or value["role"] != role or value["pair_id"] != pair_id
            or value["explicit_decision"] != ("request_approved" if role == "windows" else "invitation_accepted")
            or value["contact_trust"] not in ("approved", "verified")
            or any(type(value[key]) is not int or value[key] != 1
                   for key in ("contact_count", "outbound_message_count", "inbound_message_count"))
            or any(value[key] is not True for key in ("messaging_ready", "pairing_transferred",
                                                      "cancel_preserved_transferred", "outbound_delivered"))
            or type(value["public_request_count"]) is not int or not 1 <= value["public_request_count"] <= 96
            or any(not hex_value(value[key]) for key in ("self_destination_sha256", "peer_destination_sha256"))
            or value["self_destination_sha256"] == value["peer_destination_sha256"]
            or value["outbound_text_sha256"] != text_digest(pair_id, role)
            or value["inbound_text_sha256"] != text_digest(pair_id, next(item for item in ROLES if item != role))):
        raise ValueError("public_pair_flow")


def verify_role(value, role, context, tree):
    if (type(value) is not dict or set(value) != REPORT_FIELDS
            or type(value["v"]) is not int or value["v"] != 1 or value["passed"] is not True
            or value["evidence_level"] != LEVEL or value["scope"] != SCOPE
            or value["role"] != role or value["context"] != context or value["source_tree"] != tree
            or type(value["session"]) is not dict or set(value["session"]) != {"finished", "cleanup"}
            or any(item is not True for item in value["session"].values())
            or type(value["duration_seconds"]) not in {int, float}
            or not math.isfinite(value["duration_seconds"]) or not 0 < value["duration_seconds"] <= 1200):
        raise ValueError("public_pair_role")
    checked_context(value["context"])
    verify_flow(value["flow"], role, context["pair_id"])


def verify_pair(windows, android, context, tree, expected_inputs, needs):
    checked_context(context)
    if not hex_value(tree, 40):
        raise ValueError("public_pair_tree")
    if (type(needs) is not dict or set(needs) != JOBS
            or any(type(job) is not dict or job.get("result") != "success" for job in needs.values())):
        raise ValueError("public_pair_prerequisites")
    if type(expected_inputs) is not dict or set(expected_inputs) != set(ROLES):
        raise ValueError("public_pair_inputs")
    for role, report in (("windows", windows), ("android", android)):
        verify_role(report, role, context, tree)
        if report["inputs"] != expected_inputs[role]:
            raise ValueError("public_pair_inputs")
    left, right = windows["flow"], android["flow"]
    for own, other in ((left, right), (right, left)):
        if (own["self_destination_sha256"] != other["peer_destination_sha256"]
                or own["outbound_text_sha256"] != other["inbound_text_sha256"]):
            raise ValueError("public_pair_cross_match")
    return True


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_report_field")
        result[key] = value
    return result


def reject_constant(_value):
    raise ValueError("non_finite_report_number")


def read_report(path):
    path = Path(path)
    for parent in (path, *path.parents):
        info = parent.lstat()
        if parent.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("report_link")
    before = path.stat()
    if not path.is_file() or not 0 < before.st_size <= MAX_REPORT:
        raise ValueError("report_size")
    with path.open("rb") as stream:
        data = stream.read(MAX_REPORT + 1)
    after = path.stat()
    if (len(data) != before.st_size or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns):
        raise ValueError("report_changed")
    value = json.loads(data.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=reject_constant)
    if type(value) is not dict:
        raise ValueError("report_object")
    return value, {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}


def windows_inputs(windows, context, tree, identity):
    verify_windows_bootstrap(windows, context["source_commit"], tree)
    current_files = {name: digest(APPLICATION / name) for name in FILES}
    if windows["application"]["application_files"] != current_files:
        raise ValueError("windows_application_inputs")
    return {**{key: windows[key] for key in
        ("sidecar_sha256", "build_input_sha256", "build_manifest_sha256", "sdk_sha256")},
        "bootstrap_report_sha256": identity["sha256"], "application_files": current_files}


def android_inputs(android, context, tree, identity):
    verify_android_distribution(android, {"source_commit": context["source_commit"], "source_tree": tree},
                                android.get("artifacts", {}))
    verify_source_inputs(android)
    return {"distribution_report_sha256": identity["sha256"],
            "artifacts": android["artifacts"], "application_files": android["application_files"]}


def prerequisite_inputs(windows, android, context, tree, identities):
    return {
        "windows": windows_inputs(windows, context, tree, identities["windows_bootstrap"]),
        "android": android_inputs(android, context, tree, identities["android_distribution"]),
    }


def write_summary(path, value):
    data = (json.dumps(value, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(data) > MAX_SUMMARY:
        raise ValueError("summary_size")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--pair-id")
    for name in ("windows-report", "android-report", "windows-bootstrap", "android-distribution", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    summary = {"v": 1, "passed": False, "evidence_level": LEVEL, "scope": SCOPE, "reports": {}}
    phase = "admission"
    try:
        environment = os.environ
        if (environment.get("GITHUB_ACTIONS") != "true" or environment.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
                or environment.get("GITHUB_JOB") != "public_pair_check" or environment.get("GITHUB_SHA") != args.expected_source):
            raise ValueError("manual_public_pair_admission")
        fields = {"repository": environment["GITHUB_REPOSITORY"],
            "repository_id": int(environment["GITHUB_REPOSITORY_ID"]), "run_id": int(environment["GITHUB_RUN_ID"]),
            "run_attempt": int(environment["GITHUB_RUN_ATTEMPT"]), "source_commit": args.expected_source}
        context = checked_context({**fields, "pair_id": args.pair_id or pair_id_for(fields)})
        _, tree = source_identity(args.expected_source)
        summary.update(context=context, source_tree=tree)
        phase = "reports"
        values = {}
        for name in ("windows_report", "android_report", "windows_bootstrap", "android_distribution"):
            values[name], summary["reports"][name] = read_report(getattr(args, name))
        phase = "producer_inputs"
        inputs = prerequisite_inputs(values["windows_bootstrap"], values["android_distribution"],
                                     context, tree, summary["reports"])
        phase = "pair"
        needs = json.loads(environment.get("PUBLIC_PAIR_NEEDS", "null"),
                           object_pairs_hook=unique_object, parse_constant=reject_constant)
        verify_pair(values["windows_report"], values["android_report"], context, tree, inputs, needs)
        summary["passed"] = True
    except Exception:
        summary["failure_phase"] = phase
    write_summary(args.output, summary)
    print(json.dumps({"passed": summary["passed"], "failure_phase": summary.get("failure_phase")}))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
