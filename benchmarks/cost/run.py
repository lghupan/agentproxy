"""
Cost saving benchmark.

Measures token reduction achieved by AgentProxy compression across
realistic tool output samples. Reports per-handler and aggregate savings,
and writes a markdown report to benchmarks/cost/report.md.

Usage:
  python benchmarks/cost/run.py
"""

import sys
import os
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import tiktoken
from agentproxy.core.pipeline import preprocess
from agentproxy.handlers.registry import get_handler

_ENC = tiktoken.get_encoding('cl100k_base')


def count_tokens(text: str) -> int:
    return len(_ENC.encode(text))


# ---------------------------------------------------------------------------
# Realistic tool output samples
# ---------------------------------------------------------------------------

# git diff with 80-line hunk — exceeds the 50-line truncation threshold
_GIT_DIFF_HUNK = "\n".join(
    [f" context_line_{i} = some_value_{i}  # unchanged" for i in range(80)]
)

SAMPLES = {
    'git diff': f"""\
diff --git a/src/auth/middleware.py b/src/auth/middleware.py
index a1b2c3d..e4f5a6b 100644
--- a/src/auth/middleware.py
+++ b/src/auth/middleware.py
@@ -1,8 +1,8 @@
 import jwt
 import logging
-from datetime import datetime
+from datetime import datetime, timezone
 from functools import wraps
 from flask import request, jsonify, current_app
-from models import User
+from models import User, Session
@@ -45,6 +45,87 @@ def require_auth(f):
     @wraps(f)
     def decorated(*args, **kwargs):
         token = request.headers.get('Authorization', '').replace('Bearer ', '')
+        if not token:
+            return jsonify({{'error': 'Missing token'}}), 401
         try:
             payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
             user = User.query.get(payload['user_id'])
         except jwt.ExpiredSignatureError:
             return jsonify({{'error': 'Token expired'}}), 401
+        except jwt.InvalidTokenError as e:
+            logger.warning(f'Invalid token: {{e}}')
+            return jsonify({{'error': 'Invalid token'}}), 401
{_GIT_DIFF_HUNK}
""",

    'git status': """\
On branch feature/auth-refactor
Your branch is ahead of 'origin/feature/auth-refactor' by 3 commits.
  (use "git push" to publish your local commits)

Changes to be committed:
  (use "git restore --staged <file>..." to unstage)
	modified:   src/auth/middleware.py
	modified:   src/auth/models.py
	new file:   src/auth/session.py
	modified:   tests/test_auth.py
	modified:   tests/test_middleware.py

Changes not staged for commit:
  (use "git restore <file>..." to discard changes in working directory)
	modified:   src/utils/helpers.py
	modified:   docs/api.md

Untracked files:
  (use "git add <file>..." to include in what will be committed)
	scratch.py
	.env.local
""",

    'pytest': """\
============================= test session starts ==============================
platform linux -- Python 3.11.4, pytest-7.4.0, pluggy-1.2.0
rootdir: /workspace
configfile: pytest.ini
collecting ... collected 847 items

tests/test_users.py::test_create_user PASSED                           [  0%]
tests/test_users.py::test_create_user_duplicate_email PASSED           [  0%]
tests/test_users.py::test_get_user PASSED                              [  0%]
tests/test_users.py::test_update_user PASSED                           [  0%]
tests/test_users.py::test_delete_user PASSED                           [  1%]
tests/test_auth.py::test_login_success PASSED                          [  1%]
tests/test_auth.py::test_login_invalid_password PASSED                 [  1%]
tests/test_auth.py::test_login_missing_fields PASSED                   [  1%]
tests/test_auth.py::test_token_refresh PASSED                          [  2%]
tests/test_auth.py::test_token_expiry FAILED                           [  2%]

================================== FAILURES ===================================
_________________________ test_token_expiry ____________________________

    def test_token_expiry():
        token = create_token(user_id=1, expires_in=-1)
        response = client.get('/api/profile', headers={'Authorization': f'Bearer {token}'})
>       assert response.status_code == 401
E       AssertionError: assert 200 == 401
E        +  where 200 = <Response [200]>.status_code

tests/test_auth.py:88: AssertionError
----------------------- Captured log call -----------------------
WARNING  auth.middleware:middleware.py:57 Invalid token: Signature has expired

tests/test_auth.py::test_require_auth_no_token FAILED                  [  2%]

    def test_require_auth_no_token():
        response = client.get('/api/profile')
>       assert response.status_code == 401
E       AssertionError: assert 200 == 401

tests/test_auth.py:102: AssertionError
""" + "\n".join([f"tests/test_api.py::test_endpoint_{i} PASSED" for i in range(200)]) + """

=========================== short test summary info ============================
FAILED tests/test_auth.py::test_token_expiry - AssertionError: assert 200 == 401
FAILED tests/test_auth.py::test_require_auth_no_token - AssertionError: assert 200 == 401
============================== 2 failed, 845 passed in 12.34s ==================
""",

    'tsc': """\
src/components/UserProfile.tsx(45,18): error TS2339: Property 'userName' does not exist on type 'User'.
src/components/UserProfile.tsx(67,5): error TS2345: Argument of type 'string | undefined' is not assignable to parameter of type 'string'.
src/api/client.ts(23,10): error TS2305: Module '"axios"' has no exported member 'AxiosRequestConfig'.
src/utils/format.ts(12,3): warning TS6133: 'unused' is declared but its value is never read.
src/utils/format.ts(34,7): warning TS6133: 'temp' is declared but its value is never read.
src/hooks/useAuth.ts(89,15): error TS2532: Object is possibly 'undefined'.
src/hooks/useAuth.ts(91,15): error TS2532: Object is possibly 'undefined'.
src/pages/Dashboard.tsx(156,22): error TS2339: Property 'data' does not exist on type 'never'.
Found 6 errors, 2 warnings.
""",

    'grep -r token src/': "\n".join(
        [f"src/auth/middleware.py:42:    token = request.headers.get('Authorization')"]
        + [f"src/auth/utils.py:{i}:    # token handling logic" for i in range(10, 60)]
        + [f"tests/test_auth.py:{i}:    assert token is not None" for i in range(15, 45)]
        + [f"docs/api.md:{i}:Authorization: Bearer <token>" for i in range(5, 20)]
    ),

    'ls -la src/': "\n".join(
        ['total 48']
        + [f'-rw-r--r--  1 dev dev  {800+i*120:5d} Mar 31 00:00 module_{i:02d}.py' for i in range(30)]
        + ['drwxr-xr-x  2 dev dev   4096 Mar 31 00:00 __pycache__']
        + [f'-rw-r--r--  1 dev dev    {i*40:4d} Mar 31 00:00 module_{i:02d}.pyc' for i in range(30)]
    ),

    'find . -name "*.py"': "\n".join(
        [f'./src/module_{i:02d}.py' for i in range(40)]
        + [f'./__pycache__/module_{i:02d}.cpython-313.pyc' for i in range(40)]
        + ['./node_modules/some-pkg/index.py'] * 20
        + [f'./tests/test_module_{i:02d}.py' for i in range(20)]
    ),

    'pip install -e .': """\
Obtaining file:///workspace/myproject
  Installing build dependencies ... done
Collecting fastapi>=0.110
  Downloading fastapi-0.115.0-py3-none-any.whl (94 kB)
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 94.9/94.9 kB 2.1 MB/s eta 0:00:00
Collecting httpx>=0.27
  Using cached httpx-0.27.2-py3-none-any.whl (76 kB)
Collecting litellm>=1.40
  Downloading litellm-1.52.0-py3-none-any.whl (6.4 MB)
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 6.4/6.4 MB 8.3 MB/s eta 0:00:00
Collecting uvicorn>=0.30
  Using cached uvicorn-0.32.0-py3-none-any.whl (63 kB)
Collecting anyio<5,>=3.5.0
  Using cached anyio-4.6.2.post1-py3-none-any.whl (90 kB)
Collecting starlette<0.42.0,>=0.40.0
  Downloading starlette-0.41.3-py3-none-any.whl (73 kB)
Collecting certifi
  Using cached certifi-2024.8.30-py3-none-any.whl (167 kB)
Building wheels for collected packages: myproject
  Building wheel for myproject (pyproject.toml) ... done
  Created wheel for myproject: filename=myproject-0.1.0-py3-none-any.whl
  Stored in directory: /root/.cache/pip/wheels/
Successfully installed anyio-4.6.2 certifi-2024.8.30 fastapi-0.115.0 httpx-0.27.2 litellm-1.52.0 myproject-0.1.0 starlette-0.41.3 uvicorn-0.32.0
WARNING: pip is configured with locations that require TLS/SSL, however the ssl module in Python is not available.
WARNING: pip version 24.0 is available. Run pip install --upgrade pip to update.
""",

    'docker logs api --tail 200': "\n".join(
        [f'[2026-03-31T{i//60:02d}:{i%60:02d}:00Z] INFO  GET /api/health 200 OK latency=2ms' for i in range(180)]
        + ['[2026-03-31T03:00:01Z] ERROR Connection refused: PostgreSQL at 127.0.0.1:5432',
           '[2026-03-31T03:00:02Z] ERROR Retry 1/3 failed: ECONNREFUSED',
           '[2026-03-31T03:00:04Z] ERROR Retry 2/3 failed: ECONNREFUSED',
           '[2026-03-31T03:00:08Z] FATAL Max retries exceeded, shutting down server']
    ),

    'cat src/auth/middleware.py': """\
# Authentication middleware module
# This file handles JWT token validation and user authentication
# Last modified: 2024-01-15
# Author: Team Auth

import jwt  # PyJWT library for token handling
import logging  # Standard logging
from datetime import datetime, timezone  # Date utilities
from functools import wraps  # For decorator support
from flask import request, jsonify, current_app  # Flask components
from models import User, Session  # Database models

# Set up module logger
logger = logging.getLogger(__name__)

# Token expiry constants
ACCESS_TOKEN_EXPIRY = 3600      # 1 hour in seconds
REFRESH_TOKEN_EXPIRY = 604800   # 7 days in seconds

def create_token(user_id: int, expires_in: int = ACCESS_TOKEN_EXPIRY) -> str:
    # Build JWT payload with standard claims
    payload = {
        'user_id': user_id,
        'iat': datetime.now(timezone.utc),
        'exp': datetime.now(timezone.utc).timestamp() + expires_in,
    }
    return jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')

def require_auth(f):
    # Decorator that enforces authentication on routes
    @wraps(f)
    def decorated(*args, **kwargs):
        # Extract token from Authorization header
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token:
            return jsonify({'error': 'Missing token'}), 401
        try:
            # Decode and validate the token
            payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
            user = User.query.get(payload['user_id'])
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token expired'}), 401
        return f(*args, **kwargs)
    return decorated
""",
}

