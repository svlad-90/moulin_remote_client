from __future__ import annotations

import unittest
from unittest.mock import patch

from components.host_config_ui.api import remote_location
from components.remote.api import discovery as remote_discovery


class FakeScreen:
    def __init__(self, keys: list[int], *, height: int = 30, width: int = 120) -> None:
        self.keys = keys
        self.height = height
        self.width = width
        self.timeouts: list[int] = []
        self.clear_count = 0
        self.erase_count = 0
        self.refresh_count = 0
        self.noutrefresh_count = 0

    def timeout(self, value: int) -> None:
        self.timeouts.append(value)

    def clear(self) -> None:
        self.clear_count += 1

    def erase(self) -> None:
        self.erase_count += 1

    def getmaxyx(self) -> tuple[int, int]:
        return self.height, self.width

    def refresh(self) -> None:
        self.refresh_count += 1

    def noutrefresh(self) -> None:
        self.noutrefresh_count += 1


class FakeLocationPort:
    def __init__(self, keys: list[int]) -> None:
        self.screen = FakeScreen(keys)
        self.status = ""
        self.rows: list[tuple[int, int, str, int | None]] = []
        self.boxes: list[tuple[int, int, int, int, str]] = []

    def read_key(self) -> int:
        if not self.screen.keys:
            raise AssertionError("fake key queue is empty")
        return self.screen.keys.pop(0)

    def add(self, row: int, col: int, text: str, attr: int | None = None) -> None:
        self.rows.append((row, col, text, attr))

    def draw_box(self, top: int, left: int, height: int, width: int, title: str) -> None:
        self.boxes.append((top, left, height, width, title))

    def selected_attr(self) -> int:
        return 1

    def accent_attr(self) -> int:
        return 2

    def warn_attr(self) -> int:
        return 3

    def error_attr(self) -> int:
        return 4


def config() -> dict[str, object]:
    return {
        "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
        "active_remote": "build",
        "projects": [
            {
                "name": "prod",
                "project_dir": "meta-product",
            }
        ],
        "active_project": "prod",
    }


def parent_dir(path: str, home: str = "~") -> str:
    return remote_discovery.remote_project_discovery_service().remote_parent_dir(path, home)


class RemoteLocationBrowserServiceTests(unittest.TestCase):
    def test_remote_location_browser_factory_wires_remote_commands_to_runner(self) -> None:
        commands: list[list[str]] = []

        def runner(argv: list[str]) -> str:
            commands.append(argv)
            if argv[-1] == "printf '%s\\n' \"$HOME\"":
                return "/home/builder\n"
            return "meta\nother\n"

        service = remote_location.remote_location_browser_for_config(config(), runner)

        self.assertEqual(service.fetch_child_dirs("/mnt/projects"), ["/mnt/projects/meta", "/mnt/projects/other"])
        self.assertEqual(service.fetch_home(), "/home/builder")
        self.assertEqual(len(commands), 2)

    def test_browse_project_directory_returns_selected_child_directory(self) -> None:
        port = FakeLocationPort([ord("j"), ord(" ")])
        calls: list[str] = []
        service = remote_location.RemoteLocationBrowser(
            config(),
            fetch_child_dirs=lambda path: calls.append(path) or ["~/work", "~/tmp"],
            fetch_home=lambda: "/home/builder",
            parent_dir=parent_dir,
        )

        with patch("components.host_config_ui.src.remote_location.curses.doupdate"):
            selected = service.browse_project_directory(port, "~")

        self.assertEqual(selected, "~/work")
        self.assertEqual(calls, ["~"])
        self.assertEqual(port.screen.timeouts[-1], -1)

    def test_browse_project_directory_resolves_parent_from_remote_home(self) -> None:
        port = FakeLocationPort([10, ord(" ")])
        calls: list[str] = []

        def fetch_child_dirs(path: str) -> list[str]:
            calls.append(path)
            return []

        service = remote_location.RemoteLocationBrowser(
            config(),
            fetch_child_dirs=fetch_child_dirs,
            fetch_home=lambda: "/home/builder",
            parent_dir=parent_dir,
        )

        with patch("components.host_config_ui.src.remote_location.curses.doupdate"):
            selected = service.browse_project_directory(port, "~")

        self.assertEqual(selected, "/home")
        self.assertEqual(calls, ["~", "/home"])

    def test_project_remote_dir_editor_applies_selected_directory(self) -> None:
        port = FakeLocationPort([ord(" ")])
        project = {"name": "prod", "project_dir": "meta-product"}
        updates: list[tuple[str, str]] = []
        browser = remote_location.RemoteLocationBrowser(
            config(),
            fetch_child_dirs=lambda _path: [],
            fetch_home=lambda: "/home/builder",
            parent_dir=parent_dir,
        )
        editor = remote_location.ProjectRemoteDirEditor(config(), browser=browser)

        with patch("components.host_config_ui.src.remote_location.curses.doupdate"):
            editor.edit_project_remote_dir(
                port,
                project,
                connected=True,
                apply_project_value=lambda _project, key, value: (
                    _project.__setitem__(key, value),
                    updates.append((key, value)),
                ),
            )

        self.assertEqual(updates, [("project_dir", "meta-product")])
        self.assertEqual(port.status, "Project dir: meta-product")

    def test_project_remote_dir_editor_reports_disabled_reason_without_browsing(self) -> None:
        port = FakeLocationPort([])
        project = {"name": "prod", "project_dir": "meta-product"}
        browser = remote_location.RemoteLocationBrowser(
            config(),
            fetch_child_dirs=lambda _path: (_ for _ in ()).throw(AssertionError("browse should not run")),
            fetch_home=lambda: "/home/builder",
            parent_dir=parent_dir,
        )
        editor = remote_location.ProjectRemoteDirEditor(config(), browser=browser)

        editor.edit_project_remote_dir(
            port,
            project,
            connected=False,
            apply_project_value=lambda _project, _key, _value: None,
        )

        self.assertEqual(port.status, "connect to the build host first")


if __name__ == "__main__":
    unittest.main()
