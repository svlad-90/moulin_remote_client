"""Host-owned runtime for plugin actions, capabilities, and custom views."""

from __future__ import annotations

import curses
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from components.config.api import accessors as config_accessors
from components.plugins.src.discovery import PluginDiscovery
from components.plugins.src.model import (
    BoardProfile,
    PluginDefinition,
    UiEvent,
    plugin_config,
    plugin_enabled,
    set_plugin_enabled,
)
from components.remote.api import transport as remote_transport
from components.ui.api import dialogs as ui_dialog_api
from components.ui.api import input as ui_input_api
from components.ui.api.menu import MenuItem


class PluginCommands:
    def __init__(self, app: Any) -> None:
        self._app = app

    def run(self, title: str, commands: list[list[str]]) -> int:
        return self._app.command_workflow_service().run_commands(self._app, title, commands)

    def run_build_host(self, title: str, commands: list[str]) -> int:
        remote = config_accessors.remote_spec_for_config(self._app.config)
        if not remote:
            raise RuntimeError("build host is not configured")
        return self.run(title, [remote_transport.ssh_command(remote, command) for command in commands])

    def run_board(self, board_id: str, title: str, commands: list[str]) -> int:
        board = self._board(board_id)
        if not board.remote:
            raise RuntimeError(f"board host is not configured: {board_id}")
        return self.run(title, [remote_transport.ssh_command(board.remote, command) for command in commands])

    def run_boards(self, title: str, commands_by_board: dict[str, list[str]]) -> int:
        commands: list[list[str]] = []
        for board_id, remote_commands in commands_by_board.items():
            board = self._board(board_id)
            if not board.remote:
                raise RuntimeError(f"board host is not configured: {board_id}")
            commands.extend(remote_transport.ssh_command(board.remote, command) for command in remote_commands)
        return self.run(title, commands)

    def _board(self, board_id: str) -> BoardProfile:
        for board in board_profiles(self._app.config):
            if board.board_id == board_id:
                return board
        raise KeyError(f"unknown board host: {board_id}")


class PluginDialogs:
    def __init__(self, app: Any) -> None:
        self._app = app

    def confirm(self, title: str, message: str, *, warning: str = "Confirm plugin action.") -> bool:
        return self._app.dialog_workflow_controller().run_confirm_dialog(
            self._app,
            ui_dialog_api.ConfirmContent(
                title=title,
                warning=warning,
                subject=title,
                details=message,
                footer="Enter/y: run | n/q/Esc: cancel",
            ),
        )

    def message(self, title: str, lines: list[str]) -> None:
        self._app.show_message(title, lines)

    def prompt(self, label: str, current: str = "") -> str:
        return self._app.prompt(label, current)


class PluginContext:
    """Capabilities available to plugin handlers and views."""

    def __init__(self, app: Any, definition: PluginDefinition, runtime: "PluginRuntime") -> None:
        self._app = app
        self._definition = definition
        self._runtime = runtime
        self.commands = PluginCommands(app)
        self.dialogs = PluginDialogs(app)

    @property
    def plugin_id(self) -> str:
        return self._definition.plugin_id

    @property
    def config(self) -> dict[str, Any]:
        values = plugin_config(self._app.config, self.plugin_id)
        for setting in self._definition.settings:
            values.setdefault(setting.key, setting.default)
        return values

    @property
    def boards(self) -> tuple[BoardProfile, ...]:
        return board_profiles(self._app.config)

    @property
    def active_board_id(self) -> str:
        return str(self._app.config.get("active_board_host") or "")

    def save_config(self) -> None:
        self._app.dependencies.save_config(self._app.config)

    def open_view(self, view_id: str) -> None:
        self._runtime.open_view(self._app, self._definition, view_id)

    def close_view(self) -> None:
        self._runtime.close_view(self._app)

    def request_redraw(self) -> None:
        self._app.main_full_redraw = True


