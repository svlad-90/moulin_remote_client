from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any

from components.jobs.api import connection


@dataclass
class FakeMenuItem:
    label: str


class FakeConnectionPort:
    def __init__(self) -> None:
        self.items = [
            FakeMenuItem("Connect build host"),
            FakeMenuItem("Connect board host"),
        ]
        self.status = ""
        self.action_running = False
        self.active_job: dict[str, Any] | None = None
        self.board_job: dict[str, Any] | None = None
        self.connection_state = "disconnected"
        self.board_connection_state = "disconnected"
        self.menu_dirty = False
        self.main_full_redraw = False
        self.logs_dirty = False


class FakeRemoteProjectService:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], str]] = []

    def preflight_command_for_config(self, config: dict[str, Any], docker_image: str) -> list[str]:
        self.calls.append((config, docker_image))
        return ["ssh", "build", "preflight"]


class FakeBoardSessionService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def connect_command_for_config(self, config: dict[str, Any]) -> list[str]:
        self.calls.append(config)
        return ["ssh", "board", "connect"]


def config() -> dict[str, Any]:
    return {
        "remote": {"user": "builder", "host": "10.0.0.1"},
        "board_host": {"user": "tester", "host": "10.0.0.2"},
    }


class ConnectionJobControllerTests(unittest.TestCase):
    def test_start_build_host_connect_creates_job_and_applies_session_state(self) -> None:
        port = FakeConnectionPort()
        started: list[dict[str, Any]] = []
        remote_service = FakeRemoteProjectService()
        cfg = config()
        controller = connection.ConnectionJobController(
            cfg,
            docker_image="builder:latest",
            now=lambda: 12.5,
            remote_project_service=remote_service,
        )

        controller.start_build_host_connect(port, start_next_command=started.append)

        self.assertIs(port.active_job, started[0])
        self.assertEqual(port.active_job["kind"], "connect")
        self.assertEqual(port.active_job["item_label"], "Connect build host")
        self.assertEqual(port.active_job["commands"], [["ssh", "build", "preflight"]])
        self.assertEqual(port.active_job["started_at"], 12.5)
        self.assertEqual(remote_service.calls, [(cfg, "builder:latest")])
        self.assertEqual(port.connection_state, "connecting")
        self.assertEqual(port.status, "Connecting...")
        self.assertTrue(port.logs_dirty)

    def test_start_board_host_connect_creates_board_job_and_applies_session_state(self) -> None:
        port = FakeConnectionPort()
        started: list[dict[str, Any]] = []
        board_service = FakeBoardSessionService()
        cfg = config()
        controller = connection.ConnectionJobController(
            cfg,
            docker_image="builder:latest",
            now=lambda: 13.5,
            board_session_service=board_service,
        )

        controller.start_board_host_connect(port, start_next_command=started.append)

        self.assertIs(port.board_job, started[0])
        self.assertEqual(port.board_job["kind"], "board-connect")
        self.assertEqual(port.board_job["item_label"], "Connect board host")
        self.assertEqual(port.board_job["commands"], [["ssh", "board", "connect"]])
        self.assertEqual(port.board_job["started_at"], 13.5)
        self.assertEqual(board_service.calls, [cfg])
        self.assertEqual(port.board_connection_state, "connecting")
        self.assertEqual(port.status, "Connecting board host...")
        self.assertTrue(port.logs_dirty)

    def test_start_build_host_connect_reports_busy_action(self) -> None:
        port = FakeConnectionPort()
        port.action_running = True
        controller = connection.ConnectionJobController(config(), docker_image="builder:latest")

        controller.start_build_host_connect(port, start_next_command=lambda _job: None)

        self.assertIsNone(port.active_job)
        self.assertEqual(port.status, "Another action is already running")

    def test_start_board_host_connect_reports_busy_board_slot(self) -> None:
        port = FakeConnectionPort()
        port.board_job = {"title": "Flash UFS image"}
        controller = connection.ConnectionJobController(config(), docker_image="builder:latest")

        controller.start_board_host_connect(port, start_next_command=lambda _job: None)

        self.assertEqual(port.board_job, {"title": "Flash UFS image"})
        self.assertEqual(port.status, "Another board action is already running")


if __name__ == "__main__":
    unittest.main()
