"""
Unified FAccT paper scraper.

FAccT proceedings are collected two different ways depending on the year:

  * Early years (2018-2020) are scraped live from the web. 2018 lived on PMLR
    (the conference shared MLR's proceedings that year); 2019 and 2020 have an
    accepted-papers HTML page on facctconference.org that only lists titles, so
    abstracts are backfilled from the OpenAlex API. These web fetches run
    concurrently (aiohttp + a bounded semaphore) to keep the run fast.

  * Later years (2021-2025) are exported as BibTeX from the ACM Digital Library
    and committed to input_data/facct/facctYYYY.bib. These carry the abstract
    (and a url) inline, so no network access is needed.

This module mirrors the other conference sub-scrapers: it exposes an importable
async entry point, scrape_facct(output, ...), and writes a CSV with columns
    title, abstract, year, conference, url

Usage:
    python facct_scraper.py -o facct_abstracts.csv
"""

import os
import csv
import re
import asyncio
import argparse

import aiohttp
from bs4 import BeautifulSoup
from urllib.parse import urljoin

try:
    import bibtexparser
except ImportError:  # pragma: no cover - only needed for the bib years
    bibtexparser = None

# --- Paths -----------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(SCRIPT_DIR)), "input_data")
FACCT_BIB_DIR = os.path.join(INPUT_DATA_DIR, "facct")

# --- Year configuration ----------------------------------------------------
START_YEAR = 2018
END_YEAR = 2025

# 2018 shared MLR Press's proceedings server.
PMLR_URLS = {
    2018: "https://proceedings.mlr.press/v81/",
}

# 2019-2020 publish a title-only accepted-papers page; abstracts come from OpenAlex.
HTML_URLS = {
    2019: "https://facctconference.org/2019/acceptedpapers.html",
    2020: "https://facctconference.org/2020/acceptedpapers.html",
}

# 2021 onward are read from committed BibTeX exports in input_data/facct/.
BIB_YEARS = [2021, 2022, 2023, 2024, 2025]
FACCT_BOOKTITLE = "Proceedings of the {year} ACM Conference on Fairness, Accountability, and Transparency"

CONFERENCE = "facct"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FAccTPaperScraper/1.0)"
}

OUTPUT_FIELDS = ["title", "abstract", "year", "conference", "url"]

# --- Network / rate-limit tuning ------------------------------------------
MAX_CONCURRENT_REQUESTS = 5      # bounded concurrency to stay polite
MAX_RETRIES = 5                  # retries on HTTP 429 (rate limit)
RETRY_BASE_DELAY = 2.0           # seconds; exponential backoff base
REQUEST_DELAY = 0.2              # small per-request courtesy pause
# OpenAlex's "polite pool" gives more generous rate limits when you identify
# yourself with a mailto. See https://docs.openalex.org/how-to-use-the-api/rate-limits-and-authentication
OPENALEX_MAILTO = "teohrenjie@gmail.com"


def clean_text(text):
    """Collapse whitespace and strip BibTeX/LaTeX-ish braces."""
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    return text.replace("{", "").replace("}", "").strip()


def sanitize_for_search(title):
    """Strip characters that break OpenAlex full-text search.

    OpenAlex treats characters like '?', '&', '|', and '!' as query operators,
    so a title such as "Is fairness fair?" returns no results unless they're
    removed. We only sanitize the *query*; the original title is kept for output
    and for match comparison.
    """
    cleaned = re.sub(r"[?&|!+\-:()\"]", " ", title)
    return re.sub(r"\s+", " ", cleaned).strip()


# --- Abstract backfill helpers --------------------------------------------
def reconstruct_abstract(inverted_index):
    """Convert an OpenAlex abstract_inverted_index ({word: [positions]}) to text."""
    if not inverted_index:
        return ""
    position_to_word = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            position_to_word[pos] = word
    return " ".join(position_to_word[i] for i in sorted(position_to_word))


