import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { test } from "node:test";
import { PassThrough } from "node:stream";
import { fileURLToPath } from "node:url";
import { boundedCdpFrame, closeBoundedSocket, closeCheckedSocket, completeAfterCleanup, fixedUiFailure, readBoundedInput, UiCleanupFailure, withDeadline } from "../../scripts/windows_release_ui_io.mjs";
import { emptyStartupObservation, observeStartup, waitForStartup } from "../../scripts/windows_release_ui_startup.mjs";

const readyStartup = () => Object.fromEntries(Object.keys(emptyStartupObservation()).map((key) => [key, true]));

test("startup waits for bridge and React mount after native identity is correct", async () => {
  let time = 0;
  const seen = [];
  const observations = [emptyStartupObservation(), { ...readyStartup(), root_mounted: false }, readyStartup()];
  await waitForStartup(async (remaining) => {
    assert.equal(remaining, 500 - time);
    return observations.shift();
  }, 500, (value) => seen.push(value), { now: () => time, pause: async (ms) => { time += ms; } });
  assert.equal(seen.length, 3);
  assert.equal(time, 200);
});

test("wrong source or version fails immediately even before mount", async () => {
  for (const field of ["source_matches", "version_matches"]) {
    let calls = 0;
    await assert.rejects(waitForStartup(async () => {
      calls += 1;
      return { ...readyStartup(), [field]: false, root_mounted: false };
    }, 100, () => {}, { now: () => 0, pause: async () => assert.fail("identity mismatch must not wait") }),
    /ui_source_mismatch/);
    assert.equal(calls, 1);
  }
});

test("startup distinguishes missing bridge from mount and title deadlines", async () => {
  for (const [value, failure] of [[emptyStartupObservation(), /ui_bridge_deadline/],
    [{ ...readyStartup(), root_mounted: false }, /ui_mount_deadline/],
    [{ ...readyStartup(), title_matches: false }, /ui_mount_deadline/]]) {
    let time = 0;
    await assert.rejects(waitForStartup(async () => value, 150, () => {},
      { now: () => time, pause: async (ms) => { time += ms; } }), failure);
    assert.equal(time, 150);
  }
});

test("startup propagates CDP failure and bounds an unresolved native observation", async () => {
  await assert.rejects(waitForStartup(async () => { throw new Error("ui_cdp_failed"); },
    Date.now() + 1000, () => {}), /ui_cdp_failed/);
  await assert.rejects(waitForStartup(() => new Promise(() => {}), Date.now() + 20,
    () => {}), /ui_startup_deadline/);
});

test("startup rejects raw or malformed observations instead of retaining them", async () => {
  for (const value of [{ ...readyStartup(), source: "raw value" },
    { ...readyStartup(), root_mounted: "true" }, null]) {
    await assert.rejects(waitForStartup(async () => value, Date.now() + 1000, () => {
      assert.fail("malformed observation must not be retained");
    }), /ui_observation_failed/);
  }
});

test("page startup observation exports only boolean identity and readiness facts", async () => {
  const priorWindow = globalThis.window, priorDocument = globalThis.document;
  try {
    globalThis.document = { title: "Mesh Chat", querySelector: () => ({}) };
    globalThis.window = { __TAURI_INTERNALS__: { invoke: async (command) => {
      assert.equal(command, "app_build_info");
      return { build_commit: "a".repeat(40), installed_version: "0.9.66", unrelated: "private" };
    } } };
    assert.deepEqual(await observeStartup("a".repeat(40), "0.9.66"), readyStartup());
    delete globalThis.window.__TAURI_INTERNALS__;
    assert.deepEqual(await observeStartup("a".repeat(40), "0.9.66"),
      { ...emptyStartupObservation(), root_mounted: true, title_matches: true });
  } finally {
    if (priorWindow === undefined) delete globalThis.window; else globalThis.window = priorWindow;
    if (priorDocument === undefined) delete globalThis.document; else globalThis.document = priorDocument;
  }
});

test("only fixed UI codes pass through diagnostic attribution", () => {
  assert.equal(fixedUiFailure(new Error("ui_source_mismatch")), "ui_source_mismatch");
  assert.equal(fixedUiFailure(new Error("secret path C:\\user\\profile")), "ui_contract_failed");
  assert.equal(fixedUiFailure({ message: "ui_source_mismatch" }), "ui_contract_failed");
});

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
  for (const shape of ["null", "[]", "1", '"text"', "true"]) {
    assert.throws(() => boundedCdpFrame(shape), /ui_cdp_frame_invalid/);
  }
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
  }), (error) => error instanceof UiCleanupFailure
    && error.actionFailed === false && error.cleanup.message === "retirement_failed");
  await assert.rejects(completeAfterCleanup(async () => {
    throw new Error("ui_source_mismatch");
  }, async () => {
    throw new Error("ui_socket_retirement_failed");
  }), (error) => error instanceof UiCleanupFailure
    && error.actionFailed === true && error.primary.message === "ui_source_mismatch"
    && error.cleanup.message === "ui_socket_retirement_failed");
});

test("protocol fault during final socket retirement defeats successful readback", async () => {
  class FaultOnClose extends EventTarget {
    readyState = 1;
    close() {
      this.readyState = 2;
      queueMicrotask(() => {
        this.dispatchEvent(new MessageEvent("message", { data: "null" }));
        this.readyState = 3;
        this.dispatchEvent(new Event("close"));
      });
    }
  }
  const socket = new FaultOnClose();
  let protocolFailed = false;
  socket.addEventListener("message", (event) => {
    try { boundedCdpFrame(event.data); }
    catch { protocolFailed = true; }
  });
  await assert.rejects(
    completeAfterCleanup(async () => "successful_readback", () => closeCheckedSocket(socket, () => protocolFailed)),
    (error) => error instanceof UiCleanupFailure
      && error.actionFailed === false && error.cleanup.message === "ui_cdp_frame_invalid"
  );
  assert.equal(socket.readyState, 3);
  assert.equal(protocolFailed, true);
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
  for (const [data, code] of [["x".repeat(2_049), "ui_config_unbounded"],
                              ['{"phase":"seed"}', "ui_config_deadline"]]) {
    const result = await invokeWithoutEof(data);
    assert.equal(result.code, 1);
    assert.deepEqual(JSON.parse(result.output), {
      v: 1, passed: false, evidence_level: "windows_release_ui_seed_readback_contract_only",
      failure_kind: code,
    });
    assert.equal(result.output.includes(data.slice(0, 20)), false);
  }
});
