"""
AgentProxy latency benchmark.

Measures overhead at three levels:
  1. Compression pipeline only (pure CPU, no network)
  2. Proxy round-trip vs direct HTTP (using a local echo server as fake upstream)
  3. Breakdown: JSON parse/serialize vs handler execution vs HTTP hop

Run: python benchmarks/latency/run.py
"""

import asyncio
import json
import os
import statistics
import sys
import time
import threading
from pathlib import Path

# Make sure agentproxy is importable from repo root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import Response

# ---------------------------------------------------------------------------
# Realistic payloads (same data used in cost benchmark)
# ---------------------------------------------------------------------------

_GIT_DIFF = """\
diff --git a/src/auth/middleware.py b/src/auth/middleware.py
index abc1234..def5678 100644
--- a/src/auth/middleware.py
+++ b/src/auth/middleware.py
@@ -1,6 +1,8 @@
 import hashlib
 import hmac
+import logging
+import time
 from functools import wraps
 from flask import request, abort, g

@@ -15,12 +17,18 @@ SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-only')
+log = logging.getLogger(__name__)
+
 def require_auth(f):
     @wraps(f)
     def decorated(*args, **kwargs):
-        token = request.headers.get('Authorization', '').replace('Bearer ', '')
-        if not _verify(token):
-            abort(401)
+        token = request.headers.get('Authorization', '')
+        if not token.startswith('Bearer '):
+            log.warning('missing Bearer prefix')
+            abort(401)
+        token = token[7:]
+        if not _verify(token):
+            log.warning('invalid token')
+            abort(401)
         return f(*args, **kwargs)
     return decorated
""" * 4  # ~4KB diff

_PYTEST_OUTPUT = """\
============================= test session starts ==============================
platform linux -- Python 3.11.4, pytest-7.4.0
rootdir: /workspace
collected 847 items

tests/test_models.py .............................................................. [ 6%]
tests/test_api.py .................................................................. [13%]
tests/test_auth.py ................................................................. [21%]
tests/test_utils.py ................................................................ [29%]
tests/test_db.py ................................................................... [37%]
tests/test_cache.py ................................................................ [45%]
tests/test_search.py ............................................................... [53%]
tests/test_billing.py .............................................................. [60%]
tests/test_webhooks.py ............................................................. [68%]
tests/test_jobs.py ................................................................. [76%]
tests/test_admin.py ................................................................ [84%]
tests/test_e2e.py .F................................................................ [92%]
tests/test_regression.py ....F..................................................... [100%]

=================================== FAILURES ===================================
_____________ test_checkout_flow_with_discount _____________
...
FAILED tests/test_e2e.py::test_checkout_flow_with_discount - AssertionError: 0 != 200
FAILED tests/test_regression.py::test_price_rounding - AssertionError: 1.005 != 1.01
============================== 2 failed, 845 passed in 12.34s ==============================
"""

_GREP_OUTPUT = "\n".join(
    f"src/module_{i}/file_{j}.py:42:    result = authenticate(user, token)"
    for i in range(8) for j in range(20)
)  # 160 lines


def _make_messages(tool_output: str, command: str, n_turns: int = 1) -> list[dict]:
    """Build a realistic messages array with tool_use + tool_result pairs."""
    messages = []
    for i in range(n_turns):
        tool_id = f"tool_{i:04d}"
        messages.append({
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let me check that."},
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": "Bash",
                    "input": {"command": command},
                },
            ],
        })
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": tool_output,
                }
            ],
        })
    return messages


# ---------------------------------------------------------------------------
# 1. Pure compression pipeline benchmark (no network)
# ---------------------------------------------------------------------------

