"""Profile normalization helpers."""

from __future__ import annotations

import copy
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4


def new_profile_id() -> str:
    return str(uuid4())


def ensure_profile_id(profile: dict[str, Any]) -> str:
    profile_id = str(profile.get("id") or "")
    if not profile_id:
        profile_id = new_profile_id()
        profile["id"] = profile_id
    return profile_id


def profile_by_reference(
    profiles: list[dict[str, Any]],
    reference: str,
) -> dict[str, Any] | None:
    """Resolve an ID, accepting a name only while migrating old configuration."""
    value = str(reference or "")
    for profile in profiles:
        if str(profile.get("id") or "") == value:
            return profile
    for profile in profiles:
        if str(profile.get("name") or "") == value:
            return profile
    return None


def empty_host_profile(name: str = "") -> dict[str, Any]:
    return {
        "id": new_profile_id(),
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
        "mac_address": "",
        "commands": {},
    }


def empty_board_access_host(name: str = "") -> dict[str, Any]:
    return {
        "id": new_profile_id(),
        "name": name,
        "label": name,
        "user": "",
        "host": "",
        "work_dir": "~/moulin-board-work",
        "direct_copy": "no",
        "tftp_root": "/srv/tftp",
        "nfs_root": "/srv/nfs",
        "deploy_subdir": "",
        "server_ip": "",
        "boards": [],
    }


