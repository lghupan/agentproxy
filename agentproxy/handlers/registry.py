"""Routes a command to its handler, or returns None for passthrough."""

from ..core.base_handler import BaseHandler
from .git import GitHandler
from .build import BuildHandler
from .test import TestHandler
from .files import FilesHandler
from .grep import GrepHandler
from .filesystem import LsHandler, FindHandler
from .package import PipHandler, NpmHandler, DockerHandler, KubectlHandler

_HANDLERS: list[BaseHandler] = [
    GitHandler(),
    BuildHandler(),
    TestHandler(),
    FilesHandler(),
    GrepHandler(),
    LsHandler(),
    FindHandler(),
    PipHandler(),
    NpmHandler(),
    DockerHandler(),
    KubectlHandler(),
]


def get_handler(command: str) -> BaseHandler | None:
    for handler in _HANDLERS:
        if handler.can_handle(command):
            return handler
    return None
