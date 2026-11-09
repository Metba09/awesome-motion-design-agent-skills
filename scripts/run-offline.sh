#!/usr/bin/env bash
# Run a command with the network cut (default: make check) and prove the cut first.
# Uses an isolated network namespace; falls back to poisoned proxies if unshare is refused.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "$#" -eq 0 ]; then set -- make check; fi

probe='import socket,sys
try:
    socket.create_connection(("1.1.1.1", 53), timeout=2)
except OSError:
    sys.exit(0)
sys.exit(3)'

if unshare -rn true 2>/dev/null; then
  unshare -rn python3 -c "$probe" || { echo "ERREUR: isolation réseau inefficace" >&2; exit 3; }
  echo "[run-offline] réseau coupé (namespace isolé) : $*"
  exec unshare -rn "$@"
fi
echo "[run-offline] unshare refusé : repli proxy neutralisé (moins strict) : $*" >&2
export HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 ALL_PROXY=http://127.0.0.1:9 NO_PROXY=
exec "$@"
