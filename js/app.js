import { SITE_DATA } from "./locations.js";
import { TALKS_DATA } from "./talks.js";
import { TALK_SIMILARITIES } from "./talk-similarities.js";
import { EMISSIONS_DATA } from "./emissions-data.js";
import { SPEAKER_PROFILES } from "./speaker-profiles.js";
import { NON_SPEAKING_DELEGATE_GROUPS } from "./non-speaking-delegates.js";
import {
  MAP_EXCLUDED_AFFILIATION_KEYS,
  MAP_EXCLUDED_NAMES,
} from "./map-excluded-names.js";
import { createMapView } from "./map.js";
import { createNetworkView } from "./network.js";
import { createEmissionsView } from "./emissions-view.js";
import { createShareView } from "./more.js";
import { escapeHtml, buildDelegateIndex, applyAffiliationGeocodeOverrides, setMapExclusions, filterEmissionsPool } from "./utils.js";

setMapExclusions({
  names: MAP_EXCLUDED_NAMES,
  affiliationKeys: MAP_EXCLUDED_AFFILIATION_KEYS,
});

if (EMISSIONS_DATA.speakers) {
  EMISSIONS_DATA.speakers = filterEmissionsPool(EMISSIONS_DATA.speakers);
}
if (EMISSIONS_DATA.all_delegates) {
  EMISSIONS_DATA.all_delegates = filterEmissionsPool(EMISSIONS_DATA.all_delegates);
}

SITE_DATA.locations = applyAffiliationGeocodeOverrides(SITE_DATA.locations);
if (EMISSIONS_DATA.all_delegates?.locations) {
  EMISSIONS_DATA.all_delegates.locations = applyAffiliationGeocodeOverrides(
    EMISSIONS_DATA.all_delegates.locations
  );
}
if (EMISSIONS_DATA.speakers?.locations) {
  EMISSIONS_DATA.speakers.locations = applyAffiliationGeocodeOverrides(
    EMISSIONS_DATA.speakers.locations
  );
}
const locations = SITE_DATA.locations;
const meta = SITE_DATA.meta;
const delegateIndex = buildDelegateIndex(NON_SPEAKING_DELEGATE_GROUPS);
const delegateEmissionsLocations = EMISSIONS_DATA.all_delegates?.locations || [];

