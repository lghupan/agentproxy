"""
SWE-bench performance benchmark.

Runs a coding agent on a subset of SWE-bench Lite with and without
AgentProxy, then compares pass rate, token cost, and latency.

Usage:
  # Start AgentProxy first (in another terminal):
  #   python3 -m agentproxy serve --port 8080

  python benchmarks/swe/run.py --n 30 --model gpt-5-nano
  python benchmarks/swe/run.py --n 30 --model gpt-5-nano --proxy-only
  python benchmarks/swe/run.py --n 30 --model gpt-5-nano --baseline-only

Options:
  --n INT           Number of instances to run (default: 30)
  --model STR       Model to use (default: gpt-4o-mini)
  --proxy-url STR   AgentProxy URL (default: http://127.0.0.1:8080)
  --proxy-only      Skip baseline run
  --baseline-only   Skip proxy run
  --workers INT     Parallel workers (default: 4)
  --output DIR      Output directory (default: benchmarks/swe/results)
"""

from __future__ import annotations
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from benchmarks.swe.dataset import load_instances
from benchmarks.swe.agent import run_agent
from benchmarks.swe.evaluate import run_evaluation, parse_results


def run_batch(
    instances: list[dict],
    model: str,
    base_url: str | None,
    label: str,
    workers: int,
    output_dir: Path,
) -> tuple[Path, dict]:
    """Run agent on all instances in parallel. Returns (predictions_path, stats)."""
    predictions = []
    stats = {'total_prompt_tokens': 0, 'total_completion_tokens': 0, 'total_time_s': 0.0, 'errors': 0}

    print(f'\n[{label}] Running {len(instances)} instances with {model} ...')
    t0 = time.time()

    def _run_one(instance: dict) -> dict:
        try:
            return run_agent(instance, model=model, base_url=base_url)
        except Exception as e:
            print(f'  ERROR {instance["instance_id"]}: {e}')
            return {
                'instance_id': instance['instance_id'],
                'model_patch': '',
                'model_name_or_path': model,
                'error': str(e),
            }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_run_one, inst): inst for inst in instances}
        done = 0
        for future in as_completed(futures):
            result = future.result()
            predictions.append(result)
            stats['total_prompt_tokens'] += result.get('total_prompt_tokens', 0)
            stats['total_completion_tokens'] += result.get('total_completion_tokens', 0)
            if result.get('error'):
                stats['errors'] += 1
            done += 1
            print(f'  [{label}] {done}/{len(instances)} done — {result["instance_id"]}')

    stats['total_time_s'] = time.time() - t0

    # Write predictions
    output_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = output_dir / f'predictions_{label}.jsonl'
    with open(predictions_path, 'w') as f:
        for p in predictions:
            f.write(json.dumps(p) + '\n')

    print(f'[{label}] Predictions saved to {predictions_path}')
    return predictions_path, stats


def print_report(
    baseline_results: dict | None,
    baseline_stats: dict | None,
    proxy_results: dict | None,
    proxy_stats: dict | None,
    model: str,
) -> None:
    print('\n' + '=' * 60)
    print('BENCHMARK RESULTS')
    print('=' * 60)

    # Pass rate
    print(f'\n{"Metric":<30} {"Baseline":>12} {"+ AgentProxy":>12}')
    print('-' * 56)

    def fmt(results, stats):
        if results is None or stats is None:
            return ('—', '—', '—', '—', '—')
        passed, total, rate = parse_results(results)
        pt = stats['total_prompt_tokens']
        ct = stats['total_completion_tokens']
        cost = (pt / 1_000_000 * 0.15) + (ct / 1_000_000 * 0.60)  # gpt-4o-mini pricing
        elapsed = stats['total_time_s']
        return (
            f'{passed}/{total} ({rate:.1%})',
            f'{pt:,}',
            f'{ct:,}',
            f'${cost:.3f}',
            f'{elapsed:.0f}s',
        )

    b = fmt(baseline_results, baseline_stats)
    p = fmt(proxy_results, proxy_stats)

    rows = [
        ('Pass rate', b[0], p[0]),
        ('Prompt tokens', b[1], p[1]),
        ('Completion tokens', b[2], p[2]),
        ('Estimated cost', b[3], p[3]),
        ('Total time', b[4], p[4]),
    ]

    for label, bv, pv in rows:
        print(f'{label:<30} {bv:>12} {pv:>12}')

    # Token savings
    if baseline_stats and proxy_stats:
        bp = baseline_stats['total_prompt_tokens']
        pp = proxy_stats['total_prompt_tokens']
        if bp > 0:
            saving = (bp - pp) / bp * 100
            print(f'\nPrompt token reduction: {saving:.1f}%  ({bp - pp:,} tokens saved)')

    print()


def main() -> None:
    parser = argparse.ArgumentParser(description='SWE-bench benchmark')
    parser.add_argument('--n', type=int, default=30)
    parser.add_argument('--model', default='gpt-5-nano')
    parser.add_argument('--proxy-url', default='http://127.0.0.1:8080')
    parser.add_argument('--proxy-only', action='store_true')
    parser.add_argument('--baseline-only', action='store_true')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--output', default='benchmarks/swe/results')
    parser.add_argument('--difficulty', default='easy', choices=['easy', 'any'])
    parser.add_argument('--skip-eval', action='store_true', help='Skip Docker evaluation, only generate patches')
    args = parser.parse_args()

    output_dir = Path(args.output)
    instances = load_instances(n=args.n, difficulty=args.difficulty)
    print(f'Loaded {len(instances)} instances (difficulty={args.difficulty})')

    baseline_results = baseline_stats = None
    proxy_results = proxy_stats = None

    if not args.proxy_only:
        pred_path, baseline_stats = run_batch(
            instances, model=args.model, base_url=None,
            label='baseline', workers=args.workers, output_dir=output_dir,
        )
        if not args.skip_eval:
            baseline_results = run_evaluation(str(pred_path), run_id='baseline')

    if not args.baseline_only:
        pred_path, proxy_stats = run_batch(
            instances, model=args.model, base_url=args.proxy_url,
            label='proxy', workers=args.workers, output_dir=output_dir,
        )
        if not args.skip_eval:
            proxy_results = run_evaluation(str(pred_path), run_id='proxy')

    if not args.skip_eval:
        print_report(baseline_results, baseline_stats, proxy_results, proxy_stats, args.model)
    else:
        print('\nPatches generated. Run without --skip-eval to evaluate with Docker.')


if __name__ == '__main__':
    main()
