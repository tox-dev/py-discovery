from __future__ import annotations

import copy
import functools
import itertools
import json
import logging
import os
import sys
import sysconfig
from pathlib import Path
from platform import python_implementation
from textwrap import dedent
from typing import TYPE_CHECKING, Mapping, NamedTuple, Tuple, cast

import pytest

from py_discovery import PythonInfo, PythonSpec, VersionInfo

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

CURRENT = PythonInfo.current_system()


def test_current_as_json() -> None:
    result = CURRENT._to_json()  # noqa: SLF001
    parsed = json.loads(result)
    a, b, c, d, e = sys.version_info
    assert parsed["version_info"] == {"major": a, "minor": b, "micro": c, "releaselevel": d, "serial": e}


def test_bad_exe_py_info_raise(tmp_path: Path) -> None:
    exe = str(tmp_path)
    with pytest.raises(RuntimeError) as context:
        PythonInfo.from_exe(exe)
    msg = str(context.value)
    assert "code" in msg
    assert exe in msg


def test_bad_exe_py_info_no_raise(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.NOTSET)
    exe = str(tmp_path)
    result = PythonInfo.from_exe(exe, raise_on_error=False)
    assert result is None
    out, _ = capsys.readouterr()
    assert not out
    messages = [r.message for r in caplog.records if r.name != "filelock"]
    assert len(messages) == 2
    msg = messages[0]
    assert "get interpreter info via cmd: " in msg
    msg = messages[1]
    assert str(exe) in msg
    assert "code" in msg


@pytest.mark.parametrize(
    "spec",
    itertools.chain(
        [sys.executable],
        [
            f"{impl}{'.'.join(str(i) for i in ver)}{arch}"
            for impl, ver, arch in itertools.product(
                (
                    [CURRENT.implementation]
                    + (["python"] if CURRENT.implementation == "CPython" else [])
                    + (
                        [CURRENT.implementation.lower()]
                        if CURRENT.implementation != CURRENT.implementation.lower()
                        else []
                    )
                ),
                [sys.version_info[0 : i + 1] for i in range(3)],
                ["", f"-{CURRENT.architecture}"],
            )
        ],
    ),
)
def test_satisfy_py_info(spec: str) -> None:
    parsed_spec = PythonSpec.from_string_spec(spec)
    matches = CURRENT.satisfies(parsed_spec, True)
    assert matches is True


def test_satisfy_not_arch() -> None:
    parsed_spec = PythonSpec.from_string_spec(
        f"{CURRENT.implementation}-{64 if CURRENT.architecture == 32 else 32}",
    )
    matches = CURRENT.satisfies(parsed_spec, True)
    assert matches is False


def _generate_not_match_current_interpreter_version() -> list[str]:
    result: list[str] = []
    for i in range(3):
        ver = cast(Tuple[int, ...], sys.version_info[0 : i + 1])
        for a in range(len(ver)):
            for o in [-1, 1]:
                temp = list(ver)
                temp[a] += o
                result.append(".".join(str(i) for i in temp))
    return result


_NON_MATCH_VER = _generate_not_match_current_interpreter_version()


@pytest.mark.parametrize("spec", _NON_MATCH_VER)
def test_satisfy_not_version(spec: str) -> None:
    parsed_spec = PythonSpec.from_string_spec(f"{CURRENT.implementation}{spec}")
    matches = CURRENT.satisfies(parsed_spec, True)
    assert matches is False


class PyInfoMock(NamedTuple):
    implementation: str
    architecture: int
    version_info: VersionInfo


