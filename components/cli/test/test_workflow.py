from __future__ import annotations

import argparse
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from components.cli.api import workflow


def make_controller(command: str, *, names: list[str] | None = None) -> workflow.CliWorkflowController:
    namespace = argparse.Namespace(config=Path("config.json"), command=command)
    if names is not None:
        namespace.names = names
    return workflow.CliWorkflowController(
        description="desc",
        default_config=Path("config.json"),
        app_dir=Path("/app"),
        default_dockerfile="doc/Dockerfile",
        default_moulin_manifest="product.yaml",
        parse_args=Mock(return_value=namespace),
        load_config=Mock(return_value={"loaded": True}),
        run_curses_app=Mock(),
        app_factory=Mock(),
        curses_wrapper=Mock(),
        remote_runtime_context=Mock(return_value={"ctx": True}),
        run_command=Mock(),
        capture_command=Mock(return_value="inventory"),
        read_input=Mock(return_value=""),
        write_line=Mock(),
        save_config=Mock(),
    )


class CliWorkflowControllerTests(unittest.TestCase):
    def test_tui_command_loads_config_and_runs_curses_app(self) -> None:
        controller = make_controller("tui")

        self.assertEqual(controller.run(["tui"]), 0)

        controller.parse_args.assert_called_once_with(["tui"], description="desc", default_config=Path("config.json"))
        controller.load_config.assert_called_once_with(Path("config.json"))
        controller.run_curses_app.assert_called_once_with(
            {"loaded": True},
            app_factory=controller.app_factory,
            wrapper=controller.curses_wrapper,
        )

    def test_remote_command_routes_to_remote_component(self) -> None:
        controller = make_controller("remote-status")
        controller.remote_command_workflow.structured_script = Mock(return_value="script")  # type: ignore[method-assign]

        with patch.object(controller.remote_command_workflow, "run_cli_command") as run_remote:
            self.assertEqual(controller.run(["remote-status"]), 0)

        run_remote.assert_called_once()
        args, kwargs = run_remote.call_args
        self.assertEqual(args[:2], ({"loaded": True}, "remote-status"))
        self.assertEqual(kwargs["runtime_context"](), {"ctx": True})
        self.assertEqual(kwargs["structured_script"](["step"]), "script")

    def test_project_command_routes_to_project_component(self) -> None:
        controller = make_controller("mappings")

        controller.remote_runtime_context.return_value = {"docker_image": "prod-image"}
        controller.remote_command_workflow.structured_script = Mock(return_value="script")  # type: ignore[method-assign]

        with patch.object(controller.project_cli_workflow, "run_cli_project_command_for_config") as run_project:
            self.assertEqual(controller.run(["mappings"]), 0)
            run_project.assert_called_once()
            args, kwargs = run_project.call_args
            self.assertEqual(args[:2], ({"loaded": True}, "mappings"))
            self.assertEqual(kwargs["app_dir"], Path("/app"))
            self.assertEqual(kwargs["docker_image"], "prod-image")
            self.assertEqual(kwargs["structured_script"](["step"]), "script")
            self.assertEqual(kwargs["capture_command"](["fetch"]), "inventory")

        kwargs["local_runner"](["cmd"])
        controller.run_command.assert_called_with(["cmd"], check=False)

    def test_sync_command_routes_to_sync_component_with_names(self) -> None:
        controller = make_controller("pull-map", names=["one", "two"])

        with patch.object(controller.sync_command_workflow, "run_cli_command") as run_sync:
            self.assertEqual(controller.run(["pull-map", "one", "two"]), 0)

        run_sync.assert_called_once_with(
            {"loaded": True},
            "pull-map",
            ["one", "two"],
            runner=controller.run_command,
            write_line=controller.write_line,
        )


if __name__ == "__main__":
    unittest.main()
