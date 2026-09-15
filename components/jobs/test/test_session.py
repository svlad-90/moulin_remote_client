from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import Mock, patch

from components.jobs.api import session


class FakeCommandControl:
    def __init__(self) -> None:
        self.preview_calls: list[tuple[Any, str | None]] = []
        self.stop_calls: list[tuple[Any, str | None]] = []

    def stop_running_preview(self, port: Any, slot: str | None = None) -> str:
        self.preview_calls.append((port, slot))
        return "preview"

    def stop_running_command(self, port: Any, slot: str | None = None) -> None:
        self.stop_calls.append((port, slot))


class FakeCommandWorkflow:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any, Any]] = []

    def finish_job(self, port: Any, job: Any = None) -> None:
        self.calls.append(("finish", port, job))

    def start_next_command(self, port: Any, job: Any = None) -> None:
        self.calls.append(("next", port, job))

    def poll_jobs(self, port: Any) -> None:
        self.calls.append(("poll-jobs", port, None))

    def poll_job(self, port: Any, job: Any = None) -> None:
        self.calls.append(("poll-job", port, job))


class FakeConnectionWorkflow:
    def __init__(self) -> None:
        self.pending_calls: list[Any] = []

    def start_pending_auto_board_connect(self, port: Any) -> bool:
        self.pending_calls.append(port)
        return True


class JobSessionControllerTests(unittest.TestCase):
    def make_controller(self) -> session.JobSessionController:
        return session.job_session_controller(
            {},
            docker_image="image",
            terminate_process_group=Mock(),
            display_command=Mock(return_value="cmd"),
            display_command_lines=Mock(return_value=["cmd"]),
            format_preflight=Mock(return_value=("ok", {})),
            confirm_dialog=Mock(return_value=True),
            draw=Mock(),
        )

    def test_stop_use_cases_delegate_to_command_control_service(self) -> None:
        controller = self.make_controller()
        control = FakeCommandControl()
        port = object()

        with patch("components.jobs.src.session.job_command_control_api.command_control_service", return_value=control):
            self.assertEqual(controller.stop_running_preview(port, "build"), "preview")
            controller.stop_running_command(port, "board")

        self.assertEqual(control.preview_calls, [(port, "build")])
        self.assertEqual(control.stop_calls, [(port, "board")])

    def test_job_lifecycle_methods_delegate_to_command_workflow_service(self) -> None:
        controller = self.make_controller()
        workflow = FakeCommandWorkflow()
        port = object()
        job = {"title": "Build"}

        with patch.object(controller, "command_workflow_service", return_value=workflow):
            controller.finish_active_job(port, job)
            controller.start_next_active_job_command(port, job)
            controller.poll_active_jobs(port)
            controller.poll_active_job(port, job)

        self.assertEqual(
            workflow.calls,
            [
                ("finish", port, job),
                ("next", port, job),
                ("poll-jobs", port, None),
                ("poll-job", port, job),
            ],
        )

    def test_command_workflow_wires_pending_board_connect_callback(self) -> None:
        controller = self.make_controller()
        port = object()
        lifecycle = object()
        runner = object()
        command_workflow = object()
        connection_workflow = FakeConnectionWorkflow()

        with (
            patch("components.jobs.src.session.job_command_runner_api.command_runner_service", return_value=runner),
            patch("components.jobs.src.session.job_command_lifecycle_api.command_lifecycle_service", return_value=lifecycle) as lifecycle_factory,
            patch("components.jobs.src.session.job_workflow_api.command_workflow_service", return_value=command_workflow) as workflow_factory,
            patch.object(controller, "connection_workflow_service", return_value=connection_workflow),
        ):
            result = controller.command_workflow_service(port)
            callback = lifecycle_factory.call_args.kwargs["start_pending_auto_board_connect"]
            self.assertTrue(callback(port))

        self.assertIs(result, command_workflow)
        workflow_factory.assert_called_once_with(runner=runner, lifecycle=lifecycle)
        self.assertEqual(connection_workflow.pending_calls, [port])

    def test_connection_workflow_wires_start_next_command_callback(self) -> None:
        controller = self.make_controller()
        port = object()
        command_workflow = FakeCommandWorkflow()
        connection_workflow = object()

        with (
            patch("components.jobs.src.session.job_connection_workflow_api.connection_workflow_service", return_value=connection_workflow) as connection_factory,
            patch.object(controller, "command_workflow_service", return_value=command_workflow),
        ):
            result = controller.connection_workflow_service(port)
            callback = connection_factory.call_args.kwargs["start_next_command"]
            job = {"title": "Connect"}
            callback(port, job)

        self.assertIs(result, connection_workflow)
        self.assertEqual(command_workflow.calls, [("next", port, job)])


if __name__ == "__main__":
    unittest.main()
