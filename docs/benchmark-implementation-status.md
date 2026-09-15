# Benchmark implementation evidence

The completion contract is [benchmark-completion-plan.md](benchmark-completion-plan.md).
Implementation is in progress. A passing unit test is not Pi acceptance.

The [release audit](release-audit.md) separates current-source release checks
from historical verification and every remaining target gate. The
[Pi 5 handoff](pi5-handoff.md) gives the exact install/acceptance/equal-work/
four-hour/transfer commands. Source changes invalidate applicability of earlier
certificates; current-source evidence is listed there only after inspected
terminal results.

| Gate | Current evidence | Remaining evidence/work |
|---|---|---|
| 1. Experiment contract | Strict immutable version-1 manifests and seven protocols; unified session/block execution; fixed-attempt/deadline/failure semantics, affinity and observation-level controls tested | Pilot-calibrated frozen comparison protocols and complete mode evidence matrix |
| 2. Runtime/science | Real full-data validation on Miniconda Python 3.13.5 and 3.14.7 with final pins, all four pairs/all 32 configured plots; image checks, magnetic units/domain audits, trusted row identity and frozen full-reference variant acceptance; current-source fifteen-gate full-data certificate including 19 version-pinned published own-model cases and 12 separately labelled complete production API bridges; package asset verified | Empirical cross-device tolerance acceptance, complete variant/control classification and target acceptance; independent physical accuracy is not claimed |
| 3. Orchestration | Unified foreground/detached/status/graceful-stop/resume, inherited device lock; real detached persistent stop/resume; checkpoint-orphan reconciliation with immutable originals and explicit count/duration limits; real local supervisor SIGKILL during native production followed by fixed/timed resume and saved-report accounting | Broader corruption/disk/clock fault evidence and per-board acceptance |
| 4. Measurement | Worker/stage/post-commit cycle boundaries, streaming extrema; labelled observations and actual levels; verified portable export/import; runtime dependency closure/native hashes/ABI/compiler-versus-wheel provenance and effective native pool controls tested; separate parent compression/sharing clocks, inode allocation and acquired filesystem-growth/capacity observations; dated automatic master/API and external launch/exit/log-finalization wall/CPU receipts with saved raw audits and declared observer controls | Actual per-board matched overhead, detached child interpreter/stdlib bootstrap outside its automatic master clock, unavailable historical wheel/build provenance, representative target storage pilots/headroom |
| 5. Thermal | Fail-closed baseline/stable recovery, compressed raw traces, replay tests, balanced pair/block ordering, declared threshold/cancellation; sampled safety-event latch and separate firmware-protected stress policy requiring the built-in sensor; invalid/regressing protocol clocks fail closed; hash-bound real acquisition wall/CPU receipts; saved observed-span windows, heating/phase summaries and separate current/historical firmware transition reports/plots; job-context temperature/latency associations, separate warmup statistics and disjoint backend-specific early/late windows with failure counts | Pi sensor/clock acceptance, pilot calibration and actual sustained-performance evidence |
| 6. Worker/counters | Production persistent worker/all-array fresh parity and short cleanup budgets; grouped repeated counter jobs, actual capability probes, raw coverage/scope/precision/IPC accounting; unsupported counters do not prevent software timing | Long-duration resource evidence; exact-versus-estimated enabled-time provenance; actual per-Pi PMU results |
| 7. Analysis | Saved-attempt reader includes failures/orphans/corruption in the same controlled cohort; snapshot-bound trusted rows/TLE assignment; all frozen plot recipes/masks/values checked; frozen same-backend numeric policy; full-certificate bytes/source/runtime/criteria rechecked and every first/repeated workload projected against its own full-data pair; native launcher and full-suite evidence; whole-session bootstrap latency/p95/speedups and paired observation overhead; independent scalar analysis-product checks; stage/raw journals, bounded sensor/resource plots, exploratory thermal windows/transitions, temperature/latency reports, outcome-aware stage I/O/counter availability/quality tables, all-attempt retention cost tables/conditional same-cohort storage forecasts and declared workload/output scaling with native multi-size/profile reference acceptance | Actual cross-device/overhead/sustained/scaling evidence, complete cost analysis, representative target storage pilots/headroom and complete mode/report matrix |
| 8. Operator workflow | Existing straightforward global Pi installer retained; new launcher/control/transfer commands documented; real local smoke/full acceptance, detached stop/resume and transfer/imported-report verification; owned-process abrupt recovery driver; short native foreground matrix for all seven protocol kinds plus stress, with explicit missing-sensor/counter outcomes | Remaining operator/fault/release audit and versioned push, then every Pi's dependency/capability acceptance and longer experiments |

All verification output belongs under `outputs/verification/` and is retained.
This table must be updated from inspected test results and real products before
any completion claim. No board is certified from local simulation.

## Inspected local evidence (2026-09-14)

The initial final-runtime suite passed 135 tests in 41.21 seconds, recorded in
`outputs/verification/initial-implementation/python313-full-tests.xml`.
After the scaling, mapping-unit and saved-image additions, the complete suite
passed 150 tests in 42.94 seconds, recorded in
`outputs/verification/initial-implementation/python313-full-tests-after-products.xml`.
Subsequent targeted verification passed 26 tests for scaling, mapping units,
pipeline outputs and persistent execution, and three tests for image acceptance
and complete-pipeline validation. Targeted tests include real native backend
execution; thermal trace and orchestration fault tests use declared mocks.

`outputs/verification/full-runtime-20260914T173206315Z/full-validation-certificate.json`
records real **26,725-row** execution on Python 3.13.5, NumPy 2.5.2,
Matplotlib 3.10.5, Astropy 7.2.2, SGP4 2.27, Skyfield 1.55,
AACGMv2 2.7.0, ApexPy 2.1.1 and psutil 7.0.0. All 13 certificate criteria
passed. Each pair retains 35 verified PNGs (three default maps plus the complete
32-plot profile), scientific arrays, plot masks and raw stage observations.
Both orbit paths produced 26,725 valid positions. Each AACGM run recorded
26,473 valid magnetic results and 252 invalid results; each Apex run recorded
26,725 valid results. Invalid model-domain rows remain in the raw products.
Optional SYM-H was excluded from this particular full-data execution and is
covered separately by the automated suite. These artifacts certify their
recorded source hash, not untested later source revisions.

The subsequent fresh full-data execution in
`outputs/verification/full-runtime-domain-20260914T173720004Z/`
also passed all 13 criteria, with the new magnetic row/domain/unit audits
running inside every production pipeline. Its 140 images passed decoding,
dimension, count and geographic-context checks. Ten targeted tests passed for
the new post-commit cycle timing and persistent campaign integration; 17
passed for magnetic invariants, pipeline products and persistent execution.
The complete suite after the cycle/domain changes passed **153 tests in
42.80 seconds**, recorded in
`outputs/verification/initial-implementation/python313-full-tests-cycle-domain.xml`.

The local machine is x86-64 WSL, not a Raspberry Pi. It cannot supply the Pi
firmware clock or built-in temperature evidence. Native ARM builds, thermal
gates and hardware-counter capabilities still require each board's own
acceptance results. There is no claim of whole-plan completion or Pi acceptance.

## Inspected local evidence (2026-09-15)

