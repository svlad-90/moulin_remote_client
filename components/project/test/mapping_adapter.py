"""Test adapter for legacy project mapping helper assertions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from components.project.src.core import ProjectMappingCoreService, project_mapping_core_service
from components.project.src.inventory import ProjectInventoryService, project_inventory_service
from components.project.src.model import project_mapping_model_service
from components.project.src.overlay import project_overlay_validation_service
from components.project.src.presentation import project_mapping_presentation_service
from components.project.src.selection import ProjectMappingSelectionService


def is_project_cli_command(command: str) -> bool:
    return project_cli_workflow_service().supports_cli_command(command)


def normalize_relpath(path: str) -> str:
    return project_mapping_model_service().normalize_relpath(path)


def normalize_mapping_path(path: str) -> str:
    return project_mapping_model_service().normalize_mapping_path(path)


def is_descendant_mapping_path(path: str, parent: str) -> bool:
    return project_mapping_model_service().is_descendant_mapping_path(path, parent)


def mapping_path_mark(path: str, selected_paths: set[str], mapped_paths: set[str]) -> str:
    return project_mapping_presentation_service().mapping_path_mark(path, selected_paths, mapped_paths)


def mapping_name_from_path(path: str) -> str:
    return project_mapping_presentation_service().mapping_name_from_path(path)


def mapping_draft_for_entry(entry: dict[str, str]) -> dict[str, Any]:
    return project_mapping_presentation_service().mapping_draft_for_entry(entry)


def refresh_mapping_draft_for_entry(draft: dict[str, Any], entry: dict[str, str]) -> dict[str, Any]:
    return project_mapping_presentation_service().refresh_mapping_draft_for_entry(draft, entry)


def mapping_path_sets(
    raw_project_mappings: list[Any],
    selected_names: set[str],
) -> tuple[set[str], set[str]]:
    return project_mapping_presentation_service().mapping_path_sets(raw_project_mappings, selected_names)


def mapping_state_label(path: str, selected_paths: set[str], mapped_paths: set[str]) -> str:
    return project_mapping_presentation_service().mapping_state_label(path, selected_paths, mapped_paths)


def listing_with_parent_entry(current_dir: str, entries: list[dict[str, str]]) -> list[dict[str, str]]:
    return project_mapping_presentation_service().listing_with_parent_entry(current_dir, entries)


def mapping_browser_path_state(config: dict[str, Any], selection_path: Path) -> dict[str, Any]:
    return project_browser_workflow_service().path_state(config, selection_path)


def mapping_browser_entry_name(entry: dict[str, str]) -> str:
    return project_mapping_presentation_service().mapping_browser_entry_name(entry)


def mapping_browser_entry_kind(entry: dict[str, str]) -> str:
    return project_mapping_presentation_service().mapping_browser_entry_kind(entry)


def mapping_browser_entry_label(
    entry: dict[str, str],
    *,
    selected_paths: set[str],
    mapped_paths: set[str],
) -> str:
    return project_mapping_presentation_service().mapping_browser_entry_label(
        entry,
        selected_paths=selected_paths,
        mapped_paths=mapped_paths,
    )


def mapping_browser_current_entry(entries: list[dict[str, str]], index: int) -> dict[str, str]:
    return project_browser_workflow_service().current_entry(entries, index)


def normalize_mappings(raw_source: list[Any]) -> list[dict[str, Any]]:
    return project_mapping_model_service().normalize_mappings(raw_source)


def mappings_from_project_config(project: dict[str, Any], legacy_mappings: list[Any]) -> list[dict[str, Any]]:
    return project_mapping_model_service().mappings_from_project_config(project, legacy_mappings)


def mappings_for_config(config: dict[str, Any]) -> list[dict[str, Any]]:
    return project_mapping_service().mappings_for_config(config)


class ProjectMappingService(ProjectMappingCoreService, ProjectMappingSelectionService):
    """Compatibility service for project mapping APIs."""

    def __init__(self) -> None:
        ProjectMappingCoreService.__init__(self)
        ProjectMappingSelectionService.__init__(self, mapping_service=self)


def project_mapping_service() -> ProjectMappingService:
    return ProjectMappingService()


from components.project.src.browser_workflow import ProjectBrowserWorkflowService


def project_browser_workflow_service() -> ProjectBrowserWorkflowService:
    from components.project.src import browser_workflow

    return browser_workflow.project_browser_workflow_service()


def add_mapping_to_active_project(
    config: dict[str, Any],
    *,
    name: str,
    role: str,
    remote: str,
    local: str,
    kind: str,
    push: bool,
) -> dict[str, Any]:
    return project_mapping_service().add_mapping_to_active_project(
        config,
        name=name,
        role=role,
        remote=remote,
        local=local,
        kind=kind,
        push=push,
    )


def store_mapping_for_config(
    config: dict[str, Any],
    selection_path: Path,
    *,
    name: str,
    role: str,
    remote: str,
    local: str,
    kind: str,
    push: bool,
    save_config: Callable[[dict[str, Any]], Any],
) -> dict[str, Any]:
    return project_mapping_service().store_mapping_for_config(
        config,
        selection_path,
        name=name,
        role=role,
        remote=remote,
        local=local,
        kind=kind,
        push=push,
        save_config=save_config,
    )


def store_mapping_action_for_config(
    config: dict[str, Any],
    selection_path: Path,
    *,
    name: str,
    role: str,
    remote: str,
    local: str,
    kind: str,
    push: bool,
    save_config: Callable[[dict[str, Any]], Any],
) -> dict[str, Any]:
    return project_mapping_service().store_mapping_action_for_config(
        config,
        selection_path,
        name=name,
        role=role,
        remote=remote,
        local=local,
        kind=kind,
        push=push,
        save_config=save_config,
    )


def store_mapping_from_tree_entry_action_for_config(
    config: dict[str, Any],
    selection_path: Path,
    entry: dict[str, str],
    *,
    name: str,
    local: str,
    role: str,
    push: bool,
    save_config: Callable[[dict[str, Any]], Any],
) -> dict[str, Any]:
    return project_mapping_service().store_mapping_from_tree_entry_action_for_config(
        config,
        selection_path,
        entry,
        name=name,
        local=local,
        role=role,
        push=push,
        save_config=save_config,
    )


def remove_mapping_from_active_project_by_name(config: dict[str, Any], name: str) -> bool:
    return project_mapping_service().remove_mapping_from_active_project_by_name(config, name)


def remove_mapping_from_active_project_by_remote_path(config: dict[str, Any], remote_path: str) -> list[str]:
    return project_mapping_service().remove_mapping_from_active_project_by_remote_path(config, remote_path)


def remove_mapping_by_remote_path_for_config(
    config: dict[str, Any],
    selection_path: Path,
    remote_path: str,
    *,
    save_config: Callable[[dict[str, Any]], Any],
) -> list[str]:
    return project_mapping_service().remove_mapping_by_remote_path_for_config(
        config,
        selection_path,
        remote_path,
        save_config=save_config,
    )


def remove_mapping_by_remote_path_action_for_config(
    config: dict[str, Any],
    selection_path: Path,
    remote_path: str,
    *,
    save_config: Callable[[dict[str, Any]], Any],
) -> dict[str, Any]:
    return project_mapping_service().remove_mapping_by_remote_path_action_for_config(
        config,
        selection_path,
        remote_path,
        save_config=save_config,
    )


def mapping_browser_toggle_action_for_config(
    config: dict[str, Any],
    selection_path: Path,
    entry: dict[str, str],
    draft: dict[str, Any],
    *,
    mapped_paths: set[str],
    save_config: Callable[[dict[str, Any]], Any],
) -> dict[str, Any]:
    return project_browser_workflow_service().toggle_action_for_config(
        config,
        selection_path,
        entry,
        draft,
        mapped_paths=mapped_paths,
        save_config=save_config,
    )


def mapping_browser_key_action(
    *,
    entries_exist: bool,
    current_kind: str,
    up: bool = False,
    down: bool = False,
    enter: bool = False,
    toggle: bool = False,
    edit_name: bool = False,
    edit_local: bool = False,
    edit_role: bool = False,
    edit_push: bool = False,
    quit_key: bool = False,
) -> dict[str, Any]:
    return project_browser_workflow_service().key_action(
        entries_exist=entries_exist,
        current_kind=current_kind,
        up=up,
        down=down,
        enter=enter,
        toggle=toggle,
        edit_name=edit_name,
        edit_local=edit_local,
        edit_role=edit_role,
        edit_push=edit_push,
        quit_key=quit_key,
    )


def mapping_selection_screen_state_for_config(config: dict[str, Any], selection_path: Path) -> dict[str, Any]:
    return project_mapping_service().mapping_selection_screen_state_for_config(config, selection_path)


def mapping_selection_row_label(mapping: dict[str, Any], selected: set[str]) -> str:
    return project_mapping_presentation_service().mapping_selection_row_label(mapping, selected)


def mapping_selection_detail_for_config(
    config: dict[str, Any],
    app_dir: Path,
    mapping: dict[str, Any],
    *,
    selected_count: int,
    total_count: int,
) -> dict[str, str]:
    return project_mapping_presentation_service().mapping_selection_detail_for_config(
        config,
        app_dir,
        mapping,
        selected_count=selected_count,
        total_count=total_count,
    )


def _store_ordered_mapping_selection(
    config: dict[str, Any],
    selection_path: Path,
    all_mappings: list[dict[str, Any]],
    selected: set[str],
    *,
    save_config: Callable[[dict[str, Any]], Any],
) -> list[str]:
    return project_mapping_service().store_ordered_mapping_selection(
        config,
        selection_path,
        all_mappings,
        selected,
        save_config=save_config,
    )


def toggle_mapping_selection_for_config(
    config: dict[str, Any],
    selection_path: Path,
    all_mappings: list[dict[str, Any]],
    selected: set[str],
    index: int,
    *,
    save_config: Callable[[dict[str, Any]], Any],
) -> dict[str, Any]:
    return project_mapping_service().toggle_mapping_selection_for_config(
        config,
        selection_path,
        all_mappings,
        selected,
        index,
        save_config=save_config,
    )


def select_all_mappings_for_config(
    config: dict[str, Any],
    selection_path: Path,
    all_mappings: list[dict[str, Any]],
    *,
    save_config: Callable[[dict[str, Any]], Any],
) -> dict[str, Any]:
    return project_mapping_service().select_all_mappings_for_config(
        config,
        selection_path,
        all_mappings,
        save_config=save_config,
    )


def clear_mapping_selection_for_config(
    config: dict[str, Any],
    selection_path: Path,
    *,
    save_config: Callable[[dict[str, Any]], Any],
) -> dict[str, Any]:
    return project_mapping_service().clear_mapping_selection_for_config(
        config,
        selection_path,
        save_config=save_config,
    )


def delete_mapping_selection_action_for_config(
    config: dict[str, Any],
    selection_path: Path,
    name: str,
    *,
    save_config: Callable[[dict[str, Any]], Any],
) -> dict[str, Any]:
    return project_mapping_service().delete_mapping_selection_action_for_config(
        config,
        selection_path,
        name,
        save_config=save_config,
    )


def mapping_selection_key_action(
    *,
    mappings_exist: bool,
    up: bool = False,
    down: bool = False,
    toggle: bool = False,
    delete: bool = False,
    all_key: bool = False,
    none_key: bool = False,
    add_key: bool = False,
    close_key: bool = False,
) -> dict[str, Any]:
    return project_mapping_service().mapping_selection_key_action(
        mappings_exist=mappings_exist,
        up=up,
        down=down,
        toggle=toggle,
        delete=delete,
        all_key=all_key,
        none_key=none_key,
        add_key=add_key,
        close_key=close_key,
    )


def select_mappings_from(
    all_mappings: list[dict[str, Any]],
    names: list[str],
) -> list[dict[str, Any]]:
    return project_mapping_service().select_mappings_from(all_mappings, names)


def select_mappings_for_config(config: dict[str, Any], names: list[str]) -> list[dict[str, Any]]:
    return project_mapping_service().select_mappings_for_config(config, names)


def active_mapping_state_for_config(
    config: dict[str, Any],
    selection_path: Path,
) -> tuple[list[str], list[dict[str, Any]], str | None]:
    return project_mapping_service().active_mapping_state_for_config(config, selection_path)


def project_mapping_selection_from(project: dict[str, Any]) -> list[str]:
    return project_mapping_service().project_mapping_selection_from(project)


def parse_ranges(raw: str, limit: int) -> list[int]:
    return project_inventory_service().parse_ranges(raw, limit)


def read_selection_file(path: Path) -> list[str]:
    return project_inventory_service().read_selection_file(path, normalize_path=normalize_relpath)


def write_selection_file(path: Path, paths: list[str]) -> None:
    project_inventory_service().write_selection_file(path, paths)


def parse_inventory_text(text: str) -> list[str]:
    return project_inventory_service().parse_inventory_text(text)


def format_inventory_choices(paths: list[str]) -> list[str]:
    return project_inventory_service().format_inventory_choices(paths)


def selected_paths_from_inventory_input(raw: str, paths: list[str]) -> list[str]:
    return project_inventory_service().selected_paths_from_inventory_input(raw, paths)


def run_inventory_fetch(
    output_path: Path,
    *,
    fetch_inventory_text: Callable[[], str],
    write_line: Callable[[str], Any],
) -> None:
    project_inventory_service().run_inventory_fetch(
        output_path,
        fetch_inventory_text=fetch_inventory_text,
        write_line=write_line,
    )


def run_inventory_choose(
    inventory_path: Path,
    selection_path: Path,
    *,
    read_input: Callable[[str], str],
    write_line: Callable[[str], Any],
) -> None:
    project_inventory_service().run_inventory_choose(
        inventory_path,
        selection_path,
        read_input=read_input,
        write_line=write_line,
    )


def local_mapping_issue(local_base: Path, mapping: dict[str, Any]) -> str | None:
    return project_overlay_validation_service().local_mapping_issue(local_base, mapping)


def local_mapping_issues(local_base: Path, active_mappings: list[dict[str, Any]]) -> list[str]:
    return project_overlay_validation_service().local_mapping_issues(local_base, active_mappings)


def read_mapping_selection_file(path: Path, *, required: bool) -> list[str]:
    return project_mapping_service().read_mapping_selection_file(path, required=required)


def read_mapping_selection_from(project: dict[str, Any], path: Path, *, required: bool) -> list[str]:
    return project_mapping_service().read_mapping_selection_from(project, path, required=required)


def read_mapping_selection_for_config(config: dict[str, Any], path: Path, *, required: bool) -> list[str]:
    return project_mapping_service().read_mapping_selection_for_config(config, path, required=required)


def write_mapping_selection_file(path: Path, names: list[str]) -> None:
    project_mapping_service().write_mapping_selection_file(path, names)


def write_mapping_selection_for_config(config: dict[str, Any], path: Path, names: list[str]) -> None:
    project_mapping_service().write_mapping_selection_for_config(config, path, names)


def store_mapping_selection_for_config(
    config: dict[str, Any],
    path: Path,
    names: list[str],
    *,
    save_config: Callable[[dict[str, Any]], Any],
    write_line: Callable[[str], Any] | None = None,
) -> None:
    project_mapping_service().store_mapping_selection_for_config(
        config,
        path,
        names,
        save_config=save_config,
        write_line=write_line,
    )


from components.project.src.cli_workflow import ProjectCliWorkflowService


def project_cli_workflow_service() -> ProjectCliWorkflowService:
    from components.project.src import cli_workflow

    return cli_workflow.project_cli_workflow_service()


def format_mapping_listing_for_config(config: dict[str, Any], selection_path: Path, app_dir: Path) -> list[str]:
    return project_cli_workflow_service().format_mapping_listing_for_config(config, selection_path, app_dir)


def format_mapping_selection_prompt_for_config(config: dict[str, Any], selection_path: Path, app_dir: Path) -> list[str]:
    return project_cli_workflow_service().format_mapping_selection_prompt_for_config(config, selection_path, app_dir)


def mapping_names_from_selection_input(raw: str, all_mappings: list[dict[str, Any]]) -> list[str] | None:
    return project_cli_workflow_service().mapping_names_from_selection_input(raw, all_mappings)


def run_mapping_listing_for_config(
    config: dict[str, Any],
    selection_path: Path,
    app_dir: Path,
    *,
    write_line: Callable[[str], Any],
) -> None:
    project_cli_workflow_service().run_mapping_listing_for_config(
        config,
        selection_path,
        app_dir,
        write_line=write_line,
    )


def run_project_status_for_config(
    config: dict[str, Any],
    app_dir: Path,
    *,
    remote_probe_command: list[str],
    local_runner: Callable[[list[str]], Any],
    remote_runner: Callable[[list[str]], Any],
    write_line: Callable[[str], Any],
) -> None:
    project_cli_workflow_service().run_project_status_for_config(
        config,
        app_dir,
        remote_probe_command=remote_probe_command,
        local_runner=local_runner,
        remote_runner=remote_runner,
        write_line=write_line,
    )


def run_mapping_selection_for_config(
    config: dict[str, Any],
    selection_path: Path,
    app_dir: Path,
    *,
    read_input: Callable[[str], str],
    write_line: Callable[[str], Any],
    save_config: Callable[[dict[str, Any]], Any],
) -> None:
    project_cli_workflow_service().run_mapping_selection_for_config(
        config,
        selection_path,
        app_dir,
        read_input=read_input,
        write_line=write_line,
        save_config=save_config,
    )


def run_cli_project_command_for_config(
    config: dict[str, Any],
    command: str,
    *,
    app_dir: Path,
    docker_image: str,
    structured_script: Callable[[list[tuple[str, str]]], str],
    capture_command: Callable[[list[str]], str],
    local_runner: Callable[[list[str]], Any],
    remote_runner: Callable[[list[str]], Any],
    read_input: Callable[[str], str],
    write_line: Callable[[str], Any],
    save_config: Callable[[dict[str, Any]], Any],
) -> None:
    project_cli_workflow_service().run_cli_project_command_for_config(
        config,
        command,
        app_dir=app_dir,
        docker_image=docker_image,
        structured_script=structured_script,
        capture_command=capture_command,
        local_runner=local_runner,
        remote_runner=remote_runner,
        read_input=read_input,
        write_line=write_line,
        save_config=save_config,
    )
