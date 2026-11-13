"""Failure-only, bounded attribution for controller and Android boundaries."""

from contextlib import contextmanager
import math
from subprocess import CalledProcessError


RECOVERY_STATES = frozenset({
    "waiting_for_keys", "queued", "sending", "stored_for_delivery",
    "received_by_endpoint", "delivered", "expired", "failed", "cancelled",
})
RECOVERY_PHASES = ("blocked_receipt", "restored_delivery")
RECOVERY_POLL_CAP = 512
RECOVERY_ELAPSED_MS_CAP = 120000


def recovery_delivery_observation(value):
    """Validate the fixed, identifier-free projection before it leaves RAM."""
    if type(value) is not dict or set(value) != {"scenario", *RECOVERY_PHASES}:
        return None
    if type(value["scenario"]) is not str or value["scenario"] not in {"turn_tcp", "turn_tls", "impaired"}:
        return None
    result = {"scenario": value["scenario"]}
    fields = {"polls", "polls_capped", "first_state", "last_state",
              "transitions", "transitions_capped", "first_elapsed_ms", "last_elapsed_ms",
              "first_transition_elapsed_ms", "last_transition_elapsed_ms", "elapsed_capped"}
    for phase in RECOVERY_PHASES:
        item = value[phase]
        if type(item) is not dict or set(item) != fields:
            return None
        polls, transitions = item["polls"], item["transitions"]
        if (type(polls) is not int or not 0 <= polls <= RECOVERY_POLL_CAP
                or type(transitions) is not int or not 0 <= transitions <= polls
                or type(item["polls_capped"]) is not bool
                or type(item["transitions_capped"]) is not bool
                or type(item["elapsed_capped"]) is not bool
                or (item["polls_capped"] and polls != RECOVERY_POLL_CAP)
                or (item["transitions_capped"] and (transitions != RECOVERY_POLL_CAP
                                                    or not item["polls_capped"]))
                or (not item["polls_capped"] and transitions > max(0, polls - 1))):
            return None
        first, last = item["first_state"], item["last_state"]
        first_ms, last_ms = item["first_elapsed_ms"], item["last_elapsed_ms"]
        first_transition = item["first_transition_elapsed_ms"]
        last_transition = item["last_transition_elapsed_ms"]
        if polls == 0:
            if (any(part is not None for part in (
                    first, last, first_ms, last_ms, first_transition, last_transition))
                    or transitions or item["elapsed_capped"]):
                return None
        elif (type(first) is not str or type(last) is not str
                or first not in RECOVERY_STATES or last not in RECOVERY_STATES
                or type(first_ms) is not int or type(last_ms) is not int
                or not 0 <= first_ms <= last_ms <= RECOVERY_ELAPSED_MS_CAP
                or (item["elapsed_capped"] and last_ms != RECOVERY_ELAPSED_MS_CAP)
                or (transitions == 0 and first != last)
                or (polls == 1 and (transitions != 0 or first != last or first_ms != last_ms))):
            return None
        if transitions == 0:
            if first_transition is not None or last_transition is not None:
                return None
        elif (type(first_transition) is not int or type(last_transition) is not int
              or not first_ms <= first_transition <= last_transition <= last_ms
              or (transitions == 1 and (first_transition != last_transition or first == last))):
            return None
        result[phase] = dict(item)
    return result


