"""Apartments.com scraper.

Strategy: Apartments.com embeds listing data in JSON-LD <script> tags and
data attributes on placard divs. We use curl_cffi (impersonates a real browser
TLS fingerprint) to get past Cloudflare, then parse the resulting HTML.

Each search URL targets a specific neighborhood for better hit rates.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import List, Optional
from urllib.parse import urljoin

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


# URL patterns — apartments.com uses a flat URL scheme per-neighborhood
SEARCH_URLS = [
    "https://www.apartments.com/capitol-hill-washington-dc/min-2-bedrooms-under-3200/",
    "https://www.apartments.com/capitol-hill-washington-dc/2-bedrooms-2-bathrooms/",
    "https://www.apartments.com/navy-yard-washington-dc/2-bedrooms/",
    "https://www.apartments.com/southeast-washington-dc/2-bedrooms-under-3200/",
    "https://www.apartments.com/noma-washington-dc/2-bedrooms/",
    "https://www.apartments.com/southwest-waterfront-washington-dc/2-bedrooms/",
]


class ApartmentsDotComScraper(BaseScraper):
    source_name = "apartments.com"

    def scrape(self) -> List[Listing]:
        if not _HAVE_CFFI:
            logger.warning("curl_cffi not installed — apartments.com scraper will likely fail")

        all_listings: List[Listing] = []
        seen_urls = set()

        for url in SEARCH_URLS:
            logger.info("Apartments.com: scraping %s", url)
            html = self._fetch(url)
            if not html:
                continue

            listings = self._parse_search_page(html)
            for l in listings:
                if l.url not in seen_urls:
                    seen_urls.add(l.url)
                    all_listings.append(l)

            if len(all_listings) >= self.max_listings:
                break
            time.sleep(self.rate_limit)

        logger.info("Apartments.com: collected %d listings", len(all_listings))
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
                logger.warning("Apartments.com %s: %d", url, resp.status_code)
                return None
            except Exception as exc:
                logger.warning("curl_cffi fetch failed for %s: %s", url, exc)
                return None

        resp = self.get(url)
        return resp.text if resp else None

    def _parse_search_page(self, html: str) -> List[Listing]:
        soup = BeautifulSoup(html, "lxml")
        listings: List[Listing] = []

        # Strategy A: JSON-LD embedded SearchResultsPage schema
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            listings.extend(self._parse_ld_json(data))

        # Strategy B: scan article/placard elements for fallback data
        if not listings:
            listings.extend(self._parse_placards(soup))

        return listings

    def _parse_ld_json(self, data) -> List[Listing]:
        results = []
        if isinstance(data, list):
            for item in data:
                results.extend(self._parse_ld_json(item))
            return results

        if not isinstance(data, dict):
            return results

        # SearchResultsPage with `about` or `mainEntity.itemListElement`
        items = []
        if data.get("@type") == "SearchResultsPage":
            items = data.get("about", []) or data.get("mainEntity", {}).get("itemListElement", [])
        elif data.get("@type") == "ApartmentComplex" or data.get("@type") == "Apartment":
            items = [data]

        for item in items:
            if isinstance(item, dict) and "item" in item:
                item = item["item"]
            if not isinstance(item, dict):
                continue
            listing = self._ld_item_to_listing(item)
            if listing:
                results.append(listing)

        return results

    def _ld_item_to_listing(self, item: dict) -> Optional[Listing]:
        try:
            url = item.get("url") or item.get("@id")
            if not url:
                return None
            name = item.get("name", "")
            address_data = item.get("address", {})
            if isinstance(address_data, list):
                address_data = address_data[0] if address_data else {}
            address = " ".join(filter(None, [
                address_data.get("streetAddress"),
                address_data.get("addressLocality"),
                address_data.get("addressRegion"),
            ]))

            geo = item.get("geo", {})
            lat = geo.get("latitude") if isinstance(geo, dict) else None
            lon = geo.get("longitude") if isinstance(geo, dict) else None
            try:
                lat = float(lat) if lat else None
                lon = float(lon) if lon else None
            except (ValueError, TypeError):
                lat = lon = None

            # Price — apartments.com may list a range. Use the lower bound.
            price = None
            offers = item.get("offers") or {}
            if isinstance(offers, list) and offers:
                offers = offers[0]
            if isinstance(offers, dict):
                price_val = offers.get("price") or offers.get("lowPrice")
                if price_val:
                    try:
                        price = int(float(price_val))
                    except (ValueError, TypeError):
                        pass

            source_id = re.sub(r"[^a-z0-9]+", "-", url.lower()).strip("-")[:60]

            return Listing(
                source=self.source_name,
                source_id=source_id,
                url=url,
                title=name or address,
                price=price,
                address=address,
                latitude=lat,
                longitude=lon,
                neighborhood=detect_neighborhood(lat, lon, name, address),
                description=item.get("description", ""),
            )
        except Exception as exc:
            logger.debug("Couldn't parse LD item: %s", exc)
            return None

    def _parse_placards(self, soup: BeautifulSoup) -> List[Listing]:
        results = []
        # Apartments.com uses article.placard / div.placard / li.placard
        for el in soup.select("article.placard, article[data-listingid], li.mortar-wrapper"):
            try:
                link = el.select_one("a.property-link, a[href*='apartments.com']")
                if not link:
                    continue
                url = link.get("href")
                if not url or not url.startswith("http"):
                    url = urljoin("https://www.apartments.com", url or "")
                title = (el.select_one(".property-title, .property-name") or link).get_text(strip=True)
                address_el = el.select_one(".property-address, .property-addressLabel")
                address = address_el.get_text(strip=True) if address_el else None

                price_el = el.select_one(".property-pricing, .price-range")
                price = None
                if price_el:
                    m = re.search(r"\$([0-9,]+)", price_el.get_text())
                    if m:
                        try:
                            price = int(m.group(1).replace(",", ""))
                        except ValueError:
                            pass

                source_id = el.get("data-listingid") or el.get("data-listing-id") or url.rstrip("/").split("/")[-1]

                results.append(Listing(
                    source=self.source_name,
                    source_id=source_id,
                    url=url,
                    title=title,
                    price=price,
                    address=address,
                    neighborhood=detect_neighborhood(None, None, title, address or ""),
                ))
            except Exception as exc:
                logger.debug("Couldn't parse placard: %s", exc)
                continue
        return results
