"""Static and interactive plotting helpers for ICRS investigation outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import h3
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from cartopy.mpl.gridliner import LATITUDE_FORMATTER, LONGITUDE_FORMATTER
from matplotlib.axes import Axes
from matplotlib.collections import PolyCollection
from matplotlib.figure import Figure

GEO = ccrs.PlateCarree()

AUCKLAND_LAT = -36.8485
AUCKLAND_LON = 174.7633
EARTH_RADIUS_KM = 6371.0


def _shortest_lon_delta(lon1: float, lon2: float) -> float:
    delta = lon2 - lon1
    return (delta + 180.0) % 360.0 - 180.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_rad = np.radians(lat1)
    lat2_rad = np.radians(lat2)
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(_shortest_lon_delta(lon1, lon2))
    a = (
        np.sin(dlat / 2) ** 2
        + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlon / 2) ** 2
    )
    return float(2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a)))


def _pacific_projection(central_meridian: float = 180) -> ccrs.Mollweide:
    return ccrs.Mollweide(central_longitude=central_meridian)


def _h3_hex_counts(
    lats: np.ndarray,
    lons: np.ndarray,
    *,
    resolution: int,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for lat, lon in zip(lats, lons):
        cell = h3.latlng_to_cell(float(lat), float(lon), resolution)
        counts[cell] = counts.get(cell, 0) + 1
    return counts


def _h3_polygons(cells: Iterable[str]) -> list[list[tuple[float, float]]]:
    polygons: list[list[tuple[float, float]]] = []
    for cell in cells:
        boundary = h3.cell_to_boundary(cell)
        polygons.append([(lon, lat) for lat, lon in boundary])
    return polygons


def _draw_world_basemap(
    ax,
    *,
    land_color: str,
    ocean_color: str,
    border_color: str,
) -> None:
    ax.set_facecolor(ocean_color)
    ax.add_feature(cfeature.OCEAN, facecolor=ocean_color, zorder=0)
    ax.add_feature(cfeature.LAND, facecolor=land_color, edgecolor="none", zorder=1)
    ax.add_feature(cfeature.COASTLINE, edgecolor=border_color, linewidth=0.25, zorder=2)
    ax.add_feature(cfeature.BORDERS, edgecolor=border_color, linewidth=0.15, zorder=2)


def _style_geo_axes(ax, *, central_meridian: float = 180) -> None:
    ax.set_global()
    gl = ax.gridlines(
        draw_labels=True,
        linewidth=0.3,
        alpha=0.35,
        color="#666666",
        linestyle="-",
        xlocs=np.arange(-180, 181, 30),
        ylocs=np.arange(-60, 61, 30),
    )
    gl.top_labels = False
    gl.right_labels = False
    gl.xformatter = LONGITUDE_FORMATTER
    gl.yformatter = LATITUDE_FORMATTER


def _prepare_map_points(
    df: pd.DataFrame,
    *,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
    affiliation_col: str = "affiliation",
) -> pd.DataFrame:
    points = df.dropna(subset=[lat_col, lon_col]).copy()
    if points.empty:
        return points

    grouped = (
        points.groupby([affiliation_col, lat_col, lon_col], dropna=True)
        .size()
        .reset_index(name="n_talks")
    )
    return grouped


def _coerce_coordinate_series(series: pd.Series) -> pd.Series:
    """Convert coordinate columns to float, dropping non-numeric values."""
    return pd.to_numeric(series, errors="coerce")


def _geocoded_points(
    df: pd.DataFrame,
    *,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
) -> pd.DataFrame:
    points = df.copy()
    points[lat_col] = _coerce_coordinate_series(points[lat_col])
    points[lon_col] = _coerce_coordinate_series(points[lon_col])
    points = points.dropna(subset=[lat_col, lon_col])
    valid = points[lat_col].between(-90, 90, inclusive="both") & points[
        lon_col
    ].between(-180, 180, inclusive="both")
    return points.loc[valid].copy()


def _add_map_footer(
    ax: Axes,
    df: pd.DataFrame,
    *,
    lat_col: str = "latitude",
) -> None:
    na_count = df[lat_col].isna().sum()
    geocoded_count = df[lat_col].notna().sum()
    ax.text(
        0.01,
        0.01,
        f"Geocoded talks: {geocoded_count:,} | Missing: {na_count:,}",
        transform=ax.transAxes,
        fontsize=9,
        va="bottom",
        ha="left",
        bbox={"facecolor": "white", "alpha": 0.8, "edgecolor": "none", "pad": 3},
    )


def plot_affiliation_map(
    df: pd.DataFrame,
    *,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
    affiliation_col: str = "affiliation",
    title: str = "ICRS 2026",
    figsize: tuple[float, float] = (12, 6),
    point_color: str = "#d95f02",
    land_color: str = "#f0f0f0",
    ocean_color: str = "#dbeafe",
    border_color: str = "#bdbdbd",
    annotate_top_n: int = 8,
    central_meridian: float = 180,
    save_path: str | None = None,
    dpi: int = 300,
) -> tuple[Figure, Axes]:
    """Plot a static world map of speaker affiliations."""
    points = _prepare_map_points(
        df,
        lat_col=lat_col,
        lon_col=lon_col,
        affiliation_col=affiliation_col,
    )

    projection = _pacific_projection(central_meridian)
    fig, ax = plt.subplots(
        figsize=figsize, dpi=dpi, subplot_kw={"projection": projection}
    )
    _draw_world_basemap(
        ax,
        land_color=land_color,
        ocean_color=ocean_color,
        border_color=border_color,
    )

    if not points.empty:
        sizes = 20 + 8 * points["n_talks"].pow(0.5)
        ax.scatter(
            points[lon_col],
            points[lat_col],
            s=sizes,
            c=point_color,
            alpha=0.75,
            edgecolors="white",
            linewidths=0.4,
            transform=GEO,
            zorder=3,
        )

        if annotate_top_n > 0:
            top = points.nlargest(annotate_top_n, "n_talks")
            for _, row in top.iterrows():
                ax.annotate(
                    f"{row[affiliation_col]} ({int(row['n_talks'])})",
                    xy=(row[lon_col], row[lat_col]),
                    xycoords=GEO._as_mpl_transform(ax),
                    xytext=(4, 4),
                    textcoords="offset points",
                    fontsize=8,
                    color="#333333",
                    zorder=4,
                )

    _style_geo_axes(ax, central_meridian=central_meridian)
    ax.set_title(title)

    na_count = df[lat_col].isna().sum()
    geocoded_count = df[lat_col].notna().sum()
    ax.text(
        0.01,
        0.01,
        f"Geocoded talks: {geocoded_count:,} | Missing: {na_count:,}",
        transform=ax.transAxes,
        fontsize=9,
        va="bottom",
        ha="left",
        bbox={"facecolor": "white", "alpha": 0.8, "edgecolor": "none", "pad": 3},
    )

    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path, dpi=dpi, bbox_inches="tight")
    return fig, ax


def plot_affiliation_hexmap(
    df: pd.DataFrame,
    *,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
    title: str = "ICRS 2026 (hex heatmap)",
    figsize: tuple[float, float] = (12, 6),
    h3_resolution: int = 3,
    cmap: str = "YlOrRd",
    land_color: str = "#f0f0f0",
    ocean_color: str = "#dbeafe",
    border_color: str = "#bdbdbd",
    mincnt: int = 1,
    central_meridian: float = 180,
    save_path: str | None = None,
    dpi: int = 300,
) -> tuple[Figure, Axes]:
    """Plot a static hexagonal heatmap of speaker locations."""
    points = _geocoded_points(df, lat_col=lat_col, lon_col=lon_col)

    projection = _pacific_projection(central_meridian)
    fig, ax = plt.subplots(
        figsize=figsize, dpi=dpi, subplot_kw={"projection": projection}
    )
    _draw_world_basemap(
        ax,
        land_color=land_color,
        ocean_color=ocean_color,
        border_color=border_color,
    )

    if not points.empty:
        counts = _h3_hex_counts(
            points[lat_col].to_numpy(),
            points[lon_col].to_numpy(),
            resolution=h3_resolution,
        )
        filtered = {cell: value for cell, value in counts.items() if value >= mincnt}
        if filtered:
            polygons = _h3_polygons(filtered.keys())
            values = np.array(list(filtered.values()))
            mesh = PolyCollection(
                polygons,
                array=values,
                cmap=cmap,
                transform=GEO,
                edgecolors="white",
                linewidths=0.15,
                alpha=0.9,
                zorder=3,
            )
            ax.add_collection(mesh)
            cbar = fig.colorbar(mesh, ax=ax, shrink=0.78, pad=0.02, fraction=0.04)
            cbar.set_label("Talks per hex")

    _style_geo_axes(ax, central_meridian=central_meridian)
    ax.set_title(title)
    _add_map_footer(ax, df, lat_col=lat_col)

    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path, dpi=dpi, bbox_inches="tight")
    return fig, ax


def plot_affiliation_map_interactive(
    df: pd.DataFrame,
    *,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
    affiliation_col: str = "affiliation",
    presenter_col: str = "presenter",
    title_col: str = "title",
    title: str = "ICRS 2026",
    save_path: str | None = "outputs/speaker_affiliation_map.html",
    central_meridian: float = 180,
):
    """Create an interactive point map with hover details."""
    import plotly.express as px

    points = _geocoded_points(df, lat_col=lat_col, lon_col=lon_col)
    if points.empty:
        raise ValueError("No geocoded talks available for interactive map.")

    plot_points = _prepare_interactive_hover_points(
        points,
        colname=affiliation_col,
    )

    hover_cols = (affiliation_col,)  # tidy
    hover_data = {col: True for col in hover_cols}
    hover_data[lat_col] = False
    hover_data[lon_col] = False

    fig = px.scatter_geo(
        plot_points,
        lat=lat_col,
        lon=lon_col,
        hover_name=presenter_col if presenter_col in plot_points.columns else None,
        hover_data=hover_data,
        opacity=0.65,
        color_discrete_sequence=["#d95f02"],
        title=title,
    )
    fig.update_geos(
        showland=True,
        landcolor="#f0f0f0",
        showocean=True,
        oceancolor="#dbeafe",
        showcountries=True,
        countrycolor="#bdbdbd",
        projection_type="natural earth",
        projection_rotation={"lon": central_meridian, "lat": 0},
    )
    fig.update_traces(marker={"size": 6, "line": {"width": 0.4, "color": "white"}})
    if hover_cols:
        hover_lines = "".join(
            f"<br>{col}=%{{customdata[{idx}]}}" for idx, col in enumerate(hover_cols)
        )
        fig.update_traces(
            hovertemplate=f"<b>%{{hovertext}}</b>{hover_lines}<extra></extra>"
        )
    fig.update_layout(
        margin={"l": 0, "r": 0, "t": 50, "b": 0},
        width=1100,
        height=600,
    )

    if save_path is not None:
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        fig.write_html(save_path)
    return fig


def _build_talk_title_index(
    df: pd.DataFrame,
    *,
    presenter_col: str = "presenter",
    title_col: str = "title",
) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, dict[str, dict[str, Any]]] = {}

    for _, row in df.iterrows():
        title = row.get(title_col)
        if pd.isna(title) or not str(title).strip():
            continue
        title_text = str(title).strip()
        presenter = row.get(presenter_col)
        presenter_text = "" if pd.isna(presenter) else str(presenter).strip()
        authors = _talk_authors(row, presenter_col=presenter_col)
        if not authors:
            continue
        for author in authors:
            author_bucket = index.setdefault(author, {})
            is_primary = author == presenter_text or (
                not presenter_text and author == authors[0]
            )
            talk_id = row.get("talk_id")
            talk_id_text = "" if pd.isna(talk_id) else str(talk_id).strip()
            existing = author_bucket.get(title_text)
            if not existing or (is_primary and not existing.get("primary")):
                entry = {"title": title_text, "primary": is_primary}
                if talk_id_text:
                    entry["talk_id"] = talk_id_text
                author_bucket[title_text] = entry

    result: dict[str, list[dict[str, Any]]] = {}
    for author, titles in sorted(index.items()):
        result[author] = sorted(
            titles.values(),
            key=lambda item: (not item["primary"], item["title"].casefold()),
        )
    return result


def _affiliation_location_records(
    df: pd.DataFrame,
    *,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
    affiliation_col: str = "affiliation",
    presenter_col: str = "presenter",
    title_col: str = "title",
    abstract_col: str = "abstract",
    auckland_lat: float = AUCKLAND_LAT,
    auckland_lon: float = AUCKLAND_LON,
) -> list[dict[str, Any]]:
    """Group geocoded talks by canonical affiliation."""
    from src.geocode import affiliation_base_name, affiliation_display_name, canonical_affiliation_key

    points = _geocoded_points(df, lat_col=lat_col, lon_col=lon_col)
    if points.empty:
        return []

    buckets: dict[str, list[pd.DataFrame]] = {}
    display_name: dict[str, str] = {}
    for _, row in points.iterrows():
        affiliation_text = (
            "" if pd.isna(row[affiliation_col]) else str(row[affiliation_col])
        )
        aff_key = canonical_affiliation_key(affiliation_text)
        lat = round(float(row[lat_col]), 4)
        lon = round(float(row[lon_col]), 4)
        bucket_key = f"{aff_key}\t{lat}\t{lon}"
        buckets.setdefault(bucket_key, []).append(row.to_frame().T)
        preferred = affiliation_display_name(affiliation_text) or affiliation_text
        existing = display_name.get(bucket_key)
        if not existing or len(preferred) > len(existing):
            display_name[bucket_key] = preferred

    records: list[dict[str, Any]] = []
    for index, (bucket_key, row_frames) in enumerate(sorted(buckets.items()), start=1):
        group = pd.concat(row_frames, ignore_index=True)
        lat = float(group[lat_col].iloc[0])
        lon = float(group[lon_col].iloc[0])
        display = display_name.get(bucket_key) or bucket_key.split("\t", 1)[0]

        from src.delegates import canonical_person_name, delegate_person_key

        speaker_details: list[dict[str, str]] = []
        speaker_by_key: dict[str, dict[str, Any]] = {}
        for presenter, speaker_group in group.groupby(presenter_col, dropna=True):
            if pd.isna(presenter):
                continue
            presenter_name = str(presenter)
            person_key = delegate_person_key(presenter_name)
            parts = [presenter_name]
            talk_titles: list[str] = []
            for _, talk in speaker_group.iterrows():
                title = talk.get(title_col)
                abstract = talk.get(abstract_col)
                if pd.notna(title) and str(title).strip():
                    title_text = str(title).strip()
                    parts.append(title_text)
                    talk_titles.append(title_text)
                if pd.notna(abstract) and str(abstract).strip():
                    parts.append(str(abstract))

            existing = speaker_by_key.get(person_key)
            if existing is None:
                speaker_by_key[person_key] = {
                    "name": canonical_person_name(presenter_name),
                    "search_text": " ".join(parts).lower(),
                    "talk_titles": talk_titles,
                    "person_key": person_key,
                }
                continue

            existing["search_text"] = f"{existing['search_text']} {' '.join(parts).lower()}".strip()
            existing["talk_titles"].extend(talk_titles)

        speaker_details = sorted(
            speaker_by_key.values(),
            key=lambda item: str(item["name"]).casefold(),
        )
        speakers = [item["name"] for item in speaker_details]

        level = group.get("geocode_level")
        geocode_level = ""
        if level is not None:
            levels = [value for value in level.dropna().unique() if str(value).strip()]
            if levels:
                geocode_level = "institute" if "institute" in levels else str(levels[0])

        affiliation_text = display
        search_parts = [affiliation_text, *speakers]
        for item in speaker_details:
            search_parts.append(item["search_text"])
        records.append(
            {
                "id": f"loc-{index:04d}",
                "affiliation": affiliation_text,
                "lat": lat,
                "lon": lon,
                "speakers": speakers,
                "speaker_details": speaker_details,
                "speaker_count": len(speakers),
                "talk_count": len(group),
                "geocode_level": geocode_level,
                "distance_km": round(
                    _haversine_km(lat, lon, auckland_lat, auckland_lon),
                    1,
                ),
                "search_text": " ".join(search_parts).lower(),
            }
        )
    return records


def _author_affiliation_map(
    df: pd.DataFrame,
    *,
    affiliation_col: str = "affiliation",
    presenter_col: str = "presenter",
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for _, row in df.iterrows():
        presenter = row.get(presenter_col)
        affiliation = row.get(affiliation_col)
        if pd.isna(presenter) or pd.isna(affiliation):
            continue
        name = str(presenter).strip()
        if name and name not in mapping:
            mapping[name] = str(affiliation).strip()
    return mapping


def author_profile_entries(
    df: pd.DataFrame,
    *,
    affiliation_col: str = "affiliation",
    presenter_col: str = "presenter",
    delegate_affiliations: dict[str, str] | None = None,
) -> list[tuple[str, str, str, bool]]:
    """Return profile candidates as (name, affiliation, role, affiliation_explicit).

    Presenters are included only when their presenting talk has an explicit
    affiliation. Co-authors are included only when the delegate list provides
    an explicit affiliation.
    """
    from src.delegates import normalize_person_name

    delegate_affiliations = delegate_affiliations or _delegate_affiliation_map()
    presenter_map = _author_affiliation_map(
        df,
        affiliation_col=affiliation_col,
        presenter_col=presenter_col,
    )
    talk_counts = author_talk_counts(df, presenter_col=presenter_col)

    entries: dict[str, tuple[str, str, str, bool]] = {}
    for name, affiliation in presenter_map.items():
        entries[name] = (name, affiliation, "presenter", True)

    for name in talk_counts:
        if name in entries:
            continue
        norm = normalize_person_name(name)
        delegate_affiliation = delegate_affiliations.get(norm)
        if delegate_affiliation:
            entries[name] = (name, delegate_affiliation, "co_author", True)

    return list(entries.values())


def speakers_by_profile_connections(
    df: pd.DataFrame,
    *,
    affiliation_col: str = "affiliation",
    presenter_col: str = "presenter",
    delegate_affiliations: dict[str, str] | None = None,
) -> list[tuple[str, str, str, bool]]:
    """Profile candidates sorted by talk count (descending)."""
    entries = author_profile_entries(
        df,
        affiliation_col=affiliation_col,
        presenter_col=presenter_col,
        delegate_affiliations=delegate_affiliations,
    )
    talk_counts = author_talk_counts(df, presenter_col=presenter_col)
    return sorted(
        entries,
        key=lambda item: (-talk_counts.get(item[0], 0), item[0].casefold()),
    )


def _delegate_affiliation_map(
    delegates_path: str | Path = "data/delegates.json",
) -> dict[str, str]:
    """Map normalized person name to affiliation from the official delegate list."""
    from src.delegates import normalize_person_name
    from src.geocode import affiliation_base_name

    path = Path(delegates_path)
    if not path.exists():
        return {}

    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    mapping: dict[str, str] = {}
    for delegate in payload.get("delegates", []):
        name = str(delegate.get("full_name") or "").strip()
        affiliation = str(delegate.get("affiliation") or "").strip()
        if not name or not affiliation:
            continue
        norm = normalize_person_name(name)
        if norm and norm not in mapping:
            mapping[norm] = affiliation_base_name(affiliation) or affiliation
    return mapping


def _affiliation_coord_index(
    locations: list[dict[str, Any]],
) -> dict[str, tuple[float, float]]:
    from src.geocode import affiliation_base_name, canonical_affiliation_key

    index: dict[str, tuple[float, float]] = {}
    for location in locations:
        coords = (location["lat"], location["lon"])
        affiliation = location["affiliation"]
        for candidate in (
            affiliation,
            affiliation_base_name(affiliation),
            canonical_affiliation_key(affiliation),
        ):
            if candidate and candidate not in index:
                index[candidate] = coords
    return index


def _resolve_affiliation_coords(
    affiliation: str,
    coord_index: dict[str, tuple[float, float]],
) -> tuple[str, tuple[float, float] | None]:
    from src.geocode import affiliation_base_name, canonical_affiliation_key

    if not affiliation:
        return "", None
    display = affiliation_base_name(affiliation) or affiliation
    for candidate in (display, affiliation, canonical_affiliation_key(affiliation)):
        if candidate in coord_index:
            return display, coord_index[candidate]
    return display, None


def author_talk_counts(
    df: pd.DataFrame,
    *,
    presenter_col: str = "presenter",
) -> dict[str, int]:
    """Count talks where each author appears on the author list."""
    counts: dict[str, int] = {}
    for _, row in df.iterrows():
        for author in _talk_authors(row, presenter_col=presenter_col):
            counts[author] = counts.get(author, 0) + 1
    return counts


def _talk_authors(row: pd.Series, *, presenter_col: str = "presenter") -> list[str]:
    authors = row.get("authors")
    if isinstance(authors, list) and authors:
        cleaned = [str(author).strip() for author in authors if str(author).strip()]
        if cleaned:
            return cleaned
    presenter = row.get(presenter_col)
    if pd.isna(presenter):
        return []
    return [str(presenter).strip()]


def _build_network_data(
    df: pd.DataFrame,
    locations: list[dict[str, Any]],
    *,
    affiliation_col: str = "affiliation",
    presenter_col: str = "presenter",
    delegate_affiliations: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build co-authorship networks at individual and affiliation level."""
    from src.delegates import canonical_person_name, normalize_person_name

    delegate_affiliations = delegate_affiliations or {}
    presenter_affiliations = {
        canonical_person_name(name): affiliation
        for name, affiliation in _author_affiliation_map(
            df,
            affiliation_col=affiliation_col,
            presenter_col=presenter_col,
        ).items()
    }
    author_affiliations = dict(presenter_affiliations)
    explicit_affiliation = {name: True for name in presenter_affiliations}
    affiliation_coords = _affiliation_coord_index(locations)

    individual_talk_count: dict[str, int] = {}
    affiliation_talk_count: dict[str, int] = {}
    individual_edges: dict[tuple[str, str], int] = {}
    affiliation_edges: dict[tuple[str, str], int] = {}

    for _, row in df.iterrows():
        authors = [
            canonical_person_name(author)
            for author in _talk_authors(row, presenter_col=presenter_col)
        ]
        if not authors:
            continue

        affiliation = row.get(affiliation_col)
        affiliation_text = "" if pd.isna(affiliation) else str(affiliation).strip()

        for author in authors:
            individual_talk_count[author] = individual_talk_count.get(author, 0) + 1
            if affiliation_text and author not in author_affiliations:
                author_affiliations[author] = affiliation_text
                explicit_affiliation[author] = False

        if affiliation_text:
            affiliation_talk_count[affiliation_text] = (
                affiliation_talk_count.get(affiliation_text, 0) + 1
            )

        if len(authors) < 2:
            continue

        talk_affiliations = {
            author_affiliations[author]
            for author in authors
            if author in author_affiliations
        }

        for index, author_a in enumerate(authors):
            for author_b in authors[index + 1 :]:
                key = tuple(sorted((author_a, author_b)))
                individual_edges[key] = individual_edges.get(key, 0) + 1

        affiliation_list = sorted(talk_affiliations)
        for index, affiliation_a in enumerate(affiliation_list):
            for affiliation_b in affiliation_list[index + 1 :]:
                key = tuple(sorted((affiliation_a, affiliation_b)))
                affiliation_edges[key] = affiliation_edges.get(key, 0) + 1

    for author in individual_talk_count:
        norm = normalize_person_name(author)
        if norm in delegate_affiliations:
            author_affiliations[author] = delegate_affiliations[norm]
            explicit_affiliation[author] = True

    individual_nodes = []
    for author, connections in sorted(
        individual_talk_count.items(),
        key=lambda item: (-item[1], item[0].casefold()),
    ):
        affiliation, coords = _resolve_affiliation_coords(
            author_affiliations.get(author, ""),
            affiliation_coords,
        )
        lat = None
        lon = None
        distance_km = None
        if coords:
            lat, lon = coords
            distance_km = round(
                _haversine_km(lat, lon, AUCKLAND_LAT, AUCKLAND_LON),
                1,
            )
        individual_nodes.append(
            {
                "id": f"person:{author}",
                "label": author,
                "kind": "individual",
                "affiliation": affiliation,
                "author_role": (
                    "presenter" if author in presenter_affiliations else "co_author"
                ),
                "affiliation_explicit": explicit_affiliation.get(author, False),
                "connections": connections,
                "lat": lat,
                "lon": lon,
                "distance_km": distance_km,
            }
        )

    affiliation_nodes = []
    for affiliation, connections in sorted(
        affiliation_talk_count.items(),
        key=lambda item: (-item[1], item[0].casefold()),
    ):
        _, coords = _resolve_affiliation_coords(affiliation, affiliation_coords)
        lat = None
        lon = None
        distance_km = None
        if coords:
            lat, lon = coords
            distance_km = round(
                _haversine_km(lat, lon, AUCKLAND_LAT, AUCKLAND_LON),
                1,
            )
        affiliation_nodes.append(
            {
                "id": f"aff:{affiliation}",
                "label": affiliation,
                "kind": "affiliation",
                "connections": connections,
                "lat": lat,
                "lon": lon,
                "distance_km": distance_km,
            }
        )

    def _links(
        edges: dict[tuple[str, str], int],
        prefix: str,
    ) -> list[dict[str, Any]]:
        return [
            {
                "source": f"{prefix}{source}",
                "target": f"{prefix}{target}",
                "weight": weight,
            }
            for (source, target), weight in edges.items()
        ]

    return {
        "individual": {
            "nodes": individual_nodes,
            "links": _links(individual_edges, "person:"),
        },
        "affiliation": {
            "nodes": affiliation_nodes,
            "links": _links(affiliation_edges, "aff:"),
        },
    }


