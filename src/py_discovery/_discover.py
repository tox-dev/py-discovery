from __future__ import annotations

from abc import ABCMeta, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace

    from py_discovery import PythonInfo


class Discover(metaclass=ABCMeta):
    """Discover and provide the requested Python interpreter."""

    @classmethod
    def add_parser_arguments(cls, parser: ArgumentParser) -> None:
        """
        Add CLI arguments for this discovery mechanisms.

        :param parser: The CLI parser.

        """
        raise NotImplementedError

    def __init__(self, options: Namespace) -> None:
        """
        Create a new discovery mechanism.

        :param options: The parsed options as defined within the :meth:`add_parser_arguments`.

        """
        self._has_run = False
        self._interpreter: PythonInfo | None = None
        self._env = options.env

    @abstractmethod
    def run(self) -> PythonInfo | None:
        """
        Discovers an interpreter.

        :return: The interpreter ready to use for virtual environment creation

        """
        raise NotImplementedError

    @property
    def interpreter(self) -> PythonInfo | None:
        """:return: the interpreter as returned by the :meth:`run`, cached"""
        if self._has_run is False:
            self._interpreter = self.run()
            self._has_run = True
        return self._interpreter


__all__ = [
    "Discover",
]
