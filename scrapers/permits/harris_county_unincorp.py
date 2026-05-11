"""
Harris County Unincorporated — Permits Scraper (Phase 1 MVP)

Source: Harris County Engineering Department permit search
Public records, no auth required, robots.txt friendly.

WHAT IT DOES:
1. Queries the HCED permit search for the last N days
2. Filters to permit types we care about (excavation, grading, foundation, etc.)
3. Extracts: permit ID, address, contractor, valuation, dates
4. Upserts into the permits table
5. Tags with relevance keywords for downstream scoring

NOTE ON URL: Harris County's permit portal URL has historically lived at
https://www.eng.hctx.net/Permits — verify this is current before first run
(see docs/DATA_SOURCES.md for the verification checklist). If the portal has
moved or the form has changed, only the selectors in `scrape()` need updating;
the rest of the pipeline is decoupled.
"""

import asyncio
import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# Permit types we care about (case-insensitive substring match)
RELEVANT_PERMIT_TYPES = [
    "excavation", "grading", "site", "foundation",
    "detention", "drainage", "demolition", "demo",
    "paving", "utility", "subdivision", "earthwork",
    "commercial", "new construction",
]

# Tag detection keywords — drives scoring bonuses
TAG_KEYWORDS = {
    "detention_basin": ["detention", "basin", "stormwater pond"],
    "subdivision":     ["subdivision", "phase ", "section ", "tract "],
    "drainage":        ["drainage", "storm sewer", "outfall"],
    "commercial":      ["commercial", "retail", "warehouse", "industrial", "office"],
    "large_lot":       [],  # Set later from lot_size_acres
}


