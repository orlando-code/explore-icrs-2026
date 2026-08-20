import {
  AFFILIATION_MAP_CIRCLE_PAINT,
  buildDisplayPositions,
  buildMapLocationPool,
  escapeHtml,
  formatDistance,
  locationMatchesQuery,
  matchedSpeakersForLocation,
  locationCorrectionMailto,
  renderTalkTitlesHtml,
  setTalkFormatElement,
  buildPersonNameSearchHits,
  findLocationIdByAffiliation,
  resolveCanonicalPersonName,
  isRegistryPersonKey,
  personKeyFromRecord,
  speakerIdentityKey,
  foldSearchText,
  resolveDelegatePersonKey,
} from "./utils.js";
import { resolveTalkId } from "./talk-similarity.js";

const MAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";
const MAX_ZOOM = 10;

function isMobileLayout() {
  return window.matchMedia("(max-width: 900px)").matches;
}

function useCooperativeMapGestures() {
  return window.matchMedia("(max-width: 900px) and (pointer: coarse)").matches;
}

export function createMapView(
  siteData,
  elements,
  { delegateEmissionsLocations = [], delegateIndex = new Map() } = {}
) {
  const speakerLocations = siteData.locations;
  const nonSpeakerLocations = siteData.non_speaker_locations || [];
  const hasDelegatePool =
    delegateEmissionsLocations.length > 0 || nonSpeakerLocations.length > 0;
  const networkNodes = siteData.network?.individual?.nodes || [];
  const networkNodeIdsByPersonKey = new Map();
  const networkNodeIdsByLabel = new Map();
  const networkNodeByLabel = new Map();
  for (const node of networkNodes) {
    if (isRegistryPersonKey(node.person_key)) {
      networkNodeIdsByPersonKey.set(node.person_key, node.id);
    }
    const label = String(node.label || "").trim();
    if (label) {
      networkNodeIdsByLabel.set(label, node.id);
      networkNodeByLabel.set(label, node);
    }
  }

  function networkNodeForSpeaker(speaker) {
    const name = String(speaker?.name || speaker || "").trim();
    if (!name) return null;
    const personKey =
      personKeyFromRecord(speaker) || resolveDelegatePersonKey(name) || "";
    if (isRegistryPersonKey(personKey)) {
      const byKey = networkNodeIdsByPersonKey.get(personKey);
      if (byKey) {
        return networkNodes.find((n) => n.id === byKey) || null;
      }
    }
    return networkNodeByLabel.get(name) || null;
  }

  function authorDidNotAttend(speaker) {
    const node = networkNodeForSpeaker(speaker);
    if (node?.external_coauthor === true) return true;
    if (node?.external_coauthor === false) return false;
    if (node?.attended) return false;
    if (node?.on_programme) return false;
    const name = String(speaker?.name || speaker || "").trim();
    const personKey = personKeyFromRecord(speaker) || resolveDelegatePersonKey(name) || "";
    return !locationIdForSpeaker(name, personKey);
  }

  function networkLinkHtml(speaker) {
    const name = speaker.name || speaker;
    const node = networkNodeForSpeaker(speaker);
    if (!node) return "";
    const personKey = personKeyFromRecord(speaker) || resolveDelegatePersonKey(name) || "";
    const externalClass = authorDidNotAttend(speaker) ? " cross-view-link--external" : "";
    const attrs = [
      `data-show-network="${escapeHtml(name)}"`,
      personKey ? `data-show-network-key="${escapeHtml(personKey)}"` : "",
    ].join(" ");
    return `<button type="button" class="btn-ghost btn-small cross-view-link${externalClass}" ${attrs}>Show in network</button>`;
  }

  let includeNonSpeakers = hasDelegatePool;

  function buildLocationPool() {
    return buildMapLocationPool(speakerLocations, {
      includeNonSpeakers,
      delegateIndex,
      delegateEmissionsLocations,
      nonSpeakerLocations,
    });
  }

  let locations = buildLocationPool();
  const meta = siteData.meta;
  const auckland = meta.auckland;

  let searchQuery = "";
  let matchedIds = new Set(locations.map((location) => location.id));
  let matchedSpeakersByLocation = new Map();
  let selectedId = null;
  let hoveredId = null;
  let connectionsSizeMode = false;
  let mapReady = false;
  let selectedTalkId = null;
  let hoverCardLocationId = null;
  let highlightedAuthorName = null;
  let authorHighlightLocationId = null;
  let focusedSpeakerName = null;
  let focusedSpeakerKey = null;
  let speakerLocationIndex = new Map();
  let speakerLocationByPersonKey = new Map();
  const talksData = elements.talksData || { by_id: {}, title_index: {} };
  const talksById = talksData.by_id || {};
  let maxConnectionCount = Math.max(
    ...locations.map((location) => location.connection_count || 0),
    1
  );
  let displayPositions = buildDisplayPositions(locations);

  function rebuildSpeakerLocationIndex() {
    speakerLocationIndex = new Map();
    speakerLocationByPersonKey = new Map();
    for (const location of locations) {
      for (const speaker of location.speaker_details || []) {
        const name = String(speaker.name || speaker).trim();
        const personKey = personKeyFromRecord(speaker);
        if (personKey && !speakerLocationByPersonKey.has(personKey)) {
          speakerLocationByPersonKey.set(personKey, location.id);
        }
        if (name && !speakerLocationIndex.has(name)) {
          speakerLocationIndex.set(name, location.id);
        }
      }
      for (const name of location.speakers || []) {
        const trimmed = String(name).trim();
        if (trimmed && !speakerLocationIndex.has(trimmed)) {
          speakerLocationIndex.set(trimmed, location.id);
        }
      }
    }
  }

  rebuildSpeakerLocationIndex();

  function locationIdForSpeaker(name, personKey = "") {
    const key = String(personKey || "").trim();
    if (isRegistryPersonKey(key) && speakerLocationByPersonKey.has(key)) {
      return speakerLocationByPersonKey.get(key);
    }
    return speakerLocationIndex.get(String(name || "").trim()) || null;
  }

  function clearTalkHighlights() {
    highlightedAuthorName = null;
    authorHighlightLocationId = null;
  }

  function refreshTalkAuthors() {
    if (!elements.talkAuthors || !selectedTalkId) return;
    const talk = talksById[selectedTalkId];
    if (!talk) return;
    elements.talkAuthors.innerHTML = renderTalkAuthorsHtml(talk.authors);
  }

  function renderTalkAuthorsHtml(authors) {
    const list = (authors || []).map((name) => String(name || "").trim()).filter(Boolean);
    if (!list.length) return "";

    return list
      .map((name, index) => {
        const separator = index > 0 ? '<span class="network-talk-author-sep">, </span>' : "";
        const personKey = resolveDelegatePersonKey(name) || "";
        const speaker = { name, person_key: personKey };
        const externalClass = authorDidNotAttend(speaker) ? " network-talk-author-external" : "";
        const locationId = locationIdForSpeaker(name, personKey);

        if (locationId) {
          const selected =
            name === highlightedAuthorName || locationId === authorHighlightLocationId
              ? " network-talk-author-selected"
              : "";
          return `${separator}<a href="#" class="network-talk-author-link${externalClass}${selected}" data-speaker-name="${escapeHtml(name)}"${personKey ? ` data-speaker-key="${escapeHtml(personKey)}"` : ""}>${escapeHtml(name)}</a>`;
        }

        return `${separator}<span class="network-talk-author-plain${externalClass}">${escapeHtml(name)}</span>`;
      })
      .join("");
  }

  function highlightAuthorOnMap(speakerName, personKey = "") {
    const trimmed = String(speakerName || "").trim();
    const locationId = locationIdForSpeaker(trimmed, personKey);
    if (!locationId) return;

    highlightedAuthorName = trimmed;
    authorHighlightLocationId = locationId;
    focusedSpeakerName = trimmed;
    focusedSpeakerKey = isRegistryPersonKey(personKey) ? personKey : null;
    refreshTalkAuthors();
    selectedId = locationId;
    hoveredId = locationId;
    renderHoverCard(locationById(locationId));
    elements.renderResults({
      searchQuery,
      matchedIds,
      selectedId,
      selectLocation,
      locationList: locations,
    });
    upsertMapData();
    flyToLocation(locationById(locationId));
  }

  function resolveFocusedSpeaker(location, explicitName = null, explicitPersonKey = null) {
    const personKey = String(explicitPersonKey || focusedSpeakerKey || "").trim();
    if (isRegistryPersonKey(personKey)) {
      const match = (location.speaker_details || []).find(
        (speaker) => personKeyFromRecord(speaker) === personKey
      );
      if (match) return String(match.name || match).trim();
    }
    const name = String(explicitName || focusedSpeakerName || "").trim();
    if (name) return name;
    if (highlightedAuthorName) return highlightedAuthorName;
    if (searchQuery) {
      const matched = matchedSpeakersByLocation.get(location.id);
      if (matched?.size) {
        const match = (location.speaker_details || []).find((speaker) =>
          matched.has(speakerIdentityKey(speaker))
        );
        if (match) return String(match.name || match).trim();
      }
    }
    const details = location.speaker_details || [];
    const speakers = details.filter((speaker) => !speaker.non_speaking_delegate);
    if (speakers.length === 1) {
      return String(speakers[0].name || speakers[0]).trim();
    }
    return null;
  }

  function scrollSpeakerIntoView(name, personKey = "") {
    if (!elements.hoverSpeakers) return;
    window.requestAnimationFrame(() => {
      if (!name && !personKey) {
        elements.hoverSpeakers.scrollTop = 0;
        return;
      }
      let entry = null;
      if (isRegistryPersonKey(personKey)) {
        entry = elements.hoverSpeakers.querySelector(
          `[data-speaker-key="${CSS.escape(personKey)}"]`
        );
      }
      if (!entry && name) {
        entry = elements.hoverSpeakers.querySelector(
          `[data-speaker-name="${CSS.escape(name)}"]`
        );
      }
      if (!entry) return;
      entry.scrollIntoView({ block: "start", behavior: "smooth" });
    });
  }

  function applyLocationPool() {
    locations = buildLocationPool();
    maxConnectionCount = Math.max(
      ...locations.map((location) => location.connection_count || 0),
      1
    );
    displayPositions = buildDisplayPositions(locations);
    rebuildSpeakerLocationIndex();
    updateMatches(searchQuery);
    if (selectedId && !locationById(selectedId)) {
      selectedId = null;
      hoveredId = null;
      renderHoverCard(null);
    }
    elements.renderResults({
      searchQuery,
      matchedIds,
      selectedId,
      selectLocation,
      locationList: locations,
    });
    if (mapReady) upsertMapData();
  }

  function setIncludeNonSpeakers(enabled) {
    if (!hasDelegatePool) return;
    includeNonSpeakers = Boolean(enabled);
    applyLocationPool();
  }

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

  function locationById(id) {
    return locations.find((location) => location.id === id) || null;
  }

  function displayForLocation(location) {
    return displayPositions.get(location.id) || { lat: location.lat, lon: location.lon };
  }

  function radiusForLocation(location, highlighted) {
    let base;
    if (connectionsSizeMode) {
      const count = Math.max(1, location.connection_count || 1);
      const scale = d3
        .scaleLog()
        .domain([1, maxConnectionCount])
        .range([6, 28])
        .clamp(true);
      base = scale(count);
    } else {
      base = Math.min(28, 6 + Math.sqrt(location.speaker_count) * 3.2);
    }
    return highlighted ? base + 2 : base;
  }

  function updateMatches(query) {
    searchQuery = query.trim();
    matchedSpeakersByLocation = new Map();
    if (!searchQuery) {
      matchedIds = new Set(locations.map((location) => location.id));
      return matchedIds;
    }

    matchedIds = new Set();
    for (const location of locations) {
      if (locationMatchesQuery(location, searchQuery)) {
        matchedIds.add(location.id);
        const speakers = matchedSpeakersForLocation(location, searchQuery);
        if (speakers.size) {
          matchedSpeakersByLocation.set(location.id, speakers);
        }
      }
    }
    return matchedIds;
  }

  function setLocationInfoOpen(open) {
    if (!elements.locationInfo || !elements.locationInfoBtn) return;
    elements.locationInfo.hidden = !open;
    elements.locationInfoBtn.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function updateLocationInfo(location) {
    const isSelected = Boolean(selectedId && location && location.id === selectedId);
    if (elements.locationInfoBtn) {
      elements.locationInfoBtn.hidden = !isSelected;
    }
    if (!isSelected) {
      setLocationInfoOpen(false);
      return;
    }
    if (elements.locationFixLink) {
      elements.locationFixLink.href = locationCorrectionMailto(location);
    }
  }

  function setSpeakerListVisible(visible) {
    if (elements.hoverSpeakers) elements.hoverSpeakers.hidden = !visible;
    elements.hoverCard?.classList.toggle("map-card--talk-open", !visible);
  }

  function clearTalkDetail() {
    selectedTalkId = null;
    clearTalkHighlights();
    if (elements.talkDetail) elements.talkDetail.hidden = true;
    if (elements.talkBack) elements.talkBack.hidden = true;
    if (elements.talkAuthors) elements.talkAuthors.innerHTML = "";
    if (elements.talkTitle) elements.talkTitle.textContent = "";
    setTalkFormatElement(elements.talkFormat, null);
    if (elements.talkAbstract) elements.talkAbstract.textContent = "";
    setSpeakerListVisible(true);
    upsertMapData();
  }

  function scrollTalkDetailIntoView() {
    const target = elements.talkDetail;
    const container = elements.hoverCard;
    if (!target || !container || target.hidden) return;
    window.requestAnimationFrame(() => {
      target.scrollIntoView({ block: "nearest", behavior: "smooth" });
      if (container.scrollHeight > container.clientHeight) {
        const top = Math.max(0, target.offsetTop - 12);
        container.scrollTo({ top, behavior: "smooth" });
      }
    });
  }

  function showTalkDetail(talkId) {
    const normalizedTalkId = String(talkId || "").trim();
    const talk = talksById[normalizedTalkId];
    if (!talk || !elements.talkDetail) return;

    selectedTalkId = normalizedTalkId;
    clearTalkHighlights();
    setSpeakerListVisible(false);
    if (elements.talkBack) elements.talkBack.hidden = false;
    elements.talkDetail.hidden = false;
    if (elements.talkTitle) elements.talkTitle.textContent = talk.title;
    setTalkFormatElement(elements.talkFormat, talk);
    if (elements.talkAuthors) {
      elements.talkAuthors.innerHTML = renderTalkAuthorsHtml(talk.authors);
    }
    if (elements.talkAbstract) {
      elements.talkAbstract.textContent = talk.abstract || "No abstract available.";
    }
    upsertMapData();
    scrollTalkDetailIntoView();
  }

  function handleTalkSelection(talkId) {
    const normalizedTalkId = String(talkId || "").trim();
    if (!normalizedTalkId) return;
    if (normalizedTalkId === selectedTalkId) {
      scrollTalkDetailIntoView();
      return;
    }
    showTalkDetail(normalizedTalkId);
  }

  function renderHoverCard(location) {
    if (!location) {
      hoverCardLocationId = null;
      clearTalkDetail();
      elements.hoverCard.hidden = true;
      updateLocationInfo(null);
      return;
    }

    if (hoverCardLocationId !== location.id) {
      clearTalkDetail();
    }
    hoverCardLocationId = location.id;

    elements.hoverCard.hidden = false;
    updateLocationInfo(location);
    elements.hoverAffiliation.textContent = location.affiliation;
    if (location.delegate_only) {
      const delegateCount =
        location.non_speaking_delegate_count ||
        location.speaker_details?.length ||
        location.speaker_count;
      elements.hoverMeta.textContent = [
        `${delegateCount} non-speaking delegate${delegateCount === 1 ? "" : "s"}`,
        location.geocode_level || null,
      ]
        .filter(Boolean)
        .join(" · ");
      renderSpeakerList(location);
      if (isMobileLayout()) {
        window.requestAnimationFrame(() => {
          elements.hoverCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
        });
      }
      return;
    }

    elements.hoverMeta.textContent = [
      (() => {
        const nonSpeaking = location.non_speaking_delegate_count || 0;
        const speakers = Math.max(0, location.speaker_count - nonSpeaking);
        const speakerLabel = `${speakers} speaker${speakers === 1 ? "" : "s"}`;
        if (!nonSpeaking) return `${location.speaker_count} delegate${location.speaker_count === 1 ? "" : "s"}`;
        return `${speakerLabel} · ${nonSpeaking} non-speaking delegate${nonSpeaking === 1 ? "" : "s"}`;
      })(),
      `${location.talk_count} talk${location.talk_count === 1 ? "" : "s"}`,
      `${(location.connection_count || 0).toLocaleString()} talk${location.connection_count === 1 ? "" : "s"} on author lists`,
      location.geocode_level ? `${location.geocode_level} geocode` : null,
    ]
      .filter(Boolean)
      .join(" · ");

    const highlightedSpeakers = matchedSpeakersByLocation.get(location.id) || new Set();
    const searching = Boolean(searchQuery);
    focusedSpeakerName = resolveFocusedSpeaker(location, focusedSpeakerName, focusedSpeakerKey);
    renderSpeakerList(location, {
      highlightedSpeakers,
      searching,
      focusedSpeakerName,
      focusedSpeakerKey,
    });
    scrollSpeakerIntoView(focusedSpeakerName, focusedSpeakerKey);
    if (selectedTalkId) {
      setSpeakerListVisible(false);
      if (elements.talkBack) elements.talkBack.hidden = false;
      if (elements.talkDetail) elements.talkDetail.hidden = false;
      refreshTalkAuthors();
    }

    if (isMobileLayout()) {
      window.requestAnimationFrame(() => {
        elements.hoverCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
    }
  }

  function renderSpeakerList(
    location,
    {
      highlightedSpeakers = new Set(),
      searching = false,
      focusedSpeakerName: focusedName = null,
      focusedSpeakerKey: focusedKey = null,
    } = {}
  ) {
    const details = location.speaker_details || location.speakers.map((name) => ({ name }));
    const speakers = details.filter((speaker) => !speaker.non_speaking_delegate);
    const delegates = details.filter((speaker) => speaker.non_speaking_delegate);

    const speakerEntryClass = (speaker) => {
      const identityKey = speakerIdentityKey(speaker);
      const isMatch = searching && highlightedSpeakers.has(identityKey);
      const isFocused =
        (focusedKey && personKeyFromRecord(speaker) === focusedKey) ||
        (focusedName && (speaker.name || speaker) === focusedName);
      return `${isMatch ? " speaker-match" : ""}${isFocused ? " speaker-focused" : ""}`;
    };

    const speakerHtml = speakers
      .map((speaker) => {
        const name = speaker.name || speaker;
        const personKey = personKeyFromRecord(speaker);
        const titlesHtml = renderTalkTitlesHtml(speaker.talk_titles || [], {
          kicker: "",
          selectedTalkId,
          resolveTalkId: (entry) => resolveTalkId(entry, talksData, name),
        });
        return `
          <li class="speaker-entry${speakerEntryClass(speaker)}" data-speaker-name="${escapeHtml(name)}"${personKey ? ` data-speaker-key="${escapeHtml(personKey)}"` : ""}>
            <div class="speaker-name-row">
              <span class="speaker-name">${escapeHtml(name)}</span>
              ${networkLinkHtml(speaker)}
            </div>
            ${titlesHtml}
          </li>`;
      })
      .join("");

    const delegatesHtml = delegates.length
      ? `
        <li class="speaker-delegates-group">
          <p class="speaker-role">Non-speaking delegates:</p>
          <ul class="speaker-delegate-list">
            ${delegates
              .map((speaker) => {
                const name = speaker.name || speaker;
                const personKey = personKeyFromRecord(speaker);
                return `<li class="${speakerEntryClass(speaker).trim() || ""}" data-speaker-name="${escapeHtml(name)}"${personKey ? ` data-speaker-key="${escapeHtml(personKey)}"` : ""}><span class="speaker-delegate-name">${escapeHtml(name)}</span></li>`;
              })
              .join("")}
          </ul>
        </li>`
      : "";

    elements.hoverSpeakers.innerHTML = speakerHtml + delegatesHtml;
  }

  function locationFeatures() {
    const searching = Boolean(searchQuery);
    return locations.map((location) => {
      const highlighted = !searching || matchedIds.has(location.id);
      const display = displayForLocation(location);
      const talkHighlighted = 0;
      const authorHighlighted = authorHighlightLocationId === location.id ? 1 : 0;
      return {
        type: "Feature",
        properties: {
          id: location.id,
          affiliation: location.affiliation,
          speaker_count: location.speaker_count,
          talk_count: location.talk_count,
          connection_count: location.connection_count || 0,
          distance_km: location.distance_km,
          highlighted: highlighted ? 1 : 0,
          selected: location.id === selectedId ? 1 : 0,
          hovered: location.id === hoveredId ? 1 : 0,
          talk_highlighted: talkHighlighted,
          author_highlighted: authorHighlighted,
          radius: radiusForLocation(location, highlighted),
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
    map.getSource("locations")?.setData({
      type: "FeatureCollection",
      features: locationFeatures(),
    });
  }

  function boundsForIds(ids) {
    const coords = locations
      .filter((location) => ids.has(location.id))
      .map((location) => [location.lon, location.lat]);
    if (!coords.length) return null;
    let minLon = coords[0][0];
    let maxLon = coords[0][0];
    let minLat = coords[0][1];
    let maxLat = coords[0][1];
    for (const [lon, lat] of coords.slice(1)) {
      minLon = Math.min(minLon, lon);
      maxLon = Math.max(maxLon, lon);
      minLat = Math.min(minLat, lat);
      maxLat = Math.max(maxLat, lat);
    }
    return [
      [minLon, minLat],
      [maxLon, maxLat],
    ];
  }

  function flyToLocation(location, minZoom = 4) {
    if (!mapReady || !location) return;
    const display = displayForLocation(location);
    map.flyTo({
      center: [display.lon, display.lat],
      zoom: Math.max(map.getZoom(), minZoom),
      essential: true,
    });
  }

  function selectLocation(id, { fly = true, toggle = false, speakerName = undefined, personKey = undefined } = {}) {
    const previousId = selectedId;
    const nextId = toggle && selectedId === id ? null : id;
    if (nextId !== previousId) clearTalkHighlights();
    selectedId = nextId;
    if (!nextId) {
      focusedSpeakerName = null;
      focusedSpeakerKey = null;
    } else if (personKey !== undefined) {
      focusedSpeakerKey = isRegistryPersonKey(personKey) ? personKey : null;
      if (speakerName !== undefined) {
        focusedSpeakerName = String(speakerName || "").trim() || null;
      }
    } else if (speakerName !== undefined) {
      focusedSpeakerName = String(speakerName || "").trim() || null;
      focusedSpeakerKey = null;
    } else if (nextId !== previousId) {
      focusedSpeakerName = null;
      focusedSpeakerKey = null;
    }
    renderHoverCard(locationById(selectedId));
    elements.renderResults({
      searchQuery,
      matchedIds,
      selectedId,
      selectLocation,
      locationList: locations,
    });
    upsertMapData();
    if (fly && selectedId) flyToLocation(locationById(selectedId));
    return selectedId;
  }

  function applySearch(query, { fly = true } = {}) {
    updateMatches(query);
    const searching = Boolean(searchQuery);
    if (searching) {
      elements.setStatus(
        matchedIds.size
          ? `${matchedIds.size.toLocaleString()} location${matchedIds.size === 1 ? "" : "s"} matched`
          : "No points matched that search.",
        !matchedIds.size
      );
    } else {
      elements.setStatus("");
    }

    if (selectedId && !matchedIds.has(selectedId)) {
      selectedId = null;
      renderHoverCard(null);
    }

    elements.renderResults({
      searchQuery,
      matchedIds,
      selectedId,
      selectLocation,
      locationList: locations,
    });
    upsertMapData();

    if (fly && searching && matchedIds.size) {
      const bounds = boundsForIds(matchedIds);
      if (bounds) {
        map.fitBounds(bounds, { padding: 80, maxZoom: 5.5, duration: 900 });
      }
    }
  }

  function buildSuggestions(query) {
    const trimmed = foldSearchText(query).trim();
    if (trimmed.length < 2) return [];

    const people = locations.flatMap((location) =>
      (location.speaker_details || []).map((speaker) => ({
        ...speaker,
        affiliation: location.affiliation,
        locationId: location.id,
        talkTitles: speaker.talk_titles,
        nonSpeakingDelegate: Boolean(speaker.non_speaking_delegate),
      }))
    );
    const speakerHits = buildPersonNameSearchHits(people, trimmed, { limit: 8 }).map((hit) => ({
      label: hit.name,
      detail: hit.affiliation,
      query: hit.name,
      locationId: hit.locationId,
      speakerName: hit.name,
      person_key: hit.person_key,
      talkTitles: hit.talkTitles,
      nonSpeakingDelegate: hit.nonSpeakingDelegate,
    }));
    const affiliationHits = new Map();

    for (const location of locations) {
      if (foldSearchText(location.affiliation).includes(trimmed) && !affiliationHits.has(location.id)) {
        affiliationHits.set(location.id, {
          label: location.affiliation,
          detail: `${location.speaker_count} delegate${location.speaker_count === 1 ? "" : "s"}`,
          query: location.affiliation,
          locationId: location.id,
        });
      }
    }

    return [...speakerHits, ...affiliationHits.values()].slice(0, 8);
  }

  function renderLegend() {
    if (!elements.legend) return;

    if (connectionsSizeMode) {
      const counts = locations.map((location) => Math.max(1, location.connection_count || 1));
      const minCount = Math.max(1, d3.min(counts));
      const maxCount = Math.max(minCount, d3.max(counts));
      const scale = d3
        .scaleLog()
        .domain([minCount, Math.max(minCount + 1, maxCount)])
        .range([8, 28])
        .clamp(true);
      const talkLabel = (count) =>
        `${count.toLocaleString()} talk${count === 1 ? "" : "s"}`;
      const samples =
        minCount === maxCount
          ? [{ label: talkLabel(minCount), size: scale(minCount) }]
          : (() => {
              const midCount = Math.round(Math.sqrt(minCount * maxCount));
              return [
                { label: talkLabel(minCount), size: scale(minCount) },
                { label: talkLabel(midCount), size: scale(midCount) },
                { label: talkLabel(maxCount), size: scale(maxCount) },
              ];
            })();
      elements.legend.innerHTML = `
        <h3>Point size · talks on author lists (log scale)</h3>
        <p>Circle area scales with talks where this affiliation appears on the author list.</p>
        ${samples
          .map(
            (sample) => `
          <div class="legend-row">
            <span class="legend-dot legend-dot--accent" style="width:${sample.size}px;height:${sample.size}px"></span>
            <span>${sample.label}</span>
          </div>`
          )
          .join("")}
      `;
      return;
    }

    const counts = locations.map((location) => Math.max(1, location.speaker_count));
    const minCount = Math.max(1, d3.min(counts));
    const maxCount = Math.max(minCount + 1, d3.max(counts));
    const midCount = Math.round(Math.sqrt(minCount * maxCount));
    const scale = d3
      .scaleLog()
      .domain([minCount, maxCount])
      .range([8, 28])
      .clamp(true);
    const samples = [
      { label: `${minCount} delegates`, size: scale(minCount) },
      { label: `${midCount} delegates`, size: scale(midCount) },
      { label: `${maxCount} delegates`, size: scale(maxCount) },
    ];
    elements.legend.innerHTML = `
      <h3>Point size · delegates (log scale)</h3>
      <p>Default view sizes each affiliation by delegate count at that location.</p>
      ${samples
        .map(
          (sample) => `
        <div class="legend-row">
          <span class="legend-dot legend-dot--accent" style="width:${sample.size}px;height:${sample.size}px"></span>
          <span>${sample.label}</span>
        </div>`
        )
        .join("")}
    `;
  }

  function setConnectionsSize(enabled) {
    connectionsSizeMode = Boolean(enabled);
    upsertMapData();
    renderLegend();
    return connectionsSizeMode;
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

    map.addLayer({
      id: "locations-circle",
      type: "circle",
      source: "locations",
      paint: AFFILIATION_MAP_CIRCLE_PAINT,
    });

    map.easeTo({
      center: [auckland.lon, auckland.lat],
      zoom: 1.9,
      duration: 0,
    });
    upsertMapData();
    renderLegend();
  });

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
    if (!selectedId) {
      hoveredId = null;
      renderHoverCard(null);
      upsertMapData();
      return;
    }
    hoveredId = selectedId;
    renderHoverCard(locationById(selectedId));
    upsertMapData();
  });

  map.on("click", "locations-circle", (event) => {
    const id = event.features?.[0]?.properties?.id;
    if (id) selectLocation(id, { toggle: true });
  });

  map.on("click", (event) => {
    const hitLocation = map.queryRenderedFeatures(event.point, { layers: ["locations-circle"] });
    if (hitLocation.length) return;
    if (!selectedId) return;
    selectedId = null;
    hoveredId = null;
    renderHoverCard(null);
    elements.renderResults({
      searchQuery,
      matchedIds,
      selectedId,
      selectLocation,
      locationList: locations,
    });
    upsertMapData();
  });

  if (elements.locationInfoBtn && elements.locationInfo) {
    elements.locationInfoBtn.addEventListener("click", () => {
      setLocationInfoOpen(elements.locationInfo.hidden);
    });
  }

  if (elements.hoverCard) {
    elements.hoverCard.addEventListener("click", (event) => {
      const authorLink = event.target.closest(".network-talk-author-link[data-speaker-name]");
      if (authorLink && elements.talkAuthors?.contains(authorLink)) {
        event.preventDefault();
        event.stopPropagation();
        highlightAuthorOnMap(authorLink.dataset.speakerName, authorLink.dataset.speakerKey || "");
        return;
      }

      const button = event.target.closest("[data-talk-id]");
      if (!button || !elements.hoverSpeakers?.contains(button)) {
        const networkButton = event.target.closest("[data-show-network]");
        if (networkButton && elements.hoverSpeakers?.contains(networkButton)) {
          event.preventDefault();
          event.stopPropagation();
          elements.onShowInNetwork?.(
            networkButton.dataset.showNetwork,
            networkButton.dataset.showNetworkKey || ""
          );
        }
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      handleTalkSelection(button.dataset.talkId);
    });
  }

  if (elements.talkBack) {
    elements.talkBack.addEventListener("click", () => {
      clearTalkDetail();
      const location = locationById(hoverCardLocationId || selectedId || hoveredId);
      if (!location) return;
      const highlightedSpeakers = matchedSpeakersByLocation.get(location.id) || new Set();
      renderSpeakerList(location, {
        highlightedSpeakers,
        searching: Boolean(searchQuery),
        focusedSpeakerName,
        focusedSpeakerKey,
      });
      scrollSpeakerIntoView(focusedSpeakerName);
    });
  }

  return {
    applySearch,
    buildSuggestions,
    selectLocation,
    setConnectionsSize,
    setIncludeNonSpeakers,
    hasDelegatePool,
    getLocations: () => locations,
    getMatchedIds: () => matchedIds,
    findLocationIdByAffiliation: (affiliation) => findLocationIdByAffiliation(locations, affiliation),
    resize: () => map.resize(),
  };
}
