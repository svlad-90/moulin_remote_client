from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, call, patch

from components.config.api.entities import core_profile_contributor
from components.config.api.store import config_store
from components.plugins.src.discovery import PluginDiscovery
from plugins.cts_vts import commands, config_entities, downloads, model, plugin, runner_agent


def plugin_context(config: dict[str, object] | None = None, **values: object) -> SimpleNamespace:
    plugin_values = config if config is not None else {}
    build_hosts = tuple(values.get("build_hosts", ()))
    projects = tuple(values.get("projects", ()))
    boards = tuple(values.get("boards", ()))
    root: dict[str, object] = {
        "remotes": [
            {"id": str(host.host_id), "name": str(host.host_id)}
            for host in build_hosts
        ],
        "projects": [
            {"id": str(project.project_id), "name": str(project.project_id)}
            for project in projects
        ],
        "board_hosts": [{
            "id": "test-board-host",
            "name": "test-board-host",
            "boards": [
                {"id": str(board.board_id), "name": str(board.board_id)}
                for board in boards
            ],
        }],
        "plugins": {"cts-vts": {"enabled": True, "config": plugin_values}},
    }
    saved = Mock()

    def save(updated_root: dict[str, object]) -> None:
        updated = updated_root["plugins"]["cts-vts"]["config"]  # type: ignore[index]
        snapshot = deepcopy(updated)
        plugin_values.clear()
        plugin_values.update(snapshot)  # type: ignore[arg-type]
        saved()

    store = config_store(root, save=save)
    store.initialize([core_profile_contributor(), config_entities.config_contributor()])
    return SimpleNamespace(
        config=plugin_values,
        config_store=store,
        save_config=saved,
        **values,
    )


class CtsVtsModelTests(unittest.TestCase):
    def test_runtime_reads_do_not_migrate_configuration(self) -> None:
        config = {"runners": [{"name": "runner"}]}
        before = json.loads(json.dumps(config))

        model.state(config)
        model.records(config, "runners")

        self.assertEqual(config, before)

    def test_plugin_load_migration_resolves_external_names_to_ids(self) -> None:
        root = {
            "remotes": [{"id": "host-id", "name": "builder"}],
            "projects": [{"id": "project-id", "name": "gen5"}],
            "board_hosts": [{
                "id": "board-host-id",
                "name": "lab",
                "boards": [{"id": "board-id", "name": "carla.ih2"}],
            }],
            "plugins": {
                "cts-vts": {
                    "enabled": True,
                    "config": {
                        "board_profiles": [{
                            "name": "boards",
                            "devices": [{"board_id": "carla.ih2", "serial": ""}],
                        }],
                        "product_profiles": [{
                            "name": "product",
                            "build_host": "builder",
                            "project": "gen5",
                        }],
                    },
                }
            },
        }

        self.assertTrue(plugin.migrate_config(root))
        config = root["plugins"]["cts-vts"]["config"]

        self.assertEqual(config["board_profiles"][0]["devices"][0]["board_id"], "board-id")
        self.assertEqual(config["product_profiles"][0]["build_host"], "host-id")
        self.assertEqual(config["product_profiles"][0]["project"], "project-id")
        self.assertFalse(plugin.migrate_config(root))

    def test_name_based_run_references_migrate_to_ids(self) -> None:
        config = {
            "active_runner": "runner",
            "active_run": "run",
            "runners": [{"name": "runner"}],
            "board_profiles": [{"name": "boards"}],
            "test_profiles": [{"name": "tests"}],
            "product_profiles": [{"name": "product"}],
            "runs": [{
                "name": "run",
                "runner_profile": "runner",
                "board_profile": "boards",
                "test_profile": "tests",
                "product_profile": "product",
            }],
        }

        self.assertTrue(model.migrate_state(config))
        state = model.state(config)
        run = model.find(config, "runs", "run")

        self.assertEqual(state["active_runner"], model.find(config, "runners", "runner")["id"])
        self.assertEqual(state["active_run"], run["id"])
        self.assertEqual(run["runner_profile"], model.find(config, "runners", "runner")["id"])
        self.assertEqual(run["board_profile"], model.find(config, "board_profiles", "boards")["id"])
        self.assertEqual(run["test_profile"], model.find(config, "test_profiles", "tests")["id"])
        self.assertEqual(run["product_profile"], model.find(config, "product_profiles", "product")["id"])

    def test_runner_state_uses_a_profile_registry(self) -> None:
        config = {"runner": {"root": "obsolete"}}

        self.assertTrue(model.migrate_state(config))
        state = model.state(config)

        self.assertEqual(config["schema_version"], 6)
        self.assertNotIn("runner", state)
        self.assertEqual(state["runners"], [])
        self.assertEqual(state["active_runner"], "")

    def test_obsolete_manual_adb_resolver_is_removed(self) -> None:
        config = {
            "board_profiles": [
                {
                    "name": "lab",
                    "devices": [
                        {
                            "board_id": "board-a",
                            "serial": "",
                            "serial_resolver_command": "old-command",
                        }
                    ],
                }
            ]
        }

        self.assertTrue(model.migrate_state(config))

        self.assertNotIn("serial_resolver_command", config["board_profiles"][0]["devices"][0])

    def test_named_profiles_resolve_into_one_run(self) -> None:
        config: dict[str, object] = {}
        model.upsert(config, "runners", {"name": "runner-a"})
        model.upsert(config, "board_profiles", {"name": "lab", "devices": []})
        model.upsert(config, "test_profiles", {"name": "vts", "suites": ["vts"]})
        model.upsert(config, "product_profiles", {"name": "gen5"})
        run = {
            "name": "nightly",
            "runner_profile": "runner-a",
            "board_profile": "lab",
            "test_profile": "vts",
            "product_profile": "gen5",
        }

        runner, board, test, product = model.resolve_run(config, run)

        self.assertEqual(runner["name"], "runner-a")
        self.assertEqual((board["name"], test["name"], product["name"]), ("lab", "vts", "gen5"))

    def test_stale_board_hosts_are_removed_from_profiles(self) -> None:
        config = {"board_profiles": [{"name": "lab", "devices": [{"board_id": "keep"}, {"board_id": "gone"}]}]}

        removed = model.prune_board_references(config, {"keep"})

        self.assertEqual(removed, ["lab:gone"])
        self.assertEqual(config["board_profiles"][0]["devices"], [{"board_id": "keep"}])

    def test_suite_and_name_validation(self) -> None:
        self.assertEqual(model.parse_suites("VTS,cts,vts"), ["vts", "cts"])
        self.assertEqual(model.safe_name("nightly-17"), "nightly-17")
        with self.assertRaises(ValueError):
            model.safe_name("../nightly")
        with self.assertRaisesRegex(ValueError, "managed by the plugin"):
            model.validate_tradefed_args(["--shard-count", "4"])

    def test_referenced_profile_cannot_be_deleted_without_finding_dependant_run(self) -> None:
        config = {
            "runners": [{"name": "runner-a"}],
            "board_profiles": [{"name": "lab"}],
            "runs": [{"name": "nightly", "runner_profile": "runner-a", "board_profile": "lab"}],
        }
        model.migrate_state(config)

        self.assertEqual(model.dependent_runs(config, "runners", "runner-a"), ["nightly"])
        self.assertEqual(model.dependent_runs(config, "board_profiles", "lab"), ["nightly"])
        self.assertTrue(model.delete(config, "runs", "nightly"))
        self.assertTrue(model.delete(config, "board_profiles", "lab"))


class CtsVtsCommandTests(unittest.TestCase):
    def test_agent_and_plan_commands_keep_run_under_runner_root(self) -> None:
        deploy = commands.deploy_agent_command("/srv/runs", "nightly", b"print('ok')\n")
        plan = commands.write_plan_command("/srv/runs", "nightly", {"suites": ["vts"]})

        self.assertIn("/srv/runs/nightly/runner_agent.py", deploy)
        self.assertIn("/srv/runs/nightly/plan.json", plan)

    def test_agent_status_reports_unprepared_run_without_python_error(self) -> None:
        command = commands.agent_status_command("/srv/runs", "nightly")

        self.assertIn("if test -f /srv/runs/nightly/runner_agent.py", command)
        self.assertIn('"status": "not-prepared"', command)
        self.assertIn("python3 /srv/runs/nightly/runner_agent.py status", command)

    def test_vts_build_exports_prebuilt_kernel_inputs(self) -> None:
        command = commands.vts_build_command(
            "android",
            {
                "TARGET_PREBUILT_KERNEL": "image",
                "TARGET_PREBUILT_MODULES_DIR": "modules",
            },
            (". ./build/envsetup.sh", "lunch target"),
        )

        self.assertIn("TARGET_PREBUILT_KERNEL=image", command)
        self.assertIn("TARGET_PREBUILT_MODULES_DIR=modules", command)
        self.assertIn("lunch target", command)
        self.assertIn("make vts -j", command)

    def test_adb_inventory_command_requests_android_identity(self) -> None:
        command = commands.adb_inventory_command([{"board_id": "board-a", "serial": "192.0.2.10:5555"}])

        self.assertIn("python3 -c", command)
        self.assertIn("ro.serialno", command)
        self.assertIn("ro.build.id", command)
        self.assertIn("ro.build.version.incremental", command)
        self.assertIn("ro.build.fingerprint", command)

    def test_adb_probe_distinguishes_android_boot_from_readiness(self) -> None:
        command = commands.adb_probe_command([{"serial": "192.0.2.10:5555"}])

        self.assertIn("sys.boot_completed", command)
        self.assertIn("waiting-for-adb", command)
        self.assertIn("booting", command)
        self.assertIn("ready", command)


