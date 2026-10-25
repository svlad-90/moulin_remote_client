"""Reusable local filesystem picker for terminal workflows."""

from __future__ import annotations

import curses
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from components.ui.api import input as ui_input_api


@dataclass(frozen=True)
class LocalFileEntry:
    path: Path
    is_directory: bool
    selectable: bool


def local_file_entries(
    directory: Path,
    accept_file: Callable[[Path], bool],
) -> list[LocalFileEntry]:
    entries: list[LocalFileEntry] = []
    if directory.parent != directory:
        entries.append(LocalFileEntry(directory.parent, True, False))
    children = sorted(
        directory.iterdir(),
        key=lambda path: (not path.is_dir(), path.name.casefold()),
    )
    for path in children:
        is_directory = path.is_dir()
        entries.append(LocalFileEntry(path, is_directory, path.is_file() and accept_file(path)))
    return entries


def select_local_file(
    port: Any,
    *,
    title: str,
    accept_file: Callable[[Path], bool],
    initial_directory: Path | None = None,
    file_hint: str = "Select a file",
) -> Path | None:
    current = (initial_directory or Path.home()).expanduser()
    if current.is_file():
        current = current.parent
    try:
        current = current.resolve()
    except OSError:
        current = Path.home().resolve()
    index = 0
    offset = 0
    message = ""
    port.screen.timeout(-1)
    while True:
        try:
            entries = local_file_entries(current, accept_file)
        except OSError as exc:
            entries = []
            message = str(exc)
        index = max(0, min(index, len(entries) - 1))
        port.screen.erase()
        height, width = port.screen.getmaxyx()
        port.add(0, 0, title[:width], curses.A_BOLD)
        port.add(1, 0, str(current)[:width], port.accent_attr())
        list_top = 3
        visible = max(1, height - list_top - 3)
        if index < offset:
            offset = index
        elif index >= offset + visible:
            offset = index - visible + 1
        for row, entry in enumerate(entries[offset:offset + visible], start=list_top):
            if entry.path == current.parent and entry.is_directory:
                label = "[..]"
            elif entry.is_directory:
                label = f"[{entry.path.name}]"
            else:
                label = entry.path.name
            attr = curses.A_REVERSE if offset + row - list_top == index else curses.A_NORMAL
            if entry.is_directory:
                attr |= curses.A_BOLD
            elif not entry.selectable:
                attr |= curses.A_DIM
            port.add(row, 2, label[: max(1, width - 4)], attr)
        detail = message or file_hint
        port.add(height - 2, 0, detail[:width], port.warn_attr() if message else port.accent_attr())
        footer = "Up/Down: select | Enter: open/select | Left/Backspace: parent | q/Esc: cancel"
        port.add(height - 1, 0, footer[:width], curses.A_REVERSE)
        port.screen.refresh()
        ch = port.read_key()
        message = ""
        if ch == curses.KEY_UP and entries:
            index = (index - 1) % len(entries)
        elif ch == curses.KEY_DOWN and entries:
            index = (index + 1) % len(entries)
        elif ch == curses.KEY_PPAGE and entries:
            index = max(0, index - visible)
        elif ch == curses.KEY_NPAGE and entries:
            index = min(len(entries) - 1, index + visible)
        elif ch in (curses.KEY_LEFT, curses.KEY_BACKSPACE, 8, 127):
            if current.parent != current:
                current = current.parent
                index = 0
                offset = 0
        elif ch in (10, 13, curses.KEY_ENTER) and entries:
            entry = entries[index]
            if entry.is_directory:
                current = entry.path
                index = 0
                offset = 0
            elif entry.selectable:
                port.screen.timeout(1000)
                return entry.path
            else:
                message = "This file does not match the expected artifact type"
        elif ch == 27 or ui_input_api.key_code_matches(ch, "q"):
            port.screen.timeout(1000)
            return None
