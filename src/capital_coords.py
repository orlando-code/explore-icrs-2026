"""Capital-city coordinates for affiliation geocode fallbacks."""

from __future__ import annotations

import re
import unicodedata

from src.delegates import COUNTRY_ALIASES, country_to_iso2

US_STATE_CAPITALS: dict[str, tuple[str, float, float]] = {
    "Alabama": ("Montgomery", 32.3668, -86.3000),
    "Alaska": ("Juneau", 58.3019, -134.4197),
    "Arizona": ("Phoenix", 33.4484, -112.0740),
    "Arkansas": ("Little Rock", 34.7465, -92.2896),
    "California": ("Sacramento", 38.5816, -121.4944),
    "Colorado": ("Denver", 39.7392, -104.9903),
    "Connecticut": ("Hartford", 41.7658, -72.6734),
    "Delaware": ("Dover", 39.1582, -75.5244),
    "Florida": ("Tallahassee", 30.4383, -84.2807),
    "Georgia": ("Atlanta", 33.7490, -84.3880),
    "Hawaii": ("Honolulu", 21.3069, -157.8583),
    "Idaho": ("Boise", 43.6150, -116.2023),
    "Illinois": ("Springfield", 39.7817, -89.6501),
    "Indiana": ("Indianapolis", 39.7684, -86.1581),
    "Iowa": ("Des Moines", 41.5868, -93.6250),
    "Kansas": ("Topeka", 39.0473, -95.6752),
    "Kentucky": ("Frankfort", 38.2009, -84.8733),
    "Louisiana": ("Baton Rouge", 30.4515, -91.1871),
    "Maine": ("Augusta", 44.3106, -69.7795),
    "Maryland": ("Annapolis", 38.9784, -76.4922),
    "Massachusetts": ("Boston", 42.3601, -71.0589),
    "Michigan": ("Lansing", 42.7325, -84.5555),
    "Minnesota": ("Saint Paul", 44.9537, -93.0900),
    "Mississippi": ("Jackson", 32.2988, -90.1848),
    "Missouri": ("Jefferson City", 38.5767, -92.1735),
    "Montana": ("Helena", 46.5891, -112.0391),
    "Nebraska": ("Lincoln", 40.8136, -96.7026),
    "Nevada": ("Carson City", 39.1638, -119.7674),
    "New Hampshire": ("Concord", 43.2081, -71.5376),
    "New Jersey": ("Trenton", 40.2171, -74.7429),
    "New Mexico": ("Santa Fe", 35.6870, -105.9378),
    "New York": ("Albany", 42.6526, -73.7562),
    "North Carolina": ("Raleigh", 35.7796, -78.6382),
    "North Dakota": ("Bismarck", 46.8083, -100.7837),
    "Ohio": ("Columbus", 39.9612, -82.9988),
    "Oklahoma": ("Oklahoma City", 35.4676, -97.5164),
    "Oregon": ("Salem", 44.9429, -123.0351),
    "Pennsylvania": ("Harrisburg", 40.2732, -76.8867),
    "Rhode Island": ("Providence", 41.8240, -71.4128),
    "South Carolina": ("Columbia", 34.0007, -81.0348),
    "South Dakota": ("Pierre", 44.3683, -100.3510),
    "Tennessee": ("Nashville", 36.1627, -86.7816),
    "Texas": ("Austin", 30.2672, -97.7431),
    "Utah": ("Salt Lake City", 40.7608, -111.8910),
    "Vermont": ("Montpelier", 44.2601, -72.5754),
    "Virginia": ("Richmond", 37.5407, -77.4360),
    "Washington": ("Olympia", 47.0379, -122.9007),
    "West Virginia": ("Charleston", 38.3498, -81.6326),
    "Wisconsin": ("Madison", 43.0731, -89.4012),
    "Wyoming": ("Cheyenne", 41.1400, -104.8202),
    "District of Columbia": ("Washington", 38.9072, -77.0369),
    "Puerto Rico": ("San Juan", 18.4655, -66.1057),
    "Guam": ("Hagåtña", 13.4760, 144.7502),
    "American Samoa": ("Pago Pago", -14.2756, -170.7020),
    "Northern Mariana Islands": ("Saipan", 15.1778, 145.7508),
    "United States Virgin Islands": ("Charlotte Amalie", 18.3419, -64.9307),
}

