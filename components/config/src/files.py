"""Configuration file IO helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from components.build_runtime.api.env import apply_env_overrides
from components.config.src.profiles import (
    normalize_board_host_profiles,
    normalize_project_profiles,
    normalize_remote_profiles,
    sync_active_board_host,
    sync_active_project,
    sync_active_remote,
)


CONFIG_SAVE_KEYS = (
    "remote",
    "remotes",
    "active_remote",
    "board_host",
    "board_hosts",
    "active_board_host",
    "project",
    "projects",
    "active_project",
    "local",
    "moulin",
    "docker",
    "state",
    "inventory",
    "mappings",
    "exclude",
    "ui",
)


def load_config_file(
    path: Path,
    example_path: Path,
    *,
    prepare: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    source = path if path.exists() else example_path
    with source.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    config["__config_path"] = str(path)
    prepare(config)
    return config


def sync_config_profiles(config: dict[str, Any]) -> None:
    sync_active_remote(config)
    sync_active_board_host(config)
    sync_active_project(config)


def prepare_loaded_config(
    config: dict[str, Any],
    *,
    env: dict[str, str],
    legacy_settings: dict[str, Any] | None = None,
    default_build_targets: str = "",
    default_moulin_manifest: str = "product.yaml",
    default_dockerfile: str = "doc/Dockerfile",
) -> None:
    normalize_remote_profiles(config)
    normalize_board_host_profiles(config)
    normalize_project_profiles(
        config,
        legacy_settings=legacy_settings,
        default_build_targets=default_build_targets,
        default_moulin_manifest=default_moulin_manifest,
        default_dockerfile=default_dockerfile,
    )
    apply_env_overrides(config, env)
    sync_config_profiles(config)


def save_config_file(
    config: dict[str, Any],
    default_path: Path,
    *,
    sync: Callable[[dict[str, Any]], None],
) -> None:
    if "__config_path" not in config:
        raise RuntimeError("Refusing to save config without __config_path")
    path = Path(str(config.get("__config_path", default_path)))
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {key: value for key, value in config.items() if not key.startswith("__")}
    sync(config)
    for key in CONFIG_SAVE_KEYS:
        if key in config:
            data[key] = config[key]
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
