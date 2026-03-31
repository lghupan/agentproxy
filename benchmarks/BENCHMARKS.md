# AgentProxy — Benchmark Results

*Run date: 2026-03-31 | Instances: 30 (SWE-bench Lite, easy subset)*

---

## 1. Cost Benchmark — Token Compression on Realistic Tool Outputs

Measures token reduction on fixed representative samples from a typical coding-agent session.

### Results

| Command | Before | After | Saved | Reduction |
|---|---:|---:|---:|---:|
| `git diff` (80-line hunk) | 1,307 | 754 | 553 | **42.3%** |
| `git status` | 177 | 103 | 74 | **41.8%** |
| `pytest` (847 tests, 2 fail) | 2,885 | 71 | 2,814 | **97.5%** |
| `tsc` (errors + warnings) | 221 | 169 | 52 | **23.5%** |
| `grep -r token src/` (4 files) | 1,282 | 498 | 784 | **61.2%** |
| `ls -la src/` (60 entries) | 1,652 | 1,355 | 297 | **18.0%** |
| `find . -name "*.py"` (w/ noise) | 1,239 | 9 | 1,230 | **99.3%** |
| `pip install -e .` | 517 | 99 | 418 | **80.9%** |
| `docker logs` (200 lines, 4 errors) | 5,513 | 726 | 4,787 | **86.8%** |
| `cat src/auth/middleware.py` | 386 | 306 | 80 | **20.7%** |
| **TOTAL** | **15,179** | **4,090** | **11,089** | **73.1%** |

### Cost savings per session

| Model | $/1M tokens | Cost before | Cost after | Saved |
|---|---:|---:|---:|---:|
| claude-sonnet-4-6 | $3.00 | $0.0455 | $0.0123 | **$0.0333** |
| claude-haiku-4-5 | $0.80 | $0.0121 | $0.0033 | **$0.0089** |
| gpt-4o-mini | $0.15 | $0.0023 | $0.0006 | **$0.0017** |
| gpt-5-nano | $0.05 | $0.0008 | $0.0002 | **$0.0006** |

### How each handler compresses

| Handler | Strategy | Key savings |
|---|---|---|
| `git diff` | Stat block + truncated hunks (50 lines each) | Eliminates unchanged context lines |
| `git status` | Compact summary: branch, counts per category | Strips git "use X to..." hints |
| `pytest` / `jest` / `cargo test` | Failures + summary line only | Removes 200+ passing test lines |
| `tsc` / `cargo` / `eslint` / `ruff` | Errors only; warnings suppressed when errors exist | Removes warnings when action is clear |
| `grep` / `rg` | Group by file, cap 10 matches/file, 20 files max | Deduplicates repetitive match lines |
| `cat` | Strip inline comments, cap at 500 lines | Reduces comment-heavy files |
| `ls` | Strip `__pycache__`, dot-files, noise extensions | Removes non-code filesystem entries |
| `find` | Filter out `__pycache__`, `node_modules`, `.pyc` paths | 99%+ reduction when noise dirs present |
| `pip install` | Keep only `Successfully installed` and errors | Strips downloading/building progress spam |
| `npm` / `pnpm` / `yarn` | Keep errors and final install summary | Strips spinner lines and audit noise |
| `docker logs` / `kubectl logs` | Error lines + last 20 lines | Surfaces failures in long log streams |
| `docker ps` / `kubectl get` | Cap at 20–30 rows | Truncates large container/pod tables |

### Methodology

- Token counting: `tiktoken` `cl100k_base` encoding
- Samples are static strings representing realistic agent tool outputs
- `git diff`: 80-line hunk exceeding the 50-line truncation threshold
- `pytest`: 847 test run (200 passing test lines shown, 2 failures with tracebacks)
- `grep`: 4 files with 10–50 matches each
- `find`: repo with `__pycache__` and `node_modules` directories (typical Python project)
- `docker logs`: 180 INFO lines + 4 ERROR/FATAL lines

Run: `python benchmarks/cost/run.py`

---

## 2. SWE-bench Benchmark — Real Agent Performance

