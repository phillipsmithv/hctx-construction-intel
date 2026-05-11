# Data Sources — URLs, Verification Steps, ToS Notes

This file is the source-of-truth for every government portal we scrape. When something breaks, start here.

---

## Phase 1 — Active Permits

### Harris County Unincorporated (MVP)
- **Portal**: Harris County Engineering Department permits
- **Likely URL**: `https://www.eng.hctx.net/Permits` (verify before first run)
- **Backup search**: Google `site:hctx.net permits search`
- **Records**: Excavation, grading, foundation, utility, demolition permits in unincorporated Harris County
- **ToS**: Public records under Texas Public Information Act, no scraping prohibition observed
- **Update cadence**: Permits typically posted within 1-3 days of issuance
- **Selector verification (do this on first run)**:
  ```bash
  # Open the portal in a real browser, hit F12, find the search form
  # Note the actual selectors for: start date input, end date input, submit button, results table rows
  # Update scrapers/permits/harris_county_unincorp.py if they differ from placeholders
  ```

### City of Houston ePermits (Phase 1.1)
- **Portal**: `https://epermits.houstontx.gov/`
- **Notes**: ASP.NET WebForms-based. Heavier JavaScript, expect Playwright to handle it but slower than HC.
- **Records**: All permits inside Houston city limits (the bigger market by far)

### Suburban cities (Phase 1.2)
| City | Portal | Notes |
|------|--------|-------|
| Pearland | `pearlandtx.gov` → permits | Smaller volume, simpler portal |
| Sugar Land | `sugarlandtx.gov` → permits | Tyler EnerGov platform (common) |
| Katy | `cityofkaty.com` | Lower volume, residential-heavy |
| Pasadena | `pasadenatx.gov` | Industrial corridor, good for utility work |
| Baytown | `baytown.org` | Petrochem-adjacent, oilfield-ish |
| Conroe | `cityofconroe.org` | Montgomery County, fastest growing |

---

## Phase 2 — Bids & RFPs

### TxDOT Construction Letting
- **URL**: `https://www.txdot.gov/business/letting-bids.html`
- **Notes**: Highway, bridge, drainage projects. Massive earthwork volume on highway expansion.
- **Cadence**: Monthly letting calendar

### Harris County Purchasing
- **URL**: `https://purchasing.harriscountytx.gov/`
- **Notes**: County construction bids, often drainage and infrastructure (HCFCD-adjacent)

### City of Houston Strategic Procurement
- **URL**: `https://purchasing.houstontx.gov/`
- **Notes**: Public works, parks, infrastructure bids

---

## Phase 3 — Contract Awards (PDF parsing)

### Harris County Commissioners Court
- **URL**: `https://www.harriscountytx.gov/Government/Commissioners-Court` → Agendas
- **Format**: Posted PDFs with weekly agenda items including contract awards
- **Parser**: pdfplumber (text-based PDFs) → regex for "AWARD" / "CONTRACT" sections

### Houston City Council Agendas
- **URL**: `https://houstontx.gov/citysec/agenda.html`
- **Format**: PDF agendas, weekly

---

## Phase 4 — CIP & Bond Programs (long-horizon)

### Harris County Flood Control District (HCFCD)
- **URL**: `https://www.hcfcd.org/Activity` → Projects map
- **Records**: Flood mitigation projects, detention basins, channel work — your highest-margin niche
- **Format**: Interactive map + project pages, possibly with PDFs for major projects

### City of Houston Public Works
- **URL**: `https://www.houstonpublicworks.org/`
- **Records**: CIP, drainage, paving programs

### School Districts (CIP / bond)
- **HISD**: `houstonisd.org/bond`
- **Cy-Fair ISD**: `cfisd.net/bond`
- **Klein ISD**: `kleinisd.net/bond`
- **Katy ISD**: `katyisd.org/bond`
- **Notes**: Bond programs publish project lists with budget, schedule, location. New school construction = massive earthwork.

---

## TCEQ Construction General Permit (Tier 1 sub discovery)

- **URL**: `https://www.tceq.texas.gov/permitting/stormwater/wq_construction.html`
- **Records**: Operators required to file CGPs for sites disturbing 1+ acre. Active CGPs = active site subs.
- **Why it matters**: Most permits don't list the site sub, but the site sub IS the CGP filer. Cross-reference CGP filings with permits at the same address → identify the actual dirt buyer.

---

## TX Secretary of State Business Filings (contractor enrichment)

- **URL**: `https://www.sos.state.tx.us/corp/sosda/index.shtml`
- **Use**: Enrich contractor company names → registered agent + officers + addresses
- **Free**: Public business filing data
- **Limit**: Rate-limit politely (2 sec between requests) — this is a state government portal

---

## Verification Checklist (run this monthly)

For each active source:
1. Open the URL in a real browser
2. Confirm the page still loads and the search/data is still publicly accessible
3. Spot-check one record from this week's scrape against the live portal — do values match?
4. Check `scrape_log` table for the source's recent run history — any pattern of failures?
5. If portal redesigned: update selectors, document the change in this file with date
