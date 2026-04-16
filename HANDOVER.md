# Vehicle Market Analyzer — Project Handover Summary
*Last updated: April 16, 2026 (evening — alerts hardened, notifications stabilised)*

---

## 1. Project Overview & Goals

A Porsche-focused market intelligence platform running autonomously on a Mac Mini M4. Scrapes 9 active sources (ALL LOCAL — Distill cancelled April 15), tracks price history, scores every listing against FMV using 6,004 BaT sold comps, and sends iMessage alerts the moment a new listing hits the DB. Long-term goal: become the most informed buyer in the air-cooled, water-cooled, and GT Porsche market.

### Business Context
Owner operates a small, focused performance car dealership. All purchases are investments — short-term flips or long-term holds. Core price range: $70K–$150K. GT/collector cars have no ceiling.

---

## 2. Target Vehicles

### Tier 1 — GT / Collector (alert immediately)
- 911: GT3, GT3 RS, GT2, GT2 RS, R, Speedster, Sport Classic, Touring (996/997/991/992)
- 911: All air-cooled — 930, 964, 993 (pre-1998)
- Cayman: GT4, GT4 RS, Spyder, R (987/981/718)
- Boxster: Spyder (987/981/718)
- Any Turbo S variant
- 356, 914-6

### Tier 2 — Standard (alert only at DEAL — 10%+ below FMV)
- 911: Carrera, S, 4S, GTS, Targa (996/997/991/992)
- Cayman: S, GTS (987/981/718)
- Boxster: Base, S, GTS (987/981/718)

### Never
- Cayenne, Panamera, Macan, Taycan — excluded at scrape level
- Salvage, rebuilt, flood, frame damage
- Year: 1986–2024 | Mileage: <100k | Price: <$5,000 (non-auction)
- **⚠️ HARD RULE — YEAR_MAX=2024:** Do not change this to 2025 or 2026 under any
  circumstances. Applies to scraper.py and ALL scrapers. Owner decision required before
  any year ceiling change. Locked until Jan 1, 2027 at the earliest.

---

## 3. System Architecture

### Infrastructure
- **Machine:** Mac Mini M4, 24/7, user: claw
- **Scrape schedule:** Every 12 minutes flat (launchd `StartInterval=720`)
- **Dashboard push:** Every 2 minutes (launchd `StartInterval=120`)
- **Alert delivery:** iMessage via `notify_imessage.py` → Messages.app → iPhone

### Key Files
```
~/porsche-tracker/
├── scraper.py              # BaT, PCA Mart, pcarmarket scrapers + DEALERS list
├── scraper_autotrader.py   # AutoTrader Playwright (mobile site) ✅ LIVE
├── scraper_carscom.py      # Cars.com curl_cffi — per-model slug, VIN-stop ✅ LIVE
├── scraper_ebay.py         # eBay Browse API (OAuth2) ✅ LIVE
├── scraper_rennlist.py     # Rennlist curl_cffi Chrome impersonation ✅ LIVE
├── scraper_cnb.py          # Cars & Bids Playwright ✅ LIVE
├── scraper_bfb.py          # Built for Backroads Playwright ✅ LIVE
├── db.py                   # DB layer, tier classification, upsert logic
├── main.py                 # Entry point — scrape + snapshot + dashboards + alerts
├── fmv.py                  # FMV engine — weighted median, generation bucketing
├── notify_imessage.py      # iMessage alerts — LIVE ✅
├── new_dashboard.py        # Primary dashboard → docs/index.html (GitHub Pages)
├── git_push_dashboard.sh   # Auto-pushes docs/ to GitHub Pages every 2 min
├── run_daily.sh            # Launched by launchd every 12 min
├── live_feed.py            # Live feed → docs/live_feed.html
├── comp_scraper.py         # Ongoing BaT sold comp scraping (daily auto-run)
├── enrich_bat_vins.py      # BaT VIN/mileage enricher (run overnight)
├── enrich_ebay_mileage.py  # eBay per-item mileage enricher (run on-demand)
├── decode_vin_generation.py # VIN → generation decoder (resumable, run on-demand)
├── archive_capture.py      # HTML + screenshot archive every 10 min (useful, keep)
└── data/
    ├── inventory.db              # SQLite — listings, price_history, sold_comps
    ├── imessage_config.json      # {"recipient": "6108361111"} ✅
    ├── seen_alerts_imessage.json # Dedup for iMessage alerts
    ├── proxy_config.json         # DataImpulse (gw.dataimpulse.com:823)
    └── autotrader_state.json     # {"bootstrapped": true}
```

