#!/bin/bash
# ============================================================
# OmniAgent Smart Hub — Setup for OrangePi RV 2
# ============================================================
# Hardware: SpacemiT K1 (8-core RISC-V), 2 TOPS NPU, 8GB RAM
# OS:       Ubuntu 24.04 (RISC-V)
# Display:  7" Touchscreen
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
    chromium-browser \
    xdotool \
    unclutter \
    pulseaudio \
    python3 python3-pip python3-venv \
    xinput \
    xserver-xorg-input-evdev \
    fonts-noto-color-emoji

# ── 2. Touchscreen calibration ─────────────────────────────
echo "[2/6] Configuring touchscreen..."
# Auto-detect touchscreen device
TOUCH_DEV=$(xinput list --name-only 2>/dev/null | grep -i "touch" | head -1)
if [ -n "$TOUCH_DEV" ]; then
    echo "  Found touchscreen: $TOUCH_DEV"
    # Map to correct display (for single-display setups this is automatic)
    xinput map-to-output "$TOUCH_DEV" "$(xrandr | grep ' connected' | head -1 | cut -d' ' -f1)" 2>/dev/null || true
else
    echo "  No touchscreen detected (will work with mouse)"
fi

# ── 3. Copy Smart Hub files ────────────────────────────────
echo "[3/6] Setting up Smart Hub..."
mkdir -p "$INSTALL_DIR"
cp "$SCRIPT_DIR/index.html" "$INSTALL_DIR/"

# Generate kiosk launcher
cat > "$INSTALL_DIR/start-hub.sh" << 'LAUNCHER'
#!/bin/bash
# Kill any existing chromium
pkill -f "chromium.*kiosk" 2>/dev/null || true

# Wait for X server
while ! xdotool getactivewindow &>/dev/null; do sleep 1; done

# Hide cursor after 3 seconds of inactivity
unclutter -idle 3 &

# Disable screen blanking
xset s off
xset -dpms
xset s noblank

# Set display brightness (if supported)
echo 200 | sudo tee /sys/class/backlight/*/brightness 2>/dev/null || true

# Launch Chromium in kiosk mode
exec chromium-browser \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-component-update \
    --check-for-update-interval=31536000 \
    --disable-features=TranslateUI \
    --overscroll-history-navigation=0 \
    --autoplay-policy=no-user-gesture-required \
    --enable-features=OverlayScrollbar \
    --disable-pinch \
    --touch-events=enabled \
    --enable-touch-drag-drop \
    --user-data-dir="$HOME/.config/omniagent-hub" \
    "file://$HOME/omniagent-hub/index.html"
LAUNCHER
chmod +x "$INSTALL_DIR/start-hub.sh"

# ── 4. Autostart on boot ──────────────────────────────────
echo "[4/6] Configuring autostart..."
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/omniagent-hub.desktop" << EOF
[Desktop Entry]
Type=Application
Name=OmniAgent Smart Hub
Exec=$INSTALL_DIR/start-hub.sh
X-GNOME-Autostart-enabled=true
Hidden=false
NoDisplay=false
Comment=OmniAgent touch-based Smart Hub
EOF

# Also create a systemd user service as fallback
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

# ── 5. NPU setup (SpacemiT K1) ────────────────────────────
echo "[5/6] Setting up NPU..."
# Check for SpacemiT NPU device
if [ -e "/dev/spacemit-npu" ] || [ -e "/dev/npu" ] || [ -d "/sys/class/npu" ]; then
    echo "  NPU device detected"
    # Install SpacemiT AI SDK if available
    if command -v spacemit-ai &>/dev/null; then
        echo "  SpacemiT AI SDK already installed"
    else
        echo "  SpacemiT AI SDK not found — NPU will be used if SDK is installed later"
        echo "  Install from: https://developer.spacemit.com/"
    fi
else
    echo "  No NPU device found — using CPU for local inference"
fi

# Install ONNX Runtime for local inference (CPU fallback)
pip3 install --user onnxruntime 2>/dev/null || echo "  ONNX Runtime install skipped (may not support RISC-V yet)"

# ── 6. Audio setup ─────────────────────────────────────────
echo "[6/6] Configuring audio..."
# Enable PulseAudio for mic + speaker
pulseaudio --check 2>/dev/null || pulseaudio --start 2>/dev/null || true

# ── Done ───────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════"
echo "  Setup complete!"
echo ""
echo "  Hub location:  $INSTALL_DIR"
echo "  Start command: $INSTALL_DIR/start-hub.sh"
echo "  Autostart:     enabled (reboots into kiosk)"
echo ""
echo "  First launch:"
echo "    1. Reboot:  sudo reboot"
echo "    2. Hub opens in kiosk mode on the touchscreen"
echo "    3. Enter your OmniAgent server IP (e.g. 192.168.1.100:8000)"
echo "    4. Or tap 'Scan Network' to auto-discover"
echo ""
echo "  Manual start:  $INSTALL_DIR/start-hub.sh"
echo "  Quit kiosk:    Alt+F4 or ssh in and run: pkill chromium"
echo "═══════════════════════════════════════════════"
