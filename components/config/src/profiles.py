"""Profile normalization helpers."""

from __future__ import annotations

import copy
from pathlib import PurePosixPath
from typing import Any


def empty_host_profile(name: str = "") -> dict[str, str]:
    return {
        "name": name,
        "label": name,
        "type": "gen5_x5h",
        "user": "",
        "host": "",
        "work_dir": "~/moulin-board-work",
        "direct_copy": "no",
        "console_device": "",
        "ufs_loadaddr": "",
        "ufs_buffersize": "",
        "tftp_root": "/srv/tftp",
        "nfs_root": "/srv/nfs",
        "deploy_subdir": "",
        "server_ip": "",
        "board_ip": "",
    }


def empty_remote_profile(name: str = "") -> dict[str, str]:
    profile = empty_host_profile(name)
    profile.update({
        "projects_dir": "",
        "work_dir": "",
        "git_url": "",
        "moulin_manifest": "",
        "dockerfile": "",
        "docker_image": "",
    })
    return profile


def is_blank_default_remote(remote: dict[str, Any]) -> bool:
    return (
        str(remote.get("name", "")) == "default"
        and str(remote.get("label", "")) in ("", "default", "remote")
        and not str(remote.get("user", "")).strip()
        and not str(remote.get("host", "")).strip()
        and not str(remote.get("project_dir", "")).strip()
        and not str(remote.get("projects_dir", "")).strip()
        and not str(remote.get("git_url", "")).strip()
    )


def split_remote_project_path(path: str) -> tuple[str, str]:
    value = path.strip().rstrip("/")
    if not value:
        return "", ""
    pure = PurePosixPath(value)
    parent = str(pure.parent)
    name = pure.name
    if parent == ".":
        return "", name
    return parent, name


def active_profile_index(profiles: list[dict[str, Any]], active_name: str) -> int:
    for index, profile in enumerate(profiles):
        if str(profile.get("name", "")) == active_name:
            return index
    return 0


def project_profiles_for_config(config: dict[str, Any]) -> list[dict[str, Any]]:
    return [project for project in config.get("projects", []) if isinstance(project, dict)]


def project_picker_row_model(project: dict[str, Any], *, active_project: str) -> dict[str, Any]:
    is_active = str(project.get("name", "")) == str(active_project)
    mark = "*" if is_active else " "
    return {
        "text": f"{mark} {project.get('label') or project.get('name')}",
        "active": is_active,
    }


def first_profile_name(profiles: list[dict[str, Any]]) -> str:
    for profile in profiles:
        if isinstance(profile, dict):
            return str(profile.get("name", ""))
    return ""


def profile_label_after_rename(label: str, old_name: str, new_name: str) -> str:
    if not str(label).strip() or str(label) == str(old_name):
        return str(new_name)
    return str(label)


def active_profile_name_after_rename(active_name: str, old_name: str, new_name: str) -> str:
    if str(active_name) == str(old_name):
        return str(new_name)
    return str(active_name)


def next_profile_name(profiles: list[dict[str, Any]], prefix: str) -> str:
    existing = {str(profile.get("name", "")) for profile in profiles}
    index = len(existing) + 1
    while f"{prefix}-{index}" in existing:
        index += 1
    return f"{prefix}-{index}"


def next_remote_name(remotes: list[dict[str, Any]]) -> str:
    return next_profile_name(remotes, "remote")


def next_board_host_name(hosts: list[dict[str, Any]]) -> str:
    return next_profile_name(hosts, "board")


def profile_name_exists(profiles: list[dict[str, Any]], name: str) -> bool:
    return any(isinstance(profile, dict) and str(profile.get("name", "")) == name for profile in profiles)


def add_remote_profile(config: dict[str, Any], name: str) -> dict[str, Any]:
    if not name:
        raise ValueError("Build host profile name is required")
    remotes = config.setdefault("remotes", [])
    if profile_name_exists(remotes, name):
        raise ValueError(f"Build host profile already exists: {name}")
    profile = empty_remote_profile(name)
    remotes.append(profile)
    sync_active_remote(config)
    return profile