# Pricing per 1M input tokens (as of 2026)
PRICING = {
    'claude-sonnet-4-6':  3.00,
    'claude-haiku-4-5':   0.80,
    'gpt-4o-mini':        0.15,
    'gpt-5-nano':         0.05,   # $0.05/1M input, released Aug 2025
    'gpt-5.4-nano':       0.20,   # $0.20/1M input, released Mar 2026
}


def bar(pct: float, width: int = 20) -> str:
    filled = int(pct / 100 * width)
    return '█' * filled + '░' * (width - filled)


def run() -> list[tuple]:
    rows = []
    for command, raw_output in SAMPLES.items():
        before = count_tokens(raw_output)
        processed = preprocess(raw_output)
        handler = get_handler(command)
        after_text = handler.handle(command, processed) if handler else processed
        after = count_tokens(after_text)
        saved = before - after
        pct = (saved / before * 100) if before > 0 else 0.0
        rows.append((command, before, after, saved, pct, handler is not None))
    return rows


def print_table(rows: list[tuple]) -> None:
    total_before = sum(r[1] for r in rows)
    total_after = sum(r[2] for r in rows)
    total_saved = total_before - total_after
    total_pct = (total_saved / total_before * 100) if total_before > 0 else 0.0

    col_w = 32
    print(f"\n{'Command':<{col_w}} {'Before':>8} {'After':>8} {'Saved':>8} {'Saving':>9}  {'Reduction'}")
    print('-' * (col_w + 56))
    for command, before, after, saved, pct, has_handler in rows:
        label = '✓' if has_handler else '○'
        print(f"{command:<{col_w}} {before:>8,} {after:>8,} {saved:>8,} {pct:>8.1f}%  {bar(pct)} {label}")
    print('-' * (col_w + 56))
    print(f"{'TOTAL':<{col_w}} {total_before:>8,} {total_after:>8,} {total_saved:>8,} {total_pct:>8.1f}%  {bar(total_pct)}")
    print()
    print('✓ = command-specific handler   ○ = lossless preprocessing only')
    print()

    print(f"{'Model':<22} {'$/1M tokens':>12} {'Cost before':>12} {'Cost after':>12} {'Saving':>10}")
    print('-' * 72)
    for model, price in PRICING.items():
        cb = total_before / 1_000_000 * price
        ca = total_after / 1_000_000 * price
        print(f"{model:<22} ${price:>10.2f} ${cb:>11.4f} ${ca:>11.4f} ${cb-ca:>9.4f}")
    print()


