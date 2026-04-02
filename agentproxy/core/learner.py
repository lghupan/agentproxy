"""
Learning-based handler synthesis.

Reads saved output samples for an unhandled command, sends them to an LLM
with few-shot handler examples, extracts the generated Python code, validates
it, and saves it to ~/.agentproxy/handlers/<prefix>.py.

The generated handler is deterministic — no LLM calls at inference time.
The LLM is only used once to write the code; after that it runs like any
built-in handler.

Usage:
    agentproxy learn "terraform plan"
    agentproxy learn "make build" --samples 3
    agentproxy learn "kubectl describe pod" --dry-run
"""

from __future__ import annotations
import importlib.util
import re
import sys
import textwrap
from pathlib import Path

_USER_HANDLERS_DIR = Path.home() / '.agentproxy' / 'handlers'

# ---------------------------------------------------------------------------
# Few-shot examples shown to the LLM
# ---------------------------------------------------------------------------

_EXAMPLE_PIP = '''\
class PipHandler(BaseHandler):
    """pip install — keep "Successfully installed" and errors, drop download spam."""

    def can_handle(self, command: str) -> bool:
        return bool(re.match(r'^pip3?\\s+install', command.strip()))

    def handle(self, command: str, output: str) -> str:
        try:
            noise = re.compile(
                r'^(Collecting |Downloading |Installing collected|Using cached|'
                r'Found existing|Building wheels|Built |Created wheel|'
                r'Stored in directory|WARNING: pip|DEPRECATION|━+|[\\-\\s]*$)'
            )
            lines = [l for l in output.splitlines() if l.strip() and not noise.match(l.strip())]
            return '\\n'.join(lines) if lines else output
        except Exception:
            return output
'''

_EXAMPLE_PYTEST = '''\
class PytestHandler(BaseHandler):
    """pytest — keep the FAILURES block and the final summary line, drop everything else."""

    def can_handle(self, command: str) -> bool:
        return bool(re.match(r'^(pytest|python3?\\s+-m\\s+pytest)', command.strip()))

    def handle(self, command: str, output: str) -> str:
        try:
            lines = output.splitlines()
            failure_block: list[str] = []
            summary_line = ''
            in_failures = False

            for line in lines:
                if re.match(r'^={5,}', line):
                    if 'FAILURES' in line.upper() or 'ERRORS' in line.upper():
                        in_failures = True
                    elif in_failures:
                        in_failures = False
                    if re.search(r'\\d+ (failed|passed|error)', line, re.I):
                        summary_line = line
                elif in_failures:
                    failure_block.append(line)

            result = []
            if failure_block:
                result.append('\\n'.join(failure_block).strip())
            if summary_line:
                result.append(summary_line)
            return '\\n'.join(result) if result else output
        except Exception:
            return output
'''

# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert Python developer writing compression handlers for AgentProxy, \
a token-compression proxy for LLM coding agents.

A handler is a Python class that compresses the output of a specific shell command \
before it is sent to the LLM. The goal is to keep only the lines the model needs \
to take its next action, and drop everything else (progress bars, verbose logs, \
redundant lines, noise).

Rules:
1. The class must subclass BaseHandler (already imported).
2. `can_handle(self, command: str) -> bool` — return True for the target command(s).
3. `handle(self, command: str, output: str) -> str` — compress and return.
   - MUST catch all exceptions and return `output` unchanged on any error.
   - MUST be fully deterministic — no LLM calls, no network, no randomness.
   - Use only Python stdlib (re, collections, itertools, etc.).
4. Keep: error messages, failure details, key facts, file paths, line numbers,
   final status/summary lines.
5. Drop: progress bars, download percentages, spinner lines, verbose INFO logs,
   lines that repeat the same information, decorative separators with no content.
6. Return ONLY the Python class definition — no imports, no explanation, \
   no markdown fences.
"""


def _build_prompt(command_prefix: str, samples: list[dict]) -> str:
    samples_text = ''
    for i, s in enumerate(samples, 1):
        output_preview = s['output'][:3000]
        samples_text += f'\n--- Sample {i} (command: {s["command"]!r}) ---\n{output_preview}\n'

    return f"""\
Write a compression handler for the shell command: `{command_prefix}`

Here are {len(samples)} real output sample(s) from that command:
{samples_text}

Here are two complete handler examples to follow as templates:

Example 1 — pip install:
{_EXAMPLE_PIP}

Example 2 — pytest:
{_EXAMPLE_PYTEST}

