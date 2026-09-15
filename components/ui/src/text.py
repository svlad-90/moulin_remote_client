"""Text layout helpers for the terminal UI."""

from __future__ import annotations


def fit_text(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    left = max(1, (width - 3) // 2)
    right = max(1, width - 3 - left)
    return f"{text[:left]}...{text[-right:]}"


def wrap_text_lines(text: str, width: int, max_lines: int) -> list[str]:
    words = text.split()
    line = ""
    lines: list[str] = []
    for word in words:
        candidate = word if not line else f"{line} {word}"
        if len(candidate) > width and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return [line[:width] for line in lines[:max_lines]]