class PluginCanvas:
    """Coordinate-safe drawing surface owned and refreshed by the host."""

    def __init__(self, app: Any, *, top: int, left: int, height: int, width: int) -> None:
        self._app = app
        self._top = top
        self._left = left
        self.height = max(0, height)
        self.width = max(0, width)

    def text(self, row: int, column: int, text: str, *, style: str = "normal") -> None:
        if not self._inside(row, column):
            return
        available = max(0, self.width - column)
        self._app.add(self._top + row, self._left + column, text[:available], self._attr(style))

    def box(self, row: int, column: int, height: int, width: int, title: str = "", *, style: str = "normal") -> None:
        if not self._inside(row, column):
            return
        clipped_height = min(height, self.height - row)
        clipped_width = min(width, self.width - column)
        if clipped_height >= 2 and clipped_width >= 2:
            self._app.draw_box(
                self._top + row,
                self._left + column,
                clipped_height,
                clipped_width,
                title,
                self._attr(style),
            )

    def wrapped_text(self, row: int, column: int, width: int, text: str, *, style: str = "normal", max_lines: int = 4) -> int:
        if not self._inside(row, column):
            return 0
        return self._app.draw_wrapped(
            self._top + row,
            self._left + column,
            min(width, self.width - column),
            text,
            self._attr(style),
            max_lines,
        )

    def scrollbar(self, row: int, column: int, height: int, total: int, visible: int, scroll: int) -> None:
        if self._inside(row, column):
            self._app.draw_scrollbar(
                self._top + row,
                self._left + column,
                min(height, self.height - row),
                total,
                visible,
                scroll,
            )

    def _inside(self, row: int, column: int) -> bool:
        return 0 <= row < self.height and 0 <= column < self.width

    def _attr(self, style: str) -> int:
        if style == "title":
            return curses.A_BOLD
        if style == "accent":
            return self._app.accent_attr()
        if style == "warning":
            return self._app.warn_attr()
        if style == "error":
            return self._app.error_attr()
        if style == "ok":
            return self._app.ok_attr()
        if style == "selected":
            return self._app.selected_attr()
        return 0


@dataclass
class ActivePluginView:
    definition: PluginDefinition
    view_id: str
    label: str
    view: Any


