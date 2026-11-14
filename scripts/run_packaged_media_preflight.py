"""Install one exact-source NSIS candidate on a disposable Windows CI runner.

This prepares and executes only the WebView2 audio capture preflight. It never
qualifies CallDialog, public pairing, messaging receipts, or SC17.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile

import packaged_media_preflight as preflight


ROOT = Path(__file__).resolve().parents[1]
DELIVERY = ROOT / "dist/reports/packaged-media-build.json"
PREFLIGHT = ROOT / "scripts/packaged_media_preflight.py"
INSTALL_TIMEOUT_SECONDS = 180
PREFLIGHT_TIMEOUT_SECONDS = 180
LEVEL = "windows_nsis_install_webview2_media_preflight_only"


class PreparationFailure(RuntimeError):
    pass


def _hex64(value: object) -> bool:
    return isinstance(value, str) and bool(preflight.HEX64.fullmatch(value))


def _artifact_rows(rows: object) -> dict[str, dict]:
    if not isinstance(rows, list):
        raise PreparationFailure("artifact_index_invalid")
    selected: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise PreparationFailure("artifact_index_invalid")
        relative = PurePosixPath(row["path"])
        if (relative.is_absolute() or not row["path"] or ".." in relative.parts
                or relative.as_posix() != row["path"] or "\\" in row["path"]):
            raise PreparationFailure("artifact_path_invalid")
        role = row.get("role")
        key = role if role in {"desktop-manifest", "application", "sidecar"} else None
        if role == "installer" and len(relative.parts) >= 3 and relative.parts[-3:-1] == ("bundle", "nsis"):
            if relative.suffix.lower() != ".exe" or len(relative.parts) < 3:
                raise PreparationFailure("nsis_installer_invalid")
            key = "nsis"
        if key is None:
            continue
        if key in selected or type(row.get("size")) is not int or row["size"] <= 0 or not _hex64(row.get("sha256")):
            raise PreparationFailure("artifact_index_invalid")
        selected[key] = row
    return selected


def source_bound_candidate(delivery_path: Path, source: str, tree: str) -> dict:
    """Crosscheck the real release.py build report, publisher manifest and bytes."""
    if delivery_path.resolve() != DELIVERY.resolve():
        raise PreparationFailure("delivery_path_invalid")
    report_bytes = preflight.checked_bytes(delivery_path)
    report_sha = hashlib.sha256(report_bytes).hexdigest()
    report = json.loads(report_bytes)
    if (not isinstance(report, dict) or type(report.get("schema_version")) is not int
            or report["schema_version"] != 1 or report.get("product") != "Mesh Chat"
            or report.get("status") != "passed" or report.get("platforms") != ["desktop"]
            or report.get("source") != {"git_commit": source, "dirty": False}
            or not isinstance(report.get("gates"), dict) or report["gates"].get("automated") != "passed"
            or not isinstance(report.get("steps"), list)
            or not any(isinstance(step, dict) and step.get("name") == "desktop-build"
                       and step.get("status") == "passed" for step in report["steps"])):
        raise PreparationFailure("delivery_source_invalid")
    indexed = _artifact_rows(report.get("artifacts"))
    if set(indexed) != {"desktop-manifest", "application", "sidecar", "nsis"}:
        raise PreparationFailure("delivery_artifacts_incomplete")
    manifest_relative = PurePosixPath(indexed["desktop-manifest"]["path"])
    if (len(manifest_relative.parts) != 6 or manifest_relative.parts[:3] != ("dist", "desktop", "releases")
            or manifest_relative.name != "manifest.json"):
        raise PreparationFailure("delivery_manifest_path_invalid")
    manifest_path = ROOT.joinpath(*manifest_relative.parts)
    manifest_bytes = preflight.checked_bytes(manifest_path)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    if (len(manifest_bytes) != indexed["desktop-manifest"]["size"]
            or manifest_sha != indexed["desktop-manifest"]["sha256"].lower()):
        raise PreparationFailure("delivery_manifest_mismatch")
    manifest = json.loads(manifest_bytes)
    if (not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] != 1 or manifest.get("product") != "Mesh Chat"
            or manifest.get("platform") != "windows" or manifest.get("version") != report.get("version")):
        raise PreparationFailure("publisher_manifest_invalid")
    published = _artifact_rows(manifest.get("artifacts"))
    if set(published) != {"application", "sidecar", "nsis"}:
        raise PreparationFailure("publisher_artifacts_incomplete")
    prefix = manifest_relative.parent
    for role, name in (("application", "mesh-chat.exe"), ("sidecar", "mesh-chat-service.exe")):
        row, index = published[role], indexed[role]
        if (row["path"] != name or PurePosixPath(index["path"]) != prefix / name
                or row["size"] != index["size"] or row["sha256"].lower() != index["sha256"].lower()):
            raise PreparationFailure("candidate_artifacts_unbound")
    installer_row, installer_index = published["nsis"], indexed["nsis"]
    relative_installer = PurePosixPath(installer_row["path"])
    if (len(relative_installer.parts) != 3 or relative_installer.parts[:2] != ("bundle", "nsis")
            or PurePosixPath(installer_index["path"]) != prefix / relative_installer
            or installer_row["size"] != installer_index["size"]
            or installer_row["sha256"].lower() != installer_index["sha256"].lower()):
        raise PreparationFailure("nsis_installer_unbound")
    files = {"application": manifest_path.parent / "mesh-chat.exe",
             "sidecar": manifest_path.parent / "mesh-chat-service.exe",
             "nsis": manifest_path.parent.joinpath(*relative_installer.parts)}
    for role, path in files.items():
        row = published[role]
        if (preflight.regular_input(path, 2 * 1024 * 1024 * 1024) != row["size"]
                or preflight.digest(path) != row["sha256"].lower()):
            raise PreparationFailure("candidate_file_mismatch")
    return {"source_commit": source, "source_tree": tree, "delivery_report_sha256": report_sha,
            "release_manifest_sha256": manifest_sha, "manifest_path": manifest_path,
            "installer_path": files["nsis"], "installer_sha256": installer_row["sha256"].lower(),
            "installer_size": installer_row["size"],
            "application_sha256": published["application"]["sha256"].lower(),
            "application_size": published["application"]["size"],
            "sidecar_sha256": published["sidecar"]["sha256"].lower(),
            "sidecar_size": published["sidecar"]["size"]}


def installer_command(installer: Path, directory: Path) -> str:
    """NSIS /D consumes the unquoted remainder of CreateProcess's command line."""
    path = str(directory)
    if (not directory.is_absolute() or re.fullmatch(r"[A-Za-z]:\\[^\r\n\"]+", path) is None
            or path.endswith(("\\", "/"))):
        raise PreparationFailure("install_directory_invalid")
    return subprocess.list2cmdline([str(installer)]) + " /S /D=" + path


