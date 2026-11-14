"""The installed media diagnostic cannot borrow or cancel ordinary CI acceptance."""

from pathlib import Path
import re

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]


def evaluate(expression, event, **inputs):
    expression = expression.removeprefix("${{").removesuffix("}}").strip()
    expression = expression.replace("github.event_name", repr(event))
    expression = expression.replace("needs.verify.result", repr(inputs.pop("verify", "success")))
    expression = re.sub(r"\binputs\.([a-z0-9_]+)\b", lambda match: repr(inputs.get(match[1], False)), expression)
    expression = expression.replace("&&", " and ").replace("||", " or ")
    expression = re.sub(r"\btrue\b", "True", expression)
    expression = re.sub(r"!(?!=)", " not ", expression)
    return eval(expression, {"__builtins__": {}}, {})


@pytest.mark.parametrize("event,enabled,verification,selected", [
    ("workflow_dispatch", True, "success", True),
    ("workflow_dispatch", False, "success", False),
    ("workflow_dispatch", True, "failure", False),
    ("workflow_dispatch", True, "cancelled", False),
    ("push", True, "success", False),
    ("pull_request", True, "success", False),
])
def test_capture_route_requires_manual_opt_in_and_same_source_verification(event, enabled, verification, selected):
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = workflow["jobs"]["media_preflight"]
    assert job["needs"] == "verify"
    assert evaluate(job["if"], event, packaged_media_preflight=enabled, verify=verification) is selected
    assert job["uses"] == "./.github/workflows/packaged-media-preflight.yml"
    assert workflow.get("on", workflow.get(True))["workflow_dispatch"]["inputs"]["packaged_media_preflight"]["default"] is False


@pytest.mark.parametrize("event,inputs,suffix,cancel", [
    ("workflow_dispatch", {}, "", True),
    ("push", {}, "", True),
    ("workflow_dispatch", {"windows_candidate_pair": True}, "", True),
    ("workflow_dispatch", {"packaged_media_preflight": True}, "-media-preflight", False),
    ("push", {"packaged_media_preflight": True}, "", True),
    ("workflow_dispatch", {"b8_diagnostic_producer": True}, "-b8-first-cold", False),
])
def test_capture_concurrency_preserves_ordinary_and_paired_groups(event, inputs, suffix, cancel):
    concurrency = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["concurrency"]
    expression = re.findall(r"\$\{\{([^{}]+)\}\}", concurrency["group"])[-1]
    assert evaluate(expression, event, **inputs) == suffix
    assert evaluate(concurrency["cancel-in-progress"], event, **inputs) is cancel


def test_capture_build_has_bounded_separate_outputs_without_publication():
    workflow = yaml.safe_load((ROOT / ".github/workflows/packaged-media-preflight.yml").read_text())
    assert set(workflow.get("on", workflow.get(True))) == {"workflow_call"}
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] is False
    job = workflow["jobs"]["media_capture"]
    assert job["if"] == "${{ github.event_name == 'workflow_dispatch' }}"
    assert job["runs-on"] == "windows-latest" and job["timeout-minutes"] == 90
    steps = job["steps"]
    build = next(i for i, step in enumerate(steps) if "scripts/release.py build" in step.get("run", ""))
    probe = next(i for i, step in enumerate(steps) if "scripts/run_packaged_media_preflight.py" in step.get("run", ""))
    assert build < probe
    assert "--skip-tests" in steps[build]["run"]
    assert '--expected-source "${{ github.sha }}"' in steps[probe]["run"]
    assert "--delivery-report dist/reports/packaged-media-build.json" in steps[probe]["run"]
    upload = next(step for step in steps if step.get("uses") == "actions/upload-artifact@v4")
    assert upload["if"] == "always()"
    assert upload["with"]["name"] == "packaged-media-preflight-${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}"
    assert "dist/reports/packaged-media-*.json" in upload["with"]["path"]
    assert all("release_qualification.py" not in step.get("run", "") for step in steps)
