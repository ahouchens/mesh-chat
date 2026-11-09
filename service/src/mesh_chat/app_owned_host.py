"""Normal, empty, independently installed Windows application runtime host."""
from dataclasses import dataclass
import os
from pathlib import Path
from threading import Event

from .core_api.host import OWNER_PERMISSIONS
from .core_api.pipe_endpoint import PipeConfig, PipeEndpoint
from .core_api.pipe_policy import allowed_images, pipe_name
from .errors import MeshChatError, NativeUnavailable, ValidationError
from .service import MeshChatService
from .vault import ProfileLock, VaultStore
from .windows_app_key import load_key


@dataclass(frozen=True)
class AppOwnedConfig:
    data_directory: Path
    pipe: str
    client_image: str
    parent_pid: int

    def __post_init__(self):
        directory = self.data_directory
        if (not isinstance(directory, Path) or not directory.is_absolute()
                or not 1 <= len(str(directory)) <= 1024 or "\0" in str(directory)
                or type(self.parent_pid) is not int or not 1 <= self.parent_pid <= 0xFFFFFFFF):
            raise ValidationError("App-owned runtime configuration is invalid")
        pipe_name(self.pipe)
        allowed_images((self.client_image,))

    @classmethod
    def from_environment(cls, environment):
        try:
            return cls(Path(environment["MESH_CHAT_APP_DATA_DIRECTORY"]),
                environment["MESH_CHAT_CORE_API_PIPE"], environment["MESH_CHAT_CORE_API_CLIENT_IMAGE"],
                int(environment["MESH_CHAT_APP_PARENT_PID"]))
        except (KeyError, TypeError, ValueError):
            raise ValidationError("App-owned runtime configuration is invalid") from None


class AppOwnedStartupIncomplete(NativeUnavailable):
    def __init__(self, runtime):
        super().__init__("App-owned runtime startup is incomplete")
        self.runtime = runtime


class AppOwnedRuntime:
    """Retain exact store/native owners until both retirement acknowledgments."""
    def __init__(self, config, *, key_loader=load_key, store_factory=VaultStore,
                 service_factory=MeshChatService, host_factory=None, endpoint_factory=PipeEndpoint):
        self.service = self.store = self.host = self.endpoint = self.lease = None
        try:
            root = config.data_directory.resolve() / "mesh-core-runtime"
            if root.is_symlink() or root.is_junction():
                raise NativeUnavailable("App-owned directory binding changed")
            root.mkdir(parents=True, exist_ok=True)
            self.lease = ProfileLock(root / ".runtime.lock")
            directory = root / "profile-v1"
            if directory.is_symlink() or directory.is_junction():
                raise NativeUnavailable("App-owned profile binding changed")
            self.store = store_factory(directory, key_loader(root))
            if host_factory is None:
                from .native_windows_webrtc import WindowsNativeWebRTCHost
                host_factory = WindowsNativeWebRTCHost
            self.host = host_factory(lambda *event: self.service.native_webrtc_event(*event)
                if self.service is not None else None)
            self.service = service_factory(self.store, directory, lambda _: None,
                connection_policy="shared-native", native_webrtc_host=self.host)
            config_pipe = PipeConfig(caller="mesh-core-independent-application",
                permissions=tuple(sorted(OWNER_PERMISSIONS | {"profile_owner"})),
                allowed_images=(config.client_image,), max_clients=2, idle_timeout=300,
                scope="owner", private_profile_bootstrap=True,
                private_native=False, private_composer_legacy=False)
            self.endpoint = endpoint_factory(config.pipe, config_pipe)
            self.endpoint.start(self.service)
        except Exception as error:
            self.service = getattr(error, "retiring_service", self.service)
            raise AppOwnedStartupIncomplete(self) from error

    def close(self):
        if self.endpoint is not None:
            self.endpoint.close()
            self.endpoint = None
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


def run(reader, writer, *, watch_parent, environment=None, runtime_factory=AppOwnedRuntime):
    """Inherited stdin controls lifetime by EOF only; SDK traffic uses the pipe."""
    runtime, status = None, 0
    def publish(value):
        try:
            writer.write(value)
        except (OSError, ValueError):
            pass  # A lost status pipe cannot surrender native/store custody.
    try:
        _require_windows()
        config = AppOwnedConfig.from_environment(os.environ if environment is None else environment)
        watch_parent(config.parent_pid)
        runtime = runtime_factory(config)
        publish({"v": 1, "type": "runtime_started", "pipe": config.pipe})
        if reader.read(1):
            raise ValidationError("App-owned lifetime stream accepts only EOF")
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
