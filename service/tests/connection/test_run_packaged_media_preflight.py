"""Admission and raw NSIS invocation checks; no installer runs here."""

from contextlib import redirect_stdout
import hashlib
from io import StringIO
import json
from pathlib import Path, PureWindowsPath
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import run_packaged_media_preflight as runner  # noqa: E402
sys.path.pop(0)


def row(role: str, path: str, content: bytes) -> dict:
    return {"role": role, "path": path, "sha256": hashlib.sha256(content).hexdigest().upper(),
            "size": len(content)}


class NsIsCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = "a" * 40
        self.tree = "b" * 40
        self.prefix = Path("dist/desktop/releases/0.9.66/x86_64-pc-windows-msvc")
        self.release = self.root / self.prefix
        self.release.mkdir(parents=True)
        self.files = {
            "application": ("mesh-chat.exe", b"application bytes"),
            "sidecar": ("mesh-chat-service.exe", b"sidecar bytes"),
            "nsis": ("bundle/nsis/mesh-chat_0.9.66_x64-setup.exe", b"installer bytes"),
        }
        for name, content in self.files.values():
            path = self.release / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.manifest = self.release / "manifest.json"
        artifacts = [row("installer" if key == "nsis" else key, name, content)
                     for key, (name, content) in self.files.items()]
        self.manifest.write_text(json.dumps({"schema_version": 1, "product": "Mesh Chat", "version": "0.9.66",
                                             "platform": "windows", "artifacts": artifacts}), encoding="utf-8")
        report_rows = [row("desktop-manifest", (self.prefix / "manifest.json").as_posix(),
                           self.manifest.read_bytes())]
        report_rows += [row("installer" if key == "nsis" else key, (self.prefix / name).as_posix(), content)
                        for key, (name, content) in self.files.items()]
        self.delivery = self.root / "dist/reports/packaged-media-build.json"
        self.delivery.parent.mkdir(parents=True)
        self.report = {"schema_version": 1, "product": "Mesh Chat", "version": "0.9.66",
                       "platforms": ["desktop"], "status": "passed",
                       "source": {"git_commit": self.source, "dirty": False},
                       "gates": {"automated": "passed"},
                       "steps": [{"name": "desktop-build", "status": "passed"}], "artifacts": report_rows}
        self.write_report()
        root = patch.object(runner, "ROOT", self.root)
        delivery = patch.object(runner, "DELIVERY", self.delivery)
        root.start()
        delivery.start()
        self.addCleanup(root.stop)
        self.addCleanup(delivery.stop)

    def write_report(self):
        self.delivery.write_text(json.dumps(self.report), encoding="utf-8")

    def test_accepts_exact_release_and_actual_staged_bytes(self):
        value = runner.source_bound_candidate(self.delivery, self.source, self.tree)
        self.assertEqual(value["installer_path"], self.release / self.files["nsis"][0])
        self.assertEqual(value["source_tree"], self.tree)
        self.assertEqual(value["application_size"], len(self.files["application"][1]))

    def test_wrong_source_or_installer_hash_or_path_fails_before_launch(self):
        with self.assertRaisesRegex(runner.PreparationFailure, "delivery_source_invalid"):
            runner.source_bound_candidate(self.delivery, "c" * 40, self.tree)
        installer = self.release / self.files["nsis"][0]
        installer.write_bytes(b"tampered installer")
        with self.assertRaisesRegex(runner.PreparationFailure, "candidate_file_mismatch"):
            runner.source_bound_candidate(self.delivery, self.source, self.tree)
        installer.write_bytes(self.files["nsis"][1])
        self.report["artifacts"][-1]["path"] = (self.prefix / "bundle/other/foreign.exe").as_posix()
        self.write_report()
        with self.assertRaisesRegex(runner.PreparationFailure, "delivery_artifacts_incomplete"):
            runner.source_bound_candidate(self.delivery, self.source, self.tree)

    def test_main_rejects_wrong_source_path_and_hash_without_process_launch(self):
        output = self.root / "dist/reports/packaged-media-install.json"
        args = ["run_packaged_media_preflight.py", "--expected-source", self.source,
                "--delivery-report", str(self.delivery), "--output", str(output)]
        env = {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}
        original = json.loads(json.dumps(self.report))
        for condition, expected in (("source", "delivery_source_invalid"),
                                    ("path", "delivery_artifacts_incomplete"),
                                    ("hash", "nsis_installer_unbound")):
            with self.subTest(condition=condition):
                self.report = json.loads(json.dumps(original))
                if condition == "source":
                    self.report["source"]["git_commit"] = "c" * 40
                elif condition == "path":
                    self.report["artifacts"][-1]["path"] = (self.prefix / "bundle/other/foreign.exe").as_posix()
                else:
                    self.report["artifacts"][-1]["sha256"] = "d" * 64
                self.write_report()
                with patch.object(runner.sys, "argv", args), patch.object(runner.sys, "platform", "win32"), \
                        patch.dict(runner.os.environ, env), \
                        patch.object(runner, "fresh_runner_temp", return_value=self.root), \
                        patch.object(runner.subprocess, "check_output", return_value=self.tree) as git_tree, \
                        patch.object(runner.preflight, "source_identity", return_value=(self.source, self.tree)), \
                        patch.object(runner.subprocess, "Popen") as launch:
                    with redirect_stdout(StringIO()):
                        self.assertEqual(runner.main(), 1)
                    launch.assert_not_called()
                    git_tree.assert_called_once_with(
                        ["git", "show", "-s", "--format=%T", self.source], cwd=self.root, text=True)
                self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["failure"], expected)

    def test_nsis_command_keeps_d_last_and_unquoted_with_spaces(self):
        installer = PureWindowsPath(r"C:\build output\mesh setup.exe")
        directory = PureWindowsPath(r"C:\Runner Temp\mesh media install")
        command = runner.installer_command(installer, directory)
        self.assertEqual(command, '"C:\\build output\\mesh setup.exe" /S /D=C:\\Runner Temp\\mesh media install')
        self.assertEqual(command.count("/D="), 1)
        self.assertNotIn('"', command.split("/D=", 1)[1])

    def test_install_uses_raw_commandline_and_bounded_exact_child_wait(self):
        installer = PureWindowsPath(r"C:\build output\mesh setup.exe")
        directory = PureWindowsPath(r"C:\Runner Temp\mesh media install")
        with patch.object(runner.subprocess, "Popen") as launch, \
                patch.object(runner.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True):
            launch.return_value.wait.return_value = 0
            self.assertEqual(runner.install(installer, directory), (0, True))
            self.assertEqual(launch.call_args.args[0], runner.installer_command(installer, directory))
            self.assertEqual(launch.call_args.kwargs["executable"], str(installer))
            self.assertFalse(launch.call_args.kwargs["shell"])
            launch.return_value.wait.assert_called_once_with(timeout=runner.INSTALL_TIMEOUT_SECONDS)

    def test_install_timeout_retires_only_the_exact_child_and_fails(self):
        installer = PureWindowsPath(r"C:\build output\mesh setup.exe")
        directory = PureWindowsPath(r"C:\Runner Temp\mesh media install")
        with patch.object(runner.subprocess, "Popen") as launch, \
                patch.object(runner.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True):
            launch.return_value.wait.side_effect = [subprocess.TimeoutExpired("nsis", 180), 0]
            with self.assertRaisesRegex(runner.PreparationFailure, "installer_timed_out"):
                runner.install(installer, directory)
            launch.return_value.kill.assert_called_once_with()
            self.assertEqual(launch.return_value.wait.call_count, 2)

    def test_installed_observation_identifies_each_mismatch_without_accepting_it(self):
        candidate = runner.source_bound_candidate(self.delivery, self.source, self.tree)
        installed = self.root / "installed"
        installed.mkdir()
        (installed / "mesh-chat.exe").write_bytes(self.files["application"][1])
        (installed / "mesh-chat-service.exe").write_bytes(self.files["sidecar"][1])
        self.assertTrue(runner.installed_artifacts_match(runner.installed_artifacts(installed, candidate)))
        changed = b"changed sidecar bytes"
        (installed / "mesh-chat-service.exe").write_bytes(changed)
        observed = runner.installed_artifacts(installed, candidate)
        self.assertTrue(observed["application"]["matches_expected"])
        self.assertEqual(observed["sidecar"], {
            "size_bytes": len(changed), "sha256": hashlib.sha256(changed).hexdigest(),
            "matches_expected": False,
        })
        self.assertFalse(runner.installed_artifacts_match(observed))
        (installed / "mesh-chat-service.exe").unlink()
        missing = runner.installed_artifacts(installed, candidate)
        self.assertEqual(missing["sidecar"], {"availability": "unavailable", "matches_expected": False})
        self.assertFalse(runner.installed_artifacts_match(missing))

    def test_install_mismatch_retains_both_observations_and_never_starts_capture(self):
        output = self.root / "dist/reports/packaged-media-install.json"
        candidate = runner.source_bound_candidate(self.delivery, self.source, self.tree)
        changed = b"changed application bytes"

        def installed_bytes(_installer, directory):
            (directory / "mesh-chat.exe").write_bytes(changed)
            (directory / "mesh-chat-service.exe").write_bytes(self.files["sidecar"][1])
            return 0, True

        args = ["run_packaged_media_preflight.py", "--expected-source", self.source,
                "--expected-tree", self.tree, "--delivery-report", str(self.delivery),
                "--run-id", "123", "--run-attempt", "1", "--output", str(output)]
        env = {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}
        with patch.object(runner.sys, "argv", args), patch.object(runner.sys, "platform", "win32"), \
                patch.dict(runner.os.environ, env), \
                patch.object(runner, "fresh_runner_temp", return_value=self.root), \
                patch.object(runner, "fresh_user_app_data"), \
                patch.object(runner.preflight, "source_identity", return_value=(self.source, self.tree)), \
                patch.object(runner, "install", side_effect=installed_bytes), \
                patch.object(runner, "run_preflight") as capture:
            with redirect_stdout(StringIO()):
                self.assertEqual(runner.main(), 1)
        capture.assert_not_called()
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual((report["phase"], report["failure"]), ("install", "installed_bytes_mismatch"))
        self.assertEqual(report["application_size"], candidate["application_size"])
        self.assertEqual(report["sidecar_size"], candidate["sidecar_size"])
        self.assertEqual(report["installed_artifacts"]["application"], {
            "size_bytes": len(changed), "sha256": hashlib.sha256(changed).hexdigest(),
            "matches_expected": False,
        })
        self.assertTrue(report["installed_artifacts"]["sidecar"]["matches_expected"])

    def test_preflight_timeout_records_wrapper_retirement_and_app_uncertainty(self):
        args = SimpleNamespace(run_id="123", run_attempt=1, node=Path("node"),
                               preflight_output=self.root / "dist/reports/packaged-media-preflight.json")
        candidate = {"manifest_path": self.manifest, "release_manifest_sha256": "c" * 64,
                     "delivery_report_sha256": "d" * 64, "source_commit": self.source,
                     "source_tree": self.tree}
        result = {}
        with patch.object(runner.subprocess, "Popen") as launch:
            launch.return_value.wait.side_effect = [subprocess.TimeoutExpired("preflight", 180), 0]
            with self.assertRaisesRegex(runner.PreparationFailure,
                                        "preflight_timed_out_app_retirement_unconfirmed"):
                runner.run_preflight(self.release / "mesh-chat.exe", candidate, args, result)
            launch.return_value.kill.assert_called_once_with()
            self.assertEqual(launch.return_value.wait.call_count, 2)
            self.assertEqual(launch.call_args.args[0][-4:-2], ["--node", "node"])
        self.assertEqual(result, {"app_retirement_unconfirmed": True, "preflight_child_retired": True})

    def test_preflight_timeout_does_not_claim_retirement_when_kill_fails(self):
        args = SimpleNamespace(run_id="123", run_attempt=1, node=Path("node"),
                               preflight_output=self.root / "dist/reports/packaged-media-preflight.json")
        candidate = {"manifest_path": self.manifest, "release_manifest_sha256": "c" * 64,
                     "delivery_report_sha256": "d" * 64, "source_commit": self.source,
                     "source_tree": self.tree}
        result = {}
        with patch.object(runner.subprocess, "Popen") as launch:
            launch.return_value.wait.side_effect = subprocess.TimeoutExpired("preflight", 180)
            launch.return_value.kill.side_effect = OSError("cannot retire child")
            launch.return_value.poll.return_value = None
            with self.assertRaisesRegex(runner.PreparationFailure, "preflight_child_retirement_uncertain"):
                runner.run_preflight(self.release / "mesh-chat.exe", candidate, args, result)
            launch.return_value.kill.assert_called_once_with()
        self.assertEqual(result, {"app_retirement_unconfirmed": True, "preflight_child_retired": False})


if __name__ == "__main__":
    unittest.main()