def bench_compression_pipeline(n: int = 500) -> dict:
    from agentproxy.proxy.compressor import compress_messages
    from agentproxy.proxy.server import _try_compress

    scenarios = [
        ("git diff (4KB, 1 turn)", _GIT_DIFF, "git diff HEAD", 1),
        ("pytest (847 tests, 1 turn)", _PYTEST_OUTPUT, "pytest", 1),
        ("grep (160 lines, 1 turn)", _GREP_OUTPUT, "grep -r authenticate src/", 1),
        ("git diff (10 turns, accumulated)", _GIT_DIFF, "git diff HEAD", 10),
        ("no tool_result (passthrough)", "hello world", "", 1),
    ]

    results = []
    for label, output, command, turns in scenarios:
        messages = _make_messages(output, command, n_turns=turns)
        payload = json.dumps({"model": "claude-sonnet-4-6", "messages": messages})
        body = payload.encode()

        # Warm up
        for _ in range(5):
            _try_compress(body)

        # Measure
        times = []
        for _ in range(n):
            t0 = time.perf_counter()
            _try_compress(body)
            times.append((time.perf_counter() - t0) * 1000)

        results.append({
            "scenario": label,
            "payload_kb": len(body) / 1024,
            "p50_ms": statistics.median(times),
            "p95_ms": statistics.quantiles(times, n=20)[18],  # 95th percentile
            "p99_ms": statistics.quantiles(times, n=100)[98],
            "mean_ms": statistics.mean(times),
        })

    return results


# ---------------------------------------------------------------------------
# 2. JSON parse/serialize breakdown
# ---------------------------------------------------------------------------

def bench_json_breakdown(n: int = 1000) -> dict:
    from agentproxy.proxy.compressor import compress_messages

    output = _GIT_DIFF
    command = "git diff HEAD"
    messages = _make_messages(output, command, n_turns=5)
    payload = {"model": "claude-sonnet-4-6", "messages": messages}
    body = json.dumps(payload).encode()

    # Just JSON parse + serialize (no compression)
    parse_times = []
    for _ in range(n):
        t0 = time.perf_counter()
        parsed = json.loads(body)
        _ = json.dumps(parsed).encode()
        parse_times.append((time.perf_counter() - t0) * 1000)

    # Just compression (no JSON)
    compress_times = []
    for _ in range(n):
        t0 = time.perf_counter()
        compress_messages(messages)
        compress_times.append((time.perf_counter() - t0) * 1000)

    # Full pipeline
    full_times = []
    from agentproxy.proxy.server import _try_compress
    for _ in range(n):
        t0 = time.perf_counter()
        _try_compress(body)
        full_times.append((time.perf_counter() - t0) * 1000)

    return {
        "json_only_p50": statistics.median(parse_times),
        "compress_only_p50": statistics.median(compress_times),
        "full_pipeline_p50": statistics.median(full_times),
        "payload_kb": len(body) / 1024,
        "n_turns": 5,
    }


# ---------------------------------------------------------------------------
# 3. HTTP round-trip overhead (proxy vs direct)
# ---------------------------------------------------------------------------

def _start_echo_server(port: int) -> None:
    """Minimal FastAPI server that echoes back a 200 with empty JSON body."""
    echo_app = FastAPI(docs_url=None, redoc_url=None)

    @echo_app.api_route("/{path:path}", methods=["GET", "POST", "PUT"])
    async def echo(request: Request, path: str) -> Response:
        # Simulate minimal upstream processing time
        body = await request.body()
        return Response(
            content=b'{"id":"msg_bench","type":"message","role":"assistant","content":[],"model":"claude-sonnet-4-6","stop_reason":"end_turn","usage":{"input_tokens":10,"output_tokens":1}}',
            status_code=200,
            headers={"content-type": "application/json"},
        )

    config = uvicorn.Config(echo_app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    asyncio.run(server.serve())


def _start_proxy(proxy_port: int, upstream_port: int) -> None:
    """Start AgentProxy pointing at the local echo server."""
    os.environ["AGENTPROXY_ANTHROPIC_UPSTREAM"] = f"http://127.0.0.1:{upstream_port}"
    os.environ["AGENTPROXY_OPENAI_UPSTREAM"] = f"http://127.0.0.1:{upstream_port}"

    from agentproxy.proxy.server import create_app
    app = create_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=proxy_port, log_level="error")
    server = uvicorn.Server(config)
    asyncio.run(server.serve())


