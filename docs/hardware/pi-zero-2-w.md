# Raspberry Pi Zero 2 W inventory

Captured on 2026-08-14 before installation of the SUCHAI-1 analysis software.

## Summary

| Property | Value |
|---|---|
| Board | Raspberry Pi Zero 2 W Rev 1.0 |
| Operating system | Debian GNU/Linux 13.5 (Trixie) |
| Kernel | Linux 6.18.34+rpt-rpi-v8, aarch64 |
| Userspace | 64-bit, `arm64` |
| Python | CPython 3.13.5 |
| CPU | 4 × ARM Cortex-A53, 600–1000 MHz |
| Frequency boost | Disabled |
| CPU governor | `ondemand` |
| Memory | 415 MiB total, 263 MiB available at capture |
| Swap | 414 MiB total, effectively unused at capture |
| Root storage | 29 GiB total, 26 GiB available at capture |
| Temperature | 37.0 °C |
| Throttling | `0x0` (none reported) |

## Experimental conditions still required

- Power-supply model and rated output.
- Cooling configuration.
- MicroSD make and model.
- Network mode used during benchmarks.

## Raw capture

```text
Raspberry Pi Zero 2 W Rev 1.0
PRETTY_NAME="Debian GNU/Linux 13 (trixie)"
NAME="Debian GNU/Linux"
VERSION_ID="13"
VERSION="13 (trixie)"
VERSION_CODENAME=trixie
DEBIAN_VERSION_FULL=13.5
ID=debian
Linux 6.18.34+rpt-rpi-v8 #1 SMP PREEMPT Debian 1:6.18.34-1+rpt1 (2026-06-09) aarch64
userspace_bits=64
debian_architecture=arm64
Python 3.13.5
Architecture: aarch64
CPU op-mode(s): 32-bit, 64-bit
Byte Order: Little Endian
CPU(s): 4
Model name: Cortex-A53
Thread(s) per core: 1
Core(s) per cluster: 4
Frequency boost: disabled
CPU max MHz: 1000.0000
CPU min MHz: 600.0000
L1d: 128 KiB (4 instances)
L1i: 128 KiB (4 instances)
L2: 512 KiB (1 instance)
Memory total: 415 MiB
Memory used: 151 MiB
Memory available: 263 MiB
Swap total: 414 MiB
Swap used: 92 KiB
Root filesystem: 29 GiB
Root filesystem used: 2.3 GiB
Root filesystem available: 26 GiB
Temperature: 37.0 °C
Throttled: 0x0
CPU governor: ondemand
```
