from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from components.build_runtime.api import runtime as runtime_api
from components.main_menu.api import items


class FakeWorkflow:
    def __init__(self) -> None:
        self.build_calls: list[dict[str, Any]] = []
        self.command_calls: list[tuple[str, list[list[str]]]] = []

    def run_build_command(self, _port: Any, title: str, command: list[str], **kwargs: Any) -> int:
        self.build_calls.append({"title": title, "command": command, **kwargs})
        return 0

    def run_commands(self, _port: Any, title: str, commands: list[list[str]]) -> int:
        self.command_calls.append((title, commands))
        return 0


class FakeTerminalSession:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.commands: list[list[str]] = []

    def open_remote_shell(self, _port: Any) -> None:
        self.calls.append("remote")

    def open_board_shell(self, _port: Any) -> None:
        self.calls.append("board")

    def open_local_directory_shell(self, _port: Any, title: str, _path: Path) -> None:
        self.calls.append(f"local:{title}")

    def open_build_host_directory_shell(self, _port: Any, title: str, _path: str) -> None:
        self.calls.append(f"build-dir:{title}")

    def open_board_host_directory_shell(self, _port: Any, title: str, _path: str) -> None:
        self.calls.append(f"board-dir:{title}")

    def open_command_shell(self, _port: Any, title: str, _details: list[str], command: list[str]) -> None:
        self.calls.append(f"command:{title}")
        self.commands.append(command)


class FakeConfigWorkflow:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run_remote_configurations_screen(self, _port: Any) -> None:
        self.calls.append("remote")

    def select_active_remote(self, _port: Any) -> None:
        self.calls.append("select-remote")

    def run_board_host_configurations_screen(self, _port: Any) -> None:
        self.calls.append("board")

    def select_active_board_host(self, _port: Any) -> None:
        self.calls.append("select-board")

    def run_project_configurations_screen(self, _port: Any) -> None:
        self.calls.append("project")

    def select_build_targets(self, _port: Any) -> None:
        self.calls.append("targets")


class FakeDialogWorkflow:
    def __init__(self) -> None:
        self.confirm_calls: list[Any] = []
        self.confirm_result = True
        self.confirm_results: list[bool] = []

    def run_confirm_dialog(self, _port: Any, content: Any, **_kwargs: Any) -> bool:
        self.confirm_calls.append(content)
        if self.confirm_results:
            return self.confirm_results.pop(0)
        return self.confirm_result


class FakeApp:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.preflight_values: dict[str, str] = {}
        self.connection_state = "connected"
        self.board_connection_state = "connected"
        self.docker_image = "demo-image"
        self.build_params = {"ENABLE_ANDROID": "yes"}
        self.build_targets = "full_ufs.img.gz"
        self.board_artifacts = "full_ufs.img.gz"
        self.workflow = FakeWorkflow()
        self.terminal_session = FakeTerminalSession()
        self.config_workflow = FakeConfigWorkflow()
        self.dialog_workflow = FakeDialogWorkflow()
        self.reload_config_calls = 0

    def command_workflow_service(self) -> FakeWorkflow:
        return self.workflow

    def terminal_session_controller(self) -> FakeTerminalSession:
        return self.terminal_session

    def config_workflow_controller(self) -> FakeConfigWorkflow:
        return self.config_workflow

    def dialog_workflow_controller(self) -> FakeDialogWorkflow:
        return self.dialog_workflow

    def reload_config_from_disk(self) -> None:
        self.reload_config_calls += 1

    def toggle_connection(self) -> None:
        return None

    def stop_running_preview(self, _slot: str) -> str:
        return "stop preview"

    def stop_running_command(self, _slot: str) -> None:
        return None

    def toggle_board_connection(self) -> None:
        return None

    def sync_screen(self) -> None:
        return None


class FakeMenuScreen:
    def __init__(self, keys: list[int]) -> None:
        self.keys = keys
        self.timeouts: list[int] = []

    def timeout(self, value: int) -> None:
        self.timeouts.append(value)

    def erase(self) -> None:
        return None

    def getmaxyx(self) -> tuple[int, int]:
        return (24, 100)

    def refresh(self) -> None:
        return None


class FakeMenuApp(FakeApp):
    def __init__(self, config: dict[str, Any], keys: list[int]) -> None:
        super().__init__(config)
        self.screen = FakeMenuScreen(keys)
        self.status = ""

    def add(self, *_args: Any) -> None:
        return None

    def draw_box(self, *_args: Any) -> None:
        return None

    def read_key(self) -> int:
        return self.screen.keys.pop(0)

    def accent_attr(self) -> int:
        return 1

    def warn_attr(self) -> int:
        return 2

    def selected_attr(self) -> int:
        return 3

    def disabled_attr(self) -> int:
        return 4