The user's existing Miniconda base now runs **Python 3.14.7**, not OS Python.
Scientific dependencies were restored into that existing interpreter, without
new environments, `--user`, or invoking the Pi/OS installer on this PC.
The pins are the same as the previous full validation: NumPy 2.5.2,
Matplotlib 3.10.5, Astropy 7.2.2, SGP4 2.27, Skyfield 1.55,
AACGMv2 2.7.0, ApexPy 2.1.1 and psutil 7.0.0.

The unified acceptance run at
`outputs/verification/controller-workflow/local-pc-python314/2026/09/15/20260915T142455.688586Z-acceptance/`
completed four scheduled/started/scientifically valid smoke attempts, followed
by a passing full-data certificate under `validation/20260915T142503.922656Z/`.
All 13 criteria passed. Later edits invalidate applicability to a later source
hash; they do not alter this historical evidence.

An earlier root, `20260915T142420.506942Z-acceptance/`, retained an unmet thermal
gate with zero started attempts because this PC has no Pi SoC sensor. No sensor
value was invented. Acceptance was then explicitly changed to an uncontrolled
small default-map smoke check plus full validation, and launched under a new
identity. Equal-work/thermal manifests retain their stable gates.

The real detached persistent launch/stop/resume test passed, preserving earlier
attempt bytes, compressed protocols and old stop requests. The initial
controller/counter/CLI group passed **9 tests in 9.39 seconds**. Subsequent
recovery/controller tests passed **16 in 14.79 seconds**, including verified
orphan recovery without replacement executions and interrupted/damaged slot
accounting. Thermal/failure orchestration replays use declared mocks.

The complete suite passed **187 tests in 56.57 seconds**, recorded in
`outputs/verification/initial-implementation/python314-full-tests-sequential.xml`.
An earlier suite invocation retained four lock-denial failures because real
export/import was executing concurrently; the sequential rerun passed. These
denials were not bypassed by weakening the production lock.

The real transfer bundle
`outputs/verification/controller-workflow/acceptance-python314-transfer.tar.gz`
has SHA-256 `d108e6424a0de83b8381469f1e049b5e74161bf1a4e91c29b9f0db6ee2c73766`.
Import verified **422 files, 40 directories, 194,648,422 logical bytes**.
Its compressed size is 147,527,212 bytes. Original JSON and all raw bytes remain
unchanged; verification against rebased imported paths decoded **152 images
from eight pipeline manifests**, with passing dimensions/count/context checks.
This is retained-byte/image evidence, not a new cross-device science result.

Later targeted tests passed **26 in 11.57 seconds**, including an actual
100-row complete-profile run retaining all 32 configured plots plus three
default maps, empty-filter annotations/full masks, default empty maps,
abrupt-duration accounting and transfer traversal/tamper protections.
Source-snapshot/portable/recovery/controller tests then passed **35 in 7.32
seconds**, including mutation during tar reading and image verification with
the original directory moved away. These later changes require the next
current-source full-suite/scientific evidence before a release claim.

The subsequent current-source acceptance run,
`outputs/verification/controller-workflow/local-pc-python314/2026/09/15/20260915T144345.280076Z-acceptance/`,
completed all four smoke attempts and passed full-data validation at
`validation/20260915T144353.425756Z/full-validation-certificate.json`.
The inspected verifier matched its source digest to the current checkout and
experiment state, and passed input hashes, Python/package versions and complete
plot-profile checks. The full-data geographic Apex footpoint PNG was also
visually inspected for filled markers and continents. This remains local
scientific acceptance, not proof of complete reporting, Pi capabilities or
hardware experiments.

The complete current-source regression suite then passed **196 tests in
62.44 seconds**, saved in
`outputs/verification/initial-implementation/python314-full-tests-current-source.xml`.
The recorded warnings are dependency deprecations, not suppressed test failures.
Remaining completion-plan requirements above are still open.

## Saved-record reporting evidence (2026-09-15)

Miniconda's existing Python is confirmed as **3.14.7**, Conda **26.7.2**.
No OS Python installation or new environment was used. Threadpoolctl **3.6.0**
was installed into that existing interpreter and added to benchmark pins.
Native pool introspection and limiting already-loaded pools/restoring their
stock state were tested. Dependency closure excludes unrelated OS/type-stub
packages; build metadata distinguishes installed extension hashes, source
archive hashes, compatible cached wheel hashes and genuinely unknown provenance.

The complete regression suite passed **244 tests in 85.90 seconds**, saved in
`outputs/verification/initial-implementation/python314-full-tests-saved-reports.xml`.
Native filtering fixtures verify exact full masks, values, labels, scales and
empty selections against frozen recipes. Fault tests preserve malformed
records/snapshots, terminal orphans, missing checkpoint-referenced attempts,
duplicate slots and unavailable commit timings. Statistical tests verify
equal-session weighting, whole-session resampling, exact paired-session
identity, unavailable one-session intervals and observed overhead without
assumed subtraction. Timers/scheduling in fault fixtures are explicitly
synthetic, not hardware-performance evidence.

Fresh unified acceptance at
`outputs/verification/saved-report-workflow/acceptance/local-pc-python314/2026/09/15/20260915T152626.100386Z-acceptance/`
completed four scheduled/started/valid smoke jobs with no failures, retries or
skipped slots. Its certificate under `validation/20260915T152634.807590Z/`
passed all 13 criteria for **26,725 rows × four pairs × 32 configured plots**.
The inspected source digest matched the checkout:
`263796c2595b86787c92769c0fbb6932147bcb491ae3701616ecb465ad6bbb1d`.

The saved-record report at
`outputs/verification/saved-report-workflow/20260915-current-acceptance-report/`
reconstructed all four valid attempts, four controlled diagnostic cohorts,
130 positive stage-statistic groups, 13 original block observation rows and
90 source/role/segment reading trends, plus the observation/outcome PNG.
One session per pair correctly has **unavailable between-session confidence
intervals**, not fabricated precision. All detailed attempts, stage values,
observations and numeric comparisons are streamed to compressed report journals.

The corresponding transfer bundle,
`outputs/verification/saved-report-workflow/20260915-current-acceptance-transfer.tar.gz`,
has SHA-256 `200e6c6ec586f7e71ba6d33c66868cd011090094e2242c3d76b55504e40a12b9`.
It contains **427 files, 40 directories and 194,897,006 logical bytes**;
compressed size is **147,624,271 bytes**, measured export time **5.170 seconds**.
Import verified every retained byte. The imported image audit passed **152
images from eight pipeline manifests**, resolving references into the imported
root. These are local transfer/image checks, not native ARM or PMU acceptance.
The report reconstructed from `imported-current-acceptance/` preserved the
original experiment identities, cohort statistics and attempt accounting
exactly; its observation PNG was visually inspected for readable layout and
explicitly unavailable temperature/firmware-clock panels.

Operator commands and exact scope are documented in
[saved-benchmark-reports.md](saved-benchmark-reports.md). Reporting remains
explicitly diagnostic until the remaining completion gates are evidenced.

## Full-reference workload acceptance (2026-09-15)

The saved report at
`outputs/verification/reference-workflow/20260915-archived-full-reference-report/`
rechecked the archived full-data certificate/source/snapshots/artifacts and
accepted **all four first smoke attempts** against their respective full-data
backend arrays, with zero excluded/failed/interrupted attempts. This verifies
the historical source digest recorded above, not a claim that today's source
already completed the full operator matrix.

