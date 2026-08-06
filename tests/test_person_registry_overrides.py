"""Unit tests for person-registry overrides and official-ID matching helpers."""

from __future__ import annotations

import pandas as pd
import pytest

from src.registry.person_registry import (
    _apply_registry_overrides,
    _clean_official_id,
    _match_presenter_norm,
    _official_id_priority,
    load_registry_overrides,
    lookup_person_key,
)
from src.sources.delegates import _UnionFind, name_tokens, normalize_person_name


class TestOfficialIdHelpers:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("17228", "17228"),
            ("17228.0", "17228"),
            ("", ""),
            ("nan", ""),
            (None, ""),
        ],
    )
    def test_clean_official_id(self, value, expected, assert_eq):
        assert_eq(_clean_official_id(value), expected, context=f"clean {value!r}")

    @pytest.mark.parametrize(
        "tier,reason,expected",
        [
            ("perfect", "", 1),
            ("confirmed", "", 2),
            ("confirmed", "manually_confirmed", 3),
            ("perfect", "manually_confirmed", 3),
            ("fuzzy", "", 0),
            ("", "", 0),
        ],
    )
    def test_official_id_priority(self, tier, reason, expected, assert_eq):
        assert_eq(
            _official_id_priority(tier, reason),
            expected,
            context=f"priority({tier!r}, {reason!r})",
        )


class TestMatchPresenterNorm:
    def test_accepts_subset_token_match(self, assert_eq):
        token_index = {
            "ashtyn": {"ashtyn isaak"},
            "isaak": {"ashtyn isaak"},
        }
        presenter_display = {"ashtyn isaak": "Ashtyn Isaak"}
        matched = _match_presenter_norm(
            "Ashtyn L. Isaak",
            token_index,
            presenter_display,
        )
        assert_eq(matched, "ashtyn isaak", context="middle-initial subset match")

    def test_rejects_presenter_with_more_tokens(self, assert_eq):
        """Sam King must not merge into Sam King Fung Yiu."""
        token_index = {
            "sam": {"sam king fung yiu"},
            "king": {"sam king fung yiu"},
            "fung": {"sam king fung yiu"},
            "yiu": {"sam king fung yiu"},
        }
        presenter_display = {"sam king fung yiu": "Sam King Fung Yiu"}
        matched = _match_presenter_norm("Sam King", token_index, presenter_display)
        assert matched is None, (
            f"expected no match for shorter delegate name, got {matched!r}; "
            f"delegate_tokens={name_tokens('Sam King')}, "
            f"presenter_tokens={name_tokens('Sam King Fung Yiu')}"
        )

    def test_no_match_when_tokens_missing(self, assert_eq):
        token_index = {"alice": {"alice example"}}
        presenter_display = {"alice example": "Alice Example"}
        matched = _match_presenter_norm("Bob Example", token_index, presenter_display)
        assert matched is None, f"unexpected match: {matched!r}"


class TestPersonRegistryOverrides:
    def test_missing_overrides_file(self, tmp_path, assert_eq):
        frame = load_registry_overrides(tmp_path / "missing.csv")
        assert_eq(
            list(frame.columns),
            ["action", "left", "right", "canonical_name", "notes"],
        )
        assert_eq(len(frame), 0, context="empty overrides")

    def test_load_and_apply_merge_override(self, tmp_path, assert_eq):
        path = tmp_path / "person_registry_overrides.csv"
        path.write_text(
            "action,left,right,canonical_name,notes\n"
            "merge,Alice Example,Alicia Example,Alice Example,same person\n"
            "split,John Burt,Nicole Burt,,keep distinct\n"
            "merge,,,should skip,missing names\n",
            encoding="utf-8",
        )
        overrides = load_registry_overrides(path)
        assert_eq(len(overrides), 3, context="loaded override rows")

        uf = _UnionFind()
        key_to_canonical: dict[str, str] = {}
        left = normalize_person_name("Alice Example")
        right = normalize_person_name("Alicia Example")
        uf.find(left)
        uf.find(right)
        assert uf.find(left) != uf.find(right), "precondition: names not yet united"

        _apply_registry_overrides(
            uf,
            overrides,
            presenter_display={},
            delegate_display={},
            key_to_canonical=key_to_canonical,
        )
        assert_eq(
            uf.find(left),
            uf.find(right),
            context="merge override united names",
        )
        assert_eq(
            key_to_canonical[left],
            "Alice Example",
            context="canonical_name from merge override",
        )
        assert_eq(
            key_to_canonical[right],
            "Alice Example",
            context="canonical_name on both sides",
        )

        # Split is documentation-only — no error, no union change for Burt pair.
        john = normalize_person_name("John Burt")
        nicole = normalize_person_name("Nicole Burt")
        uf.find(john)
        uf.find(nicole)
        assert uf.find(john) != uf.find(nicole), (
            f"split action must not union names; john={uf.find(john)!r} "
            f"nicole={uf.find(nicole)!r}"
        )


class TestLookupPersonKey:
    def test_lookup_from_aliases_frame(self, assert_eq):
        aliases = pd.DataFrame(
            [
                {
                    "normalized_name": "alice example",
                    "name_variant": "Alice Example",
                    "person_key": "icrs-p-00001",
                },
                {
                    "normalized_name": "alicia example",
                    "name_variant": "Alicia Example",
                    "person_key": "icrs-p-00001",
                },
            ]
        )
        assert_eq(
            lookup_person_key("Alice Example", aliases=aliases),
            "icrs-p-00001",
            context="alias lookup",
        )
        assert_eq(
            lookup_person_key("Unknown Person", aliases=aliases),
            "",
            context="missing alias",
        )
