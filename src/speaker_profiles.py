"""Look up public researcher profiles and contact hints for ICRS speakers."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from difflib import SequenceMatcher
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import requests
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

_REQUEST_LOCK = threading.Lock()
_DDG_WARMED = threading.local()
_MAX_PAGE_FETCHES = 14
_MAX_SERP_RESULTS = 10
SERP_FETCH_LIMIT = 7
DEFAULT_WORKERS = min(4, max(2, (os.cpu_count() or 4)))

DEFAULT_CACHE_PATH = Path("data/speaker_profiles_cache.json")
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
SEARCH_USER_AGENT = DEFAULT_USER_AGENT
OPENALEX_API = "https://api.openalex.org/authors"
ORCID_API = "https://pub.orcid.org/v3.0"
DDG_HTML_URL = "https://html.duckduckgo.com/html/"
DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
DEFAULT_KEYS_PATH = Path("keys.yaml")
DEFAULT_BRAVE_BUDGET = 1000
SEARCH_DELAY_SECONDS = 0.35
REQUEST_DELAY_SECONDS = 0.11
LOOKUP_VERSION = 8
MIN_EMAIL_SCORE = 0.72
MIN_STRUCTURED_EMAIL_SCORE = 0.58
MIN_WEB_PROFILE_SCORE = 0.85

_BRAVE_API_KEY: str | None = None
_BRAVE_BUDGET: int | None = DEFAULT_BRAVE_BUDGET
_BRAVE_REQUEST_COUNT = 0
_BRAVE_STATE_LOCK = threading.Lock()

_TITLE_PREFIX_RE = re.compile(
    r"^(?:dr|prof|professor|mr|mrs|ms|miss)\.?\s+",
    flags=re.IGNORECASE,
)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", re.IGNORECASE)
_LINKEDIN_RE = re.compile(
    r"https?://(?:[a-z]+\.)?linkedin\.com/in/[\w%-]+", re.IGNORECASE
)
_JUNK_EMAIL_RE = re.compile(
    r"(?:example\.com|noreply|no-reply|sentry\.io|wixpress|schema\.org|"
    r"webmaster|onlineredaktion|info@|contact@|press@|admin@|office@|enquiries@)",
    re.IGNORECASE,
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
_FREEMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "hotmail.com",
        "outlook.com",
        "aol.com",
        "icloud.com",
        "proton.me",
        "protonmail.com",
    }
)
_JUNK_PROFILE_HOSTS = (
    "researchgate.net",
    "rocketreach.co",
    "zoominfo.com",
    "linkedin.com",
    "facebook.com",
    "twitter.com",
    "x.com",
    "orcid.org",
    "scholar.google.",
    "semanticscholar.org",
    "loop.frontiersin.org",
    "mpg.de/person",
    "adscientificindex.com",
    "scispace.com",
    "research.com",
    "ssrn.com",
    "radaris.com",
    "spokeo.com",
    "beenverified.com",
    "truepeoplesearch.com",
    "whitepages.com",
    "fastpeoplesearch.com",
    "intelius.com",
    "peekyou.com",
)
_PUBLIC_JUNK_URL_PATTERNS = (
    "radaris.com",
    "spokeo.com",
    "beenverified.com",
    "truepeoplesearch.com",
    "whitepages.com",
    "fastpeoplesearch.com",
    "intelius.com",
    "peekyou.com",
    "showbizjunkies.com",
    "greatexpectation.com.au/presenter",
    "mail-archive.com",
    "ecoevo.social",
    "wikipedia.org",
    "researchgate.net",
    "peerj.com/",
    "youtube.com",
    "youtu.be",
)
_UNTRUSTED_PROFILE_URL_RES = (
    re.compile(r"wikipedia\.org", re.IGNORECASE),
    re.compile(r"researchgate\.net", re.IGNORECASE),
    re.compile(r"orcid\.org", re.IGNORECASE),
    re.compile(r"scholar\.google", re.IGNORECASE),
    re.compile(r"linkedin\.com/in/", re.IGNORECASE),
    re.compile(r"youtube\.com|youtu\.be", re.IGNORECASE),
    re.compile(r"\.pdf(?:\?|#|$)", re.IGNORECASE),
    re.compile(
        r"/news/|/newsroom/|article\.php|nature\.com/articles/|/press-releases?/",
        re.IGNORECASE,
    ),
    re.compile(r"peerj\.com/", re.IGNORECASE),
    re.compile(r"mail-archive|ecoevo\.social|showbizjunkies", re.IGNORECASE),
    re.compile(r"/publications(?:/|$|\?)", re.IGNORECASE),
    re.compile(r"/contact-us(?:/|$|\?)", re.IGNORECASE),
    re.compile(r"fisheries\.noaa\.gov/contact/", re.IGNORECASE),
    re.compile(
        r"(?:\.edu|\.gov|\.ac\.[a-z]{2}|\.org)/.*/contact(?:/|$|\?)",
        re.IGNORECASE,
    ),
)
_DIRECTORY_LISTING_URL_RES = (
    re.compile(r"/directory/?(?:\?|$)", re.IGNORECASE),
    re.compile(r"/full-directory", re.IGNORECASE),
    re.compile(r"our-people/\?(?:[^/]*&)?(?:page|sort)=", re.IGNORECASE),
    re.compile(r"our-people/?$", re.IGNORECASE),
    re.compile(r"meet-the-team/?$", re.IGNORECASE),
    re.compile(r"/team/?$", re.IGNORECASE),
    re.compile(r"\?page=\d", re.IGNORECASE),
    re.compile(r"MemberSearchForm", re.IGNORECASE),
    re.compile(r"/leadership/?$", re.IGNORECASE),
    re.compile(r"/students/?$", re.IGNORECASE),
    re.compile(r"phd-students/?$", re.IGNORECASE),
    re.compile(r"about_us\.php", re.IGNORECASE),
)
_PROFILE_PATH_HINTS = (
    "/researchers/",
    "/people/",
    "/staff/",
    "/profile",
    "/expert/",
    "/our-people/",
    "/directory/",
)
_DIRECTORY_CARD_RE = re.compile(
    r"<(?:div|li|article|section)[^>]+class=\"[^\"]*"
    r"\b(?:staff|person|people|faculty|member|profile|directory|team|expert|card|contact)\b"
    r"[^\"]*\"[^>]*>",
    re.IGNORECASE,
)
_ITEMPROP_EMAIL_RE = re.compile(
    r'itemprop=["\']email["\'][^>]*(?:content=["\']([^"\']+)["\']|>([^<]+)<)',
    re.IGNORECASE,
)
_DATA_EMAIL_RE = re.compile(r'data-email=["\']([^"\']+)["\']', re.IGNORECASE)
_OBFUSCATED_EMAIL_RES = (
    re.compile(r"([\w.+-]+)\s*\[at\]\s*([\w.-]+)\s*\[dot\]\s*(\w+)", re.IGNORECASE),
    re.compile(r"([\w.+-]+)\s*\(at\)\s*([\w.-]+)\s*\(dot\)\s*(\w+)", re.IGNORECASE),
    re.compile(r"([\w.+-]+)\s+at\s+([\w.-]+)\s+dot\s+(\w+)", re.IGNORECASE),
)
_SITE_SEARCH_TEMPLATES = (
    "https://www.{domain}/search?q={name_query}",
    "https://{domain}/search?q={name_query}",
    "https://www.{domain}/?s={name_query}",
    "https://{domain}/?s={name_query}",
)

# Affiliation pattern -> domains, profile URL templates, paginated crawls, site searches.
_INSTITUTION_REGISTRY: list[tuple[re.Pattern[str], dict[str, Any]]] = [
    (
        re.compile(r"james cook|\bjcu\b", re.IGNORECASE),
        {
            "domains": ["jcu.edu.au"],
            "profiles": ["https://portfolio.jcu.edu.au/researchers/{slug_dot}"],
        },
    ),
    (
        re.compile(r"university of queensland|\buq\b", re.IGNORECASE),
        {
            "domains": ["uq.edu.au"],
            "profiles": [
                "https://researchers.uq.edu.au/researcher/{slug_hyphen}",
                "https://profiles.uq.edu.au/{slug_hyphen}",
                "https://about.uq.edu.au/experts/{slug_hyphen}",
                "https://environment.uq.edu.au/profile/{slug_hyphen}",
                "https://marine.uq.edu.au/profile/{slug_hyphen}",
            ],
            "searches": [
                "https://about.uq.edu.au/experts/search?q={name_query}",
                "https://environment.uq.edu.au/search?query={name_query}",
            ],
            "web_queries": [
                '"{clean_name}" site:uq.edu.au email',
                "{clean_name} University of Queensland email",
            ],
            "crawls": [
                {
                    "urls": [
                        "https://about.uq.edu.au/experts/search?q={name_query}",
                        "https://researchers.uq.edu.au/search?query={name_query}",
                    ],
                    "max_pages": 1,
                    "active_marker": "",
                },
            ],
        },
    ),
    (
        re.compile(r"australian institute of marine science|\baims\b", re.IGNORECASE),
        {
            "domains": ["aims.gov.au"],
            "profiles": ["https://www.aims.gov.au/about/our-people/{slug_hyphen}"],
            "crawls": [
                {
                    "urls": ["https://www.aims.gov.au/about/our-people"],
                    "max_pages": 1,
                    "active_marker": "our-people",
                },
            ],
        },
    ),
    (
        re.compile(r"nova southeastern|\bnsu\b", re.IGNORECASE),
        {
            "domains": ["nova.edu"],
            "profiles": [
                "https://hcas.nova.edu/people/index.html?search={name_query}",
            ],
            "crawls": [
                {
                    "urls": [
                        "https://hcas.nova.edu/people/index.html?group=Staff&page={page}",
                        "https://hcas.nova.edu/people/index.html?group=Faculty&page={page}",
                    ],
                    "max_pages": 12,
                    "active_marker": "contact-name",
                },
            ],
        },
    ),
    (
        re.compile(r"\bkaust\b", re.IGNORECASE),
        {
            "domains": ["kaust.edu.sa"],
            "profiles": [
                "https://www.kaust.edu.sa/en/study/faculty/{slug_hyphen}",
                "https://cemse.kaust.edu.sa/profiles/{slug_hyphen}",
            ],
            "searches": ["https://www.kaust.edu.sa/en/search?search={name_query}"],
        },
    ),
    (
        re.compile(r"university of hawai|hawai.?i institute|him\b", re.IGNORECASE),
        {
            "domains": ["hawaii.edu"],
            "profiles": [
                "https://www.hawaii.edu/search/?q={name_query}",
            ],
            "searches": ["https://www.hawaii.edu/search/?q={name_query}"],
        },
    ),
    (
        re.compile(r"national university of singapore|\bnus\b", re.IGNORECASE),
        {
            "domains": ["nus.edu.sg"],
            "profiles": [
                "https://www.dbs.nus.edu.sg/staff/{last}/",
                "https://www.dbs.nus.edu.sg/staff/{slug_hyphen}/",
            ],
            "searches": ["https://www.nus.edu.sg/search?query={name_query}"],
        },
    ),
    (
        re.compile(r"university of miami", re.IGNORECASE),
        {
            "domains": ["miami.edu", "rsmas.miami.edu"],
            "searches": [
                "https://people.miami.edu/search/?search={name_query}",
                "https://www.rsmas.miami.edu/?s={name_query}",
            ],
        },
    ),
    (
        re.compile(r"florida international|\bfiu\b", re.IGNORECASE),
        {
            "domains": ["fiu.edu"],
            "profiles": [
                "https://case.fiu.edu/about/directory/profiles/{slug_hyphen}.html",
                "https://case.fiu.edu/about/directory/profiles/{last}.html",
            ],
            "searches": ["https://case.fiu.edu/?s={name_query}"],
        },
    ),
    (
        re.compile(r"university of sydney", re.IGNORECASE),
        {
            "domains": ["sydney.edu.au"],
            "profiles": [
                "https://www.sydney.edu.au/science/about/our-people/{slug_hyphen}.html",
                "https://profiles.sydney.edu.au/{slug_hyphen}",
            ],
            "searches": ["https://www.sydney.edu.au/search.html?q={name_query}"],
        },
    ),
    (
        re.compile(r"university of technology sydney|\buts\b", re.IGNORECASE),
        {
            "domains": ["uts.edu.au"],
            "profiles": ["https://profiles.uts.edu.au/{slug_dot}"],
            "searches": ["https://www.uts.edu.au/search?q={name_query}"],
        },
    ),
    (
        re.compile(r"university of western australia|\buwa\b", re.IGNORECASE),
        {
            "domains": ["uwa.edu.au"],
            "profiles": ["https://www.uwa.edu.au/profile/{slug_hyphen}"],
        },
    ),
    (
        re.compile(r"victoria university of wellington|\bvuw\b", re.IGNORECASE),
        {
            "domains": ["vuw.ac.nz", "wgtn.ac.nz"],
            "profiles": ["https://people.wgtn.ac.nz/{slug_dot}"],
            "crawls": [
                {
                    "urls": ["https://people.wgtn.ac.nz/search?q={name_query}"],
                    "max_pages": 1,
                    "active_marker": "",
                },
            ],
        },
    ),
    (
        re.compile(r"university of california.*santa barbara|\bucsb\b", re.IGNORECASE),
        {
            "domains": ["ucsb.edu"],
            "profiles": ["https://www.ucsb.edu/people/{slug_hyphen}"],
            "searches": ["https://www.ucsb.edu/search?q={name_query}"],
        },
    ),
    (
        re.compile(
            r"university of california.*san diego|\bucsd\b|scripps institution",
            re.IGNORECASE,
        ),
        {
            "domains": ["ucsd.edu"],
            "profiles": [
                "https://profiles.ucsd.edu/{slug_dot}",
                "https://scripps.ucsd.edu/profiles/{slug_hyphen}",
            ],
        },
    ),
    (
        re.compile(r"university of north carolina.*wilmington|\buncw\b", re.IGNORECASE),
        {
            "domains": ["uncw.edu"],
            "searches": ["https://uncw.edu/search.html?q={name_query}"],
        },
    ),
    (
        re.compile(r"arizona state|\basu\b", re.IGNORECASE),
        {
            "domains": ["asu.edu"],
            "profiles": ["https://search.asu.edu/profile/{slug_hyphen}"],
            "searches": ["https://search.asu.edu/?q={name_query}"],
        },
    ),
    (
        re.compile(r"university of hong kong|\bhku\b", re.IGNORECASE),
        {
            "domains": ["hku.hk"],
            "profiles": ["https://www.hku.hk/press/people/{slug_hyphen}.html"],
            "searches": ["https://www.hku.hk/search?q={name_query}"],
        },
    ),
    (
        re.compile(r"university of leeds", re.IGNORECASE),
        {
            "domains": ["leeds.ac.uk"],
            "profiles": [
                "https://biologicalsciences.leeds.ac.uk/school-of-biology/staff/dr-{slug_hyphen}",
                "https://biologicalsciences.leeds.ac.uk/school-of-biology/staff/{slug_hyphen}",
                "https://environment.leeds.ac.uk/see/staff/{last}",
            ],
            "searches": [
                "https://biologicalsciences.leeds.ac.uk/search?q={name_query}",
                "https://www.leeds.ac.uk/search?q={name_query}",
            ],
            "web_queries": [
                '"{clean_name}" site:leeds.ac.uk email',
                "{clean_name} biologicalsciences leeds staff",
            ],
        },
    ),
    (
        re.compile(r"university of konstanz|konstanz", re.IGNORECASE),
        {
            "domains": ["uni-konstanz.de"],
            "profiles": [
                "https://www.biologie.uni-konstanz.de/{last}/",
                "https://www.biologie.uni-konstanz.de/{slug_hyphen}/",
            ],
            "web_queries": [
                "{clean_name} biologie uni-konstanz",
                '"{clean_name}" email konstanz',
            ],
        },
    ),
    (
        re.compile(r"university of the ryukyus|ryukyu", re.IGNORECASE),
        {
            "domains": ["u-ryukyu.ac.jp"],
            "web_queries": [
                '"{clean_name}" miseryukyu',
                '"{clean_name}" MISE University of the Ryukyus',
                "{clean_name} u-ryukyu email",
            ],
        },
    ),
    (
        re.compile(r"mote marine", re.IGNORECASE),
        {
            "domains": ["mote.org"],
            "profiles": [
                "https://mote.org/research/about/our-scientists/{slug_hyphen}"
            ],
        },
    ),
    (
        re.compile(r"national oceanic|noaa\b", re.IGNORECASE),
        {
            "domains": ["noaa.gov"],
            "searches": ["https://www.noaa.gov/search?query={name_query}"],
        },
    ),
    (
        re.compile(r"university of the virgin islands|\buvi\b", re.IGNORECASE),
        {
            "domains": ["uvi.edu"],
            "searches": ["https://www.uvi.edu/search?q={name_query}"],
        },
    ),
    (
        re.compile(r"university of guam", re.IGNORECASE),
        {
            "domains": ["uog.edu"],
            "searches": ["https://www.uog.edu/search?q={name_query}"],
        },
    ),
    (
        re.compile(r"southern cross", re.IGNORECASE),
        {
            "domains": ["scu.edu.au"],
            "profiles": ["https://www.scu.edu.au/research/people/{slug_hyphen}/"],
        },
    ),
    (
        re.compile(r"tel aviv", re.IGNORECASE),
        {
            "domains": ["tau.ac.il"],
            "searches": ["https://english.tau.ac.il/search?q={name_query}"],
        },
    ),
    (
        re.compile(r"boston university", re.IGNORECASE),
        {
            "domains": ["bu.edu"],
            "profiles": ["https://www.bu.edu/ourprofiles/profile/{slug_hyphen}/"],
            "searches": ["https://www.bu.edu/search/?q={name_query}"],
        },
    ),
]


def _normalize_text(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value or "")
    ascii_text = folded.encode("ascii", "ignore").decode("ascii")
    return _NON_ALNUM_RE.sub(" ", ascii_text.lower()).strip()


def _clean_name_for_search(name: str) -> str:
    cleaned = _TITLE_PREFIX_RE.sub("", name.strip())
    return re.sub(r"\s+", " ", cleaned).strip()


def _name_slug_dot(name: str) -> str:
    parts = _normalize_text(_clean_name_for_search(name)).split()
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[-1]}"
    return parts[0] if parts else ""


def _name_slug_hyphen(name: str) -> str:
    parts = _normalize_text(_clean_name_for_search(name)).split()
    return "-".join(parts)


def _name_parts(name: str) -> list[str]:
    return _normalize_text(_clean_name_for_search(name)).split()


def _first_name(name: str) -> str:
    parts = _name_parts(name)
    return parts[0] if parts else ""


def _last_name(name: str) -> str:
    parts = _name_parts(name)
    return parts[-1] if parts else ""


def _institution_config(affiliation: str) -> dict[str, Any] | None:
    for pattern, config in _INSTITUTION_REGISTRY:
        if pattern.search(affiliation):
            return config
    return None


def _domains_from_affiliation_text(affiliation: str) -> list[str]:
    domains: list[str] = []
    for match in re.finditer(
        r"([\w-]+\.(?:edu(?:\.[a-z]{2})?|ac\.[a-z]{2}|gov(?:\.[a-z]{2})?|org))",
        affiliation,
        re.IGNORECASE,
    ):
        domain = match.group(1).lower()
        if domain not in domains:
            domains.append(domain)
    return domains


def _institution_domains(affiliation: str) -> list[str]:
    domains: list[str] = []
    config = _institution_config(affiliation)
    if config:
        for domain in config.get("domains") or []:
            if domain not in domains:
                domains.append(domain)
    for domain in _domains_from_affiliation_text(affiliation):
        if domain not in domains:
            domains.append(domain)
    return domains


def _format_institution_url(template: str, name: str) -> str:
    clean = _clean_name_for_search(name)
    return template.format(
        slug_dot=_name_slug_dot(name),
        slug_hyphen=_name_slug_hyphen(name),
        name_query=quote_plus(clean),
        first=_first_name(name),
        last=_last_name(name),
        name=quote_plus(clean),
    )


def _institution_profile_candidates(name: str, affiliation: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    config = _institution_config(affiliation)
    if not config:
        return urls
    for template in config.get("profiles") or []:
        url = _format_institution_url(template, name)
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _institution_search_candidates(name: str, affiliation: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    config = _institution_config(affiliation)
    templates: list[str] = []
    if config:
        templates.extend(config.get("searches") or [])
        for domain in config.get("domains") or []:
            for site_template in _SITE_SEARCH_TEMPLATES:
                templates.append(
                    site_template.format(domain=domain, name_query="{name_query}")
                )
    for domain in _institution_domains(affiliation)[:2]:
        for site_template in _SITE_SEARCH_TEMPLATES[:2]:
            templates.append(
                site_template.format(domain=domain, name_query="{name_query}")
            )
    for template in templates:
        url = _format_institution_url(template, name)
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls[:8]


def _domain_from_url(page_url: str) -> str:
    host = urlparse(page_url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _email_matches_domains(email: str, domains: list[str]) -> bool:
    if not domains:
        return True
    email_l = email.lower()
    return any(domain in email_l for domain in domains)


def _is_plausible_personal_email(email: str, name: str) -> bool:
    local = email.split("@", 1)[0].lower()
    if _GENERIC_EMAIL_LOCAL_RE.search(local) or _JUNK_EMAIL_RE.search(email):
        return False
    parts = [part for part in _name_parts(name) if len(part) > 2]
    if len(parts) >= 2:
        compact = local.replace(".", "").replace("_", "").replace("-", "")
        first, last = parts[0], parts[-1]
        if first in local and last in local:
            return True
        if f"{first[0]}{last}" in compact or f"{first}.{last}" in local:
            return True
        if last in local and len(local) <= len(last) + 6:
            return True
    return bool(parts) and parts[-1] in local


def _filter_personal_emails(emails: list[str], name: str) -> list[str]:
    personal = [email for email in emails if _is_plausible_personal_email(email, name)]
    return personal or emails


def _is_obviously_junk_email(email: str) -> bool:
    if not email or "@" not in email:
        return True
    if _OBVIOUS_JUNK_EMAIL_RE.search(email):
        return True
    local, _, domain = email.partition("@")
    if not local or not domain or len(domain) < 4:
        return True
    if local in {"email", "name", "user", "username", "address"}:
        return True
    return False


def _is_generic_role_email(email: str) -> bool:
    local = email.split("@", 1)[0].lower()
    return bool(_GENERIC_EMAIL_LOCAL_RE.match(local))


def _email_plausibility_score(
    email: str,
    name: str,
    domains: list[str] | None = None,
    *,
    structured: bool = False,
) -> float:
    if _is_obviously_junk_email(email) or _JUNK_EMAIL_RE.search(email):
        return 0.0
    if _is_generic_role_email(email):
        return 0.0

    local = email.split("@", 1)[0].lower()
    domain = email.split("@", 1)[1].lower()
    score = 0.0

    if domains and _email_matches_domains(email, domains):
        score += 0.38
    elif domain.endswith((".edu", ".edu.au", ".ac.uk", ".gov.au", ".ac.nz")):
        score += 0.22

    if _is_plausible_personal_email(email, name):
        score += 0.42
    else:
        parts = [part for part in _name_parts(name) if len(part) > 2]
        compact_local = re.sub(r"[^a-z]", "", local)
        if parts:
            last = parts[-1]
            if last in compact_local:
                score += 0.28
            if len(parts) >= 2 and parts[0][0] in local and last in compact_local:
                score += 0.2

    if domain in _FREEMAIL_DOMAINS:
        score -= 0.35

    if structured:
        score += 0.15

    return max(0.0, min(1.0, score))


def _pick_best_email(
    emails: list[str],
    name: str,
    domains: list[str] | None = None,
    *,
    structured: bool = False,
) -> tuple[str | None, float]:
    threshold = MIN_STRUCTURED_EMAIL_SCORE if structured else MIN_EMAIL_SCORE
    best_email: str | None = None
    best_score = 0.0
    for email in emails:
        score = _email_plausibility_score(
            email,
            name,
            domains,
            structured=structured,
        )
        if score > best_score:
            best_score = score
            best_email = email
    if best_email and best_score >= threshold:
        return best_email, best_score
    return None, best_score


def _filter_scored_emails(
    emails: list[str],
    name: str,
    domains: list[str] | None = None,
    *,
    structured: bool = False,
) -> list[str]:
    kept: list[str] = []
    for email in emails:
        if _email_plausibility_score(email, name, domains, structured=structured) > 0:
            kept.append(email)
    return kept


def _merge_web_profiles(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
    *,
    name: str,
    email_domains: list[str],
) -> dict[str, Any] | None:
    if not left:
        return right
    if not right:
        return left

    left_score = float(left.get("_score") or 0.0)
    right_score = float(right.get("_score") or 0.0)
    combined_emails = list(dict.fromkeys((left.get("emails") or []) + (right.get("emails") or [])))
    structured = bool(left.get("structured") or right.get("structured"))
    best_email, email_score = _pick_best_email(
        combined_emails,
        name,
        email_domains,
        structured=structured,
    )
    winner = left if left_score >= right_score else right
    merged = dict(winner)
    merged["emails"] = [best_email] if best_email else []
    merged["structured"] = structured
    merged["email_score"] = email_score
    merged["_score"] = max(left_score, right_score, email_score)
    if merged["emails"]:
        merged["confidence"] = (
            "high"
            if structured and email_score >= MIN_EMAIL_SCORE
            else winner.get("confidence", "medium")
        )
    return merged


def _filter_emails(emails: list[str], domains: list[str]) -> list[str]:
    if not emails:
        return []
    if not domains:
        return emails
    matched = [email for email in emails if _email_matches_domains(email, domains)]
    return matched or emails


def _affiliation_tokens(affiliation: str) -> set[str]:
    tokens = {token for token in _normalize_text(affiliation).split() if len(token) > 3}
    extras: set[str] = set()
    if "james cook" in _normalize_text(affiliation):
        extras.update({"jcu", "james", "cook"})
    if "queensland" in _normalize_text(affiliation):
        extras.add("uq")
    if "nova" in _normalize_text(affiliation) or "southeastern" in _normalize_text(
        affiliation
    ):
        extras.update({"nova", "southeastern", "nsu"})
    return tokens | extras


def _name_similarity(left: str, right: str) -> float:
    left_norm = _normalize_text(_clean_name_for_search(left))
    right_norm = _normalize_text(_clean_name_for_search(right))
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def _affiliation_similarity(left: str, right: str) -> float:
    left_norm = _normalize_text(left)
    right_norm = _normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm in right_norm or right_norm in left_norm:
        return 1.0
    left_tokens = {token for token in left_norm.split() if len(token) > 3}
    right_tokens = {token for token in right_norm.split() if len(token) > 3}
    if not left_tokens or not right_tokens:
        return SequenceMatcher(None, left_norm, right_norm).ratio()
    overlap = len(left_tokens & right_tokens) / max(len(left_tokens), 1)
    return max(overlap, SequenceMatcher(None, left_norm, right_norm).ratio() * 0.75)


def _profile_key(name: str, affiliation: str = "") -> str:
    return f"{name.strip()}|{affiliation.strip()}"


def _linkedin_search_url(name: str, affiliation: str) -> str:
    query = quote_plus(f"{_clean_name_for_search(name)} {affiliation}".strip())
    return f"https://www.linkedin.com/search/results/people/?keywords={query}"


def _linkedin_search_link(name: str, affiliation: str) -> dict[str, str]:
    return {
        "kind": "linkedin_search",
        "label": "Search LinkedIn",
        "url": _linkedin_search_url(name, affiliation),
    }


def _is_direct_linkedin_url(url: str | None) -> bool:
    return bool(url and "linkedin.com/in/" in url.lower())


def normalize_linkedin_links_in_profile(profile: dict[str, Any]) -> bool:
    """Replace scraped LinkedIn profile URLs with name-based search links."""
    name = str(profile.get("name") or "")
    affiliation = str(profile.get("affiliation") or "")
    changed = False

    primary = profile.get("primary") or {}
    if primary.get("type") == "linkedin" or _is_direct_linkedin_url(primary.get("url")):
        profile["primary"] = None
        changed = True

    search_link = _linkedin_search_link(name, affiliation)
    kept_links: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for link in profile.get("links") or []:
        url = str(link.get("url") or "")
        kind = str(link.get("kind") or "")
        if kind in {"linkedin", "linkedin_search"} or _is_direct_linkedin_url(url):
            changed = True
            continue
        if url and url not in seen_urls:
            seen_urls.add(url)
            kept_links.append(link)

    kept_links.append(search_link)
    if profile.get("links") != kept_links:
        profile["links"] = kept_links
        changed = True
    return changed


def _scholar_search_url(name: str, affiliation: str) -> str:
    query = quote_plus(f"{_clean_name_for_search(name)} {affiliation}".strip())
    return f"https://scholar.google.com/scholar?q={query}"


def _orcid_id_from_url(orcid_url: str | None) -> str | None:
    if not orcid_url:
        return None
    match = re.search(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dX])", orcid_url)
    return match.group(1) if match else None


def load_brave_api_key(keys_path: str | Path = DEFAULT_KEYS_PATH) -> str | None:
    """Load Brave Search API key from env or keys.yaml."""
    env_key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if env_key:
        return env_key.strip()

    path = Path(keys_path)
    if not path.exists():
        return None

    try:
        import yaml
    except ImportError:
        return None

    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for name in ("brave-search-api", "brave_search_api", "brave-search"):
        value = payload.get(name)
        if value:
            return str(value).strip()
    return None


def configure_brave_search(
    *,
    api_key: str | None = None,
    keys_path: str | Path = DEFAULT_KEYS_PATH,
    budget: int | None = DEFAULT_BRAVE_BUDGET,
) -> str | None:
    """Configure Brave as the web search provider when a key is available."""
    global _BRAVE_API_KEY, _BRAVE_BUDGET, _BRAVE_REQUEST_COUNT
    with _BRAVE_STATE_LOCK:
        _BRAVE_API_KEY = (
            api_key if api_key is not None else load_brave_api_key(keys_path)
        )
        _BRAVE_BUDGET = budget
        _BRAVE_REQUEST_COUNT = 0
    return _BRAVE_API_KEY


def brave_api_query_count() -> int:
    with _BRAVE_STATE_LOCK:
        return _BRAVE_REQUEST_COUNT


def brave_api_budget_remaining() -> int | None:
    with _BRAVE_STATE_LOCK:
        if _BRAVE_BUDGET is None:
            return None
        return max(0, _BRAVE_BUDGET - _BRAVE_REQUEST_COUNT)


def _brave_budget_allows_request() -> bool:
    with _BRAVE_STATE_LOCK:
        if not _BRAVE_API_KEY:
            return False
        if _BRAVE_BUDGET is None:
            return True
        return _BRAVE_REQUEST_COUNT < _BRAVE_BUDGET


def _record_brave_request() -> None:
    global _BRAVE_REQUEST_COUNT
    with _BRAVE_STATE_LOCK:
        _BRAVE_REQUEST_COUNT += 1


def _session(user_agent: str = DEFAULT_USER_AGENT) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return session


def _ensure_ddg_session(session: requests.Session) -> None:
    if getattr(_DDG_WARMED, "ready", False):
        return
    with _REQUEST_LOCK:
        if getattr(_DDG_WARMED, "ready", False):
            return
        try:
            session.get(
                "https://duckduckgo.com/",
                timeout=15,
                headers={"User-Agent": SEARCH_USER_AGENT},
            )
            time.sleep(0.4)
        except requests.RequestException:
            pass
        _DDG_WARMED.ready = True


def _is_junk_profile_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    path = (urlparse(url).path or "").lower()
    return any(junk in host or junk in f"{host}{path}" for junk in _JUNK_PROFILE_HOSTS)


def _score_profile_url(url: str, name: str, affiliation: str) -> float:
    if _is_junk_profile_url(url):
        return -1.0
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return -1.0
    path = (parsed.path or "").lower()
    if path.endswith((".pdf", ".png", ".jpg", ".zip")):
        return -1.0

    url_l = url.lower()
    score = 0.0
    slug_dot = _name_slug_dot(name)
    slug_hyphen = _name_slug_hyphen(name)
    compact_name = _normalize_text(_clean_name_for_search(name)).replace(" ", "")
    compact_url = url_l.replace(".", "").replace("-", "").replace("_", "")

    if slug_dot and slug_dot in url_l:
        score += 0.45
    elif slug_hyphen and slug_hyphen in url_l:
        score += 0.4
    elif compact_name and compact_name in compact_url:
        score += 0.35

    aff_tokens = _affiliation_tokens(affiliation)
    host = (parsed.netloc or "").lower()
    if any(token in host or token in path for token in aff_tokens):
        score += 0.25

    if any(hint in path for hint in _PROFILE_PATH_HINTS):
        score += 0.2
    if any(
        host.endswith(suffix) for suffix in (".edu", ".edu.au", ".ac.uk", ".gov.au")
    ):
        score += 0.1
    if "news" in path or "/releases/" in path:
        score -= 0.35
    if _is_search_results_page(url):
        score -= 0.55
    return score


def _is_search_results_page(url: str) -> bool:
    lower = url.lower()
    return any(
        marker in lower
        for marker in (
            "/search",
            "?q=",
            "&q=",
            "?s=",
            "&s=",
            "query=",
            "&search=",
            "search?",
        )
    )


def _format_web_query(template: str, name: str) -> str:
    clean = _clean_name_for_search(name)
    return template.format(
        clean_name=clean,
        slug_dot=_name_slug_dot(name),
        slug_hyphen=_name_slug_hyphen(name),
        first=_first_name(name),
        last=_last_name(name),
        name_query=quote_plus(clean),
    )


def _affiliation_short(affiliation: str) -> str:
    return affiliation.split(",")[0].strip()


def _google_like_search_queries(
    name: str, affiliation: str, *, broad: bool = False
) -> list[str]:
    """Queries ordered like a human typing into Google."""
    clean_name = _clean_name_for_search(name)
    aff = _affiliation_short(affiliation)
    queries = [
        f"{clean_name} {aff}",
        f'"{clean_name}" {aff}',
        f'"{clean_name}" {aff} email',
        f'"{clean_name}" email',
    ]
    config = _institution_config(affiliation)
    if config:
        for template in config.get("web_queries") or []:
            queries.append(_format_web_query(template, name))
    for domain in _institution_domains(affiliation)[:2]:
        queries.append(f'"{clean_name}" site:{domain}')
    if broad:
        last = _last_name(name)
        queries.extend(
            [
                f"{clean_name} {last} lab email",
                f"{clean_name} university staff profile",
            ]
        )
    seen: set[str] = set()
    ordered: list[str] = []
    for query in queries:
        if query not in seen:
            seen.add(query)
            ordered.append(query)
    return ordered


def _unwrap_search_redirect(url: str) -> str:
    if "uddg=" not in url:
        return url
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    redirect = params.get("uddg", [None])[0]
    if redirect:
        return unquote(redirect)
    return url


def _parse_ddg_lite_results(html: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r'href="(https?://[^"]+)"', html, re.IGNORECASE):
        url = unescape(match.group(1)).strip()
        if "duckduckgo.com" in url.lower():
            continue
        url = _unwrap_search_redirect(url)
        if url in seen or _is_junk_profile_url(url):
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= _MAX_SERP_RESULTS:
            break
    return urls


def _parse_ddg_html_results(html: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(
        r'class="result__a"[^>]*href="([^"]+)"', html, re.IGNORECASE
    ):
        url = _unwrap_search_redirect(unescape(match.group(1)).strip())
        if not url.startswith("http") or url in seen or _is_junk_profile_url(url):
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= _MAX_SERP_RESULTS:
            break
    return urls


def _parse_brave_results(payload: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for item in (payload.get("web") or {}).get("results") or []:
        url = str(item.get("url") or "").strip()
        if not url.startswith("http") or url in seen or _is_junk_profile_url(url):
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= _MAX_SERP_RESULTS:
            break
    return urls


def _brave_search_serp(session: requests.Session, query: str) -> list[str]:
    """Return external result URLs via Brave Search API (counts against budget)."""
    if not _brave_budget_allows_request():
        return []

    with _BRAVE_STATE_LOCK:
        api_key = _BRAVE_API_KEY
    if not api_key:
        return []

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }
    params = {
        "q": query,
        "count": _MAX_SERP_RESULTS,
        "search_lang": "en",
    }
    with _REQUEST_LOCK:
        try:
            response = session.get(
                BRAVE_SEARCH_URL,
                headers=headers,
                params=params,
                timeout=30,
            )
            if response.status_code == 429:
                time.sleep(SEARCH_DELAY_SECONDS * 2)
                return []
            response.raise_for_status()
            urls = _parse_brave_results(response.json())
            _record_brave_request()
            time.sleep(SEARCH_DELAY_SECONDS)
            return urls
        except requests.RequestException:
            time.sleep(SEARCH_DELAY_SECONDS)
            return []


def _web_search_serp(session: requests.Session, query: str) -> list[str]:
    if _BRAVE_API_KEY and _brave_budget_allows_request():
        urls = _brave_search_serp(session, query)
        if urls:
            return urls
    return _ddg_search_serp(session, query)


def _ddg_search_serp(session: requests.Session, query: str) -> list[str]:
    """Return external result URLs in SERP order (Google-like: first hit is best)."""
    _ensure_ddg_session(session)
    headers = {
        "User-Agent": SEARCH_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://duckduckgo.com/",
    }
    endpoints = (
        (DDG_LITE_URL, _parse_ddg_lite_results),
        (DDG_HTML_URL, _parse_ddg_html_results),
    )
    with _REQUEST_LOCK:
        for endpoint, parser in endpoints:
            for attempt in range(2):
                try:
                    response = session.post(
                        endpoint,
                        data={"q": query},
                        timeout=30,
                        headers=headers,
                    )
                    if response.status_code not in {200, 202}:
                        time.sleep(SEARCH_DELAY_SECONDS * (attempt + 1))
                        continue
                    urls = parser(response.text)
                    if urls:
                        time.sleep(SEARCH_DELAY_SECONDS)
                        return urls
                except requests.RequestException:
                    time.sleep(SEARCH_DELAY_SECONDS * (attempt + 1))
        time.sleep(SEARCH_DELAY_SECONDS)
    return []


def _collect_serp_urls(
    session: requests.Session,
    name: str,
    affiliation: str,
    *,
    broad: bool = False,
) -> list[str]:
    """Run web search queries; merge results preserving SERP order (deduped)."""
    use_brave = bool(_BRAVE_API_KEY and _brave_budget_allows_request())
    if use_brave:
        clean_name = _clean_name_for_search(name)
        aff = _affiliation_short(affiliation)
        if broad:
            queries = [f'"{clean_name}" email']
        else:
            queries = [f"{clean_name} {aff}"]
    else:
        queries = _google_like_search_queries(name, affiliation, broad=broad)

    urls: list[str] = []
    seen: set[str] = set()
    for query in queries:
        for url in _web_search_serp(session, query):
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
            if len(urls) >= _MAX_SERP_RESULTS:
                return urls
        if urls:
            break
    return urls


def _web_search_queries(
    name: str, affiliation: str, *, broad: bool = False
) -> list[str]:
    return _google_like_search_queries(name, affiliation, broad=broad)


def _web_search_profile_urls(
    session: requests.Session,
    name: str,
    affiliation: str,
    *,
    max_results: int = 10,
    broad: bool = False,
) -> list[str]:
    return _collect_serp_urls(session, name, affiliation, broad=broad)[:max_results]


def _extract_profile_links_from_page(
    html: str,
    page_url: str,
    name: str,
    affiliation: str,
) -> list[str]:
    slug_hyphen = _name_slug_hyphen(name)
    slug_dot = _name_slug_dot(name)
    last = _last_name(name)
    compact = _normalize_text(_clean_name_for_search(name)).replace(" ", "")
    links: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE):
        href = unescape(match.group(1)).strip()
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue
        full = urljoin(page_url, href)
        if full in seen:
            continue
        low = full.lower()
        if not any(
            hint in low
            for hint in (
                "/staff",
                "/people",
                "/profile",
                "/faculty",
                "/researcher",
                "/expert",
                "/our-people",
            )
        ):
            continue
        compact_url = low.replace(".", "").replace("-", "").replace("_", "")
        if not (
            (slug_hyphen and slug_hyphen in low)
            or (slug_dot and slug_dot in low)
            or (last and len(last) > 3 and last in low)
            or (compact and compact in compact_url)
        ):
            continue
        seen.add(full)
        links.append(full)
    return sorted(
        links, key=lambda url: _score_profile_url(url, name, affiliation), reverse=True
    )[:6]


def _fetch_and_evaluate_url(
    session: requests.Session,
    url: str,
    *,
    name: str,
    affiliation: str,
    email_domains: list[str],
    url_score: float,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Fetch one URL; return (profile, follow-up links from search pages)."""
    follow_ups: list[str] = []
    if _is_junk_profile_url(url) or url_score < 0:
        return None, follow_ups
    try:
        response = session.get(url, timeout=25, allow_redirects=True)
        if response.status_code >= 400:
            return None, follow_ups
        html = response.text
    except requests.RequestException:
        return None, follow_ups

    if _is_search_results_page(response.url):
        follow_ups = _extract_profile_links_from_page(
            html, response.url, name, affiliation
        )

    profile = _evaluate_fetched_page(
        html=html,
        page_url=response.url,
        name=name,
        affiliation=affiliation,
        url_score=url_score,
        email_domains=email_domains,
    )
    return profile, follow_ups


