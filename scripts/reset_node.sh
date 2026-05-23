#!/usr/bin/env bash
# ARTEMIS node reset script — undoes everything setup_node.sh did.
# Usage:
#   sudo bash scripts/reset_node.sh [--remove-repo] [--dry-run]
#
# By default the repository at REPO_DIR is KEPT (only venv + service removed).
# Pass --remove-repo to also delete the checkout (DESTRUCTIVE — you lose config edits).

set -euo pipefail

DRY_RUN=0
REMOVE_REPO=0
for arg in "$@"; do
  case "$arg" in
    --dry-run)     DRY_RUN=1 ;;
    --remove-repo) REMOVE_REPO=1 ;;
  esac
done

REPO_DIR="${REPO_DIR:-/opt/artemis}"
SERVICE_FILE="/etc/systemd/system/artemis-node.service"
SERVICE_NAME="artemis-node"

RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }

run() {
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "(dry-run) $*"
  else
    "$@"
  fi
}

if [[ $REMOVE_REPO -eq 1 ]]; then
  warn "WARNING: --remove-repo will delete ${REPO_DIR} including all config edits."
  read -r -p "Type YES to confirm deletion: " confirm
  if [[ "${confirm}" != "YES" ]]; then
    echo "Aborted."
    exit 0
  fi
fi

echo ""
info "[1/4] Stopping and disabling artemis-node service..."
if systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
  run sudo systemctl stop "${SERVICE_NAME}"
  info "Service stopped."
else
  info "Service not running — skipping stop."
fi
if systemctl is-enabled --quiet "${SERVICE_NAME}" 2>/dev/null; then
  run sudo systemctl disable "${SERVICE_NAME}"
  info "Service disabled."
fi

echo ""
info "[2/4] Removing systemd service file..."
if [[ -f "${SERVICE_FILE}" ]]; then
  run sudo rm -f "${SERVICE_FILE}"
  run sudo systemctl daemon-reload
  info "Removed ${SERVICE_FILE}"
else
  info "Service file not found — skipping."
fi

echo ""
info "[3/4] Removing Python virtual environment..."
if [[ -d "${REPO_DIR}/.venv" ]]; then
  run rm -rf "${REPO_DIR}/.venv"
  info "Removed ${REPO_DIR}/.venv"
else
  info ".venv not found — skipping."
fi

echo ""
info "[4/4] Removing log directory..."
if [[ -d "${REPO_DIR}/logs" ]]; then
  run rm -rf "${REPO_DIR}/logs"
  info "Removed ${REPO_DIR}/logs"
fi

if [[ $REMOVE_REPO -eq 1 ]]; then
  info "Removing repository at ${REPO_DIR}..."
  run sudo rm -rf "${REPO_DIR}"
  info "Done — repository deleted."
else
  info "Repository kept at ${REPO_DIR} (run with --remove-repo to delete it too)."
fi

echo ""
echo -e "${GREEN}ARTEMIS node reset complete.${NC}"
echo "Re-provision with:  sudo bash ${REPO_DIR}/scripts/setup_node.sh"
echo ""
