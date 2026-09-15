"""Remote project discovery service."""

from __future__ import annotations

import shlex
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from components.config.api import accessors as config_accessors


def _normalize_mapping_path(path: str) -> str:
    clean = path.strip().replace("\\", "/")
    while clean.startswith("./"):
        clean = clean[2:]
    while "//" in clean:
        clean = clean.replace("//", "/")
    return clean.strip("/")


class RemoteProjectDiscoveryService:
    """Own remote project inspection commands and their parsers."""

    def build_project_file_read_command(self, remote: str, project_dir: str, path: str) -> list[str]:
        target = path if Path(path).is_absolute() else f"./{path.lstrip('./')}"
        script = f"cd {shlex.quote(project_dir)} && cat -- {shlex.quote(target)}"
        return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", remote, script]

    def build_project_file_read_command_for_config(self, config: dict[str, Any], path: str) -> list[str]:
        return self.build_project_file_read_command(
            config_accessors.remote_spec_for_config(config),
            config_accessors.remote_project_dir_for_config(config),
            path,
        )

    def read_project_file_for_config(
        self,
        config: dict[str, Any],
        path: str,
        runner: Callable[[list[str]], str],
    ) -> str:
        return runner(self.build_project_file_read_command_for_config(config, path))

    def project_file_reader(self, runner: Callable[[list[str]], str]) -> Callable[[dict[str, Any], str], str]:
        return lambda config, path: self.read_project_file_for_config(config, path, runner)

    def build_inventory_command(self, project_dir: str, excludes: list[str], max_depth: int) -> str:
        prune_parts = []
        for pattern in excludes:
            if pattern.endswith("/"):
                prune_parts.append(f"-path {shlex.quote('./' + pattern.rstrip('/'))}")
        prune = " -o ".join(prune_parts)
        prune_expr = f"\\( {prune} \\) -prune -o " if prune else ""
        return (
            f"cd {shlex.quote(project_dir)} && "
            f"find . -mindepth 1 -maxdepth {int(max_depth)} {prune_expr}"
            "-type d -print | sed 's#^./##' | sort"
        )

    def build_inventory_command_for_config(self, config: dict[str, Any]) -> str:
        max_depth = int(config["inventory"].get("max_depth", 5))
        return self.build_inventory_command(
            config_accessors.remote_project_dir_for_config(config),
            config.get("exclude", []),
            max_depth,
        )

    def build_inventory_fetch_command_for_config(self, config: dict[str, Any]) -> list[str]:
        return ["ssh", config_accessors.remote_spec_for_config(config), self.build_inventory_command_for_config(config)]

    def _build_find_prune_expr(self, excludes: list[str]) -> str:
        prune_parts = []
        for pattern in excludes:
            if pattern.endswith("/"):
                clean = pattern.rstrip("/")
                prune_parts.append(f"-path {shlex.quote('./' + clean)}")
                prune_parts.append(f"-path {shlex.quote('./' + clean + '/*')}")
                prune_parts.append(f"-name {shlex.quote(PurePosixPath(clean).name)}")
            else:
                prune_parts.append(f"-name {shlex.quote(pattern)}")
        prune = " -o ".join(prune_parts)
        return f"\\( {prune} \\) -prune -o " if prune else ""

    def build_project_tree_command(self, project_dir: str, excludes: list[str], depth: int) -> str:
        depth = max(1, min(depth, 99))
        prune_expr = self._build_find_prune_expr(excludes)
        return (
            f"cd {shlex.quote(project_dir)} && "
            f"find . -mindepth 1 -maxdepth {depth} {prune_expr}"
            "-type d -printf 'd\\t%P\\n' | sort -k2"
        )

    def build_project_tree_command_for_config(self, config: dict[str, Any], depth: int) -> str:
        return self.build_project_tree_command(
            config_accessors.remote_project_dir_for_config(config),
            config.get("exclude", []),
            depth,
        )

    def build_project_tree_fetch_command_for_config(self, config: dict[str, Any], depth: int) -> list[str]:
        return [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            config_accessors.remote_spec_for_config(config),
            self.build_project_tree_command_for_config(config, depth),
        ]

    def fetch_project_tree_for_config(
        self,
        config: dict[str, Any],
        depth: int,
        runner: Callable[[list[str]], str],
    ) -> list[dict[str, str]]:
        return self.parse_project_tree_output(runner(self.build_project_tree_fetch_command_for_config(config, depth)))

    def build_project_listing_command(self, project_dir: str, excludes: list[str], directory: str) -> str:
        find_root = "." if directory == "." else f"./{directory}"
        prune_expr = self._build_find_prune_expr(excludes)
        return (
            f"cd {shlex.quote(project_dir)} && "
            f"find {shlex.quote(find_root)} -mindepth 1 -maxdepth 1 {prune_expr}"
            "\\( -type d -printf 'd\\t%p\\n' -o -type f -printf 'f\\t%p\\n' -o -type l -printf 'l\\t%p\\n' \\) "
            "| sed 's#\\t\\./#\\t#' | sort -k1,1 -k2,2"
        )

    def build_project_listing_command_for_config(self, config: dict[str, Any], directory: str) -> str:
        return self.build_project_listing_command(
            config_accessors.remote_project_dir_for_config(config),
            config.get("exclude", []),
            directory,
        )

    def build_project_listing_fetch_command_for_config(self, config: dict[str, Any], directory: str) -> list[str]:
        return [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            config_accessors.remote_spec_for_config(config),
            self.build_project_listing_command_for_config(config, _normalize_mapping_path(directory)),
        ]

    def fetch_project_listing_for_config(
        self,
        config: dict[str, Any],
        directory: str,
        runner: Callable[[list[str]], str],
    ) -> list[dict[str, str]]:
        return self.parse_project_listing_output(runner(self.build_project_listing_fetch_command_for_config(config, directory)))

    def build_remote_child_dirs_fetch_command(self, remote: str, path: str) -> list[str]:
        quoted = "$HOME" if path == "~" else shlex.quote(path)
        script = f"cd {quoted} && find . -mindepth 1 -maxdepth 1 -type d -printf '%P\\n' | sort"
        return ["ssh", remote, script]

    def build_remote_child_dirs_fetch_command_for_config(self, config: dict[str, Any], path: str) -> list[str]:
        return self.build_remote_child_dirs_fetch_command(config_accessors.remote_spec_for_config(config), path)

    def parse_remote_child_dirs_output(self, path: str, output: str) -> list[str]:
        base = path.rstrip("/") if path != "~" else "~"
        return [f"{base}/{line.strip()}".replace("//", "/") for line in output.splitlines() if line.strip()]

    def fetch_remote_child_dirs_for_config(
        self,
        config: dict[str, Any],
        path: str,
        runner: Callable[[list[str]], str],
    ) -> list[str]:
        return self.parse_remote_child_dirs_output(
            path,
            runner(self.build_remote_child_dirs_fetch_command_for_config(config, path)),
        )

    def build_remote_home_fetch_command(self, remote: str) -> list[str]:
        return ["ssh", remote, "printf '%s\\n' \"$HOME\""]

    def build_remote_home_fetch_command_for_config(self, config: dict[str, Any]) -> list[str]:
        return self.build_remote_home_fetch_command(config_accessors.remote_spec_for_config(config))

    def remote_home_from_output(self, output: str) -> str:
        return output.strip() or "~"

    def fetch_remote_home_for_config(self, config: dict[str, Any], runner: Callable[[list[str]], str]) -> str:
        return self.remote_home_from_output(runner(self.build_remote_home_fetch_command_for_config(config)))

    def remote_parent_dir(self, path: str, home: str = "~") -> str:
        if path in ("", "/"):
            return path or "~"
        if path == "~":
            parent = str(PurePosixPath(home).parent)
            return parent if parent else "/"
        if path.startswith("~/"):
            rest = path[2:].rstrip("/")
            parent = str(PurePosixPath(rest).parent)
            return "~" if parent == "." else f"~/{parent}"
        parent = str(PurePosixPath(path.rstrip("/")).parent)
        return parent if parent else "/"

    def parse_project_tree_output(self, output: str) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        for raw in output.splitlines():
            kind_code, _, path = raw.partition("\t")
            path = path.strip()
            if kind_code == "d" and path:
                entries.append({"path": _normalize_mapping_path(path), "kind": "directory"})
        return entries

    def parse_project_listing_output(self, output: str) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        for raw in output.splitlines():
            kind_code, _, path = raw.partition("\t")
            path = path.strip()
            if not path:
                continue
            kind = "directory" if kind_code == "d" else "file"
            entries.append({"path": _normalize_mapping_path(path), "kind": kind})
        return entries

    def parse_git_tracked_files(self, output: str) -> list[str]:
        return [line.strip() for line in output.splitlines() if line.strip()]

    def build_git_tracked_files_fetch_command_for_config(self, config: dict[str, Any]) -> list[str]:
        script = f"cd {shlex.quote(config_accessors.remote_project_dir_for_config(config))} && git ls-files"
        return [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            config_accessors.remote_spec_for_config(config),
            script,
        ]

    def fetch_git_tracked_files_for_config(
        self,
        config: dict[str, Any],
        runner: Callable[[list[str]], str],
    ) -> list[str]:
        return self.parse_git_tracked_files(runner(self.build_git_tracked_files_fetch_command_for_config(config)))

    def root_yaml_candidates(self, paths: list[str]) -> list[str]:
        return [
            path
            for path in paths
            if "/" not in path and path.lower().endswith((".yaml", ".yml"))
        ]

    def dockerfile_candidates(self, paths: list[str]) -> list[str]:
        candidates: list[str] = []
        for path in paths:
            name = PurePosixPath(path).name.lower()
            if name == "dockerfile" or name.startswith("dockerfile.") or name.endswith(".dockerfile"):
                candidates.append(path)
        return candidates

    def validate_dockerfile_text(self, text: str) -> tuple[bool, str]:
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.upper().startswith("FROM "):
                return True, stripped
            return False, "first instruction is not FROM"
        return False, "empty file"

    def build_git_branch_list_fetch_command(self, remote: str, git_url: str) -> list[str]:
        script = f"git ls-remote --heads --refs {shlex.quote(git_url)}"
        return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", remote, script]

    def build_git_branch_list_fetch_command_for_config(self, config: dict[str, Any], git_url: str) -> list[str]:
        return self.build_git_branch_list_fetch_command(config_accessors.remote_spec_for_config(config), git_url)

    def parse_git_branch_list_output(self, output: str) -> list[str]:
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

    def fetch_git_branches_for_config(
        self,
        config: dict[str, Any],
        git_url: str,
        runner: Callable[[list[str]], str],
    ) -> list[str]:
        return self.parse_git_branch_list_output(
            runner(self.build_git_branch_list_fetch_command_for_config(config, git_url))
        )


def remote_project_discovery_service() -> RemoteProjectDiscoveryService:
    return RemoteProjectDiscoveryService()
