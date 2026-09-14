"""Installer-only regression checks; no packages or scientific analyses are run."""

import importlib.util
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest
from packaging.markers import default_environment
from packaging.requirements import Requirement


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/install_rpi.sh"
DEPENDENCY_SCRIPT = ROOT / "scripts/check_dependencies.py"
SPEC = importlib.util.spec_from_file_location("check_dependencies", DEPENDENCY_SCRIPT)
DEPENDENCIES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DEPENDENCIES)


def _heredocs() -> list[str]:
    """Extract Python snippets for tests using fake package metadata/paths."""

    return re.findall(r"<<'PY'\n(.*?)\nPY", SCRIPT.read_text(), flags=re.S)


def test_installer_shell_and_embedded_python_syntax() -> None:
    import ast

    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
    for source in _heredocs():
        ast.parse(source)


def test_installer_uses_normal_global_pip_and_checks_only_suchai() -> None:
    source = SCRIPT.read_text()
    assert "PYTHON_BIN=/usr/bin/python3" in source
    assert "PIP_ARGS=(--user" not in source
    assert "--upgrade pip" not in source
    assert "GLOBAL_PYTHON=(sudo -H" in source
    assert "--break-system-packages" in source
    assert "--ignore-installed" not in source
    assert "--force-reinstall" not in source
    assert "pip._internal" not in source
    assert "pip check" not in source
    assert "types-seaborn" not in source
    assert "pandas-stubs" not in source
    assert "export PATH=\"/usr/local/bin:/usr/bin:/bin:$PATH\"" in source
    assert "--no-build-isolation" in source
    assert "optional-quadmath.patch" in source
    assert source.index("1/3:") < source.index("2/3:") < source.index("3/3:")
    assert source.index("scripts/check_dependencies.py") < source.index("Installation complete")


def test_global_install_command_does_not_force_or_use_user_install() -> None:
    source = SCRIPT.read_text()
    helper = re.search(r"global_pip_install\(\) \{\n.*?\n\}", source, flags=re.S).group()
    shell = '\n'.join([
        'sudo() { printf "%s\\n" "$@"; }',
        'GLOBAL_PYTHON=(sudo -H /usr/bin/python3 -s)',
        helper,
        'global_pip_install --requirement requirements/rpi-common.txt',
    ])
    result = subprocess.run(["bash", "-c", shell], check=True, capture_output=True, text=True)
    assert result.stdout.splitlines() == [
        "-H", "/usr/bin/python3", "-s", "-m", "pip", "--isolated", "install",
        "--break-system-packages", "--requirement", "requirements/rpi-common.txt",
    ]


@pytest.mark.parametrize("dependency_exit", [0, 5])
def test_complete_installer_cached_wheel_flow_with_mocked_system_commands(tmp_path, dependency_exit) -> None:
    """Exercise real shell control flow without apt, pip, imports or native builds."""

    root = tmp_path / "pcsuchai"
    script = root / "scripts/install_rpi.sh"
    script.parent.mkdir(parents=True)
    script.write_text(SCRIPT.read_text().replace(
        "PYTHON_BIN=/usr/bin/python3", "PYTHON_BIN=mock_python",
    ))
    wheel = root / "vendor/wheels/aarch64-cp313/apexpy-2.1.1-cp313-cp313-linux_aarch64.whl"
    wheel.parent.mkdir(parents=True)
    wheel.write_bytes(b"mock cached native wheel; never imported")
    bootstrap = r'''
mock_python() {
    case "$*" in
        *platform.machine*) printf 'aarch64\n' ;;
        *sys.version_info*) printf 'cp313\n' ;;
        *scripts/check_dependencies.py*)
            printf 'MOCK SUCHAI dependency verification\n'
            return "$2"
            ;;
        *) printf 'MOCK PYTHON: %s\n' "$*" ;;
    esac
}
sudo() {
    printf 'MOCK SUDO: %s\n' "$*"
    if [[ "$1" == apt-get ]]; then return 0; fi
    shift
    "$@"
}
'''
    # Embed only this integer in the fake checker response. All paths are
    # supplied as argv; no external installation command can be executed.
    bootstrap = bootstrap.replace('return "$2"', f"return {dependency_exit}")
    bootstrap += '\ninstaller_test_path=$1\nshift\nsource "$installer_test_path"\n'
    result = subprocess.run(
        ["bash", "-c", bootstrap, "installer-test", str(script)],
        capture_output=True, text=True,
    )
    output = result.stdout + result.stderr
    assert result.returncode == dependency_exit
    assert output.index("1/3:") < output.index("2/3:") < output.index("3/3:")
    assert "MOCK SUDO: apt-get install" in output
    assert "--requirement requirements/rpi-common.txt" in output
    assert str(wheel) in output
    assert "MOCK SUCHAI dependency verification" in output
    assert "ApexPy source download" not in output
    if dependency_exit:
        assert "Installation complete" not in output
        assert "ERROR: installation failed during SUCHAI dependency" in output
    else:
        assert "Installation complete" in output
        assert "installation-report" in output
    assert wheel.read_bytes() == b"mock cached native wheel; never imported"
    assert len(list((root / "installation-reports").glob("*/install.log"))) == 1