const $ = (id) => document.getElementById(id);
const els = {
  title: $("site-title"),
  summary: $("site-summary"),
  query: $("search-query"),
  suggestions: $("search-suggestions"),
  status: $("search-status"),
  form: $("search-form"),
  clear: $("btn-clear-search"),
  stats: $("stats-card"),
  mapLegend: $("map-legend"),
  resultsTitle: $("results-title"),
  results: $("results-list"),
  hoverCard: $("hover-card"),
  hoverAffiliation: $("hover-affiliation"),
  hoverMeta: $("hover-meta"),
  hoverSpeakers: $("hover-speakers"),
  mapTalkBack: $("map-talk-back"),
  mapTalkDetail: $("map-talk-detail"),
  mapTalkTitle: $("map-talk-title"),
  mapTalkAuthors: $("map-talk-authors"),
  mapTalkAbstract: $("map-talk-abstract"),
  mapLocationInfoBtn: $("map-location-info-btn"),
  mapLocationInfo: $("map-location-info"),
  mapLocationFixLink: $("map-location-fix-link"),
  connectionsSizeToggle: $("connections-size-toggle"),
  mapIncludeNonSpeakingDelegates: $("map-include-non-speaking-delegates"),
  mapPanel: $("map-panel"),
  networkPanel: $("network-panel"),
  emissionsPanel: $("emissions-panel"),
  methodsPanel: $("methods-panel"),
  mapStage: $("map-stage"),
  networkStage: $("network-stage"),
  networkHintBanner: $("network-hint-banner"),
  networkHintDismiss: $("network-hint-dismiss"),
  emissionsStage: $("emissions-stage"),
  shareStage: $("share-stage"),
  mapContainer: $("map"),
  networkSvg: $("network-svg"),
  networkSummary: $("network-summary"),
  networkCard: $("network-card"),
  networkCardTitle: $("network-card-title"),
  networkCardMeta: $("network-card-meta"),
  networkCardTalks: $("network-card-talks"),
  networkTalkBack: $("network-talk-back"),
  networkTalkDetail: $("network-talk-detail"),
  networkTalkTitle: $("network-talk-title"),
  networkTalkAuthors: $("network-talk-authors"),
  networkTalkAbstract: $("network-talk-abstract"),
  networkSimilarTalks: $("network-similar-talks"),
  networkSimilarStatus: $("network-similar-status"),
  networkSimilarList: $("network-similar-list"),
  networkCardContacts: $("network-card-contacts"),
  networkDataInfoBtn: $("network-data-info-btn"),
  networkDataInfo: $("network-data-info"),
  networkDataFixLink: $("network-data-fix-link"),
  networkDataRemovalLink: $("network-data-removal-link"),
  resetZoom: $("network-reset-zoom"),
  clearSelection: $("network-clear-selection"),
  networkCardClear: $("network-card-clear"),
  networkCardSlot: $("network-card-slot"),
  networkSearch: $("network-search-query"),
  networkSuggestions: $("network-suggestions"),
  networkSearchStatus: $("network-search-status"),
  networkSearchBtn: $("network-search-btn"),
  networkClearSearch: $("network-clear-search"),
  networkDensity: $("network-density"),
  networkLegendCoauthorship: $("network-legend-coauthorship"),
  networkLegendScale: $("network-legend-scale"),
  networkBarChart: $("network-bar-chart"),
  networkResults: $("network-results"),
  networkResultsTitle: $("network-results-title"),
  shareQr: $("share-qr"),
  shareUrl: $("share-url"),
  shareStatus: $("share-status"),
  emissionsHeadline: $("emissions-headline"),
  emissionsOffsetForm: $("emissions-offset-form"),
  emissionsOffsetQuery: $("emissions-offset-query"),
  emissionsOffsetSuggestions: $("emissions-offset-suggestions"),
  emissionsOffsetRegister: $("emissions-offset-register"),
  emissionsOffsetDelegateField: $("emissions-offset-delegate-field"),
  emissionsOffsetDelegateId: $("emissions-offset-delegate-id"),
  emissionsOffsetDelegateError: $("emissions-offset-delegate-error"),
  emissionsOffsetStatus: $("emissions-offset-status"),
  emissionsOffsetTracker: $("emissions-offset-tracker"),
  emissionsOffsetTrackerFill: $("emissions-offset-tracker-fill"),
  emissionsOffsetTrackerLabel: $("emissions-offset-tracker-label"),
  emissionsContext: $("emissions-context"),
  emissionsModeBreakdown: $("emissions-mode-breakdown"),
  emissionsLegend: $("emissions-legend"),
  emissionsBarChart: $("emissions-bar-chart"),
  emissionsResults: $("emissions-results"),
  emissionsResultsTitle: $("emissions-results-title"),
  emissionsAssumptions: $("emissions-assumptions"),
  emissionsMap: $("emissions-map"),
  emissionsLineTooltip: $("emissions-line-tooltip"),
  emissionsHoverCard: $("emissions-hover-card"),
  emissionsHoverAffiliation: $("emissions-hover-affiliation"),
  emissionsHoverMeta: $("emissions-hover-meta"),
  includeNonSpeakingDelegates: $("include-non-speaking-delegates"),
  emissionsDistanceToggle: $("emissions-distance-toggle"),
  tabButtons: [...document.querySelectorAll("[data-tab]")],
  networkModeButtons: [...document.querySelectorAll("[data-network-mode]")],
  emissionsModeButtons: [...document.querySelectorAll("[data-emissions-mode]")],
};

function renderStats() {
  const stats = meta.stats;
  els.title.textContent = meta.title;
  els.stats.innerHTML = [
    `<strong>${stats.location_count.toLocaleString()}</strong> affiliation locations on the map`,
    `<strong>${stats.mapped_speakers.toLocaleString()}</strong> / ${stats.total_speakers.toLocaleString()} speakers geocoded`,
    `<strong>${stats.mapped_talks.toLocaleString()}</strong> / ${stats.total_talks.toLocaleString()} talks geocoded`,
  ].join("<br>");
}

