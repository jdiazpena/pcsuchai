#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if (($# != 1)); then
  printf 'Usage: %s SESSION_DIRECTORY\n' "$0" >&2
  exit 2
fi
exec python3 "$ROOT_DIR/scripts/run_campaign.py" --resume-session "$1"
