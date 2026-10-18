"""CI-only production recovery, real QUIC, isolated RNS and encrypted restarts.

Synthetic candidates resolve only to loopback in AppHostNative. No physical
router, Internet traversal or Android lifecycle result is inferred.
"""
import multiprocessing
import os
import time
import uuid

import pytest

from test_direct_setup_pipeline import _service_worker


class Peers:
    def __init__(self, root, binary, unhosted=False):
        self.root, self.binary = root, binary
        self.unhosted = unhosted
        self.context = multiprocessing.get_context("spawn")
        self.pipes = [self.context.Queue(maxsize=128) for _ in range(2)]
        self.commands, self.replies, self.processes = [None]*2, [None]*2, [None]*2
        self.channels = list(self.pipes)
        self.keys = [os.urandom(32) for _ in range(2)]  # Python-only test custodian.

    def start(self, index):
        self.commands[index], self.replies[index] = [self.context.Queue(maxsize=2) for _ in range(2)]
        self.channels.extend((self.commands[index], self.replies[index]))
        process = self.context.Process(target=_service_worker,args=(str(self.root/str(index)),
            self.pipes[index],self.pipes[1-index],self.commands[index],self.replies[index],
            self.binary,False,self.unhosted and index==1,self.keys[index]))
        process.start()
        self.processes[index] = process
        assert self.replies[index].get(timeout=20)["ok"]

    def call(self, index, operation, **payload):
        self.commands[index].put((operation,payload),timeout=2)
        response = self.replies[index].get(timeout=20)
        assert response["ok"], response
        return response.get("result")

    def command(self, index, command_name, **payload):
        return self.call(index,"command",command=command_name,payload=payload)

    def wait(self, index, name, predicate, *, timeout=45, **payload):
        deadline=time.monotonic()+timeout
        last=None
        while time.monotonic()<deadline:
            last=self.command(index,name,**payload)
            result=predicate(last)
            if result: return result
            time.sleep(.2)
        raise AssertionError((index,name,last,self.call(index,"recovery_diagnostic")))

    def connected(self, index, previous_certificate=None):
        # One total bound includes the configured native attempt and retry window.
        # A usable old Phase 2/path is not evidence that recovery has completed.
        deadline=time.monotonic()+100
        evidence=None
        while time.monotonic()<deadline:
            rows=self.command(index,"direct_recovery_status")
            evidence=self.call(index,"recovery_diagnostic")
            if (rows and all(r["state"]=="connected" and r["authenticated_peer_live"] and r["rns_ready"] for r in rows)
                    and evidence["pending"]==0 and len(evidence["paths"])==1
                    and evidence["paths"][0]["recovery"]
                    and evidence["paths"][0]["certificate"]!=previous_certificate):
                return evidence
            time.sleep(.2)
        raise AssertionError({"failed_peer":index,"peers":[self.call(i,"recovery_diagnostic") for i in range(2)]})

    def admit(self):
        op=lambda:str(uuid.uuid4())
        workspace=self.command(0,"create_workspace",operation_id=op(),name="Durable recovery",description="")
        self.workspace=workspace
        invite=self.command(0,"create_workspace_invitation",operation_id=op(),workspace_id=workspace["id"])
        offer=self.call(0,"offer",invitation_id=invite["id"])
        answer=self.call(1,"answer",document=offer["text"],operation_id=op())
        ready=self.call(0,"ready",document=answer["text"])
        self.call(1,"accept_ready",document=ready["text"])
        for index,setup in enumerate((ready,answer)):
            self.call(index,"connect",setup_id=setup["setup_id"],document=ready["text"])
        request=self.wait(0,"workspace_snapshot",lambda snap:next((r for r in snap["workspace_join_requests"] if r["state"]=="pending"),None))
        self.wait(1,"workspace_snapshot",lambda snap:any(w.get("join_acknowledged") for w in snap["workspaces"]))
        self.command(0,"approve_workspace_join",operation_id=op(),workspace_id=workspace["id"],request_id=request["id"])
        self.wait(1,"workspace_snapshot",lambda snap:any(w["id"]==workspace["general_channel_id"] for w in snap["workspace_channels"]))
        return [self.connected(i) for i in range(2)]

    def send(self, index, text):
        return self.command(index,"send_workspace_message",operation_id=str(uuid.uuid4()),event_id=str(uuid.uuid4()),
            workspace_id=self.workspace["id"],channel_id=self.workspace["general_channel_id"],text=text)

    def delivered(self, sender, sent):
        args=dict(workspace_id=self.workspace["id"],channel_id=self.workspace["general_channel_id"],limit=50)
        self.wait(1-sender,"list_workspace_messages",lambda page:len([m for m in page["messages"] if m["id"]==sent["id"]])==1,**args)
        self.wait(sender,"list_workspace_messages",lambda page:any(m["id"]==sent["id"] and
            m.get("delivery_summary",{}).get("devices_reached")==1 for m in page["messages"]),**args)

    def crash(self,index):
        self.commands[index].put(("crash",{}),timeout=2)
        self.processes[index].join(10)
        assert self.processes[index].exitcode==91

    def close(self):
        for index,process in enumerate(self.processes):
            if process is None: continue
            if process.is_alive(): self.commands[index].put(("close",{}),timeout=2)
            process.join(10)
            if process.is_alive(): process.terminate(); process.join(3)
        for channel in self.channels:
            channel.close(); channel.cancel_join_thread()


