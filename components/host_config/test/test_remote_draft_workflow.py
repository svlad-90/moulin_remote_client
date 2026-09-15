from __future__ import annotations

import unittest
from typing import Any

from components.host_config.api import remote_draft_workflow


class FakePort:
    def __init__(self, prompts: list[str] | None = None) -> None:
        self.status = ""
        self.connection_state = "connected"
        self.prompts = list(prompts or [])

    def prompt(self, _label: str, current: str = "") -> str:
        if not self.prompts:
            return current
        return self.prompts.pop(0)


def config() -> dict[str, Any]:
    return {
        "remotes": [
            {"name": "build-a", "label": "Build A", "user": "user", "host": "10.0.0.1"},
        ],
        "active_remote": "build-a",
    }


class RemoteDraftWorkflowServiceTests(unittest.TestCase):
    def test_edit_name_updates_label_when_label_is_empty(self) -> None:
        service = remote_draft_workflow.RemoteDraftWorkflowService(
            config(),
            save_config=lambda _config: None,
            reset_preflight=lambda: None,
        )
        port = FakePort(["new-build"])

        closed = service.handle_enter(port)

        self.assertFalse(closed)
        self.assertEqual(service.draft["name"], "new-build")
        self.assertEqual(service.draft["label"], "new-build")

    def test_create_remote_saves_config_resets_preflight_and_closes(self) -> None:
        cfg = config()
        saves: list[dict[str, Any]] = []
        resets: list[bool] = []
        service = remote_draft_workflow.RemoteDraftWorkflowService(
            cfg,
            save_config=saves.append,
            reset_preflight=lambda: resets.append(True),
        )
        service.draft.update({"name": "new-build", "label": "New Build", "user": "me", "host": "10.0.0.2"})
        service.index = 4
        port = FakePort()

        closed = service.handle_enter(port)

        self.assertTrue(closed)
        self.assertEqual(cfg["active_remote"], "new-build")
        self.assertEqual(cfg["remotes"][-1]["label"], "New Build")
        self.assertEqual(port.connection_state, "disconnected")
        self.assertEqual(resets, [True])
        self.assertEqual(saves, [cfg])
        self.assertEqual(port.status, "Remote profile added: new-build")

    def test_disabled_create_reports_status_and_keeps_screen_open(self) -> None:
        service = remote_draft_workflow.RemoteDraftWorkflowService(
            config(),
            save_config=lambda _config: None,
            reset_preflight=lambda: None,
        )
        service.index = 4
        port = FakePort()

        closed = service.handle_enter(port)

        self.assertFalse(closed)
        self.assertEqual(port.status, "set SSH user first")


if __name__ == "__main__":
    unittest.main()
