# Raspberry Pi 4 inventory

Captured on 2026-08-14 before installation of the SUCHAI-1 analysis software.

## Summary

| Property | Value |
|---|---|
| Board | Raspberry Pi 4 Model B Rev 1.5 |
| Operating system | Debian GNU/Linux 13.5 (Trixie) |
| Kernel | Linux 6.18.34+rpt-rpi-v8, aarch64 |
| Userspace | 64-bit, `arm64` |
| Python | CPython 3.13.5 |
| CPU | 4 × ARM Cortex-A72, 600–1800 MHz |
| Frequency boost | Disabled |
| CPU governor | `ondemand` |
| Memory | 1.8 GiB total, 1.6 GiB available at capture |
| Swap | 1.8 GiB total, unused at capture |
| Root storage | 29 GiB total, 24 GiB available at capture |
| Temperature | 43.8 °C |
| Throttling | `0x0` (none reported) |

## Experimental conditions still required

- Power-supply model and rated output.
- Cooling configuration.
- MicroSD make and model.
- Network mode used during benchmarks.

## Raw capture

```text
Raspberry Pi 4 Model B Rev 1.5
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
Model name: Cortex-A72
Thread(s) per core: 1
Core(s) per cluster: 4
Frequency boost: disabled
CPU max MHz: 1800.0000
CPU min MHz: 600.0000
L1d: 128 KiB (4 instances)
L1i: 192 KiB (4 instances)
L2: 1 MiB (1 instance)
Memory total: 1.8 GiB
Memory used: 161 MiB
Memory available: 1.6 GiB
Swap total: 1.8 GiB
Swap used: 0 B
Root filesystem: 29 GiB
Root filesystem used: 3.7 GiB
Root filesystem available: 24 GiB
Temperature: 43.8 °C
Throttled: 0x0
CPU governor: ondemand
```