@pytest.mark.integration
@pytest.mark.parametrize("scenario",["replacement","route_change","server_route_change","blocked","address_loss","client_restart","server_restart","both_restart","unhosted_restart","suspend"])
def test_production_durable_recovery(tmp_path,scenario):
    binary=os.environ.get("MESH_DIRECT_APP_HOST_BINARY")
    if not binary: pytest.skip("Requires the GitHub-built shipping dispatcher")
    peers=Peers(tmp_path,binary,unhosted=scenario=="unhosted_restart")
    try:
        for i in range(2): peers.start(i)
        before=peers.admit()
        identities=[item["identity"] for item in before]
        assert len(before[1]["application_receipts"])==1
        snapshots=[peers.command(i,"workspace_snapshot") for i in range(2)]
        memberships=[[(w["id"],w["local_member_id"],w["local_device_id"]) for w in s["workspaces"]] for s in snapshots]
        client=1 if scenario=="unhosted_restart" else 0 if identities[0]<identities[1] else 1
        changed=[0,1]
        if scenario.endswith("restart"):
            changed=[client] if scenario in {"client_restart","unhosted_restart"} else [1-client] if scenario=="server_restart" else [0,1]
            for i in changed: peers.crash(i)
            if len(changed)==1: queued=(1-changed[0],peers.send(1-changed[0],"Queued across peer process death"))
            time.sleep(1)  # Native owner detects inherited-channel EOF and retires sockets.
            for i in changed: peers.start(i)
        elif scenario=="suspend":
            peers.command(1,"mobile_lifecycle_transition",state="suspended",reason="controlled_sleep")
            assert peers.call(1,"diagnostic")=={"native_count":0,"interfaces":0}
            queued=(0,peers.send(0,"Queued during suspension"))
            peers.command(1,"mobile_lifecycle_transition",state="foreground",reason="controlled_resume")
            changed=[1]
        elif scenario in {"route_change","server_route_change"}:
            changed_peer=client if scenario=="route_change" else 1-client
            peers.call(changed_peer,"route_change")
            time.sleep(6)
            changed=[]  # Successful client migration keeps its authenticated key.
        elif scenario in {"blocked","address_loss"}:
            for i in range(2): peers.call(i,"force_recovery",retire=True,blocked=scenario=="blocked",lose_addresses=scenario=="address_loss")
            queued=(0,peers.send(0,"Queued without reachable path"))
            for i in range(2):
                peers.wait(i,"direct_recovery_status",lambda rows:rows and rows[0]["state"]=="connection_update_needed" and not rows[0]["authenticated_peer_live"],timeout=90)
            if scenario=="blocked":
                for i in range(2): peers.call(i,"force_recovery",retire=True,blocked=False)
            else:
                # Explicit fresh updates carry signed hints, never another invitation.
                documents=[]
                for i in range(2):
                    identifier=peers.command(i,"direct_recovery_status")[0]["relationship_id"]
                    documents.append(peers.wait(i,"export_recovery_update",lambda value:value.get("text"),identifier=identifier))
                for i in range(2): peers.command(i,"import_recovery_update",document=documents[1-i],workspace_id=peers.workspace["id"])
        else:
            for i in range(2): peers.call(i,"force_recovery")
        if scenario=="replacement": time.sleep(2)
        after=[peers.connected(i,before[i]["paths"][0]["certificate"] if i in changed else None) for i in range(2)]
        if scenario=="replacement":
            assert all(after[i]["controls"]["received"]>before[i]["controls"]["received"] for i in range(2))
        if scenario in {"route_change","server_route_change"}:
            assert after[changed_peer]["migration_attempts"]>before[changed_peer]["migration_attempts"]
            if after[changed_peer]["migrations"]>before[changed_peer]["migrations"]:
                assert after[changed_peer]["paths"][0]["certificate"]==before[changed_peer]["paths"][0]["certificate"]
            else:
                assert after[changed_peer]["paths"][0]["certificate"]!=before[changed_peer]["paths"][0]["certificate"]
        for i in range(2):
            assert after[i]["identity"]==identities[i]
            assert after[i]["application_receipts"]==before[i]["application_receipts"]
            if i in changed: assert after[i]["paths"][0]["certificate"]!=before[i]["paths"][0]["certificate"]
            snapshot=peers.command(i,"workspace_snapshot")
            assert [(w["id"],w["local_member_id"],w["local_device_id"]) for w in snapshot["workspaces"]]==memberships[i]
            assert not any(r["state"]=="pending" for r in snapshot["workspace_join_requests"])
            evidence=peers.call(i,"relationship_evidence")
            assert len(evidence)==1 and evidence[0]["last_success"]["generation"]<=evidence[0]["accepted"]["generation"]
            assert after[i]["native_count"]==1
        if "queued" in locals(): peers.delivered(*queued)
        for i in range(2): peers.delivered(i,peers.send(i,"Bidirectional message after "+scenario))
        for i in range(2):
            identifier=peers.command(i,"direct_recovery_status")[0]["relationship_id"]
            peers.command(i,"pause_direct_recovery",identifier=identifier)
            assert peers.call(i,"diagnostic")=={"native_count":0,"interfaces":0}
    finally:
        peers.close()
