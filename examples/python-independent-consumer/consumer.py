"""Installed Python SDK against one ordinary app-owned Windows runtime."""

import argparse
import json
import os
from pathlib import Path
from queue import Queue
import re
import subprocess
import sys
from threading import Thread
from time import monotonic
from uuid import uuid4


STATUS_LIMIT = 4096
STATUS_TIMEOUT = 30
END_OF_STATUS = object()
CHECKS = {
    "fresh_without_profile": True,
    "public_only_capabilities": True,
    "explicit_profile_create_and_key_replay": True,
    "changed_key_payload_rejected": True,
    "reopen_same_public_identity": True,
    "clean_host_exits": 2,
}
phase = "arguments"
retirement_outcome = "not_started"


def _exact(stream, count):
    chunks = bytearray()
    while len(chunks) < count:
        chunk = stream.read(count - len(chunks))
        if not chunk:
            raise ValueError("runtime_status_closed")
        chunks.extend(chunk)
    return bytes(chunks)


def read_status(stream, header=None):
    header = _exact(stream, 4) if header is None else header
    if len(header) != 4:
        raise ValueError("runtime_status_truncated")
    length = int.from_bytes(header, "big")
    if not 2 <= length <= STATUS_LIMIT:
        raise ValueError("runtime_status_budget")
    value = json.loads(_exact(stream, length).decode("utf-8", "strict"))
    if not isinstance(value, dict) or type(value.get("v")) is not int or value["v"] != 1:
        raise ValueError("runtime_status_protocol")
    return value


class Runtime:
    def __init__(self, executable, directory):
        if os.name != "nt" or not executable.is_absolute() or not directory.is_absolute():
            raise ValueError("explicit_windows_runtime_and_data_required")
        self.pipe = "\\\\.\\pipe\\mesh-chat-python-" + uuid4().hex
        environment = {name: value for name, value in os.environ.items()
                       if not name.upper().startswith(("MESH_", "GITHUB_", "ACTIONS_", "INPUT_"))
                       and name.upper() not in {"PYTHONPATH", "PYTHONHOME", "NODE_PATH", "NODE_OPTIONS"}}
        environment.update(MESH_CHAT_APP_DATA_DIRECTORY=str(directory),
                           MESH_CHAT_CORE_API_PIPE=self.pipe,
                           MESH_CHAT_CORE_API_CLIENT_IMAGE=str(Path(sys.executable).resolve()),
                           MESH_CHAT_APP_PARENT_PID=str(os.getpid()))
        self.process = subprocess.Popen([str(executable), "--app-owned-native"],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, env=environment,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
        self.statuses = Queue(maxsize=4)
        self.reader = Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            first = self._next(STATUS_TIMEOUT)
            if first != {"v": 1, "type": "runtime_started", "pipe": self.pipe}:
                raise ValueError("runtime_start_unavailable")
        except BaseException:
            self._abort_start()
            raise

    def _read(self):
        try:
            while True:
                header = self.process.stdout.read(4)
                if not header:
                    self.statuses.put_nowait(END_OF_STATUS)
                    return
                self.statuses.put_nowait(read_status(self.process.stdout, header))
        except BaseException as error:
            try:
                self.statuses.put_nowait(error)
            except Exception:
                pass

    def _next(self, timeout):
        value = self.statuses.get(timeout=max(0, timeout))
        if isinstance(value, BaseException):
            raise ValueError("runtime_status_unavailable") from value
        return value

    def _abort_start(self):
        if self.process.stdin and not self.process.stdin.closed:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        try:
            self.process.wait(timeout=STATUS_TIMEOUT)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        finally:
            if self.process.stdout:
                self.process.stdout.close()
            self.reader.join(timeout=1)

    def stop(self):
        deadline = monotonic() + STATUS_TIMEOUT
        try:
            if self.process.stdin and not self.process.stdin.closed:
                self.process.stdin.close()  # EOF is the only host lifetime command.
            stopped = False
            while not stopped:
                value = self._next(deadline - monotonic())
                if value == {"v": 1, "type": "runtime_retiring"}:
                    continue
                if value != {"v": 1, "type": "runtime_stopped"}:
                    raise ValueError("runtime_retirement_protocol")
                stopped = True
            code = self.process.wait(timeout=max(0, deadline - monotonic()))
            if code != 0:
                raise ValueError("runtime_exit_unavailable")
            if self._next(deadline - monotonic()) is not END_OF_STATUS:
                raise ValueError("runtime_trailing_status")
            self.reader.join(timeout=max(0, deadline - monotonic()))
            if self.reader.is_alive() or not self.statuses.empty():
                raise ValueError("runtime_trailing_status")
        except BaseException:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=5)
            raise
        finally:
            if self.process.stdout:
                self.process.stdout.close()
            self.reader.join(timeout=1)


