"""Filesystem measurements and explicitly conditional, non-guaranteed forecasts."""

from __future__ import annotations

import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path


def inventory_storage(root: Path, *, scope: str = "inventoried_filesystem_tree") -> dict:
    """Count file lengths and inode allocation once, without following symlinks.

    Allocation describes this filesystem now, not the original board after an
    export/import. Directory allocation is included; metadata, journal space,
    compression by the filesystem and other concurrent activity are not known.
    Hard-linked names contribute repeatedly to logical bytes but once to blocks.
    """

    logical = allocated = names = directories = links = 0
    inodes = set()
    missing_blocks = False
    for path in _walk(root) if root.is_dir() and not root.is_symlink() else (root,):
        stat = path.lstat()
        if path.is_symlink():
            links += 1
            continue
        if not (path.is_file() or path.is_dir()):
            continue
        if path.is_file():
            logical += stat.st_size
            names += 1
        else:
            directories += 1
        inode = (stat.st_dev, stat.st_ino)
        if inode in inodes:
            continue
        inodes.add(inode)
        blocks = getattr(stat, "st_blocks", None)
        if blocks is None:
            missing_blocks = True
        else:
            allocated += blocks * 512
    return {"captured_utc": datetime.now(timezone.utc).isoformat(),
            "monotonic_seconds": time.monotonic(), "source": "lstat.st_size/st_blocks/st_dev/st_ino",
            "scope": scope, "logical_file_bytes": logical,
            "unique_allocated_bytes": None if missing_blocks else allocated,
            "allocation_status": "unsupported" if missing_blocks else "available",
            "file_names": names, "unique_inodes": len(inodes), "directories": directories,
            "symlinks_not_followed": links,
            "limit": "inode block allocation, including directories; not total filesystem consumption"}


def _walk(root: Path):
    """Traverse a tree incrementally; never enter a symbolic-link directory."""

    yield root
    for directory, names, files in os.walk(root, followlinks=False):
        for name in names + files:
            yield Path(directory) / name


def filesystem_capacity(path: Path) -> dict:
    """Capture available bytes/inodes for the actual retention filesystem."""

    result = {"captured_utc": datetime.now(timezone.utc).isoformat(),
              "monotonic_seconds": time.monotonic(), "source": "os.statvfs/os.stat",
              "scope": "retention_filesystem", "unit": "bytes_and_inodes"}
    try:
        stat, filesystem = path.stat(), os.statvfs(path)
        return {**result, "status": "available", "device_id": stat.st_dev,
                "free_bytes": filesystem.f_bavail * filesystem.f_frsize,
                "free_inodes": filesystem.f_favail, "block_size_bytes": filesystem.f_frsize}
    except (OSError, AttributeError) as exc:
        return {**result, "status": "unavailable", "reason": str(exc),
                "free_bytes": None, "free_inodes": None, "device_id": None}


def _nonnegative(value) -> bool:
    """Reject unknown, boolean, non-finite and negative byte/count observations."""

    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value >= 0
    return isinstance(value, float) and math.isfinite(value) and value >= 0


def forecast_storage(growth_bytes: list, growth_inodes: list, capacity: dict, *,
                     planned_attempts: int | None = None, reserve_bytes: int | None = None) -> dict:
    """Use the largest measured allocation per attempt, with explicit headroom.

    This is a conditional extrapolation, not admission control or a guarantee.
    A staging reserve must be supplied: completed products do not establish peak
    temporary allocation. Unknown growth (including failed/partial jobs) prevents
    a complete forecast. Zero observed growth never implies infinite capacity.
    Capacity must be a saved retention-filesystem observation, not analysis-PC
    free space. Counts include all scheduled jobs, including warmups/failures.
    """

    if planned_attempts is not None and (not isinstance(planned_attempts, int) or isinstance(planned_attempts, bool) or planned_attempts < 0):
        raise ValueError("planned_attempts must be a nonnegative integer")
    if reserve_bytes is not None and (not isinstance(reserve_bytes, int) or isinstance(reserve_bytes, bool) or reserve_bytes < 0):
        raise ValueError("reserve_bytes must be a nonnegative integer")
    known = [value for value in growth_bytes if _nonnegative(value)]
    known_inodes = [value for value in growth_inodes if _nonnegative(value)]
    largest = max(known, default=None)
    largest_inodes = max(known_inodes, default=None)
    result = {"status": "unavailable", "method": "largest_observed_attempt_allocation",
              "pilot_attempts": len(growth_bytes), "known_byte_growth_attempts": len(known),
              "known_inode_growth_attempts": len(known_inodes), "largest_growth_bytes": largest,
              "largest_growth_inodes": largest_inodes, "planned_attempts": planned_attempts,
              "reserve_bytes": reserve_bytes, "capacity_observation": capacity,
              "conditional_attempt_capacity": None, "planned_growth_bytes": None,
              "fits_observed_capacity": None, "guaranteed_to_fit": False,
              "limit": "same declared workload/filesystem; future growth and temporary peak may exceed this pilot; no raw records are pruned"}
    reason = None
    if not growth_bytes or len(growth_inodes) != len(growth_bytes) or len(known) != len(growth_bytes) or len(known_inodes) != len(growth_bytes):
        reason = "missing allocation for one or more pilot attempts"
    elif capacity.get("status") != "available" or not _nonnegative(capacity.get("free_bytes")) or not _nonnegative(capacity.get("free_inodes")):
        reason = "saved retention filesystem capacity unavailable"
    elif reserve_bytes is None:
        reason = "temporary-job and finalization headroom not supplied"
    elif largest == 0 or largest_inodes == 0:
        reason = "zero observed byte/inode growth cannot establish a finite capacity"
    if reason:
        return {**result, "reason": reason}
    budget = max(0, capacity["free_bytes"] - reserve_bytes)
    attempts = min(int(budget // largest), int(capacity["free_inodes"] // largest_inodes))
    return {**result, "status": "conditional_estimate", "conditional_attempt_capacity": attempts,
            "planned_growth_bytes": planned_attempts * largest if planned_attempts is not None else None,
            "fits_observed_capacity": planned_attempts <= attempts if planned_attempts is not None else None}
