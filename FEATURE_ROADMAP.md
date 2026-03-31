# AgentProxy — Feature Roadmap

*Synthesized from three user persona brainstorming sessions: indie dev/startup, enterprise platform team, and competitive gap analysis vs. rtk/LLMlingua/Helicone. Date: 2026-03-31.*

---

## Themes

Three user types have different primary concerns:

| Persona | Top 3 needs |
|---|---|
| **Indie dev / startup** | Cost visibility in dollars, OpenAI endpoint parity, pytest correctness (preserve failures verbatim) |
| **Enterprise platform team** | Auth/RBAC, multi-tenancy with cost isolation, OpenTelemetry observability, secret redaction |
| **Competitive gap** | Non-Bash tool name support, cross-turn deduplication (moat), configurable compression level, CI/CD integration |

---

## Priority 1 — Ship Now (high impact, low effort)

### 1.1 Dollar-denominated cost tracking in dashboard
- **Why:** "73.1% reduction" requires mental math. "$0.14 saved today" converts users instantly.
- **What:** Add model pricing lookup table; dashboard and `agentproxy stats` show dollar savings alongside character counts.
- **Source:** Competitive gap (Gap 4), indie dev (Feature 4), enterprise (Feature 6)

### 1.2 Non-Bash tool name support
- **Why:** Compressor hardcodes `name == 'Bash'`. Aider, LangChain agents, and most OpenAI function-call agents use `run_bash`, `shell`, `execute`, `run_code`, etc. These get zero compression today despite the README claiming OpenAI compatibility.
- **What:** `AGENTPROXY_BASH_TOOL_NAMES=Bash,run_bash,shell,execute` env var (comma-separated). Fall back to heuristic: any `tool_use` block with an `input.command` field gets treated as a shell command.
- **Source:** Competitive gap (Gap 5)

### 1.3 Configurable compression level
- **Why:** Weak models (gpt-5-nano) benefit from aggressive compression; security/audit use cases need high fidelity. Currently requires editing source.
- **What:** `AGENTPROXY_COMPRESSION_LEVEL=conservative|default|aggressive` env var. Adjusts handler parameters (lines per hunk, matches per file, etc.).
- **Source:** Competitive gap (Gap 8), indie dev (Feature 9, 13)

### 1.4 CI/CD integration (`--output json` + GitHub Action)
- **Why:** `agentproxy run` already works headlessly; teams running CI agents just need machine-readable output and a copy-paste GitHub Action.
- **What:** `agentproxy run --output json` prints JSON summary on exit. Publish a `lghupan/agentproxy-action` GitHub Action wrapping it.
- **Source:** Competitive gap (Gap 12)

### 1.5 `pytest` handler: preserve failing tests verbatim
- **Why:** Current handler compresses aggressively; risk of losing the exact stack trace the model needs to fix a bug. Failing tests are signal, passing tests are noise.
- **What:** In `TestHandler.handle()`, extract failure blocks before any truncation and include them in full; only compress passing test lines.
- **Source:** Indie dev (Feature 6)

### 1.6 More handlers: `sed`, `head`/`tail`, `make`, `go build`/`go test`
- **Why:** `agentproxy stats` data from SWE-bench sessions shows `sed -n 'X,Yp' file` (file region reads) is the most common unhandled command. Every unhandled command is a miss.
- **What:** Priority order per miss-tracking data: `sed` (line-range extraction), `head`/`tail`, `make`, `go build`, `go test`, `curl`, `env`.
- **Source:** Competitive gap (Gap 2)

---

## Priority 2 — Near-Term (high impact, medium effort)

### 2.1 Cross-turn result deduplication
- **Why:** This is AgentProxy's **structural moat** — rtk cannot do this because it only sees each command once at execution time. AgentProxy sees the full message history on every request; identical tool results from turn 3 can be replaced with a back-reference on turns 4–20.
- **What:** Content-hash each tool_result at compression time. If an identical result was already sent in a prior turn, replace with `[same output as turn N — {N} chars]`.
- **Source:** Competitive gap (Gap 6)

### 2.2 Per-session cost export
- **Why:** Developers need to show ROI; enterprise teams need chargebacks. `savings.jsonl` already has the data.
- **What:** `agentproxy export [--session <id>] [--format csv|json]` → exportable per-session breakdown. Session IDs inferred from timestamps or explicit `X-Session-ID` header.
- **Source:** Indie dev (Feature 4), enterprise (Feature 2)

### 2.3 ML fallback cost cap
- **Why:** `AGENTPROXY_ML_FALLBACK=1` is a footgun in high-volume sessions — fallback LLM calls can exceed savings.
- **What:** `AGENTPROXY_ML_FALLBACK_MAX_TOKENS_PER_SESSION=10000` hard cap. After the cap, fall back to truncation only.
- **Source:** Indie dev (Feature 5)

### 2.4 Structure-aware `cat` handler (AST-based)
- **Why:** Current `FilesHandler` strips comments and caps at 500 lines — naive truncation. Python `ast` module can extract class/method signatures so the model sees a structural outline instead of truncated raw text.
- **What:** For `.py` files, emit `# lines 1-40: imports; class Foo (lines 42-200): methods [bar, baz, qux]; class Bar...`. Fall back to current behavior for non-Python files.
- **Source:** Competitive gap (Gap 13)

### 2.5 LangChain / LlamaIndex integration guide + tested example
- **Why:** Most API-based agents use LangChain or LlamaIndex. Compatibility is claimed but untested; quirks around streaming and custom headers have bitten users.
- **What:** `examples/langchain/agent.py` and `examples/llamaindex/agent.py` with explicit notes on streaming (disable or configure) and base URL setup.
- **Source:** Competitive gap (Gap 7), indie dev (Feature 14)

