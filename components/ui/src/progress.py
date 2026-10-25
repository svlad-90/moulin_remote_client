"""Modal progress display for short blocking computations."""

from __future__ import annotations

import curses
import queue
import threading
from typing import Any, Callable, TypeVar, cast

from components.ui.api import text as ui_text_api


T = TypeVar("T")


class ModalTaskCancelled(RuntimeError):
    """Raised in a modal worker after the user requests cancellation."""


class ProgressReporter:
    """Thread-safe progress callback with cooperative cancellation."""

    def __init__(self, progress: list[int], lock: threading.Lock) -> None:
        self.progress = progress
        self.lock = lock
        self.cancel_event = threading.Event()

    def __call__(self, current: int, total: int) -> None:
        if self.cancel_event.is_set():
            raise ModalTaskCancelled("operation cancelled")
        with self.lock:
            self.progress[:] = [max(0, current), max(0, total)]

    def cancel(self) -> None:
        self.cancel_event.set()


def run_modal_task(
    port: Any,
    *,
    title: str,
    detail: str,
    task: Callable[[ProgressReporter], T],
) -> T:
    """Run a computation off the curses thread while keeping progress visible."""
    outcome: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)
    progress_lock = threading.Lock()
    progress = [0, 0]
    reporter = ProgressReporter(progress, progress_lock)

    def worker() -> None:
        try:
            outcome.put((True, task(reporter)))
        except BaseException as exc:
            outcome.put((False, exc))

    thread = threading.Thread(target=worker, name="moulin-modal-task", daemon=True)
    thread.start()
    frames = ("|", "/", "-", "\\")
    frame = 0
    port.screen.timeout(0)
    try:
        while thread.is_alive():
            port.screen.erase()
            height, width = port.screen.getmaxyx()
            if height >= 8 and width >= 60:
                box_height = 8
                box_width = min(width - 4, 78)
                top = max(0, (height - box_height) // 2)
                left = max(0, (width - box_width) // 2)
                port.draw_box(top, left, box_height, box_width, title)
                port.add(top + 2, left + 2, ui_text_api.fit_text(detail, box_width - 4))
                with progress_lock:
                    current, total = progress
                if total:
                    ratio = min(1.0, current / total)
                    bar_width = max(10, box_width - 24)
                    filled = round(bar_width * ratio)
                    bar = "[" + "#" * filled + "-" * (bar_width - filled) + "]"
                    status = f"{bar} {ratio * 100:5.1f}%"
                    amount = f"{current / 1048576:.1f} / {total / 1048576:.1f} MiB"
                else:
                    status = f"{frames[frame % len(frames)]} Reading artifact metadata..."
                    amount = "Waiting for archive reader"
                port.add(
                    top + 4,
                    left + 2,
                    ui_text_api.fit_text(status, box_width - 4),
                    port.accent_attr(),
                )
                port.add(top + 5, left + 2, ui_text_api.fit_text(amount, box_width - 4))
                footer = "Cancelling..." if reporter.cancel_event.is_set() else "Esc: cancel"
                port.add(top + 7, left + 2, ui_text_api.fit_text(footer, box_width - 4))
            else:
                port.add(0, 0, ui_text_api.fit_text(f"{title}: {detail}", width), curses.A_BOLD)
            port.screen.refresh()
            ch = port.read_key()
            if ch == 27:
                reporter.cancel()
            frame += 1
            thread.join(0.1)
    finally:
        port.screen.timeout(1000)
    success, value = outcome.get()
    if not success:
        raise cast(BaseException, value)
    return cast(T, value)
