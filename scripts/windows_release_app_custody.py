"""Own an installed Windows app and its sidecar before either can run."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path
import subprocess
import time

import packaged_media_preflight as media
from packaged_call_windows_job import WindowsJob


CREATE_SUSPENDED = 0x00000004
CREATE_NO_WINDOW = 0x08000000
TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPTHREAD = 0x00000004
THREAD_SUSPEND_RESUME = 0x0002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


class THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG),
                ("dwFlags", wintypes.DWORD)]


def descendant_sidecars(rows, app_pid):
    """Find exact sidecar PIDs, including PyInstaller workers, by ancestry."""
    pending = [app_pid]
    found = set()
    visited = {app_pid}
    while pending:
        parent = pending.pop()
        for pid, parent_pid, name in rows:
            if parent_pid != parent or pid in visited:
                continue
            visited.add(pid)
            pending.append(pid)
            if name.lower() == "mesh-chat-service.exe":
                found.add(pid)
    return found


class ProcessApi:
    def __init__(self):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self.kernel.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        self.kernel.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
        self.kernel.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
        self.kernel.Thread32First.argtypes = [ctypes.c_void_p, ctypes.POINTER(THREADENTRY32)]
        self.kernel.Thread32Next.argtypes = [ctypes.c_void_p, ctypes.POINTER(THREADENTRY32)]
        self.kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenThread.restype = ctypes.c_void_p
        self.kernel.ResumeThread.argtypes = [ctypes.c_void_p]
        self.kernel.ResumeThread.restype = wintypes.DWORD
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = ctypes.c_void_p
        self.kernel.IsProcessInJob.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL)]
        self.kernel.IsProcessInJob.restype = wintypes.BOOL
        self.kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.kernel.CloseHandle.restype = wintypes.BOOL

    def _snapshot(self, kind):
        handle = self.kernel.CreateToolhelp32Snapshot(kind, 0)
        if not handle or handle == ctypes.c_void_p(-1).value:
            raise OSError("release_process_snapshot_failed")
        return handle

    def resume_initial_thread(self, pid):
        snapshot = self._snapshot(TH32CS_SNAPTHREAD)
        try:
            entry = THREADENTRY32()
            entry.dwSize = ctypes.sizeof(entry)
            threads = []
            if self.kernel.Thread32First(snapshot, ctypes.byref(entry)):
                while True:
                    if entry.th32OwnerProcessID == pid:
                        threads.append(entry.th32ThreadID)
                    if not self.kernel.Thread32Next(snapshot, ctypes.byref(entry)):
                        break
            if len(threads) != 1:
                raise OSError("release_initial_thread_ambiguous")
            thread = self.kernel.OpenThread(THREAD_SUSPEND_RESUME, False, threads[0])
            if not thread:
                raise OSError("release_initial_thread_unavailable")
            try:
                if self.kernel.ResumeThread(thread) != 1:
                    raise OSError("release_initial_thread_not_suspended_once")
            finally:
                self.kernel.CloseHandle(thread)
        finally:
            self.kernel.CloseHandle(snapshot)

    def process_rows(self):
        snapshot = self._snapshot(TH32CS_SNAPPROCESS)
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            rows = []
            if self.kernel.Process32FirstW(snapshot, ctypes.byref(entry)):
                while True:
                    rows.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID), str(entry.szExeFile)))
                    if not self.kernel.Process32NextW(snapshot, ctypes.byref(entry)):
                        break
            return rows
        finally:
            self.kernel.CloseHandle(snapshot)

    def hold_job_member(self, pid, job):
        handle = self.kernel.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            raise OSError("release_sidecar_handle_unavailable")
        member = wintypes.BOOL()
        if not self.kernel.IsProcessInJob(handle, job.handle, ctypes.byref(member)) or not member.value:
            self.kernel.CloseHandle(handle)
            raise OSError("release_sidecar_outside_job")
        return handle

    def exited(self, handle):
        state = self.kernel.WaitForSingleObject(handle, 0)
        if state not in {WAIT_OBJECT_0, WAIT_TIMEOUT}:
            raise OSError("release_process_wait_failed")
        return state == WAIT_OBJECT_0

    def close_handle(self, handle):
        self.kernel.CloseHandle(handle)


def cleanup_process_job(process, job):
    """Attempt both independent retirements even if closing a job raises."""
    outcome = {"job_released": job is None, "job_forced_close": False,
               "job_close_failed": False, "process_retired": False}
    if job is not None:
        try:
            outcome["job_released"], outcome["job_forced_close"] = job.close()
        except Exception:
            outcome["job_close_failed"] = True
    try:
        running = process.poll() is None
    except Exception:
        running = True
    if running:
        try: process.kill()
        except Exception: pass
    try:
        process.wait(timeout=5)
        outcome["process_retired"] = process.poll() is not None
    except Exception:
        pass
    return outcome


class OwnedApp:
    def __init__(self, process, job, api, port):
        self.process, self.job, self.api, self.port = process, job, api, port
        self.sidecars = []
        self.witnessed_pids = set()
        self.retired = False

    @classmethod
    def launch(cls, executable: Path, directory: Path, environment: dict, port: int,
               *, popen=subprocess.Popen, job_factory=WindowsJob, api_factory=ProcessApi):
        process = popen([str(executable)], cwd=directory, env=environment,
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, shell=False,
                        creationflags=CREATE_SUSPENDED | CREATE_NO_WINDOW)
        job = None
        try:
            job = job_factory()
            job.assign(process)
            api = api_factory()
            api.resume_initial_thread(process.pid)
            return cls(process, job, api, port)
        except BaseException as error:
            outcome = cleanup_process_job(process, job)
            try: error.release_cleanup = outcome
            except Exception: pass
            raise

    def witness_sidecar(self):
        pids = descendant_sidecars(self.api.process_rows(), self.process.pid)
        if not pids:
            raise ValueError("release_sidecar_not_observed")
        for pid in sorted(pids - self.witnessed_pids):
            self.sidecars.append(self.api.hold_job_member(pid, self.job))
            self.witnessed_pids.add(pid)
        return len(self.sidecars)

    def retire(self):
        """Require graceful app close, exact sidecar exits, job zero, and closed CDP."""
        clean = False
        try:
            graceful = self.process.poll() is None and media.request_app_window_close(self.process.pid)
            if graceful:
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    graceful = False
            until = time.monotonic() + 10
            while graceful and time.monotonic() < until:
                if (media.cdp_closed(self.port)
                        and all(self.api.exited(handle) for handle in self.sidecars)
                        and not descendant_sidecars(self.api.process_rows(), self.process.pid)):
                    break
                time.sleep(0.1)
            clean = (graceful and self.process.poll() is not None and self.sidecars
                     and all(self.api.exited(handle) for handle in self.sidecars)
                     and not descendant_sidecars(self.api.process_rows(), self.process.pid)
                     and self.job.wait_zero(10) and media.cdp_closed(self.port))
        finally:
            # Closing the kill-on-close job is mandatory even if a Windows API
            # observation raised. Forced termination never counts as evidence.
            outcome = cleanup_process_job(self.process, self.job)
            self.retired = bool(clean and outcome["job_released"]
                                and not outcome["job_forced_close"]
                                and not outcome["job_close_failed"]
                                and outcome["process_retired"])
            for handle in self.sidecars:
                try: self.api.close_handle(handle)
                except Exception: self.retired = False
            self.sidecars.clear()
        return self.retired


def install_with_job(command: str, executable: Path, *, timeout: int = 180,
                     popen=subprocess.Popen, job_factory=WindowsJob, api_factory=ProcessApi,
                     cleanup=None):
    """Use the R5 NSIS command while proving its entire child job has exited."""
    process = popen(command, executable=str(executable), cwd=executable.parent,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, shell=False,
                    creationflags=CREATE_SUSPENDED | CREATE_NO_WINDOW)
    job = None
    clean = False
    code = None
    try:
        job = job_factory()
        job.assign(process)
        api_factory().resume_initial_thread(process.pid)
        code = process.wait(timeout=timeout)
        clean = job.wait_zero(20)
    finally:
        outcome = cleanup_process_job(process, job)
        if cleanup is not None:
            cleanup.update(outcome)
        clean = bool(clean and outcome["job_released"]
                     and not outcome["job_forced_close"]
                     and not outcome["job_close_failed"]
                     and outcome["process_retired"])
    return code, clean
