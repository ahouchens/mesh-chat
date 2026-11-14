"""The installed public session is a separate manual Android producer route."""

from itertools import product
from pathlib import Path
import re
import shutil
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/android-webrtc.yml"
WRAPPER = ROOT / "scripts/test_android_public_session_qualification.sh"
FLAGS = ("network_inventory", "gateway_probe", "restart_diagnostic", "public_core_session")


def workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def expression_value(expression, event, **flags):
    expression = expression.removeprefix("${{").removesuffix("}}").strip()
    expression = expression.replace("github.event_name", repr(event))
    expression = re.sub(r"\binputs\.([a-z0-9_]+)\b",
                        lambda match: repr(flags.get(match[1], False)), expression)
    expression = expression.replace("&&", " and ").replace("||", " or ")
    expression = re.sub(r"!(?!=)", " not ", expression)
    return eval(expression, {"__builtins__": {}}, {})


def test_manual_public_route_is_single_and_conflicts_before_producer_start():
    parsed = workflow()
    inputs = parsed.get("on", parsed.get(True))["workflow_dispatch"]["inputs"]
    assert inputs["public_core_session"]["type"] == "boolean"
    assert inputs["public_core_session"]["default"] is False
    jobs = parsed["jobs"]
    for values in product((False, True), repeat=len(FLAGS)):
        flags = dict(zip(FLAGS, values))
        selected = {name for name, job in jobs.items()
                    if expression_value(job["if"], "workflow_dispatch", **flags)}
        count = sum(values)
        if count > 1:
            assert selected == {"diagnostic_conflict"}
        elif flags["network_inventory"]:
            assert selected == {"network_inventory"}
        elif flags["gateway_probe"]:
            assert selected == {"gateway_probe"}
        elif flags["restart_diagnostic"]:
            assert selected == {"restart_diagnostic"}
        else:
            assert selected == {"android"}
    assert {name for name, job in jobs.items()
            if expression_value(job["if"], "workflow_call")} == {"android"}
    assert {name for name, job in jobs.items()
            if expression_value(job["if"], "workflow_call", b8_diagnostic_producer=True)} == {"android"}


def test_public_concurrency_is_distinct_and_preserves_default_and_b8_call():
    parsed = workflow()
    expressions = re.findall(r"\$\{\{([^{}]+)\}\}", parsed["concurrency"]["group"])
    assert len(expressions) == 3
    suffix, b8_suffix = expressions[1:]
    assert expression_value(suffix, "workflow_dispatch") == ""
    assert expression_value(suffix, "workflow_dispatch", public_core_session=True) == "-public-session"
    assert expression_value(suffix, "workflow_dispatch", restart_diagnostic=True) == "-restart"
    assert expression_value(suffix, "workflow_dispatch", gateway_probe=True) == "-gateway"
    assert expression_value(suffix, "workflow_dispatch", network_inventory=True) == "-inventory"
    for other in FLAGS[:-1]:
        assert expression_value(suffix, "workflow_dispatch", public_core_session=True,
                                **{other: True}) == "-conflict"
    assert expression_value(b8_suffix, "workflow_call") == ""
    assert expression_value(b8_suffix, "workflow_call", b8_diagnostic_producer=True) == "-b8-first-cold"
    cancel = parsed["concurrency"]["cancel-in-progress"]
    assert expression_value(cancel, "workflow_dispatch") is True
    assert expression_value(cancel, "workflow_dispatch", public_core_session=True) is False
    assert expression_value(cancel, "workflow_call") is True
    assert expression_value(cancel, "workflow_call", b8_diagnostic_producer=True) is False


def test_public_route_runs_required_suite_then_one_extra_session_in_same_emulator():
    steps = workflow()["jobs"]["android"]["steps"]
    by_name = {step["name"]: step for step in steps if "name" in step}
    ordinary = by_name["Test Chromium interop and Android signalling mailbox recovery"]
    public = by_name["Test required Android suites and installed public Core session"]
    assert ordinary["uses"] == public["uses"] == "reactivecircus/android-emulator-runner@v2"
    assert ordinary["with"]["script"] == "bash scripts/test_android_qualification.sh"
    assert public["with"]["script"] == "bash scripts/test_android_public_session_qualification.sh"
    assert {key: public["with"][key] for key in ordinary["with"] if key != "script"} == {
        key: value for key, value in ordinary["with"].items() if key != "script"}
    assert public["with"]["emulator-port"] == 5554
    for flags in ({}, {"public_core_session": True}):
        selected = [step for step in (ordinary, public)
                    if expression_value(step["if"], "workflow_dispatch", **flags)]
        assert len(selected) == 1
    assert expression_value(ordinary["if"], "workflow_call") is True
    assert expression_value(public["if"], "workflow_call") is False
    assert ordinary["timeout-minutes"] == 45
    assert public["timeout-minutes"] == 60
    script = WRAPPER.read_text(encoding="utf-8")
    assert script.index("bash scripts/test_android_qualification.sh") < script.index(
        "python -B scripts/check_android_independent_public_session.py")
    assert '--expected-source "${GITHUB_SHA:?}"' in script
    assert "--disposable-emulator-serial emulator-5554" in script
    assert "--output dist/reports/android-independent-public-session.json" in script
    bash = shutil.which("bash")
    if bash is not None and sys.platform != "win32":
        subprocess.run([bash, "-n", str(WRAPPER)], check=True, timeout=10)


def test_public_report_is_separate_run_bound_diagnostic_artifact():
    steps = workflow()["jobs"]["android"]["steps"]
    by_name = {step["name"]: step for step in steps if "name" in step}
    required = by_name["Retain required run-bound Android evidence"]
    public = by_name["Retain installed public Core session diagnostic"]
    assert required["with"]["path"] == "dist/reports/android-qualification.json"
    assert required["with"]["name"] == "android-qualification-${{ github.sha }}"
    assert public["uses"] == "actions/upload-artifact@v4"
    assert public["if"] == "${{ always() && github.event_name == 'workflow_dispatch' && inputs.public_core_session }}"
    assert public["with"] == {
        "name": "android-independent-public-session-${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}",
        "path": "dist/reports/android-independent-public-session.json",
        "if-no-files-found": "error", "retention-days": 14,
    }
