"""
Comprehensive handler tests.

Each test verifies:
  1. The handler fires (can_handle returns True for expected commands)
  2. The handler does NOT fire for unrelated commands
  3. The output contains the expected signal lines
  4. The output does NOT contain known noise lines
  5. Fallback: handler returns original output on empty/unrecognisable input
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentproxy.handlers.git import GitHandler
from agentproxy.handlers.test import TestHandler
from agentproxy.handlers.build import BuildHandler
from agentproxy.handlers.grep import GrepHandler
from agentproxy.handlers.files import FilesHandler
from agentproxy.handlers.filesystem import LsHandler, FindHandler
from agentproxy.handlers.package import PipHandler, NpmHandler, DockerHandler, KubectlHandler
from agentproxy.handlers.registry import get_handler
from agentproxy.core.pipeline import preprocess
from agentproxy.proxy.compressor import compress_messages


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def compress(command: str, output: str) -> str:
    handler = get_handler(command)
    processed = preprocess(output)
    return handler.handle(command, processed) if handler else processed


# ---------------------------------------------------------------------------
# git diff
# ---------------------------------------------------------------------------

GIT_DIFF_SHORT = """\
diff --git a/src/auth.py b/src/auth.py
index abc1234..def5678 100644
--- a/src/auth.py
+++ b/src/auth.py
@@ -10,6 +10,7 @@ import hashlib
 def verify(token):
-    return token == SECRET
+    if not token:
+        return False
+    return hmac.compare_digest(token, SECRET)
"""

GIT_DIFF_LONG = ("diff --git a/big.py b/big.py\nindex aaa..bbb 100644\n"
                 "--- a/big.py\n+++ b/big.py\n@@ -1,80 +1,80 @@\n"
                 + "\n".join(f" line {i}" for i in range(100)))


class TestGitDiff:
    def test_can_handle(self):
        h = GitHandler()
        assert h.can_handle("git diff HEAD")
        assert h.can_handle("git diff --staged")
        assert h.can_handle("git show abc123")

    def test_cannot_handle_other(self):
        h = GitHandler()
        assert not h.can_handle("pytest")
        assert not h.can_handle("grep -r foo src/")

    def test_short_diff_unchanged(self):
        result = compress("git diff HEAD", GIT_DIFF_SHORT)
        assert "+    return hmac.compare_digest(token, SECRET)" in result

    def test_long_diff_truncated(self):
        result = compress("git diff HEAD", GIT_DIFF_LONG)
        assert "omitted" in result
        lines = result.splitlines()
        hunk_lines = [l for l in lines if l.startswith(" line ") or l.startswith("+line") or l.startswith("-line")]
        assert len(hunk_lines) <= 50

    def test_diff_preserves_file_headers(self):
        result = compress("git diff HEAD", GIT_DIFF_LONG)
        assert "diff --git" in result
        assert "@@" in result

    def test_empty_diff_passthrough(self):
        result = compress("git diff HEAD", "")
        assert result == ""


# ---------------------------------------------------------------------------
# git status
# ---------------------------------------------------------------------------

GIT_STATUS = """\
On branch feature/auth
Your branch is ahead of 'origin/feature/auth' by 2 commits.
  (use "git push" to publish your local commits)

Changes to be committed:
  (use "git restore --staged <file>..." to unstage)
	modified:   src/auth.py
	new file:   src/tokens.py

Changes not staged for commit:
  (use "git restore <file>..." to discard changes in working directory)
	modified:   README.md
	modified:   tests/test_auth.py

Untracked files:
  (use "git add <file>..." to include in what will be committed)
	scratch.py
	notes.txt
"""


class TestGitStatus:
    def test_contains_branch(self):
        result = compress("git status", GIT_STATUS)
        assert "feature/auth" in result

    def test_contains_staged_files(self):
        result = compress("git status", GIT_STATUS)
        assert "src/auth.py" in result or "modified: src/auth.py" in result

    def test_strips_hints(self):
        result = compress("git status", GIT_STATUS)
        assert "use \"git restore" not in result
        assert "use \"git push" not in result

    def test_clean_tree(self):
        result = compress("git status", "On branch main\nnothing to commit, working tree clean\n")
        assert "Clean" in result or "main" in result


# ---------------------------------------------------------------------------
# git log
# ---------------------------------------------------------------------------

GIT_LOG = """\
commit a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2
Author: Alice <alice@example.com>
Date:   Mon Mar 31 10:00:00 2025 +0000

    Fix authentication bug

