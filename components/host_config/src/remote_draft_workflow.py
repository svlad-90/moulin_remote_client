"""Build host draft workflow service."""

from __future__ import annotations

from typing import Any, Callable

from components.host_config.api import fields as config_field_api


class RemoteDraftWorkflowService:
    """Execute add-build-host draft actions for the TUI."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        save_config: Callable[[dict[str, Any]], Any],
        reset_preflight: Callable[[], Any],
    ) -> None:
        self.config = config
        self.save_config = save_config
        self.reset_preflight = reset_preflight
        self.draft = config_field_api.remote_draft_for_config(config)
        self.actions = config_field_api.remote_draft_actions()
        self.index = 0

    def action_models(self) -> list[dict[str, Any]]:
        return [
            config_field_api.remote_draft_action_model(action, self.draft, self.config.get("remotes", []))
            for action in self.actions
        ]

    def move(self, delta: int) -> None:
        self.index = (self.index + delta) % len(self.actions)

    def handle_enter(self, port: Any) -> bool:
        action = config_field_api.remote_draft_enter_action_for_config(
            self.config,
            self.draft,
            self.actions[self.index],
        )
        if action["action"] == "status":
            port.status = str(action["status"])
            return False
        if action["action"] == "edit":
            self._edit_value(port, action)
            return False
        if action["action"] == "create":
            self._create_remote(port)
            return True
        if action["action"] == "cancel":
            port.status = str(action["status"])
            return True
        return False

    def cancel(self, port: Any) -> None:
        port.status = "Build host add cancelled"

    def _edit_value(self, port: Any, action: dict[str, Any]) -> None:
        kind = str(action["kind"])
        current = str(self.draft[kind])
        value = port.prompt(str(action["label"]), current).strip()
        self.draft[kind] = value
        if kind == "name" and not self.draft["label"]:
            self.draft["label"] = value

    def _create_remote(self, port: Any) -> None:
        plan = config_field_api.apply_remote_draft_create_for_config(self.config, self.draft)
        if plan["connection_reset"]:
            port.connection_state = "disconnected"
        if plan["preflight_reset"]:
            self.reset_preflight()
        self.save_config(self.config)
        port.status = str(plan["status"])


def remote_draft_workflow_service(
    config: dict[str, Any],
    *,
    save_config: Callable[[dict[str, Any]], Any],
    reset_preflight: Callable[[], Any],
) -> RemoteDraftWorkflowService:
    return RemoteDraftWorkflowService(config, save_config=save_config, reset_preflight=reset_preflight)
