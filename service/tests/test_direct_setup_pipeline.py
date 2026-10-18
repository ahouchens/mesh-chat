"""Production setup/handoff with real isolated RNS and two controlled carriers.

Source pipes qualify orchestration; the CI-only shipping dispatcher adds real
QUIC. Neither qualifies physical router reachability or Android devices.
"""
import multiprocessing
import os
from pathlib import Path
import queue
import socket
import threading
import time
import uuid

import pytest


class PipeNative:
    def __init__(self, incoming, outgoing, delay_admission=False):
        self.incoming, self.outgoing = incoming, outgoing
        self.lock = threading.RLock()
        self.owned, self.remote, self.next = {}, {}, 0
        self.delay_admission = delay_admission
        self.admission_visible_at = None

    def request(self, operation, **payload):
        with self.lock:
            while True:
                try:
                    event = self.incoming.get_nowait()
                except queue.Empty:
                    break
                if event[0] == "activate":
                    self.remote[event[1]] = event[2]
                elif event[0] == "close":
                    self.remote.pop(event[1],None)
                elif event[1] in self.owned:
                    packets = self.owned[event[1]]["packets"]
                    if len(packets) < 32:
                        packets.append(event[2])
            if operation == "prepare":
                self.next += 1
                host = payload["address"].rsplit(":",1)[0].strip("[]")
                value = {"id":self.next,"host":host,"port":45000+self.next,
                    "session":str(uuid.uuid4()),"generation":payload["generation"],
                    "certificate":str(self.next).encode().hex()}
                self.owned[self.next] = {"public":value,"peer":None,"packets":[],"online":False}
                return dict(value)
            if operation == "close":
                self.owned.pop(payload["id"],None)
                self.outgoing.put(("close",payload["id"]),timeout=1)
                return None
            record = self.owned[payload["id"]]
            if operation == "inspect":
                return {key:record["public"][key] for key in ("id","host","port","certificate")}
            if operation in {"arm","rearm"}:
                return None
            if operation == "activate":
                record["peer"] = int(bytes.fromhex(payload["certificate"]).decode())
                self.outgoing.put(("activate",payload["id"],record["peer"]),timeout=1)
                return None
            online = self.remote.get(record["peer"]) == payload["id"]
            if operation == "poll":
                # The peer observes QUIC authentication before this service
                # installs its admitted RNS adapter. Bootstrap must stay alive
                # during that gap, or channel bootstrap never completes.
                if online and self.delay_admission and payload["id"] == 2:
                    if self.admission_visible_at is None:
                        self.admission_visible_at = time.monotonic()+1.5
                    if time.monotonic() < self.admission_visible_at:
                        return {"state":0,"packets":[]}
                state = 1 if online else 2 if record["online"] else 0
                record["online"] = record["online"] or online
                packets, record["packets"] = record["packets"], []
                return {"state":state,"packets":packets}
            if operation == "send":
                assert online
                for packet in payload["packets"]:
                    self.outgoing.put(("packet",record["peer"],packet),timeout=1)
                return None
            raise ValueError("unknown fake native operation")

    def close(self):
        with self.lock:
            for identifier in list(self.owned):
                self.request("close", id=identifier)

    retire = close


