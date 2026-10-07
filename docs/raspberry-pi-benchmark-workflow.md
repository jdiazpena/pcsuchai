# Raspberry Pi benchmark workflow

This is the canonical operator sequence for the SUCHAI-1 post-processing
benchmark. Run the same stages, in this order, on the Pi 5, Pi 4, Pi Zero 2 W
and Pi Zero W. A result from one board never certifies another board.

The local `commands_for_joaquin.md` file is an operator clipboard. It is ignored
by Git and contains only the next command Joaquín should copy. It is not part of
the reproducible protocol or public documentation.

## Devices and labels

| Order | Device | Benchmark label | Architecture | Current status |
|---:|---|---|---|---|
| 1 | Raspberry Pi 5 | `pi5` | 64-bit `aarch64` | Acceptance and both operation logs independently verified; pilot pending |
| 2 | Raspberry Pi 4 | `pi4` | 64-bit `aarch64` | Pending |
| 3 | Raspberry Pi Zero 2 W | `pi-zero-2-w` | 64-bit `aarch64` | Pending |
| 4 | Raspberry Pi Zero W | `pi-zero-w` | 32-bit `armv6l` | Installation and acceptance unproven |

Use the exact label shown above for every command on that device. Do not merge
results produced by different source, input, package or protocol identities.

## Rules that apply to every stage

- Use the Pi's system `/usr/bin/python3`; do not create/activate an environment
  and do not install with `pip --user`.
- Run one benchmark operation at a time on a board. Do not delete/bypass its
  lock or run another load concurrently.
- Use only the existing board, storage, cooling, supply and built-in SoC sensor.
  No power meter, external sensor or new hardware is required or claimed.
- Never debug or edit scientific code on a Pi. Stop on a scientific failure,
  preserve its files and reproduce/fix it on the local PC first. Pi-specific
  dependency installation may be diagnosed on the Pi.
- Never delete an old result to reuse a name. Every experiment, report and
  archive has a new identity. Failed, partial and warm-up records are evidence.
- Keep the complete terminal output and every printed `EXPERIMENT:`, receipt,
  archive and SHA-256 identity.

## Stage 1 — Update and install

Run each command separately from the Pi's SSH terminal:

```bash
cd ~/pcsuchai
git pull --ff-only origin main
git rev-parse HEAD
bash scripts/install_rpi.sh
```

Stop if a command fails. Do not reset/reflash/delete packages or results. The
installer invokes `sudo` itself, installs pinned dependencies globally, builds
or reuses an architecture/Python-tag-specific corrected ApexPy wheel, installs
PCS SUCHAI, and verifies the dependency closure, native imports and an ApexPy
round trip. It retains a dated `installation-reports/` directory.

Acceptance of this stage requires the installer to finish successfully. A
successful AArch64 build is not evidence that the ARMv6 Pi Zero W will build.

## Stage 2 — Foreground scientific acceptance

Replace `DEVICE_LABEL` with the board's exact label:

```bash
python3 scripts/run_experiment.py run --manifest configs/experiments/acceptance.json --device-label DEVICE_LABEL
```

Keep SSH open. This is a correctness gate, not a performance campaign. It runs
all four orbit/magnetic combinations on 100 rows and then runs complete 26,725-
row validation with every configured plot/filter. It recomputes TLE selection,
orbit, native AACGMv2/ApexPy coordinates, geographic footpoints and all products.

Acceptance requires all of the following:

- command exit zero and root status `complete`;
- 4 scheduled, 4 started and 4 scientifically valid attempts;
- zero failed, interrupted, automatically retried and skipped attempts;
- a passing 15-criterion full-validation certificate;
- all four retained backend-pair artifact checks passing.

Save the exact printed `EXPERIMENT:` path. Do not start performance work after a
partial or failed acceptance.

## Stage 3 — Export and transfer acceptance evidence

After the acceptance process has exited, replace the two placeholders:

```bash
python3 scripts/run_experiment.py export EXPERIMENT_DIRECTORY --output /home/pi/pcsuchai/outputs/DEVICE_LABEL-acceptance-YYYYMMDD.tar.gz
```

Export writes a new verified archive and prints its SHA-256. It contains every
original experiment byte: raw arrays, telemetry, source/input snapshots, logs,
plot masks/images, warm-ups, failures and partial records—not only summaries.
It does not delete or rewrite the experiment.

