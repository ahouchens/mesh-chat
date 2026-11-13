"""The CI consumer must prove native scenarios ran, not merely exited zero."""
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import direct_qualification as direct


def run_fixture(tmp_path, body, *, options="", binary=True):
    tests = tmp_path / "service/tests"
    tests.mkdir(parents=True)
    (tmp_path / "service/pytest.ini").write_text("[pytest]\n")
    (tests / "test_direct_recovery_pipeline.py").write_text(body)
    native = tmp_path / "dispatcher.exe"
    native.write_bytes(b"isolated evidence fixture, never executed")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.name=Evidence test", "-c", "user.email=test@example.invalid",
                    "commit", "-qm", "fixture"], cwd=tmp_path, check=True)
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    env = {key: value for key, value in os.environ.items()
           if key not in {"PYTEST_ADDOPTS", "MESH_DIRECT_APP_HOST_BINARY", "GITHUB_SHA"}}
    env["PYTEST_ADDOPTS"] = options
    if binary:
        env["MESH_DIRECT_APP_HOST_BINARY"] = str(native)
    result = subprocess.run([sys.executable, str(SCRIPTS / "direct_qualification.py"),
                             "--suite", "recovery", "--expected-source", source],
                            cwd=tmp_path, env=env, text=True, capture_output=True, timeout=60)
    return result, source, tmp_path / "dist/reports/direct/recovery.json"


def test_runner_records_complete_execution_and_the_exact_native_binary(tmp_path):
    result, source, report = run_fixture(tmp_path, "def test_first(): pass\ndef test_second(): pass\n")
    assert result.returncode == 0, result.stdout + result.stderr
    record = direct.read_suite(report, source, direct.git(tmp_path, "HEAD^{tree}"), os.name)
    assert record["tests_collected"] == record["tests_executed"] == record["tests_passed"] == 2
    assert record["tests_skipped"] == 0
    assert record["artifacts"] == {"shipping_dispatcher": direct.digest(tmp_path / "dispatcher.exe")}


@pytest.mark.parametrize("fault", ["skip", "filter", "missing_binary", "failure"])
def test_runner_rejects_zero_exit_skips_filters_missing_native_and_failures(tmp_path, fault):
    body = "import pytest\ndef test_first(): pass\ndef test_second(): pass\n"
    if fault == "skip":
        body += "def test_native(): pytest.skip('native execution unavailable')\n"
    elif fault == "failure":
        body += "def test_native(): assert False\n"
    result, _, report = run_fixture(tmp_path, body, options="-k first" if fault == "filter" else "",
                                     binary=fault != "missing_binary")
    assert result.returncode != 0
    assert not report.exists()


@pytest.mark.parametrize("fault", ["source", "tree", "platform", "binary", "partial", "stale", "summary"])
def test_consumer_revalidates_execution_instead_of_trusting_summary(tmp_path, fault):
    result, source, path = run_fixture(tmp_path, "def test_first(): pass\ndef test_second(): pass\n")
    assert result.returncode == 0, result.stderr
    record = json.loads(path.read_text())
    tree = direct.git(tmp_path, "HEAD^{tree}")
    if fault in {"source", "tree", "platform"}:
        record[{"source": "source_commit", "tree": "source_tree", "platform": "platform"}[fault]] = "wrong"
    elif fault == "binary":
        record["artifacts"] = {}
    elif fault == "summary":
        record["tests_executed"] = 99
    else:
        xml = path.with_suffix(".xml")
        document = ET.parse(xml)
        suite = document.getroot().find("testsuite")
        if fault == "partial":
            suite.remove(suite.findall("testcase")[-1])
        else:
            suite.find("testcase/properties/property[@name='qualification_run']").set("value", "old")
        document.write(xml)
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        direct.read_suite(path, source, tree, os.name)
