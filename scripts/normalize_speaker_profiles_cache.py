#!/usr/bin/env python3
"""Normalize speaker_profiles_cache.json and set verified fields."""

from __future__ import annotations

import json
import re
import shutil
import sys
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.speaker_profiles import conservative_clean_profile, normalize_linkedin_links_in_profile

CACHE_PATH = PROJECT_ROOT / "data" / "speaker_profiles_cache.json"
MIN_EMAIL_SCORE = 0.72
_TITLE_PREFIX_RE = re.compile(
    r"^(?:dr|prof|professor|mr|mrs|ms|miss)\.?\s+",
    flags=re.IGNORECASE,
)
_GENERIC_EMAIL_LOCAL_RE = re.compile(
    r"^(?:info|contact|webmaster|admin|press|media|office|enquiries|onlineredaktion|"
    r"caseadvising|case|help|support|hello|team|news|pcn|editorial|partnerships|"
    r"healthcare_initiative)(?:[._-]|$)",
    re.IGNORECASE,
)
_OBVIOUS_JUNK_EMAIL_RE = re.compile(
    r"(?:%{|\.png|\.jpg|\.gif|\.svg|spokeo|beenverified|sharathyoga|dailygalaxy|"
    r"faisalman|travelandtourworld|schema\.org|user@domain|\\\\)",
    re.IGNORECASE,
)


def _normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", value).strip().lower()


def _clean_name_for_search(name: str) -> str:
    return _TITLE_PREFIX_RE.sub("", name).strip()


def _name_parts(name: str) -> list[str]:
    return _normalize_text(_clean_name_for_search(name)).split()


def _institution_domains(affiliation: str) -> list[str]:
    domains: list[str] = []
    for match in re.finditer(
        r"([\w-]+\.(?:edu(?:\.[a-z]{2})?|ac\.[a-z]{2}|gov(?:\.[a-z]{2})?|org))",
        affiliation,
        re.IGNORECASE,
    ):
        domain = match.group(1).lower()
        if domain not in domains:
            domains.append(domain)
    aff = affiliation.lower()
    if "aims" in aff:
        domains.append("aims.gov.au")
    if "kaust" in aff:
        domains.append("kaust.edu.sa")
    if "queensland" in aff or re.search(r"\buq\b", aff):
        domains.append("uq.edu.au")
    return domains


def _is_obviously_junk_email(email: str) -> bool:
    return not email or "@" not in email or bool(_OBVIOUS_JUNK_EMAIL_RE.search(email))


def _is_generic_role_email(email: str) -> bool:
    return bool(_GENERIC_EMAIL_LOCAL_RE.match(email.split("@", 1)[0].lower()))


def _email_plausibility_score(
    email: str,
    name: str,
    domains: list[str],
    *,
    structured: bool = False,
) -> float:
    if _is_obviously_junk_email(email) or _is_generic_role_email(email):
        return 0.0
    local = email.split("@", 1)[0].lower()
    domain = email.split("@", 1)[1].lower()
    score = 0.0
    if domains and any(domain.endswith(inst) or inst in domain for inst in domains):
        score += 0.38
    elif domain.endswith((".edu", ".edu.au", ".ac.uk", ".gov.au", ".ac.nz")):
        score += 0.22
    parts = [part for part in _name_parts(name) if len(part) > 2]
    compact_local = re.sub(r"[^a-z]", "", local)
    if parts:
        last = parts[-1]
        if last in compact_local:
            score += 0.42
        if len(parts) >= 2 and parts[0][0] in local and last in compact_local:
            score += 0.2
    if structured:
        score += 0.15
    return min(1.0, score)


def _fix_raw_json_syntax(text: str) -> str:
    text = text.replace(
        '        "url": null\n      {',
        '        "url": null\n      },\n      {',
    )
    return text