def _service_worker(root, incoming, outgoing, commands, replies, native_binary=None, delay_admission=False, unhosted=False, vault_key=None):
    from mesh_chat import connectivity as c
    from mesh_chat.reticulum_config import NetworkSettings
    from mesh_chat.service import MeshChatService
    from mesh_chat.vault import VaultStore
    c.default_routes = lambda: [c.RouteInfo(socket.AF_INET,"controlled","192.168.1.1","93.184.216.34",1)]
    if unhosted:
        c.default_routes = lambda: []
    store = VaultStore(Path(root), vault_key or os.urandom(32), allow_unprotected_for_tests=True)
    store.put("settings","network",NetworkSettings(nearby_discovery=False,lan_fallback=False).to_dict())
    if native_binary:
        from direct_app_host_fixture import AppHostNative
        native = AppHostNative(native_binary)
    else:
        native = PipeNative(incoming,outgoing,delay_admission)
    service = MeshChatService(store,Path(root),lambda _:None,direct_native=native)
    try:
        service.create_profile("Controlled peer")
        replies.put({"ok":True})
        while True:
            operation, payload = commands.get()
            if operation == "close":
                break
            if operation == "crash":
                os._exit(91)
            try:
                with service._dispatch_lock:
                    if operation == "command":
                        result, _ = service.dispatch({"v":1,"id":str(uuid.uuid4()),**payload})
                        result = result["result"]
                    elif operation == "diagnostic":
                        import RNS
                        result = {"native_count":len(service._direct_native.owned),
                                  "interfaces":len(RNS.Transport.interfaces)}
                    elif operation == "recovery_diagnostic":
                        import hashlib
                        from mesh_chat.invitations import canonical_bytes
                        result = {"peers":service._direct_recovery.status(),
                            "identity":service.network.destination_hash.hex(),
                            "migration_attempts":getattr(native,"migration_attempts",0),"migrations":getattr(native,"migrations",0),
                            "application_receipts":[hashlib.sha256(canonical_bytes(w["join_receipt"])).hexdigest()
                                for w in store.list("workspace") if w.get("join_receipt")],
                            "paths":[{"recovery":carrier.recovery,"certificate":hashlib.sha256(bytes.fromhex(carrier.prepared._owned["certificate"])).hexdigest()}
                                     for carrier in service._direct_recovery._active.values() if not carrier._stop.is_set()],
                            "pending":len(service._direct_recovery._pending),"native_count":len(native.owned),
                            "failures":[{key:value.get(key) for key in ("failure_stage","failure_type","attempts","state")}
                                        for value in store.list("direct_recovery")]}
                    elif operation == "force_recovery":
                        if payload.get("retire"):
                            service._direct_recovery.retire()
                        if "blocked" in payload:
                            native.blocked = payload["blocked"]
                        for identifier, record in store.items("direct_relationship"):
                            if payload.get("lose_addresses"):
                                saved=service._direct_recovery._state(identifier).get("local")
                                assert saved
                                saved["socket_hint"]={**saved["socket_hint"],"port":0}
                                service._direct_recovery._write(identifier,local=saved)
                            service._direct_recovery._write(identifier,next_at=time.time(),
                                attempts=6 if payload.get("blocked") or payload.get("lose_addresses") else 0,state="reconnecting")
                        service._direct_recovery._wake.set()
                        result = None
                    elif operation == "route_change":
                        c.default_routes = lambda: [c.RouteInfo(socket.AF_INET,"changed","192.168.2.1","93.184.216.34",1)]
                        service._direct_recovery._route_check_at=0
                        result = None
                    elif operation == "relationship_evidence":
                        records = store.list("direct_relationship")
                        result = [{"scope": item["scope"], "accepted": item["accepted"],
                                   "last_success": item["last_success"]} for item in records]
                    else:
                        names = {"offer":"prepare_direct_offer", "answer":"prepare_direct_answer",
                            "ready":"prepare_direct_ready", "accept_ready":"accept_direct_ready",
                            "connect":"connect_direct_setup", "status":"direct_setup_status"}
                        result, _ = service.dispatch({"v":1,"id":str(uuid.uuid4()),
                            "command":names[operation],"payload":payload})
                        result = result["result"]
                replies.put({"ok":True,"result":result})
            except Exception as exc:
                replies.put({"ok":False,"error":type(exc).__name__+":"+str(exc)})
    finally:
        service.close()
        native.close()


