"""Discover and validate plugins from the application plugins directory."""

from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from components.plugins.src.model import (
    PLUGIN_API_VERSION,
    PluginAction,
    PluginDefinition,
    PluginSetting,
    PluginViewDefinition,
)


class PluginDiscovery:
    """Load plugin metadata and enabled Python entry points."""

    def __init__(self, plugins_dir: Path) -> None:
        self.plugins_dir = plugins_dir
        self._definitions: list[PluginDefinition] | None = None

    def discover(self, *, refresh: bool = False) -> list[PluginDefinition]:
        if self._definitions is not None and not refresh:
            return list(self._definitions)
        definitions: list[PluginDefinition] = []
        seen: set[str] = set()
        if self.plugins_dir.is_dir():
            for manifest_path in sorted(self.plugins_dir.glob("*/plugin.yaml")):
                definition = self._load_manifest(manifest_path)
                if definition.plugin_id in seen:
                    definition.error = f"duplicate plugin id: {definition.plugin_id}"
                seen.add(definition.plugin_id)
                definitions.append(definition)
        self._definitions = definitions
        return list(definitions)

    def load_module(self, definition: PluginDefinition) -> Any:
        if definition.module is not None:
            return definition.module
        if definition.error:
            raise RuntimeError(definition.error)
        root_hash = hashlib.sha256(str(definition.root).encode("utf-8")).hexdigest()[:12]
        module_name = "_mrc_plugin_" + re.sub(r"[^a-zA-Z0-9_]", "_", definition.plugin_id) + "_" + root_hash
        spec = importlib.util.spec_from_file_location(
            module_name,
            definition.module_path,
            submodule_search_locations=[str(definition.root)],
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load module: {definition.module_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        definition.module = module
        return module

    def resolve(self, definition: PluginDefinition, reference: str) -> Any:
        if not reference:
            raise RuntimeError(f"plugin {definition.plugin_id} has an empty callable reference")
        target: Any = self.load_module(definition)
        for part in reference.split("."):
            target = getattr(target, part)
        if not callable(target):
            raise TypeError(f"plugin callable is not callable: {reference}")
        return target

    def _load_manifest(self, path: Path) -> PluginDefinition:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("plugin manifest must contain a mapping")
            api_version = int(raw.get("api_version", 0))
            if api_version != PLUGIN_API_VERSION:
                raise ValueError(f"unsupported api_version {api_version}; expected {PLUGIN_API_VERSION}")
            plugin_id = self._required_text(raw, "id")
            name = str(raw.get("name") or plugin_id)
            module_name = str(raw.get("entrypoint") or "plugin.py")
            module_path = (path.parent / module_name).resolve()
            if path.parent.resolve() not in module_path.parents:
                raise ValueError("entrypoint must stay inside the plugin directory")
            if not module_path.is_file():
                raise ValueError(f"entrypoint does not exist: {module_name}")
            settings = self._settings(raw.get("settings"))
            actions = self._actions(raw.get("tabs"))
            views = self._views(raw.get("views"))
            return PluginDefinition(plugin_id, name, path.parent, module_path, settings, actions, views)
        except Exception as exc:
            fallback_id = path.parent.name
            return PluginDefinition(fallback_id, fallback_id, path.parent, path.parent / "plugin.py", error=str(exc))

    @staticmethod
    def _required_text(raw: dict[str, Any], key: str) -> str:
        value = str(raw.get(key) or "").strip()
        if not value:
            raise ValueError(f"missing required field: {key}")
        return value

    def _settings(self, raw: Any) -> tuple[PluginSetting, ...]:
        if raw is None:
            return ()
        if not isinstance(raw, dict):
            raise ValueError("settings must be a mapping")
        result: list[PluginSetting] = []
        for key, value in raw.items():
            if not isinstance(value, dict):
                raise ValueError(f"setting {key} must be a mapping")
            kind = str(value.get("type") or "string")
            if kind not in {"string", "integer", "boolean", "choice"}:
                raise ValueError(f"setting {key} has unsupported type: {kind}")
            choices = tuple(str(item) for item in value.get("choices", []) or [])
            if kind == "choice" and not choices:
                raise ValueError(f"choice setting {key} requires choices")
            result.append(
                PluginSetting(
                    key=str(key),
                    label=str(value.get("label") or key),
                    kind=kind,
                    description=str(value.get("description") or ""),
                    default=value.get("default", False if kind == "boolean" else ""),
                    choices=choices,
                    minimum=self._optional_int(value.get("minimum")),
                    maximum=self._optional_int(value.get("maximum")),
                )
            )
        return tuple(result)

    def _actions(self, raw: Any) -> tuple[PluginAction, ...]:
        if raw is None:
            return ()
        if not isinstance(raw, list):
            raise ValueError("tabs must be a list")
        result: list[PluginAction] = []
        for tab in raw:
            if not isinstance(tab, dict):
                raise ValueError("tab must be a mapping")
            tab_id = self._required_text(tab, "id")
            tab_label = str(tab.get("label") or tab_id)
            actions = tab.get("actions", [])
            if not isinstance(actions, list):
                raise ValueError(f"tab {tab_id} actions must be a list")
            for action in actions:
                if not isinstance(action, dict):
                    raise ValueError(f"tab {tab_id} action must be a mapping")
                action_id = self._required_text(action, "id")
                handler = str(action.get("handler") or "")
                view = str(action.get("view") or "")
                if not handler and not view:
                    raise ValueError(f"action {action_id} requires handler or view")
                result.append(
                    PluginAction(
                        action_id=action_id,
                        label=str(action.get("label") or action_id),
                        description=str(action.get("description") or ""),
                        tab_id=tab_id,
                        tab_label=tab_label,
                        group=str(action.get("group") or "Actions"),
                        handler=handler,
                        preview=str(action.get("preview") or ""),
                        view=view,
                        confirm=bool(action.get("confirm", False)),
                        job_slot=str(action["job_slot"]) if action.get("job_slot") in {"build", "board"} else None,
                    )
                )
        return tuple(result)

    def _views(self, raw: Any) -> dict[str, PluginViewDefinition]:
        if raw is None:
            return {}
        if not isinstance(raw, list):
            raise ValueError("views must be a list")
        result: dict[str, PluginViewDefinition] = {}
        for view in raw:
            if not isinstance(view, dict):
                raise ValueError("view must be a mapping")
            view_id = self._required_text(view, "id")
            result[view_id] = PluginViewDefinition(
                view_id=view_id,
                label=str(view.get("label") or view_id),
                factory=self._required_text(view, "factory"),
            )
        return result

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        return None if value is None else int(value)


def plugin_discovery(plugins_dir: Path) -> PluginDiscovery:
    return PluginDiscovery(plugins_dir)
