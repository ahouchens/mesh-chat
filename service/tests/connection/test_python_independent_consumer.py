"""Fail-closed provenance and host-status checks for the installed Python app."""

import copy
import importlib.util
import io
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import check_python_independent_consumer as check


def application_module():
    path = ROOT / "examples/python-independent-consumer/consumer.py"
    spec = importlib.util.spec_from_file_location("python_independent_application", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frame(value):
    body = json.dumps(value, separators=(",", ":")).encode()
    return len(body).to_bytes(4, "big") + body


def test_app_owned_status_requires_bounded_strict_frame():
    application = application_module()
    assert application.read_status(io.BytesIO(frame({"v": 1, "type": "runtime_started", "pipe": "pipe"}))) == {
        "v": 1, "type": "runtime_started", "pipe": "pipe"}
    for raw in (b"\0\0\0\1x", (4097).to_bytes(4, "big"), b"\0\0\0\4oops",
                frame({"v": True, "type": "runtime_started"}), b"\0\0\0\2\xff\xff"):
        with pytest.raises((ValueError, UnicodeError)):
            application.read_status(io.BytesIO(raw))


def report():
    return {"v": 1, "passed": True, "source_commit": "a" * 40, "source_tree": "b" * 40,
            "evidence_level": check.LEVEL, "scope": check.SCOPE,
            "sdk_artifact": check.SDK_ARTIFACT, "runtime_installed_outside_checkout": True,
            "cleanup": "passed", "checks": dict(check.CHECKS),
            "application_files": {name: "c" * 64 for name in check.FILES},
            "duration_seconds": 1.25, "run_id": "d" * 32,
            "sidecar_sha256": "e" * 64, "build_input_sha256": "f" * 64,
            "build_manifest_sha256": "1" * 64, "sdk_sha256": "2" * 64,
            "sdk_staging_report_sha256": "3" * 64}


@pytest.mark.parametrize("change", [
    lambda value: value["checks"].update(reopen_same_public_identity=False),
    lambda value: value.update(scope="SC21"),
    lambda value: value.update(sdk_sha256="0" * 63),
    lambda value: value.update(cleanup="pending"),
    lambda value: value.update(source_commit="c" * 40),
    lambda value: value.update(unexpected_private_data="secret"),
])
def test_report_rejects_scope_provenance_or_cleanup_substitution(change):
    valid = report()
    assert check.verify_report(valid, "a" * 40, "b" * 40) is valid
    invalid = copy.deepcopy(valid)
    change(invalid)
    with pytest.raises(ValueError):
        check.verify_report(invalid, "a" * 40, "b" * 40)


def test_staged_wheel_rejects_wrong_source_and_changed_bytes(tmp_path, monkeypatch):
    directory = tmp_path / "sdk"
    wheel = directory / "python" / check.WHEEL
    wheel.parent.mkdir(parents=True)
    wheel.write_bytes(b"installed-wheel")
    distribution = wheel.parent / "distribution-report.json"
    distribution.write_text("{}")
    item = {"artifact": "python/" + check.WHEEL, "sha256": check.digest(wheel),
            "size_bytes": wheel.stat().st_size, "report_sha256": check.digest(distribution)}
    staging = tmp_path / "staging.json"
    staging.write_text(json.dumps({"v": 1, "passed": True, "source_commit": "a" * 40,
                                   "source_tree": "b" * 40,
                                   "evidence_level": "public_sdk_archive_and_isolated_import_staging",
                                   "artifacts": {"python": item}}))
    import check_python_distribution
    monkeypatch.setattr(check_python_distribution, "verify", lambda path: {"artifact": path.name})
    assert check.staged_wheel(directory, staging, "a" * 40, "b" * 40) == wheel
    with pytest.raises(ValueError):
        check.staged_wheel(directory, staging, "c" * 40, "b" * 40)
    wheel.write_bytes(b"substituted-wheel")
    with pytest.raises(ValueError):
        check.staged_wheel(directory, staging, "a" * 40, "b" * 40)