def _try_urls_for_profile(
    session: requests.Session,
    urls: list[str],
    *,
    name: str,
    affiliation: str,
    email_domains: list[str],
    stop_on_email: bool = False,
) -> dict[str, Any] | None:
    """Walk URLs and keep the strongest profile candidate instead of first email."""
    best: dict[str, Any] | None = None
    best_score = 0.0
    for index, url in enumerate(urls):
        url_score = max(0.35, 1.0 - (index * 0.06))
        profile, follow_ups = _fetch_and_evaluate_url(
            session,
            url,
            name=name,
            affiliation=affiliation,
            email_domains=email_domains,
            url_score=url_score,
        )
        if profile:
            profile_score = float(profile.pop("_score", 0.0))
            profile_emails = profile.get("emails") or []
            if profile_emails:
                best_email, email_score = _pick_best_email(
                    profile_emails,
                    name,
                    email_domains,
                    structured=bool(profile.get("structured")),
                )
                profile["emails"] = [best_email] if best_email else []
                profile["email_score"] = email_score
                profile_score = max(profile_score, email_score)
            if profile_score > best_score:
                best_score = profile_score
                best = profile
            if stop_on_email and profile.get("emails") and profile_score >= MIN_WEB_PROFILE_SCORE:
                return profile
        for follow_up in follow_ups:
            if follow_up not in urls:
                urls.append(follow_up)
        time.sleep(REQUEST_DELAY_SECONDS)
    if best and best.get("emails") and best_score < MIN_STRUCTURED_EMAIL_SCORE:
        best = dict(best)
        best["emails"] = []
    return best