The native-reference/orchestration group passed **23 tests in 30.81 seconds**,
saved in
`outputs/verification/initial-implementation/python314-full-reference-and-runner-tests.xml`.
The native fixture actually executes all four pairs/all 32 canonical recipes
on its entire frozen six-row input. It is explicitly small-input regression
evidence, not canonical-data or Pi performance evidence. Candidate tests cover
prefix/spread/full source-row projection, an alternative frozen profile with
geographic/footpoint/empty recipes, wrong coordinates on the first attempt,
certificate criterion/source/input/profile corruption, stage order, byte
integrity and immutable original records. Mocked launcher tests separately
verify that postmeasurement acceptance follows completed jobs and prevents a
failed scientific root from claiming completion.

After tightening pre-run criterion/schema/object/retained-byte checks and
adding acquisition-clock and distinct outcome-plot regressions, the complete
suite passed **277 tests in 116.34 seconds**, saved in
`outputs/verification/initial-implementation/python314-full-tests-reference-gates.xml`.
The preceding full-suite result (265 tests in 113.73 seconds) is retained at
`outputs/verification/initial-implementation/python314-full-tests-reference-plots.xml`.
These warnings are recorded dependency/cache deprecations, not suppressed
failures. Unknown slots, failed warm-ups and incomplete attempts cannot produce
an accepted scientific audit; their original detailed journals remain intact.

The current-source unified launch at
`outputs/verification/reference-gated-launcher/acceptance/local-pc-python314/2026/09/15/20260915T155307.210962Z-acceptance/`
completed four scheduled/started attempts without failures, skips or retries.
Its full certificate under `validation/20260915T155315.629740Z/` passed all
13 criteria for **26,725 rows × four backend pairs × 32 configured plots**.
The inspected certificate/experiment/checkout source inventories were equal,
with digest `06d8a25178897fab2da2a8dbc2f388c3722daf408c829706190e0f80a48997c7`.
The stricter pre-run verifier also passed every criterion/input/runtime/source
and retained-artifact check on this real certificate.

The launcher's separate postmeasurement journal accepted **all four first
attempts** against their full-data pairs, with no unknown/failed/interrupted/
excluded/unavailable slots. Recorded acceptance wall cost was **2.951 seconds**,
excluded from worker and committed-cycle timings. Root scientific classification
is `full_reference_workloads_accepted`; hardware classification remains
diagnostic. The independently reconstructed report at
`outputs/verification/reference-gated-launcher/20260915-current-source-report/`
rechecked all four accepted attempts, four cohorts and 13 original observations.
Its readable PNG was visually inspected: four pair-labelled outcome groups,
separate worker/supervisor memory and explicitly unavailable local SoC/firmware
clock panels. Elapsed metadata uses individual reading acquisitions with the
retained segment anchor. None of this constitutes Pi thermal/PMU acceptance
or completion of the remaining analysis/operator matrix.

The new postmeasurement acceptance records also survived lossless transfer.
Bundle `outputs/verification/reference-gated-launcher/20260915-current-source-transfer.tar.gz`
has SHA-256 `46dbdbce91453570a3eb66fa72d9bc65114c95793c4bb9d39cc8da59b3bc427e`.
Import verified **429 files, 42 directories, 194,918,059 logical bytes**;
compressed size is **147,637,755 bytes**, measured export time **5.121 seconds**.
The report reconstructed from `imported-current-source/` again accepted all
four attempts with zero exclusions/failures and matched the original
experiment identity, cohort statistics and counts exactly. This is same-data
portable reconstruction, not an independent board session or hardware result.

## Thermal windows/firmware reports (2026-09-15)

Observed-span temperature windows, heating/phase summaries, separate sampled
current/historical firmware flag tracks, and complete transition/window journals
are implemented. Criteria and operator options are documented in
[thermal-reports.md](thermal-reports.md). Default criteria are explicitly
exploratory, not sensor-calibrated protection limits or proof of equilibrium.
Stopped blocks, short windows, sensor outages, acquisition gaps, wrong units
and clock anomalies cannot masquerade as completed sustained acceptance.
New firmware masks are acquired once per board sample and reused in the
structured reading and legacy column, with source/status/UTC/monotonic times.
No power/energy measurement or additional hardware is introduced.

The targeted replay/native-observation/plot/controller group passed **54 tests
in 28.03 seconds**, saved in
`outputs/verification/initial-implementation/python314-thermal-plots-and-cli-tests.xml`.
Sensor/flag sequences are labelled synthetic; the detached stop/resume test
executes the actual persistent scientific worker. A 10,000-reading replay
checks constant-memory window state. The initial full suite passed **309 tests
in 117.17 seconds** at
`outputs/verification/initial-implementation/python314-full-tests-thermal-reports.xml`.

Real unified acceptance at
`outputs/verification/thermal-report-workflow/acceptance/local-pc-python314/2026/09/15/20260915T161001.855819Z-acceptance/`
completed four scheduled/started/accepted attempts, no failures/skips/retries,
and full-data validation at `validation/20260915T161010.195140Z/`. All 13
criteria passed for **26,725 rows × four pairs × 32 configured plots**.
At the inspected execution, its source/certificate/checkout inventories matched
digest `c72229c677ff354eb18cddb8cffd64e4c50b463221bc384908b5a15ade74d5ff`.
The later envelope-reader fix changes today's source digest, not these archived
artifact bytes or their historical reference applicability.

The first report from that real data exposed an envelope-reader defect: scalar
`schema_version` was incorrectly classified as a malformed measurement role.
The original report remains retained. The reader now interprets only the three
declared role maps, preserving the entire envelope in the raw report journal.
A real `ObservationSampler` regression was added. The corrected report at
`outputs/verification/thermal-report-workflow/20260915-native-envelope-corrected-report/`
accepted all four attempts, reconstructed all 13 original observations with
zero observation issues, and correctly reported this PC's SoC temperature
unavailable and all 13 firmware-mask acquisitions unsupported. Its thermal PNG
was visually inspected for readable, explicitly unavailable panels, not zeros.

The complete suite after that fix passed **310 tests in 119.68 seconds**, saved
in `outputs/verification/initial-implementation/python314-full-tests-native-envelope-thermal.xml`.
The failed/successful cohort split also received a regression: both outcomes
remain under their common work/reference-availability controls, keeping failed
and interrupted attempts in the same cohort's started denominator. Actual
per-Pi sensor/clock/PMU acceptance, pilot calibration, sustained-performance
analysis and the remaining cost/scaling/operator matrix are still outstanding.
# Storage-cost additions (2026-09-15)

The focused current-source suite passed **42 tests in 29.87 seconds**:
`outputs/verification/initial-implementation/python314-storage-workflow-current.xml`.
It includes real local filesystem allocation/compression/sharing, native saved
scientific products and a real detached persistent stop/resume through six jobs.
Forecast arithmetic and failure/capability cases use explicitly synthetic
observations; they are not measured Pi capacity or hardware performance.

New attempt records separate verified parent compression and sharing clocks,
compression bytes/ratios, newly retained file-block allocation and acquired
whole-filesystem growth/capacity. Reports preserve every attempt's raw storage
record in `storage-costs.jsonl.gz`, including missing historical measurements and
failed/partial jobs. Current imported-tree allocation is separately scoped from
the original target's saved capacity. See [storage-costs.md](storage-costs.md).

Forecasts are conditional same-workload extrapolations with explicit byte
headroom, not statistical upper bounds, admission guarantees or pruning policies.
Complete setup/finalization cost clocks, representative target pilots/temporary
peak headroom, scaling and sustained-performance analysis, further scientific
analysis-product checks and the remaining mode/operator matrix still need work.

