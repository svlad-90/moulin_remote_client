from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

import moulin_remote_client as client
from components.board.api import workflow
from components.board.api.session import board_session_command_service
from components.config.api import profiles as config_profiles

from components.board.test.test_commands import sample_config, sample_copy_config


class BoardCommandWorkflowServiceTests(unittest.TestCase):
    def test_session_service_owns_connect_and_shell_use_cases(self) -> None:
        config = sample_config()
        config_profiles.normalize_board_host_profiles(config)
        service = board_session_command_service()
        calls: list[list[str]] = []

        self.assertEqual(
            service.connect_command_for_config(config),
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                "testrpi5@10.13.64.242",
                "printf 'ssh=ok\\n'; uname -a | sed 's/^/target=/'",
            ],
        )
        self.assertEqual(
            service.interactive_shell_command_for_config(config),
            ["ssh", "-t", "testrpi5@10.13.64.242"],
        )
        self.assertEqual(
            service.run_interactive_shell(config, lambda argv: calls.append(argv) or 23),
            23,
        )
        self.assertEqual(calls, [["ssh", "-t", "testrpi5@10.13.64.242"]])

    def test_interactive_shell_service_matches_command_builder(self) -> None:
        config = sample_config()
        config_profiles.normalize_board_host_profiles(config)
        service = self._service()

        self.assertEqual(
            service.connect_command(config),
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                "testrpi5@10.13.64.242",
                "printf 'ssh=ok\\n'; uname -a | sed 's/^/target=/'",
            ],
        )
        self.assertEqual(
            service.interactive_shell_command(config),
            ["ssh", "-t", "testrpi5@10.13.64.242"],
        )

    def test_copy_build_artifacts_service_owns_config_use_case(self) -> None:
        config = sample_copy_config()
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_board_host_profiles(config)
        config_profiles.normalize_project_profiles(config)
        manifest_text = "\n".join(
            [
                "min_ver: '1.0'",
                "components:",
                "  boot_artifacts:",
                "    builder:",
                "      target_images:",
                "        - artifacts/boot.tar",
                "images:",
                "  full_ufs: {}",
            ]
        )
        service = self._service(remote_read_project_file=lambda _config, _path: manifest_text)

        argv = service.copy_build_artifacts_commands(
            config,
            artifact_targets="boot_artifacts full_ufs.img.gz",
            build_params={},
        )

        self.assertIn("Copy build artifacts", argv[0][2])
        self.assertIn("boot_artifacts: artifacts/boot.tar (manifest component target_images)", argv[0][2])
        self.assertIn("full_ufs.img.gz: full_ufs.img.gz (manifest image output)", argv[0][2])

    def test_workflow_runs_copy_build_artifacts_with_scenario_title(self) -> None:
        config = sample_copy_config()
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_board_host_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = self._service(remote_read_project_file=lambda _config, _path: "images:\n  full_ufs: {}\n")
        calls: list[tuple[str, list[list[str]]]] = []

        result = service.run_copy_build_artifacts(
            config,
            artifact_targets="full_ufs.img.gz",
            build_params={},
            runner=lambda title, commands: calls.append((title, commands)) or 17,
        )

        self.assertEqual(result, 17)
        self.assertEqual(calls[0][0], "Copy build artifacts")
        self.assertIn("full_ufs.img.gz: full_ufs.img.gz", calls[0][1][0][2])

    def test_flash_services_match_command_builders(self) -> None:
        config = sample_config()
        config_profiles.normalize_board_host_profiles(config)
        service = self._service()

        bootloaders = service.flash_bootloaders_commands(config)
        ufs = service.flash_ufs_image_commands(config)

        self.assertEqual(len(bootloaders), 7)
        self.assertIn("x5h_flash", bootloaders[3][-1])
        self.assertIn("python3 -u ./flash_bootloaders.py", bootloaders[6][-1])
        self.assertEqual(len(ufs), 4)
        self.assertIn("x5h_boot", ufs[3][-1])
        self.assertIn("XT_FLASH_TOOL", ufs[3][-1])

    def test_workflow_runs_flash_scenarios_with_titles(self) -> None:
        config = sample_config()
        config_profiles.normalize_board_host_profiles(config)
        service = self._service()
        calls: list[tuple[str, list[list[str]]]] = []

        service.run_flash_bootloaders(config, runner=lambda title, commands: calls.append((title, commands)))
        service.run_flash_ufs_image(config, runner=lambda title, commands: calls.append((title, commands)))

        self.assertEqual([title for title, _commands in calls], ["Flash bootloaders", "Flash UFS image"])
        self.assertEqual(calls[0][1], service.flash_bootloaders_commands(config))
        self.assertEqual(calls[1][1], service.flash_ufs_image_commands(config))

    def _service(
        self,
        *,
        remote_read_project_file: Any = None,
    ) -> workflow.BoardCommandWorkflowService:
        return workflow.board_command_workflow_service(
            app_dir=Path("/tmp/app"),
            default_moulin_manifest="product.yaml",
            flash_bootloaders_tool=client.FLASH_BOOTLOADERS_TOOL,
            xt_imager_tool=client.XT_IMAGER_TOOL,
            remote_read_project_file=remote_read_project_file or (lambda _config, _path: ""),
            manifest_cache={},
        )


if __name__ == "__main__":
    unittest.main()
