// Installed Windows proof for the opt-in owner/private-helper admission path.
// This application imports only the installed public SDK and its own modules.
import { CoreClient, TransportClosedError } from "@mesh-chat/core-client";
import { connectNamedPipe } from "@mesh-chat/core-client/node";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { isAbsolute, join } from "node:path";
import { performance } from "node:perf_hooks";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { Helper, PrivateConsumerInput } from "./public-process-helper.mjs";
import { hostWitnessScript, requireDeniedBeforeReply, requireRevokedHelper } from "./private-admission-evidence.mjs";
import { launchRuntime } from "./runtime.mjs";

const SOURCE = fileURLToPath(import.meta.url);
const SCOPE = "Installed Windows public SDK, opt-in private owner/helper admission on one fresh profile; no cross-launch vault, pairing, receipts, Android, or full R7 acceptance";
const TOTAL_MS = 150000;
const OUTPUT_LIMIT = 4096;

function budget(deadline, cap = 30000) {
  const ms = Math.min(cap, Math.floor(deadline - performance.now()));
  if (!Number.isSafeInteger(ms) || ms < 1) throw new Error("fixture_deadline");
  return ms;
}

function bounded(action, deadline, cap = 30000) {
  let timer;
  return Promise.race([action, new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error("fixture_deadline")), budget(deadline, cap));
  })]).finally(() => clearTimeout(timer));
}

function cleanEnvironment() {
  return Object.fromEntries(Object.entries(process.env).filter(([key]) =>
    !["MESH_", "GITHUB_", "ACTIONS_", "INPUT_"].some(prefix => key.toUpperCase().startsWith(prefix))
    && !["NODE_OPTIONS", "NODE_PATH", "PYTHONPATH", "PYTHONHOME"].includes(key.toUpperCase())));
}

function validPipe(pipe) {
  return typeof pipe === "string" && /^\\\\\.\\pipe\\mesh-chat-independent-[0-9a-f-]{36}$/.test(pipe);
}

async function denied(transport, mode) {
  return requireDeniedBeforeReply(transport, mode, null,
    value => CoreClient.open(value, {requestTimeoutMs: 5000}), TransportClosedError);
}

async function probe(mode, pipe) {
  if (process.platform !== "win32" || !validPipe(pipe)) throw new Error("probe_arguments");
  if (mode === "unregistered") return denied(await connectNamedPipe(pipe, 5000), mode);
  if (!["valid_replay", "wrong_preface", "expired"].includes(mode)) throw new Error("probe_mode");
  const invitation = await new PrivateConsumerInput(process.stdin).invitation();
  if (mode === "expired") await new Promise(resolve => setTimeout(resolve, 16000));
  const transport = await connectNamedPipe(pipe, 5000);
  if (mode === "valid_replay") {
    await transport.writeLine(`MESH-HELPER/1 ${invitation}\n`);
    let client;
    try {
      client = await CoreClient.open(transport, {requestTimeoutMs: 5000});
      const handles = client.capabilities.profiles;
      if (!Array.isArray(handles) || handles.length !== 1 || typeof handles[0] !== "string"
          || client.capabilities.operations?.includes("native.command")) throw new Error("helper_capabilities");
      const profile = await client.request("profile.query", {profile: handles[0]}, {timeoutMs: 5000});
      if (typeof profile?.destination !== "string" || !profile.destination) throw new Error("helper_profile");
    } finally { if (client) client.close(); else transport.close(); }
    const replay = await connectNamedPipe(pipe, 5000);
    const rejected = await requireDeniedBeforeReply(replay, "replay", `MESH-HELPER/1 ${invitation}\n`,
      value => CoreClient.open(value, {requestTimeoutMs: 5000}), TransportClosedError);
    return {v: 1, mode, first_admitted: true, replay_denied: rejected.closed_before_core_reply};
  }
  const preface = mode === "wrong_preface"
    ? `MESH-HELPER/1 ${invitation.slice(0, 63)}g\n`
    : `MESH-HELPER/1 ${invitation}\n`;
  return requireDeniedBeforeReply(transport, mode, preface,
    value => CoreClient.open(value, {requestTimeoutMs: 5000}), TransportClosedError);
}

