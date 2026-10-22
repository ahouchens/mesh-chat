const MAX_DOCUMENT_BYTES = 48 * 1024;
const TTL_SECONDS = 600;
const SESSION = /^[A-Za-z0-9_-]{16,80}$/;
const TOKEN = /^[A-Za-z0-9_-]{16,160}$/;
const ROLES = new Set(["request", "offer", "answer"]);
const ROLE_TYPES = {
  request: new Set(["webrtc_reconnect_request"]),
  offer: new Set(["webrtc_onboarding_offer", "webrtc_reconnect_offer"]),
  answer: new Set(["webrtc_onboarding_answer", "webrtc_reconnect_answer"]),
};
const RECONNECT_TYPES = new Set([
  "webrtc_reconnect_request",
  "webrtc_reconnect_offer",
  "webrtc_reconnect_answer",
]);

// Per-token and per-IP sliding-window budgets. They are deliberately generous
// for a two-person rendezvous and tight enough that a leaked capability cannot
// be used to flood a room or enumerate guesses.
const WRITE_LIMIT_TOKEN = 30;
const WRITE_LIMIT_IP = 120;
const READ_LIMIT_TOKEN = 120;
const READ_LIMIT_IP = 480;
const LIMIT_WINDOW_MS = 60 * 1000;

const encoder = new TextEncoder();

function cors(body, status = 200) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "GET, PUT, OPTIONS",
      "access-control-allow-headers": "content-type, x-mesh-token",
      "access-control-expose-headers": "retry-after",
    },
  });
}

async function tokenHash(token) {
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(token));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/**
 * One Durable Object per signaling session. It holds at most a request, an
 * offer, and an answer for ten minutes and deletes itself via a storage alarm.
 *
 * Sessions created by tokenless onboarding are legacy-compatible. Reconnect
 * documents always require a capability token; the first authenticated write
 * pins the SHA-256 token hash for the room, and every later read or write must
 * present the same token. A token rotation is accepted only from the current
 * token holder.
 */
export class SignalRoom {
  constructor(state) {
    this.storage = state.storage;
  }

  async fetch(request) {
    const url = new URL(request.url);
    const role = url.searchParams.get("role");
    if (!ROLES.has(role)) return cors({ error: "invalid_role" }, 400);

    const token = request.headers.get("x-mesh-token");
    if (token !== null && !TOKEN.test(token)) return cors({ error: "invalid_token" }, 401);
    const rotation = request.headers.get("x-mesh-token-new");
    if (rotation !== null && !TOKEN.test(rotation)) return cors({ error: "invalid_token" }, 401);
    if (rotation !== null && request.method !== "PUT") return cors({ error: "invalid_rotation" }, 400);
    const ip = request.headers.get("cf-connecting-ip") || "unknown";

    if (request.method === "GET") {
      if (!(await this.withinLimit("read", token, ip, READ_LIMIT_TOKEN, READ_LIMIT_IP))) {
        return cors({ error: "rate_limited" }, 429);
      }
      return this.read(role, token);
    }

    if (request.method === "PUT") {
      if (!(await this.withinLimit("write", token, ip, WRITE_LIMIT_TOKEN, WRITE_LIMIT_IP))) {
        return cors({ error: "rate_limited" }, 429);
      }
      return this.write(role, token, rotation, request);
    }

    return cors({ error: "method_not_allowed" }, 405);
  }

  async read(role, token) {
    const meta = await this.storage.get("meta");
    if (!meta || meta.expiresAt <= Date.now()) return cors({ error: "not_found" }, 404);
    if (meta.tokenHash !== null) {
      if (token === null || (await tokenHash(token)) !== meta.tokenHash) {
        return cors({ error: "token_required" }, 401);
      }
    }
    const value = await this.storage.get(role);
    if (!value || value.expiresAt <= Date.now()) return cors({ error: "not_found" }, 404);
    // A reconnect room must never have been created without a token. This is
    // defence in depth: PUT already refuses that combination.
    if (meta.tokenHash === null && RECONNECT_TYPES.has(value.type)) {
      return cors({ error: "token_required" }, 401);
    }
    return cors({ document: value.document, type: value.type, expires_in: Math.ceil((value.expiresAt - Date.now()) / 1000) });
  }

