"""
AgentProxy compression hook for LiteLLM.

Registered via litellm.callbacks — fires before every API call including
/v1/messages (Anthropic format). Compresses tool_result content in the
messages array before it reaches the upstream model.
"""

from litellm.integrations.custom_logger import CustomLogger
from .compressor import compress_messages


class AgentProxyCallback(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        messages = data.get("messages")
        if isinstance(messages, list):
            compressed = compress_messages(messages)
            if compressed is not messages:
                data["messages"] = compressed
        return data
