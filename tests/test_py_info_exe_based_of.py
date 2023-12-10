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
    caplog.set_level(logging.DEBUG)  # pragma: no cover
    folder = tmp_path / into  # pragma: no cover
    folder.mkdir(parents=True, exist_ok=True)  # pragma: no cover
    name = f"{impl}{version}"  # pragma: no cover
    if arch:  # pragma: no cover
        name += f"-{arch}"  # pragma: no cover
    name += suffix  # pragma: no cover
    dest = folder / name  # pragma: no cover
    assert CURRENT.executable is not None  # pragma: no cover
    os.symlink(CURRENT.executable, str(dest))  # pragma: no cover
    pyvenv = Path(CURRENT.executable).parents[1] / "pyvenv.cfg"  # pragma: no cover
    if pyvenv.exists():  # pragma: no cover
        (folder / pyvenv.name).write_text(pyvenv.read_text(encoding="utf-8"), encoding="utf-8")  # pragma: no cover
    inside_folder = str(tmp_path)  # pragma: no cover
    base = CURRENT.discover_exe(inside_folder)  # pragma: no cover
    found = base.executable  # pragma: no cover
    assert found is not None  # pragma: no cover
    dest_str = str(dest)  # pragma: no cover
    if not fs_is_case_sensitive():  # pragma: no cover
        found = found.lower()  # pragma: no cover
        dest_str = dest_str.lower()  # pragma: no cover
    assert found == dest_str  # pragma: no cover
    assert len(caplog.messages) >= 1, caplog.text  # pragma: no cover
    assert "get interpreter info via cmd: " in caplog.text  # pragma: no cover

    dest.rename(dest.parent / (dest.name + "-1"))  # pragma: no cover
    CURRENT._cache_exe_discovery.clear()  # noqa: SLF001 # pragma: no cover
    with pytest.raises(RuntimeError):  # pragma: no cover
        CURRENT.discover_exe(inside_folder)  # pragma: no cover
