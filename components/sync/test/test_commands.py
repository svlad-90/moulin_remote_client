from __future__ import annotations

import json
from shlex import quote as shlex_quote
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable

from components.sync.api import display as sync_display_api
from components.sync.api import planner as sync_planner_api
from components.sync.api import screen_workflow as sync_screen_workflow_api
from components.sync.api import workflow as sync_workflow_api


class commands:
    @staticmethod
    def build_rsync_mapping_command(
        mapping: dict[str, Any],
        *,
        direction: str,
        dry_run: bool,
        excludes: list[str],
        local_base: Path,
        remote_base: str,
        prepare: bool = True,
    ) -> list[str]:
        return sync_planner_api.sync_command_planner().rsync_mapping_command(
            mapping,
            direction=direction,
            dry_run=dry_run,
            excludes=excludes,
            local_base=local_base,
            remote_base=remote_base,
            prepare=prepare,
        )

    @staticmethod
    def display_command_lines(argv: list[str]) -> list[str]:
        return sync_display_api.sync_command_display_service().display_command_lines(argv)

    @staticmethod
    def sanitize_log_line(line: str) -> str:
        return sync_display_api.sync_command_display_service().sanitize_log_line(line)

    @staticmethod
    def build_rsync_path_args(paths: list[str], base: str) -> list[str]:
        return sync_planner_api.sync_command_planner().build_rsync_path_args(paths, base)

    @staticmethod
    def build_selected_paths_pull_command_for_config(
        config: dict[str, Any],
        paths: list[str],
        *,
        dry_run: bool,
        app_dir: Path,
    ) -> list[str]:
        return sync_planner_api.sync_command_planner().selected_paths_pull_command_for_config(
            config,
            paths,
            dry_run=dry_run,
            app_dir=app_dir,
        )

    @staticmethod
    def build_selected_paths_push_command_for_config(
        config: dict[str, Any],
        paths: list[str],
        *,
        dry_run: bool,
        app_dir: Path,
    ) -> list[str]:
        return sync_planner_api.sync_command_planner().selected_paths_push_command_for_config(
            config,
            paths,
            dry_run=dry_run,
            app_dir=app_dir,
        )

    @staticmethod
    def run_selected_paths_pull_for_config(
        config: dict[str, Any],
        selection_path: Path,
        *,
        dry_run: bool,
        app_dir: Path,
        runner: Callable[[list[str]], Any],
    ) -> None:
        sync_planner_api.sync_command_planner().run_selected_paths_pull_for_config(
            config,
            selection_path,
            dry_run=dry_run,
            app_dir=app_dir,
            runner=runner,
        )

    @staticmethod
    def run_selected_paths_push_for_config(
        config: dict[str, Any],
        selection_path: Path,
        *,
        dry_run: bool,
        app_dir: Path,
        runner: Callable[[list[str]], Any],
    ) -> None:
        sync_planner_api.sync_command_planner().run_selected_paths_push_for_config(
            config,
            selection_path,
            dry_run=dry_run,
            app_dir=app_dir,
            runner=runner,
        )

    @staticmethod
    def build_mapping_sync_plan_for_config(
        config: dict[str, Any],
        names: list[str],
        *,
        direction: str,
        dry_run: bool,
        app_dir: Path,
    ) -> list[dict[str, Any]]:
        return sync_planner_api.sync_command_planner().mapping_sync_plan_for_config(
            config,
            names,
            direction=direction,
            dry_run=dry_run,
            app_dir=app_dir,
        )

    @staticmethod
    def run_command_plan(
        plan: list[dict[str, Any]],
        *,
        runner: Callable[[list[str]], Any],
        write_line: Callable[[str], Any],
    ) -> None:
        sync_planner_api.sync_command_planner().run_command_plan(plan, runner=runner, write_line=write_line)

    @staticmethod
    def run_mapping_sync_plan_for_config(
        config: dict[str, Any],
        names: list[str],
        *,
        direction: str,
        dry_run: bool,
        app_dir: Path,
        runner: Callable[[list[str]], Any],
        write_line: Callable[[str], Any],
    ) -> None:
        sync_planner_api.sync_command_planner().run_mapping_sync_plan_for_config(
            config,
            names,
            direction=direction,
            dry_run=dry_run,
            app_dir=app_dir,
            runner=runner,
            write_line=write_line,
        )

    @staticmethod
    def run_selected_mapping_sync_plan_for_config(
        config: dict[str, Any],
        selection_path: Path,
        *,
        direction: str,
        dry_run: bool,
        app_dir: Path,
        runner: Callable[[list[str]], Any],
        write_line: Callable[[str], Any],
    ) -> None:
        sync_planner_api.sync_command_planner().run_selected_mapping_sync_plan_for_config(
            config,
            selection_path,
            direction=direction,
            dry_run=dry_run,
            app_dir=app_dir,
            runner=runner,
            write_line=write_line,
        )

    @staticmethod
    def run_cli_sync_command_for_config(
        config: dict[str, Any],
        command: str,
        names: list[str],
        *,
        app_dir: Path,
        runner: Callable[[list[str]], Any],
        write_line: Callable[[str], Any],
    ) -> None:
        sync_workflow_api.sync_command_workflow_service(
            app_dir=app_dir,
            default_config_path=Path(str(config.get("__config_path", app_dir / "config.json"))),
        ).run_cli_command(
            config,
            command,
            names,
            runner=runner,
            write_line=write_line,
        )

    @staticmethod
    def build_rsync_mapping_commands(
        mappings: list[dict[str, Any]],
        *,
        direction: str,
        dry_run: bool,
        excludes: list[str],
        local_base: Path,
        remote_base: str,
        prepare: bool = True,
    ) -> list[list[str]]:
        return sync_planner_api.sync_command_planner().rsync_mapping_commands(
            mappings,
            direction=direction,
            dry_run=dry_run,
            excludes=excludes,
            local_base=local_base,
            remote_base=remote_base,
            prepare=prepare,
        )

    @staticmethod
    def build_rsync_mapping_command_for_config(
        config: dict[str, Any],
        mapping: dict[str, Any],
        *,
        direction: str,
        dry_run: bool,
        app_dir: Path,
        prepare: bool = True,
    ) -> list[str]:
        return sync_planner_api.sync_command_planner().rsync_mapping_command_for_config(
            config,
            mapping,
            direction=direction,
            dry_run=dry_run,
            app_dir=app_dir,
            prepare=prepare,
        )

    @staticmethod
    def build_selected_mapping_commands_for_config(
        config: dict[str, Any],
        *,
        selection_path: Path,
        direction: str,
        dry_run: bool,
        app_dir: Path,
        prepare: bool = True,
    ) -> list[list[str]]:
        return sync_planner_api.sync_command_planner().selected_mapping_commands_for_config(
            config,
            selection_path=selection_path,
            direction=direction,
            dry_run=dry_run,
            app_dir=app_dir,
            prepare=prepare,
        )

    @staticmethod
    def build_pre_build_sync_commands(
        names: list[str],
        active_mappings: list[dict[str, Any]],
        issues: list[str],
        *,
        rsync_command: Callable[[dict[str, Any]], list[str]],
    ) -> list[list[str]]:
        return sync_planner_api.sync_command_planner().pre_build_sync_commands(
            names,
            active_mappings,
            issues,
            rsync_command=rsync_command,
        )

    @staticmethod
    def build_pre_build_sync_commands_for_config(
        config: dict[str, Any],
        *,
        selection_path: Path,
        app_dir: Path,
    ) -> list[list[str]]:
        return sync_planner_api.sync_command_planner().pre_build_sync_commands_for_config(
            config,
            selection_path=selection_path,
            app_dir=app_dir,
        )

    @staticmethod
    def build_command_sequence_for_config(
        config: dict[str, Any],
        build_command: list[str],
        *,
        parameters: dict[str, Any],
        targets: str,
        docker_image: str,
        selection_path: Path,
        app_dir: Path,
        default_config_path: Path,
    ) -> list[list[str]]:
        return sync_planner_api.sync_command_planner().command_sequence_for_config(
            config,
            build_command,
            parameters=parameters,
            targets=targets,
            docker_image=docker_image,
            selection_path=selection_path,
            app_dir=app_dir,
            default_config_path=default_config_path,
        )

    @staticmethod
    def build_pre_build_selection_error_command(error: BaseException) -> list[list[str]]:
        return sync_planner_api.sync_command_planner().pre_build_selection_error_command(error)

    @staticmethod
    def sync_screen_actions() -> list[dict[str, Any]]:
        return sync_screen_workflow_api.sync_screen_workflow_service().actions()

    @staticmethod
    def sync_screen_action_enabled(action: dict[str, Any], *, connected: bool) -> bool:
        return sync_screen_workflow_api.sync_screen_workflow_service().action_enabled(action, connected=connected)

    @staticmethod
    def sync_screen_disabled_status(action: dict[str, Any], *, connected: bool) -> str:
        return sync_screen_workflow_api.sync_screen_workflow_service().disabled_status(action, connected=connected)

    @staticmethod
    def sync_screen_mapping_detail_rows(
        mappings: list[dict[str, Any]],
        selected_names: list[str],
        *,
        limit: int,
    ) -> list[str]:
        return sync_screen_workflow_api.sync_screen_workflow_service().mapping_detail_rows(
            mappings,
            selected_names,
            limit=limit,
        )

    @staticmethod
    def sync_screen_action_result_for_config(
        config: dict[str, Any],
        action: dict[str, Any],
        *,
        app_dir: Path,
    ) -> dict[str, Any]:
        return sync_screen_workflow_api.sync_screen_workflow_service().action_result_for_config(
            config,
            action,
            app_dir=app_dir,
        )


