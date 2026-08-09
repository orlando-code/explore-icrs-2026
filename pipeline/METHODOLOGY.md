# ICRS 2026 Explorer – end-to-end methodology

## Contents

- [ICRS 2026 Explorer – end-to-end methodology](#icrs-2026-explorer--end-to-end-methodology)
  - [Contents](#contents)
  - [Overview](#overview)
  - [Data sources](#data-sources)
    - [Delegate list](#delegate-list)
    - [Presentation titles, abstracts, and co-authorship](#presentation-titles-abstracts-and-co-authorship)
  - [Data processing](#data-processing)
    - [PDF ingestion](#pdf-ingestion)
    - [Person registry and aliases](#person-registry-and-aliases)
    - [Affiliation registry and aliases](#affiliation-registry-and-aliases)
    - [Geocoding](#geocoding)
    - [Network construction](#network-construction)
    - [Contacts](#contacts)
    - [Emissions](#emissions)
  - [Ethics, privacy, and protection](#ethics-privacy-and-protection)
  - [Caveats and limitations](#caveats-and-limitations)
  - [Application structure](#application-structure)

---

## Overview

The 2026 International Coral Reef Symposium (ICRS) took place in Auckland, New Zealand. To help channel the momentum and inspiration of the conference to facilitate connections and collaborations, I built the 'ICRS 2026 Explorer'. 

The web-app features an interactive map, a network linking delegates by co-authorship on conference talks, and a quantification of the travel emissions associated with attending the conference. 

The app is built using publicly-available data: the [most recent official delegate list](https://airdrive.eventsair.com/eventsairaueprod/production-innovators-public/20d10b81d8cd43ad9b0fc3a08e5695f4), the [online programme](https://innovators-icrs2026programme.eventsairsite.com/) (titles, abstracts, author lists), and in some cases, delegates' public webpages and emails.

I hope this will help and intrigue you! Please get in touch via [rt582@cam.ac.uk](mailto:rt582@cam.ac.uk) if you have any questions, suggestions, or concerns.

---

## Data sources

### Delegate list

Delegate information was taken from the [delegate list](https://airdrive.eventsair.com/eventsairaueprod/production-innovators-public/20d10b81d8cd43ad9b0fc3a08e5695f4) generated on **Thursday 9 July 2026** and distributed by email to delegates on the same day. The PDF was processed via the command-line **[Poppler](https://poppler.freedesktop.org/)** package (`pdftotext`, UTF-8, `-layout` mode).

Each row in the PDF is intended to conform to:

| first name | last name | organisation | country |

### Presentation titles, abstracts, and co-authorship

A JSON file containing presentation information (for both talks and posters) was obtained from the **[Github repository of the  grass-roots conference app](https://github.com/nirivas/icrs2026)**. This in turn was scraped from the conference website via the associated EventsAir API.

Co-authorship is defined as **any person appearing on the author list of a conference presentation** (talk or poster). The presenting author's affiliation is taken from the programme where available; other authors inherit affiliation only when explicitly listed elsewhere (i.e. in the programme or delegate list).

---

## Data processing

### PDF ingestion

Extracting text from a semi-structured PDF is often non-exact – there were numerous errors in reading and organising text into a structured dataframe.

There were also issues with reading accented characters; the same organisation referred to by different names; the same organisation with different country affiliations etc. Cleaning was largely automated but manually verified. The parser (`src/sources/delegates.py`) repairs common [mojibake](https://en.wikipedia.org/wiki/Mojibake), handles wrapped organisation/country lines, and flags incomplete organisation strings for downstream override.

---

### Person registry and aliases

Thank goodness I find data cleaning satisfying (if vaguely soul-destroying). In many cases (~20%), delegate name from delegate list **≠** delegate name from presentation information on programme: people choose a variant for their name-badge, or perhaps got married! These had to be standardised to make sure delegates weren't duplicated. An algorithmic + fuzzy name-matching process partially matched **~13.6%** of the missing 20%, and along with the **~6.9% that failed to match**, were manually reviewed.

After review and corrections, **93.5%** of programme speakers are linked to a delegate-list record (`person_registry.meta.json`: 1,915 of 2,048 names in the online programme). At this point, each person receives a stable internal key `icrs-p-`* (`data/registry/person_registry.csv`).

**Matching precedence:**

1. **Token overlap** between programme presenter and delegate-list name (rejects unsafe matches, e.g. "Sam King" ≠ "Sam King Fung Yiu").
2. **Official ID review** – confirmed pairs from merged `delegate_id_match_review_*_merged.csv` files; ~1,865 links loaded.
3. **Manual overrides** – `data/registry/person_registry_overrides.csv` for exceptional name merges/splits.
4. **Union-find** merges linked names into a unique`person_key` for each delegate.

Name variants map through `data/registry/person_name_aliases.csv` (3,032 aliases).

**Attendance rule:** `attended=True` only when the person appears on the delegate list (1,953 attended). Programme-only names (133) are retained for the network but excluded from attendance and emissions tallies, since not appearing on the delegate list implies they dropped out. N.B. see [Caveats and limitations](#caveats-and-limitations) for further discussion.

---

### Affiliation registry and aliases

As with delegates, affiliations were referred to by different names e.g. *'University of California at Berkeley'* and *'University of California - Berkeley'*, and were occasionally mis-spelt. Affiliations were standardised to a single name via the **affiliation registry** (`data/registry/affiliation_registry.csv`, 816 organisation+country rows from 1,160 raw variants).

**Standardisation sources (in order):**

1. Delegate list authority – `organisation` + `country` from `delegates.json`.
2. Affiliation parsing – trailing country segments validated with ISO-2 lookup from the delegate pdf. This handles organisation names containing commas e.g. would otherwise struggle to find where the organisation ends and the country begins for *Rethinking, Rebuilding, Regenerating Coral Reefs, Philippines*.
3. `data/geocodes/affiliation_display_aliases.json` – reviewed 293 display aliases.
4. Institution canonicalisation rules in geocoding code (e.g. BIOS, KAUST, WWF regional branches – where an organisation appears connected with multiple countries i.e. when someone works for an organisation in a different country).
5. `data/registry/affiliation_registry_overrides.csv` – manual merges.
6. `data/registry/affiliation_registry_unmatched_reviewed.csv` – manual review of affiliations which are missing countries, compound affiliations and primary/secondary splits (53 rows applied).
7. Geocode metadata from automated + manual coordinate files.

Compound affiliations (e.g. dual appointments) are split into **primary** and **secondary** organisation; secondary organisations are not plotted or given emissions unless another delegate lists them as their primary. As with delegates, each organisation(+location) is assigned a unique identifying key `icrs-a-`* to help with future processing.

---

### Geocoding

Locations (latitude/longitude coordinate pairs and where possible postal address) of delegates' affiliated institutes were geocoded via the **[Google Maps Geocoding API](https://developers.google.com/maps/documentation/geocoding)**. Committed coordinates live in `data/geocodes/affiliation_geocodes.csv` and were supplemented by manual corrections where necessary. 69 organisation-specific geographical overrides were necessary due to missing/inaccurate retrievals from Google.

Geolocations were manually verified as follows:

1. **Geocoding precise** – allow.
2. **Geocoding imprecise** (no exact address returned, usually because there were multiple results e.g. multiple university campuses) – search [Google Maps](https://www.google.com/maps) manually and take the largest/most central location e.g. main campus rather than satellites.
3. **Geocoding failed** – search online e.g. for company website to look for head offices. If no address available, fall back to state/country capital (see [Caveats and limitations](#caveats-and-limitations)).

**Override precedence** (highest first): `geocode_overrides.json` (manual ground truth) → `affiliation_geocodes.csv` (initial search) → `affiliation_geocodes_manual_01.csv` (corrected search) → display aliases (e.g. '*University of Konstanz*' rather than '*University Of Konstanz*' → delegate organisation overrides → reviewed affiliation registry → map exclusions.

**Foreign-delegate anchoring:** where an institute's physical home (from its name or institution rules) differs from the delegate's country – e.g. BIOS (Bermuda) staff based in New Caledonia, Bangor University (Wales) delegate in the Maldives – the **organisation label is kept** but map pins and travel routes anchor to the **delegate country's capital** (or a reviewed manual coordinate). A standardisation report is written to `pipeline/artifacts/foreign_delegate_anchors.csv` when the affiliations stage runs.

Current geocode coverage: **99.4%** of registry affiliations geocoded or use the state/national capital-fallback (`affiliation_registry.meta.json`). The remaining **five** affiliations (0.6%) were listed in the programme but not the delegate list, and where therefore omitted from the map and emissions calculations.



These rows are flagged `geocode_missing` in `data/registry/affiliation_registry.csv` and listed in `data/registry/affiliation_registry_unmatched.csv`.

---

### Network construction

The **Network** tab shows co-authorship links derived from programme author lists. The network has two hierarchical structures:

- **Individual-level graph** – nodes = people; edges connect co-authors on the same talk (edge weight = shared talks).
- **Affiliation-level graph** – nodes = institutions; edges connect affiliations represented on the same talk.

Talk details are exported into `js/locations.js` (affiliation `connection_count`) and `js/talks.js`. Speaker-level detail for richer cards lives in committed `js/speaker-profiles.js` (built outside the main pipeline – see `pipeline/README.md`).

**Affiliation inheritance (network only):** programme author lists often name co-authors without listing their institution. For network placement, a co-author with no affiliation in the programme or delegate list **inherits the presenting author's affiliation for that talk** (`src/site/plot_utils.py`). These nodes are flagged `affiliation_explicit: false` (~4,000 co-author placements); the UI labels them *"(inferred from a presenting author's talk)"*. If the person later matches the delegate list, their delegate affiliation overrides the inference and the flag becomes explicit. These should therefore be taken with a heavy pinch of salt!

---

### Contacts

Institutional webpages were scraped from the web using the **[Brave Search API](https://brave.com/search/api/)**. For the top 500 delegates (ranked by number of co-authorships) these are supplemented with **manually-verified email addresses** and institutional/personal webpages where available. See [Ethics, privacy, and protection](#ethics-privacy-and-protection).

In addition, the option to copy the delegates' details (full name and affiliation) to clipboard as well as a link to their name and affiliation searched via **[LinkedIn](https://www.linkedin.com/feed/)** and **[Google Scholar](https://scholar.google.com/)** aim to speed up searching for a specific contact online. 

---

### Emissions

Return-trip **[CO₂e](https://www.climatepartner.com/en/knowledge/glossary/carbon-dioxide-equivalent)** (carbon dioxide equivalent emissions) **to Auckland** is estimated per delegate using the location of their primary affiliation location:


| Origin                                        | Assumption                                                                                                                                                        |
| --------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Outside New Zealand, or >400 km from Auckland | Return **economy flight** to Auckland (AKL)                                                                                                                       |
| New Zealand, within ~400 km                   | Return **shared car** trip with average occupancy (1.54 according to the [New Zealand transport agency](https://www.nzta.govt.nz/resources/research/reports/399)) |


Route emissions come from the **[emissions.dev](https://emissions.dev) Travel API**. Flights are assumed to be in economy class: premium economy and business would incur **1.6×** and **2.9×** multipliers respectively.

**Headline figures (speakers pool, cache build):** estimated ~5,011 t CO₂e across geocoded delegates.

Map pins on the **Emissions** tab align with the main **Map** tab but only show locations with **CO₂e > 0**.

**Carbon contributions:** delegates may self-report contributions to a carbon/biodiversity project via a lightweight **API** (running on [Fly.io](https://fly.io/), SQLite). Only **aggregate counts per affiliation** are published, never individual offset status: this isn't about singling anyone out; it's about quantifying the collective emissions of a research field.

National per-capita context uses World Bank **[EN.GHG.CO2.PC.CE.AR5](https://data.worldbank.org/indicator/EN.GHG.CO2.PC.CE.AR5)** (2024 release, metric tonnes CO₂e per person excluding LULUCF). Aggregate travel totals are also compared to the [UNEP Emissions Gap Report 2020](https://www.unep.org/emissions-gap-report-2020) benchmark of **2.1 t CO₂e fair annual per-capita emissions by 2030** (`FAIR_PER_CAPITA_TONNES_CO2E_2030` in `src/emissions/travel_emissions.py`).

---

## Ethics, privacy, and protection

While institutional pages and publicly-listed email addresses are available online – and presumably intended to be found – grouping them in one neat location online may make it easier for bad actors and bots to misuse.

I've taken a number of steps to help mitigate this:

- **Verified contact lookup** requires [Cloudflare Turnstile](https://www.cloudflare.com/products/turnstile/); responses return at most one email per verified name+affiliation pair.
- **Offset registrations** store only a hashed attendee id (`offset-xxxxxxxx`); the public API returns **counts only**, not who has or hasn't offset.
- The organisers' delegate PDF, files containing contact information, and API caches are never made available online.
- Map exclusions (`data/overrides/map_excluded_names.txt`) allow named individuals to be omitted from the public map – just get in touch at [rt582@cam.ac.uk](rt582@cam.ac.uk) and I can remove you!

---

## Caveats and limitations

**Inaccurate/out of date delegate list** – the delegate list was provided ~10 days before the start of the conference. A number of people who appear on that list withdrew at the last minute, and therefore may not have made the trip to Auckland at all. This would overestimate the emissions directly attributable to those delegates – although most would have had a travel ticket booked, likely leading to an empty seat on a plane.

**Co-authorship** – classed as any person appearing on the authorship of the conference presentation: it should be noted that this may have changed between applying to the conference and delivering the presentation. It also does not imply that the project is published or peer-reviewed yet.

**Affiliations with no location** – many delegates belonging to international or small organisations do not have an obvious working location. Where location was impossible to estimate from the affiliation (and believe me, I searched manually wherever necessary!), the capital city of the state/country was used as a fallback e.g. an organisation with country *'United States'* but no obvious location would be assigned to its state capital if the state was mentioned in the name; New York if not.

**Contradictory affiliation locations** – a large number of delegates listed institutional affiliations e.g. *'University of California - Berkeley'* in a different country from the institute e.g. *'India'* rather than the *'United States'*. It is assumed that this that the delegate is working at an offshoot of their parent organisation in the country named. These were unpicked where possible e.g. of course *'the Nature Conservancy Venezuela, Bolivarian Republic of'* implies that the delegate works for TNC in Venezuela. Where impossible to decipher, the location of the named country's state/national capital was used as a fallback. The map pin retains this location while keeping the organisation label e.g. there's an instance of the *Bermuda Institute of Ocean Sciences* in New Caledonia.

**Emissions uncertainty** – 414 routes use country-level origins only (mapping to state/national capital). This could lead to either an under- or over-estimate. Cabin class is assumed economy and empty seats are ignored.

**Non-speaking delegates** – 288 delegates on the list have no programme talk; they appear on the map (and emissions view when toggled) but not as network speakers.

---

## Application structure

Static **HTML/CSS/JavaScript**; the wonderful [MapLibre GL](https://maplibre.org/) for maps; and [D3 for network visualisation.](https://d3-graph-gallery.com/network.html)


| Tab           | Role                                                                | Primary data                            |
| ------------- | ------------------------------------------------------------------- | --------------------------------------- |
| **Map**       | Affiliation pins; search by name, institution, talk keyword         | `js/locations.js`                       |
| **Network**   | Co-authorship graph; topic highlighting                             | `js/talks.js`, `js/speaker-profiles.js` |
| **Emissions** | CO₂e pins, national context, offset choropleth, self-report offsets | `js/emissions-data.js`, offset API      |


Live site: [orlando-codes.com/explore-icrs-2026](https://orlando-codes.com/explore-icrs-2026/)

---

*Thanks for reading this far – I hope you enjoy the tool!*