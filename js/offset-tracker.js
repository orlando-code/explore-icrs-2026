import { affiliationMapKey, escapeHtml, haversineKm } from "./utils.js";
import { OFFSET_API_URL, TURNSTILE_SITE_KEY } from "./config.js";

let offsetTurnstileWidgetId = null;
let offsetTurnstileToken = "";
let offsetTurnstilePending = null;

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
    mount.hidden = true;
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
}

function offsetTurnstileResponse() {
  if (offsetTurnstileToken) return offsetTurnstileToken;
  if (offsetTurnstileWidgetId == null || !window.turnstile?.getResponse) return "";
  return window.turnstile.getResponse(offsetTurnstileWidgetId) || "";
}

async function ensureOffsetTurnstileToken() {
  const existing = offsetTurnstileResponse();
  if (existing) return existing;
  if (offsetTurnstileWidgetId == null) mountOffsetTurnstile();
  if (offsetTurnstileWidgetId == null || !window.turnstile?.execute) return "";

  return new Promise((resolve) => {
    const timeoutId = window.setTimeout(() => {
      if (!offsetTurnstilePending) return;
      offsetTurnstilePending = null;
      resolve(offsetTurnstileResponse());
    }, 30000);

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
      offsetTurnstilePending = null;
      resolve("");
    }
  });
}

function initOffsetTurnstile() {
  if (!TURNSTILE_SITE_KEY) return;
  if (window.turnstile?.ready) {
    window.turnstile.ready(() => mountOffsetTurnstile());
    return;
  }
  window.setTimeout(() => {
    if (window.turnstile) mountOffsetTurnstile();
  }, 0);
}

const STATIC_REGISTRATIONS_URL = "data/offset-registrations.json";
const POLL_INTERVAL_MS = 5_000;
const OFFSET_GREEN = "#2d8a4e";