class CtsDownloadTests(unittest.TestCase):
    def test_extracts_only_arm_cts_archives(self) -> None:
        html = """
        <a href="https://example/android-cts-17.0_r2-linux_x86-arm.zip?download=1">CTS</a>
        <a href="https://example/android-cts-17.0_r2-linux_x86-x86.zip">x86</a>
        """

        self.assertEqual(
            downloads.parse_cts_downloads(html),
            {"17.0_r2": "https://example/android-cts-17.0_r2-linux_x86-arm.zip?download=1"},
        )

    def test_sorts_revisions_by_numeric_android_version_and_release(self) -> None:
        html = """
        <a href="https://example/android-cts-9.0_r20-linux_x86-arm.zip">9</a>
        <a href="https://example/android-cts-17_r1-linux_x86-arm.zip">17 r1</a>
        <a href="https://example/android-cts-16_r6-linux_x86-arm.zip">16</a>
        <a href="https://example/android-cts-16.1_r4-linux_x86-arm.zip">16.1</a>
        <a href="https://example/android-cts-17_r2-linux_x86-arm.zip">17 r2</a>
        """

        revisions = list(downloads.parse_cts_downloads(html))

        self.assertEqual(revisions, ["17_r2", "17_r1", "16.1_r4", "16_r6", "9.0_r20"])


class RunnerAgentTests(unittest.TestCase):
    def test_parses_latest_tradefed_session_progress(self) -> None:
        listing = """Session Pass Fail Modules Complete Result Directory Test Plan\n0 57 7 22 of 383 old vts\n3 60 7 31 of 383 new vts\n"""

        self.assertEqual(runner_agent.parse_result_listing(listing), (3, 31, 383))

    def test_invocation_shards_across_selected_serials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = {
                "suite_dirs": {"vts": tmp},
                "devices": [{"serial": "one"}, {"serial": "two"}],
                "test_profile": {"extra_args": ["--skip-device-info"]},
            }

            command = runner_agent.invocation(plan, runner_agent.initial_state(), "vts")

        self.assertEqual(command[-7:], ["--shard-count", "2", "-s", "one", "-s", "two", "--skip-device-info"])

    def test_adb_device_is_ready_only_after_android_boot_completed(self) -> None:
        result = SimpleNamespace(returncode=0, stdout="")
        device = SimpleNamespace(returncode=0, stdout="device\n")
        with patch(
            "plugins.cts_vts.runner_agent.subprocess.run",
            side_effect=[
                result,
                device,
                SimpleNamespace(returncode=0, stdout="0\n"),
                result,
                device,
                SimpleNamespace(returncode=0, stdout="1\n"),
            ],
        ):
            booting = runner_agent.adb_state("192.0.2.10:5555")
            ready = runner_agent.adb_state("192.0.2.10:5555")

        self.assertEqual(booting, "booting")
        self.assertEqual(ready, "ready")

    def test_structured_reflash_commands_run_without_a_shell(self) -> None:
        with patch("plugins.cts_vts.runner_agent.subprocess.run") as run:
            run.return_value.returncode = 0

            result = runner_agent.run_argv_hooks(
                [["ssh", "board", "flash", "{serial}"], ["verify", "{serial}"]],
                serial="192.0.2.10:5555",
                timeout_seconds=1800,
            )

        self.assertEqual(result, 0)
        self.assertEqual(
            run.call_args_list,
            [
                call(["ssh", "board", "flash", "192.0.2.10:5555"], timeout=1800, check=False),
                call(["verify", "192.0.2.10:5555"], timeout=1800, check=False),
            ],
        )

    def test_structured_reflash_timeout_fails_the_recovery_hook(self) -> None:
        with patch(
            "plugins.cts_vts.runner_agent.subprocess.run",
            side_effect=runner_agent.subprocess.TimeoutExpired(["flash"], 30),
        ):
            result = runner_agent.run_argv_hooks([["flash"]], serial="device", timeout_seconds=30)

        self.assertEqual(result, 124)

    def test_reboot_recovery_uses_the_board_operation(self) -> None:
        plan = {
            "devices": [
                {
                    "serial": "192.0.2.10:5555",
                    "reboot": {
                        "commands": [["ssh", "board", "restart"]],
                        "execute_timeout_seconds": 300,
                        "post_execute_delay_seconds": 0,
                    },
                }
            ],
            "test_profile": {"adb_loss_timeout_minutes": 1},
        }
        with (
            patch("plugins.cts_vts.runner_agent.run_argv_hooks", return_value=0) as run,
            patch("plugins.cts_vts.runner_agent.device_statuses", return_value={"192.0.2.10:5555": "ready"}),
            patch("plugins.cts_vts.runner_agent.time.sleep"),
        ):
            result = runner_agent.recover_devices(plan, "reboot")

        self.assertTrue(result)
        run.assert_called_once_with(
            [["ssh", "board", "restart"]],
            serial="192.0.2.10:5555",
            timeout_seconds=300,
        )

    def test_wait_for_devices_treats_missing_adb_and_android_boot_as_transient(self) -> None:
        plan = {
            "devices": [{"serial": "192.0.2.10:5555"}],
            "test_profile": {"adb_loss_timeout_minutes": 1},
        }
        with (
            patch(
                "plugins.cts_vts.runner_agent.device_statuses",
                side_effect=[
                    {"192.0.2.10:5555": "waiting-for-adb"},
                    {"192.0.2.10:5555": "booting"},
                    {"192.0.2.10:5555": "ready"},
                ],
            ),
            patch("plugins.cts_vts.runner_agent.time.monotonic", side_effect=[0, 1, 2]),
            patch("plugins.cts_vts.runner_agent.time.sleep") as sleep,
            patch("builtins.print"),
        ):
            result = runner_agent.wait_for_devices(plan)

        self.assertTrue(result)
        self.assertEqual(sleep.call_count, 2)


class CtsVtsDiscoveryTests(unittest.TestCase):
    def test_real_plugin_manifest_loads_with_relative_modules(self) -> None:
        plugins_dir = Path(__file__).resolve().parents[2]
        definition = next(item for item in PluginDiscovery(plugins_dir).discover() if item.plugin_id == "cts-vts")

        module = PluginDiscovery(plugins_dir).load_module(definition)
        actions = {action.action_id: action for action in definition.actions}

        self.assertFalse(definition.error)
        self.assertEqual(definition.actions[0].tab_label, "CTS&VTS")
        self.assertEqual(
            [action.action_id for action in definition.actions[:5]],
            ["runner", "boards", "products", "tests", "runs"],
        )
        self.assertEqual(actions["runner"].view, "runner-configuration")
        self.assertEqual(actions["boards"].view, "board-profile-configuration")
        self.assertEqual(actions["products"].view, "product-profile-configuration")
        self.assertEqual(actions["runs"].view, "test-run-configuration")
        self.assertEqual(actions["dashboard"].group, "Status")
        self.assertEqual(actions["dashboard"].label, "Test run status")
        self.assertNotIn("delete-profile", actions)
        self.assertEqual(
            definition.views["product-profile-configuration"].factory,
            "create_product_profile_configuration",
        )
        self.assertEqual(definition.views["available-boards"].factory, "create_available_boards")
        available_boards = next(action for action in definition.actions if action.action_id == "available-boards")
        self.assertEqual(available_boards.availability, "")
        self.assertTrue(callable(module.create_runner_configuration))
        self.assertTrue(callable(module.create_board_profile_configuration))
        self.assertTrue(callable(module.create_product_profile_configuration))
        self.assertTrue(callable(module.create_test_run_configuration))
        self.assertTrue(callable(module.create_available_boards))

    def test_command_availability_requires_runner_and_resolved_run(self) -> None:
        class Context:
            config: dict[str, object] = {
                "active_run": "nightly",
                "runs": [
                    {
                        "name": "nightly",
                        "runner_profile": "missing-runner",
                        "board_profile": "missing-boards",
                        "test_profile": "missing-tests",
                        "product_profile": "missing-product",
                    },
                ],
            }

        enabled, reason = plugin.configured_run_available(Context())

        self.assertFalse(enabled)
        self.assertIn("runner", reason)


