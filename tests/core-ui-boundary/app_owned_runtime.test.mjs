// Subprocess lifetime protocol components only; no Core or native host substitute.
import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { observeRuntime } from "../../examples/typescript-independent-consumer/runtime.mjs";

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
