"""Unit tests for delegate organisation overrides and PDF sanitisation helpers."""

from __future__ import annotations

import pandas as pd
import pytest

from src.sources.delegates import (
    country_override_for_row,
    country_to_iso2,
    delegate_affiliation_for_row,
    delegate_country_for_row,
    infer_country_from_organisation,
    is_incomplete_organisation,
    load_organisation_overrides,
    normalize_person_name,
    organisation_for_delegate_row,
    organisation_override_for_row,
    repair_mojibake,
    sanitize_delegate_organisation,
    _country_is_incomplete,
    _match_country_label,
    _merge_wrapped_country,
    _ORGANISATION_COUNTRY_OVERRIDES,
)


class TestNormalizePersonName:
    def test_strips_titles_and_punctuation(self, assert_eq):
        assert_eq(
            normalize_person_name("Prof. John Burt"),
            "john burt",
            context="title strip",
        )
        assert_eq(
            normalize_person_name("Hamzah Abdel-Majid"),
            "hamzah abdel majid",
            context="hyphen fold",
        )
        assert_eq(
            normalize_person_name("  Dr Jane   Doe  "),
            "jane doe",
            context="whitespace collapse",
        )


class TestIncompleteOrganisation:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("", True),
            ("nan", True),
            ("National", True),
            ("University of", True),
            ("University of the", True),
            ("University of Southern", True),
            ("University of Western", True),
            ("Something /", True),
            ("Institute of", True),
            ("Australian Institute of Marine Science", False),
            ("KAUST", False),
            ("University of Auckland", False),
        ],
    )
    def test_incomplete_heuristics(self, name, expected, assert_eq):
        actual = is_incomplete_organisation(name)
        assert_eq(
            actual,
            expected,
            context=f"is_incomplete_organisation({name!r})",
        )


class TestSanitizeDelegateOrganisation:
    def test_strips_title_bleed_suffix(self, assert_eq):
        raw = "Australian Institute of Marine Science Dr Jane Smith"
        cleaned = sanitize_delegate_organisation(
            raw, first_name="Jane", last_name="Smith"
        )
        assert_eq(
            cleaned,
            "Australian Institute of Marine Science",
            context="title-bleed strip",
        )

    def test_splits_multi_space_pdf_bleed(self, assert_eq):
        # Use an org-hint token so the person/country segments are dropped, not the org.
        raw = "Australian Institute of Marine Science    Jane Doe    Australia"
        cleaned = sanitize_delegate_organisation(
            raw,
            first_name="Jane",
            last_name="Doe",
            country="Australia",
        )
        assert_eq(
            cleaned,
            "Australian Institute of Marine Science",
            context="multi-space PDF bleed",
        )

    def test_keeps_complete_org_unchanged(self, assert_eq):
        org = "University of Auckland"
        assert_eq(
            sanitize_delegate_organisation(org),
            org,
            context="complete org passthrough",
        )

    def test_empty_returns_empty(self, assert_eq):
        assert_eq(sanitize_delegate_organisation(""), "", context="empty org")
        assert_eq(sanitize_delegate_organisation("   "), "", context="whitespace org")


class TestOrganisationOverrides:
    def test_load_overrides_from_temp_csv(self, tmp_path, assert_eq):
        csv_path = tmp_path / "org_overrides.csv"
        csv_path.write_text(
            "full_name,organisation,country,notes\n"
            "Alice Example,Corrected Institute,Australia,manual\n"
            "Bob Example,Only Org,,org only\n"
            ",Should Skip,Fiji,missing name\n",
            encoding="utf-8",
        )
        overrides = load_organisation_overrides(csv_path)

        assert_eq(
            overrides[normalize_person_name("Alice Example")],
            ("Corrected Institute", "Australia"),
            context="alice override",
        )
        assert_eq(
            overrides["alice example"],
            ("Corrected Institute", "Australia"),
            context="alice casefold key",
        )
        assert_eq(
            overrides[normalize_person_name("Bob Example")],
            ("Only Org", ""),
            context="bob org-only override",
        )
        assert "should skip" not in overrides

    def test_override_lookup_by_full_name_and_presenter(self, tmp_path, monkeypatch, assert_eq):
        csv_path = tmp_path / "org_overrides.csv"
        csv_path.write_text(
            "full_name,organisation,country,notes\n"
            "Carol Example,Override Org,Fiji,note\n",
            encoding="utf-8",
        )
        import src.sources.delegates as delegates_module

        # Default-arg binding means path= must be injected via the loader/cache.
        loaded = load_organisation_overrides(csv_path)
        monkeypatch.setattr(
            delegates_module,
            "load_organisation_overrides",
            lambda path=csv_path: loaded,
        )

        row = {"full_name": "Carol Example", "organisation": "Wrong Org", "country": "Tonga"}
        assert_eq(
            organisation_override_for_row(row),
            "Override Org",
            context="organisation override",
        )
        assert_eq(
            country_override_for_row(row),
            "Fiji",
            context="country override",
        )
        assert_eq(
            organisation_for_delegate_row(row),
            "Override Org",
            context="override wins over PDF org",
        )
        assert_eq(
            delegate_country_for_row(row),
            "Fiji",
            context="country override wins",
        )
        assert_eq(
            delegate_affiliation_for_row(row),
            "Override Org, Fiji",
            context="affiliation uses overrides",
        )

        presenter_row = {"presenter": "Carol Example", "organisation": "Wrong", "country": "Tonga"}
        assert_eq(
            organisation_override_for_row(presenter_row),
            "Override Org",
            context="presenter-key override",
        )

    def test_apply_overrides_false_keeps_pdf_fields(self, tmp_path, monkeypatch, assert_eq):
        csv_path = tmp_path / "org_overrides.csv"
        csv_path.write_text(
            "full_name,organisation,country,notes\n"
            "Dana Example,Override Org,Fiji,note\n",
            encoding="utf-8",
        )
        import src.sources.delegates as delegates_module

        loaded = load_organisation_overrides(csv_path)
        monkeypatch.setattr(
            delegates_module,
            "load_organisation_overrides",
            lambda path=csv_path: loaded,
        )

        row = {
            "full_name": "Dana Example",
            "organisation": "PDF Org",
            "country": "Tonga",
            "first_name": "Dana",
            "last_name": "Example",
        }
        assert_eq(
            organisation_for_delegate_row(row, apply_overrides=False),
            "PDF Org",
            context="overrides disabled",
        )
        assert_eq(
            delegate_country_for_row(row, apply_overrides=False),
            "Tonga",
            context="country overrides disabled",
        )


