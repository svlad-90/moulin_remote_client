"""Remote build command service."""

from __future__ import annotations

import shlex
import base64
import json
from pathlib import PurePosixPath
from typing import Any, Callable

from components.config.api import accessors as config_accessors
from components.remote.src import session as remote_session


class RemoteBuildCommandService:
    """Own build-host Docker, Moulin, Ninja, and status command use cases."""

    def __init__(self) -> None:
        self.session_service = remote_session.remote_session_command_service()

    def docker_command(self, remote: str, project_dir: str, docker_image: str, dockerfile: str) -> list[str]:
        if not docker_image:
            raise SystemExit("Docker image name is not configured")
        if not dockerfile:
            raise SystemExit("Dockerfile is not configured")
        dockerfile_path = PurePosixPath(dockerfile)
        context = "." if str(dockerfile_path.parent) == "." else str(dockerfile_path.parent)
        command = (
            f"docker build {shlex.quote(context)} -f {shlex.quote(dockerfile)} "
            '--build-arg "USER_ID=$(id -u)" '
            '--build-arg "USER_GID=$(id -g)" '
            f"-t {shlex.quote(docker_image + ':latest')}"
        )
        return self.session_service.remote_shell_command(remote, project_dir, command)

    def docker_command_for_config(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        default_dockerfile: str,
    ) -> list[str]:
        return self.docker_command(
            config_accessors.remote_spec_for_config(config),
            config_accessors.remote_project_dir_for_config(config),
            docker_image,
            config_accessors.configured_dockerfile_for_config(config, default_dockerfile),
        )

    def run_docker_for_config(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        default_dockerfile: str,
        runner: Callable[[list[str]], Any],
    ) -> None:
        runner(
            self.docker_command_for_config(
                config,
                docker_image=docker_image,
                default_dockerfile=default_dockerfile,
            )
        )

    def product_docker_command(self, project_dir: str, docker_image: str, inner_command: str) -> str:
        workspace = shlex.quote(project_dir)
        image = shlex.quote(docker_image)
        inner = shlex.quote(f"cd /home/builder/workspace && {inner_command}")
        return (
            "docker run --network=host --privileged --security-opt apparmor=unconfined "
            "-e PYTHONUNBUFFERED=1 "
            '-v "$HOME"/.ssh:/home/builder/.ssh '
            '--mount type=bind,source="$HOME"/.gitconfig,target=/home/builder/.gitconfig '
            '--mount type=bind,source="$HOME"/.git-credentials,target=/home/builder/.git-credentials '
            f"-v {workspace}:/home/builder/workspace "
            f"-i --rm {image} /bin/bash -lc {inner}"
        )

    def product_docker_command_for_config(self, config: dict[str, Any], docker_image: str, inner_command: str) -> str:
        return self.product_docker_command(
            config_accessors.remote_project_dir_for_config(config),
            docker_image,
            inner_command,
        )

    def moulin_command(
        self,
        remote: str,
        project_dir: str,
        docker_image: str,
        manifest_name: str,
        build_params: dict[str, str],
    ) -> list[str]:
        params = " ".join(
            f"--{shlex.quote(name)} {shlex.quote(value)}"
            for name, value in sorted(build_params.items())
        )
        inner = f"moulin {shlex.quote(manifest_name)}" + (f" {params}" if params else "")
        return self.session_service.remote_shell_command(
            remote,
            project_dir,
            self.product_docker_command(project_dir, docker_image, inner),
        )

    def moulin_command_for_config(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        default_moulin_manifest: str,
        build_params: dict[str, str],
    ) -> list[str]:
        return self.moulin_command(
            config_accessors.remote_spec_for_config(config),
            config_accessors.remote_project_dir_for_config(config),
            docker_image,
            config_accessors.moulin_manifest_name_for_config(config, default_moulin_manifest),
            build_params=build_params,
        )

    def run_moulin_for_config(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        default_moulin_manifest: str,
        build_params: dict[str, str],
        runner: Callable[[list[str]], Any],
    ) -> None:
        runner(
            self.moulin_command_for_config(
                config,
                docker_image=docker_image,
                default_moulin_manifest=default_moulin_manifest,
                build_params=build_params,
            )
        )

    def build_command(self, remote: str, project_dir: str, docker_image: str, targets: str) -> list[str]:
        quoted_targets = " ".join(shlex.quote(target) for target in shlex.split(targets))
        return self.session_service.remote_shell_command(
            remote,
            project_dir,
            self.product_docker_command(project_dir, docker_image, f"ninja {quoted_targets}"),
        )

    def component_clean_command(
        self,
        remote: str,
        project_dir: str,
        docker_image: str,
        components: list[dict[str, Any]],
        *,
        mode: str,
        dry_run: bool = True,
    ) -> list[str]:
        mode = mode.strip()
        if mode not in {"artifacts", "directory", "build_output", "yocto_component_clean", "yocto_component_sstate", "all"}:
            raise ValueError(f"unsupported clean mode: {mode}")
        payload = base64.b64encode(json.dumps(components, sort_keys=True).encode("utf-8")).decode("ascii")
        script = r'''
from __future__ import annotations

import base64
import json
import os
import shlex
import subprocess
from pathlib import Path, PurePosixPath


MODE = "__MODE__"
DRY_RUN = "__DRY_RUN__" == "1"
COMPONENTS = json.loads(base64.b64decode("__COMPONENTS_B64__").decode("utf-8"))


def run(command: str, *, label: str) -> int:
    print()
    print(label)
    print("$", command)
    if DRY_RUN:
        return 0
    return subprocess.run(command, shell=True, executable="/bin/bash", check=False).returncode


def safe_relative_path(raw: str) -> str:
    text = raw.strip()
    if not text or text.startswith("/") or text.startswith("~"):
        return ""
    path = PurePosixPath(text)
    if any(part in {"", ".", ".."} for part in path.parts):
        return ""
    return str(path)


def artifact_paths(component: dict[str, object]) -> list[str]:
    result: list[str] = []
    for key in ("target_images", "artifacts"):
        values = component.get(key, [])
        if isinstance(values, list):
            result.extend(str(value) for value in values)
    target = str(component.get("target", "")).strip()
    suffixes = (".img", ".img.gz", ".wic", ".wic.gz", ".bmap", ".dtb", ".dtbo", ".cpio", ".cpio.gz")
    if "/" in target or target.endswith(suffixes):
        result.append(target)
    seen: set[str] = set()
    clean: list[str] = []
    for raw in result:
        path = safe_relative_path(raw)
        if path and path not in seen:
            seen.add(path)
            clean.append(path)
    return clean


def ninja_clean_target(component: dict[str, object]) -> str:
    target = str(component.get("target", "") or component.get("name", "")).strip()
    if not target or target.startswith("-") or target.startswith("//"):
        return ""
    return target


def remove_artifacts(component: dict[str, object]) -> int:
    paths = artifact_paths(component)
    if paths:
        quoted = " ".join(shlex.quote(path) for path in paths)
        return run(f"rm -rf -- {quoted}", label=f"remove artifacts for {component.get('name')}")
    target = ninja_clean_target(component)
    if not target:
        print(f"skip artifact cleanup for {component.get('name')}: no manifest artifacts or Ninja target")
        return 0
    return run(f"ninja -t clean {shlex.quote(target)}", label=f"clean ninja target for {component.get('name')}")


def remove_component_directory(component: dict[str, object]) -> int:
    build_dir = safe_relative_path(str(component.get("build_dir", "")))
    if not build_dir:
        return 0
    if component.get("builder_type") == "yocto":
        build_path = PurePosixPath(build_dir)
        if not build_path.name.startswith("build-"):
            name = safe_relative_path(str(component.get("name", "")))
            if not name:
                return 0
            build_dir = str(build_path / f"build-{name}")
    return run(f"rm -rf -- {shlex.quote(build_dir)}", label=f"remove component directory for {component.get('name')}")


def build_output_paths(component: dict[str, object]) -> list[str]:
    build_dir = safe_relative_path(str(component.get("build_dir", "")))
    if not build_dir:
        return []
    builder_type = str(component.get("builder_type", ""))
    if builder_type == "android":
        return [str(PurePosixPath(build_dir) / "out")]
    return []


def remove_build_output(component: dict[str, object]) -> int:
    is_yocto = component.get("builder_type") == "yocto"
    paths = yocto_build_output_paths(component) if is_yocto else build_output_paths(component)
    if not paths:
        if not is_yocto:
            print(f"ERROR: build output cleanup is not supported for {component.get('name')}")
        return 1
    quoted = " ".join(shlex.quote(path) for path in paths)
    return run(f"rm -rf -- {quoted}", label=f"remove build output for {component.get('name')}")


def bitbake_setup(build_dir: Path) -> str:
    return f". yocto/openembedded-core/oe-init-build-env {shlex.quote(str(build_dir))} >/dev/null"


def output_tail(text: str, *, limit: int = 12) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-limit:])


def bitbake_env_value(build_dir: Path, recipe: str, variable: str) -> tuple[str, int, str]:
    command = f"{bitbake_setup(build_dir)} && bitbake -e {shlex.quote(recipe)}"
    result = subprocess.run(command, shell=True, executable="/bin/bash", text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        detail = output_tail(result.stderr) or output_tail(result.stdout)
        return "", result.returncode, detail
    prefix = f'{variable}="'
    for line in result.stdout.splitlines():
        if line.startswith(prefix) and line.endswith('"'):
            return line[len(prefix):-1], 0, ""
    return "", 1, f"{variable} was not present in bitbake -e output"


def safe_resolved_output_path(build_dir: Path, raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    path = Path(text)
    if path.is_absolute():
        try:
            return str(path.resolve().relative_to(Path.cwd().resolve()))
        except ValueError:
            return ""
    clean = safe_relative_path(text)
    if not clean:
        return ""
    return str(build_dir / clean)


def yocto_build_output_paths(component: dict[str, object]) -> list[str]:
    name = str(component.get("name", "")).strip()
    recipe = str(component.get("target", "")).strip()
    if not recipe:
        print(f"ERROR: no Yocto recipe target for {name or '<unnamed>'}")
        return []
    build_dirs, exact_build_dir = yocto_component_build_dirs(component)
    if not build_dirs:
        print(f"ERROR: no Yocto build directories found for {name or recipe}")
        return []
    paths: list[str] = []
    for build_dir in build_dirs:
        if not exact_build_dir:
            found, probe_rc = bitbake_recipe_probe(build_dir, recipe)
            if not found:
                reason = f"probe exit {probe_rc}" if probe_rc not in (0, 1) else "recipe not available"
                print(f"skip {name or recipe} in {build_dir}: {reason}")
                continue
        tmpdir, env_rc, env_detail = bitbake_env_value(build_dir, recipe, "TMPDIR")
        if env_rc != 0:
            print(f"skip {name or recipe} in {build_dir}: failed to read TMPDIR with bitbake -e rc={env_rc}")
            if env_detail:
                print(env_detail)
            continue
        path = safe_resolved_output_path(build_dir, tmpdir)
        if not path:
            print(f"skip {name or recipe} in {build_dir}: unsafe TMPDIR {tmpdir!r}")
            continue
        paths.append(path)
        break
    if not paths:
        print(f"ERROR: selected Yocto component {name or recipe} target {recipe} has no safe BitBake TMPDIR")
    return paths


def bitbake_recipe_probe(build_dir: Path, recipe: str) -> tuple[bool, int]:
    command = f"{bitbake_setup(build_dir)} && bitbake -s {shlex.quote(recipe)}"
    result = subprocess.run(command, shell=True, executable="/bin/bash", text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if result.returncode not in (0, 1):
        return False, result.returncode
    return any(line.split()[:1] == [recipe] or line.split()[:1] == [f"{recipe}:"] for line in result.stdout.splitlines()), result.returncode


def yocto_component_build_dirs(component: dict[str, object]) -> tuple[list[Path], bool]:
    build_dir = safe_relative_path(str(component.get("build_dir", "")))
    work_dir = safe_relative_path(str(component.get("work_dir", "")))
    if work_dir:
        base = build_dir or "yocto"
        return [Path(base) / work_dir], True
    if build_dir and PurePosixPath(build_dir).name.startswith("build-"):
        return [Path(build_dir)], True
    return sorted(path for path in Path("yocto").glob("build-*") if (path / "conf/bblayers.conf").exists()), False


def clean_yocto_work(component: dict[str, object], *, task: str) -> int:
    name = str(component.get("name", "")).strip()
    recipe = str(component.get("target", "")).strip()
    if not recipe:
        print(f"ERROR: no Yocto recipe target for {name or '<unnamed>'}")
        return 1
    rc = 0
    matched = 0
    build_dirs, exact_build_dir = yocto_component_build_dirs(component)
    if not build_dirs:
        print(f"ERROR: no Yocto build directories found for {name or recipe}")
        return 1
    for build_dir in build_dirs:
        if exact_build_dir:
            command = f"{bitbake_setup(build_dir)} && bitbake -c {shlex.quote(task)} {shlex.quote(recipe)}"
            matched += 1
            rc = run(command, label=f"{task} {recipe} in {build_dir}") or rc
            continue
        found, probe_rc = bitbake_recipe_probe(build_dir, recipe)
        if not found:
            reason = f"probe exit {probe_rc}" if probe_rc not in (0, 1) else "recipe not available"
            print(f"skip {name or recipe} in {build_dir}: {reason}")
            continue
        matched += 1
        command = f"{bitbake_setup(build_dir)} && bitbake -c {shlex.quote(task)} {shlex.quote(recipe)}"
        rc = run(command, label=f"{task} {recipe} in {build_dir}") or rc
    if matched == 0:
        print(f"ERROR: selected Yocto component {name or recipe} target {recipe} was not found in any yocto/build-* directory")
        return rc or 1
    return rc


def main() -> int:
    print("mode:", MODE)
    print("dry_run:", DRY_RUN)
    print("components:", " ".join(str(component.get("name", "")) for component in COMPONENTS) or "<none>")
    rc = 0
    for component in COMPONENTS:
        if MODE in {"artifacts", "all"}:
            rc = remove_artifacts(component) or rc
        if MODE == "directory":
            rc = remove_component_directory(component) or rc
        if MODE == "build_output":
            rc = remove_build_output(component) or rc
        if component.get("builder_type") == "yocto" and MODE in {"yocto_component_clean", "yocto_component_sstate", "all"}:
            task = "clean" if MODE == "yocto_component_clean" else "cleansstate"
            rc = clean_yocto_work(component, task=task) or rc
    if rc == 0:
        print("clean-component completed")
    return rc


raise SystemExit(main())
'''
        script = (
            script.replace("__MODE__", mode)
            .replace("__DRY_RUN__", "1" if dry_run else "0")
            .replace("__COMPONENTS_B64__", payload)
        )
        inner = "python3 - <<'PY'\n" + script + "\nPY"
        return self.session_service.remote_shell_command(
            remote,
            project_dir,
            self.product_docker_command(project_dir, docker_image, inner),
        )

    def ninja_tool_command(self, remote: str, project_dir: str, docker_image: str, args: str) -> list[str]:
        quoted_args = " ".join(shlex.quote(arg) for arg in shlex.split(args))
        return self.session_service.remote_shell_command(
            remote,
            project_dir,
            self.product_docker_command(project_dir, docker_image, f"ninja {quoted_args}"),
        )

    def bazel_config_command(self, remote: str, project_dir: str, docker_image: str, targets: str) -> list[str]:
        quoted_targets = " ".join(shlex.quote(target) for target in shlex.split(targets))
        inner = f"cd android_kernel && tools/bazel --max_idle_secs=1 build {quoted_targets}; BUILD_RESULT=$?; tools/bazel shutdown; exit ${{BUILD_RESULT}}"
        return self.session_service.remote_shell_command(
            remote,
            project_dir,
            self.product_docker_command(project_dir, docker_image, inner),
        )

    def bazel_component_command(
        self,
        remote: str,
        project_dir: str,
        docker_image: str,
        component: dict[str, Any],
    ) -> list[str]:
        build_dir = str(component.get("build_dir") or ".").strip() or "."
        tool = str(component.get("tool") or "tools/bazel").strip() or "tools/bazel"
        command = str(component.get("command") or "build").strip() or "build"
        args = [str(arg) for arg in component.get("args", []) if str(arg).strip()]
        target = str(component.get("target", "")).strip()
        target_patterns = [str(arg) for arg in component.get("target_patterns", []) if str(arg).strip()]
        target_images = [str(path) for path in component.get("target_images", []) if str(path).strip()]

        command_parts = [shlex.quote(tool), "--max_idle_secs=1", shlex.quote(command)]
        command_parts.extend(shlex.quote(arg) for arg in args)
        if target:
            command_parts.append(shlex.quote(target))
        if target_patterns:
            command_parts.append("--")
            command_parts.extend(shlex.quote(arg) for arg in target_patterns)
        bazel = " ".join(command_parts)

        touch = ""
        if target_images:
            touch_parts = " ".join(shlex.quote(path) for path in target_images)
            touch = f"; if [ $BUILD_RESULT -eq 0 ]; then for p in {touch_parts}; do [ -e \"$p\" ] && touch \"$p\"; done; fi"
        inner = f"cd {shlex.quote(build_dir)} && {bazel}; BUILD_RESULT=$?{touch}; {shlex.quote(tool)} shutdown; exit ${{BUILD_RESULT}}"
        return self.session_service.remote_shell_command(
            remote,
            project_dir,
            self.product_docker_command(project_dir, docker_image, inner),
        )

    def build_command_for_config(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        targets: str,
    ) -> list[str]:
        return self.build_command(
            config_accessors.remote_spec_for_config(config),
            config_accessors.remote_project_dir_for_config(config),
            docker_image,
            targets,
        )

    def component_clean_command_for_config(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        components: list[dict[str, Any]],
        mode: str,
        dry_run: bool = True,
    ) -> list[str]:
        return self.component_clean_command(
            config_accessors.remote_spec_for_config(config),
            config_accessors.remote_project_dir_for_config(config),
            docker_image,
            components,
            mode=mode,
            dry_run=dry_run,
        )

    def ninja_tool_command_for_config(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        args: str,
    ) -> list[str]:
        return self.ninja_tool_command(
            config_accessors.remote_spec_for_config(config),
            config_accessors.remote_project_dir_for_config(config),
            docker_image,
            args,
        )

    def bazel_config_command_for_config(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        targets: str,
    ) -> list[str]:
        return self.bazel_config_command(
            config_accessors.remote_spec_for_config(config),
            config_accessors.remote_project_dir_for_config(config),
            docker_image,
            targets,
        )

    def bazel_component_command_for_config(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        component: dict[str, Any],
    ) -> list[str]:
        return self.bazel_component_command(
            config_accessors.remote_spec_for_config(config),
            config_accessors.remote_project_dir_for_config(config),
            docker_image,
            component,
        )

    def run_build_for_config(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        targets: str,
        runner: Callable[[list[str]], Any],
    ) -> None:
        runner(self.build_command_for_config(config, docker_image=docker_image, targets=targets))

    def yocto_impact_command(
        self,
        remote: str,
        project_dir: str,
        docker_image: str,
        targets: str,
        *,
        action: str = "analyze",
        image_recipes: list[str] | None = None,
        allow_empty: bool = False,
    ) -> list[str]:
        script = r'''
from __future__ import annotations

import subprocess
import sys
import selectors
import time
import os
from pathlib import Path


ACTION = "__ACTION__"
TARGETS = "__TARGETS__".strip()
IMAGE_RECIPES = "__IMAGE_RECIPES__".strip().split()
ALLOW_EMPTY = "__ALLOW_EMPTY__" == "1"


def run_lines(argv: list[str]) -> list[str]:
    result = subprocess.run(argv, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if result.returncode not in (0, 1):
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def run_output(command: str, *, label: str, heartbeat_s: int = 30) -> tuple[int, str]:
    started = time.monotonic()
    next_heartbeat = started + heartbeat_s
    process = subprocess.Popen(
        command,
        shell=True,
        executable="/bin/bash",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    assert process.stdout is not None
    output: list[str] = []
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    while process.poll() is None:
        events = selector.select(timeout=1)
        for key, _mask in events:
            line = key.fileobj.readline()
            if line:
                output.append(line)
        now = time.monotonic()
        if now >= next_heartbeat:
            elapsed = int(now - started)
            print(f"[progress] still running after {elapsed}s: {label}", flush=True)
            next_heartbeat = now + heartbeat_s
    for line in process.stdout:
        output.append(line)
    elapsed = int(time.monotonic() - started)
    print(f"{label}: exit {process.returncode} elapsed {elapsed}s", flush=True)
    return int(process.returncode or 0), "".join(output)


def run_shell(command: str, *, label: str, step: int, total: int, heartbeat_s: int = 30) -> int:
    print()
    print(f"== yocto impact {ACTION} ==")
    print(f"step: {step}/{total}")
    print("label:", label)
    if os.environ.get("MOULIN_TUI_SHOW_COMMANDS", "").strip().lower() in {"1", "true", "yes", "on"}:
        print("cmd:", command)
    started = time.monotonic()
    next_heartbeat = started + heartbeat_s
    process = subprocess.Popen(
        command,
        shell=True,
        executable="/bin/bash",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    while process.poll() is None:
        events = selector.select(timeout=1)
        for key, _mask in events:
            line = key.fileobj.readline()
            if line:
                print(line, end="")
        now = time.monotonic()
        if now >= next_heartbeat:
            elapsed = int(now - started)
            print(f"[progress] step {step}/{total} still running after {elapsed}s: {label}", flush=True)
            next_heartbeat = now + heartbeat_s

    for line in process.stdout:
        print(line, end="")
    elapsed = int(time.monotonic() - started)
    print(f"exit: {process.returncode} elapsed: {elapsed}s")
    return int(process.returncode or 0)


def bitbake_setup(build_dir: Path) -> str:
    return f". yocto/openembedded-core/oe-init-build-env {build_dir} >/dev/null"


def available_recipes(build_dir: Path) -> set[str]:
    rc, output = run_output(
        f"{bitbake_setup(build_dir)} && bitbake -s",
        label=f"scan available recipes in {build_dir}",
    )
    if rc != 0:
        print(f"WARN: failed to list recipes for {build_dir}")
        print(output[-4000:])
        return set()
    recipes: set[str] = set()
    for raw in output.splitlines():
        line = raw.strip()
        if not line or line.startswith(("Loading", "Loaded", "Parsing", "Recipe Name", "==")):
            continue
        name = line.split()[0]
        if name and (name[0].isalnum() or name[0] in "_-"):
            recipes.add(name)
    return recipes


def recipe_name(path: Path) -> str:
    name = path.name
    for suffix in (".bbappend", ".bb", ".inc"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name.split("_", 1)[0]


def recipe_dir_for(path: Path) -> Path | None:
    parts = path.parts
    for idx, part in enumerate(parts):
        if part.startswith("recipes-") and idx + 1 < len(parts):
            return Path(*parts[: idx + 2])
    return None


def recipes_for_path(raw: str) -> set[str]:
    path = Path(raw)
    recipes: set[str] = set()
    if path.suffix in {".bb", ".bbappend", ".inc"}:
        recipes.add(recipe_name(path))
    directory = recipe_dir_for(path)
    if directory and directory.exists():
        recipes.update(recipe_name(candidate) for candidate in directory.glob("*.bb"))
        recipes.update(recipe_name(candidate) for candidate in directory.glob("*.bbappend"))
        if not recipes and path.suffix == ".inc":
            recipes.add(recipe_name(path))
    return {recipe for recipe in recipes if recipe}


changed = run_lines(["git", "diff", "--name-only", "HEAD", "--"])
changed.extend(run_lines(["git", "ls-files", "--others", "--exclude-standard"]))
changed = sorted(set(changed))

recipes_by_path: dict[str, set[str]] = {}
for item in changed:
    recipes = recipes_for_path(item)
    if recipes:
        recipes_by_path[item] = recipes

recipes = sorted({recipe for values in recipes_by_path.values() for recipe in values})
build_dirs = sorted(path for path in Path("yocto").glob("build-*") if (path / "conf/bblayers.conf").exists())
available_by_build_dir: dict[Path, set[str]] = {}
recipes_by_build_dir: dict[Path, list[str]] = {}
if (recipes or IMAGE_RECIPES) and build_dirs:
    for build_dir in build_dirs:
        print(f"Scanning available recipes in {build_dir}...")
        available = available_recipes(build_dir)
        available_by_build_dir[build_dir] = available
        recipes_by_build_dir[build_dir] = [recipe for recipe in recipes if recipe in available]

print("Changed files:", len(changed))
for item in changed:
    suffix = ""
    if item in recipes_by_path:
        suffix = " -> " + ", ".join(sorted(recipes_by_path[item]))
    print("  " + item + suffix)

print()
print("Impacted Yocto recipes:", len(recipes))
for recipe in recipes:
    print("  " + recipe)

print()
if not recipes:
    print("No directly impacted Yocto recipes detected from changed layer paths.")
else:
    recipe_args = " ".join(recipes)
    print("Suggested commands:")
    for build_dir in build_dirs:
        build_recipes = recipes_by_build_dir.get(build_dir, [])
        image_recipes = [recipe for recipe in IMAGE_RECIPES if recipe in available_by_build_dir.get(build_dir, set())] if IMAGE_RECIPES else []
        if not build_recipes and not image_recipes:
            print(f"  # {build_dir}: no impacted recipes available here")
            continue
        build_recipe_args = " ".join(build_recipes)
        print(f"  cd /home/builder/workspace && {bitbake_setup(build_dir)}")
        if build_recipes:
            print(f"  bitbake -c cleansstate {build_recipe_args}")
            print(f"  bitbake {build_recipe_args}")
        if image_recipes:
            image_recipe_args = " ".join(image_recipes)
            print(f"  bitbake -c cleansstate {image_recipe_args}")
            print(f"  bitbake {image_recipe_args}")
    if TARGETS:
        print(f"  cd /home/builder/workspace && ninja {TARGETS}")
if IMAGE_RECIPES:
    print()
    print("Configured Yocto image recipes:", len(IMAGE_RECIPES))
    for image_recipe in IMAGE_RECIPES:
        print("  " + image_recipe)

if not build_dirs:
    print("No yocto/build-* directories with conf/bblayers.conf were found.")

if ACTION == "analyze":
    raise SystemExit(0)

if ACTION not in {"clean", "rebuild", "clean-rebuild"}:
    print("Unsupported Yocto impact action:", ACTION)
    raise SystemExit(2)

if not recipes and not IMAGE_RECIPES and ALLOW_EMPTY:
    print("No impacted Yocto recipes or configured image recipes; nothing to clean.")
    raise SystemExit(0)
if not recipes and not IMAGE_RECIPES:
    raise SystemExit(1)
if not build_dirs:
    raise SystemExit(1)

commands: list[tuple[str, str]] = []
for build_dir in build_dirs:
    build_recipes = recipes_by_build_dir.get(build_dir, [])
    image_recipes = [recipe for recipe in IMAGE_RECIPES if recipe in available_by_build_dir.get(build_dir, set())] if IMAGE_RECIPES else []
    if not build_recipes and not image_recipes:
        print(f"skip {build_dir}: no impacted recipes available here")
        continue
    setup = bitbake_setup(build_dir)
    recipe_args = " ".join(build_recipes)
    if build_recipes and ACTION in {"clean", "clean-rebuild"}:
        commands.append((f"cleansstate {build_dir}: {recipe_args}", f"{setup} && bitbake -c cleansstate {recipe_args}"))
    if build_recipes and ACTION in {"rebuild", "clean-rebuild"}:
        commands.append((f"rebuild {build_dir}: {recipe_args}", f"{setup} && bitbake {recipe_args}"))
    if image_recipes and ACTION in {"clean", "clean-rebuild"}:
        image_args = " ".join(image_recipes)
        commands.append((f"cleansstate images {build_dir}: {image_args}", f"{setup} && bitbake -c cleansstate {image_args}"))
    if image_recipes and ACTION in {"rebuild", "clean-rebuild"}:
        image_args = " ".join(image_recipes)
        commands.append((f"rebuild images {build_dir}: {image_args}", f"{setup} && bitbake {image_args}"))

if not commands and ALLOW_EMPTY:
    print("No build directory contains the impacted recipes; nothing to clean.")
    raise SystemExit(0)
if not commands:
    print("No build directory contains the impacted recipes.")
    raise SystemExit(1)

for index, (label, command) in enumerate(commands, start=1):
    rc = run_shell(command, label=label, step=index, total=len(commands))
    if rc != 0:
        raise SystemExit(rc)

raise SystemExit(0)
'''
        quoted_targets = " ".join(shlex.quote(target) for target in shlex.split(targets))
        quoted_image_recipes = " ".join(shlex.quote(recipe) for recipe in (image_recipes or []))
        script_targets = quoted_targets.replace("\\", "\\\\").replace('"', '\\"')
        script_action = action.replace("\\", "\\\\").replace('"', '\\"')
        script_image_recipes = quoted_image_recipes.replace("\\", "\\\\").replace('"', '\\"')
        script_allow_empty = "1" if allow_empty else "0"
        inner_script = (
            script.replace("__TARGETS__", script_targets)
            .replace("__ACTION__", script_action)
            .replace("__IMAGE_RECIPES__", script_image_recipes)
            .replace("__ALLOW_EMPTY__", script_allow_empty)
        )
        inner = "python3 -u - <<'PY'\n" + inner_script + "\nPY"
        return self.session_service.remote_shell_command(
            remote,
            project_dir,
            self.product_docker_command(project_dir, docker_image, inner),
        )

    def yocto_impact_command_for_config(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        targets: str,
        action: str = "analyze",
        image_recipes: list[str] | None = None,
        allow_empty: bool = False,
    ) -> list[str]:
        return self.yocto_impact_command(
            config_accessors.remote_spec_for_config(config),
            config_accessors.remote_project_dir_for_config(config),
            docker_image,
            targets,
            action=action,
            image_recipes=image_recipes if image_recipes is not None else config_accessors.yocto_image_recipes_for_config(config),
            allow_empty=allow_empty,
        )

    def status_command_for_config(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        structured_script: Callable[[list[tuple[str, str]]], str],
    ) -> list[str]:
        docker_cmd = (
            "docker image ls " + shlex.quote(f"{docker_image}:latest")
            if docker_image
            else "printf 'Docker image is not configured\\n'"
        )
        command = structured_script(
            [
                ("Project directory", "pwd"),
                ("Disk usage", "df -h ."),
                ("Git status", "git status --short --branch"),
                ("Docker image", docker_cmd),
            ]
        )
        return self.session_service.remote_shell_command(
            config_accessors.remote_spec_for_config(config),
            config_accessors.remote_project_dir_for_config(config),
            command,
        )

    def run_status_for_config(
        self,
        config: dict[str, Any],
        *,
        docker_image: str,
        structured_script: Callable[[list[tuple[str, str]]], str],
        runner: Callable[[list[str]], Any],
    ) -> None:
        runner(
            self.status_command_for_config(
                config,
                docker_image=docker_image,
                structured_script=structured_script,
            )
        )

def remote_build_command_service() -> RemoteBuildCommandService:
    return RemoteBuildCommandService()
