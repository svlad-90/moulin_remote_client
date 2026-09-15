"""Keyboard input UI API."""

from __future__ import annotations

from components.ui.src.input import (
    KEY_ALIASES,
    InlineEditResult,
    PromptRender,
    TEXT_KEY_OFFSET,
    decode_text_key,
    encode_text_key,
    inline_edit_key_action,
    key_code_matches,
    key_code_to_text,
    key_matches_text,
    prompt_render,
    prompt_value_or_current,
    prompt_was_cancelled,
)

__all__ = [
    "KEY_ALIASES",
    "InlineEditResult",
    "PromptRender",
    "TEXT_KEY_OFFSET",
    "decode_text_key",
    "encode_text_key",
    "inline_edit_key_action",
    "key_code_matches",
    "key_code_to_text",
    "key_matches_text",
    "prompt_render",
    "prompt_value_or_current",
    "prompt_was_cancelled",
]
