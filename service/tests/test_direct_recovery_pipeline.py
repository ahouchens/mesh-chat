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


_RECOVERY_STATES = frozenset({"connected", "connection_update_needed", "reconnecting", "paused", "failed"})
_EVENT_STATES = ("queued", "waiting_for_keys", "sending", "stored_for_delivery",
    "received_by_endpoint", "delivered", "failed", "expired", "cancelled", "unknown")
_EVENT_TRACE_OUTCOMES = {
    "preflight": frozenset({"ready", "waiting", "recipient_keys_unavailable", "network_unavailable",
                            "other_mesh_error", "other_error"}),
    "send": frozenset({"accepted", "recipient_keys_unavailable", "network_unavailable",
                       "other_mesh_error", "other_error", "unknown"}),
    "status": frozenset({"handled", "unhandled"}),
    "ingress": frozenset({"observed"}),
    "acceptance": frozenset({"accepted", "deferred_or_rejected", "error", "unknown"}),
}
_EVENT_READINESS = ("bootstrap_ready", "bootstrap_handles", "main_identity", "main_ratchet", "main_path")
_EVENT_SCHEDULES = frozenset({"due", "future", "terminal", "unknown"})
_EVENT_FAILURES = frozenset({"none", "identity_binding_invalid", "transport_unavailable", "transport_error", "unknown"})


def _fixed_count(value, limit):
    return min(value, limit) if type(value) is int and value >= 0 else None


def _event_trace_snapshot(value):
    if type(value) not in (list, tuple): return {"entries": [], "malformed": True}
    entries, malformed = [], len(value) > 16
    for row in value[-16:]:
        if type(row) is not dict or type(row.get("stage")) is not str or row["stage"] not in _EVENT_TRACE_OUTCOMES:
            malformed = True
            continue
        stage = row["stage"]
        if type(row.get("outcome")) is not str or row["outcome"] not in _EVENT_TRACE_OUTCOMES[stage]:
            malformed = True
            continue
        entry = {"stage": stage, "outcome": row["outcome"]}
        if stage in {"preflight", "send"}:
            entry.update({name: row.get(name) if type(row.get(name)) is bool else None for name in _EVENT_READINESS})
        if stage == "status":
            state = row.get("state")
            entry["state"] = state if type(state) is str and state in _EVENT_STATES else "unknown"
        entries.append(entry)
    return {"entries": entries, "malformed": malformed}


def _event_delivery_snapshot(value):
    """Select at most eight event rows from the already-bounded delivery projection."""
    if type(value) not in (list, tuple): return {"entries": [], "truncated": False, "malformed": True}
    entries, malformed = [], False
    truncated = len(value) > 64
    for row in value[:64]:
        if type(row) is not dict:
            malformed = True
            continue
        kind = row.get("kind")
        if kind != "workspace_event":
            if type(kind) is not str: malformed = True
            continue
        if len(entries) == 8:
            truncated = True
            continue
        state, schedule, failure = row.get("state"), row.get("schedule"), row.get("failure")
        attempts = row.get("attempts")
        capped = row.get("attempts_capped")
        native_present = row.get("native_message_id_present")
        if (type(state) is not str or state not in _EVENT_STATES
                or type(schedule) is not str or schedule not in _EVENT_SCHEDULES
                or type(failure) is not str or failure not in _EVENT_FAILURES
                or (attempts is not None and (type(attempts) is not int or attempts < 0))
                or type(capped) is not bool or type(native_present) is not bool):
            malformed = True
        entries.append({
            "state": state if type(state) is str and state in _EVENT_STATES else "unknown",
            "attempts": _fixed_count(attempts, 32),
            "attempts_capped": capped if type(capped) is bool else None,
            "schedule": schedule if type(schedule) is str and schedule in _EVENT_SCHEDULES else "unknown",
            "native_message_id_present": native_present if type(native_present) is bool else None,
            "failure": failure if type(failure) is str and failure in _EVENT_FAILURES else "unknown",
        })
    return {"entries": entries, "truncated": truncated, "malformed": malformed}


def _recovery_failure_snapshot(value):
    """Bounded test-only failure context; never copy source identifiers or text."""
    if type(value) is not dict: return {"available": False}
    rows = value.get("peers")
    if type(rows) not in (list, tuple): rows = []
    peer_states = []
    for row in rows[:2]:
        row = row if type(row) is dict else {}
        state = row.get("state")
        peer_states.append({"state": state if type(state) is str and state in _RECOVERY_STATES else "unknown",
            "authenticated_peer_live": row.get("authenticated_peer_live") if type(row.get("authenticated_peer_live")) is bool else None,
            "rns_ready": row.get("rns_ready") if type(row.get("rns_ready")) is bool else None})
    workspace = value.get("workspace_bootstrap")
    workspace = workspace if type(workspace) is dict else {}
    states = workspace.get("workspace_event_states")
    states = states if type(states) is dict else {}
    tables = workspace.get("tables")
    tables = tables if type(tables) is dict else {}
    delivery_table = tables.get("workspace_delivery")
    delivery_table = delivery_table if type(delivery_table) is dict else {}
    if delivery_table.get("unavailable") is True:
        scan = "unavailable"
    elif delivery_table.get("truncated") is True or _fixed_count(delivery_table.get("malformed_rows"), 64):
        scan = "partial"
    elif (delivery_table.get("unavailable") is False and delivery_table.get("truncated") is False
            and type(delivery_table.get("malformed_rows")) is int and delivery_table["malformed_rows"] == 0):
        scan = "complete"
    else:
        scan = "unknown"
    workspaces = workspace.get("workspaces")
    first = workspaces[0] if type(workspaces) is list and workspaces and type(workspaces[0]) is dict else {}
    discovery = first.get("channel_discovery")
    return {"available": True, "peer_states": peer_states, "peer_states_truncated": len(rows) > 2,
        "pending": _fixed_count(value.get("pending"), 32),
        "pending_capped": type(value.get("pending")) is int and value["pending"] > 32,
        "channel_discovery": discovery if type(discovery) is str and discovery in {"converged", "incomplete"} else "unknown",
        "workspace_event_scan": scan,
        "workspace_event_states": {name: _fixed_count(states.get(name), 64) for name in _EVENT_STATES},
        "workspace_event_deliveries": _event_delivery_snapshot(workspace.get("deliveries")),
        "workspace_event_trace": _event_trace_snapshot(value.get("workspace_event_trace"))}


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

    def call(self, index, operation, *, _diagnostic_timeout=None, **payload):
        self.commands[index].put((operation,payload),timeout=2 if _diagnostic_timeout is None else _diagnostic_timeout)
        response = self.replies[index].get(timeout=20 if _diagnostic_timeout is None else _diagnostic_timeout)
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
        # The original timeout remains authoritative. Optional test-only
        # snapshots use at most one second per queue operation on each peer.
        diagnostics=[]
        for peer in range(2):
            try: diagnostics.append(_recovery_failure_snapshot(
                self.call(peer,"recovery_diagnostic",_diagnostic_timeout=1)))
            except Exception: diagnostics.append({"available":False})
        raise AssertionError((index,name,last,{"peers":diagnostics}))

    def connected(self, index, previous_certificate=None):
        # One total bound includes the configured native attempt and retry window.
        # A usable old Phase 2/path is not evidence that recovery has completed.
        # The specification allows 240 seconds for post-partition recovery.
        # Windows CI can be heavily loaded; 180 seconds stays inside that bound
        # while avoiding a false product failure when recovery is merely slow.
        deadline=time.monotonic()+180
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
