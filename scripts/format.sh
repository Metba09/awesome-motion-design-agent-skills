#!/usr/bin/env bash
# Explicit format (replaces any hook): mechanical fixes only (trailing whitespace, final newline).
# Usage: scripts/format.sh [--check]
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "${1:-}" = "--check" ]; then exec python3 scripts/lint-docs.py; fi
python3 scripts/lint-docs.py --fix
