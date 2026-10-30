import importlib.util
from pathlib import Path

import pytest


script = Path(__file__).resolve().parents[3] / "scripts" / "connection_evidence.py"
spec = importlib.util.spec_from_file_location("connection_evidence", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize("body", ["", '<testcase><skipped/></testcase>',
                                  '<testcase><failure/></testcase>', '<testcase><error/></testcase>'])
def test_required_skipped_failed_or_empty_suites_fail(tmp_path, body):
    report = tmp_path / "results.xml"
    report.write_text(f"<testsuite>{body}</testsuite>")
    with pytest.raises(ValueError):
        module.evidence(report, "commit", "commit")


def test_wrong_source_and_missing_evidence_fail(tmp_path):
    with pytest.raises(ValueError):
        module.evidence(tmp_path / "missing", "other", "required")
    with pytest.raises(FileNotFoundError):
        module.evidence(tmp_path / "missing", "required", "required")


def test_passing_evidence_records_actual_execution(tmp_path):
    report = tmp_path / "results.xml"
    report.write_text('<testsuites><testsuite><testcase name="ownership" time="0.5"/></testsuite></testsuites>')
    result = module.evidence(report, "commit", "commit")
    assert result["tests_executed"] == 1
    assert result["tests_skipped"] == 0
    assert result["duration_seconds"] == 0.5
