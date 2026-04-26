#!/usr/bin/env python3
"""
notify_push.py — Web Push deal alerts for PTOX11.

Drop-in replacement for notify_imessage.py. Sends native iOS push
notifications via the PTOX11 push server (push_server.py on :5055).

Tapping a push notification opens the listing URL directly in Safari.

Delivery: this module → POST /send-push on localhost:5055 → pywebpush →
Apple Push Notification Service (APNs) → iPhone.

Dedup: data/seen_alerts_push.json — same structure as seen_alerts_imessage.json.
"""
import json
import logging
from pathlib import Path
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
LOG_DIR    = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
SEEN_FILE  = SCRIPT_DIR / "data" / "seen_alerts_push.json"

PUSH_SERVER_URL = "http://127.0.0.1:5055"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "push_alerts.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

NOTIFICATIONS_ENABLED = True

sys.path.insert(0, str(SCRIPT_DIR))
import db as database


# ── Dedup store ────────────────────────────────────────────────────────────────

def _load_seen() -> dict:
    if SEEN_FILE.exists():
        try:
            data = json.loads(SEEN_FILE.read_text())
        except Exception:
            return {}
        cutoff = (datetime.now() - timedelta(days=30)).isoformat()
        pruned = {k: v for k, v in data.items()
                  if v.get("alerted_at", "") >= cutoff}
        if len(pruned) < len(data):
            log.info("seen_alerts_push: pruned %d entries older than 30 days",
                     len(data) - len(pruned))
            SEEN_FILE.parent.mkdir(exist_ok=True)
            SEEN_FILE.write_text(json.dumps(pruned, indent=2))
        return pruned
    return {}


def _save_seen(seen: dict):
    SEEN_FILE.parent.mkdir(exist_ok=True)
    SEEN_FILE.write_text(json.dumps(seen, indent=2))


# ── Push delivery ──────────────────────────────────────────────────────────────

def _send_push(payload: dict) -> bool:
    """POST payload to push_server.py /send-push endpoint."""
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{PUSH_SERVER_URL}/send-push",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            sent = result.get("sent", 0)
            if sent > 0:
                log.info("Push delivered to %d subscriber(s)", sent)
                return True
            log.info("Push server: no subscribers yet")
            return False
    except urllib.error.URLError as e:
        log.error("Push server unreachable: %s — is push_server.py running?", e)
        return False
    except Exception as e:
        log.error("Push delivery failed: %s", e)
        return False


# ── Formatting helpers ─────────────────────────────────────────────────────────

_SOURCE_LABELS = {
    "bring a trailer":    "BaT",
    "cars and bids":      "C&B",
    "pcarmarket":         "pcarmarket",
    "pca mart":           "PCA Mart",
    "ebay motors":        "eBay",
    "autotrader":         "AutoTrader",
    "cars.com":           "Cars.com",
    "rennlist":           "Rennlist",
    "built for backroads":"BfB",
    "dupont registry":    "DuPont",
}
_AUCTION_SOURCES = frozenset({"bring a trailer", "cars and bids", "pcarmarket"})


def _clean_url(url: str) -> str:
    if not url:
        return url
    if "ebay.com/itm/" in url:
        import re
        m = re.search(r"(https://www\.ebay\.com/itm/\d+)", url)
        if m:
            return m.group(1)
    return url


def _format_new_listing_push(s: dict) -> dict:
    """Build push payload for a new listing."""
    import re as _re
    year   = s.get("year", "?")
    model  = s.get("model", "") or ""
    trim   = s.get("trim") or ""
    price  = s.get("price")
    mileage = s.get("mileage")
    dealer = s.get("dealer", "?")
    url    = _clean_url(s.get("listing_url", ""))
    tier   = s.get("tier", "TIER2")

    # Strip leading model name from trim
    trim_clean = _re.sub(r"^" + _re.escape(model) + r"\s+", "", trim, flags=_re.I).strip() if trim else ""
    if len(trim_clean) > 40:
        trim_clean = trim_clean[:40].rsplit(" ", 1)[0].strip()

    title_parts = [str(year), "Porsche", model]
    if trim_clean and trim_clean.lower() != model.lower():
        title_parts.append(trim_clean)
    title = " ".join(p for p in title_parts if p)

    src_key   = dealer.lower().strip()
    src_label = _SOURCE_LABELS.get(src_key, dealer)
    is_auction = src_key in _AUCTION_SOURCES
    src_type  = "AUCTION" if is_auction else "RETAIL"
    tier_tag  = " 🔥" if tier == "TIER1" else ""

    price_str  = f"${price:,}" if price else "No Price"
    miles_str  = f"{mileage:,} mi" if mileage else "mileage TBD"

    body = f"{price_str}  ·  {miles_str}  ·  {src_label} {src_type}{tier_tag}"

    return {
        "title": f"🆕 {title}",
        "body": body,
        "url": url,
    }


# ── Public API ─────────────────────────────────────────────────────────────────

