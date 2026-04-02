# Learning-Based Handler Synthesis

AgentProxy ships with 11 built-in handlers. Every other command passes through uncompressed. `agentproxy learn` closes that gap by using an LLM to write new handlers — once, offline — from real output samples collected while the proxy runs.

The generated handlers are ordinary Python. No LLM is called at inference time.

---

## The three phases

```
Phase 1: Collect          Phase 2: Generate         Phase 3: Run
─────────────────         ─────────────────         ──────────────
Proxy runs normally   →   LLM reads samples,    →   Handler loads at
Unhandled output is       writes Python class.       startup. Compresses
saved as samples.         You review and save.       like any built-in.
~/.agentproxy/            agentproxy learn           <0.1ms, no network.
  samples/terraform/
  sample_0.txt
  sample_1.txt
  ...
```

---

## Phase 1 — Sample collection

When the proxy handles a request and no handler matches a tool result, it calls `log_miss()`. If the output is ≥512 bytes, it saves the raw output to disk alongside the miss record:

```
~/.agentproxy/
  misses.jsonl               ← command name + byte count (always)
  samples/
    terraform/               ← normalized command prefix
      sample_0.txt           ← full output, capped at 8KB
      sample_1.txt
      sample_2.txt           ← up to 5 samples per command
```

Each sample file is:
```
# command: terraform plan -out=tfplan
<raw output up to 8KB>
```

The command prefix is normalized the same way `agentproxy stats` normalizes it — two-word prefixes like `git diff`, `docker logs` are kept together; others use the first word. So `terraform plan -out=tfplan` and `terraform plan` both land under `samples/terraform/`.

Sampling is passive — the proxy never delays a request for it.

---

## Phase 2 — Handler generation

```bash
agentproxy learn "terraform plan"
```

This command:

**1. Reads saved samples**

Up to 5 samples are read from `~/.agentproxy/samples/terraform/`. Each one is a real output produced by the agent's actual tool calls, so the LLM sees the exact format, edge cases, and noise patterns present in your environment.

**2. Builds a few-shot prompt**

The prompt has three parts:

- **System instructions** — rules the handler must follow:
  - Subclass `BaseHandler`
  - `handle()` must catch all exceptions and return original output on error
  - No LLM calls, no network, no randomness — pure deterministic Python stdlib
  - Keep: errors, failures, key facts, file paths, line numbers, summary lines
  - Drop: progress bars, spinner lines, verbose INFO logs, decorative separators

- **Two complete handler examples** — `PipHandler` (noise filter pattern) and `PytestHandler` (section extraction pattern). These teach the LLM the expected code shape.

- **Your samples** — the real outputs, labelled with their originating command.

**3. Calls the LLM**

Tries Anthropic (`claude-sonnet-4-6`) first, falls back to OpenAI (`gpt-4o`) if the `anthropic` package isn't installed. Model is configurable:

```bash
agentproxy learn "terraform plan" --model claude-opus-4-6
agentproxy learn "make build" --model gpt-4o-mini
```

**4. Validates the generated code**

Before saving anything:

1. **Syntax check** — `compile()` on the generated class. Catches malformed Python immediately.
2. **Runtime check** — `exec()` the class in an isolated namespace with `BaseHandler` injected. Verifies it actually runs.
3. **Smoke test** — instantiates the class, calls `can_handle(command)` and `handle(command, "test output")`. Verifies both methods work and `handle()` returns a string.

If any step fails, an error is printed with the reason. The original output on the LLM will be printed so you can see what went wrong.

**5. Saves the handler**

```
~/.agentproxy/handlers/
  terraform_plan.py
```

The saved file is a self-contained Python module:

```python
import re
from agentproxy.core.base_handler import BaseHandler

class TerraformPlanHandler(BaseHandler):
    def can_handle(self, command: str) -> bool:
        return command.strip().startswith('terraform plan')

    def handle(self, command: str, output: str) -> str:
        try:
            # ... generated compression logic ...
        except Exception:
            return output
```

