"""CI-only production recovery, real QUIC, isolated RNS and encrypted restarts.

Synthetic candidates resolve only to loopback in AppHostNative. No physical
router, Internet traversal or Android lifecycle result is inferred.
"""
import json
import multiprocessing
import os
import time
import uuid
from queue import Empty

import pytest

import direct_timeout_probe as timeout_probe
from test_direct_setup_pipeline import _service_worker


_RECOVERY_STATES = frozenset({"connected", "connection_update_needed", "reconnecting", "paused", "failed"})
_EVENT_STATES = ("queued", "waiting_for_keys", "sending", "stored_for_delivery",
    "received_by_endpoint", "delivered", "failed", "expired", "cancelled", "unknown")
_EVENT_TRACE_OUTCOMES = {
    "preflight": frozenset({"ready", "waiting", "recipient_keys_unavailable", "network_unavailable",
                            "other_mesh_error", "other_error"}),
    "send": frozenset({"accepted", "recipient_keys_unavailable", "network_unavailable",
                       "other_mesh_error", "other_error", "unknown"}),
    "status": frozenset({"returned_true", "returned_false", "unknown"}),
    "ingress": frozenset({"observed"}),
    "acceptance": frozenset({"returned_true", "returned_false", "error", "unknown"}),
}
_EVENT_READINESS = ("bootstrap_ready", "bootstrap_handles", "main_identity", "main_ratchet", "main_path")
_EVENT_SCHEDULES = frozenset({"due", "future", "terminal", "unknown"})
_EVENT_FAILURES = frozenset({"none", "identity_binding_invalid", "transport_unavailable", "transport_error", "unknown"})
_NATIVE_STATES = frozenset({"outbound", "sending", "sent", "delivered", "failed", "rejected", "cancelled", "unknown"})
_NATIVE_MEMBERSHIP = frozenset({"present", "absent", "partial", "unknown"})
_NATIVE_LINKS = frozenset({"active", "pending", "stale", "closed", "absent", "unknown"})


def _fixed_count(value, limit):
    return min(value, limit) if type(value) is int and value >= 0 else None


def _fixed_label(value, allowed):
    return value if type(value) is str and value in allowed else "unknown"


def _event_trace_snapshot(value, *, source_truncated=False):
    if type(value) not in (list, tuple):
        return {"entries": [], "malformed": True, "truncated": source_truncated is True}
    entries, malformed = [], type(source_truncated) is not bool
    truncated = source_truncated is True or len(value) > 16
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
    return {"entries": entries, "malformed": malformed, "truncated": truncated}


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


def _native_failure_snapshot(value):
    if type(value) is not dict:
        return {"selection": "unknown", "attempts": "unavailable", "callbacks": "unavailable"}
    selection = _fixed_label(value.get("selection"), {"selected", "absent", "ambiguous", "partial", "unavailable"})
    raw_attempts = value.get("attempts")
    if type(raw_attempts) is dict:
        entries = raw_attempts.get("entries")
        entries = entries[:4] if type(entries) is list else []
        attempts = {"count": _fixed_count(raw_attempts.get("count"), 4),
            "capped": raw_attempts.get("capped") if type(raw_attempts.get("capped")) is bool else None,
            "entries": []}
        for row in entries:
            row = row if type(row) is dict else {}
            attempts["entries"].append({
                "state": _fixed_label(row.get("state"), _NATIVE_STATES),
                "delivery_attempts": _fixed_count(row.get("delivery_attempts"), 64),
                "pending": _fixed_label(row.get("pending"), _NATIVE_MEMBERSHIP),
                "deferred": _fixed_label(row.get("deferred"), _NATIVE_MEMBERSHIP),
                "direct_link": _fixed_label(row.get("direct_link"), _NATIVE_LINKS),
                "backchannel_link": _fixed_label(row.get("backchannel_link"), _NATIVE_LINKS)})
    else:
        attempts = _fixed_label(raw_attempts, {"contended", "unavailable"})
    raw_callbacks = value.get("callbacks")
    if type(raw_callbacks) is dict:
        callbacks = {}
        for name in ("queue_depth", "dropped_inbound", "dropped_status"):
            callbacks[name] = _fixed_count(raw_callbacks.get(name), 64)
            capped = raw_callbacks.get(name + "_capped") if name != "queue_depth" else raw_callbacks.get("queue_capped")
            callbacks[name + "_capped" if name != "queue_depth" else "queue_capped"] = (
                capped if type(capped) is bool else None)
    else:
        callbacks = _fixed_label(raw_callbacks, {"contended", "unavailable"})
    return {"selection": selection, "attempts": attempts, "callbacks": callbacks}


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
    result = {"available": True, "peer_states": peer_states, "peer_states_truncated": len(rows) > 2,
        "pending": _fixed_count(value.get("pending"), 32),
        "pending_capped": type(value.get("pending")) is int and value["pending"] > 32,
        "channel_discovery": discovery if type(discovery) is str and discovery in {"converged", "incomplete"} else "unknown",
        "workspace_event_scan": scan,
        "workspace_event_states": {name: _fixed_count(states.get(name), 64) for name in _EVENT_STATES},
        "workspace_event_deliveries": _event_delivery_snapshot(workspace.get("deliveries")),
        "workspace_event_trace": _event_trace_snapshot(value.get("workspace_event_trace"),
            source_truncated=value.get("workspace_event_trace_truncated", False))}
    if "native_failure" in workspace:
        result["native_failure"] = _native_failure_snapshot(workspace["native_failure"])
    return result


