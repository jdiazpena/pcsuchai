#!/usr/bin/env bash
# Mandatory complete-code validation gate before official Raspberry Pi campaigns.
set -Eeuo pipefail
ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if (($# < 1)); then printf 'Usage: %s DEVICE_LABEL [LIMIT]\n' "$0" >&2; exit 2; fi
LABEL=$(printf '%s' "$1" | tr -cs 'A-Za-z0-9_.-' '-')
STAMP=$(date -u '+%Y%m%dT%H%M%SZ')
DESTINATION="$ROOT_DIR/outputs/validations/${LABEL}/${STAMP}"
export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
COMMAND=(python3 -m pcsuchai validate-full --project-root "$ROOT_DIR" --output-dir "$DESTINATION")
if (($# >= 2)); then COMMAND+=(--limit "$2"); fi
mkdir -p "$DESTINATION"
"${COMMAND[@]}" 2>&1 | tee "$DESTINATION/validation.log"
printf 'Full-code validation complete: %s\n' "$DESTINATION"
