/**
 * Same-origin reverse proxy for the ICRS offset/contact API.
 *
 * Browsers (especially Chrome on iOS) often fail cross-origin fetch() to
 * *.fly.dev after Turnstile. Routing /explore-icrs-2026/api/* through this
 * Worker keeps the request first-party on orlando-codes.com.
 *
 * Deploy: npx wrangler deploy --config cloudflare/wrangler.toml
 */

const DEFAULT_UPSTREAM = "https://icrs-offset-api.fly.dev";
const PATH_RE = /^\/explore-icrs-2026\/api\/(contact|offsets)\/?$/;

function corsHeaders(request) {
  const origin = request.headers.get("Origin") || "";
  const headers = {
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "X-Content-Type-Options": "nosniff",
  };
  if (origin) {
    headers["Access-Control-Allow-Origin"] = origin;
    headers.Vary = "Origin";
  }
  return headers;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const match = url.pathname.match(PATH_RE);
    if (!match) {
      return new Response("Not found", { status: 404, headers: corsHeaders(request) });
    }

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(request) });
    }

    if (request.method !== "GET" && request.method !== "POST") {
      return new Response(JSON.stringify({ error: "Method not allowed." }), {
        status: 405,
        headers: { "Content-Type": "application/json; charset=utf-8", ...corsHeaders(request) },
      });
    }

    const upstreamBase = String(env.UPSTREAM_ORIGIN || DEFAULT_UPSTREAM).replace(/\/$/, "");
    const upstreamUrl = `${upstreamBase}/api/${match[1]}${url.search}`;

    const headers = new Headers(request.headers);
    headers.delete("host");
    headers.delete("cf-connecting-ip");
    headers.delete("cf-ipcountry");
    headers.delete("cf-ray");
    headers.delete("cf-visitor");
    headers.delete("content-length");

    const init = {
      method: request.method,
      headers,
      redirect: "manual",
    };
    if (request.method === "POST") {
      init.body = request.body;
    }

    let upstream;
    try {
      upstream = await fetch(upstreamUrl, init);
    } catch {
      return new Response(JSON.stringify({ error: "Upstream email service unreachable." }), {
        status: 502,
        headers: { "Content-Type": "application/json; charset=utf-8", ...corsHeaders(request) },
      });
    }

    const responseHeaders = new Headers(upstream.headers);
    const localCors = corsHeaders(request);
    for (const [key, value] of Object.entries(localCors)) {
      responseHeaders.set(key, value);
    }

    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    });
  },
};
