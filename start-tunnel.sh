#!/bin/bash
# Start OmniAgent with a free Cloudflare Tunnel for internet access.
# No account needed — uses cloudflared quick tunnels (trycloudflare.com).
#
# Usage: ./start-tunnel.sh
# This starts the server on port 8000 and creates a public URL.

set -e
cd "$(dirname "$0")"

CLOUDFLARED="${CLOUDFLARED:-$HOME/.local/bin/cloudflared}"
VENV=".venv/bin"

echo "=== OmniAgent + Cloudflare Tunnel ==="
echo ""

# Start OmniAgent server in background
echo "[1/2] Starting OmniAgent server on port 8000..."
$VENV/uvicorn omni_agent:app --host 0.0.0.0 --port 8000 &
SERVER_PID=$!
sleep 2

# Verify server is running
if ! kill -0 $SERVER_PID 2>/dev/null; then
    echo "ERROR: Server failed to start"
    exit 1
fi
echo "       Server running (PID: $SERVER_PID)"

# Start Cloudflare quick tunnel
echo "[2/2] Creating Cloudflare tunnel..."
echo ""
echo "========================================"
echo "  Your OmniAgent public URL will appear below."
echo "  Share this URL to access from anywhere."
echo "  No account or setup needed."
echo "========================================"
echo ""

$CLOUDFLARED tunnel --url http://localhost:8000 2>&1 | while IFS= read -r line; do
    # Extract and highlight the tunnel URL
    if echo "$line" | grep -q "trycloudflare.com"; then
        URL=$(echo "$line" | grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com')
        if [ -n "$URL" ]; then
            echo ""
            echo "============================================"
            echo "  PUBLIC URL: $URL"
            echo "============================================"
            echo ""
            echo "  Connect your Android app to this URL"
            echo "  or open it in any browser."
            echo ""
        fi
    fi
    echo "$line"
done

# Cleanup on exit
trap "kill $SERVER_PID 2>/dev/null; echo 'Shutdown.'" EXIT
wait
