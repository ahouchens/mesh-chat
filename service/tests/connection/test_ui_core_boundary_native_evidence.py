"""Native packaged reports must bind execution to actual source/artifact inputs."""

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_windows_evidence as native


@pytest.mark.parametrize("fault", ["none", "tracked_source", "unrelated_untracked", "adjacent_host_source", "wrong_revision"])
def test_downloaded_android_host_repository_preserves_exact_clean_source_binding(monkeypatch, fault):
    import test_packaged_lifecycle as packaged
    ignore = (Path(__file__).resolve().parents[3] / ".gitignore").read_bytes()
    # Exact25 members observed in Android artifact13724901774 / source733c38b;
    # bytes are tiny stand-ins, never claimed as build/artifact verification.
    base = "plugins/tauri-plugin-mesh-runtime/android/runtime-host/build/repository/com/meshchat/core-runtime-host"
    paths = [f"{base}/0.3.0-experimental/core-runtime-host-0.3.0-experimental{suffix}{checksum}"
             for suffix in ("-sources.jar", ".aar", ".module", ".pom")
             for checksum in ("", ".md5", ".sha1", ".sha256", ".sha512")]
    paths += [f"{base}/maven-metadata.xml{checksum}" for checksum in ("", ".md5", ".sha1", ".sha256", ".sha512")]
    # A short external temp path also keeps exact Maven filenames below Windows MAX_PATH.
    with tempfile.TemporaryDirectory(prefix="ms-") as directory:
        root = Path(directory)
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
        monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
        def git(*args):
            return subprocess.check_output(["git", *args], cwd=root, text=True).strip()
        git("init", "--quiet")
        (root / ".gitignore").write_bytes(ignore)
        source = root / "source.py"
        source.write_text("tracked source\n")
        git("add", ".gitignore", "source.py")
        git("-c", "user.name=Qualification Test", "-c", "user.email=qualification@example.invalid",
            "commit", "--quiet", "-m", "isolated source")
        expected = git("rev-parse", "HEAD")
        tree = git("rev-parse", "HEAD^{tree}")
        monkeypatch.setattr(packaged, "ROOT", root)
        assert packaged.source_identity(expected) == (expected, tree)
        for name in paths:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"synthetic downloaded output")
        assert len(paths) == 25
        # Exercise the actual guard, not a mocked status or relaxed path filter.
        assert packaged.source_identity(expected) == (expected, tree)
        if fault == "none": return
        if fault == "tracked_source": source.write_text("modified source\n")
        elif fault == "wrong_revision": expected = "0" * 40
        else:
            name = ("unrelated.txt" if fault == "unrelated_untracked"
                    else "plugins/tauri-plugin-mesh-runtime/android/runtime-host/src/main/unexpected.kt")
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("untracked source\n")
        with pytest.raises(RuntimeError, match="exact clean source revision"):
            packaged.source_identity(expected)


def report(kind):
    value = {"v": 1, "passed": True, "source_commit": "a" * 40, "source_tree": "b" * 40,
             "evidence_level": native.LEVELS[kind], "run_id": "c" * 32,
             "sidecar_sha256": "d" * 64, "build_input_sha256": "e" * 64,
             "build_manifest_sha256": "f" * 64, "checks": list(native.CHECKS[kind]),
             "counts": dict(native.COUNTS[kind]), "duration_seconds": 1.0, "scope": native.SCOPE}
    if kind == "lifecycle":
        value["timings_ms"] = {"open_max": 100, "control_max": 200, "control_p95": 150}
    return value


@pytest.mark.parametrize("kind", ["control", "lifecycle"])
@pytest.mark.parametrize("fault", ["source", "tree", "skip", "version", "binary", "build", "manifest",
                                    "run", "counts", "checks", "scope", "duration"])
def test_required_native_report_rejects_mismatched_or_incomplete_execution(kind, fault):
    record = report(kind)
    if fault in {"source", "tree"}:
        record["source_commit" if fault == "source" else "source_tree"] = "f" * 40
    elif fault == "skip":
        record.update(passed=True, skipped="requires Windows")
    elif fault == "version":
        record["v"] = True
    elif fault in {"binary", "build", "manifest"}:
        field = {"binary": "sidecar_sha256", "build": "build_input_sha256", "manifest": "build_manifest_sha256"}[fault]
        record[field] = "missing"
    elif fault == "run":
        record["run_id"] = None
    elif fault == "counts":
        record["counts"]["clean_exits"] -= 1
    elif fault == "checks":
        record["checks"].pop()
    elif fault == "scope":
        record["scope"] = "authenticated receipt delivery over Windows-Android"
    else:
        record["duration_seconds"] = float("nan")
    with pytest.raises(ValueError):
        native.verify_report(record, "a" * 40, "b" * 40, kind)


