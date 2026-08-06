#!/usr/bin/env python3
"""Run the ICRS data pipeline end-to-end or stage-by-stage with verification."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.config import PIPELINE_STAGES, PipelineConfig
from pipeline.report import load_all_reports, print_report, print_summary
from pipeline.stages import STAGE_RUNNERS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild ICRS site data from raw sources with verification at each stage. "
            "Reports are written to pipeline/reports/<stage>.json."
        )
    )
    parser.add_argument(
        "stages",
        nargs="*",
        choices=[*PIPELINE_STAGES, "all"],
        help="Stages to run (default: all). Use 'all' for the full pipeline.",
    )
    parser.add_argument(
        "--from",
        dest="from_stage",
        choices=PIPELINE_STAGES,
        help="Run this stage and all later stages.",
    )
    parser.add_argument(
        "--refresh-delegates",
        action="store_true",
        help="Re-parse delegate PDF into data/sources/delegates.json.",
    )
    parser.add_argument(
        "--refresh-geocodes",
        action="store_true",
        help="Call Google geocoding API before verifying coverage (slow, needs keys.yaml).",
    )
    parser.add_argument(
        "--estimate-emissions",
        action="store_true",
        help="Re-query all travel routes via emissions.dev (primary API key).",
    )
    parser.add_argument(
        "--no-fetch-routes",
        action="store_true",
        help="Emissions stage: use travel cache only (no API calls).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Less console output from export scripts.",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print verification summary from existing reports and exit.",
    )
    return parser.parse_args()


def resolve_stages(args: argparse.Namespace) -> list[str]:
    if args.summary:
        return []

    if args.from_stage:
        start = PIPELINE_STAGES.index(args.from_stage)
        return list(PIPELINE_STAGES[start:])

    if not args.stages or "all" in args.stages:
        return list(PIPELINE_STAGES)

    return list(args.stages)


def run_stage(name: str, config: PipelineConfig, args: argparse.Namespace):
    runner = STAGE_RUNNERS[name]
    if name == "delegates":
        return runner(config, refresh=args.refresh_delegates)
    if name == "geocode":
        return runner(config, refresh=args.refresh_geocodes)
    if name == "export-site":
        return runner(config, quiet=args.quiet)
    if name == "emissions":
        return runner(
            config,
            fetch_missing=not args.no_fetch_routes,
            requery_all=args.estimate_emissions,
            quiet=args.quiet,
        )
    return runner(config)


def main() -> int:
    args = parse_args()
    config = PipelineConfig()

    if args.summary:
        print_summary(load_all_reports(config.reports_dir))
        return 0

    stages = resolve_stages(args)
    if not stages:
        print("No stages selected.", file=sys.stderr)
        return 1

    failed = False
    for name in stages:
        report = run_stage(name, config, args)
        report.save(config.report(name))
        print_report(report)
        if not report.ok:
            failed = True
            break

    print_summary(load_all_reports(config.reports_dir))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