def fresh_runner_temp() -> Path:
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Windows":
        raise PreparationFailure("disposable_windows_runner_required")
    raw = os.environ.get("RUNNER_TEMP")
    if not raw:
        raise PreparationFailure("runner_temp_missing")
    parent = Path(raw)
    if (not parent.is_absolute() or parent.resolve().is_relative_to(ROOT)
            or not parent.is_dir() or not re.fullmatch(r"[A-Za-z]:\\[^\r\n\"]+", str(parent))):
        raise PreparationFailure("runner_temp_invalid")
    return parent


def fresh_user_app_data() -> None:
    config = json.loads(preflight.checked_bytes(ROOT / "src-tauri/tauri.conf.json"))
    if (not isinstance(config, dict) or not isinstance(config.get("app"), dict)
            or config["app"].get("appDirectoriesOverride") is not None
            or not isinstance(config.get("identifier"), str)):
        raise PreparationFailure("app_config_invalid")
    roaming = preflight.known_folder("3EB685DB-65F9-4CF6-A03A-E3EF65729F3D")
    local = preflight.known_folder("F1B32785-6FBA-4FCF-9D55-7B8E7F157091")
    if (Path(os.environ["APPDATA"]).resolve() != roaming
            or Path(os.environ["LOCALAPPDATA"]).resolve() != local):
        raise PreparationFailure("app_data_env_mismatch")
    preflight.require_fresh_app_data(config["identifier"], roaming, local)


