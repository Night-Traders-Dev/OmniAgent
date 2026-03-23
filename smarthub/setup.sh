#!/bin/bash
# ============================================================
# OmniAgent Smart Hub — Setup for OrangePi RV 2
# ============================================================
# Hardware: SpacemiT K1 (8-core RISC-V), 2 TOPS NPU, 8GB RAM
# OS:       Ubuntu 24.04 (RISC-V) / Bianbu
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
NPU_SDK_DIR="$HOME/spacemit-ai-sdk"
CONFIG_FILE="$HOME/.omniagent-hub-url"
DEFAULT_SERVER="192.168.254.2:8000"

# ── 0. Cleanup previous installations ──────────────────────
echo "[0/8] Cleaning up previous installations..."

# Kill any running hub instances
pkill -f "omni-hub" 2>/dev/null || true
pkill -f "chromium.*kiosk" 2>/dev/null || true
pkill -f "chromium.*omniagent" 2>/dev/null || true
sleep 1

# Remove old autostart entries
rm -f "$HOME/.config/autostart/omniagent-hub.desktop" 2>/dev/null
rm -f "$HOME/.config/autostart/omniagent*.desktop" 2>/dev/null

# Disable and remove old systemd services
systemctl --user disable omniagent-hub.service 2>/dev/null || true
systemctl --user stop omniagent-hub.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/omniagent-hub.service" 2>/dev/null
systemctl --user daemon-reload 2>/dev/null || true

# Remove old install directory
if [ -d "$INSTALL_DIR" ]; then
    echo "  Removing old install: $INSTALL_DIR"
    rm -rf "$INSTALL_DIR"
fi

# Remove old Chromium kiosk config
rm -rf "$HOME/.config/omniagent-hub" 2>/dev/null

echo "  Cleanup complete"

# ── 1. System dependencies ──────────────────────────────────
echo "[1/8] Installing system packages..."
sudo apt-get update
sudo apt-get install -y \
    build-essential cmake pkg-config \
    libsdl2-dev libsdl2-ttf-dev libcurl4-openssl-dev \
    fonts-dejavu-core fonts-noto-color-emoji \
    pulseaudio \
    unclutter \
    xinput xdotool \
    xserver-xorg-input-evdev \
    avahi-utils \
    net-tools \
    curl wget

# ── 2. Build Smart Hub ─────────────────────────────────────
echo "[2/8] Building native Smart Hub..."
cd "$SCRIPT_DIR"
rm -rf build
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)

# ── 3. Install binary ──────────────────────────────────────
echo "[3/8] Installing..."
mkdir -p "$INSTALL_DIR"
cp build/omni-hub "$INSTALL_DIR/"

# ── 4. Auto-discover OmniAgent server ──────────────────────
echo "[4/8] Discovering OmniAgent server..."

discover_server() {
    # Try saved URL first
    if [ -f "$CONFIG_FILE" ]; then
        SAVED=$(cat "$CONFIG_FILE" 2>/dev/null)
        if [ -n "$SAVED" ]; then
            echo "  Trying saved server: $SAVED"
            if curl -sf --connect-timeout 2 "http://$SAVED/api/identify" | grep -q "OmniAgent" 2>/dev/null; then
                echo "  Connected to saved server: $SAVED"
                echo "$SAVED"
                return 0
            fi
            echo "  Saved server not responding, scanning..."
        fi
    fi

    # Try the default
    echo "  Trying default: $DEFAULT_SERVER"
    if curl -sf --connect-timeout 2 "http://$DEFAULT_SERVER/api/identify" | grep -q "OmniAgent" 2>/dev/null; then
        echo "  Found server at default: $DEFAULT_SERVER"
        echo "$DEFAULT_SERVER"
        return 0
    fi

    # Scan common subnets
    for SUBNET in \
        "$(ip -4 route show default 2>/dev/null | awk '{print $3}' | sed 's/\.[0-9]*$//')" \
        "192.168.254" \
        "192.168.1" \
        "192.168.0" \
        "10.0.0" \
        "172.16.0"; do

        [ -z "$SUBNET" ] && continue
        echo "  Scanning ${SUBNET}.0/24..."

        for i in $(seq 1 254); do
            IP="${SUBNET}.${i}"
            # Quick TCP check on port 8000 (faster than full HTTP)
            if timeout 0.3 bash -c "echo >/dev/tcp/$IP/8000" 2>/dev/null; then
                if curl -sf --connect-timeout 1 "http://${IP}:8000/api/identify" | grep -q "OmniAgent" 2>/dev/null; then
                    echo "  Found OmniAgent at ${IP}:8000"
                    echo "${IP}:8000"
                    return 0
                fi
            fi
        done
    done

    echo "  No server found — you can enter the IP in the hub UI"
    return 1
}

DISCOVERED=$(discover_server)
if [ -n "$DISCOVERED" ]; then
    echo "$DISCOVERED" > "$CONFIG_FILE"
    echo "  Server saved to $CONFIG_FILE"
fi

