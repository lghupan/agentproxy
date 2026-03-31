# Benchmarks

## Setup

```bash
pip install -e ".[benchmark]"
```

---

## 1. Cost Saving Benchmark

Measures token reduction on realistic tool outputs without needing any API key or Docker.

```bash
python benchmarks/cost/run.py
```

**What it measures:**
- Tokens before/after compression per command type (git diff, pytest, tsc, grep, cat)
- Aggregate savings % across a typical coding session
- Estimated dollar cost saved per session

---

## 2. SWE-bench Performance Benchmark

Runs a coding agent on SWE-bench Lite with and without AgentProxy, comparing pass rate and token cost.

### Prerequisites

- Docker running
- `OPENAI_API_KEY` set
- AgentProxy running in another terminal

```bash
# Terminal 1
python3 -m agentproxy serve --port 8080

# Terminal 2
python benchmarks/swe/run.py --n 30 --model gpt-4o-mini
```

### What it measures

| Metric | Description |
|---|---|
| Pass rate | % of instances where tests pass after the patch |
| Prompt tokens | Total input tokens (should be lower with proxy) |
| Completion tokens | Total output tokens (should be similar) |
| Estimated cost | Dollar cost at current model pricing |
| Total time | Wall clock time for the full run |

### Options

```bash
# Run only 10 instances for a quick check
python benchmarks/swe/run.py --n 10

# Generate patches without running Docker eval (faster)
python benchmarks/swe/run.py --n 30 --skip-eval

# Run only the proxy version (if you already have baseline)
python benchmarks/swe/run.py --n 30 --proxy-only

# Use a different model
python benchmarks/swe/run.py --n 30 --model gpt-4o

# Use any difficulty (not just easy)
python benchmarks/swe/run.py --n 30 --difficulty any
```

### How instances are selected

`--difficulty easy` (default): picks instances with exactly 1 `FAIL_TO_PASS` test — the clearest signal of a correct fix with the least noise.

`--difficulty any`: first N instances from SWE-bench Lite regardless of difficulty.

### Results location

Patches and results are saved to `benchmarks/swe/results/`.
