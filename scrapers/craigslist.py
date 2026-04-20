"""Craigslist scraper — uses RSS feeds (stable, unblocked).

Craigslist has a quirky but reliable RSS export for any search. We construct
search URLs for each target neighborhood × 2bd min, then parse the RSS.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

import feedparser

from core.models import Listing
from core.neighborhoods import detect_neighborhood
from .base import BaseScraper

logger = logging.getLogger(__name__)

try:
    from curl_cffi import requests as cffi_requests
    _HAVE_CFFI = True
except ImportError:
    _HAVE_CFFI = False


# Craigslist DC searches by neighborhood via the `nh` (neighborhood) filter.
# These IDs correspond to DC neighborhoods in CL's taxonomy.
CL_NEIGHBORHOOD_IDS = {
    "Capitol Hill": [111],
    "Navy Yard": [114, 127],
    "Capitol Riverfront": [114, 127],
    "NoMa": [111],
    "Southwest Waterfront": [127],
    # Capitol South isn't a distinct CL neighborhood, covered by Capitol Hill
}

CL_BASE = "https://washingtondc.craigslist.org/search/apa"


class CraigslistScraper(BaseScraper):
    source_name = "craigslist"

    def _build_feed_url(self, min_price: int, max_price: int, min_bedrooms: int) -> str:
        # format=rss gives us a reliable feed
        params = (
            f"?format=rss&min_price={min_price}&max_price={max_price}"
            f"&min_bedrooms={min_bedrooms}&max_bedrooms={min_bedrooms}"
            f"&availabilityMode=0&sale_date=all+dates"
        )
        # Combine all target neighborhood IDs
        all_ids = set()
        for ids in CL_NEIGHBORHOOD_IDS.values():
            all_ids.update(ids)
        nh_params = "".join(f"&nh={nid}" for nid in sorted(all_ids))
        return CL_BASE + params + nh_params

    def scrape(self) -> List[Listing]:
        s = self.config["search"]
        url = self._build_feed_url(s["min_rent"], s["max_rent"], s["min_bedrooms"])
        logger.info("Craigslist feed URL: %s", url)

        content = self._fetch_rss(url)
        if not content:
            return []

        feed = feedparser.parse(content)
        listings: List[Listing] = []
        for entry in feed.entries[: self.max_listings]:
            listing = self._entry_to_listing(entry)
            if listing:
                listings.append(listing)

        logger.info("Craigslist: collected %d listings", len(listings))
        return listings

    def _fetch_rss(self, url: str):
        if _HAVE_CFFI:
            try:
                resp = cffi_requests.get(url, impersonate="chrome120", timeout=self.timeout)
                if resp.status_code == 200:
                    return resp.content
                logger.warning("Craigslist %s: %d (cffi)", url, resp.status_code)
            except Exception as exc:
                logger.warning("Craigslist cffi failed: %s", exc)
        resp = self.get(url)
        return resp.content if resp else None

    def _entry_to_listing(self, entry) -> Optional[Listing]:
        try:
            url = entry.link
            source_id = url.rstrip("/").split("/")[-1].replace(".html", "")
            title = entry.title

            price = self._extract_price(title)
            bedrooms, bathrooms, sqft = self._extract_layout(title, entry.get("summary", ""))

            # Try to extract coordinates — CL puts them in the entry
            lat = lon = None
            if hasattr(entry, "geo_lat") and hasattr(entry, "geo_long"):
                try:
                    lat = float(entry.geo_lat)
                    lon = float(entry.geo_long)
                except (ValueError, TypeError):
                    pass

            description = entry.get("summary", "") or entry.get("description", "")
            neighborhood = detect_neighborhood(lat, lon, title, description)

            return Listing(
                source=self.source_name,
                source_id=source_id,
                url=url,
                title=title,
                price=price,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                sqft=sqft,
                latitude=lat,
                longitude=lon,
                neighborhood=neighborhood,
                description=description,
                posted_at=entry.get("published", None),
            )
        except Exception as exc:
            logger.warning("Failed to parse CL entry: %s", exc)
            return None

    @staticmethod
    def _extract_price(title: str) -> Optional[int]:
        m = re.search(r"\$([0-9,]+)", title)
        if m:
            try:
                return int(m.group(1).replace(",", ""))
            except ValueError:
                return None
        return None

    @staticmethod
    def _extract_layout(title: str, description: str) -> tuple:
        text = f"{title} {description}".lower()

        bedrooms = None
        bd_match = re.search(r"(\d+)\s*(?:br|bd|bed)", text)
        if bd_match:
            try:
                bedrooms = float(bd_match.group(1))
            except ValueError:
                pass

        bathrooms = None
        ba_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:ba|bath)", text)
        if ba_match:
            try:
                bathrooms = float(ba_match.group(1))
            except ValueError:
                pass

        sqft = None
        sq_match = re.search(r"(\d{3,4})\s*(?:ft|sq\s*ft|sqft)", text)
        if sq_match:
            try:
                sqft = int(sq_match.group(1))
            except ValueError:
                pass

        return bedrooms, bathrooms, sqft
