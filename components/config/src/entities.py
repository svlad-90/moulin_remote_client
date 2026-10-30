"""Built-in configuration entity contribution."""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
import re
from typing import Any, Iterable
from urllib.parse import urlsplit

from components.config.src import profiles
from components.config.src.store import (
    ConfigRegistrar,
    DeletePolicy,
    EntityAdapter,
    EntityRef,
    ReferenceAdapter,
    ReferenceLink,
)


SELECTION = EntityRef("core.selection", "active")

_CORE_FIELDS = {
    "build_host": {
        "name", "label", "type", "user", "host", "work_dir", "direct_copy",
        "console_device", "ufs_loadaddr", "ufs_buffersize", "tftp_root", "nfs_root",
        "deploy_subdir", "server_ip", "board_ip", "mac_address", "commands",
        "projects_dir", "git_url", "moulin_manifest", "dockerfile", "docker_image",
    },
    "board_host": {
        "name", "label", "user", "host", "work_dir", "direct_copy", "tftp_root",
        "nfs_root", "deploy_subdir", "server_ip",
    },
    "board": {
        "name", "label", "type", "console_device", "ufs_loadaddr", "ufs_buffersize",
        "camera_stream_url", "board_ip", "mac_address", "commands",
    },
    "project": {
        "name", "label", "product_type", "project_dir", "local_project_dir", "git_url",
        "git_ref", "moulin_manifest", "dockerfile", "docker_image", "parameters", "targets",
        "board_artifacts", "mappings", "active_mappings",
    },
}


def _validate_single_line(field: str, value: str) -> str:
    clean = value.strip()
    if any(character in clean for character in ("\x00", "\n", "\r")):
        raise ValueError(f"{field} must be a single-line value")
    return clean


def _validate_type_id(field: str, value: str, available: set[str]) -> None:
    if value not in available:
        raise ValueError(f"unknown {field}: {value}")


def _validate_core_fields(
    kind: str,
    values: dict[str, Any],
    *,
    extra_fields: set[str] | None = None,
) -> dict[str, Any]:
    allowed = _CORE_FIELDS[kind] | (extra_fields or set())
    unknown = set(values).difference(allowed)
    if unknown:
        raise ValueError(f"unsupported {kind} field(s): {', '.join(sorted(unknown))}")
    validated: dict[str, Any] = {}
    for field, value in values.items():
        if field in {"make_active"}:
            if not isinstance(value, bool):
                raise ValueError(f"{field} must be a boolean")
            validated[field] = value
            continue
        if field in {"board_host_id", "_remote_projects_dir"}:
            if not isinstance(value, str):
                raise ValueError(f"{field} must be a string")
            validated[field] = _validate_single_line(field, value)
            continue
        if field in {"commands", "parameters"}:
            if not isinstance(value, dict) or not all(
                isinstance(key, str) and isinstance(item, str)
                for key, item in value.items()
            ):
                raise ValueError(f"{field} must be a string mapping")
            validated[field] = {
                _validate_single_line(field, key): _validate_single_line(field, item)
                for key, item in value.items()
            }
            continue
        if field in {"targets", "board_artifacts"} and isinstance(value, list):
            if not all(isinstance(item, str) for item in value):
                raise ValueError(f"{field} must contain strings")
            validated[field] = " ".join(item.strip() for item in value if item.strip())
            continue
        if field in {"mappings", "active_mappings"}:
            if not isinstance(value, list):
                raise ValueError(f"{field} must be a list")
            validated[field] = value
            continue
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a string")
        clean = _validate_single_line(field, value)
        if field == "name" and not clean:
            raise ValueError(f"{kind} name is required")
        if field == "direct_copy" and clean not in {"yes", "no"}:
            raise ValueError("direct_copy must be yes or no")
        if field in {"server_ip", "board_ip"} and clean:
            try:
                ip_address(clean)
            except ValueError as exc:
                raise ValueError(f"{field} must be a valid IP address") from exc
        if field == "mac_address" and clean and not re.fullmatch(
            r"[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}", clean
        ):
            raise ValueError("mac_address must use six colon-separated octets")
        if field == "camera_stream_url" and clean:
            parsed = urlsplit(clean)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("camera_stream_url must be an HTTP or HTTPS URL")
        if field == "type" and clean:
            from components.board_types.api import registry as board_type_registry_api

            _validate_type_id(
                "board type",
                clean,
                {adapter.type_id for adapter in board_type_registry_api.board_type_registry().adapters()},
            )
        if field == "product_type" and clean:
            from components.product_types.api import registry as product_type_registry_api

            _validate_type_id(
                "product type",
                clean,
                {adapter.type_id for adapter in product_type_registry_api.product_type_registry().adapters()},
            )
        validated[field] = clean
    return validated