class RunnerConfigurationViewTests(unittest.TestCase):
    def test_renders_build_host_style_single_panel_layout(self) -> None:
        class Canvas:
            width = 120
            height = 30

            def __init__(self) -> None:
                self.boxes: list[tuple[int, int, int, int, str]] = []
                self.lines: list[str] = []

            def text(self, _row: int, _column: int, text: str, **_kwargs: object) -> None:
                self.lines.append(text)

            def box(self, row: int, column: int, height: int, width: int, title: str, **_kwargs: object) -> None:
                self.boxes.append((row, column, height, width, title))

        config: dict[str, object] = {}
        model.upsert(
            config,
            "runners",
            {
                "name": "runner-a",
                "label": "Runner A",
                "user": "builder",
                "host": "runner.example",
                "workspace_dir": "/srv/test-runs",
            },
        )
        model.state(config)["active_runner"] = "runner-a"
        context = SimpleNamespace(config=config)
        canvas = Canvas()
        view = plugin.RunnerConfigurationView()

        view.render(canvas, context)

        self.assertEqual(canvas.boxes, [(2, 0, 27, 120, "Test runners")])
        self.assertIn("A Name              User@Host", canvas.lines)
        self.assertIn("PROFILE", canvas.lines)
        self.assertIn("SSH", canvas.lines)
        self.assertIn("REMOTE WORKSPACE", canvas.lines)

    def test_adds_named_runner_profile_and_marks_it_active(self) -> None:
        dialogs = SimpleNamespace(
            prompt=Mock(side_effect=["lab-runner", "Lab runner"]),
            prompt_cancelled=False,
            message=Mock(),
            confirm=Mock(),
        )
        context = plugin_context(dialogs=dialogs)
        view = plugin.RunnerConfigurationView()

        result = view.handle_event(SimpleNamespace(code=ord("a"), text="a"), context)

        self.assertEqual(result, "handled")
        runner = model.find(context.config, "runners", "lab-runner")
        self.assertEqual(model.state(context.config)["active_runner"], runner["id"])
        self.assertEqual(runner["label"], "Lab runner")
        self.assertEqual(view.focus, "fields")

    def test_field_selection_and_edit_cursor_match_host_screen(self) -> None:
        class Canvas:
            width = 120
            height = 30

            def __init__(self) -> None:
                self.lines: list[tuple[str, str]] = []
                self.cursors: list[tuple[int, int]] = []

            def text(self, _row: int, _column: int, text: str, *, style: str = "normal") -> None:
                self.lines.append((text, style))

            def box(self, *_args: object, **_kwargs: object) -> None:
                return None

            def cursor(self, row: int, column: int) -> None:
                self.cursors.append((row, column))

        config: dict[str, object] = {}
        model.upsert(
            config,
            "runners",
            {"name": "runner-a", "label": "Runner A", "user": "", "host": "", "workspace_dir": "/srv/runs"},
        )
        context = SimpleNamespace(config=config)
        view = plugin.RunnerConfigurationView()
        view.focus = "fields"
        view.selected = 2
        canvas = Canvas()

        view.render(canvas, context)

        selected = next(item for item in canvas.lines if item[0].startswith("SSH user:"))
        self.assertEqual(selected[1], "selected")
        self.assertEqual(canvas.cursors, [])
        self.assertEqual(set(view.field_hints), {key for key, _label in view.fields})
        self.assertIn(("SSH user for the remote test runner.", "accent"), canvas.lines)

        view.handle_event(SimpleNamespace(code=10, text=""), context)
        canvas = Canvas()
        view.render(canvas, context)

        editing = next(item for item in canvas.lines if item[0].startswith("SSH user:"))
        self.assertEqual(editing[1], "editing")
        self.assertTrue(editing[0].startswith("SSH user:           <not set>"))
        self.assertEqual(canvas.cursors, [(11, 22)])
        self.assertIn(("Enter: save | Esc: cancel | Left/Right/Home/End: move cursor", "accent"), canvas.lines)

    def test_selects_active_runner_from_profile_list(self) -> None:
        config: dict[str, object] = {}
        model.upsert(config, "runners", {"name": "runner-a"})
        model.upsert(config, "runners", {"name": "runner-b"})
        dialogs = SimpleNamespace(prompt=Mock(), prompt_cancelled=False, message=Mock(), confirm=Mock())
        context = plugin_context(config, dialogs=dialogs)
        view = plugin.RunnerConfigurationView()
        view.runner_index = 1

        view.handle_event(SimpleNamespace(code=ord("s"), text="s"), context)

        self.assertEqual(model.state(config)["active_runner"], model.find(config, "runners", "runner-b")["id"])
        context.save_config.assert_called_once_with()

    def test_edits_selected_field_and_saves_plugin_config(self) -> None:
        dialogs = SimpleNamespace(prompt=Mock(), prompt_cancelled=False, message=Mock())
        context = plugin_context(
            config={},
            dialogs=dialogs,
            inline_edit=Mock(
                side_effect=[
                    SimpleNamespace(action="edit", value="runner.example", cursor=14),
                    SimpleNamespace(action="save", value="runner.example", cursor=14),
                ],
            ),
        )
        model.upsert(
            context.config,
            "runners",
            {"name": "runner-a", "label": "Runner A", "user": "", "host": "", "workspace_dir": "runs"},
        )
        view = plugin.RunnerConfigurationView()
        view.selected = 3
        view.focus = "fields"

        view.handle_event(SimpleNamespace(code=10, text=""), context)
        view.handle_event(SimpleNamespace(code=ord("r"), text="r"), context)
        result = view.handle_event(SimpleNamespace(code=10, text=""), context)

        self.assertEqual(result, "handled")
        self.assertEqual(model.find(context.config, "runners", "runner-a")["host"], "runner.example")
        context.save_config.assert_called_once_with()

    def test_cancelled_inline_edit_does_not_change_value(self) -> None:
        config: dict[str, object] = {}
        model.upsert(
            config,
            "runners",
            {"name": "runner-a", "label": "Runner A", "user": "", "host": "old.example", "workspace_dir": "runs"},
        )
        dialogs = SimpleNamespace(prompt=Mock(), prompt_cancelled=False, message=Mock())
        context = plugin_context(
            config=config,
            dialogs=dialogs,
            inline_edit=Mock(return_value=SimpleNamespace(action="cancel", value="changed", cursor=7)),
        )
        view = plugin.RunnerConfigurationView()
        view.selected = 3
        view.focus = "fields"

        view.handle_event(SimpleNamespace(code=10, text=""), context)
        view.handle_event(SimpleNamespace(code=27, text=""), context)

        self.assertEqual(model.find(config, "runners", "runner-a")["host"], "old.example")
        context.save_config.assert_not_called()


