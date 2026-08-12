import {
  affiliationMapKey,
  escapeHtml,
  haversineKm,
  resolveCanonicalPersonName,
  personKeyFromRecord,
  activateSuggestionAt,
  handleSuggestionListKeydown,
  buildPersonNameSearchHits,
} from "./utils.js";
import { OFFSET_API_URL, REQUIRE_DELEGATE_ID, SKIP_TURNSTILE, TURNSTILE_SITE_KEY } from "./config.js";

let offsetTurnstileWidgetId = null;
let offsetTurnstileToken = "";
let offsetTurnstilePending = null;
/** @type {"loading"|"challenge"|"ready"|"failed"} */
let offsetTurnstileState = "loading";
let offsetTurnstileFailureReason = "";

const TURNSTILE_READY_TIMEOUT_MS = 15_000;
const TURNSTILE_EXECUTE_TIMEOUT_MS = 25_000;
const TURNSTILE_SCRIPT_POLL_MS = 100;
const FETCH_TIMEOUT_MS = 25_000;

const TURNSTILE_LOAD_FAILED_MSG =
  "Security check could not load. If you use an ad blocker or VPN, try disabling it briefly, or submit for manual review below.";
const TURNSTILE_TIMEOUT_MSG =
  "Security check timed out. Check your connection and try again, or submit for manual review.";
const TURNSTILE_CHALLENGE_MSG = "Complete the security check above to register.";

function turnstileApiReady() {
  return typeof window.turnstile?.render === "function";
}

