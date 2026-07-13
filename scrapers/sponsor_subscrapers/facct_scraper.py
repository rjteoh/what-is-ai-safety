import requests
from bs4 import BeautifulSoup
import pandas as pd


def facct_scraper(year: int) -> pd.DataFrame:
    """
    Scrape sponsors + 'levels' (section headers) from FAccT sponsor pages.

    For most years: https://facctconference.org/<YEAR>/sponsors.html
    2020 special case: https://facctconference.org/2020/sponsorship.html
    """
    if year == 2021:  # FAccT 2021 was held virtually with no sponsors
        print(f"Skipping FAccT {year}: held virtually during the pandemic, no sponsors.")
        return None

    if year == 2020:
        url = "https://facctconference.org/2020/sponsorship.html"
    else:
        url = f"https://facctconference.org/{year}/sponsors.html"

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"HTTP error for FAccT {year}: {e}")
        return pd.DataFrame(columns=["conference", "year", "tier", "sponsor", "url"])

    soup = BeautifulSoup(resp.text, "html.parser")

    # Strategy:
    # 1) Find section headers like "Supporters", "Sponsors", "With Ongoing support from"
    # 2) Collect the sponsor logos/links that appear under each header
    tiers = []
    for header in soup.find_all(["h2", "h3"]):
        title = header.get_text(" ", strip=True)
        if not title:
            continue

        # Heuristic: only keep relevant sponsor-ish sections
        if title.lower() not in {
            "supporters",
            "sponsors",
            "with ongoing support from",
        }:
            continue

        collected = []

        # Walk forward until the next header, collecting <a> and <img>. We emit
        # the raw sponsor string (link href or image filename) here and leave all
        # name canonicalization to sponsor_classifier.py, for consistency with the
        # other conference scrapers.
        node = header.find_next_sibling()
        while node and node.name not in ["h2", "h3"]:
            # Prefer <a> tags (sometimes they link to sponsor sites)
            for a in node.find_all("a", href=True):
                href = a.get("href", "").strip()

                # raw sponsor string could come from the link href OR enclosed img src
                img = a.find("img")
                img_src = img.get("src", "").strip() if img else ""
                name = href or img_src

                if name:
                    collected.append((name, title, year, url))

            # Also handle plain <img> tags that are not wrapped in <a>
            for img in node.find_all("img"):
                name = img.get("src", "").strip()
                if name:
                    collected.append((name, title, year, url))

            node = node.find_next_sibling()

        tiers.extend(collected)

    df = pd.DataFrame(tiers, columns=["sponsor", "tier", "year", "url"])
    if df.empty:
        # If the page format changes, you'll at least get a clean empty result
        df = pd.DataFrame(columns=["sponsor", "tier", "year", "url"])

    df["conference"] = "facct"

    # Clean up sponsor casing a bit (optional)
    df["sponsor"] = df["sponsor"].astype(str).str.strip()

    # Drop obvious duplicates
    df = df.drop_duplicates(subset=["conference", "year", "tier", "sponsor", "url"]).reset_index(drop=True)

    return df


if __name__ == "__main__":
    # Choose the years you need
    years = list(range(2015,2026))

    all_dfs = []
    for y in years:
        print(f"Scraping {y}...")
        all_dfs.append(facct_scraper(y))

    out = pd.concat(all_dfs, ignore_index=True)
    out.to_csv("facct_sponsors.csv", index=False)
    print("Saved: facct_sponsors.csv")
    print(out.head(20))