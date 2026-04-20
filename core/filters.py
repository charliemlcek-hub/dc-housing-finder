"""Filtering + scoring. Runs after scrapers, before output."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Iterable, List

from .models import Listing


def _parse_date(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:len(fmt) + 4], fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def passes_hard_filters(listing: Listing, config: dict) -> bool:
    """Return True if listing meets MUST-haves. Filtered out if False."""
    s = config["search"]

    if listing.price is None or listing.price < s["min_rent"] or listing.price > s["max_rent"]:
        return False

    if listing.bedrooms is None or listing.bedrooms < s["min_bedrooms"]:
        return False
    if listing.bedrooms > s["max_bedrooms"]:
        return False

    if listing.bathrooms is None or listing.bathrooms < s["min_bathrooms"]:
        return False

    # Must be in one of the target neighborhoods
    if not listing.neighborhood:
        return False
    all_target_neighborhoods = _all_target_neighborhoods(config)
    if listing.neighborhood not in all_target_neighborhoods:
        return False

    # Must have in-unit laundry (if we can determine). If unknown, allow but penalize in scoring.
    if "in_unit_laundry" in config["must_have"]:
        if listing.in_unit_laundry is False:
            return False  # explicitly no in-unit laundry

    # Availability date (if listing reports one): must overlap move-in window
    start = _parse_date(s.get("move_in_start"))
    end = _parse_date(s.get("move_in_end"))
    avail = _parse_date(listing.available_date)
    if avail and start and end:
        # Allow up to 30 days earlier than start (already available)
        if avail > end:
            return False

    return True


def _all_target_neighborhoods(config: dict) -> set:
    names = set()
    for tier in ("tier_1", "tier_2", "tier_3"):
        for entry in config["neighborhoods"].get(tier, []):
            names.add(entry["name"])
    return names


def _neighborhood_weight(name: str, config: dict) -> int:
    for tier in ("tier_1", "tier_2", "tier_3"):
        for entry in config["neighborhoods"].get(tier, []):
            if entry["name"] == name:
                return entry["score_weight"]
    return 0


def score_listing(listing: Listing, config: dict) -> None:
    """Mutates listing in place with score + breakdown."""
    breakdown = {}
    score = 0.0

    # Neighborhood (up to 100)
    n_weight = _neighborhood_weight(listing.neighborhood or "", config)
    score += n_weight * 0.40
    breakdown["neighborhood"] = round(n_weight * 0.40, 1)

    # Price (up to 40 pts) — cheaper = more points
    if listing.price:
        max_rent = config["search"]["max_rent"]
        min_rent = config["search"]["min_rent"]
        # Normalize: $min_rent → 40, $max_rent → 0
        denom = max(max_rent - min_rent, 1)
        price_score = max(0, min(40, 40 * (max_rent - listing.price) / denom))
        score += price_score
        breakdown["price"] = round(price_score, 1)

    # Bed/bath exact match (up to 15 pts)
    if listing.bedrooms == 2 and listing.bathrooms == 2:
        score += 15
        breakdown["layout"] = 15
    elif listing.bedrooms == 2 and listing.bathrooms == 1:
        score += 5
        breakdown["layout"] = 5

    # Amenities (up to 15 pts total: 5 laundry confirmed + 5 parking + 5 gym)
    amen_score = 0
    if listing.in_unit_laundry:
        amen_score += 5
    if listing.parking:
        amen_score += 5
    if listing.gym:
        amen_score += 5
    score += amen_score
    breakdown["amenities"] = amen_score

    # Penalty for unknown laundry (we allow through hard filter but deduct)
    if listing.in_unit_laundry is None:
        score -= 3
        breakdown["laundry_unknown_penalty"] = -3

    listing.score = round(score, 1)
    listing.score_breakdown = breakdown


def is_extraordinary_fit(listing: Listing, config: dict) -> bool:
    e = config["extraordinary_fit"]
    if listing.price is None or listing.price > e["max_rent"]:
        return False
    if listing.neighborhood not in e["neighborhoods"]:
        return False
    if listing.bedrooms != e["bedrooms"]:
        return False
    if listing.bathrooms != e["bathrooms"]:
        return False
    for req in e.get("required", []):
        if req == "in_unit_laundry" and not listing.in_unit_laundry:
            return False
    return True


def filter_and_score(listings: Iterable[Listing], config: dict) -> List[Listing]:
    results = []
    for l in listings:
        if not passes_hard_filters(l, config):
            continue
        score_listing(l, config)
        l.is_extraordinary = is_extraordinary_fit(l, config)
        results.append(l)
    results.sort(key=lambda x: x.score, reverse=True)
    return results


# ---- Amenity detection from raw description text ----

_LAUNDRY_POSITIVE = [
    r"\bin[- ]?unit (washer|laundry|w\/d|wd)\b",
    r"\bwasher\s*(\/|and)\s*dryer\b",
    r"\bw\/d in unit\b",
    r"\bwasher and dryer in unit\b",
    r"\bfull sized? (washer|w\/d)\b",
    r"\blaundry in[- ]unit\b",
]
_LAUNDRY_NEGATIVE = [
    r"\blaundry (room|on[- ]site|in building|shared)\b",
    r"\bcoin[- ]?op(erated)? laundry\b",
    r"\blaundry (facilities|center)\b",
    r"\bno (in[- ]?unit )?laundry\b",
]
_PARKING_POSITIVE = [
    r"\bparking (included|available|space|spot|garage)\b",
    r"\bgarage parking\b",
    r"\bassigned parking\b",
    r"\boff[- ]?street parking\b",
]
_GYM_POSITIVE = [
    r"\b(fitness center|gym|workout room|fitness room)\b",
]


def infer_amenities(listing: Listing) -> None:
    """Infer boolean amenity flags from description/title if unset."""
    text = " ".join(filter(None, [listing.title, listing.description])).lower()
    if not text:
        return

    if listing.in_unit_laundry is None:
        if any(re.search(p, text) for p in _LAUNDRY_POSITIVE):
            listing.in_unit_laundry = True
        elif any(re.search(p, text) for p in _LAUNDRY_NEGATIVE):
            listing.in_unit_laundry = False

    if listing.parking is None:
        if any(re.search(p, text) for p in _PARKING_POSITIVE):
            listing.parking = True

    if listing.gym is None:
        if any(re.search(p, text) for p in _GYM_POSITIVE):
            listing.gym = True
