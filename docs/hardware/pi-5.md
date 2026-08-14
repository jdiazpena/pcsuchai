# Raspberry Pi 5 inventory

Captured on 2026-08-14 before installation of the SUCHAI-1 analysis software.

## Summary

| Property | Value |
|---|---|
| Board | Raspberry Pi 5 Model B Rev 1.0 |
| Operating system | Debian GNU/Linux 13.5 (Trixie) |
| Kernel | Linux 6.18.34+rpt-rpi-2712, aarch64 |
| Userspace | 64-bit, `arm64` |
| Python | CPython 3.13.5 |
| CPU | 4 × ARM Cortex-A76, 1500–2400 MHz |
| Frequency boost | Disabled |
| CPU governor | `ondemand` |
| Memory | 4.0 GiB total, 3.7 GiB available at capture |
| Swap | 2.0 GiB total, unused at capture |
| Root storage | 29 GiB total, 26 GiB available at capture |
| Temperature | 30.7 °C |
| Throttling | `0x0` (none reported) |

## Topology note

The captured `lscpu` output reports eight NUMA nodes that all reference CPUs
0–3. We will preserve this reported topology as environment metadata and avoid
assuming that it represents eight independent memory domains when interpreting
benchmarks.

## Experimental conditions still required

- Power-supply model and rated output.
- Cooling configuration.
- Approximate ambient temperature.
- MicroSD make and model.
- Network mode used during benchmarks.

## Raw capture

```text
Raspberry Pi 5 Model B Rev 1.0
PRETTY_NAME="Debian GNU/Linux 13 (trixie)"
NAME="Debian GNU/Linux"
VERSION_ID="13"
VERSION="13 (trixie)"
VERSION_CODENAME=trixie
DEBIAN_VERSION_FULL=13.5
ID=debian
Linux 6.18.34+rpt-rpi-2712 #1 SMP PREEMPT Debian 1:6.18.34-1+rpt1 (2026-06-09) aarch64
userspace_bits=64
debian_architecture=arm64
Python 3.13.5
Architecture: aarch64
CPU op-mode(s): 32-bit, 64-bit
Byte Order: Little Endian
CPU(s): 4
Model name: Cortex-A76
Thread(s) per core: 1
Core(s) per cluster: 4
Frequency boost: disabled
CPU max MHz: 2400.0000
CPU min MHz: 1500.0000
L1d: 256 KiB (4 instances)
L1i: 256 KiB (4 instances)
L2: 2 MiB (4 instances)
L3: 2 MiB (1 instance)
NUMA nodes reported: 8, each referencing CPUs 0-3
Memory total: 4.0 GiB
Memory used: 253 MiB
Memory available: 3.7 GiB
Swap total: 2.0 GiB
Swap used: 0 B
Root filesystem: 29 GiB
Root filesystem used: 2.1 GiB
Root filesystem available: 26 GiB
Temperature: 30.7 °C
Throttled: 0x0
CPU governor: ondemand
```
