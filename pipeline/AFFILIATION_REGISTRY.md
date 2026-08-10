# Affiliation registry

Internal source of truth for **affiliations** (organisation + country pairs).

## Key fields


| Field                         | Example                                        | Role                                                                             |
| ----------------------------- | ---------------------------------------------- | -------------------------------------------------------------------------------- |
| `affiliation_key`             | `icrs-a-00142`                                 | Pipeline source of truth for one institution in one country                      |
| `canonical_affiliation`       | `University of Hawaiʻi - Mānoa, United States` | Standard display label, retaining accents                                        |
| `primary_organisation`        | `KAUST`                                        | Resolved primary institution (after manual review)                               |
| `secondary_organisation`      | `Harvard T.H. Chan School of Public Health`    | Secondary institution when a delegate/programme row lists a compound affiliation |
| `redirect_to_affiliation_key` | `icrs-a-00287`                                 | Compound rows redirect here; attendee counts roll up to the target               |
| `plot_on_map`                 | `True`                                         | Whether this row should appear on the map / carry emissions                      |


Coordinates are metadata on the registry row, resolved from existing geocode files – not a separate identity system.

## Build

```bash
python scripts/build_pipeline.py affiliations
# run after person registry:
python scripts/build_pipeline.py registry affiliations
```

Outputs:


| File                                               | Contents                                           |
| -------------------------------------------------- | -------------------------------------------------- |
| `data/registry/affiliation_registry.csv`           | One row per organisation+country                   |
| `data/registry/affiliation_aliases.csv`            | Raw variant → `affiliation_key`                    |
| `data/registry/affiliation_registry_unmatched.csv` | Rows still missing geocodes / country after review |
| `data/registry/affiliation_registry.meta.json`     | Build metrics                                      |




## Manual review workflow

Some affiliations need human judgement (missing country on programme-only strings, compound organisation names, geocode gaps).

1. **Build** the registry (commands above).
2. **Open** `data/registry/affiliation_registry_unmatched.csv` – one row per affiliation that still needs review.
3. **Edit** in a spreadsheet:
  - Fill `country` where missing.
  - Set `primary organisation` and `secondary organisation` for compound affiliations (e.g. `KAUST & Harvard…` → primary `KAUST`, secondary `Harvard T.H. Chan School of Public Health`).
  - Correct `organisation` / `canonical_affiliation` labels if needed.
4. **Save as** `data/registry/affiliation_registry_unmatched_reviewed.csv` (keep the header; add `primary organisation` and `secondary organisation` columns).
5. **Rebuild** – the build reads `affiliation_registry_unmatched_reviewed.csv` automatically and applies corrections.



### Primary / secondary rules

- Delegates or programme rows with a **secondary organisation** are matched to their **primary** organisation for attendee counts and map placement.
- Compound affiliation rows get `redirect_to_affiliation_key` pointing at the primary organisation+country row when one already exists; otherwise the compound row is rewritten in place to the primary organisation.
- A **secondary organisation is not plotted** and does not carry emissions **unless** a different delegate lists that organisation as their primary. (Abbreviated names such as `Scripps Inst. of Oceanography` are treated separately from `Scripps Institution of Oceanography`.)



## Standardization sources (applied in order)

1. **Delegate list authority** – `organisation` + `country` (+ `country_code`) from `delegates.json` are the source of truth when present
2. **Smart affiliation parsing** – trailing country segments detected via `country_to_iso2()` (handles organisationnames with commas)
3. `data/geocodes/affiliation_display_aliases.json` – reviewed display aliases
4. `src/geocode.py` – `canonical_affiliation_key()` institution rules
5. `data/registry/affiliation_registry_overrides.csv` – manual merge/canonical overrides
6. `data/registry/affiliation_registry_unmatched_reviewed.csv` – reviewed country fixes and primary/secondary splits (matched by organisation+country `group_key`, not `affiliation_key`)
7. Geocode metadata from `data/geocodes/affiliation_geocodes.csv` + `data/geocodes/affiliation_geocodes_manual_01.csv` (rows with invalid countries after parsing are skipped)
8. Pin overrides from `data/geocodes/geocode_overrides.json`



## Lookup

Each affiliation has a stable internal id: `affiliation_key` (`icrs-a-NNNNN`). Keys are reassigned when the registry is rebuilt, so **join on organisation+country or alias variants**, not saved `affiliation_key` values in review files.

### `group_key` vs `affiliation_key`


|                             | `group_key`                                           | `affiliation_key`                    |
| --------------------------- | ----------------------------------------------------- | ------------------------------------ |
| **Form**                    | `university of queensland`                            | `australia`                          |
| **Purpose**                 | Deduplicate variants of the same organisation+country | Row id in `affiliation_registry.csv` |
| **Stable across rebuilds?** | Yes (content-derived)                                 | No (serial reassignment)             |
| **Use for**                 | Merges, alias lookup, review CSV matching             | Traceability in exports, geocode CSV |


`group_key` is the organisation fingerprint (canonical organisationname + country). It is not a separate entity from `affiliation_key` – it is how I decide which variants belong to the same `icrs-a-*` row. Think of `affiliation_key` as the primary key and `group_key` as the natural key.

```python
from src.registry.affiliation_lookup import AffiliationIndex, lookup_affiliation_key

index = AffiliationIndex.load()
key = index.resolve_key("University of Queensland", "Australia")
row = index.resolve_row("University of Queensland", "Australia")
```



## Geocode refresh (Google Maps, cached)

```bash
# Missing rows from affiliation_registry → Google API → affiliation_geocodes.csv
python scripts/run_affiliation_geocoding.py

# Or via pipeline (also rebuilds registry afterward)
python scripts/build_pipeline.py affiliations geocode --refresh-geocodes
```

Cache: `data/cache/google_geocode_cache.json`. New CSV rows include `affiliation_key` for traceability.

## Relation to people registry

`attendee_count` on each affiliation row counts attended people (`person_registry.attended=True`) at that organisation+country, **after** primary/secondary redirects from the reviewed file.

Use `redirect_to_affiliation_key` to resolve compound affiliations to the row that should receive map pins and emissions.

Programme-only affiliations (no delegate-list attendees) are still listed; `plot_on_map` is `True` when geocoded and the row has programme presence, attendees, or delegate-list membership (unless redirected or secondary-only).