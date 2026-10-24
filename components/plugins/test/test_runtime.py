from __future__ import annotations

import curses
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from components.config.api.store import config_store

from components.board_types.api.base import BoardCapability
from components.product_types.api.base import ProductCapability, ProductDomain
from components.plugins.src.model import UiEvent, plugin_config
from components.plugins.src.runtime import (
    PluginCanvas,
    PluginCommands,
    PluginContext,
    PluginLogPanel,
    PluginRuntime,
    board_profiles,
    build_host_profiles,
    project_profiles,
)
from components.ui.src import menu
from components.ui.api import input as ui_input_api


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

def availability(context):
    return (bool(context.config.get('ready')), 'plugin is not ready')

def migrate_config(config):
    values = config['plugins']['diagnostics'].setdefault('config', {})
    if values.get('schema_version') == 1:
        return False
    values['schema_version'] = 1
    return True

class Contributor:
    def contribute_config(self, registrar):
        pass

def config_contributor():
    return Contributor()

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
            "active_board_host": "board-host-a-id",
            "active_board": "board-a-id",
            "active_remote": "build-a-id",
            "active_project": "gen5-id",
            "board_hosts": [
                {
                    "id": "board-host-a-id",
                    "name": "board-host-a",
                    "user": "root",
                    "host": "192.0.2.1",
                    "boards": [{
                        "id": "board-a-id",
                        "board_host_id": "board-host-a-id",
                        "name": "board-a",
                        "label": "Board A",
                        "type": "x5h",
                        "mac_address": "aa:bb:cc:dd:ee:ff",
                    }],
                },
                {
                    "id": "carla-id",
                    "name": "carla",
                    "user": "carla",
                    "host": "192.0.2.2",
                    "boards": [{
                        "id": "board-b-id",
                        "board_host_id": "carla-id",
                        "name": "board-b",
                        "label": "Board B",
                        "type": "x5h",
                    }],
                },
            ],
            "remotes": [
                {"id": "build-a-id", "name": "build-a", "label": "Build A", "user": "builder", "host": "198.51.100.2", "projects_dir": "/work"},
            ],
            "projects": [
                {
                    "id": "gen5-id",
                    "name": "gen5",
                    "label": "Gen5",
                    "product_type": "gen5_xen_android",
                    "project_dir": "product",
                    "moulin_manifest": "prod.yaml",
                    "docker_image": "gen5-builder",
                    "git_url": "git@example:gen5.git",
                    "git_ref": "main",
                    "targets": "doma",
                },
            ],
        }
        self.dependencies = SimpleNamespace(save_config=Mock())
        self.config_store = config_store(self.config, save=self.dependencies.save_config)
        self.active_plugin_view = None
        self.main_full_redraw = False
        self.render_cache = {}
        self.menu_dirty = False
        self.active_menu_tab = "configuration"
        self.status = ""
        self.workflow = Mock()
        self.workflow.run_commands.return_value = 0

    def command_workflow_service(self) -> Mock:
        return self.workflow

    def read_queued_text(self, _code: int) -> str:
        return "queued"


