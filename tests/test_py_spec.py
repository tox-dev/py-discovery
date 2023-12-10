from __future__ import annotations

import sys
from copy import copy
from typing import TYPE_CHECKING, Tuple, cast

import pytest

from py_discovery import PythonSpec

if TYPE_CHECKING:
    from pathlib import Path


def test_bad_py_spec() -> None:
    text = "python2.3.4.5"
    spec = PythonSpec.from_string_spec(text)
    assert text in repr(spec)
    assert spec.str_spec == text
    assert spec.path == text
    content = vars(spec)
    del content["str_spec"]
    del content["path"]
    assert all(v is None for v in content.values())


def test_py_spec_first_digit_only_major() -> None:
    spec = PythonSpec.from_string_spec("278")
    assert spec.major == 2
    assert spec.minor == 78


def test_spec_satisfies_path_ok() -> None:
    spec = PythonSpec.from_string_spec(sys.executable)
    assert spec.satisfies(spec) is True


def test_spec_satisfies_path_nok(tmp_path: Path) -> None:
    spec = PythonSpec.from_string_spec(sys.executable)
    of = PythonSpec.from_string_spec(str(tmp_path))
    assert spec.satisfies(of) is False


def test_spec_satisfies_arch() -> None:
    spec_1 = PythonSpec.from_string_spec("python-32")
    spec_2 = PythonSpec.from_string_spec("python-64")

    assert spec_1.satisfies(spec_1) is True
    assert spec_2.satisfies(spec_1) is False


@pytest.mark.parametrize(
    ("req", "spec"),
    [("py", "python"), ("jython", "jython"), ("CPython", "cpython")],
)
def test_spec_satisfies_implementation_ok(req: str, spec: str) -> None:
    spec_1 = PythonSpec.from_string_spec(req)
    spec_2 = PythonSpec.from_string_spec(spec)
    assert spec_1.satisfies(spec_1) is True
    assert spec_2.satisfies(spec_1) is True


def test_spec_satisfies_implementation_nok() -> None:
    spec_1 = PythonSpec.from_string_spec("cpython")
    spec_2 = PythonSpec.from_string_spec("jython")
    assert spec_2.satisfies(spec_1) is False
    assert spec_1.satisfies(spec_2) is False


def _version_satisfies_pairs() -> list[tuple[str, str]]:
    target: set[tuple[str, str]] = set()
    version = tuple(str(i) for i in sys.version_info[0:3])
    for i in range(len(version) + 1):
        req = ".".join(version[0:i])
        for j in range(i + 1):
            sat = ".".join(version[0:j])
            # can be satisfied in both directions
            target.add((req, sat))
            target.add((sat, req))
    return sorted(target)


@pytest.mark.parametrize(("req", "spec"), _version_satisfies_pairs())
def test_version_satisfies_ok(req: str, spec: str) -> None:
    req_spec = PythonSpec.from_string_spec(f"python{req}")
    sat_spec = PythonSpec.from_string_spec(f"python{spec}")
    assert sat_spec.satisfies(req_spec) is True


def _version_not_satisfies_pairs() -> list[tuple[str, str]]:
    target: set[tuple[str, str]] = set()
    version = tuple(str(i) for i in cast(Tuple[int, ...], sys.version_info[0:3]))
    for major in range(len(version)):
        req = ".".join(version[0 : major + 1])
        for minor in range(major + 1):
            sat_ver = list(cast(Tuple[int, ...], sys.version_info[0 : minor + 1]))
            for patch in range(minor + 1):
                for o in [1, -1]:
                    temp = copy(sat_ver)
                    temp[patch] += o
                    if temp[patch] >= 0:
                        sat = ".".join(str(i) for i in temp)
                        target.add((req, sat))
    return sorted(target)


@pytest.mark.parametrize(("req", "spec"), _version_not_satisfies_pairs())
def test_version_satisfies_nok(req: str, spec: str) -> None:
    req_spec = PythonSpec.from_string_spec(f"python{req}")
    sat_spec = PythonSpec.from_string_spec(f"python{spec}")
    assert sat_spec.satisfies(req_spec) is False


def test_relative_spec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    a_relative_path = str((tmp_path / "a" / "b").relative_to(tmp_path))
    spec = PythonSpec.from_string_spec(a_relative_path)
    assert spec.path == a_relative_path
