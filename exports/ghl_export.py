"""
Go High Level CSV Exporter

Generates a GHL-compatible CSV with hot leads for Jarvis AI outbound campaigns.
Output goes to exports/csv_outputs/ — committed to repo so you can grab from GitHub.

Run after scoring: `python -m exports.ghl_export`
"""

import csv
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "db" / "construction_intel.db"
OUTPUT_DIR = REPO_ROOT / "exports" / "csv_outputs"

# GHL standard contact import fields
GHL_FIELDS = [
    "First Name", "Last Name", "Company", "Email", "Phone",
    "Address", "City", "State", "Postal Code",
    "Tags", "Notes",
    # Custom fields for the construction pipeline
    "Permit ID", "Permit Type", "Project Valuation", "Issue Date",
    "Lead Score", "Pipeline Stage", "Outreach Tier",
]


def export_hot_leads(min_score: int = 70, days_back: int = 30) -> Path:
    """Export hot uncontacted leads to a timestamped CSV."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"ghl_hot_leads_{timestamp}.csv"

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                p.source_permit_id, p.permit_type, p.permit_subtype,
                p.project_address, p.city, p.county, p.zip,
                p.declared_valuation, p.issue_date,
                p.lead_score, p.pipeline_stage, p.tags, p.description,
                c.company_name, c.primary_contact, c.phone, c.email,
                c.outreach_tier, c.contractor_role
            FROM permits p
            LEFT JOIN contractors c ON c.id = p.contractor_id
            WHERE p.lead_score >= ?
              AND p.pipeline_stage IN ('hot', 'contacted')
              AND p.issue_date >= DATE('now', ? || ' days')
            ORDER BY p.lead_score DESC, p.issue_date DESC
            """,
            (min_score, f"-{days_back}"),
        )
        rows = cur.fetchall()

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=GHL_FIELDS)
            writer.writeheader()
            for r in rows:
                contact_name = (r["primary_contact"] or "").strip()
                first, last = "", ""
                if contact_name:
                    parts = contact_name.split(maxsplit=1)
                    first = parts[0]
                    last = parts[1] if len(parts) > 1 else ""

                tags = []
                if r["contractor_role"]:
                    tags.append(f"role:{r['contractor_role']}")
                if r["permit_type"]:
                    tags.append(f"type:{r['permit_type']}")
                tags.append(f"county:{r['county'] or 'unknown'}")
                tags.append(f"score:{(r['lead_score'] // 10) * 10}+")

                notes = (
                    f"Permit {r['source_permit_id']} | "
                    f"{r['permit_subtype'] or r['permit_type']} | "
                    f"${(r['declared_valuation'] or 0):,.0f} | "
                    f"Issued {r['issue_date'] or 'unknown'} | "
                    f"{(r['description'] or '')[:200]}"
                )

                writer.writerow({
                    "First Name":        first,
                    "Last Name":         last,
                    "Company":           r["company_name"] or "",
                    "Email":             r["email"] or "",
                    "Phone":             r["phone"] or "",
                    "Address":           r["project_address"] or "",
                    "City":              r["city"] or "",
                    "State":             "TX",
                    "Postal Code":       r["zip"] or "",
                    "Tags":              ",".join(tags),
                    "Notes":             notes,
                    "Permit ID":         r["source_permit_id"],
                    "Permit Type":       r["permit_type"] or "",
                    "Project Valuation": r["declared_valuation"] or 0,
                    "Issue Date":        r["issue_date"] or "",
                    "Lead Score":        r["lead_score"],
                    "Pipeline Stage":    r["pipeline_stage"],
                    "Outreach Tier":     r["outreach_tier"] or "",
                })

        logger.info("Exported %d leads → %s", len(rows), output_path)
        return output_path
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    export_hot_leads()
