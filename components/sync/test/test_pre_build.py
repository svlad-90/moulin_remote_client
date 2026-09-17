from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from components.sync.api import pre_build
from components.sync.test.test_planner import sample_config


class SyncPreBuildServiceTests(unittest.TestCase):
    def test_pre_build_sync_commands_own_intro_issue_and_failure_paths(self) -> None:
        service = pre_build.sync_pre_build_service()

        no_mapping_commands = service.pre_build_sync_commands([], [], [], rsync_command=lambda mapping: ["rsync"])
        self.assertIn("Copy mapped files: no active mappings selected", no_mapping_commands[0][2])

        issue_commands = service.pre_build_sync_commands(
            ["layer"],
            [{"name": "layer"}],
            [f"issue-{index}" for index in range(10)],
            rsync_command=lambda mapping: ["rsync"],
        )
        self.assertEqual(len(issue_commands), 1)
        self.assertIn("Copy mapped files skipped: local overlay is not ready", issue_commands[0][2])
        self.assertIn("issue-7", issue_commands[0][2])
        self.assertNotIn("issue-8", issue_commands[0][2])

        def failing_rsync(mapping: dict[str, str]) -> list[str]:
            if mapping["name"] == "bad":
                raise SystemExit("cannot push")
            return ["rsync", mapping["name"]]

        failure_commands = service.pre_build_sync_commands(
            ["ok", "bad", "later"],
            [{"name": "ok"}, {"name": "bad"}, {"name": "later"}],
            [],
            rsync_command=failing_rsync,
        )
        self.assertIn("Copy mapped files mapping: ok", failure_commands[1][2])
        self.assertEqual(failure_commands[1][-2:], ["rsync", "ok"])
        self.assertIn("Copy mapped files failed: bad", failure_commands[2][2])

    def test_pre_build_sync_commands_for_config_push_active_mappings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            layer = local_base / "layers/meta"
            layer.mkdir(parents=True)
            (layer / "recipe.bb").write_text("x\n", encoding="utf-8")
            service = pre_build.sync_pre_build_service()
            config = sample_config(app_dir)

            argv = service.pre_build_sync_commands_for_config(
                config,
                selection_path=app_dir / "unused.txt",
                app_dir=app_dir,
            )

            self.assertEqual(len(argv), 3)
            self.assertIn("Copy mapped files: pushing active mappings to remote", argv[0][2])
            self.assertIn("Copy mapped files mapping: layer", argv[1][2])
            self.assertEqual(argv[1][-2:], [str(layer) + "/", "builder@10.0.0.1:/mnt/projects/meta-product/layers/meta/"])
            self.assertIn("recorded incremental build baseline", argv[2][2])

    def test_command_sequence_saves_build_settings_and_appends_build_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            layer = local_base / "layers/meta"
            layer.mkdir(parents=True)
            (layer / "recipe.bb").write_text("x\n", encoding="utf-8")
            default_config_path = app_dir / "config.json"
            service = pre_build.sync_pre_build_service()
            config = sample_config(app_dir)
            config["__config_path"] = str(default_config_path)

            argv = service.command_sequence_for_config(
                config,
                ["ninja", "full_ufs.img.gz"],
                parameters={"ENABLE_ANDROID": "yes"},
                targets="full_ufs.img.gz",
                docker_image="prod-image",
                selection_path=app_dir / "unused.txt",
                app_dir=app_dir,
                default_config_path=default_config_path,
            )

            self.assertEqual(argv[-1], ["ninja", "full_ufs.img.gz"])
            self.assertEqual(json.loads((app_dir / "state/build-settings.json").read_text(encoding="utf-8"))["targets"], "full_ufs.img.gz")


if __name__ == "__main__":
    unittest.main()
