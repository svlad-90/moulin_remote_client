from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from components.app.api import services


class FakeScreen:
    def __init__(self) -> None:
        self.timeouts: list[int] = []

    def timeout(self, value: int) -> None:
        self.timeouts.append(value)


class FakePort:
    def __init__(self) -> None:
        self.config: dict[str, Any] = {}
        self.docker_image = "image"
        self.screen = FakeScreen()
        self.show_message = Mock()
        self.refresh_mapping_selection_cache = Mock()
        self.confirm_sync_action = Mock(return_value=True)
        self.load_active_project_runtime = Mock()
        self.draw = Mock()
        self.suspend_tui = Mock()
        self.restore_tui = Mock()


class FakeJobSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any, Any]] = []

    def stop_running_preview(self, port: Any, slot: str | None = None) -> str:
        self.calls.append(("preview", port, slot))
        return "preview"

    def stop_running_command(self, port: Any, slot: str | None = None) -> None:
        self.calls.append(("stop", port, slot))

    def command_workflow_service(self, port: Any) -> str:
        self.calls.append(("command", port, None))
        return "command-workflow"


class FakeDialogWorkflow:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any, Any]] = []

    def run_confirm_dialog(self, port: Any, content: Any) -> bool:
        self.calls.append(("confirm", port, content))
        return True

    def confirm_sync_action(self, port: Any, label: str, description: str) -> bool:
        self.calls.append(("sync", port, (label, description)))
        return True

    def wait_message(self, port: Any, message: str) -> None:
        self.calls.append(("wait", port, message))

    def show_message(self, port: Any, title: str, lines: list[str]) -> None:
        self.calls.append(("show", port, (title, lines)))

    def prompt(self, port: Any, label: str, current: str) -> str:
        self.calls.append(("prompt", port, (label, current)))
        return "value"


class AppServicesControllerTests(unittest.TestCase):
    def make_controller(self, app_dir: Path) -> services.AppServicesController:
        return services.app_services_controller(
            app_dir=app_dir,
            default_config_path=app_dir / "config.json",
            default_dockerfile="doc/Dockerfile",
            default_moulin_manifest="product.yaml",
            default_build_targets="target",
            flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
            xt_imager_tool=app_dir / "xt-imager.py",
            remote_read_project_file=Mock(),
            manifest_cache={},
            save_config=Mock(),
            env={"MOULIN_REMOTE_AUTO_CONNECT": "1"},
            read_input=Mock(return_value=""),
            write_line=Mock(),
            subprocess_call=Mock(return_value=0),
        )

    def test_build_items_delegates_to_main_menu_builder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            controller = self.make_controller(app_dir)
            port = FakePort()
            menu_builder = Mock()
            menu_builder.build_items.return_value = ["item"]

            with patch("components.app.src.ui.main_menu_items.main_menu_builder", return_value=menu_builder) as builder_factory:
                result = controller.build_items(port)

            builder_factory.assert_called_once()
            self.assertEqual(builder_factory.call_args.kwargs["app_dir"], app_dir)
            menu_builder.build_items.assert_called_once_with(port)
            self.assertEqual(result, ["item"])

    def test_run_and_draw_delegate_to_ui_controllers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            controller = self.make_controller(Path(tmpdir))
            port = FakePort()
            run_loop = Mock()
            draw_controller = Mock()

            with (
                patch("components.app.src.ui.ui_main_run_loop.main_run_loop_controller", return_value=run_loop) as run_factory,
                patch("components.app.src.ui.ui_main_draw.main_draw_controller", return_value=draw_controller) as draw_factory,
            ):
                controller.run(port)
                controller.draw(port)

            run_factory.assert_called_once_with(auto_connect_enabled=True)
            run_loop.run.assert_called_once_with(port)
            draw_factory.assert_called_once_with(app_dir=Path(tmpdir))
            draw_controller.draw.assert_called_once_with(port)

    def test_job_session_and_command_workflow_are_composed_in_services_layer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            controller = self.make_controller(Path(tmpdir))
            port = FakePort()
            session = FakeJobSession()

            with patch("components.app.src.jobs.job_session.job_session_controller", return_value=session) as session_factory:
                self.assertEqual(controller.stop_running_preview(port, "build"), "preview")
                controller.stop_running_command(port, "board")
                self.assertEqual(controller.command_workflow_service(port), "command-workflow")

            self.assertEqual(
                session.calls,
                [("preview", port, "build"), ("stop", port, "board"), ("command", port, None)],
            )
            session_factory.assert_called()
            self.assertEqual(session_factory.call_args.kwargs["docker_image"], "image")

    def test_config_sync_terminal_and_dialog_workflows_are_wired(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            controller = self.make_controller(app_dir)
            port = FakePort()
            config_controller = Mock()
            config_controller.remote_project_config_ready.return_value = True
            sync_controller = Mock()
            terminal_controller = Mock()
            dialog = FakeDialogWorkflow()

            with (
                patch("components.app.src.workflows.config_workflow.config_workflow_controller", return_value=config_controller) as config_factory,
                patch("components.app.src.workflows.sync_workflow.sync_workflow_controller", return_value=sync_controller) as sync_factory,
                patch("components.app.src.workflows.local_terminal_session.terminal_session_controller", return_value=terminal_controller) as terminal_factory,
                patch.object(controller.workflows, "dialog_workflow_controller", return_value=dialog),
            ):
                self.assertTrue(controller.remote_project_config_ready(port))
                controller.run_sync_screen(port)
                self.assertIs(controller.terminal_session_controller(port), terminal_controller)
                self.assertTrue(controller.confirm_sync_action(port, "Sync", "desc"))
                controller.wait_message(port, "wait")
                controller.show_message(port, "Title", ["line"])
                self.assertEqual(controller.prompt(port, "Field", "old"), "value")

            config_factory.assert_called_once()
            self.assertEqual(config_factory.call_args.kwargs["default_build_targets"], "target")
            sync_factory.assert_called_once()
            sync_controller.run_sync_screen.assert_called_once_with(port)
            terminal_factory.assert_called_once()
            self.assertEqual(dialog.calls[-4:], [
                ("sync", port, ("Sync", "desc")),
                ("wait", port, "wait"),
                ("show", port, ("Title", ["line"])),
                ("prompt", port, ("Field", "old")),
            ])


if __name__ == "__main__":
    unittest.main()
