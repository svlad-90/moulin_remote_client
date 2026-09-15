from __future__ import annotations

import unittest
from pathlib import Path

import moulin_remote_client as client
from components.board.api import builder as board_builder_api
from components.board.api import flash as board_flash_api
from components.board.api import transfer as board_transfer_api
from components.board.api import workflow as board_workflow_api
from components.config.api import accessors as config_accessors
from components.config.api import profiles as config_profiles


def sample_config() -> dict[str, object]:
    return {
        "board_hosts": [
            {
                "name": "board",
                "label": "Board",
                "user": "testrpi5",
                "host": "10.13.64.242",
                "work_dir": "/srv/tftp/vgon",
            }
        ],
        "active_board_host": "board",
    }


def sample_copy_config() -> dict[str, object]:
    config = sample_config()
    config.update(
        {
            "remotes": [
                {
                    "name": "build",
                    "label": "Build",
                    "user": "builder",
                    "host": "10.0.0.1",
                    "projects_dir": "/mnt/projects",
                }
            ],
            "active_remote": "build",
            "projects": [{"name": "prod", "project_dir": "meta-product", "moulin_manifest": "prod.yaml"}],
            "active_project": "prod",
        }
    )
    return config


class BoardCommandBehaviorTests(unittest.TestCase):
    def test_remote_shell_path_quoting_matches_current_behavior(self) -> None:
        builder = board_builder_api.board_command_builder()

        self.assertEqual(builder.remote_shell_path("~/work"), "$HOME/work")
        self.assertEqual(builder.quote_remote_shell_path("~"), '"$HOME"')
        self.assertEqual(builder.quote_remote_shell_path("~/work dir"), '"$HOME"/\'work dir\'')

    def test_board_ssh_command_matches_current_behavior(self) -> None:
        config = sample_config()
        config_profiles.normalize_board_host_profiles(config)
        workflow = self._workflow_service()
        builder = board_builder_api.board_command_builder()
        command = "cd /srv/tftp/vgon && ls"
        board_host = config_accessors.host_spec(config_profiles.active_board_host(config))

        self.assertEqual(
            workflow.interactive_shell_command(config),
            ["ssh", "-t", "testrpi5@10.13.64.242"],
        )
        self.assertEqual(
            builder.board_ssh_command(board_host, command, tty=True),
            ["ssh", "-tt", "testrpi5@10.13.64.242", "bash -lic 'cd /srv/tftp/vgon && ls'"],
        )

    def test_run_board_interactive_shell_for_config_delegates_to_runner(self) -> None:
        config = sample_config()
        config_profiles.normalize_board_host_profiles(config)
        workflow = self._workflow_service()
        calls: list[list[str]] = []

        rc = workflow.run_interactive_shell(
            config,
            lambda argv: calls.append(argv) or 17,
        )

        self.assertEqual(rc, 17)
        self.assertEqual(calls, [["ssh", "-t", "testrpi5@10.13.64.242"]])

    def test_board_deploy_tool_command_matches_current_behavior(self) -> None:
        config = sample_config()
        config_profiles.normalize_board_host_profiles(config)
        builder = board_builder_api.board_command_builder()
        tool = Path("/tmp/flash_bootloaders.py")
        board_host = config_accessors.host_spec(config_profiles.active_board_host(config))
        work_dir = config_accessors.board_work_dir(config_profiles.active_board_host(config))

        self.assertEqual(
            builder.board_deploy_tool_command(board_host, work_dir, tool),
            [
                "bash",
                "-lc",
                "cat /tmp/flash_bootloaders.py | ssh testrpi5@10.13.64.242 'mkdir -p /srv/tftp/vgon && cat > /srv/tftp/vgon/flash_bootloaders.py && chmod +x /srv/tftp/vgon/flash_bootloaders.py'",
            ],
        )
        self.assertEqual(
            builder.board_tool_remote_path(work_dir, tool),
            "/srv/tftp/vgon/flash_bootloaders.py",
        )

    def test_board_prepare_work_dir_command_matches_current_behavior(self) -> None:
        config = sample_config()
        config_profiles.normalize_board_host_profiles(config)
        builder = board_builder_api.board_command_builder()
        board_host = config_accessors.host_spec(config_profiles.active_board_host(config))
        artifacts_dir = config_accessors.board_artifacts_dir(
            config_accessors.board_work_dir(config_profiles.active_board_host(config))
        )

        self.assertEqual(
            builder.board_prepare_work_dir_command(board_host, artifacts_dir),
            ["ssh", "testrpi5@10.13.64.242", "mkdir -p /srv/tftp/vgon/artifacts"],
        )

    def test_artifact_resolver_script_matches_current_shape(self) -> None:
        specs = [
            {"label": "boot_artifacts", "path": "artifacts/ironhide-boot-artifacts.tar.bz2"},
            {"label": "full_ufs.img.gz", "path": "full_ufs.img.gz"},
        ]
        transfer = self._transfer_service()

        script = transfer.artifact_resolver_script("/remote/product", specs)

        self.assertIn("requested_labels=(boot_artifacts full_ufs.img.gz)", script)
        self.assertIn("requested_paths=(artifacts/ironhide-boot-artifacts.tar.bz2 full_ufs.img.gz)", script)
        self.assertIn("resolved_tar_args+=(-C \"$tar_dir\" \"$(basename \"$found\")\")", script)

    def test_tar_progress_command_matches_current_behavior(self) -> None:
        destination_script = "mkdir -p /srv/tftp/vgon/artifacts && cd /srv/tftp/vgon/artifacts && tar -xf -"
        transfer = self._transfer_service()

        command = transfer.tar_progress_command("testrpi5@10.13.64.242", destination_script)

        self.assertIn("BOARD_COPY_DESTINATION=testrpi5@10.13.64.242", command)
        self.assertIn("StrictHostKeyChecking=accept-new", command)
        self.assertIn("progress: {pct}% ({copied}/{total} bytes)", command)

    def test_copy_build_artifacts_direct_route_uses_build_host_to_board_stream(self) -> None:
        specs = [
            {
                "label": "boot_artifacts",
                "path": "artifacts/ironhide-boot-artifacts.tar.bz2",
                "source": "manifest component target_images",
            },
            {"label": "full_ufs.img.gz", "path": "full_ufs.img.gz", "source": "manifest image output"},
        ]
        transfer = self._transfer_service()

        argv = transfer.copy_build_artifacts_command_plan(
            artifact_targets=["boot_artifacts", "full_ufs.img.gz"],
            artifact_specs=specs,
            build_host="builder@10.0.0.1",
            board_host="board@10.0.0.2",
            source_dir="/mnt/projects/meta-product",
            destination_dir="/srv/tftp/vgon/artifacts",
            direct_copy=True,
        )

        self.assertEqual(argv[0][:2], ["bash", "-lc"])
        self.assertIn("route: direct build-host -> board-host", argv[0][2])
        self.assertEqual(argv[1][0:2], ["ssh", "builder@10.0.0.1"])
        self.assertIn("transfer: tar stream build-host -> board-host", argv[1][2])
        self.assertIn("StrictHostKeyChecking=accept-new board@10.0.0.2", argv[1][2])
        self.assertIn("progress: pv not found on build host; using python byte progress", argv[1][2])

    def test_copy_build_artifacts_via_client_route_uses_prepare_and_pipe(self) -> None:
        specs = [{"label": "full_ufs.img.gz", "path": "full_ufs.img.gz", "source": "manifest image output"}]
        transfer = self._transfer_service()

        argv = transfer.copy_build_artifacts_command_plan(
            artifact_targets=["full_ufs.img.gz"],
            artifact_specs=specs,
            build_host="builder@10.0.0.1",
            board_host="board@10.0.0.2",
            source_dir="/mnt/projects/meta-product",
            destination_dir="/srv/tftp/vgon/artifacts",
            direct_copy=False,
        )

        self.assertEqual(len(argv), 3)
        self.assertIn("route: via client machine", argv[0][2])
        self.assertEqual(argv[1], ["ssh", "board@10.0.0.2", "mkdir -p /srv/tftp/vgon/artifacts"])
        self.assertEqual(argv[2][0:2], ["bash", "-lc"])
        self.assertIn("ssh builder@10.0.0.1", argv[2][2])
        self.assertIn("ssh board@10.0.0.2", argv[2][2])

    def test_copy_build_artifacts_reports_missing_artifact_configuration(self) -> None:
        argv = self._transfer_service().copy_build_artifacts_command_plan(
            artifact_targets=["  "],
            artifact_specs=[],
            build_host="builder@10.0.0.1",
            board_host="board@10.0.0.2",
            source_dir="/mnt/projects/meta-product",
            destination_dir="/srv/tftp/vgon/artifacts",
            direct_copy=True,
        )

        self.assertEqual(argv[0][:2], ["bash", "-lc"])
        self.assertIn("No board artifacts configured", argv[0][2])
        self.assertIn("exit 1", argv[0][2])

    def test_copy_build_artifacts_from_config_reports_missing_artifact_configuration(self) -> None:
        config = sample_copy_config()
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_board_host_profiles(config)
        config_profiles.normalize_project_profiles(config)

        argv = self._transfer_service().copy_build_artifacts_commands(
            config,
            artifact_targets="",
            build_params={},
        )

        self.assertEqual(argv[0][:2], ["bash", "-lc"])
        self.assertIn("No board artifacts configured", argv[0][2])

    def test_copy_build_artifacts_from_config_uses_manifest_specs(self) -> None:
        config = sample_copy_config()
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_board_host_profiles(config)
        config_profiles.normalize_project_profiles(config)
        manifest_text = "\n".join(
            [
                "min_ver: '1.0'",
                "variables:",
                "  out: artifacts",
                "components:",
                "  boot_artifacts:",
                "    builder:",
                "      target_images:",
                "        - '%{out}/boot.tar'",
                "images:",
                "  full_ufs: {}",
            ]
        )

        argv = self._transfer_service(remote_read_project_file=lambda _config, _path: manifest_text).copy_build_artifacts_commands(
            config,
            artifact_targets="boot_artifacts full_ufs.img.gz",
            build_params={},
        )

        self.assertIn("from: builder@10.0.0.1:/mnt/projects/meta-product", argv[0][2])
        self.assertIn("to:   testrpi5@10.13.64.242:/srv/tftp/vgon/artifacts", argv[0][2])
        self.assertIn("boot_artifacts: artifacts/boot.tar (manifest component target_images)", argv[0][2])
        self.assertIn("full_ufs.img.gz: full_ufs.img.gz (manifest image output)", argv[0][2])

    def test_flash_bootloaders_commands_from_config_match_low_level_builder(self) -> None:
        config = sample_config()
        config_profiles.normalize_board_host_profiles(config)
        flash = self._flash_service()
        workflow = self._workflow_service()

        argv = flash.flash_bootloaders_command_plan(
            board_host=config_accessors.board_host_spec_for_config(config),
            work_dir=config_accessors.board_work_dir_for_config(config),
            artifacts_dir=config_accessors.board_artifacts_dir_for_config(config),
            tool=client.FLASH_BOOTLOADERS_TOOL,
        )

        self.assertEqual(
            argv,
            workflow.flash_bootloaders_commands(config),
        )
        self.assertEqual(len(argv), 7)
        self.assertIn("x5h_flash", argv[3][-1])
        self.assertIn("tar -xf \"$archive\" -C \"$artifact_dir\" --strip-components=1", argv[4][-1])
        self.assertIn("python3 -u ./flash_bootloaders.py --port /dev/GEN5_CONSOLE", argv[6][-1])
        self.assertIn("x5h_boot", argv[6][-1])

    def test_flash_ufs_commands_from_config_match_low_level_builder(self) -> None:
        config = sample_config()
        config["board_hosts"][0]["console_device"] = ""
        config["board_hosts"][0]["ufs_loadaddr"] = "0x50000000"
        config["board_hosts"][0]["ufs_buffersize"] = "0x4000000"
        config_profiles.normalize_board_host_profiles(config)
        flash = self._flash_service()
        workflow = self._workflow_service()

        argv = flash.flash_ufs_command_plan(
            board_host=config_accessors.board_host_spec_for_config(config),
            work_dir=config_accessors.board_work_dir_for_config(config),
            artifacts_dir=config_accessors.board_artifacts_dir_for_config(config),
            console=config_accessors.board_console_device_for_config(config),
            loadaddr=config_accessors.board_ufs_loadaddr_for_config(config),
            buffersize=config_accessors.board_ufs_buffersize_for_config(config),
            tool=client.XT_IMAGER_TOOL,
        )

        self.assertEqual(
            argv,
            workflow.flash_ufs_image_commands(config),
        )
        self.assertEqual(len(argv), 4)
        script = argv[3][-1]
        self.assertIn("x5h_off", script)
        self.assertIn("x5h_on", script)
        self.assertIn("x5h_boot", script)
        self.assertIn("console=$(ls -1 /dev/GEN5_CONSOLE*", script)
        self.assertIn("To continue, type exactly: FLASH UFS 1", script)
        self.assertIn("--loadaddr", script)
        self.assertIn("0x50000000", script)
        self.assertIn("--buffersize", script)
        self.assertIn("0x4000000", script)

    def _transfer_service(
        self,
        *,
        remote_read_project_file=lambda _config, _path: "",
    ) -> board_transfer_api.BoardArtifactTransferService:
        return board_transfer_api.board_artifact_transfer_service(
            command_builder=board_builder_api.board_command_builder(),
            app_dir=Path("/tmp/app"),
            default_moulin_manifest="product.yaml",
            remote_read_project_file=remote_read_project_file,
            manifest_cache={},
        )

    def _flash_service(self) -> board_flash_api.BoardFlashCommandService:
        return board_flash_api.board_flash_command_service(command_builder=board_builder_api.board_command_builder())

    def _workflow_service(self) -> board_workflow_api.BoardCommandWorkflowService:
        return board_workflow_api.board_command_workflow_service(
            app_dir=Path("/tmp/app"),
            default_moulin_manifest="product.yaml",
            flash_bootloaders_tool=client.FLASH_BOOTLOADERS_TOOL,
            xt_imager_tool=client.XT_IMAGER_TOOL,
            remote_read_project_file=lambda _config, _path: "",
            manifest_cache={},
        )


if __name__ == "__main__":
    unittest.main()
