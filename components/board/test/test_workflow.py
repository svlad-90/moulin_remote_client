from __future__ import annotations

import gzip
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

import moulin_remote_client as client
from components.board.api import workflow
from components.board_types.api.base import BoardCapability
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
            transport.ssh_command("board@192.0.2.10", "printf 'ssh=ok\\n'; uname -a | sed 's/^/target=/'"),
        )
        self.assertEqual(
            service.interactive_shell_command_for_config(config),
            transport.ssh_command("board@192.0.2.10", tty="-t"),
        )
        self.assertEqual(
            service.run_interactive_shell(config, lambda argv: calls.append(argv) or 23),
            23,
        )
        self.assertEqual(calls, [transport.ssh_command("board@192.0.2.10", tty="-t")])

    def test_interactive_shell_service_matches_command_builder(self) -> None:
        config = sample_config()
        config_profiles.normalize_board_host_profiles(config)
        service = self._service()

        self.assertEqual(
            service.connect_command(config),
            transport.ssh_command("board@192.0.2.10", "printf 'ssh=ok\\n'; uname -a | sed 's/^/target=/'"),
        )
        self.assertEqual(
            service.interactive_shell_command(config),
            transport.ssh_command("board@192.0.2.10", tty="-t"),
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
        self.assertEqual(len(argv), 3)
        self.assertIn('--prepare', argv[-1][-1])
        self.assertIn('.moulin-ipls', argv[-1][-1])

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

    def test_copy_local_artifact_streams_to_board_artifacts_directory(self) -> None:
        config = sample_config()
        config_profiles.normalize_board_host_profiles(config)
        service = self._service()
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "downloaded.img.gz"
            source.write_bytes(b"image")

            commands = service.copy_local_artifact_commands(
                config,
                source=source,
                destination_name="full_ufs.img.gz",
                remove_patterns=("full_ufs.img.gz",),
            )

        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][:2], ["python3", "-c"])
        self.assertEqual(commands[0][3], str(source))
        self.assertEqual(commands[0][4], "board@192.0.2.10")
        self.assertIn("progress:", commands[0][2])
        self.assertIn("/srv/tftp/demo/artifacts/full_ufs.img.gz", commands[0][5])
        self.assertIn("-name full_ufs.img.gz", commands[0][5])

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
                "flash_single_ipl",
                "flash_ufs_image",
                "restart_board",
                "open_board_serial_console",
                "open_uboot_console",
                "turn_off_board",
                "deploy_network_boot",
                "deploy_network_domd_rootfs",
                "deploy_network_domu_rootfs",
                "deploy_network_android",
                "unpack_network_android",
                "deploy_network_full",
                "install_nfs_deploy_helper",
                "pull_network_workspace",
                "push_network_workspace",
                "pull_dom0_initramfs_workspace",
                "push_dom0_initramfs_workspace",
                "apply_uboot_network_env",
                "apply_uboot_ufs_env",
                "inject_invasive_uboot_parameters",
            ],
        )
        self.assertEqual(
            [action.label for action in actions[:6]],
            [
                "Open board host shell",
                "Copy build artifacts",
                "Flash bootloaders (flash mode) from build host",
                "Flash bootloaders from build host",
                "Flash UFS image from build host",
                "Restart board",
            ],
        )
        self.assertTrue(next(action for action in actions if action.action_id == "open_board_host_shell").interactive)
        self.assertTrue(next(action for action in actions if action.action_id == "open_board_serial_console").interactive)
        self.assertTrue(next(action for action in actions if action.action_id == "open_board_serial_console").allow_during_job)
        self.assertTrue(next(action for action in actions if action.action_id == "open_uboot_console").interactive)
        self.assertTrue(next(action for action in actions if action.action_id == "open_uboot_console").allow_during_job)

    def test_board_power_off_and_restart_use_configured_commands(self) -> None:
        config = sample_config()
        config["board_hosts"][0]["commands"] = {
            "power_off": "relayctl off slot-2",
            "boot_mode": "relayctl normal slot-2",
        }
        config_profiles.normalize_board_host_profiles(config)
        service = self._service()

        power_off = service.board_action_commands(config, "turn_off_board")
        restart = service.board_action_commands(config, "restart_board")

        self.assertEqual(len(power_off), 1)
        self.assertIn("relayctl off slot-2", power_off[0][-1])
        self.assertIn("relayctl normal slot-2", restart[-1][-1])

    def test_board_ownership_actions_run_opaque_configured_commands(self) -> None:
        config = sample_config()
        config["board_hosts"][0]["commands"] = {
            "ownership_acquire": ". /etc/profile.d/labgrid-native.sh; labgrid-client -p ironhide-2 acquire",
            "ownership_release": ". /etc/profile.d/labgrid-native.sh; labgrid-client -p ironhide-2 release",
            "ownership_status": "labctl --board ironhide-2 status",
        }
        config_profiles.normalize_board_host_profiles(config)
        service = self._service()

        actions = service.board_actions(config)
        acquire = service.board_action_commands(config, "ownership_acquire")
        release = service.board_action_commands(config, "ownership_release")
        status = service.board_action_commands(config, "ownership_status")

        self.assertEqual(
            [action.action_id for action in actions[1:3]],
            ["ownership_acquire", "ownership_release"],
        )
        self.assertNotIn("ownership_status", [action.action_id for action in actions])
        self.assertIn("labgrid-client -p ironhide-2 acquire", acquire[0][-1])
        self.assertIn("labgrid-client -p ironhide-2 release", release[0][-1])
        self.assertIn("labctl --board ironhide-2 status", status[0][-1])

    def test_network_deploy_commands_use_project_tftp_nfs_paths(self) -> None:
        config = sample_copy_config()
        config["board_hosts"][0].update(
            {
                "tftp_root": "/srv/tftp",
                "nfs_root": "/srv/nfs",
                "deploy_subdir": "demo/projects",
                "server_ip": "192.0.2.10",
                "board_ip": "192.0.2.20",
            }
        )
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_board_host_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = self._service()

        boot = service.board_action_commands(config, "deploy_network_boot")
        rootfs = service.board_action_commands(config, "deploy_network_domd_rootfs")
        domu_rootfs = service.board_action_commands(config, "deploy_network_domu_rootfs")
        android = service.board_action_commands(config, "deploy_network_android")
        uboot = service.board_action_commands(config, "apply_uboot_network_env")
        ufs = service.board_action_commands(config, "apply_uboot_ufs_env")

        self.assertEqual("ssh", boot[0][0])
        self.assertIn("builder@10.0.0.1", boot[0])
        self.assertIn("/srv/tftp/demo/projects/prod", boot[0][-1])
        self.assertIn("board@192.0.2.10", boot[0][-1])
        self.assertIn("rsync -az", boot[0][-1])
        self.assertIn("--info=progress2", boot[0][-1])
        self.assertIn("--stats", boot[0][-1])
        self.assertIn("board@192.0.2.10:/srv/tftp/demo/projects/prod/", boot[0][-1])
        self.assertNotIn("MOULIN_STREAM_FILE", boot[0][-1])
        self.assertNotIn("pv not found", boot[0][-1])
        self.assertIn("/srv/nfs/demo/projects/prod", rootfs[1][-1])
        self.assertIn("rcar-image-adas", rootfs[0][-1])
        self.assertIn("rcar-image-adas", rootfs[1][-1])
        self.assertIn("rsync -az", rootfs[1][-1])
        self.assertIn("--info=progress2", rootfs[1][-1])
        self.assertIn("--stats", rootfs[1][-1])
        self.assertIn("board@192.0.2.10:/srv/nfs/demo/projects/prod/rootfs/domd/.moulin-domd-rootfs.tar.bz2", rootfs[1][-1])
        self.assertIn("sudo -n /usr/local/sbin/moulin-deploy-rootfs --check", rootfs[1][-1])
        self.assertIn("sudo -n /usr/local/sbin/moulin-deploy-rootfs --prepare /srv/nfs/demo/projects/prod/rootfs/domd board", rootfs[1][-1])
        self.assertIn("sudo -n /usr/local/sbin/moulin-deploy-rootfs \"$dest\" \"$tarball\"", rootfs[1][-1])
        self.assertIn("sudo -n /usr/local/sbin/moulin-deploy-rootfs --refresh-current /srv/nfs/demo/projects /srv/nfs/demo/projects/current prod", rootfs[1][-1])
        self.assertNotIn("ln -sfn prod /srv/nfs/demo/projects/current", rootfs[1][-1])
        self.assertNotIn("sudo -n mkdir -p /srv/nfs/demo/projects/prod", rootfs[1][-1])
        self.assertNotIn("MOULIN_STREAM_FILE", rootfs[1][-1])
        self.assertNotIn("pv not found", rootfs[1][-1])
        self.assertIn("/srv/nfs/demo/projects/prod", domu_rootfs[1][-1])
        self.assertIn("yocto/build-domu/tmp/deploy/images", domu_rootfs[0][-1])
        self.assertIn("yocto/build-domu/tmp/deploy/images", domu_rootfs[1][-1])
        self.assertIn("Deploy DomU NFS rootfs", domu_rootfs[1][-1])
        self.assertIn("Installing DomU rootfs on board host", domu_rootfs[1][-1])
        self.assertIn("board@192.0.2.10:/srv/nfs/demo/projects/prod/rootfs/domu/.moulin-domu-rootfs.tar.bz2", domu_rootfs[1][-1])
        self.assertIn("android_only.img.gz", android[0][-1])
        self.assertIn("rsync -az", android[0][-1])
        self.assertNotIn("rsync -azS", android[0][-1])
        self.assertIn("--inplace", android[0][-1])
        self.assertIn("--info=progress2", android[0][-1])
        self.assertIn("--stats", android[0][-1])
        self.assertIn("sudo -n /usr/local/sbin/moulin-deploy-rootfs --prepare-android /srv/nfs/demo/projects/prod board", android[0][-1])
        self.assertIn("board@192.0.2.10:/srv/nfs/demo/projects/prod/.moulin-android_only.img.gz", android[0][-1])
        self.assertIn("sudo -n /usr/local/sbin/moulin-deploy-rootfs --install-android /srv/nfs/demo/projects/prod /srv/nfs/demo/projects/prod/.moulin-android_only.img.gz", android[0][-1])
        self.assertIn("sudo -n /usr/local/sbin/moulin-deploy-rootfs --refresh-current /srv/nfs/demo/projects /srv/nfs/demo/projects/current prod", android[0][-1])
        self.assertNotIn("MOULIN_STREAM_FILE", android[0][-1])
        self.assertNotIn("cat >", android[0][-1])
        self.assertNotIn("pv not found", android[0][-1])
        invasive = service.board_action_commands(config, "inject_invasive_uboot_parameters")
        self.assertIn("setenv serverip 192.0.2.10", invasive[-1][-1])
        self.assertIn("setenv ipaddr 192.0.2.20", invasive[-1][-1])
        self.assertNotIn("setenv ethaddr", invasive[-1][-1])
        self.assertIn("cat > /srv/tftp/demo/projects/prod/env/uboot.env", uboot[0][-1])
        self.assertIn("ln -sfn prod /srv/tftp/demo/projects/current", uboot[0][-1])
        self.assertNotIn("mkdir -p /srv/nfs/demo/projects", uboot[0][-1])
        self.assertNotIn("ln -sfn prod /srv/nfs/demo/projects/current", uboot[0][-1])
        self.assertIn("demo/projects/current/Image", uboot[0][-1])
        self.assertIn("tftp_configure_nfs=", uboot[0][-1])
        self.assertIn("nfs_domd_dir=/srv/nfs/demo/projects/current/rootfs/domd", uboot[0][-1])
        self.assertIn("fdt set /boot_dev device_doma domd_rootfs", uboot[0][-1])
        self.assertIn("fdt set /boot_dev nfs_dir $nfs_domd_dir", uboot[0][-1])
        self.assertNotIn("device_domu", uboot[0][-1])
        self.assertNotIn("nfs_dir_domu", uboot[0][-1])
        self.assertNotIn("guest_domains", uboot[0][-1])
        self.assertIn("tftp_initramfs_load=", uboot[0][-1])
        self.assertIn("tftp 0x50000000 demo/projects/current/uInitramfs", uboot[0][-1])
        self.assertIn("tftp 0x54000000 demo/projects/current/r8a78000-ironhide-xen.dtb && fdt addr", uboot[0][-1])
        self.assertIn("bootcmd_moulin=", uboot[0][-1])
        self.assertIn("env delete bootargs; run tftp_xen_load", uboot[0][-1])
        self.assertIn("run tftp_xen_load && run tftp_dtb_load && run tftp_kernel_load", uboot[0][-1])
        self.assertIn("run tftp_xenpolicy_load && run tftp_initramfs_load", uboot[0][-1])
        self.assertIn("bootm 0x54080000 0x50000000 0x54000000", uboot[0][-1])
        self.assertIn("setenv user_demo", uboot[-1][-1])
        self.assertIn("env import -t ${loadaddr} ${filesize}; run bootcmd_moulin", uboot[-1][-1])
        self.assertNotIn("setenv bootcmd", uboot[-1][-1])
        self.assertIn("--boot-mode-command x5h_boot", ufs[-1][-1])
        self.assertIn("--port", ufs[-1][-1])
        self.assertNotIn("--power-off-command", ufs[-1][-1])
        self.assertNotIn("--power-on-command", ufs[-1][-1])
        self.assertIn("ufs_dtb_load=", ufs[0][-1])
        self.assertIn("ufs_initramfs_load=", ufs[0][-1])
        self.assertIn("ufs_kernel_load=", ufs[0][-1])
        self.assertIn("ufs_xen_load=", ufs[0][-1])
        self.assertIn("ufs_xenpolicy_load=", ufs[0][-1])
        self.assertIn("bootcmd_moulin=", ufs[0][-1])
        self.assertIn("setenv user_demo", ufs[-1][-1])
        self.assertIn("--verify-variable user_demo", ufs[-1][-1])
        self.assertIn("saveenv", ufs[-1][-1])
        self.assertNotIn("The board must be stopped at the U-Boot prompt", ufs[0][-1])

    def test_android_unpack_uses_existing_board_archive_without_upload(self) -> None:
        config = sample_copy_config()
        config["board_hosts"][0].update(
            {"nfs_root": "/srv/nfs", "deploy_subdir": "demo/projects"}
        )
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_board_host_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = self._service()

        commands = service.board_action_commands(config, "unpack_network_android")

        self.assertEqual(len(commands), 1)
        self.assertIn("board@192.0.2.10", commands[0])
        self.assertNotIn("builder@10.0.0.1", commands[0])
        self.assertNotIn("rsync", commands[0][-1])
        self.assertIn(
            "--install-android /srv/nfs/demo/projects/prod "
            "/srv/nfs/demo/projects/prod/.moulin-android_only.img.gz",
            commands[0][-1],
        )
        self.assertIn("--refresh-current", commands[0][-1])
        action = next(
            action for action in service.board_actions(config)
            if action.action_id == "unpack_network_android"
        )
        self.assertFalse(action.requires_remote)

    def test_android_helper_retains_archive_for_repeated_unpack(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            nfs = root / "nfs"
            dest = nfs / "project"
            domd = dest / "rootfs" / "domd"
            domd.mkdir(parents=True)
            archive = dest / ".moulin-android_only.img.gz"
            payload = b"android image data"
            archive.write_bytes(gzip.compress(payload))
            helper = root / "helper.sh"
            adapter = self._service().board_type_registry.adapter_for_type("gen5_x5h")
            helper.write_text(
                adapter.nfs_deploy_helper_script().replace("/srv/nfs", str(nfs)),
                encoding="utf-8",
            )
            tools = root / "bin"
            tools.mkdir()
            chown = tools / "chown"
            chown.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            chown.chmod(0o755)
            env = {**os.environ, "PATH": f"{tools}:{os.environ['PATH']}"}

            for _ in range(2):
                (dest / "android_only.img").write_bytes(b"stale image")
                subprocess.run(
                    ["sh", str(helper), "--install-android", str(dest), str(archive)],
                    env=env,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                self.assertTrue(archive.is_file())
                self.assertEqual((dest / "android_only.img").read_bytes(), payload)
                self.assertEqual((domd / "android_only.img").read_bytes(), payload)

    def test_full_network_deploy_uses_active_artifact_targets(self) -> None:
        config = sample_copy_config()
        config["board_hosts"][0].update(
            {
                "tftp_root": "/srv/tftp",
                "nfs_root": "/srv/nfs",
                "deploy_subdir": "demo/projects",
            }
        )
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_board_host_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = self._service()

        commands = service.board_action_commands(
            config,
            "deploy_network_full",
            artifact_targets="boot_artifacts domd domu",
        )
        script = "\n".join(command[-1] for command in commands)

        self.assertIn("Deploy TFTP boot artifacts", script)
        self.assertIn("Deploy DomD NFS rootfs", script)
        self.assertIn("Deploy DomU NFS rootfs", script)
        self.assertNotIn("Deploy Android image to NFS", script)
        self.assertNotIn("android_only.img", script)

    def test_full_network_deploy_uses_active_manifest_domains(self) -> None:
        config = sample_copy_config()
        config["board_hosts"][0].update(
            {
                "tftp_root": "/srv/tftp",
                "nfs_root": "/srv/nfs",
                "deploy_subdir": "demo/projects",
            }
        )
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_board_host_profiles(config)
        config_profiles.normalize_project_profiles(config)
        manifest_text = "\n".join(
            [
                "min_ver: '1.0'",
                "components:",
                "  boot_artifacts:",
                "    builder:",
                "      type: custom_script",
                "  domd:",
                "    builder:",
                "      type: yocto",
                "      build_target: rcar-image-adas",
                "  domu:",
                "    builder:",
                "      type: yocto",
                "      build_target: domu-image",
                "  doma:",
                "    builder:",
                "      type: android",
            ]
        )
        service = self._service(remote_read_project_file=lambda _config, _path: manifest_text)

        commands = service.board_action_commands(
            config,
            "deploy_network_full",
            artifact_targets="boot_artifacts domd domu doma",
            build_params={"ENABLE_ANDROID": "no"},
        )
        script = "\n".join(command[-1] for command in commands)

        self.assertIn("Deploy TFTP boot artifacts", script)
        self.assertIn("Deploy DomD NFS rootfs", script)
        self.assertIn("Deploy DomU NFS rootfs", script)
        self.assertNotIn("Deploy Android image to NFS", script)

    def test_uboot_network_env_uses_manifest_yocto_guest_domains(self) -> None:
        config = sample_copy_config()
        config["board_hosts"][0].update(
            {
                "tftp_root": "/srv/tftp",
                "nfs_root": "/srv/nfs",
                "deploy_subdir": "demo/projects",
                "server_ip": "192.0.2.10",
                "board_ip": "192.0.2.20",
            }
        )
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_board_host_profiles(config)
        config_profiles.normalize_project_profiles(config)
        manifest_text = "\n".join(
            [
                "min_ver: '1.0'",
                "components:",
                "  dom0:",
                "    builder:",
                "      type: yocto",
                "      build_target: core-image-thin-initramfs",
                "  domd:",
                "    builder:",
                "      type: yocto",
                "      build_target: rcar-image-adas",
                "  domu:",
                "    builder:",
                "      type: yocto",
                "      build_target: rcar-image-adas",
                "  doma:",
                "    builder:",
                "      type: android",
            ]
        )
        service = self._service(remote_read_project_file=lambda _config, _path: manifest_text)

        uboot = service.board_action_commands(config, "apply_uboot_network_env", build_params={"ENABLE_DOMU": "yes"})

        self.assertIn("nfs_domd_dir=/srv/nfs/demo/projects/current/rootfs/domd", uboot[0][-1])
        self.assertIn("nfs_domu_dir=/srv/nfs/demo/projects/current/rootfs/domu", uboot[0][-1])
        self.assertIn("fdt set /boot_dev nfs_dir $nfs_domd_dir", uboot[0][-1])
        self.assertIn("fdt set /boot_dev device_domu nfs", uboot[0][-1])
        self.assertIn("fdt set /boot_dev nfs_dir_domu $nfs_domu_dir", uboot[0][-1])
        self.assertIn("fdt set /boot_dev device_doma domd_rootfs", uboot[0][-1])
        self.assertNotIn("guest_domains", uboot[0][-1])

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
        self.assertIn("board@192.0.2.10", helper[0])
        self.assertIn("/usr/local/sbin/moulin-deploy-rootfs", helper[0][-1])
        self.assertIn('if [ "$dest" = "--check" ]', helper[0][-1])
        self.assertIn('if [ "$dest" = "--prepare" ]', helper[0][-1])
        self.assertIn('if [ "$dest" = "--prepare-android" ]', helper[0][-1])
        self.assertIn('if [ "$dest" = "--refresh-current" ]', helper[0][-1])
        self.assertIn('if [ "$dest" = "--install-android" ]', helper[0][-1])
        self.assertIn('.moulin-domd-rootfs.tar.bz2', helper[0][-1])
        self.assertIn('.moulin-domu-rootfs.tar.bz2', helper[0][-1])
        self.assertIn(".moulin-*-rootfs.tar.bz2", helper[0][-1])
        self.assertIn("gzip -dc", helper[0][-1])
        self.assertIn("rootfs/domd/android_only.img", helper[0][-1])
        self.assertIn("linked DomD /android_only.img", helper[0][-1])
        self.assertIn("android_only.img", helper[0][-1])
        self.assertIn("board ALL=(root) NOPASSWD: /usr/local/sbin/moulin-deploy-rootfs", helper[0][-1])
        self.assertIn("visudo -cf /etc/sudoers.d/moulin-rootfs-deploy", helper[0][-1])

    def test_open_board_serial_console_runs_managed_bridge_without_restart(self) -> None:
        config = sample_copy_config()
        config["board_hosts"][0]["console_device"] = "socket://127.0.0.1:36511"
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_board_host_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = self._service()

        commands = service.board_action_commands(config, "open_board_serial_console")

        self.assertEqual(len(commands), 1)
        self.assertIn("serial.serial_for_url", commands[0][-1])
        self.assertEqual(commands[-1][0], "ssh")
        self.assertIn("-tt", commands[-1])
        self.assertIn("board@192.0.2.10", commands[-1])
        self.assertNotIn("x5h_boot", commands[-1][-1])
        self.assertIn("--device socket://127.0.0.1:36511", commands[-1][-1])
        self.assertIn("managed serial endpoint socket://127.0.0.1:36511", commands[-1][-1])

    def test_open_board_serial_console_runs_configured_command_without_bridge(self) -> None:
        config = sample_copy_config()
        console_command = (
            "labgrid-client -c /etc/labgrid-native/users/$(id -u)/ironhide-1.yaml "
            "-p ironhide-1 console main"
        )
        config["board_hosts"][0]["commands"] = {"console": console_command}
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_board_host_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = self._service()

        commands = service.board_action_commands(config, "open_board_serial_console")

        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][0], "ssh")
        self.assertIn("-tt", commands[0])
        self.assertIn(console_command, commands[0][-1])
        self.assertNotIn("serial_console_bridge.py", commands[0][-1])
        self.assertNotIn("serial-console-bridge-", commands[0][-1])

    def test_open_uboot_console_runs_mode_transition_and_managed_bridge(self) -> None:
        config = sample_copy_config()
        config["board_hosts"][0]["console_device"] = "/dev/GEN5_CONSOLE_X5H"
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_board_host_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = self._service()

        commands = service.board_action_commands(config, "open_uboot_console")

        self.assertEqual(len(commands), 1)
        self.assertIn("serial.serial_for_url", commands[0][-1])
        self.assertEqual(commands[-1][0], "ssh")
        self.assertIn("-tt", commands[-1])
        self.assertIn("board@192.0.2.10", commands[-1])
        self.assertIn("x5h_boot", commands[-1][-1])
        self.assertIn("--device /dev/GEN5_CONSOLE_X5H", commands[-1][-1])
        self.assertIn("managed serial endpoint /dev/GEN5_CONSOLE_X5H", commands[-1][-1])

    def test_network_workspace_commands_sync_local_workspace(self) -> None:
        config = sample_copy_config()
        config["board_hosts"][0].update({"deploy_subdir": "demo/projects"})
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_board_host_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = self._service()

        pull = service.board_action_commands(config, "pull_network_workspace")
        push = service.board_action_commands(config, "push_network_workspace")

        self.assertIn("/tmp/app/workspace/board-network/prod/tftp", pull[0][2])
        self.assertEqual(pull[1][0], "rsync")
        self.assertIn("board@192.0.2.10:/srv/tftp/demo/projects/prod/", pull[1])
        self.assertEqual(push[1][0], "rsync")
        self.assertIn("--delete", push[1])
        self.assertIn("sudo -n /usr/local/sbin/moulin-deploy-rootfs --prepare /srv/nfs/demo/projects/prod board", push[0][-1])
        self.assertIn("sudo -n /usr/local/sbin/moulin-deploy-rootfs --refresh-current /srv/nfs/demo/projects /srv/nfs/demo/projects/current prod", push[0][-1])
        self.assertNotIn("mkdir -p /srv/tftp/demo/projects/prod /srv/nfs/demo/projects/prod", push[0][-1])

    def test_dom0_initramfs_workspace_commands_unpack_and_repack(self) -> None:
        config = sample_copy_config()
        config["board_hosts"][0].update({"deploy_subdir": "demo/projects"})
        config_profiles.normalize_remote_profiles(config)
        config_profiles.normalize_board_host_profiles(config)
        config_profiles.normalize_project_profiles(config)
        service = self._service()

        pull = service.board_action_commands(config, "pull_dom0_initramfs_workspace")
        push = service.board_action_commands(config, "push_dom0_initramfs_workspace")

        self.assertIn("uInitramfs", pull[0][2])
        self.assertIn("/tmp/app/workspace/board-network/prod/dom0-initramfs/rootfs", pull[0][-1])
        self.assertIn("board@192.0.2.10:/srv/tftp/demo/projects/prod/uInitramfs", pull[1])
        self.assertIn("dumpimage", pull[2][-1])
        self.assertIn("find \"$rootfs\" -mindepth 1 -maxdepth 1", pull[2][-1])
        self.assertIn("cpio -idmu", pull[2][-1])
        self.assertIn("mkimage", push[0][-1])
        self.assertIn("cpio --null -o --format=newc", push[0][-1])
        self.assertIn("/tmp/app/workspace/board-network/prod/dom0-initramfs/uInitramfs", push[2])
        self.assertIn("board@192.0.2.10:/srv/tftp/demo/projects/prod/uInitramfs", push[2])

    def test_gen5_board_type_builds_flash_commands_and_capabilities(self) -> None:
        config = sample_config()
        config_profiles.normalize_board_host_profiles(config)
        service = self._service()

        bootloaders = service.flash_bootloaders_commands(config)
        ufs = service.flash_ufs_image_commands(config)
        reflash = service.board_operation_plan(config, BoardCapability.REFLASH)
        bootloader_reflash = service.board_operation_plan(config, BoardCapability.REFLASH_BOOTLOADERS)
        reboot = service.board_operation_plan(config, BoardCapability.REBOOT)
        restart = service.board_action_commands(config, "restart_board")

        self.assertEqual(len(bootloaders), 6)
        self.assertIn("x5h_flash", bootloaders[2][-1])
        self.assertIn("python3 -u ./flash_bootloaders.py", bootloaders[5][-1])
        self.assertIn('PYTHONUNBUFFERED=1 python3 -u ./flash_bootloaders.py --port "$console"', bootloaders[5][-1])
        self.assertEqual(len(ufs), 4)
        self.assertEqual(
            service.board_capabilities(config),
            frozenset({BoardCapability.REBOOT, BoardCapability.REFLASH, BoardCapability.REFLASH_BOOTLOADERS}),
        )
        self.assertIsNotNone(reboot)
        self.assertEqual(reboot.capability, BoardCapability.REBOOT)
        self.assertEqual(reboot.build_targets, ())
        self.assertEqual(reboot.provision_commands, ())
        self.assertEqual(reboot.execute_commands, tuple(tuple(command) for command in restart))
        self.assertIsNotNone(reflash)
        self.assertEqual(reflash.capability, BoardCapability.REFLASH)
        self.assertEqual(reflash.build_targets, ("full_ufs.img.gz",))
        self.assertEqual(reflash.execute_commands, (tuple(ufs[-1]),))
        self.assertEqual(reflash.provision_commands[-3:], tuple(tuple(command) for command in ufs[:-1]))
        self.assertIsNotNone(bootloader_reflash)
        self.assertEqual(bootloader_reflash.capability, BoardCapability.REFLASH_BOOTLOADERS)
        self.assertEqual(bootloader_reflash.build_targets, ("boot_artifacts",))
        self.assertEqual(
            bootloader_reflash.execute_commands,
            (tuple(bootloaders[2]), tuple(bootloaders[5])),
        )
        self.assertEqual(
            bootloader_reflash.provision_commands[-4:],
            tuple(tuple(command) for command in (bootloaders[0], bootloaders[1], bootloaders[3], bootloaders[4])),
        )
        self.assertIn("gen5_x5h_flash_ufs.py", ufs[2][-1])
        self.assertIn("x5h_boot", ufs[3][-1])
        self.assertIn("python3 /srv/tftp/demo/gen5_x5h_flash_ufs.py", ufs[3][-1])
        self.assertEqual(restart[-1][0], "ssh")
        self.assertIn("-tt", restart[-1])
        self.assertIn("bash -lic", restart[-1][-1])
        self.assertIn("x5h_boot", restart[-1][-1])
        self.assertIn("--port", restart[-1][-1])
        self.assertNotIn("--console-command", restart[-1][-1])
        self.assertIn("Restart board and run Moulin U-Boot action", restart[-1][-1])
        self.assertIn("--require-variable user_default", restart[-1][-1])
        self.assertIn("user_default", restart[-1][-1])
        self.assertIn("run user_default", restart[-1][-1])
        self.assertIn("Apply U-Boot network env or Apply U-Boot UFS env first", restart[-1][-1])

    def test_flash_bootloaders_uses_configured_console_device(self) -> None:
        config = sample_config()
        config["board_hosts"][0]["console_device"] = "/dev/GEN5_CONSOLE2"
        config_profiles.normalize_board_host_profiles(config)
        service = self._service()

        bootloaders = service.flash_bootloaders_commands(config)
        script = bootloaders[5][-1]

        self.assertIn("console=/dev/GEN5_CONSOLE2", script)
        self.assertIn('PYTHONUNBUFFERED=1 python3 -u ./flash_bootloaders.py --port "$console"', script)
        self.assertNotIn("--port /dev/GEN5_CONSOLE --config", script)

    def test_board_host_command_overrides_replace_board_type_defaults(self) -> None:
        config = sample_config()
        config["board_hosts"][0]["commands"] = {
            "power_off": "relayctl off",
            "power_on": "relayctl on",
            "boot_mode": "relayctl boot",
            "flash_mode": "relayctl flash",
        }
        config_profiles.normalize_board_host_profiles(config)
        service = self._service()

        bootloaders = service.flash_bootloaders_commands(config)
        ufs = service.flash_ufs_image_commands(config)
        restart = service.board_action_commands(config, "restart_board")

        self.assertIn("relayctl flash", bootloaders[2][-1])
        self.assertIn("relayctl boot", bootloaders[5][-1])
        self.assertIn("gen5_x5h_flash_ufs.py", ufs[2][-1])
        self.assertIn("python3 /srv/tftp/demo/gen5_x5h_flash_ufs.py", ufs[3][-1])
        self.assertIn("relayctl boot", restart[-1][-1])
        self.assertIn("--require-variable user_default", restart[-1][-1])
        self.assertIn("user_default", restart[-1][-1])
        self.assertNotIn("x5h_flash", bootloaders[2][-1])
        self.assertNotIn("x5h_off", restart[-1][-1])

    def test_workflow_runs_flash_scenarios_with_titles(self) -> None:
        config = sample_config()
        config_profiles.normalize_board_host_profiles(config)
        service = self._service()
        calls: list[tuple[str, list[list[str]]]] = []

        service.run_flash_bootloaders(config, runner=lambda title, commands: calls.append((title, commands)))
        service.run_flash_ufs_image(config, runner=lambda title, commands: calls.append((title, commands)))

        self.assertEqual(
            [title for title, _commands in calls],
            ["Flash bootloaders (flash mode) from build host", "Flash UFS image from build host"],
        )
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
