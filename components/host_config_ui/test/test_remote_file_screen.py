from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from components.host_config_ui.api import remote_file_screen


class FakeScreen:
    def __init__(self, keys: list[int], *, height: int = 30, width: int = 120) -> None:
        self.keys = keys
        self.height = height
        self.width = width
        self.timeouts: list[int] = []
        self.erase_count = 0
        self.refresh_count = 0

    def timeout(self, value: int) -> None:
        self.timeouts.append(value)

    def erase(self) -> None:
        self.erase_count += 1

    def getmaxyx(self) -> tuple[int, int]:
        return self.height, self.width

    def refresh(self) -> None:
        self.refresh_count += 1


class FakeRemoteFilePort:
    def __init__(self, keys: list[int], *, ready: bool = True, prompts: list[str] | None = None) -> None:
        self.screen = FakeScreen(keys)
        self.status = ""
        self.ready = ready
        self.prompt_cancelled = False
        self.prompts = prompts or []
        self.build_params: dict[str, Any] = {}
        self.rows: list[tuple[int, int, str, int | None]] = []
        self.boxes: list[tuple[int, int, int, int, str]] = []

    def read_key(self) -> int:
        if not self.screen.keys:
            raise AssertionError("fake key queue is empty")
        return self.screen.keys.pop(0)

    def add(self, row: int, col: int, text: str, attr: int | None = None) -> None:
        self.rows.append((row, col, text, attr))

    def prompt(self, _label: str, _default: str = "") -> str:
        if not self.prompts:
            raise AssertionError("fake prompt queue is empty")
        return self.prompts.pop(0)

    def draw_box(self, top: int, left: int, height: int, width: int, title: str) -> None:
        self.boxes.append((top, left, height, width, title))

    def remote_project_config_ready(self) -> bool:
        return self.ready

    def selected_attr(self) -> int:
        return 1

    def selected_disabled_attr(self) -> int:
        return 2

    def disabled_attr(self) -> int:
        return 3

    def accent_attr(self) -> int:
        return 4

    def warn_attr(self) -> int:
        return 5


class FakeFieldActionController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def apply_project_inline_value(
        self,
        _port: Any,
        project: dict[str, Any],
        key: str,
        value: str,
    ) -> None:
        self.calls.append((key, value))
        project[key] = value


def config_with_active_project() -> dict[str, Any]:
    return {
        "remotes": [
            {
                "name": "build",
                "user": "builder",
                "host": "10.0.0.1",
                "projects_dir": "/mnt/projects",
            }
        ],
        "active_remote": "build",
        "projects": [
            {
                "name": "prod",
                "project_dir": "meta-product",
                "moulin_manifest": "product.yaml",
                "dockerfile": "doc/Dockerfile",
            }
        ],
        "active_project": "prod",
    }


