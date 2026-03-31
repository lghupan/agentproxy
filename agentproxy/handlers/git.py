import re
from ..core.base_handler import BaseHandler

_GIT_CMD = re.compile(r'^git\s+(\w+)')


class GitHandler(BaseHandler):
    def can_handle(self, command: str) -> bool:
        return bool(_GIT_CMD.match(command.strip()))

    def handle(self, command: str, output: str) -> str:
        m = _GIT_CMD.match(command.strip())
        subcommand = m.group(1) if m else ''
        try:
            if subcommand == 'status':
                return _compress_status(output)
            elif subcommand in ('diff', 'show'):
                return _compress_diff(output)
            elif subcommand == 'log':
                return _compress_log(output)
            else:
                return output
        except Exception:
            return output


def _compress_status(output: str) -> str:
    lines = output.splitlines()
    branch = ''
    upstream_status = ''
    staged, unstaged, untracked = [], [], []
    section = None

    for line in lines:
        if line.startswith('On branch'):
            branch = line.split()[-1]
        elif 'up to date' in line:
            upstream_status = 'up to date'
        elif "ahead" in line or "behind" in line:
            upstream_status = line.strip().strip("()")
        elif 'Changes to be committed' in line:
            section = 'staged'
        elif 'Changes not staged' in line:
            section = 'unstaged'
        elif 'Untracked files' in line:
            section = 'untracked'
        elif line.startswith('\t') or line.startswith('        '):
            item = line.strip()
            if item and not item.startswith('(use'):
                if section == 'staged':
                    staged.append(item)
                elif section == 'unstaged':
                    unstaged.append(item)
                elif section == 'untracked':
                    untracked.append(item)

    parts = []
    branch_str = f'Branch: {branch}' if branch else ''
    if upstream_status:
        branch_str += f' ({upstream_status})'
    if branch_str:
        parts.append(branch_str)

    def fmt(label: str, items: list[str]) -> str:
        preview = ', '.join(items[:5])
        suffix = f' +{len(items) - 5} more' if len(items) > 5 else ''
        return f'{label} ({len(items)}): {preview}{suffix}'

    if staged:
        parts.append(fmt('Staged', staged))
    if unstaged:
        parts.append(fmt('Modified', unstaged))
    if untracked:
        parts.append(fmt('Untracked', untracked))
    if not any([staged, unstaged, untracked]):
        parts.append('Clean working tree')

    return '\n'.join(parts)


def _compress_diff(output: str, max_hunk_lines: int | None = None) -> str:
    if max_hunk_lines is None:
        from ..core.config import get
        max_hunk_lines = get('git_diff_hunk_lines')
    lines = output.splitlines(keepends=True)
    result = []
    hunk_lines = 0
    in_hunk = False
    truncated = 0

    for line in lines:
        if line.startswith('diff --git') or line.startswith('---') or line.startswith('+++'):
            if truncated:
                result.append(f'... ({truncated} lines omitted)\n')
                truncated = 0
            in_hunk = False
            hunk_lines = 0
            result.append(line)
        elif line.startswith('@@'):
            if truncated:
                result.append(f'... ({truncated} lines omitted)\n')
                truncated = 0
            in_hunk = True
            hunk_lines = 0
            result.append(line)
        elif in_hunk:
            if hunk_lines < max_hunk_lines:
                result.append(line)
                hunk_lines += 1
            else:
                truncated += 1
        else:
            result.append(line)

    if truncated:
        result.append(f'... ({truncated} lines omitted)\n')

    return ''.join(result)


def _compress_log(output: str, max_entries: int = 20) -> str:
    """Collapse multi-line log entries to one line each."""
    lines = output.splitlines()
    entries = []
    current: list[str] = []

    for line in lines:
        if line.startswith('commit ') and current:
            entries.append(_fmt_log_entry(current))
            current = [line]
        else:
            current.append(line)
    if current:
        entries.append(_fmt_log_entry(current))

    # If already one-line format (--oneline), just cap
    if all(len(e.splitlines()) == 1 for e in entries):
        result = entries[:max_entries]
        if len(entries) > max_entries:
            result.append(f'... ({len(entries) - max_entries} more commits)')
        return '\n'.join(result)

    result = entries[:max_entries]
    if len(entries) > max_entries:
        result.append(f'... ({len(entries) - max_entries} more commits)')
    return '\n'.join(result)


def _fmt_log_entry(lines: list[str]) -> str:
    sha = ''
    author = ''
    date = ''
    subject = ''
    for line in lines:
        if line.startswith('commit '):
            sha = line.split()[1][:7]
        elif line.startswith('Author:'):
            author = line.split(':', 1)[1].strip()
        elif line.startswith('Date:'):
            date = line.split(':', 1)[1].strip()
        elif line.strip() and not line.startswith('commit') and not line.startswith('Author') and not line.startswith('Date') and not line.startswith('Merge'):
            if not subject:
                subject = line.strip()[:80]
    return f'{sha} {subject} ({date}) <{author}>'