def _config(app_dir: Path) -> dict[str, Any]:
    return {
        "__config_path": str(app_dir / "config.json"),
        "state": {"build_settings": "state/build-settings.json"},
        "inventory": {"mapping_selection": str(app_dir / "mapping-selection.txt")},
        "local": {"project_dir": str(app_dir / "overlay")},
        "active_remote": "build",
        "remotes": [
            {
                "name": "build",
                "user": "builder",
                "host": "10.0.0.1",
                "projects_dir": "/mnt/projects",
            }
        ],
        "active_board_host": "board",
        "board_hosts": [
            {
                "name": "board",
                "user": "tester",
                "host": "10.0.0.2",
                "work_dir": "/srv/tftp/vgon",
            }
        ],
        "active_project": "prod",
        "projects": [
            {
                "name": "prod",
                "project_dir": "meta-product",
                "local_project_dir": str(app_dir / "overlay"),
                "git_url": "https://example.invalid/prod.git",
                "git_ref": "main",
                "moulin_manifest": "product.yaml",
                "dockerfile": "doc/Dockerfile",
            }
        ],
    }


class MainMenuBuilderTests(unittest.TestCase):
    def test_build_items_includes_main_workflow_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: "",
                manifest_cache={},
            )

            self.assertIsInstance(builder.command_items, items.MainMenuCommandItemsService)
            self.assertIsInstance(builder.setup_items, items.MainMenuSetupItemsService)

            menu_items = builder.build_items(FakeApp(_config(app_dir)))

            labels = [item.label for item in menu_items]
            self.assertIn("Build host configuration", labels)
            self.assertIn("Select build host", labels)
            self.assertIn("Copy mapped files to build host", labels)
            self.assertIn("Run product build", labels)
            self.assertIn("Incremental build", labels)
            self.assertIn("Select board host", labels)
            self.assertIn("Copy build artifacts", labels)
            self.assertIn("Sync mapped files", labels)
            self.assertNotIn("Analyze changed Yocto recipes", labels)
            self.assertNotIn("Clean impacted Yocto recipes", labels)
            self.assertNotIn("Rebuild impacted Yocto recipes", labels)
            build_host_labels = [item.label for item in menu_items if item.group == "build / build host"]
            build_configuration_labels = [item.label for item in menu_items if item.group == "build / configuration"]
            build_labels = [item.label for item in menu_items if item.group == "build / commands"]
            command_labels = [item.label for item in builder.command_items.build_items(FakeApp(_config(app_dir)))]
            self.assertEqual(
                command_labels[:3],
                ["Open build host shell", "Select build targets", "Copy mapped files to build host"],
            )
            self.assertEqual(
                build_host_labels,
                [
                    "Open build host shell",
                ],
            )
            self.assertEqual(build_configuration_labels, ["Select build targets"])
            self.assertEqual(
                build_labels,
                [
                    "Copy mapped files to build host",
                    "Build Docker image",
                    "Regenerate Moulin/Ninja",
                    "Run product build",
                    "Incremental build",
                    "Clean Moulin components",
                    "Stop running command",
                ],
            )
            mapping_labels = [item.label for item in menu_items if item.group == "build / files mapping"]
            self.assertEqual(mapping_labels, ["Sync mapped files", "Open mapped workspace"])
            self.assertIn("Select build host", [item.label for item in menu_items if item.group == "sessions / build host"])
            self.assertIn("Select board host", [item.label for item in menu_items if item.group == "sessions / board host"])
            flashing_labels = [item.label for item in menu_items if item.group == "flashing / commands"]
            flashing_host_labels = [item.label for item in menu_items if item.group == "flashing / hosts"]
            board_host_labels = [item.label for item in menu_items if item.group == "flashing / board host"]
            self.assertIn("Copy build artifacts", flashing_labels)
            self.assertIn("Flash UFS image", flashing_labels)
            self.assertEqual(flashing_host_labels, ["Open build host shell", "Open board host shell"])
            self.assertEqual(
                board_host_labels,
                [
                    "Restart board",
                    "Open board serial console",
                    "Open U-Boot console",
                ],
            )
            self.assertIn("Open board serial console", board_host_labels)
            self.assertIn("Open U-Boot console", board_host_labels)
            self.assertIn("Restart board", board_host_labels)
            self.assertIn("Stop current board command", flashing_labels)
            tftp_deploy_labels = [item.label for item in menu_items if item.group == "tftp/nfs / deploy artifacts"]
            tftp_control_labels = [item.label for item in menu_items if item.group == "tftp/nfs / board control"]
            tftp_setup_labels = [item.label for item in menu_items if item.group == "tftp/nfs / board setup"]
            tftp_workspace_labels = [item.label for item in menu_items if item.group == "tftp/nfs / tftp/nfs workspace"]
            dom0_workspace_labels = [item.label for item in menu_items if item.group == "tftp/nfs / dom0 initramfs workspace"]
            tftp_remote_labels = [item.label for item in menu_items if item.group == "tftp/nfs / open remote roots"]
            tftp_labels = [item.label for item in menu_items if item.group.startswith("tftp/nfs / ")]
            self.assertIn("Deploy full TFTP/NFS set", tftp_deploy_labels)
            self.assertIn("Stop current board command", tftp_control_labels)
            self.assertEqual(
                tftp_workspace_labels,
                [
                    "Pull TFTP/NFS workspace",
                    "Push TFTP/NFS workspace",
                    "Open local TFTP workspace",
                    "Open local NFS workspace",
                ],
            )
            self.assertEqual(
                dom0_workspace_labels,
                [
                    "Pull Dom0 initramfs workspace",
                    "Push Dom0 initramfs workspace",
                    "Open local Dom0 initramfs workspace",
                ],
            )
            self.assertEqual(tftp_remote_labels, ["Open remote TFTP root", "Open remote NFS root"])
            self.assertEqual(
                tftp_setup_labels,
                ["Install NFS deploy helper", "Apply U-Boot network env", "Apply U-Boot UFS env"],
            )
            self.assertEqual(
                tftp_labels,
                [
                    "Deploy TFTP boot artifacts",
                    "Deploy DomD NFS rootfs",
                    "Deploy DomU NFS rootfs",
                    "Deploy Android image to NFS",
                    "Deploy full TFTP/NFS set",
                    "Pull TFTP/NFS workspace",
                    "Push TFTP/NFS workspace",
                    "Open local TFTP workspace",
                    "Open local NFS workspace",
                    "Pull Dom0 initramfs workspace",
                    "Push Dom0 initramfs workspace",
                    "Open local Dom0 initramfs workspace",
                    "Install NFS deploy helper",
                    "Apply U-Boot network env",
                    "Apply U-Boot UFS env",
                    "Stop current board command",
                    "Open remote TFTP root",
                    "Open remote NFS root",
                ],
            )

    def test_build_command_handler_uses_command_workflow_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: "",
                manifest_cache={},
            )
            app = FakeApp(_config(app_dir))
            menu_items = builder.build_items(app)
            build_item = next(item for item in menu_items if item.label == "Run product build")

            build_item.handler(app)

            self.assertEqual(app.reload_config_calls, 1)
            self.assertEqual(app.workflow.build_calls[0]["title"], "Run product build")
            self.assertEqual(app.workflow.build_calls[0]["targets"], "full_ufs.img.gz")
            self.assertEqual(app.workflow.command_calls, [])

    def test_build_tab_target_selector_delegates_to_config_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: "",
                manifest_cache={},
            )
            app = FakeApp(_config(app_dir))
            menu_items = builder.build_items(app)
            target_item = next(item for item in menu_items if item.label == "Select build targets")

            self.assertEqual(target_item.preview(app), "Current build targets: full_ufs.img.gz")
            target_item.handler(app)

            self.assertEqual(app.config_workflow.calls, ["targets"])
            self.assertEqual(app.workflow.build_calls, [])
            self.assertEqual(app.workflow.command_calls, [])

    def test_incremental_handler_runs_selected_component_builds_then_product_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            manifest_text = "\n".join(
                [
                    "min_ver: '1.0'",
                    "variables:",
                    "  DOM0_IMAGE: core-image-thin-initramfs",
                    "  DOMD_IMAGE: rcar-image-adas",
                    "components:",
                    "  dom0:",
                    "    builder:",
                    "      type: yocto",
                    "      build_target: '%{DOM0_IMAGE}'",
                    "  domd:",
                    "    builder:",
                    "      type: yocto",
                    "      build_target: '%{DOMD_IMAGE}'",
                    "  doma_kernel:",
                    "    build-dir: android_kernel",
                    "    builder:",
                    "      type: bazel",
                    "      tool: tools/bazel",
                    "      command: run",
                    "      args:",
                    "        - --verbose_failures",
                    "      target: '//common-modules/xen-virtual-device:xen_virtual_device_aarch64_dist'",
                    "      target-patterns:",
                    "        - '--destdir=../android/out/android_kernel/deploy/common-modules/xen-virtual-device/xen_virtual_device_aarch64'",
                    "      target_images:",
                    "        - '../android/out/android_kernel/deploy/common-modules/xen-virtual-device/xen_virtual_device_aarch64/Image'",
                    "  doma:",
                    "    builder:",
                    "      type: android",
                    "  boot_artifacts:",
                    "    builder:",
                    "      type: custom_script",
                ]
            )
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: manifest_text,
                manifest_cache={},
            )
            app = FakeApp(_config(app_dir))
            command_items = builder.command_items.build_items(app)
            builder.command_items.select_incremental_component_names = lambda _app, _components: [
                "domd",
                "doma_kernel",
                "doma",
                "boot_artifacts",
            ]
            yocto_item = next(item for item in command_items if item.label == "Incremental build")

            yocto_item.handler(app)

            self.assertEqual(app.reload_config_calls, 1)
            title, commands = app.workflow.command_calls[0]
            self.assertEqual(title, "Incremental build")
            self.assertEqual(len(commands), 6)
            self.assertIn('ACTION = "clean"', commands[0][-1])
            self.assertIn('IMAGE_RECIPES = "rcar-image-adas"', commands[0][-1])
            self.assertIn('ALLOW_EMPTY = "1" == "1"', commands[0][-1])
            self.assertIn("moulin product.yaml", commands[1][-1])
            self.assertIn(
                "tools/bazel --max_idle_secs=1 build //common-modules/xen-virtual-device:xen_virtual_device_aarch64/.config",
                commands[2][-1],
            )
            self.assertIn(
                "cd android_kernel && tools/bazel --max_idle_secs=1 run --verbose_failures //common-modules/xen-virtual-device:xen_virtual_device_aarch64_dist -- --destdir=../android/out/android_kernel/deploy/common-modules/xen-virtual-device/xen_virtual_device_aarch64",
                commands[3][-1],
            )
            self.assertIn("touch \"$p\"", commands[3][-1])
            self.assertIn("ninja doma_kernel doma", commands[4][-1])
            self.assertIn("ninja domd doma_kernel doma boot_artifacts", commands[5][-1])
            settings_path = app_dir / "state" / "build-settings.json"
            self.assertEqual(
                json.loads(settings_path.read_text(encoding="utf-8"))["incremental_components"],
                ["domd", "doma_kernel", "doma", "boot_artifacts"],
            )

    def test_incremental_handler_ignores_android_components_when_android_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            manifest_text = "\n".join(
                [
                    "min_ver: '1.0'",
                    "components:",
                    "  domu:",
                    "    builder:",
                    "      type: yocto",
                    "      build_target: rcar-image-adas",
                    "  doma_kernel:",
                    "    build-dir: android_kernel",
                    "    builder:",
                    "      type: bazel",
                    "      target: //common-modules/xen-virtual-device:xen_virtual_device_aarch64_dist",
                    "  doma:",
                    "    builder:",
                    "      type: android",
                ]
            )
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: manifest_text,
                manifest_cache={},
            )
            app = FakeApp(_config(app_dir))
            app.build_params = {"ENABLE_ANDROID": "no"}
            app.build_targets = "boot_artifacts"
            command_items = builder.command_items.build_items(app)
            builder.command_items.select_incremental_component_names = lambda _app, _components: [
                "domu",
                "doma_kernel",
                "doma",
            ]
            yocto_item = next(item for item in command_items if item.label == "Incremental build")

            yocto_item.handler(app)

            _title, commands = app.workflow.command_calls[0]
            command_text = "\n".join(command[-1] for command in commands if command)
            self.assertIn('IMAGE_RECIPES = "rcar-image-adas"', command_text)
            self.assertNotIn("tools/bazel", command_text)
            self.assertNotIn("ninja doma", command_text)
            self.assertNotIn("ninja doma_kernel", command_text)

    def test_incremental_handler_reconfigures_bazel_for_changed_config_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            config_path = local_base / "android_kernel/common/drivers/firmware/arm_scmi/transports/Kconfig"
            config_path.parent.mkdir(parents=True)
            config_path.write_text("default y\n", encoding="utf-8")
            config = _config(app_dir)
            config["state"] = {"build_settings": str(app_dir / "state/build-settings.json")}
            project = config["projects"][0]
            project["mappings"] = [
                {
                    "name": "android-kernel-scmi-virtio-kconfig",
                    "role": "android-kernel-scmi-virtio-kconfig",
                    "remote": "android_kernel/common/drivers/firmware/arm_scmi/transports/Kconfig",
                    "local": "android_kernel/common/drivers/firmware/arm_scmi/transports/Kconfig",
                    "kind": "file",
                    "push": True,
                }
            ]
            project["active_mappings"] = ["android-kernel-scmi-virtio-kconfig"]
            runtime_api.save_runtime_mapping_snapshot(config, app_dir, project["mappings"])
            config_path.write_text("default n\n", encoding="utf-8")
            manifest_text = "\n".join(
                [
                    "min_ver: '1.0'",
                    "components:",
                    "  doma_kernel:",
                    "    build-dir: android_kernel",
                    "    builder:",
                    "      type: bazel",
                    "      command: run",
                    "      target: '//common-modules/xen-virtual-device:xen_virtual_device_aarch64_dist'",
                    "      target-patterns:",
                    "        - '--destdir=../android/out/android_kernel/deploy/common-modules/xen-virtual-device/xen_virtual_device_aarch64'",
                    "      target_images:",
                    "        - '../android/out/android_kernel/deploy/common-modules/xen-virtual-device/xen_virtual_device_aarch64/Image'",
                    "  doma:",
                    "    builder:",
                    "      type: android",
                ]
            )
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: manifest_text,
                manifest_cache={},
            )
            app = FakeApp(config)
            command_items = builder.command_items.build_items(app)
            builder.command_items.select_incremental_component_names = lambda _app, _components: ["doma_kernel", "doma"]
            yocto_item = next(item for item in command_items if item.label == "Incremental build")

            yocto_item.handler(app)

            _title, commands = app.workflow.command_calls[0]
            self.assertEqual(len(commands), 6)
            self.assertIn("moulin product.yaml", commands[1][-1])
            self.assertIn(
                "tools/bazel --max_idle_secs=1 build //common-modules/xen-virtual-device:xen_virtual_device_aarch64/.config",
                commands[2][-1],
            )
            self.assertIn(
                "cd android_kernel && tools/bazel --max_idle_secs=1 run //common-modules/xen-virtual-device:xen_virtual_device_aarch64_dist -- --destdir=../android/out/android_kernel/deploy/common-modules/xen-virtual-device/xen_virtual_device_aarch64",
                commands[3][-1],
            )
            self.assertIn("ninja doma_kernel doma", commands[4][-1])
            self.assertIn("ninja doma_kernel doma", commands[5][-1])

    def test_incremental_handler_runs_yocto_impact_even_without_selected_yocto_component(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            manifest_text = "\n".join(
                [
                    "min_ver: '1.0'",
                    "components:",
                    "  doma:",
                    "    builder:",
                    "      type: android",
                ]
            )
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: manifest_text,
                manifest_cache={},
            )
            app = FakeApp(_config(app_dir))
            command_items = builder.command_items.build_items(app)
            builder.command_items.select_incremental_component_names = lambda _app, _components: ["doma"]
            yocto_item = next(item for item in command_items if item.label == "Incremental build")

            yocto_item.handler(app)

            self.assertEqual(app.reload_config_calls, 1)
            _title, commands = app.workflow.command_calls[0]
            self.assertEqual(len(commands), 4)
            self.assertIn('ACTION = "clean"', commands[0][-1])
            self.assertIn('IMAGE_RECIPES = ""', commands[0][-1])
            self.assertIn('ALLOW_EMPTY = "1" == "1"', commands[0][-1])
            self.assertIn("moulin product.yaml", commands[1][-1])
            self.assertIn("ninja doma", commands[2][-1])
            self.assertIn("ninja doma", commands[3][-1])

    def test_component_clean_popup_cancel_returns_to_component_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            manifest_text = "\n".join(
                [
                    "min_ver: '1.0'",
                    "components:",
                    "  domd:",
                    "    builder:",
                    "      type: yocto",
                    "      build_target: rcar-image-adas",
                    "      target_images:",
                    "        - yocto/build-domd/tmp/deploy/images/x5h/rcar-image-adas.ext4",
                    "  domu:",
                    "    builder:",
                    "      type: yocto",
                    "      build_target: domu-image",
                    "      target_images:",
                    "        - yocto/build-domu/tmp/deploy/images/x5h/domu-image.ext4",
                ]
            )
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: manifest_text,
                manifest_cache={},
            )
            app = FakeApp(_config(app_dir))
            app.dialog_workflow.confirm_results = [False, True]
            command_items = builder.command_items.build_items(app)
            builder.command_items.select_component_clean_action = lambda _app: {
                "mode": "artifacts",
                "dry_run": False,
            }
            selections = iter([["domd"], ["domu"]])
            builder.command_items.select_incremental_component_names = lambda _app, _components, **_kwargs: next(selections)
            captured_clean: list[dict[str, Any]] = []
            builder.command_items.component_clean_commands = lambda _app, *, selected_names, mode, dry_run: (
                captured_clean.append({"selected_names": selected_names, "mode": mode, "dry_run": dry_run}) or [["clean"]]
            )
            clean_item = next(item for item in command_items if item.label == "Clean Moulin components")

            self.assertFalse(clean_item.confirm)
            clean_item.handler(app)

            self.assertEqual(app.reload_config_calls, 1)
            self.assertEqual(len(app.dialog_workflow.confirm_calls), 2)
            self.assertEqual(app.workflow.command_calls[0][0], "Clean components (artifacts)")
            self.assertEqual(captured_clean, [{"selected_names": ["domu"], "mode": "artifacts", "dry_run": False}])

    def test_artifact_cleanup_supports_android_and_custom_script_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            manifest_text = "\n".join(
                [
                    "min_ver: '1.0'",
                    "components:",
                    "  doma:",
                    "    builder:",
                    "      type: android",
                    "  boot_artifacts:",
                    "    builder:",
                    "      type: custom_script",
                ]
            )
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: manifest_text,
                manifest_cache={},
            )
            app = FakeApp(_config(app_dir))

            cleanable = builder.command_items.cleanable_components(app, mode="artifacts")

            self.assertEqual(
                [(component["name"], component["builder_type"], component["supported"]) for component in cleanable],
                [("doma", "android", True), ("boot_artifacts", "custom_script", True)],
            )

    def test_directory_cleanup_uses_manifest_build_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            manifest_text = "\n".join(
                [
                    "min_ver: '1.0'",
                    "components:",
                    "  doma:",
                    "    build-dir: android",
                    "    builder:",
                    "      type: android",
                    "  boot_artifacts:",
                    "    builder:",
                    "      type: custom_script",
                ]
            )
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: manifest_text,
                manifest_cache={},
            )
            app = FakeApp(_config(app_dir))

            cleanable = builder.command_items.cleanable_components(app, mode="directory")

            self.assertEqual(
                [(component["name"], component.get("build_dir", ""), component["supported"]) for component in cleanable],
                [("doma", "android", True), ("boot_artifacts", "", False)],
            )

    def test_directory_cleanup_lists_manifest_components_even_when_disabled_by_params(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            manifest_text = "\n".join(
                [
                    "min_ver: '1.0'",
                    "components:",
                    "  domd:",
                    "    build-dir: yocto",
                    "    builder:",
                    "      type: yocto",
                    "      build_target: rcar-image-adas",
                    "  doma_kernel:",
                    "    build-dir: android_kernel",
                    "    builder:",
                    "      type: bazel",
                    "      target: //kernel:dist",
                    "  doma:",
                    "    build-dir: android",
                    "    builder:",
                    "      type: android",
                ]
            )
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: manifest_text,
                manifest_cache={},
            )
            app = FakeApp(_config(app_dir))
            app.build_params = {"ENABLE_ANDROID": "no"}

            cleanable = builder.command_items.cleanable_components(app, mode="directory")

            self.assertEqual(
                [(component["name"], component.get("build_dir", ""), component["supported"]) for component in cleanable],
                [("domd", "yocto", True), ("doma_kernel", "android_kernel", True), ("doma", "android", True)],
            )

    def test_directory_cleanup_filters_missing_remote_component_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            manifest_text = "\n".join(
                [
                    "min_ver: '1.0'",
                    "components:",
                    "  domd:",
                    "    build-dir: yocto",
                    "    builder:",
                    "      type: yocto",
                    "      work_dir: build-domd",
                    "      build_target: rcar-image-adas",
                    "  doma_kernel:",
                    "    build-dir: android_kernel",
                    "    builder:",
                    "      type: bazel",
                    "      target: //kernel:dist",
                    "  doma:",
                    "    build-dir: android",
                    "    builder:",
                    "      type: android",
                    "  boot_artifacts:",
                    "    build-dir: artifacts",
                    "    builder:",
                    "      type: custom_script",
                ]
            )
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: manifest_text,
                manifest_cache={},
            )
            app = FakeApp(_config(app_dir))
            captured_commands: list[list[str]] = []
            app.remote_capture_command = lambda argv: captured_commands.append(argv) or "domd\nboot_artifacts\n"

            cleanable = builder.command_items.cleanable_components(app, mode="directory")

            self.assertEqual(
                [(component["name"], component.get("build_dir", ""), component["supported"]) for component in cleanable],
                [("domd", "yocto", True), ("boot_artifacts", "artifacts", True)],
            )
            probe_script = captured_commands[0][-1]
            self.assertIn("; if [ -d", probe_script)
            self.assertIn("yocto/build-domd", probe_script)
            self.assertIn("android_kernel", probe_script)
            self.assertIn("android", probe_script)
            self.assertIn("artifacts", probe_script)

    def test_directory_cleanup_hides_successfully_removed_components(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            manifest_text = "\n".join(
                [
                    "min_ver: '1.0'",
                    "components:",
                    "  doma_kernel:",
                    "    build-dir: android_kernel",
                    "    builder:",
                    "      type: bazel",
                    "      target: //kernel:dist",
                    "  doma:",
                    "    build-dir: android",
                    "    builder:",
                    "      type: android",
                    "  domd:",
                    "    build-dir: yocto",
                    "    builder:",
                    "      type: yocto",
                    "      build_target: rcar-image-adas",
                ]
            )
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: manifest_text,
                manifest_cache={},
            )
            app = FakeApp(_config(app_dir))
            builder.command_items.select_incremental_component_names = (
                lambda _app, _components, **_kwargs: ["doma_kernel", "doma"]
            )
            builder.command_items.confirm_component_clean = lambda _app, **_kwargs: True

            result = builder.command_items.run_component_clean(app, mode="directory", dry_run=False)
            cleanable = builder.command_items.cleanable_components(app, mode="directory")

            self.assertEqual(result, 0)
            self.assertEqual(app.cleaned_component_directories, {"doma_kernel", "doma"})
            self.assertEqual(
                [(component["name"], component.get("build_dir", ""), component["supported"]) for component in cleanable],
                [("domd", "yocto", True)],
            )

    def test_component_clean_confirm_uses_popup_dialog(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: "",
                manifest_cache={},
            )
            app = FakeApp(_config(app_dir))

            result = builder.command_items.confirm_component_clean(
                app,
                selected_names=["boot_artifacts"],
                mode="directory",
                dry_run=False,
            )

            self.assertTrue(result)
            self.assertEqual(len(app.dialog_workflow.confirm_calls), 1)
            content = app.dialog_workflow.confirm_calls[0]
            self.assertEqual(content.title, "Confirm")
            self.assertEqual(content.subject, "Clean Moulin components: boot_artifacts")
            self.assertIn("Mode: directory.", content.details)

    def test_build_output_cleanup_supports_android_and_yocto_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            manifest_text = "\n".join(
                [
                    "min_ver: '1.0'",
                    "components:",
                    "  domd:",
                    "    build-dir: yocto",
                    "    builder:",
                    "      type: yocto",
                    "      work_dir: build-domd",
                    "      build_target: rcar-image-adas",
                    "  doma:",
                    "    build-dir: android",
                    "    builder:",
                    "      type: android",
                    "  doma_kernel:",
                    "    build-dir: android_kernel",
                    "    builder:",
                    "      type: bazel",
                    "      target: //kernel:dist",
                ]
            )
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: manifest_text,
                manifest_cache={},
            )
            app = FakeApp(_config(app_dir))

            cleanable = builder.command_items.cleanable_components(app, mode="build_output")

            self.assertEqual(
                [(component["name"], component["builder_type"], component["supported"]) for component in cleanable],
                [("domd", "yocto", True), ("doma", "android", True), ("doma_kernel", "bazel", False)],
            )

    def test_component_selection_cursor_skips_unsupported_components(self) -> None:
        components = [
            {"name": "dom0", "supported": True},
            {"name": "doma_kernel", "supported": False},
            {"name": "doma", "supported": False},
            {"name": "domd", "supported": True},
        ]

        self.assertEqual(items.MainMenuCommandItemsService.clamp_supported_component_index(components, 1), 3)
        self.assertEqual(items.MainMenuCommandItemsService.move_supported_component_index(components, 0, 1), 3)
        self.assertEqual(items.MainMenuCommandItemsService.move_supported_component_index(components, 3, 1), 0)
        self.assertEqual(items.MainMenuCommandItemsService.move_supported_component_index(components, 0, -1), 3)

    def test_component_clean_mode_selection_preserves_stack_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: "",
                manifest_cache={},
            )
            app = FakeMenuApp(_config(app_dir), [ord("j"), ord("j"), ord("j"), ord("j"), ord(" "), 10])

            first = builder.command_items.select_component_clean_action(app)
            app.screen.keys = [10]
            second = builder.command_items.select_component_clean_action(app)

            self.assertEqual(first, {"label": "Yocto component sstate", "mode": "yocto_component_sstate", "description": "Run BitBake cleansstate for each selected Yocto component build target.", "dry_run": False})
            self.assertEqual(second, first)

    def test_component_clean_component_cancel_returns_to_mode_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            manifest_text = "\n".join(
                [
                    "min_ver: '1.0'",
                    "components:",
                    "  doma:",
                    "    builder:",
                    "      type: android",
                ]
            )
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: manifest_text,
                manifest_cache={},
            )
            app = FakeApp(_config(app_dir))
            choices = iter([
                {"mode": "artifacts", "dry_run": True},
                None,
            ])
            builder.command_items.select_component_clean_action = lambda _app: next(choices)
            builder.command_items.select_incremental_component_names = lambda _app, _components, **_kwargs: None

            builder.command_items.run_component_clean_menu(app)

            self.assertEqual(app.workflow.command_calls, [])
            self.assertEqual(app.status, "Component cleanup cancelled")

    def test_incremental_change_state_auto_selects_component_from_changed_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_base = app_dir / "overlay"
            layer = local_base / "layers/meta-xt-dom0-gen5"
            layer.mkdir(parents=True)
            (layer / "doma.bbappend").write_text("old\n", encoding="utf-8")
            config = _config(app_dir)
            config["state"] = {"build_settings": str(app_dir / "state/build-settings.json")}
            project = config["projects"][0]
            project["mappings"] = [
                {
                    "name": "layers-meta-xt-dom0-gen5",
                    "role": "layers-meta-xt-dom0-gen5",
                    "remote": "layers/meta-xt-dom0-gen5",
                    "local": "layers/meta-xt-dom0-gen5",
                    "kind": "directory",
                    "push": True,
                }
            ]
            project["active_mappings"] = ["layers-meta-xt-dom0-gen5"]
            mapping = project["mappings"][0]
            runtime_api.save_runtime_mapping_snapshot(config, app_dir, [mapping])
            (layer / "doma.bbappend").write_text("new\n", encoding="utf-8")
            manifest_text = "\n".join(
                [
                    "min_ver: '1.0'",
                    "components:",
                    "  dom0:",
                    "    builder:",
                    "      type: yocto",
                    "      build_target: core-image-thin-initramfs",
                    "  doma:",
                    "    builder:",
                    "      type: android",
                ]
            )
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: manifest_text,
                manifest_cache={},
            )
            app = FakeApp(config)

            components = builder.command_items.incremental_components(app)
            state = builder.command_items.incremental_change_state(app, components)

            self.assertEqual(state["mappings"], ["layers-meta-xt-dom0-gen5"])
            self.assertEqual(state["components"], ["dom0"])

    def test_copy_mapped_files_handler_runs_explicit_mapping_push(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: "",
                manifest_cache={},
            )
            app = FakeApp(_config(app_dir))
            command_items = builder.command_items.build_items(app)
            copy_item = next(item for item in command_items if item.label == "Copy mapped files to build host")

            copy_item.handler(app)

            self.assertEqual(app.reload_config_calls, 1)
            self.assertEqual(app.workflow.command_calls[0][0], "Copy mapped files to build host")
            self.assertIn("Copy mapped files", app.workflow.command_calls[0][1][0][2])

    def test_command_items_service_builds_board_command_handlers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: "",
                manifest_cache={},
            )
            app = FakeApp(_config(app_dir))
            command_items = builder.command_items.build_items(app)
            copy_item = next(item for item in command_items if item.label == "Copy build artifacts")

            copy_item.handler(app)

            self.assertEqual(app.workflow.command_calls[0][0], "Copy build artifacts")
            self.assertIn("Copy build artifacts", app.workflow.command_calls[0][1][1][2])

    def test_setup_items_service_adds_preflight_action_handlers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: "",
                manifest_cache={},
            )
            app = FakeApp(_config(app_dir))
            app.preflight_values = {"project": "missing", "origin": "mismatch", "ref": "mismatch"}
            setup_items = builder.setup_items.build_items(app)
            prepare_item = next(item for item in setup_items if item.label == "Prepare remote project")

            prepare_item.handler(app)

            self.assertEqual(app.workflow.command_calls[0][0], "Prepare remote project")
            self.assertIn("git clone", app.workflow.command_calls[0][1][0][-1])

    def test_shell_handlers_use_terminal_session_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            builder = items.main_menu_builder(
                app_dir=app_dir,
                default_config_path=app_dir / "config.json",
                default_dockerfile="doc/Dockerfile",
                default_moulin_manifest="product.yaml",
                flash_bootloaders_tool=app_dir / "flash_bootloaders.py",
                xt_imager_tool=app_dir / "xt-imager.py",
                remote_read_project_file=lambda *_args, **_kwargs: "",
                manifest_cache={},
            )
            app = FakeApp(_config(app_dir))
            menu_items = builder.build_items(app)

            next(item for item in menu_items if item.label == "Open build host shell").handler(app)
            next(item for item in menu_items if item.label == "Open board host shell" and item.group == "sessions / board host").handler(app)
            next(item for item in menu_items if item.label == "Open build host shell" and item.group == "flashing / hosts").handler(app)
            next(item for item in menu_items if item.label == "Open board host shell" and item.group == "flashing / hosts").handler(app)
            next(item for item in menu_items if item.label == "Open mapped workspace").handler(app)
            next(item for item in menu_items if item.label == "Open remote TFTP root").handler(app)
            next(item for item in menu_items if item.label == "Open local NFS workspace").handler(app)
            next(item for item in menu_items if item.label == "Open board serial console").handler(app)
            next(item for item in menu_items if item.label == "Open U-Boot console").handler(app)

            self.assertEqual(
                app.terminal_session.calls,
                [
                    "remote",
                    "board",
                    "remote",
                    "board",
                    "local:Open mapped workspace",
                    "board-dir:Open remote TFTP root",
                    "local:Open local NFS workspace",
                    "command:Open board serial console",
                    "command:Open U-Boot console",
                ],
            )
            self.assertEqual(app.terminal_session.commands[0][0], "ssh")
            self.assertIn("-tt", app.terminal_session.commands[0])
            self.assertIn("tester@10.0.0.2", app.terminal_session.commands[0])
            self.assertIn("picocom -b 1843200", app.terminal_session.commands[0][-1])
            self.assertNotIn("x5h_off", app.terminal_session.commands[0][-1])
            self.assertIn("x5h_off", app.terminal_session.commands[1][-1])
            self.assertIn("picocom -b 1843200", app.terminal_session.commands[1][-1])


if __name__ == "__main__":
    unittest.main()
