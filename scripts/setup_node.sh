#!/usr/bin/env bash
# ARTEMIS node provisioning script
# Usage:
#   sudo bash scripts/setup_node.sh [--dry-run] [--skip-radar] [--skip-hw-check]
#
# Environment overrides:
#   REPO_DIR      — path to ARTEMIS checkout  (default: /opt/artemis)
#   PYTHON_BIN    — python binary name         (default: python3.11)
#   ARTEMIS_USER  — user to run the daemon as  (default: pi)

set -euo pipefail

# ── Argument parsing ─────────────────────────────────────────────────────────
DRY_RUN=0
SKIP_RADAR=0
SKIP_HW_CHECK=0
for arg in "$@"; do
  case "$arg" in
    --dry-run)       DRY_RUN=1 ;;
    --skip-radar)    SKIP_RADAR=1 ;;
    --skip-hw-check) SKIP_HW_CHECK=1 ;;
  esac
done

# ── Constants ─────────────────────────────────────────────────────────────────
REPO_DIR="${REPO_DIR:-/opt/artemis}"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"
ARTEMIS_USER="${ARTEMIS_USER:-pi}"
SERVICE_FILE="/etc/systemd/system/artemis-node.service"
MIN_DISK_KB=2097152   # 2 GB in kB

RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

run() {
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "(dry-run) $*"
  else
    "$@"
  fi
}

# ── Cleanup / rollback on error ───────────────────────────────────────────────
_ROLLBACK_VENV=0
_ROLLBACK_SERVICE=0

cleanup() {
  local exit_code=$?
  if [[ $exit_code -ne 0 ]]; then
    warn "Setup failed (exit $exit_code) — rolling back..."
    if [[ $_ROLLBACK_SERVICE -eq 1 ]]; then
      sudo systemctl disable artemis-node 2>/dev/null || true
      sudo rm -f "${SERVICE_FILE}"
      sudo systemctl daemon-reload
      warn "Removed systemd service."
    fi
    if [[ $_ROLLBACK_VENV -eq 1 && -d "${REPO_DIR}/.venv" ]]; then
      rm -rf "${REPO_DIR}/.venv"
      warn "Removed .venv."
    fi
    error "Setup aborted. Fix the issue above and re-run."
  fi
}
trap cleanup EXIT

# ── Step 0: Hardware & pre-flight checks ─────────────────────────────────────
echo ""
info "[0/9] Pre-flight checks..."

if [[ $SKIP_HW_CHECK -eq 0 ]]; then
  if [[ -f /proc/cpuinfo ]]; then
    if ! grep -qi "Raspberry Pi 5" /proc/cpuinfo; then
      warn "This script targets Raspberry Pi 5 (Bookworm). Detected hardware:"
      grep "Model" /proc/cpuinfo 2>/dev/null || true
      warn "Continuing anyway — use --skip-hw-check to suppress this warning."
    else
      info "Hardware: $(grep 'Model' /proc/cpuinfo | head -1 | cut -d: -f2 | xargs)"
    fi
  else
    warn "/proc/cpuinfo not found — not running on Linux? Use --skip-hw-check to suppress."
  fi
fi

# Disk space check
FREE_KB=$(df -k / | awk 'NR==2 {print $4}')
if [[ "${FREE_KB}" -lt "${MIN_DISK_KB}" ]]; then
  error "Insufficient disk space: ${FREE_KB} kB free, need ${MIN_DISK_KB} kB (2 GB)."
  error "Free up space with: sudo apt clean && sudo journalctl --vacuum-time=3d"
  exit 1
fi
info "Disk space OK: $((FREE_KB / 1024)) MB free."

# Python check
if ! command -v "${PYTHON_BIN}" &>/dev/null; then
  error "${PYTHON_BIN} not found. Install with: sudo apt install -y python3.11 python3.11-venv"
  exit 1
fi
PY_VER=$("${PYTHON_BIN}" --version 2>&1)
info "Python: ${PY_VER}"

# Repository check
if [[ ! -d "${REPO_DIR}" ]]; then
  error "Repository directory not found: ${REPO_DIR}"
  error "Clone first:  git clone https://github.com/manu14357/Artemis ${REPO_DIR}"
  exit 1
fi
info "Repo:  ${REPO_DIR}"

# ── Step 1: apt update ────────────────────────────────────────────────────────
echo ""
info "[1/9] Updating apt package index..."
run sudo apt update -qq

# ── Step 2: System dependencies ───────────────────────────────────────────────
echo ""
info "[2/9] Installing system dependencies..."
APT_PACKAGES=(
  git curl build-essential pkg-config
  python3 python3-pip python3-venv python3-dev
  librtlsdr-dev rtl-sdr
  gnuradio python3-gnuradio
  libatlas-base-dev libopenblas-dev
  portaudio19-dev libportaudio2 alsa-utils
  mosquitto mosquitto-clients
  python3-picamera2
  cmake
  usbutils   # lsusb — for USB device detection
)
run sudo apt install -y "${APT_PACKAGES[@]}"

