"""
Compresses tool_result content in an Anthropic or OpenAI messages array.

Strategy:
  1. Walk the messages array to build a map of tool_use_id -> bash command.
  2. Walk again to find tool_result blocks, look up the originating command,
     and apply the appropriate handler.
  3. Unknown commands pass through unchanged.
"""

import hashlib
import os
from ..core.pipeline import preprocess
from ..core.stats import log_miss, log_saving
from ..handlers.registry import get_handler

# Only log misses for outputs larger than this (small outputs aren't worth a handler)
_LOG_MISS_THRESHOLD_BYTES = 512


def compress_messages(messages: list[dict]) -> list[dict]:
    """Return a new messages list with tool_result content compressed."""
    tool_commands = _extract_tool_commands(messages)
    return [_compress_message(msg, tool_commands) for msg in messages]


def _extract_tool_commands(messages: list[dict]) -> dict[str, str]:
    """Build tool_use_id -> command map from Bash tool_use blocks."""
    mapping: dict[str, str] = {}
    for msg in messages:
        content = msg.get('content')
        if not isinstance(content, list):
            continue
        for block in content:
            if (
                isinstance(block, dict)
                and block.get('type') == 'tool_use'
                and block.get('name') == 'Bash'
            ):
                tool_id = block.get('id')
                command = block.get('input', {}).get('command', '')
                if tool_id and command:
                    mapping[tool_id] = command
    return mapping


def _compress_message(msg: dict, tool_commands: dict[str, str]) -> dict:
    content = msg.get('content')
    if not isinstance(content, list):
        return msg

    new_content = [_compress_block(block, tool_commands) for block in content]
    if new_content == content:
        return msg
    return {**msg, 'content': new_content}


def _compress_block(block: dict, tool_commands: dict[str, str]) -> dict:
    if not isinstance(block, dict) or block.get('type') != 'tool_result':
        return block

    tool_use_id = block.get('tool_use_id', '')
    command = tool_commands.get(tool_use_id, '')
    raw_content = block.get('content', '')

    # tool_result content can be a string or a list of content blocks
    if isinstance(raw_content, str):
        compressed = _compress_text(command, raw_content)
        if compressed == raw_content:
            return block
        return {**block, 'content': compressed}

    if isinstance(raw_content, list):
        new_parts = []
        changed = False
        for part in raw_content:
            if isinstance(part, dict) and part.get('type') == 'text':
                compressed = _compress_text(command, part.get('text', ''))
                if compressed != part.get('text', ''):
                    new_parts.append({**part, 'text': compressed})
                    changed = True
                    continue
            new_parts.append(part)
        if changed:
            return {**block, 'content': new_parts}

    return block


def _compress_text(command: str, text: str) -> str:
    processed = preprocess(text)
    handler = get_handler(command)
    if handler:
        result = handler.handle(command, processed)
        log_saving(command, len(text), len(result))
        return result
    # No handler matched — log for discovery if output is large enough
    if command and len(text.encode()) >= _LOG_MISS_THRESHOLD_BYTES:
        log_miss(command, text)
    # ML fallback: opt-in via AGENTPROXY_ML_FALLBACK=1
    if command and len(text.encode()) >= _LOG_MISS_THRESHOLD_BYTES and _ml_fallback_enabled():
        ml_result = _ml_compress(command, text)
        if ml_result and len(ml_result) < len(text):
            log_saving(command, len(text), len(ml_result))
            return ml_result
    return processed


# ---------------------------------------------------------------------------
# ML fallback (opt-in)
# ---------------------------------------------------------------------------

_ml_cache: dict[str, str] = {}  # sha256[:16] -> compressed text


def _ml_fallback_enabled() -> bool:
    return os.environ.get('AGENTPROXY_ML_FALLBACK', '').lower() in ('1', 'true', 'yes')


def _ml_compress(command: str, text: str) -> str:
    """
    Use a cheap LLM to summarize an unhandled tool output.
    Cached by content hash. Returns empty string on failure.
    Opt-in: set AGENTPROXY_ML_FALLBACK=1.
    Model: AGENTPROXY_ML_MODEL env var, default gpt-5-nano.
    """
    cache_key = hashlib.sha256(text[:2000].encode()).hexdigest()[:16]
    if cache_key in _ml_cache:
        return _ml_cache[cache_key]

    try:
        import openai
        model = os.environ.get('AGENTPROXY_ML_MODEL', 'gpt-5-nano')
        client = openai.OpenAI()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    'role': 'system',
                    'content': (
                        'You are a lossless compressor for AI coding agent tool outputs. '
                        'Given the output of a shell command, return only the essential facts '
                        'an agent needs to take its next action. '
                        'Be extremely terse — 3 to 8 lines maximum. '
                        'Preserve file paths, line numbers, error messages, and key values exactly.'
                    ),
                },
                {
                    'role': 'user',
                    'content': f'Command: {command}\n\nOutput:\n{text[:3000]}',
                },
            ],
            max_completion_tokens=300,
        )
        result = response.choices[0].message.content or ''
        _ml_cache[cache_key] = result
        return result
    except Exception:
        return ''