The subsequent complete local suite passed **330 tests in 122.05 seconds**, with
zero skips/failures/errors, recorded in
`outputs/verification/initial-implementation/python314-full-tests-storage-current.xml`.
The separate native master-launcher acceptance completed four scheduled/started
jobs, with four accepted, zero failed/interrupted/skipped and no retries:
`outputs/verification/storage-report-workflow/acceptance/local-pc-python314/2026/09/15/20260915T163442.347289Z-acceptance/`.
Its full-validation certificate is
`validation/20260915T163451.043703Z/full-validation-certificate.json` and binds
source digest `2e892fc71aa40550b5f471426d6ad300b7b1a825412fb7776cfa84da887a747f`.
All 13 criteria passed; every pair processed 26,725 rows and all 32 configured
plots, with image validation passing. The postmeasurement variant audit accepted
all four first measured workloads against their own full-data references.
This proves that archived execution's source/runtime, not later revisions.

`outputs/verification/storage-report-workflow/20260915-native-storage-report/`
reconstructed four accepted cohorts, 13 observation rows, four raw storage-cost
records and no observation issues. Each attempt retained three per-file verified
parent compression records. Observed whole-filesystem growth ranged from
389,120 to 585,728 bytes for these 100-row/minimal-map jobs. These are local-PC
observations, not Pi results or full-data job-size estimates. The report's
10-additional-jobs/1-GiB-byte-reserve projection is only an explicit arithmetic
test scenario, not a calibrated reserve recommendation. All four forecasts are
labelled conditional, never guaranteed. The full saved tree contains 194,974,844
logical file bytes and 194,011,136 inode-allocated bytes on this analysis host;
that tree includes full validation and setup, not just the four small jobs.
# Analysis-product validation additions (2026-09-15)

The focused independent-summary/native-filter/reference suite passed **47 tests
in 32.24 seconds**, recorded in
`outputs/verification/initial-implementation/python314-analysis-products-current.xml`.
After adding direct full-certificate analysis checks and explicit null-field
validation, the targeted suite passed **44 tests in 39.36 seconds**, recorded in
`outputs/verification/initial-implementation/python314-full-analysis-gates-current.xml`.
These include real native products and small full-pipeline executions; antipodal,
negative/non-finite/overflow-weight cases and metadata tampering are synthetic
mathematical/fault cases, not physical SAA accuracy measurements.

Saved-selection verifier version 2 now checks selected metadata/ranges, exact
timeline UTC endpoints and independent scalar-reference centroids. Direct full
validation records the analysis audit inside every pipeline criterion. Production
centroids preserve raw masks/values, normalize weights before multiplication,
report overflowed totals separately and retain undefined circular longitude as
explicitly unavailable. See [analysis-product-validation.md](analysis-product-validation.md).
After the version-2 audit and additional tampering/null-field regression tests,
the complete suite passed **347 tests in 122.81 seconds** (zero failures/errors/
skips), recorded in
`outputs/verification/initial-implementation/python314-full-tests-analysis-products.xml`.
The separate real native master-launcher acceptance completed all four scheduled
jobs with four first-workload full-reference acceptances and no failures,
interruptions, exclusions, skips or retries:
`outputs/verification/analysis-products-workflow/acceptance/local-pc-python314/2026/09/15/20260915T164507.961976Z-acceptance/`.
Certificate `validation/20260915T164516.594063Z/full-validation-certificate.json`
binds source digest `2b6228ac2fc6ee15057ff12fa7fa894e4da097ee8c4a1063185e1804cbed6d8f`.
Every pair processed 26,725 rows and all 32 configured plots with both image
validation and the independent analysis audit passing. Each profile includes two
requested centroids and one UTC time-availability plot. All 13 top-level criteria
passed; this is the archived execution's evidence, not proof of later revisions.

`outputs/verification/analysis-products-workflow/20260915-native-analysis-report/`
reconstructed four accepted cohorts, 13 observation rows and zero observation
issues directly from retained records. It remains a diagnostic report, not Pi
hardware/thermal/PMU acceptance. Further independent magnetic references,
thermal/performance and scaling/campaign-cost analysis, the complete mode/fault
matrix and target evidence still remain.
# API campaign-cost additions (2026-09-15)

The focused cost/controls/real detached-runner suite passed **14 tests in 12.91
seconds**, recorded in
`outputs/verification/initial-implementation/python314-campaign-cost-controls-current.xml`.
The combined cost/storage/report/runner suite passed **52 tests in 33.44 seconds**,
recorded in
`outputs/verification/initial-implementation/python314-campaign-cost-report-current.xml`.
The full suite subsequently passed **355 tests in 122.86 seconds**, with zero
failures/errors/skips, recorded in
`outputs/verification/initial-implementation/python314-full-tests-campaign-costs.xml`.
Exact-clock/corruption arithmetic is synthetic; filesystem journals, native
science products and detached stop/resume are exercised locally. The newly
exposed first-import environment-restoration regression was fixed: the actual
`threadpoolctl` import sets `KMP_DUPLICATE_LIB_OK`; numerical controls now restore
its previous caller value rather than leaving that implicit mutation behind.

The separate native four-pair master-launcher acceptance completed all four
scheduled jobs with four full-reference acceptances and no failure/interruption/
exclusion/skip/retry:
`outputs/verification/campaign-cost-workflow/acceptance/local-pc-python314/2026/09/15/20260915T165652.923202Z-acceptance/`.
Certificate `validation/20260915T165701.816936Z/full-validation-certificate.json`
binds source digest `76a7c4bc6d88e1bc4d65c35d05df48ed2e7f9344a3789b04a29f9569561366ae`.
All 13 criteria passed; each pair processed 26,725 rows and all 32 configured
plots, including independent analysis checks. This proves its archived source,
not later revisions.

`outputs/verification/campaign-cost-workflow/20260915-native-campaign-cost-report/`
audited nine non-overlapping parent call phases against **91.9327043 seconds** of
API-active wall time and **84.4909131 seconds** of parent-process CPU. The full
scientific validation phase consumed 79.4616223 seconds and block execution
7.8677647 seconds; 0.1005908 seconds remained unclassified orchestration/journal
work. These figures are local functional evidence, not calibrated Pi performance
or steady-state satellite throughput. The report retained four accepted cohorts,
13 observation rows and zero observation issues. All four forecast groups
preferred the newer final target capacity acquisition at
`2026-09-15T16:58:24.852042+00:00`, after the full validation/acceptance work.

See [campaign-costs.md](campaign-costs.md) for containing-span/CPU semantics,
partial-journal recovery and exclusions. Master interpreter/launch/lock startup,
own receipt writing, offline report/export/import cost boundaries, recovery
subcost aggregation, thermal/performance and scaling analysis, remaining
independent model references/mode/fault evidence and all target acceptance still
need completion. These additions do not certify the whole plan as complete.
## Thermal/performance association additions (2026-09-15)

The focused saved-report/association suite passed **21 tests in 20.84 seconds**,
recorded in
`outputs/verification/initial-implementation/python314-thermal-performance-current.xml`.
After bounded dual-envelope plots and window failure accounting, **24 tests in
21.49 seconds** passed, recorded in
`outputs/verification/initial-implementation/python314-thermal-performance-plots.xml`.
Sensor/latency association and long context windows are explicit synthetic replays,
not measured Pi heating effects. Native saved science products remain separately
exercised by the saved-report fixtures.

