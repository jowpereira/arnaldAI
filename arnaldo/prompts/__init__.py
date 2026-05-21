"""Prompts e context builders para o substrate cognitivo."""

from .persona import ARNALDO_PERSONA, build_system_prompt
from .context import build_chat_messages

__all__ = ["ARNALDO_PERSONA", "build_system_prompt", "build_chat_messages"]
