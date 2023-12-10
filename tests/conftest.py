from __future__ import annotations

import os
import sys
from tempfile import NamedTemporaryFile

import pytest


@pytest.fixture(scope="session")
def _fs_supports_symlink() -> None:
    if hasattr(os, "symlink"):
        if sys.platform == "win32":  # pragma: win32 cover
            with NamedTemporaryFile(prefix="TmP") as tmp_file:
                temp_dir = os.path.dirname(tmp_file.name)  # noqa: PTH120
                dest = os.path.join(temp_dir, f"{tmp_file.name}-{'b'}")  # noqa: PTH118
                try:
                    os.symlink(tmp_file.name, dest)
                    can = True
                except (OSError, NotImplementedError):
                    pass
        else:  # pragma: win32 cover
            can = True
    if not can:  # pragma: no branch
        pytest.skip("No symlink support")  # pragma: no cover
