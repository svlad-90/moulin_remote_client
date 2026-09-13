#!/usr/bin/env python3
"""Local TUI client for remote Moulin product development."""

from __future__ import annotations

import argparse
import curses
import json
import os
import re
import select
import shlex
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable

try:
    import yaml
except ImportError:
    yaml = None


os.environ.setdefault("ESCDELAY", "100")

APP_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = APP_DIR / "moulin_remote_client.config.json"
DEFAULT_CONFIG_EXAMPLE = APP_DIR / "moulin_remote_client.config.example.json"
DEFAULT_DOCKER_IMAGE = ""
DEFAULT_DOCKERFILE = "doc/Dockerfile"
DEFAULT_BUILD_TARGETS = ""
DEFAULT_MOULIN_MANIFEST = "product.yaml"
UI_PROFILE_SLOW_MS = 20.0
TEXT_KEY_OFFSET = sys.maxunicode + 1
MANIFEST_CACHE: dict[tuple[str, str, str], dict[str, Any]] = {}
KEY_ALIASES = {
    "a": ("a", "ф"),
    "b": ("b", "и"),
    "d": ("d", "в"),
    "f": ("f", "а"),
    "h": ("h", "р"),
    "j": ("j", "о"),
    "k": ("k", "л"),
    "l": ("l", "д"),
    "n": ("n", "т"),
    "p": ("p", "з"),
    "q": ("q", "й"),
    "r": ("r", "к"),
    "s": ("s", "ы", "і"),
    "y": ("y", "н"),
}

if yaml is not None:
    class MoulinYamlLoader(yaml.SafeLoader):
        pass

    MoulinYamlLoader.yaml_implicit_resolvers = {
        key: [
            resolver
            for resolver in value
            if resolver[0] != "tag:yaml.org,2002:bool"
        ]
        for key, value in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }

    def construct_moulin_tag(loader: "MoulinYamlLoader", tag_suffix: str, node: Any) -> Any:
        if isinstance(node, yaml.MappingNode):
            return loader.construct_mapping(node, deep=True)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node, deep=True)
        return loader.construct_scalar(node)

    MoulinYamlLoader.add_multi_constructor("!", construct_moulin_tag)
    MoulinYamlLoader.add_constructor(None, lambda loader, node: construct_moulin_tag(loader, "", node))
else:
    MoulinYamlLoader = None

MOULIN_TAG_RE = re.compile(r"(?m)(?:^|[\s\[{,:-])(!(?![!\s])(?:<[^>\r\n]+>|[A-Za-z0-9_.-]+(?:![A-Za-z0-9_./:-]+)?))")
YAML_TAG_DIRECTIVE_RE = re.compile(r"(?m)^%TAG\s+(![^ \t]*)\s+([^ \t\r\n]+)")


def moulin_yaml_tags(text: str) -> list[str]:
    tags: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0]
        if YAML_TAG_DIRECTIVE_RE.search(line):
            tags.add("%TAG")
        tags.update(match.group(1) for match in MOULIN_TAG_RE.finditer(line))
    return sorted(tags)


def moulin_manifest_markers(data: dict[str, Any]) -> list[str]:
    markers: list[str] = []
    if "min_ver" in data:
        markers.append("min_ver")
    components = data.get("components")
    if isinstance(components, dict) and components:
        markers.append("components")
        for raw in components.values():
            if isinstance(raw, dict) and isinstance(raw.get("builder"), dict) and raw["builder"].get("type"):
                markers.append("builder.type")
                break
    for key in ("images", "parameters", "variables", "common_data"):
        if isinstance(data.get(key), dict):
            markers.append(key)
    return markers


def is_moulin_manifest_data(data: dict[str, Any]) -> bool:
    markers = set(moulin_manifest_markers(data))
    return "min_ver" in markers and (
        "components" in markers
        or "images" in markers
        or "parameters" in markers
        or "builder.type" in markers
    )


def load_config(path: Path) -> dict[str, Any]:
    source = path if path.exists() else DEFAULT_CONFIG_EXAMPLE
    with source.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    config["__config_path"] = str(path)
    normalize_remote_profiles(config)
    normalize_project_profiles(config)
    apply_env_overrides(config)
    sync_active_remote(config)
    sync_active_project(config)
    return config


def save_config(config: dict[str, Any]) -> None:
    if "__config_path" not in config:
        raise RuntimeError("Refusing to save config without __config_path")
    path = Path(str(config.get("__config_path", DEFAULT_CONFIG)))
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {key: value for key, value in config.items() if not key.startswith("__")}
    sync_active_remote(config)
    sync_active_project(config)
    for key in ("remote", "remotes", "active_remote", "project", "projects", "active_project", "local", "moulin", "docker", "state", "inventory", "mappings", "exclude", "ui"):
        if key in config:
            data[key] = config[key]
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def empty_remote_profile(name: str = "") -> dict[str, str]:
    return {
        "name": name,
        "label": name,
        "user": "",
        "host": "",
        "project_dir": "",
        "git_url": "",
        "moulin_manifest": "",
        "dockerfile": "",
        "docker_image": "",
    }


def is_blank_default_remote(remote: dict[str, Any]) -> bool:
    return (
        str(remote.get("name", "")) == "default"
        and str(remote.get("label", "")) in ("", "default", "remote")
        and not str(remote.get("user", "")).strip()
        and not str(remote.get("host", "")).strip()
        and not str(remote.get("project_dir", "")).strip()
        and not str(remote.get("git_url", "")).strip()
    )


def normalize_remote_profiles(config: dict[str, Any]) -> None:
    remotes = config.get("remotes")
    if not isinstance(remotes, list):
        remote = dict(config.get("remote", {}))
        remote.setdefault("name", str(remote.get("label") or ""))
        remote.setdefault("label", str(remote.get("name") or "remote"))
        remote.setdefault("user", "")
        remote.setdefault("host", "")
        remote.setdefault("project_dir", "")
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
        remote.setdefault("project_dir", "")
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


def _legacy_build_settings(config: dict[str, Any]) -> dict[str, Any]:
    try:
        path = state_path(config, "build_settings")
    except KeyError:
        return {}
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


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
    }


