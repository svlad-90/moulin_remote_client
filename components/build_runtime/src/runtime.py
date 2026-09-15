"""Runtime-level config orchestration helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from components.build_runtime.api import env as config_env
from components.build_runtime.api import settings as build_settings
from components.config.api import accessors, files, profiles


def legacy_build_settings(config: dict[str, Any], app_dir: Path) -> dict[str, Any]:
    try:
        path = accessors.config_path(config, "build_settings", app_dir, "state")
    except KeyError:
        return {}
    return build_settings.read_legacy_build_settings_file(path)


def prepare_loaded_runtime_config(
    config: dict[str, Any],
    *,
    app_dir: Path,
    env: Mapping[str, str],
    default_build_targets: str,
    default_moulin_manifest: str,
    default_dockerfile: str,
) -> None:
    files.prepare_loaded_config(
        config,
        env=dict(env),
        legacy_settings=legacy_build_settings(config, app_dir),
        default_build_targets=default_build_targets,
        default_moulin_manifest=default_moulin_manifest,
        default_dockerfile=default_dockerfile,
    )


def load_runtime_config(
    path: Path,
    example_path: Path,
    *,
    app_dir: Path,
    env: Mapping[str, str],
    default_build_targets: str,
    default_moulin_manifest: str,
    default_dockerfile: str,
) -> dict[str, Any]:
    return files.load_config_file(
        path,
        example_path,
        prepare=lambda config: prepare_loaded_runtime_config(
            config,
            app_dir=app_dir,
            env=env,
            default_build_targets=default_build_targets,
            default_moulin_manifest=default_moulin_manifest,
            default_dockerfile=default_dockerfile,
        ),
    )


def load_runtime_config_for_env(
    path: Path,
    example_path: Path,
    *,
    app_dir: Path,
    env: Mapping[str, str],
    default_build_targets: str,
    default_moulin_manifest: str,
    default_dockerfile: str,
) -> dict[str, Any]:
    return load_runtime_config(
        path,
        example_path,
        app_dir=app_dir,
        env=env,
        default_build_targets=config_env.build_targets_from_env(env, default_build_targets),
        default_moulin_manifest=default_moulin_manifest,
        default_dockerfile=default_dockerfile,
    )


def save_runtime_config(config: dict[str, Any], default_path: Path) -> None:
    files.save_config_file(config, default_path, sync=files.sync_config_profiles)


def normalize_runtime_project_profiles(
    config: dict[str, Any],
    *,
    app_dir: Path,
    default_build_targets: str,
    default_moulin_manifest: str,
    default_dockerfile: str,
) -> None:
    profiles.normalize_project_profiles(
        config,
        legacy_settings=legacy_build_settings(config, app_dir),
        default_build_targets=default_build_targets,
        default_moulin_manifest=default_moulin_manifest,
        default_dockerfile=default_dockerfile,
    )


def load_runtime_build_settings(config: dict[str, Any], app_dir: Path, default_build_targets: str) -> dict[str, Any]:
    project = profiles.active_project(config)
    if project:
        return build_settings.build_settings_from_project(
            project,
            legacy_build_settings(config, app_dir),
            default_build_targets,
        )
    try:
        path = accessors.config_path(config, "build_settings", app_dir, "state")
    except KeyError:
        return {}
    return build_settings.read_build_settings_file(path)


def save_runtime_build_settings(config: dict[str, Any], settings: dict[str, Any], app_dir: Path, default_path: Path) -> None:
    project = profiles.active_project(config)
    if project:
        build_settings.apply_build_settings_to_project(project, settings)
        profiles.sync_active_project(config)
        save_runtime_config(config, default_path)
    path = accessors.config_path(config, "build_settings", app_dir, "state")
    build_settings.write_build_settings_file(path, settings)


def save_current_runtime_build_settings(
    config: dict[str, Any],
    *,
    parameters: dict[str, Any],
    targets: str,
    docker_image: str,
    app_dir: Path,
    default_path: Path,
) -> None:
    save_runtime_build_settings(
        config,
        {
            "parameters": parameters,
            "targets": targets,
            "docker_image": docker_image,
        },
        app_dir,
        default_path,
    )


def build_runtime_context_for_config(
    config: dict[str, Any],
    *,
    app_dir: Path,
    env: Mapping[str, str],
    default_docker_image: str,
    default_build_targets: str,
    default_parameters: Callable[[], dict[str, str]],
) -> dict[str, Any]:
    env_build_targets = config_env.build_targets_from_env(env, default_build_targets)
    settings = load_runtime_build_settings(config, app_dir, env_build_targets)
    docker_image = (
        accessors.configured_docker_image_for_config(
            config,
            config_env.docker_image_from_env(env, default_docker_image),
        )
        or str(settings.get("docker_image", ""))
    )
    if env.get("MOULIN_REMOTE_DOCKER_IMAGE"):
        docker_image = config_env.docker_image_from_env(env, default_docker_image)

    build_params = default_parameters()
    build_params.update({str(key): str(value) for key, value in settings.get("parameters", {}).items()})

    build_targets = str(settings.get("targets", env_build_targets))
    if env.get("MOULIN_REMOTE_BUILD_TARGETS"):
        build_targets = env_build_targets

    return {
        "docker_image": docker_image,
        "build_params": build_params,
        "build_targets": build_targets,
        "board_artifacts": str(profiles.active_project(config).get("board_artifacts", "")) or build_targets,
    }