def apply_add_remote_profile_for_config(config: dict[str, Any], name: str) -> dict[str, Any]:
    clean_name = name.strip()
    add_remote_profile(config, clean_name)
    return {
        "status": f"Build host profile added: {clean_name}",
    }


def delete_remote_profile(config: dict[str, Any], name: str) -> bool:
    was_active = str(config.get("active_remote", "")) == name
    config["remotes"] = [
        profile
        for profile in config.get("remotes", [])
        if not (isinstance(profile, dict) and str(profile.get("name", "")) == name)
    ]
    if was_active:
        config["active_remote"] = first_profile_name(config.get("remotes", []))
    sync_active_remote(config)
    return was_active


def apply_delete_remote_profile_for_config(config: dict[str, Any], remote: dict[str, Any]) -> dict[str, Any]:
    name = str(remote.get("name", ""))
    active_changed = delete_remote_profile(config, name)
    return {
        "status": f"Build host profile deleted: {name}",
        "connection_reset": active_changed,
        "preflight_reset": active_changed,
    }


def set_active_remote_profile(config: dict[str, Any], name: str) -> bool:
    if str(config.get("active_remote", "")) == name:
        return False
    config["active_remote"] = name
    sync_active_remote(config)
    return True


def apply_active_remote_profile_for_config(config: dict[str, Any], remote: dict[str, Any]) -> dict[str, Any]:
    name = str(remote.get("name", ""))
    if not set_active_remote_profile(config, name):
        return {
            "changed": False,
            "status": "selected build host is already active",
            "connection_reset": False,
            "preflight_reset": False,
        }
    return {
        "changed": True,
        "status": f"Active build host: {name}",
        "connection_reset": True,
        "preflight_reset": True,
    }


def update_remote_profile_field(
    config: dict[str, Any],
    profile: dict[str, Any],
    key: str,
    value: str,
) -> None:
    old_name = str(profile.get("name", ""))
    if key == "name":
        if not value:
            raise ValueError("Build host profile name is required")
        if value != old_name and profile_name_exists(config.get("remotes", []), value):
            raise ValueError(f"Build host profile already exists: {value}")
    profile[key] = value
    if key == "name":
        profile["label"] = profile_label_after_rename(str(profile.get("label", "")), old_name, value)
        config["active_remote"] = active_profile_name_after_rename(
            str(config.get("active_remote", "")),
            old_name,
            value,
        )
    sync_active_remote(config)


def add_board_host_profile(config: dict[str, Any], name: str) -> dict[str, Any]:
    if not name:
        raise ValueError("Board host profile name is required")
    hosts = config.setdefault("board_hosts", [])
    if profile_name_exists(hosts, name):
        raise ValueError(f"Board host profile already exists: {name}")
    profile = empty_host_profile(name)
    hosts.append(profile)
    sync_active_board_host(config)
    return profile


def apply_add_board_host_profile_for_config(config: dict[str, Any], name: str) -> dict[str, Any]:
    clean_name = name.strip()
    add_board_host_profile(config, clean_name)
    return {
        "status": f"Board host profile added: {clean_name}",
    }


def delete_board_host_profile(config: dict[str, Any], name: str) -> bool:
    was_active = str(config.get("active_board_host", "")) == name
    config["board_hosts"] = [
        profile
        for profile in config.get("board_hosts", [])
        if not (isinstance(profile, dict) and str(profile.get("name", "")) == name)
    ]
    if was_active:
        config["active_board_host"] = first_profile_name(config.get("board_hosts", []))
    sync_active_board_host(config)
    return was_active


def apply_delete_board_host_profile_for_config(config: dict[str, Any], host: dict[str, Any]) -> dict[str, Any]:
    name = str(host.get("name", ""))
    active_changed = delete_board_host_profile(config, name)
    return {
        "status": f"Board host profile deleted: {name}",
        "connection_reset": active_changed,
    }


def set_active_board_host_profile(config: dict[str, Any], name: str) -> bool:
    if str(config.get("active_board_host", "")) == name:
        return False
    config["active_board_host"] = name
    sync_active_board_host(config)
    return True