def install(installer: Path, directory: Path) -> tuple[int, bool]:
    command = installer_command(installer, directory)
    process = subprocess.Popen(command, executable=str(installer), cwd=installer.parent,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, shell=False,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        return process.wait(timeout=INSTALL_TIMEOUT_SECONDS), True
    except subprocess.TimeoutExpired as error:
        process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            raise PreparationFailure("installer_child_retirement_uncertain") from error
        raise PreparationFailure("installer_timed_out") from error


def run_preflight(app: Path, candidate: dict, args: argparse.Namespace, result: dict) -> tuple[bool, str]:
    if args.preflight_output.exists():
        raise PreparationFailure("preflight_output_not_fresh")
    command = [sys.executable, str(PREFLIGHT), "--app", str(app),
               "--release-manifest", str(candidate["manifest_path"]),
               "--expected-manifest-sha256", candidate["release_manifest_sha256"],
               "--delivery-report", str(DELIVERY),
               "--expected-delivery-report-sha256", candidate["delivery_report_sha256"],
               "--expected-source", candidate["source_commit"], "--expected-tree", candidate["source_tree"],
               "--run-id", args.run_id, "--run-attempt", str(args.run_attempt),
               "--node", str(args.node), "--output", str(args.preflight_output)]
    process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        code = process.wait(timeout=PREFLIGHT_TIMEOUT_SECONDS)
        result["preflight_child_retired"] = True
    except subprocess.TimeoutExpired as error:
        result["app_retirement_unconfirmed"] = True
        try:
            process.kill()
        except OSError:
            if process.poll() is None:
                result["preflight_child_retired"] = False
                raise PreparationFailure("preflight_child_retirement_uncertain") from error
        try:
            process.wait(timeout=5)
            result["preflight_child_retired"] = True
        except subprocess.TimeoutExpired:
            result["preflight_child_retired"] = False
            raise PreparationFailure("preflight_child_retirement_uncertain") from error
        raise PreparationFailure("preflight_timed_out_app_retirement_unconfirmed") from error
    raw = preflight.checked_bytes(args.preflight_output, preflight.MAX_REPORT_BYTES)
    record = json.loads(raw)
    if (not isinstance(record, dict) or record.get("source_commit") != candidate["source_commit"]
            or record.get("source_tree") != candidate["source_tree"] or record.get("run_id") != args.run_id
            or record.get("run_attempt") != args.run_attempt
            or record.get("release_manifest_sha256") != candidate["release_manifest_sha256"]
            or record.get("delivery_report_sha256") != candidate["delivery_report_sha256"]
            or record.get("application_sha256") != candidate["application_sha256"]
            or record.get("sidecar_sha256") != candidate["sidecar_sha256"]):
        raise PreparationFailure("preflight_result_unbound")
    result["app_retired"] = record.get("app_retired") is True
    return code == 0 and record.get("passed") is True, hashlib.sha256(raw).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--expected-tree")
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID"))
    parser.add_argument("--run-attempt", type=int, default=os.environ.get("GITHUB_RUN_ATTEMPT"))
    parser.add_argument("--delivery-report", type=Path, default=DELIVERY)
    parser.add_argument("--node", type=Path, default=Path("node"))
    parser.add_argument("--preflight-output", type=Path, default=ROOT / "dist/reports/packaged-media-preflight.json")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/reports/packaged-media-install.json")
    args = parser.parse_args()
    result = {"v": 1, "passed": False, "evidence_level": LEVEL, "run_id": args.run_id,
              "run_attempt": args.run_attempt, "phase": "runner_admission"}
    try:
        if (sys.platform != "win32" or not isinstance(args.run_id, str)
                or not re.fullmatch(r"[0-9]{1,20}", args.run_id)
                or not isinstance(args.run_attempt, int) or args.run_attempt < 1
                or os.environ.get("GITHUB_RUN_ID") != args.run_id
                or os.environ.get("GITHUB_RUN_ATTEMPT") != str(args.run_attempt)):
            raise PreparationFailure("run_context_invalid")
        parent = fresh_runner_temp()
        if not preflight.HEX40.fullmatch(args.expected_source):
            raise PreparationFailure("expected_source_invalid")
        expected_tree = args.expected_tree or subprocess.check_output(
            ["git", "show", "-s", "--format=%T", args.expected_source], cwd=ROOT, text=True).strip()
        source, tree = preflight.source_identity(args.expected_source, expected_tree)
        result.update(source_commit=source, source_tree=tree)
        result["phase"] = "candidate_admission"
        candidate = source_bound_candidate(args.delivery_report, source, tree)
        result.update({key: candidate[key] for key in ("delivery_report_sha256", "release_manifest_sha256",
                      "installer_sha256", "installer_size", "application_sha256", "sidecar_sha256")})
        fresh_user_app_data()
        result["phase"] = "install"
        install_dir = Path(tempfile.mkdtemp(prefix="mesh-media-install-", dir=parent))
        result["fresh_install_directory_created"] = True
        code, retired = install(candidate["installer_path"], install_dir)
        result["installer_exit_code"] = code
        result["installer_child_retired"] = retired
        if code != 0:
            raise PreparationFailure("installer_failed")
        app = install_dir / "mesh-chat.exe"
        if (preflight.regular_input(app, 2 * 1024 * 1024 * 1024) != candidate["application_size"]
                or preflight.digest(app) != candidate["application_sha256"]
                or preflight.regular_input(install_dir / "mesh-chat-service.exe", 2 * 1024 * 1024 * 1024)
                != candidate["sidecar_size"]
                or preflight.digest(install_dir / "mesh-chat-service.exe") != candidate["sidecar_sha256"]):
            raise PreparationFailure("installed_bytes_mismatch")
        result["phase"] = "capture_preflight"
        passed, report_sha = run_preflight(app, candidate, args, result)
        result["preflight_report_sha256"] = report_sha
        result["preflight_passed"] = passed
        if not passed:
            raise PreparationFailure("capture_preflight_failed")
        result["phase"] = "final_binding"
        if (preflight.source_identity(source, tree) != (source, tree)
                or source_bound_candidate(args.delivery_report, source, tree) != candidate
                or preflight.regular_input(app, 2 * 1024 * 1024 * 1024) != candidate["application_size"]
                or preflight.digest(app) != candidate["application_sha256"]
                or preflight.regular_input(install_dir / "mesh-chat-service.exe", 2 * 1024 * 1024 * 1024)
                != candidate["sidecar_size"]
                or preflight.digest(install_dir / "mesh-chat-service.exe") != candidate["sidecar_sha256"]):
            raise PreparationFailure("candidate_changed_during_run")
        result["passed"] = True
        result["phase"] = "complete"
    except Exception as error:
        result["failure"] = str(error) if isinstance(error, (PreparationFailure, preflight.PreflightFailure)) else type(error).__name__
    preflight.write_report(args.output, result)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
