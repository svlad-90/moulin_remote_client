from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from components.app.api import bootstrap


class AppBootstrapControllerTests(unittest.TestCase):
    def make_settings(self, app_dir: Path) -> bootstrap.AppBootstrapSettings:
        return bootstrap.AppBootstrapSettings(
            app_dir=app_dir,
            default_config=app_dir / "config.json",
            default_config_example=app_dir / "config.example.json",
            default_docker_image="image",
            default_dockerfile="doc/Dockerfile",
            default_build_targets="target",
            default_moulin_manifest="product.yaml",
            flash_bootloaders_tool=app_dir / "flash.py",
            xt_imager_tool=app_dir / "imager.py",
            profile_slow_ms=20.0,
        )

    def make_controller(self, app_dir: Path) -> bootstrap.AppBootstrapController:
        return bootstrap.app_bootstrap_controller(
            self.make_settings(app_dir),
            env={"ENV": "1"},
            manifest_cache={},
            curses_wrapper=Mock(),
            capture_command=Mock(return_value="out"),
            run_command=Mock(),
            read_input=Mock(return_value=""),
            write_line=Mock(),
            monotonic=Mock(return_value=1.0),
        )

    def test_load_and_save_config_use_runtime_component(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            controller = self.make_controller(app_dir)
            config = {"loaded": True}

            with (
                patch("components.app.src.bootstrap.config_runtime.load_runtime_config_for_env", return_value=config) as load_config,
                patch("components.app.src.bootstrap.config_runtime.save_runtime_config") as save_config,
            ):
                self.assertIs(controller.load_config(app_dir / "custom.json"), config)
                controller.save_config(config)

            load_config.assert_called_once_with(
                app_dir / "custom.json",
                example_path=app_dir / "config.example.json",
                app_dir=app_dir,
                env={"ENV": "1"},
                default_build_targets="target",
                default_moulin_manifest="product.yaml",
                default_dockerfile="doc/Dockerfile",
            )
            save_config.assert_called_once_with(config, default_path=app_dir / "config.json")

    def test_cli_runtime_context_uses_moulin_component(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            controller = self.make_controller(app_dir)

            with patch("components.app.src.bootstrap.moulin_manifest.build_runtime_context_for_config", return_value={"ctx": True}) as runtime_context:
                self.assertEqual(controller.cli_runtime_context({"config": True}), {"ctx": True})

            runtime_context.assert_called_once()
            self.assertEqual(runtime_context.call_args.kwargs["app_dir"], app_dir)
            self.assertEqual(runtime_context.call_args.kwargs["default_docker_image"], "image")
            self.assertIs(runtime_context.call_args.kwargs["remote_read_project_file"], controller.remote_project_file_reader)

    def test_client_app_class_binds_client_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            controller = self.make_controller(app_dir)
            bound_class = type("Bound", (), {})

            with patch("components.app.src.bootstrap.app_client.client_app_class", return_value=bound_class) as class_factory:
                self.assertIs(controller.client_app_class(), bound_class)

            deps = class_factory.call_args.args[0]
            self.assertEqual(deps.app_dir, app_dir)
            self.assertEqual(deps.default_config_path, app_dir / "config.json")
            self.assertIs(deps.remote_read_project_file, controller.remote_project_file_reader)
            self.assertIs(deps.load_config, controller.load_config)
            self.assertIs(deps.save_config, controller.save_config)
            self.assertEqual(deps.profile_slow_ms, 20.0)

    def test_run_builds_cli_workflow_and_runs_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            controller = self.make_controller(app_dir)
            cli = Mock()
            cli.run.return_value = 7
            client_class = type("Client", (), {})

            with (
                patch.object(controller, "client_app_class", return_value=client_class),
                patch("components.app.src.bootstrap.cli_workflow.cli_workflow_controller", return_value=cli) as workflow_factory,
            ):
                self.assertEqual(controller.run(["tui"], description="desc"), 7)

            workflow_factory.assert_called_once()
            kwargs = workflow_factory.call_args.kwargs
            self.assertEqual(kwargs["description"], "desc")
            self.assertEqual(kwargs["default_config"], app_dir / "config.json")
            self.assertIs(kwargs["app_factory"], client_class)
            self.assertIs(kwargs["remote_runtime_context"].__self__, controller)
            self.assertEqual(kwargs["remote_runtime_context"].__name__, "cli_runtime_context")
            cli.run.assert_called_once_with(["tui"])


if __name__ == "__main__":
    unittest.main()
