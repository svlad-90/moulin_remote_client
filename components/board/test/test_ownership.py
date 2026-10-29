from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from components.board.src import ownership


class BoardOwnershipTests(unittest.TestCase):
    def test_parse_status_distinguishes_free_owned_and_busy_boards(self) -> None:
        self.assertEqual(
            ownership.parse_ownership_status(json.dumps({"owner": None, "user": "alice"}))["state"],
            "free",
        )
        self.assertEqual(
            ownership.parse_ownership_status(json.dumps({"owner": "host/alice", "user": "alice"}))["state"],
            "owned",
        )
        busy = ownership.parse_ownership_status(json.dumps({"owner": "host/bob", "user": "alice"}))
        self.assertEqual(busy["state"], "busy")
        self.assertIn("host/bob", busy["text"])

    def test_monitor_queries_configured_status_without_blocking_poll(self) -> None:
        commands: list[list[str]] = []

        def capture(argv: list[str], **_kwargs: object) -> str:
            commands.append(argv)
            return json.dumps({"owner": "testrpi5/alice", "user": "alice"})

        monitor = ownership.BoardOwnershipMonitor(capture_command=capture)
        port = SimpleNamespace(
            config={
                "board_hosts": [
                    {
                        "name": "lab",
                        "user": "alice",
                        "host": "lab.example",
                        "commands": {
                            "ownership_acquire": "acquire",
                            "ownership_release": "release",
                            "ownership_status": "status",
                        },
                    }
                ],
                "active_board_host": "lab",
            },
            board_connection_state="connected",
            board_job=None,
            last_board_job=None,
            board_ownership_identity="",
            board_ownership_status={"state": "unknown", "text": "unknown", "owner": ""},
            board_ownership_task=None,
            board_ownership_next_poll=0.0,
            board_ownership_last_job=None,
            menu_dirty=False,
            main_full_redraw=False,
            render_cache={},
        )

        monitor.poll(port)
        port.board_ownership_task["thread"].join(timeout=1)
        monitor.poll(port)

        self.assertEqual(port.board_ownership_status["state"], "owned")
        self.assertEqual(len(commands), 1)
        self.assertIn("status", commands[0][-1])


if __name__ == "__main__":
    unittest.main()
