import assert from "node:assert/strict";
import test from "node:test";
import worker, { SignalRoom } from "./worker.js";

const SESSION = "session0123456789abcdef";
const TOKEN = "a".repeat(43);
const OTHER = "b".repeat(43);
const body = (marker = "a") => JSON.stringify({ v: 2, ciphertext: Buffer.alloc(80, marker.charCodeAt(0)).toString("base64url") });

function room() {
  const map = new Map();
  const storage = {
    map, alarm: null,
    async get(key) { return structuredClone(map.get(key)); },
    async put(key, value) { map.set(key, structuredClone(value)); },
    async deleteAll() { map.clear(); },
    async deleteAlarm() { this.alarm = null; },
    async setAlarm(value) { this.alarm = value; },
    async transaction(callback) { return callback(this); },
  };
  let queue = Promise.resolve();
  return new SignalRoom({ storage, blockConcurrencyWhile(callback) {
    const next = queue.then(callback);
    queue = next.catch(() => {});
    return next;
  } });
}
function request(role = "offer", method = "PUT", options = {}) {
  return new Request(`https://signal.example/v2/signal/${SESSION}/${role}?role=${role}`, {
    method,
    headers: { "x-mesh-token": options.token ?? TOKEN, ...options.headers },
    body: method === "PUT" ? (options.body ?? body()) : undefined,
  });
}
const call = (target, role, method, options) => target.fetch(request(role, method, options));

test("stores only opaque envelopes and requires the pinned token", async () => {
  const target = room();
  assert.equal((await call(target, "offer", "PUT")).status, 201);
  assert.equal((await call(target, "offer", "GET", { token: OTHER })).status, 401);
  assert.equal((await call(target, "offer", "PUT", { token: OTHER })).status, 401);
  assert.equal((await call(target, "offer", "GET", { token: "" })).status, 401);
  assert.deepEqual(await (await call(target, "offer", "GET")).json(), JSON.parse(body()));
  const saved = JSON.stringify([...target.storage.map]);
  assert.ok(!saved.includes(TOKEN));
  assert.ok(!saved.includes("203.0.113"));
  assert.deepEqual([...target.storage.map.keys()], ["room", "limits"]);
});

test("plaintext and malformed/oversized envelopes leave no state", async () => {
  for (const invalid of ['{"v":1,"type":"webrtc_onboarding_offer"}', "null", "[]", '{"v":2,"ciphertext":"abc"}', body().replace('"v":2', '"v":true')]) {
    const target = room();
    assert.equal((await call(target, "offer", "PUT", { body: invalid })).status, 400);
    assert.equal(target.storage.map.size, 0);
    assert.equal(target.storage.alarm, null);
  }
  const target = room();
  assert.equal((await call(target, "offer", "PUT", { body: "x".repeat(68 * 1024 + 1) })).status, 413);
  assert.equal((await call(target, "offer", "PUT", { headers: { "content-length": String(68 * 1024 + 1) } })).status, 413);
  assert.equal(target.storage.map.size, 0);
});

test("streaming uploads are bounded without trusting Content-Length", async () => {
  const target = room();
  let cancelled = false;
  const stream = new ReadableStream({
    pull(controller) { controller.enqueue(new Uint8Array(16 * 1024)); },
    cancel() { cancelled = true; },
  });
  const input = new Request(`https://signal.example/v2/signal/${SESSION}/offer?role=offer`,
    { method: "PUT", headers: { "x-mesh-token": TOKEN }, body: stream, duplex: "half" });
  assert.equal((await target.fetch(input)).status, 413);
  assert.equal(cancelled, true);
  assert.equal(target.storage.map.size, 0);
});

test("missing-room reads and invalid tokens do not allocate stored counters", async () => {
  const target = room();
  for (let i = 0; i < 200; i++) assert.equal((await call(target, "request", "GET")).status, 404);
  assert.equal(target.storage.map.size, 0);
  assert.equal(target.storage.alarm, null);
  assert.equal((await call(target, "offer", "PUT", { token: "short" })).status, 401);
});

test("strict room budgets stay bounded under arbitrary wrong tokens", async () => {
  const target = room();
  for (let i = 0; i < 30; i++) assert.equal((await call(target, "offer", "PUT")).status, 201);
  const rejected = await call(target, "offer", "PUT");
  assert.equal(rejected.status, 429);
  assert.equal(rejected.headers.get("retry-after"), "60");
  const before = JSON.stringify([...target.storage.map]);
  for (let i = 0; i < 200; i++) await call(target, "offer", "GET", { token: "wrong".repeat(8) + i });
  assert.equal(JSON.stringify([...target.storage.map]), before);
  for (let i = 0; i < 120; i++) assert.equal((await call(target, "offer", "GET")).status, 200);
  assert.equal((await call(target, "offer", "GET")).status, 429);
});