class RemoteFileScreenControllerTests(unittest.TestCase):
    def test_select_remote_candidate_validates_and_returns_valid_path(self) -> None:
        port = FakeRemoteFilePort([10])
        candidates = [{"path": "product.yaml", "valid": None, "detail": "press Enter to validate"}]

        selected = remote_file_screen.run_select_remote_candidate_screen(
            port,
            config_with_active_project(),
            "Select Moulin manifest",
            candidates,
            lambda path: (True, f"valid {path}"),
        )

        self.assertEqual(selected, "product.yaml")
        self.assertEqual(candidates[0]["valid"], True)
        self.assertEqual(port.status, "valid product.yaml")
        self.assertEqual(port.screen.timeouts[-1], -1)

    def test_select_remote_candidate_stays_on_invalid_then_can_cancel(self) -> None:
        port = FakeRemoteFilePort([10, ord("q")])
        candidates = [{"path": "broken.yaml", "valid": None, "detail": "press Enter to validate"}]

        selected = remote_file_screen.run_select_remote_candidate_screen(
            port,
            config_with_active_project(),
            "Select Moulin manifest",
            candidates,
            lambda _path: (False, "no Moulin manifest markers"),
        )

        self.assertIsNone(selected)
        self.assertEqual(candidates[0]["valid"], False)
        self.assertEqual(port.status, "no Moulin manifest markers")

    def test_select_remote_dockerfile_applies_valid_choice_and_saves(self) -> None:
        port = FakeRemoteFilePort([10])
        config = config_with_active_project()
        controller = FakeFieldActionController()

        remote_file_screen.run_select_remote_dockerfile(
            port,
            config,
            fetch_git_tracked_files=lambda: ["doc/Dockerfile", "README.md"],
            fetch_git_remote_files=lambda: (_ for _ in ()).throw(AssertionError("remote fallback should not run")),
            read_project_file=lambda _config, path: "FROM ubuntu:22.04\n" if path == "doc/Dockerfile" else "",
            read_git_remote_file=lambda _config, _path: "",
            field_action_controller=controller,
        )

        self.assertEqual(config["projects"][0]["dockerfile"], "doc/Dockerfile")
        self.assertEqual(port.status, "Dockerfile: doc/Dockerfile")
        self.assertEqual(controller.calls, [("dockerfile", "doc/Dockerfile")])

    def test_select_remote_dockerfile_returns_early_when_remote_project_not_ready(self) -> None:
        port = FakeRemoteFilePort([10], ready=False)
        config = config_with_active_project()
        controller = FakeFieldActionController()

        remote_file_screen.run_select_remote_dockerfile(
            port,
            config,
            fetch_git_tracked_files=lambda: (_ for _ in ()).throw(AssertionError("fetch should not run")),
            fetch_git_remote_files=lambda: (_ for _ in ()).throw(AssertionError("fetch should not run")),
            read_project_file=lambda _config, _path: "",
            read_git_remote_file=lambda _config, _path: "",
            field_action_controller=controller,
        )

        self.assertEqual(config["projects"][0]["dockerfile"], "doc/Dockerfile")
        self.assertEqual(controller.calls, [])

    def test_select_remote_dockerfile_falls_back_to_manual_path_on_search_failure(self) -> None:
        port = FakeRemoteFilePort([], prompts=["manual/Dockerfile"])
        config = config_with_active_project()
        controller = FakeFieldActionController()

        remote_file_screen.run_select_remote_dockerfile(
            port,
            config,
            fetch_git_tracked_files=lambda: (_ for _ in ()).throw(RuntimeError("git failed")),
            fetch_git_remote_files=lambda: (_ for _ in ()).throw(RuntimeError("remote git failed")),
            read_project_file=lambda _config, _path: "",
            read_git_remote_file=lambda _config, _path: "",
            field_action_controller=controller,
        )

        self.assertEqual(config["projects"][0]["dockerfile"], "manual/Dockerfile")
        self.assertEqual(port.status, "Dockerfile: manual/Dockerfile")
        self.assertEqual(controller.calls, [("dockerfile", "manual/Dockerfile")])

    def test_select_remote_dockerfile_falls_back_to_remote_git_when_checkout_has_no_candidates(self) -> None:
        port = FakeRemoteFilePort([10])
        config = config_with_active_project()
        controller = FakeFieldActionController()

        remote_file_screen.run_select_remote_dockerfile(
            port,
            config,
            fetch_git_tracked_files=lambda: ["README.md"],
            fetch_git_remote_files=lambda: ["remote/Dockerfile"],
            read_project_file=lambda _config, _path: (_ for _ in ()).throw(AssertionError("checkout read should not run")),
            read_git_remote_file=lambda _config, path: "FROM ubuntu:24.04\n" if path == "remote/Dockerfile" else "",
            field_action_controller=controller,
        )

        self.assertEqual(config["projects"][0]["dockerfile"], "remote/Dockerfile")
        self.assertEqual(port.status, "Dockerfile: remote/Dockerfile")
        self.assertEqual(controller.calls, [("dockerfile", "remote/Dockerfile")])

    def test_select_remote_moulin_manifest_falls_back_to_manual_path_when_no_candidates(self) -> None:
        port = FakeRemoteFilePort([], prompts=["manual.yaml"])
        config = config_with_active_project()
        field_controller = FakeFieldActionController()

        with patch(
            "components.host_config_ui.src.remote_file_screen.moulin_manifest_api.default_parameters_for_config",
            return_value={},
        ):
            remote_file_screen.run_select_remote_moulin_manifest(
                port,
                config,
                Path("/app"),
                fetch_git_tracked_files=lambda: ["README.md"],
                fetch_git_remote_files=lambda: [],
                read_project_file=lambda _config, _path: "",
                read_git_remote_file=lambda _config, _path: "",
                manifest_cache={("old", "cache", "entry"): {}},
                default_moulin_manifest="product.yaml",
                field_action_controller=field_controller,
            )

        self.assertEqual(config["projects"][0]["moulin_manifest"], "manual.yaml")
        self.assertEqual(port.status, "Moulin manifest: manual.yaml")
        self.assertEqual(field_controller.calls, [("moulin_manifest", "manual.yaml")])

    def test_remote_file_selection_controller_selects_dockerfile(self) -> None:
        port = FakeRemoteFilePort([10])
        config = config_with_active_project()
        field_controller = FakeFieldActionController()
        controller = remote_file_screen.RemoteFileSelectionController(
            config,
            app_dir=Path("/app"),
            fetch_git_tracked_files=lambda: ["doc/Dockerfile"],
            fetch_git_remote_files=lambda: (_ for _ in ()).throw(AssertionError("remote fallback should not run")),
            read_project_file=lambda _config, _path: "FROM ubuntu:22.04\n",
            read_git_remote_file=lambda _config, _path: "",
            manifest_cache={},
            default_moulin_manifest="product.yaml",
            field_action_controller=field_controller,
        )

        controller.select_dockerfile(port)

        self.assertEqual(config["projects"][0]["dockerfile"], "doc/Dockerfile")
        self.assertEqual(field_controller.calls, [("dockerfile", "doc/Dockerfile")])


if __name__ == "__main__":
    unittest.main()
