"""Estimate conference travel emissions via emissions.dev."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pycountry
import requests
from rich.console import Console
from rich.table import Table

from src.geocoding.geocode import _extract_country_hints
from src.sources.programme import load_talks
from src.data_paths import (
    COUNTRY_BOUNDARIES_REL,
    GEOCODE_OVERRIDES_JSON,
    NATIONAL_PER_CAPITA_JSON,
    REVERSE_GEOCODE_CACHE_JSON,
    TRAVEL_EMISSIONS_CACHE_JSON,
)

_MISSING_AFFILIATION_TOKENS = frozenset({"nan", "none", "<na>", "nat"})


def _clean_affiliation_value(value: Any) -> str:
    """Normalize affiliation fields; treat pandas NaN and literal 'nan' as missing."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if text.casefold() in _MISSING_AFFILIATION_TOKENS:
        return ""
    return text


def _row_text(row: Any, field: str) -> str:
    """Read a string field from a DataFrame row without tripping on pandas NA."""
    if isinstance(row, dict):
        value = row.get(field)
    else:
        value = row.get(field) if hasattr(row, "get") else getattr(row, field, None)
    return _clean_affiliation_value(value)


API_BASE_URL = "https://api.emissions.dev/v1/travel/emissions"
API_CONNECT_TIMEOUT_SECONDS = 15
API_READ_TIMEOUT_SECONDS = 90
API_MAX_RETRIES = 5
API_RETRY_BACKOFF_SECONDS = 3.0
API_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
DEFAULT_DESTINATION_COUNTRY = "NZ"
DEFAULT_DESTINATION_LOCATION = "AKL"
DEFAULT_KEYS_PATH = Path("keys.yaml")
DEFAULT_TRAVEL_CACHE_PATH = TRAVEL_EMISSIONS_CACHE_JSON
THIRD_EMISSIONS_KEY_NAME = "third-emissions-dev"
FOURTH_EMISSIONS_KEY_NAME = "fourth-emissions-dev"
FIFTH_EMISSIONS_KEY_NAME = "fifth-emissions-dev"
# Key used when fetching only routes not yet in travel_emissions_cache.json
MISSING_ROUTES_KEY_NAME = FIFTH_EMISSIONS_KEY_NAME
DEFAULT_REVERSE_CACHE_PATH = REVERSE_GEOCODE_CACHE_JSON
DEFAULT_OUTPUT_PATH = Path("outputs/travel_emissions_summary.json")
DEFAULT_EMISSIONS_SITE_PATH = Path("js/emissions-data.js")
DEFAULT_USER_AGENT = "explore-icrs-2026/0.1"
TREE_ABSORPTION_KG_PER_YEAR = 22.0
MIN_COUNTRY_ATTENDEES_FOR_CONTEXT = 3
MIN_NATIONAL_PER_CAPITA_TONNES = 0.2
DEFAULT_NATIONAL_PER_CAPITA_PATH = NATIONAL_PER_CAPITA_JSON
NATIONAL_PER_CAPITA_INDICATOR = "EN.GHG.CO2.PC.CE.AR5"
NATIONAL_PER_CAPITA_YEAR = 2024
WORLD_BANK_NATIONAL_PER_CAPITA_URL = (
    "https://data.worldbank.org/indicator/EN.GHG.CO2.PC.CE.AR5"
)
WORLD_BANK_API_URL = "https://api.worldbank.org/v2"
ILLUSTRATIVE_LOW_PER_CAPITA_COUNTRIES = ("VU", "TZ", "CM", "FJ", "PG")
ILLUSTRATIVE_HIGH_PER_CAPITA_COUNTRIES = ("US", "AU", "CA", "SA", "AE", "QA")


def national_per_capita_source_note(year: int = NATIONAL_PER_CAPITA_YEAR) -> str:
    return (
        f"World Bank {NATIONAL_PER_CAPITA_INDICATOR}, {year}, "
        "metric tonnes CO₂e per person (excl. LULUCF)"
    )


EMISSIONS_SOURCES = [
    {
        "id": "travel",
        "label": "Return-trip travel estimates",
        "url": "https://emissions.dev/docs/api/travel",
        "note": "emissions.dev Travel API (economy flights; Auckland shared car)",
    },
    {
        "id": "national_per_capita",
        "label": "National per-capita CO₂",
        "url": WORLD_BANK_NATIONAL_PER_CAPITA_URL,
        "note": national_per_capita_source_note(),
    },
    {
        "id": "tree_uptake",
        "label": "Tree CO₂ uptake (~22 kg/yr)",
        "url": "https://www.epa.gov/energy/greenhouse-gases-equivalencies-calculator-calculations-and-references",
        "note": "US EPA GHG equivalencies (≈48 lb CO₂ per tree per year)",
    },
]
NZ_CAR_PASSENGERS_CENTRAL = 2
NZ_CAR_PASSENGERS_LOW = 4
NZ_CAR_PASSENGERS_HIGH = 1
FLIGHT_PREMIUM_ECONOMY_MULTIPLIER = 1.6
FLIGHT_BUSINESS_MULTIPLIER = 2.9
_CONSOLE = Console()
_query_count = 0


@dataclass(frozen=True)
class TravelLeg:
    presenter: str
    affiliation: str
    origin_country: str
    origin_location: str
    transport_mode: str
    geocode_level: str | None
    latitude: float
    longitude: float


@dataclass(frozen=True)
class TravelEstimate:
    presenter: str
    affiliation: str
    transport_mode: str
    origin_country: str
    origin_location: str
    geocode_level: str | None
    co2e_kg: float
    co2e_low_kg: float
    co2e_high_kg: float
    distance_km: float | None
    passengers: int
    return_trip: bool
    query_used: dict[str, Any]


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)


def load_site_locations(
    path: str | Path = "js/locations.js",
) -> list[dict[str, Any]]:
    """Load affiliation locations exported for the static site."""
    js_path = Path(path)
    if not js_path.exists():
        raise FileNotFoundError(f"Site locations file not found: {js_path}")
    text = js_path.read_text(encoding="utf-8")
    marker = "export const SITE_DATA = "
    start = text.find(marker)
    if start < 0:
        raise ValueError(f"Could not parse SITE_DATA from {js_path}")
    payload = json.loads(text[start + len(marker) :].rstrip().rstrip(";"))
    return payload.get("locations", [])


def _api_key() -> str | None:
    return os.environ.get("EMISSIONS_DEV_API_KEY") or os.environ.get(
        "EMISSIONS_API_KEY"
    )


def _parse_keys_yaml(path: Path) -> dict[str, str]:
    """Minimal keys.yaml reader (avoids PyYAML dependency for simple key files)."""
    payload: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        value = value.strip().strip('"').strip("'")
        if key.strip():
            payload[key.strip()] = value
    return payload


def load_api_key(
    keys_path: Path = DEFAULT_KEYS_PATH,
    *,
    key_name: str | None = None,
) -> str:
    """Load emissions.dev API key from env or keys.yaml."""
    env_key = _api_key()
    if env_key:
        return env_key

    if not keys_path.exists():
        raise ValueError(
            f"Missing API key. Set EMISSIONS_DEV_API_KEY or create {keys_path} "
            "(see https://emissions.dev/register)."
        )

    try:
        import yaml

        payload = yaml.safe_load(keys_path.read_text(encoding="utf-8")) or {}
    except ImportError:
        payload = _parse_keys_yaml(keys_path)
    if key_name:
        value = payload.get(key_name)
        if value:
            return str(value).strip()
        raise ValueError(f"No {key_name} key found in {keys_path}")

    for name in (
        "emissions-dev",
        "emissions_dev",
        "emissions.dev",
        "second-emissions-dev",
        "third-emissions-dev",
        "fourth-emissions-dev",
        "fifth-emissions-dev",
    ):
        value = payload.get(name)
        if value:
            return str(value).strip()

    raise ValueError(f"No emissions-dev key found in {keys_path}")


