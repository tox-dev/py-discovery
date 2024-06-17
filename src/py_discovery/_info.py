"""
The PythonInfo contains information about a concrete instance of a Python interpreter.

Note: this file is also used to query target interpreters, so can only use standard library methods

"""

from __future__ import annotations

import copy
import json
import logging
import os
import platform
import re
import sys
import sysconfig
import warnings
from collections import OrderedDict, namedtuple
from pathlib import Path
from random import choice
from shlex import quote
from string import ascii_lowercase, ascii_uppercase, digits
from subprocess import PIPE, Popen  # noqa: S404
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any, Iterator, Mapping, MutableMapping

if TYPE_CHECKING:
    from py_discovery import PythonSpec

_FS_CASE_SENSITIVE = None


def fs_is_case_sensitive() -> bool:
    global _FS_CASE_SENSITIVE  # noqa: PLW0603

    if _FS_CASE_SENSITIVE is None:
        with NamedTemporaryFile(prefix="TmP") as tmp_file:
            _FS_CASE_SENSITIVE = not os.path.exists(tmp_file.name.lower())  # noqa: PTH110
            logging.debug("filesystem is %scase-sensitive", "" if _FS_CASE_SENSITIVE else "not ")
    return _FS_CASE_SENSITIVE


VersionInfo = namedtuple("VersionInfo", ["major", "minor", "micro", "releaselevel", "serial"])  # noqa: PYI024


def _get_path_extensions() -> list[str]:
    return list(OrderedDict.fromkeys(["", *os.environ.get("PATHEXT", "").lower().split(os.pathsep)]))


EXTENSIONS = _get_path_extensions()
_CONF_VAR_RE = re.compile(r"\{\w+\}")


