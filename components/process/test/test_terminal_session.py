from __future__ import annotations

import unittest
from typing import Any

from components.process.api import terminal_session


class FakePort:
    def __init__(self) -> None:
        self.status = ""
        self.last_exit: int | None = None


def config() -> dict[str, Any]:
    return {
        "remote": {
            "name": "build",
            "user": "builder",
            "host": "10.0.0.1",
            "project_dir": "/mnt/projects/prod",
        },
        "board_host": {"name": "board", "user": "tester", "host": "10.0.0.2"},
        "active_project": "prod",
        "projects": [{"name": "prod", "project_dir": "prod"}],
    }


class Harness:
    def __init__(self, *, remote_rc: int = 0, board_rc: int = 0) -> None:
        self.events: list[str] = []
        self.lines: list[str] = []
        self.prompts: list[str] = []
        self.controller = terminal_session.terminal_session_controller(
            config(),
            suspend_tui=lambda: self.events.append("suspend"),
            restore_tui=lambda: self.events.append("restore"),
            read_input=self.read_input,
            write_line=self.write_line,
            run_remote_shell=lambda: self.run_shell("remote", remote_rc),
            run_board_shell=lambda: self.run_shell("board", board_rc),
        )

    def write_line(self, *values: Any) -> None:
        self.lines.append(" ".join(str(value) for value in values))

    def read_input(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return ""

    def run_shell(self, name: str, rc: int) -> int:
        self.events.append(f"run:{name}")
        return rc


class TerminalSessionControllerTests(unittest.TestCase):
    def test_open_remote_shell_suspends_tui_runs_shell_and_restores(self) -> None:
        port = FakePort()
        harness = Harness(remote_rc=7)

        harness.controller.open_remote_shell(port)

        self.assertEqual(harness.events, ["suspend", "run:remote", "restore"])
        self.assertEqual(port.last_exit, 7)
        self.assertEqual(port.status, "Remote shell closed: exit 7")
        self.assertIn("Moulin build host shell", harness.lines)
        self.assertIn("Shell exited. Press Enter to return to Moulin client...", harness.prompts)

    def test_open_board_shell_suspends_tui_runs_shell_and_restores(self) -> None:
        port = FakePort()
        harness = Harness(board_rc=3)

        harness.controller.open_board_shell(port)

        self.assertEqual(harness.events, ["suspend", "run:board", "restore"])
        self.assertEqual(port.last_exit, 3)
        self.assertEqual(port.status, "Board host shell closed: exit 3")
        self.assertIn("Moulin board host shell", harness.lines)

    def test_run_local_callable_reports_system_exit_and_restores_tui(self) -> None:
        port = FakePort()
        harness = Harness()

        harness.controller.run_local_callable(port, "Local task", lambda: (_ for _ in ()).throw(SystemExit("failed")))

        self.assertEqual(harness.events, ["suspend", "restore"])
        self.assertEqual(port.last_exit, 1)
        self.assertEqual(port.status, "Local task: failed")
        self.assertIn("failed", harness.lines)


if __name__ == "__main__":
    unittest.main()
