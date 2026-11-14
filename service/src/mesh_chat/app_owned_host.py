"""Normal, empty, independently installed Windows application runtime host."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
from threading import Event, RLock, Thread
import time

from .app_owned_admission import AppOwnedAdmission, ProcessPort
from .app_owned_control import (
    HELPER_PREFACE_LENGTH, MAX_CONTROL_LINE, decode_helper_preface,
    decode_owner_control, helper_registered_ack, helper_removed_ack,
)
from .core_api.host import OWNER_PERMISSIONS
from .core_api.pipe_endpoint import PipeClientAdmission, PipeConfig, PipeEndpoint
from .core_api.pipe_policy import allowed_images, pipe_name
from .errors import MeshChatError, NativeUnavailable, ValidationError
from .inherited_input import InheritedInput
from .service import MeshChatService
from .reticulum_config import NetworkSettings
from .vault import ProfileLock, VaultStore
from .windows_app_key import load_key


@dataclass(frozen=True)
class AppOwnedConfig:
    data_directory: Path
    pipe: str
    client_image: str
    parent_pid: int
    private_admission: bool = False

    def __post_init__(self):
        directory = self.data_directory
        if (not isinstance(directory, Path) or not directory.is_absolute()
                or not 1 <= len(str(directory)) <= 1024 or "\0" in str(directory)
                or type(self.parent_pid) is not int or not 1 <= self.parent_pid <= 0xFFFFFFFF
                or type(self.private_admission) is not bool):
            raise ValidationError("App-owned runtime configuration is invalid")
        pipe_name(self.pipe)
        allowed_images((self.client_image,))

    @classmethod
    def from_environment(cls, environment):
        try:
            private = environment.get("MESH_CHAT_APP_PRIVATE_HELPER_ADMISSION", "0")
            if type(private) is not str or private not in ("0", "1"):
                raise ValueError()
            return cls(Path(environment["MESH_CHAT_APP_DATA_DIRECTORY"]),
                environment["MESH_CHAT_CORE_API_PIPE"], environment["MESH_CHAT_CORE_API_CLIENT_IMAGE"],
                int(environment["MESH_CHAT_APP_PARENT_PID"]), private == "1")
        except (KeyError, TypeError, ValueError):
            raise ValidationError("App-owned runtime configuration is invalid") from None


class AppOwnedStartupIncomplete(NativeUnavailable):
    def __init__(self, runtime):
        super().__init__("App-owned runtime startup is incomplete")
        self.runtime = runtime


class AppOwnedPipeAdmission:
    """Opt-in, host-private callback for one connected Windows pipe client.

    The caller must fence the roster under service dispatch before stopping the
    endpoint. Retire this callback only after endpoint workers have exited; it
    owns temporary process-query handles, not the roster's owner/helper pins.
    """

    def __init__(self, roster: AppOwnedAdmission, processes: ProcessPort,
                 *, preface_seconds: float = 5.0):
        if (type(preface_seconds) not in (int, float)
                or not 0.1 <= preface_seconds <= 10.0):
            raise ValueError("Private helper preface deadline is invalid")
        self._roster = roster
        self._processes = processes
        self._preface_seconds = float(preface_seconds)
        self._pending = []
        self._closed = False
        self._lock = RLock()

    def __call__(self, pid, stream) -> PipeClientAdmission | None:
        """Return a lease only for an OS-identical owner or invited helper."""
        with self._lock:
            if self._closed:
                return None
            handle = lease = None
            try:
                handle = self._processes.open(pid)
                identity = handle.identity
                role = self._roster.candidate_role(identity)
                if role == "owner":
                    lease = self._roster.admit(identity)
                elif role == "helper":
                    line = stream.readline(HELPER_PREFACE_LENGTH,
                                           deadline=time.monotonic() + self._preface_seconds)
                    token = decode_helper_preface(line)
                    lease = self._roster.admit(identity, token)
            except Exception:
                pass  # A failed process query or proof cannot create a grant.
            finally:
                if handle is not None:
                    try:
                        handle.close()
                    except Exception:
                        self._pending.append(handle)
                        self._closed = True
            if lease is None or self._closed:
                if lease is not None:
                    self._roster.release(lease)
                return None
            return PipeClientAdmission(lambda: not self._closed and self._roster.authorize(lease),
                                       lambda: self._roster.release(lease))

    def retire(self) -> bool:
        """Retry temporary handles and failed port opens after workers stop."""
        with self._lock:
            self._closed = True
            pending = self._pending
            self._pending = []
            for handle in pending:
                try:
                    handle.close()
                except Exception:
                    self._pending.append(handle)
            port_retired = self._processes.retire() is True
            return not self._pending and port_retired


class _PrivateOwnerWatcher:
    """Stop and join the pinned owner watch before closing the roster pin."""

    def __init__(self, owner, reader):
        self._owner = owner
        self._reader = reader
        self._stop = Event()
        self._thread = Thread(target=self._watch, name="mesh-chat-private-owner-watch", daemon=True)
        self._thread.start()

    def _watch(self):
        while not self._stop.wait(.05):
            try:
                alive = self._owner.is_alive() is True
            except Exception:
                alive = False
            if not alive:
                cancel = getattr(self._reader, "cancel", None)
                if callable(cancel):
                    cancel()
                return

    def retire(self) -> bool:
        self._stop.set()
        self._thread.join(timeout=1)
        return not self._thread.is_alive()


class AppOwnedRuntime:
    """Retain exact store/native owners until both retirement acknowledgments."""
    def __init__(self, config, *, key_loader=load_key, store_factory=VaultStore,
                 service_factory=MeshChatService, host_factory=None, endpoint_factory=PipeEndpoint,
                 process_port_factory=None, private_input=None, watcher_factory=_PrivateOwnerWatcher):
        self.service = self.store = self.host = self.endpoint = self.lease = None
        self.owner_port = self.admission = self.pipe_admission = self.watcher = None
        self._startup_owner = None
        try:
            if config.private_admission and not callable(getattr(private_input, "cancel", None)):
                raise ValidationError("Private owner input must be cancellable")
            root = config.data_directory.resolve() / "mesh-core-runtime"
            if root.is_symlink() or root.is_junction():
                raise NativeUnavailable("App-owned directory binding changed")
            root.mkdir(parents=True, exist_ok=True)
            self.lease = ProfileLock(root / ".runtime.lock")
            directory = root / "profile-v1"
            if directory.is_symlink() or directory.is_junction():
                raise NativeUnavailable("App-owned profile binding changed")
            self.store = store_factory(directory, key_loader(root))
            if self.store.get("settings", "network") is None:
                self.store.put("settings", "network",
                    NetworkSettings(nearby_discovery=False, lan_fallback=False).to_dict())
            if host_factory is None:
                from .native_windows_webrtc import WindowsNativeWebRTCHost
                host_factory = WindowsNativeWebRTCHost
            self.host = host_factory(lambda *event: self.service.native_webrtc_event(*event)
                if self.service is not None else None)
            self.service = service_factory(self.store, directory, lambda _: None,
                connection_policy="shared-native", native_webrtc_host=self.host)
            if config.private_admission:
                lock = getattr(self.service, "_dispatch_lock", None)
                if (lock is None or not callable(getattr(lock, "__enter__", None))
                        or not callable(getattr(lock, "__exit__", None))):
                    raise NativeUnavailable("Private service dispatch lock is unavailable")
            config_pipe = PipeConfig(caller="mesh-core-independent-application",
                permissions=tuple(sorted(OWNER_PERMISSIONS | {"profile_owner"})),
                allowed_images=(config.client_image,), max_clients=2, idle_timeout=300,
                scope="owner", private_profile_bootstrap=True,
                private_native=False, private_composer_legacy=False)
            if config.private_admission:
                if process_port_factory is None:
                    from .app_owned_windows_process import WindowsProcessPort
                    process_port_factory = WindowsProcessPort
                self.owner_port = process_port_factory()
                self._startup_owner = self.owner_port.open(config.parent_pid)
                self.admission = AppOwnedAdmission(self._startup_owner,
                                                    config.client_image, self.owner_port)
                owner = self._startup_owner
                self._startup_owner = None  # The roster now owns this exact pin.
                self.pipe_admission = AppOwnedPipeAdmission(self.admission, self.owner_port)
                self.endpoint = endpoint_factory(config.pipe, config_pipe,
                                                 admit_client=self.pipe_admission)
            else:
                self.endpoint = endpoint_factory(config.pipe, config_pipe)
            self.endpoint.start(self.service)
            if config.private_admission:
                self.watcher = watcher_factory(owner, private_input)
        except Exception as error:
            self.service = getattr(error, "retiring_service", self.service)
            raise AppOwnedStartupIncomplete(self) from error

    def close(self):
        if self.admission is not None:
            lock = getattr(self.service, "_dispatch_lock", None)
            if lock is None:
                raise RuntimeError("Private service dispatch lock is unavailable")
            with lock:
                self.admission.fence()
        if self.endpoint is not None:
            self.endpoint.close()
            self.endpoint = None
        if self.watcher is not None:
            if self.watcher.retire() is not True:
                return False
            self.watcher = None
        if self.admission is not None:
            if self.admission.retire() is not True:
                return False
            self.admission = None
        if self._startup_owner is not None:
            self._startup_owner.close()
            self._startup_owner = None
        if self.pipe_admission is not None:
            if self.pipe_admission.retire() is not True:
                return False
            self.pipe_admission = None
        if self.owner_port is not None:
            if self.owner_port.retire() is not True:
                return False
            self.owner_port = None
        if self.service is not None:
            self.service.close()
            if not self.service._store_closed:
                return False
        elif self.store is not None:
            self.store.close()
        if self.host is not None:
            self.host.shutdown()
            self.host = None
        if self.lease is not None:
            self.lease.close()
            self.lease = None
        return True


def _require_windows():
    if os.name != "nt":
        raise NativeUnavailable("App-owned runtime requires Windows")


def _pairing_diagnostics_enabled(environment):
    key = "MESH_CHAT_APP_PAIRING_DIAGNOSTICS"
    if key not in environment:
        return False
    value = environment[key]
    if value not in ("0", "1") or type(value) is not str:
        raise ValidationError("App-owned pairing diagnostics flag is invalid")
    return value == "1"


def _pairing_diagnostics_status(runtime):
    try:
        from .app_owned_diagnostics import observe_pairing

        message = {"v": 1, "type": "runtime_pairing_diagnostics",
                   "observation": observe_pairing(runtime.service)}
        if len(json.dumps(message, separators=(",", ":")).encode("utf-8")) > 4000:
            message["observation"] = {"status": "unavailable", "total_intents": 0, "intents": []}
        return message
    except BaseException:
        return {"v": 1, "type": "runtime_pairing_diagnostics",
                "observation": {"status": "unavailable", "total_intents": 0, "intents": []}}


def _owner_control_line(reader):
    """Read one private line with a fixed byte ceiling and post-first-byte deadline."""
    line = bytearray()
    deadline = None
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            raise ValidationError("Private owner control deadline expired")
        part = (reader.read(1, deadline=deadline) if isinstance(reader, InheritedInput)
                else reader.read(1))
        if deadline is not None and time.monotonic() >= deadline:
            raise ValidationError("Private owner control deadline expired")
        if part == b"":
            if line:
                raise ValidationError("Private owner control ended mid-line")
            return None
        if type(part) is not bytes or len(part) != 1:
            raise ValidationError("Private owner control input is invalid")
        if deadline is None:
            deadline = time.monotonic() + 5
        line.extend(part)
        if len(line) > MAX_CONTROL_LINE:
            raise ValidationError("Private owner control exceeds its ceiling")
        if part == b"\n":
            return decode_owner_control(bytes(line))


def _serve_owner_controls(reader, runtime, publish):
    while True:
        command = _owner_control_line(reader)
        if command is None:
            return
        with runtime.service._dispatch_lock:
            if command.action == "register":
                invitation = runtime.admission.register_helper(command.pid)
                response = helper_registered_ack(command.sequence, invitation.token)
            else:
                if runtime.admission.remove_helper(command.pid) is not True:
                    raise NativeUnavailable("Private helper removal is pending")
                response = helper_removed_ack(command.sequence)
        publish(response)


def run(reader, writer, *, watch_parent, environment=None, runtime_factory=AppOwnedRuntime):
    """Inherited stdin controls lifetime by EOF only; SDK traffic uses the pipe."""
    runtime, status = None, 0
    def publish(value, *, required=False):
        try:
            writer.write(value)
        except (OSError, ValueError):
            if required:
                raise
            pass  # A lost status pipe cannot surrender native/store custody.
    try:
        _require_windows()
        selected_environment = os.environ if environment is None else environment
        pairing_diagnostics = _pairing_diagnostics_enabled(selected_environment)
        config = AppOwnedConfig.from_environment(selected_environment)
        if not config.private_admission:
            watch_parent(config.parent_pid)
        runtime = (runtime_factory(config, private_input=reader) if config.private_admission
                   else runtime_factory(config))
        publish({"v": 1, "type": "runtime_started", "pipe": config.pipe},
                required=config.private_admission)
        if config.private_admission:
            _serve_owner_controls(reader, runtime, lambda value: publish(value, required=True))
        elif reader.read(1):
            raise ValidationError("App-owned lifetime stream accepts only EOF")
        if pairing_diagnostics:
            try:
                publish(_pairing_diagnostics_status(runtime))
            except BaseException:
                pass  # Diagnostic transport cannot change runtime retirement.
    except AppOwnedStartupIncomplete as error:
        runtime, status = error.runtime, 2
        publish({"v": 1, "type": "runtime_failed", "error": "unavailable"})
    except Exception as error:
        status = 2
        publish({"v": 1, "type": "runtime_failed",
            "error": error.code if isinstance(error, MeshChatError) else "unavailable"})
    finally:
        if runtime is not None:
            retiring = False
            while True:
                try:
                    if runtime.close():
                        break
                except Exception:
                    pass  # Retain exact custody; never claim that cleanup finished.
                if not retiring:
                    publish({"v": 1, "type": "runtime_retiring"})
                    retiring = True
                Event().wait(.05)
            publish({"v": 1, "type": "runtime_stopped"})
    return status
