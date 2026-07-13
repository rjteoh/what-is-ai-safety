"""
Master sponsor scraper: imports each conference sub-scraper as a function, runs
them across a range of years, then concatenates their output into a single
sponsors CSV.

Conferences covered: naacl, neurips, icml, iclr, facct

Sub-scrapers live in sponsor_subscrapers/ and each exposes an importable entry
point that takes a year and returns a pandas DataFrame (or None on failure):
    naacl_scraper.naacl_scraper(year)              -> DataFrame
    standard_scraper.standard_scraper(conf, year)  -> DataFrame   (used for neurips)
    icml_scraper.icml_scraper(year)                -> DataFrame
    iclr_scraper.iclr_scraper(year)                -> DataFrame
    facct_scraper.facct_scraper(year)              -> DataFrame

Every sub-scraper returns the same columns so the frames can be concatenated
directly: ["sponsor", "tier", "year", "conference"]. NeurIPS follows
the generic ".cc/Conferences/<year>/Sponsors" layout, so it reuses
standard_scraper rather than having its own module.

COMMENT: The scraper will not collect the following years:
- ICLR 2018 and 2019 (no sponsors listed on website for some reason)
- NeurIPS 2021 (no sponsors as it was held virtually during the pandemic)
- NAACL 2017, 2020, 2023 (wasn't held during those years)
- FAccT 2021 (no sponsors as it was held virtually during the pandemic)

Usage:
    python sponsor_scraper.py            # scrape all -> output_data/scrapers/sponsors.csv
    python sponsor_scraper.py -o out.csv # custom output path
"""

import os
import sys
import argparse
import pandas as pd

SCRIPT_DIR      = os.path.dirname(os.path.abspath(__file__))
SUBSCRAPERS_DIR = os.path.join(SCRIPT_DIR, "sponsor_subscrapers")

# Make the sub-scraper modules importable.
sys.path.insert(0, SUBSCRAPERS_DIR)

from standard_scraper import standard_scraper
from naacl_scraper import naacl_scraper
from icml_scraper import icml_scraper
from iclr_scraper import iclr_scraper
from facct_scraper import facct_scraper

START_YEAR = 2015
END_YEAR   = 2025


def run_all_scrapers():
    """Run every sub-scraper across the year range, returning a list of frames.

    Each entry is (name, callable-taking-no-args). Frames that come back as
    None or empty are skipped so one missing/reformatted page doesn't abort the
    whole run.
    """
    frames = []
    for year in range(START_YEAR, END_YEAR + 1):
        print(f"\n{'=' * 60}")
        print(f"Scraping sponsors for {year}...")
        print(f"{'=' * 60}")
        scrapers = [("NAACL", lambda y=year: naacl_scraper(y))]

        # NeurIPS 2021 was held virtually with no sponsors (it has no dedicated
        # subscraper, so the skip lives here rather than in standard_scraper).
        if year == 2021:
            print("  Skipping NeurIPS 2021: held virtually during the pandemic, no sponsors.")
        else:
            scrapers.append(("NeurIPS", lambda y=year: standard_scraper("neurips", y)))  # neurips follows standard format

        scrapers += [
            ("ICML", lambda y=year: icml_scraper(y)),
            ("ICLR", lambda y=year: iclr_scraper(y)),
        ]
        # FAccT's first conference was 2019, so there are no earlier pages to scrape.
        if year >= 2019:
            scrapers.append(("FAccT", lambda y=year: facct_scraper(y)))

        for name, fn in scrapers:
            try:
                df = fn()
            except Exception as e:
                print(f"  WARNING: {name} {year} scraper failed: {e}")
                continue
            if df is not None and not df.empty:
                frames.append(df)
                print(f"  {name}: {len(df)} sponsors")
    return frames


def main():
    parser = argparse.ArgumentParser(
        description="Run all conference sponsor scrapers and combine into a single CSV."
    )
    parser.add_argument(
        "-o", "--output",
        default=os.path.join(os.path.dirname(SCRIPT_DIR), "output_data", "scrapers", "sponsors.csv"),
        help="Output CSV path (default: output_data/scrapers/sponsors.csv)",
    )
    args = parser.parse_args()

    frames = run_all_scrapers()
    if not frames:
        print("\nNo sponsor data to combine. Exiting.")
        return

    combined = pd.concat(frames, ignore_index=True)
    # Drop the source-page url; it's only useful for debugging scrapes.
    combined = combined.drop(columns="url", errors="ignore")
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    combined.to_csv(args.output, index=False)
    print(f"\nTotal: {len(combined)} sponsors saved to {args.output}")


if __name__ == "__main__":
    main()
