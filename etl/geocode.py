"""
Geocoding via U.S. Census Geocoder.

Free, unlimited, no API key required. Used to convert permit addresses
into lat/lng for the map view and county verification.

Falls back to skipping (logs warning) if Census API is down — never blocks the pipeline.
"""

import logging
import sqlite3
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "db" / "construction_intel.db"

CENSUS_GEOCODER = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"


def geocode_address(address: str, timeout: int = 10) -> dict | None:
    """Return {'lat', 'lng', 'matched_address'} or None if no match."""
    if not address or len(address.strip()) < 5:
        return None
    try:
        r = requests.get(
            CENSUS_GEOCODER,
            params={
                "address": address,
                "benchmark": "Public_AR_Current",
                "format": "json",
            },
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
        matches = data.get("result", {}).get("addressMatches", [])
        if not matches:
            return None
        m = matches[0]
        coords = m.get("coordinates", {})
        return {
            "lat": coords.get("y"),
            "lng": coords.get("x"),
            "matched_address": m.get("matchedAddress"),
        }
    except Exception as e:
        logger.warning("Geocode failed for %r: %s", address, e)
        return None


def geocode_pending_permits(db_path: Path = DB_PATH, batch_size: int = 100) -> int:
    """Geocode all permits missing lat/lng. Polite 0.1s delay between requests."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, project_address FROM permits "
            "WHERE (latitude IS NULL OR longitude IS NULL) "
            "  AND project_address IS NOT NULL "
            "LIMIT ?",
            (batch_size,),
        )
        rows = cur.fetchall()
        geocoded = 0
        for row in rows:
            result = geocode_address(row["project_address"])
            if result:
                cur.execute(
                    "UPDATE permits SET latitude = ?, longitude = ?, "
                    "last_updated = CURRENT_TIMESTAMP WHERE id = ?",
                    (result["lat"], result["lng"], row["id"]),
                )
                geocoded += 1
            time.sleep(0.1)  # Be polite to the free service
        conn.commit()
        logger.info("Geocoded %d/%d permits", geocoded, len(rows))
        return geocoded
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    geocode_pending_permits()