def _contacts_from_fragment(
    fragment: str, email_domains: list[str] | None = None
) -> dict[str, Any]:
    emails: list[str] = []
    linkedin: str | None = None
    seen_emails: set[str] = set()
    domains = email_domains or []

    def add_email(raw: str) -> None:
        email = unquote(raw).strip().lower()
        if not email or _JUNK_EMAIL_RE.search(email) or email in seen_emails:
            return
        if _is_obviously_junk_email(email) or _is_generic_role_email(email):
            return
        seen_emails.add(email)
        emails.append(email)

    for match in re.finditer(r'mailto:([^"\'>\s?]+)', fragment, re.IGNORECASE):
        add_email(match.group(1))
    for match in _DATA_EMAIL_RE.finditer(fragment):
        add_email(match.group(1))
    for match in _ITEMPROP_EMAIL_RE.finditer(fragment):
        add_email(match.group(1) or match.group(2) or "")
    for pattern in _OBFUSCATED_EMAIL_RES:
        for match in pattern.finditer(fragment):
            add_email(f"{match.group(1)}@{match.group(2)}.{match.group(3)}")
    for match in _EMAIL_RE.finditer(fragment):
        add_email(match.group(0))

    for match in _LINKEDIN_RE.finditer(fragment):
        linkedin = match.group(0)
        break

    return {
        "emails": _filter_emails(emails, domains)[:3],
        "linkedin": linkedin,
    }


