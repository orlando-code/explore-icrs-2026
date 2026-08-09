# `src/profiles/`

Optional network-tab enrichment (not part of default `build_pipeline.py all`).


| Module                     | Role                                              |
| -------------------------- | ------------------------------------------------- |
| `speaker_profiles.py`      | Build/export `js/speaker-profiles.js`             |
| `talk_similarity_build.py` | Embedding similarity -> `js/talk-similarities.js` |


Runtime UI: `js/network.js` + hand-maintained `js/talk-similarity.js` (lookup over the static build).