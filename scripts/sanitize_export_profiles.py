#!/usr/bin/env python3
"""Sanitize and export speaker profiles from cache to js/speaker-profiles.js."""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE_PATH = PROJECT_ROOT / "data" / "speaker_profiles_cache.json"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "js" / "speaker-profiles.js"
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
    r"faisalman|travelandtourworld|schema\.org)",
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


def sanitize_profile_for_export(profile: dict) -> dict:
    cleaned = dict(profile)
    cleaned.pop("phones", None)
    if cleaned.get("verified"):
        return cleaned

    primary = cleaned.get("primary") or {}
    if primary.get("type") != "email":
        return cleaned

    email = str(primary.get("label") or "")
    name = str(cleaned.get("name") or "")
    affiliation = str(cleaned.get("affiliation") or "")
    domains = _institution_domains(affiliation)
    structured = bool(cleaned.get("email_structured"))
    score = float(cleaned.get("email_score") or 0.0)
    if score <= 0.0:
        score = _email_plausibility_score(email, name, domains, structured=structured)

    if (
        _is_obviously_junk_email(email)
        or _is_generic_role_email(email)
        or score < MIN_EMAIL_SCORE
    ):
        cleaned["primary"] = None
        if cleaned.get("institutional_page"):
            cleaned["primary"] = {
                "type": "institution",
                "label": "University profile",
                "url": str(cleaned["institutional_page"]),
            }
        elif cleaned.get("confidence") not in {"search", "low"}:
            cleaned["confidence"] = "search"
        cleaned.pop("email_score", None)
        cleaned.pop("email_structured", None)
    return cleaned


def main() -> None:
    cache_path = DEFAULT_CACHE_PATH
    output_path = DEFAULT_OUTPUT_PATH
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    text = output_path.read_text(encoding="utf-8")
    match = re.match(r"(/\*\*.*?\*/\nexport const SPEAKER_PROFILES = )(.*)(;\n?)$", text, re.DOTALL)
    if not match:
        raise SystemExit("Unexpected speaker-profiles.js format")

    profiles = json.loads(match.group(2))
    cache_by_name = {entry["name"]: entry for entry in cache.values()}
    demoted = 0
    verified = 0

    for name in profiles:
        src = cache_by_name.get(name, profiles[name])
        cleaned = sanitize_profile_for_export(src)
        if src.get("verified"):
            verified += 1
        old_primary = profiles[name].get("primary") or {}
        new_primary = cleaned.get("primary") or {}
        if old_primary.get("type") == "email" and new_primary.get("type") != "email":
            demoted += 1
        profiles[name] = cleaned

    output_path.write_text(
        match.group(1) + json.dumps(profiles, ensure_ascii=True, indent=2) + match.group(3),
        encoding="utf-8",
    )
    print(f"Exported {len(profiles)} profiles ({verified} verified, {demoted} weak emails demoted)")


if __name__ == "__main__":
    main()
