"""Source-bound Windows app/WebView2 media preflight, before an R5 call scenario.

Run on a fresh interactive Windows user after installing the exact published
candidate. This probes the app's real WebView2 capture engine, not CallDialog,
pairing, authenticated receipts, or a completed media call.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import stat
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen
from uuid import UUID


ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "scripts/packaged_media_preflight.mjs"
LEVEL = "windows_packaged_app_webview2_media_preflight_only"
FIELDS = {"appMounted", "tauriBridge", "mediaApi", "peerApi", "buildCommitMatches", "captured", "stopped"}
PROBE_FAILURE_PREFIX = "mesh_media_probe_failure_v1:"
PROBE_STAGES = {"arguments", "target_discovery", "devtools_connect", "runtime_enable",
                "runtime_evaluate", "result_validation"}
PROBE_CODES = {"invalid_probe_arguments", "app_webview_unavailable", "devtools_deadline",
               "devtools_socket_failed", "devtools_command_failed", "invalid_media_probe", "unexpected"}
HEX64 = re.compile(r"[a-fA-F0-9]{64}\Z")
HEX40 = re.compile(r"[a-f0-9]{40}\Z")
VERSION = re.compile(r"(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,2})\.(0|[1-9][0-9]{0,2})\Z")
MAX_REPORT_BYTES = 16 * 1024


class PreflightFailure(RuntimeError):
    pass


def bounded_probe_failure(stderr: str) -> dict[str, str] | None:
    """Retain only one fixed-stage driver failure, never raw DevTools output."""
    if len(stderr) > 8192:
        return None
    markers = [line.removeprefix(PROBE_FAILURE_PREFIX) for line in stderr.splitlines()
               if line.startswith(PROBE_FAILURE_PREFIX)]
    if len(markers) != 1:
        return None
    try:
        value = json.loads(markers[0])
    except json.JSONDecodeError:
        return None
    if (not isinstance(value, dict) or set(value) != {"stage", "code"}
            or type(value["stage"]) is not str or value["stage"] not in PROBE_STAGES
            or type(value["code"]) is not str or value["code"] not in PROBE_CODES):
        return None
    return value


def regular_input(path: Path, limit: int) -> int:
    absolute = path.absolute()
    for item in (absolute, *absolute.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise PreflightFailure("reparse_input")
    info = absolute.lstat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
        raise PreflightFailure("input_size_or_type_invalid")
    return info.st_size


def checked_bytes(path: Path, limit: int = 4 * 1024 * 1024) -> bytes:
    size = regular_input(path, limit)
    value = path.read_bytes()
    if len(value) != size:
        raise PreflightFailure("input_changed_during_read")
    return value


def digest(path: Path) -> str:
    expected_size = regular_input(path, 2 * 1024 * 1024 * 1024)
    value = hashlib.sha256()
    count = 0
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
            count += len(block)
            if count > expected_size:
                raise PreflightFailure("input_changed_during_read")
    if count != expected_size:
        raise PreflightFailure("input_changed_during_read")
    return value.hexdigest()


def source_identity(expected: str, expected_tree: str) -> tuple[str, str]:
    if not HEX40.fullmatch(expected) or not HEX40.fullmatch(expected_tree):
        raise PreflightFailure("expected_source_invalid")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(["git", "show", "-s", "--format=%T", "HEAD"], cwd=ROOT, text=True).strip()
    if head != expected or tree != expected_tree:
        raise PreflightFailure("source_mismatch")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT):
        raise PreflightFailure("source_dirty")
    return head, tree


def published_bytes(manifest_path: Path, expected_digest: str, app: Path) -> dict[str, str | int]:
    if not HEX64.fullmatch(expected_digest):
        raise PreflightFailure("manifest_mismatch")
    manifest_bytes = checked_bytes(manifest_path)
    if hashlib.sha256(manifest_bytes).hexdigest() != expected_digest.lower():
        raise PreflightFailure("manifest_mismatch")
    manifest = json.loads(manifest_bytes)
    if (not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] != 1
            or manifest.get("product") != "Mesh Chat"
            or manifest.get("platform") != "windows" or not isinstance(manifest.get("version"), str)
            or not isinstance(manifest.get("artifacts"), list)):
        raise PreflightFailure("manifest_invalid")
    version = manifest["version"]
    match = VERSION.fullmatch(version) if len(version) <= 12 else None
    if match is None or int(match.group(1)) * 1_000_000 + int(match.group(2)) * 1_000 + int(match.group(3)) > 2_100_000_000:
        raise PreflightFailure("manifest_version_invalid")
    if app.name.lower() != "mesh-chat.exe" or app.resolve().is_relative_to(ROOT):
        raise PreflightFailure("app_not_installed_candidate")
    roles = {}
    for row in manifest["artifacts"]:
        if not isinstance(row, dict) or row.get("role") not in {"application", "sidecar"}:
            continue
        role = row["role"]
        if role in roles or row.get("path") != {"application": "mesh-chat.exe", "sidecar": "mesh-chat-service.exe"}[role]:
            raise PreflightFailure("manifest_invalid")
        if (type(row.get("size")) is not int or row["size"] <= 0
                or not isinstance(row.get("sha256"), str) or not HEX64.fullmatch(row["sha256"])):
            raise PreflightFailure("manifest_invalid")
        roles[role] = row
    if set(roles) != {"application", "sidecar"}:
        raise PreflightFailure("manifest_incomplete")
    bound: dict[str, str | int] = {"release_version": manifest["version"]}
    for role, path in (("application", app), ("sidecar", app.with_name("mesh-chat-service.exe"))):
        row = roles[role]
        if regular_input(path, 2 * 1024 * 1024 * 1024) != row["size"] or digest(path) != row["sha256"].lower():
            raise PreflightFailure("installed_bytes_mismatch")
        bound[role + "_sha256"] = row["sha256"].lower()
        bound[role + "_size"] = row["size"]
    return bound


def delivery_provenance(path: Path, expected_digest: str, source: str, manifest_path: Path,
                        manifest_digest: str, bound: dict[str, str | int]) -> str:
    """Validate scripts/release.py build report's source and artifact crosslinks."""
    if not HEX64.fullmatch(expected_digest):
        raise PreflightFailure("delivery_report_mismatch")
    raw = checked_bytes(path)
    if hashlib.sha256(raw).hexdigest() != expected_digest.lower():
        raise PreflightFailure("delivery_report_mismatch")
    value = json.loads(raw)
    if (not isinstance(value, dict) or type(value.get("schema_version")) is not int
            or value["schema_version"] != 1 or value.get("product") != "Mesh Chat"
            or value.get("version") != bound["release_version"]
            or value.get("status") != "passed" or not isinstance(value.get("platforms"), list)
            or "desktop" not in value["platforms"] or not isinstance(value.get("source"), dict)
            or value["source"] != {"git_commit": source, "dirty": False}
            or not isinstance(value.get("gates"), dict) or value["gates"].get("automated") != "passed"
            or not isinstance(value.get("steps"), list)
            or not any(isinstance(step, dict) and step.get("name") == "desktop-build"
                       and step.get("status") == "passed" for step in value["steps"])
            or not isinstance(value.get("artifacts"), list)):
        raise PreflightFailure("delivery_source_invalid")
    roles: dict[str, dict] = {}
    for item in value["artifacts"]:
        if not isinstance(item, dict) or item.get("role") not in {"desktop-manifest", "application", "sidecar"}:
            continue
        role = item["role"]
        if (role in roles or not isinstance(item.get("path"), str)
                or not isinstance(item.get("sha256"), str) or not HEX64.fullmatch(item["sha256"].lower())
                or type(item.get("size")) is not int or item["size"] <= 0):
            raise PreflightFailure("delivery_artifacts_invalid")
        roles[role] = item
    if set(roles) != {"desktop-manifest", "application", "sidecar"}:
        raise PreflightFailure("delivery_artifacts_incomplete")
    manifest_row = roles["desktop-manifest"]
    manifest_name = PurePosixPath(manifest_row["path"])
    if (manifest_name.name != "manifest.json" or manifest_name.is_absolute()
            or ".." in manifest_name.parts or manifest_row["sha256"].lower() != manifest_digest
            or manifest_row["size"] != regular_input(manifest_path, 4 * 1024 * 1024)):
        raise PreflightFailure("delivery_manifest_unbound")
    for role, name in (("application", "mesh-chat.exe"), ("sidecar", "mesh-chat-service.exe")):
        row = roles[role]
        relative = PurePosixPath(row["path"])
        if (relative != manifest_name.parent / name or row["sha256"].lower() != bound[role + "_sha256"]
                or row["size"] != bound[role + "_size"]):
            raise PreflightFailure("delivery_artifacts_unbound")
    return expected_digest.lower()


