#!/usr/bin/env bash
# Explicit lint (replaces any hook): python, shell, markdown, whitespace, JSON. Offline.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/lint-docs.py
python3 scripts/validate-repo.py