The new journal retains warmup/measured/failed/excluded job contexts, each sensor
source/scope/unit and sampled mean/extrema/clocks alongside worker/cycle times.
Descriptive associations never claim causal temperature dependence or independent
hot-loop confidence. Early/late context windows remain disjoint by backend,
cohort, block and segment; failed late jobs remain counted with no invented valid
late latency. Warmup versus measured latency has separate session-bootstrap
summaries. See [thermal-performance.md](thermal-performance.md) for timing and
steady-state limits. Full current-source verification, real report reconstruction,
actual Pi traces/pilot-calibrated stability inference, scaling/remaining full-cost
boundaries, independent model references and the mode/fault/target matrix remain.

The full suite subsequently passed **368 tests**, with zero failures/errors/skips
and 123.918 seconds recorded in
`outputs/verification/initial-implementation/python314-full-tests-thermal-performance.xml`.
`outputs/verification/thermal-performance-workflow/20260915-native-report/`
reconstructed the previously archived native four-pair full-data acceptance:
four accepted measured attempts/cohorts, 13 observation rows, zero issues.
Eight worker/cycle phase summaries were generated. All four temperature charts
explicitly annotate missing Pi sensor readings; associations and short-run
early/late windows remain unavailable. This is saved-data reconstruction, not a
new full-pipeline run on the later report source or real Pi thermal evidence.

## Resource/counter report additions (2026-09-15)

Stage resource and repeated-counter reporting is implemented in
`resource_report.py`, documented in [resource-reports.md](resource-reports.md).
The first focused resource/counter/native-saved-report suite passed **41 tests
in 21.48 seconds**, recorded in
`outputs/verification/initial-implementation/python314-resource-report-current.xml`.
Exact counter arithmetic, availability, scope/window/coverage faults and linked
paths are synthetic. Saved-report fixtures exercise native scientific products.
Counter numbers are now reparsed from losslessly retained raw perf text rather
than trusted from run metadata. Live group acceptance requires the exact frozen
events, not merely an equal number of events. Whole-source and saved native
reconstruction verification of these latest changes is still pending.

The subsequent full local suite passed **384 tests in 123.81 seconds**, with
zero failures/errors/skips, recorded in
`outputs/verification/initial-implementation/python314-full-tests-resource-report.xml`.
This includes real backend/image/worker/operator fixtures and explicitly
synthetic counter/fault tests; it does not establish actual Pi PMU support.

`outputs/verification/resource-report-workflow/20260915-native-report/`
reconstructed the historical native four-pair acceptance without changing its
archives: four full-reference-accepted attempts/cohorts, 13 observations and
zero report issues. Its 40 saved stage records produced **320 resource rows**,
including **160 available zero-valued rows**; no missing values were substituted.
The four temperature-association PNGs decoded at 1000×500, and one was visually
inspected for explicit unavailable-reading annotation. This original campaign
did not collect hardware counters, so its empty counter experiment list is not
a supported-counter result. The new reader's raw-counter precision/coverage/
availability claims rely on separately labelled replay tests until target probes
are available. Workload/output scaling, remaining whole-operation cost boundaries,
thermal-stress policy, independent model references, broader operator/fault
coverage, final release/push and the actual four-board matrix remain unfinished.

## Workload/output scaling additions (2026-09-15)

`scaling_report.py` and `scaling_plotting.py` implement the saved-record scaling
contract in [scaling-reports.md](scaling-reports.md). Verified product descriptors
now retain all default/configured plot metadata and observed row/selection
coverage. Scaling groups vary only input size/profile; backend/device/software/
thread/process/thermal/observation/selection-method controls remain frozen.
Failed jobs without products stay in their requested variant's denominator.
Matched ratios change one variable at a time, refuse missing/inconsistent
rendering contracts and use paired whole-session uncertainty, not independent
hot-loop resampling. Per-input-row worker/cycle costs include fixed startup and
output work. PNG bytes/selected points/empty filters are observed products, not
an assumed radio budget or scientific-utility score.

The first focused scaling/native-saved-product suite passed **44 tests in 22.39
seconds**, recorded in
`outputs/verification/initial-implementation/python314-scaling-report-current.xml`.
After readable 1200×900 filled-scatter charts and the explicit small LOCAL-only
functional manifest, **51 tests in 21.48 seconds** passed, recorded in
`outputs/verification/initial-implementation/python314-scaling-plots-current.xml`.
Control/ratio/availability arithmetic is synthetic; saved scientific products
and image/chart decoding are native local execution. Full-suite and actual
multi-size/profile launcher→full-reference→saved-report verification of this
latest source are still pending. Actual controlled per-Pi scaling conclusions
require target traces/pilots and remain unavailable from local replays.

The full local suite passed **404 tests in 123.91 seconds**, with zero
failures/errors/skips, recorded in
`outputs/verification/initial-implementation/python314-full-tests-scaling-report.xml`.
After tightening PNG byte acquisition to the actual bound/hash-verified readable
files and exposing per-row stage CPU, the focused suite passed **47 tests in
24.28 seconds**, recorded in
`outputs/verification/initial-implementation/python314-scaling-actual-bytes-current.xml`.
The added native fixture deliberately reports wrong size metadata and verifies
that the actual measured file bytes remain correct, with the original metadata
and disagreement flag retained. The 404-test full suite preceded this small
descriptor refinement; final whole-source regression verification remains part
of release acceptance, not implied by that earlier run.

The actual master-launcher scaling workflow completed:
`outputs/verification/scaling-workflow/local-pc-python314/2026/09/15/20260915T172950.048959Z-local-scaling-functional-not-controlled-Pi-performance/`.
All four scheduled jobs (one pair × sizes 6/100 × minimal/archive-full profiles)
were started and full-reference accepted; no failed/interrupted/excluded/skipped/
retry slots were present. Certificate
`validation/20260915T172950.847317Z/full-validation-certificate.json` binds source
`e16cb6d3e0ce99ef447d0e8418e5c7791eda1c5b5b3cfc00c827fbcd7545f162`.
All 13 criteria passed, with 26,725 observations/all 32 configured plots and
image/independent analysis checks for every full-reference backend pair.
This evidence certifies its archived source, not later revisions.

The reconstructed native report is
`outputs/verification/scaling-workflow/20260915-native-scaling-report/`:
four accepted primary cohorts, one intended-variable scaling group/four variants,
21 acquired observation rows and zero report issues. It retained all per-job
plot metadata: 3 images per minimal job and 35 per archive-full job. Actual PNG
payload totals were 373,894/418,536 bytes for 6/100-row minimal jobs and
5,131,350/5,279,756 bytes for archive-full jobs. All metadata/file size agreement
flags passed. Eight one-variable worker/cycle cost ratios were available; their
uncertainty remained unavailable because only one session was observed. The
1200×900 filled-scatter scaling chart was decoded and visually inspected.
These are LOCAL functional examples with uncontrolled thermal settings, not
comparative Pi measurements, a capacity guarantee or an SAA utility score.

At this earlier scaling checkpoint, remaining implementation included whole-operation startup/report/import/export
cost boundaries, additional
independent model references and broader mode/fault/operator evidence. Final
current-source regression/scientific workflow, release/push and each board's
actual dependency/capability/thermal/pilot/longer-run matrix remain required.

### Thermal safety and recovery cost evidence

