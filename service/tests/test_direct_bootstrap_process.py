import base64
import json
import time
import uuid
from pathlib import Path

import pytest
import RNS

from mesh_chat.direct_bootstrap_process import BootstrapProcess
from mesh_chat.direct_bootstrap_worker import BootstrapWorker, MAX_BYTES
from mesh_chat.errors import ValidationError


def test_desktop_child_owns_dedicated_interpreter_and_retires_on_error(tmp_path):
    local, peer = RNS.Identity(), RNS.Identity()
    child = BootstrapProcess(directory=tmp_path)
    temporary = Path(child._temporary.name)
    assert temporary.parent == tmp_path
    try:
        assert child.request("initialize", private_identity=local.get_private_key().hex(),
            peer_identity=peer.get_public_key().hex(), workspace_id=str(uuid.uuid4()),
            expires_at=int(time.time())+60) is None
        assert child.request("activate") is None
        result = child.request("exchange", packets=[])
        assert set(result) == {"packets", "events", "recipient_ready"}
        with pytest.raises(ValidationError):
            child.request("send", kind="workspace_event", logical_id=str(uuid.uuid4()),
                          document="forbidden", expires_at=int(time.time())+30)
        with pytest.raises(ValidationError):
            child.request("exchange", packets=[])
    finally:
        child.close()
        child._process.wait(timeout=5)
    deadline = time.monotonic()+5
    while temporary.exists() and time.monotonic() < deadline:
        time.sleep(.01)  # Cleanup deliberately runs outside service dispatch.
    assert not temporary.exists()


def test_desktop_bootstrap_requires_explicit_protected_workspace():
    with pytest.raises(TypeError):
        BootstrapProcess()


def test_desktop_spawn_failure_cleans_protected_temporary_directory(tmp_path, monkeypatch):
    import mesh_chat.direct_bootstrap_process as module
    def failed_spawn(*args, **kwargs):
        temporary = Path(kwargs["env"]["MESH_CHAT_BOOTSTRAP_DIRECTORY"])
        assert temporary.parent == tmp_path and temporary.is_dir()
        raise OSError("controlled spawn failure")
    monkeypatch.setattr(module.subprocess, "Popen", failed_spawn)
    with pytest.raises(OSError, match="controlled spawn failure"):
        BootstrapProcess(directory=tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("raw", ["[]", "null", "{}", "{", "x"*(MAX_BYTES+1),
    '{"operation":"packet_api","payload":{}}',
    '{"operation":"close","payload":{"private_identity":"secret"}}'],
    ids=["array","null","empty","malformed","oversized","unknown","extra-field"])
def test_worker_invalid_requests_are_content_free_and_terminal(raw):
    worker = BootstrapWorker(None)
    response = worker.call(raw)
    assert response == '{"ok":false,"error":"bootstrap_unavailable"}'
    assert worker.retired


def test_maximal_inbound_event_and_packets_fit_private_mobile_boundary():
    worker = BootstrapWorker(None)
    class Engine:
        def exchange(self, packets):
            return {"packets":[b"x"*516]*32,
                    "events":[{"kind":"inbound","packed":b"y"*(512*1024)}],"recipient_ready":True}
        def close(self):
            pass
    worker.engine = Engine()
    response = worker.call('{"operation":"exchange","payload":{"packets":[]}}')
    assert len(response.encode()) < MAX_BYTES
    value = json.loads(response)
    assert value["ok"] and len(base64.b64decode(value["result"]["events"][0]["packed"])) == 512*1024