def check(executable, directory, site):
    if not site.is_absolute() or not site.is_dir():
        raise ValueError("installed_sdk_required")
    sys.path.insert(0, str(site))
    from mesh_chat_core_client import CoreClient, CoreClientError
    from mesh_chat_core_client.windows import connect
    import mesh_chat_core_client

    if (not Path(mesh_chat_core_client.__file__).resolve().is_relative_to(site.resolve())
            or any(name == "mesh_chat" or name.startswith("mesh_chat.") for name in sys.modules)):
        raise ValueError("private_or_uninstalled_sdk")
    key = uuid4().hex
    identity = None
    global phase, retirement_outcome
    for incarnation in range(2):
        phase = "runtime_start"
        retirement_outcome = "unconfirmed"
        runtime = Runtime(executable, directory)
        client = None
        api_failure = None
        api_phase = None
        try:
            phase = "capabilities"
            pipe = connect(runtime.pipe)
            client = CoreClient.open(pipe.readline, pipe.write, pipe.close)
            caps = client.capabilities
            if (len(caps.get("profiles", [])) != 1 or "profile.create" not in caps.get("operations", [])
                    or "native.command" in caps.get("operations", [])):
                raise ValueError("public_capabilities_incomplete")
            handle = caps["profiles"][0]
            phase = "fresh_state"
            before = client.application_snapshot()
            if ((before.get("profile") is None) != (incarnation == 0)
                    or before.get("contacts") != [] or before.get("messages") != []):
                raise ValueError("unexpected_public_state")
            if incarnation == 0:
                try:
                    client.profile(handle)
                    raise ValueError("empty_profile_was_queryable")
                except CoreClientError as error:
                    if error.code != "locked":
                        raise
            phase = "profile_create"
            first = client.create_profile("Independent Python application", key)
            phase = "key_replay"
            if client.create_profile("Independent Python application", key) != first:
                raise ValueError("profile_replay_changed")
            phase = "changed_payload"
            try:
                client.create_profile("Changed intent", key)
                raise ValueError("changed_payload_accepted")
            except CoreClientError as error:
                if error.code != "idempotency_conflict":
                    raise
            phase = "observations"
            profile = client.profile(handle)
            snapshot = client.application_snapshot()
            if (profile.get("display_name") != "Independent Python application"
                    or snapshot.get("profile", {}).get("display_name") != profile["display_name"]
                    or not isinstance(profile.get("destination"), str)
                    or not profile["destination"] or snapshot.get("contacts") != []
                    or snapshot.get("messages") != []):
                raise ValueError("profile_observation_incomplete")
            if incarnation == 0:
                identity = profile["destination"]
            elif identity != profile["destination"]:
                raise ValueError("reopened_identity_changed")
        except Exception as error:
            api_failure, api_phase = error, phase
        finally:
            retirement_failure = None
            try:
                if client is not None:
                    client.close()
            except Exception as error:
                retirement_failure = error
            try:
                runtime.stop()
            except Exception as error:
                retirement_failure = error
            if retirement_failure is None:
                retirement_outcome = "confirmed"
            elif api_failure is None:
                phase = "retirement"
                api_failure = retirement_failure
        if api_failure is not None:
            if api_phase is not None:
                phase = api_phase
            raise api_failure
    return CHECKS


def main():
    global phase
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--data-directory", type=Path, required=True)
    parser.add_argument("--site", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.runtime, args.data_directory, args.site), separators=(",", ":")))
        return 0
    except Exception as error:
        candidate = getattr(error, "code", None)
        code = candidate if isinstance(candidate, str) and re.fullmatch(r"[a-z_]{1,64}", candidate) else "unavailable"
        print(json.dumps({"passed": False, "phase": phase, "error_code": code,
                          "retirement_outcome": retirement_outcome}, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