def normalize_project_profiles(config: dict[str, Any]) -> None:
    projects = config.get("projects")
    if not isinstance(projects, list):
        settings = _legacy_build_settings(config)
        remote = active_remote(config)
        project = {
            "name": str(config.get("active_project") or config.get("project", {}).get("name") or "default"),
            "label": str(config.get("project", {}).get("label") or config.get("active_project") or "default"),
            "project_dir": str(remote.get("project_dir") or config.get("project", {}).get("project_dir", "")),
            "local_project_dir": str(config.get("local", {}).get("project_dir", "workspace/project-overlay")),
            "git_url": str(remote.get("git_url") or config.get("project", {}).get("git_url", "")),
            "git_ref": str(config.get("project", {}).get("git_ref", "")),
            "moulin_manifest": str(remote.get("moulin_manifest") or config.get("moulin", {}).get("manifest", DEFAULT_MOULIN_MANIFEST)),
            "dockerfile": str(remote.get("dockerfile") or config.get("docker", {}).get("dockerfile", DEFAULT_DOCKERFILE)),
            "docker_image": str(settings.get("docker_image") or remote.get("docker_image") or config.get("docker", {}).get("image", "")),
            "parameters": dict(settings.get("parameters", {})) if isinstance(settings.get("parameters", {}), dict) else {},
            "targets": str(settings.get("targets", build_targets())),
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
        project.setdefault("project_dir", str(active_remote(config).get("project_dir") or config.get("project", {}).get("project_dir", "")))
        project.setdefault("local_project_dir", str(config.get("local", {}).get("project_dir", "workspace/project-overlay")))
        project.setdefault("git_url", str(config.get("project", {}).get("git_url", "")))
        project.setdefault("git_ref", str(config.get("project", {}).get("git_ref", "")))
        project.setdefault("moulin_manifest", str(config.get("moulin", {}).get("manifest", DEFAULT_MOULIN_MANIFEST)))
        project.setdefault("dockerfile", str(config.get("docker", {}).get("dockerfile", DEFAULT_DOCKERFILE)))
        project.setdefault("docker_image", str(config.get("docker", {}).get("image", "")))
        if not isinstance(project.get("parameters"), dict):
            project["parameters"] = {}
        project.setdefault("targets", build_targets())
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


def apply_env_overrides(config: dict[str, Any]) -> None:
    remote = active_remote(config)
    mapping = {
        "MOULIN_REMOTE_SSH_USER": "user",
        "MOULIN_REMOTE_SSH_HOST": "host",
    }
    for env_name, key in mapping.items():
        value = os.environ.get(env_name)
        if value:
            remote[key] = value
    sync_active_remote(config)
    project_dir = os.environ.get("MOULIN_REMOTE_PROJECT_DIR")
    if project_dir:
        active_project(config)["project_dir"] = project_dir
        sync_active_project(config)
    git_url = os.environ.get("MOULIN_REMOTE_PROJECT_GIT_URL")
    if git_url:
        active_project(config)["git_url"] = git_url
        sync_active_project(config)
    git_ref = os.environ.get("MOULIN_REMOTE_PROJECT_GIT_REF")
    if git_ref:
        active_project(config)["git_ref"] = git_ref
        sync_active_project(config)


def task_path(config: dict[str, Any], key: str) -> Path:
    value = Path(config["inventory"][key])
    return value if value.is_absolute() else APP_DIR / value


def state_path(config: dict[str, Any], key: str) -> Path:
    value = Path(config.get("state", {})[key])
    return value if value.is_absolute() else APP_DIR / value


def local_project_dir(config: dict[str, Any]) -> Path:
    project_value = str(active_project(config).get("local_project_dir", "")).strip()
    value = Path(project_value or config["local"]["project_dir"])
    return value if value.is_absolute() else APP_DIR / value


def ui_title(config: dict[str, Any]) -> str:
    return str(config.get("ui", {}).get("title", "Moulin Client"))


def remote_label(config: dict[str, Any]) -> str:
    return str(active_remote(config).get("label", active_remote(config).get("name", "remote")))


def remote_spec(config: dict[str, Any]) -> str:
    remote = active_remote(config)
    return f"{remote.get('user', '')}@{remote.get('host', '')}"


def remote_project_dir(config: dict[str, Any]) -> str:
    project_value = str(active_project(config).get("project_dir", "")).strip()
    if project_value:
        return project_value.rstrip("/")
    return str(active_remote(config).get("project_dir", "")).rstrip("/")


def project_git_url(config: dict[str, Any]) -> str:
    project_value = str(active_project(config).get("git_url", "")).strip()
    if project_value:
        return project_value
    return str(active_remote(config).get("git_url", "")).strip()


def project_git_ref(config: dict[str, Any]) -> str:
    return str(active_project(config).get("git_ref", "")).strip()


def remote_user(config: dict[str, Any]) -> str:
    return str(active_remote(config).get("user", "")).strip()


def remote_host(config: dict[str, Any]) -> str:
    return str(active_remote(config).get("host", "")).strip()


def remote_has_user(config: dict[str, Any]) -> bool:
    return bool(remote_user(config))


def remote_has_host(config: dict[str, Any]) -> bool:
    return bool(remote_host(config))


def remote_has_ssh(config: dict[str, Any]) -> bool:
    return remote_has_user(config) and remote_has_host(config)


def remote_has_project_dir(config: dict[str, Any]) -> bool:
    return bool(remote_project_dir(config))


def docker_image() -> str:
    return os.environ.get("MOULIN_REMOTE_DOCKER_IMAGE", DEFAULT_DOCKER_IMAGE)


def configured_docker_image(config: dict[str, Any]) -> str:
    project_value = str(active_project(config).get("docker_image", "")).strip()
    if project_value:
        return project_value
    remote_value = str(active_remote(config).get("docker_image", "")).strip()
    if remote_value:
        return remote_value
    return str(config.get("docker", {}).get("image", docker_image()))


def configured_dockerfile(config: dict[str, Any]) -> str:
    project_value = str(active_project(config).get("dockerfile", "")).strip()
    if project_value:
        return project_value
    remote_value = str(active_remote(config).get("dockerfile", "")).strip()
    if remote_value:
        return remote_value
    return str(config.get("docker", {}).get("dockerfile", DEFAULT_DOCKERFILE))


def build_targets() -> str:
    return os.environ.get("MOULIN_REMOTE_BUILD_TARGETS", DEFAULT_BUILD_TARGETS)


def moulin_manifest_name(config: dict[str, Any]) -> str:
    project_value = str(active_project(config).get("moulin_manifest", "")).strip()
    if project_value:
        return project_value
    remote_value = str(active_remote(config).get("moulin_manifest", "")).strip()
    if remote_value:
        return remote_value
    return str(config.get("moulin", {}).get("manifest", DEFAULT_MOULIN_MANIFEST))


def remote_read_project_file(config: dict[str, Any], path: str) -> str:
    target = path if Path(path).is_absolute() else f"./{path.lstrip('./')}"
    script = f"cd {shlex.quote(remote_project_dir(config))} && cat -- {shlex.quote(target)}"
    return capture(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", remote_spec(config), script], echo=False, timeout=15)


def moulin_manifest_path(config: dict[str, Any]) -> Path:
    manifest = Path(moulin_manifest_name(config))
    candidates = []
    if manifest.is_absolute():
        candidates.append(manifest)
    else:
        candidates.append(local_project_dir(config) / manifest)
        fallback = config.get("moulin", {}).get("fallback_manifest")
        if fallback:
            fallback_path = Path(str(fallback))
            candidates.append(fallback_path if fallback_path.is_absolute() else APP_DIR / fallback_path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def load_moulin_manifest(config: dict[str, Any]) -> dict[str, Any]:
    if yaml is None or MoulinYamlLoader is None:
        return {}
    manifest_name = moulin_manifest_name(config)
    if remote_has_ssh(config) and remote_has_project_dir(config) and manifest_name:
        cache_key = (remote_spec(config), remote_project_dir(config), manifest_name)
        if cache_key in MANIFEST_CACHE:
            return MANIFEST_CACHE[cache_key]
        try:
            data = yaml.load(remote_read_project_file(config, manifest_name), Loader=MoulinYamlLoader)
            result = data if isinstance(data, dict) else {}
            MANIFEST_CACHE[cache_key] = result
            return result
        except Exception:
            pass
    path = moulin_manifest_path(config)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.load(handle, Loader=MoulinYamlLoader)
    return data if isinstance(data, dict) else {}


def load_build_settings(config: dict[str, Any]) -> dict[str, Any]:
    project = active_project(config)
    if project:
        settings: dict[str, Any] = {
            "parameters": dict(project.get("parameters", {})) if isinstance(project.get("parameters", {}), dict) else {},
            "targets": str(project.get("targets", build_targets())),
            "docker_image": str(project.get("docker_image", "")),
        }
        legacy = _legacy_build_settings(config)
        if legacy:
            settings["parameters"] = {**dict(legacy.get("parameters", {})), **settings["parameters"]} if isinstance(legacy.get("parameters", {}), dict) else settings["parameters"]
            settings["targets"] = settings["targets"] or str(legacy.get("targets", ""))
            settings["docker_image"] = settings["docker_image"] or str(legacy.get("docker_image", ""))
        return settings
    try:
        path = state_path(config, "build_settings")
    except KeyError:
        return {}
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def save_build_settings(config: dict[str, Any], settings: dict[str, Any]) -> None:
    project = active_project(config)
    if project:
        if isinstance(settings.get("parameters"), dict):
            project["parameters"] = dict(settings["parameters"])
        project["targets"] = str(settings.get("targets", ""))
        project["docker_image"] = str(settings.get("docker_image", ""))
        sync_active_project(config)
        save_config(config)
    path = state_path(config, "build_settings")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def moulin_parameters(config: dict[str, Any]) -> list[dict[str, Any]]:
    data = load_moulin_manifest(config)
    if not data:
        return []
    raw_params = data.get("parameters", {}) if isinstance(data, dict) else {}
    result: list[dict[str, Any]] = []
    if not isinstance(raw_params, dict):
        return result
    for name, raw in raw_params.items():
        if not isinstance(raw, dict):
            continue
        choices = [str(key) for key in raw.keys() if key != "desc" and isinstance(raw.get(key), dict)]
        default = next(
            (
                choice
                for choice in choices
                if str(raw.get(choice, {}).get("default", "")).strip().lower() == "true"
            ),
            choices[0] if choices else "",
        )
        result.append({"name": str(name), "desc": str(raw.get("desc", "")), "choices": choices, "default": default})
    return result


def default_build_params(config: dict[str, Any]) -> dict[str, str]:
    return {param["name"]: str(param["default"]) for param in moulin_parameters(config)}


def moulin_target_candidates(config: dict[str, Any], build_params: dict[str, str] | None = None) -> list[dict[str, str]]:
    data = load_moulin_manifest(config)
    if not data:
        return []
    candidates: dict[str, dict[str, str]] = {}

    def add_image_targets(images: Any, source: str) -> None:
        if not isinstance(images, dict):
            return
        for name, raw in images.items():
            desc = raw.get("desc", "") if isinstance(raw, dict) else ""
            target = f"{name}.img.gz"
            candidates.setdefault(target, {"target": target, "source": source, "desc": str(desc)})

    def add_component_targets(components: Any, source: str) -> None:
        if not isinstance(components, dict):
            return
        for name, raw in components.items():
            builder = raw.get("builder", {}) if isinstance(raw, dict) else {}
            if isinstance(builder, dict) and builder.get("target_images"):
                target = str(name)
                desc = f"{source} component target"
                candidates.setdefault(target, {"target": target, "source": source, "desc": desc})

    add_image_targets(data.get("images"), "manifest")
    add_component_targets(data.get("components"), "manifest")
    selected = build_params or default_build_params(config)
    params = data.get("parameters", {})
    if isinstance(params, dict):
        for param_name, value in selected.items():
            param = params.get(param_name)
            if not isinstance(param, dict):
                continue
            choice = param.get(value)
            if not isinstance(choice, dict):
                continue
            overrides = choice.get("overrides", {})
            if isinstance(overrides, dict):
                add_image_targets(overrides.get("images"), f"{param_name}={value}")
                add_component_targets(overrides.get("components"), f"{param_name}={value}")
    return sorted(candidates.values(), key=lambda item: item["target"])


def auto_connect_enabled() -> bool:
    value = os.environ.get("MOULIN_REMOTE_AUTO_CONNECT", "yes").strip().lower()
    return value not in {"0", "false", "no", "off"}


def run(
    argv: list[str],
    *,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    print("+ " + shlex.join(argv))
    return subprocess.run(argv, text=True, check=check, env=env)


def capture(argv: list[str], *, echo: bool = True, timeout: float | None = None) -> str:
    if echo:
        print("+ " + shlex.join(argv), file=sys.stderr)
    result = subprocess.run(argv, text=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, check=True)
    return result.stdout


def rsync_excludes(config: dict[str, Any]) -> list[str]:
    args: list[str] = []
    for pattern in config.get("exclude", []):
        args.extend(["--exclude", pattern])
    return args


def normalize_relpath(path: str) -> str:
    clean = path.strip()
    if not clean:
        raise ValueError("empty path")
    clean = clean.removeprefix("./").rstrip("/")
    if clean in ("", "."):
        raise ValueError("project root is not allowed as a sync path")
    parts = Path(clean).parts
    if clean.startswith("/") or ".." in parts:
        raise ValueError(f"unsafe path: {path}")
    return clean


def normalize_mapping_path(path: str) -> str:
    clean = path.strip()
    if clean in ("", "."):
        return "."
    return normalize_relpath(clean)


def mappings(config: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in config.get("mappings", []):
        name = str(raw["name"]).strip()
        if not name:
            raise SystemExit("mapping with empty name")
        if name in seen:
            raise SystemExit(f"duplicate mapping name: {name}")
        seen.add(name)
        kind = str(raw.get("kind", "directory"))
        if kind not in ("directory", "file"):
            raise SystemExit(f"mapping {name}: unsupported kind {kind!r}")
        result.append(
            {
                "name": name,
                "role": str(raw.get("role", "")),
                "remote": normalize_mapping_path(str(raw["remote"])),
                "local": normalize_mapping_path(str(raw.get("local", raw["remote"]))),
                "kind": kind,
                "push": bool(raw.get("push", True)),
            }
        )
    return result


def select_mappings(config: dict[str, Any], names: list[str]) -> list[dict[str, Any]]:
    all_mappings = mappings(config)
    by_name = {mapping["name"]: mapping for mapping in all_mappings}
    if not names:
        raise SystemExit("mapping names are required; use 'all' for every mapping")
    if names == ["all"]:
        return all_mappings
    missing = [name for name in names if name not in by_name]
    if missing:
        raise SystemExit("unknown mapping(s): " + ", ".join(missing))
    return [by_name[name] for name in names]


def read_selection(config: dict[str, Any]) -> list[str]:
    selection = task_path(config, "selection")
    if not selection.exists():
        raise SystemExit(f"selection file does not exist: {selection}")
    paths: list[str] = []
    for raw in selection.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            paths.append(normalize_relpath(line))
    if not paths:
        raise SystemExit(f"selection file is empty: {selection}")
    return paths


def write_selection(config: dict[str, Any], paths: list[str], *, echo: bool = True) -> None:
    selection = task_path(config, "selection")
    selection.parent.mkdir(parents=True, exist_ok=True)
    selection.write_text("\n".join(paths) + "\n", encoding="utf-8")
    if echo:
        print(f"selection: {selection}")


def mapping_selection_path(config: dict[str, Any]) -> Path:
    return task_path(config, "mapping_selection")


def read_mapping_selection(config: dict[str, Any]) -> list[str]:
    selection = mapping_selection_path(config)
    if not selection.exists():
        raise SystemExit(f"mapping selection file does not exist: {selection}")
    names = []
    for raw in selection.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            names.append(line)
    if not names:
        raise SystemExit(f"no mappings selected: {selection}")
    return names


def read_mapping_selection_if_exists(config: dict[str, Any]) -> list[str]:
    selection = mapping_selection_path(config)
    if not selection.exists():
        return []
    names = []
    for raw in selection.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            names.append(line)
    return names


def write_mapping_selection(config: dict[str, Any], names: list[str], *, echo: bool = True) -> None:
    selection = mapping_selection_path(config)
    text = "\n".join(names)
    selection.parent.mkdir(parents=True, exist_ok=True)
    selection.write_text(text + ("\n" if text else ""), encoding="utf-8")
    if echo:
        print(f"mapping selection: {selection}")


def inventory_command(config: dict[str, Any]) -> str:
    max_depth = int(config["inventory"].get("max_depth", 5))
    prune_parts = []
    for pattern in config.get("exclude", []):
        if pattern.endswith("/"):
            prune_parts.append(f"-path {shlex.quote('./' + pattern.rstrip('/'))}")
    prune = " -o ".join(prune_parts)
    prune_expr = f"\\( {prune} \\) -prune -o " if prune else ""
    return (
        f"cd {shlex.quote(remote_project_dir(config))} && "
        f"find . -mindepth 1 -maxdepth {max_depth} {prune_expr}"
        "-type d -print | sed 's#^./##' | sort"
    )


def project_tree_command(config: dict[str, Any], depth: int) -> str:
    depth = max(1, min(depth, 99))
    prune_parts = []
    for pattern in config.get("exclude", []):
        if pattern.endswith("/"):
            clean = pattern.rstrip("/")
            prune_parts.append(f"-path {shlex.quote('./' + clean)}")
            prune_parts.append(f"-path {shlex.quote('./' + clean + '/*')}")
            prune_parts.append(f"-name {shlex.quote(PurePosixPath(clean).name)}")
        else:
            prune_parts.append(f"-name {shlex.quote(pattern)}")
    prune = " -o ".join(prune_parts)
    prune_expr = f"\\( {prune} \\) -prune -o " if prune else ""
    return (
        f"cd {shlex.quote(remote_project_dir(config))} && "
        f"find . -mindepth 1 -maxdepth {depth} {prune_expr}"
        "-type d -printf 'd\\t%P\\n' | sort -k2"
    )


def project_listing_command(config: dict[str, Any], directory: str) -> str:
    directory = normalize_mapping_path(directory)
    find_root = "." if directory == "." else f"./{directory}"
    prune_parts = []
    for pattern in config.get("exclude", []):
        if pattern.endswith("/"):
            clean = pattern.rstrip("/")
            prune_parts.append(f"-path {shlex.quote('./' + clean)}")
            prune_parts.append(f"-path {shlex.quote('./' + clean + '/*')}")
            prune_parts.append(f"-name {shlex.quote(PurePosixPath(clean).name)}")
        else:
            prune_parts.append(f"-name {shlex.quote(pattern)}")
    prune = " -o ".join(prune_parts)
    prune_expr = f"\\( {prune} \\) -prune -o " if prune else ""
    return (
        f"cd {shlex.quote(remote_project_dir(config))} && "
        f"find {shlex.quote(find_root)} -mindepth 1 -maxdepth 1 {prune_expr}"
        "\\( -type d -printf 'd\\t%p\\n' -o -type f -printf 'f\\t%p\\n' -o -type l -printf 'l\\t%p\\n' \\) "
        "| sed 's#\\t\\./#\\t#' | sort -k1,1 -k2,2"
    )


def cmd_status(config: dict[str, Any]) -> None:
    local_dir = local_project_dir(config)
    print(f"local overlay: {local_dir}")
    print(f"remote project: {remote_spec(config)}:{remote_project_dir(config)}")
    print(f"mapped areas: {len(mappings(config))}")
    if local_dir.exists():
        run(["du", "-sh", str(local_dir)], check=False)
    else:
        print("local overlay does not exist yet")
    remote_cmd = (
        f"cd {shlex.quote(remote_project_dir(config))} && "
        "pwd && df -h . && git status --short --branch || true"
    )
    run(["ssh", remote_spec(config), remote_cmd], check=False)


def cmd_inventory(config: dict[str, Any]) -> None:
    output = task_path(config, "output")
    output.parent.mkdir(parents=True, exist_ok=True)
    text = capture(["ssh", remote_spec(config), inventory_command(config)])
    output.write_text(text, encoding="utf-8")
    count = len([line for line in text.splitlines() if line.strip()])
    print(f"inventory: {output}")
    print(f"directories: {count}")


def parse_ranges(raw: str, limit: int) -> list[int]:
    indexes: list[int] = []
    for item in raw.replace(",", " ").split():
        if "-" in item:
            start_s, end_s = item.split("-", 1)
            start = int(start_s)
            end = int(end_s)
            indexes.extend(range(start, end + 1))
        else:
            indexes.append(int(item))
    unique = sorted(set(indexes))
    for index in unique:
        if index < 1 or index > limit:
            raise ValueError(f"selection index out of range: {index}")
    return unique


def cmd_choose(config: dict[str, Any]) -> None:
    inventory = task_path(config, "output")
    if not inventory.exists():
        raise SystemExit(f"inventory file does not exist, run inventory first: {inventory}")
    paths = [line.strip() for line in inventory.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not paths:
        raise SystemExit(f"inventory file is empty: {inventory}")
    for index, path in enumerate(paths, 1):
        print(f"{index:4d}  {path}")
    raw = input("Select numbers/ranges, for example 1 4 10-12: ").strip()
    selected = [paths[index - 1] for index in parse_ranges(raw, len(paths))]
    write_selection(config, selected)


def rsync_path_args(paths: list[str], base: str) -> list[str]:
    return [f"{base}/./{path}" for path in paths]


def local_log_command(*lines: str, exit_code: int = 0) -> list[str]:
    script = "".join(f"printf '%s\\n' {shlex.quote(line)}\n" for line in lines)
    script += f"exit {int(exit_code)}\n"
    return ["bash", "-lc", script]


def rsync_mapping_command(
    config: dict[str, Any],
    mapping: dict[str, Any],
    *,
    direction: str,
    dry_run: bool,
    prepare: bool = True,
) -> list[str]:
    local_base = local_project_dir(config)
    remote_base = f"{remote_spec(config)}:{remote_project_dir(config)}"
    local_path = local_base / mapping["local"]
    remote_path = f"{remote_base}/{mapping['remote']}"
    argv = ["rsync", "-az", "--delete"]
    if dry_run:
        argv.extend(["--dry-run", "--itemize-changes"])
    argv.extend(rsync_excludes(config))
    source_suffix = "/" if mapping["kind"] == "directory" else ""
    target_suffix = "/" if mapping["kind"] == "directory" else ""
    if direction == "pull":
        if prepare:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            if mapping["kind"] == "directory":
                local_path.mkdir(parents=True, exist_ok=True)
        argv.extend([remote_path + source_suffix, str(local_path) + target_suffix])
    elif direction == "push":
        if not mapping["push"]:
            if dry_run:
                return local_log_command(
                    f"SKIP push dry-run: {mapping['name']}",
                    "reason: mapping is marked push=false",
                    f"local:  {local_path}",
                    f"remote: {mapping['remote']}",
                )
            raise SystemExit(f"mapping {mapping['name']} is marked push=false")
        if not local_path.exists():
            if dry_run:
                return local_log_command(
                    f"SKIP push dry-run: {mapping['name']}",
                    "reason: local mapping path does not exist",
                    f"local:  {local_path}",
                    f"remote: {mapping['remote']}",
                )
            raise SystemExit(f"local mapping path does not exist: {local_path}")
        argv.extend([str(local_path) + source_suffix, remote_path + target_suffix])
    else:
        raise ValueError(direction)
    return argv


def rsync_mapping(
    config: dict[str, Any],
    mapping: dict[str, Any],
    *,
    direction: str,
    dry_run: bool,
) -> None:
    print(f"\n== {direction}: {mapping['name']} ==")
    print(f"role: {mapping['role']}")
    print(f"remote: {mapping['remote']}")
    print(f"local:  {mapping['local']}")
    run(rsync_mapping_command(config, mapping, direction=direction, dry_run=dry_run))


def cmd_pull(config: dict[str, Any], *, dry_run: bool) -> None:
    paths = read_selection(config)
    local_dir = local_project_dir(config)
    local_dir.mkdir(parents=True, exist_ok=True)
    remote_base = f"{remote_spec(config)}:{remote_project_dir(config)}"
    argv = ["rsync", "-az", "--relative", "--delete"]
    if dry_run:
        argv.extend(["--dry-run", "--itemize-changes"])
    argv.extend(rsync_excludes(config))
    argv.extend(rsync_path_args(paths, remote_base))
    argv.append(str(local_dir) + "/")
    run(argv)


def cmd_push(config: dict[str, Any], *, dry_run: bool) -> None:
    paths = read_selection(config)
    local_dir = local_project_dir(config)
    missing = [path for path in paths if not (local_dir / path).exists()]
    if missing:
        raise SystemExit("local selected paths are missing:\n" + "\n".join(missing))
    remote_base = f"{remote_spec(config)}:{remote_project_dir(config)}/"
    argv = ["rsync", "-az", "--relative", "--delete"]
    if dry_run:
        argv.extend(["--dry-run", "--itemize-changes"])
    argv.extend(rsync_excludes(config))
    argv.extend(rsync_path_args(paths, str(local_dir)))
    argv.append(remote_base)
    run(argv)


def cmd_mappings(config: dict[str, Any]) -> None:
    selected = set(read_mapping_selection_if_exists(config))
    print(f"local overlay: {local_project_dir(config)}")
    print(f"remote project: {remote_spec(config)}:{remote_project_dir(config)}")
    for mapping in mappings(config):
        push = "push" if mapping["push"] else "pull-only"
        mark = "*" if mapping["name"] in selected else " "
        print()
        print(f"{mark} {mapping['name']} [{mapping['kind']}, {push}]")
        print(f"  role:   {mapping['role']}")
        print(f"  remote: {mapping['remote']}")
        print(f"  local:  {mapping['local']}")


def cmd_select_mappings(config: dict[str, Any]) -> None:
    all_mappings = mappings(config)
    selected = set(read_mapping_selection_if_exists(config))
    print(f"local overlay: {local_project_dir(config)}")
    print(f"remote project: {remote_spec(config)}:{remote_project_dir(config)}")
    print()
    print("Mapping areas:")
    for index, mapping in enumerate(all_mappings, 1):
        mark = "*" if mapping["name"] in selected else " "
        print(f"{index:3d}. [{mark}] {mapping['name']}")
        print(f"     {mapping['role']}")
        print(f"     remote: {mapping['remote']}")
        print(f"     local:  {mapping['local']}")
    print()
    print("Input numbers/ranges, for example: 1 3-4")
    print("Input 'all' to select all, 'none' to clear, or Enter to keep current.")
    raw = input("> ").strip().lower()
    if not raw:
        print("mapping selection unchanged")
        return
    if raw == "all":
        names = [mapping["name"] for mapping in all_mappings]
    elif raw in ("none", "clear"):
        names = []
    else:
        indexes = parse_ranges(raw, len(all_mappings))
        names = [all_mappings[index - 1]["name"] for index in indexes]
    write_mapping_selection(config, names)


def cmd_pull_map(config: dict[str, Any], names: list[str], *, dry_run: bool) -> None:
    for mapping in select_mappings(config, names):
        rsync_mapping(config, mapping, direction="pull", dry_run=dry_run)


def cmd_push_map(config: dict[str, Any], names: list[str], *, dry_run: bool) -> None:
    for mapping in select_mappings(config, names):
        rsync_mapping(config, mapping, direction="push", dry_run=dry_run)


def selected_mapping_names(config: dict[str, Any]) -> list[str]:
    return read_mapping_selection(config)


def remote_shell_command(config: dict[str, Any], command: str) -> list[str]:
    if not remote_has_project_dir(config):
        raise SystemExit("Remote project directory is not configured")
    return ["ssh", remote_spec(config), f"cd {shlex.quote(remote_project_dir(config))} && {command}"]


def remote_connect_command(config: dict[str, Any]) -> list[str]:
    check = (
        f"cd {shlex.quote(remote_project_dir(config))} && printf 'ssh=ok\\n'; pwd | sed 's/^/cwd=/'"
        if remote_has_project_dir(config)
        else "printf 'ssh=ok\\n'; pwd | sed 's/^/cwd=/'"
    )
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=5",
        remote_spec(config),
        check,
    ]


def remote_prepare_project_command(config: dict[str, Any]) -> list[str]:
    project_dir = remote_project_dir(config)
    git_url = project_git_url(config)
    git_ref = project_git_ref(config)
    parent = str(Path(project_dir).parent)
    name = Path(project_dir).name
    checkout_ref = f" && cd {shlex.quote(name)} && git checkout {shlex.quote(git_ref)}" if git_ref else ""
    if git_url:
        script = (
            f"if [ -d {shlex.quote(project_dir + '/.git')} ]; then "
            f"cd {shlex.quote(project_dir)} && git remote -v; "
            f"elif [ -e {shlex.quote(project_dir)} ]; then "
            f"printf 'target exists but is not a git checkout: %s\\n' {shlex.quote(project_dir)} >&2; exit 2; "
            f"else mkdir -p {shlex.quote(parent)} && cd {shlex.quote(parent)} && "
            f"git clone {shlex.quote(git_url)} {shlex.quote(name)}{checkout_ref}; fi"
        )
    else:
        script = (
            f"if [ -d {shlex.quote(project_dir + '/.git')} ]; then "
            f"cd {shlex.quote(project_dir)} && git remote -v; "
            "else printf 'project Git URL is required to prepare a missing project checkout\\n' >&2; exit 2; fi"
        )
    return ["ssh", remote_spec(config), script]


def remote_checkout_git_ref_command(config: dict[str, Any]) -> list[str]:
    git_ref = project_git_ref(config)
    if not git_ref:
        raise SystemExit("Git branch/ref is not configured")
    project_dir = shlex.quote(remote_project_dir(config))
    quoted_ref = shlex.quote(git_ref)
    script = (
        f"cd {project_dir} || exit 2; "
        "if [ ! -d .git ]; then printf 'target is not a git checkout\\n' >&2; exit 2; fi; "
        "if [ -n \"$(git status --porcelain --untracked-files=no)\" ]; then "
        "printf 'tracked local changes present; refusing to switch ref\\n' >&2; exit 2; fi; "
        "git fetch origin --prune && "
        f"git checkout {quoted_ref} && "
        "git status --short --branch"
    )
    return ["ssh", remote_spec(config), script]


def remote_status_command(config: dict[str, Any], app: "ClientApp") -> list[str]:
    docker_cmd = (
        "docker image ls " + shlex.quote(f"{app.docker_image}:latest")
        if app.docker_image
        else "printf 'Docker image is not configured\\n'"
    )
    command = app.structured_script(
        [
            ("Project directory", "pwd"),
            ("Disk usage", "df -h ."),
            ("Git status", "git status --short --branch"),
            ("Docker image", docker_cmd),
        ],
        fail_fast=False,
    )
    return remote_shell_command(config, command)


def remote_preflight_command(config: dict[str, Any], app: "ClientApp") -> list[str]:
    if not remote_has_project_dir(config):
        return remote_connect_command(config)
    image = shlex.quote(f"{app.docker_image}:latest") if app.docker_image else ""
    expected_origin = project_git_url(config)
    expected_ref = project_git_ref(config)
    docker_check = (
        f"docker image inspect {image} >/dev/null 2>&1 && printf 'docker=ok\\n' || printf 'docker=missing\\n'; "
        if image
        else "printf 'docker=not-configured\\n'; "
    )
    origin_check = (
        "origin=$(git config --get remote.origin.url 2>/dev/null || true); "
        f"if [ \"$origin\" = {shlex.quote(expected_origin)} ]; then printf 'origin=ok\\n'; "
        "elif [ -n \"$origin\" ]; then printf 'origin=mismatch:%s\\n' \"$origin\"; "
        "else printf 'origin=missing\\n'; fi; "
        if expected_origin
        else "origin=$(git config --get remote.origin.url 2>/dev/null || true); "
        "if [ -n \"$origin\" ]; then printf 'origin=%s\\n' \"$origin\"; else printf 'origin=missing\\n'; fi; "
    )
    ref_check = (
        "current_ref=$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true); "
        "current_head=$(git rev-parse --verify HEAD 2>/dev/null || true); "
        f"if [ \"$current_ref\" = {shlex.quote(expected_ref)} ] || [ \"$current_head\" = {shlex.quote(expected_ref)} ]; then printf 'ref=ok\\n'; "
        "elif [ -n \"$current_ref\" ]; then printf 'ref=mismatch:%s\\n' \"$current_ref\"; "
        "elif [ -n \"$current_head\" ]; then printf 'ref=mismatch:%s\\n' \"$current_head\"; "
        "else printf 'ref=missing\\n'; fi; "
        if expected_ref
        else "current_ref=$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true); "
        "if [ -n \"$current_ref\" ]; then printf 'ref=%s\\n' \"$current_ref\"; "
        "else git rev-parse --short HEAD 2>/dev/null | sed 's/^/ref=/'; fi; "
    )
    project_dir = shlex.quote(remote_project_dir(config))
    script = (
        f"project_dir={project_dir}; "
        "if [ ! -e \"$project_dir\" ]; then printf 'project=missing\\n'; exit 0; fi; "
        "if [ ! -d \"$project_dir\" ]; then printf 'project=not-directory\\n'; exit 0; fi; "
        "cd \"$project_dir\" || { printf 'project=inaccessible\\n'; exit 0; }; "
        "df -h . | awk 'NR==2 {print \"disk=\"$4\" free, \"$5\" used\"}'; "
        + docker_check
        + "if [ -d .git ]; then "
        "printf 'project=ok\\n'; "
        "git status --short --branch | sed -n '1s/^/git=/p'; "
        + origin_check
        + ref_check
        + "else printf 'project=not-git\\n'; printf 'git=not-git\\n'; printf 'origin=missing\\n'; printf 'ref=missing\\n'; fi"
    )
    return ["ssh", remote_spec(config), script]


def remote_docker_command(config: dict[str, Any], app: "ClientApp") -> list[str]:
    if not app.docker_image:
        raise SystemExit("Docker image name is not configured")
    dockerfile = configured_dockerfile(config)
    if not dockerfile:
        raise SystemExit("Dockerfile is not configured")
    dockerfile_path = PurePosixPath(dockerfile)
    context = "." if str(dockerfile_path.parent) == "." else str(dockerfile_path.parent)
    command = (
        f"docker build {shlex.quote(context)} -f {shlex.quote(dockerfile)} "
        '--build-arg "USER_ID=$(id -u)" '
        '--build-arg "USER_GID=$(id -g)" '
        f"-t {shlex.quote(app.docker_image + ':latest')}"
    )
    return remote_shell_command(config, command)


def run_in_product_docker_command(config: dict[str, Any], app: "ClientApp", inner_command: str) -> str:
    workspace = shlex.quote(remote_project_dir(config))
    image = shlex.quote(app.docker_image)
    inner = shlex.quote(f"cd /home/builder/workspace && {inner_command}")
    return (
        "docker run --network=host --privileged --security-opt apparmor=unconfined "
        '-v "$HOME"/.ssh:/home/builder/.ssh '
        '--mount type=bind,source="$HOME"/.gitconfig,target=/home/builder/.gitconfig '
        '--mount type=bind,source="$HOME"/.git-credentials,target=/home/builder/.git-credentials '
        f"-v {workspace}:/home/builder/workspace "
        f"-i --rm {image} /bin/bash -lc {inner}"
    )


def remote_moulin_command(config: dict[str, Any], app: "ClientApp") -> list[str]:
    params = " ".join(
        f"--{shlex.quote(name)} {shlex.quote(value)}"
        for name, value in sorted(app.build_params.items())
    )
    inner = f"moulin {shlex.quote(moulin_manifest_name(config))}" + (f" {params}" if params else "")
    command = run_in_product_docker_command(config, app, inner)
    return remote_shell_command(config, command)


def remote_build_command(config: dict[str, Any], app: "ClientApp") -> list[str]:
    targets = " ".join(shlex.quote(target) for target in shlex.split(app.build_targets))
    command = run_in_product_docker_command(config, app, f"ninja {targets}")
    return remote_shell_command(config, command)


def selected_mapping_commands(
    config: dict[str, Any],
    *,
    direction: str,
    dry_run: bool,
    prepare: bool = True,
) -> list[list[str]]:
    names = selected_mapping_names(config)
    return [
        rsync_mapping_command(config, mapping, direction=direction, dry_run=dry_run, prepare=prepare)
        for mapping in select_mappings(config, names)
    ]


def all_mapping_commands(
    config: dict[str, Any],
    *,
    direction: str,
    dry_run: bool,
    prepare: bool = True,
) -> list[list[str]]:
    return [
        rsync_mapping_command(config, mapping, direction=direction, dry_run=dry_run, prepare=prepare)
        for mapping in select_mappings(config, ["all"])
    ]


@dataclass(frozen=True)
class MenuItem:
    label: str
    group: str
    description: str
    preview: Callable[["ClientApp"], str]
    handler: Callable[["ClientApp"], None]
    confirm: bool = False
    requires_remote: bool = False
    requires_ssh: bool = False
    requires_project: bool = False
    allow_during_job: bool = False


class ClientApp:
    def __init__(self, screen: "curses._CursesWindow", config: dict[str, Any]) -> None:
        self.screen = screen
        self.config = config
        self.docker_image = ""
        self.build_params: dict[str, str] = {}
        self.build_targets = ""
        self.load_active_project_runtime()
        self.connection_state = "disconnected"
        self.auto_connect_done = False
        self.action_running = False
        self.active_job: dict[str, Any] | None = None
        self.last_job: dict[str, Any] | None = None
        self.preflight_values: dict[str, str] = {}
        self.status = "Disconnected"
        self.reset_preflight()
        self.selected = 0
        self.menu_scroll = 0
        self.focus_panel = "actions"
        self.log_scroll = 0
        self.log_follow = True
        self.logs_expanded = False
        self.last_exit: int | None = None
        self.done = False
        self.items = self.build_items()
        self.menu_dirty = True
        self.main_full_redraw = True
        self.render_cache: dict[str, Any] = {}
        self.logs_dirty = True
        self.last_log_render_at = 0.0
        self.mapping_selection_cache: list[str] = []
        self.refresh_mapping_selection_cache()
        self.ui_profile_enabled = os.environ.get("MOULIN_REMOTE_UI_PROFILE", "").strip().lower() in {"1", "yes", "true", "on"}
        self.ui_profile_path = Path(os.environ.get("MOULIN_REMOTE_UI_PROFILE_PATH", str(APP_DIR / "workspace" / "ui-profile.log")))
        self.ui_profile_buffer: list[str] = []
        self.ui_profile_last_flush = time.monotonic()
        if self.ui_profile_enabled:
            self.ui_profile("profile-start", path=str(self.ui_profile_path))

    def load_active_project_runtime(self) -> None:
        settings = load_build_settings(self.config)
        self.docker_image = configured_docker_image(self.config) or str(settings.get("docker_image", ""))
        if os.environ.get("MOULIN_REMOTE_DOCKER_IMAGE"):
            self.docker_image = docker_image()
        self.build_params = default_build_params(self.config)
        self.build_params.update({str(key): str(value) for key, value in settings.get("parameters", {}).items()})
        self.build_targets = str(settings.get("targets", build_targets()))
        if os.environ.get("MOULIN_REMOTE_BUILD_TARGETS"):
            self.build_targets = build_targets()

    def refresh_mapping_selection_cache(self) -> None:
        self.mapping_selection_cache = read_mapping_selection_if_exists(self.config)
        if hasattr(self, "render_cache"):
            self.render_cache.pop("details", None)

    def ui_profile(self, event: str, **fields: Any) -> None:
        if not getattr(self, "ui_profile_enabled", False):
            return
        now = time.monotonic()
        parts = [f"{now:.6f}", event]
        for key, value in fields.items():
            value_text = str(value)
            if any(char.isspace() for char in value_text):
                value_text = repr(value_text)
            parts.append(f"{key}={value_text}")
        self.ui_profile_buffer.append(" ".join(parts))
        if len(self.ui_profile_buffer) >= 50 or now - self.ui_profile_last_flush > 1.0:
            self.flush_ui_profile()

    def ui_profile_slow(self, event: str, started: float, threshold_ms: float = UI_PROFILE_SLOW_MS, **fields: Any) -> float:
        elapsed_ms = (time.monotonic() - started) * 1000.0
        if elapsed_ms >= threshold_ms:
            self.ui_profile(event, ms=f"{elapsed_ms:.1f}", **fields)
        return elapsed_ms

    def flush_ui_profile(self) -> None:
        if not getattr(self, "ui_profile_enabled", False) or not self.ui_profile_buffer:
            return
        try:
            self.ui_profile_path.parent.mkdir(parents=True, exist_ok=True)
            with self.ui_profile_path.open("a", encoding="utf-8") as handle:
                handle.write("\n".join(self.ui_profile_buffer) + "\n")
            self.ui_profile_buffer.clear()
            self.ui_profile_last_flush = time.monotonic()
        except Exception:
                self.ui_profile_enabled = False

    def build_items(self) -> list[MenuItem]:
        items = [
            MenuItem(
                "Remote configurations",
                "setup",
                "Add, delete, select, and edit remote machine profiles before running builds.",
                lambda app: "Open remote profile setup.",
                lambda app: app.remote_configurations_screen(),
                allow_during_job=True,
            ),
            MenuItem(
                "Project configurations",
                "setup",
                "Select and edit project-local build profile settings such as manifest, targets, parameters, Docker image, and local overlay.",
                lambda app: f"Active project: {active_project(app.config).get('label') or active_project(app.config).get('name')}",
                lambda app: app.project_configurations_screen(),
                allow_during_job=True,
            ),
            MenuItem(
                "Connect / disconnect",
                "session",
                "Check SSH access to the configured remote target or mark it disconnected.",
                lambda app: app.connection_preview(),
                lambda app: app.toggle_connection(),
                requires_ssh=True,
                allow_during_job=True,
            ),
            MenuItem(
                "Open remote shell",
                "session",
                "Open SSH shell in the remote product directory; exit returns to this TUI.",
                lambda app: f"ssh -t {remote_spec(app.config)} 'cd {remote_project_dir(app.config)} && exec bash -l'",
                lambda app: app.open_remote_shell(),
                requires_remote=True,
                requires_project=True,
                allow_during_job=True,
            ),
        ]
        if self.prepare_remote_project_needed():
            items.append(
                MenuItem(
                    "Prepare remote project",
                    "commands",
                    "Create or repair the configured target checkout when preflight detects a missing project, non-git directory, or Git origin mismatch.",
                    lambda app: shlex.join(remote_prepare_project_command(app.config)),
                    lambda app: app.run_command("Prepare remote project", remote_prepare_project_command(app.config)),
                    confirm=True,
                    requires_ssh=True,
                    requires_project=True,
                )
            )
        if self.checkout_git_ref_needed():
            items.append(
                MenuItem(
                    "Checkout project Git ref",
                    "commands",
                    "Switch the existing remote checkout to the configured project Git branch/ref when the working tree has no tracked local changes.",
                    lambda app: shlex.join(remote_checkout_git_ref_command(app.config)),
                    lambda app: app.run_command("Checkout project Git ref", remote_checkout_git_ref_command(app.config)),
                    confirm=True,
                    requires_remote=True,
                    requires_project=True,
                )
            )
        items.extend(
            [
            MenuItem(
                "Build Docker image",
                "commands",
                "Rebuild the configured Docker image on the remote target.",
                lambda app: shlex.join(remote_docker_command(app.config, app)),
                lambda app: app.run_build_command("Build Docker image", remote_docker_command(app.config, app)),
                confirm=True,
                requires_remote=True,
                requires_project=True,
            ),
            MenuItem(
                "Regenerate Moulin/Ninja",
                "commands",
                "Run Moulin on the remote target and refresh Ninja files.",
                lambda app: shlex.join(remote_moulin_command(app.config, app)),
                lambda app: app.run_build_command("Regenerate Moulin/Ninja", remote_moulin_command(app.config, app)),
                confirm=True,
                requires_remote=True,
                requires_project=True,
            ),
            MenuItem(
                "Run product build",
                "commands",
                "Run configured Ninja targets on the remote target.",
                lambda app: shlex.join(remote_build_command(app.config, app)),
                lambda app: app.run_build_command("Run product build", remote_build_command(app.config, app)),
                confirm=True,
                requires_remote=True,
                requires_project=True,
            ),
            MenuItem(
                "Stop running command",
                "commands",
                "Gracefully stop the currently running command, then force-kill it if it does not exit.",
                lambda app: app.stop_running_preview(),
                lambda app: app.stop_running_command(),
                allow_during_job=True,
            ),
            MenuItem(
                "Sync mapped files",
                "sync",
                "Pull or push the configured local/remote source mappings used for patch development.",
                lambda app: "Open the sync workflow for configured mappings.",
                lambda app: app.sync_screen(),
                requires_remote=True,
                requires_project=True,
            ),
            ]
        )
        return items

    def sync_menu_items(self) -> None:
        if self.items:
            self.selected = min(max(0, self.selected), len(self.items) - 1)
        selected_label = self.items[self.selected].label if self.items else ""
        self.items = self.build_items()
        if not self.items:
            self.selected = 0
            return
        self.selected = next((index for index, item in enumerate(self.items) if item.label == selected_label), min(self.selected, len(self.items) - 1))
        self.normalize_active_job_selection()

    def prepare_remote_project_needed(self) -> bool:
        values = self.preflight_values
        project = values.get("project", "")
        origin = values.get("origin", "")
        if project in {"missing", "not-git", "not-directory", "inaccessible"}:
            return True
        if origin == "missing" and project_git_url(self.config):
            return True
        return origin.startswith("mismatch:")

    def checkout_git_ref_needed(self) -> bool:
        if not project_git_ref(self.config):
            return False
        ref = self.preflight_values.get("ref", "")
        return ref == "missing" or ref.startswith("mismatch:")

    def reset_preflight(self) -> None:
        self.preflight = "not run"
        self.preflight_values = {}
        if hasattr(self, "menu_dirty"):
            self.menu_dirty = True
        if hasattr(self, "render_cache"):
            self.render_cache.pop("header", None)

    def run(self) -> None:
        self.configure_escape_delay()
        self.set_cursor(False)
        self.screen.keypad(True)
        self.screen.timeout(250)
        if auto_connect_enabled():
            self.auto_connect()
        started = time.monotonic()
        self.draw()
        self.ui_profile_slow("draw-initial", started)
        try:
            while not self.done:
                started = time.monotonic()
                self.poll_active_job()
                self.ui_profile_slow("poll-slow", started)
                input_timeout = 0.05 if self.active_job is not None else 0.25
                self.screen.timeout(max(0, int(input_timeout * 1000)))
                wait_started = time.monotonic()
                ch = self.read_key()
                if ch == -1:
                    self.ui_profile_slow("input-wait-timeout", wait_started, threshold_ms=300.0, active=bool(self.active_job))
                    started = time.monotonic()
                    self.draw()
                    self.ui_profile_slow("draw-idle-slow", started)
                    time.sleep(0.05)
                    continue
                batch_started = time.monotonic()
                key_count = 1
                key_started = time.monotonic()
                self.handle_main_key(ch)
                self.ui_profile_slow("key-handler-slow", key_started, threshold_ms=5.0, key=ch, selected=self.selected, active=bool(self.active_job))
                self.ui_profile_slow("input-batch-slow", batch_started, threshold_ms=10.0, keys=key_count, selected=self.selected, active=bool(self.active_job))
                started = time.monotonic()
                self.draw()
                self.ui_profile_slow("draw-after-input-slow", started)
        finally:
            self.flush_ui_profile()

    def handle_main_key(self, ch: int) -> None:
        self.normalize_active_job_selection()
        if self.logs_expanded:
            if (self.key_matches(ch, "f") or ch == 27):
                self.logs_expanded = False
                self.main_full_redraw = True
                self.render_cache.clear()
            elif ch == curses.KEY_UP or self.key_matches(ch, "k"):
                self.scroll_logs(-1)
            elif ch == curses.KEY_DOWN or self.key_matches(ch, "j"):
                self.scroll_logs(1)
            elif ch in (curses.KEY_PPAGE,):
                self.scroll_logs(-10)
            elif ch in (curses.KEY_NPAGE,):
                self.scroll_logs(10)
            else:
                self.status = "Logs expanded; use f/Esc to return"
            return
        if ch == curses.KEY_LEFT or self.key_matches(ch, "h"):
            self.focus_panel = "actions"
        elif ch == curses.KEY_RIGHT or self.key_matches(ch, "l"):
            self.focus_panel = "logs"
        elif ch == curses.KEY_UP or self.key_matches(ch, "k"):
            if self.focus_panel == "logs":
                self.scroll_logs(-1)
            else:
                self.move_menu_selection(-1)
                self.log_follow = True
        elif ch == curses.KEY_DOWN or self.key_matches(ch, "j"):
            if self.focus_panel == "logs":
                self.scroll_logs(1)
            else:
                self.move_menu_selection(1)
                self.log_follow = True
        elif ch in (curses.KEY_ENTER, 10, 13) or self.key_matches(ch, "r"):
            self.run_selected()
        elif self.key_matches(ch, "f"):
            self.focus_panel = "logs"
            self.logs_expanded = True
            self.main_full_redraw = True
            self.render_cache.clear()
        elif self.key_matches(ch, "s"):
            self.project_configurations_screen()
            self.main_full_redraw = True
            self.menu_dirty = True
        elif self.key_matches(ch, "q"):
            self.quit()
        elif ch == 27:
            if self.active_job is not None:
                self.status = "Command is running; use q after it finishes or open the command screen to stop it"
            else:
                if self.confirm_exit():
                    self.quit()
        else:
            self.status = f"Unknown key: {chr(ch)!r}" if 0 <= ch < 256 else f"Unknown key: {ch}"

    def move_menu_selection(self, delta: int) -> None:
        if not self.items:
            self.selected = 0
            return
        if self.active_job is None:
            self.selected = (self.selected + delta) % len(self.items)
            return
        indices = self.active_job_menu_indices()
        if not indices:
            return
        if self.selected not in indices:
            self.selected = indices[0]
            return
        current = indices.index(self.selected)
        self.selected = indices[(current + delta) % len(indices)]

    def active_job_menu_indices(self) -> list[int]:
        if self.active_job is None:
            return list(range(len(self.items)))
        active_label = str(self.active_job.get("item_label", ""))
        result: list[int] = []
        for index, item in enumerate(self.items):
            if item.label == active_label or item.allow_during_job:
                result.append(index)
        return result

    def normalize_active_job_selection(self) -> None:
        if self.active_job is None or not self.items:
            return
        indices = self.active_job_menu_indices()
        if self.selected in indices:
            return
        active_label = str(self.active_job.get("item_label", ""))
        self.selected = next(
            (index for index in indices if self.items[index].label == active_label),
            indices[0] if indices else min(self.selected, len(self.items) - 1),
        )

    def setup_colors(self) -> None:
        if not curses.has_colors():
            return
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(2, curses.COLOR_CYAN, -1)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)
        curses.init_pair(4, curses.COLOR_GREEN, -1)
        curses.init_pair(5, curses.COLOR_RED, -1)
        curses.init_pair(6, curses.COLOR_WHITE, curses.COLOR_BLUE)
        curses.init_pair(7, curses.COLOR_GREEN, -1)
        curses.init_pair(8, curses.COLOR_BLACK, curses.COLOR_GREEN)

    def configure_escape_delay(self) -> None:
        try:
            curses.set_escdelay(100)
        except (AttributeError, curses.error):
            pass

    def set_cursor(self, visible: bool) -> None:
        try:
            curses.curs_set(1 if visible else 0)
        except curses.error:
            pass

    def read_key(self) -> int:
        try:
            ch = self.screen.get_wch()
        except curses.error:
            return -1
        except AttributeError:
            return self.screen.getch()
        if isinstance(ch, str):
            if not ch:
                return -1
            code = ord(ch)
            if code >= 256 and ch.isprintable():
                return TEXT_KEY_OFFSET + code
            return code
        return int(ch)

    def key_text(self, ch: int) -> str:
        encoded_text_key = ch >= TEXT_KEY_OFFSET
        if ch >= TEXT_KEY_OFFSET:
            ch -= TEXT_KEY_OFFSET
        if ch < 0 or ch > sys.maxunicode:
            return ""
        if not encoded_text_key and curses.KEY_MIN <= ch <= curses.KEY_MAX:
            return ""
        try:
            text = chr(ch)
        except (OverflowError, ValueError):
            return ""
        if not text.isprintable():
            return ""
        return text

    def key_matches(self, ch: int, *keys: str) -> bool:
        text = self.key_text(ch).casefold()
        if not text:
            return False
        for key in keys:
            aliases = KEY_ALIASES.get(key.casefold(), (key,))
            if text in {alias.casefold() for alias in aliases}:
                return True
        return False

    def selected_attr(self) -> int:
        if curses.has_colors():
            return curses.color_pair(1) | curses.A_BOLD
        return curses.A_REVERSE | curses.A_BOLD

    def selected_disabled_attr(self) -> int:
        if curses.has_colors():
            return curses.color_pair(1) | curses.A_DIM
        return curses.A_REVERSE | curses.A_DIM

    def active_row_attr(self) -> int:
        if curses.has_colors():
            return curses.color_pair(7) | curses.A_BOLD
        return curses.A_REVERSE | curses.A_BOLD

    def selected_active_attr(self) -> int:
        if curses.has_colors():
            return curses.color_pair(8) | curses.A_BOLD
        return curses.A_REVERSE | curses.A_BOLD

    def editing_attr(self) -> int:
        if curses.has_colors():
            return curses.color_pair(6) | curses.A_BOLD
        return curses.A_REVERSE | curses.A_BOLD

    def accent_attr(self) -> int:
        return curses.color_pair(2) | curses.A_BOLD if curses.has_colors() else curses.A_BOLD

    def warn_attr(self) -> int:
        return curses.color_pair(3) | curses.A_BOLD if curses.has_colors() else curses.A_BOLD

    def running_attr(self) -> int:
        return self.warn_attr()

    def group_attr(self) -> int:
        return curses.color_pair(4) | curses.A_BOLD if curses.has_colors() else curses.A_BOLD

    def disabled_attr(self) -> int:
        return curses.A_DIM

    def ok_attr(self) -> int:
        return self.group_attr()

    def error_attr(self) -> int:
        if curses.has_colors():
            return curses.color_pair(5) | curses.A_BOLD
        return curses.A_BOLD

    def item_enabled(self, item: MenuItem) -> bool:
        if item.label == "Stop running command" and self.active_job is None:
            return False
        if self.active_job is not None:
            if item.label == self.active_job.get("item_label"):
                return True
            return item.allow_during_job and (self.connected or not item.requires_remote)
        if item.requires_ssh and not remote_has_ssh(self.config):
            return False
        if item.requires_remote and not self.connected:
            return False
        if item.requires_project and not remote_has_project_dir(self.config):
            return False
        if item.label != "Prepare remote project" and item.requires_project and self.prepare_remote_project_needed():
            return False
        if item.label != "Checkout project Git ref" and item.requires_project and self.checkout_git_ref_needed():
            return False
        return True

    def disabled_reason(self, item: MenuItem) -> str:
        if item.label == "Stop running command" and self.active_job is None:
            return "no command is running"
        if item.requires_ssh and not remote_has_user(self.config):
            return "set SSH user first"
        if item.requires_ssh and not remote_has_host(self.config):
            return "set SSH host first"
        if item.requires_remote and not self.connected:
            return "connect to the remote target first"
        if item.requires_project and not remote_has_project_dir(self.config):
            return "select remote project directory first"
        if item.label != "Prepare remote project" and item.requires_project and self.prepare_remote_project_needed():
            return "remote project needs preparation"
        if item.label != "Checkout project Git ref" and item.requires_project and self.checkout_git_ref_needed():
            return "remote project Git ref mismatch"
        if self.active_job is not None:
            return "blocked by active command"
        return "disabled"

    @property
    def connected(self) -> bool:
        return self.connection_state == "connected"

    def connection_label(self) -> str:
        labels = {
            "connected": "Disconnect",
            "connecting": "Connecting...",
            "disconnecting": "Disconnecting...",
            "disconnected": "Connect",
        }
        return labels.get(self.connection_state, "Connect")

    def connection_preview(self) -> str:
        if self.connection_state == "connected":
            return "disconnect from Moulin client remote session"
        if self.connection_state == "connecting":
            return "checking SSH access to the remote target"
        if self.connection_state == "disconnecting":
            return "clearing local connection state"
        return shlex.join(remote_connect_command(self.config))

    def add(self, y: int, x: int, text: str, attr: int = 0) -> None:
        try:
            self.screen.addstr(y, x, text, attr)
        except curses.error:
            pass

    def add_segments(self, y: int, x: int, max_width: int, segments: list[tuple[str, int]]) -> None:
        remaining = max_width
        pos = x
        for text, attr in segments:
            if remaining <= 0:
                return
            chunk = text[:remaining]
            self.add(y, pos, chunk, attr)
            pos += len(chunk)
            remaining -= len(chunk)

    def fit_text(self, text: str, width: int) -> str:
        if width <= 0:
            return ""
        if len(text) <= width:
            return text
        if width <= 3:
            return text[:width]
        left = max(1, (width - 3) // 2)
        right = max(1, width - 3 - left)
        return f"{text[:left]}...{text[-right:]}"

    def draw_box(self, top: int, left: int, height: int, width: int, title: str = "", attr: int = 0) -> None:
        if height < 2 or width < 2:
            return
        horizontal = "-" * max(0, width - 2)
        self.add(top, left, "+" + horizontal + "+", attr)
        for row in range(top + 1, top + height - 1):
            self.add(row, left, "|", attr)
            self.add(row, left + 1, " " * max(0, width - 2))
            self.add(row, left + width - 1, "|", attr)
        self.add(top + height - 1, left, "+" + horizontal + "+", attr)
        if title:
            self.add(top, left + 2, f" {title} "[: max(0, width - 4)], attr or self.accent_attr())

    def connection_attr(self) -> int:
        if self.connection_state == "connected":
            return self.group_attr()
        if self.connection_state in {"connecting", "disconnecting"}:
            return self.warn_attr()
        return self.disabled_attr()

    def draw_header(self, width: int) -> None:
        self.draw_box(0, 0, 9, width, ui_title(self.config))
        inner_width = max(1, width - 4)
        label_width = 14
        entries = [
            ("Remote", f"{remote_label(self.config)}  {remote_spec(self.config)}:{remote_project_dir(self.config)}"),
            ("Local overlay", str(local_project_dir(self.config))),
            ("Manifest", moulin_manifest_name(self.config)),
        ]
        for offset, (label, value) in enumerate(entries, start=1):
            self.add(offset, 2, f"{label}:".ljust(label_width), self.accent_attr())
            self.add(offset, 2 + label_width, self.fit_text(value, inner_width - label_width))

        row = 4
        x = 2
        self.add(row, x, "Connection:", self.accent_attr())
        x += len("Connection: ")
        state = self.connection_state
        self.add(row, x, state, self.connection_attr())
        x += len(state) + 4
        self.add_segments(row, x, width - x - 2, self.build_param_segments() + [("   Docker image: ", 0), (self.docker_image, self.accent_attr())])
        self.add(5, 2, "Targets:".ljust(label_width), self.accent_attr())
        self.add(5, 2 + label_width, self.fit_text(self.build_targets, inner_width - label_width))
        self.add_segments(6, 2, inner_width, [("Preflight: ", self.accent_attr())] + self.preflight_segments())
        self.add(7, 2, "Mappings:".ljust(label_width), self.accent_attr())
        self.add(7, 2 + label_width, self.fit_text(self.mapping_status_text(), inner_width - label_width), self.mapping_status_attr())

    def build_param_segments(self) -> list[tuple[str, int]]:
        segments: list[tuple[str, int]] = [("Params: ", self.accent_attr())]
        for index, (name, value) in enumerate(sorted(self.build_params.items())):
            if index:
                segments.append(("  ", 0))
            segments.append((f"{name.removeprefix('ENABLE_')}=", 0))
            segments.append((value, self.ok_attr() if value == "yes" else self.warn_attr()))
        return segments

    def preflight_segments(self) -> list[tuple[str, int]]:
        if not self.preflight:
            return [("not run", self.disabled_attr())]
        if not self.connected:
            return [(self.preflight, self.disabled_attr())]
        segments: list[tuple[str, int]] = []
        for index, part in enumerate(self.preflight.split(" | ")):
            if index:
                segments.append((" | ", 0))
            attr = self.ok_attr() if self.preflight_part_ok(part) else self.error_attr()
            segments.append((part, attr))
        return segments

    def preflight_part_ok(self, part: str) -> bool:
        lowered = part.lower()
        if any(token in lowered for token in ("fail", "missing", "timeout", "failed", "mismatch", "?")):
            return False
        return "ok" in lowered or part.startswith("cwd ") or part.startswith("disk ") or part.startswith("git ##") or part.startswith("origin ")

    def active_mappings(self) -> tuple[list[str], list[dict[str, Any]], str | None]:
        names = read_mapping_selection_if_exists(self.config)
        if not names:
            return names, [], None
        try:
            return names, select_mappings(self.config, names), None
        except SystemExit as exc:
            return names, [], str(exc)

    def local_mapping_issue(self, mapping: dict[str, Any]) -> str | None:
        local_path = local_project_dir(self.config) / mapping["local"]
        if not local_path.exists():
            return f"{mapping['name']}: local path missing: {local_path}"
        if mapping["kind"] == "directory":
            if not local_path.is_dir():
                return f"{mapping['name']}: local path is not a directory: {local_path}"
            try:
                if not any(local_path.iterdir()):
                    return f"{mapping['name']}: local directory is empty: {local_path}"
            except OSError as exc:
                return f"{mapping['name']}: cannot inspect local directory: {exc}"
        elif not local_path.is_file():
            return f"{mapping['name']}: local path is not a file: {local_path}"
        return None

    def local_mapping_issues(self, active_mappings: list[dict[str, Any]]) -> list[str]:
        return [
            issue
            for mapping in active_mappings
            for issue in [self.local_mapping_issue(mapping)]
            if issue is not None
        ]

    def mapping_status_text(self) -> str:
        names, active_mappings, error = self.active_mappings()
        if not names:
            return "0 active | pre-build push no"
        if error is not None:
            return f"{len(names)} selected | invalid selection"
        issues = self.local_mapping_issues(active_mappings)
        if issues:
            return f"{len(active_mappings)} active | needs pull before build"
        return f"{len(active_mappings)} active | pre-build push yes"

    def mapping_status_attr(self) -> int:
        names, active_mappings, error = self.active_mappings()
        if not names:
            return self.disabled_attr()
        if error is not None or self.local_mapping_issues(active_mappings):
            return self.warn_attr()
        return self.ok_attr()

    def draw_wrapped(self, y: int, x: int, width: int, text: str, attr: int = 0, max_lines: int = 4) -> int:
        words = text.split()
        line = ""
        lines: list[str] = []
        for word in words:
            candidate = word if not line else f"{line} {word}"
            if len(candidate) > width and line:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            lines.append(line)
        row = y
        for line in lines[:max_lines]:
            self.add(row, x, line[:width], attr)
            row += 1
        return row

    def draw_scrollbar(self, top: int, left: int, height: int, total: int, visible: int, scroll: int) -> None:
        if height <= 0 or total <= visible:
            return
        thumb_height = max(1, int(height * visible / max(total, 1)))
        thumb_top = top + int((height - thumb_height) * scroll / max(total - visible, 1))
        for row in range(top, top + height):
            attr = self.accent_attr() if thumb_top <= row < thumb_top + thumb_height else self.disabled_attr()
            self.add(row, left, "#" if thumb_top <= row < thumb_top + thumb_height else "|", attr)

    def draw_label_value_wrapped(self, row: int, x: int, width: int, label: str, value: str, *, max_lines: int = 3) -> int:
        label_text = f"{label}:"
        label_width = min(14, max(8, len(label_text) + 1))
        self.add(row, x, label_text.ljust(label_width)[:width], self.accent_attr())
        value_x = x + label_width
        value_width = max(1, width - label_width)
        return self.draw_wrapped(row, value_x, value_width, value or "<not set>", max_lines=max_lines)

    def active_job_running(self) -> bool:
        return self.job_running(self.active_job)

    def job_running(self, job: dict[str, Any] | None) -> bool:
        if job is None:
            return False
        process = job.get("process")
        return process is not None and process.poll() is None

    def log_max_scroll(self, job: dict[str, Any] | None, visible: int) -> int:
        if job is None:
            return 0
        return max(0, len(self.job_output_lines(job)) - max(1, visible))

    def clamp_log_scroll(self, job: dict[str, Any] | None, visible: int) -> int:
        max_scroll = self.log_max_scroll(job, visible)
        if self.log_follow:
            self.log_scroll = max_scroll
        else:
            self.log_scroll = min(max(0, self.log_scroll), max_scroll)
        return self.log_scroll

    def job_output_lines(self, job: dict[str, Any] | None) -> list[str]:
        if job is None:
            return []
        lock = job.get("output_lock")
        if hasattr(lock, "__enter__") and hasattr(lock, "__exit__"):
            with lock:
                return list(job.get("output", []))
        return list(job.get("output", []))

    def display_job_for_item(self, item: MenuItem) -> dict[str, Any] | None:
        if self.active_job is not None and item.label == self.active_job.get("item_label"):
            return self.active_job
        if self.last_job is not None and item.label == self.last_job.get("item_label"):
            return self.last_job
        return None

    def scroll_logs(self, delta: int) -> None:
        item = self.items[self.selected]
        job = self.display_job_for_item(item)
        if job is None:
            self.status = "No log for selected action"
            return
        visible = self.last_log_visible_lines()
        max_scroll = self.log_max_scroll(job, visible)
        current = self.clamp_log_scroll(job, visible)
        if delta < 0:
            self.log_follow = False
            self.log_scroll = max(0, current + delta)
        else:
            next_scroll = min(max_scroll, current + delta)
            self.log_scroll = next_scroll
            self.log_follow = next_scroll >= max_scroll

    def last_log_visible_lines(self) -> int:
        height, _ = self.screen.getmaxyx()
        if self.logs_expanded:
            return max(1, height - 6)
        panel_top = 10
        panel_height = height - 12
        details_height = max(8, panel_height // 2)
        logs_height = max(5, panel_height - details_height - 1)
        return max(1, logs_height - 6)

    def draw_details_panel(self, top: int, left: int, height: int, width: int, item: MenuItem) -> None:
        self.draw_box(top, left, height, width, "Details")
        x = left + 2
        inner = width - 4
        row = top + 2
        self.add(row, x, self.menu_label(item)[:inner], curses.A_BOLD)
        row += 2
        row = self.draw_wrapped(row, x, inner, item.description, max_lines=3)
        row += 1

        if self.active_job is not None and item.label == self.active_job.get("item_label"):
            state = "RUNNING" if self.active_job_running() else "DONE"
            self.add(row, x, f"Status: {state}", self.running_attr() if state == "RUNNING" else self.group_attr())
            row += 1
        elif not self.item_enabled(item):
            self.add(row, x, f"Status: {self.disabled_reason(item)}"[:inner], self.disabled_attr())
            row += 1

        selection = ", ".join(self.mapping_selection_cache) or "none"
        if row < top + height - 3:
            self.add(row, x, f"Selected mappings: {selection}"[:inner])
            row += 1
        if item.label in {"Build Docker image", "Regenerate Moulin/Ninja", "Run product build"} and row < top + height - 2:
            self.add(row, x, f"Pre-build sync: {self.mapping_status_text()}"[:inner], self.mapping_status_attr())
            row += 1
        if row < top + height - 2:
            last = "none" if self.last_exit is None else str(self.last_exit)
            self.add(row, x, f"Last exit: {last}"[:inner])

    def draw_logs_panel(self, top: int, left: int, height: int, width: int, item: MenuItem) -> None:
        border_attr = self.accent_attr() if self.focus_panel == "logs" else 0
        self.draw_box(top, left, height, width, "Logs", border_attr)
        x = left + 2
        inner = width - 4
        row = top + 2
        job = self.display_job_for_item(item)
        if job is None:
            self.add(row, x, "No command log for this action yet."[:inner], self.disabled_attr())
            return

        state = "RUNNING" if self.job_running(job) else "DONE"
        self.add(row, x, f"{job.get('title', 'Command')} [{state}]"[:inner], self.running_attr() if state == "RUNNING" else self.group_attr())
        row += 2
        visible = max(1, top + height - 2 - row)
        output = self.job_output_lines(job)
        if not output:
            self.add(row, x, "Waiting for output..."[:inner], self.disabled_attr())
            return
        scroll = self.clamp_log_scroll(job, visible)
        shown = output[scroll : scroll + visible]
        first = min(len(output), scroll + 1)
        last = min(len(output), scroll + len(shown))
        follow = " follow" if self.log_follow else ""
        counter = f"lines {first}-{last}/{len(output)}{follow}"
        self.add(top, max(left + 2, left + width - len(counter) - 2), counter[: max(0, width - 4)], self.accent_attr())
        for line in shown:
            self.add(row, x, line[:inner])
            row += 1

    def draw_expanded_logs(self, height: int, width: int, item: MenuItem) -> None:
        self.screen.erase()
        self.draw_logs_panel(0, 0, max(3, height - 2), width, item)
        footer = "Logs full | Up/Down/PgUp/PgDn scroll | f/Esc shrink"
        self.add(height - 2, 0, footer[:width].ljust(width), self.accent_attr())
        self.add(height - 1, 0, self.status[:width].ljust(width), curses.A_REVERSE)

    def draw(self) -> None:
        draw_started = time.monotonic()
        rendered: list[str] = []
        self.setup_colors()
        height, width = self.screen.getmaxyx()
        if height < 20 or width < 80:
            self.screen.erase()
            self.add(0, 0, "Terminal is too small. Need at least 80x20.", self.warn_attr())
            self.screen.refresh()
            self.main_full_redraw = True
            self.ui_profile_slow("draw-small-terminal", draw_started)
            return

        left_width = min(46, max(34, width // 3))
        right_left = left_width + 1
        right_width = width - right_left
        panel_top = 10
        panel_height = height - 12
        menu_visible_rows = max(1, panel_height - 2)
        details_height = max(8, panel_height // 2)
        logs_height = max(5, panel_height - details_height - 1)
        logs_top = panel_top + details_height + 1
        layout = (height, width, left_width, right_left, right_width, panel_top, panel_height, details_height, logs_height, logs_top)
        if self.render_cache.get("layout") != layout:
            self.screen.erase()
            self.render_cache.clear()
            self.render_cache["layout"] = layout
            self.main_full_redraw = True
        for row in range(panel_top, panel_top + panel_height):
            self.add(row, left_width, " ")

        if self.menu_dirty:
            self.sync_menu_items()
            self.menu_dirty = False
            self.render_cache.pop("actions", None)
            self.render_cache.pop("details", None)
            self.render_cache.pop("logs", None)

        menu_rows: list[tuple[str, int | None]] = []
        last_group = ""
        for index, item in enumerate(self.items):
            if item.group != last_group:
                if last_group:
                    menu_rows.append(("", None))
                menu_rows.append((item.group.upper(), None))
                last_group = item.group
            menu_rows.append((f"{index + 1}. {self.menu_label(item)}", index))

        selected_row = next((row for row, (_, item_index) in enumerate(menu_rows) if item_index == self.selected), 0)
        if selected_row < self.menu_scroll:
            self.menu_scroll = selected_row
        elif selected_row >= self.menu_scroll + menu_visible_rows:
            self.menu_scroll = selected_row - menu_visible_rows + 1

        item = self.items[self.selected] if self.items else MenuItem("", "", "", lambda app: "", lambda app: None)
        active_label = str(self.active_job.get("item_label", "")) if self.active_job is not None else ""
        item_labels = tuple(item.label for item in self.items)
        item_enabled = tuple(self.item_enabled(item) for item in self.items)
        selection = tuple(self.mapping_selection_cache)

        if self.logs_expanded:
            expanded_sig = (
                height,
                width,
                self.selected,
                item.label,
                self.focus_panel,
                self.log_scroll,
                self.log_follow,
                self.status,
            )
            job = self.display_job_for_item(item)
            job_output = tuple(self.job_output_lines(job)[-20:]) if job is not None else ()
            expanded_sig += (
                job.get("title", "") if job is not None else "",
                self.job_running(job),
                len(self.job_output_lines(job)) if job is not None else 0,
                job_output,
            )
            started = time.monotonic()
            self.draw_expanded_logs(height, width, item)
            self.render_cache["expanded_logs"] = expanded_sig
            self.last_log_render_at = time.monotonic()
            self.logs_dirty = False
            self.ui_profile_slow("panel-expanded-logs-slow", started, threshold_ms=5.0, item=item.label)
            self.main_full_redraw = False
            refresh_started = time.monotonic()
            self.screen.refresh()
            self.ui_profile_slow("refresh-slow", refresh_started, threshold_ms=5.0)
            self.ui_profile_slow("draw-slow", draw_started, rendered="expanded-logs", active=bool(self.active_job), selected=self.selected)
            return

        header_sig = (
            width,
            remote_label(self.config),
            remote_spec(self.config),
            remote_project_dir(self.config),
            str(local_project_dir(self.config)),
            moulin_manifest_name(self.config),
            self.connection_state,
            tuple(sorted(self.build_params.items())),
            self.docker_image,
            self.build_targets,
            self.preflight,
            self.mapping_status_text(),
        )
        if self.main_full_redraw or self.render_cache.get("header") != header_sig:
            started = time.monotonic()
            self.draw_header(width)
            self.ui_profile_slow("panel-header-slow", started, threshold_ms=5.0)
            self.render_cache["header"] = header_sig
            rendered.append("header")

        actions_sig = (
            left_width,
            panel_height,
            self.selected,
            self.menu_scroll,
            self.focus_panel,
            active_label,
            item_labels,
            item_enabled,
        )
        if self.main_full_redraw or self.render_cache.get("actions") != actions_sig:
            started = time.monotonic()
            actions_attr = self.accent_attr() if self.focus_panel == "actions" else 0
            self.draw_box(panel_top, 0, panel_height, left_width, "Actions", actions_attr)
            row = panel_top + 1
            for label, item_index in menu_rows[self.menu_scroll : self.menu_scroll + menu_visible_rows]:
                if item_index is None:
                    attr = self.group_attr() if label else 0
                else:
                    menu_item = self.items[item_index]
                    if self.active_job is not None and menu_item.label == self.active_job.get("item_label"):
                        attr = self.running_attr()
                        if item_index == self.selected:
                            attr |= curses.A_REVERSE
                    elif item_index == self.selected:
                        attr = self.selected_attr()
                    elif not self.item_enabled(menu_item):
                        attr = self.disabled_attr()
                    else:
                        attr = 0
                self.add(row, 2, label[: left_width - 4].ljust(left_width - 4), attr)
                row += 1
            self.render_cache["actions"] = actions_sig
            self.ui_profile_slow("panel-actions-slow", started, threshold_ms=5.0, rows=len(menu_rows))
            rendered.append("actions")

        details_sig = (
            right_width,
            details_height,
            self.selected,
            item.label,
            item.description,
            active_label,
            self.active_job_running(),
            self.last_exit,
            selection,
            self.mapping_status_text(),
            self.item_enabled(item),
            self.disabled_reason(item) if not self.item_enabled(item) else "",
        )
        if self.main_full_redraw or self.render_cache.get("details") != details_sig:
            started = time.monotonic()
            self.draw_details_panel(panel_top, right_left, details_height, right_width, item)
            self.render_cache["details"] = details_sig
            self.ui_profile_slow("panel-details-slow", started, threshold_ms=5.0, item=item.label)
            rendered.append("details")

        now = time.monotonic()
        job = self.display_job_for_item(item)
        job_output = tuple(self.job_output_lines(job)[-5:]) if job is not None else ()
        logs_sig = (
            right_width,
            logs_height,
            self.focus_panel,
            item.label,
            active_label,
            job.get("title", "") if job is not None else "",
            self.job_running(job),
            len(self.job_output_lines(job)) if job is not None else 0,
            job_output,
            self.log_scroll,
            self.log_follow,
        )
        should_draw_logs = self.main_full_redraw or self.render_cache.get("logs") != logs_sig
        if self.active_job is not None and self.logs_dirty and now - self.last_log_render_at < 0.15 and self.render_cache.get("logs") is not None:
            should_draw_logs = False
        if should_draw_logs:
            started = time.monotonic()
            self.draw_logs_panel(logs_top, right_left, logs_height, right_width, item)
            self.render_cache["logs"] = logs_sig
            self.last_log_render_at = now
            self.logs_dirty = False
            self.ui_profile_slow("panel-logs-slow", started, threshold_ms=5.0, item=item.label, lines=len(self.job_output_lines(job)) if job is not None else 0)
            rendered.append("logs")

        if self.active_job is not None and self.focus_panel == "logs":
            footer = "Running | Left actions | Up/Down logs | f full | s settings | q quit"
        elif self.active_job is not None:
            footer = "Running | Right logs | f full | Up/Down actions | s settings | q quit"
        else:
            footer = "Left/Right panel | Up/Down select/scroll | f full logs | Enter/r run | s settings | q quit | Esc exit"
        footer_sig = (width, footer, self.status)
        if self.main_full_redraw or self.render_cache.get("footer") != footer_sig:
            started = time.monotonic()
            self.add(height - 2, 0, footer[:width].ljust(width), self.accent_attr())
            self.add(height - 1, 0, self.status[:width].ljust(width), curses.A_REVERSE)
            self.render_cache["footer"] = footer_sig
            self.ui_profile_slow("panel-footer-slow", started, threshold_ms=5.0)
            rendered.append("footer")
        self.main_full_redraw = False
        refresh_started = time.monotonic()
        self.screen.refresh()
        self.ui_profile_slow("refresh-slow", refresh_started, threshold_ms=5.0)
        self.ui_profile_slow("draw-slow", draw_started, rendered=",".join(rendered) or "none", active=bool(self.active_job), selected=self.selected)

    def run_selected(self) -> None:
        item = self.items[self.selected]
        if self.action_running:
            self.status = "Another action is already running"
            return
        if self.active_job is not None:
            if item.label == self.active_job.get("item_label"):
                self.status = "Command is already running; live log is shown in Logs"
                return
            elif item.allow_during_job and self.item_enabled(item):
                pass
            else:
                self.status = "Another command is already running"
                return
        if not self.item_enabled(item):
            self.status = self.disabled_reason(item)
            return
        if item.confirm and not self.confirm_action(item):
            self.status = f"Cancelled: {item.label}"
            return
        try:
            item.handler(self)
        except SystemExit as exc:
            self.status = f"{item.label}: failed"
            self.show_message("Action failed", [str(exc)])
        except Exception as exc:
            self.status = f"{item.label}: failed"
            self.show_message("Action failed", [str(exc)])
        finally:
            self.refresh_mapping_selection_cache()
            self.menu_dirty = True
            self.main_full_redraw = True
            self.logs_dirty = True

    def menu_label(self, item: MenuItem) -> str:
        if item.label == "Connect / disconnect":
            return self.connection_label()
        return item.label

    def toggle_connection(self) -> None:
        if self.action_running:
            self.status = "Another action is already running"
            return
        if self.active_job is not None and not self.connected:
            self.status = "Another command is already running"
            return
        if not remote_has_user(self.config):
            self.status = "set SSH user first"
            return
        if not remote_has_host(self.config):
            self.status = "set SSH host first"
            return
        if self.connected:
            if not self.confirm_disconnect():
                self.status = "Cancelled: Disconnect"
                return
            self.action_running = True
            try:
                self.connection_state = "disconnecting"
                self.status = "Disconnecting..."
                self.draw()
                self.connection_state = "disconnected"
                self.status = "Disconnected"
            finally:
                self.action_running = False
            return
        self.start_connect_job()

    def auto_connect(self) -> None:
        if self.auto_connect_done:
            return
        self.auto_connect_done = True
        if not remote_has_ssh(self.config):
            self.status = "Remote SSH user/host are not configured"
            return
        self.start_connect_job()

    def start_connect_job(self) -> None:
        if self.action_running or self.active_job is not None:
            self.status = "Another action is already running"
            return
        item = next((menu_item for menu_item in self.items if menu_item.label == "Connect / disconnect"), self.items[0])
        self.connection_state = "connecting"
        self.preflight = "checking..."
        self.status = "Connecting..."
        command = remote_preflight_command(self.config, self)
        self.active_job = {
            "kind": "connect",
            "title": "Connect to remote target",
            "item_label": item.label,
            "commands": [command],
            "index": 0,
            "output": deque(["Starting remote preflight..."], maxlen=1000),
            "output_lock": threading.Lock(),
            "process": None,
            "current_command": "",
            "rc": None,
            "started_at": time.monotonic(),
            "timeout": 10.0,
        }
        self.start_next_active_job_command()
        self.focus_panel = "actions"
        self.menu_dirty = True
        self.main_full_redraw = True
        self.logs_dirty = True

    def check_connection_quiet(self) -> int:
        try:
            result = subprocess.run(
                remote_preflight_command(self.config, self),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self.preflight = "timeout"
            self.preflight_values = {}
            return 124
        self.preflight = self.format_preflight(result.stdout)
        return result.returncode

    def parse_preflight_values(self, output: str) -> dict[str, str]:
        values: dict[str, str] = {}
        for line in output.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
        return values

    def format_preflight(self, output: str) -> str:
        values = self.parse_preflight_values(output)
        self.preflight_values = values
        if not values:
            return "failed"
        if "ssh" in values and "project" not in values:
            parts = [f"ssh {values.get('ssh', '?')}"]
            if values.get("cwd"):
                parts.append(f"cwd {values['cwd']}")
            return " | ".join(parts)
        parts = [
            f"project {values.get('project', '?')}",
            f"disk {values.get('disk', '?')}",
            f"git {values.get('git', '?')}",
            f"docker {values.get('docker', '?')}",
            f"origin {values.get('origin', '?')}",
            f"ref {values.get('ref', '?')}",
        ]
        return " | ".join(parts)

    def confirm_action(self, item: MenuItem) -> bool:
        self.screen.timeout(-1)
        self.draw_confirm(
            "Confirm",
            "This action can change local or remote build state.",
            item.label,
            item.description,
            "Enter/y: run | n/q/Esc: cancel",
        )
        while True:
            ch = self.read_key()
            if (self.key_matches(ch, "y") or ch in (10, 13)):
                self.screen.timeout(250)
                return True
            if (self.key_matches(ch, "n", "q") or ch in (27, 3)):
                self.screen.timeout(250)
                return False

    def confirm_exit(self) -> bool:
        self.screen.timeout(-1)
        self.draw_confirm(
            "Exit",
            "Leave the Moulin client?",
            "No remote process is stopped by exiting the menu.",
            "If a command was started from this screen, it is stopped only from its command screen.",
            "Enter/y: exit | n/q/Esc: stay",
        )
        while True:
            ch = self.read_key()
            if (self.key_matches(ch, "y") or ch in (10, 13)):
                self.screen.timeout(250)
                return True
            if (self.key_matches(ch, "n", "q") or ch in (27, 3)):
                self.screen.timeout(250)
                return False

    def confirm_disconnect(self) -> bool:
        self.screen.timeout(-1)
        self.draw_confirm(
            "Disconnect",
            "Disconnect the active remote profile?",
            f"{remote_label(self.config)}  {remote_spec(self.config)}",
            "Running commands are not stopped by disconnect. Use Stop running command first if needed.",
            "Enter/y: disconnect | n/q/Esc: cancel",
        )
        while True:
            ch = self.read_key()
            if (self.key_matches(ch, "y") or ch in (10, 13)):
                self.screen.timeout(250)
                return True
            if (self.key_matches(ch, "n", "q") or ch in (27, 3)):
                self.screen.timeout(250)
                return False

    def draw_confirm(
        self,
        title: str,
        warning: str,
        subject: str,
        details: str,
        footer: str,
        *,
        redraw_background: bool = True,
    ) -> None:
        height, width = self.screen.getmaxyx()
        box_width = min(max(64, width // 2), width - 4)
        box_height = 10
        top = max(1, (height - box_height) // 2)
        left = max(1, (width - box_width) // 2)
        if redraw_background:
            self.draw()
        self.draw_box(top, left, box_height, box_width, title)
        x = left + 2
        y = top + 2
        inner = box_width - 4
        self.add(y, x, warning[:inner], self.warn_attr())
        y += 2
        self.add(y, x, subject[:inner], curses.A_BOLD)
        y += 1
        self.draw_wrapped(y, x, inner, details, max_lines=3)
        self.add(top + box_height - 2, x, footer[:inner], self.accent_attr())
        self.screen.refresh()

    def run_command(self, title: str, argv: list[str]) -> int:
        return self.run_commands(title, [argv])

    def run_build_command(self, title: str, argv: list[str]) -> int:
        self.save_current_build_settings()
        return self.run_commands(title, self.pre_build_sync_commands() + [argv])

    def pre_build_sync_commands(self) -> list[list[str]]:
        names = read_mapping_selection_if_exists(self.config)
        if not names:
            return []
        commands: list[list[str]] = []
        try:
            active_mappings = select_mappings(self.config, names)
        except SystemExit as exc:
            return [
                local_log_command(
                    "Pre-build sync failed",
                    str(exc),
                    exit_code=1,
                )
            ]
        issues = self.local_mapping_issues(active_mappings)
        if issues:
            return [
                local_log_command(
                    "Pre-build sync skipped: local overlay is not ready",
                    "Run Sync mapped files -> Pull selected apply first.",
                    *issues[:8],
                    exit_code=1,
                )
            ]
        commands.append(
            local_log_command(
                "Pre-build sync: pushing active mappings to remote",
                f"mappings: {', '.join(names)}",
            )
        )
        for mapping in active_mappings:
            try:
                commands.append(
                    rsync_mapping_command(
                        self.config,
                        mapping,
                        direction="push",
                        dry_run=False,
                    )
                )
            except SystemExit as exc:
                commands.append(
                    local_log_command(
                        f"Pre-build sync failed: {mapping['name']}",
                        str(exc),
                        exit_code=1,
                    )
                )
                break
        return commands

    def save_current_build_settings(self) -> None:
        save_build_settings(
            self.config,
            {
                "parameters": self.build_params,
                "targets": self.build_targets,
                "docker_image": self.docker_image,
            },
        )

    def run_commands(self, title: str, commands: list[list[str]]) -> int:
        if self.action_running or self.active_job is not None:
            self.status = "Another action is already running"
            return 1
        item = self.items[self.selected]
        self.active_job = {
            "title": title,
            "item_label": item.label,
            "commands": commands,
            "index": 0,
            "output": deque(maxlen=1000),
            "output_lock": threading.Lock(),
            "process": None,
            "current_command": "",
            "rc": None,
        }
        self.start_next_active_job_command()
        self.status = f"Running: {title}"
        self.focus_panel = "actions"
        self.menu_dirty = True
        self.main_full_redraw = True
        self.logs_dirty = True
        return 0

    def stop_running_preview(self) -> str:
        if self.active_job is None:
            return "No command is running."
        title = str(self.active_job.get("title", "Command"))
        return f"Stop active command: {title}"

    def stop_running_command(self) -> None:
        job = self.active_job
        if job is None:
            self.status = "No command is running"
            return
        if job.get("stopping"):
            self.status = "Command stop is already requested"
            return
        job["stopping"] = True
        process = job.get("process")
        if isinstance(process, subprocess.Popen) and process.poll() is None:
            self.append_job_output(job, "stop requested: SIGTERM")
            self.terminate_process_group(process.pid, signal.SIGTERM)
            job["stop_requested_at"] = time.monotonic()
            self.status = "Stop requested"
            self.logs_dirty = True
            return
        self.append_job_output(job, "stopped: no active process")
        job["rc"] = 130
        self.last_exit = 130
        self.status = f"{job.get('title', 'Command')}: stopped"
        self.finish_active_job()

    def finish_active_job(self) -> None:
        if self.active_job is not None:
            self.last_job = self.active_job
            self.active_job = None
            self.menu_dirty = True
            self.main_full_redraw = True
            self.logs_dirty = True

    def start_next_active_job_command(self) -> None:
        job = self.active_job
        if job is None:
            return
        commands = job["commands"]
        index = int(job["index"])
        if index >= len(commands):
            rc = int(job["rc"] or 0)
            self.last_exit = rc
            self.status = f"{job['title']}: exit {rc}"
            if job.get("title") == "Prepare remote project" and rc == 0:
                self.reset_preflight()
                self.status = "Prepare remote project: done; reconnect to refresh preflight"
            self.finish_active_job()
            return
        command = commands[index]
        job["current_command"] = shlex.join(command)
        self.append_job_output(job, f"Starting step {index + 1}/{len(commands)}...")
        self.logs_dirty = True
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        job["process"] = process
        reader = threading.Thread(target=self.read_process_output, args=(process, job), daemon=True)
        job["output_reader"] = reader
        reader.start()

    def append_job_output(self, job: dict[str, Any], line: str) -> None:
        lock = job.get("output_lock")
        if hasattr(lock, "__enter__") and hasattr(lock, "__exit__"):
            with lock:
                output = job.setdefault("output", deque(maxlen=1000))
                output.append(line)
                if not isinstance(output, deque) and len(output) > 1000:
                    del output[: len(output) - 1000]
        else:
            output = job.setdefault("output", deque(maxlen=1000))
            output.append(line)
            if not isinstance(output, deque) and len(output) > 1000:
                del output[: len(output) - 1000]
        self.logs_dirty = True

    def read_process_output(self, process: subprocess.Popen[str], job: dict[str, Any]) -> None:
        stdout = process.stdout
        if stdout is None:
            return
        try:
            for line in stdout:
                self.append_job_output(job, line.rstrip("\n"))
        finally:
            try:
                stdout.close()
            except Exception:
                pass

    def poll_active_job(self) -> None:
        job = self.active_job
        if job is None:
            return
        process = job.get("process")
        if process is None:
            self.start_next_active_job_command()
            return
        if (
            job.get("stopping")
            and process.poll() is None
            and time.monotonic() - float(job.get("stop_requested_at", time.monotonic())) > 2.0
        ):
            self.append_job_output(job, "stop timeout: SIGKILL")
            self.terminate_process_group(process.pid, signal.SIGKILL)
        if (
            job.get("kind") == "connect"
            and process.poll() is None
            and time.monotonic() - float(job.get("started_at", time.monotonic())) > float(job.get("timeout", 10.0))
        ):
            self.terminate_process_group(process.pid, signal.SIGTERM)
            time.sleep(0.2)
            if process.poll() is None:
                self.terminate_process_group(process.pid, signal.SIGKILL)
            self.append_job_output(job, "timeout")
            self.preflight = "timeout"
            self.preflight_values = {}
            self.connection_state = "disconnected"
            self.last_exit = 124
            self.status = "Disconnected: connect timeout"
            self.finish_active_job()
            return
        rc = process.poll()
        if rc is None:
            return
        reader = job.get("output_reader")
        if isinstance(reader, threading.Thread) and reader.is_alive():
            reader.join(timeout=0.2)
        self.append_job_output(job, f"exit: {rc}")
        job["rc"] = int(rc)
        if job.get("stopping"):
            self.last_exit = int(rc)
            self.status = f"{job['title']}: stopped ({rc})"
            self.finish_active_job()
            return
        if job.get("kind") == "connect":
            output = "\n".join(str(line) for line in self.job_output_lines(job))
            self.preflight = self.format_preflight(output)
            self.last_exit = int(rc)
            self.connection_state = "connected" if rc == 0 else "disconnected"
            self.status = "Connected" if self.connected else "Disconnected: connect failed"
            self.finish_active_job()
            return
        if rc != 0:
            self.last_exit = int(rc)
            self.status = f"{job['title']}: exit {rc}"
            self.finish_active_job()
            return
        job["index"] = int(job["index"]) + 1
        job["process"] = None
        self.start_next_active_job_command()

    def run_one_command(
        self,
        title: str,
        argv: list[str],
        output: list[str],
        view: dict[str, int | bool],
        stopped: bool,
    ) -> int:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        assert process.stdout is not None
        rc: int | None = None
        while rc is None:
            ready, _, _ = select.select([process.stdout], [], [], 0.1)
            if ready:
                line = process.stdout.readline()
                if line:
                    output.append(line.rstrip("\n"))
                    output[:] = output[-1000:]
            rc = process.poll()
            self.draw_command(title, shlex.join(argv), output, view, running=rc is None, stopped=stopped)
            ch = self.read_key()
            if self.handle_command_scroll_key(ch, output, view):
                continue
            if (self.key_matches(ch, "q") or ch in (27, 3)) and rc is None:
                stopped = True
                self.terminate_process_group(process.pid, signal.SIGTERM)
                time.sleep(1)
                if process.poll() is None:
                    self.terminate_process_group(process.pid, signal.SIGKILL)
        for line in process.stdout:
            output.append(line.rstrip("\n"))
            output[:] = output[-1000:]
        output.append(f"exit: {rc}")
        return int(rc)

    def command_result_loop(
        self,
        title: str,
        command: str,
        output: list[str],
        view: dict[str, int | bool],
        *,
        stopped: bool,
    ) -> None:
        self.screen.timeout(-1)
        while True:
            self.draw_command(title, command, output, view, running=False, stopped=stopped)
            ch = self.read_key()
            if (self.key_matches(ch, "q") or ch in (27, 10, 13)):
                return
            self.handle_command_scroll_key(ch, output, view)

    def command_visible_lines(self) -> int:
        height, _ = self.screen.getmaxyx()
        output_top = 9
        output_height = max(3, height - output_top - 2)
        return max(1, output_height - 2)

    def clamp_command_scroll(self, output: list[str], view: dict[str, int | bool]) -> int:
        visible = self.command_visible_lines()
        max_scroll = max(0, len(output) - visible)
        if view.get("follow"):
            view["scroll"] = max_scroll
        else:
            view["scroll"] = min(max(0, int(view["scroll"])), max_scroll)
        return int(view["scroll"])

    def handle_command_scroll_key(self, ch: int, output: list[str], view: dict[str, int | bool]) -> bool:
        if ch == -1:
            return False
        visible = self.command_visible_lines()
        max_scroll = max(0, len(output) - visible)
        scroll = self.clamp_command_scroll(output, view)
        if ch == curses.KEY_UP or self.key_matches(ch, "k"):
            view["follow"] = False
            view["scroll"] = max(0, scroll - 1)
        elif ch == curses.KEY_DOWN or self.key_matches(ch, "j"):
            view["follow"] = False
            view["scroll"] = min(max_scroll, scroll + 1)
        elif ch == curses.KEY_PPAGE:
            view["follow"] = False
            view["scroll"] = max(0, scroll - visible)
        elif ch == curses.KEY_NPAGE:
            view["follow"] = False
            view["scroll"] = min(max_scroll, scroll + visible)
        elif ch == curses.KEY_HOME:
            view["follow"] = False
            view["scroll"] = 0
        elif ch == curses.KEY_END:
            view["follow"] = True
            view["scroll"] = max_scroll
        else:
            return False
        return True

    def remote_configurations_screen(self) -> None:
        remote_index = 0
        remote_index_initialized = False
        field_index = 0
        focus = "remotes"
        editing_key = ""
        editing_value = ""
        editing_cursor = 0
        editing_cursor_yx: tuple[int, int] | None = None
        self.screen.timeout(-1)
        while True:
            editing_cursor_yx = None
            self.screen.clear()
            height, width = self.screen.getmaxyx()
            if height < 20 or width < 90:
                self.add(0, 0, "Terminal is too small. Need at least 90x20.", self.warn_attr())
                self.screen.refresh()
                ch = self.read_key()
                if (self.key_matches(ch, "q") or ch == 27):
                    self.screen.timeout(250)
                    return
                continue

            remote = active_remote(self.config)
            remotes = [item for item in self.config.get("remotes", []) if isinstance(item, dict)]
            if not remote_index_initialized:
                remote_index = self.active_remote_index(remotes)
                focus = "remotes"
                remote_index_initialized = True
            remote_index = min(remote_index, max(0, len(remotes) - 1))
            selected_remote = remotes[remote_index] if remotes else None
            panel_top = 3
            panel_height = height - 6
            self.add(0, 0, "Remote configurations"[:width], curses.A_BOLD)
            active_name = str(remote.get("name", "")) or "<none>"
            self.add(1, 0, f"Active: {active_name} | Connection: {self.connection_state}"[:width])
            self.add(2, 0, f"Focus: {'remote list' if focus == 'remotes' else 'fields'}"[:width], self.accent_attr())
            self.draw_box(panel_top, 0, panel_height, width, "Remotes")

            detail_x = 2
            detail_w = width - 4
            table_w = width - 4
            fields: list[tuple[str, str]] = []
            if selected_remote is not None:
                fields = [
                    ("Profile name", "name"),
                    ("Display label", "label"),
                    ("SSH user", "user"),
                    ("SSH host", "host"),
                ]
                field_index = min(field_index, max(0, len(fields) - 1))
            else:
                field_index = 0
            min_detail_rows = 2 + len(fields) + 3
            visible_remotes = max(1, min(max(1, len(remotes)), panel_height - min_detail_rows))
            remote_scroll = min(max(0, remote_index - visible_remotes + 1), max(0, len(remotes) - visible_remotes))
            table_y = panel_top + 1
            self.add(table_y, 2, self.fit_text("A Name               User@Host", table_w), self.accent_attr())
            if not remotes:
                self.add(table_y + 1, 2, "No remotes configured. Press 'a' to add one."[:table_w], self.disabled_attr())
            else:
                for offset, profile in enumerate(remotes[remote_scroll : remote_scroll + visible_remotes]):
                    item_index = remote_scroll + offset
                    is_active = str(profile.get("name", "")) == str(self.config.get("active_remote", ""))
                    active_mark = "*" if is_active else " "
                    user_host = f"{profile.get('user', '')}@{profile.get('host', '')}"
                    active_suffix = "  ACTIVE" if is_active else ""
                    text = f"{active_mark} {str(profile.get('name', ''))[:18]:18} {user_host}{active_suffix}"
                    selected_remote_row = focus == "remotes" and item_index == remote_index
                    if selected_remote_row and is_active:
                        attr = self.selected_active_attr()
                    elif selected_remote_row:
                        attr = self.selected_attr()
                    elif is_active:
                        attr = self.active_row_attr()
                    else:
                        attr = 0
                    self.add(table_y + 1 + offset, 2, self.fit_text(text, table_w).ljust(table_w), attr)

            row = table_y + visible_remotes + 2
            if len(remotes) > visible_remotes:
                self.add(row, detail_x, f"{remote_index + 1}/{len(remotes)} remotes"[:detail_w], self.disabled_attr())
                row += 1
            if selected_remote is None:
                self.add(row, detail_x, "Selected remote: <none>"[:detail_w], self.disabled_attr())
            else:
                self.add(row, detail_x, "Fields:", self.accent_attr())
                row += 1
                visible_fields = max(0, panel_top + panel_height - row - 5)
                for offset, (label, key) in enumerate(fields[:visible_fields]):
                    is_editing = focus == "fields" and key == editing_key
                    raw_value = editing_value if is_editing else str(selected_remote.get(key, ""))
                    value = raw_value or "<not set>"
                    enabled = self.remote_field_enabled(key, selected_remote)
                    selected = focus == "fields" and offset == field_index
                    if is_editing:
                        attr = self.editing_attr()
                    elif selected and enabled:
                        attr = self.selected_attr()
                    elif selected:
                        attr = self.selected_disabled_attr()
                    elif not enabled:
                        attr = self.disabled_attr()
                    else:
                        attr = 0
                    text = f"{label}:".ljust(20) + value
                    self.add(row, detail_x, self.fit_text(text, detail_w).ljust(detail_w), attr)
                    if is_editing:
                        cursor_x = min(detail_x + 20 + editing_cursor, detail_x + detail_w - 1)
                        editing_cursor_yx = (row, cursor_x)
                    row += 1
                if row < height - 3 and fields and focus == "fields":
                    _, selected_key = fields[field_index]
                    if editing_key:
                        self.add(row, detail_x, "Enter: save | Esc: cancel | Left/Right/Home/End: move cursor"[:detail_w], self.accent_attr())
                    else:
                        enabled = self.remote_field_enabled(selected_key, selected_remote)
                        message = self.remote_field_hint(selected_key, selected_remote) if enabled else self.remote_field_disabled_reason(selected_key, selected_remote)
                        self.add(row, detail_x, message[:detail_w], self.accent_attr() if enabled else self.disabled_attr())

            footer = "Left/Right: remotes/fields | Enter: edit/save | a: add | d: delete | s: set active | Esc: remotes/back | q: back"
            self.add(height - 2, 0, footer[:width], self.accent_attr())
            self.add(height - 1, 0, self.status[:width].ljust(width), curses.A_REVERSE)
            if editing_cursor_yx is not None:
                self.set_cursor(True)
                try:
                    self.screen.move(*editing_cursor_yx)
                except curses.error:
                    pass
            else:
                self.set_cursor(False)
            self.screen.timeout(-1)
            self.screen.refresh()
            ch = self.read_key()
            if ch == -1:
                continue
            if editing_key:
                if ch in (10, 13):
                    self.apply_remote_inline_value(selected_remote, editing_key, editing_value)
                    editing_key = ""
                    editing_value = ""
                    editing_cursor = 0
                    self.set_cursor(False)
                elif ch == 27:
                    editing_key = ""
                    editing_value = ""
                    editing_cursor = 0
                    self.status = "Edit cancelled"
                    self.set_cursor(False)
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    if editing_cursor > 0:
                        editing_value = editing_value[: editing_cursor - 1] + editing_value[editing_cursor:]
                        editing_cursor -= 1
                elif ch == curses.KEY_DC:
                    if editing_cursor < len(editing_value):
                        editing_value = editing_value[:editing_cursor] + editing_value[editing_cursor + 1:]
                elif ch == curses.KEY_LEFT:
                    editing_cursor = max(0, editing_cursor - 1)
                elif ch == curses.KEY_RIGHT:
                    editing_cursor = min(len(editing_value), editing_cursor + 1)
                elif ch == curses.KEY_HOME:
                    editing_cursor = 0
                elif ch == curses.KEY_END:
                    editing_cursor = len(editing_value)
                elif char := self.key_text(ch):
                    editing_value = editing_value[:editing_cursor] + char + editing_value[editing_cursor:]
                    editing_cursor += 1
                continue
            self.set_cursor(False)
            if ch == curses.KEY_LEFT or self.key_matches(ch, "h"):
                focus = "remotes"
            elif ch == curses.KEY_RIGHT or self.key_matches(ch, "l"):
                if selected_remote is None:
                    self.status = "Add a remote first"
                else:
                    focus = "fields"
            elif ch == curses.KEY_UP or self.key_matches(ch, "k"):
                if focus == "fields" and fields:
                    field_index = (field_index - 1) % len(fields)
                elif remotes:
                    remote_index = (remote_index - 1) % len(remotes)
            elif (ch == curses.KEY_DOWN or self.key_matches(ch, "j") or ch == ord("\t")):
                if focus == "fields" and fields:
                    field_index = (field_index + 1) % len(fields)
                elif remotes:
                    remote_index = (remote_index + 1) % len(remotes)
            elif ch in (10, 13):
                if selected_remote is None:
                    self.status = "Add a remote first"
                elif focus == "remotes":
                    focus = "fields"
                else:
                    label, key = fields[field_index]
                    if not self.remote_field_enabled(key, selected_remote):
                        self.status = self.remote_field_disabled_reason(key, selected_remote)
                    elif key == "moulin_manifest":
                        self.select_remote_moulin_manifest()
                    elif key == "dockerfile":
                        self.select_remote_dockerfile()
                    else:
                        editing_key = key
                        editing_value = str(selected_remote.get(key, ""))
                        editing_cursor = len(editing_value)
                        self.status = f"Editing {label}"
            elif self.key_matches(ch, "a"):
                self.add_empty_remote()
                remote_index = max(0, len(self.config.get("remotes", [])) - 1)
                focus = "fields" if self.config.get("remotes") else "remotes"
            elif self.key_matches(ch, "d"):
                if selected_remote is None:
                    self.status = "No remote selected"
                else:
                    self.delete_remote(selected_remote)
                    remote_index = min(remote_index, max(0, len(self.config.get("remotes", [])) - 1))
                    focus = "remotes"
            elif self.key_matches(ch, "s"):
                if selected_remote is None:
                    self.status = "No remote selected"
                else:
                    self.set_active_remote(selected_remote)
            elif ch == 27 and focus == "fields":
                focus = "remotes"
                self.status = "Remote list focused"
            elif (self.key_matches(ch, "q") or ch == 27):
                save_config(self.config)
                self.screen.timeout(250)
                return

    def active_remote_index(self, remotes: list[dict[str, Any]]) -> int:
        active = str(self.config.get("active_remote", ""))
        for index, remote in enumerate(remotes):
            if str(remote.get("name", "")) == active:
                return index
        return 0

    def add_empty_remote(self) -> None:
        name = self.prompt("Remote profile name", self.next_remote_name()).strip()
        if not name:
            self.status = "Remote add cancelled"
            return
        if any(str(item.get("name", "")) == name for item in self.config.get("remotes", [])):
            self.status = f"Remote profile already exists: {name}"
            return
        self.config.setdefault("remotes", []).append(empty_remote_profile(name))
        save_config(self.config)
        self.status = f"Remote profile added: {name}"

    def delete_remote(self, remote: dict[str, Any]) -> None:
        name = str(remote.get("name", ""))
        if not self.confirm_sync_action("Delete remote", f"Delete remote profile {name}."):
            self.status = "Remote delete cancelled"
            return
        self.config["remotes"] = [item for item in self.config.get("remotes", []) if item is not remote]
        if str(self.config.get("active_remote", "")) == name:
            self.config["active_remote"] = str(self.config["remotes"][0].get("name", "")) if self.config["remotes"] else ""
            self.connection_state = "disconnected"
            self.reset_preflight()
        sync_active_remote(self.config)
        save_config(self.config)
        self.status = f"Remote profile deleted: {name}"

    def set_active_remote(self, remote: dict[str, Any]) -> None:
        name = str(remote.get("name", ""))
        if str(self.config.get("active_remote", "")) == name:
            self.status = "selected remote is already active"
            return
        self.config["active_remote"] = name
        sync_active_remote(self.config)
        self.connection_state = "disconnected"
        self.reset_preflight()
        save_config(self.config)
        self.status = f"Active remote: {name}"

    def edit_remote_screen(self, remote: dict[str, Any]) -> None:
        fields = [
            ("Profile name", "name"),
            ("Display label", "label"),
            ("SSH user", "user"),
            ("SSH host", "host"),
            ("Project directory", "project_dir"),
            ("Back", "back"),
        ]
        index = 0
        self.screen.timeout(-1)
        while True:
            self.screen.clear()
            height, width = self.screen.getmaxyx()
            if height < 18 or width < 80:
                self.add(0, 0, "Terminal is too small. Need at least 80x18.", self.warn_attr())
                self.screen.refresh()
                ch = self.read_key()
                if (self.key_matches(ch, "q") or ch == 27):
                    self.screen.timeout(250)
                    return
                continue

            name = str(remote.get("name", ""))
            active = name == str(self.config.get("active_remote", ""))
            self.add(0, 0, "Edit remote"[:width], curses.A_BOLD)
            self.add(1, 0, f"{name or '<unnamed>'} | {'active' if active else 'inactive'} | connection: {self.connection_state}"[:width])
            self.draw_box(3, 0, height - 6, width, "Fields")
            for offset, (label, key) in enumerate(fields):
                if key == "back":
                    value = ""
                else:
                    value = str(remote.get(key, "")) or "<not set>"
                enabled = self.remote_field_enabled(key, remote)
                if offset == index and enabled:
                    attr = self.selected_attr()
                elif offset == index:
                    attr = self.selected_disabled_attr()
                elif not enabled:
                    attr = self.disabled_attr()
                else:
                    attr = 0
                text = f"{offset + 1}. {label}".ljust(22) + (value if value else "")
                self.add(4 + offset, 2, self.fit_text(text, width - 4).ljust(width - 4), attr)

            selected_label, selected_key = fields[index]
            detail_row = 4 + len(fields) + 2
            if detail_row < height - 3:
                self.add(detail_row, 2, self.remote_field_hint(selected_key, remote)[: width - 4], self.accent_attr())
            reason = self.remote_field_disabled_reason(selected_key, remote)
            if reason and detail_row + 1 < height - 3:
                self.add(detail_row + 1, 2, f"Status: {reason}"[: width - 4], self.disabled_attr())

            footer = "Enter: edit/open | b: browse project dir | s: set active | q/Esc: back"
            self.add(height - 2, 0, footer[:width], self.accent_attr())
            self.add(height - 1, 0, self.status[:width].ljust(width), curses.A_REVERSE)
            self.screen.refresh()
            ch = self.read_key()
            if ch == curses.KEY_UP or self.key_matches(ch, "k"):
                index = (index - 1) % len(fields)
            elif (ch == curses.KEY_DOWN or self.key_matches(ch, "j") or ch == ord("\t")):
                index = (index + 1) % len(fields)
            elif self.key_matches(ch, "s"):
                self.set_active_remote(remote)
                active = True
            elif self.key_matches(ch, "b"):
                self.edit_remote_project_dir(remote)
            elif ch in (10, 13):
                label, key = fields[index]
                if key == "back":
                    save_config(self.config)
                    self.screen.timeout(250)
                    return
                if not self.remote_field_enabled(key, remote):
                    self.status = self.remote_field_disabled_reason(key, remote)
                    continue
                if key == "project_dir":
                    self.edit_remote_project_dir(remote)
                else:
                    self.edit_remote_value(remote, key, label)
            elif (self.key_matches(ch, "q") or ch == 27):
                save_config(self.config)
                self.screen.timeout(250)
                return

    def remote_field_enabled(self, key: str, remote: dict[str, Any]) -> bool:
        if key in ("back", "name", "label", "user"):
            return True
        if key == "host":
            return bool(str(remote.get("user", "")).strip())
        if key in ("project_dir", "moulin_manifest", "dockerfile"):
            return (
                str(remote.get("name", "")) == str(self.config.get("active_remote", ""))
                and self.connected
                and bool(str(remote.get("user", "")).strip())
                and bool(str(remote.get("host", "")).strip())
                and (key == "project_dir" or bool(str(remote.get("project_dir", "")).strip()))
            )
        return True

    def remote_field_disabled_reason(self, key: str, remote: dict[str, Any]) -> str:
        if key == "host":
            return "set SSH user first"
        if key in ("project_dir", "moulin_manifest", "dockerfile"):
            if str(remote.get("name", "")) != str(self.config.get("active_remote", "")):
                return "set this remote active first"
            if not str(remote.get("user", "")).strip():
                return "set SSH user first"
            if not str(remote.get("host", "")).strip():
                return "set SSH host first"
            if key != "project_dir" and not str(remote.get("project_dir", "")).strip():
                return "select remote project directory first"
            return "connect to the remote target first"
        return ""

    def remote_field_hint(self, key: str, remote: dict[str, Any]) -> str:
        hints = {
            "name": "Unique local profile id. Renaming an active profile preserves active selection.",
            "label": "Display label shown in the main client header.",
            "user": "SSH user for the remote build machine.",
            "host": "SSH host name or IP address.",
            "project_dir": "Remote Moulin checkout directory. Use Enter or b to browse after connect.",
            "back": "Return to the remote list.",
        }
        return hints.get(key, "")

    def apply_remote_inline_value(self, remote: dict[str, Any] | None, key: str, value: str) -> None:
        if remote is None:
            self.status = "No remote selected"
            return
        old_name = str(remote.get("name", ""))
        value = value.strip()
        if key == "name":
            if not value:
                self.status = "Remote profile name is required"
                return
            if value != old_name and any(str(item.get("name", "")) == value for item in self.config.get("remotes", [])):
                self.status = f"Remote profile already exists: {value}"
                return
        remote[key] = value
        if key == "name":
            if not str(remote.get("label", "")).strip() or str(remote.get("label", "")) == old_name:
                remote["label"] = value
            if str(self.config.get("active_remote", "")) == old_name:
                self.config["active_remote"] = value
        if key in ("user", "host", "project_dir") and str(remote.get("name", "")) == str(self.config.get("active_remote", "")):
            self.connection_state = "disconnected"
            self.reset_preflight()
        sync_active_remote(self.config)
        save_config(self.config)
        self.status = f"{key} updated"

    def edit_remote_value(self, remote: dict[str, Any], key: str, label: str) -> None:
        old_name = str(remote.get("name", ""))
        value = self.prompt(label, str(remote.get(key, ""))).strip()
        if key == "name":
            if not value:
                self.status = "Remote profile name is required"
                return
            if value != old_name and any(str(item.get("name", "")) == value for item in self.config.get("remotes", [])):
                self.status = f"Remote profile already exists: {value}"
                return
        remote[key] = value
        if key == "name":
            if not str(remote.get("label", "")).strip() or str(remote.get("label", "")) == old_name:
                remote["label"] = value
            if str(self.config.get("active_remote", "")) == old_name:
                self.config["active_remote"] = value
        if key in ("user", "host", "project_dir") and str(remote.get("name", "")) == str(self.config.get("active_remote", "")):
            self.connection_state = "disconnected"
            self.reset_preflight()
        sync_active_remote(self.config)
        save_config(self.config)
        self.status = f"{label} updated"

    def edit_remote_project_dir(self, remote: dict[str, Any]) -> None:
        if not self.remote_field_enabled("project_dir", remote):
            self.status = self.remote_field_disabled_reason("project_dir", remote)
            return
        selected = self.browse_remote_directory_screen(str(remote.get("project_dir", "")) or "~")
        if selected:
            remote["project_dir"] = selected
            sync_active_remote(self.config)
            save_config(self.config)
            self.status = f"Remote project dir: {selected}"

    def remote_config_action_enabled(self, label: str, remote: dict[str, Any]) -> bool:
        if label == "Set active remote":
            return str(remote.get("name", "")) != str(self.config.get("active_remote", ""))
        if label == "Edit SSH host":
            return bool(str(remote.get("user", "")).strip())
        if label == "Browse project dir":
            return (
                str(remote.get("name", "")) == str(self.config.get("active_remote", ""))
                and self.connected
                and bool(str(remote.get("user", "")).strip())
                and bool(str(remote.get("host", "")).strip())
            )
        if label == "Delete selected remote":
            return True
        return True

    def remote_config_action_disabled_reason(self, label: str, remote: dict[str, Any]) -> str:
        if label == "Set active remote":
            return "selected remote is already active"
        if label == "Edit SSH host":
            return "set SSH user first"
        if label == "Browse project dir":
            if str(remote.get("name", "")) != str(self.config.get("active_remote", "")):
                return "set this remote active first"
            if not str(remote.get("user", "")).strip():
                return "set SSH user first"
            if not str(remote.get("host", "")).strip():
                return "set SSH host first"
            return "connect to the remote target first"
        if label == "Delete selected remote":
            return ""
        return "disabled"

    def run_remote_config_action(self, label: str, remote: dict[str, Any]) -> bool:
        if label == "Back":
            save_config(self.config)
            return True
        if label == "Add remote":
            name = self.prompt("Remote profile name", self.next_remote_name()).strip()
            if not name:
                self.status = "Remote add cancelled"
                return False
            if any(str(item.get("name", "")) == name for item in self.config.get("remotes", [])):
                self.status = f"Remote profile already exists: {name}"
                return False
            new_remote = empty_remote_profile(name)
            self.config.setdefault("remotes", []).append(new_remote)
            save_config(self.config)
            self.status = f"Remote profile added: {name}"
            return False
        if label == "Delete selected remote":
            name = str(remote.get("name", ""))
            if not self.confirm_sync_action("Delete remote", f"Delete remote profile {name}."):
                self.status = "Remote delete cancelled"
                return False
            self.config["remotes"] = [item for item in self.config.get("remotes", []) if item is not remote]
            if str(self.config.get("active_remote", "")) == name:
                self.config["active_remote"] = str(self.config["remotes"][0].get("name", "")) if self.config["remotes"] else ""
                self.connection_state = "disconnected"
                self.reset_preflight()
            sync_active_remote(self.config)
            save_config(self.config)
            self.status = f"Remote profile deleted: {name}"
            return False
        if label == "Set active remote":
            self.config["active_remote"] = str(remote.get("name", ""))
            sync_active_remote(self.config)
            self.connection_state = "disconnected"
            self.reset_preflight()
            save_config(self.config)
            self.status = f"Active remote: {self.config['active_remote']}"
            return False
        if label == "Edit profile name":
            old = str(remote.get("name", ""))
            new = self.prompt("Remote profile name", old).strip()
            if not new:
                self.status = "Remote rename cancelled"
                return False
            if new != old and any(str(item.get("name", "")) == new for item in self.config.get("remotes", [])):
                self.status = f"Remote profile already exists: {new}"
                return False
            remote["name"] = new
            remote["label"] = self.prompt("Remote label", str(remote.get("label", new))).strip() or new
            self.config["active_remote"] = new
            sync_active_remote(self.config)
            save_config(self.config)
            self.status = f"Remote profile renamed: {new}"
            return False
        if label == "Edit display label":
            remote["label"] = self.prompt("Remote label", str(remote.get("label", remote.get("name", "")))).strip() or str(remote.get("name", ""))
            sync_active_remote(self.config)
            save_config(self.config)
            self.status = "Remote label updated"
            return False
        if label == "Edit SSH user":
            remote["user"] = self.prompt("SSH user", str(remote.get("user", ""))).strip()
            sync_active_remote(self.config)
            if str(remote.get("name", "")) == str(self.config.get("active_remote", "")):
                self.connection_state = "disconnected"
                self.reset_preflight()
            save_config(self.config)
            self.status = "SSH user updated"
            return False
        if label == "Edit SSH host":
            remote["host"] = self.prompt("SSH host", str(remote.get("host", ""))).strip()
            sync_active_remote(self.config)
            if str(remote.get("name", "")) == str(self.config.get("active_remote", "")):
                self.connection_state = "disconnected"
                self.reset_preflight()
            save_config(self.config)
            self.status = "SSH host updated"
            return False
        if label == "Browse project dir":
            selected = self.browse_remote_directory_screen(str(remote.get("project_dir", "")) or "~")
            if selected:
                remote["project_dir"] = selected
                sync_active_remote(self.config)
                save_config(self.config)
                self.status = f"Remote project dir: {selected}"
            return False
        return False

    def add_remote_screen(self) -> None:
        draft = {
            "name": self.next_remote_name(),
            "label": "",
            "user": "",
            "host": "",
            "project_dir": "",
        }
        actions = [
            ("Edit profile name", "name", "Unique local profile id."),
            ("Edit display label", "label", "Human-readable label shown in the header."),
            ("Edit SSH user", "user", "Remote SSH user. Required before the profile can be used."),
            ("Edit SSH host", "host", "Remote SSH host. Required before the profile can be used."),
            ("Create remote", "create", "Save this profile and make it active."),
            ("Cancel", "cancel", "Return without saving this profile."),
        ]
        index = 0
        self.screen.timeout(-1)
        while True:
            self.screen.erase()
            height, width = self.screen.getmaxyx()
            if height < 20 or width < 90:
                self.add(0, 0, "Terminal is too small. Need at least 90x20.", self.warn_attr())
                self.screen.refresh()
                ch = self.read_key()
                if (self.key_matches(ch, "q") or ch == 27):
                    return
                continue

            left_width = min(42, max(34, width // 3))
            right_left = left_width + 1
            right_width = width - right_left
            panel_top = 3
            panel_height = height - 6
            self.add(0, 0, "Add remote"[:width], curses.A_BOLD)
            self.add(1, 0, "Fill fields, then run Create remote. Nothing is saved before Create."[:width])
            self.draw_box(panel_top, 0, panel_height, left_width, "Fields")
            self.draw_box(panel_top, right_left, panel_height, right_width, "Details")

            for offset, (label, kind, _) in enumerate(actions):
                enabled = self.add_remote_action_enabled(kind, draft)
                if offset == index and enabled:
                    attr = self.selected_attr()
                elif offset == index:
                    attr = self.selected_disabled_attr()
                elif not enabled:
                    attr = self.disabled_attr()
                else:
                    attr = 0
                value = ""
                if kind in draft:
                    value = f": {draft[kind] or '<not set>'}"
                self.add(panel_top + 1 + offset, 2, f"{offset + 1}. {label}{value}"[: left_width - 4].ljust(left_width - 4), attr)

            label, kind, description = actions[index]
            detail_x = right_left + 2
            detail_w = right_width - 4
            row = panel_top + 2
            self.add(row, detail_x, label[:detail_w], curses.A_BOLD)
            row += 2
            row = self.draw_wrapped(row, detail_x, detail_w, description, max_lines=3)
            row += 1
            reason = self.add_remote_disabled_reason(kind, draft)
            if reason:
                self.add(row, detail_x, f"Status: {reason}"[:detail_w], self.disabled_attr())
                row += 2
            else:
                row += 1
            for key in ("name", "label", "user", "host"):
                value = draft[key] or "<not set>"
                self.add(row, detail_x, f"{key}:".ljust(10), self.accent_attr())
                self.add(row, detail_x + 10, self.fit_text(value, detail_w - 10), self.disabled_attr() if value == "<not set>" else 0)
                row += 1

            footer = "Up/Down/Tab: select | Enter: edit/run | q/Esc: cancel"
            self.add(height - 2, 0, footer[:width], self.accent_attr())
            self.add(height - 1, 0, self.status[:width].ljust(width), curses.A_REVERSE)
            self.screen.refresh()
            ch = self.read_key()
            if ch == curses.KEY_UP or self.key_matches(ch, "k"):
                index = (index - 1) % len(actions)
            elif (ch == curses.KEY_DOWN or self.key_matches(ch, "j") or ch == ord("\t")):
                index = (index + 1) % len(actions)
            elif ch in (10, 13):
                if not self.add_remote_action_enabled(kind, draft):
                    self.status = self.add_remote_disabled_reason(kind, draft)
                    continue
                if kind in draft:
                    current = str(draft[kind])
                    value = self.prompt(label.removeprefix("Edit "), current).strip()
                    draft[kind] = value
                    if kind == "name" and not draft["label"]:
                        draft["label"] = value
                elif kind == "create":
                    new_remote = {key: str(value).strip() for key, value in draft.items()}
                    if not new_remote["label"]:
                        new_remote["label"] = new_remote["name"]
                    new_remote["project_dir"] = ""
                    self.config.setdefault("remotes", []).append(new_remote)
                    self.config["active_remote"] = new_remote["name"]
                    sync_active_remote(self.config)
                    self.connection_state = "disconnected"
                    self.reset_preflight()
                    save_config(self.config)
                    self.status = f"Remote profile added: {new_remote['name']}"
                    return
                elif kind == "cancel":
                    self.status = "Remote add cancelled"
                    return
            elif (self.key_matches(ch, "q") or ch == 27):
                self.status = "Remote add cancelled"
                return

    def next_remote_name(self) -> str:
        existing = {str(remote.get("name", "")) for remote in self.config.get("remotes", [])}
        index = len(existing) + 1
        while f"remote-{index}" in existing:
            index += 1
        return f"remote-{index}"

    def add_remote_action_enabled(self, kind: str, draft: dict[str, str]) -> bool:
        if kind == "create":
            return not self.add_remote_disabled_reason(kind, draft)
        return True

    def add_remote_disabled_reason(self, kind: str, draft: dict[str, str]) -> str:
        if kind != "create":
            return ""
        name = draft.get("name", "").strip()
        if not name:
            return "set profile name first"
        if any(str(remote.get("name", "")) == name for remote in self.config.get("remotes", [])):
            return "profile name already exists"
        if not draft.get("user", "").strip():
            return "set SSH user first"
        if not draft.get("host", "").strip():
            return "set SSH host first"
        return ""

    def browse_remote_directory_screen(self, start_path: str) -> str | None:
        current_path = start_path if start_path and start_path != "." else "~"
        index = 0
        dirs: list[str] = []
        error = ""
        pending_path: str | None = current_path
        self.screen.timeout(-1)
        while True:
            height, width = self.screen.getmaxyx()
            if height < 18 or width < 80:
                self.screen.clear()
                self.add(0, 0, "Terminal is too small. Need at least 80x18.", self.warn_attr())
                self.screen.refresh()
                ch = self.read_key()
                if (self.key_matches(ch, "q") or ch == 27):
                    return None
                continue
            if pending_path is not None:
                try:
                    next_dirs = self.remote_child_dirs(pending_path)
                    current_path = pending_path
                    dirs = next_dirs
                    error = ""
                    index = 0
                except Exception as exc:
                    error = str(exc)
                pending_path = None
            entries = [".."] + dirs
            index = min(index, max(0, len(entries) - 1))
            self.draw_remote_directory_browser(current_path, dirs, index, error, loading=False)
            ch = self.read_key()
            if ch == curses.KEY_UP or self.key_matches(ch, "k"):
                index = (index - 1) % len(entries)
            elif ch == curses.KEY_DOWN or self.key_matches(ch, "j"):
                index = (index + 1) % len(entries)
            elif ch in (ord("\t"), 10, 13):
                selected = entries[index]
                if selected == "..":
                    pending_path = self.remote_parent_dir(current_path)
                else:
                    pending_path = selected
            elif ch == ord(" "):
                selected = entries[index]
                return current_path if selected == ".." else selected
            elif (self.key_matches(ch, "q") or ch == 27):
                return None

    def draw_remote_directory_browser(self, current_path: str, dirs: list[str], index: int, error: str, *, loading: bool) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        panel_top = 3
        panel_height = height - 6
        self.add(0, 0, "Browse remote project directory"[:width].ljust(width), curses.A_BOLD)
        self.add(1, 0, f"{remote_spec(self.config)}:{current_path}"[:width].ljust(width))
        self.draw_box(panel_top, 0, panel_height, width, "Directories")
        inner_width = max(0, width - 4)
        for row in range(panel_top + 1, panel_top + panel_height - 1):
            self.add(row, 2, " " * inner_width)
        if loading:
            self.add(panel_top + 1, 2, "Loading..."[:inner_width], self.accent_attr())
        elif error:
            self.add(panel_top + 1, 2, error[:inner_width], self.error_attr())
        entries = [".."] + dirs
        visible = max(1, panel_height - 2)
        index = min(index, max(0, len(entries) - 1))
        scroll = min(max(0, index - visible + 1), max(0, len(entries) - visible))
        if not loading:
            for offset, path in enumerate(entries[scroll : scroll + visible]):
                item_index = scroll + offset
                attr = self.selected_attr() if item_index == index else 0
                label = "../" if path == ".." else Path(path).name + "/"
                self.add(panel_top + 1 + offset, 2, label[:inner_width].ljust(inner_width), attr)
        footer = "Up/Down: select | Enter: open | Space: choose selected | q/Esc: back"
        self.add(height - 2, 0, footer[:width].ljust(width), self.accent_attr())
        self.add(height - 1, 0, self.status[:width].ljust(width), curses.A_REVERSE)
        self.screen.noutrefresh()
        curses.doupdate()

    def remote_child_dirs(self, path: str) -> list[str]:
        quoted = "$HOME" if path == "~" else shlex.quote(path)
        script = f"cd {quoted} && find . -mindepth 1 -maxdepth 1 -type d -printf '%P\\n' | sort"
        result = capture(["ssh", remote_spec(self.config), script], echo=False)
        base = path.rstrip("/") if path != "~" else "~"
        return [f"{base}/{line.strip()}".replace("//", "/") for line in result.splitlines() if line.strip()]

    def remote_parent_dir(self, path: str) -> str:
        if path in ("", "/"):
            return path or "~"
        if path == "~":
            home = self.remote_home_dir()
            parent = str(PurePosixPath(home).parent)
            return parent if parent else "/"
        if path.startswith("~/"):
            rest = path[2:].rstrip("/")
            parent = str(PurePosixPath(rest).parent)
            return "~" if parent == "." else f"~/{parent}"
        parent = str(PurePosixPath(path.rstrip("/")).parent)
        return parent if parent else "/"

    def remote_home_dir(self) -> str:
        try:
            home = capture(["ssh", remote_spec(self.config), "printf '%s\\n' \"$HOME\""], echo=False).strip()
        except Exception:
            return "~"
        return home or "~"

    def run_local_callable(self, title: str, callback: Callable[[], None]) -> None:
        curses.def_prog_mode()
        curses.endwin()
        try:
            print()
            print(f"== {title} ==")
            callback()
            input("Press Enter to return to Moulin client...")
            self.status = f"{title}: done"
            self.last_exit = 0
        except SystemExit as exc:
            print(exc)
            input("Press Enter to return to Moulin client...")
            self.status = f"{title}: failed"
            self.last_exit = 1
        finally:
            curses.reset_prog_mode()
            self.screen.keypad(True)
            self.screen.timeout(250)

    def sync_screen(self) -> None:
        actions = [
            {
                "label": "Select mappings",
                "description": "Browse the remote project tree and save file or directory mappings to the client config.",
                "handler": lambda: self.add_mapping_screen(),
                "requires_remote": True,
                "confirm": False,
            },
            {
                "label": "Activate mappings",
                "description": "Choose the active subset of saved mappings for pull, push, and automatic pre-build sync.",
                "handler": lambda: self.select_mappings_screen(),
                "requires_remote": False,
                "confirm": False,
            },
            {
                "label": "Pull selected dry-run",
                "description": "Preview copying active mapped areas from the remote project tree to the local overlay.",
                "handler": lambda: self.run_commands(
                    "Pull selected mappings dry-run",
                    selected_mapping_commands(self.config, direction="pull", dry_run=True),
                ),
                "requires_remote": True,
                "confirm": False,
            },
            {
                "label": "Pull selected apply",
                "description": "Copy active mapped areas from the remote project tree to the local overlay.",
                "handler": lambda: self.run_commands(
                    "Pull selected mappings apply",
                    selected_mapping_commands(self.config, direction="pull", dry_run=False),
                ),
                "requires_remote": True,
                "confirm": True,
            },
            {
                "label": "Push selected dry-run",
                "description": "Preview pushing active mapped areas from the local overlay to the remote project tree.",
                "handler": lambda: self.run_commands(
                    "Push selected mappings dry-run",
                    selected_mapping_commands(self.config, direction="push", dry_run=True),
                ),
                "requires_remote": True,
                "confirm": False,
            },
            {
                "label": "Push selected apply",
                "description": "Push active mapped areas from the local overlay to the remote project tree.",
                "handler": lambda: self.run_commands(
                    "Push selected mappings apply",
                    selected_mapping_commands(self.config, direction="push", dry_run=False),
                ),
                "requires_remote": True,
                "confirm": True,
            },
            {
                "label": "Back",
                "description": "Return to the main menu.",
                "handler": None,
                "requires_remote": False,
                "confirm": False,
            },
        ]
        index = 0
        self.screen.timeout(-1)
        while True:
            self.screen.erase()
            height, width = self.screen.getmaxyx()
            if height < 18 or width < 80:
                self.add(0, 0, "Terminal is too small. Need at least 80x18.", self.warn_attr())
                self.screen.refresh()
                ch = self.read_key()
                if (self.key_matches(ch, "q") or ch == 27):
                    self.screen.timeout(250)
                    return
                continue

            left_width = min(38, max(30, width // 3))
            right_left = left_width + 1
            right_width = width - right_left
            panel_top = 3
            panel_height = height - 6
            selected_names = read_mapping_selection_if_exists(self.config)

            self.add(0, 0, "Sync mapped files"[:width], curses.A_BOLD)
            self.add(1, 0, f"Selected mappings: {', '.join(selected_names) or 'none'}"[:width])
            self.draw_box(panel_top, 0, panel_height, left_width, "Actions")
            self.draw_box(panel_top, right_left, panel_height, right_width, "Details")

            for offset, action in enumerate(actions):
                row = panel_top + 1 + offset
                enabled = self.connected or not action["requires_remote"]
                label = f"{offset + 1}. {action['label']}"
                attr = self.selected_attr() if offset == index else 0
                if not enabled:
                    attr = self.disabled_attr()
                self.add(row, 2, label[: left_width - 4].ljust(left_width - 4), attr)

            action = actions[index]
            detail_x = right_left + 2
            detail_w = right_width - 4
            row = panel_top + 2
            self.add(row, detail_x, str(action["label"])[:detail_w], curses.A_BOLD)
            row += 2
            row = self.draw_wrapped(row, detail_x, detail_w, str(action["description"]), max_lines=4)
            row += 1
            if action["requires_remote"] and not self.connected:
                self.add(row, detail_x, "Status: disabled until the remote target is connected"[:detail_w], self.disabled_attr())
                row += 1
            self.add(row, detail_x, "Configured mappings:"[:detail_w], self.accent_attr())
            row += 1
            for mapping in mappings(self.config)[: max(0, panel_top + panel_height - row - 2)]:
                mark = "*" if mapping["name"] in selected_names else " "
                self.add(row, detail_x, f"[{mark}] {mapping['name']} -> {mapping['local']}"[:detail_w])
                row += 1

            footer = "Up/Down: select | Enter: run | q/Esc: back"
            self.add(height - 2, 0, footer[:width], self.accent_attr())
            self.add(height - 1, 0, self.status[:width].ljust(width), curses.A_REVERSE)
            self.screen.refresh()
            ch = self.read_key()
            if ch == curses.KEY_UP or self.key_matches(ch, "k"):
                index = (index - 1) % len(actions)
            elif ch == curses.KEY_DOWN or self.key_matches(ch, "j"):
                index = (index + 1) % len(actions)
            elif ch in (10, 13):
                action = actions[index]
                if action["handler"] is None:
                    self.screen.timeout(250)
                    return
                if action["requires_remote"] and not self.connected:
                    self.status = "Connect to the remote target first"
                    continue
                if action["confirm"] and not self.confirm_sync_action(str(action["label"]), str(action["description"])):
                    self.screen.timeout(-1)
                    self.status = f"Cancelled: {action['label']}"
                    continue
                self.screen.timeout(-1)
                try:
                    action["handler"]()
                except SystemExit as exc:
                    self.status = f"{action['label']}: failed"
                    self.show_message("Action failed", [str(exc)])
                    continue
                if action["label"] in {"Select mappings", "Activate mappings"}:
                    self.screen.timeout(-1)
                    continue
                self.screen.timeout(250)
                return
            elif (self.key_matches(ch, "q") or ch == 27):
                self.screen.timeout(250)
                return

    def confirm_sync_action(self, label: str, description: str) -> bool:
        self.screen.timeout(-1)
        self.draw_confirm(
            "Confirm",
            "This action can change local or remote mapped files.",
            label,
            description,
            "Enter/y: run | n/q/Esc: cancel",
            redraw_background=False,
        )
        while True:
            ch = self.read_key()
            if (self.key_matches(ch, "y") or ch in (10, 13)):
                return True
            if (self.key_matches(ch, "n", "q") or ch in (27, 3)):
                return False

    def store_mapping(self, name: str, role: str, remote: str, local: str, kind: str, push: bool) -> bool:
        existing = {mapping["name"] for mapping in mappings(self.config)}
        if not name:
            self.status = "Mapping add cancelled: empty name"
            return False
        if name in existing:
            self.status = f"Mapping already exists: {name}"
            return False
        try:
            remote = normalize_mapping_path(remote)
            local = normalize_mapping_path(local)
        except ValueError as exc:
            self.status = f"Mapping add failed: {exc}"
            return False
        if kind not in ("file", "directory"):
            self.status = "Mapping add failed: kind must be file or directory"
            return False
        raw_mappings = list(self.config.setdefault("mappings", []))
        raw_mappings.append(
            {
                "name": name,
                "role": role or name,
                "remote": remote,
                "local": local,
                "kind": kind,
                "push": push,
            }
        )
        self.config["mappings"] = raw_mappings
        save_config(self.config)
        selected = read_mapping_selection_if_exists(self.config)
        if name not in selected:
            selected.append(name)
            write_mapping_selection(self.config, selected, echo=False)
        self.status = f"Mapping added: {name}"
        return True

    def fetch_project_tree(self, depth: int) -> list[dict[str, str]]:
        output = capture(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=8",
                remote_spec(self.config),
                project_tree_command(self.config, depth),
            ],
            echo=False,
            timeout=30,
        )
        entries: list[dict[str, str]] = []
        for raw in output.splitlines():
            kind_code, _, path = raw.partition("\t")
            path = path.strip()
            if kind_code == "d" and path:
                entries.append({"path": normalize_mapping_path(path), "kind": "directory"})
        return entries

    def fetch_project_listing(self, directory: str) -> list[dict[str, str]]:
        output = capture(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=8",
                remote_spec(self.config),
                project_listing_command(self.config, directory),
            ],
            echo=False,
            timeout=30,
        )
        entries: list[dict[str, str]] = []
        for raw in output.splitlines():
            kind_code, _, path = raw.partition("\t")
            path = path.strip()
            if not path:
                continue
            kind = "directory" if kind_code == "d" else "file"
            entries.append({"path": normalize_mapping_path(path), "kind": kind})
        return entries

    def add_mapping_screen(self) -> None:
        current_dir = "."
        index = 0
        scroll = 0
        entries: list[dict[str, str]] = []
        error = ""
        need_load = True
        draft_path = ""
        draft_name = ""
        draft_local = ""
        draft_role = ""
        draft_push = True
        self.screen.timeout(-1)
        while True:
            if need_load:
                try:
                    loaded = self.fetch_project_listing(current_dir)
                    parent = str(PurePosixPath(current_dir).parent)
                    if current_dir != ".":
                        loaded.insert(0, {"path": "." if parent in ("", ".") else parent, "kind": "parent"})
                    entries = loaded
                    error = "" if entries else "Directory is empty"
                    index = 0
                    scroll = 0
                    draft_path = ""
                except Exception as exc:
                    error = str(exc)
                need_load = False

            self.screen.erase()
            height, width = self.screen.getmaxyx()
            if height < 18 or width < 80:
                self.add(0, 0, "Terminal is too small. Need at least 80x18.", self.warn_attr())
                self.screen.refresh()
                ch = self.read_key()
                if (self.key_matches(ch, "q") or ch == 27):
                    return
                continue

            left_width = min(64, max(40, width // 2))
            right_left = left_width + 1
            right_width = width - right_left
            panel_top = 3
            panel_height = height - 6
            visible = max(1, panel_height - 2)
            if index < scroll:
                scroll = index
            elif index >= scroll + visible:
                scroll = index - visible + 1

            current_remote = f"{remote_spec(self.config)}:{remote_project_dir(self.config)}"
            display_dir = "~" if current_dir == "." else current_dir
            self.add(0, 0, "Select mappings from remote project browser"[:width], curses.A_BOLD)
            self.add(1, 0, f"Remote: {current_remote} | dir={display_dir}"[:width])
            self.draw_box(panel_top, 0, panel_height, left_width, "Project")
            self.draw_box(panel_top, right_left, panel_height, right_width, "Mapping")

            if error:
                self.add(panel_top + 1, 2, error[: left_width - 4], self.error_attr())
            mapped_paths = {
                normalize_mapping_path(str(mapping.get("remote", "")))
                for mapping in self.config.get("mappings", [])
                if isinstance(mapping, dict) and str(mapping.get("remote", "")).strip()
            }
            selected_names = set(read_mapping_selection_if_exists(self.config))
            selected_paths = {
                normalize_mapping_path(str(mapping.get("remote", "")))
                for mapping in self.config.get("mappings", [])
                if isinstance(mapping, dict)
                and str(mapping.get("name", "")) in selected_names
                and str(mapping.get("remote", "")).strip()
            }
            self.draw_scrollbar(panel_top + 1, left_width - 2, visible, len(entries), visible, scroll)
            for offset, entry in enumerate(entries[scroll : scroll + visible]):
                row = panel_top + 1 + offset
                item_index = scroll + offset
                name = "../" if entry["kind"] == "parent" else PurePosixPath(entry["path"]).name
                mark = "S" if entry["path"] in selected_paths else "*" if entry["path"] in mapped_paths else " "
                if entry["kind"] in ("directory", "parent"):
                    label = f"{mark} [d] {name}/"
                else:
                    label = f"{mark} [f] {name}"
                attr = self.selected_attr() if item_index == index else 0
                self.add(row, 2, label[: left_width - 4].ljust(left_width - 4), attr)

            current = entries[index] if entries else {"path": "", "kind": "directory"}
            if current["path"] != draft_path:
                draft_path = current["path"]
                draft_name = self.mapping_name_from_path(current["path"])
                draft_local = current["path"]
                draft_role = draft_name
                draft_push = True
            detail_x = right_left + 2
            detail_w = right_width - 4
            row = panel_top + 2
            current_path = current["path"] or current_dir
            row = self.draw_wrapped(row, detail_x, detail_w, current_path, curses.A_BOLD, max_lines=3)
            row += 1
            kind = "directory" if current["kind"] == "parent" else current["kind"]
            row = self.draw_label_value_wrapped(row, detail_x, detail_w, "kind", kind, max_lines=1)
            row = self.draw_label_value_wrapped(row, detail_x, detail_w, "name", draft_name, max_lines=2)
            row = self.draw_label_value_wrapped(row, detail_x, detail_w, "local path", draft_local, max_lines=3)
            row = self.draw_label_value_wrapped(row, detail_x, detail_w, "role", draft_role, max_lines=3)
            row = self.draw_label_value_wrapped(row, detail_x, detail_w, "push", "yes" if draft_push else "no", max_lines=1)
            row += 1
            mapped = current["path"] in mapped_paths
            selected = current["path"] in selected_paths
            row = self.draw_label_value_wrapped(row, detail_x, detail_w, "mapped", "selected" if selected else "yes" if mapped else "no", max_lines=1)
            row += 1
            row = self.draw_wrapped(row, detail_x, detail_w, "Enter opens directories. Space toggles the selected path as a mapping. Use n/l/r/p before adding to edit name, local path, role, or push permission.", max_lines=4)

            footer = "S selected mapping | * mapped | Up/Down: select | Enter: open dir | Space: toggle | n/l/r/p: edit fields | q/Esc: back"
            self.add(height - 2, 0, footer[:width], self.accent_attr())
            self.add(height - 1, 0, self.status[:width].ljust(width), curses.A_REVERSE)
            self.screen.refresh()
            ch = self.read_key()
            if (ch == curses.KEY_UP or self.key_matches(ch, "k")) and entries:
                index = (index - 1) % len(entries)
            elif (ch == curses.KEY_DOWN or self.key_matches(ch, "j")) and entries:
                index = (index + 1) % len(entries)
            elif ch in (10, 13) and entries:
                if current["kind"] in ("directory", "parent"):
                    current_dir = current["path"]
                    self.status = f"Loading {current_dir}..."
                    need_load = True
                else:
                    self.status = "Space toggles the selected file mapping"
            elif ch == ord(" ") and entries:
                if current["path"] in mapped_paths:
                    self.remove_mapping_by_remote_path(current["path"])
                else:
                    self.save_mapping_from_tree(current, draft_name, draft_local, draft_role, draft_push)
                draft_path = ""
            elif self.key_matches(ch, "n") and entries:
                name = self.prompt("Mapping name", draft_name).strip()
                if name:
                    draft_name = name
            elif self.key_matches(ch, "l") and entries:
                draft_local = self.prompt("Local path", draft_local)
            elif self.key_matches(ch, "r") and entries:
                draft_role = self.prompt("Role", draft_role)
            elif self.key_matches(ch, "p") and entries:
                push_raw = self.prompt("Allow push: yes or no", "yes" if draft_push else "no").strip().lower()
                if push_raw not in ("yes", "no", "y", "n", "true", "false", "1", "0"):
                    self.status = "Mapping add failed: push must be yes or no"
                    continue
                draft_push = push_raw in ("yes", "y", "true", "1")
            elif (self.key_matches(ch, "q") or ch == 27):
                return

    def mapping_name_from_path(self, path: str) -> str:
        clean = path.strip("/").replace("/", "-").replace("_", "-")
        clean = "-".join(part for part in clean.split("-") if part)
        return clean or "mapping"

    def save_mapping_from_tree(self, entry: dict[str, str], name: str, local: str, role: str, push: bool) -> bool:
        return self.store_mapping(
            name=name.strip(),
            role=role.strip() or name.strip(),
            remote=entry["path"],
            local=local,
            kind="directory" if entry["kind"] == "parent" else entry["kind"],
            push=push,
        )

    def remove_mapping_by_remote_path(self, remote_path: str) -> bool:
        try:
            target = normalize_mapping_path(remote_path)
        except ValueError as exc:
            self.status = f"Mapping remove failed: {exc}"
            return False
        raw_mappings = [mapping for mapping in self.config.get("mappings", []) if isinstance(mapping, dict)]
        removed_names = [
            str(mapping.get("name", ""))
            for mapping in raw_mappings
            if normalize_mapping_path(str(mapping.get("remote", ""))) == target
        ]
        if not removed_names:
            self.status = f"Mapping not found: {target}"
            return False
        removed = set(removed_names)
        self.config["mappings"] = [
            mapping
            for mapping in raw_mappings
            if normalize_mapping_path(str(mapping.get("remote", ""))) != target
        ]
        save_config(self.config)
        selected = [name for name in read_mapping_selection_if_exists(self.config) if name not in removed]
        write_mapping_selection(self.config, selected, echo=False)
        self.status = f"Mapping removed: {', '.join(removed_names)}"
        return True

    def delete_mapping_screen(self) -> None:
        all_mappings = mappings(self.config)
        if not all_mappings:
            self.status = "No mappings to delete"
            return
        index = 0
        self.screen.timeout(-1)
        while True:
            self.screen.erase()
            height, width = self.screen.getmaxyx()
            if height < 16 or width < 80:
                self.add(0, 0, "Terminal is too small. Need at least 80x16.", self.warn_attr())
                self.screen.refresh()
                ch = self.read_key()
                if (self.key_matches(ch, "q") or ch == 27):
                    return
                continue

            left_width = min(44, max(34, width // 3))
            right_left = left_width + 1
            right_width = width - right_left
            panel_top = 3
            panel_height = height - 6
            self.add(0, 0, "Delete mapping"[:width], curses.A_BOLD)
            self.add(1, 0, "Delete removes the mapping from the local Moulin client config only."[:width])
            self.draw_box(panel_top, 0, panel_height, left_width, "Mappings")
            self.draw_box(panel_top, right_left, panel_height, right_width, "Details")

            visible = max(1, panel_height - 2)
            scroll = min(max(0, index - visible + 1), max(0, len(all_mappings) - visible))
            for offset, mapping in enumerate(all_mappings[scroll : scroll + visible]):
                row = panel_top + 1 + offset
                item_index = scroll + offset
                attr = self.selected_attr() if item_index == index else 0
                self.add(row, 2, f"{item_index + 1}. {mapping['name']}"[: left_width - 4].ljust(left_width - 4), attr)

            current = all_mappings[index]
            detail_x = right_left + 2
            detail_w = right_width - 4
            row = panel_top + 2
            self.add(row, detail_x, current["name"][:detail_w], curses.A_BOLD)
            row += 2
            row = self.draw_wrapped(row, detail_x, detail_w, current["role"], max_lines=3)
            row += 1
            self.add(row, detail_x, f"kind:   {current['kind']}"[:detail_w])
            row += 1
            self.add(row, detail_x, f"push:   {'yes' if current['push'] else 'no'}"[:detail_w])
            row += 2
            self.add(row, detail_x, f"remote: {current['remote']}"[:detail_w])
            row += 1
            self.add(row, detail_x, f"local:  {current['local']}"[:detail_w])

            footer = "Up/Down: select | Enter/d: delete | q/Esc: back"
            self.add(height - 2, 0, footer[:width], self.accent_attr())
            self.add(height - 1, 0, self.status[:width].ljust(width), curses.A_REVERSE)
            self.screen.refresh()
            ch = self.read_key()
            if ch == curses.KEY_UP or self.key_matches(ch, "k"):
                index = (index - 1) % len(all_mappings)
            elif ch == curses.KEY_DOWN or self.key_matches(ch, "j"):
                index = (index + 1) % len(all_mappings)
            elif ch in (10, 13) or self.key_matches(ch, "d"):
                if not self.confirm_sync_action("Delete mapping", f"Remove mapping {current['name']} from the client config."):
                    self.screen.timeout(-1)
                    self.status = "Mapping delete cancelled"
                    continue
                name = current["name"]
                self.config["mappings"] = [
                    raw for raw in self.config.get("mappings", []) if str(raw.get("name", "")).strip() != name
                ]
                save_config(self.config)
                selected = [item for item in read_mapping_selection_if_exists(self.config) if item != name]
                write_mapping_selection(self.config, selected, echo=False)
                self.status = f"Mapping deleted: {name}"
                return
            elif (self.key_matches(ch, "q") or ch == 27):
                return

    def select_mappings_screen(self) -> None:
        all_mappings = mappings(self.config)
        selected = set(read_mapping_selection_if_exists(self.config))
        index = 0
        scroll = 0
        self.screen.timeout(-1)
        while True:
            self.screen.erase()
            height, width = self.screen.getmaxyx()
            if height < 16 or width < 80:
                self.add(0, 0, "Terminal is too small. Need at least 80x16.", self.warn_attr())
                self.screen.refresh()
                ch = self.read_key()
                if (self.key_matches(ch, "q") or ch == 27):
                    self.screen.timeout(250)
                    return
                continue

            left_width = min(44, max(34, width // 3))
            right_left = left_width + 1
            right_width = width - right_left
            panel_top = 3
            panel_height = height - 6
            visible = max(1, panel_height - 2)
            if index < scroll:
                scroll = index
            elif index >= scroll + visible:
                scroll = index - visible + 1

            self.add(0, 0, "Activate mappings"[:width], curses.A_BOLD)
            self.add(1, 0, f"Remote: {remote_spec(self.config)}:{remote_project_dir(self.config)}"[:width])
            self.draw_box(panel_top, 0, panel_height, left_width, "Mappings")
            self.draw_box(panel_top, right_left, panel_height, right_width, "Details")

            if not all_mappings:
                self.add(panel_top + 1, 2, "No mappings configured."[: left_width - 4], self.warn_attr())
                detail_x = right_left + 2
                detail_w = right_width - 4
                row = panel_top + 2
                self.add(row, detail_x, "No mappings yet"[:detail_w], curses.A_BOLD)
                row += 2
                row = self.draw_wrapped(row, detail_x, detail_w, "Use Select mappings to add file or directory mappings from the remote project browser.", max_lines=4)
                footer = "a: select mappings | q/Esc: back"
                self.add(height - 2, 0, footer[:width], self.accent_attr())
                self.add(height - 1, 0, self.status[:width].ljust(width), curses.A_REVERSE)
                self.screen.refresh()
                ch = self.read_key()
                if self.key_matches(ch, "a"):
                    self.add_mapping_screen()
                    all_mappings = mappings(self.config)
                    selected = set(read_mapping_selection_if_exists(self.config))
                    index = 0
                    scroll = 0
                elif (self.key_matches(ch, "q") or ch in (27, 10, 13)):
                    self.status = "Activate mappings closed"
                    self.screen.timeout(250)
                    return
                continue

            for offset, mapping in enumerate(all_mappings[scroll : scroll + visible]):
                row = panel_top + 1 + offset
                selected_mark = "*" if mapping["name"] in selected else " "
                push = "push" if mapping["push"] else "pull-only"
                label = f"[{selected_mark}] {mapping['name']} ({mapping['kind']}, {push})"
                attr = self.selected_attr() if scroll + offset == index else 0
                self.add(row, 2, label[: left_width - 4].ljust(left_width - 4), attr)

            current = all_mappings[index]
            detail_x = right_left + 2
            detail_w = right_width - 4
            row = panel_top + 2
            self.add(row, detail_x, current["name"][:detail_w], curses.A_BOLD)
            row += 2
            row = self.draw_wrapped(row, detail_x, detail_w, current["role"], max_lines=3)
            row += 1
            self.add(row, detail_x, f"kind:   {current['kind']}"[:detail_w])
            row += 1
            self.add(row, detail_x, f"push:   {'yes' if current['push'] else 'no'}"[:detail_w])
            row += 2
            self.add(row, detail_x, "remote:", self.accent_attr())
            row += 1
            row = self.draw_wrapped(row, detail_x, detail_w, current["remote"], max_lines=3)
            row += 1
            self.add(row, detail_x, "local:", self.accent_attr())
            row += 1
            row = self.draw_wrapped(row, detail_x, detail_w, str(local_project_dir(self.config) / current["local"]), max_lines=3)
            row += 1
            self.add(row, detail_x, f"selected: {len(selected)}/{len(all_mappings)}"[:detail_w])

            footer = "Up/Down: select | Space: activate/deactivate | d: delete | a: all | n: none | Enter/q/Esc: back"
            self.add(height - 2, 0, footer[:width], self.accent_attr())
            self.add(height - 1, 0, self.status[:width].ljust(width), curses.A_REVERSE)
            self.screen.refresh()
            ch = self.read_key()
            if ch == curses.KEY_UP or self.key_matches(ch, "k"):
                index = (index - 1) % len(all_mappings)
            elif ch == curses.KEY_DOWN or self.key_matches(ch, "j"):
                index = (index + 1) % len(all_mappings)
            elif ch == ord(" "):
                name = all_mappings[index]["name"]
                if name in selected:
                    selected.remove(name)
                    self.status = f"Mapping deactivated: {name}"
                else:
                    selected.add(name)
                    self.status = f"Mapping activated: {name}"
                write_mapping_selection(
                    self.config,
                    [mapping["name"] for mapping in all_mappings if mapping["name"] in selected],
                    echo=False,
                )
            elif self.key_matches(ch, "d"):
                current = all_mappings[index]
                if not self.confirm_sync_action("Delete mapping", f"Remove mapping {current['name']} from the client config."):
                    self.screen.timeout(-1)
                    self.status = "Mapping delete cancelled"
                    continue
                name = current["name"]
                self.config["mappings"] = [
                    raw for raw in self.config.get("mappings", []) if str(raw.get("name", "")).strip() != name
                ]
                selected.discard(name)
                save_config(self.config)
                all_mappings = mappings(self.config)
                write_mapping_selection(
                    self.config,
                    [mapping["name"] for mapping in all_mappings if mapping["name"] in selected],
                    echo=False,
                )
                if all_mappings:
                    index = min(index, len(all_mappings) - 1)
                    scroll = min(scroll, max(0, len(all_mappings) - visible))
                else:
                    index = 0
                    scroll = 0
                self.screen.timeout(-1)
                self.status = f"Mapping deleted: {name}"
            elif self.key_matches(ch, "a"):
                selected = {mapping["name"] for mapping in all_mappings}
                write_mapping_selection(self.config, [mapping["name"] for mapping in all_mappings], echo=False)
                self.status = "All mappings activated"
            elif self.key_matches(ch, "n"):
                selected = set()
                write_mapping_selection(self.config, [], echo=False)
                self.status = "All mappings deactivated"
            elif ch in (10, 13):
                self.status = "Activate mappings closed"
                self.screen.timeout(250)
                return
            elif (self.key_matches(ch, "q") or ch == 27):
                self.status = "Activate mappings closed"
                self.screen.timeout(250)
                return

    def open_remote_shell(self) -> None:
        curses.def_prog_mode()
        curses.endwin()
        try:
            print()
            print("Moulin remote shell")
            print(f"remote: {remote_spec(self.config)}")
            print(f"cwd: {remote_project_dir(self.config)}")
            print("Return to TUI: type 'exit' or press Ctrl-D.")
            print()
            command = f"cd {shlex.quote(remote_project_dir(self.config))} && exec bash -l"
            rc = subprocess.call(["ssh", "-t", remote_spec(self.config), command])
            self.last_exit = rc
            input("Shell exited. Press Enter to return to Moulin client...")
            self.status = f"Remote shell closed: exit {rc}"
        finally:
            curses.reset_prog_mode()
            self.screen.keypad(True)
            self.screen.timeout(250)

    def draw_command(
        self,
        title: str,
        command: str,
        output: list[str],
        view: dict[str, int | bool],
        *,
        running: bool,
        stopped: bool,
    ) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        state = "RUNNING" if running else "DONE"
        if stopped:
            state = "STOPPING" if running else "STOPPED"
        self.add(0, 0, f"{title} [{state}]"[:width], curses.A_BOLD)
        self.add(1, 0, f"remote: {remote_spec(self.config)}:{remote_project_dir(self.config)}"[:width])
        command_box_height = 5
        self.draw_box(3, 0, command_box_height, width, "Command")
        self.draw_wrapped(4, 2, max(1, width - 4), command, max_lines=command_box_height - 2)
        output_top = 9
        output_height = max(3, height - output_top - 2)
        self.draw_box(output_top - 1, 0, output_height + 1, width, "Output")
        visible = max(0, output_height - 2)
        scroll = self.clamp_command_scroll(output, view)
        shown = output[scroll : scroll + visible]
        for index, line in enumerate(shown):
            attr = self.accent_attr() if line.startswith("== ") else 0
            self.add(output_top + index, 2, line[: max(1, width - 4)], attr)
        if output:
            first = min(len(output), scroll + 1)
            last = min(len(output), scroll + len(shown))
            follow = " follow" if view.get("follow") else ""
            counter = f"lines {first}-{last}/{len(output)}{follow}"
            self.add(output_top - 1, max(1, width - len(counter) - 2), counter[: max(1, width - 4)], self.accent_attr())
        hint = (
            "Up/Down/PgUp/PgDn/Home/End: scroll | q/Esc/Ctrl-C: stop command"
            if running
            else "Up/Down/PgUp/PgDn/Home/End: scroll | q/Esc/Enter: return"
        )
        self.add(height - 2, 0, hint[:width], self.warn_attr() if running else self.accent_attr())
        self.add(height - 1, 0, self.status[:width].ljust(width), curses.A_REVERSE)
        self.screen.refresh()

    def wait_message(self, message: str) -> None:
        height, width = self.screen.getmaxyx()
        self.add(height - 1, 0, message[:width].ljust(width), curses.A_REVERSE)
        self.screen.timeout(-1)
        while True:
            ch = self.read_key()
            if (self.key_matches(ch, "q") or ch in (27, 10, 13)):
                return

    def show_message(self, title: str, lines: list[str]) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        self.add(0, 0, title[:width], curses.A_BOLD)
        for index, line in enumerate(lines[: max(0, height - 3)]):
            attr = self.warn_attr() if index == 0 else 0
            self.add(index + 2, 0, line[:width], attr)
        self.add(height - 2, 0, "q/Esc/Enter: return to menu"[:width], self.accent_attr())
        self.screen.refresh()
        self.wait_message("q/Esc/Enter: return to menu")
        self.screen.timeout(250)

    def remote_project_config_ready(self) -> bool:
        if not self.connected:
            self.status = "connect to the remote target first"
            return False
        if not remote_has_project_dir(self.config):
            self.status = "select remote project directory first"
            return False
        return True

    def remote_git_tracked_files(self) -> list[str]:
        script = f"cd {shlex.quote(remote_project_dir(self.config))} && git ls-files"
        output = capture(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", remote_spec(self.config), script], echo=False, timeout=20)
        return [line.strip() for line in output.splitlines() if line.strip()]

    def remote_root_yaml_candidates(self) -> list[str]:
        return [
            path
            for path in self.remote_git_tracked_files()
            if "/" not in path and path.lower().endswith((".yaml", ".yml"))
        ]

    def remote_dockerfile_candidates(self) -> list[str]:
        candidates = []
        for path in self.remote_git_tracked_files():
            name = PurePosixPath(path).name.lower()
            if name == "dockerfile" or name.startswith("dockerfile.") or name.endswith(".dockerfile"):
                candidates.append(path)
        return candidates

    def draw_loading_message(self, title: str, message: str) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        self.add(0, 0, title[:width], curses.A_BOLD)
        self.add(2, 0, message[:width], self.accent_attr())
        self.add(height - 1, 0, self.status[:width].ljust(width), curses.A_REVERSE)
        self.screen.refresh()

    def validate_moulin_manifest_candidate(self, path: str) -> tuple[bool, str]:
        if yaml is None or MoulinYamlLoader is None:
            return False, "PyYAML is not installed locally"
        try:
            text = remote_read_project_file(self.config, path)
        except Exception as exc:
            return False, str(exc)
        tags = moulin_yaml_tags(text)
        try:
            data = yaml.load(text, Loader=MoulinYamlLoader)
        except Exception as exc:
            return False, f"YAML parse failed: {exc}"
        if not isinstance(data, dict):
            return False, "not a YAML mapping"
        markers = moulin_manifest_markers(data)
        if not is_moulin_manifest_data(data):
            detail = ", ".join(markers) if markers else "no Moulin manifest markers"
            return False, detail
        detail_parts = [", ".join(markers)]
        if tags:
            detail_parts.append("tags " + ", ".join(tags))
        return True, "; ".join(detail_parts)

    def validate_dockerfile_candidate(self, path: str) -> tuple[bool, str]:
        try:
            text = remote_read_project_file(self.config, path)
        except Exception as exc:
            return False, str(exc)
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            return (stripped.upper().startswith("FROM "), stripped if stripped.upper().startswith("FROM ") else "first instruction is not FROM")
        return False, "empty file"

    def select_remote_candidate_screen(
        self,
        title: str,
        candidates: list[dict[str, Any]],
        validator: Callable[[str], tuple[bool, str]],
    ) -> str | None:
        index = 0
        self.screen.timeout(-1)
        while True:
            self.screen.erase()
            height, width = self.screen.getmaxyx()
            if height < 18 or width < 80:
                self.add(0, 0, "Terminal is too small. Need at least 80x18.", self.warn_attr())
                self.screen.refresh()
                ch = self.read_key()
                if (self.key_matches(ch, "q") or ch == 27):
                    return None
                continue
            self.add(0, 0, title[:width], curses.A_BOLD)
            self.add(1, 0, f"Remote: {remote_spec(self.config)}:{remote_project_dir(self.config)}"[:width])
            self.draw_box(3, 0, height - 6, width, "Candidates")
            visible = max(1, height - 8)
            if not candidates:
                self.add(4, 2, "No candidates found."[: width - 4], self.warn_attr())
            else:
                index = min(index, len(candidates) - 1)
                scroll = min(max(0, index - visible + 1), max(0, len(candidates) - visible))
                for offset, candidate in enumerate(candidates[scroll : scroll + visible]):
                    item_index = scroll + offset
                    valid = candidate.get("valid")
                    marker = "?" if valid is None else ("ok" if valid else "bad")
                    path = str(candidate.get("path", ""))
                    detail = str(candidate.get("detail", ""))
                    label = f"{marker:3} {path}  {detail}".strip()
                    if item_index == index and valid is not False:
                        attr = self.selected_attr()
                    elif item_index == index:
                        attr = self.selected_disabled_attr()
                    elif valid is not False:
                        attr = 0
                    else:
                        attr = self.disabled_attr()
                    self.add(4 + offset, 2, self.fit_text(label, width - 4).ljust(width - 4), attr)
            footer = "Up/Down: select | Enter: validate/select | q/Esc: back"
            self.add(height - 2, 0, footer[:width], self.accent_attr())
            self.add(height - 1, 0, self.status[:width].ljust(width), curses.A_REVERSE)
            self.screen.refresh()
            ch = self.read_key()
            if (ch == curses.KEY_UP or self.key_matches(ch, "k")) and candidates:
                index = (index - 1) % len(candidates)
            elif (ch == curses.KEY_DOWN or self.key_matches(ch, "j") or ch == ord("\t")) and candidates:
                index = (index + 1) % len(candidates)
            elif ch in (10, 13) and candidates:
                candidate = candidates[index]
                if candidate.get("valid") is None:
                    path = str(candidate.get("path", ""))
                    self.draw_loading_message(title, f"Validating {path}...")
                    valid, detail = validator(path)
                    candidate["valid"] = valid
                    candidate["detail"] = detail
                    self.status = detail
                if candidate.get("valid") is True:
                    return str(candidate.get("path", ""))
                self.status = str(candidate.get("detail", "invalid candidate"))
            elif (self.key_matches(ch, "q") or ch == 27):
                return None

    def select_remote_moulin_manifest(self) -> None:
        if not self.remote_project_config_ready():
            return
        try:
            self.draw_loading_message("Select Moulin manifest", "Searching tracked root YAML files...")
            paths = self.remote_root_yaml_candidates()
        except Exception as exc:
            self.status = f"Manifest search failed: {exc}"
            return
        candidates = [{"path": path, "valid": None, "detail": "press Enter to validate"} for path in paths[:200]]
        selected = self.select_remote_candidate_screen("Select Moulin manifest", candidates, self.validate_moulin_manifest_candidate)
        if not selected:
            self.status = "Moulin manifest unchanged"
            return
        active_project(self.config)["moulin_manifest"] = selected
        sync_active_project(self.config)
        MANIFEST_CACHE.clear()
        self.build_params = default_build_params(self.config)
        self.reset_preflight()
        save_config(self.config)
        self.status = f"Moulin manifest: {selected}"

    def select_remote_dockerfile(self) -> None:
        if not self.remote_project_config_ready():
            return
        try:
            self.draw_loading_message("Select Dockerfile", "Searching tracked Dockerfiles...")
            paths = self.remote_dockerfile_candidates()
        except Exception as exc:
            self.status = f"Dockerfile search failed: {exc}"
            return
        candidates = [{"path": path, "valid": None, "detail": "press Enter to validate"} for path in paths[:200]]
        selected = self.select_remote_candidate_screen("Select Dockerfile", candidates, self.validate_dockerfile_candidate)
        if not selected:
            self.status = "Dockerfile unchanged"
            return
        active_project(self.config)["dockerfile"] = selected
        sync_active_project(self.config)
        self.reset_preflight()
        save_config(self.config)
        self.status = f"Dockerfile: {selected}"

    def project_configurations_screen(self) -> None:
        project_index = 0
        project_index_initialized = False
        field_index = 0
        focus = "projects"
        editing_key = ""
        editing_value = ""
        editing_cursor = 0
        editing_cursor_yx: tuple[int, int] | None = None
        self.screen.timeout(-1)
        while True:
            editing_cursor_yx = None
            params = moulin_parameters(self.config)
            self.screen.clear()
            height, width = self.screen.getmaxyx()
            if height < 22 or width < 90:
                self.add(0, 0, "Terminal is too small. Need at least 90x22.", self.warn_attr())
                self.screen.refresh()
                ch = self.read_key()
                if (self.key_matches(ch, "q") or ch == 27):
                    self.screen.timeout(250)
                    return
                continue

            project = active_project(self.config)
            projects = [item for item in self.config.get("projects", []) if isinstance(item, dict)]
            if not project_index_initialized:
                project_index = self.active_project_index(projects)
                focus = "projects"
                project_index_initialized = True
            project_index = min(project_index, max(0, len(projects) - 1))
            selected_project = projects[project_index] if projects else None
            panel_top = 3
            panel_height = height - 6
            self.add(0, 0, "Project configurations"[:width], curses.A_BOLD)
            active_name = str(project.get("label") or project.get("name") or "<none>")
            self.add(1, 0, self.fit_text(f"Active: {active_name} | Remote: {remote_spec(self.config)}:{remote_project_dir(self.config)}", width))
            self.add(2, 0, f"Focus: {'project list' if focus == 'projects' else 'fields'}"[:width], self.accent_attr())
            self.draw_box(panel_top, 0, panel_height, width, "Projects")

            table_w = width - 4
            detail_x = 2
            detail_w = width - 4
            fields: list[dict[str, Any]] = []
            if selected_project is not None:
                fields = [
                    {"label": "Profile name", "key": "name", "kind": "text"},
                    {"label": "Display label", "key": "label", "kind": "text"},
                    {"label": "Remote project dir", "key": "project_dir", "kind": "remote_dir"},
                    {"label": "Local overlay dir", "key": "local_project_dir", "kind": "text"},
                    {"label": "Project Git URL", "key": "git_url", "kind": "text"},
                    {"label": "Git branch/ref", "key": "git_ref", "kind": "git_ref"},
                ]
                fields.extend({"label": str(param["name"]), "key": f"param:{param['name']}", "kind": "param", "param": param} for param in params)
                fields.extend(
                    [
                        {"label": "Moulin manifest", "key": "moulin_manifest", "kind": "manifest"},
                        {"label": "Dockerfile", "key": "dockerfile", "kind": "dockerfile"},
                        {"label": "Build targets", "key": "targets", "kind": "targets"},
                        {"label": "Docker image name", "key": "docker_image", "kind": "text"},
                    ]
                )
                field_index = min(field_index, max(0, len(fields) - 1))
            else:
                field_index = 0

            min_detail_rows = 2 + min(len(fields), 11) + 3
            visible_projects = max(1, min(max(1, len(projects)), panel_height - min_detail_rows))
            project_scroll = min(max(0, project_index - visible_projects + 1), max(0, len(projects) - visible_projects))
            table_y = panel_top + 1
            self.add(table_y, 2, self.fit_text("A Name               Manifest                         Targets", table_w), self.accent_attr())
            if not projects:
                self.add(table_y + 1, 2, "No projects configured. Press 'a' to add one."[:table_w], self.disabled_attr())
            else:
                for offset, profile in enumerate(projects[project_scroll : project_scroll + visible_projects]):
                    item_index = project_scroll + offset
                    is_active = str(profile.get("name", "")) == str(self.config.get("active_project", ""))
                    active_mark = "*" if is_active else " "
                    manifest = str(profile.get("moulin_manifest", "")) or "<not set>"
                    targets = str(profile.get("targets", "")) or "<not set>"
                    active_suffix = "  ACTIVE" if is_active else ""
                    text = f"{active_mark} {str(profile.get('name', ''))[:18]:18} {manifest[:30]:30} {targets}{active_suffix}"
                    selected_row = focus == "projects" and item_index == project_index
                    if selected_row and is_active:
                        attr = self.selected_active_attr()
                    elif selected_row:
                        attr = self.selected_attr()
                    elif is_active:
                        attr = self.active_row_attr()
                    else:
                        attr = 0
                    self.add(table_y + 1 + offset, 2, self.fit_text(text, table_w).ljust(table_w), attr)

            row = table_y + visible_projects + 2
            if len(projects) > visible_projects:
                self.add(row, detail_x, f"{project_index + 1}/{len(projects)} projects"[:detail_w], self.disabled_attr())
                row += 1
            if selected_project is None:
                self.add(row, detail_x, "Selected project: <none>"[:detail_w], self.disabled_attr())
            else:
                self.add(row, detail_x, "Fields:", self.accent_attr())
                row += 1
                visible_fields = max(0, panel_top + panel_height - row - 5)
                field_scroll = min(max(0, field_index - visible_fields + 1), max(0, len(fields) - visible_fields))
                for visible_offset, field in enumerate(fields[field_scroll : field_scroll + visible_fields]):
                    item_index = field_scroll + visible_offset
                    label = str(field["label"])
                    key = str(field["key"])
                    is_editing = focus == "fields" and key == editing_key
                    raw_value = editing_value if is_editing else self.project_field_value(selected_project, field)
                    value = raw_value or "<not set>"
                    enabled = self.project_field_enabled(field, selected_project)
                    selected = focus == "fields" and item_index == field_index
                    if is_editing:
                        attr = self.editing_attr()
                    elif selected and enabled:
                        attr = self.selected_attr()
                    elif selected:
                        attr = self.selected_disabled_attr()
                    elif not enabled:
                        attr = self.disabled_attr()
                    else:
                        attr = 0
                    text = f"{label}:".ljust(22) + value
                    self.add(row, detail_x, self.fit_text(text, detail_w).ljust(detail_w), attr)
                    if is_editing:
                        cursor_x = min(detail_x + 22 + editing_cursor, detail_x + detail_w - 1)
                        editing_cursor_yx = (row, cursor_x)
                    row += 1
                if row < height - 3 and fields and focus == "fields":
                    field = fields[field_index]
                    if editing_key:
                        self.add(row, detail_x, "Enter: save | Esc: cancel | Left/Right/Home/End: move cursor"[:detail_w], self.accent_attr())
                    else:
                        enabled = self.project_field_enabled(field, selected_project)
                        message = self.project_field_hint(field, selected_project) if enabled else self.project_field_disabled_reason(field, selected_project)
                        max_lines = max(1, height - 3 - row)
                        self.draw_wrapped(row, detail_x, detail_w, message, self.accent_attr() if enabled else self.disabled_attr(), max_lines=max_lines)

            footer = "Left/Right: projects/fields | Enter: edit/open/save | a: add | d: delete | s: set active | Esc: projects/back | q: back"
            self.add(height - 2, 0, footer[:width], self.accent_attr())
            self.add(height - 1, 0, self.status[:width].ljust(width), curses.A_REVERSE)
            if editing_cursor_yx is not None:
                self.set_cursor(True)
                try:
                    self.screen.move(*editing_cursor_yx)
                except curses.error:
                    pass
            else:
                self.set_cursor(False)
            self.screen.timeout(-1)
            self.screen.refresh()
            ch = self.read_key()
            if ch == -1:
                continue
            if editing_key:
                if ch in (10, 13):
                    self.apply_project_inline_value(selected_project, editing_key, editing_value)
                    editing_key = ""
                    editing_value = ""
                    editing_cursor = 0
                    self.set_cursor(False)
                elif ch == 27:
                    editing_key = ""
                    editing_value = ""
                    editing_cursor = 0
                    self.status = "Edit cancelled"
                    self.set_cursor(False)
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    if editing_cursor > 0:
                        editing_value = editing_value[: editing_cursor - 1] + editing_value[editing_cursor:]
                        editing_cursor -= 1
                elif ch == curses.KEY_DC:
                    if editing_cursor < len(editing_value):
                        editing_value = editing_value[:editing_cursor] + editing_value[editing_cursor + 1:]
                elif ch == curses.KEY_LEFT:
                    editing_cursor = max(0, editing_cursor - 1)
                elif ch == curses.KEY_RIGHT:
                    editing_cursor = min(len(editing_value), editing_cursor + 1)
                elif ch == curses.KEY_HOME:
                    editing_cursor = 0
                elif ch == curses.KEY_END:
                    editing_cursor = len(editing_value)
                elif char := self.key_text(ch):
                    editing_value = editing_value[:editing_cursor] + char + editing_value[editing_cursor:]
                    editing_cursor += 1
                continue
            self.set_cursor(False)
            if ch == curses.KEY_LEFT or self.key_matches(ch, "h"):
                focus = "projects"
            elif ch == curses.KEY_RIGHT or self.key_matches(ch, "l"):
                if selected_project is None:
                    self.status = "Add a project first"
                else:
                    focus = "fields"
            elif ch == curses.KEY_UP or self.key_matches(ch, "k"):
                if focus == "fields" and fields:
                    field_index = (field_index - 1) % len(fields)
                elif projects:
                    project_index = (project_index - 1) % len(projects)
            elif (ch == curses.KEY_DOWN or self.key_matches(ch, "j") or ch == ord("\t")):
                if focus == "fields" and fields:
                    field_index = (field_index + 1) % len(fields)
                elif projects:
                    project_index = (project_index + 1) % len(projects)
            elif ch in (10, 13):
                if selected_project is None:
                    self.status = "Add a project first"
                elif focus == "projects":
                    focus = "fields"
                else:
                    field = fields[field_index]
                    if not self.project_field_enabled(field, selected_project):
                        self.status = self.project_field_disabled_reason(field, selected_project)
                    elif field["kind"] == "manifest":
                        self.select_remote_moulin_manifest()
                    elif field["kind"] == "dockerfile":
                        self.select_remote_dockerfile()
                    elif field["kind"] == "remote_dir":
                        self.edit_project_remote_dir(selected_project)
                    elif field["kind"] == "git_ref":
                        self.edit_project_git_ref(selected_project)
                    elif field["kind"] == "targets":
                        self.select_build_targets_screen()
                    elif field["kind"] == "param":
                        self.cycle_parameter(field["param"])
                        self.save_current_build_settings()
                    else:
                        editing_key = str(field["key"])
                        editing_value = self.project_field_value(selected_project, field)
                        editing_cursor = len(editing_value)
                        self.status = f"Editing {field['label']}"
            elif self.key_matches(ch, "a"):
                self.add_project_profile()
                projects = [item for item in self.config.get("projects", []) if isinstance(item, dict)]
                project_index = self.active_project_index(projects)
                focus = "fields" if projects else "projects"
            elif self.key_matches(ch, "d"):
                if selected_project is None:
                    self.status = "No project selected"
                else:
                    self.delete_project_profile(selected_project)
                    projects = [item for item in self.config.get("projects", []) if isinstance(item, dict)]
                    project_index = min(project_index, max(0, len(projects) - 1))
                    focus = "projects"
            elif self.key_matches(ch, "s"):
                if selected_project is None:
                    self.status = "No project selected"
                else:
                    self.set_active_project(selected_project)
            elif ch == 27 and focus == "fields":
                focus = "projects"
                self.status = "Project list focused"
            elif (self.key_matches(ch, "q") or ch == 27):
                save_config(self.config)
                self.screen.timeout(250)
                return

    def active_project_index(self, projects: list[dict[str, Any]]) -> int:
        active = str(self.config.get("active_project", ""))
        for index, project in enumerate(projects):
            if str(project.get("name", "")) == active:
                return index
        return 0

    def set_active_project(self, project: dict[str, Any]) -> None:
        name = str(project.get("name", ""))
        if str(self.config.get("active_project", "")) == name:
            self.status = "selected project is already active"
            return
        self.config["active_project"] = name
        sync_active_project(self.config)
        self.load_active_project_runtime()
        self.reset_preflight()
        save_config(self.config)
        self.status = f"Active project: {project.get('label') or name}"

    def delete_project_profile(self, project: dict[str, Any]) -> None:
        projects = [item for item in self.config.get("projects", []) if isinstance(item, dict)]
        if len(projects) <= 1:
            self.status = "Cannot delete the only project"
            return
        name = str(project.get("name", ""))
        if not self.confirm_sync_action("Delete project", f"Remove project profile {name} from the client config."):
            self.screen.timeout(-1)
            self.status = "Project delete cancelled"
            return
        self.config["projects"] = [item for item in projects if item is not project]
        if str(self.config.get("active_project", "")) == name:
            remaining = [item for item in self.config.get("projects", []) if isinstance(item, dict)]
            self.config["active_project"] = str(remaining[0].get("name", "")) if remaining else ""
            self.load_active_project_runtime()
            self.reset_preflight()
        sync_active_project(self.config)
        save_config(self.config)
        self.screen.timeout(-1)
        self.status = f"Project deleted: {name}"

    def project_is_active(self, project: dict[str, Any]) -> bool:
        return str(project.get("name", "")) == str(self.config.get("active_project", ""))

    def project_field_value(self, project: dict[str, Any], field: dict[str, Any]) -> str:
        key = str(field["key"])
        if field["kind"] == "param":
            name = key.removeprefix("param:")
            params = project.get("parameters", {})
            if isinstance(params, dict) and name in params:
                return str(params.get(name, ""))
            return str(field["param"].get("default", ""))
        return str(project.get(key, ""))

    def project_field_enabled(self, field: dict[str, Any], project: dict[str, Any]) -> bool:
        kind = str(field["kind"])
        if kind in ("text", "git_ref"):
            return True
        if not self.project_is_active(project):
            return False
        if kind == "param":
            return True
        if kind == "targets":
            return True
        if kind == "remote_dir":
            return self.connected and remote_has_ssh(self.config)
        if kind in ("manifest", "dockerfile"):
            return self.connected and remote_has_ssh(self.config) and remote_has_project_dir(self.config)
        return True

    def project_field_disabled_reason(self, field: dict[str, Any], project: dict[str, Any]) -> str:
        kind = str(field["kind"])
        if not self.project_is_active(project):
            return "set this project active first"
        if kind in ("remote_dir", "manifest", "dockerfile"):
            if not remote_has_user(self.config):
                return "set SSH user first"
            if not remote_has_host(self.config):
                return "set SSH host first"
            if kind == "remote_dir":
                return "connect to the remote target first"
            if not remote_has_project_dir(self.config):
                return "select remote project directory first"
            return "connect to the remote target first"
        return ""

    def project_field_hint(self, field: dict[str, Any], project: dict[str, Any]) -> str:
        key = str(field["key"])
        kind = str(field["kind"])
        hints = {
            "name": "Unique local project id. Renaming an active project preserves active selection.",
            "label": "Display label for this project profile.",
            "project_dir": "Remote Moulin checkout directory for this project. Use Enter to browse after connecting the active remote.",
            "local_project_dir": f"Local overlay for mapped pull/push. Relative paths are resolved from {APP_DIR}.",
            "git_url": "Git URL used by Prepare remote project when checkout origin should be validated.",
            "git_ref": "Enter selects a branch from the remote Git URL when reachable, otherwise manual input. Existing checkouts are checked but not switched automatically.",
            "moulin_manifest": "Search tracked root YAML files on the active remote and save a Moulin manifest.",
            "dockerfile": "Search tracked Dockerfiles on the active remote and save a Dockerfile path.",
            "targets": "Space toggles build targets, Enter saves, Esc cancels.",
            "docker_image": "Docker image name/tag used for remote Docker and product build commands.",
        }
        if kind == "param":
            return str(field["param"].get("desc", "")) or "Enter switches this Moulin parameter to its next allowed value."
        return hints.get(key, "")

    def apply_project_inline_value(self, project: dict[str, Any] | None, key: str, value: str) -> None:
        if project is None:
            self.status = "No project selected"
            return
        old_name = str(project.get("name", ""))
        value = value.strip()
        if key == "name":
            if not value:
                self.status = "Project profile name is required"
                return
            if value != old_name and any(str(item.get("name", "")) == value for item in self.config.get("projects", []) if isinstance(item, dict)):
                self.status = f"Project already exists: {value}"
                return
        project[key] = value
        if key == "name":
            if not str(project.get("label", "")).strip() or str(project.get("label", "")) == old_name:
                project["label"] = value
            if str(self.config.get("active_project", "")) == old_name:
                self.config["active_project"] = value
        if self.project_is_active(project):
            sync_active_project(self.config)
            if key in ("project_dir", "local_project_dir", "docker_image"):
                self.load_active_project_runtime()
            if key in ("project_dir", "git_url", "git_ref"):
                self.reset_preflight()
            if key == "docker_image":
                self.docker_image = value
        save_config(self.config)
        self.status = f"{key} updated"

    def edit_project_remote_dir(self, project: dict[str, Any]) -> None:
        field = {"label": "Remote project dir", "key": "project_dir", "kind": "remote_dir"}
        if not self.project_field_enabled(field, project):
            self.status = self.project_field_disabled_reason(field, project)
            return
        selected = self.browse_remote_directory_screen(str(project.get("project_dir", "")) or "~")
        if selected:
            project["project_dir"] = selected
            if self.project_is_active(project):
                sync_active_project(self.config)
                self.reset_preflight()
            save_config(self.config)
            self.status = f"Remote project dir: {selected}"

    def edit_project_git_ref(self, project: dict[str, Any]) -> None:
        git_url = project_git_url(self.config)
        if self.project_is_active(project) and self.connected and remote_has_ssh(self.config) and git_url:
            try:
                self.draw_loading_message("Select Git branch/ref", "Reading remote Git branches...")
                branches = self.remote_git_branches(git_url)
            except Exception as exc:
                self.status = f"Branch list failed: {exc}"
            else:
                selected = self.select_git_branch_screen(branches, str(project.get("git_ref", "")))
                if selected is not None:
                    self.apply_project_inline_value(project, "git_ref", selected)
                    return
        value = self.prompt("Git branch/ref", str(project.get("git_ref", ""))).strip()
        self.apply_project_inline_value(project, "git_ref", value)

    def remote_git_branches(self, git_url: str) -> list[str]:
        script = f"git ls-remote --heads --refs {shlex.quote(git_url)}"
        output = capture(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", remote_spec(self.config), script], echo=False, timeout=20)
        branches: list[str] = []
        for line in output.splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            ref = parts[1]
            prefix = "refs/heads/"
            if ref.startswith(prefix):
                branches.append(ref[len(prefix) :])
        return sorted(set(branches))

    def select_git_branch_screen(self, branches: list[str], current: str) -> str | None:
        choices = ["<manual input>"] + branches
        index = choices.index(current) if current in choices else 0
        self.screen.timeout(-1)
        while True:
            self.screen.erase()
            height, width = self.screen.getmaxyx()
            if height < 16 or width < 70:
                self.add(0, 0, "Terminal is too small. Need at least 70x16.", self.warn_attr())
                self.screen.refresh()
                ch = self.read_key()
                if (self.key_matches(ch, "q") or ch == 27):
                    return None
                continue
            self.add(0, 0, "Select Git branch/ref"[:width], curses.A_BOLD)
            self.add(1, 0, self.fit_text(f"Git URL: {project_git_url(self.config)}", width))
            self.draw_box(3, 0, height - 6, width, "Branches")
            visible = max(1, height - 8)
            if len(choices) == 1:
                self.add(4, 2, "No branches found. Use manual input."[: width - 4], self.warn_attr())
            index = min(index, max(0, len(choices) - 1))
            scroll = min(max(0, index - visible + 1), max(0, len(choices) - visible))
            for offset, choice in enumerate(choices[scroll : scroll + visible]):
                item_index = scroll + offset
                marker = "*" if choice == current and choice != "<manual input>" else " "
                label = f"{marker} {choice}"
                attr = self.selected_attr() if item_index == index else 0
                self.add(4 + offset, 2, self.fit_text(label, width - 4).ljust(width - 4), attr)
            footer = "Up/Down: select | Enter: choose | q/Esc: cancel"
            self.add(height - 2, 0, footer[:width], self.accent_attr())
            self.add(height - 1, 0, self.status[:width].ljust(width), curses.A_REVERSE)
            self.screen.refresh()
            ch = self.read_key()
            if (ch == curses.KEY_UP or self.key_matches(ch, "k")) and choices:
                index = (index - 1) % len(choices)
            elif (ch == curses.KEY_DOWN or self.key_matches(ch, "j") or ch == ord("\t")) and choices:
                index = (index + 1) % len(choices)
            elif ch in (10, 13) and choices:
                if choices[index] == "<manual input>":
                    return self.prompt("Git branch/ref", current).strip()
                return choices[index]
            elif (self.key_matches(ch, "q") or ch == 27):
                return None

    def settings_action_label(self, action: dict[str, Any]) -> str:
        kind = action["kind"]
        if kind == "select_project":
            project = active_project(self.config)
            return f"Active project: {project.get('label') or project.get('name')}"
        if kind == "add_project":
            return "Add project"
        if kind == "delete_project":
            return "Delete active project"
        if kind == "param":
            param = action["param"]
            name = param["name"]
            value = self.build_params.get(name, str(param["default"]))
            choices = "/".join(str(choice) for choice in param.get("choices", []))
            return f"Edit {name}: {value} ({choices})"
        if kind == "local_project_dir":
            return f"Edit local overlay dir: {active_project(self.config).get('local_project_dir', '')}"
        if kind == "manifest":
            return f"Select Moulin manifest: {moulin_manifest_name(self.config)}"
        if kind == "git_url":
            return f"Edit project Git URL: {project_git_url(self.config) or '<not set>'}"
        if kind == "dockerfile":
            return f"Select Dockerfile: {configured_dockerfile(self.config)}"
        if kind == "targets":
            return f"Select build targets: {self.build_targets}"
        if kind == "docker":
            return f"Edit Docker image name: {self.docker_image}"
        if kind == "save":
            return "Save project"
        if kind == "back":
            return "Back to main menu"
        return str(kind)

    def settings_action_description(self, action: dict[str, Any]) -> str:
        kind = action["kind"]
        if kind == "select_project":
            return "Choose which project profile provides manifest, build parameters, targets, Docker image, and local overlay."
        if kind == "add_project":
            return "Create a new project profile initialized from the current project values."
        if kind == "delete_project":
            return "Remove the active project profile. At least one project profile is kept."
        if kind == "param":
            param = action["param"]
            desc = str(param.get("desc", ""))
            return desc or "Switch this Moulin parameter to its next allowed value."
        if kind == "local_project_dir":
            return "Local overlay directory used for mapped file pull/push operations."
        if kind == "manifest":
            return "Search the remote project checkout for YAML files, validate Moulin-shaped files, and save the selected path in the active project."
        if kind == "git_url":
            return "Git URL used by Prepare remote project when the checkout is missing or origin should be validated."
        if kind == "dockerfile":
            return "Search the remote project checkout for Dockerfiles, validate files that start with FROM, and save the selected path in the active project."
        if kind == "targets":
            return "Choose Ninja targets from the Moulin manifest and selected parameter overrides."
        if kind == "docker":
            return "Edit the Docker image name/tag stored in the active project and used for remote Docker and product build commands."
        if kind == "save":
            return "Persist current project parameters, targets, manifest, Dockerfile, Docker image, and local overlay."
        if kind == "back":
            return "Return to the main Moulin client menu without writing project changes."
        return ""

    def run_settings_action(self, action: dict[str, Any]) -> bool:
        kind = action["kind"]
        if kind == "select_project":
            self.select_project_screen()
            return False
        if kind == "add_project":
            self.add_project_profile()
            return False
        if kind == "delete_project":
            self.delete_active_project_profile()
            return False
        if kind == "param":
            self.cycle_parameter(action["param"])
            return False
        if kind == "local_project_dir":
            value = self.prompt("Local overlay dir", str(active_project(self.config).get("local_project_dir", "")))
            active_project(self.config)["local_project_dir"] = value
            sync_active_project(self.config)
            return False
        if kind == "manifest":
            self.select_remote_moulin_manifest()
            return False
        if kind == "git_url":
            active_project(self.config)["git_url"] = self.prompt("Project Git URL", project_git_url(self.config)).strip()
            sync_active_project(self.config)
            self.reset_preflight()
            return False
        if kind == "dockerfile":
            self.select_remote_dockerfile()
            return False
        if kind == "targets":
            self.select_build_targets_screen()
            return False
        if kind == "docker":
            self.docker_image = self.prompt("Docker image name", self.docker_image)
            active_project(self.config)["docker_image"] = self.docker_image
            sync_active_project(self.config)
            return False
        if kind == "save":
            self.save_current_build_settings()
            save_config(self.config)
            self.status = "Project saved"
            return True
        if kind == "back":
            self.status = "Project changes kept in memory, not saved"
            return True
        return False

    def select_project_screen(self) -> None:
        projects = [project for project in self.config.get("projects", []) if isinstance(project, dict)]
        if not projects:
            normalize_project_profiles(self.config)
            projects = [project for project in self.config.get("projects", []) if isinstance(project, dict)]
        index = next(
            (idx for idx, project in enumerate(projects) if str(project.get("name", "")) == str(self.config.get("active_project", ""))),
            0,
        )
        self.screen.timeout(-1)
        while True:
            self.screen.erase()
            height, width = self.screen.getmaxyx()
            if height < 12 or width < 70:
                self.add(0, 0, "Terminal is too small. Need at least 70x12.", self.warn_attr())
                self.screen.refresh()
                ch = self.read_key()
                if (self.key_matches(ch, "q") or ch == 27):
                    return
                continue
            self.draw_box(0, 0, height - 2, width, "Projects")
            visible = max(1, height - 5)
            index = min(index, max(0, len(projects) - 1))
            scroll = min(max(0, index - visible + 1), max(0, len(projects) - visible))
            for offset, project in enumerate(projects[scroll : scroll + visible]):
                item_index = scroll + offset
                mark = "*" if str(project.get("name", "")) == str(self.config.get("active_project", "")) else " "
                label = f"{mark} {project.get('label') or project.get('name')}"
                attr = self.selected_attr() if item_index == index else 0
                self.add(1 + offset, 2, label[: width - 4].ljust(width - 4), attr)
            footer = "Up/Down: select | Enter: set active | q/Esc: back"
            self.add(height - 2, 0, footer[:width], self.accent_attr())
            self.add(height - 1, 0, self.status[:width].ljust(width), curses.A_REVERSE)
            self.screen.refresh()
            ch = self.read_key()
            if (ch == curses.KEY_UP or self.key_matches(ch, "k")) and projects:
                index = (index - 1) % len(projects)
            elif (ch == curses.KEY_DOWN or self.key_matches(ch, "j")) and projects:
                index = (index + 1) % len(projects)
            elif ch in (10, 13) and projects:
                self.config["active_project"] = str(projects[index].get("name", ""))
                sync_active_project(self.config)
                self.load_active_project_runtime()
                save_config(self.config)
                self.status = f"Active project: {projects[index].get('label') or projects[index].get('name')}"
                return
            elif (self.key_matches(ch, "q") or ch == 27):
                return

    def add_project_profile(self) -> None:
        name = self.prompt("Project profile name", "project").strip()
        if not name:
            self.status = "Project add cancelled: empty name"
            return
        projects = [project for project in self.config.setdefault("projects", []) if isinstance(project, dict)]
        if any(str(project.get("name", "")) == name for project in projects):
            self.status = f"Project already exists: {name}"
            return
        current = dict(active_project(self.config))
        current["name"] = name
        current["label"] = name
        current["parameters"] = dict(self.build_params)
        current["targets"] = self.build_targets
        current["docker_image"] = self.docker_image
        projects.append(current)
        self.config["projects"] = projects
        self.config["active_project"] = name
        sync_active_project(self.config)
        self.load_active_project_runtime()
        save_config(self.config)
        self.status = f"Project added: {name}"

    def delete_active_project_profile(self) -> None:
        projects = [project for project in self.config.get("projects", []) if isinstance(project, dict)]
        if len(projects) <= 1:
            self.status = "Cannot delete the only project"
            return
        active = str(self.config.get("active_project", ""))
        if not self.confirm_sync_action("Delete project", f"Remove project profile {active} from the client config."):
            self.screen.timeout(-1)
            self.status = "Project delete cancelled"
            return
        remaining = [project for project in projects if str(project.get("name", "")) != active]
        self.config["projects"] = remaining
        self.config["active_project"] = str(remaining[0].get("name", ""))
        sync_active_project(self.config)
        self.load_active_project_runtime()
        save_config(self.config)
        self.screen.timeout(-1)
        self.status = f"Project deleted: {active}"

    def select_build_targets_screen(self) -> None:
        candidates = moulin_target_candidates(self.config, self.build_params)
        selected = set(shlex.split(self.build_targets))
        index = 0
        self.screen.timeout(-1)
        while True:
            self.screen.erase()
            height, width = self.screen.getmaxyx()
            if height < 18 or width < 80:
                self.add(0, 0, "Terminal is too small. Need at least 80x18.", self.warn_attr())
                self.screen.refresh()
                ch = self.read_key()
                if (self.key_matches(ch, "q") or ch == 27):
                    self.screen.timeout(250)
                    return
                continue

            actions: list[dict[str, Any]] = [{"kind": "target", "candidate": candidate} for candidate in candidates]
            index = min(index, max(0, len(actions) - 1))
            self.draw_box(0, 0, height - 2, width, "Build Targets")
            self.add(1, 2, "Manifest:", self.accent_attr())
            self.add(1, 18, self.fit_text(moulin_manifest_name(self.config), width - 20))
            self.add(2, 2, "Selected:", self.accent_attr())
            selected_text = " ".join(target for target in self.ordered_targets(candidates, selected)) or "none"
            self.add(2, 18, self.fit_text(selected_text, width - 20))

            top = 4
            visible = max(1, height - 10)
            if not candidates:
                self.add(top, 2, "No build targets found in Moulin manifest.", self.warn_attr())
                top += 2
            if actions:
                for offset, action in enumerate(actions[:visible]):
                    row = top + offset
                    label = self.build_target_action_label(action, selected)
                    attr = self.selected_attr() if offset == index else 0
                    self.add(row, 2, label[: width - 4].ljust(width - 4), attr)

            if actions:
                self.add(height - 4, 2, self.fit_text(self.build_target_action_description(actions[index]), width - 4))
            footer = "Up/Down: select | Space: toggle | Enter: save | q/Esc: cancel"
            self.add(height - 2, 0, footer[:width], self.accent_attr())
            self.add(height - 1, 0, self.status[:width].ljust(width), curses.A_REVERSE)
            self.screen.refresh()
            ch = self.read_key()
            if (ch == curses.KEY_UP or self.key_matches(ch, "k")) and actions:
                index = (index - 1) % len(actions)
            elif (ch == curses.KEY_DOWN or self.key_matches(ch, "j")) and actions:
                index = (index + 1) % len(actions)
            elif ch == ord(" ") and actions:
                target = actions[index]["candidate"]["target"]
                if target in selected:
                    selected.remove(target)
                else:
                    selected.add(target)
                self.status = f"{target}: {'selected' if target in selected else 'removed'}"
            elif ch in (10, 13):
                ordered = self.ordered_targets(candidates, selected)
                self.build_targets = " ".join(ordered)
                self.save_current_build_settings()
                self.status = "Build target selection saved"
                self.screen.timeout(250)
                return
            elif (self.key_matches(ch, "q") or ch == 27):
                self.status = "Build target selection cancelled"
                self.screen.timeout(250)
                return

    def ordered_targets(self, candidates: list[dict[str, str]], selected: set[str]) -> list[str]:
        current = [target for target in shlex.split(self.build_targets) if target in selected]
        extra = [candidate["target"] for candidate in candidates if candidate["target"] in selected and candidate["target"] not in current]
        return current + extra

    def build_target_action_label(self, action: dict[str, Any], selected: set[str]) -> str:
        kind = action["kind"]
        if kind == "target":
            candidate = action["candidate"]
            mark = "x" if candidate["target"] in selected else " "
            source = candidate.get("source", "")
            return f"[{mark}] {candidate['target']} ({source})"
        return str(kind)

    def build_target_action_description(self, action: dict[str, Any]) -> str:
        kind = action["kind"]
        if kind == "target":
            candidate = action["candidate"]
            return candidate.get("desc", "") or f"Toggle Ninja target {candidate['target']}."
        return ""

    def cycle_parameter(self, param: dict[str, Any]) -> None:
        choices = [str(choice) for choice in param.get("choices", [])]
        if not choices:
            return
        name = param["name"]
        current = self.build_params.get(name, str(param["default"]))
        try:
            index = choices.index(current)
        except ValueError:
            index = -1
        self.build_params[name] = choices[(index + 1) % len(choices)]
        self.status = f"{name}={self.build_params[name]}"

    def prompt(self, label: str, current: str) -> str:
        curses.echo()
        self.set_cursor(True)
        height, width = self.screen.getmaxyx()
        prompt = f"{label} [{current}]: "
        self.add(height - 2, 0, " " * max(0, width - 1))
        self.add(height - 2, 0, prompt[: max(0, width - 1)])
        try:
            curses.flushinp()
            value = self.screen.getstr(height - 2, min(len(prompt), width - 2)).decode("utf-8").strip()
            return value or current
        finally:
            curses.noecho()
            self.set_cursor(False)

    def preview_commands(self, commands: list[list[str]]) -> str:
        if not commands:
            return "no commands"
        return "\n".join(shlex.join(command) for command in commands[:3])

    def structured_script(self, steps: list[tuple[str, str]], *, fail_fast: bool) -> str:
        parts = ["overall_rc=0"]
        for title, command in steps:
            quoted_title = shlex.quote(title)
            parts.extend(
                [
                    f"printf '\\n== %s ==\\n' {quoted_title}",
                    f"printf 'cmd: %s\\n' {shlex.quote(command)}",
                    command,
                    "step_rc=$?",
                    "printf 'exit: %s\\n' \"$step_rc\"",
                    "if [ \"$step_rc\" -ne 0 ]; then overall_rc=\"$step_rc\"; fi",
                ]
            )
            if fail_fast:
                parts.append("if [ \"$step_rc\" -ne 0 ]; then exit \"$step_rc\"; fi")
        parts.append("exit \"$overall_rc\"")
        return "; ".join(parts)

    def terminate_process_group(self, pid: int, sig: signal.Signals) -> None:
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            pass

    def quit(self) -> None:
        self.flush_ui_profile()
        self.done = True


def cmd_menu(config: dict[str, Any]) -> None:
    curses.wrapper(lambda screen: ClientApp(screen, config).run())


def cmd_connect(config: dict[str, Any]) -> None:
    command = f"cd {shlex.quote(remote_project_dir(config))} && exec bash -l"
    run(["ssh", "-t", remote_spec(config), command])


def cmd_remote_status(config: dict[str, Any]) -> None:
    app = NullApp(config)
    run(remote_status_command(config, app), check=False)


def cmd_remote_build_docker(config: dict[str, Any]) -> None:
    run(remote_docker_command(config, NullApp(config)))


def cmd_remote_regen_moulin(config: dict[str, Any]) -> None:
    run(remote_moulin_command(config, NullApp(config)))


def cmd_remote_build(config: dict[str, Any]) -> None:
    run(remote_build_command(config, NullApp(config)))


class NullApp:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        settings = load_build_settings(config) if config is not None else {}
        self.docker_image = (configured_docker_image(config) or str(settings.get("docker_image", ""))) if config is not None else docker_image()
        self.build_params = default_build_params(config) if config is not None else {}
        self.build_params.update({str(key): str(value) for key, value in settings.get("parameters", {}).items()})
        self.build_targets = str(settings.get("targets", build_targets()))

    def structured_script(self, steps: list[tuple[str, str]], *, fail_fast: bool) -> str:
        parts = ["overall_rc=0"]
        for title, command in steps:
            quoted_title = shlex.quote(title)
            parts.extend(
                [
                    f"printf '\\n== %s ==\\n' {quoted_title}",
                    f"printf 'cmd: %s\\n' {shlex.quote(command)}",
                    command,
                    "step_rc=$?",
                    "printf 'exit: %s\\n' \"$step_rc\"",
                    "if [ \"$step_rc\" -ne 0 ]; then overall_rc=\"$step_rc\"; fi",
                ]
            )
            if fail_fast:
                parts.append("if [ \"$step_rc\" -ne 0 ]; then exit \"$step_rc\"; fi")
        parts.append("exit \"$overall_rc\"")
        return "; ".join(parts)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("connect")
    sub.add_parser("server-tui")
    sub.add_parser("sync-menu")
    sub.add_parser("menu")
    sub.add_parser("remote-status")
    sub.add_parser("build-docker")
    sub.add_parser("regen-moulin")
    sub.add_parser("build")
    sub.add_parser("status")
    sub.add_parser("mappings")
    sub.add_parser("select-mappings")
    sub.add_parser("inventory")
    sub.add_parser("choose")
    sub.add_parser("pull")
    sub.add_parser("pull-dry-run")
    sub.add_parser("push")
    sub.add_parser("push-dry-run")
    pull_map = sub.add_parser("pull-map")
    pull_map.add_argument("names", nargs="+", help="mapping names, or 'all'")
    pull_map_dry = sub.add_parser("pull-map-dry-run")
    pull_map_dry.add_argument("names", nargs="+", help="mapping names, or 'all'")
    push_map = sub.add_parser("push-map")
    push_map.add_argument("names", nargs="+", help="mapping names, or 'all'")
    push_map_dry = sub.add_parser("push-map-dry-run")
    push_map_dry.add_argument("names", nargs="+", help="mapping names, or 'all'")
    sub.add_parser("pull-selected-map")
    sub.add_parser("pull-selected-map-dry-run")
    sub.add_parser("push-selected-map")
    sub.add_parser("push-selected-map-dry-run")
    sub.add_parser("tui")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    config = load_config(args.config)
    if args.command in ("connect", "server-tui"):
        cmd_connect(config)
    elif args.command in ("sync-menu", "menu", "tui"):
        cmd_menu(config)
    elif args.command == "remote-status":
        cmd_remote_status(config)
    elif args.command == "build-docker":
        cmd_remote_build_docker(config)
    elif args.command == "regen-moulin":
        cmd_remote_regen_moulin(config)
    elif args.command == "build":
        cmd_remote_build(config)
    elif args.command == "status":
        cmd_status(config)
    elif args.command == "mappings":
        cmd_mappings(config)
    elif args.command == "select-mappings":
        cmd_select_mappings(config)
    elif args.command == "inventory":
        cmd_inventory(config)
    elif args.command == "choose":
        cmd_choose(config)
    elif args.command == "pull":
        cmd_pull(config, dry_run=False)
    elif args.command == "pull-dry-run":
        cmd_pull(config, dry_run=True)
    elif args.command == "push":
        cmd_push(config, dry_run=False)
    elif args.command == "push-dry-run":
        cmd_push(config, dry_run=True)
    elif args.command == "pull-map":
        cmd_pull_map(config, args.names, dry_run=False)
    elif args.command == "pull-map-dry-run":
        cmd_pull_map(config, args.names, dry_run=True)
    elif args.command == "push-map":
        cmd_push_map(config, args.names, dry_run=False)
    elif args.command == "push-map-dry-run":
        cmd_push_map(config, args.names, dry_run=True)
    elif args.command == "pull-selected-map":
        cmd_pull_map(config, selected_mapping_names(config), dry_run=False)
    elif args.command == "pull-selected-map-dry-run":
        cmd_pull_map(config, selected_mapping_names(config), dry_run=True)
    elif args.command == "push-selected-map":
        cmd_push_map(config, selected_mapping_names(config), dry_run=False)
    elif args.command == "push-selected-map-dry-run":
        cmd_push_map(config, selected_mapping_names(config), dry_run=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
