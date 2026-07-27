#!/usr/bin/env python3
"""Mark manually curated speaker profiles as verified in the cache."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

DEFAULT_CACHE_PATH = Path("data/speaker_profiles_cache.json")
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
    if "queensland" in aff or "uq" in aff:
        domains.append("uq.edu.au")
    return domains


def _is_obviously_junk_email(email: str) -> bool:
    return not email or "@" not in email or bool(_OBVIOUS_JUNK_EMAIL_RE.search(email))


def _is_generic_role_email(email: str) -> bool:
    return bool(_GENERIC_EMAIL_LOCAL_RE.match(email.split("@", 1)[0].lower()))


def _email_plausibility_score(email: str, name: str, domains: list[str]) -> float:
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
    return min(1.0, score)


def _looks_manually_curated(profile: dict) -> bool:
    if profile.get("verified"):
        return False
    primary = profile.get("primary") or {}
    if primary.get("type") != "email":
        return False
    email = str(primary.get("label") or "")
    name = str(profile.get("name") or "")
    affiliation = str(profile.get("affiliation") or "")
    score = float(profile.get("email_score") or 0.0)
    if score <= 0.0:
        score = _email_plausibility_score(email, name, _institution_domains(affiliation))
    return score >= MIN_EMAIL_SCORE


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", default=str(DEFAULT_CACHE_PATH))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cache_path = Path(args.cache)
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    marked = 0
    already = sum(1 for profile in cache.values() if profile.get("verified"))

    for profile in cache.values():
        if profile.get("verified") or not _looks_manually_curated(profile):
            continue
        marked += 1
        if not args.dry_run:
            profile["verified"] = True

    if not args.dry_run:
        cache_path.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(
        f"Verified profiles: {already} already marked, {marked} newly marked"
        + (" (dry run)" if args.dry_run else "")
    )


if __name__ == "__main__":
    main()
