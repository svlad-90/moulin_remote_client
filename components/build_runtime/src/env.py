"""Environment override helpers for configuration loading."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from components.config.api.profiles import (
    active_project,
    active_remote,
    sync_active_project,
    sync_active_remote,
)


def env_value(env: Mapping[str, str], name: str, default: str) -> str:
    return env.get(name, default)


def docker_image_from_env(env: Mapping[str, str], default: str) -> str:
    return env_value(env, "MOULIN_REMOTE_DOCKER_IMAGE", default)


def build_targets_from_env(env: Mapping[str, str], default: str) -> str:
    return env_value(env, "MOULIN_REMOTE_BUILD_TARGETS", default)


def auto_connect_enabled(env: Mapping[str, str]) -> bool:
    value = env.get("MOULIN_REMOTE_AUTO_CONNECT", "yes").strip().lower()
    return value not in {"0", "false", "no", "off"}


def apply_env_overrides(config: dict[str, Any], env: Mapping[str, str]) -> None:
    remote = active_remote(config)
    mapping = {
        "MOULIN_REMOTE_SSH_USER": "user",
        "MOULIN_REMOTE_SSH_HOST": "host",
    }
    for env_name, key in mapping.items():
        value = env.get(env_name)
        if value:
            remote[key] = value
    sync_active_remote(config)
    project_dir = env.get("MOULIN_REMOTE_PROJECT_DIR")
    if project_dir:
        active_project(config)["project_dir"] = project_dir
        sync_active_project(config)
    git_url = env.get("MOULIN_REMOTE_PROJECT_GIT_URL")
    if git_url:
        active_project(config)["git_url"] = git_url
        sync_active_project(config)
    git_ref = env.get("MOULIN_REMOTE_PROJECT_GIT_REF")
    if git_ref:
        active_project(config)["git_ref"] = git_ref
        sync_active_project(config)
