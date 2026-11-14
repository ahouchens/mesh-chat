"""Controller clients for actual frozen Windows and own-UID Android hosts.

No service is constructed in this module. Runtime messages use the production
Core pipe/Binder path; inspector calls use the explicit qualification binding.
"""

import base64
import json
import os
from pathlib import Path
import queue
import re
import socket
import signal
import shutil
import struct
import subprocess
import sys
import threading
import time
from uuid import UUID, uuid4

from native_interop_diagnostics import PreflightDiagnostics
from native_interop_core_observation import core_failure_observation
from native_interop_carrier_observation import carrier_target
from native_interop_android_observation import (
    BYTE_CAP, READ_CAP, InstrumentationStatus, android_lifecycle_snapshot,
    android_transport_snapshot, process_observation, adb_stderr_category, stop_failure,
)

ROOT = Path(__file__).resolve().parents[1]
MAX_FRAME = 4 * 1024 * 1024
HEADER = struct.Struct(">I")
SAFE_ERROR = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


def _instrumentation_status():
    try: return InstrumentationStatus()
    except Exception: return None  # Optional evidence cannot prevent peer startup.


class PeerFailure(RuntimeError):
    def __init__(self, code="peer_unavailable"):
        self.code = code if isinstance(code, str) and SAFE_ERROR.fullmatch(code) else "peer_unavailable"
        super().__init__(self.code)


def checked_reply(value, identifier):
    if not isinstance(value, dict) or value.get("id") != identifier or type(value.get("ok")) is not bool:
        raise PeerFailure("invalid_peer_reply")
    if value["ok"] is not True:
        error = value.get("error")
        raise PeerFailure(error.get("code") if isinstance(error, dict) else None)
    return value.get("result")


def checked_sample_request(value):
    if type(value) is not str or re.fullmatch(r"[a-f0-9]{32}", value) is None:
        raise PeerFailure("invalid_sample_request")
    return value


def retirement_correlation(operation_id, request_id):
    if operation_id is None and request_id is None: return {}
    if (type(operation_id) is not str or len(operation_id) != 36
            or type(request_id) is not str or re.fullmatch(r"[a-f0-9]{32}", request_id) is None):
        raise PeerFailure("invalid_carrier_retirement_request")
    try: canonical = str(UUID(operation_id)) == operation_id
    except ValueError: canonical = False
    if not canonical: raise PeerFailure("invalid_carrier_retirement_request")
    return {"operation_id": operation_id, "request_id": request_id}


def inventory_payload(operation_id, request_id, carrier_observation):
    if carrier_observation is None:
        return retirement_correlation(operation_id, request_id)
    target = carrier_target(carrier_observation)
    if operation_id is not None or request_id is not None or target is None:
        raise PeerFailure("invalid_carrier_observation_request")
    return {"carrier_observation": target}


def retirement_payload(operation_id, request_id, logical_session, expected_physical,
                       expected_service_incarnation, expected_adapter_epoch, *, action=None):
    payload = retirement_correlation(operation_id, request_id)
    if (type(action) is not str or action not in {"prepare", "commit"}
            or not payload or any(type(value) is not str or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is None
                          for value in (logical_session, expected_physical))
            or any(type(value) is not str or re.fullmatch(r"[a-f0-9]{32}", value) is None
                   for value in (expected_service_incarnation, expected_adapter_epoch))):
        raise PeerFailure("invalid_carrier_retirement_request")
    return {"action": action, **payload, "logical_session": logical_session, "expected_physical": expected_physical,
            "expected_service_incarnation": expected_service_incarnation, "expected_adapter_epoch": expected_adapter_epoch}


def encode(value):
    raw = json.dumps(value, separators=(",", ":")).encode()
    if not 1 < len(raw) <= MAX_FRAME:
        raise PeerFailure("peer_frame_budget")
    return HEADER.pack(len(raw)) + raw


def receive(read, on_eof=None):
    received = reads = 0
    def exact(length, stage):
        nonlocal received, reads
        chunks = bytearray()
        while len(chunks) < length:
            reads += 1
            part = read(length - len(chunks))
            if not part:
                if on_eof is not None:
                    try: on_eof(stage, min(received, BYTE_CAP), received > BYTE_CAP,
                                min(reads, READ_CAP), reads > READ_CAP)
                    except Exception: pass  # Optional observation cannot replace peer_closed.
                raise PeerFailure("peer_closed")
            chunks.extend(part)
            received += len(part)
        return bytes(chunks)
    length, = HEADER.unpack(exact(4, "header"))
    if not 1 < length <= MAX_FRAME:
        raise PeerFailure("peer_frame_budget")
    try:
        value = json.loads(exact(length, "body"))
    except (UnicodeError, ValueError):
        raise PeerFailure("invalid_peer_frame") from None
    if not isinstance(value, dict):
        raise PeerFailure("invalid_peer_frame")
    return value


