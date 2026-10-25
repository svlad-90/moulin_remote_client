"""CTS/VTS contribution to the shared configuration store."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable
from urllib.parse import urlparse

from components.config.api.store import (
    ConfigRegistrar,
    DeletePolicy,
    EntityAdapter,
    EntityRef,
    ReferenceAdapter,
    ReferenceLink,
)
from components.plugins.api.model import plugin_config

from . import model


PLUGIN_ID = "cts-vts"
SELECTION = EntityRef("cts_vts.selection", "active")

_ENTITY_FIELDS = {
    "runners": {"name", "label", "user", "host", "workspace_dir"},
    "board_profiles": {"name", "devices"},
    "test_profiles": {
        "name", "suites", "cts_revision", "cts_url", "extra_args", "skipped_modules",
        "adb_loss_timeout_minutes", "no_progress_runs", "max_reboots", "max_reflashes",
        "max_skip_cycles",
    },
    "product_profiles": {"name", "build_host", "project"},
    "runs": {
        "name", "runner_profile", "board_profile", "test_profile", "product_profile",
        "last_status",
    },
}


def _single_line(field: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    clean = value.strip()
    if any(character in clean for character in ("\x00", "\n", "\r")):
        raise ValueError(f"{field} must be a single-line value")
    return clean


def _validate_device(device: Any) -> dict[str, str]:
    if not isinstance(device, dict):
        raise ValueError("board profile devices must be mappings")
    unknown = set(device).difference({"board_id", "serial", "resolver_command"})
    if unknown:
        raise ValueError(f"unsupported board device field(s): {', '.join(sorted(unknown))}")
    board_id = _single_line("board_id", device.get("board_id"))
    if not board_id:
        raise ValueError("board_id is required")
    serial = _single_line("serial", device.get("serial", ""))
    if serial and any(character.isspace() for character in serial):
        raise ValueError("ADB serial must not contain whitespace")
    result = {"board_id": board_id, "serial": serial}
    if "resolver_command" in device:
        result["resolver_command"] = _single_line("resolver_command", device["resolver_command"])
    return result


def _validate_entity_fields(
    key: str,
    values: dict[str, Any],
    *,
    allow_device_update: bool = False,
) -> dict[str, Any]:
    allowed = _ENTITY_FIELDS[key] | ({"device_update"} if allow_device_update else set())
    unknown = set(values).difference(allowed)
    if unknown:
        raise ValueError(f"unsupported CTS/VTS {key} field(s): {', '.join(sorted(unknown))}")
    validated: dict[str, Any] = {}
    for field, value in values.items():
        if field == "name":
            validated[field] = model.safe_name(_single_line(field, value))
        elif field == "workspace_dir":
            workspace = _single_line(field, value)
            if not workspace or workspace.startswith("~"):
                raise ValueError("runner workspace must not be empty or start with '~'")
            validated[field] = workspace
        elif field in {
            "label", "user", "host", "cts_revision", "cts_url", "build_host", "project",
            "runner_profile", "board_profile", "test_profile", "product_profile", "last_status",
        }:
            clean = _single_line(field, value)
            if field in {"user", "host"} and clean and any(character.isspace() for character in clean):
                raise ValueError(f"{field} must not contain whitespace")
            if field == "cts_revision" and clean and not re.fullmatch(r"\d+(?:\.\d+)?_r\d+", clean):
                raise ValueError("CTS revision must look like 17_r2 or 16.1_r4")
            if field == "cts_url" and clean and urlparse(clean).scheme not in {"http", "https"}:
                raise ValueError("CTS URL must use http or https")
            validated[field] = clean
        elif field == "suites":
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError("suites must be a list of suite names")
            validated[field] = model.parse_suites(",".join(value))
        elif field == "extra_args":
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError("extra_args must be a list of strings")
            validated[field] = model.validate_tradefed_args(list(value))
        elif field == "skipped_modules":
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError("skipped_modules must be a list of module names")
            validated[field] = list(dict.fromkeys(_single_line(field, item) for item in value if item.strip()))
        elif field in {"adb_loss_timeout_minutes", "no_progress_runs"}:
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field} must be a positive integer")
            validated[field] = value
        elif field in {"max_reboots", "max_reflashes", "max_skip_cycles"}:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field} must be a non-negative integer")
            validated[field] = value
        elif field == "devices":
            if not isinstance(value, list):
                raise ValueError("devices must be a list")
            devices = [_validate_device(device) for device in value]
            board_ids = [device["board_id"] for device in devices]
            if len(board_ids) != len(set(board_ids)):
                raise ValueError("board profile devices must be unique")
            validated[field] = devices
        elif field == "device_update":
            if not isinstance(value, dict):
                raise ValueError("board profile device update must be a mapping")
            unknown_update = set(value).difference({"board_id", "field", "value"})
            if unknown_update:
                raise ValueError(
                    f"unsupported board device update field(s): {', '.join(sorted(unknown_update))}"
                )
            update_field = _single_line("field", value.get("field"))
            if update_field not in {"serial", "resolver_command"}:
                raise ValueError(f"unsupported board device field: {update_field}")
            update_value = _single_line(update_field, value.get("value", ""))
            if update_field == "serial" and update_value and any(
                character.isspace() for character in update_value
            ):
                raise ValueError("ADB serial must not contain whitespace")
            validated[field] = {
                "board_id": _single_line("board_id", value.get("board_id")),
                "field": update_field,
                "value": update_value,
            }
    return validated


def _config(root: dict[str, Any]) -> dict[str, Any]:
    return plugin_config(root, PLUGIN_ID)


def _records(key: str):
    return lambda root: model.records(_config(root), key)


def _delete(key: str):
    def apply(root: dict[str, Any], entity_id: str) -> None:
        if not model.delete(_config(root), key, entity_id):
            raise ValueError(f"unknown CTS/VTS {key} entity: {entity_id}")

    return apply


def _create(key: str, *, active_field: str = ""):
    def apply(root: dict[str, Any], entity_id: str, values: dict[str, Any]) -> None:
        config = _config(root)
        values = _validate_entity_fields(key, values)
        name = str(values.get("name") or "")
        if model.find(config, key, name) is not None:
            raise ValueError(f"CTS/VTS {key} entity already exists: {name}")
        record = {**values, "id": entity_id, "name": name}
        if key == "runs":
            model.resolve_run(config, record)
        model.upsert(config, key, record)
        if active_field:
            model.state(config)[active_field] = entity_id

    return apply


def _update(key: str):
    def apply(root: dict[str, Any], entity_id: str, changes: dict[str, Any]) -> None:
        config = _config(root)
        changes = _validate_entity_fields(key, changes, allow_device_update=key == "board_profiles")
        record = model.find(config, key, entity_id)
        if record is None:
            raise ValueError(f"unknown CTS/VTS {key} entity: {entity_id}")
        if "name" in changes:
            name = str(changes["name"])
            duplicate = model.find(config, key, name)
            if duplicate is not None and model.record_id(duplicate) != entity_id:
                raise ValueError(f"CTS/VTS {key} entity already exists: {name}")
            changes["name"] = name
        if key == "board_profiles" and "device_update" in changes:
            device_update = changes.pop("device_update")
            if not isinstance(device_update, dict):
                raise ValueError("board profile device update must be a mapping")
            board_id = str(device_update.get("board_id") or "")
            device = next(
                (
                    item
                    for item in record.get("devices", [])
                    if isinstance(item, dict) and str(item.get("board_id") or "") == board_id
                ),
                None,
            )
            if device is None:
                raise ValueError(f"board is not selected in the profile: {board_id}")
            field = str(device_update.get("field") or "")
            if field not in {"serial", "resolver_command"}:
                raise ValueError(f"unsupported board device field: {field}")
            device[field] = str(device_update.get("value") or "")
        protected = {
            "runners": set(),
            "board_profiles": {"devices"},
            "test_profiles": set(),
            "product_profiles": {"build_host", "project"},
            "runs": {"runner_profile", "board_profile", "test_profile", "product_profile"},
        }[key]
        invalid = protected.intersection(changes)
        if invalid:
            fields = ", ".join(sorted(invalid))
            raise ValueError(f"CTS/VTS references must be changed through the reference API: {fields}")
        record.update(changes)

    return apply


def _selection_records(_root: dict[str, Any]) -> Iterable[dict[str, Any]]:
    return ({"id": SELECTION.entity_id, "name": "CTS/VTS active selections"},)


def _delete_selection(_root: dict[str, Any], _entity_id: str) -> None:
    raise ValueError("CTS/VTS active selections cannot be deleted")


def _active_links(field: str, target_kind: str, label: str):
    def links(root: dict[str, Any]) -> Iterable[ReferenceLink]:
        target_id = str(model.state(_config(root)).get(field) or "")
        if target_id:
            yield ReferenceLink(
                SELECTION,
                EntityRef(target_kind, target_id),
                f"active CTS/VTS {label} selection will be cleared",
            )

    return links


def _replace_active(field: str):
    def replace(root: dict[str, Any], _source: EntityRef, targets: tuple[EntityRef, ...]) -> None:
        if len(targets) > 1:
            raise ValueError("an active selection accepts at most one target")
        model.state(_config(root))[field] = targets[0].entity_id if targets else ""

    return replace


def _detach_active(field: str):
    def detach(_root: dict[str, Any], _link: ReferenceLink) -> None:
        # model.delete() owns fallback selection for the deleted entity type.
        return None

    return detach


def _run_links(root: dict[str, Any], field: str, target_kind: str, label: str) -> Iterable[ReferenceLink]:
    for run in model.records(_config(root), "runs"):
        target_id = str(run.get(field) or "")
        if target_id:
            yield ReferenceLink(
                EntityRef("cts_vts.run", model.record_id(run)),
                EntityRef(target_kind, target_id),
                f"CTS/VTS test run {run.get('name')}: {label} is required; delete the test run first",
            )


def _board_links(root: dict[str, Any]) -> Iterable[ReferenceLink]:
    for profile in model.records(_config(root), "board_profiles"):
        for device in profile.get("devices", []):
            board_id = str(device.get("board_id") or "") if isinstance(device, dict) else ""
            if board_id:
                yield ReferenceLink(
                    EntityRef("cts_vts.board_profile", model.record_id(profile)),
                    EntityRef("board", board_id),
                    f"CTS/VTS board profile {profile.get('name')}: board will be removed from the selection",
                )


def _detach_board(root: dict[str, Any], link: ReferenceLink) -> None:
    profile = model.find(_config(root), "board_profiles", link.source.entity_id)
    if profile is None:
        return
    profile["devices"] = [
        device
        for device in profile.get("devices", [])
        if not isinstance(device, dict) or str(device.get("board_id") or "") != link.target.entity_id
    ]


def _product_links(
    root: dict[str, Any],
    field: str,
    target_kind: str,
    label: str,
) -> Iterable[ReferenceLink]:
    for profile in model.records(_config(root), "product_profiles"):
        target_id = str(profile.get(field) or "")
        if target_id:
            yield ReferenceLink(
                EntityRef("cts_vts.product_profile", model.record_id(profile)),
                EntityRef(target_kind, target_id),
                f"CTS/VTS product profile {profile.get('name')}: {label} selection will be cleared",
            )


def _detach_product_field(field: str):
    def apply(root: dict[str, Any], link: ReferenceLink) -> None:
        profile = model.find(_config(root), "product_profiles", link.source.entity_id)
        if profile is not None and str(profile.get(field) or "") == link.target.entity_id:
            profile[field] = ""

    return apply


def _replace_field(key: str, field: str):
    def replace(root: dict[str, Any], source: EntityRef, targets: tuple[EntityRef, ...]) -> None:
        if len(targets) > 1:
            raise ValueError(f"{field} accepts at most one target")
        record = model.find(_config(root), key, source.entity_id)
        if record is None:
            raise ValueError(f"unknown CTS/VTS {key} entity: {source.entity_id}")
        record[field] = targets[0].entity_id if targets else ""

    return replace


def _replace_boards(root: dict[str, Any], source: EntityRef, targets: tuple[EntityRef, ...]) -> None:
    profile = model.find(_config(root), "board_profiles", source.entity_id)
    if profile is None:
        raise ValueError(f"unknown CTS/VTS board profile: {source.entity_id}")
    existing = {
        str(device.get("board_id") or ""): device
        for device in profile.get("devices", [])
        if isinstance(device, dict)
    }
    profile["devices"] = [
        existing.get(target.entity_id, {"board_id": target.entity_id, "serial": ""})
        for target in targets
    ]


@dataclass(frozen=True)
class CtsVtsConfigContributor:
    def contribute_config(self, registrar: ConfigRegistrar) -> None:
        for key, kind, active_field in (
            ("runners", "cts_vts.runner", "active_runner"),
            ("board_profiles", "cts_vts.board_profile", ""),
            ("test_profiles", "cts_vts.test_profile", ""),
            ("product_profiles", "cts_vts.product_profile", ""),
            ("runs", "cts_vts.run", "active_run"),
        ):
            registrar.register_entity(
                EntityAdapter(
                    kind,
                    _records(key),
                    _delete(key),
                    create=_create(key, active_field=active_field),
                    update=_update(key),
                )
            )
        registrar.register_entity(EntityAdapter(SELECTION.kind, _selection_records, _delete_selection))

        for field, target_kind, label in (
            ("runner_profile", "cts_vts.runner", "runner profile"),
            ("board_profile", "cts_vts.board_profile", "board profile"),
            ("test_profile", "cts_vts.test_profile", "test profile"),
            ("product_profile", "cts_vts.product_profile", "product profile"),
        ):
            registrar.register_reference(
                ReferenceAdapter(
                    name=f"cts_vts.run.{field}",
                    source_kind="cts_vts.run",
                    target_kind=target_kind,
                    policy=DeletePolicy.RESTRICT,
                    links=lambda root, field=field, target_kind=target_kind, label=label: _run_links(
                        root, field, target_kind, label
                    ),
                    replace=_replace_field("runs", field),
                )
            )

        registrar.register_reference(
            ReferenceAdapter(
                name="cts_vts.board_profile.devices",
                source_kind="cts_vts.board_profile",
                target_kind="board",
                policy=DeletePolicy.DETACH,
                links=_board_links,
                detach=_detach_board,
                replace=_replace_boards,
            )
        )
        for field, target_kind, label in (
            ("build_host", "build_host", "build host"),
            ("project", "project", "project"),
        ):
            registrar.register_reference(
                ReferenceAdapter(
                    name=f"cts_vts.product_profile.{field}",
                    source_kind="cts_vts.product_profile",
                    target_kind=target_kind,
                    policy=DeletePolicy.DETACH,
                    links=lambda root, field=field, target_kind=target_kind, label=label: _product_links(
                        root, field, target_kind, label
                    ),
                    detach=_detach_product_field(field),
                    replace=_replace_field("product_profiles", field),
                )
            )
        for field, target_kind, label in (
            ("active_runner", "cts_vts.runner", "runner"),
            ("active_run", "cts_vts.run", "test run"),
        ):
            registrar.register_reference(
                ReferenceAdapter(
                    name=f"cts_vts.{field}",
                    source_kind=SELECTION.kind,
                    target_kind=target_kind,
                    policy=DeletePolicy.DETACH,
                    links=_active_links(field, target_kind, label),
                    detach=_detach_active(field),
                    replace=_replace_active(field),
                )
            )


def config_contributor() -> CtsVtsConfigContributor:
    return CtsVtsConfigContributor()
