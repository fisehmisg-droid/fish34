import os
import requests
from dotenv import load_dotenv

load_dotenv()

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")

def scrape_markdown(url: str):
    print(f"Scraping markdown from {url}...")
    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "url": url,
        "formats": ["markdown"]
    }
    try:
        response = requests.post(
            "https://api.firecrawl.dev/v1/scrape",
            json=payload,
            headers=headers
        )
        if response.status_code != 200:
            print(f"Error {response.status_code}: {response.text}")
            return
        data = response.json()
        markdown = data.get("data", {}).get("markdown", "")
        print("Markdown preview (first 1500 chars):")
        print(markdown[:1500])
        print("\n... length:", len(markdown))
    except Exception as e:
        print(f"Failed to scrape {url}: {e}")

if __name__ == "__main__":
    scrape_markdown("https://www.neaea.com/grade-12-english-unit-1-question-answers/")