@pytest.mark.parametrize(
    ("target", "position", "discovered"),
    [
        (
            PyInfoMock("CPython", 64, VersionInfo(3, 6, 8, "final", 0)),
            0,
            [
                PyInfoMock("CPython", 64, VersionInfo(3, 6, 9, "final", 0)),
                PyInfoMock("PyPy", 64, VersionInfo(3, 6, 8, "final", 0)),
            ],
        ),
        (
            PyInfoMock("CPython", 64, VersionInfo(3, 6, 8, "final", 0)),
            0,
            [
                PyInfoMock("CPython", 64, VersionInfo(3, 6, 9, "final", 0)),
                PyInfoMock("CPython", 32, VersionInfo(3, 6, 9, "final", 0)),
            ],
        ),
        (
            PyInfoMock("CPython", 64, VersionInfo(3, 8, 1, "final", 0)),
            0,
            [
                PyInfoMock("CPython", 32, VersionInfo(2, 7, 12, "rc", 2)),
                PyInfoMock("PyPy", 64, VersionInfo(3, 8, 1, "final", 0)),
            ],
        ),
    ],
)
def test_system_executable_no_exact_match(  # noqa: PLR0913
    target: PyInfoMock,
    position: int,
    discovered: list[PyInfoMock],
    tmp_path: Path,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Here we should fallback to other compatible"""
    caplog.set_level(logging.DEBUG)

    def _make_py_info(of: PyInfoMock) -> PythonInfo:
        base = copy.deepcopy(CURRENT)
        base.implementation = of.implementation
        base.version_info = of.version_info
        base.architecture = of.architecture
        base.system_executable = CURRENT.system_executable
        base.executable = CURRENT.system_executable
        base.base_executable = str(path)  # type: ignore[attr-defined] # we mock it on for the test
        return base

    discovered_with_path = {}
    names = []
    selected = None
    for pos, i in enumerate(discovered):
        path = tmp_path / str(pos)
        path.write_text("", encoding="utf-8")
        py_info = _make_py_info(i)
        if pos == position:
            selected = py_info
        discovered_with_path[str(path)] = py_info
        names.append(path.name)

    target_py_info = _make_py_info(target)
    mocker.patch.object(target_py_info, "_find_possible_exe_names", return_value=names)
    mocker.patch.object(target_py_info, "_find_possible_folders", return_value=[str(tmp_path)])

    def func(k: str, resolve_to_host: bool, raise_on_error: bool, env: Mapping[str, str]) -> PythonInfo:  # noqa: ARG001
        return discovered_with_path[k]

    mocker.patch.object(target_py_info, "from_exe", side_effect=func)
    target_py_info.real_prefix = str(tmp_path)

    target_py_info.system_executable = None
    target_py_info.executable = str(tmp_path)
    mapped = target_py_info._resolve_to_system(target_py_info)  # noqa: SLF001
    assert mapped.system_executable == CURRENT.system_executable
    found = discovered_with_path[mapped.base_executable]  # type: ignore[attr-defined] # we set it a few lines above
    assert found is selected

    assert caplog.records[0].msg == "discover exe for %s in %s"
    for record in caplog.records[1:-1]:
        assert record.message.startswith("refused interpreter ")
        assert record.levelno == logging.DEBUG

    warn_similar = caplog.records[-1]
    assert warn_similar.levelno == logging.DEBUG
    assert warn_similar.msg.startswith("no exact match found, chosen most similar")


def test_py_info_ignores_distutils_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    raw = f"""
    [install]
    prefix={tmp_path}{os.sep}prefix
    install_purelib={tmp_path}{os.sep}purelib
    install_platlib={tmp_path}{os.sep}platlib
    install_headers={tmp_path}{os.sep}headers
    install_scripts={tmp_path}{os.sep}scripts
    install_data={tmp_path}{os.sep}data
    """
    (tmp_path / "setup.cfg").write_text(dedent(raw), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    py_info = PythonInfo.from_exe(sys.executable)
    assert py_info is not None
    distutils = py_info.distutils_install
    # on newer pythons this is just empty
    for key, value in distutils.items():  # pragma: no branch
        assert not value.startswith(str(tmp_path)), f"{key}={value}"  # pragma: no cover


def test_discover_exe_on_path_non_spec_name_match(mocker: MockerFixture) -> None:
    suffixed_name = f"python{CURRENT.version_info.major}.{CURRENT.version_info.minor}m"
    if sys.platform == "win32":  # pragma: win32 cover
        assert CURRENT.original_executable is not None
        suffixed_name += Path(CURRENT.original_executable).suffix
    spec = PythonSpec.from_string_spec(suffixed_name)
    assert CURRENT.executable is not None
    mocker.patch.object(CURRENT, "original_executable", str(Path(CURRENT.executable).parent / suffixed_name))
    assert CURRENT.satisfies(spec, impl_must_match=True) is True


def test_discover_exe_on_path_non_spec_name_not_match(mocker: MockerFixture) -> None:
    suffixed_name = f"python{CURRENT.version_info.major}.{CURRENT.version_info.minor}m"
    if sys.platform == "win32":  # pragma: win32 cover
        assert CURRENT.original_executable is not None
        suffixed_name += Path(CURRENT.original_executable).suffix
    spec = PythonSpec.from_string_spec(suffixed_name)
    assert CURRENT.executable is not None
    mocker.patch.object(
        CURRENT,
        "original_executable",
        str(Path(CURRENT.executable).parent / f"e{suffixed_name}"),
    )
    assert CURRENT.satisfies(spec, impl_must_match=True) is False


if python_implementation() != "PyPy":  # pragma: pypy no cover

    def test_py_info_setuptools() -> None:
        from setuptools.dist import Distribution

        assert Distribution
        PythonInfo()


if CURRENT.system_executable is None:  # pragma: no branch

    def test_py_info_to_system_raises(  # pragma: no cover
        mocker: MockerFixture,  # pragma: no cover
        caplog: pytest.LogCaptureFixture,  # pragma: no cover
    ) -> None:  # pragma: no cover
        caplog.set_level(logging.DEBUG)  # pragma: no cover
        mocker.patch.object(PythonInfo, "_find_possible_folders", return_value=[])  # pragma: no cover
        result = PythonInfo.from_exe(sys.executable, raise_on_error=False)  # pragma: no cover
        assert result is None  # pragma: no cover
        log = caplog.records[-1]  # pragma: no cover
        assert log.levelno == logging.INFO  # pragma: no cover
        exe = sys.executable  # pragma: no cover
        expected = f"ignore {exe} due cannot resolve system due to RuntimeError('failed to detect "  # pragma: no cover
        assert expected in log.message  # pragma: no cover


def test_custom_venv_install_scheme_is_prefered(mocker: MockerFixture) -> None:
    # The paths in this test are Fedora paths, but we set them for nt as well, so the test also works on Windows,
    # despite the actual values are nonsense there.
    # Values were simplified to be compatible with all the supported Python versions.
    default_scheme = {
        "stdlib": "{base}/lib/python{py_version_short}",
        "platstdlib": "{platbase}/lib/python{py_version_short}",
        "purelib": "{base}/local/lib/python{py_version_short}/site-packages",
        "platlib": "{platbase}/local/lib/python{py_version_short}/site-packages",
        "include": "{base}/include/python{py_version_short}",
        "platinclude": "{platbase}/include/python{py_version_short}",
        "scripts": "{base}/local/bin",
        "data": "{base}/local",
    }
    venv_scheme = {key: path.replace("local", "") for key, path in default_scheme.items()}
    sysconfig_install_schemes = {
        "posix_prefix": default_scheme,
        "nt": default_scheme,
        "pypy": default_scheme,
        "pypy_nt": default_scheme,
        "venv": venv_scheme,
    }
    if getattr(sysconfig, "get_preferred_scheme", None):  # pragma: no branch
        # define the prefix as sysconfig.get_preferred_scheme did before 3.11
        sysconfig_install_schemes["nt" if os.name == "nt" else "posix_prefix"] = default_scheme  # pragma: no cover

    # On Python < 3.10, the distutils schemes are not derived from sysconfig schemes, so we mock them as well to assert
    # the custom "venv" install scheme has priority
    distutils_scheme = {
        "purelib": "$base/local/lib/python$py_version_short/site-packages",
        "platlib": "$platbase/local/lib/python$py_version_short/site-packages",
        "headers": "$base/include/python$py_version_short/$dist_name",
        "scripts": "$base/local/bin",
        "data": "$base/local",
    }
    distutils_schemes = {
        "unix_prefix": distutils_scheme,
        "nt": distutils_scheme,
    }

    # We need to mock distutils first, so they don't see the mocked sysconfig,
    # if imported for the first time.
    # That can happen if the actual interpreter has the "venv" INSTALL_SCHEME
    # and hence this is the first time we are touching distutils in this process.
    # If distutils saw our mocked sysconfig INSTALL_SCHEMES, we would need
    # to define all install schemes.
    mocker.patch("distutils.command.install.INSTALL_SCHEMES", distutils_schemes)
    mocker.patch("sysconfig._INSTALL_SCHEMES", sysconfig_install_schemes)

    pyinfo = PythonInfo()
    pyver = f"{pyinfo.version_info.major}.{pyinfo.version_info.minor}"
    assert pyinfo.install_path("scripts") == "bin"
    assert pyinfo.install_path("purelib").replace(os.sep, "/") == f"lib/python{pyver}/site-packages"


if sys.version_info[:2] >= (3, 11):  # pragma: >=3.11 cover # pytest.skip doesn't support covdefaults
    if sys.platform != "win32":  # pragma: win32 no cover # pytest.skip doesn't support covdefaults

        def test_fallback_existent_system_executable(mocker: MockerFixture) -> None:
            current = PythonInfo()
            # Posix may execute a "python" out of a venv but try to set the base_executable
            # to "python" out of the system installation path. PEP 394 informs distributions
            # that "python" is not required and the standard `make install` does not provide one

            # Falsify some data to look like we're in a venv
            current.prefix = current.exec_prefix = "/tmp/tmp.izZNCyINRj/venv"  # noqa: S108
            exe = os.path.join(current.prefix, "bin/python")  # noqa: PTH118
            current.executable = current.original_executable = exe

            # Since we don't know if the distribution we're on provides python, use a binary that should not exist
            assert current.system_executable is not None
            mocker.patch.object(
                sys,
                "_base_executable",
                os.path.join(os.path.dirname(current.system_executable), "idontexist"),  # noqa: PTH118,PTH120
            )
            mocker.patch.object(sys, "executable", current.executable)

            # ensure it falls back to an alternate binary name that exists
            current._fast_get_system_executable()  # noqa: SLF001
            assert current.system_executable is not None
            assert os.path.basename(current.system_executable) in [  # noqa: PTH119
                f"python{v}"
                for v in (current.version_info.major, f"{current.version_info.major}.{current.version_info.minor}")
            ]
            assert current.system_executable is not None
            assert os.path.exists(current.system_executable)  # noqa: PTH110


@pytest.mark.skipif(sys.version_info[:2] != (3, 10), reason="Only runs on Python 3.10")  # pragma: ==3.10 cover
def test_uses_posix_prefix_on_debian_3_10_without_venv(mocker: MockerFixture) -> None:
    # this is taken from ubuntu 22.04 /usr/lib/python3.10/sysconfig.py
    sysconfig_install_schemes = {
        "posix_prefix": {
            "stdlib": "{installed_base}/{platlibdir}/python{py_version_short}",
            "platstdlib": "{platbase}/{platlibdir}/python{py_version_short}",
            "purelib": "{base}/lib/python{py_version_short}/site-packages",
            "platlib": "{platbase}/{platlibdir}/python{py_version_short}/site-packages",
            "include": "{installed_base}/include/python{py_version_short}{abiflags}",
            "platinclude": "{installed_platbase}/include/python{py_version_short}{abiflags}",
            "scripts": "{base}/bin",
            "data": "{base}",
        },
        "posix_home": {
            "stdlib": "{installed_base}/lib/python",
            "platstdlib": "{base}/lib/python",
            "purelib": "{base}/lib/python",
            "platlib": "{base}/lib/python",
            "include": "{installed_base}/include/python",
            "platinclude": "{installed_base}/include/python",
            "scripts": "{base}/bin",
            "data": "{base}",
        },
        "nt": {
            "stdlib": "{installed_base}/Lib",
            "platstdlib": "{base}/Lib",
            "purelib": "{base}/Lib/site-packages",
            "platlib": "{base}/Lib/site-packages",
            "include": "{installed_base}/Include",
            "platinclude": "{installed_base}/Include",
            "scripts": "{base}/Scripts",
            "data": "{base}",
        },
        "deb_system": {
            "stdlib": "{installed_base}/{platlibdir}/python{py_version_short}",
            "platstdlib": "{platbase}/{platlibdir}/python{py_version_short}",
            "purelib": "{base}/lib/python3/dist-packages",
            "platlib": "{platbase}/{platlibdir}/python3/dist-packages",
            "include": "{installed_base}/include/python{py_version_short}{abiflags}",
            "platinclude": "{installed_platbase}/include/python{py_version_short}{abiflags}",
            "scripts": "{base}/bin",
            "data": "{base}",
        },
        "posix_local": {
            "stdlib": "{installed_base}/{platlibdir}/python{py_version_short}",
            "platstdlib": "{platbase}/{platlibdir}/python{py_version_short}",
            "purelib": "{base}/local/lib/python{py_version_short}/dist-packages",
            "platlib": "{platbase}/local/lib/python{py_version_short}/dist-packages",
            "include": "{installed_base}/local/include/python{py_version_short}{abiflags}",
            "platinclude": "{installed_platbase}/local/include/python{py_version_short}{abiflags}",
            "scripts": "{base}/local/bin",
            "data": "{base}",
        },
    }
    # reset the default in case we're on a system which doesn't have this problem
    sysconfig_get_path = functools.partial(sysconfig.get_path, scheme="posix_local")

    # make it look like python3-distutils is not available
    mocker.patch.dict(sys.modules, {"distutils.command": None})
    mocker.patch("sysconfig._INSTALL_SCHEMES", sysconfig_install_schemes)
    mocker.patch("sysconfig.get_path", sysconfig_get_path)
    mocker.patch("sysconfig.get_default_scheme", return_value="posix_local")

    pyinfo = PythonInfo()
    pyver = f"{pyinfo.version_info.major}.{pyinfo.version_info.minor}"
    assert pyinfo.install_path("scripts") == "bin"
    assert pyinfo.install_path("purelib").replace(os.sep, "/") == f"lib/python{pyver}/site-packages"
