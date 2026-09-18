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


@dataclass(frozen=True)
class BoardActionContext:
    """Runtime inputs available when a board action builds commands."""

    config: dict[str, Any]
    artifact_targets: str = ""
    build_params: dict[str, str] | None = None
    app_dir: Path | None = None
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

    def action_commands(self, ctx: BoardActionContext, action_id: str) -> list[list[str]]:
        raise ValueError(f"unsupported board action for {self.type_id}: {action_id}")