test("concurrent first writes cannot claim the room with different tokens", async () => {
  const target = room();
  const results = await Promise.all([call(target, "offer", "PUT"), call(target, "answer", "PUT", { token: OTHER })]);
  // Hashing/upload completion may reorder simultaneous claims. Either writer
  // may win, but only that token and its document may become the room owner.
  assert.deepEqual(results.map(x => x.status).sort(), [201, 401]);
  const firstWon = results[0].status === 201;
  const role = firstWon ? "offer" : "answer";
  assert.deepEqual(Object.keys(target.storage.map.get("room").documents), [role]);
  assert.equal((await call(target, role, "GET", { token: firstWon ? TOKEN : OTHER })).status, 200);
  assert.equal((await call(target, role, "GET", { token: firstWon ? OTHER : TOKEN })).status, 401);
});

test("individual expiry is cleaned while other roles are active, reads never extend it", async () => {
  const real = Date.now;
  let now = 1_800_000_000_000;
  Date.now = () => now;
  try {
    const target = room();
    await call(target, "request", "PUT");
    const first = target.storage.alarm;
    now += 300_000;
    await call(target, "offer", "PUT");
    assert.equal(target.storage.alarm, first);
    await call(target, "request", "GET");
    assert.equal(target.storage.alarm, first);
    now = first;
    await target.alarm();
    assert.equal((await call(target, "request", "GET")).status, 404);
    assert.equal((await call(target, "offer", "GET")).status, 200);
    now += 300_000;
    await target.alarm();
    assert.equal(target.storage.map.size, 0);
    assert.equal(target.storage.alarm, null);
    assert.equal((await call(target, "offer", "GET")).status, 404);
  } finally { Date.now = real; }
});

test("expired room metadata and legacy state are completely removed", async () => {
  const target = room();
  target.storage.map.set("meta", { tokenHash: "old" });
  target.storage.map.set("limits", { ip: "old" });
  await target.alarm();
  assert.equal(target.storage.map.size, 0);
});

function env() {
  const calls = [];
  const target = room();
  return { calls, WRITES_ENABLED: "true",
    READ_LIMITER: { async limit({ key }) { calls.push(key); return { success: true }; } },
    WRITE_LIMITER: { async limit({ key }) { calls.push(key); return { success: true }; } },
    SIGNALS: { idFromName(name) { calls.push(name); return name; }, get() { return target; } },
  };
}
function edge(path, method = "GET", token = TOKEN) {
  return new Request("https://signal.example" + path, { method,
    headers: { "x-mesh-token": token, "cf-connecting-ip": "203.0.113.9" },
    body: method === "PUT" ? body() : undefined });
}

test("health, legacy rejection, methods and incident write-disable", async () => {
  const e = env();
  assert.deepEqual(await (await worker.fetch(edge("/health"), e)).json(), { protocol: 2, writes_enabled: true });
  assert.equal((await worker.fetch(edge("/signal/" + SESSION + "/offer"), e)).status, 410);
  assert.equal((await worker.fetch(edge("/v2/signal/" + SESSION + "/offer", "DELETE"), e)).status, 405);
  e.WRITES_ENABLED = "false";
  assert.equal((await worker.fetch(edge("/v2/signal/" + SESSION + "/offer", "PUT"), e)).status, 503);
  assert.equal(e.calls.length, 0);
});

test("edge rate limiting occurs across rooms before Durable Object access", async () => {
  const e = env();
  e.WRITE_LIMITER = { async limit({ key }) { e.calls.push(key); return { success: false }; } };
  for (const session of [SESSION, SESSION + "2"]) {
    const result = await worker.fetch(edge("/v2/signal/" + session + "/offer", "PUT"), e);
    assert.equal(result.status, 429);
  }
  assert.deepEqual(e.calls, ["203.0.113.9", "203.0.113.9"]);
  delete e.WRITE_LIMITER;
  assert.equal((await worker.fetch(edge("/v2/signal/" + SESSION + "/offer", "PUT"), e)).status, 503);
});

test("v2 requests are routed to a separate namespace key", async () => {
  const e = env();
  assert.equal((await worker.fetch(edge("/v2/signal/" + SESSION + "/offer", "PUT"), e)).status, 201);
  assert.ok(e.calls.includes("v2:" + SESSION));
  assert.deepEqual(await (await worker.fetch(edge("/v2/signal/" + SESSION + "/offer"), e)).json(), JSON.parse(body()));
});