def notify_new_listings(conn, new_listing_ids):
    """Send one push per new listing. Called from main.py."""
    if not NOTIFICATIONS_ENABLED:
        log.info("Push notifications disabled — skipping new-listing alerts.")
        return

    if not new_listing_ids:
        return

    placeholders = ",".join("?" * len(new_listing_ids))
    rows = conn.execute(
        f"""SELECT id, year, make, model, trim, price, mileage, dealer,
                   listing_url, source_category, tier, image_url, image_url_cdn
            FROM listings WHERE id IN ({placeholders})""",
        new_listing_ids
    ).fetchall()

    seen = _load_seen()
    sent = 0

    for row in rows:
        s = dict(row)
        url      = s.get("listing_url") or ""
        seen_key = f"new:{url}" if url else f"new:id:{s.get('id')}"

        if seen_key in seen:
            log.debug("Skip push (already sent): %s", seen_key[:80])
            continue

        log.info("NEW LISTING push: %s %s %s  ask=%s",
                 s.get("year"), s.get("model"), s.get("trim") or "",
                 f"${s['price']:,}" if s.get("price") else "no price")

        payload = _format_new_listing_push(s)
        ok = _send_push(payload)

        if ok:
            seen[seen_key] = {
                "alerted_at": datetime.now().isoformat(),
                "alerted": True,
            }
            _save_seen(seen)
            sent += 1

    log.info("New-listing push alerts: %d sent of %d new IDs", sent, len(new_listing_ids))


