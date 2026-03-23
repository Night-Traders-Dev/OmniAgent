#!/bin/bash
# ============================================================
# OmniAgent Smart Hub — Setup for OrangePi RV 2
# ============================================================
# Hardware: SpacemiT K1 (8-core RISC-V), 2 TOPS NPU, 8GB RAM
# OS:       Ubuntu 24.04 (RISC-V)
# Display:  7" Touchscreen
#
# Builds a native C application (SDL2 + libcurl) for maximum
# responsiveness on the touchscreen. No browser needed.
# ============================================================
set -e

echo "═══════════════════════════════════════════════"
echo "  OmniAgent Smart Hub — OrangePi RV 2 Setup"
echo "═══════════════════════════════════════════════"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/omniagent-hub"

# ── 1. System dependencies ──────────────────────────────────
echo "[1/6] Installing system packages..."
sudo apt-get update
sudo apt-get install -y \
    build-essential cmake pkg-config \
    libsdl2-dev libsdl2-ttf-dev libcurl4-openssl-dev \
    fonts-dejavu-core fonts-noto-color-emoji \
    pulseaudio \
    unclutter \
    xinput xdotool \
    xserver-xorg-input-evdev

# ── 2. Build Smart Hub ─────────────────────────────────────
echo "[2/6] Building native Smart Hub..."
cd "$SCRIPT_DIR"
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)

# ── 3. Install ──────────────────────────────────────────────
echo "[3/6] Installing..."
mkdir -p "$INSTALL_DIR"
cp build/omni-hub "$INSTALL_DIR/"

# Create launcher script
cat > "$INSTALL_DIR/start-hub.sh" << 'LAUNCHER'
#!/bin/bash
# Wait for display server
while ! xdotool getactivewindow &>/dev/null 2>&1; do sleep 1; done

# Hide cursor after 3s of inactivity
unclutter -idle 3 &

# Disable screen blanking
xset s off 2>/dev/null
xset -dpms 2>/dev/null
xset s noblank 2>/dev/null

# Set display brightness (if supported)
for bl in /sys/class/backlight/*/brightness; do
    echo 200 | sudo tee "$bl" 2>/dev/null
done

# Launch Smart Hub (pass server URL if saved)
SAVED_URL=""
if [ -f "$HOME/.omniagent-hub-url" ]; then
    SAVED_URL=$(cat "$HOME/.omniagent-hub-url")
fi

exec "$HOME/omniagent-hub/omni-hub" $SAVED_URL
LAUNCHER
chmod +x "$INSTALL_DIR/start-hub.sh"

# ── 4. Touchscreen calibration ─────────────────────────────
echo "[4/6] Configuring touchscreen..."
TOUCH_DEV=$(xinput list --name-only 2>/dev/null | grep -i "touch" | head -1)
if [ -n "$TOUCH_DEV" ]; then
    echo "  Found touchscreen: $TOUCH_DEV"
    DISPLAY_NAME=$(xrandr 2>/dev/null | grep ' connected' | head -1 | cut -d' ' -f1)
    if [ -n "$DISPLAY_NAME" ]; then
        xinput map-to-output "$TOUCH_DEV" "$DISPLAY_NAME" 2>/dev/null || true
        echo "  Mapped to display: $DISPLAY_NAME"
    fi
else
    echo "  No touchscreen detected (will work with mouse)"
fi

# ── 5. Autostart on boot ──────────────────────────────────
echo "[5/6] Configuring autostart..."
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/omniagent-hub.desktop" << EOF
[Desktop Entry]
Type=Application
Name=OmniAgent Smart Hub
Exec=$INSTALL_DIR/start-hub.sh
X-GNOME-Autostart-enabled=true
Hidden=false
NoDisplay=false
Comment=OmniAgent native touch-based Smart Hub
EOF

# Systemd user service as fallback
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/omniagent-hub.service" << EOF
[Unit]
Description=OmniAgent Smart Hub
After=graphical-session.target

[Service]
Type=simple
Environment=DISPLAY=:0
ExecStart=$INSTALL_DIR/start-hub.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable omniagent-hub.service 2>/dev/null || true

# ── 6. NPU setup (SpacemiT K1) ────────────────────────────
echo "[6/6] Checking NPU..."
if [ -e "/dev/spacemit-npu" ] || [ -e "/dev/npu" ] || [ -d "/sys/class/npu" ]; then
    echo "  NPU device detected — available for future local inference"
else
    echo "  No NPU device node found (may need SpacemiT AI SDK)"
    echo "  Install from: https://developer.spacemit.com/"
fi

# ── Done ───────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════"
echo "  Setup complete!"
echo ""
echo "  Binary:    $INSTALL_DIR/omni-hub"
echo "  Launcher:  $INSTALL_DIR/start-hub.sh"
echo "  Autostart: enabled (boots into hub)"
echo ""
echo "  Run now:   $INSTALL_DIR/omni-hub"
echo "  With URL:  $INSTALL_DIR/omni-hub 192.168.1.100:8000"
echo ""
echo "  Quit:      Press Escape or Ctrl+C"
echo "═══════════════════════════════════════════════"
