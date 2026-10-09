"""Runtime-level config orchestration helpers."""

from __future__ import annotations

import fnmatch
import hashlib
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping

from components.build_runtime.api import env as config_env
from components.build_runtime.api import settings as build_settings
from components.config.api import accessors, files, profiles


GENERATED_MAPPING_SNAPSHOT_EXCLUDES = (
    ".moulin_*.d",
    ".ninja_deps",
    ".ninja_deps.*",
    ".ninja_log",
    ".ninja_log.*",
    "__agent_task_dir=*",
    "defras-build-console.log",
    "exit *PIPESTATUS*",
    "full*.bmap",
    "full*.img",
    "full*.img.gz",
    "android/out/",
    "report/logs/",
    "yocto/build-*/",
)


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


def load_runtime_incremental_components(config: dict[str, Any], app_dir: Path) -> list[str] | None:
    try:
        path = accessors.config_path(config, "build_settings", app_dir, "state")
    except KeyError:
        return None
    settings = build_settings.read_build_settings_file(path)
    components = settings.get("incremental_components")
    if not isinstance(components, list):
        return None
    return [str(component).strip() for component in components if str(component).strip()]


def save_runtime_incremental_components(config: dict[str, Any], app_dir: Path, components: list[str]) -> None:
    path = accessors.config_path(config, "build_settings", app_dir, "state")
    settings = build_settings.read_build_settings_file(path)
    settings["incremental_components"] = [str(component) for component in components if str(component).strip()]
    build_settings.write_build_settings_file(path, settings)


def mapping_snapshot_exclude_patterns(config: dict[str, Any]) -> list[str]:
    return [str(pattern) for pattern in config.get("exclude", [])] + list(GENERATED_MAPPING_SNAPSHOT_EXCLUDES)


def mapping_path_is_excluded(rel: str, patterns: list[str]) -> bool:
    parts = rel.split("/")
    return any(
        fnmatch.fnmatch(rel, pattern.rstrip("/"))
        or fnmatch.fnmatch(rel + "/", pattern)
        or (pattern.endswith("/") and fnmatch.fnmatch(rel + "/", pattern + "*"))
        or (pattern.endswith("/") and pattern.rstrip("/") in parts)
        for pattern in patterns
    )


