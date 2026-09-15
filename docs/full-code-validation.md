# Full-code validation and acceptance contract

PCS SUCHAI distinguishes correctness validation, focused diagnostics, and the
official Raspberry Pi benchmark. None may be substituted for another.

## Production workload

Every complete backend scenario executes the following chain in one worker
process (fresh by default; persistent lifetime is a separately declared variant):

```text
trusted measurement loading and audit
→ fixed-width/checksummed TLE loading
→ nearest retrospective TLE assignment
→ SGP4 orbit propagation
→ Earth-fixed and WGS84 coordinate conversion
→ AACGMv2 or ApexPy magnetic conversion and surface mapping
→ all configured selections, classifications, and centroids
→ core geographic/magnetic/footpoint maps
→ all 32 archive-parity configured plots
→ scientific CSV tables, images, manifests, hashes, and benchmark records
```

The four official alternatives are Astropy→AACGMv2, Astropy→ApexPy,
Skyfield→AACGMv2, and Skyfield→ApexPy. Each repeats the complete workload; one
scenario never reuses another scenario's calculated orbit.

## Mandatory validation certificate

Run:

```bash
scripts/run_full_validation.sh DEVICE_LABEL
```

With no limit, the resulting `full-validation-certificate.json` is an
acceptance certificate for the exact source tree, raw measurements, TLE file,
EOP file, plot profile, Python interpreter, and scientific package versions.
It covers:

- trusted-field structure, duplicate timestamps, and non-finite instrument
  values;
- all TLE fixed-width records and checksums;
- satellite identity, chronological order, unique epochs, TLE coverage, and
  selected-TLE age;
- successful propagation of every TLE at its own epoch;
- a published Vallado/CelesTrak SGP4 reference state vector;
- finite local EOP interpolation for every observation with downloads off;
- hashes of Skyfield's bundled offline time tables;
- raw SGP4 wrapper configuration consistency;
- final Astropy/Skyfield WGS84 consistency and row-level differences;
- AACGMv2 and ApexPy execution from both orbit backends;
- all four complete pipeline combinations and all configured plots;
- preserved magnetic invalid-row masks, coordinate/MLT ranges and model-specific
  footpoint altitude/angular-residual units;
- version-specific published magnetic regressions for each model and separately
  labelled production API bridges, with all acquired values retained in hashed
  compressed reports; see [magnetic reference acceptance](magnetic-reference-validation.md);
- PNG decoding, declared dimensions, selected-point counts matched to saved
  masks, filled-marker metadata and added geographic land/border context;
- required process-stage order: orbit before magnetic conversion;
- independence of orbit CSV output from the selected downstream magnetic
  backend;
- optional OMNI SYM-H parsing and plotting.

An official benchmark verifies the certificate again immediately before it
runs. Any source edit, changed input byte, changed plot configuration, Python
version, package version, row limit, failed criterion, or incomplete workload
invalidates it.
Verification also rejects malformed/duplicate-key certificate JSON, missing or
failed recorded criteria, and corrupted retained pipeline artifacts. A copied
top-level `status: pass` is not sufficient evidence. Retained manifests/stage
order, arrays, plot masks and decoded images are rechecked.
Contract version 2 requires fifteen gates and both raw magnetic reference
reports. Verified historical source snapshots retain their original contract;
removing new flags/gates from new-source evidence cannot bypass acceptance.

Manifest-driven experiments separately accept their actual selected workload
against the certificate's full-data arrays after the measured blocks finish.
Prefix/spread/full selections and different frozen profiles keep exact source
rows and plot decisions. This acceptance runs outside measured clocks and never
rewrites an original attempt record. Historical offline reporting binds the
certificate to its own archived source/runtime rather than today's checkout;
see [saved-benchmark-reports.md](saved-benchmark-reports.md).

The invariant/image checks do not establish absolute magnetic accuracy or
prove that overlapping plotted points can be visually distinguished. Saved
unrounded arrays and complete masks remain the scientific comparison data.
Fresh/persistent parity and resource-stability evidence are separate from the
fresh-process scientific certificate; see
[running-benchmarks.md](running-benchmarks.md#persistent-process-lifetime).

## Official and diagnostic labels

Official reports contain:

```json
{
  "official": true,
  "workload_classification": "validated_full_code"
}
```

Quick checks and focused orbit/magnetic benchmarks contain `"official":
false` and a diagnostic classification. Cross-device comparison refuses those
reports. A diagnostic can help explain performance but cannot support the final
Raspberry Pi ranking.
The new manifest-driven saved reports still carry an explicit diagnostic
hardware classification while the completion plan is unfinished. A
`full_reference_workloads_accepted` scientific classification alone does not
certify thermal control, PMU availability or a complete Pi ranking.

## TLE assignment-age gate

This project requires the nearest selected TLE to be no more than 24 hours from
each observation. This is an engineering coverage/freshness criterion, not a
claim of 24-hour orbit truth accuracy. The canonical data currently has a
maximum absolute assignment age below 17 hours. Both earlier and later TLEs are
eligible because processing is retrospective; their counts and signed offsets
are preserved.

## Orbit consistency limits

The current cross-implementation limits are 0.01° latitude, 0.01° wrapped
longitude, 0.1 km altitude, and zero unmatched-validity rows. They are
regression limits supported by the full canonical comparison, not independent
orbit truth bounds. The SGP4 reference-vector gate validates the common SGP4
implementation separately. An external precision ephemeris would be required
for absolute orbit-accuracy validation.

## Optional external context

SYM-H is validated because its parser and image generation are repository
functionality, but it is not repeated inside every satellite-like backend
scenario: OMNI geomagnetic indices are external context, not an output of the
onboard Langmuir/particle/TLE pipeline. This distinction is recorded in the
certificate rather than silently omitting the code path.
## Independent saved-analysis checks

Every configured plot's selected count/status/range and every time-availability
plot's exact selected UTC endpoints are checked against retained data. Requested
centroids use an independent scalar reference; undefined longitudes and
overflowed totals have explicit availability. These checks contribute to each
full-pipeline criterion and are also rerun by saved-record reports. See
[analysis-product-validation.md](analysis-product-validation.md) for the numerical
contract and its limits; summary agreement is not absolute orbit/model truth.
