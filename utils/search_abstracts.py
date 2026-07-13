"""
Searches the abstract pool for papers matching one or more keywords (whole-word,
in the title and/or abstract) and writes the matches to a CSV. Keywords can be
combined with OR (any match, default) or AND (all must match) logic. Handy for
quickly pulling every paper that mentions a given term.

Usage (run from the repo root):
    python utils/search_abstracts.py alignment safety            # OR match, any keyword
    python utils/search_abstracts.py alignment safety -a         # AND match, all keywords
    python utils/search_abstracts.py rlhf -i in.csv -o out.csv   # custom input/output
"""

import os
import pandas as pd
import argparse
from datetime import datetime
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT  = os.path.dirname(SCRIPT_DIR)

# default anchored to the repo root so the tool runs from any directory
DEFAULT_INPUT = os.path.join(REPO_ROOT, "output_data", "scrapers", "abstracts.csv")


def search_abstracts(
    input_file=DEFAULT_INPUT,
    keywords=None,
    output_file=None,
    case_sensitive=False,
    search_title=True,
    search_abstract=True,
    match_all=False
):
    """
    Search for keywords in abstracts CSV.
    
    Args:
        input_file: Path to input CSV file (default: abstracts.csv)
        keywords: List of keywords to search for
        output_file: Path to output CSV (default: temp_results_TIMESTAMP.csv)
        case_sensitive: Whether to perform case-sensitive search
        search_title: Whether to search in title column
        search_abstract: Whether to search in abstract column
        match_all: If True, require ALL keywords to match (AND logic)
                  If False, require ANY keyword to match (OR logic)
    
    Returns:
        DataFrame of matching results
    """
    if keywords is None or len(keywords) == 0:
        raise ValueError("At least one keyword must be provided")
    
    # Read the CSV file
    print(f"Reading {input_file}...")
    df = pd.read_csv(input_file)
    print(f"Loaded {len(df)} papers")
    
    # Create search function
    flags = 0 if case_sensitive else re.IGNORECASE
    
    def matches_keywords(row):
        text_to_search = []
        if search_title and 'title' in df.columns:
            text_to_search.append(str(row.get('title', '')))
        if search_abstract and 'abstract' in df.columns:
            text_to_search.append(str(row.get('abstract', '')))
        
        combined_text = ' '.join(text_to_search)
        
        if match_all:
            # All keywords must be present (AND logic)
            return all(re.search(rf'\b{re.escape(kw)}\b', combined_text, flags) 
                      for kw in keywords)
        else:
            # Any keyword can be present (OR logic)
            return any(re.search(rf'\b{re.escape(kw)}\b', combined_text, flags) 
                      for kw in keywords)
    
    # Apply filter
    print(f"Searching for keywords: {keywords}")
    print(f"Match mode: {'ALL keywords (AND)' if match_all else 'ANY keyword (OR)'}")
    print(f"Case sensitive: {case_sensitive}")
    print(f"Searching in: {', '.join(filter(None, ['title' if search_title else None, 'abstract' if search_abstract else None]))}")
    
    results = df[df.apply(matches_keywords, axis=1)]
    print(f"\nFound {len(results)} matching papers")
    
    # Generate output filename if not provided
    if output_file is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f"temp_results_{timestamp}.csv"
    
    # Save results
    results.to_csv(output_file, index=False)
    print(f"Results saved to: {output_file}")
    
    return results


def main():
    parser = argparse.ArgumentParser(
        description='Search abstracts.csv for papers matching keywords'
    )
    parser.add_argument(
        'keywords',
        nargs='+',
        help='Keywords to search for'
    )
    parser.add_argument(
        '-i', '--input',
        default=DEFAULT_INPUT,
        help='Input CSV file (default: output_data/scrapers/abstracts.csv)'
    )
    parser.add_argument(
        '-o', '--output',
        help='Output CSV file (default: temp_results_TIMESTAMP.csv)'
    )
    parser.add_argument(
        '-c', '--case-sensitive',
        action='store_true',
        help='Perform case-sensitive search'
    )
    parser.add_argument(
        '--no-title',
        action='store_true',
        help='Do not search in title column'
    )
    parser.add_argument(
        '--no-abstract',
        action='store_true',
        help='Do not search in abstract column'
    )
    parser.add_argument(
        '-a', '--all',
        action='store_true',
        help='Require ALL keywords to match (AND logic, default is OR)'
    )
    
    args = parser.parse_args()
    
    # Run search
    results = search_abstracts(
        input_file=args.input,
        keywords=args.keywords,
        output_file=args.output,
        case_sensitive=args.case_sensitive,
        search_title=not args.no_title,
        search_abstract=not args.no_abstract,
        match_all=args.all
    )
    
    # Display sample results
    if len(results) > 0:
        print("\n" + "="*80)
        print("Sample results (first 3):")
        print("="*80)
        for idx, row in results.head(3).iterrows():
            print(f"\nTitle: {row.get('title', 'N/A')}")
            print(f"Year: {row.get('year', 'N/A')}, Conference: {row.get('conference', 'N/A')}")
            abstract = row.get('abstract', 'N/A')
            if len(abstract) > 200:
                abstract = abstract[:200] + "..."
            print(f"Abstract: {abstract}")


if __name__ == '__main__':
    main()
