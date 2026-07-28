import { escapeHtml, buildTalkTitleIndex, renderTalkTitlesHtml } from "./utils.js";
import { createTalkSimilarityLookup, resolveTalkId } from "./talk-similarity.js";

const DEFAULT_NODE_LIMIT = 150;
const MAX_LINKS_ALL = 6000;
const DATA_REMOVAL_EMAIL = "rt582@cam.ac.uk";

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

function copyDelegateButtonHtml(name, affiliation) {
  return `<button type="button" class="btn-small network-contact-copy-details" data-copy-name="${escapeHtml(name)}" data-copy-affiliation="${escapeHtml(affiliation)}" data-original-label="Copy speaker details" aria-label="Copy speaker details" title="Copy name and institute">Copy speaker details</button>`;
}

function delegateDetailsText(name, affiliation = "") {
  const lines = [String(name || "").trim()];
  const inst = String(affiliation || "").trim();
  if (inst) lines.push(inst);
  return lines.join("\n");
}

async function copyTextToClipboard(text, button) {
  if (!text) return false;
  try {
    await navigator.clipboard.writeText(text);
    if (button) {
      button.classList.add("copied");
      button.setAttribute("aria-label", "Copied");
      button.setAttribute("title", "Copied");
      const originalLabel = button.dataset.originalLabel;
      if (originalLabel) button.textContent = "Copied";
      window.setTimeout(() => {
        button.classList.remove("copied");
        button.setAttribute("aria-label", "Copy speaker details");
        button.setAttribute("title", "Copy name and institute");
        if (originalLabel) button.textContent = originalLabel;
      }, 1500);
    }
    return true;
  } catch {
    return false;
  }
}

function buildAuthorSearchIndex(locations) {
  const index = new Map();
  for (const location of locations) {
    for (const detail of location.speaker_details || []) {
      const name = detail.name;
      if (!name) continue;
      const existing = index.get(name) || [];
      if (detail.search_text) existing.push(detail.search_text);
      index.set(name, existing);
    }
  }
  return index;
}

function buildPresenterIndex(talksData) {
  const presenters = new Set();
  for (const talk of Object.values(talksData?.by_id || {})) {
    const presenter = String(talk?.presenter || "").trim();
    if (presenter) presenters.add(presenter);
  }
  return presenters;
}

function authorContextFor(node, profile) {
  const role = node?.author_role || profile?.profile_role || null;
  const affiliationExplicit =
    node?.affiliation_explicit ?? profile?.affiliation_explicit ?? Boolean(profile);
  return { role, affiliationExplicit };
}

function authorRoleLabel(role) {
  if (role === "presenter") return "Presenting author";
  if (role === "co_author") return "Co-author";
  return "Author";
}

function profileStatusLabel({ role, affiliationExplicit, hasProfile }) {
  if (hasProfile && role === "presenter") {
    return "Presenting author profile";
  }
  if (hasProfile && role === "co_author") {
    return "Co-author profile";
  }
  if (role === "presenter" && !affiliationExplicit) {
    return "Presenting author without a confirmed affiliation";
  }
  if (role === "co_author" && !affiliationExplicit) {
    return "Co-author with inferred affiliation only";
  }
  if (role === "co_author") {
    return "Co-author without a looked-up profile";
  }
  return "No profile lookup available";
}