class PythonInfo:
    """Contains information for a Python interpreter."""

    def __init__(self) -> None:
        def abs_path(v: str | None) -> str | None:
            # unroll relative elements from path (e.g. ..)
            return None if v is None else os.path.abspath(v)  # noqa: PTH100

        # qualifies the python
        self.platform = sys.platform
        self.implementation = platform.python_implementation()
        self.pypy_version_info = (
            tuple(sys.pypy_version_info)  # type: ignore[attr-defined]
            if self.implementation == "PyPy"
            else None
        )

        # this is a tuple in earlier, struct later, unify to our own named tuple
        self.version_info = VersionInfo(*sys.version_info)
        self.architecture = 64 if sys.maxsize > 2**32 else 32

        # Used to determine some file names - see `CPython3Windows.python_zip()`.
        self.version_nodot = sysconfig.get_config_var("py_version_nodot")

        self.version = sys.version
        self.os = os.name

        # information about the prefix - determines python home
        self.prefix = abs_path(getattr(sys, "prefix", None))  # prefix we think
        self.base_prefix = abs_path(getattr(sys, "base_prefix", None))  # venv
        self.real_prefix = abs_path(getattr(sys, "real_prefix", None))  # old virtualenv

        # information about the exec prefix - dynamic stdlib modules
        self.base_exec_prefix = abs_path(getattr(sys, "base_exec_prefix", None))
        self.exec_prefix = abs_path(getattr(sys, "exec_prefix", None))

        self.executable = abs_path(sys.executable)  # the executable we were invoked via
        self.original_executable = abs_path(self.executable)  # the executable as known by the interpreter
        self.system_executable = self._fast_get_system_executable()  # the executable we are based of (if available)

        try:
            __import__("venv")
            has = True
        except ImportError:
            has = False
        self.has_venv = has
        self.path = sys.path
        self.file_system_encoding = sys.getfilesystemencoding()
        self.stdout_encoding = getattr(sys.stdout, "encoding", None)

        scheme_names = sysconfig.get_scheme_names()

        if "venv" in scheme_names:
            self.sysconfig_scheme = "venv"
            self.sysconfig_paths = {
                i: sysconfig.get_path(i, expand=False, scheme=self.sysconfig_scheme) for i in sysconfig.get_path_names()
            }
            # we cannot use distutils at all if "venv" exists, distutils don't know it
            self.distutils_install = {}
        # debian / ubuntu python 3.10 without `python3-distutils` will report
        # mangled `local/bin` / etc. names for the default prefix
        # intentionally select `posix_prefix` which is the unaltered posix-like paths
        elif sys.version_info[:2] == (3, 10) and "deb_system" in scheme_names:
            self.sysconfig_scheme: str | None = "posix_prefix"
            self.sysconfig_paths = {
                i: sysconfig.get_path(i, expand=False, scheme=self.sysconfig_scheme) for i in sysconfig.get_path_names()
            }
            # we cannot use distutils at all if "venv" exists, distutils don't know it
            self.distutils_install = {}
        else:
            self.sysconfig_scheme = None  # type: ignore[assignment]
            self.sysconfig_paths = {i: sysconfig.get_path(i, expand=False) for i in sysconfig.get_path_names()}
            self.distutils_install = self._distutils_install().copy()

        # https://bugs.python.org/issue22199
        makefile = getattr(sysconfig, "get_makefile_filename", getattr(sysconfig, "_get_makefile_filename", None))
        # a list of content to store from sysconfig
        self.sysconfig = {
            k: v for k, v in ([("makefile_filename", makefile())] if makefile is not None else []) if k is not None
        }

        config_var_keys: set[str] = set()
        for element in self.sysconfig_paths.values():
            config_var_keys.update(k[1:-1] for k in _CONF_VAR_RE.findall(element))
        config_var_keys.add("PYTHONFRAMEWORK")

        self.sysconfig_vars = {i: sysconfig.get_config_var(i or "") for i in config_var_keys}

        confs = {
            k: (self.system_prefix if v is not None and v.startswith(self.prefix) else v)
            for k, v in self.sysconfig_vars.items()
        }
        self.system_stdlib = self.sysconfig_path("stdlib", confs)
        self.system_stdlib_platform = self.sysconfig_path("platstdlib", confs)
        self.max_size = getattr(sys, "maxsize", getattr(sys, "maxint", None))
        self._creators = None

    def _fast_get_system_executable(self) -> str | None:
        """Try to get the system executable by just looking at properties."""
        # if this is a virtual environment
        if self.real_prefix or (self.base_prefix is not None and self.base_prefix != self.prefix):  # noqa: PLR1702
            if self.real_prefix is None:
                # some platforms may set this to help us
                base_executable: str | None = getattr(sys, "_base_executable", None)
                if base_executable is not None:  # noqa: SIM102 # use the saved system executable if present
                    if sys.executable != base_executable:  # we know we're in a virtual environment, cannot be us
                        if os.path.exists(base_executable):  # noqa: PTH110
                            return base_executable
                        # Python may return "python" because it was invoked from the POSIX virtual environment; but some
                        # installs/distributions do not provide a version-less python binary in the system install
                        # location (see PEP 394) so try to fall back to a versioned binary.
                        #
                        # Gate this to Python 3.11 as `sys._base_executable` path resolution is now relative to
                        # the home key from `pyvenv.cfg`, which often points to the system installs location.
                        major, minor = self.version_info.major, self.version_info.minor
                        if self.os == "posix" and (major, minor) >= (3, 11):
                            # search relative to the directory of sys._base_executable
                            base_dir = os.path.dirname(base_executable)  # noqa: PTH120
                            versions = (f"python{major}", f"python{major}.{minor}")
                            for base_executable in [os.path.join(base_dir, exe) for exe in versions]:  # noqa: PTH118
                                if os.path.exists(base_executable):  # noqa: PTH110
                                    return base_executable
            return None  # in this case, we just can't tell easily without poking around FS and calling them, bail
        # if we're not in a virtual environment, this is already a system python, so return the original executable
        # note we must choose the original and not the pure executable as shim scripts might throw us off
        return self.original_executable

    def install_path(self, key: str) -> str:
        result = self.distutils_install.get(key)
        if result is None:  # use sysconfig if sysconfig_scheme is set or distutils is unavailable
            # set prefixes to empty => result is relative from cwd
            prefixes = self.prefix, self.exec_prefix, self.base_prefix, self.base_exec_prefix
            config_var = {k: "" if v in prefixes else v for k, v in self.sysconfig_vars.items()}
            result = self.sysconfig_path(key, config_var=config_var).lstrip(os.sep)
        return result

    @staticmethod
    def _distutils_install() -> dict[str, str]:
        # use distutils primarily because that's what pip does
        # https://github.com/pypa/pip/blob/main/src/pip/_internal/locations.py#L95
        # note here we don't import Distribution directly to allow setuptools to patch it
        with warnings.catch_warnings():  # disable warning for PEP-632
            warnings.simplefilter("ignore")
            try:
                from distutils import dist  # noqa: PLC0415
                from distutils.command.install import SCHEME_KEYS  # noqa: PLC0415
            except ImportError:  # if removed or not installed ignore
                return {}

        d = dist.Distribution({"script_args": "--no-user-cfg"})  # conf files not parsed so they do not hijack paths
        if hasattr(sys, "_framework"):
            sys._framework = None  # disable macOS static paths for framework  # noqa: SLF001

        with warnings.catch_warnings():  # disable warning for PEP-632
            warnings.simplefilter("ignore")
            i = d.get_command_obj("install", create=True)
            assert i is not None  # noqa: S101

        # paths generated are relative to prefix that contains the path sep, this makes it relative
        i.prefix = os.sep  # type: ignore[attr-defined]
        i.finalize_options()
        return {key: (getattr(i, f"install_{key}")[1:]).lstrip(os.sep) for key in SCHEME_KEYS}

    @property
    def version_str(self) -> str:
        return ".".join(str(i) for i in self.version_info[0:3])

    @property
    def version_release_str(self) -> str:
        return ".".join(str(i) for i in self.version_info[0:2])

    @property
    def python_name(self) -> str:
        version_info = self.version_info
        return f"python{version_info.major}.{version_info.minor}"

    @property
    def is_old_virtualenv(self) -> bool:
        return self.real_prefix is not None

    @property
    def is_venv(self) -> bool:
        return self.base_prefix is not None

    def sysconfig_path(self, key: str, config_var: dict[str, str] | None = None, sep: str = os.sep) -> str:
        pattern = self.sysconfig_paths[key]
        if config_var is None:
            config_var = self.sysconfig_vars
        else:
            base = self.sysconfig_vars.copy()
            base.update(config_var)
            config_var = base
        return pattern.format(**config_var).replace("/", sep)

    @property
    def system_include(self) -> str:
        path = self.sysconfig_path(
            "include",
            {
                k: (self.system_prefix if v is not None and v.startswith(self.prefix) else v)
                for k, v in self.sysconfig_vars.items()
            },
        )
        if not os.path.exists(path) and self.prefix is not None:  # noqa: PTH110
            # some broken packaging doesn't respect the sysconfig, fallback to a distutils path
            # the pattern includes the distribution name too at the end, remove that via the parent call
            fallback = os.path.join(self.prefix, os.path.dirname(self.install_path("headers")))  # noqa: PTH118, PTH120
            if os.path.exists(fallback):  # noqa: PTH110
                path = fallback
        return path

    @property
    def system_prefix(self) -> str:
        res = self.real_prefix or self.base_prefix or self.prefix
        assert res is not None  # noqa: S101
        return res

    @property
    def system_exec_prefix(self) -> str:
        res = self.real_prefix or self.base_exec_prefix or self.exec_prefix
        assert res is not None  # noqa: S101
        return res

    def __repr__(self) -> str:
        return "{}({!r})".format(
            self.__class__.__name__,
            {k: v for k, v in self.__dict__.items() if not k.startswith("_")},
        )

    def __str__(self) -> str:
        return "{}({})".format(
            self.__class__.__name__,
            ", ".join(
                f"{k}={v}"
                for k, v in (
                    ("spec", self.spec),
                    (
                        "system"
                        if self.system_executable is not None and self.system_executable != self.executable
                        else None,
                        self.system_executable,
                    ),
                    (
                        "original"
                        if self.original_executable not in {self.system_executable, self.executable}
                        else None,
                        self.original_executable,
                    ),
                    ("exe", self.executable),
                    ("platform", self.platform),
                    ("version", repr(self.version)),
                    ("encoding_fs_io", f"{self.file_system_encoding}-{self.stdout_encoding}"),
                )
                if k is not None
            ),
        )

    @property
    def spec(self) -> str:
        return "{}{}-{}".format(self.implementation, ".".join(str(i) for i in self.version_info), self.architecture)

    def satisfies(self, spec: PythonSpec, impl_must_match: bool) -> bool:  # noqa: C901, FBT001
        """Check if a given specification can be satisfied by the python interpreter instance."""
        if spec.path:
            if self.executable == os.path.abspath(spec.path):  # noqa: PTH100
                return True  # if the path is a our own executable path we're done
            if not spec.is_abs:
                # if path set, and is not our original executable name, this does not match
                assert self.original_executable is not None  # noqa: S101
                basename = os.path.basename(self.original_executable)  # noqa: PTH119
                spec_path = spec.path
                if sys.platform == "win32":
                    basename, suffix = os.path.splitext(basename)  # noqa: PTH122
                    if spec_path.endswith(suffix):
                        spec_path = spec_path[: -len(suffix)]
                if basename != spec_path:
                    return False

        if (
            impl_must_match
            and spec.implementation is not None
            and spec.implementation.lower() != self.implementation.lower()
        ):
            return False

        if spec.architecture is not None and spec.architecture != self.architecture:
            return False

        for our, req in zip(self.version_info[0:3], (spec.major, spec.minor, spec.micro)):
            if req is not None and our is not None and our != req:
                return False
        return True

    _current_system = None
    _current = None

    @classmethod
    def current(cls) -> PythonInfo:
        """
        Locate the current host interpreter information.

        This might be different than what we run into in case the host python has been upgraded from underneath us.

        """
        if cls._current is None:
            cls._current = cls.from_exe(sys.executable, raise_on_error=True, resolve_to_host=False)
            assert cls._current is not None  # noqa: S101
        return cls._current

    @classmethod
    def current_system(cls) -> PythonInfo:
        """
        Locate the current host interpreter information.

        This might be different than what we run into in case the host python has been upgraded from underneath us.

        """
        if cls._current_system is None:
            cls._current_system = cls.from_exe(sys.executable, raise_on_error=True, resolve_to_host=True)
            assert cls._current_system is not None  # noqa: S101
        return cls._current_system

    def _to_json(self) -> str:
        # don't save calculated paths, as these are non-primitive types
        return json.dumps(self._to_dict(), indent=2)

    def _to_dict(self) -> dict[str, Any]:
        data = {var: (getattr(self, var) if var != "_creators" else None) for var in vars(self)}

        data["version_info"] = data["version_info"]._asdict()  # namedtuple to dictionary
        return data

    @classmethod
    def from_exe(
        cls,
        exe: str,
        *,
        raise_on_error: bool = True,
        resolve_to_host: bool = True,
        env: MutableMapping[str, str] | None = None,
    ) -> PythonInfo | None:
        """Given a path to an executable, get the python information."""
        # this method is not used by itself, so here and called functions can import stuff locally

        env = os.environ if env is None else env
        proposed = cls._from_exe(exe, env=env, raise_on_error=raise_on_error)

        if isinstance(proposed, PythonInfo) and resolve_to_host:
            try:
                proposed = proposed._resolve_to_system(proposed)  # noqa: SLF001
            except Exception as exception:
                if raise_on_error:
                    raise
                logging.info("ignore %s due cannot resolve system due to %r", proposed.original_executable, exception)
                proposed = None
        return proposed

    @classmethod
    def _from_exe(
        cls,
        exe: str,
        env: MutableMapping[str, str] | None = None,
        raise_on_error: bool = True,  # noqa: FBT001, FBT002
    ) -> PythonInfo | None:
        env = os.environ if env is None else env
        outcome = _run_subprocess(cls, exe, env)
        if isinstance(outcome, Exception):
            if raise_on_error:
                raise outcome
            logging.info("%s", outcome)
            return None
        outcome.executable = exe
        return outcome

    @classmethod
    def _from_json(cls, payload: str) -> PythonInfo:
        # the dictionary unroll here is to protect against pypy bug of interpreter crashing
        raw = json.loads(payload)
        return cls._from_dict(raw.copy())

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> PythonInfo:
        data["version_info"] = VersionInfo(**data["version_info"])  # restore this to a named tuple structure
        result = cls()
        result.__dict__ = data.copy()
        return result

    @classmethod
    def _resolve_to_system(cls, target: PythonInfo) -> PythonInfo:
        start_executable = target.executable
        prefixes: OrderedDict[str, PythonInfo] = OrderedDict()
        while target.system_executable is None:
            prefix = target.real_prefix or target.base_prefix or target.prefix
            assert prefix is not None  # noqa: S101
            if prefix in prefixes:
                if len(prefixes) == 1:
                    # if we're linking back to ourselves, accept ourselves with a WARNING
                    logging.info("%r links back to itself via prefixes", target)
                    target.system_executable = target.executable
                    break
                for at, (p, t) in enumerate(prefixes.items(), start=1):
                    logging.error("%d: prefix=%s, info=%r", at, p, t)
                logging.error("%d: prefix=%s, info=%r", len(prefixes) + 1, prefix, target)
                msg = "prefixes are causing a circle {}".format("|".join(prefixes.keys()))
                raise RuntimeError(msg)
            prefixes[prefix] = target
            target = target.discover_exe(prefix=prefix, exact=False)
        if target.executable != target.system_executable and target.system_executable is not None:
            outcome = cls.from_exe(target.system_executable)
            if outcome is None:
                msg = "failed to resolve to system executable"
                raise RuntimeError(msg)
            target = outcome
        target.executable = start_executable
        return target

    _cache_exe_discovery: dict[tuple[str, bool], PythonInfo] = {}  # noqa: RUF012

    def discover_exe(self, prefix: str, exact: bool = True, env: MutableMapping[str, str] | None = None) -> PythonInfo:  # noqa: FBT001, FBT002
        key = prefix, exact
        if key in self._cache_exe_discovery and prefix:
            logging.debug("discover exe from cache %s - exact %s: %r", prefix, exact, self._cache_exe_discovery[key])
            return self._cache_exe_discovery[key]
        logging.debug("discover exe for %s in %s", self, prefix)
        # we don't know explicitly here, do some guess work - our executable name should tell
        possible_names = self._find_possible_exe_names()
        possible_folders = self._find_possible_folders(prefix)
        discovered: list[PythonInfo] = []
        not_none_env = os.environ if env is None else env
        for folder in possible_folders:
            for name in possible_names:
                info = self._check_exe(folder, name, exact, discovered, not_none_env)
                if info is not None:
                    self._cache_exe_discovery[key] = info
                    return info
        if exact is False and discovered:
            info = self._select_most_likely(discovered, self)
            folders = os.pathsep.join(possible_folders)
            self._cache_exe_discovery[key] = info
            logging.debug("no exact match found, chosen most similar of %s within base folders %s", info, folders)
            return info
        msg = "failed to detect {} in {}".format("|".join(possible_names), os.pathsep.join(possible_folders))
        raise RuntimeError(msg)

    def _check_exe(  # noqa: PLR0913
        self,
        folder: str,
        name: str,
        exact: bool,  # noqa: FBT001
        discovered: list[PythonInfo],
        env: MutableMapping[str, str],
    ) -> PythonInfo | None:
        exe_path = os.path.join(folder, name)  # noqa: PTH118
        if not os.path.exists(exe_path):  # noqa: PTH110
            return None
        info = self.from_exe(exe_path, resolve_to_host=False, raise_on_error=False, env=env)
        if info is None:  # ignore if for some reason we can't query
            return None
        for item in ["implementation", "architecture", "version_info"]:
            found = getattr(info, item)
            searched = getattr(self, item)
            if found != searched:
                if item == "version_info":
                    found, searched = ".".join(str(i) for i in found), ".".join(str(i) for i in searched)
                executable = info.executable
                logging.debug("refused interpreter %s because %s differs %s != %s", executable, item, found, searched)
                if exact is False:
                    discovered.append(info)
                break
        else:
            return info
        return None

    @staticmethod
    def _select_most_likely(discovered: list[PythonInfo], target: PythonInfo) -> PythonInfo:
        # no exact match found, start relaxing our requirements then to facilitate system package upgrades that
        # could cause this (when using copy strategy of the host python)
        def sort_by(info: PythonInfo) -> int:
            # we need to set up some priority of traits, this is as follows:
            # implementation, major, minor, micro, architecture, tag, serial
            matches = [
                info.implementation == target.implementation,
                info.version_info.major == target.version_info.major,
                info.version_info.minor == target.version_info.minor,
                info.architecture == target.architecture,
                info.version_info.micro == target.version_info.micro,
                info.version_info.releaselevel == target.version_info.releaselevel,
                info.version_info.serial == target.version_info.serial,
            ]
            return sum((1 << pos if match else 0) for pos, match in enumerate(reversed(matches)))

        sorted_discovered = sorted(discovered, key=sort_by, reverse=True)  # sort by priority in decreasing order
        return sorted_discovered[0]

    def _find_possible_folders(self, inside_folder: str) -> list[str]:
        candidate_folder: OrderedDict[str, None] = OrderedDict()
        executables: OrderedDict[str, None] = OrderedDict()
        assert self.executable is not None  # noqa: S101
        executables[os.path.realpath(self.executable)] = None
        executables[self.executable] = None
        assert self.original_executable is not None  # noqa: S101
        executables[os.path.realpath(self.original_executable)] = None
        executables[self.original_executable] = None
        for exe in executables:
            base = os.path.dirname(exe)  # noqa: PTH120
            # following path pattern of the current
            assert self.prefix is not None  # noqa: S101
            if base.startswith(self.prefix):
                relative = base[len(self.prefix) :]
                candidate_folder[f"{inside_folder}{relative}"] = None

        # or at root level
        candidate_folder[inside_folder] = None
        return [i for i in candidate_folder if os.path.exists(i)]  # noqa: PTH110

    def _find_possible_exe_names(self) -> list[str]:
        name_candidate: OrderedDict[str, None] = OrderedDict()
        for name in self._possible_base():
            for at in (3, 2, 1, 0):
                version = ".".join(str(i) for i in self.version_info[:at])
                for arch in [f"-{self.architecture}", ""]:
                    for ext in EXTENSIONS:
                        candidate = f"{name}{version}{arch}{ext}"
                        name_candidate[candidate] = None
        return list(name_candidate.keys())

    def _possible_base(self) -> Iterator[str]:
        possible_base: OrderedDict[str, None] = OrderedDict()
        assert self.executable is not None  # noqa: S101
        basename = os.path.splitext(os.path.basename(self.executable))[0].rstrip(digits)  # noqa: PTH119, PTH122
        possible_base[basename] = None
        possible_base[self.implementation] = None
        # python is always the final option as in practice is used by multiple implementation as exe name
        if "python" in possible_base:
            del possible_base["python"]
        possible_base["python"] = None
        for base in possible_base:
            lower = base.lower()
            yield lower

            if fs_is_case_sensitive():
                if base != lower:
                    yield base
                upper = base.upper()
                if upper != base:
                    yield upper


