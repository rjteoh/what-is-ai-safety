"""
Extracts rejected or withdrawn ICLR papers from the per-year ICLR JSON dumps and
writes them to a CSV. The main paper scraper only collects accepted papers; this
pulls the reject/withdraw pile so we can compare safety-paper rates between
accepted and non-accepted work.

Reads:  https://raw.githubusercontent.com/papercopilot/paperlists/main/iclr/iclr{year}.json
        (JSON dumps from the Paper Copilot project, fetched live so we don't have
        to vendor them; pass a local folder to -i to read iclr{year}.json from disk)
Writes: output_data/scrapers/iclr-rejected.csv
        (or iclr-withdrawn.csv with -t withdraw)

Each output row has title, uid, abstract, year, conference — matching the schema
of the main abstracts CSV so it can be fed to the classifier. UIDs are the same
content-derived hashes used everywhere else (conference_<hash>, see uid_utils);
since a paper has a single status, rejected/withdrawn rows never collide with
the accepted ones.

Usage:
    python iclr_reject_scraper.py                 # rejects -> iclr-rejected.csv
    python iclr_reject_scraper.py -t withdraw     # withdrawn papers instead
    python iclr_reject_scraper.py -i in_dir -o out.csv   # custom paths
"""

import json
import os
import sys
import argparse
import pandas as pd
import requests

# shared UID helpers live in the repo-level utils/ folder
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "utils"))
from uid_utils import make_uid, dedupe_uids

YEARS = range(2017, 2025)

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT     = os.path.dirname(SCRIPT_DIR)
# Default to the Paper Copilot JSON dumps on GitHub so nothing has to be vendored.
DEFAULT_INPUT = "https://raw.githubusercontent.com/papercopilot/paperlists/main/iclr"
OUTPUT_DIR    = os.path.join(REPO_ROOT, "output_data", "scrapers")


def load_papers(year, source, status_filter):
    """Load one year's papers from a remote base URL or a local folder.

    `source` is treated as a base URL when it starts with http(s), otherwise as
    a local directory containing iclr{year}.json.
    """
    filename = f"iclr{year}.json"
    if str(source).lower().startswith("http"):
        url = f"{source.rstrip('/')}/{filename}"
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            papers = response.json()
        except requests.RequestException as e:
            print(f"Skipping {year}: could not fetch {url} ({e})")
            return []
    else:
        path = os.path.join(source, filename)
        if not os.path.exists(path):
            print(f"Skipping {year}: file not found")
            return []
        with open(path, encoding="utf-8") as f:
            papers = json.load(f)

    # status field is not always consistent in casing
    matched = [p for p in papers if str(p.get("status", "")).lower() == status_filter]
    print(f"{year}: {len(matched)} {status_filter} papers")
    return matched


def main():
    parser = argparse.ArgumentParser(description="Extract rejected or withdrawn papers from conference JSON data.")
    parser.add_argument("-i", "--input", default=DEFAULT_INPUT,
                        help="Base URL or local folder holding the iclr{year}.json files "
                             "(default: Paper Copilot GitHub raw URL)")
    parser.add_argument("-o", "--output", default=None,
                        help="Output CSV path (default: output_data/scrapers/iclr-<type>.csv)")
    parser.add_argument("-c", "--conference", default="iclr", help="Conference name to tag each row (default: iclr)")
    parser.add_argument("-t", "--type", dest="paper_type", choices=["reject", "withdraw"], default="reject",
                        help="Type of papers to scrape: 'reject' or 'withdraw' (default: reject)")
    args = parser.parse_args()

    # default output name reflects the paper type: iclr-rejected.csv / iclr-withdrawn.csv
    output_csv = args.output or os.path.join(
        OUTPUT_DIR, f"{args.conference}-{'rejected' if args.paper_type == 'reject' else 'withdrawn'}.csv"
    )
    os.makedirs(os.path.dirname(output_csv), exist_ok=True)

    rows = []
    for year in YEARS:
        for p in load_papers(year, args.input, args.paper_type):
            title = p.get("title", "")
            # Content-derived UID (see uid_utils); the conference|year|title hash
            # is unique on its own, so accepted and rejected rows never collide.
            uid = make_uid(title, year, args.conference)
            rows.append({
                "title": title,
                "uid": uid,
                "abstract": p.get("abstract", ""),
                "year": year,
                "conference": args.conference,
            })

    df = pd.DataFrame(rows, columns=["title", "uid", "abstract", "year", "conference"])
    df = dedupe_uids(df, label=f"{args.paper_type} UIDs")
    df.to_csv(output_csv, index=False)
    print(f"\nTotal: {len(df)} {args.paper_type} papers saved to {output_csv}")


if __name__ == "__main__":
    main()
