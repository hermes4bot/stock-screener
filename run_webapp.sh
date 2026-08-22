#!/bin/bash
# Start the gap screener web frontend
# Usage: ./run_webapp.sh [port]   (default 8080)
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.hermes/bin:$PATH"
PORT="${1:-8080}"
exec .venv/bin/python webapp.py "$PORT"