class BoardProfileConfigurationViewTests(unittest.TestCase):
    @staticmethod
    def board(board_id: str = "board-a") -> SimpleNamespace:
        return SimpleNamespace(
            board_id=board_id,
            label="Board A",
            user="root",
            host="192.0.2.20",
            board_type="gen5_x5h",
            remote="root@192.0.2.20",
            values={},
        )

    def test_renders_profile_board_and_device_sections_with_field_hint(self) -> None:
        class Canvas:
            width = 120
            height = 34

            def __init__(self) -> None:
                self.lines: list[tuple[str, str]] = []
                self.boxes: list[str] = []

            def text(self, _row: int, _column: int, text: str, *, style: str = "normal") -> None:
                self.lines.append((text, style))

            def box(self, _row: int, _column: int, _height: int, _width: int, title: str) -> None:
                self.boxes.append(title)

            def cursor(self, _row: int, _column: int) -> None:
                return None

        config: dict[str, object] = {}
        model.upsert(
            config,
            "board_profiles",
            {
                "name": "lab",
                "devices": [
                    {
                        "board_id": "board-a",
                        "serial": "192.0.2.20:5555",
                    }
                ],
            },
        )
        context = SimpleNamespace(config=config, boards=(self.board(),))
        view = plugin.BoardProfileConfigurationView()
        view.focus = "fields"
        view.field_index = 1
        canvas = Canvas()

        view.render(canvas, context)

        texts = [text for text, _style in canvas.lines]
        self.assertEqual(canvas.boxes, ["Board profiles"])
        self.assertIn("PROFILE", texts)
        self.assertIn("BOARDS", texts)
        self.assertIn("DEVICE: board-a", texts)
        self.assertTrue(any(text.startswith("[x] board-a") for text in texts))
        self.assertIn((view.field_hints["serial"], "accent"), canvas.lines)

    def test_toggles_board_membership_with_adb_defaults(self) -> None:
        config: dict[str, object] = {}
        model.upsert(config, "board_profiles", {"name": "lab", "devices": []})
        context = plugin_context(config, boards=(self.board(),))
        view = plugin.BoardProfileConfigurationView()
        view.focus = "boards"

        view.handle_event(SimpleNamespace(code=10, text=""), context)

        profile = model.find(config, "board_profiles", "lab")
        self.assertEqual(
            profile["devices"],
            [
                {
                    "board_id": "board-a",
                    "serial": "",
                }
            ],
        )
        context.save_config.assert_called_once_with()
        self.assertEqual(view.focus, "fields")
        self.assertEqual(view.field_index, 1)

    def test_enter_configures_an_included_board_while_space_removes_it(self) -> None:
        config: dict[str, object] = {}
        device = {
            "board_id": "board-a",
            "serial": "static.example:5555",
        }
        model.upsert(config, "board_profiles", {"name": "lab", "devices": [device]})
        context = plugin_context(config, boards=(self.board(),))
        view = plugin.BoardProfileConfigurationView()
        view.focus = "boards"

        view.handle_event(SimpleNamespace(code=10, text=""), context)

        self.assertEqual(view.focus, "fields")
        self.assertEqual(view.field_index, 1)
        self.assertEqual(model.find(config, "board_profiles", "lab")["devices"], [device])

        view.focus = "boards"
        view.handle_event(SimpleNamespace(code=ord(" "), text=" "), context)

        self.assertEqual(model.find(config, "board_profiles", "lab")["devices"], [])

    def test_new_board_starts_without_a_guessed_adb_endpoint(self) -> None:
        config: dict[str, object] = {}
        model.upsert(config, "board_profiles", {"name": "lab", "devices": []})
        context = plugin_context(config, boards=(self.board(),))
        view = plugin.BoardProfileConfigurationView()
        view.focus = "boards"

        view.handle_event(SimpleNamespace(code=10, text=""), context)

        profile = model.find(config, "board_profiles", "lab")
        self.assertEqual(profile["devices"][0]["serial"], "")

    def test_uses_product_resolver_when_serial_override_is_empty(self) -> None:
        commands = SimpleNamespace(
            product_adb_resolver=Mock(return_value=SimpleNamespace(command="resolve-domd-adb", timeout_seconds=45)),
            capture_host=Mock(
                return_value=SimpleNamespace(returncode=0, stdout="diagnostic output\n10.13.64.232:5555\n", stderr="")
            )
        )
        context = SimpleNamespace(boards=(self.board(),), commands=commands)

        devices = plugin._resolve_adb_devices(
            context,
            [{"board_id": "board-a", "serial": ""}],
            {"project": "project-a"},
        )

        self.assertEqual(devices[0]["serial"], "10.13.64.232:5555")
        commands.product_adb_resolver.assert_called_once_with("project-a", "board-a")
        commands.capture_host.assert_called_once_with("root@192.0.2.20", "resolve-domd-adb", timeout=45)

    def test_probe_streams_resolver_progress(self) -> None:
        statuses: list[dict[str, object]] = []

        def capture_host_stream(_remote, _command, on_stdout_line, *, timeout):
            self.assertEqual(timeout, 45)
            on_stdout_line('__MRC_BOARD_LOG__{"message": "send: enter DomD console"}')
            on_stdout_line('__MRC_BOARD_PROGRESS__{"board": true, "serial": true}')
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    '__MRC_BOARD_STATUS__{"adb": true, "adb_serial": "10.13.64.232:5555"}\n'
                    "10.13.64.232:5555\n"
                ),
                stderr="",
            )

        commands = SimpleNamespace(
            product_adb_resolver=Mock(
                return_value=SimpleNamespace(command="resolve-domd-adb", timeout_seconds=45)
            ),
            capture_host_stream=capture_host_stream,
        )
        context = SimpleNamespace(boards=(self.board(),), commands=commands)

        device, probe, error = plugin._probe_adb_device(
            context,
            {"board_id": "board-a", "serial": ""},
            {"project": "project-a"},
            statuses.append,
        )

        self.assertEqual(
            statuses,
            [
                {"_log": "send: enter DomD console"},
                {"board": True, "serial": True},
            ],
        )
        self.assertEqual(device["serial"], "10.13.64.232:5555")
        self.assertEqual(probe["adb"], True)
        self.assertEqual(error, "")

    def test_static_adb_serial_override_bypasses_product_resolver(self) -> None:
        commands = SimpleNamespace(capture_host=Mock(), product_adb_resolver=Mock())
        context = SimpleNamespace(boards=(self.board(),), commands=commands)

        devices = plugin._resolve_adb_devices(
            context,
            [{"board_id": "board-a", "serial": "static.example:5555"}],
            {"project": "project-a"},
        )

        self.assertEqual(devices[0]["serial"], "static.example:5555")
        commands.capture_host.assert_not_called()
        commands.product_adb_resolver.assert_not_called()

    def test_reports_missing_product_resolver(self) -> None:
        context = SimpleNamespace(
            boards=(self.board(),),
            commands=SimpleNamespace(
                capture_host=Mock(),
                product_adb_resolver=Mock(side_effect=ValueError("product resolver unavailable")),
            ),
        )

        with self.assertRaisesRegex(RuntimeError, "product resolver unavailable"):
            plugin._resolve_adb_devices(
                context,
                [{"board_id": "board-a", "serial": ""}],
                {"project": "project-a"},
            )

    def test_edits_selected_board_device_field_inline(self) -> None:
        config: dict[str, object] = {}
        model.upsert(
            config,
            "board_profiles",
            {
                "name": "lab",
                "devices": [
                    {
                        "board_id": "board-a",
                        "serial": "old:5555",
                    }
                ],
            },
        )
        context = plugin_context(
            config=config,
            boards=(self.board(),),
            dialogs=SimpleNamespace(message=Mock()),
            inline_edit=Mock(
                side_effect=[
                    SimpleNamespace(action="edit", value="new:5555", cursor=8),
                    SimpleNamespace(action="save", value="new:5555", cursor=8),
                ]
            ),
        )
        view = plugin.BoardProfileConfigurationView()
        view.focus = "fields"
        view.field_index = 1

        view.handle_event(SimpleNamespace(code=10, text=""), context)
        view.handle_event(SimpleNamespace(code=ord("n"), text="n"), context)
        view.handle_event(SimpleNamespace(code=10, text=""), context)

        profile = model.find(config, "board_profiles", "lab")
        self.assertEqual(profile["devices"][0]["serial"], "new:5555")
        context.save_config.assert_called_once_with()

    def test_enter_does_not_rewrite_missing_board_references(self) -> None:
        config: dict[str, object] = {}
        model.upsert(
            config,
            "board_profiles",
            {"name": "lab", "devices": [{"board_id": "board-a"}, {"board_id": "gone"}]},
        )
        context = plugin_context(
            config=config,
            boards=(self.board(),),
            dialogs=SimpleNamespace(message=Mock()),
        )

        plugin.BoardProfileConfigurationView().on_enter(context)

        profile = model.find(config, "board_profiles", "lab")
        self.assertEqual(profile["devices"], [{"board_id": "board-a"}, {"board_id": "gone"}])
        context.save_config.assert_not_called()
        context.dialogs.message.assert_not_called()