The thermal-stress sustained-policy variant is documented in
[thermal-stress.md](thermal-stress.md). It requires real temperature readings,
does not impose a software ceiling, and does not change firmware protection,
cooling, supply or OS settings. Ordinary declared ceilings remain distinct.
Replay tests retain a sampled mid-job ceiling crossing even after later cooling:
the active complete scientific job is saved, then further work stops. Missing
required readings stop before warmup/measured work. These are logic tests, not
measured Pi heating or steady-state evidence.

Recovery receipts bind actual compressed traces to independently acquired real
monotonic/process-CPU costs through compression and hashing. Unknown historical
costs stay unavailable. Reports reject wrong hashes, clocks, booleans, outcome,
units, scope and source while retaining damaged original receipt bytes.
Invalid/non-finite/regressing protocol clocks retain a `clock_invalid` terminal
trace and cannot pass the gate or fabricate elapsed time. These injected-clock
tests do not establish every host clock or reboot behavior.

Inspected local JUnit evidence:

- `outputs/verification/initial-implementation/python314-recovery-costs-current.xml`:
  **68 passed**, 34.37 seconds; thermal/recovery/orchestration/saved-report group.
- `outputs/verification/initial-implementation/python314-thermal-clock-current.xml`:
  **56 passed**, 7.84 seconds; strict receipt and invalid/regressing clock cases.
- `outputs/verification/initial-implementation/python314-full-tests-thermal-recovery.xml`:
  **443 passed**, 128.41 seconds, zero failures/errors/skips. This is the full
  local Python 3.14.7 suite for this executable source, not per-Pi acceptance.

The actual default-sensor local probe at
`outputs/verification/recovery-cost-workflow/20260915T174821.589298Z-local-unavailable-sensor-probe/`
recorded `sensor_unavailable`, retained its raw compressed trace and committed
one verified failed-condition acquisition receipt. Actual call wall time was
0.007503433 seconds and parent CPU time 0.001046556 seconds. Its separately saved
report is `20260915T174821.589298Z-local-recovery-cost-report/` in the same parent.
This is native execution of the missing-capability path, not a benchmark run,
Pi sensor acceptance or representative recovery-cost estimate.

The current saved-report reader reconstructed the historical native scaling
campaign into
`outputs/verification/thermal-recovery-workflow/20260915-native-saved-report/`.
All four attempts remained full-reference accepted, with four cohorts, 21
observation rows and zero report issues. The historical uncontrolled campaign
has no saved recovery acquisitions: its recovery cost is explicitly unavailable,
not zero. The compressed report journals were decoded and image products read.
The archived scientific certificate retains its historical source identity;
reading it with this updated reporter does not re-certify current source.

At this earlier thermal checkpoint, whole-command/transfer/report cost boundaries, independent model reference
cases and broader operator/fault evidence remain implementation work. The full
plan is not complete, no Pi hardware result is inferred, and release/push still
requires the final current-source scientific/operator workflow.

### Whole-operation cost evidence

The saved scopes, automatic locations, external command wrapper and `costs`
audit are documented in [whole-operation-costs.md](whole-operation-costs.md).
Public report/export/import calls now retain complete locked-call wall/parent-CPU
receipts outside their immutable input/output payloads. Master run/resume saves
project-import-through-result clocks, including separate detached handoff/child
identities. External commands save launch-through-exit, waited-child user/system
CPU, parent CPU, bounded raw stdout/stderr and their measured finalization.
All scopes remain explicitly separate; the enclosing costs are not added twice.
Detached child interpreter/stdlib startup remains outside its narrower automatic
master clock, not invented. Foreground external measurement includes the command's
interpreter startup but excludes its own wrapper bootstrap/lock acquisition.

The wrapper holds/passes the same device lock through logging/finalization and
refuses a competing launch before creating observer files. Its declared
tee/sync/echo context is captured in runtime and scientific comparison controls;
wrapped, unwrapped and upstream-detached-launcher-only contexts do not silently
merge. These are declared/inherited settings, not a live-observer measurement.
The frozen runtime resume contract also prevents silently changing that context.

Inspected local JUnit evidence:

- `outputs/verification/initial-implementation/python314-operation-existing-paths.xml`:
  **31 passed**, 23.19 seconds, native saved science and verified transfer paths.
- `outputs/verification/initial-implementation/python314-operation-observation-controls.xml`:
  **69 passed**, 35.38 seconds, including real detached stop/resume with three
  master receipts and unchanged original attempts, raw binary logs, graceful
  signals, cost/storage failures, corrupt/partial metadata and observer controls.
- `outputs/verification/initial-implementation/python314-operation-lock-current.xml`:
  **23 passed**, 0.92 seconds, including actual competing-wrapper lock denial.
- `outputs/verification/initial-implementation/python314-full-tests-whole-operation.xml`:
  **467 passed**, 129.29 seconds, zero failures/errors/skips on Python 3.14.7.

The real LOCAL operator workflow is retained at
`outputs/verification/whole-operation-workflow/20260915T180951.174970Z/`.
It binds executable source
`65f64d90cdb08e13fa872d34bd388461a29bdc4b19c8083cc7ddf1d7e177ced2`.
Its explicitly uncontrolled one-pair 100-row functional manifest executed the
complete Skyfield/ApexPy chain. Launch → export → import → image verification →
saved science report → cost audit succeeded. All **49 original files** were
byte-identical in the imported payload and unchanged in the original experiment.
The three imported 1200×600 maps decoded. The saved science report retained one
product-valid attempt, ten stage rows, five acquired board observations and zero
issues; full-reference acceptance remained unavailable by explicit design.
This small fixture is not all-four-pair scientific or Pi acceptance.

The saved cost audit independently decoded/audited nine terminal receipts:
five external commands, three public API calls and one foreground master.
All nine returned; none were raised/unfinished/invalid. Raw metadata journals and
both command log streams were retained losslessly. Example containing wall
spans were 3.282784 seconds external launch, 3.193493 seconds master, 0.296289
seconds external export and 0.199218 seconds export API. These are local observed
calls, not additive totals, target throughput, a speedup estimate or an assumed
constant overhead. Parent/child CPU includes their declared all-thread scopes
and can exceed wall time when threads run concurrently.

At that earlier checkpoint, remaining work included model reference cases, broader abrupt/disk/
corruption/mode/operator evidence and final current-source scientific/release
workflow. Actual per-board dependencies, PMU/sensor/clock capability, frozen
pilots, matched observation overhead, cross-device numerical/scaling comparisons
and sustained/persistent long-run evidence remain required. No hardware result
or whole-plan completion is inferred from local tests; push is still pending.

### Published magnetic regressions and protected validation evidence

The current contract is described in
[magnetic-reference-validation.md](magnetic-reference-validation.md).
It requires **19 published own-model regression cases** (12 AACGMv2, seven
ApexPy) and **12 production API bridges** (seven AACGMv2, five ApexPy), with
explicitly distinct accuracy scopes. Primitive APIs check the production
combined coordinate/MLT wrappers; each ground projection retains its model's
height/residual units. High-altitude fallback, two epochs, leap-day/dateline
representations, invalid-orbit propagation and AACGM's undefined equatorial
row are included. Native binaries/configured coefficients are hash recorded.
Acquired float64 bits, including unavailable/non-finite values, remain in raw
compressed reports alongside nullable presentation and numerical deltas.

Source-enabled contract version 2 requires both gates/reports. Readers derive
the required version from the verified source inventory, replay frozen archived
oracles without executing archived code, and recompute bridge invariants from
raw values. Removing flags/gates/source members cannot downgrade active
acceptance. Verified older source retains its historical thirteen-gate contract.
Direct full validation rejects reuse of complete/partial artifact directories
before touching inputs/products; its reference files are created exclusively.