def require_unchanged(source: str, tree: str, manifest_path: Path, manifest_sha: str,
                      delivery_path: Path, delivery_sha: str, app: Path,
                      bound: dict[str, str | int], driver_sha: str) -> None:
    if (source_identity(source, tree) != (source, tree)
            or published_bytes(manifest_path, manifest_sha, app) != bound
            or delivery_provenance(delivery_path, delivery_sha, source, manifest_path,
                                   manifest_sha, bound) != delivery_sha
            or digest(DRIVER) != driver_sha):
        raise PreflightFailure("inputs_changed_during_probe")


def require_fresh_app_data(identifier: str, roaming: Path, local: Path) -> None:
    if identifier != "com.meshchat.desktop" or not roaming.is_absolute() or not local.is_absolute():
        raise PreflightFailure("app_data_scope_invalid")
    if not roaming.is_dir() or not local.is_dir():
        raise PreflightFailure("app_data_roots_missing")
    if os.path.lexists(roaming / identifier) or os.path.lexists(local / identifier):
        raise PreflightFailure("app_data_not_fresh")


def known_folder(guid: str) -> Path:
    """Use the same OS known folders Tauri resolves, not caller-set path text."""
    shell32 = ctypes.WinDLL("shell32")
    ole32 = ctypes.WinDLL("ole32")
    identifier = (ctypes.c_byte * 16).from_buffer_copy(UUID(guid).bytes_le)
    result = ctypes.c_wchar_p()
    shell32.SHGetKnownFolderPath.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
                                            ctypes.POINTER(ctypes.c_wchar_p)]
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    if shell32.SHGetKnownFolderPath(ctypes.byref(identifier), 0, None, ctypes.byref(result)) != 0:
        raise PreflightFailure("known_folder_unavailable")
    try:
        return Path(result.value).resolve()
    finally:
        ole32.CoTaskMemFree(ctypes.cast(result, ctypes.c_void_p))