class RecoveryDeliveryDiagnostics:
    """Failure-only observations bound to one blocked public message handle."""

    def __init__(self, scenario, handle):
        if scenario not in {"turn_tcp", "turn_tls", "impaired"} or type(handle) is not str or not handle:
            raise ValueError("Invalid recovery diagnostic scope")
        self.scenario, self._handle = scenario, handle
        self._phase, self._started, self._last_now, self._failure = None, None, None, None
        self._disabled = False
        self._phases = {}

    def start(self, phase, now):
        if (self._disabled or phase not in RECOVERY_PHASES
                or type(now) not in (int, float) or not math.isfinite(now)):
            self._disabled = True
            return
        if phase == "restored_delivery" and self._phase != "blocked_receipt":
            self._disabled = True
            return
        self._phase, self._started, self._last_now = phase, now, None
        self._phases[phase] = {"polls": 0, "polls_capped": False,
            "first_state": None, "last_state": None, "transitions": 0,
            "transitions_capped": False, "first_elapsed_ms": None, "last_elapsed_ms": None,
            "first_transition_elapsed_ms": None, "last_transition_elapsed_ms": None,
            "elapsed_capped": False}

    def observe(self, handle, state, now):
        if self._disabled or handle != self._handle or self._phase not in RECOVERY_PHASES:
            return
        if (type(state) is not str or state not in RECOVERY_STATES
                or type(now) not in (int, float) or not math.isfinite(now)
                or now < self._started or (self._last_now is not None and now < self._last_now)):
            self._disabled = True
            return
        item = self._phases[self._phase]
        elapsed_raw = int((now - self._started) * 1000)
        elapsed = min(RECOVERY_ELAPSED_MS_CAP, elapsed_raw)
        item["elapsed_capped"] |= elapsed_raw > RECOVERY_ELAPSED_MS_CAP
        self._last_now = now
        if item["polls"] == 0:
            item["first_state"], item["first_elapsed_ms"] = state, elapsed
        elif item["last_state"] != state:
            if item["first_transition_elapsed_ms"] is None:
                item["first_transition_elapsed_ms"] = elapsed
            item["last_transition_elapsed_ms"] = elapsed
            if item["transitions"] < RECOVERY_POLL_CAP:
                item["transitions"] += 1
            else:
                item["transitions_capped"] = True
        if item["polls"] < RECOVERY_POLL_CAP:
            item["polls"] += 1
        else:
            item["polls_capped"] = True
        item["last_state"], item["last_elapsed_ms"] = state, elapsed

    def failed(self, error):
        if not self._disabled and self._phase == "restored_delivery":
            self._failure = error

    def failure_observation(self, error, scenario, handle):
        if (self._disabled or error is not self._failure
                or scenario != self.scenario or handle != self._handle):
            return None
        return recovery_delivery_observation({
            "scenario": self.scenario, **self._phases})


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

FINAL_PATH_MISSING_REASONS = frozenset({"no_resource", "pending_adoption", "pending_negotiation", "adopted_not_true",
    "attached_not_true", "messaging_ready_not_true", "nonselected", "mixed", "unavailable"})
FINAL_PATH_SKIP_REASONS = FINAL_PATH_MISSING_REASONS - {"mixed", "unavailable"}


def record_final_path_skip(reasons, reason):
    try:
        if type(reasons) is set and reason in FINAL_PATH_SKIP_REASONS and len(reasons) < 2:
            reasons.add(reason)
    except Exception:
        pass  # Optional explanation cannot change the observed path result.


def final_path_missing_reason(reasons):
    """Reduce at most two fixed skip labels; missing collection is unavailable."""
    if type(reasons) is not set or len(reasons) > 2 or not reasons <= FINAL_PATH_SKIP_REASONS:
        return "unavailable"
    if not reasons: return "unavailable"
    return next(iter(reasons)) if len(reasons) == 1 else "mixed"


def final_path_missing_observation(value):
    return value if type(value) is str and value in FINAL_PATH_MISSING_REASONS else None


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


def _root_failure_lines(stderr):
    if type(stderr) not in (bytes, str) or len(stderr) > 4096:
        return None
    if type(stderr) is str:
        try:
            stderr = stderr.encode("utf-8")
        except UnicodeEncodeError:
            return None
    if len(stderr) > 4096:
        return None
    return [line for line in stderr.splitlines() if line]


def root_failure_reason(stderr):
    # AOSP client/commandline.cpp adb_root/wait_for_device diagnostic families.
    # These identify text families, never a runner version or a proven cause.
    lines = _root_failure_lines(stderr)
    if lines is None:
        return "unclassified"
    reasons = set()
    for line in lines:
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


def root_connect_detail(stderr):
    """Recognize entire fixed ADB messages; never serialize a private suffix."""
    lines = _root_failure_lines(stderr)
    if lines is None or len(lines) != 1:
        return None
    prefix = b"adb: unable to connect for root: "
    labels = {
        b"device offline": "device_offline",
        b"device offline (no transport)": "no_transport",
        b"device offline (transport offline)": "transport_offline",
        b"device still connecting": "device_connecting",
        b"device still authorizing": "device_authorizing",
        b"closed": "connection_closed",
        b"failed to read transport id from server": "transport_id_read_failed",
    }
    return labels.get(lines[0][len(prefix):]) if lines[0].startswith(prefix) else None


def command_failure_observation(error, site):
    if type(error) is not CalledProcessError:
        return {}
    observation = {}
    status = error.returncode
    if type(status) is int and -64 <= status <= 255 and status != 0:
        observation["preflight_exit_status"] = status
    if site == "android_root":
        observation["preflight_root_reason"] = root_failure_reason(error.stderr)
        detail = root_connect_detail(error.stderr)
        if detail is not None:
            observation["preflight_root_connect_detail"] = detail
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