### launchd Jobs
| Label | Script | Interval | Status |
|---|---|---|---|
| com.porschetracker.scrape | run_daily.sh | 720s (12 min) | ✅ Running |
| com.porschetracker.gitpush | git_push_dashboard.sh | 120s (2 min) | ✅ Running |
| com.porschetracker.archive-capture | archive_capture.py | 600s (10 min) | ✅ Running |

Note: All Distill launchd jobs (distill-poller, distill-watcher, distill-receiver) are
**cancelled** as of April 15, 2026. Zero cloud dependency.

---

## 4. Active Data Sources

| Source | Method | Status | Listings | Images |
|---|---|---|---|---|
| cars.com | `scraper_carscom.py` curl_cffi | ✅ Working | ~733 | ❌ No |
| eBay Motors | `scraper_ebay.py` Browse API | ✅ Working | ~82 | ✅ Yes |
| PCA Mart | `scraper.py` Playwright cookie-auth | ✅ Working | ~55 | ✅ CDN URL |
| Bring a Trailer | `scraper.py` Playwright | ✅ Working | ~40 | ✅ Yes |
| Cars & Bids | `scraper_cnb.py` Playwright | ✅ Working | ~12 | ✅ Yes |
| Built for Backroads | `scraper_bfb.py` Playwright | ✅ Working | ~10 | ✅ Yes |
| AutoTrader | `scraper_autotrader.py` Playwright | ⚠️ Intermittent | ~10 | Via link |
| pcarmarket | `scraper.py` Playwright | ✅ Working | ~8 | ✅ Yes |
| Rennlist | `scraper_rennlist.py` curl_cffi | ✅ Working | ~6 | ✅ Yes |

**Total active: ~956 listings across 9 sources**

### Source Notes
- **cars.com:** Per-model slug approach (911/boxster/cayman/718_boxster/718_cayman). Direct
  curl_cffi, no proxy (proxy made CF blocking worse). Incremental mode: VIN-based stop +
  3-page cap per slug.
- **PCA Mart:** Images now store both local `/static/img_cache/` path (for dashboard) and
  original CDN URL in `image_url_cdn` column (for iMessage thumbnails).
- **AutoTrader:** Zeros out ~50% of cycles (Akamai mobile site block). Known issue.
- **Rennlist:** Fixed April 16 with curl_cffi Chrome impersonation (was 403 Playwright block).

### Proxy
DataImpulse rotating residential (`gw.dataimpulse.com:823`).
- Username: 7dffcde9c33e2eab45cb
- Password: 068a3aeba25658b5
- Balance: ~$50 topped up April 1 (~16 months runway)
- **Policy: mandatory on AutoTrader only** — cars.com works better without proxy

---

## 5. Database

| Table | Count | Notes |
|---|---|---|
| listings (active) | ~956 | 9 sources |
| listings (sold/archived) | ~1,800+ | Historical |
| sold_comps | 6,004 | BaT primary source — current through April 15 |
| bat_reserve_not_met | 1,784 | Price floor signal |
| hagerty_valuations | 22 | Good condition only |

### Key Columns (listings table)
- `auction_ends_at` — ISO UTC end time for BaT and C&B auctions
- `image_url` — local `/static/img_cache/HASH.jpg` for dashboard rendering
- `image_url_cdn` — original CDN URL (PCA Mart); used for iMessage thumbnails

---

## 6. FMV Engine

`fmv.py` — wired into dashboards and alerts every cycle.
- Source: BaT sold comps (weight 1.0)
- Groups by: generation + trim family
- Recency decay: full weight ≤6 months, decays to 0.3 at 24 months
- Outputs: weighted median, price_low/high, RNM floor, confidence, comp count
- Confidence breakdown: 78% HIGH, 22% MEDIUM, <1% LOW

### VIN Generation Decoder
`decode_vin_generation.py` — decodes VIN position 10 → model year → generation.
- Resumable: skips rows where generation is already set
- Run on-demand after bulk comp imports
- Last run: April 16, 2026 — 4,006 decoded, 1,314 unknown (no VIN or unrecognized)
- NULL generation: ~15% (933/6,004) — expected for pre-VIN-standard and non-standard VINs

---

## 7. Alert System — LIVE ✅

**File:** `notify_imessage.py`
**Recipient:** 6108361111

### Three-layer alert system (order each cycle):
1. **`notify_new_listings(conn, new_ids)`** — fires for EVERY new listing the moment it hits DB. No FMV required. Format:
```
🆕 NEW: 2019 Porsche 911 GT3 RS
💰 $289,000
🛣️  8,400 mi
📍 Bring a Trailer [AUCTION]  [GT/Collector]
🔗 https://bringatrailer.com/listing/...
```