commit b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3
Author: Bob <bob@example.com>
Date:   Sun Mar 30 09:00:00 2025 +0000

    Add token refresh logic
"""


class TestGitLog:
    def test_one_line_per_commit(self):
        result = compress("git log", GIT_LOG)
        lines = [l for l in result.splitlines() if l.strip()]
        assert len(lines) == 2

    def test_contains_sha_and_subject(self):
        result = compress("git log", GIT_LOG)
        assert "a1b2c3d" in result
        assert "Fix authentication bug" in result

    def test_strips_author_date_lines(self):
        result = compress("git log", GIT_LOG)
        assert "Author:" not in result
        assert "Date:" not in result


# ---------------------------------------------------------------------------
# pytest
# ---------------------------------------------------------------------------

PYTEST_ALL_PASS = """\
============================= test session starts ==============================
collected 5 items

tests/test_foo.py .....                                                  [100%]

============================== 5 passed in 0.12s ==============================
"""

PYTEST_WITH_FAILURES = """\
============================= test session starts ==============================
platform linux -- Python 3.11.4, pytest-7.4.0
collected 847 items

tests/test_models.py ...................................................... [ 6%]
tests/test_api.py ..................................................... [ 13%]
tests/test_auth.py ..................................................... [ 21%]
tests/test_utils.py .................................................... [ 29%]
tests/test_db.py ...................................................... [ 37%]
tests/test_cache.py .................................................... [ 45%]
tests/test_search.py ................................................... [ 53%]
tests/test_billing.py .................................................. [ 60%]
tests/test_webhooks.py ................................................. [ 68%]
tests/test_jobs.py ..................................................... [ 76%]
tests/test_admin.py .................................................... [ 84%]
tests/test_e2e.py .F.................................................... [ 92%]
tests/test_regression.py ....F.......................................... [100%]

=================================== FAILURES ===================================
_________________ test_checkout_flow_with_discount _________________

    def test_checkout_flow_with_discount():
        cart = Cart()
        cart.add_item("widget", price=9.99, qty=3)
        cart.apply_discount("SAVE10")
>       assert cart.total() == 26.97
E       AssertionError: assert 29.97 == 26.97

tests/test_e2e.py:88: AssertionError
_________________ test_price_rounding _________________

    def test_price_rounding():
>       assert round(1.005, 2) == 1.01
E       AssertionError: assert 1.0 == 1.01

tests/test_regression.py:14: AssertionError
============================== 2 failed, 845 passed in 12.34s ==============================
"""

PYTEST_WITH_ERRORS = """\
============================= test session starts ==============================
collected 3 items

