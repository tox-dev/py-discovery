"""Python discovery."""

from __future__ import annotations

from ._builtin import Builtin, PathPythonInfo, get_interpreter
from ._discover import Discover
from ._info import PythonInfo, VersionInfo
from ._spec import PythonSpec
from ._version import version

__version__ = version  #: version of the package

__all__ = [
    "Builtin",
    "Discover",
    "PathPythonInfo",
    "PythonInfo",
    "PythonSpec",
    "VersionInfo",
    "__version__",
    "get_interpreter",
]
