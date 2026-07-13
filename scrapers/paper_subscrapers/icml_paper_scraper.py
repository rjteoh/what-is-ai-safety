import aiohttp
import asyncio
from bs4 import BeautifulSoup
import re
import csv

START_YEAR = 2015
END_YEAR = 2025
MAX_CONCURRENT_REQUESTS = 20  # limit concurrent connections to be polite to the server


async def get_icml_urls(start_year, end_year):
    """
    Scrape the MLR Press website to get URLs for ICML proceedings.
    Returns dict of ICML proceedings and year
    """
    base_url = "https://proceedings.mlr.press/"

    print(f"Fetching url list from {base_url}...")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(base_url) as response:
                response.raise_for_status()
                html = await response.text()

        soup = BeautifulSoup(html, 'html.parser')

        # Find all links on the page
        icml_urls = []

        # look for all <li> tags that contain ICML proceedings
        list_items = soup.find_all('li')

        for li in list_items:
            # get the full text of the <li> element
            li_text = li.get_text().strip()

            # match either "ICML XXXX Proceedings" or "Proceedings of ICML XXXX"
            year_match = re.search(r'ICML (\d{4}) Proceedings|Proceedings of ICML (\d{4})', li_text)
            if year_match:
                year = int(year_match.group(1) or year_match.group(2))

                # check if year is in our range
                if start_year <= year <= end_year:
                    # find the <a> tag within this <li>
                    link = li.find('a', href=True)
                    if link:
                        href = link['href']
                        # build full URL
                        full_url = base_url + href
                        # append to dict
                        icml_urls.append({
                            'year': year,
                            'url': full_url
                        })

        return icml_urls

    except aiohttp.ClientError as e:
        print(f"Error fetching website: {e}")
        return []


async def get_paper_abstract(session, abs_url, semaphore):
    """
    Visit the abstract page and scrape the title and abstract.
    Uses semaphore to limit concurrent requests.
    """
    async with semaphore:
        try:
            async with session.get(abs_url) as response:
                response.raise_for_status()
                html = await response.text()

            soup = BeautifulSoup(html, 'html.parser')

            # find title in h1
            title = soup.find('h1')
            title_text = title.get_text().strip()
            abstract = soup.find('div', id='abstract')
            abstract_text = abstract.get_text().strip()

            # Add delay between requests to be polite to the server
            await asyncio.sleep(0.1)

            return title_text, abstract_text

        except aiohttp.ClientError as e:
            print(f"Error fetching abstract from {abs_url}: {e}")
            return "N/A", "N/A"


async def scrape_papers(session, proceedings_url, year):
    """
    Scrape all papers from a proceedings page.
    Returns list of dicts with title, abstract, and year.
    """
    try:
        print(f"Scraping papers from {proceedings_url}...")
        async with session.get(proceedings_url) as response:
            response.raise_for_status()
            html = await response.text()

        soup = BeautifulSoup(html, 'html.parser')

        # Find all links with [abs] text
        all_links = soup.find_all('a', href=True)

        abs_urls = []
        for link in all_links:
            if link.get_text().strip().lower() == 'abs':
                abs_urls.append(link['href'])

        print(f"  Found {len(abs_urls)} abstract links")

        # Create semaphore to limit concurrent requests
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

        # Fetch all abstracts in parallel with rate limiting
        tasks = [get_paper_abstract(session, url, semaphore) for url in abs_urls]
        results = await asyncio.gather(*tasks)

        papers = []
        for title, abstract in results:
            papers.append({
                'title': title,
                'abstract': abstract,
                'year': year,
                'conference': 'icml'
            })

        print(f"Found {len(papers)} papers from {year}")
        return papers

    except aiohttp.ClientError as e:
        print(f"Error fetching proceedings from {proceedings_url}: {e}")
        return []


async def scrape_icml(output="icml_abstracts.csv"):
    """
    Scrape all ICML proceedings and save to CSV at `output`.
    Importable entry point used by the master paper_scraper.
    """
    icml_urls = await get_icml_urls(START_YEAR, END_YEAR)
    print(f"Found {len(icml_urls)} ICML proceedings")
    print()

    all_papers = []

    async with aiohttp.ClientSession() as session:
        for proc in icml_urls:
            papers = await scrape_papers(session, proc['url'], proc['year'])
            all_papers.extend(papers)
            print()

    with open(output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['title', 'abstract', 'year', 'conference'])
        writer.writeheader()
        writer.writerows(all_papers)

    print(f"Done. Scraped {len(all_papers)} papers total.")
    return all_papers


if __name__ == "__main__":
    asyncio.run(scrape_icml())