# ── 5. Create launcher script ─────────────────────────────
echo "[5/8] Creating launcher..."
cat > "$INSTALL_DIR/start-hub.sh" << 'LAUNCHER'
#!/bin/bash
# OmniAgent Smart Hub launcher — runs on boot

# Wait for display server
for i in $(seq 1 30); do
    if xdotool getactivewindow &>/dev/null 2>&1; then break; fi
    sleep 1
done

# Hide cursor after 3s of inactivity
unclutter -idle 3 &

# Disable screen blanking
xset s off 2>/dev/null
xset -dpms 2>/dev/null
xset s noblank 2>/dev/null

# Set display brightness (if supported)
for bl in /sys/class/backlight/*/brightness; do
    [ -f "$bl" ] && echo 200 | sudo tee "$bl" 2>/dev/null
done

# Load saved server URL
SERVER_URL=""
CONFIG="$HOME/.omniagent-hub-url"
if [ -f "$CONFIG" ]; then
    SERVER_URL=$(cat "$CONFIG")
fi

# If no saved URL, try default then scan
if [ -z "$SERVER_URL" ]; then
    # Try default
    if curl -sf --connect-timeout 2 "http://192.168.254.2:8000/api/identify" | grep -q "OmniAgent" 2>/dev/null; then
        SERVER_URL="192.168.254.2:8000"
    else
        # Quick scan of local gateway subnet
        GW_SUBNET=$(ip -4 route show default 2>/dev/null | awk '{print $3}' | sed 's/\.[0-9]*$//')
        if [ -n "$GW_SUBNET" ]; then
            for i in $(seq 1 254); do
                if timeout 0.3 bash -c "echo >/dev/tcp/${GW_SUBNET}.${i}/8000" 2>/dev/null; then
                    if curl -sf --connect-timeout 1 "http://${GW_SUBNET}.${i}:8000/api/identify" | grep -q "OmniAgent" 2>/dev/null; then
                        SERVER_URL="${GW_SUBNET}.${i}:8000"
                        echo "$SERVER_URL" > "$CONFIG"
                        break
                    fi
                fi
            done
        fi
    fi
fi

# Launch — pass discovered URL or let the UI handle connection
if [ -n "$SERVER_URL" ]; then
    exec "$HOME/omniagent-hub/omni-hub" "$SERVER_URL"
else
    exec "$HOME/omniagent-hub/omni-hub"
fi
LAUNCHER
chmod +x "$INSTALL_DIR/start-hub.sh"

# ── 6. Touchscreen calibration ─────────────────────────────
echo "[6/8] Configuring touchscreen..."
TOUCH_DEV=$(xinput list --name-only 2>/dev/null | grep -i "touch" | head -1)
if [ -n "$TOUCH_DEV" ]; then
    echo "  Found touchscreen: $TOUCH_DEV"
    DISPLAY_NAME=$(xrandr 2>/dev/null | grep ' connected' | head -1 | cut -d' ' -f1)
    if [ -n "$DISPLAY_NAME" ]; then
        xinput map-to-output "$TOUCH_DEV" "$DISPLAY_NAME" 2>/dev/null || true
        echo "  Mapped to display: $DISPLAY_NAME"
    fi

    # Persist touchscreen mapping via udev rule
    TOUCH_ID=$(xinput list --id-only "$TOUCH_DEV" 2>/dev/null)
    if [ -n "$TOUCH_ID" ] && [ -n "$DISPLAY_NAME" ]; then
        cat > /tmp/99-touchscreen.rules << UDEV_EOF
# OmniAgent Smart Hub — auto-map touchscreen
ACTION=="add|change", SUBSYSTEM=="input", ATTRS{name}=="$TOUCH_DEV", \
    RUN+="/usr/bin/xinput map-to-output $TOUCH_ID $DISPLAY_NAME"
UDEV_EOF
        sudo cp /tmp/99-touchscreen.rules /etc/udev/rules.d/ 2>/dev/null || true
        rm -f /tmp/99-touchscreen.rules
        echo "  Udev rule created for persistent mapping"
    fi
else
    echo "  No touchscreen detected (will work with mouse)"
fi

# ── 7. SpacemiT NPU AI SDK ────────────────────────────────
echo "[7/8] Setting up SpacemiT NPU AI SDK..."

ARCH=$(uname -m)
install_npu_sdk() {
    # Check if already installed
    if command -v spacemit-npu &>/dev/null || [ -d "$NPU_SDK_DIR" ]; then
        echo "  SpacemiT AI SDK already present"
        return 0
    fi

    # Only install on RISC-V hardware
    if [ "$ARCH" != "riscv64" ]; then
        echo "  Skipping NPU SDK (not RISC-V hardware: $ARCH)"
        return 0
    fi

    echo "  Detecting SpacemiT K1 NPU..."

    # Check for NPU device nodes
    NPU_FOUND=false
    for dev in /dev/spacemit-npu /dev/npu /dev/vha0 /sys/class/misc/vha; do
        if [ -e "$dev" ]; then
            NPU_FOUND=true
            echo "  NPU device found: $dev"
            break
        fi
    done

    if ! $NPU_FOUND; then
        echo "  No NPU device node — checking kernel modules..."
        if lsmod 2>/dev/null | grep -qi "img_npu\|vha\|spacemit_ai"; then
            NPU_FOUND=true
            echo "  NPU kernel module loaded"
        fi
    fi

    # Try Bianbu package manager (SpacemiT's distro)
    if command -v apt-get &>/dev/null; then
        echo "  Checking Bianbu/SpacemiT repositories..."

        # Add SpacemiT repo if not present
        if ! grep -rq "spacemit\|bianbu" /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null; then
            echo "  Adding SpacemiT package repository..."
            echo "deb [trusted=yes] https://archive.spacemit.com/bianbu/ noble main" | \
                sudo tee /etc/apt/sources.list.d/spacemit.list >/dev/null 2>&1 || true
            sudo apt-get update 2>/dev/null || true
        fi

        # Try installing the SDK packages
        for pkg in spacemit-ai-sdk spacemit-ai-support spacemit-npu-firmware img-npu-firmware; do
            if apt-cache show "$pkg" &>/dev/null; then
                echo "  Installing $pkg..."
                sudo apt-get install -y "$pkg" 2>/dev/null || true
            fi
        done
    fi

    # Download SDK from GitHub/SpacemiT if packages not available
    if ! command -v spacemit-npu &>/dev/null && [ ! -d "$NPU_SDK_DIR" ]; then
        echo "  Downloading SpacemiT AI SDK from source..."
        mkdir -p "$NPU_SDK_DIR"

        # Try the official SDK release
        SDK_URL="https://github.com/nicholasjng/spacemit-k1-npu-sdk/releases/latest/download/spacemit-ai-sdk-linux-riscv64.tar.gz"
        if wget -q --timeout=30 -O /tmp/spacemit-ai-sdk.tar.gz "$SDK_URL" 2>/dev/null; then
            tar -xzf /tmp/spacemit-ai-sdk.tar.gz -C "$NPU_SDK_DIR" --strip-components=1 2>/dev/null || true
            rm -f /tmp/spacemit-ai-sdk.tar.gz
            echo "  SDK extracted to $NPU_SDK_DIR"
        else
            echo "  Could not download SDK — trying pip fallback..."
            pip3 install --user spacemit-ort 2>/dev/null || true
        fi

        # Add SDK to PATH
        if [ -d "$NPU_SDK_DIR/bin" ]; then
            echo "export PATH=\"$NPU_SDK_DIR/bin:\$PATH\"" >> "$HOME/.bashrc"
            echo "export LD_LIBRARY_PATH=\"$NPU_SDK_DIR/lib:\$LD_LIBRARY_PATH\"" >> "$HOME/.bashrc"
            echo "  Added SDK to PATH in .bashrc"
        fi
    fi

    # Install ONNX Runtime with SpacemiT NPU backend
    echo "  Installing ONNX Runtime (NPU backend if available)..."
    pip3 install --user onnxruntime 2>/dev/null || true

    # Verify NPU access
    if $NPU_FOUND; then
        echo "  NPU Status: DETECTED"
        echo "  NPU can accelerate: wake word detection, intent classification, TTS"
    else
        echo "  NPU Status: not detected (CPU fallback will be used)"
        echo "  If your board has the SpacemiT K1, ensure NPU firmware is loaded:"
        echo "    sudo modprobe img_npu"
    fi
}

install_npu_sdk

# ── 8. Autostart on boot ──────────────────────────────────
echo "[8/8] Configuring autostart..."
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

# Systemd user service as fallback (for headless/no-DE setups)
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

# ── Done ───────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════"
echo "  Setup complete!"
echo ""
echo "  Binary:    $INSTALL_DIR/omni-hub ($(du -h "$INSTALL_DIR/omni-hub" | cut -f1))"
echo "  Launcher:  $INSTALL_DIR/start-hub.sh"
echo "  Autostart: enabled (boots into hub)"
if [ -f "$CONFIG_FILE" ]; then
    echo "  Server:    $(cat "$CONFIG_FILE") (saved)"
else
    echo "  Server:    not discovered — enter IP in hub UI"
fi
if [ -d "$NPU_SDK_DIR" ] || command -v spacemit-npu &>/dev/null; then
    echo "  NPU SDK:   installed"
else
    echo "  NPU SDK:   not available (CPU fallback)"
fi
echo ""
echo "  Run now:     $INSTALL_DIR/omni-hub"
echo "  With URL:    $INSTALL_DIR/omni-hub 192.168.254.2:8000"
echo "  Reboot:      sudo reboot  (hub starts automatically)"
echo ""
echo "  Quit:        Press Escape or Ctrl+C"
echo "  Uninstall:   rm -rf $INSTALL_DIR ~/.config/autostart/omniagent-hub.desktop"
echo "═══════════════════════════════════════════════"
