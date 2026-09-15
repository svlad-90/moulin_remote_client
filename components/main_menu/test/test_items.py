from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from components.main_menu.api import items


class FakeWorkflow:
    def __init__(self) -> None:
        self.build_calls: list[dict[str, Any]] = []
        self.command_calls: list[tuple[str, list[list[str]]]] = []

    def run_build_command(self, _port: Any, title: str, command: list[str], **kwargs: Any) -> int:
        self.build_calls.append({"title": title, "command": command, **kwargs})
        return 0

    def run_commands(self, _port: Any, title: str, commands: list[list[str]]) -> int:
        self.command_calls.append((title, commands))
        return 0


class FakeTerminalSession:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def open_remote_shell(self, _port: Any) -> None:
        self.calls.append("remote")

    def open_board_shell(self, _port: Any) -> None:
        self.calls.append("board")


class FakeConfigWorkflow:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run_remote_configurations_screen(self, _port: Any) -> None:
        self.calls.append("remote")

    def run_board_host_configurations_screen(self, _port: Any) -> None:
        self.calls.append("board")

    def run_project_configurations_screen(self, _port: Any) -> None:
        self.calls.append("project")


class FakeApp:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.preflight_values: dict[str, str] = {}
        self.connection_state = "connected"
        self.board_connection_state = "connected"
        self.docker_image = "demo-image"
        self.build_params = {"ENABLE_ANDROID": "yes"}
        self.build_targets = "full_ufs.img.gz"
        self.board_artifacts = "full_ufs.img.gz"
        self.workflow = FakeWorkflow()
        self.terminal_session = FakeTerminalSession()
        self.config_workflow = FakeConfigWorkflow()

    def command_workflow_service(self) -> FakeWorkflow:
        return self.workflow

    def terminal_session_controller(self) -> FakeTerminalSession:
        return self.terminal_session

    def config_workflow_controller(self) -> FakeConfigWorkflow:
        return self.config_workflow

    def toggle_connection(self) -> None:
        return None

    def stop_running_preview(self, _slot: str) -> str:
        return "stop preview"

    def stop_running_command(self, _slot: str) -> None:
        return None

    def toggle_board_connection(self) -> None:
        return None

    def sync_screen(self) -> None:
        return None


def _config(app_dir: Path) -> dict[str, Any]:
    return {
        "inventory": {"mapping_selection": str(app_dir / "mapping-selection.txt")},
        "local": {"project_dir": str(app_dir / "overlay")},
        "active_remote": "build",
        "remotes": [
            {
                "name": "build",
                "user": "builder",
                "host": "10.0.0.1",
                "projects_dir": "/mnt/projects",
            }
        ],
        "active_board_host": "board",
        "board_hosts": [
            {
                "name": "board",
                "user": "tester",
                "host": "10.0.0.2",
                "work_dir": "/srv/tftp/vgon",
            }
        ],
        "active_project": "prod",
        "projects": [
            {
                "name": "prod",
                "project_dir": "meta-product",
                "local_project_dir": str(app_dir / "overlay"),
                "git_url": "https://example.invalid/prod.git",
                "git_ref": "main",
                "moulin_manifest": "product.yaml",
                "dockerfile": "doc/Dockerfile",
            }
        ],
    }


class MainMenuBuilderTests(unittest.TestCase):
    def test_build_items_includes_main_workflow_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: "",
                manifest_cache={},
            )

            self.assertIsInstance(builder.command_items, items.MainMenuCommandItemsService)
            self.assertIsInstance(builder.setup_items, items.MainMenuSetupItemsService)

            menu_items = builder.build_items(FakeApp(_config(app_dir)))

            labels = [item.label for item in menu_items]
            self.assertIn("Build host configuration", labels)
            self.assertIn("Run product build", labels)
            self.assertIn("Copy build artifacts", labels)
            self.assertIn("Sync mapped files", labels)

    def test_build_command_handler_uses_command_workflow_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: "",
                manifest_cache={},
            )
            app = FakeApp(_config(app_dir))
            menu_items = builder.build_items(app)
            build_item = next(item for item in menu_items if item.label == "Run product build")

            build_item.handler(app)

            self.assertEqual(app.workflow.build_calls[0]["title"], "Run product build")
            self.assertEqual(app.workflow.build_calls[0]["targets"], "full_ufs.img.gz")
            self.assertEqual(app.workflow.command_calls, [])

    def test_command_items_service_builds_board_command_handlers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: "",
                manifest_cache={},
            )
            app = FakeApp(_config(app_dir))
            command_items = builder.command_items.build_items()
            copy_item = next(item for item in command_items if item.label == "Copy build artifacts")

            copy_item.handler(app)

            self.assertEqual(app.workflow.command_calls[0][0], "Copy build artifacts")
            self.assertIn("Copy build artifacts", app.workflow.command_calls[0][1][0][2])

    def test_setup_items_service_adds_preflight_action_handlers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: "",
                manifest_cache={},
            )
            app = FakeApp(_config(app_dir))
            app.preflight_values = {"project": "missing", "origin": "mismatch", "ref": "mismatch"}
            setup_items = builder.setup_items.build_items(app)
            prepare_item = next(item for item in setup_items if item.label == "Prepare remote project")

            prepare_item.handler(app)

            self.assertEqual(app.workflow.command_calls[0][0], "Prepare remote project")
            self.assertIn("git clone", app.workflow.command_calls[0][1][0][-1])

    def test_shell_handlers_use_terminal_session_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: "",
                manifest_cache={},
            )
            app = FakeApp(_config(app_dir))
            menu_items = builder.build_items(app)

            next(item for item in menu_items if item.label == "Open build host shell").handler(app)
            next(item for item in menu_items if item.label == "Open board host shell").handler(app)

            self.assertEqual(app.terminal_session.calls, ["remote", "board"])


if __name__ == "__main__":
    unittest.main()
