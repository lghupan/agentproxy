"""Grep output handler — group by file, cap results per file."""

import re
from collections import defaultdict
from ..core.base_handler import BaseHandler

_GREP_CMDS = re.compile(r'^(grep|rg|ripgrep)(\s+|$)')


class GrepHandler(BaseHandler):
    def can_handle(self, command: str) -> bool:
        return bool(_GREP_CMDS.match(command.strip()))

    def handle(self, command: str, output: str) -> str:
        try:
            return _compress_grep(output)
        except Exception:
            return output


def _compress_grep(output: str) -> str:
    from ..core.config import get
    max_per_file = get('grep_per_file')
    max_files = get('grep_max_files')

    lines = output.splitlines()
    # grep -n format: filename:line_number:content  or  filename:content
    by_file: dict[str, list[str]] = defaultdict(list)
    bare: list[str] = []

    for line in lines:
        # Try to parse file:lnum:content or file:content
        m = re.match(r'^([^:\n]+):(\d+:)?(.*)$', line)
        if m and ('/' in m.group(1) or m.group(2)):
            filename = m.group(1)
            by_file[filename].append(line)
        else:
            bare.append(line)

    if not by_file:
        # No file grouping possible — just cap total lines
        cap = max_per_file * max_files
        if len(bare) > cap:
            omitted = len(bare) - cap
            return '\n'.join(bare[:cap]) + f'\n... ({omitted} more lines)'
        return output

    result = []
    files = list(by_file.keys())[:max_files]
    omitted_files = len(by_file) - max_files

    for filename in files:
        file_lines = by_file[filename]
        result.append(f'{filename} ({len(file_lines)} match{"es" if len(file_lines) != 1 else ""}):')
        shown = file_lines[:max_per_file]
        result.extend(f'  {l}' for l in shown)
        if len(file_lines) > max_per_file:
            result.append(f'  ... ({len(file_lines) - max_per_file} more)')

    if omitted_files > 0:
        result.append(f'... ({omitted_files} more files)')

    return '\n'.join(result)