### 2.6 `--dry-run` mode
- **Why:** First-time users want to audit the proxy before trusting it with production requests.
- **What:** `agentproxy serve --dry-run` passes all requests through unmodified but logs what each handler *would* have done (handler name, chars before/after, % reduction).
- **Source:** Indie dev (Feature 3)

### 2.7 Docker image + one-liner startup
- **Why:** Setup friction is a primary adoption blocker. Installing Python + pip across dev laptop, CI, and VPS is unnecessary yak shave.
- **What:** `docker run -p 8080:8080 ghcr.io/lghupan/agentproxy` with env-var configuration passthrough.
- **Source:** Indie dev (Feature 11)

---

## Priority 3 — Enterprise Track (required for production deployment at scale)

### 3.1 Authentication layer
- **Why:** No auth means any process on the network can consume API quota. Blocker for shared infrastructure.
- **What:** API key or mTLS-based client authentication. Associate client identity with rate limits and budgets.
- **Source:** Enterprise (Feature 1)

### 3.2 Multi-tenancy with cost isolation
- **Why:** Teams sharing one proxy need per-team budgets, chargebacks, and soft-limit alerts.
- **What:** Tenant namespaces by API key prefix or request header. Per-tenant `savings.jsonl` partition. Spend export for FinOps.
- **Source:** Enterprise (Feature 2)

### 3.3 OpenTelemetry observability
- **Why:** Production systems require distributed tracing. Without OTEL spans there is no way to correlate proxy latency to agent slowness.
- **What:** OTEL traces per request (spans for each handler + compression ratio). OTEL metrics: token savings, latency p50/p95/p99, error rate. OTLP exporter config.
- **Source:** Enterprise (Feature 3)

### 3.4 Secret & PII redaction
- **Why:** `cat .env`, `git diff`, `kubectl describe secret` can leak credentials into LLM context.
- **What:** Configurable regex patterns applied before any handler. Built-in patterns for AWS keys, GCP SA JSON, private keys, JWT. Redaction audit log (pattern fired, no actual value).
- **Source:** Enterprise (Feature 4)

### 3.5 Production deployment (Kubernetes/Helm)
- **Why:** Single-process script does not meet SRE production readiness standards.
- **What:** Helm chart with probes, PDB, HPA. `/healthz` + `/readyz`. Graceful shutdown. Non-root container user.
- **Source:** Enterprise (Feature 5)

### 3.6 Rate limiting & circuit breaker
- **Why:** One runaway agent can exhaust upstream rate limits for all agents sharing the proxy.
- **What:** Per-tenant RPM/TPM rate limits (token-bucket). Circuit breaker per upstream (open after N 5xx, half-open after cooldown). Return 429 + Retry-After to clients.
- **Source:** Enterprise (Feature 7)

### 3.7 Policy-as-code for handler configuration
- **Why:** Different teams need different compression tradeoffs. Security team may want `cat` blocked; devtools team wants aggressive ML fallback.
- **What:** Per-tenant handler enable/disable and parameter overrides in YAML config files, applied without restart.
- **Source:** Enterprise (Feature 9)

### 3.8 Prompt caching injection (Anthropic cache_control)
- **Why:** Agents re-send identical system prompts on every request. Anthropic's prompt caching eliminates most of this cost but requires agents to add cache-control headers.
- **What:** Proxy detects repeated message prefixes across requests from the same session and injects `cache_control: {type: "ephemeral"}` transparently.
- **Source:** Enterprise (Feature 13)

---

## Priority 4 — Research / Differentiation

### 4.1 Cross-session result deduplication (identity-aware)
- Building on 2.1, extend deduplication across sessions for the same agent (e.g., same `cat README.md` across nightly CI runs).

### 4.2 Model-requestable full-output escape hatch
- When the proxy truncates output, include a retrieval token in the compressed result. Agent can signal "I need the full output for this tool call" and the proxy serves the cached original.
- This is a novel capability: no competitor can offer it at the shell level.
- **Source:** Competitive gap (Gap 14)

### 4.3 Local ML compression model (no API call)
- Currently ML fallback calls `gpt-5-nano` via API, adding cost and latency. A locally-runnable distilled compression model (LLMlingua-2 style) could make ML fallback the default.
- **Source:** Competitive gap (Gap 3)

### 4.4 System prompt / user message compression
- LLMlingua-2 compresses any prompt content. AgentProxy only touches `tool_result` blocks. Opt-in system prompt compression for RAG pipelines that paste large retrieved documents.
- **Source:** Competitive gap (Gap 10)

---

## Summary by Effort

| Effort | Features |
|---|---|
| **1–2 days each** | Dollar dashboard (1.1), non-Bash tool names (1.2), compression level env var (1.3), CI JSON output (1.4), pytest fix (1.5), new handlers (1.6) |
| **3–5 days each** | Cross-turn dedup (2.1), session export (2.2), ML cost cap (2.3), AST cat handler (2.4), framework examples (2.5), dry-run (2.6), Docker image (2.7) |
| **1–2 weeks each** | Auth (3.1), multi-tenancy (3.2), OTEL (3.3), secret redaction (3.4), Helm chart (3.5) |
| **Research** | Escape hatch (4.2), local ML model (4.3), system prompt compression (4.4) |

---

## The Structural Moat

> AgentProxy's unique advantage vs. rtk and all shell-level tools: **it compresses the accumulated conversation history on every API call**.
>
> A tool result from turn 3 is re-sent on turns 4, 5, 6… 20. rtk compresses it once at execution time. AgentProxy compresses it 17 times. Cross-turn deduplication (Priority 2.1) turns this architectural advantage into a feature rtk structurally cannot replicate.

---

*See also: `benchmarks/BENCHMARKS.md` for quantitative baselines.*
