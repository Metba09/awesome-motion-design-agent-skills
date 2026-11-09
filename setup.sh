#!/usr/bin/env bash
# Idempotent, non-interactive, offline setup. Safe to re-run: the sandbox restarts from zero each session.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
PY="${PYTHON:-python3}"
say() { printf '[setup] %s\n' "$*"; }

"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
  || { echo "[setup] ERREUR: Python 3.9+ requis" >&2; exit 1; }
say "python $("$PY" -c 'import platform; print(platform.python_version())')"

# Python dependencies: none today (stdlib only). If some are declared later they must come from vendor/wheels.
if grep -qvE '^[[:space:]]*(#|$)' requirements.txt 2>/dev/null; then
  [ -d vendor/wheels ] || { echo "[setup] ERREUR: requirements.txt déclare des dépendances mais vendor/wheels est absent" >&2; exit 1; }
  "$PY" -m pip install --break-system-packages --no-index --find-links vendor/wheels -r requirements.txt
else
  say "dépendances Python tierces : aucune (bibliothèque standard uniquement)"
fi

# Node dependencies: none today. If a lockfile appears, install only from a local cache.
if [ -f package-lock.json ]; then
  [ -d vendor/npm-cache ] || { echo "[setup] ERREUR: lockfile présent mais vendor/npm-cache est absent" >&2; exit 1; }
  npm ci --offline --ignore-scripts --cache vendor/npm-cache
else
  say "dépendances Node : aucune (pas de package-lock.json)"
fi

if [ -f .env ]; then say ".env déjà présent (conservé)"; else cp .env.example .env; say ".env créé depuis .env.example (mode mock)"; fi
mkdir -p dist out
chmod +x setup.sh scripts/*.py scripts/*.sh 2>/dev/null || true

if [ -f MANIFEST.sha256 ]; then
  "$PY" scripts/snapshot.py verify || say "AVERTISSEMENT: le contenu diffère du snapshot (fichiers modifiés depuis la création du bundle)"
fi
say "OK. Étape suivante : make check"
