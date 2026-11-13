"""Private owner evidence crosses both independent consumer validation boundaries."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import check_independent_core_pairing as pairing
import stage_core_sdk as staging


def observation(as_of="failed_result"):
    gather = dict(as_of=as_of, worker="started", stage="native_offer", stage_state="entered",
                  last_completed="ice_config", queue_age="lt1s", stage_age="1to5s")
    if as_of == "failed_result":
        gather.update(exception_kind="native_unavailable", native_code="no_candidates")
    return dict(status="observed", total_intents=1, intents=[dict(role="offer", state="retired",
        retirement=dict(phase="gather_offer", event="failed" if as_of == "failed_result" else "tick",
                        reason="invalid_document" if as_of == "failed_result" else "phase_timeout"),
        gather_failure=gather)])


def project(value):
    node, _ = staging.tools()
    module = (ROOT / "examples/typescript-independent-consumer/owner-pairing-diagnostic.mjs").as_uri()
    script = f"import {{ownerPairingObservation}} from {json.dumps(module)};\n" + """
let input = ''; for await (const chunk of process.stdin) input += chunk;
try { console.log(JSON.stringify({value:ownerPairingObservation(JSON.parse(input))})); }
catch { console.log(JSON.stringify({rejected:true})); }
"""
    result = subprocess.run([node, "--input-type=module", "-e", script], input=json.dumps(value),
                            capture_output=True, text=True, timeout=15, env=os.environ)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def validate_report(value):
    intent = value["intents"][0]
    role = "offerer" if intent["role"] == "offer" else "answerer"
    pairing.owner_retirement_details(dict(scope="trusted_owner_before_cleanup", budget_ms=2000,
        peers={role: dict(outcome="received", observation=value)}))


@pytest.mark.parametrize("as_of", ["failed_result", "phase_deadline"])
@pytest.mark.parametrize("stage,last_completed", [
    ("not_started", "none"), ("ice_config", "none"), ("native_offer", "ice_config"),
    ("offer_sign", "native_offer"), ("complete", "offer_sign"), ("unknown", "unknown")])
def test_offer_gather_survives_both_consumer_boundaries(as_of, stage, last_completed):
    value = observation(as_of)
    value["intents"][0]["gather_failure"].update(stage=stage, last_completed=last_completed)
    projected = project(value)
    assert projected == {"value": value}
    validate_report(projected["value"])


@pytest.mark.parametrize("kind,code", [("native_unavailable", "unknown"),
    ("identity_mismatch", "not_applicable"), ("validation_error", "not_applicable"), ("unknown", "unknown")])
def test_offer_exception_labels_remain_bounded(kind, code):
    value = observation()
    value["intents"][0]["gather_failure"].update(exception_kind=kind, native_code=code)
    assert project(value) == {"value": value}
    validate_report(value)


@pytest.mark.parametrize("fault", ["answer_role", "answer_phase", "answer_stage", "answer_completed",
    "live", "missing_cause", "wrong_event", "wrong_reason", "wrong_as_of", "deadline_exception",
    "missing_exception", "native_not_applicable", "validation_native", "unknown_native",
    "raw", "boolean", "array", "missing_age", "unknown_stage", "unknown_age", "null"])
def test_offer_gather_rejects_wrong_attribution_or_unsafe_fields_at_both_boundaries(fault):
    value = observation()
    intent = value["intents"][0]
    gather = intent["gather_failure"]
    if fault == "answer_role": intent["role"] = "answer"
    elif fault == "answer_phase": intent["retirement"]["phase"] = "gather_answer"
    elif fault == "answer_stage": gather["stage"] = "native_accept"
    elif fault == "answer_completed": gather["last_completed"] = "answer_sign"
    elif fault == "live": intent["state"] = "offer_ready"
    elif fault == "missing_cause": intent["retirement"] = None
    elif fault == "wrong_event": intent["retirement"]["event"] = "tick"
    elif fault == "wrong_reason": intent["retirement"]["reason"] = "transient"
    elif fault == "wrong_as_of": gather["as_of"] = "phase_deadline"
    elif fault == "deadline_exception":
        intent["retirement"].update(event="tick", reason="phase_timeout")
        gather["as_of"] = "phase_deadline"
    elif fault == "missing_exception": del gather["exception_kind"]
    elif fault == "native_not_applicable": gather["native_code"] = "not_applicable"
    elif fault == "validation_native": gather["exception_kind"] = "validation_error"
    elif fault == "unknown_native": gather["exception_kind"] = "unknown"
    elif fault == "raw": gather["message"] = "private SDP address"
    elif fault == "boolean": gather["queue_age"] = True
    elif fault == "array": gather["stage"] = ["native_offer"]
    elif fault == "missing_age": del gather["stage_age"]
    elif fault == "unknown_stage": gather["stage"] = "private SDP address"
    elif fault == "unknown_age": gather["queue_age"] = 0.5
    elif fault == "null": intent["gather_failure"] = None
    assert project(value) == {"rejected": True}
    with pytest.raises(ValueError):
        validate_report(value)


@pytest.mark.parametrize("role", ["offer", "answer"])
def test_legacy_owner_rows_remain_valid_without_optional_gather(role):
    value = observation()
    intent = value["intents"][0]
    del intent["gather_failure"]
    intent["role"] = role
    intent["retirement"]["phase"] = "gather_offer" if role == "offer" else "gather_answer"
    assert project(copy.deepcopy(value)) == {"value": value}
    validate_report(value)
