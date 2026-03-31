"""Universal lossless pre-processing applied to all tool output."""

import re

_ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE.sub('', text)


def strip_progress_lines(lines: list[str]) -> list[str]:
    """Remove carriage-return progress/spinner lines, keeping the final state."""
    result = []
    for line in lines:
        if '\r' in line:
            last = line.rsplit('\r', 1)[-1]
            if last.strip():
                result.append(last)
        else:
            result.append(line)
    return result


def dedup_consecutive(lines: list[str]) -> list[str]:
    """Collapse runs of identical consecutive lines."""
    if not lines:
        return lines
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        j = i + 1
        while j < len(lines) and lines[j] == line:
            j += 1
        result.append(line)
        count = j - i
        if count > 1:
            result.append(f'[above line repeated {count - 1} more time{"s" if count > 2 else ""}]\n')
        i = j
    return result


def collapse_blank_lines(lines: list[str]) -> list[str]:
    """Collapse runs of 3+ blank lines to 2."""
    result = []
    blank_count = 0
    for line in lines:
        if not line.strip():
            blank_count += 1
            if blank_count <= 2:
                result.append(line)
        else:
            blank_count = 0
            result.append(line)
    return result


def preprocess(text: str) -> str:
    """Apply all lossless transformations. Safe for any command output."""
    text = strip_ansi(text)
    lines = text.splitlines(keepends=True)
    lines = strip_progress_lines(lines)
    lines = dedup_consecutive(lines)
    lines = collapse_blank_lines(lines)
    return ''.join(lines)
