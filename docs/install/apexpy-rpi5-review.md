# Review of the Raspberry Pi 5 ApexPy installation

Review date: 2026-08-14.

The procedure in `APEXPY_RPI5_ARM64_INSTALL.md` is technically credible and
the reported installation is suitable for PCS SUCHAI testing. The strongest
evidence is local to the Pi: the native ARM64 extension built, imported, had no
missing ELF dependencies, performed real coordinate conversions, and passed a
numerical geographic-to-QD-to-geographic round trip.

The following details were independently confirmed against published sources:

- PyPI publishes ApexPy 2.1.1 with the source filename, URL, and SHA-256 digest
  recorded in the guide.
- The ApexPy 2.1.1 `meson.build` unconditionally adds `-lquadmath`.
- Debian 13 (Trixie) publishes native `libquadmath0` for amd64, i386, and
  ppc64el, but not arm64.
- ApexPy's official instructions require `gfortran` and `libgfortran` for a
  source installation and support selecting `FC` and `CC` explicitly.

Two limitations should remain explicit. First, a successful coordinate
round-trip and dependency inspection provide strong installation evidence but
do not prove every ApexPy operation. PCS SUCHAI therefore runs its own
modified-apex, MLT, and surface-mapping integration tests. Second, the claim
that no source path needs quadmath is based on the source search and binary
inspection performed on the Pi; upstream maintainers should still decide
whether removal or Meson feature detection is the portable fix.

The built package lives under `/home/pi/.venvs/apexpy`. A benchmark launched
with another `python` executable will not see it. Runs must use
`/home/pi/.venvs/apexpy/bin/python`, with PCS SUCHAI and all compared
dependencies installed for that same interpreter. The benchmark manifest must
record the interpreter path and exact package versions.

Finally, scientific comparisons require version parity. The Pi uses ApexPy
2.1.1, while the development PC had ApexPy 2.0.1 at review time. Local final
validation and all Pi benchmarks must use the pinned 2.1.1 release.
