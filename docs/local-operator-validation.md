# Local operator-mode evidence

This is local software evidence, not Raspberry Pi acceptance or a completed
hardware comparison. It uses the user's existing Miniconda Python 3.14.7 and
installed libraries. No dependency, system Python or Pi was changed.

The retained matrix is
`outputs/verification/operator-mode-workflow/2026/09/15/20260915T191009.759833Z/`.
Each case stores its original template checksum, effective immutable manifest,
normal foreground master's campaign, raw products/observations, gzip subprocess
logs, saved report and case result. The exact generating/launch commands and
raw stdout/stderr are retained in dated command receipts in that parent tree.

All cases invoke `scripts/run_experiment.py run`, with their generated manifest
and a new campaign directory. The external verification coordinator serializes
them under the normal inherited device lock. Its enclosing command/API costs
are not replacements for primary worker latency or Pi overhead measurements.

## Work and limits

| Template | Actual measured work | Result and interpretation |
|---|---|---|
| Acceptance | Four pairs, one 20-row spread/full-profile attempt each, then full-data validation | Four full-reference accepted smoke attempts; full 26,725-row/four-pair/32-recipe certificate passed all 15 gates |
| Equal work | Two scheduled attempts, unchanged stable-before-each-attempt mode | Zero started/two skipped; real built-in sensor unavailable, gate stopped rather than silently passing |
| Sustained | Skyfield/ApexPy, 20 rows, one three-second continuous block | Three valid completions; no between-job cooldown; short functional deadline evidence, not thermal equilibrium |
| Persistent | Skyfield/ApexPy, one warmup plus two 20-row attempts | All three jobs used one actual worker PID and recomputed their results; not a long-run leak certificate |
| Counters | Four original event groups, two 20-row attempts per group | Eight software completions; every real capability probe reported `unsupported` because `perf` was absent; no instructions/cycles/IPC invented |
| Scaling | Spread sizes 6/20 × minimal/full plot profiles, one attempt each | Four valid jobs, preserving empty filters and every requested full-profile image/mask |
| Observation overhead | Minimal/normal/detailed, two 20-row attempts per level | Six valid matched-work jobs; levels change instrumentation, not science; one uncontrolled local session cannot calibrate Pi overhead |
| Firmware-protected stress variant | Three-second block, required built-in sensor and stable initial gate retained | Zero started; unavailable sensor stopped before any warmup/measured work; no stress/throttle result claimed |

Except for the acceptance case, the computed cases use the minimal three-map
profile unless the table specifies scaling's full profile. Non-acceptance
computed cases explicitly disable a new full-reference certificate and retain
diagnostic classification; their reports have zero full-reference-accepted
attempts. Full input acceptance is established separately by the acceptance
certificate, not inferred from those short diagnostics.

The sustained, persistent, counter, scaling and observation-level cases are
explicitly adapted to uncontrolled local operation. They do not emulate a Pi
temperature or establish controlled timing. Equal-work and stress retain their
required thermal modes with shortened diagnostic windows; the original Pi
templates and their proposed calibration windows are unchanged.

The final matrix contains **27 measured completions**, one separate persistent
warmup, no failed/interrupted measured attempts and no automatic retries. Its
source digest is
`2cf52bd772bfb8454ba369e19e47e435a122f975a0de6390482acbf827a6fc11`
(124 inventoried executable/configuration files). The acceptance certificate is
`acceptance/campaign/validation/20260915T191035.027419Z/full-validation-certificate.json`.
Its applicability must be rechecked against any later source/runtime revision.

## Retained observer error, not replacement executions

The initial verifier completed acceptance and the real equal-work gate, then
failed an incorrect wording assertion: it expected the word “temperature” in
the stop reason rather than the actual structured `sensor_unavailable` result.
Its external command exit 1 and complete raw logs remain retained.

The continuation rechecked both saved terminal cases, corrected the observer
condition and launched only the remaining new cases. It did not rerun acceptance
or turn the unstarted equal-work slots into successes. The initial observer did
not commit equal-work's process exit code to its case metadata before its later
assertion failed; that case therefore retains an explicit null/unavailable code,
not a newly fabricated observation. The stress case's independently observed
exit code is 2; every computed case's observed code is 0. The continuation itself
finished with observed command exit 0.

This matrix supplements the [abrupt recovery checks](local-recovery-validation.md),
portable interrupted-campaign checks and regression tests. Target installation,
real stable sensor gates, supported PMUs, calibrated pilots, matched independent
sessions, storage forecasts and sustained/persistent long runs still require
each of the four existing Pis. No external hardware or power measurement is
assumed.