function renderResults({
  searchQuery,
  matchedIds,
  selectedId,
  selectLocation,
  locationList = locations,
}) {
  const searching = Boolean(searchQuery);
  const ordered = [...locationList].sort((a, b) => {
    const aMatch = matchedIds.has(a.id) ? 0 : 1;
    const bMatch = matchedIds.has(b.id) ? 0 : 1;
    if (aMatch !== bMatch) return aMatch - bMatch;
    if (b.speaker_count !== a.speaker_count) return b.speaker_count - a.speaker_count;
    return a.affiliation.localeCompare(b.affiliation, undefined, { sensitivity: "base" });
  });

  const visible = searching ? ordered.filter((location) => matchedIds.has(location.id)) : ordered;
  els.resultsTitle.textContent = searching
    ? `${visible.length.toLocaleString()} matching location${visible.length === 1 ? "" : "s"}`
    : "All locations";

  els.results.innerHTML = "";
  if (!visible.length) {
    els.results.innerHTML = `<p class="status">No locations match that search.</p>`;
    return;
  }

  for (const location of visible.slice(0, 200)) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "result-item";
    btn.dataset.id = location.id;
    btn.classList.toggle("selected", location.id === selectedId);
    btn.classList.toggle("dimmed", searching && !matchedIds.has(location.id));
    const metaText = location.delegate_only
      ? `${location.speaker_details?.length || location.speaker_count} non-speaking delegate${(location.speaker_details?.length || location.speaker_count) === 1 ? "" : "s"}`
      : (() => {
          const nonSpeaking = location.non_speaking_delegate_count || 0;
          const speakers = Math.max(0, location.speaker_count - nonSpeaking);
          const peopleLabel = nonSpeaking
            ? `${speakers} speaker${speakers === 1 ? "" : "s"} · ${nonSpeaking} non-speaking`
            : `${location.speaker_count} speaker${location.speaker_count === 1 ? "" : "s"}`;
          return `${peopleLabel} · ${location.talk_count} talk${location.talk_count === 1 ? "" : "s"} · ${(location.connection_count || 0).toLocaleString()} on author lists`;
        })();
    btn.innerHTML = `
      <div class="affiliation">${escapeHtml(location.affiliation)}</div>
      <div class="meta">${metaText}</div>
    `;
    btn.addEventListener("click", () => selectLocation(location.id));
    els.results.appendChild(btn);
  }

  if (visible.length > 200) {
    const note = document.createElement("p");
    note.className = "status";
    note.textContent = `Showing first 200 of ${visible.length.toLocaleString()} matches. Refine your search to narrow further.`;
    els.results.appendChild(note);
  }
}

function setStatus(message, isError = false) {
  els.status.textContent = message || "";
  els.status.classList.toggle("error", isError);
}

function ensureNetworkIndividualMode() {
  if (networkView.getMode() === "individual") return;
  els.networkModeButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.networkMode === "individual");
  });
  networkView.setMode("individual");
}

function showPersonInNetwork(name) {
  setTab("network");
  ensureNetworkIndividualMode();
  const nodeId = networkView.findNodeIdByName(name);
  if (nodeId) networkView.selectNode(nodeId, { focus: true });
}

function showAffiliationOnMap(locationId, speakerName) {
  setTab("map");
  if (locationId) {
    mapView.selectLocation(locationId, {
      fly: true,
      speakerName: speakerName || undefined,
    });
  }
}

const mapView = createMapView(
  SITE_DATA,
  {
    mapContainer: els.mapContainer,
    hoverCard: els.hoverCard,
    hoverAffiliation: els.hoverAffiliation,
    hoverMeta: els.hoverMeta,
    hoverSpeakers: els.hoverSpeakers,
    talkBack: els.mapTalkBack,
    talkDetail: els.mapTalkDetail,
    talkTitle: els.mapTalkTitle,
    talkAuthors: els.mapTalkAuthors,
    talkAbstract: els.mapTalkAbstract,
    talksData: TALKS_DATA,
    locationInfoBtn: els.mapLocationInfoBtn,
    locationInfo: els.mapLocationInfo,
    locationFixLink: els.mapLocationFixLink,
    legend: els.mapLegend,
    setStatus,
    renderResults,
    onShowInNetwork: showPersonInNetwork,
  },
  { delegateEmissionsLocations, delegateIndex }
);

