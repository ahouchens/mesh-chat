import assert from "node:assert/strict";
import test from "node:test";

import { SignalRoom } from "./worker.js";

const SESSION = "session0123456789abcdef";
const TOKEN = "token-0123456789abcdefghijklmnop";
const OTHER_TOKEN = "other-0123456789abcdefghijklmnop";
const IP = "203.0.113.7";

function storage() {
  const map = new Map();
  return {
    map,
    alarm: 0,
    async get(key) {
      return map.get(key);
    },
    async put(key, value) {
      map.set(key, value);
    },
    async delete(key) {
      map.delete(key);
    },
    async setAlarm(value) {
      this.alarm = value;
    },
  };
}

function document(type, extra = {}) {
  return JSON.stringify({
    v: 1,
    type,
    session_id: "0123456789abcdef01234567",
    ...extra,
  });
}

async function call(room, role, method, options = {}) {
  const headers = new Headers();
  if (options.token !== undefined) headers.set("x-mesh-token", options.token);
  if (options.rotation !== undefined) headers.set("x-mesh-token-new", options.rotation);
  headers.set("cf-connecting-ip", options.ip ?? IP);
  const request = new Request(
    `https://signal.example.workers.dev/signal/${SESSION}/${role}?role=${role}`,
    { method, headers, body: options.body },
  );
  const response = await room.fetch(request);
  const text = await response.text();
  return { status: response.status, body: text ? JSON.parse(text) : null };
}

function room() {
  return new SignalRoom({ storage: storage() });
}

test("tokenless onboarding sessions remain readable and writable", async () => {
  const signal = room();
  const offer = document("webrtc_onboarding_offer");
  const put = await call(signal, "offer", "PUT", { body: offer });
  assert.equal(put.status, 201);
  assert.equal(put.body.rotated, false);

  const get = await call(signal, "offer", "GET");
  assert.equal(get.status, 200);
  assert.equal(get.body.document, offer);
});

test("reconnect documents require a capability token", async () => {
  const signal = room();
  const body = document("webrtc_reconnect_request");
  const missing = await call(signal, "request", "PUT", { body });
  assert.equal(missing.status, 401);
  assert.equal(missing.body.error, "token_required");

  const accepted = await call(signal, "request", "PUT", { token: TOKEN, body });
  assert.equal(accepted.status, 201);

  const unauthenticatedRead = await call(signal, "request", "GET");
  assert.equal(unauthenticatedRead.status, 401);
  assert.equal(unauthenticatedRead.body.error, "token_required");

  const wrong = await call(signal, "request", "GET", { token: OTHER_TOKEN });
  assert.equal(wrong.status, 401);
  assert.equal(wrong.body.error, "token_required");

  const correct = await call(signal, "request", "GET", { token: TOKEN });
  assert.equal(correct.status, 200);
  assert.equal(correct.body.document, body);
});

test("the first token pins the room, and later mismatches are rejected", async () => {
  const signal = room();
  const first = await call(signal, "offer", "PUT", {
    token: TOKEN,
    body: document("webrtc_reconnect_offer"),
  });
  assert.equal(first.status, 201);

  const wrongWrite = await call(signal, "offer", "PUT", {
    token: OTHER_TOKEN,
    body: document("webrtc_reconnect_offer"),
  });
  assert.equal(wrongWrite.status, 401);
  assert.equal(wrongWrite.body.error, "token_mismatch");

  const tokenless = await call(signal, "offer", "PUT", {
    body: document("webrtc_onboarding_offer"),
  });
  assert.equal(tokenless.status, 401);
});

test("token rotation requires the current token and revokes the old one", async () => {
  const signal = room();
  await call(signal, "answer", "PUT", {
    token: TOKEN,
    body: document("webrtc_reconnect_answer"),
  });

  const rejected = await call(signal, "answer", "PUT", {
    token: OTHER_TOKEN,
    rotation: "rotated-0123456789abcdefghijkl",
    body: document("webrtc_reconnect_answer"),
  });
  assert.equal(rejected.status, 401);

  const rotated = await call(signal, "answer", "PUT", {
    token: TOKEN,
    rotation: "rotated-0123456789abcdefghijkl",
    body: document("webrtc_reconnect_answer"),
  });
  assert.equal(rotated.status, 201);
  assert.equal(rotated.body.rotated, true);

  const oldToken = await call(signal, "answer", "GET", { token: TOKEN });
  assert.equal(oldToken.status, 401);
  const newToken = await call(signal, "answer", "GET", { token: "rotated-0123456789abcdefghijkl" });
  assert.equal(newToken.status, 200);
});

