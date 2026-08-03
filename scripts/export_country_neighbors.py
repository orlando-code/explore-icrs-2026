#!/usr/bin/env python3
"""Export land-border adjacency for delegate countries (ISO-3166 alpha-2)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import geopandas as gpd
from shapely.geometry import shape

from src.origin_country import iso3_from_iso2

DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "country_neighbors.json"
GEOBOUNDARIES_API = "https://www.geoboundaries.org/api/current/gbOpen/{iso3}/ADM0/"
TOUCH_BUFFER_M = 750

# Maritime / narrow-strait links missing from simplified polygons.
NEIGHBOR_OVERRIDES: dict[str, list[str]] = {
    "AE": ["OM", "QA", "SA"],
    "BH": ["QA", "SA"],
    "GI": ["ES"],
    "HK": ["CN"],
    "KW": ["IQ", "SA"],
    "MC": ["FR"],
    "MO": ["CN"],
    "OM": ["AE", "SA", "YE"],
    "PS": ["EG", "IL", "JO"],
    "QA": ["SA"],
    "RE": ["MG", "YT"],
    "SG": ["MY"],
    "SM": ["IT"],
    "VA": ["IT"],
    "YT": ["MG", "RE"],
}


def _country_codes() -> list[str]:
    centroids_path = PROJECT_ROOT / "data" / "country_boundaries_centroids.json"
    continents_path = PROJECT_ROOT / "data" / "country_continents.json"
    codes: set[str] = set()
    if centroids_path.exists():
        codes.update(json.loads(centroids_path.read_text(encoding="utf-8")).keys())
    if continents_path.exists():
        codes.update(json.loads(continents_path.read_text(encoding="utf-8")).keys())
    return sorted(code.upper() for code in codes if len(str(code)) == 2)


def _fetch_geometry(iso2: str) -> dict | None:
    iso3 = iso3_from_iso2(iso2)
    if not iso3:
        return None
    try:
        with urlopen(GEOBOUNDARIES_API.format(iso3=iso3), timeout=45) as response:
            metadata = json.load(response)
        with urlopen(metadata["gjDownloadURL"], timeout=90) as response:
            payload = json.load(response)
    except Exception:
        return None
    geometry = payload.get("features", [{}])[0].get("geometry")
    if not geometry:
        return None
    return {"iso_a2": iso2, "geometry": geometry}


def export_country_neighbors(output_path: Path = DEFAULT_OUTPUT) -> Path:
    rows = []
    for index, iso2 in enumerate(_country_codes()):
        row = _fetch_geometry(iso2)
        if row:
            rows.append(row)
            print(f"Fetched {iso2}")
        else:
            print(f"Skipped {iso2}")
        if index % 8 == 7:
            time.sleep(0.15)

    if not rows:
        raise RuntimeError("No geometries fetched for neighbor export")

    frame = gpd.GeoDataFrame(
        [{"iso_a2": row["iso_a2"], "geometry": shape(row["geometry"])} for row in rows],
        crs="EPSG:4326",
    )
    projected = frame.to_crs(frame.estimate_utm_crs())
    projected["geometry"] = projected.geometry.buffer(TOUCH_BUFFER_M)

    neighbors: dict[str, list[str]] = {iso2: [] for iso2 in projected["iso_a2"]}
    indexed = projected.set_index("iso_a2")
    for iso2, row in indexed.iterrows():
        hits = indexed[indexed.geometry.intersects(row.geometry) & (indexed.index != iso2)].index
        neighbors[str(iso2).upper()] = sorted(str(code).upper() for code in hits)

    for code, extra in NEIGHBOR_OVERRIDES.items():
        code = code.upper()
        merged = set(neighbors.get(code, [])) | {neighbor.upper() for neighbor in extra}
        neighbors[code] = sorted(merged)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(neighbors, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {len(neighbors)} countries to {output_path}")
    return output_path


def main() -> None:
    export_country_neighbors()


if __name__ == "__main__":
    main()
