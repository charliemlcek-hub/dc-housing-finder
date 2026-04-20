"""HotPads rental scraper.

Strategy: HotPads (owned by Zillow) exposes listing data in embedded JSON
on the search page. We parse the __NEXT_DATA__-like blob, or fall back to
the visible listing cards.
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


def _pick_photo(val):
    """HotPads photos can be strings or nested dicts. Return a url string or None."""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        return val.get("url") or val.get("src") or val.get("originalUrl")
    return None


SEARCH_URLS = [
    "https://hotpads.com/washington-dc/apartments-for-rent?beds=2&maxRent=3200",
    "https://hotpads.com/capitol-hill-washington-dc/apartments-for-rent?beds=2&maxRent=3200",
    "https://hotpads.com/navy-yard-washington-dc/apartments-for-rent?beds=2&maxRent=3200",
    "https://hotpads.com/noma-washington-dc/apartments-for-rent?beds=2&maxRent=3200",
]


class HotPadsScraper(BaseScraper):
    source_name = "hotpads"

    def scrape(self) -> List[Listing]:
        all_listings: List[Listing] = []
        seen = set()

        for url in SEARCH_URLS:
            logger.info("HotPads: scraping %s", url)
            html = self._fetch(url)
            if not html:
                continue
            for l in self._parse(html):
                if l.url in seen:
                    continue
                seen.add(l.url)
                all_listings.append(l)
            if len(all_listings) >= self.max_listings:
                break

        logger.info("HotPads: collected %d listings", len(all_listings))
        return all_listings

    def _fetch(self, url: str) -> Optional[str]:
        if _HAVE_CFFI:
            try:
                resp = cffi_requests.get(url, impersonate="chrome120", timeout=self.timeout)
                if resp.status_code == 200:
                    return resp.text
            except Exception as exc:
                logger.warning("hotpads curl_cffi failed: %s", exc)
        resp = self.get(url)
        return resp.text if resp else None

    def _parse(self, html: str) -> List[Listing]:
        results: List[Listing] = []

        # Find "window.__PRELOADED_STATE__ = " and walk braces to find the end
        data = self._extract_preloaded_state(html)
        if data:
            results.extend(self._walk(data))

        if not results:
            soup = BeautifulSoup(html, "lxml")
            nd = soup.find("script", id="__NEXT_DATA__")
            if nd and nd.string:
                try:
                    results.extend(self._walk(json.loads(nd.string)))
                except json.JSONDecodeError:
                    pass

        return results

    @staticmethod
    def _extract_preloaded_state(html: str):
        """Find `window.__PRELOADED_STATE__ = {...};` and parse via brace matching."""
        anchor = "window.__PRELOADED_STATE__"
        idx = html.find(anchor)
        if idx == -1:
            return None
        # Skip past '= '
        start = html.find("{", idx)
        if start == -1:
            return None
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(html)):
            ch = html[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    blob = html[start:i + 1]
                    try:
                        return json.loads(blob)
                    except json.JSONDecodeError as exc:
                        logger.debug("HotPads JSON decode failed: %s", exc)
                        return None
        return None

    def _walk(self, node) -> List[Listing]:
        """HotPads structure: data['listings']['listingGroups']['byCoords'] is the key list."""
        results: List[Listing] = []
        listings_root = node.get("listings") if isinstance(node, dict) else None
        if not isinstance(listings_root, dict):
            return results

        groups = listings_root.get("listingGroups", {})
        if isinstance(groups, dict):
            for group_name in ("byCoords", "mostPopular", "petFriendly"):
                items = groups.get(group_name)
                if isinstance(items, list):
                    for it in items:
                        listing = self._item_to_listing(it)
                        if listing:
                            results.append(listing)

        # listingsByArea is a dict keyed by area ID → list of listings
        by_area = listings_root.get("listingsByArea", {})
        if isinstance(by_area, dict):
            for v in by_area.values():
                if isinstance(v, list):
                    for it in v:
                        listing = self._item_to_listing(it)
                        if listing:
                            results.append(listing)

        # Dedup by url
        seen_urls = set()
        deduped = []
        for l in results:
            if l.url in seen_urls:
                continue
            seen_urls.add(l.url)
            deduped.append(l)
        return deduped

    def _item_to_listing(self, item) -> Optional[Listing]:
        if not isinstance(item, dict):
            return None
        try:
            uri = item.get("uriV2") or item.get("uriMalone") or item.get("urlMaloneUnit")
            if not uri:
                return None
            url = uri if uri.startswith("http") else "https://hotpads.com" + uri

            source_id = item.get("aliasEncoded") or uri.strip("/").split("/")[-1]

            # Price + beds + baths from listingMinMaxPriceBeds
            lmp = item.get("listingMinMaxPriceBeds") or {}
            price = lmp.get("minPrice") or lmp.get("maxPrice")
            try:
                price = int(price) if price else None
            except (ValueError, TypeError):
                price = None

            # Prefer max when min is 0 or missing — HotPads often has only max populated
            def _best(minv, maxv):
                if minv not in (None, 0):
                    return minv
                if maxv not in (None, 0):
                    return maxv
                return None

            beds = _best(lmp.get("minBeds"), lmp.get("maxBeds"))
            baths = _best(lmp.get("minBaths"), lmp.get("maxBaths"))
            try:
                beds = float(beds) if beds is not None else None
                baths = float(baths) if baths is not None else None
            except (ValueError, TypeError):
                beds = baths = None

            geo = item.get("geo") or {}
            lat = geo.get("lat")
            lon = geo.get("lon")
            try:
                lat = float(lat) if lat else None
                lon = float(lon) if lon else None
            except (ValueError, TypeError):
                lat = lon = None

            addr = item.get("address") or {}
            address_str = " ".join(filter(None, [
                addr.get("street"), addr.get("city"), addr.get("state"), addr.get("zip"),
            ]))

            title = item.get("displayName") or addr.get("street") or "Listing"

            # Amenities from highlights[].id
            amenities = item.get("amenities") or {}
            highlight_ids = set()
            for h in amenities.get("highlights", []):
                if isinstance(h, dict) and h.get("id"):
                    highlight_ids.add(h["id"])

            # HotPads doesn't explicitly flag "in-unit laundry" as a top highlight;
            # check if description mentions it.
            description = item.get("fullDescription") or ""
            gym = "gym" in highlight_ids
            parking = "parking" in highlight_ids

            # laundry parse: check description for in-unit patterns
            in_unit_laundry = None
            desc_lower = description.lower()
            if any(p in desc_lower for p in ["in-unit laundry", "in unit laundry",
                                              "washer and dryer in unit",
                                              "w/d in unit", "in-unit w/d"]):
                in_unit_laundry = True

            return Listing(
                source=self.source_name,
                source_id=str(source_id),
                url=url,
                title=title,
                price=price,
                bedrooms=beds,
                bathrooms=baths,
                address=address_str,
                latitude=lat,
                longitude=lon,
                neighborhood=detect_neighborhood(lat, lon, title, address_str, addr.get("neighborhood") or ""),
                description=description,
                image_url=_pick_photo(item.get("previewPhotoMed") or item.get("previewPhoto")),
                gym=gym,
                parking=parking,
                in_unit_laundry=in_unit_laundry,
            )
        except Exception as exc:
            logger.debug("HotPads parse error: %s", exc)
            return None
