const CLOUDFLARE_TURN_API = "https://rtc.live.cloudflare.com/v1/turn/keys";
const MAX_TTL_SECONDS = 3600;
const MIN_TTL_SECONDS = 300;

function json(body, status = 200, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "GET, POST, OPTIONS",
      "access-control-allow-headers": "content-type",
      ...headers,
    },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "GET, POST, OPTIONS",
          "access-control-allow-headers": "content-type",
        },
      });
    }
    if (url.pathname !== "/credentials") return json({ error: "not_found" }, 404);
    if (request.method !== "GET" && request.method !== "POST") {
      return json({ error: "method_not_allowed" }, 405);
    }
    if (!env.TURN_KEY_ID || !env.TURN_KEY_API_TOKEN) {
      return json({ error: "broker_not_configured" }, 500);
    }

    const requested = Number(url.searchParams.get("ttl") ?? "3600");
    const ttl = Number.isFinite(requested)
      ? Math.min(MAX_TTL_SECONDS, Math.max(MIN_TTL_SECONDS, Math.floor(requested)))
      : 3600;

    let upstream;
    try {
      upstream = await fetch(
        `${CLOUDFLARE_TURN_API}/${encodeURIComponent(env.TURN_KEY_ID)}/credentials/generate-ice-servers`,
        {
          method: "POST",
          headers: {
            authorization: `Bearer ${env.TURN_KEY_API_TOKEN}`,
            "content-type": "application/json",
          },
          body: JSON.stringify({ ttl }),
        },
      );
    } catch {
      return json({ error: "turn_upstream_unavailable" }, 502);
    }

    if (!upstream.ok) {
      // Do not relay Cloudflare's error body: it can contain account/key data.
      // The status alone distinguishes bad credentials (401/403) from a bad
      // request (400) without exposing secrets.
      return json({ error: "turn_upstream_rejected", upstream_status: upstream.status }, 502);
    }

    let payload;
    try {
      payload = await upstream.json();
    } catch {
      return json({ error: "turn_upstream_invalid" }, 502);
    }
    if (!payload || !Array.isArray(payload.iceServers)) {
      return json({ error: "turn_upstream_invalid" }, 502);
    }
    return json({ iceServers: payload.iceServers });
  },
};
