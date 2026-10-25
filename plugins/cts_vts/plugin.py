"""CTS and VTS plugin entry point."""

from __future__ import annotations

import curses
import json
import queue
import shlex
import threading
import time
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from components.board_types.api.base import BoardCapability
from components.config.api.store import EntityRef
from components.host_config.api import fields as config_field_api
from components.plugins.api.model import plugin_config
from components.plugins.api.runtime import PluginLogPanel
from components.product_types.api.base import ProductCapability
from components.ui.api import input as ui_input_api

from . import commands, config_entities, downloads, model


def config_contributor() -> config_entities.CtsVtsConfigContributor:
    """Expose CTS/VTS entities and references to the shared config store."""

    return config_entities.config_contributor()


def _delete_entity(
    context: Any,
    *,
    kind: str,
    record: dict[str, Any],
    title: str,
    question: str,
    warning: str,
) -> bool:
    plan = context.config_store.prepare_delete(EntityRef(kind, model.record_id(record)))
    if plan.blockers:
        context.dialogs.message(
            f"{plan.target_label} is in use",
            ["Dependent configuration must be removed first:"]
            + [f"- {impact.link.description}" for impact in plan.blockers],
        )
        return False
    updates = list(dict.fromkeys(impact.link.description for impact in plan.updates))
    full_warning = warning
    if updates:
        full_warning += "\n\nDependent configuration will be updated:\n" + "\n".join(
            f"- {value}" for value in updates
        )
    if not context.dialogs.confirm(title, question, warning=full_warning):
        return False
    context.config_store.execute_delete(plan)
    return True


def migrate_config(root: dict[str, Any]) -> bool:
    """Migrate persisted CTS/VTS data during the application load stage."""

    before = deepcopy(root.get("plugins"))
    config = plugin_config(root, "cts-vts")
    model.migrate_state(config)

    def resolve(reference: Any, profiles: list[dict[str, Any]]) -> str:
        value = str(reference or "")
        for profile in profiles:
            profile_id = str(profile.get("id") or "")
            source_name = str(profile.get("name") or "")
            if value in {profile_id, source_name}:
                return profile_id
        return value

    build_hosts = [item for item in root.get("remotes", []) if isinstance(item, dict)]
    projects = [item for item in root.get("projects", []) if isinstance(item, dict)]
    boards = [
        board
        for host in root.get("board_hosts", [])
        if isinstance(host, dict)
        for board in host.get("boards", [])
        if isinstance(board, dict)
    ]
    for profile in model.records(config, "board_profiles"):
        for device in profile.get("devices", []):
            if isinstance(device, dict):
                device["board_id"] = resolve(device.get("board_id"), boards)
    for profile in model.records(config, "product_profiles"):
        profile["build_host"] = resolve(profile.get("build_host"), build_hosts)
        profile["project"] = resolve(profile.get("project"), projects)
    return before != root.get("plugins")