def apply_active_board_host_profile_for_config(config: dict[str, Any], host: dict[str, Any]) -> dict[str, Any]:
    name = str(host.get("name", ""))
    if not set_active_board_host_profile(config, name):
        return {
            "changed": False,
            "status": "selected board host is already active",
            "connection_reset": False,
        }
    return {
        "changed": True,
        "status": f"Active board host: {name}",
        "connection_reset": True,
    }


def update_board_host_profile_field(
    config: dict[str, Any],
    profile: dict[str, Any],
    key: str,
    value: str,
) -> None:
    old_name = str(profile.get("name", ""))
    if key == "name":
        if not value:
            raise ValueError("Board host profile name is required")
        if value != old_name and profile_name_exists(config.get("board_hosts", []), value):
            raise ValueError(f"Board host profile already exists: {value}")
    profile[key] = value
    if key == "name":
        profile["label"] = profile_label_after_rename(str(profile.get("label", "")), old_name, value)
        config["active_board_host"] = active_profile_name_after_rename(
            str(config.get("active_board_host", "")),
            old_name,
            value,
        )
    sync_active_board_host(config)


def normalize_remote_profiles(config: dict[str, Any]) -> None:
    remotes = config.get("remotes")
    if not isinstance(remotes, list):
        remote = dict(config.get("remote", {}))
        remote.setdefault("name", str(remote.get("label") or ""))
        remote.setdefault("label", str(remote.get("name") or "remote"))
        remote.setdefault("user", "")
        remote.setdefault("host", "")
        projects_dir, _ = split_remote_project_path(str(remote.get("project_dir", "")))
        remote.setdefault("projects_dir", projects_dir)
        remote.setdefault("git_url", "")
        remote.setdefault("moulin_manifest", "")
        remote.setdefault("dockerfile", "")
        remote.setdefault("docker_image", "")
        remotes = [] if is_blank_default_remote(remote) else [remote]
        config["remotes"] = remotes
    remotes = [remote for remote in remotes if isinstance(remote, dict) and not is_blank_default_remote(remote)]
    config["remotes"] = remotes
    for index, remote in enumerate(remotes):
        remote.setdefault("name", str(remote.get("label") or ""))
        remote.setdefault("label", str(remote.get("name") or f"remote-{index + 1}"))
        remote.setdefault("user", "")
        remote.setdefault("host", "")
        projects_dir, _ = split_remote_project_path(str(remote.get("project_dir", "")))
        remote.setdefault("projects_dir", projects_dir)
        remote.setdefault("git_url", "")
        remote.setdefault("moulin_manifest", "")
        remote.setdefault("dockerfile", "")
        remote.setdefault("docker_image", "")
    if not remotes:
        config["active_remote"] = ""
        sync_active_remote(config)
        return
    active = str(config.get("active_remote") or remotes[0].get("name") or "")
    if not any(str(remote.get("name", "")) == active for remote in remotes if isinstance(remote, dict)):
        active = str(remotes[0].get("name") or "")
    config["active_remote"] = active
    sync_active_remote(config)


def active_remote(config: dict[str, Any]) -> dict[str, Any]:
    normalize_remote_profiles(config) if "remotes" not in config else None
    active = str(config.get("active_remote", ""))
    for remote in config.get("remotes", []):
        if isinstance(remote, dict) and str(remote.get("name", "")) == active:
            return remote
    return empty_remote_profile("")


def sync_active_remote(config: dict[str, Any]) -> None:
    config["remote"] = active_remote(config)


def is_blank_host_profile(host: dict[str, Any]) -> bool:
    return (
        str(host.get("name", "")) in ("", "default")
        and str(host.get("label", "")) in ("", "default", "remote", "board")
        and not str(host.get("user", "")).strip()
        and not str(host.get("host", "")).strip()
    )


