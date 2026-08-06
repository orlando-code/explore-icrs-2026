"""Unit tests for geography overrides: neighbors, hosts, continents, territories."""

from __future__ import annotations

import pytest

from src.geography.country_clusters import _best_neighbor_host, build_country_clusters
from src.geography.country_continents import continent_for_country, same_continent
from src.geography.country_neighbors import (
    HOST_PREFERENCES,
    NEIGHBOR_OVERRIDES,
    load_country_neighbors,
    neighbors_for_country,
)
from src.geography.territory_overlays import TERRITORY_OVERLAY_ISO2, territory_overlay_codes


class TestNeighborOverrides:
    def test_override_entries_are_bidirectional_in_loaded_map(self, assert_eq):
        neighbors = load_country_neighbors()
        for code, expected in NEIGHBOR_OVERRIDES.items():
            actual = neighbors_for_country(code, neighbors)
            for neighbor in expected:
                assert neighbor in actual, (
                    f"NEIGHBOR_OVERRIDES[{code!r}] expected neighbor {neighbor!r} "
                    f"in loaded adjacency {actual!r}"
                )
                reverse = neighbors_for_country(neighbor, neighbors)
                assert code in reverse, (
                    f"override adjacency must be bidirectional: {neighbor!r} → {code!r} "
                    f"missing from {reverse!r}"
                )

    def test_key_microstate_overrides(self, assert_eq):
        neighbors = load_country_neighbors()
        assert_eq(
            sorted(set(neighbors_for_country("HK", neighbors)) & {"CN"}),
            ["CN"],
            context="HK includes CN",
        )
        assert "ES" in neighbors_for_country("GI", neighbors), (
            f"Gibraltar should neighbor Spain; got {neighbors_for_country('GI', neighbors)!r}"
        )
        assert "IT" in neighbors_for_country("VA", neighbors), (
            f"Vatican should neighbor Italy; got {neighbors_for_country('VA', neighbors)!r}"
        )


class TestHostPreferences:
    def test_preferences_point_at_override_neighbors(self, assert_eq):
        for code, host in HOST_PREFERENCES.items():
            assert host in NEIGHBOR_OVERRIDES.get(code, [host]) or host in load_country_neighbors().get(
                code, []
            ), (
                f"HOST_PREFERENCES[{code!r}]={host!r} is not a known neighbor of {code!r}"
            )

    def test_best_neighbor_host_prefers_host_preference(self, assert_eq):
        neighbors = {
            "HK": ["CN", "TW"],
            "CN": ["HK"],
            "TW": ["HK"],
        }
        counts = {"HK": 1, "CN": 10, "TW": 50}
        continents = {"HK": "Asia", "CN": "Asia", "TW": "Asia"}
        centroids = {
            "HK": (22.3, 114.2),
            "CN": (35.0, 105.0),
            "TW": (23.7, 121.0),
        }
        # Without preference, TW would win on attendee count; preference forces CN.
        host = _best_neighbor_host("HK", counts, neighbors, continents, centroids)
        assert_eq(host, "CN", context="HK host preference over larger TW")


class TestContinents:
    def test_same_continent(self, assert_eq):
        continents = {"US": "North America", "CA": "North America", "AU": "Oceania", "FJ": "Oceania"}
        assert same_continent("US", "CA", continents) is True
        assert same_continent("US", "AU", continents) is False
        assert same_continent("US", "ZZ", continents) is False
        assert_eq(continent_for_country("fj", continents), "Oceania", context="casefold code")


class TestTerritoryOverlays:
    def test_overlay_filter(self, assert_eq):
        active = {"US", "RE", "FJ", "HK", "AU", "XX"}
        overlays = territory_overlay_codes(active)
        assert_eq(overlays, ["HK", "RE"], context="overlay intersection sorted")
        for code in overlays:
            assert code in TERRITORY_OVERLAY_ISO2


class TestHostPreferenceInClustering:
    def test_hong_kong_joins_china_preference(self, assert_eq):
        neighbors = {
            **load_country_neighbors(),
            "HK": ["CN", "TW"],
            "CN": ["HK", "MN"],
            "TW": ["HK"],
            "MN": ["CN"],
        }
        counts = {"CN": 20, "TW": 40, "HK": 1, "MN": 5}
        centroids = {
            "CN": (35.0, 105.0),
            "TW": (23.7, 121.0),
            "HK": (22.3, 114.2),
            "MN": (46.0, 105.0),
        }
        _, mapping = build_country_clusters(
            counts,
            centroids,
            min_size=3,
            neighbors=neighbors,
        )
        assert mapping["HK"] == mapping["CN"], (
            f"HK should join CN via HOST_PREFERENCES; mapping={mapping!r}"
        )
