/** Fetch World Bank EN.GHG.CO2.PC.CE.AR5 (2024) and refresh emissions comparisons. */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const nationalPath = join(root, "data/national_per_capita_co2.json");
const emissionsPath = join(root, "js/emissions-data.js");
const INDICATOR = "EN.GHG.CO2.PC.CE.AR5";
const YEAR = 2024;
const SOURCE_URL = "https://data.worldbank.org/indicator/EN.GHG.CO2.PC.CE.AR5";
const MIN_COUNTRY_ATTENDEES = 3;
const MIN_NATIONAL_PER_CAPITA_TONNES = 0.2;
const TREE_KG_PER_YEAR = 22;
const ILLUSTRATIVE_LOW = ["VU", "TZ", "CM", "FJ", "PG"];
const ILLUSTRATIVE_HIGH = ["US", "AU", "CA", "SA", "AE", "QA"];

async function fetchIndicatorYear(year) {
  const values = new Map();
  let page = 1;
  while (true) {
    const url = new URL(`https://api.worldbank.org/v2/country/all/indicator/${INDICATOR}`);
    url.searchParams.set("format", "json");
    url.searchParams.set("per_page", "20000");
    url.searchParams.set("date", String(year));
    url.searchParams.set("page", String(page));
    const response = await fetch(url);
    if (!response.ok) throw new Error(`World Bank API failed: ${response.status}`);
    const payload = await response.json();
    const [meta, rows] = payload;
    for (const row of rows) {
      const code = row?.country?.id;
      if (!code || row.value == null) continue;
      values.set(code, Number(row.value));
    }
    if (page >= Number(meta.pages || 1)) break;
    page += 1;
  }
  return values;
}

async function fetchMostRecent(code) {
  const url = new URL(`https://api.worldbank.org/v2/country/${code}/indicator/${INDICATOR}`);
  url.searchParams.set("format", "json");
  url.searchParams.set("mrv", "1");
  const response = await fetch(url);
  if (!response.ok) return null;
  const [, rows] = await response.json();
  const value = rows?.[0]?.value;
  return value == null ? null : Number(value);
}

function buildNationalPayload(existingCodes, valuesByCode) {
  const countries = {};
  for (const code of existingCodes) {
    let tonnes = valuesByCode.get(code);
    if (tonnes == null) continue;
    countries[code] = {
      tonnes_co2e_per_capita: Math.round(tonnes * 1000) / 1000,
      kg_co2e_per_capita: Math.round(tonnes * 1000 * 10) / 10,
    };
  }
  return {
    countries,
    meta: {
      indicator: INDICATOR,
      source_label: `World Bank national CO₂ per capita (${YEAR})`,
      source_url: SOURCE_URL,
      unit: "metric tonnes CO2e per capita (excl. LULUCF)",
      year: YEAR,
    },
  };
}

function estimatesFromByCountry(byCountry, fallbackPerAttendeeKg) {
  const rows = [];
  for (const [index, row] of byCountry.entries()) {
    const code = String(row.origin_country || "").trim();
    if (!code) continue;
    let attendeeCount = row.attendee_count;
    const co2eKg = row.co2e_kg;
    let perAttendee = row.co2e_per_attendee_kg;
    if (attendeeCount == null && co2eKg != null && perAttendee != null) {
      attendeeCount = Math.max(1, Math.round(co2eKg / perAttendee));
    }
    if (attendeeCount == null && co2eKg != null && fallbackPerAttendeeKg) {
      attendeeCount = Math.max(1, Math.round(co2eKg / fallbackPerAttendeeKg));
    }
    if (!attendeeCount) continue;
    if (perAttendee == null && co2eKg != null) {
      perAttendee = co2eKg / attendeeCount;
    }
    if (perAttendee == null) continue;
    for (let sub = 0; sub < attendeeCount; sub += 1) {
      rows.push({ origin_country: code, co2e_kg: perAttendee });
    }
  }
  return rows;
}

