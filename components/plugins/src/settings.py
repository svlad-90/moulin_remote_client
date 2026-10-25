"""Host-rendered configuration screen for declarative plugin settings."""

from __future__ import annotations

import curses
from typing import Any

from components.plugins.src.model import PluginDefinition, PluginSetting, plugin_config
from components.ui.api import input as ui_input_api


def setting_value(config: dict[str, Any], definition: PluginDefinition, setting: PluginSetting) -> Any:
    return plugin_config(config, definition.plugin_id).get(setting.key, setting.default)


def setting_text(config: dict[str, Any], definition: PluginDefinition, setting: PluginSetting) -> str:
    value = setting_value(config, definition, setting)
    if setting.kind == "boolean":
        return "yes" if bool(value) else "no"
    return str(value)


def run_plugin_settings_screen(app: Any, definition: PluginDefinition) -> None:
    if not definition.settings:
        app.show_message(definition.name, ["This plugin has no configurable settings."])
        return
    index = 0
    app.screen.timeout(-1)
    while True:
        app.screen.erase()
        height, width = app.screen.getmaxyx()
        if height < 12 or width < 60:
            app.add(0, 0, "Terminal is too small. Need at least 60x12.", app.warn_attr())
            app.screen.refresh()
            ch = app.read_key()
            if ui_input_api.key_code_matches(ch, "q") or ch == 27:
                break
            continue
        app.add(0, 0, f"Plugin settings | {definition.name}"[:width], curses.A_BOLD)
        app.add(1, 0, "Up/Down: select | Enter/Space: edit | q/Esc: back"[:width], app.accent_attr())
        app.draw_box(3, 0, height - 5, width, "Configuration")
        visible_width = max(1, width - 4)
        visible_entries = max(1, height - 10)
        first_visible = min(
            max(0, index - visible_entries + 1),
            max(0, len(definition.settings) - visible_entries),
        )
        for row_offset, setting in enumerate(definition.settings[first_visible : first_visible + visible_entries]):
            setting_index = first_visible + row_offset
            text = f"{setting.label}: {setting_text(app.config, definition, setting)}"
            attr = app.selected_attr() if setting_index == index else 0
            app.add(4 + row_offset, 2, text[:visible_width].ljust(visible_width), attr)
        current = definition.settings[index]
        detail_row = height - 5
        app.draw_wrapped(detail_row, 2, visible_width, current.description or f"Plugin setting: {current.key}")
        app.add(height - 1, 0, app.status[:width].ljust(width), curses.A_REVERSE)
        app.screen.refresh()
        ch = app.read_key()
        if ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k"):
            index = (index - 1) % len(definition.settings)
        elif ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j") or ch == ord("\t"):
            index = (index + 1) % len(definition.settings)
        elif ch in (10, 13, ord(" ")):
            _edit_setting(app, definition, current)
        elif ui_input_api.key_code_matches(ch, "q") or ch == 27:
            break
    app.screen.timeout(250)
    app.status = f"Plugin settings closed: {definition.name}"
    app.main_full_redraw = True


def _edit_setting(app: Any, definition: PluginDefinition, setting: PluginSetting) -> None:
    values = plugin_config(app.config, definition.plugin_id)
    current = values.get(setting.key, setting.default)
    if setting.kind == "boolean":
        value: Any = not bool(current)
    elif setting.kind == "choice":
        choices = setting.choices
        try:
            current_index = choices.index(str(current))
        except ValueError:
            current_index = -1
        value = choices[(current_index + 1) % len(choices)]
    else:
        entered = app.prompt(setting.label, str(current))
        if app.prompt_cancelled:
            return
        if setting.kind == "integer":
            try:
                value = int(entered, 10)
            except ValueError:
                app.status = f"{setting.label}: expected an integer"
                return
            if setting.minimum is not None and value < setting.minimum:
                app.status = f"{setting.label}: minimum is {setting.minimum}"
                return
            if setting.maximum is not None and value > setting.maximum:
                app.status = f"{setting.label}: maximum is {setting.maximum}"
                return
        else:
            value = entered
    app.config_store.update_config(
        lambda config: plugin_config(config, definition.plugin_id).__setitem__(setting.key, value)
    )
    app.status = f"Updated plugin setting: {setting.label}"
