from __future__ import annotations

import unittest
from typing import Any

from components.project_config_ui.api import project_screen_state


class FakePort:
    def __init__(self) -> None:
        self.status = ""
        self.cursor_states: list[bool] = []
        self.queued_text = ""

    def read_queued_text(self, _first_char: int) -> str:
        return self.queued_text

    def set_cursor(self, value: bool) -> None:
        self.cursor_states.append(value)


def config() -> dict[str, Any]:
    return {
        "active_project": "sdk",
        "projects": [{"name": "prod"}, {"name": "sdk"}],
    }


class ProjectScreenStateControllerTests(unittest.TestCase):
    def test_sync_selection_initializes_from_active_project_and_clamps_fields(self) -> None:
        controller = project_screen_state.ProjectScreenStateController(config())

        controller.sync_selection(controller.projects(), [{"key": "name"}])

        self.assertEqual(controller.state.project_index, 1)
        self.assertEqual(controller.state.field_index, 0)
        self.assertEqual(controller.state.focus, "projects")

    def test_navigation_action_moves_between_project_and_field_indexes(self) -> None:
        controller = project_screen_state.ProjectScreenStateController(config())
        port = FakePort()

        controller.apply_navigation_action(port, {"action": "focus-fields"}, field_count=3, project_count=2)
        controller.apply_navigation_action(port, {"action": "move-field", "delta": 1}, field_count=3, project_count=2)
        controller.apply_navigation_action(port, {"action": "move-list", "delta": 1}, field_count=3, project_count=2)

        self.assertEqual(controller.state.focus, "fields")
        self.assertEqual(controller.state.field_index, 1)
        self.assertEqual(controller.state.project_index, 1)

    def test_inline_edit_updates_value_then_saves_through_callback(self) -> None:
        controller = project_screen_state.ProjectScreenStateController(config())
        port = FakePort()
        project = {"name": "prod", "label": "Prod"}
        calls: list[tuple[str, str]] = []
        controller.begin_inline_edit("label", "Prod")
        port.queued_text = "X"

        controller.handle_inline_edit_key(
            port,
            ord("X"),
            project,
            lambda _port, target, key, value: calls.append((key, value)),
        )
        controller.handle_inline_edit_key(
            port,
            10,
            project,
            lambda _port, target, key, value: calls.append((key, value)),
        )

        self.assertEqual(calls, [("label", "ProdX")])
        self.assertEqual(controller.state.editing_key, "")
        self.assertEqual(port.cursor_states, [False])

    def test_inline_edit_cancel_clears_state_and_sets_status(self) -> None:
        controller = project_screen_state.ProjectScreenStateController(config())
        port = FakePort()
        controller.begin_inline_edit("label", "Prod")

        controller.handle_inline_edit_key(port, 27, {"name": "prod"}, lambda *_args: None)

        self.assertEqual(controller.state.editing_key, "")
        self.assertEqual(port.status, "Edit cancelled")
        self.assertEqual(port.cursor_states, [False])

    def test_apply_profile_state_updates_index_and_focus(self) -> None:
        controller = project_screen_state.ProjectScreenStateController(config())

        projects = controller.apply_profile_state(
            {"projects": [{"name": "prod"}], "project_index": 0, "focus": "fields"}
        )

        self.assertEqual(projects, [{"name": "prod"}])
        self.assertEqual(controller.state.project_index, 0)
        self.assertEqual(controller.state.focus, "fields")


if __name__ == "__main__":
    unittest.main()
