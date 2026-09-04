import { SITE_BASE_PATH } from "./config.js";

/** Discrete offset-progress palette: low pledge share → high. */
export const OFFSET_PROGRESS_PALETTE = [
  "#ff5117", // tiger-flame
  "#ff7547", // coral-glow
  "#ff9c7a", // tangerine-dream
  "#ffaf94", // powder-blush
  "#ffc2ad", // powder-blush-2
  "#dccf9d", // vanilla-custard
  "#b7c384", // muted-olive
  "#91b66a", // muted-olive-2
  "#76ac3c", // bright-fern
  "#5aa20d", // bright-fern-2
];

export const OFFSET_RED = OFFSET_PROGRESS_PALETTE[0];
export const OFFSET_GREEN = OFFSET_PROGRESS_PALETTE[OFFSET_PROGRESS_PALETTE.length - 1];

const NATIVE_COUNTRY_LAYER = "countries-fill";
const TERRITORY_LAYER = "territory-offset-fill";
const NATIVE_COUNTRY_PROP = "ADM0_A3";
const DEFAULT_UNCLUSTERED = "#D8E8F4";

function resolveAssetUrl(path) {
  const trimmed = String(path || "").trim();
  if (!trimmed) return "";
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  const base = SITE_BASE_PATH || "/";
  const relative = trimmed.replace(/^\//, "");
  return `${base}${relative}`;
}

export function mixChannel(low, high, share) {
  const parse = (hex) => [
    Number.parseInt(hex.slice(1, 3), 16),
    Number.parseInt(hex.slice(3, 5), 16),
    Number.parseInt(hex.slice(5, 7), 16),
  ];
  const [r1, g1, b1] = parse(low);
  const [r2, g2, b2] = parse(high);
  const t = Math.max(0, Math.min(1, share));
  const channel = (a, b) => Math.round(a + (b - a) * t);
  const hex = (value) => value.toString(16).padStart(2, "0");
  return `#${hex(channel(r1, r2))}${hex(channel(g1, g2))}${hex(channel(b1, b2))}`;
}

export function colourForOffsetShare(share, palette = OFFSET_PROGRESS_PALETTE) {
  const proportion = Math.max(0, Math.min(1, Number(share) || 0));
  const index = Math.min(palette.length - 1, Math.floor(proportion * palette.length));
  return palette[index];
}

export function buildOffsetStepColourExpression(
  palette = OFFSET_PROGRESS_PALETTE,
  property = "offset_share"
) {
  const expression = ["step", ["coalesce", ["get", property], 0], palette[0]];
  for (let index = 1; index < palette.length; index += 1) {
    expression.push(index / palette.length, palette[index]);
  }
  return expression;
}

function buildMatchColourExpression(iso3ToColour, fallback) {
  const expression = ["match", ["get", NATIVE_COUNTRY_PROP]];
  for (const [iso3, colour] of iso3ToColour) {
    expression.push(iso3, colour);
  }
  expression.push(fallback);
  return expression;
}

function pointInRing(lng, lat, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    const intersects =
      yi > lat !== yj > lat &&
      lng < ((xj - xi) * (lat - yi)) / (yj - yi || Number.EPSILON) + xi;
    if (intersects) inside = !inside;
  }
  return inside;
}

function pointInGeometry(lng, lat, geometry) {
  if (!geometry) return false;
  if (geometry.type === "Polygon") {
    const [outer, ...holes] = geometry.coordinates;
    if (!pointInRing(lng, lat, outer)) return false;
    return holes.every((hole) => !pointInRing(lng, lat, hole));
  }
  if (geometry.type === "MultiPolygon") {
    return geometry.coordinates.some((polygon) =>
      pointInGeometry(lng, lat, { type: "Polygon", coordinates: polygon })
    );
  }
  return false;
}

