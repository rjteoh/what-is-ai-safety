import pandas as pd
import re
import argparse

# setting global vars
BIB_FILE = "../../input_data/naacl/aacl_anthology.bib"
START_YEAR = 2015
END_YEAR = 2025

def is_aacl_main(booktitle: str) -> bool:
    '''
    check if a book title is part of naacl main proceedings
    '''
    clean = re.sub(r'[^a-zA-Z\s]', '', booktitle)
    bt = clean.lower()
    if "proceedings" not in bt:
        return False
    if "north american chapter" not in bt and "nations of the americas" not in bt:
        return False
    return True


def parse_naacl(bib_file=BIB_FILE, start_year=START_YEAR, end_year=END_YEAR, output=None):
    """
    Parse NAACL papers from BibTeX file and extract titles and abstracts.
    
    Args:
        bib_file: Path to BibTeX file (default: "aacl_anthology.bib")
        start_year: Start year for filtering (default: 2015)
        end_year: End year for filtering (default: 2025)
        output: Path to output file for all abstracts (default: None)
    
    Returns:
        DataFrame with columns: title, abstract, conference, year
    """
    print(f"Parsing abstracts from {bib_file}...")

    # read file
    with open(bib_file, "r", encoding="utf-8") as f:
        bib_text = f.read()

    # split into entries (each @inproceedings block)
    entries = bib_text.split("@inproceedings")
    print(f"Total entries in file: {len(entries)-1}")

    abstracts_data = []  # List to store all abstracts

    for entry in entries[1:]:  # skip before first @inproceedings
        block = "@inproceedings" + entry

        # extract year
        year_match = re.search(r"year\s*=\s*\"?(\d{4})\"?", block)
        if not year_match:
            continue
        year = int(year_match.group(1))
        if not (start_year <= year <= end_year):
            continue

        # extract book title
        bt_match = re.search(r"booktitle\s*=\s*\"([^\"]+)\"", block, flags=re.IGNORECASE)
        if not bt_match:
            continue
        booktitle = bt_match.group(1)
        if not is_aacl_main(booktitle):
            continue

        # extract title and abstract
        title_match = re.search(r"title\s*=\s*\"([^\"]+)\"", block, flags=re.IGNORECASE)
        abstract_match = re.search(r"abstract\s*=\s*\"([^\"]+)\"", block, flags=re.IGNORECASE)
        title = title_match.group(1) if title_match else ""
        abstract = abstract_match.group(1) if abstract_match else ""
        
        # Store all abstracts data
        abstracts_data.append({
            "title": title,
            "abstract": abstract,
            "conference": "naacl",
            "year": year
        })

    # Create dataframe
    df = pd.DataFrame(abstracts_data)
    
    # Export if output path is provided
    if output:
        df.to_csv(output, index=False)
        print(f"Exported {len(df)} abstracts to {output}")
    
    return df


def main():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Extract NAACL paper titles and abstracts from BibTeX file")
    parser.add_argument(
        "-o", "--output",
        required=True,
        help="Path to output CSV file (required)"
    )
    args = parser.parse_args()

    df = parse_naacl(
        bib_file=BIB_FILE,
        start_year=START_YEAR,
        end_year=END_YEAR,
        output=args.output
    )

if __name__ == "__main__":
    main()