class PluginRuntime:
    """Bridge plugin declarations to the host menu and event loop."""

    def __init__(self, plugins_dir: Path) -> None:
        self.discovery = PluginDiscovery(plugins_dir)

    def definitions(self, *, refresh: bool = False) -> list[PluginDefinition]:
        return self.discovery.discover(refresh=refresh)

    def build_items(self, app: Any) -> list[MenuItem]:
        items: list[MenuItem] = []
        for definition in self.definitions():
            if definition.error or not plugin_enabled(app.config, definition.plugin_id):
                continue
            try:
                self.discovery.load_module(definition)
                items.extend(self._definition_items(app, definition))
            except Exception as exc:
                definition.error = str(exc)
        return items

    def set_enabled(self, app: Any, definition: PluginDefinition, enabled: bool) -> None:
        set_plugin_enabled(app.config, definition.plugin_id, enabled)
        if enabled and not definition.error:
            try:
                self.discovery.load_module(definition)
            except Exception as exc:
                definition.error = str(exc)
                set_plugin_enabled(app.config, definition.plugin_id, False)
        app.dependencies.save_config(app.config)
        if definition.error:
            app.status = f"Plugin {definition.name}: {definition.error}"
        else:
            app.status = f"Plugin {definition.name}: {'enabled' if enabled else 'disabled'}"
        app.menu_dirty = True
        app.main_full_redraw = True

    def open_view(self, app: Any, definition: PluginDefinition, view_id: str) -> None:
        view_definition = definition.views.get(view_id)
        if view_definition is None:
            raise KeyError(f"plugin {definition.plugin_id} has no view {view_id}")
        factory = self.discovery.resolve(definition, view_definition.factory)
        context = PluginContext(app, definition, self)
        view = factory(context)
        app.active_plugin_view = ActivePluginView(definition, view_id, view_definition.label, view)
        callback = getattr(view, "on_enter", None)
        if callable(callback):
            callback(context)
        app.main_full_redraw = True

    def close_view(self, app: Any) -> None:
        active = getattr(app, "active_plugin_view", None)
        if active is None:
            return
        context = PluginContext(app, active.definition, self)
        callback = getattr(active.view, "on_leave", None)
        try:
            if callable(callback):
                callback(context)
        except Exception as exc:
            app.status = f"Plugin {active.definition.name} view cleanup failed: {exc}"
        finally:
            app.active_plugin_view = None
        app.main_full_redraw = True
        app.render_cache.clear()

    def draw_view(self, app: Any) -> bool:
        active = getattr(app, "active_plugin_view", None)
        if active is None:
            return False
        app.setup_colors()
        height, width = app.screen.getmaxyx()
        app.screen.erase()
        app.add(0, 0, f"{active.definition.name} | {active.label}"[:width], curses.A_BOLD)
        canvas = PluginCanvas(app, top=2, left=0, height=max(0, height - 4), width=width)
        context = PluginContext(app, active.definition, self)
        try:
            active.view.render(canvas, context)
        except Exception as exc:
            self._abort_view(app, active, exc)
            return False
        footer = "q/Esc: back"
        app.add(height - 2, 0, footer[:width].ljust(width), app.accent_attr())
        app.add(height - 1, 0, app.status[:width].ljust(width), curses.A_REVERSE)
        app.screen.refresh()
        app.main_full_redraw = False
        return True

    def handle_view_key(self, app: Any, code: int) -> bool:
        active = getattr(app, "active_plugin_view", None)
        if active is None:
            return False
        context = PluginContext(app, active.definition, self)
        callback = getattr(active.view, "handle_event", None)
        try:
            result = callback(UiEvent(code, ui_input_api.key_code_to_text(code)), context) if callable(callback) else None
        except Exception as exc:
            self._abort_view(app, active, exc)
            return True
        if result == "close" or (result is None and (code == 27 or ui_input_api.key_code_matches(code, "q"))):
            self.close_view(app)
        else:
            app.main_full_redraw = True
        return True

    def poll_view(self, app: Any) -> None:
        active = getattr(app, "active_plugin_view", None)
        if active is None:
            return
        callback = getattr(active.view, "on_tick", None)
        try:
            if callable(callback):
                callback(PluginContext(app, active.definition, self))
        except Exception as exc:
            self._abort_view(app, active, exc)

    def _abort_view(self, app: Any, active: ActivePluginView, exc: Exception) -> None:
        app.active_plugin_view = None
        app.status = f"Plugin {active.definition.name} view failed: {exc}"
        app.main_full_redraw = True
        app.render_cache.clear()

    def _definition_items(self, app: Any, definition: PluginDefinition) -> list[MenuItem]:
        result: list[MenuItem] = []
        for action in definition.actions:
            result.append(
                MenuItem(
                    action.label,
                    f"{action.tab_id} / {action.group}",
                    action.description,
                    self._preview(definition, action.preview, action.description),
                    self._handler(definition, action.handler, action.view),
                    confirm=action.confirm,
                    job_slot=action.job_slot,
                    tab_id=f"plugin:{definition.plugin_id}:{action.tab_id}",
                    tab_label=action.tab_label,
                )
            )
        return result

    def _preview(self, definition: PluginDefinition, reference: str, fallback: str) -> Any:
        if not reference:
            return lambda _app: fallback

        def preview(app: Any) -> str:
            callback = self.discovery.resolve(definition, reference)
            return str(callback(PluginContext(app, definition, self)))

        return preview

    def _handler(self, definition: PluginDefinition, reference: str, view_id: str) -> Any:
        def handler(app: Any) -> None:
            if view_id:
                self.open_view(app, definition, view_id)
                return
            callback = self.discovery.resolve(definition, reference)
            callback(PluginContext(app, definition, self))

        return handler


def board_profiles(config: dict[str, Any]) -> tuple[BoardProfile, ...]:
    result: list[BoardProfile] = []
    for raw in config.get("board_hosts", []):
        if not isinstance(raw, dict):
            continue
        board_id = str(raw.get("name") or "")
        if not board_id:
            continue
        result.append(
            BoardProfile(
                board_id=board_id,
                label=str(raw.get("label") or board_id),
                user=str(raw.get("user") or ""),
                host=str(raw.get("host") or ""),
                board_type=str(raw.get("type") or ""),
                values=MappingProxyType(deepcopy(raw)),
            )
        )
    return tuple(result)


def plugin_runtime(plugins_dir: Path) -> PluginRuntime:
    return PluginRuntime(plugins_dir)
