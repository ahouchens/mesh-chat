"""Bounded local control framing is distinct from product traffic evidence."""

from io import BytesIO
import json
import copy
import os
from pathlib import Path
import socket
import struct
import sys
import threading
import queue
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_peers as peers
from native_interop_diagnostics import PREFLIGHT_FAILURE_SITES, ROOT_FAILURE_REASONS, PreflightDiagnostics


@pytest.mark.parametrize("role", ["windows", "android"])
def test_private_path_framing_threads_exact_invocation_challenge(role, monkeypatch):
    request = "c" * 32
    result = {"sample_request": request}
    if role == "windows":
        peer, streams, _ = windows_fixture(monkeypatch)
        peer._responses = queue.Queue()
        peer._responses.put({"id": "qualification:1", "ok": True, "result": result})
        assert peer.path("logical", "physical", request) == result
        frame = peers.receive(BytesIO(streams[0].getvalue()).read)
        assert frame == {"v": 1, "id": "qualification:1", "command": "qualification.path_evidence",
            "payload": {"logical_session": "logical", "expected_physical": "physical", "sample_request": request}}
    else:
        peer = peers.AndroidPeer(b"k" * 32)
        frames = []
        class Socket:
            def settimeout(self, value): assert 0 < value <= 60
            def sendall(self, value): frames.append(peers.receive(BytesIO(value).read))
            def recv(self, count): return response.read(count)
        response = BytesIO(peers.encode({"id": "qualification:1", "ok": True, "result": result}))
        peer.socket = Socket()
        assert peer.path("logical", "physical", request) == result
        assert frames == [{"id": "qualification:1", "action": "inspect", "payload": {
            "command": "qualification.path_evidence", "payload": {
                "logical_session": "logical", "expected_physical": "physical", "sample_request": request}}}]


class SampleRequest(str): pass


RETIREMENT = {"operation_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", "request_id": "d" * 32,
    "logical_session": "PRIVATE_LOGICAL", "expected_physical": "PRIVATE_PHYSICAL",
    "expected_service_incarnation": "b" * 32, "expected_adapter_epoch": "a" * 32}


@pytest.mark.parametrize("role", ["windows", "android"])
def test_private_retirement_and_correlated_inventory_use_exact_existing_frames(role, monkeypatch):
    responses = [{}, {"request_id": RETIREMENT["request_id"], "state": "prepared"},
                 {"request_id": RETIREMENT["request_id"], "state": "pending"},
                 {"carrier_retirement": {"request_id": RETIREMENT["request_id"], "state": "acknowledged"}}]
    frames = []
    if role == "windows":
        peer, streams, _ = windows_fixture(monkeypatch)
        for index, result in enumerate(responses, 1):
            peer._responses.put({"id": f"qualification:{index}", "ok": True, "result": result})
    else:
        peer = peers.AndroidPeer(b"k" * 32)
        response = BytesIO(b"".join(peers.encode({"id": f"qualification:{index}", "ok": True, "result": result})
                                  for index, result in enumerate(responses, 1)))
        class Socket:
            def settimeout(self, value): assert 0 < value <= 60
            def sendall(self, value): frames.append(peers.receive(BytesIO(value).read))
            def recv(self, count): return response.read(count)
        peer.socket = Socket()
    assert peer.inventory() == responses[0]
    assert peer.retire_carrier(**RETIREMENT, action="prepare") == responses[1]
    assert peer.retire_carrier(**RETIREMENT, action="commit") == responses[2]
    correlation = {key: RETIREMENT[key] for key in ("operation_id", "request_id")}
    assert peer.inventory(**correlation) == responses[3]
    if role == "windows":
        encoded = BytesIO(streams[0].getvalue())
        while encoded.tell() < len(encoded.getvalue()): frames.append(peers.receive(encoded.read))
        assert frames == [{"v": 1, "id": f"qualification:{index}", "command": command, "payload": payload}
            for index, (command, payload) in enumerate((("qualification.inventory", {}),
                ("qualification.retire_carrier", {**RETIREMENT, "action": "prepare"}),
                ("qualification.retire_carrier", {**RETIREMENT, "action": "commit"}), ("qualification.inventory", correlation)), 1)]
    else:
        assert frames == [{"id": f"qualification:{index}", "action": "inspect", "payload": {"command": command, "payload": payload}}
            for index, (command, payload) in enumerate((("qualification.inventory", {}),
                ("qualification.retire_carrier", {**RETIREMENT, "action": "prepare"}),
                ("qualification.retire_carrier", {**RETIREMENT, "action": "commit"}), ("qualification.inventory", correlation)), 1)]


@pytest.mark.parametrize("role", ["windows", "android"])
@pytest.mark.parametrize("field,value", [
    pytest.param(field, value, id=label) for label, field, value in (
        ("operation-none", "operation_id", None), ("operation-shape", "operation_id", "PRIVATE_BAD_UUID"),
        ("operation-uppercase", "operation_id", RETIREMENT["operation_id"].upper()),
        ("nonce-none", "request_id", None), ("nonce-bool", "request_id", True),
        ("nonce-short", "request_id", "d" * 31), ("nonce-uppercase", "request_id", "D" * 32),
        ("nonce-subclass", "request_id", SampleRequest("d" * 32)),
        ("logical-empty", "logical_session", ""), ("logical-long", "logical_session", "x" * 129),
        ("logical-control", "logical_session", "PRIVATE\nID"), ("physical-type", "expected_physical", []),
        ("logical-unicode", "logical_session", "PRIVATE_\u00e9"), ("physical-space", "expected_physical", "PRIVATE ID"),
        ("physical-dot", "expected_physical", "PRIVATE.ID"), ("physical-del", "expected_physical", "PRIVATE\x7f"),
        ("service-uppercase", "expected_service_incarnation", "B" * 32),
        ("service-type", "expected_service_incarnation", True), ("adapter-short", "expected_adapter_epoch", "a" * 31),
    )
])
def test_invalid_retirement_target_is_rejected_before_private_io(role, field, value):
    peer = object.__new__(peers.WindowsPeer if role == "windows" else peers.AndroidPeer)
    calls = []
    peer.private = peer._request = lambda *args, **kwargs: calls.append(args)
    payload = copy.deepcopy(RETIREMENT)
    payload[field] = value
    with pytest.raises(peers.PeerFailure) as caught: peer.retire_carrier(**payload, action="prepare")
    assert caught.value.code == "invalid_carrier_retirement_request" and calls == []