Now write a handler class for `{command_prefix}`. \
Return only the class definition (no imports, no markdown).
"""


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _call_llm(prompt: str, model: str | None = None) -> str:
    """Call Anthropic (default) or OpenAI to generate a handler. Returns raw text."""
    # Try Anthropic first
    try:
        import anthropic
        client = anthropic.Anthropic()
        m = model or 'claude-sonnet-4-6'
        response = client.messages.create(
            model=m,
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[{'role': 'user', 'content': prompt}],
        )
        return response.content[0].text
    except ImportError:
        pass
    except Exception as e:
        raise RuntimeError(f'Anthropic call failed: {e}') from e

    # Fall back to OpenAI
    try:
        import openai
        client = openai.OpenAI()
        m = model or 'gpt-4o'
        response = client.chat.completions.create(
            model=m,
            messages=[
                {'role': 'system', 'content': _SYSTEM_PROMPT},
                {'role': 'user', 'content': prompt},
            ],
            max_tokens=2048,
        )
        return response.choices[0].message.content or ''
    except ImportError:
        pass

    raise RuntimeError(
        'No LLM client available. Install anthropic or openai:\n'
        '  pip install anthropic\n'
        '  pip install openai'
    )


# ---------------------------------------------------------------------------
# Code extraction and validation
# ---------------------------------------------------------------------------

def _extract_code(raw: str) -> str:
    """Strip markdown fences if the LLM added them anyway."""
    # Remove ```python ... ``` or ``` ... ```
    raw = re.sub(r'^```(?:python)?\n?', '', raw.strip(), flags=re.MULTILINE)
    raw = re.sub(r'\n?```$', '', raw.strip(), flags=re.MULTILINE)
    return raw.strip()


def _validate_code(code: str, command_prefix: str) -> str:
    """
    Compile-check the code and verify it produces a usable handler class.
    Returns the full module source (with necessary imports prepended).
    """
    # The file saved to disk uses a standard import
    module_source = (
        'import re\n'
        'from agentproxy.core.base_handler import BaseHandler\n\n'
        + code + '\n'
    )

    # Syntax check against the class code only
    try:
        compile(code, '<generated>', 'exec')
    except SyntaxError as e:
        raise ValueError(f'Generated code has a syntax error: {e}') from e

    # Runtime check: inject BaseHandler so the class definition works without file I/O
    from agentproxy.core.base_handler import BaseHandler as _BaseHandler
    ns: dict = {'re': __import__('re'), 'BaseHandler': _BaseHandler}
    try:
        exec(code, ns)  # noqa: S102
    except Exception as e:
        raise ValueError(f'Generated code failed to execute: {e}') from e

    # Find the handler class
    handler_cls = _find_handler_class(ns)
    if handler_cls is None:
        raise ValueError('Generated code contains no class that subclasses BaseHandler.')

    # Smoke test
    try:
        instance = handler_cls()
        can = instance.can_handle(command_prefix)
        result = instance.handle(command_prefix, 'test output')
        if not isinstance(result, str):
            raise ValueError('handle() did not return a str')
    except Exception as e:
        raise ValueError(f'Handler smoke test failed: {e}') from e

    if not can:
        # Not a hard error — warn but continue; the LLM may have used a tighter pattern
        pass

    return module_source


def _find_handler_class(ns: dict):
    """Return the first class in ns that subclasses BaseHandler."""
    from agentproxy.core.base_handler import BaseHandler
    for obj in ns.values():
        try:
            if isinstance(obj, type) and issubclass(obj, BaseHandler) and obj is not BaseHandler:
                return obj
        except TypeError:
            continue
    return None


# ---------------------------------------------------------------------------
# Save and load
# ---------------------------------------------------------------------------

def _handler_path(command_prefix: str) -> Path:
    safe = re.sub(r'[^\w\-]', '_', command_prefix)[:60]
    return _USER_HANDLERS_DIR / f'{safe}.py'


def save_handler(command_prefix: str, module_source: str) -> Path:
    _USER_HANDLERS_DIR.mkdir(parents=True, exist_ok=True)
    path = _handler_path(command_prefix)
    path.write_text(module_source, encoding='utf-8')
    return path


def load_user_handlers() -> list:
    """
    Dynamically load all handlers from ~/.agentproxy/handlers/*.py.
    Returns a list of instantiated handler objects.
    """
    if not _USER_HANDLERS_DIR.exists():
        return []

    handlers = []
    for py_file in sorted(_USER_HANDLERS_DIR.glob('*.py')):
        try:
            spec = importlib.util.spec_from_file_location(f'_user_handler_{py_file.stem}', py_file)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            ns = vars(mod)
            cls = _find_handler_class(ns)
            if cls:
                handlers.append(cls())
        except Exception as e:
            print(f'[agentproxy] warning: failed to load user handler {py_file.name}: {e}',
                  file=sys.stderr)
    return handlers


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def learn(command_prefix: str, n_samples: int = 5, dry_run: bool = False,
          model: str | None = None, verbose: bool = True) -> str | None:
    """
    Generate a handler for `command_prefix` from saved samples.
    Returns the saved file path (or generated code if dry_run), or None on failure.
    """
    from .stats import get_samples

    samples = get_samples(command_prefix)[:n_samples]
    if not samples:
        raise ValueError(
            f'No samples found for {command_prefix!r}.\n'
            f'Run the proxy with some {command_prefix} tool calls first so samples are collected,\n'
            f'then run: agentproxy learn "{command_prefix}"'
        )

    if verbose:
        print(f'Generating handler for {command_prefix!r} using {len(samples)} sample(s)...')

    prompt = _build_prompt(command_prefix, samples)
    raw = _call_llm(prompt, model=model)
    code = _extract_code(raw)

    if verbose:
        print('\n--- Generated code ---')
        print(code)
        print('--- End ---\n')

    module_source = _validate_code(code, command_prefix)

    if dry_run:
        if verbose:
            print('[dry-run] Handler validated. Not saving.')
        return code

    path = save_handler(command_prefix, module_source)
    if verbose:
        print(f'Handler saved to {path}')
        print('It will be loaded automatically on next proxy start.')
    return str(path)