def _attendee_site_stats(
    df: pd.DataFrame,
    locations: list[dict[str, Any]],
    *,
    presenter_col: str = "presenter",
) -> dict[str, int]:
    mapped_speakers = sum(location["speaker_count"] for location in locations)
    total_presenters = df[presenter_col].nunique(dropna=True)
    mapped_talks = len(_geocoded_points(df))
    return {
        "location_count": len(locations),
        "mapped_speakers": mapped_speakers,
        "missing_speakers": total_presenters - mapped_speakers,
        "mapped_talks": mapped_talks,
        "missing_talks": len(df) - mapped_talks,
        "total_speakers": total_presenters,
        "total_talks": len(df),
    }


def export_attendee_site_data(
    df: pd.DataFrame,
    *,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
    affiliation_col: str = "affiliation",
    presenter_col: str = "presenter",
    title_col: str = "title",
    abstract_col: str = "abstract",
    title: str = "ICRS 2026",
    save_path: str | Path = "js/locations.js",
    auckland_lat: float = AUCKLAND_LAT,
    auckland_lon: float = AUCKLAND_LON,
) -> Path:
    """Export grouped affiliation locations for the static JS map site."""
    from datetime import UTC, datetime

    from src.map_exclusions import (
        export_map_exclusions_js,
        load_map_exclusions,
        map_talks_for_export,
    )

    map_exclusions = load_map_exclusions()
    export_map_exclusions_js()
    map_df = map_talks_for_export(
        df,
        exclusions=map_exclusions,
        presenter_col=presenter_col,
    )
    locations = _affiliation_location_records(
        map_df,
        lat_col=lat_col,
        lon_col=lon_col,
        affiliation_col=affiliation_col,
        presenter_col=presenter_col,
        title_col=title_col,
        abstract_col=abstract_col,
        auckland_lat=auckland_lat,
        auckland_lon=auckland_lon,
    )
    if not locations:
        raise ValueError("No geocoded affiliations available for site export.")

    # Network, talks index, and stats use the full programme; map locations do not.
    network = _build_network_data(
        df,
        locations,
        affiliation_col=affiliation_col,
        presenter_col=presenter_col,
        delegate_affiliations=_delegate_affiliation_map(),
    )
    talk_titles_by_author = _build_talk_title_index(
        df,
        presenter_col=presenter_col,
        title_col=title_col,
    )
    for location in locations:
        for speaker in location["speaker_details"]:
            speaker["talk_titles"] = talk_titles_by_author.get(speaker["name"], [])
    affiliation_connections = {
        node["label"]: node["connections"] for node in network["affiliation"]["nodes"]
    }
    for location in locations:
        location["connection_count"] = affiliation_connections.get(
            location["affiliation"],
            0,
        )

    payload = {
        "meta": {
            "title": title,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "central_lon": auckland_lon,
            "auckland": {
                "label": "Auckland, New Zealand",
                "lat": auckland_lat,
                "lon": auckland_lon,
            },
            "stats": _attendee_site_stats(df, locations, presenter_col=presenter_col),
        },
        "locations": locations,
        "network": network,
        "talk_titles_by_author": talk_titles_by_author,
    }
    js_body = (
        "/** Generated by export_attendee_site_data – do not edit by hand. */\n"
        f"export const SITE_DATA = {json.dumps(payload, ensure_ascii=False, indent=2)};\n"
    )
    output_path = Path(save_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(js_body, encoding="utf-8")
    return output_path


def plot_geocoding_summary(
    geocoded: pd.DataFrame,
    *,
    title: str = "Affiliation geocoding coverage",
    figsize: tuple[float, float] = (6, 4),
    save_path: str | None = None,
) -> tuple[Figure, Axes]:
    """Bar chart of geocoded vs missing affiliations."""
    counts = (
        geocoded["geocoded"]
        .value_counts()
        .rename(index={True: "Geocoded", False: "Missing"})
    )
    counts = counts.reindex(["Geocoded", "Missing"], fill_value=0)

    fig, ax = plt.subplots(figsize=figsize)
    bars: Iterable = ax.bar(counts.index, counts.values, color=["#1b9e77", "#7570b3"])
    ax.set_ylabel("Unique affiliations")
    ax.set_title(title)

    for bar in bars:
        height = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            height,
            f"{int(height)}",
            ha="center",
            va="bottom",
            fontsize=10,
        )

    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path, dpi=200, bbox_inches="tight")
    return fig, ax


def limit_line_length(line: str, line_lim: int = 20, *, line_sep: str = "\n") -> str:
    """Wrap long strings at whitespace boundaries."""
    if len(line) <= line_lim:
        return line

    whitespace_idx = line[:line_lim].rfind(" ")
    if whitespace_idx == -1:
        return line

    return (
        line[:whitespace_idx]
        + line_sep
        + limit_line_length(line[whitespace_idx + 1 :], line_lim, line_sep=line_sep)
    )


def _prepare_interactive_hover_points(
    points: pd.DataFrame,
    colname: str,
    line_lim: int = 20,
) -> pd.DataFrame:
    """Return a copy of points with wrapped hover text fields."""
    hover_points = points.copy()
    hover_points[colname] = hover_points[colname].map(
        lambda value: (
            limit_line_length(str(value), line_lim=line_lim, line_sep="<br>")
            if pd.notna(value)
            else value
        )
    )
    return hover_points
