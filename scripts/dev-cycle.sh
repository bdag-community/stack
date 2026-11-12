#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPOS_DIR="${REPOS_DIR:-$(cd "$ROOT/.." && pwd)}"
BDAGRIG_DIR="${BDAGRIG_DIR:-$REPOS_DIR/bdagrig}"

TARGET_DIR="/opt/bdagrig/releases/dev-local" TARGET="${TARGET:-linux-amd64}" \
  "$ROOT/scripts/sim-release.sh"

echo "Rebuilding bdagrig binary in $BDAGRIG_DIR"
(cd "$BDAGRIG_DIR" && go build -o ./bdagrig ./cmd/bdagrig)

echo "Dev cycle complete"
echo "  release: /opt/bdagrig/releases/dev-local"
echo "  binary:  $BDAGRIG_DIR/bdagrig"
