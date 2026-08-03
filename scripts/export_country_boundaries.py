#!/usr/bin/env python3
"""Export OSM-aligned country polygons (geoBoundaries) for delegate countries only."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import geopandas as gpd

from src.origin_country import iso3_from_iso2

DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "country_boundaries.geojson"
GEOBOUNDARIES_API = "https://www.geoboundaries.org/api/current/gbOpen/{iso3}/ADM0/"
INWARD_BUFFER_KM = 18.0


def _shrink_geometry(geom, distance_km: float = INWARD_BUFFER_KM):
    if geom is None or geom.is_empty:
        return geom
    series = gpd.GeoSeries([geom], crs="EPSG:4326")
    utm = series.estimate_utm_crs()
    if utm is None:
        return geom
    projected = series.to_crs(utm)
    for factor in (1.0, 0.65, 0.4, 0.2):
        shrunk = projected.buffer(-distance_km * 1000 * factor)
        candidate = shrunk.iloc[0]
        if candidate is not None and not candidate.is_empty and candidate.area > 0:
            return gpd.GeoSeries([candidate], crs=utm).to_crs("EPSG:4326").iloc[0]
    return geom


def _roster_country_codes() -> set[str]:
    delegates_path = PROJECT_ROOT / "data" / "delegates.json"
    if not delegates_path.exists():
        return set()
    payload = json.loads(delegates_path.read_text(encoding="utf-8"))
    codes: set[str] = set()
    for row in payload.get("delegates") or []:
        code = str(row.get("country_code") or "").strip().upper()
        if len(code) == 2:
            codes.add(code)
    return codes


def _emissions_country_codes(emissions_path: Path) -> set[str]:
    import re

    source = emissions_path.read_text(encoding="utf-8")
    match = re.search(r"export const EMISSIONS_DATA = (\{.*\});\s*$", source, re.S)
    if not match:
        return set()
    payload = json.loads(match.group(1))
    codes: set[str] = set()
    for pool_name in ("speakers", "all_delegates"):
        pool = payload.get(pool_name) or {}
        for attendee in pool.get("attendees") or []:
            code = str(attendee.get("origin_country") or "").strip().upper()
            if code:
                codes.add(code)
        for location in pool.get("locations") or []:
            for key in ("origin_country",):
                code = str(location.get(key) or "").strip().upper()
                if code:
                    codes.add(code)
        for mapping in (pool.get("country_to_cluster") or {}).values():
            pass
        for cluster in pool.get("country_clusters") or []:
            for code in cluster.get("countries") or []:
                if code:
                    codes.add(str(code).strip().upper())
    return {code for code in codes if len(code) == 2}


def _fetch_country_feature(iso2: str) -> dict | None:
    iso3 = iso3_from_iso2(iso2)
    if not iso3:
        return None
    try:
        with urlopen(GEOBOUNDARIES_API.format(iso3=iso3), timeout=60) as response:
            metadata = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return None
    boundary_url = metadata.get("gjDownloadURL")
    if not boundary_url:
        return None
    try:
        with urlopen(boundary_url, timeout=120) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return None
    features = payload.get("features") or []
    if not features:
        return None
    geometry = features[0].get("geometry")
    if not geometry:
        return None
    return {
        "type": "Feature",
        "properties": {
            "iso_a2": iso2,
            "name": metadata.get("boundaryName") or iso2,
        },
        "geometry": geometry,
    }


def export_country_boundaries(
    output_path: Path = DEFAULT_OUTPUT,
    *,
    emissions_path: Path | None = None,
    country_codes: set[str] | None = None,
) -> Path:
    emissions_path = emissions_path or (PROJECT_ROOT / "js" / "emissions-data.js")
    codes = country_codes or (_emissions_country_codes(emissions_path) | _roster_country_codes())
    if not codes:
        raise ValueError("No country codes found to export")

    features: list[dict] = []
    for index, iso2 in enumerate(sorted(codes)):
        feature = _fetch_country_feature(iso2)
        if feature:
            features.append(feature)
            print(f"Fetched {iso2}")
        else:
            print(f"Skipped {iso2} (geoBoundaries unavailable)")
        if index % 5 == 4:
            time.sleep(0.2)

    if not features:
        raise RuntimeError("No country boundaries could be downloaded")

    frame = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    centroids = {
        row.iso_a2: [
            round(float(row.geometry.centroid.y), 4),
            round(float(row.geometry.centroid.x), 4),
        ]
        for row in frame.itertuples()
    }
    frame["geometry"] = frame.geometry.simplify(
        tolerance=0.01,
        preserve_topology=True,
    )
    frame["geometry"] = frame.geometry.map(_shrink_geometry)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_file(output_path, driver="GeoJSON")
    centroids_path = output_path.with_name("country_boundaries_centroids.json")
    centroids_path.write_text(
        json.dumps(centroids, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"Wrote {len(features)} countries to {output_path} ({size_mb:.1f} MB)")
    return output_path


def main() -> None:
    export_country_boundaries()


if __name__ == "__main__":
    main()