const networkView = createNetworkView(SITE_DATA, {
  stage: els.networkStage,
  networkSvg: els.networkSvg,
  summary: els.networkSummary,
  card: els.networkCard,
  cardTitle: els.networkCardTitle,
  cardMeta: els.networkCardMeta,
  cardTalks: els.networkCardTalks,
  talkBack: els.networkTalkBack,
  talkDetail: els.networkTalkDetail,
  talkTitle: els.networkTalkTitle,
  talkAuthors: els.networkTalkAuthors,
  talkAbstract: els.networkTalkAbstract,
  similarTalks: els.networkSimilarTalks,
  similarStatus: els.networkSimilarStatus,
  similarList: els.networkSimilarList,
  talksData: TALKS_DATA,
  similaritiesData: TALK_SIMILARITIES,
  cardContacts: els.networkCardContacts,
  dataInfoBtn: els.networkDataInfoBtn,
  dataInfo: els.networkDataInfo,
  dataFixLink: els.networkDataFixLink,
  dataRemovalLink: els.networkDataRemovalLink,
  resultsWrap: $("network-results-wrap"),
  speakerProfiles: SPEAKER_PROFILES,
  resetZoom: els.resetZoom,
  clearSelection: els.clearSelection,
  cardClear: els.networkCardClear,
  cardSlot: els.networkCardSlot,
  legendCoauthorship: els.networkLegendCoauthorship,
  legendScale: els.networkLegendScale,
  barChart: els.networkBarChart,
  results: els.networkResults,
  resultsTitle: els.networkResultsTitle,
  searchInput: els.networkSearch,
  searchStatus: els.networkSearchStatus,
  onShowOnMap: showAffiliationOnMap,
});

const shareView = createShareView(SITE_DATA, {
  qrCanvas: els.shareQr,
  url: els.shareUrl,
  status: els.shareStatus,
});

const emissionsView = createEmissionsView(EMISSIONS_DATA, SITE_DATA, {
  mapContainer: els.emissionsMap,
  lineTooltip: els.emissionsLineTooltip,
  headline: els.emissionsHeadline,
  headlineTotal: $("emissions-total"),
  headlineAssumption: $("emissions-assumption"),
  headlineMeta: $("emissions-meta"),
  headlineDelegateNote: $("emissions-delegate-note"),
  delegateToggleWrap: $("emissions-delegate-toggle-wrap"),
  includeNonSpeakersToggle: els.includeNonSpeakingDelegates,
  offsetForm: els.emissionsOffsetForm,
  offsetQuery: els.emissionsOffsetQuery,
  offsetSuggestions: els.emissionsOffsetSuggestions,
  offsetRegister: els.emissionsOffsetRegister,
  offsetDelegateField: els.emissionsOffsetDelegateField,
  offsetDelegateId: els.emissionsOffsetDelegateId,
  offsetDelegateError: els.emissionsOffsetDelegateError,
  offsetStatus: els.emissionsOffsetStatus,
  offsetTracker: els.emissionsOffsetTracker,
  offsetTrackerFill: els.emissionsOffsetTrackerFill,
  offsetTrackerLabel: els.emissionsOffsetTrackerLabel,
  context: els.emissionsContext,
  modeBreakdown: els.emissionsModeBreakdown,
  legend: els.emissionsLegend,
  barChart: els.emissionsBarChart,
  results: els.emissionsResults,
  resultsTitle: els.emissionsResultsTitle,
  assumptions: els.emissionsAssumptions,
  hoverCard: els.emissionsHoverCard,
  hoverAffiliation: els.emissionsHoverAffiliation,
  hoverMeta: els.emissionsHoverMeta,
}, { delegateGroups: NON_SPEAKING_DELEGATE_GROUPS });

let activeTab = "map";

const layout = document.querySelector(".layout");
const TAB_STORAGE_KEY = "icrs-active-tab";
const VALID_TABS = new Set(["map", "network", "emissions", "methods", "share"]);
const NETWORK_HINT_STORAGE_KEY = "icrs-network-hint-dismissed";

function getStoredTab() {
  try {
    const stored = localStorage.getItem(TAB_STORAGE_KEY);
    return VALID_TABS.has(stored) ? stored : "map";
  } catch {
    return "map";
  }
}

function storeTab(tab) {
  try {
    localStorage.setItem(TAB_STORAGE_KEY, tab);
  } catch {
    /* private browsing */
  }
}

function isNetworkHintDismissed() {
  try {
    return Boolean(localStorage.getItem(NETWORK_HINT_STORAGE_KEY));
  } catch {
    return false;
  }
}

function dismissNetworkHint() {
  if (els.networkHintBanner) {
    els.networkHintBanner.hidden = true;
  }
  try {
    localStorage.setItem(NETWORK_HINT_STORAGE_KEY, "1");
  } catch {
    /* private browsing */
  }
}

function showNetworkHintIfNeeded() {
  if (!els.networkHintBanner || isNetworkHintDismissed()) return;
  els.networkHintBanner.hidden = false;
}

function tabForHash(hash) {
  if (!hash) return null;
  if (VALID_TABS.has(hash)) return hash;
  if (hash === "methods-panel" || hash === "methods-offsetting" || hash.startsWith("methods-")) {
    return "methods";
  }
  return null;
}

