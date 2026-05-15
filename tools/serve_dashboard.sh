#!/usr/bin/env bash
# Serve the static dashboard on localhost.
#
# Pre-condition: `scripts/build_dashboard.py` already ran (or set --dir).
#
# Usage:
#   tools/serve_dashboard.sh                  # serve ./dashboard on :8080
#   tools/serve_dashboard.sh 9000             # on :9000
#   tools/serve_dashboard.sh 8080 ./public    # custom dir

set -u

PORT="${1:-8080}"
DIR="${2:-dashboard}"

if [ ! -d "$DIR" ]; then
  echo "ERROR: '$DIR' does not exist. Run first:" >&2
  echo "  scripts/build_dashboard.py --output $DIR" >&2
  exit 1
fi

if [ ! -f "$DIR/index.html" ]; then
  echo "ERROR: '$DIR/index.html' not found. Rebuild with:" >&2
  echo "  scripts/build_dashboard.py --output $DIR" >&2
  exit 1
fi

echo "==> Serving $DIR on http://localhost:$PORT"
echo "    Open: http://localhost:$PORT/"
echo "    Stop: Ctrl-C"
echo ""
cd "$DIR"
exec python3 -m http.server "$PORT"