class TestProfileConfigurationViewTests(unittest.TestCase):
    @staticmethod
    def config() -> dict[str, object]:
        config: dict[str, object] = {
            "test_profiles": [
                {
                    "name": "compatibility",
                    "suites": ["vts"],
                    "cts_revision": "",
                    "cts_url": "",
                    "extra_args": ["--skip-device-info"],
                    "skipped_modules": ["VtsBrokenModule"],
                    "adb_loss_timeout_minutes": 5,
                    "no_progress_runs": 3,
                    "max_reboots": 2,
                    "max_reflashes": 1,
                    "max_skip_cycles": 1,
                }
            ]
        }
        model.migrate_state(config)
        return config

    def test_renders_profile_registry_sections_and_field_hint(self) -> None:
        class Canvas:
            width = 120
            height = 40

            def __init__(self) -> None:
                self.lines: list[tuple[str, str]] = []
                self.boxes: list[str] = []

            def text(self, _row: int, _column: int, text: str, *, style: str = "normal") -> None:
                self.lines.append((text, style))

            def box(self, _row: int, _column: int, _height: int, _width: int, title: str) -> None:
                self.boxes.append(title)

            def cursor(self, _row: int, _column: int) -> None:
                return None

        context = SimpleNamespace(config=self.config())
        view = plugin.TestProfileConfigurationView()
        view.focus = "fields"
        view.selected = 3
        canvas = Canvas()

        view.render(canvas, context)

        texts = [text for text, _style in canvas.lines]
        self.assertEqual(canvas.boxes, ["Test profiles"])
        self.assertIn("PROFILE", texts)
        self.assertIn("SUITES", texts)
        self.assertIn("TRADEFED", texts)
        self.assertIn("RECOVERY", texts)
        self.assertTrue(any("compatibility" in text and "vts" in text for text in texts))
        self.assertIn((view.field_hints["extra_args"], "accent"), canvas.lines)

    def test_recovery_fields_describe_each_escalation_threshold(self) -> None:
        view = plugin.TestProfileConfigurationView()

        labels = dict(view.fields)
        self.assertEqual(labels["adb_loss_timeout_minutes"], "ADB loss timeout, minutes")
        self.assertEqual(labels["no_progress_runs"], "Maximum runs before reboot")
        self.assertEqual(labels["max_reboots"], "Maximum reboots before reflash")
        self.assertEqual(labels["max_reflashes"], "Maximum reflashes before module skip")
        self.assertEqual(labels["max_skip_cycles"], "Maximum module skips before failure")
        self.assertIn("Android boot completion", view.field_hints["adb_loss_timeout_minutes"])
        self.assertIn("without additional completed modules", view.field_hints["no_progress_runs"])
        self.assertIn("recovery escalates", view.field_hints["max_reboots"])
        self.assertIn("automatically excluded", view.field_hints["max_reflashes"])
        self.assertIn("stops with an error", view.field_hints["max_skip_cycles"])

    def test_suite_and_cts_revision_use_selectors(self) -> None:
        config = self.config()
        context = plugin_context(
            config=config,
            dialogs=SimpleNamespace(message=Mock()),
        )
        view = plugin.TestProfileConfigurationView()
        view.focus = "fields"

        view.selected = 1
        view.handle_event(SimpleNamespace(code=10, text=""), context)
        self.assertEqual(view.selector_choices, ["vts", "cts", "cts,vts"])
        view.handle_event(SimpleNamespace(code=plugin.curses.KEY_DOWN, text=""), context)
        view.handle_event(SimpleNamespace(code=10, text=""), context)

        with patch(
            "plugins.cts_vts.plugin.downloads.fetch_cts_downloads",
            return_value={"17_r1": "https://example.test/cts.zip"},
        ):
            view.selected = 2
            view.handle_event(SimpleNamespace(code=10, text=""), context)
        self.assertEqual(view.selector_choices, ["17_r1"])
        view.handle_event(SimpleNamespace(code=10, text=""), context)

        profile = model.find(config, "test_profiles", "compatibility")
        self.assertEqual(profile["suites"], ["cts"])
        self.assertEqual(profile["cts_revision"], "17_r1")
        self.assertEqual(profile["cts_url"], "https://example.test/cts.zip")
        self.assertEqual(context.save_config.call_count, 2)

    def test_adds_profile_with_recovery_defaults(self) -> None:
        context = plugin_context(
            config={},
            dialogs=SimpleNamespace(
                prompt=Mock(return_value="smoke"),
                prompt_cancelled=False,
                message=Mock(),
            ),
        )
        view = plugin.TestProfileConfigurationView()

        view._add_profile(context)

        profile = model.find(context.config, "test_profiles", "smoke")
        self.assertEqual(profile["suites"], ["vts"])
        self.assertEqual(profile["adb_loss_timeout_minutes"], 5)
        self.assertEqual(profile["no_progress_runs"], 3)
        self.assertEqual(profile["max_reboots"], 2)
        self.assertEqual(profile["max_reflashes"], 1)
        self.assertEqual(profile["max_skip_cycles"], 1)
        self.assertEqual(view.focus, "fields")
        context.save_config.assert_called_once_with()

    def test_renaming_profile_updates_test_runs(self) -> None:
        config = self.config()
        profile = model.find(config, "test_profiles", "compatibility")
        config["runs"] = [{"id": "run-a", "name": "nightly", "test_profile": profile["id"]}]
        context = plugin_context(
            config=config,
            dialogs=SimpleNamespace(message=Mock()),
        )
        view = plugin.TestProfileConfigurationView()
        view.editing_key = "name"
        view.editing_value = "compatibility-next"

        view._apply_edited_value(context)

        self.assertEqual(model.find(config, "test_profiles", "compatibility-next")["name"], "compatibility-next")
        renamed = model.find(config, "test_profiles", "compatibility-next")
        self.assertEqual(model.find(config, "runs", "nightly")["test_profile"], renamed["id"])
        context.save_config.assert_called_once_with()


class ProductProfileConfigurationViewTests(unittest.TestCase):
    @staticmethod
    def hosts() -> tuple[SimpleNamespace, ...]:
        return (
            SimpleNamespace(host_id="build-a"),
            SimpleNamespace(host_id="build-b"),
        )

    @staticmethod
    def projects() -> tuple[SimpleNamespace, ...]:
        return (
            SimpleNamespace(project_id="project-a", build_targets=("doma",)),
            SimpleNamespace(project_id="project-b", build_targets=("doma", "doma_kernel")),
        )

    @staticmethod
    def config() -> dict[str, object]:
        config: dict[str, object] = {
            "product_profiles": [
                {
                    "name": "gen5",
                    "build_host": "build-a",
                    "project": "project-a",
                }
            ]
        }
        model.migrate_state(config)
        return config

    def test_renders_profile_registry_and_field_hint(self) -> None:
        class Canvas:
            width = 120
            height = 32

            def __init__(self) -> None:
                self.lines: list[tuple[str, str]] = []
                self.boxes: list[str] = []

            def text(self, _row: int, _column: int, text: str, *, style: str = "normal") -> None:
                self.lines.append((text, style))

            def box(self, _row: int, _column: int, _height: int, _width: int, title: str) -> None:
                self.boxes.append(title)

            def cursor(self, _row: int, _column: int) -> None:
                return None

        context = SimpleNamespace(
            config=self.config(),
            build_hosts=self.hosts(),
            projects=self.projects(),
        )
        view = plugin.ProductProfileConfigurationView()
        view.focus = "fields"
        view.selected = 2
        canvas = Canvas()

        view.render(canvas, context)

        texts = [text for text, _style in canvas.lines]
        self.assertEqual(canvas.boxes, ["Product profiles"])
        self.assertIn("PROFILE", texts)
        self.assertIn("PRODUCT SOURCE", texts)
        self.assertNotIn("BUILD AND ANDROID", texts)
        self.assertTrue(any("gen5" in text and "build-a" in text and "project-a" in text for text in texts))
        self.assertIn((view.field_hints["project"], "accent"), canvas.lines)

        view.handle_event(SimpleNamespace(code=10, text=""), context)
        selector_canvas = Canvas()
        view.render(selector_canvas, context)

        self.assertEqual(selector_canvas.boxes, ["Project"])
        self.assertIn(("Select project", "accent"), selector_canvas.lines)
        self.assertTrue(any("project-a" in text for text, _style in selector_canvas.lines))

    def test_submenus_select_build_host_and_project(self) -> None:
        config = self.config()
        context = plugin_context(
            config=config,
            build_hosts=self.hosts(),
            projects=self.projects(),
            dialogs=SimpleNamespace(message=Mock()),
        )
        view = plugin.ProductProfileConfigurationView()
        view.focus = "fields"

        view.selected = 1
        view.handle_event(SimpleNamespace(code=10, text=""), context)
        self.assertEqual(view.selector_key, "build_host")
        view.handle_event(SimpleNamespace(code=plugin.curses.KEY_DOWN, text=""), context)
        view.handle_event(SimpleNamespace(code=10, text=""), context)
        view.selected = 2
        view.handle_event(SimpleNamespace(code=10, text=""), context)
        self.assertEqual(view.selector_key, "project")
        view.handle_event(SimpleNamespace(code=plugin.curses.KEY_DOWN, text=""), context)
        view.handle_event(SimpleNamespace(code=10, text=""), context)

        profile = model.find(config, "product_profiles", "gen5")
        self.assertEqual(profile["build_host"], "build-b")
        self.assertEqual(profile["project"], "project-b")
        self.assertNotIn("build_targets", profile)
        self.assertEqual(context.save_config.call_count, 2)

    def test_new_profile_references_active_project(self) -> None:
        config: dict[str, object] = {}
        context = plugin_context(
            config=config,
            active_build_host_id="build-b",
            active_project_id="project-b",
            build_hosts=self.hosts(),
            projects=self.projects(),
            dialogs=SimpleNamespace(
                prompt=Mock(return_value="product"),
                prompt_cancelled=False,
                message=Mock(),
            ),
        )
        view = plugin.ProductProfileConfigurationView()

        view._add_profile(context)

        profile = model.find(config, "product_profiles", "product")
        self.assertEqual(profile["build_host"], "build-b")
        self.assertEqual(profile["project"], "project-b")
        self.assertEqual(set(profile), {"id", "name", "build_host", "project"})
        context.save_config.assert_called_once_with()

    def test_renaming_profile_updates_test_runs(self) -> None:
        config = self.config()
        profile = model.find(config, "product_profiles", "gen5")
        config["runs"] = [{"id": "run-a", "name": "nightly", "product_profile": profile["id"]}]
        context = plugin_context(
            config=config,
            dialogs=SimpleNamespace(message=Mock()),
        )
        view = plugin.ProductProfileConfigurationView()
        view.editing_key = "name"
        view.editing_value = "gen5-next"

        view._apply_edited_value(context)

        self.assertEqual(model.find(config, "product_profiles", "gen5-next")["name"], "gen5-next")
        renamed = model.find(config, "product_profiles", "gen5-next")
        self.assertEqual(model.find(config, "runs", "nightly")["product_profile"], renamed["id"])
        context.save_config.assert_called_once_with()