def empty_board(name: str = "") -> dict[str, Any]:
    return {
        "id": new_profile_id(),
        "board_host_id": "",
        "name": name,
        "label": name,
        "type": "gen5_x5h",
        "console_device": "",
        "ufs_loadaddr": "",
        "ufs_buffersize": "",
        "camera_stream_url": "",
        "board_ip": "",
        "mac_address": "",
        "commands": {},
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


def active_profile_index(profiles: list[dict[str, Any]], active_reference: str) -> int:
    for index, profile in enumerate(profiles):
        if str(profile.get("id") or "") == active_reference:
            return index
    for index, profile in enumerate(profiles):
        if str(profile.get("name") or "") == active_reference:
            return index
    return 0


def project_profiles_for_config(config: dict[str, Any]) -> list[dict[str, Any]]:
    return [project for project in config.get("projects", []) if isinstance(project, dict)]


def project_picker_row_model(project: dict[str, Any], *, active_project: str) -> dict[str, Any]:
    is_active = str(active_project) in {
        str(project.get("id") or ""),
        str(project.get("name") or ""),
    }
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


def first_profile_id(profiles: list[dict[str, Any]]) -> str:
    for profile in profiles:
        if isinstance(profile, dict):
            return ensure_profile_id(profile)
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


def next_board_name(host: dict[str, Any]) -> str:
    return next_profile_name([item for item in host.get("boards", []) if isinstance(item, dict)], "board")


def profile_name_exists(profiles: list[dict[str, Any]], name: str) -> bool:
    return any(isinstance(profile, dict) and str(profile.get("name", "")) == name for profile in profiles)


def add_remote_profile(config: dict[str, Any], name: str) -> dict[str, Any]:
    if not name:
        raise ValueError("Build host profile name is required")
    remotes = config.setdefault("remotes", [])
    for remote in remotes:
        if isinstance(remote, dict):
            ensure_profile_id(remote)
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
    profile = profile_by_reference(config.get("remotes", []), name)
    profile_id = ensure_profile_id(profile) if profile is not None else name
    active = profile_by_reference(config.get("remotes", []), str(config.get("active_remote", "")))
    was_active = active is profile
    config["remotes"] = [
        item
        for item in config.get("remotes", [])
        if not (isinstance(item, dict) and ensure_profile_id(item) == profile_id)
    ]
    if was_active:
        config["active_remote"] = first_profile_id(config.get("remotes", []))
    sync_active_remote(config)
    return was_active


def apply_delete_remote_profile_for_config(config: dict[str, Any], remote: dict[str, Any]) -> dict[str, Any]:
    name = str(remote.get("name", ""))
    active_changed = delete_remote_profile(config, ensure_profile_id(remote))
    return {
        "status": f"Build host profile deleted: {name}",
        "connection_reset": active_changed,
        "preflight_reset": active_changed,
    }


def set_active_remote_profile(config: dict[str, Any], name: str) -> bool:
    profile = profile_by_reference(config.get("remotes", []), name)
    if profile is None:
        raise ValueError(f"Unknown build host: {name}")
    profile_id = ensure_profile_id(profile)
    current = profile_by_reference(config.get("remotes", []), str(config.get("active_remote", "")))
    current_id = ensure_profile_id(current) if current is not None else ""
    if current_id == profile_id:
        config["active_remote"] = profile_id
        return False
    config["active_remote"] = profile_id
    sync_active_remote(config)
    return True


def apply_active_remote_profile_for_config(config: dict[str, Any], remote: dict[str, Any]) -> dict[str, Any]:
    name = str(remote.get("name", ""))
    if not set_active_remote_profile(config, ensure_profile_id(remote)):
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
    active_remote(config)
    old_name = str(profile.get("name", ""))
    if key == "name":
        if not value:
            raise ValueError("Build host profile name is required")
        if value != old_name and profile_name_exists(config.get("remotes", []), value):
            raise ValueError(f"Build host profile already exists: {value}")
    profile[key] = value
    if key == "name":
        profile["label"] = profile_label_after_rename(str(profile.get("label", "")), old_name, value)
    sync_active_remote(config)


def add_board_host_profile(config: dict[str, Any], name: str) -> dict[str, Any]:
    if not name:
        raise ValueError("Board host profile name is required")
    hosts = config.setdefault("board_hosts", [])
    for host in hosts:
        if not isinstance(host, dict):
            continue
        host_id = ensure_profile_id(host)
        for board in host.get("boards", []):
            if isinstance(board, dict):
                ensure_profile_id(board)
                board["board_host_id"] = host_id
    if profile_name_exists(hosts, name):
        raise ValueError(f"Board host profile already exists: {name}")
    profile = empty_board_access_host(name)
    hosts.append(profile)
    active_board_access_host(config)
    sync_active_board_host(config)
    return profile


def apply_add_board_host_profile_for_config(config: dict[str, Any], name: str) -> dict[str, Any]:
    clean_name = name.strip()
    add_board_host_profile(config, clean_name)
    return {
        "status": f"Board host profile added: {clean_name}",
    }


def add_board(config: dict[str, Any], host: dict[str, Any], name: str) -> dict[str, Any]:
    if not name:
        raise ValueError("Board name is required")
    if any(str(board.get("name", "")) == name for board in host.get("boards", [])):
        raise ValueError(f"Board already exists on this host: {name}")
    board = empty_board(name)
    board["board_host_id"] = ensure_profile_id(host)
    host.setdefault("boards", []).append(board)
    if not str(config.get("active_board") or ""):
        config["active_board_host"] = ensure_profile_id(host)
        config["active_board"] = ensure_profile_id(board)
    sync_active_board_host(config)
    return board


def delete_board(config: dict[str, Any], host: dict[str, Any], name: str) -> bool:
    board = profile_by_reference(board_profiles(config), name)
    board_id = ensure_profile_id(board) if board is not None else name
    current = profile_by_reference(board_profiles(config), str(config.get("active_board") or ""))
    was_active = current is board
    host["boards"] = [
        item
        for item in host.get("boards", [])
        if not (isinstance(item, dict) and ensure_profile_id(item) == board_id)
    ]
    if was_active:
        remaining = board_profiles(config)
        selected = remaining[0] if remaining else empty_board("")
        config["active_board"] = ensure_profile_id(selected) if remaining else ""
        selected_host = board_host_for_board(config, str(config["active_board"]))
        config["active_board_host"] = ensure_profile_id(selected_host) if remaining else ""
    sync_active_board_host(config)
    return was_active


def set_active_board(config: dict[str, Any], name: str) -> bool:
    board = profile_by_reference(board_profiles(config), name)
    if board is None:
        raise ValueError(f"Unknown board: {name}")
    board_id = ensure_profile_id(board)
    current = profile_by_reference(board_profiles(config), str(config.get("active_board") or ""))
    current_id = ensure_profile_id(current) if current is not None else ""
    if current_id == board_id:
        config["active_board"] = board_id
        return False
    host = board_host_for_board(config, board_id)
    if profile_by_reference(config.get("board_hosts", []), ensure_profile_id(host)) is None:
        raise ValueError(f"Unknown board: {name}")
    config["active_board_host"] = ensure_profile_id(host)
    config["active_board"] = board_id
    sync_active_board_host(config)
    return True


def update_board_field(config: dict[str, Any], board: dict[str, Any], key: str, value: str) -> None:
    current = active_board(config)
    if str(current.get("name") or ""):
        config["active_board"] = ensure_profile_id(current)
    old_name = str(board.get("name") or "")
    if key == "name":
        if not value:
            raise ValueError("Board name is required")
        owner = board_host_for_board(config, ensure_profile_id(board))
        siblings = [item for item in owner.get("boards", []) if isinstance(item, dict) and item is not board]
        if value != old_name and any(str(item.get("name", "")) == value for item in siblings):
            raise ValueError(f"Board already exists on this host: {value}")
    board[key] = value
    if key == "name":
        board["label"] = profile_label_after_rename(str(board.get("label", "")), old_name, value)
    sync_active_board_host(config)


def delete_board_host_profile(config: dict[str, Any], name: str) -> bool:
    host = profile_by_reference(config.get("board_hosts", []), name)
    host_id = ensure_profile_id(host) if host is not None else name
    current = profile_by_reference(config.get("board_hosts", []), str(config.get("active_board_host", "")))
    was_active = current is host
    config["board_hosts"] = [
        profile
        for profile in config.get("board_hosts", [])
        if not (isinstance(profile, dict) and ensure_profile_id(profile) == host_id)
    ]
    if was_active:
        config["active_board_host"] = first_profile_id(config.get("board_hosts", []))
    remaining_boards = board_profiles(config)
    if profile_by_reference(remaining_boards, str(config.get("active_board", ""))) is None:
        config["active_board"] = ensure_profile_id(remaining_boards[0]) if remaining_boards else ""
        if remaining_boards:
            selected_host = board_host_for_board(config, str(config["active_board"]))
            config["active_board_host"] = ensure_profile_id(selected_host)
    sync_active_board_host(config)
    return was_active


def apply_delete_board_host_profile_for_config(config: dict[str, Any], host: dict[str, Any]) -> dict[str, Any]:
    name = str(host.get("name", ""))
    active_changed = delete_board_host_profile(config, ensure_profile_id(host))
    return {
        "status": f"Board host profile deleted: {name}",
        "connection_reset": active_changed,
    }


def set_active_board_host_profile(config: dict[str, Any], name: str) -> bool:
    host = profile_by_reference(config.get("board_hosts", []), name)
    if host is None:
        raise ValueError(f"Unknown board host: {name}")
    host_id = ensure_profile_id(host)
    current = profile_by_reference(config.get("board_hosts", []), str(config.get("active_board_host", "")))
    current_id = ensure_profile_id(current) if current is not None else ""
    if current_id == host_id:
        config["active_board_host"] = host_id
        return False
    config["active_board_host"] = host_id
    boards = [item for item in (host or {}).get("boards", []) if isinstance(item, dict)]
    if profile_by_reference(boards, str(config.get("active_board", ""))) is None:
        config["active_board"] = ensure_profile_id(boards[0]) if boards else ""
    sync_active_board_host(config)
    return True


def apply_active_board_host_profile_for_config(config: dict[str, Any], host: dict[str, Any]) -> dict[str, Any]:
    name = str(host.get("name", ""))
    if not set_active_board_host_profile(config, ensure_profile_id(host)):
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
    active_board_access_host(config)
    old_name = str(profile.get("name", ""))
    if key == "name":
        if not value:
            raise ValueError("Board host profile name is required")
        if value != old_name and profile_name_exists(config.get("board_hosts", []), value):
            raise ValueError(f"Board host profile already exists: {value}")
    profile[key] = value
    if key == "name":
        profile["label"] = profile_label_after_rename(str(profile.get("label", "")), old_name, value)
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
        ensure_profile_id(remote)
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
    selected = profile_by_reference(remotes, str(config.get("active_remote") or "")) or remotes[0]
    config["active_remote"] = ensure_profile_id(selected)
    sync_active_remote(config)


def active_remote(config: dict[str, Any]) -> dict[str, Any]:
    normalize_remote_profiles(config) if "remotes" not in config else None
    active = str(config.get("active_remote", ""))
    remote = profile_by_reference(
        [item for item in config.get("remotes", []) if isinstance(item, dict)],
        active,
    )
    if remote is not None:
        config["active_remote"] = ensure_profile_id(remote)
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
    if hosts and not any(isinstance(host.get("boards"), list) for host in hosts):
        legacy_active = str(config.get("active_board_host") or "")
        grouped: list[dict[str, Any]] = []
        group_keys: dict[tuple[str, ...], dict[str, Any]] = {}
        host_fields = ("user", "host", "work_dir", "direct_copy", "tftp_root", "nfs_root", "deploy_subdir", "server_ip")
        board_fields = ("name", "label", "type", "console_device", "ufs_loadaddr", "ufs_buffersize", "camera_stream_url", "board_ip", "mac_address", "commands")
        used_names: set[str] = set()
        active_host = ""
        for legacy in hosts:
            key = tuple(str(legacy.get(field, "")) for field in host_fields)
            host = group_keys.get(key)
            if host is None:
                base_name = str(legacy.get("user") or legacy.get("name") or "board-host")
                host_name = base_name
                suffix = 2
                while host_name in used_names:
                    host_name = f"{base_name}-{suffix}"
                    suffix += 1
                used_names.add(host_name)
                host = empty_board_access_host(host_name)
                host["label"] = str(legacy.get("user") or legacy.get("label") or host_name)
                for field in host_fields:
                    host[field] = legacy.get(field, host[field])
                grouped.append(host)
                group_keys[key] = host
            board = empty_board(str(legacy.get("name") or ""))
            board["board_host_id"] = ensure_profile_id(host)
            for field in board_fields:
                board[field] = copy.deepcopy(legacy.get(field, board[field]))
            host["boards"].append(board)
            if board["name"] == legacy_active:
                active_host = ensure_profile_id(host)
        hosts = grouped
        config["active_board"] = legacy_active
        config["active_board_host"] = active_host
    config["board_hosts"] = hosts
    for index, host in enumerate(hosts):
        host_id = ensure_profile_id(host)
        host.setdefault("name", str(host.get("label") or f"board-host-{index + 1}"))
        host.setdefault("label", str(host.get("name") or f"board-host-{index + 1}"))
        host.setdefault("user", "")
        host.setdefault("host", "")
        host.setdefault("work_dir", "~/moulin-board-work")
        host.setdefault("direct_copy", "no")
        host.setdefault("tftp_root", "/srv/tftp")
        host.setdefault("nfs_root", "/srv/nfs")
        host.setdefault("deploy_subdir", "")
        host.setdefault("server_ip", "")
        boards = host.setdefault("boards", [])
        if not isinstance(boards, list):
            boards = []
            host["boards"] = boards
        for board_index, board in enumerate(boards):
            if not isinstance(board, dict):
                continue
            board.setdefault("name", str(board.get("label") or f"board-{board_index + 1}"))
            ensure_profile_id(board)
            board["board_host_id"] = host_id
            board.setdefault("label", str(board.get("name") or f"board-{board_index + 1}"))
            board.setdefault("type", "gen5_x5h")
            board.setdefault("console_device", "")
            board.setdefault("ufs_loadaddr", "")
            board.setdefault("ufs_buffersize", "")
            board.setdefault("camera_stream_url", "")
            board.setdefault("board_ip", "")
            board.setdefault("mac_address", "")
            if not isinstance(board.get("commands"), dict):
                board["commands"] = {}
    if not hosts:
        config["active_board_host"] = ""
        sync_active_board_host(config)
        return
    selected_host = profile_by_reference(hosts, str(config.get("active_board_host") or "")) or hosts[0]
    config["active_board_host"] = ensure_profile_id(selected_host)
    boards = [board for host in hosts for board in host.get("boards", []) if isinstance(board, dict)]
    selected_board = profile_by_reference(boards, str(config.get("active_board") or ""))
    if selected_board is None and boards:
        selected_board = boards[0]
    config["active_board"] = ensure_profile_id(selected_board) if selected_board is not None else ""
    if selected_board is not None:
        config["active_board_host"] = str(selected_board.get("board_host_id") or "")
    sync_active_board_host(config)


def active_board_access_host(config: dict[str, Any]) -> dict[str, Any]:
    normalize_board_host_profiles(config) if "board_hosts" not in config else None
    active = str(config.get("active_board_host", ""))
    host = profile_by_reference(
        [item for item in config.get("board_hosts", []) if isinstance(item, dict)],
        active,
    )
    if host is not None:
        config["active_board_host"] = ensure_profile_id(host)
        return host
    return empty_board_access_host("")


def active_board_host(config: dict[str, Any]) -> dict[str, Any]:
    return board_target(config)


def board_profiles(config: dict[str, Any]) -> list[dict[str, Any]]:
    normalize_board_host_profiles(config) if "board_hosts" not in config else None
    return [
        board
        for host in config.get("board_hosts", [])
        if isinstance(host, dict)
        for board in host.get("boards", [])
        if isinstance(board, dict)
    ]


def active_board(config: dict[str, Any]) -> dict[str, Any]:
    active = str(config.get("active_board", ""))
    board = profile_by_reference(board_profiles(config), active)
    if board is not None:
        config["active_board"] = ensure_profile_id(board)
        return board
    return empty_board("")


def board_host_for_board(config: dict[str, Any], board_name: str) -> dict[str, Any]:
    board = profile_by_reference(board_profiles(config), board_name)
    if board is None:
        return empty_board_access_host("")
    owner_id = str(board.get("board_host_id") or "")
    owner = profile_by_reference(
        [item for item in config.get("board_hosts", []) if isinstance(item, dict)],
        owner_id,
    )
    if owner is not None:
        return owner
    for host in config.get("board_hosts", []):
        if not isinstance(host, dict):
            continue
        if board in host.get("boards", []):
            return host
    return empty_board_access_host("")


def board_target(config: dict[str, Any], board_name: str = "") -> dict[str, Any]:
    board = active_board(config) if not board_name else (
        profile_by_reference(board_profiles(config), board_name) or empty_board("")
    )
    host = board_host_for_board(config, str(board.get("id", "")))
    if not str(board.get("name") or ""):
        active_host_id = str(config.get("active_board_host") or "")
        host = profile_by_reference(
            [item for item in config.get("board_hosts", []) if isinstance(item, dict)],
            active_host_id,
        ) or empty_board_access_host("")
        target = copy.deepcopy(host)
        target.pop("boards", None)
        return target
    target = copy.deepcopy(host)
    target.pop("boards", None)
    target.update(copy.deepcopy(board))
    return target


def sync_active_board_host(config: dict[str, Any]) -> None:
    config["board_host"] = board_target(config)


def empty_project_profile(name: str = "") -> dict[str, Any]:
    return {
        "id": new_profile_id(),
        "name": name,
        "label": name,
        "product_type": "gen5_xen_android",
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
    for existing in projects:
        ensure_profile_id(existing)
    if profile_name_exists(projects, name):
        raise ValueError(f"Project already exists: {name}")
    project = dict(active_project(config))
    project["id"] = new_profile_id()
    project["name"] = name
    project["label"] = name
    project["parameters"] = dict(parameters)
    project["targets"] = targets
    project["board_artifacts"] = board_artifacts
    project["docker_image"] = docker_image
    projects.append(project)
    config["projects"] = projects
    config["active_project"] = ensure_profile_id(project)
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
    project = profile_by_reference(projects, name)
    project_id = ensure_profile_id(project) if project is not None else name
    current = profile_by_reference(projects, str(config.get("active_project", "")))
    was_active = current is project
    remaining = [item for item in projects if ensure_profile_id(item) != project_id]
    config["projects"] = remaining
    if was_active:
        config["active_project"] = first_profile_id(remaining)
    sync_active_project(config)
    return was_active


def apply_delete_project_profile_for_config(config: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    name = str(project.get("name", ""))
    active_changed = delete_project_profile(config, ensure_profile_id(project))
    return {
        "status": f"Project deleted: {name}",
        "runtime_reload": active_changed,
        "preflight_reset": active_changed,
    }


def set_active_project_profile(config: dict[str, Any], name: str) -> bool:
    project = profile_by_reference(
        [item for item in config.get("projects", []) if isinstance(item, dict)],
        name,
    )
    if project is None:
        raise ValueError(f"Unknown project: {name}")
    project_id = ensure_profile_id(project)
    current = profile_by_reference(config.get("projects", []), str(config.get("active_project", "")))
    current_id = ensure_profile_id(current) if current is not None else ""
    if current_id == project_id:
        config["active_project"] = project_id
        return False
    config["active_project"] = project_id
    sync_active_project(config)
    return True


def apply_active_project_profile_for_config(config: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    name = str(project.get("name", ""))
    if not set_active_project_profile(config, ensure_profile_id(project)):
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
    set_active_project_profile(config, ensure_profile_id(project))
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
    active_project(config)
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
            "product_type": "gen5_xen_android",
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
        ensure_profile_id(project)
        project.setdefault("name", str(project.get("label") or f"project-{index + 1}"))
        project.setdefault("label", str(project.get("name") or f"project-{index + 1}"))
        project.setdefault("product_type", "gen5_xen_android")
        if project["product_type"] == "gen5_xen":
            project["product_type"] = "gen5_xen_android"
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
    selected = profile_by_reference(projects, str(config.get("active_project") or "")) or projects[0]
    config["active_project"] = ensure_profile_id(selected)
    sync_active_project(config)


def active_project(config: dict[str, Any]) -> dict[str, Any]:
    normalize_project_profiles(config) if "projects" not in config else None
    active = str(config.get("active_project", ""))
    project = profile_by_reference(
        [item for item in config.get("projects", []) if isinstance(item, dict)],
        active,
    )
    if project is not None:
        config["active_project"] = ensure_profile_id(project)
        return project
    return empty_project_profile("")


def sync_active_project(config: dict[str, Any]) -> None:
    project = active_project(config)
    config["project"] = project
    config.setdefault("local", {})["project_dir"] = str(project.get("local_project_dir", ""))
    config.setdefault("moulin", {})["manifest"] = str(project.get("moulin_manifest", ""))
    config.setdefault("docker", {})["dockerfile"] = str(project.get("dockerfile", ""))
    config.setdefault("docker", {})["image"] = str(project.get("docker_image", ""))
