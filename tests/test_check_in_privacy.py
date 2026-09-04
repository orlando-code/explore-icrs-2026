"""Tests for check-in privacy and EX-TRUE release handling."""

from __future__ import annotations

import pandas as pd
import pytest

from src.registry.check_in_attendance import (
    _display_name_from_check_in,
    _is_privacy_released,
    _is_privacy_restricted,
    apply_check_in_attendance,
    load_check_in_attendees,
    resolve_check_in_delegates_path,
)


class TestPrivacyFlags:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("TRUE", True),
            ("true", True),
            ("FALSE", False),
            ("EX-TRUE", False),
            ("ex-true", False),
        ],
    )
    def test_is_privacy_restricted(self, value, expected, assert_eq):
        assert_eq(_is_privacy_restricted(value), expected, context=f"privacy={value!r}")

    def test_is_privacy_released(self, assert_eq):
        assert_eq(_is_privacy_released("EX-TRUE"), True)
        assert_eq(_is_privacy_released("TRUE"), False)


class TestDisplayNameFromCheckIn:
    def test_privacy_first_name_only(self, assert_eq):
        row = pd.Series({"first name": "Theresa", "last name": "", "privacy": "TRUE"})
        assert_eq(_display_name_from_check_in(row), "Theresa")

    def test_ex_true_uses_surname(self, assert_eq):
        row = pd.Series(
            {
                "first name": "Theresa",
                "last name": "Rueger",
                "privacy": "EX-TRUE",
            }
        )
        assert_eq(_display_name_from_check_in(row), "Theresa Rueger")


class TestEditableCheckInPath:
    def test_prefers_editable_when_present(self, tmp_path, assert_eq):
        default = tmp_path / "default.csv"
        editable = tmp_path / "editable.csv"
        default.write_text("ID,first name,last name,privacy,organisation,country\n", encoding="utf-8")
        editable.write_text("ID,first name,last name,privacy,organisation,country\n", encoding="utf-8")
        resolved = resolve_check_in_delegates_path(
            editable_path=editable,
            default_path=default,
        )
        assert_eq(resolved, editable)

    def test_falls_back_to_default(self, tmp_path, assert_eq):
        default = tmp_path / "default.csv"
        editable = tmp_path / "editable.csv"
        default.write_text("ID,first name,last name,privacy,organisation,country\n", encoding="utf-8")
        resolved = resolve_check_in_delegates_path(
            editable_path=editable,
            default_path=default,
        )
        assert_eq(resolved, default)


