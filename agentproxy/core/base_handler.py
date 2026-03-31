"""Base class for all command output handlers."""

from abc import ABC, abstractmethod


class BaseHandler(ABC):
    @abstractmethod
    def can_handle(self, command: str) -> bool:
        """Return True if this handler knows how to compress this command's output."""

    @abstractmethod
    def handle(self, command: str, output: str) -> str:
        """Compress and return the output. Must never raise — return original on error."""
