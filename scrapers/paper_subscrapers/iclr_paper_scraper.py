import openreview
from openreview.api import OpenReviewClient
import csv
import time
import requests
from bs4 import BeautifulSoup
import re
import asyncio
import aiohttp

"""
This code is super finicky and breaks a bunch if the APIs/arxiv decides to rate limit you, but I got it to work
once thank goodness, probably not super replicable though
"""

# Configuration
START_YEAR = 2015
END_YEAR = 2025
OUTPUT_FILE = "iclr_abstracts.csv"

# ICLR venue IDs for each year (2016 and 2015 have to be scraped directly from the website
ICLR_VENUES = {
    2025: "ICLR.cc/2025/Conference",
    2024: "ICLR.cc/2024/Conference",
    2023: "ICLR.cc/2023/Conference",
    2022: "ICLR.cc/2022/Conference",
    2021: "ICLR.cc/2021/Conference",
    2020: "ICLR.cc/2020/Conference",
    2019: "ICLR.cc/2019/Conference",
    2018: "ICLR.cc/2018/Conference",
    2017: "ICLR.cc/2017/conference"
}


def get_note_content(note, key):
    """Helper function to get content from both Note objects and dicts."""
    if isinstance(note, dict):
        content = note.get('content', {}).get(key, '')
    else:
        content = note.content.get(key, '')

    # Handle content being a dict with a 'value' key (API v2 format)
    if isinstance(content, dict):
        content = content.get('value', '')

    return content


def get_note_details(note):
    """Helper function to get details/replies from both Note objects and dicts."""
    if isinstance(note, dict):
        return note.get('details', {}).get('replies', [])
    else:
        if hasattr(note, 'details') and 'replies' in note.details:
            return note.details['replies']
        return []


def scrape_iclr_year(client, year):
    """
    Scrapes ICLR papers for a given year using OpenReview API.
    Returns a list of [title, abstract, year] for each paper.
    """
    print(f"Fetching papers from ICLR {year}...")

    venue_id = ICLR_VENUES.get(year)
    if not venue_id:
        print(f"  ⚠️  No venue ID configured for {year}")
        return []

    papers_data = []

    try:
        # Get all submissions for this venue that were accepted
        # Use the 'invitation' parameter to get accepted papers
        # For 2024+, use API v2 format
        if year >= 2024:
            invitation = f"{venue_id}/-/Submission"
        elif year == 2017 or year == 2016:
            invitation = f"{venue_id}/-/submission" # 2017 and 2016 have weird formats for some reason
        else:
            invitation = f"{venue_id}/-/Blind_Submission"

        submissions = client.get_all_notes(
            invitation=invitation,
            details='replies'
        )

        print(f"  Found {len(submissions)} submissions for {year}")

        for note in submissions:
            # Check if paper was accepted by looking at decision notes
            is_accepted = False

            # For 2024+, check the venueid field directly (API v2 format)
            if year >= 2024:
                note_content = note.get('content', {}) if isinstance(note, dict) else note.content
                # In API v2, accepted papers have venueid set to the accepted track
                venueid = note_content.get('venueid', {})
                venueid_str = venueid.get('value', '')
                if venueid_str and 'Withdrawn' not in venueid_str and 'Rejected' not in venueid_str:
                    is_accepted = True

            # For older years, check decision in replies
            if year < 2024:
                replies = get_note_details(note)
                for reply in replies:
                    # Handle both dict and object replies
                    reply_content = reply.get('content', {}) if isinstance(reply, dict) else reply.content
                    if 'decision' in reply_content:
                        decision = reply_content['decision'].lower()
                        if 'accept' in decision and 'reject' not in decision:
                            is_accepted = True
                            break
                    # 2019 uses the recommendation field instead of decision for some reason lmao
                    if year == 2019 and 'recommendation' in reply_content:
                        recommendation = reply_content['recommendation'].lower()
                        if 'accept' in recommendation and 'reject' not in recommendation:
                            is_accepted = True
                            break

            # Only include accepted papers
            if is_accepted:
                title = get_note_content(note, 'title').strip()
                abstract = get_note_content(note, 'abstract').strip()

                # Only include papers with both title and abstract
                if title and abstract:
                    papers_data.append([title, abstract, year, 'iclr'])

        print(f"  ✅ Collected {len(papers_data)} accepted papers from {year}")
        time.sleep(1)  # Be respectful to the API

    except Exception as e:
        print(f"  ❌ Error fetching {year}: {e}")

    return papers_data