class TestApplyCheckInPrivacyRelease:
    def test_ex_true_clears_privacy_and_updates_name(self, tmp_path, assert_eq):
        check_in = tmp_path / "check_in.csv"
        check_in.write_text(
            "ID,first name,last name,privacy,organisation,country\n"
            "18291,Theresa,Rueger,EX-TRUE,Newcastle University,United Kingdom\n",
            encoding="utf-8",
        )
        registry = pd.DataFrame(
            [
                {
                    "person_key": "icrs-p-09999",
                    "canonical_name": "Theresa",
                    "organisation": "Newcastle University",
                    "country": "United Kingdom",
                    "in_delegate_list": False,
                    "in_programme": False,
                    "attended": False,
                    "is_speaker": False,
                    "name_variants": "Theresa",
                    "needs_review": True,
                    "review_reason": "check_in_only_not_in_registry",
                }
            ]
        )
        aliases = pd.DataFrame(columns=["person_key", "name_variant", "normalized_name", "source"])
        official_ids = tmp_path / "official_ids.csv"
        official_ids.write_text("person_key,official_delegate_id\n", encoding="utf-8")

        updated, updated_aliases, metrics = apply_check_in_attendance(
            registry,
            aliases,
            check_in_path=check_in,
            official_ids_path=official_ids,
        )
        person = updated.loc[updated["person_key"].eq("icrs-p-09999")].iloc[0]
        assert_eq(person["canonical_name"], "Theresa Rueger", context="canonical name updated")
        assert_eq(str(person["privacy_restricted"]).lower(), "false", context="privacy cleared")
        assert_eq(metrics["privacy_released_attendees"], 1)
        assert "theresa rueger" in set(updated_aliases["normalized_name"].astype(str))

    def test_check_in_overrides_delegate_list_affiliation(self, tmp_path, assert_eq):
        check_in = tmp_path / "check_in.csv"
        check_in.write_text(
            "ID,first name,last name,privacy,organisation,country\n"
            "17604,Julian,Lilkendey,FALSE,Auckland University of Technology (AUT),New Zealand\n",
            encoding="utf-8",
        )
        registry = pd.DataFrame(
            [
                {
                    "person_key": "icrs-p-01022",
                    "canonical_name": "Dr Julian Lilkendey",
                    "organisation": "Leibniz Centre for Tropical Marine Research",
                    "country": "New Zealand",
                    "in_delegate_list": True,
                    "in_programme": True,
                    "attended": False,
                    "is_speaker": True,
                    "name_variants": "Dr Julian Lilkendey",
                    "needs_review": False,
                    "review_reason": "",
                }
            ]
        )
        aliases = pd.DataFrame(columns=["person_key", "name_variant", "normalized_name", "source"])
        official_ids = tmp_path / "official_ids.csv"
        official_ids.write_text(
            "person_key,official_delegate_id\nicrs-p-01022,17604\n",
            encoding="utf-8",
        )

        updated, _, metrics = apply_check_in_attendance(
            registry,
            aliases,
            check_in_path=check_in,
            official_ids_path=official_ids,
        )
        person = updated.loc[updated["person_key"].eq("icrs-p-01022")].iloc[0]
        assert_eq(person["organisation"], "Auckland University of Technology (AUT)")
        assert_eq(str(person["checked_in"]).lower(), "true")
        assert_eq(metrics["check_in_matched"], 1)

    def test_delegate_country_override_wins_over_check_in_nationality(self, tmp_path, assert_eq):
        check_in = tmp_path / "check_in.csv"
        check_in.write_text(
            "ID,first name,last name,privacy,organisation,country\n"
            "11043,Novia,Kayfetz-Vuong,FALSE,Lingnan University,United States\n",
            encoding="utf-8",
        )
        registry = pd.DataFrame(
            [
                {
                    "person_key": "icrs-p-00891",
                    "canonical_name": "Novia Kayfetz-Vuong",
                    "organisation": "Lingnan University",
                    "country": "United States",
                    "in_delegate_list": True,
                    "in_programme": True,
                    "attended": False,
                    "is_speaker": True,
                    "name_variants": "Novia Kayfetz-Vuong",
                    "needs_review": False,
                    "review_reason": "",
                }
            ]
        )
        aliases = pd.DataFrame(columns=["person_key", "name_variant", "normalized_name", "source"])
        official_ids = tmp_path / "official_ids.csv"
        official_ids.write_text(
            "person_key,official_delegate_id\nicrs-p-00891,11043\n",
            encoding="utf-8",
        )

        updated, _, metrics = apply_check_in_attendance(
            registry,
            aliases,
            check_in_path=check_in,
            official_ids_path=official_ids,
        )
        person = updated.loc[updated["person_key"].eq("icrs-p-00891")].iloc[0]
        assert_eq(person["organisation"], "Lingnan University")
        assert_eq(person["country"], "Hong Kong")
        assert_eq(metrics["check_in_matched"], 1)

    def test_placeholder_organisation_affiliation_is_country_only(self, assert_eq):
        from src.registry.affiliation_registry import _make_affiliation
        from src.sources.delegates import delegate_affiliation_for_row

        assert_eq(_make_affiliation(".", "New Zealand"), "New Zealand")
        row = pd.Series(
            {
                "organisation": ".",
                "country": "New Zealand",
                "first_name": "Georgina",
                "last_name": "Nicholson",
                "full_name": "Dr Georgina Nicholson",
            }
        )
        assert_eq(delegate_affiliation_for_row(row), "New Zealand")
