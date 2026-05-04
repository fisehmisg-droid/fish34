from firecrawl import FirecrawlApp
import os

app = FirecrawlApp(api_key='test')
print("Methods on app:", [m for m in dir(app) if not m.startswith('_')])
import inspect
print("\nSignature of scrape:")
try:
    print(inspect.signature(app.scrape_url))
except Exception as e:
    print("scrape_url err:", e)
try:
    print(inspect.signature(app.scrape))
except Exception as e:
    print("scrape err:", e)
