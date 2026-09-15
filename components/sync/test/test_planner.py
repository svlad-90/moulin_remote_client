from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from components.sync.api import planner
from components.sync.test.test_commands import commands


def sample_config(app_dir: Path, *, with_mapping: bool = True) -> dict[str, object]:
    local_base = app_dir / "overlay"
    project: dict[str, object] = {
        "name": "prod",
        "project_dir": "meta-product",
        "local_project_dir": str(local_base),
    }
    if with_mapping:
        project.update(
            {
                "active_mappings": ["layer"],
                "mappings": [{"name": "layer", "role": "source layer", "remote": "layers/meta", "local": "layers/meta"}],
            }
        )
    return {
        "inventory": {"mapping_selection": str(app_dir / "selected-mappings.txt")},
        "state": {"build_settings": "state/build-settings.json"},
        "local": {"project_dir": str(local_base)},
        "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
        "active_remote": "build",
        "projects": [project],
        "active_project": "prod",
    }


class SyncCommandPlannerTests(unittest.TestCase):
    def test_selected_path_commands_match_existing_command_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            (local_base / "layers/meta").mkdir(parents=True)
            service = planner.sync_command_planner()
            config = sample_config(app_dir, with_mapping=False)

            self.assertEqual(
                service.selected_paths_pull_command_for_config(
                    config,
                    ["layers/meta", "prod.yaml"],
                    dry_run=True,
                    app_dir=app_dir,
                ),
                commands.build_selected_paths_pull_command_for_config(
                    config,
                    ["layers/meta", "prod.yaml"],
                    dry_run=True,
                    app_dir=app_dir,
                ),
            )
            self.assertEqual(
                service.selected_paths_push_command_for_config(
                    config,
                    ["layers/meta"],
                    dry_run=False,
                    app_dir=app_dir,
                ),
                commands.build_selected_paths_push_command_for_config(
                    config,
                    ["layers/meta"],
                    dry_run=False,
                    app_dir=app_dir,
                ),
            )

    def test_mapping_plan_and_batch_commands_match_existing_command_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            (local_base / "layers/meta").mkdir(parents=True)
            selection_path = app_dir / "selected-mappings.txt"
            service = planner.sync_command_planner()
            config = sample_config(app_dir)

            self.assertEqual(
                service.mapping_sync_plan_for_config(
                    config,
                    ["layer"],
                    direction="push",
                    dry_run=True,
                    app_dir=app_dir,
                ),
                commands.build_mapping_sync_plan_for_config(
                    config,
                    ["layer"],
                    direction="push",
                    dry_run=True,
                    app_dir=app_dir,
                ),
            )
            self.assertEqual(
                service.selected_mapping_commands_for_config(
                    config,
                    selection_path=selection_path,
                    direction="push",
                    dry_run=True,
                    app_dir=app_dir,
                ),
                commands.build_selected_mapping_commands_for_config(
                    config,
                    selection_path=selection_path,
                    direction="push",
                    dry_run=True,
                    app_dir=app_dir,
                ),
            )

    def test_pre_build_and_build_sequence_match_existing_command_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            layer = local_base / "layers/meta"
            layer.mkdir(parents=True)
            (layer / "recipe.bb").write_text("x\n", encoding="utf-8")
            default_config_path = app_dir / "config.json"
            service = planner.sync_command_planner()
            config = sample_config(app_dir)
            config["__config_path"] = str(default_config_path)

            self.assertEqual(
                service.pre_build_sync_commands_for_config(
                    config,
                    selection_path=app_dir / "unused.txt",
                    app_dir=app_dir,
                ),
                commands.build_pre_build_sync_commands_for_config(
                    config,
                    selection_path=app_dir / "unused.txt",
                    app_dir=app_dir,
                ),
            )

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