function spawnProbe(mode, pipe, children) {
  const child = spawn(process.execPath, [SOURCE, "--probe", mode, pipe], {
    env: cleanEnvironment(), stdio: ["pipe", "pipe", "pipe"], windowsHide: true,
  });
  let output = Buffer.alloc(0), stderrBytes = 0, overflow = false, spawnError = false;
  child.stdout.on("data", chunk => {
    if (output.length + chunk.length > OUTPUT_LIMIT) overflow = true;
    else output = Buffer.concat([output, chunk]);
  });
  child.stderr.on("data", chunk => { stderrBytes += chunk.length; });
  child.once("error", () => { spawnError = true; });
  const closed = new Promise(resolve => child.once("close", (code, signal) => resolve({code, signal})));
  children.set(child, closed);
  if (!Number.isSafeInteger(child.pid) || child.pid < 1 || child.pid === process.pid) {
    throw new Error("probe_identity");
  }
  return {child, closed, result: () => {
    if (spawnError || overflow || stderrBytes || output.length > OUTPUT_LIMIT) throw new Error("probe_output");
    const line = output.toString("utf8");
    if (!line.endsWith("\n") || line.slice(0, -1).includes("\n")) throw new Error("probe_output");
    const value = JSON.parse(line);
    if (!value || typeof value !== "object" || Array.isArray(value) || value.v !== 1) throw new Error("probe_output");
    return value;
  }};
}

async function finishProbe(probe, deadline, children) {
  const outcome = await bounded(probe.closed, deadline, 25000);
  children.delete(probe.child);
  if (outcome.code !== 0 || outcome.signal !== null) throw new Error("probe_exit");
  return probe.result();
}

async function invitedProbe(mode, runtime, deadline, children) {
  const child = spawnProbe(mode, runtime.pipe, children);
  let registered = false;
  try {
    const token = await bounded(runtime.registerHelper(child.child.pid, budget(deadline, 5000)), deadline, 5000);
    registered = true;
    if (typeof token !== "string" || !/^[0-9a-f]{64}$/.test(token)) throw new Error("invitation_shape");
    await bounded(new Promise((resolve, reject) => child.child.stdin.write(`MESH-INVITE/1 ${token}\n`,
      error => error ? reject(new Error("invitation_write")) : resolve())), deadline, 5000);
    child.child.stdin.end();
    return await finishProbe(child, deadline, children);
  } finally {
    if (registered && mode !== "expired") await runtime.removeHelper(child.child.pid, budget(deadline, 5000));
  }
}

function lineFrom(child, deadline, cap = 10000) {
  return bounded(new Promise((resolve, reject) => {
    let pending = Buffer.alloc(0);
    function fail() { cleanup(); reject(new Error("process_line")); }
    function data(chunk) {
      if (pending.length + chunk.length > OUTPUT_LIMIT) return fail();
      pending = Buffer.concat([pending, chunk]);
      const end = pending.indexOf(10);
      if (end < 0) return;
      if (end !== pending.length - 1) return fail();
      cleanup(); resolve(pending.toString("utf8").trimEnd());
    }
    function cleanup() { child.stdout.off("data", data); child.stdout.off("end", fail); child.off("error", fail); }
    child.stdout.on("data", data);
    child.stdout.once("end", fail);
    child.once("error", fail);
  }), deadline, cap);
}

async function ownerDeath(executable, dataDirectory, deadline, children) {
  // The supervisor obtains a Windows process handle before killing the owner.
  // No invitation or private control data crosses this process boundary.
  const owner = spawn(process.execPath, [SOURCE, "--death-owner", executable, dataDirectory], {
    env: cleanEnvironment(), stdio: ["pipe", "pipe", "pipe"], windowsHide: true,
  });
  const ownerClosed = new Promise(resolve => owner.once("close", (code, signal) => resolve({code, signal})));
  children.set(owner, ownerClosed);
  owner.on("error", () => {});
  owner.stderr.resume();
  try {
    const identity = JSON.parse(await lineFrom(owner, deadline));
    if (identity?.v !== 1 || !Number.isSafeInteger(identity.host_pid) || identity.host_pid < 1
        || identity.host_pid === owner.pid || !validPipe(identity.pipe)) throw new Error("death_owner_identity");
    // The held handle prevents PID reuse while CIM verifies the exact image
    // and parent process. Any query failure or mismatch precludes READY.
    const script = hostWitnessScript(identity.host_pid, owner.pid, executable);
    const witness = spawn("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], {
      env: cleanEnvironment(), stdio: ["ignore", "pipe", "pipe"], windowsHide: true,
    });
    const witnessClosed = new Promise(resolve => witness.once("close", (code, signal) => resolve({code, signal})));
    children.set(witness, witnessClosed);
    witness.on("error", () => {});
    witness.stderr.resume();
    const lines = createInterface({input: witness.stdout, crlfDelay: Infinity})[Symbol.asyncIterator]();
    const readyLine = await bounded(lines.next(), deadline, 10000);
    const ready = !readyLine.done && readyLine.value.length <= 100 ? readyLine.value : "";
    if (ready !== "READY") throw new Error("host_handle_not_pinned");
    if (!owner.kill()) throw new Error("owner_kill_failed");
    const ownerExit = await bounded(ownerClosed, deadline, 10000);
    children.delete(owner);
    if (ownerExit.signal === null) throw new Error("owner_not_killed");
    const exitLine = await bounded(lines.next(), deadline, 25000);
    const exit = !exitLine.done && exitLine.value.length <= 100 ? exitLine.value : "";
    const witnessExit = await bounded(witnessClosed, deadline, 5000);
    children.delete(witness);
    if (exit !== "EXIT" || witnessExit.code !== 0 || witnessExit.signal !== null) {
      throw new Error("host_survived_owner_death");
    }
    // This only proves process retirement; it does not assert vault continuity.
    return true;
  } finally {
    if (owner.exitCode === null && owner.signalCode === null) owner.kill();
  }
}

