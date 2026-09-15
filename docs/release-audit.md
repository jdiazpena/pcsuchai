# Release and target acceptance audit

The full completion contract remains
[benchmark-completion-plan.md](benchmark-completion-plan.md), including its
eight gates. This audit separates deliverable software from measurements that
must come from the existing four Pis. Publishing the software does not satisfy
the target measurement gates.

## Public contents and preservation

The canonical `data/raw/langmuir-2018-2.csv` is tracked and distributed with
checksum-pinned TLE/EOP inputs. Previously derived input coordinates and
classifications remain ignored. `archive/`, alternative private raw files,
generated outputs, installation reports, local credentials/configuration and
native source/wheel caches remain excluded from Git. Unrelated untracked
root files are not staged or included in release bundles.

The release helper packages clean **committed** public files, rather than the
working directory. It rejects accidentally committed private/generated paths,
non-regular source members and the reserved `release-manifest.json` name.
Cached ApexPy 2.1.1 wheels may be added separately after opaque metadata/tag
agreement checks; this is not execution on ARM or scientific acceptance.
Each source/wheel byte is indexed by SHA-256 and the archive binds to its Git
commit. Version/commit-named archive and checksum publication is exclusive;
existing artifacts cannot be overwritten. Recoverable new partials remain
available on failure. No benchmark pruning or old-file cleanup is performed.

## Local runtime and evidence boundaries

Local verification uses the user's existing Miniconda base Python 3.14.7, not
the PC's OS interpreter, a new environment or `pip --user`. No Pi installer is
invoked here. The installed scientific dependency closure passes separately
from the project, which is executed from `src/`. The full installed-package
policy correctly reports `pcsuchai` as not installed locally; that result is
retained rather than renamed a pass. Pi installation must satisfy the entire
policy, including the installed project and native imports.

The current executable-source inventory is
`9a5382940425e6413d7451af14c9b8f541922c023b24d9328292d91444deb1f9`
(120 files). Root documentation/tests are outside that scientific inventory;
the Git commit and release archive additionally bind those files. Earlier
source-bound certificates and fault/operation matrices remain historical
evidence for their recorded revisions, not substitute current-source results.
Current-source regression/full-science results are recorded below only after
their real command handles return.

The release audit exposed generated `.egg-info` text files in the previous
source inventory. Building a wheel changed that inventory despite unchanged
scientific code. Generated `.egg-info`/`.dist-info` directories are now excluded
from source identity; installed distribution provenance is recorded separately.
A regression verifies metadata generation cannot change the fingerprint while
real model-source and requirements edits still do. No generated file was deleted.
The source/release group passed **14 tests in 0.37 seconds**; the preceding
full suite passed **556 tests in 207.92 seconds**, but predates this final
fingerprint fix. Its XML remains historical, not final-source certification.

The final-source suite passed **557 tests in 206.44 seconds**, with zero
failures/errors/skips, recorded in
`outputs/verification/release-workflow/python314-full-tests-source-identity.xml`.
The project wheel built without installing packages or fetching dependencies;
its SHA-256 is
`ae3dc9ef88c6866d57bf4215dfaa7506fb1f45a4d610b0fd4272bf5a66f6a468`.
Generating distribution metadata during that build left the 120-file source
fingerprint unchanged. Earlier wheel/check outputs remain retained separately.

The final-source native master returned **exit zero**, root status `complete`,
under
`outputs/verification/release-workflow/full-science/local-pc-python314/2026/09/15/20260915T201457.444712Z-local-scaling-functional-not-controlled-Pi-performance/`.
Its full-data certificate passed all **15 criteria** for all four pairs,
26,725 rows each and all 32 configured recipes plus three default maps per pair.
The certificate SHA-256 is
`3cd8dca6454a77ea776c2c78d0ad7328446f67398ca026c4e86cbf2cb19b5273`.
Separate post-exit verification passed all **18 source/runtime/input/contract/
retained-artifact checks** and each pair's artifact audit. Four spread-scaling
attempts (6/100 rows × minimal/full plots) were scheduled, started and accepted
against their own full-data reference, with zero failures/interruptions/retries.
Raw arrays, complete masks, readable images, inputs/source snapshots, stage/
board observations and compressed external stdout/stderr remain retained.
These are local functional results, not thermally controlled Pi performance.
All 76 Python-package source/assets in the built wheel also matched source bytes.

## Requirement-by-requirement target work

| Completion gate | Deliverable software/local evidence | Evidence still required on the Pis |
|---|---|---|
| 1. Contract | Strict seven-kind manifests; immutable workload/session/attempt/time semantics; failures consume slots, no automatic retries | Per-board pilots and reviewed frozen counts/thermal/storage policies |
| 2. Science/runtime | Full historical chain, orbit reference/parity, own-model magnetic references, footpoints, all 32 filters/maps, complete raw/invalid rows | Installed final dependency closure and full scientific acceptance on each board; same-backend cross-device tolerance decisions |
| 3. Orchestration | Unified foreground/detached/status/stop/resume; device lock; native short mode matrix and owned-process abrupt recovery | Successful supported workflows on all four targets |
| 4. Measurement | Explicit stage/worker/supervisor/full-cycle scopes; streaming raw samples; acquisition availability; separate retained operation costs | Actual matched overhead, representative storage growth/headroom and effective target provenance |
| 5. Thermal | Built-in-sensor recovery, balanced blocks, fail-closed missing/timeout/clock checks, preserved traces and firmware protections | Real SoC sensor/clock observations, calibration and sustained trends; no assumed equilibrium |
| 6. Worker/counters | Same recomputed chain in persistent/fresh modes; cleanup tests; repeated small counter groups with support/permission/coverage decisions | Long-duration resource behavior and actual exposed PMU measurements (unavailable reasons where unsupported) |
| 7. Reporting | Saved-raw reports include failures, independent sessions, numerical decisions, uncertainty, stages/resources/thermal/counters/scaling/storage | Actual independent cross-device/equal-work/overhead/scaling/sustained results under frozen contracts |
| 8. Operation | Straightforward global installer with proven Apex fix; [exact Pi commands](pi5-handoff.md); immutable raw export/import/report | Every supported board's installation → acceptance → comparison → sustained → export/report, then declared longer tests |

Only existing boards/storage/cooling/supplies and their built-in sensors are
used. Electrical power/energy, additional sensors and new hardware are excluded.
Pi Zero W ARMv6/32-bit installation is **unproven**, not promised from AArch64
success. An unavailable metric is not zero; a skipped or interrupted protocol
is not a completed benchmark. No whole-plan completion claim is made.