function stableAttendeeId(name, locationId) {
  const key = `${name.trim().toLowerCase()}|${locationId}`;
  let hash = 2166136261;
  for (let index = 0; index < key.length; index += 1) {
    hash ^= key.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `offset-${(hash >>> 0).toString(16).padStart(8, "0")}`;
}

function personKey(name, affiliation) {
  return `${String(name).trim().toLowerCase()}|${affiliationMapKey(affiliation)}`;
}

function buildAttendeeLookupIndex(attendees) {
  const byId = new Map();
  for (const attendee of attendees) {
    byId.set(attendee.id, attendee);
    const legacyId = stableAttendeeId(attendee.name, attendee.location_id);
    if (!byId.has(legacyId)) byId.set(legacyId, attendee);
  }
  return byId;
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
  getAttendeeLookup,
  getHeadline,
  onChange,
  onRegisterSuccess,
  apiUrl = OFFSET_API_URL,
}) {
  let attendees = [];
  let attendeeById = new Map();
  let attendeeLookupById = new Map();
  let currentPoolKeys = new Set();
  let registeredIds = new Set();
  let selectedAttendeeId = null;
  let searchQuery = "";
  let pollTimer = null;
  let loadError = "";
  let offsetCountByAffiliation = new Map();
  const pendingRegistrationIds = new Set();

  function resolveAttendee(id) {
    return attendeeLookupById.get(id) || attendeeById.get(id) || null;
  }

  function isRegistered(attendee) {
    if (!attendee) return false;
    const key = personKey(attendee.name, attendee.affiliation);
    for (const id of registeredIds) {
      const resolved = resolveAttendee(id);
      if (resolved && personKey(resolved.name, resolved.affiliation) === key) return true;
    }
    return false;
  }

  function rebuildOffsetCounts() {
    offsetCountByAffiliation = new Map();
    for (const id of registeredIds) {
      const attendee = resolveAttendee(id);
      if (!attendee) continue;
      if (!currentPoolKeys.has(personKey(attendee.name, attendee.affiliation))) continue;
      const affiliationKey = affiliationMapKey(attendee.affiliation);
      if (!affiliationKey) continue;
      offsetCountByAffiliation.set(
        affiliationKey,
        (offsetCountByAffiliation.get(affiliationKey) || 0) + 1
      );
    }
  }

  async function loadRegistrations() {
    loadError = "";
    if (apiUrl) {
      try {
        const response = await fetch(apiUrl, { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        const ids = Array.isArray(payload?.registrations) ? payload.registrations : [];
        registeredIds = new Set(ids.filter((item) => typeof item === "string"));
        return;
      } catch (error) {
        loadError = "Could not refresh live offset totals.";
        console.warn("Offset API unavailable:", error);
      }
    }

    try {
      const response = await fetch(STATIC_REGISTRATIONS_URL, { cache: "no-store" });
      if (!response.ok) return;
      const payload = await response.json();
      const ids = Array.isArray(payload)
        ? payload
        : Array.isArray(payload?.registrations)
          ? payload.registrations
          : [];
      registeredIds = new Set(ids.filter((item) => typeof item === "string"));
    } catch {
      registeredIds = new Set();
    }
  }

  function refreshAttendees() {
    attendees = getAttendees();
    attendeeById = new Map(attendees.map((attendee) => [attendee.id, attendee]));
    currentPoolKeys = new Set(
      attendees.map((attendee) => personKey(attendee.name, attendee.affiliation))
    );
    const lookupAttendees = getAttendeeLookup?.() || attendees;
    attendeeLookupById = buildAttendeeLookupIndex(lookupAttendees);
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
    const registeredCount = attendees.filter((attendee) => isRegistered(attendee)).length;
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
        alreadyRegistered ? " · registered" : ""
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
    if (loadError) {
      elements.status.textContent = loadError;
      return;
    }
    elements.status.textContent = "";
  }

  function renderTracker() {
    const { registeredCount, totalAttendees, percent } = stats();
    if (elements.fill) {
      elements.fill.style.width = `${Math.min(100, percent)}%`;
    }
    if (elements.label) {
      const rounded = percent < 10 ? percent.toFixed(1) : Math.round(percent).toString();
      elements.label.innerHTML = `<strong>${rounded}%</strong> offset · <strong>${registeredCount.toLocaleString()}</strong> of ${totalAttendees.toLocaleString()} ${getHeadline()?.attendee_label || "delegates"} offsetted`;
    }
    if (elements.registerButton) {
      const attendee = resolveSelectedAttendee();
      elements.registerButton.disabled =
        !attendee || isRegistered(attendee) || pendingRegistrationIds.has(attendee.id);
      elements.registerButton.textContent = "I've offset my travel";
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
      if (elements.status) {
        elements.status.textContent = "Verification failed. Please try again.";
      }
      return false;
    }

    try {
      const response = await fetch(apiUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: attendee.id,
          name: attendee.name,
          "cf-turnstile-response": token,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        offsetTurnstileToken = "";
        window.turnstile?.reset?.(offsetTurnstileWidgetId);
        registeredIds.delete(attendee.id);
        rebuildOffsetCounts();
        render({ updateMap: true });
        throw new Error(payload.error || `HTTP ${response.status}`);
      }
      if (!payload.created) {
        registeredIds.delete(attendee.id);
        rebuildOffsetCounts();
        render({ updateMap: true });
      }
      if (elements.status) {
        elements.status.textContent = payload.created
          ? `Thanks, ${attendee.name}! Your offset is registered.`
          : `${attendee.name} was already registered.`;
      }
      if (elements.query) elements.query.value = "";
      searchQuery = "";
      selectedAttendeeId = null;
      renderTracker();
      offsetTurnstileToken = "";
      window.turnstile?.reset?.(offsetTurnstileWidgetId);
      return Boolean(payload.created);
    } catch (error) {
      offsetTurnstileToken = "";
      window.turnstile?.reset?.(offsetTurnstileWidgetId);
      if (elements.status) {
        elements.status.textContent = "Registration failed. Please try again.";
      }
      console.warn("Offset registration failed:", error);
      return false;
    }
  }

  function registerSelected() {
    const attendee = resolveSelectedAttendee();
    if (!attendee) return false;
    if (isRegistered(attendee) || pendingRegistrationIds.has(attendee.id)) {
      if (elements.status && isRegistered(attendee)) {
        elements.status.textContent = `${attendee.name} is already registered.`;
      }
      return false;
    }

    if (!apiUrl) {
      if (elements.status) {
        elements.status.textContent = "Live registration API is not configured.";
      }
      return false;
    }

    selectedAttendeeId = attendee.id;
    pendingRegistrationIds.add(attendee.id);
    registeredIds.add(attendee.id);
    rebuildOffsetCounts();
    renderTracker();
    renderStatus();
    onRegisterSuccess?.(attendee);

    void persistRegistration(attendee).finally(() => {
      pendingRegistrationIds.delete(attendee.id);
      renderTracker();
    });
    return true;
  }

  function bindEvents() {
    elements.query?.addEventListener("input", (event) => {
      searchQuery = event.target.value;
      selectedAttendeeId = null;
      render();
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