def _name_matches_block(name: str, block_name: str, block_html: str = "") -> float:
    score = _name_similarity(name, block_name)
    if score >= 0.88:
        return score
    if not block_name and block_html:
        parts = [part for part in _name_parts(name) if len(part) > 2]
        block_text = _normalize_text(unescape(re.sub(r"<[^>]+>", " ", block_html)))
        if parts and all(part in block_text for part in parts):
            return 0.9
    return score


def _pick_named_block_contacts(
    name: str,
    block_name: str,
    block_html: str,
    *,
    email_domains: list[str],
) -> tuple[dict[str, Any] | None, float]:
    name_score = _name_matches_block(name, block_name, block_html)
    if name_score < 0.88:
        return None, 0.0
    contacts = _contacts_from_fragment(block_html, email_domains)
    score = name_score + (0.25 if contacts["emails"] else 0.0)
    return contacts, score


def _extract_from_directory_blocks(
    html: str,
    name: str,
    *,
    email_domains: list[str],
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_score = 0.0

    if "contact-name" in html.lower():
        for match in re.finditer(
            r'<p\s+class="contact-name"[^>]*>\s*([^<]+?)\s*</p>(.*?)(?=<p\s+class="contact-name"|$)',
            html,
            re.IGNORECASE | re.DOTALL,
        ):
            contacts, score = _pick_named_block_contacts(
                name,
                unescape(match.group(1)).strip(),
                match.group(2),
                email_domains=email_domains,
            )
            if contacts and score > best_score:
                best_score = score
                best = contacts
            if score >= 1.15 and contacts and contacts.get("emails"):
                return contacts

    for match in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.IGNORECASE | re.DOTALL):
        row_html = match.group(1)
        if "mailto:" not in row_html.lower():
            continue
        row_text = unescape(re.sub(r"<[^>]+>", " ", row_html))
        contacts, score = _pick_named_block_contacts(
            name,
            row_text,
            row_html,
            email_domains=email_domains,
        )
        if contacts and score > best_score:
            best_score = score
            best = contacts

    for match in _DIRECTORY_CARD_RE.finditer(html):
        start = match.start()
        end = min(len(html), start + 5000)
        card_html = html[start:end]
        next_card = _DIRECTORY_CARD_RE.search(card_html, 1)
        if next_card:
            card_html = card_html[: next_card.start()]
        title_match = re.search(
            r"<h[1-4][^>]*>(.*?)</h[1-4]>",
            card_html,
            re.IGNORECASE | re.DOTALL,
        )
        block_name = (
            unescape(re.sub(r"<[^>]+>", " ", title_match.group(1))).strip()
            if title_match
            else ""
        )
        contacts, score = _pick_named_block_contacts(
            name,
            block_name,
            card_html,
            email_domains=email_domains,
        )
        if contacts and score > best_score:
            best_score = score
            best = contacts

    return best


