from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any

from components.jobs.api import connection_workflow


@dataclass
class FakeMenuItem:
    label: str


class FakeConnectionWorkflowPort:
    def __init__(self) -> None:
        self.items = [FakeMenuItem("Connect build host"), FakeMenuItem("Connect board host")]
        self.status = ""
        self.action_running = False
        self.active_job: dict[str, Any] | None = None
        self.board_job: dict[str, Any] | None = None
        self.connection_state = "disconnected"
        self.board_connection_state = "disconnected"
        self.auto_connect_done = False
        self.pending_auto_board_connect = False
        self.menu_dirty = False
        self.main_full_redraw = False
        self.logs_dirty = False


def config() -> dict[str, Any]:
    return {
        "remote": {"name": "build", "user": "builder", "host": "10.0.0.1"},
        "board_host": {"name": "board", "user": "tester", "host": "10.0.0.2"},
    }


class ConnectionWorkflowServiceTests(unittest.TestCase):
    def test_toggle_build_host_starts_connection_job(self) -> None:
        started: list[tuple[Any, dict[str, Any]]] = []
        port = FakeConnectionWorkflowPort()
        service = connection_workflow.connection_workflow_service(
            config(),
            docker_image="builder:latest",
            confirm_dialog=lambda _content: True,
            draw=lambda: None,
            start_next_command=lambda port, job: started.append((port, job)),
        )

        service.toggle_build_host(port)

        self.assertIs(port.active_job, started[0][1])
        self.assertIs(port, started[0][0])
        self.assertEqual(port.active_job["kind"], "connect")
        self.assertEqual(port.connection_state, "connecting")

    def test_auto_connect_marks_board_pending_and_starts_build(self) -> None:
        started: list[dict[str, Any]] = []
        port = FakeConnectionWorkflowPort()
        service = connection_workflow.connection_workflow_service(
            config(),
            docker_image="builder:latest",
            confirm_dialog=lambda _content: True,
            draw=lambda: None,
            start_next_command=lambda _port, job: started.append(job),
        )

        service.auto_connect(port)

        self.assertTrue(port.auto_connect_done)
        self.assertTrue(port.pending_auto_board_connect)
        self.assertEqual(started[0]["kind"], "connect")

    def test_pending_auto_board_connect_starts_board_job(self) -> None:
        started: list[dict[str, Any]] = []
        port = FakeConnectionWorkflowPort()
        port.pending_auto_board_connect = True
        service = connection_workflow.connection_workflow_service(
            config(),
            docker_image="builder:latest",
            confirm_dialog=lambda _content: True,
            draw=lambda: None,
            start_next_command=lambda _port, job: started.append(job),
        )

        result = service.start_pending_auto_board_connect(port)

        self.assertTrue(result)
        self.assertFalse(port.pending_auto_board_connect)
        self.assertEqual(started[0]["kind"], "board-connect")


if __name__ == "__main__":
    unittest.main()
