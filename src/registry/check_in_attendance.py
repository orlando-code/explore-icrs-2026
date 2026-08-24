"""Conference check-in as ground truth for who attended."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

from src.data_paths import (
    CHECK_IN_DELEGATES_CSV,
    CHECK_IN_OVERRIDES_CSV,
    PERSON_OFFICIAL_IDS_CSV,
    PERSON_REGISTRY_CSV,
    REGISTRY,
)
from src.registry.affiliation_registry import _make_affiliation
from src.sources.delegates import normalize_person_name

DEFAULT_CHECK_IN_PATH = CHECK_IN_DELEGATES_CSV
DEFAULT_CHECK_IN_SOURCE_PATH = REGISTRY / "all_delegates_checked_in.csv"
DEFAULT_CHECK_IN_OVERRIDES_PATH = CHECK_IN_OVERRIDES_CSV

CHECK_IN_COLUMNS = [
    "ID",
    "first name",
    "last name",
    "privacy",
    "organisation",
    "country",
]

PUBLIC_REGISTRY_EXTRA_COLUMNS = ["checked_in", "privacy_restricted"]


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes"}


def _normalize_org(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _display_name_from_check_in(row: pd.Series) -> str:
    first = str(row.get("first name") or "").strip()
    last = str(row.get("last name") or "").strip()
    if _truthy(row.get("privacy")) and not last:
        return first
    parts = [part for part in (first, last) if part]
    return " ".join(parts).strip()


CHECK_IN_COUNTRY_ALIASES = {
    "chinese taipei": "Taiwan",
}


def _normalize_check_in_country(value: object) -> str:
    label = str(value or "").strip()
    if not label:
        return ""
    return CHECK_IN_COUNTRY_ALIASES.get(label.casefold(), label)


def _split_registry_full_name(full_name: str) -> tuple[str, str]:
    """Split a registry canonical_name into first and last name."""
    cleaned = " ".join(str(full_name or "").split())
    if not cleaned:
        return "", ""
    tokens = cleaned.split()
    honorifics = {"dr", "prof", "professor", "mr", "mrs", "ms", "miss"}
    while tokens and tokens[0].rstrip(".").casefold() in honorifics:
        tokens = tokens[1:]
    if not tokens:
        return "", ""
    if len(tokens) == 1:
        return tokens[0], ""
    return " ".join(tokens[:-1]), tokens[-1]


def _registered_official_delegate_ids(
    official: pd.DataFrame,
) -> frozenset[int]:
    """IDs from person_registry_official_ids (pre-registration / delegate-list matches only)."""
    if official.empty:
        return frozenset()
    if "official_id_match_tier" in official.columns:
        tier = official["official_id_match_tier"].astype(str).str.strip()
        official = official.loc[~tier.eq("check_in_only")].copy()
    ids = pd.to_numeric(official["official_delegate_id"], errors="coerce").dropna()
    return frozenset(int(value) for value in ids)


def load_check_in_overrides(
    path: Path | str = DEFAULT_CHECK_IN_OVERRIDES_PATH,
) -> pd.DataFrame:
    """Manual fixes for check-in rows: country, organisation, names (keyed by delegate ID)."""
    override_path = Path(path)
    columns = [
        "official_delegate_id",
        "country",
        "organisation",
        "first_name",
        "last_name",
        "notes",
    ]
    if not override_path.exists():
        return pd.DataFrame(columns=columns)
    frame = pd.read_csv(override_path, dtype=str).fillna("")
    frame = frame.rename(columns=lambda col: str(col).strip().lower())
    frame["official_delegate_id"] = frame["official_delegate_id"].astype(str).str.strip()
    return frame.reindex(columns=[c for c in columns if c in frame.columns or c == "official_delegate_id"])


def apply_check_in_overrides(
    frame: pd.DataFrame,
    overrides: pd.DataFrame | None = None,
    *,
    overrides_path: Path | str = DEFAULT_CHECK_IN_OVERRIDES_PATH,
) -> pd.DataFrame:
    """Apply optional override columns onto a check-in frame (matched on ID)."""
    if overrides is None:
        overrides = load_check_in_overrides(overrides_path)
    if overrides.empty or frame.empty:
        return frame

    result = frame.copy()
    result["ID"] = pd.to_numeric(result["ID"], errors="coerce").astype("Int64")
    overrides = overrides.copy()
    overrides["ID"] = pd.to_numeric(
        overrides["official_delegate_id"], errors="coerce"
    ).astype("Int64")

    for column, override_col in (
        ("country", "country"),
        ("organisation", "organisation"),
        ("first name", "first_name"),
        ("last name", "last_name"),
    ):
        if override_col not in overrides.columns:
            continue
        override_values = overrides.set_index("ID")[override_col]
        for check_in_id, value in override_values.items():
            if pd.isna(check_in_id) or not str(value or "").strip():
                continue
            mask = result["ID"].eq(check_in_id)
            result.loc[mask, column] = str(value).strip()

    if "country" in result.columns:
        result["country"] = result["country"].map(_normalize_check_in_country)
    return result


def build_check_in_privacy_export(
    *,
    checked_in_path: Path | str = DEFAULT_CHECK_IN_SOURCE_PATH,
    official_ids_path: Path | str = PERSON_OFFICIAL_IDS_CSV,
    overrides_path: Path | str = DEFAULT_CHECK_IN_OVERRIDES_PATH,
    output_path: Path | str = DEFAULT_CHECK_IN_PATH,
) -> pd.DataFrame:
    """Merge Innovators check-in with official IDs; write delegates_checked_in_with_privacy.csv."""
    checked = pd.read_csv(
        Path(checked_in_path),
        dtype={"ID": "Int64"},
        encoding="latin-1",
    )
    checked.columns = checked.columns.str.strip().str.lower()
    checked.rename(columns={"organsation": "organisation"}, inplace=True)
    if "id" in checked.columns and "ID" not in checked.columns:
        checked = checked.rename(columns={"id": "ID"})
    for column in ("first name", "organisation", "country"):
        if column not in checked.columns:
            checked[column] = ""
    if "last name" not in checked.columns:
        checked["last name"] = ""

    official = pd.read_csv(Path(official_ids_path), dtype=str).fillna("")
    official["ID"] = pd.to_numeric(
        official["official_delegate_id"], errors="coerce"
    ).astype("Int64")
    registered_ids = _registered_official_delegate_ids(official)

    merged = checked.merge(
        official[["ID", "canonical_name", "person_key"]],
        on="ID",
        how="left",
    )
    merged = apply_check_in_overrides(
        merged,
        overrides_path=overrides_path,
    )

    first_names: list[str] = []
    last_names: list[str] = []
    privacy_flags: list[str] = []
    for _, row in merged.iterrows():
        check_in_id = int(row["ID"])
        privacy = check_in_id not in registered_ids
        privacy_flags.append("TRUE" if privacy else "FALSE")
        if privacy:
            first = str(row.get("first name") or "").strip()
            last = str(row.get("last name") or "").strip()
        else:
            first, last = _split_registry_full_name(str(row.get("canonical_name") or ""))
        first_names.append(first)
        last_names.append(last)

    output = pd.DataFrame(
        {
            "ID": merged["ID"],
            "first name": first_names,
            "last name": last_names,
            "privacy": privacy_flags,
            "organisation": merged["organisation"].fillna("").astype(str).str.strip(),
            "country": merged["country"].fillna("").astype(str).str.strip(),
        }
    ).sort_values("ID", na_position="last")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(output_path, index=False)
    return output


def load_check_in_attendees(path: Path | str = DEFAULT_CHECK_IN_PATH) -> pd.DataFrame:
    """Load Innovators check-in export (Latin-1 or UTF-8)."""
    check_in_path = Path(path)
    if not check_in_path.exists():
        return pd.DataFrame(columns=CHECK_IN_COLUMNS)

    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            frame = pd.read_csv(check_in_path, dtype=str, encoding=encoding).fillna("")
            break
        except UnicodeDecodeError:
            frame = None
    if frame is None:
        raise UnicodeDecodeError("check-in", b"", 0, 1, "Could not decode check-in CSV")

    frame = frame.rename(columns=lambda col: str(col).strip())
    frame["ID"] = pd.to_numeric(frame["ID"], errors="coerce").astype("Int64")
    frame = frame.dropna(subset=["ID"]).copy()
    frame["privacy"] = frame.get("privacy", pd.Series(dtype=str)).map(
        lambda value: "TRUE" if _truthy(value) else "FALSE"
    )
    for column in ("first name", "last name", "organisation", "country"):
        if column not in frame.columns:
            frame[column] = ""
    frame = apply_check_in_overrides(frame)
    frame["country"] = frame["country"].map(_normalize_check_in_country)
    return frame


def _next_person_key(existing_keys: set[str]) -> str:
    max_index = 0
    for key in existing_keys:
        match = re.fullmatch(r"icrs-p-(\d+)", str(key).strip())
        if match:
            max_index = max(max_index, int(match.group(1)))
    return f"icrs-p-{max_index + 1:05d}"


def _match_check_in_row(
    row: pd.Series,
    *,
    id_to_person_key: dict[str, str],
    registry_by_key: dict[str, pd.Series],
    registry_by_name_org: dict[tuple[str, str], str],
    registry_by_org_first: dict[tuple[str, str], str],
) -> str:
    delegate_id = str(int(row["ID"]))
    person_key = id_to_person_key.get(delegate_id, "")
    if person_key and person_key not in registry_by_key:
        person_key = ""
    if person_key:
        return person_key

    org_key = _normalize_org(row.get("organisation"))
    first_norm = normalize_person_name(str(row.get("first name") or ""))
    display_norm = normalize_person_name(_display_name_from_check_in(row))
    if org_key and display_norm:
        person_key = registry_by_name_org.get((display_norm, org_key), "")
        if person_key:
            return person_key
    if org_key and first_norm:
        person_key = registry_by_org_first.get((first_norm, org_key), "")
        if person_key:
            return person_key

    country = str(row.get("country") or "").strip()
    if display_norm and org_key:
        for key, person in registry_by_key.items():
            person_org = _normalize_org(person.get("organisation"))
            person_country = str(person.get("country") or "").strip().casefold()
            if person_org != org_key:
                continue
            if country and person_country and person_country != country.casefold():
                continue
            variants = str(person.get("name_variants") or "").split(";")
            names = {normalize_person_name(str(person.get("canonical_name") or ""))}
            names.update(normalize_person_name(v) for v in variants if v.strip())
            if display_norm in names or (first_norm and first_norm in names):
                return key
    return ""


def apply_check_in_attendance(
    registry: pd.DataFrame,
    aliases: pd.DataFrame,
    *,
    check_in_path: Path | str = DEFAULT_CHECK_IN_PATH,
    official_ids_path: Path | str = PERSON_OFFICIAL_IDS_CSV,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Set attended/checked_in from check-in; add unmatched rows; compute privacy flags."""
    check_in = load_check_in_attendees(check_in_path)
    metrics: dict[str, Any] = {
        "check_in_rows": int(len(check_in)),
        "check_in_matched": 0,
        "check_in_new_people": 0,
        "check_in_unmatched": 0,
        "privacy_restricted_attendees": 0,
        "last_minute_dropout_count": 0,
    }
    if check_in.empty:
        registry = registry.copy()
        registry["checked_in"] = False
        registry["privacy_restricted"] = False
        registry["attended"] = False
        return registry, aliases, metrics

    official_ids = (
        pd.read_csv(official_ids_path, dtype=str).fillna("")
        if Path(official_ids_path).exists()
        else pd.DataFrame(columns=["person_key", "official_delegate_id"])
    )
    id_to_person_key = {
        str(row["official_delegate_id"]).strip(): str(row["person_key"]).strip()
        for _, row in official_ids.iterrows()
        if str(row.get("official_delegate_id") or "").strip()
        and str(row.get("person_key") or "").strip()
    }

    registry = registry.copy()
    if "official_delegate_id" not in registry.columns:
        registry["official_delegate_id"] = ""

    registry_by_key = {
        str(row["person_key"]): row for _, row in registry.iterrows()
    }
    registry_by_name_org: dict[tuple[str, str], str] = {}
    registry_by_org_first: dict[tuple[str, str], str] = {}
    for _, person in registry.iterrows():
        person_key = str(person["person_key"])
        org_key = _normalize_org(person.get("organisation"))
        canonical_norm = normalize_person_name(str(person.get("canonical_name") or ""))
        if org_key and canonical_norm:
            registry_by_name_org.setdefault((canonical_norm, org_key), person_key)
        first_token = canonical_norm.split()[0] if canonical_norm else ""
        if org_key and first_token:
            registry_by_org_first.setdefault((first_token, org_key), person_key)

    checked_in_keys: set[str] = set()
    privacy_by_key: dict[str, bool] = {}
    new_rows: list[dict[str, Any]] = []
    new_aliases: list[dict[str, str]] = []
    unmatched_rows: list[dict[str, Any]] = []

    existing_keys = set(registry_by_key.keys())

    for _, row in check_in.iterrows():
        person_key = _match_check_in_row(
            row,
            id_to_person_key=id_to_person_key,
            registry_by_key=registry_by_key,
            registry_by_name_org=registry_by_name_org,
            registry_by_org_first=registry_by_org_first,
        )
        privacy_flag = _truthy(row.get("privacy"))
        if person_key and person_key not in registry_by_key:
            person_key = ""
        if person_key:
            checked_in_keys.add(person_key)
            privacy_by_key[person_key] = privacy_flag
            metrics["check_in_matched"] += 1
            continue

        person_key = _next_person_key(existing_keys)
        existing_keys.add(person_key)
        checked_in_keys.add(person_key)
        privacy_by_key[person_key] = privacy_flag
        metrics["check_in_new_people"] += 1

        organisation = str(row.get("organisation") or "").strip()
        country = str(row.get("country") or "").strip()
        canonical_name = _display_name_from_check_in(row) or f"Check-in delegate {int(row['ID'])}"
        new_rows.append(
            {
                "person_key": person_key,
                "canonical_name": canonical_name,
                "organisation": organisation,
                "country": country,
                "in_delegate_list": False,
                "in_programme": False,
                "attended": True,
                "checked_in": True,
                "is_speaker": False,
                "official_delegate_id": str(int(row["ID"])),
                "official_id_match_tier": "check_in_only",
                "match_methods": "check_in_unmatched",
                "name_variants": canonical_name,
                "needs_review": True,
                "review_reason": "check_in_only_not_in_registry",
                "privacy_restricted": privacy_flag,
            }
        )
        new_aliases.append(
            {
                "person_key": person_key,
                "name_variant": canonical_name,
                "normalized_name": normalize_person_name(canonical_name),
                "source": "check_in",
            }
        )
        unmatched_rows.append(
            {
                "check_in_id": int(row["ID"]),
                "canonical_name": canonical_name,
                "organisation": organisation,
                "country": country,
                "privacy": row.get("privacy"),
            }
        )

    metrics["check_in_unmatched"] = len(unmatched_rows)

    if new_rows:
        registry = pd.concat([registry, pd.DataFrame(new_rows)], ignore_index=True)

    in_programme = registry["in_programme"].map(_truthy)
    registry["checked_in"] = registry["person_key"].astype(str).isin(checked_in_keys)
    registry["attended"] = registry["checked_in"]
    registry["privacy_restricted"] = [
        bool(
            privacy_by_key.get(str(person_key), False)
            and not _truthy(in_programme_flag)
        )
        for person_key, in_programme_flag in zip(
            registry["person_key"].astype(str),
            registry["in_programme"],
            strict=True,
        )
    ]
    metrics["privacy_restricted_attendees"] = int(registry["privacy_restricted"].sum())

    on_delegate_list = registry["in_delegate_list"].map(_truthy)
    metrics["last_minute_dropout_count"] = int(
        (on_delegate_list & ~registry["checked_in"]).sum()
    )

    if new_aliases:
        aliases = pd.concat([aliases, pd.DataFrame(new_aliases)], ignore_index=True)
        aliases = aliases.drop_duplicates(subset=["person_key", "normalized_name"])

    metrics["checked_in_attendees"] = int(registry["checked_in"].sum())
    return registry, aliases, metrics


def load_privacy_restricted_person_keys(
    path: Path | str = PERSON_REGISTRY_CSV,
) -> frozenset[str]:
    """Person keys omitted from public emissions map/search (privacy, not on programme)."""
    registry_path = Path(path)
    if not registry_path.exists():
        return frozenset()
    registry = pd.read_csv(registry_path, dtype=str).fillna("")
    if "privacy_restricted" not in registry.columns:
        return frozenset()
    mask = registry["privacy_restricted"].map(_truthy)
    return frozenset(registry.loc[mask, "person_key"].astype(str).str.strip())


def check_in_affiliation(row: pd.Series) -> str:
    organisation = str(row.get("organisation") or "").strip()
    country = str(row.get("country") or "").strip()
    if organisation and country:
        return _make_affiliation(organisation, country)
    if organisation:
        return organisation
    return ""
