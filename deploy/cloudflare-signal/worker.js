const MAX_DOCUMENT_BYTES = 48 * 1024;
const TTL_SECONDS = 600;
const SESSION = /^[A-Za-z0-9_-]{16,80}$/;
const ROLES = new Set(["offer", "answer"]);

function cors(body, status = 200) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "GET, PUT, OPTIONS",
      "access-control-allow-headers": "content-type",
    },
  });
}

/**
 * One Durable Object per signaling session. It holds at most an offer and an
 * answer for ten minutes and deletes itself via a storage alarm.
 */
export class SignalRoom {
  constructor(state) {
    this.storage = state.storage;
  }

  async fetch(request) {
    const url = new URL(request.url);
    const role = url.searchParams.get("role");
    if (!ROLES.has(role)) return cors({ error: "invalid_role" }, 400);

    if (request.method === "GET") {
      const value = await this.storage.get(role);
      if (!value || value.expiresAt <= Date.now()) return cors({ error: "not_found" }, 404);
      return cors({ document: value.document });
    }

    if (request.method === "PUT") {
      const document = await request.text();
      if (!document || new TextEncoder().encode(document).length > MAX_DOCUMENT_BYTES) {
        return cors({ error: "document_too_large" }, 413);
      }
      try {
        const parsed = JSON.parse(document);
        if (!parsed || typeof parsed !== "object") return cors({ error: "document_invalid" }, 400);
        if (parsed.type !== "webrtc_onboarding_offer" && parsed.type !== "webrtc_onboarding_answer") {
          return cors({ error: "document_invalid" }, 400);
        }
      } catch {
        return cors({ error: "document_invalid" }, 400);
      }
      const expiresAt = Date.now() + TTL_SECONDS * 1000;
      await this.storage.put(role, { document, expiresAt });
      await this.storage.setAlarm(expiresAt);
      return cors({ expires_in: TTL_SECONDS }, 201);
    }

    return cors({ error: "method_not_allowed" }, 405);
  }

  async alarm() {
    const now = Date.now();
    const entries = await this.storage.list();
    for (const [key, value] of entries) {
      if (!value || value.expiresAt <= now) await this.storage.delete(key);
    }
    if ((await this.storage.list()).size > 0) {
      await this.storage.setAlarm(now + TTL_SECONDS * 1000);
    }
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