  async write(role, token, rotation, request) {
    const document = await request.text();
    if (!document || encoder.encode(document).length > MAX_DOCUMENT_BYTES) {
      return cors({ error: "document_too_large" }, 413);
    }
    let parsed;
    try {
      parsed = JSON.parse(document);
    } catch {
      return cors({ error: "document_invalid" }, 400);
    }
    if (!parsed || typeof parsed !== "object") return cors({ error: "document_invalid" }, 400);
    if (!ROLE_TYPES[role].has(parsed.type)) return cors({ error: "document_invalid" }, 400);
    const reconnect = RECONNECT_TYPES.has(parsed.type);
    if (reconnect && token === null) return cors({ error: "token_required" }, 401);

    const now = Date.now();
    let meta = await this.storage.get("meta");
    if (!meta || meta.expiresAt <= now) {
      meta = { tokenHash: null, expiresAt: 0 };
    }
    const provided = token === null ? null : await tokenHash(token);
    if (meta.tokenHash !== null) {
      if (provided === null || provided !== meta.tokenHash) {
        return cors({ error: "token_mismatch" }, 401);
      }
    } else if (token !== null) {
      // First authenticated write pins the room capability.
      meta.tokenHash = provided;
    } else if (reconnect) {
      return cors({ error: "token_required" }, 401);
    }

    let rotated = false;
    if (rotation !== null) {
      if (meta.tokenHash === null || provided !== meta.tokenHash) {
        return cors({ error: "token_mismatch" }, 401);
      }
      meta.tokenHash = await tokenHash(rotation);
      rotated = true;
    }

    const expiresAt = now + TTL_SECONDS * 1000;
    meta.expiresAt = expiresAt;
    await this.storage.put("meta", meta);
    await this.storage.put(role, { document, type: parsed.type, expiresAt });
    await this.storage.setAlarm(expiresAt);
    return cors({ expires_in: TTL_SECONDS, role, rotated }, 201);
  }

  /**
   * Count one operation against a per-token bucket and the per-IP bucket. The
   * token budget is checked first so a shared public IP cannot mask abuse.
   */
  async withinLimit(scope, token, ip, tokenLimit, ipLimit) {
    const now = Date.now();
    const counters = (await this.storage.get("limits")) ?? {};
    for (const key of Object.keys(counters)) {
      if (now - counters[key].start >= LIMIT_WINDOW_MS) delete counters[key];
    }
    const tokenKey = `${scope}:token:${token === null ? "anon" : await tokenHash(token)}`;
    const ipKey = `${scope}:ip:${ip}`;
    const tokenCounter = this.counter(counters, tokenKey, now);
    const address = this.counter(counters, ipKey, now);
    const allowed = tokenCounter.count < tokenLimit && address.count < ipLimit;
    if (allowed) {
      tokenCounter.count += 1;
      address.count += 1;
    }
    counters[tokenKey] = tokenCounter;
    counters[ipKey] = address;
    await this.storage.put("limits", counters);
    return allowed;
  }

  counter(counters, key, now) {
    const value = counters[key];
    if (!value || now - value.start >= LIMIT_WINDOW_MS) return { start: now, count: 0 };
    return { start: value.start, count: value.count };
  }

  async alarm() {
    const now = Date.now();
    const meta = await this.storage.get("meta");
    if (!meta || meta.expiresAt <= now) {
      for (const role of ROLES) await this.storage.delete(role);
      await this.storage.delete("meta");
      await this.storage.delete("limits");
      return;
    }
    for (const role of ROLES) {
      const value = await this.storage.get(role);
      if (!value || value.expiresAt <= now) await this.storage.delete(role);
    }
    await this.storage.setAlarm(meta.expiresAt);
  }
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return cors(undefined, 204);
    const url = new URL(request.url);
    const parts = url.pathname.split("/").filter(Boolean);
    if (parts.length !== 3 || parts[0] !== "signal") return cors({ error: "not_found" }, 404);
    const [, session, role] = parts;
    if (!SESSION.test(session) || !ROLES.has(role)) return cors({ error: "invalid_session" }, 400);
    const id = env.SIGNALS.idFromName(session);
    const stub = env.SIGNALS.get(id);
    const forwarded = new URL(request.url);
    forwarded.searchParams.set("role", role);
    return stub.fetch(new Request(forwarded.toString(), request));
  },
};
