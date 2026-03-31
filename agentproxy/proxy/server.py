"""
Transparent HTTP proxy built on FastAPI + httpx.

- FastAPI owns the HTTP server layer (lightweight)
- httpx handles outbound requests with proper SSL (no certificate issues)
- Compresses tool_results before forwarding to upstream LLM API
- Streams SSE responses without buffering

Supports:
  /v1/messages            Anthropic format (Claude Code, anthropic SDK)
  /v1/chat/completions    OpenAI format (any OpenAI-compatible agent)
  /dashboard              Token savings dashboard
  everything else         passed through unchanged
"""

import json
import logging
import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

log = logging.getLogger(__name__)

_ANTHROPIC_UPSTREAM = 'https://api.anthropic.com'
_OPENAI_UPSTREAM = 'https://api.openai.com'

_HOP_BY_HOP = frozenset([
    'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
    'te', 'trailers', 'transfer-encoding', 'upgrade', 'host',
    'content-length',
    'accept-encoding', 'content-encoding',
])


def create_app() -> FastAPI:
    from .callback import AgentProxyCallback
    import litellm
    litellm.callbacks = [AgentProxyCallback()]

    app = FastAPI(docs_url=None, redoc_url=None)

    @app.get('/dashboard', response_class=HTMLResponse, include_in_schema=False)
    async def dashboard() -> HTMLResponse:
        from ..core.stats import read_stats, read_savings
        savings = read_savings()
        misses = read_stats(top_n=10)
        return HTMLResponse(_render_dashboard(savings, misses))

    @app.get('/dashboard/data', response_class=JSONResponse, include_in_schema=False)
    async def dashboard_data() -> JSONResponse:
        from ..core.stats import read_stats, read_savings
        return JSONResponse({
            'savings': read_savings(),
            'misses': read_stats(top_n=10),
        })

    @app.api_route('/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
    async def proxy(request: Request, path: str) -> Response:
        upstream = _upstream_for(path)
        fwd_path = f'v1/{path}' if path.startswith('chat/') else path
        url = f'{upstream}/{fwd_path}'

        body = await request.body()
        headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP}

        # Detect streaming request before compression (compression may re-encode)
        is_stream_request = False
        content_type = request.headers.get('content-type', '')
        if 'application/json' in content_type and body:
            try:
                is_stream_request = json.loads(body).get('stream', False)
            except Exception:
                pass
            body = _try_compress(body)

        # Keep client alive for streaming; close manually in generator finally
        client = httpx.AsyncClient(timeout=300)
        try:
            req = client.build_request(request.method, url, headers=headers, content=body)
            resp = await client.send(req, stream=True)
        except Exception:
            await client.aclose()
            raise

        resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in _HOP_BY_HOP}
        is_sse = 'text/event-stream' in resp.headers.get('content-type', '')

        if is_sse or is_stream_request:
            async def _stream():
                try:
                    async for chunk in resp.aiter_bytes():
                        yield chunk
                finally:
                    await resp.aclose()
                    await client.aclose()
            return StreamingResponse(_stream(), status_code=resp.status_code, headers=resp_headers)

        # Non-streaming: buffer, close, return
        content = await resp.aread()
        await resp.aclose()
        await client.aclose()
        return Response(content=content, status_code=resp.status_code, headers=resp_headers)

    return app


def _upstream_for(path: str) -> str:
    if path.startswith('v1/chat') or path.startswith('chat/'):
        return os.environ.get('AGENTPROXY_OPENAI_UPSTREAM', _OPENAI_UPSTREAM)
    return os.environ.get('AGENTPROXY_ANTHROPIC_UPSTREAM', _ANTHROPIC_UPSTREAM)


def _try_compress(body: bytes) -> bytes:
    try:
        payload = json.loads(body)
    except Exception:
        return body

    messages = payload.get('messages')
    if not isinstance(messages, list):
        return body

    from .compressor import compress_messages
    compressed = compress_messages(messages)
    if compressed is messages:
        return body

    return json.dumps({**payload, 'messages': compressed}).encode()


