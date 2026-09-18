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
from components.moulin.api import manifest as moulin_manifest_api


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

        command = builder.board_deploy_tool_command(board_host, work_dir, tool)

        self.assertEqual(command[:2], ["bash", "-lc"])
        self.assertIn("cat /tmp/flash_bootloaders.py | ssh testrpi5@10.13.64.242", command[2])
        self.assertIn("Deploy board helper", command[2])
        self.assertIn("from: /tmp/flash_bootloaders.py", command[2])
        self.assertIn("to:   testrpi5@10.13.64.242:/srv/tftp/vgon/flash_bootloaders.py", command[2])
        self.assertIn("cat > /srv/tftp/vgon/flash_bootloaders.py", command[2])
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
            [
                "ssh",
                "testrpi5@10.13.64.242",
                "printf '%s\\n' 'Prepare board artifacts directory'\nprintf '%s\\n' 'path: /srv/tftp/vgon/artifacts'\nmkdir -p /srv/tftp/vgon/artifacts",
            ],
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

        self.assertEqual(argv[0][0:2], ["ssh", "builder@10.0.0.1"])
        self.assertIn("route: direct build-host -> board-host", argv[0][2])
        self.assertIn("transfer: tar stream build-host -> board-host", argv[0][2])
        self.assertIn("StrictHostKeyChecking=accept-new board@10.0.0.2", argv[0][2])
        self.assertIn("progress: pv not found on build host; using python byte progress", argv[0][2])

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

        self.assertEqual(len(argv), 2)
        self.assertIn("Prepare board artifacts directory", argv[0][2])
        self.assertIn("mkdir -p /srv/tftp/vgon/artifacts", argv[0][2])
        self.assertEqual(argv[1][0:2], ["bash", "-lc"])
        self.assertIn("route: via client machine", argv[1][2])
        self.assertIn("ssh builder@10.0.0.1", argv[1][2])
        self.assertIn("ssh board@10.0.0.2", argv[1][2])

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

    @unittest.skipUnless(moulin_manifest_api.yaml_available(), "PyYAML is not installed")
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

        self.assertIn("from: builder@10.0.0.1:/mnt/projects/meta-product", argv[1][2])
        self.assertIn("to:   testrpi5@10.13.64.242:/srv/tftp/vgon/artifacts", argv[1][2])
        self.assertIn("boot_artifacts: artifacts/boot.tar (manifest component target_images)", argv[1][2])
        self.assertIn("full_ufs.img.gz: full_ufs.img.gz (manifest image output)", argv[1][2])

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
        self.assertEqual(len(argv), 6)
        self.assertIn("x5h_flash", argv[2][-1])
        self.assertIn("tar -xf \"$archive\" -C \"$artifact_dir\" --strip-components=1", argv[3][-1])
        self.assertIn("python3 -u ./flash_bootloaders.py --port /dev/GEN5_CONSOLE", argv[5][-1])
        self.assertIn("x5h_boot", argv[5][-1])

    def test_flash_ufs_commands_from_config_use_gen5_board_type_helper(self) -> None:
        config = sample_config()
        config["board_hosts"][0]["console_device"] = ""
        config["board_hosts"][0]["ufs_loadaddr"] = "0x50000000"
        config["board_hosts"][0]["ufs_buffersize"] = "0x4000000"
        config_profiles.normalize_board_host_profiles(config)
        workflow = self._workflow_service()

        argv = workflow.flash_ufs_image_commands(config)

        self.assertEqual(len(argv), 4)
        self.assertIn("xt-imager.py", argv[1][-1])
        self.assertIn("gen5_x5h_flash_ufs.py", argv[2][-1])
        script = argv[3][-1]
        self.assertIn("x5h_off", script)
        self.assertIn("x5h_on", script)
        self.assertIn("x5h_boot", script)
        self.assertIn("console=$(ls -1 /dev/GEN5_CONSOLE*", script)
        self.assertIn("python3 /srv/tftp/vgon/gen5_x5h_flash_ufs.py", script)
        self.assertIn("--tool /srv/tftp/vgon/xt-imager.py", script)
        self.assertNotIn("python3 -c", script)
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
