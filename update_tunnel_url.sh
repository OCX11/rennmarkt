#!/bin/bash
# update_tunnel_url.sh — reads the live cloudflared tunnel URL from its log,
# patches docs/notify.html, commits, and pushes to GitHub.
# Runs at boot via launchd AFTER cloudflared has started.

PROJ="/Users/claw/porsche-tracker"
LOG="$PROJ/logs/cloudflared.log"
HTML="$PROJ/docs/notify.html"
MAX_WAIT=60   # seconds to wait for tunnel to come up

echo "[update_tunnel_url] starting at $(date)"

# Clear stale log so we only find the URL from this boot
> "$LOG"
sleep 3   # let cloudflared start writing
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
    echo "[update_tunnel_url] ERROR: tunnel URL not found in log after ${MAX_WAIT}s"
    exit 1
fi

echo "[update_tunnel_url] tunnel URL: $TUNNEL_URL"

# Patch notify.html — replace any existing push server URL
sed -i '' "s|const PUSH_SERVER = '.*';|const PUSH_SERVER = '$TUNNEL_URL';|g" "$HTML"

# Verify patch landed
CURRENT=$(grep "const PUSH_SERVER" "$HTML" | head -1)
echo "[update_tunnel_url] patched: $CURRENT"

# Save for reference
echo "$TUNNEL_URL" > "$PROJ/data/tunnel_url.txt"

# Commit and push to GitHub Pages
cd "$PROJ"
git add docs/notify.html data/tunnel_url.txt
git commit -m "chore: update tunnel URL to $TUNNEL_URL" --no-verify 2>&1
git push origin main 2>&1

echo "[update_tunnel_url] done at $(date)"
