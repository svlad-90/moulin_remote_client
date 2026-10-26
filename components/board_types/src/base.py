"""Board type adapter contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class BoardArtifactPart:
    """Selectable part discovered inside a board-specific local artifact."""

    part_id: str
    label: str
    detail: str = ""


@dataclass(frozen=True)
class BoardLocalArtifactSpec:
    """Declarative UI contract for a board action accepting a local artifact."""

    picker_title: str
    picker_hint: str
    accepted_suffixes: tuple[str, ...]
    selection_title: str = ""
    selection_footer: str = "Space: toggle | a: all | n: none | Enter: continue | q/Esc: back"


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
    required_commands: tuple[str, ...] = ()
    local_artifact: BoardLocalArtifactSpec | None = None


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
    manifest_cache: dict[tuple[str, ...], dict[str, Any]] | None = None
    flash_bootloaders_tool: Path | None = None
    xt_imager_tool: Path | None = None
    command_builder: Any = None
    transfer_service: Any = None


class BoardCapability(str, Enum):
    """Stable board operations available to application workflows and plugins."""

    REBOOT = "board.reboot"
    REFLASH = "board.reflash"
    REFLASH_BOOTLOADERS = "board.reflash-bootloaders"


@dataclass(frozen=True)
class BoardOperationPlan:
    """Materialized board operation with explicit provisioning and execution phases."""

    capability: BoardCapability
    operation_id: str
    build_targets: tuple[str, ...]
    provision_commands: tuple[tuple[str, ...], ...]
    execute_commands: tuple[tuple[str, ...], ...]
    execute_timeout_seconds: int
    post_execute_delay_seconds: int = 10

    def __post_init__(self) -> None:
        if not self.operation_id:
            raise ValueError("board operation id is required")
        if not self.execute_commands or any(not command for command in self.execute_commands):
            raise ValueError("board operation requires non-empty execute commands")
        if any(not command for command in self.provision_commands):
            raise ValueError("board operation provision commands must not be empty")
        if self.execute_timeout_seconds <= 0:
            raise ValueError("board operation execute timeout must be positive")
        if self.post_execute_delay_seconds < 0:
            raise ValueError("board operation post-execute delay must not be negative")


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

    def local_artifact_parts(
        self,
        action_id: str,
        source: Path,
        progress: Callable[[int, int], None] | None = None,
    ) -> list[BoardArtifactPart]:
        """Inspect a local artifact and return optional board-specific parts."""
        return []

    def local_artifact_destination(self, action_id: str, source: Path) -> tuple[str, tuple[str, ...]]:
        """Return the remote filename and stale-artifact patterns to replace."""
        raise ValueError(f"local artifacts are unsupported for board action {action_id}")

    def local_artifact_build_params(
        self,
        action_id: str,
        selected_parts: tuple[BoardArtifactPart, ...],
    ) -> dict[str, str]:
        """Translate a generic part selection into board-action parameters."""
        return {}

    def local_artifact_warning(self, action_id: str) -> str:
        """Describe the destructive effect of a local-artifact action."""
        raise ValueError(f"local artifacts are unsupported for board action {action_id}")

    def capabilities(self, board_host: dict[str, Any] | None = None) -> frozenset[BoardCapability]:
        host = board_host or {}
        restart = next((action for action in self.actions(host) if action.action_id == "restart_board"), None)
        if restart is None or not restart.required_commands:
            return frozenset()
        command_ids = self.command_default_map()
        if not set(restart.required_commands) <= command_ids.keys():
            return frozenset()
        if not all(self.command_value_for_host(host, command_id).strip() for command_id in restart.required_commands):
            return frozenset()
        return frozenset({BoardCapability.REBOOT})

    def operation_plan(
        self,
        ctx: BoardActionContext,
        capability: BoardCapability,
    ) -> BoardOperationPlan | None:
        if capability == BoardCapability.REBOOT:
            commands = self.action_commands(ctx, "restart_board")
            if not commands:
                raise ValueError(f"board reboot produced no execute command for {self.type_id}")
            return BoardOperationPlan(
                capability=capability,
                operation_id=f"{self.type_id}-reboot",
                build_targets=(),
                provision_commands=(),
                execute_commands=tuple(tuple(command) for command in commands),
                execute_timeout_seconds=300,
                post_execute_delay_seconds=10,
            )
        return None