class TestRunConfigurationViewTests(unittest.TestCase):
    @staticmethod
    def config() -> dict[str, object]:
        config: dict[str, object] = {
            "active_runner": "runner-a",
            "active_run": "nightly",
            "runners": [{"name": "runner-a"}, {"name": "runner-b"}],
            "board_profiles": [{"name": "boards-a"}, {"name": "boards-b"}],
            "product_profiles": [{"name": "product-a"}, {"name": "product-b"}],
            "test_profiles": [{"name": "test-a"}, {"name": "test-b"}],
            "runs": [
                {
                    "name": "nightly",
                    "runner_profile": "runner-a",
                    "board_profile": "boards-a",
                    "product_profile": "product-a",
                    "test_profile": "test-a",
                }
            ],
        }
        model.migrate_state(config)
        return config

    def test_renders_run_registry_and_active_run(self) -> None:
        class Canvas:
            width = 120
            height = 28

            def __init__(self) -> None:
                self.lines: list[tuple[str, str]] = []
                self.boxes: list[str] = []

            def text(self, _row: int, _column: int, text: str, *, style: str = "normal") -> None:
                self.lines.append((text, style))

            def box(self, _row: int, _column: int, _height: int, _width: int, title: str) -> None:
                self.boxes.append(title)

            def cursor(self, _row: int, _column: int) -> None:
                return None

        context = SimpleNamespace(config=self.config())
        view = plugin.TestRunConfigurationView()
        view.on_enter(context)
        canvas = Canvas()

        view.render(canvas, context)

        texts = [text for text, _style in canvas.lines]
        self.assertEqual(canvas.boxes, ["Test runs"])
        self.assertIn("Active: nightly", texts)
        self.assertIn("RUN", texts)
        self.assertIn("CONFIGURATION", texts)
        self.assertTrue(
            any(
                "nightly" in text
                and "runner-a" in text
                and "boards-a" in text
                and "product-a" in text
                and "test-a" in text
                for text in texts
            )
        )

    def test_profile_fields_use_selectors(self) -> None:
        config = self.config()
        context = plugin_context(
            config=config,
            dialogs=SimpleNamespace(message=Mock()),
        )
        view = plugin.TestRunConfigurationView()
        view.focus = "fields"

        for selected, key in enumerate(("runner_profile", "board_profile", "product_profile", "test_profile"), start=1):
            view.selected = selected
            view.handle_event(SimpleNamespace(code=10, text=""), context)
            self.assertEqual(view.selector_key, key)
            view.handle_event(SimpleNamespace(code=plugin.curses.KEY_DOWN, text=""), context)
            view.handle_event(SimpleNamespace(code=10, text=""), context)

        run = model.find(config, "runs", "nightly")
        self.assertEqual(run["runner_profile"], model.find(config, "runners", "runner-b")["id"])
        self.assertEqual(run["board_profile"], model.find(config, "board_profiles", "boards-b")["id"])
        self.assertEqual(run["product_profile"], model.find(config, "product_profiles", "product-b")["id"])
        self.assertEqual(run["test_profile"], model.find(config, "test_profiles", "test-b")["id"])
        self.assertEqual(context.save_config.call_count, 4)

    def test_adds_run_with_active_runner_and_first_profiles(self) -> None:
        config = self.config()
        config["runs"] = []
        config["active_run"] = ""
        context = plugin_context(
            config=config,
            dialogs=SimpleNamespace(
                prompt=Mock(return_value="smoke"),
                prompt_cancelled=False,
                message=Mock(),
            ),
        )
        view = plugin.TestRunConfigurationView()

        view._add_run(context)

        run = model.find(config, "runs", "smoke")
        self.assertEqual(run["name"], "smoke")
        self.assertEqual(run["runner_profile"], model.find(config, "runners", "runner-a")["id"])
        self.assertEqual(run["board_profile"], model.find(config, "board_profiles", "boards-a")["id"])
        self.assertEqual(run["product_profile"], model.find(config, "product_profiles", "product-a")["id"])
        self.assertEqual(run["test_profile"], model.find(config, "test_profiles", "test-a")["id"])
        self.assertEqual(model.state(config)["active_run"], run["id"])
        self.assertEqual(view.focus, "fields")
        context.save_config.assert_called_once_with()

    def test_renames_active_run(self) -> None:
        config = self.config()
        context = plugin_context(
            config=config,
            dialogs=SimpleNamespace(message=Mock()),
        )
        view = plugin.TestRunConfigurationView()
        view.editing_key = "name"
        view.editing_value = "nightly-next"

        view._apply_edited_value(context)

        self.assertIsNotNone(model.find(config, "runs", "nightly-next"))
        self.assertEqual(model.state(config)["active_run"], model.find(config, "runs", "nightly-next")["id"])
        context.save_config.assert_called_once_with()


