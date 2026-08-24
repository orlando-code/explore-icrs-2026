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

A JSON file containing presentation information (for both talks and posters) was obtained from the **[Github repository of the  grassroots conference app](https://github.com/nirivas/icrs2026)**. The JSON was originally scraped from the conference website via the associated EventsAir API.

Co-authorship is defined as **any person appearing on the author list of a conference presentation** (talk or poster). Where available, the presenting author's affiliation is taken from the programme; co-authors are assigned affiliations only if they are explicitly listed elsewhere (i.e. in the programme or delegate list).

---



## Data processing



### PDF ingestion

Extracting text from a semi-structured PDF is often non-exact – there were numerous errors in reading and organising text into a structured dataframe. There were also issues with reading accented characters; the same organisation referred to by different names; the same organisation with different country affiliations etc. 

Cleaning of the resulting database was largely automated but manually verified. The parser (`src/sources/delegates.py`) repairs common [mojibake](https://en.wikipedia.org/wiki/Mojibake), handles wrapped organisation/country lines, and flags incomplete organisation strings for manual override.

---



### Person registry and aliases

Thank goodness I find data cleaning satisfying (if vaguely soul-destroying). In many cases (~23%), delegate name from delegate list **≠** delegate name from presentation information on programme: people choose a variant for their name-badge, or perhaps got married! Names were standardised to prevent delegate double-counting. An algorithmic + fuzzy name-matching process partially matched **~1.4%** of those ~23%, and along with the **~21.6% that failed to match**, were manually reviewed.

After review and corrections, **86.8%** of programme speakers are linked to a delegate-list record (`person_registry.meta.json`: 1,676 of 1,930 names in the online programme). At this point, each person receives a stable internal key `icrs-p-`* (`data/registry/person_registry.csv`) for use in further processing. See [PERSON_REGISTRY.md](pipeline/PERSON_REGISTRY.md) for more information.

**Matching precedence:**

1. **Token overlap** between programme presenter and delegate-list name.
2. **Official ID review** – confirmed pairs from merged `delegate_id_match_review_*_merged.csv` files; ~1,865 links loaded.
3. **Manual overrides** – `data/registry/person_registry_overrides.csv` for exceptional name merges/splits.
4. **Union-find** merges linked names into a unique`person_key` for each delegate.

Name variants map through `data/registry/person_name_aliases.csv` (3,155 aliases).

**Attendance rule:** `attended=True` when the person **checked in at Innovators** (conference check-in export, ~2,069 rows). The July delegate PDF (`in_delegate_list=True`) is retained for matching and dropout analysis but is **not** used as attendance ground truth. Programme-only names without a check-in remain in the network but are excluded from attendance and emissions tallies.

**Privacy:** delegates who requested privacy on check-in and are **not** on the programme still contribute to the **headline emissions total**, but their pins are omitted from the emissions map and they are excluded from emissions search/offset self-registration. Programme authors remain visible on the map, network, and emissions views regardless of privacy flags.

Check-in rows are matched to registry `person_key` via official delegate ID, then name+organisation (+ country) fallbacks; unmatched check-ins become new registry rows (`needs_review`).

N.B. see [Caveats and limitations](#caveats-and-limitations) for dropout / empty-seat underestimates.

---



### Affiliation registry and aliases

As with delegates, affiliations were referred to by different names e.g. *'University of California at Berkeley'* and *'University of California - Berkeley'*, and were occasionally mis-spelt. Affiliations were standardised to a single name via the **affiliation registry** (`data/registry/affiliation_registry.csv`, 816 organisation+country rows from 1,160 raw variants). See [AFFILIATION_REGISTRY.md](pipeline/AFFILIATION_REGISTRY.md) for more information.

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

Fallback to state/national capital allowed **100%** of delegates to be assigned a location.

---



### Network construction

The **Network** tab shows co-authorship links derived from programme author lists. The network has two hierarchical structures:

- **Individual-level graph** – nodes = people; edges connect co-authors on the same talk (edge weight = shared talks).
- **Affiliation-level graph** – nodes = institutions; edges connect affiliations represented on the same talk.

Presentation details include the title, presentation type (poster, oral presentation, or keynote), full abstract, and list of co-authors. In addition, I used a lightweight, locally-hosted large language model (LLM; [Meta's Ollama](https://ollama.com/library/llama3)) to quantify the top four most similar talks, based on the abstract and title. I hope this will be useful for finding collaborators and conference follow-ups!

Co-authors and their links are shown in the network and appear light blue if they didn't attend the conference. However, the online programme author lists unfortunately made it impossible to match co-authors to their affiliations.

---



### Contacts

For the top 500 delegates (ranked by number of co-authorships), **institutional webpages and email addresses** were scraped from the web using the **[Brave Search API](https://brave.com/search/api/)** and **manually verified**. See [Ethics, privacy, and protection](#ethics-privacy-and-protection).

In addition, the option to copy the delegates' details (full name and affiliation) to clipboard as well as a link to their name and affiliation searched via **[LinkedIn](https://www.linkedin.com/feed/)** aim to speed up searching for a specific contact online. 

---



### Emissions

Return-trip **[CO₂e](https://www.climatepartner.com/en/knowledge/glossary/carbon-dioxide-equivalent)** (carbon dioxide equivalent emissions) **to Auckland** were estimated for each attending delegate using the location of their primary affiliation location as follows:


| Origin                                                                   | Assumption                                                                                                                                                        |
| ------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Outside New Zealand, or >400 km from Auckland (that includes Wellington) | Return **economy flight** to Auckland                                                                                                                             |
| New Zealand, within ~400 km                                              | Return **shared car** trip with average occupancy (1.54 according to the [New Zealand transport agency](https://www.nzta.govt.nz/resources/research/reports/399)) |


Route emissions come from the **[emissions.dev](https://emissions.dev) Travel API**. Flights are assumed to be in economy class: premium economy and business would incur **1.6×** and **2.9×** multipliers respectively.

**Headline figures (delegates pool):** estimated travel CO₂e across **checked-in** delegates with geocoded affiliations and cached routes. The emissions tab notes how many July-list delegates did not check in; totals are an **underestimate** because empty booked seats from last-minute drop-outs are not counted.

**Carbon contributions:** delegates may self-report contributions to a carbon/biodiversity project via a lightweight **API** (running on [Fly.io](https://fly.io/), SQLite) and gradually turn the map **from red to green**. Only **aggregate counts per affiliation** are published, never individuals' contributions: this isn't about singling anyone out; it's about quantifying the collective emissions of a research field. Additionally, in order to preserve anonymity, any country with fewer than three delegates in attendance is visually grouped with their neighbour(s).

In the '*Putting it in context*' tab, ****National per-capita emissions use World Bank **[EN.GHG.CO2.PC.CE.AR5](https://data.worldbank.org/indicator/EN.GHG.CO2.PC.CE.AR5)** (2024 release, metric tonnes CO₂e per person excluding LULUCF (Land Use, Land-Use Change and Forestry)). Aggregate travel totals are also compared to the [UNEP Emissions Gap Report 2020](https://www.unep.org/emissions-gap-report-2020) benchmark of **2.1 t CO₂e fair annual per-capita emissions by 2030** (`FAIR_PER_CAPITA_TONNES_CO2E_2030` in `src/emissions/travel_emissions.py`). While this report is worth a read, it's important to remember that socioeconomic status and historical emissions would make this 'fair share' value differ greatly between individuals: it's a bit of a utopian, long-term metric.

**Having problems registering your contribution?** The conference organisers are currently missing ~89 delegates' IDs. If this is you, you'll get an *'Incorrect delegate ID. Check the code from your confirmation email.'* error, despite entering the right code. If this is you, please get in touch at [rt582@cam.ac.uk](rt582@cam.ac.uk) and I'll help you out!

*N.B. Your unique ID is a 2-5 digit number e.g. 12 or 12345 and can be found at the top of every email from [teawa@conference.nz](mailto:teawa@conference.nz)*

---



## Ethics, privacy, and protection

While institutional pages and publicly-listed email addresses are available online – and are presumably intended to be found – grouping them in one neat location online may make it easier for bad actors and bots to misuse.

I've taken a number of steps to help mitigate this:

- **Verified contact lookup** requires [Cloudflare Turnstile](https://www.cloudflare.com/products/turnstile/); responses return at most one email per verified name+affiliation pair.
- **Contribution registrations** store an anonymous hashed attendee ID (`offset-xxxxxxxx`); the public API returns **counts only**, not who has or hasn't offset.
- The organisers' delegate PDF, files containing contact information, and API caches are never made available online.
- Map exclusions (`data/overrides/map_excluded_names.txt`) allow named individuals to be omitted from the public map – just get in touch at [rt582@cam.ac.uk](rt582@cam.ac.uk) and I can remove you!

---



## Caveats and limitations

**Check-in vs delegate list** – attendance and headline emissions use Innovators **check-in** data, not the July delegate PDF. People on the PDF who did not check in are excluded from totals (they likely dropped out), which **underestimates** conference-scale emissions: many would still have held booked seats. Conversely, check-in-only attendees not on the PDF are included.

**Inaccurate/out of date delegate list** – the delegate list was provided ~10 days before the start of the conference. A number of people who appear on that list withdrew at the last minute and did not check in.

**Co-authorship** – classed as any person appearing on the authorship of the conference presentation: it should be noted that this may have changed between applying to the conference and delivering the presentation. It also does not imply that the project is published or peer-reviewed yet.

**Affiliations with no location** – many delegates belonging to international or small organisations do not have an obvious working location. Where location was impossible to estimate from the affiliation (and believe me, I searched manually wherever necessary!), the capital city of the state/country was used as a fallback e.g. an organisation with country *'United States'* but no obvious location would be assigned to its state capital if the state was mentioned in the affiliation title; Washington D.C. if not.

**Seemingly contradictory affiliation locations** – a large number of delegates listed institutional affiliations e.g. *'University of California - Berkeley'* in a different country from the institute e.g. *'India'* rather than the *'United States'*. I've assumed that this means that the delegate is working for the named organisation somewhere in the named country. Since there is no obvious address for this work, the country's state/national capital was used as a fallback. Map pins use this location while retaining the organisation label e.g. there's an instance of the *Bermuda Institute of Ocean Sciences* in New Caledonia.

**Emissions uncertainty** – 515 delegates' travel routes use country-level origins only (mapping to state/national capital). This could lead to either an under- or over-estimate depending on the capitals' distance to Auckland. Cabin class is assumed economy and empty seats are ignored.

**Not all flights are equal** – **[emissions.dev](https://emissions.dev) estimates flight emissions using great-circle distances from the origin to the destination. This overlooks the (often many) shorter legs required to transit around the world – I took three flights to get here from the UK, for example! Since a disproportionate amount of emissions from flying come from the takeoff, multiple legs are often more emitting – and travel further – than this approximation. This results in an understimate of flight emissions. On top of this, different models of planes emit different amounts, and taking a plane at night generally [directly contributes to global heating by emitting contrails](https://map.contrails.org/)...! The API averages all of this information out, so take the exact value with a pinch of salt!

**Non-speaking delegates** – 288 delegates on the list have no programme talk; they appear on the map (and emissions view when toggled) but not in the network unless there are also listed as co-authors.

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