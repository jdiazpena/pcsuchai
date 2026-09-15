# Raspberry Pi hardware inventory

This document defines the information collected from each Raspberry Pi before
installing the SUCHAI-1 analysis software. The inventory is used to select a
common Python baseline, diagnose package compatibility, and interpret benchmark
results.

The collector is read-only and intentionally excludes passwords, Wi-Fi names,
IP and MAC addresses, hostnames, and device serial numbers.

## Target systems

| Device | Intended OS | Architecture | Inventory captured | Notes |
|---|---|---|---|---|
| Raspberry Pi Zero W | Raspbian 13 Lite | armhf / ARMv6 / 32-bit | Yes | Python 3.13.5; single core; 426 MiB usable RAM |
| Raspberry Pi Zero 2 W | Debian 13 Lite, Raspberry Pi kernel | arm64 / 64-bit | Yes | Python 3.13.5; 415 MiB usable RAM |
| Raspberry Pi 4 | Debian 13 Lite, Raspberry Pi kernel | arm64 / 64-bit | Yes | Python 3.13.5; 1.8 GiB usable RAM |
| Raspberry Pi 5 | Debian 13 Lite, Raspberry Pi kernel | arm64 / 64-bit | Yes | Python 3.13.5; 4.0 GiB usable RAM |

## Collect an inventory

From the repository root on the notebook, copy the collector to a Pi. Replace
the username and address with the values for that Pi:

```powershell
scp scripts/collect_system_info.sh USERNAME@PI_ADDRESS:~/collect_system_info.sh
```

Run it remotely and save the result on the notebook:

```powershell
ssh USERNAME@PI_ADDRESS "bash ~/collect_system_info.sh" |
    Out-File -Encoding utf8 pi-system-info.txt
```

Rename the result for the corresponding device before collecting the next one,
for example `pi-zero-w.txt` or `pi-5.txt`. Review the file before sharing or
committing it.

## Manually recorded experimental conditions

The following details cannot be detected reliably in software and must be
recorded for every benchmark session:

- Power-supply model and rated output.
- Cooling configuration: none, heatsink, passive case, or fan.
- Boot storage make, model, capacity, and interface.
- Attached USB or other peripheral devices.
- Whether Ethernet, Wi-Fi, or no network was active during the run.
- Any intentional overclocking or firmware configuration changes.

## Why these details matter

Operating-system architecture affects Python wheel availability and memory
usage. CPU governors, temperature, cooling, throttling, storage, and background
services can change benchmark results independently of the analysis code.
Capturing them lets us distinguish software performance from environmental
differences.

## Captured inventories

- [Raspberry Pi Zero W](hardware/pi-zero-w.md)
- [Raspberry Pi Zero 2 W](hardware/pi-zero-2-w.md)
- [Raspberry Pi 4](hardware/pi-4.md)
- [Raspberry Pi 5](hardware/pi-5.md)
