"""Documented firmware bit identities; no power or voltage measurement inferred."""

from __future__ import annotations

import re


FLAG_DOCUMENTATION = "https://www.raspberrypi.com/documentation/computers/os.html#get_throttled"
CURRENT_FLAGS = {0: "undervoltage_detected", 1: "arm_frequency_capped",
                 2: "currently_throttled", 3: "soft_temperature_limit_active"}
HISTORICAL_FLAGS = {bit + 16: name for bit, name in CURRENT_FLAGS.items()}
KNOWN_FLAG_MASK = sum(1 << bit for bit in (*CURRENT_FLAGS, *HISTORICAL_FLAGS))


def parse_throttling_mask(value) -> int:
    """Accept a uint32 integer or explicit hexadecimal mask, never bool/float.

    Unknown bits are retained, not interpreted as documented events. Parsing
    does not establish a firmware source, availability or acquisition time.
    """

    if isinstance(value, str) and re.fullmatch(r"0[xX][0-9a-fA-F]{1,8}", value.strip()):
        value = int(value.strip(), 16)
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("throttling mask must be a uint32 or explicit hexadecimal mask")
    return value


def decode_throttling_mask(value) -> dict:
    """Separate sampled current states from historical conditions and unknowns."""

    mask = parse_throttling_mask(value)
    return {"mask": mask, "hex": hex(mask),
            "current": {name: bool(mask & (1 << bit)) for bit, name in CURRENT_FLAGS.items()},
            "historical": {name: bool(mask & (1 << bit)) for bit, name in HISTORICAL_FLAGS.items()},
            "unknown_bits_hex": hex(mask & ~KNOWN_FLAG_MASK), "documentation": FLAG_DOCUMENTATION,
            "limit": "sampled firmware flags, not watts/energy/measured voltage or a unique throttling cause"}
