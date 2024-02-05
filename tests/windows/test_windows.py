from __future__ import annotations

import sys
import textwrap
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator, Tuple, cast

import pytest

from py_discovery import PythonInfo, PythonSpec, VersionInfo
from py_discovery._windows import discover_pythons, pep514, propose_interpreters  # type: ignore[attr-defined]

if TYPE_CHECKING:
    from types import TracebackType

    from pytest_mock import MockerFixture

    if sys.version_info >= (3, 11):  # pragma: no cover (py311+)
        from typing import Self
    else:  # pragma: no cover (<py311)
        from typing_extensions import Self


@pytest.fixture()
def _mock_registry(mocker: MockerFixture) -> None:  # noqa: C901
    loc: dict[str, Any] = {}
    glob: dict[str, Any] = {}
    mock_value_str = (Path(__file__).parent / "winreg-mock-values.py").read_text(encoding="utf-8")
    exec(mock_value_str, glob, loc)  # noqa: S102
    enum_collect: dict[int, list[str | OSError]] = loc["enum_collect"]
    value_collect: dict[int, dict[str, tuple[str, int] | OSError]] = loc["value_collect"]
    key_open: dict[int, dict[str, int | OSError]] = loc["key_open"]
    hive_open: dict[tuple[int, str, int, int], int | OSError] = loc["hive_open"]

    class Key:
        def __init__(self, value: int) -> None:
            self.value = value

        def __enter__(self) -> Self:
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: TracebackType | None,
        ) -> None:
            return None

    def _enum_key(key: int | Key, at: int) -> str:
        key_id = key.value if isinstance(key, Key) else key
        result = enum_collect[key_id][at]
        if isinstance(result, OSError):
            raise result
        return result

    def _query_value_ex(key: Key, value_name: str) -> tuple[str, int]:
        key_id = key.value if isinstance(key, Key) else key
        result = value_collect[key_id][value_name]
        if isinstance(result, OSError):
            raise result
        return result

    @contextmanager
    def _open_key_ex(*args: str | int) -> Iterator[Key | int]:
        if len(args) == 2:
            key, value = cast(int, args[0]), cast(str, args[1])
            key_id = key.value if isinstance(key, Key) else key
            got = key_open[key_id][value]
            if isinstance(got, OSError):
                raise got
            yield Key(got)  # this needs to be something that can be withed, so let's wrap it
        elif len(args) == 4:  # pragma: no branch
            got = hive_open[cast(Tuple[int, str, int, int], args)]
            if isinstance(got, OSError):
                raise got
            yield got
        else:
            raise RuntimeError  # pragma: no cover

    mocker.patch("py_discovery._windows.pep514.EnumKey", side_effect=_enum_key)
    mocker.patch("py_discovery._windows.pep514.QueryValueEx", side_effect=_query_value_ex)
    mocker.patch("py_discovery._windows.pep514.OpenKeyEx", side_effect=_open_key_ex)
    mocker.patch("os.path.exists", return_value=True)


@pytest.mark.usefixtures("_mock_registry")
@pytest.mark.parametrize(
    ("string_spec", "expected_exe"),
    [
        # 64-bit over 32-bit
        ("python3.10", "C:\\Users\\user\\Miniconda3-64\\python.exe"),
        ("cpython3.10", "C:\\Users\\user\\Miniconda3-64\\python.exe"),
        # 1 installation of 3.9 available
        ("python3.12", "C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python312\\python.exe"),
        ("cpython3.12", "C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python312\\python.exe"),
        # resolves to the highest available version
        ("python", "C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python312\\python.exe"),
        ("cpython", "C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python312\\python.exe"),
        # Non-standard org name
        ("python3.6", "Z:\\CompanyA\\Python\\3.6\\python.exe"),
        ("cpython3.6", "Z:\\CompanyA\\Python\\3.6\\python.exe"),
    ],
)
def test_propose_interpreters(string_spec: str, expected_exe: str, mocker: MockerFixture) -> None:
    mocker.patch("sys.platform", "win32")
    mocker.patch("sysconfig.get_config_var", return_value=f"{sys.version_info.major}{sys.version_info}")
    mocker.patch("sysconfig.get_makefile_filename", return_value="make")

    spec = PythonSpec.from_string_spec(string_spec)
    mocker.patch(
        "py_discovery._windows.Pep514PythonInfo.from_exe",
        return_value=_mock_pyinfo(spec.major, spec.minor, spec.architecture, expected_exe),
    )

    interpreter = next(propose_interpreters(spec, env={}))
    assert interpreter.executable == expected_exe