COUNTRY_CAPITALS: dict[str, tuple[str, float, float]] = {
    "American Samoa": ("Pago Pago", -14.2756, -170.7020),
    "Australia": ("Canberra", -35.2809, 149.1300),
    "Barbados": ("Bridgetown", 13.0975, -59.6167),
    "Bolivia, Plurinational State of": ("Sucre", -19.0196, -65.2620),
    "Brazil": ("Brasília", -15.7939, -47.8828),
    "Canada": ("Ottawa", 45.4215, -75.6972),
    "China": ("Beijing", 39.9042, 116.4074),
    "Colombia": ("Bogotá", 4.7110, -74.0721),
    "Cook Islands": ("Avarua", -21.2070, -159.7716),
    "Cuba": ("Havana", 23.1136, -82.3666),
    "Dominican Republic": ("Santo Domingo", 18.4861, -69.9312),
    "Egypt": ("Cairo", 30.0444, 31.2357),
    "El Salvador": ("San Salvador", 13.6929, -89.2182),
    "Fiji": ("Suva", -18.1416, 178.4419),
    "Finland": ("Helsinki", 60.1699, 24.9384),
    "France": ("Paris", 48.8566, 2.3522),
    "French Polynesia": ("Papeete", -17.5516, -149.5585),
    "Germany": ("Berlin", 52.5200, 13.4050),
    "Ghana": ("Accra", 5.6037, -0.1870),
    "Guam": ("Hagåtña", 13.4760, 144.7502),
    "Honduras": ("Tegucigalpa", 14.0723, -87.1921),
    "India": ("New Delhi", 28.6139, 77.2090),
    "Indonesia": ("Jakarta", -6.2088, 106.8456),
    "Italy": ("Rome", 41.9028, 12.4964),
    "Jamaica": ("Kingston", 18.0179, -76.8099),
    "Japan": ("Tokyo", 35.6762, 139.6503),
    "Kenya": ("Nairobi", -1.2921, 36.8219),
    "Madagascar": ("Antananarivo", -18.8792, 47.5079),
    "Malaysia": ("Kuala Lumpur", 3.1390, 101.6869),
    "Maldives": ("Malé", 4.1755, 73.5093),
    "Mauritius": ("Port Louis", -20.1609, 57.5012),
    "Mayotte": ("Mamoudzou", -12.7806, 45.2278),
    "Mexico": ("Mexico City", 19.4326, -99.1332),
    "Micronesia, Federated States of": ("Palikir", 6.9147, 158.1610),
    "Netherlands": ("Amsterdam", 52.3676, 4.9041),
    "New Caledonia": ("Nouméa", -22.2558, 166.4505),
    "New Zealand": ("Wellington", -41.2865, 174.7762),
    "Northern Mariana Islands": ("Saipan", 15.1778, 145.7508),
    "Palau": ("Ngerulmud", 7.5004, 134.6242),
    "Panama": ("Panama City", 8.9824, -79.5199),
    "Papua New Guinea": ("Port Moresby", -9.4438, 147.1803),
    "Philippines": ("Manila", 14.5995, 120.9842),
    "Portugal": ("Lisbon", 38.7223, -9.1393),
    "Puerto Rico": ("San Juan", 18.4655, -66.1057),
    "Réunion": ("Saint-Denis", -20.8823, 55.4504),
    "Samoa": ("Apia", -13.8333, -171.7667),
    "Saudi Arabia": ("Riyadh", 24.7136, 46.6753),
    "Seychelles": ("Victoria", -4.6191, 55.4513),
    "Singapore": ("Singapore", 1.3521, 103.8198),
    "Sint Maarten": ("Philipsburg", 18.0237, -63.0458),
    "Spain": ("Madrid", 40.4168, -3.7038),
    "Switzerland": ("Bern", 46.9480, 7.4474),
    "Taiwan": ("Taipei", 25.0330, 121.5654),
    "Tanzania, United Republic of": ("Dodoma", -6.1630, 35.7516),
    "Thailand": ("Bangkok", 13.7563, 100.5018),
    "Tokelau": ("Atafu", -8.5540, -172.5156),
    "Tonga": ("Nuku'alofa", -21.1393, -175.2049),
    "Tuvalu": ("Funafuti", -8.5200, 179.1981),
    "United Kingdom": ("London", 51.5074, -0.1278),
    "United States": ("Washington", 38.9072, -77.0369),
    "United States Virgin Islands": ("Charlotte Amalie", 18.3419, -64.9307),
    "Vanuatu": ("Port Vila", -17.7333, 168.3273),
    "Venezuela, Bolivarian Republic of": ("Caracas", 10.4806, -66.9036),
}

