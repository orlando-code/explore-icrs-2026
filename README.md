# ICRS 2026 speaker affiliations

Interactive map and co-authorship network for ICRS 2026 speakers, geocoded by affiliation and centred on Auckland.

**Live site:** https://orlando-code.github.io/explore-icrs-2026/

Regenerate speaker profile/contact links for the network tab:

```bash
# Refresh failed / outdated lookups (parallel by default)
python scripts/export_speaker_profiles.py --retry-failed

# Tune concurrency if you hit rate limits (OpenAlex, DuckDuckGo)
python scripts/export_speaker_profiles.py --retry-failed --workers 4

# Re-export JS from cache only
python scripts/export_speaker_profiles.py --export-only
```
