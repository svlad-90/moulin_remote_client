"""Product type adapter registry."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Any

from components.product_types.src import builtin
from components.product_types.src.base import ProductTypeAdapter

DEFAULT_PRODUCT_TYPE = "gen5_xen_android"


class ProductTypeRegistry:
    """Resolve product type ids to behavior adapters."""

    def __init__(self, adapters: list[ProductTypeAdapter] | None = None) -> None:
        discovered = adapters if adapters is not None else discover_builtin_adapters()
        self._adapters = {adapter.type_id: adapter for adapter in discovered}

    def default_type_id(self) -> str:
        return DEFAULT_PRODUCT_TYPE

    def adapters(self) -> list[ProductTypeAdapter]:
        return list(self._adapters.values())

    def adapter_for_type(self, type_id: str) -> ProductTypeAdapter:
        clean_type = type_id.strip() or DEFAULT_PRODUCT_TYPE
        return self._adapters.get(clean_type) or self._adapters[DEFAULT_PRODUCT_TYPE]

    def adapter_for_project(self, project: dict[str, Any]) -> ProductTypeAdapter:
        return self.adapter_for_type(str(project.get("product_type", DEFAULT_PRODUCT_TYPE)))


def product_type_registry() -> ProductTypeRegistry:
    return ProductTypeRegistry()


def discover_builtin_adapters() -> list[ProductTypeAdapter]:
    adapters: list[ProductTypeAdapter] = []
    for module_info in pkgutil.iter_modules(builtin.__path__, f"{builtin.__name__}."):
        if module_info.name.rsplit(".", 1)[-1].startswith("_"):
            continue
        module = importlib.import_module(module_info.name)
        for _name, cls in inspect.getmembers(module, inspect.isclass):
            if cls is ProductTypeAdapter or not issubclass(cls, ProductTypeAdapter):
                continue
            if cls.__module__ != module.__name__:
                continue
            adapter = cls()
            if adapter.type_id:
                adapters.append(adapter)
    adapters.sort(key=lambda adapter: (adapter.type_id != DEFAULT_PRODUCT_TYPE, adapter.type_id))
    return adapters
