"""
Draws a random sample of abstracts whose text matches at least one keyword from a
keyword list (keywords.txt by default). Useful for pulling a manageable, topic-
relevant subset out of the full abstract pool (e.g. to hand to human coders).
The sample is reproducible (fixed random_state).

Usage (run from the repo root):
    python utils/sampler.py -n 50 -o sample.csv               # 50 keyword-matched rows
    python utils/sampler.py -n 50 -o sample.csv -i in.csv     # custom input pool
    python utils/sampler.py -n 50 -o sample.csv -k mywords.txt  # custom keyword list
"""

import os
import argparse
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT  = os.path.dirname(SCRIPT_DIR)

# defaults anchored to the repo root so the tool runs from any directory
DEFAULT_INPUT    = os.path.join(REPO_ROOT, "output_data", "scrapers", "abstracts.csv")
DEFAULT_KEYWORDS = os.path.join(SCRIPT_DIR, "keywords.txt")

def sampler(n_samples: int, output_csv, input_csv=DEFAULT_INPUT,
            keywords_file=DEFAULT_KEYWORDS):
    """
    Command-line tool to select n number of samples matching a keyword list
    from our abstract files .

    Args:
        n_samples - number of files to sample
        input_csv - input file
        output_csv - output filename
        keywords_file - keyword list (one keyword per line)
    """
    # import abstracts
    df = pd.read_csv(input_csv)

    # importing keyword list
    with open(keywords_file, "r", encoding="utf-8") as f:
        keywords = [line.strip().lower() for line in f if line.strip()]

    # filter for papers containing at least one keyword
    def contains_keyword(text):
        if pd.isna(text):
            return False
        text_lower = str(text).lower()
        return any(keyword in text_lower for keyword in keywords)

    filtered = df[df['abstract'].apply(contains_keyword)]

    if n_samples > len(filtered):
        raise ValueError(
            f"Requested {n_samples} samples but only {len(filtered)} of {len(df)} "
            f"abstracts match a keyword from {keywords_file}."
        )

    random_sample = filtered.sample(n=n_samples, random_state=42)
    random_sample.to_csv(output_csv, index=False)

    print(f"Selected {n_samples} random rows from {len(filtered)} keyword-matched "
          f"({len(df)} total) rows")
    print(f"Saved to {output_csv}.")

def main():
    # setting CLI inputs with argparse
    parser = argparse.ArgumentParser(
        description="Select a random sample from our abstract lists"
    )
    parser.add_argument(
        "-i", "--input",
        default=DEFAULT_INPUT,
        help="Input CSV file (default: output_data/scrapers/abstracts.csv)"
    )
    parser.add_argument(
        "-o", "--output",
        required=True,
        help="Output CSV file"
    )
    parser.add_argument(
        "-n", "--n_samples",
        type=int,
        required=True,
        help="Number of rows to sample"
    )
    parser.add_argument(
        "-k", "--keywords",
        default=DEFAULT_KEYWORDS,
        help="Keyword list file, one per line (default: utils/keywords.txt)"
    )
    args = parser.parse_args()

    sampler(
        input_csv = args.input,
        n_samples = args.n_samples,
        output_csv = args.output,
        keywords_file = args.keywords
    )

if __name__ == "__main__":
    main()