def _dict_records(values: Any) -> Iterable[dict[str, Any]]:
    return (value for value in values if isinstance(value, dict))


def _remote_records(config: dict[str, Any]) -> Iterable[dict[str, Any]]:
    return _dict_records(config.get("remotes", []))


def _board_host_records(config: dict[str, Any]) -> Iterable[dict[str, Any]]:
    return _dict_records(config.get("board_hosts", []))


def _board_records(config: dict[str, Any]) -> Iterable[dict[str, Any]]:
    return (
        board
        for host in _dict_records(config.get("board_hosts", []))
        for board in _dict_records(host.get("boards", []))
    )


def _project_records(config: dict[str, Any]) -> Iterable[dict[str, Any]]:
    return _dict_records(config.get("projects", []))


def _selection_records(_config: dict[str, Any]) -> Iterable[dict[str, Any]]:
    return ({"id": SELECTION.entity_id, "name": "active selections"},)


def _delete_selection(_config: dict[str, Any], _entity_id: str) -> None:
    raise ValueError("active selections cannot be deleted")


def _selection_links(field: str, target_kind: str, label: str):
    def links(config: dict[str, Any]) -> Iterable[ReferenceLink]:
        target_id = str(config.get(field) or "")
        if target_id:
            yield ReferenceLink(
                SELECTION,
                EntityRef(target_kind, target_id),
                f"active {label} selection will be updated",
            )

    return links


def _detach_selection(field: str):
    def detach(_config: dict[str, Any], _link: ReferenceLink) -> None:
        # The entity delete adapter selects the next valid active profile.
        return None

    return detach


def _replace_selection(setter):
    def replace(config: dict[str, Any], _source: EntityRef, targets: tuple[EntityRef, ...]) -> None:
        if len(targets) > 1:
            raise ValueError("an active selection accepts at most one target")
        if targets:
            setter(config, targets[0].entity_id)

    return replace


def _delete_remote(config: dict[str, Any], entity_id: str) -> None:
    profiles.delete_remote_profile(config, entity_id)


def _delete_board_host(config: dict[str, Any], entity_id: str) -> None:
    profiles.delete_board_host_profile(config, entity_id)


def _delete_board(config: dict[str, Any], entity_id: str) -> None:
    host = profiles.board_host_for_board(config, entity_id)
    profiles.delete_board(config, host, entity_id)


def _delete_project(config: dict[str, Any], entity_id: str) -> None:
    profiles.delete_project_profile(config, entity_id)


def _adopt_store_id(
    config: dict[str, Any],
    record: dict[str, Any],
    entity_id: str,
    *active_fields: str,
) -> None:
    previous_id = profiles.ensure_profile_id(record)
    record["id"] = entity_id
    for field in active_fields:
        if str(config.get(field) or "") == previous_id:
            config[field] = entity_id


def _create_remote(config: dict[str, Any], entity_id: str, values: dict[str, Any]) -> None:
    values = _validate_core_fields("build_host", values, extra_fields={"make_active"})
    remote = profiles.add_remote_profile(config, str(values.get("name") or "").strip())
    for field in ("label", "user", "host", "projects_dir"):
        if field in values:
            remote[field] = str(values[field]).strip()
    _adopt_store_id(config, remote, entity_id, "active_remote")
    if values.get("make_active"):
        config["active_remote"] = entity_id
    profiles.sync_active_remote(config)


def _create_board_host(config: dict[str, Any], entity_id: str, values: dict[str, Any]) -> None:
    values = _validate_core_fields("board_host", values)
    host = profiles.add_board_host_profile(config, str(values.get("name") or "").strip())
    _adopt_store_id(config, host, entity_id, "active_board_host")
    profiles.sync_active_board_host(config)


def _create_board(config: dict[str, Any], entity_id: str, values: dict[str, Any]) -> None:
    values = _validate_core_fields("board", values, extra_fields={"board_host_id"})
    host_id = str(values.get("board_host_id") or "")
    host = profiles.profile_by_reference(config.get("board_hosts", []), host_id)
    if host is None:
        raise ValueError(f"Unknown board host: {host_id}")
    board = profiles.add_board(config, host, str(values.get("name") or "").strip())
    _adopt_store_id(config, board, entity_id, "active_board")
    profiles.sync_active_board_host(config)


def _create_project(config: dict[str, Any], entity_id: str, values: dict[str, Any]) -> None:
    values = _validate_core_fields("project", values)
    project = profiles.add_project_profile_from_current(
        config,
        str(values.get("name") or "").strip(),
        parameters=dict(values.get("parameters") or {}),
        targets=str(values.get("targets") or ""),
        board_artifacts=str(values.get("board_artifacts") or ""),
        docker_image=str(values.get("docker_image") or ""),
    )
    _adopt_store_id(config, project, entity_id, "active_project")
    profiles.sync_active_project(config)


