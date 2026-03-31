"""Filesystem command handlers — ls, find."""

import re
from ..core.base_handler import BaseHandler

_LS_CMD = re.compile(r'^ls(\s+|$)')
_FIND_CMD = re.compile(r'^find(\s+|$)')

# Extensions that are almost never interesting to agents
_NOISE_EXTENSIONS = frozenset([
    '.pyc', '.pyo', '.pyd', '.class', '.o', '.a', '.so', '.dylib', '.dll',
    '.exe', '.bin', '.obj', '.cache', '.coverage', '.DS_Store', '.egg-info',
])

# Directories that are almost never interesting
_NOISE_DIRS = frozenset([
    '__pycache__', '.git', 'node_modules', '.tox', '.mypy_cache',
    '.pytest_cache', 'venv', '.venv', 'env', '.env', 'dist', 'build',
    '.eggs', '*.egg-info',
])



class LsHandler(BaseHandler):
    def can_handle(self, command: str) -> bool:
        return bool(_LS_CMD.match(command.strip()))

    def handle(self, command: str, output: str) -> str:
        try:
            from ..core.config import get
            lines = output.splitlines()
            result = _compress_ls(lines, max_entries=get('ls_max_entries'))
            return '\n'.join(result) if result else output
        except Exception:
            return output


class FindHandler(BaseHandler):
    def can_handle(self, command: str) -> bool:
        return bool(_FIND_CMD.match(command.strip()))

    def handle(self, command: str, output: str) -> str:
        try:
            from ..core.config import get
            lines = [l for l in output.splitlines() if l.strip()]
            result = _compress_find(lines, max_lines=get('find_max_lines'))
            return '\n'.join(result) if result else output
        except Exception:
            return output


def _compress_ls(lines: list[str], max_entries: int = 50) -> list[str]:
    result = []
    entries = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # total line from ls -l
        if stripped.startswith('total '):
            continue
        # directory headers like "dir:"
        if stripped.endswith(':') and not stripped.startswith('-'):
            if entries:
                result.extend(_format_ls_entries(entries, max_entries=max_entries))
                entries = []
            result.append(line)
            continue
        entries.append(stripped)

    if entries:
        result.extend(_format_ls_entries(entries, max_entries=max_entries))

    return result


def _format_ls_entries(entries: list[str], max_entries: int = 50) -> list[str]:
    # Filter noise files from long-form ls output (ls -l / ls -la)
    filtered = []
    for e in entries:
        # Long form: permissions, links, owner, group, size, date, name
        parts = e.split()
        name = parts[-1] if parts else e
        # Skip hidden files like .git, __pycache__ etc.
        if _is_noise_name(name):
            continue
        filtered.append(e)

    if len(filtered) > max_entries:
        kept = filtered[:max_entries]
        omitted = len(filtered) - max_entries
        kept.append(f'... ({omitted} more entries omitted)')
        return kept

    return filtered


def _compress_find(lines: list[str], max_lines: int = 40) -> list[str]:
    # Filter noise paths
    filtered = []
    for line in lines:
        path = line.strip()
        # Drop paths containing noise dirs or extensions
        parts = path.replace('\\', '/').split('/')
        if any(_is_noise_name(p) for p in parts):
            continue
        ext = _file_ext(path)
        if ext in _NOISE_EXTENSIONS:
            continue
        filtered.append(path)

    if len(filtered) > max_lines:
        kept = filtered[:max_lines]
        omitted = len(filtered) - max_lines
        kept.append(f'... ({omitted} paths omitted)')
        return kept

    return filtered


def _is_noise_name(name: str) -> bool:
    if name in ('.', '..'):
        return False  # current/parent dir markers are not noise
    return name in _NOISE_DIRS or name.startswith('.')


def _file_ext(path: str) -> str:
    dot = path.rfind('.')
    slash = path.rfind('/')
    if dot > slash:
        return path[dot:]
    return ''