async def fetch_arxiv_paper(session, arxiv_url, semaphore):
    """
    Fetch a single arxiv paper's title and abstract asynchronously.
    """
    async with semaphore:
        try:
            # Make sure we're using the abs page
            if '/abs/' not in arxiv_url:
                # Extract arxiv ID and construct abs URL
                match = re.search(r'(\d+\.\d+)', arxiv_url)
                if match:
                    arxiv_id = match.group(1)
                    arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"

            await asyncio.sleep(0.2)  # Rate limiting

            async with session.get(arxiv_url) as response:
                html = await response.text()
                paper_soup = BeautifulSoup(html, 'html.parser')

                # Extract title
                title_tag = paper_soup.find('h1', class_='title mathjax')
                if title_tag:
                    title = title_tag.get_text().replace('Title:', '').strip()
                else:
                    return None

                # Extract abstract
                abstract_tag = paper_soup.find('blockquote', class_='abstract mathjax')
                if abstract_tag:
                    abstract = abstract_tag.get_text().replace('Abstract:', '').strip()
                else:
                    return None

                if title and abstract:
                    return [title, abstract]

                return None

        except Exception as e:
            print(f"    ❌ Error fetching {arxiv_url}: {e}")
            return None


async def scrape_iclr_site(year):
    """
    Scrapes ICLR papers from the archive website for years not on OpenReview (2015, 2016).
    Returns a list of [title, abstract, year] for each paper.
    Uses async requests for faster scraping.
    """
    print(f"Scraping ICLR {year} from archive website...")

    # Access the archive page
    url = f"https://www.iclr.cc/archive/www/doku.php%3Fid=iclr{year}:accepted-main.html"

    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # Find all arxiv.org links
        arxiv_links = []
        for link in soup.find_all('a', href=True):
            href = link['href']
            if 'arxiv.org' in href:
                # Normalize arxiv URLs to abs format
                if '/abs/' in href:
                    arxiv_links.append(href)
                elif '/pdf/' in href:
                    # Convert PDF links to abs links
                    arxiv_links.append(href.replace('/pdf/', '/abs/').replace('.pdf', ''))
                else:
                    arxiv_links.append(href)

        # Remove duplicates
        arxiv_links = list(set(arxiv_links))
        print(f"  Found {len(arxiv_links)} arxiv links")

        # Fetch all papers concurrently
        semaphore = asyncio.Semaphore(5)  # Limit to 5 concurrent requests

        async with aiohttp.ClientSession() as session:
            tasks = [fetch_arxiv_paper(session, url, semaphore) for url in arxiv_links]
            results = await asyncio.gather(*tasks)

        # Filter out None results and add year
        papers_data = []
        for result in results:
            if result:
                title, abstract = result
                papers_data.append([title, abstract, year, 'iclr'])

        print(f"  ✅ Collected {len(papers_data)} papers from {year}")
        return papers_data

    except Exception as e:
        print(f"  ❌ Error accessing archive page for {year}: {e}")
        return []

async def scrape_iclr(output=OUTPUT_FILE):
    """
    Scrape all ICLR years and save to CSV at `output`.
    Importable entry point used by the master paper_scraper.
    """
    # Initialize OpenReview clients
    print("Initializing OpenReview clients...")
    client_v1 = openreview.Client(baseurl='https://api.openreview.net')
    client_v2 = OpenReviewClient(baseurl='https://api2.openreview.net')

    all_papers = []

    # Scrape each year
    for year in range(START_YEAR, END_YEAR + 1):
        # Use site scraping for 2015 and 2016 (not on OpenReview)
        if year in [2015, 2016]:
            papers = await scrape_iclr_site(year)
        # Use API v2 for 2024 and later
        elif year >= 2024:
            papers = scrape_iclr_year(client_v2, year)
        else:
            papers = scrape_iclr_year(client_v1, year)
        all_papers.extend(papers)

    # Write to CSV
    print(f"\nWriting {len(all_papers)} papers to {output}...")
    with open(output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['title', 'abstract', 'year', 'conference'])
        writer.writerows(all_papers)

    print(f"\n✅ Done! Saved {len(all_papers)} papers to {output}")
    return all_papers


if __name__ == "__main__":
    asyncio.run(scrape_iclr())

