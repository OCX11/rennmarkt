#!/bin/bash
# update_tunnel_url.sh — on reboot, reads new cloudflared tunnel URL and
# redeploys Cloudflare Worker so the permanent URL keeps working.
# Permanent push URL: https://rennmarkt-push.openclawx1.workers.dev

PROJ="/Users/claw/porsche-tracker"
LOG="$PROJ/logs/cloudflared.log"
CF_CONFIG="$PROJ/data/cf_config.json"
MAX_WAIT=60

# Load CF credentials from gitignored config
CF_KEY=$(python3 -c "import json; d=json.load(open('$CF_CONFIG')); print(d['cf_key'])")
CF_EMAIL=$(python3 -c "import json; d=json.load(open('$CF_CONFIG')); print(d['cf_email'])")
CF_ACCOUNT=$(python3 -c "import json; d=json.load(open('$CF_CONFIG')); print(d['cf_account'])")
WORKER_NAME=$(python3 -c "import json; d=json.load(open('$CF_CONFIG')); print(d['worker_name'])")

echo "[update_tunnel_url] starting at $(date)"

# Wait for tunnel URL to appear in log
TUNNEL_URL=""
ELAPSED=0
while [ -z "$TUNNEL_URL" ] && [ $ELAPSED -lt $MAX_WAIT ]; do
    TUNNEL_URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" 2>/dev/null | tail -1)
    if [ -z "$TUNNEL_URL" ]; then
        sleep 2
        ELAPSED=$((ELAPSED + 2))
    fi
done

if [ -z "$TUNNEL_URL" ]; then
    echo "[update_tunnel_url] ERROR: no tunnel URL after ${MAX_WAIT}s"
    exit 1
fi

echo "[update_tunnel_url] tunnel URL: $TUNNEL_URL"
echo "$TUNNEL_URL" > "$PROJ/data/tunnel_url.txt"

# Redeploy Worker with updated TUNNEL_URL binding
curl -s "https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT/workers/scripts/$WORKER_NAME" \
  -X PUT \
  -H "X-Auth-Email: $CF_EMAIL" \
  -H "X-Auth-Key: $CF_KEY" \
  -F "metadata={\"main_module\":\"worker.js\",\"bindings\":[{\"type\":\"plain_text\",\"name\":\"TUNNEL_URL\",\"text\":\"$TUNNEL_URL\"}],\"compatibility_date\":\"2024-01-01\"};type=application/json" \
  -F "worker.js=@$PROJ/worker.js;type=application/javascript+module" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('[update_tunnel_url] worker redeploy:', 'OK' if d.get('success') else d.get('errors'))"

echo "[update_tunnel_url] done at $(date)"
