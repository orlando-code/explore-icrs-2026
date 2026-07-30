import { affiliationMapKey, escapeHtml, haversineKm } from "./utils.js";
import { OFFSET_API_URL, REQUIRE_DELEGATE_ID, TURNSTILE_SITE_KEY } from "./config.js";

let offsetTurnstileWidgetId = null;
let offsetTurnstileToken = "";
let offsetTurnstilePending = null;

const TURNSTILE_READY_TIMEOUT_MS = 12_000;
const TURNSTILE_EXECUTE_TIMEOUT_MS = 20_000;
const FETCH_TIMEOUT_MS = 25_000;

async function waitForTurnstileReady(timeoutMs = TURNSTILE_READY_TIMEOUT_MS) {
  if (!window.turnstile) return false;
  if (!window.turnstile.ready) return true;
  return new Promise((resolve) => {
    let settled = false;
    const finish = (ready) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timerId);
      resolve(ready);
    };
    const timerId = window.setTimeout(() => finish(Boolean(window.turnstile)), timeoutMs);
    try {
      window.turnstile.ready(() => finish(true));
    } catch {
      finish(Boolean(window.turnstile));
    }
  });
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
  let mount = document.getElementById("emissions-offset-turnstile");
  if (!mount) {
    mount = document.createElement("div");
    mount.id = "emissions-offset-turnstile";
    mount.className = "turnstile-mount";
    mount.setAttribute("aria-hidden", "true");
    document.body.appendChild(mount);
  }
  return mount;
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
  if (!TURNSTILE_SITE_KEY || !window.turnstile) return;
  try {
    offsetTurnstileWidgetId = window.turnstile.render(mount, {
      sitekey: TURNSTILE_SITE_KEY,
      action: "turnstile-spin-v2",
      size: "invisible",
      callback: (token) => {
        offsetTurnstileToken = token;
        finishOffsetTurnstilePending(token);
      },
      "expired-callback": () => {
        offsetTurnstileToken = "";
        finishOffsetTurnstilePending("");
      },
      "error-callback": () => {
        offsetTurnstileToken = "";
        finishOffsetTurnstilePending("");
      },
    });
  } catch (error) {
    offsetTurnstileWidgetId = null;
    console.warn("Turnstile mount failed:", error);
  }
}

function offsetTurnstileResponse() {
  if (offsetTurnstileToken) return offsetTurnstileToken;
  if (offsetTurnstileWidgetId == null || !window.turnstile?.getResponse) return "";
  return window.turnstile.getResponse(offsetTurnstileWidgetId) || "";
}

async function ensureOffsetTurnstileToken() {
  const existing = offsetTurnstileResponse();
  if (existing) return existing;
  if (offsetTurnstileWidgetId == null) {
    const ready = await waitForTurnstileReady();
    if (!ready) return "";
    mountOffsetTurnstile();
  }
  if (offsetTurnstileWidgetId == null || !window.turnstile?.execute) return "";

  return new Promise((resolve) => {
    const timeoutId = window.setTimeout(() => {
      finishOffsetTurnstilePending(offsetTurnstileResponse());
    }, TURNSTILE_EXECUTE_TIMEOUT_MS);

    offsetTurnstilePending = {
      resolve: (token) => {
        window.clearTimeout(timeoutId);
        resolve(token);
      },
    };

    try {
      window.turnstile.execute(offsetTurnstileWidgetId);
    } catch {
      window.clearTimeout(timeoutId);
      finishOffsetTurnstilePending("");
    }
  });
}

function initOffsetTurnstile() {
  if (!TURNSTILE_SITE_KEY || offsetTurnstileWidgetId != null) return;

  const tryMount = () => {
    void waitForTurnstileReady().then((ready) => {
      if (ready && offsetTurnstileWidgetId == null) mountOffsetTurnstile();
    });
  };

  if (window.turnstile) {
    tryMount();
    return;
  }

  let attempts = 0;
  const timerId = window.setInterval(() => {
    attempts += 1;
    if (window.turnstile) {
      window.clearInterval(timerId);
      tryMount();
    } else if (attempts >= 150) {
      window.clearInterval(timerId);
    }
  }, 100);
}

