import requests
from bs4 import BeautifulSoup
import pandas as pd

def standard_scraper(conference_name, year):
    '''
    Simple scraper function for .cc pages that follow a standard format
    '''
    # fetch page and parse html
    url = "https://" + str(conference_name) + ".cc/Conferences/" + str(year) + "/Sponsors"
    try:
        resp = requests.get(url)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e: # error handling so it doesn't crash my loop if a year is missing
        print(f"HTTP error for {conference_name} {year}: {e}")
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    sponsors = []
    for div in soup.find_all("div", class_="logo-box"):
        name = div.get("title", "").strip() # extract sponsor name from div title attribute
        # extract tier from class attribute (it's always the next one after logo-box)
        classes = div.get("class", [])
        if len(classes) > 1:
            tier = classes[1]
        if name and tier: # append to tuple if name and tier exist
            sponsors.append((name, tier, year, url))
    df = pd.DataFrame(sponsors, columns=["sponsor", "tier", "year", "url"])
    df["conference"] = conference_name # add new column with name of conference
    return df

if __name__ == '__main__':
    standard_scraper()