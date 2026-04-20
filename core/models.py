"""Shared data models for listings."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class Listing:
    source: str
    source_id: str
    url: str
    title: str
    price: Optional[int] = None
    bedrooms: Optional[float] = None
    bathrooms: Optional[float] = None
    sqft: Optional[int] = None
    address: Optional[str] = None
    neighborhood: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    available_date: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None

    # Amenity flags (booleans or None if unknown)
    in_unit_laundry: Optional[bool] = None
    parking: Optional[bool] = None
    gym: Optional[bool] = None

    posted_at: Optional[str] = None       # ISO timestamp string
    scraped_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    # Computed after scraping
    score: float = 0.0
    score_breakdown: dict = field(default_factory=dict)
    is_extraordinary: bool = False

    @property
    def fingerprint(self) -> str:
        """Stable fingerprint across sources to deduplicate."""
        norm = "|".join([
            (self.address or "").strip().lower(),
            str(self.price or ""),
            str(self.bedrooms or ""),
            str(self.bathrooms or ""),
        ])
        # Fall back to source+source_id if address is missing
        if not self.address:
            norm = f"{self.source}|{self.source_id}"
        return hashlib.sha256(norm.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def per_person_rent(self) -> Optional[float]:
        if self.price is None:
            return None
        return round(self.price / 2, 2)
