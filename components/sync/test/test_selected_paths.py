from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from components.remote.api import transport
from components.sync.api import selected_paths
from components.sync.test.test_planner import sample_config


class SyncSelectedPathServiceTests(unittest.TestCase):
    def test_pull_command_owns_selected_project_path_use_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            service = selected_paths.sync_selected_path_service()
            config = sample_config(app_dir, with_mapping=False)
            config["exclude"] = ["tmp/", "*.pyc"]

            argv = service.selected_paths_pull_command_for_config(
                config,
                ["layers/meta", "prod.yaml"],
                dry_run=True,
                app_dir=app_dir,
            )

            expected = transport.rsync_base_command(dry_run=True, relative=True)
            expected.extend(
                [
                    "--exclude",
                    "tmp/",
                    "--exclude",
                    "*.pyc",
                    "builder@10.0.0.1:/mnt/projects/meta-product/./layers/meta",
                    "builder@10.0.0.1:/mnt/projects/meta-product/./prod.yaml",
                    str(app_dir / "overlay") + "/",
                ]
            )
            self.assertEqual(argv, expected)
            self.assertTrue((app_dir / "overlay").is_dir())

    def test_push_command_checks_missing_local_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            service = selected_paths.sync_selected_path_service()
            config = sample_config(app_dir, with_mapping=False)

            with self.assertRaisesRegex(SystemExit, "local selected paths are missing"):
                service.selected_paths_push_command_for_config(
                    config,
                    ["missing/path"],
                    dry_run=False,
                    app_dir=app_dir,
                )

    def test_run_selected_paths_reads_selection_and_runs_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            (local_base / "layers/meta").mkdir(parents=True)
            selection_path = app_dir / "selected.txt"
            selection_path.write_text("layers/meta\n", encoding="utf-8")
            service = selected_paths.sync_selected_path_service()
            config = sample_config(app_dir, with_mapping=False)
            calls: list[list[str]] = []

            service.run_selected_paths_push_for_config(
                config,
                selection_path,
                dry_run=True,
                app_dir=app_dir,
                runner=calls.append,
            )

            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][-2:], [str(local_base) + "/./layers/meta", "builder@10.0.0.1:/mnt/projects/meta-product/"])


if __name__ == "__main__":
    unittest.main()
