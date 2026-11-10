"""Failure-only, bounded attribution for controller and Android boundaries."""

from contextlib import contextmanager
from subprocess import CalledProcessError


NEGATIVE_CONTROL_REASONS = {
    "kernel_block": frozenset(),
    "kernel_current_process": frozenset({"process_changed"}),
    "kernel_current_socket": frozenset({"socket_changed"}),
    "kernel_block_install": frozenset(),
    "ready_publish": frozenset(),
    "ready_receive": frozenset({"not_acknowledged"}),
    "blocked_enqueue": frozenset({"not_accepted"}),
    "blocked_receipt": frozenset({"receipt_while_blocked"}),
    "checked_receive": frozenset({"not_acknowledged"}),
    "checked_publish": frozenset(),
    "kernel_unblock": frozenset(),
    "kernel_counter_read": frozenset(),
    "kernel_counter_parse": frozenset({"counter_unavailable"}),
    "kernel_restore_current": frozenset({"current_check_failed"}),
    "kernel_restore_delete": frozenset(),
    "dropped_count": frozenset({"no_dropped_packets"}),
    "restored_delivery": frozenset(),
    "recovered_inbound": frozenset(),
    "recovered_records": frozenset({"record_count"}),
    "final_observation": frozenset({"path_missing"}),
    "final_evidence": frozenset({"rtt_unavailable"}),
    "final_traffic": frozenset(),
    "fault_cleanup": frozenset({"cleanup_incomplete"}),
}


def negative_control_observation(value):
    if (type(value) is not dict or not {"scenario", "stage"} <= set(value)
            or set(value) - {"scenario", "stage", "reason"}
            or type(value["scenario"]) is not str or value["scenario"] not in {"turn_tcp", "turn_tls", "impaired"}
            or type(value["stage"]) is not str or value["stage"] not in NEGATIVE_CONTROL_REASONS):
        return {}
    if "reason" in value and (type(value["reason"]) is not str
            or value["reason"] not in NEGATIVE_CONTROL_REASONS[value["stage"]]):
        return {}
    return dict(value)


class NegativeControlDiagnostics:
    def __init__(self):
        self.reset()

    def reset(self, scenario=None):
        self._scenario, self._failure, self._disabled = scenario, None, False

    def observe(self, error, stage, reason=None):
        if self._disabled or (self._failure is not None and self._failure[0] is error):
            return
        value = {"scenario": self._scenario, "stage": stage}
        if reason is not None: value["reason"] = reason
        selected = negative_control_observation(value)
        self._failure = (error, selected) if selected else None

    def failure_observation(self, error):
        if self._disabled or self._failure is None or self._failure[0] is not error:
            return {}
        return negative_control_observation(self._failure[1])


def reset_negative_control(observer, scenario=None):
    try:
        observer.reset(scenario)
        return observer
    except Exception:
        return None


def negative_control_error(observer, stage, error, reason=None):
    try:
        observer.observe(error, stage, reason)
    except Exception:
        try:
            observer._failure, observer._disabled = None, True
        except Exception:
            pass
    return error


@contextmanager
def negative_control_stage(observer, stage):
    try:
        yield
    except Exception as error:
        negative_control_error(observer, stage, error)
        raise


RENDEZVOUS_REASONS = {
    "inventory_request": frozenset({"http_rejected", "response_empty", "response_oversized",
                                     "json_invalid", "read_failed", "transport_failed"}),
    "archive_request": frozenset({"http_rejected", "redirect_invalid", "response_empty", "response_oversized",
                                   "read_failed", "transport_failed"}),
    "blob_request": frozenset({"http_rejected", "response_empty", "response_oversized", "read_failed", "transport_failed"}),
    "inventory_check": frozenset({"inventory_invalid", "duplicate_identity", "missing_identity"}),
    "partner_wait": frozenset({"deadline_exhausted"}),
    "transport_state": frozenset({"closed"}),
}


def rendezvous_observation(value):
    required = {"rendezvous_stage", "rendezvous_reason"}
    if (type(value) is not dict or not required <= set(value)
            or set(value) - required - {"rendezvous_http_status"}):
        return {}
    stage, reason = value["rendezvous_stage"], value["rendezvous_reason"]
    if (type(stage) is not str or stage not in RENDEZVOUS_REASONS
            or type(reason) is not str or reason not in RENDEZVOUS_REASONS[stage]):
        return {}
    if "rendezvous_http_status" in value:
        status = value["rendezvous_http_status"]
        if type(status) is not int or not 100 <= status <= 599 or reason != "http_rejected":
            return {}
    return dict(value)


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