async def fetch_abstract_from_openalex(session, title, year, semaphore):
    """Search OpenAlex by title and return the reconstructed abstract, or "".

    Retries with exponential backoff on HTTP 429.
    """
    async with semaphore:
        params = {
            "search": sanitize_for_search(title),
            "per-page": 5,
            "filter": f"publication_year:{year}",
            "mailto": OPENALEX_MAILTO,
        }
        for attempt in range(MAX_RETRIES):
            try:
                async with session.get(
                    "https://api.openalex.org/works", params=params
                ) as response:
                    if response.status == 429:
                        wait = RETRY_BASE_DELAY * (2 ** attempt)
                        print(f"    429 from OpenAlex; backing off {wait:.0f}s ({title[:60]})")
                        await asyncio.sleep(wait)
                        continue
                    response.raise_for_status()
                    data = await response.json()

                results = data.get("results", [])
                if not results:
                    return ""

                title_lower = clean_text(title).lower()

                # Prefer an exact title match, then a substring match, else the top hit.
                best_match = next(
                    (w for w in results if clean_text(w.get("title", "")).lower() == title_lower),
                    None,
                )
                if best_match is None:
                    best_match = next(
                        (
                            w for w in results
                            if title_lower in clean_text(w.get("title", "")).lower()
                            or clean_text(w.get("title", "")).lower() in title_lower
                        ),
                        None,
                    )
                if best_match is None:
                    best_match = results[0]

                await asyncio.sleep(REQUEST_DELAY)
                return reconstruct_abstract(best_match.get("abstract_inverted_index"))
            except asyncio.TimeoutError:
                print(f"    Timeout fetching abstract for: {title[:60]}")
                return ""
            except aiohttp.ClientError as e:
                print(f"    Request failed for '{title[:60]}': {e}")
                return ""
            except Exception as e:
                print(f"    Unexpected error for '{title[:60]}': {e}")
                return ""

        print(f"    Gave up after {MAX_RETRIES} retries (rate limited): {title[:60]}")
        return ""


async def fetch_pmlr_abstract(session, abs_url, semaphore):
    """Visit a PMLR abs page and extract the abstract text, or ""."""
    async with semaphore:
        try:
            async with session.get(abs_url) as response:
                response.raise_for_status()
                html = await response.text()

            soup = BeautifulSoup(html, "html.parser")
            abstract_div = soup.find("div", id="abstract")
            if abstract_div:
                await asyncio.sleep(REQUEST_DELAY)
                return clean_text(abstract_div.get_text(" ", strip=True))

            # Fallback: any block that starts with "Abstract".
            for tag in soup.find_all(["div", "p"]):
                text = clean_text(tag.get_text(" ", strip=True))
                if text.lower().startswith("abstract"):
                    await asyncio.sleep(REQUEST_DELAY)
                    return text.replace("Abstract", "", 1).replace(":", "", 1).strip()
            return ""
        except Exception as e:
            print(f"    Error fetching abstract from {abs_url}: {e}")
            return ""


# --- Per-source scrapers ---------------------------------------------------
async def scrape_pmlr_year(session, year, url, semaphore):
    """Scrape a year hosted on PMLR (2018): walk 'abs' links under Contributed Papers."""
    print(f"  Scraping FAccT {year} from PMLR ({url})...")
    async with session.get(url) as response:
        response.raise_for_status()
        html = await response.text()

    soup = BeautifulSoup(html, "html.parser")
    contributed_header = soup.find(
        lambda tag: tag.name in ["h1", "h2", "h3", "h4"]
        and clean_text(tag.get_text()) == "Contributed Papers"
    )
    if contributed_header is None:
        raise ValueError("Could not find 'Contributed Papers' header.")

    # Collect (title, abs_url) pairs first, then fetch abstracts concurrently.
    items = []
    seen_titles = set()
    for a in contributed_header.find_all_next("a", href=True):
        if clean_text(a.get_text()) != "abs":
            continue
        abs_url = urljoin(url, a["href"])

        # The title is the nearest meaningful preceding sibling block.
        title = ""
        prev = a.parent.find_previous_sibling()
        steps = 0
        while prev and steps < 5:
            text = clean_text(prev.get_text(" ", strip=True))
            if text and "Proceedings of the 1st Conference on Fairness" not in text:
                title = text
                break
            prev = prev.find_previous_sibling()
            steps += 1

        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        items.append((title, abs_url))

    abstracts = await asyncio.gather(
        *(fetch_pmlr_abstract(session, abs_url, semaphore) for _, abs_url in items)
    )

    papers = [
        {
            "title": title,
            "abstract": abstract,
            "year": year,
            "conference": CONFERENCE,
            "url": abs_url,
        }
        for (title, abs_url), abstract in zip(items, abstracts)
    ]
    print(f"  Collected {len(papers)} papers from FAccT {year}")
    return papers


