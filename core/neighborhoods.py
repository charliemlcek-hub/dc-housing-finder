"""Neighborhood detection via bounding polygons + name matching.

Coords are approximate, drawn to cover each neighborhood's commonly-understood
footprint. Overlaps are resolved by the order in `NEIGHBORHOOD_ORDER` (first wins).
"""
from __future__ import annotations

from typing import Optional

try:
    from shapely.geometry import Point, Polygon
    _HAVE_SHAPELY = True
except ImportError:
    _HAVE_SHAPELY = False


# (lon, lat) polygon vertices — roughly approximating each neighborhood.
NEIGHBORHOOD_POLYGONS = {
    "Capitol Hill": [
        (-77.0095, 38.8970),  # NW corner (near Union Station)
        (-76.9820, 38.8970),  # NE (Lincoln Park area)
        (-76.9820, 38.8760),  # SE (near 295)
        (-77.0050, 38.8760),  # SW (near Navy Yard border)
        (-77.0095, 38.8860),  # W (back up to N Capitol)
    ],
    "Capitol South": [
        # Tight cluster around Capitol South Metro (1st St SE & D St SE)
        (-77.0100, 38.8890),
        (-77.0020, 38.8890),
        (-77.0020, 38.8820),
        (-77.0100, 38.8820),
    ],
    "Navy Yard": [
        (-77.0095, 38.8760),
        (-76.9950, 38.8760),
        (-76.9950, 38.8680),
        (-77.0095, 38.8680),
    ],
    "Capitol Riverfront": [
        (-77.0130, 38.8770),
        (-76.9920, 38.8770),
        (-76.9920, 38.8680),
        (-77.0130, 38.8680),
    ],
    "NoMa": [
        (-77.0120, 38.9110),
        (-76.9950, 38.9110),
        (-76.9950, 38.8970),
        (-77.0120, 38.8970),
    ],
    "Southwest Waterfront": [
        (-77.0280, 38.8830),
        (-77.0100, 38.8830),
        (-77.0100, 38.8720),
        (-77.0280, 38.8720),
    ],
}

# Preference order when a point falls in multiple polygons
NEIGHBORHOOD_ORDER = [
    "Capitol South",   # most specific first
    "Capitol Hill",
    "Navy Yard",
    "Capitol Riverfront",
    "Southwest Waterfront",
    "NoMa",
]

# Keyword hints used when we only have text (no coords)
NEIGHBORHOOD_KEYWORDS = {
    "Capitol Hill": ["capitol hill", "capitol-hill", "cap hill", "eastern market",
                     "lincoln park", "stanton park", "barracks row"],
    "Capitol South": ["capitol south"],
    "Navy Yard": ["navy yard", "navy-yard"],
    "Capitol Riverfront": ["capitol riverfront", "riverfront", "ballpark district",
                           "near nationals park"],
    "NoMa": ["noma", "north of massachusetts", "union market"],
    "Southwest Waterfront": ["southwest waterfront", "sw waterfront", "the wharf",
                             "waterfront sw"],
}


def neighborhood_from_coords(lat: Optional[float], lon: Optional[float]) -> Optional[str]:
    if lat is None or lon is None or not _HAVE_SHAPELY:
        return None
    point = Point(lon, lat)
    for name in NEIGHBORHOOD_ORDER:
        poly = Polygon(NEIGHBORHOOD_POLYGONS[name])
        if poly.contains(point):
            return name
    return None


def neighborhood_from_text(*texts: Optional[str]) -> Optional[str]:
    """Scan address / title / description for neighborhood keywords."""
    combined = " ".join(t.lower() for t in texts if t)
    if not combined:
        return None
    for name in NEIGHBORHOOD_ORDER:
        for kw in NEIGHBORHOOD_KEYWORDS[name]:
            if kw in combined:
                return name
    return None


def detect_neighborhood(lat, lon, *texts) -> Optional[str]:
    """Prefer coord-based detection, fall back to keyword matching."""
    return neighborhood_from_coords(lat, lon) or neighborhood_from_text(*texts)