@pytest.mark.parametrize("fault", ["fewer_cycles", "no_cold_start", "boolean_count", "open_budget", "control_budget", "fake_p95"])
def test_100_control_cycles_cannot_be_replaced_by_partial_or_invalid_soak(fault):
    record = report("lifecycle")
    if fault == "fewer_cycles":
        record["counts"]["channel_pairs"] = 99
    elif fault == "no_cold_start":
        record["counts"]["cold_starts"] = 0
    elif fault == "boolean_count":
        record["counts"]["webview_processes"] = False
    elif fault == "open_budget":
        record["timings_ms"]["open_max"] = 20_000
    elif fault == "control_budget":
        record["timings_ms"]["control_max"] = 30_000
    else:
        record["timings_ms"]["control_p95"] = 201
    with pytest.raises(ValueError):
        native.verify_report(record, "a" * 40, "b" * 40, "lifecycle")


@pytest.fixture
def artifact(tmp_path, monkeypatch):
    binary = tmp_path / f"mesh-chat-service-{native.TARGET}.exe"
    binary.write_bytes(b"synthetic artifact for binding tests; never executed")
    manifest = tmp_path / f".mesh-chat-service-{native.TARGET}.build.json"
    value = {"schema_version": 1, "input_sha256": "C" * 64,
             "output_sha256": native.sha256(binary).upper(), "output": binary.name}
    manifest.write_text(json.dumps(value))
    monkeypatch.setattr(native, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(native, "BINARIES", tmp_path)
    monkeypatch.setattr(native, "source_identity", lambda expected: (expected, "b" * 40))
    monkeypatch.setattr(native, "_build_fingerprint", lambda target: "C" * 64)
    return binary, manifest, value


@pytest.mark.parametrize("fault", ["missing_binary", "wrong_name", "missing_manifest", "changed_binary",
                                    "changed_inputs", "output_name", "boolean_version", "oversized"])
def test_binding_rehashes_binary_and_requires_exact_build_manifest(artifact, fault):
    binary, manifest, value = artifact
    if fault == "missing_binary":
        binary.unlink()
    elif fault == "wrong_name":
        binary = binary.rename(binary.with_name("another.exe"))
    elif fault == "missing_manifest":
        manifest.unlink()
    elif fault == "changed_binary":
        binary.write_bytes(b"different binary")
    elif fault == "oversized":
        manifest.write_text(" " * (16 * 1024 + 1))
    else:
        if fault == "changed_inputs": value["input_sha256"] = "D" * 64
        elif fault == "output_name": value["output"] = "other.exe"
        else: value["schema_version"] = True
        manifest.write_text(json.dumps(value))
    with pytest.raises((ValueError, RuntimeError, FileNotFoundError)):
        native.artifact_binding("a" * 40, binary)


def test_changed_artifact_during_execution_cannot_qualify(artifact):
    binary, _, _ = artifact

    def execute(path):
        path.write_bytes(b"changed while running")
        return {"counts": dict(native.COUNTS["control"])}

    record = native.qualify("control", "a" * 40, binary, execute)
    assert record["passed"] is False and record["phase"] == "result_binding"


@pytest.mark.parametrize("module", ["check_native_windows_messaging", "check_native_windows_messaging_soak"])
def test_wrong_environment_fails_and_overwrites_stale_passing_report(tmp_path, monkeypatch, module):
    runner = importlib.import_module(module)
    output = tmp_path / "report.json"
    output.write_text(json.dumps({"passed": True, "source_commit": "a" * 40}))
    monkeypatch.setattr(native, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(sys, "argv", [module, "--expected-source", "a" * 40, "--output", str(output)])
    assert runner.main() == 1
    value = json.loads(output.read_text())
    assert value["passed"] is False and "skipped" not in value
    assert value["phase"] == "build_binding"


@pytest.mark.parametrize("iterations", [1, 99, 101, True])
def test_required_lifecycle_runner_refuses_non_100_iteration_claims(iterations):
    import check_native_windows_messaging_soak as runner
    with pytest.raises(ValueError, match="exactly 100"):
        runner.exercise(Path("unused.exe"), iterations)
