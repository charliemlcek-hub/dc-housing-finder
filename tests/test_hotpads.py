"""Quick manual test of HotPads scraper."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml
from scrapers.hotpads import HotPadsScraper

config = yaml.safe_load(open(Path(__file__).resolve().parent.parent / "config.yaml"))
s = HotPadsScraper(config)
listings = s.scrape()
print(f"Got {len(listings)} listings")
for l in listings[:5]:
    print(f"  ${l.price} — {l.title or l.address} | {l.neighborhood} | {l.bedrooms}bd/{l.bathrooms}ba")
