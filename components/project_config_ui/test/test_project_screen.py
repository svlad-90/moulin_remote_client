from __future__ import annotations

import curses
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from components.project_config_ui.api import project_screen


class FakeScreen:
    def __init__(self, keys: list[int], *, height: int = 30, width: int = 120) -> None:
        self.keys = keys
        self.height = height
        self.width = width
        self.timeouts: list[int] = []
        self.clear_count = 0
        self.refresh_count = 0

    def timeout(self, value: int) -> None:
        self.timeouts.append(value)

    def clear(self) -> None:
        self.clear_count += 1

    def getmaxyx(self) -> tuple[int, int]:
        return self.height, self.width

    def refresh(self) -> None:
        self.refresh_count += 1

    def move(self, _row: int, _col: int) -> None:
        return None


class FakeProjectConfigPort:
    def __init__(self, keys: list[int]) -> None:
        self.screen = FakeScreen(keys)
        self.status = ""
        self.connection_state = "disconnected"
        self.build_params: dict[str, str] = {}
        self.build_targets = ""
        self.docker_image = ""
        self.rows: list[tuple[int, int, str, int | None]] = []
        self.boxes: list[tuple[int, int, int, int, str]] = []
        self.cursor_states: list[bool] = []
        self.add_calls = 0
        self.set_active_calls: list[str] = []
        self.delete_calls: list[str] = []

    def read_key(self) -> int:
        if not self.screen.keys:
            raise AssertionError("fake key queue is empty")
        return self.screen.keys.pop(0)

    def read_queued_text(self, _first_char: int) -> str:
        if 32 <= _first_char < 127:
            return chr(_first_char)
        return ""

    def add(self, row: int, col: int, text: str, attr: int | None = None) -> None:
        self.rows.append((row, col, text, attr))

    def draw_box(self, top: int, left: int, height: int, width: int, title: str) -> None:
        self.boxes.append((top, left, height, width, title))

    def draw_wrapped(self, row: int, _col: int, _width: int, text: str, _attr: int = 0, *, max_lines: int = 3) -> int:
        return row + min(max(1, len(text) // 80 + 1), max_lines)

    def set_cursor(self, value: bool) -> None:
        self.cursor_states.append(value)

    def selected_active_attr(self) -> int:
        return 1

    def selected_attr(self) -> int:
        return 2

    def active_row_attr(self) -> int:
        return 3

    def accent_attr(self) -> int:
        return 4

    def disabled_attr(self) -> int:
        return 5

    def warn_attr(self) -> int:
        return 6

    def editing_attr(self) -> int:
        return 7

    def selected_disabled_attr(self) -> int:
        return 8

    def add_project_profile(self) -> None:
        self.add_calls += 1

    def delete_project_profile(self, project: dict[str, Any]) -> None:
        self.delete_calls.append(str(project.get("name", "")))

    def set_active_project(self, project: dict[str, Any]) -> None:
        self.set_active_calls.append(str(project.get("name", "")))

    def apply_project_inline_value(self, project: dict[str, Any], key: str, value: str) -> None:
        project[key] = value

    def select_remote_moulin_manifest(self) -> None:
        return None

    def select_remote_dockerfile(self) -> None:
        return None

    def edit_project_remote_dir(self, _project: dict[str, Any]) -> None:
        return None

    def edit_project_git_ref(self, _project: dict[str, Any]) -> None:
        return None

    def select_build_targets_screen(self) -> None:
        return None

    def select_board_artifacts_screen(self) -> None:
        return None

    def cycle_parameter(self, _param: dict[str, Any]) -> None:
        return None


class FakeTargetSelector:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.reload_runtime: Any = None

    def select_build_targets(self, _port: Any, *, reload_runtime: Any) -> None:
        self.calls.append("targets")
        self.reload_runtime = reload_runtime

    def select_board_artifacts(self, _port: Any, *, reload_runtime: Any) -> None:
        self.calls.append("board_artifacts")
        self.reload_runtime = reload_runtime


class FakeProjectSettingsController:
    def __init__(self) -> None:
        self.params: list[str] = []

    def cycle_parameter(self, port: Any, param: dict[str, Any]) -> None:
        self.params.append(str(param["name"]))
        port.build_params[str(param["name"])] = "yes"
        port.status = f"{param['name']}=yes"


class FakeRemoteFileSelector:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def select_moulin_manifest(self, _port: Any) -> None:
        self.calls.append("manifest")

    def select_dockerfile(self, _port: Any) -> None:
        self.calls.append("dockerfile")


class FakeProjectRemoteDirEditor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def edit_project_remote_dir(self, _port: Any, project: dict[str, Any], *, connected: bool, apply_project_value: Any) -> None:
        self.calls.append((str(project.get("name", "")), connected))
        apply_project_value(project, "project_dir", "meta-new")


class FakeProjectGitRefSelector:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def edit_project_git_ref(self, _port: Any, project: dict[str, Any], *, connected: bool, apply_project_value: Any) -> None:
        self.calls.append((str(project.get("name", "")), connected))
        apply_project_value(project, "git_ref", "mirror")


class FakeProfileActionController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def add_project_profile(self, port: Any) -> None:
        self.calls.append(("add", ""))
        port.status = "added by controller"

    def delete_project_profile(self, port: Any, project: dict[str, Any]) -> None:
        self.calls.append(("delete", str(project.get("name", ""))))
        port.status = "deleted by controller"

    def set_active_project(self, port: Any, project: dict[str, Any]) -> None:
        self.calls.append(("set-active", str(project.get("name", ""))))
        port.status = "active by controller"


class FakeFieldActionController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def apply_project_inline_value(self, _port: Any, project: dict[str, Any], key: str, value: str) -> None:
        self.calls.append((str(project.get("name", "")), key, value))
        project[key] = value


def config_with_projects() -> dict[str, Any]:
    return {
        "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
        "active_remote": "build",
        "projects": [
            {"name": "prod", "label": "Prod", "project_dir": "meta-product", "moulin_manifest": "missing.yaml"},
            {"name": "sdk", "label": "SDK", "project_dir": "meta-sdk", "moulin_manifest": "missing.yaml"},
        ],
        "active_project": "prod",
    }


class ProjectConfigurationScreenControllerTests(unittest.TestCase):
    def test_project_fields_include_base_params_and_artifact_fields(self) -> None:
        fields = project_screen.project_fields([{"name": "ENABLE_ANDROID"}])

        self.assertEqual(fields[0]["key"], "name")
        self.assertIn("param:ENABLE_ANDROID", [field["key"] for field in fields])
        self.assertEqual(fields[-1]["key"], "docker_image")

    def test_run_project_configurations_screen_quit_saves_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            port = FakeProjectConfigPort([ord("q")])
            saved: list[dict[str, Any]] = []

            project_screen.run_project_configurations_screen(
                port,
                config_with_projects(),
                Path(tmpdir),
                remote_read_project_file=lambda _config, _path: "",
                manifest_cache={},
                default_moulin_manifest="missing.yaml",
                default_config_path=Path(tmpdir) / "config.json",
                save_config=saved.append,
            )

            self.assertEqual(len(saved), 1)
            self.assertEqual(port.screen.timeouts[-1], 250)

    def test_run_project_configurations_screen_disconnected_does_not_load_remote_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            port = FakeProjectConfigPort([ord("q")])
            remote_read = Mock(return_value="")

            with patch("components.project_config_ui.src.project_screen.moulin_manifest_api.parameters_for_config") as parameters:
                project_screen.run_project_configurations_screen(
                    port,
                    config_with_projects(),
                    Path(tmpdir),
                    remote_read_project_file=remote_read,
                    manifest_cache={},
                    default_moulin_manifest="missing.yaml",
                    default_config_path=Path(tmpdir) / "config.json",
                    save_config=lambda _config: None,
                )

            parameters.assert_not_called()
            remote_read.assert_not_called()

    def test_run_project_configurations_screen_add_action_uses_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            port = FakeProjectConfigPort([ord("a"), ord("q")])

            project_screen.run_project_configurations_screen(
                port,
                config_with_projects(),
                Path(tmpdir),
                remote_read_project_file=lambda _config, _path: "",
                manifest_cache={},
                default_moulin_manifest="missing.yaml",
                default_config_path=Path(tmpdir) / "config.json",
                save_config=lambda _config: None,
            )

            self.assertEqual(port.add_calls, 1)

    def test_run_project_configurations_screen_set_active_uses_selected_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            port = FakeProjectConfigPort([ord("j"), ord("s"), ord("q")])

            project_screen.run_project_configurations_screen(
                port,
                config_with_projects(),
                Path(tmpdir),
                remote_read_project_file=lambda _config, _path: "",
                manifest_cache={},
                default_moulin_manifest="missing.yaml",
                default_config_path=Path(tmpdir) / "config.json",
                save_config=lambda _config: None,
            )

            self.assertEqual(port.set_active_calls, ["sdk"])

    def test_run_project_configurations_screen_uses_profile_action_controller_for_add(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            port = FakeProjectConfigPort([ord("a"), ord("q")])
            controller = FakeProfileActionController()

            project_screen.run_project_configurations_screen(
                port,
                config_with_projects(),
                Path(tmpdir),
                remote_read_project_file=lambda _config, _path: "",
                manifest_cache={},
                default_moulin_manifest="missing.yaml",
                default_config_path=Path(tmpdir) / "config.json",
                save_config=lambda _config: None,
                profile_action_controller=controller,
            )

            self.assertEqual(controller.calls, [("add", "")])
            self.assertEqual(port.add_calls, 0)

    def test_run_project_configurations_screen_uses_profile_action_controller_for_selected_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            port = FakeProjectConfigPort([ord("j"), ord("s"), ord("d"), ord("q")])
            controller = FakeProfileActionController()

            project_screen.run_project_configurations_screen(
                port,
                config_with_projects(),
                Path(tmpdir),
                remote_read_project_file=lambda _config, _path: "",
                manifest_cache={},
                default_moulin_manifest="missing.yaml",
                default_config_path=Path(tmpdir) / "config.json",
                save_config=lambda _config: None,
                profile_action_controller=controller,
            )

            self.assertEqual(controller.calls, [("set-active", "sdk"), ("delete", "sdk")])
            self.assertEqual(port.set_active_calls, [])
            self.assertEqual(port.delete_calls, [])

    def test_run_project_configurations_screen_uses_field_action_controller_for_inline_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            port = FakeProjectConfigPort([curses.KEY_RIGHT, ord("j"), 10, ord("X"), 10, ord("q")])
            controller = FakeFieldActionController()
            config = config_with_projects()

            project_screen.run_project_configurations_screen(
                port,
                config,
                Path(tmpdir),
                remote_read_project_file=lambda _config, _path: "",
                manifest_cache={},
                default_moulin_manifest="missing.yaml",
                default_config_path=Path(tmpdir) / "config.json",
                save_config=lambda _config: None,
                field_action_controller=controller,
            )

            self.assertEqual(controller.calls, [("prod", "label", "ProdX")])
            self.assertEqual(config["projects"][0]["label"], "ProdX")

    def test_run_project_configurations_screen_uses_target_selection_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            keys = [curses.KEY_RIGHT] + [ord("j")] * 8 + [10, ord("q")]
            port = FakeProjectConfigPort(keys)
            port.connection_state = "connected"
            selector = FakeTargetSelector()
            reloaded: list[bool] = []

            project_screen.run_project_configurations_screen(
                port,
                config_with_projects(),
                Path(tmpdir),
                remote_read_project_file=lambda _config, _path: "",
                manifest_cache={},
                default_moulin_manifest="missing.yaml",
                default_config_path=Path(tmpdir) / "config.json",
                save_config=lambda _config: None,
                target_selection_controller_factory=lambda: selector,
                reload_runtime=lambda: reloaded.append(True),
            )

            selector.reload_runtime()

            self.assertEqual(selector.calls, ["targets"])
            self.assertEqual(reloaded, [True])

    def test_run_project_configurations_screen_uses_remote_file_selection_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            keys = [curses.KEY_RIGHT] + [ord("j")] * 6 + [10, ord("q")]
            port = FakeProjectConfigPort(keys)
            port.connection_state = "connected"
            selector = FakeRemoteFileSelector()

            project_screen.run_project_configurations_screen(
                port,
                config_with_projects(),
                Path(tmpdir),
                remote_read_project_file=lambda _config, _path: "",
                manifest_cache={},
                default_moulin_manifest="missing.yaml",
                default_config_path=Path(tmpdir) / "config.json",
                save_config=lambda _config: None,
                remote_file_selection_controller=selector,
            )

            self.assertEqual(selector.calls, ["manifest"])

    def test_run_project_configurations_screen_uses_project_remote_dir_editor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            keys = [curses.KEY_RIGHT, 10, ord("q")]
            port = FakeProjectConfigPort(keys)
            port.connection_state = "connected"
            editor = FakeProjectRemoteDirEditor()
            config = config_with_projects()

            with patch(
                "components.project_config_ui.src.project_screen.project_fields",
                return_value=[{"label": "Project dir", "key": "project_dir", "kind": "remote_dir"}],
            ):
                project_screen.run_project_configurations_screen(
                    port,
                    config,
                    Path(tmpdir),
                    remote_read_project_file=lambda _config, _path: "",
                    manifest_cache={},
                    default_moulin_manifest="missing.yaml",
                    default_config_path=Path(tmpdir) / "config.json",
                    save_config=lambda _config: None,
                    project_remote_dir_editor=editor,
                )

            self.assertEqual(editor.calls, [("prod", True)])
            self.assertEqual(config["projects"][0]["project_dir"], "meta-new")

    def test_run_project_configurations_screen_uses_project_git_ref_selector(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            keys = [curses.KEY_RIGHT] + [ord("j")] * 5 + [10, ord("q")]
            port = FakeProjectConfigPort(keys)
            port.connection_state = "connected"
            selector = FakeProjectGitRefSelector()
            config = config_with_projects()

            project_screen.run_project_configurations_screen(
                port,
                config,
                Path(tmpdir),
                remote_read_project_file=lambda _config, _path: "",
                manifest_cache={},
                default_moulin_manifest="missing.yaml",
                default_config_path=Path(tmpdir) / "config.json",
                save_config=lambda _config: None,
                project_git_ref_selector=selector,
            )

            self.assertEqual(selector.calls, [("prod", True)])
            self.assertEqual(config["projects"][0]["git_ref"], "mirror")

    def test_run_project_configurations_screen_uses_settings_controller_for_parameter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            keys = [curses.KEY_RIGHT] + [ord("j")] * 6 + [10, ord("q")]
            port = FakeProjectConfigPort(keys)
            port.connection_state = "connected"
            settings = FakeProjectSettingsController()
            runtime_saves: list[dict[str, Any]] = []

            with patch(
                "components.project_config_ui.src.project_screen.moulin_manifest_api.parameters_for_config",
                return_value=[{"name": "ENABLE_ANDROID", "default": "no", "choices": ["no", "yes"]}],
            ), patch(
                "components.project_config_ui.src.project_screen.config_runtime_api.save_current_runtime_build_settings",
                side_effect=lambda _config, **kwargs: runtime_saves.append(kwargs),
            ):
                project_screen.run_project_configurations_screen(
                    port,
                    config_with_projects(),
                    Path(tmpdir),
                    remote_read_project_file=lambda _config, _path: "",
                    manifest_cache={},
                    default_moulin_manifest="missing.yaml",
                    default_config_path=Path(tmpdir) / "config.json",
                    save_config=lambda _config: None,
                    project_settings_controller=settings,
                )

            self.assertEqual(settings.params, ["ENABLE_ANDROID"])
            self.assertEqual(port.build_params["ENABLE_ANDROID"], "yes")
            self.assertEqual(runtime_saves[0]["parameters"], port.build_params)


if __name__ == "__main__":
    unittest.main()
