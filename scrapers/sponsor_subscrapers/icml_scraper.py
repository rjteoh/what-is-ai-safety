import requests
from bs4 import BeautifulSoup
import pandas as pd
from standard_scraper import standard_scraper

def icml_scraper(year):
    if year > 2016: # ICML follows the standard format after 2016
        return standard_scraper("icml", year)
    else:
        url = "https://icml.cc/Conferences/" + str(year) + "/index.html%3Fp=63.html"
        try:
            resp = requests.get(url)
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:  # error handling
            print(f"HTTP error for ICML {year}: {e}")
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        sponsors = []
        for h2 in soup.find_all("h2", class_="pc"):
            tier = h2.get_text(strip=True) # gets sponsor tier
            for element in h2.find_all_next(True):
                if element.name == "img":
                    name = element.get("alt", "") # grabs sponsor name from alt text
                    sponsors.append((name, tier, year, url)) # appends to tuple
                if element.name == "h2":
                    break # breaks out of the loop once we hit the next h2 tag
        df = pd.DataFrame(sponsors, columns=["sponsor", "tier", "year", "url"])
        df["conference"] = "icml" # add new column with name of conference
        return df
