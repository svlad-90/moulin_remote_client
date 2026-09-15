"""Keyboard input helpers for the terminal UI."""

from __future__ import annotations

import curses
import sys
from dataclasses import dataclass


TEXT_KEY_OFFSET = sys.maxunicode + 1


@dataclass(frozen=True)
class PromptRender:
    prompt: str
    visible_prompt: str
    clear_text: str
    input_x: int


@dataclass(frozen=True)
class InlineEditResult:
    value: str
    cursor: int
    action: str


KEY_ALIASES = {
    "a": ("a", "ф"),
    "b": ("b", "и"),
    "d": ("d", "в"),
    "f": ("f", "а"),
    "h": ("h", "р"),
    "j": ("j", "о"),
    "k": ("k", "л"),
    "l": ("l", "д"),
    "n": ("n", "т"),
    "p": ("p", "з"),
    "q": ("q", "й"),
    "r": ("r", "к"),
    "s": ("s", "ы", "і"),
    "y": ("y", "н"),
}


def encode_text_key(text: str) -> int:
    if not text:
        return -1
    code = ord(text[0])
    if code >= 256 and text[0].isprintable():
        return TEXT_KEY_OFFSET + code
    return code


def decode_text_key(ch: int) -> str:
    if ch < TEXT_KEY_OFFSET:
        return ""
    try:
        return chr(ch - TEXT_KEY_OFFSET)
    except (OverflowError, ValueError):
        return ""


def key_code_to_text(ch: int) -> str:
    encoded_text_key = ch >= TEXT_KEY_OFFSET
    if encoded_text_key:
        ch -= TEXT_KEY_OFFSET
    if ch < 0 or ch > sys.maxunicode:
        return ""
    if not encoded_text_key and curses.KEY_MIN <= ch <= curses.KEY_MAX:
        return ""
    try:
        text = chr(ch)
    except (OverflowError, ValueError):
        return ""
    if not text.isprintable():
        return ""
    return text


def key_matches_text(text: str, *keys: str) -> bool:
    clean = text.casefold()
    if not clean:
        return False
    for key in keys:
        aliases = KEY_ALIASES.get(key.casefold(), (key,))
        if clean in {alias.casefold() for alias in aliases}:
            return True
    return False


def key_code_matches(ch: int, *keys: str) -> bool:
    return key_matches_text(key_code_to_text(ch), *keys)


def prompt_render(label: str, current: str, width: int) -> PromptRender:
    prompt = f"{label} [{current}]: "
    visible_width = max(0, width - 1)
    return PromptRender(
        prompt=prompt,
        visible_prompt=prompt[:visible_width],
        clear_text=" " * visible_width,
        input_x=min(len(prompt), width - 2),
    )


def prompt_value_or_current(value: str, current: str) -> str:
    value = value.strip()
    return value or current


def inline_edit_key_action(value: str, cursor: int, ch: int, text: str = "") -> InlineEditResult:
    cursor = min(max(0, cursor), len(value))
    if ch in (10, 13):
        return InlineEditResult(value=value, cursor=cursor, action="save")
    if ch == 27:
        return InlineEditResult(value=value, cursor=cursor, action="cancel")
    if ch in (curses.KEY_BACKSPACE, 127, 8):
        if cursor <= 0:
            return InlineEditResult(value=value, cursor=cursor, action="edit")
        return InlineEditResult(
            value=value[: cursor - 1] + value[cursor:],
            cursor=cursor - 1,
            action="edit",
        )
    if ch == curses.KEY_DC:
        if cursor >= len(value):
            return InlineEditResult(value=value, cursor=cursor, action="edit")
        return InlineEditResult(
            value=value[:cursor] + value[cursor + 1:],
            cursor=cursor,
            action="edit",
        )
    if ch == curses.KEY_LEFT:
        return InlineEditResult(value=value, cursor=max(0, cursor - 1), action="edit")
    if ch == curses.KEY_RIGHT:
        return InlineEditResult(value=value, cursor=min(len(value), cursor + 1), action="edit")
    if ch == curses.KEY_HOME:
        return InlineEditResult(value=value, cursor=0, action="edit")
    if ch == curses.KEY_END:
        return InlineEditResult(value=value, cursor=len(value), action="edit")
    if text:
        return InlineEditResult(
            value=value[:cursor] + text + value[cursor:],
            cursor=cursor + len(text),
            action="edit",
        )
    return InlineEditResult(value=value, cursor=cursor, action="noop")