def normalize_board_host_profiles(config: dict[str, Any]) -> None:
    hosts = config.get("board_hosts")
    if not isinstance(hosts, list):
        seed = config.get("board_host")
        if isinstance(seed, dict):
            host = dict(seed)
        else:
            remote = active_remote(config)
            host = empty_host_profile(str(remote.get("name", "")) or "board-1")
            host["label"] = str(remote.get("label", "")) or str(host["name"])
            host["user"] = str(remote.get("user", ""))
            host["host"] = str(remote.get("host", ""))
        hosts = [] if is_blank_host_profile(host) else [host]
        config["board_hosts"] = hosts
    hosts = [host for host in hosts if isinstance(host, dict) and not is_blank_host_profile(host)]
    config["board_hosts"] = hosts
    for index, host in enumerate(hosts):
        host.setdefault("name", str(host.get("label") or f"board-{index + 1}"))
        host.setdefault("label", str(host.get("name") or f"board-{index + 1}"))
        host.setdefault("type", "gen5_x5h")
        host.setdefault("user", "")
        host.setdefault("host", "")
        host.setdefault("work_dir", "~/moulin-board-work")
        host.setdefault("direct_copy", "no")
        host.setdefault("console_device", "")
        host.setdefault("ufs_loadaddr", "")
        host.setdefault("ufs_buffersize", "")
    if not hosts:
        config["active_board_host"] = ""
        sync_active_board_host(config)
        return
    active = str(config.get("active_board_host") or hosts[0].get("name") or "")
    if not any(str(host.get("name", "")) == active for host in hosts if isinstance(host, dict)):
        active = str(hosts[0].get("name") or "")
    config["active_board_host"] = active
    sync_active_board_host(config)


def active_board_host(config: dict[str, Any]) -> dict[str, Any]:
    normalize_board_host_profiles(config) if "board_hosts" not in config else None
    active = str(config.get("active_board_host", ""))
    for host in config.get("board_hosts", []):
        if isinstance(host, dict) and str(host.get("name", "")) == active:
            return host
    return empty_host_profile("")


def sync_active_board_host(config: dict[str, Any]) -> None:
    config["board_host"] = active_board_host(config)


def empty_project_profile(name: str = "") -> dict[str, Any]:
    return {
        "name": name,
        "label": name,
        "project_dir": "",
        "local_project_dir": "",
        "git_url": "",
        "git_ref": "",
        "moulin_manifest": "",
        "dockerfile": "",
        "docker_image": "",
        "parameters": {},
        "targets": "",
        "board_artifacts": "",
        "mappings": [],
        "active_mappings": [],
    }


def add_project_profile_from_current(
    config: dict[str, Any],
    name: str,
    *,
    parameters: dict[str, Any],
    targets: str,
    board_artifacts: str,
    docker_image: str,
) -> dict[str, Any]:
    if not name:
        raise ValueError("Project profile name is required")
    projects = [project for project in config.setdefault("projects", []) if isinstance(project, dict)]
    if profile_name_exists(projects, name):
        raise ValueError(f"Project already exists: {name}")
    project = dict(active_project(config))
    project["name"] = name
    project["label"] = name
    project["parameters"] = dict(parameters)
    project["targets"] = targets
    project["board_artifacts"] = board_artifacts
    project["docker_image"] = docker_image
    projects.append(project)
    config["projects"] = projects
    config["active_project"] = name
    sync_active_project(config)
    return project


def apply_add_project_profile_for_config(
    config: dict[str, Any],
    name: str,
    *,
    parameters: dict[str, Any],
    targets: str,
    board_artifacts: str,
    docker_image: str,
) -> dict[str, Any]:
    clean_name = name.strip()
    add_project_profile_from_current(
        config,
        clean_name,
        parameters=parameters,
        targets=targets,
        board_artifacts=board_artifacts,
        docker_image=docker_image,
    )
    return {
        "status": f"Project added: {clean_name}",
        "runtime_reload": True,
    }


def can_delete_project_profile(config: dict[str, Any]) -> bool:
    projects = [project for project in config.get("projects", []) if isinstance(project, dict)]
    return len(projects) > 1


