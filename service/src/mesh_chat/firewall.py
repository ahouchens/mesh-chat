from __future__ import annotations

import base64
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from .connectivity import diagnostic_step

_PROFILE_NAMES = {"Public": "public", "Private": "private", "DomainAuthenticated": "domain"}


def _powershell(
    script: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    timeout: float = 8,
) -> subprocess.CompletedProcess[str]:
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return runner(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def active_windows_profiles(
    *, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
) -> list[str]:
    if platform.system().lower() != "windows":
        return []
    script = (
        "Get-NetConnectionProfile | Where-Object {"
        "$_.IPv4Connectivity -eq 'Internet' -or $_.IPv6Connectivity -eq 'Internet'} "
        "| Select-Object -ExpandProperty NetworkCategory"
    )
    try:
        completed = _powershell(script, runner=runner, timeout=4)
    except (OSError, subprocess.SubprocessError):
        return []
    profiles: list[str] = []
    for line in completed.stdout.splitlines() if completed.returncode == 0 else []:
        value = _PROFILE_NAMES.get(line.strip())
        if value and value not in profiles:
            profiles.append(value)
    return profiles


def firewall_diagnostic() -> dict[str, str]:
    if platform.system().lower() != "windows":
        return diagnostic_step(
            "firewall", "unsupported", "firewall_check_unsupported", "check_host_firewall"
        )
    if not active_windows_profiles():
        return diagnostic_step(
            "firewall", "blocked", "windows_firewall_blocked", "check_active_network_profile"
        )
    return diagnostic_step(
        "firewall", "available", "windows_firewall_permission_required",
        "configure_firewall_after_prepare",
    )


def install_temporary_windows_rule(
    session_id: str,
    port: int,
    state_dir: Path,
    *,
    executable: Path | None = None,
    parent_pid: int | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Install an exact temporary rule with one explicit UAC consent.

    The elevated helper remains only as a cleanup watchdog. It removes the rule
    when the session marker disappears or the sidecar process exits, so stopping
    hosting does not require a second elevation prompt.
    """

    if platform.system().lower() != "windows" or not re.fullmatch(r"[0-9a-f]{64}", session_id):
        return {"configured": False, "reason": "firewall_check_unsupported"}
    if isinstance(port, bool) or not 1 <= int(port) <= 65535:
        return {"configured": False, "reason": "windows_firewall_blocked"}
    profiles = active_windows_profiles(runner=runner)
    if not profiles:
        return {"configured": False, "reason": "windows_firewall_blocked"}
    state_dir.mkdir(parents=True, exist_ok=True)
    marker = (state_dir / f"{session_id}.active").resolve()
    ready = (state_dir / f"{session_id}.ready").resolve()
    marker.write_text("active", encoding="ascii")
    try:
        ready.unlink(missing_ok=True)
    except OSError:
        pass
    rule_name = f"Mesh Chat temporary invitation {session_id[:12]}"
    executable_path = (executable or Path(sys.executable)).resolve()
    owner_pid = int(parent_pid or os.getpid())

    def ps(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    args = [
        "advfirewall", "firewall", "add", f"name={rule_name}", "dir=in", "action=allow",
        f"program={executable_path}", "protocol=TCP", f"localport={int(port)}",
        f"profile={','.join(profiles)}", "enable=yes",
    ]
    delete_args = ["advfirewall", "firewall", "delete", f"name={rule_name}"]
    helper = (
        f"$a=@({','.join(ps(item) for item in args)});"
        f"$d=@({','.join(ps(item) for item in delete_args)});"
        "$p=Start-Process -FilePath 'netsh.exe' -ArgumentList $a -Wait -PassThru -WindowStyle Hidden;"
        f"if($p.ExitCode -eq 0){{Set-Content -LiteralPath {ps(str(ready))} -Value 'ok' -Encoding ascii;"
        f"while((Test-Path -LiteralPath {ps(str(marker))}) -and "
        f"(Get-Process -Id {owner_pid} -ErrorAction SilentlyContinue)){{Start-Sleep -Seconds 1}};"
        "Start-Process -FilePath 'netsh.exe' -ArgumentList $d -Wait -WindowStyle Hidden}"
    )
    encoded_helper = base64.b64encode(helper.encode("utf-16-le")).decode("ascii")
    launcher = (
        "$p=Start-Process -FilePath 'powershell.exe' -Verb RunAs -PassThru "
        "-WindowStyle Hidden -ArgumentList @('-NoLogo','-NoProfile','-NonInteractive',"
        f"'-EncodedCommand',{ps(encoded_helper)}); if($null -eq $p){{exit 1}} else {{exit 0}}"
    )
    try:
        completed = _powershell(launcher, runner=runner, timeout=20)
        deadline = time.monotonic() + 3
        while completed.returncode == 0 and time.monotonic() < deadline and not ready.exists():
            time.sleep(0.05)
        configured = completed.returncode == 0 and ready.exists()
    except (OSError, subprocess.SubprocessError):
        configured = False
    if not configured:
        try:
            marker.unlink(missing_ok=True)
        except OSError:
            pass
        return {"configured": False, "reason": "windows_firewall_permission_required"}
    return {
        "configured": True,
        "rule_name": rule_name,
        "marker": str(marker),
        "ready": str(ready),
        "profiles": profiles,
    }


def remove_temporary_windows_rule(record: dict[str, Any]) -> None:
    try:
        Path(str(record["marker"])).unlink(missing_ok=True)
        Path(str(record.get("ready", ""))).unlink(missing_ok=True)
    except (KeyError, OSError, ValueError):
        return
