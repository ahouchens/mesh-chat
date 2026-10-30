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