class DashboardViewTests(unittest.TestCase):
    @staticmethod
    def config(serial: str = "") -> dict[str, object]:
        return {
            "active_run": "run-1",
            "runners": [
                {
                    "name": "runner-a",
                    "user": "runner",
                    "host": "192.0.2.10",
                    "workspace_dir": "/srv/runs",
                }
            ],
            "board_profiles": [
                {"name": "lab", "devices": [{"board_id": "board-a", "serial": serial}]}
            ],
            "test_profiles": [{"name": "cts", "suites": ["cts"]}],
            "product_profiles": [{"name": "product-a"}],
            "runs": [
                {
                    "name": "run-1",
                    "runner_profile": "runner-a",
                    "board_profile": "lab",
                    "test_profile": "cts",
                    "product_profile": "product-a",
                }
            ],
        }

    @staticmethod
    def canvas() -> Any:
        class Canvas:
            width = 120
            height = 36

            def __init__(self) -> None:
                self.lines: list[str] = []

            def text(self, _row: int, _column: int, value: str, **_kwargs: Any) -> None:
                self.lines.append(value)

            def wrapped_text(self, _row: int, _column: int, _width: int, value: str, **_kwargs: Any) -> None:
                self.lines.append(value)

        return Canvas()

    def test_unprepared_run_is_structured_and_skips_empty_adb_serial(self) -> None:
        capture = Mock(
            return_value=SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"status": "not-prepared"}),
                stderr="",
            )
        )
        context = SimpleNamespace(config=self.config(), commands=SimpleNamespace(capture_host=capture))
        view = plugin.DashboardView()

        view.refresh(context)
        canvas = self.canvas()
        view.render(canvas, context)

        self.assertEqual(capture.call_count, 1)
        self.assertIn("if test -f /srv/runs/run-1/runner_agent.py", capture.call_args.args[1])
        self.assertIn("State: not prepared", canvas.lines)
        self.assertIn("Next action: Prepare test run", canvas.lines)
        self.assertIn("Boards: lab (1)", canvas.lines)
        self.assertTrue(any("ADB serial not resolved for: board-a" in line for line in canvas.lines))
        self.assertFalse(any("can't open file" in line for line in canvas.lines))
        self.assertNotIn("q/Esc: back", canvas.lines)

    def test_enter_starts_status_refresh_without_blocking_the_ui(self) -> None:
        capture = Mock(
            side_effect=[
                SimpleNamespace(returncode=0, stdout=json.dumps({"status": "running"}), stderr=""),
                SimpleNamespace(returncode=0, stdout=json.dumps({"192.0.2.20:5555": True}), stderr=""),
            ]
        )
        context = SimpleNamespace(
            config=self.config("192.0.2.20:5555"),
            commands=SimpleNamespace(capture_host=capture),
            request_redraw=Mock(),
        )
        view = plugin.DashboardView()

        with patch.object(plugin.threading, "Thread") as thread_class:
            thread = thread_class.return_value
            view.on_enter(context)

            capture.assert_not_called()
            thread.start.assert_called_once_with()
            self.assertTrue(view.refreshing)
            worker = thread_class.call_args.kwargs["target"]
            worker()

        self.assertTrue(view.refreshing)
        view.on_tick(context)
        self.assertFalse(view.refreshing)
        self.assertEqual(view.device_statuses, {"192.0.2.20:5555": "ready"})
        self.assertGreaterEqual(context.request_redraw.call_count, 2)

    def test_loading_status_is_rendered_while_refresh_runs(self) -> None:
        context = SimpleNamespace(config=self.config("192.0.2.20:5555"))
        view = plugin.DashboardView()
        view.refreshing = True
        canvas = self.canvas()

        view.render(canvas, context)

        self.assertIn("State: loading", canvas.lines)
        self.assertIn("Checking runner and ADB status...", canvas.lines)

    def test_waiting_for_adb_is_rechecked_without_reporting_failure(self) -> None:
        context = SimpleNamespace(config=self.config("192.0.2.20:5555"), request_redraw=Mock())
        view = plugin.DashboardView()
        view.refreshing = True
        view._results.put(({}, {"192.0.2.20:5555": "waiting-for-adb"}, [], ""))

        with patch.object(plugin.time, "monotonic", side_effect=[100, 100]):
            view.on_tick(context)

        self.assertEqual(view.device_statuses, {"192.0.2.20:5555": "waiting-for-adb"})
        self.assertEqual(view.error, "")
        self.assertEqual(view._next_refresh_at, 105)
        canvas = self.canvas()
        view.render(canvas, context)
        self.assertIn("192.0.2.20:5555: waiting for ADB", canvas.lines)

    def test_waiting_for_adb_becomes_unavailable_after_timeout(self) -> None:
        context = SimpleNamespace(config=self.config("192.0.2.20:5555"), request_redraw=Mock())
        view = plugin.DashboardView()
        view.refreshing = True
        view._waiting_since["192.0.2.20:5555"] = 0
        view._results.put(({}, {"192.0.2.20:5555": "waiting-for-adb"}, [], ""))

        with patch.object(plugin.time, "monotonic", return_value=301):
            view.on_tick(context)

        self.assertEqual(view.device_statuses, {"192.0.2.20:5555": "unavailable"})
        self.assertEqual(view._next_refresh_at, 0)

    def test_resolved_adb_serial_is_probed_and_rendered(self) -> None:
        capture = Mock(
            side_effect=[
                SimpleNamespace(returncode=0, stdout=json.dumps({"status": "running"}), stderr=""),
                SimpleNamespace(returncode=0, stdout=json.dumps({"192.0.2.20:5555": "ready"}), stderr=""),
            ]
        )
        context = SimpleNamespace(
            config=self.config("192.0.2.20:5555"),
            commands=SimpleNamespace(capture_host=capture),
        )
        view = plugin.DashboardView()

        view.refresh(context)
        canvas = self.canvas()
        view.render(canvas, context)

        self.assertEqual(capture.call_count, 2)
        self.assertIn("192.0.2.20:5555: ready", canvas.lines)

    def test_cached_board_status_supplies_dynamic_serial(self) -> None:
        capture = Mock(
            side_effect=[
                SimpleNamespace(returncode=0, stdout=json.dumps({"status": "running"}), stderr=""),
                SimpleNamespace(returncode=0, stdout=json.dumps({"192.0.2.30:5555": "ready"}), stderr=""),
            ]
        )
        context = SimpleNamespace(
            config=self.config(),
            commands=SimpleNamespace(capture_host=capture),
            runtime_state={
                "board_status": {
                    "board-a": {
                        "serial": "192.0.2.30:5555",
                        "available": True,
                        "adb_checked": True,
                    }
                }
            },
        )
        view = plugin.DashboardView()

        view.refresh(context)

        self.assertEqual(view.device_statuses, {"192.0.2.30:5555": "ready"})
        self.assertEqual(view.unresolved_devices, [])
        self.assertIn("192.0.2.30:5555", capture.call_args_list[1].args[1])

    def test_cached_availability_is_rechecked_on_the_runner(self) -> None:
        capture = Mock(
            side_effect=[
                SimpleNamespace(returncode=0, stdout=json.dumps({"status": "running"}), stderr=""),
                SimpleNamespace(returncode=1, stdout="", stderr="device offline"),
            ]
        )
        context = SimpleNamespace(
            config=self.config(),
            commands=SimpleNamespace(capture_host=capture),
            runtime_state={
                "board_status": {
                    "board-a": {
                        "serial": "192.0.2.30:5555",
                        "available": True,
                        "adb_checked": True,
                    }
                }
            },
        )
        view = plugin.DashboardView()

        view.refresh(context)

        self.assertEqual(view.device_statuses, {})
        self.assertEqual(view.unresolved_devices, [])
        self.assertEqual(view.error, "ADB status check failed: device offline")