Inspected native local evidence on Miniconda Python **3.14.7**:

- `outputs/verification/initial-implementation/python314-full-tests-magnetic-primitives.xml`:
  **513 passed**, 134.41 seconds; zero failures/errors/skips. Includes real small
  four-pair/all-32-recipe fixtures, production-wrapper faults, missing libraries,
  reference corruption/units/version/contract faults and unchanged-file checks
  after attempted validation-directory reuse.
- `outputs/verification/initial-implementation/python314-magnetic-refreshed-raw-faults.xml`:
  **41 passed**, 0.22 seconds. This later focused group adds two synthetic
  model cases with refreshed raw bits/deltas and forged passing flags: fixed
  upstream tolerance replay still rejects them. It changes tests only, not the
  executable source certified below; its overlapping tests are not added to
  the 513 full-suite count as if they were disjoint.

Native experiment at that checkpoint (later worker/driver edits change source):
`outputs/verification/magnetic-reference-workflow/local-pc-python314/2026/09/15/20260915T183654.317628Z-local-scaling-functional-not-controlled-Pi-performance/`.
Certificate `validation/20260915T183655.120665Z/full-validation-certificate.json`
binds source
`7356755dcffe883807ce31f3c3050e56ddd8ab4e5235a57c82678c4d5365a1a1`.
All **15 criteria** passed for **26,725 rows × four pairs × 32 configured
plots**, with 35 decoded images per pair (140 in total), complete scientific
arrays/masks and compressed raw samples. The two new reference reports were
decoded/replayed and retain 92 AACGM/4 Apex installed-file hashes. The current
runtime/source/input/retained-artifact verifier independently passed afterward.
One full-data Apex geographic footpoint image was visually inspected: filled
points, continents and the concentrated South Atlantic counts remain visible.

The same actual launcher then completed four scheduled/started/accepted
Skyfield/ApexPy scaling jobs (6/100 spread-selected rows, minimal/full profiles),
with zero failures/interruption/retries/skips. This is explicitly uncontrolled
local functional evidence, not temperature calibration or Pi performance.
`outputs/verification/magnetic-reference-workflow/final-current-source-saved-report/`
reconstructed all four full-reference accepted attempts, four cohorts, 104
stage rows and 25 acquired observations with zero issues. Every compressed
report journal was decoded; unavailable thermal/counter data remains absent,
not invented. The reader also successfully rechecked the earlier historical
thirteen-gate scaling certificate under its own archived source contract.

Package verification built a wheel from a separate temporary source copy,
using the existing interpreter/build tools with no dependency installation or
build environment. The retained wheel at
`outputs/verification/magnetic-reference-workflow/package-check/wheels/pcsuchai-0.1.0-py3-none-any.whl`
has SHA-256 `a10d97e614deead44d94875c0d683e71c4f6b4d0f09773c6046206e536e52e38`.
Its reference asset is byte-exact to source, SHA-256
`1932a2ac1516403ce73ffad55571ea60b7ea519d4081d169ed8d75eda722894e`.
The executable source hash was unchanged after building and verification.

External validation/verification/build logs and operation receipts remain under
`outputs/verification/magnetic-reference-workflow/command-receipts/`.
`operation-cost-audit/` in that parent audited seven returned receipts (four
external commands, two actual masters and one report API), with zero raised,
unfinished or invalid receipts and lossless raw metadata. Containing spans are
descriptive costs, not summed deployment latency or measured observer overhead.

Remaining: broader abrupt/disk/corruption/operator-mode evidence and the final
release/push workflow; actual per-board dependencies, sensor/clock/PMU capability,
pilot calibration/frozen protocols, matched observation overhead, cross-device
numerical/scaling results and sustained/persistent long-run evidence. Published
regressions do not establish independent physical accuracy. No Pi was modified
or certified in this local checkpoint, and the full plan remains active.

### Abrupt supervisor recovery and publication failures

The [local recovery workflow](local-recovery-validation.md) now exercises an
actual supervisor SIGKILL after observing native production output, not a
simulated worker response alone. The worker's original completed terminal was
already retained by the old path; the corrected bug is its second attempted
send after delivery failure. Publication now has one send attempt and a separate
hash-bound incident, without overwriting science or claiming supervisor-confirmed
benchmark completion. Readiness failures and existing incident files are tested.

Owned-process checks require the native worker's actual parent and live
boot/start identity. Both original and resumed supervisor handles/workers are
tracked for explicit failure cleanup. Observation expiry does not restart work
or imply an exit code; failed checks retain their intent, logs and exception.

Inspected evidence on the existing local Miniconda Python **3.14.7**:

- `outputs/verification/initial-implementation/python314-worker-recovery-safety.xml`:
  **28 passed** in 22.11 seconds. Includes real native 20-row science with
  explicitly injected write/flush pipe failures, and separately labelled
  synthetic launch, timeout, invalid-PID and cleanup faults. The parent-identity
  check uses the actual Linux process identity without signalling it.
- `outputs/verification/initial-implementation/python314-full-tests-abrupt-recovery.xml`:
  **534 passed** in 136.72 seconds, zero failures/errors/skips. This is a complete
  sequential suite, not the sum of overlapping focused groups.
- `outputs/verification/abrupt-recovery-workflow/2026/09/15/20260915T185606.104458Z-fixed-d3b00e3f/`:
  four scheduled/started attempts, three product-validated and one interrupted,
  zero retries/skips; original supervisor exit −9, resume exit 0.
- `outputs/verification/abrupt-recovery-workflow/2026/09/15/20260915T185634.265350Z-timed-12d8e56f/`:
  one started/interrupted attempt, zero product-validated completions or retries;
  original supervisor exit −9, resume exit 2. The duration clock is explicitly
  unavailable after the abrupt uncommitted segment; no additional work starts.

Both actual scenarios used 100 spread-selected rows and all 32 plot recipes.
Each preserved **79 original orphan files byte-for-byte**, including the complete
worker result and delivery incident; each retained four gzip subprocess logs.
Unknown supervisor finish times remain null. Both saved reports remain
`partial_or_excluded` and retain their interrupted attempt, with zero
full-reference-accepted diagnostic attempts. Their killed master intents remain
unfinished; resume/report receipts are committed rather than fabricating the
missing enclosing wall/CPU cost.

These changes bind executable source
`a8a4c22cfb95ad36b4f453387d3a34636e467fb9d548ee95cc33ab89faba22a3`
(124 inventoried files). They do not establish power-loss durability, Pi
capabilities, calibrated thermal conditions or long-running resource stability.
Broader disk/corruption/operator-mode verification and release/push remain open,
alongside the actual per-board acceptance/pilot/comparison evidence above.

The fresh normal-launcher workflow at
`outputs/verification/abrupt-recovery-workflow/full-science/local-pc-python314/2026/09/15/20260915T185926.699525Z-local-scaling-functional-not-controlled-Pi-performance/`
then passed current-source full validation at
`validation/20260915T185927.502129Z/full-validation-certificate.json`.
All **15 criteria** passed for **26,725 rows × four pairs × 32 configured
plots**, with the same `a8a4c22c…` source above. The independent retained-artifact
recheck passed all **18 checks** and each pair's saved products. The following
four normal-launcher scaling jobs (6/100 spread rows, minimal/full profiles)
were all full-reference accepted. The saved report under
`outputs/verification/abrupt-recovery-workflow/saved-workflow-20260915T190137.106411Z/full-science-report/`
reconstructed four attempts/cohorts, 104 stage rows and 25 actual observations.
Every report journal was decoded; unavailable temperature/counter rows were
not invented. This is local functional evidence, not controlled Pi performance.

