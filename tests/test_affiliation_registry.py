"""Unit tests for affiliation registry parsing, redirects, and lookup."""

from __future__ import annotations

import pandas as pd
import pytest

from src.registry.affiliation_lookup import (
    AffiliationIndex,
    lookup_affiliation_key,
    registry_geocode_hit,
)
from src.registry.affiliation_registry import (
    _build_org_redirects,
    _clean_review_value,
    _make_affiliation,
    _resolve_attendee_org_country,
    canonical_for_parts,
    group_key,
    load_registry_overrides,
    parse_affiliation_parts,
)


class TestParseAffiliationParts:
    def test_empty(self, assert_eq):
        assert_eq(parse_affiliation_parts(""), ("", ""), context="empty affiliation")
        assert_eq(parse_affiliation_parts("   "), ("", ""), context="whitespace affiliation")

    def test_org_only(self, assert_eq):
        assert_eq(
            parse_affiliation_parts("KAUST"),
            ("KAUST", ""),
            context="org-only",
        )

    def test_simple_org_country(self, assert_eq):
        assert_eq(
            parse_affiliation_parts("University of Auckland, New Zealand"),
            ("University of Auckland", "New Zealand"),
            context="simple org,country",
        )

    def test_org_with_internal_commas(self, assert_eq):
        affiliation = (
            "Rethinking, Rebuilding, Regenerating Coral Reefs, Philippines"
        )
        org, country = parse_affiliation_parts(affiliation)
        assert_eq(country, "Philippines", context="trailing country with internal commas")
        assert_eq(
            org,
            "Rethinking, Rebuilding, Regenerating Coral Reefs",
            context="org keeps internal commas",
        )

    def test_multi_part_country_name(self, assert_eq):
        org, country = parse_affiliation_parts(
            "Some Lab, Micronesia, Federated States of"
        )
        # Depending on trailing-country detection, country may be multi-part.
        assert country, (
            f"expected a country for Micronesia affiliation, got org={org!r} country={country!r}"
        )
        assert "Micronesia" in country or country_to_iso2_safe(country), (
            f"expected Micronesia-related country, got {country!r}"
        )


def country_to_iso2_safe(country: str) -> bool:
    from src.sources.delegates import country_to_iso2

    return bool(country_to_iso2(country))


class TestGroupKeyAndCanonical:
    def test_group_key_is_stable_and_case_insensitive(self, assert_eq):
        left = group_key("University of Auckland", "New Zealand")
        right = group_key("University of Auckland", "new zealand")
        assert_eq(left, right, context="group_key country casefold")
        assert "|" in left, f"group_key missing separator: {left!r}"

    def test_make_affiliation(self, assert_eq):
        assert_eq(
            _make_affiliation("KAUST", "Saudi Arabia"),
            "KAUST, Saudi Arabia",
            context="make affiliation",
        )
        assert_eq(_make_affiliation("KAUST", ""), "KAUST", context="make affiliation no country")
        assert_eq(_make_affiliation("", "Fiji"), "Fiji", context="country only")
        assert_eq(_make_affiliation(".", "New Zealand"), "New Zealand", context="placeholder org")

    def test_canonical_for_parts_includes_country(self, assert_eq):
        label = canonical_for_parts("University of Auckland", "New Zealand")
        assert "Auckland" in label or "auckland" in label.casefold(), (
            f"expected Auckland in canonical label, got {label!r}"
        )


class TestOrgRedirects:
    def test_clean_review_value(self, assert_eq):
        assert_eq(_clean_review_value("nan"), "", context="nan → empty")
        assert_eq(_clean_review_value("None"), "", context="None → empty")
        assert_eq(_clean_review_value("  KAUST  "), "KAUST", context="strip")

    def test_build_and_resolve_redirects(self, assert_eq):
        reviews = pd.DataFrame(
            [
                {
                    "organisation": "AIMS / University Partner",
                    "canonical_affiliation": "AIMS / University Partner, Australia",
                    "primary organisation": "Australian Institute of Marine Science",
                    "secondary organisation": "University Partner",
                    "country": "Australia",
                },
                {
                    "organisation": "Solo Org",
                    "canonical_affiliation": "Solo Org, Fiji",
                    "primary organisation": "",
                    "secondary organisation": "",
                    "country": "Fiji",
                },
            ]
        )
        redirects = _build_org_redirects(reviews)
        assert redirects, f"expected redirects from compound review, got {redirects!r}"

        primary, country = _resolve_attendee_org_country(
            "AIMS / University Partner",
            "Australia",
            redirects,
        )
        assert_eq(
            primary,
            "Australian Institute of Marine Science",
            context="compound redirect primary",
        )
        assert_eq(country, "Australia", context="compound redirect country")

        unchanged_org, unchanged_country = _resolve_attendee_org_country(
            "Solo Org",
            "Fiji",
            redirects,
        )
        assert_eq(unchanged_org, "Solo Org", context="non-compound unchanged")
        assert_eq(unchanged_country, "Fiji", context="non-compound country")

    def test_substring_compound_redirect(self, assert_eq):
        reviews = pd.DataFrame(
            [
                {
                    "organisation": "Parent / Child Lab",
                    "canonical_affiliation": "Parent / Child Lab, USA",
                    "primary organisation": "Parent Institute",
                    "secondary organisation": "Child Lab",
                    "country": "United States",
                }
            ]
        )
        redirects = _build_org_redirects(reviews)
        primary, country = _resolve_attendee_org_country(
            "Parent / Child Lab Extra Detail",
            "United States",
            redirects,
        )
        assert_eq(primary, "Parent Institute", context="substring redirect")
        assert_eq(country, "United States", context="substring redirect country")


