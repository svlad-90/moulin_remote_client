"""Board type adapter registry."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Any

from components.board_types.src.base import BoardTypeAdapter
from components.board_types.src import builtin

DEFAULT_BOARD_TYPE = "gen5_x5h"


class BoardTypeRegistry:
    """Resolve board type ids to behavior adapters."""

    def __init__(self, adapters: list[BoardTypeAdapter] | None = None) -> None:
        self._adapters = {adapter.type_id: adapter for adapter in (adapters or discover_builtin_adapters())}

    def default_type_id(self) -> str:
        return DEFAULT_BOARD_TYPE

    def adapters(self) -> list[BoardTypeAdapter]:
        return list(self._adapters.values())

    def adapter_for_type(self, type_id: str) -> BoardTypeAdapter:
        clean_type = type_id.strip() or DEFAULT_BOARD_TYPE
        return self._adapters.get(clean_type) or self._adapters[DEFAULT_BOARD_TYPE]

    def adapter_for_host(self, host: dict[str, Any]) -> BoardTypeAdapter:
        return self.adapter_for_type(str(host.get("type", DEFAULT_BOARD_TYPE)))


def board_type_registry() -> BoardTypeRegistry:
    return BoardTypeRegistry()


def discover_builtin_adapters() -> list[BoardTypeAdapter]:
    adapters: list[BoardTypeAdapter] = []
    for module_info in pkgutil.iter_modules(builtin.__path__, f"{builtin.__name__}."):
        if module_info.name.rsplit(".", 1)[-1].startswith("_"):
            continue
        module = importlib.import_module(module_info.name)
        for _name, cls in inspect.getmembers(module, inspect.isclass):
            if cls is BoardTypeAdapter or not issubclass(cls, BoardTypeAdapter):
                continue
            if cls.__module__ != module.__name__:
                continue
            adapter = cls()
            if adapter.type_id:
                adapters.append(adapter)
    adapters.sort(key=lambda adapter: (adapter.type_id != DEFAULT_BOARD_TYPE, adapter.type_id))
    return adapters
