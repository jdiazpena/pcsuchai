#!/usr/bin/env bash
# Create one transferable repository archive, including cached native wheels.
set -Eeuo pipefail
ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
DESTINATION=${1:-"$ROOT_DIR/dist"}
VERSION=$(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')
mkdir -p "$DESTINATION"
ARCHIVE="$DESTINATION/pcsuchai-${VERSION}.tar.gz"
cd "$ROOT_DIR"
tar -czf "$ARCHIVE" \
  --transform "s#^\./#pcsuchai-${VERSION}/#" \
  --exclude='./.git' --exclude='./.pcsuchai-git' \
  --exclude='./.agents' --exclude='./.codex' \
  --exclude='./archive' --exclude='./outputs' --exclude='./dist' \
  --exclude='./.pytest_cache' --exclude='*/__pycache__' --exclude='*.pyc' \
  .
sha256sum "$ARCHIVE" > "$ARCHIVE.sha256"
printf 'Bundle: %s\nChecksum: %s\n' "$ARCHIVE" "$ARCHIVE.sha256"
