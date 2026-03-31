# AgentProxy — Cost Saving Benchmark

*Generated: 2026-03-31 01:53*

## Summary

- **Token reduction: 73.1%** across a typical coding agent session
- Tokens before: 15,179
- Tokens after:  4,090
- Tokens saved:  11,089

## Per-command breakdown

| Command | Before | After | Saved | Reduction |
|---|---:|---:|---:|---:|
| `git diff` | 1,307 | 754 | 553 | **42.3%** |
| `git status` | 177 | 103 | 74 | **41.8%** |
| `pytest` | 2,885 | 71 | 2,814 | **97.5%** |
| `tsc` | 221 | 169 | 52 | **23.5%** |
| `grep -r token src/` | 1,282 | 498 | 784 | **61.2%** |
| `ls -la src/` | 1,652 | 1,355 | 297 | **18.0%** |
| `find . -name "*.py"` | 1,239 | 9 | 1,230 | **99.3%** |
| `pip install -e .` | 517 | 99 | 418 | **80.9%** |
| `docker logs api --tail 200` | 5,513 | 726 | 4,787 | **86.8%** |
| `cat src/auth/middleware.py` | 386 | 306 | 80 | **20.7%** |
| **TOTAL** | **15,179** | **4,090** | **11,089** | **73.1%** |

○ = lossless preprocessing only (ANSI strip, dedup, blank line collapse)

## Cost savings per session

| Model | $/1M tokens | Before | After | Saved |
|---|---:|---:|---:|---:|
| claude-sonnet-4-6 | $3.00 | $0.0455 | $0.0123 | **$0.0333** |
| claude-haiku-4-5 | $0.80 | $0.0121 | $0.0033 | **$0.0089** |
| gpt-4o-mini | $0.15 | $0.0023 | $0.0006 | **$0.0017** |
| gpt-5-nano | $0.05 | $0.0008 | $0.0002 | **$0.0006** |
| gpt-5.4-nano | $0.20 | $0.0030 | $0.0008 | **$0.0022** |

## Methodology

Each sample represents realistic tool output from a coding agent session:

- **git diff**: large hunk (80 lines) triggering truncation at 50 lines per hunk
- **git status**: branch, staged/modified/untracked file listing
- **pytest**: 847 tests, 200 passing test lines, 2 failures with tracebacks
- **tsc**: TypeScript errors and warnings
- **grep**: multi-file search results across 4 files
- **cat**: source file with inline comments

Token counting uses `tiktoken` with `cl100k_base` encoding.
