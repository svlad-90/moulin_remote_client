"""Board type registry API."""

from __future__ import annotations

from components.board_types.src.registry import (
    DEFAULT_BOARD_TYPE,
    BoardTypeRegistry,
    board_type_registry,
    discover_builtin_adapters,
)

__all__ = ["DEFAULT_BOARD_TYPE", "BoardTypeRegistry", "board_type_registry", "discover_builtin_adapters"]
