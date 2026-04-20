"""Render the SQLite-backed listing set to a static HTML dashboard."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)


TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def _tier_for(neighborhood: str, config: dict) -> str:
    for tier in ("tier_1", "tier_2", "tier_3"):
        for entry in config["neighborhoods"].get(tier, []):
            if entry["name"] == neighborhood:
                return tier
    return "tier_3"


def _card_flags(listing: dict, config: dict, new_ids: set) -> List[str]:
    flags = []
    if listing.get("is_extraordinary"):
        flags.append("extraordinary")
    tier = _tier_for(listing.get("neighborhood") or "", config)
    flags.append(tier)
    if listing.get("price") and listing["price"] < 2800:
        flags.append("under-2800")
    if listing.get("bedrooms") == 2 and listing.get("bathrooms") == 2:
        flags.append("2bd-2ba")
    if listing.get("fingerprint") in new_ids:
        flags.append("new")
    return flags


def _render_card(listing: dict, config: dict, new_ids: set) -> str:
    flags = _card_flags(listing, config, new_ids)
    is_extra = "extraordinary" in flags
    is_new = "new" in flags
    tier = next((f for f in flags if f.startswith("tier_")), "tier_3")

    badges = []
    if is_extra:
        badges.append('<span class="badge badge-extraordinary">★ extraordinary</span>')
    if is_new:
        badges.append('<span class="badge badge-new">NEW</span>')
    tier_label = {"tier_1": "Tier 1", "tier_2": "Tier 2", "tier_3": "Tier 3"}[tier]
    badges.append(f'<span class="badge badge-{tier}">{tier_label}</span>')

    price = listing.get("price")
    per_person = f" <span class='per-person'>(${price//2:,}/person)</span>" if price else ""

    beds = listing.get("bedrooms")
    baths = listing.get("bathrooms")
    layout = f"{int(beds) if beds else '?'}bd / {baths if baths else '?'}ba"

    def amenity(label, value):
        if value == 1:
            return f'<span class="amenity yes">✓ {label}</span>'
        if value == 0:
            return f'<span class="amenity no">✗ {label}</span>'
        return f'<span class="amenity">{label}?</span>'

    amen_html = "".join([
        amenity("in-unit laundry", listing.get("in_unit_laundry")),
        amenity("parking", listing.get("parking")),
        amenity("gym", listing.get("gym")),
    ])

    title = (listing.get("title") or listing.get("address") or "Listing").strip()
    address = listing.get("address") or listing.get("neighborhood") or ""
    score = listing.get("score") or 0
    source = listing.get("source") or "?"
    url = listing.get("url") or "#"
    neighborhood = listing.get("neighborhood") or "?"

    card_class = "card extraordinary" if is_extra else "card"
    flag_str = " ".join(flags)

    return f'''<div class="{card_class}" data-flags="{flag_str}">
      <div class="score">{score:.0f}</div>
      <div>{" ".join(badges)}</div>
      <h3><a href="{url}" target="_blank" rel="noopener">{title}</a></h3>
      <div class="address">{address}</div>
      <div class="price">${price:,}{per_person}</div>
      <div class="meta">
        <span>{layout}</span>
        <span>{neighborhood}</span>
      </div>
      <div class="amenities">{amen_html}</div>
      <div class="source">via {source}</div>
    </div>'''


def render_dashboard(
    active_listings: List[dict],
    new_ids: set,
    config: dict,
    output_path: Path | str,
) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    extraordinary = [l for l in active_listings if l.get("is_extraordinary")]
    cheapest = min((l.get("price") for l in active_listings if l.get("price")), default=None)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    tmpl = env.get_template("dashboard.html")

    # Pre-render cards so the template stays simple; then inject via string replacement.
    extraordinary_html = [_render_card(l, config, new_ids) for l in extraordinary]
    all_html = [_render_card(l, config, new_ids) for l in active_listings]

    # Use a lightweight render where we pre-build lists of pre-rendered strings
    html = tmpl.render(
        title=config["dashboard"]["title"],
        updated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        active_count=len(active_listings),
        new_today_count=len(new_ids),
        extraordinary_count=len(extraordinary),
        cheapest_price=f"{cheapest:,}" if cheapest else None,
        extraordinary=extraordinary,
        all_listings=active_listings,
        render_card=lambda l, is_extra: _render_card(l, config, new_ids),
    )

    output_path.write_text(html, encoding="utf-8")
    logger.info("Wrote dashboard to %s (%d listings)", output_path, len(active_listings))