function navigateToHash({ scroll = true } = {}) {
  const hash = decodeURIComponent(location.hash.slice(1));
  const tab = tabForHash(hash);
  if (tab) setTab(tab);
  if (!hash || !scroll) return;

  requestAnimationFrame(() => {
    const target =
      document.getElementById(hash) || (hash === "methods-panel" ? els.methodsPanel : null);
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

function setTab(tab) {
  if (!VALID_TABS.has(tab)) tab = "map";
  activeTab = tab;
  storeTab(tab);
  els.tabButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === tab);
  });
  els.mapPanel.hidden = tab !== "map";
  els.networkPanel.hidden = tab !== "network";
  els.emissionsPanel.hidden = tab !== "emissions";
  els.methodsPanel.hidden = tab !== "methods";
  els.mapStage.hidden = tab !== "map";
  els.networkStage.hidden = tab !== "network";
  els.emissionsStage.hidden = tab !== "emissions";
  els.shareStage.hidden = tab !== "share";
  layout?.classList.toggle("layout-methods", tab === "methods");
  layout?.classList.toggle("layout-share", tab === "share");
  if (tab === "map") {
    mapView.resize();
  } else if (tab === "network") {
    requestAnimationFrame(() => networkView.resize());
    showNetworkHintIfNeeded();
  } else if (tab === "emissions") {
    requestAnimationFrame(() => {
      emissionsView.resize();
      emissionsView.refreshMap?.();
    });
  } else if (tab === "share") {
    shareView.render();
  }
}

els.tabButtons.forEach((button) => {
  button.addEventListener("click", () => setTab(button.dataset.tab));
});

els.networkModeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    els.networkModeButtons.forEach((item) => {
      item.classList.toggle("active", item === button);
    });
    networkView.setMode(button.dataset.networkMode);
  });
});

els.emissionsModeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    els.emissionsModeButtons.forEach((item) => {
      item.classList.toggle("active", item === button);
    });
    emissionsView.setRankMode(button.dataset.emissionsMode);
  });
});

if (els.emissionsDistanceToggle) {
  els.emissionsDistanceToggle.addEventListener("change", (event) => {
    emissionsView.setDistanceMode(event.target.checked);
  });
}

const hasDelegatePool = emissionsView.hasDelegatePool || mapView.hasDelegatePool;

function setIncludeNonSpeakingDelegates(enabled) {
  const include = Boolean(enabled);
  if (els.includeNonSpeakingDelegates) {
    els.includeNonSpeakingDelegates.checked = include;
  }
  if (els.mapIncludeNonSpeakingDelegates) {
    els.mapIncludeNonSpeakingDelegates.checked = include;
  }
  emissionsView.setIncludeNonSpeakers(include);
  mapView.setIncludeNonSpeakers(include);
}

if (els.includeNonSpeakingDelegates) {
  els.includeNonSpeakingDelegates.addEventListener("change", (event) => {
    setIncludeNonSpeakingDelegates(event.target.checked);
  });
}

if (els.mapIncludeNonSpeakingDelegates) {
  els.mapIncludeNonSpeakingDelegates.disabled = !hasDelegatePool;
  els.mapIncludeNonSpeakingDelegates.addEventListener("change", (event) => {
    setIncludeNonSpeakingDelegates(event.target.checked);
  });
}

if (hasDelegatePool) {
  setIncludeNonSpeakingDelegates(true);
}

els.connectionsSizeToggle.addEventListener("change", (event) => {
  const enabled = mapView.setConnectionsSize(event.target.checked);
  els.connectionsSizeToggle.checked = enabled;
});

let suggestionTimer = null;
els.query.addEventListener("input", () => {
  clearTimeout(suggestionTimer);
  const query = els.query.value;
  suggestionTimer = setTimeout(() => {
    renderSuggestions(mapView.buildSuggestions(query));
    mapView.applySearch(query, { fly: false });
  }, 180);
});

function renderSuggestions(items) {
  els.suggestions.innerHTML = "";
  if (!items.length) {
    els.suggestions.classList.remove("open");
    return;
  }

  items.forEach((item, index) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "suggestion" + (index === 0 ? " active" : "");
    btn.innerHTML = `${escapeHtml(item.label)}<small>${escapeHtml(item.detail)}</small>`;
    btn.addEventListener("mousedown", (event) => {
      event.preventDefault();
      els.query.value = item.query;
      mapView.applySearch(item.query);
      mapView.selectLocation(item.locationId, { speakerName: item.speakerName });
      els.suggestions.classList.remove("open");
    });
    els.suggestions.appendChild(btn);
  });
  els.suggestions.classList.add("open");
}

