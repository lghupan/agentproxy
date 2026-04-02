"""
agentproxy CLI

Commands:
  run <cmd>     Start proxy and launch a command with ANTHROPIC_BASE_URL set
  serve         Start the proxy server only
  compress      Compress command output from stdin (for testing)
  stats         Show top unhandled commands by bytes passed through

Examples:
  agentproxy run claude          # run Claude Code through the proxy
  agentproxy run claude --port 9090
  agentproxy run -- my-agent --flag
  agentproxy stats               # discover what handlers to write next
  agentproxy stats --clear       # reset stats
"""

import argparse
import os
import subprocess
import sys
import threading


def main() -> None:
    parser = argparse.ArgumentParser(
        prog='agentproxy',
        description='Token compression proxy for LLM agents',
    )
    sub = parser.add_subparsers(dest='command', required=True)

    run_p = sub.add_parser('run', help='Start proxy and launch a command')
    run_p.add_argument('--port', type=int, default=8080)
    run_p.add_argument('--host', default='127.0.0.1')
    run_p.add_argument('agent_cmd', nargs=argparse.REMAINDER, help='Command to run (e.g. claude)')

    serve_p = sub.add_parser('serve', help='Start the proxy server only')
    serve_p.add_argument('--port', type=int, default=8080)
    serve_p.add_argument('--host', default='127.0.0.1')

    compress_p = sub.add_parser('compress', help='Compress command output (reads from stdin)')
    compress_p.add_argument('cmd', nargs=argparse.REMAINDER, help='Originating command (for handler selection)')

    stats_p = sub.add_parser('stats', help='Show top unhandled commands by bytes passed through')
    stats_p.add_argument('--top', type=int, default=20, help='Number of entries to show (default: 20)')
    stats_p.add_argument('--clear', action='store_true', help='Clear the stats file')

    learn_p = sub.add_parser('learn', help='Generate a compression handler from collected samples')
    learn_p.add_argument('cmd_prefix', help='Command prefix to generate a handler for (e.g. "terraform plan")')
    learn_p.add_argument('--samples', type=int, default=5, help='Max samples to use (default: 5)')
    learn_p.add_argument('--model', default=None, help='LLM model to use (default: claude-sonnet-4-6 or gpt-4o)')
    learn_p.add_argument('--dry-run', action='store_true', help='Print generated code without saving')

    args = parser.parse_args()

    if args.command == 'run':
        agent_cmd = [c for c in args.agent_cmd if c != '--']
        if not agent_cmd:
            print('Usage: agentproxy run <command>  e.g. agentproxy run claude', file=sys.stderr)
            sys.exit(1)
        _run_with_proxy(agent_cmd, host=args.host, port=args.port)

    elif args.command == 'serve':
        from .proxy.server import serve
        serve(port=args.port, host=args.host)

    elif args.command == 'compress':
        cmd = ' '.join(args.cmd).lstrip('-- ').strip()
        text = sys.stdin.read()
        from .core.pipeline import preprocess
        from .handlers.registry import get_handler
        processed = preprocess(text)
        handler = get_handler(cmd)
        result = handler.handle(cmd, processed) if handler else processed
        print(result, end='')

    elif args.command == 'stats':
        from .core.stats import read_stats, clear_stats, _MISSES_FILE
        if args.clear:
            clear_stats()
            print('Stats cleared.')
            return
        rows = read_stats(top_n=args.top)
        if not rows:
            print(f'No miss data yet. Stats are written to {_MISSES_FILE} as the proxy runs.')
            return
        _print_stats(rows)

    elif args.command == 'learn':
        from .core.learner import learn, _USER_HANDLERS_DIR
        try:
            result = learn(
                args.cmd_prefix,
                n_samples=args.samples,
                model=args.model,
                dry_run=args.dry_run,
            )
            if not args.dry_run and result:
                print(f'\nTest it: echo "sample output" | agentproxy compress {args.cmd_prefix!r}')
        except ValueError as e:
            print(f'Error: {e}', file=sys.stderr)
            sys.exit(1)
        except RuntimeError as e:
            print(f'Error: {e}', file=sys.stderr)
            sys.exit(1)


def _run_with_proxy(agent_cmd: list[str], host: str, port: int) -> None:
    """Start the proxy in a background thread, then exec the agent command."""
    import asyncio
    import uvicorn
    from .proxy.server import create_app

    ready = threading.Event()

    def _start_server() -> None:
        app = create_app()
        config = uvicorn.Config(app, host=host, port=port, log_level='warning')
        server = uvicorn.Server(config)

        async def _run() -> None:
            await server.startup()
            ready.set()
            await server.main_loop()
            await server.shutdown()

        asyncio.run(_run())

    thread = threading.Thread(target=_start_server, daemon=True)
    thread.start()
    ready.wait(timeout=5)

    env = os.environ.copy()
    base_url = f'http://{host}:{port}'
    env['ANTHROPIC_BASE_URL'] = base_url
    env['OPENAI_BASE_URL'] = base_url

    print(f'AgentProxy running on {base_url}')
    result = subprocess.run(agent_cmd, env=env)
    sys.exit(result.returncode)


def _print_stats(rows: list[dict]) -> None:
    from .core.stats import _MISSES_FILE
    total_bytes = sum(r['total_bytes'] for r in rows)
    total_calls = sum(r['calls'] for r in rows)

    print(f'\nAgentProxy — Unhandled Commands  (data from {_MISSES_FILE})')
    print(f'{total_calls} calls, {total_bytes / 1024:.1f} KB passed through uncompressed\n')

    col_w = 22
    print(f"{'Rank':<5} {'Command':<{col_w}} {'Calls':>6} {'Total KB':>9} {'Avg KB':>7}  Example")
    print('-' * (col_w + 56))
    for i, row in enumerate(rows, 1):
        kb = row['total_bytes'] / 1024
        avg_kb = row['avg_bytes'] / 1024
        example = row['example'][:50]
        print(f"{i:<5} {row['prefix']:<{col_w}} {row['calls']:>6,} {kb:>8.1f} {avg_kb:>7.1f}  {example}")

    print()
    print('Run `agentproxy stats --clear` to reset.')
