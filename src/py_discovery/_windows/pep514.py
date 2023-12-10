"""Implement https://www.python.org/dev/peps/pep-0514/ to discover interpreters - Windows only."""

from __future__ import annotations

import os
import re
import sys
from logging import basicConfig, getLogger
from typing import TYPE_CHECKING, Any, Iterator, Union, cast

if TYPE_CHECKING:
    from types import TracebackType

if sys.platform == "win32":  # pragma: win32 cover
    from winreg import (
        HKEY_CURRENT_USER,
        HKEY_LOCAL_MACHINE,
        KEY_READ,
        KEY_WOW64_32KEY,
        KEY_WOW64_64KEY,
        EnumKey,
        HKEYType,
        OpenKeyEx,
        QueryValueEx,
    )


else:  # pragma: win32 no cover
    HKEY_CURRENT_USER = 0
    HKEY_LOCAL_MACHINE = 1
    KEY_READ = 131097
    KEY_WOW64_32KEY = 512
    KEY_WOW64_64KEY = 256

    class HKEYType:
        def __bool__(self) -> bool:
            return True

        def __int__(self) -> int:
            return 1

        def __enter__(self) -> HKEYType:  # noqa: PYI034
            return HKEYType()

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> bool | None:
            ...

    def EnumKey(__key: _KeyType, __index: int) -> str:  # noqa: N802
        return ""

    def OpenKeyEx(  # noqa: N802
        key: _KeyType,  # noqa: ARG001
        sub_key: str,  # noqa: ARG001
        reserved: int = 0,  # noqa: ARG001
        access: int = 131097,  # noqa: ARG001
    ) -> HKEYType:
        return HKEYType()

    def QueryValueEx(__key: HKEYType, __name: str) -> tuple[Any, int]:  # noqa: N802
        return "", 0


_KeyType = Union[HKEYType, int]
LOGGER = getLogger(__name__)


def enum_keys(key: _KeyType) -> Iterator[str]:
    at = 0
    while True:
        try:
            yield EnumKey(key, at)
        except OSError:
            break
        at += 1


def get_value(key: HKEYType, value_name: str) -> str | None:
    try:
        return cast(str, QueryValueEx(key, value_name)[0])
    except OSError:
        return None


def discover_pythons() -> Iterator[tuple[str, int, int | None, int, str, str | None]]:
    for hive, hive_name, key, flags, default_arch in [
        (HKEY_CURRENT_USER, "HKEY_CURRENT_USER", r"Software\Python", 0, 64),
        (HKEY_LOCAL_MACHINE, "HKEY_LOCAL_MACHINE", r"Software\Python", KEY_WOW64_64KEY, 64),
        (HKEY_LOCAL_MACHINE, "HKEY_LOCAL_MACHINE", r"Software\Python", KEY_WOW64_32KEY, 32),
    ]:
        yield from process_set(hive, hive_name, key, flags, default_arch)


def process_set(
    hive: int,
    hive_name: str,
    key: str,
    flags: int,
    default_arch: int,
) -> Iterator[tuple[str, int, int | None, int, str, str | None]]:
    try:
        with OpenKeyEx(hive, key, 0, KEY_READ | flags) as root_key:
            for company in enum_keys(root_key):
                if company == "PyLauncher":  # reserved
                    continue
                yield from process_company(hive_name, company, root_key, default_arch)
    except OSError:
        pass


def process_company(
    hive_name: str,
    company: str,
    root_key: _KeyType,
    default_arch: int,
) -> Iterator[tuple[str, int, int | None, int, str, str | None]]:
    with OpenKeyEx(root_key, company) as company_key:
        for tag in enum_keys(company_key):
            spec = process_tag(hive_name, company, company_key, tag, default_arch)
            if spec is not None:
                yield spec


def process_tag(
    hive_name: str,
    company: str,
    company_key: HKEYType,
    tag: str,
    default_arch: int,
) -> tuple[str, int, int | None, int, str, str | None] | None:
    with OpenKeyEx(company_key, tag) as tag_key:
        version = load_version_data(hive_name, company, tag, tag_key)
        if version is not None:  # if failed to get version bail
            major, minor, _ = version
            arch = load_arch_data(hive_name, company, tag, tag_key, default_arch)
            if arch is not None:
                exe_data = load_exe(hive_name, company, company_key, tag)
                if exe_data is not None:
                    exe, args = exe_data
                    return company, major, minor, arch, exe, args
                return None
            return None
        return None


def load_exe(hive_name: str, company: str, company_key: HKEYType, tag: str) -> tuple[str, str | None] | None:
    key_path = f"{hive_name}/{company}/{tag}"
    try:
        with OpenKeyEx(company_key, rf"{tag}\InstallPath") as ip_key, ip_key:
            exe = get_value(ip_key, "ExecutablePath")
            if exe is None:
                ip = get_value(ip_key, "")
                if ip is None:
                    msg(key_path, "no ExecutablePath or default for it")

                else:
                    ip = ip.rstrip("\\")
                    exe = f"{ip}\\python.exe"
            if exe is not None and os.path.exists(exe):  # noqa: PTH110
                args = get_value(ip_key, "ExecutableArguments")
                return exe, args
            msg(key_path, f"could not load exe with value {exe}")
    except OSError:
        msg(f"{key_path}/InstallPath", "missing")
    return None


def load_arch_data(hive_name: str, company: str, tag: str, tag_key: HKEYType, default_arch: int) -> int:
    arch_str = get_value(tag_key, "SysArchitecture")
    if arch_str is not None:
        key_path = f"{hive_name}/{company}/{tag}/SysArchitecture"
        try:
            return parse_arch(arch_str)
        except ValueError as sys_arch:
            msg(key_path, sys_arch)
    return default_arch


def parse_arch(arch_str: str) -> int:
    if isinstance(arch_str, str):
        match = re.match(r"^(\d+)bit$", arch_str)
        if match:
            return int(next(iter(match.groups())))
        error = f"invalid format {arch_str}"
    else:
        error = f"arch is not string: {arch_str!r}"
    raise ValueError(error)


def load_version_data(
    hive_name: str,
    company: str,
    tag: str,
    tag_key: HKEYType,
) -> tuple[int, int | None, int | None] | None:
    for candidate, key_path in [
        (get_value(tag_key, "SysVersion"), f"{hive_name}/{company}/{tag}/SysVersion"),
        (tag, f"{hive_name}/{company}/{tag}"),
    ]:
        if candidate is not None:
            try:
                return parse_version(candidate)
            except ValueError as sys_version:
                msg(key_path, sys_version)
    return None


def parse_version(version_str: str) -> tuple[int, int | None, int | None]:
    if isinstance(version_str, str):
        match = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?$", version_str)
        if match:
            return tuple(int(i) if i is not None else None for i in match.groups())  # type: ignore[return-value]
        error = f"invalid format {version_str}"
    else:
        error = f"version is not string: {version_str!r}"
    raise ValueError(error)


def msg(path: str, what: str | ValueError) -> None:
    LOGGER.warning("PEP-514 violation in Windows Registry at %s error: %s", path, what)


def _run() -> None:
    basicConfig()
    interpreters = [repr(spec) for spec in discover_pythons()]
    print("\n".join(sorted(interpreters)))  # noqa: T201


__all__ = [
    "HKEY_CURRENT_USER",
    "HKEY_LOCAL_MACHINE",
    "KEY_READ",
    "KEY_WOW64_32KEY",
    "KEY_WOW64_64KEY",
    "discover_pythons",
]

if __name__ == "__main__":
    _run()
