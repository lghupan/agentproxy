"""
Minimal coding agent for SWE-bench.

Given a SWE-bench instance, checks out the repo, runs a tool-calling
agent loop to produce a patch, and returns the unified diff.

Works with any OpenAI-compatible model. Point at AgentProxy by passing
base_url='http://127.0.0.1:8080'.
"""

from __future__ import annotations
import json
import os
import subprocess
import tempfile
from pathlib import Path

from openai import OpenAI

_MAX_TURNS = 30
_MAX_TOKENS = 4096

_SYSTEM = """\
You are an expert software engineer fixing a bug in a GitHub repository.
You have access to the codebase via bash and write_file tools.

WORKFLOW:
1. Read the problem statement carefully
2. Find the relevant file(s): grep -r "keyword" --include="*.py" -l
3. Read the file: cat -n path/to/file.py
4. Identify the exact lines that need to change
5. Make the edit using write_file (preferred) or bash with python3/sed
6. Verify the edit: grep -n "new_text" path/to/file.py
7. Run the test: python3 -m pytest path/to/test.py -x -q 2>&1 | tail -20
8. Call finish()

EDITING — use write_file tool (pass the COMPLETE file content):
  write_file(path="src/foo.py", content="...complete file content...")

Or use bash with python3:
  python3 -c "
  import pathlib
  p = pathlib.Path('src/foo.py')
  txt = p.read_text()
  txt = txt.replace('old_line', 'new_line')
  p.write_text(txt)
  print('done')
  "

Or sed:
  sed -i 's/old_text/new_text/g' path/to/file.py

IMPORTANT: You MUST make a code change. Do not just explore — fix the bug.
After 3-4 bash calls for exploration, you must write a fix.
"""

_TOOLS = [
    {
        'type': 'function',
        'function': {
            'name': 'bash',
            'description': 'Run a shell command in the repository directory.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'command': {'type': 'string', 'description': 'Shell command to execute'},
                },
                'required': ['command'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'write_file',
            'description': 'Write complete content to a file. Use this to make code edits.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {'type': 'string', 'description': 'Path to the file relative to repo root'},
                    'content': {'type': 'string', 'description': 'Complete file content to write'},
                },
                'required': ['path', 'content'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'finish',
            'description': 'Submit your solution. Call when the fix is complete.',
            'parameters': {
                'type': 'object',
                'properties': {},
                'required': [],
            },
        },
    },
]

# After this many bash-only turns, inject a nudge to make edits
_NUDGE_AFTER_TURNS = 6


def run_agent(
    instance: dict,
    model: str = 'gpt-5-nano',
    base_url: str | None = None,
    api_key: str | None = None,
) -> dict:
    """
    Run the agent on a single SWE-bench instance.
    Returns a prediction dict with instance_id and model_patch.
    """
    client = OpenAI(
        base_url=base_url,
        api_key=api_key or os.environ.get('OPENAI_API_KEY', 'placeholder'),
    )

    instance_id = instance['instance_id']
    repo = instance['repo']
    base_commit = instance['base_commit']
    problem = instance['problem_statement']

    with tempfile.TemporaryDirectory(prefix=f'swe_{instance_id}_') as workdir:
        # Clone and checkout
        _run(f'git clone https://github.com/{repo} {workdir}', cwd='/')
        _run(f'git checkout {base_commit}', cwd=workdir)

        # Install repo in editable mode if setup exists
        for setup_file in ['setup.py', 'pyproject.toml']:
            if Path(workdir, setup_file).exists():
                _run('pip install -e . -q 2>/dev/null || true', cwd=workdir)
                break

        messages = [
            {'role': 'system', 'content': _SYSTEM},
            {'role': 'user', 'content': (
                f'Repository: {repo}\n'
                f'Base commit: {base_commit}\n\n'
                f'Problem statement:\n\n{problem}\n\n'
                f'The repository has been cloned to your working directory. '
                f'Use bash to explore the code, write_file to make edits, '
                f'and finish() when done.'
            )},
        ]

        patch = ''
        total_tokens = {'prompt': 0, 'completion': 0}
        bash_only_turns = 0  # turns with only bash calls (no writes)
        nudged = False

        for turn in range(_MAX_TURNS):
            # Inject nudge if agent has been exploring too long without edits
            if bash_only_turns >= _NUDGE_AFTER_TURNS and not nudged:
                messages.append({
                    'role': 'user',
                    'content': (
                        'You have explored the codebase enough. '
                        'Now make the actual code fix. '
                        'Use write_file to write the corrected file, '
                        'or use bash with python3 to edit in place. '
                        'Do NOT explore more — write the fix now.'
                    ),
                })
                nudged = True

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=_TOOLS,
                tool_choice='required',
                max_completion_tokens=_MAX_TOKENS,
            )

            if response.usage:
                total_tokens['prompt'] += response.usage.prompt_tokens
                total_tokens['completion'] += response.usage.completion_tokens

            msg = response.choices[0].message
            assistant_msg = {
                'role': 'assistant',
                'content': msg.content or '',
            }
            if msg.tool_calls:
                assistant_msg['tool_calls'] = [
                    {
                        'id': tc.id,
                        'type': 'function',
                        'function': {'name': tc.function.name, 'arguments': tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ]
            messages.append(assistant_msg)

            if not msg.tool_calls:
                # Text-only response — agent finished early
                break

            tool_results = []
            done = False
            turn_has_write = False

            for tc in msg.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments or '{}')

                if name == 'finish':
                    done = True
                    result = 'Patch submitted.'
                elif name == 'bash':
                    result = _run(args.get('command', ''), cwd=workdir)
                elif name == 'write_file':
                    file_path = args.get('path', '')
                    content = args.get('content', '')
                    try:
                        full_path = Path(workdir) / file_path
                        full_path.parent.mkdir(parents=True, exist_ok=True)
                        full_path.write_text(content)
                        result = f'Written {file_path} ({len(content)} bytes)'
                        turn_has_write = True
                    except Exception as e:
                        result = f'Error writing file: {e}'
                else:
                    result = f'Unknown tool: {name}'

                tool_results.append({
                    'role': 'tool',
                    'tool_call_id': tc.id,
                    'content': result[:8000],  # cap long outputs
                })

            messages.extend(tool_results)

            # Track exploration-only turns
            if turn_has_write or done:
                bash_only_turns = 0
            else:
                bash_only_turns += 1

            if done:
                patch = _run('git diff HEAD', cwd=workdir)
                break

        if not patch:
            patch = _run('git diff HEAD', cwd=workdir)

    return {
        'instance_id': instance_id,
        'model_patch': patch,
        'model_name_or_path': model,
        'total_prompt_tokens': total_tokens['prompt'],
        'total_completion_tokens': total_tokens['completion'],
    }


def _run(command: str, cwd: str = '.') -> str:
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=120,
        )
        output = result.stdout + result.stderr
        return output.strip()
    except subprocess.TimeoutExpired:
        return '[command timed out]'
    except Exception as e:
        return f'[error: {e}]'
