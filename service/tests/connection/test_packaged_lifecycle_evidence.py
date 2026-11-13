from copy import deepcopy
from pathlib import Path
import runpy

import pytest


gate = runpy.run_path(str(Path(__file__).resolve().parents[3] / "scripts/test_packaged_lifecycle.py"))


def record():
    return {"v": 1, "passed": True, "source_commit": "a" * 40, "source_tree": "b" * 40,
            "evidence_level": gate["LEVEL"], "run_id": "c" * 32, "sidecar_sha256": "d" * 64,
            "build_input_sha256": "e" * 64, "checks": list(gate["CHECKS"]),
            "counts": dict(gate["COUNTS"]), "duration_seconds": 1.0}


def test_packaged_evidence_requires_complete_execution_from_the_selected_source():
    value = record()
    assert gate["verify_report"](value, "a" * 40, "b" * 40) == value


@pytest.mark.parametrize("fault", ["source", "tree", "version", "passed", "level", "missing", "duplicate",
                                  "count", "boolean_count", "digest", "build", "run", "duration", "extra"])
def test_partial_stale_or_unbound_packaged_evidence_fails(fault):
    value = deepcopy(record())
    if fault == "source": value["source_commit"] = "f" * 40
    elif fault == "tree": value["source_tree"] = "f" * 40
    elif fault == "version": value["v"] = True
    elif fault == "passed": value["passed"] = False
    elif fault == "level": value["evidence_level"] = "simulation"
    elif fault == "missing": value["checks"].pop()
    elif fault == "duplicate": value["checks"].append(value["checks"][0])
    elif fault == "count": value["counts"]["forced_exits"] = 0
    elif fault == "boolean_count": value["counts"]["forced_exits"] = True
    elif fault == "digest": value["sidecar_sha256"] = None
    elif fault == "build": value.pop("build_input_sha256")
    elif fault == "run": value["run_id"] = ""
    elif fault == "duration": value["duration_seconds"] = float("nan")
    else: value["test_skip"] = True
    with pytest.raises(ValueError): gate["verify_report"](value, "a" * 40, "b" * 40)