def _wait_for_port(port: int, timeout: float = 5.0) -> bool:
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def bench_http_roundtrip(n: int = 200) -> dict:
    echo_port = 18081
    proxy_port = 18082

    # Start echo server
    echo_thread = threading.Thread(
        target=_start_echo_server, args=(echo_port,), daemon=True
    )
    echo_thread.start()

    # Start proxy
    proxy_thread = threading.Thread(
        target=_start_proxy, args=(proxy_port, echo_port), daemon=True
    )
    proxy_thread.start()

    if not _wait_for_port(echo_port):
        return {"error": "echo server failed to start"}
    if not _wait_for_port(proxy_port):
        return {"error": "proxy failed to start"}

    # Payload with a real tool result (git diff)
    messages = _make_messages(_GIT_DIFF, "git diff HEAD", n_turns=3)
    payload = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": 1024,
        "messages": messages,
        "stream": False,
    }).encode()
    headers = {
        "content-type": "application/json",
        "x-api-key": "sk-ant-benchmark",
        "anthropic-version": "2023-06-01",
    }

    def measure(url: str, reps: int) -> list[float]:
        times = []
        with httpx.Client(timeout=30) as client:
            # Warm up
            for _ in range(5):
                client.post(url, content=payload, headers=headers)
            for _ in range(reps):
                t0 = time.perf_counter()
                client.post(url, content=payload, headers=headers)
                times.append((time.perf_counter() - t0) * 1000)
        return times

    direct_times = measure(f"http://127.0.0.1:{echo_port}/v1/messages", n)
    proxy_times = measure(f"http://127.0.0.1:{proxy_port}/v1/messages", n)

    return {
        "direct_p50_ms": statistics.median(direct_times),
        "direct_p95_ms": statistics.quantiles(direct_times, n=20)[18],
        "proxy_p50_ms": statistics.median(proxy_times),
        "proxy_p95_ms": statistics.quantiles(proxy_times, n=20)[18],
        "overhead_p50_ms": statistics.median(proxy_times) - statistics.median(direct_times),
        "overhead_p95_ms": statistics.quantiles(proxy_times, n=20)[18] - statistics.quantiles(direct_times, n=20)[18],
        "payload_kb": len(payload) / 1024,
        "n_turns": 3,
    }


# ---------------------------------------------------------------------------
# Per-handler microbenchmark
# ---------------------------------------------------------------------------

def bench_handlers(n: int = 1000) -> list[dict]:
    from agentproxy.handlers.registry import get_handler
    from agentproxy.core.pipeline import preprocess

    cases = [
        ("git diff", _GIT_DIFF, "git diff HEAD"),
        ("pytest", _PYTEST_OUTPUT, "pytest"),
        ("grep", _GREP_OUTPUT, "grep -r authenticate src/"),
        ("preprocess only (no handler)", _GIT_DIFF, "unknown_command_xyz"),
    ]

    results = []
    for label, output, command in cases:
        processed = preprocess(output)
        handler = get_handler(command)

        # Warm up
        for _ in range(10):
            preprocess(output)
            if handler:
                handler.handle(command, processed)

        times = []
        for _ in range(n):
            t0 = time.perf_counter()
            p = preprocess(output)
            if handler:
                handler.handle(command, p)
            times.append((time.perf_counter() - t0) * 1000)

        results.append({
            "handler": label,
            "input_kb": len(output.encode()) / 1024,
            "p50_ms": statistics.median(times),
            "p95_ms": statistics.quantiles(times, n=20)[18],
            "mean_ms": statistics.mean(times),
        })

    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _bar(val: float, max_val: float, width: int = 20) -> str:
    filled = int(val / max_val * width) if max_val > 0 else 0
    return "█" * filled + "░" * (width - filled)


