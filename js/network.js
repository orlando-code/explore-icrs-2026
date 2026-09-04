import {
  escapeHtml,
  buildTalkTitleIndex,
  renderTalkTitlesHtml,
  findLocationIdByAffiliation,
  dedupeSearchHitsByPerson,
  isRegistryPersonKey,
  resolveCanonicalPersonName,
  resolveDelegatePersonKey,
  normalizePersonName,
  setTalkFormatElement,
  foldSearchText,
} from "./utils.js";
import { createTalkSimilarityLookup, resolveTalkId } from "./talk-similarity.js";
import {
  CONTACT_API_URL,
  SKIP_TURNSTILE,
  TURNSTILE_SITE_KEY,
  contactApiUrlCandidates,
  fetchApiJson,
} from "./config.js";

const DEFAULT_NODE_LIMIT = 150;
const NETWORK_COLOR_HIGHLIGHT = "#20409a";
const NETWORK_COLOR_SECONDARY = "#01b9b0";
const NETWORK_COLOR_ACCENT = "#d95f02";
const MAX_LINKS_ALL = 6000;
const DATA_REMOVAL_EMAIL = "rt582@cam.ac.uk";
let contactTurnstileWidgetId = null;
let contactTurnstileToken = "";
let contactTurnstilePending = null;
/** @type {"loading"|"challenge"|"ready"|"failed"} */
let contactTurnstileState = "loading";
let contactTurnstileFailureReason = "";
/** Invalidates in-flight prepareContactTurnstile when the card remounts. */
let contactTurnstilePrepareGen = 0;
const revealedContactEmails = new Map();

const TURNSTILE_READY_TIMEOUT_MS = 15_000;
const TURNSTILE_EXECUTE_TIMEOUT_MS = 25_000;
const TURNSTILE_SCRIPT_POLL_MS = 100;
const CONTACT_TURNSTILE_LOAD_FAILED_MSG =
  "Security check could not load. If you use an ad blocker or VPN, try disabling it briefly, then tap Show email again.";
const CONTACT_TURNSTILE_TIMEOUT_MSG =
  "Security check timed out. Check your connection and try again.";
const CONTACT_TURNSTILE_CHALLENGE_MSG =
  "Complete the security check above, then tap Show email.";
const CONTACT_EMAIL_FETCH_FAILED_MSG =
  "Could not reach the email service from this browser. Try Wi‑Fi, disable content blockers for this site, or retry in Safari.";

function linkEndpointId(endpoint) {
  return typeof endpoint === "object" ? endpoint.id : endpoint;
}

function stripSimulationState(node) {
  const copy = { ...node };
  delete copy.x;
  delete copy.y;
  delete copy.vx;
  delete copy.vy;
  delete copy.fx;
  delete copy.fy;
  return copy;
}

function forceTopicCluster(matchedIds, strength = 0.1) {
  let nodes;

  function force(alpha) {
    const matched = nodes.filter((node) => matchedIds.has(node.id) && node.x != null && node.y != null);
    if (matched.length < 2) return;

    let cx = 0;
    let cy = 0;
    for (const node of matched) {
      cx += node.x;
      cy += node.y;
    }
    cx /= matched.length;
    cy /= matched.length;

    const pull = strength * alpha;
    for (const node of matched) {
      node.vx += (cx - node.x) * pull;
      node.vy += (cy - node.y) * pull;
    }
  }

  force.initialize = (_nodes) => {
    nodes = _nodes;
  };

  return force;
}

function dataCorrectionMailto(name) {
  const subject = encodeURIComponent("Correction for ICRS delegate explorer profile");
  const body = encodeURIComponent(
    `Hello,\n\nI would like to correct my information on the ICRS delegate explorer.\n\nName: ${name}\nWebsite: [your website URL]\nContact email: [your contact email]\n\nThank you.`
  );
  return `mailto:${DATA_REMOVAL_EMAIL}?subject=${subject}&body=${body}`;
}

function dataRemovalMailto(name) {
  const subject = encodeURIComponent("Request to remove my data from ICRS delegate explorer");
  const body = encodeURIComponent(
    `Hello,\n\nI would like to request removal of my information from the ICRS delegate explorer.\n\nName: ${name}\n\nThank you.`
  );
  return `mailto:${DATA_REMOVAL_EMAIL}?subject=${subject}&body=${body}`;
}

function linkedInSearchUrl(name, affiliation = "") {
  const query = encodeURIComponent(`${name} ${affiliation}`.trim());
  return `https://www.linkedin.com/search/results/people/?keywords=${query}`;
}

function fallbackLinksFor(name, affiliation = "") {
  return [
    {
      kind: "linkedin_search",
      label: "Search LinkedIn",
      url: linkedInSearchUrl(name, affiliation),
    },
    {
      kind: "scholar_search",
      label: "Search Google Scholar",
      url: scholarSearchUrl(name, affiliation),
    },
  ];
}

function normalizeProfileLinks(links, name, affiliation = "") {
  const kept = [];
  const seen = new Set();
  for (const link of links || []) {
    const url = String(link?.url || "");
    const kind = String(link?.kind || "");
    if (kind === "linkedin" || /linkedin\.com\/in\//i.test(url)) continue;
    if (kind === "linkedin_search") continue;
    if (url && !seen.has(url)) {
      seen.add(url);
      kept.push(link);
    }
  }
  kept.push({
    kind: "linkedin_search",
    label: "Search LinkedIn",
    url: linkedInSearchUrl(name, affiliation),
  });
  return kept;
}

function scholarSearchUrl(name, affiliation = "") {
  const query = encodeURIComponent(`${name} ${affiliation}`.trim());
  return `https://scholar.google.com/scholar?q=${query}`;
}

function profilePageFor(profile) {
  if (!profile) return null;

  if (profile.institutional_page) {
    return {
      label: "University profile",
      url: profile.institutional_page,
      kind: "institution",
    };
  }

  if (profile.profile_page) {
    return {
      label: profile.profile_page_label || "Personal website",
      url: profile.profile_page,
      kind: "website",
    };
  }

  const links = profile.links || [];
  const institution = links.find((link) => link.kind === "institution");
  if (institution?.url) {
    return {
      label: institution.label || "University profile",
      url: institution.url,
      kind: "institution",
    };
  }

  const website = links.find(
    (link) =>
      link.kind === "website" &&
      link.url &&
      !link.url.startsWith("mailto:") &&
      link.url !== "value" &&
      !/linkedin\.com/i.test(link.url)
  );
  if (website?.url) {
    return {
      label: website.label || "Personal website",
      url: website.url,
      kind: "website",
    };
  }

  return null;
}

function profilePageHost(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "View profile";
  }
}

function linkedInLinkFor(name, affiliation = "", profile = null) {
  const fromProfile = (profile?.links || []).find((link) => link.kind === "linkedin_search");
  if (fromProfile?.url) return fromProfile;
  return {
    kind: "linkedin_search",
    label: "Search LinkedIn",
    url: linkedInSearchUrl(name, affiliation),
  };
}

function copyEmailButtonHtml(email) {
  return `<button type="button" class="network-contact-copy" data-copy-email="${escapeHtml(email)}" aria-label="Copy email" title="Copy email">
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>
  </button>`;
}

function contactRevealKey(name, affiliation = "") {
  return `${String(name).trim().toLowerCase()}|${String(affiliation).trim().toLowerCase()}`;
}

function finishContactTurnstilePending(token = "") {
  if (!contactTurnstilePending) return;
  const { resolve } = contactTurnstilePending;
  contactTurnstilePending = null;
  resolve(token);
}

function setContactTurnstileState(state, reason = "") {
  contactTurnstileState = state;
  contactTurnstileFailureReason = reason;
}

function contactTurnstileActionEl() {
  return document.querySelector(".network-contact-email-action");
}

function contactTurnstileHintEl() {
  return document.querySelector(".network-contact-turnstile-hint");
}

function syncContactShowEmailButton() {
  const button = document.querySelector(".network-contact-show-email");
  if (!button || button.dataset.contactBusy === "1") return;
  if (SKIP_TURNSTILE || !TURNSTILE_SITE_KEY) {
    button.disabled = false;
    button.textContent = "Show email";
    return;
  }
  if (contactTurnstileState === "ready" && contactTurnstileResponse()) {
    button.disabled = false;
    button.textContent = "Show email";
    return;
  }
  if (contactTurnstileState === "failed") {
    button.disabled = false;
    button.textContent = "Try again";
    return;
  }
  button.disabled = true;
  button.textContent =
    contactTurnstileState === "loading" ? "Preparing…" : "Complete check above";
}

function syncContactTurnstileChrome() {
  const action = contactTurnstileActionEl();
  if (!action) return;
  action.classList.remove(
    "network-contact-email-action--loading",
    "network-contact-email-action--challenge",
    "network-contact-email-action--ready",
    "network-contact-email-action--failed"
  );
  if (SKIP_TURNSTILE || !TURNSTILE_SITE_KEY) {
    action.classList.add("network-contact-email-action--ready");
    syncContactShowEmailButton();
    return;
  }
  action.classList.add(`network-contact-email-action--${contactTurnstileState}`);

  const hint = contactTurnstileHintEl();
  if (hint) {
    if (contactTurnstileState === "challenge") {
      hint.textContent = CONTACT_TURNSTILE_CHALLENGE_MSG;
      hint.hidden = false;
    } else if (contactTurnstileState === "failed") {
      hint.textContent = contactTurnstileFailureReason || CONTACT_TURNSTILE_LOAD_FAILED_MSG;
      hint.hidden = false;
    } else {
      hint.hidden = true;
    }
  }
  syncContactShowEmailButton();
}

function contactTurnstileMountEl() {
  return document.getElementById("network-contact-turnstile");
}

function resetContactTurnstile() {
  contactTurnstilePrepareGen += 1;
  if (contactTurnstileWidgetId != null && window.turnstile) {
    try {
      window.turnstile.remove(contactTurnstileWidgetId);
    } catch {
      /* widget may already be gone */
    }
  }
  contactTurnstileWidgetId = null;
  contactTurnstileToken = "";
  contactTurnstileState = "loading";
  contactTurnstileFailureReason = "";
  finishContactTurnstilePending("");
}

