"""Command-line interface for reproducible local and Raspberry Pi runs."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

from .errors import PCSException
from .pipeline import run_analysis


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pcsuchai", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze", help="run the analysis and minimal map pipeline")
    analyze.add_argument("--measurements", type=Path, default=Path("data/raw/langmuir-2018-2.csv"))
    analyze.add_argument("--tle", type=Path, default=Path("data/tle/suchai1.tle"))
    analyze.add_argument("--eop", type=Path, default=Path("data/eop/finals2000A.all"))
    analyze.add_argument("--output-dir", type=Path, default=Path("outputs/local"))
    analyze.add_argument("--orbit-backend", choices=("astropy", "skyfield"), default="astropy")
    analyze.add_argument(
        "--magnetic-backend", choices=("none", "aacgmv2", "apexpy"), default="none"
    )
    analyze.add_argument("--limit", type=int, default=None, help="process only the first N rows")
    analyze.add_argument("--particle-threshold", type=float, default=0.0)
    analyze.add_argument(
        "--plot-config", type=Path, default=None,
        help="JSON profile containing additional filtered plot recipes",
    )
    analyze.add_argument("--benchmark", action="store_true", help="enable stage performance sampling")
    validate = commands.add_parser(
        "validate-orbits", help="validate and benchmark Astropy and Skyfield on identical inputs"
    )
    validate.add_argument("--measurements", type=Path, default=Path("data/raw/langmuir-2018-2.csv"))
    validate.add_argument("--tle", type=Path, default=Path("data/tle/suchai1.tle"))
    validate.add_argument("--eop", type=Path, default=Path("data/eop/finals2000A.all"))
    validate.add_argument("--output", type=Path, default=Path("outputs/orbit-validation.json"))
    validate.add_argument(
        "--benchmark-output", type=Path, default=Path("outputs/orbit-benchmark.json")
    )
    validate.add_argument(
        "--differences-output", type=Path, default=Path("outputs/orbit-differences.csv")
    )
    validate.add_argument(
        "--plots-output-dir", type=Path, default=Path("outputs/orbit-validation-plots")
    )
    validate.add_argument("--limit", type=int, default=None)
    magnetic = commands.add_parser(
        "validate-magnetic", help="benchmark AACGMv2 and ApexPy on identical positions"
    )
    magnetic.add_argument("--measurements", type=Path, default=Path("data/raw/langmuir-2018-2.csv"))
    magnetic.add_argument("--tle", type=Path, default=Path("data/tle/suchai1.tle"))
    magnetic.add_argument("--eop", type=Path, default=Path("data/eop/finals2000A.all"))
    magnetic.add_argument("--orbit-backend", choices=("astropy", "skyfield"), default="astropy")
    magnetic.add_argument("--output", type=Path, default=Path("outputs/magnetic-validation.json"))
    magnetic.add_argument(
        "--benchmark-output", type=Path, default=Path("outputs/magnetic-benchmark.json")
    )
    magnetic.add_argument(
        "--differences-output", type=Path, default=Path("outputs/magnetic-differences.csv")
    )
    magnetic.add_argument("--limit", type=int, default=None)
    symh = commands.add_parser("plot-symh", help="plot optional OMNI SYM-H reference data")
    symh.add_argument(
        "--input", type=Path, default=Path("data/external/OMNI_HRO_1MIN_2527270.txt")
    )
    symh.add_argument("--output", type=Path, default=Path("outputs/symh.png"))
    symh.add_argument("--start", default=None, help="inclusive ISO UTC start")
    symh.add_argument("--end", default=None, help="inclusive ISO UTC end")
    suite = commands.add_parser(
        "benchmark-suite", help="run randomized, repeated, clean-process comparisons"
    )
    suite.add_argument("--output-dir", type=Path, default=Path("outputs/benchmark-session"))
    suite.add_argument("--measurements", type=Path, default=Path("data/raw/langmuir-2018-2.csv"))
    suite.add_argument("--tle", type=Path, default=Path("data/tle/suchai1.tle"))
    suite.add_argument("--eop", type=Path, default=Path("data/eop/finals2000A.all"))
    suite.add_argument("--plot-config", type=Path, default=None)
    suite.add_argument("--orbit-backends", nargs="+", choices=("astropy", "skyfield"), default=("astropy", "skyfield"))
    suite.add_argument("--magnetic-backends", nargs="+", choices=("aacgmv2", "apexpy"), default=("aacgmv2", "apexpy"))
    suite.add_argument("--repeats", type=int, default=None)
    suite.add_argument(
        "--duration-seconds", type=float, default=None,
        help="run complete randomized rounds until this active duration is reached",
    )
    suite.add_argument("--warmups", type=int, default=1)
    suite.add_argument("--seed", type=int, default=1729)
    suite.add_argument("--limit", type=int, default=None)
    suite.add_argument("--cooldown-seconds", type=float, default=0.0)
    suite.add_argument("--cooldown-until-c", type=float, default=None)
    suite.add_argument("--cooldown-max-seconds", type=float, default=600.0)
    suite.add_argument("--timeout-seconds", type=float, default=3600.0)
    suite.add_argument("--perf", action="store_true", help="attempt a separate Linux perf run")
    suite.add_argument("--device-label", default=None)
    suite.add_argument("--notes", default=None)
    suite.add_argument("--project-root", type=Path, default=Path("."))
    suite.add_argument("--official", action="store_true", help="require exact full-code validation")
    suite.add_argument("--validation-certificate", type=Path, default=None)
    suite.add_argument("--telemetry-interval-seconds", type=float, default=2.0)
    suite.add_argument("--minimum-free-gb", type=float, default=1.0)
    suite.add_argument("--maximum-temperature-c", type=float, default=None)
    suite.add_argument("--continue-on-error", action="store_true")
    suite.add_argument("--max-consecutive-failures", type=int, default=3)
    suite.add_argument("--resume", action="store_true", help="continue the exact checkpoint in output-dir")
    preflight = commands.add_parser("preflight", help="verify a machine before benchmarking")
    preflight.add_argument("--project-root", type=Path, default=Path("."))
    preflight.add_argument("--output-dir", type=Path, default=Path("outputs/preflight-probe"))
    preflight.add_argument("--report", type=Path, default=Path("outputs/preflight.json"))
    preflight.add_argument("--orbit-backends", nargs="+", choices=("astropy", "skyfield"), default=("astropy", "skyfield"))
    preflight.add_argument("--magnetic-backends", nargs="+", choices=("aacgmv2", "apexpy"), default=("aacgmv2", "apexpy"))
    preflight.add_argument("--input-manifest", type=Path, default=None)
    preflight.add_argument("--version-policy", type=Path, default=None)
    preflight.add_argument("--expected-python", default=None)
    preflight.add_argument("--minimum-free-gb", type=float, default=1.0)
    install_report = commands.add_parser(
        "installation-report", help="record ApexPy native binary and dependency evidence"
    )
    install_report.add_argument("--apex-wheel", type=Path, default=None)
    install_report.add_argument("--output", type=Path, required=True)
    compare = commands.add_parser("compare-sessions", help="combine strictly comparable device sessions")
    compare.add_argument("sessions", nargs="+", type=Path)
    compare.add_argument("--output-dir", type=Path, required=True)
    full = commands.add_parser(
        "validate-full", help="certify the complete input-to-products workload"
    )
    full.add_argument("--project-root", type=Path, default=Path("."))
    full.add_argument("--output-dir", type=Path, default=Path("outputs/full-validation"))
    full.add_argument("--measurements", type=Path, default=Path("data/raw/langmuir-2018-2.csv"))
    full.add_argument("--tle", type=Path, default=Path("data/tle/suchai1.tle"))
    full.add_argument("--eop", type=Path, default=Path("data/eop/finals2000A.all"))
    full.add_argument("--plot-config", type=Path, default=Path("configs/plots/archive-full.json"))
    full.add_argument("--symh", type=Path, default=Path("data/external/OMNI_HRO_1MIN_2527270.txt"))
    full.add_argument("--no-symh", action="store_true")
    full.add_argument("--limit", type=int, default=None)
    orbit_benchmark = commands.add_parser(
        "benchmark-orbits", help="run repeated randomized clean-process orbit diagnostics"
    )
    orbit_benchmark.add_argument("--project-root", type=Path, default=Path("."))
    orbit_benchmark.add_argument("--output-dir", type=Path, default=Path("outputs/orbit-benchmark-suite"))
    orbit_benchmark.add_argument("--measurements", type=Path, default=Path("data/raw/langmuir-2018-2.csv"))
    orbit_benchmark.add_argument("--tle", type=Path, default=Path("data/tle/suchai1.tle"))
    orbit_benchmark.add_argument("--eop", type=Path, default=Path("data/eop/finals2000A.all"))
    orbit_benchmark.add_argument("--repeats", type=int, default=5)
    orbit_benchmark.add_argument("--warmups", type=int, default=1)
    orbit_benchmark.add_argument("--seed", type=int, default=1729)
    orbit_benchmark.add_argument("--limit", type=int, default=None)
    orbit_benchmark.add_argument("--timeout-seconds", type=float, default=7200.0)
    commands.add_parser("capabilities", help="report optional backend availability")
    return parser


def _capabilities() -> dict[str, bool]:
    """Return import availability without loading heavyweight libraries."""

    return {
        "orbit_astropy": all(importlib.util.find_spec(name) is not None for name in ("astropy", "sgp4")),
        "orbit_skyfield": all(importlib.util.find_spec(name) is not None for name in ("skyfield", "sgp4")),
        "magnetic_aacgmv2": importlib.util.find_spec("aacgmv2") is not None,
        "magnetic_apexpy": importlib.util.find_spec("apexpy") is not None,
        "benchmark_psutil": importlib.util.find_spec("psutil") is not None,
    }


def main(argv: list[str] | None = None) -> int:
    """Run the requested command and convert expected failures to clean errors."""

    arguments = _parser().parse_args(argv)
    if arguments.command == "capabilities":
        print(json.dumps(_capabilities(), indent=2))
        return 0
    if arguments.command == "preflight":
        from .preflight import run_preflight, write_preflight

        result = run_preflight(
            arguments.project_root, arguments.output_dir,
            tuple(arguments.orbit_backends), tuple(arguments.magnetic_backends),
            arguments.input_manifest, arguments.version_policy,
            int(arguments.minimum_free_gb * 1_000_000_000), arguments.expected_python,
        )
        write_preflight(result, arguments.report)
        print(json.dumps({"status": result["status"], "report": str(arguments.report), "failed_checks": result["failed_checks"]}, indent=2))
        return 0 if result["status"] == "pass" else 2
    if arguments.command == "installation-report":
        from .install_report import create_installation_report, write_installation_report

        result = create_installation_report(arguments.apex_wheel)
        write_installation_report(result, arguments.output)
        print(json.dumps({"status": result["status"], "report": str(arguments.output)}, indent=2))
        return 0 if result["status"] == "pass" else 2
    if arguments.command == "compare-sessions":
        from .comparison import compare_sessions

        result = compare_sessions(arguments.sessions, arguments.output_dir)
        print(json.dumps({"status": result["status"], "report": result["report_path"], "mismatch_count": len(result["mismatches"])}, indent=2))
        return 0 if result["status"] == "comparable" else 2
    if arguments.command == "validate-full":
        from .full_validation import run_full_validation

        result = run_full_validation(
            arguments.output_dir, arguments.project_root, arguments.measurements,
            arguments.tle, arguments.eop, arguments.plot_config,
            None if arguments.no_symh else arguments.symh, arguments.limit,
        )
        print(json.dumps({
            "status": result["status"], "certificate": result["certificate_path"],
            "criteria": len(result["criteria"]),
        }, indent=2))
        return 0 if result["status"] == "pass" else 2
    if arguments.command == "benchmark-orbits":
        from .orbit_benchmark import run_orbit_benchmark

        result = run_orbit_benchmark(
            arguments.output_dir, arguments.project_root, arguments.measurements,
            arguments.tle, arguments.eop, arguments.repeats, arguments.warmups,
            arguments.seed, arguments.limit, arguments.timeout_seconds,
        )
        print(json.dumps({
            "status": result["status"], "report": result["report_path"],
            "scientific_outputs_consistent": result["scientific_outputs_consistent"],
        }, indent=2))
        return 0 if result["status"] == "complete" else 2
    if arguments.command == "validate-orbits":
        from .validation import validate_orbit_backends

        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        result = validate_orbit_backends(
            arguments.measurements, arguments.tle, arguments.eop, arguments.output,
            arguments.limit, arguments.benchmark_output, arguments.differences_output,
            arguments.plots_output_dir,
        )
        print(json.dumps(result, indent=2))
        return 0
    if arguments.command == "validate-magnetic":
        from .validation import validate_magnetic_backends

        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.benchmark_output.parent.mkdir(parents=True, exist_ok=True)
        result = validate_magnetic_backends(
            arguments.measurements, arguments.tle, arguments.eop, arguments.orbit_backend,
            arguments.output, arguments.benchmark_output, arguments.limit,
            arguments.differences_output,
        )
        print(json.dumps(result, indent=2))
        return 0
    if arguments.command == "plot-symh":
        from datetime import datetime, timezone
        from .symh import load_symh, plot_symh

        def parse_time(value):
            if value is None:
                return None
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)

        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        times, values = load_symh(arguments.input)
        result = plot_symh(
            times, values, arguments.output, parse_time(arguments.start), parse_time(arguments.end)
        )
        print(json.dumps(result, indent=2))
        return 0
    if arguments.command == "benchmark-suite":
        from .benchmark_suite import run_benchmark_suite

        result = run_benchmark_suite(
            output_dir=arguments.output_dir, measurements=arguments.measurements,
            tle=arguments.tle, eop=arguments.eop,
            orbit_backends=tuple(arguments.orbit_backends),
            magnetic_backends=tuple(arguments.magnetic_backends),
            plot_config=arguments.plot_config,
            repeats=(arguments.repeats if arguments.repeats is not None else
                     (None if arguments.duration_seconds is not None else 3)),
            warmups=arguments.warmups, seed=arguments.seed, limit=arguments.limit,
            cooldown_seconds=arguments.cooldown_seconds,
            timeout_seconds=arguments.timeout_seconds, collect_perf=arguments.perf,
            cooldown_until_c=arguments.cooldown_until_c,
            cooldown_max_seconds=arguments.cooldown_max_seconds,
            device_label=arguments.device_label, notes=arguments.notes,
            project_root=arguments.project_root,
            official=arguments.official,
            validation_certificate=arguments.validation_certificate,
            duration_seconds=arguments.duration_seconds,
            telemetry_interval_seconds=arguments.telemetry_interval_seconds,
            minimum_free_bytes=int(arguments.minimum_free_gb * 1_000_000_000),
            maximum_temperature_c=arguments.maximum_temperature_c,
            continue_on_error=arguments.continue_on_error,
            max_consecutive_failures=arguments.max_consecutive_failures,
            resume=arguments.resume,
        )
        summary = {
            "report_path": result["report_path"],
            "scientific_outputs_consistent": result["scientific_outputs_consistent"],
            "scenarios": list(result["scenarios"]),
        }
        print(json.dumps(summary, indent=2))
        return 0 if result["status"] == "complete" and result["scientific_outputs_consistent"] else 2
    try:
        outputs = run_analysis(
            measurement_path=arguments.measurements,
            tle_path=arguments.tle,
            eop_path=arguments.eop,
            output_dir=arguments.output_dir,
            orbit_backend=arguments.orbit_backend,
            magnetic_backend=arguments.magnetic_backend,
            limit=arguments.limit,
            particle_threshold=arguments.particle_threshold,
            plot_config_path=arguments.plot_config,
            benchmark=arguments.benchmark,
        )
    except (PCSException, ValueError) as exc:
        _parser().error(str(exc))
    print(json.dumps(outputs.__dict__, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
