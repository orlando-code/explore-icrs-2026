import {
  buildDisplayPositions,
  enrichSpeakerLocationsWithDelegates,
  escapeHtml,
  formatDistance,
  formatEmissions,
  formatTonnes,
  greatCircleArc,
  haversineKm,
  buildDelegateIndex,
} from "./utils.js";
import {
  buildEmissionsAttendeesFromSite,
  createOffsetTracker,
  pieSlicePolygon,
} from "./offset-tracker.js";
import { createFireworksOverlay } from "./celebration.js";

const MAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";
const MAX_ZOOM = 10;
const FLIGHT_PREMIUM_ECONOMY_MULTIPLIER = 1.6;
const FLIGHT_BUSINESS_MULTIPLIER = 2.9;
const regionNames = new Intl.DisplayNames(["en"], { type: "region" });

function isMobileLayout() {
  return window.matchMedia("(max-width: 900px)").matches;
}

function useCooperativeMapGestures() {
  return window.matchMedia("(max-width: 900px) and (pointer: coarse)").matches;
}

function countryLabel(code) {
  try {
    return regionNames.of(code) || code;
  } catch {
    return code;
  }
}

function formatCount(value) {
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function normalizeEmissionsData(data) {
  if (data?.speakers) {
    return {
      meta: data.meta || {},
      speakers: data.speakers,
      all_delegates: data.all_delegates || data.speakers,
    };
  }
  return {
    meta: { generated_at: data.meta?.generated_at, delegate_meta: {} },
    speakers: data,
    all_delegates: data,
  };
}

export function createEmissionsView(
  rawEmissionsData,
  siteData,
  elements,
  { delegateGroups = [] } = {}
) {
  const normalized = normalizeEmissionsData(rawEmissionsData);
  const delegateIndex = buildDelegateIndex(delegateGroups);
  const delegateMeta = normalized.meta.delegate_meta || {};
  const hasDelegatePool =
    Boolean(delegateMeta.non_speaker_count) &&
    normalized.all_delegates?.meta?.headline?.attendees_estimated !==
      normalized.speakers?.meta?.headline?.attendees_estimated;

  let includeNonSpeakers = hasDelegatePool;
  let emissionsData = normalized.speakers;
  let locations = [];
  let allLocations = [];
  let headline = {};
  let rankings = [];
  let byCountry = [];
  let context = {};
  let positiveCo2e = [];
  let maxCo2e = 1;
  let minCo2e = 1;
  let sizeScale = null;
  let emissionNorm = null;
  let displayPositions = new Map();

  const auckland = siteData.meta.auckland;
  let rankMode = "affiliation";
  let distanceMode = false;
  let selectedId = null;
  let hoveredId = null;
  let mapReady = false;
  let offsetTracker = null;
  let sliceRefreshTimer = null;
  let mapUpdateTimer = null;
  let cachedAttendees = null;
  let cachedAttendeesKey = "";

  const colorScale = (value) =>
    d3.interpolateRgb("#f7dcc8", "#c43c01")(emissionNorm(Math.max(value, minCo2e)));

  const map = new maplibregl.Map({
    container: elements.mapContainer,
    style: MAP_STYLE,
    center: [auckland.lon, auckland.lat],
    zoom: isMobileLayout() ? 1.35 : 1.9,
    minZoom: isMobileLayout() ? 0.9 : 0.5,
    maxZoom: MAX_ZOOM,
    touchPitch: false,
    cooperativeGestures: useCooperativeMapGestures(),
  });

  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");

  const fireworks = createFireworksOverlay(elements.mapContainer.parentElement);
  let celebrateTimer = null;

  function attendeeLabel() {
    return headline.attendee_label || (includeNonSpeakers ? "delegates" : "speakers");
  }

  function applyPool() {
    emissionsData = includeNonSpeakers ? normalized.all_delegates : normalized.speakers;
    allLocations = emissionsData.locations || [];
    locations = allLocations.filter((location) => location.co2e_kg > 0);
    headline = emissionsData.meta.headline || {};
    rankings = emissionsData.rankings || [];
    byCountry = emissionsData.by_country || [];
    context = emissionsData.meta.context || {};

    positiveCo2e = locations.map((location) => location.co2e_kg);
    maxCo2e = Math.max(...positiveCo2e, 1);
    minCo2e = Math.max(1, Math.min(...positiveCo2e));

    sizeScale = d3
      .scaleLog()
      .domain([minCo2e, maxCo2e])
      .range([7, 30])
      .clamp(true);
    emissionNorm = d3
      .scaleLog()
      .domain([minCo2e, maxCo2e])
      .range([0, 1])
      .clamp(true);
    displayPositions = buildDisplayPositions(allLocations);
    selectedId = null;
    hoveredId = null;
    cachedAttendees = null;
  }

  function locationById(id) {
    return allLocations.find((location) => location.id === id) || null;
  }

  function displayForLocation(location) {
    return displayPositions.get(location.id) || { lat: location.lat, lon: location.lon };
  }

  function radiusFor(location) {
    if (!location.co2e_kg) return 4;
    return sizeScale(location.co2e_kg);
  }

  function colorFor(location, highlighted) {
    if (!location.co2e_kg) return "#b8c4cc";
    if (location.id === selectedId) return "#1f6f8b";
    const offsetShare = offsetTracker?.offsetShareForLocation(
      location.id,
      location.travel_attendees
    );
    if (offsetShare >= 1) return offsetTracker?.OFFSET_GREEN || "#2d8a4e";
    if (!highlighted) return "#b8c4cc";
    return colorScale(location.co2e_kg);
  }

  function flightBusinessMultiplier() {
    return (
      emissionsData.meta?.assumptions?.flight_business_multiplier ?? FLIGHT_BUSINESS_MULTIPLIER
    );
  }

  function flightPremiumEconomyMultiplier() {
    return (
      emissionsData.meta?.assumptions?.flight_premium_economy_multiplier ?? FLIGHT_PREMIUM_ECONOMY_MULTIPLIER
    );
  }

  function currentAttendees() {
    if (emissionsData.attendees?.length) return emissionsData.attendees;
    const cacheKey = includeNonSpeakers ? "all" : "speakers";
    if (cachedAttendees && cachedAttendeesKey === cacheKey) return cachedAttendees;
    let siteLocations = siteData.locations || [];
    if (includeNonSpeakers && delegateIndex.size) {
      siteLocations = enrichSpeakerLocationsWithDelegates(siteLocations, delegateIndex);
    }
    cachedAttendees = buildEmissionsAttendeesFromSite(siteLocations, allLocations);
    cachedAttendeesKey = cacheKey;
    return cachedAttendees;
  }

  function locationOffsetShare(location) {
    if (!location?.id || !location.travel_attendees) return 0;
    return offsetTracker?.offsetShareForLocation(location.id, location.travel_attendees) || 0;
  }

  function offsetSliceFeatures() {
    if (!mapReady || !offsetTracker) return [];
    return allLocations
      .filter((location) => location.co2e_kg > 0 && locationOffsetShare(location) > 0)
      .map((location) => {
        const share = locationOffsetShare(location);
        if (share >= 1) return null;
        const display = displayForLocation(location);
        const radius = radiusFor(location);
        const ring = pieSlicePolygon(map, display.lon, display.lat, radius, share);
        if (!ring) return null;
        return {
          type: "Feature",
          properties: {
            id: location.id,
            offset_share: share,
            sort_key: location.co2e_kg || 0,
          },
          geometry: {
            type: "Polygon",
            coordinates: [ring],
          },
        };
      })
      .filter(Boolean);
  }

  function updateOffsetSlices() {
    if (!mapReady || !offsetTracker) return;
    map.getSource("offset-slices")?.setData({
      type: "FeatureCollection",
      features: offsetSliceFeatures(),
    });
  }

  function scheduleMapUpdate() {
    if (!mapReady) return;
    if (mapUpdateTimer) return;
    mapUpdateTimer = window.requestAnimationFrame(() => {
      mapUpdateTimer = null;
      upsertMapData();
    });
  }

  function scheduleSliceRefresh() {
    if (!mapReady) return;
    if (sliceRefreshTimer) return;
    sliceRefreshTimer = window.requestAnimationFrame(() => {
      sliceRefreshTimer = null;
      updateOffsetSlices();
    });
  }

  function economyAssumptionNote() {
    const premiumEconomyMult = flightPremiumEconomyMultiplier();
    const businessMult = flightBusinessMultiplier();
    const premiumEconomyMultLabel = Number.isInteger(premiumEconomyMult)
      ? String(premiumEconomyMult)
      : premiumEconomyMult.toFixed(1);
    const businessMultLabel = Number.isInteger(businessMult)
      ? String(businessMult)
      : businessMult.toFixed(1);
    return `Assuming economy flights – premium economy and business class would be around ~${premiumEconomyMultLabel}× and ~${businessMultLabel}× more emissions respectively.`;
  }

  function renderHeadline() {
    const label = attendeeLabel();
    const showDelegateNote = includeNonSpeakers && delegateMeta.non_speaker_count;

    if (elements.headlineTotal) {
      elements.headlineTotal.textContent = formatTonnes(headline.co2e_kg);
    }
    if (elements.headlineAssumption) {
      elements.headlineAssumption.textContent = economyAssumptionNote();
    }
    if (elements.headlineMeta) {
      elements.headlineMeta.innerHTML = `
        <strong>${headline.attendees_estimated.toLocaleString()}</strong> ${label} with geocoded affiliations ·
        <strong>${headline.attendees_missing_location.toLocaleString()}</strong> excluded (no location)
      `;
    }
    if (elements.headlineDelegateNote) {
      elements.headlineDelegateNote.hidden = !showDelegateNote;
      if (showDelegateNote) {
        elements.headlineDelegateNote.innerHTML = `Includes <strong>${formatCount(delegateMeta.non_speaker_count)}</strong> non-speaking delegates.`;
      }
    }
    if (elements.delegateToggleWrap) {
      elements.delegateToggleWrap.hidden = !hasDelegatePool;
    }
    if (elements.includeNonSpeakersToggle) {
      elements.includeNonSpeakersToggle.checked = includeNonSpeakers;
      elements.includeNonSpeakersToggle.disabled = !hasDelegatePool;
    }
  }

  function formatRatioPhrase(ratio) {
    if (ratio >= 1.05) {
      const rounded = ratio >= 10 ? Math.round(ratio).toLocaleString() : ratio.toFixed(1);
      return `<strong>${rounded}×</strong> higher than`;
    }
    if (ratio <= 0.95) {
      return `<strong>${ratio.toFixed(1)}×</strong> (about ${Math.round(ratio * 100)}% of)`;
    }
    return `<strong>about the same as</strong>`;
  }

  function formatNationalTonnes(tonnes) {
    if (tonnes == null) return "–";
    return `${Number(tonnes).toLocaleString(undefined, { maximumFractionDigits: 2 })} t/person`;
  }

  function renderContext() {
    if (!elements.context) return;
    const bullets = [];
    const year = context.national_per_capita_year || 2024;
    const minN = context.country_avg_min_attendees || 3;
    const label = attendeeLabel();
    const travelSource = (context.sources || []).find((item) => item.id === "travel");
    const treeSource = (context.sources || []).find((item) => item.id === "tree_uptake");
    const nationalSource = (context.sources || []).find((item) => item.id === "national_per_capita");

    // Helper for [source] snippet if available
    function sourceLink(source) {
      return source
        ? ` [<a href="${escapeHtml(source.url)}" target="_blank" rel="noopener">source</a>]`
        : "";
    }

    if (context.tree_years) {
      const kgPerTree = context.tree_kg_per_year_assumption || 22;
      bullets.push(
        `About <strong>${formatCount(context.tree_years)} tree-years</strong> of CO₂ uptake to offset this total with the estimated equivalent of ≈${kgPerTree} kg per mature tree per year${sourceLink(treeSource)}.`
      );
    }

    if (context.per_attendee_kg) {
      bullets.push(
        `Averaged across geocoded ${label}: <strong>${formatEmissions(context.per_attendee_kg, { compact: true })}</strong> estimated return travel per person${sourceLink(travelSource)}.`
      );
    }

    const nationalNote = nationalSource
      ? ` ([<a href="${escapeHtml(nationalSource.url)}" target="_blank" rel="noopener">World Bank ${year}</a>])`
      : ` (World Bank ${year})`;

    // if (context.lowest_national_per_capita) {
    //   const row = context.lowest_national_per_capita;
    //   bullets.push(
    //     `Among countries with ≥${minN} ${label}, <strong>${escapeHtml(countryLabel(row.origin_country))}</strong> has the lowest national per-capita emissions (${formatNationalTonnes(row.national_tonnes_per_capita)}${nationalNote}). ${label.charAt(0).toUpperCase() + label.slice(1)} from ${escapeHtml(countryLabel(row.origin_country))} averaged ${formatRatioPhrase(row.ratio_vs_national_annual)} that annual footprint in return travel alone (${formatEmissions(row.co2e_per_attendee_kg, { compact: true })}/person, n=${row.attendee_count}).`
    //   );
    // }

    // if (context.highest_national_per_capita) {
    //   const row = context.highest_national_per_capita;
    //   bullets.push(
    //     `<strong>${escapeHtml(countryLabel(row.origin_country))}</strong> has the highest national per-capita emissions among represented countries (${formatNationalTonnes(row.national_tonnes_per_capita)}${nationalNote}). ${label.charAt(0).toUpperCase() + label.slice(1)} from ${escapeHtml(countryLabel(row.origin_country))} averaged ${formatRatioPhrase(row.ratio_vs_national_annual)} that annual footprint (${formatEmissions(row.co2e_per_attendee_kg, { compact: true })}/person, n=${row.attendee_count}).`
    //   );
    // }

    if (context.conference_vs_lowest_national && context.conference_vs_highest_national) {
      const low = context.conference_vs_lowest_national;
      const high = context.conference_vs_highest_national;
      bullets.push(
        `Personally, as a delegate from the UK, this return trip was equivalent to a year's worth of emissions...${sourceLink(nationalSource)}.`
      );
    }

    // for (const row of context.illustrative_per_capita || []) {
    //   const labelText =
    //     row.role === "illustrative_low"
    //       ? `For comparison, ${escapeHtml(countryLabel(row.origin_country))}'s national per-capita is ${formatNationalTonnes(row.national_tonnes_per_capita)}${nationalNote}: the conference average return trip is ${formatRatioPhrase(row.ratio_vs_national_annual)} that annual footprint.`
    //       : `${escapeHtml(countryLabel(row.origin_country))}'s national per-capita is ${formatNationalTonnes(row.national_tonnes_per_capita)}${nationalNote}; the conference average return trip is ${formatRatioPhrase(row.ratio_vs_national_annual)} that annual footprint.`;
    //   bullets.push(labelText);
    // }

    const sources = context.sources || [];
    const sourcesHtml = sources.length
      ? `<div class="emissions-sources"><h3>Sources</h3><ul>${sources
        .map(
          (source) =>
            `<li><a href="${escapeHtml(source.url)}" target="_blank" rel="noopener">${escapeHtml(source.label)}</a>${source.note ? `<span> – ${escapeHtml(source.note)}</span>` : ""}</li>`
        )
        .join("")}</ul></div>`
      : "";

    const contextHtml = bullets.length
      ? `<h3>Putting it in context</h3><ul class="emissions-context-list">${bullets.map((item) => `<li>${item}</li>`).join("")}</ul>${sourcesHtml}`
      : sourcesHtml;

    elements.context.innerHTML = contextHtml;
  }

  function renderModeBreakdown() {
    const modes = emissionsData.meta.by_transport_mode || [];
    elements.modeBreakdown.innerHTML = modes
      .map((row) => {
        const label = row.transport_mode === "car" ? "NZ shared car" : "Return flights";
        const share = headline.co2e_kg
          ? Math.round((row.co2e_kg / headline.co2e_kg) * 100)
          : 0;
        return `<div class="emissions-mode-row">
          <span>${label}</span>
          <strong>${formatEmissions(row.co2e_kg, { compact: true })}</strong>
          <span class="emissions-mode-share">${share}%</span>
        </div>`;
      })
      .join("");
  }

  function renderLegend() {
    const samples = [
      { label: formatEmissions(minCo2e, { compact: true }), size: sizeScale(minCo2e), color: colorScale(minCo2e) },
      {
        label: formatEmissions(Math.sqrt(minCo2e * maxCo2e), { compact: true }),
        size: sizeScale(Math.sqrt(minCo2e * maxCo2e)),
        color: colorScale(Math.sqrt(minCo2e * maxCo2e)),
      },
      { label: formatEmissions(maxCo2e, { compact: true }), size: sizeScale(maxCo2e), color: colorScale(maxCo2e) },
    ];
    elements.legend.innerHTML = `
      <h3>Point size &amp; colour · travel CO₂e</h3>
      <p>Return-trip estimates per affiliation (economy flights; NZ by shared car).</p>
      ${samples
        .map(
          (sample) => `
        <div class="legend-row">
          <span class="legend-dot" style="width:${sample.size}px;height:${sample.size}px;background:${sample.color}"></span>
          <span>${sample.label}</span>
        </div>`
        )
        .join("")}
      <p class="legend-note">Click a bar or map point to show the route to Auckland, or toggle routes for all affiliations.</p>
    `;
  }

  function renderBarChart() {
    if (rankMode === "affiliation") {
      const maxValue = rankings[0]?.co2e_kg || 1;
      elements.barChart.innerHTML = rankings
        .slice(0, 15)
        .map((row) => {
          const width = Math.max(4, (row.co2e_kg / maxValue) * 100);
          const selected = row.id === selectedId;
          return `
          <button type="button" class="bar-row${selected ? " selected" : ""}" data-id="${escapeHtml(row.id)}">
            <span class="bar-label">${escapeHtml(row.affiliation)}</span>
            <div class="bar-track"><div class="bar-fill" style="width:${width}%"></div></div>
            <span class="bar-count">${formatEmissions(row.co2e_kg, { compact: true })}</span>
          </button>`;
        })
        .join("");

      elements.barChart.querySelectorAll("button[data-id]").forEach((button) => {
        button.addEventListener("click", () => selectLocation(button.dataset.id, { fly: true, toggle: true }));
      });
      return;
    }

    const maxValue = byCountry[0]?.co2e_kg || 1;
    elements.barChart.innerHTML = byCountry
      .slice(0, 15)
      .map((row) => {
        const width = Math.max(4, (row.co2e_kg / maxValue) * 100);
        return `
        <div class="bar-row emissions-country-row">
          <span class="bar-label">${escapeHtml(countryLabel(row.origin_country))}</span>
          <div class="bar-track"><div class="bar-fill emissions-country-fill" style="width:${width}%"></div></div>
          <span class="bar-count">${formatEmissions(row.co2e_kg, { compact: true })}</span>
        </div>`;
      })
      .join("");
  }

  function renderRankings() {
    const personLabel = attendeeLabel().replace(/s$/, "");
    if (rankMode === "affiliation") {
      elements.resultsTitle.textContent = "Emissions breakdown";
      elements.results.innerHTML = rankings
        .slice(0, 30)
        .map((row) => {
          const selected = row.id === selectedId;
          return `
          <button type="button" class="result-item${selected ? " selected" : ""}" data-id="${escapeHtml(row.id)}">
            <div class="affiliation">${escapeHtml(row.affiliation)}</div>
            <div class="meta">
              ${formatEmissions(row.co2e_kg, { compact: true })} total ·
              ${row.travel_attendees} attendee${row.travel_attendees === 1 ? "" : "s"} ·
              ${formatEmissions(row.co2e_per_speaker_kg, { compact: true })}/person ·
              ${formatDistance(row.distance_km)} from Auckland
            </div>
          </button>`;
        })
        .join("");

      elements.results.querySelectorAll("button[data-id]").forEach((button) => {
        button.addEventListener("click", () => selectLocation(button.dataset.id, { fly: true, toggle: true }));
      });
      return;
    }

    elements.resultsTitle.textContent = "Top countries by emissions";
    elements.results.innerHTML = byCountry
      .slice(0, 30)
      .map((row, index) => {
        const perPerson =
          row.co2e_per_attendee_kg != null
            ? `${formatEmissions(row.co2e_per_attendee_kg, { compact: true })}/person · `
            : "";
        const attendees =
          row.attendee_count != null
            ? `${row.attendee_count} ${personLabel}${row.attendee_count === 1 ? "" : "s"} · `
            : "";
        return `
        <div class="result-item emissions-country-row">
          <div class="affiliation">${index + 1}. ${escapeHtml(countryLabel(row.origin_country))}</div>
          <div class="meta">
            ${formatEmissions(row.co2e_kg, { compact: true })} total ·
            ${attendees}${perPerson}
          </div>
        </div>`;
      })
      .join("");
  }

  function renderAssumptions() {
    const nzTransport =
      emissionsData.meta.assumptions?.nz_transport ||
      "Return shared car trip for attendees in New Zealand.";
    elements.assumptions.innerHTML = `
      <p>${escapeHtml(economyAssumptionNote())}</p>
      <p>${escapeHtml(nzTransport)}</p>
    `;
  }

  function treeKgPerYear() {
    return context.tree_kg_per_year_assumption || 22;
  }

  function treeYearsForCo2e(kg) {
    if (!kg || kg <= 0) return null;
    return Math.round(kg / treeKgPerYear());
  }

  function renderHoverCard(location) {
    if (!location) {
      elements.hoverCard.hidden = true;
      return;
    }
    elements.hoverCard.hidden = false;
    elements.hoverAffiliation.textContent = location.affiliation;
    const treeYears = treeYearsForCo2e(location.co2e_kg);
    const metaParts = [
      formatEmissions(location.co2e_kg, { compact: true }),
      `${location.travel_attendees} attendee${location.travel_attendees === 1 ? "" : "s"}`,
      `${formatEmissions(location.co2e_per_speaker_kg, { compact: true })}/person`,
    ];
    if (location.distance_km != null) {
      metaParts.push(`${formatDistance(location.distance_km)} from Auckland`);
    } else {
      const distanceKm = distanceForLocation(location);
      if (distanceKm != null) {
        metaParts.push(`${formatDistance(distanceKm)} from Auckland`);
      }
    }
    if (treeYears != null) {
      metaParts.push(`≈${formatCount(treeYears)} tree-years to offset`);
    }
    elements.hoverMeta.textContent = metaParts.join(" · ");

    if (isMobileLayout()) {
      window.requestAnimationFrame(() => {
        elements.hoverCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
    }
  }

  function distanceForLocation(location) {
    if (location?.distance_km != null) return location.distance_km;
    if (location?.lat == null || location?.lon == null) return null;
    return haversineKm(location.lat, location.lon, auckland.lat, auckland.lon);
  }

  function distanceLineFeatures() {
    return allLocations
      .filter((location) => {
        if (location.lat == null || location.lon == null) return false;
        if (distanceMode) return location.co2e_kg > 0;
        return location.id === selectedId;
      })
      .map((location) => {
        const display = displayForLocation(location);
        const distanceKm = distanceForLocation(location);
        return {
          type: "Feature",
          properties: {
            id: location.id,
            affiliation: location.affiliation,
            distance_km: distanceKm ?? 0,
            selected: location.id === selectedId ? 1 : 0,
          },
          geometry: {
            type: "LineString",
            coordinates: greatCircleArc(display.lat, display.lon, auckland.lat, auckland.lon),
          },
        };
      });
  }

  function aucklandFeature() {
    return {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: { label: auckland.label },
          geometry: {
            type: "Point",
            coordinates: [auckland.lon, auckland.lat],
          },
        },
      ],
    };
  }

  function showLineTooltip(text, point) {
    if (!elements.lineTooltip) return;
    elements.lineTooltip.textContent = text;
    elements.lineTooltip.hidden = false;
    elements.lineTooltip.style.left = `${point.x + 12}px`;
    elements.lineTooltip.style.top = `${point.y + 12}px`;
  }

  function hideLineTooltip() {
    if (!elements.lineTooltip) return;
    elements.lineTooltip.hidden = true;
  }

  function locationFeatures() {
    return allLocations.map((location) => {
      const highlighted = location.co2e_kg > 0;
      const display = displayForLocation(location);
      const radius = radiusFor(location);
      const selected = location.id === selectedId;
      const hovered = location.id === hoveredId;
      const dimmed = Boolean(selectedId && !selected && highlighted);
      const offsetShare = locationOffsetShare(location);
      return {
        type: "Feature",
        properties: {
          id: location.id,
          affiliation: location.affiliation,
          co2e_kg: location.co2e_kg,
          highlighted: highlighted ? 1 : 0,
          selected: selected ? 1 : 0,
          hovered: hovered ? 1 : 0,
          offset_share: offsetShare,
          sort_key: selected ? 1e9 + (location.co2e_kg || 0) : location.co2e_kg || 0,
          radius: selected ? radius + 3 : hovered ? radius + 2 : radius,
          color: colorFor(location, highlighted),
          opacity: highlighted
            ? selected
              ? 0.95
              : dimmed
                ? 0.22
                : hovered
                  ? 0.9
                  : 0.82
            : 0.2,
        },
        geometry: {
          type: "Point",
          coordinates: [display.lon, display.lat],
        },
      };
    });
  }

  function upsertMapData() {
    if (!mapReady) return;
    const showLines = distanceMode || Boolean(selectedId);
    map.getSource("locations")?.setData({
      type: "FeatureCollection",
      features: locationFeatures(),
    });
    map.getSource("distance-lines")?.setData({
      type: "FeatureCollection",
      features: showLines ? distanceLineFeatures() : [],
    });
    updateOffsetSlices();
    map.setLayoutProperty("distance-lines-visible", "visibility", showLines ? "visible" : "none");
    map.setLayoutProperty("distance-lines-hit", "visibility", showLines ? "visible" : "none");
    map.setLayoutProperty("auckland-circle", "visibility", showLines ? "visible" : "none");
  }

  function flyToLocation(location, { zoom = null, duration = 1400 } = {}) {
    if (!mapReady || !location) return;
    const display = displayForLocation(location);
    map.flyTo({
      center: [display.lon, display.lat],
      zoom: zoom ?? Math.max(map.getZoom(), 4),
      duration,
      essential: true,
    });
  }

  function launchFireworksAt(location) {
    const display = displayForLocation(location);
    fireworks.resize();
    const point = map.project([display.lon, display.lat]);
    fireworks.celebrateAt(point.x, point.y);
  }

  function celebrateOffsetRegistration(attendee) {
    if (!attendee?.location_id || !mapReady) {
      scheduleMapUpdate();
      return;
    }
    const location = locationById(attendee.location_id);
    if (!location) {
      scheduleMapUpdate();
      return;
    }

    if (celebrateTimer) window.clearTimeout(celebrateTimer);
    elements.offsetTracker?.classList.add("emissions-offset-tracker--celebrate");
    elements.offsetForm?.classList.add("emissions-offset-register--celebrate");
    celebrateTimer = window.setTimeout(() => {
      elements.offsetTracker?.classList.remove("emissions-offset-tracker--celebrate");
      elements.offsetForm?.classList.remove("emissions-offset-register--celebrate");
      celebrateTimer = null;
    }, 4500);

    const targetZoom = Math.min(
      MAX_ZOOM,
      Math.max(map.getZoom(), isMobileLayout() ? 4.8 : 6)
    );
    map.once("moveend", () => {
      launchFireworksAt(location);
      scheduleMapUpdate();
    });
    launchFireworksAt(location);
    flyToLocation(location, { zoom: targetZoom, duration: 1400 });
  }

  function selectLocation(id, { fly = false, toggle = false } = {}) {
    selectedId = toggle && selectedId === id ? null : id;
    renderHoverCard(locationById(selectedId));
    renderBarChart();
    renderRankings();
    upsertMapData();
    if (fly && selectedId) flyToLocation(locationById(selectedId));
    return selectedId;
  }

  function setRankMode(mode) {
    rankMode = mode;
    renderBarChart();
    renderRankings();
  }

  function setDistanceMode(enabled) {
    distanceMode = Boolean(enabled);
    upsertMapData();
    renderLegend();
  }

  function setIncludeNonSpeakers(enabled) {
    if (!hasDelegatePool) return;
    includeNonSpeakers = Boolean(enabled);
    applyPool();
    offsetTracker?.refreshAttendees();
    renderSidebar();
    upsertMapData();
    renderHoverCard(null);
  }

  function renderSidebar() {
    renderHeadline();
    renderContext();
    renderModeBreakdown();
    renderLegend();
    renderBarChart();
    renderRankings();
    renderAssumptions();
  }

  map.on("load", () => {
    mapReady = true;
    map.setSky?.({
      "sky-color": "#87CEEB",
      "sky-horizon-blend": 0.6,
      "horizon-color": "#ffffff",
      "horizon-fog-blend": 0.4,
      "fog-color": "#ffffff",
      "fog-ground-blend": 0.3,
    });

    map.addSource("locations", {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
    });
    map.addSource("distance-lines", {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
    });
    map.addSource("auckland", {
      type: "geojson",
      data: aucklandFeature(),
    });
    map.addSource("offset-slices", {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
    });

    map.addLayer({
      id: "distance-lines-visible",
      type: "line",
      source: "distance-lines",
      layout: { visibility: "none" },
      paint: {
        "line-color": "#1f6f8b",
        "line-opacity": [
          "case",
          ["==", ["get", "selected"], 1],
          0.92,
          0.14,
        ],
        "line-width": [
          "case",
          ["==", ["get", "selected"], 1],
          3,
          1.2,
        ],
      },
    });
    map.addLayer({
      id: "distance-lines-hit",
      type: "line",
      source: "distance-lines",
      layout: { visibility: "none" },
      paint: {
        "line-color": "#000000",
        "line-opacity": 0.01,
        "line-width": 10,
      },
    });
    map.addLayer({
      id: "auckland-circle",
      type: "circle",
      source: "auckland",
      layout: { visibility: "none" },
      paint: {
        "circle-radius": 7,
        "circle-color": "#1f6f8b",
        "circle-stroke-width": 2,
        "circle-stroke-color": "#ffffff",
      },
    });

    map.addLayer({
      id: "locations-circle",
      type: "circle",
      source: "locations",
      layout: {
        "circle-sort-key": ["get", "sort_key"],
      },
      paint: {
        "circle-radius": ["get", "radius"],
        "circle-color": ["get", "color"],
        "circle-opacity": ["get", "opacity"],
        "circle-stroke-width": [
          "case",
          ["==", ["get", "selected"], 1],
          3,
          ["==", ["get", "hovered"], 1],
          2.5,
          1.5,
        ],
        "circle-stroke-color": "#ffffff",
      },
    });

    map.addLayer({
      id: "locations-offset-slices",
      type: "fill",
      source: "offset-slices",
      layout: {
        "fill-sort-key": ["get", "sort_key"],
      },
      paint: {
        "fill-color": "#2d8a4e",
        "fill-opacity": 0.95,
      },
    });

    upsertMapData();
  });

  map.on("zoom", scheduleSliceRefresh);
  map.on("move", scheduleSliceRefresh);
  map.on("rotate", scheduleSliceRefresh);
  map.on("moveend", scheduleSliceRefresh);

  map.on("mouseenter", "locations-circle", (event) => {
    map.getCanvas().style.cursor = "pointer";
    const id = event.features?.[0]?.properties?.id;
    if (!id || id === hoveredId) return;
    hoveredId = id;
    renderHoverCard(locationById(id));
    upsertMapData();
  });

  map.on("mouseleave", "locations-circle", () => {
    map.getCanvas().style.cursor = "";
    hoveredId = selectedId;
    renderHoverCard(locationById(hoveredId));
    upsertMapData();
  });

  map.on("click", "locations-circle", (event) => {
    const id = event.features?.[0]?.properties?.id;
    if (id) selectLocation(id, { fly: true, toggle: true });
  });

  map.on("click", (event) => {
    const hit = map.queryRenderedFeatures(event.point, { layers: ["locations-circle"] });
    if (hit.length) return;
    if (!selectedId) return;
    selectedId = null;
    hoveredId = null;
    renderHoverCard(null);
    renderBarChart();
    renderRankings();
    upsertMapData();
  });

  map.on("mouseenter", "distance-lines-hit", (event) => {
    map.getCanvas().style.cursor = "help";
    const props = event.features?.[0]?.properties;
    if (!props) return;
    showLineTooltip(
      `${props.affiliation}: ${formatDistance(Number(props.distance_km))} from Auckland`,
      event.point
    );
  });

  map.on("mousemove", "distance-lines-hit", (event) => {
    const props = event.features?.[0]?.properties;
    if (!props) return;
    showLineTooltip(
      `${props.affiliation}: ${formatDistance(Number(props.distance_km))} from Auckland`,
      event.point
    );
  });

  map.on("mouseleave", "distance-lines-hit", () => {
    map.getCanvas().style.cursor = "";
    hideLineTooltip();
  });

  offsetTracker = createOffsetTracker({
    elements: {
      form: elements.offsetForm,
      query: elements.offsetQuery,
      suggestions: elements.offsetSuggestions,
      registerButton: elements.offsetRegister,
      status: elements.offsetStatus,
      fill: elements.offsetTrackerFill,
      label: elements.offsetTrackerLabel,
    },
    getAttendees: currentAttendees,
    getHeadline: () => headline,
    onChange: () => scheduleMapUpdate(),
    onRegisterSuccess: celebrateOffsetRegistration,
  });

  applyPool();
  void offsetTracker.init();
  renderSidebar();

  return {
    setRankMode,
    setDistanceMode,
    setIncludeNonSpeakers,
    hasDelegatePool,
    selectLocation,
    renderSidebar,
    resize: () => {
      map.resize();
      fireworks.resize();
    },
  };
}
