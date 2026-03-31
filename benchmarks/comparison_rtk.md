# AgentProxy vs rtk — Benchmark Comparison

*Generated: 2026-03-31*

## TL;DR

On equivalent coding-agent tool outputs, AgentProxy achieves **83.8% token reduction** vs rtk's **85.8%** — essentially tied. The two tools are architecturally complementary, not competing.

---

## Head-to-head: Token Compression

| Command | Baseline | AgentProxy | AP% | rtk | rtk% | Winner |
|---|---:|---:|---:|---:|---:|---|
| `git diff` (80-line change) | 1,052 | 382 | **63.7%** | 833 | 20.8% | AgentProxy |
| `git status` | 70 | 13 | **81.4%** | 14 | 80.0% | AgentProxy |
| `pytest` (200 pass, 2 fail) | 10,499 | 123 | **98.8%** | 244 | 97.7% | AgentProxy |
| `grep` (4 files, 140+ matches) | 7,335 | 2,310 | 68.5% | 1,274 | **82.6%** | rtk |
| `cat` Python source | 386 | 306 | **20.7%** | 386 | 0.0% | AgentProxy |
| **TOTAL** | **19,342** | **3,134** | **83.8%** | **2,751** | **85.8%** | rtk (tiny margin) |

Token counting: `tiktoken` `cl100k_base`. Benchmark data: real shell executions on equivalent codebases.

---

## Architectural Difference

| | AgentProxy | rtk |
|---|---|---|
| **Interception point** | LLM API (HTTP proxy) | Shell (command wrapper) |
| **Usage** | `ANTHROPIC_BASE_URL=http://localhost:8080` | `rtk git diff` or hook init |
| **Agent compatibility** | Any agent (API-based) | Claude Code, Cursor, Copilot, Cline… |
| **Streaming support** | Yes | N/A (CLI) |
| **Handlers** | 5 command types | 100+ commands |
| **Language** | Python (ML-extensible) | Rust (zero deps) |
| **Overhead** | ~1ms proxy + handler | <10ms per command |

### When to use which

**AgentProxy** — you're running a custom agent or building one that calls the Anthropic/OpenAI API directly. Works without changing agent code; just point at the proxy.

**rtk** — you're using Claude Code, Cursor, or another IDE-based agent. Works by hooking into shell command execution.

**Both together** — AgentProxy compresses the API-level context; rtk compresses the shell outputs before they even reach the agent. Combined reduction would be additive for overlapping commands.

---

## SWE-bench Results (30 instances, gpt-4o-mini)

| Metric | Baseline | + AgentProxy |
|---|---|---|
| Non-empty patches | 29/30 | 26/30 |
| Total prompt tokens | 4,908,929 | 4,730,179 |
| Prompt token reduction | — | **3.6%** |
| Estimated cost | $0.736 | $0.710 |

The 3.6% real-world reduction vs 83.8% on benchmark samples is expected:
- SWE-bench test runs are small (targeted tests, not full suites)
- Tool outputs like `sed -n` and `find` don't match current handlers
- Token counts include system prompt and assistant messages, not just tool outputs

---

## Handler Coverage Gaps

Commands agents commonly run that AgentProxy doesn't yet compress:

| Command | Frequency | Savings potential |
|---|---|---|
| `sed -n 'Xp' file` | Very high | Low (reading specific lines) |
| `find . -name "*.py"` | High | Medium |
| `python3 -c "..."` (edit) | High | None (write-only) |
| `pip install ...` | Medium | High (noisy output) |
| `ls -la` / `ls -R` | Medium | High |
| `wc -l` / `head -n` | Low | None (already small) |

Expanding handler coverage is the primary lever to improve real-world SWE-bench reduction from 3.6% → 30%+.
