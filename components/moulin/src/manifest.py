"""Pure Moulin manifest helpers."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, Callable, Mapping

from components.config.api import accessors as config_accessors
from components.build_runtime.api import runtime as config_runtime

try:
    import yaml
except ImportError:
    yaml = None

MOULIN_TAG_RE = re.compile(r"(?m)(?:^|[\s\[{,:-])(!(?![!\s])(?:<[^>\r\n]+>|[A-Za-z0-9_.-]+(?:![A-Za-z0-9_./:-]+)?))")
YAML_TAG_DIRECTIVE_RE = re.compile(r"(?m)^%TAG\s+(![^ \t]*)\s+([^ \t\r\n]+)")

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


def yaml_available() -> bool:
    return yaml is not None and MoulinYamlLoader is not None


def yaml_tags(text: str) -> list[str]:
    tags: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0]
        if YAML_TAG_DIRECTIVE_RE.search(line):
            tags.add("%TAG")
        tags.update(match.group(1) for match in MOULIN_TAG_RE.finditer(line))
    return sorted(tags)


def manifest_markers(data: dict[str, Any]) -> list[str]:
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


def is_manifest_data(data: dict[str, Any]) -> bool:
    markers = set(manifest_markers(data))
    return "min_ver" in markers and (
        "components" in markers
        or "images" in markers
        or "parameters" in markers
        or "builder.type" in markers
    )


def parse_manifest_text(text: str) -> Any:
    if not yaml_available():
        return {}
    return yaml.load(text, Loader=MoulinYamlLoader)


def load_manifest_text(text: str) -> dict[str, Any]:
    data = parse_manifest_text(text)
    return data if isinstance(data, dict) else {}


def load_manifest_file(path: Path) -> dict[str, Any]:
    if not yaml_available() or not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.load(handle, Loader=MoulinYamlLoader)
    return data if isinstance(data, dict) else {}


def resolve_manifest_path(
    manifest_name: str,
    local_project_dir: Path,
    app_dir: Path,
    fallback_manifest: Any,
) -> Path:
    manifest = Path(manifest_name)
    candidates: list[Path] = []
    if manifest.is_absolute():
        candidates.append(manifest)
    else:
        candidates.append(local_project_dir / manifest)
        if fallback_manifest:
            fallback_path = Path(str(fallback_manifest))
            candidates.append(fallback_path if fallback_path.is_absolute() else app_dir / fallback_path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def resolve_manifest_path_for_config(
    config: dict[str, Any],
    app_dir: Path,
    default_moulin_manifest: str = "product.yaml",
) -> Path:
    return resolve_manifest_path(
        config_accessors.moulin_manifest_name_for_config(config, default_moulin_manifest),
        config_accessors.local_project_dir_for_config(config, app_dir),
        app_dir,
        config.get("moulin", {}).get("fallback_manifest"),
    )


def load_manifest_for_config(
    config: dict[str, Any],
    *,
    app_dir: Path,
    remote_read_project_file: Callable[[dict[str, Any], str], str],
    cache: dict[tuple[str, str, str], dict[str, Any]],
    default_moulin_manifest: str = "product.yaml",
) -> dict[str, Any]:
    if not yaml_available():
        return {}
    manifest_name = config_accessors.moulin_manifest_name_for_config(config, default_moulin_manifest)
    if (
        config_accessors.remote_has_ssh_for_config(config)
        and config_accessors.remote_has_project_dir_for_config(config)
        and manifest_name
    ):
        cache_key = (
            config_accessors.remote_spec_for_config(config),
            config_accessors.remote_project_dir_for_config(config),
            manifest_name,
        )
        if cache_key in cache:
            return cache[cache_key]
        try:
            result = load_manifest_text(remote_read_project_file(config, manifest_name))
            cache[cache_key] = result
            return result
        except Exception:
            pass
    return load_manifest_file(resolve_manifest_path_for_config(config, app_dir, default_moulin_manifest))


def validate_manifest_text(text: str) -> tuple[bool, str]:
    if not yaml_available():
        return False, "PyYAML is not installed locally"
    tags = yaml_tags(text)
    try:
        data = parse_manifest_text(text)
    except Exception as exc:
        return False, f"YAML parse failed: {exc}"
    if not isinstance(data, dict):
        return False, "not a YAML mapping"
    markers = manifest_markers(data)
    if not is_manifest_data(data):
        detail = ", ".join(markers) if markers else "no Moulin manifest markers"
        return False, detail
    detail_parts = [", ".join(markers)]
    if tags:
        detail_parts.append("tags " + ", ".join(tags))
    return True, "; ".join(detail_parts)


def parameters_from_manifest(data: dict[str, Any]) -> list[dict[str, Any]]:
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


def parameters_for_config(
    config: dict[str, Any],
    *,
    app_dir: Path,
    remote_read_project_file: Callable[[dict[str, Any], str], str],
    cache: dict[tuple[str, str, str], dict[str, Any]],
    default_moulin_manifest: str = "product.yaml",
) -> list[dict[str, Any]]:
    data = load_manifest_for_config(
        config,
        app_dir=app_dir,
        remote_read_project_file=remote_read_project_file,
        cache=cache,
        default_moulin_manifest=default_moulin_manifest,
    )
    return parameters_from_manifest(data) if data else []


def default_parameters(data: dict[str, Any]) -> dict[str, str]:
    return {param["name"]: str(param["default"]) for param in parameters_from_manifest(data)}


def default_parameters_for_config(
    config: dict[str, Any],
    *,
    app_dir: Path,
    remote_read_project_file: Callable[[dict[str, Any], str], str],
    cache: dict[tuple[str, str, str], dict[str, Any]],
    default_moulin_manifest: str = "product.yaml",
) -> dict[str, str]:
    return {
        param["name"]: str(param["default"])
        for param in parameters_for_config(
            config,
            app_dir=app_dir,
            remote_read_project_file=remote_read_project_file,
            cache=cache,
            default_moulin_manifest=default_moulin_manifest,
        )
    }


def build_runtime_context_for_config(
    config: dict[str, Any],
    *,
    app_dir: Path,
    env: Mapping[str, str],
    default_docker_image: str,
    default_build_targets: str,
    default_moulin_manifest: str,
    remote_read_project_file: Callable[[dict[str, Any], str], str],
    cache: dict[tuple[str, str, str], dict[str, Any]],
) -> dict[str, Any]:
    return config_runtime.build_runtime_context_for_config(
        config,
        app_dir=app_dir,
        env=env,
        default_docker_image=default_docker_image,
        default_build_targets=default_build_targets,
        default_parameters=lambda: default_parameters_for_config(
            config,
            app_dir=app_dir,
            remote_read_project_file=remote_read_project_file,
            cache=cache,
            default_moulin_manifest=default_moulin_manifest,
        ),
    )


def target_candidates_from_manifest(
    data: dict[str, Any],
    build_params: dict[str, str] | None = None,
) -> list[dict[str, str]]:
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
    selected = build_params or default_parameters(data)
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


def target_candidates_for_config(
    config: dict[str, Any],
    *,
    app_dir: Path,
    remote_read_project_file: Callable[[dict[str, Any], str], str],
    cache: dict[tuple[str, str, str], dict[str, Any]],
    default_moulin_manifest: str = "product.yaml",
    build_params: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    data = load_manifest_for_config(
        config,
        app_dir=app_dir,
        remote_read_project_file=remote_read_project_file,
        cache=cache,
        default_moulin_manifest=default_moulin_manifest,
    )
    if not data:
        return []
    return target_candidates_from_manifest(
        data,
        build_params or default_parameters_for_config(
            config,
            app_dir=app_dir,
            remote_read_project_file=remote_read_project_file,
            cache=cache,
            default_moulin_manifest=default_moulin_manifest,
        ),
    )


def merge_values(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = copy.deepcopy(base)
        for key, value in override.items():
            merged[key] = merge_values(merged[key], value) if key in merged else copy.deepcopy(value)
        return merged
    if isinstance(base, list) and isinstance(override, list):
        return copy.deepcopy(base) + copy.deepcopy(override)
    return copy.deepcopy(override)


def effective_manifest(data: dict[str, Any], build_params: dict[str, str] | None = None) -> dict[str, Any]:
    if not data:
        return {}
    effective = copy.deepcopy(data)
    selected = build_params or default_parameters(data)
    params = data.get("parameters", {})
    if not isinstance(params, dict):
        return effective
    for param_name, value in selected.items():
        param = params.get(param_name)
        if not isinstance(param, dict):
            continue
        choice = param.get(value)
        if not isinstance(choice, dict):
            continue
        overrides = choice.get("overrides", {})
        if isinstance(overrides, dict):
            effective = merge_values(effective, overrides)
    return effective


def effective_manifest_for_config(
    config: dict[str, Any],
    *,
    app_dir: Path,
    remote_read_project_file: Callable[[dict[str, Any], str], str],
    cache: dict[tuple[str, str, str], dict[str, Any]],
    default_moulin_manifest: str = "product.yaml",
    build_params: dict[str, str] | None = None,
) -> dict[str, Any]:
    data = load_manifest_for_config(
        config,
        app_dir=app_dir,
        remote_read_project_file=remote_read_project_file,
        cache=cache,
        default_moulin_manifest=default_moulin_manifest,
    )
    if not data:
        return {}
    return effective_manifest(
        data,
        build_params or default_parameters_for_config(
            config,
            app_dir=app_dir,
            remote_read_project_file=remote_read_project_file,
            cache=cache,
            default_moulin_manifest=default_moulin_manifest,
        ),
    )


def expand_value(value: str, variables: dict[str, str]) -> str:
    result = value
    for _ in range(20):
        updated = re.sub(r"%\{([^}]+)\}", lambda match: variables.get(match.group(1), match.group(0)), result)
        if updated == result:
            return updated
        result = updated
    return result


def effective_variables(data: dict[str, Any]) -> dict[str, str]:
    raw = data.get("variables", {})
    if not isinstance(raw, dict):
        return {}
    variables = {str(key): str(value) for key, value in raw.items()}
    return {key: expand_value(value, variables) for key, value in variables.items()}


def artifact_copy_specs_from_manifest(data: dict[str, Any], targets: list[str]) -> list[dict[str, str]]:
    variables = effective_variables(data)
    components = data.get("components", {}) if isinstance(data.get("components", {}), dict) else {}
    images = data.get("images", {}) if isinstance(data.get("images", {}), dict) else {}
    specs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(label: str, path: str, source: str) -> None:
        clean = expand_value(path, variables).strip().strip("/")
        if not clean:
            return
        key = (label, clean)
        if key in seen:
            return
        seen.add(key)
        specs.append({"label": label, "path": clean, "source": source})

    for target in targets:
        component = components.get(target)
        builder = component.get("builder", {}) if isinstance(component, dict) else {}
        target_images = builder.get("target_images", []) if isinstance(builder, dict) else []
        if isinstance(target_images, list) and target_images:
            for image in target_images:
                add(target, str(image), "manifest component target_images")
            continue

        image_name = target[:-7] if target.endswith(".img.gz") else target
        if image_name in images:
            add(target, target, "manifest image output")
            continue

        add(target, target, "filesystem fallback")
    return specs


def artifact_copy_specs_for_config(
    config: dict[str, Any],
    targets: list[str],
    *,
    app_dir: Path,
    remote_read_project_file: Callable[[dict[str, Any], str], str],
    cache: dict[tuple[str, str, str], dict[str, Any]],
    default_moulin_manifest: str = "product.yaml",
    build_params: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    data = effective_manifest_for_config(
        config,
        app_dir=app_dir,
        remote_read_project_file=remote_read_project_file,
        cache=cache,
        default_moulin_manifest=default_moulin_manifest,
        build_params=build_params,
    )
    return artifact_copy_specs_from_manifest(data, targets)


def yocto_image_recipes_from_manifest(
    data: dict[str, Any],
    build_params: dict[str, str] | None = None,
) -> list[str]:
    effective = effective_manifest(data, build_params)
    variables = effective_variables(effective)
    components = effective.get("components", {}) if isinstance(effective.get("components", {}), dict) else {}
    recipes: list[str] = []
    seen: set[str] = set()
    for raw in components.values():
        builder = raw.get("builder", {}) if isinstance(raw, dict) else {}
        if not isinstance(builder, dict) or builder.get("type") != "yocto":
            continue
        target = str(builder.get("build_target", "")).strip()
        if not target:
            continue
        recipe = expand_value(target, variables).strip()
        if not recipe or "%{" in recipe or recipe in seen:
            continue
        seen.add(recipe)
        recipes.append(recipe)
    return recipes


def component_enabled_by_params(name: str, build_params: dict[str, str] | None) -> bool:
    if not build_params:
        return True
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()
    candidates = [f"ENABLE_{normalized}"]
    if normalized.endswith("_KERNEL"):
        candidates.append(f"ENABLE_{normalized.removesuffix('_KERNEL')}")
    disabled_values = {"0", "false", "no", "off", "disable", "disabled"}
    for param_name in candidates:
        value = build_params.get(param_name)
        if value is not None and str(value).strip().lower() in disabled_values:
            return False
    return True


def expanded_string_list(value: Any, variables: dict[str, str]) -> list[str]:
    if not isinstance(value, list):
        return []
    return [expand_value(str(item), variables).strip() for item in value if str(item).strip()]


def component_builders_from_manifest(
    data: dict[str, Any],
    build_params: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    effective = effective_manifest(data, build_params)
    variables = effective_variables(effective)
    components = effective.get("components", {}) if isinstance(effective.get("components", {}), dict) else {}
    result: list[dict[str, str]] = []
    for name, raw in components.items():
        if not component_enabled_by_params(str(name), build_params):
            continue
        builder = raw.get("builder", {}) if isinstance(raw, dict) else {}
        if not isinstance(builder, dict):
            continue
        builder_type = str(builder.get("type", "")).strip()
        if not builder_type:
            continue
        target = str(builder.get("build_target") or builder.get("target") or name).strip()
        expanded_target = expand_value(target, variables).strip()
        item: dict[str, Any] = {
            "name": str(name),
            "builder_type": builder_type,
            "target": expanded_target,
        }
        if builder_type == "bazel":
            item.update(
                {
                    "build_dir": expand_value(str(raw.get("build-dir", "")), variables).strip(),
                    "tool": expand_value(str(builder.get("tool", "tools/bazel")), variables).strip(),
                    "command": expand_value(str(builder.get("command", "build")), variables).strip(),
                    "args": expanded_string_list(builder.get("args", []), variables),
                    "target_patterns": expanded_string_list(builder.get("target-patterns", []), variables),
                    "target_images": expanded_string_list(builder.get("target_images", []), variables),
                }
            )
        result.append(item)
    return result


def component_builders_for_config(
    config: dict[str, Any],
    *,
    app_dir: Path,
    remote_read_project_file: Callable[[dict[str, Any], str], str],
    cache: dict[tuple[str, str, str], dict[str, Any]],
    default_moulin_manifest: str = "product.yaml",
    build_params: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    data = load_manifest_for_config(
        config,
        app_dir=app_dir,
        remote_read_project_file=remote_read_project_file,
        cache=cache,
        default_moulin_manifest=default_moulin_manifest,
    )
    if not data:
        return []
    return component_builders_from_manifest(
        data,
        build_params or default_parameters_for_config(
            config,
            app_dir=app_dir,
            remote_read_project_file=remote_read_project_file,
            cache=cache,
            default_moulin_manifest=default_moulin_manifest,
        ),
    )


def yocto_image_recipes_for_config(
    config: dict[str, Any],
    *,
    app_dir: Path,
    remote_read_project_file: Callable[[dict[str, Any], str], str],
    cache: dict[tuple[str, str, str], dict[str, Any]],
    default_moulin_manifest: str = "product.yaml",
    build_params: dict[str, str] | None = None,
) -> list[str]:
    data = load_manifest_for_config(
        config,
        app_dir=app_dir,
        remote_read_project_file=remote_read_project_file,
        cache=cache,
        default_moulin_manifest=default_moulin_manifest,
    )
    if not data:
        return []
    return yocto_image_recipes_from_manifest(
        data,
        build_params or default_parameters_for_config(
            config,
            app_dir=app_dir,
            remote_read_project_file=remote_read_project_file,
            cache=cache,
            default_moulin_manifest=default_moulin_manifest,
        ),
    )
