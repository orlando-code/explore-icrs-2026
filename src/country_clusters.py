"""Privacy-preserving country clusters for offset choropleth (minimum group size)."""

from __future__ import annotations

import math
from typing import Any

from src.country_continents import continent_for_country, load_country_continents, same_continent
from src.country_neighbors import load_country_neighbors, neighbors_for_country

MIN_OFFSET_CLUSTER_SIZE = 3


def haversine_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius_km * math.asin(math.sqrt(a))


def _cluster_centroid(
    members: list[str],
    centroids: dict[str, tuple[float, float]],
) -> tuple[float, float]:
    points = [centroids[code] for code in members if code in centroids]
    if not points:
        return 0.0, 0.0
    return (
        sum(lat for lat, _ in points) / len(points),
        sum(lon for _, lon in points) / len(points),
    )


def _neighbor_candidates(
    code: str,
    counts: dict[str, int],
    neighbors: dict[str, list[str]],
    continents: dict[str, str],
) -> list[str]:
    return [
        neighbor
        for neighbor in neighbors_for_country(code, neighbors)
        if neighbor in counts and same_continent(code, neighbor, continents)
    ]


def _best_neighbor_host(
    code: str,
    counts: dict[str, int],
    neighbors: dict[str, list[str]],
    continents: dict[str, str],
    centroids: dict[str, tuple[float, float]],
) -> str | None:
    from src.country_neighbors import HOST_PREFERENCES

    candidates = _neighbor_candidates(code, counts, neighbors, continents)
    if not candidates:
        return None
    preferred = HOST_PREFERENCES.get(code.upper())
    if preferred and preferred in candidates and preferred in counts:
        return preferred
    origin = centroids.get(code)

    def sort_key(neighbor: str) -> tuple[int, float]:
        distance = 0.0
        if origin and neighbor in centroids:
            distance = haversine_km(origin[0], origin[1], *centroids[neighbor])
        return (-counts[neighbor], distance)

    return min(candidates, key=sort_key)


def _nearest_anchor(
    code: str,
    anchors: list[str],
    counts: dict[str, int],
    centroids: dict[str, tuple[float, float]],
    continents: dict[str, str],
    neighbors: dict[str, list[str]],
) -> str | None:
    neighbor_anchors = [
        neighbor
        for neighbor in _neighbor_candidates(
            code,
            {anchor: counts[anchor] for anchor in anchors if anchor in counts},
            neighbors,
            continents,
        )
        if neighbor in anchors and neighbor in centroids
    ]
    if neighbor_anchors:
        return max(neighbor_anchors, key=lambda anchor: counts[anchor])

    continent_anchors = [
        anchor
        for anchor in anchors
        if same_continent(code, anchor, continents) and anchor in centroids
    ]
    if not continent_anchors:
        return None

    origin = centroids.get(code)
    if not origin:
        return max(continent_anchors, key=lambda anchor: counts[anchor])

    return min(
        continent_anchors,
        key=lambda anchor: (
            haversine_km(origin[0], origin[1], *centroids[anchor]),
            -counts[anchor],
        ),
    )


def _cluster_label(members: list[str], labels: dict[str, str]) -> str:
    member_labels = [labels.get(code, code) for code in members]
    return ", ".join(member_labels)


def build_country_clusters(
    country_counts: dict[str, int],
    centroids: dict[str, tuple[float, float]],
    *,
    min_size: int = MIN_OFFSET_CLUSTER_SIZE,
    country_labels: dict[str, str] | None = None,
    continents: dict[str, str] | None = None,
    neighbors: dict[str, list[str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Attach small countries to larger contiguous neighbours; large countries anchor alone."""
    labels = country_labels or {}
    continent_map = continents or load_country_continents()
    neighbor_map = neighbors or load_country_neighbors()
    counts = {
        str(code).strip().upper(): int(value)
        for code, value in country_counts.items()
        if str(code).strip() and int(value) > 0
    }
    if not counts:
        return [], {}

    cluster_members: dict[str, list[str]] = {}
    country_to_cluster: dict[str, str] = {}

    anchors = [code for code, total in counts.items() if total >= min_size]
    for code in sorted(anchors, key=lambda item: (-counts[item], item)):
        cluster_id = f"cluster-{code}"
        cluster_members[cluster_id] = [code]
        country_to_cluster[code] = cluster_id

    small_codes = sorted(
        [code for code, total in counts.items() if total < min_size],
        key=lambda code: (counts[code], code),
    )
    unassigned: list[str] = []
    for code in small_codes:
        host = _best_neighbor_host(code, counts, neighbor_map, continent_map, centroids)
        if host and host in country_to_cluster:
            cluster_id = country_to_cluster[host]
            cluster_members[cluster_id].append(code)
            country_to_cluster[code] = cluster_id
            continue
        unassigned.append(code)

    for code in unassigned:
        host = _nearest_anchor(
            code,
            anchors,
            counts,
            centroids,
            continent_map,
            neighbor_map,
        )
        if host and host in country_to_cluster:
            cluster_id = country_to_cluster[host]
            cluster_members[cluster_id].append(code)
            country_to_cluster[code] = cluster_id
            continue

        continent_codes = [
            other
            for other, total in counts.items()
            if other != code and same_continent(code, other, continent_map)
        ]
        if not continent_codes:
            continue
        host = max(continent_codes, key=lambda other: counts[other])
        if host not in country_to_cluster:
            cluster_id = f"cluster-{host}"
            cluster_members[cluster_id] = [host]
            country_to_cluster[host] = cluster_id
        cluster_id = country_to_cluster[host]
        cluster_members[cluster_id].append(code)
        country_to_cluster[code] = cluster_id

    clusters: list[dict[str, Any]] = []
    for cluster_id, members in sorted(cluster_members.items()):
        unique_members = sorted(set(members))
        clusters.append(
            {
                "cluster_id": cluster_id,
                "countries": unique_members,
                "attendee_count": sum(counts[member] for member in unique_members),
                "label": _cluster_label(unique_members, labels),
            }
        )

    return clusters, country_to_cluster


def country_counts_from_estimates(estimates) -> dict[str, int]:
    if estimates is None or estimates.empty or "origin_country" not in estimates.columns:
        return {}
    series = estimates["origin_country"].astype(str).str.strip().str.upper()
    series = series[series.ne("") & series.ne("UNKNOWN") & series.ne("NAN")]
    return {code: int(count) for code, count in series.value_counts().items()}
