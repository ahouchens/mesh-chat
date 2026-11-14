import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { test } from "node:test";
import { PassThrough } from "node:stream";
import { fileURLToPath } from "node:url";
import { boundedCdpFrame, closeBoundedSocket, completeAfterCleanup, readBoundedInput, withDeadline } from "../../scripts/windows_release_ui_io.mjs";

test("oversized unterminated stdin is refused before EOF", async () => {
  const input = new PassThrough();
  const reading = readBoundedInput(input, 2_048, 1_000);
  input.write(Buffer.alloc(2_049, 65));
  await assert.rejects(reading, /ui_config_unbounded/);
  assert.equal(input.destroyed, true);
});

test("stdin without EOF reaches a finite deadline and is retired", async () => {
  const input = new PassThrough();
  const reading = readBoundedInput(input, 2_048, 20);
  input.write('{"phase":"seed"}');
  await assert.rejects(reading, /ui_config_deadline/);
  assert.equal(input.destroyed, true);
});

test("bounded stdin accepts a complete small input", async () => {
  const input = new PassThrough();
  const reading = readBoundedInput(input, 2_048, 1_000);
  input.end('{"phase":"seed"}');
  assert.equal(await reading, '{"phase":"seed"}');
  assert.equal(input.listenerCount("data"), 0);
});

test("deadline helper clears timer after success and failure", async () => {
  let created = 0, cleared = 0;
  const timers = {
    setTimeout() { return ++created; },
    clearTimeout() { cleared += 1; },
  };
  assert.equal(await withDeadline(Promise.resolve("ok"), 1_000, "late", timers), "ok");
  await assert.rejects(withDeadline(Promise.reject(new Error("failed")), 1_000, "late", timers), /failed/);
  assert.equal(created, 2);
  assert.equal(cleared, 2);
});

test("CDP frame is byte-bounded before JSON parsing", () => {
  assert.deepEqual(boundedCdpFrame('{"id":1}'), { id: 1 });
  assert.throws(() => boundedCdpFrame('{' + "x".repeat(65_536)), /ui_cdp_frame_unbounded/);
  assert.throws(() => boundedCdpFrame(new Uint8Array(10)), /ui_cdp_frame_unbounded/);
});

test("socket close is observed before success; missing close fails in a bound", async () => {
  class ClosingSocket extends EventTarget {
    readyState = 1;
    closeCalls = 0;
    close() {
      this.closeCalls += 1;
      this.readyState = 2;
      queueMicrotask(() => { this.readyState = 3; this.dispatchEvent(new Event("close")); });
    }
  }
  const closed = new ClosingSocket();
  assert.equal(await closeBoundedSocket(closed, 100), true);
  assert.equal(closed.closeCalls, 1);
  assert.equal(closed.readyState, 3);
  const stuck = new ClosingSocket();
  stuck.close = () => { stuck.readyState = 2; };
  await assert.rejects(closeBoundedSocket(stuck, 20), /ui_socket_retirement_deadline/);
});

test("success cannot be emitted before cleanup; failed cleanup rejects it", async () => {
  let release;
  const close = new Promise((resolve) => { release = resolve; });
  let completed = false;
  const result = completeAfterCleanup(async () => "ready", () => close)
    .then((value) => { completed = true; return value; });
  await Promise.resolve();
  assert.equal(completed, false);
  release();
  assert.equal(await result, "ready");
  assert.equal(completed, true);
  await assert.rejects(completeAfterCleanup(async () => "ready", async () => {
    throw new Error("retirement_failed");
  }), /retirement_failed/);
});

function invokeWithoutEof(data) {
  return new Promise((resolve, reject) => {
    const script = fileURLToPath(new URL("../../scripts/check_windows_release_ui.mjs", import.meta.url));
    const child = spawn(process.execPath, [script, "12345"], { stdio: ["pipe", "pipe", "ignore"] });
    child.stdin.on("error", () => {});
    let output = "";
    child.stdout.on("data", (chunk) => {
      output += chunk.toString("utf8");
      if (output.length > 1_024) child.kill();
    });
    const watchdog = setTimeout(() => { child.kill(); reject(new Error("child_deadline")); }, 7_000);
    child.on("close", (code) => { clearTimeout(watchdog); resolve({ code, output }); });
    child.on("error", (error) => { clearTimeout(watchdog); reject(error); });
    child.stdin.write(data);
  });
}

test("driver refuses oversized and missing-EOF input with sanitized output", async () => {
  for (const data of ["x".repeat(2_049), '{"phase":"seed"}']) {
    const result = await invokeWithoutEof(data);
    assert.equal(result.code, 1);
    assert.deepEqual(JSON.parse(result.output), {
      v: 1, passed: false, evidence_level: "windows_release_ui_seed_readback_contract_only",
      failure_kind: "ui_contract_failed",
    });
    assert.equal(result.output.includes(data.slice(0, 20)), false);
  }
});
