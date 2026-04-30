"""
enrich_listing_detail.py — Enrich active listings missing transmission data using the
free NHTSA VIN decode API (vpic.nhtsa.dot.gov). No proxy needed.

Processes all sources with VINs and missing transmission:
  - AutoTrader: 713 listings (0% tx coverage)
  - DuPont Registry: 137
  - cars.com: 80
  - eBay Motors: 48

NHTSA API: free, no key, 50 req/batch recommended, ~0.5s per VIN.
Estimated runtime for 978 VINs: ~15 minutes.

Run:
  python3 enrich_listing_detail.py              # enrich all missing-tx listings
  python3 enrich_listing_detail.py --dry-run    # print without writing
  python3 enrich_listing_detail.py --limit 100  # process N listings
  python3 enrich_listing_detail.py --source "AutoTrader"  # one source only
"""

import argparse
import json
import logging
import sqlite3
import time
import urllib.request
import urllib.error
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent / "data" / "inventory.db"

NHTSA_BASE = "https://vpic.nhtsa.dot.gov/api/vehicles/decodevin/{vin}?format=json"
SLEEP_BETWEEN = 0.4   # seconds between NHTSA requests (polite rate limit)
BATCH_SIZE = 50
SLEEP_BATCH = 5.0     # seconds between batches


# ── NHTSA fetch ───────────────────────────────────────────────────────────────

def decode_vin_nhtsa(vin: str) -> dict:
    """
    Call NHTSA VIN decode API. Returns dict with useful fields.
    Returns empty dict on failure.
    """
    url = NHTSA_BASE.format(vin=vin)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "RennMarkt/1.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, Exception) as e:
        log.debug("NHTSA error for %s: %s", vin, e)
        return {}

    results = {r["Variable"]: r["Value"] for r in data.get("Results", [])
               if r.get("Value") and r["Value"] not in ("null", "None", "Not Applicable", "")}

    if results.get("Error Code", "0") not in ("0", "1"):
        log.debug("NHTSA decode error for %s: %s", vin, results.get("Error Text"))

    # Extract and normalize the fields we care about
    out = {}

    # Transmission
    tx_style = results.get("Transmission Style", "")
    tx_speeds = results.get("Transmission Speeds", "")
    if tx_style:
        ts = tx_style.lower()
        if "manual" in ts:
            out["transmission"] = "Manual"
        elif "automatic" in ts or "dual" in ts or "cvt" in ts:
            # Map speed count to PDK for 7-speed Porsche (PDK is always 7-speed)
            if tx_speeds == "7":
                out["transmission"] = "PDK"
            else:
                out["transmission"] = "Automatic"
        else:
            out["transmission"] = tx_style.strip()[:50]

    # Drive type
    drive = results.get("Drive Type", "")
    if drive:
        d = drive.lower()
        if "rear" in d:
            out["drive_type"] = "RWD"
        elif "all" in d or "awd" in d or "4wd" in d or "4x4" in d:
            out["drive_type"] = "AWD"
        else:
            out["drive_type"] = drive.strip()[:20]

    # Body class
    body = results.get("Body Class", "")
    if body:
        b = body.strip()
        # Normalize to our standard values
        if "cabriolet" in b.lower() or "convertible" in b.lower():
            out["body_style"] = "Cabriolet"
        elif "targa" in b.lower():
            out["body_style"] = "Targa"
        elif "coupe" in b.lower() or "hatchback" in b.lower():
            out["body_style"] = "Coupe"
        else:
            out["body_style"] = b[:40]

    return out


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_listings_to_enrich(conn: sqlite3.Connection, limit: int, source: str = None) -> list:
    c = conn.cursor()
    source_filter = "AND dealer = ?" if source else ""
    params = [limit] if not source else [source, limit]

    # Prioritize: no transmission AND has full 17-char VIN
    query = f"""
        SELECT id, dealer, listing_url, year, model, trim, vin, transmission, drive_type, body_style
        FROM listings
        WHERE status = 'active'
          AND (transmission IS NULL OR transmission = '')
          AND vin IS NOT NULL AND vin != '' AND length(vin) = 17
          {source_filter}
        ORDER BY
          CASE dealer
            WHEN 'AutoTrader' THEN 1
            WHEN 'DuPont Registry' THEN 2
            WHEN 'cars.com' THEN 3
            WHEN 'eBay Motors' THEN 4
            ELSE 5
          END,
          date_last_seen DESC
        LIMIT ?
    """
    if source:
        c.execute(query, [source, limit])
    else:
        c.execute(query, [limit])

    cols = [d[0] for d in c.description]
    return [dict(zip(cols, row)) for row in c.fetchall()]