function buildEmissionsContext(estimates, totalCo2eKg, nationalByIso2, attendeeTotal) {
  const byCountry = new Map();
  for (const row of estimates) {
    const code = row.origin_country;
    const bucket = byCountry.get(code) || { count: 0, total: 0 };
    bucket.count += 1;
    bucket.total += row.co2e_kg;
    byCountry.set(code, bucket);
  }

  const rows = [];
  for (const [origin_country, bucket] of byCountry.entries()) {
    if (bucket.count < MIN_COUNTRY_ATTENDEES) continue;
    const national = nationalByIso2[origin_country];
    const tonnes = national?.tonnes_co2e_per_capita;
    if (tonnes == null || tonnes < MIN_NATIONAL_PER_CAPITA_TONNES) continue;
    const co2e_per_attendee_kg = bucket.total / bucket.count;
    const national_kg_per_capita = tonnes * 1000;
    rows.push({
      origin_country,
      attendee_count: bucket.count,
      co2e_per_attendee_kg,
      national_tonnes_per_capita: tonnes,
      national_kg_per_capita,
      ratio_vs_national_annual: co2e_per_attendee_kg / national_kg_per_capita,
    });
  }

  const perAttendeeKg = totalCo2eKg / Math.max(attendeeTotal, 1);
  const context = {
    tree_years: Math.round(totalCo2eKg / TREE_KG_PER_YEAR),
    tree_kg_per_year_assumption: TREE_KG_PER_YEAR,
    per_attendee_kg: Math.round(perAttendeeKg * 10) / 10,
    country_avg_min_attendees: MIN_COUNTRY_ATTENDEES,
    national_per_capita_year: YEAR,
    sources: [
      {
        id: "travel",
        label: "Return-trip travel estimates",
        url: "https://emissions.dev/docs/api/travel",
        note: "emissions.dev Travel API (economy flights; Auckland shared car).",
      },
      {
        id: "national_per_capita",
        label: "National per-capita CO₂",
        url: SOURCE_URL,
        note: `World Bank ${INDICATOR}, ${YEAR}, metric tonnes CO₂e per person (excl. LULUCF).`,
      },
      {
        id: "tree_uptake",
        label: "Tree CO₂ uptake (~22 kg/yr)",
        url: "https://www.epa.gov/energy/greenhouse-gases-equivalencies-calculator-calculations-and-references",
        note: "US EPA GHG equivalencies (≈48 lb CO₂ per tree per year).",
      },
    ],
  };

  if (!rows.length) return context;
  rows.sort((a, b) => a.national_tonnes_per_capita - b.national_tonnes_per_capita);
  const lowest = rows[0];
  const highest = rows[rows.length - 1];
  const comparisonRow = (row) => ({
    origin_country: row.origin_country,
    co2e_per_attendee_kg: Math.round(row.co2e_per_attendee_kg * 10) / 10,
    attendee_count: row.attendee_count,
    national_tonnes_per_capita: Math.round(row.national_tonnes_per_capita * 1000) / 1000,
    national_kg_per_capita: Math.round(row.national_kg_per_capita * 10) / 10,
    ratio_vs_national_annual: Math.round(row.ratio_vs_national_annual * 100) / 100,
  });
  context.lowest_national_per_capita = comparisonRow(lowest);
  context.highest_national_per_capita = comparisonRow(highest);
  context.conference_vs_lowest_national = {
    origin_country: lowest.origin_country,
    national_tonnes_per_capita: Math.round(lowest.national_tonnes_per_capita * 1000) / 1000,
    conference_per_attendee_kg: context.per_attendee_kg,
    ratio_vs_national_annual:
      Math.round((context.per_attendee_kg / lowest.national_kg_per_capita) * 100) / 100,
  };
  context.conference_vs_highest_national = {
    origin_country: highest.origin_country,
    national_tonnes_per_capita: Math.round(highest.national_tonnes_per_capita * 1000) / 1000,
    conference_per_attendee_kg: context.per_attendee_kg,
    ratio_vs_national_annual:
      Math.round((context.per_attendee_kg / highest.national_kg_per_capita) * 100) / 100,
  };

  const present = new Set(estimates.map((row) => row.origin_country));
  const illustrative = [];
  for (const code of ILLUSTRATIVE_LOW) {
    if (!present.has(code) || !nationalByIso2[code]) continue;
    const tonnes = nationalByIso2[code].tonnes_co2e_per_capita;
    illustrative.push({
      role: "illustrative_low",
      origin_country: code,
      national_tonnes_per_capita: Math.round(tonnes * 1000) / 1000,
      national_kg_per_capita: Math.round(tonnes * 1000 * 10) / 10,
      conference_per_attendee_kg: context.per_attendee_kg,
      ratio_vs_national_annual:
        Math.round((context.per_attendee_kg / (tonnes * 1000)) * 100) / 100,
    });
    break;
  }
  for (const code of ILLUSTRATIVE_HIGH) {
    if (!present.has(code) || !nationalByIso2[code]) continue;
    const tonnes = nationalByIso2[code].tonnes_co2e_per_capita;
    illustrative.push({
      role: "illustrative_high",
      origin_country: code,
      national_tonnes_per_capita: Math.round(tonnes * 1000) / 1000,
      national_kg_per_capita: Math.round(tonnes * 1000 * 10) / 10,
      conference_per_attendee_kg: context.per_attendee_kg,
      ratio_vs_national_annual:
        Math.round((context.per_attendee_kg / (tonnes * 1000)) * 100) / 100,
    });
    break;
  }
  if (illustrative.length) context.illustrative_per_capita = illustrative;
  return context;
}

function refreshEmissionsSite(nationalByIso2) {
  const source = readFileSync(emissionsPath, "utf8");
  const prefix = "export const EMISSIONS_DATA = ";
  const start = source.indexOf(prefix) + prefix.length;
  const end = source.lastIndexOf(";\n");
  const payload = JSON.parse(source.slice(start, end));

  for (const poolName of ["speakers", "all_delegates"]) {
    const pool = payload[poolName];
    if (!pool) continue;
    const headline = pool.meta?.headline || {};
    const totalCo2eKg = Number(headline.co2e_kg || 0);
    const fallback = pool.meta?.context?.per_attendee_kg;
    const estimates = estimatesFromByCountry(pool.by_country || [], fallback);
    if (!estimates.length) continue;
    const attendeeTotal = Number(headline.attendees_estimated || estimates.length || 1);
    pool.meta.context = buildEmissionsContext(
      estimates,
      totalCo2eKg,
      nationalByIso2,
      attendeeTotal
    );
  }

  writeFileSync(
    emissionsPath,
    `/** Generated by estimate_travel_emissions.py – do not edit by hand. */\nexport const EMISSIONS_DATA = ${JSON.stringify(payload, null, 2)};\n`,
    "utf8"
  );
}

const existing = JSON.parse(readFileSync(nationalPath, "utf8"));
const existingCodes = Object.keys(existing.countries || {}).sort();
const valuesByCode = await fetchIndicatorYear(YEAR);
for (const code of existingCodes) {
  if (!valuesByCode.has(code)) {
    const mrv = await fetchMostRecent(code);
    if (mrv != null) valuesByCode.set(code, mrv);
  }
}
const payload = buildNationalPayload(existingCodes, valuesByCode);
writeFileSync(nationalPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
console.log(`Wrote ${nationalPath} (${Object.keys(payload.countries).length} countries, year ${YEAR})`);
refreshEmissionsSite(payload.countries);
console.log(`Refreshed national context in ${emissionsPath}`);
