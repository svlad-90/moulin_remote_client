"""Persistent data model for the CTS and VTS plugin."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any
from uuid import uuid4


DEFAULT_RUNNER_WORKSPACE = "moulin-test-runs"
VALID_SUITES = {"cts", "vts"}
RESERVED_TRADEFED_OPTIONS = {"-s", "--serial", "--shard-count", "--retry", "--retry-type"}
SCHEMA_VERSION = 6
REGISTRIES = ("runners", "board_profiles", "test_profiles", "product_profiles", "runs")


def record_id(record: dict[str, Any]) -> str:
    value = str(record.get("id") or "")
    if not value:
        raise ValueError("configuration record has no id; run configuration migration first")
    return value


def _ensure_record_id(record: dict[str, Any]) -> str:
    value = str(record.get("id") or "")
    if not value:
        value = str(uuid4())
        record["id"] = value
    return value


def _find_in(values: list[Any], reference: str) -> dict[str, Any] | None:
    records = [item for item in values if isinstance(item, dict)]
    for item in records:
        if str(item.get("id") or "") == reference:
            return item
    for item in records:
        if str(item.get("name") or "") == reference:
            return item
    return None


def _migrate_reference(
    config: dict[str, Any],
    key: str,
    reference: Any,
    *,
    preserve_missing: bool = False,
) -> str:
    value = str(reference or "")
    record = _find_in(config.get(key, []), value)
    if record is not None:
        return _ensure_record_id(record)
    return value if preserve_missing else ""


def migrate_state(config: dict[str, Any]) -> bool:
    before = deepcopy(config)
    version = int(config.get("schema_version") or 0)
    if version > SCHEMA_VERSION:
        raise ValueError(
            f"unsupported CTS/VTS configuration schema {version}; maximum is {SCHEMA_VERSION}"
        )
    config["schema_version"] = SCHEMA_VERSION
    config.pop("runner", None)
    for key in REGISTRIES:
        if not isinstance(config.get(key), list):
            config[key] = []
        for record in config[key]:
            if isinstance(record, dict):
                _ensure_record_id(record)
    config.setdefault("active_runner", "")
    config.setdefault("active_run", "")
    config["active_runner"] = _migrate_reference(config, "runners", config["active_runner"])
    config["active_run"] = _migrate_reference(config, "runs", config["active_run"])
    run_references = {
        "runner_profile": "runners",
        "board_profile": "board_profiles",
        "test_profile": "test_profiles",
        "product_profile": "product_profiles",
    }
    for run in config["runs"]:
        if not isinstance(run, dict):
            continue
        for field, registry in run_references.items():
            run[field] = _migrate_reference(
                config,
                registry,
                run.get(field),
                preserve_missing=True,
            )
    for profile in config["product_profiles"]:
        if not isinstance(profile, dict):
            continue
        for key in ("build_targets", "android_dir", "lunch_target", "kernel_image", "kernel_modules"):
            profile.pop(key, None)
    for profile in config["board_profiles"]:
        if not isinstance(profile, dict) or not isinstance(profile.get("devices"), list):
            continue
        for device in profile["devices"]:
            if isinstance(device, dict):
                device.pop("serial_resolver_command", None)
    return before != config


def state(config: dict[str, Any]) -> dict[str, Any]:
    return config


def records(config: dict[str, Any], key: str) -> list[dict[str, Any]]:
    values = config.get(key, [])
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, dict)]


def find(config: dict[str, Any], key: str, name: str) -> dict[str, Any] | None:
    return _find_in(records(config, key), name)


def upsert(config: dict[str, Any], key: str, value: dict[str, Any]) -> None:
    name = str(value.get("name") or "").strip()
    if not name:
        raise ValueError("profile name is required")
    value_id = _ensure_record_id(value)
    values = config.setdefault(key, [])
    if not isinstance(values, list):
        raise ValueError(f"configuration registry is not a list: {key}")
    for index, current in enumerate(values):
        if isinstance(current, dict) and record_id(current) == value_id:
            values[index] = value
            return
    values.append(value)


def delete(config: dict[str, Any], key: str, name: str) -> bool:
    values = config.get(key, [])
    if not isinstance(values, list):
        return False
    selected = _find_in(values, name)
    selected_id = record_id(selected) if selected is not None else name
    for index, current in enumerate(values):
        if isinstance(current, dict) and record_id(current) == selected_id:
            del values[index]
            if key == "runners" and config.get("active_runner") == selected_id:
                config["active_runner"] = record_id(values[0]) if values else ""
            if key == "runs" and config.get("active_run") == selected_id:
                config["active_run"] = ""
            return True
    return False


def dependent_runs(config: dict[str, Any], key: str, name: str) -> list[str]:
    field = {
        "runners": "runner_profile",
        "board_profiles": "board_profile",
        "test_profiles": "test_profile",
        "product_profiles": "product_profile",
    }.get(key)
    if field is None:
        return []
    selected = find(config, key, name)
    selected_id = record_id(selected) if selected is not None else name
    return [str(run.get("name")) for run in records(config, "runs") if run.get(field) == selected_id]


def csv_values(value: str) -> list[str]:
    return list(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))


def parse_suites(value: str) -> list[str]:
    suites = list(dict.fromkeys(item.lower() for item in csv_values(value)))
    invalid = [item for item in suites if item not in VALID_SUITES]
    if invalid or not suites:
        raise ValueError("suites must contain cts, vts, or both")
    return suites


def validate_tradefed_args(values: list[str]) -> list[str]:
    for value in values:
        option = value.split("=", 1)[0]
        if option in RESERVED_TRADEFED_OPTIONS:
            raise ValueError(f"Tradefed option is managed by the plugin: {option}")
        if "\n" in value or "\r" in value:
            raise ValueError("Tradefed arguments must not contain newlines")
    return values


def positive_int(value: str, label: str, default: int) -> int:
    text = value.strip()
    result = default if not text else int(text, 10)
    if result < 1:
        raise ValueError(f"{label} must be greater than zero")
    return result


def nonnegative_int(value: str, label: str, default: int) -> int:
    text = value.strip()
    result = default if not text else int(text, 10)
    if result < 0:
        raise ValueError(f"{label} must not be negative")
    return result


def safe_name(value: str) -> str:
    name = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        raise ValueError("name may contain letters, digits, dot, underscore, and dash")
    return name


def active_runner(config: dict[str, Any]) -> dict[str, Any] | None:
    return find(config, "runners", str(state(config).get("active_runner") or ""))


def runner_remote(runner: dict[str, Any] | None) -> str:
    if runner is None:
        return ""
    user = str(runner.get("user") or "")
    host = str(runner.get("host") or "")
    return f"{user}@{host}" if user and host else host


def active_run(config: dict[str, Any]) -> dict[str, Any] | None:
    return find(config, "runs", str(state(config).get("active_run") or ""))


def prune_board_references(config: dict[str, Any], available: set[str]) -> list[str]:
    removed: list[str] = []
    for profile in records(config, "board_profiles"):
        devices = profile.get("devices", [])
        kept = []
        for device in devices if isinstance(devices, list) else []:
            board_id = str(device.get("board_id") or "") if isinstance(device, dict) else ""
            if board_id in available:
                kept.append(device)
            elif board_id:
                removed.append(f"{profile.get('name')}:{board_id}")
        profile["devices"] = kept
    return removed


def resolve_run(
    config: dict[str, Any],
    run: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    runner = find(config, "runners", str(run.get("runner_profile") or ""))
    board = find(config, "board_profiles", str(run.get("board_profile") or ""))
    test = find(config, "test_profiles", str(run.get("test_profile") or ""))
    product = find(config, "product_profiles", str(run.get("product_profile") or ""))
    missing = [
        label
        for label, value in (("runner", runner), ("board", board), ("test", test), ("product", product))
        if value is None
    ]
    if missing:
        raise ValueError("run references missing profiles: " + ", ".join(missing))
    return runner, board, test, product
