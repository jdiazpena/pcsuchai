# Full-code validation and acceptance contract

PCS SUCHAI distinguishes correctness validation, focused diagnostics, and the
official Raspberry Pi benchmark. None may be substituted for another.

## Production workload

Every official backend scenario is one clean Python process executing:

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
- required process-stage order: orbit before magnetic conversion;
- independence of orbit CSV output from the selected downstream magnetic
  backend;
- optional OMNI SYM-H parsing and plotting.

An official benchmark verifies the certificate again immediately before it
runs. Any source edit, changed input byte, changed plot configuration, Python
version, package version, row limit, failed criterion, or incomplete workload
invalidates it.

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