@pytest.mark.parametrize("role", ["windows", "android"])
@pytest.mark.parametrize("correlation", [
    {"operation_id": RETIREMENT["operation_id"]}, {"request_id": RETIREMENT["request_id"]},
    {"operation_id": "PRIVATE_BAD_UUID", "request_id": RETIREMENT["request_id"]},
    {"operation_id": RETIREMENT["operation_id"], "request_id": "D" * 32},
])
def test_correlated_inventory_cannot_omit_or_substitute_request_identity(role, correlation):
    peer = object.__new__(peers.WindowsPeer if role == "windows" else peers.AndroidPeer)
    calls = []
    peer.private = peer._request = lambda *args, **kwargs: calls.append(args)
    with pytest.raises(peers.PeerFailure): peer.inventory(**correlation)
    assert calls == []


@pytest.mark.parametrize("role", ["windows", "android"])
@pytest.mark.parametrize("action", [None, "abort", "pending", "Prepare", True, 1, [], SampleRequest("prepare")])
def test_private_retirement_requires_exact_prepare_or_commit_before_io(role, action):
    peer = object.__new__(peers.WindowsPeer if role == "windows" else peers.AndroidPeer)
    calls = []
    peer.private = peer._request = lambda *args, **kwargs: calls.append(args)
    with pytest.raises(peers.PeerFailure): peer.retire_carrier(**RETIREMENT, action=action)
    assert calls == []


@pytest.mark.parametrize("role", ["windows", "android"])
def test_missing_retirement_action_cannot_silently_use_legacy_one_step(role):
    peer = object.__new__(peers.WindowsPeer if role == "windows" else peers.AndroidPeer)
    calls = []
    peer.private = peer._request = lambda *args, **kwargs: calls.append(args)
    with pytest.raises(peers.PeerFailure): peer.retire_carrier(**RETIREMENT)
    assert calls == []


def test_retirement_identifier_accepts_exact_existing_ascii_bound():
    target = {**RETIREMENT, "logical_session": "A" * 126 + "_-", "expected_physical": "9" * 128}
    assert peers.retirement_payload(**target, action="prepare") == {**target, "action": "prepare"}


@pytest.mark.parametrize("role", ["windows", "android"])
@pytest.mark.parametrize("sample_request", [None, [], {}, True, b"c" * 32, "c" * 31, "c" * 33,
    "C" * 32, "g" * 32, SampleRequest("c" * 32)])
def test_bad_sample_request_is_refused_before_any_private_exchange(role, sample_request):
    peer = object.__new__(peers.WindowsPeer if role == "windows" else peers.AndroidPeer)
    calls = []
    peer.private = peer._request = lambda *args, **kwargs: calls.append(args)
    with pytest.raises(peers.PeerFailure) as failure: peer.path("logical", "physical", sample_request)
    assert failure.value.code == "invalid_sample_request" and calls == []
    with pytest.raises(TypeError): peer.path("logical", "physical")


ANDROID_START_SITES = (
    "android_devices", "android_avd_create", "android_root", "android_wait_for_device",
    "android_root_identity", "android_host_apk_install", "android_test_apk_install", "android_notification_grant",
)
ANDROID_ENVIRONMENT_SITES = ("android_device_state", "android_emulator_property", "android_abi")


