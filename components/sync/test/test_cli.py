from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from components.sync.api import cli


class SyncCliServiceTests(unittest.TestCase):
    def test_run_command_plan_prints_headers_and_runs_commands_in_order(self) -> None:
        service = cli.sync_cli_service()
        lines: list[str] = []
        ran: list[list[str]] = []

        service.run_command_plan(
            [
                {"header": ["one", "two"], "argv": ["cmd", "1"]},
                {"header": ["three"], "argv": ["cmd", "2"]},
            ],
            runner=ran.append,
            write_line=lines.append,
        )

        self.assertEqual(lines, ["one", "two", "three"])
        self.assertEqual(ran, [["cmd", "1"], ["cmd", "2"]])

    def test_run_cli_sync_command_routes_selected_path_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            inventory = app_dir / "selection.txt"
            inventory.write_text("layers/meta\n", encoding="utf-8")
            service = cli.sync_cli_service()
            ran: list[list[str]] = []
            config = {
                "inventory": {"selection": str(inventory)},
                "local": {"project_dir": str(app_dir / "overlay")},
                "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
                "active_remote": "build",
                "projects": [{"name": "prod", "project_dir": "meta-product"}],
                "active_project": "prod",
            }

            service.run_cli_sync_command_for_config(
                config,
                "pull-dry-run",
                [],
                app_dir=app_dir,
                runner=ran.append,
                write_line=lambda _line: None,
            )

            self.assertIn("--dry-run", ran[0])
            self.assertEqual(ran[0][-2:], ["builder@10.0.0.1:/mnt/projects/meta-product/./layers/meta", str(app_dir / "overlay") + "/"])

    def test_run_cli_sync_command_routes_selected_mapping_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            (local_base / "layers/meta").mkdir(parents=True)
            mapping_selection = app_dir / "mapping-selection.txt"
            service = cli.sync_cli_service()
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

            service.run_cli_sync_command_for_config(
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


if __name__ == "__main__":
    unittest.main()
