from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

SAM_HOST = "127.0.0.1"
SAM_PORT = 7656

_CONFIG = """\
ipv4 = true
ipv6 = false
bandwidth = L
notransit = true
log = stdout
loglevel = warn

[ntcp2]
enabled = true

[ssu2]
enabled = true

[http]
enabled = false

[httpproxy]
enabled = false

[socksproxy]
enabled = false

[upnp]
enabled = false

[sam]
enabled = true
address = 127.0.0.1
port = 7656
"""


class I2PRouterManager:
    """Own an optional, local-only i2pd process for Mesh Chat.

    The router binds SAM to localhost, disables the web console and proxies,
    does not request router mappings, and runs with a low transit budget. It is
    never installed as a service and never requires administrator rights.
    """

    def __init__(self, profile_dir: Path, *, binary: str | None = None) -> None:
        self.profile_dir = Path(profile_dir)
        self._binary = binary
        self._process: subprocess.Popen[bytes] | None = None
        self._log = None
        self._lock = threading.RLock()
        self._started = False
        self._reason: str | None = None
        self._data_dir = self.profile_dir / "i2p-router"
        self._config_path = self._data_dir / "i2pd.conf"
        self._log_path = self._data_dir / "i2pd.log"

    @property
    def running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    @staticmethod
    def supported() -> bool:
        return os.name == "nt"

    def binary_path(self) -> Path | None:
        if not self.supported():
            return None
        candidates: list[Path] = []
        if self._binary:
            candidates.append(Path(self._binary))
        env = os.environ.get("MESH_CHAT_I2PD_PATH")
        if env:
            candidates.append(Path(env))
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "i2pd.exe")
        candidates.extend(
            [
                Path(sys.executable).resolve().parent / "i2pd.exe",
                Path(sys.argv[0]).resolve().parent / "i2pd.exe",
                Path(__file__).resolve().parent / "i2pd.exe",
            ]
        )
        found = shutil.which("i2pd")
        if found:
            candidates.append(Path(found))
        for candidate in candidates:
            try:
                if candidate.is_file():
                    return candidate
            except OSError:
                continue
        return None

    @staticmethod
    def sam_available() -> bool:
        try:
            with socket.create_connection((SAM_HOST, SAM_PORT), timeout=0.35):
                return True
        except OSError:
            return False

    def start(self) -> dict[str, Any]:
        with self._lock:
            if not self.supported():
                self._reason = "unsupported_platform"
                return self.status()
            if self._process is not None and self._process.poll() is None:
                return self.status()
            if self.sam_available():
                self._started = True
                self._reason = None
                return self.status()
            binary = self.binary_path()
            if binary is None:
                self._reason = "router_missing"
                return self.status()
            self._data_dir.mkdir(parents=True, exist_ok=True)
            self._config_path.write_text(_CONFIG, encoding="utf-8", newline="\n")
            self._log = open(self._log_path, "ab", buffering=0)
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                self._process = subprocess.Popen(
                    [
                        str(binary),
                        "--conf", str(self._config_path),
                        "--datadir", str(self._data_dir),
                        "--log", "stdout",
                        "--loglevel", "warn",
                    ],
                    cwd=str(self._data_dir),
                    stdin=subprocess.DEVNULL,
                    stdout=self._log,
                    stderr=subprocess.STDOUT,
                    creationflags=creationflags,
                )
            except OSError:
                self._reason = "router_start_failed"
                self._close_log()
                return self.status()
            self._started = True
            for _ in range(80):
                if self._process.poll() is not None:
                    self._reason = "router_exited"
                    self._close_log()
                    return self.status()
                if self.sam_available():
                    self._reason = None
                    return self.status()
                time.sleep(0.25)
            self._reason = "sam_timeout"
            self._stop_process()
            return self.status()

    def stop(self) -> None:
        with self._lock:
            self._stop_process()
            self._started = False
            self._reason = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            external = self.sam_available() and not self.running
            if external:
                state = "external"
                reason = None
            elif self._process is not None and self._process.poll() is None:
                state = "running" if self.sam_available() else "starting"
                reason = None
            elif self._process is not None and self._process.poll() is not None:
                self._reason = self._reason or "router_exited"
                state = "failed"
                reason = self._reason
            elif self._reason:
                state = "failed"
                reason = self._reason
            elif self._started:
                state = "stopped"
                reason = None
            else:
                state = "not_started"
                reason = None
            return {
                "state": state,
                "available": bool(self.binary_path()) or external,
                "managed": self._process is not None and self._process.poll() is None,
                "sam_ready": self.sam_available(),
                "reason": reason,
            }

    def _stop_process(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            self._close_log()
            return
        try:
            process.terminate()
            process.wait(timeout=4)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
        self._close_log()

    def _close_log(self) -> None:
        log = self._log
        self._log = None
        if log is not None:
            try:
                log.close()
            except OSError:
                pass
