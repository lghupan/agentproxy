"""File read handlers — strip comments, cap length."""

import re
from ..core.base_handler import BaseHandler

_FILE_CMDS = re.compile(r'^cat\s+')
_COMMENT_PATTERNS = {
    '.py': re.compile(r'^\s*#(?!!).*$'),
    '.js': re.compile(r'^\s*//.*$'),
    '.ts': re.compile(r'^\s*//.*$'),
    '.jsx': re.compile(r'^\s*//.*$'),
    '.tsx': re.compile(r'^\s*//.*$'),
    '.go': re.compile(r'^\s*//.*$'),
    '.rs': re.compile(r'^\s*//(?!/).*$'),   # keep doc comments ///
    '.java': re.compile(r'^\s*//.*$'),
    '.c': re.compile(r'^\s*//.*$'),
    '.cpp': re.compile(r'^\s*//.*$'),
    '.rb': re.compile(r'^\s*#(?!!).*$'),
    '.sh': re.compile(r'^\s*#(?!!).*$'),
}


class FilesHandler(BaseHandler):
    def can_handle(self, command: str) -> bool:
        return bool(_FILE_CMDS.match(command.strip()))

    def handle(self, command: str, output: str) -> str:
        try:
            from ..core.config import get
            max_lines = get('cat_max_lines')
            ext = _get_extension(command)
            lines = output.splitlines(keepends=True)
            if ext in _COMMENT_PATTERNS:
                lines = _strip_inline_comments(lines, _COMMENT_PATTERNS[ext])
            if len(lines) > max_lines:
                kept = lines[:max_lines]
                omitted = len(lines) - max_lines
                kept.append(f'\n... ({omitted} lines omitted)\n')
                lines = kept
            return ''.join(lines)
        except Exception:
            return output


def _get_extension(command: str) -> str:
    parts = command.strip().split()
    if len(parts) >= 2:
        filename = parts[-1]
        dot = filename.rfind('.')
        if dot != -1:
            return filename[dot:]
    return ''


def _strip_inline_comments(lines: list[str], pattern: re.Pattern) -> list[str]:
    return [l for l in lines if not pattern.match(l.rstrip('\n'))]