def reserve_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def cdp_closed(port: int) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=0.5):
            return False
    except (OSError, URLError):
        return True


def request_app_window_close(pid: int) -> bool:
    """Post WM_CLOSE only to top-level windows owned by this launched app PID."""
    user32 = ctypes.WinDLL("user32")
    handles: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows.argtypes = [callback_type, ctypes.c_void_p]
    user32.EnumWindows.restype = ctypes.c_bool
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user32.IsWindowVisible.restype = ctypes.c_bool
    user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_size_t, ctypes.c_ssize_t]
    user32.PostMessageW.restype = ctypes.c_bool

    @callback_type
    def collect(handle, _data):
        owner = ctypes.c_uint32()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(handle):
            handles.append(handle)
        return True

    user32.EnumWindows(collect, 0)
    return bool(handles) and all(user32.PostMessageW(handle, 0x0010, 0, 0) for handle in handles)


def retire(process: subprocess.Popen[bytes] | None, port: int | None) -> bool:
    if process is None:
        return True
    graceful = False
    if process.poll() is None:
        graceful = request_app_window_close(process.pid)
        if graceful:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                graceful = False
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    if port is None:
        return graceful and process.poll() is not None
    for _ in range(20):
        if cdp_closed(port):
            return graceful and process.poll() is not None
        time.sleep(0.25)
    return False


