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

export const SITE_BASE_PATH = normalizeBasePath(metaContent("icrs-base-path"));
export const OFFSET_API_URL = metaContent("icrs-offset-api");
export const TURNSTILE_SITE_KEY = metaContent("icrs-turnstile-site-key");

function metaFlag(name) {
  const value = metaContent(name).toLowerCase();
  return value === "1" || value === "true" || value === "yes";
}

export const REQUIRE_DELEGATE_ID = metaFlag("icrs-require-delegate-id");

export const SKIP_TURNSTILE =
  metaFlag("icrs-skip-turnstile") ||
  /^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?\//i.test(OFFSET_API_URL);

function apiBaseUrl(apiUrl) {
  if (!apiUrl) return "";
  return apiUrl.replace(/\/[^/]+\/?$/, "");
}

export const CONTACT_API_URL =
  metaContent("icrs-contact-api") ||
  (OFFSET_API_URL ? `${apiBaseUrl(OFFSET_API_URL)}/contact` : "");

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
