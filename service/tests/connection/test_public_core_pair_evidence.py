"""Reject mismatched public-pair reports independently of the flow runner."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import check_public_core_pair as checker
import check_independent_core_consumers as windows_bootstrap
import verify_android_independent_consumer as android_distribution


CONTEXT = {"repository": "owner/repository", "repository_id": 7, "run_id": 17,
           "run_attempt": 1, "source_commit": "a" * 40}
CONTEXT["pair_id"] = hashlib.sha256(b"public-core-pair:v1:" +
    json.dumps(CONTEXT, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()[:32]
TREE = "c" * 40


def prerequisites():
    application_files = {name: checker.digest(checker.APPLICATION / name) for name in checker.FILES}
    windows = {"v": 1, "passed": True, "source_commit": CONTEXT["source_commit"], "source_tree": TREE,
        "sdk_artifact": windows_bootstrap.SDK_ARTIFACT, "sidecar_sha256": "1" * 64,
        "build_input_sha256": "2" * 64, "build_manifest_sha256": "3" * 64, "sdk_sha256": "4" * 64,
        "application": {"application_files": application_files, "installed_outside_checkout": True,
                        "imports_public_package": True}, "runtime_installed_outside_checkout": True,
        "cleanup": "passed", "run_id": "5" * 32, "duration_seconds": 12,
        "evidence_level": windows_bootstrap.LEVEL, "scope": windows_bootstrap.SCOPE,
        "checks": dict(windows_bootstrap.CHECKS)}
    android = {"v": 1, "passed": True, "source_commit": CONTEXT["source_commit"], "source_tree": TREE,
        "scope": android_distribution.SCOPE, "checks": dict(android_distribution.CHECKS),
        "application_files": {name: checker.digest(android_distribution.ROOT / "examples/android-independent-consumer" / name)
                              for name in android_distribution.APPLICATION_FILES},
        "artifacts": {path.relative_to(android_distribution.ROOT).as_posix(): "6" * 64
                      for path in android_distribution.ARTIFACTS}}
    identities = {"windows_bootstrap": {"sha256": "7" * 64}, "android_distribution": {"sha256": "8" * 64}}
    return windows, android, identities


def valid_pair():
    windows, android, identities = prerequisites()
    inputs = checker.prerequisite_inputs(windows, android, CONTEXT, TREE, identities)
    reports = []
    for role, own, other in (("windows", "d", "e"), ("android", "e", "d")):
        peer = "android" if role == "windows" else "windows"
        flow = {"v": 1, "role": role, "pair_id": CONTEXT["pair_id"],
            "self_destination_sha256": own * 64, "peer_destination_sha256": other * 64,
            "explicit_decision": "request_approved" if role == "windows" else "invitation_accepted",
            "contact_count": 1, "contact_trust": "approved", "messaging_ready": True,
            "pairing_transferred": True, "cancel_preserved_transferred": True,
            "outbound_text_sha256": checker.text_digest(CONTEXT["pair_id"], role),
            "outbound_message_count": 1, "outbound_delivered": True,
            "inbound_text_sha256": checker.text_digest(CONTEXT["pair_id"], peer),
            "inbound_message_count": 1, "public_request_count": 40}
        reports.append({"v": 1, "passed": True, "evidence_level": checker.LEVEL, "scope": checker.SCOPE,
            "role": role, "context": dict(CONTEXT), "source_tree": TREE, "flow": flow,
            "inputs": deepcopy(inputs[role]), "session": {"finished": True, "cleanup": True},
            "duration_seconds": 130.5})
    needs = {job: {"result": "success", "outputs": {}} for job in checker.JOBS}
    return reports, inputs, needs


def test_exact_pair_with_independent_producer_inputs_passes():
    reports, inputs, needs = valid_pair()
    assert checker.verify_pair(*reports, CONTEXT, TREE, inputs, needs) is True
    assert reports[0]["flow"]["outbound_text_sha256"] != reports[0]["flow"]["inbound_text_sha256"]


def test_checker_and_setup_transport_bind_the_same_pair_identity():
    from public_core_pair_rendezvous import checked_context
    assert checked_context(CONTEXT) == checker.checked_context(CONTEXT)
    changed = {**CONTEXT, "pair_id": "0" * 32}
    for verify in (checked_context, checker.checked_context):
        with pytest.raises(ValueError):
            verify(changed)


@pytest.mark.parametrize("field,value", [
    ("v", True), ("pair_id", "0" * 32), ("role", "android"),
    ("explicit_decision", "invitation_accepted"), ("contact_count", True), ("contact_count", 2),
    ("contact_trust", "pending_request"), ("messaging_ready", 1), ("pairing_transferred", False),
    ("cancel_preserved_transferred", False), ("outbound_message_count", 2), ("outbound_delivered", False),
    ("inbound_message_count", 0), ("inbound_message_count", True),
    ("public_request_count", 97), ("public_request_count", True), ("public_request_count", 0),
    ("outbound_text_sha256", "1" * 64), ("inbound_text_sha256", "1" * 64),
    ("self_destination_sha256", "invalid"), ("extra", "secret"),
])
def test_incomplete_or_misbound_flow_cannot_pass(field, value):
    reports, inputs, needs = valid_pair()
    reports[0]["flow"][field] = value
    with pytest.raises(ValueError):
        checker.verify_pair(*reports, CONTEXT, TREE, inputs, needs)


@pytest.mark.parametrize("field,value", [
    ("passed", False), ("source_tree", "0" * 40), ("role", "android"), ("v", True),
    ("evidence_level", "native_gate_passed"), ("scope", "full SC21"),
    ("duration_seconds", 0), ("duration_seconds", 1201), ("duration_seconds", float("nan")),
    ("duration_seconds", float("inf")), ("duration_seconds", True),
    ("session", {"finished": True, "cleanup": False}), ("session", {"finished": 1, "cleanup": True}),
    ("extra", "secret"),
])
def test_failed_or_overclaimed_role_cannot_pass(field, value):
    reports, inputs, needs = valid_pair()
    reports[0][field] = value
    with pytest.raises(ValueError):
        checker.verify_pair(*reports, CONTEXT, TREE, inputs, needs)


@pytest.mark.parametrize("field,value", [("run_id", 18), ("run_attempt", 2), ("repository_id", 8),
    ("source_commit", "0" * 40), ("pair_id", "0" * 32), ("run_attempt", True)])
def test_cross_run_context_rejected(field, value):
    reports, inputs, needs = valid_pair()
    reports[1]["context"][field] = value
    with pytest.raises(ValueError):
        checker.verify_pair(*reports, CONTEXT, TREE, inputs, needs)


def test_valid_individual_identity_hashes_must_match_opposite_role():
    reports, inputs, needs = valid_pair()
    reports[1]["flow"]["peer_destination_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="cross_match"):
        checker.verify_pair(*reports, CONTEXT, TREE, inputs, needs)


@pytest.mark.parametrize("job", sorted(checker.JOBS))
@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", None])
def test_all_producers_and_peer_jobs_must_succeed(job, result):
    reports, inputs, needs = valid_pair()
    needs[job]["result"] = result
    with pytest.raises(ValueError, match="prerequisites"):
        checker.verify_pair(*reports, CONTEXT, TREE, inputs, needs)


def test_missing_job_or_artifact_identity_fails():
    reports, inputs, needs = valid_pair()
    del needs["verification"]
    with pytest.raises(ValueError, match="prerequisites"):
        checker.verify_pair(*reports, CONTEXT, TREE, inputs, needs)
    reports, inputs, needs = valid_pair()
    reports[0]["inputs"]["bootstrap_report_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="inputs"):
        checker.verify_pair(*reports, CONTEXT, TREE, inputs, needs)


@pytest.mark.parametrize("role", ["windows", "android"])
def test_prerequisite_report_binds_actual_application_sources(role):
    windows, android, identities = prerequisites()
    files = windows["application"]["application_files"] if role == "windows" else android["application_files"]
    files[next(iter(files))] = "0" * 64
    with pytest.raises(ValueError):
        checker.prerequisite_inputs(windows, android, CONTEXT, TREE, identities)


@pytest.mark.parametrize("data", [b'{"v":1,"v":1}', b'{"time":NaN}', b'[]', b'\xff',
                                  b'x' * (checker.MAX_REPORT + 1)],
                         ids=["duplicate", "nonfinite", "array", "encoding", "oversize"])
def test_bounded_report_reader_rejects_ambiguous_or_invalid_data(tmp_path, data):
    path = tmp_path / "report.json"
    path.write_bytes(data)
    with pytest.raises((ValueError, UnicodeError)):
        checker.read_report(path)


def test_report_digest_uses_the_exact_bytes_read(tmp_path):
    path = tmp_path / "report.json"
    path.write_text('{ "value": 1 }\n', encoding="utf-8")
    value, identity = checker.read_report(path)
    assert value == {"value": 1}
    assert identity == {"sha256": checker.digest(path), "size_bytes": path.stat().st_size}


def test_cli_missing_manual_admission_writes_only_bounded_failure(tmp_path, monkeypatch, capsys):
    output = tmp_path / "summary.json"
    monkeypatch.setattr(sys, "argv", ["checker", "--expected-source", CONTEXT["source_commit"],
        "--pair-id", CONTEXT["pair_id"], "--windows-report", "absent", "--android-report", "absent",
        "--windows-bootstrap", "absent", "--android-distribution", "absent", "--output", str(output)])
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert checker.main() == 1
    value = json.loads(output.read_text())
    assert value["passed"] is False and value["failure_phase"] == "admission"
    assert "absent" not in capsys.readouterr().out
    assert output.stat().st_size < checker.MAX_SUMMARY


@pytest.mark.parametrize("tamper", [False, True], ids=["matched", "changed-bootstrap-bytes"])
def test_cli_cross_checks_actual_report_bytes_and_job_results(tmp_path, monkeypatch, tamper):
    windows, android, _ = prerequisites()
    paths = {name: tmp_path / (name + ".json") for name in
             ("windows_bootstrap", "android_distribution", "windows_report", "android_report")}
    identities = {}
    for name, value in (("windows_bootstrap", windows), ("android_distribution", android)):
        paths[name].write_text(json.dumps(value), encoding="utf-8")
        _, identities[name] = checker.read_report(paths[name])
    inputs = checker.prerequisite_inputs(windows, android, CONTEXT, TREE, identities)
    reports, _, needs = valid_pair()
    for role, value in zip(checker.ROLES, reports):
        value["inputs"] = inputs[role]
        paths[role + "_report"].write_text(json.dumps(value), encoding="utf-8")
    if tamper:
        with paths["windows_bootstrap"].open("a", encoding="utf-8") as stream:
            stream.write("\n")
    environment = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_JOB": "public_pair_check", "GITHUB_SHA": CONTEXT["source_commit"],
        "GITHUB_REPOSITORY": CONTEXT["repository"], "GITHUB_REPOSITORY_ID": str(CONTEXT["repository_id"]),
        "GITHUB_RUN_ID": str(CONTEXT["run_id"]), "GITHUB_RUN_ATTEMPT": str(CONTEXT["run_attempt"]),
        "PUBLIC_PAIR_NEEDS": json.dumps(needs)}
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(checker, "source_identity", lambda expected: (CONTEXT["source_commit"], TREE))
    output = tmp_path / "summary.json"
    arguments = ["checker", "--expected-source", CONTEXT["source_commit"], "--pair-id", CONTEXT["pair_id"]]
    for name, path in paths.items():
        arguments.extend(("--" + name.replace("_", "-"), str(path)))
    monkeypatch.setattr(sys, "argv", arguments + ["--output", str(output)])
    assert checker.main() == int(tamper)
    result = json.loads(output.read_text())
    assert result["passed"] is (not tamper)
    assert len(result["reports"]) == 4
    if tamper:
        assert result["failure_phase"] == "pair"