async def scrape_html_year(session, year, url, semaphore):
    """Scrape a facctconference.org accepted-papers page (2019, 2020).

    The page lists titles only (as <h4> links); abstracts are backfilled from
    OpenAlex concurrently.
    """
    print(f"  Scraping FAccT {year} from {url}...")
    async with session.get(url) as response:
        response.raise_for_status()
        html = await response.text()

    soup = BeautifulSoup(html, "html.parser")
    titles = []
    seen_titles = set()
    for h4 in soup.find_all("h4"):
        a = h4.find("a", href=True)
        if not a:
            continue
        title = clean_text(a.get_text())
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        titles.append(title)

    print(f"  Found {len(titles)} titles; backfilling abstracts from OpenAlex...")
    abstracts = await asyncio.gather(
        *(fetch_abstract_from_openalex(session, t, year, semaphore) for t in titles)
    )

    papers = [
        {
            "title": title,
            "abstract": abstract,
            "year": year,
            "conference": CONFERENCE,
            "url": "",
        }
        for title, abstract in zip(titles, abstracts)
    ]
    print(f"  Collected {len(papers)} papers from FAccT {year}")
    return papers


def parse_bib_year(year, bib_path):
    """Parse a committed FAccT BibTeX export (2021-2025)."""
    print(f"  Parsing FAccT {year} from {bib_path}...")
    if bibtexparser is None:
        raise ImportError("bibtexparser is required for FAccT bib years (pip install bibtexparser)")
    if not os.path.exists(bib_path):
        print(f"  WARNING: bib file not found at {bib_path} — skipping {year}.")
        return []

    with open(bib_path, "r", encoding="utf-8") as f:
        bib_database = bibtexparser.load(f)

    target_booktitle = FACCT_BOOKTITLE.format(year=year)

    papers = []
    for entry in bib_database.entries:
        # Keep only the main proceedings for this exact year.
        if target_booktitle not in entry.get("booktitle", ""):
            continue
        if str(entry.get("year", "")).strip() != str(year):
            continue

        papers.append({
            "title": clean_text(entry.get("title", "")),
            "abstract": clean_text(entry.get("abstract", "")),
            "year": year,
            "conference": CONFERENCE,
            "url": clean_text(entry.get("url", "")),
        })

    print(f"  Collected {len(papers)} papers from FAccT {year}")
    return papers


# --- Entry point -----------------------------------------------------------
async def scrape_facct(output=None, start_year=START_YEAR, end_year=END_YEAR):
    """Scrape all FAccT years in [start_year, end_year] and optionally write a CSV.

    Web-scraped years (2018-2020) hit the network concurrently; bib years
    (2021-2025) read input_data/facct/facctYYYY.bib. Returns the list of paper
    dicts.
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    timeout = aiohttp.ClientTimeout(total=60)

    all_papers = []
    async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
        for year in range(start_year, end_year + 1):
            print(f"\n{'-' * 50}\nFAccT {year}\n{'-' * 50}")
            try:
                if year in PMLR_URLS:
                    papers = await scrape_pmlr_year(session, year, PMLR_URLS[year], semaphore)
                elif year in HTML_URLS:
                    papers = await scrape_html_year(session, year, HTML_URLS[year], semaphore)
                elif year in BIB_YEARS:
                    bib_path = os.path.join(FACCT_BIB_DIR, f"facct{year}.bib")
                    papers = parse_bib_year(year, bib_path)
                else:
                    print(f"  No source configured for FAccT {year} — skipping.")
                    papers = []
            except Exception as e:
                print(f"  WARNING: FAccT {year} failed: {e}")
                papers = []
            all_papers.extend(papers)

    if output:
        os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
        with open(output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
            writer.writeheader()
            writer.writerows(all_papers)
        print(f"\nSaved {len(all_papers)} papers to {output}")

    return all_papers


def main():
    parser = argparse.ArgumentParser(
        description="Scrape FAccT papers (2018-2020 from the web, 2021-2025 from bib) into one CSV."
    )
    parser.add_argument(
        "-o", "--output",
        default="facct_abstracts.csv",
        help="Output CSV path (default: facct_abstracts.csv)",
    )
    parser.add_argument("--start-year", type=int, default=START_YEAR)
    parser.add_argument("--end-year", type=int, default=END_YEAR)
    args = parser.parse_args()

    asyncio.run(
        scrape_facct(output=args.output, start_year=args.start_year, end_year=args.end_year)
    )


if __name__ == "__main__":
    main()