@pytest.mark.integration
@pytest.mark.parametrize("retirement", ["cancel", "suspend", "revocation"])
@pytest.mark.parametrize("carrier_mode", ["source", "native"])
@pytest.mark.parametrize("unhosted_joiner", [False, True], ids=["both_hosted", "unhosted_joiner"])
def test_production_setup_bootstrap_admission_and_fresh_workspace_path(tmp_path, retirement, carrier_mode, unhosted_joiner):
    native_binary = os.environ.get("MESH_DIRECT_APP_HOST_BINARY") if carrier_mode == "native" else None
    if carrier_mode == "native" and not native_binary:
        pytest.skip("Requires the GitHub-built shipping native dispatcher harness")
    context = multiprocessing.get_context("spawn")
    pipes = [context.Queue(maxsize=128),context.Queue(maxsize=128)]
    commands, replies, processes = [], [], []
    def call(index, operation, **payload):
        commands[index].put((operation,payload),timeout=2)
        response = replies[index].get(timeout=15)
        assert response["ok"], response
        return response.get("result")
    def command(index, command_name, **payload):
        return call(index,"command",command=command_name,payload=payload)
    def wait(index, name, predicate, **payload):
        deadline = time.monotonic()+25
        last = None
        while time.monotonic() < deadline:
            last = command(index,name,**payload)
            result = predicate(last)
            if result:
                return result
            time.sleep(.1)
        raise AssertionError((name,last))
    op = lambda: str(uuid.uuid4())
    try:
        for index in range(2):
            commands.append(context.Queue(maxsize=2))
            replies.append(context.Queue(maxsize=2))
            process = context.Process(target=_service_worker,args=(str(tmp_path/str(index)),pipes[index],
                pipes[1-index],commands[index],replies[index],native_binary,index == 1,unhosted_joiner and index == 1))
            process.start()
            processes.append(process)
            assert replies[index].get(timeout=15)["ok"]
        workspace = command(0,"create_workspace",operation_id=op(),name="Production setup",description="")
        invite = command(0,"create_workspace_invitation",operation_id=op(),workspace_id=workspace["id"])
        offer = call(0,"offer",invitation_id=invite["id"])
        answer = call(1,"answer",document=offer["text"],operation_id=op())
        assert answer["candidate_count"] == (0 if unhosted_joiner else 1)
        ready = call(0,"ready",document=answer["text"])
        call(1,"accept_ready",document=ready["text"])
        for index, setup in enumerate((ready,answer)):
            assert call(index,"connect",setup_id=setup["setup_id"],document=ready["text"])["state"] == "connecting"
        request = wait(0,"workspace_snapshot",lambda snap:next((item for item in snap["workspace_join_requests"]
            if item["state"] == "pending"),None))
        wait(1,"workspace_snapshot",lambda snap:any(item.get("join_acknowledged") for item in snap["workspaces"]))
        command(0,"approve_workspace_join",operation_id=op(),workspace_id=workspace["id"],request_id=request["id"])
        wait(1,"workspace_snapshot",lambda snap:any(item["state"] == "active" for item in snap["workspaces"]))
        wait(1,"workspace_snapshot",lambda snap:any(item["id"] == workspace["general_channel_id"] for item in snap["workspace_channels"]))
        for index, setup in enumerate((ready,answer)):
            assert call(index,"status",setup_id=setup["setup_id"])["state"] in {"admitted_path","relationship_active"}
        for sender, recipient in ((0,1),(1,0)):
            sent = command(sender,"send_workspace_message",operation_id=op(),event_id=op(),workspace_id=workspace["id"],
                channel_id=workspace["general_channel_id"],text="Fresh admitted path")
            wait(recipient,"list_workspace_messages",lambda page:any(item["id"] == sent["id"] for item in page["messages"]),
                workspace_id=workspace["id"],channel_id=workspace["general_channel_id"],limit=50)
            wait(sender,"list_workspace_messages",lambda page:any(item["id"] == sent["id"] and
                item.get("delivery_summary",{}).get("devices_reached") == 1 for item in page["messages"]),
                workspace_id=workspace["id"],channel_id=workspace["general_channel_id"],limit=50)
        for index in range(2):
            evidence = call(index, "relationship_evidence")
            assert len(evidence) == 1
            assert evidence[0]["scope"]["workspace_id"] == workspace["id"]
            assert evidence[0]["last_success"] is not None
            # A newly accepted replacement can coexist with the authenticated old path.
            assert evidence[0]["last_success"]["generation"] <= evidence[0]["accepted"]["generation"]
            if evidence[0]["last_success"]["generation"] == evidence[0]["accepted"]["generation"]:
                assert evidence[0]["last_success"]["digest"] == evidence[0]["accepted"]["digest"]
        if retirement == "cancel":
            command(0,"cancel_direct_setup",setup_id=ready["setup_id"])
        elif retirement == "suspend":
            command(0,"mobile_lifecycle_transition",state="suspended",reason="controlled_test")
        else:
            member = next(item for item in command(1,"workspace_snapshot")["workspaces"] if item["id"] == workspace["id"])
            command(0,"remove_workspace_member",operation_id=op(),workspace_id=workspace["id"],member_id=member["local_member_id"])
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            diagnostic = call(0,"diagnostic")
            if diagnostic == {"native_count":0,"interfaces":0}:
                break
            time.sleep(.05)
        assert diagnostic == {"native_count":0,"interfaces":0}
    finally:
        for index, process in enumerate(processes):
            if process.is_alive():
                commands[index].put(("close",{}),timeout=2)
            process.join(8)
            if process.is_alive():
                process.terminate()
                process.join(3)
        for channel in pipes+commands+replies:
            channel.close()
            channel.cancel_join_thread()
    assert all(process.exitcode == 0 for process in processes)
