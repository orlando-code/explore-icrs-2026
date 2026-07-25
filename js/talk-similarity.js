export function createTalkSimilarityLookup(similaritiesData, talksById) {
  const byId = similaritiesData?.by_id || {};

  function findSimilar(talk) {
    if (!talk?.id) return [];
    const entries = byId[talk.id] || [];
    return entries
      .map((entry) => ({
        talk: talksById[String(entry.id)],
        reason: String(entry.reason || "").trim(),
        score: entry.score,
      }))
      .filter((entry) => entry.talk);
  }

  return { findSimilar };
}

function lookupTitleIds(titleIndex, title) {
  const trimmed = String(title || "").trim();
  if (!trimmed || !titleIndex) return [];
  return titleIndex[trimmed.toLowerCase()] || titleIndex[trimmed] || [];
}

export function resolveTalkId(entry, talksData, speakerName = "") {
  if (!entry) return null;
  if (entry.talk_id) return String(entry.talk_id);

  const title = String(entry.title || "").trim();
  const ids = lookupTitleIds(talksData?.title_index, title);
  if (!ids.length) return null;
  if (ids.length === 1) return ids[0];

  if (speakerName) {
    for (const id of ids) {
      const talk = talksData.by_id?.[id];
      if (!talk) continue;
      if (talk.presenter === speakerName || (talk.authors || []).includes(speakerName)) {
        return id;
      }
    }
  }

  return ids[0];
}
