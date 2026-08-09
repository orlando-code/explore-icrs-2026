from src.sources.delegates import (
    canonical_person_name,
    delegate_person_key,
    normalize_person_name,
)


def test_talk_and_delegate_middle_initial_share_person_key():
    talk_name = "Ashtyn Isaak"
    delegate_name = "Ashtyn L. Isaak"

    assert delegate_person_key(talk_name) == delegate_person_key(delegate_name)
    assert canonical_person_name(delegate_name) == talk_name
    assert canonical_person_name(talk_name) == talk_name


def test_delegate_only_name_uses_delegate_spelling():
    from src.sources.delegates import load_delegates

    delegates = load_delegates()
    non_speaker = delegates.loc[~delegates["is_speaker"]].iloc[0]
    delegate_name = str(non_speaker["full_name"])
    person_key = delegate_person_key(delegate_name)
    from src.registry.key_resolution import get_registry_key_resolver

    canonical = get_registry_key_resolver().canonical_name(person_key, fallback=delegate_name)

    assert person_key
    assert canonical == delegate_name


def test_id_review_names_share_registry_person_key():
    talk_name = "Hamzah Abdel Majid"
    delegate_name = "Hamzah Abdel-Majid"

    talk_key = delegate_person_key(talk_name)
    delegate_key = delegate_person_key(delegate_name)
    assert talk_key == delegate_key
    assert talk_key.startswith("icrs-p-")


def test_shared_surname_does_not_merge_distinct_burts():
    import src.sources.delegates as delegates_module
    from src.registry.key_resolution import clear_registry_key_resolver_cache

    clear_registry_key_resolver_cache()

    john_key = delegate_person_key("Prof John Burt")
    nicole_key = delegate_person_key("Nicole Burt")

    assert john_key != nicole_key
    assert john_key.startswith("icrs-p-")
    assert nicole_key.startswith("icrs-p-")
    assert canonical_person_name("Prof John Burt") == "Prof John Burt"
    assert canonical_person_name("Nicole Burt") == "Nicole Burt"


def test_takashi_nakamura_homonyms_stay_distinct():
    from src.registry.key_resolution import clear_registry_key_resolver_cache

    clear_registry_key_resolver_cache()

    ryukyus_key = delegate_person_key(
        "Takashi Nakamura",
        affiliation="University of the Ryukyus, Japan",
    )
    tokyo_key = delegate_person_key(
        "Takashi Nakamura",
        affiliation="Institute of Science - Tokyo, Japan",
    )

    assert ryukyus_key != tokyo_key
    assert ryukyus_key.startswith("icrs-p-")
    assert tokyo_key.startswith("icrs-p-")


def test_takashi_nakamura_talk_titles_split_by_person_key():
    from src.registry.key_resolution import clear_registry_key_resolver_cache

    from src.registry.registry_export import build_map_talks
    from src.site.plot_utils import _build_talk_title_index

    clear_registry_key_resolver_cache()

    talks = build_map_talks()
    index = _build_talk_title_index(talks)
    ryukyus_key = delegate_person_key(
        "Takashi Nakamura",
        affiliation="University of the Ryukyus, Japan",
    )
    tokyo_key = delegate_person_key(
        "Takashi Nakamura",
        affiliation="Institute of Science - Tokyo, Japan",
    )
    ryukyus_titles = {item["title"] for item in index.get(ryukyus_key, [])}
    tokyo_titles = {item["title"] for item in index.get(tokyo_key, [])}

    assert ryukyus_titles != tokyo_titles
    assert (
        "Potential shifts in Acropora corals' resilience under repeated bleaching events in Sekisei Lagoon, southern Japan"
        in ryukyus_titles
    )
    assert (
        "An Integrated Modeling System for Projecting Coral Community Succession Induced by Future Climate Change"
        in tokyo_titles
    )
    assert (
        "An Integrated Modeling System for Projecting Coral Community Succession Induced by Future Climate Change"
        not in ryukyus_titles
    )


def test_emissions_attendees_keep_takashi_nakamura_homonyms():
    import pandas as pd

    from src.emissions.travel_emissions import (
        _build_emissions_attendees,
        _emissions_location_key,
    )

    legs = pd.DataFrame(
        [
            {
                "presenter": "Takashi Nakamura",
                "affiliation": "University of the Ryukyus, Japan",
                "latitude": 26.251687,
                "longitude": 127.768408,
            },
            {
                "presenter": "Takashi Nakamura",
                "affiliation": "Institute of Science - Tokyo, Japan",
                "latitude": 35.605902,
                "longitude": 139.683560,
            },
        ]
    )
    estimates = legs[["presenter", "affiliation"]].copy()
    estimates["co2e_kg"] = [2191.8, 2255.6]
    estimates["origin_country"] = "JP"
    key_to_id = {
        _emissions_location_key("University of the Ryukyus, Japan"): "emis-ryu",
        _emissions_location_key("Institute of Science - Tokyo, Japan"): "emis-tok",
    }
    attendees = _build_emissions_attendees(
        estimates, legs, key_to_id, country_to_cluster={}
    )
    takashi = [row for row in attendees if "nakamura" in row["name"].casefold()]

    assert len(takashi) == 2
    assert len({row["person_key"] for row in takashi}) == 2
    assert {row["affiliation"] for row in takashi} == {
        "University of the Ryukyus",
        "Institute of Science - Tokyo",
    }


def test_enrich_talks_assigns_registry_keys():
    from src.registry.key_resolution import clear_registry_key_resolver_cache, enrich_talks_with_registry_keys
    from src.sources.programme import load_talks

    clear_registry_key_resolver_cache()
    talks = load_talks()
    enriched = enrich_talks_with_registry_keys(talks)
    assert "person_key" in enriched.columns
    assert "affiliation_key" in enriched.columns
    takashi = enriched.loc[
        enriched["presenter"].astype(str).str.contains("Takashi Nakamura", na=False)
    ]
    keys = set(takashi["person_key"].astype(str).str.strip()) - {""}
    assert len(keys) == 2


def test_names_likely_same_person_matches_nicknames():
    from src.sources.delegates import names_likely_same_person

    assert names_likely_same_person("Dr Alex Van Nynatten", "Alexander Van Nynatten")
    assert not names_likely_same_person("Prof John Burt", "Nicole Burt")


def test_programme_nickname_resolves_to_attended_delegate(built_person_registry):
    from src.registry.key_resolution import RegistryKeyResolver, clear_registry_key_resolver_cache

    clear_registry_key_resolver_cache()
    resolver = RegistryKeyResolver(
        people=built_person_registry.registry,
        aliases=built_person_registry.aliases,
    )
    person_key = resolver.resolve_person_key(
        "Alexander Van Nynatten",
        affiliation="University of Victoria",
    )
    assert person_key.startswith("icrs-p-")
    attended = str(resolver.people_by_key[person_key].get("attended") or "").lower()
    assert attended in {"true", "1", "yes"}


def test_all_programme_talks_resolve_person_keys(built_person_registry):
    from src.registry.key_resolution import (
        RegistryKeyResolver,
        clear_registry_key_resolver_cache,
        enrich_talks_with_registry_keys,
    )
    from src.sources.programme import load_talks

    clear_registry_key_resolver_cache()
    resolver = RegistryKeyResolver(
        people=built_person_registry.registry,
        aliases=built_person_registry.aliases,
    )
    enriched = enrich_talks_with_registry_keys(load_talks(), resolver=resolver)
    missing = enriched.loc[
        ~enriched["person_key"].astype(str).str.strip().str.startswith("icrs-p-")
    ]
    assert missing.empty, sorted(missing["presenter"].unique())[:10]
