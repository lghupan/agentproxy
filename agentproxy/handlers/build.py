"""Build and lint tool output handlers — errors first, warnings suppressed when errors exist."""

import re
from ..core.base_handler import BaseHandler

_BUILD_CMDS = re.compile(
    r'^(tsc|npx\s+tsc|cargo\s+(build|check|clippy)|eslint|npx\s+eslint|ruff(\s+check)?)'
)


class BuildHandler(BaseHandler):
    def can_handle(self, command: str) -> bool:
        return bool(_BUILD_CMDS.match(command.strip()))

    def handle(self, command: str, output: str) -> str:
        try:
            if 'tsc' in command:
                return _compress_tsc(output)
            elif 'cargo' in command:
                return _compress_cargo_build(output)
            elif 'eslint' in command:
                return _compress_eslint(output)
            elif 'ruff' in command:
                return _compress_ruff(output)
            else:
                return output
        except Exception:
            return output


def _errors_only_if_present(lines: list[str], error_pred, warning_pred) -> list[str]:
    errors = [l for l in lines if error_pred(l)]
    if errors:
        return errors
    warnings = [l for l in lines if warning_pred(l)]
    return warnings if warnings else lines


def _compress_tsc(output: str) -> str:
    lines = output.splitlines()
    errors = [l for l in lines if re.search(r'error TS\d+', l)]
    warnings = [l for l in lines if re.search(r'warning TS\d+', l)]
    summary = [l for l in lines if 'Found' in l and ('error' in l or 'warning' in l)]

    result = errors if errors else warnings
    result += summary
    return '\n'.join(result) if result else output


def _compress_cargo_build(output: str) -> str:
    lines = output.splitlines()
    errors = [l for l in lines if re.match(r'\s*error(\[E\d+\])?', l)]
    warnings = [l for l in lines if re.match(r'\s*warning(\[.*?\])?', l)]
    summary = [l for l in lines if re.match(r'error\[', l) or 'aborting due to' in l]

    result = (errors + summary) if errors else warnings
    return '\n'.join(result) if result else output


def _compress_eslint(output: str) -> str:
    lines = output.splitlines()
    errors = [l for l in lines if ' error ' in l]
    warnings = [l for l in lines if ' warning ' in l]
    summary = [l for l in lines if re.search(r'\d+ problem', l)]

    result = (errors + summary) if errors else (warnings + summary)
    return '\n'.join(result) if result else output


def _compress_ruff(output: str) -> str:
    lines = output.splitlines()
    # ruff format: path:line:col: E/W code message
    errors = [l for l in lines if re.search(r':\d+:\d+:\s+[EF]\d+', l)]
    warnings = [l for l in lines if re.search(r':\d+:\d+:\s+W\d+', l)]
    summary = [l for l in lines if 'Found' in l or 'fixed' in l.lower()]

    result = (errors + summary) if errors else (warnings + summary)
    return '\n'.join(result) if result else output
