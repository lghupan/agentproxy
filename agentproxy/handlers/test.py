"""Test runner output handlers — keep failures only."""

import re
from ..core.base_handler import BaseHandler

_TEST_CMDS = re.compile(
    r'^(pytest|python3?\s+-m\s+pytest|jest|npx\s+jest|vitest|npx\s+vitest|cargo\s+test)'
)


class TestHandler(BaseHandler):
    def can_handle(self, command: str) -> bool:
        return bool(_TEST_CMDS.match(command.strip()))

    def handle(self, command: str, output: str) -> str:
        try:
            if 'cargo' in command:
                return _compress_cargo_test(output)
            elif 'pytest' in command:
                return _compress_pytest(output)
            else:
                return _compress_jest(output)
        except Exception:
            return output


def _compress_pytest(output: str) -> str:
    lines = output.splitlines()
    failure_block: list[str] = []  # everything inside === FAILURES === ... ===
    summary_line = ''              # "N failed, M passed in Xs"
    in_failures = False

    for line in lines:
        if re.match(r'^={5,}', line):
            if 'FAILURES' in line.upper() or 'ERRORS' in line.upper():
                in_failures = True
            elif in_failures:
                # Next === after FAILURES section — end of failure details
                in_failures = False
            # Capture the final "N failed, M passed" summary line
            if re.search(r'\d+ (failed|passed|error)', line, re.I):
                summary_line = line
        elif in_failures:
            failure_block.append(line)

    result = []
    if failure_block:
        # Strip leading/trailing blank lines from the block
        block = '\n'.join(failure_block).strip()
        if block:
            result.append(block)
    if summary_line:
        result.append(summary_line)
    return '\n'.join(result) if result else output


def _compress_jest(output: str) -> str:
    lines = output.splitlines()
    result = []
    in_failure = False

    for line in lines:
        stripped = line.strip()
        # Failure markers
        if re.match(r'●|✕|✗|FAIL\s', stripped) or 'FAIL' == stripped[:4]:
            in_failure = True
            result.append(line)
        elif in_failure and stripped.startswith('✓') or stripped.startswith('✔') or stripped.startswith('PASS'):
            in_failure = False
        elif in_failure:
            result.append(line)
        # Summary line
        elif re.match(r'Tests?:\s+\d+', stripped) or re.match(r'Test Suites?:', stripped):
            result.append(line)

    return '\n'.join(result) if result else output


def _compress_cargo_test(output: str) -> str:
    lines = output.splitlines()
    result = []

    for line in lines:
        stripped = line.strip()
        if 'FAILED' in line or stripped.startswith('error'):
            result.append(line)
        elif re.match(r'test result:', stripped):
            result.append(line)
        elif 'failures:' in stripped.lower():
            result.append(line)

    return '\n'.join(result) if result else output
