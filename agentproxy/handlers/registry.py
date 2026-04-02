"""Routes a command to its handler, or returns None for passthrough."""

from ..core.base_handler import BaseHandler
from .git import GitHandler
from .build import BuildHandler
from .test import TestHandler
from .files import FilesHandler
from .grep import GrepHandler
from .filesystem import LsHandler, FindHandler
from .package import PipHandler, NpmHandler, DockerHandler, KubectlHandler

_BUILTIN_HANDLERS: list[BaseHandler] = [
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

# User-generated handlers (from ~/.agentproxy/handlers/) are loaded once at
# import time. They take precedence over built-ins so users can override defaults.
def _load_user_handlers() -> list[BaseHandler]:
    try:
        from ..core.learner import load_user_handlers
        return load_user_handlers()
    except Exception:
        return []


_USER_HANDLERS: list[BaseHandler] = _load_user_handlers()
_HANDLERS: list[BaseHandler] = _USER_HANDLERS + _BUILTIN_HANDLERS


def get_handler(command: str) -> BaseHandler | None:
    for handler in _HANDLERS:
        if handler.can_handle(command):
            return handler
    return None


def reload_user_handlers() -> int:
    """Reload user handlers from disk. Returns count loaded. Called after `agentproxy learn`."""
    global _USER_HANDLERS, _HANDLERS
    _USER_HANDLERS = _load_user_handlers()
    _HANDLERS = _USER_HANDLERS + _BUILTIN_HANDLERS
    return len(_USER_HANDLERS)