function affiliationNote({ role, affiliationExplicit, affiliation }) {
  if (!affiliation) return "";
  if (affiliationExplicit) return affiliation;
  if (role === "co_author") {
    return `${affiliation} (inferred from a presenting author's talk)`;
  }
  return `${affiliation} (inferred)`;
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
    siteData.talk_titles_by_author
  );
  const talksData = elements.talksData || { by_id: {}, title_index: {} };
  const talksById = talksData.by_id || {};
  const presenterIndex = buildPresenterIndex(talksData);
  const similarityLookup = createTalkSimilarityLookup(
    elements.similaritiesData || { by_id: {} },
    talksById
  );
  let selectedTalkId = null;
  let selectedSpeakerName = "";
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
  let pendingNodeFocus = false;
  let resizeTimer = null;
  let graphRenderKey = "";
  let autoFitPending = false;
  let userAdjustedZoom = false;
  let viewFitGeneration = 0;
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

  function neighborIdsFromLinks(nodeId, links) {
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
      for (const id of neighborIdsFromLinks(selectedNodeId, fullLinks)) {
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
      const neighborCount = Math.max(0, graphNodes.length - 1);
      return `Showing ${neighborCount.toLocaleString()} co-author${neighborCount === 1 ? "" : "s"} linked to ${name || "selection"}.`;
    }
    if (!graphThinned || !graphTotalNodes) return "";
    if (searchQuery && matchedNodeIds.size) {
      return `Showing ${graphNodes.length.toLocaleString()} of ${graphTotalNodes.toLocaleString()} matches and co-authors. All ${matchedNodeIds.size.toLocaleString()} matches are included.`;
    }
    return `Showing ${graphNodes.length.toLocaleString()} of ${graphTotalNodes.toLocaleString()} nodes (by talk count). Search or increase “Nodes shown” to explore more.`;
  }

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
    const baseRadius = Math.max(28, Math.min(140, 12 + Math.sqrt(matchCount) * 7));

    matchNodes.forEach((node, index) => {
      const ring = Math.floor(index / Math.max(1, Math.ceil(Math.sqrt(matchCount))));
      const angle = (2 * Math.PI * index) / matchCount + ring * 0.35;
      const radius = baseRadius + ring * (16 + baseRadius * 0.12);
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
      const offset = 24 + (index % 5) * 8;
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
    const q = query.toLowerCase();
    if (node.label.toLowerCase().includes(q)) return true;
    if (mode === "individual" && node.affiliation?.toLowerCase().includes(q)) return true;
    if (mode === "individual") {
      const texts = authorSearchIndex.get(node.label) || [];
      if (texts.some((text) => text.includes(q))) return true;
    } else if (affiliationSearchIndex.get(node.label)?.includes(q)) {
      return true;
    }
    return false;
  }

  function formatNodeMeta(node) {
    const profile = profileForNode(node);
    const context = authorContextFor(node, profile);
    const role =
      context.role || (presenterIndex.has(node.label) ? "presenter" : "co_author");
    const parts = [
      authorRoleLabel(role),
      `on author list of ${node.connections.toLocaleString()} talk${node.connections === 1 ? "" : "s"}`,
    ];
    // Travel distance hidden for now – re-enable when individual travel estimates are ready.
    // if (node.distance_km != null) {
    //   parts.push(`${formatDistance(node.distance_km)} from Auckland`);
    // }
    if (mode === "individual" && node.affiliation) {
      parts.push(
        affiliationNote({
          role,
          affiliationExplicit: context.affiliationExplicit,
          affiliation: node.affiliation,
        })
      );
    }
    return parts.join(" · ");
  }

  function profileForNode(node) {
    if (!node || mode !== "individual") return null;
    return speakerProfiles[node.label] || null;
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
    const role =
      context.role || (presenterIndex.has(node.label) ? "presenter" : "co_author");
    const profileStatus = profileStatusLabel({
      role,
      affiliationExplicit: context.affiliationExplicit,
      hasProfile: Boolean(profile),
    });
    const profilePage = profilePageFor(profile);
    const linkedIn = linkedInLinkFor(node.label, affiliation, profile);
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
      <p class="network-contact-status">${escapeHtml(profileStatus)}</p>
      <div class="network-contact-copy-details-wrap">
        ${copyDelegateButtonHtml(node.label, affiliation)}
      </div>
      <ul class="network-contact-links">${linkItems}</ul>
      <p class="network-contact-footnote">Copy speaker details or follow the public profile links below.</p>
    `;
  }

  function updateNodeContacts(node) {
    if (!elements.cardContacts) return;
    if (!node) {
      elements.cardContacts.hidden = true;
      elements.cardContacts.innerHTML = "";
      return;
    }
    elements.cardContacts.hidden = false;
    elements.cardContacts.innerHTML = renderContactLinksHtml(node);
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
    const neighbors = neighborIds(selectedNodeId);
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
        <button type="button" class="result-item${node.id === selectedNodeId ? " selected" : ""}${selectedNodeId && neighbors.has(node.id) ? " neighbor" : ""}" data-node-id="${escapeHtml(node.id)}">
          <div class="affiliation">${escapeHtml(node.label)}</div>
          <div class="meta">${escapeHtml(formatNodeMeta(node))}</div>
        </button>`;
      })
      .join("");

    elements.results.querySelectorAll("[data-node-id]").forEach((button) => {
      button.addEventListener("click", () => selectNode(button.dataset.nodeId, { focus: true }));
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
        <span class="legend-dot" style="background:#d95f02"></span>
        <span>Matches “${escapeHtml(searchQuery)}”</span>
      </div>
      <div class="legend-row">
        <span class="legend-dot" style="background:#b8c4cc"></span>
        <span>Co-authors (not a direct match)</span>
      </div>
    `
        : "";

    const selectionSection = selectedNodeId
      ? `
      <h3>Selection</h3>
      <p>Highlighted links connect the selected node to direct co-authors. Other nodes fade.</p>
      <div class="legend-row">
        <span class="legend-line" style="height:3px;background:#1f6f8b"></span>
        <span>Link to selected node</span>
      </div>
      <div class="legend-row">
        <span class="legend-line"></span>
        <span>Other co-authorship links</span>
      </div>
    `
      : "";

    elements.legendCoauthorship.innerHTML = `
      <h3>Co-authorship links</h3>
      <p>Edges connect speakers or affiliations who share authorship on at least one ICRS talk. Thicker lines mean more shared talks.</p>
      ${selectionSection}
      ${searchSection}
    `;
  }

  function renderScaleLegend(nodes, radiusScale) {
    if (!elements.legendScale || !radiusScale) return;
    const counts = nodes.map((node) => node.connections);
    const minCount = Math.max(1, d3.min(counts) || 1);
    const maxCount = Math.max(minCount, d3.max(counts) || 1);
    const midCount = Math.round(Math.sqrt(minCount * maxCount));
    const samples = [
      { label: `${minCount.toLocaleString()} talks`, value: minCount },
      { label: `${midCount.toLocaleString()} talks`, value: midCount },
      { label: `${maxCount.toLocaleString()} talks`, value: maxCount },
    ];

    elements.legendScale.innerHTML = `
      <h3>Node size · talks on author lists (log scale)</h3>
      <p>Circle area scales with talks where the person or affiliation appears on the author list.</p>
      ${samples
        .map(
          (sample) => `
        <div class="legend-row">
          <span class="legend-dot" style="width:${radiusScale(sample.value) * 2}px;height:${radiusScale(sample.value) * 2}px"></span>
          <span>${sample.label}</span>
        </div>`
        )
        .join("")}
    `;
  }

  function neighborIds(nodeId) {
    return neighborIdsFromLinks(nodeId, graphLinks);
  }

  function labelNodes(nodes) {
    const searching = Boolean(searchQuery);
    const neighbors = neighborIds(selectedNodeId);
    return nodes.filter((node) => {
      if (node.id === selectedNodeId) return false;
      if (selectedNodeId && neighbors.has(node.id)) return true;
      if (searching && matchedNodeIds.has(node.id)) return true;
      if (!searchQuery && !selectedNodeId && node.connections >= 20) return true;
      return false;
    });
  }

  function nodeDrawOrder(node, neighbors) {
    if (node.id === selectedNodeId) return 3;
    if (selectedNodeId && neighbors.has(node.id)) return 2;
    if (searchQuery && matchedNodeIds.has(node.id)) return 1;
    return 0;
  }

  function labelDrawOrder(node, neighbors) {
    return nodeDrawOrder(node, neighbors);
  }

  function raiseSelectedLabel() {
    labelOverlay?.raise();
    selectedLabelSelection?.raise();
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
      .attr("dy", (d) => -radiusScale(Math.max(1, d.connections)) - 8)
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

  function linkIsHighlighted(link) {
    if (!selectedNodeId) return false;
    const { sourceId, targetId } = linkEndpointIds(link);
    return sourceId === selectedNodeId || targetId === selectedNodeId;
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
      updateNodeTalks(null);
      updateNodeContacts(null);
      setDataInfoOpen(false);
      elements.cardClear?.setAttribute("hidden", "");
      elements.clearSelection?.setAttribute("hidden", "");
    }

    const thinningNote = thinningSummary();
    elements.summary.textContent = selectedNodeId
      ? `${graphNodes.length.toLocaleString()} nodes · tap background or Clear to deselect`
      : [
          `${graphNodes.length.toLocaleString()} nodes · ${graphLinks.length.toLocaleString()} co-authorship links · ${isCoarsePointer ? "pinch to zoom, drag background to pan" : "scroll to zoom, drag to pan"}`,
          thinningNote,
        ]
          .filter(Boolean)
          .join(" · ");
  }

  function scrollToSelectedSidebar() {
    if (!selectedNodeId) return;
    const selector = `[data-node-id="${CSS.escape(selectedNodeId)}"]`;
    const target =
      elements.results?.querySelector(selector) ||
      elements.barChart?.querySelector(selector);
    target?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    if (!target && elements.card && !elements.card.hidden) {
      elements.card.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }

  function updateHighlight() {
    if (!nodeSelection || !linkSelection || !radiusScale) return;

    const searching = Boolean(searchQuery);
    const neighbors = neighborIds(selectedNodeId);

    linkSelection
      .attr("stroke", (d) => (linkIsHighlighted(d) ? "#1f6f8b" : "#94a3ad"))
      .attr("stroke-opacity", (d) => {
        if (!selectedNodeId) return 0.18;
        return linkIsHighlighted(d) ? 0.88 : 0.05;
      })
      .attr("stroke-width", (d) => {
        const base = Math.max(0.35, Math.log2(d.weight + 1) * 0.45);
        return linkIsHighlighted(d) ? base + 0.9 : base;
      });

    nodeSelection
      .sort((a, b) => nodeDrawOrder(a, neighbors) - nodeDrawOrder(b, neighbors))
      .attr("fill", (d) => {
        if (d.id === selectedNodeId) return "#1f6f8b";
        if (selectedNodeId && neighbors.has(d.id)) return "#4a90a7";
        if (searching && matchedNodeIds.has(d.id)) return "#d95f02";
        if (searching) return "#b8c4cc";
        return "#d95f02";
      })
      .attr("stroke-width", (d) => {
        if (d.id === selectedNodeId) return 3;
        if (selectedNodeId && neighbors.has(d.id)) return 2.5;
        if (searching && matchedNodeIds.has(d.id)) return 2.5;
        return 1.5;
      })
      .attr("opacity", (d) => {
        if (d.id === selectedNodeId) return 1;
        if (selectedNodeId) {
          return neighbors.has(d.id) ? 0.72 : 0.16;
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
      .sort((a, b) => labelDrawOrder(a, neighbors) - labelDrawOrder(b, neighbors))
      .attr("font-size", 10)
      .attr("font-weight", (d) => (neighbors.has(d.id) ? 600 : 500))
      .attr("fill", (d) => (neighbors.has(d.id) ? "#1a3340" : "#14212b"))
      .attr("fill-opacity", 1)
      .attr("stroke", "#ffffff")
      .attr("stroke-width", 3)
      .attr("stroke-opacity", 0.88)
      .attr("paint-order", "stroke")
      .attr("dy", (d) => -radiusScale(Math.max(1, d.connections)) - 4)
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
  }

  function renderBarChart(nodes) {
    if (!elements.barChart) return;
    const sorted = [...nodes].sort((a, b) => b.connections - a.connections).slice(0, 12);
    const maxConnections = sorted[0]?.connections || 1;
    const logScale = d3.scaleLog().domain([1, maxConnections]).range([0.08, 1]).clamp(true);
    const neighbors = neighborIds(selectedNodeId);

    elements.barChart.innerHTML = sorted
      .map((node) => {
        const widthPct = `${logScale(Math.max(1, node.connections)) * 100}%`;
        const selected = node.id === selectedNodeId;
        const neighbor = selectedNodeId && neighbors.has(node.id);
        const dimmed =
          (searchQuery && matchedNodeIds.size && !matchedNodeIds.has(node.id)) ||
          (selectedNodeId && !selected && !neighbor);
        return `
          <button type="button" class="bar-row${selected ? " selected" : ""}${neighbor ? " neighbor" : ""}${dimmed ? " dimmed" : ""}" data-node-id="${escapeHtml(node.id)}">
            <span class="bar-label">${escapeHtml(node.label)}</span>
            <div class="bar-track" aria-hidden="true"><div class="bar-fill" style="width:${widthPct}"></div></div>
            <span class="bar-count">${node.connections.toLocaleString()}</span>
          </button>`;
      })
      .join("");

    elements.barChart.querySelectorAll("[data-node-id]").forEach((button) => {
      button.addEventListener("click", () => selectNode(button.dataset.nodeId, { focus: true }));
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

  function renderGraph({ force = false, resetZoom = false } = {}) {
    updateDimensions();
    const graph = prepareGraph();
    const nextRenderKey = graphRenderSignature(graph.nodes, graph.links);
    if (!force && hasRendered && nextRenderKey === graphRenderKey) {
      updateHighlight();
      return;
    }

    if (resetZoom) userAdjustedZoom = false;

    graphRenderKey = nextRenderKey;
    const fitGeneration = ++viewFitGeneration;
    autoFitPending = !pendingNodeFocus && !userAdjustedZoom;

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
      .alpha(isSearchLayout ? 1 : 0.3)
      .alphaDecay(
        isSearchLayout ? (largeGraph ? 0.045 : 0.032) : largeGraph ? 0.06 : 0.0228
      )
      .velocityDecay(isSearchLayout ? (largeGraph ? 0.55 : 0.45) : largeGraph ? 0.72 : 0.4)
      .force(
        "link",
        d3
          .forceLink(graphLinks)
          .id((d) => d.id)
          .distance(isSearchLayout ? (largeGraph ? 38 : 48) : largeGraph ? 70 : 90)
          .strength(isSearchLayout ? (largeGraph ? 0.62 : 0.78) : largeGraph ? 0.3 : 0.45)
      )
      .force(
        "charge",
        d3
          .forceManyBody()
          .strength(
            isSearchLayout
              ? largeGraph
                ? -28
                : -48
              : largeGraph
                ? -90
                : isCoarsePointer
                  ? -140
                  : -180
          )
      )
      .force("center", d3.forceCenter(centerX, centerY))
      .force(
        "collide",
        d3
          .forceCollide()
          .radius((d) => radiusScale(Math.max(1, d.connections)) + (isCoarsePointer ? 8 : 4))
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

        if (pendingNodeFocus && selectedNodeId) {
          focusNode(selectedNodeId);
          pendingNodeFocus = false;
          autoFitPending = false;
          return;
        }

        if (autoFitPending) {
          fitToView({ animate: false });
          autoFitPending = false;
        }
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
        if (!event.active && simulation) simulation.alphaTarget(0.25).restart();
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
          selectNode(d.id, { focus: isCoarsePointer });
        }
        d.fx = null;
        d.fy = null;
      });
  }

  function resolveTalkIdForEntry(entry) {
    return resolveTalkId(entry, talksData, selectedSpeakerName);
  }

  function nodeIdForAuthor(name) {
    const trimmed = String(name || "").trim();
    if (!trimmed) return null;
    const node = network.individual.nodes.find((item) => item.label === trimmed);
    return node?.id || null;
  }

  function renderTalkAuthorsHtml(authors) {
    const list = (authors || []).map((name) => String(name || "").trim()).filter(Boolean);
    if (!list.length) return "";

    return list
      .map((name, index) => {
        const separator = index > 0 ? '<span class="network-talk-author-sep">, </span>' : "";
        const nodeId = nodeIdForAuthor(name);
        if (nodeId) {
          const selected = nodeId === selectedNodeId ? " network-talk-author-selected" : "";
          return `${separator}<button type="button" class="network-talk-author-btn${selected}" data-node-id="${escapeHtml(nodeId)}">${escapeHtml(name)}</button>`;
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
      target.scrollIntoView({ block: "nearest", behavior: "smooth" });
      if (container.scrollHeight > container.clientHeight) {
        const top = Math.max(0, target.offsetTop - 12);
        container.scrollTo({ top, behavior: "smooth" });
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
      setSimilarStatus("No similar talks found.", true);
      renderSimilarTalks([]);
      return;
    }
    setSimilarStatus("Similar talks by topic.");
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
      elements.cardTalks.hidden = true;
      elements.cardTalks.innerHTML = "";
      clearTalkDetail();
      return;
    }
    if (node.label !== selectedSpeakerName) {
      clearTalkDetail();
    }
    selectedSpeakerName = node.label;
    const titles = talkTitleIndex.get(node.label) || [];
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
    if (selectedTalkId) {
      setTalkListVisible(false);
    } else {
      setTalkListVisible(true);
    }
  }

  function showNodeCard(node) {
    elements.card.hidden = false;
    elements.cardTitle.textContent = node.label;
    const snippet = matchSnippet(node);
    elements.cardMeta.textContent = snippet
      ? `${formatNodeMeta(node)} · ${snippet}`
      : formatNodeMeta(node);
    updateNodeContacts(node);
    updateNodeTalks(node);
    updateDataInfoLinks(node);
    setDataInfoOpen(false);
  }

  function focusNode(nodeId) {
    const node = graphNodes.find((item) => item.id === nodeId);
    if (!node || node.x == null || node.y == null) return;

    const focusIds = new Set([nodeId, ...neighborIds(nodeId)]);
    fitToView({
      animate: true,
      transitionMs: 450,
      nodeIds: focusIds,
      minScale: isCoarsePointer ? 1.2 : 1.4,
      maxScale: isCoarsePointer ? 2.2 : 2.8,
      padding: 72,
    });
  }

  function clearSelection() {
    selectedNodeId = null;
    pendingNodeFocus = false;
    clearTalkDetail();
    renderGraph({ resetZoom: true });
  }

  function selectNode(nodeId, { focus = false } = {}) {
    selectedNodeId = nodeId;
    pendingNodeFocus = focus;
    if (!focus) userAdjustedZoom = false;
    renderGraph();
  }

  function previewSearch(query) {
    updateMatches(query);
    selectedNodeId = null;

    if (!searchQuery) {
      setSearchStatus("");
      renderGraph({ resetZoom: true });
      return;
    }

    if (!matchedNodeIds.size) {
      setSearchStatus("No nodes matched that search.", true);
      renderGraph({ resetZoom: true });
      return;
    }

    setSearchStatus(
      `${matchedNodeIds.size.toLocaleString()} match${matchedNodeIds.size === 1 ? "" : "es"} (matches always shown; co-authors fill remaining slots)`
    );
    renderGraph({ resetZoom: true });
  }

  function applySearch(query, { focus = true } = {}) {
    updateMatches(query);
    selectedNodeId = null;

    if (!searchQuery) {
      setSearchStatus("");
      pendingNodeFocus = false;
      renderGraph({ resetZoom: true });
      return;
    }

    if (!matchedNodeIds.size) {
      setSearchStatus("No nodes matched that search.", true);
      renderGraph({ resetZoom: true });
      return;
    }

    setSearchStatus(
      `${matchedNodeIds.size.toLocaleString()} node${matchedNodeIds.size === 1 ? "" : "s"} matched (all matches shown; co-authors fill remaining slots)`
    );

    if (focus) {
      const firstMatch = currentGraph().nodes.find((node) => matchedNodeIds.has(node.id));
      if (firstMatch) {
        selectNode(firstMatch.id, { focus: true });
        return;
      }
    }

    renderGraph({ resetZoom: !focus });
  }

  function setNodeLimit(value) {
    const nextLimit = parseNodeLimit(value);
    if (nextLimit === nodeLimit) return;
    nodeLimit = nextLimit;
    renderGraph({ resetZoom: true });
  }

  function buildSuggestions(query) {
    const trimmed = query.trim().toLowerCase();
    if (trimmed.length < 2) return [];

    return currentGraph()
      .nodes.filter((node) => nodeMatchesSearch(node, trimmed))
      .sort((a, b) => b.connections - a.connections)
      .slice(0, 8)
      .map((node) => ({
        label: node.label,
        detail: formatNodeMeta(node),
        query: node.label,
        nodeId: node.id,
      }));
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
    renderGraph({ resetZoom: true });
  }

  function resetView() {
    clearSelection();
    resetZoom();
  }

  function resetZoom() {
    userAdjustedZoom = false;
    autoFitPending = true;
    fitToView({ animate: true });
    autoFitPending = false;
  }

  function updateDimensions() {
    const w = width();
    const h = height();
    svg.attr("viewBox", `0 0 ${w} ${h}`).attr("width", w).attr("height", h);
  }

  function resize() {
    placeNetworkCard();
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
      if (!userAdjustedZoom) {
        if (selectedNodeId) {
          focusNode(selectedNodeId);
        } else {
          fitToView({ animate: false });
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
      const authorButton = event.target.closest(".network-talk-author-btn[data-node-id]");
      if (authorButton && elements.card.contains(authorButton)) {
        event.preventDefault();
        event.stopPropagation();
        selectNode(authorButton.dataset.nodeId, { focus: true });
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
        const titles = talkTitleIndex.get(selectedSpeakerName) || [];
        elements.cardTalks.innerHTML = renderTalkTitlesHtml(titles, {
          kicker: "Talks",
          resolveTalkId: resolveTalkIdForEntry,
        });
      }
    });
  }

  renderSearchResults([]);

  return {
    setMode,
    setNodeLimit,
    resize,
    resetZoom,
    clearSelection,
    previewSearch,
    applySearch,
    buildSuggestions,
    selectNode,
  };
}
