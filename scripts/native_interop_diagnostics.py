"""Failure-only, per-run attribution for checked Android preflight commands."""

from contextlib import contextmanager
from subprocess import CalledProcessError


PREFLIGHT_FAILURE_SITES = frozenset({
    "android_devices", "android_avd_create", "android_root", "android_wait_for_device",
    "android_root_identity", "android_host_apk_install", "android_test_apk_install",
    "android_notification_grant", "android_device_state", "android_emulator_property", "android_abi",
})


ROOT_FAILURE_REASONS = frozenset({
    "connect_failure", "read_failure", "unexpected_output_length", "wait_for_device_timeout", "unclassified",
})


def root_failure_reason(stderr):
    # AOSP client/commandline.cpp adb_root/wait_for_device diagnostic families.
    # These identify text families, never a runner version or a proven cause.
    if type(stderr) not in (bytes, str) or len(stderr) > 4096:
        return "unclassified"
    if type(stderr) is str:
        try:
            stderr = stderr.encode("utf-8")
        except UnicodeEncodeError:
            return "unclassified"
    if len(stderr) > 4096:
        return "unclassified"
    reasons = set()
    for line in stderr.splitlines():
        if not line:
            continue
        if line.startswith(b"adb: unable to connect for root: "):
            reasons.add("connect_failure")
        elif line.startswith(b"adb: error while reading for root: "):
            reasons.add("read_failure")
        elif line == b"adb: unexpected output length for root":
            reasons.add("unexpected_output_length")
        elif line == b"timeout expired while waiting for device":
            reasons.add("wait_for_device_timeout")
        else:
            return "unclassified"
    return next(iter(reasons)) if len(reasons) == 1 else "unclassified"


def command_failure_observation(error, site):
    if type(error) is not CalledProcessError:
        return {}
    observation = {}
    status = error.returncode
    if type(status) is int and -64 <= status <= 255 and status != 0:
        observation["preflight_exit_status"] = status
    if site == "android_root":
        observation["preflight_root_reason"] = root_failure_reason(error.stderr)
    return observation


class PreflightDiagnostics:
    def __init__(self):
        self._failure = None

    @contextmanager
    def scope(self, site):
        if site is not None and (type(site) is not str or site not in PREFLIGHT_FAILURE_SITES):
            raise ValueError("Unknown preflight diagnostic site")
        self._failure = None
        try:
            yield
        except Exception as error:
            # Retain identity and a bounded safe snapshot, never raw command data.
            if site is not None:
                self._failure = error, site, command_failure_observation(error, site)
            raise
        else:
            self._failure = None

    def failure_site(self, error):
        observed = self._failure
        return observed[1] if observed is not None and observed[0] is error and observed[1] in PREFLIGHT_FAILURE_SITES else None

    def failure_observation(self, error):
        return dict(self._failure[2]) if self.failure_site(error) is not None else {}