function mountContactTurnstile() {
  // Remove a previous widget without bumping prepareGen (caller owns lifecycle).
  if (contactTurnstileWidgetId != null && window.turnstile) {
    try {
      window.turnstile.remove(contactTurnstileWidgetId);
    } catch {
      /* widget may already be gone */
    }
  }
  contactTurnstileWidgetId = null;
  contactTurnstileToken = "";
  finishContactTurnstilePending("");

  const mount = contactTurnstileMountEl();
  if (!mount) return false;
  if (!TURNSTILE_SITE_KEY || !window.turnstile) {
    setContactTurnstileState("failed", CONTACT_TURNSTILE_LOAD_FAILED_MSG);
    syncContactTurnstileChrome();
    return false;
  }
  // Make the mount visible before render. Turnstile fails (often with a
  // "network error" in the iframe) when rendered into :empty { display: none }.
  setContactTurnstileState("challenge");
  syncContactTurnstileChrome();
  void mount.offsetWidth;
  try {
    contactTurnstileWidgetId = window.turnstile.render(mount, {
      sitekey: TURNSTILE_SITE_KEY,
      action: "contact-email",
      // compact avoids the scaled "pill" CSS transform, which breaks Turnstile
      // hit-testing / iframe checks on mobile Safari.
      size: "compact",
      theme: "light",
      appearance: "always",
      callback: (token) => {
        contactTurnstileToken = token;
        setContactTurnstileState("ready");
        syncContactTurnstileChrome();
        finishContactTurnstilePending(token);
      },
      "expired-callback": () => {
        contactTurnstileToken = "";
        setContactTurnstileState("challenge");
        syncContactTurnstileChrome();
        finishContactTurnstilePending("");
      },
      "error-callback": () => {
        contactTurnstileToken = "";
        setContactTurnstileState("failed", CONTACT_TURNSTILE_LOAD_FAILED_MSG);
        syncContactTurnstileChrome();
        finishContactTurnstilePending("");
      },
    });
    return true;
  } catch (error) {
    contactTurnstileWidgetId = null;
    console.warn("Turnstile mount failed:", error);
    setContactTurnstileState("failed", CONTACT_TURNSTILE_LOAD_FAILED_MSG);
    syncContactTurnstileChrome();
    return false;
  }
}

async function prepareContactTurnstile() {
  if (SKIP_TURNSTILE || !TURNSTILE_SITE_KEY) {
    syncContactTurnstileChrome();
    return;
  }
  if (!contactTurnstileMountEl()) return;
  if (contactTurnstileWidgetId != null) return;

  const gen = contactTurnstilePrepareGen;
  setContactTurnstileState("loading");
  syncContactTurnstileChrome();
  const ready = await waitForContactTurnstileApi();
  if (gen !== contactTurnstilePrepareGen) return;
  if (!contactTurnstileMountEl()) return;
  if (!ready) {
    setContactTurnstileState("failed", CONTACT_TURNSTILE_LOAD_FAILED_MSG);
    syncContactTurnstileChrome();
    return;
  }
  if (contactTurnstileWidgetId != null) return;
  mountContactTurnstile();
}

function contactTurnstileResponse() {
  if (contactTurnstileToken) return contactTurnstileToken;
  if (contactTurnstileWidgetId == null || !window.turnstile?.getResponse) return "";
  return window.turnstile.getResponse(contactTurnstileWidgetId) || "";
}

async function waitForContactTurnstileApi(timeoutMs = TURNSTILE_READY_TIMEOUT_MS) {
  if (typeof window.turnstile?.render === "function") return true;
  const started = Date.now();
  return new Promise((resolve) => {
    const timerId = window.setInterval(() => {
      if (typeof window.turnstile?.render === "function") {
        window.clearInterval(timerId);
        resolve(true);
        return;
      }
      if (Date.now() - started >= timeoutMs) {
        window.clearInterval(timerId);
        resolve(false);
      }
    }, TURNSTILE_SCRIPT_POLL_MS);
  });
}

async function ensureContactTurnstileToken() {
  if (SKIP_TURNSTILE) return "skip";
  if (contactTurnstileState === "ready") {
    const existing = contactTurnstileResponse();
    if (existing) return existing;
  }
  if (contactTurnstileWidgetId == null || contactTurnstileState === "failed") {
    setContactTurnstileState("loading");
    syncContactTurnstileChrome();
    const ready = await waitForContactTurnstileApi();
    if (!ready) {
      setContactTurnstileState("failed", CONTACT_TURNSTILE_LOAD_FAILED_MSG);
      syncContactTurnstileChrome();
      return "";
    }
    if (!contactTurnstileMountEl()) {
      setContactTurnstileState("failed", CONTACT_TURNSTILE_LOAD_FAILED_MSG);
      syncContactTurnstileChrome();
      return "";
    }
    if (!mountContactTurnstile()) return "";
  }

  const cached = contactTurnstileResponse();
  if (cached) {
    setContactTurnstileState("ready");
    syncContactTurnstileChrome();
    return cached;
  }

  setContactTurnstileState("challenge");
  syncContactTurnstileChrome();

  return new Promise((resolve) => {
    const timeoutId = window.setTimeout(() => {
      setContactTurnstileState("failed", CONTACT_TURNSTILE_TIMEOUT_MSG);
      syncContactTurnstileChrome();
      finishContactTurnstilePending("");
      resolve("");
    }, TURNSTILE_EXECUTE_TIMEOUT_MS);

    contactTurnstilePending = {
      resolve: (token) => {
        window.clearTimeout(timeoutId);
        if (token) {
          setContactTurnstileState("ready");
          syncContactTurnstileChrome();
        }
        resolve(token);
      },
    };
  });
}

function setContactEmailError(message) {
  setContactTurnstileState("failed", message);
  syncContactTurnstileChrome();
}

function isMobileContactUi() {
  if (typeof window === "undefined") return false;
  if (window.matchMedia("(pointer: coarse)").matches) return true;
  // iPhone/iPad Chrome reports as CriOS but still uses WebKit networking.
  return /iPhone|iPad|iPod|Android/i.test(navigator.userAgent || "");
}

function renderEmailRevealHtml(node, profile) {
  if (!CONTACT_API_URL || !profile?.has_verified_email) return "";

  const cacheKey = contactRevealKey(node.label, node.affiliation);
  const cachedEmail = revealedContactEmails.get(cacheKey);
  if (cachedEmail) {
    return `
      <div class="network-contact-primary">
        <span class="network-contact-primary-label">Email</span>
        <div class="network-contact-email-row">
          <span class="network-contact-primary-value network-contact-email-value">${escapeHtml(cachedEmail)}</span>
          ${copyEmailButtonHtml(cachedEmail)}
        </div>
      </div>
    `;
  }

  // Mobile browsers (esp. Chrome on iOS) often complete Turnstile then fail the
  // cross-origin email API fetch. Desktop works; hide reveal on touch devices.
  if (isMobileContactUi()) {
    return `
      <p class="network-contact-email-desktop-note">
        View on a desktop browser to access email.
      </p>
    `;
  }

  return `
    <div class="network-contact-email-gate">
      <div class="network-contact-email-action">
        <div
          id="network-contact-turnstile"
          class="network-contact-turnstile turnstile-pill"
          aria-hidden="true"
        ></div>
        <p class="network-contact-turnstile-hint" hidden></p>
        <button
          type="button"
          class="btn-small network-contact-show-email"
          data-contact-name="${escapeHtml(node.label)}"
          data-contact-affiliation="${escapeHtml(node.affiliation || "")}"
        >
          Show email
        </button>
      </div>
    </div>
  `;
}

async function fetchVerifiedEmail(name, affiliation, button) {
  if (button) {
    button.dataset.contactBusy = "1";
    button.disabled = true;
    button.textContent = "Checking…";
  }
  if (CONTACT_API_URL && TURNSTILE_SITE_KEY && !SKIP_TURNSTILE && contactTurnstileWidgetId == null) {
    setContactTurnstileState("loading");
    syncContactTurnstileChrome();
    const ready = await waitForContactTurnstileApi();
    if (!ready) {
      setContactEmailError(CONTACT_TURNSTILE_LOAD_FAILED_MSG);
      if (button) {
        button.dataset.contactBusy = "0";
        syncContactShowEmailButton();
      }
      return null;
    }
    if (!contactTurnstileMountEl()) {
      setContactEmailError(CONTACT_TURNSTILE_LOAD_FAILED_MSG);
      if (button) {
        button.dataset.contactBusy = "0";
        syncContactShowEmailButton();
      }
      return null;
    }
    mountContactTurnstile();
  }
  if (button && !SKIP_TURNSTILE && TURNSTILE_SITE_KEY && !contactTurnstileResponse()) {
    button.textContent = "Complete check above";
  }
  const token = await ensureContactTurnstileToken();
  if (!token) {
    if (button) {
      button.dataset.contactBusy = "0";
      syncContactShowEmailButton();
    }
    return null;
  }
  if (button) button.textContent = "Fetching…";
  try {
    // Prefer same-origin Worker proxy, then the configured Fly URL. text/plain
    // avoids a CORS preflight on the cross-origin fallback (helps mobile WebKit).
    const { response, payload } = await fetchApiJson(contactApiUrlCandidates(), {
      method: "POST",
      mode: "cors",
      credentials: "omit",
      headers: { "Content-Type": "text/plain;charset=UTF-8" },
      body: JSON.stringify({
        name,
        affiliation,
        "cf-turnstile-response": token === "skip" ? "" : token,
      }),
    });
    if (!response.ok) {
      contactTurnstileToken = "";
      window.turnstile?.reset?.(contactTurnstileWidgetId);
      setContactEmailError(payload.error || "Email lookup unavailable right now.");
      if (button) {
        button.dataset.contactBusy = "0";
        syncContactShowEmailButton();
      }
      return null;
    }
    contactTurnstileToken = "";
    window.turnstile?.reset?.(contactTurnstileWidgetId);
    setContactTurnstileState("ready");
    syncContactTurnstileChrome();
    if (button) button.dataset.contactBusy = "0";
    return typeof payload.email === "string" ? payload.email : null;
  } catch {
    contactTurnstileToken = "";
    window.turnstile?.reset?.(contactTurnstileWidgetId);
    const offline = typeof navigator !== "undefined" && navigator.onLine === false;
    setContactEmailError(
      offline
        ? "You appear to be offline. Check your connection and try again."
        : CONTACT_EMAIL_FETCH_FAILED_MSG
    );
    if (button) {
      button.dataset.contactBusy = "0";
      syncContactShowEmailButton();
    }
    return null;
  }
}

function copyDelegateButtonHtml(name, affiliation) {
  return `<button type="button" class="btn-small network-contact-copy-details" data-copy-name="${escapeHtml(name)}" data-copy-affiliation="${escapeHtml(affiliation)}" data-original-label="Copy speaker details" aria-label="Copy speaker details" title="Copy name and institute">Copy speaker details</button>`;
}

function delegateDetailsText(name, affiliation = "") {
  const lines = [String(name || "").trim()];
  const inst = String(affiliation || "").trim();
  if (inst) lines.push(inst);
  return lines.join("\n");
}

function copyViaExecCommand(text) {
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.setAttribute("aria-hidden", "true");
  textarea.style.cssText =
    "position:fixed;top:0;left:0;width:1px;height:1px;padding:0;border:0;opacity:0;";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, text.length);
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  textarea.remove();
  return ok;
}

