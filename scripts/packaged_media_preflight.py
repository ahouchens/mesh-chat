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
from pathlib import Path
import re
import socket
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
FIELDS = {"appMounted", "tauriBridge", "mediaApi", "peerApi", "captured", "stopped"}
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
HEX40 = re.compile(r"[a-f0-9]{40}\Z")


class PreflightFailure(RuntimeError):
    pass


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def source_identity(expected: str) -> tuple[str, str]:
    if not HEX40.fullmatch(expected):
        raise PreflightFailure("expected_source_invalid")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(["git", "show", "-s", "--format=%T", "HEAD"], cwd=ROOT, text=True).strip()
    if head != expected or not HEX40.fullmatch(tree):
        raise PreflightFailure("source_mismatch")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT):
        raise PreflightFailure("source_dirty")
    return head, tree


def published_bytes(manifest_path: Path, expected_digest: str, app: Path) -> dict[str, str]:
    if not HEX64.fullmatch(expected_digest) or digest(manifest_path) != expected_digest:
        raise PreflightFailure("manifest_mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] != 1
            or manifest.get("product") != "Mesh Chat"
            or manifest.get("platform") != "windows" or not isinstance(manifest.get("artifacts"), list)):
        raise PreflightFailure("manifest_invalid")
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
    bound = {}
    for role, path in (("application", app), ("sidecar", app.with_name("mesh-chat-service.exe"))):
        row = roles[role]
        if not path.is_file() or path.stat().st_size != row["size"] or digest(path) != row["sha256"]:
            raise PreflightFailure("installed_bytes_mismatch")
        bound[role + "_sha256"] = row["sha256"]
    return bound


def require_fresh_app_data(identifier: str, roaming: Path, local: Path) -> None:
    if identifier != "com.meshchat.desktop" or not roaming.is_absolute() or not local.is_absolute():
        raise PreflightFailure("app_data_scope_invalid")
    if not roaming.is_dir() or not local.is_dir():
        raise PreflightFailure("app_data_roots_missing")
    if (roaming / identifier).exists() or (local / identifier).exists():
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
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as output:
        json.dump(report, output, indent=2, sort_keys=True)
        output.write("\n")
        pending = Path(output.name)
    pending.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True, help="installed mesh-chat.exe, outside the source checkout")
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--expected-source", required=True)
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
        source, tree = source_identity(args.expected_source)
        report.update(source_commit=source, source_tree=tree)
        report["phase"] = "published_bytes"
        report.update(published_bytes(args.release_manifest, args.expected_manifest_sha256, args.app))
        report["release_manifest_sha256"] = args.expected_manifest_sha256
        report["driver_sha256"] = digest(DRIVER)
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
        probe = subprocess.run([str(args.node), str(DRIVER), str(port), "60000"], cwd=ROOT,
                               text=True, capture_output=True, timeout=65)
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