The same saved workflow exported the two inactive interrupted campaigns,
imported them into new directories, verified every original byte and decoded
their saved images using paths rebased wholly inside the imported roots:

| Bundle | Files/directories | Logical/compressed bytes | Verified images | SHA-256 |
|---|---|---|---|---|
| `fixed.tar.gz` | 427 / 28 | 37,031,542 / 17,786,337 | 140 across four manifests | `38166b9b63455f374418da4df5ab8fb9c6c993bfec7da7b24e0ebc7e08237aeb` |
| `timed.tar.gz` | 114 / 18 | 12,506,079 / 11,900,281 | 35 across one manifest | `f66c46274ad4c352af89f92d6e33a7f2be88ce32ff69885e1974e72e35e90e00` |

Both imported reports remain `partial_or_excluded`, retaining four/one started
attempts respectively and one interrupted attempt each, with no full-reference
acceptance falsely inferred from readable orphan images. Original campaigns,
source/input snapshots, raw scientific/telemetry bytes and transfer bundles
remain intact. Image/integrity verification is not target scientific acceptance.

`cost-audit/` in that saved-workflow root retained 15 raw receipt rows, with
**13 returned, two unfinished, zero raised and zero invalid**. All 28 acquired
intent/terminal raw metadata documents were base64-decoded. The two killed
masters remain unfinished with unavailable costs, not zero-cost successes.
Containing command/API/job spans are not added into a fabricated deployment
latency. The two enclosing external commands also retain gzip logs and terminal
receipts under `outputs/verification/abrupt-recovery-workflow/command-receipts/`.

Full plan completion remains unproven: the broader operator/fault/release matrix
and the per-board acceptance/calibration/long-run/comparison results are still
required. No Pi or system dependency was changed in this checkpoint.

### Retention failure accounting, sampler ownership and operator modes

Actual native 20-row fixtures exposed two missing failure paths. Parent
compression errors escaped before recording a failed attempt; an unwritable
terminal also left the board sampler alive after both fresh and persistent
campaign calls returned exceptionally. The retained pre-fix XML files
`python314-retention-disk-before-fix.xml` and
`python314-terminal-disk-sampler-before-fix.xml` each record two failures.
The storage errors are explicitly injected ENOSPC, not actual disk filling.

The corrected parent retention handler keeps completed science distinct from
failed full-job finalization, records the actual errno/class/attempted wall time,
preserves a separate primary computation/interrupt cause and stops subsequent
work even under continue-on-error. Every campaign owns its sampler cleanup
before recording begins. ExitStack cleanup joins it before lock release;
idempotent final sampling cannot recreate a finalized timeline. Worker-log
compression is not silently retried, and secondary cleanup errors are attached
to the original exception. Unwritable terminal cases retain their intent/raw
products and consume their slot as interrupted on resume, with unknown timing.
See [raw-data-retention.md](raw-data-retention.md) for the exact limits.

Inspected sequential verification:

- `outputs/verification/initial-implementation/python314-retention-cleanup-complete.xml`:
  **11 passed**, 15.66 seconds; real fresh/persistent × warmup/measured storage
  faults, real orphan resume with unchanged original bytes, and separately
  declared synthetic final-sample/secondary-cleanup/log-retention faults.
- `outputs/verification/initial-implementation/python314-full-tests-retention-mode-matrix.xml`:
  **545 passed**, 151.72 seconds; zero failures/errors/skips. All earlier tests
  ran sequentially alongside the new failure-path cases.

The [local operator-mode matrix](local-operator-validation.md) retains normal
foreground master execution under
`outputs/verification/operator-mode-workflow/2026/09/15/20260915T191009.759833Z/`.
It produced **27 measured completions** and one separate persistent warmup:
four acceptance, three sustained, two persistent, eight grouped-counter,
four scaling and six observation-level jobs. Equal-work and the stress variant
correctly stopped with zero started attempts at the actual unavailable-sensor
gate. Counter probes recorded the actual absence of `perf`, with software
timing retained and no invented instruction/cycle values. Cases outside the
acceptance run are explicitly short/uncontrolled diagnostic variants, not
calibrated Pi performance or additional full-reference acceptance.

Acceptance first completed all four 20-row spread/full-profile smoke jobs,
then passed **26,725 rows × four pairs × 32 configured plots**, all **15 gates**,
at `acceptance/campaign/validation/20260915T191035.027419Z/full-validation-certificate.json`.
The source is
`2cf52bd772bfb8454ba369e19e47e435a122f975a0de6390482acbf827a6fc11`
(124 inventoried files). Later doc/test evidence does not mutate that inventory.

The matrix's initial observer failed its own human-readable wording assertion
after the real equal-work gate correctly recorded `sensor_unavailable`. Its
command exit 1/raw gzip logs remain held. The successful continuation reused
both saved terminal cases rather than rerunning them, and launched only new
remaining cases. Equal-work's uncommitted observer exit code remains explicitly
null; independently acquired codes and the continuation's exit 0 are retained.
No failed observer evidence or scientific attempt was deleted or relabelled.

Hardware acceptance/calibration, real supported PMU values, matched independent
sessions/overhead, representative storage forecasts and sustained/persistent
long-run comparisons remain required on the four existing Pis. Local expected
unavailability is not a substitute for their successful thermal/counter tests.
The release/push handoff and full completion audit remain open.

Permanent native fault evidence is retained at
`outputs/verification/retention-fault-workflow/2026/09/15/20260915T191800.093135Z/`.
All **eight cases** (fresh/persistent × measured/warmup × closed-log compression/
terminal-commit failure) passed using real 20-row/default-map science and
explicitly injected ENOSPC. No filesystem was physically filled. Compression
cases retain a failed full-job record alongside completed science and launch
no additional work. Terminal cases retain no fabricated run terminal; the normal
CLI resumes only the remaining slots and preserves the original interruption,
including warmup interruptions separately from measured outcomes. All four
actual CLI resumes exited 0. **118 original attempt files** across the eight
cases remained byte-identical through reporting/recovery. Raw source/input
snapshots, arrays, maps, stage/board journals and failure metadata remain held.

That final fault result also retained a passing recheck of the current `2cf52bd7…`
full-data certificate, all 18 checks/four pair artifact audits. The earlier
observer errors remain as separate gzip command evidence: reporting before
the diagnostic supervisor exited hit the live-process guard; a later child
incorrectly expected an exception to escape the continue-policy master rather
than its correctly stopped durable outcome. Neither completed failed attempt
was rerun. Continuations observed inactive child handles, acquired missing
post-exit inventory where required, and recorded unavailable initial observer
codes/observations explicitly rather than inventing measurements. New child
checks directly asserted sampler closure before returning; generic fresh/
persistent terminal tests independently establish that cleanup boundary.

Final command exit 0/raw logs are retained in
`outputs/verification/retention-fault-workflow/command-receipts/2026/09/15/20260915T192202.529149Z-native-retention-faults-final-continuation-702f60306a51/`.
API/command outcomes are not successful benchmark attempts or hardware results.
Broader release/fault audit and the actual target experiments remain open.
