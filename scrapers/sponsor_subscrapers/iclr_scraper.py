import requests
from bs4 import BeautifulSoup
import pandas as pd
from standard_scraper import standard_scraper
import re

def iclr_scraper(year):
    if year in (2018, 2019):  # ICLR did not list sponsors on its website these years
        print(f"Skipping ICLR {year}: no sponsors listed on the conference website.")
        return None
    if year > 2017: # ICLR follows the standard format after 2017
        return standard_scraper("iclr", year)
    else:
        if year == 2015 or year == 2016:
            url = f"https://iclr.cc/archive/www/{year}.html" # 2015 and 2016 follow consistent formatting
        if year == 2017:
            url = "https://iclr.cc/archive/www/doku.php%3Fid=iclr2017:sponsors.html" # special format for 2017
        try:
            resp = requests.get(url)
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:  # error handling
            print(f"HTTP error for ICLR {year}: {e}")
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        sponsors = []
        for tiers in soup.find_all(id=("platinum","gold","silver","bronze")):
            tier = tiers.get("id","")
            div = tiers.find_next_sibling("div")
            for link in div.find_all("a"):
                name = link.get("href", "") # we gotta use URLs because ICLR doesn't have good alt text
                # short parser to extract company name for standard URLs, have to do the rest manually
                match = re.search(r'https?://(?:www\.|research\.)?(.+?)\.com', name)
                if match:
                    name = match.group(1)
                sponsors.append((name, tier, year, url))  # appends to tuple
        df = pd.DataFrame(sponsors, columns=["sponsor", "tier", "year", "url"])
        df["conference"] = "iclr" # add new column with name of conference
        return df