async function deathOwner(executable, dataDirectory) {
  if (process.platform !== "win32" || !isAbsolute(executable) || !isAbsolute(dataDirectory)) {
    throw new Error("death_owner_arguments");
  }
  let runtime;
  runtime = await launchRuntime(executable, dataDirectory, {
    timeoutMs: 30000, privateHelperAdmission: true, onOwned: value => { runtime = value; },
  });
  const client = await CoreClient.open(await connectNamedPipe(runtime.pipe, 10000), {requestTimeoutMs: 10000});
  if (!Array.isArray(client.capabilities.profiles) || client.capabilities.profiles.length !== 1
      || !Number.isSafeInteger(runtime.hostPid) || runtime.hostPid < 1) throw new Error("death_owner_start");
  process.stdout.write(JSON.stringify({v: 1, host_pid: runtime.hostPid, pipe: runtime.pipe}) + "\n");
  await new Promise(() => {}); // Supervisor must terminate this owner without EOF.
}

async function check(executable, dataDirectory) {
  const started = performance.now(), deadline = started + TOTAL_MS;
  let phase = "arguments", runtime, owner, helper, stopped = false, passed = false;
  const children = new Map();
  const checks = {};
  try {
    if (process.platform !== "win32" || !isAbsolute(executable) || !isAbsolute(dataDirectory)) throw new Error("arguments");
    phase = "private_owner_start";
    runtime = await launchRuntime(executable, dataDirectory, {
      timeoutMs: budget(deadline), privateHelperAdmission: true, onOwned: value => { runtime = value; },
    });
    owner = await CoreClient.open(await connectNamedPipe(runtime.pipe, budget(deadline, 10000)),
      {requestTimeoutMs: budget(deadline)});
    const handle = owner.capabilities.profiles?.[0];
    if (typeof handle !== "string" || owner.capabilities.profiles.length !== 1
        || owner.capabilities.operations?.includes("native.command")) throw new Error("owner_capabilities");
    await owner.request("profile.create", {display_name: "Private admission"},
      {idempotencyKey: randomUUID(), timeoutMs: budget(deadline)});
    const profile = await owner.request("profile.query", {profile: handle}, {timeoutMs: budget(deadline)});
    if (typeof profile?.destination !== "string" || !profile.destination) throw new Error("owner_profile");
    checks.owner_usable = true;

    phase = "unregistered_same_image";
    const unregistered = spawnProbe("unregistered", runtime.pipe, children);
    const deniedSameImage = await finishProbe(unregistered, deadline, children);
    if (deniedSameImage.mode !== "unregistered" || deniedSameImage.connected !== true
        || deniedSameImage.closed_before_core_reply !== true) throw new Error("unregistered_admitted");
    checks.unregistered_same_image_denied = true;

    phase = "registered_helper";
    helper = new Helper(runtime.pipe, {privateMode: true});
    await helper.startPrivate(runtime, deadline);
    const helperCaps = await helper.request("runtime.capabilities", {}, deadline);
    if (helperCaps.profiles?.[0] !== handle || helperCaps.profiles.length !== 1
        || helperCaps.operations?.includes("native.command")) throw new Error("helper_capabilities");
    const helperProfile = await helper.request("profile.query", {profile: handle}, deadline);
    if (helperProfile.destination !== profile.destination) throw new Error("helper_profile");
    checks.registered_helper_once = true;

    phase = "removed_helper";
    const before = (await owner.request("settings.query", {profile: handle}, {timeoutMs: budget(deadline)})).settings;
    if (typeof before?.nearby_discovery !== "boolean") throw new Error("settings_shape");
    const changedSetting = {nearby_discovery: !before.nearby_discovery};
    await owner.request("settings.update", {profile: handle, settings: changedSetting},
      {idempotencyKey: randomUUID(), timeoutMs: budget(deadline)});
    const changed = (await owner.request("settings.query", {profile: handle}, {timeoutMs: budget(deadline)})).settings;
    if (changed.nearby_discovery !== changedSetting.nearby_discovery) throw new Error("mutation_control");
    await owner.request("settings.update", {profile: handle,
      settings: {nearby_discovery: before.nearby_discovery}},
    {idempotencyKey: randomUUID(), timeoutMs: budget(deadline)});
    const restored = (await owner.request("settings.query", {profile: handle}, {timeoutMs: budget(deadline)})).settings;
    if (restored.nearby_discovery !== before.nearby_discovery) throw new Error("mutation_restore");
    checks.owner_mutation_control = true;
    await runtime.removeHelper(helper.child.pid, budget(deadline, 5000));
    await requireRevokedHelper(helper, handle, changedSetting, deadline);
    const after = (await owner.request("settings.query", {profile: handle}, {timeoutMs: budget(deadline)})).settings;
    if (after.nearby_discovery !== before.nearby_discovery) {
      throw new Error("removed_helper_mutated");
    }
    checks.removed_helper_mutation_denied = true;
    helper = null;

    phase = "one_use_replay";
    const replay = await invitedProbe("valid_replay", runtime, deadline, children);
    if (replay.mode !== "valid_replay" || replay.first_admitted !== true || replay.replay_denied !== true) {
      throw new Error("replay_admitted");
    }
    checks.one_use_replay_denied = true;
    phase = "wrong_preface";
    const wrong = await invitedProbe("wrong_preface", runtime, deadline, children);
    if (wrong.mode !== "wrong_preface" || wrong.connected !== true
        || wrong.closed_before_core_reply !== true) throw new Error("wrong_preface_admitted");
    checks.wrong_preface_denied = true;
    phase = "expired_invitation";
    const expired = await invitedProbe("expired", runtime, deadline, children);
    if (expired.mode !== "expired" || expired.connected !== true
        || expired.closed_before_core_reply !== true) throw new Error("expired_admitted");
    checks.expired_invitation_denied = true;

    phase = "owner_after_denials";
    const unchanged = await owner.request("profile.query", {profile: handle}, {timeoutMs: budget(deadline)});
    if (unchanged.destination !== profile.destination) throw new Error("owner_changed");
    checks.owner_survived_denials = true;
    phase = "owner_eof";
    owner.close(); owner = null;
    const retirement = await runtime.stop(budget(deadline));
    stopped = retirement?.stopped === true && retirement.exit_code === 0;
    if (!stopped) throw new Error("owner_retirement");
    checks.owner_eof_retires_host = true;
    phase = "owner_death";
    if (!await ownerDeath(executable, join(dataDirectory, `owner-death-${randomUUID()}`), deadline, children)) {
      throw new Error("owner_death");
    }
    checks.owner_death_retires_host = true;
    passed = true;
  } catch { passed = false; }
  finally {
    try { owner?.close(); } catch { passed = false; }
    if (helper) try { await helper.dispose(); } catch { passed = false; }
    for (const [child, closed] of children) {
      if (child.exitCode === null && child.signalCode === null) child.kill();
      try { await bounded(closed, deadline, 5000); children.delete(child); } catch { passed = false; }
    }
    if (runtime && !stopped) {
      try { const value = await runtime.stop(Math.min(30000, Math.max(0, Math.floor(deadline - performance.now()))));
        stopped = value?.stopped === true && value.exit_code === 0; }
      catch { passed = false; }
    }
    if (children.size || !stopped || performance.now() > deadline) passed = false;
  }
  return {v: 1, passed, scope: SCOPE, ...(passed ? {checks} : {phase}),
    duration_ms: Math.min(TOTAL_MS, Math.max(0, Math.floor(performance.now() - started)))};
}

const args = process.argv.slice(2);
let result;
try {
  if (args.length === 3 && args[0] === "--probe") result = await probe(args[1], args[2]);
  else if (args.length === 3 && args[0] === "--death-owner") result = await deathOwner(args[1], args[2]);
  else if (args.length === 4 && args[0] === "--runtime" && args[2] === "--data-directory") {
    result = await check(args[1], args[3]);
  } else result = {v: 1, passed: false, scope: SCOPE, phase: "arguments", duration_ms: 0};
} catch { result = {v: 1, passed: false, phase: "probe"}; }
process.stdout.on("error", () => process.exit(1));
process.stdout.write(JSON.stringify(result) + "\n", () => process.exit(result.passed === false ? 1 : 0));
