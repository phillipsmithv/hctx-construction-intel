# HCTX Construction Intel

**Lead generation pipeline for Houston-area construction projects** — built on the same proven architecture as [hctx-intel](https://github.com/phillipsmithv/hctx-intel) (real estate motivated sellers).

Scrapes public construction permits, scores them against your business priorities (dirt hauling, excavation, grading, detention basins, $250K+ commercial), and pipes hot leads into Go High Level for Jarvis AI outreach.

---

## What This Does

- **Daily scrape** of Harris County permits at 7 UTC (2 AM Houston) via GitHub Actions
- **Lead scoring** (0–100) tuned to your services: excavation, grading, foundation, detention basins
- **Three dashboard views** on GitHub Pages: Kanban board, Map view, Table view
- **GHL CSV export** for Jarvis AI bulk outreach campaigns
- **5-county service area**: Harris, Fort Bend, Montgomery, Brazoria, Galveston
- **$250K+ minimum valuation** filter (skips kitchen remodels)
- **Three outreach tiers**: GCs from permits (T2), site subs from past awards (T1), developers (T3)

**Cost: $0/month.** Same stack as HCTX-Intel — GitHub Actions free tier, SQLite committed to repo, GitHub Pages, Census Geocoder (free).

---

## Repository Structure

```
hctx-construction-intel/
├── .github/workflows/       # GitHub Actions cron jobs
├── scrapers/                # Per-source Playwright scrapers
│   ├── permits/             # Phase 1: city/county building permits
│   ├── bids/                # Phase 2: TxDOT, county purchasing bids
│   ├── awards/              # Phase 3: Commissioners Court PDFs
│   └── cip/                 # Phase 4: HCFCD, ISD bond programs
├── etl/                     # Geocoding, scoring, normalization
├── exports/                 # GHL CSV exports
├── dashboard/               # Kanban + Map + Table views (deployed to Pages)
├── db/                      # SQLite + schema
├── config/                  # Tunable scoring weights & service area
└── docs/                    # Data sources, scoring algorithm, runbook
```

---

## Setup — First Time (≈ 30 minutes)

### 1. Create the GitHub repo

```bash
# In GitHub UI: create new repo named hctx-construction-intel (public is fine)
# Then locally:

cd ~/projects   # or wherever you keep your code
git clone https://github.com/phillipsmithv/hctx-construction-intel.git
cd hctx-construction-intel
```

### 2. Copy these files into the repo

Drop everything from this build into the repo root.

### 3. Initialize the local environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 4. Initialize the SQLite database

```bash
mkdir -p db
sqlite3 db/construction_intel.db < db/schema.sql
echo "Database initialized."
```

### 5. Test the scraper locally

```bash
python -m scrapers.permits.harris_county_unincorp
```

Expected output: log messages showing search dates, pages scraped, records found.

> **First-run note:** The Harris County portal selectors in `scrapers/permits/harris_county_unincorp.py` are placeholders that match the most common DOM patterns for ASP.NET permit portals. On the first live run, expect to spend 15–30 min in the browser inspector matching the actual selectors. The base scraper logs everything to `scrape_log` so failures are clean and recoverable. See `docs/DATA_SOURCES.md` for verification steps.

### 6. Score and export

```bash
python -m etl.score
python -m exports.ghl_export
ls -la exports/csv_outputs/
```

### 7. Push to GitHub

```bash
git add .
git commit -m "Initial Construction Intel build"
git push origin main
```

### 8. Enable GitHub Pages

GitHub repo → **Settings → Pages → Source: GitHub Actions**. The deploy workflow fires on the next push or DB update; dashboard available at `https://phillipsmithv.github.io/hctx-construction-intel/`.

### 9. Get a free Mapbox token (for the map view)

1. Go to [mapbox.com](https://mapbox.com) → sign up (no credit card)
2. Account → Tokens → copy the default public token (starts with `pk.`)
3. Open the dashboard, switch to Map view, paste the token in the prompt
4. Stored in browser localStorage — no need to commit it

### 10. Verify the cron is running

GitHub repo → **Actions** tab → "Scrape Construction Permits Daily" → click "Run workflow" to trigger manually first time. After it succeeds, the daily cron is live.

---

## Daily Workflow Once Running

1. **7 UTC daily**: GitHub Actions runs the scraper, geocodes new permits, scores everything, exports a fresh GHL CSV, commits the updated DB
2. **Dashboard auto-deploys**: Within 2 minutes of the DB commit, GitHub Pages rebuilds
3. **Morning routine**: Open dashboard → Kanban view → review the **Hot** column → drag promising leads to **Contacted** as you fire Jarvis at them
4. **GHL bulk import**: Grab the latest `exports/csv_outputs/ghl_hot_leads_*.csv` from the repo, import into GHL, Jarvis runs the SMS/voicemail campaign
5. **Driving for dollars**: Switch to Map view → filter by neighborhood → tap a pin → "Get Directions" → physical site visit

---

## Stage Sync Note

The Kanban drag-and-drop currently updates stage **in-browser only** — the SQLite file in the repo doesn't get the change because GitHub Pages is read-only. For now: track stage changes in GHL (the source of truth for outreach status). The dashboard Kanban view is a daily snapshot, not a live editor.

To make stages persistent, the next iteration adds a small Cloudflare Worker (free tier) that accepts stage updates and commits them back via the GitHub API. Slated for week 3 of the build.

---

## Roadmap

| Phase | Status | What it adds |
|-------|--------|--------------|
| **1** Harris County permits | ✅ Built | Daily active permit scrape, MVP scope |
| **1.1** City of Houston ePermits | ⏳ Next | Bigger market, separate scraper module |
| **1.2** Suburbs (Pearland, Sugar Land, Katy, Pasadena, Baytown, Conroe) | ⏳ Next | Modular drop-in scrapers per city |
| **2** TxDOT + County Purchasing bids | 📋 Planned | 30–90 day forward signal |
| **3** Commissioners Court awards (PDF) | 📋 Planned | Tier 1 sub discovery |
| **4** CIP / bond programs (HCFCD, school districts) | 📋 Planned | Long-horizon pipeline |
| **+** TCEQ CGP scraper | 📋 Planned | Direct Tier 1 sub list |
| **+** SMS daily digest via Twilio | 📋 Planned | Top 5 leads to your phone, 7 AM |
| **+** Stage persistence via CF Worker | 📋 Planned | Make Kanban drag persistent |

---

## Anti-Bot & Legal

- **Public records only** — building permits are open records under the Texas Public Information Act
- **robots.txt respected** in `scrapers/base.py`
- **3-second rate limit** between requests, off-hours scraping (2 AM Houston time)
- **Realistic User-Agent** rotation, no headless detection bypasses beyond standard Playwright defaults
- **No private/login-protected scraping** — if a source requires auth, we don't touch it (ruled out CivCast for this reason)

---

## Maintenance

- **When a portal changes its DOM**: scrape_log will show failures. Fix the selectors in the relevant `scrapers/permits/*.py` file. The base class isolates breakage to one source — others keep running.
- **Weekly review**: check `scrape_log` for sources with `status = 'failed'` more than 2 days running
- **Tuning scoring**: edit `config/scoring_weights.yaml` and run `python -m etl.score` to rescore everything against new weights — no scraper re-run needed

---

## Built For

Phillip Villalobos — dirt, trucking, excavation, and construction materials, Greater Houston (5-county service area). Companion project to [hctx-intel](https://github.com/phillipsmithv/hctx-intel) (real estate motivated sellers). Both repos share the same architecture so maintenance is one mental model, two domains.
