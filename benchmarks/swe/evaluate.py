"""
Run the SWE-bench evaluation harness on a predictions file.
Wraps the official `swebench` CLI to run Docker-based test execution.
"""

from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

# Docker Desktop on macOS uses a non-standard socket path
_DOCKER_SOCKET = os.path.expanduser('~/.docker/run/docker.sock')
if os.path.exists(_DOCKER_SOCKET) and 'DOCKER_HOST' not in os.environ:
    os.environ['DOCKER_HOST'] = f'unix://{_DOCKER_SOCKET}'


def run_evaluation(
    predictions_path: str,
    run_id: str,
    max_workers: int = 4,
) -> dict:
    """
    Run swebench evaluation and return per-instance results.

    predictions_path: path to JSONL file with {instance_id, model_patch, model_name_or_path}
    run_id: identifier for this evaluation run (used for output dirs)
    """
    report_dir = Path(predictions_path).parent / 'eval_logs'
    report_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, '-m', 'swebench.harness.run_evaluation',
        '--dataset_name', 'princeton-nlp/SWE-bench_Lite',
        '--predictions_path', predictions_path,
        '--max_workers', str(max_workers),
        '--run_id', run_id,
        '--report_dir', str(report_dir),
    ]

    print(f'Running evaluation: {" ".join(cmd)}')
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print('STDERR:', result.stderr[-2000:])
        raise RuntimeError(f'Evaluation failed with code {result.returncode}')

    # swebench writes {model}.{run_id}.json in the current directory
    candidates = (
        list(Path('.').glob(f'*.{run_id}.json'))
        + list(Path('.').glob(f'{run_id}*.json'))
        + list(report_dir.glob('*.json'))
    )
    if not candidates:
        raise FileNotFoundError(
            f'Results not found. Checked cwd and {report_dir}. '
            f'Files in cwd: {list(Path(".").glob("*.json"))}'
        )

    results_path = candidates[0]
    print(f'Results found at {results_path}')
    return json.loads(results_path.read_text())


def parse_results(results: dict) -> tuple[int, int, float]:
    """Return (passed, total, pass_rate) from swebench results dict."""
    resolved = results.get('resolved', [])
    total = results.get('total', 0)
    passed = len(resolved)
    rate = passed / total if total > 0 else 0.0
    return passed, total, rate
