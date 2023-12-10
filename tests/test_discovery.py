from __future__ import annotations

import logging
import os
import sys
from argparse import Namespace
from pathlib import Path
from uuid import uuid4

import pytest

from py_discovery import Builtin, PythonInfo, get_interpreter


@pytest.mark.usefixtures("_fs_supports_symlink")
@pytest.mark.parametrize("case", ["mixed", "lower", "upper"])
def test_discovery_via_path(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    current = PythonInfo.current_system()
    core = f"somethingVeryCryptic{'.'.join(str(i) for i in current.version_info[0:3])}"
    name = "somethingVeryCryptic"
    if case == "lower":
        name = name.lower()
    elif case == "upper":
        name = name.upper()
    exe_name = f"{name}{current.version_info.major}{'.exe' if sys.platform == 'win32' else ''}"
    target = tmp_path / current.install_path("scripts")
    target.mkdir(parents=True)
    executable = target / exe_name
    os.symlink(sys.executable, str(executable))
    pyvenv_cfg = Path(sys.executable).parents[1] / "pyvenv.cfg"
    if pyvenv_cfg.exists():  # pragma: no branch
        (target / pyvenv_cfg.name).write_bytes(pyvenv_cfg.read_bytes())  # pragma: no cover
    new_path = os.pathsep.join([str(target), *os.environ.get("PATH", "").split(os.pathsep)])
    monkeypatch.setenv("PATH", new_path)
    interpreter = get_interpreter(core, [])

    assert interpreter is not None


def test_discovery_via_path_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    interpreter = get_interpreter(uuid4().hex, [])
    assert interpreter is None


def test_relative_path(monkeypatch: pytest.MonkeyPatch) -> None:
    sys_executable_str = PythonInfo.current_system().system_executable
    assert sys_executable_str is not None
    sys_executable = Path(sys_executable_str)
    cwd = sys_executable.parents[1]
    monkeypatch.chdir(str(cwd))
    relative = str(sys_executable.relative_to(cwd))
    result = get_interpreter(relative, [])
    assert result is not None


def test_discovery_fallback_fail(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    builtin = Builtin(Namespace(try_first_with=[], python=["magic-one", "magic-two"], env=os.environ))

    result = builtin.run()
    assert result is None

    assert "accepted" not in caplog.text


def test_discovery_fallback_ok(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    builtin = Builtin(Namespace(try_first_with=[], python=["magic-one", sys.executable], env=os.environ))

    result = builtin.run()
    assert result is not None, caplog.text
    assert result.executable == sys.executable, caplog.text

    assert "accepted" in caplog.text
