"""Zillow rental scraper.

Strategy: Zillow embeds all listing data in a <script id="__NEXT_DATA__"> JSON
payload. We fetch the search page with curl_cffi (Chrome TLS fingerprint),
extract that JSON, and walk the result set.
"""
from __future__ import annotations

import json
import logging
import re
from typing import List, Optional

from bs4 import BeautifulSoup

from core.models import Listing
from core.neighborhoods import detect_neighborhood
from .base import BaseScraper

logger = logging.getLogger(__name__)

try:
    from curl_cffi import requests as cffi_requests
    _HAVE_CFFI = True
except ImportError:
    _HAVE_CFFI = False


# DC rental searches with 2bd filter
SEARCH_URLS = [
    # Capitol Hill
    "https://www.zillow.com/capitol-hill-washington-dc/rentals/2-_beds/",
    # Navy Yard / Southeast DC
    "https://www.zillow.com/navy-yard-washington-dc/rentals/2-_beds/",
    # NoMa
    "https://www.zillow.com/noma-washington-dc/rentals/2-_beds/",
    # Southwest
    "https://www.zillow.com/southwest-washington-dc/rentals/2-_beds/",
]


class ZillowScraper(BaseScraper):
    source_name = "zillow"

    def scrape(self) -> List[Listing]:
        if not _HAVE_CFFI:
            logger.warning("curl_cffi not installed — zillow scraper will likely fail")

        all_listings: List[Listing] = []
        seen_urls = set()

        for url in SEARCH_URLS:
            logger.info("Zillow: scraping %s", url)
            html = self._fetch(url)
            if not html:
                continue
            for l in self._parse_search(html):
                if l.url not in seen_urls:
                    seen_urls.add(l.url)
                    all_listings.append(l)
            if len(all_listings) >= self.max_listings:
                break

        logger.info("Zillow: collected %d listings", len(all_listings))
        return all_listings

    def _fetch(self, url: str) -> Optional[str]:
        if _HAVE_CFFI:
            try:
                resp = cffi_requests.get(
                    url,
                    impersonate="chrome120",
                    timeout=self.timeout,
                    headers={"Accept-Language": "en-US,en;q=0.9"},
                )
                if resp.status_code == 200:
                    return resp.text
                logger.warning("Zillow %s: %d", url, resp.status_code)
                return None
            except Exception as exc:
                logger.warning("curl_cffi fetch failed for %s: %s", url, exc)
                return None

        resp = self.get(url)
        return resp.text if resp else None

    def _parse_search(self, html: str) -> List[Listing]:
        soup = BeautifulSoup(html, "lxml")
        script = soup.find("script", id="__NEXT_DATA__")

        results: List[Listing] = []
        if script and script.string:
            try:
                data = json.loads(script.string)
                results.extend(self._walk_next_data(data))
            except json.JSONDecodeError as exc:
                logger.warning("Zillow JSON decode failed: %s", exc)

        # Backup: script blobs containing the initial search results
        if not results:
            results.extend(self._parse_blob(html))

        return results

    def _walk_next_data(self, data) -> List[Listing]:
        """Zillow's __NEXT_DATA__ has different shapes across page variants.
        Recursively find 'searchResults' or 'listResults' containing listings.
        """
        results: List[Listing] = []

        def walk(node):
            if isinstance(node, dict):
                # Common keys that hold the array of listings
                for key in ("listResults", "searchResults", "mapResults"):
                    if key in node and isinstance(node[key], list):
                        for item in node[key]:
                            listing = self._zillow_item_to_listing(item)
                            if listing:
                                results.append(listing)
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(data)
        return results

    def _parse_blob(self, html: str) -> List[Listing]:
        """Fallback: extract inline !--(.*)-- JSON that zillow sometimes uses."""
        results: List[Listing] = []
        m = re.search(r'<!--(\{.*?"listResults".*?\})-->', html, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                results.extend(self._walk_next_data(data))
            except json.JSONDecodeError:
                pass
        return results

    def _zillow_item_to_listing(self, item: dict) -> Optional[Listing]:
        try:
            url = item.get("detailUrl") or item.get("hdpUrl")
            if url and not url.startswith("http"):
                url = "https://www.zillow.com" + url
            if not url:
                return None

            zpid = item.get("zpid") or item.get("id")
            source_id = str(zpid) if zpid else url.rstrip("/").split("/")[-1]

            # Price handling — zillow shows "$2,500/mo" or raw integer
            price = None
            price_val = item.get("unformattedPrice") or item.get("price")
            if isinstance(price_val, (int, float)):
                price = int(price_val)
            elif isinstance(price_val, str):
                m = re.search(r"([0-9,]+)", price_val)
                if m:
                    try:
                        price = int(m.group(1).replace(",", ""))
                    except ValueError:
                        pass

            beds = item.get("beds")
            baths = item.get("baths")
            sqft = item.get("area") or item.get("livingArea")
            try:
                beds = float(beds) if beds is not None else None
                baths = float(baths) if baths is not None else None
                sqft = int(sqft) if sqft else None
            except (ValueError, TypeError):
                pass

            address = item.get("address") or ""
            lat = item.get("latLong", {}).get("latitude") if isinstance(item.get("latLong"), dict) else None
            lon = item.get("latLong", {}).get("longitude") if isinstance(item.get("latLong"), dict) else None

            return Listing(
                source=self.source_name,
                source_id=source_id,
                url=url,
                title=address,
                price=price,
                bedrooms=beds,
                bathrooms=baths,
                sqft=sqft,
                address=address,
                latitude=lat,
                longitude=lon,
                neighborhood=detect_neighborhood(lat, lon, address),
                image_url=item.get("imgSrc"),
            )
        except Exception as exc:
            logger.debug("Couldn't parse Zillow item: %s", exc)
            return None