=================================== ERRORS =====================================
_______________ ERROR collecting tests/test_broken.py _______________
ImportError: cannot import name 'missing_func' from 'mymodule'
tests/test_broken.py:1: ImportError
============================== 1 error in 0.05s ==============================
"""


class TestPytest:
    def test_can_handle(self):
        h = TestHandler()
        assert h.can_handle("pytest")
        assert h.can_handle("pytest tests/")
        assert h.can_handle("python -m pytest")
        assert h.can_handle("python3 -m pytest -x")

    def test_failures_preserved(self):
        result = compress("pytest", PYTEST_WITH_FAILURES)
        assert "test_checkout_flow_with_discount" in result
        assert "assert 29.97 == 26.97" in result
        assert "test_price_rounding" in result
        assert "assert 1.0 == 1.01" in result

    def test_passing_dots_stripped(self):
        result = compress("pytest", PYTEST_WITH_FAILURES)
        # No lines of dots
        assert not any(set(l.strip()) <= set('. ') and len(l.strip()) > 5
                       for l in result.splitlines())

    def test_summary_line_preserved(self):
        result = compress("pytest", PYTEST_WITH_FAILURES)
        assert "2 failed, 845 passed" in result

    def test_session_header_stripped(self):
        result = compress("pytest", PYTEST_WITH_FAILURES)
        assert "test session starts" not in result
        assert "platform linux" not in result
        assert "collected 847 items" not in result

    def test_all_pass_returns_summary(self):
        result = compress("pytest", PYTEST_ALL_PASS)
        assert "5 passed" in result

    def test_errors_preserved(self):
        result = compress("pytest", PYTEST_WITH_ERRORS)
        assert "ImportError" in result or "ERROR" in result

    def test_empty_passthrough(self):
        result = compress("pytest", "")
        assert result == ""

    def test_reduction_significant(self):
        result = compress("pytest", PYTEST_WITH_FAILURES)
        assert len(result) < len(PYTEST_WITH_FAILURES) * 0.5


# ---------------------------------------------------------------------------
# tsc
# ---------------------------------------------------------------------------

TSC_WITH_ERRORS = """\
src/auth.ts(42,5): error TS2345: Argument of type 'string' is not assignable to parameter of type 'number'.
src/auth.ts(67,12): warning TS6133: 'token' is declared but its value is never read.
src/models.ts(15,3): error TS2304: Cannot find name 'User'.
Found 2 errors and 1 warning.
"""

TSC_WARNINGS_ONLY = """\
src/old.ts(10,1): warning TS6133: 'legacyFn' is declared but its value is never read.
src/old.ts(20,1): warning TS6133: 'unusedVar' is declared but its value is never read.
Found 0 errors and 2 warnings.
"""


class TestTsc:
    def test_can_handle(self):
        h = BuildHandler()
        assert h.can_handle("tsc")
        assert h.can_handle("tsc --noEmit")
        assert h.can_handle("npx tsc")

    def test_errors_kept(self):
        result = compress("tsc", TSC_WITH_ERRORS)
        assert "TS2345" in result
        assert "TS2304" in result

    def test_warnings_suppressed_when_errors_exist(self):
        result = compress("tsc", TSC_WITH_ERRORS)
        assert "TS6133" not in result

    def test_warnings_kept_when_no_errors(self):
        result = compress("tsc", TSC_WARNINGS_ONLY)
        assert "TS6133" in result

    def test_summary_kept(self):
        result = compress("tsc", TSC_WITH_ERRORS)
        assert "Found" in result or "error" in result.lower()


# ---------------------------------------------------------------------------
# eslint
# ---------------------------------------------------------------------------

ESLINT_OUTPUT = """\
/src/auth.js
  42:5  error    'token' is not defined                  no-undef
  67:12 warning  Unexpected console statement             no-console

/src/models.js
  15:3  error    Expected '===' and instead saw '=='     eqeqeq

✖ 3 problems (2 errors, 1 warning)
"""


class TestEslint:
    def test_can_handle(self):
        h = BuildHandler()
        assert h.can_handle("eslint src/")
        assert h.can_handle("npx eslint .")

    def test_errors_kept(self):
        result = compress("eslint src/", ESLINT_OUTPUT)
        assert "no-undef" in result
        assert "eqeqeq" in result

    def test_warnings_suppressed_when_errors(self):
        result = compress("eslint src/", ESLINT_OUTPUT)
        assert "no-console" not in result

    def test_summary_kept(self):
        result = compress("eslint src/", ESLINT_OUTPUT)
        assert "problem" in result


# ---------------------------------------------------------------------------
# grep
# ---------------------------------------------------------------------------

GREP_OUTPUT = "\n".join(
    f"src/module_{i}/file.py:{j * 10}:    result = authenticate(user, token)"
    for i in range(5) for j in range(15)
)  # 75 lines across 5 files, 15 matches each

GREP_BARE = "\n".join(f"    result = authenticate(user, token)" for _ in range(30))


class TestGrep:
    def test_can_handle(self):
        h = GrepHandler()
        assert h.can_handle("grep -r authenticate src/")
        assert h.can_handle("rg authenticate")
        assert h.can_handle("grep foo file.txt")

    def test_groups_by_file(self):
        result = compress("grep -r authenticate src/", GREP_OUTPUT)
        assert "src/module_0/file.py" in result
        assert "matches" in result.lower() or "match" in result.lower()

    def test_caps_per_file(self):
        result = compress("grep -r authenticate src/", GREP_OUTPUT)
        # Each file should show at most 10 + header line
        for i in range(5):
            fname = f"src/module_{i}/file.py"
            section_lines = [l for l in result.splitlines() if fname in l]
            # At most 10 match lines + 1 header + 1 omitted notice
            assert len(section_lines) <= 12

    def test_bare_output_capped(self):
        result = compress("grep foo file.txt", GREP_BARE)
        assert len(result.splitlines()) <= 205  # 200 cap + some overhead

    def test_significant_reduction(self):
        result = compress("grep -r authenticate src/", GREP_OUTPUT)
        assert len(result) < len(GREP_OUTPUT)


# ---------------------------------------------------------------------------
# cat
# ---------------------------------------------------------------------------

CAT_PYTHON = """\
# This is a module-level comment
# Author: Alice

