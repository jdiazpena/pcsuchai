# Pi 5: installation, acceptance and first experiments

Run these commands in your existing SSH terminal on the Pi, from `~/pcsuchai`.
They do not create or activate a Python environment. The installer uses system
`/usr/bin/python3`, global installation with `--break-system-packages`, and the
proven ApexPy optional-quadmath build fix. No installer runs on the local PC.
Use only the existing Pi, storage, cooling and supply; no power meter or external
temperature sensor is involved.

## 1. Update and install

```bash
cd ~/pcsuchai
git pull --ff-only origin main
scripts/install_rpi.sh
```

If either command fails, stop and send its final error. Do not reset the
checkout, delete old packages/results, reflash, or start a measured campaign.
The installer verifies only SUCHAI's dependency closure and native imports;
unrelated packages are not repaired. It builds/caches a corrected ApexPy wheel
if a matching architecture/Python-ABI wheel is not already present.

## 2. Foreground acceptance (not a performance benchmark)

```bash
python3 scripts/run_experiment.py run --manifest configs/experiments/acceptance.json --device-label pi5
```

This runs 100 trusted measurement rows through all four orbit/magnetic pairs,
then the complete 26,725-row scientific validation with all 32 configured plot
recipes plus the default maps. It recomputes orbit, native magnetic coordinates
and geographic ground footpoints, preserving every existing filter and raw row.
Require exit zero, root status `complete`, accepted smoke decisions and a passing
fifteen-gate full-data certificate. This is deliberately uncontrolled for
temperature: it checks correctness, not comparable performance.

Save the printed `EXPERIMENT:` path. Send that path and the final command output;
on failure, send the final error instead. Keep all files in that directory.
Local validation does not certify the Pi's native libraries or firmware sensors.

## 3. Short full-data thermal/storage pilot

Create a data protocol outside the frozen source/config tree, without replacing
an existing protocol. This requests one session with two attempts per pair:

```bash
python3 -s - <<'PY'
import json
import os
from pathlib import Path

protocol = json.loads(Path("configs/experiments/equal-work.json").read_text())
protocol["name"] = "full-data-pilot-v1"
protocol["sessions"] = 1
protocol["execution"]["stop"]["value"] = 2
destination = Path("outputs/protocols/full-data-pilot-v1.json")
destination.parent.mkdir(parents=True, exist_ok=True)
with destination.open("x") as stream:
    json.dump(protocol, stream, indent=2)
    stream.write("\n")
    stream.flush()
    os.fsync(stream.fileno())
print(destination)
PY
python3 scripts/run_experiment.py run --manifest outputs/protocols/full-data-pilot-v1.json --device-label pi5
```

Eight measured attempts and four separate pair warm-ups are scheduled, using
full data/full plots and the proposed thermal gate. This is a pilot, not a
precision comparison. A gate timeout/missing sensor is useful diagnostic
evidence, not permission to disable the gate and call the result controlled.
After actual exit, replace `PILOT_DIRECTORY` with its printed experiment path:

```bash
python3 scripts/run_experiment.py report PILOT_DIRECTORY --output outputs/reports/pi5-pilot-v1
```

Review the complete idle/recovery/board traces, cadence/gaps, achieved starting
temperature/slope, effective threading, full-job times and allocated/free
storage. Freeze revised gate/count/headroom choices only from those observations;
reports do not choose an invented safety reserve or guarantee that one job fits.
Keep the same calibrated intended protocol for subsequent comparisons and
record each board's sensor resolution and unavoidable runtime differences.
Do not update code/dependencies between a frozen pilot and its measured series.

## 4. Equal work across devices

After acceptance and review of a short thermal/storage pilot:

```bash
python3 scripts/run_experiment.py run --manifest configs/experiments/equal-work.json --device-label pi5 --detach
```

The default is three independent sessions, ten scheduled attempts per pair per
session: 30 per pair, 120 measured attempts overall. Failed/interrupted attempts
consume slots; these are not targets of 120 successes. Warm-ups are separate,
and no automatic retry occurs. Every attempt processes the complete pipeline.
It waits for stable starting temperature and recovers between attempts.

The proposed gate uses each Pi's built-in SoC sensor: within 2°C of its session
idle baseline, absolute slope at most 0.2°C/min, stable for 60 seconds. These are
starting defaults, **not a calibrated guarantee**. Inspect each board's pilot
traces and storage growth, then freeze the same intended workload/protocol for
comparison. A missing sensor or recovery timeout stops/skips work explicitly;
it never silently becomes a thermally controlled measurement.

Use the same source, workload and frozen manifest on all four boards, changing
only the device label (`pi5`, `pi4`, `pi-zero-2-w`, `pi-zero-w`). Record unavoidable
ARMv6/32-bit package differences rather than calling this isolated silicon speed.
Zero W installation and counter capabilities remain to be demonstrated.

## 5. Four-hour continuous test

Do not overlap this with another experiment on the same Pi. After acceptance
and pilot review, the existing manifest needs no edit:

```bash
python3 scripts/run_experiment.py run --manifest configs/experiments/sustained.json --device-label pi5 --detach
```

It selects **Astropy/ApexPy only**, full data/full plots, fresh worker processes,
and 14,400 seconds of continuous measured work. Validation, initial recovery
and warm-up precede the duration clock. There is no cooldown between jobs;
the active job finishes after the deadline, so total command time can exceed
four hours. The 80°C campaign stop and firmware protection remain enabled;
a thermal/storage/failure stop can end it early. Four hours alone does not
prove a plateau or memory stability.

For the separate long-lived-worker test, after recovery:

```bash
python3 scripts/run_experiment.py run --manifest configs/experiments/persistent.json --device-label pi5 --detach
```

This also selects Astropy/ApexPy for four hours but keeps one worker alive per
block/segment. Each iteration recomputes inputs, orbit, magnetic conversion,
footpoints and plots; it does not reuse calculated science. Fresh and persistent
tests answer different questions and have distinct retained identities.

For another pair or stopping rule, copy a manifest **before launch**, preferably
under `outputs/protocols/`, and record that named variant. Do not edit/resume an
existing experiment into different work. `duration_per_pair_seconds` means the
duration applies to each selected pair; selecting four pairs would request
four hours per pair, not four hours overall.

## 6. Disconnect, inspect, stop or resume

Detached work runs on the Pi and continues after closing SSH. It does not stay
running through a reboot. Replace `EXPERIMENT_DIRECTORY` with the exact printed
path, including its timestamp:

```bash
python3 scripts/run_experiment.py status EXPERIMENT_DIRECTORY
python3 scripts/run_experiment.py stop EXPERIMENT_DIRECTORY
python3 scripts/run_experiment.py resume EXPERIMENT_DIRECTORY --detach
```

`stop` requests a graceful end after the active job. Use `status` to verify the
actual process has exited before reporting/transferring or running another job.
Never delete a lock to bypass it. A readiness observation timeout is not a
failed experiment: inspect its printed handle/log instead of launching a copy.
Resume preserves original records and fixed-attempt accounting. Abruptly ended
timed work with an unknowable remaining budget is recovered, not silently
extended. Completed experiments cannot be resumed into additional attempts.

## 7. Counters, scaling and observation overhead

These are separate full-pipeline experiments, not concurrent profilers of a
primary timing job. After pilots and recovery, run one at a time:

```bash
python3 scripts/run_experiment.py run --manifest configs/experiments/counters.json --device-label pi5 --detach
python3 scripts/run_experiment.py run --manifest configs/experiments/scaling.json --device-label pi5 --detach
python3 scripts/run_experiment.py run --manifest configs/experiments/overhead.json --device-label pi5 --detach
```

Wait for the verified handle to exit before executing the next line. Counters
use repeated small event groups and record permissions/support/coverage; scaling
uses declared row sizes and minimal/full plots; overhead matches minimal,
normal and detailed observation levels without changing scientific output.
These defaults are experiment budgets, not short smoke checks.

The counter experiment needs the Linux `perf` executable to acquire exposed
events. On the Debian 13 arm64 Pis, its distribution package is
[`linux-perf`](https://packages.debian.org/trixie/linux-perf). If it is absent,
install this software on the Pi **before freezing the pilot/runtime**:

```bash
sudo apt install linux-perf
perf --version
```

This package's existence does not prove compatibility or PMU access on your
specific Pi kernel. The experiment probes actual events. Stop and send the error
if package installation/execution fails; do not use a Debian ARMv7 binary on the
ARMv6 Zero W or assume arm64 results apply there. The benchmark does not change
security settings or run the whole pipeline as root to obtain counters.
Denied/unsupported events retain their actual reasons; permission changes would
be a separately authorized, recorded OS configuration, not a hidden workaround.

## 8. Keep and transfer every raw record

Each experiment has a fresh UTC/device/year/month/day directory under
`outputs/benchmarks/`. It retains raw telemetry, arrays, plot masks/images,
source/input snapshots, logs, attempts, warm-ups, failures and partial records.
Raw streams use verified gzip and arrays use NPZ; summaries never replace them.
Content sharing does not remove access to any attempt's data. No pruning policy
is enabled. Free-space checks do not guarantee that one large job fits: the pilot
must establish headroom, including temporary compression/export space.

After the verified process exits, export to a **new**, non-existing archive
outside the experiment (use a distinct timestamped name for each export):

```bash
python3 scripts/run_experiment.py export EXPERIMENT_DIRECTORY --output outputs/pi5-first-test.tar.gz
```

Save its printed SHA-256. Transfer that archive and digest to the analysis PC.
There, replace `TRANSFER_SHA256` with the actual digest and use new destinations:

```bash
python3 scripts/run_experiment.py import outputs/pi5-first-test.tar.gz outputs/imported-pi5-first-test --sha256 TRANSFER_SHA256
python3 scripts/run_experiment.py verify-import outputs/imported-pi5-first-test --images
python3 scripts/run_experiment.py report outputs/imported-pi5-first-test --output outputs/reports/pi5-first-test
```

Export/import preserves original bytes, including failed/partial files; report
commands reconstruct analysis from them without rerunning science. Byte/image
verification is not cross-device numerical acceptance. Automatic operation-cost
receipts remain separate from worker latency; see
[whole-operation costs](whole-operation-costs.md).
Master receipts live in the experiment parent's `operation-costs/`, and export
receipts live beside the archive under `operation-costs/`. They are not inside
the immutable science payload (an archive cannot include its own later export
cost). Preserve and transfer those actual receipt directories alongside the
science archive if analyzing complete operating costs; copying only the science
archive does not transfer these separate records.

## Remaining target evidence

Acceptance on every Pi, actual sensor/clock and supported-counter observations,
pilot-calibrated thermal/storage protocols, independent equal-work sessions,
matched instrumentation overhead, scaling and longer fresh/persistent tests
must still be acquired on the boards. Missing/denied counters remain unavailable,
never zero; basic software timing does not require them. No actual electrical
power/energy measurement is claimed. The
[completion plan](benchmark-completion-plan.md) remains the full contract.