async function waitForTurnstileReady(timeoutMs = TURNSTILE_READY_TIMEOUT_MS) {
  if (turnstileApiReady()) return true;
  const started = Date.now();
  return new Promise((resolve) => {
    const timerId = window.setInterval(() => {
      if (turnstileApiReady()) {
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

function setOffsetTurnstileState(state, reason = "") {
  offsetTurnstileState = state;
  offsetTurnstileFailureReason = reason;
}

function offsetTurnstileActionEl() {
  return document.getElementById("emissions-offset-register-action");
}

function offsetTurnstileHintEl() {
  return document.getElementById("emissions-offset-turnstile-hint");
}

function syncOffsetTurnstileChrome() {
  const action = offsetTurnstileActionEl();
  if (!action) return;
  action.classList.remove(
    "emissions-offset-register-action--loading",
    "emissions-offset-register-action--challenge",
    "emissions-offset-register-action--ready",
    "emissions-offset-register-action--failed",
  );
  if (SKIP_TURNSTILE || !TURNSTILE_SITE_KEY) {
    action.classList.add("emissions-offset-register-action--ready");
    return;
  }
  action.classList.add(`emissions-offset-register-action--${offsetTurnstileState}`);

  const hint = offsetTurnstileHintEl();
  if (!hint) return;
  if (offsetTurnstileState === "challenge") {
    hint.textContent = TURNSTILE_CHALLENGE_MSG;
    hint.hidden = false;
  } else if (offsetTurnstileState === "failed") {
    hint.textContent = offsetTurnstileFailureReason || TURNSTILE_LOAD_FAILED_MSG;
    hint.hidden = false;
  } else {
    hint.hidden = true;
  }
}

async function fetchJsonWithTimeout(url, options = {}, timeoutMs = FETCH_TIMEOUT_MS) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    const payload = await response.json().catch(() => ({}));
    return { response, payload };
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function finishOffsetTurnstilePending(token = "") {
  if (!offsetTurnstilePending) return;
  const { resolve } = offsetTurnstilePending;
  offsetTurnstilePending = null;
  resolve(token);
}

function offsetTurnstileMountEl() {
  return document.getElementById("emissions-offset-turnstile");
}

function resetTurnstile() {
  if (offsetTurnstileWidgetId != null && window.turnstile) {
    try {
      window.turnstile.remove(offsetTurnstileWidgetId);
    } catch {
      /* widget may already be gone */
    }
  }
  offsetTurnstileWidgetId = null;
  offsetTurnstileToken = "";
  finishOffsetTurnstilePending("");
}

function mountOffsetTurnstile() {
  resetTurnstile();
  const mount = offsetTurnstileMountEl();
  if (!TURNSTILE_SITE_KEY || !window.turnstile || !mount) {
    setOffsetTurnstileState("failed", TURNSTILE_LOAD_FAILED_MSG);
    syncOffsetTurnstileChrome();
    return false;
  }
  setOffsetTurnstileState("challenge");
  syncOffsetTurnstileChrome();
  try {
    offsetTurnstileWidgetId = window.turnstile.render(mount, {
      sitekey: TURNSTILE_SITE_KEY,
      action: "offset-pledge",
      size: "flexible",
      theme: "light",
      // Always show the compact checkbox (not interaction-only, which stays
      // invisible when Cloudflare auto-passes low-risk visitors).
      appearance: "always",
      callback: (token) => {
        offsetTurnstileToken = token;
        setOffsetTurnstileState("ready");
        syncOffsetTurnstileChrome();
        finishOffsetTurnstilePending(token);
      },
      "expired-callback": () => {
        offsetTurnstileToken = "";
        setOffsetTurnstileState("challenge");
        syncOffsetTurnstileChrome();
        finishOffsetTurnstilePending("");
      },
      "error-callback": () => {
        offsetTurnstileToken = "";
        setOffsetTurnstileState("failed", TURNSTILE_LOAD_FAILED_MSG);
        syncOffsetTurnstileChrome();
        finishOffsetTurnstilePending("");
      },
    });
    return true;
  } catch (error) {
    offsetTurnstileWidgetId = null;
    console.warn("Turnstile mount failed:", error);
    setOffsetTurnstileState("failed", TURNSTILE_LOAD_FAILED_MSG);
    syncOffsetTurnstileChrome();
    return false;
  }
}

function offsetTurnstileResponse() {
  if (offsetTurnstileToken) return offsetTurnstileToken;
  if (offsetTurnstileWidgetId == null || !window.turnstile?.getResponse) return "";
  return window.turnstile.getResponse(offsetTurnstileWidgetId) || "";
}

async function ensureOffsetTurnstileToken() {
  if (offsetTurnstileState === "ready") {
    const existing = offsetTurnstileResponse();
    if (existing) return existing;
  }

  if (offsetTurnstileWidgetId == null) {
    setOffsetTurnstileState("loading");
    syncOffsetTurnstileChrome();
    const ready = await waitForTurnstileReady();
    if (!ready) {
      setOffsetTurnstileState("failed", TURNSTILE_LOAD_FAILED_MSG);
      syncOffsetTurnstileChrome();
      return "";
    }
    if (!mountOffsetTurnstile()) return "";
  }

  const cached = offsetTurnstileResponse();
  if (cached) {
    setOffsetTurnstileState("ready");
    syncOffsetTurnstileChrome();
    return cached;
  }

  // appearance "always" challenges on render — wait for the callback, don't call execute().
  setOffsetTurnstileState("challenge");
  syncOffsetTurnstileChrome();

  return new Promise((resolve) => {
    const timeoutId = window.setTimeout(() => {
      const token = offsetTurnstileResponse();
      if (token) {
        setOffsetTurnstileState("ready");
        syncOffsetTurnstileChrome();
        resolve(token);
        return;
      }
      setOffsetTurnstileState("failed", TURNSTILE_TIMEOUT_MSG);
      syncOffsetTurnstileChrome();
      finishOffsetTurnstilePending("");
      resolve("");
    }, TURNSTILE_EXECUTE_TIMEOUT_MS);

    offsetTurnstilePending = {
      resolve: (token) => {
        window.clearTimeout(timeoutId);
        if (token) {
          setOffsetTurnstileState("ready");
          syncOffsetTurnstileChrome();
        }
        resolve(token);
      },
    };
  });
}

async function initOffsetTurnstile(onStateChange) {
  if (!TURNSTILE_SITE_KEY || SKIP_TURNSTILE) {
    setOffsetTurnstileState("ready");
    syncOffsetTurnstileChrome();
    onStateChange?.();
    return;
  }

  setOffsetTurnstileState("loading");
  syncOffsetTurnstileChrome();

  const ready = await waitForTurnstileReady();
  if (!ready) {
    setOffsetTurnstileState("failed", TURNSTILE_LOAD_FAILED_MSG);
    syncOffsetTurnstileChrome();
    onStateChange?.();
    return;
  }

  if (mountOffsetTurnstile()) {
    onStateChange?.();
  } else {
    onStateChange?.();
  }
}

const STATIC_REGISTRATIONS_URL = "data/offset-registrations.json";
const POLL_INTERVAL_MS = 5_000;
const OFFSET_GREEN = "#2d8a4e";
function emptyAggregate() {
  return { counts: { speakers: {}, delegates: {} }, totals: { speakers: 0, delegates: 0 } };
}

function normalizeAggregate(payload) {
  const aggregate = emptyAggregate();
  for (const pool of ["speakers", "delegates"]) {
    const counts = payload?.counts?.[pool];
    if (counts && typeof counts === "object") {
      for (const [key, value] of Object.entries(counts)) {
        if (Number.isFinite(value) && value > 0) aggregate.counts[pool][key] = value;
      }
    }
    const total = payload?.totals?.[pool];
    aggregate.totals[pool] = Number.isFinite(total) && total > 0 ? total : 0;
  }
  return aggregate;
}

function aggregateSignature(aggregate) {
  return JSON.stringify(aggregate);
}

function stableAttendeeId(name, locationId) {
  const key = `${name.trim().toLowerCase()}|${locationId}`;
  let hash = 2166136261;
  for (let index = 0; index < key.length; index += 1) {
    hash ^= key.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `offset-${(hash >>> 0).toString(16).padStart(8, "0")}`;
}

export function attendeeDedupeKey(name, affiliation) {
  return `${String(name).trim().toLowerCase()}|${affiliationMapKey(affiliation)}`;
}

function attendeeIdentityKey(attendee) {
  const registryKey = personKeyFromRecord(attendee);
  if (registryKey) return registryKey;
  return attendeeDedupeKey(attendee.name, attendee.affiliation);
}

export function buildEmissionsAttendeesFromSite(siteLocations, emissionsLocations, exportedAttendees = []) {
  if (exportedAttendees?.length) {
    const seen = new Set();
    return exportedAttendees
      .filter((attendee) => {
        const key = attendeeIdentityKey(attendee);
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .map((attendee) => {
        const registryKey = personKeyFromRecord(attendee);
        return {
          ...attendee,
          person_key: registryKey || attendee.person_key || "",
          name: resolveCanonicalPersonName(attendee.name, registryKey),
        };
      })
      .sort((left, right) =>
        left.name.localeCompare(right.name, undefined, { sensitivity: "base" })
      );
  }

  const travelLocations = emissionsLocations.filter((location) => location.co2e_kg > 0);
  const seen = new Set();
  const attendees = [];

  function emissionsLocationForSite(siteLocation) {
    const key = affiliationMapKey(siteLocation.affiliation);
    const candidates = travelLocations.filter(
      (location) => affiliationMapKey(location.affiliation) === key
    );
    if (!candidates.length) return null;
    if (candidates.length === 1) return candidates[0];
    return candidates.sort((left, right) => {
      const leftDistance = haversineKm(
        siteLocation.lat,
        siteLocation.lon,
        left.lat,
        left.lon
      );
      const rightDistance = haversineKm(
        siteLocation.lat,
        siteLocation.lon,
        right.lat,
        right.lon
      );
      return leftDistance - rightDistance;
    })[0];
  }

  for (const siteLocation of siteLocations) {
    const emissionsLocation = emissionsLocationForSite(siteLocation);
    if (!emissionsLocation) continue;

    for (const speaker of siteLocation.speaker_details?.length
      ? siteLocation.speaker_details
      : (siteLocation.speakers || []).map((name) => ({ name }))) {
      const trimmed = String(speaker.name || speaker).trim();
      if (!trimmed) continue;
      const registryKey = personKeyFromRecord(speaker);
      const identityKey = registryKey || attendeeDedupeKey(trimmed, emissionsLocation.affiliation);
      if (seen.has(identityKey)) continue;
      seen.add(identityKey);
      const displayName = resolveCanonicalPersonName(trimmed, registryKey);
      attendees.push({
        id: stableAttendeeId(displayName, emissionsLocation.id),
        name: displayName,
        person_key: registryKey || "",
        affiliation: emissionsLocation.affiliation,
        location_id: emissionsLocation.id,
        co2e_kg: emissionsLocation.co2e_per_speaker_kg,
      });
    }
  }

  return attendees.sort((left, right) =>
    left.name.localeCompare(right.name, undefined, { sensitivity: "base" })
  );
}

export function createOffsetTracker({
  elements,
  getAttendees,
  getHeadline,
  getPool,
  isSpeakerAttendee,
  onChange,
  onRegisterSuccess,
  apiUrl = OFFSET_API_URL,
  requireDelegateId = REQUIRE_DELEGATE_ID,
}) {
  let attendees = [];
  let attendeeById = new Map();
  let selectedAttendeeId = null;
  let searchQuery = "";
  let pollTimer = null;
  let loadError = "";
  let statusMessage = "";
  let statusIsError = false;
  let statusIsSuccess = false;
  let delegateIdInput = "";
  let delegateIdErrorMessage = "";
  let aggregate = emptyAggregate();
  let offsetCountByAffiliation = new Map();
  let clusterAttendeeCounts = new Map();
  let clusterOffsetCounts = new Map();
  const pendingRegistrationIds = new Set();

  function activePool() {
    return getPool?.() === "delegates" ? "delegates" : "speakers";
  }

  function rebuildOffsetCounts() {
    offsetCountByAffiliation = new Map();
    const pools =
      activePool() === "delegates" ? ["speakers", "delegates"] : ["speakers"];
    for (const pool of pools) {
      for (const [key, value] of Object.entries(aggregate.counts[pool])) {
        offsetCountByAffiliation.set(key, (offsetCountByAffiliation.get(key) || 0) + value);
      }
    }
    rebuildClusterOffsetCounts();
  }

  function rebuildClusterOffsetCounts() {
    clusterAttendeeCounts = new Map();
    for (const attendee of attendees) {
      const clusterId = attendee.country_cluster_id;
      if (!clusterId) continue;
      clusterAttendeeCounts.set(clusterId, (clusterAttendeeCounts.get(clusterId) || 0) + 1);
    }

    clusterOffsetCounts = new Map();
    for (const [affiliationKey, count] of offsetCountByAffiliation.entries()) {
      const matched = attendees.filter(
        (attendee) => affiliationMapKey(attendee.affiliation) === affiliationKey
      );
      if (!matched.length) continue;
      const byCluster = new Map();
      for (const attendee of matched) {
        const clusterId = attendee.country_cluster_id;
        if (!clusterId) continue;
        byCluster.set(clusterId, (byCluster.get(clusterId) || 0) + 1);
      }
      for (const [clusterId, clusterPeople] of byCluster.entries()) {
        const allocated = count * (clusterPeople / matched.length);
        clusterOffsetCounts.set(clusterId, (clusterOffsetCounts.get(clusterId) || 0) + allocated);
      }
    }
  }

  function offsetShareForCluster(clusterId) {
    if (!clusterId) return 0;
    const total = clusterAttendeeCounts.get(clusterId) || 0;
    if (!total) return 0;
    const offsets = clusterOffsetCounts.get(clusterId) || 0;
    return Math.min(1, offsets / total);
  }

  async function loadRegistrations() {
    loadError = "";
    if (apiUrl) {
      try {
        const { response, payload } = await fetchJsonWithTimeout(apiUrl, { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        aggregate = normalizeAggregate(payload);
        return;
      } catch (error) {
        loadError = "Could not refresh live totals.";
        console.warn("Offset API unavailable:", error);
      }
    }

    try {
      const { response, payload } = await fetchJsonWithTimeout(STATIC_REGISTRATIONS_URL, {
        cache: "no-store",
      });
      if (!response.ok) return;
      aggregate = normalizeAggregate(payload);
    } catch {
      aggregate = emptyAggregate();
    }
  }

  function refreshAttendees() {
    attendees = getAttendees();
    attendeeById = new Map(attendees.map((attendee) => [attendee.id, attendee]));
    rebuildOffsetCounts();
    render();
  }

  function offsetShareForLocation(locationId, travelAttendees, affiliation) {
    if (!locationId || !travelAttendees) return 0;
    const affiliationKey = affiliationMapKey(affiliation);
    if (!affiliationKey) return 0;
    const count = offsetCountByAffiliation.get(affiliationKey) || 0;
    return Math.min(1, count / travelAttendees);
  }

  function stats() {
    const totalAttendees = getHeadline()?.attendees_estimated || attendees.length || 1;
    const registeredCount =
      aggregate.totals.speakers +
      (activePool() === "delegates" ? aggregate.totals.delegates : 0);
    const percent = totalAttendees ? (registeredCount / totalAttendees) * 100 : 0;
    return { registeredCount, totalAttendees, percent };
  }

  function closeSuggestions() {
    if (!elements.suggestions) return;
    elements.suggestions.innerHTML = "";
    elements.suggestions.classList.remove("open");
  }

  function syncSelectionFromQuery() {
    const query = searchQuery.trim();
    if (!query) {
      selectedAttendeeId = null;
      return;
    }
    const exact = attendees.find(
      (attendee) => attendee.name.toLowerCase() === query.toLowerCase()
    );
    selectedAttendeeId = exact ? exact.id : null;
  }

  function hasLockedSelection() {
    return Boolean(selectedAttendeeId && attendeeById.has(selectedAttendeeId));
  }

  function lockSelection(attendee) {
    if (!attendee) return;
    selectedAttendeeId = attendee.id;
    searchQuery = attendee.name;
    if (elements.query) elements.query.value = attendee.name;
    closeSuggestions();
  }

  function filteredAttendees() {
    const query = searchQuery.trim();
    if (query.length < 2) return [];
    // Same ranked name matching as the map search (aliases + token preference).
    return buildPersonNameSearchHits(attendees, query, { limit: 40 });
  }

  function renderSuggestions() {
    if (!elements.suggestions) return;
    const query = searchQuery.trim();
    if (query.length < 2 || hasLockedSelection()) {
      closeSuggestions();
      return;
    }

    const matches = filteredAttendees();
    if (!matches.length) {
      closeSuggestions();
      return;
    }

    elements.suggestions.innerHTML = "";
    for (const attendee of matches) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "suggestion";
      button.dataset.attendeeId = attendee.id;
      button.innerHTML = `${escapeHtml(attendee.name)}<small>${escapeHtml(attendee.affiliation)}</small>`;
      button.addEventListener("mousedown", (event) => {
        event.preventDefault();
        if (pendingRegistrationIds.has(attendee.id)) return;
        lockSelection(attendee);
        renderTracker();
        renderStatus();
      });
      elements.suggestions.appendChild(button);
    }
    elements.suggestions.classList.add("open");
    activateSuggestionAt(elements.suggestions, 0);
  }

  function normalizedDelegateId() {
    const raw = elements.delegateId?.value ?? delegateIdInput;
    return String(raw || "").replace(/\D/g, "").slice(0, 5);
  }

  function delegateIdReady() {
    return !requireDelegateId || /^\d{2,5}$/.test(normalizedDelegateId());
  }

  function beginRegistering(attendeeId) {
    pendingRegistrationIds.add(attendeeId);
    renderTracker();
  }

  function endRegistering(attendeeId) {
    pendingRegistrationIds.delete(attendeeId);
    renderTracker();
    renderDelegateIdError();
    renderStatus();
  }

  function clearOffsetForm() {
    if (elements.query) elements.query.value = "";
    if (elements.delegateId) elements.delegateId.value = "";
    searchQuery = "";
    delegateIdInput = "";
    selectedAttendeeId = null;
    closeSuggestions();
  }

  function applyRegistrationResult(result) {
    if (!result) return;
    if (result.error) {
      showRegistrationError(result.error, { underDelegateField: result.underDelegateField });
      return;
    }
    if (result.message) {
      clearDelegateIdError();
      setStatus(result.message, { success: true });
      if (result.clearForm) clearOffsetForm();
      render({ updateMap: result.updateMap ?? false });
    }
  }

  function showRegistrationError(message, { underDelegateField = false } = {}) {
    const text = String(message || "").trim();
    if (!text) return;
    if (underDelegateField) {
      setDelegateIdError(text);
      // Field error is the only visible message (status is also CSS-hidden).
      statusMessage = "";
      statusIsError = false;
      statusIsSuccess = false;
      if (elements.status) {
        elements.status.textContent = "";
        elements.status.hidden = true;
        elements.status.classList.remove("error", "success");
      }
    } else {
      clearDelegateIdError();
      setStatus(text, { error: true, success: false });
    }
    render({ updateMap: false });
  }

  function resolveSelectedAttendee() {
    if (selectedAttendeeId && attendeeById.has(selectedAttendeeId)) {
      return attendeeById.get(selectedAttendeeId);
    }
    const query = searchQuery.trim().toLowerCase();
    if (!query) return null;
    const exact = attendees.find((attendee) => attendee.name.toLowerCase() === query);
    if (exact) return exact;
    const matches = filteredAttendees();
    return matches.length === 1 ? matches[0] : null;
  }

  const DELEGATE_ID_ERROR =
    "Incorrect delegate ID. Check the code from your confirmation email.";

  function renderDelegateIdError() {
    const text = delegateIdErrorMessage;
    if (elements.delegateIdError) {
      elements.delegateIdError.textContent = text;
      if (text) elements.delegateIdError.removeAttribute("hidden");
      else elements.delegateIdError.setAttribute("hidden", "");
    }
    if (elements.delegateId) {
      elements.delegateId.setAttribute("aria-invalid", text ? "true" : "false");
    }
    elements.delegateField?.classList.toggle("field--error", Boolean(text));
    elements.form?.classList.toggle("emissions-offset-register--error", Boolean(text));
  }

  function setDelegateIdError(message) {
    delegateIdErrorMessage = String(message || "").trim();
    renderDelegateIdError();
  }

  function clearDelegateIdError() {
    setDelegateIdError("");
  }

  function renderStatus() {
    if (!elements.status) return;
    // Kept in a variable rather than written straight to the DOM so the
    // five-second poll cannot wipe a message the user has not read yet.
    const text = statusMessage || loadError;
    elements.status.textContent = text;
    elements.status.hidden = !text;
    elements.status.classList.toggle("error", statusIsError || Boolean(loadError));
    elements.status.classList.toggle("success", statusIsSuccess && !statusIsError && !loadError);
  }

  function setStatus(message, { error = false, success = false } = {}) {
    statusMessage = message;
    statusIsError = error;
    statusIsSuccess = success;
    renderStatus();
  }

  function turnstileAllowsSubmit() {
    if (SKIP_TURNSTILE || !TURNSTILE_SITE_KEY) return true;
    if (offsetTurnstileState === "ready" && offsetTurnstileResponse()) return true;
    if (offsetTurnstileState === "failed" && requireDelegateId && delegateIdReady()) return true;
    return false;
  }

  function renderTracker() {
    const { registeredCount, totalAttendees, percent } = stats();
    const isRegistering = pendingRegistrationIds.size > 0;
    if (elements.fill) {
      elements.fill.style.width = `${Math.min(100, percent)}%`;
    }
    if (elements.label) {
      const rounded = percent < 10 ? percent.toFixed(1) : Math.round(percent).toString();
      elements.label.innerHTML = `<strong>${rounded}%</strong> offset · <strong>${registeredCount.toLocaleString()}</strong> of ${totalAttendees.toLocaleString()} ${getHeadline()?.attendee_label || "delegates"}`;
    }
    if (elements.form) {
      elements.form.classList.toggle("emissions-offset-register--pending", isRegistering);
    }
    syncOffsetTurnstileChrome();
    if (elements.registerButton) {
      const attendee = resolveSelectedAttendee();
      const awaitingTurnstile =
        !SKIP_TURNSTILE &&
        TURNSTILE_SITE_KEY &&
        (offsetTurnstileState === "loading" || offsetTurnstileState === "challenge");
      elements.registerButton.disabled =
        isRegistering ||
        !attendee ||
        !delegateIdReady() ||
        !turnstileAllowsSubmit() ||
        awaitingTurnstile ||
        pendingRegistrationIds.has(attendee?.id);
      let label = "I've pledged";
      if (isRegistering) {
        label = "Registering…";
      } else if (awaitingTurnstile) {
        label = offsetTurnstileState === "loading" ? "Preparing…" : "Complete check above";
      } else if (
        offsetTurnstileState === "failed" &&
        requireDelegateId &&
        delegateIdReady()
      ) {
        label = "Submit for manual review";
      }
      elements.registerButton.textContent = label;
      elements.registerButton.setAttribute("aria-busy", isRegistering ? "true" : "false");
    }
  }

  function render({ updateMap = false } = {}) {
    renderSuggestions();
    renderDelegateIdError();
    renderStatus();
    renderTracker();
    if (updateMap) onChange?.();
  }

  async function persistRegistration(attendee, token, { verificationFallback = false } = {}) {
    try {
      const body = {
        id: attendee.id,
        name: attendee.name,
        affiliation_key: affiliationMapKey(attendee.affiliation || ""),
        pool: isSpeakerAttendee?.(attendee) === false ? "delegates" : "speakers",
        ...(requireDelegateId ? { delegate_id: normalizedDelegateId() } : {}),
      };
      if (verificationFallback) {
        body.verification_fallback = true;
      } else {
        body["cf-turnstile-response"] = token;
      }

      const { response, payload } = await fetchJsonWithTimeout(apiUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        offsetTurnstileToken = "";
        window.turnstile?.reset?.(offsetTurnstileWidgetId);
        const errorText = String(payload.error || "");
        const delegateMismatch =
          requireDelegateId && errorText.toLowerCase().includes("delegate id");
        const turnstileFailed =
          payload.code === "turnstile_failed" ||
          errorText.toLowerCase().includes("verification failed");
        if (
          turnstileFailed &&
          requireDelegateId &&
          delegateIdReady() &&
          !verificationFallback
        ) {
          return persistRegistration(attendee, "", { verificationFallback: true });
        }
        return {
          created: false,
          error: delegateMismatch
            ? DELEGATE_ID_ERROR
            : turnstileFailed
              ? "Security check failed on the server. Try again, or submit for manual review."
              : errorText || "Registration failed. Please try again.",
          underDelegateField: delegateMismatch,
        };
      }

      if (requireDelegateId && payload.delegate_verified !== true) {
        return {
          created: false,
          error:
            "This API is not checking delegate IDs. For local testing, use docker compose and point index.html at http://127.0.0.1:8080/api/offsets.",
          underDelegateField: true,
        };
      }

      const accepted = Boolean(payload.created);

      const pool = isSpeakerAttendee?.(attendee) === false ? "delegates" : "speakers";
      const beforeTotal =
        aggregate.totals.speakers +
        (activePool() === "delegates" ? aggregate.totals.delegates : 0);

      if (accepted && !payload.pending) {
        aggregate.totals[pool] += 1;
        const key = affiliationMapKey(attendee.affiliation || "");
        if (key) {
          aggregate.counts[pool][key] = (aggregate.counts[pool][key] || 0) + 1;
        }
        rebuildOffsetCounts();
      }

      let message;
      if (payload.pending) {
        message = `Thanks, ${attendee.name}! Your offset is logged and will be counted once checked.`;
      } else if (accepted) {
        message = payload.reactivated
          ? `Thanks, ${attendee.name}! Your offset is registered again.`
          : `Thanks, ${attendee.name}! Your offset is registered.`;
      } else {
        message = `${attendee.name} is already registered on the server.`;
      }

      offsetTurnstileToken = "";
      window.turnstile?.reset?.(offsetTurnstileWidgetId);

      void loadRegistrations()
        .then(() => {
          rebuildOffsetCounts();
          const afterTotal =
            aggregate.totals.speakers +
            (activePool() === "delegates" ? aggregate.totals.delegates : 0);
          if (accepted && !payload.pending && afterTotal < beforeTotal + 1) {
            aggregate.totals[pool] += 1;
            const key = affiliationMapKey(attendee.affiliation || "");
            if (key) {
              aggregate.counts[pool][key] = (aggregate.counts[pool][key] || 0) + 1;
            }
            rebuildOffsetCounts();
          }
          render({ updateMap: true });
        })
        .catch(() => {
          /* loadRegistrations handles its own errors */
        });

      return {
        created: accepted,
        message,
        clearForm: true,
        updateMap: true,
      };
    } catch (error) {
      offsetTurnstileToken = "";
      window.turnstile?.reset?.(offsetTurnstileWidgetId);
      const timedOut = error?.name === "AbortError";
      console.warn("Offset registration failed:", error);
      return {
        created: false,
        error: timedOut
          ? "Registration timed out. Check your connection and try again."
          : "Registration failed. Please try again.",
      };
    }
  }

  async function registerSelected() {
    const attendee = resolveSelectedAttendee();
    if (!attendee) {
      if (searchQuery.trim()) setStatus("Select your name from the suggestions.");
      return false;
    }
    if (pendingRegistrationIds.has(attendee.id)) {
      return false;
    }

    if (!apiUrl) {
      setStatus("Live registration API is not configured.");
      return false;
    }
    if (requireDelegateId && !delegateIdReady()) {
      setStatus("Enter your delegate ID from your welcome email.");
      return false;
    }

    let token = "local-dev";
    let verificationFallback = false;
    if (!SKIP_TURNSTILE && TURNSTILE_SITE_KEY) {
      token = offsetTurnstileResponse();
      if (!token) {
        setStatus("Verifying…");
        token = await ensureOffsetTurnstileToken();
      }
      if (!token) {
        if (requireDelegateId && delegateIdReady() && offsetTurnstileState === "failed") {
          verificationFallback = true;
          setStatus(
            "Security check unavailable — submitting your pledge for manual review…",
          );
        } else if (offsetTurnstileState === "challenge") {
          setStatus(TURNSTILE_CHALLENGE_MSG, { error: true });
          return false;
        } else {
          setStatus(offsetTurnstileFailureReason || TURNSTILE_LOAD_FAILED_MSG, {
            error: true,
          });
          return false;
        }
      }
    }

    selectedAttendeeId = attendee.id;
    beginRegistering(attendee.id);
    closeSuggestions();
    elements.query?.blur();

    try {
      const result = await persistRegistration(attendee, token, { verificationFallback });
      applyRegistrationResult(result);
      if (result?.created) onRegisterSuccess?.(attendee);
      return Boolean(result?.created);
    } finally {
      endRegistering(attendee.id);
    }
  }

  function bindEvents() {
    elements.query?.addEventListener("input", (event) => {
      searchQuery = event.target.value;
      syncSelectionFromQuery();
      statusMessage = "";
      statusIsError = false;
      statusIsSuccess = false;
      clearDelegateIdError();
      render();
    });

    elements.delegateId?.addEventListener("input", (event) => {
      const digits = String(event.target.value || "").replace(/\D/g, "").slice(0, 5);
      delegateIdInput = digits;
      if (elements.delegateId && elements.delegateId.value !== digits) {
        elements.delegateId.value = digits;
      }
      statusMessage = "";
      statusIsError = false;
      statusIsSuccess = false;
      clearDelegateIdError();
      renderTracker();
    });

    elements.query?.addEventListener("keydown", (event) => {
      if (
        handleSuggestionListKeydown(event, {
          container: elements.suggestions,
          onSelect: (button) => {
            const attendee = attendeeById.get(button.dataset.attendeeId);
            if (attendee && !pendingRegistrationIds.has(attendee.id)) {
              lockSelection(attendee);
              renderTracker();
              renderStatus();
            }
          },
          onClose: closeSuggestions,
        })
      ) {
        return;
      }
      if (event.key !== "Enter") return;
      if (hasLockedSelection()) return;
      event.preventDefault();
      if (searchQuery.trim()) setStatus("Select your name from the suggestions.");
    });

    elements.delegateId?.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      elements.form?.requestSubmit();
    });

    elements.query?.addEventListener("focus", () => {
      if (hasLockedSelection()) return;
      if (searchQuery.trim()) renderSuggestions();
    });

    document.addEventListener("click", (event) => {
      if (
        elements.suggestions &&
        !elements.suggestions.contains(event.target) &&
        event.target !== elements.query
      ) {
        closeSuggestions();
      }
    });

    elements.form?.addEventListener("submit", (event) => {
      event.preventDefault();
      void registerSelected();
    });

    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") {
        void loadRegistrations().then(() => {
          rebuildOffsetCounts();
          render({ updateMap: true });
        });
      }
    });
  }

  function startPolling() {
    if (!apiUrl || pollTimer) return;
    pollTimer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      const before = aggregateSignature(aggregate);
      void loadRegistrations().then(() => {
        const changed = before !== aggregateSignature(aggregate);
        rebuildOffsetCounts();
        render({ updateMap: changed });
      });
    }, POLL_INTERVAL_MS);
  }

  function stopPolling() {
    if (!pollTimer) return;
    window.clearInterval(pollTimer);
    pollTimer = null;
  }

  async function init() {
    if (elements.delegateField) {
      elements.delegateField.hidden = !requireDelegateId;
    }
    refreshAttendees();
    bindEvents();
    startPolling();
    render();
    void initOffsetTurnstile(() => render({ updateMap: false }));
    try {
      await loadRegistrations();
      rebuildOffsetCounts();
      render({ updateMap: true });
    } catch {
      /* loadRegistrations handles its own errors */
    }
  }

  return {
    init,
    stopPolling,
    refreshAttendees,
    offsetShareForLocation,
    offsetShareForCluster,
    stats,
    OFFSET_GREEN,
  };
}

export function circlePolygon(map, lon, lat, radiusPx, steps = 32) {
  if (!map || radiusPx <= 0) return null;
  const center = map.project([lon, lat]);
  const ring = [];

  for (let index = 0; index <= steps; index += 1) {
    const angle = (2 * Math.PI * index) / steps;
    const x = center.x + radiusPx * Math.cos(angle);
    const y = center.y + radiusPx * Math.sin(angle);
    const point = map.unproject([x, y]);
    ring.push([point.lng, point.lat]);
  }

  return ring;
}

export function pieSlicePolygon(map, lon, lat, radiusPx, fraction) {
  if (!map || fraction <= 0 || fraction >= 1) return null;
  const center = map.project([lon, lat]);
  const centerGeo = map.unproject([center.x, center.y]);
  const start = -Math.PI / 2;
  const end = start + fraction * Math.PI * 2;
  const steps = Math.max(8, Math.ceil(32 * fraction));
  const ring = [[centerGeo.lng, centerGeo.lat]];

  for (let index = 0; index <= steps; index += 1) {
    const angle = start + ((end - start) * index) / steps;
    const x = center.x + radiusPx * Math.cos(angle);
    const y = center.y + radiusPx * Math.sin(angle);
    const point = map.unproject([x, y]);
    ring.push([point.lng, point.lat]);
  }
  ring.push([centerGeo.lng, centerGeo.lat]);

  return ring;
}
