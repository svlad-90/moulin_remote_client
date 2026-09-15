"""Configuration value accessors."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from components.config.src import profiles as config_profiles


def config_path(config: dict[str, Any], key: str, app_dir: Path, section: str) -> Path:
    value = Path(config[section][key])
    return value if value.is_absolute() else app_dir / value


def inventory_output_path_for_config(config: dict[str, Any], app_dir: Path) -> Path:
    return config_path(config, "output", app_dir, "inventory")


def inventory_selection_path_for_config(config: dict[str, Any], app_dir: Path) -> Path:
    return config_path(config, "selection", app_dir, "inventory")


def mapping_selection_path_for_config(config: dict[str, Any], app_dir: Path) -> Path:
    return config_path(config, "mapping_selection", app_dir, "inventory")


def local_project_dir(config: dict[str, Any], project: dict[str, Any], app_dir: Path) -> Path:
    project_value = str(project.get("local_project_dir", "")).strip()
    value = Path(project_value or config["local"]["project_dir"])
    return value if value.is_absolute() else app_dir / value


def local_project_dir_for_config(config: dict[str, Any], app_dir: Path) -> Path:
    return local_project_dir(config, config_profiles.active_project(config), app_dir)


def ui_title(config: dict[str, Any]) -> str:
    return str(config.get("ui", {}).get("title", "Moulin Client"))


def profile_label(profile: dict[str, Any], fallback: str) -> str:
    return str(profile.get("label", profile.get("name", fallback)))


def host_spec(host: dict[str, Any]) -> str:
    return f"{host.get('user', '')}@{host.get('host', '')}"


def build_host_projects_dir(remote: dict[str, Any]) -> str:
    value = str(remote.get("projects_dir", "")).strip()
    if value:
        return value.rstrip("/")
    legacy = str(remote.get("project_dir", "")).strip().rstrip("/")
    if legacy:
        parent, _ = config_profiles.split_remote_project_path(legacy)
        return parent.rstrip("/")
    return ""


def project_dir_name(project: dict[str, Any]) -> str:
    return str(project.get("project_dir", "")).strip().strip("/")


def remote_project_dir(remote: dict[str, Any], project: dict[str, Any]) -> str:
    project_value = str(project.get("project_dir", "")).strip()
    if project_value.startswith("/"):
        return project_value.rstrip("/")
    projects_dir = build_host_projects_dir(remote)
    if projects_dir and project_value:
        return str(PurePosixPath(projects_dir) / project_value).rstrip("/")
    if project_value:
        return project_value.rstrip("/")
    legacy = str(remote.get("project_dir", "")).strip()
    return legacy.rstrip("/")


def board_work_dir(board_host: dict[str, Any]) -> str:
    return str(board_host.get("work_dir", "~/moulin-board-work")).strip().rstrip("/") or "~/moulin-board-work"


def board_type(board_host: dict[str, Any]) -> str:
    return str(board_host.get("type", "gen5_x5h")).strip() or "gen5_x5h"


def board_artifacts_dir(board_work_dir_value: str) -> str:
    return str(PurePosixPath(board_work_dir_value) / "artifacts")


def board_direct_copy_enabled(board_host: dict[str, Any]) -> bool:
    value = str(board_host.get("direct_copy", "no")).strip().lower()
    return value in {"1", "true", "yes", "on"}


def board_ufs_loadaddr(board_host: dict[str, Any]) -> str:
    return str(board_host.get("ufs_loadaddr", "")).strip()


def board_ufs_buffersize(board_host: dict[str, Any]) -> str:
    return str(board_host.get("ufs_buffersize", "")).strip()


def board_console_device(board_host: dict[str, Any]) -> str:
    return str(board_host.get("console_device", "")).strip()


def project_git_url(project: dict[str, Any], remote: dict[str, Any]) -> str:
    project_value = str(project.get("git_url", "")).strip()
    if project_value:
        return project_value
    return str(remote.get("git_url", "")).strip()


def project_git_ref(project: dict[str, Any]) -> str:
    return str(project.get("git_ref", "")).strip()


def host_user(host: dict[str, Any]) -> str:
    return str(host.get("user", "")).strip()


def host_host(host: dict[str, Any]) -> str:
    return str(host.get("host", "")).strip()


def host_has_ssh(host: dict[str, Any]) -> bool:
    return bool(host_user(host)) and bool(host_host(host))


def configured_docker_image(
    config: dict[str, Any],
    project: dict[str, Any],
    remote: dict[str, Any],
    default_docker_image: str,
) -> str:
    project_value = str(project.get("docker_image", "")).strip()
    if project_value:
        return project_value
    remote_value = str(remote.get("docker_image", "")).strip()
    if remote_value:
        return remote_value
    return str(config.get("docker", {}).get("image", default_docker_image))


def configured_dockerfile(
    config: dict[str, Any],
    project: dict[str, Any],
    remote: dict[str, Any],
    default_dockerfile: str,
) -> str:
    project_value = str(project.get("dockerfile", "")).strip()
    if project_value:
        return project_value
    remote_value = str(remote.get("dockerfile", "")).strip()
    if remote_value:
        return remote_value
    return str(config.get("docker", {}).get("dockerfile", default_dockerfile))


def moulin_manifest_name(
    config: dict[str, Any],
    project: dict[str, Any],
    remote: dict[str, Any],
    default_moulin_manifest: str,
) -> str:
    project_value = str(project.get("moulin_manifest", "")).strip()
    if project_value:
        return project_value
    remote_value = str(remote.get("moulin_manifest", "")).strip()
    if remote_value:
        return remote_value
    return str(config.get("moulin", {}).get("manifest", default_moulin_manifest))


def remote_label_for_config(config: dict[str, Any]) -> str:
    return profile_label(config_profiles.active_remote(config), "remote")


def remote_spec_for_config(config: dict[str, Any]) -> str:
    return host_spec(config_profiles.active_remote(config))


def board_host_label_for_config(config: dict[str, Any]) -> str:
    return profile_label(config_profiles.active_board_host(config), "board")


def board_host_spec_for_config(config: dict[str, Any]) -> str:
    return host_spec(config_profiles.active_board_host(config))


def build_host_projects_dir_for_config(config: dict[str, Any]) -> str:
    return build_host_projects_dir(config_profiles.active_remote(config))


def project_dir_name_for_config(config: dict[str, Any]) -> str:
    return project_dir_name(config_profiles.active_project(config))


def remote_project_dir_for_config(config: dict[str, Any]) -> str:
    return remote_project_dir(config_profiles.active_remote(config), config_profiles.active_project(config))


def board_work_dir_for_config(config: dict[str, Any]) -> str:
    return board_work_dir(config_profiles.active_board_host(config))


def board_type_for_config(config: dict[str, Any]) -> str:
    return board_type(config_profiles.active_board_host(config))


def board_artifacts_dir_for_config(config: dict[str, Any]) -> str:
    return board_artifacts_dir(board_work_dir_for_config(config))


def board_direct_copy_enabled_for_config(config: dict[str, Any]) -> bool:
    return board_direct_copy_enabled(config_profiles.active_board_host(config))


def board_ufs_loadaddr_for_config(config: dict[str, Any]) -> str:
    return board_ufs_loadaddr(config_profiles.active_board_host(config))


def board_ufs_buffersize_for_config(config: dict[str, Any]) -> str:
    return board_ufs_buffersize(config_profiles.active_board_host(config))


def board_console_device_for_config(config: dict[str, Any]) -> str:
    return board_console_device(config_profiles.active_board_host(config))


def project_git_url_for_config(config: dict[str, Any]) -> str:
    return project_git_url(config_profiles.active_project(config), config_profiles.active_remote(config))


def project_git_ref_for_config(config: dict[str, Any]) -> str:
    return project_git_ref(config_profiles.active_project(config))


def remote_user_for_config(config: dict[str, Any]) -> str:
    return host_user(config_profiles.active_remote(config))


def remote_host_for_config(config: dict[str, Any]) -> str:
    return host_host(config_profiles.active_remote(config))


def remote_has_user_for_config(config: dict[str, Any]) -> bool:
    return bool(remote_user_for_config(config))


def remote_has_host_for_config(config: dict[str, Any]) -> bool:
    return bool(remote_host_for_config(config))


def remote_has_ssh_for_config(config: dict[str, Any]) -> bool:
    return host_has_ssh(config_profiles.active_remote(config))


def board_host_user_for_config(config: dict[str, Any]) -> str:
    return host_user(config_profiles.active_board_host(config))


def board_host_host_for_config(config: dict[str, Any]) -> str:
    return host_host(config_profiles.active_board_host(config))


def board_host_has_ssh_for_config(config: dict[str, Any]) -> bool:
    return host_has_ssh(config_profiles.active_board_host(config))


def remote_has_project_dir_for_config(config: dict[str, Any]) -> bool:
    return bool(remote_project_dir_for_config(config))


def remote_project_config_ready_plan(config: dict[str, Any], *, connected: bool) -> dict[str, Any]:
    if not connected:
        return {"ready": False, "status": "connect to the build host first"}
    if not remote_has_project_dir_for_config(config):
        return {"ready": False, "status": "select remote project directory first"}
    return {"ready": True, "status": ""}


def configured_docker_image_for_config(config: dict[str, Any], default_docker_image: str = "") -> str:
    return configured_docker_image(
        config,
        config_profiles.active_project(config),
        config_profiles.active_remote(config),
        default_docker_image,
    )


def configured_dockerfile_for_config(config: dict[str, Any], default_dockerfile: str = "doc/Dockerfile") -> str:
    return configured_dockerfile(
        config,
        config_profiles.active_project(config),
        config_profiles.active_remote(config),
        default_dockerfile,
    )


def moulin_manifest_name_for_config(config: dict[str, Any], default_moulin_manifest: str = "product.yaml") -> str:
    return moulin_manifest_name(
        config,
        config_profiles.active_project(config),
        config_profiles.active_remote(config),
        default_moulin_manifest,
    )
