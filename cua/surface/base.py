"""Abstract surface. Anything the agent can drive implements this.

The whole point: the agent loop and replay engine talk to THIS,
never to Playwright directly. Swap in a desktop/AX-tree surface later
and nothing above this line changes.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from cua.surface.types import Observation, Action


class Surface(ABC):
    @abstractmethod
    def observe(self) -> Observation:
        """Return the current perceivable state (interactive elements + text)."""

    @abstractmethod
    def act(self, action: Action) -> None:
        """Perform one action against the live surface."""

    @abstractmethod
    def screenshot(self, path: str) -> None:
        """Capture a richer evidence signal."""

    @abstractmethod
    def close(self) -> None:
        ...