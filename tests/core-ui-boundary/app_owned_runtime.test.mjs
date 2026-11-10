// Subprocess lifetime protocol components only; no Core or native host substitute.
import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { observeRuntime, observeRuntimeRefusal } from "../../examples/typescript-independent-consumer/runtime.mjs";

const pipe = "\\\\.\\pipe\\mesh-chat-independent-component";
const prelude = `
const pipe = ${JSON.stringify(pipe)};
function frame(value) {
  const body = Buffer.from(JSON.stringify(value));
  const header = Buffer.alloc(4); header.writeUInt32BE(body.length);
  return Buffer.concat([header, body]);
}
function send(type, fields={}) { process.stdout.write(frame({v:1,type,...fields})); }
process.stdin.resume();
`;
function run(script, timeout = 5000) {
  const child = spawn(process.execPath, ["--input-type=module", "-e", prelude + script], {
    stdio: ["pipe", "pipe", "pipe"], windowsHide: true,
  });
  return observeRuntime(child, pipe, timeout);
}

test("fragmented startup and deferred retirement require the final process acknowledgement", async () => {
  const runtime = run(`
    const started = frame({v:1,type:'runtime_started',pipe});
    for (const byte of started) process.stdout.write(Buffer.from([byte]));
    process.stdin.on('end', () => {
      send('runtime_retiring');
      setTimeout(() => { send('runtime_stopped'); process.exitCode=0; }, 30);
    });
  `);
  await runtime.ready;
  await runtime.stop();
  await runtime.stop();
});

for (const [name, script] of [
  ["wrong pipe", "send('runtime_started',{pipe:pipe+'other'});"],
  ["extra authority field", "send('runtime_started',{pipe,grants:['owner']});"],
  ["unbounded status", "const header=Buffer.alloc(4); header.writeUInt32BE(4097); process.stdout.write(header);"],
  ["invalid UTF-8", "process.stdout.write(Buffer.from([0,0,0,2,0xff,0xff]));"],
  ["duplicate startup", "send('runtime_started',{pipe}); send('runtime_started',{pipe});"],
  ["failure status", "send('runtime_failed',{error:'unavailable'});"],
]) {
  test(`reject ${name} without accepting cleanup`, async () => {
    const runtime = run(script + "process.stdin.on('end',()=>process.exit(0));");
    try { await runtime.ready; } catch { /* Some faults arrive after startup. */ }
    await assert.rejects(runtime.stop(), /app_owned_runtime_unavailable/);
  });
}

for (const [name, end] of [
  ["missing stopped", "process.exitCode=0;"],
  ["nonzero exit", "send('runtime_stopped'); process.exitCode=2;"],
  ["truncated final frame", "process.stdout.write(Buffer.from([0,0]));"],
]) {
  test(`reject ${name} after a valid startup`, async () => {
    const runtime = run(`send('runtime_started',{pipe}); process.stdin.on('end',()=>{${end}});`);
    await runtime.ready;
    await assert.rejects(runtime.stop(), /app_owned_runtime_unavailable/);
  });
}

test("silent startup has a bounded failure and requests EOF cleanup", async () => {
  const runtime = run("process.stdin.on('end',()=>process.exit(0));", 50);
  await assert.rejects(runtime.ready, /app_owned_runtime_unavailable/);
  await assert.rejects(runtime.stop(), /app_owned_runtime_unavailable/);
});

async function refusal(script, check, timeout = 5000) {
  const child = spawn(process.execPath, ["--input-type=module", "-e", prelude + script], {
    stdio: ["pipe", "pipe", "pipe"], windowsHide: true,
  });
  const closed = new Promise(resolve => child.once("close", resolve));
  const runtime = observeRuntimeRefusal(child, pipe, timeout);
  try { await check(runtime); }
  finally {
    if (child.exitCode === null) child.kill(); // Component teardown, never completion evidence.
    await closed;
  }
}

test("expected refusal requires unavailable, partial retirement and exact exit2", async () => {
  await refusal(`
    send('runtime_failed',{error:'unavailable'});
    process.stdin.on('end',()=>{
      send('runtime_retiring');
      setTimeout(()=>{send('runtime_stopped');process.exitCode=2;},30);
    });`, async runtime => {
    await runtime.ready;
    assert.deepEqual(await runtime.stop(0), {stopped:true,exit_code:2,refused:true,error:'unavailable'});
  });
});

for (const [name, script] of [
  ["no stopped", "send('runtime_failed',{error:'unavailable'});"],
  ["no failed", "send('runtime_stopped');"],
  ["wrong error", "send('runtime_failed',{error:'native_unavailable'});send('runtime_stopped');"],
  ["started then failed", "send('runtime_started',{pipe});send('runtime_failed',{error:'unavailable'});send('runtime_stopped');"],
  ["wrong pipe", "send('runtime_started',{pipe:pipe+'other'});send('runtime_failed',{error:'unavailable'});send('runtime_stopped');"],
  ["duplicate failed", "send('runtime_failed',{error:'unavailable'});send('runtime_failed',{error:'unavailable'});send('runtime_stopped');"],
  ["extra authority", "send('runtime_failed',{error:'unavailable',grants:['owner']});send('runtime_stopped');"],
  ["oversized", "const h=Buffer.alloc(4);h.writeUInt32BE(4097);process.stdout.write(h);"],
  ["malformed", "process.stdout.write(Buffer.from([0,0,0,2,0xff,0xff]));"],
  ["duplicate stopped", "send('runtime_failed',{error:'unavailable'});send('runtime_stopped');send('runtime_stopped');"],
  ["wrong exit", "send('runtime_failed',{error:'unavailable'});send('runtime_stopped');"],
]) {
  test(`expected refusal rejects ${name}`, async () => {
    const code = ["wrong exit", "no failed"].includes(name) ? 0 : 2;
    await refusal(script + `process.stdin.on('end',()=>{process.exitCode=${code};});`, async runtime => {
      await assert.rejects(runtime.ready, /app_owned_runtime_unavailable/);
      await assert.rejects(runtime.stop(), /app_owned_runtime_unavailable/);
    });
  });
}

for (const stopped of [false, true]) {
  test(`refusal ${stopped ? "with" : "without"} stopped but no child exit cannot pass`, async () => {
    await refusal(`send('runtime_failed',{error:'unavailable'});${stopped ? "send('runtime_stopped');" : ""}
      setInterval(()=>{},1000);`, async runtime => {
      await assert.rejects(runtime.ready, /app_owned_runtime_unavailable/);
      await assert.rejects(runtime.stop(0), /app_owned_runtime_retirement_pending/);
    }, 500);
  });
}

test("exhausted retirement budget still sends EOF and cannot accept a later exit", async () => {
  const child = spawn(process.execPath, ["--input-type=module", "-e", prelude + `
    send('runtime_started',{pipe});
    process.stdin.on('end',()=>setTimeout(()=>{send('runtime_stopped');process.exitCode=0;},50));`],
    {stdio:["pipe","pipe","pipe"],windowsHide:true});
  const closed = new Promise(resolve => child.once("close", resolve));
  const runtime = observeRuntime(child, pipe);
  try {
    await runtime.ready;
    await assert.rejects(runtime.stop(0), /app_owned_runtime_retirement_pending/);
    assert.equal(await closed, 0); // The failed observation did request EOF; late close is teardown only.
  } finally {
    if (child.exitCode === null) child.kill();
    await closed;
  }
});
