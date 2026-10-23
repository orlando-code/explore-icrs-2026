"""Map pin country metadata and unique-country stats."""

from __future__ import annotations

from src.site.plot_utils import (
    _map_pin_country,
    _map_pin_country_fields,
    _unique_map_country_count,
)


def test_map_pin_country_prefers_registry_country_code():
    code, label = _map_pin_country(
        "Example Institute",
        {"country": "nan", "latitude": 38.9, "longitude": -77.0},
        country_code="US",
    )
    assert code == "US"
    assert label == "United States"


def test_map_pin_country_uses_geocode_hit_country():
    code, label = _map_pin_country(
        "Example Institute, United States",
        {"country": "United States", "latitude": 38.9, "longitude": -77.0},
    )
    assert code == "US"
    assert label == "United States"


def test_map_pin_country_parses_affiliation_when_hit_missing_country():
    code, label = _map_pin_country("Example Institute, Fiji", None)
    assert code == "FJ"
    assert label == "Fiji"


def test_unique_map_country_count_uses_iso_codes():
    locations = [
        {"country_code": "US", "country": "United States"},
        {"country_code": "US", "country": "United States"},
        {"country_code": "FJ", "country": "Fiji"},
        {"country_code": "NZ", "country": "New Zealand"},
    ]
    assert _unique_map_country_count(locations) == 3


def test_map_pin_country_fields_omits_empty():
    assert _map_pin_country_fields("", None) == {}
