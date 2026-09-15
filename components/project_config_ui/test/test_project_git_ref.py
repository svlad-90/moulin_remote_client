from __future__ import annotations

import unittest

from components.project_config_ui.api import project_git_ref


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


class FakeGitRefPort:
    def __init__(self, keys: list[int], prompts: list[str] | None = None) -> None:
        self.screen = FakeScreen(keys)
        self.status = ""
        self.prompts = list(prompts or [])
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

    def prompt(self, _label: str, current: str = "") -> str:
        if not self.prompts:
            return current
        return self.prompts.pop(0)

    def selected_attr(self) -> int:
        return 1

    def accent_attr(self) -> int:
        return 2

    def warn_attr(self) -> int:
        return 3


def config() -> dict[str, object]:
    return {
        "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1"}],
        "active_remote": "build",
        "projects": [
            {
                "name": "prod",
                "git_url": "git@example:prod",
                "git_ref": "mirror",
            }
        ],
        "active_project": "prod",
    }


class ProjectGitRefSelectorServiceTests(unittest.TestCase):
    def test_project_git_ref_selector_factory_wires_remote_branch_fetch(self) -> None:
        commands: list[list[str]] = []

        def runner(argv: list[str]) -> str:
            commands.append(argv)
            return "abc refs/heads/mirror\nabc refs/heads/develop\n"

        selector = project_git_ref.project_git_ref_selector_for_config(config(), runner)

        self.assertEqual(selector.fetch_branches("git@example:prod"), ["develop", "mirror"])
        self.assertEqual(len(commands), 1)

    def test_edit_project_git_ref_selects_remote_branch_when_connected(self) -> None:
        port = FakeGitRefPort([ord("k"), 10])
        project = {"name": "prod", "git_ref": "mirror", "git_url": "git@example:prod"}
        updates: list[tuple[str, str]] = []
        selector = project_git_ref.ProjectGitRefSelector(
            config(),
            fetch_branches=lambda _git_url: ["develop", "mirror"],
        )

        selector.edit_project_git_ref(
            port,
            project,
            connected=True,
            apply_project_value=lambda _project, key, value: updates.append((key, value)),
        )

        self.assertEqual(updates, [("git_ref", "develop")])
        self.assertEqual(port.screen.timeouts[-1], -1)

    def test_edit_project_git_ref_uses_manual_prompt_when_disconnected(self) -> None:
        port = FakeGitRefPort([], prompts=["feature/local"])
        project = {"name": "prod", "git_ref": "mirror", "git_url": "git@example:prod"}
        updates: list[tuple[str, str]] = []
        selector = project_git_ref.ProjectGitRefSelector(
            config(),
            fetch_branches=lambda _git_url: (_ for _ in ()).throw(AssertionError("fetch should not run")),
        )

        selector.edit_project_git_ref(
            port,
            project,
            connected=False,
            apply_project_value=lambda _project, key, value: updates.append((key, value)),
        )

        self.assertEqual(updates, [("git_ref", "feature/local")])

    def test_edit_project_git_ref_falls_back_to_prompt_after_branch_fetch_failure(self) -> None:
        port = FakeGitRefPort([], prompts=["manual/ref"])
        project = {"name": "prod", "git_ref": "mirror", "git_url": "git@example:prod"}
        updates: list[tuple[str, str]] = []
        selector = project_git_ref.ProjectGitRefSelector(
            config(),
            fetch_branches=lambda _git_url: (_ for _ in ()).throw(RuntimeError("ssh failed")),
        )

        selector.edit_project_git_ref(
            port,
            project,
            connected=True,
            apply_project_value=lambda _project, key, value: updates.append((key, value)),
        )

        self.assertEqual(port.status, "Branch list failed: ssh failed")
        self.assertEqual(updates, [("git_ref", "manual/ref")])


if __name__ == "__main__":
    unittest.main()
