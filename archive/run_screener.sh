#!/bin/bash
# ============================================================
# Stock Gap Scanner — Daily Cron Runner
# Runs the gap scanner at 8:00 AM ET on weekdays
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="$HOME/.hermes/bin:$PATH"

# Load environment from .env if it exists
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

# Required: Finnhub API key
if [ -z "${FINNHUB_API_KEY:-}" ]; then
    echo "ERROR: FINNHUB_API_KEY not set" >&2
    exit 1
fi

# Run the scanner for all indices
cd "$SCRIPT_DIR"
.venv/bin/python scan_gaps.py all 2>&1
