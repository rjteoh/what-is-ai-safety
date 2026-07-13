"""
Drops the held-out test set (input_data/test_data/test_set.csv) from the master
pool of scraped abstracts, matching on 'uid'. abstract_classifier.py calls this
in-memory before classifying so the human-labelled test set never leaks into the
classified pile and stays a clean benchmark.

Can also be run standalone to write the filtered abstracts to a CSV for inspection.

Usage:
    python remove_test_abstracts.py                  # filter with default paths
    python remove_test_abstracts.py -i in.csv -o out.csv -t test.csv  # custom paths
"""

import os
import argparse
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT  = os.path.dirname(SCRIPT_DIR)

# defaults used only when this script is run standalone (see __main__ below)
DEFAULT_MASTER = os.path.join(REPO_ROOT, "output_data", "scrapers", "abstracts.csv")
DEFAULT_OUTPUT = os.path.join(REPO_ROOT, "output_data", "classifiers", "abstracts-filtered.csv")
DEFAULT_TEST   = os.path.join(REPO_ROOT, "input_data", "test_data", "test_set.csv")


def remove_test_abstracts(master: pd.DataFrame, test_csv: str) -> pd.DataFrame:
    """Drop the held-out test-set abstracts (matched by uid) from a master df.

    Called by abstract_classifier.py before classifying so the test set never
    leaks into the classified pile. Returns a new, re-indexed DataFrame.

    Args:
        master: DataFrame of all scraped abstracts (must have a 'uid' column).
        test_csv: Path to the held-out test set CSV (must have a 'uid' column).
    """
    test = pd.read_csv(test_csv)
    test_uids = set(test["uid"].astype(str))

    before = len(master)
    filtered = master[~master["uid"].astype(str).isin(test_uids)].reset_index(drop=True)
    print(f"Removed {before - len(filtered)} test-set rows. {len(filtered)} remaining.")
    return filtered


if __name__ == "__main__":
    # standalone use: read the master abstracts, filter out the test set, and write the
    # intermediate CSV. The classifier no longer needs this file (it filters in-memory),
    # but it stays handy for inspecting exactly which rows get removed.
    parser = argparse.ArgumentParser(
        description="Filter the held-out test set out of a master abstracts CSV."
    )
    parser.add_argument('-i', '--input', default=DEFAULT_MASTER, dest='master_csv',
                        help='Master abstracts CSV to filter (default: output_data/scrapers/abstracts.csv)')
    parser.add_argument('-o', '--output', default=DEFAULT_OUTPUT, dest='output_csv',
                        help='Filtered output CSV (default: output_data/classifiers/abstracts-filtered.csv)')
    parser.add_argument('-t', '--test', default=DEFAULT_TEST, dest='test_csv',
                        help='Held-out test set CSV (default: input_data/test_data/test_set.csv)')
    args = parser.parse_args()

    master = pd.read_csv(args.master_csv)
    filtered = remove_test_abstracts(master, args.test_csv)
    os.makedirs(os.path.dirname(args.output_csv), exist_ok=True)
    filtered.to_csv(args.output_csv, index=False)
    print(f"Output: {args.output_csv}")
