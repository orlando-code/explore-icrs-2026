# `data/overrides/`

Manual corrections for organisations and map visibility.


| File                                  | Description                             |
| ------------------------------------- | --------------------------------------- |
| `delegate_organisation_overrides.csv` | Fix org/country by delegate `full_name` |
| `map_excluded_names.txt`              | Optional names/affiliations to omit from delegate + emissions maps |


`map_excluded_names.txt` is optional. Most affiliations without precise geocodes (e.g. Fluvio → Australia capital, Individual → New Zealand capital) use the normal capital-fallback behaviour and do not need listing here.

**Local only (gitignored):** `delegate_id_match_review_*_merged.csv` – latest curated name ↔ official-ID links for offset verification.

Usage: [pipeline/_README.md](../../pipeline/_README.md#manual-overrides).
