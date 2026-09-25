from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

import moulin_remote_client as client
from components.board.api import workflow
from components.board.api.session import board_session_command_service
from components.config.api import profiles as config_profiles
from components.moulin.api import manifest as moulin_manifest_api
from components.remote.api import transport

from components.board.test.test_commands import sample_config, sample_copy_config


class BoardCommandWorkflowServiceTests(unittest.TestCase):
    def test_session_service_owns_connect_and_shell_use_cases(self) -> None:
        config = sample_config()
        config_profiles.normalize_board_host_profiles(config)
        service = board_session_command_service()
        calls: list[list[str]] = []

        self.assertEqual(
            service.connect_command_for_config(config),
            transport.ssh_command("testrpi5@10.13.64.242", "printf 'ssh=ok\\n'; uname -a | sed 's/^/target=/'"),
        )
        self.assertEqual(
            service.interactive_shell_command_for_config(config),
            transport.ssh_command("testrpi5@10.13.64.242", tty="-t"),
        )
        self.assertEqual(
            service.run_interactive_shell(config, lambda argv: calls.append(argv) or 23),
            23,
        )
        self.assertEqual(calls, [transport.ssh_command("testrpi5@10.13.64.242", tty="-t")])

    def test_interactive_shell_service_matches_command_builder(self) -> None:
        config = sample_config()
        config_profiles.normalize_board_host_profiles(config)
        service = self._service()

        self.assertEqual(
            service.connect_command(config),
            transport.ssh_command("testrpi5@10.13.64.242", "printf 'ssh=ok\\n'; uname -a | sed 's/^/target=/'"),
        )
        self.assertEqual(
            service.interactive_shell_command(config),
            transport.ssh_command("testrpi5@10.13.64.242", tty="-t"),
        )

    @unittest.skipUnless(moulin_manifest_api.yaml_available(), "PyYAML is not installed")
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

        self.assertIn("Copy build artifacts", argv[1][2])
        self.assertIn("boot_artifacts: artifacts/boot.tar (manifest component target_images)", argv[1][2])
        self.assertIn("full_ufs.img.gz: full_ufs.img.gz (manifest image output)", argv[1][2])

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
        self.assertIn("full_ufs.img.gz: full_ufs.img.gz", calls[0][1][1][2])

    def test_board_type_adapter_exposes_current_builtin_actions(self) -> None:
        config = sample_config()
        config_profiles.normalize_board_host_profiles(config)
        service = self._service()

        actions = service.board_actions(config)

        self.assertEqual(
            [action.action_id for action in actions],
            [
                "open_board_host_shell",
                "copy_build_artifacts",
                "flash_bootloaders",
                "flash_ufs_image",
                "restart_board",
                "open_board_serial_console",
                "open_uboot_console",
                "deploy_network_boot",
                "deploy_network_domd_rootfs",
                "deploy_network_android",
                "deploy_network_full",
                "install_nfs_deploy_helper",
                "pull_network_workspace",
                "push_network_workspace",
                "pull_dom0_initramfs_workspace",
                "push_dom0_initramfs_workspace",
                "apply_uboot_network_env",
                "apply_uboot_ufs_env",
            ],
        )
        self.assertEqual(
            [action.label for action in actions[:5]],
            ["Open board host shell", "Copy build artifacts", "Flash bootloaders", "Flash UFS image", "Restart board"],
        )
        self.assertTrue(next(action for action in actions if action.action_id == "open_board_host_shell").interactive)
        self.assertTrue(next(action for action in actions if action.action_id == "open_board_serial_console").interactive)
        self.assertTrue(next(action for action in actions if action.action_id == "open_board_serial_console").allow_during_job)
        self.assertTrue(next(action for action in actions if action.action_id == "open_uboot_console").interactive)
        self.assertTrue(next(action for action in actions if action.action_id == "open_uboot_console").allow_during_job)

    def test_network_deploy_commands_use_project_tftp_nfs_paths(self) -> None:
        config = sample_copy_config()
        config["board_hosts"][0].update(
            {
                "tftp_root": "/srv/tftp",
                "nfs_root": "/srv/nfs",
                "deploy_subdir": "vgoncharuk/projects",
                "server_ip": "10.13.64.242",
                "board_ip": "10.13.64.120",
            }
        )
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_board_host_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = self._service()

        boot = service.board_action_commands(config, "deploy_network_boot")
        rootfs = service.board_action_commands(config, "deploy_network_domd_rootfs")
        android = service.board_action_commands(config, "deploy_network_android")
        uboot = service.board_action_commands(config, "apply_uboot_network_env")
        ufs = service.board_action_commands(config, "apply_uboot_ufs_env")

        self.assertEqual("ssh", boot[0][0])
        self.assertIn("builder@10.0.0.1", boot[0])
        self.assertIn("/srv/tftp/vgoncharuk/projects/prod", boot[0][-1])
        self.assertIn("testrpi5@10.13.64.242", boot[0][-1])
        self.assertIn("rsync -az", boot[0][-1])
        self.assertIn("--info=progress2", boot[0][-1])
        self.assertIn("--stats", boot[0][-1])
        self.assertIn("testrpi5@10.13.64.242:/srv/tftp/vgoncharuk/projects/prod/", boot[0][-1])
        self.assertNotIn("MOULIN_STREAM_FILE", boot[0][-1])
        self.assertNotIn("pv not found", boot[0][-1])
        self.assertIn("/srv/nfs/vgoncharuk/projects/prod", rootfs[1][-1])
        self.assertIn("rcar-image-adas", rootfs[0][-1])
        self.assertIn("rcar-image-adas", rootfs[1][-1])
        self.assertIn("rsync -az", rootfs[1][-1])
        self.assertIn("--info=progress2", rootfs[1][-1])
        self.assertIn("--stats", rootfs[1][-1])
        self.assertIn("testrpi5@10.13.64.242:/srv/nfs/vgoncharuk/projects/prod/.moulin-domd-rootfs.tar.bz2", rootfs[1][-1])
        self.assertIn("sudo -n /usr/local/sbin/moulin-deploy-rootfs --check", rootfs[1][-1])
        self.assertIn("sudo -n /usr/local/sbin/moulin-deploy-rootfs --prepare /srv/nfs/vgoncharuk/projects/prod testrpi5", rootfs[1][-1])
        self.assertIn("sudo -n /usr/local/sbin/moulin-deploy-rootfs \"$dest\" \"$tarball\"", rootfs[1][-1])
        self.assertNotIn("sudo -n mkdir -p /srv/nfs/vgoncharuk/projects/prod", rootfs[1][-1])
        self.assertNotIn("MOULIN_STREAM_FILE", rootfs[1][-1])
        self.assertNotIn("pv not found", rootfs[1][-1])
        self.assertIn("android_only.img", android[0][-1])
        self.assertIn("rsync -azS", android[0][-1])
        self.assertIn("--inplace", android[0][-1])
        self.assertIn("--info=progress2", android[0][-1])
        self.assertIn("--stats", android[0][-1])
        self.assertIn("sudo -n /usr/local/sbin/moulin-deploy-rootfs --prepare-android /srv/nfs/vgoncharuk/projects/prod testrpi5", android[0][-1])
        self.assertIn("testrpi5@10.13.64.242:/srv/nfs/vgoncharuk/projects/prod/.moulin-android_only.img", android[0][-1])
        self.assertIn("sudo -n /usr/local/sbin/moulin-deploy-rootfs --install-android /srv/nfs/vgoncharuk/projects/prod /srv/nfs/vgoncharuk/projects/prod/.moulin-android_only.img", android[0][-1])
        self.assertNotIn("MOULIN_STREAM_FILE", android[0][-1])
        self.assertNotIn("cat >", android[0][-1])
        self.assertNotIn("pv not found", android[0][-1])
        self.assertIn("setenv serverip 10.13.64.242", uboot[0][-1])
        self.assertIn("setenv ipaddr 10.13.64.120", uboot[0][-1])
        self.assertIn("vgoncharuk/projects/current/Image", uboot[0][-1])
        self.assertIn("setenv tftp_configure_nfs", uboot[0][-1])
        self.assertIn("fdt set /boot_dev device_doma domd_rootfs", uboot[0][-1])
        self.assertIn("setenv tftp_initramfs_load", uboot[0][-1])
        self.assertIn("tftp 0x50000000 vgoncharuk/projects/current/uInitramfs", uboot[0][-1])
        self.assertIn("tftp 0x54000000 vgoncharuk/projects/current/r8a78000-ironhide-xen.dtb && fdt addr", uboot[0][-1])
        self.assertIn("setenv bootcmd_tftp", uboot[0][-1])
        self.assertIn("env delete bootargs; run tftp_xen_load", uboot[0][-1])
        self.assertNotIn("bootcmd_tftp 'run i2c_pci", uboot[0][-1])
        self.assertIn("run tftp_xen_load && run tftp_dtb_load && run tftp_kernel_load", uboot[0][-1])
        self.assertIn("run tftp_xenpolicy_load && run tftp_initramfs_load", uboot[0][-1])
        self.assertIn("bootm 0x54080000 0x50000000 0x54000000", uboot[0][-1])
        self.assertIn("setenv bootcmd", uboot[0][-1])
        self.assertIn("run bootcmd_tftp", uboot[0][-1])
        self.assertIn("bootcmd_ufs", ufs[0][-1])
        self.assertIn("saveenv", ufs[0][-1])

    def test_install_nfs_deploy_helper_is_interactive_board_setup(self) -> None:
        config = sample_copy_config()
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_board_host_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = self._service()

        actions = {action.action_id: action for action in service.board_actions(config)}
        helper = service.board_action_commands(config, "install_nfs_deploy_helper")

        self.assertTrue(actions["install_nfs_deploy_helper"].interactive)
        self.assertEqual(helper[0][0], "ssh")
        self.assertIn("-tt", helper[0])
        self.assertIn("testrpi5@10.13.64.242", helper[0])
        self.assertIn("/usr/local/sbin/moulin-deploy-rootfs", helper[0][-1])
        self.assertIn('if [ "$dest" = "--check" ]', helper[0][-1])
        self.assertIn('if [ "$dest" = "--prepare" ]', helper[0][-1])
        self.assertIn('if [ "$dest" = "--prepare-android" ]', helper[0][-1])
        self.assertIn('if [ "$dest" = "--install-android" ]', helper[0][-1])
        self.assertIn("android_only.img", helper[0][-1])
        self.assertIn("testrpi5 ALL=(root) NOPASSWD: /usr/local/sbin/moulin-deploy-rootfs", helper[0][-1])
        self.assertIn("visudo -cf /etc/sudoers.d/moulin-rootfs-deploy", helper[0][-1])

    def test_open_board_serial_console_runs_picocom_without_restart(self) -> None:
        config = sample_copy_config()
        config["board_hosts"][0]["console_device"] = "/dev/GEN5_CONSOLE_X5H"
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_board_host_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = self._service()

        commands = service.board_action_commands(config, "open_board_serial_console")

        self.assertEqual(commands[0][0], "ssh")
        self.assertIn("-tt", commands[0])
        self.assertIn("testrpi5@10.13.64.242", commands[0])
        self.assertNotIn("x5h_off", commands[0][-1])
        self.assertNotIn("x5h_boot", commands[0][-1])
        self.assertNotIn("x5h_on", commands[0][-1])
        self.assertIn("picocom -b 1843200", commands[0][-1])
        self.assertIn("/dev/GEN5_CONSOLE_X5H", commands[0][-1])

    def test_open_uboot_console_power_cycles_and_runs_picocom(self) -> None:
        config = sample_copy_config()
        config["board_hosts"][0]["console_device"] = "/dev/GEN5_CONSOLE_X5H"
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_board_host_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = self._service()

        commands = service.board_action_commands(config, "open_uboot_console")

        self.assertEqual(commands[0][0], "ssh")
        self.assertIn("-tt", commands[0])
        self.assertIn("testrpi5@10.13.64.242", commands[0])
        self.assertIn("x5h_off", commands[0][-1])
        self.assertIn("x5h_boot", commands[0][-1])
        self.assertIn("x5h_on", commands[0][-1])
        self.assertIn("picocom -b 1843200", commands[0][-1])
        self.assertIn("/dev/GEN5_CONSOLE_X5H", commands[0][-1])

    def test_network_workspace_commands_sync_local_workspace(self) -> None:
        config = sample_copy_config()
        config["board_hosts"][0].update({"deploy_subdir": "vgoncharuk/projects"})
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_board_host_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = self._service()

        pull = service.board_action_commands(config, "pull_network_workspace")
        push = service.board_action_commands(config, "push_network_workspace")

        self.assertIn("/tmp/app/workspace/board-network/prod/tftp", pull[0][2])
        self.assertEqual(pull[1][0], "rsync")
        self.assertIn("testrpi5@10.13.64.242:/srv/tftp/vgoncharuk/projects/prod/", pull[1])
        self.assertEqual(push[1][0], "rsync")
        self.assertIn("--delete", push[1])

    def test_dom0_initramfs_workspace_commands_unpack_and_repack(self) -> None:
        config = sample_copy_config()
        config["board_hosts"][0].update({"deploy_subdir": "vgoncharuk/projects"})
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_board_host_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = self._service()

        pull = service.board_action_commands(config, "pull_dom0_initramfs_workspace")
        push = service.board_action_commands(config, "push_dom0_initramfs_workspace")

        self.assertIn("uInitramfs", pull[0][2])
        self.assertIn("/tmp/app/workspace/board-network/prod/dom0-initramfs/rootfs", pull[0][-1])
        self.assertIn("testrpi5@10.13.64.242:/srv/tftp/vgoncharuk/projects/prod/uInitramfs", pull[1])
        self.assertIn("dumpimage", pull[2][-1])
        self.assertIn("find \"$rootfs\" -mindepth 1 -maxdepth 1", pull[2][-1])
        self.assertIn("cpio -idmu", pull[2][-1])
        self.assertIn("mkimage", push[0][-1])
        self.assertIn("cpio --null -o --format=newc", push[0][-1])
        self.assertIn("/tmp/app/workspace/board-network/prod/dom0-initramfs/uInitramfs", push[2])
        self.assertIn("testrpi5@10.13.64.242:/srv/tftp/vgoncharuk/projects/prod/uInitramfs", push[2])

    def test_flash_services_match_command_builders(self) -> None:
        config = sample_config()
        config_profiles.normalize_board_host_profiles(config)
        service = self._service()

        bootloaders = service.flash_bootloaders_commands(config)
        ufs = service.flash_ufs_image_commands(config)
        restart = service.board_action_commands(config, "restart_board")

        self.assertEqual(len(bootloaders), 6)
        self.assertIn("x5h_flash", bootloaders[2][-1])
        self.assertIn("python3 -u ./flash_bootloaders.py", bootloaders[5][-1])
        self.assertEqual(len(ufs), 4)
        self.assertIn("gen5_x5h_flash_ufs.py", ufs[2][-1])
        self.assertIn("x5h_boot", ufs[3][-1])
        self.assertIn("python3 /srv/tftp/vgon/gen5_x5h_flash_ufs.py", ufs[3][-1])
        self.assertEqual(restart[0][0], "ssh")
        self.assertIn("-tt", restart[0])
        self.assertIn("bash -lic", restart[0][-1])
        self.assertIn("x5h_off", restart[0][-1])
        self.assertIn("x5h_boot", restart[0][-1])
        self.assertIn("x5h_on", restart[0][-1])

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
