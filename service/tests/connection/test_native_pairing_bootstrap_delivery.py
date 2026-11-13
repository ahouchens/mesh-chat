"""Two real native/RNS peers; source component evidence, not packaged proof."""
import multiprocessing
from pathlib import Path
import queue
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

import pytest

HARNESS = Path(__file__).resolve().parents[2] / "tools" / "connection_harness"
sys.path.insert(0, str(HARNESS))
from packaged_pairing_probe import exercise
from packaged_transport_probe import Controller


def _peer(commands, replies):
    from mesh_chat.native_windows_webrtc import WindowsNativeWebRTCHost
    from mesh_chat.service import MeshChatService
    from mesh_chat.vault import VaultStore
    import base64

    service = None
    counts = {}

    class CountingHost(WindowsNativeWebRTCHost):
        def createOffer(self, *args, **kwargs):
            counts["createOffer"] = counts.get("createOffer", 0) + 1
            return super().createOffer(*args, **kwargs)

        def acceptOffer(self, *args, **kwargs):
            counts["acceptOffer"] = counts.get("acceptOffer", 0) + 1
            return super().acceptOffer(*args, **kwargs)

        def applyAnswer(self, *args, **kwargs):
            counts["applyAnswer"] = counts.get("applyAnswer", 0) + 1
            return super().applyAnswer(*args, **kwargs)

        def close(self, *args, **kwargs):
            counts["close"] = counts.get("close", 0) + 1
            return super().close(*args, **kwargs)

    host = CountingHost(lambda *event: service.native_webrtc_event(*event) if service else None)
    try:
        while True:
            action, arguments = commands.get()
            if action == "stop":
                break
            if action == "counts":
                replies.put({"ok": True, "result": dict(counts)})
                continue
            command, payload = arguments["command"], arguments["payload"]
            if command == "initialize":
                store = VaultStore(Path(payload["profile_dir"]), base64.b64decode(payload["vault_key"]), allow_unprotected_for_tests=True)
                service = MeshChatService(store, store.profile_dir, lambda _: None,
                    native_webrtc_host=host, connection_policy="shared-native")
                result = {"ok": True, "result": service.snapshot()}
            else:
                try:
                    result, _ = service.dispatch({"v": 1, "id": str(uuid4()),
                        "command": command, "payload": payload})
                except Exception as exc:
                    result = {"ok": False, "error": {"code": getattr(exc, "code", type(exc).__name__)}}
            replies.put(result)
    except BaseException as exc:
        replies.put({"ok": False, "error": {"code": type(exc).__name__}})
        raise
    finally:
        if service:
            service.close()
        host.shutdown()


class SourceController(Controller):
    def __init__(self):
        self.phase, self.checks, self.error_code = "fixture", [], None
        self.counts = {"processes_started": 0, "forced_exits": 0, "authenticated_receipts": 0}
        self.peers = {}
        self.previous_counts = {}

    def _response(self, slot, action, **arguments):
        if action == "start":
            commands, replies = multiprocessing.Queue(), multiprocessing.Queue()
            process = multiprocessing.Process(target=_peer, args=(commands, replies))
            process.start()
            self.peers[slot] = process, commands, replies
            return {"ok": True, "result": {}}
        process, commands, replies = self.peers[slot]
        if action in {"stop", "crash"}:
            if process.is_alive() and action == "crash":
                self.previous_counts[slot] = self._response(slot, "counts")["result"]
            if action == "crash":
                process.terminate()
            elif process.is_alive():
                commands.put(("stop", {}))
            process.join(10)
            if process.is_alive():
                process.terminate()
                process.join(5)
                raise AssertionError("source peer did not acknowledge shutdown")
            if action == "stop":
                assert process.exitcode == 0, "source peer exited abnormally"
            return {"ok": True, "result": {}}
        commands.put((action, arguments))
        try:
            response = replies.get(timeout=30)
        except queue.Empty:
            raise AssertionError((self.phase, "source peer did not reply", process.exitcode))
        if not response["ok"]:
            response["error"] = response["error"]["code"]
        if action == "counts":
            previous = self.previous_counts.get(slot, {})
            response["result"] = {key: previous.get(key, 0) + response["result"].get(key, 0)
                for key in previous.keys() | response["result"].keys()}
        return response


@pytest.mark.integration
def test_shared_native_first_contact_keeps_approved_carrier_and_delivers_receipts(tmp_path_factory, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["source-component", "1"])
    import packaged_pairing_probe, packaged_transport_probe
    from mesh_chat.vault import VaultStore
    test_store = lambda *args: VaultStore(*args, allow_unprotected_for_tests=True)
    monkeypatch.setattr(packaged_pairing_probe, "VaultStore", test_store)
    monkeypatch.setattr(packaged_transport_probe, "VaultStore", test_store)
    controller = SourceController()
    try:
        with TemporaryDirectory(prefix="pc-", dir=tmp_path_factory.getbasetemp()) as directory:
            exercise(controller, Path(directory))
    except Exception as exc:
        exc.add_note(f"{controller.phase}: {controller.error_code or 'condition_failed'}")
        raise
    assert "continuous_pairing_carrier_transfer" in controller.checks
    assert controller.counts["authenticated_receipts"] == 2

