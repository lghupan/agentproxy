"""Load and filter SWE-bench instances."""

from __future__ import annotations
import json
from datasets import load_dataset


def load_instances(n: int = 30, split: str = 'test', difficulty: str = 'easy') -> list[dict]:
    """
    Load N instances from SWE-bench Lite.

    difficulty='easy'   → instances with exactly 1 FAIL_TO_PASS test (least ambiguous)
    difficulty='any'    → first N instances regardless of difficulty
    """
    ds = load_dataset('princeton-nlp/SWE-bench_Lite', split=split)
    instances = list(ds)

    if difficulty == 'easy':
        instances = [
            i for i in instances
            if len(_parse_list(i.get('FAIL_TO_PASS', '[]'))) == 1
        ]

    return instances[:n]


def _parse_list(value) -> list:
    """FAIL_TO_PASS is stored as a JSON-encoded string in the dataset."""
    if isinstance(value, list):
        return value
    try:
        return json.loads(value)
    except Exception:
        return []
