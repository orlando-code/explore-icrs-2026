"""Overseas territories that need a separate choropleth overlay on the demo basemap."""

from __future__ import annotations

# The MapLibre demo tiles merge many territories into their parent country polygon
# (e.g. Réunion into France). These ISO-3166 alpha-2 codes are shaded from
# country_boundaries.geojson instead.
TERRITORY_OVERLAY_ISO2 = frozenset(
    {
        "RE",
        "YT",
        "GP",
        "MQ",
        "GF",
        "PF",
        "NC",
        "BL",
        "MF",
        "PM",
        "WF",
        "TF",
        "HK",
        "MO",
        "GI",
        "MC",
        "AW",
        "CW",
        "SX",
        "BM",
        "KY",
        "VG",
        "AI",
        "MS",
        "TC",
        "GU",
        "VI",
        "PR",
        "AS",
        "MP",
        "CK",
        "NU",
        "TK",
        "FO",
        "GL",
        "AX",
        "SH",
        "FK",
        "GI",
        "JE",
        "GG",
        "IM",
    }
)


def territory_overlay_codes(active_iso2: set[str] | frozenset[str]) -> list[str]:
    return sorted(code for code in active_iso2 if code in TERRITORY_OVERLAY_ISO2)
