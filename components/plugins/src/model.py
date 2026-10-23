"""Stable data model exposed to Moulin Remote Client plugins."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol


PLUGIN_API_VERSION = 1


@dataclass(frozen=True)
class PluginSetting:
    key: str
    label: str
    kind: str = "string"
    description: str = ""
    default: Any = ""
    choices: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None


@dataclass(frozen=True)
class PluginAction:
    action_id: str
    label: str
    description: str
    tab_id: str
    tab_label: str
    group: str = "Actions"
    handler: str = ""
    preview: str = ""
    view: str = ""
    confirm: bool = False
    job_slot: str | None = None


@dataclass(frozen=True)
class PluginViewDefinition:
    view_id: str
    label: str
    factory: str


@dataclass
class PluginDefinition:
    plugin_id: str
    name: str
    root: Path
    module_path: Path
    settings: tuple[PluginSetting, ...] = ()
    actions: tuple[PluginAction, ...] = ()
    views: dict[str, PluginViewDefinition] = field(default_factory=dict)
    module: Any = None
    error: str = ""


@dataclass(frozen=True)
class BoardProfile:
    board_id: str
    label: str
    user: str
    host: str
    board_type: str
    values: Mapping[str, Any]

    @property
    def remote(self) -> str:
        if self.user and self.host:
            return f"{self.user}@{self.host}"
        return self.host


@dataclass(frozen=True)
class UiEvent:
    code: int
    text: str = ""


class PluginView(Protocol):
    def render(self, ui: Any, context: Any) -> None:
        """Render the view into the host-owned canvas."""

    def handle_event(self, event: UiEvent, context: Any) -> Any:
        """Handle one host-delivered input event."""


def plugin_enabled(config: dict[str, Any], plugin_id: str) -> bool:
    plugins = config.get("plugins")
    if not isinstance(plugins, dict):
        return False
    state = plugins.get(plugin_id)
    return isinstance(state, dict) and bool(state.get("enabled"))


def plugin_config(config: dict[str, Any], plugin_id: str) -> dict[str, Any]:
    plugins = config.setdefault("plugins", {})
    if not isinstance(plugins, dict):
        plugins = {}
        config["plugins"] = plugins
    state = plugins.setdefault(plugin_id, {})
    if not isinstance(state, dict):
        state = {}
        plugins[plugin_id] = state
    values = state.setdefault("config", {})
    if not isinstance(values, dict):
        values = {}
        state["config"] = values
    return values


def set_plugin_enabled(config: dict[str, Any], plugin_id: str, enabled: bool) -> None:
    plugin_config(config, plugin_id)
    config["plugins"][plugin_id]["enabled"] = bool(enabled)
