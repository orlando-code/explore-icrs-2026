#!/usr/bin/env python3
"""Build data/geography/country_capitals.json and us_state_capitals.json.

Sources (in precedence order for each ISO2):
  1. Curated seed overrides (conference territories and capitals with known coords)
  2. world-cities.csv rows whose name matches the dr5hn capital city
  3. geopy Nominatim geocode of \"{capital}, {country}\" (offline cache in data/cache/)

Re-run when adding delegate countries or updating capital coordinates.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_paths import GEOGRAPHY
from src.sources.delegates import country_to_iso2

DR5HN_COUNTRIES_URL = (
    "https://raw.githubusercontent.com/dr5hn/countries-states-cities-database/"
    "master/json/countries.json"
)

# Curated coordinates keyed by ISO2. These override automated matches when present.
SEED_COUNTRY_CAPITALS: dict[str, dict[str, object]] = {
    "AS": {"city": "Pago Pago", "lat": -14.2756, "lon": -170.7020, "country": "American Samoa"},
    "AG": {"city": "St. John's", "lat": 17.1274, "lon": -61.8468, "country": "Antigua and Barbuda"},
    "AU": {"city": "Canberra", "lat": -35.2809, "lon": 149.1300, "country": "Australia"},
    "BS": {"city": "Nassau", "lat": 25.0443, "lon": -77.3504, "country": "Bahamas"},
    "BB": {"city": "Bridgetown", "lat": 13.0975, "lon": -59.6167, "country": "Barbados"},
    "BE": {"city": "Brussels", "lat": 50.8503, "lon": 4.3517, "country": "Belgium"},
    "BZ": {"city": "Belmopan", "lat": 17.2510, "lon": -88.7590, "country": "Belize"},
    "BM": {"city": "Hamilton", "lat": 32.2949, "lon": -64.7830, "country": "Bermuda"},
    "BO": {"city": "Sucre", "lat": -19.0196, "lon": -65.2620, "country": "Bolivia, Plurinational State of"},
    "BR": {"city": "Brasília", "lat": -15.7939, "lon": -47.8828, "country": "Brazil"},
    "CA": {"city": "Ottawa", "lat": 45.4215, "lon": -75.6972, "country": "Canada"},
    "CN": {"city": "Beijing", "lat": 39.9042, "lon": 116.4074, "country": "China"},
    "CO": {"city": "Bogotá", "lat": 4.7110, "lon": -74.0721, "country": "Colombia"},
    "CK": {"city": "Avarua", "lat": -21.2070, "lon": -159.7716, "country": "Cook Islands"},
    "CR": {"city": "San José", "lat": 9.9281, "lon": -84.0907, "country": "Costa Rica"},
    "CU": {"city": "Havana", "lat": 23.1136, "lon": -82.3666, "country": "Cuba"},
    "CW": {"city": "Willemstad", "lat": 12.1224, "lon": -68.8824, "country": "Curaçao"},
    "DK": {"city": "Copenhagen", "lat": 55.6761, "lon": 12.5683, "country": "Denmark"},
    "DO": {"city": "Santo Domingo", "lat": 18.4861, "lon": -69.9312, "country": "Dominican Republic"},
    "EC": {"city": "Quito", "lat": -0.1807, "lon": -78.4678, "country": "Ecuador"},
    "EG": {"city": "Cairo", "lat": 30.0444, "lon": 31.2357, "country": "Egypt"},
    "SV": {"city": "San Salvador", "lat": 13.6929, "lon": -89.2182, "country": "El Salvador"},
    "FJ": {"city": "Suva", "lat": -18.1416, "lon": 178.4419, "country": "Fiji"},
    "FI": {"city": "Helsinki", "lat": 60.1699, "lon": 24.9384, "country": "Finland"},
    "FR": {"city": "Paris", "lat": 48.8566, "lon": 2.3522, "country": "France"},
    "PF": {"city": "Papeete", "lat": -17.5516, "lon": -149.5585, "country": "French Polynesia"},
    "DE": {"city": "Berlin", "lat": 52.5200, "lon": 13.4050, "country": "Germany"},
    "GH": {"city": "Accra", "lat": 5.6037, "lon": -0.1870, "country": "Ghana"},
    "GU": {"city": "Hagåtña", "lat": 13.4760, "lon": 144.7502, "country": "Guam"},
    "HN": {"city": "Tegucigalpa", "lat": 14.0723, "lon": -87.1921, "country": "Honduras"},
    "HK": {"city": "Hong Kong", "lat": 22.3193, "lon": 114.1694, "country": "Hong Kong"},
    "IN": {"city": "New Delhi", "lat": 28.6139, "lon": 77.2090, "country": "India"},
    "ID": {"city": "Jakarta", "lat": -6.2088, "lon": 106.8456, "country": "Indonesia"},
    "IR": {"city": "Tehran", "lat": 35.6892, "lon": 51.3890, "country": "Iran"},
    "IL": {"city": "Jerusalem", "lat": 31.7683, "lon": 35.2137, "country": "Israel"},
    "IT": {"city": "Rome", "lat": 41.9028, "lon": 12.4964, "country": "Italy"},
    "JM": {"city": "Kingston", "lat": 18.0179, "lon": -76.8099, "country": "Jamaica"},
    "JP": {"city": "Tokyo", "lat": 35.6762, "lon": 139.6503, "country": "Japan"},
    "KE": {"city": "Nairobi", "lat": -1.2921, "lon": 36.8219, "country": "Kenya"},
    "MG": {"city": "Antananarivo", "lat": -18.8792, "lon": 47.5079, "country": "Madagascar"},
    "MY": {"city": "Kuala Lumpur", "lat": 3.1390, "lon": 101.6869, "country": "Malaysia"},
    "MV": {"city": "Malé", "lat": 4.1755, "lon": 73.5093, "country": "Maldives"},
    "MH": {"city": "Majuro", "lat": 7.0897, "lon": 171.3803, "country": "Marshall Islands"},
    "MU": {"city": "Port Louis", "lat": -20.1609, "lon": 57.5012, "country": "Mauritius"},
    "YT": {"city": "Mamoudzou", "lat": -12.7806, "lon": 45.2278, "country": "Mayotte"},
    "MX": {"city": "Mexico City", "lat": 19.4326, "lon": -99.1332, "country": "Mexico"},
    "FM": {"city": "Palikir", "lat": 6.9147, "lon": 158.1610, "country": "Micronesia, Federated States of"},
    "MC": {"city": "Monaco", "lat": 43.7384, "lon": 7.4246, "country": "Monaco"},
    "MZ": {"city": "Maputo", "lat": -25.9692, "lon": 32.5732, "country": "Mozambique"},
    "NL": {"city": "Amsterdam", "lat": 52.3676, "lon": 4.9041, "country": "Netherlands"},
    "NC": {"city": "Nouméa", "lat": -22.2558, "lon": 166.4505, "country": "New Caledonia"},
    "NZ": {"city": "Wellington", "lat": -41.2865, "lon": 174.7762, "country": "New Zealand"},
    "NG": {"city": "Abuja", "lat": 9.0765, "lon": 7.3986, "country": "Nigeria"},
    "MP": {"city": "Saipan", "lat": 15.1778, "lon": 145.7508, "country": "Northern Mariana Islands"},
    "OM": {"city": "Muscat", "lat": 23.5880, "lon": 58.3829, "country": "Oman"},
    "PW": {"city": "Ngerulmud", "lat": 7.5004, "lon": 134.6242, "country": "Palau"},
    "PA": {"city": "Panama City", "lat": 8.9824, "lon": -79.5199, "country": "Panama"},
    "PG": {"city": "Port Moresby", "lat": -9.4438, "lon": 147.1803, "country": "Papua New Guinea"},
    "PH": {"city": "Manila", "lat": 14.5995, "lon": 120.9842, "country": "Philippines"},
    "PL": {"city": "Warsaw", "lat": 52.2297, "lon": 21.0122, "country": "Poland"},
    "PT": {"city": "Lisbon", "lat": 38.7223, "lon": -9.1393, "country": "Portugal"},
    "PR": {"city": "San Juan", "lat": 18.4655, "lon": -66.1057, "country": "Puerto Rico"},
    "QA": {"city": "Doha", "lat": 25.2854, "lon": 51.5310, "country": "Qatar"},
    "RE": {"city": "Saint-Denis", "lat": -20.8823, "lon": 55.4504, "country": "Réunion"},
    "WS": {"city": "Apia", "lat": -13.8333, "lon": -171.7667, "country": "Samoa"},
    "SA": {"city": "Riyadh", "lat": 24.7136, "lon": 46.6753, "country": "Saudi Arabia"},
    "SC": {"city": "Victoria", "lat": -4.6191, "lon": 55.4513, "country": "Seychelles"},
    "SG": {"city": "Singapore", "lat": 1.3521, "lon": 103.8198, "country": "Singapore"},
    "SX": {"city": "Philipsburg", "lat": 18.0237, "lon": -63.0458, "country": "Sint Maarten"},
    "KR": {"city": "Seoul", "lat": 37.5665, "lon": 126.9780, "country": "South Korea"},
    "ES": {"city": "Madrid", "lat": 40.4168, "lon": -3.7038, "country": "Spain"},
    "LK": {"city": "Colombo", "lat": 6.9271, "lon": 79.8612, "country": "Sri Lanka"},
    "SE": {"city": "Stockholm", "lat": 59.3293, "lon": 18.0686, "country": "Sweden"},
    "CH": {"city": "Bern", "lat": 46.9480, "lon": 7.4474, "country": "Switzerland"},
    "TW": {"city": "Taipei", "lat": 25.0330, "lon": 121.5654, "country": "Taiwan"},
    "TZ": {"city": "Dodoma", "lat": -6.1630, "lon": 35.7516, "country": "Tanzania, United Republic of"},
    "TH": {"city": "Bangkok", "lat": 13.7563, "lon": 100.5018, "country": "Thailand"},
    "TK": {"city": "Atafu", "lat": -8.5540, "lon": -172.5156, "country": "Tokelau"},
    "TO": {"city": "Nuku'alofa", "lat": -21.1393, "lon": -175.2049, "country": "Tonga"},
    "TV": {"city": "Funafuti", "lat": -8.5200, "lon": 179.1981, "country": "Tuvalu"},
    "AE": {"city": "Abu Dhabi", "lat": 24.4539, "lon": 54.3773, "country": "United Arab Emirates"},
    "GB": {"city": "London", "lat": 51.5074, "lon": -0.1278, "country": "United Kingdom"},
    "US": {"city": "Washington", "lat": 38.9072, "lon": -77.0369, "country": "United States"},
    "VI": {"city": "Charlotte Amalie", "lat": 18.3419, "lon": -64.9307, "country": "United States Virgin Islands"},
    "VU": {"city": "Port Vila", "lat": -17.7333, "lon": 168.3273, "country": "Vanuatu"},
    "VE": {"city": "Caracas", "lat": 10.4806, "lon": -66.9036, "country": "Venezuela, Bolivarian Republic of"},
}

US_STATE_CAPITALS: dict[str, dict[str, object]] = {
    "Alabama": {"city": "Montgomery", "lat": 32.3668, "lon": -86.3000},
    "Alaska": {"city": "Juneau", "lat": 58.3019, "lon": -134.4197},
    "Arizona": {"city": "Phoenix", "lat": 33.4484, "lon": -112.0740},
    "Arkansas": {"city": "Little Rock", "lat": 34.7465, "lon": -92.2896},
    "California": {"city": "Sacramento", "lat": 38.5816, "lon": -121.4944},
    "Colorado": {"city": "Denver", "lat": 39.7392, "lon": -104.9903},
    "Connecticut": {"city": "Hartford", "lat": 41.7658, "lon": -72.6734},
    "Delaware": {"city": "Dover", "lat": 39.1582, "lon": -75.5244},
    "Florida": {"city": "Tallahassee", "lat": 30.4383, "lon": -84.2807},
    "Georgia": {"city": "Atlanta", "lat": 33.7490, "lon": -84.3880},
    "Hawaii": {"city": "Honolulu", "lat": 21.3069, "lon": -157.8583},
    "Idaho": {"city": "Boise", "lat": 43.6150, "lon": -116.2023},
    "Illinois": {"city": "Springfield", "lat": 39.7817, "lon": -89.6501},
    "Indiana": {"city": "Indianapolis", "lat": 39.7684, "lon": -86.1581},
    "Iowa": {"city": "Des Moines", "lat": 41.5868, "lon": -93.6250},
    "Kansas": {"city": "Topeka", "lat": 39.0473, "lon": -95.6752},
    "Kentucky": {"city": "Frankfort", "lat": 38.2009, "lon": -84.8733},
    "Louisiana": {"city": "Baton Rouge", "lat": 30.4515, "lon": -91.1871},
    "Maine": {"city": "Augusta", "lat": 44.3106, "lon": -69.7795},
    "Maryland": {"city": "Annapolis", "lat": 38.9784, "lon": -76.4922},
    "Massachusetts": {"city": "Boston", "lat": 42.3601, "lon": -71.0589},
    "Michigan": {"city": "Lansing", "lat": 42.7325, "lon": -84.5555},
    "Minnesota": {"city": "Saint Paul", "lat": 44.9537, "lon": -93.0900},
    "Mississippi": {"city": "Jackson", "lat": 32.2988, "lon": -90.1848},
    "Missouri": {"city": "Jefferson City", "lat": 38.5767, "lon": -92.1735},
    "Montana": {"city": "Helena", "lat": 46.5891, "lon": -112.0391},
    "Nebraska": {"city": "Lincoln", "lat": 40.8136, "lon": -96.7026},
    "Nevada": {"city": "Carson City", "lat": 39.1638, "lon": -119.7674},
    "New Hampshire": {"city": "Concord", "lat": 43.2081, "lon": -71.5376},
    "New Jersey": {"city": "Trenton", "lat": 40.2171, "lon": -74.7429},
    "New Mexico": {"city": "Santa Fe", "lat": 35.6870, "lon": -105.9378},
    "New York": {"city": "Albany", "lat": 42.6526, "lon": -73.7562},
    "North Carolina": {"city": "Raleigh", "lat": 35.7796, "lon": -78.6382},
    "North Dakota": {"city": "Bismarck", "lat": 46.8083, "lon": -100.7837},
    "Ohio": {"city": "Columbus", "lat": 39.9612, "lon": -82.9988},
    "Oklahoma": {"city": "Oklahoma City", "lat": 35.4676, "lon": -97.5164},
    "Oregon": {"city": "Salem", "lat": 44.9429, "lon": -123.0351},
    "Pennsylvania": {"city": "Harrisburg", "lat": 40.2732, "lon": -76.8867},
    "Rhode Island": {"city": "Providence", "lat": 41.8240, "lon": -71.4128},
    "South Carolina": {"city": "Columbia", "lat": 34.0007, "lon": -81.0348},
    "South Dakota": {"city": "Pierre", "lat": 44.3683, "lon": -100.3510},
    "Tennessee": {"city": "Nashville", "lat": 36.1627, "lon": -86.7816},
    "Texas": {"city": "Austin", "lat": 30.2672, "lon": -97.7431},
    "Utah": {"city": "Salt Lake City", "lat": 40.7608, "lon": -111.8910},
    "Vermont": {"city": "Montpelier", "lat": 44.2601, "lon": -72.5754},
    "Virginia": {"city": "Richmond", "lat": 37.5407, "lon": -77.4360},
    "Washington": {"city": "Olympia", "lat": 47.0379, "lon": -122.9007},
    "West Virginia": {"city": "Charleston", "lat": 38.3498, "lon": -81.6326},
    "Wisconsin": {"city": "Madison", "lat": 43.0731, "lon": -89.4012},
    "Wyoming": {"city": "Cheyenne", "lat": 41.1400, "lon": -104.8202},
    "District of Columbia": {"city": "Washington", "lat": 38.9072, "lon": -77.0369},
    "Puerto Rico": {"city": "San Juan", "lat": 18.4655, "lon": -66.1057},
    "Guam": {"city": "Hagåtña", "lat": 13.4760, "lon": 144.7502},
    "American Samoa": {"city": "Pago Pago", "lat": -14.2756, "lon": -170.7020},
    "Northern Mariana Islands": {"city": "Saipan", "lat": 15.1778, "lon": 145.7508},
    "United States Virgin Islands": {
        "city": "Charlotte Amalie",
        "lat": 18.3419,
        "lon": -64.9307,
    },
}

US_STATE_ALIASES = {
    "hawai'i": "Hawaii",
    "hawaii": "Hawaii",
    "hawaiʻi": "Hawaii",
    "washington dc": "District of Columbia",
    "washington d.c.": "District of Columbia",
    "dc": "District of Columbia",
}


def _geocode_capital(city: str, country: str, cache: dict[str, dict[str, float]]) -> dict[str, float] | None:
    key = f"{city}|{country}".casefold()
    if key in cache:
        return cache[key]
    from geopy.geocoders import Nominatim

    geocoder = Nominatim(user_agent="explore-icrs-2026-capital-build/1.0")
    query = f"{city}, {country}"
    location = geocoder.geocode(query, timeout=20)
    time.sleep(1.1)
    if location is None:
        return None
    payload = {"lat": float(location.latitude), "lon": float(location.longitude)}
    cache[key] = payload
    return payload


def build_country_capitals(*, use_geopy: bool = True) -> dict[str, dict[str, object]]:
    countries = requests.get(DR5HN_COUNTRIES_URL, timeout=60).json()

    cache_path = PROJECT_ROOT / "data/cache/capital_geocode_cache.json"
    cache: dict[str, dict[str, float]] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))

    built: dict[str, dict[str, object]] = {
        iso: dict(record) for iso, record in SEED_COUNTRY_CAPITALS.items()
    }
    unresolved: list[str] = []

    for row in countries:
        iso = str(row.get("iso2") or "").strip().upper()
        if not iso or iso in built:
            continue

        capital = str(row.get("capital") or "").strip()
        country_name = str(row.get("name") or "").strip()
        if not capital:
            continue

        if use_geopy:
            try:
                coords = _geocode_capital(capital, country_name, cache)
            except Exception as exc:  # noqa: BLE001 - geocoder/network errors should not abort build
                print(f"  geopy failed for {iso} ({country_name}): {exc}")
                coords = None
            if coords is not None:
                built[iso] = {
                    "city": capital,
                    "lat": coords["lat"],
                    "lon": coords["lon"],
                    "country": country_name,
                    "source": "nominatim",
                }
                continue

        lat = row.get("latitude")
        lon = row.get("longitude")
        if capital and lat not in (None, "") and lon not in (None, ""):
            built[iso] = {
                "city": capital,
                "lat": float(lat),
                "lon": float(lon),
                "country": country_name,
                "source": "dr5hn-country-centroid",
            }
            continue

        unresolved.append(f"{iso} ({country_name}): {capital}")

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if unresolved:
        print("Unresolved capitals (add to SEED_COUNTRY_CAPITALS or re-run with geopy):")
        for line in unresolved:
            print(" ", line)

    return built


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-geopy",
        action="store_true",
        help="Only write curated seed capitals (skip Nominatim for remaining ISO codes).",
    )
    args = parser.parse_args()

    countries = build_country_capitals(use_geopy=not args.no_geopy)
    country_payload = {
        "meta": {
            "schema_version": 1,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "description": "ISO 3166-1 alpha-2 country and territory capitals for geocode fallback.",
            "sources": [
                "scripts/pipeline/build_capital_coords_data.py SEED_COUNTRY_CAPITALS",
                "dr5hn/countries-states-cities-database",
                "Nominatim when available (cached in data/cache/capital_geocode_cache.json)",
                "dr5hn country latitude/longitude as centroid fallback",
            ],
            "entry_count": len(countries),
        },
        "countries": dict(sorted(countries.items())),
    }
    state_payload = {
        "meta": {
            "schema_version": 1,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "description": "US state and territory capitals for delegate-country United States.",
            "entry_count": len(US_STATE_CAPITALS),
        },
        "states": dict(sorted(US_STATE_CAPITALS.items())),
        "aliases": dict(sorted(US_STATE_ALIASES.items())),
    }

    country_path = GEOGRAPHY / "country_capitals.json"
    state_path = GEOGRAPHY / "us_state_capitals.json"
    country_path.write_text(json.dumps(country_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    state_path.write_text(json.dumps(state_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {country_path} ({len(countries)} countries)")
    print(f"Wrote {state_path} ({len(US_STATE_CAPITALS)} states/territories)")

    from src.sources.delegates import load_delegates

    missing_delegate = []
    for country in sorted(load_delegates()["country"].astype(str).str.strip().unique()):
        if not country:
            continue
        iso = country_to_iso2(country)
        if iso and iso not in countries:
            missing_delegate.append((country, iso))
    if missing_delegate:
        print("Delegate countries missing from country_capitals.json:")
        for country, iso in missing_delegate:
            print(f"  {country} ({iso})")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
