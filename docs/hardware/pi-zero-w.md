# Raspberry Pi Zero W inventory

Captured on 2026-08-14 before installation of the SUCHAI-1 analysis software.

## Summary

| Property | Value |
|---|---|
| Board | Raspberry Pi Zero W Rev 1.1 |
| Operating system | Raspbian GNU/Linux 13.4 (Trixie) |
| Kernel | Linux 6.18.34+rpt-rpi-v6, ARMv6 |
| Userspace | 32-bit, `armhf` |
| Python | CPython 3.13.5 |
| CPU | 1 × ARMv6-compatible processor, 700–1000 MHz |
| Frequency boost | Disabled |
| CPU governor | `ondemand` |
| Memory | 426 MiB total, 310 MiB available at capture |
| Swap | 425 MiB total, unused at capture |
| Root storage | 15 GiB total, 12 GiB available at capture |
| Temperature | 33.6 °C |
| Throttling | `0x0` (none reported) |

## Compatibility significance

This is the strictest target in the hardware matrix because it combines a
single ARMv6 core, 32-bit userspace, approximately 426 MiB of usable memory,
and Python 3.13. Package wheel availability, source-build memory requirements,
installation time, import time, and swap activity must be tested explicitly.

## Experimental conditions still required

- Power-supply model and rated output.
- Cooling configuration.
- MicroSD make and model.
- Network mode used during benchmarks.

## Raw capture

```text
Raspberry Pi Zero W Rev 1.1
PRETTY_NAME="Raspbian GNU/Linux 13 (trixie)"
NAME="Raspbian GNU/Linux"
VERSION_ID="13"
VERSION="13 (trixie)"
VERSION_CODENAME=trixie
DEBIAN_VERSION_FULL=13.4
ID=raspbian
ID_LIKE=debian
Linux 6.18.34+rpt-rpi-v6 #1 Raspbian 1:6.18.34-1+rpt1 (2026-06-09) armv6l
userspace_bits=32
debian_architecture=armhf
Python 3.13.5
Architecture: armv6l
Byte Order: Little Endian
CPU(s): 1
Model name: ARMv6-compatible processor rev 7 (v6l)
Thread(s) per core: 1
Core(s) per socket: 1
Frequency boost: disabled
CPU max MHz: 1000.0000
CPU min MHz: 700.0000
Memory total: 426 MiB
Memory used: 116 MiB
Memory available: 310 MiB
Swap total: 425 MiB
Swap used: 0 B
Root filesystem: 15 GiB
Root filesystem used: 2.1 GiB
Root filesystem available: 12 GiB
Temperature: 33.6 °C
Throttled: 0x0
CPU governor: ondemand
```