export function createCountryChoropleth(map, options = {}) {
  const {
    boundariesPath = "data/geography/country_boundaries.geojson",
    colourPalette = OFFSET_PROGRESS_PALETTE,
    getClusterShare = () => 0,
    getIso3ToCluster = () => ({}),
    getClusterLabels = () => ({}),
    getCountryToCluster = () => ({}),
    getTerritoryOverlayIso2 = () => [],
    beforeLayerId = "distance-lines-visible",
  } = options;

  const palette = colourPalette.length ? colourPalette : OFFSET_PROGRESS_PALETTE;
  const colourHigh = palette[palette.length - 1];
  const stepColourExpression = buildOffsetStepColourExpression(palette);

  let baseFeatures = [];
  let ready = false;
  let visible = true;
  let tooltipEl = null;
  let hoverHandlersBound = false;
  let nativeMode = false;
  let territoryHitFeatures = [];

  function rebuildTerritoryHitFeatures() {
    const overlayCodes = new Set(territoryOverlayCodes());
    territoryHitFeatures = baseFeatures
      .filter((feature) =>
        overlayCodes.has(String(feature.properties?.iso_a2 || "").toUpperCase())
      )
      .map((feature) => {
        const iso = feature.properties?.iso_a2;
        return {
          geometry: feature.geometry,
          label: clusterLabelForCountry(iso),
        };
      })
      .filter((entry) => entry.label);
  }

  function territoryLabelAtLngLat(lngLat) {
    const lng = lngLat.lng;
    const lat = lngLat.lat;
    for (const entry of territoryHitFeatures) {
      if (pointInGeometry(lng, lat, entry.geometry)) return entry.label;
    }
    return "";
  }

  function ensureTooltip() {
    if (tooltipEl) return tooltipEl;
    const container = map.getContainer();
    tooltipEl = document.createElement("div");
    tooltipEl.className = "country-choropleth-tooltip";
    tooltipEl.hidden = true;
    container.appendChild(tooltipEl);
    return tooltipEl;
  }

  function hideTooltip() {
    if (!tooltipEl) return;
    tooltipEl.hidden = true;
    map.getCanvas().style.cursor = "";
  }

  function showTooltip(label, point) {
    const el = ensureTooltip();
    el.textContent = label;
    el.hidden = false;
    const offset = 12;
    el.style.left = `${point.x + offset}px`;
    el.style.top = `${point.y + offset}px`;
    map.getCanvas().style.cursor = "pointer";
  }

  function labelForIso3(iso3) {
    const code = String(iso3 || "").trim().toUpperCase();
    const clusterId = getIso3ToCluster()[code];
    if (!clusterId) return "";
    return getClusterLabels()[clusterId] || clusterId;
  }

  function clusterLabelForCountry(isoCode) {
    const countryToCluster = getCountryToCluster();
    const clusterLabels = getClusterLabels();
    const code = String(isoCode || "").trim().toUpperCase();
    const clusterId = countryToCluster[code];
    if (!clusterId) return "";
    return clusterLabels[clusterId] || clusterId;
  }

  function clusterShareForCountry(isoCode) {
    const countryToCluster = getCountryToCluster();
    const code = String(isoCode || "").trim().toUpperCase();
    const clusterId = countryToCluster[code];
    if (!clusterId) return 0;
    return getClusterShare(clusterId) || 0;
  }

  function territoryOverlayCodes() {
    const countryToCluster = getCountryToCluster();
    const configured = (getTerritoryOverlayIso2() || [])
      .map((code) => String(code || "").trim().toUpperCase())
      .filter(Boolean);
    return configured.filter((code) => countryToCluster[code]);
  }

  function nativeIso3Colours() {
    const colours = new Map();
    for (const [iso3, clusterId] of Object.entries(getIso3ToCluster())) {
      const code = String(iso3 || "").trim().toUpperCase();
      if (!code) continue;
      const share = getClusterShare(clusterId) || 0;
      colours.set(code, colourForOffsetShare(share, palette));
    }
    return colours;
  }

  function territoryFeatureCollection() {
    const overlayCodes = new Set(territoryOverlayCodes());
    return {
      type: "FeatureCollection",
      features: baseFeatures
        .filter((feature) => overlayCodes.has(String(feature.properties?.iso_a2 || "").toUpperCase()))
        .map((feature) => {
          const iso = feature.properties?.iso_a2;
          const code = String(iso || "").trim().toUpperCase();
          const clusterId = getCountryToCluster()[code] || "";
          const offsetShare = clusterId ? clusterShareForCountry(iso) : 0;
          return {
            ...feature,
            properties: {
              ...feature.properties,
              in_cluster: clusterId ? 1 : 0,
              cluster_id: clusterId,
              cluster_label: clusterLabelForCountry(iso),
              offset_share: offsetShare,
            },
          };
        }),
    };
  }

  function featureCollection() {
    const countryToCluster = getCountryToCluster();
    return {
      type: "FeatureCollection",
      features: baseFeatures.map((feature) => {
        const iso = feature.properties?.iso_a2;
        const code = String(iso || "").trim().toUpperCase();
        const clusterId = countryToCluster[code] || "";
        const inCluster = clusterId ? 1 : 0;
        const offsetShare = inCluster ? clusterShareForCountry(iso) : 0;
        return {
          ...feature,
          properties: {
            ...feature.properties,
            in_cluster: inCluster,
            cluster_id: clusterId,
            cluster_label: clusterLabelForCountry(iso),
            offset_share: offsetShare,
          },
        };
      }),
    };
  }

  function updateNativeLayer() {
    if (!map.getLayer(NATIVE_COUNTRY_LAYER)) return;
    const colours = nativeIso3Colours();
    map.setPaintProperty(
      NATIVE_COUNTRY_LAYER,
      "fill-color",
      buildMatchColourExpression(colours, DEFAULT_UNCLUSTERED)
    );
    map.setPaintProperty(NATIVE_COUNTRY_LAYER, "fill-opacity", visible ? 0.55 : 0);
  }

  function ensureTerritoryLayer() {
    if (!nativeMode || !baseFeatures.length) return;
    if (!map.getSource("territory-offset-boundaries")) {
      map.addSource("territory-offset-boundaries", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
    }
    if (!map.getLayer(TERRITORY_LAYER)) {
      map.addLayer(
        {
          id: TERRITORY_LAYER,
          type: "fill",
          source: "territory-offset-boundaries",
          layout: {
            visibility: visible ? "visible" : "none",
          },
          paint: {
            "fill-color": stepColourExpression,
            "fill-opacity": [
              "case",
              ["==", ["get", "in_cluster"], 1],
              0.55,
              0,
            ],
            "fill-antialias": true,
          },
        },
        beforeLayerId
      );
    }
  }

  function updateTerritoryLayer() {
    if (!nativeMode) return;
    ensureTerritoryLayer();
    rebuildTerritoryHitFeatures();
    map.getSource("territory-offset-boundaries")?.setData(territoryFeatureCollection());
    if (map.getLayer(TERRITORY_LAYER)) {
      map.setLayoutProperty(TERRITORY_LAYER, "visibility", visible ? "visible" : "none");
      map.setPaintProperty(TERRITORY_LAYER, "fill-color", stepColourExpression);
      map.setPaintProperty(TERRITORY_LAYER, "fill-opacity", [
        "case",
        ["==", ["get", "in_cluster"], 1],
        0.55,
        0,
      ]);
      map.setPaintProperty(TERRITORY_LAYER, "fill-antialias", true);
    }
  }

  function ensureGeoJsonLayer() {
    if (!map.getSource("country-offset-boundaries")) {
      map.addSource("country-offset-boundaries", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
    }
    if (!map.getLayer("country-offset-fill")) {
      map.addLayer(
        {
          id: "country-offset-fill",
          type: "fill",
          source: "country-offset-boundaries",
          layout: {
            visibility: visible ? "visible" : "none",
          },
          paint: {
            "fill-color": stepColourExpression,
            "fill-opacity": [
              "case",
              ["==", ["get", "in_cluster"], 1],
              0.72,
              0,
            ],
            "fill-antialias": true,
          },
        },
        beforeLayerId
      );
    }
  }

  function updateGeoJsonLayer() {
    ensureGeoJsonLayer();
    map.getSource("country-offset-boundaries")?.setData(featureCollection());
    const visibility = visible ? "visible" : "none";
    if (map.getLayer("country-offset-fill")) {
      map.setLayoutProperty("country-offset-fill", "visibility", visibility);
    }
  }

  function bindHoverHandlers() {
    if (hoverHandlersBound) return;
    hoverHandlersBound = true;

    const layers = nativeMode
      ? [TERRITORY_LAYER, NATIVE_COUNTRY_LAYER]
      : ["country-offset-fill"];

    for (const layerId of layers) {
      map.on("mousemove", layerId, (event) => {
        const territoryLabel = territoryLabelAtLngLat(event.lngLat);
        const feature = event.features?.[0];
        if (!feature && !territoryLabel) {
          hideTooltip();
          return;
        }
        const label =
          territoryLabel ||
          (layerId === NATIVE_COUNTRY_LAYER
            ? labelForIso3(feature?.properties?.[NATIVE_COUNTRY_PROP])
            : feature?.properties?.cluster_label || feature?.properties?.name || "");
        if (!label) {
          hideTooltip();
          return;
        }
        showTooltip(label, event.point);
      });

      map.on("mouseleave", layerId, () => {
        hideTooltip();
      });
    }
  }

  async function loadBoundaries() {
    const url = resolveAssetUrl(boundariesPath);
    const response = await fetch(url, { cache: "force-cache" });
    if (!response.ok) {
      throw new Error(`Could not load country boundaries (${response.status})`);
    }
    const payload = await response.json();
    baseFeatures = (payload.features || []).filter((feature) => feature.properties?.iso_a2);
    return baseFeatures.length;
  }

  async function load() {
    nativeMode = Boolean(map.getLayer(NATIVE_COUNTRY_LAYER));
    if (nativeMode) {
      try {
        await loadBoundaries();
      } catch (error) {
        console.warn("Territory overlay boundaries unavailable:", error);
      }
      ready = true;
      bindHoverHandlers();
      update();
      return Object.keys(getIso3ToCluster()).length;
    }

    baseFeatures = [];
    const count = await loadBoundaries();
    ready = true;
    bindHoverHandlers();
    update();
    return count;
  }

  function update() {
    if (!ready) return;
    if (nativeMode) {
      updateNativeLayer();
      updateTerritoryLayer();
      return;
    }
    updateGeoJsonLayer();
  }

  function ensurePulseLayers() {
    if (!map.getSource("country-offset-pulse")) {
      map.addSource("country-offset-pulse", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
    }
    if (!map.getLayer("country-offset-pulse-fill")) {
      map.addLayer(
        {
          id: "country-offset-pulse-fill",
          type: "fill",
          source: "country-offset-pulse",
          paint: {
            "fill-color": colourHigh,
            "fill-opacity": 0,
          },
        },
        beforeLayerId
      );
    }
    if (!map.getLayer("country-offset-pulse-line")) {
      map.addLayer(
        {
          id: "country-offset-pulse-line",
          type: "line",
          source: "country-offset-pulse",
          paint: {
            "line-color": colourHigh,
            "line-width": 2.5,
            "line-opacity": 0,
          },
        },
        beforeLayerId
      );
    }
  }

  let pulseRaf = 0;
  let pulseToken = 0;

  function clearCountryPulse() {
    pulseToken += 1;
    if (pulseRaf) {
      window.cancelAnimationFrame(pulseRaf);
      pulseRaf = 0;
    }
    if (!map.getSource("country-offset-pulse")) return;
    map.getSource("country-offset-pulse").setData({ type: "FeatureCollection", features: [] });
    if (map.getLayer("country-offset-pulse-fill")) {
      map.setPaintProperty("country-offset-pulse-fill", "fill-opacity", 0);
    }
    if (map.getLayer("country-offset-pulse-line")) {
      map.setPaintProperty("country-offset-pulse-line", "line-opacity", 0);
    }
  }

  /**
   * Flash matching countries bright green, then ease out so the updated
   * choropleth colour underneath becomes the lasting state.
   */
  function pulseCountries(iso2Codes, { durationMs = 2400, peakMs = 700 } = {}) {
    const codes = new Set(
      (Array.isArray(iso2Codes) ? iso2Codes : [iso2Codes])
        .map((code) => String(code || "").trim().toUpperCase())
        .filter(Boolean)
    );
    if (!ready || !codes.size || !baseFeatures.length) return false;

    ensurePulseLayers();
    const features = baseFeatures.filter((feature) =>
      codes.has(String(feature.properties?.iso_a2 || "").toUpperCase())
    );
    if (!features.length) return false;

    clearCountryPulse();
    const token = pulseToken;
    map.getSource("country-offset-pulse").setData({
      type: "FeatureCollection",
      features,
    });

    const started = performance.now();
    const tick = (now) => {
      if (token !== pulseToken) return;
      const elapsed = now - started;
      let opacity = 0;
      if (elapsed <= peakMs) {
        opacity = 0.15 + 0.7 * (elapsed / peakMs);
      } else if (elapsed <= durationMs) {
        const t = (elapsed - peakMs) / Math.max(1, durationMs - peakMs);
        opacity = 0.85 * (1 - t) * (1 - t);
      }
      if (map.getLayer("country-offset-pulse-fill")) {
        map.setPaintProperty("country-offset-pulse-fill", "fill-opacity", opacity);
      }
      if (map.getLayer("country-offset-pulse-line")) {
        map.setPaintProperty(
          "country-offset-pulse-line",
          "line-opacity",
          Math.min(1, opacity + 0.15)
        );
      }
      if (elapsed < durationMs) {
        pulseRaf = window.requestAnimationFrame(tick);
      } else {
        clearCountryPulse();
      }
    };
    pulseRaf = window.requestAnimationFrame(tick);
    return true;
  }

  function setVisible(enabled) {
    visible = Boolean(enabled);
    if (nativeMode) {
      updateNativeLayer();
      updateTerritoryLayer();
    } else if (map.getLayer("country-offset-fill")) {
      map.setLayoutProperty(
        "country-offset-fill",
        "visibility",
        visible ? "visible" : "none"
      );
    }
    if (!visible) hideTooltip();
  }

  function renderLegend(container, { title = "Pledge coverage by emissions" } = {}) {
    if (!container) return;
    container.insertAdjacentHTML(
      "beforeend",
      `
      <div class="offset-choropleth-legend">
        <h3>${title}</h3>
        <div class="offset-choropleth-gradient offset-choropleth-gradient--discrete"></div>
        <div class="offset-choropleth-labels">
          <span>None pledged</span>
          <span>All emissions pledged</span>
        </div>
        <p class="legend-note">Colour shows the share of each region's travel emissions covered by offset pledges.</p>
      </div>`
    );
  }

  return {
    load,
    update,
    setVisible,
    renderLegend,
    pulseCountries,
    clearCountryPulse,
    colourForOffsetShare,
    isReady: () => ready,
    usesNativeLayer: () => nativeMode,
  };
}
