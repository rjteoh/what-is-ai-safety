import asyncio
import aiohttp
from bs4 import BeautifulSoup
import csv
import json

# defining start and end year
START_YEAR = 2015
END_YEAR = 2025

# 2025 breaks on papers.nips.cc for some reason, so for that year we read a
# JSON export (Paper Copilot format) instead of scraping the web. It's fetched
# live from the project's GitHub repo so we don't have to vendor the 38MB file.
NEURIPS_2025_JSON_URL = "https://raw.githubusercontent.com/papercopilot/paperlists/main/nips/nips2025.json"

async def fetch_abstract(session, paper_url, semaphore):
    """fetch abstract for single paper with rate limiting"""
    async with semaphore:
        await asyncio.sleep(0.1)  # rate limiting myself to be respectful to server
        async with session.get(paper_url) as response:
            html = await response.text()
            paper_soup = BeautifulSoup(html, "html.parser")
            abstract_h4 = paper_soup.find("h4", string="Abstract") # find abstract in h4 element
            abstract = abstract_h4.find_next_sibling().text.strip() if abstract_h4 else ""
            return abstract


async def scrape_neurips(year):
    """
    Scrapes NeurIPS proceedings for a given year using async requests for better performance.
    """
    url = f"https://papers.nips.cc/paper_files/paper/{year}"
    semaphore = asyncio.Semaphore(20) # limit concurrent requests to be respectful to server

    async with aiohttp.ClientSession() as session:
        # fetching main page to build link directory - this part doesn't need to be async, but it's easier to be in one function
        async with session.get(url) as response:
            html = await response.text()
            soup = BeautifulSoup(html, "html.parser")

        paper_links = soup.find_all("a", attrs={"title": "paper title"}) # select all paper titles and links

        # create list of paper urls and fetch_abstract tasks
        tasks = []
        paper_data = []
        for link in paper_links:
            paper_title = link.text.strip()
            paper_url = "https://papers.nips.cc" + link["href"]
            paper_data.append((paper_title, paper_url))
            tasks.append(fetch_abstract(session, paper_url, semaphore))

        # fetch all abstracts concurrently
        abstracts = await asyncio.gather(*tasks)

        # combine data by matching each paper with its abstract
        data = []
        for (title, url), abstract in zip(paper_data, abstracts):
            data.append([title, abstract, url, year, 'neurips'])

    return data

async def scrape_neurips_2025_from_json(url=NEURIPS_2025_JSON_URL):
    """
    Load NeurIPS 2025 papers from the Paper Copilot JSON export instead of
    scraping the web (papers.nips.cc isn't reliably serving 2025 yet). The file
    is fetched live from GitHub. Excludes rejected submissions; keeps all
    accepted statuses (Poster/Spotlight/Oral) and tracks.
    Returns a list of [title, abstract, url, year, conference].
    """
    print(f"Loading NeurIPS 2025 from {url}...")
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            response.raise_for_status()
            # raw.githubusercontent.com serves text/plain, so parse manually.
            entries = json.loads(await response.text())

    data = []
    for entry in entries:
        if entry.get("status", "").strip().lower() == "reject":
            continue
        title = (entry.get("title") or "").strip()
        abstract = (entry.get("abstract") or "").strip()
        url = (entry.get("site") or "").strip()
        if not title:
            continue
        data.append([title, abstract, url, 2025, "neurips"])

    print(f"  Loaded {len(data)} accepted papers from NeurIPS 2025 JSON")
    return data


async def scrape_all_neurips(output="neurips_abstracts.csv"):
    """
    Scrape all NeurIPS years and save to CSV at `output`.
    Importable entry point used by the master paper_scraper.
    """
    papers = []
    # iterate and scrape neurips years
    for year in range(START_YEAR, END_YEAR + 1):
        print(f"Scraping year {year}...")
        # 2025 comes from the committed JSON export, not the website.
        if year == 2025:
            data = await scrape_neurips_2025_from_json()
        else:
            data = await scrape_neurips(year)
        papers.extend(data)

    # write to file
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["title", "abstract", "url", "year", "conference"])
        writer.writerows(papers)

    print(f"Saved {len(papers)} papers to {output}")
    return papers

if __name__ == "__main__":
    asyncio.run(scrape_all_neurips())