def write_enrichment(conn: sqlite3.Connection, listing_id: int, data: dict, dry_run: bool = False) -> bool:
    """Write enrichment data. Only update fields that are currently NULL/empty."""
    if not data:
        return False

    # Build SET clause — only update fields not already present
    updates = {k: v for k, v in data.items() if v is not None}
    if not updates:
        return False

    if dry_run:
        log.info("  [DRY RUN] id=%d: %s", listing_id, updates)
        return True

    # Only write to columns that are NULL/empty in DB (don't overwrite existing data)
    set_clauses = []
    values = []
    for col, val in updates.items():
        set_clauses.append(f"{col} = COALESCE(NULLIF({col}, ''), ?)")
        values.append(val)

    values.append(listing_id)
    conn.execute(
        f"UPDATE listings SET {', '.join(set_clauses)} WHERE id = ?",
        values
    )
    conn.commit()
    return True


# ── Main ──────────────────────────────────────────────────────────────────────

def print_coverage(conn: sqlite3.Connection):
    c = conn.cursor()
    c.execute("""
        SELECT dealer,
               COUNT(*) as total,
               SUM(CASE WHEN transmission IS NOT NULL AND transmission != '' THEN 1 ELSE 0 END) as has_tx
        FROM listings WHERE status='active'
        GROUP BY dealer ORDER BY total DESC
    """)
    print("\nTransmission coverage after enrichment:")
    print(f"{'Source':<25} {'Total':>7} {'Has TX':>7} {'%':>5}")
    print("-" * 45)
    for dealer, total, has_tx in c.fetchall():
        pct = 100 * has_tx // total if total else 0
        print(f"{dealer:<25} {total:>7} {has_tx:>7} {pct:>4}%")


def main():
    parser = argparse.ArgumentParser(description="Enrich listings with NHTSA VIN data")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=2000, help="Max listings to process")
    parser.add_argument("--source", type=str, default=None, help="Filter to one source (e.g. 'AutoTrader')")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    listings = get_listings_to_enrich(conn, args.limit, args.source)
    log.info("Found %d listings with VINs missing transmission data", len(listings))

    if not listings:
        log.info("Nothing to enrich.")
        print_coverage(conn)
        return

    enriched = 0
    failed   = 0
    no_data  = 0

    for i, listing in enumerate(listings):
        vin = listing["vin"]
        log.info("[%d/%d] %s | %d %s %s — VIN %s",
                 i+1, len(listings), listing["dealer"],
                 listing["year"], listing["model"], listing["trim"] or "", vin[:11])

        data = decode_vin_nhtsa(vin)

        if not data:
            log.debug("  – no useful data from NHTSA")
            no_data += 1
        else:
            parts = []
            if data.get("transmission"): parts.append(f"tx={data['transmission']}")
            if data.get("drive_type"):   parts.append(f"drive={data['drive_type']}")
            if data.get("body_style"):   parts.append(f"body={data['body_style']}")
            log.info("  ✓ %s", " | ".join(parts) if parts else "no new fields")

            if write_enrichment(conn, listing["id"], data, args.dry_run):
                enriched += 1
            else:
                no_data += 1

        # Polite pacing
        if (i + 1) % BATCH_SIZE == 0:
            log.info("--- Batch %d done. Sleeping %ds ---", (i+1)//BATCH_SIZE, int(SLEEP_BATCH))
            time.sleep(SLEEP_BATCH)
        else:
            time.sleep(SLEEP_BETWEEN)

    conn.close()
    log.info("=" * 50)
    log.info("Done. enriched=%d | no_data=%d | failed=%d | total=%d",
             enriched, no_data, failed, len(listings))

    if not args.dry_run:
        conn2 = sqlite3.connect(DB_PATH)
        print_coverage(conn2)
        conn2.close()


if __name__ == "__main__":
    main()
