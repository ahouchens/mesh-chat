"""CI-only adapter to the shipping native dispatcher over inherited frames.

The controlled fabric translates the signed synthetic public candidate address
to loopback, preserving its exact native-owned port and certificate. It performs
no discovery and is not physical router evidence.
"""
import os
import subprocess
import threading

from mesh_chat.direct_native import NativeChannel
from mesh_chat.ipc import FrameWriter, read_frame


class AppHostNative:
    def __init__(self, executable):
        self.process = subprocess.Popen([executable],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.writer = FrameWriter(self.process.stdin)
        self.channel = NativeChannel(self.writer.write)
        self._lock = threading.Lock()
        self._closed = False
        self.owned = {}
        self.blocked = False
        self.migration_attempts = self.migrations = 0
        self._reader = threading.Thread(target=self._read,daemon=True,name="controlled-native-private")
        self._reader.start()

    def _read(self):
        try:
            while True:
                self.channel.receive(read_frame(self.process.stdout,max_bytes=65536))
        except Exception:
            self.channel.close()

    def request(self, operation, **payload):
        if operation in {"prepare", "prepare_recovery"}:
            public_host = payload["address"].rsplit(":",1)[0].strip("[]")
            assert public_host in {"93.184.216.34", "0.0.0.0"}
            payload = {**payload,"address":"127.0.0.1:"+payload["address"].rsplit(":",1)[1]}
        elif operation == "recover":
            assert all(candidate.startswith("93.184.216.34:") for candidate in payload["candidates"])
            payload = {**payload,"candidates":[candidate.replace("93.184.216.34:","127.0.0.1:") for candidate in payload["candidates"]]}
        elif operation == "migrate":
            self.migration_attempts += 1
            public_host = payload["address"].rsplit(":",1)[0].strip("[]")
            assert public_host == "93.184.216.34"
            payload = {**payload,"address":"127.0.0.1:0"}
        elif operation == "activate":
            assert all(candidate["host"] == "93.184.216.34" for candidate in payload["candidates"])
            payload = {**payload,"candidates":[{**candidate,"host":"127.0.0.1"} for candidate in payload["candidates"]]}
        if operation == "recover" and self.blocked:
            payload = {**payload,"candidates":["127.0.0.1:9" for _ in payload["candidates"]]}
        result = self.channel.request(operation,**payload)
        with self._lock:
            if operation in {"prepare", "prepare_recovery"}:
                actual = {key:result[key] for key in ("id","host","port","certificate")}
                assert actual["host"] == "127.0.0.1"
                self.owned[result["id"]] = (public_host,actual)
                result = {**result,"host":public_host}
            elif operation == "migrate":
                self.migrations += 1
                _, actual = self.owned[payload["id"]]
                self.owned[payload["id"]] = (public_host,{**actual,**result})
                result = {**result,"host":public_host}
            elif operation == "inspect":
                public_host, actual = self.owned[payload["id"]]
                assert result == actual  # Exact socket, port and key retained.
                result = {**result,"host":public_host}
            elif operation == "close":
                self.owned.pop(payload["id"],None)
        return result

    def retire(self):
        self.channel.retire()
        with self._lock:
            self.owned.clear()

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self.owned.clear()
        self.channel.close()
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=5)
        self._reader.join(timeout=2)
        self.process.stdin.close()
        self.process.stdout.close()
