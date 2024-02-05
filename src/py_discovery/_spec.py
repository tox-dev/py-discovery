"""A Python specification is an abstract requirement definition of an interpreter."""

from __future__ import annotations

import os
import re
from collections import OrderedDict
from typing import Iterator, Tuple, cast

from py_discovery._info import fs_is_case_sensitive

PATTERN = re.compile(r"^(?P<impl>[a-zA-Z]+)?(?P<version>[0-9.]+)?(?:-(?P<arch>32|64))?$")


class PythonSpec:
    """Contains specification about a Python Interpreter."""

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        str_spec: str | None,
        implementation: str | None,
        major: int | None,
        minor: int | None,
        micro: int | None,
        architecture: int | None,
        path: str | None,
    ) -> None:
        self.str_spec = str_spec
        self.implementation = implementation
        self.major = major
        self.minor = minor
        self.micro = micro
        self.architecture = architecture
        self.path = path

    @classmethod
    def from_string_spec(cls, string_spec: str) -> PythonSpec:  # noqa: C901, PLR0912
        impl, major, minor, micro, arch, path = None, None, None, None, None, None
        if os.path.isabs(string_spec):  # noqa: PTH117, PLR1702
            path = string_spec
        else:
            ok = False
            match = re.match(PATTERN, string_spec)
            if match:

                def _int_or_none(val: str | None) -> int | None:
                    return None if val is None else int(val)

                try:
                    groups = match.groupdict()
                    version = groups["version"]
                    if version is not None:
                        versions = tuple(int(i) for i in version.split(".") if i)
                        if len(versions) > 3:  # noqa: PLR2004
                            raise ValueError  # noqa: TRY301
                        if len(versions) == 3:  # noqa: PLR2004
                            major, minor, micro = versions
                        elif len(versions) == 2:  # noqa: PLR2004
                            major, minor = versions
                        elif len(versions) == 1:
                            version_data = versions[0]
                            major = int(str(version_data)[0])  # first digit major
                            if version_data > 9:  # noqa: PLR2004
                                minor = int(str(version_data)[1:])
                    ok = True
                except ValueError:
                    pass
                else:
                    impl = groups["impl"]
                    if impl in {"py", "python"}:
                        impl = None
                    arch = _int_or_none(groups["arch"])

            if not ok:
                path = string_spec

        return cls(string_spec, impl, major, minor, micro, arch, path)

    def generate_names(self) -> Iterator[tuple[str, bool]]:
        impls = OrderedDict()
        if self.implementation:
            # first, consider implementation as it is
            impls[self.implementation] = False
            if fs_is_case_sensitive():
                # for case-sensitive file systems, consider lower and upper case versions too
                # trivia: MacBooks and all pre-2018 Windows-es were case-insensitive by default
                impls[self.implementation.lower()] = False
                impls[self.implementation.upper()] = False
        impls["python"] = True  # finally, consider python as alias; implementation must match now
        version = self.major, self.minor, self.micro
        try:
            not_none_version: tuple[int, ...] = version[: version.index(None)]  # type: ignore[assignment]
        except ValueError:
            not_none_version = cast(Tuple[int, ...], version)

        for impl, match in impls.items():
            for at in range(len(not_none_version), -1, -1):
                cur_ver = not_none_version[0:at]
                spec = f"{impl}{'.'.join(str(i) for i in cur_ver)}"
                yield spec, match

    @property
    def is_abs(self) -> bool:
        return self.path is not None and os.path.isabs(self.path)  # noqa: PTH117

    def satisfies(self, spec: PythonSpec) -> bool:
        """Call when there's a candidate metadata spec to see if compatible - e.g., PEP-514 on Windows."""
        if spec.is_abs and self.is_abs and self.path != spec.path:
            return False
        if (
            spec.implementation is not None
            and self.implementation is not None
            and spec.implementation.lower() != self.implementation.lower()
        ):
            return False
        if spec.architecture is not None and spec.architecture != self.architecture:
            return False

        for our, req in zip((self.major, self.minor, self.micro), (spec.major, spec.minor, spec.micro)):
            if req is not None and our is not None and our != req:
                return False
        return True

    def __repr__(self) -> str:
        name = type(self).__name__
        params = "implementation", "major", "minor", "micro", "architecture", "path"
        return f"{name}({', '.join(f'{k}={getattr(self, k)}' for k in params if getattr(self, k) is not None)})"


__all__ = [
    "PythonSpec",
]