def _create_entity(
    context: Any,
    kind: str,
    registry: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    result = context.config_store.create_entity(kind, values)
    record = model.find(context.config, registry, result.reference.entity_id)
    if record is None:
        raise RuntimeError(f"created entity is not visible in plugin configuration: {kind}")
    return record


def _update_entity(
    context: Any,
    kind: str,
    registry: str,
    record: dict[str, Any],
    changes: dict[str, Any],
) -> None:
    context.config_store.update_entity(EntityRef(kind, model.record_id(record)), changes)


def _replace_reference(
    context: Any,
    adapter_name: str,
    source: EntityRef,
    target_kind: str,
    target_ids: list[str] | tuple[str, ...],
) -> None:
    context.config_store.replace_references(
        adapter_name,
        source,
        tuple(EntityRef(target_kind, target_id) for target_id in target_ids),
    )
def _prompt(context: Any, label: str, current: Any = "") -> str:
    return context.dialogs.prompt(label, str(current))


def _names(context: Any, key: str) -> str:
    return ", ".join(str(item.get("name")) for item in model.records(context.config, key)) or "not configured"


def _record_name(context: Any, key: str, reference: Any) -> str:
    record = model.find(context.config, key, str(reference or ""))
    return str((record or {}).get("name") or reference or "")


def _external_name(profiles: Any, id_attr: str, reference: Any) -> str:
    value = str(reference or "")
    for profile in profiles:
        if str(getattr(profile, id_attr, "") or "") == value:
            values = getattr(profile, "values", {})
            source_name = str(values.get("name") or "") if hasattr(values, "get") else ""
            return str(getattr(profile, "label", "") or source_name or value)
    return value


def _handle(context: Any, title: str, callback: Callable[[], None]) -> None:
    try:
        callback()
    except (KeyError, OSError, RuntimeError, ValueError) as exc:
        context.dialogs.message(title, [str(exc)])


def _board_status_cache(context: Any) -> dict[str, dict[str, Any]]:
    runtime_state = getattr(context, "runtime_state", None)
    if not isinstance(runtime_state, dict):
        return {}
    cache = runtime_state.setdefault("board_status", {})
    if not isinstance(cache, dict):
        cache = {}
        runtime_state["board_status"] = cache
    return cache


def _cache_board_status(context: Any, board: dict[str, Any]) -> None:
    board_id = str(board.get("board_id") or "")
    if not board_id:
        return
    values = {
        key: deepcopy(board.get(key))
        for key in (
            "serial",
            "available",
            "adb_checked",
            "adb_state",
            "state",
            "probe",
            "error",
            "android_serial",
            "build_id",
            "build_incremental",
            "build_fingerprint",
        )
    }
    values["checked_at"] = time.time()
    _board_status_cache(context)[board_id] = values


def runner_preview(context: Any) -> str:
    state = model.state(context.config)
    runner = model.active_runner(context.config)
    active = str(state.get("active_runner") or "none")
    remote = model.runner_remote(runner) or "not configured"
    return f"Runner profiles: {_names(context, 'runners')}\nActive: {active} ({remote})"


def board_profiles_preview(context: Any) -> str:
    return "Board profiles: " + _names(context, "board_profiles")


def test_profiles_preview(context: Any) -> str:
    return "Test profiles: " + _names(context, "test_profiles")


def product_profiles_preview(context: Any) -> str:
    return "Product profiles: " + _names(context, "product_profiles")


def runs_preview(context: Any) -> str:
    state = model.state(context.config)
    return f"Runs: {_names(context, 'runs')}\nActive: {state.get('active_run') or 'none'}"


def active_run_preview(context: Any) -> str:
    run = model.active_run(context.config)
    if run is None:
        return "No active test run"
    return (
        f"Run: {run['name']}\nRunner: {run.get('runner_profile')}\nBoards: {run.get('board_profile')}\n"
        f"Tests: {run.get('test_profile')}\nProduct: {run.get('product_profile')}"
    )


def configured_run_available(context: Any) -> tuple[bool, str]:
    run = model.active_run(context.config)
    if run is None:
        return False, "no active test run is configured"
    try:
        runner, _board, _test, _product = model.resolve_run(context.config, run)
    except ValueError as exc:
        return False, str(exc)
    if not model.runner_remote(runner):
        return False, "test runner SSH is not configured"
    return True, ""


def running_run_available(context: Any) -> tuple[bool, str]:
    enabled, reason = configured_run_available(context)
    if not enabled:
        return enabled, reason
    run = model.active_run(context.config)
    if run is None or run.get("last_status") not in {"starting", "running"}:
        return False, "the active test run is not marked as running"
    return True, ""


class RunnerConfigurationView:
    fields = (
        ("name", "Profile name"),
        ("label", "Display label"),
        ("user", "SSH user"),
        ("host", "SSH host"),
        ("workspace_dir", "Workspace dir"),
    )
    field_hints = {
        "name": "Unique local test runner profile id. Renaming it preserves references from test runs.",
        "label": "Display label shown for this test runner in the client.",
        "user": "SSH user for the remote test runner.",
        "host": "SSH host name or IP address of the remote test runner.",
        "workspace_dir": "Base directory on the test runner for prepared artifacts, run state, and test results.",
    }
    field_rows = (0, 1, 4, 5, 8)

    def __init__(self) -> None:
        self.focus = "runners"
        self.runner_index = 0
        self.selected = 0
        self.editing_key = ""
        self.editing_value = ""
        self.editing_cursor = 0

    def on_enter(self, context: Any) -> None:
        runners = model.records(context.config, "runners")
        active = str(model.state(context.config).get("active_runner") or "")
        self.runner_index = next(
            (index for index, runner in enumerate(runners) if runner.get("id") == active),
            0,
        )

    def _selected_runner(self, context: Any) -> dict[str, Any] | None:
        runners = model.records(context.config, "runners")
        if not runners:
            return None
        self.runner_index = min(self.runner_index, len(runners) - 1)
        return runners[self.runner_index]

    def render(self, ui: Any, context: Any) -> None:
        state = model.state(context.config)
        runners = model.records(context.config, "runners")
        runner = self._selected_runner(context)
        active = str(state.get("active_runner") or "none")
        ui.text(0, 0, f"Active: {_record_name(context, 'runners', active) or 'none'}")
        ui.text(1, 0, f"Focus: {'test runner list' if self.focus == 'runners' else 'fields'}", style="accent")
        panel_top = 2
        panel_height = max(2, ui.height - 3)
        ui.box(panel_top, 0, panel_height, max(2, ui.width), "Test runners")
        ui.text(3, 2, "A Name              User@Host", style="accent")
        if not runners:
            ui.text(4, 2, "No test runners. Press 'a' to add one.", style="warning")
        minimum_detail_rows = 11
        visible_runners = max(1, min(max(1, len(runners)), panel_height - minimum_detail_rows))
        first_runner = min(
            max(0, self.runner_index - visible_runners + 1),
            max(0, len(runners) - visible_runners),
        )
        for offset, item in enumerate(runners[first_runner : first_runner + visible_runners]):
            index = first_runner + offset
            name = str(item.get("name") or "")
            is_active = str(item.get("id") or "") == active
            marker = "*" if is_active else " "
            remote = model.runner_remote(item)
            is_selected = self.focus == "runners" and index == self.runner_index
            style = "selected-active" if is_selected and is_active else "selected" if is_selected else "active" if is_active else "normal"
            suffix = "  ACTIVE" if is_active else ""
            ui.text(4 + offset, 2, f"{marker} {name[:17]:17} {remote}{suffix}", style=style)
        detail_row = 4 + visible_runners + 1
        if len(runners) > visible_runners:
            ui.text(detail_row, 2, f"Runner {self.runner_index + 1} of {len(runners)}", style="warning")
            detail_row += 1
        if runner is None:
            ui.text(detail_row, 2, "Selected test runner: <none>", style="warning")
            ui.text(max(0, ui.height - 1), 0, "a: add | q/Esc: back", style="accent")
            return
        ui.text(detail_row, 2, "PROFILE", style="accent")
        ui.text(detail_row + 3, 2, "SSH", style="accent")
        ui.text(detail_row + 7, 2, "REMOTE WORKSPACE", style="accent")
        for index, ((key, label), row) in enumerate(zip(self.fields, self.field_rows)):
            editing = key == self.editing_key
            value = self.editing_value if editing else str(runner.get(key) or "")
            row_model = config_field_api.host_field_row_model(
                label=label,
                key=key,
                profile=runner,
                value=value,
                enabled=True,
                selected=self.focus == "fields" and index == self.selected,
                editing=editing,
            )
            draw_row = detail_row + row + 1
            ui.text(
                draw_row,
                2,
                str(row_model["text"]).ljust(max(0, ui.width - 4)),
                style=str(row_model["state"]),
            )
            if editing:
                ui.cursor(draw_row, min(max(0, ui.width - 2), 22 + self.editing_cursor))
        if self.editing_key:
            hint = "Enter: save | Esc: cancel | Left/Right/Home/End: move cursor"
        elif self.focus == "fields":
            hint = self.field_hints[self.fields[self.selected][0]]
        else:
            hint = "Select a test runner profile or press 'a' to add one."
        ui.text(panel_top + panel_height - 2, 2, hint, style="accent")
        ui.text(
            max(0, ui.height - 1),
            0,
            "Left/Right: focus | Up/Down: select | Enter: edit | a: add | d: delete | s: set active | q/Esc: back",
            style="accent",
        )

    def handle_event(self, event: Any, context: Any) -> str | None:
        if self.editing_key:
            edit = context.inline_edit(event, self.editing_value, self.editing_cursor)
            if edit.action == "save":
                self._apply_edited_value(context)
            elif edit.action == "cancel":
                self._clear_edit()
            elif edit.action == "edit":
                self.editing_value = edit.value
                self.editing_cursor = edit.cursor
            return "handled"

        runners = model.records(context.config, "runners")
        if event.code == curses.KEY_LEFT or ui_input_api.key_code_matches(event.code, "h"):
            self.focus = "runners"
            return "handled"
        if event.code == curses.KEY_RIGHT or ui_input_api.key_code_matches(event.code, "l"):
            if runners:
                self.focus = "fields"
            return "handled"
        if event.code == 9:
            self.focus = "fields" if self.focus == "runners" and runners else "runners"
            return "handled"
        if event.code == curses.KEY_UP or ui_input_api.key_code_matches(event.code, "k"):
            if self.focus == "runners" and runners:
                self.runner_index = (self.runner_index - 1) % len(runners)
            else:
                self.selected = (self.selected - 1) % len(self.fields)
            return "handled"
        if event.code == curses.KEY_DOWN or ui_input_api.key_code_matches(event.code, "j"):
            if self.focus == "runners" and runners:
                self.runner_index = (self.runner_index + 1) % len(runners)
            else:
                self.selected = (self.selected + 1) % len(self.fields)
            return "handled"
        if ui_input_api.key_code_matches(event.code, "a"):
            self._add_runner(context)
            return "handled"
        if ui_input_api.key_code_matches(event.code, "d") and self.focus == "runners":
            self._delete_runner(context)
            return "handled"
        if ui_input_api.key_code_matches(event.code, "s") and self.focus == "runners":
            runner = self._selected_runner(context)
            if runner is not None:
                _replace_reference(
                    context,
                    "cts_vts.active_runner",
                    config_entities.SELECTION,
                    "cts_vts.runner",
                    [model.record_id(runner)],
                )
            return "handled"
        if event.code not in (curses.KEY_ENTER, 10, 13):
            return None
        if self.focus == "runners":
            runner = self._selected_runner(context)
            if runner is not None:
                _replace_reference(
                    context,
                    "cts_vts.active_runner",
                    config_entities.SELECTION,
                    "cts_vts.runner",
                    [model.record_id(runner)],
                )
                self.focus = "fields"
            return "handled"

        key, _label = self.fields[self.selected]
        runner = self._selected_runner(context)
        if runner is None:
            return "handled"
        self.editing_key = key
        self.editing_value = str(runner.get(key) or "")
        self.editing_cursor = len(self.editing_value)
        return "handled"

    def _apply_edited_value(self, context: Any) -> None:
        runner = self._selected_runner(context)
        if runner is None:
            self._clear_edit()
            return
        key = self.editing_key
        value = self.editing_value.strip()
        if key == "name":
            try:
                value = model.safe_name(value)
            except ValueError as exc:
                context.dialogs.message("Test runner configuration", [str(exc)])
                return
        if key == "workspace_dir" and (not value or value.startswith("~")):
            context.dialogs.message(
                "Test runner configuration",
                ["Runner workspace must be an absolute path or a home-relative path without '~'."],
            )
            return
        old_name = str(runner.get("name") or "")
        if key == "name" and value != old_name:
            if model.find(context.config, "runners", value) is not None:
                context.dialogs.message("Test runner configuration", [f"Runner profile already exists: {value}"])
                return
        _update_entity(context, "cts_vts.runner", "runners", runner, {key: value})
        self._clear_edit()

    def _clear_edit(self) -> None:
        self.editing_key = ""
        self.editing_value = ""
        self.editing_cursor = 0

    def _add_runner(self, context: Any) -> None:
        name = context.dialogs.prompt("Profile name", "test-runner")
        if context.dialogs.prompt_cancelled:
            return
        try:
            name = model.safe_name(name)
        except ValueError as exc:
            context.dialogs.message("Test runner configuration", [str(exc)])
            return
        if model.find(context.config, "runners", name) is not None:
            context.dialogs.message("Test runner configuration", [f"Runner profile already exists: {name}"])
            return
        label = context.dialogs.prompt("Display label", name)
        if context.dialogs.prompt_cancelled:
            return
        runner = {
            "name": name,
            "label": label.strip() or name,
            "user": "",
            "host": "",
            "workspace_dir": model.DEFAULT_RUNNER_WORKSPACE,
        }
        _create_entity(
            context,
            "cts_vts.runner",
            "runners",
            runner,
        )
        self.runner_index = len(model.records(context.config, "runners")) - 1
        self.focus = "fields"

    def _delete_runner(self, context: Any) -> None:
        runner = self._selected_runner(context)
        if runner is None:
            return
        name = str(runner.get("name") or "")
        if not _delete_entity(
            context,
            kind="cts_vts.runner",
            record=runner,
            title="Delete test runner",
            question=f"Delete test runner profile {name}?",
            warning="This removes the saved runner configuration.",
        ):
            return
        self.runner_index = max(0, self.runner_index - 1)


def create_runner_configuration(_context: Any) -> RunnerConfigurationView:
    return RunnerConfigurationView()


class BoardProfileConfigurationView:
    device_fields = (
        ("serial", "ADB serial override"),
    )
    field_hints = {
        "name": "Unique local board profile id. Renaming it preserves references from test runs.",
        "serial": "Optional static ADB serial. When empty, the selected product type resolves the endpoint.",
    }

    def __init__(self) -> None:
        self.focus = "profiles"
        self.profile_index = 0
        self.board_index = 0
        self.field_index = 0
        self.editing_key = ""
        self.editing_value = ""
        self.editing_cursor = 0

    def on_enter(self, context: Any) -> None:
        profiles = model.records(context.config, "board_profiles")
        self.profile_index = min(self.profile_index, max(0, len(profiles) - 1))

    def _selected_profile(self, context: Any) -> dict[str, Any] | None:
        profiles = model.records(context.config, "board_profiles")
        if not profiles:
            return None
        self.profile_index = min(self.profile_index, len(profiles) - 1)
        return profiles[self.profile_index]

    def _selected_board(self, context: Any) -> Any | None:
        boards = list(context.boards)
        if not boards:
            return None
        self.board_index = min(self.board_index, len(boards) - 1)
        return boards[self.board_index]

    @staticmethod
    def _device(profile: dict[str, Any] | None, board_id: str) -> dict[str, Any] | None:
        if profile is None:
            return None
        return next(
            (device for device in profile.get("devices", []) if str(device.get("board_id") or "") == board_id),
            None,
        )

    def _fields(self, device: dict[str, Any] | None) -> tuple[tuple[str, str], ...]:
        return (("name", "Profile name"),) + (self.device_fields if device is not None else ())

    def render(self, ui: Any, context: Any) -> None:
        profiles = model.records(context.config, "board_profiles")
        boards = list(context.boards)
        profile = self._selected_profile(context)
        selected_board = self._selected_board(context)
        selected_board_id = str(getattr(selected_board, "board_id", ""))
        device = self._device(profile, selected_board_id)
        fields = self._fields(device)
        self.field_index = min(self.field_index, len(fields) - 1)

        ui.text(0, 0, f"Profiles: {len(profiles)} | Available board hosts: {len(boards)}")
        ui.text(1, 0, f"Focus: {self.focus}", style="accent")
        panel_top = 2
        panel_height = max(2, ui.height - 3)
        panel_bottom = panel_top + panel_height - 2
        ui.box(panel_top, 0, panel_height, max(2, ui.width), "Board profiles")
        ui.text(3, 2, "Name                  Boards", style="accent")

        visible_profiles = max(1, min(max(1, len(profiles)), 4))
        first_profile = min(
            max(0, self.profile_index - visible_profiles + 1),
            max(0, len(profiles) - visible_profiles),
        )
        for offset, item in enumerate(profiles[first_profile : first_profile + visible_profiles]):
            index = first_profile + offset
            devices = item.get("devices", [])
            style = "selected" if self.focus == "profiles" and index == self.profile_index else "normal"
            ui.text(4 + offset, 2, f"{str(item.get('name') or '')[:21]:21} {len(devices)}", style=style)
        if not profiles:
            ui.text(4, 2, "No board profiles. Press 'a' to add one.", style="warning")
            ui.text(panel_bottom, 2, "Create a board profile before selecting target boards.", style="accent")
            self._render_footer(ui)
            return

        detail_row = 4 + visible_profiles + 1
        ui.text(detail_row, 2, "PROFILE", style="accent")
        self._render_field(ui, detail_row + 1, profile, None, fields, 0)

        boards_heading = detail_row + 3
        ui.text(boards_heading, 2, "BOARDS", style="accent")
        board_row = boards_heading + 1
        visible_boards = max(1, min(max(1, len(boards)), max(1, panel_bottom - board_row - 6)))
        first_board = min(
            max(0, self.board_index - visible_boards + 1),
            max(0, len(boards) - visible_boards),
        )
        for offset, board in enumerate(boards[first_board : first_board + visible_boards]):
            index = first_board + offset
            configured = self._device(profile, board.board_id)
            included = configured is not None
            marker = "[x]" if included else "[ ]"
            serial = str(configured.get("serial") or "") if configured else ""
            style = (
                "selected-active"
                if self.focus == "boards" and index == self.board_index and included
                else "selected"
                if self.focus == "boards" and index == self.board_index
                else "active"
                if included
                else "normal"
            )
            ui.text(board_row + offset, 2, f"{marker} {board.board_id[:18]:18} {board.remote:24} {serial}", style=style)
        if not boards:
            ui.text(board_row, 2, "No board hosts are configured in the client.", style="warning")

        device_heading = board_row + visible_boards + 1
        if selected_board is not None:
            ui.text(device_heading, 2, f"DEVICE: {selected_board.board_id}", style="accent")
        if device is not None:
            for index in range(1, len(fields)):
                self._render_field(ui, device_heading + index, profile, device, fields, index)
        elif selected_board is not None:
            ui.text(device_heading + 1, 2, "Press Enter or Space to include this board.", style="warning")

        if self.editing_key:
            hint = "Enter: save | Esc: cancel | Left/Right/Home/End: move cursor"
        elif self.focus == "fields":
            hint = self.field_hints[fields[self.field_index][0]]
        elif self.focus == "boards":
            hint = (
                "Enter configures the selected board. Space removes it from this profile."
                if device is not None
                else "Enter or Space includes the selected board in this profile."
            )
        else:
            hint = "Select a board profile or press 'a' to add one."
        ui.text(panel_bottom, 2, hint, style="accent")
        self._render_footer(ui)

    def _render_field(
        self,
        ui: Any,
        row: int,
        profile: dict[str, Any],
        device: dict[str, Any] | None,
        fields: tuple[tuple[str, str], ...],
        index: int,
    ) -> None:
        key, label = fields[index]
        owner = profile if key == "name" else device or {}
        editing = key == self.editing_key
        value = self.editing_value if editing else str(owner.get(key) or "")
        row_model = config_field_api.host_field_row_model(
            label=label,
            key=key,
            profile=owner,
            value=value,
            enabled=True,
            selected=self.focus == "fields" and index == self.field_index,
            editing=editing,
        )
        ui.text(row, 2, str(row_model["text"]).ljust(max(0, ui.width - 4)), style=str(row_model["state"]))
        if editing:
            ui.cursor(row, min(max(0, ui.width - 2), 22 + self.editing_cursor))

    @staticmethod
    def _render_footer(ui: Any) -> None:
        ui.text(
            max(0, ui.height - 1),
            0,
            "Left/Right: focus | Up/Down: select | Enter: configure/edit | Space: include/exclude | a: add | d: delete | q/Esc: back",
            style="accent",
        )

    def handle_event(self, event: Any, context: Any) -> str | None:
        if self.editing_key:
            edit = context.inline_edit(event, self.editing_value, self.editing_cursor)
            if edit.action == "save":
                self._apply_edited_value(context)
            elif edit.action == "cancel":
                self._clear_edit()
            elif edit.action == "edit":
                self.editing_value = edit.value
                self.editing_cursor = edit.cursor
            return "handled"

        profiles = model.records(context.config, "board_profiles")
        boards = list(context.boards)
        profile = self._selected_profile(context)
        board = self._selected_board(context)
        device = self._device(profile, str(getattr(board, "board_id", "")))
        fields = self._fields(device)
        if event.code == 27:
            if self.focus == "fields":
                self.focus = "boards" if boards else "profiles"
                return "handled"
            if self.focus == "boards":
                self.focus = "profiles"
                return "handled"
            return None
        if event.code == curses.KEY_LEFT or ui_input_api.key_code_matches(event.code, "h"):
            self.focus = {"fields": "boards", "boards": "profiles"}.get(self.focus, "profiles")
            return "handled"
        if (
            event.code == curses.KEY_RIGHT
            or ui_input_api.key_code_matches(event.code, "l")
            or event.code == 9
        ):
            if self.focus == "profiles" and boards:
                self.focus = "boards"
            elif self.focus == "boards" and device is not None:
                self.focus = "fields"
                self.field_index = 1
            return "handled"
        if event.code == curses.KEY_UP or ui_input_api.key_code_matches(event.code, "k"):
            if self.focus == "profiles" and profiles:
                self.profile_index = (self.profile_index - 1) % len(profiles)
            elif self.focus == "boards" and boards:
                self.board_index = (self.board_index - 1) % len(boards)
            else:
                self.field_index = (self.field_index - 1) % len(fields)
            return "handled"
        if event.code == curses.KEY_DOWN or ui_input_api.key_code_matches(event.code, "j"):
            if self.focus == "profiles" and profiles:
                self.profile_index = (self.profile_index + 1) % len(profiles)
            elif self.focus == "boards" and boards:
                self.board_index = (self.board_index + 1) % len(boards)
            else:
                self.field_index = (self.field_index + 1) % len(fields)
            return "handled"
        if ui_input_api.key_code_matches(event.code, "a"):
            self._add_profile(context)
            return "handled"
        if ui_input_api.key_code_matches(event.code, "d") and self.focus == "profiles":
            self._delete_profile(context)
            return "handled"
        if self.focus == "boards" and event.code == ord(" "):
            self._toggle_board(context)
            return "handled"
        if self.focus == "boards" and event.code in (curses.KEY_ENTER, 10, 13):
            if device is None:
                self._toggle_board(context)
            self.focus = "fields"
            self.field_index = 1
            return "handled"
        if event.code not in (curses.KEY_ENTER, 10, 13):
            return None
        if self.focus == "profiles":
            self.focus = "boards" if boards else "fields"
            return "handled"
        if profile is None:
            return "handled"
        key, _label = fields[self.field_index]
        owner = profile if key == "name" else device
        if owner is None:
            return "handled"
        self.editing_key = key
        self.editing_value = str(owner.get(key) or "")
        self.editing_cursor = len(self.editing_value)
        return "handled"

    def _apply_edited_value(self, context: Any) -> None:
        profile = self._selected_profile(context)
        board = self._selected_board(context)
        if profile is None:
            self._clear_edit()
            return
        key = self.editing_key
        value = self.editing_value.strip()
        if key == "name":
            try:
                value = model.safe_name(value)
            except ValueError as exc:
                context.dialogs.message("Board profile configuration", [str(exc)])
                return
            old_name = str(profile.get("name") or "")
            if value != old_name:
                if model.find(context.config, "board_profiles", value) is not None:
                    context.dialogs.message("Board profile configuration", [f"Board profile already exists: {value}"])
                    return
            _update_entity(
                context,
                "cts_vts.board_profile",
                "board_profiles",
                profile,
                {"name": value},
            )
        else:
            device = self._device(profile, str(getattr(board, "board_id", "")))
            if device is None:
                self._clear_edit()
                return
            _update_entity(
                context,
                "cts_vts.board_profile",
                "board_profiles",
                profile,
                {
                    "device_update": {
                        "board_id": str(device.get("board_id") or ""),
                        "field": key,
                        "value": value,
                    }
                },
            )
        self._clear_edit()

    def _clear_edit(self) -> None:
        self.editing_key = ""
        self.editing_value = ""
        self.editing_cursor = 0

    def _add_profile(self, context: Any) -> None:
        name = context.dialogs.prompt("Board profile name", "boards")
        if context.dialogs.prompt_cancelled:
            return
        try:
            name = model.safe_name(name)
        except ValueError as exc:
            context.dialogs.message("Board profile configuration", [str(exc)])
            return
        if model.find(context.config, "board_profiles", name) is not None:
            context.dialogs.message("Board profile configuration", [f"Board profile already exists: {name}"])
            return
        _create_entity(
            context,
            "cts_vts.board_profile",
            "board_profiles",
            {"name": name, "devices": []},
        )
        self.profile_index = len(model.records(context.config, "board_profiles")) - 1
        self.focus = "boards" if context.boards else "fields"

    def _delete_profile(self, context: Any) -> None:
        profile = self._selected_profile(context)
        if profile is None:
            return
        name = str(profile.get("name") or "")
        if not _delete_entity(
            context,
            kind="cts_vts.board_profile",
            record=profile,
            title="Delete board profile",
            question=f"Delete board profile {name}?",
            warning="This removes the saved board selection and recovery commands.",
        ):
            return
        self.profile_index = max(0, self.profile_index - 1)

    def _toggle_board(self, context: Any) -> None:
        profile = self._selected_profile(context)
        board = self._selected_board(context)
        if profile is None or board is None:
            return
        current = self._device(profile, board.board_id)
        target_ids = [
            str(device.get("board_id") or "")
            for device in profile.get("devices", [])
            if isinstance(device, dict) and str(device.get("board_id") or "")
        ]
        if current is not None:
            target_ids.remove(board.board_id)
            self.field_index = 0
        else:
            target_ids.append(board.board_id)
        _replace_reference(
            context,
            "cts_vts.board_profile.devices",
            EntityRef("cts_vts.board_profile", model.record_id(profile)),
            "board",
            target_ids,
        )


def create_board_profile_configuration(_context: Any) -> BoardProfileConfigurationView:
    return BoardProfileConfigurationView()


class TestProfileConfigurationView:
    fields = (
        ("name", "Profile name"),
        ("suites", "Suites"),
        ("cts_revision", "CTS revision"),
        ("extra_args", "Tradefed arguments"),
        ("skipped_modules", "Excluded modules"),
        ("adb_loss_timeout_minutes", "ADB loss timeout, minutes"),
        ("no_progress_runs", "Maximum runs before reboot"),
        ("max_reboots", "Maximum reboots before reflash"),
        ("max_reflashes", "Maximum reflashes before module skip"),
        ("max_skip_cycles", "Maximum module skips before failure"),
    )
    field_label_width = max(len(label) + 2 for _key, label in fields)
    field_rows = (0, 3, 4, 7, 8, 11, 12, 13, 14, 15)
    choice_fields = frozenset({"suites", "cts_revision"})
    field_hints = {
        "name": "Unique test profile id. Renaming it preserves references from test runs.",
        "suites": "Compatibility suites to execute. Enter opens the suite selector.",
        "cts_revision": "ARM CTS package revision. Enter loads available Android CTS revisions.",
        "extra_args": "Additional Tradefed arguments. Serial, sharding, and retry options are managed by the plugin.",
        "skipped_modules": "Comma-separated modules excluded before the first run.",
        "adb_loss_timeout_minutes": "Minutes to wait for ADB and Android boot completion before the board is considered unavailable.",
        "no_progress_runs": "Consecutive runs without additional completed modules before all boards are rebooted.",
        "max_reboots": "All-board reboot attempts before recovery escalates to reflashing all boards.",
        "max_reflashes": "All-board reflash attempts before the blocking module is automatically excluded.",
        "max_skip_cycles": "Automatic blocking-module exclusions before the test run stops with an error.",
    }

    def __init__(self) -> None:
        self.focus = "profiles"
        self.profile_index = 0
        self.selected = 0
        self.editing_key = ""
        self.editing_value = ""
        self.editing_cursor = 0
        self.selector_key = ""
        self.selector_index = 0
        self.selector_choices: list[str] = []
        self.cts_downloads: dict[str, str] = {}

    def on_enter(self, context: Any) -> None:
        profiles = model.records(context.config, "test_profiles")
        self.profile_index = min(self.profile_index, max(0, len(profiles) - 1))

    def _selected_profile(self, context: Any) -> dict[str, Any] | None:
        profiles = model.records(context.config, "test_profiles")
        if not profiles:
            return None
        self.profile_index = min(self.profile_index, len(profiles) - 1)
        return profiles[self.profile_index]

    @staticmethod
    def _field_value(profile: dict[str, Any], key: str) -> str:
        value = profile.get(key)
        if key in {"suites", "skipped_modules"}:
            return ",".join(str(item) for item in value or [])
        if key == "extra_args":
            return shlex.join(str(item) for item in value or [])
        return str(value if value is not None else "")

    def render(self, ui: Any, context: Any) -> None:
        if self.selector_key:
            self._render_selector(ui, context)
            return
        profiles = model.records(context.config, "test_profiles")
        profile = self._selected_profile(context)
        ui.text(0, 0, f"Test profiles: {len(profiles)}")
        ui.text(1, 0, f"Focus: {'test profile list' if self.focus == 'profiles' else 'fields'}", style="accent")
        panel_top = 2
        panel_height = max(2, ui.height - 3)
        ui.box(panel_top, 0, panel_height, max(2, ui.width), "Test profiles")
        ui.text(3, 2, "Name                    Suites       CTS revision", style="accent")
        if not profiles:
            ui.text(4, 2, "No test profiles. Press 'a' to add one.", style="warning")
        minimum_detail_rows = 19
        visible_profiles = max(1, min(max(1, len(profiles)), panel_height - minimum_detail_rows))
        first_profile = min(
            max(0, self.profile_index - visible_profiles + 1),
            max(0, len(profiles) - visible_profiles),
        )
        for offset, item in enumerate(profiles[first_profile : first_profile + visible_profiles]):
            index = first_profile + offset
            selected = self.focus == "profiles" and index == self.profile_index
            suites = ",".join(str(value) for value in item.get("suites", []))
            ui.text(
                4 + offset,
                2,
                f"{str(item.get('name') or '')[:22]:22}  {suites[:11]:11}  {item.get('cts_revision') or '-'}",
                style="selected" if selected else "normal",
            )
        detail_row = 4 + visible_profiles + 1
        if profile is None:
            ui.text(detail_row, 2, "Selected test profile: <none>", style="warning")
            ui.text(max(0, ui.height - 1), 0, "a: add | q/Esc: back", style="accent")
            return
        ui.text(detail_row, 2, "PROFILE", style="accent")
        ui.text(detail_row + 3, 2, "SUITES", style="accent")
        ui.text(detail_row + 7, 2, "TRADEFED", style="accent")
        ui.text(detail_row + 11, 2, "RECOVERY", style="accent")
        suites = {str(value) for value in profile.get("suites", [])}
        for index, ((key, label), field_row) in enumerate(zip(self.fields, self.field_rows)):
            editing = key == self.editing_key
            value = self.editing_value if editing else self._field_value(profile, key)
            enabled = key != "cts_revision" or "cts" in suites
            row_model = config_field_api.host_field_row_model(
                label=label,
                key=key,
                profile=profile,
                value=value,
                enabled=enabled,
                selected=self.focus == "fields" and index == self.selected,
                editing=editing,
                label_width=self.field_label_width,
            )
            draw_row = detail_row + field_row + 1
            ui.text(
                draw_row,
                2,
                str(row_model["text"]).ljust(max(0, ui.width - 4)),
                style=str(row_model["state"]),
            )
            if editing:
                ui.cursor(
                    draw_row,
                    min(max(0, ui.width - 2), 2 + self.field_label_width + self.editing_cursor),
                )
        if self.editing_key:
            hint = "Enter: save | Esc: cancel | Left/Right/Home/End: move cursor"
        elif self.focus == "fields":
            hint = self.field_hints[self.fields[self.selected][0]]
        else:
            hint = "Select a test profile or press 'a' to add one."
        ui.text(panel_top + panel_height - 2, 2, hint, style="accent")
        ui.text(
            max(0, ui.height - 1),
            0,
            "Left/Right: focus | Up/Down: select | Enter: edit/select | a: add | d: delete | q/Esc: back",
            style="accent",
        )

    def handle_event(self, event: Any, context: Any) -> str | None:
        if self.selector_key:
            return self._handle_selector(event, context)
        if self.editing_key:
            edit = context.inline_edit(event, self.editing_value, self.editing_cursor)
            if edit.action == "save":
                self._apply_edited_value(context)
            elif edit.action == "cancel":
                self._clear_edit()
            elif edit.action == "edit":
                self.editing_value = edit.value
                self.editing_cursor = edit.cursor
            return "handled"

        profiles = model.records(context.config, "test_profiles")
        if event.code == curses.KEY_LEFT or ui_input_api.key_code_matches(event.code, "h"):
            self.focus = "profiles"
            return "handled"
        if event.code == curses.KEY_RIGHT or ui_input_api.key_code_matches(event.code, "l"):
            if profiles:
                self.focus = "fields"
            return "handled"
        if event.code == 9:
            self.focus = "fields" if self.focus == "profiles" and profiles else "profiles"
            return "handled"
        if event.code == curses.KEY_UP or ui_input_api.key_code_matches(event.code, "k"):
            if self.focus == "profiles" and profiles:
                self.profile_index = (self.profile_index - 1) % len(profiles)
            else:
                self.selected = (self.selected - 1) % len(self.fields)
            return "handled"
        if event.code == curses.KEY_DOWN or ui_input_api.key_code_matches(event.code, "j"):
            if self.focus == "profiles" and profiles:
                self.profile_index = (self.profile_index + 1) % len(profiles)
            else:
                self.selected = (self.selected + 1) % len(self.fields)
            return "handled"
        if ui_input_api.key_code_matches(event.code, "a"):
            self._add_profile(context)
            return "handled"
        if ui_input_api.key_code_matches(event.code, "d") and self.focus == "profiles":
            self._delete_profile(context)
            return "handled"
        if event.code not in (curses.KEY_ENTER, 10, 13):
            return None
        if self.focus == "profiles":
            if self._selected_profile(context) is not None:
                self.focus = "fields"
            return "handled"

        key, _label = self.fields[self.selected]
        profile = self._selected_profile(context)
        if profile is None:
            return "handled"
        if key in self.choice_fields:
            self._open_selector(context, profile, key)
            return "handled"
        self.editing_key = key
        self.editing_value = self._field_value(profile, key)
        self.editing_cursor = len(self.editing_value)
        return "handled"

    def _selector_choices(self, profile: dict[str, Any], key: str) -> list[str]:
        if key == "suites":
            return ["vts", "cts", "cts,vts"]
        if key == "cts_revision":
            if "cts" not in profile.get("suites", []):
                raise ValueError("select the CTS suite before choosing a CTS revision")
            self.cts_downloads = downloads.fetch_cts_downloads()
            if not self.cts_downloads:
                raise RuntimeError("the Android CTS downloads page returned no ARM packages")
            return list(self.cts_downloads)
        return []

    def _open_selector(self, context: Any, profile: dict[str, Any], key: str) -> None:
        try:
            choices = self._selector_choices(profile, key)
        except (KeyError, OSError, RuntimeError, ValueError) as exc:
            context.dialogs.message("Test profile configuration", [str(exc)])
            return
        self.selector_key = key
        self.selector_choices = choices
        current = self._field_value(profile, key)
        self.selector_index = choices.index(current) if current in choices else 0

    def _render_selector(self, ui: Any, context: Any) -> None:
        profile = self._selected_profile(context)
        if profile is None:
            self._clear_selector()
            return
        label = dict(self.fields)[self.selector_key]
        ui.text(0, 0, f"Test profile: {profile.get('name') or '<not set>'}")
        ui.text(1, 0, f"Select {label.lower()}", style="accent")
        panel_top = 2
        panel_height = max(2, ui.height - 3)
        ui.box(panel_top, 0, panel_height, max(2, ui.width), label)
        visible = max(1, panel_height - 3)
        first = min(
            max(0, self.selector_index - visible + 1),
            max(0, len(self.selector_choices) - visible),
        )
        for offset, choice in enumerate(self.selector_choices[first : first + visible]):
            index = first + offset
            marker = "*" if index == self.selector_index else " "
            ui.text(3 + offset, 2, f"{marker} {choice}", style="selected" if index == self.selector_index else "normal")
        ui.text(max(0, ui.height - 1), 0, "Up/Down: select | Enter: select | q/Esc: cancel", style="accent")

    def _handle_selector(self, event: Any, context: Any) -> str:
        profile = self._selected_profile(context)
        if profile is None:
            self._clear_selector()
            return "handled"
        if event.code == 27 or ui_input_api.key_code_matches(event.code, "q"):
            self._clear_selector()
            return "handled"
        if event.code == curses.KEY_UP or ui_input_api.key_code_matches(event.code, "k"):
            self.selector_index = (self.selector_index - 1) % len(self.selector_choices)
            return "handled"
        if event.code == curses.KEY_DOWN or ui_input_api.key_code_matches(event.code, "j"):
            self.selector_index = (self.selector_index + 1) % len(self.selector_choices)
            return "handled"
        if event.code not in (curses.KEY_ENTER, 10, 13):
            return "handled"
        key = self.selector_key
        choice = self.selector_choices[self.selector_index]
        if key == "suites":
            changes = {"suites": model.parse_suites(choice)}
        else:
            changes = {
                "cts_revision": choice,
                "cts_url": self.cts_downloads[choice],
            }
        _update_entity(
            context,
            "cts_vts.test_profile",
            "test_profiles",
            profile,
            changes,
        )
        self._clear_selector()
        return "handled"

    def _clear_selector(self) -> None:
        self.selector_key = ""
        self.selector_index = 0
        self.selector_choices = []
        self.cts_downloads = {}

    def _apply_edited_value(self, context: Any) -> None:
        profile = self._selected_profile(context)
        if profile is None:
            self._clear_edit()
            return
        key = self.editing_key
        value = self.editing_value.strip()
        try:
            if key == "name":
                parsed: Any = model.safe_name(value)
            elif key == "extra_args":
                parsed = model.validate_tradefed_args(shlex.split(value))
            elif key == "skipped_modules":
                parsed = model.csv_values(value)
            elif key in {"adb_loss_timeout_minutes", "no_progress_runs"}:
                parsed = model.positive_int(value, dict(self.fields)[key], int(profile.get(key) or 1))
            else:
                parsed = model.nonnegative_int(value, dict(self.fields)[key], int(profile.get(key) or 0))
        except (TypeError, ValueError) as exc:
            context.dialogs.message("Test profile configuration", [str(exc)])
            return
        old_name = str(profile.get("name") or "")
        if key == "name" and parsed != old_name:
            if model.find(context.config, "test_profiles", str(parsed)) is not None:
                context.dialogs.message("Test profile configuration", [f"Test profile already exists: {parsed}"])
                return
        _update_entity(
            context,
            "cts_vts.test_profile",
            "test_profiles",
            profile,
            {key: parsed},
        )
        self._clear_edit()

    def _clear_edit(self) -> None:
        self.editing_key = ""
        self.editing_value = ""
        self.editing_cursor = 0

    def _add_profile(self, context: Any) -> None:
        name = context.dialogs.prompt("Profile name", "compatibility")
        if context.dialogs.prompt_cancelled:
            return
        try:
            name = model.safe_name(name)
        except ValueError as exc:
            context.dialogs.message("Test profile configuration", [str(exc)])
            return
        if model.find(context.config, "test_profiles", name) is not None:
            context.dialogs.message("Test profile configuration", [f"Test profile already exists: {name}"])
            return
        _create_entity(
            context,
            "cts_vts.test_profile",
            "test_profiles",
            {
                "name": name,
                "suites": ["vts"],
                "cts_revision": "",
                "cts_url": "",
                "extra_args": [],
                "skipped_modules": [],
                "adb_loss_timeout_minutes": 5,
                "no_progress_runs": 3,
                "max_reboots": 2,
                "max_reflashes": 1,
                "max_skip_cycles": 1,
            },
        )
        self.profile_index = len(model.records(context.config, "test_profiles")) - 1
        self.focus = "fields"

    def _delete_profile(self, context: Any) -> None:
        profile = self._selected_profile(context)
        if profile is None:
            return
        name = str(profile.get("name") or "")
        if not _delete_entity(
            context,
            kind="cts_vts.test_profile",
            record=profile,
            title="Delete test profile",
            question=f"Delete test profile {name}?",
            warning="This removes the saved suite and recovery configuration.",
        ):
            return
        self.profile_index = max(0, self.profile_index - 1)


def create_test_profile_configuration(_context: Any) -> TestProfileConfigurationView:
    return TestProfileConfigurationView()


class ProductProfileConfigurationView:
    fields = (
        ("name", "Profile name"),
        ("build_host", "Build host"),
        ("project", "Project"),
    )
    field_hints = {
        "name": "Unique product profile id. Renaming it preserves references from test runs.",
        "build_host": "Build host used to prepare the product and VTS artifacts. Enter opens the host selector.",
        "project": "Moulin project configuration used for this test product. Enter opens the project selector.",
    }
    field_rows = (0, 3, 4)
    choice_fields = frozenset({"build_host", "project"})

    def __init__(self) -> None:
        self.focus = "profiles"
        self.profile_index = 0
        self.selected = 0
        self.editing_key = ""
        self.editing_value = ""
        self.editing_cursor = 0
        self.selector_key = ""
        self.selector_index = 0
        self.selector_choices: list[str] = []
        self.selector_selected: set[str] = set()

    def on_enter(self, context: Any) -> None:
        profiles = model.records(context.config, "product_profiles")
        self.profile_index = min(self.profile_index, max(0, len(profiles) - 1))

    def _selected_profile(self, context: Any) -> dict[str, Any] | None:
        profiles = model.records(context.config, "product_profiles")
        if not profiles:
            return None
        self.profile_index = min(self.profile_index, len(profiles) - 1)
        return profiles[self.profile_index]

    @staticmethod
    def _field_value(context: Any, profile: dict[str, Any], key: str) -> str:
        value = profile.get(key)
        if key == "build_host":
            return _external_name(context.build_hosts, "host_id", value)
        if key == "project":
            return _external_name(context.projects, "project_id", value)
        return str(value or "")

    def render(self, ui: Any, context: Any) -> None:
        if self.selector_key:
            self._render_selector(ui, context)
            return
        profiles = model.records(context.config, "product_profiles")
        profile = self._selected_profile(context)
        ui.text(0, 0, f"Profiles: {len(profiles)} | Build hosts: {len(context.build_hosts)} | Projects: {len(context.projects)}")
        ui.text(1, 0, f"Focus: {'product profile list' if self.focus == 'profiles' else 'fields'}", style="accent")
        panel_top = 2
        panel_height = max(2, ui.height - 3)
        ui.box(panel_top, 0, panel_height, max(2, ui.width), "Product profiles")
        ui.text(3, 2, "Name                    Build host           Project", style="accent")
        if not profiles:
            ui.text(4, 2, "No product profiles. Press 'a' to add one.", style="warning")
        minimum_detail_rows = 9
        visible_profiles = max(1, min(max(1, len(profiles)), panel_height - minimum_detail_rows))
        first_profile = min(
            max(0, self.profile_index - visible_profiles + 1),
            max(0, len(profiles) - visible_profiles),
        )
        for offset, item in enumerate(profiles[first_profile : first_profile + visible_profiles]):
            index = first_profile + offset
            selected = self.focus == "profiles" and index == self.profile_index
            ui.text(
                4 + offset,
                2,
                f"{str(item.get('name') or '')[:22]:22}  "
                f"{_external_name(context.build_hosts, 'host_id', item.get('build_host'))[:18]:18}  "
                f"{_external_name(context.projects, 'project_id', item.get('project'))}",
                style="selected" if selected else "normal",
            )
        detail_row = 4 + visible_profiles + 1
        if profile is None:
            ui.text(detail_row, 2, "Selected product profile: <none>", style="warning")
            ui.text(max(0, ui.height - 1), 0, "a: add | q/Esc: back", style="accent")
            return
        ui.text(detail_row, 2, "PROFILE", style="accent")
        ui.text(detail_row + 3, 2, "PRODUCT SOURCE", style="accent")
        for index, ((key, label), row) in enumerate(zip(self.fields, self.field_rows)):
            editing = key == self.editing_key
            value = self.editing_value if editing else self._field_value(context, profile, key)
            row_model = config_field_api.host_field_row_model(
                label=label,
                key=key,
                profile=profile,
                value=value,
                enabled=True,
                selected=self.focus == "fields" and index == self.selected,
                editing=editing,
            )
            draw_row = detail_row + row + 1
            ui.text(
                draw_row,
                2,
                str(row_model["text"]).ljust(max(0, ui.width - 4)),
                style=str(row_model["state"]),
            )
            if editing:
                ui.cursor(draw_row, min(max(0, ui.width - 2), 22 + self.editing_cursor))
        if self.editing_key:
            hint = "Enter: save | Esc: cancel | Left/Right/Home/End: move cursor"
        elif self.focus == "fields":
            hint = self.field_hints[self.fields[self.selected][0]]
        else:
            hint = "Select a product profile or press 'a' to add one."
        ui.text(panel_top + panel_height - 2, 2, hint, style="accent")
        ui.text(
            max(0, ui.height - 1),
            0,
            "Left/Right: focus | Up/Down: select | Enter: edit/select | a: add | d: delete | q/Esc: back",
            style="accent",
        )

    def handle_event(self, event: Any, context: Any) -> str | None:
        if self.selector_key:
            return self._handle_selector(event, context)
        if self.editing_key:
            edit = context.inline_edit(event, self.editing_value, self.editing_cursor)
            if edit.action == "save":
                self._apply_edited_value(context)
            elif edit.action == "cancel":
                self._clear_edit()
            elif edit.action == "edit":
                self.editing_value = edit.value
                self.editing_cursor = edit.cursor
            return "handled"

        profiles = model.records(context.config, "product_profiles")
        if event.code == curses.KEY_LEFT or ui_input_api.key_code_matches(event.code, "h"):
            self.focus = "profiles"
            return "handled"
        if event.code == curses.KEY_RIGHT or ui_input_api.key_code_matches(event.code, "l"):
            if profiles:
                self.focus = "fields"
            return "handled"
        if event.code == 9:
            self.focus = "fields" if self.focus == "profiles" and profiles else "profiles"
            return "handled"
        if event.code == curses.KEY_UP or ui_input_api.key_code_matches(event.code, "k"):
            if self.focus == "profiles" and profiles:
                self.profile_index = (self.profile_index - 1) % len(profiles)
            else:
                self.selected = (self.selected - 1) % len(self.fields)
            return "handled"
        if event.code == curses.KEY_DOWN or ui_input_api.key_code_matches(event.code, "j"):
            if self.focus == "profiles" and profiles:
                self.profile_index = (self.profile_index + 1) % len(profiles)
            else:
                self.selected = (self.selected + 1) % len(self.fields)
            return "handled"
        if ui_input_api.key_code_matches(event.code, "a"):
            self._add_profile(context)
            return "handled"
        if ui_input_api.key_code_matches(event.code, "d") and self.focus == "profiles":
            self._delete_profile(context)
            return "handled"
        if event.code not in (curses.KEY_ENTER, 10, 13):
            return None
        if self.focus == "profiles":
            if self._selected_profile(context) is not None:
                self.focus = "fields"
            return "handled"

        key, _label = self.fields[self.selected]
        profile = self._selected_profile(context)
        if profile is None:
            return "handled"
        if key in self.choice_fields:
            self._open_selector(context, profile, key)
            return "handled"
        self.editing_key = key
        self.editing_value = self._field_value(context, profile, key)
        self.editing_cursor = len(self.editing_value)
        return "handled"

    def _selector_choices(self, context: Any, profile: dict[str, Any], key: str) -> list[str]:
        if key == "build_host":
            return [host.host_id for host in context.build_hosts]
        if key == "project":
            return [project.project_id for project in context.projects]
        return []

    def _open_selector(self, context: Any, profile: dict[str, Any], key: str) -> None:
        try:
            choices = self._selector_choices(context, profile, key)
        except (KeyError, OSError, RuntimeError, ValueError) as exc:
            context.dialogs.message("Product profile configuration", [f"Target discovery failed: {exc}"])
            return
        if not choices:
            context.dialogs.message(
                "Product profile configuration",
                [f"No choices are available for {dict(self.fields)[key]}."],
            )
            return
        self.selector_key = key
        self.selector_choices = choices
        current = str(profile.get(key) or "")
        self.selector_index = choices.index(current) if current in choices else 0
        self.selector_selected.clear()

    def _render_selector(self, ui: Any, context: Any) -> None:
        profile = self._selected_profile(context)
        if profile is None:
            self._clear_selector()
            return
        choices = self.selector_choices
        label = dict(self.fields)[self.selector_key]
        multiple = False
        ui.text(0, 0, f"Product profile: {profile.get('name') or '<not set>'}")
        ui.text(1, 0, f"Select {label.lower()}", style="accent")
        panel_top = 2
        panel_height = max(2, ui.height - 3)
        ui.box(panel_top, 0, panel_height, max(2, ui.width), label)
        visible = max(1, panel_height - 3)
        first = min(
            max(0, self.selector_index - visible + 1),
            max(0, len(choices) - visible),
        )
        for offset, choice in enumerate(choices[first : first + visible]):
            index = first + offset
            marker = "[x]" if multiple and choice in self.selector_selected else "[ ]" if multiple else "*" if index == self.selector_index else " "
            ui.text(3 + offset, 2, f"{marker} {choice}", style="selected" if index == self.selector_index else "normal")
        action = "Space: toggle | Enter: apply" if multiple else "Enter: select"
        ui.text(max(0, ui.height - 1), 0, f"Up/Down: select | {action} | q/Esc: cancel", style="accent")

    def _handle_selector(self, event: Any, context: Any) -> str:
        profile = self._selected_profile(context)
        if profile is None:
            self._clear_selector()
            return "handled"
        choices = self.selector_choices
        if event.code == 27 or ui_input_api.key_code_matches(event.code, "q"):
            self._clear_selector()
            return "handled"
        if event.code == curses.KEY_UP or ui_input_api.key_code_matches(event.code, "k"):
            self.selector_index = (self.selector_index - 1) % len(choices)
            return "handled"
        if event.code == curses.KEY_DOWN or ui_input_api.key_code_matches(event.code, "j"):
            self.selector_index = (self.selector_index + 1) % len(choices)
            return "handled"
        if event.code not in (curses.KEY_ENTER, 10, 13):
            return "handled"
        key = self.selector_key
        target_kind = "build_host" if key == "build_host" else "project"
        _replace_reference(
            context,
            f"cts_vts.product_profile.{key}",
            EntityRef("cts_vts.product_profile", model.record_id(profile)),
            target_kind,
            [choices[self.selector_index]],
        )
        self._clear_selector()
        return "handled"

    def _clear_selector(self) -> None:
        self.selector_key = ""
        self.selector_index = 0
        self.selector_choices = []
        self.selector_selected.clear()

    def _apply_edited_value(self, context: Any) -> None:
        profile = self._selected_profile(context)
        if profile is None:
            self._clear_edit()
            return
        key = self.editing_key
        value = self.editing_value.strip()
        if key == "name":
            try:
                value = model.safe_name(value)
            except ValueError as exc:
                context.dialogs.message("Product profile configuration", [str(exc)])
                return
        old_name = str(profile.get("name") or "")
        if key == "name" and value != old_name:
            if model.find(context.config, "product_profiles", value) is not None:
                context.dialogs.message("Product profile configuration", [f"Product profile already exists: {value}"])
                return
        _update_entity(
            context,
            "cts_vts.product_profile",
            "product_profiles",
            profile,
            {key: value},
        )
        self._clear_edit()

    def _clear_edit(self) -> None:
        self.editing_key = ""
        self.editing_value = ""
        self.editing_cursor = 0

    def _add_profile(self, context: Any) -> None:
        name = context.dialogs.prompt("Profile name", "product")
        if context.dialogs.prompt_cancelled:
            return
        try:
            name = model.safe_name(name)
        except ValueError as exc:
            context.dialogs.message("Product profile configuration", [str(exc)])
            return
        if model.find(context.config, "product_profiles", name) is not None:
            context.dialogs.message("Product profile configuration", [f"Product profile already exists: {name}"])
            return
        active_host_id = str(getattr(context, "active_build_host_id", "") or "")
        host = next((item for item in context.build_hosts if item.host_id == active_host_id), None)
        if host is None and context.build_hosts:
            host = context.build_hosts[0]
        active_project_id = str(getattr(context, "active_project_id", "") or "")
        project = next((item for item in context.projects if item.project_id == active_project_id), None)
        if project is None and context.projects:
            project = context.projects[0]
        _create_entity(
            context,
            "cts_vts.product_profile",
            "product_profiles",
            {
                "name": name,
                "build_host": host.host_id if host else "",
                "project": project.project_id if project else "",
            },
        )
        self.profile_index = len(model.records(context.config, "product_profiles")) - 1
        self.focus = "fields"

    def _delete_profile(self, context: Any) -> None:
        profile = self._selected_profile(context)
        if profile is None:
            return
        name = str(profile.get("name") or "")
        if not _delete_entity(
            context,
            kind="cts_vts.product_profile",
            record=profile,
            title="Delete product profile",
            question=f"Delete product profile {name}?",
            warning="This removes the saved product build configuration.",
        ):
            return
        self.profile_index = max(0, self.profile_index - 1)


def create_product_profile_configuration(_context: Any) -> ProductProfileConfigurationView:
    return ProductProfileConfigurationView()


class TestRunConfigurationView:
    fields = (
        ("name", "Run name"),
        ("runner_profile", "Test runner"),
        ("board_profile", "Board profile"),
        ("product_profile", "Product profile"),
        ("test_profile", "Test profile"),
    )
    choice_fields = frozenset({"runner_profile", "board_profile", "product_profile", "test_profile"})
    profile_keys = {
        "runner_profile": "runners",
        "board_profile": "board_profiles",
        "product_profile": "product_profiles",
        "test_profile": "test_profiles",
    }
    field_hints = {
        "name": "Unique test run id. Prepared artifacts and results are stored under this name on the test runner.",
        "runner_profile": "Test runner host that stores artifacts and executes Tradefed.",
        "board_profile": "Set of boards used as Android test devices for this run.",
        "product_profile": "Build host and Moulin project used to build images and VTS artifacts.",
        "test_profile": "CTS/VTS suites, revisions, filters, and recovery limits used by this run.",
    }

    def __init__(self) -> None:
        self.focus = "runs"
        self.run_index = 0
        self.selected = 0
        self.editing_key = ""
        self.editing_value = ""
        self.editing_cursor = 0
        self.selector_key = ""
        self.selector_index = 0
        self.selector_choices: list[str] = []

    def on_enter(self, context: Any) -> None:
        runs = model.records(context.config, "runs")
        active = str(model.state(context.config).get("active_run") or "")
        self.run_index = next((index for index, run in enumerate(runs) if run.get("id") == active), 0)

    def _selected_run(self, context: Any) -> dict[str, Any] | None:
        runs = model.records(context.config, "runs")
        if not runs:
            return None
        self.run_index = min(self.run_index, len(runs) - 1)
        return runs[self.run_index]

    def render(self, ui: Any, context: Any) -> None:
        if self.selector_key:
            self._render_selector(ui, context)
            return
        state = model.state(context.config)
        runs = model.records(context.config, "runs")
        run = self._selected_run(context)
        active = str(state.get("active_run") or "none")
        ui.text(0, 0, f"Active: {_record_name(context, 'runs', active) or 'none'}")
        ui.text(1, 0, f"Focus: {'test run list' if self.focus == 'runs' else 'fields'}", style="accent")
        panel_top = 2
        panel_height = max(2, ui.height - 3)
        ui.box(panel_top, 0, panel_height, max(2, ui.width), "Test runs")
        ui.text(3, 2, "A Name                Runner              Boards              Product             Test", style="accent")
        if not runs:
            ui.text(4, 2, "No test runs. Press 'a' to add one.", style="warning")
        minimum_detail_rows = 10
        visible_runs = max(1, min(max(1, len(runs)), panel_height - minimum_detail_rows))
        first_run = min(max(0, self.run_index - visible_runs + 1), max(0, len(runs) - visible_runs))
        for offset, item in enumerate(runs[first_run : first_run + visible_runs]):
            index = first_run + offset
            name = str(item.get("name") or "")
            is_active = str(item.get("id") or "") == active
            selected = self.focus == "runs" and index == self.run_index
            style = "selected-active" if selected and is_active else "selected" if selected else "active" if is_active else "normal"
            marker = "*" if is_active else " "
            ui.text(
                4 + offset,
                2,
                f"{marker} {name[:18]:18}  {_record_name(context, 'runners', item.get('runner_profile'))[:18]:18}  "
                f"{_record_name(context, 'board_profiles', item.get('board_profile'))[:18]:18}  "
                f"{_record_name(context, 'product_profiles', item.get('product_profile'))[:18]:18}  "
                f"{_record_name(context, 'test_profiles', item.get('test_profile'))}",
                style=style,
            )
        detail_row = 4 + visible_runs + 1
        if run is None:
            ui.text(detail_row, 2, "Selected test run: <none>", style="warning")
            ui.text(max(0, ui.height - 1), 0, "a: add | q/Esc: back", style="accent")
            return
        ui.text(detail_row, 2, "RUN", style="accent")
        ui.text(detail_row + 3, 2, "CONFIGURATION", style="accent")
        field_rows = (0, 3, 4, 5, 6)
        for index, ((key, label), row) in enumerate(zip(self.fields, field_rows)):
            editing = key == self.editing_key
            value = self.editing_value if editing else (
                str(run.get(key) or "")
                if key == "name"
                else _record_name(context, self.profile_keys[key], run.get(key))
            )
            row_model = config_field_api.host_field_row_model(
                label=label,
                key=key,
                profile=run,
                value=value,
                enabled=True,
                selected=self.focus == "fields" and index == self.selected,
                editing=editing,
            )
            draw_row = detail_row + row + 1
            ui.text(draw_row, 2, str(row_model["text"]).ljust(max(0, ui.width - 4)), style=str(row_model["state"]))
            if editing:
                ui.cursor(draw_row, min(max(0, ui.width - 2), 22 + self.editing_cursor))
        if self.editing_key:
            hint = "Enter: save | Esc: cancel | Left/Right/Home/End: move cursor"
        elif self.focus == "fields":
            hint = self.field_hints[self.fields[self.selected][0]]
        else:
            hint = "Select a test run or press 'a' to add one."
        ui.text(panel_top + panel_height - 2, 2, hint, style="accent")
        ui.text(
            max(0, ui.height - 1),
            0,
            "Left/Right: focus | Up/Down: select | Enter: edit/select | a: add | d: delete | s: set active | q/Esc: back",
            style="accent",
        )

    def handle_event(self, event: Any, context: Any) -> str | None:
        if self.selector_key:
            return self._handle_selector(event, context)
        if self.editing_key:
            edit = context.inline_edit(event, self.editing_value, self.editing_cursor)
            if edit.action == "save":
                self._apply_edited_value(context)
            elif edit.action == "cancel":
                self._clear_edit()
            elif edit.action == "edit":
                self.editing_value = edit.value
                self.editing_cursor = edit.cursor
            return "handled"

        runs = model.records(context.config, "runs")
        if event.code == curses.KEY_LEFT or ui_input_api.key_code_matches(event.code, "h"):
            self.focus = "runs"
            return "handled"
        if event.code == curses.KEY_RIGHT or ui_input_api.key_code_matches(event.code, "l"):
            if runs:
                self.focus = "fields"
            return "handled"
        if event.code == 9:
            self.focus = "fields" if self.focus == "runs" and runs else "runs"
            return "handled"
        if event.code == curses.KEY_UP or ui_input_api.key_code_matches(event.code, "k"):
            if self.focus == "runs" and runs:
                self.run_index = (self.run_index - 1) % len(runs)
            else:
                self.selected = (self.selected - 1) % len(self.fields)
            return "handled"
        if event.code == curses.KEY_DOWN or ui_input_api.key_code_matches(event.code, "j"):
            if self.focus == "runs" and runs:
                self.run_index = (self.run_index + 1) % len(runs)
            else:
                self.selected = (self.selected + 1) % len(self.fields)
            return "handled"
        if ui_input_api.key_code_matches(event.code, "a"):
            self._add_run(context)
            return "handled"
        if ui_input_api.key_code_matches(event.code, "d") and self.focus == "runs":
            self._delete_run(context)
            return "handled"
        if ui_input_api.key_code_matches(event.code, "s") and self.focus == "runs":
            self._set_active(context)
            return "handled"
        if event.code not in (curses.KEY_ENTER, 10, 13):
            return None
        if self.focus == "runs":
            if self._selected_run(context) is not None:
                self._set_active(context)
                self.focus = "fields"
            return "handled"
        run = self._selected_run(context)
        if run is None:
            return "handled"
        key, _label = self.fields[self.selected]
        if key in self.choice_fields:
            self._open_selector(context, run, key)
            return "handled"
        self.editing_key = key
        self.editing_value = str(run.get(key) or "")
        self.editing_cursor = len(self.editing_value)
        return "handled"

    def _open_selector(self, context: Any, run: dict[str, Any], key: str) -> None:
        choices = [model.record_id(item) for item in model.records(context.config, self.profile_keys[key])]
        if not choices:
            context.dialogs.message("Test run configuration", [f"No choices are available for {dict(self.fields)[key]}."])
            return
        self.selector_key = key
        self.selector_choices = choices
        current = str(run.get(key) or "")
        self.selector_index = choices.index(current) if current in choices else 0

    def _render_selector(self, ui: Any, context: Any) -> None:
        run = self._selected_run(context)
        if run is None:
            self._clear_selector()
            return
        label = dict(self.fields)[self.selector_key]
        ui.text(0, 0, f"Test run: {run.get('name') or '<not set>'}")
        ui.text(1, 0, f"Select {label.lower()}", style="accent")
        panel_top = 2
        panel_height = max(2, ui.height - 3)
        ui.box(panel_top, 0, panel_height, max(2, ui.width), label)
        visible = max(1, panel_height - 3)
        first = min(max(0, self.selector_index - visible + 1), max(0, len(self.selector_choices) - visible))
        for offset, choice in enumerate(self.selector_choices[first : first + visible]):
            index = first + offset
            selected = model.find(context.config, self.profile_keys[self.selector_key], choice)
            display = str((selected or {}).get("name") or choice)
            ui.text(3 + offset, 2, f"{'*' if index == self.selector_index else ' '} {display}", style="selected" if index == self.selector_index else "normal")
        ui.text(max(0, ui.height - 1), 0, "Up/Down: select | Enter: select | q/Esc: cancel", style="accent")

    def _handle_selector(self, event: Any, context: Any) -> str:
        run = self._selected_run(context)
        if run is None:
            self._clear_selector()
            return "handled"
        if event.code == 27 or ui_input_api.key_code_matches(event.code, "q"):
            self._clear_selector()
            return "handled"
        if event.code == curses.KEY_UP or ui_input_api.key_code_matches(event.code, "k"):
            self.selector_index = (self.selector_index - 1) % len(self.selector_choices)
            return "handled"
        if event.code == curses.KEY_DOWN or ui_input_api.key_code_matches(event.code, "j"):
            self.selector_index = (self.selector_index + 1) % len(self.selector_choices)
            return "handled"
        if event.code not in (curses.KEY_ENTER, 10, 13):
            return "handled"
        target_kind = {
            "runner_profile": "cts_vts.runner",
            "board_profile": "cts_vts.board_profile",
            "test_profile": "cts_vts.test_profile",
            "product_profile": "cts_vts.product_profile",
        }[self.selector_key]
        _replace_reference(
            context,
            f"cts_vts.run.{self.selector_key}",
            EntityRef("cts_vts.run", model.record_id(run)),
            target_kind,
            [self.selector_choices[self.selector_index]],
        )
        self._clear_selector()
        return "handled"

    def _apply_edited_value(self, context: Any) -> None:
        run = self._selected_run(context)
        if run is None:
            self._clear_edit()
            return
        try:
            value = model.safe_name(self.editing_value)
        except ValueError as exc:
            context.dialogs.message("Test run configuration", [str(exc)])
            return
        old_name = str(run.get("name") or "")
        if value != old_name and model.find(context.config, "runs", value) is not None:
            context.dialogs.message("Test run configuration", [f"Test run already exists: {value}"])
            return
        _update_entity(context, "cts_vts.run", "runs", run, {"name": value})
        self._clear_edit()

    def _clear_edit(self) -> None:
        self.editing_key = ""
        self.editing_value = ""
        self.editing_cursor = 0

    def _clear_selector(self) -> None:
        self.selector_key = ""
        self.selector_index = 0
        self.selector_choices = []

    def _set_active(self, context: Any) -> None:
        run = self._selected_run(context)
        if run is None:
            return
        _replace_reference(
            context,
            "cts_vts.active_run",
            config_entities.SELECTION,
            "cts_vts.run",
            [model.record_id(run)],
        )

    def _add_run(self, context: Any) -> None:
        missing = [label for key, label in self.fields[1:] if not model.records(context.config, self.profile_keys[key])]
        if missing:
            context.dialogs.message(
                "Test run configuration",
                ["Create the required profiles before adding a test run:"] + [f"- {label}" for label in missing],
            )
            return
        name = context.dialogs.prompt("Test run name", "run-1")
        if context.dialogs.prompt_cancelled:
            return
        try:
            name = model.safe_name(name)
        except ValueError as exc:
            context.dialogs.message("Test run configuration", [str(exc)])
            return
        if model.find(context.config, "runs", name) is not None:
            context.dialogs.message("Test run configuration", [f"Test run already exists: {name}"])
            return
        active_runner = str(model.state(context.config).get("active_runner") or "")
        runners = model.records(context.config, "runners")
        runner = model.find(context.config, "runners", active_runner) or runners[0]
        value = {
            "name": name,
            "runner_profile": model.record_id(runner),
            "board_profile": model.record_id(model.records(context.config, "board_profiles")[0]),
            "product_profile": model.record_id(model.records(context.config, "product_profiles")[0]),
            "test_profile": model.record_id(model.records(context.config, "test_profiles")[0]),
        }
        model.resolve_run(context.config, value)
        _create_entity(
            context,
            "cts_vts.run",
            "runs",
            value,
        )
        self.run_index = len(model.records(context.config, "runs")) - 1
        self.focus = "fields"

    def _delete_run(self, context: Any) -> None:
        run = self._selected_run(context)
        if run is None:
            return
        name = str(run.get("name") or "")
        if not _delete_entity(
            context,
            kind="cts_vts.run",
            record=run,
            title="Delete test run",
            question=f"Delete test run {name}?",
            warning="This removes the saved run configuration. Remote artifacts and results are not deleted.",
        ):
            return
        self.run_index = max(0, self.run_index - 1)


def create_test_run_configuration(_context: Any) -> TestRunConfigurationView:
    return TestRunConfigurationView()


def _run_plan(
    context: Any,
    devices: list[dict[str, Any]] | None = None,
    *,
    resolve_devices: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    run = model.active_run(context.config)
    if run is None:
        raise ValueError("configure and select an active test run first")
    runner, board, test, product = model.resolve_run(context.config, run)
    project_id = str(product.get("project") or "")
    if ProductCapability.ANDROID_ADB not in context.commands.product_capabilities(
        project_id,
        str(product.get("build_host") or ""),
    ):
        raise ValueError("selected product configuration does not enable an Android domain with ADB")
    if int(test.get("max_reflashes", 0)) > 0:
        missing = [
            str(device.get("board_id"))
            for device in board["devices"]
            if BoardCapability.REFLASH not in context.commands.board_capabilities(str(device.get("board_id")))
        ]
        if missing:
            raise ValueError("board type does not provide a reflash flow for: " + ", ".join(missing))
    if int(test.get("max_reboots", 0)) > 0:
        missing = [
            str(device.get("board_id"))
            for device in board["devices"]
            if BoardCapability.REBOOT not in context.commands.board_capabilities(str(device.get("board_id")))
        ]
        if missing:
            raise ValueError("board does not provide a reboot operation for: " + ", ".join(missing))
    directory = commands.run_dir(str(runner["workspace_dir"]), str(run["name"]))
    selected_devices = devices if devices is not None else board["devices"]
    if resolve_devices:
        selected_devices = _resolve_adb_devices(context, selected_devices, product)
    selected_devices = [dict(device) for device in selected_devices]
    plan = {
        "run_name": run["name"],
        "suites": test["suites"],
        "devices": selected_devices,
        "test_profile": test,
        "product_profile": product,
        "suite_dirs": {
            "cts": str(PurePosixPath(directory) / "artifacts" / "android-cts"),
            "vts": str(PurePosixPath(directory) / "artifacts" / "android-vts"),
        },
    }
    plan["test_profile"]["skipped_modules"] = list(test.get("skipped_modules", []))
    return run, runner, plan


def _resolve_adb_devices(
    context: Any,
    devices: list[dict[str, Any]],
    product: dict[str, Any],
) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for device in devices:
        value, _probe, error = _probe_adb_device(context, device, product)
        if value is None:
            board_id = str(device.get("board_id") or "")
            raise RuntimeError(f"ADB resolver failed for {board_id}: {error}")
        resolved.append(value)
    return resolved


def _resolver_probe_status(output: str) -> dict[str, Any]:
    prefix = "__MRC_BOARD_STATUS__"
    for line in output.splitlines():
        if not line.startswith(prefix):
            continue
        value = json.loads(line[len(prefix) :])
        if isinstance(value, dict):
            return value
    return {}


def _resolver_progress_status(line: str) -> dict[str, Any]:
    prefix = "__MRC_BOARD_PROGRESS__"
    if not line.startswith(prefix):
        return {}
    value = json.loads(line[len(prefix) :])
    return value if isinstance(value, dict) else {}


def _resolver_log_message(line: str) -> str:
    prefix = "__MRC_BOARD_LOG__"
    if not line.startswith(prefix):
        return ""
    value = json.loads(line[len(prefix) :])
    return str(value.get("message") or "") if isinstance(value, dict) else ""


def _probe_adb_device(
    context: Any,
    device: dict[str, Any],
    product: dict[str, Any],
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any], str]:
    board_hosts = {board.board_id: board for board in context.boards}
    board_id = str(device.get("board_id") or "")
    serial = str(device.get("serial") or "").strip()
    probe: dict[str, Any] = {}
    if not serial:
        board = board_hosts.get(board_id)
        if board is None:
            return None, probe, f"board profile references a missing board host: {board_id}"
        try:
            resolver = context.commands.product_adb_resolver(
                str(product.get("project") or ""),
                board_id,
            )
            stream = getattr(context.commands, "capture_host_stream", None)
            if progress is not None and callable(stream):
                def on_stdout_line(line: str) -> None:
                    message = _resolver_log_message(line)
                    if message:
                        progress({"_log": message})
                        return
                    value = _resolver_progress_status(line)
                    if value:
                        progress(value)

                result = stream(
                    board.remote,
                    resolver.command,
                    on_stdout_line,
                    timeout=resolver.timeout_seconds,
                )
            else:
                result = context.commands.capture_host(
                    board.remote,
                    resolver.command,
                    timeout=resolver.timeout_seconds,
                )
        except (OSError, RuntimeError, ValueError) as exc:
            return None, probe, str(exc)
        try:
            probe = _resolver_probe_status(result.stdout)
        except json.JSONDecodeError as exc:
            return None, {}, f"resolver returned invalid status: {exc}"
        if result.returncode != 0:
            details = str(probe.get("error") or "").strip()
            details = details or result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            return None, probe, details
        lines = [
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip() and not line.startswith("__MRC_BOARD_")
        ]
        if not lines:
            return None, probe, "ADB resolver returned no serial"
        serial = lines[-1]
    else:
        probe = {"adb": True, "adb_serial": serial, "source": "override"}
    if any(character.isspace() for character in serial):
        return None, probe, f"ADB resolver returned an invalid serial for {board_id}"
    value = dict(device)
    value["serial"] = serial
    return value, probe, ""


def _available_boards_product(context: Any) -> dict[str, Any]:
    run = model.active_run(context.config)
    if run is not None:
        _runner, _board, _test, product = model.resolve_run(context.config, run)
        return product
    active_project_id = str(getattr(context, "active_project_id", "") or "")
    if active_project_id:
        return {"project": active_project_id}
    products = model.records(context.config, "product_profiles")
    if len(products) == 1:
        return products[0]
    if not products:
        raise ValueError("select an active project before resolving Android devices")
    raise ValueError("select an active test run or project before resolving Android devices")


def _agent_source() -> bytes:
    return Path(__file__).with_name("runner_agent.py").read_bytes()


def prepare_test_run(context: Any) -> None:
    def apply() -> None:
        run, runner, plan = _run_plan(context, resolve_devices=True)
        _runner, board, test, product = model.resolve_run(context.config, run)
        selected = set(model.csv_values(_prompt(context, "Prepare steps (build,flash,artifacts)", "build,flash,artifacts")))
        unknown = selected - {"build", "flash", "artifacts"}
        if unknown:
            raise ValueError("unknown preparation steps: " + ", ".join(sorted(unknown)))
        remote = model.runner_remote(runner)
        host = next((item for item in context.build_hosts if item.host_id == product["build_host"]), None)
        project = next((item for item in context.projects if item.project_id == product["project"]), None)
        if host is None or project is None:
            raise ValueError("product profile references a missing build host or project")
        if not project.docker_image or not project.moulin_manifest:
            raise ValueError("selected project requires a Docker image and Moulin manifest")
        directory = commands.product_dir(host.projects_dir, project.project_dir)
        argv: list[list[str]] = []
        if "build" in selected or ("artifacts" in selected and "vts" in test["suites"]):
            argv.append(context.commands.prepare_product_command(host.host_id, project.project_id))
            checkout = context.commands.checkout_product_command(host.host_id, project.project_id)
            if checkout is not None:
                argv.append(checkout)
        needs_reflash = "flash" in selected or int(test.get("max_reflashes", 0)) > 0
        reflash_plans: dict[str, Any] = {}
        reboot_plans: dict[str, Any] = {}
        for device in plan["devices"]:
            board_id = str(device["board_id"])
            reboot_plans[board_id] = context.commands.board_operation_plan(
                board_id,
                host.host_id,
                project.project_id,
                BoardCapability.REBOOT,
                build_params=dict(project.parameters),
            )
        if needs_reflash:
            for device in plan["devices"]:
                board_id = str(device["board_id"])
                reflash_plans[board_id] = context.commands.board_operation_plan(
                    board_id,
                    host.host_id,
                    project.project_id,
                    BoardCapability.REFLASH,
                    build_params=dict(project.parameters),
                )
        if "build" in selected:
            build_targets = list(project.build_targets)
            for operation in reflash_plans.values():
                for target in operation.build_targets:
                    if target not in build_targets:
                        build_targets.append(target)
            argv.append(context.commands.ensure_product_graph_command(host.host_id, project.project_id))
            argv.append(context.commands.product_build_command(host.host_id, project.project_id, build_targets))
        for device in plan["devices"]:
            reboot = reboot_plans[str(device["board_id"])]
            device["reboot"] = {
                "operation_id": reboot.operation_id,
                "commands": [list(command) for command in reboot.execute_commands],
                "execute_timeout_seconds": reboot.execute_timeout_seconds,
                "post_execute_delay_seconds": reboot.post_execute_delay_seconds,
            }
            operation = reflash_plans.get(str(device["board_id"]))
            if operation is not None:
                argv.extend([list(command) for command in operation.provision_commands])
                device["reflash"] = {
                    "operation_id": operation.operation_id,
                    "commands": [list(command) for command in operation.execute_commands],
                    "execute_timeout_seconds": operation.execute_timeout_seconds,
                    "post_execute_delay_seconds": operation.post_execute_delay_seconds,
                }
                if "flash" in selected:
                    argv.extend([list(command) for command in operation.execute_commands])
        argv.append(context.commands.host_command(remote, commands.deploy_agent_command(str(runner["workspace_dir"]), str(run["name"]), _agent_source())))
        argv.append(context.commands.host_command(remote, commands.write_plan_command(str(runner["workspace_dir"]), str(run["name"]), plan)))
        if "artifacts" in selected:
            run_directory = commands.run_dir(str(runner["workspace_dir"]), str(run["name"]))
            if "cts" in test["suites"]:
                artifact_dir = str(PurePosixPath(run_directory) / "artifacts")
                command = (
                    f"mkdir -p {shlex.quote(artifact_dir)} && cd {shlex.quote(artifact_dir)} && "
                    f"curl -fL {shlex.quote(test['cts_url'])} -o android-cts.zip && "
                    "rm -rf android-cts && unzip -q android-cts.zip"
                )
                argv.append(context.commands.host_command(remote, command))
            if "vts" in test["suites"]:
                android = context.commands.product_android_build_context(
                    project.project_id,
                    host.host_id,
                    build_params=dict(project.parameters),
                )
                argv.append(
                    context.commands.product_inner_command(
                        host.host_id,
                        project.project_id,
                        commands.vts_build_command(
                            android.build_dir,
                            android.environment,
                            android.setup_commands,
                        ),
                    )
                )
                source = str(PurePosixPath(directory) / android.build_dir / "out/host/linux-x86/vts")
                target = str(PurePosixPath(run_directory) / "artifacts")
                source_command = f"tar -C {shlex.quote(source)} -cf - android-vts"
                target_command = f"mkdir -p {shlex.quote(target)} && tar -C {shlex.quote(target)} -xf -"
                pipeline = shlex.join(context.commands.build_host_command(host.host_id, source_command))
                pipeline += " | " + shlex.join(context.commands.host_command(remote, target_command))
                argv.append(["bash", "-lc", pipeline])
        context.commands.run(f"Prepare CTS/VTS run {run['name']}", argv)

    _handle(context, "Prepare test run", apply)


def start_or_continue(context: Any) -> None:
    def apply() -> None:
        run, runner, plan = _run_plan(context, resolve_devices=True)
        remote = model.runner_remote(runner)
        update = context.commands.capture_host(
            remote,
            commands.write_plan_command(str(runner["workspace_dir"]), str(run["name"]), plan),
            timeout=45,
        )
        if update.returncode != 0:
            raise RuntimeError(update.stderr.strip() or "failed to update the test-run plan")
        probe = context.commands.capture_host(remote, commands.agent_command(str(runner["workspace_dir"]), str(run["name"]), "probe"), timeout=45)
        try:
            statuses = json.loads(probe.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError) as exc:
            raise RuntimeError(probe.stderr.strip() or "test-runner probe did not return device status") from exc
        unavailable = [serial for serial, status in statuses.items() if status == "unavailable"]
        effective = plan["devices"]
        commands_to_run: list[list[str]] = []
        if unavailable:
            lines = [f"{serial}: unavailable" for serial in unavailable]
            if not context.dialogs.confirm("Limited test run", "\n".join(lines), warning="Some target boards are unavailable."):
                return
            effective = [
                device
                for device in effective
                if statuses.get(str(device["serial"])) != "unavailable"
            ]
            if not effective:
                raise RuntimeError("no reachable target boards remain")
            plan["devices"] = effective
            commands_to_run.append(context.commands.host_command(remote, commands.write_plan_command(str(runner["workspace_dir"]), str(run["name"]), plan)))
        commands_to_run.append(context.commands.host_command(remote, commands.agent_command(str(runner["workspace_dir"]), str(run["name"]), "start")))
        _update_entity(context, "cts_vts.run", "runs", run, {"last_status": "starting"})
        context.commands.run(f"Start CTS/VTS run {run['name']}", commands_to_run)

    _handle(context, "Start test run", apply)


def stop_test_run(context: Any) -> None:
    def apply() -> None:
        run, runner, _plan = _run_plan(context)
        _update_entity(context, "cts_vts.run", "runs", run, {"last_status": "stopped"})
        context.commands.run_host(model.runner_remote(runner), f"Stop CTS/VTS run {run['name']}", [commands.agent_command(str(runner["workspace_dir"]), str(run["name"]), "stop")])

    _handle(context, "Stop test run", apply)


def reset_test_run(context: Any) -> None:
    def apply() -> None:
        run, runner, _plan = _run_plan(context)
        scope = _prompt(context, "Reset scope (results/all)", "results").strip().lower()
        if scope not in {"results", "all"}:
            raise ValueError("reset scope must be results or all")
        if not context.dialogs.confirm("Reset test run", f"Reset {scope} data for {run['name']}?", warning="This removes test-run data."):
            return
        context.commands.run_host(model.runner_remote(runner), f"Reset CTS/VTS run {run['name']}", [commands.agent_command(str(runner["workspace_dir"]), str(run["name"]), "reset", scope)])

    _handle(context, "Reset test run", apply)


class AvailableBoardsView:
    def __init__(self) -> None:
        self.boards: list[dict[str, Any]] = []
        self.selected = 0
        self.error = ""
        self.checking = False
        self.log_panel = PluginLogPanel()
        self._results: queue.SimpleQueue[tuple[list[dict[str, Any]], str]] = queue.SimpleQueue()
        self._progress: queue.SimpleQueue[tuple[int, dict[str, Any]]] = queue.SimpleQueue()

    def on_enter(self, context: Any) -> None:
        self._load_boards(context)

    def _load_boards(self, context: Any) -> None:
        self.boards = []
        cache = _board_status_cache(context)
        configured_board_ids: set[str] = set()
        for board_profile in model.records(context.config, "board_profiles"):
            for device in board_profile.get("devices", []):
                if not isinstance(device, dict):
                    continue
                board_id = str(device.get("board_id") or "")
                configured_board_ids.add(board_id)
                configured_serial = str(device.get("serial") or "")
                cached = cache.get(board_id, {})
                cached_serial = str(cached.get("serial") or "")
                cache_matches = bool(cached_serial) and (not configured_serial or cached_serial == configured_serial)
                self.boards.append(
                    {
                        "board_profile": str(board_profile.get("name") or ""),
                        "board_id": board_id,
                        "serial": configured_serial or cached_serial,
                        "configured_serial": configured_serial,
                        "available": bool(cached.get("available")) if cache_matches else False,
                        "adb_checked": bool(cached.get("adb_checked")) if cache_matches else False,
                        "adb_state": str(cached.get("adb_state") or "") if cache_matches else "",
                        "state": str(cached.get("state") or "not checked") if cache_matches else "not checked",
                        "probe": deepcopy(cached.get("probe", {})) if cache_matches else {},
                        "logs": [],
                        "error": str(cached.get("error") or "") if cache_matches else "",
                        "android_serial": str(cached.get("android_serial") or "") if cache_matches else "",
                        "build_id": str(cached.get("build_id") or "") if cache_matches else "",
                        "build_incremental": str(cached.get("build_incremental") or "") if cache_matches else "",
                        "build_fingerprint": str(cached.get("build_fingerprint") or "") if cache_matches else "",
                    }
                )
        for board_id in set(cache) - configured_board_ids:
            del cache[board_id]
        self.selected = min(self.selected, max(0, len(self.boards) - 1))

    def refresh(
        self,
        context: Any,
        indices: list[int] | None = None,
        progress: Callable[[int, dict[str, Any]], None] | None = None,
    ) -> None:
        self.error = ""
        try:
            runner = model.active_runner(context.config)
            runner_remote = model.runner_remote(runner)
            if not runner_remote:
                raise ValueError("active test runner SSH is not configured")
            product = _available_boards_product(context)
            if not self.boards:
                self._load_boards(context)
            target_indices = indices if indices is not None else list(range(len(self.boards)))
            resolved: list[dict[str, Any]] = []
            for index in target_indices:
                if index < 0 or index >= len(self.boards):
                    continue
                board = self.boards[index]
                device = {
                    "board_profile": board["board_profile"],
                    "board_id": board["board_id"],
                    "serial": board["configured_serial"],
                }
                callback = None
                if progress is not None:
                    callback = lambda value, board_index=index: progress(board_index, value)
                value, probe, error = _probe_adb_device(context, device, product, callback)
                if progress is not None and error:
                    progress(index, {"_log": "ERROR: " + error})
                board.update(
                    {
                        "available": False,
                        "adb_checked": False,
                        "adb_state": "",
                        "state": "ADB pending" if value is not None else "probe failed",
                        "probe": probe,
                        "error": error,
                    }
                )
                if value is not None:
                    board["serial"] = value["serial"]
                    if progress is not None:
                        progress(index, {"_log": "resolved ADB serial " + str(value["serial"])})
                    resolved.append(value)
                _cache_board_status(context, board)
            if not resolved:
                return
            result = context.commands.capture_host(
                runner_remote,
                commands.adb_inventory_command(resolved),
                timeout=60,
            )
            if result.returncode != 0:
                details = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
                raise RuntimeError(f"ADB inventory failed: {details}")
            inventory = json.loads(result.stdout)
            if not isinstance(inventory, list):
                raise RuntimeError("ADB inventory returned an invalid response")
            by_key = {
                (str(item.get("board_profile") or ""), str(item.get("board_id") or "")): item
                for item in inventory
                if isinstance(item, dict)
            }
            for index in target_indices:
                if index < 0 or index >= len(self.boards):
                    continue
                board = self.boards[index]
                item = by_key.get((board["board_profile"], board["board_id"]))
                if item is not None:
                    probe = board.get("probe", {})
                    board.update(item)
                    board["probe"] = probe
                    board["adb_checked"] = True
                _cache_board_status(context, board)
        except (json.JSONDecodeError, OSError, RuntimeError, ValueError) as exc:
            self.error = str(exc)

    def _start_refresh(self, context: Any, indices: list[int] | None = None) -> None:
        if self.checking:
            return
        target_indices = indices if indices is not None else list(range(len(self.boards)))
        if not target_indices:
            return
        for index in target_indices:
            if 0 <= index < len(self.boards):
                self.boards[index]["state"] = "checking"
                self.boards[index]["available"] = False
                self.boards[index]["adb_checked"] = False
                self.boards[index]["error"] = ""
                self.boards[index]["logs"] = ["check started"]
        snapshot = deepcopy(self.boards)
        self.checking = True

        def check() -> None:
            worker = AvailableBoardsView()
            worker.boards = snapshot

            def report(index: int, value: dict[str, Any]) -> None:
                if 0 <= index < len(worker.boards) and value.get("_log"):
                    logs = worker.boards[index].setdefault("logs", [])
                    logs.append(str(value["_log"]))
                    del logs[:-200]
                self._progress.put((index, value))

            try:
                worker.refresh(
                    context,
                    target_indices,
                    progress=report,
                )
            except Exception as exc:
                worker.error = str(exc)
            self._results.put((worker.boards, worker.error))

        threading.Thread(target=check, name="cts-vts-board-check", daemon=True).start()

    def _confirm_refresh(self, context: Any, indices: list[int] | None = None) -> None:
        if self.checking:
            return
        target_indices = indices if indices is not None else list(range(len(self.boards)))
        targets = [
            f"{self.boards[index]['board_profile']} / {self.boards[index]['board_id']}"
            for index in target_indices
            if 0 <= index < len(self.boards)
        ]
        if not targets:
            return
        details = [
            "This check takes exclusive control of each serial console and sends control characters.",
            "It may switch between Dom0 and DomD and interrupt another user's console session.",
            "",
            "Boards:",
            *(f"  {target}" for target in targets),
        ]
        if context.dialogs.confirm(
            "Check board consoles",
            "\n".join(details),
            warning="Confirm that these boards are not being used by another developer.",
        ):
            if indices is None:
                self._start_refresh(context)
            else:
                self._start_refresh(context, indices)

    def on_tick(self, context: Any) -> None:
        redraw = False
        while True:
            try:
                index, probe = self._progress.get_nowait()
            except queue.Empty:
                break
            if 0 <= index < len(self.boards):
                if probe.get("_log"):
                    logs = self.boards[index].setdefault("logs", [])
                    logs.append(str(probe["_log"]))
                    del logs[:-200]
                else:
                    self.boards[index]["probe"] = probe
                self.boards[index]["state"] = "checking"
                if probe.get("adb_serial"):
                    self.boards[index]["serial"] = str(probe["adb_serial"])
                redraw = True
        try:
            boards, error = self._results.get_nowait()
        except queue.Empty:
            boards = None
        if boards is not None:
            self.boards = boards
            self.error = error
            self.checking = False
            self.selected = min(self.selected, max(0, len(self.boards) - 1))
            redraw = True
        if redraw:
            context.request_redraw()

    @staticmethod
    def _indicator(value: Any) -> str:
        if value is True:
            return "+"
        if value is False:
            return "-"
        if value == "pending":
            return "~"
        return "?"

    def render(self, ui: Any, _context: Any) -> None:
        selected = self.boards[self.selected] if self.boards else None
        owner = (
            f"{selected['board_profile']} / {selected['board_id']}"
            if selected is not None
            else "No board selected"
        )
        logs = [str(line) for line in selected.get("logs", []) if str(line)] if selected is not None else []
        log_running = bool(selected is not None and selected.get("state") == "checking")
        if self.log_panel.expanded:
            self.log_panel.draw(
                ui,
                top=0,
                left=0,
                height=max(3, ui.height - 1),
                width=ui.width,
                owner=owner,
                lines=logs,
                running=log_running,
            )
            ui.text(
                max(0, ui.height - 1),
                0,
                "Logs full | Up/Down/PgUp/PgDn scroll | f/Esc shrink",
                style="accent",
            )
            return

        log_x = ui.width // 2
        show_logs = log_x >= 36 and ui.width - log_x >= 36
        left_width = log_x - 1 if show_logs else ui.width
        if show_logs:
            self.log_panel.draw(
                ui,
                top=0,
                left=log_x,
                height=max(3, ui.height - 1),
                width=ui.width - log_x,
                owner=owner,
                lines=logs,
                running=log_running,
            )

        title = "Configured Android board status"
        if self.checking:
            title += " (checking...)"
        ui.text(0, 0, title, style="accent")
        ui.text(1, 2, "[Enter Check board]  [s Check profile]  [a Check all]", style="accent")
        row = 3
        if not self.boards and not self.error:
            ui.text(row, 2, "No boards are selected by the active test run.", style="warning")

        profile_width = min(18, max(10, (left_width - 31) // 2))
        board_width = max(10, left_width - profile_width - 31)

        def cell(value: Any, width: int) -> str:
            text = str(value)
            if len(text) <= width:
                return f"{text:<{width}}"
            return text[: max(1, width - 3)] + "..."

        if self.boards:
            header = (
                f"  {cell('Profile', profile_width)} {cell('Board', board_width)} "
                f"{'Serial':^6} {'Power':^5} {'Dom0':^4} {'DomD':^4} {'ADB':^3}"
            )
            ui.text(row, 0, header, style="accent")
            row += 1
            ui.text(row, 0, "  " + "-" * max(1, left_width - 3), style="muted")
            row += 1

        max_board_rows = max(1, ui.height - row - 13)
        first_board = max(
            0,
            min(self.selected - max_board_rows + 1, len(self.boards) - max_board_rows),
        )
        visible_boards = self.boards[first_board : first_board + max_board_rows]
        for index, board in enumerate(visible_boards, start=first_board):
            available = bool(board.get("available"))
            profile = str(board.get("board_profile") or "")
            board_name = str(board.get("board_id") or "<unknown>")
            probe = board.get("probe", {})
            adb_state = str(board.get("adb_state") or "")
            adb_status: Any = None
            if board.get("adb_checked"):
                adb_status = "pending" if adb_state in {"waiting-for-adb", "booting"} else available
            values = (
                self._indicator(probe.get("serial")),
                self._indicator(probe.get("board")),
                self._indicator(probe.get("dom0")),
                self._indicator(probe.get("domd")),
                self._indicator(adb_status),
            )
            line = (
                f"{'>' if index == self.selected else ' '} "
                f"{cell(profile or '-', profile_width)} {cell(board_name, board_width)} "
                f"{f'[{values[0]}]':^6} {f'[{values[1]}]':^5} "
                f"{f'[{values[2]}]':^4} {f'[{values[3]}]':^4} {f'[{values[4]}]':^3}"
            )
            ui.text(
                row,
                0,
                line,
                style="selected" if index == self.selected else "ok" if available else "error" if board.get("error") else "normal",
            )
            row += 1

        if selected is not None and row < ui.height - 3:
            row += 1
            ui.text(row, 2, f"Selected board: {owner}", style="accent")
            row += 1
            detail_label_width = 14
            value_column = 2 + detail_label_width + 3
            ui.text(row, 2, f"{cell('Field', detail_label_width)} | Value", style="accent")
            row += 1
            ui.text(row, 2, "-" * detail_label_width + "-+-" + "-" * max(1, left_width - value_column))
            row += 1

            def detail(
                label: str,
                value: Any,
                *,
                style: str = "normal",
                max_lines: int = 1,
            ) -> None:
                nonlocal row
                ui.text(row, 2, f"{cell(label, detail_label_width)} |", style="accent")
                if max_lines == 1:
                    ui.text(row, value_column, str(value), style=style)
                else:
                    ui.wrapped_text(
                        row,
                        value_column,
                        max(1, left_width - value_column - 1),
                        str(value),
                        style=style,
                        max_lines=max_lines,
                    )
                row += max_lines

            detail("ADB serial", selected.get("serial") or "<not resolved>")
            if selected.get("adb_checked"):
                detail("Android state", str(selected.get("adb_state") or "unknown").replace("-", " "))
            probe = selected.get("probe", {})
            if probe:
                dom0_login = probe.get("dom0_login")
                domd_login = probe.get("domd_login")
                detail("Dom0 login", "entered" if dom0_login is True else "ready" if dom0_login is False else "unknown")
                detail("DomD login", "entered" if domd_login is True else "ready" if domd_login is False else "unknown")
            if selected.get("available"):
                detail("Android serial", selected.get("android_serial") or "<not reported>")
                build = str(selected.get("build_id") or "<not reported>")
                incremental = str(selected.get("build_incremental") or "")
                detail("Build", build + (f" ({incremental})" if incremental else ""))
                detail(
                    "Fingerprint",
                    selected.get("build_fingerprint") or "<not reported>",
                    max_lines=2,
                )
            elif selected.get("error"):
                detail("Error", selected["error"], style="error", max_lines=3)
        if self.error:
            ui.wrapped_text(min(row, max(0, ui.height - 4)), 0, max(1, left_width), self.error, style="error", max_lines=3)

        ui.text(
            max(0, ui.height - 1),
            0,
            "Up/Down: select | Enter: check board | s: check profile | a/r: check all | q/Esc: back",
            style="accent",
        )

    def handle_event(self, event: Any, context: Any) -> str | None:
        selected = self.boards[self.selected] if self.boards else None
        logs = [str(line) for line in selected.get("logs", []) if str(line)] if selected is not None else []
        if self.log_panel.handle_event(event, logs):
            return "handled"
        if event.code == curses.KEY_UP or ui_input_api.key_code_matches(event.code, "k"):
            if self.boards:
                self.selected = (self.selected - 1) % len(self.boards)
                self.log_panel.reset()
            return "handled"
        if event.code == curses.KEY_DOWN or ui_input_api.key_code_matches(event.code, "j"):
            if self.boards:
                self.selected = (self.selected + 1) % len(self.boards)
                self.log_panel.reset()
            return "handled"
        if event.code in (curses.KEY_ENTER, 10, 13):
            if self.boards:
                self._confirm_refresh(context, [self.selected])
            context.request_redraw()
            return "handled"
        if ui_input_api.key_code_matches(event.code, "s") and self.boards:
            profile = self.boards[self.selected]["board_profile"]
            indices = [index for index, board in enumerate(self.boards) if board["board_profile"] == profile]
            self._confirm_refresh(context, indices)
            context.request_redraw()
            return "handled"
        if ui_input_api.key_code_matches(event.code, "a", "r"):
            self._confirm_refresh(context)
            context.request_redraw()
            return "handled"
        return None


def create_available_boards(_context: Any) -> AvailableBoardsView:
    return AvailableBoardsView()


class DashboardView:
    def __init__(self) -> None:
        self.remote_state: dict[str, Any] = {}
        self.device_statuses: dict[str, str] = {}
        self.unresolved_devices: list[str] = []
        self.error = ""
        self.refreshing = False
        self._results: queue.SimpleQueue[
            tuple[dict[str, Any], dict[str, str], list[str], str]
        ] = queue.SimpleQueue()
        self._waiting_since: dict[str, float] = {}
        self._next_refresh_at = 0.0

    def on_enter(self, context: Any) -> None:
        self._start_refresh(context)

    def _start_refresh(self, context: Any, *, preserve: bool = False) -> None:
        if self.refreshing:
            return
        if not preserve:
            self.remote_state = {}
            self.device_statuses = {}
            self.unresolved_devices = []
            self.error = ""
            self._waiting_since = {}
            self._next_refresh_at = 0.0
        if model.active_run(context.config) is None:
            return
        self.refreshing = True

        def check() -> None:
            worker = DashboardView()
            try:
                worker.refresh(context)
            except Exception as exc:
                worker.error = str(exc)
            self._results.put(
                (
                    worker.remote_state,
                    worker.device_statuses,
                    worker.unresolved_devices,
                    worker.error,
                )
            )

        threading.Thread(target=check, name="cts-vts-run-status", daemon=True).start()
        context.request_redraw()

    def on_tick(self, context: Any) -> None:
        try:
            remote_state, device_statuses, unresolved_devices, error = self._results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.remote_state = remote_state
            self.device_statuses = device_statuses
            self.unresolved_devices = unresolved_devices
            self.error = error
            self.refreshing = False
            now = time.monotonic()
            timeout = self._adb_wait_timeout_seconds(context)
            pending = False
            for serial, state in list(self.device_statuses.items()):
                if state not in {"waiting-for-adb", "booting"}:
                    self._waiting_since.pop(serial, None)
                    continue
                started = self._waiting_since.setdefault(serial, now)
                if now - started >= timeout:
                    self.device_statuses[serial] = "unavailable"
                    self._waiting_since.pop(serial, None)
                else:
                    pending = True
            self._next_refresh_at = now + 5 if pending else 0.0
            context.request_redraw()
        if not self.refreshing and self._next_refresh_at and time.monotonic() >= self._next_refresh_at:
            self._next_refresh_at = 0.0
            self._start_refresh(context, preserve=True)

    @staticmethod
    def _adb_wait_timeout_seconds(context: Any) -> int:
        run = model.active_run(context.config)
        if run is None:
            return 5 * 60
        try:
            _runner, _board, test, _product = model.resolve_run(context.config, run)
        except ValueError:
            return 5 * 60
        return max(1, int(test.get("adb_loss_timeout_minutes", 5))) * 60

    def refresh(self, context: Any) -> None:
        self.remote_state = {}
        self.device_statuses = {}
        self.unresolved_devices = []
        self.error = ""
        run = model.active_run(context.config)
        if run is None:
            return
        try:
            runner, board, _test, _product = model.resolve_run(context.config, run)
            remote = model.runner_remote(runner)
            if not remote:
                self.error = "Test runner SSH access is not configured"
                return
            result = context.commands.capture_host(
                remote,
                commands.agent_status_command(str(runner["workspace_dir"]), str(run["name"])),
                timeout=15,
            )
            if result.returncode == 0:
                value = json.loads(result.stdout)
                self.remote_state = value if isinstance(value, dict) else {}
            else:
                details = result.stderr.strip().splitlines()
                self.error = "Runner status check failed" + (f": {details[-1]}" if details else "")
            if self.remote_state:
                run["last_status"] = str(self.remote_state.get("status") or "unknown")
            cache = _board_status_cache(context)
            devices = [dict(device) for device in board.get("devices", []) if isinstance(device, dict)]
            for device in devices:
                configured_serial = str(device.get("serial") or "").strip()
                cached = cache.get(str(device.get("board_id") or ""), {})
                cached_serial = str(cached.get("serial") or "").strip()
                if not configured_serial and cached_serial:
                    device["serial"] = cached_serial
            resolved_devices = [device for device in devices if str(device.get("serial") or "").strip()]
            self.unresolved_devices = [
                str(device.get("board_id") or "<unnamed>")
                for device in devices
                if not str(device.get("serial") or "").strip()
            ]
            if not resolved_devices:
                return
            probe = context.commands.capture_host(
                remote,
                commands.adb_probe_command(resolved_devices),
                timeout=45,
            )
            if probe.returncode == 0:
                value = json.loads(probe.stdout)
                if isinstance(value, dict):
                    self.device_statuses = {
                        str(serial): (
                            "ready" if state is True else "unavailable" if state is False else str(state)
                        )
                        for serial, state in value.items()
                    }
            if probe.returncode and not self.error:
                details = probe.stderr.strip().splitlines()
                self.error = "ADB status check failed" + (f": {details[-1]}" if details else "")
        except (json.JSONDecodeError, OSError, RuntimeError, ValueError) as exc:
            self.error = str(exc)

    def render(self, ui: Any, context: Any) -> None:
        run = model.active_run(context.config)
        ui.text(0, 0, "Active test run", style="title")
        if run is None:
            ui.text(2, 2, "No active run is configured.", style="error")
            ui.text(3, 2, "Open Test run configuration and select a run.")
            ui.text(max(0, ui.height - 1), 0, "r: refresh", style="accent")
            return
        try:
            runner, board, test, product = model.resolve_run(context.config, run)
        except ValueError as exc:
            ui.text(2, 2, str(exc), style="error")
            ui.text(max(0, ui.height - 1), 0, "r: refresh", style="accent")
            return

        directory = commands.run_dir(str(runner.get("workspace_dir") or ""), str(run.get("name") or ""))
        suites = ", ".join(str(value).upper() for value in test.get("suites", [])) or "not configured"
        status = (
            "loading"
            if self.refreshing and not self.remote_state
            else str(self.remote_state.get("status") or "unknown").replace("-", " ")
        )
        board_count = len([device for device in board.get("devices", []) if isinstance(device, dict)])
        row = 2
        ui.text(row, 0, "Run", style="accent")
        row += 1
        ui.text(row, 2, f"Name: {run.get('name') or '<not set>'}")
        row += 1
        ui.text(row, 2, f"State: {status}", style="error" if status in {"unknown", "not prepared"} else "ok")
        row += 1
        ui.text(row, 2, f"Directory: {directory}")
        if status == "not prepared":
            row += 1
            ui.text(row, 2, "Next action: Prepare test run")
        row += 2
        ui.text(row, 0, "Configuration", style="accent")
        row += 1
        ui.text(row, 2, f"Runner: {runner.get('name')} ({model.runner_remote(runner) or 'SSH not configured'})")
        row += 1
        ui.text(row, 2, f"Boards: {board.get('name')} ({board_count})")
        row += 1
        ui.text(row, 2, f"Tests: {test.get('name')} ({suites})")
        row += 1
        ui.text(row, 2, f"Product: {product.get('name')}")
        row += 2
        if self.remote_state and status not in {"unknown", "not prepared"}:
            ui.text(row, 0, "Progress", style="accent")
            row += 1
            ui.text(row, 2, f"Suite: {self.remote_state.get('active_suite') or '-'}")
            row += 1
            ui.text(row, 2, f"Modules: {self.remote_state.get('completed_modules', 0)} / {self.remote_state.get('total_modules', 0)}")
            row += 1
            ui.text(row, 2, f"Session: {self.remote_state.get('head_session') or '-'}")
            row += 2
        ui.text(row, 0, "ADB devices", style="accent")
        row += 1
        labels = {
            "ready": ("ready", "ok"),
            "booting": ("Android booting", "accent"),
            "waiting-for-adb": ("waiting for ADB", "accent"),
            "unavailable": ("unavailable", "error"),
        }
        for serial, state in sorted(self.device_statuses.items()):
            label, style = labels.get(state, (state, "error"))
            ui.text(row, 2, f"{serial}: {label}", style=style)
            row += 1
        if self.unresolved_devices:
            ui.wrapped_text(
                row,
                2,
                max(1, ui.width - 4),
                "ADB serial not resolved for: " + ", ".join(self.unresolved_devices),
                style="error",
                max_lines=2,
            )
            row += 2
            ui.text(row, 2, "Open Boards status and check these boards.")
            row += 1
        elif self.refreshing:
            ui.text(row, 2, "Checking runner and ADB status...")
            row += 1
        elif not self.device_statuses:
            ui.text(row, 2, "No devices are configured.")
            row += 1
        if self.error:
            ui.wrapped_text(min(row + 1, max(0, ui.height - 4)), 0, max(1, ui.width), self.error, style="error", max_lines=2)
        ui.text(max(0, ui.height - 1), 0, "r: refresh", style="accent")

    def handle_event(self, event: Any, context: Any) -> str | None:
        if ui_input_api.key_code_matches(event.code, "r"):
            self._start_refresh(context)
            return "handled"
        return None


def create_dashboard(_context: Any) -> DashboardView:
    return DashboardView()
