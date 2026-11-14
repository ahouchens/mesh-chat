"""Disposable CI-only installed Windows v0.9.66 whole-app continuity attempt.

The candidate has the same version as the published baseline. An installer that
does not replace both binaries fails this lane. This makes no peer or schema claim.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import packaged_media_preflight as media
import run_packaged_media_preflight as installer
from windows_release_app_custody import OwnedApp, install_with_job


ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "scripts/check_windows_release_ui.mjs"
BASELINE_SOURCE = "7c40f7b23eab3e9d83ff7ca1075c90c4d84ce516"
BASELINE_INSTALLER_SHA256 = "a20b381a8c7199c40aeba0487634c1302043c3e07d8b66c7838be8abfc050e23"
BASELINE_FILES = {
    "application": (8604672, "b6afcfbf67f90b351393131f159e3e97018090a82b60bbafda41463299f148d2"),
    "sidecar": (20566140, "e5a9e908d3eff074b516e916440fc395d02dfe96a3149ef5a18fbdad2cea47c5"),
}
VERSION = "0.9.66"
WEBVIEW_CLIENT = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
LEVEL = "disposable_windows_installed_same_version_continuity_attempt"
MAX_DRIVER_OUTPUT = 16 * 1024


class ContinuityFailure(RuntimeError):
    pass


class CREDENTIALW(ctypes.Structure):
    _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.c_void_p), ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]


def require_fresh_credential_slot() -> None:
    """Enumerate names only; never read or report credential material."""
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    pointer = ctypes.POINTER(ctypes.POINTER(CREDENTIALW))()
    count = wintypes.DWORD()
    advapi.CredEnumerateW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                     ctypes.POINTER(wintypes.DWORD),
                                     ctypes.POINTER(ctypes.POINTER(ctypes.POINTER(CREDENTIALW)))]
    advapi.CredEnumerateW.restype = wintypes.BOOL
    advapi.CredFree.argtypes = [ctypes.c_void_p]
    if not advapi.CredEnumerateW(None, 0, ctypes.byref(count), ctypes.byref(pointer)):
        if ctypes.get_last_error() == 1168:  # ERROR_NOT_FOUND
            return
        raise ContinuityFailure("credential_inventory_unavailable")
    try:
        for index in range(count.value):
            name = (pointer[index].contents.TargetName or "").lower()
            if "com.meshchat.desktop" in name or "vault-key-v1" in name:
                raise ContinuityFailure("credential_slot_not_fresh")
    finally:
        advapi.CredFree(pointer)


def require_webview2_ready() -> None:
    import winreg
    path = rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW_CLIENT}"
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view) as key:
                    version, kind = winreg.QueryValueEx(key, "pv")
                if kind == winreg.REG_SZ and re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", version) and version != "0.0.0.0":
                    return
            except OSError:
                continue
    raise ContinuityFailure("webview2_runtime_not_ready")


def exact_file(path: Path, size: int, sha256: str) -> bool:
    try:
        return media.regular_input(path, 2 * 1024 * 1024 * 1024) == size and media.digest(path) == sha256
    except (OSError, media.PreflightFailure):
        return False


def observed_baseline_files(directory: Path) -> dict:
    """Only the two known binary sizes and digests enter the report."""
    observed = {}
    for role, name in (("application", "mesh-chat.exe"), ("sidecar", "mesh-chat-service.exe")):
        expected_size, expected_sha = BASELINE_FILES[role]
        try:
            path = directory / name
            size = media.regular_input(path, 2 * 1024 * 1024 * 1024)
            sha256 = media.digest(path)
            observed[role] = {"size_bytes": size, "sha256": sha256,
                              "matches_expected": size == expected_size and sha256 == expected_sha}
        except (OSError, media.PreflightFailure):
            observed[role] = {"availability": "unavailable", "matches_expected": False}
    return observed


def file_rows_match(rows: dict) -> bool:
    return set(rows) == {"application", "sidecar"} and all(
        rows[role].get("matches_expected") is True for role in ("application", "sidecar"))


def candidate_binding(candidate: dict) -> dict:
    """Pin the publisher and delivery hashes without exposing artifact paths."""
    return {"source_commit": candidate["source_commit"], "source_tree": candidate["source_tree"],
            "delivery_report_sha256": candidate["delivery_report_sha256"],
            "release_manifest_sha256": candidate["release_manifest_sha256"],
            "installer": {"size_bytes": candidate["installer_size"],
                          "sha256": candidate["installer_sha256"]},
            "application": {"size_bytes": candidate["application_size"],
                            "sha256": candidate["application_sha256"]},
            "sidecar": {"size_bytes": candidate["sidecar_size"],
                        "sha256": candidate["sidecar_sha256"]}}


def protected_profile(roaming: Path) -> bool:
    root = roaming / "com.meshchat.desktop" / "profile-v1"
    for path in (root, root / "mesh-chat.vault"):
        try:
            if path.is_symlink() or not path.stat().st_file_attributes & 0x4000:
                return False
        except OSError:
            return False
    return True


def valid_hashes(value: object) -> bool:
    fields = {"profile", "workspace", "channel", "message_id", "message_text", "draft_text"}
    return isinstance(value, dict) and set(value) == fields and all(
        isinstance(item, str) and re.fullmatch(r"[a-f0-9]{64}", item) for item in value.values())


def run_ui(node: Path, port: int, config: dict) -> dict:
    payload = json.dumps(config, separators=(",", ":")).encode() + b"\n"
    if len(payload) > 2048:
        raise ContinuityFailure("ui_config_oversized")
    probe = subprocess.run([str(node), str(DRIVER), str(port)], cwd=ROOT, input=payload,
                           capture_output=True, timeout=100, creationflags=subprocess.CREATE_NO_WINDOW)
    if probe.returncode or len(probe.stdout) > MAX_DRIVER_OUTPUT or probe.stderr or probe.stdout.count(b"\n") != 1:
        raise ContinuityFailure("ui_driver_failed")
    value = json.loads(probe.stdout)
    if (not isinstance(value, dict)
            or set(value) != {"v", "passed", "evidence_level", "source_commit", "installed_version",
                              "phase", "hashes", "native_upgrade_qualified", "peer_receipt_qualified",
                              "schema_refusal_qualified", "physical_device_identity_qualified"}
            or value.get("v") != 1 or value.get("passed") is not True
            or value.get("evidence_level") != "windows_release_ui_seed_readback_contract_only"
            or value.get("phase") != config["phase"]
            or value.get("source_commit") != config["expected_source"]
            or value.get("installed_version") != VERSION
            or not valid_hashes(value.get("hashes"))
            or any(value.get(field) is not False for field in
                   ("native_upgrade_qualified", "peer_receipt_qualified",
                    "schema_refusal_qualified", "physical_device_identity_qualified"))):
        raise ContinuityFailure("ui_driver_report_invalid")
    return value


def check_hashes(seed: dict, observed: dict, reopened: dict) -> bool:
    hashes = [item.get("hashes") for item in (seed, observed, reopened)]
    return all(valid_hashes(item) for item in hashes) and hashes[0] == hashes[1] == hashes[2]


def ui_config(phase: str, source: str, marker: str) -> dict:
    return {"phase": phase, "expected_source": source, "expected_version": VERSION,
            "workspace_name": f"R8 CI {marker}", "message_text": f"R8 message {marker}",
            "draft_text": f"R8 draft {marker}"}


def install_owned(executable: Path, directory: Path, cleanup: dict) -> tuple[int, bool]:
    return install_with_job(installer.installer_command(executable, directory), executable,
                            cleanup=cleanup)


def launch_and_observe(app_path: Path, node: Path, config: dict, observation: dict) -> dict:
    port = media.reserve_port()
    flags = f"--remote-debugging-port={port}"
    environment = os.environ.copy()
    policy = None
    app = None
    retired = False
    primary_failure = None
    observation["browser_flag_scope"] = "hklm_app_policy" if media.token_elevated() else "child_environment"
    try:
        if observation["browser_flag_scope"] == "hklm_app_policy":
            policy = media.ScopedBrowserPolicy(flags)
            policy.install()
        else:
            environment["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = flags
        app = OwnedApp.launch(app_path, app_path.parent, environment, port)
        report = run_ui(node, port, config)
        observation["ui_report"] = report
        app.witness_sidecar()
        retired = app.retire()
        if not retired:
            raise ContinuityFailure("whole_app_retirement_unconfirmed")
        return report
    except BaseException as error:
        primary_failure = error
        cleanup = getattr(error, "release_cleanup", None)
        if isinstance(cleanup, dict):
            observation["launch_cleanup"] = {
                field: cleanup.get(field) is True for field in
                ("job_released", "job_forced_close", "job_close_failed", "process_retired")}
        raise
    finally:
        if app is not None and not retired:
            try: retired = app.retire()
            except Exception: retired = False
        observation["app_retired"] = retired
        policy_retired = True
        if policy is not None:
            try: policy_retired = policy.remove() is True
            except Exception: policy_retired = False
        observation["browser_policy_retired"] = policy_retired
        if primary_failure is None and not policy_retired:
            raise ContinuityFailure("browser_policy_retirement_unconfirmed")


def execute(args: argparse.Namespace, result: dict) -> None:
    if (sys.platform != "win32" or os.environ.get("GITHUB_RUN_ID") != args.run_id
            or os.environ.get("GITHUB_RUN_ATTEMPT") != str(args.run_attempt)
            or not re.fullmatch(r"[0-9]{1,20}", args.run_id or "")
            or args.run_attempt < 1 or os.environ.get("GITHUB_SHA") != args.candidate_source):
        raise ContinuityFailure("runner_context_invalid")
    parent = installer.fresh_runner_temp()
    if "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS" in os.environ:
        raise ContinuityFailure("inherited_webview_flags")
    installer.fresh_user_app_data()
    require_fresh_credential_slot()
    require_webview2_ready()
    result["fresh_runner_profile_credential_webview2"] = True
    if not exact_file(args.baseline_installer, 28012178, BASELINE_INSTALLER_SHA256):
        raise ContinuityFailure("published_installer_bytes_invalid")
    tagged_source = subprocess.check_output(["git", "rev-list", "-n", "1", "v0.9.66"],
                                            cwd=ROOT, text=True, timeout=10).strip()
    if tagged_source != BASELINE_SOURCE:
        raise ContinuityFailure("published_tag_source_invalid")
    result["published_nsis_sha256"] = BASELINE_INSTALLER_SHA256
    result["published_expected_files"] = {
        role: {"size_bytes": size, "sha256": sha256}
        for role, (size, sha256) in BASELINE_FILES.items()}
    source, tree = media.source_identity(args.candidate_source, args.candidate_tree)
    if source == BASELINE_SOURCE:
        raise ContinuityFailure("candidate_not_distinct")
    candidate = installer.source_bound_candidate(installer.DELIVERY, source, tree)
    result["candidate_binding"] = candidate_binding(candidate)
    directory = Path(tempfile.mkdtemp(prefix="mesh-r8-install-", dir=parent))
    result["phase"] = "published_install"
    code, child_retired = install_owned(args.baseline_installer, directory,
                                        result.setdefault("published_installer_custody", {}))
    result["published_installer_exit_code"] = code
    result["published_installer_job_retired"] = child_retired
    result["published_installed_files"] = observed_baseline_files(directory)
    if code != 0 or not child_retired or not file_rows_match(result["published_installed_files"]):
        raise ContinuityFailure("published_install_bytes_invalid")
    result["published_installed_files_verified"] = True
    roaming = media.known_folder("3EB685DB-65F9-4CF6-A03A-E3EF65729F3D")
    marker = args.run_id[-12:] + " " + str(args.run_attempt)
    result["phase"] = "published_ui_seed"
    observations = result.setdefault("ui_observations", {})
    seed = launch_and_observe(directory / "mesh-chat.exe", args.node,
                              ui_config("seed", BASELINE_SOURCE, marker),
                              observations.setdefault("published_seed", {}))
    result["published_installed_files_after_seed"] = observed_baseline_files(directory)
    if (not protected_profile(roaming)
            or not file_rows_match(result["published_installed_files_after_seed"])):
        raise ContinuityFailure("published_profile_or_retirement_invalid")
    result["published_efs_and_whole_app_retired"] = True
    result["phase"] = "same_version_installer_switch"
    if installer.source_bound_candidate(installer.DELIVERY, source, tree) != candidate:
        raise ContinuityFailure("candidate_changed_before_switch")
    code, child_retired = install_owned(candidate["installer_path"], directory,
                                        result.setdefault("candidate_installer_custody", {}))
    installed = installer.installed_artifacts(directory, candidate)
    result["candidate_installer_exit_code"] = code
    result["candidate_installer_job_retired"] = child_retired
    result["candidate_installed_files_before_launch"] = installed
    if code != 0 or not child_retired or not installer.installed_artifacts_match(installed):
        raise ContinuityFailure("same_version_switch_failed_or_mixed_bytes")
    result["same_version_candidate_files_verified"] = True
    result["phase"] = "candidate_observe"
    config = ui_config("observe", source, marker)
    observed = launch_and_observe(directory / "mesh-chat.exe", args.node, config,
                                  observations.setdefault("candidate_observe", {}))
    result["candidate_installed_files_after_observe"] = installer.installed_artifacts(directory, candidate)
    if (not protected_profile(roaming)
            or not installer.installed_artifacts_match(result["candidate_installed_files_after_observe"])):
        raise ContinuityFailure("candidate_profile_or_retirement_invalid")
    result["phase"] = "candidate_reopen"
    reopened = launch_and_observe(directory / "mesh-chat.exe", args.node, config,
                                  observations.setdefault("candidate_reopen", {}))
    result["candidate_installed_files_after_reopen"] = installer.installed_artifacts(directory, candidate)
    if (not protected_profile(roaming)
            or not installer.installed_artifacts_match(result["candidate_installed_files_after_reopen"])):
        raise ContinuityFailure("candidate_reopen_or_retirement_invalid")
    if not check_hashes(seed, observed, reopened):
        raise ContinuityFailure("ui_continuity_hashes_changed")
    result["candidate_installed_files_final"] = installer.installed_artifacts(directory, candidate)
    if (not installer.installed_artifacts_match(result["candidate_installed_files_final"])
            or installer.source_bound_candidate(installer.DELIVERY, source, tree) != candidate
            or media.source_identity(source, tree) != (source, tree)):
        raise ContinuityFailure("candidate_changed_during_run")
    result["ui_hashes_equal_across_switch_and_reopen"] = True
    result["candidate_whole_app_retired_twice"] = True
    result["installed_continuity_executed"] = True
    result["same_version_switch_observed"] = True
    result["passed"] = True
    result["phase"] = "complete"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-installer", type=Path, required=True)
    parser.add_argument("--candidate-source", required=True)
    parser.add_argument("--candidate-tree", required=True)
    parser.add_argument("--node", type=Path, default=Path("node"))
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID"))
    parser.add_argument("--run-attempt", type=int, default=os.environ.get("GITHUB_RUN_ATTEMPT"))
    parser.add_argument("--output", type=Path, default=ROOT / "dist/reports/windows-release-continuity.json")
    args = parser.parse_args()
    result = {"v": 1, "passed": False, "evidence_level": LEVEL, "phase": "runner_admission",
              "run_id": args.run_id, "run_attempt": args.run_attempt,
              "installed_continuity_executed": False,
              "installer_upgrade_qualified": False, "peer_receipt_qualified": False,
              "schema_refusal_qualified": False, "physical_device_identity_qualified": False,
              "full_r8_qualified": False}
    try:
        execute(args, result)
    except Exception as error:
        result["failure"] = str(error) if isinstance(error, (ContinuityFailure, installer.PreparationFailure,
                                                                media.PreflightFailure)) else type(error).__name__
    media.write_report(args.output, result)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
