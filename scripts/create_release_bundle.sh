#!/usr/bin/env bash
# Create one committed public repository archive, including checked cached wheels.
set -Eeuo pipefail
ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec python3 -s "$ROOT_DIR/scripts/create_release_bundle.py" "$@"