def _extract_from_heading_sections(
    html: str,
    name: str,
    *,
    email_domains: list[str],
) -> dict[str, Any] | None:
    chunks = re.split(r"(?=<h[1-4]\b)", html, flags=re.IGNORECASE)
    for chunk in chunks:
        heading_match = re.match(
            r"<h[1-4][^>]*>(.*?)</h[1-4]>",
            chunk,
            re.IGNORECASE | re.DOTALL,
        )
        if not heading_match:
            continue
        heading_text = unescape(re.sub(r"<[^>]+>", " ", heading_match.group(1))).strip()
        if _name_similarity(name, heading_text) < 0.85:
            continue
        body = chunk[heading_match.end() :]
        next_heading = re.search(r"<h[1-4]\b", body, re.IGNORECASE)
        if next_heading:
            body = body[: next_heading.start()]
        contacts = _contacts_from_fragment(body, email_domains)
        if contacts.get("emails"):
            return contacts
    return None


def _walk_jsonld_nodes(node: Any) -> list[dict[str, Any]]:
    people: list[dict[str, Any]] = []
    if isinstance(node, list):
        for item in node:
            people.extend(_walk_jsonld_nodes(item))
        return people
    if not isinstance(node, dict):
        return people
    node_type = node.get("@type")
    types = node_type if isinstance(node_type, list) else [node_type]
    if any(str(item).lower() == "person" for item in types if item):
        people.append(node)
    for key in ("@graph", "mainEntity", "author", "creator", "member", "employee"):
        if key in node:
            people.extend(_walk_jsonld_nodes(node[key]))
    return people


