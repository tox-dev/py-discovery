from __future__ import annotations


def test_version() -> None:
    from py_discovery import __version__

    assert __version__