From the computer that can SSH to the Pi, copy both the archive and the relevant
adjacent `operation-costs/` directories. An archive cannot contain the cost of
creating itself, so operation receipts remain separate. Example archive copy:

```bash
scp pi@PI_HOST:/home/pi/pcsuchai/outputs/DEVICE_LABEL-acceptance-YYYYMMDD.tar.gz .
```

Place the archive in the local `pcsuchai/outputs/` directory. From the local
repository, use a new import directory and the exact printed digest:

```bash
python3 scripts/run_experiment.py import outputs/DEVICE_LABEL-acceptance-YYYYMMDD.tar.gz outputs/imported-DEVICE_LABEL-acceptance-YYYYMMDD --sha256 TRANSFER_SHA256
python3 scripts/run_experiment.py verify-import outputs/imported-DEVICE_LABEL-acceptance-YYYYMMDD --images
python3 scripts/run_experiment.py report outputs/imported-DEVICE_LABEL-acceptance-YYYYMMDD --output outputs/reports/DEVICE_LABEL-acceptance-YYYYMMDD
```

Import must verify every original byte and image. We then inspect the recorded
source/runtime/dependency identity and compare same-backend numerical products.
Transfer verification is not itself scientific or hardware acceptance.

## Stage 4 — Full-data thermal and storage pilot

