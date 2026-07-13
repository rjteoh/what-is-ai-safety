import requests
from bs4 import BeautifulSoup
import pandas as pd
import sys
import os

def naacl_scraper(year):
    '''
    Simple scraper function for AACL sponsors that returns a df
    '''
    if year in (2017, 2020, 2023):  # NAACL was not held these years
        print(f"Skipping NAACL {year}: conference was not held this year.")
        return None

    # list of all url formats
    urls = [
        f"https://{year}.naacl.org/sponsors/",
        f"https://naacl.org/naacl-hlt-{year}/sponsors/list/",
        f"https://naacl.org/naacl-hlt-{year}/sponsor.html",
        f"https://naacl.org/naacl-hlt-{year}/sponsors.html"
    ]

    # list of all tier keywords
    tier_keywords = ['diamond', 'platinum', 'gold', 'silver', 'bronze']

    # loop to try all url variants
    resp = None
    for url in urls:
        try:
            resp = requests.get(url)
            resp.raise_for_status()
            break # worked, break loop
        except requests.exceptions.RequestException:
            resp = None
            continue  # try next url
    if resp is None: # error handling so I know what failed
        print(f"All URLs failed for naacl {year}")
        return None

    # initialising variables
    sponsors = []

    soup = BeautifulSoup(resp.text, "html.parser")
    # logic for the page types ending with sponsors.html
    if url.endswith('.html'):
        # sponsor names aren't written out so we have to extract from the image
        for img in soup.find_all('img', class_=['sponsor-img', 'sponsorlogo', 'sponsor-logo', 'sponsor-logo-vertical']):
            alt = img.get('alt', '')
            if alt:
                name = alt # grab name if we can find it from alt text easily
            else:
                img_url = img.get('src', '') # if not, grab from url
                if img_url:
                    name = os.path.splitext(img_url.split('/')[-1])[0]
                    name = name.replace("-logo", "")
            # find nearest tier keyword above this img
            tier = None
            for element in img.find_all_previous():
                element_text = element.get_text(strip=True).lower()
                for keyword in tier_keywords:
                    if keyword in element_text:
                        tier = element_text
                        break
                if tier:  # stop once we found a tier
                    break
            if name and tier:  # safety check
                sponsors.append((name, tier, year, url))

    # logic for the other two url versions - same logic works for both
    else:
        for element in soup.find_all(['h2', 'figure']):
            # grab sponsor name from h2 headers
            if element.name == 'h2':
                tier = element.get_text(strip=True)
            # grab sponsor names from html figure element
            elif element.name == 'figure' and tier:
                for link in element.find_all("a"):
                    if link: # safety check
                        name = link.get('title', '').strip() # grab name from title field
                        if name: # safety check
                            sponsors.append((name, tier, year, url))

    # convert to df for exporting
    df = pd.DataFrame(sponsors, columns=["sponsor", "tier", "year", "url"])
    df["conference"] = "naacl"

    return df