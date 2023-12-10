from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pytest

from py_discovery import PythonInfo
from py_discovery._info import EXTENSIONS, fs_is_case_sensitive

CURRENT = PythonInfo.current()


def test_discover_empty_folder(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        CURRENT.discover_exe(prefix=str(tmp_path))


BASE = (CURRENT.install_path("scripts"), ".")


@pytest.mark.usefixtures("_fs_supports_symlink")
@pytest.mark.parametrize("suffix", sorted({".exe", ".cmd", ""} & set(EXTENSIONS) if sys.platform == "win32" else [""]))
@pytest.mark.parametrize("into", BASE)
@pytest.mark.parametrize("arch", [CURRENT.architecture, ""])
@pytest.mark.parametrize("version", [".".join(str(i) for i in CURRENT.version_info[0:i]) for i in range(3, 0, -1)])
@pytest.mark.parametrize("impl", [CURRENT.implementation, "python"])
def test_discover_ok(  # noqa: PLR0913
    tmp_path: Path,
    suffix: str,
    impl: str,
    version: str,
    arch: str,
    into: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    folder = tmp_path / into
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{impl}{version}"
    if arch:
        name += f"-{arch}"
    name += suffix
    dest = folder / name
    assert CURRENT.executable is not None
    os.symlink(CURRENT.executable, str(dest))
    pyvenv = Path(CURRENT.executable).parents[1] / "pyvenv.cfg"
    if pyvenv.exists():  # pragma: no branch
        (folder / pyvenv.name).write_text(pyvenv.read_text(encoding="utf-8"), encoding="utf-8")
    inside_folder = str(tmp_path)
    base = CURRENT.discover_exe(inside_folder)
    found = base.executable
    assert found is not None
    dest_str = str(dest)
    if not fs_is_case_sensitive():  # pragma: no branch
        found = found.lower()
        dest_str = dest_str.lower()
    assert found == dest_str
    assert len(caplog.messages) >= 1, caplog.text
    assert "get interpreter info via cmd: " in caplog.text

    dest.rename(dest.parent / (dest.name + "-1"))
    CURRENT._cache_exe_discovery.clear()  # noqa: SLF001
    with pytest.raises(RuntimeError):
        CURRENT.discover_exe(inside_folder)
