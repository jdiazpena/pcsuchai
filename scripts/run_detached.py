#!/usr/bin/env python3
"""Launch an endurance campaign that survives closing the SSH connection."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    """Record the launch, detach all standard streams, and print monitoring details."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device_label")
    parser.add_argument("hours", type=float, nargs="?", default=24.0)
    parser.add_argument("notes", nargs="?", default="")
    args = parser.parse_args()
    if args.hours <= 0:
        parser.error("hours must be positive")
    root = Path(__file__).resolve().parent.parent
    now = datetime.now(timezone.utc)
    launch = root / "outputs/benchmarks/launches" / now.strftime("%Y/%m/%d/%Y%m%dT%H%M%S.%fZ")
    launch.mkdir(parents=True, exist_ok=False)
    command = [
        sys.executable, str(root / "scripts/run_campaign.py"),
        "--config", "configs/benchmark/endurance.json",
        "--device-label", args.device_label, "--duration-hours", str(args.hours),
        "--notes", args.notes,
    ]
    log_path = launch / "launcher.log"
    with log_path.open("xb") as log:
        child = subprocess.Popen(
            command, cwd=root, stdin=subprocess.DEVNULL, stdout=log,
            stderr=subprocess.STDOUT, start_new_session=True, close_fds=True,
        )
    record = {
        "launched_utc": now.isoformat(), "pid": child.pid,
        "process_group_id": child.pid, "command": command, "log": str(log_path),
    }
    (launch / "launch.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"LAUNCH PID: {child.pid}\nLOG: {log_path}")
    print(f"Monitor: tail -f '{log_path}'")
    print("The log prints SESSION: followed by the timestamped campaign directory.")
    print("Closing SSH does not stop the campaign. Reboot/power loss does; use resume afterward.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
