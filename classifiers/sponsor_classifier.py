"""
Sponsor classifier: takes the combined sponsors CSV produced by the sponsor
scraper and labels each sponsor as "big tech" or not, using an LLM to map messy
sponsor strings (names, URLs, logo filenames) onto a canonical list of firms.


What it does:
    1. Loads the full sponsors CSV (one row per sponsor mention, with duplicates).
    2. Deduplicates the sponsor strings so the LLM is called once per distinct
       string (one row of sponsors.csv != one API call).
    Pipeline:
        output_data/scrapers/sponsors.csv  ->  THIS SCRIPT
            ->  output_data/classifiers/sponsors-classified.csv

    3. Classifies each unique string against input_data/big-tech-list.csv. The
       LLM returns, per string: is_bigtech (bool) and canonical_name (the parent
       firm, e.g. "deepmind" -> "Alphabet", or null if not big tech).
    4. Merges the labels back onto the FULL dataset (duplicates included) and
       writes the result, with all text columns lowercased so downstream analysis
       doesn't trip on case mismatches.

Caching (so the expensive LLM step is resumable):
    Every classified string is appended to classifiers/.sponsor-cache.csv the
    moment it comes back, so a crash never loses tokens already spent. On each
    run only strings missing from the cache are sent to the LLM; a re-run after a
    failure (or with new sponsors) classifies just the new names. The cache is
    keyed ONLY on the sponsor string, so it does NOT notice edits to
    big-tech-list.csv — pass --refresh (or delete the cache file) to re-classify
    everything after changing that list.

Requirements:
    - input_data/big-tech-list.csv  : the canonical firm list (column "company")
    - a repo-root .env with OPENAI_API_KEY set (loaded via python-dotenv)

COMMENT: A better implementation might use the LLM's web search tool to ensure that
it captures any changes to a firm that might have happened after its knowledge
cut-off date, but we chose to just use the LLM's pre-trained knowledge to save on cost.    

Usage:
    python sponsor_classifier.py                       # output_data/scrapers/sponsors.csv -> output_data/classifiers/sponsors-classified.csv
    python sponsor_classifier.py -i in.csv -o out.csv  # custom input/output paths
    python sponsor_classifier.py --refresh             # ignore cache, re-classify every name
"""

import argparse
import pandas as pd
import json
import os
from dotenv import load_dotenv
from openai import OpenAI

# constants
LLM = 'gpt-5.2'
SCRIPT_DIR     = os.path.dirname(os.path.abspath(__file__))
ENV_PATH       = os.path.join(os.path.dirname(SCRIPT_DIR), ".env")  # repo-root .env
BIG_TECH_LIST  = os.path.join(os.path.dirname(SCRIPT_DIR), "input_data", "big-tech-list.csv")
# Per-sponsor classification cache. Keyed only on the sponsor string, so if you
# edit big-tech-list.csv the cached labels go stale — re-run with --refresh (or
# delete this file) to force re-classification.
CACHE_PATH     = os.path.join(SCRIPT_DIR, ".sponsor-cache.csv")
CACHE_COLS     = ["sponsor", "is_bigtech", "canonical_name"]


def load_cache(path):
    """Load previously classified sponsors, or an empty frame if no cache exists."""
    if os.path.exists(path):
        return pd.read_csv(path)
    return pd.DataFrame(columns=CACHE_COLS)

