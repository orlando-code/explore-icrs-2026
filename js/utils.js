export function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

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

export function normalizeTalkTitleEntry(entry) {
  if (!entry) return null;
  if (typeof entry === "string") {
    const title = entry.trim();
    return title ? { title, primary: true } : null;
  }
  const title = String(entry.title || "").trim();
  if (!title) return null;
  return { title, primary: Boolean(entry.primary) };
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

export function buildTalkTitleIndex(locations, talkTitlesByAuthor = null) {
  if (talkTitlesByAuthor) {
    const index = new Map();
    for (const [name, entries] of Object.entries(talkTitlesByAuthor)) {
      const merged = mergeTalkTitleEntries([], entries)
        .map(normalizeTalkTitleEntry)
        .filter(Boolean);
      if (merged.length) index.set(name, merged);
    }
    return index;
  }

  const index = new Map();
  for (const location of locations) {
    for (const speaker of location.speaker_details || []) {
      const titles = speaker.talk_titles || [];
      if (!titles.length) continue;
      const existing = index.get(speaker.name) || [];
      index.set(speaker.name, mergeTalkTitleEntries(existing, titles));
    }
  }
  return index;
}

export function renderTalkTitlesHtml(titles, { kicker = null } = {}) {
  const entries = sortTalkTitleEntries(
    (titles || []).map(normalizeTalkTitleEntry).filter(Boolean)
  );
  if (!entries.length) return "";
  const items = entries
    .map(({ title, primary }) => {
      const text = escapeHtml(title);
      return primary ? `<li><strong>${text}</strong></li>` : `<li>${text}</li>`;
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

export function matchedSpeakersForLocation(location, query) {
  const trimmed = query.trim().toLowerCase();
  if (!trimmed) return new Set();
  const matched = new Set();
  for (const speaker of location.speaker_details || []) {
    if (speakerMatchesQuery(speaker, trimmed)) {
      matched.add(speaker.name);
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

const AFFILIATION_COORD_OVERRIDE_ENTRIES = [
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
      !isAustraliaCentroid(lat, lon) &&
      Math.abs(lat - override.lat) < 0.0001 &&
      Math.abs(lon - override.lon) < 0.0001
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
  if (key === "university of wellington") {
    return "victoria university of wellington";
  }
  return key;
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
    ]);
    if (countries.has(last)) {
      return canonicalAffiliationKey(parts.slice(0, -1).join(", ").toLowerCase());
    }
  }
  return canonicalAffiliationKey(normalized.toLowerCase());
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
    name: delegate.name,
    search_text: delegate.search_text || delegate.name.toLowerCase(),
    talk_titles: [],
    non_speaking_delegate: true,
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
  if (!delegateIndex?.size) return speakerLocations;

  return speakerLocations.map((location) => {
    const delegates = delegateIndex.get(affiliationMapKey(location.affiliation)) || [];
    if (!delegates.length) return location;

    const existingNames = new Set(
      (location.speaker_details || []).map((speaker) => speaker.name.toLowerCase())
    );
    const newDelegates = delegates.filter(
      (delegate) => !existingNames.has(delegate.name.toLowerCase())
    );
    if (!newDelegates.length) return location;

    const speakerDetails = [
      ...(location.speaker_details || []),
      ...delegateSpeakerDetails(newDelegates),
    ];
    speakerDetails.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));

    return {
      ...location,
      speakers: speakerDetails.map((speaker) => speaker.name),
      speaker_details: speakerDetails,
      speaker_count: speakerDetails.length,
      non_speaking_delegate_count: newDelegates.length,
      search_text: mergeDelegateSearchText(location, speakerDetails),
    };
  });
}

export function buildDelegateMapLocations(
  speakerLocations,
  delegateEmissionsLocations = [],
  delegateIndex = new Map(),
) {
  const knownKeys = new Set(
    speakerLocations.map((location) => affiliationMapKey(location.affiliation))
  );
  const seenDelegateKeys = new Set();
  const supplemental = [];

  for (const location of delegateEmissionsLocations) {
    const affiliation = location.affiliation;
    if (!affiliation || location.lat == null || location.lon == null) continue;
    const key = affiliationMapKey(affiliation);
    if (knownKeys.has(key) || seenDelegateKeys.has(key)) continue;
    seenDelegateKeys.add(key);

    const speakerDetails = delegateSpeakerDetails(delegateIndex.get(key) || []);
    const count = speakerDetails.length || location.travel_attendees || location.speaker_count || 1;
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
      non_speaking_delegate_count: speakerDetails.length,
    });
  }
  return supplemental;
}