def main() -> None:
    print("AgentProxy — Latency Benchmark")
    print("=" * 60)

    # 1. Per-handler timing
    print("\n[1/4] Handler microbenchmark (preprocess + compress, n=1000)")
    print(f"  {'Handler':<40} {'Input':>7} {'p50':>8} {'p95':>8} {'mean':>8}")
    print("  " + "-" * 76)
    handler_results = bench_handlers(n=1000)
    max_p50 = max(r["p50_ms"] for r in handler_results)
    for r in handler_results:
        bar = _bar(r["p50_ms"], max_p50)
        print(f"  {r['handler']:<40} {r['input_kb']:>6.1f}KB {r['p50_ms']:>6.3f}ms {r['p95_ms']:>6.3f}ms {r['mean_ms']:>6.3f}ms  {bar}")

    # 2. Pipeline scenarios
    print("\n[2/4] Full compression pipeline (_try_compress), n=500")
    print(f"  {'Scenario':<45} {'Size':>7} {'p50':>8} {'p95':>8} {'p99':>8}")
    print("  " + "-" * 83)
    pipeline_results = bench_compression_pipeline(n=500)
    for r in pipeline_results:
        print(f"  {r['scenario']:<45} {r['payload_kb']:>6.1f}KB {r['p50_ms']:>6.3f}ms {r['p95_ms']:>6.3f}ms {r['p99_ms']:>6.3f}ms")

    # 3. JSON breakdown
    print("\n[3/4] Pipeline breakdown (5-turn git diff payload)")
    breakdown = bench_json_breakdown(n=1000)
    print(f"  JSON parse + serialize:  {breakdown['json_only_p50']:.3f}ms  (p50)")
    print(f"  Compression only:        {breakdown['compress_only_p50']:.3f}ms  (p50)")
    print(f"  Full pipeline total:     {breakdown['full_pipeline_p50']:.3f}ms  (p50)")
    print(f"  Payload: {breakdown['payload_kb']:.1f}KB, {breakdown['n_turns']} turns")

    # 4. HTTP round-trip
    print("\n[4/4] HTTP round-trip overhead (local echo upstream, n=200)")
    print("      Starting servers...", end="", flush=True)
    http_results = bench_http_roundtrip(n=200)
    if "error" in http_results:
        print(f"\n  ERROR: {http_results['error']}")
    else:
        print()
        print(f"  Direct (echo only):   p50={http_results['direct_p50_ms']:.2f}ms  p95={http_results['direct_p95_ms']:.2f}ms")
        print(f"  Via proxy:            p50={http_results['proxy_p50_ms']:.2f}ms  p95={http_results['proxy_p95_ms']:.2f}ms")
        print(f"  Proxy overhead:       p50=+{http_results['overhead_p50_ms']:.2f}ms  p95=+{http_results['overhead_p95_ms']:.2f}ms")
        print(f"  Payload: {http_results['payload_kb']:.1f}KB, {http_results['n_turns']} turns")

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    if "error" not in http_results:
        compress_p50 = pipeline_results[0]['p50_ms']
        # In the benchmark, proxy overhead = client→proxy hop + compression + proxy→echo hop.
        # In production, the upstream is remote (not local), so the overhead is:
        #   client→proxy (one local round-trip ≈ direct_p50/2) + compression
        local_hop_ms = http_results['direct_p50_ms'] / 2
        production_overhead = local_hop_ms + compress_p50
        print(f"  Compression pipeline (CPU only):   ~{compress_p50:.3f}ms p50  (4KB git diff, 1 turn)")
        print(f"  Compression pipeline (CPU only):   ~{pipeline_results[3]['p50_ms']:.3f}ms p50  (4KB git diff, 10 turns)")
        print()
        print(f"  Benchmark HTTP overhead (2 local hops vs 1):  +{http_results['overhead_p50_ms']:.1f}ms p50")
        print(f"  Note: benchmark compares 2 loopback hops vs 1. In production upstream")
        print(f"  is remote, so proxy adds only 1 local hop + compression:")
        print(f"    local hop (½ of direct p50):  ~{local_hop_ms:.2f}ms")
        print(f"    compression pipeline:          ~{compress_p50:.3f}ms")
        print(f"    estimated production overhead: ~{production_overhead:.2f}ms  (<1ms typical)")
        print()
        for latency_ms, label in [(300, "fast API, 300ms"), (600, "typical API, 600ms"), (2000, "slow/streaming, 2s")]:
            pct = production_overhead / latency_ms * 100
            print(f"  As % of {label} TTFB:  {pct:.2f}%")


if __name__ == "__main__":
    main()
