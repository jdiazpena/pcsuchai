#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if (($# < 1)); then printf 'Usage: %s DEVICE_LABEL [NOTES]\n' "$0" >&2; exit 2; fi
ARGS=(--config configs/benchmark/full-products.json --device-label "$1")
if (($# >= 2)); then ARGS+=(--notes "$2"); fi
exec python3 "$ROOT_DIR/scripts/run_campaign.py" "${ARGS[@]}"