def _fake_packages(monkeypatch, packages: dict) -> list[str]:
    """Supply only fake distribution metadata; never import scientific packages."""

    calls = []

    def installed(name):
        calls.append(name)
        if name not in packages:
            raise DEPENDENCIES.PackageNotFoundError(name)
        version, dependencies, *python_requirement = packages[name]
        return types.SimpleNamespace(
            version=version, requires=dependencies,
            metadata={"Requires-Python": python_requirement[0]} if python_requirement else {},
            locate_file=lambda path: f"/usr/local/lib/python3.13/dist-packages/{path}",
        )

    environment = {**default_environment(), "python_version": "3.13",
                   "python_full_version": "3.13.5", "sys_platform": "linux"}
    monkeypatch.setattr(DEPENDENCIES, "distribution", installed)
    monkeypatch.setattr(DEPENDENCIES, "default_environment", lambda: environment)
    return calls


def test_reported_unrelated_os_conflicts_do_not_block_suchai(monkeypatch) -> None:
    requirements = [
        text for line in (ROOT / "requirements/rpi-version-policy.txt").read_text().splitlines()
        if (text := line.split("#", 1)[0].strip())
    ]
    packages = {
        Requirement(line).name: (next(iter(Requirement(line).specifier)).version, ["common>=1"])
        for line in requirements
    }
    packages.update({
        "common": ("1.0", []),
        "types-seaborn": ("0.13.2", ["pandas-stubs"]),
        "types-flask-migrate": ("4.0", ["flask", "flask-sqlalchemy"]),
        "types-tree-sitter-languages": ("1.10", ["tree-sitter"]),
        "types-click-default-group": ("1.2", ["click"]),
        "apt-listchanges": ("4.8", ["debconf"]),
        "types-flask-cors": ("5.0", ["flask"]),
        "types-flask-socketio": ("5.4", ["flask"]),
    })
    calls = _fake_packages(monkeypatch, packages)
    result = DEPENDENCIES.check_dependencies(requirements)
    assert result["status"] == "pass"
    assert result["errors"] == []
    assert set(calls) == {Requirement(line).name for line in requirements} | {"common"}


@pytest.mark.parametrize("dependency,installed", [
    ("child>=1", None),
    ("child>=2", "1.0"),
])
def test_missing_or_incompatible_runtime_dependency_fails(monkeypatch, dependency, installed) -> None:
    packages = {"root": ("1.0", [dependency])}
    if installed is not None:
        packages["child"] = (installed, [])
    _fake_packages(monkeypatch, packages)
    result = DEPENDENCIES.check_dependencies(["root==1.0"])
    assert result["status"] == "fail"
    assert len(result["errors"]) == 1
    assert f"root requires {dependency}" in result["errors"][0]


def test_pinned_version_mismatch_fails(monkeypatch) -> None:
    _fake_packages(monkeypatch, {"root": ("1.1", [])})
    result = DEPENDENCIES.check_dependencies(["root==1.0"])
    assert result["status"] == "fail"
    assert "installed version is 1.1" in result["errors"][0]


def test_shared_dependency_checked_again_for_stricter_parent(monkeypatch) -> None:
    _fake_packages(monkeypatch, {
        "root": ("1.0", ["left", "right"]),
        "left": ("1.0", ["shared>=1"]),
        "right": ("1.0", ["shared>=2"]),
        "shared": ("1.5", []),
    })
    result = DEPENDENCIES.check_dependencies(["root==1.0"])
    assert result["status"] == "fail"
    assert "right requires shared>=2" in result["errors"][0]


def test_platform_and_unrequested_extra_dependencies_are_skipped(monkeypatch) -> None:
    calls = _fake_packages(monkeypatch, {"root": ("1.0", [
        "windows-only; sys_platform == 'win32'", "pytest; extra == 'test'",
    ])})
    assert DEPENDENCIES.check_dependencies(["root==1.0"])["status"] == "pass"
    assert calls == ["root"]


def test_requested_nested_extra_dependencies_are_checked(monkeypatch) -> None:
    _fake_packages(monkeypatch, {
        "root": ("1.0", ["child[science]"]),
        "child": ("1.0", ["required; extra == 'science'"]),
    })
    result = DEPENDENCIES.check_dependencies(["root==1.0"])
    assert result["status"] == "fail"
    assert "child requires required" in result["errors"][0]


def test_cycles_terminate(monkeypatch) -> None:
    calls = _fake_packages(monkeypatch, {
        "root": ("1.0", ["child"]), "child": ("1.0", ["root>=1"]),
    })
    assert DEPENDENCIES.check_dependencies(["root==1.0"])["status"] == "pass"
    assert calls == ["root", "child", "root"]


def test_incompatible_python_dependency_fails(monkeypatch) -> None:
    _fake_packages(monkeypatch, {"root": ("1.0", [], ">=3.14")})
    result = DEPENDENCIES.check_dependencies(["root==1.0"])
    assert result["status"] == "fail"
    assert "requires Python >=3.14: running 3.13.5" in result["errors"][0]


def test_empty_policy_does_not_pass() -> None:
    assert DEPENDENCIES.check_dependencies([])["status"] == "fail"


@pytest.mark.parametrize("installed,expected_status,expected_exit", [
    ("1.0", "pass", 0), ("1.1", "fail", 5),
])
def test_dependency_cli_saves_complete_report(monkeypatch, tmp_path, installed, expected_status, expected_exit) -> None:
    import json

    _fake_packages(monkeypatch, {"root": (installed, [])})
    policy = tmp_path / "policy.txt"
    report = tmp_path / "reports/dependencies.json"
    policy.write_text("# runtime pins\nroot==1.0 # preserved\n\n")
    monkeypatch.setattr(sys, "argv", [str(DEPENDENCY_SCRIPT), "--policy", str(policy), "--report", str(report)])
    assert DEPENDENCIES.main() == expected_exit
    result = json.loads(report.read_text())
    assert result["status"] == expected_status
    assert result["requirements"] == ["root==1.0"]
    assert result["packages"][0]["version"] == installed
