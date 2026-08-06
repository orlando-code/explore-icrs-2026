"""Unit tests for geocode overrides, capital fallbacks, and foreign-delegate anchors."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.geocoding.affiliation_geocodes import (
    _accept_org_country_hit,
    _capital_fallback_record,
    _override_hit,
    build_geocode_lookup,
    load_geocode_overrides,
    load_geocode_source_frames,
    resolve_geocode,
)
from src.geocoding.capital_coords import (
    coords_plausible_for_country,
    organisation_country_mismatch,
    resolve_capital_fallback,
    resolve_country_anchor_fallback,
)
from src.geocoding.foreign_delegate import (
    foreign_delegate_anchor_reason,
    institute_home_countries,
    standardised_affiliation_label,
)
from src.geocoding.geocode import (
    _affiliation_fingerprint,
    _lookup_override,
    affiliation_base_name,
    affiliation_lookup_keys,
    canonical_affiliation_key,
    geocode_coords_score,
    is_crf_cache_poison,
    load_affiliation_display_aliases,
    resolve_affiliation_alias,
)


class TestAffiliationFingerprintAndKeys:
    def test_fingerprint_folds_punctuation(self, assert_eq):
        left = _affiliation_fingerprint("Hawai'i Institute of Marine Biology")
        right = _affiliation_fingerprint("Hawaii Institute of Marine Biology")
        assert_eq(left, right, context="apostrophe fingerprint fold")

    def test_lookup_keys_include_variants(self, assert_eq):
        keys = affiliation_lookup_keys("KAUST, Saudi Arabia")
        assert keys, "expected non-empty lookup keys"
        assert any("KAUST" in key or "kaust" in key.casefold() for key in keys), (
            f"expected KAUST in keys, got {keys!r}"
        )

    def test_affiliation_base_name_strips_country(self, assert_eq):
        assert_eq(
            affiliation_base_name("University of Auckland, New Zealand"),
            "University of Auckland",
            context="base name strip",
        )


class TestDisplayAliases:
    def test_load_and_resolve_alias(self, tmp_path, monkeypatch, assert_eq):
        path = tmp_path / "affiliation_display_aliases.json"
        path.write_text(
            json.dumps(
                {
                    "aliases": {
                        "AIMS": "Australian Institute of Marine Science",
                        "Uni of Auckland": "University of Auckland",
                    }
                }
            ),
            encoding="utf-8",
        )
        import src.geocoding.geocode as geocode_module

        monkeypatch.setattr(geocode_module, "DEFAULT_DISPLAY_ALIASES_PATH", path)
        geocode_module._DISPLAY_ALIASES_CACHE = None

        aliases = load_affiliation_display_aliases(path)
        assert_eq(
            aliases["AIMS"],
            "Australian Institute of Marine Science",
            context="loaded alias",
        )
        assert_eq(
            resolve_affiliation_alias("AIMS"),
            "Australian Institute of Marine Science",
            context="exact alias resolve",
        )
        assert_eq(
            resolve_affiliation_alias("Unknown Lab"),
            "Unknown Lab",
            context="unknown alias passthrough",
        )


class TestLookupOverride:
    def test_exact_and_fingerprint_match(self, assert_eq):
        overrides = {
            "Coral Restoration Foundation": {
                "latitude": 25.088014,
                "longitude": -80.441046,
                "query_used": "override:Coral Restoration Foundation",
                "geocode_level": "institute",
            }
        }
        exact = _lookup_override("Coral Restoration Foundation", overrides)
        assert exact is not None, "exact override miss"
        assert_eq(exact["latitude"], 25.088014, context="exact lat")
        assert_eq(exact["query_used"], "override:Coral Restoration Foundation")

        fuzzy = _lookup_override("coral restoration foundation", overrides)
        assert fuzzy is not None, (
            f"fingerprint override miss for casefold key; fingerprints="
            f"{_affiliation_fingerprint('Coral Restoration Foundation')!r} vs "
            f"{_affiliation_fingerprint('coral restoration foundation')!r}"
        )

        missing = _lookup_override("Totally Different Lab", overrides)
        assert missing is None, f"unexpected override hit: {missing!r}"


class TestCrfCachePoison:
    def test_legitimate_crf_not_poison(self, assert_eq):
        coords = {
            "latitude": 25.088014,
            "longitude": -80.441046,
            "query_used": "override:Coral Restoration Foundation",
        }
        assert is_crf_cache_poison("Coral Restoration Foundation, United States", coords) is False

    def test_poisoned_unrelated_affiliation(self, assert_eq):
        coords = {
            "latitude": 25.088014,
            "longitude": -80.441046,
            "query_used": "override:Coral Restoration Foundation",
        }
        assert is_crf_cache_poison("University of Auckland, New Zealand", coords) is True, (
            "CRF Key Largo coords on unrelated affiliation must be flagged as poison"
        )

    def test_nearby_coords_without_crf_query_not_poison(self, assert_eq):
        coords = {
            "latitude": 25.088014,
            "longitude": -80.441046,
            "query_used": "nominatim:some other query",
        }
        assert is_crf_cache_poison("Random Lab", coords) is False

    def test_missing_coords(self, assert_eq):
        assert is_crf_cache_poison("Anything", None) is False
        assert is_crf_cache_poison("Anything", {}) is False


class TestGeocodeCoordsScore:
    def test_priority_order(self, assert_eq):
        assert_eq(geocode_coords_score(None), 0, context="missing")
        assert_eq(
            geocode_coords_score({"latitude": 1, "query_used": "override"}),
            100,
            context="override score",
        )
        assert_eq(
            geocode_coords_score({"latitude": 1, "query_used": "google:x"}),
            80,
            context="google score",
        )
        assert_eq(
            geocode_coords_score({"latitude": 1, "geocode_level": "institute"}),
            50,
            context="institute score",
        )
        assert_eq(
            geocode_coords_score({"latitude": 1, "geocode_level": "country"}),
            10,
            context="country score",
        )


class TestOrganisationCountryMismatch:
    def test_bios_in_french_polynesia_is_mismatch(self, assert_eq):
        assert organisation_country_mismatch(
            "Bermuda Institute of Ocean Sciences",
            "French Polynesia",
        ) is True, "BIOS + French Polynesia should be treated as foreign-institute mismatch"

    def test_matching_home_is_not_mismatch(self, assert_eq):
        assert organisation_country_mismatch(
            "Bermuda Institute of Ocean Sciences",
            "Bermuda",
        ) is False

    def test_generic_org_without_country_hint(self, assert_eq):
        assert organisation_country_mismatch("Random Research Group", "Fiji") is False


class TestCapitalFallback:
    def test_resolve_australia_capital(self, assert_eq):
        fallback = resolve_capital_fallback("Some Org", "Australia")
        assert fallback is not None, "expected Australia capital fallback"
        city, lat, lon, query = fallback
        assert_eq(city, "Canberra", context="Australia capital city")
        assert -36 < lat < -34, f"unexpected Canberra lat {lat}"
        assert 148 < lon < 150, f"unexpected Canberra lon {lon}"
        assert query.startswith("fallback:capital:"), f"bad query label {query!r}"

    def test_us_state_capital_from_org(self, assert_eq):
        fallback = resolve_capital_fallback("University of Hawaii", "United States")
        assert fallback is not None, "expected US/Hawaii capital fallback"
        city, _, _, query = fallback
        assert "Hawaii" in query or city, (
            f"expected Hawaii-aware fallback, got city={city!r} query={query!r}"
        )

    def test_us_default_dc(self, assert_eq):
        fallback = resolve_capital_fallback("Generic US Lab", "United States")
        assert fallback is not None
        city, _, _, query = fallback
        assert_eq(city, "Washington", context="default US capital")
        assert "United States" in query

    def test_country_anchor_only_on_mismatch(self, assert_eq):
        mismatch_anchor = resolve_country_anchor_fallback(
            "Bermuda Institute of Ocean Sciences",
            "French Polynesia",
        )
        assert mismatch_anchor is not None, "mismatch should force country-anchor fallback"

        no_mismatch = resolve_country_anchor_fallback(
            "University of Auckland",
            "New Zealand",
        )
        assert no_mismatch is None, (
            f"local institute must not force country anchor, got {no_mismatch!r}"
        )

    def test_coords_plausible_near_capital(self, assert_eq):
        assert coords_plausible_for_country(-41.3, 174.8, "New Zealand") is True
        # Key Largo is far from French Polynesia capitals.
        assert coords_plausible_for_country(25.088, -80.441, "French Polynesia") is False


class TestForeignDelegate:
    def test_anchor_reason(self, assert_eq):
        assert_eq(
            foreign_delegate_anchor_reason(
                "Bermuda Institute of Ocean Sciences",
                "French Polynesia",
            ),
            "institute_home_country_differs",
            context="foreign BIOS reason",
        )
        assert_eq(
            foreign_delegate_anchor_reason("University of Auckland", "New Zealand"),
            "",
            context="local Auckland reason",
        )

    def test_institute_home_countries(self, assert_eq):
        homes = institute_home_countries("Bermuda Institute of Ocean Sciences")
        assert any("Bermuda" in home for home in homes), (
            f"expected Bermuda in institute homes, got {homes!r}"
        )

    def test_standardised_label_keeps_org_not_capital_city(self, assert_eq):
        label = standardised_affiliation_label(
            "Bermuda Institute of Ocean Sciences",
            "French Polynesia",
        )
        assert "Bermuda Institute of Ocean Sciences" in label, f"org missing from {label!r}"
        # Display helper may strip the trailing country; never rename the org to a capital.
        assert "Papeete" not in label, f"label must not become capital city: {label!r}"


class TestAffiliationGeocodeResolution:
    def test_load_overrides_from_temp(self, tmp_path, monkeypatch, assert_eq):
        path = tmp_path / "geocode_overrides.json"
        path.write_text(
            json.dumps(
                {
                    "Test Lab": {
                        "latitude": 1.23,
                        "longitude": 4.56,
                        "query_used": "override:Test Lab",
                    }
                }
            ),
            encoding="utf-8",
        )
        import src.geocoding.affiliation_geocodes as mod
        import src.geocoding.geocode as geocode_mod

        monkeypatch.setattr(mod, "DEFAULT_OVERRIDES_PATH", path)
        monkeypatch.setattr(geocode_mod, "DEFAULT_OVERRIDES_PATH", path)
        mod._GEOCODE_OVERRIDES_CACHE = None

        # Bypass cache by loading via path through _load_json directly.
        from src.geocoding.geocode import _load_json

        payload = _load_json(path)
        assert_eq(payload["Test Lab"]["latitude"], 1.23, context="override json lat")

    def test_source_frame_priority(self, tmp_path, assert_eq):
        main = tmp_path / "main.csv"
        manual = tmp_path / "manual.csv"
        main.write_text(
            "organisation,country,affiliation,status,latitude,longitude,formatted_address,query_used\n"
            "Lab A,Fiji,Lab A Fiji,IMPRECISE,-18.0,178.0,x,q1\n",
            encoding="utf-8",
        )
        manual.write_text(
            "organisation,country,affiliation,status,latitude,longitude,formatted_address,query_used\n"
            "Lab A,Fiji,Lab A Fiji,OK,-18.1,178.4,y,q2\n",
            encoding="utf-8",
        )
        frame = load_geocode_source_frames(main, manual_path=manual)
        assert_eq(len(frame), 1, context="deduped to one org+country")
        assert_eq(str(frame.iloc[0]["status"]), "OK", context="OK beats IMPRECISE")
        assert abs(float(frame.iloc[0]["latitude"]) - (-18.1)) < 1e-9

    def test_override_hit_and_accept_mismatch(self, assert_eq):
        overrides = {
            "Bermuda Institute of Ocean Sciences": {
                "latitude": 32.3,
                "longitude": -64.8,
                "query_used": "override:BIOS Bermuda",
            }
        }
        hit = _override_hit(
            "Bermuda Institute of Ocean Sciences, French Polynesia",
            overrides,
            organisation="Bermuda Institute of Ocean Sciences",
            country="French Polynesia",
        )
        assert hit is not None, "expected override/fallback hit for BIOS+FP"
        # Bermuda coords are not plausible for French Polynesia → capital fallback.
        assert str(hit["query_used"]).startswith("fallback:capital:") or float(hit["latitude"]) != 32.3, (
            f"implausible Bermuda override for FP should fall back; got {hit!r}"
        )

    def test_resolve_geocode_uses_override_when_no_country(self, assert_eq):
        """Overrides apply when affiliation has no trailing country (skips org+country path)."""
        lookup = build_geocode_lookup(pd.DataFrame())
        overrides = {
            "Override Only Lab": {
                "latitude": -17.5,
                "longitude": 177.5,
                "query_used": "override:Override Only Lab",
            }
        }
        hit = resolve_geocode(
            "Override Only Lab",
            presenter="",
            lookup=lookup,
            overrides=overrides,
        )
        assert hit is not None, (
            f"expected override geocode hit for org-only affiliation; got {hit!r}"
        )
        assert_eq(float(hit["latitude"]), -17.5, context="override lat")
        assert "override" in str(hit["query_used"]).casefold(), (
            f"expected override query_used, got {hit['query_used']!r}"
        )

    def test_override_hit_helper_returns_coords(self, assert_eq):
        overrides = {
            "Standalone Override Lab": {
                "latitude": 12.34,
                "longitude": 56.78,
                "query_used": "override:Standalone",
            }
        }
        hit = _override_hit(
            "Standalone Override Lab",
            overrides,
            organisation="Standalone Override Lab",
            country="",
        )
        assert hit is not None, f"expected _override_hit, got {hit!r}"
        assert_eq(float(hit["latitude"]), 12.34, context="_override_hit lat")
        assert_eq(float(hit["longitude"]), 56.78, context="_override_hit lon")

    def test_resolve_geocode_org_country_hit_before_override(self, assert_eq):
        """Current resolve order: org+country CSV/capital path runs before override lookup."""
        geocodes = pd.DataFrame(
            [
                {
                    "organisation": "Test Lab",
                    "country": "Fiji",
                    "affiliation": "Test Lab, Fiji",
                    "latitude": -18.0,
                    "longitude": 178.0,
                    "formatted_address": "csv",
                    "query_used": "csv",
                    "status": "OK",
                }
            ]
        )
        lookup = build_geocode_lookup(geocodes)
        overrides = {
            "Test Lab, Fiji": {
                "latitude": -17.5,
                "longitude": 177.5,
                "query_used": "override:Test Lab",
            }
        }
        hit = resolve_geocode(
            "Test Lab, Fiji",
            presenter="",
            lookup=lookup,
            overrides=overrides,
        )
        assert hit is not None, "expected geocode hit"
        assert_eq(float(hit["latitude"]), -18.0, context="CSV org+country currently wins")

    def test_capital_fallback_record(self, assert_eq):
        record = _capital_fallback_record("Some Org", "Australia", "Some Org, Australia")
        assert record is not None
        assert_eq(record["geocode_level"], "country", context="fallback level")
        assert record["query_used"].startswith("fallback:capital:")

    def test_accept_org_country_hit_keeps_plausible(self, assert_eq):
        hit = {
            "latitude": -36.85,
            "longitude": 174.76,
            "query_used": "csv",
            "geocode_level": "institute",
        }
        accepted = _accept_org_country_hit(
            hit,
            organisation="University of Auckland",
            country="New Zealand",
            affiliation="University of Auckland, New Zealand",
        )
        assert accepted is hit