def mapping_fingerprint(local_base: Path, mapping: dict[str, Any], exclude_patterns: list[str]) -> str:
    root = local_base / str(mapping.get("local", ""))
    digest = hashlib.sha256()
    digest.update(str(mapping.get("name", "")).encode())
    digest.update(b"\0")
    if not root.exists():
        digest.update(b"missing")
        return digest.hexdigest()
    candidates = [root] if root.is_file() else sorted(path for path in root.rglob("*") if path.is_file())
    for path in candidates:
        rel = path.relative_to(local_base).as_posix()
        if mapping_path_is_excluded(rel, exclude_patterns):
            continue
        digest.update(rel.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def mapping_snapshot(config: dict[str, Any], app_dir: Path, mappings: list[dict[str, Any]]) -> dict[str, str]:
    local_base = accessors.local_project_dir_for_config(config, app_dir)
    exclude_patterns = mapping_snapshot_exclude_patterns(config)
    return {
        str(mapping["name"]): mapping_fingerprint(local_base, mapping, exclude_patterns)
        for mapping in mappings
    }


def mapping_file_fingerprints(config: dict[str, Any], app_dir: Path, mappings: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    local_base = accessors.local_project_dir_for_config(config, app_dir)
    exclude_patterns = mapping_snapshot_exclude_patterns(config)
    fingerprints: dict[str, dict[str, str]] = {}
    for mapping in mappings:
        root = local_base / str(mapping.get("local", ""))
        files: dict[str, str] = {}
        if root.exists():
            candidates = [root] if root.is_file() else sorted(path for path in root.rglob("*") if path.is_file())
            for path in candidates:
                rel = path.relative_to(local_base).as_posix()
                if mapping_path_is_excluded(rel, exclude_patterns):
                    continue
                digest = hashlib.sha256()
                digest.update(path.read_bytes())
                files[rel] = digest.hexdigest()
        fingerprints[str(mapping["name"])] = files
    return fingerprints


def load_runtime_mapping_snapshot(config: dict[str, Any], app_dir: Path) -> dict[str, str]:
    try:
        path = accessors.config_path(config, "build_settings", app_dir, "state")
    except KeyError:
        return {}
    settings = build_settings.read_build_settings_file(path)
    snapshot = settings.get("mapping_snapshot")
    if not isinstance(snapshot, dict):
        return {}
    return {str(name): str(value) for name, value in snapshot.items() if str(name).strip()}


def load_runtime_mapping_file_snapshot(config: dict[str, Any], app_dir: Path) -> dict[str, dict[str, str]]:
    try:
        path = accessors.config_path(config, "build_settings", app_dir, "state")
    except KeyError:
        return {}
    settings = build_settings.read_build_settings_file(path)
    snapshot = settings.get("mapping_file_snapshot")
    if not isinstance(snapshot, dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for name, files in snapshot.items():
        if isinstance(files, dict) and str(name).strip():
            result[str(name)] = {str(path): str(value) for path, value in files.items() if str(path).strip()}
    return result


def load_runtime_mapping_build_file_snapshot(config: dict[str, Any], app_dir: Path) -> dict[str, dict[str, str]]:
    try:
        path = accessors.config_path(config, "build_settings", app_dir, "state")
    except KeyError:
        return {}
    settings = build_settings.read_build_settings_file(path)
    snapshot = settings.get("mapping_build_file_snapshot")
    if not isinstance(snapshot, dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for name, files in snapshot.items():
        if isinstance(files, dict) and str(name).strip():
            result[str(name)] = {str(path): str(value) for path, value in files.items() if str(path).strip()}
    return result


def load_runtime_mapping_pending_changes(config: dict[str, Any], app_dir: Path) -> tuple[list[str], list[str]]:
    try:
        path = accessors.config_path(config, "build_settings", app_dir, "state")
    except KeyError:
        return [], []
    settings = build_settings.read_build_settings_file(path)
    mappings = settings.get("mapping_pending_mappings")
    files = settings.get("mapping_pending_files")
    pending_mappings = [str(name) for name in mappings if str(name).strip()] if isinstance(mappings, list) else []
    pending_files = [str(path) for path in files if str(path).strip()] if isinstance(files, list) else []
    return sorted(set(pending_mappings)), sorted(set(pending_files))


def clear_runtime_mapping_pending_changes(config: dict[str, Any], app_dir: Path) -> None:
    path = accessors.config_path(config, "build_settings", app_dir, "state")
    settings = build_settings.read_build_settings_file(path)
    settings.pop("mapping_pending_mappings", None)
    settings.pop("mapping_pending_files", None)
    build_settings.write_build_settings_file(path, settings)


def git_changed_files_under(base: Path, *, git_dir: Path) -> list[str]:
    try:
        root_result = subprocess.run(
            ["git", "-C", str(git_dir), "rev-parse", "--show-toplevel"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return []
    if root_result.returncode != 0:
        return []
    git_root = Path(root_result.stdout.strip()).resolve()
    base_resolved = base.resolve()
    try:
        pathspec = base_resolved.relative_to(git_root).as_posix()
    except ValueError:
        pathspec = str(base_resolved)
    changed: list[str] = []
    for argv in (
        ["git", "-C", str(git_dir), "diff", "--name-only", "HEAD", "--", pathspec],
        ["git", "-C", str(git_dir), "ls-files", "--others", "--exclude-standard", "--", pathspec],
    ):
        result = subprocess.run(argv, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if result.returncode not in (0, 1):
            continue
        for raw in result.stdout.splitlines():
            path = (git_root / raw.strip()).resolve()
            try:
                changed.append(path.relative_to(base_resolved).as_posix())
            except ValueError:
                continue
    return sorted(set(changed))


def mapping_contains_path(mapping: dict[str, Any], rel: str) -> bool:
    local = str(mapping.get("local", "")).strip().strip("/")
    if not local or local == ".":
        return True
    return rel == local or rel.startswith(local + "/")


def mapping_names_for_files(mappings: list[dict[str, Any]], files: list[str]) -> list[str]:
    names: set[str] = set()
    for mapping in mappings:
        if any(mapping_contains_path(mapping, path) for path in files):
            names.add(str(mapping["name"]))
    return sorted(names)


def reset_runtime_mapping_state(config: dict[str, Any], app_dir: Path, mappings: list[dict[str, Any]] | None = None) -> None:
    path = accessors.config_path(config, "build_settings", app_dir, "state")
    settings = build_settings.read_build_settings_file(path)
    active_mappings = mappings or []
    pending_files = settings.get("mapping_pending_files", [])
    local_base = accessors.local_project_dir_for_config(config, app_dir)
    exclude_patterns = mapping_snapshot_exclude_patterns(config)
    git_changed_files = [
        rel
        for rel in git_changed_files_under(local_base, git_dir=app_dir)
        if not mapping_path_is_excluded(rel, exclude_patterns)
        and any(mapping_contains_path(mapping, rel) for mapping in active_mappings)
    ]
    changed_files = git_changed_files or [
        str(rel)
        for rel in pending_files
        if str(rel).strip() and any(mapping_contains_path(mapping, str(rel)) for mapping in active_mappings)
    ]
    settings["mapping_snapshot"] = mapping_snapshot(config, app_dir, active_mappings)
    settings["mapping_file_snapshot"] = mapping_file_fingerprints(config, app_dir, active_mappings)
    settings["mapping_pending_mappings"] = mapping_names_for_files(active_mappings, changed_files)
    settings["mapping_pending_files"] = sorted(set(changed_files))
    build_settings.write_build_settings_file(path, settings)


def mark_runtime_mapping_build_applied(
    config: dict[str, Any],
    app_dir: Path,
    mappings: list[dict[str, Any]],
    applied_files: list[str] | None = None,
) -> None:
    path = accessors.config_path(config, "build_settings", app_dir, "state")
    settings = build_settings.read_build_settings_file(path)
    current_snapshot = mapping_snapshot(config, app_dir, mappings)
    current_files = mapping_file_fingerprints(config, app_dir, mappings)
    if applied_files is None:
        settings["mapping_build_snapshot"] = current_snapshot
        settings["mapping_build_file_snapshot"] = current_files
        settings.pop("mapping_pending_mappings", None)
        settings.pop("mapping_pending_files", None)
        build_settings.write_build_settings_file(path, settings)
        return

    applied = {str(path) for path in applied_files if str(path).strip()}
    build_files = load_runtime_mapping_build_file_snapshot(config, app_dir)
    for mapping in mappings:
        name = str(mapping["name"])
        mapping_files = current_files.get(name, {})
        saved = dict(build_files.get(name, {}))
        for rel in sorted(applied):
            if not mapping_contains_path(mapping, rel):
                continue
            if rel in mapping_files:
                saved[rel] = mapping_files[rel]
            else:
                saved.pop(rel, None)
        build_files[name] = saved
    _pending_mappings, pending_files = load_runtime_mapping_pending_changes(config, app_dir)
    remaining = sorted(set(pending_files) - applied)
    settings["mapping_build_file_snapshot"] = build_files
    settings["mapping_pending_files"] = remaining
    settings["mapping_pending_mappings"] = mapping_names_for_files(mappings, remaining)
    build_settings.write_build_settings_file(path, settings)


def changed_mapping_files_from_snapshots(
    baseline: dict[str, dict[str, str]],
    current: dict[str, dict[str, str]],
    mappings: list[dict[str, Any]],
    changed_mapping_names: set[str],
) -> list[str]:
    changed: set[str] = set()
    for mapping in mappings:
        name = str(mapping["name"])
        if name not in changed_mapping_names:
            continue
        before = baseline.get(name)
        after = current.get(name, {})
        if before is None:
            changed.update(after)
            continue
        for path in sorted(set(before) | set(after)):
            if before.get(path) != after.get(path):
                changed.add(path)
    return sorted(changed)


def save_runtime_mapping_snapshot(config: dict[str, Any], app_dir: Path, mappings: list[dict[str, Any]]) -> None:
    path = accessors.config_path(config, "build_settings", app_dir, "state")
    settings = build_settings.read_build_settings_file(path)
    previous_files = load_runtime_mapping_build_file_snapshot(config, app_dir)
    current_snapshot = mapping_snapshot(config, app_dir, mappings)
    current_files = mapping_file_fingerprints(config, app_dir, mappings)
    changed_names = {
        str(mapping["name"])
        for mapping in mappings
        if previous_files.get(str(mapping["name"])) != current_files.get(str(mapping["name"]))
    }
    changed_files = changed_mapping_files_from_snapshots(previous_files, current_files, mappings, changed_names)
    pending_names = set(settings.get("mapping_pending_mappings", [])) if isinstance(settings.get("mapping_pending_mappings"), list) else set()
    pending_files = set(settings.get("mapping_pending_files", [])) if isinstance(settings.get("mapping_pending_files"), list) else set()
    settings["mapping_pending_mappings"] = sorted({str(name) for name in pending_names | changed_names if str(name).strip()})
    settings["mapping_pending_files"] = sorted({str(path) for path in pending_files | set(changed_files) if str(path).strip()})
    settings["mapping_snapshot"] = current_snapshot
    settings["mapping_file_snapshot"] = current_files
    build_settings.write_build_settings_file(path, settings)


def changed_runtime_mappings(config: dict[str, Any], app_dir: Path, mappings: list[dict[str, Any]]) -> list[str]:
    baseline = load_runtime_mapping_snapshot(config, app_dir)
    current = mapping_snapshot(config, app_dir, mappings)
    pending, _pending_files = load_runtime_mapping_pending_changes(config, app_dir)
    changed = {str(mapping["name"]) for mapping in mappings if baseline.get(str(mapping["name"])) != current.get(str(mapping["name"]))}
    changed.update(name for name in pending if name in {str(mapping["name"]) for mapping in mappings})
    return sorted(changed)


def changed_runtime_mapping_files(config: dict[str, Any], app_dir: Path, mappings: list[dict[str, Any]]) -> list[str]:
    baseline = load_runtime_mapping_file_snapshot(config, app_dir)
    current = mapping_file_fingerprints(config, app_dir, mappings)
    _pending_mappings, pending_files = load_runtime_mapping_pending_changes(config, app_dir)
    changed_mapping_names = set(changed_runtime_mappings(config, app_dir, mappings))
    changed = set(changed_mapping_files_from_snapshots(baseline, current, mappings, changed_mapping_names))
    changed.update(pending_files)
    return sorted(changed)


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
