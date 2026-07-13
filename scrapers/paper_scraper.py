"""
Master paper scraper: imports each conference sub-scraper as a function, runs them,
then combines their output into a single abstracts CSV with content-derived UIDs
(see uid_utils) and all (empty) classification columns, ready to be fed to the
classifier.

Merge order: iclr, icml, neurips, naacl, facct

Sub-scrapers live in paper_subscrapers/ and each exposes an importable entry
point:
    iclr_paper_scraper.scrape_iclr(output)           -> async
    icml_paper_scraper.scrape_icml(output)           -> async
    neurips_paper_scraper.scrape_all_neurips(output) -> async
    naacl_scraper.parse_naacl(bib_file, ..., output) -> sync

Each conference's individual output CSV is written *into the paper_subscrapers/
folder* (iclr_abstracts.csv, icml_abstracts.csv, etc.); this master then reads
those intermediates back and concatenates them. The final combined CSV is
written to output_data/scrapers/abstracts.csv by default (see --output).

NOTE on NAACL: the NAACL step parses a BibTeX export rather than scraping the
web, so it needs the anthology file to exist on disk. It expects:
    input_data/naacl/aacl_anthology.bib   (NAACL_BIB below)
If that file is missing the NAACL step is skipped with a warning. If you move or
rename it, the run will produce no NAACL rows — update NAACL_BIB to match.

COMMENT: The scrapers seem reasonably durable after testing, but in general web  
scraping can be temperamental and rate limiting can mess it up. A better future
solution might be to point to the well structured data collected from the Paper
Copilot project at https://github.com/papercopilot/paperlists. We did not know it
existed when starting our work. 

Usage:
    python paper_scraper.py                 # run all scrapers, then combine
    python paper_scraper.py --skip-scraping # combine existing intermediates only
    python paper_scraper.py -o out.csv      # custom combined-output path
"""

import os
import sys
import asyncio
import argparse
import pandas as pd

SCRIPT_DIR      = os.path.dirname(os.path.abspath(__file__))
SUBSCRAPERS_DIR = os.path.join(SCRIPT_DIR, "paper_subscrapers")
INPUT_DATA_DIR  = os.path.join(os.path.dirname(SCRIPT_DIR), "input_data")
UTILS_DIR       = os.path.join(os.path.dirname(SCRIPT_DIR), "utils")

# Make the sub-scraper modules and shared utils importable.
sys.path.insert(0, SUBSCRAPERS_DIR)
sys.path.insert(0, UTILS_DIR)

from uid_utils import make_uid, dedupe_uids
from iclr_paper_scraper import scrape_iclr
from icml_paper_scraper import scrape_icml
from neurips_paper_scraper import scrape_all_neurips
from naacl_scraper import parse_naacl
from facct_scraper import scrape_facct

ICLR_OUT    = os.path.join(SUBSCRAPERS_DIR, "iclr_abstracts.csv")
ICML_OUT    = os.path.join(SUBSCRAPERS_DIR, "icml_abstracts.csv")
NEURIPS_OUT = os.path.join(SUBSCRAPERS_DIR, "neurips_abstracts.csv")
NAACL_OUT   = os.path.join(SUBSCRAPERS_DIR, "naacl_abstracts.csv")
FACCT_OUT   = os.path.join(SUBSCRAPERS_DIR, "facct_abstracts.csv")

NAACL_BIB = os.path.join(INPUT_DATA_DIR, "naacl", "aacl_anthology.bib")


def run_step(name, fn):
    """Run a sub-scraper, logging a banner and warning (not aborting) on failure."""
    print(f"\n{'=' * 60}")
    print(f"Running {name} scraper...")
    print(f"{'=' * 60}")
    try:
        fn()
        return True
    except Exception as e:
        print(f"WARNING: {name} scraper failed: {e}")
        return False


