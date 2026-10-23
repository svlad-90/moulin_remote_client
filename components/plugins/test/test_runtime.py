from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from components.plugins.src.model import plugin_config
from components.plugins.src.runtime import PluginCommands, PluginRuntime, board_profiles
from components.ui.src import menu


PLUGIN_MANIFEST = """api_version: 1
id: diagnostics
name: Board diagnostics
settings:
  timeout:
    type: integer
    label: Timeout
    default: 10
tabs:
  - id: checks
    label: Checks
    actions:
      - id: run
        label: Run checks
        description: Check all configured boards.
        handler: run
        preview: preview
        job_slot: board
      - id: matrix
        label: Open matrix
        description: Show board state.
        view: matrix
views:
  - id: matrix
    label: Board matrix
    factory: create_matrix
"""

PLUGIN_MODULE = """def preview(context):
    return f'boards={len(context.boards)} timeout={context.config["timeout"]}'

def run(context):
    context.config['handled'] = [board.board_id for board in context.boards]

class Matrix:
    def on_enter(self, context):
        context.config['entered'] = True

    def render(self, ui, context):
        ui.text(0, 0, 'matrix')

    def handle_event(self, event, context):
        return 'close' if event.text == 'x' else None

    def on_leave(self, context):
        context.config['left'] = True

def create_matrix(context):
    return Matrix()
"""


class FakeApp:
    def __init__(self) -> None:
        self.config = {
            "plugins": {"diagnostics": {"enabled": True}},
            "active_board_host": "board-a",
            "board_hosts": [
                {"name": "board-a", "label": "Board A", "user": "root", "host": "192.0.2.1", "type": "x5h"},
                {"name": "board-b", "label": "Board B", "user": "carla", "host": "192.0.2.2", "type": "x5h"},
            ],
        }
        self.dependencies = SimpleNamespace(save_config=Mock())
        self.active_plugin_view = None
        self.main_full_redraw = False
        self.render_cache = {}
        self.menu_dirty = False
        self.status = ""
        self.workflow = Mock()
        self.workflow.run_commands.return_value = 0

    def command_workflow_service(self) -> Mock:
        return self.workflow


class PluginRuntimeTests(unittest.TestCase):
    def runtime(self, tmp: str) -> PluginRuntime:
        plugin = Path(tmp) / "plugins" / "diagnostics"
        plugin.mkdir(parents=True)
        (plugin / "plugin.yaml").write_text(PLUGIN_MANIFEST, encoding="utf-8")
        (plugin / "plugin.py").write_text(PLUGIN_MODULE, encoding="utf-8")
        return PluginRuntime(Path(tmp) / "plugins")

    def test_enabled_plugin_contributes_labeled_tab_and_runs_handler(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.runtime(tmp)
            app = FakeApp()

            items = runtime.build_items(app)

            self.assertEqual(menu.menu_tabs(items), ["plugin:diagnostics:checks"])
            self.assertEqual(menu.menu_tab_labels(items), {"plugin:diagnostics:checks": "Checks"})
            self.assertEqual(menu.item_job_slot(items[0]), "board")
            self.assertEqual(items[0].preview(app), "boards=2 timeout=10")
            items[0].handler(app)
            self.assertEqual(plugin_config(app.config, "diagnostics")["handled"], ["board-a", "board-b"])

    def test_plugin_view_uses_host_lifecycle_and_can_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.runtime(tmp)
            app = FakeApp()
            items = runtime.build_items(app)

            items[1].handler(app)

            values = plugin_config(app.config, "diagnostics")
            self.assertTrue(values["entered"])
            self.assertIsNotNone(app.active_plugin_view)
            runtime.handle_view_key(app, ord("x"))
            self.assertIsNone(app.active_plugin_view)
            self.assertTrue(values["left"])

    def test_board_profiles_are_snapshots_of_all_configured_boards(self) -> None:
        app = FakeApp()

        boards = board_profiles(app.config)
        app.config["board_hosts"][0]["host"] = "changed"

        self.assertEqual([board.board_id for board in boards], ["board-a", "board-b"])
        self.assertEqual(boards[0].remote, "root@192.0.2.1")
        self.assertEqual(boards[0].values["host"], "192.0.2.1")

    def test_set_enabled_persists_state_and_rebuilds_menu(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.runtime(tmp)
            app = FakeApp()
            definition = runtime.definitions()[0]

            runtime.set_enabled(app, definition, False)

            self.assertFalse(app.config["plugins"]["diagnostics"]["enabled"])
            app.dependencies.save_config.assert_called_once_with(app.config)
            self.assertTrue(app.menu_dirty)
            self.assertTrue(app.main_full_redraw)

    def test_run_boards_builds_one_logged_sequence_for_explicit_board_ids(self) -> None:
        app = FakeApp()

        result = PluginCommands(app).run_boards(
            "Check boards",
            {"board-a": ["uname -a"], "board-b": ["uptime"]},
        )

        self.assertEqual(result, 0)
        call = app.workflow.run_commands.call_args
        self.assertEqual(call.args[0:2], (app, "Check boards"))
        self.assertEqual(call.args[2][0][-2:], ["root@192.0.2.1", "uname -a"])
        self.assertEqual(call.args[2][1][-2:], ["carla@192.0.2.2", "uptime"])


if __name__ == "__main__":
    unittest.main()