def write_report(path: Path, report: dict) -> None:
    payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(payload) > MAX_REPORT_BYTES:
        raise PreflightFailure("report_too_large")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, suffix=".tmp", delete=False) as output:
        output.write(payload)
        pending = Path(output.name)
    pending.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True, help="installed mesh-chat.exe, outside the source checkout")
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--delivery-report", type=Path, required=True, help="scripts/release.py desktop build report")
    parser.add_argument("--expected-delivery-report-sha256", required=True)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--expected-tree", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--node", type=Path, default=Path("node"))
    parser.add_argument("--output", type=Path, default=ROOT / "dist/reports/packaged-media-preflight.json")
    args = parser.parse_args()
    report = {"v": 1, "passed": False, "evidence_level": LEVEL, "phase": "arguments",
              "run_id": args.run_id, "run_attempt": args.run_attempt}
    process = None
    port = None
    try:
        if sys.platform != "win32" or not re.fullmatch(r"[0-9]{1,20}", args.run_id) or args.run_attempt < 1:
            raise PreflightFailure("platform_or_run_invalid")
        if (os.environ.get("GITHUB_RUN_ID") != args.run_id
                or os.environ.get("GITHUB_RUN_ATTEMPT") != str(args.run_attempt)):
            raise PreflightFailure("run_context_mismatch")
        source, tree = source_identity(args.expected_source, args.expected_tree)
        report.update(source_commit=source, source_tree=tree)
        report["phase"] = "published_bytes"
        bound = published_bytes(args.release_manifest, args.expected_manifest_sha256, args.app)
        report.update(bound)
        report["release_manifest_sha256"] = args.expected_manifest_sha256.lower()
        report["phase"] = "delivery_provenance"
        report["delivery_report_sha256"] = delivery_provenance(
            args.delivery_report, args.expected_delivery_report_sha256, source,
            args.release_manifest, report["release_manifest_sha256"], bound)
        driver_sha = digest(DRIVER)
        report["driver_sha256"] = driver_sha
        report["phase"] = "fresh_app_data"
        config = json.loads((ROOT / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
        if not isinstance(config, dict) or not isinstance(config.get("app"), dict):
            raise PreflightFailure("app_config_invalid")
        if config["app"].get("appDirectoriesOverride") is not None:
            raise PreflightFailure("app_data_override_unreviewed")
        roaming = known_folder("3EB685DB-65F9-4CF6-A03A-E3EF65729F3D")
        local = known_folder("F1B32785-6FBA-4FCF-9D55-7B8E7F157091")
        if Path(os.environ["APPDATA"]).resolve() != roaming or Path(os.environ["LOCALAPPDATA"]).resolve() != local:
            raise PreflightFailure("app_data_env_mismatch")
        require_fresh_app_data(config.get("identifier"), roaming, local)
        if "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS" in os.environ:
            raise PreflightFailure("inherited_webview_flags")
        node_version = subprocess.run([str(args.node), "--version"], text=True, capture_output=True, timeout=5)
        match = re.fullmatch(r"v([0-9]{1,3})\.[0-9]{1,3}\.[0-9]{1,3}\s*", node_version.stdout)
        if node_version.returncode != 0 or not match or int(match.group(1)) < 24:
            raise PreflightFailure("node_24_required")
        report["node_major"] = int(match.group(1))
        port = reserve_port()
        environment = os.environ.copy()
        environment["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
            f"--remote-debugging-port={port} --use-fake-device-for-media-stream --use-fake-ui-for-media-stream"
        )
        report["phase"] = "webview2_capture"
        process = subprocess.Popen([str(args.app.resolve())], cwd=args.app.parent, env=environment,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        probe = subprocess.run([str(args.node), str(DRIVER), str(port), "60000", source], cwd=ROOT,
                               text=True, capture_output=True, timeout=65)
        if failure := bounded_probe_failure(probe.stderr):
            report["probe_failure"] = failure
        lines = probe.stdout.splitlines()
        if len(lines) != 1:
            raise PreflightFailure("probe_output_invalid")
        checks = json.loads(lines[0])
        if (set(checks) != FIELDS or any(type(checks[field]) is not bool for field in FIELDS)):
            raise PreflightFailure("probe_output_invalid")
        report["checks"] = checks
        if probe.returncode != 0 or not all(checks.values()):
            raise PreflightFailure("webview2_capture_failed")
        if process.poll() is not None:
            raise PreflightFailure("app_exited_before_probe_completed")
        report["phase"] = "final_binding"
        require_unchanged(source, tree, args.release_manifest, report["release_manifest_sha256"],
                          args.delivery_report, report["delivery_report_sha256"], args.app, bound, driver_sha)
        report["phase"] = "retirement"
    except Exception as error:
        report["failure"] = str(error) if isinstance(error, PreflightFailure) else type(error).__name__
    finally:
        try:
            report["app_retired"] = retire(process, port)
        except Exception:
            report["app_retired"] = False
        if not report["app_retired"]:
            report["failure"] = "app_retirement_unconfirmed"
        report["passed"] = "failure" not in report and report["app_retired"] and report["phase"] == "retirement"
        write_report(args.output, report)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