def _admission_failure_snapshot(value):
    """Whitelist bounded admission evidence; never echo source identifiers."""
    if type(value) is not dict or value.get("available") is not True:
        return {"available": False}
    control = value.get("channel_control")
    control = control if type(control) is dict else {}
    pending = value.get("pending_control")
    pending = pending if type(pending) is dict else {}
    selection = _fixed_label(control.get("selection"),
        {"selected", "not_observed", "absent", "ambiguous", "unavailable"})
    control_result = {"selection": selection}
    if selection == "selected":
        attempts = control.get("attempts")
        control_result.update({
            "state": _fixed_label(control.get("state"), _EVENT_STATES),
            "attempts": _fixed_count(attempts, 32),
            "attempts_capped": (control.get("attempts_capped")
                                if type(control.get("attempts_capped")) is bool else None),
            "schedule": _fixed_label(control.get("schedule"), _EVENT_SCHEDULES),
            "native_message_id_present": (control.get("native_message_id_present")
                                          if type(control.get("native_message_id_present")) is bool else None),
            "failure": _fixed_label(control.get("failure"), _EVENT_FAILURES)})
    pending_selection = _fixed_label(pending.get("selection"),
        {"present", "not_observed", "absent", "ambiguous", "unavailable"})
    pending_result = {"selection": pending_selection}
    if pending_selection == "present":
        pending_result["reason"] = _fixed_label(pending.get("reason"),
            {"missing_manifest", "missing_channel_predecessor"})
    result = {"available": True,
        "workspace_state": _fixed_label(value.get("workspace_state"),
            {"joining", "active", "incomplete_sync", "forked", "closed", "removed", "left"}),
        "channel_discovery": _fixed_label(value.get("channel_discovery"),
            {"incomplete", "converged"}),
        "general_reference": _fixed_label(value.get("general_reference"), {"present", "absent"}),
        "general_channel_record": _fixed_label(value.get("general_channel_record"),
            {"present", "absent", "unknown", "unavailable"}),
        "channel_control": control_result, "pending_control": pending_result}
    if "channel_send_trace" in value:
        result["channel_send_trace"] = _event_trace_snapshot(value["channel_send_trace"])
    if "native_failure" in value:
        result["native_failure"] = _native_failure_snapshot(value["native_failure"])
    return result


def _failure_last_page(value):
    if type(value) is not dict or type(value.get("messages")) is not list:
        return {"available": False}
    count = len(value["messages"])
    return {"available": True, "messages_count": min(count, 64), "messages_capped": count > 64}


