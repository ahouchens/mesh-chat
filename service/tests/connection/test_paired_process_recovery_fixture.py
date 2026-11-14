"""Synthetic public-process custody for the opt-in paired recovery fixture.

The initial pairing/host/API are substituted here. Installed Windows evidence
still requires the normal producer and exact frozen host.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[3]
APPLICATION = ROOT / "examples/typescript-independent-consumer"


PRELOADER = r'''
import { registerHooks } from 'node:module';
import { appendFileSync, readFileSync, writeFileSync } from 'node:fs';

Object.defineProperty(process, 'platform', {value:'win32'});
const state = () => JSON.parse(readFileSync(process.env.PAIR_STATE, 'utf8'));
const save = value => writeFileSync(process.env.PAIR_STATE, JSON.stringify(value));
const log = value => appendFileSync(process.env.PAIR_LOG, JSON.stringify(value) + '\n');
const handles = {offerer:'PROFILE_OFFER',answerer:'PROFILE_ANSWER'};
const destinations = {offerer:'DEST_OFFER',answerer:'DEST_ANSWER'};
const contacts = {offerer:{id:'CONTACT_OFFER',core_handle:'PEER_ANSWER',destination_hash:'DEST_ANSWER',trust:'approved'},
  answerer:{id:'CONTACT_ANSWER',core_handle:'PEER_OFFER',destination_hash:'DEST_OFFER',trust:'approved'}};
let incarnation = {offerer:0,answerer:0};
let prefixFailure;

function snapshot(peer) {
  const work = state().message;
  const messages = [];
  if (work && peer.role === 'offerer') messages.push({id:'RECORD_ONE',kind:'chat',direction:'outbound',
    text:work.text,state:work.state,contact_id:contacts.offerer.id});
  if (work && peer.role === 'answerer' && work.inbound) {
    messages.push({id:'INBOUND_ONE',kind:'chat',direction:'inbound',text:work.text,
      state:'delivered',contact_id:contacts.answerer.id});
    if (process.env.PAIR_FAULT === 'duplicate_inbound') messages.push({...messages.at(-1),id:'INBOUND_TWO'});
  }
  return {profile:{destination_hash:destinations[peer.role],display_name:peer.displayName},
    contacts:[{...contacts[peer.role]}],messages};
}
function client(peer) {
  return {capabilities:{profiles:[handles[peer.role]],operations:['runtime.capabilities','message.enqueue']},
    close(){},async request(operation, params) {
      const work = state().message;
      if (operation === 'runtime.capabilities') return this.capabilities;
      if (operation === 'profile.query') return {destination:destinations[peer.role]};
      if (operation === 'application.snapshot') return snapshot(peer);
      if (operation === 'message.list') return {messages:work&&peer.role==='offerer'
        ? [{profile:handles.offerer,message:'HANDLE_ONE',recipient:contacts.offerer.core_handle,
          kind:'text',text:work.text,state:work.state,created_at:1},
          ...(process.env.PAIR_FAULT === 'duplicate_pending' ? [{profile:handles.offerer,
            message:'HANDLE_TWO',recipient:contacts.offerer.core_handle,kind:'text',text:work.text,
            state:work.state,created_at:1}] : [])] : [],next_cursor:null,events_cursor:'CURSOR'};
      if (operation === 'message.query') return {message:'HANDLE_ONE',text:work.text,
        recipient:contacts.offerer.core_handle,state:work.state};
      throw new Error('unexpected public operation');
    }};
}
function peer(role) {
  const value={role,profile:handles[role],destination:destinations[role],
    expectedDestination:destinations[role==='offerer'?'answerer':'offerer'],
    displayName:'Independent '+role,contact:{...contacts[role]},
    directory:process.env.PAIR_ROOT+'\\'+role,retired:false,
    runtime:{pipe:'synthetic-pipe',async stop(){return {stopped:true,exit_code:0}}},
    clients:new Set(),transports:new Set()};
  value.client=client(value);value.clients.add(value.client);
  return value;
}
globalThis.__paired = {
  async launchRuntime(_executable,directory,options) {
    const role=directory.endsWith('offerer')?'offerer':'answerer';
    const runtime={pipe:'synthetic-pipe',async stop(){return {stopped:true,exit_code:0}}};
    options.onOwned(runtime);
    log({event:'owner_reopen',role});
    if(role==='answerer'&&process.env.PAIR_FAULT!=='no_receipt'){
      const current=state();
      if(current.message){current.message.state='delivered';current.message.inbound=true;save(current);}
    }
    return runtime;
  },
  async runPairing(_executable,_directory,{afterPaired,totalMs}) {
    if (totalMs!==360000) throw new Error('wrong bound');
    if (process.env.PAIR_FAULT==='initial_pairing_timeout') {
      prefixFailure=new Error('public_pairing_deadline');throw prefixFailure;
    }
    const sender=peer('offerer'),receiver=peer('answerer'),owned=[sender,receiver];
    incarnation.offerer=incarnation.answerer=1;
    const api={
      budget:()=>1000,
      own(list,value){value.incarnation=++incarnation[value.role];list.push(value)},
      retainRuntime(value,runtime){value.runtime=runtime},
      async attach(value){value.client=client(value);value.clients.add(value.client);return value.client},
      async retire(value){
        if(value.retired)return;
        const done=await value.runtime.stop();
        if(done.stopped!==true||done.exit_code!==0)throw new Error('owner stop');
        value.retired=true;value.clients.clear();
        log({event:'owner_exit',role:value.role,incarnation:value.incarnation});
      },
      async wait(read){
        const deadline=Date.now()+700;
        while(Date.now()<deadline){const value=await read();if(value)return value;
          await new Promise(resolve=>setTimeout(resolve,10));}
        throw new Error('synthetic wait deadline');
      },
      async snapshot(value){return value.client.request('application.snapshot',{})},
    };
    let result;
    try{result=await afterPaired('synthetic.exe',sender,receiver,[],owned,api)}
    finally{for(const value of owned)await api.retire(value)}
    if(process.env.PAIR_FAULT==='wrong_owner_count')result.positive_helper_exits=1;
    return {fresh_profiles:2,explicit_contact_decisions:2,authenticated_receipts:2,
      clean_host_exits:owned.filter(value=>value.retired).length,
      owner_native_host_shutdown_acknowledgments:owned.filter(value=>value.retired).length,...result};
  },
  pairingFailureSummary(error) {return error===prefixFailure
    ? {phase:'public_pairing',subphase:'offer_code_wait',error_code:'unavailable'}:null},
};
registerHooks({resolve(specifier,context,nextResolve){
  if(context.parentURL?.endsWith('paired-process-recovery-check.mjs')&&specifier==='./pairing-check.mjs')
    return {url:'data:text/javascript,export const runPairing=globalThis.__paired.runPairing;'
      +'export const pairingFailureSummary=globalThis.__paired.pairingFailureSummary;',shortCircuit:true};
  if(context.parentURL?.endsWith('paired-process-recovery-check.mjs')&&specifier==='./runtime.mjs')
    return {url:'data:text/javascript,export const launchRuntime=globalThis.__paired.launchRuntime;',shortCircuit:true};
  return nextResolve(specifier,context);
}});
'''


CHILD = r'''
import { appendFileSync, readFileSync, writeFileSync } from 'node:fs';
import { createInterface } from 'node:readline';
const state=()=>JSON.parse(readFileSync(process.env.PAIR_STATE,'utf8'));
const save=value=>writeFileSync(process.env.PAIR_STATE,JSON.stringify(value));
const log=value=>appendFileSync(process.env.PAIR_LOG,JSON.stringify(value)+'\n');
log({event:'child_start',pid:process.pid,parent:process.ppid});
process.on('exit',code=>log({event:'child_exit',pid:process.pid,code}));
let first=false;
for await(const line of createInterface({input:process.stdin})){
  const command=JSON.parse(line),work=state().message;
  log({event:'command',pid:process.pid,operation:command.operation});
  let result;
  if(command.operation==='runtime.capabilities')result={profiles:['PROFILE_OFFER'],
    operations:['runtime.capabilities','message.enqueue']};
  else if(command.operation==='profile.query')result={destination:'DEST_OFFER'};
  else if(command.operation==='application.snapshot')result={profile:{destination_hash:'DEST_OFFER',
    display_name:'Independent offerer'},contacts:[{id:'CONTACT_OFFER',core_handle:'PEER_ANSWER',
    destination_hash:'DEST_ANSWER',trust:process.env.PAIR_FAULT==='changed_trust'&&work?'blocked':'approved'}],
    messages:work?[{id:'RECORD_ONE',kind:'chat',direction:'outbound',text:work.text,
      state:work.state,contact_id:'CONTACT_OFFER'}]:[]};
  else if(command.operation==='message.list')result={messages:work?[{profile:'PROFILE_OFFER',
    message:'HANDLE_ONE',recipient:'PEER_ANSWER',kind:'text',text:work.text,state:work.state,
    created_at:1}]:[],next_cursor:null,
    events_cursor:process.env.PAIR_FAULT==='missing_watermark'?null:'CURSOR_ZERO'};
  else if(command.operation==='message.query')result={message:'HANDLE_ONE',text:work.text,
    recipient:'PEER_ANSWER',state:work.state};
  else if(command.operation==='events.poll'){
    const current=state();
    if(command.params.cursor===null&&(!current.ackCursor
        || process.env.PAIR_FAULT==='resume_requires_resync')
        && process.env.PAIR_FAULT!=='initial_resync_missing'){
      process.stdout.write(JSON.stringify({id:command.id,ok:false,
        error:{code:'resync_required'}})+'\n');continue;
    }
    const delivered=command.params.cursor==='CURSOR_ZERO'&&work?.state==='delivered';
    const event=delivered&&process.env.PAIR_FAULT!=='no_delivery_event'
      ? {id:process.env.PAIR_FAULT==='event_replay_changed'&&current.deliveryPollCount>0
          ? 'EVENT_CHANGED':'EVENT_ONE',message:'HANDLE_ONE',type:'message.changed',
        state:'delivered',direction:'outbound',timestamp:1}:null;
    if(delivered){current.deliveryPollCount=(current.deliveryPollCount||0)+1;save(current);}
    result={profile:'PROFILE_OFFER',events:event?[event]:[],
      next_cursor:event?'CURSOR_ONE':'CURSOR_ZERO',more:false};
  }
  else if(command.operation==='events.ack'){
    const current=state();
    current.ackCursor=command.params.cursor;
    if(process.env.PAIR_FAULT==='ack_changes_pending'&&current.message?.state==='queued'){
      current.message.state='delivered';
    }
    if(process.env.PAIR_FAULT==='ack_changes_delivery'&&command.params.cursor==='CURSOR_ONE'){
      current.message.state='queued';
    }
    save(current);
    result={profile:'PROFILE_OFFER',checkpoint:'CHECKPOINT',acknowledged:true,
      acknowledged_at:1,expires_at:2};
  }
  else if(command.operation==='message.enqueue'){
    if(!work){
      first=true;
      if(process.env.PAIR_FAULT!=='missing_pending')save({message:{key:command.idempotency_key,
        text:command.params.text,state:'queued',inbound:false}});
      result={accepted:true,message:'HANDLE_ONE'};
    }else if(command.idempotency_key===work.key&&command.params.text!==work.text){
      if(process.env.PAIR_FAULT==='conflict_accepted')result={accepted:true,message:'HANDLE_ONE'};
      else {process.stdout.write(JSON.stringify({id:command.id,ok:false,
        error:{code:'idempotency_conflict'}})+'\n');continue;}
    }else result={accepted:true,message:process.env.PAIR_FAULT==='replay_new_handle'
      ?'HANDLE_TWO':'HANDLE_ONE'};
  }else process.exit(2);
  process.stdout.write(JSON.stringify({id:command.id,ok:true,result})+'\n');
}
if(first&&process.env.PAIR_FAULT==='first_child_nonzero')process.exitCode=1;
'''


REAL_PREFIX_PRELOADER = r'''
import {registerHooks} from 'node:module';
const exportsFor = {
  '@mesh-chat/core-client': "export class CoreClient{};export class CoreError extends Error{};",
  '@mesh-chat/core-client/node': "export const connectNamedPipe=()=>{};",
  './runtime.mjs': "export async function launchRuntime(_exe,_dir,options){"
    +"options.onOwned({stop:async()=>{throw new Error('PRIVATE_CLEANUP')}});"
    +"throw new Error('PRIVATE_INITIAL_FAILURE')}"
    +"export const launchRefusedRuntime=()=>{};",
  './relay-settings.mjs': "export const freshRelaySettings=()=>({});",
  './connection-readiness.mjs': "export const connectionMessagingReady=()=>false;",
  './owner-pairing-diagnostic.mjs': "export const collectOwnerPairingDiagnostics=()=>({});"
    +"export const readOwnerPairingDiagnostic=()=>({});",
};
registerHooks({resolve(specifier,context,nextResolve){
  if(context.parentURL?.endsWith('pairing-check.mjs')&&Object.hasOwn(exportsFor,specifier))
    return {url:'data:text/javascript,'+encodeURIComponent(exportsFor[specifier]),shortCircuit:true};
  return nextResolve(specifier,context);
}});
'''


def node_runtime():
    selected = os.environ.get("MESH_CHAT_TEST_NODE") or os.environ.get("MESH_NODE") or shutil.which("node")
    if not selected or not Path(selected).is_file():
        pytest.skip("Node >=22 runtime unavailable")
    version = subprocess.check_output([selected, "--version"], text=True, timeout=5)
    if int(version.strip().lstrip("v").split(".")[0]) < 22:
        pytest.skip("Node >=22 runtime unavailable")
    return selected


def test_real_pairing_failure_summary_keeps_original_prefix_cause_after_cleanup(tmp_path):
    preloader = tmp_path / "real-prefix-preloader.mjs"
    preloader.write_text(REAL_PREFIX_PRELOADER, encoding="utf-8")
    script = ("import {runPairing,pairingFailureSummary} from "
              + json.dumps((APPLICATION / "pairing-check.mjs").as_uri()) + ";"
              "let caught;try{await runPairing('host.exe','data',{totalMs:360000,afterPaired:async()=>{}})}"
              "catch(error){caught=error}"
              "if(!caught)throw new Error('missing_failure');"
              "process.stdout.write(JSON.stringify({selected:pairingFailureSummary(caught),"
              "foreign:pairingFailureSummary(new Error('PRIVATE_INITIAL_FAILURE'))})+'\\n');")
    completed = subprocess.run([node_runtime(), "--import", preloader.as_uri(),
                                "--input-type=module", "-e", script], cwd=tmp_path,
                               capture_output=True, text=True, timeout=12)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "selected": {"phase": "fresh_profiles", "subphase": "offerer_create",
                     "error_code": "unavailable"}, "foreign": None}
    assert "PRIVATE" not in completed.stdout


def execute(tmp_path, fault="normal"):
    for name in ("paired-process-recovery-check.mjs", "public-process-helper.mjs"):
        shutil.copyfile(APPLICATION / name, tmp_path / name)
    (tmp_path / "preloader.mjs").write_text(PRELOADER, encoding="utf-8")
    (tmp_path / "consumer.mjs").write_text(CHILD, encoding="utf-8")
    (tmp_path / "state.json").write_text('{"message":null}', encoding="utf-8")
    log = tmp_path / "events.jsonl"
    env = {**os.environ, "PAIR_STATE": str(tmp_path / "state.json"),
           "PAIR_LOG": str(log), "PAIR_ROOT": str(tmp_path), "PAIR_FAULT": fault}
    completed = subprocess.run([node_runtime(), "--import", (tmp_path / "preloader.mjs").as_uri(),
        str(tmp_path / "paired-process-recovery-check.mjs"), "--runtime", str(tmp_path / "host.exe"),
        "--data-directory", str(tmp_path / "data")], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=12)
    events = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    state = json.loads((tmp_path / "state.json").read_text())
    return completed, json.loads(completed.stdout), events, state


def test_distinct_children_discarded_reply_and_later_single_receipt(tmp_path):
    completed, report, events, state = execute(tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == "" and report["passed"] is True
    assert set(report) == {"v", "passed", "scope", "checks", "duration_ms"}
    assert report["checks"]["positive_owner_exits"] == 4
    assert report["checks"]["positive_helper_exits"] == 2
    assert report["checks"]["discarded_application_reply"] is True
    assert report["checks"]["independent_pending_commit_observed"] is True
    assert report["checks"]["same_key_original_handle"] is True
    assert report["checks"]["changed_payload_conflict"] is True
    assert report["checks"]["single_inbound_record"] is True
    for key in ("initial_null_cursor_resync", "terminal_snapshot_watermark",
                "ack_preserved_pending_state", "same_caller_progress_resumed_after_restart",
                "delivered_event_replayed_once", "ack_preserved_delivered_state"):
        assert report["checks"][key] is True
    starts = [item for item in events if item["event"] == "child_start"]
    exits = [item for item in events if item["event"] == "child_exit"]
    assert len(starts) == len(exits) == 2 and len({item["pid"] for item in starts}) == 2
    assert [item["code"] for item in exits] == [0, 0]
    assert len([item for item in events if item["event"] == "owner_exit"]) == 4
    assert state["message"]["state"] == "delivered" and state["message"]["inbound"] is True
    operations = [item["operation"] for item in events if item["event"] == "command"]
    assert operations.count("events.ack") == 2
    assert operations.count("events.poll") >= 4
    assert operations.index("events.poll") < operations.index("events.ack")
    assert "HANDLE_ONE" not in completed.stdout and "RECORD_ONE" not in completed.stdout


@pytest.mark.parametrize("fault", ["initial_pairing_timeout", "missing_pending", "duplicate_pending", "replay_new_handle",
                                   "conflict_accepted", "changed_trust", "no_receipt",
                                   "duplicate_inbound", "first_child_nonzero", "initial_resync_missing",
                                   "missing_watermark", "ack_changes_pending", "resume_requires_resync",
                                   "no_delivery_event", "event_replay_changed", "ack_changes_delivery"])
def test_mutated_public_observation_or_child_exit_cannot_pass(tmp_path, fault):
    completed, report, events, state = execute(tmp_path, fault)
    assert completed.returncode == 1
    expected_fields = {"v", "passed", "scope", "phase", "stage", "cause", "duration_ms"}
    if fault == "initial_pairing_timeout": expected_fields.add("pairing_failure")
    assert report["passed"] is False and set(report) == expected_fields
    expected = {
        "initial_pairing_timeout": ("initial_pairing", "public_pairing_deadline"),
        "missing_pending": ("enqueue_and_pending", "unavailable"),
        "duplicate_pending": ("enqueue_and_pending", "duplicate_outbound"),
        "replay_new_handle": ("replay_and_conflict", "replay_handle_changed"),
        "conflict_accepted": ("replay_and_conflict", "changed_payload_accepted"),
        "changed_trust": ("second_helper", "public_authority_changed"),
        "no_receipt": ("delivery_receipt", "unavailable"),
        "duplicate_inbound": ("delivery_receipt", "duplicate_public_record"),
        "first_child_nonzero": ("first_helper_stop", "helper_exit"),
        "initial_resync_missing": ("event_resnapshot", "initial_resync_missing"),
        "missing_watermark": ("event_resnapshot", "event_snapshot_watermark"),
        "ack_changes_pending": ("event_resnapshot", "event_ack_changed_pending"),
        "resume_requires_resync": ("event_resume", "helper_core_error"),
        "no_delivery_event": ("event_delivery", "unavailable"),
        "event_replay_changed": ("event_delivery", "delivery_event_replay"),
        "ack_changes_delivery": ("event_delivery", "event_ack_changed_delivery"),
    }
    assert (report["stage"], report["cause"]) == expected[fault]
    if fault == "initial_pairing_timeout":
        assert report["pairing_failure"] == {"phase": "public_pairing",
                                             "subphase": "offer_code_wait", "error_code": "unavailable"}
    assert "PRIVATE" not in completed.stdout + completed.stderr
    assert fault == "initial_pairing_timeout" or any(item["event"] == "owner_exit" for item in events)
    assert len([item for item in events if item["event"] == "owner_exit"]) == (
        0 if fault == "initial_pairing_timeout" else
        2 + len([item for item in events if item["event"] == "owner_reopen"]))
    assert len([item for item in events if item["event"] == "child_start"]) == len(
        [item for item in events if item["event"] == "child_exit"])
    if fault in {"duplicate_pending", "replay_new_handle", "conflict_accepted", "changed_trust", "no_receipt",
                 "duplicate_inbound", "first_child_nonzero"}:
        assert state["message"] is not None  # Failure cleanup never erases accepted pending work.
    if fault == "first_child_nonzero":
        assert any(item["event"] == "child_exit" and item["code"] == 1 for item in events)
