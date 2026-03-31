"""Package manager and infra command handlers — pip, npm, docker, kubectl."""

import re
from ..core.base_handler import BaseHandler

_PIP_CMD = re.compile(r'^pip3?\s+')
_NPM_CMD = re.compile(r'^(npm|pnpm|yarn)\s+')
_DOCKER_CMD = re.compile(r'^docker\s+')
_KUBECTL_CMD = re.compile(r'^kubectl\s+')


class PipHandler(BaseHandler):
    def can_handle(self, command: str) -> bool:
        return bool(_PIP_CMD.match(command.strip()))

    def handle(self, command: str, output: str) -> str:
        try:
            cmd = command.strip()
            if 'install' in cmd:
                return _compress_pip_install(output)
            if 'list' in cmd or 'freeze' in cmd:
                return _compress_pip_list(output)
            return output
        except Exception:
            return output


class NpmHandler(BaseHandler):
    def can_handle(self, command: str) -> bool:
        return bool(_NPM_CMD.match(command.strip()))

    def handle(self, command: str, output: str) -> str:
        try:
            cmd = command.strip()
            if any(x in cmd for x in ['install', 'ci', 'add']):
                return _compress_npm_install(output)
            if 'list' in cmd or 'ls' in cmd:
                return _compress_npm_list(output)
            return output
        except Exception:
            return output


class DockerHandler(BaseHandler):
    def can_handle(self, command: str) -> bool:
        return bool(_DOCKER_CMD.match(command.strip()))

    def handle(self, command: str, output: str) -> str:
        try:
            cmd = command.strip()
            if 'logs' in cmd:
                return _compress_docker_logs(output)
            if 'ps' in cmd:
                return _compress_docker_ps(output)
            return output
        except Exception:
            return output


class KubectlHandler(BaseHandler):
    def can_handle(self, command: str) -> bool:
        return bool(_KUBECTL_CMD.match(command.strip()))

    def handle(self, command: str, output: str) -> str:
        try:
            cmd = command.strip()
            if 'logs' in cmd:
                return _compress_docker_logs(output)  # same pattern
            if any(x in cmd for x in ['get pods', 'get po', 'get nodes', 'get svc']):
                return _compress_kubectl_get(output)
            return output
        except Exception:
            return output


# ---------------------------------------------------------------------------
# pip
# ---------------------------------------------------------------------------

_PIP_NOISE = re.compile(
    r'^(Requirement already satisfied|Collecting |Downloading |Installing collected|'
    r'Using cached|Found existing|Building wheels|Built |Created wheel|'
    r'Stored in directory|WARNING: pip|DEPRECATION|━+|[\-\s]*$)'
)


def _compress_pip_install(output: str) -> str:
    lines = output.splitlines()
    result = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _PIP_NOISE.match(stripped):
            continue
        # Keep: Successfully installed, error lines, version conflict lines
        result.append(line)
    return '\n'.join(result) if result else output


def _compress_pip_list(output: str) -> list[str]:
    # pip list produces a two-line header + one package per line
    # Just pass through — usually small enough already
    return output


# ---------------------------------------------------------------------------
# npm / pnpm / yarn
# ---------------------------------------------------------------------------

_NPM_NOISE = re.compile(
    r'^(npm warn|npm notice|npm http|yarn warning|WARN |added \d+ packages|'
    r'audited \d+|found \d+ vulnerabilities|up to date|resolved \d+|'
    r'Packages are hard linked|Already up-to-date|Lockfile|'
    r'[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏])',
    re.IGNORECASE
)


def _compress_npm_install(output: str) -> str:
    lines = output.splitlines()
    result = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _NPM_NOISE.match(stripped):
            continue
        result.append(line)
    # If nothing left, keep the last meaningful line
    return '\n'.join(result) if result else output.strip().splitlines()[-1]


def _compress_npm_list(output: str) -> str:
    lines = output.splitlines()
    if len(lines) <= 30:
        return output
    kept = lines[:30]
    kept.append(f'... ({len(lines) - 30} more packages omitted)')
    return '\n'.join(kept)


# ---------------------------------------------------------------------------
# docker logs / kubectl logs
# ---------------------------------------------------------------------------

_LOG_LEVELS = re.compile(
    r'\b(error|err|critical|fatal|exception|traceback|panic|failed|failure)\b',
    re.IGNORECASE,
)


def _compress_docker_logs(output: str) -> str:
    from ..core.config import get
    max_log_lines = get('log_max_lines')
    tail_lines = max_log_lines // 5  # tail is 20% of the cap
    error_cap = get('log_error_cap')

    lines = output.splitlines()
    if len(lines) <= max_log_lines:
        return output

    # Keep all error lines + last N lines
    errors = [l for l in lines if _LOG_LEVELS.search(l)]
    tail = lines[-tail_lines:]

    result = []
    if errors:
        result.append(f'--- Errors ({len(errors)} lines) ---')
        result.extend(errors[-error_cap:])
    result.append(f'--- Last {tail_lines} lines (of {len(lines)} total) ---')
    result.extend(tail)
    return '\n'.join(result)


# ---------------------------------------------------------------------------
# docker ps / kubectl get
# ---------------------------------------------------------------------------

def _compress_docker_ps(output: str) -> str:
    lines = output.splitlines()
    if len(lines) <= 20:
        return output
    # Header + first 20 containers
    kept = lines[:21]
    kept.append(f'... ({len(lines) - 21} more containers omitted)')
    return '\n'.join(kept)


def _compress_kubectl_get(output: str) -> str:
    lines = output.splitlines()
    if len(lines) <= 30:
        return output
    kept = lines[:31]
    kept.append(f'... ({len(lines) - 31} more rows omitted)')
    return '\n'.join(kept)
