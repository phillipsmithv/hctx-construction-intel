"""
Lead Scoring Engine

Reads config/scoring_weights.yaml, applies scoring to all permits in the DB,
and stores the score + breakdown back to each row.

Run after every scrape: `python -m etl.score`
"""

import json
import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "db" / "construction_intel.db"
WEIGHTS_PATH = REPO_ROOT / "config" / "scoring_weights.yaml"
MAX_SCORE = 100


def load_weights() -> dict:
    with open(WEIGHTS_PATH) as f:
        return yaml.safe_load(f)


def score_permit(permit: dict[str, Any], weights: dict, contractor_in_db: bool = False) -> tuple[int, dict]:
    """Return (final_score, breakdown_dict) for a single permit."""
    w = weights["permit_scoring"]
    breakdown: dict[str, int] = {}

    # 1. Permit type
    ptype = (permit.get("permit_type") or "other").lower()
    breakdown["permit_type"] = w["permit_type"].get(ptype, w["permit_type"]["other"])

    # 2. Valuation tier
    val = float(permit.get("declared_valuation") or 0)
    if val < 250_000:
        breakdown["valuation"] = w["declared_valuation"]["under_250k"]
    elif val < 500_000:
        breakdown["valuation"] = w["declared_valuation"]["250k_to_500k"]
    elif val < 1_000_000:
        breakdown["valuation"] = w["declared_valuation"]["500k_to_1m"]
    elif val < 5_000_000:
        breakdown["valuation"] = w["declared_valuation"]["1m_to_5m"]
    else:
        breakdown["valuation"] = w["declared_valuation"]["over_5m"]

    # 3. County
    county = (permit.get("county") or "other").lower()
    breakdown["county"] = w["county"].get(county, w["county"]["other"])

    # 4. Recency
    issue_date_str = permit.get("issue_date")
    if issue_date_str:
        try:
            issue_date = datetime.fromisoformat(issue_date_str).date()
            days_old = (date.today() - issue_date).days
            if days_old <= 7:
                breakdown["recency"] = w["recency"]["issued_within_7_days"]
            elif days_old <= 30:
                breakdown["recency"] = w["recency"]["issued_within_30_days"]
            elif days_old <= 90:
                breakdown["recency"] = w["recency"]["issued_within_90_days"]
            else:
                breakdown["recency"] = w["recency"]["older"]
        except ValueError:
            breakdown["recency"] = 0
    else:
        breakdown["recency"] = 0

    # 5. Bonus tags
    tags_str = permit.get("tags") or "[]"
    try:
        tags = json.loads(tags_str)
    except json.JSONDecodeError:
        tags = []

    if "subdivision" in tags:
        breakdown["bonus_subdivision"] = w["bonus_tags"]["subdivision_keyword"]
    if "commercial" in tags:
        breakdown["bonus_commercial"] = w["bonus_tags"]["commercial_zoning"]
    if "detention_basin" in tags or "drainage" in tags:
        breakdown["bonus_detention"] = w["bonus_tags"]["detention_or_drainage"]
    if "large_lot" in tags:
        breakdown["bonus_large_lot"] = w["bonus_tags"]["large_lot"]
    if contractor_in_db:
        breakdown["bonus_repeat_contractor"] = w["bonus_tags"]["repeat_contractor"]

    raw_score = sum(breakdown.values())
    final_score = max(0, min(MAX_SCORE, raw_score))
    breakdown["__total_raw"] = raw_score
    breakdown["__total_capped"] = final_score
    return final_score, breakdown


def rescore_all_permits(db_path: Path = DB_PATH) -> int:
    """Recompute scores for every permit. Returns count of permits scored."""
    weights = load_weights()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM permits")
        rows = cur.fetchall()

        # Build set of known contractor names for repeat-contractor bonus
        cur.execute("SELECT normalized_name FROM contractors WHERE normalized_name IS NOT NULL")
        known = {r[0] for r in cur.fetchall()}

        scored = 0
        for row in rows:
            permit = dict(row)
            contractor_name = (permit.get("contractor_name_raw") or "").lower().strip()
            in_db = contractor_name in known if contractor_name else False
            score, breakdown = score_permit(permit, weights, in_db)
            cur.execute(
                "UPDATE permits SET lead_score = ?, score_breakdown = ?, "
                "last_updated = CURRENT_TIMESTAMP WHERE id = ?",
                (score, json.dumps(breakdown), permit["id"]),
            )
            scored += 1
        conn.commit()
        logger.info("Rescored %d permits", scored)
        return scored
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    rescore_all_permits()
