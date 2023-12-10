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
    caplog.set_level(logging.DEBUG)  # pragma: no cover
    current = PythonInfo.current_system()  # pragma: no cover
    core = f"somethingVeryCryptic{'.'.join(str(i) for i in current.version_info[0:3])}"  # pragma: no cover
    name = "somethingVeryCryptic"  # pragma: no cover
    if case == "lower":  # pragma: no cover
        name = name.lower()  # pragma: no cover
    elif case == "upper":  # pragma: no cover
        name = name.upper()  # pragma: no cover
    exe_name = f"{name}{current.version_info.major}{'.exe' if sys.platform == 'win32' else ''}"  # pragma: no cover
    target = tmp_path / current.install_path("scripts")  # pragma: no cover
    target.mkdir(parents=True)  # pragma: no cover
    executable = target / exe_name  # pragma: no cover
    os.symlink(sys.executable, str(executable))  # pragma: no cover
    pyvenv_cfg = Path(sys.executable).parents[1] / "pyvenv.cfg"  # pragma: no cover
    if pyvenv_cfg.exists():  # pragma: no cover
        (target / pyvenv_cfg.name).write_bytes(pyvenv_cfg.read_bytes())  # pragma: no cover
    new_path = os.pathsep.join([str(target), *os.environ.get("PATH", "").split(os.pathsep)])  # pragma: no cover
    monkeypatch.setenv("PATH", new_path)  # pragma: no cover
    interpreter = get_interpreter(core, [])  # pragma: no cover

    assert interpreter is not None  # pragma: no cover


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
