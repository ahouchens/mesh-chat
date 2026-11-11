"""Outside-checkout application staging is component evidence, not SC21 traffic."""

import json
import io
import copy
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import tarfile
import xml.etree.ElementTree as ET
import zipfile
from threading import Event, RLock
from types import SimpleNamespace

import pytest

from mesh_chat.core_api.composition import bind_service_stream
from mesh_chat.core_api.session import Grant
from mesh_chat.core_api.wire_codec import decode_frame, encode_frame
from test_core_messages import host

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import stage_independent_core_consumers as staging
import check_independent_core_consumers as bootstrap
import check_independent_core_pairing as pairing
import verify_android_independent_consumer as android_distribution
import stage_android_independent_consumer as android_staging


def test_installed_node_sdk_readiness_reaches_actual_framed_connection_projection(tmp_path):
    from mesh_chat.connection.projection import snapshot
    from tools.connection_harness.simulation import Simulation
    simulation = Simulation()
    simulation.recover()
    service = SimpleNamespace(_shutdown=Event(), _dispatch_lock=RLock(), _identity=object(),
        store=SimpleNamespace(opaque_id=lambda *_: "ab" * 32, items=lambda *_, **__: [],
            get=lambda *_: {"display_name": "Alex", "destination_hash": "cd" * 16}),
        _require_profile=lambda: {"display_name": "Alex", "destination_hash": "cd" * 16},
        _connection_runtime=SimpleNamespace(snapshots=lambda: {
            simulation.key.profile_id: snapshot(simulation.owner.snapshot(simulation.key), simulation.now)}))
    stream = bind_service_stream(service, lambda: Grant("readiness-consumer", frozenset({"observe"}), ("local",)))
    # Install the actual public package bytes, not a fake connectionSnapshot method.
    artifact = Path(os.environ.get("MESH_CORE_SDK_ARTIFACTS", staging.ROOT / "dist/sdk")) / "typescript" / staging.ARTIFACTS["typescript"]
    assert artifact.is_file(), "Stage the real public TypeScript SDK first"
    with tarfile.open(artifact) as archive: archive.extractall(tmp_path / "installed", filter="data")
    sdk = tmp_path / "installed/package/dist/index.js"
    helper = staging.APPLICATION / "connection-readiness.mjs"
    script = f"import {{CoreClient}} from {json.dumps(sdk.as_uri())};\n" + \
             f"import {{connectionMessagingReady}} from {json.dumps(helper.as_uri())};\n" + """
import {createInterface} from 'node:readline';
const input = createInterface({input:process.stdin});
const lines = input[Symbol.asyncIterator]();
const client = await CoreClient.open({
  async writeLine(line) { process.stdout.write(line); },
  async readLine() { const value = await lines.next(); return value.done ? null : value.value + '\\n'; },
  close() { input.close(); },
}, {requestTimeoutMs:3000});
const profile = client.capabilities.profiles[0];
const connection = (await client.request('profile.query', {profile})).connections[0];
const before = await connectionMessagingReady(client, profile, connection);
const after = await connectionMessagingReady(client, profile, connection);
let obsolete;
try { await client.request('connection.query', {profile,connection}); } catch (error) { obsolete = error.code; }
client.close();
console.log(JSON.stringify({before,after,obsolete}));
"""
    node, _ = staging.tools()
    process = subprocess.Popen([node, "--input-type=module", "-e", script], cwd=tmp_path,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for index, expected in enumerate(("runtime.capabilities", "profile.query", "connection.snapshot", "connection.snapshot", "connection.query")):
            line = process.stdout.readline()
            assert line, process.stderr.read()
            assert json.loads(line)["operation"] == expected
            response = stream.exchange(line.encode())
            decoded = json.loads(response)
            if expected == "connection.snapshot":
                assert decoded["ok"], decoded
                assert decoded["result"]["observation"]["messaging_ready"] is (index == 2)
            elif expected == "connection.query":
                assert decoded["error"]["code"] == "unsupported_operation"
            process.stdin.write(response.decode())
            process.stdin.flush()
            if index == 2: simulation.close()
        assert json.loads(process.stdout.readline()) == {"before": True, "after": False, "obsolete": "unsupported_operation"}
        assert process.wait(timeout=5) == 0, process.stderr.read()
    finally:
        if process.poll() is None: process.kill()
        process.wait(timeout=5)
        stream.close()


@pytest.mark.parametrize("fault", ["invitation_wait", "invitation_accept", "pending_request_wait",
    "offerer_relationship_wait", "offerer_ready_wait", "answerer_ready_wait", "unsafe_error"])
def test_actual_node_pairing_producer_reports_safe_specific_failure_observations(fault):
    # Actual producer control flow; synthetic SDK/host boundary, no native claim.
    node, _ = staging.tools()
    completed = subprocess.run([node, "--import", (staging.ROOT /
        "tests/core-ui-boundary/pairing_diagnostic_fixture.mjs").as_uri(),
        str(staging.APPLICATION / "pairing-check.mjs"), "--runtime", "unused", "--data-directory", "unused"],
        cwd=staging.ROOT, env={**os.environ, "PAIRING_DIAGNOSTIC_FAULT": fault},
        capture_output=True, text=True, timeout=15)
    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert len(completed.stdout.encode()) <= 4096
    observed = json.loads(completed.stdout)
    details = pairing.failure_details(observed)
    expected = "invitation_accept" if fault == "unsafe_error" else fault
    assert details["application_phase"] == "explicit_approval"
    assert details["diagnostics"]["subphase"] == expected
    assert details["diagnostics"]["deadline_exhausted"] is (fault not in {"invitation_accept", "unsafe_error"})
    assert details["error_code"] == ("forbidden" if fault == "invitation_accept" else "unavailable")
    assert "private" not in (completed.stdout + completed.stderr).lower()
    peers = details["diagnostics"]["peers"]
    assert peers["answerer"]["last_pairing"] == {"state": "awaiting_approval", "code_present": False}
    assert details["diagnostics"]["failure_probe"] == {
        role: {"query_outcome": "ok", "state": "transferred", "expired": True} for role in ("offerer", "answerer")}
    if fault == "invitation_wait":
        assert peers["answerer"]["last_snapshot"]["pending_invitations"] == 0
    elif fault == "pending_request_wait":
        assert peers["offerer"]["last_snapshot"]["pending_requests"] == 1
        assert peers["offerer"]["last_snapshot"]["matching_pending_request"] is False
    elif fault == "offerer_relationship_wait":
        assert peers["offerer"]["last_snapshot"]["approved_contacts"] == 1
        assert peers["offerer"]["last_snapshot"]["matching_approved_contact"] is False
    elif fault.endswith("ready_wait"):
        role = fault.removesuffix("_ready_wait")
        assert peers[role]["last_connections"] == {"total": 1, "checked": 1, "ready": 0, "counts_capped": False}


@pytest.mark.parametrize("mode,present,error", [("pre_profile_absence", False, None),
    ("missing", False, "network_start_failed"), ("unavailable", True, "network_interface_unavailable"),
    ("healthy", True, None), ("unexpected_error", True, "unknown"), ("error_object", True, "unknown"),
    ("invalid_string", False, "unknown"), ("invalid_array", False, "unknown")])
def test_actual_node_snapshot_selects_network_presence_without_extra_requests(tmp_path, mode, present, error):
    node, _ = staging.tools()
    log = tmp_path / "events.jsonl"
    pre_profile = mode == "pre_profile_absence"
    completed = subprocess.run([node, "--import", (staging.ROOT /
        "tests/core-ui-boundary/pairing_diagnostic_fixture.mjs").as_uri(),
        str(staging.APPLICATION / "pairing-check.mjs"), "--runtime", "unused", "--data-directory", "unused"],
        cwd=staging.ROOT, env={**os.environ, "PAIRING_DIAGNOSTIC_FAULT": mode if pre_profile else "pending_request_wait",
            "PAIRING_DIAGNOSTIC_NETWORK": mode, "PAIRING_DIAGNOSTIC_LOG": str(log)},
        capture_output=True, text=True, timeout=15)
    assert completed.returncode == 1 and len(completed.stdout.encode()) <= 4096
    assert "private" not in (completed.stdout + completed.stderr).lower()
    details = pairing.failure_details(json.loads(completed.stdout))
    observed = details["diagnostics"]["peers"]["offerer"]["last_snapshot"]
    assert observed["network_present"] is present and observed["service_error"] == error
    assert observed["observed_subphase"] == ("offerer_create" if pre_profile else "pending_request_wait")
    events = [json.loads(line) for line in log.read_text().splitlines()]
    snapshots = [(event["role"], event["operation"]) for event in events
                 if event["event"] == "request" and event["operation"] == "application.snapshot"]
    if pre_profile:
        assert details["application_phase"] == "fresh_profiles" and details["error_code"] == "forbidden"
        assert snapshots == [("offerer", "application.snapshot")]
        assert details["diagnostics"]["failure_probe"] == {}
    else:
        assert details["application_phase"] == "explicit_approval" and details["error_code"] == "unavailable"
        assert snapshots == [(role, "application.snapshot") for role in
                             ("offerer", "offerer", "answerer", "answerer", "answerer", "answerer", "offerer")]
        assert details["diagnostics"]["post_accept_reads"] == {"attempts": 1, "completed": 1,
            "clipped": False, "deadline_exhausted_at_entry": False}
        assert [event["operation"] for event in events if event["event"] == "request"][-4:] == [
            "peer.pairing_query", "peer.pairing_query", "diagnostics.query", "diagnostics.query"]
    assert [event["role"] for event in events if event["event"] == "stop"] == (["offerer"] if pre_profile else ["offerer", "answerer"])


def test_network_projection_never_reads_members_and_safely_marshals_invalid_shapes():
    node, _ = staging.tools()
    script = """
import {pairingDiagnostics} from './examples/typescript-independent-consumer/pairing-diagnostics.mjs';
const network = {};
Object.defineProperty(network,'address',{enumerable:true,get(){throw new Error('PRIVATE_ADDRESS_READ');}});
const values = [];
for (const value of [network,null,'PRIVATE_ADDRESS',[],42,undefined]) {
  const diagnostics = pairingDiagnostics();
  diagnostics.snapshot('offerer',{network:value,service_error:null,contacts:[],contact_invitations:[]});
  const snapshot = diagnostics.failure().peers.offerer.last_snapshot;
  values.push({network_present:snapshot.network_present,service_error:snapshot.service_error});
}
console.log(JSON.stringify(values));
"""
    completed = subprocess.run([node, "--input-type=module", "-e", script], cwd=staging.ROOT,
        capture_output=True, text=True, check=True, timeout=15)
    assert "PRIVATE" not in completed.stdout + completed.stderr
    assert json.loads(completed.stdout) == [{"network_present": True, "service_error": None},
        {"network_present": False, "service_error": None}] + [{"network_present": False, "service_error": "unknown"}] * 4


@pytest.mark.parametrize("unavailable", [False, True])
def test_invitation_observer_retains_early_public_state_with_fixed_budget(unavailable):
    node, _ = staging.tools()
    script = """
import {pairingDiagnostics,invitationWaitObserver} from './examples/typescript-independent-consumer/pairing-diagnostics.mjs';
let tick=0, active=0, maximum=0;
const calls=[];
const unavailable=UNAVAILABLE;
const peer=role=>({role,profile:'PRIVATE_PROFILE',pairing:'PRIVATE_PAIRING',client:{
  async request(operation,params,options){
    calls.push({role,operation,limit:params.limit??null,timeout:options.timeoutMs});
    maximum=Math.max(maximum,++active);
    try {
      await Promise.resolve();
      if(unavailable)throw new Error('PRIVATE_OBSERVER_ERROR');
      if(operation==='peer.pairing_query')return {state:tick>=5000?'retired':
        tick>=1000&&role==='answerer'?'awaiting_approval':role==='offerer'?'offer_ready':'reserved',
        expires_at:1240,pairing_code:'PRIVATE_CODE',sdp:'PRIVATE_SDP'};
      return {available:true,runtime_failure:null,total_connections:tick===20000?2:1,
        truncated:tick===20000,
        connections:[{connection:'PRIVATE_CONNECTION',observation:{desired:tick>=5000?'stopped':'enabled',
          execution:'available',negotiation:tick>=5000?'idle':'checking',
          reason:tick>=5000?'ineligible':tick>=1000?'phase_timeout':'wait_offer',
          endpoint:'PRIVATE_ENDPOINT'}}]};
    } finally {active--;}
  }
}});
const diagnostics=pairingDiagnostics(()=>tick);
const observe=invitationWaitObserver([peer('offerer'),peer('answerer')],diagnostics,()=>1000000+tick,()=>tick);
for(const at of [0,500,1000,5000,20000,90000,100000]){
  tick=at;observe.poll([],1240000);await new Promise(resolve=>setImmediate(resolve));
}
const primary=new Error('PRIVATE_WORK_ERROR');
let same=false;
try {observe.poll([],1240000);throw primary;}catch(error){same=error===primary;}
observe.stop();
tick=239000;
const lateDiagnostics=pairingDiagnostics(()=>tick);
const lateObserve=invitationWaitObserver([peer('offerer'),peer('answerer')],lateDiagnostics,
  ()=>1000000+tick,()=>tick);
const before=calls.length;
lateObserve.poll([],1240000);
console.log(JSON.stringify({calls,maximum,same,nearDeadlineCalls:calls.length-before,
  nearDeadlineSamples:lateDiagnostics.failure().invitation_observation.samples.length,
  observation:diagnostics.failure().invitation_observation}));
""".replace("UNAVAILABLE", json.dumps(unavailable))
    completed = subprocess.run([node, "--input-type=module", "-e", script], cwd=staging.ROOT,
                               capture_output=True, text=True, check=True, timeout=15)
    assert "PRIVATE" not in completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    observation = result["observation"]
    pairing.invitation_observation_details(observation)
    assert observation["sample_offsets_ms"] == pairing.INVITATION_SAMPLE_OFFSETS_MS
    assert observation["sample_budget"] == 5 and observation["capped"] is True
    assert (observation["request_budget_ms"], observation["work_reserve_ms"], observation["actor_limit"]) == (2000, 100, 1)
    assert [sample["offset_ms"] for sample in observation["samples"]] == pairing.INVITATION_SAMPLE_OFFSETS_MS
    assert len(result["calls"]) == 20 and result["maximum"] <= 2 and result["same"] is True
    assert result["nearDeadlineCalls"] == 0 and result["nearDeadlineSamples"] == 0
    assert all(0 < call["timeout"] <= 2000 for call in result["calls"])
    assert all(call["limit"] == 1 for call in result["calls"] if call["operation"] == "diagnostics.query")
    early = observation["samples"][1]["answerer"]
    late = observation["samples"][2]["answerer"]
    if unavailable:
        assert early == {"pairing": {"query_outcome": "failed"}, "actor": {"query_outcome": "failed"}}
    else:
        assert early["pairing"] == {"query_outcome": "ok", "state": "awaiting_approval", "expired": False}
        assert early["actor"]["actor"]["reason"] == "phase_timeout"
        assert late["pairing"]["state"] == "retired" and late["actor"]["actor"]["reason"] == "ineligible"
        assert observation["samples"][3]["answerer"]["actor"]["actor"] is None
        assert observation["samples"][3]["answerer"]["actor"]["truncated"] is True


@pytest.mark.parametrize("fault", ["raw_handle", "raw_endpoint", "invalid_reason", "too_many_samples",
    "bad_offset", "bad_budget", "bad_request_budget", "wrong_role", "ambiguous_actor", "object_outcome"])
def test_invitation_observation_validator_rejects_unsafe_or_unbounded_fields(fault):
    actor = {"query_outcome": "ok", "available": True, "runtime_failure": None,
             "total_connections": 1, "truncated": False,
             "actor": {"desired": "enabled", "execution": "available", "negotiation": "checking",
                       "reason": "phase_timeout"}}
    peer = {"pairing": {"query_outcome": "ok", "state": "awaiting_approval", "expired": False},
            "actor": actor}
    sample = {"offset_ms": 0, "pending_invitations": 0, "counts_capped": False, "outcome": "complete",
              "offerer": copy.deepcopy(peer), "answerer": copy.deepcopy(peer)}
    observed = {"sample_budget": 5, "sample_offsets_ms": pairing.INVITATION_SAMPLE_OFFSETS_MS.copy(),
                "request_budget_ms": 2000, "work_reserve_ms": 100, "actor_limit": 1,
                "samples": [sample], "capped": False}
    pairing.invitation_observation_details(observed)
    if fault == "raw_handle": sample["answerer"]["pairing"]["pairing"] = "PRIVATE_PAIRING"
    elif fault == "raw_endpoint": sample["answerer"]["actor"]["actor"]["endpoint"] = "PRIVATE_ENDPOINT"
    elif fault == "invalid_reason": sample["answerer"]["actor"]["actor"]["reason"] = "PRIVATE_ERROR"
    elif fault == "too_many_samples": observed["samples"] *= 6
    elif fault == "bad_offset": sample["offset_ms"] = -1
    elif fault == "bad_budget": observed["sample_budget"] = 6
    elif fault == "bad_request_budget": observed["request_budget_ms"] = 30000
    elif fault == "wrong_role": sample["contender"] = sample.pop("answerer")
    elif fault == "ambiguous_actor": sample["answerer"]["actor"]["total_connections"] = 2
    else: sample["answerer"]["actor"]["query_outcome"] = {"error": "PRIVATE_ERROR"}
    with pytest.raises(ValueError): pairing.invitation_observation_details(observed)


@pytest.mark.parametrize("stall", ["pairing", "diagnostics"])
def test_stalled_public_observer_does_not_delay_invitation_or_mutate_after_stop(tmp_path, stall):
    node, _ = staging.tools()
    preloader = tmp_path / "stall-observer.mjs"
    preloader.write_text("""
const fixture=globalThis.__diagnosticFixture;
const originalOpen=fixture.CoreClient.open;
fixture.CoreClient.open=async (...args)=>{
  const client=await originalOpen(...args);
  if(args[0].owner.role!=='answerer')return client;
  let answered=false, skipped=false, stalled=false, release;
  const originalBegin=client.pairingBegin.bind(client);
  const originalRequest=client.request.bind(client);
  client.pairingBegin=async (...values)=>{
    const result=await originalBegin(...values);
    if(values[1]==='answer')answered=true;
    return result;
  };
  client.request=async (operation,params,options)=>{
    if(answered && operation==='application.snapshot' && !skipped){
      skipped=true;
      return {...await originalRequest(operation,params,options),contact_invitations:[]};
    }
    if(answered && !stalled && (STAGE==='pairing' && operation==='peer.pairing_query'
        || STAGE==='diagnostics' && operation==='diagnostics.query' && params.limit===1)){
      stalled=true;
      return new Promise(resolve=>{release=resolve;});
    }
    if(operation==='contact.invitation' && release){
      release(STAGE==='pairing' ? {state:'retired',expires_at:Date.now()/1000+30,
        pairing_code:'PRIVATE_CODE'} : {available:false,runtime_failure:null,
        total_connections:0,truncated:false,connections:[]});
      release=undefined;
    }
    return originalRequest(operation,params,options);
  };
  return client;
};
""".replace("STAGE", json.dumps(stall)), encoding="utf-8")
    log = tmp_path / "events.jsonl"
    completed = subprocess.run([node, "--import", (staging.ROOT /
        "tests/core-ui-boundary/pairing_diagnostic_fixture.mjs").as_uri(),
        "--import", preloader.as_uri(), str(staging.APPLICATION / "pairing-check.mjs"),
        "--runtime", "unused", "--data-directory", "unused"], cwd=staging.ROOT,
        env={**os.environ, "PAIRING_DIAGNOSTIC_FAULT": "invitation_accept",
             "PAIRING_DIAGNOSTIC_LOG": str(log)}, capture_output=True, text=True, timeout=10)
    assert completed.returncode == 1 and len(completed.stdout.encode()) <= 4096
    assert "PRIVATE" not in completed.stdout + completed.stderr
    details = pairing.failure_details(json.loads(completed.stdout))
    assert details["application_phase"] == "explicit_approval" and details["error_code"] == "forbidden"
    assert details["diagnostics"]["subphase"] == "invitation_accept"
    observation = details["diagnostics"]["invitation_observation"]
    assert observation["samples"] == [{"offset_ms": 0, "pending_invitations": 0,
        "counts_capped": False, "outcome": "incomplete"}]
    events = [json.loads(line) for line in log.read_text().splitlines()]
    assert len([item for item in events if item.get("event") == "request"
                and item.get("role") == "answerer" and item.get("operation") == "application.snapshot"]) == 5
    assert len([item for item in events if item.get("event") == "public_probe"
                and item.get("role") == "answerer" and item.get("limit") == 1]) == 0


@pytest.mark.parametrize("fault", ["integer_presence", "object_presence", "error_string", "error_object", "error_array",
    "missing_presence", "missing_error", "raw_network", "raw_address"])
def test_strict_failure_parser_rejects_unselected_network_or_error_values(fault):
    snapshot = {**{key: 0 for key in pairing.SNAPSHOT_COUNTS}, **{key: False for key in pairing.SNAPSHOT_FLAGS},
        "observed_subphase": "offerer_create", "service_error": None}
    observed = {"passed": False, "phase": "fresh_profiles", "error_code": "unavailable", "diagnostics": {
        "subphase": "offerer_create", "deadline_exhausted": False, "failure_origin": "unknown", "cleanup": [],
        "stage_timing": {"offsets_ms": {"failure_observed": 0}, "clipped": False},
        "peers": {"offerer": {"last_snapshot": snapshot}}}}
    pairing.failure_details(copy.deepcopy(observed))
    if fault == "integer_presence": snapshot["network_present"] = 1
    elif fault == "object_presence": snapshot["network_present"] = {"address": "PRIVATE_ADDRESS"}
    elif fault == "error_string": snapshot["service_error"] = "PRIVATE_ERROR"
    elif fault == "error_object": snapshot["service_error"] = {"path": "PRIVATE_PATH"}
    elif fault == "error_array": snapshot["service_error"] = ["PRIVATE_ERROR"]
    elif fault == "missing_presence": snapshot.pop("network_present")
    elif fault == "missing_error": snapshot.pop("service_error")
    elif fault == "raw_network": snapshot["network"] = {"address": "PRIVATE_ADDRESS"}
    else: snapshot["address"] = "PRIVATE_ADDRESS"
    with pytest.raises(ValueError): pairing.failure_details(observed)


@pytest.mark.parametrize("fault,completed,entry_expired,failure_ms", [
    ("late_accept", 0, True, 240100), ("pending_read_reject", 0, False, 1500),
    ("pending_read_in_flight", 0, False, 1500), ("pending_request_wait", 1, False, 300000)])
def test_actual_producer_distinguishes_late_acceptance_and_post_accept_reads(tmp_path, fault, completed, entry_expired, failure_ms):
    node, _ = staging.tools()
    log = tmp_path / "events.jsonl"
    process = subprocess.run([node, "--import", (staging.ROOT /
        "tests/core-ui-boundary/pairing_diagnostic_fixture.mjs").as_uri(),
        str(staging.APPLICATION / "pairing-check.mjs"), "--runtime", "unused", "--data-directory", "unused"],
        cwd=staging.ROOT, env={**os.environ, "PAIRING_DIAGNOSTIC_FAULT": fault,
            "PAIRING_DIAGNOSTIC_LOG": str(log)}, capture_output=True, text=True, timeout=15)
    assert process.returncode == 1 and len(process.stdout.encode()) <= 4096
    assert "private" not in (process.stdout + process.stderr).lower()
    result = pairing.failure_details(json.loads(process.stdout))
    assert result["application_phase"] == "explicit_approval" and result["error_code"] == "unavailable"
    diagnostics = result["diagnostics"]
    assert diagnostics["subphase"] == "pending_request_wait"
    assert diagnostics["deadline_exhausted"] is (fault in {"late_accept", "pending_request_wait"})
    assert diagnostics["stage_timing"] == {"offsets_ms": {"invitation_accept_started": 0,
        "invitation_accept_returned": 240100 if entry_expired else 1000,
        "pending_request_wait_entered": 240100 if entry_expired else 1000,
        "failure_observed": failure_ms}, "clipped": False}
    assert diagnostics["post_accept_reads"] == {"attempts": 0 if entry_expired else 1,
        "completed": completed, "clipped": False, "deadline_exhausted_at_entry": entry_expired}
    assert diagnostics["peers"]["offerer"]["last_snapshot"]["observed_subphase"] == (
        "pending_request_wait" if completed else "offerer_create")
    assert diagnostics["peers"]["answerer"]["last_snapshot"]["observed_subphase"] == "invitation_guard"
    events = [json.loads(line) for line in log.read_text().splitlines()]
    assert [item for item in events if item["event"] == "open"] == [
        {"event": "open", "role": role, "timeout": 30000} for role in ("offerer", "answerer")]
    assert len([item for item in events if item["event"] == "post_accept_snapshot"]) == (0 if entry_expired else 1)
    assert [item["role"] for item in events if item["event"] == "stop"] == ["offerer", "answerer"]
    accepted = next(index for index, item in enumerate(events) if item["event"] == "accept_returned")
    following = [item["operation"] for item in events[accepted + 1:] if item["event"] == "request"]
    assert following == ([] if entry_expired else ["application.snapshot"]) + [
        "peer.pairing_query", "peer.pairing_query", "diagnostics.query", "diagnostics.query"]


@pytest.mark.parametrize("mode", ["reject", "invalid", "advance_clock", "retirement_failure", "uninitialized"])
def test_failure_probe_preserves_original_failure_and_retirement_with_bounded_requests(tmp_path, mode):
    node, _ = staging.tools()
    log = tmp_path / "probe.jsonl"
    completed = subprocess.run([node, "--import", (staging.ROOT /
        "tests/core-ui-boundary/pairing_diagnostic_fixture.mjs").as_uri(),
        str(staging.APPLICATION / "pairing-check.mjs"), "--runtime", "unused", "--data-directory", "unused"],
        cwd=staging.ROOT, env={**os.environ, "PAIRING_DIAGNOSTIC_FAULT": "create_failure" if mode == "uninitialized" else "invitation_accept",
            "PAIRING_DIAGNOSTIC_PROBE": mode, "PAIRING_DIAGNOSTIC_LOG": str(log)},
        capture_output=True, text=True, timeout=15)
    assert completed.returncode == 1
    assert "private" not in (completed.stdout + completed.stderr).lower()
    observed = json.loads(completed.stdout)
    details = pairing.failure_details(observed)
    events = [json.loads(line) for line in log.read_text().splitlines()]
    probes = [item for item in events if item["event"] == "probe"]
    stops = [item for item in events if item["event"] == "stop"]
    assert details["diagnostics"]["deadline_exhausted"] is False
    assert details["diagnostics"]["stage_timing"]["offsets_ms"]["failure_observed"] == 0
    if mode == "uninitialized":
        assert probes == [] and stops == [{"event": "stop", "role": "offerer", "incarnation": 1, "remaining": 30000}]
        assert details["application_phase"] == "fresh_profiles" and details["error_code"] == "forbidden"
        assert details["diagnostics"]["subphase"] == "offerer_create"
        assert details["diagnostics"]["failure_probe"] == {}
    else:
        assert probes == [{"event": "probe", "role": role, "timeout": 2000} for role in ("offerer", "answerer")]
        assert stops == [{"event": "stop", "role": role, "incarnation": 1,
                          "remaining": 0 if mode == "advance_clock" else 30000} for role in ("offerer", "answerer")]
        assert events.index(stops[0]) > events.index(probes[1])
        assert details["application_phase"] == "explicit_approval" and details["error_code"] == "forbidden"
        assert details["diagnostics"]["subphase"] == "invitation_accept"
        expected = ({"query_outcome": "ok", "state": "transferred", "expired": True}
                    if mode in {"advance_clock", "retirement_failure"}
                    else {"query_outcome": "failed" if mode == "reject" else "invalid_result"})
        assert details["diagnostics"]["failure_probe"] == {role: expected for role in ("offerer", "answerer")}


def test_failure_probe_queries_two_distinct_initialized_peers_concurrently_once():
    node, _ = staging.tools()
    script = """
import {pairingDiagnostics,probePairingFailure} from './examples/typescript-independent-consumer/pairing-diagnostics.mjs';
const diagnostics = pairingDiagnostics();
const calls = [];
let release;
const first = new Promise(resolve => { release = resolve; });
function peer(role) { return {role,profile:'PRIVATE_PROFILE',pairing:'PRIVATE_PAIRING',client:{
  async request(operation,params,options) {
    calls.push({role,operation,timeout:options.timeoutMs});
    if (calls.length === 1) await first;
    else release();
    return {state:'awaiting_approval',expires_at:Date.now()/1000+30,token:'PRIVATE_TOKEN'};
  }
}}; }
await probePairingFailure([{role:'offerer'},peer('offerer'),peer('offerer'),peer('answerer'),peer('answerer')],diagnostics,()=>0);
console.log(JSON.stringify({calls,probe:diagnostics.failure().failure_probe}));
"""
    completed = subprocess.run([node, "--input-type=module", "-e", script], cwd=staging.ROOT,
        capture_output=True, text=True, check=True, timeout=5)
    assert "PRIVATE" not in completed.stdout
    value = json.loads(completed.stdout)
    assert value["calls"][:2] == [{"role": role, "operation": "peer.pairing_query", "timeout": 2000}
        for role in ("offerer", "answerer")]
    assert sorted(value["calls"][2:], key=lambda row: row["role"]) == [
        {"role": role, "operation": "diagnostics.query", "timeout": 2000} for role in ("answerer", "offerer")]
    assert value["probe"] == {role: {"query_outcome": "ok", "state": "awaiting_approval", "expired": False} for role in ("offerer", "answerer")}


@pytest.mark.parametrize("elapsed,reject,stall", [
    (0, False, False), (0, True, False), (1250, False, False), (1250, False, True),
    (1999.4, False, False), (2000, False, False), (2500, True, False)])
def test_serialized_clients_share_one_failure_probe_deadline(elapsed, reject, stall):
    node, _ = staging.tools()
    script = """
import {pairingDiagnostics,probePairingFailure} from './examples/typescript-independent-consumer/pairing-diagnostics.mjs';
const config = CONFIG;
let now=0, release, diagnosticTimeout;
const gate=new Promise(resolve=>{release=resolve;});
const stalled=new Promise(resolve=>{diagnosticTimeout=resolve;});
const calls=[];
function peer(role){
  let tail=Promise.resolve();
  return {role,profile:'PRIVATE_PROFILE',pairing:'PRIVATE_PAIRING',client:{request(operation,params,options){
    const run=async()=>{
      calls.push({role,operation,timeout:options.timeoutMs,limit:params.limit??null,at:now});
      if(operation==='peer.pairing_query'){
        await gate;
        if(config.reject)throw new Error('PRIVATE_PAIRING_ERROR');
        return {state:'retired',expires_at:Date.now()/1000+30};
      }
      if(config.stall){await stalled;throw new Error('PRIVATE_TIMEOUT');}
      return {available:false,runtime_failure:null,total_connections:0,truncated:false,connections:[]};
    };
    const result=tail.then(run,run); tail=result.then(()=>undefined,()=>undefined);return result;
  }}};
}
const diagnostics=pairingDiagnostics();
const work=probePairingFailure([peer('offerer'),peer('offerer'),peer('answerer'),peer('answerer')],diagnostics,()=>now);
await new Promise(resolve=>setImmediate(resolve));
const before=structuredClone(calls);
now=config.elapsed;release();
if(config.stall){await new Promise(resolve=>setImmediate(resolve));now=2000;diagnosticTimeout();}
await work;
console.log(JSON.stringify({before,calls,finished:now,diagnostics:diagnostics.failure()}));
""".replace("CONFIG", json.dumps({"elapsed": elapsed, "reject": reject, "stall": stall}))
    completed = subprocess.run([node, "--input-type=module", "-e", script], cwd=staging.ROOT,
        capture_output=True, text=True, check=True, timeout=5)
    assert "PRIVATE" not in completed.stdout + completed.stderr
    value = json.loads(completed.stdout)
    assert value["before"] == [{"role": role, "operation": "peer.pairing_query", "timeout": 2000, "limit": None, "at": 0}
                               for role in ("offerer", "answerer")]
    diagnostics = value["diagnostics"]["public_diagnostics"]
    remaining = int(2000 - elapsed)
    if remaining > 0:
        assert value["calls"][2:] == [{"role": role, "operation": "diagnostics.query", "timeout": remaining, "limit": 4, "at": elapsed}
                                       for role in ("offerer", "answerer")]
        assert all(row["query_outcome"] == ("failed" if stall else "ok") for row in diagnostics.values())
        assert value["finished"] == (2000 if stall else elapsed)
    else:
        assert len(value["calls"]) == 2
        assert diagnostics == {role: {"query_outcome": "not_attempted", "reason": "deadline_exhausted"}
                               for role in ("offerer", "answerer")}
    assert value["diagnostics"]["failure_probe"] == {role: ({"query_outcome": "failed"} if reject else
        {"query_outcome": "ok", "state": "retired", "expired": False}) for role in ("offerer", "answerer")}


def test_public_actor_projection_uses_only_existing_view_enums_and_selected_fields():
    from mesh_chat.core_api.views import ENUMS, REASONS
    node, _ = staging.tools()
    script = """
import {publicDiagnosticObservation,ACTOR_ENUMS,FAILURE_ORIGINS} from './examples/typescript-independent-consumer/pairing-diagnostics.mjs';
const row={desired:'enabled',execution:'available',negotiation:'checking',reason:'phase_timeout',
  runtime_epoch:'PRIVATE_EPOCH',sequence:12,captured_at:123};
const value={profile:'PRIVATE_PROFILE',available:true,runtime_failure:null,total_connections:1,truncated:false,
  connections:[{connection:'PRIVATE_CONNECTION',observation:row}]};
Object.defineProperty(value,'captured_at',{get(){throw new Error('PRIVATE_UNSELECTED_READ');}});
const good=publicDiagnosticObservation(value);
const unknown=publicDiagnosticObservation({...value,runtime_failure:'PRIVATE_FAILURE',connections:[{observation:{
  desired:'PRIVATE_DESIRED',execution:'PRIVATE_EXECUTION',negotiation:'PRIVATE_NEGOTIATION',reason:'PRIVATE_REASON'}}]});
const enums=Object.fromEntries(Object.entries(ACTOR_ENUMS).map(([key,values])=>[key,[...values]]));
console.log(JSON.stringify({good,unknown,enums,origins:[...FAILURE_ORIGINS]}));
"""
    completed = subprocess.run([node, "--input-type=module", "-e", script], cwd=staging.ROOT,
        capture_output=True, text=True, check=True, timeout=5)
    assert "PRIVATE" not in completed.stdout + completed.stderr
    value = json.loads(completed.stdout)
    assert {key: set(values) for key, values in value["enums"].items()} == {
        **{key: ENUMS[key] for key in ("desired", "execution", "negotiation")}, "reason": REASONS} == pairing.ACTOR_ENUMS
    assert set(value["origins"]) == pairing.FAILURE_ORIGINS
    assert value["good"] == {"query_outcome": "ok", "available": True, "runtime_failure": None,
        "total_connections": 1, "truncated": False, "connections": [
            {"desired": "enabled", "execution": "available", "negotiation": "checking", "reason": "phase_timeout"}]}
    assert value["unknown"]["runtime_failure"] == "unknown"
    assert value["unknown"]["connections"] == [{key: "unknown" for key in pairing.ACTOR_ENUMS}]
    pairing.public_diagnostic_details({"offerer": value["good"], "answerer": value["unknown"]})


@pytest.mark.parametrize("fault", ["available", "runtime_failure", "total_bool", "total_fraction", "total_negative",
    "total_nan", "truncated", "rows", "too_many", "row", "observation", "enum_type", "unavailable_rows"])
def test_public_actor_producer_fails_closed_on_malformed_selected_fields(fault):
    node, _ = staging.tools()
    script = """
import {publicDiagnosticObservation} from './examples/typescript-independent-consumer/pairing-diagnostics.mjs';
const value={available:true,runtime_failure:null,total_connections:1,truncated:false,connections:[{observation:{
  desired:'enabled',execution:'available',negotiation:'checking',reason:'phase_timeout'}}]};
const fault=FAULT;
if(fault==='available')value.available=1;
if(fault==='runtime_failure')value.runtime_failure={path:'PRIVATE_PATH'};
if(fault==='total_bool')value.total_connections=true;
if(fault==='total_fraction')value.total_connections=1.5;
if(fault==='total_negative')value.total_connections=-1;
if(fault==='total_nan')value.total_connections=NaN;
if(fault==='truncated')value.truncated=1;
if(fault==='rows')value.connections='PRIVATE_ROWS';
if(fault==='too_many'){value.connections=Array(5).fill(value.connections[0]);value.total_connections=5;}
if(fault==='row')value.connections[0]=null;
if(fault==='observation')value.connections[0].observation=[];
if(fault==='enum_type')value.connections[0].observation.reason={path:'PRIVATE_PATH'};
if(fault==='unavailable_rows')value.available=false;
console.log(JSON.stringify(publicDiagnosticObservation(value)));
""".replace("FAULT", json.dumps(fault))
    completed = subprocess.run([node, "--input-type=module", "-e", script], cwd=staging.ROOT,
        capture_output=True, text=True, check=True, timeout=5)
    assert json.loads(completed.stdout) == {"query_outcome": "invalid_result"}
    assert "PRIVATE" not in completed.stdout + completed.stderr


def custody_report():
    return {"passed": False, "phase": "explicit_approval", "error_code": "forbidden", "diagnostics": {
        "subphase": "invitation_accept", "deadline_exhausted": False, "failure_origin": "core_error", "peers": {},
        "stage_timing": {"offsets_ms": {"failure_observed": 0}, "clipped": False},
        "cleanup": [{"role": "offerer", "incarnation": 1, "attempts": 1, "detach": "ok", "stop": "completed",
                     "retired": True, "budget_ms": 30000}],
        "public_diagnostics": {"offerer": {"query_outcome": "ok", "available": True, "runtime_failure": None,
            "total_connections": 1, "truncated": False, "connections": [
                {"desired": "enabled", "execution": "available", "negotiation": "checking", "reason": "phase_timeout"}]}}}}


@pytest.mark.parametrize("path,value", [
    pytest.param(path, value, id=label) for label, path, value in (
        ("origin", ("failure_origin",), "PRIVATE_ORIGIN"),
        ("origin-type", ("failure_origin",), []),
        ("cleanup-only-phase", ("failure_origin",), "cleanup_failure"),
        ("cleanup-type", ("cleanup",), {}),
        ("role", ("cleanup", 0, "role"), "PRIVATE_ROLE"),
        ("incarnation-bool", ("cleanup", 0, "incarnation"), True),
        ("incarnation-limit", ("cleanup", 0, "incarnation"), 3),
        ("attempts-bool", ("cleanup", 0, "attempts"), True),
        ("attempts-limit", ("cleanup", 0, "attempts"), 3),
        ("detach", ("cleanup", 0, "detach"), "PRIVATE_DETACH"),
        ("stop-type", ("cleanup", 0, "stop"), []),
        ("retired-type", ("cleanup", 0, "retired"), 1),
        ("detach-is-not-exit", ("cleanup", 0, "detach"), "failed"),
        ("budget-bool", ("cleanup", 0, "budget_ms"), True),
        ("budget-float", ("cleanup", 0, "budget_ms"), 30.5),
        ("budget-negative", ("cleanup", 0, "budget_ms"), -1),
        ("budget-limit", ("cleanup", 0, "budget_ms"), 30001),
        ("budget-provenance", ("cleanup", 0, "attempts"), 0),
        ("detach-provenance", ("cleanup", 0, "detach"), "not_attempted"),
        ("actor-roles", ("public_diagnostics",), {"PRIVATE_ROLE": {"query_outcome": "failed"}}),
        ("actor-outcome", ("public_diagnostics", "offerer", "query_outcome"), "PRIVATE_OUTCOME"),
        ("actor-available", ("public_diagnostics", "offerer", "available"), 1),
        ("actor-failure", ("public_diagnostics", "offerer", "runtime_failure"), "PRIVATE_FAILURE"),
        ("actor-failure-type", ("public_diagnostics", "offerer", "runtime_failure"), []),
        ("actor-total-bool", ("public_diagnostics", "offerer", "total_connections"), True),
        ("actor-total-float", ("public_diagnostics", "offerer", "total_connections"), 1.5),
        ("actor-total-negative", ("public_diagnostics", "offerer", "total_connections"), -1),
        ("actor-total-limit", ("public_diagnostics", "offerer", "total_connections"), 257),
        ("actor-truncated", ("public_diagnostics", "offerer", "truncated"), 0),
        ("actor-truncated-provenance", ("public_diagnostics", "offerer", "truncated"), True),
        ("actor-rows", ("public_diagnostics", "offerer", "connections"), {}),
        ("actor-row-count", ("public_diagnostics", "offerer", "connections"), []),
        ("actor-row-type", ("public_diagnostics", "offerer", "connections", 0), []),
        ("actor-enum", ("public_diagnostics", "offerer", "connections", 0, "desired"), "PRIVATE_DESIRED"),
        ("actor-enum-type", ("public_diagnostics", "offerer", "connections", 0, "reason"), []),
        ("actor-unavailable", ("public_diagnostics", "offerer", "available"), False),
    )
])
def test_failure_custody_consumer_rejects_malformed_types_ranges_enums_and_provenance(path, value):
    observed = custody_report()
    pairing.failure_details(copy.deepcopy(observed))
    target = observed["diagnostics"]
    for part in path[:-1]: target = target[part]
    target[path[-1]] = value
    with pytest.raises(ValueError): pairing.failure_details(observed)


@pytest.mark.parametrize("fault", ["origin_missing", "cleanup_missing", "slot_duplicate", "slots_limit", "budget_missing",
    "raw_owner", "raw_actor", "raw_diagnostic", "failed_payload", "deadline_payload", "row_limit"])
def test_failure_custody_consumer_rejects_missing_custody_and_private_extra_fields(fault):
    observed = custody_report()
    diagnostics = observed["diagnostics"]
    if fault == "origin_missing": diagnostics.pop("failure_origin")
    elif fault == "cleanup_missing": diagnostics.pop("cleanup")
    elif fault == "slot_duplicate": diagnostics["cleanup"] *= 2
    elif fault == "slots_limit": diagnostics["cleanup"] *= 5
    elif fault == "budget_missing": diagnostics["cleanup"][0].pop("budget_ms")
    elif fault == "raw_owner": diagnostics["cleanup"][0]["runtime_id"] = "PRIVATE_RUNTIME"
    elif fault == "raw_actor": diagnostics["public_diagnostics"]["offerer"]["connections"][0]["connection"] = "PRIVATE_HANDLE"
    elif fault == "raw_diagnostic": diagnostics["public_diagnostics"]["offerer"]["runtime_epoch"] = "PRIVATE_EPOCH"
    elif fault == "failed_payload": diagnostics["public_diagnostics"]["offerer"] = {"query_outcome": "failed", "error": "PRIVATE_ERROR"}
    elif fault == "deadline_payload": diagnostics["public_diagnostics"]["offerer"] = {"query_outcome": "not_attempted", "reason": "PRIVATE_REASON"}
    else: diagnostics["public_diagnostics"]["offerer"]["connections"] *= 5
    with pytest.raises(ValueError): pairing.failure_details(observed)


def test_maximum_selected_failure_report_fits_existing_byte_bound():
    node, _ = staging.tools()
    script = """
import {pairingDiagnostics,publicDiagnosticObservation,ACTOR_ENUMS} from './examples/typescript-independent-consumer/pairing-diagnostics.mjs';
let now=0;
const d=pairingDiagnostics(()=>now);d.start();now=600000;
d.enter('invitation_accept');d.acceptanceReturned();d.enter('pending_request_wait');d.pendingWait(true);
for(let i=0;i<4096;i++){d.pendingAttempt();d.pendingComplete();}
d.enter('offerer_relationship_wait');
for(const role of ['offerer','answerer']){
  d.snapshot(role,{network:{},service_error:'network_interface_unavailable',contacts:Array(256).fill({trust:'pending_request'}),
    contact_invitations:Array(256).fill({state:'pending'})});
  d.pairing(role,{state:'awaiting_approval'});d.connections(role,256,256,256);
}
for(const [role,incarnation] of [['offerer',1],['answerer',1],['contender',1],['offerer',2]]){
  Object.assign(d.owned(role,incarnation),{attempts:2,detach:'failed',stop:'completed',retired:false,budget_ms:30000});
}
d.freezeFailure('core_error');
const observation=Object.fromEntries(Object.entries(ACTOR_ENUMS).map(([key,values])=>[key,[...values].sort((a,b)=>b.length-a.length)[0]]));
const actors=publicDiagnosticObservation({available:true,runtime_failure:'adapter_quarantined',total_connections:Number.MAX_SAFE_INTEGER,
  truncated:true,connections:Array(4).fill({connection:'PRIVATE_HANDLE',observation})});
d.publicProbe({offerer:actors,answerer:actors});d.probe(Object.fromEntries(['offerer','answerer'].map(role=>
  [role,{query_outcome:'ok',state:'awaiting_approval',expired:false}])));
console.log(JSON.stringify({passed:false,phase:'explicit_approval',error_code:'resource_exhausted',diagnostics:d.failure(true)}));
"""
    completed = subprocess.run([node, "--input-type=module", "-e", script], cwd=staging.ROOT,
        capture_output=True, text=True, check=True, timeout=5)
    assert len(completed.stdout.encode()) <= 4096
    assert "PRIVATE" not in completed.stdout + completed.stderr
    details = pairing.failure_details(json.loads(completed.stdout))
    assert details["diagnostics"]["public_diagnostics"]["offerer"]["total_connections"] == 256


def test_node_diagnostic_projection_caps_counts_and_selects_no_private_payloads():
    node, _ = staging.tools()
    script = """
import {pairingDiagnostics, SUBPHASES, ERROR_CODES} from './examples/typescript-independent-consumer/pairing-diagnostics.mjs';
const diagnostics = pairingDiagnostics();
diagnostics.start();
diagnostics.enter('invitation_wait');
diagnostics.snapshot('answerer', {contacts: Array(300).fill({trust:'pending_request',destination_hash:'PRIVATE_DESTINATION'}),
  contact_invitations: Array(300).fill({state:'pending',sdp:'PRIVATE_SDP'})}, 'PRIVATE_DESTINATION');
diagnostics.pairing('answerer', {state:'PRIVATE_STATE',pairing_code:'PRIVATE_PAIRING_CODE',token:'PRIVATE_TOKEN'});
diagnostics.connections('answerer',300,299,298);
diagnostics.freezeFailure();
console.log(JSON.stringify({diagnostics:diagnostics.failure(),subphases:[...SUBPHASES],errors:[...ERROR_CODES]}));
"""
    completed = subprocess.run([node, "--input-type=module", "-e", script], cwd=staging.ROOT,
        capture_output=True, text=True, check=True, timeout=15)
    assert "PRIVATE" not in completed.stdout
    value = json.loads(completed.stdout)
    assert set(value["subphases"]) == set().union(*pairing.SUBPHASES.values())
    contract = json.loads((staging.ROOT / "contracts/core-api/error-v1.schema.json").read_text())
    assert set(value["errors"]) == pairing.ERROR_CODES == set(contract["properties"]["error"]["properties"]["code"]["enum"])
    observed = {"passed": False, "phase": "explicit_approval", "error_code": "unavailable", "diagnostics": value["diagnostics"]}
    pairing.failure_details(observed)
    peer = observed["diagnostics"]["peers"]["answerer"]
    assert peer["last_snapshot"]["contacts"] == peer["last_snapshot"]["pending_invitations"] == 256
    assert peer["last_snapshot"]["counts_capped"] is True
    assert peer["last_pairing"] == {"state": "unknown", "code_present": True}
    assert peer["last_connections"] == {"total": 256, "checked": 256, "ready": 256, "counts_capped": True}


def test_monotonic_stage_offsets_and_read_counts_clip_and_freeze_without_private_values():
    node, _ = staging.tools()
    script = """
import {pairingDiagnostics} from './examples/typescript-independent-consumer/pairing-diagnostics.mjs';
let now = 100;
const diagnostics = pairingDiagnostics(() => now);
diagnostics.start();
now = 90;
diagnostics.enter('invitation_accept');
now = 900000;
diagnostics.acceptanceReturned();
diagnostics.pendingWait(false);
for (let i=0;i<4100;i++) { diagnostics.pendingAttempt(); diagnostics.pendingComplete(); }
diagnostics.snapshot('offerer',{contacts:[],contact_invitations:[],sdp:'PRIVATE_SDP'},'PRIVATE_DESTINATION');
now = 'PRIVATE_CLOCK';
diagnostics.freezeFailure();
const before = diagnostics.failure();
now = 2000000;
diagnostics.acceptanceReturned();
diagnostics.pendingWait(true);
diagnostics.pendingAttempt(); diagnostics.pendingComplete();
diagnostics.enter('retirement');diagnostics.freezeFailure('cleanup_failure');
diagnostics.snapshot('offerer',{contacts:[],contact_invitations:[]});
diagnostics.pairing('offerer',{state:'retired'});diagnostics.connections('offerer',0,0,0);
console.log(JSON.stringify({before,after:diagnostics.failure()}));
"""
    completed = subprocess.run([node, "--input-type=module", "-e", script], cwd=staging.ROOT,
        capture_output=True, text=True, check=True, timeout=15)
    assert "PRIVATE" not in completed.stdout
    result = json.loads(completed.stdout)
    assert result["before"] == result["after"]
    diagnostics = result["before"]
    assert diagnostics["stage_timing"] == {"offsets_ms": {"invitation_accept_started": 0,
        "invitation_accept_returned": 600000, "pending_request_wait_entered": 600000,
        "failure_observed": 600000}, "clipped": True}
    assert diagnostics["post_accept_reads"] == {"attempts": 4096, "completed": 4096,
        "clipped": True, "deadline_exhausted_at_entry": False}
    pairing.failure_details({"passed": False, "phase": "explicit_approval", "error_code": "unavailable", "diagnostics": diagnostics})


@pytest.mark.parametrize("fault", ["missing_timing", "unknown_timing_field", "absolute_timestamp", "negative_offset",
    "oversized_offset", "boolean_offset", "nonfinite_offset", "offset_order", "missing_failure", "missing_start",
    "clip_type", "negative_count", "oversized_count", "boolean_count", "count_order", "entry_type",
    "missing_entry", "missing_counts", "provenance", "provenance_missing"])
def test_timing_read_count_and_snapshot_provenance_contract_rejects_unsafe_fields(fault):
    observed = {"passed": False, "phase": "explicit_approval", "error_code": "unavailable", "diagnostics": {
        "subphase": "pending_request_wait", "deadline_exhausted": True, "failure_origin": "unknown", "cleanup": [],
        "stage_timing": {"offsets_ms": {"invitation_accept_started": 1, "invitation_accept_returned": 2,
            "pending_request_wait_entered": 2, "failure_observed": 3}, "clipped": False},
        "post_accept_reads": {"attempts": 1, "completed": 1, "clipped": False, "deadline_exhausted_at_entry": False},
        "peers": {"offerer": {"last_snapshot": {"contacts": 0, "invitations": 0, "pending_invitations": 0,
            "pending_requests": 0, "approved_contacts": 0, "matching_pending_request": False,
            "matching_approved_contact": False, "counts_capped": False, "observed_subphase": "pending_request_wait",
            "network_present": True, "service_error": None}}}}}
    pairing.failure_details(copy.deepcopy(observed))
    diagnostics = observed["diagnostics"]
    offsets = diagnostics["stage_timing"]["offsets_ms"]
    reads = diagnostics["post_accept_reads"]
    if fault == "missing_timing": diagnostics.pop("stage_timing")
    elif fault == "unknown_timing_field": offsets["PRIVATE_IDENTIFIER"] = 1
    elif fault == "absolute_timestamp": diagnostics["stage_timing"]["wall_clock"] = 1234567890
    elif fault == "negative_offset": offsets["failure_observed"] = -1
    elif fault == "oversized_offset": offsets["failure_observed"] = 600001
    elif fault == "boolean_offset": offsets["failure_observed"] = True
    elif fault == "nonfinite_offset": offsets["failure_observed"] = float("inf")
    elif fault == "offset_order": offsets["failure_observed"] = 0
    elif fault == "missing_failure": offsets.pop("failure_observed")
    elif fault == "missing_start": offsets.pop("invitation_accept_started")
    elif fault == "clip_type": diagnostics["stage_timing"]["clipped"] = "PRIVATE_CLOCK"
    elif fault == "negative_count": reads["attempts"] = -1
    elif fault == "oversized_count": reads["attempts"] = 4097
    elif fault == "boolean_count": reads["attempts"] = True
    elif fault == "count_order": reads["completed"] = 2
    elif fault == "entry_type": reads["deadline_exhausted_at_entry"] = "PRIVATE_VALUE"
    elif fault == "missing_entry": offsets.pop("pending_request_wait_entered")
    elif fault == "missing_counts": diagnostics.pop("post_accept_reads")
    elif fault == "provenance": diagnostics["peers"]["offerer"]["last_snapshot"]["observed_subphase"] = "PRIVATE_IDENTIFIER"
    else: diagnostics["peers"]["offerer"]["last_snapshot"].pop("observed_subphase")
    with pytest.raises(ValueError): pairing.failure_details(observed)


@pytest.mark.parametrize("fault", ["subphase", "phase_mismatch", "role", "state", "pairing_code", "private_field",
    "envelope_field", "error_code", "negative", "oversized", "boolean_count", "string_flag", "inconsistent"])
def test_pairing_failure_report_rejects_unselected_private_or_unbounded_fields(fault):
    observed = {"passed": False, "phase": "explicit_approval", "error_code": "unavailable",
        "diagnostics": {"subphase": "offerer_ready_wait", "deadline_exhausted": True, "failure_origin": "unknown", "cleanup": [],
            "stage_timing": {"offsets_ms": {"failure_observed": 1}, "clipped": False}, "peers": {"offerer": {
            "last_pairing": {"state": "awaiting_approval", "code_present": False},
            "last_connections": {"total": 1, "checked": 1, "ready": 0, "counts_capped": False}}}}}
    pairing.failure_details(copy.deepcopy(observed))
    diagnostics = observed["diagnostics"]
    peer = diagnostics["peers"]["offerer"]
    if fault == "subphase": diagnostics["subphase"] = "PRIVATE_TOKEN"
    elif fault == "phase_mismatch": diagnostics["subphase"] = "offer_begin"
    elif fault == "role": diagnostics["peers"]["PRIVATE_IDENTITY"] = diagnostics["peers"].pop("offerer")
    elif fault == "state": peer["last_pairing"]["state"] = "PRIVATE_SDP"
    elif fault == "pairing_code": peer["last_pairing"]["pairing_code"] = "PRIVATE_PAIRING_CODE"
    elif fault == "private_field": peer["sdp"] = "PRIVATE_SDP"
    elif fault == "envelope_field": observed["token"] = "PRIVATE_TOKEN"
    elif fault == "error_code": observed["error_code"] = "private_token"
    elif fault == "negative": peer["last_connections"]["total"] = -1
    elif fault == "oversized": peer["last_connections"]["total"] = 257
    elif fault == "boolean_count": peer["last_connections"]["total"] = True
    elif fault == "string_flag": peer["last_connections"]["counts_capped"] = "PRIVATE_TOKEN"
    else: peer["last_connections"]["ready"] = 2
    with pytest.raises(ValueError): pairing.failure_details(observed)


@pytest.mark.parametrize("fault", ["role", "state", "code", "timestamp", "error", "expired_type", "unknown_outcome"])
def test_failure_probe_report_cannot_retain_private_or_unselected_result_fields(fault):
    observed = {"passed": False, "phase": "explicit_approval", "error_code": "forbidden",
        "diagnostics": {"subphase": "invitation_accept", "deadline_exhausted": False, "failure_origin": "unknown", "cleanup": [],
            "stage_timing": {"offsets_ms": {"failure_observed": 1}, "clipped": False}, "peers": {},
            "failure_probe": {"offerer": {"query_outcome": "ok", "state": "transferred", "expired": False}}}}
    pairing.failure_details(copy.deepcopy(observed))
    probe = observed["diagnostics"]["failure_probe"]
    value = probe["offerer"]
    if fault == "role": probe["PRIVATE_IDENTITY"] = probe.pop("offerer")
    elif fault == "state": value["state"] = "PRIVATE_STATE"
    elif fault == "code": value["pairing_code"] = "PRIVATE_CODE"
    elif fault == "timestamp": value["expires_at"] = 123456
    elif fault == "error": probe["offerer"] = {"query_outcome": "failed", "error": "PRIVATE_ERROR"}
    elif fault == "expired_type": value["expired"] = "PRIVATE_TIMESTAMP"
    else: probe["offerer"] = {"query_outcome": "PRIVATE_ERROR"}
    with pytest.raises(ValueError): pairing.failure_details(observed)


def test_pairing_relay_settings_serialize_real_public_query_into_accepted_core_update(host):
    service = host()
    stream = bind_service_stream(service, lambda: Grant(
        "independent-settings", frozenset({"observe", "read", "send"}), ("local",)))

    def invoke(operation, **params):
        return decode_frame(stream.exchange(encode_frame({"api_version": 1,
            "request_id": "independent:relay-settings", "operation": operation, "params": params})))

    try:
        capabilities = invoke("runtime.capabilities")
        assert capabilities["ok"], capabilities
        profile = capabilities["result"]["profiles"][0]
        queried = invoke("call.settings_query", profile=profile)
        assert queried["ok"], queried
        settings = queried["result"]["settings"]
        assert settings["turn_configured"] is False
        # Replaying a public query as an update was the actual producer defect.
        rejected = invoke("call.settings_update", profile=profile,
                          settings={**settings, "turn_broker_consent": True, "relay_only": True})
        assert not rejected["ok"] and rejected["error"]["code"] == "invalid_request"
        node, _ = staging.tools()
        script = """
import { freshRelaySettings } from './examples/typescript-independent-consumer/relay-settings.mjs';
let input = '';
for await (const chunk of process.stdin) input += chunk;
process.stdout.write(JSON.stringify(freshRelaySettings(JSON.parse(input))));
"""
        completed = subprocess.run([node, "--input-type=module", "-e", script], cwd=staging.ROOT,
            input=json.dumps(settings), capture_output=True, text=True, check=True, timeout=15)
        update = json.loads(completed.stdout)
        assert set(update) == {"stun_urls", "turn_url", "turn_username", "turn_broker_url",
            "signal_mailbox_url", "store_call_signaling", "turn_broker_consent", "relay_only"}
        accepted = invoke("call.settings_update", profile=profile, settings=update)
        assert accepted["ok"], accepted
        applied = invoke("call.settings_query", profile=profile)
        assert applied["ok"], applied
        assert applied["result"]["settings"]["turn_broker_consent"] is True
        assert applied["result"]["settings"]["relay_only"] is True
    finally:
        stream.close()


def test_application_owned_runtime_framing_and_retirement_use_real_subprocesses():
    node, _ = staging.tools()
    result = subprocess.run([node, "--test", "--test-reporter=tap",
                             str(staging.ROOT / "tests/core-ui-boundary/app_owned_runtime.test.mjs")],
                            cwd=staging.ROOT, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-1000:]
    assert "# tests 26" in result.stdout
    assert "# pass 26" in result.stdout and "# fail 0" in result.stdout and "# skipped 0" in result.stdout


def lifetime_fixture(tmp_path, fault="", *, probe=""):
    """Actual installed-app JS control flow; inert SDK/runtime only, not native proof."""
    node, _ = staging.tools()
    log = tmp_path / "lifetime.jsonl"
    completed = subprocess.run([node, "--import", (staging.ROOT /
        "tests/core-ui-boundary/pairing_diagnostic_fixture.mjs").as_uri(),
        str(staging.APPLICATION / "pairing-check.mjs"), "--runtime", "unused", "--data-directory", "unused"],
        cwd=staging.ROOT, env={**os.environ, "PAIRING_DIAGNOSTIC_FAULT": fault,
            "PAIRING_DIAGNOSTIC_PROBE": probe, "PAIRING_DIAGNOSTIC_LOG": str(log)},
        capture_output=True, text=True, timeout=15)
    assert "private" not in (completed.stdout + completed.stderr).lower()
    assert len(completed.stdout.encode()) <= 4096
    return completed, json.loads(completed.stdout), [json.loads(line) for line in log.read_text().splitlines()]


def test_primary_core_failure_survives_secondary_cleanup_rejection(tmp_path):
    completed, observed, events = lifetime_fixture(tmp_path, "invitation_accept", probe="retirement_failure")
    assert completed.returncode == 1
    assert observed["phase"] == "explicit_approval"
    assert observed["error_code"] == "forbidden"
    assert observed["diagnostics"]["subphase"] == "invitation_accept"
    assert observed["diagnostics"]["failure_origin"] == "core_error"
    assert observed["diagnostics"]["cleanup"] == [
        {"role": role, "incarnation": 1, "attempts": 1, "detach": "ok", "stop": "failed", "retired": False,
         "budget_ms": 30000} for role in ("offerer", "answerer")]
    assert [item["original"] for item in events if item["event"] == "error_identity"] == [True, True]
    pairing.failure_details(observed)
    assert [item["role"] for item in events if item["event"] == "stop"] == ["offerer", "answerer"]


@pytest.mark.parametrize("fault", ["throw_undefined", "throw_null", "throw_number", "throw_string", "throw_false"])
def test_unknown_primitive_throw_retains_identity_and_stage_despite_cleanup_failure(tmp_path, fault):
    completed, observed, events = lifetime_fixture(tmp_path, fault, probe="retirement_failure")
    assert completed.returncode == 1 and observed["phase"] == "explicit_approval"
    assert observed["error_code"] == "unavailable"
    diagnostics = pairing.failure_details(observed)["diagnostics"]
    assert diagnostics["subphase"] == "invitation_accept" and diagnostics["failure_origin"] == "unknown"
    assert diagnostics["deadline_exhausted"] is False
    assert diagnostics["stage_timing"]["offsets_ms"] == {"invitation_accept_started": 0, "failure_observed": 0}
    assert all(row["stop"] == "failed" and row["retired"] is False for row in diagnostics["cleanup"])
    assert [row["original"] for row in events if row["event"] == "error_identity"] == [True, True]


@pytest.mark.parametrize("fault,subphase,origin,elapsed", [
    ("invitation_wait", "invitation_wait", "wait_deadline", 300000),
    ("invitation_budget", "invitation_guard", "budget_deadline", 240001),
])
def test_owned_deadline_identity_survives_zero_budget_cleanup(tmp_path, fault, subphase, origin, elapsed):
    completed, observed, events = lifetime_fixture(tmp_path, fault, probe="zero_budget_failure")
    assert completed.returncode == 1 and observed["phase"] == "explicit_approval"
    diagnostics = pairing.failure_details(observed)["diagnostics"]
    assert diagnostics["subphase"] == subphase and diagnostics["failure_origin"] == origin
    assert diagnostics["deadline_exhausted"] is True
    assert diagnostics["stage_timing"]["offsets_ms"] == {"failure_observed": elapsed}
    assert all(row["budget_ms"] == 0 and row["stop"] == "failed" and row["retired"] is False
               for row in diagnostics["cleanup"])
    assert [row["role"] for row in events if row["event"] == "stop"] == ["offerer", "answerer"]
    assert max(i for i, row in enumerate(events) if row["event"] in {"probe", "public_probe"}) < next(
        i for i, row in enumerate(events) if row["event"] == "stop")


@pytest.mark.parametrize("mode", ["reject", "invalid", "advance_clock", "diagnostic_throw", "projection_throw", "observer_throw", "mutate_error"])
def test_probe_failure_or_clock_advance_never_substitutes_primary_error(tmp_path, mode):
    completed, observed, events = lifetime_fixture(tmp_path, "invitation_accept", probe=mode)
    assert completed.returncode == 1 and observed["phase"] == "explicit_approval" and observed["error_code"] == "forbidden"
    diagnostics = pairing.failure_details(observed)["diagnostics"]
    assert diagnostics["subphase"] == "invitation_accept" and diagnostics["failure_origin"] == "core_error"
    assert diagnostics["deadline_exhausted"] is False
    assert diagnostics["stage_timing"]["offsets_ms"] == {"invitation_accept_started": 0, "failure_observed": 0}
    assert [row["original"] for row in events if row["event"] == "error_identity"] == [True, True]
    assert len([row for row in events if row["event"] == "probe"]) == 2
    public = diagnostics["public_diagnostics"]
    expected = ({"query_outcome": "not_attempted", "reason": "deadline_exhausted"} if mode == "advance_clock"
                else {"query_outcome": "invalid_result"} if mode == "invalid"
                else {"query_outcome": "failed"})
    if mode not in {"observer_throw", "mutate_error"}:
        assert public == {role: expected for role in ("offerer", "answerer")}
    assert [row["role"] for row in events if row["event"] == "stop"] == ["offerer", "answerer"]


def test_arbitrary_deadline_message_cannot_supply_owned_failure_origin(tmp_path):
    _, observed, _ = lifetime_fixture(tmp_path, "forged_deadline_message", probe="retirement_failure")
    assert observed["phase"] == "explicit_approval" and observed["diagnostics"]["failure_origin"] == "unknown"


@pytest.mark.parametrize("fault,detach,stop", [
    ("final_exit_missing", "ok", "failed"), ("final_detach_failure", "failed", "completed")])
def test_cleanup_only_failure_keeps_distinct_incarnations_and_detach_facts(tmp_path, fault, detach, stop):
    completed, observed, events = lifetime_fixture(tmp_path, fault)
    assert completed.returncode == 1 and observed["phase"] == "retirement"
    diagnostics = pairing.failure_details(observed)["diagnostics"]
    assert diagnostics["failure_origin"] == "cleanup_failure" and diagnostics["subphase"] == "retirement"
    facts = diagnostics["cleanup"]
    assert [(row["role"], row["incarnation"]) for row in facts] == [
        ("offerer", 1), ("answerer", 1), ("contender", 1), ("offerer", 2)]
    assert all(row["retired"] is True for row in facts[:3])
    assert facts[-1] == {"role": "offerer", "incarnation": 2, "attempts": 1, "detach": detach, "stop": stop,
                         "retired": False, "budget_ms": 30000}
    assert not any(row["event"] in {"probe", "public_probe"} for row in events)
    assert "public_diagnostics" not in diagnostics and "failure_probe" not in diagnostics


def test_detach_failure_cannot_be_counted_as_retired_despite_positive_stop(tmp_path):
    _, observed, _ = lifetime_fixture(tmp_path, "invitation_accept", probe="detach_failure")
    diagnostics = pairing.failure_details(observed)["diagnostics"]
    assert observed["phase"] == "explicit_approval" and observed["error_code"] == "forbidden"
    assert all(row["detach"] == "failed" and row["stop"] == "completed" and row["retired"] is False
               for row in diagnostics["cleanup"])


def test_actual_js_shared_session_lifetime_preserves_order_and_original_pending_key(tmp_path):
    completed, observed, events = lifetime_fixture(tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert observed == {key: value for key, value in pairing.CHECKS.items() if not key.startswith("efs_")}
    assert [(item["role"], item["incarnation"]) for item in events if item["event"] == "start"] == [
        ("offerer", 1), ("answerer", 1), ("offerer", 2)]
    exits = [(index, item) for index, item in enumerate(events) if item["event"] == "exited"]
    assert [(item["role"], item["incarnation"], item["code"]) for _, item in exits] == [
        ("contender", 1, 2), ("answerer", 1, 0), ("offerer", 1, 0), ("offerer", 2, 0)]
    pending = [(index, item) for index, item in enumerate(events) if item["event"] == "enqueue" and item["pending"]]
    assert len(pending) == 4 and len({item["key"] for _, item in pending}) == 1
    assert [item["incarnation"] for _, item in pending] == [1, 1, 2, 2]
    assert [item["changed"] for _, item in pending] == [False, False, False, True]
    assert exits[1][0] < pending[0][0] < pending[1][0] < exits[2][0] < pending[2][0] < pending[3][0] < exits[3][0]
    detached = next(index for index, item in enumerate(events) if item["event"] == "close" and item["role"] == "offerer" and item["session"] == 1)
    reattached = next(index for index in range(detached + 1, len(events)) if events[index]["event"] == "open")
    survivor = [item["operation"] for item in events[detached:reattached] if item["event"] == "request"]
    assert survivor == ["runtime.capabilities", "profile.query", "application.snapshot", "message.query"]
    assert not any(item["event"] in {"start", "stop"} for item in events[detached:reattached])
    assert len([item for item in events if item["event"] == "request" and item["operation"] == "profile.create"]) == 2
    assert not any(item["event"] == "request" and item["operation"] in {"runtime.stop", "native.command"} for item in events)
    assert all(0 <= item["remaining"] <= 30000 for item in events if item["event"] == "stop")


@pytest.mark.parametrize("fault,subphase", [
    ("detach_stops_owner", "client_detach_survivor"), ("survivor_identity", "second_client_attach"),
    ("snapshot_profile", "second_client_attach"), ("survivor_contact", "second_client_attach"),
    ("survivor_message", "second_client_attach"), ("extra_authority", "second_client_attach"),
    ("changed_operations", "second_client_attach"), ("reattach_wrong_owner", "client_reattach"),
    ("slot_never_releases", "client_reattach"),
    ("second_client_failure", "second_client_attach"), ("refused_alive", "competing_owner_refusal"),
    ("receiver_not_exited", "pending_enqueue"), ("pending_terminal", "pending_enqueue"),
    ("pending_absent", "pending_enqueue"), ("replay_duplicate", "pending_enqueue"),
    ("replay_new_handle", "pending_enqueue"), ("reopened_identity", "pending_owner_reopen"),
    ("reopened_contact", "pending_owner_reopen"), ("reopened_handle", "pending_owner_reopen"),
    ("original_key_lost", "original_key_replay"), ("changed_payload_succeeds", "original_key_replay"),
    ("final_exit_missing", "retirement"),
])
def test_actual_js_lifetime_faults_cannot_manufacture_qualification(tmp_path, fault, subphase):
    completed, observed, events = lifetime_fixture(tmp_path, fault)
    assert completed.returncode == 1
    details = pairing.failure_details(observed)
    assert details["application_phase"] == ("retirement" if subphase == "retirement" else "shared_host_lifetime")
    assert details["diagnostics"]["subphase"] == subphase
    assert "checks" not in observed and observed["passed"] is False
    # Every acquired successful runtime is still asked to stop on failed assertions/negotiation.
    starts = {(item["role"], item["incarnation"]) for item in events if item["event"] == "start"}
    stops = {(item["role"], item["incarnation"]) for item in events if item["event"] == "stop"}
    assert starts <= stops
    receiver_exit = next((index for index, item in enumerate(events) if item["event"] == "exited" and item["role"] == "answerer"), None)
    for index, item in enumerate(events):
        if item["event"] == "enqueue" and item["pending"]: assert receiver_exit is not None and receiver_exit < index
    exited_roles = set()
    for item in events:
        if item["event"] == "exited": exited_roles.add(item["role"])
        if item["event"] == "probe": assert item["role"] not in exited_roles


@pytest.mark.parametrize("fault,phase", [("startup_observation_failure", "fresh_profiles"),
    ("initial_negotiation_failure", "fresh_profiles")])
def test_owner_custody_precedes_startup_observation_and_sdk_negotiation(tmp_path, fault, phase):
    completed, observed, events = lifetime_fixture(tmp_path, fault)
    assert completed.returncode == 1
    assert pairing.failure_details(observed)["application_phase"] == phase
    assert [item["role"] for item in events if item["event"] == "start"] == ["offerer"]
    assert [item["role"] for item in events if item["event"] == "stop"] == ["offerer"]
    assert not any(item["event"] == "request" for item in events)


def test_replacement_session_retries_only_bounded_released_slot_without_another_owner(tmp_path):
    completed, observed, events = lifetime_fixture(tmp_path, "slot_releases")
    assert completed.returncode == 0 and observed["shared_host_sdk_sessions"] == 2
    assert len([item for item in events if item["event"] == "open" and item["role"] == "offerer"]) == 6
    assert len([item for item in events if item["event"] == "start"]) == 3
    assert observed["clean_host_exits"] == 3


def test_lifetime_cleanup_uses_actual_remaining_budget_and_still_requests_all_owned_stops(tmp_path):
    completed, observed, events = lifetime_fixture(tmp_path, "pending_budget_exhausted")
    assert completed.returncode == 1 and observed["passed"] is False
    assert observed["diagnostics"]["deadline_exhausted"] is True
    assert any(item["event"] == "stop" and item["role"] == "offerer" and item["remaining"] == 0 for item in events)
    assert all(item["operation"] == "peer.pairing_query" or item.get("timeout", 30000) <= 30000
               for item in events if item["event"] == "request")


def test_conflicting_replay_cannot_insert_changed_text_before_expected_error(tmp_path):
    completed, observed, events = lifetime_fixture(tmp_path, "changed_payload_insert_then_conflict")
    assert [item for item in events if item["event"] == "conflict_insert"] == [
        {"event": "conflict_insert", "outbound_records": 3, "matching_changed": 1, "error_code": "idempotency_conflict"}]
    pending = [item for item in events if item["event"] == "enqueue" and item["pending"]]
    assert len(pending) == 4 and pending[-1]["changed"] is True
    assert len({item["key"] for item in pending}) == 1
    assert completed.returncode == 1
    details = pairing.failure_details(observed)
    assert details["application_phase"] == "shared_host_lifetime"
    assert details["diagnostics"]["subphase"] == "original_key_replay"
    assert observed["passed"] is False and "checks" not in observed
    assert [(item["role"], item["incarnation"]) for item in events if item["event"] == "exited"] == [
        ("contender", 1), ("answerer", 1), ("offerer", 1), ("offerer", 2)]


LIFETIME_CHECKS = {key: value for key, value in pairing.CHECKS.items() if key in {
    "clean_host_exits", "concurrent_owner_refusals", "rejected_owner_exits", "pending_message_before_owner_stop",
    "reopened_original_message_and_key", "reopened_same_public_identity", "runtime_lock_reacquired",
    "owner_native_host_shutdown_acknowledgments", "shared_host_sdk_sessions", "closed_sdk_session_survivor_usable",
    "reattached_sdk_session_same_authorized_state"}}


@pytest.mark.parametrize("key", LIFETIME_CHECKS)
@pytest.mark.parametrize("fault", ["missing", "wrong", "string", "float", "boolean_integer"])
def test_lifetime_report_requires_every_exact_observation_and_type(key, fault):
    record = pairing_record()
    expected = LIFETIME_CHECKS[key]
    if fault == "missing": record["checks"].pop(key)
    elif fault == "wrong": record["checks"][key] = False if type(expected) is bool else expected - 1
    elif fault == "string": record["checks"][key] = str(expected)
    elif fault == "float": record["checks"][key] = float(expected)
    else: record["checks"][key] = int(expected) if type(expected) is bool else True
    with pytest.raises(ValueError): pairing.verify_report(record, "a" * 40, "b" * 40)


@pytest.mark.parametrize("fault", ["old_level", "old_scope", "extra", "helper", "consumer_process", "android", "SC26"])
def test_lifetime_report_rejects_prior_scope_and_unexecuted_claims(fault):
    record = pairing_record()
    if fault == "old_level": record["evidence_level"] = "windows_installed_public_sdk_supervisor_pairing_and_receipts"
    elif fault == "old_scope": record["scope"] = bootstrap.SCOPE
    elif fault == "extra": record["checks"]["isolated_helper_exits"] = 1
    else: record["scope"] += " " + fault + " qualification"
    with pytest.raises(ValueError): pairing.verify_report(record, "a" * 40, "b" * 40)


@pytest.mark.parametrize("fault", ["source", "tree", "failed", "scope", "inside_checkout", "integer_check",
    "application_missing", "application_hash", "host_pom_missing", "host_aar_changed", "sdk_module_missing", "apk_missing"])
def test_android_distribution_requires_both_publications_apks_and_exact_scope(fault):
    identity = {"source_commit": "a" * 40, "source_tree": "b" * 40}
    artifacts = {path.relative_to(staging.ROOT).as_posix(): "c" * 64 for path in android_distribution.ARTIFACTS}
    record = {"v": 1, "passed": True, **identity, "checks": dict(android_distribution.CHECKS),
        "scope": android_distribution.SCOPE, "artifacts": dict(artifacts),
        "application_files": {name: "d" * 64 for name in android_distribution.APPLICATION_FILES}}
    android_distribution.verify_record(record, identity, artifacts)
    if fault == "source": record["source_commit"] = "e" * 40
    elif fault == "tree": record["source_tree"] = "e" * 40
    elif fault == "failed": record["passed"] = False
    elif fault == "scope": record["scope"] = "Successful OS confirmation and peer receipts"
    elif fault == "inside_checkout": record["checks"]["outside_checkout"] = False
    elif fault == "integer_check": record["checks"]["outside_checkout"] = 1
    elif fault == "application_missing": record["application_files"].pop("app/build.gradle.kts")
    elif fault == "application_hash": record["application_files"]["app/build.gradle.kts"] = "missing"
    else:
        name = next(name for name in artifacts if
            (fault == "host_pom_missing" and "core-runtime-host" in name and name.endswith(".pom")) or
            (fault == "host_aar_changed" and "core-runtime-host" in name and name.endswith(".aar")) or
            (fault == "sdk_module_missing" and "core-client" in name and name.endswith(".module")) or
            (fault == "apk_missing" and name.endswith("consumer.apk")))
        if fault == "host_aar_changed": record["artifacts"][name] = "e" * 64
        else: record["artifacts"].pop(name)
    with pytest.raises(ValueError): android_distribution.verify_record(record, identity, artifacts)


def test_android_staging_cannot_resolve_producer_checkout_as_application():
    with pytest.raises(ValueError, match="outside checkout"):
        android_staging.stage(staging.ROOT)


def android_installed_manifest():
    # Exact SDK-decoded consumer manifest from d0babe9 / CI42723779984,
    # artifact13723116006. Raw binary manifest SHA256:
    # 26f95238c753ad13c543b6c570e4397a3975983c35f9aeca4f0fafb1f7e131ce.
    # Source archive SHA256 (validated by lead before extraction):
    # d9ab9c343e5f4cdad9958247a0140525802571547b443b5b9022c94305d685c9.
    # Manifest admission evidence only; neither independent device case ran.
    return ET.parse(staging.ROOT / "tests/core-ui-boundary/android_consumer_manifest.xml").getroot()


@pytest.mark.parametrize("protection", ["0x2", "signature", "2", "0x00000002", "0X00000002"])
def test_actual_compiled_consumer_manifest_requires_exact_signature_authority(protection):
    manifest = android_installed_manifest()
    android_distribution.verify_manifest(manifest)
    ns = "{http://schemas.android.com/apk/res/android}"
    permission = next(node for node in manifest.findall("permission")
        if node.get(ns + "name") == android_distribution.APP_ID + ".permission.MESH_CORE_API")
    assert permission.get(ns + "protectionLevel") == "0x2"  # apkanalyzer's actual rendering.
    permission.set(ns + "protectionLevel", protection)
    android_distribution.verify_manifest(manifest)


@pytest.mark.parametrize("fault", ["package", "application_name", "backup", "application_process",
    "missing_application", "duplicate_application", "missing_core", "duplicate_core", "core_permission",
    "missing_core_permission", "core_exported", "missing_core_exported", "core_process", "core_isolated",
    "missing_bootstrap", "duplicate_bootstrap", "bootstrap_exported", "missing_bootstrap_exported",
    "bootstrap_process", "missing_bootstrap_process", "bootstrap_isolated", "missing_declaration",
    "duplicate_declaration", "missing_protection", "normal", "dangerous", "signature_or_system",
    "privileged_flags", "other_flags", "text_flags", "malformed_protection", "reference_protection",
    "missing_uses_permission"])
def test_installed_consumer_manifest_rejects_authority_and_process_substitutions(fault):
    manifest = android_installed_manifest()
    android_distribution.verify_manifest(manifest)
    ns = "{http://schemas.android.com/apk/res/android}"
    application = manifest.find("application")
    core, bootstrap_service = application.findall("service")
    permission_name = android_distribution.APP_ID + ".permission.MESH_CORE_API"
    permission = next(node for node in manifest.findall("permission") if node.get(ns + "name") == permission_name)
    if fault == "package": manifest.set("package", "com.other.application")
    elif fault == "application_name": application.set(ns + "name", "com.other.Application")
    elif fault == "backup": application.set(ns + "allowBackup", "true")
    elif fault == "application_process": application.set(ns + "process", ":other")
    elif fault == "missing_application": manifest.remove(application)
    elif fault == "duplicate_application": manifest.append(copy.deepcopy(application))
    elif fault == "missing_core": application.remove(core)
    elif fault == "duplicate_core": application.append(copy.deepcopy(core))
    elif fault == "core_permission": core.set(ns + "permission", "com.other.PERMISSION")
    elif fault == "missing_core_permission": core.attrib.pop(ns + "permission")
    elif fault == "core_exported": core.set(ns + "exported", "false")
    elif fault == "missing_core_exported": core.attrib.pop(ns + "exported")
    elif fault == "core_process": core.set(ns + "process", ":mesh_bootstrap")
    elif fault == "core_isolated": core.set(ns + "isolatedProcess", "true")
    elif fault == "missing_bootstrap": application.remove(bootstrap_service)
    elif fault == "duplicate_bootstrap": application.append(copy.deepcopy(bootstrap_service))
    elif fault == "bootstrap_exported": bootstrap_service.set(ns + "exported", "true")
    elif fault == "missing_bootstrap_exported": bootstrap_service.attrib.pop(ns + "exported")
    elif fault == "bootstrap_process": bootstrap_service.set(ns + "process", ":other")
    elif fault == "missing_bootstrap_process": bootstrap_service.attrib.pop(ns + "process")
    elif fault == "bootstrap_isolated": bootstrap_service.set(ns + "isolatedProcess", "true")
    elif fault == "missing_declaration": manifest.remove(permission)
    elif fault == "duplicate_declaration": manifest.append(copy.deepcopy(permission))
    elif fault == "missing_protection": permission.attrib.pop(ns + "protectionLevel")
    elif fault == "missing_uses_permission":
        manifest.remove(next(node for node in manifest.findall("uses-permission") if node.get(ns + "name") == permission_name))
    else:
        permission.set(ns + "protectionLevel", {"normal": "0x0", "dangerous": "1", "signature_or_system": "0x3",
            "privileged_flags": "0x12", "other_flags": "0x80000002", "text_flags": "signature|privileged",
            "malformed_protection": "signature PRIVATE_ERROR", "reference_protection": "@integer/signature"}[fault])
    with pytest.raises(ValueError, match="ordinary app-owned service authority"):
        android_distribution.verify_manifest(manifest)


def android_publication_fixture(directory):
    """Synthetic archives test packaging admission only, never Android execution."""
    for artifact in ("core-client", "core-runtime-host"):
        aar = android_distribution.publication_path(directory, artifact, "aar")
        aar.parent.mkdir(parents=True)
        classes = io.BytesIO()
        with zipfile.ZipFile(classes, "w") as jar:
            jar.writestr("META-INF/LICENSE", (staging.ROOT / "LICENSE").read_bytes())
            names = ("core/CoreClient", "IMeshCoreApi") if artifact == "core-client" else (
                "MeshCoreRuntime", "MeshCoreApiService", "BootstrapService", "NativeWebRtcBridge")
            for name in names: jar.writestr("com/meshchat/runtime/" + name + ".class", b"fixture class name only")
        python = io.BytesIO()
        with zipfile.ZipFile(python, "w") as package:
            package.writestr("mesh_chat/mobile_bridge.pyc", b"fixture source name only")
        with zipfile.ZipFile(aar, "w") as archive:
            archive.writestr("AndroidManifest.xml", b"fixture manifest")
            archive.writestr("classes.jar", classes.getvalue())
            if artifact == "core-runtime-host": archive.writestr("assets/chaquopy/app.imy", python.getvalue())
        dependencies = [] if artifact == "core-client" else [
            ("com.meshchat", "core-client", android_distribution.VERSION, "compile"),
            ("androidx.activity", "activity-ktx", "1.10.1", "compile"),
            ("io.github.webrtc-sdk", "android", "150.7871.01", "runtime")]
        pom = '<project xmlns="http://maven.apache.org/POM/4.0.0"><groupId>com.meshchat</groupId>' + \
            f'<artifactId>{artifact}</artifactId><version>{android_distribution.VERSION}</version><dependencies>'
        pom += "".join("<dependency>" + "".join(f"<{key}>{value}</{key}>" for key, value in
            zip(("groupId", "artifactId", "version", "scope"), dependency)) + "</dependency>" for dependency in dependencies)
        android_distribution.publication_path(directory, artifact, "pom").write_text(pom + "</dependencies></project>")
        sources = aar.with_name(f"{artifact}-{android_distribution.VERSION}-sources.jar")
        with zipfile.ZipFile(sources, "w") as archive:
            archive.writestr("CoreClient.kt" if artifact == "core-client" else "MeshCoreRuntime.kt", b"fixture source only")
        android_distribution.publication_path(directory, artifact, "module").write_text(json.dumps({
            "component": {"group": "com.meshchat", "module": artifact, "version": android_distribution.VERSION},
            "variants": [{"attributes": {"org.gradle.usage": usage, "org.gradle.category": "library",
                                        "org.gradle.libraryelements": "aar"},
                "dependencies": [{"group": group, "module": name, "version": {"requires": version}}
                    for group, name, version, scope in dependencies if usage == "java-runtime" or scope == "compile"],
                "files": [{"name": aar.name, "url": aar.name, "sha256": staging.digest(aar),
                           "size": aar.stat().st_size}]} for usage in ("java-api", "java-runtime")] +
                [{"attributes": {"org.gradle.usage": "java-runtime", "org.gradle.category": "documentation",
                                  "org.gradle.docstype": "sources"},
                  "files": [{"name": sources.name, "url": sources.name, "sha256": staging.digest(sources),
                              "size": sources.stat().st_size}]}]}))


@pytest.mark.parametrize("fault", ["none", "old_version", "activity_not_exported", "sdk_not_exported",
    "module_aar_hash", "module_aar_size", "module_absolute_url", "runtime_missing",
    "variant_sdk_missing", "variant_runtime_missing", "variant_redirect", "sources_changed", "sources_missing"])
def test_android_maven_metadata_binds_exact_runtime_and_public_api(tmp_path, fault):
    android_publication_fixture(tmp_path)
    android_distribution.verify_publications(tmp_path)
    pom = android_distribution.publication_path(tmp_path, "core-runtime-host", "pom")
    module = android_distribution.publication_path(tmp_path, "core-runtime-host", "module")
    if fault == "old_version": pom.write_text(pom.read_text().replace(android_distribution.VERSION, "0.2.0"))
    elif fault in {"activity_not_exported", "sdk_not_exported"}:
        needle = "activity-ktx" if fault == "activity_not_exported" else "core-client"
        pom.write_text(pom.read_text().replace(f"<artifactId>{needle}</artifactId><version>" +
            ("1.10.1" if fault == "activity_not_exported" else android_distribution.VERSION) +
            "</version><scope>compile</scope>", f"<artifactId>{needle}</artifactId><version>0.0.0</version><scope>runtime</scope>"))
    elif fault.startswith("module_"):
        value = json.loads(module.read_text())
        item = value["variants"][0]["files"][0]
        item[{"module_aar_hash": "sha256", "module_aar_size": "size", "module_absolute_url": "url"}[fault]] = {
            "module_aar_hash": "e" * 64, "module_aar_size": 1, "module_absolute_url": "https://unqualified.invalid/runtime.aar"}[fault]
        module.write_text(json.dumps(value))
    elif fault == "runtime_missing":
        pom.write_text(pom.read_text().replace("150.7871.01", "0.0.0"))
    elif fault.startswith("variant_"):
        value = json.loads(module.read_text())
        if fault == "variant_redirect": value["variants"][0]["available-at"] = {"url": "other.module"}
        else:
            variant = value["variants"][1 if fault == "variant_runtime_missing" else 0]
            missing = "android" if fault == "variant_runtime_missing" else "core-client"
            variant["dependencies"] = [item for item in variant["dependencies"] if item["module"] != missing]
        module.write_text(json.dumps(value))
    elif fault.startswith("sources_"):
        sources = android_distribution.publication_path(tmp_path, "core-runtime-host", "aar").with_name(
            f"core-runtime-host-{android_distribution.VERSION}-sources.jar")
        if fault == "sources_missing": sources.unlink()
        else: sources.write_bytes(sources.read_bytes() + b"changed")
    if fault != "none":
        with pytest.raises((ValueError, FileNotFoundError)): android_distribution.verify_publications(tmp_path)


def staged_input(tmp_path):
    directory = tmp_path / "sdk"
    (directory / "typescript").mkdir(parents=True)
    artifact = directory / "typescript" / staging.ARTIFACTS["typescript"]
    artifact.write_bytes(b"component fixture bytes; not a real SDK archive")
    value = {"v": 1, "passed": True, "evidence_level": "public_sdk_archive_and_isolated_import_staging",
             "source_commit": "a" * 40, "source_tree": "b" * 40,
             "artifacts": {"typescript": {"artifact": "typescript/" + artifact.name,
                "sha256": staging.digest(artifact), "size_bytes": artifact.stat().st_size}}}
    report = tmp_path / "sdk-staging.json"
    report.write_text(json.dumps(value))
    return directory, artifact, report, value


def bootstrap_record(source="a" * 40, tree="b" * 40):
    """Synthetic complete declaration for rejection checks; never execution proof."""
    return {"v": 1, "passed": True, "source_commit": source, "source_tree": tree,
            "evidence_level": bootstrap.LEVEL, "scope": bootstrap.SCOPE,
            "checks": dict(bootstrap.CHECKS), "run_id": "6" * 32, "duration_seconds": 1,
            "sidecar_sha256": "d" * 64, "build_input_sha256": "e" * 64, "build_manifest_sha256": "f" * 64,
            "sdk_sha256": "a" * 64, "runtime_installed_outside_checkout": True, "cleanup": "passed",
            "sdk_artifact": bootstrap.SDK_ARTIFACT,
            "application": {"installed_outside_checkout": True, "imports_public_package": True,
                "application_files": {name: "c" * 64 for name in staging.FILES}}}


def pairing_record(source="a" * 40, tree="b" * 40):
    return {**bootstrap_record(source, tree), "evidence_level": pairing.LEVEL, "scope": pairing.SCOPE,
            "checks": dict(pairing.CHECKS), "run_id": "7" * 32, "bootstrap_report_sha256": "b" * 64}


@pytest.mark.parametrize("mode", ["healthy", "unavailable", "null", "missing_network", "string", "array",
    "boolean", "number", "startup_failure", "failure_with_object", "unknown_error", "object_error",
    "array_error", "boolean_error", "missing_error"])
@pytest.mark.parametrize("incarnation", [0, 1])
def test_actual_bootstrap_producer_requires_network_construction_without_more_requests(tmp_path, mode, incarnation):
    # Actual consumer control flow, synthetic SDK/host only; no native/network claim.
    node, _ = staging.tools()
    log = tmp_path / "events.jsonl"
    completed = subprocess.run([node, "--import", (staging.ROOT /
        "tests/core-ui-boundary/bootstrap_network_fixture.mjs").as_uri(),
        str(staging.APPLICATION / "bootstrap-check.mjs"), "--runtime", "unused", "--data-directory", "unused"],
        env={**os.environ, "BOOTSTRAP_NETWORK_MODE": mode, "BOOTSTRAP_NETWORK_INCARNATION": str(incarnation),
             "BOOTSTRAP_NETWORK_LOG": str(log)}, capture_output=True, text=True, timeout=15)
    passed = mode in {"healthy", "unavailable"}
    assert completed.returncode == (0 if passed else 1), completed.stderr
    observed = json.loads(completed.stdout)
    if passed:
        assert observed == {key: value for key, value in bootstrap.CHECKS.items() if not key.startswith("efs_")}
        assert not completed.stderr
    else:
        assert observed == {"passed": False, "phase": "network_construction", "error_code": "unavailable"}
        assert completed.stderr == "Independent application bootstrap check failed.\n"
    assert "PRIVATE_" not in completed.stdout + completed.stderr
    events = [json.loads(line) for line in log.read_text().splitlines()]
    last = 1 if passed else incarnation
    assert [(event["event"], event["incarnation"]) for event in events if event["event"] != "request"] == [
        (event, index) for index in range(last + 1) for event in ("start", "open", "close", "stop")]
    for index in range(last + 1):
        assert [event["operation"] for event in events if event["event"] == "request"
                and event["incarnation"] == index] == ["application.snapshot"] + (
            ["profile.query"] if index == 0 else []) + ["profile.create"] * 3 + [
            "runtime.capabilities", "profile.query", "application.snapshot"]


@pytest.mark.parametrize("fault", ["missing", "zero", "one", "boolean", "float", "string", "object", "extra"])
def test_bootstrap_evidence_requires_two_strict_network_construction_observations(fault):
    record = bootstrap_record()
    bootstrap.verify_report(record, "a" * 40, "b" * 40)
    if fault == "missing": record["checks"].pop("post_profile_network_constructed")
    elif fault == "extra": record["checks"]["network"] = {"address": "PRIVATE_ADDRESS"}
    else:
        record["checks"]["post_profile_network_constructed"] = {
            "zero": 0, "one": 1, "boolean": True, "float": 2.0, "string": "2", "object": {"count": 2}}[fault]
    with pytest.raises(ValueError): bootstrap.verify_report(record, "a" * 40, "b" * 40)


@pytest.mark.parametrize("fault", ["bootstrap_scope", "SC21_scope", "implicit_approval", "missing_receipt",
    "duplicate_records", "missing_transfer", "missing_cancel", "unready", "efs", "receipt_boolean", "cleanup", "missing_bootstrap_binding",
    "direct_disclosure", "relay_not_requested", "broker_consent"])
def test_public_pairing_report_requires_exact_receipts_consent_and_normal_host_provenance(fault):
    record = pairing_record()
    pairing.verify_report(record, "a" * 40, "b" * 40)
    if fault == "bootstrap_scope": record["evidence_level"] = bootstrap.LEVEL
    elif fault == "SC21_scope": record["scope"] = "Windows-Android SC21 qualification"
    elif fault == "implicit_approval": record["checks"]["explicit_contact_decisions"] = 0
    elif fault == "missing_receipt": record["checks"]["authenticated_receipts"] = 1
    elif fault == "duplicate_records": record["checks"]["single_inbound_and_outbound_records"] = False
    elif fault == "missing_transfer": record["checks"]["supervisor_transfers"] = 1
    elif fault == "missing_cancel": record["checks"]["transferred_cancel_preserves_delivery"] = False
    elif fault == "unready": record["checks"]["public_messaging_ready"] = 0
    elif fault == "efs": record["checks"]["efs_vault_files"] = 0
    elif fault == "receipt_boolean": record["checks"]["original_message_key_replay"] = 1
    elif fault == "cleanup": record["cleanup"] = "pending"
    elif fault == "direct_disclosure": record["checks"]["direct_disclosure_consented"] = True
    elif fault == "relay_not_requested": record["checks"]["relay_only_requested"] = False
    elif fault == "broker_consent": record["checks"]["broker_consent"] = False
    else: record.pop("bootstrap_report_sha256")
    with pytest.raises(ValueError): pairing.verify_report(record, "a" * 40, "b" * 40)


@pytest.mark.parametrize("fault", ["source", "tree", "scope", "component_scope", "failed", "efs",
    "efs_integer", "sdk_hash", "runtime_hash", "inside_checkout", "runtime_inside", "file_missing",
    "file_hash", "cleanup", "single_exit", "run", "duration"])
def test_normal_bootstrap_evidence_cannot_substitute_components_or_unprotected_storage(fault):
    record = bootstrap_record()
    bootstrap.verify_report(record, "a" * 40, "b" * 40)
    if fault == "source": record["source_commit"] = "c" * 40
    elif fault == "tree": record["source_tree"] = "c" * 40
    elif fault == "scope": record["scope"] = "SC21 public peer receipt qualification"
    elif fault == "component_scope": record["evidence_level"] = "windows_named_pipe_and_inprocess_domain"
    elif fault == "failed": record["passed"] = False
    elif fault == "efs": record["checks"]["efs_vault_file"] = False
    elif fault == "efs_integer": record["checks"]["efs_profile_directory"] = 1
    elif fault == "sdk_hash": record["sdk_sha256"] = "missing"
    elif fault == "runtime_hash": record.pop("sidecar_sha256")
    elif fault == "inside_checkout": record["application"]["installed_outside_checkout"] = False
    elif fault == "runtime_inside": record["runtime_installed_outside_checkout"] = False
    elif fault == "file_missing": record["application"]["application_files"].pop("bootstrap-check.mjs")
    elif fault == "file_hash": record["application"]["application_files"]["runtime.mjs"] = "bad"
    elif fault == "cleanup": record["cleanup"] = "pending"
    elif fault == "single_exit": record["checks"]["clean_host_exits"] = 1
    elif fault == "run": record["run_id"] = ""
    else: record["duration_seconds"] = float("nan")
    with pytest.raises(ValueError): bootstrap.verify_report(record, "a" * 40, "b" * 40)


def test_installed_application_does_not_inherit_checkout_import_paths_or_artifact_bearers():
    assert bootstrap.application_environment({"Path": "tools", "SYSTEMROOT": "system",
        "PythonPath": "checkout", "PYTHONHOME": "checkout", "NODE_PATH": "checkout", "NODE_OPTIONS": "checkout-preload",
        "mesh_private_key": "secret", "GITHUB_TOKEN": "secret", "Actions_Runtime_Token": "secret",
        "INPUT_ROLE": "secret"}) == {"Path": "tools", "SYSTEMROOT": "system"}


def test_normal_profile_protection_requires_an_existing_protected_profile_and_vault(tmp_path):
    directory = tmp_path / "mesh-core-runtime/profile-v1"
    directory.mkdir(parents=True)
    # The parent may itself be encrypted on a developer machine; missing Vault
    # storage must fail in either case, without asserting local EFS support.
    with pytest.raises((ValueError, FileNotFoundError)):
        bootstrap.protected_profile(tmp_path)


@pytest.mark.parametrize("fault", ["source", "tree", "bytes", "size", "path", "failed", "component_scope"])
def test_independent_stage_refuses_sdk_source_hash_and_scope_substitution(tmp_path, fault):
    directory, artifact, report, value = staged_input(tmp_path)
    assert staging.sdk_input(directory, report, "a" * 40, "b" * 40) == artifact
    if fault == "source": value["source_commit"] = "c" * 40
    elif fault == "tree": value["source_tree"] = "c" * 40
    elif fault == "bytes": artifact.write_bytes(artifact.read_bytes() + b"changed")
    elif fault == "size": value["artifacts"]["typescript"]["size_bytes"] += 1
    elif fault == "path": value["artifacts"]["typescript"]["artifact"] = "../different.tgz"
    elif fault == "failed": value["passed"] = False
    else: value["evidence_level"] = "simulated_and_in_process"
    report.write_text(json.dumps(value))
    with pytest.raises(ValueError): staging.sdk_input(directory, report, "a" * 40, "b" * 40)


def test_independent_install_cannot_use_checkout_or_delete_unowned_directory(tmp_path):
    with pytest.raises(ValueError, match="outside the checkout"):
        staging.outside_directory(staging.ROOT)
    with pytest.raises(ValueError, match="checkout dependencies"):
        staging.install_typescript(staging.ROOT, Path("missing-sdk"), "missing-node", "missing-npm")
    with pytest.raises(ValueError, match="ownership changed"):
        staging.cleanup(tmp_path, tmp_path.parent)
    assert tmp_path.is_dir()


def test_actual_independent_app_installs_from_sdk_archive_outside_checkout(record_property):
    # Actual SDK bytes are a mandatory staging prerequisite. This exercises
    # installation/import only, with no substitute host or fabricated receipt.
    artifact = Path(os.environ.get("MESH_CORE_SDK_ARTIFACTS", staging.ROOT / "dist/sdk")) / "typescript" / staging.ARTIFACTS["typescript"]
    assert artifact.is_file(), "Stage the actual public TypeScript SDK first"
    node, npm = staging.tools()
    parent = Path(os.environ.get("MESH_CORE_CONSUMER_TMP") or tempfile.gettempdir())
    directory = staging.outside_directory(parent)
    try:
        report = staging.install_typescript(directory, artifact, node, npm)
        record_property("sdk_sha256", staging.digest(artifact))
        assert report["imports_public_package"] and report["installed_outside_checkout"]
        assert report["installed_sdk_entry"].startswith("node_modules/@mesh-chat/core-client/")
        assert set(report["application_files"]) == set(staging.FILES)
        rejected = subprocess.run([node, "bootstrap-check.mjs"], cwd=directory,
                                  capture_output=True, text=True, timeout=15)
        assert rejected.returncode == 1
        assert json.loads(rejected.stdout) == {"passed": False, "phase": "arguments", "error_code": "unavailable"}
        rejected = subprocess.run([node, "pairing-check.mjs"], cwd=directory,
                                  capture_output=True, text=True, timeout=15)
        assert rejected.returncode == 1
        assert json.loads(rejected.stdout) == {"passed": False, "phase": "arguments", "error_code": "unavailable",
            "diagnostics": {"subphase": "arguments", "deadline_exhausted": False,
                "failure_origin": "unknown", "cleanup": [], "peers": {}}}
        assert pairing.failure_details(json.loads(rejected.stdout))["application_phase"] == "arguments"
    finally:
        staging.cleanup(directory, parent)
    assert not directory.exists()
