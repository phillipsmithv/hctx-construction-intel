-- HCTX Construction Intel — SQLite Schema
-- Reuses the proven HCTX-Intel pattern: SQLite committed to repo, sql.js queries in browser.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ============================================================================
-- PERMITS — Phase 1 (Active construction permits, the immediate signal)
-- ============================================================================
CREATE TABLE IF NOT EXISTS permits (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    source                  TEXT    NOT NULL,                    -- 'harris_co', 'houston', 'pearland', etc.
    source_permit_id        TEXT    NOT NULL,
    permit_type             TEXT,                                 -- 'excavation', 'grading', 'foundation', 'detention'
    permit_subtype          TEXT,
    status                  TEXT,                                 -- 'issued', 'in_review', 'finaled', 'expired'
    issue_date              DATE,
    expiration_date         DATE,
    project_address         TEXT,
    city                    TEXT,
    county                  TEXT,
    zip                     TEXT,
    latitude                REAL,
    longitude               REAL,
    declared_valuation      DECIMAL(12, 2),
    description             TEXT,
    contractor_id           INTEGER,                              -- FK to contractors.id (the GC, Tier 2)
    contractor_name_raw     TEXT,                                 -- As scraped, before normalization
    owner_name              TEXT,
    owner_address           TEXT,
    parcel_id               TEXT,
    hcad_account            TEXT,
    lot_size_acres          REAL,
    lead_score              INTEGER DEFAULT 0,                    -- 0-100
    score_breakdown         TEXT,                                 -- JSON
    tags                    TEXT,                                 -- JSON array: ['detention_basin', 'subdivision']
    pipeline_stage          TEXT    DEFAULT 'hot',                -- 'hot', 'contacted', 'engaged', 'quoted', 'won', 'cold'
    ghl_contact_id          TEXT,
    last_outreach_date      DATE,
    notes                   TEXT,
    raw_data                TEXT,                                 -- Full source payload (JSON)
    first_seen              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, source_permit_id),
    FOREIGN KEY (contractor_id) REFERENCES contractors(id)
);

CREATE INDEX IF NOT EXISTS idx_permits_score        ON permits(lead_score DESC);
CREATE INDEX IF NOT EXISTS idx_permits_issue_date   ON permits(issue_date DESC);
CREATE INDEX IF NOT EXISTS idx_permits_county       ON permits(county);
CREATE INDEX IF NOT EXISTS idx_permits_stage        ON permits(pipeline_stage);
CREATE INDEX IF NOT EXISTS idx_permits_geo          ON permits(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_permits_type         ON permits(permit_type);

-- ============================================================================
-- BIDS — Phase 2 (Upcoming projects, 30-90 day forward signal)
-- ============================================================================
CREATE TABLE IF NOT EXISTS bids (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    source                  TEXT    NOT NULL,                    -- 'txdot', 'harris_purchasing', 'houston_proc'
    source_bid_id           TEXT,
    project_name            TEXT,
    description             TEXT,
    estimated_value         DECIMAL(14, 2),
    bid_open_date           DATE,
    pre_bid_meeting_date    TIMESTAMP,
    project_location        TEXT,
    county                  TEXT,
    work_categories         TEXT,                                 -- JSON: ['earthwork', 'paving', 'drainage']
    contact_name            TEXT,
    contact_email           TEXT,
    contact_phone           TEXT,
    documents_url           TEXT,
    lead_score              INTEGER DEFAULT 0,
    relevance_tags          TEXT,                                 -- JSON
    pipeline_stage          TEXT    DEFAULT 'hot',
    first_seen              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, source_bid_id)
);

CREATE INDEX IF NOT EXISTS idx_bids_score           ON bids(lead_score DESC);
CREATE INDEX IF NOT EXISTS idx_bids_open_date       ON bids(bid_open_date);

-- ============================================================================
-- AWARDS — Phase 3 (Contract awards = who won = who hires subs)
-- ============================================================================
CREATE TABLE IF NOT EXISTS awards (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    source                  TEXT,                                 -- 'commissioners_court', 'city_council'
    award_date              DATE,
    project_name            TEXT,
    award_amount            DECIMAL(14, 2),
    awarded_to_company      TEXT,
    awarded_to_address      TEXT,
    project_description     TEXT,
    project_location        TEXT,
    agenda_item_url         TEXT,
    pdf_source_url          TEXT,
    contractor_id           INTEGER,                              -- FK once we resolve to contractor
    lead_score              INTEGER DEFAULT 0,
    first_seen              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (contractor_id) REFERENCES contractors(id)
);

