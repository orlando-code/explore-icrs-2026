/** Runtime config for the static site (set via meta tags in index.html). */

function metaContent(name) {
  return document.querySelector(`meta[name="${name}"]`)?.content?.trim() || "";
}

function normalizeBasePath(value) {
  const trimmed = String(value || "").trim();
  if (!trimmed) return "";
  let base = trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
  if (!base.endsWith("/")) base += "/";
  return base;
}

function resolveApiUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  if (/^https?:\/\//i.test(raw)) return raw;
  if (typeof location === "undefined") return raw;
  try {
    return new URL(raw, location.origin).href;
  } catch {
    return raw;
  }
}

export const SITE_BASE_PATH = normalizeBasePath(metaContent("icrs-base-path"));
export const TURNSTILE_SITE_KEY = metaContent("icrs-turnstile-site-key");

function metaFlag(name) {
  const value = metaContent(name).toLowerCase();
  return value === "1" || value === "true" || value === "yes";
}

export const REQUIRE_DELEGATE_ID = metaFlag("icrs-require-delegate-id");

export const OFFSET_COUNTRY_CHOROPLETH = metaContent("icrs-offset-country-choropleth")
  ? metaFlag("icrs-offset-country-choropleth")
  : true;

export const OFFSET_AFFILIATION_SLICES = metaContent("icrs-offset-affiliation-slices")
  ? metaFlag("icrs-offset-affiliation-slices")
  : true;

function apiBaseUrl(apiUrl) {
  if (!apiUrl) return "";
  return apiUrl.replace(/\/[^/]+\/?$/, "");
}

/** Prefer canonical/meta base path; fall back to the directory of this page. */
export function effectiveSiteBasePath() {
  if (SITE_BASE_PATH) return SITE_BASE_PATH;
  const canonical = metaContent("icrs-canonical-url");
  if (canonical) {
    try {
      const path = new URL(canonical).pathname;
      if (path && path !== "/") return path.endsWith("/") ? path : `${path}/`;
    } catch {
      /* ignore */
    }
  }
  if (typeof location === "undefined") return "";
  const path = location.pathname || "/";
  if (path.endsWith("/")) return path;
  return `${path.replace(/\/[^/]*$/, "")}/`;
}

/**
 * Same-origin Worker proxy path (see cloudflare/). Used first so mobile browsers
 * that block cross-origin calls to *.fly.dev still reach the API.
 */
export function sameOriginApiUrl(endpoint) {
  if (typeof location === "undefined" || !/^https?:$/i.test(location.protocol)) {
    return "";
  }
  const base = effectiveSiteBasePath();
  if (!base) return "";
  return `${location.origin}${base}api/${String(endpoint || "").replace(/^\/+/, "")}`;
}

export const OFFSET_API_URL = resolveApiUrl(metaContent("icrs-offset-api"));

export const SKIP_TURNSTILE =
  metaFlag("icrs-skip-turnstile") ||
  /^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?\//i.test(OFFSET_API_URL);

export const CONTACT_API_URL = resolveApiUrl(
  metaContent("icrs-contact-api") ||
    (OFFSET_API_URL ? `${apiBaseUrl(OFFSET_API_URL)}/contact` : "")
);

function uniqueUrls(urls) {
  const seen = new Set();
  const out = [];
  for (const url of urls) {
    const value = String(url || "").trim();
    if (!value || seen.has(value)) continue;
    seen.add(value);
    out.push(value);
  }
  return out;
}

const FLY_CONTACT_API = "https://icrs-offset-api.fly.dev/api/contact";
const FLY_OFFSET_API = "https://icrs-offset-api.fly.dev/api/offsets";
/** Cloudflare Worker proxy (cross-origin, but often allowed when *.fly.dev is not). */
const WORKER_API_ORIGIN = "https://icrs-api-proxy.orlando-code.workers.dev";

function workerApiUrl(endpoint) {
  return `${WORKER_API_ORIGIN}/explore-icrs-2026/api/${String(endpoint || "").replace(/^\/+/, "")}`;
}

export function contactApiUrlCandidates() {
  return uniqueUrls([
    sameOriginApiUrl("contact"),
    workerApiUrl("contact"),
    CONTACT_API_URL,
    FLY_CONTACT_API,
  ]);
}

export function offsetApiUrlCandidates(configured = OFFSET_API_URL) {
  return uniqueUrls([
    sameOriginApiUrl("offsets"),
    workerApiUrl("offsets"),
    resolveApiUrl(configured),
    FLY_OFFSET_API,
  ]);
}

/** Try each candidate until one returns JSON (skips GitHub Pages HTML 404s). */
export async function fetchApiJson(candidates, options = {}) {
  const urls = Array.isArray(candidates) ? candidates : [candidates];
  let lastError = null;
  for (const url of urls) {
    if (!url) continue;
    try {
      const response = await fetch(url, options);
      const contentType = response.headers.get("content-type") || "";
      if (!contentType.includes("application/json")) {
        lastError = new Error(`Non-JSON response from ${url}`);
        continue;
      }
      const payload = await response.json().catch(() => ({}));
      return { response, payload, url };
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error("API unreachable");
}

export function canonicalSiteUrl() {
  const configured = metaContent("icrs-canonical-url");
  if (configured) {
    return configured.endsWith("/") ? configured : `${configured}/`;
  }
  if (SITE_BASE_PATH) {
    return `${location.origin}${SITE_BASE_PATH}`;
  }
  const path = location.pathname.endsWith("/") ? location.pathname : `${location.pathname}/`;
  return `${location.origin}${path}`;
}