const STATIC_REGISTRATIONS_URL = "data/offset-registrations.json";
const POLL_INTERVAL_MS = 5_000;
const OFFSET_GREEN = "#2d8a4e";
const LOCAL_REGISTRATIONS_KEY = "icrs-offset-registered";

/** Person keys this browser has registered. The server publishes only counts,
 *  so a visitor's own registration is remembered here rather than looked up. */
function loadLocalRegistrations() {
  try {
    const raw = window.localStorage?.getItem(LOCAL_REGISTRATIONS_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(parsed) ? parsed.filter((item) => typeof item === "string") : []);
  } catch {
    return new Set();
  }
}

function saveLocalRegistrations(keys) {
  try {
    window.localStorage?.setItem(LOCAL_REGISTRATIONS_KEY, JSON.stringify([...keys]));
  } catch {
    /* private browsing or storage disabled — the session still works */
  }
}

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

function stableAttendeeId(name, locationId) {
  const key = `${name.trim().toLowerCase()}|${locationId}`;
  let hash = 2166136261;
  for (let index = 0; index < key.length; index += 1) {
    hash ^= key.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `offset-${(hash >>> 0).toString(16).padStart(8, "0")}`;
}

export function personKey(name, affiliation) {
  return `${String(name).trim().toLowerCase()}|${affiliationMapKey(affiliation)}`;
}

export function buildEmissionsAttendeesFromSite(siteLocations, emissionsLocations, exportedAttendees = []) {
  if (exportedAttendees?.length) {
    return exportedAttendees
      .slice()
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

    for (const name of siteLocation.speakers || []) {
      const trimmed = String(name).trim();
      if (!trimmed) continue;
      const dedupeKey = `${trimmed.toLowerCase()}|${emissionsLocation.id}`;
      if (seen.has(dedupeKey)) continue;
      seen.add(dedupeKey);
      attendees.push({
        id: stableAttendeeId(trimmed, emissionsLocation.id),
        name: trimmed,
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
  let delegateIdInput = "";
  let aggregate = emptyAggregate();
  let offsetCountByAffiliation = new Map();
  const localRegistrations = loadLocalRegistrations();
  const pendingRegistrationIds = new Set();

  function activePool() {
    return getPool?.() === "delegates" ? "delegates" : "speakers";
  }

  /** True only for people this browser registered. Other delegates' status is
   *  no longer published, so it is not knowable here. */
  function isRegistered(attendee) {
    if (!attendee) return false;
    return localRegistrations.has(personKey(attendee.name, attendee.affiliation));
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
        loadError = "Could not refresh live offset totals.";
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

  function filteredAttendees() {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return attendees.slice(0, 40);
    return attendees
      .filter((attendee) => {
        const haystack = `${attendee.name} ${attendee.affiliation}`.toLowerCase();
        return haystack.includes(query);
      })
      .slice(0, 40);
  }

  function renderSuggestions() {
    if (!elements.suggestions) return;
    const matches = filteredAttendees();
    if (!searchQuery.trim() || !matches.length) {
      elements.suggestions.innerHTML = "";
      elements.suggestions.classList.remove("open");
      return;
    }

    elements.suggestions.innerHTML = "";
    for (const attendee of matches) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "suggestion";
      button.dataset.attendeeId = attendee.id;
      const alreadyRegistered = isRegistered(attendee);
      button.innerHTML = `${escapeHtml(attendee.name)}<small>${escapeHtml(attendee.affiliation)}${
        alreadyRegistered ? " · you registered this" : ""
      }</small>`;
      button.addEventListener("mousedown", (event) => {
        event.preventDefault();
        if (isRegistered(attendee) || pendingRegistrationIds.has(attendee.id)) return;
        selectedAttendeeId = attendee.id;
        if (elements.query) elements.query.value = attendee.name;
        elements.suggestions.classList.remove("open");
        renderTracker();
        renderStatus();
      });
      elements.suggestions.appendChild(button);
    }
    elements.suggestions.classList.add("open");
  }

  function normalizedDelegateId(value = delegateIdInput) {
    return String(value || "").replace(/\D/g, "").slice(0, 5);
  }

  function delegateIdReady() {
    return !requireDelegateId || /^\d{5}$/.test(normalizedDelegateId());
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

  function renderStatus() {
    if (!elements.status) return;
    // Kept in a variable rather than written straight to the DOM so the
    // five-second poll cannot wipe a message the user has not read yet.
    elements.status.textContent = statusMessage || loadError;
  }

  function setStatus(message) {
    statusMessage = message;
    renderStatus();
  }

  function renderTracker() {
    const { registeredCount, totalAttendees, percent } = stats();
    const isRegistering = pendingRegistrationIds.size > 0;
    if (elements.fill) {
      elements.fill.style.width = `${Math.min(100, percent)}%`;
    }
    if (elements.label) {
      const rounded = percent < 10 ? percent.toFixed(1) : Math.round(percent).toString();
      elements.label.innerHTML = `<strong>${rounded}%</strong> offset · <strong>${registeredCount.toLocaleString()}</strong> of ${totalAttendees.toLocaleString()} ${getHeadline()?.attendee_label || "delegates"} offsetted`;
    }
    if (elements.form) {
      elements.form.classList.toggle("emissions-offset-register--pending", isRegistering);
    }
    if (elements.status) {
      elements.status.classList.toggle("status--pending", isRegistering);
    }
    if (elements.registerButton) {
      const attendee = resolveSelectedAttendee();
      elements.registerButton.disabled =
        isRegistering ||
        !attendee ||
        !delegateIdReady() ||
        isRegistered(attendee) ||
        pendingRegistrationIds.has(attendee.id);
      elements.registerButton.textContent = isRegistering ? "Registering…" : "I've offset my travel";
      elements.registerButton.setAttribute("aria-busy", isRegistering ? "true" : "false");
    }
  }

  function render({ updateMap = false } = {}) {
    renderSuggestions();
    renderStatus();
    renderTracker();
    if (updateMap) onChange?.();
  }

  async function persistRegistration(attendee) {
    const token = await ensureOffsetTurnstileToken();
    if (!token) {
      setStatus("Verification failed. Please try again.");
      return false;
    }

    try {
      const { response, payload } = await fetchJsonWithTimeout(apiUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: attendee.id,
          name: attendee.name,
          // The server groups by this label without parsing it, so the site
          // stays the single source of truth for how affiliations are keyed.
          affiliation_key: affiliationMapKey(attendee.affiliation || ""),
          pool: isSpeakerAttendee?.(attendee) === false ? "delegates" : "speakers",
          ...(requireDelegateId ? { delegate_id: normalizedDelegateId() } : {}),
          "cf-turnstile-response": token,
        }),
      });
      if (!response.ok) {
        offsetTurnstileToken = "";
        window.turnstile?.reset?.(offsetTurnstileWidgetId);
        setStatus(payload.error || "Registration failed. Please try again.");
        return false;
      }

      const accepted = Boolean(payload.created);

      if (accepted) {
        localRegistrations.add(personKey(attendee.name, attendee.affiliation));
        saveLocalRegistrations(localRegistrations);
      } else {
        // Already published on the server — sync browser memory only.
        localRegistrations.add(personKey(attendee.name, attendee.affiliation));
        saveLocalRegistrations(localRegistrations);
      }

      const pool = isSpeakerAttendee?.(attendee) === false ? "delegates" : "speakers";
      const beforeTotal =
        aggregate.totals.speakers +
        (activePool() === "delegates" ? aggregate.totals.delegates : 0);

      // Bump immediately so the bar moves, then re-fetch published totals.
      if (accepted && !payload.pending) {
        aggregate.totals[pool] += 1;
        const key = affiliationMapKey(attendee.affiliation || "");
        if (key) {
          aggregate.counts[pool][key] = (aggregate.counts[pool][key] || 0) + 1;
        }
        rebuildOffsetCounts();
      }

      if (payload.pending) {
        statusMessage = `Thanks, ${attendee.name}! Your offset is logged and will be counted once checked.`;
      } else if (accepted) {
        statusMessage = payload.reactivated
          ? `Thanks, ${attendee.name}! Your offset is registered again.`
          : `Thanks, ${attendee.name}! Your offset is registered.`;
      } else {
        statusMessage = `${attendee.name} is already registered on the server.`;
      }
      if (elements.query) elements.query.value = "";
      if (elements.delegateId) elements.delegateId.value = "";
      searchQuery = "";
      delegateIdInput = "";
      selectedAttendeeId = null;
      render({ updateMap: true });
      offsetTurnstileToken = "";
      window.turnstile?.reset?.(offsetTurnstileWidgetId);

      void loadRegistrations()
        .then(() => {
          rebuildOffsetCounts();
          const afterTotal =
            aggregate.totals.speakers +
            (activePool() === "delegates" ? aggregate.totals.delegates : 0);
          // If the server has not caught up yet, keep the optimistic bump.
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

      // Celebrate any newly accepted registration, including ones held for
      // review — the visitor did the work; the hold only delays the total.
      return accepted;
    } catch (error) {
      offsetTurnstileToken = "";
      window.turnstile?.reset?.(offsetTurnstileWidgetId);
      const timedOut = error?.name === "AbortError";
      setStatus(
        timedOut
          ? "Registration timed out. Check your connection and try again."
          : "Registration failed. Please try again."
      );
      console.warn("Offset registration failed:", error);
      return false;
    }
  }

  function registerSelected() {
    const attendee = resolveSelectedAttendee();
    if (!attendee) {
      if (searchQuery.trim()) setStatus("Select your name from the suggestions.");
      return false;
    }
    if (isRegistered(attendee) || pendingRegistrationIds.has(attendee.id)) {
      if (isRegistered(attendee)) setStatus(`You already registered ${attendee.name}.`);
      return false;
    }

    if (!apiUrl) {
      setStatus("Live registration API is not configured.");
      return false;
    }
    if (requireDelegateId && !delegateIdReady()) {
      setStatus("Enter your 5-digit delegate ID.");
      return false;
    }

    selectedAttendeeId = attendee.id;
    pendingRegistrationIds.add(attendee.id);
    setStatus("Registering…");
    renderTracker();

    void persistRegistration(attendee)
      .then((created) => {
        if (created) onRegisterSuccess?.(attendee);
      })
      .finally(() => {
        pendingRegistrationIds.delete(attendee.id);
        renderTracker();
      });
    return true;
  }

  function bindEvents() {
    elements.query?.addEventListener("input", (event) => {
      searchQuery = event.target.value;
      selectedAttendeeId = null;
      statusMessage = "";
      render();
    });

    elements.delegateId?.addEventListener("input", (event) => {
      delegateIdInput = event.target.value;
      statusMessage = "";
      renderTracker();
    });

    elements.query?.addEventListener("focus", () => {
      if (searchQuery.trim()) renderSuggestions();
    });

    document.addEventListener("click", (event) => {
      if (
        elements.suggestions &&
        !elements.suggestions.contains(event.target) &&
        event.target !== elements.query
      ) {
        elements.suggestions.classList.remove("open");
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
      void loadRegistrations().then(() => {
        rebuildOffsetCounts();
        render({ updateMap: true });
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
    initOffsetTurnstile();
    refreshAttendees();
    bindEvents();
    startPolling();
    render();
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
