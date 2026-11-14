"""Kill-on-close Windows Job custody for the peer Node process and Edge tree."""

import ctypes
import time


class BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32)]


class IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


class BasicAccounting(ctypes.Structure):
    _fields_ = [("TotalUserTime", ctypes.c_int64),
                ("TotalKernelTime", ctypes.c_int64),
                ("ThisPeriodTotalUserTime", ctypes.c_int64),
                ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                ("TotalPageFaultCount", ctypes.c_uint32),
                ("TotalProcesses", ctypes.c_uint32),
                ("ActiveProcesses", ctypes.c_uint32),
                ("TotalTerminatedProcesses", ctypes.c_uint32)]


class WindowsJob:
    def __init__(self):
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        api.CreateJobObjectW.restype = ctypes.c_void_p
        api.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                                ctypes.c_void_p, ctypes.c_uint32]
        api.SetInformationJobObject.restype = ctypes.c_bool
        api.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        api.AssignProcessToJobObject.restype = ctypes.c_bool
        api.QueryInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                                  ctypes.c_void_p, ctypes.c_uint32,
                                                  ctypes.c_void_p]
        api.QueryInformationJobObject.restype = ctypes.c_bool
        api.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        api.TerminateJobObject.restype = ctypes.c_bool
        api.CloseHandle.argtypes = [ctypes.c_void_p]
        api.CloseHandle.restype = ctypes.c_bool
        self.api = api
        self.handle = api.CreateJobObjectW(None, None)
        self.assigned = False
        self.released = False
        self.forced_close = False
        if not self.handle: raise OSError("call_job_create_failed")
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            api.CloseHandle(self.handle)
            self.handle = None
            raise OSError("call_job_limit_failed")

    def assign(self, process):
        if self.handle is None or self.assigned or process.poll() is not None:
            raise ValueError("call_job_assignment_invalid")
        if not self.api.AssignProcessToJobObject(self.handle, ctypes.c_void_p(int(process._handle))):
            raise OSError("call_job_assignment_failed")
        self.assigned = True

    def active(self):
        if self.handle is None: raise ValueError("call_job_closed")
        value = BasicAccounting()
        if not self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(value),
                                                  ctypes.sizeof(value), None):
            raise OSError("call_job_query_failed")
        return value.ActiveProcesses

    def terminate(self):
        if self.handle is None: return False
        if not self.api.TerminateJobObject(self.handle, 1): return False
        until = time.monotonic() + 5
        while time.monotonic() < until:
            if self.active() == 0: return True
            time.sleep(0.05)
        return self.active() == 0

    def wait_zero(self, seconds=5):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            if self.active() == 0: return True
            time.sleep(0.05)
        return self.active() == 0

    def close(self):
        if self.handle is None: return self.released, self.forced_close
        forced = not self.wait_zero()
        self.forced_close |= forced
        zero = self.terminate() if forced else True
        if not zero: return False, self.forced_close
        if not self.api.CloseHandle(self.handle): return False, self.forced_close
        self.handle = None
        self.released = True
        return True, self.forced_close
