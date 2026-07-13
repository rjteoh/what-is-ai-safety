"""
Shared UID helpers for the paper pipeline, plus a standalone re-keying tool.

UIDs are content-derived: a short hashlib digest of
    conference | year | normalized-title
rather than a sequential row number. This makes them stable across re-scrapes
and reordering — the same paper always gets the same UID no matter where it
lands in the file or when the scraper runs. (Sequential UIDs reshuffle every
time the row order changes.)

Imported by the scrapers (scrapers/paper_scraper.py, scrapers/iclr_reject_scraper.py)
to mint UIDs at scrape time. Can also be run standalone to RE-KEY an existing CSV
— e.g. already-classified data — to the new hashing scheme without re-scraping or
re-classifying. Because the hash is deterministic, re-keying old rows yields the
exact same UIDs a fresh scrape would, so classifications stay correctly matched.
If re-keying turns up any duplicate UIDs, the duplicate rows are dropped (one
kept per UID) and a single copy of each colliding row is dumped to utils/debug.csv
so the de-duplicated papers stay visible.

Notes:
  * We use hashlib, NOT Python's built-in hash(): the latter is salted per
    process (PYTHONHASHSEED) and is therefore NOT reproducible across runs.
  * 12 hex chars = 48 bits. Across ~55k papers the collision probability is
    roughly 1 in 200,000; callers should still guard with check_unique().

Usage:
    python uid_utils.py -i abstracts.csv                 # re-key in place
    python uid_utils.py -i in.csv -o out.csv             # write to a new file
"""

import os
import hashlib

UID_LEN = 12  # hex chars of the digest to keep

# When re-keying turns up duplicate UIDs, the offending rows are dumped here for
# inspection (alongside this module, in utils/).
DEBUG_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug.csv")


def normalize_title(title):
    """Lowercase and collapse whitespace so trivial formatting differences
    (extra spaces, casing) don't change a paper's UID."""
    return " ".join(str(title).lower().split())


def _norm_year(year):
    """Render the year as a clean integer string ('2024'), tolerating ints,
    strings, and floats like 2024.0 that pandas can introduce."""
    try:
        return str(int(year))
    except (TypeError, ValueError):
        return str(year).strip()


def make_uid(title, year, conference):
    """Build a stable, content-derived UID for a paper.

    Format: "{conference}_{digest}". The digest hashes conference|year|title, so
    a paper is uniquely identified regardless of acceptance status (a given paper
    has only one status, so accepted/rejected/withdrawn rows never collide).
    """
    key = f"{conference}|{_norm_year(year)}|{normalize_title(title)}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:UID_LEN]
    return f"{conference}_{digest}"


def check_unique(uids, label="UIDs"):
    """Warn (and return the count) if any UIDs collide. A collision means two
    rows share conference+year+normalized-title — usually a genuine duplicate
    paper rather than a hash accident."""
    seen, dupes = set(), 0
    for uid in uids:
        if uid in seen:
            dupes += 1
        seen.add(uid)
    if dupes:
        print(f"WARNING: {dupes} duplicate {label} detected "
              f"(same conference+year+title).")
    return dupes


def duplicate_rows(df, uid_col="uid"):
    """Return every row whose UID is shared by at least one other row (all
    members of each collision group), sorted so duplicates sit together."""
    dupes = df[df.duplicated(subset=uid_col, keep=False)]
    return dupes.sort_values(uid_col)


def dedupe_uids(df, debug_csv=DEBUG_CSV, label="UIDs"):
    """Drop rows with duplicate UIDs, keeping the first occurrence of each.

    Expects a 'uid' column. If any UIDs collide, a single copy of each colliding
    row is written to `debug_csv` (default: utils/debug.csv) for inspection, then
    the extra copies are dropped. Returns the de-duplicated DataFrame.
    """
    if check_unique(df["uid"], label=label):
        if debug_csv:
            # one representative row per colliding UID, for inspection
            dupes = duplicate_rows(df).drop_duplicates(subset="uid")
            os.makedirs(os.path.dirname(os.path.abspath(debug_csv)), exist_ok=True)
            dupes.to_csv(debug_csv, index=False)
            print(f"  Wrote {len(dupes)} duplicate UID(s) to {debug_csv}")
        before = len(df)
        df = df.drop_duplicates(subset="uid", keep="first").reset_index(drop=True)
        print(f"  Removed {before - len(df)} duplicate row(s); kept one per UID.")
    return df


def rekey_dataframe(df, debug_csv=DEBUG_CSV):
    """Return a copy of `df` with its 'uid' column recomputed via make_uid(),
    de-duplicated so each UID appears once.

    The input must have title, year, and conference columns; all other columns
    (abstract, classification labels, ...) are preserved untouched. If a 'uid'
    column already exists it is overwritten in place (keeping its position),
    otherwise one is added.

    If any UIDs collide, the duplicate rows are dropped (the first occurrence of
    each UID is kept) and a single copy of each colliding row is written to
    `debug_csv` (default: utils/debug.csv) so the dropped papers are visible.
    """
    required = {"title", "year", "conference"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing required column(s): {sorted(missing)}")

    df = df.copy()
    df["uid"] = [
        make_uid(t, y, c)
        for t, y, c in zip(df["title"], df["year"], df["conference"])
    ]
    return dedupe_uids(df, debug_csv=debug_csv)


if __name__ == "__main__":
    # Standalone re-keying: read a CSV, recompute its uid column with the
    # content-hash scheme, and write it back (in place by default).
    import argparse
    import pandas as pd

    parser = argparse.ArgumentParser(
        description="Re-key a CSV's uid column to the content-hash scheme "
                    "(needs title, year, conference columns)."
    )
    parser.add_argument("-i", "--input", required=True,
                        help="Input CSV to re-key (must have title, year, conference columns)")
    parser.add_argument("-o", "--output", default=None,
                        help="Output CSV (default: overwrite the input file in place)")
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    df = rekey_dataframe(df)

    output = args.output or args.input
    df.to_csv(output, index=False)
    print(f"Re-keyed {len(df)} rows -> {output}")