_COOKIE_LENGTH: int = 32


def _gen_cookie() -> str:
    return "".join(choice(f"{ascii_lowercase}{ascii_uppercase}{digits}") for _ in range(_COOKIE_LENGTH))  # noqa: S311


def _run_subprocess(  # noqa: PLR0914
    cls: type[PythonInfo], exe: str, env: MutableMapping[str, str]
) -> PythonInfo | RuntimeError:
    py_info_script = Path(os.path.abspath(__file__)).parent / "_info.py"  # noqa: PTH100
    # Cookies allow splitting the serialized stdout output generated by the script collecting the info from the output
    # generated by something else.
    # The right way to deal with it is to create an anonymous pipe and pass its descriptor to the child and output to
    # it.
    # However, AFAIK all of them are either not cross-platform or too big to implement and are not in the stdlib; so the
    # easiest and the shortest way I could mind is just using the cookies.
    # We generate pseudorandom cookies because it is easy to implement and avoids breakage from outputting modules
    # source code, i.e., by debug output libraries.
    # We reverse the cookies to avoid breakages resulting from variable values appearing in debug output.

    start_cookie = _gen_cookie()
    end_cookie = _gen_cookie()
    cmd = [exe, str(py_info_script), start_cookie, end_cookie]
    # prevent sys.prefix from leaking into the child process - see https://bugs.python.org/issue22490
    env = copy.copy(env)
    env.pop("__PYVENV_LAUNCHER__", None)
    logging.debug("get interpreter info via cmd: %s", LogCmd(cmd))
    try:
        process = Popen(
            cmd,  # noqa: S603
            universal_newlines=True,
            stdin=PIPE,
            stderr=PIPE,
            stdout=PIPE,
            env=env,
            encoding="utf-8",
        )
        out, err = process.communicate()
        code = process.returncode
    except OSError as os_error:
        out, err, code = "", os_error.strerror, os_error.errno
    if code == 0:
        out_starts = out.find(start_cookie[::-1])

        if out_starts > -1:
            pre_cookie = out[:out_starts]

            if pre_cookie:
                sys.stdout.write(pre_cookie)

            out = out[out_starts + _COOKIE_LENGTH :]

        out_ends = out.find(end_cookie[::-1])

        if out_ends > -1:
            post_cookie = out[out_ends + _COOKIE_LENGTH :]

            if post_cookie:
                sys.stdout.write(post_cookie)

            out = out[:out_ends]

        result = cls._from_json(out)
        result.executable = exe  # keep the original executable as this may contain initialization code
        return result

    err_str = f" err: {err!r}" if err else ""
    out_str = f" out: {out!r}" if out else ""
    msg = f"{exe} with code {code}{out_str}{err_str}"
    return RuntimeError(f"failed to query {msg}")


class LogCmd:
    def __init__(self, cmd: list[str], env: Mapping[str, str] | None = None) -> None:
        self.cmd = cmd
        self.env = env

    def __repr__(self) -> str:
        cmd_repr = " ".join(quote(str(c)) for c in self.cmd)
        if self.env is not None:
            cmd_repr = f"{cmd_repr} env of {self.env!r}"
        return cmd_repr


__all__ = [
    "EXTENSIONS",
    "PythonInfo",
    "VersionInfo",
    "fs_is_case_sensitive",
]


def _run() -> None:
    """Dump a JSON representation of the current python."""
    argv = sys.argv[1:]
    if len(argv) >= 1:
        start_cookie = argv[0]
        argv = argv[1:]
    else:
        start_cookie = ""
    if len(argv) >= 1:
        end_cookie = argv[0]
        argv = argv[1:]
    else:
        end_cookie = ""
    sys.argv = sys.argv[:1] + argv
    info = PythonInfo()._to_json()  # noqa: SLF001
    sys.stdout.write("".join((start_cookie[::-1], info, end_cookie[::-1])))


if __name__ == "__main__":
    _run()
