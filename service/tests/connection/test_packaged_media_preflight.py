"""Fail-closed input checks for the packaged WebView2 capture preflight."""

from contextlib import redirect_stdout
from io import StringIO
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/packaged_media_preflight.py"
SPEC = spec_from_file_location("packaged_media_preflight", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
preflight = module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


class PublishedCandidateTests(unittest.TestCase):
    def test_probe_emits_only_fixed_argument_failure(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is unavailable")
        probe = subprocess.run([node, str(SCRIPT.with_suffix(".mjs")), "invalid", "1000", "a" * 40],
                               text=True, capture_output=True, timeout=5)
        self.assertNotEqual(probe.returncode, 0)
        self.assertEqual(probe.stdout, "")
        self.assertEqual(preflight.bounded_probe_failure(probe.stderr),
                         {"stage": "arguments", "code": "invalid_probe_arguments"})

    def test_probe_failure_diagnostic_is_bounded_and_allowlisted(self):
        marker = preflight.PROBE_FAILURE_PREFIX + json.dumps(
            {"stage": "target_discovery", "code": "app_webview_unavailable"})
        self.assertEqual(preflight.bounded_probe_failure(marker),
                         {"stage": "target_discovery", "code": "app_webview_unavailable"})
        for stderr in (marker + "\n" + marker,
                       preflight.PROBE_FAILURE_PREFIX + json.dumps({"stage": "target_discovery", "code": "secret"}),
                       preflight.PROBE_FAILURE_PREFIX + json.dumps({"stage": [], "code": "unexpected"}),
                       preflight.PROBE_FAILURE_PREFIX + json.dumps({"stage": "target_discovery", "code": "unexpected", "url": "private"}),
                       "private" * 2000 + marker):
            with self.subTest(stderr=stderr[:70]):
                self.assertIsNone(preflight.bounded_probe_failure(stderr))

    def test_probe_failure_stage_reaches_report_without_raw_stderr(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "preflight.json"
            source, tree = "a" * 40, "b" * 40
            marker = preflight.PROBE_FAILURE_PREFIX + json.dumps(
                {"stage": "target_discovery", "code": "app_webview_unavailable"})
            arguments = ["packaged_media_preflight.py", "--app", str(root / "mesh-chat.exe"),
                         "--release-manifest", str(root / "manifest.json"),
                         "--expected-manifest-sha256", "c" * 64,
                         "--delivery-report", str(root / "build.json"),
                         "--expected-delivery-report-sha256", "d" * 64,
                         "--expected-source", source, "--expected-tree", tree,
                         "--run-id", "12345", "--run-attempt", "1", "--output", str(output)]
            node_version = subprocess.CompletedProcess([], 0, stdout="v24.0.0\n", stderr="")
            node_probe = subprocess.CompletedProcess([], 1, stdout="", stderr=marker + "\nprivate detail")
            with patch.object(preflight.sys, "argv", arguments), patch.object(preflight.sys, "platform", "win32"), \
                    patch.dict(preflight.os.environ, {"GITHUB_RUN_ID": "12345", "GITHUB_RUN_ATTEMPT": "1",
                                                    "APPDATA": str(root), "LOCALAPPDATA": str(root)}, clear=True), \
                    patch.object(preflight, "source_identity", return_value=(source, tree)), \
                    patch.object(preflight, "published_bytes", return_value={"application_sha256": "e" * 64,
                                                                            "application_size": 1,
                                                                            "sidecar_sha256": "f" * 64,
                                                                            "sidecar_size": 1}), \
                    patch.object(preflight, "delivery_provenance", return_value="d" * 64), \
                    patch.object(preflight, "digest", return_value="0" * 64), \
                    patch.object(preflight, "known_folder", return_value=root), \
                    patch.object(preflight, "require_fresh_app_data"), \
                    patch.object(preflight, "reserve_port", return_value=12345), \
                    patch.object(preflight, "retire", return_value=True), \
                    patch.object(preflight.subprocess, "Popen") as launch, \
                    patch.object(preflight.subprocess, "run", side_effect=[node_version, node_probe]):
                with redirect_stdout(StringIO()):
                    self.assertEqual(preflight.main(), 1)
                launch.assert_called_once()
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["failure"], "probe_output_invalid")
            self.assertEqual(result["phase"], "webview2_capture")
            self.assertEqual(result["probe_failure"],
                             {"stage": "target_discovery", "code": "app_webview_unavailable"})
            self.assertNotIn("private detail", output.read_text(encoding="utf-8"))

    def test_cli_refuses_mismatched_run_before_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            arguments = ["packaged_media_preflight.py", "--app", "missing.exe", "--release-manifest", "missing.json",
                         "--expected-manifest-sha256", "a" * 64, "--delivery-report", "missing-report.json",
                         "--expected-delivery-report-sha256", "b" * 64, "--expected-source", "c" * 40,
                         "--expected-tree", "d" * 40, "--run-id", "12345", "--run-attempt", "1",
                         "--output", str(output)]
            with patch.object(preflight.sys, "argv", arguments), patch.object(preflight.sys, "platform", "win32"), \
                    patch.dict(preflight.os.environ, {"GITHUB_RUN_ID": "67890", "GITHUB_RUN_ATTEMPT": "1"}), \
                    patch.object(preflight.subprocess, "Popen") as launch:
                with redirect_stdout(StringIO()):
                    self.assertEqual(preflight.main(), 1)
                launch.assert_not_called()
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["failure"], "run_context_mismatch")

    def test_real_git_clean_exact_source_then_wrong_and_dirty(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
            (repo / "source.txt").write_text("source", encoding="utf-8")
            subprocess.run(["git", "add", "source.txt"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "-c", "user.email=test@example.invalid", "-c", "user.name=Test",
                            "commit", "-qm", "seed"], cwd=repo, check=True, capture_output=True)
            source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            tree = subprocess.check_output(["git", "show", "-s", "--format=%T", "HEAD"], cwd=repo, text=True).strip()
            self.assertEqual((len(source), len(tree)), (40, 40))
            with patch.object(preflight, "ROOT", repo):
                self.assertEqual(preflight.source_identity(source, tree), (source, tree))
                with self.assertRaisesRegex(preflight.PreflightFailure, "source_mismatch"):
                    preflight.source_identity("a" * 40, tree)
                with self.assertRaisesRegex(preflight.PreflightFailure, "source_mismatch"):
                    preflight.source_identity(source, "b" * 40)
                (repo / "dirty.txt").write_text("untracked", encoding="utf-8")
                with self.assertRaisesRegex(preflight.PreflightFailure, "source_dirty"):
                    preflight.source_identity(source, tree)
                with self.assertRaisesRegex(preflight.PreflightFailure, "expected_source_invalid"):
                    preflight.source_identity("a" * 64, tree)

    def test_installed_bytes_must_match_the_bound_release_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / "mesh-chat.exe"
            sidecar = root / "mesh-chat-service.exe"
            app.write_bytes(b"application candidate")
            sidecar.write_bytes(b"sidecar candidate")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "schema_version": 1, "product": "Mesh Chat", "version": "0.9.66", "platform": "windows",
                "artifacts": [
                    {"role": "application", "path": app.name, "sha256": preflight.digest(app).upper(), "size": app.stat().st_size},
                    {"role": "sidecar", "path": sidecar.name, "sha256": preflight.digest(sidecar).upper(), "size": sidecar.stat().st_size},
                ],
            }), encoding="utf-8")
            expected = preflight.digest(manifest)
            bound = preflight.published_bytes(manifest, expected, app)
            self.assertEqual(bound["application_sha256"], preflight.digest(app))
            sidecar.write_bytes(b"changed sidecar candidate")
            with self.assertRaisesRegex(preflight.PreflightFailure, "installed_bytes_mismatch"):
                preflight.published_bytes(manifest, expected, app)
            with self.assertRaisesRegex(preflight.PreflightFailure, "manifest_mismatch"):
                preflight.published_bytes(manifest, "0" * 64, app)
            for version in ("9" * 20_000, "1.2.3-rc", "2101.0.0"):
                value = json.loads(manifest.read_text(encoding="utf-8"))
                value["version"] = version
                manifest.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaisesRegex(preflight.PreflightFailure, "manifest_version_invalid"):
                    preflight.published_bytes(manifest, preflight.digest(manifest), app)

    def test_report_has_serialized_16k_bound_before_temporary_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "report.json"
            with self.assertRaisesRegex(preflight.PreflightFailure, "report_too_large"):
                preflight.write_report(target, {"release_version": "9" * 20_000})
            self.assertFalse(target.exists())
            self.assertFalse(list(root.glob("*.tmp")))
            preflight.write_report(target, {"v": 1, "passed": False})
            self.assertLessEqual(target.stat().st_size, preflight.MAX_REPORT_BYTES)

    def test_real_delivery_schema_binds_source_manifest_and_installed_files(self):
        source = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / "mesh-chat.exe"
            sidecar = root / "mesh-chat-service.exe"
            app.write_bytes(b"app")
            sidecar.write_bytes(b"sidecar")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "schema_version": 1, "product": "Mesh Chat", "version": "0.9.66", "platform": "windows",
                "artifacts": [
                    {"role": "application", "path": app.name, "sha256": preflight.digest(app).upper(), "size": app.stat().st_size},
                    {"role": "sidecar", "path": sidecar.name, "sha256": preflight.digest(sidecar).upper(), "size": sidecar.stat().st_size},
                ],
            }), encoding="utf-8")
            manifest_sha = preflight.digest(manifest)
            bound = preflight.published_bytes(manifest, manifest_sha, app)
            prefix = "dist/desktop/releases/0.9.66/x86_64-pc-windows-msvc"
            value = {
                "schema_version": 1, "product": "Mesh Chat", "version": "0.9.66",
                "status": "passed", "platforms": ["desktop"],
                "source": {"git_commit": source, "dirty": False},
                "gates": {"automated": "passed"},
                "steps": [{"name": "desktop-build", "status": "passed"}],
                "artifacts": [
                    {"role": "desktop-manifest", "path": f"{prefix}/manifest.json",
                     "sha256": manifest_sha.upper(), "size": manifest.stat().st_size},
                    {"role": "application", "path": f"{prefix}/{app.name}",
                     "sha256": preflight.digest(app).upper(), "size": app.stat().st_size},
                    {"role": "sidecar", "path": f"{prefix}/{sidecar.name}",
                     "sha256": preflight.digest(sidecar).upper(), "size": sidecar.stat().st_size},
                ],
            }
            report = root / "report.json"
            report.write_text(json.dumps(value), encoding="utf-8")
            report_sha = preflight.digest(report)
            self.assertEqual(preflight.delivery_provenance(report, report_sha, source, manifest,
                                                           manifest_sha, bound), report_sha)
            value["source"]["git_commit"] = "b" * 40
            report.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(preflight.PreflightFailure, "delivery_source_invalid"):
                preflight.delivery_provenance(report, preflight.digest(report), source, manifest, manifest_sha, bound)
            output = root / "preflight-result.json"
            arguments = ["packaged_media_preflight.py", "--app", str(app), "--release-manifest", str(manifest),
                         "--expected-manifest-sha256", manifest_sha, "--delivery-report", str(report),
                         "--expected-delivery-report-sha256", preflight.digest(report), "--expected-source", source,
                         "--expected-tree", "c" * 40, "--run-id", "12345", "--run-attempt", "1",
                         "--output", str(output)]
            with patch.object(preflight.sys, "argv", arguments), patch.object(preflight.sys, "platform", "win32"), \
                    patch.dict(preflight.os.environ, {"GITHUB_RUN_ID": "12345", "GITHUB_RUN_ATTEMPT": "1"}), \
                    patch.object(preflight, "source_identity", return_value=(source, "c" * 40)), \
                    patch.object(preflight.subprocess, "Popen") as launch:
                with redirect_stdout(StringIO()):
                    self.assertEqual(preflight.main(), 1)
                launch.assert_not_called()
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["failure"], "delivery_source_invalid")
            value["source"]["git_commit"] = source
            value["artifacts"][1]["sha256"] = "0" * 64
            report.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(preflight.PreflightFailure, "delivery_artifacts_unbound"):
                preflight.delivery_provenance(report, preflight.digest(report), source, manifest, manifest_sha, bound)

    def test_final_recheck_detects_driver_and_app_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / "mesh-chat.exe"
            app.write_bytes(b"app")
            sidecar = root / "mesh-chat-service.exe"
            sidecar.write_bytes(b"sidecar")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"schema_version": 1, "product": "Mesh Chat", "version": "0.9.66",
                "platform": "windows", "artifacts": [
                    {"role": "application", "path": app.name, "sha256": preflight.digest(app), "size": app.stat().st_size},
                    {"role": "sidecar", "path": sidecar.name, "sha256": preflight.digest(sidecar), "size": sidecar.stat().st_size},
                ]}), encoding="utf-8")
            bound = preflight.published_bytes(manifest, preflight.digest(manifest), app)
            driver = root / "driver.mjs"
            driver.write_text("probe", encoding="utf-8")
            with patch.object(preflight, "DRIVER", driver), patch.object(preflight, "source_identity", return_value=("a" * 40, "b" * 40)), \
                    patch.object(preflight, "delivery_provenance", return_value="c" * 64):
                with self.assertRaisesRegex(preflight.PreflightFailure, "inputs_changed_during_probe"):
                    preflight.require_unchanged("a" * 40, "b" * 40, manifest, preflight.digest(manifest),
                                                root / "report.json", "c" * 64, app, bound, "0" * 64)
                sidecar.write_bytes(b"altered")
                with self.assertRaises(preflight.PreflightFailure):
                    preflight.require_unchanged("a" * 40, "b" * 40, manifest, preflight.digest(manifest),
                                                root / "report.json", "c" * 64, app, bound, preflight.digest(driver))

    def test_reparse_attribute_and_oversize_input_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "manifest.json"
            original.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(preflight.PreflightFailure, "input_size_or_type_invalid"):
                preflight.checked_bytes(original, 1)
            original_lstat = Path.lstat

            def reparse_attribute(path, *args, **kwargs):
                info = original_lstat(path, *args, **kwargs)
                if path == original.absolute():
                    return SimpleNamespace(st_mode=info.st_mode, st_size=info.st_size,
                                           st_file_attributes=0x400)
                return info

            with patch.object(Path, "lstat", reparse_attribute):
                with self.assertRaisesRegex(preflight.PreflightFailure, "reparse_input"):
                    preflight.checked_bytes(original)

    def test_live_symlink_input_is_rejected_when_windows_allows_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "manifest.json"
            original.write_text("{}", encoding="utf-8")
            link = root / "linked.json"
            try:
                link.symlink_to(original)
            except OSError:
                self.skipTest("File symlinks are unavailable")
            with self.assertRaisesRegex(preflight.PreflightFailure, "reparse_input"):
                preflight.checked_bytes(link)

    def test_existing_app_data_refuses_launch_without_deleting_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            roaming = root / "roaming"
            local = root / "local"
            roaming.mkdir()
            local.mkdir()
            preflight.require_fresh_app_data("com.meshchat.desktop", roaming, local)
            marker = roaming / "com.meshchat.desktop"
            marker.mkdir()
            with self.assertRaisesRegex(preflight.PreflightFailure, "app_data_not_fresh"):
                preflight.require_fresh_app_data("com.meshchat.desktop", roaming, local)
            self.assertTrue(marker.is_dir())


if __name__ == "__main__":
    unittest.main()
