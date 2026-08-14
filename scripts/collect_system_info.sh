#!/usr/bin/env bash

# Collect non-identifying Raspberry Pi system information needed to choose
# compatible dependencies and interpret performance benchmarks.
#
# This script is intentionally read-only. It does not collect hostnames, IP or
# MAC addresses, Wi-Fi names, device serial numbers, or passwords.

set -u

section() {
    printf '\n## %s\n' "$1"
}

show_file() {
    local path="$1"
    if [[ -r "$path" ]]; then
        tr -d '\0' < "$path"
        printf '\n'
    else
        printf 'unavailable\n'
    fi
}

show_command() {
    if command -v "$1" >/dev/null 2>&1; then
        "$@" 2>&1 || true
    else
        printf '%s: command unavailable\n' "$1"
    fi
}

section "Capture"
printf 'utc_time: '
date -u '+%Y-%m-%dT%H:%M:%SZ'

section "Board"
printf 'model: '
show_file /proc/device-tree/model
printf 'revision: '
awk -F ': *' '/^Revision/ {print $2}' /proc/cpuinfo 2>/dev/null || true

section "Operating system"
show_file /etc/os-release
printf 'kernel: '
uname -srvm
printf 'machine_architecture: '
uname -m
printf 'userspace_bits: '
show_command getconf LONG_BIT
printf 'debian_architecture: '
show_command dpkg --print-architecture
printf 'glibc: '
show_command getconf GNU_LIBC_VERSION

section "CPU"
show_command lscpu
printf 'logical_cpus: '
show_command nproc

CPUFREQ_DIR=/sys/devices/system/cpu/cpu0/cpufreq
for item in scaling_driver scaling_governor scaling_available_governors \
            scaling_cur_freq scaling_min_freq scaling_max_freq \
            cpuinfo_min_freq cpuinfo_max_freq; do
    printf '%s: ' "$item"
    show_file "$CPUFREQ_DIR/$item"
done

section "Memory"
show_command free -b
show_command swapon --show --bytes

section "Storage"
show_command lsblk -o NAME,TYPE,SIZE,ROTA,TRAN
show_command df -B1 /

section "Python"
show_command python3 --version
if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import platform, struct, sys; print("executable:", sys.executable); print("implementation:", platform.python_implementation()); print("python_bits:", 8 * struct.calcsize("P"))' 2>&1 || true
    python3 -m pip --version 2>&1 || printf 'pip: unavailable\n'
fi
section "Thermal and throttling"
printf 'thermal_zone0_millidegrees_c: '
show_file /sys/class/thermal/thermal_zone0/temp
if command -v vcgencmd >/dev/null 2>&1; then
    show_command vcgencmd measure_temp
    show_command vcgencmd get_throttled
    show_command vcgencmd measure_clock arm
else
    printf 'vcgencmd: command unavailable\n'
fi

section "Time configuration"
if command -v timedatectl >/dev/null 2>&1; then
    timedatectl show \
        --property=Timezone \
        --property=NTPSynchronized \
        --property=LocalRTC 2>&1 || true
else
    printf 'timedatectl: command unavailable\n'
fi

section "Network services (no addresses collected)"
if command -v systemctl >/dev/null 2>&1; then
    printf 'NetworkManager: '
    systemctl is-active NetworkManager 2>&1 || true
    printf 'ssh: '
    systemctl is-active ssh 2>&1 || true
fi