async def run_all_scrapers():
    """Run every sub-scraper that's available, writing each intermediate CSV."""
    # The three async scrapers share this event loop; await them in order so
    # their progress logs stay readable.
    for name, coro in [
        ("ICLR",    scrape_iclr(output=ICLR_OUT)),
        ("ICML",    scrape_icml(output=ICML_OUT)),
        ("NeurIPS", scrape_all_neurips(output=NEURIPS_OUT)),
    ]:
        print(f"\n{'=' * 60}")
        print(f"Running {name} scraper...")
        print(f"{'=' * 60}")
        try:
            await coro
        except Exception as e:
            print(f"WARNING: {name} scraper failed: {e}")

    # NAACL — synchronous, needs the anthology bib file.
    if os.path.exists(NAACL_BIB):
        run_step("NAACL", lambda: parse_naacl(bib_file=NAACL_BIB, output=NAACL_OUT))
    else:
        print(f"\nWARNING: NAACL bib file not found at {NAACL_BIB} — skipping.")

    # FAccT — async; web-scrapes 2018-2020 and reads input_data/facct/*.bib for 2021-2025.
    print(f"\n{'=' * 60}")
    print("Running FAccT scraper...")
    print(f"{'=' * 60}")
    try:
        await scrape_facct(output=FACCT_OUT)
    except Exception as e:
        print(f"WARNING: FAccT scraper failed: {e}")


def load_csv(path, conference):
    if not os.path.exists(path):
        print(f"  WARNING: {path} not found — skipping {conference}")
        return pd.DataFrame()
    df = pd.read_csv(path)
    df.columns = df.columns.str.lower()
    if "conference" not in df.columns:
        df["conference"] = conference
    keep = [c for c in ["title", "abstract", "year", "conference", "url"] if c in df.columns]
    return df[keep]


def main():
    parser = argparse.ArgumentParser(
        description="Run all conference scrapers and combine into a single abstracts CSV."
    )
    parser.add_argument(
        "-o", "--output",
        default=os.path.join(os.path.dirname(SCRIPT_DIR), "output_data", "scrapers", "abstracts.csv"),
        help="Output CSV path (default: output_data/scrapers/abstracts.csv)",
    )
    parser.add_argument(
        "--skip-scraping",
        action="store_true",
        help="Skip running scrapers and just combine the existing intermediate CSVs",
    )
    args = parser.parse_args()

    if not args.skip_scraping:
        asyncio.run(run_all_scrapers())

    # Combine in order
    print("\nCombining results...")
    frames = []
    for path, conference in [
        (ICLR_OUT,    "iclr"),
        (ICML_OUT,    "icml"),
        (NEURIPS_OUT, "neurips"),
        (NAACL_OUT,   "naacl"),
        (FACCT_OUT,   "facct"),
    ]:
        df = load_csv(path, conference)
        if not df.empty:
            frames.append(df)
            print(f"  {conference}: {len(df)} papers")

    if not frames:
        print("No data to combine. Exiting.")
        return

    combined = pd.concat(frames, ignore_index=True)

    # Content-derived UIDs (hash of conference|year|title) so they stay stable
    # across re-scrapes and reordering — see uid_utils.
    combined.insert(0, "uid", [
        make_uid(t, y, c)
        for t, y, c in zip(combined["title"], combined["year"], combined["conference"])
    ])
    combined = dedupe_uids(combined)

    # Empty classification columns, left blank for the downstream classifier to fill.
    CLASSIFICATION_COLS = [
        "safety", "indiv_grp_harm", "info_epistemic_harm", "socioec_harm",
        "physical_harm", "abstract_harm", "reliability_safety", "bias_inequity",
        "security_resilience", "transparency_accountability", "alignment", "governance",
    ]

    # Exact column order expected by the classifier — do not reorder.
    col_order = ["title", "uid", "abstract", "year", "conference", "url"] + CLASSIFICATION_COLS

    # Add any columns missing from the scraped data (e.g. url, all classification cols) as blank.
    for col in col_order:
        if col not in combined.columns:
            combined[col] = ""

    combined = combined[col_order]

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    combined.to_csv(args.output, index=False)
    print(f"\nTotal: {len(combined)} papers saved to {args.output}")


if __name__ == "__main__":
    main()
