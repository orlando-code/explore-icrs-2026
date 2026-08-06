"""Unit tests for map exclusion parsing and emissions-pool filtering."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.site.map_exclusions import (
    MapExclusions,
    _parse_exclusion_line,
    filter_emissions_pool,
    is_map_excluded,
    is_map_excluded_affiliation,
    load_map_exclusions,
    map_talks_for_export,
)
from src.sources.delegates import normalize_person_name
from src.geocoding.geocode import canonical_affiliation_key


class TestParseExclusionLine:
    def test_name_and_comment_and_affiliation(self, assert_eq):
        names: set[str] = set()
        affiliations: set[str] = set()

        _parse_exclusion_line("# comment", names, affiliations)
        assert_eq(names, set(), context="comment ignored")
        assert_eq(affiliations, set(), context="comment affiliations")

        _parse_exclusion_line("", names, affiliations)
        assert_eq(names, set(), context="blank ignored")

        _parse_exclusion_line("Alice Example", names, affiliations)
        assert_eq(
            names,
            {normalize_person_name("Alice Example")},
            context="name exclusion",
        )

        _parse_exclusion_line("@Secret Lab, Fiji", names, affiliations)
        expected_aff = canonical_affiliation_key("Secret Lab, Fiji").casefold()
        assert expected_aff in affiliations, (
            f"expected affiliation key {expected_aff!r} in {affiliations!r}"
        )


class TestLoadMapExclusions:
    def test_txt_and_json_sources(self, tmp_path, assert_eq):
        txt = tmp_path / "map_excluded_names.txt"
        txt.write_text(
            "# header\n"
            "Bob Example\n"
            "@Hidden Org, Australia\n",
            encoding="utf-8",
        )
        json_path = tmp_path / "map_excluded_names.json"
        json_path.write_text(
            json.dumps(
                {
                    "names": ["Carol Example"],
                    "affiliations": ["Another Hidden, Fiji"],
                }
            ),
            encoding="utf-8",
        )

        exclusions = load_map_exclusions(txt, json_path=json_path)
        assert normalize_person_name("Bob Example") in exclusions.names
        assert normalize_person_name("Carol Example") in exclusions.names
        assert is_map_excluded("Bob Example", set(exclusions.names)) is True
        assert is_map_excluded("Not Excluded", set(exclusions.names)) is False
        assert is_map_excluded_affiliation(
            "Hidden Org, Australia", set(exclusions.affiliations)
        ) is True
        assert is_map_excluded_affiliation(
            "Visible Org, Fiji", set(exclusions.affiliations)
        ) is False


class TestMapTalksForExport:
    def test_drops_excluded_presenter_and_affiliation(self, assert_eq):
        talks = pd.DataFrame(
            [
                {"presenter": "Keep Me", "affiliation": "Visible Lab, Fiji", "title": "A"},
                {"presenter": "Drop Me", "affiliation": "Visible Lab, Fiji", "title": "B"},
                {"presenter": "Also Keep", "affiliation": "Hidden Lab, Fiji", "title": "C"},
            ]
        )
        exclusions = MapExclusions(
            names=frozenset({normalize_person_name("Drop Me")}),
            affiliations=frozenset(
                {canonical_affiliation_key("Hidden Lab, Fiji").casefold()}
            ),
        )
        kept = map_talks_for_export(talks, exclusions=exclusions)
        assert_eq(list(kept["presenter"]), ["Keep Me"], context="filtered presenters")
        assert_eq(list(kept["title"]), ["A"], context="filtered titles")


class TestFilterEmissionsPool:
    def test_removes_people_and_reaggregates(self, assert_eq):
        pool = {
            "meta": {
                "headline": {
                    "co2e_kg": 300.0,
                    "co2e_tonnes": 0.3,
                    "attendees_estimated": 3,
                }
            },
            "attendees": [
                {
                    "name": "Keep Me",
                    "affiliation": "Visible Lab, Fiji",
                    "location_id": "loc-1",
                    "co2e_kg": 100.0,
                },
                {
                    "name": "Drop Me",
                    "affiliation": "Visible Lab, Fiji",
                    "location_id": "loc-1",
                    "co2e_kg": 100.0,
                },
                {
                    "name": "Also Drop",
                    "affiliation": "Hidden Lab, Fiji",
                    "location_id": "loc-2",
                    "co2e_kg": 100.0,
                },
            ],
            "locations": [
                {
                    "id": "loc-1",
                    "affiliation": "Visible Lab, Fiji",
                    "co2e_kg": 200.0,
                    "travel_attendees": 2,
                },
                {
                    "id": "loc-2",
                    "affiliation": "Hidden Lab, Fiji",
                    "co2e_kg": 100.0,
                    "travel_attendees": 1,
                },
            ],
            "rankings": [],
        }
        exclusions = MapExclusions(
            names=frozenset({normalize_person_name("Drop Me")}),
            affiliations=frozenset(
                {canonical_affiliation_key("Hidden Lab, Fiji").casefold()}
            ),
        )
        filtered = filter_emissions_pool(pool, exclusions=exclusions)

        names = [row["name"] for row in filtered["attendees"]]
        assert_eq(names, ["Keep Me"], context="remaining attendees")
        assert_eq(len(filtered["locations"]), 1, context="one location left")
        assert_eq(filtered["locations"][0]["id"], "loc-1", context="kept location id")
        assert_eq(filtered["locations"][0]["co2e_kg"], 100.0, context="reaggregated co2e")
        assert_eq(
            filtered["locations"][0]["travel_attendees"],
            1,
            context="reaggregated attendees",
        )
        assert_eq(
            filtered["meta"]["headline"]["attendees_estimated"],
            1,
            context="headline attendees",
        )
        assert_eq(
            filtered["meta"]["headline"]["co2e_kg"],
            100.0,
            context="headline co2e",
        )

    def test_empty_exclusions_passthrough(self, assert_eq):
        pool = {"attendees": [{"name": "A"}], "locations": [], "meta": {}}
        filtered = filter_emissions_pool(
            pool,
            exclusions=MapExclusions(names=frozenset(), affiliations=frozenset()),
        )
        assert filtered is pool or filtered["attendees"] == pool["attendees"]
