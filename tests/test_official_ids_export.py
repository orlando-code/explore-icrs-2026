"""Tests for EX-TRUE delegate ID export."""

from __future__ import annotations

import pandas as pd

from src.registry.person_registry import official_ids_export_mask


def test_released_check_in_only_included_in_official_ids_export(assert_eq):
    registry = pd.DataFrame(
        [
            {
                "person_key": "icrs-p-00001",
                "canonical_name": "Pre Reg",
                "official_delegate_id": "1234",
                "official_id_match_tier": "confirmed",
                "privacy_restricted": "False",
            },
            {
                "person_key": "icrs-p-00002",
                "canonical_name": "Still Private",
                "official_delegate_id": "5678",
                "official_id_match_tier": "check_in_only",
                "privacy_restricted": "True",
            },
            {
                "person_key": "icrs-p-00003",
                "canonical_name": "Matias Gómez-Corrales",
                "official_delegate_id": "651",
                "official_id_match_tier": "check_in_only",
                "privacy_restricted": "False",
            },
        ]
    )
    mask = official_ids_export_mask(registry)
    exported = registry.loc[mask, "person_key"].tolist()
    assert_eq(exported, ["icrs-p-00001", "icrs-p-00003"])