test("roles only accept their own document types", async () => {
  const signal = room();
  const wrongRole = await call(signal, "request", "PUT", {
    token: TOKEN,
    body: document("webrtc_reconnect_offer"),
  });
  assert.equal(wrongRole.status, 400);
  assert.equal(wrongRole.body.error, "document_invalid");

  const wrongType = await call(signal, "answer", "PUT", {
    token: TOKEN,
    body: document("webrtc_reconnect_request"),
  });
  assert.equal(wrongType.status, 400);

  const onboardingOfferInAnswer = await call(signal, "answer", "PUT", {
    body: document("webrtc_onboarding_offer"),
  });
  assert.equal(onboardingOfferInAnswer.status, 400);
});

test("documents are size limited and must parse", async () => {
  const signal = room();
  const broken = await call(signal, "offer", "PUT", { body: "{" });
  assert.equal(broken.status, 400);
  const oversized = await call(signal, "offer", "PUT", {
    body: JSON.stringify({ type: "webrtc_onboarding_offer", pad: "a".repeat(49 * 1024) }),
  });
  assert.equal(oversized.status, 413);
});

test("per-token writes are rate limited", async () => {
  const signal = room();
  let limited = 0;
  let accepted = 0;
  for (let index = 0; index < 40; index += 1) {
    const result = await call(signal, "offer", "PUT", {
      token: TOKEN,
      body: document("webrtc_reconnect_offer", { nonce: String(index) }),
      ip: `198.51.100.${index}`,
    });
    if (result.status === 429) limited += 1;
    if (result.status === 201) accepted += 1;
  }
  assert.equal(accepted, 30);
  assert.equal(limited, 10);
});

test("per-IP writes are limited across tokens", async () => {
  const signal = room();
  let limited = 0;
  for (let index = 0; index < 130; index += 1) {
    const result = await call(signal, "offer", "PUT", {
      token: `${String(index).padStart(3, "0")}-0123456789abcdefghijklmnop`,
      body: document("webrtc_reconnect_offer", { nonce: String(index) }),
    });
    if (result.status === 429) limited += 1;
  }
  assert.equal(limited, 10);
});

test("a capability is not an oracle: wrong tokens cannot read documents", async () => {
  const signal = room();
  await call(signal, "answer", "PUT", {
    token: TOKEN,
    body: document("webrtc_reconnect_answer"),
  });
  const guesses = [
    "a".repeat(32),
    "b".repeat(32),
    OTHER_TOKEN,
  ];
  for (const guess of guesses) {
    const result = await call(signal, "answer", "GET", { token: guess });
    assert.equal(result.status, 401);
    assert.equal(result.body.document, undefined);
  }
});

test("expired sessions and alarms purge documents", async () => {
  const state = { storage: storage() };
  const signal = new SignalRoom(state);
  await call(signal, "offer", "PUT", { token: TOKEN, body: document("webrtc_reconnect_offer") });

  const offer = state.storage.map.get("offer");
  offer.expiresAt = Date.now() - 1;
  state.storage.map.set("offer", offer);
  const expired = await call(signal, "offer", "GET", { token: TOKEN });
  assert.equal(expired.status, 404);
});

test("the public entrypoint validates sessions and roles", async () => {
  const env = {
    SIGNALS: {
      idFromName: (name) => name,
      get: () => ({ fetch: async () => new Response(JSON.stringify({ ok: true })) }),
    },
  };
  const worker = (await import("./worker.js")).default;
  const missing = await worker.fetch(
    new Request("https://signal.example.workers.dev/nope"),
    env,
  );
  assert.equal(missing.status, 404);

  const invalidSession = await worker.fetch(
    new Request("https://signal.example.workers.dev/signal/short/offer"),
    env,
  );
  assert.equal(invalidSession.status, 400);

  const options = await worker.fetch(
    new Request("https://signal.example.workers.dev/signal/" + SESSION + "/offer", {
      method: "OPTIONS",
    }),
    env,
  );
  assert.equal(options.status, 204);
  assert.match(options.headers.get("access-control-allow-headers") ?? "", /x-mesh-token/);
});