import os
import sys

# Helper function
def authenticate(user, token):
    # Check token
    return hmac.compare_digest(token, get_secret(user))

def get_secret(user):
    # Fetch from DB
    return db.get(user)
"""

CAT_LONG = "\n".join(f"line {i}" for i in range(600))


class TestCat:
    def test_can_handle(self):
        h = FilesHandler()
        assert h.can_handle("cat src/auth.py")
        assert h.can_handle("cat README.md")

    def test_strips_inline_comments_python(self):
        result = compress("cat auth.py", CAT_PYTHON)
        assert "# This is a module-level comment" not in result
        assert "# Check token" not in result
        assert "def authenticate" in result

    def test_preserves_shebang(self):
        result = compress("cat script.sh", "#!/bin/bash\n# comment\necho hello\n")
        assert "#!/bin/bash" in result
        assert "echo hello" in result

    def test_caps_at_500_lines(self):
        result = compress("cat big.py", CAT_LONG)
        assert "omitted" in result
        assert len(result.splitlines()) <= 502  # 500 + omit notice

    def test_no_extension_no_comment_strip(self):
        output = "# keep this\nsome content\n"
        result = compress("cat Makefile", output)
        assert "# keep this" in result  # Makefile not in comment patterns


# ---------------------------------------------------------------------------
# ls
# ---------------------------------------------------------------------------

LS_OUTPUT = """\
total 64
drwxr-xr-x  8 alice staff   256 Mar 31 10:00 .
drwxr-xr-x 12 alice staff   384 Mar 31 09:00 ..
drwxr-xr-x  5 alice staff   160 Mar 31 10:00 .git
-rw-r--r--  1 alice staff  1024 Mar 31 10:00 .env
drwxr-xr-x  3 alice staff    96 Mar 31 10:00 __pycache__
drwxr-xr-x  8 alice staff   256 Mar 31 10:00 node_modules
-rw-r--r--  1 alice staff  2048 Mar 31 10:00 README.md
-rw-r--r--  1 alice staff  4096 Mar 31 10:00 auth.py
drwxr-xr-x  4 alice staff   128 Mar 31 10:00 src
"""


class TestLs:
    def test_can_handle(self):
        h = LsHandler()
        assert h.can_handle("ls -la")
        assert h.can_handle("ls src/")
        assert not h.can_handle("eslint src/")

    def test_strips_noise_dirs(self):
        result = compress("ls -la", LS_OUTPUT)
        assert "__pycache__" not in result
        assert "node_modules" not in result
        assert ".git" not in result

    def test_strips_dot_files(self):
        result = compress("ls -la", LS_OUTPUT)
        assert ".env" not in result

    def test_keeps_real_files(self):
        result = compress("ls -la", LS_OUTPUT)
        assert "README.md" in result
        assert "auth.py" in result
        assert "src" in result

    def test_strips_total_line(self):
        result = compress("ls -la", LS_OUTPUT)
        assert not any(l.strip().startswith("total ") for l in result.splitlines())

    def test_caps_entries(self):
        many = "\n".join(f"-rw-r--r-- 1 a b 100 Jan 1 file_{i}.py" for i in range(100))
        result = compress("ls", many)
        assert "omitted" in result


# ---------------------------------------------------------------------------
# find
# ---------------------------------------------------------------------------

FIND_OUTPUT = """\
.
./src
./src/auth.py
./src/models.py
./__pycache__
./__pycache__/auth.cpython-313.pyc
./__pycache__/models.cpython-313.pyc
./node_modules
./node_modules/lodash
./node_modules/lodash/index.js
./.git
./.git/config
./README.md
"""


class TestFind:
    def test_can_handle(self):
        h = FindHandler()
        assert h.can_handle("find . -name '*.py'")
        assert h.can_handle("find src/")
        assert not h.can_handle("grep foo src/")

    def test_strips_pycache(self):
        result = compress("find . -name '*.py'", FIND_OUTPUT)
        assert "__pycache__" not in result

    def test_strips_node_modules(self):
        result = compress("find . -name '*.py'", FIND_OUTPUT)
        assert "node_modules" not in result

    def test_strips_git(self):
        result = compress("find . -name '*.py'", FIND_OUTPUT)
        assert ".git" not in result

    def test_keeps_real_files(self):
        result = compress("find . -name '*.py'", FIND_OUTPUT)
        assert "src/auth.py" in result
        assert "README.md" in result

    def test_caps_lines(self):
        many = "\n".join(f"./src/file_{i}.py" for i in range(100))
        result = compress("find . -name '*.py'", many)
        assert "omitted" in result


# ---------------------------------------------------------------------------
# pip install
# ---------------------------------------------------------------------------

PIP_OUTPUT = """\
Collecting requests==2.31.0
  Downloading requests-2.31.0-py3-none-any.whl (62 kB)
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 62.6/62.6 kB 1.2 MB/s eta 0:00:00
Collecting urllib3<3,>=1.21.1
  Using cached urllib3-2.0.7-py3-none-any.whl (124 kB)
