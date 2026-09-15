from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from components.sync.api import workflow


class SyncCommandWorkflowServiceTests(unittest.TestCase):
    def test_build_command_sequence_saves_settings_and_prepends_sync(self) -> None:
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
                "inventory": {"mapping_selection": str(app_dir / "selected-mappings.txt")},
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
            service = workflow.sync_command_workflow_service(
                app_dir=app_dir,
                default_config_path=default_config_path,
            )

            argv = service.build_command_sequence(
                config,
                ["ninja", "full_ufs.img.gz"],
                parameters={"ENABLE_ANDROID": "yes"},
                targets="full_ufs.img.gz",
                docker_image="prod-image",
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

    def test_run_cli_command_delegates_to_sync_cli_service_with_workflow_app_dir(self) -> None:
        class FakeCliService:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def run_cli_sync_command_for_config(
                self,
                config: dict[str, object],
                command: str,
                names: list[str],
                *,
                app_dir: Path,
                runner: object,
                write_line: object,
            ) -> None:
                self.calls.append({
                    "config": config,
                    "command": command,
                    "names": names,
                    "app_dir": app_dir,
                    "runner": runner,
                    "write_line": write_line,
                })

        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            cli_service = FakeCliService()
            service = workflow.sync_command_workflow_service(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                cli_service=cli_service,
            )
            config: dict[str, object] = {"active_project": "prod"}
            runner = lambda _argv: None
            write_line = lambda _line: None

            service.run_cli_command(
                config,
                "push-selected-map-dry-run",
                ["meta"],
                runner=runner,
                write_line=write_line,
            )

            self.assertEqual(cli_service.calls[0]["config"], config)
            self.assertEqual(cli_service.calls[0]["command"], "push-selected-map-dry-run")
            self.assertEqual(cli_service.calls[0]["names"], ["meta"])
            self.assertEqual(cli_service.calls[0]["app_dir"], app_dir)
            self.assertIs(cli_service.calls[0]["runner"], runner)
            self.assertIs(cli_service.calls[0]["write_line"], write_line)


if __name__ == "__main__":
    unittest.main()