Only after acceptance/import review, create one immutable pilot protocol from
the public equal-work manifest. The detailed, copy-ready creation command is in
[Pi 5 handoff](pi5-handoff.md#3-short-full-data-thermalstorage-pilot); use the
same protocol content on every board and change only the device label.

The pilot schedules one session with two measured attempts per pair: eight
measured attempts plus four separate pair warm-ups. It uses full data/full plots
and the proposed built-in-sensor gate. It is not a precision comparison.

Review before proceeding:

- complete idle/recovery/board temperature traces and sensor availability;
- observed cadence/gaps, start temperature and temperature slope;
- throttling transitions, requested/observed frequency and effective threads;
- full-job time, memory/swap/pressure and open-resource trends;
- logical/newly allocated bytes, compression cost and remaining bytes/inodes;
- whether the proposed recovery timeout/gate actually works on that board.

Freeze thermal thresholds, counts and storage headroom from acquired evidence.
Never disable a failed gate and rename the result controlled. Record an
unavailable sensor/clock/counter as unavailable, not zero.

## Stage 5 — Equal-work comparison

After all boards have passed acceptance and their pilots have been reviewed,
freeze one shared intended protocol. Then run on each board:

```bash
python3 scripts/run_experiment.py run --manifest configs/experiments/equal-work.json --device-label DEVICE_LABEL --detach
```

The default schedules three independent sessions and ten attempts per pair per
session: 30 attempts per pair and 120 measured attempts total. Attempts—not
successes—are the denominator; failed/interrupted work consumes a slot. Warm-ups
are separate and automatic retries are disabled. Recovery occurs between
attempts and pair order is balanced.

Do not compare these results until source/input/protocol identities and intended
controls agree. Differences forced by ARMv6/32-bit software remain explicit;
the result compares board-plus-software systems, not isolated silicon.

## Stage 6 — Scaling, observation overhead and counters

Run these as separate experiments, one at a time, with recovery between them:

```bash
python3 scripts/run_experiment.py run --manifest configs/experiments/scaling.json --device-label DEVICE_LABEL --detach
python3 scripts/run_experiment.py run --manifest configs/experiments/overhead.json --device-label DEVICE_LABEL --detach
python3 scripts/run_experiment.py run --manifest configs/experiments/counters.json --device-label DEVICE_LABEL --detach
```

Wait for one verified handle to exit before starting the next. Scaling compares
declared row counts and minimal/full plotting. Overhead compares matched minimal,
normal and detailed observation. Counter runs use repeated small event groups.
`perf` support, permissions, enabled/running coverage and event scope must be
recorded per board. Do not change security settings or run the pipeline as root
merely to force counters; denied/unsupported events remain valid evidence.

## Stage 7 — Sustained and persistent four-hour blocks

After pilot review, run the fresh-process block:

```bash
python3 scripts/run_experiment.py run --manifest configs/experiments/sustained.json --device-label DEVICE_LABEL --detach
```

After it exits and the board recovers, run the long-lived-worker block:

```bash
python3 scripts/run_experiment.py run --manifest configs/experiments/persistent.json --device-label DEVICE_LABEL --detach
```

Each manifest selects Astropy/ApexPy, full data/full plots and 14,400 measured
seconds. Validation, initial recovery and warm-up occur before the duration
clock. The active job finishes after the deadline, so total wall time can exceed
four hours. No cooldown occurs between jobs within a block. The fresh and
persistent variants answer different questions; each iteration still recomputes
the complete scientific chain.

Four hours does not by itself prove a temperature plateau or memory stability.
A thermal/storage/failure threshold can stop a block early; stopped work cannot
be reported as a completed four-hour result.

## Detached controls

Detached work continues after SSH closes, but not through a reboot. Replace the
placeholder with the exact experiment directory:

```bash
python3 scripts/run_experiment.py status EXPERIMENT_DIRECTORY
python3 scripts/run_experiment.py stop EXPERIMENT_DIRECTORY
python3 scripts/run_experiment.py resume EXPERIMENT_DIRECTORY --detach
```

`stop` finishes the active job and prevents another. Verify actual exit before
transfer or another experiment. Resume preserves fixed-attempt accounting and
original bytes; completed work cannot be resumed into extra attempts. Abruptly
ended timed work with unknowable remaining duration is recovered, not extended.

## Stage 8 — Reports and cross-device decision

Export/import/verify every experiment as in Stage 3, preserving separate
operation receipts. Reconstruct reports only from retained raw records. Include
failures, interruptions, exclusions and unavailable measurements in their real
denominators. Compare same scientific backends across devices under frozen
tolerances; AACGMv2 and ApexPy are different magnetic models and are not expected
to produce equal coordinates.

Required reporting includes latency/full-cycle/stage contribution, valid
throughput, independent-session uncertainty, temperature/frequency/throttling,
fresh/persistent resource trends, counter quality, observation overhead,
scaling/output size, compression/physical storage and cross-device numerical
decisions. Do not infer electrical power/energy or absolute magnetic/orbit truth.

## Evidence ledger

Update this table only from retained output or transferred artifacts.

| Device | Install | Acceptance | Export/import | Pilot | Equal work | Scaling/overhead/counters | Sustained/persistent |
|---|---|---|---|---|---|---|---|
| Pi 5 | Reported successful | **Passed 2026-10-07**: 4/4 valid, 0 failures; 15-criterion certificate passed; 39.7–40.25°C during smoke jobs | **Passed 2026-10-07**: both archive checksums matched; all 443 experiment files/196,189,884 logical bytes and 152 images independently verified; report reconstructed 4/4 accepted attempts; both master/export operation logs validated and matched to this experiment | Pending | Pending | Pending | Pending |
| Pi 4 | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| Pi Zero 2 W | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| Pi Zero W | Pending | Pending | Pending | Pending | Pending | Pending | Pending |

Pi 5 acceptance evidence above comes from independently verified archives
transferred by the operator, retaining the original experiment path
`/home/pi/pcsuchai/outputs/benchmarks/pi5/2026/10/07/20261007T150704.396363Z-acceptance`.
The Pi produced the acceptance archive in 10.751 seconds. Independent import
confirmed source fingerprint
`dbd3abe44b776c5e1d77b61abd59cf083ea5343c64c26aec55e298ae8b34a5b1`
(120 files), system Python 3.13.5 on AArch64, the pinned dependency versions,
all 15 certificate criteria, all 443 retained files and all 152 images from
eight pipeline manifests. ApexPy 2.1.1 passed all seven frozen upstream
numerical anchors and five production bridge cases. This completes Pi 5
functional acceptance; it is not a performance comparison, thermal pilot,
absolute physical-truth claim or evidence for another board.

The separate operation-log archive has SHA-256
`b095a281cd12ab3daa149a003fc91185dd4b6a462ffc683840d5b21a3814a1bd`.
Its two logs passed the saved-cost audit with zero invalid, unfinished or failed
operations. The master log matches the experiment path and canonical manifest
hash; the export log matches the transferred science archive's hash, file count
and sizes. The master command took 169.125830 seconds, with 153.593448 seconds
of parent-process CPU time. The export API took 10.761194 seconds, with
8.760326 seconds of parent-process CPU time. These containing timings are
retained separately and are not added to individual scientific-job timings.
All acceptance evidence requested for Stage 3 is now transferred and verified.

The full scientific/statistical acceptance contract remains
[benchmark-completion-plan.md](benchmark-completion-plan.md). This workflow is
the execution order; it does not reduce any of that plan's completion gates.