class HarrisCountyUnincorpScraper(BaseScraper):
    source_name = "harris_county_unincorp"
    base_url = "https://www.eng.hctx.net/Permits"
    rate_limit_seconds = 3.0   # Extra polite to county servers

    # Default look-back window for daily runs
    lookback_days = 7

    async def scrape(self) -> list[dict[str, Any]]:
        """Run the scrape — returns list of permits found this run."""
        if not await self.safe_goto(self.base_url):
            return []

        await self.polite_sleep()

        # ─── Set search window ────────────────────────────────────────────
        end_date = date.today()
        start_date = end_date - timedelta(days=self.lookback_days)
        logger.info(
            "Searching %s permits %s → %s",
            self.source_name, start_date, end_date,
        )

        # NOTE: Selectors below are placeholders — verify against live portal.
        # The base class wraps everything in scrape_log so a selector mismatch
        # is logged cleanly without breaking the pipeline.
        try:
            # Set date range in the form
            await self.page.fill("input[name='StartDate']", start_date.strftime("%m/%d/%Y"))
            await self.page.fill("input[name='EndDate']",   end_date.strftime("%m/%d/%Y"))
            await self.page.click("button[type='submit']")
            await self.page.wait_for_load_state("networkidle", timeout=30000)
        except Exception as e:
            logger.error("Search form interaction failed: %s", e)
            logger.info(
                "Selectors likely need updating. See docs/DATA_SOURCES.md "
                "for inspection commands."
            )
            return []

        permits: list[dict[str, Any]] = []
        page_num = 1
        max_pages = 50  # Safety cap

        while page_num <= max_pages:
            logger.info("Scraping page %d", page_num)
            page_permits = await self._extract_page_permits()
            permits.extend(page_permits)
            self.records_found += len(page_permits)

            # Try to advance to next page
            next_button = await self.page.query_selector("a.next-page:not(.disabled)")
            if not next_button:
                break
            await next_button.click()
            await self.page.wait_for_load_state("networkidle")
            await self.polite_sleep()
            page_num += 1

        # Upsert each permit
        for permit in permits:
            try:
                self.upsert_permit(permit)
            except Exception as e:
                logger.error(
                    "Upsert failed for permit %s: %s",
                    permit.get("source_permit_id"), e,
                )

        logger.info(
            "Run complete: found=%d, new=%d, updated=%d",
            self.records_found, self.records_new, self.records_updated,
        )
        return permits

    # ------------------------------------------------------------------
    # Page-level extraction
    # ------------------------------------------------------------------
    async def _extract_page_permits(self) -> list[dict[str, Any]]:
        """Pull permit rows from current results page."""
        rows = await self.page.query_selector_all("table.results tr.permit-row")
        permits = []
        for row in rows:
            try:
                permit = await self._extract_permit_row(row)
                if permit and self._is_relevant(permit):
                    permits.append(permit)
            except Exception as e:
                logger.warning("Row extract failed: %s", e)
        return permits

    async def _extract_permit_row(self, row) -> dict[str, Any] | None:
        """Extract a single permit row into our schema dict."""
        permit_id = (await self._cell_text(row, "td.permit-id")) or ""
        if not permit_id:
            return None

        permit_type = (await self._cell_text(row, "td.permit-type")) or ""
        address     = (await self._cell_text(row, "td.address"))     or ""
        contractor  = (await self._cell_text(row, "td.contractor"))  or ""
        owner       = (await self._cell_text(row, "td.owner"))       or ""
        valuation_s = (await self._cell_text(row, "td.valuation"))   or "0"
        issue_date_s = (await self._cell_text(row, "td.issue-date")) or ""
        description = (await self._cell_text(row, "td.description")) or ""

        valuation = self._parse_money(valuation_s)
        issue_date = self._parse_date(issue_date_s)
        tags = self._detect_tags(permit_type, description, address)

        return {
            "source_permit_id":     permit_id.strip(),
            "permit_type":          self._normalize_type(permit_type),
            "permit_subtype":       permit_type.strip(),
            "status":               "issued",
            "issue_date":           issue_date.isoformat() if issue_date else None,
            "project_address":      address.strip(),
            "city":                 None,        # Filled by geocoder
            "county":               "harris",
            "zip":                  self._extract_zip(address),
            "declared_valuation":   valuation,
            "description":          description.strip(),
            "contractor_name_raw":  contractor.strip() or None,
            "owner_name":           owner.strip() or None,
            "tags":                 json.dumps(tags),
            "raw_data":             json.dumps({
                "scraped_at": datetime.utcnow().isoformat(),
                "valuation_raw": valuation_s,
                "permit_type_raw": permit_type,
            }),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    async def _cell_text(row, selector: str) -> str | None:
        cell = await row.query_selector(selector)
        if not cell:
            return None
        text = await cell.inner_text()
        return text.strip() if text else None

    @staticmethod
    def _parse_money(s: str) -> float:
        if not s:
            return 0.0
        cleaned = re.sub(r"[^\d.]", "", s)
        try:
            return float(cleaned) if cleaned else 0.0
        except ValueError:
            return 0.0

    @staticmethod
    def _parse_date(s: str) -> date | None:
        if not s:
            return None
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
            try:
                return datetime.strptime(s.strip(), fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _extract_zip(address: str) -> str | None:
        m = re.search(r"\b(7[0-9]{4})(?:-\d{4})?\b", address or "")
        return m.group(1) if m else None

    @staticmethod
    def _normalize_type(raw: str) -> str:
        raw_l = (raw or "").lower()
        if any(k in raw_l for k in ["excavat"]):              return "excavation"
        if any(k in raw_l for k in ["grad"]):                  return "grading"
        if any(k in raw_l for k in ["detention", "basin"]):    return "detention_basin"
        if any(k in raw_l for k in ["drain"]):                 return "drainage"
        if any(k in raw_l for k in ["foundation"]):            return "foundation"
        if any(k in raw_l for k in ["pave", "paving"]):        return "paving"
        if any(k in raw_l for k in ["utility", "water", "sewer"]): return "utility"
        if any(k in raw_l for k in ["demo", "demolition"]):    return "demolition"
        if any(k in raw_l for k in ["site", "site develop"]):  return "site_development"
        if any(k in raw_l for k in ["commercial", "retail"]):  return "new_construction_commercial"
        if "residential" in raw_l:                              return "new_construction_residential"
        return "other"

    @staticmethod
    def _detect_tags(permit_type: str, description: str, address: str) -> list[str]:
        haystack = " ".join([permit_type or "", description or "", address or ""]).lower()
        tags = []
        for tag, keywords in TAG_KEYWORDS.items():
            if not keywords:
                continue
            if any(kw in haystack for kw in keywords):
                tags.append(tag)
        return tags

    @staticmethod
    def _is_relevant(permit: dict) -> bool:
        """Filter to permit types we actually care about."""
        haystack = " ".join([
            (permit.get("permit_type") or ""),
            (permit.get("permit_subtype") or ""),
            (permit.get("description") or ""),
        ]).lower()
        return any(kw in haystack for kw in RELEVANT_PERMIT_TYPES)


# ----------------------------------------------------------------------
# CLI entry point
# ----------------------------------------------------------------------
async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    async with HarrisCountyUnincorpScraper() as scraper:
        await scraper.scrape()


if __name__ == "__main__":
    asyncio.run(main())
