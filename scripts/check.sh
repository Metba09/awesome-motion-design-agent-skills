#!/usr/bin/env bash
# Full gate to run by hand before concluding. Offline, no input. Runs every step, then summarises.
set -uo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
fail=0; summary=()

step() {  # step "label" cmd...
  local label="$1"; shift
  if out=$("$@" 2>&1); then
    summary+=("  OK   $label")
  else
    summary+=("  FAIL $label"); fail=1
    printf '%s\n' "$out" | sed 's/^/       | /' | head -25
  fi
}

step "validate (frontmatter, JSON, public-safety)" "$PY" scripts/validate-repo.py
step "lint (python, shell, markdown, whitespace)"   "$PY" scripts/lint-docs.py
step "links (local files and anchors)"              "$PY" scripts/check-links.py
step "media jobs match the schema"                  "$PY" scripts/validate-json.py
step "invalid fixtures are rejected"                "$PY" scripts/validate-json.py --expect-invalid tests/fixtures/invalid/*.json
step "skill packages (payloads)"                    "$PY" scripts/verify-skill-packages.py
step "offline guard (no network in the tooling)"    "$PY" scripts/offline-guard.py
step "unit tests"                                   "$PY" -m unittest discover -s tests -p 'test_*.py'
if [ -f MANIFEST.sha256 ]; then
  if "$PY" scripts/snapshot.py verify >/dev/null 2>&1; then summary+=("  OK   snapshot integrity")
  else summary+=("  info snapshot differs from MANIFEST.sha256 (expected if you edited files: make snapshot)"); fi
fi

echo "== check =="; printf '%s\n' "${summary[@]}"
if [ "$fail" -eq 0 ]; then echo "RESULT: all green"; else echo "RESULT: failures above"; fi
exit "$fail"