function flashCopyButton(button, ok) {
  if (!button) return;
  const originalLabel =
    button.dataset.originalLabel ||
    button.getAttribute("aria-label") ||
    button.textContent ||
    "Copy";
  if (!button.dataset.originalLabel) button.dataset.originalLabel = originalLabel;
  const usesTextLabel = Boolean(button.dataset.originalLabel && button.classList.contains("network-contact-copy-details"));

  button.classList.toggle("copied", ok);
  button.classList.toggle("copy-failed", !ok);
  button.setAttribute("aria-label", ok ? "Copied" : "Copy failed");
  button.setAttribute("title", ok ? "Copied" : "Copy failed");
  if (usesTextLabel) button.textContent = ok ? "Copied" : "Copy failed";

  window.setTimeout(() => {
    button.classList.remove("copied", "copy-failed");
    button.setAttribute("aria-label", originalLabel);
    button.setAttribute(
      "title",
      button.classList.contains("network-contact-copy-details")
        ? "Copy name and institute"
        : "Copy email"
    );
    if (usesTextLabel) button.textContent = originalLabel;
  }, 1600);
}

async function copyTextToClipboard(text, button) {
  if (!text) return false;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      flashCopyButton(button, true);
      return true;
    }
  } catch {
    /* iOS / insecure context: fall through to execCommand */
  }
  const ok = copyViaExecCommand(text);
  flashCopyButton(button, ok);
  return ok;
}

function buildAuthorSearchIndex(locations) {
  const index = new Map();
  for (const location of locations) {
    for (const detail of location.speaker_details || []) {
      const name = detail.name;
      if (!name || !detail.search_text) continue;
      for (const key of personLookupKeys(name, detail.person_key)) {
        const existing = index.get(key) || [];
        existing.push(detail.search_text);
        index.set(key, existing);
      }
    }
  }
  return index;
}

function personLookupKeys(name, personKey = "") {
  const cleaned = String(name || "").trim();
  if (!cleaned && !personKey) return [];
  const keys = new Set();
  if (isRegistryPersonKey(personKey)) keys.add(personKey);
  if (cleaned) {
    keys.add(cleaned);
    keys.add(cleaned.toLowerCase());
    keys.add(resolveCanonicalPersonName(cleaned, personKey));
    const resolved = resolveDelegatePersonKey(cleaned);
    if (resolved) keys.add(resolved);
    keys.add(normalizePersonName(cleaned));
  }
  return [...keys].filter(Boolean);
}

function indexRecordByPersonKey(record, personKey, store) {
  if (!isRegistryPersonKey(personKey)) return;
  const existing = store.get(personKey);
  if (!existing || (Array.isArray(record) && record.length > (existing.length || 0))) {
    store.set(personKey, record);
  }
}

function buildTalkTitleByPersonKey(talkTitleIndex) {
  const byKey = new Map();
  for (const [key, titles] of talkTitleIndex.entries()) {
    if (isRegistryPersonKey(key)) {
      indexRecordByPersonKey(titles, key, byKey);
    }
  }
  return byKey;
}

function buildProfileByPersonKey(speakerProfiles) {
  const byKey = new Map();
  for (const [name, profile] of Object.entries(speakerProfiles || {})) {
    for (const key of personLookupKeys(name)) {
      if (!byKey.has(key)) byKey.set(key, profile);
    }
  }
  return byKey;
}

function talksForNodeLabel(label, talkTitleIndex, talkTitleByPersonKey) {
  for (const key of personLookupKeys(label)) {
    const direct = talkTitleIndex.get(key);
    if (direct?.length) return direct;
    const indexed = talkTitleByPersonKey.get(key);
    if (indexed?.length) return indexed;
  }
  return [];
}

function talksForNode(node, talkTitleIndex, talkTitleByPersonKey) {
  const personKey = String(node?.person_key || "").trim();
  if (personKey) {
    const direct = talkTitleIndex.get(personKey);
    if (direct?.length) return direct;
    const indexed = talkTitleByPersonKey.get(personKey);
    if (indexed?.length) return indexed;
  }
  return talksForNodeLabel(node?.label, talkTitleIndex, talkTitleByPersonKey);
}

function profileForSpeakerName(label, speakerProfiles, profileByPersonKey) {
  for (const key of personLookupKeys(label)) {
    if (speakerProfiles[key]) return speakerProfiles[key];
    const profile = profileByPersonKey.get(key);
    if (profile) return profile;
  }
  return null;
}

function attendanceLabel(node) {
  if (node?.attended) return "attended";
  if (node?.on_programme) return "on programme, did not attend";
  return "non-presenting co-author";
}

function isExternalCoauthor(node) {
  return Boolean(node?.external_coauthor);
}

function externalAffiliationLabel(node) {
  if (!isExternalCoauthor(node)) return "";
  return node.affiliation_mapped ? "Mapped affiliation on file" : "No mapped affiliation";
}

function defaultNodeFill(node) {
  if (isExternalCoauthor(node)) return NETWORK_COLOR_SECONDARY;
  return NETWORK_COLOR_ACCENT;
}

function authorContextFor(node, profile) {
  const role = node?.author_role || profile?.profile_role || null;
  const affiliationExplicit = Boolean(node?.affiliation_explicit);
  return { role, affiliationExplicit };
}

function authorRoleLabel(role) {
  if (role === "presenter") return "Presenting author";
  if (role === "co_author") return "Co-author";
  return "Author";
}

function profileStatusLabel({ role, affiliationExplicit, hasProfile }) {
  if (hasProfile) return "Profile available";
  if (role === "presenter" && !affiliationExplicit) {
    return "Without a confirmed affiliation";
  }
  if (role === "co_author") {
    return "No looked-up profile";
  }
  return "";
}

function affiliationNote({ affiliationExplicit, affiliation }) {
  if (!affiliation || !affiliationExplicit) return "";
  return affiliation;
}

function buildAffiliationSearchIndex(locations) {
  const index = new Map();
  for (const location of locations) {
    if (location.affiliation && location.search_text) {
      index.set(location.affiliation, location.search_text);
    }
  }
  return index;
}

