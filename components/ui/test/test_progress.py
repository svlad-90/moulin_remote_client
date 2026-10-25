from __future__ import annotations

import time
import unittest

from components.ui.api.progress import ModalTaskCancelled, ProgressReporter, run_modal_task


class _Screen:
    def __init__(self) -> None:
        self.timeouts: list[int] = []

    def timeout(self, value: int) -> None:
        self.timeouts.append(value)

    def erase(self) -> None:
        return None

    def getmaxyx(self) -> tuple[int, int]:
        return (24, 100)

    def refresh(self) -> None:
        return None


class _Port:
    def __init__(self, keys: list[int] | None = None) -> None:
        self.screen = _Screen()
        self.lines: list[str] = []
        self.keys = list(keys or [])

    def draw_box(self, *_args: object) -> None:
        return None

    def add(self, _row: int, _column: int, text: str, *_args: object) -> None:
        self.lines.append(text)

    def accent_attr(self) -> int:
        return 0

    def read_key(self) -> int:
        return self.keys.pop(0) if self.keys else -1


class ModalProgressTests(unittest.TestCase):
    def test_reports_worker_progress_while_waiting(self) -> None:
        port = _Port()

        def task(report: ProgressReporter) -> str:
            report(25, 100)
            time.sleep(0.12)
            return "done"

        result = run_modal_task(port, title="Inspect", detail="archive.tar.bz2", task=task)

        self.assertEqual(result, "done")
        self.assertTrue(any("25.0%" in line for line in port.lines))
        self.assertEqual(port.screen.timeouts, [0, 1000])

    def test_escape_cancels_worker_cooperatively(self) -> None:
        port = _Port([27])

        def task(report: ProgressReporter) -> None:
            for current in range(100):
                report(current, 100)
                time.sleep(0.01)

        with self.assertRaises(ModalTaskCancelled):
            run_modal_task(port, title="Inspect", detail="archive.tar.bz2", task=task)

        self.assertEqual(port.screen.timeouts, [0, 1000])


if __name__ == "__main__":
    unittest.main()
