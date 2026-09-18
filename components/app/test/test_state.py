from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from components.app.api import state


class FakePort:
    def __init__(self) -> None:
        self.config: dict[str, Any] = {
            "inventory": {"mapping_selection": "workspace/selected-mappings.txt"},
            "project": {"active_mappings": ["src"]},
        }
        self.render_cache: dict[str, Any] = {"details": "stale", "other": "keep"}
        self.done = False


class AppStateControllerTests(unittest.TestCase):
    def make_controller(
        self,
        app_dir: Path,
        *,
        env: dict[str, str] | None = None,
        monotonic_values: list[float] | None = None,
    ) -> state.AppStateController:
        values = list(monotonic_values or [10.0])

        def monotonic() -> float:
            if len(values) == 1:
                return values[0]
            return values.pop(0)

        return state.app_state_controller(
            app_dir=app_dir,
            env=env or {},
            default_docker_image="default-image",
            default_build_targets="default-target",
            default_moulin_manifest="product.yaml",
            remote_read_project_file=Mock(),
            manifest_cache={},
            profile_slow_ms=20.0,
            monotonic=monotonic,
        )

    def test_initialize_loads_runtime_mapping_cache_and_profile_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            port = FakePort()
            controller = self.make_controller(app_dir, env={"MOULIN_REMOTE_UI_PROFILE": "yes"})

            with patch(
                "components.app.src.state.moulin_manifest.build_runtime_context_for_config",
                return_value={
                    "docker_image": "image",
                    "build_params": {"A": "1"},
                    "build_targets": "target",
                    "board_artifacts": "artifact",
                },
            ) as runtime_factory, patch(
                "components.project.src.selection.ProjectMappingSelectionService.read_mapping_selection_for_config",
                return_value=["src"],
            ) as mapping_reader:
                controller.initialize(port)

            runtime_factory.assert_called_once()
            mapping_reader.assert_called_once_with(port.config, app_dir / "workspace" / "selected-mappings.txt", required=False)
            self.assertEqual(port.docker_image, "image")
            self.assertEqual(port.build_params, {"A": "1"})
            self.assertEqual(port.build_targets, "target")
            self.assertEqual(port.board_artifacts, "artifact")
            self.assertEqual(port.mapping_selection_cache, ["src"])
            self.assertNotIn("details", port.render_cache)
            self.assertEqual(port.render_cache["other"], "keep")
            self.assertTrue(port.ui_profile_enabled)
            self.assertIn("profile-start", port.ui_profile_buffer[0])
            self.assertIn("path=" + str(app_dir / "workspace" / "ui-profile.log"), port.ui_profile_buffer[0])

    def test_initialize_session_sets_current_client_session_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            port = FakePort()
            controller = self.make_controller(app_dir, env={"MOULIN_REMOTE_UI_PROFILE": "yes"})
            reset_calls: list[Any] = []

            with patch(
                "components.app.src.state.moulin_manifest.build_runtime_context_for_config",
                side_effect=AssertionError("session initialization must not read remote manifest"),
            ), patch(
                "components.project.src.selection.ProjectMappingSelectionService.read_mapping_selection_for_config",
                return_value=["src"],
            ):
                controller.initialize_session(
                    port,
                    build_items=lambda target: ["item:" + target.status],
                    reset_preflight=reset_calls.append,
                )

            self.assertEqual(reset_calls, [port])
            self.assertEqual(port.docker_image, "")
            self.assertEqual(port.build_params, {})
            self.assertEqual(port.build_targets, "default-target")
            self.assertEqual(port.board_artifacts, "default-target")
            self.assertEqual(port.connection_state, "disconnected")
            self.assertEqual(port.board_connection_state, "disconnected")
            self.assertFalse(port.auto_connect_done)
            self.assertFalse(port.pending_auto_board_connect)
            self.assertFalse(port.action_running)
            self.assertIsNone(port.active_job)
            self.assertIsNone(port.last_job)
            self.assertEqual(port.last_jobs_by_label, {})
            self.assertIsNone(port.board_job)
            self.assertIsNone(port.last_board_job)
            self.assertEqual(port.last_board_jobs_by_label, {})
            self.assertEqual(port.preflight_values, {})
            self.assertEqual(port.status, "Disconnected")
            self.assertEqual(port.selected, 0)
            self.assertEqual(port.focus_panel, "actions")
            self.assertEqual(port.items, ["item:Disconnected"])
            self.assertTrue(port.menu_dirty)
            self.assertTrue(port.main_full_redraw)
            self.assertTrue(port.logs_dirty)
            self.assertEqual(port.mapping_selection_cache, ["src"])
            self.assertTrue(port.ui_profile_enabled)

    def test_profile_formats_fields_and_flushes_on_buffer_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            port = FakePort()
            controller = self.make_controller(app_dir, env={"MOULIN_REMOTE_UI_PROFILE": "1"}, monotonic_values=[1.0, 1.1, 1.2])
            controller.initialize_ui_profile(port)
            port.ui_profile_buffer = ["line"] * 49

            controller.profile(port, "event", label="two words")

            profile_text = (app_dir / "workspace" / "ui-profile.log").read_text(encoding="utf-8")
            self.assertIn("event label='two words'", profile_text)
            self.assertEqual(port.ui_profile_buffer, [])

    def test_profile_slow_uses_threshold_and_returns_elapsed_ms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            port = FakePort()
            controller = self.make_controller(Path(tmp), env={"MOULIN_REMOTE_UI_PROFILE": "1"}, monotonic_values=[1.0, 1.1, 1.13])
            controller.initialize_ui_profile(port)
            port.ui_profile_buffer.clear()

            elapsed = controller.profile_slow(port, "slow", 1.1, threshold_ms=20.0, panel="details")

            self.assertAlmostEqual(elapsed, 30.0)
            self.assertEqual(len(port.ui_profile_buffer), 1)
            self.assertIn("slow ms=30.0 panel=details", port.ui_profile_buffer[0])

    def test_quit_flushes_profile_and_marks_port_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            port = FakePort()
            controller = self.make_controller(app_dir, env={"MOULIN_REMOTE_UI_PROFILE": "1"}, monotonic_values=[1.0, 1.1, 1.2])
            controller.initialize_ui_profile(port)

            controller.quit(port)

            self.assertTrue(port.done)
            self.assertEqual(port.ui_profile_buffer, [])
            self.assertIn("profile-start", (app_dir / "workspace" / "ui-profile.log").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
