# Person registry

Internal source of truth for **people** in the ICRS pipeline.

## Two different IDs for each person


| Field                  | Example                                                     | Purpose                                                                     |
| ---------------------- | ----------------------------------------------------------- | --------------------------------------------------------------------------- |
| `person_key`           | `icrs-p-00016`                                              | **Our** stable key – use everywhere in the pipeline                         |
| `official_delegate_id` | *(local only to enable carbon contribution security check)* | Official offset-registration ID found on official conference correspondence |
| `attended`             | `True` / `False`                                            | **On delegate list = attended.** Programme-only names did not attend.       |


Every person gets an `icrs-p-*` key. Official delegate IDs are written to the local-only `data/registry/person_registry_official_ids.csv` during registry build.

### Attendance rule

- `attended=True` when the person appears on the delegate list (whether or not they have a programme talk).
- `attended=False` for programme-only names (listed in `person_registry_unmatched.csv` as `programme_only_not_attended`). Possible simplification, will be working with the conference organisers to make this more accurate.



## Build

```bash
python scripts/build_pipeline.py registry
```

Outputs:


| File                                             | Contents                                             |
| ------------------------------------------------ | ---------------------------------------------------- |
| `data/registry/person_registry.csv`              | One row per person                                   |
| `data/registry/person_registry_official_ids.csv` | **Local only** – `person_key` + official delegate ID |
| `data/registry/person_name_aliases.csv`          | Name variant → `person_key`                          |
| `data/registry/person_registry_unmatched.csv`    | Flagged rows needing review                          |
| `data/registry/person_registry.meta.json`        | Build metrics                                        |




## How matching works

1. **Token overlap** – programme presenter ↔ delegate-list name (rejects when presenter name has more tokens, e.g. John Smith ≠ John New World Smith). Presenters are indexed by **name + affiliation** so homonyms at different institutions stay separate.
2. **Official ID review** – confirmed pairs from all `delegate_id_match_review_*_merged.csv` files (highest version (most recent) wins per delegate name). Shared `id_full_name` values that map to multiple delegates are **not** used to bridge rows.
3. **Manual overrides** – `data/registry/person_registry_overrides.csv` for exceptional **name** merges (e.g. duplicate PDF rows). For organisation fixes use `data/overrides/delegate_organisation_overrides.csv` (see below).
4. Union-find merges linked names into one `person_key`

Presenter display names are preferred for `canonical_name`; delegate list supplies organisation/country.

## Review flags (`person_registry_unmatched.csv`)


| `issue`                             | Meaning                                                           |
| ----------------------------------- | ----------------------------------------------------------------- |
| `programme_only_not_attended`       | Programme speaker not on delegate list – excluded from attendance |
| `conflicting_official_delegate_ids` | Multiple official IDs at same priority (rare; needs manual fix)   |




## Lookup in code

```python
from src.registry.person_registry import lookup_person_key, load_person_registry

key = lookup_person_key("Alexander A. Hamilton")  # -> icrs-p-XXXXX
```



## Organisation fixes (empty or wrong organisation on delegate list)


| File                                                 | Purpose                                                                     |
| ---------------------------------------------------- | --------------------------------------------------------------------------- |
| `data/overrides/delegate_organisation_overrides.csv` | Set organisation by **full_name** (preferred for Kelly Lumpkin–style fixes) |
| `data/sources/delegates.json`                        | Direct edit when re-parsing the PDF is not needed – recreated automatically |
| `data/registry/person_registry_overrides.csv`        | **Names only** (`merge`/`split`) – not for organisation/country             |


`delegate_organisation_overrides.csv` columns: `full_name`, `organisation`, `country` (optional), `notes`.

Example – the existing `Kelly` row only matched first-name PDF bleed; add the speaker's full name:

```csv
full_name,organisation,notes
Kelly Lumpkin,Georgia Institute of Technology,Speaker; PDF also has truncated row as Kelly
```

Then rebuild: `python scripts/build_pipeline.py registry affiliations`.

For organisations with no programme affiliation and empty delegate organisation (e.g. Dr Mickael Leclercq), look up the institution in the offset registration or contacts data and add a `delegate_organisation_overrides.csv` row, or edit `delegates.json` directly.