class Peers:
    def __init__(self, root, binary, unhosted=False):
        self.root, self.binary = root, binary
        self.unhosted = unhosted
        self.context = multiprocessing.get_context("spawn")
        self.pipes = [self.context.Queue(maxsize=128) for _ in range(2)]
        self.commands, self.replies, self.processes = [None]*2, [None]*2, [None]*2
        self.channels = list(self.pipes)
        self.keys = [os.urandom(32) for _ in range(2)]  # Python-only test custodian.
        self._timeout_probes = [None, None]
        self._command_sequences = [0, 0]

    def start(self, index):
        self.commands[index], self.replies[index] = [self.context.Queue(maxsize=2) for _ in range(2)]
        self.channels.extend((self.commands[index], self.replies[index]))
        try:
            self._timeout_probes[index] = timeout_probe.new_probe()
        except Exception:
            self._timeout_probes[index] = None
        self._command_sequences[index] = 0
        process = self.context.Process(target=_service_worker,args=(str(self.root/str(index)),
            self.pipes[index],self.pipes[1-index],self.commands[index],self.replies[index],
            self.binary,False,self.unhosted and index==1,self.keys[index],self._timeout_probes[index]))
        process.start()
        self.processes[index] = process
        assert self.replies[index].get(timeout=20)["ok"]

    def call(self, index, operation, *, _diagnostic_timeout=None, **payload):
        sequence = self._command_sequences[index] + 1
        self.commands[index].put((operation,payload),timeout=2 if _diagnostic_timeout is None else _diagnostic_timeout)
        self._command_sequences[index] = sequence
        try:
            response = self.replies[index].get(timeout=20 if _diagnostic_timeout is None else _diagnostic_timeout)
        except Empty as error:
            try:
                process = self.processes[index]
                liveness = ("alive" if process.is_alive() else "exited") if process is not None else "unknown"
                note = {"peer": index, **timeout_probe.timeout_note(
                    self._timeout_probes[index], sequence,
                    timeout_probe.command_label(operation, payload), liveness)}
                encoded = json.dumps(note, separators=(",", ":"))
                if len(encoded) <= 320:
                    error.add_note("direct_command_timeout:" + encoded)
            except Exception:
                pass  # Timeout attribution cannot replace the original Empty.
            raise
        assert response["ok"], response
        return response.get("result")

    def command(self, index, command_name, **payload):
        return self.call(index,"command",command=command_name,payload=payload)

    def wait(self, index, name, predicate, *, timeout=45, deadline=None, **payload):
        stop=(time.monotonic()+timeout) if timeout is not None else deadline
        if stop is None: raise ValueError("A wait needs a timeout or deadline")
        if deadline is not None: stop=min(stop,deadline)
        if deadline is not None and time.monotonic()>=deadline:
            raise AssertionError((index,name,{"shared_deadline":"expired"}))
        last=None
        while time.monotonic()<stop:
            last=self.command(index,name,**payload)
            if deadline is not None and time.monotonic()>=stop: break
            result=predicate(last)
            if result: return result
            time.sleep(.2)
        if deadline is not None and time.monotonic()>=deadline:
            raise AssertionError((index,name,{"shared_deadline":"expired"}))
        # The original timeout remains authoritative. Optional test-only
        # snapshots use at most one second per queue operation on each peer.
        diagnostics=[]
        workspace = getattr(self, "workspace", None)
        admission_request = ({"workspace_id": workspace["id"]}
                             if name == "workspace_snapshot" and type(workspace) is dict
                             and type(workspace.get("id")) is str else None)
        native_request = ({"failure_native": True, "workspace_id": workspace["id"]}
                          if name == "list_workspace_messages" and type(workspace) is dict
                          and type(workspace.get("id")) is str else {})
        for peer in range(2):
            try:
                if admission_request is not None:
                    diagnostics.append(_admission_failure_snapshot(self.call(
                        peer, "admission_diagnostic", _diagnostic_timeout=1, **admission_request)))
                else:
                    diagnostics.append(_recovery_failure_snapshot(self.call(
                        peer, "recovery_diagnostic", _diagnostic_timeout=1, **native_request)))
            except Exception: diagnostics.append({"available":False})
        failure = (index,name,_failure_last_page(last) if name == "list_workspace_messages" else last,
                   {"peers":diagnostics})
        if name == "list_workspace_messages":
            try:
                if len(json.dumps(failure)) > 12000:
                    failure = (index,name,{"available":False},{"observation":"size_capped"})
            except Exception:
                failure = (index,name,{"available":False},{"observation":"unavailable"})
        raise AssertionError(failure)

    def connected(self, index, previous_certificate=None, *, route_before=None, deadline=None,
                  control_receipts_before=None):
        # One total bound includes the configured native attempt and retry window.
        # A usable old Phase 2/path is not evidence that recovery has completed.
        # Retain the existing 180-second per-call ceiling. A shared scenario
        # deadline can shorten it; neither value establishes a product SLA.
        if control_receipts_before is not None and (
                type(control_receipts_before) is not int or control_receipts_before < 0):
            raise ValueError("Control receipt baseline must be a nonnegative integer")
        stop=time.monotonic()+180
        if deadline is not None: stop=min(stop,deadline)
        if deadline is not None and time.monotonic()>=deadline:
            raise AssertionError({"failed_peer":index,"shared_deadline":"expired"})
        evidence=None
        connection_observed=False
        while time.monotonic()<stop:
            rows=self.command(index,"direct_recovery_status")
            if (deadline is not None or control_receipts_before is not None) and time.monotonic()>=stop: break
            evidence=self.call(index,"recovery_diagnostic")
            if (deadline is not None or control_receipts_before is not None) and time.monotonic()>=stop: break
            if (rows and all(r["state"]=="connected" and r["authenticated_peer_live"] and r["rns_ready"] for r in rows)
                    and evidence["pending"]==0 and len(evidence["paths"])==1
                    and evidence["paths"][0]["recovery"]
                    and evidence["paths"][0]["certificate"]!=previous_certificate):
                # An attempted migration can leave the old path live while
                # asynchronous replacement is still due. Require its outcome.
                if route_before is not None and not (
                        evidence["migration_attempts"] > route_before["migration_attempts"]
                        and (evidence["migrations"] > route_before["migrations"]
                             or evidence["paths"][0]["certificate"] != route_before["paths"][0]["certificate"])):
                    time.sleep(.2)
                    continue
                # Native capsule authorization and ordinary signed-control ingress
                # are separate observations. Require both within this same window.
                if control_receipts_before is not None:
                    connection_observed=True
                    controls=evidence.get("controls")
                    received=controls.get("received") if type(controls) is dict else None
                    if type(received) is not int or received<=control_receipts_before:
                        time.sleep(.2)
                        continue
                return evidence
            time.sleep(.2)
        if deadline is not None and time.monotonic()>=deadline:
            raise AssertionError({"failed_peer":index,"shared_deadline":"expired"})
        if control_receipts_before is not None:
            controls=evidence.get("controls") if type(evidence) is dict else None
            controls=controls if type(controls) is dict else {}
            raise AssertionError({"failed_peer":index,"replacement_control":{
                "received_before":min(control_receipts_before,1024),
                "received_before_capped":control_receipts_before>1024,
                "connection_observed":connection_observed,
                "counts_capped":any(type(controls.get(name)) is int and controls[name]>1024
                                    for name in ("sent","send_failed","received","rejected")),
                "last_counts":{name:_fixed_count(controls.get(name),1024)
                               for name in ("sent","send_failed","received","rejected")}}})
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

    def delivered(self, sender, sent, *, deadline=None):
        args=dict(workspace_id=self.workspace["id"],channel_id=self.workspace["general_channel_id"],limit=50)
        wait_options={} if deadline is None else {"timeout":None,"deadline":deadline}
        self.wait(1-sender,"list_workspace_messages",lambda page:len([m for m in page["messages"] if m["id"]==sent["id"]])==1,**wait_options,**args)
        self.wait(sender,"list_workspace_messages",lambda page:any(m["id"]==sent["id"] and
            m.get("delivery_summary",{}).get("devices_reached")==1 for m in page["messages"]),**wait_options,**args)

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
        changed_peer=None
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
                # Compose the existing 180-second recovery and 45-second delivery
                # windows once for all peers/receipts after explicit restoration.
                # Ordinary outbox backoff remains authoritative; this is no SLA.
                delivery_deadline=time.monotonic()+225
        else:
            for i in range(2): peers.call(i,"force_recovery")
        if scenario=="replacement": time.sleep(2)
        after=[peers.connected(i,before[i]["paths"][0]["certificate"] if i in changed else None,
                              route_before=before[i] if i==changed_peer else None,
                              deadline=delivery_deadline if scenario=="address_loss" else None,
                              **({"control_receipts_before":before[i]["controls"]["received"]}
                                 if scenario=="replacement" else {})) for i in range(2)]
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
        if "queued" in locals(): peers.delivered(*queued,deadline=delivery_deadline if scenario=="address_loss" else None)
        for i in range(2):
            if scenario=="address_loss" and time.monotonic()>=delivery_deadline:
                raise AssertionError({"shared_deadline":"expired","stage":"bidirectional_send"})
            sent=peers.send(i,"Bidirectional message after "+scenario)
            if scenario=="address_loss" and time.monotonic()>=delivery_deadline:
                raise AssertionError({"shared_deadline":"expired","stage":"bidirectional_send"})
            peers.delivered(i,sent,deadline=delivery_deadline if scenario=="address_loss" else None)
        for i in range(2):
            identifier=peers.command(i,"direct_recovery_status")[0]["relationship_id"]
            peers.command(i,"pause_direct_recovery",identifier=identifier)
            assert peers.call(i,"diagnostic")=={"native_count":0,"interfaces":0}
    finally:
        peers.close()
