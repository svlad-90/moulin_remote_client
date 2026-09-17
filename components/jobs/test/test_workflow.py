from __future__ import annotations

import unittest
from typing import Any

from components.jobs.api import workflow


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, str, list[list[str]]]] = []
        self.start_next_command: Any = None

    def start_commands(self, port: Any, title: str, commands: list[list[str]], *, start_next_command: Any) -> int:
        self.calls.append((port, title, commands))
        self.start_next_command = start_next_command
        return 0


class FakeLifecycle:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any, Any]] = []

    def finish_job(self, port: Any, job: dict[str, Any] | None = None) -> None:
        self.calls.append(("finish", port, job))

    def start_next_command(self, port: Any, job: dict[str, Any] | None = None) -> None:
        self.calls.append(("start-next", port, job))

    def poll_jobs(self, port: Any) -> None:
        self.calls.append(("poll-jobs", port, None))

    def poll_job(self, port: Any, job: dict[str, Any] | None = None) -> None:
        self.calls.append(("poll-job", port, job))


class CommandWorkflowServiceTests(unittest.TestCase):
    def test_run_commands_starts_runner_and_routes_next_step_to_lifecycle(self) -> None:
        runner = FakeRunner()
        lifecycle = FakeLifecycle()
        service = workflow.command_workflow_service(runner=runner, lifecycle=lifecycle)
        port = object()
        job = {"title": "Build"}

        rc = service.run_commands(port, "Build", [["ninja"]])
        runner.start_next_command(job)

        self.assertEqual(rc, 0)
        self.assertEqual(runner.calls, [(port, "Build", [["ninja"]])])
        self.assertEqual(lifecycle.calls, [("start-next", port, job)])

    def test_lifecycle_methods_delegate_to_lifecycle_service(self) -> None:
        runner = FakeRunner()
        lifecycle = FakeLifecycle()
        service = workflow.command_workflow_service(runner=runner, lifecycle=lifecycle)
        port = object()
        job = {"title": "Build"}

        service.finish_job(port, job)
        service.start_next_command(port, job)
        service.poll_jobs(port)
        service.poll_job(port, job)

        self.assertEqual(
            lifecycle.calls,
            [
                ("finish", port, job),
                ("start-next", port, job),
                ("poll-jobs", port, None),
                ("poll-job", port, job),
            ],
        )

    def test_run_build_command_builds_sequence_before_starting_job(self) -> None:
        runner = FakeRunner()
        lifecycle = FakeLifecycle()
        service = workflow.command_workflow_service(runner=runner, lifecycle=lifecycle)
        port = object()
        config = {"project": "prod"}
        sequence_calls: list[dict[str, Any]] = []

        def build_sequence(
            received_config: dict[str, Any],
            build_command: list[str],
            *,
            parameters: dict[str, str],
            targets: str,
            docker_image: str,
        ) -> list[list[str]]:
            sequence_calls.append(
                {
                    "config": received_config,
                    "build_command": build_command,
                    "parameters": parameters,
                    "targets": targets,
                    "docker_image": docker_image,
                }
            )
            return [["save-build-settings"], ["ninja", "full_ufs.img.gz"]]

        rc = service.run_build_command(
            port,
            "Run product build",
            ["ninja"],
            config=config,
            parameters={"ENABLE_ANDROID": "yes"},
            targets="full_ufs.img.gz",
            docker_image="image",
            build_command_sequence=build_sequence,
        )

        self.assertEqual(rc, 0)
        self.assertEqual(
            runner.calls,
            [(port, "Run product build", [["save-build-settings"], ["ninja", "full_ufs.img.gz"]])],
        )
        self.assertEqual(sequence_calls[0]["config"], config)
        self.assertEqual(sequence_calls[0]["build_command"], ["ninja"])
        self.assertEqual(sequence_calls[0]["parameters"], {"ENABLE_ANDROID": "yes"})
        self.assertEqual(sequence_calls[0]["targets"], "full_ufs.img.gz")
        self.assertEqual(sequence_calls[0]["docker_image"], "image")


if __name__ == "__main__":
    unittest.main()
