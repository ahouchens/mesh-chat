from copy import deepcopy
from pathlib import Path
import runpy
import json
from types import SimpleNamespace

import pytest


gate = runpy.run_path(str(Path(__file__).resolve().parents[3] / "scripts/test_packaged_transport.py"))


def record():
    return {"v": 1, "passed": True, "source_commit": "a" * 40, "source_tree": "b" * 40,
            "evidence_level": gate["LEVEL"], "run_id": "c" * 32, "sidecar_sha256": "d" * 64,
            "native_binary_sha256": "e" * 64, "build_input_sha256": "f" * 64,
            "checks": list(gate["CHECKS"]), "counts": dict(gate["COUNTS"]), "duration_seconds": 1.0}


def test_complete_packaged_transport_evidence():
    value = record()
    assert gate["verify_report"](value, "a" * 40, "b" * 40) == value


def test_pairing_and_preapproved_recovery_are_distinct_qualification_levels():
    value = {**record(), "evidence_level": gate["PAIRING_LEVEL"], "checks": list(gate["PAIRING_CHECKS"]),
             "counts": dict(gate["PAIRING_COUNTS"])}
    assert gate["verify_pairing_report"](value, "a" * 40, "b" * 40) == value
    with pytest.raises(ValueError): gate["verify_report"](value, "a" * 40, "b" * 40)
    with pytest.raises(ValueError): gate["verify_pairing_report"](record(), "a" * 40, "b" * 40)


def test_pairing_requires_continuous_transfer_evidence():
    value = {**record(), "evidence_level": gate["PAIRING_LEVEL"],
             "checks": ["explicit_pairing_without_preapproved_contacts", "paired_bidirectional_authenticated_receipts"],
             "counts": dict(gate["PAIRING_COUNTS"])}
    with pytest.raises(ValueError):
        gate["verify_pairing_report"](value, "a" * 40, "b" * 40)


def test_pairing_requires_cancellation_and_unapproved_restart_evidence():
    required = {"cancelled_pairing_retires_native_sessions", "pending_invitation_survives_restart_without_approval"}
    assert required <= set(gate["PAIRING_CHECKS"])
    assert gate["PAIRING_COUNTS"] == {"processes_started": 3, "forced_exits": 1, "authenticated_receipts": 2}
    for missing in required:
        value = {**record(), "evidence_level": gate["PAIRING_LEVEL"],
                 "checks": [check for check in gate["PAIRING_CHECKS"] if check != missing],
                 "counts": dict(gate["PAIRING_COUNTS"])}
        with pytest.raises(ValueError): gate["verify_pairing_report"](value, "a" * 40, "b" * 40)


@pytest.mark.parametrize("fault", ["source", "tree", "version", "passed", "level", "missing", "duplicate",
                                  "count", "boolean_count", "digest", "build", "run", "duration", "extra"])
def test_incomplete_or_unbound_execution_is_not_qualification(fault):
    value = deepcopy(record())
    if fault == "source": value["source_commit"] = "f" * 40
    elif fault == "tree": value["source_tree"] = "f" * 40
    elif fault == "version": value["v"] = True
    elif fault == "passed": value["passed"] = False
    elif fault == "level": value["evidence_level"] = "simulation"
    elif fault == "missing": value["checks"].pop()
    elif fault == "duplicate": value["checks"].append(value["checks"][0])
    elif fault == "count": value["counts"]["authenticated_receipts"] = 0
    elif fault == "boolean_count": value["counts"]["forced_exits"] = True
    elif fault == "digest": value["native_binary_sha256"] = None
    elif fault == "build": value.pop("build_input_sha256")
    elif fault == "run": value["run_id"] = ""
    elif fault == "duration": value["duration_seconds"] = float("nan")
    else: value["test_skip"] = True
    with pytest.raises(ValueError): gate["verify_report"](value, "a" * 40, "b" * 40)


@pytest.mark.parametrize("fault", ["exit", "source", "false_success", "missing", "duplicate"])
def test_host_failure_or_stale_executable_cannot_produce_evidence(fault):
    value = {"v": 1, "source_commit": "a" * 40, "evidence_level": gate["LEVEL"],
             "result": {"ok": True, "checks": list(gate["CHECKS"]), "counts": dict(gate["COUNTS"])}}
    if fault == "source": value["source_commit"] = "b" * 40
    if fault == "false_success": value["result"]["ok"] = False
    lines = [] if fault == "missing" else [json.dumps(value)]
    if fault == "duplicate": lines *= 2
    process = SimpleNamespace(returncode=1 if fault == "exit" else 0, stdout="\n".join(lines))
    with pytest.raises(RuntimeError): gate["host_result"](process, "a" * 40)


def test_failure_report_keeps_bounded_process_classification_without_raw_content():
    error = gate["ScenarioFailure"]({"phase": "restart", "error_type": "service_stopped",
        "process_exits": [{"slot": 0, "reason": "terminated", "exit_code": 3,
            "stderr_bytes": 80, "unrecognized_stderr_lines": 1,
            "failures": [{"stage": "initialize", "category": "runtime_error",
                "frames": [{"module": "service", "line": 512, "locals": "secret"}],
                "message": "secret"}], "stderr": "secret"}]})
    assert error.diagnostics["process_exits"] == [{"slot": 0, "reason": "terminated", "exit_code": 3,
        "stderr_bytes": 80, "unrecognized_stderr_lines": 1, "transport_error": "unknown",
        "failures": [{"stage": "initialize", "category": "runtime_error",
                      "frames": [{"module": "service", "line": 512}]}]}]
    assert "secret" not in json.dumps(error.diagnostics)


def test_failure_report_rejects_unbounded_or_unrecognized_process_fields():
    error = gate["ScenarioFailure"]({"process_exits": [None, {"slot": True},
        {"slot": 0, "reason": "secret", "exit_code": True, "stderr_bytes": -1,
         "failures": [{"stage": "secret", "category": "secret",
             "frames": [{"module": "secret", "line": 1}]}]}] * 20})
    assert error.diagnostics["process_exits"] == []


def test_process_diagnostics_bound_records_frames_numbers_and_transport_codes():
    value = {"slot": 1, "reason": "transport_admission", "transport_error": "transport_replay",
             "exit_code": 2 ** 64, "stderr_bytes": True, "unrecognized_stderr_lines": -1,
             "failures": [{"stage": "secret", "category": "secret",
                 "frames": [{"module": "ipc", "line": 30}] * 20}] * 20}
    result = gate["process_exits"]([value] * 20)
    assert len(result) == 2
    assert result[0]["reason"] == "transport_admission"
    assert result[0]["transport_error"] == "transport_replay"
    assert all(result[0][key] is None for key in ("exit_code", "stderr_bytes", "unrecognized_stderr_lines"))
    assert len(result[0]["failures"]) == len(result[0]["failures"][0]["frames"]) == 8
    assert result[0]["failures"][0]["stage"] == result[0]["failures"][0]["category"] == "unknown"
    value["transport_error"] = "secret"
    assert gate["process_exits"]([value])[0]["transport_error"] == "unknown"
