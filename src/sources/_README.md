# `src/sources/`

Load and process committed JSONs under `data/sources/`.


| Module         | Role                                                                 |
| -------------- | -------------------------------------------------------------------- |
| `programme.py` | Talks, sessions, presenters from `programme.json` + `abstracts.json` |
| `delegates.py` | Delegate list, map grouping, `non-speaking-delegates.js` export      |


`delegates.py` exports `delegate_person_key()` (returns `icrs-p-*` only) and name-normalisation helpers. Person identity for map/network/emissions exports is resolved through `src/registry/key_resolution.py`; `non-speaking-delegates.js` includes `DELEGATE_PERSON_KEY_ALIASES` for the browser.


