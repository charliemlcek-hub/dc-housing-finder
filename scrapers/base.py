"""Base class and shared utilities for scrapers."""
from __future__ import annotations

import logging
import random
import time
from typing import List, Optional

import requests

from core.models import Listing

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENTS = [
    # Recent Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # Recent Firefox on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:124.0) Gecko/20100101 Firefox/124.0",
    # Recent Safari on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]


class BaseScraper:
    source_name: str = "base"

    def __init__(self, config: dict):
        self.config = config
        self.rate_limit = config["scraping"]["rate_limit_seconds"]
        self.timeout = config["scraping"]["timeout_seconds"]
        self.max_listings = config["scraping"]["max_listings_per_source"]
        self.session = requests.Session()
        self._last_request_time = 0.0

    def _headers(self) -> dict:
        return {
            "User-Agent": random.choice(DEFAULT_USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
        }

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed + random.uniform(0, 0.5))
        self._last_request_time = time.time()

    def get(self, url: str, extra_headers: Optional[dict] = None) -> Optional[requests.Response]:
        self._throttle()
        headers = self._headers()
        if extra_headers:
            headers.update(extra_headers)
        try:
            resp = self.session.get(url, headers=headers, timeout=self.timeout)
            if resp.status_code == 200:
                return resp
            logger.warning("%s: %s returned %d", self.source_name, url, resp.status_code)
            return None
        except requests.RequestException as exc:
            logger.warning("%s: failed to fetch %s: %s", self.source_name, url, exc)
            return None

    def scrape(self) -> List[Listing]:
        raise NotImplementedError