class TestInferCountryFromOrganisation:
    @pytest.mark.parametrize(
        "organisation,expected",
        [
            ("KAUST", "Saudi Arabia"),
            ("Australian Institute of Marine Science", "Australia"),
            ("University of Auckland", "New Zealand"),
            ("University of Waikato Marine Lab", "New Zealand"),
            ("State of Hawai'i", "United States"),
            ("Division of Aquatic Resources - Hawaii", "United States"),
            ("Some Hawaii Reef Lab", "United States"),
            ("Australian Coral Society Chapter", "Australia"),
            ("Random Institute", ""),
            ("", ""),
        ],
    )
    def test_hardcoded_and_regex_inference(self, organisation, expected, assert_eq):
        assert_eq(
            infer_country_from_organisation(organisation),
            expected,
            context=f"infer_country_from_organisation({organisation!r})",
        )

    def test_override_table_keys_are_lowercase(self, assert_eq):
        for key in _ORGANISATION_COUNTRY_OVERRIDES:
            assert_eq(
                key,
                key.casefold(),
                context=f"override key must be casefolded: {key!r}",
            )


class TestCountryToIso2:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("United States", "US"),
            ("USA", "US"),
            ("South Korea", "KR"),
            ("Korea, Republic of", "KR"),
            ("United States Virgin Islands", "VI"),
            ("Sint Maarten", "SX"),
            ("Curaçao", "CW"),
            ("curacao", "CW"),
            ("Hong Kong", "HK"),
            ("", ""),
            ("Not A Real Country XYZ", ""),
        ],
    )
    def test_aliases_and_territories(self, name, expected, assert_eq):
        assert_eq(
            country_to_iso2(name),
            expected,
            context=f"country_to_iso2({name!r})",
        )


class TestCountryLabelParsing:
    def test_match_complete_country(self, assert_eq):
        label, incomplete = _match_country_label("Australia")
        assert_eq(label, "Australia", context="matched Australia")
        assert_eq(incomplete, False, context="Australia complete")

    def test_match_wrapped_prefix(self, assert_eq):
        label, incomplete = _match_country_label("Northern Mariana")
        assert_eq(label, "Northern Mariana Islands", context="Northern Mariana prefix")
        assert incomplete is True or _country_is_incomplete("Northern Mariana")

    def test_incomplete_special_cases(self, assert_eq):
        for fragment in (
            "Northern Mariana",
            "Micronesia (the",
            "Venezuela, Bolivarian",
            "Tanzania, United",
            "Bolivia, Plurinational",
        ):
            assert_eq(
                _country_is_incomplete(fragment),
                True,
                context=f"incomplete fragment {fragment!r}",
            )

    def test_merge_wrapped_country(self, assert_eq):
        merged = _merge_wrapped_country("Northern Mariana", "Islands")
        assert_eq(
            merged,
            "Northern Mariana Islands",
            context="wrapped Northern Mariana merge",
        )
        assert_eq(
            country_to_iso2(merged),
            "MP",
            context="merged Northern Mariana ISO2",
        )


class TestRepairMojibake:
    def test_passthrough_clean_text(self, assert_eq):
        assert_eq(repair_mojibake("plain text"), "plain text", context="clean passthrough")

    def test_empty(self, assert_eq):
        assert_eq(repair_mojibake(""), "", context="empty mojibake")


class TestDelegateSpeakerExport:
    def test_nickname_delegate_marked_speaker_via_registry(self, assert_eq):
        from src.sources.delegates import delegate_list_groups, load_delegates

        groups = delegate_list_groups(load_delegates())
        sassa = next(
            delegate
            for group in groups
            for delegate in group["delegates"]
            if delegate["name"] == "Sassa Jordan"
        )
        assert_eq(sassa["is_speaker"], True, context="registry-linked presenter")
        assert_eq(sassa["person_key"], "icrs-p-00866", context="person key")
