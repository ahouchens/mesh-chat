const MAX_DOCUMENT_BYTES = 48 * 1024;
const TTL_SECONDS = 600;
const SESSION = /^[A-Za-z0-9_-]{16,80}$/;
const ROLES = new Set(["offer", "answer"]);

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
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

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "GET, PUT, OPTIONS",
          "access-control-allow-headers": "content-type",
        },
      });
    }
    if (!env.SIGNALS) return json({ error: "mailbox_not_configured" }, 500);
    const url = new URL(request.url);
    const parts = url.pathname.split("/").filter(Boolean);
    if (parts.length !== 3 || parts[0] !== "signal") return json({ error: "not_found" }, 404);
    const [, session, role] = parts;
    if (!SESSION.test(session) || !ROLES.has(role)) return json({ error: "invalid_session" }, 400);
    const key = `signal:${session}:${role}`;

    if (request.method === "GET") {
      const document = await env.SIGNALS.get(key, "text");
      if (document === null) return json({ error: "not_found" }, 404);
      return json({ session, role, document });
    }
    if (request.method === "PUT") {
      const document = await request.text();
      if (!document || new TextEncoder().encode(document).length > MAX_DOCUMENT_BYTES) {
        return json({ error: "document_too_large" }, 413);
      }
      try {
        const parsed = JSON.parse(document);
        if (!parsed || typeof parsed !== "object" || parsed.session_id !== session) {
          return json({ error: "document_session_mismatch" }, 400);
        }
      } catch {
        return json({ error: "document_invalid" }, 400);
      }
      await env.SIGNALS.put(key, document, { expirationTtl: TTL_SECONDS });
      return json({ session, role, expires_in: TTL_SECONDS }, 201);
    }
    return json({ error: "method_not_allowed" }, 405);
  },
};