export function createNetworkView(siteData, elements) {
  const network = siteData.network;
  const speakerProfiles = elements.speakerProfiles || {};
  const authorSearchIndex = buildAuthorSearchIndex(siteData.locations || []);
  const affiliationSearchIndex = buildAffiliationSearchIndex(siteData.locations || []);
  const talkTitleIndex = buildTalkTitleIndex(
    siteData.locations || [],
    siteData.talk_titles_by_person_key || siteData.talk_titles_by_author
  );
  const talkTitleByPersonKey = buildTalkTitleByPersonKey(talkTitleIndex);
  const profileByPersonKey = buildProfileByPersonKey(speakerProfiles);
  const talksData = elements.talksData || { by_id: {}, title_index: {} };
  const talksById = talksData.by_id || {};
  const similarityLookup = createTalkSimilarityLookup(
    elements.similaritiesData || { by_id: {} },
    talksById
  );
  let selectedTalkId = null;
  let selectedSpeakerName = "";
  let selectedPersonKey = "";
  let similarRequestId = 0;
  let mode = "individual";
  let nodeLimit = DEFAULT_NODE_LIMIT;
  let graphTotalNodes = 0;
  let graphThinned = false;
  let selectedNodeId = null;
  let searchQuery = "";
  let matchedNodeIds = new Set();
  let simulation = null;
  let hasRendered = false;
  let graphNodes = [];
  let graphLinks = [];
  let radiusScale = null;
  let linkSelection = null;
  let nodeSelection = null;
  let labelSelection = null;
  let selectedLabelSelection = null;
  let labelOverlay = null;
  let dragMoved = false;
  let resizeTimer = null;
  let graphRenderKey = "";
  let viewFitGeneration = 0;
  let userAdjustedZoom = false;
  let pendingNodeCenter = false;
  const isCoarsePointer = window.matchMedia("(pointer: coarse)").matches;
  const canvasEl =
    elements.stage?.querySelector?.(".network-stage-canvas") || elements.stage;
  const cardDesktopMq = window.matchMedia("(min-width: 901px)");

  function cardOnStage() {
    return cardDesktopMq.matches;
  }

  function placeNetworkCard() {
    const card = elements.card;
    const slot = elements.cardSlot;
    if (!card || !slot || !canvasEl) return;

    const target = cardOnStage() ? canvasEl : slot;
    if (card.parentElement !== target) {
      target.appendChild(card);
    }
    card.classList.toggle("network-side-card--on-stage", cardOnStage());
  }

  function resetCardScroll() {
    const card = elements.card;
    if (!card) return;
    card.scrollTop = 0;
    card.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }

  function resetPanelScrollForSelection() {
    if (cardOnStage()) return;
    const panel = document.getElementById("network-panel");
    if (panel) panel.scrollTop = 0;
    const sidebar = panel?.querySelector(".network-sidebar-scroll");
    if (sidebar) sidebar.scrollTop = 0;
    if (elements.cardSlot) elements.cardSlot.scrollTop = 0;
  }

  function syncOnStageCardBounds() {
    const card = elements.card;
    if (!card || !cardOnStage()) {
      if (card) card.style.maxHeight = "";
      return;
    }
    const available = Math.max(canvasEl.clientHeight - 32, 220);
    const cap = Math.min(window.innerHeight * 0.72, available);
    card.style.maxHeight = `${cap}px`;
  }

  function pinSelectionCardToTop({ resetPanel = false } = {}) {
    const card = elements.card;
    if (!card || card.hidden) return;
    syncOnStageCardBounds();

    const run = () => {
      resetCardScroll();
      if (resetPanel) resetPanelScrollForSelection();
    };

    run();
    window.requestAnimationFrame(run);
  }

  const width = () => Math.max(canvasEl.clientWidth, 320);
  const height = () => Math.max(canvasEl.clientHeight, 280);

  const svg = d3.select(elements.networkSvg);
  const viewport = svg.append("g").attr("class", "viewport");
  const graphLayer = viewport.append("g").attr("class", "graph-layer");
  labelOverlay = viewport.append("g").attr("class", "label-overlay");

  const zoom = d3
    .zoom()
    .scaleExtent([0.35, 10])
    .filter((event) => {
      if (event.type === "wheel") return true;
      if (event.type.startsWith("touch") && event.touches?.length > 1) return true;
      const target = event.target;
      return target === svg.node() || target?.nodeName === "svg";
    })
    .on("zoom", (event) => {
      viewport.attr("transform", event.transform);
      if (event.sourceEvent) userAdjustedZoom = true;
    });

  svg.call(zoom).on("dblclick.zoom", null);

  function parseNodeLimit(value) {
    if (value === "all" || value == null) return null;
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_NODE_LIMIT;
  }

  function neighbourIdsFromLinks(nodeId, links) {
    const ids = new Set();
    if (!nodeId) return ids;
    for (const link of links) {
      const sourceId = linkEndpointId(link.source);
      const targetId = linkEndpointId(link.target);
      if (sourceId === nodeId) ids.add(targetId);
      if (targetId === nodeId) ids.add(sourceId);
    }
    return ids;
  }

  function maybeThinLinks(links) {
    if (nodeLimit != null || links.length <= MAX_LINKS_ALL) return links;
    return [...links]
      .sort((a, b) => b.weight - a.weight)
      .slice(0, MAX_LINKS_ALL);
  }

  function limitGraph(nodes, links, mustInclude = new Set()) {
    const totalNodes = nodes.length;
    const required = nodes.filter((node) => mustInclude.has(node.id));
    const optional = nodes
      .filter((node) => !mustInclude.has(node.id))
      .sort((a, b) => b.connections - a.connections || a.label.localeCompare(b.label));

    let kept;
    if (nodeLimit == null || nodes.length <= nodeLimit) {
      kept = nodes;
    } else {
      const optionalSlots = Math.max(0, nodeLimit - required.length);
      kept = [...required, ...optional.slice(0, optionalSlots)];
    }

    const keep = new Set(kept.map((node) => node.id));
    const filteredNodes = nodes.filter((node) => keep.has(node.id));
    const filteredLinks = links.filter(
      (link) =>
        keep.has(linkEndpointId(link.source)) && keep.has(linkEndpointId(link.target))
    );

    return {
      nodes: filteredNodes,
      links: maybeThinLinks(filteredLinks),
      totalNodes,
      thinned: filteredNodes.length < totalNodes,
    };
  }

  function mustIncludeIds(fullLinks) {
    const mustInclude = new Set(matchedNodeIds);
    if (selectedNodeId) {
      mustInclude.add(selectedNodeId);
      for (const id of neighbourIdsFromLinks(selectedNodeId, fullLinks)) {
        mustInclude.add(id);
      }
    }
    return mustInclude;
  }

  function graphRenderSignature(nodes, links) {
    const nodeIds = nodes.map((node) => node.id).sort().join("|");
    return `${mode}:${nodeLimit ?? "all"}:${searchQuery}:${selectedNodeId ?? ""}:${nodeIds}:${links.length}`;
  }

  function thinningSummary() {
    if (selectedNodeId) {
      const name = currentGraph().nodes.find((node) => node.id === selectedNodeId)?.label;
      const neighbourCount = Math.max(0, graphNodes.length - 1);
      return `Showing <strong>${neighbourCount.toLocaleString()}</strong> co-author${neighbourCount === 1 ? "" : "s"} linked to ${escapeHtml(name || "selection")}.`;
    }
    if (!graphThinned || !graphTotalNodes) return "";
    if (searchQuery && matchedNodeIds.size) {
      return `Showing <strong>${graphNodes.length.toLocaleString()}</strong> of <strong>${graphTotalNodes.toLocaleString()}</strong> matches and co-authors. All <strong>${matchedNodeIds.size.toLocaleString()}</strong> matches are included.`;
    }
    return `Showing <strong>${graphNodes.length.toLocaleString()}</strong> of <strong>${graphTotalNodes.toLocaleString()}</strong> nodes (by greatest number of connections). Search or increase “Nodes shown” to explore more.`;  }

  function currentGraph() {
    return network[mode];
  }

  function matchSnippet(node) {
    if (!searchQuery) return "";

    const texts =
      mode === "individual"
        ? authorSearchIndex.get(node.label) || []
        : [affiliationSearchIndex.get(node.label) || ""].filter(Boolean);
    const q = searchQuery.toLowerCase();

    for (const text of texts) {
      const haystack = text.toLowerCase();
      const idx = haystack.indexOf(q);
      if (idx < 0) continue;

      const start = Math.max(0, idx - 48);
      const end = Math.min(text.length, idx + searchQuery.length + 72);
      let snippet = text.slice(start, end).replace(/\s+/g, " ").trim();
      if (start > 0) snippet = `…${snippet}`;
      if (end < text.length) snippet = `${snippet}…`;
      return snippet;
    }

    if (node.label.toLowerCase().includes(q)) {
      return `Name matches “${searchQuery}”.`;
    }
    if (mode === "individual" && node.affiliation?.toLowerCase().includes(q)) {
      return `Affiliation matches “${searchQuery}”.`;
    }

    return "";
  }

  function initializeSearchLayout(nodes, links, centerX, centerY) {
    const matchNodes = nodes
      .filter((node) => matchedNodeIds.has(node.id))
      .sort((a, b) => b.connections - a.connections || a.label.localeCompare(b.label));
    const otherNodes = nodes.filter((node) => !matchedNodeIds.has(node.id));
    const matchCount = Math.max(matchNodes.length, 1);
    const baseRadius = Math.max(36, Math.min(180, 18 + Math.sqrt(matchCount) * 10));

    matchNodes.forEach((node, index) => {
      const ring = Math.floor(index / Math.max(1, Math.ceil(Math.sqrt(matchCount))));
      const angle = (2 * Math.PI * index) / matchCount + ring * 0.35;
      const radius = baseRadius + ring * (22 + baseRadius * 0.14);
      node.x = centerX + radius * Math.cos(angle);
      node.y = centerY + radius * Math.sin(angle);
      delete node.vx;
      delete node.vy;
      delete node.fx;
      delete node.fy;
    });

    const matchById = new Map(matchNodes.map((node) => [node.id, node]));
    const anchorByNodeId = new Map();
    for (const link of links) {
      const sourceId = linkEndpointId(link.source);
      const targetId = linkEndpointId(link.target);
      if (matchedNodeIds.has(sourceId) && !matchedNodeIds.has(targetId)) {
        anchorByNodeId.set(targetId, matchById.get(sourceId));
      }
      if (matchedNodeIds.has(targetId) && !matchedNodeIds.has(sourceId)) {
        anchorByNodeId.set(sourceId, matchById.get(targetId));
      }
    }

    otherNodes.forEach((node, index) => {
      const anchor = anchorByNodeId.get(node.id);
      const angle = (2 * Math.PI * index) / Math.max(otherNodes.length, 1);
      const offset = 36 + (index % 5) * 10;
      if (anchor?.x != null && anchor?.y != null) {
        node.x = anchor.x + offset * Math.cos(angle);
        node.y = anchor.y + offset * Math.sin(angle);
      } else {
        node.x = centerX + (Math.random() - 0.5) * baseRadius;
        node.y = centerY + (Math.random() - 0.5) * baseRadius;
      }
      delete node.vx;
      delete node.vy;
      delete node.fx;
      delete node.fy;
    });
  }

  function nodeMatchesSearch(node, query) {
    const q = foldSearchText(query).trim();
    if (!q) return false;
    if (foldSearchText(node.label).includes(q)) return true;
    if (mode === "individual" && node.affiliation && foldSearchText(node.affiliation).includes(q)) {
      return true;
    }
    if (mode === "individual" && isRegistryPersonKey(node.person_key)) {
      const canonical = resolveCanonicalPersonName(node.label, node.person_key);
      if (foldSearchText(canonical).includes(q)) return true;
    }
    if (mode === "individual") {
      for (const key of personLookupKeys(node.label, node.person_key)) {
        const texts = authorSearchIndex.get(key) || [];
        if (texts.some((text) => foldSearchText(text).includes(q))) return true;
      }
    } else if (foldSearchText(affiliationSearchIndex.get(node.label) || "").includes(q)) {
      return true;
    }
    return false;
  }

  function formatNodeMeta(node) {
    const profile = profileForNode(node);
    const context = authorContextFor(node, profile);
    const role = context.role || "co_author";
    const parts = [
      authorRoleLabel(role),
      attendanceLabel(node),
      `on author list of ${node.connections.toLocaleString()} talk${node.connections === 1 ? "" : "s"}`,
    ];
    const externalAffiliation = externalAffiliationLabel(node);
    if (externalAffiliation) {
      parts.push(externalAffiliation);
    }
    if (mode === "individual" && node.affiliation) {
      const showAffiliation = !isExternalCoauthor(node) || node.affiliation_mapped;
      if (showAffiliation) {
        parts.push(
          affiliationNote({
            affiliationExplicit: context.affiliationExplicit,
            affiliation: node.affiliation,
          })
        );
      }
    }
    return parts.join(" · ");
  }

  function profileForNode(node) {
    if (!node || mode !== "individual") return null;
    const personKey = String(node.person_key || "").trim();
    if (personKey && speakerProfiles[personKey]) {
      return speakerProfiles[personKey];
    }
    if (personKey && profileByPersonKey.get(personKey)) {
      return profileByPersonKey.get(personKey);
    }
    return profileForSpeakerName(node.label, speakerProfiles, profileByPersonKey);
  }

  function renderContactLinksHtml(node) {
    if (!elements.cardContacts) return "";

    if (mode !== "individual") {
      return `
        <p class="network-contact-note">
          Switch to <strong>By individual</strong> to see profile and contact links for speakers.
        </p>
      `;
    }

    const affiliation = node.affiliation || "";
    const profile = profileForNode(node);
    const context = authorContextFor(node, profile);
    const role = context.role || "co_author";
    const profileStatus = profileStatusLabel({
      role,
      affiliationExplicit: context.affiliationExplicit,
      hasProfile: Boolean(profile),
    });
    const profilePage = profilePageFor(profile);
    const linkedIn = linkedInLinkFor(node.label, affiliation, profile);
    const emailReveal = renderEmailRevealHtml(node, profile);
    const linkItems = [
      profilePage
        ? `
          <li>
            <a href="${escapeHtml(profilePage.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(profilePage.label)}</a>
            <span class="network-contact-link-host">${escapeHtml(profilePageHost(profilePage.url))}</span>
          </li>
        `
        : "",
      `
        <li>
          <a href="${escapeHtml(linkedIn.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(linkedIn.label)}</a>
        </li>
      `,
    ].join("");

    return `
      <p class="hover-kicker network-contact-kicker">Connect</p>
      <p class="network-contact-role">${escapeHtml(authorRoleLabel(role))}</p>
      ${profileStatus ? `<p class="network-contact-status">${escapeHtml(profileStatus)}</p>` : ""}
      <div class="network-contact-copy-details-wrap">
        ${copyDelegateButtonHtml(node.label, affiliation)}
      </div>
      ${emailReveal}
      <ul class="network-contact-links">${linkItems}</ul>
      <p class="network-contact-footnote">Copy speaker details or follow the public profile links below.</p>
    `;
  }

  function updateNodeContacts(node) {
    if (!elements.cardContacts) return;
    resetContactTurnstile();
    if (!node) {
      elements.cardContacts.hidden = true;
      elements.cardContacts.innerHTML = "";
      return;
    }
    elements.cardContacts.hidden = false;
    elements.cardContacts.innerHTML = renderContactLinksHtml(node);
    void prepareContactTurnstile();
  }

  function updateMatches(query) {
    searchQuery = query.trim();
    matchedNodeIds = new Set();
    if (!searchQuery) return matchedNodeIds;

    const graph = currentGraph();
    for (const node of graph.nodes) {
      if (nodeMatchesSearch(node, searchQuery)) {
        matchedNodeIds.add(node.id);
      }
    }
    return matchedNodeIds;
  }

  function graphBounds({ nodeIds = null } = {}) {
    if (!graphNodes.length) return null;

    const nodes =
      nodeIds && nodeIds.size
        ? graphNodes.filter((node) => nodeIds.has(node.id))
        : graphNodes;
    if (!nodes.length) return null;

    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;

    for (const node of nodes) {
      if (node.x == null || node.y == null) continue;
      const radius = radiusScale
        ? radiusScale(Math.max(1, node.connections)) + (isCoarsePointer ? 8 : 4)
        : 12;
      const labelPad = node.id === selectedNodeId ? 22 : 14;
      minX = Math.min(minX, node.x - radius);
      minY = Math.min(minY, node.y - radius - labelPad);
      maxX = Math.max(maxX, node.x + radius);
      maxY = Math.max(maxY, node.y + radius);
    }

    if (!Number.isFinite(minX)) return null;

    return {
      minX,
      minY,
      maxX,
      maxY,
      width: Math.max(maxX - minX, 1),
      height: Math.max(maxY - minY, 1),
      cx: (minX + maxX) / 2,
      cy: (minY + maxY) / 2,
    };
  }

  function fitToView({
    animate = false,
    transitionMs = 250,
    nodeIds = null,
    minScale = 0.35,
    maxScale = 2.5,
    padding = 56,
  } = {}) {
    const bounds = graphBounds({ nodeIds });
    if (!bounds) return;

    const w = width();
    const h = height();
    const scale = Math.min(
      (w - padding * 2) / bounds.width,
      (h - padding * 2) / bounds.height,
      maxScale
    );
    const clampedScale = Math.max(minScale, scale);
    const transform = d3.zoomIdentity
      .translate(w / 2, h / 2)
      .scale(clampedScale)
      .translate(-bounds.cx, -bounds.cy);

    if (animate) {
      svg.transition().duration(transitionMs).call(zoom.transform, transform);
    } else {
      svg.call(zoom.transform, transform);
    }
  }

  function centerOnNode(node, { animate = true, transitionMs = 300 } = {}) {
    const target = typeof node === "string" ? graphNodes.find((item) => item.id === node) : node;
    if (!target || target.x == null || target.y == null) return;

    const w = width();
    const h = height();
    const { k } = d3.zoomTransform(svg.node());
    const transform = d3.zoomIdentity
      .translate(w / 2, h / 2)
      .scale(k)
      .translate(-target.x, -target.y);

    if (animate) {
      svg.transition().duration(transitionMs).call(zoom.transform, transform);
    } else {
      svg.call(zoom.transform, transform);
    }
  }

  function maybeCenterSelectedNode({ animate = true } = {}) {
    if (!pendingNodeCenter || !selectedNodeId) return;
    const node = graphNodes.find((item) => item.id === selectedNodeId);
    if (!node || node.x == null || node.y == null) return;
    if (simulation && simulation.alpha() > simulation.alphaMin() + 0.001) return;
    centerOnNode(node, { animate });
    pendingNodeCenter = false;
  }

  function prepareGraph() {
    const graph = currentGraph();
    const fullLinks = graph.links;
    const nodesById = new Map(graph.nodes.map((node) => [node.id, stripSimulationState(node)]));
    let links = fullLinks
      .filter(
        (link) =>
          nodesById.has(linkEndpointId(link.source)) &&
          nodesById.has(linkEndpointId(link.target))
      )
      .map((link) => ({ ...link }));

    let nodes = [...nodesById.values()];
    const mustInclude = mustIncludeIds(fullLinks);

    if (selectedNodeId) {
      const egoIds = mustInclude;
      const egoNodes = nodes.filter((node) => egoIds.has(node.id));
      const egoLinks = links.filter(
        (link) =>
          egoIds.has(linkEndpointId(link.source)) && egoIds.has(linkEndpointId(link.target))
      );
      graphTotalNodes = nodesById.size;
      graphThinned = egoNodes.length < nodesById.size;
      return { nodes: egoNodes, links: maybeThinLinks(egoLinks) };
    }

    if (searchQuery && matchedNodeIds.size) {
      const visibleIds = new Set(matchedNodeIds);
      for (const link of links) {
        const sourceId = linkEndpointId(link.source);
        const targetId = linkEndpointId(link.target);
        if (visibleIds.has(sourceId)) visibleIds.add(targetId);
        if (visibleIds.has(targetId)) visibleIds.add(sourceId);
      }
      for (const id of mustInclude) visibleIds.add(id);
      nodes = nodes.filter((node) => visibleIds.has(node.id));
      links = links.filter(
        (link) =>
          visibleIds.has(linkEndpointId(link.source)) &&
          visibleIds.has(linkEndpointId(link.target))
      );
    }

    const limited = limitGraph(nodes, links, mustInclude);
    graphTotalNodes = limited.totalNodes;
    graphThinned = limited.thinned;
    return { nodes: limited.nodes, links: limited.links };
  }

  function buildRadiusScale(nodes) {
    const counts = nodes.map((node) => Math.max(1, node.connections));
    const minCount = Math.max(1, d3.min(counts));
    const maxCount = Math.max(minCount + 1, d3.max(counts));
    return d3.scaleLog().domain([minCount, maxCount]).range([4, 26]).clamp(true);
  }

  function labelDisplayLength(label) {
    return Math.min(String(label || "").length, 28);
  }

  function nodeCollisionRadius(d, scale = radiusScale) {
    const nodeRadius = scale ? scale(Math.max(1, d.connections)) : 8;
    const labelChars = labelDisplayLength(d.label);
    const labelHalfWidth = labelChars * 3.4;
    const labelHeight = 16;
    const pad = isCoarsePointer ? 10 : 8;
    return Math.max(nodeRadius + pad, labelHalfWidth + pad, nodeRadius + labelHeight + pad);
  }

  function renderSearchResults(nodes) {
    if (!elements.results || !elements.resultsTitle) return;
    const searching = Boolean(searchQuery);
    elements.resultsWrap?.classList.toggle("has-search-results", searching);

    if (!searching) {
      elements.resultsTitle.textContent = "Search matches";
      elements.results.innerHTML = "";
      return;
    }

    const matches = nodes.filter((node) => matchedNodeIds.has(node.id));
    const neighbours = neighbourIds(selectedNodeId);
    elements.resultsTitle.textContent = `${matches.length.toLocaleString()} matching node${matches.length === 1 ? "" : "s"}`;

    if (!matches.length) {
      elements.results.innerHTML = `<p class="status">No nodes match that search.</p>`;
      return;
    }

    elements.results.innerHTML = matches
      .sort((a, b) => b.connections - a.connections || a.label.localeCompare(b.label))
      .slice(0, 30)
      .map((node) => {
        return `
        <button type="button" class="result-item${node.id === selectedNodeId ? " selected" : ""}${selectedNodeId && neighbours.has(node.id) ? " neighbour" : ""}" data-node-id="${escapeHtml(node.id)}">
          <div class="affiliation">${escapeHtml(node.label)}</div>
          <div class="meta">${escapeHtml(formatNodeMeta(node))}</div>
        </button>`;
      })
      .join("");

    elements.results.querySelectorAll("[data-node-id]").forEach((button) => {
      button.addEventListener("click", () => selectNode(button.dataset.nodeId));
    });
  }

  function renderLegend(nodes, radiusScale) {
    renderCoauthorshipLegend();
    renderScaleLegend(nodes, radiusScale);
  }

  function renderCoauthorshipLegend() {
    if (!elements.legendCoauthorship) return;

    const searchSection =
      searchQuery && matchedNodeIds.size
        ? `
      <h3>Topic search</h3>
      <p>Matches cluster at the centre; grey nodes are co-authors on the same talks.</p>
      <div class="legend-row">
        <span class="legend-dot legend-dot--accent"></span>
        <span>Matches “${escapeHtml(searchQuery)}”</span>
      </div>
      <div class="legend-row">
        <span class="legend-dot legend-dot--muted"></span>
        <span>Co-authors (not a direct match)</span>
      </div>
    `
        : "";

    elements.legendCoauthorship.innerHTML = `
      <h3>Co-authorship links</h3>
      <p>Edges connect speakers or affiliations (represented by nodes) which share authorship on at least one ICRS talk.</p>
      ${searchSection}
    `;
  }

  function renderScaleLegend(nodes, radiusScale) {
    if (!elements.legendScale || !radiusScale) return;
    const counts = nodes.map((node) => node.connections);
    const minCount = Math.max(1, d3.min(counts) || 1);
    const maxCount = Math.max(minCount, d3.max(counts) || 1);
    const talkLabel = (count) =>
      `${count.toLocaleString()} talk${count === 1 ? "" : "s"}`;
    const samples =
      minCount === maxCount
        ? [{ label: talkLabel(minCount), value: minCount }]
        : (() => {
            const midCount = Math.round(Math.sqrt(minCount * maxCount));
            return [
              { label: talkLabel(minCount), value: minCount },
              { label: talkLabel(midCount), value: midCount },
              { label: talkLabel(maxCount), value: maxCount },
            ];
          })();

    elements.legendScale.innerHTML = `
      <h3>Node size</h3>
      <p>Circle area scales logarithmically with the number of talks on which this node appears.</p>
      ${samples
        .map(
          (sample) => `
        <div class="legend-row">
          <span class="legend-dot legend-dot--accent" style="width:${radiusScale(sample.value) * 2}px;height:${radiusScale(sample.value) * 2}px"></span>
          <span>${sample.label}</span>
        </div>`
        )
        .join("")}
      <h3>Node colour</h3>
      <div class="legend-row">
        <span class="legend-dot legend-dot--accent"></span>
        <span>Delegate list and programme authors</span>
      </div>
      <div class="legend-row">
        <span class="legend-dot legend-dot--secondary"></span>
        <span>Co-authors not on programme or delegate list</span>
      </div>
      <p>Lines represent co-authorship links between nodes.</p>
    `;
    
  }

  function neighbourIds(nodeId) {
    return neighbourIdsFromLinks(nodeId, graphLinks);
  }

  function defaultLabelNodeIds(nodes) {
    const sorted = [...nodes].sort(
      (a, b) => b.connections - a.connections || a.label.localeCompare(b.label)
    );
    const count = Math.min(48, Math.max(20, Math.ceil(nodes.length * 0.22)));
    return new Set(sorted.slice(0, count).map((node) => node.id));
  }

  function labelNodes(nodes) {
    const searching = Boolean(searchQuery);
    const neighbours = neighbourIds(selectedNodeId);
    const defaultLabels =
      !searchQuery && !selectedNodeId ? defaultLabelNodeIds(nodes) : null;
    return nodes.filter((node) => {
      if (node.id === selectedNodeId) return false;
      if (selectedNodeId && neighbours.has(node.id)) return true;
      if (searching && matchedNodeIds.has(node.id)) return true;
      if (defaultLabels?.has(node.id)) return true;
      return false;
    });
  }

  function nodeDrawOrder(node, neighbours) {
    if (node.id === selectedNodeId) return 3;
    if (selectedNodeId && neighbours.has(node.id)) return 2;
    if (searchQuery && matchedNodeIds.has(node.id)) return 1;
    return 0;
  }

  function labelDrawOrder(node, neighbours) {
    return nodeDrawOrder(node, neighbours);
  }

  function raiseSelectedLabel() {
    labelOverlay?.raise();
    selectedLabelSelection?.raise();
  }

  function selectedLabelDy(d) {
    return -radiusScale(Math.max(1, d.connections)) - 3;
  }

  function updateSelectedLabel(node) {
    if (!labelOverlay) return;

    selectedLabelSelection = selectedLabelSelection || labelOverlay.selectAll("text.label-selected");
    selectedLabelSelection = selectedLabelSelection.data(node ? [node] : [], (d) => d.id);
    selectedLabelSelection.exit().remove();

    const selectedLabelEnter = selectedLabelSelection
      .enter()
      .append("text")
      .attr("class", "label-selected")
      .attr("text-anchor", "middle")
      .attr("pointer-events", "none");

    selectedLabelSelection = selectedLabelEnter.merge(selectedLabelSelection);
    if (!node) {
      raiseSelectedLabel();
      return;
    }

    selectedLabelSelection
      .attr("font-size", 14)
      .attr("font-weight", 700)
      .attr("fill", "#14212b")
      .attr("fill-opacity", 1)
      .attr("stroke", "#ffffff")
      .attr("stroke-width", 5)
      .attr("stroke-opacity", 0.95)
      .attr("paint-order", "stroke")
      .attr("dy", selectedLabelDy)
      .text((d) => (d.label.length > 32 ? `${d.label.slice(0, 30)}…` : d.label))
      .attr("x", (d) => d.x)
      .attr("y", (d) => d.y);

    raiseSelectedLabel();
  }

  function linkEndpointIds(link) {
    return {
      sourceId: linkEndpointId(link.source),
      targetId: linkEndpointId(link.target),
    };
  }

  function linkTier(link, neighbours) {
    if (!selectedNodeId) return "default";
    const { sourceId, targetId } = linkEndpointIds(link);
    if (sourceId === selectedNodeId || targetId === selectedNodeId) return "primary";
    if (neighbours.has(sourceId) && neighbours.has(targetId)) return "secondary";
    return "dim";
  }

  function linkStroke(tier) {
    if (tier === "primary") return NETWORK_COLOR_HIGHLIGHT;
    if (tier === "secondary") return NETWORK_COLOR_HIGHLIGHT;
    return "#94a3ad";
  }

  function linkOpacity(tier) {
    if (tier === "default") return 0.18;
    if (tier === "primary") return 0.5;
    if (tier === "secondary") return 0.08;
    return 0.05;
  }

  function linkWidth(link, tier) {
    const base = Math.max(0.35, Math.log2(link.weight + 1) * 0.45);
    if (tier === "primary") return base + 0.9;
    if (tier === "secondary") return base + 0.15;
    return base;
  }

  function nodeFill(node) {
    if (searchQuery && matchedNodeIds.size && !matchedNodeIds.has(node.id)) return "#b8c4cc";
    return defaultNodeFill(node);
  }

  function updateSelectionUi() {
    const node = selectedNodeId
      ? currentGraph().nodes.find((item) => item.id === selectedNodeId)
      : null;

    if (node) {
      showNodeCard(node);
      elements.cardClear?.removeAttribute("hidden");
      if (cardOnStage()) {
        elements.clearSelection?.setAttribute("hidden", "");
      } else {
        elements.clearSelection?.removeAttribute("hidden");
      }
    } else {
      elements.card.hidden = true;
      updateViewLinks(null);
      updateNodeTalks(null);
      updateNodeContacts(null);
      setDataInfoOpen(false);
      elements.cardClear?.setAttribute("hidden", "");
      elements.clearSelection?.setAttribute("hidden", "");
    }

    const thinningNote = thinningSummary();
    elements.summary.innerHTML = selectedNodeId
      ? `<strong>${graphNodes.length.toLocaleString()}</strong> nodes · tap background or Clear to deselect`
      : [
          // `showing <strong>${graphNodes.length.toLocaleString()}</strong> nodes · <strong>${graphLinks.length.toLocaleString()}</strong> co-authorship links}`,
          thinningNote,
        ]
          .filter(Boolean)
          .join(" · ");
  }

  function scrollToSelectedSidebar() {
    /* Intentionally no-op: scrolling the bar chart into view was jumping the
       sidebar and speaker card to the wrong position on selection. */
  }

  function barChartNodes(nodes) {
    const sorted = [...nodes].sort((a, b) => b.connections - a.connections);
    const limit = 12;
    let chartNodes = sorted.slice(0, limit);
    if (selectedNodeId && !chartNodes.some((node) => node.id === selectedNodeId)) {
      const selected = nodes.find((node) => node.id === selectedNodeId);
      if (selected) {
        chartNodes = [...chartNodes.slice(0, limit - 1), selected].sort(
          (a, b) => b.connections - a.connections
        );
      }
    }
    return chartNodes;
  }

  function updateHighlight() {
    if (!nodeSelection || !linkSelection || !radiusScale) return;

    const searching = Boolean(searchQuery);
    const neighbours = neighbourIds(selectedNodeId);

    linkSelection
      .attr("stroke", (d) => linkStroke(linkTier(d, neighbours)))
      .attr("stroke-opacity", (d) => linkOpacity(linkTier(d, neighbours)))
      .attr("stroke-width", (d) => linkWidth(d, linkTier(d, neighbours)));

    nodeSelection
      .sort((a, b) => nodeDrawOrder(a, neighbours) - nodeDrawOrder(b, neighbours))
      .attr("fill", (d) => nodeFill(d))
      .attr("stroke", (d) => {
        if (d.id === selectedNodeId) return NETWORK_COLOR_HIGHLIGHT;
        if (searching && matchedNodeIds.has(d.id)) return NETWORK_COLOR_HIGHLIGHT;
        return "#ffffff";
      })
      .attr("stroke-width", (d) => {
        if (d.id === selectedNodeId) return 3.5;
        if (selectedNodeId && neighbours.has(d.id)) return 2.5;
        if (searching && matchedNodeIds.has(d.id)) return 2.5;
        return 1.5;
      })
      .attr("opacity", (d) => {
        if (d.id === selectedNodeId) return 1;
        if (selectedNodeId) {
          return neighbours.has(d.id) ? 0.72 : 0.16;
        }
        if (searching && matchedNodeIds.size) {
          return matchedNodeIds.has(d.id) ? 0.95 : 0.14;
        }
        return 0.88;
      });

    const labels = labelNodes(graphNodes);
    labelSelection = labelSelection.data(labels, (d) => d.id);
    labelSelection.exit().remove();
    const labelEnter = labelSelection
      .enter()
      .append("text")
      .attr("text-anchor", "middle")
      .attr("pointer-events", "none");
    labelSelection = labelEnter.merge(labelSelection);
    labelSelection
      .sort((a, b) => labelDrawOrder(a, neighbours) - labelDrawOrder(b, neighbours))
      .attr("font-size", 10)
      .attr("font-weight", (d) => (neighbours.has(d.id) ? 600 : 500))
      .attr("fill", (d) => (neighbours.has(d.id) ? "#1a3340" : "#14212b"))
      .attr("fill-opacity", 1)
      .attr("stroke", "#ffffff")
      .attr("stroke-width", 3)
      .attr("stroke-opacity", 0.88)
      .attr("paint-order", "stroke")
      .attr("dy", (d) => -radiusScale(Math.max(1, d.connections)) - 0)
      .text((d) => (d.label.length > 28 ? `${d.label.slice(0, 26)}…` : d.label))
      .attr("x", (d) => d.x)
      .attr("y", (d) => d.y);

    const selectedNode = selectedNodeId
      ? graphNodes.find((node) => node.id === selectedNodeId) || null
      : null;
    updateSelectedLabel(selectedNode);

    renderSearchResults(graphNodes);
    updateSelectionUi();
    renderBarChart(graphNodes);
    if (radiusScale) renderLegend(graphNodes, radiusScale);
    scrollToSelectedSidebar();
    refreshTalkAuthors();
    maybeCenterSelectedNode();
  }

  function renderBarChart(nodes) {
    if (!elements.barChart) return;
    const sorted = barChartNodes(nodes);
    const maxConnections = sorted[0]?.connections || 1;
    const logScale = d3.scaleLog().domain([1, maxConnections]).range([0.08, 1]).clamp(true);
    const neighbours = neighbourIds(selectedNodeId);

    elements.barChart.innerHTML = sorted
      .map((node) => {
        const widthPct = `${logScale(Math.max(1, node.connections)) * 100}%`;
        const selected = node.id === selectedNodeId;
        const neighbour = selectedNodeId && neighbours.has(node.id);
        const dimmed =
          (searchQuery && matchedNodeIds.size && !matchedNodeIds.has(node.id)) ||
          (selectedNodeId && !selected && !neighbour);
        return `
          <button type="button" class="bar-row${selected ? " selected" : ""}${neighbour ? " neighbour" : ""}${dimmed ? " dimmed" : ""}" data-node-id="${escapeHtml(node.id)}">
            <span class="bar-label">${escapeHtml(node.label)}</span>
            <div class="bar-track" aria-hidden="true"><div class="bar-fill" style="width:${widthPct}"></div></div>
            <span class="bar-count">${node.connections.toLocaleString()}</span>
          </button>`;
      })
      .join("");

    elements.barChart.querySelectorAll("[data-node-id]").forEach((button) => {
      button.addEventListener("click", () => selectNode(button.dataset.nodeId));
    });
  }

  

  function setSearchStatus(message, isError = false) {
    if (!elements.searchStatus) return;
    elements.searchStatus.textContent = message || "";
    elements.searchStatus.classList.toggle("error", isError);
    elements.searchStatus.hidden = !message;
  }

  function setDataInfoOpen(open) {
    if (!elements.dataInfo || !elements.dataInfoBtn) return;
    elements.dataInfo.hidden = !open;
    elements.dataInfoBtn.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function updateDataInfoLinks(node) {
    const name = node?.label || "";
    if (elements.dataRemovalLink) {
      elements.dataRemovalLink.href = dataRemovalMailto(name);
    }
    if (elements.dataFixLink) {
      elements.dataFixLink.href = dataCorrectionMailto(name);
    }
  }

  function renderGraph({ force = false } = {}) {
    updateDimensions();
    const graph = prepareGraph();
    const nextRenderKey = graphRenderSignature(graph.nodes, graph.links);
    if (!force && hasRendered && nextRenderKey === graphRenderKey) {
      updateHighlight();
      return;
    }

    graphRenderKey = nextRenderKey;
    const fitGeneration = ++viewFitGeneration;

    graphLayer.selectAll("*").remove();
    labelOverlay.selectAll("*").remove();
    selectedLabelSelection = null;
    if (simulation) {
      simulation.on("end", null);
      simulation.stop();
    }

    graphNodes = graph.nodes;
    graphLinks = graph.links;
    radiusScale = buildRadiusScale(graphNodes);
    const centerX = width() / 2;
    const centerY = height() / 2;
    const largeGraph = graphNodes.length > 400;
    const isSearchLayout = Boolean(searchQuery && matchedNodeIds.size);

    if (isSearchLayout) {
      initializeSearchLayout(graphNodes, graphLinks, centerX, centerY);
    }

    linkSelection = graphLayer
      .append("g")
      .attr("class", "links")
      .selectAll("line")
      .data(graphLinks)
      .join("line");

    nodeSelection = graphLayer
      .append("g")
      .attr("class", "nodes")
      .selectAll("circle")
      .data(graphNodes)
      .join("circle")
      .attr("r", (d) => {
        const base = radiusScale(Math.max(1, d.connections));
        return isCoarsePointer ? base + 4 : base;
      })
      .attr("stroke", "#ffffff")
      .style("cursor", "pointer")
      .style("touch-action", "none")
      .on("pointerenter", (_, d) => {
        if (!isCoarsePointer && !selectedNodeId) showNodeCard(d);
      })
      .call(nodeDrag());

    labelSelection = graphLayer.append("g").attr("class", "labels").selectAll("text").data([]).join("text");

    simulation = d3
      .forceSimulation(graphNodes)
      .alpha(isSearchLayout ? 0.65 : 0.12)
      .alphaDecay(
        isSearchLayout ? (largeGraph ? 0.11 : 0.09) : largeGraph ? 0.14 : 0.11
      )
      .alphaMin(0.03)
      .velocityDecay(isSearchLayout ? (largeGraph ? 0.78 : 0.74) : largeGraph ? 0.9 : 0.84)
      .force(
        "link",
        d3
          .forceLink(graphLinks)
          .id((d) => d.id)
          .distance(isSearchLayout ? (largeGraph ? 120 : 130) : largeGraph ? 100 : 120)
          .strength(isSearchLayout ? (largeGraph ? 0.16 : 0.18) : largeGraph ? 0.08 : 0.1)
      )
      .force(
        "charge",
        d3
          .forceManyBody()
          .strength(
            isSearchLayout
              ? largeGraph
                ? -34
                : -52
              : largeGraph
                ? -85
                : isCoarsePointer
                  ? -130
                  : -165
          )
      )
      .force("center", d3.forceCenter(centerX, centerY))
      .force(
        "collide",
        d3
          .forceCollide()
          .radius((d) => nodeCollisionRadius(d))
          .strength(0.92)
          .iterations(3)
      )
      .force(
        "topicCluster",
        isSearchLayout ? forceTopicCluster(matchedNodeIds, largeGraph ? 0.08 : 0.12) : null
      )
      .force(
        "x",
        isSearchLayout
          ? d3.forceX(centerX).strength((d) => (matchedNodeIds.has(d.id) ? 0.06 : 0.025))
          : null
      )
      .force(
        "y",
        isSearchLayout
          ? d3.forceY(centerY).strength((d) => (matchedNodeIds.has(d.id) ? 0.06 : 0.025))
          : null
      )
      .on("tick", () => {
        linkSelection
          .attr("x1", (d) => d.source.x)
          .attr("y1", (d) => d.source.y)
          .attr("x2", (d) => d.target.x)
          .attr("y2", (d) => d.target.y);
        nodeSelection.attr("cx", (d) => d.x).attr("cy", (d) => d.y);
        if (labelSelection) {
          labelSelection.attr("x", (d) => d.x).attr("y", (d) => d.y);
        }
        if (selectedLabelSelection) {
          selectedLabelSelection.attr("x", (d) => d.x).attr("y", (d) => d.y);
        }
      })
      .on("end", () => {
        if (fitGeneration !== viewFitGeneration) return;
        simulation?.stop();
        maybeCenterSelectedNode();
      });

    renderLegend(graphNodes, radiusScale);
    updateHighlight();
    hasRendered = true;
  }

  function nodeDrag() {
    return d3
      .drag()
      .touchable(true)
      .clickDistance(isCoarsePointer ? 12 : 4)
      .on("start", (event, d) => {
        event.sourceEvent?.stopPropagation?.();
        dragMoved = false;
        if (!event.active && simulation) simulation.alphaTarget(0.03).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on("drag", (event, d) => {
        dragMoved = dragMoved || Math.abs(event.dx) > 1 || Math.abs(event.dy) > 1;
        const transform = d3.zoomTransform(svg.node());
        d.fx = (event.x - transform.x) / transform.k;
        d.fy = (event.y - transform.y) / transform.k;
      })
      .on("end", (event, d) => {
        if (!event.active && simulation) simulation.alphaTarget(0);
        if (!dragMoved) {
          selectNode(d.id);
        }
        d.fx = null;
        d.fy = null;
      });
  }

  function resolveTalkIdForEntry(entry) {
    return resolveTalkId(entry, talksData, selectedSpeakerName);
  }

  function findNetworkNodeByAuthorName(name, personKey = "") {
    const trimmed = String(name || "").trim();
    if (!trimmed && !isRegistryPersonKey(personKey)) return null;
    if (isRegistryPersonKey(personKey)) {
      const byKey = network.individual.nodes.find((item) => item.person_key === personKey);
      if (byKey) return byKey;
    }
    const keys = new Set(personLookupKeys(trimmed, personKey));
    const matches = network.individual.nodes.filter((item) => {
      if (trimmed && item.label === trimmed) return true;
      return personLookupKeys(item.label, item.person_key).some((key) => keys.has(key));
    });
    if (!matches.length) return null;
    if (isRegistryPersonKey(personKey)) {
      return matches.find((item) => item.person_key === personKey) || null;
    }
    if (matches.length === 1) return matches[0];
    return null;
  }

  function renderTalkAuthorsHtml(authors) {
    const list = (authors || []).map((name) => String(name || "").trim()).filter(Boolean);
    if (!list.length) return "";

    return list
      .map((name, index) => {
        const separator = index > 0 ? '<span class="network-talk-author-sep">, </span>' : "";
        const personKey = resolveDelegatePersonKey(name) || "";
        const node = findNetworkNodeByAuthorName(name, personKey);
        if (node) {
          const selected = node.id === selectedNodeId ? " network-talk-author-selected" : "";
          const externalClass = isExternalCoauthor(node) ? " network-talk-author-external" : "";
          return `${separator}<a href="#" class="network-talk-author-link${externalClass}${selected}" data-node-id="${escapeHtml(node.id)}">${escapeHtml(name)}</a>`;
        }
        return `${separator}<span class="network-talk-author-plain">${escapeHtml(name)}</span>`;
      })
      .join("");
  }

  function refreshTalkAuthors() {
    if (!elements.talkAuthors || !selectedTalkId) return;
    const talk = talksById[selectedTalkId];
    if (!talk) return;
    elements.talkAuthors.innerHTML = renderTalkAuthorsHtml(talk.authors);
  }

  function setTalkListVisible(visible) {
    if (elements.cardTalks) elements.cardTalks.hidden = !visible;
    if (elements.talkBack) elements.talkBack.hidden = visible;
    elements.card?.classList.toggle("network-card--talk-open", !visible);
  }

  function clearTalkDetail() {
    selectedTalkId = null;
    similarRequestId += 1;
    setTalkListVisible(true);
    if (elements.talkDetail) {
      elements.talkDetail.hidden = true;
      if (elements.talkTitle) elements.talkTitle.textContent = "";
      setTalkFormatElement(elements.talkFormat, null);
      if (elements.talkAuthors) elements.talkAuthors.innerHTML = "";
      if (elements.talkAbstract) elements.talkAbstract.textContent = "";
    }
    if (elements.similarTalks) elements.similarTalks.hidden = true;
    if (elements.similarStatus) elements.similarStatus.textContent = "";
    if (elements.similarList) elements.similarList.innerHTML = "";
  }

  function scrollTalkDetailIntoView() {
    const target = elements.talkDetail;
    const container = elements.card;
    if (!target || !container || target.hidden) return;
    window.requestAnimationFrame(() => {
      if (container.scrollHeight > container.clientHeight) {
        const top = Math.max(0, target.offsetTop - 12);
        container.scrollTo({ top, behavior: "smooth" });
        return;
      }
      if (!isCoarsePointer) {
        target.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
    });
  }

  function setSimilarStatus(message, { isError = false } = {}) {
    if (!elements.similarStatus) return;
    elements.similarStatus.textContent = message;
    elements.similarStatus.classList.toggle("status-error", Boolean(isError));
  }

  function renderSimilarTalks(results) {
    if (!elements.similarList || !elements.similarTalks) return;
    if (!results.length) {
      elements.similarList.innerHTML = "";
      elements.similarTalks.hidden = true;
      return;
    }

    elements.similarList.innerHTML = results
      .map(({ talk, reason }) => {
        const authors = (talk.authors || []).join(", ");
        const reasonHtml = reason
          ? `<span class="network-similar-reason">${escapeHtml(reason)}</span>`
          : "";
        return `<li><button type="button" class="network-similar-btn" data-talk-id="${escapeHtml(talk.id)}"><strong>${escapeHtml(talk.title)}</strong>${authors ? `<span class="network-similar-authors">${escapeHtml(authors)}</span>` : ""}${reasonHtml}</button></li>`;
      })
      .join("");
    elements.similarTalks.hidden = false;
  }

  function loadSimilarTalks(talk) {
    if (!elements.similarTalks) return;
    const requestId = ++similarRequestId;
    elements.similarTalks.hidden = false;

    const results = similarityLookup.findSimilar(talk);
    if (requestId !== similarRequestId || selectedTalkId !== talk.id) return;
    if (!results.length) {
      setSimilarStatus("No similar talks found.", { isError: true });
      renderSimilarTalks([]);
      return;
    }
    setSimilarStatus("");
    renderSimilarTalks(results);
  }

  function showTalkDetail(talkId, { loadSimilar = false } = {}) {
    const normalizedTalkId = String(talkId || "").trim();
    const talk = talksById[normalizedTalkId];
    if (!talk || !elements.talkDetail) return;

    selectedTalkId = normalizedTalkId;
    setTalkListVisible(false);
    elements.talkDetail.hidden = false;
    if (elements.talkTitle) elements.talkTitle.textContent = talk.title;
    setTalkFormatElement(elements.talkFormat, talk);
    if (elements.talkAuthors) {
      elements.talkAuthors.innerHTML = renderTalkAuthorsHtml(talk.authors);
    }
    if (elements.talkAbstract) {
      elements.talkAbstract.textContent = talk.abstract || "No abstract available.";
    }

    if (loadSimilar) {
      loadSimilarTalks(talk);
    } else if (elements.similarTalks) {
      elements.similarTalks.hidden = true;
      setSimilarStatus("");
      if (elements.similarList) elements.similarList.innerHTML = "";
    }

    scrollTalkDetailIntoView();
  }

  function handleTalkSelection(talkId) {
    const normalizedTalkId = String(talkId || "").trim();
    if (!normalizedTalkId) return;
    if (normalizedTalkId === selectedTalkId) {
      scrollTalkDetailIntoView();
      return;
    }
    showTalkDetail(normalizedTalkId, { loadSimilar: true });
  }

  function updateNodeTalks(node) {
    if (!elements.cardTalks) return;
    if (!node || mode !== "individual") {
      selectedSpeakerName = "";
      selectedPersonKey = "";
      elements.cardTalks.hidden = true;
      elements.cardTalks.innerHTML = "";
      clearTalkDetail();
      return;
    }
    if (node.label !== selectedSpeakerName || node.person_key !== selectedPersonKey) {
      clearTalkDetail();
    }
    selectedSpeakerName = node.label;
    selectedPersonKey = String(node.person_key || "").trim();
    const titles = talksForNode(node, talkTitleIndex, talkTitleByPersonKey);
    if (!titles.length) {
      elements.cardTalks.hidden = true;
      elements.cardTalks.innerHTML = "";
      clearTalkDetail();
      return;
    }
    elements.cardTalks.innerHTML = renderTalkTitlesHtml(titles, {
      kicker: "Talks",
      selectedTalkId,
      resolveTalkId: resolveTalkIdForEntry,
    });
    elements.cardTalks.hidden = false;
    if (selectedTalkId) {
      setTalkListVisible(false);
    } else {
      setTalkListVisible(true);
    }
  }

  function showNodeCard(node) {
    elements.card.hidden = false;
    elements.cardTitle.textContent = resolveCanonicalPersonName(node.label, node.person_key);
    const snippet = matchSnippet(node);
    elements.cardMeta.textContent = snippet
      ? `${formatNodeMeta(node)} · ${snippet}`
      : formatNodeMeta(node);
    updateViewLinks(node);
    updateNodeContacts(node);
    updateNodeTalks(node);
    updateDataInfoLinks(node);
    setDataInfoOpen(false);
    pinSelectionCardToTop({ resetPanel: true });
  }

  let cardViewLinks = null;

  function ensureCardViewLinks() {
    if (cardViewLinks || !elements.cardMeta) return cardViewLinks;
    cardViewLinks = document.createElement("div");
    cardViewLinks.className = "view-links";
    cardViewLinks.hidden = true;
    elements.cardMeta.insertAdjacentElement("afterend", cardViewLinks);
    cardViewLinks.addEventListener("click", (event) => {
      const button = event.target.closest("[data-show-on-map]");
      if (!button || !cardViewLinks.contains(button)) return;
      event.preventDefault();
      event.stopPropagation();
      elements.onShowOnMap?.(button.dataset.showOnMap, button.dataset.showOnMapSpeaker || "");
    });
    return cardViewLinks;
  }

  function updateViewLinks(node) {
    const links = ensureCardViewLinks();
    if (!links) return;
    if (!node) {
      links.hidden = true;
      links.innerHTML = "";
      return;
    }
    const affiliation = mode === "individual" ? node.affiliation : node.label;
    const locationId = findLocationIdByAffiliation(siteData.locations || [], affiliation);
    if (!locationId) {
      links.hidden = true;
      links.innerHTML = "";
      return;
    }
    const personName = mode === "individual" ? node.label : "";
    links.hidden = false;
    links.innerHTML = `<button type="button" class="btn-ghost btn-small cross-view-link" data-show-on-map="${escapeHtml(locationId)}" data-show-on-map-speaker="${escapeHtml(personName)}">Show on map</button>`;
  }

  function clearSelection() {
    selectedNodeId = null;
    pendingNodeCenter = false;
    clearTalkDetail();
    renderGraph();
  }

  function selectNode(nodeId) {
    selectedNodeId = nodeId;
    pendingNodeCenter = true;
    renderGraph();
  }

  function previewSearch(query) {
    updateMatches(query);
    selectedNodeId = null;

    if (!searchQuery) {
      setSearchStatus("");
      renderGraph();
      return;
    }

    if (!matchedNodeIds.size) {
      setSearchStatus("No nodes matched that search.", true);
      renderGraph();
      return;
    }

    setSearchStatus(
      `${matchedNodeIds.size.toLocaleString()} match${matchedNodeIds.size === 1 ? "" : "es"} (matches always shown; co-authors fill remaining slots)`
    );
    renderGraph();
  }

  function applySearch(query) {
    updateMatches(query);
    selectedNodeId = null;

    if (!searchQuery) {
      setSearchStatus("");
      renderGraph();
      return;
    }

    if (!matchedNodeIds.size) {
      setSearchStatus("No nodes matched that search.", true);
      renderGraph();
      return;
    }

    setSearchStatus(
      `${matchedNodeIds.size.toLocaleString()} node${matchedNodeIds.size === 1 ? "" : "s"} matched (all matches shown; co-authors fill remaining slots)`
    );

    const firstMatch = currentGraph().nodes.find((node) => matchedNodeIds.has(node.id));
    if (firstMatch) {
      selectNode(firstMatch.id);
      return;
    }

    renderGraph();
  }

  function setNodeLimit(value) {
    const nextLimit = parseNodeLimit(value);
    if (nextLimit === nodeLimit) return;
    nodeLimit = nextLimit;
    renderGraph();
  }

  function buildSuggestions(query) {
    const trimmed = foldSearchText(query).trim();
    if (trimmed.length < 2) return [];

    return dedupeSearchHitsByPerson(
      currentGraph()
        .nodes.filter((node) => nodeMatchesSearch(node, trimmed))
        .sort((a, b) => b.connections - a.connections)
        .map((node) => ({
          label: node.label,
          detail: formatNodeMeta(node),
          query: node.label,
          nodeId: node.id,
          person_key: node.person_key,
          _name: node.label,
        })),
      (item) => item._name
    ).slice(0, 8);
  }

  function setMode(nextMode) {
    mode = nextMode;
    selectedNodeId = null;
    searchQuery = "";
    matchedNodeIds = new Set();
    userAdjustedZoom = false;
    elements.card.hidden = true;
    clearTalkDetail();
    updateNodeTalks(null);
    updateNodeContacts(null);
    setDataInfoOpen(false);
    if (elements.searchInput) elements.searchInput.value = "";
    setSearchStatus("");
    renderGraph();
  }

  function resetView() {
    clearSelection();
    resetZoom();
  }

  function resetZoom() {
    userAdjustedZoom = false;
    fitToView({ animate: true });
  }

  function updateDimensions() {
    const w = width();
    const h = height();
    svg.attr("viewBox", `0 0 ${w} ${h}`).attr("width", w).attr("height", h);
  }

  function resize() {
    placeNetworkCard();
    syncOnStageCardBounds();
    clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => {
      updateDimensions();
      if (!hasRendered) {
        renderGraph();
        return;
      }
      if (simulation) {
        const centerX = width() / 2;
        const centerY = height() / 2;
        simulation.force("center", d3.forceCenter(centerX, centerY));
        if (searchQuery && matchedNodeIds.size) {
          simulation.force("x", d3.forceX(centerX).strength((d) => (matchedNodeIds.has(d.id) ? 0.06 : 0.025)));
          simulation.force("y", d3.forceY(centerY).strength((d) => (matchedNodeIds.has(d.id) ? 0.06 : 0.025)));
        }
      }
    }, 150);
  }

  svg.call(zoom).on("dblclick.zoom", null);
  svg.on("click", (event) => {
    if (event.target === svg.node() || event.target?.nodeName === "svg") {
      clearSelection();
    }
  });

  if (elements.resetZoom) {
    elements.resetZoom.addEventListener("click", resetView);
  }
  if (elements.clearSelection) {
    elements.clearSelection.addEventListener("click", clearSelection);
  }
  if (elements.cardClear) {
    elements.cardClear.addEventListener("click", clearSelection);
  }

  placeNetworkCard();
  cardDesktopMq.addEventListener("change", () => {
    placeNetworkCard();
    if (selectedNodeId) updateSelectionUi();
  });
  if (elements.dataInfoBtn && elements.dataInfo) {
    elements.dataInfoBtn.addEventListener("click", () => {
      setDataInfoOpen(elements.dataInfo.hidden);
    });
  }
  if (elements.card) {
    elements.card.addEventListener("click", (event) => {
      const copyButton = event.target.closest("[data-copy-name]");
      if (copyButton && elements.cardContacts?.contains(copyButton)) {
        event.preventDefault();
        event.stopPropagation();
        const text = delegateDetailsText(
          copyButton.dataset.copyName,
          copyButton.dataset.copyAffiliation
        );
        void copyTextToClipboard(text, copyButton);
        return;
      }
      const copyEmailButton = event.target.closest("[data-copy-email]");
      if (copyEmailButton && elements.cardContacts?.contains(copyEmailButton)) {
        event.preventDefault();
        event.stopPropagation();
        void copyTextToClipboard(copyEmailButton.dataset.copyEmail, copyEmailButton);
        return;
      }
      const showEmailButton = event.target.closest(".network-contact-show-email");
      if (showEmailButton && elements.cardContacts?.contains(showEmailButton)) {
        event.preventDefault();
        event.stopPropagation();
        const name = showEmailButton.dataset.contactName || "";
        const affiliation = showEmailButton.dataset.contactAffiliation || "";
        void fetchVerifiedEmail(name, affiliation, showEmailButton).then((email) => {
          if (!email) return;
          revealedContactEmails.set(contactRevealKey(name, affiliation), email);
          if (selectedNodeId) {
            const currentNode = graphNodes.find((node) => node.id === selectedNodeId);
            if (currentNode) updateNodeContacts(currentNode);
          }
        });
        return;
      }
      const authorLink = event.target.closest(".network-talk-author-link[data-node-id]");
      if (authorLink && elements.card.contains(authorLink)) {
        event.preventDefault();
        event.stopPropagation();
        selectNode(authorLink.dataset.nodeId);
        return;
      }
      const button = event.target.closest("[data-talk-id]");
      if (!button || !elements.card.contains(button)) return;
      event.preventDefault();
      event.stopPropagation();
      handleTalkSelection(button.dataset.talkId);
    });
  }
  if (elements.talkBack) {
    elements.talkBack.addEventListener("click", () => {
      clearTalkDetail();
      if (selectedSpeakerName && elements.cardTalks) {
        const titles = talksForNode(
          { label: selectedSpeakerName, person_key: selectedPersonKey },
          talkTitleIndex,
          talkTitleByPersonKey
        );
        elements.cardTalks.innerHTML = renderTalkTitlesHtml(titles, {
          kicker: "Talks",
          resolveTalkId: resolveTalkIdForEntry,
        });
      }
    });
  }

  function findNodeIdByName(name, personKey = "") {
    return findNetworkNodeByAuthorName(name, personKey)?.id || null;
  }

  renderSearchResults([]);

  return {
    setMode,
    getMode: () => mode,
    setNodeLimit,
    resize,
    resetZoom,
    clearSelection,
    previewSearch,
    applySearch,
    buildSuggestions,
    selectNode,
    findNodeIdByName,
  };
}