class PluginRuntimeTests(unittest.TestCase):
    def test_canvas_applies_requested_cursor_after_drawing(self) -> None:
        app = SimpleNamespace(set_cursor=Mock(), screen=Mock())
        canvas = PluginCanvas(app, top=2, left=3, height=10, width=20)

        canvas.cursor(4, 5)

        app.set_cursor.assert_not_called()
        app.screen.move.assert_not_called()

        canvas._apply_cursor()

        app.set_cursor.assert_called_once_with(True)
        app.screen.move.assert_called_once_with(6, 8)

    def test_plugin_log_panel_follows_and_scrolls_wrapped_output(self) -> None:
        class Canvas:
            def __init__(self) -> None:
                self.values: list[str] = []

            def box(self, _row, _column, _height, _width, title, **_kwargs) -> None:
                self.values.append(title)

            def text(self, _row, _column, value, **_kwargs) -> None:
                self.values.append(value)

        panel = PluginLogPanel()
        panel.expanded = True
        canvas = Canvas()
        lines = [f"line {index} with wrapped content" for index in range(8)]

        panel.draw(
            canvas,
            top=0,
            left=0,
            height=8,
            width=20,
            owner="lab / board-a",
            lines=lines,
            running=True,
        )

        self.assertTrue(any("follow" in value for value in canvas.values))
        self.assertTrue(panel.follow)

        handled = panel.handle_event(UiEvent(curses.KEY_UP, ""), lines)

        self.assertTrue(handled)
        self.assertFalse(panel.follow)

    def test_plugin_log_panel_accepts_russian_layout_hotkey(self) -> None:
        panel = PluginLogPanel()

        handled = panel.handle_event(
            UiEvent(ui_input_api.encode_text_key("а"), "а"),
            [],
        )

        self.assertTrue(handled)
        self.assertTrue(panel.expanded)

    def runtime(self, tmp: str) -> PluginRuntime:
        plugin = Path(tmp) / "plugins" / "diagnostics"
        plugin.mkdir(parents=True)
        (plugin / "plugin.yaml").write_text(PLUGIN_MANIFEST, encoding="utf-8")
        (plugin / "plugin.py").write_text(PLUGIN_MODULE, encoding="utf-8")
        return PluginRuntime(Path(tmp) / "plugins")

    def test_plugin_context_exposes_host_inline_editor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.runtime(tmp)
            app = FakeApp()
            context = PluginContext(app, runtime.definitions()[0], runtime)

            direct = context.inline_edit(UiEvent(ord("x"), "x"), "ab", 1)
            queued = context.inline_edit(UiEvent(-1), "ab", 1)

            self.assertEqual((direct.value, direct.cursor, direct.action), ("axb", 2, "edit"))
            self.assertEqual((queued.value, queued.cursor, queued.action), ("aqueuedb", 7, "edit"))

    def test_plugin_context_exposes_active_product_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.runtime(tmp)
            context = PluginContext(FakeApp(), runtime.definitions()[0], runtime)

            self.assertEqual(context.active_project_id, "gen5-id")
            self.assertEqual(context.active_build_host_id, "build-a-id")

    def test_plugin_context_runtime_state_is_shared_without_persisting_in_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.runtime(tmp)
            definition = runtime.definitions()[0]
            app = FakeApp()
            first = PluginContext(app, definition, runtime)
            second = PluginContext(app, definition, runtime)

            first.runtime_state["cached"] = {"value": 1}

            self.assertEqual(second.runtime_state["cached"], {"value": 1})
            self.assertNotIn("cached", first.config)

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
            self.assertEqual(plugin_config(app.config, "diagnostics")["handled"], ["board-a-id", "board-b-id"])

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

        self.assertEqual([board.board_id for board in boards], ["board-a-id", "board-b-id"])
        self.assertEqual(boards[0].remote, "root@192.0.2.1")
        self.assertEqual(boards[0].values["host"], "192.0.2.1")

    def test_set_enabled_persists_state_and_rebuilds_menu(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.runtime(tmp)
            app = FakeApp()
            definition = runtime.definitions()[0]
            app.active_menu_tab = "plugin:diagnostics:checks"

            runtime.set_enabled(app, definition, False)

            self.assertFalse(app.config["plugins"]["diagnostics"]["enabled"])
            app.dependencies.save_config.assert_called_once_with(app.config)
            self.assertTrue(app.menu_dirty)
            self.assertTrue(app.main_full_redraw)
            self.assertEqual(app.active_menu_tab, "")

            runtime.set_enabled(app, definition, True)

            self.assertEqual(app.active_menu_tab, "plugin:diagnostics:checks")

    def test_runtime_exposes_configured_plugin_config_contributors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.runtime(tmp)
            app = FakeApp()
            app.config["plugins"]["diagnostics"]["enabled"] = False

            contributors = runtime.config_contributors(app)

            self.assertEqual(len(contributors), 1)
            self.assertEqual(type(contributors[0]).__name__, "Contributor")

    def test_runtime_migrates_configured_plugins_once_during_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.runtime(tmp)
            app = FakeApp()

            self.assertTrue(runtime.migrate_loaded_config(app.config))
            self.assertEqual(plugin_config(app.config, "diagnostics")["schema_version"], 1)
            self.assertFalse(runtime.migrate_loaded_config(app.config))

    def test_build_hosts_and_projects_are_immutable_snapshots(self) -> None:
        app = FakeApp()

        hosts = build_host_profiles(app.config)
        projects = project_profiles(app.config)
        app.config["remotes"][0]["host"] = "changed"
        app.config["projects"][0]["targets"] = "doma domd"

        self.assertEqual(hosts[0].remote, "builder@198.51.100.2")
        self.assertEqual(hosts[0].projects_dir, "/work")
        self.assertEqual(projects[0].build_targets, ("doma",))

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

    def test_product_commands_use_selected_checkout_and_product_container(self) -> None:
        app = FakeApp()
        commands = PluginCommands(app)

        prepare = commands.prepare_product_command("build-a", "gen5")
        checkout = commands.checkout_product_command("build-a", "gen5")
        build = commands.product_build_command("build-a", "gen5", ["doma"])

        self.assertIn("git clone git@example:gen5.git product", prepare[-1])
        self.assertIsNotNone(checkout)
        self.assertIn("git checkout main", checkout[-1])
        self.assertIn("/work/product", build[-1])
        self.assertIn("docker run", build[-1])
        self.assertIn("gen5-builder", build[-1])
        self.assertIn("ninja doma", build[-1])

    def test_board_capabilities_come_from_board_type(self) -> None:
        commands = PluginCommands(FakeApp())

        self.assertEqual(
            commands.board_capabilities("board-a"),
            frozenset({BoardCapability.REBOOT, BoardCapability.REFLASH, BoardCapability.REFLASH_BOOTLOADERS}),
        )

    def test_board_operation_plan_binds_selected_product_and_board(self) -> None:
        app = FakeApp()
        app.dependencies = SimpleNamespace(
            app_dir=Path("/app"),
            default_moulin_manifest="product.yaml",
            flash_bootloaders_tool=Path("/app/flash.py"),
            xt_imager_tool=Path("/app/xt-imager.py"),
            remote_read_project_file=Mock(),
            manifest_cache={},
        )
        service = Mock()
        operation = SimpleNamespace(
            build_targets=("full_ufs.img.gz",),
            provision_commands=(("copy-artifacts",), ("stage-helper",)),
            execute_commands=(("ssh", "board", "flash"),),
        )
        service.board_operation_plan.return_value = operation

        with patch(
            "components.plugins.src.runtime.board_workflow_api.board_command_workflow_service",
            return_value=service,
        ):
            result = PluginCommands(app).board_operation_plan(
                "board-b",
                "build-a",
                "gen5",
                BoardCapability.REFLASH,
                build_params={"ENABLE_DOMA": "yes"},
            )

        self.assertIs(result, operation)
        config = service.board_operation_plan.call_args.args[0]
        self.assertEqual(config["active_board_host"], "carla-id")
        self.assertEqual(config["active_board"], "board-b-id")
        self.assertEqual(config["active_remote"], "build-a-id")
        self.assertEqual(config["active_project"], "gen5-id")
        self.assertEqual(service.board_operation_plan.call_args.args[1], BoardCapability.REFLASH)
        self.assertEqual(service.board_operation_plan.call_args.kwargs["build_params"], {"ENABLE_DOMA": "yes"})

    def test_product_capabilities_follow_effective_component_builders(self) -> None:
        app = FakeApp()
        app.config["projects"][0]["parameters"] = {"MODE": "saved"}
        app.dependencies = SimpleNamespace(
            app_dir=Path("/app"),
            default_moulin_manifest="product.yaml",
            remote_read_project_file=Mock(),
            manifest_cache={},
        )

        with (
            patch(
                "components.plugins.src.runtime.moulin_manifest_api.default_parameters_for_config",
                return_value={"MODE": "default", "OTHER": "value"},
            ) as defaults,
            patch(
                "components.plugins.src.runtime.moulin_manifest_api.component_builders_for_config",
                return_value=[
                    {"name": "domu", "builder_type": "yocto"},
                    {"name": "doma", "builder_type": "android"},
                ],
            ) as builders,
        ):
            commands = PluginCommands(app)
            capabilities = commands.product_capabilities("gen5", "build-a", build_params={"MODE": "call"})
            domains = commands.product_domains("gen5", "build-a", build_params={"MODE": "call"})

        self.assertEqual(capabilities, frozenset({ProductCapability.ANDROID_ADB}))
        self.assertEqual(domains, (ProductDomain("doma", "android"),))
        config = defaults.call_args.args[0]
        self.assertEqual(config["active_remote"], "build-a-id")
        self.assertEqual(config["active_project"], "gen5-id")
        self.assertEqual(builders.call_args.kwargs["build_params"], {"MODE": "call", "OTHER": "value"})

    def test_product_adb_resolver_uses_project_type_and_board_values(self) -> None:
        plan = PluginCommands(FakeApp()).product_adb_resolver("gen5", "board-a")

        self.assertIn("ip neigh show", plan.command)
        self.assertIn("aa:bb:cc:dd:ee:ff", plan.command)

    def test_product_adb_resolver_auto_detects_console_when_identity_is_missing(self) -> None:
        app = FakeApp()
        app.config["board_hosts"][0]["boards"][0]["mac_address"] = ""
        app.config["board_hosts"][0]["boards"][0]["board_ip"] = ""

        plan = PluginCommands(app).product_adb_resolver("gen5", "board-a")

        self.assertIn("ls -1 /dev/GEN5_CONSOLE*", plan.command)

    def test_capture_host_stream_reports_stdout_before_returning_result(self) -> None:
        lines: list[str] = []
        command = [
            sys.executable,
            "-c",
            "import sys; print('first', flush=True); print('problem', file=sys.stderr, flush=True)",
        ]

        with patch("components.plugins.src.runtime.remote_transport.ssh_command", return_value=command):
            result = PluginCommands(FakeApp()).capture_host_stream(
                "root@example.test",
                "ignored",
                lines.append,
            )

        self.assertEqual(lines, ["first"])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "first\n")
        self.assertEqual(result.stderr, "problem\n")

    def test_product_target_candidates_come_from_selected_project_manifest(self) -> None:
        app = FakeApp()
        app.config["projects"][0]["parameters"] = {"MODE": "saved"}
        app.dependencies = SimpleNamespace(
            app_dir=Path("/app"),
            default_moulin_manifest="product.yaml",
            remote_read_project_file=Mock(),
            manifest_cache={},
        )

        with (
            patch(
                "components.plugins.src.runtime.moulin_manifest_api.default_parameters_for_config",
                return_value={"MODE": "default", "OTHER": "value"},
            ),
            patch(
                "components.plugins.src.runtime.moulin_manifest_api.target_candidates_for_config",
                return_value=[
                    {"target": "doma", "source": "manifest", "desc": ""},
                    {"target": "full_ufs.img.gz", "source": "manifest", "desc": ""},
                ],
            ) as candidates,
        ):
            targets = PluginCommands(app).product_target_candidates(
                "gen5",
                "build-a",
                build_params={"MODE": "call"},
            )

        self.assertEqual(targets, ("doma", "full_ufs.img.gz"))
        config = candidates.call_args.args[0]
        self.assertEqual(config["active_remote"], "build-a-id")
        self.assertEqual(config["active_project"], "gen5-id")
        self.assertEqual(candidates.call_args.kwargs["build_params"], {"MODE": "call", "OTHER": "value"})

    def test_android_build_context_is_resolved_by_moulin_layer(self) -> None:
        app = FakeApp()
        app.dependencies = SimpleNamespace(
            app_dir=Path("/app"),
            default_moulin_manifest="product.yaml",
            remote_read_project_file=Mock(),
            manifest_cache={},
        )

        with (
            patch(
                "components.plugins.src.runtime.moulin_manifest_api.default_parameters_for_config",
                return_value={"DOMA_LUNCH_TARGET": "aosp_xenvm-userdebug"},
            ),
            patch(
                "components.plugins.src.runtime.moulin_manifest_api.component_builders_for_config",
                return_value=[
                    {"name": "doma_kernel", "builder_type": "bazel", "build_dir": "android_kernel"},
                    {"name": "doma", "builder_type": "android", "build_dir": "android"},
                ],
            ),
        ):
            context = PluginCommands(app).product_android_build_context("gen5", "build-a")

        self.assertEqual(context.component_name, "doma")
        self.assertEqual(context.build_dir, "android")
        self.assertEqual(context.setup_commands[-1], "lunch aosp_xenvm-userdebug")


if __name__ == "__main__":
    unittest.main()