def _mock_pyinfo(major: int | None, minor: int | None, arch: int | None, exe: str) -> PythonInfo:
    """Return PythonInfo objects with essential metadata set for the given args."""
    info = PythonInfo()
    info.base_prefix = str(Path(exe).parent)
    info.executable = info.original_executable = info.system_executable = exe
    info.implementation = "CPython"
    info.architecture = arch or 64
    info.version_info = VersionInfo(major, minor, 0, "final", 0)
    return info


@pytest.mark.usefixtures("_mock_registry")
def test_pep514() -> None:
    interpreters = list(discover_pythons())
    assert interpreters == [
        ("ContinuumAnalytics", 3, 10, 32, "C:\\Users\\user\\Miniconda3\\python.exe", None),
        ("ContinuumAnalytics", 3, 10, 64, "C:\\Users\\user\\Miniconda3-64\\python.exe", None),
        ("PythonCore", 3, 9, 64, "C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python39\\python.exe", None),
        ("PythonCore", 3, 9, 64, "C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python39\\python.exe", None),
        ("PythonCore", 3, 8, 64, "C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python38\\python.exe", None),
        ("PythonCore", 3, 9, 64, "C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python39\\python.exe", None),
        ("PythonCore", 3, 10, 32, "C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python310-32\\python.exe", None),
        ("PythonCore", 3, 12, 64, "C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python312\\python.exe", None),
        ("CompanyA", 3, 6, 64, "Z:\\CompanyA\\Python\\3.6\\python.exe", None),
        ("PythonCore", 2, 7, 64, "C:\\Python27\\python.exe", None),
        ("PythonCore", 3, 7, 64, "C:\\Python37\\python.exe", None),
    ]


@pytest.mark.usefixtures("_mock_registry")
def test_pep514_run(capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture) -> None:
    pep514._run()  # noqa: SLF001
    out, err = capsys.readouterr()
    expected = textwrap.dedent(
        r"""
    ('CompanyA', 3, 6, 64, 'Z:\\CompanyA\\Python\\3.6\\python.exe', None)
    ('ContinuumAnalytics', 3, 10, 32, 'C:\\Users\\user\\Miniconda3\\python.exe', None)
    ('ContinuumAnalytics', 3, 10, 64, 'C:\\Users\\user\\Miniconda3-64\\python.exe', None)
    ('PythonCore', 2, 7, 64, 'C:\\Python27\\python.exe', None)
    ('PythonCore', 3, 10, 32, 'C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python310-32\\python.exe', None)
    ('PythonCore', 3, 12, 64, 'C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python312\\python.exe', None)
    ('PythonCore', 3, 7, 64, 'C:\\Python37\\python.exe', None)
    ('PythonCore', 3, 8, 64, 'C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python38\\python.exe', None)
    ('PythonCore', 3, 9, 64, 'C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python39\\python.exe', None)
    ('PythonCore', 3, 9, 64, 'C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python39\\python.exe', None)
    ('PythonCore', 3, 9, 64, 'C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python39\\python.exe', None)
    """,
    ).strip()
    assert out.strip() == expected
    assert not err
    prefix = "PEP-514 violation in Windows Registry at "
    expected_logs = [
        f"{prefix}HKEY_CURRENT_USER/PythonCore/3.1/SysArchitecture error: invalid format magic",
        f"{prefix}HKEY_CURRENT_USER/PythonCore/3.2/SysArchitecture error: arch is not string: 100",
        f"{prefix}HKEY_CURRENT_USER/PythonCore/3.3 error: no ExecutablePath or default for it",
        f"{prefix}HKEY_CURRENT_USER/PythonCore/3.3 error: could not load exe with value None",
        f"{prefix}HKEY_CURRENT_USER/PythonCore/3.11/InstallPath error: missing",
        f"{prefix}HKEY_CURRENT_USER/PythonCore/3.12/SysVersion error: invalid format magic",
        f"{prefix}HKEY_CURRENT_USER/PythonCore/3.X/SysVersion error: version is not string: 2778",
        f"{prefix}HKEY_CURRENT_USER/PythonCore/3.X error: invalid format 3.X",
    ]
    assert caplog.messages == expected_logs
