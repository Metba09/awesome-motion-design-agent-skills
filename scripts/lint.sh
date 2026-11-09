#!/usr/bin/env bash
# Explicit lint (replaces any hook): python, shell, markdown, whitespace, JSON. Offline.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/lint-docs.py
python3 scripts/validate-repo.py
python3 -c 'import json,sys; json.load(open("sandbox/BUNDLE.json", encoding="utf-8"))' || { echo "ÉCART : sandbox/BUNDLE.json n'est pas du JSON valide" >&2; exit 1; }
python3 scripts/sandbox/verify_bundle.py