def api_query_count() -> int:
    return _query_count


def _route_key(origin_country: str, origin_location: str, transport_mode: str) -> str:
    return "|".join(
        [
            origin_country.strip().upper(),
            origin_location.strip().casefold(),
            transport_mode.strip().casefold(),
        ]
    )


def _cache_key(params: dict[str, Any]) -> str:
    serialized = json.dumps(params, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _country_name_to_alpha2(country_name: str) -> str | None:
    try:
        return pycountry.countries.lookup(country_name).alpha_2
    except LookupError:
        return None


def _origin_geo_from_row(row: Any) -> dict[str, str]:
    """Derive emissions.dev origin country/location from affiliation metadata."""
    affiliation = _row_text(row, "affiliation")
    hints = _extract_country_hints(affiliation)
    country_code = _row_text(row, "country_code").upper()
    if not country_code and hints:
        country_code = _country_name_to_alpha2(hints[0]) or ""
    if not country_code:
        parts = [part.strip() for part in affiliation.split(",") if part.strip()]
        if parts:
            country_code = _country_name_to_alpha2(parts[-1]) or ""

    formatted = _row_text(row, "formatted_address")
    geocode_level = str(row.get("geocode_level") or "").strip().casefold()
    if geocode_level == "country" and hints:
        location_name = hints[0]
    elif formatted:
        location_name = formatted.split(",")[0].strip()
    elif hints:
        location_name = hints[0]
    else:
        location_name = affiliation.split(",")[0].strip() if affiliation else "Unknown"

    if not country_code:
        country_code = "Unknown"
    return {"country_code": country_code, "location_name": location_name or "Unknown"}


def load_attendee_legs(
    talks_geo: pd.DataFrame,
    *,
    show_progress: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return one travel leg per presenter with a geocoded affiliation."""
    from src.sources.delegates import (
        country_to_iso2,
        delegate_org_country_for_row,
        delegate_person_key,
        load_delegates,
        normalize_person_name,
    )
    from src.registry.affiliation_registry import parse_affiliation_parts
    from src.emissions.origin_country import country_from_affiliation, resolve_origin_country
    from src.registry.person_registry import DEFAULT_REGISTRY_PATH, load_person_registry

    delegate_rows = load_delegates(refresh=False)
    registry_people = load_person_registry(DEFAULT_REGISTRY_PATH)
    registry_countries = {
        normalize_person_name(str(row["canonical_name"])): str(row.get("country") or "").strip()
        for _, row in registry_people.iterrows()
        if str(row.get("canonical_name") or "").strip()
    }
    delegate_countries = {
        normalize_person_name(str(row["full_name"])): delegate_org_country_for_row(row)[1]
        for _, row in delegate_rows.iterrows()
        if str(row.get("full_name") or "").strip()
    }
    delegate_countries_by_key = {
        delegate_person_key(str(row["full_name"])): delegate_org_country_for_row(row)[1]
        for _, row in delegate_rows.iterrows()
        if str(row.get("full_name") or "").strip()
    }

    attendees = (
        talks_geo.dropna(subset=["latitude", "longitude"])
        .sort_values(["presenter", "geocode_level"], na_position="last")
        .drop_duplicates(subset=["presenter"], keep="first")
        .copy()
    )

    rows: list[dict[str, Any]] = []
    for _, row in attendees.iterrows():
        geo = _origin_geo_from_row(row)
        origin_country, origin_location = _origin_from_attendee(
            row["affiliation"],
            geo,
            geocode_level=row.get("geocode_level"),
        )
        affiliation_text = _row_text(row, "affiliation")
        resolved = resolve_origin_country(
            affiliation=affiliation_text,
            existing=str(origin_country or ""),
            delegate_country=delegate_countries.get(
                normalize_person_name(str(row.get("presenter") or ""))
            )
            or delegate_countries_by_key.get(
                delegate_person_key(str(row.get("presenter") or ""))
            )
            or "",
        )
        if resolved:
            origin_country = resolved
        elif str(origin_country).upper() in {"", "UNKNOWN"}:
            origin_country = country_from_affiliation(affiliation_text)
        delegate_country = (
            delegate_countries.get(normalize_person_name(str(row.get("presenter") or "")))
            or delegate_countries_by_key.get(
                delegate_person_key(str(row.get("presenter") or ""))
            )
            or registry_countries.get(normalize_person_name(str(row.get("presenter") or "")))
            or ""
        )
        if delegate_country and str(origin_country).upper() in {"", "UNKNOWN"}:
            origin_country = country_to_iso2(delegate_country) or delegate_country
        country_code = _row_text(row, "country_code").upper()
        if country_code and not re.fullmatch(r"[A-Z]{2}", str(origin_country or "")):
            origin_country = country_code
        if not re.fullmatch(r"[A-Z]{2}", str(origin_country or "")):
            parts_org, parts_country = parse_affiliation_parts(affiliation_text)
            if parts_country:
                origin_country = country_to_iso2(parts_country) or country_from_affiliation(
                    affiliation_text
                )
        if _looks_like_coordinates(origin_location):
            origin_location = affiliation_text.split(",")[0].strip() or origin_location
        if (
            str(origin_country).upper() == "AU"
            and "sydney" in str(origin_location or "").casefold()
            and "university" in str(origin_location or "").casefold()
        ):
            origin_location = "Sydney"
        transport_mode = (
            "car" if origin_country == DEFAULT_DESTINATION_COUNTRY else "flight"
        )
        rows.append(
            {
                "presenter": row["presenter"],
                "affiliation": affiliation_text,
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "geocode_level": row.get("geocode_level"),
                "origin_country": origin_country,
                "origin_location": origin_location,
                "transport_mode": transport_mode,
            }
        )

    legs = pd.DataFrame(rows)
    missing = talks_geo.loc[
        ~talks_geo["presenter"].isin(legs["presenter"]), "presenter"
    ].drop_duplicates()
    return legs, pd.DataFrame({"presenter": missing})


def _looks_like_coordinates(value: str) -> bool:
    return bool(re.fullmatch(r"-?\d+\.\d+,-?\d+\.\d+", value.strip()))


def _emissions_location_key(affiliation: str) -> str:
    """Group map pins by org+delegate country so foreign-delegate anchors stay separate."""
    from src.registry.affiliation_registry import parse_affiliation_parts

    affiliation = str(affiliation or "").strip()
    if not affiliation:
        return ""
    organisation, country = parse_affiliation_parts(affiliation)
    if organisation and country:
        return f"{organisation.strip().casefold()}|{country.strip().casefold()}"
    from src.geocoding.geocode import canonical_affiliation_key

    return canonical_affiliation_key(affiliation).casefold()


def _origin_from_attendee(
    affiliation: str,
    geo: dict[str, str],
    *,
    geocode_level: str | None,
) -> tuple[str, str]:
    """Resolve emissions.dev origin country (ISO-2) and city/location label."""
    from src.geocoding.capital_coords import (
        organisation_country_mismatch,
        resolve_capital_fallback,
    )
    from src.geocoding.geocode import affiliation_base_name
    from src.sources.delegates import country_to_iso2

    affiliation_text = "" if pd.isna(affiliation) else str(affiliation)
    parts = [part.strip() for part in affiliation_text.split(",") if part.strip()]
    delegate_country = parts[-1] if len(parts) >= 2 else ""
    org_name = parts[0] if len(parts) >= 2 else affiliation_base_name(affiliation_text)

    country_code = (geo.get("country_code") or "").upper()
    if delegate_country:
        delegate_iso = country_to_iso2(delegate_country)
        if delegate_iso:
            country_code = delegate_iso

    use_capital = (
        str(geocode_level or "").strip().casefold() == "country"
        or (
            delegate_country
            and organisation_country_mismatch(org_name, delegate_country)
        )
    )
    if use_capital and delegate_country:
        fallback = resolve_capital_fallback(org_name, delegate_country)
        if fallback:
            city, _, _, _ = fallback
            return country_code or country_to_iso2(delegate_country) or "Unknown", city

    hints = _extract_country_hints(affiliation_text)
    location_name = (geo.get("location_name") or "").strip()

    if delegate_country:
        country_name = delegate_country
    elif hints:
        country_name = hints[-1]
    else:
        country_name = None

    if not country_code and country_name:
        country_code = _country_name_to_alpha2(country_name) or ""

    if not country_code:
        country_code = "Unknown"

    if location_name and not _looks_like_coordinates(location_name):
        origin_location = location_name.split(",")[0].strip() or location_name
    elif org_name and delegate_country:
        origin_location = org_name
    elif country_name:
        origin_location = country_name
    else:
        origin_location = location_name or "Unknown"

    return country_code, origin_location


def _query_travel_emissions(
    params: dict[str, Any],
    *,
    api_key: str,
    cache: dict[str, Any],
    cache_path: Path,
    pause_seconds: float,
) -> dict[str, Any]:
    global _query_count
    key = _cache_key(params)
    if key in cache:
        return cache[key]

    last_error: Exception | None = None
    route_label = f"{params.get('origin_country')} · {params.get('origin_location')}"
    for attempt in range(API_MAX_RETRIES):
        try:
            response = requests.get(
                API_BASE_URL,
                params=params,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=(API_CONNECT_TIMEOUT_SECONDS, API_READ_TIMEOUT_SECONDS),
            )
            if response.status_code in API_RETRY_STATUS_CODES:
                raise requests.HTTPError(
                    f"{response.status_code} from emissions.dev",
                    response=response,
                )
            response.raise_for_status()
            payload = response.json()
            cache[key] = payload
            _save_json(cache_path, cache)
            _query_count += 1
            time.sleep(pause_seconds)
            return payload
        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        ) as exc:
            last_error = exc
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status not in API_RETRY_STATUS_CODES:
                raise
            last_error = exc

        if attempt < API_MAX_RETRIES - 1:
            wait = API_RETRY_BACKOFF_SECONDS * (2**attempt)
            _CONSOLE.print(
                f"[yellow]API error for {route_label} "
                f"(attempt {attempt + 1}/{API_MAX_RETRIES}): {last_error}. "
                f"Retrying in {wait:.0f}s…[/]"
            )
            time.sleep(wait)

    assert last_error is not None
    raise last_error


def _extract_co2e(payload: dict[str, Any]) -> tuple[float, float | None]:
    attrs = payload["data"]["attributes"]
    emissions = attrs["emissions"]
    distance = attrs.get("route", {}).get("total_distance_km")
    return float(emissions["co2e"]), None if distance is None else float(distance)


def _bounds_from_central(
    central_co2e: float, transport_mode: str
) -> tuple[float, float]:
    if transport_mode == "car":
        low = central_co2e * (NZ_CAR_PASSENGERS_CENTRAL / NZ_CAR_PASSENGERS_LOW)
        high = central_co2e * (NZ_CAR_PASSENGERS_CENTRAL / NZ_CAR_PASSENGERS_HIGH)
        return low, high
    return central_co2e, central_co2e * FLIGHT_BUSINESS_MULTIPLIER


def _central_params_for_route(
    origin_country: str,
    origin_location: str,
    transport_mode: str,
) -> dict[str, Any]:
    base = {
        "origin_country": origin_country,
        "origin_location": origin_location,
        "destination_country": DEFAULT_DESTINATION_COUNTRY,
        "destination_location": "Auckland",
        "return_trip": "true",
        "passengers": 1,
    }
    if transport_mode == "car":
        return {
            **base,
            "transport_mode": "car",
            "passengers": NZ_CAR_PASSENGERS_CENTRAL,
            "vehicle_type": "average",
        }
    return {
        **base,
        "transport_mode": "flight",
        "cabin_class": "economy",
    }


def estimate_unique_routes(
    legs: pd.DataFrame,
    *,
    api_key: str,
    travel_cache_path: Path = DEFAULT_TRAVEL_CACHE_PATH,
    pause_seconds: float = 0.2,
    show_progress: bool = True,
    limit: int | None = None,
    missing_only: bool = True,
) -> pd.DataFrame:
    """Query emissions.dev once per unique origin route (efficient for API quotas)."""
    cache = _load_json(travel_cache_path)
    routes = (
        legs.drop_duplicates(
            subset=["origin_country", "origin_location", "transport_mode"]
        )
        .sort_values(["transport_mode", "origin_country", "origin_location"])
        .reset_index(drop=True)
    )
    routes = routes[
        routes["origin_country"].astype(str).str.fullmatch(r"[A-Z]{2}", na=False)
    ].reset_index(drop=True)
    if missing_only:
        pending: list[pd.Series] = []
        for route in routes.itertuples(index=False):
            params = _central_params_for_route(
                str(route.origin_country),
                str(route.origin_location),
                str(route.transport_mode),
            )
            if _cache_key(params) not in cache:
                pending.append(pd.Series(route._asdict()))
        routes = (
            pd.DataFrame(pending)
            if pending
            else pd.DataFrame(columns=routes.columns)
        )
    if limit is not None:
        routes = routes.head(limit)

    rows: list[dict[str, Any]] = []
    if show_progress:
        from rich.progress import (
            BarColumn,
            MofNCompleteColumn,
            Progress,
            SpinnerColumn,
            TextColumn,
            TimeElapsedColumn,
            TimeRemainingColumn,
        )

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=_CONSOLE,
        )
    else:
        progress = None

    # iterator: Any = routes.itertuples(index=False)
    if progress is not None:
        with progress:
            task_id = progress.add_task("Querying emissions.dev", total=len(routes))
            for route in routes.itertuples(index=False):
                progress.update(
                    task_id,
                    description=f"[cyan]{route.origin_country} · {str(route.origin_location)[:28]}[/]",
                )
                rows.append(
                    _estimate_route_row(
                        route._asdict(),
                        api_key=api_key,
                        cache=cache,
                        cache_path=travel_cache_path,
                        pause_seconds=pause_seconds,
                    )
                )
                progress.advance(task_id)
    else:
        for route in routes.itertuples(index=False):
            rows.append(
                _estimate_route_row(
                    route._asdict(),
                    api_key=api_key,
                    cache=cache,
                    cache_path=travel_cache_path,
                    pause_seconds=pause_seconds,
                )
            )

    return pd.DataFrame(rows)


def routes_from_travel_cache(
    legs: pd.DataFrame,
    *,
    travel_cache_path: Path = DEFAULT_TRAVEL_CACHE_PATH,
) -> pd.DataFrame:
    """Build route emissions rows using only entries already in the travel cache."""
    cache = _load_json(travel_cache_path)
    routes = (
        legs.drop_duplicates(
            subset=["origin_country", "origin_location", "transport_mode"]
        )
        .sort_values(["transport_mode", "origin_country", "origin_location"])
        .reset_index(drop=True)
    )
    rows: list[dict[str, Any]] = []
    for route in routes.itertuples(index=False):
        params = _central_params_for_route(
            str(route.origin_country),
            str(route.origin_location),
            str(route.transport_mode),
        )
        payload = cache.get(_cache_key(params))
        if not payload:
            continue
        central_co2e, distance_km = _extract_co2e(payload)
        low_co2e, high_co2e = _bounds_from_central(
            central_co2e, str(route.transport_mode)
        )
        rows.append(
            {
                "route_key": _route_key(
                    str(route.origin_country),
                    str(route.origin_location),
                    str(route.transport_mode),
                ),
                "origin_country": route.origin_country,
                "origin_location": route.origin_location,
                "transport_mode": route.transport_mode,
                "co2e_kg": central_co2e,
                "co2e_low_kg": low_co2e,
                "co2e_high_kg": high_co2e,
                "distance_km": distance_km,
                "query_used": params,
            }
        )
    return pd.DataFrame(rows)


def routes_missing_from_cache(
    legs: pd.DataFrame,
    *,
    travel_cache_path: Path = DEFAULT_TRAVEL_CACHE_PATH,
) -> int:
    """Count unique routes in legs that are not yet in the travel emissions cache."""
    cache = _load_json(travel_cache_path)
    routes = legs.drop_duplicates(
        subset=["origin_country", "origin_location", "transport_mode"]
    )
    missing = 0
    for route in routes.itertuples(index=False):
        params = _central_params_for_route(
            str(route.origin_country),
            str(route.origin_location),
            str(route.transport_mode),
        )
        if _cache_key(params) not in cache:
            missing += 1
    return missing


def _estimate_route_row(
    route: dict[str, Any],
    *,
    api_key: str,
    cache: dict[str, Any],
    cache_path: Path,
    pause_seconds: float,
) -> dict[str, Any]:
    params = _central_params_for_route(
        str(route["origin_country"]),
        str(route["origin_location"]),
        str(route["transport_mode"]),
    )
    payload = _query_travel_emissions(
        params,
        api_key=api_key,
        cache=cache,
        cache_path=cache_path,
        pause_seconds=pause_seconds,
    )
    central_co2e, distance_km = _extract_co2e(payload)
    low_co2e, high_co2e = _bounds_from_central(
        central_co2e, str(route["transport_mode"])
    )
    return {
        "route_key": _route_key(
            str(route["origin_country"]),
            str(route["origin_location"]),
            str(route["transport_mode"]),
        ),
        "origin_country": route["origin_country"],
        "origin_location": route["origin_location"],
        "transport_mode": route["transport_mode"],
        "co2e_kg": central_co2e,
        "co2e_low_kg": low_co2e,
        "co2e_high_kg": high_co2e,
        "distance_km": distance_km,
        "query_used": params,
    }


def attach_route_emissions(legs: pd.DataFrame, routes: pd.DataFrame) -> pd.DataFrame:
    legs = legs.copy()
    legs["route_key"] = legs.apply(
        lambda row: _route_key(
            row["origin_country"], row["origin_location"], row["transport_mode"]
        ),
        axis=1,
    )
    merged = legs.merge(
        routes[
            [
                "route_key",
                "co2e_kg",
                "co2e_low_kg",
                "co2e_high_kg",
                "distance_km",
            ]
        ],
        on="route_key",
        how="left",
    )
    return merged


def _leg_value(leg: TravelLeg | pd.Series | dict[str, Any], key: str) -> Any:
    if isinstance(leg, dict):
        return leg[key]
    if isinstance(leg, pd.Series):
        return leg[key]
    return getattr(leg, key)


def estimate_leg_emissions(
    leg: TravelLeg | pd.Series | dict[str, Any],
    *,
    api_key: str,
    cache: dict[str, Any],
    cache_path: Path,
    nz_car_passengers: int = 2,
    nz_car_passengers_low: int = 4,
    nz_car_passengers_high: int = 1,
    flight_cabin_central: str = "economy",
    flight_cabin_high: str = "business",
    pause_seconds: float = 0.2,
) -> TravelEstimate:
    base_params = {
        "origin_country": _leg_value(leg, "origin_country"),
        "origin_location": _leg_value(leg, "origin_location"),
        "destination_country": DEFAULT_DESTINATION_COUNTRY,
        "destination_location": "Auckland",
        "return_trip": "true",
        "passengers": 1,
    }
    transport_mode = _leg_value(leg, "transport_mode")

    if transport_mode == "car":
        central_params = {
            **base_params,
            "transport_mode": "car",
            "passengers": nz_car_passengers,
            "vehicle_type": "average",
        }
        low_params = {**central_params, "passengers": nz_car_passengers_low}
        high_params = {**central_params, "passengers": nz_car_passengers_high}
    else:
        central_params = {
            **base_params,
            "transport_mode": "flight",
            "cabin_class": flight_cabin_central,
        }
        low_params = central_params
        high_params = {
            **base_params,
            "transport_mode": "flight",
            "cabin_class": flight_cabin_high,
        }

    central_payload = _query_travel_emissions(
        central_params,
        api_key=api_key,
        cache=cache,
        cache_path=cache_path,
        pause_seconds=pause_seconds,
    )
    low_payload = _query_travel_emissions(
        low_params,
        api_key=api_key,
        cache=cache,
        cache_path=cache_path,
        pause_seconds=pause_seconds,
    )
    high_payload = _query_travel_emissions(
        high_params,
        api_key=api_key,
        cache=cache,
        cache_path=cache_path,
        pause_seconds=pause_seconds,
    )

    central_co2e, distance_km = _extract_co2e(central_payload)
    low_co2e, _ = _extract_co2e(low_payload)
    high_co2e, _ = _extract_co2e(high_payload)

    if isinstance(leg, (pd.Series, dict)):
        presenter = _leg_value(leg, "presenter")
        affiliation = _leg_value(leg, "affiliation")
        geocode_level = _leg_value(leg, "geocode_level")
        origin_country = _leg_value(leg, "origin_country")
        origin_location = _leg_value(leg, "origin_location")
    else:
        presenter = leg.presenter
        affiliation = leg.affiliation
        geocode_level = leg.geocode_level
        origin_country = leg.origin_country
        origin_location = leg.origin_location

    return TravelEstimate(
        presenter=presenter,
        affiliation=affiliation,
        transport_mode=transport_mode,
        origin_country=origin_country,
        origin_location=origin_location,
        geocode_level=geocode_level,
        co2e_kg=central_co2e,
        co2e_low_kg=min(low_co2e, high_co2e),
        co2e_high_kg=max(low_co2e, high_co2e),
        distance_km=distance_km,
        passengers=nz_car_passengers if transport_mode == "car" else 1,
        return_trip=True,
        query_used=central_params,
    )


def estimate_conference_travel(
    talks_geo: pd.DataFrame,
    *,
    api_key: str,
    legs: pd.DataFrame | None = None,
    missing: pd.DataFrame | None = None,
    travel_cache_path: Path = DEFAULT_TRAVEL_CACHE_PATH,
    pause_seconds: float = 0.2,
    show_progress: bool = True,
    limit: int | None = None,
    attendee_label: str = "speakers",
    exclusion_note: str = "Speakers without geocoded affiliations are excluded from totals.",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if legs is None or missing is None:
        legs, missing = load_attendee_legs(talks_geo, show_progress=show_progress)

    routes = estimate_unique_routes(
        legs,
        api_key=api_key,
        travel_cache_path=travel_cache_path,
        pause_seconds=pause_seconds,
        show_progress=show_progress,
        limit=limit,
    )
    attendee_estimates = attach_route_emissions(legs, routes)
    attendee_estimates = attendee_estimates.dropna(subset=["co2e_kg"])

    estimate_records = []
    for _, row in attendee_estimates.iterrows():
        estimate_records.append(
            TravelEstimate(
                presenter=row["presenter"],
                affiliation=row["affiliation"],
                transport_mode=row["transport_mode"],
                origin_country=row["origin_country"],
                origin_location=row["origin_location"],
                geocode_level=row.get("geocode_level"),
                co2e_kg=float(row["co2e_kg"]),
                co2e_low_kg=float(row["co2e_low_kg"]),
                co2e_high_kg=float(row["co2e_high_kg"]),
                distance_km=None
                if pd.isna(row.get("distance_km"))
                else float(row["distance_km"]),
                passengers=NZ_CAR_PASSENGERS_CENTRAL
                if row["transport_mode"] == "car"
                else 1,
                return_trip=True,
                query_used={},
            )
        )

    estimate_df = pd.DataFrame([estimate.__dict__ for estimate in estimate_records])
    summary = summarize_travel_emissions(
        estimate_df,
        missing_count=len(missing),
        total_presenters=talks_geo["presenter"].nunique(),
        unique_routes=len(routes),
        api_queries=api_query_count(),
        attendee_label=attendee_label,
        exclusion_note=exclusion_note,
    )
    summary["routes"] = routes.to_dict(orient="records")
    return estimate_df, summary


def _load_national_per_capita(
    path: Path = DEFAULT_NATIONAL_PER_CAPITA_PATH,
) -> dict[str, Any]:
    if not path.exists():
        return {"meta": {}, "countries": {}}
    return _load_json(path)


def fetch_world_bank_national_per_capita(
    *,
    year: int = NATIONAL_PER_CAPITA_YEAR,
    country_codes: list[str] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Fetch national per-capita CO₂ from the World Bank API."""
    indicator = NATIONAL_PER_CAPITA_INDICATOR
    values_by_code: dict[str, float] = {}
    page = 1
    while True:
        response = requests.get(
            f"{WORLD_BANK_API_URL}/country/all/indicator/{indicator}",
            params={
                "format": "json",
                "per_page": 20000,
                "date": str(year),
                "page": page,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list) or len(payload) < 2:
            break
        meta, rows = payload[0], payload[1]
        for row in rows:
            code = str(row.get("country", {}).get("id", "")).strip()
            value = row.get("value")
            if not code or value is None:
                continue
            values_by_code[code] = float(value)

        total_pages = int(meta.get("pages", 1))
        if page >= total_pages:
            break
        page += 1

    requested = country_codes
    if requested is None and DEFAULT_NATIONAL_PER_CAPITA_PATH.exists():
        existing = _load_national_per_capita()
        requested = sorted(existing.get("countries", {}).keys())

    if requested:
        missing = [code for code in requested if code not in values_by_code]
        for code in missing:
            response = requests.get(
                f"{WORLD_BANK_API_URL}/country/{code}/indicator/{indicator}",
                params={"format": "json", "mrv": 1},
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or len(payload) < 2:
                continue
            for row in payload[1]:
                value = row.get("value")
                if value is None:
                    continue
                values_by_code[code] = float(value)
                break

    countries: dict[str, dict[str, float]] = {}
    for code, tonnes in sorted(values_by_code.items()):
        if requested and code not in requested:
            continue
        countries[code] = {
            "tonnes_co2e_per_capita": round(tonnes, 3),
            "kg_co2e_per_capita": round(tonnes * 1000, 1),
        }

    return {
        "countries": countries,
        "meta": {
            "indicator": indicator,
            "source_label": f"World Bank national CO₂ per capita ({year})",
            "source_url": WORLD_BANK_NATIONAL_PER_CAPITA_URL,
            "unit": "metric tonnes CO2e per capita (excl. LULUCF)",
            "year": year,
        },
    }


def save_national_per_capita(
    data: dict[str, Any],
    path: Path = DEFAULT_NATIONAL_PER_CAPITA_PATH,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
    )
    return path


def _estimates_from_by_country(
    by_country: list[dict[str, Any]],
    *,
    fallback_per_attendee_kg: float | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(by_country):
        code = str(row.get("origin_country", "")).strip()
        if not code:
            continue
        attendee_count = row.get("attendee_count")
        co2e_kg = row.get("co2e_kg")
        co2e_per_attendee_kg = row.get("co2e_per_attendee_kg")
        if (
            attendee_count is None
            and co2e_kg is not None
            and co2e_per_attendee_kg is not None
        ):
            attendee_count = max(1, round(float(co2e_kg) / float(co2e_per_attendee_kg)))
        if attendee_count is None and co2e_kg is not None and fallback_per_attendee_kg:
            attendee_count = max(
                1, round(float(co2e_kg) / float(fallback_per_attendee_kg))
            )
        if not attendee_count:
            continue
        if co2e_per_attendee_kg is None and co2e_kg is not None:
            co2e_per_attendee_kg = float(co2e_kg) / int(attendee_count)
        if co2e_per_attendee_kg is None:
            continue
        for subindex in range(int(attendee_count)):
            rows.append(
                {
                    "presenter": f"{code}-{index}-{subindex}",
                    "origin_country": code,
                    "co2e_kg": float(co2e_per_attendee_kg),
                }
            )
    return pd.DataFrame(rows)


def refresh_emissions_site_national_context(
    site_path: str | Path = DEFAULT_EMISSIONS_SITE_PATH,
) -> Path:
    """Recompute national per-capita comparisons in the exported emissions tab."""
    site_path = Path(site_path)
    source = site_path.read_text(encoding="utf-8")
    prefix = "export const EMISSIONS_DATA = "
    start = source.index(prefix) + len(prefix)
    end = source.rindex(";\n")
    payload = json.loads(source[start:end])

    for pool_name in ("speakers", "all_delegates"):
        pool = payload.get(pool_name)
        if not pool:
            continue
        headline = pool.get("meta", {}).get("headline", {})
        total_co2e_kg = float(headline.get("co2e_kg", 0))
        existing_context = pool.get("meta", {}).get("context", {})
        fallback_per_attendee = existing_context.get("per_attendee_kg")
        estimates = _estimates_from_by_country(
            pool.get("by_country", []),
            fallback_per_attendee_kg=fallback_per_attendee,
        )
        if estimates.empty:
            continue
        context = _build_emissions_context(
            estimates,
            total_co2e_kg,
        )
        attendee_total = int(headline.get("attendees_estimated") or len(estimates) or 1)
        context["per_attendee_kg"] = round(total_co2e_kg / max(attendee_total, 1), 1)
        conf_avg_kg = context["per_attendee_kg"]
        if context.get("conference_vs_lowest_national"):
            lowest_tonnes = context["conference_vs_lowest_national"][
                "national_tonnes_per_capita"
            ]
            lowest_kg = lowest_tonnes * 1000
            context["conference_vs_lowest_national"]["conference_per_attendee_kg"] = (
                conf_avg_kg
            )
            context["conference_vs_lowest_national"]["ratio_vs_national_annual"] = (
                round(conf_avg_kg / lowest_kg, 2)
            )
        if context.get("conference_vs_highest_national"):
            highest_tonnes = context["conference_vs_highest_national"][
                "national_tonnes_per_capita"
            ]
            highest_kg = highest_tonnes * 1000
            context["conference_vs_highest_national"]["conference_per_attendee_kg"] = (
                conf_avg_kg
            )
            context["conference_vs_highest_national"]["ratio_vs_national_annual"] = (
                round(conf_avg_kg / highest_kg, 2)
            )
        if context.get("illustrative_per_capita"):
            for row in context["illustrative_per_capita"]:
                row["conference_per_attendee_kg"] = conf_avg_kg
                row["ratio_vs_national_annual"] = round(
                    conf_avg_kg / float(row["national_kg_per_capita"]), 2
                )
        pool.setdefault("meta", {})["context"] = context

    js_body = (
        "/** Generated by estimate_travel_emissions.py – do not edit by hand. */\n"
        f"export const EMISSIONS_DATA = {json.dumps(payload, ensure_ascii=False, indent=2)};\n"
    )
    site_path.write_text(js_body, encoding="utf-8")
    return site_path


def _build_emissions_context(
    estimates: pd.DataFrame, total_co2e_kg: float
) -> dict[str, Any]:
    """Comparisons for the emissions tab (trees, national per-capita multipliers)."""
    national_data = _load_national_per_capita()
    national_by_iso2 = national_data.get("countries", {})
    national_meta = national_data.get("meta", {})

    by_country = (
        estimates.groupby("origin_country")
        .agg(
            attendee_count=("presenter", "count"),
            co2e_per_attendee_kg=("co2e_kg", "mean"),
        )
        .reset_index()
    )
    by_country = by_country[
        by_country["attendee_count"] >= MIN_COUNTRY_ATTENDEES_FOR_CONTEXT
    ].copy()
    by_country["national_tonnes_per_capita"] = by_country["origin_country"].map(
        lambda code: national_by_iso2.get(str(code), {}).get("tonnes_co2e_per_capita")
    )
    by_country = by_country.dropna(subset=["national_tonnes_per_capita"])
    by_country = by_country[
        by_country["national_tonnes_per_capita"] >= MIN_NATIONAL_PER_CAPITA_TONNES
    ]
    by_country["national_kg_per_capita"] = (
        by_country["national_tonnes_per_capita"] * 1000
    )
    by_country["ratio_vs_national_annual"] = (
        by_country["co2e_per_attendee_kg"] / by_country["national_kg_per_capita"]
    )

    context: dict[str, Any] = {
        "tree_years": round(total_co2e_kg / TREE_ABSORPTION_KG_PER_YEAR),
        "tree_kg_per_year_assumption": TREE_ABSORPTION_KG_PER_YEAR,
        "per_attendee_kg": round(total_co2e_kg / max(len(estimates), 1), 1),
        "country_avg_min_attendees": MIN_COUNTRY_ATTENDEES_FOR_CONTEXT,
        "national_per_capita_year": national_meta.get("year", NATIONAL_PER_CAPITA_YEAR),
        "sources": EMISSIONS_SOURCES,
    }

    if not by_country.empty:
        lowest_pc = by_country.sort_values("national_tonnes_per_capita").iloc[0]
        highest_pc = by_country.sort_values("national_tonnes_per_capita").iloc[-1]
        context["lowest_national_per_capita"] = _country_per_capita_comparison_row(
            lowest_pc
        )
        context["highest_national_per_capita"] = _country_per_capita_comparison_row(
            highest_pc
        )

        conf_avg_kg = context["per_attendee_kg"]
        if national_meta:
            for key, row in (
                ("conference_vs_lowest_national", lowest_pc),
                ("conference_vs_highest_national", highest_pc),
            ):
                context[key] = {
                    "origin_country": str(row["origin_country"]),
                    "national_tonnes_per_capita": round(
                        float(row["national_tonnes_per_capita"]), 3
                    ),
                    "conference_per_attendee_kg": conf_avg_kg,
                    "ratio_vs_national_annual": round(
                        conf_avg_kg / float(row["national_kg_per_capita"]), 2
                    ),
                }

        present = set(estimates["origin_country"].astype(str))
        illustrative: list[dict[str, Any]] = []
        for iso2 in ILLUSTRATIVE_LOW_PER_CAPITA_COUNTRIES:
            if iso2 in present and iso2 in national_by_iso2:
                illustrative.append(
                    _illustrative_per_capita_row(
                        iso2,
                        national_by_iso2[iso2],
                        conf_avg_kg,
                        role="illustrative_low",
                    )
                )
                break
        for iso2 in ILLUSTRATIVE_HIGH_PER_CAPITA_COUNTRIES:
            if iso2 in present and iso2 in national_by_iso2:
                illustrative.append(
                    _illustrative_per_capita_row(
                        iso2,
                        national_by_iso2[iso2],
                        conf_avg_kg,
                        role="illustrative_high",
                    )
                )
                break
        if illustrative:
            context["illustrative_per_capita"] = illustrative

    return context


def _illustrative_per_capita_row(
    iso2: str,
    national_row: dict[str, Any],
    conference_per_attendee_kg: float,
    *,
    role: str,
) -> dict[str, Any]:
    tonnes = float(national_row["tonnes_co2e_per_capita"])
    national_kg = tonnes * 1000
    return {
        "role": role,
        "origin_country": iso2,
        "national_tonnes_per_capita": round(tonnes, 3),
        "national_kg_per_capita": round(national_kg, 1),
        "conference_per_attendee_kg": conference_per_attendee_kg,
        "ratio_vs_national_annual": round(conference_per_attendee_kg / national_kg, 2),
    }


def _country_per_capita_comparison_row(row: pd.Series) -> dict[str, Any]:
    return {
        "origin_country": str(row["origin_country"]),
        "co2e_per_attendee_kg": round(float(row["co2e_per_attendee_kg"]), 1),
        "attendee_count": int(row["attendee_count"]),
        "national_tonnes_per_capita": round(
            float(row["national_tonnes_per_capita"]), 3
        ),
        "national_kg_per_capita": round(float(row["national_kg_per_capita"]), 1),
        "ratio_vs_national_annual": round(float(row["ratio_vs_national_annual"]), 2),
    }


def summarize_travel_emissions(
    estimates: pd.DataFrame,
    *,
    missing_count: int,
    total_presenters: int,
    unique_routes: int | None = None,
    api_queries: int | None = None,
    attendee_label: str = "speakers",
    exclusion_note: str = "Speakers without geocoded affiliations are excluded from totals.",
) -> dict[str, Any]:
    country_level = (
        estimates["geocode_level"].eq("country").sum()
        if "geocode_level" in estimates.columns
        else 0
    )
    by_country = (
        estimates.groupby("origin_country")
        .agg(
            co2e_kg=("co2e_kg", "sum"),
            co2e_low_kg=("co2e_low_kg", "sum"),
            co2e_high_kg=("co2e_high_kg", "sum"),
            attendee_count=("presenter", "count"),
            co2e_per_attendee_kg=("co2e_kg", "mean"),
        )
        .reset_index()
        .sort_values("co2e_kg", ascending=False)
    )
    by_country["co2e_per_attendee_kg"] = by_country["co2e_per_attendee_kg"].round(1)
    by_affiliation = (
        estimates.groupby("affiliation")[["co2e_kg", "co2e_low_kg", "co2e_high_kg"]]
        .sum()
        .reset_index()
        .sort_values("co2e_kg", ascending=False)
    )
    summary = {
        "attendees_estimated": len(estimates),
        "attendees_missing_location": int(missing_count),
        "unique_presenters": int(total_presenters),
        "unique_routes_queried": int(unique_routes or 0),
        "api_queries_used": int(api_queries or 0),
        "destination": {
            "country": DEFAULT_DESTINATION_COUNTRY,
            "location": DEFAULT_DESTINATION_LOCATION,
        },
        "assumptions": {
            "non_nz_transport": "return economy flight to Auckland",
            "nz_transport": "return shared car trip for attendees in New Zealand",
            "flight_business_multiplier": FLIGHT_BUSINESS_MULTIPLIER,
            "return_trip": True,
            "api_strategy": "one emissions.dev query per unique origin route",
        },
        "co2e_kg": float(estimates["co2e_kg"].sum()),
        "co2e_low_kg": float(estimates["co2e_low_kg"].sum()),
        "co2e_high_kg": float(estimates["co2e_high_kg"].sum()),
        "co2e_tonnes": float(estimates["co2e_kg"].sum() / 1_000),
        "by_transport_mode": estimates.groupby("transport_mode")[
            ["co2e_kg", "co2e_low_kg", "co2e_high_kg"]
        ]
        .sum()
        .reset_index()
        .to_dict(orient="records"),
        "by_country": by_country.to_dict(orient="records"),
        "by_affiliation": by_affiliation.head(50).to_dict(orient="records"),
        "context": _build_emissions_context(
            estimates, float(estimates["co2e_kg"].sum())
        ),
        "uncertainty": {
            "missing_location_presenters": int(missing_count),
            "country_level_origins": int(country_level),
            "flight_business_multiplier": FLIGHT_BUSINESS_MULTIPLIER,
            "notes": [exclusion_note] if exclusion_note else [],
        },
        "attendee_label": attendee_label,
    }
    return summary


def print_travel_summary(summary: dict[str, Any]) -> None:
    table = Table(title="ICRS 2026 travel emissions estimate")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Attendees estimated", f"{summary['attendees_estimated']:,}")
    table.add_row("Missing location", f"{summary['attendees_missing_location']:,}")
    table.add_row(
        "Central total",
        f"{summary['co2e_kg']:,.0f} kg CO2e ({summary['co2e_tonnes']:,.1f} t)",
    )
    table.add_row(
        "Assumption",
        f"Economy flights (business class ~{FLIGHT_BUSINESS_MULTIPLIER}×, premium economy ~{FLIGHT_PREMIUM_ECONOMY_MULTIPLIER}×)",
    )
    _CONSOLE.print(table)

    mode_table = Table(title="By transport mode")
    mode_table.add_column("Mode")
    mode_table.add_column("Central kg", justify="right")
    mode_table.add_column("Low kg", justify="right")
    mode_table.add_column("High kg", justify="right")
    for row in summary["by_transport_mode"]:
        mode_table.add_row(
            str(row["transport_mode"]),
            f"{row['co2e_kg']:,.0f}",
            f"{row['co2e_low_kg']:,.0f}",
            f"{row['co2e_high_kg']:,.0f}",
        )
    _CONSOLE.print(mode_table)


def _build_emissions_locations(
    estimates: pd.DataFrame,
    legs: pd.DataFrame,
) -> list[dict[str, Any]]:
    from src.geocoding.geocode import (
        _institution_rule,
        _load_json,
        _lookup_override,
        affiliation_base_name,
        affiliation_display_name,
        canonical_affiliation_key,
    )

    overrides = _load_json(GEOCODE_OVERRIDES_JSON)
    country_centroids = {
        (-24.776109, 134.755),  # Australia
        (54.702354, -3.276575),  # United Kingdom
        (-41.500083, 172.834408),  # New Zealand
    }

    def _best_lat_lon(key: str, group: pd.DataFrame) -> tuple[float, float] | None:
        override = _lookup_override(key, overrides)
        if override is not None and override.get("latitude") is not None:
            return float(override["latitude"]), float(override["longitude"])

        valid = group.dropna(subset=["latitude", "longitude"])
        if valid.empty:
            return None

        lat_rounded = valid["latitude"].astype(float).round(6)
        lon_rounded = valid["longitude"].astype(float).round(6)
        pairs: dict[tuple[float, float], int] = {}
        for lat, lon in zip(lat_rounded, lon_rounded, strict=False):
            coord = (float(lat), float(lon))
            if coord in country_centroids:
                continue
            pairs[coord] = pairs.get(coord, 0) + 1
        if pairs:
            return max(pairs.items(), key=lambda item: item[1])[0]
        return float(valid["latitude"].iloc[0]), float(valid["longitude"].iloc[0])

    leg_cols = legs[
        ["presenter", "affiliation", "latitude", "longitude"]
    ].drop_duplicates(subset=["presenter"])
    merged = estimates.merge(leg_cols, on=["presenter", "affiliation"], how="left")
    clean_affiliations = merged["affiliation"].map(_clean_affiliation_value)
    merged = merged.assign(
        _affiliation_key=clean_affiliations.map(_emissions_location_key)
    )

    display_name: dict[str, str] = {}
    for affiliation in clean_affiliations.drop_duplicates():
        if pd.isna(affiliation):
            continue
        affiliation_text = str(affiliation)
        key = _emissions_location_key(affiliation_text)
        rule = _institution_rule(affiliation_text)
        preferred = (
            affiliation_display_name(affiliation_text)
            or (rule.get("canonical") if rule else None)
            or affiliation_base_name(affiliation_text)
            or affiliation_text
        )
        existing = display_name.get(key)
        if not existing or len(preferred) > len(existing):
            display_name[key] = preferred

    rows: list[dict[str, Any]] = []
    key_to_id: dict[str, str] = {}
    from src.registry.affiliation_registry import _make_affiliation, parse_affiliation_parts

    for index, (key, group) in enumerate(
        sorted(merged.groupby("_affiliation_key", sort=True)),
        start=1,
    ):
        coords = _best_lat_lon(key, group)
        if coords is None:
            continue
        lat_value, lon_value = coords
        co2e_kg = float(group["co2e_kg"].sum())
        co2e_low_kg = float(group["co2e_low_kg"].sum())
        co2e_high_kg = float(group["co2e_high_kg"].sum())
        attendees = len(group)
        loc_id = f"emis-loc-{index:04d}"
        key_to_id[key] = loc_id
        affiliation_label = display_name.get(key, key)
        for raw_affiliation in group["affiliation"].dropna().unique():
            organisation, country = parse_affiliation_parts(str(raw_affiliation))
            if organisation and country:
                affiliation_label = _make_affiliation(affiliation_label, country)
                break

        rows.append(
            {
                "id": loc_id,
                "affiliation": affiliation_label,
                "lat": lat_value,
                "lon": lon_value,
                "speaker_count": attendees,
                "travel_attendees": attendees,
                "co2e_kg": round(co2e_kg, 1),
                "co2e_low_kg": round(co2e_low_kg, 1),
                "co2e_high_kg": round(co2e_high_kg, 1),
                "co2e_per_speaker_kg": round(co2e_kg / max(attendees, 1), 1),
                "distance_km": None,
            }
        )
    return rows, key_to_id


def _stable_attendee_id(name: str, location_id: str) -> str:
    key = f"{name.strip().casefold()}|{location_id}"
    hash_value = 2166136261
    for char in key.encode():
        hash_value ^= char
        hash_value = (hash_value * 16777619) & 0xFFFFFFFF
    return f"offset-{hash_value:08x}"


def _build_emissions_attendees(
    estimates: pd.DataFrame,
    legs: pd.DataFrame,
    key_to_id: dict[str, str],
    *,
    country_to_cluster: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    from src.geocoding.geocode import (
        affiliation_display_name,
        canonical_affiliation_key,
    )

    leg_cols = legs[
        ["presenter", "affiliation", "latitude", "longitude"]
    ].drop_duplicates(subset=["presenter"])
    estimate_cols = ["presenter", "affiliation", "co2e_kg"]
    if "origin_country" in estimates.columns:
        estimate_cols.append("origin_country")
    merged = estimates[estimate_cols].merge(
        leg_cols, on=["presenter", "affiliation"], how="left"
    )

    attendees: list[dict[str, Any]] = []
    seen: set[str] = set()
    from src.sources.delegates import canonical_person_name, delegate_person_key

    columns = list(merged.columns)
    presenter_idx = columns.index("presenter")
    affiliation_idx = columns.index("affiliation")
    co2e_idx = columns.index("co2e_kg")
    origin_country_idx = (
        columns.index("origin_country") if "origin_country" in columns else None
    )

    for row in merged.itertuples(index=False, name=None):
        name = "" if pd.isna(row[presenter_idx]) else str(row[presenter_idx]).strip()
        affiliation = _clean_affiliation_value(row[affiliation_idx])
        if not name:
            continue
        key = _emissions_location_key(affiliation)
        location_id = key_to_id.get(key)
        if not location_id:
            continue
        display_name = canonical_person_name(name)
        dedupe_key = f"{delegate_person_key(name)}|{location_id}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        origin_country = ""
        if origin_country_idx is not None and pd.notna(row[origin_country_idx]):
            origin_country = str(row[origin_country_idx]).strip().upper()
        cluster_id = (
            country_to_cluster.get(origin_country, "") if origin_country else ""
        )
        attendees.append(
            {
                "id": _stable_attendee_id(display_name, location_id),
                "name": display_name,
                "affiliation": affiliation_display_name(affiliation) or affiliation,
                "location_id": location_id,
                "co2e_kg": round(float(row[co2e_idx]), 1),
                "origin_country": origin_country,
                "country_cluster_id": cluster_id,
            }
        )
    attendees.sort(key=lambda item: item["name"].casefold())
    return attendees


def _build_pool_payload(
    estimates: pd.DataFrame,
    summary: dict[str, Any],
    legs: pd.DataFrame,
    *,
    country_centroids: dict[str, tuple[float, float]] | None = None,
) -> dict[str, Any]:
    from src.geography.country_clusters import (
        build_country_clusters,
        country_counts_from_estimates,
    )

    if not summary.get("context"):
        summary = {
            **summary,
            "context": _build_emissions_context(estimates, float(summary["co2e_kg"])),
        }
    location_rows, key_to_id = _build_emissions_locations(estimates, legs)
    country_counts = country_counts_from_estimates(estimates)
    centroids = country_centroids or {}
    clusters, country_to_cluster = build_country_clusters(country_counts, centroids)
    attendee_rows = _build_emissions_attendees(
        estimates,
        legs,
        key_to_id,
        country_to_cluster=country_to_cluster,
    )
    rankings = sorted(location_rows, key=lambda row: row["co2e_kg"], reverse=True)
    return {
        "meta": {
            "headline": {
                "co2e_kg": round(summary["co2e_kg"], 1),
                "co2e_low_kg": round(summary["co2e_low_kg"], 1),
                "co2e_high_kg": round(summary["co2e_high_kg"], 1),
                "co2e_tonnes": round(summary["co2e_tonnes"], 2),
                "attendees_estimated": summary["attendees_estimated"],
                "attendees_missing_location": summary["attendees_missing_location"],
                "attendee_label": summary.get("attendee_label", "speakers"),
                "unique_routes_queried": summary.get("unique_routes_queried", 0),
                "api_queries_used": summary.get("api_queries_used", 0),
            },
            "assumptions": summary.get("assumptions", {}),
            "uncertainty": summary.get("uncertainty", {}),
            "by_transport_mode": summary.get("by_transport_mode", []),
            "context": summary.get("context", {}),
        },
        "locations": location_rows,
        "attendees": attendee_rows,
        "rankings": rankings[:30],
        "by_country": summary.get("by_country", [])[:30],
        "country_clusters": clusters,
        "country_to_cluster": country_to_cluster,
    }


def export_emissions_site_data(
    estimates: pd.DataFrame,
    summary: dict[str, Any],
    site_locations: list[dict[str, Any]],
    *,
    legs: pd.DataFrame | None = None,
    all_delegates: tuple[pd.DataFrame, dict[str, Any], pd.DataFrame] | None = None,
    delegate_meta: dict[str, Any] | None = None,
    save_path: str | Path = DEFAULT_EMISSIONS_SITE_PATH,
    show_progress: bool = False,
) -> Path:
    """Export travel emissions for the static emissions tab."""
    from datetime import UTC, datetime

    from src.site.export_progress import run_with_progress

    if legs is None:
        legs = estimates[["presenter", "affiliation"]].copy()
        legs["latitude"] = pd.NA
        legs["longitude"] = pd.NA

    speakers_pool = _build_pool_payload(estimates, summary, legs)
    from src.site.map_exclusions import filter_emissions_pool

    speakers_pool = filter_emissions_pool(speakers_pool)
    payload: dict[str, Any] = {
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "delegate_meta": delegate_meta or {},
            "offset_choropleth": {
                "enabled": True,
                "boundaries_path": COUNTRY_BOUNDARIES_REL,
                "min_cluster_size": 3,
                "color_low": "#d95f02",
                "color_high": "#2d8a4e",
            },
        },
        "speakers": speakers_pool,
    }
    if all_delegates is not None:
        delegate_estimates, delegate_summary, delegate_legs = all_delegates
        payload["all_delegates"] = filter_emissions_pool(
            _build_pool_payload(
                delegate_estimates,
                delegate_summary,
                delegate_legs,
            )
        )
    else:
        payload["all_delegates"] = speakers_pool

    from src.emissions.emissions_site_enrichment import enrich_emissions_payload

    payload = enrich_emissions_payload(payload)

    output_path = Path(save_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def _write_export() -> None:
        js_body = (
            "/** Generated by estimate_travel_emissions.py – do not edit by hand. */\n"
            f"export const EMISSIONS_DATA = {json.dumps(payload, ensure_ascii=False, indent=2)};\n"
        )
        output_path.write_text(js_body, encoding="utf-8")

    if show_progress:
        run_with_progress("Serialising and writing emissions-data.js", _write_export)
    else:
        _write_export()
    return output_path


def export_emissions_site_data_legacy(
    estimates: pd.DataFrame,
    summary: dict[str, Any],
    site_locations: list[dict[str, Any]],
    *,
    save_path: str | Path = DEFAULT_EMISSIONS_SITE_PATH,
) -> Path:
    """Export travel emissions for the static emissions tab."""
    from datetime import UTC, datetime

    affiliation_stats = (
        estimates.groupby("affiliation")
        .agg(
            co2e_kg=("co2e_kg", "sum"),
            co2e_low_kg=("co2e_low_kg", "sum"),
            co2e_high_kg=("co2e_high_kg", "sum"),
            attendee_count=("presenter", "count"),
        )
        .reset_index()
    )
    affiliation_map = {
        row["affiliation"]: row for _, row in affiliation_stats.iterrows()
    }

    location_rows: list[dict[str, Any]] = []
    for location in site_locations:
        stats = affiliation_map.get(location["affiliation"])
        co2e_kg = round(float(stats["co2e_kg"]), 1) if stats is not None else 0.0
        co2e_low_kg = (
            round(float(stats["co2e_low_kg"]), 1) if stats is not None else 0.0
        )
        co2e_high_kg = (
            round(float(stats["co2e_high_kg"]), 1) if stats is not None else 0.0
        )
        attendees = int(stats["attendee_count"]) if stats is not None else 0
        location_rows.append(
            {
                "id": location["id"],
                "affiliation": location["affiliation"],
                "lat": location["lat"],
                "lon": location["lon"],
                "speaker_count": location["speaker_count"],
                "travel_attendees": attendees,
                "co2e_kg": co2e_kg,
                "co2e_low_kg": co2e_low_kg,
                "co2e_high_kg": co2e_high_kg,
                "co2e_per_speaker_kg": round(co2e_kg / max(attendees, 1), 1),
                "distance_km": location.get("distance_km"),
            }
        )

    rankings = sorted(location_rows, key=lambda row: row["co2e_kg"], reverse=True)
    by_country = summary.get("by_country", [])

    payload = {
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "headline": {
                "co2e_kg": round(summary["co2e_kg"], 1),
                "co2e_low_kg": round(summary["co2e_low_kg"], 1),
                "co2e_high_kg": round(summary["co2e_high_kg"], 1),
                "co2e_tonnes": round(summary["co2e_tonnes"], 2),
                "attendees_estimated": summary["attendees_estimated"],
                "attendees_missing_location": summary["attendees_missing_location"],
                "unique_routes_queried": summary.get("unique_routes_queried", 0),
                "api_queries_used": summary.get("api_queries_used", 0),
            },
            "assumptions": summary.get("assumptions", {}),
            "uncertainty": summary.get("uncertainty", {}),
            "by_transport_mode": summary.get("by_transport_mode", []),
            "context": summary.get("context", {}),
        },
        "locations": location_rows,
        "rankings": rankings[:30],
        "by_country": by_country[:30],
    }

    output_path = Path(save_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    js_body = (
        "/** Generated by estimate_travel_emissions.py – do not edit by hand. */\n"
        f"export const EMISSIONS_DATA = {json.dumps(payload, ensure_ascii=False, indent=2)};\n"
    )
    output_path.write_text(js_body, encoding="utf-8")
    return output_path


def load_geocoded_talks() -> pd.DataFrame:
    from src.registry.registry_export import build_map_talks

    return build_map_talks()