class SyncCommandBehaviorTests(unittest.TestCase):
    def test_pull_directory_dry_run_command_matches_current_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            local_base = Path(tmpdir) / "overlay"
            mapping = {
                "name": "layer",
                "remote": "layers/meta-example",
                "local": "layers/meta-example",
                "kind": "directory",
                "push": True,
            }

            argv = commands.build_rsync_mapping_command(
                mapping,
                direction="pull",
                dry_run=True,
                excludes=["--exclude", "tmp/"],
                local_base=local_base,
                remote_base="builder@example:/work/product",
            )

            self.assertEqual(
                argv,
                [
                    "rsync",
                    "-az",
                    "--delete",
                    "--dry-run",
                    "--itemize-changes",
                    "--exclude",
                    "tmp/",
                    "builder@example:/work/product/layers/meta-example/",
                    str(local_base / "layers/meta-example") + "/",
                ],
            )
            self.assertTrue((local_base / "layers/meta-example").is_dir())

    def test_push_file_apply_command_matches_current_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            local_base = Path(tmpdir) / "overlay"
            local_file = local_base / "prod.yaml"
            local_file.parent.mkdir(parents=True)
            local_file.write_text("manifest\n", encoding="utf-8")
            mapping = {
                "name": "manifest",
                "remote": "prod.yaml",
                "local": "prod.yaml",
                "kind": "file",
                "push": True,
            }

            argv = commands.build_rsync_mapping_command(
                mapping,
                direction="push",
                dry_run=False,
                excludes=[],
                local_base=local_base,
                remote_base="builder@example:/work/product",
            )

            self.assertEqual(
                argv,
                [
                    "rsync",
                    "-az",
                    "--delete",
                    str(local_file),
                    "builder@example:/work/product/prod.yaml",
                ],
            )

    def test_push_dry_run_for_pull_only_mapping_returns_log_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mapping = {
                "name": "readonly",
                "remote": "readonly",
                "local": "readonly",
                "kind": "directory",
                "push": False,
            }

            argv = commands.build_rsync_mapping_command(
                mapping,
                direction="push",
                dry_run=True,
                excludes=[],
                local_base=Path(tmpdir),
                remote_base="builder@example:/work/product",
            )

            self.assertEqual(argv[:2], ["bash", "-lc"])
            self.assertIn("SKIP push dry-run: readonly", argv[2])
            self.assertEqual(commands.display_command_lines(argv), ["command: <log message>"])

    def test_display_command_lines_expands_multiline_script(self) -> None:
        argv = ["ssh", "board", "set -e\nx5h_flash\n"]

        self.assertEqual(
            commands.display_command_lines(argv),
            ["command: ssh board '<script>'", "script:", "  set -e", "  x5h_flash", ""],
        )

    def test_display_command_lines_expands_nested_bash_login_script(self) -> None:
        script = "bash -lic " + shlex_quote("set -e\nx5h_boot\n")
        argv = ["ssh", "-tt", "board", script]

        self.assertEqual(
            commands.display_command_lines(argv),
            ["command: ssh -tt board bash -lic '<script>'", "script:", "  set -e", "  x5h_boot", ""],
        )

    def test_display_command_lines_wraps_long_script_lines(self) -> None:
        long_line = "x" * 120
        lines = commands.display_command_lines(["bash", "-lc", long_line + "\n"])

        self.assertEqual(lines[0:2], ["command: bash -lc '<script>'", "script:"])
        self.assertEqual(lines[2], "  " + ("x" * 112))
        self.assertEqual(lines[3], "    " + ("x" * 8))

    def test_sanitize_log_line_removes_ansi_and_control_characters(self) -> None:
        self.assertEqual(commands.sanitize_log_line("\x1b[31mred\x1b[0m\x07\tok"), "red \tok")

    def test_push_apply_for_missing_local_path_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mapping = {
                "name": "missing",
                "remote": "missing",
                "local": "missing",
                "kind": "directory",
                "push": True,
            }

            with self.assertRaises(SystemExit):
                commands.build_rsync_mapping_command(
                    mapping,
                    direction="push",
                    dry_run=False,
                    excludes=[],
                    local_base=Path(tmpdir),
                    remote_base="builder@example:/work/product",
                )

    def test_relative_path_args_match_current_shape(self) -> None:
        self.assertEqual(
            commands.build_rsync_path_args(["a", "b/c"], "/remote/root/"),
            ["/remote/root//./a", "/remote/root//./b/c"],
        )

    def test_selected_paths_pull_command_for_config_matches_current_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            config = {
                "exclude": ["tmp/"],
                "local": {"project_dir": str(local_base)},
                "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
                "active_remote": "build",
                "projects": [{"name": "prod", "project_dir": "meta-product"}],
                "active_project": "prod",
            }

            argv = commands.build_selected_paths_pull_command_for_config(
                config,
                ["layers/meta", "prod.yaml"],
                dry_run=True,
                app_dir=app_dir,
            )

            self.assertTrue(local_base.is_dir())
            self.assertEqual(
                argv,
                [
                    "rsync",
                    "-az",
                    "--relative",
                    "--delete",
                    "--dry-run",
                    "--itemize-changes",
                    "--exclude",
                    "tmp/",
                    "builder@10.0.0.1:/mnt/projects/meta-product/./layers/meta",
                    "builder@10.0.0.1:/mnt/projects/meta-product/./prod.yaml",
                    str(local_base) + "/",
                ],
            )

    def test_selected_paths_push_command_for_config_checks_missing_local_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            local_base.mkdir()
            config = {
                "local": {"project_dir": str(local_base)},
                "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
                "active_remote": "build",
                "projects": [{"name": "prod", "project_dir": "meta-product"}],
                "active_project": "prod",
            }

            with self.assertRaisesRegex(SystemExit, "local selected paths are missing"):
                commands.build_selected_paths_push_command_for_config(
                    config,
                    ["missing"],
                    dry_run=False,
                    app_dir=app_dir,
                )

    def test_selected_paths_push_command_for_config_matches_current_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            (local_base / "layers").mkdir(parents=True)
            (local_base / "layers/meta").write_text("data\n", encoding="utf-8")
            config = {
                "local": {"project_dir": str(local_base)},
                "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
                "active_remote": "build",
                "projects": [{"name": "prod", "project_dir": "meta-product"}],
                "active_project": "prod",
            }

            argv = commands.build_selected_paths_push_command_for_config(
                config,
                ["layers/meta"],
                dry_run=False,
                app_dir=app_dir,
            )

            self.assertEqual(
                argv,
                [
                    "rsync",
                    "-az",
                    "--relative",
                    "--delete",
                    str(local_base) + "/./layers/meta",
                    "builder@10.0.0.1:/mnt/projects/meta-product/",
                ],
            )

    def test_run_selected_paths_pull_for_config_reads_selection_and_runs_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            selection_path = app_dir / "selection.txt"
            selection_path.write_text("layers/meta\nprod.yaml\n", encoding="utf-8")
            ran: list[list[str]] = []
            config = {
                "local": {"project_dir": str(app_dir / "overlay")},
                "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
                "active_remote": "build",
                "projects": [{"name": "prod", "project_dir": "meta-product"}],
                "active_project": "prod",
            }

            commands.run_selected_paths_pull_for_config(
                config,
                selection_path,
                dry_run=True,
                app_dir=app_dir,
                runner=ran.append,
            )

            self.assertEqual(
                ran[0][-3:],
                [
                    "builder@10.0.0.1:/mnt/projects/meta-product/./layers/meta",
                    "builder@10.0.0.1:/mnt/projects/meta-product/./prod.yaml",
                    str(app_dir / "overlay") + "/",
                ],
            )

    def test_run_selected_paths_push_for_config_reads_selection_and_runs_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            (local_base / "layers/meta").mkdir(parents=True)
            selection_path = app_dir / "selection.txt"
            selection_path.write_text("layers/meta\n", encoding="utf-8")
            ran: list[list[str]] = []
            config = {
                "local": {"project_dir": str(local_base)},
                "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
                "active_remote": "build",
                "projects": [{"name": "prod", "project_dir": "meta-product"}],
                "active_project": "prod",
            }

            commands.run_selected_paths_push_for_config(
                config,
                selection_path,
                dry_run=True,
                app_dir=app_dir,
                runner=ran.append,
            )

            self.assertEqual(
                ran[0][-2:],
                [str(local_base) + "/./layers/meta", "builder@10.0.0.1:/mnt/projects/meta-product/"],
            )

    def test_mapping_sync_plan_for_config_selects_and_builds_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            (local_base / "layers/meta").mkdir(parents=True)
            config = {
                "local": {"project_dir": str(local_base)},
                "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
                "active_remote": "build",
                "projects": [
                    {
                        "name": "prod",
                        "project_dir": "meta-product",
                        "mappings": [
                            {
                                "name": "meta",
                                "role": "source layer",
                                "remote": "layers/meta",
                                "local": "layers/meta",
                                "kind": "directory",
                                "push": True,
                            }
                        ],
                    }
                ],
                "active_project": "prod",
            }

            plan = commands.build_mapping_sync_plan_for_config(
                config,
                ["meta"],
                direction="push",
                dry_run=True,
                app_dir=app_dir,
            )

            self.assertEqual(
                plan,
                [
                    {
                        "header": ["\n== push: meta ==", "role: source layer", "remote: layers/meta", "local:  layers/meta"],
                        "argv": [
                            "rsync",
                            "-az",
                            "--delete",
                            "--dry-run",
                            "--itemize-changes",
                            str(local_base / "layers/meta") + "/",
                            "builder@10.0.0.1:/mnt/projects/meta-product/layers/meta/",
                        ],
                    }
                ],
            )

    def test_run_command_plan_prints_headers_and_runs_commands_in_order(self) -> None:
        lines: list[str] = []
        ran: list[list[str]] = []

        commands.run_command_plan(
            [
                {"header": ["one", "two"], "argv": ["cmd", "1"]},
                {"header": ["three"], "argv": ["cmd", "2"]},
            ],
            runner=ran.append,
            write_line=lines.append,
        )

        self.assertEqual(lines, ["one", "two", "three"])
        self.assertEqual(ran, [["cmd", "1"], ["cmd", "2"]])

    def test_run_mapping_sync_plan_for_config_builds_and_runs_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            (local_base / "layers/meta").mkdir(parents=True)
            lines: list[str] = []
            ran: list[list[str]] = []
            config = {
                "local": {"project_dir": str(local_base)},
                "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
                "active_remote": "build",
                "projects": [
                    {
                        "name": "prod",
                        "project_dir": "meta-product",
                        "mappings": [
                            {
                                "name": "meta",
                                "role": "source layer",
                                "remote": "layers/meta",
                                "local": "layers/meta",
                                "kind": "directory",
                                "push": True,
                            }
                        ],
                    }
                ],
                "active_project": "prod",
            }

            commands.run_mapping_sync_plan_for_config(
                config,
                ["meta"],
                direction="push",
                dry_run=True,
                app_dir=app_dir,
                runner=ran.append,
                write_line=lines.append,
            )

            self.assertEqual(lines, ["\n== push: meta ==", "role: source layer", "remote: layers/meta", "local:  layers/meta"])
            self.assertEqual(ran[0][-2:], [str(local_base / "layers/meta") + "/", "builder@10.0.0.1:/mnt/projects/meta-product/layers/meta/"])

    def test_run_selected_mapping_sync_plan_for_config_uses_project_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            (local_base / "layers/meta").mkdir(parents=True)
            selection_path = app_dir / "selected.txt"
            lines: list[str] = []
            ran: list[list[str]] = []
            config = {
                "local": {"project_dir": str(local_base)},
                "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
                "active_remote": "build",
                "projects": [
                    {
                        "name": "prod",
                        "project_dir": "meta-product",
                        "active_mappings": ["meta"],
                        "mappings": [{"name": "meta", "role": "source layer", "remote": "layers/meta", "local": "layers/meta"}],
                    }
                ],
                "active_project": "prod",
            }

            commands.run_selected_mapping_sync_plan_for_config(
                config,
                selection_path,
                direction="push",
                dry_run=True,
                app_dir=app_dir,
                runner=ran.append,
                write_line=lines.append,
            )

            self.assertEqual(lines[0], "\n== push: meta ==")
            self.assertEqual(ran[0][-2:], [str(local_base / "layers/meta") + "/", "builder@10.0.0.1:/mnt/projects/meta-product/layers/meta/"])

    def test_run_cli_sync_command_for_config_routes_selected_path_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            inventory = app_dir / "selection.txt"
            inventory.write_text("layers/meta\n", encoding="utf-8")
            ran: list[list[str]] = []
            config = {
                "inventory": {"selection": str(inventory)},
                "local": {"project_dir": str(app_dir / "overlay")},
                "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
                "active_remote": "build",
                "projects": [{"name": "prod", "project_dir": "meta-product"}],
                "active_project": "prod",
            }

            commands.run_cli_sync_command_for_config(
                config,
                "pull-dry-run",
                [],
                app_dir=app_dir,
                runner=ran.append,
                write_line=lambda _line: None,
            )

            self.assertIn("--dry-run", ran[0])
            self.assertEqual(ran[0][-2:], ["builder@10.0.0.1:/mnt/projects/meta-product/./layers/meta", str(app_dir / "overlay") + "/"])

    def test_run_cli_sync_command_for_config_routes_selected_mapping_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            (local_base / "layers/meta").mkdir(parents=True)
            mapping_selection = app_dir / "mapping-selection.txt"
            lines: list[str] = []
            ran: list[list[str]] = []
            config = {
                "inventory": {"mapping_selection": str(mapping_selection)},
                "local": {"project_dir": str(local_base)},
                "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
                "active_remote": "build",
                "projects": [
                    {
                        "name": "prod",
                        "project_dir": "meta-product",
                        "active_mappings": ["meta"],
                        "mappings": [{"name": "meta", "role": "source layer", "remote": "layers/meta", "local": "layers/meta"}],
                    }
                ],
                "active_project": "prod",
            }

            commands.run_cli_sync_command_for_config(
                config,
                "push-selected-map-dry-run",
                [],
                app_dir=app_dir,
                runner=ran.append,
                write_line=lines.append,
            )

            self.assertEqual(lines[0], "\n== push: meta ==")
            self.assertIn("--dry-run", ran[0])
            self.assertEqual(ran[0][-2:], [str(local_base / "layers/meta") + "/", "builder@10.0.0.1:/mnt/projects/meta-product/layers/meta/"])

    def test_mapping_command_batch_preserves_order_and_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            local_base = Path(tmpdir) / "overlay"
            (local_base / "a").mkdir(parents=True)
            (local_base / "b").mkdir()
            mappings = [
                {"name": "a", "remote": "remote-a", "local": "a", "kind": "directory", "push": True},
                {"name": "b", "remote": "remote-b", "local": "b", "kind": "directory", "push": True},
            ]

            argv = commands.build_rsync_mapping_commands(
                mappings,
                direction="push",
                dry_run=False,
                excludes=["--exclude", "tmp/"],
                local_base=local_base,
                remote_base="builder@example:/work/product",
            )

            self.assertEqual(len(argv), 2)
            self.assertEqual(argv[0][-2:], [str(local_base / "a") + "/", "builder@example:/work/product/remote-a/"])
            self.assertEqual(argv[1][-2:], [str(local_base / "b") + "/", "builder@example:/work/product/remote-b/"])
            self.assertEqual(argv[0][3:5], ["--exclude", "tmp/"])

    def test_mapping_command_for_config_resolves_active_project_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            (local_base / "layers/meta").mkdir(parents=True)
            config = {
                "exclude": ["tmp/"],
                "local": {"project_dir": str(local_base)},
                "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
                "active_remote": "build",
                "projects": [{"name": "prod", "project_dir": "meta-product"}],
                "active_project": "prod",
            }
            mapping = {
                "name": "layer",
                "remote": "layers/meta",
                "local": "layers/meta",
                "kind": "directory",
                "push": True,
            }

            argv = commands.build_rsync_mapping_command_for_config(
                config,
                mapping,
                direction="push",
                dry_run=True,
                app_dir=app_dir,
            )

            self.assertEqual(argv[5:7], ["--exclude", "tmp/"])
            self.assertEqual(argv[-2:], [str(local_base / "layers/meta") + "/", "builder@10.0.0.1:/mnt/projects/meta-product/layers/meta/"])

    def test_selected_mapping_commands_for_config_uses_project_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            (local_base / "layers/meta").mkdir(parents=True)
            selection_path = app_dir / "selection.txt"
            config = {
                "local": {"project_dir": str(local_base)},
                "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
                "active_remote": "build",
                "projects": [
                    {
                        "name": "prod",
                        "project_dir": "meta-product",
                        "active_mappings": ["layer"],
                        "mappings": [{"name": "layer", "remote": "layers/meta", "local": "layers/meta"}],
                    }
                ],
                "active_project": "prod",
            }

            argv = commands.build_selected_mapping_commands_for_config(
                config,
                selection_path=selection_path,
                direction="push",
                dry_run=True,
                app_dir=app_dir,
            )

            self.assertEqual(len(argv), 1)
            self.assertEqual(argv[0][-2:], [str(local_base / "layers/meta") + "/", "builder@10.0.0.1:/mnt/projects/meta-product/layers/meta/"])

    def test_pre_build_sync_commands_match_current_no_selection_behavior(self) -> None:
        self.assertEqual(
            commands.build_pre_build_sync_commands([], [], [], rsync_command=lambda mapping: ["rsync"]),
            [],
        )

    def test_pre_build_sync_commands_report_local_overlay_issues(self) -> None:
        argv = commands.build_pre_build_sync_commands(
            ["layer"],
            [{"name": "layer"}],
            [f"issue-{index}" for index in range(10)],
            rsync_command=lambda mapping: ["rsync"],
        )

        self.assertEqual(len(argv), 1)
        self.assertIn("Pre-build sync skipped: local overlay is not ready", argv[0][2])
        self.assertIn("Run Sync mapped files -> Pull selected apply first.", argv[0][2])
        self.assertIn("issue-7", argv[0][2])
        self.assertNotIn("issue-8", argv[0][2])
        self.assertIn("exit 1", argv[0][2])

    def test_pre_build_sync_commands_preserve_intro_and_mapping_order(self) -> None:
        mappings = [{"name": "a"}, {"name": "b"}]

        argv = commands.build_pre_build_sync_commands(
            ["a", "b"],
            mappings,
            [],
            rsync_command=lambda mapping: ["rsync", str(mapping["name"])],
        )

        self.assertEqual(len(argv), 3)
        self.assertIn("Pre-build sync: pushing active mappings to remote", argv[0][2])
        self.assertIn("mappings: a, b", argv[0][2])
        self.assertEqual(argv[1:], [["rsync", "a"], ["rsync", "b"]])

    def test_pre_build_sync_commands_turn_mapping_failure_into_log_command(self) -> None:
        def failing_rsync(mapping: dict[str, str]) -> list[str]:
            if mapping["name"] == "bad":
                raise SystemExit("cannot push")
            return ["rsync", mapping["name"]]

        argv = commands.build_pre_build_sync_commands(
            ["ok", "bad", "later"],
            [{"name": "ok"}, {"name": "bad"}, {"name": "later"}],
            [],
            rsync_command=failing_rsync,
        )

        self.assertEqual(len(argv), 3)
        self.assertEqual(argv[1], ["rsync", "ok"])
        self.assertIn("Pre-build sync failed: bad", argv[2][2])
        self.assertIn("cannot push", argv[2][2])

    def test_pre_build_sync_commands_for_config_reports_missing_local_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            config = {
                "local": {"project_dir": str(app_dir / "overlay")},
                "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
                "active_remote": "build",
                "projects": [
                    {
                        "name": "prod",
                        "project_dir": "meta-product",
                        "active_mappings": ["layer"],
                        "mappings": [{"name": "layer", "remote": "layers/meta", "local": "layers/meta"}],
                    }
                ],
                "active_project": "prod",
            }

            argv = commands.build_pre_build_sync_commands_for_config(
                config,
                selection_path=app_dir / "unused.txt",
                app_dir=app_dir,
            )

            self.assertEqual(len(argv), 1)
            self.assertIn("Pre-build sync skipped: local overlay is not ready", argv[0][2])
            self.assertIn("layer: local path missing:", argv[0][2])

    def test_pre_build_sync_commands_for_config_builds_push_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            layer = local_base / "layers/meta"
            layer.mkdir(parents=True)
            (layer / "recipe.bb").write_text("x\n", encoding="utf-8")
            config = {
                "local": {"project_dir": str(local_base)},
                "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
                "active_remote": "build",
                "projects": [
                    {
                        "name": "prod",
                        "project_dir": "meta-product",
                        "local_project_dir": str(local_base),
                        "active_mappings": ["layer"],
                        "mappings": [{"name": "layer", "remote": "layers/meta", "local": "layers/meta"}],
                    }
                ],
                "active_project": "prod",
            }

            argv = commands.build_pre_build_sync_commands_for_config(
                config,
                selection_path=app_dir / "unused.txt",
                app_dir=app_dir,
            )

            self.assertEqual(len(argv), 2)
            self.assertIn("Pre-build sync: pushing active mappings to remote", argv[0][2])
            self.assertEqual(argv[1][-2:], [str(layer) + "/", "builder@10.0.0.1:/mnt/projects/meta-product/layers/meta/"])

    def test_build_command_sequence_for_config_saves_settings_and_prepends_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            layer = local_base / "layers/meta"
            layer.mkdir(parents=True)
            (layer / "recipe.bb").write_text("x\n", encoding="utf-8")
            default_config_path = app_dir / "config.json"
            config = {
                "__config_path": str(default_config_path),
                "state": {"build_settings": "state/build-settings.json"},
                "local": {"project_dir": str(local_base)},
                "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
                "active_remote": "build",
                "projects": [
                    {
                        "name": "prod",
                        "project_dir": "meta-product",
                        "local_project_dir": str(local_base),
                        "active_mappings": ["layer"],
                        "mappings": [{"name": "layer", "remote": "layers/meta", "local": "layers/meta"}],
                    }
                ],
                "active_project": "prod",
            }

            argv = commands.build_command_sequence_for_config(
                config,
                ["ninja", "full_ufs.img.gz"],
                parameters={"ENABLE_ANDROID": "yes"},
                targets="full_ufs.img.gz",
                docker_image="prod-image",
                selection_path=app_dir / "unused.txt",
                app_dir=app_dir,
                default_config_path=default_config_path,
            )

            self.assertEqual(len(argv), 3)
            self.assertIn("Pre-build sync: pushing active mappings to remote", argv[0][2])
            self.assertEqual(argv[1][-2:], [str(layer) + "/", "builder@10.0.0.1:/mnt/projects/meta-product/layers/meta/"])
            self.assertEqual(argv[2], ["ninja", "full_ufs.img.gz"])
            project = config["projects"][0]
            self.assertEqual(project["parameters"], {"ENABLE_ANDROID": "yes"})
            self.assertEqual(project["targets"], "full_ufs.img.gz")
            self.assertEqual(project["docker_image"], "prod-image")
            saved_settings = json.loads((app_dir / "state/build-settings.json").read_text(encoding="utf-8"))
            self.assertEqual(saved_settings["targets"], "full_ufs.img.gz")
            self.assertTrue(default_config_path.exists())

    def test_pre_build_selection_error_command_matches_current_behavior(self) -> None:
        argv = commands.build_pre_build_selection_error_command(SystemExit("bad selection"))

        self.assertEqual(len(argv), 1)
        self.assertIn("Pre-build sync failed", argv[0][2])
        self.assertIn("bad selection", argv[0][2])
        self.assertIn("exit 1", argv[0][2])

    def test_sync_screen_actions_match_current_menu_shape(self) -> None:
        actions = commands.sync_screen_actions()

        self.assertEqual(
            [action["label"] for action in actions],
            [
                "Select mappings",
                "Activate mappings",
                "Pull selected dry-run",
                "Pull selected apply",
                "Push selected dry-run",
                "Push selected apply",
                "Back",
            ],
        )
        self.assertTrue(actions[0]["requires_remote"])
        self.assertFalse(actions[1]["requires_remote"])
        self.assertTrue(actions[3]["confirm"])
        self.assertFalse(actions[2]["confirm"])

    def test_sync_screen_action_enabled_tracks_build_host_requirement(self) -> None:
        actions = commands.sync_screen_actions()

        self.assertFalse(commands.sync_screen_action_enabled(actions[0], connected=False))
        self.assertTrue(commands.sync_screen_action_enabled(actions[0], connected=True))
        self.assertTrue(commands.sync_screen_action_enabled(actions[1], connected=False))
        self.assertEqual(
            commands.sync_screen_disabled_status(actions[0], connected=False),
            "disabled until the build host is connected",
        )
        self.assertEqual(commands.sync_screen_disabled_status(actions[1], connected=False), "")

    def test_sync_screen_mapping_detail_rows_mark_active_selection(self) -> None:
        rows = commands.sync_screen_mapping_detail_rows(
            [
                {"name": "meta", "local": "layers/meta"},
                {"name": "manifest", "local": "prod.yaml"},
            ],
            ["manifest"],
            limit=2,
        )

        self.assertEqual(rows, ["[ ] meta -> layers/meta", "[*] manifest -> prod.yaml"])

    def test_sync_screen_run_action_result_builds_selected_mapping_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            (local_base / "layers/meta").mkdir(parents=True)
            selection_path = app_dir / "mapping-selection.txt"
            config = {
                "inventory": {"mapping_selection": str(selection_path)},
                "local": {"project_dir": str(local_base)},
                "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
                "active_remote": "build",
                "projects": [
                    {
                        "name": "prod",
                        "project_dir": "meta-product",
                        "active_mappings": ["meta"],
                        "mappings": [{"name": "meta", "remote": "layers/meta", "local": "layers/meta"}],
                    }
                ],
                "active_project": "prod",
            }
            action = commands.sync_screen_actions()[4]

            result = commands.sync_screen_action_result_for_config(config, action, app_dir=app_dir)

            self.assertEqual(result["kind"], "run-commands")
            self.assertEqual(result["title"], "Push selected mappings dry-run")
            self.assertEqual(len(result["commands"]), 1)
            self.assertIn("--dry-run", result["commands"][0])
            self.assertEqual(
                result["commands"][0][-2:],
                [str(local_base / "layers/meta") + "/", "builder@10.0.0.1:/mnt/projects/meta-product/layers/meta/"],
            )


if __name__ == "__main__":
    unittest.main()
