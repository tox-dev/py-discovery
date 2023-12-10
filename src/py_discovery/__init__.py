"""Python discovery."""
from __future__ import annotations

from ._builtin import Builtin, PathPythonInfo, get_interpreter
from ._discover import Discover
from ._info import PythonInfo, VersionInfo
from ._spec import PythonSpec
from ._version import version

__version__ = version  #: version of the package

__all__ = [
    "PythonInfo",
    "VersionInfo",
    "PythonSpec",
    "Discover",
    "Builtin",
    "PathPythonInfo",
    "get_interpreter",
    "__version__",
]
