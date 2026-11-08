from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from components.app.api import ui


class FakePort:
    def __init__(self) -> None:
        self.config: dict[str, Any] = {}
        self.show_message = Mock()
        self.refresh_mapping_selection_cache = Mock()
        self.read_mapping_selection_cache = Mock(return_value=["mapping"])
        self.apply_mapping_selection_cache = Mock()
        self.notify_job_state_changed = Mock()
        self.menu_dirty = False
        self.main_full_redraw = False
        self.status = ""


class AppUiControllerTests(unittest.TestCase):
    def make_controller(self, app_dir: Path) -> ui.AppUiController:
        return ui.app_ui_controller(
            app_dir=app_dir,
            default_config_path=app_dir / "config.json",
            default_dockerfile="doc/Dockerfile",
            default_moulin_manifest="product.yaml",
            flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
            xt_imager_tool=app_dir / "xt-imager.py",
            remote_read_project_file=Mock(),
            manifest_cache={},
            env={"MOULIN_REMOTE_AUTO_CONNECT": "1"},
            confirm_action=Mock(return_value=True),
        )

    def test_build_items_owns_main_menu_construction(self) -> None:
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

    def test_run_key_draw_and_action_execution_are_ui_use_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            confirm_action = Mock(return_value=True)
            controller = ui.app_ui_controller(
                app_dir=Path(tmpdir),
                default_config_path=Path(tmpdir) / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=Path(tmpdir) / "flash_bootloaders.py",
                xt_imager_tool=Path(tmpdir) / "xt-imager.py",
                remote_read_project_file=Mock(),
                manifest_cache={},
                env={"MOULIN_REMOTE_AUTO_CONNECT": "1"},
                confirm_action=confirm_action,
            )
            port = FakePort()
            run_loop = Mock()
            key_controller = Mock()
            draw_controller = Mock()
            action_controller = Mock()

            with (
                patch("components.app.src.ui.ui_main_run_loop.main_run_loop_controller", return_value=run_loop) as run_factory,
                patch("components.app.src.ui.ui_main_keys.main_key_controller", return_value=key_controller),
                patch("components.app.src.ui.ui_main_draw.main_draw_controller", return_value=draw_controller),
                patch("components.app.src.ui.ui_action_execution.action_execution_controller", return_value=action_controller) as action_factory,
            ):
                controller.run(port)
                controller.handle_main_key(port, 10)
                controller.draw(port)
                controller.run_selected(port)

            run_factory.assert_called_once_with(auto_connect_enabled=True)
            run_loop.run.assert_called_once_with(port)
            key_controller.handle_key.assert_called_once_with(port, 10)
            draw_controller.draw.assert_called_once_with(port)
            action_factory.assert_called_once()
            action_controller.run_selected.assert_called_once_with(port)

            confirm_dialog = action_factory.call_args.kwargs["confirm_dialog"]
            self.assertTrue(confirm_dialog("content"))
            confirm_action.assert_called_once_with(port, "content")
            action_factory.call_args.kwargs["show_message"]("Title", ["line"])
            port.show_message.assert_called_once_with("Title", ["line"])
            action_factory.call_args.kwargs["schedule_refresh_after_action"]()
            task = port.mapping_selection_refresh_task
            task["thread"].join(timeout=1)
            controller.poll_mapping_selection_refresh(port)
            port.read_mapping_selection_cache.assert_called_once_with({})
            port.apply_mapping_selection_cache.assert_called_once_with(["mapping"])
            self.assertTrue(port.menu_dirty)
            self.assertTrue(port.main_full_redraw)

    def test_mapping_refresh_returns_before_background_read_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            controller = self.make_controller(Path(tmpdir))
            port = FakePort()
            release = threading.Event()

            def delayed_read(_config: dict[str, Any]) -> list[str]:
                release.wait(timeout=1)
                return ["updated"]

            port.read_mapping_selection_cache.side_effect = delayed_read

            controller.schedule_mapping_selection_refresh(port)

            task = port.mapping_selection_refresh_task
            self.assertTrue(task["thread"].is_alive())
            self.assertFalse(port.menu_dirty)
            port.apply_mapping_selection_cache.assert_not_called()

            release.set()
            task["thread"].join(timeout=1)
            controller.poll_mapping_selection_refresh(port)

            port.apply_mapping_selection_cache.assert_called_once_with(["updated"])
            self.assertTrue(port.menu_dirty)
            port.notify_job_state_changed.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
