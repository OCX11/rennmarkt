#!/bin/bash
# run_cloudflared.sh — wrapper for launchd so log output is captured correctly
LOG="/Users/claw/porsche-tracker/logs/cloudflared.log"
# Truncate log on each start so update_tunnel_url.sh always finds the fresh URL
> "$LOG"
exec /opt/homebrew/bin/cloudflared tunnel --url http://127.0.0.1:5055 >> "$LOG" 2>&1
