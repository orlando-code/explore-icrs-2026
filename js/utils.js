import { AFFILIATION_GEOCODE_OVERRIDE_ENTRIES } from "./geocode-overrides.js";

export function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export function activateSuggestionAt(container, index) {
  if (!container) return -1;
  const buttons = [...container.querySelectorAll(".suggestion")];
  if (!buttons.length) return -1;
  const next = Math.max(0, Math.min(index, buttons.length - 1));
  buttons.forEach((button, buttonIndex) => {
    button.classList.toggle("active", buttonIndex === next);
  });
  buttons[next].scrollIntoView({ block: "nearest" });
  return next;
}

export function moveSuggestionSelection(container, delta) {
  if (!container) return -1;
  const buttons = [...container.querySelectorAll(".suggestion")];
  if (!buttons.length) return -1;
  const current = buttons.findIndex((button) => button.classList.contains("active"));
  const start = current >= 0 ? current : delta > 0 ? -1 : buttons.length;
  return activateSuggestionAt(container, start + delta);
}

export function getActiveSuggestionButton(container) {
  if (!container) return null;
  return container.querySelector(".suggestion.active") || container.querySelector(".suggestion");
}

export function handleSuggestionListKeydown(
  event,
  {
    container,
    isOpen = () => Boolean(container?.classList.contains("open")),
    onSelect,
    onClose,
  } = {}
) {
  if (!container || !isOpen()) return false;

  if (event.key === "ArrowDown") {
    event.preventDefault();
    moveSuggestionSelection(container, 1);
    return true;
  }
  if (event.key === "ArrowUp") {
    event.preventDefault();
    moveSuggestionSelection(container, -1);
    return true;
  }
  if (event.key === "Escape") {
    event.preventDefault();
    onClose?.();
    return true;
  }
  if (event.key === "Enter") {
    const active = getActiveSuggestionButton(container);
    if (active) {
      event.preventDefault();
      onSelect?.(active);
      return true;
    }
  }
  return false;
}

/** Shared affiliation pin styling for the main map and emissions map. */
export const AFFILIATION_MAP_CIRCLE_PAINT = {
  "circle-radius": [
    "case",
    ["==", ["get", "selected"], 1],
    ["+", ["get", "radius"], 4],
    ["==", ["get", "hovered"], 1],
    ["+", ["get", "radius"], 2],
    ["get", "radius"],
  ],
  "circle-color": [
    "case",
    ["==", ["get", "selected"], 1],
    "#20409a",
    ["==", ["get", "hovered"], 1],
    "#20409a",
    ["==", ["get", "talk_highlighted"], 1],
    "#e8945a",
    ["==", ["get", "author_highlighted"], 1],
    "#01b9b0",
    ["==", ["get", "highlighted"], 1],
    "#d95f02",
    "#9aa5ad",
  ],
  "circle-opacity": [
    "case",
    ["==", ["get", "selected"], 1],
    0.95,
    ["==", ["get", "hovered"], 1],
    0.92,
    ["==", ["get", "talk_highlighted"], 1],
    0.9,
    ["==", ["get", "author_highlighted"], 1],
    0.94,
    ["==", ["get", "highlighted"], 1],
    0.78,
    0.16,
  ],
  "circle-stroke-width": [
    "case",
    ["==", ["get", "selected"], 1],
    3,
    ["==", ["get", "hovered"], 1],
    2.5,
    ["==", ["get", "talk_highlighted"], 1],
    2.4,
    ["==", ["get", "author_highlighted"], 1],
    2.8,
    ["==", ["get", "highlighted"], 1],
    1.5,
    0.5,
  ],
  "circle-stroke-color": "#ffffff",
};

const LOCATION_CORRECTION_EMAIL = "rt582@cam.ac.uk";

export function locationCorrectionMailto(location) {
  const affiliation = location?.affiliation || "";
  const level = location?.geocode_level || "unknown";
  const coords =
    location?.lat != null && location?.lon != null
      ? `${location.lat}, ${location.lon}`
      : "not mapped";
  const subject = encodeURIComponent(
    "Correction for affiliation location on ICRS delegate explorer"
  );
  const body = encodeURIComponent(
    `Hello,\n\nThe map location for this affiliation is incorrect.\n\nAffiliation: ${affiliation}\nCurrent map coordinates: ${coords}\n\nPlease fill in at least one of the following with the correct location:\nCorrect coordinates (you can get this by right-clicking on Google Maps): [latitude, longitude]\nAddress or campus: [street address, city, country]\nGoogle Maps link: [URL]\n\n\nThank you.`
  );
  return `mailto:${LOCATION_CORRECTION_EMAIL}?subject=${subject}&body=${body}`;
}

const EARTH_RADIUS_KM = 6371;

function toRad(deg) {
  return (deg * Math.PI) / 180;
}

function toDeg(rad) {
  return (rad * 180) / Math.PI;
}

/** East-west separation in degrees along the shorter arc. */
export function shortestLonDelta(lon1, lon2) {
  let delta = lon2 - lon1;
  while (delta > 180) delta -= 360;
  while (delta < -180) delta += 360;
  return delta;
}

