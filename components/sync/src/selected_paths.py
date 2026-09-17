"""Selected project-path sync command service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from components.config.api import accessors as config_accessors
from components.project.api import inventory as project_inventory_api
from components.project.api import model as project_model_api


class SyncSelectedPathService:
    """Own rsync use cases for explicitly selected project tree paths."""

    def __init__(
        self,
        *,
        inventory_service: project_inventory_api.ProjectInventoryService | None = None,
        model_service: project_model_api.ProjectMappingModelService | None = None,
    ) -> None:
        self.inventory_service = inventory_service or project_inventory_api.project_inventory_service()
        self.model_service = model_service or project_model_api.project_mapping_model_service()

    def read_selected_paths(self, selection_path: Path) -> list[str]:
        return self.inventory_service.read_selection_file(
            selection_path,
            normalize_path=self.model_service.normalize_relpath,
        )

    def rsync_excludes_for_config(self, config: dict[str, Any]) -> list[str]:
        args: list[str] = []
        for pattern in config.get("exclude", []):
            args.extend(["--exclude", pattern])
        return args

    def remote_base_for_config(self, config: dict[str, Any]) -> str:
        return f"{config_accessors.remote_spec_for_config(config)}:{config_accessors.remote_project_dir_for_config(config)}"

    def build_rsync_path_args(self, paths: list[str], base: str) -> list[str]:
        return [f"{base}/./{path}" for path in paths]

    def selected_paths_pull_command_for_config(
        self,
        config: dict[str, Any],
        paths: list[str],
        *,
        dry_run: bool,
        app_dir: Path,
    ) -> list[str]:
        local_dir = config_accessors.local_project_dir_for_config(config, app_dir)
        local_dir.mkdir(parents=True, exist_ok=True)
        argv = ["rsync", "-az", "--relative", "--delete"]
        if dry_run:
            argv.extend(["--dry-run", "--itemize-changes"])
        else:
            argv.extend(["--progress", "--stats", "--human-readable"])
        argv.extend(self.rsync_excludes_for_config(config))
        argv.extend(self.build_rsync_path_args(paths, self.remote_base_for_config(config)))
        argv.append(str(local_dir) + "/")
        return argv

    def selected_paths_push_command_for_config(
        self,
        config: dict[str, Any],
        paths: list[str],
        *,
        dry_run: bool,
        app_dir: Path,
    ) -> list[str]:
        local_dir = config_accessors.local_project_dir_for_config(config, app_dir)
        missing = [path for path in paths if not (local_dir / path).exists()]
        if missing:
            raise SystemExit("local selected paths are missing:\n" + "\n".join(missing))
        argv = ["rsync", "-az", "--relative", "--delete"]
        if dry_run:
            argv.extend(["--dry-run", "--itemize-changes"])
        else:
            argv.extend(["--progress", "--stats", "--human-readable"])
        argv.extend(self.rsync_excludes_for_config(config))
        argv.extend(self.build_rsync_path_args(paths, str(local_dir)))
        argv.append(self.remote_base_for_config(config) + "/")
        return argv

    def run_selected_paths_pull_for_config(
        self,
        config: dict[str, Any],
        selection_path: Path,
        *,
        dry_run: bool,
        app_dir: Path,
        runner: Callable[[list[str]], Any],
    ) -> None:
        runner(
            self.selected_paths_pull_command_for_config(
                config,
                self.read_selected_paths(selection_path),
                dry_run=dry_run,
                app_dir=app_dir,
            )
        )

    def run_selected_paths_push_for_config(
        self,
        config: dict[str, Any],
        selection_path: Path,
        *,
        dry_run: bool,
        app_dir: Path,
        runner: Callable[[list[str]], Any],
    ) -> None:
        runner(
            self.selected_paths_push_command_for_config(
                config,
                self.read_selected_paths(selection_path),
                dry_run=dry_run,
                app_dir=app_dir,
            )
        )


def sync_selected_path_service(
    *,
    inventory_service: project_inventory_api.ProjectInventoryService | None = None,
    model_service: project_model_api.ProjectMappingModelService | None = None,
) -> SyncSelectedPathService:
    return SyncSelectedPathService(
        inventory_service=inventory_service,
        model_service=model_service,
    )
