"""Unit tests for emissions origin-country and location-key special handling."""

from __future__ import annotations

import pytest

from src.emissions.origin_country import (
    country_from_affiliation,
    country_from_coordinates,
    country_label,
    iso3_from_iso2,
    resolve_origin_country,
)
from src.emissions.travel_emissions import (
    _emissions_location_key,
    _looks_like_coordinates,
    _origin_from_attendee,
)


class TestCountryFromAffiliation:
    @pytest.mark.parametrize(
        "affiliation,expected",
        [
            ("University of Auckland, New Zealand", "NZ"),
            ("KAUST, Saudi Arabia", "SA"),
            ("Some Lab, Australia", "AU"),
            ("", ""),
        ],
    )
    def test_trailing_country(self, affiliation, expected, assert_eq):
        assert_eq(
            country_from_affiliation(affiliation),
            expected,
            context=f"country_from_affiliation({affiliation!r})",
        )


class TestCountryFromCoordinates:
    def test_cache_hit_and_miss(self, assert_eq):
        cache = {"-36.8500,174.7600": {"country_code": "nz"}}
        assert_eq(
            country_from_coordinates(-36.85, 174.76, cache),
            "NZ",
            context="reverse cache hit",
        )
        assert_eq(
            country_from_coordinates(None, 174.76, cache),
            "",
            context="missing lat",
        )
        assert_eq(
            country_from_coordinates(-10.0, 10.0, cache),
            "",
            context="cache miss",
        )


class TestResolveOriginCountry:
    def test_delegate_iso2_wins(self, assert_eq):
        assert_eq(
            resolve_origin_country(
                affiliation="BIOS, French Polynesia",
                lat=32.3,
                lon=-64.8,
                reverse_cache={"32.3000,-64.8000": {"country_code": "BM"}},
                delegate_country="French Polynesia",
                delegate_country_code="PF",
                existing="BM",
            ),
            "PF",
            context="delegate ISO2 highest priority",
        )

    def test_existing_then_coords_then_affiliation(self, assert_eq):
        assert_eq(
            resolve_origin_country(existing="AU"),
            "AU",
            context="existing code",
        )
        assert_eq(
            resolve_origin_country(existing="UNKNOWN"),
            "",
            context="UNKNOWN existing ignored when nothing else",
        )
        assert_eq(
            resolve_origin_country(
                existing="UNKNOWN",
                lat=1.0,
                lon=2.0,
                reverse_cache={"1.0000,2.0000": {"country_code": "fj"}},
            ),
            "FJ",
            context="coords after UNKNOWN",
        )
        assert_eq(
            resolve_origin_country(affiliation="Lab, Fiji"),
            "FJ",
            context="affiliation fallback",
        )
        assert_eq(
            resolve_origin_country(delegate_country="nz"),
            "NZ",
            context="two-letter delegate_country",
        )


class TestIsoHelpers:
    def test_iso3_and_label(self, assert_eq):
        assert_eq(iso3_from_iso2("NZ"), "NZL", context="NZ → NZL")
        assert_eq(iso3_from_iso2(""), "", context="empty iso3")
        assert_eq(iso3_from_iso2("ZZ"), "", context="invalid iso3")
        assert country_label("NZ"), "expected a country label for NZ"
        assert_eq(country_label(""), "", context="empty label")


class TestEmissionsLocationKey:
    def test_groups_by_org_and_country(self, assert_eq):
        key = _emissions_location_key(
            "Bermuda Institute of Ocean Sciences, French Polynesia"
        )
        assert_eq(
            key,
            "bermuda institute of ocean sciences|french polynesia",
            context="foreign-delegate location key",
        )
        # Same org in Bermuda must not collide with FP anchor.
        other = _emissions_location_key(
            "Bermuda Institute of Ocean Sciences, Bermuda"
        )
        assert key != other, (
            f"foreign and home anchors must differ: {key!r} vs {other!r}"
        )

    def test_empty(self, assert_eq):
        assert_eq(_emissions_location_key(""), "", context="empty affiliation key")


class TestOriginFromAttendee:
    def test_delegate_country_preferred_over_geo(self, assert_eq):
        country, location = _origin_from_attendee(
            "University of Auckland, New Zealand",
            {"country_code": "US", "location_name": "Auckland"},
            geocode_level="institute",
        )
        assert_eq(country, "NZ", context="delegate country ISO2")
        assert_eq(location, "Auckland", context="location name from geo")

    def test_foreign_mismatch_uses_capital_city(self, assert_eq):
        country, location = _origin_from_attendee(
            "Bermuda Institute of Ocean Sciences, French Polynesia",
            {"country_code": "BM", "location_name": "St. George's"},
            geocode_level="institute",
        )
        assert_eq(country, "PF", context="foreign delegate ISO2")
        # Capital fallback for French Polynesia should be Papeete (or similar).
        assert location, f"expected capital city label, got {location!r}"
        assert location != "St. George's", (
            f"mismatch should not keep Bermuda city; got {location!r}"
        )

    def test_country_level_geocode_uses_capital(self, assert_eq):
        country, location = _origin_from_attendee(
            "Some Lab, Australia",
            {"country_code": "AU", "location_name": "-25.0,133.0"},
            geocode_level="country",
        )
        assert_eq(country, "AU", context="AU ISO2")
        assert_eq(location, "Canberra", context="country-level → capital city")

    def test_looks_like_coordinates(self, assert_eq):
        assert _looks_like_coordinates("-25.0,133.0") is True
        assert _looks_like_coordinates("Auckland") is False