You can edit this file freely — it's just Python.

**Dry-run mode** — preview the generated code without saving:

```bash
agentproxy learn "terraform plan" --dry-run
```

---

## Phase 3 — Auto-loading

The registry loads user handlers at import time, before the built-in handlers:

```python
# registry.py (simplified)
_USER_HANDLERS = load_user_handlers()   # from ~/.agentproxy/handlers/*.py
_BUILTIN_HANDLERS = [GitHandler(), PytestHandler(), ...]
_HANDLERS = _USER_HANDLERS + _BUILTIN_HANDLERS
```

User handlers are checked first, so they can override built-in behaviour. A user-generated `GitHandler` will take precedence over the built-in one.

Loading happens via `importlib.util.spec_from_file_location` — each `.py` file in `~/.agentproxy/handlers/` is dynamically imported. Any class that subclasses `BaseHandler` is instantiated and added to the list. Files that fail to load print a warning to stderr but do not crash the proxy.

The handlers are loaded once at process start. After running `agentproxy learn`, restart the proxy (or call `reload_user_handlers()` in a running process) to pick up the new handler.

---

## End-to-end example

```bash
# Step 1: run agent — terraform plan is called several times, samples saved
agentproxy run claude

# Step 2: check what's leaking
agentproxy stats
#  Rank  Command       Calls   Total KB
#  1     terraform        23     184.2

# Step 3: generate handler
agentproxy learn "terraform plan"
# Generating handler for 'terraform plan' using 3 sample(s)...
#
# --- Generated code ---
# class TerraformPlanHandler(BaseHandler):
#     def can_handle(self, command: str) -> bool:
#         return command.strip().startswith('terraform plan')
#     def handle(self, command: str, output: str) -> str:
#         ...
# --- End ---
#
# Handler saved to /Users/you/.agentproxy/handlers/terraform_plan.py

# Step 4: restart proxy — handler loads automatically, terraform plan now compressed
agentproxy run claude
```

---

## Why not call the LLM at inference time?

The ML fallback (`AGENTPROXY_ML_FALLBACK=1`) does this, and it works, but it has two problems:

1. **Each miss adds a second LLM call** — for high-volume commands, the cost of summarisation can exceed the savings from compression.
2. **Latency** — a 200–500ms LLM call is added to every tool result that isn't handled.

`agentproxy learn` pays the LLM cost once, offline, and produces a deterministic function that runs in under a millisecond. The tradeoff is that the handler is static — if the command's output format changes significantly, you'd run `agentproxy learn` again.

---

## Editing a generated handler

The saved file is plain Python. Common edits:

**Tighten the `can_handle` pattern** if the handler is matching too broadly:
```python
# Too broad — matches "terraform plan -destroy" too
return 'terraform' in command

# Better
return re.match(r'^terraform\s+plan\b', command.strip()) is not None
```

**Add more noise patterns** if you notice lines still leaking through:
```python
noise = re.compile(r'^(Terraform used|Resource actions|Do you want|Only .yes.|Enter a value)')
```

**Regenerate from scratch** with more samples after more agent runs:
```bash
agentproxy learn "terraform plan"   # overwrites the existing handler
```

---

## Files reference

| Path | Purpose |
|---|---|
| `~/.agentproxy/samples/<prefix>/sample_N.txt` | Raw output samples collected by the proxy |
| `~/.agentproxy/handlers/<prefix>.py` | Generated handler modules, auto-loaded at startup |
| `~/.agentproxy/misses.jsonl` | Miss log (command, byte count, timestamp) |
| `agentproxy/core/learner.py` | Prompt builder, LLM call, code validation, save/load |
| `agentproxy/core/stats.py` | Sample collection logic (`log_miss`, `get_samples`) |
| `agentproxy/handlers/registry.py` | Handler registry with user handler auto-loading |