def scripted_android(monkeypatch, tmp_path, *, fault=None, boot_failures=0,
                     failure_status=1, failure_stderr=b"PRIVATE_STDERR"):
    """Actual emulator owner with scripted OS boundaries; never starts a process."""
    import native_interop_preflight as preflight
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("ANDROID_SDK_ROOT", str(tmp_path / "PRIVATE_SDK"))
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("ANDROID_AVD_HOME", "PRIVATE_PREVIOUS_AVD_HOME")
    monkeypatch.setenv("ANDROID_SERIAL", "PRIVATE_PREVIOUS_SERIAL")
    def forbidden(*args, **kwargs):
        pytest.fail("Unexpected OS boundary")
    fake_os = SimpleNamespace(environ=os.environ, R_OK=os.R_OK, W_OK=os.W_OK,
        access=lambda path, mode: path == "/dev/kvm" and mode == os.R_OK | os.W_OK, killpg=forbidden)
    monkeypatch.setattr(peers, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(peers, "os", fake_os)
    monkeypatch.setattr(preflight, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(preflight, "os", fake_os)
    monkeypatch.setattr(peers.shutil, "which", lambda name: "PRIVATE_AVDMANAGER" if name == "avdmanager" else forbidden())
    emulator = peers.AndroidEmulator()
    apks = (Path("PRIVATE_HOST.apk"), Path("PRIVATE_TEST.apk"))
    adb = [str(emulator.sdk / "platform-tools/adb")]
    own_adb = [*adb, "-s", emulator.serial]
    shell = [*own_adb, "shell"]
    byte_options = {"stderr": peers.subprocess.DEVNULL, "timeout": 30}
    text_options = {"text": True, "stderr": peers.subprocess.DEVNULL, "timeout": 15}
    commands = {
        "android_devices": ("check_output", [*adb, "devices"], text_options, "List of devices attached\n"),
        "android_avd_create": ("run", ["PRIVATE_AVDMANAGER", "create", "avd", "--name", emulator.name,
            "--package", emulator.IMAGE], {"input": b"no\n", "check": True, "capture_output": True, "timeout": 120}, None),
        "android_root": ("check_output", [*own_adb, "root"], {**byte_options, "stderr": peers.subprocess.PIPE}, b"restarting adbd as root\n"),
        "android_wait_for_device": ("check_output", [*own_adb, "wait-for-device"], byte_options, b""),
        "android_root_identity": ("check_output", [*shell, "id", "-u"], byte_options, b"0\n"),
        "android_host_apk_install": ("check_output", [*own_adb, "install", "-r", str(apks[0])],
            {**byte_options, "timeout": 120}, b"Success\n"),
        "android_test_apk_install": ("check_output", [*own_adb, "install", "-r", str(apks[1])],
            {**byte_options, "timeout": 120}, b"Success\n"),
        "android_notification_grant": ("check_output", [*shell, "pm", "grant", peers.AndroidPeer.APP,
            "android.permission.POST_NOTIFICATIONS"], byte_options, b""),
        "android_device_state": ("check_output", ["adb", "get-state"], text_options, "device\n"),
        "android_emulator_property": ("check_output", ["adb", "shell", "getprop", "ro.kernel.qemu"], text_options, "1\n"),
        "android_abi": ("check_output", ["adb", "shell", "getprop", "ro.product.cpu.abi"], text_options, "x86_64\n"),
        "boot": ("check_output", [*shell, "getprop", "sys.boot_completed"], {**byte_options, "timeout": 5}, b"1\n"),
        "kill": ("check_output", [*own_adb, "emu", "kill"], byte_options, b""),
    }
    state = SimpleNamespace(calls=[], exit=None, exit_on_launch=None, starts=0, waits=[], now=0, boot_attempts=0, failure=None, fault=fault,
        emulator=emulator, apks=apks, commands=commands)
    def command(kind, args, **kwargs):
        matches = [(site, options, result) for site, (expected_kind, argv, options, result) in commands.items()
                   if kind == expected_kind and args == argv]
        assert len(matches) == 1, (kind, args)
        site, options, result = matches[0]
        assert kwargs == options
        state.calls.append(site)
        if site == state.fault:
            error = peers.subprocess.CalledProcessError(failure_status, ["PRIVATE_COMMAND"],
                output=b"PRIVATE_OUTPUT", stderr=failure_stderr)
            error.preflight_failure_site = "android_abi"  # Caller data is never attribution.
            state.failure = error
            raise error
        if site == "boot":
            state.boot_attempts += 1
            if boot_failures is None or state.boot_attempts <= boot_failures:
                raise peers.subprocess.CalledProcessError(1, ["PRIVATE_BOOT"], stderr=b"PRIVATE_BOOT_ERROR")
        if site == "kill": state.exit = 0
        return result
    def wait(timeout):
        state.waits.append(timeout)
        assert state.exit == 0
        return state.exit
    def launch(args, **kwargs):
        assert args == [str(emulator.sdk / "emulator/emulator"), "-avd", emulator.name, "-port", "5554",
            "-no-window", "-gpu", "swiftshader_indirect", "-accel", "on", "-no-snapshot", "-noaudio",
            "-no-boot-anim", "-camera-back", "none", "-camera-front", "none"]
        assert kwargs == {"stdout": peers.subprocess.DEVNULL, "stderr": peers.subprocess.DEVNULL, "start_new_session": True}
        state.starts += 1
        state.exit = state.exit_on_launch
        return SimpleNamespace(poll=lambda: state.exit, wait=wait)
    def sleep(seconds):
        assert seconds == 1
        state.now += seconds
    monkeypatch.setattr(peers.subprocess, "check_output", lambda args, **kwargs: command("check_output", args, **kwargs))
    monkeypatch.setattr(peers.subprocess, "run", lambda args, **kwargs: command("run", args, **kwargs))
    monkeypatch.setattr(peers.subprocess, "Popen", launch)
    monkeypatch.setattr(peers, "time", SimpleNamespace(monotonic=lambda: state.now, sleep=sleep))
    return state


def assert_android_cleaned(script):
    assert not script.emulator.root.exists() and script.emulator.process is None
    assert os.environ["ANDROID_AVD_HOME"] == "PRIVATE_PREVIOUS_AVD_HOME"
    assert os.environ["ANDROID_SERIAL"] == "PRIVATE_PREVIOUS_SERIAL"
    assert script.waits == ([30] if script.starts else [])


@pytest.mark.parametrize("site", ANDROID_START_SITES)
def test_actual_android_start_attributes_exact_command_without_retry_and_cleans_up(monkeypatch, tmp_path, site):
    script = scripted_android(monkeypatch, tmp_path, fault=site)
    diagnostics = PreflightDiagnostics()
    with pytest.raises(peers.subprocess.CalledProcessError) as failure:
        script.emulator.start(script.apks, diagnostics=diagnostics)
    assert failure.value is script.failure
    assert diagnostics.failure_site(failure.value) == site
    assert diagnostics.failure_site(peers.subprocess.CalledProcessError(1, "PRIVATE_COMMAND")) is None
    expected = list(ANDROID_START_SITES[:ANDROID_START_SITES.index(site) + 1])
    if script.starts: expected.insert(2, "boot")
    if script.starts: expected.append("kill")
    assert script.calls == expected
    script.emulator.close()  # Inventory failure is outside start's original cleanup scope.
    assert_android_cleaned(script)


@pytest.mark.parametrize("boot_failures", [1, None])
def test_boot_poll_failure_still_retries_only_within_original_deadline_without_attribution(monkeypatch, tmp_path, boot_failures):
    script = scripted_android(monkeypatch, tmp_path, boot_failures=boot_failures)
    diagnostics = PreflightDiagnostics()
    if boot_failures is None:
        with pytest.raises(peers.PeerFailure, match="emulator_boot_deadline") as failure:
            script.emulator.start(script.apks, diagnostics=diagnostics)
        assert diagnostics.failure_site(failure.value) is None
        assert script.boot_attempts == script.now == 600
        assert script.calls == [*ANDROID_START_SITES[:2], *(["boot"] * 600), "kill"]
    else:
        script.emulator.start(script.apks, diagnostics=diagnostics)
        assert script.boot_attempts == 2 and script.now == 1
        assert script.calls == [*ANDROID_START_SITES[:2], "boot", "boot", *ANDROID_START_SITES[2:]]
        script.emulator.close()
    assert_android_cleaned(script)


def test_preflight_observer_clears_success_and_rejects_untrusted_sites():
    assert PREFLIGHT_FAILURE_SITES == frozenset((*ANDROID_START_SITES, *ANDROID_ENVIRONMENT_SITES))
    diagnostics = PreflightDiagnostics()
    error = ValueError("PRIVATE_ERROR")
    with pytest.raises(ValueError):
        with diagnostics.scope("android_devices"):
            raise error
    assert diagnostics.failure_site(error) == "android_devices"
    with diagnostics.scope("android_abi"): pass
    assert diagnostics.failure_site(error) is None
    for invalid in ("PRIVATE_SITE", [], 1):
        with pytest.raises(ValueError, match="Unknown preflight"):
            with diagnostics.scope(invalid): pytest.fail("Invalid scope entered")


ROOT_DIAGNOSTICS = [
    pytest.param(b"adb: unable to connect for root: PRIVATE_SERIAL\n", "connect_failure", id="connect"),
    pytest.param(b"adb: error while reading for root: PRIVATE_PATH\n", "read_failure", id="read"),
    pytest.param(b"adb: unexpected output length for root\n", "unexpected_output_length", id="length"),
    pytest.param(b"timeout expired while waiting for device\n", "wait_for_device_timeout", id="wait-timeout"),
]


def observed_command_error(error, site="android_root"):
    diagnostics = PreflightDiagnostics()
    with pytest.raises(type(error)) as caught:
        with diagnostics.scope(site):
            raise error
    assert caught.value is error
    return diagnostics


@pytest.mark.parametrize("stderr,reason", ROOT_DIAGNOSTICS)
@pytest.mark.parametrize("text", [False, True])
def test_root_diagnostic_families_are_fixed_redacted_and_failure_only(stderr, reason, text):
    if text: stderr = stderr.decode("ascii")
    error = peers.subprocess.CalledProcessError(1, "PRIVATE_COMMAND", output=b"PRIVATE_OUTPUT", stderr=stderr)
    diagnostics = observed_command_error(error)
    observation = diagnostics.failure_observation(error)
    assert observation == {"preflight_exit_status": 1, "preflight_root_reason": reason}
    assert reason in ROOT_FAILURE_REASONS and "PRIVATE_" not in json.dumps(observation)
    assert diagnostics.failure_site(error) == "android_root"
    assert diagnostics.failure_observation(peers.subprocess.CalledProcessError(1, "PRIVATE_COMMAND")) == {}


@pytest.mark.parametrize("status", [-64, -1, 1, 255])
def test_checked_command_status_is_snapshotted_once_for_same_error(status):
    error = peers.subprocess.CalledProcessError(status, "PRIVATE_COMMAND",
        stderr=b"adb: unable to connect for root: PRIVATE_SUFFIX\n")
    diagnostics = observed_command_error(error)
    error.returncode = 0
    error.stderr = b"PRIVATE_CHANGED_STDERR"
    error.preflight_root_reason = "PRIVATE_FORGED_REASON"
    observation = diagnostics.failure_observation(error)
    assert observation == {"preflight_exit_status": status, "preflight_root_reason": "connect_failure"}
    observation["preflight_root_reason"] = "PRIVATE_MUTATION"
    assert diagnostics.failure_observation(error)["preflight_root_reason"] == "connect_failure"
    with diagnostics.scope("android_abi"): pass
    assert diagnostics.failure_observation(error) == {}


@pytest.mark.parametrize("stderr", [
    b"adb: unable to connect for root: device offline PRIVATE_SUFFIX\n",
    b"adb: unable to connect for root: device offline\nadb: unable to connect for root: closed\n",
    b"adb: unable to connect for root: device offline\nPRIVATE_EXTRA\n",
    b"adb: unable to connect for root: " + b"X" * 4096,
    b"adb: error while reading for root: device offline\n",
    "adb: unable to connect for root: \ud800",
])
def test_root_connect_detail_is_never_guessed_from_partial_or_conflicting_text(stderr):
    error = peers.subprocess.CalledProcessError(1, "PRIVATE_COMMAND", stderr=stderr)
    assert "preflight_root_connect_detail" not in observed_command_error(error).failure_observation(error)


def test_root_connect_detail_is_snapshotted_for_exact_error_and_site():
    error = peers.subprocess.CalledProcessError(1, "PRIVATE_COMMAND",
        stderr="adb: unable to connect for root: device offline\r\n")
    diagnostics = observed_command_error(error)
    error.stderr = b"PRIVATE_CHANGED"
    assert diagnostics.failure_observation(error).get("preflight_root_connect_detail") == "device_offline"
    assert diagnostics.failure_observation(peers.subprocess.CalledProcessError(1, "PRIVATE_COMMAND")) == {}
    error.stderr = b"adb: unable to connect for root: device offline\n"
    assert observed_command_error(error, "android_root_identity").failure_observation(error) == {"preflight_exit_status": 1}


class DiagnosticInt(int):
    pass


class DiagnosticBytes(bytes):
    pass


class DiagnosticString(str):
    pass


class UnreadableDiagnostic:
    def __str__(self): raise AssertionError("Must not coerce private diagnostics")
    def __len__(self): raise AssertionError("Must not inspect arbitrary diagnostics")
    def __int__(self): raise AssertionError("Must not coerce status")


@pytest.mark.parametrize("status", [
    pytest.param(value, id=label) for label, value in (
        ("zero", 0), ("below", -65), ("above", 256), ("true", True), ("false", False),
        ("float", 1.0), ("nan", float("nan")), ("inf", float("inf")), ("string", "1"),
        ("none", None), ("huge", 10 ** 1000), ("int-subclass", DiagnosticInt(1)),
        ("unreadable", UnreadableDiagnostic()),
    )
])
def test_invalid_command_status_is_omitted_without_coercion(status):
    error = peers.subprocess.CalledProcessError(status, "PRIVATE_COMMAND", stderr=b"PRIVATE_STDERR")
    assert observed_command_error(error).failure_observation(error) == {"preflight_root_reason": "unclassified"}


@pytest.mark.parametrize("stderr", [
    pytest.param(value, id=label) for label, value in (
        ("empty", b""), ("none", None), ("unknown", b"PRIVATE_STDERR"),
        ("unknown-line", b"adb: unable to connect for root: PRIVATE\nPRIVATE_OTHER\n"),
        ("conflict", b"adb: unable to connect for root: PRIVATE\nadb: error while reading for root: PRIVATE\n"),
        ("overlong", b"adb: unable to connect for root: " + b"X" * 4096),
        ("unicode-bytes-overlong", "adb: unable to connect for root: " + "\u00e9" * 2048),
        ("surrogate", "adb: unable to connect for root: \ud800"),
        ("bytes-subclass", DiagnosticBytes(b"adb: unable to connect for root: PRIVATE")),
        ("str-subclass", DiagnosticString("adb: unable to connect for root: PRIVATE")),
        ("wrong-command", b"adb: unable to connect for unroot: PRIVATE\n"),
        ("unanchored", b"PRIVATE adb: unable to connect for root: PRIVATE\n"),
        ("length-suffix", b"adb: unexpected output length for rootPRIVATE\n"),
        ("timeout-suffix", b"timeout expired while waiting for devicePRIVATE\n"),
        ("unreadable", UnreadableDiagnostic()),
    )
])
def test_unknown_oversized_conflicting_or_nonexact_stderr_is_unclassified(stderr):
    error = peers.subprocess.CalledProcessError(1, "PRIVATE_COMMAND", stderr=stderr,
        output=b"adb: unable to connect for root: PRIVATE_STDOUT")
    assert observed_command_error(error).failure_observation(error) == {
        "preflight_exit_status": 1, "preflight_root_reason": "unclassified"}


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("size,reason", [(4096, "connect_failure"), (4097, "unclassified")])
def test_root_stderr_byte_limit_is_inclusive_without_truncating_to_a_match(text, size, reason):
    prefix = b"adb: unable to connect for root: "
    stderr = prefix + b"X" * (size - len(prefix))
    if text: stderr = stderr.decode("ascii")
    error = peers.subprocess.CalledProcessError(255, "PRIVATE_COMMAND", stderr=stderr)
    assert observed_command_error(error).failure_observation(error)["preflight_root_reason"] == reason


@pytest.mark.parametrize("site", sorted(PREFLIGHT_FAILURE_SITES - {"android_root"}))
def test_root_reason_never_comes_from_other_command_stderr(site):
    error = peers.subprocess.CalledProcessError(1, "PRIVATE_COMMAND",
        stderr=b"adb: error while reading for root: PRIVATE_SUFFIX")
    assert observed_command_error(error, site).failure_observation(error) == {"preflight_exit_status": 1}


def test_nonstandard_exceptions_cannot_supply_command_diagnostics():
    class ForeignCommandError(peers.subprocess.CalledProcessError):
        @property
        def stderr(self): raise AssertionError("Must not read subclass properties")
        @stderr.setter
        def stderr(self, value): pass
    for error in (ForeignCommandError(1, "PRIVATE_COMMAND"), ValueError("PRIVATE_ERROR"),
                  peers.subprocess.TimeoutExpired("PRIVATE_COMMAND", 30)):
        error.returncode = 1
        error.preflight_root_reason = "connect_failure"
        assert observed_command_error(error).failure_observation(error) == {}
    assert ROOT_FAILURE_REASONS == frozenset({
        "connect_failure", "read_failure", "unexpected_output_length", "wait_for_device_timeout", "unclassified"})


@pytest.mark.parametrize("fault,code,expected", [
    ("unowned", "unowned_android_device_present", ["android_devices"]),
    ("avdmanager", "avdmanager_unavailable", ["android_devices"]),
    ("nonroot", "required_rootable_kernel_unavailable", [*ANDROID_START_SITES[:2], "boot", *ANDROID_START_SITES[2:5], "kill"]),
    ("exited", "emulator_exited_during_boot", [*ANDROID_START_SITES[:2]]),
])
def test_android_start_value_and_lifetime_guards_remain_fatal_and_unattributed(monkeypatch, tmp_path, fault, code, expected):
    script = scripted_android(monkeypatch, tmp_path)
    diagnostics = PreflightDiagnostics()
    if fault in {"unowned", "nonroot"}:
        site, result = ("android_devices", "List of devices attached\nPRIVATE_SERIAL\tdevice\n") if fault == "unowned" else ("android_root_identity", b"2000\n")
        script.commands[site] = (*script.commands[site][:3], result)
    if fault == "avdmanager": monkeypatch.setattr(peers.shutil, "which", lambda _: None)
    if fault == "exited": script.exit_on_launch = 1
    with pytest.raises(peers.PeerFailure) as failure:
        script.emulator.start(script.apks, diagnostics=diagnostics)
    assert failure.value.code == code and diagnostics.failure_site(failure.value) is None
    assert script.calls == expected
    script.emulator.close()
    assert not script.emulator.root.exists() and script.emulator.process is None
    assert os.environ["ANDROID_AVD_HOME"] == "PRIVATE_PREVIOUS_AVD_HOME"
    assert os.environ["ANDROID_SERIAL"] == "PRIVATE_PREVIOUS_SERIAL"


def test_real_socket_control_roundtrip_preserves_core_payload_and_correlation():
    controller, host = socket.socketpair()
    controller.settimeout(2)
    host.settimeout(2)
    peer = peers.AndroidPeer(b"k" * 32)
    peer.socket = controller
    requests = []
    def serve():
        request = peers.receive(host.recv)
        requests.append(request)
        host.sendall(peers.encode({"id": request["id"], "ok": True, "result": {"accepted": True}}))
    worker = threading.Thread(target=serve)
    worker.start()
    try:
        params = {"profile": "a" * 40, "recipient": "b" * 40, "kind": "text", "text": "controller fixture"}
        assert peer.core("message.enqueue", params, "caller-chosen-key-0001") == {"accepted": True}
        worker.join(2)
        assert not worker.is_alive()
        assert requests[0]["action"] == "core"
        assert requests[0]["payload"] == {"operation": "message.enqueue", "params": params, "idempotency_key": "caller-chosen-key-0001"}
    finally:
        controller.close()
        host.close()


def test_partial_stream_reads_do_not_change_framed_setup():
    frame = peers.encode({"id": "qualification:1", "ok": True, "result": {"public": True}})
    stream = BytesIO(frame)
    assert peers.receive(lambda count: stream.read(min(count, 1)))["result"] == {"public": True}


@pytest.mark.parametrize("frame", [b"", b"\x00", struct.pack(">I", 1) + b"x",
    struct.pack(">I", peers.MAX_FRAME + 1), struct.pack(">I", 2) + b"[1",
    struct.pack(">I", 2) + b"[]", struct.pack(">I", 2) + b"\xff\xff"])
def test_malformed_or_unbounded_local_frames_fail_without_raw_diagnostics(frame):
    with pytest.raises(peers.PeerFailure) as failure:
        peers.receive(BytesIO(frame).read)
    assert str(failure.value) in {"peer_closed", "peer_frame_budget", "invalid_peer_frame"}


@pytest.mark.parametrize("value", [None, [], {"id": "other", "ok": True}, {"id": "expected", "ok": 1},
    {"id": "expected", "ok": False, "error": {"code": "raw signed SDP secret"}}])
def test_response_identity_and_typed_errors_never_expose_raw_setup(value):
    with pytest.raises(peers.PeerFailure) as failure:
        peers.checked_reply(value, "expected")
    assert "secret" not in str(failure.value)


def test_product_process_never_inherits_artifact_or_repository_bearers():
    assert peers.child_environment({"GITHUB_TOKEN": "secret", "ACTIONS_RUNTIME_TOKEN": "secret",
        "INPUT_ROLE": "windows", "PATH": "public", "SYSTEMROOT": "C:/Windows"}) == {"PATH": "public", "SYSTEMROOT": "C:/Windows"}


def test_windows_peer_pipe_is_unique_and_accepted_by_the_actual_host_policy():
    from mesh_chat.core_api.pipe_policy import pipe_name
    first, second = peers.windows_pipe_name(), peers.windows_pipe_name()
    assert first != second
    assert pipe_name(first) == first and pipe_name(second) == second
    assert first.startswith(r"\\.\pipe\mesh-chat-native-qualification-")
    with pytest.raises(ValueError):
        pipe_name(r"\\.\pipe\mesh-native-qualification-" + "a" * 32)


@pytest.mark.parametrize("leaf", ["../existing", "absolute/path", "a" * 31, "g" * 32])
def test_android_controller_cannot_choose_arbitrary_existing_profile_paths(leaf):
    with pytest.raises(peers.PeerFailure, match="invalid_profile_leaf"):
        peers.AndroidPeer(b"k" * 32, directory_id=leaf)


def test_windows_crash_targets_the_exact_launched_pyinstaller_tree(monkeypatch):
    calls = []
    monkeypatch.setattr(peers.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    peers.WindowsPeer._kill_tree(type("OwnProcess", (), {"pid": 1234})())
    assert calls[0][0][0] == ["taskkill.exe", "/PID", "1234", "/T", "/F"]
    assert calls[0][1]["check"] and calls[0][1]["timeout"] == 15


def windows_fixture(monkeypatch):
    peer = object.__new__(peers.WindowsPeer)
    peer.clean_exits = peer.forced_exits = 0
    peer._sequence = 0
    peer._exchange_lock = threading.Lock()
    peer._pending_worker = None
    peer._poisoned = False
    peer._responses = queue.Queue()
    streams = [BytesIO() for _ in range(3)]
    state = {"exit": None, "kills": 0, "waits": 0, "client_closed": False}
    def kill(process):
        assert process is peer.process
        state.update(exit=-9, kills=state["kills"] + 1)
    def wait(timeout):
        state["waits"] += 1
        if state["exit"] is None:
            raise peers.subprocess.TimeoutExpired("owned-child", timeout)
        return state["exit"]
    peer.process = SimpleNamespace(stdin=streams[0], stdout=streams[1], stderr=streams[2],
                                   poll=lambda: state["exit"], wait=wait)
    peer.client = SimpleNamespace(close=lambda: state.update(client_closed=True))
    peer._reader = peer._stderr = SimpleNamespace(join=lambda timeout: None, is_alive=lambda: False)
    monkeypatch.setattr(peer, "_kill_tree", kill)
    return peer, streams, state


def test_windows_shutdown_failure_still_retires_owned_tree_and_every_stream(monkeypatch):
    peer, streams, state = windows_fixture(monkeypatch)
    def fail(*args): raise peers.PeerFailure("original_shutdown_error")
    monkeypatch.setattr(peer, "private", fail)
    with pytest.raises(peers.PeerFailure, match="original_shutdown_error"):
        peer.stop()
    assert state["kills"] == 1 and state["client_closed"]
    assert peer.process is peer.client is None
    assert all(stream.closed for stream in streams)
    assert peer.clean_exits == 0


def test_failed_kill_retains_exact_process_and_does_not_close_active_buffered_stream(monkeypatch):
    peer, streams, state = windows_fixture(monkeypatch)
    process = peer.process
    active = SimpleNamespace(join=lambda timeout: None, is_alive=lambda: True)
    peer._reader = active
    peer._poisoned = True
    def kill_failed(process): raise OSError("own process kill failed")
    monkeypatch.setattr(peer, "_kill_tree", kill_failed)
    with pytest.raises(peers.PeerFailure, match="peer_poisoned"):
        peer.stop()
    assert peer.process is process and peer._reader is active and peer._poisoned
    assert not any(stream.closed for stream in streams)
    assert not state["client_closed"] and peer.clean_exits == 0
    with pytest.raises(peers.PeerFailure, match="peer_already_started"):
        peer.start()
    # Exact retained ownership may retire later; cleanup then closes safely.
    state["exit"] = -9
    peer._reader = SimpleNamespace(join=lambda timeout: None, is_alive=lambda: False)
    with pytest.raises(peers.PeerFailure, match="peer_poisoned"):
        peer.stop()
    assert peer.process is None and all(stream.closed for stream in streams)


def test_overlapping_windows_exchange_is_rejected_before_another_host_write(monkeypatch):
    peer, _, _ = windows_fixture(monkeypatch)
    peer._exchange_lock.acquire()
    calls = []
    try:
        with pytest.raises(peers.PeerFailure, match="peer_exchange_in_progress"):
            peer._bounded(lambda: calls.append(True))
    finally:
        peer._exchange_lock.release()
    assert calls == []


def test_failed_kill_cleanup_returns_while_real_buffered_reader_remains_blocked(monkeypatch):
    peer, streams, state = windows_fixture(monkeypatch)
    process = peer.process
    read_fd, write_fd = os.pipe()
    reader_stream, writer_stream = os.fdopen(read_fd, "rb"), os.fdopen(write_fd, "wb", buffering=0)
    process.stdout = reader_stream
    entered = threading.Event()
    def read():
        entered.set()
        reader_stream.read(1)
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    assert entered.wait(1)
    join = reader.join
    monkeypatch.setattr(reader, "join", lambda timeout: join(min(timeout, 0.025)))
    peer._reader = reader
    peer._poisoned = True
    def denied(process): raise OSError("simulated own-child kill failure")
    monkeypatch.setattr(peer, "_kill_tree", denied)
    finished, errors = threading.Event(), []
    def cleanup():
        try: peer.stop()
        except peers.PeerFailure as error: errors.append(error.code)
        finally: finished.set()
    cleanup_worker = threading.Thread(target=cleanup, daemon=True)
    cleanup_worker.start()
    completed_without_unblocking_reader = finished.wait(1)
    try:
        assert completed_without_unblocking_reader
        assert peer.process is process and peer._poisoned
        assert not reader_stream.closed and reader.is_alive()
        assert errors == ["peer_poisoned"]
    finally:
        writer_stream.write(b"x")
        writer_stream.close()
        join(2)
        cleanup_worker.join(2)
        state["exit"] = -9
        try: peer.stop()
        except peers.PeerFailure: pass
        if not reader_stream.closed: reader_stream.close()


def test_windows_exit_timeout_kills_tree_and_never_counts_clean_exit(monkeypatch):
    peer, streams, state = windows_fixture(monkeypatch)
    monkeypatch.setattr(peer, "private", lambda *args: None)
    with pytest.raises(peers.PeerFailure, match="windows_shutdown_failed"):
        peer.stop()
    assert state["kills"] == 1 and state["waits"] == 2
    assert all(stream.closed for stream in streams) and peer.process is None
    assert peer.clean_exits == 0


@pytest.mark.parametrize("blocked", ["write", "core_read"])
def test_whole_windows_exchange_deadline_covers_blocked_write_or_core_read(monkeypatch, blocked):
    peer, _, state = windows_fixture(monkeypatch)
    peer.EXCHANGE_TIMEOUT = 0.025
    released = threading.Event()
    original_kill = peer._kill_tree
    def kill(process):
        original_kill(process)
        released.set()
    monkeypatch.setattr(peer, "_kill_tree", kill)
    def hang(*args, **kwargs):
        assert released.wait(2), "The bounded exchange must retire its exact host"
        raise OSError("raw private setup must never escape the timeout")
    if blocked == "write":
        peer.process.stdin = SimpleNamespace(write=hang)
        call = lambda: peer.private("qualification.inventory")
    else:
        peer.client.request = hang
        call = lambda: peer.core("application.snapshot")
    with pytest.raises(peers.PeerFailure, match="peer_deadline"):
        call()
    assert state["kills"] == 1 and not state["client_closed"]
    with pytest.raises(peers.PeerFailure, match="peer_poisoned"):
        peer._bounded(lambda: None)


def test_android_controller_is_explicitly_excluded_from_all_ordinary_required_suites():
    import android_qualification
    assert peers.AndroidPeer.TEST.rsplit(".", 1)[1] in android_qualification.CONTROLLER_ONLY_CLASSES
    for suite in ("webrtc", "signaling", "core_api", "core_consumer"):
        assert all(item["class"] != "PackagedNativeInteropBoundaryTest" for item in android_qualification.cases(suite))
    for name in ("test_android_webrtc.sh", "test_android_signaling.sh", "test_android_core_api.sh"):
        script = (peers.ROOT / "scripts" / name).read_text()
        assert "-e class" in script and "android_qualification.py list" in script


def test_packaged_drivers_do_not_construct_a_source_service_or_import_vault():
    source = Path(peers.__file__).read_text()
    assert "MeshChatService" not in source and "VaultStore" not in source
    assert '"--qualification-native-webrtc"' in source
    android = (peers.ROOT / "plugins/tauri-plugin-mesh-runtime/android/src/androidTest/java/com/meshchat/runtime/PackagedNativeInteropBoundaryTest.kt").read_text()
    assert 'qualification.callAttr("android_initialize"' in android
    assert "CoreApiBridge.typedCommand" in android
    assert "_start_network" not in android and 'store.put(' not in android


CORE_FAILURE_OBSERVATION = {"v": 1, "operation": "ice_servers", "stage": "tls_context",
    "category": "unexpected", "cause": "file_not_found"}


def test_actual_android_internal_reply_retains_only_same_failure_observation():
    peer = peers.AndroidPeer(b"k" * 32)
    response = BytesIO(peers.encode({"id": "qualification:1", "ok": False, "error": {"code": "internal"},
        "core_failure_observation": CORE_FAILURE_OBSERVATION}))
    class Socket:
        def settimeout(self, value): assert 0 < value <= 60
        def sendall(self, value): pass
        def recv(self, count): return response.read(count)
    peer.socket = Socket()
    with pytest.raises(peers.PeerFailure) as failure:
        peer.core("call.ice_servers")
    provider = getattr(peer, "core_failure_observation", lambda _: None)
    assert provider(failure.value) == CORE_FAILURE_OBSERVATION
    assert provider(peers.PeerFailure("internal")) is None


def observed_android_reply(peer, value):
    response = BytesIO(peers.encode(value))
    class Socket:
        def settimeout(self, timeout): assert 0 < timeout <= 60
        def sendall(self, data): assert peers.receive(BytesIO(data).read)["action"] == "core"
        def recv(self, count): return response.read(count)
    peer.socket = Socket()
    with pytest.raises(peers.PeerFailure) as failure:
        peer.core("call.ice_servers")
    return failure.value


@pytest.mark.parametrize("mutation", [
    {"core_failure_observation": {**CORE_FAILURE_OBSERVATION, "secret": "PRIVATE_CREDENTIAL"}},
    {"core_failure_observation": {**CORE_FAILURE_OBSERVATION, "cause": "PRIVATE_CREDENTIAL"}},
    {"core_failure_observation": {**CORE_FAILURE_OBSERVATION, "category": "response_encoding"}},
    {"core_failure_observation": {**CORE_FAILURE_OBSERVATION, "stage": "not_a_stage"}},
    {"error": {"code": "invalid_request"}},
    {"id": "unrelated"},
])
def test_actual_android_reply_rejects_unrelated_or_invalid_core_observation(mutation):
    peer = peers.AndroidPeer(b"k" * 32)
    reply = {"id": "qualification:1", "ok": False, "error": {"code": "internal"},
        "core_failure_observation": CORE_FAILURE_OBSERVATION, **mutation}
    error = observed_android_reply(peer, reply)
    assert peer.core_failure_observation(error) is None


def test_android_core_observation_is_cleared_by_next_actual_request():
    peer = peers.AndroidPeer(b"k" * 32)
    first = observed_android_reply(peer, {"id": "qualification:1", "ok": False,
        "error": {"code": "internal"}, "core_failure_observation": CORE_FAILURE_OBSERVATION})
    assert peer.core_failure_observation(first) == CORE_FAILURE_OBSERVATION
    response = BytesIO(peers.encode({"id": "qualification:2", "ok": True, "result": {}}))
    class Socket:
        def settimeout(self, timeout): assert 0 < timeout <= 60
        def sendall(self, data): assert peers.receive(BytesIO(data).read)["action"] == "inspect"
        def recv(self, count): return response.read(count)
    peer.socket = Socket()
    assert peer.inventory() == {}
    assert peer.core_failure_observation(first) is None


def test_nonmapping_android_reply_preserves_protocol_error():
    peer = peers.AndroidPeer(b"k" * 32)
    error = observed_android_reply(peer, ["PRIVATE_CREDENTIAL"])
    assert error.code == "invalid_peer_frame"
    assert peer.core_failure_observation(error) is None


def test_android_failure_only_network_inspect_uses_one_existing_frame_and_short_deadline():
    peer = peers.AndroidPeer(b"k" * 32)
    expected = {"v": 1, "scope": "post_failure_app_process", "internet_permission": True, "active_network": True,
        "internet_capability": True, "validated_network": False, "dns_servers_present": True,
        "process_bound_network": False, "connect_target": "broker"}
    response = BytesIO(peers.encode({"id": "qualification:1", "ok": True, "result": expected}))
    frames, timeouts = [], []
    class Socket:
        def settimeout(self, value): timeouts.append(value)
        def sendall(self, value): frames.append(peers.receive(BytesIO(value).read))
        def recv(self, count): return response.read(count)
    peer.socket = Socket()
    peer._qualification_binding = "a" * 64
    assert peer.network_diagnostic(timeout=2.0) == expected
    assert frames == [{"id": "qualification:1", "action": "inspect", "payload": {
        "command": "qualification.network_diagnostic", "payload": {"qualification_binding": "a" * 64}}}]
    assert timeouts and all(0 < value <= 2.0 for value in timeouts)


def test_android_network_inspect_cannot_increase_existing_exchange_deadline():
    peer = peers.AndroidPeer(b"k" * 32)
    class Socket:
        def settimeout(self, value): pytest.fail("Invalid budget must be rejected before socket use")
    peer.socket = Socket()
    peer._qualification_binding = "a" * 64
    with pytest.raises(peers.PeerFailure, match="peer_deadline"):
        peer.network_diagnostic(timeout=61)
