# AgentProxy

Your coding agent solves more problems and costs less to run.

On [SWE-bench](https://github.com/princeton-nlp/SWE-bench): **+40% problems solved, −25% token cost** — with no changes to your agent.

```bash
pip install agentproxy
agentproxy run claude   # or: aider, any OpenAI-compatible agent
```

That's it. AgentProxy starts a local proxy, sets `ANTHROPIC_BASE_URL` automatically, and launches your agent through it.

---

## The problem

LLM agents pay tokens for everything they read. A single `pytest` run can produce 3,000 tokens. Most of it is dots.

```
Agent → pytest → 3,000 tokens → LLM reads all of it
```

AgentProxy intercepts at the API level and compresses tool results before they reach the model:

```
Agent → pytest → 3,000 tokens → AgentProxy (71 tokens) → LLM
```

**Example — `pytest` with 847 tests, 2 failures:**

<table>
<tr><th>Before (2,885 tokens)</th><th>After (71 tokens, −97.5%)</th></tr>
<tr><td>

```
============================= test session starts ==============================
platform linux -- Python 3.11.4, pytest-7.4.0
collected 847 items

tests/test_models.py .................... [ 6%]
tests/test_api.py .................... [ 13%]
tests/test_auth.py .................... [ 21%]
... 800+ more passing lines ...
tests/test_e2e.py .F................. [ 92%]
tests/test_regression.py ....F....... [100%]

=================================== FAILURES ===================================
_____________ test_checkout_flow_with_discount _____________

    def test_checkout_flow_with_discount():
        cart = Cart()
        cart.add_item("widget", price=9.99, qty=3)
        cart.apply_discount("SAVE10")
>       assert cart.total() == 26.97
E       AssertionError: assert 29.97 == 26.97

tests/test_e2e.py:88: AssertionError
_____________ test_price_rounding _____________

    def test_price_rounding():
>       assert round(1.005, 2) == 1.01
E       AssertionError: assert 1.0 == 1.01

tests/test_regression.py:14: AssertionError
====== 2 failed, 845 passed in 12.34s ======
```

</td><td>

```
FAILED tests/test_e2e.py::test_checkout_flow_with_discount
  AssertionError: assert 29.97 == 26.97
FAILED tests/test_regression.py::test_price_rounding
  AssertionError: assert 1.0 == 1.01
====== 2 failed, 845 passed in 12.34s ======
```

</td></tr>
</table>

The model gets exactly what it needs: failing test names, assertion values, summary line. 845 passing test dots — gone.

---

## Why it works better than shell-level tools

Tools like [rtk](https://github.com/rtk-ai/rtk) intercept at the shell — they compress a result once, when the command runs. AgentProxy intercepts at the **LLM API level**, where it sees the full conversation history on every request.

A tool result from turn 3 gets re-sent on turns 4, 5, 6… AgentProxy compresses it every time. rtk compresses it once.

For a 20-turn agent session, a large tool result from turn 3 is re-sent 17 times. AgentProxy reduces it 17 times. This is why compression compounds over long sessions and why weaker models (more turns, more context overflow) benefit most.

**Latency overhead: ~0.2ms.** The compression pipeline runs in under half a millisecond for typical payloads. It is not a meaningful addition to a 500ms+ API call.

---

## Benchmarks

### Task completion — SWE-bench (30 instances, gpt-5-nano)

| Metric | Baseline | + AgentProxy | Change |
|---|---|---|---|
| Problems solved | 10/30 | **14/30** | **+4 (+40%)** |
| Prompt tokens | 4,936,165 | 3,708,953 | **−24.9%** |
| Completion tokens | 367,969 | 305,773 | −16.9% |

Compression helps most when the model is prone to context overflow — weaker models, longer sessions, harder tasks. With gpt-4o-mini (fewer turns, smaller outputs): 3.6% token reduction, patch rate roughly stable.

### Token reduction by command

| Command | Reduction |
|---|---|
| `find` (with `__pycache__`, `node_modules`) | **99.3%** |
| `pytest` (847 tests, 2 failures) | **97.5%** |
| `docker logs` (180 info + 4 errors) | **86.8%** |
| `pip install` | **80.9%** |
| `grep -r` (4 files) | **61.2%** |
| `git diff` (80-line hunk) | **42.3%** |
| `git status` | **41.8%** |
| **Overall (10 command types)** | **73.1%** |

### vs rtk (head-to-head on real shell outputs)

| | AgentProxy | rtk |
|---|---|---|
| Total token reduction | **83.8%** | 85.8% |
| `git diff` | **63.7%** | 20.8% |
| `pytest` (200 pass, 2 fail) | **98.8%** | 97.7% |
| `grep` (140+ matches) | 68.5% | **82.6%** |

Essentially tied on compression ratio. The key difference is the API-level interception: AgentProxy compresses the accumulated history on every call; rtk compresses at execution time only.

→ Full methodology: [`benchmarks/BENCHMARKS.md`](benchmarks/BENCHMARKS.md)

---

## Usage

**Run any agent through the proxy:**
```bash
agentproxy run claude          # Claude Code
agentproxy run aider           # Aider
agentproxy run -- my-agent --flag   # any agent
```

**Custom port:**
```bash
agentproxy run claude --port 9090
```

**Start the proxy standalone** (manage the agent separately):
```bash
agentproxy serve
ANTHROPIC_BASE_URL=http://localhost:8080 claude
```

**Test compression on any command:**
```bash
git diff   | agentproxy compress git diff
pytest     | agentproxy compress pytest
```

---

## Supported Commands

| Command | Strategy |
|---|---|
| `git diff` | stat block + truncated hunks (50 lines each) |
| `git status` | compact summary: branch, staged/modified/untracked counts |
| `git log` | one line per commit: sha, subject, date, author |
| `tsc` | errors only; warnings suppressed when errors exist |
| `cargo build/check/clippy` | errors only; warnings suppressed when errors exist |
| `eslint` | errors only + summary line |
| `ruff check` | errors only + summary line |
| `pytest` | failures + summary line |
| `jest / vitest` | failures + summary line |
| `cargo test` | failures + summary line |
| `cat <file>` | strip inline comments, cap at 500 lines |
| `grep / rg` | group by file, cap 10 matches per file, 20 files |
| `ls` | strip `__pycache__`, dot-files, noise extensions |
| `find` | filter `__pycache__`, `node_modules`, `.pyc` paths |
| `pip install` | keep `Successfully installed` + errors only |
| `npm/pnpm/yarn install` | keep errors + final summary |
| `docker logs` | error lines + last 20 lines |
| `kubectl logs` | error lines + last 20 lines |

---

## How It Works

Every request goes through two layers before being forwarded.

**Layer 1 — Universal pre-processing (always on, lossless)**

Applied to every tool result regardless of command: strip ANSI codes, collapse blank lines, deduplicate consecutive identical lines.

**Layer 2 — Command-specific handler**

The proxy walks the `messages` array to build a `tool_use_id → command` map, then looks up the originating command for each `tool_result` block. If a handler matches, it applies structured compression tuned to that tool's output format. If no handler matches, the output passes through after layer 1 only — a missing handler never silently drops information.

---

## Dashboard

Visit `http://localhost:8080/dashboard` while the proxy is running — live token savings, top compressed commands, and which unhandled commands are worth adding a handler for.

## Miss Tracking

```bash
agentproxy stats          # top unhandled commands by KB passed through
agentproxy stats --clear  # reset
```

Tells you exactly which handler to write next.

## ML Fallback (opt-in)

For commands with no handler, AgentProxy can call a cheap LLM to summarize the output:

```bash
AGENTPROXY_ML_FALLBACK=1 agentproxy serve
AGENTPROXY_ML_MODEL=gpt-4o-mini agentproxy serve  # default: gpt-5-nano
```

Results are cached in-process by content hash to avoid redundant calls.

---

## Adding a Handler

1. Create `agentproxy/handlers/mytool.py`:

```python
from ..core.base_handler import BaseHandler

class MyToolHandler(BaseHandler):
    def can_handle(self, command: str) -> bool:
        return command.strip().startswith('mytool')

    def handle(self, command: str, output: str) -> str:
        try:
            # your compression logic
            return compressed
        except Exception:
            return output  # always fall back to original
```

2. Register it in `agentproxy/handlers/registry.py`:

```python
from .mytool import MyToolHandler
_HANDLERS = [..., MyToolHandler()]
```

`handle` must never raise — return the original output on any error.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Your Agent (Claude Code, any OpenAI-compatible agent)  │
│  ANTHROPIC_BASE_URL=http://localhost:8080                │
└────────────────────────┬────────────────────────────────┘
                         │ POST /v1/messages
                         │ { messages: [..., tool_result: "...huge output..."] }
                         ▼
┌─────────────────────────────────────────────────────────┐
│                    AgentProxy :8080                      │
│                                                         │
│  For each request:                                      │
│  ├─ Walk messages → build tool_use_id → command map     │
│  ├─ For each tool_result: look up command, apply handler│
│  ├─ Layer 1 (always): ANSI strip, dedup, blank collapse │
│  ├─ Layer 2 (if matched): command-specific compression  │
│  └─ Unknown commands → pass through unchanged           │
└────────────────────────┬────────────────────────────────┘
                         │ POST /v1/messages (compressed)
                         ▼
┌─────────────────────────────────────────────────────────┐
│              api.anthropic.com / api.openai.com          │
└─────────────────────────────────────────────────────────┘
```

**No code changes to your agent.** No API keys managed by the proxy. Streaming responses pass through without buffering. Handlers are deterministic regex/parsing — no ML in the hot path.

---

## Roadmap

- [x] Benchmarks (cost benchmark, SWE-bench, rtk comparison)
- [x] More handlers: `ls`, `find`, `pip install`, `docker logs`, `kubectl`, `npm install`
- [x] Miss tracking — `agentproxy stats` surfaces top unhandled commands by bytes
- [x] Streaming response support — SSE chunks piped without buffering
- [x] Token usage dashboard — live view at `http://localhost:8080/dashboard`
- [x] ML-based fallback — `AGENTPROXY_ML_FALLBACK=1` for unhandled commands