def _render_dashboard(savings: dict, misses: list[dict]) -> str:
    total_saved = savings.get('total_chars_saved', 0)
    total_before = savings.get('total_chars_before', 0)
    pct = savings.get('reduction_pct', 0.0)
    total_calls = savings.get('total_calls', 0)
    top_cmds = savings.get('top_commands', [])

    def rows(data, cols):
        if not data:
            return '<tr><td colspan="10" style="color:#888">No data yet</td></tr>'
        return '\n'.join(
            '<tr>' + ''.join(f'<td>{row.get(c, "")}</td>' for c in cols) + '</tr>'
            for row in data
        )

    savings_rows = ''.join(
        f'<tr><td><code>{r["command"]}</code></td>'
        f'<td>{r["calls"]:,}</td>'
        f'<td>{r["chars_before"]/1024:.1f} KB</td>'
        f'<td>{r["chars_after"]/1024:.1f} KB</td>'
        f'<td><b>{r["pct"]:.1f}%</b></td></tr>'
        for r in top_cmds
    ) or '<tr><td colspan="5" style="color:#888">No data yet</td></tr>'

    miss_rows = ''.join(
        f'<tr><td><code>{r["prefix"]}</code></td>'
        f'<td>{r["calls"]:,}</td>'
        f'<td>{r["total_bytes"]/1024:.1f} KB</td>'
        f'<td><code>{r["example"][:60]}</code></td></tr>'
        for r in misses
    ) or '<tr><td colspan="4" style="color:#888">No data yet</td></tr>'

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>AgentProxy Dashboard</title>
  <meta http-equiv="refresh" content="10">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: #0f1117; color: #e6e6e6; margin: 0; padding: 24px; }}
    h1 {{ color: #fff; font-size: 1.4rem; margin-bottom: 4px; }}
    .subtitle {{ color: #888; font-size: 0.85rem; margin-bottom: 32px; }}
    .cards {{ display: flex; gap: 16px; margin-bottom: 32px; flex-wrap: wrap; }}
    .card {{ background: #1a1d27; border: 1px solid #2a2d3a; border-radius: 8px;
             padding: 16px 24px; min-width: 160px; }}
    .card-label {{ color: #888; font-size: 0.75rem; text-transform: uppercase;
                   letter-spacing: .05em; margin-bottom: 6px; }}
    .card-value {{ font-size: 2rem; font-weight: 700; color: #4ade80; }}
    .card-value.neutral {{ color: #60a5fa; }}
    h2 {{ color: #ccc; font-size: 1rem; margin: 0 0 12px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
    th {{ text-align: left; color: #888; font-weight: 500; padding: 6px 12px;
          border-bottom: 1px solid #2a2d3a; }}
    td {{ padding: 6px 12px; border-bottom: 1px solid #1e2130; }}
    code {{ background: #1e2130; padding: 2px 6px; border-radius: 3px;
            font-size: 0.8rem; color: #a5b4fc; }}
    .section {{ background: #1a1d27; border: 1px solid #2a2d3a; border-radius: 8px;
                padding: 20px 24px; margin-bottom: 20px; }}
    .tag-miss {{ color: #f87171; font-size: 0.75rem; font-weight: 600; }}
  </style>
</head>
<body>
  <h1>AgentProxy</h1>
  <div class="subtitle">Token compression proxy &nbsp;·&nbsp; auto-refreshes every 10s</div>

  <div class="cards">
    <div class="card">
      <div class="card-label">Chars saved</div>
      <div class="card-value">{total_saved/1024:.1f}<span style="font-size:1rem;color:#888"> KB</span></div>
    </div>
    <div class="card">
      <div class="card-label">Reduction</div>
      <div class="card-value">{pct:.1f}<span style="font-size:1rem;color:#888">%</span></div>
    </div>
    <div class="card">
      <div class="card-label">Compressions</div>
      <div class="card-value neutral">{total_calls:,}</div>
    </div>
    <div class="card">
      <div class="card-label">Unhandled cmds</div>
      <div class="card-value neutral">{len(misses)}</div>
    </div>
  </div>

  <div class="section">
    <h2>Top compressed commands</h2>
    <table>
      <tr><th>Command</th><th>Calls</th><th>Before</th><th>After</th><th>Reduction</th></tr>
      {savings_rows}
    </table>
  </div>

  <div class="section">
    <h2>Top unhandled commands <span class="tag-miss">needs handler</span></h2>
    <table>
      <tr><th>Command</th><th>Calls</th><th>Bytes passed through</th><th>Example</th></tr>
      {miss_rows}
    </table>
  </div>
</body>
</html>"""


def serve(port: int = 8080, host: str = '127.0.0.1') -> None:
    import uvicorn
    app = create_app()
    base_url = f'http://{host}:{port}'
    print(f'AgentProxy listening on {base_url}')
    print(f'  Claude Code:  ANTHROPIC_BASE_URL={base_url}')
    print(f'  OpenAI agent: OPENAI_BASE_URL={base_url}')
    print(f'  Dashboard:    {base_url}/dashboard')
    uvicorn.run(app, host=host, port=port, log_level='warning')
