"""Build settings helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_settings_from_project(
    project: dict[str, Any],
    legacy: dict[str, Any],
    default_targets: str,
) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "parameters": dict(project.get("parameters", {})) if isinstance(project.get("parameters", {}), dict) else {},
        "targets": str(project.get("targets", default_targets)),
        "docker_image": str(project.get("docker_image", "")),
    }
    if legacy:
        settings["parameters"] = (
            {**dict(legacy.get("parameters", {})), **settings["parameters"]}
            if isinstance(legacy.get("parameters", {}), dict)
            else settings["parameters"]
        )
        settings["targets"] = settings["targets"] or str(legacy.get("targets", ""))
        settings["docker_image"] = settings["docker_image"] or str(legacy.get("docker_image", ""))
    return settings


def apply_build_settings_to_project(project: dict[str, Any], settings: dict[str, Any]) -> None:
    if isinstance(settings.get("parameters"), dict):
        project["parameters"] = dict(settings["parameters"])
    project["targets"] = str(settings.get("targets", ""))
    project["docker_image"] = str(settings.get("docker_image", ""))


def read_build_settings_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def read_legacy_build_settings_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_build_settings_file(path: Path, settings: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8")
