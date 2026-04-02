"""
Miss tracking — log unhandled commands and surface compression opportunities.

When the proxy passes a tool result through unchanged (no handler matched),
it calls log_miss(). Stats are written to ~/.agentproxy/misses.jsonl.

agentproxy stats reads that file and ranks commands by total bytes passed
through, so you know exactly what handler to write next.
"""

from __future__ import annotations
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

_STATS_DIR = Path.home() / '.agentproxy'
_MISSES_FILE = _STATS_DIR / 'misses.jsonl'

# Two-word prefixes worth keeping together (e.g. "git diff", "docker logs")
_TWO_WORD_PREFIXES = frozenset([
    'git', 'docker', 'kubectl', 'npm', 'pnpm', 'yarn', 'cargo',
    'go', 'make', 'aws', 'gh',
])


_MAX_SAMPLES_PER_PREFIX = 5
_MAX_SAMPLE_BYTES = 8192


def log_miss(command: str, output: str) -> None:
    """Append one miss record to the misses file and save an output sample. Never raises."""
    try:
        _STATS_DIR.mkdir(parents=True, exist_ok=True)
        record = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'command': command.strip()[:200],
            'bytes': len(output.encode()),
        }
        with open(_MISSES_FILE, 'a') as f:
            f.write(json.dumps(record) + '\n')
    except Exception:
        pass

    # Save output sample for handler learning (best-effort)
    try:
        prefix = _normalize(command)
        samples_dir = _STATS_DIR / 'samples' / _safe_dirname(prefix)
        samples_dir.mkdir(parents=True, exist_ok=True)
        existing = sorted(samples_dir.glob('sample_*.txt'))
        if len(existing) < _MAX_SAMPLES_PER_PREFIX:
            idx = len(existing)
            sample_path = samples_dir / f'sample_{idx}.txt'
            # Store: command on first line, then output (capped)
            content = f'# command: {command.strip()}\n{output[:_MAX_SAMPLE_BYTES]}'
            sample_path.write_text(content, encoding='utf-8', errors='replace')
    except Exception:
        pass


def _safe_dirname(prefix: str) -> str:
    """Convert a command prefix to a safe directory name."""
    return re.sub(r'[^\w\-]', '_', prefix)[:60]


def get_samples(command_prefix: str) -> list[dict]:
    """
    Return saved output samples for a command prefix.
    Each entry: {'command': str, 'output': str}
    """
    safe = _safe_dirname(_normalize(command_prefix))
    samples_dir = _STATS_DIR / 'samples' / safe
    if not samples_dir.exists():
        return []
    results = []
    for path in sorted(samples_dir.glob('sample_*.txt')):
        try:
            text = path.read_text(encoding='utf-8', errors='replace')
            lines = text.split('\n', 1)
            cmd = lines[0].replace('# command: ', '').strip() if lines else command_prefix
            output = lines[1] if len(lines) > 1 else text
            results.append({'command': cmd, 'output': output})
        except Exception:
            continue
    return results


def read_stats(top_n: int = 20) -> list[dict]:
    """
    Read misses.jsonl and return top_n command prefixes ranked by total bytes.

    Each entry:
      prefix      — normalized command prefix (e.g. "git diff", "sed")
      calls       — number of times seen
      total_bytes — total bytes passed through uncompressed
      avg_bytes   — average bytes per call
      example     — one full command string seen
    """
    if not _MISSES_FILE.exists():
        return []

    totals: dict[str, dict] = defaultdict(lambda: {'calls': 0, 'total_bytes': 0, 'example': ''})

    with open(_MISSES_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            cmd = rec.get('command', '')
            prefix = _normalize(cmd)
            totals[prefix]['calls'] += 1
            totals[prefix]['total_bytes'] += rec.get('bytes', 0)
            if not totals[prefix]['example']:
                totals[prefix]['example'] = cmd

    rows = [
        {
            'prefix': prefix,
            'calls': d['calls'],
            'total_bytes': d['total_bytes'],
            'avg_bytes': d['total_bytes'] // d['calls'] if d['calls'] else 0,
            'example': d['example'],
        }
        for prefix, d in totals.items()
    ]
    rows.sort(key=lambda r: r['total_bytes'], reverse=True)
    return rows[:top_n]


def clear_stats() -> None:
    """Delete the misses file."""
    try:
        _MISSES_FILE.unlink(missing_ok=True)
    except Exception:
        pass


_SAVINGS_FILE = _STATS_DIR / 'savings.jsonl'


def log_saving(command: str, chars_before: int, chars_after: int) -> None:
    """Log a successful compression event. Never raises."""
    if chars_before <= chars_after:
        return  # no net saving, skip
    try:
        _STATS_DIR.mkdir(parents=True, exist_ok=True)
        record = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'command': command.strip()[:200],
            'chars_before': chars_before,
            'chars_after': chars_after,
        }
        with open(_SAVINGS_FILE, 'a') as f:
            f.write(json.dumps(record) + '\n')
    except Exception:
        pass


def read_savings() -> dict:
    """
    Aggregate savings.jsonl and return a summary dict:
      total_chars_before, total_chars_saved, reduction_pct, total_calls,
      top_commands: list of {command, calls, chars_before, chars_after, pct}
    """
    if not _SAVINGS_FILE.exists():
        return {
            'total_chars_before': 0, 'total_chars_saved': 0,
            'reduction_pct': 0.0, 'total_calls': 0, 'top_commands': [],
        }

    totals: dict[str, dict] = defaultdict(
        lambda: {'calls': 0, 'chars_before': 0, 'chars_after': 0}
    )

    with open(_SAVINGS_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            cmd = _normalize(rec.get('command', ''))
            totals[cmd]['calls'] += 1
            totals[cmd]['chars_before'] += rec.get('chars_before', 0)
            totals[cmd]['chars_after'] += rec.get('chars_after', 0)

    total_before = sum(d['chars_before'] for d in totals.values())
    total_after = sum(d['chars_after'] for d in totals.values())
    total_saved = total_before - total_after
    total_calls = sum(d['calls'] for d in totals.values())

    top = sorted(totals.items(), key=lambda x: x[1]['chars_before'] - x[1]['chars_after'], reverse=True)
    top_commands = [
        {
            'command': cmd,
            'calls': d['calls'],
            'chars_before': d['chars_before'],
            'chars_after': d['chars_after'],
            'pct': (d['chars_before'] - d['chars_after']) / d['chars_before'] * 100
                   if d['chars_before'] > 0 else 0.0,
        }
        for cmd, d in top[:10]
    ]

    return {
        'total_chars_before': total_before,
        'total_chars_saved': total_saved,
        'reduction_pct': total_saved / total_before * 100 if total_before > 0 else 0.0,
        'total_calls': total_calls,
        'top_commands': top_commands,
    }


def clear_savings() -> None:
    try:
        _SAVINGS_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _normalize(command: str) -> str:
    """Return a short canonical prefix for grouping similar commands."""
    parts = command.strip().split()
    if not parts:
        return '(empty)'
    first = parts[0]
    # Strip path prefix (e.g. /usr/bin/git → git)
    first = first.rsplit('/', 1)[-1]
    if first in _TWO_WORD_PREFIXES and len(parts) >= 2:
        return f'{first} {parts[1]}'
    return first
