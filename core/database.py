"""SQLite-backed listing store for dedup and history."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

from .models import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    fingerprint TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    price INTEGER,
    bedrooms REAL,
    bathrooms REAL,
    sqft INTEGER,
    address TEXT,
    neighborhood TEXT,
    latitude REAL,
    longitude REAL,
    available_date TEXT,
    description TEXT,
    image_url TEXT,
    in_unit_laundry INTEGER,
    parking INTEGER,
    gym INTEGER,
    posted_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    score REAL,
    score_breakdown TEXT,
    is_extraordinary INTEGER DEFAULT 0,
    alerted_at TEXT,
    active INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_listings_active ON listings(active);
CREATE INDEX IF NOT EXISTS idx_listings_extraordinary ON listings(is_extraordinary);
CREATE INDEX IF NOT EXISTS idx_listings_score ON listings(score DESC);
"""


class ListingStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def upsert(self, listing: Listing) -> bool:
        """Insert or update. Returns True if this is the first time we've seen it."""
        now = datetime.utcnow().isoformat()
        with self._conn() as c:
            existing = c.execute(
                "SELECT fingerprint FROM listings WHERE fingerprint = ?",
                (listing.fingerprint,),
            ).fetchone()

            if existing:
                c.execute(
                    """UPDATE listings SET
                        last_seen_at = ?, price = ?, score = ?, score_breakdown = ?,
                        is_extraordinary = ?, active = 1, url = ?
                        WHERE fingerprint = ?""",
                    (now, listing.price, listing.score, json.dumps(listing.score_breakdown),
                     int(listing.is_extraordinary), listing.url, listing.fingerprint),
                )
                return False

            c.execute(
                """INSERT INTO listings (
                    fingerprint, source, source_id, url, title, price, bedrooms, bathrooms,
                    sqft, address, neighborhood, latitude, longitude, available_date,
                    description, image_url, in_unit_laundry, parking, gym, posted_at,
                    first_seen_at, last_seen_at, score, score_breakdown, is_extraordinary, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    listing.fingerprint, listing.source, listing.source_id, listing.url,
                    listing.title, listing.price, listing.bedrooms, listing.bathrooms,
                    listing.sqft, listing.address, listing.neighborhood, listing.latitude,
                    listing.longitude, listing.available_date, listing.description,
                    listing.image_url,
                    None if listing.in_unit_laundry is None else int(listing.in_unit_laundry),
                    None if listing.parking is None else int(listing.parking),
                    None if listing.gym is None else int(listing.gym),
                    listing.posted_at, now, now, listing.score,
                    json.dumps(listing.score_breakdown), int(listing.is_extraordinary),
                ),
            )
            return True

    def bulk_upsert(self, listings: Iterable[Listing]) -> List[Listing]:
        """Returns the subset that are brand-new."""
        new_ones = []
        for l in listings:
            if self.upsert(l):
                new_ones.append(l)
        return new_ones

    def mark_alerted(self, fingerprint: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE listings SET alerted_at = ? WHERE fingerprint = ?",
                (datetime.utcnow().isoformat(), fingerprint),
            )

    def unalerted_extraordinary(self) -> List[dict]:
        with self._conn() as c:
            rows = c.execute(
                """SELECT * FROM listings
                    WHERE is_extraordinary = 1 AND alerted_at IS NULL AND active = 1
                    ORDER BY score DESC"""
            ).fetchall()
            return [dict(r) for r in rows]

    def active_listings(self, limit: Optional[int] = None) -> List[dict]:
        with self._conn() as c:
            sql = "SELECT * FROM listings WHERE active = 1 ORDER BY score DESC"
            if limit:
                sql += f" LIMIT {int(limit)}"
            return [dict(r) for r in c.execute(sql).fetchall()]

    def new_since(self, iso_timestamp: str) -> List[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM listings WHERE first_seen_at >= ? AND active = 1 ORDER BY score DESC",
                (iso_timestamp,),
            ).fetchall()
            return [dict(r) for r in rows]

    def deactivate_stale(self, hours: int = 72) -> int:
        """Mark listings not seen in N hours as inactive."""
        cutoff = datetime.utcnow().timestamp() - hours * 3600
        cutoff_iso = datetime.utcfromtimestamp(cutoff).isoformat()
        with self._conn() as c:
            result = c.execute(
                "UPDATE listings SET active = 0 WHERE last_seen_at < ? AND active = 1",
                (cutoff_iso,),
            )
            return result.rowcount