CREATE INDEX IF NOT EXISTS idx_awards_date          ON awards(award_date DESC);
CREATE INDEX IF NOT EXISTS idx_awards_company       ON awards(awarded_to_company);

-- ============================================================================
-- CIP_PROJECTS — Phase 4 (Long-horizon pipeline from bond programs, CIP plans)
-- ============================================================================
CREATE TABLE IF NOT EXISTS cip_projects (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    agency                  TEXT,                                 -- 'HCFCD', 'HISD', 'COH_PWE'
    project_id              TEXT,
    project_name            TEXT,
    project_phase           TEXT,                                 -- 'planning', 'design', 'construction', 'complete'
    estimated_start_date    DATE,
    estimated_completion    DATE,
    budget                  DECIMAL(14, 2),
    location                TEXT,
    project_manager         TEXT,
    pm_email                TEXT,
    description             TEXT,
    document_links          TEXT,                                 -- JSON
    last_updated            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- CONTRACTORS — Master registry, built up across all sources & all 3 tiers
-- ============================================================================
CREATE TABLE IF NOT EXISTS contractors (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name            TEXT    NOT NULL,
    normalized_name         TEXT    UNIQUE,                       -- For dedup matching across sources
    license_number          TEXT,
    primary_contact         TEXT,
    phone                   TEXT,
    email                   TEXT,
    address                 TEXT,
    city                    TEXT,
    state                   TEXT,
    zip                     TEXT,
    contractor_role         TEXT,                                 -- 'gc', 'sub_dirt', 'sub_excavation', 'sub_utility', 'developer', 'owner'
    outreach_tier           INTEGER,                              -- 1, 2, or 3
    permit_count            INTEGER DEFAULT 0,
    bid_count               INTEGER DEFAULT 0,
    award_count             INTEGER DEFAULT 0,
    total_project_value     DECIMAL(14, 2) DEFAULT 0,
    work_specialties        TEXT,                                 -- JSON: ['excavation', 'concrete', 'utility']
    last_active_date        DATE,
    outreach_status         TEXT    DEFAULT 'new',                -- 'new', 'contacted', 'qualified', 'customer'
    ghl_contact_id          TEXT,
    tx_sos_filing_number    TEXT,                                 -- TX Secretary of State business filing
    tceq_cgp_permit         TEXT,                                 -- TCEQ Construction General Permit (sub indicator)
    notes                   TEXT,
    first_seen              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_contractors_name     ON contractors(normalized_name);
CREATE INDEX IF NOT EXISTS idx_contractors_tier     ON contractors(outreach_tier);
CREATE INDEX IF NOT EXISTS idx_contractors_role     ON contractors(contractor_role);

-- ============================================================================
-- SCRAPE_LOG — Operational history for monitoring & debugging
-- ============================================================================
CREATE TABLE IF NOT EXISTS scrape_log (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    source                  TEXT    NOT NULL,
    run_started_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    run_completed_at        TIMESTAMP,
    records_found           INTEGER DEFAULT 0,
    records_new             INTEGER DEFAULT 0,
    records_updated         INTEGER DEFAULT 0,
    status                  TEXT,                                 -- 'success', 'partial', 'failed'
    error_message           TEXT,
    duration_seconds        INTEGER
);

CREATE INDEX IF NOT EXISTS idx_scrape_log_source    ON scrape_log(source, run_started_at DESC);

-- ============================================================================
-- VIEWS — Pre-computed for the dashboard
-- ============================================================================

-- Hot leads: scored 70+, issued in last 30 days, not yet contacted
CREATE VIEW IF NOT EXISTS v_hot_leads AS
SELECT
    p.id,
    p.source_permit_id,
    p.permit_type,
    p.project_address,
    p.county,
    p.declared_valuation,
    p.lead_score,
    p.tags,
    p.issue_date,
    p.latitude,
    p.longitude,
    c.company_name AS contractor_name,
    c.phone        AS contractor_phone,
    c.email        AS contractor_email,
    c.outreach_tier
FROM permits p
LEFT JOIN contractors c ON c.id = p.contractor_id
WHERE p.lead_score >= 70
  AND p.pipeline_stage = 'hot'
  AND p.issue_date >= DATE('now', '-30 days')
ORDER BY p.lead_score DESC, p.issue_date DESC;

-- Pipeline summary for kanban headers
CREATE VIEW IF NOT EXISTS v_pipeline_summary AS
SELECT
    pipeline_stage,
    COUNT(*)                   AS lead_count,
    SUM(declared_valuation)    AS total_pipeline_value,
    AVG(lead_score)            AS avg_score
FROM permits
WHERE issue_date >= DATE('now', '-90 days')
GROUP BY pipeline_stage;