/** Great-circle distance on a sphere (shortest path). */
export function haversineKm(lat1, lon1, lat2, lon2) {
  const phi1 = toRad(lat1);
  const phi2 = toRad(lat2);
  const dPhi = toRad(lat2 - lat1);
  const dLambda = toRad(shortestLonDelta(lon1, lon2));
  const a =
    Math.sin(dPhi / 2) ** 2 +
    Math.cos(phi1) * Math.cos(phi2) * Math.sin(dLambda / 2) ** 2;
  return EARTH_RADIUS_KM * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function unwrapLongitudes(coords) {
  const out = [[coords[0][0], coords[0][1]]];
  for (let i = 1; i < coords.length; i += 1) {
    let [lon, lat] = coords[i];
    const prevLon = out[i - 1][0];
    while (lon - prevLon > 180) lon -= 360;
    while (lon - prevLon < -180) lon += 360;
    out.push([lon, lat]);
  }
  return out;
}

/** GeoJSON [lon, lat] coordinates along the shorter great-circle arc. */
export function greatCircleArc(lat1, lon1, lat2, lon2, numPoints = 64) {
  const dLon = shortestLonDelta(lon1, lon2);
  const lambda1 = toRad(lon1);
  const phi1 = toRad(lat1);
  const lambda2 = toRad(lon1 + dLon);
  const phi2 = toRad(lat2);

  const sinHalfSigma = Math.sqrt(
    Math.sin((phi2 - phi1) / 2) ** 2 +
      Math.cos(phi1) * Math.cos(phi2) * Math.sin((lambda2 - lambda1) / 2) ** 2
  );
  const sigma = 2 * Math.asin(Math.min(1, sinHalfSigma));

  if (sigma === 0) {
    return [
      [lon1, lat1],
      [lon2, lat2],
    ];
  }

  const sinSigmaInv = 1 / Math.sin(sigma);
  const x1 = Math.cos(phi1) * Math.cos(lambda1);
  const y1 = Math.cos(phi1) * Math.sin(lambda1);
  const z1 = Math.sin(phi1);
  const x2 = Math.cos(phi2) * Math.cos(lambda2);
  const y2 = Math.cos(phi2) * Math.sin(lambda2);
  const z2 = Math.sin(phi2);

  const coords = [];
  for (let i = 0; i <= numPoints; i += 1) {
    const t = i / numPoints;
    const a = Math.sin((1 - t) * sigma) * sinSigmaInv;
    const b = Math.sin(t * sigma) * sinSigmaInv;
    const x = a * x1 + b * x2;
    const y = a * y1 + b * y2;
    const z = a * z1 + b * z2;
    coords.push([toDeg(Math.atan2(y, x)), toDeg(Math.atan2(z, Math.sqrt(x * x + y * y)))]);
  }

  return unwrapLongitudes(coords);
}

export function formatDistance(km) {
  if (km == null || Number.isNaN(km)) return "–";
  if (km < 1) return `${Math.round(km * 1000).toLocaleString()} m`;
  return `${Math.round(km).toLocaleString()} km`;
}

export function formatEmissions(kg, { compact = false } = {}) {
  if (kg == null || Number.isNaN(kg)) return "–";
  const value = Number(kg);
  if (value === 0) return "0 kg";
  if (compact) {
    if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M kg`;
    if (value >= 10_000) return `${(value / 1000).toFixed(0)} t`;
    if (value >= 1000) return `${(value / 1000).toFixed(1)} t`;
  }
  if (value >= 1000) {
    return `${value.toLocaleString(undefined, { maximumFractionDigits: 0 })} kg`;
  }
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })} kg`;
}

export function formatTonnes(kg) {
  if (kg == null || Number.isNaN(kg)) return "–";
  return `${(Number(kg) / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })} t CO₂e`;
}

export function presentationTypeLabel(type) {
  const value = String(type || "").trim().toLowerCase();
  if (value === "poster") return "Poster";
  if (value === "oral") return "Oral presentation";
  if (value === "keynote") return "Keynote";
  return "";
}

export function setTalkFormatElement(element, talk) {
  if (!element) return;
  const label = presentationTypeLabel(talk?.presentation_type);
  if (!label) {
    element.hidden = true;
    element.textContent = "";
    return;
  }
  element.hidden = false;
  element.textContent = label;
}

export function normalizeTalkTitleEntry(entry) {
  if (!entry) return null;
  if (typeof entry === "string") {
    const title = entry.trim();
    return title ? { title, primary: true } : null;
  }
  const title = String(entry.title || "").trim();
  if (!title) return null;
  const talkId = entry.talk_id ? String(entry.talk_id).trim() : "";
  return {
    title,
    primary: Boolean(entry.primary),
    ...(talkId ? { talk_id: talkId } : {}),
  };
}

function mergeTalkTitleEntries(existing, incoming) {
  const byTitle = new Map((existing || []).map((entry) => [entry.title, entry]));
  for (const raw of incoming) {
    const entry = normalizeTalkTitleEntry(raw);
    if (!entry) continue;
    const previous = byTitle.get(entry.title);
    if (!previous || (entry.primary && !previous.primary)) {
      byTitle.set(entry.title, entry);
    }
  }
  return [...byTitle.values()];
}

export function sortTalkTitleEntries(entries) {
  return [...entries].sort((a, b) => {
    if (a.primary !== b.primary) return a.primary ? -1 : 1;
    return a.title.localeCompare(b.title, undefined, { sensitivity: "base" });
  });
}

export function buildTalkTitleIndex(locations, talkTitlesByPersonKey = null) {
  if (talkTitlesByPersonKey) {
    const index = new Map();
    for (const [personKey, entries] of Object.entries(talkTitlesByPersonKey)) {
      const merged = mergeTalkTitleEntries([], entries)
        .map(normalizeTalkTitleEntry)
        .filter(Boolean);
      if (merged.length) index.set(personKey, merged);
    }
    return index;
  }

  const index = new Map();
  for (const location of locations) {
    for (const speaker of location.speaker_details || []) {
      const personKey = String(speaker.person_key || "").trim();
      if (!personKey) continue;
      const titles = speaker.talk_titles || [];
      if (!titles.length) continue;
      const existing = index.get(personKey) || [];
      index.set(personKey, mergeTalkTitleEntries(existing, titles));
    }
  }
  return index;
}

export function renderTalkTitlesHtml(
  titles,
  { kicker = null, selectedTalkId = null, resolveTalkId = null } = {}
) {
  const entries = sortTalkTitleEntries(
    (titles || []).map(normalizeTalkTitleEntry).filter(Boolean)
  );
  if (!entries.length) return "";
  const items = entries
    .map((entry) => {
      const talkId = resolveTalkId ? resolveTalkId(entry) : entry.talk_id || "";
      const text = escapeHtml(entry.title);
      const selected =
        talkId && selectedTalkId && talkId === selectedTalkId ? " talk-title-btn-selected" : "";
      const primaryClass = entry.primary ? " talk-title-btn-primary" : "";
      if (!talkId) {
        return entry.primary ? `<li><strong>${text}</strong></li>` : `<li>${text}</li>`;
      }
      return `<li><button type="button" class="talk-title-btn${primaryClass}${selected}" data-talk-id="${escapeHtml(talkId)}">${entry.primary ? `<strong>${text}</strong>` : text}</button></li>`;
    })
    .join("");
  const kickerHtml = kicker ? `<p class="hover-kicker">${escapeHtml(kicker)}</p>` : "";
  return `${kickerHtml}<ul class="speaker-talk-titles">${items}</ul>`;
}

export function speakerMatchesQuery(speaker, query) {
  const trimmed = query.trim().toLowerCase();
  if (!trimmed) return false;
  if (speaker.name.toLowerCase().includes(trimmed)) return true;
  return speaker.search_text.includes(trimmed);
}

export function speakerIdentityKey(speaker) {
  const personKey = personKeyFromRecord(speaker);
  if (personKey) return personKey;
  const name = String(speaker?.name || speaker || "").trim();
  return name ? normalizePersonName(name) : "";
}

export function matchedSpeakersForLocation(location, query) {
  const trimmed = query.trim().toLowerCase();
  if (!trimmed) return new Set();
  const matched = new Set();
  for (const speaker of location.speaker_details || []) {
    if (speakerMatchesQuery(speaker, trimmed)) {
      const key = speakerIdentityKey(speaker);
      if (key) matched.add(key);
    }
  }
  return matched;
}

export function locationMatchesQuery(location, query) {
  const trimmed = query.trim().toLowerCase();
  if (!trimmed) return true;
  if (location.affiliation.toLowerCase().includes(trimmed)) return true;
  if (location.search_text.includes(trimmed)) return true;
  return matchedSpeakersForLocation(location, query).size > 0;
}

/** Spread coincident affiliation points so each remains clickable. */
export const AUSTRALIA_CENTROID = { lat: -24.7761086, lon: 134.755 };
export const NEW_ZEALAND_CENTROID = { lat: -41.500083, lon: 172.834408 };

const AFFILIATION_COORD_OVERRIDE_ENTRIES = [
  ...AFFILIATION_GEOCODE_OVERRIDE_ENTRIES,
  ["James Cook University", -19.3289618, 146.756645],
  ["University of Western Australia", -31.9507, 115.7979],
  ["the University of Western Australia", -31.9507, 115.7979],
  ["Western Australian Museum", -31.9492, 115.8645],
  [
    "Department of Biodiversity, Conservation and Attractions - Western Australia",
    -31.9523,
    115.8613,
  ],
  ["Victoria University of Wellington", -41.2889, 174.7762],
  ["University of Wellington", -41.2889, 174.7762],
  ["University of Hong Kong", 22.283, 114.137],
  ["Chinese University of Hong Kong", 22.419, 114.206],
  ["University of Leicester", 52.6205879, -1.109923],
  ["University of Auckland", -36.8660955, 174.7737331],
  ["University of Canterbury", -43.5232778, 172.5823435],
  ["Auckland University of Technology", -36.8529871, 174.76642],
];

const AFFILIATION_COORD_OVERRIDE_PATTERNS = AFFILIATION_COORD_OVERRIDE_ENTRIES.map(
  ([affiliation, lat, lon]) => ({
    pattern: new RegExp(
      affiliation.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"),
      "i"
    ),
    lat,
    lon,
  })
);

export function isAustraliaCentroid(lat, lon) {
  if (lat == null || lon == null) return false;
  return (
    Math.abs(Number(lat) - AUSTRALIA_CENTROID.lat) < 0.02 &&
    Math.abs(Number(lon) - AUSTRALIA_CENTROID.lon) < 0.02
  );
}

export function isNewZealandCentroid(lat, lon) {
  if (lat == null || lon == null) return false;
  return (
    Math.abs(Number(lat) - NEW_ZEALAND_CENTROID.lat) < 0.02 &&
    Math.abs(Number(lon) - NEW_ZEALAND_CENTROID.lon) < 0.02
  );
}

export function geocodeOverrideForAffiliation(affiliation) {
  if (!affiliation) return null;
  const key = affiliationMapKey(affiliation);
  for (const [name, lat, lon] of AFFILIATION_COORD_OVERRIDE_ENTRIES) {
    if (affiliationMapKey(name) === key) return { lat, lon };
  }
  for (const { pattern, lat, lon } of AFFILIATION_COORD_OVERRIDE_PATTERNS) {
    if (pattern.test(affiliation)) return { lat, lon };
  }
  return null;
}

export function applyAffiliationGeocodeOverrides(locations) {
  if (!Array.isArray(locations)) return locations;
  return locations.map((location) => {
    const override = geocodeOverrideForAffiliation(location.affiliation);
    if (!override) return location;
    const lat = Number(location.lat);
    const lon = Number(location.lon);
    if (
      Number.isFinite(lat) &&
      Number.isFinite(lon) &&
      Math.abs(lat - override.lat) < 0.000001 &&
      Math.abs(lon - override.lon) < 0.000001
    ) {
      return location;
    }
    return {
      ...location,
      lat: override.lat,
      lon: override.lon,
      geocode_level: location.geocode_level || "institute",
    };
  });
}

export function buildDisplayPositions(locations, { precision = 5, ringRadius = 0.055 } = {}) {
  const keyFor = (location) =>
    `${location.lat.toFixed(precision)}:${location.lon.toFixed(precision)}`;
  const groups = new Map();

  for (const location of locations) {
    const key = keyFor(location);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(location);
  }

  const display = new Map();
  for (const group of groups.values()) {
    if (group.length === 1) {
      const [location] = group;
      display.set(location.id, { lat: location.lat, lon: location.lon });
      continue;
    }

    group.sort((a, b) => a.affiliation.localeCompare(b.affiliation, undefined, { sensitivity: "base" }));
    const baseLat = group[0].lat;
    const baseLon = group[0].lon;
    const latRad = toRad(baseLat);
    const radius = ringRadius + Math.min(group.length, 10) * 0.008;

    group.forEach((location, index) => {
      const angle = (2 * Math.PI * index) / group.length - Math.PI / 2;
      const dLat = radius * Math.cos(angle);
      const dLon = (radius * Math.sin(angle)) / Math.max(Math.cos(latRad), 0.25);
      display.set(location.id, {
        lat: baseLat + dLat,
        lon: baseLon + dLon,
      });
    });
  }

  return display;
}

/** Map locations for non-speaking delegates not already on the speaker affiliation map. */
function canonicalAffiliationKey(key) {
  const normalized = String(key || "").trim().toLowerCase();
  if (normalized === "university of wellington") {
    return "victoria university of wellington";
  }
  if (/\buniversity of south carolina\b.*\bbeaufort\b/.test(normalized)) {
    return "university of south carolina beaufort";
  }
  const wwfMatch = normalized.match(/^world wildlife fund(?:\s*[-–]\s*(.+))?$/);
  if (wwfMatch) {
    const region = (wwfMatch[1] || "").trim();
    if (region) return `world wildlife fund - ${region}`;
    return normalized;
  }
  return normalized;
}

function regionalizeAffiliationKey(baseKey, country) {
  const normalized = canonicalAffiliationKey(baseKey);
  if (normalized === "world wildlife fund" && country) {
    const countryMap = {
      australia: "australia",
      indonesia: "indonesia",
    };
    const region = countryMap[String(country).trim().toLowerCase()];
    if (region) return `world wildlife fund - ${region}`;
  }
  return normalized;
}

export function affiliationMapKey(affiliation) {
  let normalized = affiliation.trim();
  if (/^the\s+/i.test(normalized)) {
    normalized = normalized.replace(/^the\s+/i, "");
  }
  const parts = normalized.split(",").map((part) => part.trim()).filter(Boolean);
  if (parts.length >= 2) {
    const last = parts[parts.length - 1].toLowerCase();
    const countries = new Set([
      "new zealand",
      "united kingdom",
      "united states",
      "hong kong",
      "australia",
      "canada",
      "germany",
      "france",
      "china",
      "japan",
      "singapore",
      "taiwan",
      "india",
      "brazil",
      "south africa",
      "indonesia",
      "saudi arabia",
    ]);
    if (countries.has(last)) {
      const base = parts.slice(0, -1).join(", ");
      return regionalizeAffiliationKey(base, last);
    }
  }
  return canonicalAffiliationKey(normalized.toLowerCase());
}

/** Keys used to match speaker vs delegate-only map pins (org with and without country). */
export function affiliationDedupeKeys(affiliation) {
  const keys = new Set();
  const text = String(affiliation || "").trim();
  if (!text) return keys;
  const primary = affiliationMapKey(text);
  if (primary) keys.add(primary);
  const parts = text.split(",").map((part) => part.trim()).filter(Boolean);
  if (parts.length >= 2) {
    const org = parts.slice(0, -1).join(", ");
    const orgKey = affiliationMapKey(org);
    if (orgKey) keys.add(orgKey);
  }
  return keys;
}

function coordsNear(a, b, epsilon = 0.05) {
  return (
    a &&
    b &&
    Math.abs(Number(a.lat) - Number(b.lat)) < epsilon &&
    Math.abs(Number(a.lon) - Number(b.lon)) < epsilon
  );
}

export function findLocationIdByAffiliation(locations, affiliation) {
  const key = affiliationMapKey(affiliation);
  if (!key) return null;
  const match = (locations || []).find((location) => affiliationMapKey(location.affiliation) === key);
  return match?.id || null;
}

export function normalizePersonName(name) {
  return String(name || "")
    .toLowerCase()
    .replace(/\b(dr|prof|professor|mr|mrs|ms|miss)\b\.?/g, "")
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

let delegatePersonKeyAliases = null;
let personCanonicalNames = null;

export function isRegistryPersonKey(value) {
  return typeof value === "string" && value.startsWith("icrs-p-");
}

/** Load name→person_key aliases exported with delegate groups (unique variants only). */
export function setDelegatePersonKeyAliases(aliases = {}) {
  delegatePersonKeyAliases = aliases && typeof aliases === "object" ? aliases : {};
}

/** Load person_key→preferred display name (talk name when available). */
export function setPersonCanonicalNames(names = {}) {
  personCanonicalNames = names && typeof names === "object" ? names : {};
}

export function personKeyFromRecord(record = {}) {
  const key = String(record.person_key || "").trim();
  if (isRegistryPersonKey(key)) return key;
  return "";
}

export function resolveDelegatePersonKey(name) {
  const cleaned = String(name || "").trim();
  if (!cleaned) return "";
  const normalized = normalizePersonName(cleaned);
  const lowered = cleaned.toLowerCase();
  if (delegatePersonKeyAliases) {
    const alias =
      delegatePersonKeyAliases[normalized] ||
      delegatePersonKeyAliases[lowered] ||
      delegatePersonKeyAliases[cleaned];
    if (isRegistryPersonKey(alias)) return String(alias);
  }
  return "";
}

export function resolveCanonicalPersonName(name, personKey = "") {
  const cleaned = String(name || "").trim();
  if (!cleaned) return "";
  const key = isRegistryPersonKey(personKey) ? personKey : resolveDelegatePersonKey(cleaned);
  const canonical = isRegistryPersonKey(key) ? personCanonicalNames?.[key] : "";
  return canonical ? String(canonical) : cleaned;
}

/** Deduplicate search hits by person identity, keeping the canonical display name. */
function searchNamePriority(hit) {
  const titles = hit.talkTitles;
  if (Array.isArray(titles) && titles.length > 0) return 2;
  if (!hit.nonSpeakingDelegate) return 1;
  return 0;
}

export function dedupeSearchHitsByPerson(hits, getName) {
  const deduped = new Map();
  for (const hit of hits) {
    const rawName = getName(hit);
    const personKey = personKeyFromRecord(hit);
    const dedupeKey = personKey
      ? personKey
      : `${hit.locationId || hit.nodeId || ""}|${rawName}`;
    const canonical = resolveCanonicalPersonName(rawName, personKey);
    const { _name, _priority, ...rest } = hit;
    const candidate = {
      ...rest,
      person_key: personKey || rest.person_key || "",
      label: canonical,
      query: canonical,
      speakerName: canonical,
      _priority: searchNamePriority(hit),
    };
    const existing = deduped.get(dedupeKey);
    if (!existing || candidate._priority > existing._priority) {
      deduped.set(dedupeKey, candidate);
    }
  }
  const results = [...deduped.values()].map(({ _priority, ...entry }) => entry);
  const labelCounts = new Map();
  for (const hit of results) {
    labelCounts.set(hit.label, (labelCounts.get(hit.label) || 0) + 1);
  }
  return results.map((hit) => {
    if ((labelCounts.get(hit.label) || 0) <= 1) return hit;
    const detail = String(hit.detail || "").trim();
    if (!detail) return hit;
    const label = `${hit.label} — ${detail}`;
    return { ...hit, label, query: label, speakerName: hit.speakerName || hit.label };
  });
}

function delegateIdentityKeys(delegate) {
  const keys = new Set();
  if (!delegate) return keys;
  const personKey = personKeyFromRecord(delegate) || resolveDelegatePersonKey(delegate.name);
  if (isRegistryPersonKey(personKey)) keys.add(personKey);
  const normalized = normalizePersonName(delegate.name);
  if (normalized) keys.add(normalized);
  const lowered = String(delegate.name || "").trim().toLowerCase();
  if (lowered) keys.add(lowered);
  return keys;
}

function locationDelegateIdentityKeys(location) {
  const keys = new Set();
  for (const speaker of location.speaker_details || []) {
    for (const key of delegateIdentityKeys(speaker)) {
      keys.add(key);
    }
  }
  return keys;
}

function annotateSpeakerDetails(speakerDetails = []) {
  return speakerDetails.map((speaker) => ({
    ...speaker,
    person_key: personKeyFromRecord(speaker) || resolveDelegatePersonKey(speaker.name),
  }));
}

function countNonSpeakingDelegates(speakerDetails = []) {
  return speakerDetails.filter((speaker) => speaker.non_speaking_delegate).length;
}

export function buildDelegateIndex(delegateGroups = []) {
  const index = new Map();
  for (const group of delegateGroups) {
    const key = affiliationMapKey(group.affiliation || group.affiliation_key || "");
    if (!key) continue;
    const existing = index.get(key) || [];
    index.set(key, [...existing, ...(group.delegates || [])]);
  }
  return index;
}

function delegateSpeakerDetails(delegates) {
  return (delegates || []).map((delegate) => ({
    name: resolveCanonicalPersonName(delegate.name),
    search_text: delegate.search_text || delegate.name.toLowerCase(),
    talk_titles: [],
    person_key: delegate.person_key || resolveDelegatePersonKey(delegate.name),
    non_speaking_delegate: delegate.is_speaker === false,
  }));
}

function mergeDelegateSearchText(location, speakerDetails) {
  const parts = [location.search_text || location.affiliation.toLowerCase()];
  for (const speaker of speakerDetails) {
    parts.push(speaker.search_text || speaker.name.toLowerCase());
  }
  return parts.join(" ");
}

export function enrichSpeakerLocationsWithDelegates(speakerLocations, delegateIndex) {
  if (!delegateIndex?.size) {
    return speakerLocations.map((location) => ({
      ...location,
      speaker_details: annotateSpeakerDetails(location.speaker_details || []),
      non_speaking_delegate_count: countNonSpeakingDelegates(location.speaker_details || []),
    }));
  }

  return speakerLocations.map((location) => {
    const baseDetails = annotateSpeakerDetails(location.speaker_details || []);
    const delegates = (delegateIndex.get(affiliationMapKey(location.affiliation)) || []).filter(
      (delegate) => delegate.is_speaker === false,
    );
    if (!delegates.length) {
      return {
        ...location,
        speaker_details: baseDetails,
        non_speaking_delegate_count: countNonSpeakingDelegates(baseDetails),
      };
    }

    const existingKeys = new Set();
    for (const speaker of baseDetails) {
      for (const key of delegateIdentityKeys(speaker)) {
        existingKeys.add(key);
      }
    }

    const newDelegates = delegates.filter((delegate) => {
      const keys = delegateIdentityKeys(delegate);
      for (const key of keys) {
        if (existingKeys.has(key)) return false;
      }
      return true;
    });
    if (!newDelegates.length) {
      return {
        ...location,
        speaker_details: baseDetails,
        non_speaking_delegate_count: countNonSpeakingDelegates(baseDetails),
      };
    }

    const speakerDetails = [...baseDetails, ...delegateSpeakerDetails(newDelegates)];
    speakerDetails.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));

    return {
      ...location,
      speakers: speakerDetails.map((speaker) => speaker.name),
      speaker_details: speakerDetails,
      speaker_count: speakerDetails.length,
      non_speaking_delegate_count: countNonSpeakingDelegates(speakerDetails),
      search_text: mergeDelegateSearchText(location, speakerDetails),
    };
  });
}

export function buildDelegateMapLocations(
  speakerLocations,
  delegateEmissionsLocations = [],
  delegateIndex = new Map(),
) {
  const knownKeys = new Set();
  for (const location of speakerLocations) {
    for (const key of affiliationDedupeKeys(location.affiliation)) {
      knownKeys.add(key);
    }
  }
  const seenDelegateKeys = new Set();
  const supplemental = [];

  for (const location of filterDelegateEmissionsLocationsForMap(delegateEmissionsLocations)) {
    const affiliation = location.affiliation;
    if (!affiliation || location.lat == null || location.lon == null) continue;
    const dedupeKeys = affiliationDedupeKeys(affiliation);
    if ([...dedupeKeys].some((key) => knownKeys.has(key))) continue;
    if ([...dedupeKeys].some((key) => seenDelegateKeys.has(key))) continue;

    const indexKey = [...dedupeKeys][0] || affiliationMapKey(affiliation);
    const speakerDetails = delegateSpeakerDetails(
      (delegateIndex.get(indexKey) || []).filter((delegate) => delegate.is_speaker === false),
    );
    const count = speakerDetails.length || 0;
    if (count === 0) continue;
    if (speakerLocations.some((speakerLoc) => coordsNear(speakerLoc, location))) continue;

    dedupeKeys.forEach((key) => seenDelegateKeys.add(key));
    supplemental.push({
      id: `delegate-loc-${supplemental.length + 1}`,
      affiliation,
      lat: location.lat,
      lon: location.lon,
      speakers: speakerDetails.map((speaker) => speaker.name),
      speaker_details: speakerDetails,
      speaker_count: count,
      talk_count: 0,
      geocode_level: "delegate list",
      distance_km: location.distance_km,
      search_text: mergeDelegateSearchText({ affiliation, search_text: affiliation.toLowerCase() }, speakerDetails),
      connection_count: 0,
      delegate_only: true,
      non_speaking_delegate_count: count,
    });
  }
  return supplemental;
}

/** Same affiliation pins as the main map tab (speakers ± non-speaking delegates). */
export function buildMapLocationPool(
  siteLocations = [],
  {
    includeNonSpeakers = false,
    delegateIndex = new Map(),
    delegateEmissionsLocations = [],
  } = {}
) {
  let pool = [...siteLocations];
  if (includeNonSpeakers) {
    pool = [
      ...enrichSpeakerLocationsWithDelegates(siteLocations, delegateIndex),
      ...buildDelegateMapLocations(siteLocations, delegateEmissionsLocations, delegateIndex),
    ];
  }
  return applyAffiliationGeocodeOverrides(pool);
}

function inferCountryCodeFromAffiliation(affiliation) {
  const parts = String(affiliation || "")
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
  if (parts.length < 2) return "";
  const country = parts[parts.length - 1].toLowerCase();
  const lookup = {
    india: "IN",
    "sri lanka": "LK",
    "united states": "US",
    australia: "AU",
    "new zealand": "NZ",
    "united kingdom": "GB",
    germany: "DE",
    france: "FR",
    china: "CN",
    japan: "JP",
    singapore: "SG",
    taiwan: "TW",
    brazil: "BR",
    indonesia: "ID",
    "south africa": "ZA",
    "saudi arabia": "SA",
    "hong kong": "HK",
  };
  return lookup[country] || "";
}

function indexEmissionsLocationsByAffiliation(emissionsLocations = []) {
  const byKey = new Map();
  for (const location of emissionsLocations) {
    for (const key of affiliationDedupeKeys(location.affiliation)) {
      if (!byKey.has(key)) byKey.set(key, []);
      byKey.get(key).push(location);
    }
  }
  return byKey;
}

function pickEmissionsLocationCandidate(candidates = [], siteLocation) {
  const unique = [...new Map(candidates.map((candidate) => [candidate.id, candidate])).values()];
  if (!unique.length) return null;
  if (unique.length === 1) return unique[0];

  const lat = Number(siteLocation.lat);
  const lon = Number(siteLocation.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return unique[0];

  let best = unique[0];
  let bestDistance = Infinity;
  for (const candidate of unique) {
    const candidateLat = Number(candidate.lat);
    const candidateLon = Number(candidate.lon);
    if (!Number.isFinite(candidateLat) || !Number.isFinite(candidateLon)) continue;
    const distance = (candidateLat - lat) ** 2 + (candidateLon - lon) ** 2;
    if (distance < bestDistance) {
      bestDistance = distance;
      best = candidate;
    }
  }
  return best;
}

function lookupEmissionsForSiteLocation(siteLocation, emissionsByAffiliation) {
  const candidates = [];
  for (const key of affiliationDedupeKeys(siteLocation.affiliation)) {
    const hits = emissionsByAffiliation.get(key);
    if (hits) candidates.push(...hits);
  }
  return pickEmissionsLocationCandidate(candidates, siteLocation);
}

/** Align emissions map pins with the main map: site geocodes + emissions totals. */
export function mergeEmissionsMapLocations(
  emissionsLocations = [],
  siteLocations = [],
  {
    includeNonSpeakers = false,
    delegateIndex = new Map(),
    delegateEmissionsLocations = [],
    emissionsAttendees = [],
  } = {}
) {
  const sitePool = buildMapLocationPool(siteLocations, {
    includeNonSpeakers,
    delegateIndex,
    delegateEmissionsLocations,
  });

  const co2eByLocationId = new Map();
  for (const attendee of emissionsAttendees) {
    const locationId = attendee?.location_id;
    if (!locationId) continue;
    const co2e = Number(attendee.co2e_kg) || 0;
    if (co2e <= 0) continue;
    const bucket = co2eByLocationId.get(locationId) || {
      co2e_kg: 0,
      co2e_low_kg: 0,
      co2e_high_kg: 0,
      count: 0,
      origin_country: attendee.origin_country || "",
      country_cluster_id: attendee.country_cluster_id || "",
    };
    bucket.co2e_kg += co2e;
    bucket.co2e_low_kg += Number(attendee.co2e_low_kg) || co2e;
    bucket.co2e_high_kg += Number(attendee.co2e_high_kg) || co2e;
    bucket.count += 1;
    if (!bucket.origin_country && attendee.origin_country) {
      bucket.origin_country = attendee.origin_country;
    }
    if (!bucket.country_cluster_id && attendee.country_cluster_id) {
      bucket.country_cluster_id = attendee.country_cluster_id;
    }
    co2eByLocationId.set(locationId, bucket);
  }

  const emissionsByAffiliation = indexEmissionsLocationsByAffiliation(emissionsLocations);
  const emissionsById = new Map(
    emissionsLocations.map((location) => [location.id, { ...location }]),
  );
  for (const [locationId, totals] of co2eByLocationId.entries()) {
    const existing = emissionsById.get(locationId);
    if (!existing) continue;
    emissionsById.set(locationId, {
      ...existing,
      co2e_kg: totals.co2e_kg,
      co2e_low_kg: totals.co2e_low_kg,
      co2e_high_kg: totals.co2e_high_kg,
      origin_country: totals.origin_country || existing.origin_country || "",
      country_cluster_id: totals.country_cluster_id || existing.country_cluster_id || "",
      travel_attendees: totals.count || existing.travel_attendees || 0,
      co2e_per_speaker_kg: totals.co2e_kg / Math.max(totals.count || 1, 1),
    });
  }
  const indexedEmissions = indexEmissionsLocationsByAffiliation([...emissionsById.values()]);

  const merged = [];

  for (const siteLocation of sitePool) {
    const lat = Number(siteLocation.lat);
    const lon = Number(siteLocation.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;

    const emissions = lookupEmissionsForSiteLocation(siteLocation, indexedEmissions);
    const co2eKg = Number(emissions?.co2e_kg) || 0;
    if (!emissions || co2eKg <= 0) continue;

    const attendeeCount = Number(siteLocation.speaker_count) || 0;
    const siteFields = {
      speakers: siteLocation.speakers,
      speaker_details: siteLocation.speaker_details,
      non_speaking_delegate_count: siteLocation.non_speaking_delegate_count || 0,
      delegate_only: siteLocation.delegate_only,
      talk_count: siteLocation.talk_count,
      connection_count: siteLocation.connection_count,
      search_text: siteLocation.search_text,
    };
    merged.push({
      ...emissions,
      ...siteFields,
      emissions_id: emissions.id,
      id: siteLocation.id,
      affiliation: siteLocation.affiliation,
      lat,
      lon,
      geocode_level: siteLocation.geocode_level || emissions.geocode_level,
      speaker_count: attendeeCount,
      travel_attendees: attendeeCount,
      origin_country:
        emissions.origin_country ||
        inferCountryCodeFromAffiliation(siteLocation.affiliation),
      country_cluster_id: emissions.country_cluster_id || "",
    });
  }

  return merged;
}

function normalizePersonNameForExclusion(name) {
  return normalizePersonName(name);
}

let mapExcludedNames = null;
let mapExcludedAffiliationKeys = null;

export function setMapExclusions({ names = [], affiliationKeys = [] } = {}) {
  mapExcludedNames = new Set(names.map(normalizePersonNameForExclusion));
  mapExcludedAffiliationKeys = new Set(
    affiliationKeys.map((key) => String(key || "").trim().toLowerCase()).filter(Boolean)
  );
}

export function isMapExcludedPerson(name) {
  if (!mapExcludedNames?.size) return false;
  return mapExcludedNames.has(normalizePersonNameForExclusion(name));
}

export function isMapExcludedAffiliation(affiliation) {
  if (!mapExcludedAffiliationKeys?.size) return false;
  return mapExcludedAffiliationKeys.has(affiliationMapKey(affiliation));
}

export function filterEmissionsPool(pool) {
  if (!pool) return pool;
  if (!mapExcludedNames?.size && !mapExcludedAffiliationKeys?.size) {
    return pool;
  }

  const attendees = (pool.attendees || []).filter(
    (attendee) =>
      !isMapExcludedPerson(attendee?.name) &&
      !isMapExcludedAffiliation(attendee?.affiliation)
  );

  const locationById = new Map(
    (pool.locations || [])
      .filter((location) => location?.id && !isMapExcludedAffiliation(location.affiliation))
      .map((location) => [location.id, { ...location }])
  );

  const totals = new Map();
  for (const attendee of attendees) {
    const locationId = attendee.location_id;
    if (!locationId || !locationById.has(locationId)) continue;
    const bucket = totals.get(locationId) || { co2eKg: 0, count: 0 };
    bucket.co2eKg += Number(attendee.co2e_kg) || 0;
    bucket.count += 1;
    totals.set(locationId, bucket);
  }

  const locations = [];
  for (const [locationId, location] of locationById) {
    const bucket = totals.get(locationId);
    if (!bucket?.count) continue;
    const co2eKg = Math.round(bucket.co2eKg * 10) / 10;
    locations.push({
      ...location,
      co2e_kg: co2eKg,
      co2e_low_kg: co2eKg,
      co2e_high_kg: co2eKg,
      travel_attendees: bucket.count,
      speaker_count: bucket.count,
      co2e_per_speaker_kg: Math.round((co2eKg / bucket.count) * 10) / 10,
    });
  }

  const rankings = [...locations].sort((left, right) => right.co2e_kg - left.co2e_kg).slice(0, 30);
  const totalCo2e = Math.round(locations.reduce((sum, row) => sum + row.co2e_kg, 0) * 10) / 10;
  const headline = pool.meta?.headline
    ? {
        ...pool.meta.headline,
        co2e_kg: totalCo2e,
        co2e_low_kg: totalCo2e,
        co2e_high_kg: totalCo2e,
        co2e_tonnes: Math.round((totalCo2e / 1000) * 100) / 100,
        attendees_estimated: attendees.length,
      }
    : pool.meta?.headline;

  return {
    ...pool,
    meta: {
      ...pool.meta,
      headline,
    },
    attendees,
    locations,
    rankings,
  };
}

export function filterDelegateEmissionsLocationsForMap(locations = []) {
  if (!mapExcludedNames?.size && !mapExcludedAffiliationKeys?.size) {
    return locations;
  }
  return locations.filter(
    (location) => location?.affiliation && !isMapExcludedAffiliation(location.affiliation)
  );
}

