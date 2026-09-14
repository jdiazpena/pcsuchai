"""Installer-only regression checks; no packages or scientific analyses are run."""

import importlib.metadata as metadata
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/install_rpi.sh"


def _heredocs() -> list[str]:
    """Extract Python snippets for tests using fake package metadata/paths."""

    return re.findall(r"<<'PY'\n(.*?)\nPY", SCRIPT.read_text(), flags=re.S)


def test_installer_shell_and_embedded_python_syntax() -> None:
    import ast

    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
    for source in _heredocs():
        ast.parse(source)


def test_installer_uses_global_pip_and_does_not_upgrade_pip_itself() -> None:
    source = SCRIPT.read_text()
    assert "PIP_ARGS=(--user" not in source
    assert "--upgrade pip" not in source
    assert "GLOBAL_PYTHON=(sudo -H" in source
    assert "--ignore-installed" in source
    assert "export PATH=\"/usr/local/bin:/usr/bin:/bin:$PATH\"" in source
    assert "--no-build-isolation" in source
    assert "optional-quadmath.patch" in source
    assert source.index("pip check") < source.index("Installation complete")


def test_no_typing_dependencies_are_added_to_a_clean_pi(monkeypatch, capsys) -> None:
    def missing(name):
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "distribution", missing)
    exec(compile(_heredocs()[1], str(SCRIPT), "exec"), {})
    assert capsys.readouterr().out == ""


def test_reported_types_seaborn_missing_dependency_is_repaired(monkeypatch, capsys) -> None:
    def installed(name):
        if name == "types-seaborn":
            return types.SimpleNamespace(requires=["pandas-stubs>=2.0", "types-python-dateutil"])
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "distribution", installed)
    exec(compile(_heredocs()[1], str(SCRIPT), "exec"), {})
    assert capsys.readouterr().out.strip() == "pandas-stubs>=2.0"


@pytest.mark.parametrize("library_path,allowed", [
    ("/usr/local/lib/python3.13/dist-packages", True),
    ("/usr/lib/python3/dist-packages", False),
    ("/home/pi/.local/lib/python3.13/site-packages", False),
])
def test_global_destination_guard(monkeypatch, library_path, allowed) -> None:
    monkeypatch.setattr(sys, "prefix", "/usr")
    monkeypatch.setattr(sys, "base_prefix", "/usr")
    locations = types.ModuleType("pip._internal.locations")
    locations.get_scheme = lambda *args, **kwargs: types.SimpleNamespace(
        purelib=library_path, platlib=library_path, scripts="/usr/local/bin",
        data="/usr/local", headers="/usr/include/python3.13/pcsuchai",
    )
    monkeypatch.setitem(sys.modules, "pip._internal.locations", locations)
    source = compile(_heredocs()[2], str(SCRIPT), "exec")
    if allowed:
        exec(source, {})
    else:
        with pytest.raises(SystemExit, match="Unsafe global pip destination"):
            exec(source, {})