def classify_sponsors(client: OpenAI, sponsor_strings: list, big_tech_list: list, cache_path: str = None):
    """
    uses an LLM to classify a list of unique sponsor strings into "big tech" and non-big tech based
    on a given list. returns a dataframe containing the unique strings, boolean (is_bigtech) and
    canonical_name which captures which big tech firm the sponsor string points to

    Args:
        client: OpenAI client instance
        sponsor_strings: list of unique sponsor strings to check
        big_tech_list: list of big tech firm names to check against
        cache_path: if given, each classified row is appended here immediately, so a
            crash mid-run preserves progress (and the tokens already spent)
    """

    # converts the list of names into bullet format for dynamically entering into the prompt
    big_tech_names = ""
    for name in big_tech_list:
        big_tech_names += f"- {name}\n"

    prompt = f"""
        You are a precise classification system. Your task is to evaluate sponsor names and determine whether they correspond to a predefined set of major technology companies ("Big Tech"), including their subsidiaries, alternate names, and common misspellings.

        # Big Tech Firms (canonical names)
        {big_tech_names}

        # Rules
        - Handle misspellings (e.g. "Gooogle") and variants (e.g. "Amazon Inc.")
        - Sponsor strings may be messy URLs or image filenames (e.g. "https://research.fb.com/", "google-logo.png"); extract the firm from them
        - Products/subsidiaries should be mapped to the parent firm (e.g. Instagram, Facebook, WhatsApp = Meta; YouTube, DeepMind = Alphabet)
        - Give your output in JSON format as per the example below. Do not include extra text.
        - If the sponsor is not big tech, set is_bigtech to false and canonical_name to null.

        # Example Output (JSON format)
        {{
            "is_bigtech": true,
            "canonical_name": "Alphabet"
        }}
    """

    rows = []
    total_tokens = 0
    total = len(sponsor_strings)

    # classify each sponsor string
    for i, sponsor in enumerate(sponsor_strings, start=1):
        input_data = json.dumps({"sponsor": sponsor})
        # include tools = [{"type": "web_search"}] if websearch is needed
        result = client.responses.create(
            model = LLM,
            instructions = prompt,
            input = input_data,
            temperature = 0 # set temp to 0 for predictability
        )

        # simple usage tracking for cost estimates
        total_tokens += result.usage.total_tokens

        # parse JSON response and bind back to sponsor string
        parsed = json.loads(result.output_text)
        row = {
            "sponsor": sponsor,
            "is_bigtech": parsed["is_bigtech"],
            "canonical_name": parsed["canonical_name"]
        }
        rows.append(row)

        # persist immediately so a later crash never loses tokens already spent
        if cache_path:
            pd.DataFrame([row], columns=CACHE_COLS).to_csv(
                cache_path,
                mode="a",
                index=False,
                header=not os.path.exists(cache_path),
                na_rep="NA",
            )

        # progress update every 50 names (and on the last one)
        if i % 50 == 0 or i == total:
            print(f"  classified {i}/{total} sponsors...")

    print(f"Total tokens used: {total_tokens}")
    return pd.DataFrame(rows, columns=CACHE_COLS)

def main():

    parser = argparse.ArgumentParser(description="Classify sponsors as big tech or not.")
    parser.add_argument(
        "-i", "--input",
        default=os.path.join(os.path.dirname(SCRIPT_DIR), "output_data", "scrapers", "sponsors.csv"),
        help="Path to the full sponsors CSV produced by sponsor_scraper.py (default: output_data/scrapers/sponsors.csv)",
    )
    parser.add_argument(
        "-o", "--output",
        default=os.path.join(os.path.dirname(SCRIPT_DIR), "output_data", "classifiers", "sponsors-classified.csv"),
        help="Output CSV path (default: output_data/classifiers/sponsors-classified.csv)",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore the classification cache and re-classify every name (use after editing big-tech-list.csv)",
    )
    args = parser.parse_args()

    # load env file
    load_dotenv(ENV_PATH)

    # initialize OpenAI client
    client = OpenAI()

    # load the full sponsor dataset (one row per sponsor mention, with duplicates)
    sponsors = pd.read_csv(args.input)

    # deduplicate names first so we only spend one LLM call per distinct string
    unique_sponsors = sponsors["sponsor"].dropna().unique().tolist()
    print(f"Loaded {len(sponsors)} sponsor rows ({len(unique_sponsors)} unique names)")

    # load big tech list
    big_tech = pd.read_csv(BIG_TECH_LIST)["company"].dropna().tolist()

    # --refresh wipes the cache so every name is re-classified from scratch
    if args.refresh and os.path.exists(CACHE_PATH):
        os.remove(CACHE_PATH)

    # only call the LLM for names we haven't already classified in a previous run
    cache = load_cache(CACHE_PATH)
    cached_names = set(cache["sponsor"])
    todo = [s for s in unique_sponsors if s not in cached_names]
    print(f"{len(cached_names & set(unique_sponsors))} cached, {len(todo)} to classify")

    if todo:
        classify_sponsors(client, todo, big_tech, cache_path=CACHE_PATH)
        cache = load_cache(CACHE_PATH)  # reload to pick up the rows just appended

    # take the classifications for this input's names from the (now complete) cache
    classified = cache[cache["sponsor"].isin(unique_sponsors)]

    # merge the classification back onto the full dataset so every row (including
    # duplicates) gets an is_bigtech boolean and the canonical firm name
    merged = sponsors.merge(classified, on="sponsor", how="left")

    # lowercase all text columns so later analysis doesn't trip on case mismatches.
    # map per-cell (rather than .str.lower) so None/NaN in columns like
    # canonical_name pass through untouched instead of raising on the .str accessor.
    for col in merged.select_dtypes(include="object").columns:
        merged[col] = merged[col].map(lambda x: x.lower() if isinstance(x, str) else x)

    # write the full dataset, now annotated with is_bigtech / canonical_name
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    merged.to_csv(args.output, index=False, na_rep='NA')
    print(f"Saved {len(merged)} classified sponsor rows to {args.output}")

if __name__ == "__main__":
    main()