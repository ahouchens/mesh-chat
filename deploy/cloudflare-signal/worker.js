const MAX_ENVELOPE_BYTES = 68 * 1024;
const TTL_MS = 600_000;
const WINDOW_MS = 60_000;
const SESSION = /^[A-Za-z0-9_-]{16,80}$/;
const TOKEN = /^[A-Za-z0-9_-]{32,160}$/;
const ROLES = new Set(["request", "offer", "answer"]);
const encoder = new TextEncoder();

function response(body, status = 200, extra = {}) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "GET, PUT, OPTIONS",
      "access-control-allow-headers": "content-type, x-mesh-token",
      "access-control-expose-headers": "retry-after",
      ...extra,
    },
  });
}

function limited() {
  return response({ error: "rate_limited" }, 429, { "retry-after": "60" });
}

async function hash(value) {
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function envelope(request) {
  const length = request.headers.get("content-length");
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > MAX_ENVELOPE_BYTES)) {
    return response({ error: "document_too_large" }, 413);
  }
  if (!request.body) return response({ error: "document_invalid" }, 400);
  const reader = request.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_ENVELOPE_BYTES) {
        await reader.cancel();
        return response({ error: "document_too_large" }, 413);
      }
      chunks.push(value);
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    const parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
    if (!parsed || Array.isArray(parsed) || parsed.v !== 2 ||
        Object.keys(parsed).sort().join(",") !== "ciphertext,v" ||
        typeof parsed.ciphertext !== "string" || !/^[A-Za-z0-9_-]+$/.test(parsed.ciphertext)) {
      return response({ error: "document_invalid" }, 400);
    }
    const encoded = parsed.ciphertext.replace(/-/g, "+").replace(/_/g, "/");
    const binary = atob(encoded);
    if (binary.length < 64 || binary.length % 16 !== 0 ||
        btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "") !== parsed.ciphertext) {
      return response({ error: "document_invalid" }, 400);
    }
    return parsed;
  } catch {
    return response({ error: "document_invalid" }, 400);
  } finally {
    reader.releaseLock();
  }
}

/** Bounded ciphertext and fixed counters. No plaintext, IPs, or per-guessed-token state. */
export class SignalRoom {
  constructor(state) {
    this.state = state;
    this.storage = state.storage;
  }

  async fetch(request) {
    const role = new URL(request.url).searchParams.get("role");
    if (!ROLES.has(role)) return response({ error: "invalid_role" }, 400);
    if (!["GET", "PUT"].includes(request.method)) return response({ error: "method_not_allowed" }, 405);
    const token = request.headers.get("x-mesh-token");
    if (!token || !TOKEN.test(token)) return response({ error: "token_required" }, 401);
    const document = request.method === "PUT" ? await envelope(request) : null;
    if (document instanceof Response) return document;
    const tokenHash = await hash(token);
    // Serialize authorization, counters and mutation, including across awaits.
    return this.state.blockConcurrencyWhile(async () => {
      const now = Date.now();
      let room = await this.storage.get("room");
      let pruned = false;
      if (room) {
        for (const key of Object.keys(room.documents)) {
          if (room.documents[key].expiresAt <= now) { delete room.documents[key]; pruned = true; }
        }
        if (!Object.keys(room.documents).length) {
          await this.clear();
          room = null;
        }
      }
      if (room && room.tokenHash !== tokenHash) return response({ error: "token_required" }, 401);
      if (!room && request.method === "GET") return response({ error: "not_found" }, 404);
      room ??= { tokenHash, documents: {} };
      const limits = (await this.storage.get("limits")) ?? { read: { start: now, count: 0 }, write: { start: now, count: 0 } };
      const scope = request.method === "PUT" ? "write" : "read";
      const budget = scope === "write" ? 30 : 120;
      if (now - limits[scope].start >= WINDOW_MS) limits[scope] = { start: now, count: 0 };
      if (limits[scope].count >= budget) return limited();
      limits[scope].count += 1;
      if (document) room.documents[role] = { document, expiresAt: now + TTL_MS };
      // Polls update only two fixed-size counters, never rewrite ciphertext.
      await this.storage.transaction(async (txn) => {
        if (document || pruned) {
          await txn.put("room", room);
          await txn.setAlarm(Math.min(...Object.values(room.documents).map(value => value.expiresAt)));
        }
        await txn.put("limits", limits);
      });
      if (document) return response({ expires_in: 600, role }, 201);
      const value = room.documents[role];
      return value ? response(value.document) : response({ error: "not_found" }, 404);
    });
  }

  async schedule(room) {
    await this.storage.setAlarm(Math.min(...Object.values(room.documents).map((value) => value.expiresAt)));
  }

  async clear() {
    await this.storage.deleteAll();
    await this.storage.deleteAlarm();
  }

  async alarm() {
    return this.state.blockConcurrencyWhile(async () => {
      const room = await this.storage.get("room");
      // Also purges any legacy v1 state left in this namespace after upgrade.
      if (!room) { await this.clear(); return; }
      const now = Date.now();
      for (const role of Object.keys(room.documents)) {
        if (room.documents[role].expiresAt <= now) delete room.documents[role];
      }
      if (!Object.keys(room.documents).length) { await this.clear(); return; }
      await this.storage.put("room", room);
      await this.schedule(room);
    });
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/health" && request.method === "GET") {
      return response({ protocol: 2, writes_enabled: env.WRITES_ENABLED !== "false" });
    }
    if (request.method === "OPTIONS") return response(undefined, 204);
    const parts = url.pathname.split("/").filter(Boolean);
    if (parts[0] === "signal") return response({ error: "encrypted_protocol_required" }, 410);
    if (parts.length !== 4 || parts[0] !== "v2" || parts[1] !== "signal") return response({ error: "not_found" }, 404);
    const [, , session, role] = parts;
    if (url.search || !SESSION.test(session) || !ROLES.has(role)) return response({ error: "invalid_session" }, 400);
    if (!["GET", "PUT"].includes(request.method)) return response({ error: "method_not_allowed" }, 405);
    const token = request.headers.get("x-mesh-token");
    if (!token || !TOKEN.test(token)) return response({ error: "token_required" }, 401);
    if (request.method === "PUT" && env.WRITES_ENABLED === "false") return response({ error: "writes_disabled" }, 503, { "retry-after": "60" });
    const limiter = request.method === "PUT" ? env.WRITE_LIMITER : env.READ_LIMITER;
    // Missing deployment protection fails closed, never silently unlimits traffic.
    if (!limiter) return response({ error: "service_unavailable" }, 503);
    const ip = request.headers.get("cf-connecting-ip") || "unknown";
    if (!(await limiter.limit({ key: ip })).success) return limited();
    const stub = env.SIGNALS.get(env.SIGNALS.idFromName("v2:" + session));
    const forwarded = new URL(request.url);
    forwarded.searchParams.set("role", role);
    return stub.fetch(new Request(forwarded.toString(), request));
  },
};