def _normalize_primary(primary: object) -> dict | None:
    if not primary or not isinstance(primary, dict):
        return None
    ptype = primary.get("type")
    label = primary.get("label")
    url = primary.get("url")
    if label is None or url is None:
        return None
    label = str(label).strip()
    url = str(url).strip()
    if not label or not url:
        return None
    return {"type": str(ptype or "email"), "label": label, "url": url}


def _normalize_links(links: list) -> list[dict]:
    cleaned: list[dict] = []
    for link in links or []:
        if not isinstance(link, dict):
            continue
        url = link.get("url")
        if url is None or str(url).strip() == "":
            continue
        cleaned.append(
            {
                "kind": str(link.get("kind") or "website"),
                "label": str(link.get("label") or "Link"),
                "url": str(url),
            }
        )
    return cleaned


def _should_verify(profile: dict, *, was_user_cleared: bool) -> bool:
    if profile.get("verified") is True:
        return True
    if was_user_cleared:
        return True
    primary = profile.get("primary")
    if not primary or primary.get("type") != "email":
        return False
    email = str(primary.get("label") or "")
    name = str(profile.get("name") or "")
    affiliation = str(profile.get("affiliation") or "")
    score = float(profile.get("email_score") or 0.0)
    if score <= 0.0:
        score = _email_plausibility_score(
            email,
            name,
            _institution_domains(affiliation),
            structured=bool(profile.get("email_structured")),
        )
        profile["email_score"] = score
    return score >= MIN_EMAIL_SCORE


def normalize_cache(cache: dict[str, dict]) -> dict[str, int]:
    stats = {
        "syntax_fixes": 0,
        "primary_normalized": 0,
        "links_cleaned": 0,
        "linkedin_normalized": 0,
        "institutional_page_cleared": 0,
        "profile_page_cleared": 0,
        "primary_cleared": 0,
        "links_removed": 0,
        "verified_skipped": 0,
        "verified_true": 0,
        "verified_null": 0,
    }

    for profile in cache.values():
        clean_stats = conservative_clean_profile(profile)
        for key in (
            "institutional_page_cleared",
            "profile_page_cleared",
            "primary_cleared",
            "links_removed",
            "verified_skipped",
        ):
            stats[key] += clean_stats[key]

        primary = profile.get("primary")
        was_user_cleared = isinstance(primary, dict) and (
            primary.get("label") is None or primary.get("url") is None
        )
        normalized_primary = _normalize_primary(primary)
        if normalized_primary != primary:
            profile["primary"] = normalized_primary
            if was_user_cleared or normalized_primary is None:
                stats["primary_normalized"] += 1

        old_links = profile.get("links") or []
        new_links = _normalize_links(old_links)
        if len(new_links) != len(old_links):
            stats["links_cleaned"] += 1
        profile["links"] = new_links

        if normalize_linkedin_links_in_profile(profile):
            stats["linkedin_normalized"] += 1

        if profile.get("institutional_page") is None:
            profile.pop("institutional_page", None)
        elif not profile.get("institutional_page"):
            profile.pop("institutional_page", None)

        if _should_verify(profile, was_user_cleared=was_user_cleared):
            profile["verified"] = True
            stats["verified_true"] += 1
        else:
            profile["verified"] = None
            stats["verified_null"] += 1

    return stats


def main() -> None:
    raw = CACHE_PATH.read_text(encoding="utf-8")
    fixed = _fix_raw_json_syntax(raw)
    if fixed != raw:
        print("Fixed missing link-object delimiter in JSON")
    cache = json.loads(fixed)

    stamp = __import__("datetime").datetime.now(__import__("datetime").UTC).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    backup_path = CACHE_PATH.with_name(f"speaker_profiles_cache.autobackup.{stamp}.json")
    shutil.copy2(CACHE_PATH, backup_path)
    print(f"Auto-backup: {backup_path}")

    stats = normalize_cache(cache)
    CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(cache)} profiles to {CACHE_PATH}")
    for key, value in stats.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
