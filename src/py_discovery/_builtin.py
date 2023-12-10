from __future__ import annotations

import logging
import os
import sys
from typing import TYPE_CHECKING, Iterator, Mapping, MutableMapping

from ._discover import Discover
from ._info import PythonInfo
from ._spec import PythonSpec

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace


class Builtin(Discover):
    def __init__(self, options: Namespace) -> None:
        super().__init__(options)
        self.python_spec = options.python if options.python else [sys.executable]
        self.try_first_with = options.try_first_with

    @classmethod
    def add_parser_arguments(cls, parser: ArgumentParser) -> None:
        parser.add_argument(
            "-p",
            "--python",
            dest="python",
            metavar="py",
            type=str,
            action="append",
            default=[],
            help="interpreter based on what to create environment (path/identifier) "
            "- by default use the interpreter where the tool is installed - first found wins",
        )
        parser.add_argument(
            "--try-first-with",
            dest="try_first_with",
            metavar="py_exe",
            type=str,
            action="append",
            default=[],
            help="try first these interpreters before starting the discovery",
        )

    def run(self) -> PythonInfo | None:
        for python_spec in self.python_spec:
            result = get_interpreter(python_spec, self.try_first_with, self._env)
            if result is not None:
                return result
        return None

    def __repr__(self) -> str:
        spec = self.python_spec[0] if len(self.python_spec) == 1 else self.python_spec
        return f"{self.__class__.__name__} discover of python_spec={spec!r}"


def get_interpreter(
    key: str,
    try_first_with: list[str],
    env: MutableMapping[str, str] | None = None,
) -> PythonInfo | None:
    spec = PythonSpec.from_string_spec(key)
    logging.info("find interpreter for spec %r", spec)
    proposed_paths = set()
    env = os.environ if env is None else env
    for interpreter, impl_must_match in propose_interpreters(spec, try_first_with, env):
        if interpreter is None:
            continue
        lookup_key = interpreter.system_executable, impl_must_match
        if lookup_key in proposed_paths:
            continue
        logging.info("proposed %s", interpreter)
        if interpreter.satisfies(spec, impl_must_match):
            logging.debug("accepted %s", interpreter)
            return interpreter
        proposed_paths.add(lookup_key)
    return None


def propose_interpreters(  # noqa: C901, PLR0912
    spec: PythonSpec,
    try_first_with: list[str],
    env: MutableMapping[str, str] | None = None,
) -> Iterator[tuple[PythonInfo | None, bool]]:
    # 0. tries with first
    env = os.environ if env is None else env
    for py_exe in try_first_with:
        path = os.path.abspath(py_exe)  # noqa: PTH100
        try:
            os.lstat(path)  # Windows Store Python does not work with os.path.exists, but does for os.lstat
        except OSError:
            pass
        else:
            yield PythonInfo.from_exe(os.path.abspath(path), env=env), True  # noqa: PTH100

    # 1. if it's a path and exists
    if spec.path is not None:
        try:
            os.lstat(spec.path)  # Windows Store Python does not work with os.path.exists, but does for os.lstat
        except OSError:
            if spec.is_abs:
                raise
        else:
            yield PythonInfo.from_exe(os.path.abspath(spec.path), env=env), True  # noqa: PTH100
        if spec.is_abs:
            return
    else:
        # 2. otherwise tries with the current
        yield PythonInfo.current_system(), True

        # 3. otherwise fallbacks to platform default logic
        if sys.platform == "win32":
            from ._windows import propose_interpreters

            for interpreter in propose_interpreters(spec, env):
                yield interpreter, True
    # finally, find on the path, the path order matters (as the candidates are less easy to control by end user)
    paths = get_paths(env)
    tested_exes = set()
    for pos, path in enumerate(paths):
        path_str = str(path)
        logging.debug(LazyPathDump(pos, path_str, env))
        for candidate, match in possible_specs(spec):
            found = check_path(candidate, path_str)
            if found is not None:
                exe = os.path.abspath(found)  # noqa: PTH100
                if exe not in tested_exes:
                    tested_exes.add(exe)
                    interpreter = PathPythonInfo.from_exe(exe, raise_on_error=False, env=env)
                    if interpreter is not None:
                        yield interpreter, match


def get_paths(env: Mapping[str, str]) -> list[str]:
    path = env.get("PATH", None)
    if path is None:
        try:
            path = os.confstr("CS_PATH")
        except (AttributeError, ValueError):
            path = os.defpath
    return [] if not path else [p for p in path.split(os.pathsep) if os.path.exists(p)]  # noqa: PTH110


class LazyPathDump:
    def __init__(self, pos: int, path: str, env: Mapping[str, str]) -> None:
        self.pos = pos
        self.path = path
        self.env = env

    def __repr__(self) -> str:
        content = f"discover PATH[{self.pos}]={self.path}"
        if self.env.get("_VIRTUALENV_DEBUG"):  # this is the over the board debug
            content += " with =>"
            for file_name in os.listdir(self.path):
                try:
                    file_path = os.path.join(self.path, file_name)  # noqa: PTH118
                    if os.path.isdir(file_path) or not os.access(file_path, os.X_OK):  # noqa: PTH112
                        continue
                except OSError:
                    pass
                content += " "
                content += file_name
        return content


def check_path(candidate: str, path: str) -> str | None:
    _, ext = os.path.splitext(candidate)  # noqa: PTH122
    if sys.platform == "win32" and ext != ".exe":
        candidate = f"{candidate}.exe"
    if os.path.isfile(candidate):  # noqa: PTH113
        return candidate
    candidate = os.path.join(path, candidate)  # noqa: PTH118
    if os.path.isfile(candidate):  # noqa: PTH113
        return candidate
    return None


def possible_specs(spec: PythonSpec) -> Iterator[tuple[str, bool]]:
    # 4. then maybe it's something exact on PATH - if it was a direct lookup implementation no longer counts
    if spec.str_spec is not None:
        yield spec.str_spec, False
    # 5. or from the spec we can deduce a name on path that matches
    yield from spec.generate_names()


class PathPythonInfo(PythonInfo):
    """python info from a path."""


__all__ = [
    "get_interpreter",
    "Builtin",
    "PathPythonInfo",
]