def delete_project_profile(config: dict[str, Any], name: str) -> bool:
    projects = [project for project in config.get("projects", []) if isinstance(project, dict)]
    if len(projects) <= 1:
        raise ValueError("Cannot delete the only project")
    was_active = str(config.get("active_project", "")) == name
    remaining = [project for project in projects if str(project.get("name", "")) != name]
    config["projects"] = remaining
    if was_active:
        config["active_project"] = first_profile_name(remaining)
    sync_active_project(config)
    return was_active


def apply_delete_project_profile_for_config(config: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    name = str(project.get("name", ""))
    active_changed = delete_project_profile(config, name)
    return {
        "status": f"Project deleted: {name}",
        "runtime_reload": active_changed,
        "preflight_reset": active_changed,
    }


def set_active_project_profile(config: dict[str, Any], name: str) -> bool:
    if str(config.get("active_project", "")) == name:
        return False
    config["active_project"] = name
    sync_active_project(config)
    return True


def apply_active_project_profile_for_config(config: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    name = str(project.get("name", ""))
    if not set_active_project_profile(config, name):
        return {
            "changed": False,
            "status": "selected project is already active",
            "runtime_reload": False,
            "preflight_reset": False,
        }
    return {
        "changed": True,
        "status": f"Active project: {project.get('label') or name}",
        "runtime_reload": True,
        "preflight_reset": True,
    }


def apply_project_picker_selection_for_config(config: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    name = str(project.get("name", ""))
    set_active_project_profile(config, name)
    return {
        "status": f"Active project: {project.get('label') or name}",
        "runtime_reload": True,
        "save": True,
    }


def update_project_profile_field(
    config: dict[str, Any],
    project: dict[str, Any],
    key: str,
    value: str,
    *,
    projects_dir: str = "",
) -> None:
    old_name = str(project.get("name", ""))
    if key == "name":
        if not value:
            raise ValueError("Project profile name is required")
        if value != old_name and profile_name_exists(config.get("projects", []), value):
            raise ValueError(f"Project already exists: {value}")
    if projects_dir:
        active_remote(config)["projects_dir"] = projects_dir
        sync_active_remote(config)
    project[key] = value
    if key == "name":
        project["label"] = profile_label_after_rename(str(project.get("label", "")), old_name, value)
        config["active_project"] = active_profile_name_after_rename(
            str(config.get("active_project", "")),
            old_name,
            value,
        )
    if active_project(config) is project:
        sync_active_project(config)


def set_active_project_targets(config: dict[str, Any], targets: str) -> None:
    active_project(config)["targets"] = targets
    sync_active_project(config)


def apply_active_project_targets_for_config(config: dict[str, Any], targets: str) -> dict[str, Any]:
    set_active_project_targets(config, targets)
    return {
        "status": "Build target selection saved",
        "runtime_reload": True,
    }


def set_active_project_board_artifacts(config: dict[str, Any], board_artifacts: str) -> None:
    active_project(config)["board_artifacts"] = board_artifacts
    sync_active_project(config)


def apply_active_project_board_artifacts_for_config(config: dict[str, Any], board_artifacts: str) -> dict[str, Any]:
    set_active_project_board_artifacts(config, board_artifacts)
    return {
        "status": "Board artifact selection saved",
        "runtime_reload": True,
    }


def normalize_project_profiles(
    config: dict[str, Any],
    *,
    legacy_settings: dict[str, Any] | None = None,
    default_build_targets: str = "",
    default_moulin_manifest: str = "product.yaml",
    default_dockerfile: str = "doc/Dockerfile",
) -> None:
    projects = config.get("projects")
    settings = legacy_settings or {}
    if not isinstance(projects, list):
        remote = active_remote(config)
        legacy_project_dir = str(remote.get("project_dir") or config.get("project", {}).get("project_dir", ""))
        legacy_projects_dir, legacy_project_name = split_remote_project_path(legacy_project_dir)
        if legacy_projects_dir and not str(remote.get("projects_dir", "")).strip():
            remote["projects_dir"] = legacy_projects_dir
        project = {
            "name": str(config.get("active_project") or config.get("project", {}).get("name") or "default"),
            "label": str(config.get("project", {}).get("label") or config.get("active_project") or "default"),
            "project_dir": legacy_project_name or legacy_project_dir,
            "local_project_dir": str(config.get("local", {}).get("project_dir", "workspace/project-overlay")),
            "git_url": str(remote.get("git_url") or config.get("project", {}).get("git_url", "")),
            "git_ref": str(config.get("project", {}).get("git_ref", "")),
            "moulin_manifest": str(remote.get("moulin_manifest") or config.get("moulin", {}).get("manifest", default_moulin_manifest)),
            "dockerfile": str(remote.get("dockerfile") or config.get("docker", {}).get("dockerfile", default_dockerfile)),
            "docker_image": str(settings.get("docker_image") or remote.get("docker_image") or config.get("docker", {}).get("image", "")),
            "parameters": dict(settings.get("parameters", {})) if isinstance(settings.get("parameters", {}), dict) else {},
            "targets": str(settings.get("targets", default_build_targets)),
            "board_artifacts": str(settings.get("targets", default_build_targets)),
        }
        projects = [project]
        config["projects"] = projects
    projects = [project for project in projects if isinstance(project, dict)]
    config["projects"] = projects
    if not projects:
        config["projects"] = [empty_project_profile("default")]
        projects = config["projects"]
    for index, project in enumerate(projects):
        project.setdefault("name", str(project.get("label") or f"project-{index + 1}"))
        project.setdefault("label", str(project.get("name") or f"project-{index + 1}"))
        if "project_dir" not in project:
            project["project_dir"] = str(config.get("project", {}).get("project_dir", ""))
        project_dir = str(project.get("project_dir", "")).strip()
        if project_dir.startswith("/"):
            projects_dir, project_name = split_remote_project_path(project_dir)
            if projects_dir and not str(active_remote(config).get("projects_dir", "")).strip():
                active_remote(config)["projects_dir"] = projects_dir
                sync_active_remote(config)
            project["project_dir"] = project_name or project_dir
        project.setdefault("local_project_dir", str(config.get("local", {}).get("project_dir", "workspace/project-overlay")))
        project.setdefault("git_url", str(config.get("project", {}).get("git_url", "")))
        project.setdefault("git_ref", str(config.get("project", {}).get("git_ref", "")))
        project.setdefault("moulin_manifest", str(config.get("moulin", {}).get("manifest", default_moulin_manifest)))
        project.setdefault("dockerfile", str(config.get("docker", {}).get("dockerfile", default_dockerfile)))
        project.setdefault("docker_image", str(config.get("docker", {}).get("image", "")))
        if not isinstance(project.get("parameters"), dict):
            project["parameters"] = {}
        project.setdefault("targets", default_build_targets)
        project.setdefault("board_artifacts", str(project.get("targets", "")))
        if not isinstance(project.get("mappings"), list):
            legacy_mappings = config.get("mappings", [])
            project["mappings"] = copy.deepcopy(legacy_mappings) if isinstance(legacy_mappings, list) else []
        if not isinstance(project.get("active_mappings"), list):
            project["active_mappings"] = []
    active = str(config.get("active_project") or projects[0].get("name") or "")
    if not any(str(project.get("name", "")) == active for project in projects):
        active = str(projects[0].get("name") or "")
    config["active_project"] = active
    sync_active_project(config)


def active_project(config: dict[str, Any]) -> dict[str, Any]:
    normalize_project_profiles(config) if "projects" not in config else None
    active = str(config.get("active_project", ""))
    for project in config.get("projects", []):
        if isinstance(project, dict) and str(project.get("name", "")) == active:
            return project
    return empty_project_profile("")


def sync_active_project(config: dict[str, Any]) -> None:
    project = active_project(config)
    config["project"] = project
    config.setdefault("local", {})["project_dir"] = str(project.get("local_project_dir", ""))
    config.setdefault("moulin", {})["manifest"] = str(project.get("moulin_manifest", ""))
    config.setdefault("docker", {})["dockerfile"] = str(project.get("dockerfile", ""))
    config.setdefault("docker", {})["image"] = str(project.get("docker_image", ""))