def _extract_from_jsonld(
    html: str,
    name: str,
    *,
    email_domains: list[str],
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_score = 0.0
    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        for person in _walk_jsonld_nodes(payload):
            display_name = str(person.get("name") or "")
            name_score = _name_similarity(name, display_name)
            if name_score < 0.85:
                continue
            emails: list[str] = []
            email_field = person.get("email")
            if isinstance(email_field, str):
                emails.append(email_field)
            elif isinstance(email_field, list):
                emails.extend(str(item) for item in email_field if item)
            contacts = {
                "emails": _filter_emails(emails, email_domains)[:3],
                "linkedin": None,
            }
            score = name_score + (0.3 if contacts["emails"] else 0.0)
            if score > best_score:
                best_score = score
                best = contacts
    return best


def _extract_contacts_near_name(
    html: str,
    name: str,
    *,
    email_domains: list[str],
) -> dict[str, Any] | None:
    parts = [part for part in _name_parts(name) if len(part) > 2]
    if len(parts) < 2:
        return None
    between = r"(?:<[^>]+>|\s|&nbsp;)+"
    pattern = re.compile(between.join(re.escape(part) for part in parts), re.IGNORECASE)
    best: dict[str, Any] | None = None
    best_score = 0.0
    for match in pattern.finditer(html):
        start = max(0, match.start() - 2500)
        end = min(len(html), match.end() + 2500)
        contacts = _contacts_from_fragment(html[start:end], email_domains)
        if not contacts.get("emails"):
            continue
        domain_bonus = sum(
            0.15
            for email in contacts["emails"]
            if _email_matches_domains(email, email_domains)
        )
        score = 0.75 + domain_bonus
        if score > best_score:
            best_score = score
            best = contacts
    return best


def _extract_named_contacts_from_html(
    html: str,
    name: str,
    *,
    page_url: str = "",
    email_domains: list[str] | None = None,
) -> dict[str, Any] | None:
    domains = list(email_domains or [])
    page_domain = _domain_from_url(page_url)
    if page_domain and page_domain not in domains:
        domains.append(page_domain)

    strategies = (
        _extract_from_directory_blocks,
        _extract_from_jsonld,
        _extract_from_heading_sections,
        _extract_contacts_near_name,
    )
    best: dict[str, Any] | None = None
    best_score = 0.0
    for strategy in strategies:
        result = strategy(html, name, email_domains=domains)
        if not result or not result.get("emails"):
            continue
        score = 0.8 + (
            0.2
            if all(_email_matches_domains(email, domains) for email in result["emails"])
            else 0.0
        )
        if score > best_score:
            best_score = score
            best = result
    return best


def _web_profile_from_page(
    *,
    page_url: str,
    name: str,
    contacts: dict[str, Any],
    name_in_page: bool,
    url_score: float = 0.0,
    structured: bool = False,
    email_domains: list[str] | None = None,
) -> dict[str, Any]:
    structured = structured or bool(contacts.get("structured"))
    domains = list(email_domains or [])
    best_email, email_score = _pick_best_email(
        contacts.get("emails") or [],
        name,
        domains,
        structured=structured,
    )
    emails = [best_email] if best_email else []
    if emails and structured and name_in_page and email_score >= MIN_EMAIL_SCORE:
        confidence = "high"
    elif emails and email_score >= MIN_EMAIL_SCORE:
        confidence = "medium"
    elif emails:
        confidence = "low"
    elif name_in_page:
        confidence = "medium"
    else:
        confidence = "low"
    return {
        "page_url": page_url,
        "page_title": name,
        "emails": emails,
        "linkedin": contacts.get("linkedin"),
        "confidence": confidence,
        "structured": structured,
        "email_score": email_score,
        "_score": url_score
        + email_score
        + (0.15 if structured else 0.0)
        + (0.1 if name_in_page else 0.0),
    }


def _crawl_institution_directories(
    session: requests.Session,
    name: str,
    affiliation: str,
) -> dict[str, Any] | None:
    config = _institution_config(affiliation)
    if not config:
        return None
    email_domains = _institution_domains(affiliation)
    for crawl in config.get("crawls") or []:
        max_pages = int(crawl.get("max_pages") or 8)
        active_marker = str(crawl.get("active_marker") or "")
        for url_template in crawl.get("urls") or []:
            for page in range(1, max_pages + 1):
                url = url_template.format(
                    page=page,
                    name_query=quote_plus(_clean_name_for_search(name)),
                )
                try:
                    response = session.get(url, timeout=25, allow_redirects=True)
                    if response.status_code >= 400:
                        break
                    html = response.text
                except requests.RequestException:
                    break
                if active_marker and active_marker.lower() not in html.lower():
                    break
                contacts = _extract_named_contacts_from_html(
                    html,
                    name,
                    page_url=response.url,
                    email_domains=email_domains,
                )
                if contacts and contacts.get("emails"):
                    return _web_profile_from_page(
                        page_url=response.url,
                        name=name,
                        contacts=contacts,
                        name_in_page=True,
                        url_score=0.95,
                        structured=True,
                    )
                time.sleep(REQUEST_DELAY_SECONDS)
    return None


def _extract_contacts_from_html(
    html: str,
    page_url: str,
    *,
    name: str = "",
    email_domains: list[str] | None = None,
) -> dict[str, Any]:
    domains = list(email_domains or [])
    page_domain = _domain_from_url(page_url)
    if page_domain and page_domain not in domains:
        domains.append(page_domain)

    if name:
        named = _extract_named_contacts_from_html(
            html,
            name,
            page_url=page_url,
            email_domains=domains,
        )
        if named and named.get("emails"):
            named = dict(named)
            named["structured"] = True
            named["emails"] = _filter_scored_emails(
                named["emails"],
                name,
                domains,
                structured=True,
            )
            if named["emails"]:
                return named

        name_parts = [part for part in _name_parts(name) if len(part) > 2]
        page_text = _normalize_text(html)
        if name_parts and all(part in page_text for part in name_parts):
            contacts = _contacts_from_fragment(html, domains)
            inst_emails = [
                email
                for email in contacts["emails"]
                if _email_matches_domains(email, domains)
            ]
            if len(inst_emails) == 1:
                contacts = dict(contacts)
                contacts["emails"] = inst_emails
                contacts["structured"] = True
                return contacts

    contacts = _contacts_from_fragment(html, domains)
    page_domain_l = urlparse(page_url).netloc.lower()
    if page_domain_l:
        contacts["emails"] = [
            email
            for email in contacts["emails"]
            if page_domain_l.split("www.")[-1] in email
        ]
    if name:
        contacts["emails"] = _filter_scored_emails(
            contacts.get("emails") or [],
            name,
            domains,
            structured=bool(contacts.get("structured")),
        )
    return contacts


def _evaluate_fetched_page(
    *,
    html: str,
    page_url: str,
    name: str,
    affiliation: str,
    url_score: float,
    email_domains: list[str],
) -> dict[str, Any] | None:
    contacts = _extract_contacts_from_html(
        html,
        page_url,
        name=name,
        email_domains=email_domains,
    )
    name_parts = [part for part in _name_parts(name) if len(part) > 2]
    page_text = _normalize_text(html)
    name_in_page = bool(name_parts) and all(part in page_text for part in name_parts)
    if contacts.get("emails") and (
        "contact-name" in html.lower()
        or _extract_from_directory_blocks(html, name, email_domains=email_domains)
    ):
        name_in_page = True
    structured = bool(contacts.get("structured")) or bool(
        contacts.get("emails")
        and (
            "contact-name" in html.lower()
            or _extract_from_directory_blocks(html, name, email_domains=email_domains)
        )
    )
    if not contacts.get("emails"):
        if _is_search_results_page(page_url):
            return None
        if not name_in_page:
            return None
    else:
        contacts = dict(contacts)
        contacts["structured"] = structured
        best_email, email_score = _pick_best_email(
            contacts["emails"],
            name,
            email_domains,
            structured=structured,
        )
        contacts["emails"] = [best_email] if best_email else []
        if not contacts["emails"]:
            return None
    return _web_profile_from_page(
        page_url=page_url,
        name=name,
        contacts=contacts,
        name_in_page=name_in_page,
        url_score=url_score,
        structured=structured,
        email_domains=email_domains,
    )


def _fetch_web_profile(
    session: requests.Session,
    name: str,
    affiliation: str,
) -> dict[str, Any] | None:
    email_domains = _institution_domains(affiliation)
    best_profile: dict[str, Any] | None = None

    def consider(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
        nonlocal best_profile
        if not candidate:
            return best_profile
        candidate = dict(candidate)
        candidate.pop("_score", None)
        best_profile = _merge_web_profiles(
            best_profile,
            candidate,
            name=name,
            email_domains=email_domains,
        )
        return best_profile

    # 1. Direct profile URL guesses (cheap; often exact staff page).
    direct_urls = _institution_profile_candidates(name, affiliation)
    consider(
        _try_urls_for_profile(
            session,
            direct_urls,
            name=name,
            affiliation=affiliation,
            email_domains=email_domains,
        )
    )
    if best_profile and best_profile.get("emails") and best_profile.get("structured"):
        best_profile.pop("_score", None)
        return best_profile

    # 2. Paginated institution directories (AIMS, NSU, UQ search, etc.).
    consider(_crawl_institution_directories(session, name, affiliation))
    if best_profile and best_profile.get("emails") and best_profile.get("structured"):
        best_profile.pop("_score", None)
        return best_profile

    # 3. On-site search pages.
    fallback_urls: list[str] = []
    seen: set[str] = set(direct_urls)
    for url in _institution_search_candidates(name, affiliation):
        if url not in seen:
            seen.add(url)
            fallback_urls.append(url)
    consider(
        _try_urls_for_profile(
            session,
            fallback_urls,
            name=name,
            affiliation=affiliation,
            email_domains=email_domains,
        )
    )

    # 4. Google-like SERP: "{name} {institution}".
    serp_urls = _collect_serp_urls(session, name, affiliation)
    seen.update(serp_urls)
    consider(
        _try_urls_for_profile(
            session,
            serp_urls[:SERP_FETCH_LIMIT],
            name=name,
            affiliation=affiliation,
            email_domains=email_domains,
        )
    )

    # 5. Broader SERP (name + lab / profile keywords).
    broad_urls = _collect_serp_urls(session, name, affiliation, broad=True)
    consider(
        _try_urls_for_profile(
            session,
            [url for url in broad_urls if url not in seen][:SERP_FETCH_LIMIT],
            name=name,
            affiliation=affiliation,
            email_domains=email_domains,
        )
    )

    if best_profile:
        best_profile.pop("_score", None)
    return best_profile


def _openalex_candidates(
    session: requests.Session,
    name: str,
    *,
    per_page: int = 8,
) -> list[dict[str, Any]]:
    params = {
        "search": _clean_name_for_search(name),
        "per-page": per_page,
        "select": "id,display_name,orcid,works_count,last_known_institutions,summary_stats",
    }
    for attempt in range(4):
        response = session.get(OPENALEX_API, params=params, timeout=30)
        if response.status_code == 429:
            time.sleep(1.5 * (attempt + 1))
            continue
        response.raise_for_status()
        payload = response.json()
        return payload.get("results") or []
    response.raise_for_status()
    return []


def _pick_openalex_match(
    candidates: list[dict[str, Any]],
    name: str,
    affiliation: str,
) -> tuple[dict[str, Any] | None, str]:
    best: dict[str, Any] | None = None
    best_score = 0.0
    for candidate in candidates:
        display_name = str(candidate.get("display_name") or "")
        name_score = _name_similarity(name, display_name)
        institutions = candidate.get("last_known_institutions") or []
        institution_names = [
            str(item.get("display_name") or "")
            for item in institutions
            if isinstance(item, dict)
        ]
        aff_score = 0.0
        if affiliation and institution_names:
            aff_score = max(
                _affiliation_similarity(affiliation, institution_name)
                for institution_name in institution_names
            )
        elif institution_names:
            aff_score = 0.35
        score = (0.72 * name_score) + (0.28 * aff_score)
        if score > best_score:
            best = candidate
            best_score = score

    if not best or best_score < 0.78:
        return None, "search"
    if best_score >= 0.9:
        return best, "high"
    if best_score >= 0.84:
        return best, "medium"
    return best, "low"


def _fetch_orcid_details(
    session: requests.Session,
    orcid_id: str,
) -> dict[str, Any]:
    details: dict[str, Any] = {
        "emails": [],
        "urls": [],
        "linkedin": None,
    }
    try:
        email_response = session.get(f"{ORCID_API}/{orcid_id}/email", timeout=20)
        if email_response.ok:
            payload = email_response.json()
            emails = payload.get("email") or []
            for item in emails:
                address = item.get("email")
                if address:
                    details["emails"].append(str(address))
        time.sleep(REQUEST_DELAY_SECONDS)
        url_response = session.get(
            f"{ORCID_API}/{orcid_id}/researcher-urls", timeout=20
        )
        if url_response.ok:
            payload = url_response.json()
            groups = payload.get("researcher-url") or []
            for group in groups:
                if not isinstance(group, dict):
                    continue
                for entry in group.get("url", []) or []:
                    url = None
                    label = "Website"
                    if isinstance(entry, str):
                        url = entry
                    elif isinstance(entry, dict):
                        label = entry.get("url-name") or label
                        url_field = entry.get("url")
                        if isinstance(url_field, dict):
                            url = url_field.get("value")
                        elif isinstance(url_field, str):
                            url = url_field
                    if not url:
                        continue
                    details["urls"].append({"label": str(label), "url": str(url)})
                    if "linkedin.com" in url.lower():
                        details["linkedin"] = str(url)
    except requests.RequestException:
        return details
    return details


def _build_profile_record(
    name: str,
    affiliation: str,
    *,
    openalex_match: dict[str, Any] | None,
    confidence: str,
    orcid_details: dict[str, Any] | None = None,
    web_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    links: list[dict[str, str]] = []
    primary: dict[str, str] | None = None

    if web_profile:
        page_url = web_profile.get("page_url")
        if page_url:
            links.append(
                {
                    "kind": "institution",
                    "label": "University profile",
                    "url": str(page_url),
                }
            )

    orcid_url = None
    if openalex_match:
        orcid_url = openalex_match.get("orcid")
        openalex_id = str(openalex_match.get("id") or "")
        if openalex_id:
            author_url = openalex_id.replace(
                "https://openalex.org/",
                "https://openalex.org/authors/",
            )
            links.append(
                {
                    "kind": "openalex",
                    "label": "OpenAlex profile",
                    "url": author_url,
                }
            )

    orcid_id = _orcid_id_from_url(orcid_url)
    if orcid_id:
        links.append(
            {
                "kind": "orcid",
                "label": "ORCID",
                "url": f"https://orcid.org/{orcid_id}",
            }
        )

    details = orcid_details or {}
    emails = list(web_profile.get("emails") or []) if web_profile else []
    for email in details.get("emails") or []:
        if email not in emails:
            emails.append(email)

    for item in details.get("urls") or []:
        url = item.get("url")
        if not url:
            continue
        if "linkedin.com" in url.lower():
            continue
        links.append(
            {
                "kind": "website",
                "label": str(item.get("label") or "Website"),
                "url": str(url),
            }
        )

    email_score = 0.0
    structured = bool(web_profile and web_profile.get("structured"))
    if emails:
        domains = _institution_domains(affiliation)
        best_email, email_score = _pick_best_email(
            emails,
            name,
            domains,
            structured=structured,
        )
        if best_email:
            primary = {
                "type": "email",
                "label": best_email,
                "url": f"mailto:{best_email}",
            }
            emails = [best_email]
        else:
            emails = []
    elif web_profile and web_profile.get("page_url"):
        primary = {
            "type": "institution",
            "label": "University profile",
            "url": str(web_profile["page_url"]),
        }
    elif orcid_id:
        primary = {
            "type": "orcid",
            "label": "ORCID profile",
            "url": f"https://orcid.org/{orcid_id}",
        }
    elif openalex_match:
        openalex_link = next(
            (item for item in links if item["kind"] == "openalex"), None
        )
        if openalex_link:
            primary = {
                "type": "openalex",
                "label": "Researcher profile",
                "url": openalex_link["url"],
            }

    links.append(_linkedin_search_link(name, affiliation))

    links.append(
        {
            "kind": "scholar_search",
            "label": "Search Google Scholar",
            "url": _scholar_search_url(name, affiliation),
        }
    )

    deduped_links: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for link in links:
        url = link["url"]
        if url in seen_urls:
            continue
        seen_urls.add(url)
        deduped_links.append(link)

    if web_profile and web_profile.get("confidence") in {"high", "medium"}:
        confidence = web_profile["confidence"]
    elif primary and primary.get("type") == "email":
        if email_score <= 0.0:
            email_score = float((web_profile or {}).get("email_score") or 0.0)
        if structured and email_score >= MIN_EMAIL_SCORE:
            confidence = "high"
        elif email_score >= MIN_EMAIL_SCORE:
            confidence = "medium"
        else:
            confidence = "low"

    record: dict[str, Any] = {
        "name": name,
        "affiliation": affiliation,
        "confidence": confidence,
        "primary": primary,
        "links": deduped_links,
        "lookup_version": LOOKUP_VERSION,
    }
    if structured:
        record["email_structured"] = True
    if email_score > 0.0:
        record["email_score"] = email_score
    if web_profile and web_profile.get("page_url"):
        record["institutional_page"] = web_profile["page_url"]

    personal_site = next(
        (
            link
            for link in deduped_links
            if link.get("kind") == "website"
            and link.get("url")
            and link.get("url") != "value"
            and "linkedin.com" not in link.get("url", "").lower()
        ),
        None,
    )
    if personal_site and not record.get("institutional_page"):
        record["profile_page"] = personal_site["url"]
        record["profile_page_label"] = personal_site.get("label") or "Personal website"

    return record


def lookup_speaker_profile(
    name: str,
    affiliation: str = "",
    *,
    session: requests.Session | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
) -> dict[str, Any]:
    own_session = session is None
    session = session or _session(user_agent=user_agent)
    openalex_match = None
    confidence = "search"
    orcid_details = None
    openalex_error: str | None = None

    try:
        web_profile = _fetch_web_profile(session, name, affiliation)

        if not (web_profile and web_profile.get("emails")):
            try:
                candidates = _openalex_candidates(session, name)
                time.sleep(REQUEST_DELAY_SECONDS)
                openalex_match, confidence = _pick_openalex_match(
                    candidates, name, affiliation
                )
                orcid_id = _orcid_id_from_url(
                    openalex_match.get("orcid") if openalex_match else None
                )
                if orcid_id:
                    orcid_details = _fetch_orcid_details(session, orcid_id)
                    time.sleep(REQUEST_DELAY_SECONDS)
            except requests.RequestException as exc:
                openalex_error = str(exc)

        profile = _build_profile_record(
            name,
            affiliation,
            openalex_match=openalex_match,
            confidence=confidence,
            orcid_details=orcid_details,
            web_profile=web_profile,
        )
        if openalex_error and not profile.get("primary"):
            profile["openalex_error"] = openalex_error
        return profile
    finally:
        if own_session:
            session.close()


def _is_low_value_profile(profile: dict[str, Any]) -> bool:
    primary = profile.get("primary") or {}
    if primary.get("type") == "email":
        return False
    page_url = str(profile.get("institutional_page") or primary.get("url") or "")
    if not page_url:
        return profile.get("confidence") in {"search", "low"}
    if _is_search_results_page(page_url) or _is_junk_profile_url(page_url):
        return True
    return profile.get("confidence") in {"search", "low"} and not profile.get(
        "institutional_page"
    )


def _should_refresh_cached(profile: dict[str, Any], *, retry_failed: bool) -> bool:
    if profile.get("verified"):
        return False
    if profile.get("lookup_version", 0) < LOOKUP_VERSION:
        return True
    if profile.get("error"):
        return True
    if retry_failed and _is_low_value_profile(profile):
        return True
    if (
        retry_failed
        and profile.get("confidence") in {"search", "low"}
        and not profile.get("primary")
    ):
        return True
    if (
        retry_failed
        and not profile.get("institutional_page")
        and profile.get("confidence") == "search"
    ):
        return True
    return False


@dataclass
class ProfileBuildStats:
    total: int = 0
    cached: int = 0
    queried: int = 0
    success: int = 0
    partial: int = 0
    failed: int = 0
    brave_requests: int = 0

    @property
    def resolved(self) -> int:
        return self.success + self.partial


def classify_profile_outcome(profile: dict[str, Any]) -> str:
    """Return success, partial, or failed for a profile record."""
    if profile.get("error"):
        return "failed"
    primary = profile.get("primary") or {}
    if primary.get("type") == "email":
        return "success"
    if profile.get("institutional_page") or profile.get("profile_page"):
        return "success"
    if primary.get("type") in {"institution", "linkedin", "orcid", "openalex"}:
        return "partial"
    if profile.get("confidence") in {"high", "medium"}:
        return "partial"
    return "failed"


def summarize_profiles(profiles: dict[str, dict[str, Any]]) -> dict[str, int]:
    counts = {
        "email": 0,
        "institution": 0,
        "profile_page": 0,
        "partial": 0,
        "failed": 0,
    }
    for profile in profiles.values():
        outcome = classify_profile_outcome(profile)
        if outcome == "failed":
            counts["failed"] += 1
        elif outcome == "partial":
            counts["partial"] += 1
        if (profile.get("primary") or {}).get("type") == "email":
            counts["email"] += 1
        if profile.get("institutional_page"):
            counts["institution"] += 1
        if profile.get("profile_page"):
            counts["profile_page"] += 1
    return counts


def print_profile_build_summary(
    stats: ProfileBuildStats,
    *,
    cache_path: str | Path,
    output_path: str | Path | None = None,
    profile_counts: dict[str, int] | None = None,
    console: Console | None = None,
) -> None:
    console = console or _CONSOLE
    run_table = Table(title="Lookup run", show_header=True, header_style="bold")
    run_table.add_column("Metric", style="cyan")
    run_table.add_column("Count", justify="right")
    run_table.add_row("Speakers in scope", str(stats.total))
    if stats.queried or stats.success or stats.partial or stats.failed:
        run_table.add_row("Loaded from cache", str(stats.cached))
        run_table.add_row("Queried this run", str(stats.queried))
        run_table.add_row(
            "[green]Success[/] (email or profile page)", str(stats.success)
        )
        run_table.add_row(
            "[yellow]Partial[/] (ORCID / OpenAlex / LinkedIn)", str(stats.partial)
        )
        run_table.add_row("[red]Failed[/] (search-only or error)", str(stats.failed))
        if stats.brave_requests:
            run_table.add_row("Brave Search API requests", str(stats.brave_requests))
        console.print(run_table)
    elif stats.total:
        run_table.add_row("Profiles in cache", str(stats.cached or stats.total))
        console.print(run_table)

    if profile_counts:
        totals = Table(
            title="Cached export totals", show_header=True, header_style="bold"
        )
        totals.add_column("Contact type", style="cyan")
        totals.add_column("Speakers", justify="right")
        totals.add_row("Public email", str(profile_counts.get("email", 0)))
        totals.add_row(
            "University profile page", str(profile_counts.get("institution", 0))
        )
        totals.add_row("Personal website", str(profile_counts.get("profile_page", 0)))
        totals.add_row("Partial matches only", str(profile_counts.get("partial", 0)))
        totals.add_row("No useful contact", str(profile_counts.get("failed", 0)))
        console.print(totals)

    footer = Text()
    footer.append(f"Cache: {Path(cache_path)}", style="dim")
    if output_path:
        footer.append(f"\nExport: {Path(output_path)}", style="dim")
    console.print(Panel(footer, title="Saved", border_style="green"))


def load_profile_cache(
    path: str | Path = DEFAULT_CACHE_PATH,
) -> dict[str, dict[str, Any]]:
    cache_path = Path(path)
    if not cache_path.exists():
        return {}
    with cache_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_profile_cache(
    cache: dict[str, dict[str, Any]],
    path: str | Path = DEFAULT_CACHE_PATH,
) -> Path:
    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("w", encoding="utf-8") as handle:
        json.dump(cache, handle, indent=2, ensure_ascii=True)
        handle.write("\n")
    return cache_path


def _lookup_one_speaker(
    name: str,
    affiliation: str,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
) -> tuple[str, str, dict[str, Any], str]:
    try:
        profile = lookup_speaker_profile(
            name,
            affiliation,
            session=None,
            user_agent=user_agent,
        )
    except Exception as exc:
        profile = _build_profile_record(
            name,
            affiliation,
            openalex_match=None,
            confidence="search",
        )
        profile["error"] = str(exc)
    return name, affiliation, profile, classify_profile_outcome(profile)


def _record_lookup_outcome(stats: ProfileBuildStats, outcome: str) -> None:
    stats.queried += 1
    if outcome == "success":
        stats.success += 1
    elif outcome == "partial":
        stats.partial += 1
    else:
        stats.failed += 1


def build_speaker_profiles(
    speakers: list[tuple[str, str]],
    *,
    cache_path: str | Path = DEFAULT_CACHE_PATH,
    keys_path: str | Path = DEFAULT_KEYS_PATH,
    user_agent: str = DEFAULT_USER_AGENT,
    show_progress: bool = False,
    limit: int | None = None,
    retry_failed: bool = False,
    names: list[str] | None = None,
    console: Console | None = None,
    workers: int = DEFAULT_WORKERS,
    brave_budget: int | None = DEFAULT_BRAVE_BUDGET,
) -> tuple[dict[str, dict[str, Any]], ProfileBuildStats]:
    brave_key = configure_brave_search(keys_path=keys_path, budget=brave_budget)
    cache = load_profile_cache(cache_path)
    profiles_by_name: dict[str, dict[str, Any]] = {}
    unique_pairs: list[tuple[str, str]] = []
    seen_names: set[str] = set()
    name_filter = {name.strip() for name in names} if names else None
    console = console or _CONSOLE
    stats = ProfileBuildStats()
    workers = max(1, int(workers))

    for name, affiliation in speakers:
        cleaned_name = name.strip()
        if not cleaned_name or cleaned_name in seen_names:
            continue
        if name_filter is not None and cleaned_name not in name_filter:
            continue
        seen_names.add(cleaned_name)
        unique_pairs.append((cleaned_name, affiliation.strip()))

    if limit is not None:
        unique_pairs = unique_pairs[:limit]

    stats.total = len(unique_pairs)
    cached_pairs: list[tuple[str, str]] = []
    pending_pairs: list[tuple[str, str]] = []
    for name, affiliation in unique_pairs:
        key = _profile_key(name, affiliation)
        cached = cache.get(key)
        if cached and not _should_refresh_cached(cached, retry_failed=retry_failed):
            cached_pairs.append((name, affiliation))
            profiles_by_name[name] = cached
        else:
            pending_pairs.append((name, affiliation))

    stats.cached = len(cached_pairs)

    if show_progress and stats.total:
        worker_note = f" · [magenta]{workers} workers[/]" if workers > 1 else ""
        search_note = ""
        if brave_key:
            budget_note = (
                f"{brave_budget:,} max" if brave_budget is not None else "unlimited"
            )
            search_note = f" · [cyan]Brave Search[/] ({budget_note} requests)"
        console.print(
            Panel(
                f"[bold]{stats.total:,}[/] speakers · "
                f"[dim]{stats.cached:,} cached[/] · "
                f"[cyan]{len(pending_pairs):,} to query[/]"
                + worker_note
                + search_note
                + (" · [yellow]retry failed[/]" if retry_failed else ""),
                title="Speaker profile lookup",
                border_style="blue",
            )
        )

    cache_lock = threading.Lock()
    stats_lock = threading.Lock()
    completed = 0
    save_every = 25

    def persist_profile(name: str, affiliation: str, profile: dict[str, Any]) -> None:
        nonlocal completed
        key = _profile_key(name, affiliation)
        profile.pop("phones", None)
        with cache_lock:
            existing = cache.get(key)
            if existing and existing.get("verified"):
                profiles_by_name[name] = existing
                return
            cache[key] = profile
            profiles_by_name[name] = profile
            completed += 1
            if completed % save_every == 0:
                save_profile_cache(cache, cache_path)

    def run_parallel(progress=None, task_id=None) -> None:
        if not pending_pairs:
            return

        def on_result(
            name: str, affiliation: str, profile: dict[str, Any], outcome: str
        ) -> None:
            with stats_lock:
                _record_lookup_outcome(stats, outcome)
            persist_profile(name, affiliation, profile)
            if progress is None or task_id is None:
                return
            short_name = name if len(name) <= 36 else f"{name[:33]}..."
            with stats_lock:
                progress.update(
                    task_id,
                    description=(
                        f"[cyan]{short_name}[/] · "
                        f"[green]{stats.success}[/] ok · "
                        f"[yellow]{stats.partial}[/] part · "
                        f"[red]{stats.failed}[/] fail"
                    ),
                    success=stats.success,
                    partial=stats.partial,
                    failed=stats.failed,
                )
                progress.advance(task_id)

        if workers == 1:
            for name, affiliation in pending_pairs:
                on_result(
                    *_lookup_one_speaker(name, affiliation, user_agent=user_agent)
                )
            return

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    _lookup_one_speaker, name, affiliation, user_agent=user_agent
                )
                for name, affiliation in pending_pairs
            ]
            for future in as_completed(futures):
                on_result(*future.result())

    if show_progress and stats.total:
        from rich.progress import (
            BarColumn,
            MofNCompleteColumn,
            Progress,
            SpinnerColumn,
            TextColumn,
            TimeElapsedColumn,
            TimeRemainingColumn,
        )

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("[green]{task.fields[success]}[/] ok"),
            TextColumn("[yellow]{task.fields[partial]}[/] part"),
            TextColumn("[red]{task.fields[failed]}[/] fail"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=False,
        ) as progress:
            task_id = progress.add_task(
                "Looking up speaker profiles",
                total=stats.total,
                success=0,
                partial=0,
                failed=0,
            )
            for name, affiliation in cached_pairs:
                short_name = name if len(name) <= 36 else f"{name[:33]}..."
                progress.update(
                    task_id,
                    description=f"[dim]Cached[/] {short_name}",
                    success=stats.success,
                    partial=stats.partial,
                    failed=stats.failed,
                )
                progress.advance(task_id)
            run_parallel(progress, task_id)
    else:
        run_parallel()

    save_profile_cache(cache, cache_path)
    stats.brave_requests = brave_api_query_count()
    return profiles_by_name, stats


def _preserve_verified_profile(
    existing: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    preserved = dict(incoming)
    for field in (
        "verified",
        "primary",
        "confidence",
        "institutional_page",
        "profile_page",
        "profile_page_label",
        "email_score",
        "email_structured",
    ):
        if field in existing:
            preserved[field] = existing[field]
    preserved["verified"] = True
    return preserved


def _is_public_junk_url(url: str | None) -> bool:
    if not url:
        return False
    lowered = str(url).lower()
    if any(pattern in lowered for pattern in _PUBLIC_JUNK_URL_PATTERNS):
        return True
    return _is_untrusted_profile_url(url)


def _is_untrusted_profile_url(url: str | None) -> bool:
    """Return True when a URL is not a reliable personal/institutional profile page."""
    if not url:
        return False
    text = str(url).strip()
    if not text:
        return False
    if any(pattern in text.lower() for pattern in _PUBLIC_JUNK_URL_PATTERNS):
        return True
    if any(regex.search(text) for regex in _UNTRUSTED_PROFILE_URL_RES):
        return True
    return any(regex.search(text) for regex in _DIRECTORY_LISTING_URL_RES)


def _is_untrusted_primary_email(profile: dict[str, Any]) -> bool:
    if profile.get("verified") is True:
        return False
    primary = profile.get("primary") or {}
    if primary.get("type") != "email":
        return False
    email = str(primary.get("label") or "").strip()
    if not email or "@" not in email:
        return True
    if _is_obviously_junk_email(email) or _is_generic_role_email(email):
        return True
    if _JUNK_EMAIL_RE.search(email):
        return True
    score = float(profile.get("email_score") or 0.0)
    if score <= 0.0:
        affiliation = str(profile.get("affiliation") or "")
        score = _email_plausibility_score(
            email,
            str(profile.get("name") or ""),
            _institution_domains(affiliation),
            structured=bool(profile.get("email_structured")),
        )
        profile["email_score"] = score
    return score < MIN_EMAIL_SCORE


def conservative_clean_profile(profile: dict[str, Any]) -> dict[str, int]:
    """Remove untrusted URLs and emails from a profile. Prefer null over bad data."""
    stats = {
        "institutional_page_cleared": 0,
        "profile_page_cleared": 0,
        "primary_cleared": 0,
        "links_removed": 0,
        "verified_skipped": 0,
    }
    verified = profile.get("verified") is True

    def _clear_page_field(field: str, *, youtube_only: bool = False) -> None:
        value = profile.get(field)
        if not value:
            return
        text = str(value)
        untrusted = _is_untrusted_profile_url(text)
        if youtube_only and not (
            "youtube.com" in text.lower() or "youtu.be" in text.lower()
        ):
            return
        if not youtube_only and not untrusted:
            return
        profile.pop(field, None)
        if field == "profile_page":
            profile.pop("profile_page_label", None)
        stats[f"{field}_cleared"] += 1

    if verified:
        stats["verified_skipped"] += 1
        for field in ("institutional_page", "profile_page"):
            _clear_page_field(field, youtube_only=True)
        primary = profile.get("primary") or {}
        primary_url = str(primary.get("url") or "")
        if primary_url and (
            "youtube.com" in primary_url.lower() or "youtu.be" in primary_url.lower()
        ):
            profile["primary"] = None
            stats["primary_cleared"] += 1
        cleaned_links: list[dict[str, str]] = []
        for link in profile.get("links") or []:
            url = str(link.get("url") or "")
            if url and (
                "youtube.com" in url.lower() or "youtu.be" in url.lower()
            ):
                stats["links_removed"] += 1
                continue
            cleaned_links.append(link)
        profile["links"] = cleaned_links
        return stats

    for field in ("institutional_page", "profile_page"):
        _clear_page_field(field)

    primary = profile.get("primary") or {}
    primary_url = str(primary.get("url") or "")
    if primary.get("type") == "email" and _is_untrusted_primary_email(profile):
        profile["primary"] = None
        stats["primary_cleared"] += 1
    elif primary_url and _is_untrusted_profile_url(primary_url):
        profile["primary"] = None
        stats["primary_cleared"] += 1

    cleaned_links = []
    for link in profile.get("links") or []:
        url = str(link.get("url") or "")
        kind = str(link.get("kind") or "")
        if kind in {"scholar_search", "linkedin_search", "openalex", "orcid"}:
            cleaned_links.append(link)
            continue
        if url and _is_untrusted_profile_url(url):
            stats["links_removed"] += 1
            continue
        cleaned_links.append(link)
    profile["links"] = cleaned_links

    return stats


_PUBLIC_EXPORT_LINK_KINDS = frozenset(
    {
        "institution",
        "website",
        "linkedin_search",
        "scholar_search",
        "orcid",
        "openalex",
    }
)


def public_profile_for_export(profile: dict[str, Any]) -> dict[str, Any]:
    """Strip contact emails and other private fields for the public static site."""
    name = str(profile.get("name") or "")
    affiliation = str(profile.get("affiliation") or "")
    working = dict(profile)
    normalize_linkedin_links_in_profile(working)

    cleaned: dict[str, Any] = {
        "name": name,
        "affiliation": affiliation,
    }
    for field in (
        "profile_role",
        "affiliation_explicit",
        "confidence",
        "verified",
        "profile_page_label",
        "lookup_version",
    ):
        value = working.get(field)
        if value is not None:
            cleaned[field] = value

    for field in ("institutional_page", "profile_page"):
        value = working.get(field)
        if value and not _is_public_junk_url(str(value)):
            cleaned[field] = value

    links: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for link in working.get("links") or []:
        kind = str(link.get("kind") or "")
        url = str(link.get("url") or "")
        if kind not in _PUBLIC_EXPORT_LINK_KINDS:
            continue
        if not url or url.startswith("mailto:") or url in seen_urls:
            continue
        if _is_public_junk_url(url):
            continue
        seen_urls.add(url)
        links.append(
            {
                "kind": kind,
                "label": str(link.get("label") or "Link"),
                "url": url,
            }
        )

    search_link = _linkedin_search_link(name, affiliation)
    if search_link["url"] not in seen_urls:
        links.append(search_link)

    cleaned["links"] = links

    primary = working.get("primary") or {}
    if (
        primary.get("type") == "institution"
        and primary.get("url")
        and not _is_public_junk_url(str(primary["url"]))
    ):
        cleaned["primary"] = {
            "type": "institution",
            "label": str(primary.get("label") or "University profile"),
            "url": str(primary["url"]),
        }
    elif working.get("institutional_page") and not _is_public_junk_url(
        str(working["institutional_page"])
    ):
        cleaned["primary"] = {
            "type": "institution",
            "label": "University profile",
            "url": str(working["institutional_page"]),
        }
    else:
        cleaned["primary"] = None

    return cleaned


def sanitize_profile_for_export(profile: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible alias for the public site export."""
    return public_profile_for_export(profile)


def _profile_for_export(profile: dict[str, Any]) -> dict[str, Any]:
    return public_profile_for_export(profile)


def export_speaker_profiles_js(
    profiles_by_name: dict[str, dict[str, Any]],
    save_path: str | Path = "js/speaker-profiles.js",
) -> Path:
    output_path = Path(save_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    export_payload = {
        name: _profile_for_export(profile) for name, profile in profiles_by_name.items()
    }
    body = (
        "/** Generated by export_speaker_profiles – do not edit by hand. */\n"
        f"export const SPEAKER_PROFILES = {json.dumps(export_payload, ensure_ascii=True, indent=2)};\n"
    )
    output_path.write_text(body, encoding="utf-8")
    return output_path
