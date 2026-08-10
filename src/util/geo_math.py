"""Shared geographic math helpers."""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6_371.0


def shortest_lon_delta(lon1: float, lon2: float) -> float:
    """Signed longitude difference in (-180, 180], handling the antimeridian."""
    delta = lon2 - lon1
    return (delta + 180.0) % 360.0 - 180.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two WGS84 points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(shortest_lon_delta(lon1, lon2))
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))