document.addEventListener("click", (event) => {
  if (!els.suggestions.contains(event.target) && event.target !== els.query) {
    els.suggestions.classList.remove("open");
  }
});

els.form.addEventListener("submit", (event) => {
  event.preventDefault();
  mapView.applySearch(els.query.value);
});

els.clear.addEventListener("click", () => {
  els.query.value = "";
  mapView.applySearch("");
  els.suggestions.classList.remove("open");
});

let networkSuggestionTimer = null;
els.networkSearch?.addEventListener("input", () => {
  clearTimeout(networkSuggestionTimer);
  const query = els.networkSearch.value;
  networkSuggestionTimer = setTimeout(() => {
    renderNetworkSuggestions(networkView.buildSuggestions(query));
    networkView.previewSearch(query);
  }, 180);
});

els.networkSearch?.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    networkView.applySearch(els.networkSearch.value);
  }
});

els.networkSearchBtn?.addEventListener("click", () => {
  networkView.applySearch(els.networkSearch.value);
});

els.networkDensity?.addEventListener("change", () => {
  networkView.setNodeLimit(els.networkDensity.value);
});

els.networkClearSearch?.addEventListener("click", () => {
  els.networkSearch.value = "";
  networkView.applySearch("");
  els.networkSuggestions?.classList.remove("open");
});

function renderNetworkSuggestions(items) {
  if (!els.networkSuggestions) return;
  els.networkSuggestions.innerHTML = "";
  if (!items.length) {
    els.networkSuggestions.classList.remove("open");
    return;
  }

  items.forEach((item, index) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "suggestion" + (index === 0 ? " active" : "");
    btn.innerHTML = `${escapeHtml(item.label)}<small>${escapeHtml(item.detail)}</small>`;
    btn.addEventListener("mousedown", (event) => {
      event.preventDefault();
      els.networkSearch.value = item.query;
      networkView.applySearch(item.query);
      networkView.selectNode(item.nodeId, { focus: true });
      els.networkSuggestions.classList.remove("open");
    });
    els.networkSuggestions.appendChild(btn);
  });
  els.networkSuggestions.classList.add("open");
}

document.addEventListener("click", (event) => {
  if (
    els.networkSuggestions &&
    !els.networkSuggestions.contains(event.target) &&
    event.target !== els.networkSearch
  ) {
    els.networkSuggestions.classList.remove("open");
  }
});

window.addEventListener("resize", () => {
  if (activeTab === "map") mapView.resize();
  else if (activeTab === "network") networkView.resize();
  else if (activeTab === "emissions") emissionsView.resize();
  else if (activeTab === "share") shareView.render();
});

renderStats();
renderResults({
  searchQuery: "",
  matchedIds: mapView.getMatchedIds(),
  selectedId: null,
  selectLocation: mapView.selectLocation,
  locationList: mapView.getLocations(),
});
mapView.applySearch("", { fly: false });
setTab(location.hash ? tabForHash(decodeURIComponent(location.hash.slice(1))) || getStoredTab() : getStoredTab());
if (location.hash) navigateToHash();
window.addEventListener("hashchange", () => navigateToHash());

const WELCOME_STORAGE_KEY = "icrs-intro-dismissed";

function initWelcome() {
  const overlay = $("welcome-overlay");
  const dismiss = $("welcome-dismiss");
  if (!overlay || !dismiss) return;

  const closeWelcome = () => {
    overlay.hidden = true;
    try {
      localStorage.setItem(WELCOME_STORAGE_KEY, "1");
    } catch {
      /* private browsing */
    }
  };

  let dismissed = false;
  try {
    dismissed = Boolean(localStorage.getItem(WELCOME_STORAGE_KEY));
  } catch {
    dismissed = false;
  }

  if (!dismissed) {
    overlay.hidden = false;
  }

  dismiss.addEventListener("click", closeWelcome);
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) closeWelcome();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !overlay.hidden) closeWelcome();
  });
}

initWelcome();

function initNetworkHint() {
  if (!els.networkHintBanner || !els.networkHintDismiss) return;

  els.networkHintDismiss.addEventListener("click", dismissNetworkHint);
  els.networkHintBanner.addEventListener("click", (event) => {
    if (event.target === els.networkHintBanner) dismissNetworkHint();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && els.networkHintBanner && !els.networkHintBanner.hidden) {
      dismissNetworkHint();
    }
  });
}

initNetworkHint();