# ── Step 3: Audio device detection ───────────────────────────────────────────
echo ""
info "[3/9] Detecting audio input device..."
AUDIO_DEVICES=$("${PYTHON_BIN}" -c "
import sys
try:
    import sounddevice as sd
    devs = [d for d in sd.query_devices() if d['max_input_channels'] > 0]
    for i, d in enumerate(devs):
        print(f\"  [{d['index']}] {d['name']}  ({d['max_input_channels']} ch)\")
    if not devs:
        print('  (none found — connect ReSpeaker before starting daemon)')
except Exception as e:
    print(f'  (sounddevice not yet installed: {e})')
" 2>/dev/null || true)
if [[ -n "${AUDIO_DEVICES}" ]]; then
  info "Audio input devices found:"
  echo "${AUDIO_DEVICES}"
  info "Edit node/config/node_default.yaml → sensors.acoustic.device_index if needed."
else
  warn "No audio devices detected.  Connect the ReSpeaker 4-Mic array and re-run."
fi

# ── Step 4: Python virtualenv ─────────────────────────────────────────────────
echo ""
info "[4/9] Setting up Python virtual environment..."
cd "${REPO_DIR}"
if [[ ! -d .venv ]]; then
  _ROLLBACK_VENV=1
  run "${PYTHON_BIN}" -m venv .venv
  info "Created .venv"
else
  info ".venv already exists — skipping creation."
fi

if [[ $DRY_RUN -eq 0 ]]; then
  source .venv/bin/activate
  python -m pip install --upgrade pip wheel setuptools -q
fi

# ── Step 5: Python dependencies ───────────────────────────────────────────────
echo ""
info "[5/9] Installing Python dependencies (this may take 3–5 minutes)..."
run pip install -r requirements.txt -q

# ── Step 6: Radar firmware (Acconeer XM125) ──────────────────────────────────
echo ""
if [[ $SKIP_RADAR -eq 1 ]]; then
  info "[6/9] Skipping radar firmware flash (--skip-radar)."
else
  info "[6/9] Checking for Acconeer XM125 radar..."
  # Look for the XM125 on likely serial ports
  RADAR_PORT=""
  for port in /dev/ttyUSB0 /dev/ttyACM0 /dev/ttyUSB1; do
    if [[ -e "$port" ]]; then
      RADAR_PORT="$port"
      info "Found serial device at $port"
      break
    fi
  done

  if [[ -n "${RADAR_PORT}" ]]; then
    info "Flashing Acconeer XM125 default firmware on ${RADAR_PORT}..."
    if command -v python &>/dev/null; then
      run python -m acconeer.exptool.flash flash_default --serial-port "${RADAR_PORT}" || {
        warn "Firmware flash failed — device may already be running correct firmware."
        warn "If issues persist: python -m acconeer.exptool.flash --help"
      }
    fi
    # Update node config with detected port
    if [[ -f node/config/node_default.yaml ]]; then
      run sed -i "s|serial_port:.*|serial_port: '${RADAR_PORT}'|" node/config/node_default.yaml
      info "Updated node_default.yaml → sensors.radar.serial_port: ${RADAR_PORT}"
    fi
  else
    warn "No serial device found for XM125 radar."
    warn "Connect the XM125 via USB-UART and re-run, or use --skip-radar."
    warn "Manual flash:  python -m acconeer.exptool.flash flash_default --serial-port /dev/ttyUSB0"
  fi
fi

# ── Step 7: Mosquitto MQTT broker ─────────────────────────────────────────────
echo ""
info "[7/9] Enabling Mosquitto MQTT broker..."
run sudo systemctl enable mosquitto
run sudo systemctl restart mosquitto
# Brief wait to confirm it is up
if [[ $DRY_RUN -eq 0 ]]; then
  sleep 1
  if systemctl is-active --quiet mosquitto; then
    info "Mosquitto is running."
  else
    warn "Mosquitto did not start — check: sudo journalctl -u mosquitto -n 20"
  fi
fi

# ── Step 8: systemd service ───────────────────────────────────────────────────
echo ""
info "[8/9] Installing artemis-node systemd service..."

# Substitute actual REPO_DIR and user into the service template
TMPSERVICE=$(mktemp)
sed \
  -e "s|/opt/artemis|${REPO_DIR}|g" \
  -e "s|User=pi|User=${ARTEMIS_USER}|g" \
  -e "s|Group=pi|Group=${ARTEMIS_USER}|g" \
  node/systemd/artemis-node.service > "${TMPSERVICE}"

run sudo cp "${TMPSERVICE}" "${SERVICE_FILE}"
rm -f "${TMPSERVICE}"
run sudo systemctl daemon-reload
run sudo systemctl enable artemis-node
_ROLLBACK_SERVICE=1
info "Service registered: artemis-node"

# ── Step 9: Verify install ────────────────────────────────────────────────────
echo ""
info "[9/9] Running post-install verification..."
if [[ $DRY_RUN -eq 0 ]]; then
  run "${REPO_DIR}/.venv/bin/python" scripts/verify_install.py --skip-hardware || {
    warn "Some checks failed — review output above before starting daemon."
  }
fi

# ── Done ───────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔═══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   ARTEMIS node setup complete! ✓      ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════╝${NC}"
echo ""
echo "Next steps:"
echo "  1. Edit GPS coordinates:  nano ${REPO_DIR}/node/config/node_default.yaml"
echo "     (set node.location.lat / .lon / .alt_m)"
echo ""
echo "  2. Start the daemon:      sudo systemctl start artemis-node"
echo "  3. Follow logs:           sudo journalctl -u artemis-node -f"
echo "  4. Re-run verification:   python scripts/verify_install.py"
echo ""