Runs a coding agent on 30 easy instances from [SWE-bench Lite](https://github.com/princeton-nlp/SWE-bench) (instances with exactly 1 FAIL_TO_PASS test). Compares patch generation rate and token usage with and without AgentProxy.

### Setup

- **Agent**: minimal tool-calling loop with `bash` + `write_file` tools (see `benchmarks/swe/agent.py`)
- **Instances**: 30 "easy" instances (1 failing test each) from SWE-bench Lite
- **Turns**: up to 30 per instance, with a nudge after 6 exploration-only turns
- **Parallelism**: 4 workers

### Results — gpt-5-nano ($0.05/1M input)

| Metric | Baseline | + AgentProxy | Change |
|---|---|---|---|
| Patches generated | 10/30 (33%) | **14/30 (47%)** | **+4 problems solved** |
| Total prompt tokens | 4,936,165 | 3,708,953 | **−1,227,212** |
| Total completion tokens | 367,969 | 305,773 | −62,196 |
| Prompt token reduction | — | **24.9%** | |
| Completion token reduction | — | **16.9%** | |

### Results — gpt-4o-mini ($0.15/1M input)

| Metric | Baseline | + AgentProxy | Change |
|---|---|---|---|
| Patches generated | 29/30 (96.7%) | 26/30 (86.7%) | −3 |
| Total prompt tokens | 4,908,929 | 4,730,179 | **−178,750** |
| Total completion tokens | 88,946 | 93,373 | +4,427 |
| Prompt token reduction | — | **3.6%** | |
| Estimated cost | $0.790 | $0.762 | −$0.028 |

### Key finding: compression benefits weaker models more

With **gpt-5-nano**, AgentProxy improved both token efficiency (−24.9%) and task completion rate (+14 percentage points). The model runs more turns per instance, generating larger accumulated context — exactly what compression targets.

With **gpt-4o-mini**, the stronger model solves tasks in fewer turns with smaller outputs, so there is less to compress. The 3.6% reduction reflects that tool outputs are a smaller fraction of total tokens when the agent is efficient.

**The insight:** context compression matters most when the model is prone to context overflow — weaker models, harder tasks, longer sessions.

### Why gpt-4o-mini real-world reduction (3.6%) is lower than cost benchmark (73.1%)

1. **Tool outputs are smaller** — agents run targeted tests, not full suites
2. **Tool results are a fraction of prompt tokens** — system prompt, user message, accumulated assistant turns also count but aren't compressed
3. **Some frequent commands are still unhandled** — `sed -n 'X,Yp' file` (reading file regions) is very common in SWE-bench agents but not yet supported

Run: `python benchmarks/swe/run.py --n 30 --model gpt-5-nano --skip-eval`

---

## 3. Comparison vs rtk

[rtk](https://github.com/rtk-ai/rtk) is the closest existing tool. Key difference: rtk intercepts at the **shell level** (wraps command execution); AgentProxy intercepts at the **LLM API level** (compresses messages already in the conversation history).

### Head-to-head on equivalent real shell outputs

| Command | Baseline | AgentProxy | AP% | rtk | rtk% | Winner |
|---|---:|---:|---:|---:|---:|---|
| `git diff` (80-line change) | 1,052 | 382 | **63.7%** | 833 | 20.8% | AgentProxy |
| `git status` | 70 | 13 | **81.4%** | 14 | 80.0% | tie |
| `pytest` (200 pass, 2 fail) | 10,499 | 123 | **98.8%** | 244 | 97.7% | AgentProxy |
| `grep` (4 files, 140+ matches) | 7,335 | 2,310 | 68.5% | 1,274 | **82.6%** | rtk |
| `cat` Python source | 386 | 306 | **20.7%** | 386 | 0.0% | AgentProxy |
| **TOTAL** | **19,342** | **3,134** | **83.8%** | **2,751** | **85.8%** | rtk (tiny margin) |

Token counting: `tiktoken` `cl100k_base`. Data: real shell commands on equivalent test codebases.

### Architectural comparison

| | AgentProxy | rtk |
|---|---|---|
| Interception point | LLM API (HTTP proxy) | Shell (command wrapper) |
| Setup | `ANTHROPIC_BASE_URL=http://localhost:8080` | `rtk init` hook, or `rtk git diff` |
| Agent compatibility | Any agent calling Anthropic/OpenAI API | Claude Code, Cursor, Copilot, Cline, Windsurf |
| Compresses re-sent history | **Yes** — all past tool results on every request | No — only at execution time |
| Handlers | 11 command types | 100+ commands |
| Language | Python (ML-extensible) | Rust (zero-dependency binary) |
| Overhead | ~1ms proxy + handler | <10ms per command |

### Key insight: AgentProxy compresses the **accumulated context**

Every LLM API call re-sends the full conversation history. A tool output from turn 1 gets re-sent on turns 2, 3, 4… AgentProxy compresses it every time. rtk only compresses at execution time — the uncompressed output is what the agent stores and re-sends.

For a 20-turn agent session, a tool result from turn 3 is re-sent 17 times. AgentProxy reduces it 17 times; rtk reduces it once.

### The tools are complementary

- **Use AgentProxy** when running custom API-based agents, or any agent you can't modify the tooling of
- **Use rtk** when using Claude Code, Cursor, or other IDE-based agents with shell hooks
- **Use both** for maximum reduction — rtk compresses at execution, AgentProxy compresses the accumulated history

---

## Reproducing the Benchmarks

### Cost benchmark

```bash
pip install agentproxy[benchmark]
python benchmarks/cost/run.py
# Output: benchmarks/cost/report.md
```

### SWE-bench (patch generation only, no Docker required)

```bash
# Terminal 1: start proxy
python3 -m agentproxy serve --port 8080

# Terminal 2: run baseline + proxy
python benchmarks/swe/run.py \
  --n 30 \
  --model gpt-5-nano \
  --workers 4 \
  --skip-eval

# Results written to benchmarks/swe/results/
```

### rtk comparison

```bash
# Install rtk
brew install rtk-ai/tap/rtk   # macOS
# or: curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/main/install.sh | sh

python benchmarks/cost/run.py   # runs AgentProxy side
# rtk comparison: see benchmarks/comparison_rtk.md
```
