#!/usr/bin/env node
/**
 * Copy deployable static assets for hosting under a subpath (e.g. /icrs2026-explorer/).
 *
 * Usage:
 *   node scripts/bundle_static_site.mjs <target-dir> [--base-path=/icrs2026-explorer]
 */

import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");

const args = process.argv.slice(2);
const basePathArg = args.find((arg) => arg.startsWith("--base-path="));
const basePath = basePathArg ? basePathArg.split("=")[1] : "/icrs2026-explorer";
const canonicalUrl = `https://orlando-codes.com${basePath.endsWith("/") ? basePath : `${basePath}/`}`;
const targetDir = args.find((arg) => !arg.startsWith("--"));
if (!targetDir) {
  console.error("Usage: node scripts/bundle_static_site.mjs <target-dir> [--base-path=/icrs2026-explorer]");
  process.exit(1);
}

const resolvedTargetDir = path.resolve(targetDir);

function patchIndexHtml(html) {
  let next = html;
  next = next.replace(
    /(<meta name="icrs-base-path" content=")[^"]*(")/,
    `$1${basePath}$2`
  );
  next = next.replace(
    /(<meta\s+name="icrs-canonical-url"\s+content=")[^"]*(")/,
    `$1${canonicalUrl}$2`
  );
  next = next.replace(
    /<link rel="canonical" href="[^"]*"/,
    `<link rel="canonical" href="${canonicalUrl}"`
  );
  return next;
}

rmSync(resolvedTargetDir, { recursive: true, force: true });
mkdirSync(resolvedTargetDir, { recursive: true });

for (const entry of ["css", "js", "assets"]) {
  cpSync(path.join(ROOT, entry), path.join(resolvedTargetDir, entry), { recursive: true });
}

mkdirSync(path.join(resolvedTargetDir, "data"), { recursive: true });
cpSync(
  path.join(ROOT, "data", "offset-registrations.json"),
  path.join(resolvedTargetDir, "data", "offset-registrations.json")
);

const indexHtml = patchIndexHtml(readFileSync(path.join(ROOT, "index.html"), "utf8"));
writeFileSync(path.join(resolvedTargetDir, "index.html"), indexHtml);

console.log(`Bundled static site to ${resolvedTargetDir}`);
console.log(`  base path: ${basePath}`);
console.log(`  canonical: ${canonicalUrl}`);