def _record(config: dict[str, Any], key: str, entity_id: str) -> dict[str, Any]:
    record = profiles.profile_by_reference(config.get(key, []), entity_id)
    if record is None:
        raise ValueError(f"Unknown {key} entity: {entity_id}")
    return record


def _update_remote(config: dict[str, Any], entity_id: str, changes: dict[str, Any]) -> None:
    changes = _validate_core_fields("build_host", changes)
    remote = _record(config, "remotes", entity_id)
    for key, value in changes.items():
        profiles.update_remote_profile_field(config, remote, key, str(value))


def _update_board_host(config: dict[str, Any], entity_id: str, changes: dict[str, Any]) -> None:
    changes = _validate_core_fields("board_host", changes)
    host = _record(config, "board_hosts", entity_id)
    for key, value in changes.items():
        if key == "commands":
            if not isinstance(value, dict):
                raise ValueError("board host commands must be a mapping")
            host[key] = dict(value)
            profiles.sync_active_board_host(config)
        else:
            profiles.update_board_host_profile_field(config, host, key, str(value))


def _update_board(config: dict[str, Any], entity_id: str, changes: dict[str, Any]) -> None:
    if "board_host_id" in changes:
        raise ValueError("board ownership must be changed through the reference API")
    changes = _validate_core_fields("board", changes)
    board = next((item for item in _board_records(config) if str(item.get("id") or "") == entity_id), None)
    if board is None:
        raise ValueError(f"Unknown board entity: {entity_id}")
    for key, value in changes.items():
        if key == "commands":
            if not isinstance(value, dict):
                raise ValueError("board commands must be a mapping")
            board[key] = dict(value)
            profiles.sync_active_board_host(config)
        else:
            profiles.update_board_field(config, board, key, str(value))


def _update_project(config: dict[str, Any], entity_id: str, changes: dict[str, Any]) -> None:
    changes = _validate_core_fields("project", changes, extra_fields={"_remote_projects_dir"})
    project = _record(config, "projects", entity_id)
    projects_dir = str(changes.pop("_remote_projects_dir", ""))
    for key, value in changes.items():
        profiles.update_project_profile_field(config, project, key, value, projects_dir=projects_dir)
        projects_dir = ""


def _owned_boards(config: dict[str, Any], host_id: str) -> Iterable[EntityRef]:
    host = profiles.profile_by_reference(config.get("board_hosts", []), host_id)
    if host is None:
        return ()
    return tuple(
        EntityRef("board", profiles.ensure_profile_id(board))
        for board in host.get("boards", [])
        if isinstance(board, dict)
    )


@dataclass(frozen=True)
class CoreProfileContributor:
    """Expose configuration profiles through the common entity contract."""

    def contribute_config(self, registrar: ConfigRegistrar) -> None:
        registrar.register_entity(
            EntityAdapter(
                "build_host",
                _remote_records,
                _delete_remote,
                create=_create_remote,
                update=_update_remote,
            )
        )
        registrar.register_entity(
            EntityAdapter(
                "board_host",
                _board_host_records,
                _delete_board_host,
                owned=_owned_boards,
                create=_create_board_host,
                update=_update_board_host,
            )
        )
        registrar.register_entity(
            EntityAdapter(
                "board",
                _board_records,
                _delete_board,
                create=_create_board,
                update=_update_board,
            )
        )
        registrar.register_entity(
            EntityAdapter(
                "project",
                _project_records,
                _delete_project,
                create=_create_project,
                update=_update_project,
            )
        )
        registrar.register_entity(EntityAdapter(SELECTION.kind, _selection_records, _delete_selection))
        for name, field, target_kind, label, setter in (
            ("core.active_build_host", "active_remote", "build_host", "build host", profiles.set_active_remote_profile),
            ("core.active_board_host", "active_board_host", "board_host", "board host", profiles.set_active_board_host_profile),
            ("core.active_board", "active_board", "board", "board", profiles.set_active_board),
            ("core.active_project", "active_project", "project", "project", profiles.set_active_project_profile),
        ):
            registrar.register_reference(
                ReferenceAdapter(
                    name=name,
                    source_kind=SELECTION.kind,
                    target_kind=target_kind,
                    policy=DeletePolicy.DETACH,
                    links=_selection_links(field, target_kind, label),
                    detach=_detach_selection(field),
                    replace=_replace_selection(setter),
                )
            )


def core_profile_contributor() -> CoreProfileContributor:
    return CoreProfileContributor()
