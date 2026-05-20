#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/artemis}"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"
SERVICE_FILE="/etc/systemd/system/artemis-node.service"

echo "[1/8] Updating apt packages..."
sudo apt update
sudo apt upgrade -y

echo "[2/8] Installing system dependencies..."
sudo apt install -y \
  git curl build-essential pkg-config \
  python3 python3-pip python3-venv python3-dev \
  librtlsdr-dev rtl-sdr \
  gnuradio python3-gnuradio \
  libatlas-base-dev libopenblas-dev \
  portaudio19-dev libportaudio2 alsa-utils \
  mosquitto mosquitto-clients \
  python3-picamera2 \
  cmake

echo "[3/8] Ensuring repository exists at ${REPO_DIR}..."
if [[ ! -d "${REPO_DIR}" ]]; then
  echo "Repository directory not found: ${REPO_DIR}"
  echo "Clone your repo first, then rerun."
  exit 1
fi

cd "${REPO_DIR}"

echo "[4/8] Creating Python virtual environment..."
if [[ ! -d .venv ]]; then
  ${PYTHON_BIN} -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip wheel setuptools

echo "[5/8] Installing Python dependencies..."
pip install -r requirements.txt

echo "[6/8] Enabling Mosquitto broker..."
sudo systemctl enable mosquitto
sudo systemctl restart mosquitto

echo "[7/8] Installing systemd service..."
sudo cp node/systemd/artemis-node.service "${SERVICE_FILE}"
sudo systemctl daemon-reload
sudo systemctl enable artemis-node

echo "[8/8] Setup complete."
echo "To start the node daemon now:"
echo "  sudo systemctl start artemis-node"
echo "To inspect logs:"
echo "  sudo journalctl -u artemis-node -f"
