# Thermal-stress policy and recovery costs

The controlled baseline and ordinary `sustained.json` keep their declared
software ceiling (currently 80°C in the proposed manifests). This is an
operator protocol threshold, not a claim that the boards share identical
firmware limits or that stopping there proves a steady state.

`configs/experiments/thermal-stress.json` is a separate **sustained-policy
variant**, not another scientific algorithm. It runs the same complete
historical pipeline continuously using the existing board/cooling/supply:

```bash
python3 scripts/run_experiment.py run --manifest configs/experiments/thermal-stress.json --device-label pi5 --detach
```

This is a four-hour **single-pair** proposed protocol, not the first Pi smoke
test. Accept the installed code and calibrate the stable-start gate on each
actual Pi first. Change a copied manifest before launching if another pair or
duration is wanted. The original experiment remains immutable.

## Ceiling, sensor and protection behavior

Stress sets `maximum_temperature_c=null`: there is no software temperature
ceiling. It sets `require_temperature_sensor=true`: missing/invalid temperature
readings cannot silently continue. It recovers before the block, not between
its measured complete jobs. Firmware thermal protection is left enabled;
the program never changes `temp_limit`, governor, fans or cooling. Firmware can
reduce frequency as temperature rises, as described in the
[Raspberry Pi thermal-control documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#frequency-management-and-thermal-control).

Existing manifests remain valid and retain their hashes. The optional
`require_temperature_sensor` field defaults to false when absent. A non-null
software ceiling itself requires an available reading: unknown is not evidence
that temperature is below the ceiling. Uncontrolled local diagnostics with no
ceiling can continue while explicitly recording the absent Pi sensor.

Safety checks run before warmups/measured jobs and after completed jobs. A
sampled ceiling crossing or required-sensor outage **during** warmup/measured
work is latched: later cooling cannot erase it. The active job finishes and its
raw data/products/timing are retained, then the campaign stops before another
job or unnecessary recovery. A completed scientifically valid job can belong
to a thermally stopped, partial campaign. This is not a computational failure
or proof of thermal equilibrium.

Checks use acquired samples, not continuous exposure or instantaneous hardware
protection. Peaks/outages between samples can be missed; firmware protection
remains the protection mechanism. `thermal_policy_stop` links the first retained
sample/decision to its phase, run, segment and reason. All original telemetry
remains available. Firmware current and historical flags stay separate.

Setup provenance already saves actual `vcgencmd version` and
`vcgencmd get_config int` output with availability/reasons. Missing firmware
configuration or an omitted default limit is unknown, not zero or an invented
board-specific temperature. No external sensor, meter, electrical power or
energy measurement is involved.

## Recovery cost receipts

Each completed baseline/gate acquisition now saves an exclusive
`<trace.csv.gz>.receipt.json` alongside its lossless raw trace. It records actual
monotonic wall/process CPU boundaries through acquisition, raw finalization,
compression and trace hashing. Its own receipt write and caller checkpoint
occur afterward; they remain inside the containing block/API wall span.
CPU is the parent process, including its sampler threads, not child CPU.
An unmet sensor/gate condition has a real call cost but never a passing outcome.

`recovery_costs` and `recovery-costs.jsonl.gz` in saved reports inventory unique
trace files, not repeated baseline/initial-cooldown/checkpoint references. Trace
hashes and clock/outcome boundaries are verified; damaged receipt bytes remain
in the compressed journal. Legacy/partial acquisitions without a receipt have
unavailable cost, never an estimate from their last trace timestamp. Closed
gzip copies are preferred without deleting an interrupted plain copy.

Recovery call costs are **contained in** block/API elapsed time, not extra
values to add to those containing totals. Injected replay protocol clocks are
separate from the actual call wall/CPU clock; synthetic sensor replay proves
logic and byte retention, not a Pi's heating, recovery speed or calibrated
sampling overhead. Sudden interruption can leave a recoverable trace without
a committed receipt, which remains explicitly unavailable.

Non-finite, invalid or regressing protocol-clock samples fail the gate with
`clock_invalid`, an unavailable protocol duration and the original value's
representation in the raw trace. Actual call costs still use the independent
real monotonic/process CPU clocks. UTC is an identity timestamp, not the gate's
duration clock. Terminal-sample protocol time excludes later compression and
receipt writes; the real acquisition and containing block clocks cover those
costs at their documented boundaries.