2. **`notify_price_drops(conn)`** — fires when any active listing drops price ≥$500 in last 90 min. Format:
```
📉 PRICE DROP: 2022 Porsche 911 GT3
💰 $229,900 (was $249,900, -8%)
🛣️  12,000 mi
📍 AutoTrader  [GT/Collector]
🔗 https://...
```

3. **`notify_imessage.main()`** — deal/watch scoring alerts. Format:
```
🔥 DEAL: 2022 Porsche 911 GT3
💰 $239,900  -15% vs FMV ($282,000)
🛣️  12,000 mi
📍 AutoTrader [RETAIL]  [GT/Collector]
🔗 https://...
```

**Thresholds:**
- Tier 1: alert on DEAL (10%+ below) OR WATCH (5–10% below)
- Tier 2: alert only on DEAL (10%+ below)
- Price floor: listings under $20,000 skipped (auction bids / salvage)
- Price drop minimum: $500
- Confidence gate: NONE confidence skipped
- Dedup: `seen_alerts_imessage.json` — new-listing key `"new:{url}"`, deal key `"{url}"`, drop key `"drop:{id}:{price}"`
- Images: PCA Mart uses `image_url_cdn` (CDN URL); all others use `image_url` directly

---

## 8. Dashboard — GitHub Pages ✅

URL: https://ocx11.github.io/PTOX11/
GitHub repo: https://github.com/OCX11/PTOX11
- Auto-regenerated every scrape cycle by `new_dashboard.py` → `docs/index.html`
- Auto-pushed to GitHub every 2 minutes by `git_push_dashboard.sh`
- Filters: Generation, Model, Year, Price, Source, Deals only, GT/Collector only
- No pre-checked filters on load ✅
- Listing age shows accurate timestamps (uses `created_at`, not `date_first_seen`) ✅
- All report links working ✅
- Auction countdown timers live (BaT + C&B) — JS updates every 1 second
- Searchable listing history: `docs/search.html` — 2,747+ listings, VIN/model/trim/source/price/miles/status
- PWA installed on iPhone via Safari (manifest.json + sw.js)

---

## 9. Open Issues & Next Steps

### 🔴 Fix Now
1. **AutoTrader zeros ~50% of runs** — Akamai block on mobile URL. Fix in AutoTrader chat.

### 🟡 Short Term
2. **FMV accuracy audit** — some cars way off. Likely generation bucketing edge cases.
3. **eBay sold comps** — eBay Finding API gives sold listings. Gold for air-cooled FMV.
4. **PWA / offline support** — service worker currently cache-first. Consider network-first for live data.

### 🟢 Medium Term
5. **Price trend prediction** — velocity signals, seasonality, buy/sell score (needs 30+ days data)

---

## 10. Known Issues

| Issue | Severity | Status |
|---|---|---|
| AutoTrader ~50% zero cycles | Medium | Known — Akamai mobile block |
| sold_comps NULL generation (15%) | Low | No VIN or pre-standard VINs — expected |

---

## 11. Session Log

### March 26–30, 2026
- BaT backfill: 5,652 comps | eBay Browse API activated | DataImpulse proxy activated
- FMV pipeline wired | iMessage alerts live — 98 alerts first run

### April 1, 2026
- `scraper_autotrader.py` built (mobile site, bootstrap complete)
- DataImpulse topped up $50

### April 2, 2026
- `scraper_carscom.py` built (curl_cffi, 61 listings, 100% images)
- `scraper_ebay.py` built (Browse API, OAuth2, 81 listings)
- `enrich_ebay_mileage.py` built

### April 4, 2026
- `scraper_rennlist.py` built — Rennlist migrated off Distill
- Distill now only serves Built for Backroads

### April 8, 2026
- iMessage new-listing alerts wired (`notify_new_listings`)
- Dashboard live feed filter removed
- All dashboard links fixed (live_feed path, GitHub Pages)
- `.gitignore` hardened (data/, secrets, img_cache excluded)
- Scheduler fixed: 1800s → 720s (30 min → 12 min)
- `enrich_rennlist.py` removed from run loop
- `git_push_dashboard.sh` created — GitHub Pages auto-updates every 2 min
- Listing age display fixed (created_at vs date_first_seen)
- Independent dealers disabled from DEALERS list
- iMessage alert wiring restored in main.py after git restore wipe
- pcarmarket prices extracted via `span.pcar-auction-info__price` selector
- Comp mileage fix — extracts mileage first, then strips prefix

### April 9, 2026 — Post-Audit
- `notify_gunther.py` removed from `run_daily.sh` (Telegram dead)
- Alert price floor added: listings <$20k skipped
- `Cars.com` duplicate archived — all normalized to `cars.com`
- HANDOVER.md rewritten to reflect actual system state

