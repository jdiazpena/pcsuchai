# Job temperature and performance reports

`thermal-performance.jsonl.gz` retains each attempt's sampled SoC-temperature
context with its worker/cycle timings, original status, warmup/measured identity,
cohort and sensor source/unit/scope. Missing sensors do not become zero. Clock
regressions or invalid units/scope exclude temperature associations, not raw
records. Each sensor channel remains separate. Plots use bounded dual display
envelopes preserving extrema on both axes; the full raw journal is unchanged.

Descriptive fits use checked complete measured jobs only. They report jobs,
mean temperature/latency, seconds-per-Celsius slope and Pearson correlation.
Fewer than three jobs or constant temperature cannot establish a slope. Warmups,
failures and excluded jobs remain in the point journal/charts and are not silently
used as successful measured jobs. Warmup and measured latency distributions have
separate whole-session-bootstrap summaries.

These are observed associations, not causal thermal effects. Temperature, library
cache state, order, frequency, competing work and other conditions are confounded.
No independent-job/causal confidence interval is invented for a hot-loop fit.
The sampler attaches its context label after acquisition, so a job-context sample
is not an atomic worker-start/end measurement or continuous thermal exposure.

Early/late summaries use the first and last 300 seconds of a recorded context
timeline. They require a span of at least 600 seconds, separate backend/cohort/
device/block/segment identities, non-regressed context clocks and whole job
contexts inside a window. Missing segment identity or a short trace cannot
produce this comparison. Boundary jobs are counted in only one window.
Failed/interrupted/excluded jobs stay in window outcome counts; positive-latency
statistics use complete checked jobs. A late window with only failures has no
valid latency estimate. Single-session summaries have no between-session CI.

An early/late difference is not a declaration of steady state, thermal
equilibrium or causal temperature dependence. Temperature-window qualification
is reported separately in [thermal-reports.md](thermal-reports.md); a stable
sampled temperature does not by itself prove stable sustained job performance.
Pi pilot calibration, actual hardware traces and complete protocol acceptance
remain necessary before hardware conclusions.
