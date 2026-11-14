import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { test } from "node:test";
import { Helper, HelperCoreError } from "./public-process-helper.mjs";
import { observeRuntime } from "./runtime.mjs";
import { hostWitnessScript, requireDeniedBeforeReply, requireOwnerSettingsControl, requireRevokedHelper } from "./private-admission-evidence.mjs";

const TOKEN = "a".repeat(64);
const PIPE = "private-test-pipe";
const parserUrl = new URL("./public-process-helper.mjs", import.meta.url).href;
const consumerUrl = new URL("./consumer.mjs", import.meta.url).href;

async function childClose(child, ms = 3000) {
  if (child.exitCode !== null) return child.exitCode;
  let timer;
  try {
    return await Promise.race([once(child, "close").then(([code]) => code),
      new Promise((_, reject) => { timer = setTimeout(() => {
        child.kill(); reject(new Error("test_child_deadline"));
      }, ms); })]);
  } finally { clearTimeout(timer); }
}

async function parserChild(input, {holdOpen = false} = {}) {
  const script = `import { PrivateConsumerInput } from ${JSON.stringify(parserUrl)};
    const source = new PrivateConsumerInput(process.stdin);
    try {
      const token = await source.invitation(500);
      const values = [];
      for await (const value of source.frames()) values.push(value);
      process.stdout.write(JSON.stringify({valid:token === ${JSON.stringify(TOKEN)},values}));
    } catch { process.stdin.destroy(); process.stdout.write('invalid'); process.exitCode = 2; }`;
  const child = spawn(process.execPath, ["--input-type=module", "-e", script],
    { stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
  let output = "";
  child.stdout.on("data", chunk => {
    output += chunk.toString("utf8");
    if (output.length > 2048) child.kill();
  });
  child.stderr.resume();
  if (holdOpen) child.stdin.write(input);
  else child.stdin.end(input);
  const code = await childClose(child);
  return { code, output };
}

async function consumerChild(input, privateMode) {
  const clientSource = `export class CoreError extends Error {}
    export const CoreClient = {async open(transport) {
      if (Boolean(globalThis.__prefaced) !== globalThis.__privateExpected) throw new Error('wrong_open_order');
      return {async request() {return {preface_before_open:Boolean(globalThis.__prefaced)};}, close() {transport.close();}};
    }};`;
  const nodeSource = `export async function connectNamedPipe() {return {
    async writeLine(line) {
      if (!/^MESH-HELPER\\/1 [0-9a-f]{64}\\n$/.test(line)) throw new Error('bad_preface');
      globalThis.__prefaced = true;
    }, close() {globalThis.__transportClosed = true;}
  };}`;
  const script = `import { registerHooks } from 'node:module';
    globalThis.__privateExpected=${privateMode};
    const client=${JSON.stringify(`data:text/javascript,${encodeURIComponent(clientSource)}`)};
    const node=${JSON.stringify(`data:text/javascript,${encodeURIComponent(nodeSource)}`)};
    registerHooks({resolve(specifier,context,nextResolve) {
      if (specifier === '@mesh-chat/core-client') return {url:client,shortCircuit:true};
      if (specifier === '@mesh-chat/core-client/node') return {url:node,shortCircuit:true};
      return nextResolve(specifier,context);
    }});
    process.argv=[process.execPath,${JSON.stringify(consumerUrl)},
      ...(${privateMode} ? ['--private-helper'] : []),'--pipe',${JSON.stringify(PIPE)}];
    await import(${JSON.stringify(consumerUrl)});`;
  const child = spawn(process.execPath, ["--input-type=module", "-e", script],
    { stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
  let output = "", stderr = "";
  child.stdout.on("data", chunk => {
    output += chunk.toString("utf8");
    if (output.length > 2048) child.kill();
  });
  child.stderr.on("data", chunk => { stderr += chunk.toString("utf8").slice(0, 2048); });
  child.stdin.end(input);
  return {code:await childClose(child), output, stderr};
}

test("private invitation and first Core command in one chunk preserve read-ahead", { timeout: 5000 }, async () => {
  const input = `MESH-INVITE/1 ${TOKEN}\n{"id":"first"}\n{"id":"second"}\n`;
  const result = await parserChild(input);
  assert.equal(result.code, 0);
  assert.deepEqual(JSON.parse(result.output), { valid: true,
    values: [{id:"first"}, {id:"second"}] });
});

test("consumer writes private pipe preface before SDK open; normal mode has none", { timeout: 5000 }, async () => {
  const command = '{"id":"first","operation":"runtime.capabilities","params":{}}\n';
  const privateResult = await consumerChild(`MESH-INVITE/1 ${TOKEN}\n${command}`, true);
  assert.equal(privateResult.code, 0, privateResult.stderr);
  assert.deepEqual(JSON.parse(privateResult.output),
    {id:"first",ok:true,result:{preface_before_open:true}});
  const normalResult = await consumerChild(command, false);
  assert.equal(normalResult.code, 0, normalResult.stderr);
  assert.deepEqual(JSON.parse(normalResult.output),
    {id:"first",ok:true,result:{preface_before_open:false}});
});

test("private parser refuses partial, non-ASCII, NUL, CR and oversized invitation", { timeout: 15000 }, async () => {
  for (const input of [
    `MESH-INVITE/1 ${TOKEN}`, `MESH-INVITE/1 ${TOKEN}\r\n`,
    `MESH-INVITE/1 ${TOKEN}\x00\n`, `MESH-INVITE/1 ${"A".repeat(64)}\n`,
    Buffer.concat([Buffer.from("MESH-INVITE/1 "), Buffer.alloc(64, 0xff), Buffer.from("\n")]),
    "X".repeat(80),
  ]) {
    const result = await parserChild(input);
    assert.equal(result.code, 2);
    assert.equal(result.output, "invalid");
  }
  const trickle = await parserChild(`MESH-INVITE/1 ${TOKEN.slice(0, 10)}`, {holdOpen: true});
  assert.equal(trickle.code, 2);
  assert.equal(trickle.output, "invalid");
});

function host(mode) {
  const script = `const mode = ${JSON.stringify(mode)}, pipe = ${JSON.stringify(PIPE)};
    function send(value) { const body=Buffer.from(JSON.stringify(value));
      const head=Buffer.alloc(4); head.writeUInt32BE(body.length); process.stdout.write(Buffer.concat([head,body])); }
    send({v:1,type:'runtime_started',pipe});
    let pending='';
    process.stdin.on('data', chunk => {
      pending += chunk.toString('utf8');
      while (pending.includes('\\n')) {
        const end=pending.indexOf('\\n'); const line=pending.slice(0,end+1); pending=pending.slice(end+1);
        const match=/^(REGISTER\\/1|REMOVE\\/1) ([0-9a-f]{8}) ([1-9][0-9]*)\\n$/.exec(line);
        if (!match) { process.exitCode=3; process.stdin.destroy(); return; }
        const value={v:1,type:match[1]==='REGISTER/1'?'helper_registered':'helper_removed',
          sequence:mode==='wrong'?'ffffffff':match[2],
          ...(match[1]==='REGISTER/1'?{invitation:${JSON.stringify(TOKEN)}}:{})};
        if (mode==='silent') continue;
        if (mode==='exit') process.exit(4);
        if (mode==='partial') { process.stdout.write(Buffer.from([0,0])); continue; }
        if (mode==='extra') value.extra=1;
        if (mode==='uppercase') value.invitation='A'.repeat(64);
        if (mode==='late') { setTimeout(() => send(value), 400); continue; }
        send(value);
        if (mode==='duplicate') send(value);
      }
    });
    process.stdin.on('end', () => { send({v:1,type:'runtime_stopped'}); });`;
  const child = spawn(process.execPath, ["-e", script],
    { stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
  return child;
}

test("owner controls serialize and correlate exact private register/remove acks", { timeout: 5000 }, async () => {
  const child = host("normal");
  const runtime = observeRuntime(child, PIPE, 3000);
  await runtime.ready;
  assert.equal(await runtime.registerHelper(42, 1000), TOKEN);
  assert.equal(await runtime.removeHelper(42, 1000), true);
  assert.deepEqual(await runtime.stop(1000), {stopped:true,exit_code:0});
  assert.equal(child.exitCode, 0);
});

test("only one owner command can be outstanding", { timeout: 5000 }, async () => {
  const child = host("normal");
  const runtime = observeRuntime(child, PIPE, 3000);
  await runtime.ready;
  const first = runtime.registerHelper(42, 1000);
  await assert.rejects(runtime.removeHelper(42, 1000), /app_owned_helper_control_unavailable/);
  assert.equal(await first, TOKEN);
  assert.equal(await runtime.removeHelper(42, 1000), true);
  await runtime.stop(1000);
});

test("missing, partial, late, wrong, duplicate and malformed ack fail closed", { timeout: 15000 }, async () => {
  for (const mode of ["silent", "partial", "late", "wrong", "duplicate", "extra", "uppercase", "exit"]) {
    const child = host(mode);
    const runtime = observeRuntime(child, PIPE, 3000);
    await runtime.ready;
    if (mode === "duplicate") {
      await runtime.registerHelper(42, 300).catch(() => {});
      await new Promise(resolve => setTimeout(resolve, 30));
    } else await assert.rejects(runtime.registerHelper(42, 100), /app_owned_helper_control_failed/);
    await assert.rejects(runtime.stop(1000), /app_owned_runtime_unavailable/);
    assert.equal(await childClose(child), mode === "exit" ? 4 : 0);
  }
});

test("failed owner write and helper exit retain exact child custody", { timeout: 5000 }, async () => {
  const child = host("silent");
  const runtime = observeRuntime(child, PIPE, 3000);
  await runtime.ready;
  const request = runtime.registerHelper(42, 500);
  child.stdin.destroy(new Error("test_write_failure"));
  await assert.rejects(request, /app_owned_helper_control_failed/);
  await assert.rejects(runtime.stop(1000), /app_owned_runtime_unavailable/);
  assert.equal(await childClose(child), 0);

  const exited = spawn(process.execPath, ["-e", "setTimeout(() => process.exit(4), 10)"],
    { stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
  const helper = Object.create(Helper.prototype);
  Object.assign(helper, { child: exited, identityValid: true, privateMode: true,
    privateStarted: false, privateStarting: false, exited: false, outputFailure: false });
  helper.exit = new Promise(resolve => exited.once("close", () => { helper.exited = true; resolve(); }));
  exited.stdout.resume(); exited.stderr.resume();
  const removed = [];
  const owner = { async registerHelper() { await helper.exit; return TOKEN; },
    async removeHelper(pid) { removed.push(pid); return true; } };
  await assert.rejects(helper.startPrivate(owner, performance.now() + 1000), /private_helper_start_failed/);
  assert.equal(helper.child, exited);
  assert.equal(helper.outputFailure, true);
  assert.deepEqual(removed, [exited.pid]);
  assert.equal(await childClose(exited), 4);
});

test("failed private invitation write revokes the registered helper", { timeout: 5000 }, async () => {
  const child = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"],
    { stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
  child.stdout.resume(); child.stderr.resume(); child.stdin.on("error", () => {});
  const helper = Object.create(Helper.prototype);
  Object.assign(helper, { child, identityValid: true, privateMode: true,
    privateStarted: false, privateStarting: false, exited: false, outputFailure: false });
  helper.exit = new Promise(resolve => child.once("close", () => { helper.exited = true; resolve(); }));
  const removed = [];
  const owner = { async registerHelper() { return TOKEN; },
    async removeHelper(pid) { removed.push(pid); return true; } };
  try {
    child.stdin.destroy();
    await assert.rejects(helper.startPrivate(owner, performance.now() + 1000), /private_helper_start_failed/);
    assert.equal(helper.privateStarted, false);
    assert.equal(helper.outputFailure, true);
    assert.deepEqual(removed, [child.pid]);
    assert.equal(helper.child, child);
  } finally { child.kill(); await childClose(child); }
});

test("removed helper evidence requires exact unauthenticated result and clean exit", async () => {
  let closed = 0;
  const helper = {
    async request(operation, params, deadline, key) {
      assert.equal(operation, "settings.update");
      assert.deepEqual(params, {profile: "local", settings: {nearby_discovery: true}});
      assert.equal(deadline, 12345);
      assert.equal(key, undefined); // settings.update has no caller idempotency key.
      throw new HelperCoreError("unauthenticated");
    },
    async closeInput(deadline) { assert.equal(deadline, 12345); closed++; },
  };
  await requireRevokedHelper(helper, "local", {nearby_discovery: true}, 12345);
  assert.equal(closed, 1);
});

test("owner mutation control uses the public non-keyed settings operation", async () => {
  let nearbyDiscovery = false;
  const calls = [];
  const owner = {async request(operation, params, options) {
    calls.push({operation, params, options});
    assert.deepEqual(options, {timeoutMs: 1000});
    if (operation === "settings.query") return {settings: {nearby_discovery: nearbyDiscovery}};
    if (operation === "settings.update") {
      nearbyDiscovery = params.settings.nearby_discovery;
      return {settings: {nearby_discovery: nearbyDiscovery}};
    }
    throw new Error("unexpected_operation");
  }};
  const control = await requireOwnerSettingsControl(owner, "profile-handle", () => 1000);
  assert.equal(nearbyDiscovery, false);
  assert.deepEqual(control, {before: {nearby_discovery: false}, changedSetting: {nearby_discovery: true}});
  assert.deepEqual(calls.map(({operation}) => operation), [
    "settings.query", "settings.update", "settings.query", "settings.update", "settings.query",
  ]);
});

test("transport errors, other Core errors, success and dirty exits cannot prove revocation", async () => {
  for (const outcome of [new Error("transport_closed"), new HelperCoreError("forbidden"), null]) {
    let closed = false;
    const helper = {async request() { if (outcome) throw outcome; return {}; },
      async closeInput() { closed = true; }};
    await assert.rejects(requireRevokedHelper(helper, "local", {}, 12345));
    assert.equal(closed, false);
  }
  const dirty = {async request() { throw new HelperCoreError("unauthenticated"); },
    async closeInput() { throw new Error("helper_exit"); }};
  await assert.rejects(requireRevokedHelper(dirty, "local", {}, 12345), /helper_exit/);
});

test("preface write or Core open closure with zero reply bytes proves connected denial", async () => {
  class Closed extends Error {}
  for (const stage of ["write", "open"]) {
    let wrote = false, opened = false, closed = false;
    const transport = {socket: {bytesRead: 0}, async writeLine(line) {
      assert.equal(line, "preface\n"); wrote = true;
      if (stage === "write") throw new Closed();
    }, close() { closed = true; }};
    const result = await requireDeniedBeforeReply(transport, stage, "preface\n", async () => {
      opened = true; throw new Closed();
    }, Closed);
    assert.deepEqual(result, {v: 1, mode: stage, connected: true, closed_before_core_reply: true});
    assert.equal(wrote, true);
    assert.equal(opened, stage === "open");
    assert.equal(closed, true);
  }
});

test("other errors, received bytes and admitted Core client cannot prove denial", async () => {
  class Closed extends Error {}
  for (const scenario of ["other_write", "read_bytes", "admitted"]) {
    let transportClosed = false, clientClosed = false;
    const transport = {socket: {bytesRead: scenario === "read_bytes" ? 1 : 0},
      async writeLine() { if (scenario === "other_write") throw new Error("write_failed"); },
      close() { transportClosed = true; }};
    const opened = async () => scenario === "read_bytes" ? Promise.reject(new Closed())
      : {close() { clientClosed = true; }};
    await assert.rejects(requireDeniedBeforeReply(transport, scenario, "preface\n", opened, Closed));
    assert.equal(transportClosed, true);
    assert.equal(clientClosed, scenario === "admitted");
  }
});

test("owner-death witness binds pinned PID to parent and encoded executable", () => {
  const expected = "C:\\Program Files\\Owner's host;Exit 0.exe";
  const script = hostWitnessScript(345, 123, expected);
  assert.match(script, /GetProcessById\(345\); \$null=\$p.Handle/);
  assert.match(script, /Get-CimInstance -ClassName Win32_Process -Filter 'ProcessId = 345'/);
  assert.match(script, /\$p.HasExited/);
  assert.match(script, /\$info.ParentProcessId -ne 123/);
  assert.match(script, /\$info.ExecutablePath/);
  assert.equal(script.includes(expected), false);
  const encoded = script.match(/FromBase64String\('([A-Za-z0-9+/=]+)'\)/)?.[1];
  assert.equal(Buffer.from(encoded, "base64").toString("utf16le"), expected);
  assert.throws(() => hostWitnessScript(123, 123, expected), /host_witness_arguments/);
});
