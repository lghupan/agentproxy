"""
Compression level configuration.

Set AGENTPROXY_COMPRESSION_LEVEL=conservative|default|aggressive

  conservative  — raise all caps; prioritise fidelity over token savings.
                  Use when reviewing security patches, large refactors, or
                  whenever the model needs full context.

  default       — balanced caps tuned for typical coding-agent sessions.

  aggressive    — lower all caps; maximise token savings.
                  Use with weak/cheap models (gpt-5-nano) that hit context
                  limits and benefit most from compression.
"""

import os

_LEVEL = os.environ.get('AGENTPROXY_COMPRESSION_LEVEL', 'default').lower().strip()

if _LEVEL not in ('conservative', 'default', 'aggressive'):
    import warnings
    warnings.warn(
        f"Unknown AGENTPROXY_COMPRESSION_LEVEL={_LEVEL!r}. "
        "Valid values: conservative, default, aggressive. Falling back to 'default'.",
        stacklevel=2,
    )
    _LEVEL = 'default'

# ---------------------------------------------------------------------------
# Per-handler parameter sets
# ---------------------------------------------------------------------------

_PARAMS = {
    #                       conservative  default  aggressive
    'git_diff_hunk_lines':  (100,         50,      20),
    'grep_per_file':        (20,          10,      5),
    'grep_max_files':       (40,          20,      10),
    'cat_max_lines':        (1000,        500,     200),
    'ls_max_entries':       (100,         50,      20),
    'find_max_lines':       (80,          40,      15),
    'log_max_lines':        (100,         50,      20),   # docker/kubectl logs tail
    'log_error_cap':        (60,          30,      15),   # max error lines kept
}

_IDX = {'conservative': 0, 'default': 1, 'aggressive': 2}[_LEVEL]


def get(key: str) -> int:
    return _PARAMS[key][_IDX]


LEVEL = _LEVEL
