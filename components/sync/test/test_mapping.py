from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from components.remote.api import transport
from components.sync.api import mapping
from components.sync.test.test_planner import sample_config


class SyncMappingCommandServiceTests(unittest.TestCase):
    def test_rsync_mapping_command_owns_single_mapping_use_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            local_path = local_base / "layers/meta"
            local_path.mkdir(parents=True)
            service = mapping.sync_mapping_command_service()

            argv = service.rsync_mapping_command(
                {"name": "layer", "kind": "directory", "push": True, "remote": "layers/meta", "local": "layers/meta"},
                direction="push",
                dry_run=True,
                excludes=["--exclude", "*.pyc"],
                local_base=local_base,
                remote_base="builder@10.0.0.1:/mnt/projects/meta-product",
            )

            expected = transport.rsync_base_command(dry_run=True)
            expected.extend(["--exclude", "*.pyc", str(local_path) + "/", "builder@10.0.0.1:/mnt/projects/meta-product/layers/meta/"])
            self.assertEqual(argv, expected)

    def test_mapping_sync_plan_owns_header_and_argv_use_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            (local_base / "layers/meta").mkdir(parents=True)
            service = mapping.sync_mapping_command_service()
            config = sample_config(app_dir)

            plan = service.mapping_sync_plan_for_config(
                config,
                ["layer"],
                direction="push",
                dry_run=True,
                app_dir=app_dir,
                excludes=[],
                remote_base="builder@10.0.0.1:/mnt/projects/meta-product",
            )

            self.assertEqual(plan[0]["header"][0], "\n== push: layer ==")
            self.assertEqual(plan[0]["argv"][-2:], [str(local_base / "layers/meta") + "/", "builder@10.0.0.1:/mnt/projects/meta-product/layers/meta/"])

    def test_selected_mapping_commands_read_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            (local_base / "layers/meta").mkdir(parents=True)
            selection_path = app_dir / "selected-mappings.txt"
            selection_path.write_text("layer\n", encoding="utf-8")
            service = mapping.sync_mapping_command_service()
            config = sample_config(app_dir)

            commands = service.selected_mapping_commands_for_config(
                config,
                selection_path=selection_path,
                direction="push",
                dry_run=True,
                app_dir=app_dir,
                excludes=[],
                remote_base="builder@10.0.0.1:/mnt/projects/meta-product",
            )

            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0][-2:], [str(local_base / "layers/meta") + "/", "builder@10.0.0.1:/mnt/projects/meta-product/layers/meta/"])


if __name__ == "__main__":
    unittest.main()
