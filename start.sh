#!/usr/bin/env bash
set -euo pipefail

echo "==> Warp Account Manager - Linux setup/start"

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found. Install Python 3.8+" >&2
  exit 1
fi

if ! command -v pip3 >/dev/null 2>&1; then
  echo "ERROR: pip3 not found. Install pip for Python3" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==> Ensuring dependencies"
pip3 install -r requirements.txt

echo "==> Note: mitmproxy certificate trust is manual on Linux"
echo "    The certificate file is at ~/.mitmproxy/mitmproxy-ca-cert.pem after first run."
echo "    Trust it in your browser/system cert store to allow HTTPS interception."

echo "==> Starting Warp Account Manager"
exec python3 warp_account_manager.py


