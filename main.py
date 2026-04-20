"""Main orchestrator — run scrapers, score, persist, render, notify.

Usage:
  python main.py                    # full run: scrape + render + email
  python main.py --dry-run          # don't send email; print it
  python main.py --no-email         # skip email entirely
  python main.py --no-scrape        # just re-render from DB
  python main.py --alerts-only      # only check extraordinary alerts (no digest)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

# Ensure local imports work when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.database import ListingStore
from core.filters import filter_and_score, infer_amenities
from core.models import Listing
from output.email_sender import send_email
from output.html_generator import render_dashboard
from scrapers.apartments_dot_com import ApartmentsDotComScraper
from scrapers.craigslist import CraigslistScraper
from scrapers.hotpads import HotPadsScraper
from scrapers.zillow import ZillowScraper


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("dc-housing-finder")


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "listings.db"


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


SCRAPERS = [
    CraigslistScraper,
    ApartmentsDotComScraper,
    ZillowScraper,
    HotPadsScraper,
]


def scrape_all(config: dict) -> list[Listing]:
    all_listings: list[Listing] = []
    for scraper_cls in SCRAPERS:
        try:
            scraper = scraper_cls(config)
            listings = scraper.scrape()
            logger.info("%s scraper: %d raw listings", scraper_cls.source_name, len(listings))
            all_listings.extend(listings)
        except Exception as exc:
            logger.exception("%s scraper crashed: %s", scraper_cls.source_name, exc)
    return all_listings


def run(
    *,
    dry_run: bool = False,
    scrape: bool = True,
    email: bool = True,
    alerts_only: bool = False,
    force_send: bool = False,
    config_path: Path = DEFAULT_CONFIG_PATH,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    config = load_config(config_path)
    store = ListingStore(db_path)

    new_listings: list[dict] = []
    if scrape:
        raw = scrape_all(config)
        logger.info("Total raw listings collected: %d", len(raw))

        for l in raw:
            infer_amenities(l)

        kept = filter_and_score(raw, config)
        logger.info("Qualifying listings after filter: %d", len(kept))

        # Persist (upsert); returns those that are brand-new
        new_rows = store.bulk_upsert(kept)
        # Deactivate stale
        deactivated = store.deactivate_stale(hours=72)
        logger.info("New this run: %d | deactivated stale: %d", len(new_rows), deactivated)

        # For email, refetch dicts from DB (gives consistent row shape)
        cutoff = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)).isoformat()
        new_listings = store.new_since(cutoff)

    active = store.active_listings()
    extraordinary_new = store.unalerted_extraordinary()

    # Render HTML
    new_ids = {l["fingerprint"] for l in new_listings}
    output_path = Path(config["dashboard"]["output_dir"]) / "index.html"
    # Make output_dir relative to project root
    output_path = Path(__file__).resolve().parent / output_path
    render_dashboard(active, new_ids, config, output_path)

    # Dashboard URL (from env or fallback)
    dashboard_url = os.environ.get("DASHBOARD_URL", "file://" + str(output_path))

    # Send immediate extraordinary-fit alerts (outside daily cadence)
    if alerts_only:
        if extraordinary_new and email:
            ok = send_email(
                new_listings=[],
                extraordinary=extraordinary_new,
                active_count=len(active),
                config=config,
                dashboard_url=dashboard_url,
                immediate_alert=True,
                dry_run=dry_run,
            )
            if ok and not dry_run:
                for l in extraordinary_new:
                    store.mark_alerted(l["fingerprint"])
        else:
            logger.info("No new extraordinary fits to alert on.")
        return

    # Otherwise, full daily digest (includes extraordinary if any)
    if email:
        # When forcing, surface the top active listings so the email isn't empty
        if force_send and not new_listings and not extraordinary_new:
            new_listings = active[:15]
        ok = send_email(
            new_listings=new_listings,
            extraordinary=extraordinary_new,
            active_count=len(active),
            config=config,
            dashboard_url=dashboard_url,
            immediate_alert=False,
            dry_run=dry_run,
            force=force_send,
        )
        if ok and not dry_run:
            for l in extraordinary_new:
                store.mark_alerted(l["fingerprint"])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="Don't send email; print it instead")
    p.add_argument("--no-scrape", action="store_true", help="Skip scraping, just re-render from DB")
    p.add_argument("--no-email", action="store_true", help="Skip email step entirely")
    p.add_argument("--alerts-only", action="store_true", help="Only send extraordinary-fit alerts")
    p.add_argument("--force-send", action="store_true", help="Send email even if no new listings (for testing)")
    p.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    p.add_argument("--db", default=str(DEFAULT_DB_PATH))
    args = p.parse_args()

    run(
        dry_run=args.dry_run,
        scrape=not args.no_scrape,
        email=not args.no_email,
        alerts_only=args.alerts_only,
        force_send=args.force_send,
        config_path=Path(args.config),
        db_path=Path(args.db),
    )


if __name__ == "__main__":
    main()