def write_report(rows: list[tuple], output_path: str = 'benchmarks/cost/report.md') -> None:
    total_before = sum(r[1] for r in rows)
    total_after = sum(r[2] for r in rows)
    total_saved = total_before - total_after
    total_pct = (total_saved / total_before * 100) if total_before > 0 else 0.0

    lines = [
        '# AgentProxy — Cost Saving Benchmark',
        '',
        f'*Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}*',
        '',
        '## Summary',
        '',
        f'- **Token reduction: {total_pct:.1f}%** across a typical coding agent session',
        f'- Tokens before: {total_before:,}',
        f'- Tokens after:  {total_after:,}',
        f'- Tokens saved:  {total_saved:,}',
        '',
        '## Per-command breakdown',
        '',
        '| Command | Before | After | Saved | Reduction |',
        '|---|---:|---:|---:|---:|',
    ]

    for command, before, after, saved, pct, has_handler in rows:
        tag = '' if has_handler else ' ○'
        lines.append(f'| `{command}`{tag} | {before:,} | {after:,} | {saved:,} | **{pct:.1f}%** |')

    lines += [
        f'| **TOTAL** | **{total_before:,}** | **{total_after:,}** | **{total_saved:,}** | **{total_pct:.1f}%** |',
        '',
        '○ = lossless preprocessing only (ANSI strip, dedup, blank line collapse)',
        '',
        '## Cost savings per session',
        '',
        '| Model | $/1M tokens | Before | After | Saved |',
        '|---|---:|---:|---:|---:|',
    ]

    for model, price in PRICING.items():
        cb = total_before / 1_000_000 * price
        ca = total_after / 1_000_000 * price
        lines.append(f'| {model} | ${price:.2f} | ${cb:.4f} | ${ca:.4f} | **${cb-ca:.4f}** |')

    lines += [
        '',
        '## Methodology',
        '',
        'Each sample represents realistic tool output from a coding agent session:',
        '',
        '- **git diff**: large hunk (80 lines) triggering truncation at 50 lines per hunk',
        '- **git status**: branch, staged/modified/untracked file listing',
        '- **pytest**: 847 tests, 200 passing test lines, 2 failures with tracebacks',
        '- **tsc**: TypeScript errors and warnings',
        '- **grep**: multi-file search results across 4 files',
        '- **cat**: source file with inline comments',
        '',
        'Token counting uses `tiktoken` with `cl100k_base` encoding.',
    ]

    Path(output_path).write_text('\n'.join(lines) + '\n')
    print(f'Report written to {output_path}')


if __name__ == '__main__':
    rows = run()
    print_table(rows)
    write_report(rows)