class TestAffiliationRegistryOverrides:
    def test_missing_file_returns_empty_frame(self, tmp_path, assert_eq):
        frame = load_registry_overrides(tmp_path / "missing.csv")
        assert_eq(list(frame.columns), ["action", "left", "right", "canonical_affiliation", "notes"])
        assert_eq(len(frame), 0, context="missing overrides empty")

    def test_load_merge_override_rows(self, tmp_path, assert_eq):
        path = tmp_path / "affiliation_registry_overrides.csv"
        path.write_text(
            "action,left,right,canonical_affiliation,notes\n"
            'merge,Org A|australia,Org B|australia,"Org B, Australia",joined\n',
            encoding="utf-8",
        )
        frame = load_registry_overrides(path)
        assert_eq(len(frame), 1, context="one override row")
        assert_eq(str(frame.iloc[0]["action"]), "merge", context="action")
        assert_eq(str(frame.iloc[0]["left"]), "Org A|australia", context="left key")
        assert_eq(
            str(frame.iloc[0]["canonical_affiliation"]),
            "Org B, Australia",
            context="quoted canonical affiliation",
        )


class TestAffiliationIndex:
    def _index(self) -> AffiliationIndex:
        registry = pd.DataFrame(
            [
                {
                    "affiliation_key": "icrs-a-00001",
                    "organisation": "Primary Institute",
                    "country": "Australia",
                    "canonical_affiliation": "Primary Institute, Australia",
                    "name_variants": "Primary Institute, Australia; Primary Institute",
                    "redirect_to_affiliation_key": "",
                    "geocode_status": "ok",
                    "geocode_source": "geocode_csv",
                    "latitude": -16.9,
                    "longitude": 145.7,
                    "plot_on_map": "true",
                },
                {
                    "affiliation_key": "icrs-a-00002",
                    "organisation": "Secondary Compound",
                    "country": "Australia",
                    "canonical_affiliation": "Secondary Compound, Australia",
                    "name_variants": "Secondary Compound, Australia",
                    "redirect_to_affiliation_key": "icrs-a-00001",
                    "geocode_status": "ok",
                    "geocode_source": "geocode_csv",
                    "latitude": -16.9,
                    "longitude": 145.7,
                    "plot_on_map": "false",
                },
                {
                    "affiliation_key": "icrs-a-00003",
                    "organisation": "Capital Anchor Org",
                    "country": "Fiji",
                    "canonical_affiliation": "Capital Anchor Org, Fiji",
                    "name_variants": "Capital Anchor Org, Fiji",
                    "redirect_to_affiliation_key": "",
                    "geocode_status": "fallback",
                    "geocode_source": "capital_fallback",
                    "latitude": -18.1,
                    "longitude": 178.4,
                    "plot_on_map": "true",
                },
            ]
        )
        aliases = pd.DataFrame(
            [
                {
                    "affiliation_key": "icrs-a-00001",
                    "group_key": group_key("Alias Org", "Australia"),
                    "affiliation_variant": "Alias Org, Australia",
                }
            ]
        )
        return AffiliationIndex.from_frames(registry, aliases)

    def test_resolve_key_and_follow_redirect(self, assert_eq):
        index = self._index()
        assert_eq(
            index.resolve_key("Primary Institute", "Australia"),
            "icrs-a-00001",
            context="direct resolve",
        )
        assert_eq(
            index.follow_redirect("icrs-a-00002"),
            "icrs-a-00001",
            context="redirect follow",
        )
        assert_eq(
            index.resolve_key("Secondary Compound", "Australia"),
            "icrs-a-00001",
            context="resolve follows redirect",
        )
        assert_eq(
            index.resolve_key("Alias Org", "Australia"),
            "icrs-a-00001",
            context="alias group_key resolve",
        )
        assert_eq(
            index.resolve_key("Unknown Org", "Mars"),
            "",
            context="unknown org",
        )

    def test_plot_on_map_and_geocode_hit(self, assert_eq):
        index = self._index()
        assert index.plot_on_map("Primary Institute", "Australia") is True
        assert index.plot_on_map("Secondary Compound", "Australia") is True  # via redirect to primary
        assert index.is_geocoded("Capital Anchor Org", "Fiji") is True

        hit = registry_geocode_hit("Capital Anchor Org", "Fiji", index=index)
        assert hit is not None, "expected capital-fallback geocode hit"
        assert_eq(hit["geocode_level"], "country", context="capital fallback level")
        assert "registry:icrs-a-00003" in str(hit["query_used"]), (
            f"unexpected query_used: {hit['query_used']!r}"
        )

        missing = registry_geocode_hit("No Such Org", "Fiji", index=index)
        assert missing is None, f"expected None for missing org, got {missing!r}"

    def test_lookup_affiliation_key_wrapper(self, assert_eq):
        index = self._index()
        assert_eq(
            lookup_affiliation_key("Primary Institute", "Australia", index=index),
            "icrs-a-00001",
            context="lookup wrapper",
        )
