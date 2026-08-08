# Person registry

Internal source of truth for **people** in the ICRS pipeline.

## Two different IDs — do not confuse them

| Field | Example | Purpose |
|-------|---------|---------|
| `person_key` | `icrs-p-00016` | **Our** stable key — use everywhere in the pipeline |
| `official_delegate_id` | *(local only)* | Official offset-registration ID — stored in gitignored `person_registry_official_ids.csv` |
| `attended` | `True` / `False` | **On delegate list = attended.** Programme-only names are not attended. |

Every person gets an `icrs-p-*` key. Official delegate IDs are written to `data/registry/person_registry_official_ids.csv` during registry build; that file is **gitignored** and must not be published.

### Attendance rule

- `attended=True` when the person appears on the delegate list (whether or not they have a programme talk).
- `attended=False` for programme-only names (listed in `person_registry_unmatched.csv` as `programme_only_not_attended`).

## Build

```bash
python scripts/build_pipeline.py registry
```

Outputs:

| File | Contents |
|------|----------|
| `data/registry/person_registry.csv` | One row per person (no official IDs) |
| `data/registry/person_registry_official_ids.csv` | **Local only** — `person_key` + official delegate ID |
| `data/registry/person_name_aliases.csv` | Name variant → `person_key` |
| `data/registry/person_registry_unmatched.csv` | Flagged rows needing review |
| `data/registry/person_registry.meta.json` | Build metrics |

## How matching works

1. **Token overlap** — programme presenter ↔ delegate-list name (rejects when presenter name has more tokens, e.g. Sam King ≠ Sam King Fung Yiu). Presenters are indexed by **name + affiliation** so homonyms at different institutions stay separate (e.g. the two Takashi Nakamuras).
2. **Official ID review** — confirmed pairs from all `delegate_id_match_review_*_merged.csv` files (highest version wins per delegate name). Shared `id_full_name` values that map to multiple delegates are **not** used to bridge rows.
3. **Manual overrides** — `data/registry/person_registry_overrides.csv` for exceptional **name** merges (e.g. duplicate PDF rows). For organisation fixes use `data/overrides/delegate_organisation_overrides.csv` (see below).
4. Union-find merges linked names into one `person_key`

Presenter display names are preferred for `canonical_name`; delegate list supplies org/country.

## Review flags (`person_registry_unmatched.csv`)

| `issue` | Meaning |
|---------|---------|
| `programme_only_not_attended` | Programme speaker not on delegate list — excluded from attendance |
| `conflicting_official_delegate_ids` | Multiple official IDs at same priority (rare; needs manual fix) |

## Lookup in code

```python
from src.registry.person_registry import lookup_person_key, load_person_registry

key = lookup_person_key("Abdul M. Ada")  # -> icrs-p-00016
```

## Organisation fixes (empty or wrong org on delegate list)

| File | Purpose |
|------|---------|
| `data/overrides/delegate_organisation_overrides.csv` | Set organisation by **full_name** (preferred for Kelly Lumpkin–style fixes) |
| `data/sources/delegates.json` | Direct edit when re-parsing the PDF is not needed |
| `data/registry/person_registry_overrides.csv` | **Names only** (`merge`/`split`) — not for org/country |

`delegate_organisation_overrides.csv` columns: `full_name`, `organisation`, `country` (optional), `notes`.

Example — the existing `Kelly` row only matched first-name PDF bleed; add the speaker's full name:

```csv
full_name,organisation,notes
Kelly Lumpkin,Georgia Institute of Technology,Speaker; PDF also has truncated row as Kelly
```

Then rebuild: `python scripts/build_pipeline.py registry affiliations`.

For orgs with no programme affiliation and empty delegate org (e.g. Dr Mickael Leclercq), look up the institution in the offset registration or contacts data and add a `delegate_organisation_overrides.csv` row or edit `delegates.json` directly.
