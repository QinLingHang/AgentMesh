#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="$(tr -d '\r\n' < "$ROOT/VERSION")"
OUTPUT_DIR="${1:-$(dirname "$ROOT")}" 
mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"

# The development worktree may contain local dependencies/build products/.env files.
# Validate identity/docs first, then stage a sanitized tree and strictly validate the
# exact release payload before archiving it.
python3 "$ROOT/scripts/release/validate-release.py" --root "$ROOT"

NAME="AgentMesh_v${VERSION}_SOURCE.zip"
ARCHIVE="$OUTPUT_DIR/$NAME"
rm -f "$ARCHIVE"

STAGE_PARENT="$(mktemp -d "${TMPDIR:-/tmp}/agentmesh-release.XXXXXX")"
ROOT_LEAF="$(basename "$ROOT")"
STAGE_ROOT="$STAGE_PARENT/$ROOT_LEAF"
cleanup() {
  rm -rf "$STAGE_PARENT"
}
trap cleanup EXIT

python3 "$ROOT/scripts/release/stage-release.py" --source "$ROOT" --dest "$STAGE_ROOT"
python3 "$STAGE_ROOT/scripts/release/validate-release.py" --root "$STAGE_ROOT" --strict-tree

(
  cd "$STAGE_PARENT"
  zip -qr "$ARCHIVE" "$ROOT_LEAF"
)

echo "P12 Release Package: $ARCHIVE"
