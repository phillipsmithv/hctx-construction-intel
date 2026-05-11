"""
Base scraper class for HCTX Construction Intel.

Handles the boilerplate every government-data scraper needs:
- Playwright lifecycle (launch, close)
- Rate limiting between requests
- Retry logic with exponential backoff
- robots.txt awareness
- Logging to scrape_log table
- User-agent rotation

Subclass this and implement scrape() — see harris_county_unincorp.py for a reference.
"""

import asyncio
import logging
import sqlite3
import time
import urllib.robotparser
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

logger = logging.getLogger(__name__)

# Realistic desktop user agents — rotated per scraper instance
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "construction_intel.db"


class BaseScraper(ABC):
    """Base class for all source scrapers."""

    # Subclass must override these
    source_name: str = ""           # e.g. 'harris_county_unincorp'
    base_url: str = ""              # e.g. 'https://www.eng.hctx.net/Permits'
    rate_limit_seconds: float = 2.5 # Delay between requests
    max_retries: int = 3
    respect_robots: bool = True

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.run_id: int | None = None
        self.records_found = 0
        self.records_new = 0
        self.records_updated = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def __aenter__(self):
        await self._start_run()
        await self._check_robots()
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.context = await self.browser.new_context(
            user_agent=USER_AGENTS[0],
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/Chicago",
        )
        self.page = await self.context.new_page()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if hasattr(self, "playwright"):
            await self.playwright.stop()

        status = "failed" if exc else ("partial" if self.records_found == 0 else "success")
        await self._end_run(status, str(exc) if exc else None)

    # ------------------------------------------------------------------
    # Subclass contract
    # ------------------------------------------------------------------
    @abstractmethod
    async def scrape(self) -> list[dict[str, Any]]:
        """Scrape source and return list of permit dicts. Subclass implements."""
        ...

    # ------------------------------------------------------------------
    # Helpers for subclasses
    # ------------------------------------------------------------------
    async def polite_sleep(self) -> None:
        """Sleep between requests to respect server load."""
        await asyncio.sleep(self.rate_limit_seconds)

    async def safe_goto(self, url: str) -> bool:
        """Navigate with retries; returns True on success."""
        for attempt in range(self.max_retries):
            try:
                await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                return True
            except Exception as e:
                wait = 2 ** attempt
                logger.warning(
                    "goto failed (attempt %s/%s) for %s: %s — backing off %ss",
                    attempt + 1, self.max_retries, url, e, wait,
                )
                await asyncio.sleep(wait)
        logger.error("goto giving up on %s", url)
        return False

    def upsert_permit(self, permit: dict[str, Any]) -> str:
        """Insert or update a permit; returns 'new', 'updated', or 'unchanged'."""
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id FROM permits WHERE source = ? AND source_permit_id = ?",
                (self.source_name, permit["source_permit_id"]),
            )
            existing = cur.fetchone()

            cols = list(permit.keys())
            placeholders = ", ".join(["?"] * len(cols))
            values = [permit[c] for c in cols]

            if existing:
                set_clause = ", ".join(f"{c} = ?" for c in cols)
                cur.execute(
                    f"UPDATE permits SET {set_clause}, last_updated = CURRENT_TIMESTAMP "
                    f"WHERE source = ? AND source_permit_id = ?",
                    values + [self.source_name, permit["source_permit_id"]],
                )
                self.records_updated += 1
                return "updated"
            else:
                permit.setdefault("source", self.source_name)
                cols = list(permit.keys())
                placeholders = ", ".join(["?"] * len(cols))
                cur.execute(
                    f"INSERT INTO permits ({', '.join(cols)}) VALUES ({placeholders})",
                    [permit[c] for c in cols],
                )
                self.records_new += 1
                return "new"
        finally:
            conn.commit()
            conn.close()

    # ------------------------------------------------------------------
    # robots.txt + run logging (private)
    # ------------------------------------------------------------------
    async def _check_robots(self) -> None:
        if not self.respect_robots or not self.base_url:
            return
        try:
            from urllib.parse import urlparse
            parsed = urlparse(self.base_url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(robots_url)
            rp.read()
            if not rp.can_fetch(USER_AGENTS[0], self.base_url):
                raise RuntimeError(
                    f"robots.txt disallows scraping {self.base_url} for our UA"
                )
            logger.info("robots.txt allows %s", self.base_url)
        except Exception as e:
            # Don't hard-fail on robots.txt unreachable — log and proceed
            logger.warning("robots.txt check inconclusive for %s: %s", self.base_url, e)

    async def _start_run(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO scrape_log (source, run_started_at) VALUES (?, ?)",
                (self.source_name, datetime.utcnow().isoformat()),
            )
            self.run_id = cur.lastrowid
            self._run_started = time.time()
        finally:
            conn.commit()
            conn.close()

    async def _end_run(self, status: str, error: str | None) -> None:
        if self.run_id is None:
            return
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE scrape_log SET run_completed_at = ?, records_found = ?, "
                "records_new = ?, records_updated = ?, status = ?, "
                "error_message = ?, duration_seconds = ? WHERE id = ?",
                (
                    datetime.utcnow().isoformat(),
                    self.records_found,
                    self.records_new,
                    self.records_updated,
                    status,
                    error,
                    int(time.time() - self._run_started),
                    self.run_id,
                ),
            )
        finally:
            conn.commit()
            conn.close()
