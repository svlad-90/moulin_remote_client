"""Board type adapter contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BoardAction:
    """Action exposed by a board type adapter."""

    action_id: str
    label: str
    description: str
    confirm: bool = True
    requires_remote: bool = False
    requires_project: bool = False
    allow_during_job: bool = False
    interactive: bool = False
    domains: tuple[str, ...] = ()
    target_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class BoardCommandDefault:
    """Board-host command kind and its board-type default command."""

    command_id: str
    label: str
    default: str
    description: str = ""


@dataclass(frozen=True)
class BoardActionContext:
    """Runtime inputs available when a board action builds commands."""

    config: dict[str, Any]
    artifact_targets: str = ""
    active_domains: frozenset[str] = frozenset()
    build_params: dict[str, str] | None = None
    app_dir: Path | None = None
    default_moulin_manifest: str = "product.yaml"
    remote_read_project_file: Any = None
    manifest_cache: dict[tuple[str, str, str], dict[str, Any]] | None = None
    flash_bootloaders_tool: Path | None = None
    xt_imager_tool: Path | None = None
    command_builder: Any = None
    transfer_service: Any = None
    flash_service: Any = None


class BoardTypeAdapter:
    """Base class for board-specific command behavior."""

    type_id = ""
    label = ""
    description = ""

    def actions(self, _config: dict[str, Any]) -> list[BoardAction]:
        return []

    def command_defaults(self) -> list[BoardCommandDefault]:
        return []

    def command_default_map(self) -> dict[str, str]:
        return {command.command_id: command.default for command in self.command_defaults()}

    def command_value_for_host(self, host: dict[str, Any], command_id: str) -> str:
        defaults = self.command_default_map()
        if command_id not in defaults:
            raise ValueError(f"unsupported board command for {self.type_id}: {command_id}")
        commands = host.get("commands")
        if isinstance(commands, dict):
            value = str(commands.get(command_id, "")).strip()
            if value:
                return value
        return defaults[command_id]

    def action_commands(self, ctx: BoardActionContext, action_id: str) -> list[list[str]]:
        raise ValueError(f"unsupported board action for {self.type_id}: {action_id}")