def child_environment(environment=os.environ):
    # Artifact/job bearers belong to the controller, never the product runtime.
    return {key: value for key, value in environment.items()
            if not key.startswith(("GITHUB_", "ACTIONS_", "INPUT_"))}


def windows_pipe_name():
    from mesh_chat.core_api.pipe_policy import pipe_name
    return pipe_name(r"\\.\pipe\mesh-chat-native-qualification-" + uuid4().hex)


class WindowsPeer:
    EXCHANGE_TIMEOUT = 60

    def __init__(self, binary, directory, key):
        if sys.platform != "win32" or len(key) != 32:
            raise PeerFailure("windows_required")
        self.binary, self.directory, self.key = Path(binary), Path(directory).resolve(), key
        self.process = self.client = None
        self.processes_started, self.clean_exits, self.forced_exits = 0, 0, 0
        self._sequence = 0
        self._exchange_lock = threading.Lock()
        self._pending_worker = None
        self._poisoned = False
        self._lifecycle_failure = None

    def start(self):
        if self.process is not None:
            raise PeerFailure("peer_already_started")
        from mesh_chat.core_api.pipe_client import connect
        from mesh_chat.core_api.client import CoreClient
        self._responses = queue.Queue(maxsize=32)
        pipe = windows_pipe_name()
        environment = {**child_environment(), "MESH_CHAT_CORE_API_PIPE": pipe,
                       "MESH_CHAT_CORE_API_CLIENT_IMAGE": str(Path(sys.executable).resolve())}
        self.process = subprocess.Popen([str(self.binary), "--qualification-native-webrtc"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
        self.processes_started += 1
        process, responses = self.process, self._responses
        def reader():
            try:
                while True:
                    value = receive(process.stdout.read)
                    if value.get("type") != "event":
                        responses.put(value, timeout=1)
            except Exception:
                try: responses.put_nowait(None)
                except queue.Full: pass
        def drain():
            while process.stderr.read(65536):
                pass  # Raw runtime diagnostics can contain signed setup material.
        self._reader = threading.Thread(target=reader, daemon=True)
        self._stderr = threading.Thread(target=drain, daemon=True)
        self._reader.start()
        self._stderr.start()
        try:
            self.private("initialize", {"profile_dir": str(self.directory),
                "vault_key": base64.b64encode(self.key).decode(), "parent_pid": os.getpid(),
                "display_name": "Mesh qualification"})
            try:
                connection = connect(pipe, timeout=15)
            except OSError:
                raise PeerFailure("windows_core_pipe_unavailable") from None
            self.client = CoreClient.open(connection.readline, connection.write, connection.close)
            return self.inventory()
        except Exception as start_error:
            try:
                from native_interop_windows_observation import exception_kind
                masked_kind = exception_kind(start_error)
            except Exception:
                masked_kind = "other"
            self.stop(crash=True, _origin="start_rollback",
                      _masked_start_kind=masked_kind)
            raise

    def private(self, command, payload=None):
        if self.process is None:
            raise PeerFailure("peer_not_started")
        self._sequence += 1
        identifier = f"qualification:{self._sequence}"
        process, responses = self.process, self._responses
        def exchange():
            process.stdin.write(encode({"v": 1, "id": identifier, "command": command, "payload": payload or {}}))
            process.stdin.flush()
            try:
                reply = responses.get(timeout=self.EXCHANGE_TIMEOUT)
            except queue.Empty:
                raise PeerFailure("peer_deadline") from None
            return checked_reply(reply, identifier)
        return self._bounded(exchange)

    def _bounded(self, action):
        """The whole OS write/read exchange has one deadline, including flush."""
        if self._poisoned:
            raise PeerFailure("peer_poisoned")
        if not self._exchange_lock.acquire(blocking=False):
            raise PeerFailure("peer_exchange_in_progress")
        result = queue.Queue(maxsize=1)
        def execute():
            try: result.put((True, action()))
            except Exception as error: result.put((False, error))
        worker = threading.Thread(target=execute, daemon=True)
        self._pending_worker = worker
        worker.start()
        try:
            try:
                success, value = result.get(timeout=self.EXCHANGE_TIMEOUT)
            except queue.Empty:
                self._poisoned = True
                process = self.process
                try:
                    if process is not None and process.poll() is None:
                        self._kill_tree(process)
                        process.wait(timeout=15)
                except Exception:
                    pass
                worker.join(5)
                raise PeerFailure("peer_deadline") from None
            worker.join(5)
            if not success:
                raise value
            return value
        finally:
            if not worker.is_alive():
                self._pending_worker = None
            self._exchange_lock.release()

    def core(self, operation, params=None, key=None):
        if self.client is None:
            raise PeerFailure("peer_not_started")
        client = self.client
        return self._bounded(lambda: client.request(operation, params or {}, idempotency_key=key))

    def inventory(self, *, operation_id=None, request_id=None, carrier_observation=None):
        payload = inventory_payload(operation_id, request_id, carrier_observation)
        return self.private("qualification.inventory", payload) if payload else self.private("qualification.inventory")

    def retire_carrier(self, operation_id, request_id, logical_session, expected_physical,
                       expected_service_incarnation, expected_adapter_epoch, *, action=None):
        return self.private("qualification.retire_carrier", retirement_payload(operation_id, request_id,
            logical_session, expected_physical, expected_service_incarnation, expected_adapter_epoch, action=action))

    def path(self, logical, physical, sample_request):
        return self.private("qualification.path_evidence", {"logical_session": logical, "expected_physical": physical,
            "sample_request": checked_sample_request(sample_request)})

    def pairing_begin(self, operation_id, role, *, pairing_code=None, direct=False):
        payload = {"operation_id": operation_id, "role": role, "allow_direct_ip_disclosure": direct}
        if pairing_code is not None: payload["pairing_code"] = pairing_code
        return self.private("qualification.pairing_begin", payload)

    def pairing_status(self, operation_id):
        return self.private("qualification.pairing_status", {"operation_id": operation_id})

    def pairing_cancel(self, operation_id):
        return self.private("qualification.pairing_cancel", {"operation_id": operation_id})

    def failure_lifecycle_observation(self, error):
        record = getattr(self, "_lifecycle_failure", None)
        return dict(record[1]) if (type(record) is tuple and len(record) == 2
                                  and record[0] is error) else None

    def stop(self, *, crash=False, _origin="other_stop", _masked_start_kind="none"):
        self._lifecycle_failure = None
        process = self.process
        if process is None:
            return
        failure, code = None, None
        stage = "poll"
        try:
            if crash:
                if process.poll() is None:
                    stage = "kill_tree"
                    self._kill_tree(process)
                    self.forced_exits += 1
            elif self._poisoned:
                stage = "shutdown"
                raise PeerFailure("peer_poisoned")
            else:
                stage = "shutdown"
                self.private("shutdown")
            stage = "wait"
            code = process.wait(timeout=30)
        except Exception as error:
            failure = error if isinstance(error, PeerFailure) else PeerFailure("windows_shutdown_failed")
            try:
                from native_interop_windows_observation import lifecycle_row
                self._lifecycle_failure = (failure, lifecycle_row(
                    _origin, stage, error, process, _masked_start_kind))
            except Exception:
                pass  # Optional attribution cannot replace the shutdown error.
        finally:
            cleanup_stage = "poll"
            try:
                if process.poll() is None:
                    cleanup_stage = "kill_tree"
                    self._kill_tree(process)
                    cleanup_stage = "wait"
                    process.wait(timeout=15)
            except Exception as error:
                if failure is None:
                    failure = PeerFailure("windows_retirement_failed")
                    try:
                        from native_interop_windows_observation import lifecycle_row
                        self._lifecycle_failure = (failure, lifecycle_row(
                            _origin, cleanup_stage, error, process, _masked_start_kind))
                    except Exception:
                        pass
            workers = [thread for thread in (self._pending_worker, self._reader, self._stderr) if thread is not None]
            for thread in workers:
                thread.join(5)
                if thread.is_alive() and failure is None:
                    failure = PeerFailure("windows_reader_not_retired")
            retired = process.poll() is not None and all(not thread.is_alive() for thread in workers)
            if retired:
                try:
                    if self.client is not None: self.client.close()
                except Exception:
                    retired = False
                    if failure is None: failure = PeerFailure("windows_client_not_closed")
            if retired:
                # Closing a buffered stream while its worker holds an I/O lock
                # can block forever. Only close after exact worker retirement.
                for stream in (process.stdin, process.stdout, process.stderr):
                    try: stream.close()
                    except Exception:
                        retired = False
                        if failure is None: failure = PeerFailure("windows_stream_not_closed")
            if retired:
                self.process = self.client = self._pending_worker = None
                self._poisoned = False
            else:
                # Keep the exact failed process/streams/workers for retryable
                # explicit cleanup. start() cannot compete with this owner.
                self._poisoned = True
                if failure is None: failure = PeerFailure("windows_retirement_failed")
        if failure is not None:
            raise failure
        if not crash:
            if code != 0:
                raise PeerFailure("unclean_windows_exit")
            self.clean_exits += 1

    @staticmethod
    def _kill_tree(process):
        # One-file PyInstaller has a bootloader parent and runtime child. Kill
        # this exact launched tree so a retained child cannot hold the vault.
        subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                       check=True, capture_output=True, timeout=15)


class AndroidPeer:
    APP = "com.meshchat.runtime.smoke"
    RUNNER = APP + ".test/androidx.test.runner.AndroidJUnitRunner"
    TEST = "com.meshchat.runtime.PackagedNativeInteropBoundaryTest"

    def __init__(self, key, *, adb="adb", directory_id=None):
        if len(key) != 32:
            raise PeerFailure("invalid_vault_key")
        self.key, self.adb = key, adb
        self.directory_id = directory_id or uuid4().hex
        if re.fullmatch(r"[a-f0-9]{32}", self.directory_id) is None:
            raise PeerFailure("invalid_profile_leaf")
        self.process = self.socket = None
        self.forward = None
        self._start_failure = None
        self._sequence = 0
        self._core_failure = None
        self._qualification_binding = None
        self._transport_failure = None
        self._lifecycle_failure = None
        self._instrumentation_status = _instrumentation_status()
        self.processes_started, self.clean_exits, self.forced_exits = 0, 0, 0

    def _adb(self, *args):
        try: site = self._adb_lifecycle_site(args)
        except Exception: site = None
        try:
            # communicate captures lifecycle stderr within the existing timeout.
            # The 4096-byte classification limit bounds inspected/retained data,
            # not subprocess's transient output buffer.
            return subprocess.check_output([self.adb, *args],
                stderr=subprocess.PIPE if site is not None else subprocess.DEVNULL, timeout=30).decode().strip()
        except subprocess.CalledProcessError as error:
            if type(error) is subprocess.CalledProcessError:
                try:
                    if site is not None:
                        status = self._instrumentation_status.snapshot() if self._instrumentation_status is not None else None
                        code = error.returncode
                        observed = android_lifecycle_snapshot({
                            "v": 1, "site": site,
                            "exit_status": code if type(code) is int and -64 <= code <= 255 and code != 0 else None,
                            "instrumentation_process": process_observation(self.process),
                            "instrumentation": status,
                            "stderr_category": adb_stderr_category(error.stderr, args),
                        })
                        if observed is not None:
                            self._lifecycle_failure = (error, observed)
                except Exception:
                    pass  # Optional attribution cannot replace the exact ADB failure.
            raise

    @staticmethod
    def _adb_lifecycle_site(args):
        if args == ("shell", "am", "force-stop", AndroidPeer.APP):
            return "force_stop"
        if (len(args) == 3 and args[:2] == ("forward", "tcp:0")
                and type(args[2]) is str and re.fullmatch(r"tcp:[0-9]{1,5}", args[2])):
            return "forward_add"
        if (len(args) == 3 and args[:2] == ("forward", "--remove")
                and type(args[2]) is str and re.fullmatch(r"tcp:[0-9]{1,5}", args[2])):
            return "forward_remove"
        return None

    def start(self):
        if self.process is not None:
            raise PeerFailure("peer_already_started")
        self._lifecycle_failure = None
        self._start_failure = None
        self._qualification_binding = None
        self._transport_failure = None
        self._instrumentation_status = _instrumentation_status()
        self._observe_system_phase("peer_start")
        nonce = os.urandom(32).hex()
        self.process = subprocess.Popen([self.adb, "shell", "am", "instrument", "-w", "-r",
            "-e", "class", self.TEST, "-e", "mesh_interop_nonce", nonce, self.RUNNER],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.processes_started += 1
        ports = queue.Queue(maxsize=2)
        process = self.process
        status = self._instrumentation_status
        def reader():
            try:
                while line := process.stdout.readline(8193):
                    if status is not None:
                        try: status.observe(line)
                        except Exception: pass  # Status observation cannot affect port admission.
                    if len(line) > 8192:
                        continue
                    match = re.fullmatch(rb"INSTRUMENTATION_STATUS: mesh_interop_port=([0-9]{1,5})\r?\n", line)
                    if match:
                        try: ports.put_nowait(int(match[1]))
                        except queue.Full: pass
            finally:
                if status is not None:
                    try: status.ended()
                    except Exception: pass
        self._reader = threading.Thread(target=reader, daemon=True)
        self._reader.start()
        stage = "port_wait"
        try:
            port = ports.get(timeout=90)
            stage = "port_validate"
            if not 1024 <= port <= 65535:
                raise PeerFailure("invalid_android_port")
            stage = "forward"
            self.forward = self._adb("forward", "tcp:0", f"tcp:{port}")
            stage = "forward_validate"
            if re.fullmatch(r"[0-9]{1,5}", self.forward) is None:
                raise PeerFailure("invalid_adb_forward")
            stage = "connect"
            self.socket = socket.create_connection(("127.0.0.1", int(self.forward)), timeout=60)
            stage = "authenticate"
            self._request("authenticate", {"nonce": nonce})
            stage = "initialize"
            self._observe_system_phase("peer_initialize")
            self._request("initialize", {"directory_id": self.directory_id, "vault_key": base64.b64encode(self.key).decode()})
            stage = "inventory"
            inventory = self.inventory()
            stage = "binding"
            self._qualification_binding = self._initial_binding(inventory)
            self._observe_system_phase("peer_runtime")
            return inventory
        except Exception as error:
            self._fail_start(stage, error)

    def _fail_start(self, stage, error):
        primary = PeerFailure("android_host_start_failed")
        observed = None
        try:
            from native_interop_android_start import start_observation
            observed = start_observation(stage, error, peer_failure=isinstance(error, PeerFailure),
                transport=self.failure_transport_observation(error),
                lifecycle=self.failure_lifecycle_observation(error))
        except Exception:
            pass  # Failure observation cannot prevent rollback.
        try:
            try: kind = stop_failure("finish", error)["exception_kind"]
            except Exception: kind = "other"
            self.stop(crash=True, _origin="start_rollback", _masked_start_kind=kind)
        except Exception as cleanup:
            if observed is not None:
                try:
                    from native_interop_android_start import exception_kind
                    observed["rollback_exception_kind"] = exception_kind(cleanup, peer_failure=isinstance(cleanup, PeerFailure))
                    lifecycle = self.failure_lifecycle_observation(cleanup)
                    if lifecycle is not None: observed["rollback_lifecycle"] = lifecycle
                except Exception:
                    pass
        try:
            from native_interop_android_start import start_failure_snapshot
            selected = start_failure_snapshot(observed)
            if selected is not None: self._start_failure = (primary, selected)
        except Exception:
            pass
        raise primary from None

    def failure_start_observation(self, error):
        try:
            from native_interop_android_start import start_failure_snapshot
            record = self._start_failure
            if type(record) is tuple and len(record) == 2 and record[0] is error:
                return start_failure_snapshot(record[1])
        except Exception:
            pass
        return None

    def _request(self, action, payload=None, *, timeout=60):
        self._core_failure = None
        self._transport_failure = None
        if self.socket is None:
            raise PeerFailure("peer_not_started")
        if type(timeout) not in {int, float} or not 0 < timeout <= 60:
            raise PeerFailure("peer_deadline")
        self._sequence += 1
        identifier = f"qualification:{self._sequence}"
        deadline = time.monotonic() + timeout
        self.socket.settimeout(timeout)
        eof = None
        def on_eof(stage, received_bytes, bytes_capped, read_calls, reads_capped):
            nonlocal eof
            eof = (stage, received_bytes, bytes_capped, read_calls, reads_capped)
        def read(count):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PeerFailure("peer_deadline")
            self.socket.settimeout(remaining)
            return self.socket.recv(count)
        try:
            self.socket.sendall(encode({"id": identifier, "action": action, "payload": payload or {}}))
            value = receive(read, on_eof=on_eof)
            try:
                return checked_reply(value, identifier)
            except PeerFailure as error:
                if (action == "core" and error.code == "internal" and type(value) is dict and value.get("id") == identifier
                        and value.get("ok") is False):
                    selected = core_failure_observation(value.get("core_failure_observation"))
                    if selected is not None: self._core_failure = error, selected
                raise
        except PeerFailure as error:
            if error.code == "peer_closed" and eof is not None:
                try:
                    operation = payload.get("operation") if action == "core" and type(payload) is dict else None
                    operation = operation if operation in {"application.snapshot", "message.query",
                        "message.enqueue", "runtime.capabilities"} else "other"
                    selected = android_transport_snapshot({
                        "v": 1, "action": action if action in {"authenticate", "initialize", "core", "inspect", "finish"} else "other",
                        "operation": operation if action == "core" else None,
                        "eof_stage": eof[0], "received_bytes": eof[1], "received_bytes_capped": eof[2],
                        "read_calls": eof[3], "read_calls_capped": eof[4],
                        "process": process_observation(self.process),
                        "instrumentation": self._instrumentation_status.snapshot(),
                    })
                    if selected is not None:
                        self._transport_failure = (error, identifier, selected)
                except Exception:
                    self._transport_failure = None
            raise
        except TimeoutError:
            raise PeerFailure("peer_deadline") from None

    def core(self, operation, params=None, key=None):
        return self._request("core", {"operation": operation, "params": params or {}, "idempotency_key": key})

    def core_failure_observation(self, error):
        observed = self._core_failure
        if (observed is not None and type(error) is PeerFailure and error.code == "internal" and observed[0] is error):
            return core_failure_observation(observed[1])
        return None

    def failure_transport_observation(self, error):
        try:
            observed = self._transport_failure
            if (type(error) is not PeerFailure or error.code != "peer_closed"
                    or type(observed) is not tuple or len(observed) != 3
                    or observed[0] is not error or observed[1] != f"qualification:{self._sequence}"):
                return None
            return android_transport_snapshot(observed[2])
        except Exception:
            return None

    def failure_lifecycle_observation(self, error):
        try:
            observed = self._lifecycle_failure
            if (type(error) is not subprocess.CalledProcessError
                    or type(observed) is not tuple or len(observed) != 2
                    or observed[0] is not error):
                return None
            return android_lifecycle_snapshot(observed[1])
        except Exception:
            return None

    def _observe_stop_failure(self, error, origin, masked_start_kind, prior_failure=None):
        try:
            observed = self._lifecycle_failure
            if observed is not None and observed[0] is error:
                detail = android_lifecycle_snapshot({**observed[1], "stop_origin": origin,
                    **({"prior_failure": prior_failure} if prior_failure is not None else {}),
                    **({"masked_start_kind": masked_start_kind} if origin == "start_rollback" else {})})
                if detail is not None: self._lifecycle_failure = (error, detail)
        except Exception: pass  # Keep the exact escaping lifecycle failure.

    def network_diagnostic(self, *, timeout):
        binding = self._qualification_binding
        if binding is None: return None
        return self._request("inspect", {"command": "qualification.network_diagnostic", "payload": {
            "qualification_binding": binding}},
            timeout=timeout)

    @staticmethod
    def _initial_binding(value):
        if type(value) is not dict or value.get("resources") != []:
            return None
        counts = value.get("host_accounting")
        if type(counts) is not dict or counts.get("complete") is not True or any(
                type(counts.get(name)) is not int or counts[name] != 0 for name in
                ("reserved_count", "creating_count", "allocated_count", "active_count", "retiring_count")):
            return None
        service, profile = value.get("service_incarnation"), value.get("profile_incarnation")
        if any(type(item) is not str or re.fullmatch(r"[a-f0-9]{32}", item) is None
               for item in (service, profile)):
            return None
        return service + profile

    def inventory(self, *, operation_id=None, request_id=None, carrier_observation=None):
        return self._request("inspect", {"command": "qualification.inventory",
            "payload": inventory_payload(operation_id, request_id, carrier_observation)})

    def retire_carrier(self, operation_id, request_id, logical_session, expected_physical,
                       expected_service_incarnation, expected_adapter_epoch, *, action=None):
        return self._request("inspect", {"command": "qualification.retire_carrier", "payload": retirement_payload(
            operation_id, request_id, logical_session, expected_physical, expected_service_incarnation, expected_adapter_epoch, action=action)})

    def path(self, logical, physical, sample_request):
        return self._request("inspect", {"command": "qualification.path_evidence", "payload": {
            "logical_session": logical, "expected_physical": physical, "sample_request": checked_sample_request(sample_request)}})

    def pairing_begin(self, operation_id, role, *, pairing_code=None, direct=False):
        payload = {"operation_id": operation_id, "role": role, "allow_direct_ip_disclosure": direct}
        if pairing_code is not None: payload["pairing_code"] = pairing_code
        return self._request("inspect", {"command": "qualification.pairing_begin", "payload": payload})

    def pairing_status(self, operation_id):
        return self._request("inspect", {"command": "qualification.pairing_status", "payload": {"operation_id": operation_id}})

    def pairing_cancel(self, operation_id):
        return self._request("inspect", {"command": "qualification.pairing_cancel", "payload": {"operation_id": operation_id}})

    def stop(self, *, crash=False, delete_profile=False, _origin="other_stop", _masked_start_kind="none"):
        self._observe_system_phase("peer_stop")
        self._lifecycle_failure = None
        self._core_failure = None
        self._qualification_binding = None
        self._transport_failure = None
        process = self.process
        if process is None:
            return
        finished = False
        prior_failure = None
        stage = "force_stop" if crash else "finish"
        try:
            if crash:
                self._adb("shell", "am", "force-stop", self.APP)
                self.forced_exits += 1
            else:
                result = self._request("finish", {"delete_profile": delete_profile})
                if (not isinstance(result, dict) or result.get("closed") is not True
                        or result.get("resources_retired") is not True or result.get("store_retired") is not True):
                    raise PeerFailure("android_retirement_unverified")
                finished = True
            stage = "process_wait"
            code = process.wait(timeout=30)
            stage = "reader_join"
            self._reader.join(5)
            if not crash:
                stage = "exit_check"
                if code != 0 or self._reader.is_alive():
                    raise PeerFailure("unclean_android_exit")
                self.clean_exits += 1
        except Exception as error:
            try: prior_failure = stop_failure(stage, error)
            except Exception: pass  # Observation cannot replace the original stop failure.
            try: self._observe_stop_failure(error, _origin, _masked_start_kind)
            except Exception: pass
            raise
        finally:
            try:
                if self.socket is not None:
                    self.socket.close()
                    self.socket = None
                if not crash and not finished:
                    self._adb("shell", "am", "force-stop", self.APP)
                if self.forward is not None:
                    self._adb("forward", "--remove", "tcp:" + self.forward)
                    self.forward = None
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
                process.stdout.close()
                self.process = None
            except Exception as error:
                try: self._observe_stop_failure(error, _origin, _masked_start_kind, prior_failure)
                except Exception: pass
                raise

    def _observe_system_phase(self, phase):
        try:
            observation = getattr(self, "system_observation", None)
            if observation is not None: observation.phase(phase)
        except Exception:
            pass


def wait_emulator_transport_retired(emulator):
    """Keep emulator custody until ADB no longer lists its exited transport."""
    deadline = time.monotonic() + 30
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            devices = subprocess.check_output(
                [str(emulator.sdk / "platform-tools/adb"), "devices"],
                stderr=subprocess.DEVNULL, text=True, timeout=min(5, remaining))
        except Exception as error:
            raise PeerFailure("emulator_transport_retirement_failed") from error
        lines = devices.splitlines()
        if not lines or lines[0].strip() != "List of devices attached":
            raise PeerFailure("emulator_transport_retirement_failed")
        serials = {line.split()[0] for line in lines[1:] if line.strip()}
        if serials - {emulator.serial}:
            raise PeerFailure("unowned_android_device_present")
        if not serials:
            emulator._transport_owned = False
            return
        time.sleep(min(.25, max(0, deadline - time.monotonic())))
    raise PeerFailure("emulator_transport_retirement_failed")


class AndroidEmulator:
    """Own the KVM emulator for the whole Node Action, including its cleanup."""
    IMAGE = "system-images;android-35;google_apis;x86_64"

    def __init__(self):
        if (sys.platform != "linux" or os.environ.get("GITHUB_ACTIONS") != "true"
                or not os.access("/dev/kvm", os.R_OK | os.W_OK)):
            raise PeerFailure("linux_kvm_ci_required")
        self.sdk = Path(os.environ.get("ANDROID_SDK_ROOT") or os.environ["ANDROID_HOME"])
        self.name = "mesh-native-" + uuid4().hex[:12]
        self.root = Path(os.environ["RUNNER_TEMP"]).resolve() / self.name
        self.serial = "emulator-5554"
        self.process = None
        self.old_environment = {}
        self._start_failure = None
        self._transport_owned = False
        from native_interop_android_system import AndroidSystemObservation
        self.observation = AndroidSystemObservation()

    def _adb(self, *arguments, timeout=30):
        return subprocess.check_output([str(self.sdk / "platform-tools/adb"), "-s", self.serial, *arguments],
            stderr=subprocess.PIPE if arguments == ("root",) else subprocess.DEVNULL,
            timeout=timeout).decode().strip()

    def start(self, apks, *, diagnostics=None):
        self._start_failure = None
        diagnostics = diagnostics if diagnostics is not None else PreflightDiagnostics()
        with diagnostics.scope("android_devices"):
            devices = subprocess.check_output([str(self.sdk / "platform-tools/adb"), "devices"],
                stderr=subprocess.DEVNULL, text=True, timeout=15)
        if any(line.strip() for line in devices.splitlines()[1:]):
            raise PeerFailure("unowned_android_device_present")
        self.root.mkdir(exist_ok=False)
        for key, value in {"ANDROID_AVD_HOME": str(self.root), "ANDROID_SERIAL": self.serial}.items():
            self.old_environment[key] = os.environ.get(key)
            os.environ[key] = value
        try:
            avdmanager = shutil.which("avdmanager")
            if not avdmanager:
                raise PeerFailure("avdmanager_unavailable")
            with diagnostics.scope("android_avd_create"):
                subprocess.run([avdmanager, "create", "avd", "--name", self.name, "--package", self.IMAGE],
                    input=b"no\n", check=True, capture_output=True, timeout=120)
            from native_interop_android_system import LOG_TAGS
            self.process = subprocess.Popen([str(self.sdk / "emulator/emulator"), "-avd", self.name,
                "-port", "5554", "-no-window", "-gpu", "swiftshader_indirect", "-accel", "on",
                "-no-snapshot", "-noaudio", "-no-boot-anim", "-camera-back", "none", "-camera-front", "none",
                "-logcat", LOG_TAGS],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
            self._transport_owned = True
            self.observation.start(self.process.stdout)
            deadline = time.monotonic() + 600
            booted = False
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise PeerFailure("emulator_exited_during_boot")
                try: booted = self._adb("shell", "getprop", "sys.boot_completed", timeout=5) == "1"
                except Exception: booted = False
                if booted: break
                time.sleep(1)
            if not booted: raise PeerFailure("emulator_boot_deadline")
            with diagnostics.scope("android_root"):
                self._adb("root")
            with diagnostics.scope("android_wait_for_device"):
                self._adb("wait-for-device")
            with diagnostics.scope("android_root_identity"):
                uid = self._adb("shell", "id", "-u")
            if uid != "0":
                raise PeerFailure("required_rootable_kernel_unavailable")
            install_sites = ("android_host_apk_install", "android_test_apk_install")
            for index, apk in enumerate(apks):
                with diagnostics.scope(install_sites[index] if index < len(install_sites) else None):
                    self._adb("install", "-r", str(apk), timeout=120)
            with diagnostics.scope("android_notification_grant"):
                self._adb("shell", "pm", "grant", AndroidPeer.APP, "android.permission.POST_NOTIFICATIONS")
        except Exception as error:
            from native_interop_android_start import exception_kind
            observed = {"process": process_observation(self.process), "cleanup_exception_kind": None}
            self._start_failure = (error, observed)
            try:
                self.close()
            except Exception as cleanup:
                observed["cleanup_exception_kind"] = exception_kind(cleanup, peer_failure=isinstance(cleanup, PeerFailure))
                raise error from cleanup
            raise

    def failure_start_observation(self, error):
        recorded = self._start_failure
        if recorded is None or recorded[0] is not error:
            return None
        return {**recorded[1], "process": dict(recorded[1]["process"])}

    def close(self):
        self.observation.phase("cleanup")
        failure = None
        if self.process is not None:
            try:
                if self.process.poll() is None:
                    self._adb("emu", "kill")
                    self.process.wait(timeout=30)
            except Exception:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=15)
                except Exception:
                    failure = PeerFailure("emulator_retirement_failed")
            if self.process.poll() is not None:
                if self.observation.finish(self.process.stdout): self.process = None
                else: failure = PeerFailure("emulator_observer_retirement_failed")
        if self.process is None:
            if self._transport_owned:
                wait_emulator_transport_retired(self)
            expected_parent = Path(os.environ["RUNNER_TEMP"]).resolve()
            if self.root.parent != expected_parent or self.root.name != self.name:
                raise PeerFailure("emulator_cleanup_path_changed")
            if self.root.is_dir(): shutil.rmtree(self.root)
            for key, previous in self.old_environment.items():
                if previous is None: os.environ.pop(key, None)
                else: os.environ[key] = previous
        if failure is not None: raise failure
