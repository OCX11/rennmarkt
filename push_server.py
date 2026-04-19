#!/usr/bin/env python3
"""
push_server.py — PTOX11 Web Push notification server.

Runs as a Flask app on localhost:5055. Exposed to the internet via
Cloudflare Tunnel so the PWA on any device can subscribe.

Endpoints:
  GET  /vapid-public-key        → returns VAPID public key for frontend
  POST /subscribe               → save a push subscription
  POST /unsubscribe             → remove a push subscription
  GET  /subscribers             → list active subscriber count (internal)
  POST /send-push               → send a push to all subscribers (internal, localhost only)

Push payloads are sent by notify_push.py (replaces notify_imessage.py).
This server just holds subscriptions and relays pushes to APNs/FCM via VAPID.
"""
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, abort

SCRIPT_DIR = Path(__file__).parent
LOG_DIR = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "push_server.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

VAPID_KEY_FILE = SCRIPT_DIR / "data" / "vapid_keys.json"
SUBS_FILE = SCRIPT_DIR / "data" / "push_subscriptions.json"

app = Flask(__name__)


# ── VAPID keys ─────────────────────────────────────────────────────────────────

def _load_vapid():
    if not VAPID_KEY_FILE.exists():
        log.error("vapid_keys.json not found — run keygen first")
        sys.exit(1)
    return json.loads(VAPID_KEY_FILE.read_text())


VAPID = _load_vapid()
VAPID_PUBLIC_KEY = VAPID["public_key"]
VAPID_PRIVATE_KEY_PEM = VAPID["private_key_pem"]


# ── Subscription store ─────────────────────────────────────────────────────────

def _load_subs() -> dict:
    if SUBS_FILE.exists():
        try:
            return json.loads(SUBS_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_subs(subs: dict):
    SUBS_FILE.parent.mkdir(exist_ok=True)
    SUBS_FILE.write_text(json.dumps(subs, indent=2))


def _sub_key(sub: dict) -> str:
    """Unique key for a subscription — use the endpoint URL."""
    return sub.get("endpoint", "")


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/vapid-public-key")
def vapid_public_key():
    return jsonify({"publicKey": VAPID_PUBLIC_KEY})


@app.route("/subscribe", methods=["POST"])
def subscribe():
    sub = request.get_json(silent=True)
    if not sub or not sub.get("endpoint"):
        abort(400, "Invalid subscription object")

    key = _sub_key(sub)
    subs = _load_subs()

    label = request.args.get("label", "")
    subs[key] = {
        "subscription": sub,
        "label": label,
        "subscribed_at": datetime.now().isoformat(),
    }
    _save_subs(subs)
    log.info("New subscription: %s  label=%s  total=%d", key[:50], label or "(none)", len(subs))
    return jsonify({"status": "subscribed", "total": len(subs)}), 201


@app.route("/unsubscribe", methods=["POST"])
def unsubscribe():
    body = request.get_json(silent=True) or {}
    endpoint = body.get("endpoint") or (body.get("subscription") or {}).get("endpoint")
    if not endpoint:
        abort(400, "Missing endpoint")

    subs = _load_subs()
    if endpoint in subs:
        del subs[endpoint]
        _save_subs(subs)
        log.info("Unsubscribed: %s  remaining=%d", endpoint[:50], len(subs))
        return jsonify({"status": "unsubscribed", "remaining": len(subs)})
    return jsonify({"status": "not_found"}), 404


@app.route("/subscribers")
def subscribers():
    """Internal status — total subscriber count."""
    subs = _load_subs()
    entries = [{"label": v.get("label", ""), "subscribed_at": v.get("subscribed_at", "")}
               for v in subs.values()]
    return jsonify({"count": len(subs), "subscribers": entries})


@app.route("/send-push", methods=["POST"])
def send_push():
    """Internal endpoint — called by notify_push.py on the same machine.
    Rejects requests from non-localhost to prevent abuse.
    """
    remote = request.remote_addr or ""
    if remote not in ("127.0.0.1", "::1", "localhost"):
        log.warning("Rejected /send-push from non-localhost: %s", remote)
        abort(403, "Internal endpoint")

    payload = request.get_json(silent=True)
    if not payload:
        abort(400, "Missing payload")

    title   = payload.get("title", "PTOX11")
    body    = payload.get("body", "")
    url     = payload.get("url", "")
    icon    = payload.get("icon", "/PTOX11/icons/icon-192.png")
    badge   = payload.get("badge", "/PTOX11/icons/icon-192.png")

    notification = {
        "title": title,
        "body": body,
        "url": url,
        "icon": icon,
        "badge": badge,
        "timestamp": int(datetime.now().timestamp() * 1000),
    }

    subs = _load_subs()
    if not subs:
        log.info("send-push: no subscribers")
        return jsonify({"sent": 0, "failed": 0, "removed": 0})

    results = _send_to_all(subs, notification)
    return jsonify(results)


# ── Push delivery ──────────────────────────────────────────────────────────────

def _send_to_all(subs: dict, notification: dict) -> dict:
    from pywebpush import webpush, WebPushException

    sent = 0
    failed = 0
    expired = []

    for endpoint, entry in list(subs.items()):
        sub = entry["subscription"]
        try:
            webpush(
                subscription_info=sub,
                data=json.dumps(notification),
                vapid_private_key=VAPID_PRIVATE_KEY_PEM,
                vapid_claims={"sub": "mailto:ptox11@localhost"},
                ttl=86400,
            )
            sent += 1
            log.debug("Push sent: %s", endpoint[:50])
        except WebPushException as e:
            status = getattr(e.response, "status_code", None) if e.response else None
            if status in (404, 410):
                # Subscription expired or revoked — remove it
                log.info("Subscription expired (HTTP %s), removing: %s", status, endpoint[:50])
                expired.append(endpoint)
            else:
                log.warning("Push failed (HTTP %s): %s — %s", status, endpoint[:50], str(e)[:120])
                failed += 1
        except Exception as e:
            log.warning("Push error: %s — %s", endpoint[:50], str(e)[:120])
            failed += 1

    # Remove expired subscriptions
    if expired:
        for ep in expired:
            del subs[ep]
        _save_subs(subs)

    log.info("Push delivery: sent=%d  failed=%d  removed=%d  remaining=%d",
             sent, failed, len(expired), len(subs))
    return {"sent": sent, "failed": failed, "removed": len(expired)}


# ── Entry point ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("PTOX11 Push Server starting on port 5055")
    log.info("VAPID public key: %s", VAPID_PUBLIC_KEY[:30] + "...")
    subs = _load_subs()
    log.info("Loaded %d existing subscriptions", len(subs))
    app.run(host="127.0.0.1", port=5055, debug=False)
