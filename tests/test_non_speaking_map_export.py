"""Non-presenting delegates stay on map/emissions paths but not as programme speakers."""

from __future__ import annotations

import pandas as pd

from src.registry.key_resolution import clear_registry_key_resolver_cache
from src.registry.registry_export import build_map_talks
from src.site.plot_utils import (
    _affiliation_location_records,
    _build_network_data,
    _programme_map_frame,
)


def _vavia_row(registry):
    rows = registry.loc[registry["canonical_name"].astype(str).str.contains("Vavia", case=False)]
    assert len(rows) == 1, rows
    return rows.iloc[0]


def test_ant_vavia_is_attended_only_not_programme(built_person_registry):
    clear_registry_key_resolver_cache()
    row = _vavia_row(built_person_registry.registry)
    assert str(row["attended"]).lower() in {"true", "1", "yes"}
    assert str(row["is_speaker"]).lower() in {"false", "0", ""}
    assert str(row["in_programme"]).lower() in {"false", "0", ""}

    aliases = built_person_registry.aliases
    antony = aliases.loc[aliases["normalized_name"].eq("antony vavia")]
    ant = aliases.loc[aliases["normalized_name"].eq("ant vavia")]
    assert not antony.empty
    assert set(antony["source"]) == {"official_id"}
    assert not ant.empty
    assert set(ant["source"]) == {"delegate_list"}


def test_attended_only_rows_excluded_from_map_and_network(built_person_registry):
    clear_registry_key_resolver_cache()
    person_key = str(_vavia_row(built_person_registry.registry)["person_key"])
    talks = build_map_talks()
    assert "attended_only" in talks.columns

    vavia = talks.loc[talks["person_key"].astype(str).eq(person_key)]
    assert len(vavia) == 1
    assert bool(vavia.iloc[0]["attended_only"]) is True

    programme = _programme_map_frame(talks)
    assert programme.loc[programme["person_key"].astype(str).eq(person_key)].empty

    locations = _affiliation_location_records(programme)
    assert not any(
        "Ocean Toa" in str(location.get("affiliation") or "") for location in locations
    )
    assert not any(
        any(
            str(speaker.get("person_key") or "") == person_key
            for speaker in location.get("speaker_details") or []
        )
        for location in locations
    )

    network = _build_network_data(programme, locations)
    assert not any(
        str(node.get("person_key") or "") == person_key
        for node in network["individual"]["nodes"]
    )


def test_programme_coauthors_remain_in_network_without_presenter_role():
    clear_registry_key_resolver_cache()
    frame = pd.DataFrame(
        [
            {
                "presenter": "Example Talk Presenter",
                "affiliation": "Example Institute, New Zealand",
                "authors": ["Example Talk Presenter", "Example Coauthor NonSpeaker"],
                "title": "Example talk for co-author network",
                "abstract": "",
                "talk_id": "test-talk-coauthor-1",
                "person_key": "icrs-p-test-presenter",
                "attended_only": False,
                "latitude": -36.85,
                "longitude": 174.76,
                "geocode_level": "institute",
            }
        ]
    )
    locations = _affiliation_location_records(frame)
    network = _build_network_data(frame, locations)
    nodes = {
        str(node.get("label") or ""): node for node in network["individual"]["nodes"]
    }
    assert "Example Coauthor NonSpeaker" in nodes
    assert nodes["Example Coauthor NonSpeaker"]["author_role"] == "co_author"
    assert not nodes["Example Coauthor NonSpeaker"]["affiliation"]
    assert nodes["Example Coauthor NonSpeaker"]["affiliation_explicit"] is False
    assert "Example Talk Presenter" in nodes
    # Unmapped presenters are still network nodes via the author list.
    assert nodes["Example Talk Presenter"]["connections"] >= 1