_AUSTRALIAN_STATE_NAMES = frozenset(
    {
        "western australia",
        "south australia",
        "new south wales",
        "queensland",
        "victoria",
        "tasmania",
        "northern territory",
        "australian capital territory",
    }
)

_US_STATE_ALIASES = {
    "hawai'i": "Hawaii",
    "hawaii": "Hawaii",
    "hawaiʻi": "Hawaii",
    "washington dc": "District of Columbia",
    "washington d.c.": "District of Columbia",
    "dc": "District of Columbia",
}

_US_STATE_PATTERN = re.compile(
    r"\b("
    + "|".join(
        re.escape(name)
        for name in sorted(US_STATE_CAPITALS, key=len, reverse=True)
        if name not in {"District of Columbia"}
    )
    + r")\b",
    re.IGNORECASE,
)


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return text


def _canonical_country(country: str) -> str:
    cleaned = _normalize_text(country)
    if not cleaned:
        return ""
    alias = COUNTRY_ALIASES.get(cleaned.casefold())
    return alias or cleaned


def _detect_us_state(*texts: str) -> str | None:
    combined = " ".join(_normalize_text(text) for text in texts if text)
    if not combined:
        return None
    lowered = combined.casefold()
    for aus_state in _AUSTRALIAN_STATE_NAMES:
        if aus_state in lowered:
            return None
    for alias, state in _US_STATE_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            return state
    match = _US_STATE_PATTERN.search(combined)
    if not match:
        return None
    matched = match.group(1)
    for canonical in US_STATE_CAPITALS:
        if canonical.casefold() == matched.casefold():
            return canonical
    return matched


def resolve_capital_fallback(
    organisation: str,
    country: str,
) -> tuple[str, float, float, str] | None:
    """Return (city, lat, lon, query_label) for a capital fallback, or None."""
    canonical_country = _canonical_country(country)
    if canonical_country and not country_to_iso2(canonical_country):
        if canonical_country not in US_STATE_CAPITALS:
            return None

    if canonical_country == "United States":
        state = _detect_us_state(organisation, country)
        if state and state in US_STATE_CAPITALS:
            city, lat, lon = US_STATE_CAPITALS[state]
            return city, lat, lon, f"fallback:capital:{city}, {state}, United States"
        city, lat, lon = US_STATE_CAPITALS["District of Columbia"]
        return city, lat, lon, f"fallback:capital:{city}, United States"

    if canonical_country in US_STATE_CAPITALS:
        city, lat, lon = US_STATE_CAPITALS[canonical_country]
        return city, lat, lon, f"fallback:capital:{city}, {canonical_country}"

    if canonical_country in COUNTRY_CAPITALS:
        city, lat, lon = COUNTRY_CAPITALS[canonical_country]
        return city, lat, lon, f"fallback:capital:{city}, {canonical_country}"

    return None
