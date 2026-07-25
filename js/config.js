/** Runtime config for the static site (set via meta tags in index.html). */

function metaContent(name) {
  return document.querySelector(`meta[name="${name}"]`)?.content?.trim() || "";
}

export const OFFSET_API_URL = metaContent("icrs-offset-api");