def notify_auction_ending(conn):
    """Send push alerts for auctions ending soon.

    TIER1: within 3 hours. TIER2: within 1 hour.
    """
    if not NOTIFICATIONS_ENABLED:
        return

    now = datetime.utcnow()
    window_3h = (now + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    window_1h = (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_str   = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    rows = conn.execute("""
        SELECT id, year, make, model, trim, price, mileage, dealer,
               listing_url, source_category, tier, auction_ends_at
        FROM listings
        WHERE status = 'active'
          AND source_category = 'AUCTION'
          AND auction_ends_at IS NOT NULL
          AND auction_ends_at > ?
          AND auction_ends_at <= ?
    """, (now_str, window_3h)).fetchall()

    seen = _load_seen()
    sent = 0

    for row in rows:
        s    = dict(row)
        tier = s.get("tier", "TIER2")
        lid  = s.get("id")
        ends = s.get("auction_ends_at", "")

        if tier != "TIER1" and ends > window_1h:
            continue

        seen_key = f"ending:{lid}"
        if seen_key in seen:
            continue

        try:
            ends_dt = datetime.strptime(ends, "%Y-%m-%dT%H:%M:%SZ")
            delta   = ends_dt - now
            total_s = max(0, int(delta.total_seconds()))
            rem_h   = total_s // 3600
            rem_m   = (total_s % 3600) // 60
        except Exception:
            rem_h = rem_m = 0

        model  = s.get("model", "")
        trim   = s.get("trim") or ""
        price  = s.get("price")
        dealer = s.get("dealer", "?")
        url    = _clean_url(s.get("listing_url") or "")

        src_key   = dealer.lower().strip()
        src_label = _SOURCE_LABELS.get(src_key, dealer)
        price_str = f"${price:,}" if price else "No Price"

        payload = {
            "title": f"⏰ ENDING: {s.get('year','?')} Porsche {model} {trim}".rstrip(),
            "body":  f"{price_str}  ·  {rem_h}h {rem_m}m left  ·  {src_label}",
            "url":   url,
        }

        ok = _send_push(payload)
        if ok:
            seen[seen_key] = {"alerted_at": datetime.now().isoformat(), "alerted": True}
            _save_seen(seen)
            sent += 1

    log.info("Ending-soon push alerts: %d sent", sent)


def notify_dom_alert(conn):
    """Send push alerts for TIER1 listings that have been active >= 30 days.

    Fires once per listing (keyed by listing_url). Prunes seen store entries
    older than 90 days on each run.
    """
    if not NOTIFICATIONS_ENABLED:
        return

    dom_seen_file = SCRIPT_DIR / "data" / "seen_alerts_dom.json"

    # Load + prune dedup store (90-day window)
    seen = {}
    if dom_seen_file.exists():
        try:
            raw = json.loads(dom_seen_file.read_text())
        except Exception:
            raw = {}
        cutoff = (datetime.now() - timedelta(days=90)).isoformat()
        seen = {k: v for k, v in raw.items()
                if v.get("alerted_at", "") >= cutoff}
        if len(seen) < len(raw):
            log.info("seen_alerts_dom: pruned %d entries older than 90 days",
                     len(raw) - len(seen))

    rows = conn.execute("""
        SELECT id, year, make, model, trim, price, mileage, dealer,
               listing_url, tier, date_first_seen
        FROM listings
        WHERE tier = 'TIER1'
          AND status = 'active'
          AND date_first_seen IS NOT NULL
          AND CAST(julianday('now') - julianday(date_first_seen) AS INTEGER) >= 30
    """).fetchall()

    sent = 0
    for row in rows:
        s = dict(row)
        url = s.get("listing_url") or ""
        seen_key = url if url else "id:{0}".format(s.get("id"))

        if seen_key in seen:
            continue

        try:
            dom_days = int(
                conn.execute(
                    "SELECT CAST(julianday('now') - julianday(date_first_seen) AS INTEGER) FROM listings WHERE id=?",
                    (s["id"],)
                ).fetchone()[0] or 0
            )
        except Exception:
            dom_days = 30

        year  = s.get("year", "?")
        model = s.get("model", "") or ""
        trim  = (s.get("trim") or "").strip()
        price = s.get("price")

        title_parts = [str(year), "Porsche", model]
        if trim and trim.lower() != model.lower():
            title_parts.append(trim)
        title = " ".join(p for p in title_parts if p)

        price_str = "${0:,}".format(price) if price else "No Price"

        payload = {
            "title": "\u23f3 Still Available \u2014 {0} days".format(dom_days),
            "body":  "{0} \u00b7 {1}".format(title, price_str),
            "url":   _clean_url(url),
        }

        ok = _send_push(payload)
        if ok:
            seen[seen_key] = {"alerted_at": datetime.now().isoformat(), "alerted": True}
            dom_seen_file.parent.mkdir(exist_ok=True)
            dom_seen_file.write_text(json.dumps(seen, indent=2))
            sent += 1
            log.info("DOM alert sent: %s (%d days)", title, dom_days)

    log.info("Days-on-market push alerts: %d sent", sent)


# ── Watchlist alerts ──────────────────────────────────────────────────────────

_WATCHLIST_PATH = Path(__file__).parent / "data" / "watchlist.json"
_SEEN_WATCH_PATH = Path(__file__).parent / "data" / "seen_alerts_watch.json"

def _load_watchlist() -> list:
    try:
        return json.loads(_WATCHLIST_PATH.read_text())
    except Exception:
        return []

def _load_seen_watch() -> dict:
    try:
        return json.loads(_SEEN_WATCH_PATH.read_text())
    except Exception:
        return {}

def _save_seen_watch(seen: dict):
    _SEEN_WATCH_PATH.write_text(json.dumps(seen, indent=2))

def _matches_watch(listing: dict, watch: dict) -> bool:
    """Return True if listing satisfies all non-empty watch criteria."""
    gen   = (listing.get("generation") or "").strip()
    model = (listing.get("model") or "").strip().lower()
    trim  = (listing.get("trim") or "").strip().lower()
    trans = (listing.get("transmission") or "").strip().lower()
    price = listing.get("price")
    mi    = listing.get("mileage")

    # Generation filter
    gens = watch.get("gens") or []
    if gens and gen not in gens:
        return False

    # Model filter
    models = [m.lower() for m in (watch.get("models") or [])]
    if models and model not in models:
        return False

    # Trim filter (any trim keyword substring match)
    trims = [t.lower() for t in (watch.get("trims") or [])]
    if trims and not any(t in trim for t in trims):
        return False

    # Transmission filter
    watch_trans = (watch.get("transmission") or "").lower()
    if watch_trans and watch_trans not in trans:
        return False

    # Price ceiling
    max_price = watch.get("max_price")
    if max_price and price and float(price) > float(max_price):
        return False

    # Mileage ceiling
    max_mi = watch.get("max_mileage")
    if max_mi and mi and float(mi) > float(max_mi):
        return False

    return True


def notify_watchlist(conn, new_listing_ids):
    """Match new listings against watchlist specs and push an alert for each hit."""
    if not NOTIFICATIONS_ENABLED:
        return
    if not new_listing_ids:
        return

    watches = _load_watchlist()
    if not watches:
        return

    placeholders = ",".join("?" * len(new_listing_ids))
    rows = conn.execute(
        f"""SELECT id, year, make, model, trim, price, mileage, dealer,
                   listing_url, generation, transmission, image_url, tier
            FROM listings WHERE id IN ({placeholders})""",
        new_listing_ids
    ).fetchall()

    seen = _load_seen_watch()
    sent = 0

    for row in rows:
        s = dict(row)
        url = s.get("listing_url") or ""

        for watch in watches:
            if not _matches_watch(s, watch):
                continue

            seen_key = f"watch:{watch['name']}:{url}"
            if seen_key in seen:
                continue

            year  = s.get("year") or "?"
            model = s.get("model") or "911"
            trim  = s.get("trim") or ""
            price = s.get("price")
            mi    = s.get("mileage")
            dealer = s.get("dealer") or ""

            price_str = f"${int(price):,}" if price else "No price"
            mi_str    = f"{int(mi):,} mi" if mi else ""
            body_parts = [price_str]
            if mi_str: body_parts.append(mi_str)
            if dealer:  body_parts.append(dealer)

            payload = {
                "title": f"🎯 Watch Hit: {watch['name']}",
                "body":  f"{year} {model} {trim} · {' · '.join(body_parts)}",
                "url":   _clean_url(url),
                "icon":  "/icons/icon-192.png",
            }
            ok = _send_push(payload)
            if ok:
                seen[seen_key] = {"alerted_at": datetime.now().isoformat()}
                _save_seen_watch(seen)
                sent += 1
                log.info("WATCHLIST HIT: %s → %s %s %s", watch["name"], year, model, trim)

    if sent:
        log.info("Watchlist push alerts: %d sent", sent)