class AvailableBoardsViewTests(unittest.TestCase):
    @staticmethod
    def config() -> dict[str, object]:
        return {
            "active_runner": "runner-a",
            "runners": [
                {
                    "name": "runner-a",
                    "user": "runner",
                    "host": "192.0.2.10",
                    "workspace_dir": "/srv/runs",
                }
            ],
            "board_profiles": [
                {
                    "name": "lab",
                    "devices": [
                        {
                            "board_id": "board-a",
                            "serial": "",
                        }
                    ],
                }
            ],
        }

    def test_refresh_resolves_board_and_reads_android_build_identity(self) -> None:
        inventory = [
            {
                "board_profile": "lab",
                "board_id": "board-a",
                "serial": "10.13.64.232:5555",
                "available": True,
                "state": "device",
                "android_serial": "android-serial",
                "build_id": "CP2A.260605.016",
                "build_incremental": "1234567",
                "build_fingerprint": "vendor/product/device:17/build/id:userdebug/test-keys",
                "error": "",
            }
        ]
        capture = Mock(
            side_effect=[
                SimpleNamespace(
                    returncode=0,
                    stdout=(
                        '__MRC_BOARD_STATUS__{"board": true, "serial": true, "dom0": true, '
                        '"dom0_login": true, "domd": true, "domd_login": false, "adb": true}\n'
                        "10.13.64.232:5555\n"
                    ),
                    stderr="",
                ),
                SimpleNamespace(returncode=0, stdout=json.dumps(inventory), stderr=""),
            ]
        )
        context = SimpleNamespace(
            config=self.config(),
            active_project_id="project-a",
            runtime_state={},
            boards=(SimpleNamespace(board_id="board-a", remote="carla@192.0.2.20"),),
            commands=SimpleNamespace(
                capture_host=capture,
                product_adb_resolver=Mock(
                    return_value=SimpleNamespace(command="resolve-android", timeout_seconds=60)
                ),
            ),
        )
        view = plugin.AvailableBoardsView()

        view.on_enter(context)
        self.assertEqual(view.boards[0]["state"], "not checked")
        view.refresh(context)

        self.assertTrue(view.boards[0]["available"])
        self.assertTrue(view.boards[0]["adb_checked"])
        self.assertEqual(view.boards[0]["build_id"], "CP2A.260605.016")
        self.assertTrue(view.boards[0]["probe"]["dom0"])
        self.assertFalse(view.boards[0]["probe"]["domd_login"])
        self.assertEqual(view.error, "")
        self.assertEqual(
            context.runtime_state["board_status"]["board-a"]["serial"],
            "10.13.64.232:5555",
        )
        self.assertEqual(capture.call_args_list[0], call("carla@192.0.2.20", "resolve-android", timeout=60))
        self.assertEqual(capture.call_args_list[1].args[0], "runner@192.0.2.10")
        self.assertIn("ro.build.id", capture.call_args_list[1].args[1])

    def test_reopening_restores_the_last_status_from_shared_cache(self) -> None:
        context = SimpleNamespace(
            config=self.config(),
            runtime_state={
                "board_status": {
                    "board-a": {
                        "serial": "192.0.2.30:5555",
                        "available": True,
                        "adb_checked": True,
                        "state": "device",
                        "probe": {"serial": True, "board": True, "dom0": True, "domd": True},
                        "android_serial": "android-serial",
                        "build_id": "CP2A.260605.016",
                        "build_incremental": "1234567",
                        "build_fingerprint": "vendor/product/device:17/build/id:userdebug/test-keys",
                    }
                }
            },
        )
        view = plugin.AvailableBoardsView()

        view.on_enter(context)

        self.assertEqual(view.boards[0]["serial"], "192.0.2.30:5555")
        self.assertTrue(view.boards[0]["available"])
        self.assertTrue(view.boards[0]["adb_checked"])
        self.assertEqual(view.boards[0]["build_id"], "CP2A.260605.016")
        self.assertTrue(view.boards[0]["probe"]["domd"])

    def test_renders_board_status_as_aligned_table(self) -> None:
        class Canvas:
            def __init__(self) -> None:
                self.lines: list[str] = []
                self.wrapped_lines: list[str] = []
                self.height = 40
                self.width = 140

            def text(self, _row, _column, value, **_kwargs) -> None:
                self.lines.append(value)

            def box(self, _row, _column, _height, _width, title, **_kwargs) -> None:
                self.lines.append(title)

            def wrapped_text(self, _row, _column, _width, value, **_kwargs) -> None:
                self.lines.append(value)
                self.wrapped_lines.append(value)

        view = plugin.AvailableBoardsView()
        view.boards = [
            {
                "board_profile": "lab",
                "board_id": "board-a",
                "serial": "",
                "available": False,
                "state": "checking",
                "probe": {"serial": True, "board": True, "adb": None},
                "error": "resolver failure with details that must stay inside the value column",
            }
        ]
        canvas = Canvas()

        view.render(canvas, None)

        header = next(line for line in canvas.lines if "Profile" in line and "Serial" in line)
        status = next(line for line in canvas.lines if "board-a" in line and "[+]" in line)
        self.assertLess(header.index("Profile"), header.index("Board"))
        self.assertLess(header.index("Serial"), header.index("Power"))
        self.assertIn("[+]    [+]", status)
        self.assertTrue(status.rstrip().endswith("[?]"))
        self.assertTrue(any("Field" in line and "| Value" in line for line in canvas.lines))
        self.assertTrue(any(line.strip().startswith("ADB serial") for line in canvas.lines))
        self.assertTrue(any(line.strip().startswith("Dom0 login") for line in canvas.lines))
        self.assertEqual(
            canvas.wrapped_lines,
            ["resolver failure with details that must stay inside the value column"],
        )

    def test_renders_selected_board_check_log_in_right_panel(self) -> None:
        class Canvas:
            width = 140
            height = 40

            def __init__(self) -> None:
                self.entries: list[tuple[int, int, str]] = []

            def text(self, row, column, value, **_kwargs) -> None:
                self.entries.append((row, column, value))

            def box(self, row, column, _height, _width, title, **_kwargs) -> None:
                self.entries.append((row, column, title))

            def wrapped_text(self, row, column, _width, value, **_kwargs) -> None:
                self.entries.append((row, column, value))

        view = plugin.AvailableBoardsView()
        view.boards = [
            {
                "board_profile": "lab",
                "board_id": "board-a",
                "serial": "",
                "available": False,
                "probe": {},
                "logs": ["send: enter DomD console", "console: generic login:"],
                "error": "",
            }
        ]
        canvas = Canvas()

        view.render(canvas, None)

        self.assertTrue(any(value == "Logs" for _row, _column, value in canvas.entries))
        self.assertTrue(any(value == "send: enter DomD console" for _row, _column, value in canvas.entries))
        log_panel_columns = [column for _row, column, value in canvas.entries if value == "Logs"]
        self.assertEqual(log_panel_columns[0], canvas.width // 2)
        log_columns = [column for _row, column, value in canvas.entries if value.startswith("send:")]
        self.assertGreater(log_columns[0], canvas.width // 2)

    def test_log_panel_expands_with_f_and_escape_shrinks_it(self) -> None:
        view = plugin.AvailableBoardsView()
        view.boards = [
            {
                "board_profile": "lab",
                "board_id": "board-a",
                "logs": ["line 1", "line 2"],
            }
        ]
        context = SimpleNamespace()

        result = view.handle_event(SimpleNamespace(code=ord("f"), text="f"), context)

        self.assertEqual(result, "handled")
        self.assertTrue(view.log_panel.expanded)

        result = view.handle_event(SimpleNamespace(code=27, text=""), context)

        self.assertEqual(result, "handled")
        self.assertFalse(view.log_panel.expanded)

    def test_board_actions_accept_russian_layout_hotkeys(self) -> None:
        view = plugin.AvailableBoardsView()
        view.boards = [
            {"board_profile": "lab", "board_id": "board-a"},
            {"board_profile": "lab", "board_id": "board-b"},
            {"board_profile": "other", "board_id": "board-c"},
        ]
        view._start_refresh = Mock()
        context = SimpleNamespace(
            dialogs=SimpleNamespace(confirm=Mock(return_value=True)),
            request_redraw=Mock(),
        )

        view.handle_event(
            SimpleNamespace(code=plugin.ui_input_api.encode_text_key("ы"), text="ы"),
            context,
        )
        view._start_refresh.assert_called_with(context, [0, 1])
        view._start_refresh.reset_mock()

        view.handle_event(
            SimpleNamespace(code=plugin.ui_input_api.encode_text_key("ф"), text="ф"),
            context,
        )
        view._start_refresh.assert_called_with(context)

    def test_resolver_failure_is_reported_for_its_board(self) -> None:
        context = SimpleNamespace(
            config=self.config(),
            active_project_id="project-a",
            boards=(SimpleNamespace(board_id="board-a", remote="carla@192.0.2.20"),),
            commands=SimpleNamespace(
                capture_host=Mock(return_value=SimpleNamespace(returncode=1, stdout="", stderr="not found")),
                product_adb_resolver=Mock(
                    return_value=SimpleNamespace(command="resolve-android", timeout_seconds=60)
                ),
            ),
        )
        view = plugin.AvailableBoardsView()

        view.on_enter(context)
        view.refresh(context)

        self.assertEqual(view.error, "")
        self.assertEqual(view.boards[0]["board_id"], "board-a")
        self.assertEqual(view.boards[0]["state"], "probe failed")
        self.assertFalse(view.boards[0]["adb_checked"])
        self.assertIn("not found", view.boards[0]["error"])

    def test_check_actions_target_one_profile_or_all_boards(self) -> None:
        view = plugin.AvailableBoardsView()
        view.boards = [
            {"board_profile": "lab", "board_id": "board-a"},
            {"board_profile": "lab", "board_id": "board-b"},
            {"board_profile": "other", "board_id": "board-c"},
        ]
        view.selected = 1
        view._start_refresh = Mock()
        context = SimpleNamespace(
            dialogs=SimpleNamespace(confirm=Mock(return_value=True)),
            request_redraw=Mock(),
        )

        view.handle_event(SimpleNamespace(code=10, text=""), context)
        view._start_refresh.assert_called_with(context, [1])
        view._start_refresh.reset_mock()

        view.handle_event(SimpleNamespace(code=ord("s"), text="s"), context)
        view._start_refresh.assert_called_with(context, [0, 1])
        view._start_refresh.reset_mock()

        view.handle_event(SimpleNamespace(code=ord("a"), text="a"), context)
        view._start_refresh.assert_called_with(context)
        self.assertEqual(context.dialogs.confirm.call_count, 3)
        title, details = context.dialogs.confirm.call_args.args
        self.assertEqual(title, "Check board consoles")
        self.assertIn("lab / board-a", details)
        self.assertIn("other / board-c", details)

    def test_cancelled_board_check_does_not_take_serial_console(self) -> None:
        view = plugin.AvailableBoardsView()
        view.boards = [{"board_profile": "lab", "board_id": "board-a"}]
        view._start_refresh = Mock()
        context = SimpleNamespace(
            dialogs=SimpleNamespace(confirm=Mock(return_value=False)),
            request_redraw=Mock(),
        )

        view.handle_event(SimpleNamespace(code=10, text=""), context)

        view._start_refresh.assert_not_called()
        context.dialogs.confirm.assert_called_once()

    def test_background_check_result_is_applied_on_tick(self) -> None:
        view = plugin.AvailableBoardsView()
        view.checking = True
        result = [{"board_profile": "lab", "board_id": "board-a", "state": "device"}]
        view._results.put((result, ""))
        context = SimpleNamespace(request_redraw=Mock())

        view.on_tick(context)

        self.assertEqual(view.boards, result)
        self.assertFalse(view.checking)
        context.request_redraw.assert_called_once_with()

    def test_background_check_progress_is_applied_before_final_result(self) -> None:
        view = plugin.AvailableBoardsView()
        view.checking = True
        view.boards = [
            {
                "board_profile": "lab",
                "board_id": "board-a",
                "serial": "",
                "state": "checking",
                "probe": {},
            }
        ]
        view._progress.put((0, {"board": True, "serial": True, "dom0": None}))
        view._progress.put((0, {"_log": "console: generic login:"}))
        context = SimpleNamespace(request_redraw=Mock())

        view.on_tick(context)

        self.assertEqual(view.boards[0]["probe"], {"board": True, "serial": True, "dom0": None})
        self.assertEqual(view.boards[0]["logs"], ["console: generic login:"])
        self.assertEqual(view.boards[0]["state"], "checking")
        self.assertTrue(view.checking)
        context.request_redraw.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