Installing collected packages: urllib3, certifi, charset-normalizer, idna, requests
Successfully installed certifi-2024.2.2 charset-normalizer-3.3.2 idna-3.6 requests-2.31.0 urllib3-2.0.7
"""

PIP_ERROR = """\
Collecting nonexistent-package==99.0.0
  ERROR: Could not find a version that satisfies the requirement nonexistent-package==99.0.0
ERROR: No matching distribution found for nonexistent-package==99.0.0
"""


class TestPip:
    def test_can_handle(self):
        h = PipHandler()
        assert h.can_handle("pip install requests")
        assert h.can_handle("pip3 install -r requirements.txt")

    def test_strips_download_noise(self):
        result = compress("pip install requests", PIP_OUTPUT)
        assert "Downloading" not in result
        assert "━━━" not in result
        assert "Using cached" not in result

    def test_keeps_success_line(self):
        result = compress("pip install requests", PIP_OUTPUT)
        assert "Successfully installed" in result

    def test_keeps_errors(self):
        result = compress("pip install nonexistent-package", PIP_ERROR)
        assert "ERROR" in result
        assert "No matching distribution" in result


# ---------------------------------------------------------------------------
# docker logs
# ---------------------------------------------------------------------------

DOCKER_LOGS_SHORT = "\n".join(
    f"2025-03-31T10:00:{i:02d}Z INFO  Request processed" for i in range(30)
)

DOCKER_LOGS_LONG = (
    "\n".join(f"2025-03-31T10:00:{i:02d}Z INFO  Request processed" for i in range(180))
    + "\n2025-03-31T10:03:00Z ERROR Failed to connect to database"
    + "\n2025-03-31T10:03:01Z FATAL Service is shutting down"
)


class TestDocker:
    def test_can_handle(self):
        h = DockerHandler()
        assert h.can_handle("docker logs mycontainer")
        assert h.can_handle("docker ps")
        assert not h.can_handle("kubectl logs pod")

    def test_short_logs_unchanged(self):
        result = compress("docker logs mycontainer", DOCKER_LOGS_SHORT)
        assert "INFO  Request processed" in result

    def test_long_logs_extracts_errors(self):
        result = compress("docker logs mycontainer", DOCKER_LOGS_LONG)
        assert "ERROR" in result
        assert "FATAL" in result
        assert "Failed to connect" in result

    def test_long_logs_includes_tail(self):
        result = compress("docker logs mycontainer", DOCKER_LOGS_LONG)
        assert "Last" in result or "10:03:01" in result

    def test_long_logs_compressed(self):
        result = compress("docker logs mycontainer", DOCKER_LOGS_LONG)
        assert len(result) < len(DOCKER_LOGS_LONG)


# ---------------------------------------------------------------------------
# registry: get_handler routing
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_git_routes(self):
        assert get_handler("git diff HEAD") is not None
        assert get_handler("git status") is not None
        assert get_handler("git log --oneline") is not None

    def test_pytest_routes(self):
        assert get_handler("pytest") is not None
        assert get_handler("python3 -m pytest tests/") is not None

    def test_tsc_routes(self):
        assert get_handler("tsc --noEmit") is not None

    def test_grep_routes(self):
        assert get_handler("grep -r foo src/") is not None
        assert get_handler("rg pattern") is not None

    def test_unknown_returns_none(self):
        assert get_handler("terraform plan") is None
        assert get_handler("make build") is None
        assert get_handler("") is None

    def test_no_false_positives(self):
        # These should NOT match
        assert get_handler("echo hello") is None
        assert get_handler("curl https://example.com") is None
        assert get_handler("cat README.md") is not None  # cat DOES have a handler


# ---------------------------------------------------------------------------
# pipeline: preprocess
# ---------------------------------------------------------------------------

class TestPreprocess:
    def test_strips_ansi(self):
        result = preprocess("\x1b[32mGreen text\x1b[0m")
        assert "\x1b" not in result
        assert "Green text" in result

    def test_deduplicates_consecutive(self):
        output = "line A\nline A\nline A\nline B\n"
        result = preprocess(output)
        assert result.count("line A") == 1
        assert "repeated" in result
        assert "line B" in result

    def test_collapses_blank_lines(self):
        output = "a\n\n\n\n\nb\n"
        result = preprocess(output)
        assert result.count("\n\n\n") == 0
        assert "a" in result and "b" in result

    def test_idempotent(self):
        output = "hello\nworld\n"
        assert preprocess(preprocess(output)) == preprocess(output)


# ---------------------------------------------------------------------------
# compressor: compress_messages end-to-end
# ---------------------------------------------------------------------------

class TestCompressMessages:
    def _make_messages(self, command: str, output: str) -> list[dict]:
        return [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Running command."},
                    {"type": "tool_use", "id": "t001", "name": "Bash",
                     "input": {"command": command}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "t001", "content": output},
                ],
            },
        ]

    def test_pytest_compressed_end_to_end(self):
        msgs = self._make_messages("pytest", PYTEST_WITH_FAILURES)
        result = compress_messages(msgs)
        tool_result = result[1]["content"][0]["content"]
        assert "test session starts" not in tool_result
        assert "845 passed" in tool_result
        assert "test_checkout_flow_with_discount" in tool_result

    def test_unknown_command_passthrough(self):
        output = "some terraform output\n" * 10
        msgs = self._make_messages("terraform plan", output)
        result = compress_messages(msgs)
        tool_result = result[1]["content"][0]["content"]
        assert "terraform output" in tool_result

    def test_non_bash_tool_unchanged(self):
        msgs = [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "t001", "name": "str_replace_editor",
                     "input": {"path": "foo.py", "old_str": "x", "new_str": "y"}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "t001",
                     "content": "File updated successfully"},
                ],
            },
        ]
        result = compress_messages(msgs)
        assert result[1]["content"][0]["content"] == "File updated successfully"

    def test_multi_turn_all_compressed(self):
        msgs = []
        for i in range(3):
            tool_id = f"t{i:03d}"
            msgs.append({
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": tool_id, "name": "Bash",
                     "input": {"command": "pytest"}},
                ],
            })
            msgs.append({
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": tool_id,
                     "content": PYTEST_WITH_FAILURES},
                ],
            })
        result = compress_messages(msgs)
        for i in range(3):
            tool_result = result[i * 2 + 1]["content"][0]["content"]
            assert "test session starts" not in tool_result
            assert "845 passed" in tool_result

    def test_string_content_compressed(self):
        msgs = self._make_messages("git diff HEAD", GIT_DIFF_LONG)
        result = compress_messages(msgs)
        tool_result = result[1]["content"][0]["content"]
        assert len(tool_result) < len(GIT_DIFF_LONG)

    def test_list_content_compressed(self):
        msgs = [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "t001", "name": "Bash",
                     "input": {"command": "pytest"}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t001",
                        "content": [{"type": "text", "text": PYTEST_WITH_FAILURES}],
                    },
                ],
            },
        ]
        result = compress_messages(msgs)
        tool_result = result[1]["content"][0]["content"][0]["text"]
        assert "test session starts" not in tool_result
        assert "845 passed" in tool_result

    def test_messages_without_tool_results_unchanged(self):
        msgs = [
            {"role": "user", "content": "Fix the bug"},
            {"role": "assistant", "content": "Sure, let me look at it."},
        ]
        result = compress_messages(msgs)
        assert result == msgs
