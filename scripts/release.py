"""Deterministic version, verification, and delivery pipeline for Mesh Chat.

This is the single entry point used by developers and CI. It deliberately does
not install an application, create a Git tag, or mutate a remote release. Those
are separate promotion decisions; this command builds and verifies artifacts
and leaves one report for a human or an LLM to inspect only when it fails.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from .release_version import REPOSITORY, VersionError, check_versions, set_version
except ImportError:  # Direct execution: python scripts/release.py
    from release_version import REPOSITORY, VersionError, check_versions, set_version


SCHEMA_VERSION = 1


class PipelineFailure(RuntimeError):
    def __init__(self, message: str, *, step: str | None = None) -> None:
        super().__init__(message)
        self.step = step


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _command(executable: str, *arguments: str, environment: dict[str, str]) -> list[str]:
    command = [executable, *arguments]
    if os.name == "nt" and Path(executable).suffix.lower() in {".bat", ".cmd"}:
        return [environment.get("COMSPEC", "cmd.exe"), "/d", "/c", *command]
    return command


def _probe(
    executable: str,
    *arguments: str,
    environment: dict[str, str],
) -> str:
    result = subprocess.run(
        _command(executable, *arguments, environment=environment),
        cwd=REPOSITORY,
        env=environment,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=30,
    )
    return result.stdout.strip()


def _node(environment: dict[str, str]) -> Path:
    candidates: list[Path] = []
    if configured := environment.get("MESH_CHAT_NODE"):
        candidates.append(Path(configured))
    if located := shutil.which("node", path=environment.get("PATH")):
        candidates.append(Path(located))
    candidates.append(
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "node"
        / "bin"
        / ("node.exe" if os.name == "nt" else "node")
    )
    checked: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in checked or not resolved.is_file():
            continue
        checked.add(resolved)
        try:
            value = _probe(str(resolved), "--version", environment=environment)
            major = int(value.lstrip("v").split(".", 1)[0])
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
        if major >= 20:
            return resolved
    raise PipelineFailure("Node.js 20 or newer is required")


def _pnpm(environment: dict[str, str]) -> str:
    candidates = [
        environment.get("MESH_CHAT_PNPM"),
        shutil.which("pnpm", path=environment.get("PATH")),
        shutil.which("pnpm.cmd", path=environment.get("PATH")),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            _probe(candidate, "--version", environment=environment)
            return candidate
        except (OSError, subprocess.SubprocessError):
            continue
    raise PipelineFailure("pnpm 11 is required")


def _python() -> Path:
    candidate = REPOSITORY / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return candidate.resolve() if candidate.is_file() else Path(sys.executable).resolve()


def _rustc(environment: dict[str, str]) -> Path | None:
    candidates = [
        environment.get("MESH_CHAT_RUSTC"),
        shutil.which("rustc", path=environment.get("PATH")),
        str(Path.home() / ".cargo" / "bin" / ("rustc.exe" if os.name == "nt" else "rustc")),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if not path.is_file():
            continue
        try:
            _probe(str(path), "--version", environment=environment)
            return path.resolve()
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def build_environment() -> tuple[dict[str, str], dict[str, str]]:
    environment = os.environ.copy()
    node = _node(environment)
    environment["MESH_CHAT_NODE"] = str(node)
    environment["PATH"] = os.pathsep.join([str(node.parent), environment.get("PATH", "")])
    rustc = _rustc(environment)
    if rustc is not None:
        environment["MESH_CHAT_RUSTC"] = str(rustc)
        environment["PATH"] = os.pathsep.join([str(rustc.parent), environment["PATH"]])
    pnpm = _pnpm(environment)
    environment["MESH_CHAT_PNPM"] = pnpm
    tools = {
        "python": _probe(str(_python()), "--version", environment=environment),
        "node": _probe(str(node), "--version", environment=environment),
        "pnpm": _probe(pnpm, "--version", environment=environment),
    }
    if rustc is not None:
        try:
            tools["rustc"] = _probe(str(rustc), "--version", environment=environment).splitlines()[-1]
        except subprocess.SubprocessError:
            pass
    return environment, tools


def _source_state() -> dict[str, object]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=15,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = None
    try:
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=REPOSITORY,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=15,
            ).stdout.strip()
        )
    except (OSError, subprocess.SubprocessError):
        dirty = None
    return {"git_commit": commit, "dirty": dirty}


def _run_step(
    report: dict[str, Any],
    *,
    name: str,
    command: list[str],
    environment: dict[str, str],
    logs: Path,
) -> None:
    log_path = logs / f"{len(report['steps']) + 1:02d}-{name}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    step: dict[str, Any] = {
        "name": name,
        "status": "running",
        "started_at": _now(),
        "command": command,
        "log": log_path.relative_to(REPOSITORY).as_posix(),
    }
    report["steps"].append(step)
    started = time.monotonic()
    printable = subprocess.list2cmdline(command)
    print(f"\n==> {name}\n+ {printable}", flush=True)
    try:
        with log_path.open("w", encoding="utf-8", newline="\n") as log:
            process = subprocess.Popen(
                command,
                cwd=REPOSITORY,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            assert process.stdout is not None
            for line in process.stdout:
                # Windows CI and legacy consoles may expose a non-UTF-8 text
                # encoding. Preserve the original line in the UTF-8 log while
                # replacing only characters the live console cannot render.
                console_encoding = sys.stdout.encoding or "utf-8"
                printable_line = line.encode(console_encoding, errors="replace").decode(
                    console_encoding, errors="replace"
                )
                print(printable_line, end="", flush=True)
                log.write(line)
            return_code = process.wait()
    except OSError as exc:
        step.update(
            status="failed",
            finished_at=_now(),
            duration_seconds=round(time.monotonic() - started, 3),
            error=str(exc),
        )
        raise PipelineFailure(f"{name} could not start: {exc}", step=name) from exc
    step.update(
        status="passed" if return_code == 0 else "failed",
        finished_at=_now(),
        duration_seconds=round(time.monotonic() - started, 3),
        exit_code=return_code,
    )
    if return_code != 0:
        raise PipelineFailure(f"{name} failed with exit code {return_code}", step=name)


def _artifact(path: Path, *, role: str) -> dict[str, object]:
    if not path.is_file():
        raise PipelineFailure(f"expected artifact is missing: {path}", step="artifact-verification")
    return {
        "path": path.relative_to(REPOSITORY).as_posix(),
        "role": role,
        "size": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _desktop_artifacts(version: str) -> list[dict[str, object]]:
    current_path = REPOSITORY / "dist" / "desktop" / "current.json"
    try:
        current = json.loads(current_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineFailure(f"desktop current manifest is unreadable: {exc}", step="artifact-verification") from exc
    if current.get("version") != version or not isinstance(current.get("manifest"), str):
        raise PipelineFailure("desktop current manifest points at another version", step="artifact-verification")
    relative_manifest = Path(current["manifest"])
    if relative_manifest.is_absolute() or ".." in relative_manifest.parts:
        raise PipelineFailure("desktop current manifest path is unsafe", step="artifact-verification")
    manifest_path = REPOSITORY / "dist" / "desktop" / relative_manifest
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest().upper() != current.get("manifest_sha256"):
        raise PipelineFailure("desktop release manifest hash does not match current.json", step="artifact-verification")
    manifest = json.loads(manifest_bytes)
    artifacts = [_artifact(manifest_path, role="desktop-manifest")]
    for item in manifest.get("artifacts", []):
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise PipelineFailure("desktop release manifest contains an invalid artifact", step="artifact-verification")
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise PipelineFailure("desktop release manifest contains an unsafe path", step="artifact-verification")
        artifact = _artifact(manifest_path.parent / relative, role=str(item.get("role", "desktop")))
        if artifact["sha256"] != item.get("sha256") or artifact["size"] != item.get("size"):
            raise PipelineFailure(f"desktop artifact does not match its manifest: {relative}", step="artifact-verification")
        artifacts.append(artifact)
    return artifacts


def _android_artifacts(version: str) -> list[dict[str, object]]:
    mobile_root = REPOSITORY / "dist" / "mobile"
    current_path = mobile_root / "current.json"
    try:
        current = json.loads(current_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineFailure(f"Android current manifest is unreadable: {exc}", step="artifact-verification") from exc
    if current.get("version") != version or not isinstance(current.get("manifest"), str):
        raise PipelineFailure("Android current manifest points at another version", step="artifact-verification")
    relative_manifest = Path(current["manifest"])
    if relative_manifest.is_absolute() or ".." in relative_manifest.parts:
        raise PipelineFailure("Android current manifest path is unsafe", step="artifact-verification")
    manifest_path = mobile_root / relative_manifest
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest().upper() != current.get("manifest_sha256"):
        raise PipelineFailure("Android release manifest hash does not match current.json", step="artifact-verification")
    manifest = json.loads(manifest_bytes)
    if manifest.get("version") != version:
        raise PipelineFailure("Android immutable manifest has the wrong version", step="artifact-verification")
    published = manifest.get("artifacts")
    if not isinstance(published, list) or len(published) != 1:
        raise PipelineFailure("Android immutable manifest has an invalid artifact list", step="artifact-verification")
    item = published[0]
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        raise PipelineFailure("Android immutable manifest has an invalid APK entry", step="artifact-verification")
    relative_apk = Path(item["path"])
    if relative_apk.is_absolute() or ".." in relative_apk.parts:
        raise PipelineFailure("Android immutable manifest has an unsafe APK path", step="artifact-verification")
    immutable_apk = _artifact(manifest_path.parent / relative_apk, role="android-debug-apk")
    if immutable_apk["sha256"] != item.get("sha256") or immutable_apk["size"] != item.get("size"):
        raise PipelineFailure("Android immutable APK does not match its manifest", step="artifact-verification")

    apk = REPOSITORY / "dist" / "mobile" / f"mesh-chat-{version}-android-arm64-debug.apk"
    checksum = apk.with_suffix(apk.suffix + ".sha256")
    artifact = _artifact(apk, role="android-debug-apk")
    try:
        recorded = checksum.read_text(encoding="ascii").split()[0].upper()
    except (OSError, IndexError) as exc:
        raise PipelineFailure(f"Android checksum is unreadable: {exc}", step="artifact-verification") from exc
    if recorded != artifact["sha256"]:
        raise PipelineFailure("Android APK checksum does not match", step="artifact-verification")
    if artifact["sha256"] != immutable_apk["sha256"]:
        raise PipelineFailure("Android convenience APK does not match the immutable release", step="artifact-verification")
    properties = REPOSITORY / "src-tauri" / "gen" / "android" / "app" / "tauri.properties"
    metadata = properties.read_text(encoding="utf-8")
    if f"tauri.android.versionName={version}" not in metadata:
        raise PipelineFailure("generated Android version does not match source metadata", step="artifact-verification")
    return [
        _artifact(manifest_path, role="android-manifest"),
        immutable_apk,
        _artifact(checksum, role="checksum"),
    ]


def _summary_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Mesh Chat {report['version']} delivery report",
        "",
        f"Status: **{report['status']}**",
        "",
        "| Step | Status | Seconds |",
        "| --- | --- | ---: |",
    ]
    for step in report["steps"]:
        lines.append(
            f"| {step['name']} | {step['status']} | {step.get('duration_seconds', 0)} |"
        )
    if report.get("failure"):
        lines.extend(["", f"Failure: `{report['failure']['message']}`"])
    lines.extend(["", "## Artifacts", ""])
    if report["artifacts"]:
        for artifact in report["artifacts"]:
            lines.append(f"- `{artifact['path']}` — `{artifact['sha256']}`")
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Promotion gates",
            "",
            f"- Automated build and tests: {report['gates']['automated']}",
            f"- Physical Windows/Android validation: {report['gates']['physical_device']}",
            f"- Production signing: {report['gates']['production_signing']}",
            "",
        ]
    )
    return "\n".join(lines)


def _write_report(report_path: Path, report: dict[str, Any]) -> None:
    _atomic_json(report_path, report)
    summary_path = report_path.with_name("summary.md")
    summary_path.write_text(_summary_markdown(report), encoding="utf-8", newline="\n")
    _atomic_json(REPOSITORY / "dist" / "reports" / "latest.json", report)


def command_check(args: argparse.Namespace) -> int:
    state = check_versions(REPOSITORY, expected=args.expected_version)
    environment, tools = build_environment()
    package_manager = json.loads((REPOSITORY / "package.json").read_text(encoding="utf-8"))[
        "packageManager"
    ]
    required_pnpm = package_manager.removeprefix("pnpm@")
    if tools["pnpm"] != required_pnpm:
        raise PipelineFailure(f"pnpm {required_pnpm} is required; found {tools['pnpm']}")
    if not (REPOSITORY / "node_modules").is_dir():
        raise PipelineFailure("node_modules is missing; run pnpm install --frozen-lockfile")
    value = {
        "status": "ready",
        "version": state.version,
        "android_version_code": state.android_version_code,
        "tools": tools,
        "source": _source_state(),
    }
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


def command_version(args: argparse.Namespace) -> int:
    state = set_version(args.version, REPOSITORY)
    print(
        json.dumps(
            {
                "status": "updated",
                "version": state.version,
                "android_version_code": state.android_version_code,
                "files": sorted(state.configured),
            },
            indent=2,
        )
    )
    return 0


def command_verify(args: argparse.Namespace) -> int:
    state = check_versions(REPOSITORY, expected=args.expected_version)
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    report_path = (
        args.report.resolve()
        if args.report
        else REPOSITORY / "dist" / "reports" / state.version / run_id / "report.json"
    )
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "product": "Mesh Chat",
        "version": state.version,
        "android_version_code": state.android_version_code,
        "platforms": ["verification"],
        "status": "running",
        "started_at": _now(),
        "source": _source_state(),
        "host": {"platform": sys.platform, "architecture": platform.machine()},
        "steps": [],
        "artifacts": [],
        "gates": {
            "automated": "running",
            "physical_device": "not-requested",
            "production_signing": "not-requested",
        },
        "requires_attention": False,
    }
    try:
        environment, tools = build_environment()
        report["tools"] = tools
        _run_step(
            report,
            name="tests",
            command=[str(_python()), str(REPOSITORY / "scripts" / "test.py")],
            environment=environment,
            logs=report_path.parent / "logs",
        )
        report["status"] = "passed"
        report["gates"]["automated"] = "passed"
    except (OSError, ValueError, VersionError, PipelineFailure, subprocess.SubprocessError) as exc:
        report["status"] = "failed"
        report["requires_attention"] = True
        report["gates"]["automated"] = "failed"
        report["failure"] = {
            "step": getattr(exc, "step", None),
            "type": type(exc).__name__,
            "message": str(exc),
        }
    finally:
        report["finished_at"] = _now()
        report["duration_seconds"] = round(
            sum(float(step.get("duration_seconds", 0)) for step in report["steps"]), 3
        )
        _write_report(report_path, report)
        print(f"\nVerification report: {report_path}")
    return 0 if report["status"] == "passed" else 1


def _platforms(value: str) -> list[str]:
    if value == "all":
        return ["desktop", "android"]
    return [value]


def command_build(args: argparse.Namespace) -> int:
    state = check_versions(REPOSITORY, expected=args.expected_version)
    selected = _platforms(args.platform)
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    report_path = (
        args.report.resolve()
        if args.report
        else REPOSITORY / "dist" / "reports" / state.version / run_id / "report.json"
    )
    logs = report_path.parent / "logs"
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "product": "Mesh Chat",
        "version": state.version,
        "android_version_code": state.android_version_code,
        "platforms": selected,
        "status": "running",
        "started_at": _now(),
        "source": _source_state(),
        "host": {
            "platform": sys.platform,
            "architecture": platform.machine(),
        },
        "steps": [],
        "artifacts": [],
        "gates": {
            "automated": "running",
            "physical_device": "pending",
            "production_signing": "pending",
        },
        "requires_attention": False,
    }
    try:
        environment, tools = build_environment()
        report["tools"] = tools
        if not (REPOSITORY / "node_modules").is_dir():
            raise PipelineFailure(
                "node_modules is missing; run pnpm install --frozen-lockfile",
                step="preflight",
            )
        required_pnpm = json.loads(
            (REPOSITORY / "package.json").read_text(encoding="utf-8")
        )["packageManager"].removeprefix("pnpm@")
        if tools["pnpm"] != required_pnpm:
            raise PipelineFailure(
                f"pnpm {required_pnpm} is required; found {tools['pnpm']}",
                step="preflight",
            )
        if "desktop" in selected and "rustc" not in tools:
            raise PipelineFailure("Rust is required for a desktop release", step="preflight")
        free_bytes = shutil.disk_usage(REPOSITORY).free
        report["free_disk_bytes_at_start"] = free_bytes
        if free_bytes < int(args.min_free_gb * 1024**3):
            raise PipelineFailure(
                f"only {free_bytes / 1024**3:.2f} GiB is free; {args.min_free_gb:.2f} GiB is required",
                step="preflight",
            )
        python = str(_python())
        if args.skip_tests:
            report["steps"].append(
                {
                    "name": "tests",
                    "status": "skipped",
                    "reason": "--skip-tests was explicitly supplied",
                    "duration_seconds": 0,
                }
            )
        else:
            _run_step(
                report,
                name="tests",
                command=[python, str(REPOSITORY / "scripts" / "test.py")],
                environment=environment,
                logs=logs,
            )
        if "desktop" in selected:
            command = [python, str(REPOSITORY / "scripts" / "build_desktop.py")]
            if args.force:
                command.append("--force-sidecar")
                environment["MESH_CHAT_FORCE_WEB_BUILD"] = "1"
            _run_step(
                report,
                name="desktop-build",
                command=command,
                environment=environment,
                logs=logs,
            )
            report["artifacts"].extend(_desktop_artifacts(state.version))
        if "android" in selected:
            android_environment = environment.copy()
            if args.force:
                android_environment["MESH_CHAT_FORCE_ANDROID_NATIVE"] = "1"
                android_environment["MESH_CHAT_FORCE_WEB_BUILD"] = "1"
            _run_step(
                report,
                name="android-build",
                command=[python, str(REPOSITORY / "scripts" / "build_android.py")],
                environment=android_environment,
                logs=logs,
            )
            report["artifacts"].extend(_android_artifacts(state.version))
        report["status"] = "passed"
        report["gates"]["automated"] = "passed"
    except (OSError, ValueError, VersionError, PipelineFailure, subprocess.SubprocessError) as exc:
        report["status"] = "failed"
        report["requires_attention"] = True
        report["gates"]["automated"] = "failed"
        report["failure"] = {
            "step": getattr(exc, "step", None),
            "type": type(exc).__name__,
            "message": str(exc),
        }
    finally:
        report["finished_at"] = _now()
        report["duration_seconds"] = round(
            sum(float(step.get("duration_seconds", 0)) for step in report["steps"]), 3
        )
        _write_report(report_path, report)
        print(f"\nDelivery report: {report_path}")
    return 0 if report["status"] == "passed" else 1


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="validate metadata and local tool prerequisites")
    check.add_argument("--expected-version", help="exact source or v-prefixed tag version")
    check.set_defaults(handler=command_check)

    version = commands.add_parser("version", help="atomically synchronize release metadata")
    version.add_argument("version", help="stable MAJOR.MINOR.PATCH version")
    version.set_defaults(handler=command_version)

    verify = commands.add_parser("verify", help="run all maintained checks and write one report")
    verify.add_argument("--expected-version", help="exact source or v-prefixed tag version")
    verify.add_argument("--report", type=Path, help="explicit JSON report path")
    verify.set_defaults(handler=command_verify)

    build = commands.add_parser("build", help="test, build, verify, and report a delivery candidate")
    build.add_argument(
        "--platform",
        choices=("desktop", "android", "all"),
        default="all",
        help="artifact set to build (default: all)",
    )
    build.add_argument("--expected-version", help="fail unless source metadata matches this version or tag")
    build.add_argument("--skip-tests", action="store_true", help="skip tests already passed for this exact source")
    build.add_argument("--force", action="store_true", help="discard reusable build-stage caches")
    build.add_argument("--min-free-gb", type=float, default=1.5, help="minimum free disk before native builds")
    build.add_argument("--report", type=Path, help="explicit JSON report path")
    build.set_defaults(handler=command_build)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return args.handler(args)
    except (OSError, ValueError, VersionError, PipelineFailure, subprocess.SubprocessError) as exc:
        print(f"release pipeline failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
