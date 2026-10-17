import multiprocessing
import time
import uuid

import pytest
import RNS

from mesh_chat.direct_bootstrap import BootstrapEngine
from mesh_chat.errors import ValidationError


def _engine_worker(commands, replies, private_key, peer, workspace, directory):
    engine = None
    try:
        engine = BootstrapEngine(private_key, peer, workspace, int(time.time())+90, directory=directory)
        replies.put({"ok":True, "interfaces":len(RNS.Transport.interfaces),
                     "routing":RNS.Reticulum.transport_enabled()})
        while True:
            command, payload = commands.get()
            try:
                if command == "close":
                    break
                result = getattr(engine, command)(**payload)
                replies.put({"ok":True, "result":result})
            except Exception as exc:
                replies.put({"ok":False, "error":type(exc).__name__})
    finally:
        if engine:
            engine.close()


def test_bootstrap_rejects_shared_interpreter_before_creating_any_context(monkeypatch):
    monkeypatch.setattr(RNS.Reticulum, "get_instance", lambda: object())
    with pytest.raises(ValidationError, match="dedicated"):
        BootstrapEngine(b"x"*64, b"y"*64, str(uuid.uuid4()), int(time.time())+30)


@pytest.mark.parametrize("invalid", [True, 0, -1, 10**15, "30"])
def test_bootstrap_rejects_invalid_window(invalid):
    with pytest.raises(ValidationError):
        BootstrapEngine(b"x"*64, b"y"*64, str(uuid.uuid4()), invalid)


def test_real_isolated_engines_exchange_only_bootstrap_payloads(tmp_path):
    context = multiprocessing.get_context("spawn")
    identities = [RNS.Identity(), RNS.Identity()]
    workspace = str(uuid.uuid4())
    processes, commands, replies = [], [], []
    def call(index, command, **payload):
        commands[index].put((command,payload), timeout=2)
        return replies[index].get(timeout=5)
    try:
        for index in range(2):
            commands.append(context.Queue(maxsize=2))
            replies.append(context.Queue(maxsize=2))
            process = context.Process(target=_engine_worker, args=(commands[index], replies[index],
                identities[index].get_private_key(), identities[1-index].get_public_key(), workspace, str(tmp_path)))
            process.start()
            processes.append(process)
            assert replies[index].get(timeout=10) == {"ok":True,"interfaces":1,"routing":False}
        assert not call(0, "exchange", packets=[])["ok"]  # No packets before authentication.
        for index in range(2):
            assert call(index, "activate")["ok"]
        incoming = [[],[]]
        ready = [False,False]
        received = []
        def tick():
            for index in range(2):
                response = call(index, "exchange", packets=incoming[index])
                assert response["ok"], response
                incoming[index] = []
                result = response["result"]
                incoming[1-index].extend(result["packets"])
                ready[index] = result["recipient_ready"]
                received.extend((index,event) for event in result["events"])
            time.sleep(.02)
        deadline = time.monotonic()+15
        while not all(ready) and time.monotonic() < deadline:
            tick()
        assert all(ready)
        for kind in ("workspace_event", "workspace_channel_record", "workspace_channel_manifest"):
            assert not call(0, "send", kind=kind, logical_id=str(uuid.uuid4()),
                            document="not permitted", expires_at=int(time.time())+30)["ok"]
        # The parent remains responsible for validating the enclosed signed
        # application document. This fixture qualifies transport and scope only.
        assert call(0, "send", kind="workspace_join", logical_id=str(uuid.uuid4()),
                    document="parent-verifies-this-document", expires_at=int(time.time())+30)["ok"]
        deadline = time.monotonic()+20
        while not any(index == 1 and event["kind"] == "inbound" for index,event in received) and time.monotonic() < deadline:
            tick()
        inbound = [event for index,event in received if index == 1 and event["kind"] == "inbound"]
        assert len(inbound) == 1
        assert b"parent-verifies-this-document" in inbound[0]["packed"]
        assert not call(0, "exchange", packets=[b"x"]*33)["ok"]
        assert not call(0, "exchange", packets=[b"x"*517])["ok"]
    finally:
        for index, process in enumerate(processes):
            if process.is_alive():
                commands[index].put(("close",{}), timeout=2)
            process.join(5)
            if process.is_alive():
                process.terminate()
                process.join(3)
        for channel in commands+replies:
            channel.close()
            channel.join_thread()
    assert all(process.exitcode == 0 for process in processes)