### April 15, 2026 — Full Build Session
- `scraper_cnb.py` built — Cars & Bids Playwright, 12 listings, 100% images
- `scraper_bfb.py` built — Built for Backroads Playwright, kills last Distill dependency
- **Distill subscription cancelled** — ALL 9 sources on local scrapers
- FMV audit — NONE confidence 14→0, HIGH 134→145, trim fallback logic fixed
- PWA installed — manifest.json, sw.js, icons; user installed as iPhone app via Safari
- `archive_capture` confirmed useful: HTML + screenshot every 10 min → archive/
- iMessage alerts confirmed for all 9 sources; images sending for all HTTP image_url listings
- 231 active listings across 9 sources, 5,770 sold comps


### April 16, 2026 — Evening: Alerts hardened, notifications stabilised
- **cars.com bootstrap caused notification spam** — 700+ listings inserted in one day, each with multiple price_history records from same scrape session, caused false price-drop alerts (305-608 per cycle)
- **notify_price_drops() REMOVED** — feature deleted entirely from notify_imessage.py and main.py. Price-drop data still accumulates silently in price_history table. Future: show as dashboard badge, not push notification. See Apple Note: "Price Drops — Future Feature Design"
- **Deal/watch iMessage alerts DISABLED** — notify_imessage.main() commented out in main.py. Will re-enable once bootstrap noise settles and we're ready to tune thresholds. New-listing alerts remain ACTIVE.
- **Dashboard sort fixed** — was sorting by created_at (stale for eBay listings from March). Now sorts by date_last_seen (updated every cycle). eBay listings now appear fresh.
- **Alert dedup cleaned** — removed 609 bad drop: keys from seen_alerts_imessage.json

### Current alert state (April 16 evening)
- ✅ New listing alerts: ACTIVE (every new VIN entering DB fires one iMessage)
- ❌ Deal/watch alerts: DISABLED (notify_imessage.main() commented out)
- ❌ Price drop alerts: REMOVED (deleted, not just disabled)

### April 16, 2026 — cars.com scraper fix (3 → 839 listings)
- Root cause: broad URL with models[]= empty returned all Porsche models (85% Macan/Cayenne/Panamera)
- Bootstrap state stuck at true — kept scraper on 1-page incremental mode forever
- Per-model slug approach: query 911/boxster/cayman/718_boxster/718_cayman separately
- Direct curl_cffi (no proxy) works better for cars.com
- `_is_blocked` false-positive fixed — was flagging large valid pages
- Result: cars.com 2 → 839 active listings, system total ~956 across 9 sources
- Incremental mode: VIN-based stop + 3-page cap per slug (commit cc11c56a7)

### April 16, 2026 — Auction Countdown Timer
- `auction_ends_at` column added to listings table (TEXT, ISO UTC)
- BaT reads `data-timestamp_end` Unix epoch; C&B parses `span.ticking` countdown
- Dashboard JS `updateCountdowns()` fires every 1s, shows red "Ended" when expired
- 39/48 active auctions carry end time (commit fe5d7ee57)

### April 16, 2026 — Comp Scraper Overhaul + Search UI
- BaT comp scraper rebuilt — JSON API + nonce auth (50x faster than Playwright)
- Sales vs RNM correctly separated — "Sold for $X" vs "Bid to $X"
- Year filter 1986→1950 — air-cooled 911s now captured in comps
- Gap filled: 5,789→6,004 comps, March 25→April 15 fully recovered
- Searchable listing history built — docs/search.html, 2,747 listings
- GitHub repo renamed: porsche-tracker → PTOX11
- Rennlist fixed: curl_cffi Chrome impersonation replaces broken Playwright

### April 16, 2026 — CDN Images, Generation Fill, Price Drop Alerts
- **PCA Mart CDN URL** — `image_url_cdn` column added to listings table; scraper stores
  original CDN URL before overwriting `image_url` with local cache path; iMessage and fmv.py
  updated to prefer `image_url_cdn` for PCA Mart thumbnails (commit e2a53cfae)
- **sold_comps generation fill** — ran `decode_vin_generation.py`; 4,006/5,320 VINs decoded,
  1,314 unknown; NULL generation reduced from 1,408 to 933 (15% of 6,004)
  Fixed Python 3.9 compatibility (pipe union `int | None` → bare annotation) (commit 312ff7688)
- **Price drop alerts** — `notify_price_drops(conn)` added to `notify_imessage.py`; fires
  when listing drops ≥$500 in last 90 min; dedup key `"drop:{id}:{price}"`;
  wired into main.py after notify_new_listings (commit 6318bac50)
