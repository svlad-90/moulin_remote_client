from __future__ import annotations

import unittest

from components.board_types.api.base import BoardAction, BoardCapability, BoardCommandDefault, BoardTypeAdapter
from components.board_types.api import registry


class BoardTypeRegistryTests(unittest.TestCase):
    def test_reboot_capability_is_inferred_from_action_and_commands(self) -> None:
        class Adapter(BoardTypeAdapter):
            type_id = "test"

            def actions(self, _config: dict[str, object]) -> list[BoardAction]:
                return [
                    BoardAction(
                        "restart_board",
                        "Restart",
                        "Restart the board",
                        required_commands=("power_off", "boot_mode", "power_on"),
                    )
                ]

            def command_defaults(self) -> list[BoardCommandDefault]:
                return [
                    BoardCommandDefault("power_off", "Power off", ""),
                    BoardCommandDefault("boot_mode", "Boot mode", ""),
                    BoardCommandDefault("power_on", "Power on", ""),
                ]

        adapter = Adapter()

        self.assertNotIn(BoardCapability.REBOOT, adapter.capabilities())
        self.assertIn(
            BoardCapability.REBOOT,
            adapter.capabilities(
                {"commands": {"power_off": "off", "boot_mode": "boot", "power_on": "on"}}
            ),
        )
        self.assertNotIn(
            BoardCapability.REBOOT,
            adapter.capabilities({"commands": {"power_off": "off", "power_on": "on"}}),
        )

    def test_default_registry_returns_gen5_x5h_adapter(self) -> None:
        reg = registry.board_type_registry()

        self.assertEqual(reg.default_type_id(), "gen5_x5h")
        self.assertIn("gen5_x5h", [adapter.type_id for adapter in reg.adapters()])
        self.assertEqual(reg.adapter_for_type("").type_id, "gen5_x5h")
        self.assertEqual(reg.adapter_for_type("unknown").type_id, "gen5_x5h")

    def test_builtin_adapters_are_discovered_from_builtin_modules(self) -> None:
        adapters = registry.discover_builtin_adapters()

        self.assertEqual(adapters[0].type_id, "gen5_x5h")

    def test_gen5_x5h_adapter_declares_current_board_actions(self) -> None:
        adapter = registry.board_type_registry().adapter_for_type("gen5_x5h")

        self.assertEqual(
            adapter.capabilities(),
            frozenset({BoardCapability.REBOOT, BoardCapability.REFLASH, BoardCapability.REFLASH_BOOTLOADERS}),
        )
        self.assertEqual(
            [(action.action_id, action.label) for action in adapter.actions({})],
            [
                ("open_board_host_shell", "Open board host shell"),
                ("copy_build_artifacts", "Copy build artifacts"),
                ("flash_bootloaders", "Flash bootloaders (flash mode) from build host"),
                ("flash_single_ipl", "Flash bootloaders from build host"),
                ("flash_ufs_image", "Flash UFS image from build host"),
                ("restart_board", "Restart board"),
                ("open_board_serial_console", "Open board serial console"),
                ("open_uboot_console", "Open U-Boot console"),
                ("turn_off_board", "Turn off board"),
                ("deploy_network_boot", "Deploy TFTP boot artifacts"),
                ("deploy_network_domd_rootfs", "Deploy DomD NFS rootfs"),
                ("deploy_network_domu_rootfs", "Deploy DomU NFS rootfs"),
                ("deploy_network_android", "Deploy Android image to NFS"),
                ("unpack_network_android", "Unpack Android image on NFS"),
                ("deploy_network_full", "Deploy full TFTP/NFS set"),
                ("install_nfs_deploy_helper", "Install NFS deploy helper"),
                ("pull_network_workspace", "Pull TFTP/NFS workspace"),
                ("push_network_workspace", "Push TFTP/NFS workspace"),
                ("pull_dom0_initramfs_workspace", "Pull Dom0 initramfs workspace"),
                ("push_dom0_initramfs_workspace", "Push Dom0 initramfs workspace"),
                ("apply_uboot_network_env", "Apply U-Boot network env"),
                ("apply_uboot_ufs_env", "Apply U-Boot UFS env"),
                ("inject_invasive_uboot_parameters", "Inject invasive U-Boot parameters"),
            ],
        )

    def test_gen5_x5h_adapter_declares_board_host_command_defaults(self) -> None:
        adapter = registry.board_type_registry().adapter_for_type("gen5_x5h")

        self.assertEqual(
            [(command.command_id, command.default) for command in adapter.command_defaults()],
            [
                ("power_off", "x5h_off"),
                ("power_on", "x5h_on"),
                ("boot_mode", "x5h_boot"),
                ("flash_mode", "x5h_flash"),
                ("console", "{mrc_serial_console}"),
                ("ownership_acquire", ""),
                ("ownership_release", ""),
                ("ownership_status", ""),
            ],
        )
        self.assertEqual(adapter.command_value_for_host({"commands": {"power_off": "lab-off"}}, "power_off"), "lab-off")
        self.assertEqual(adapter.command_value_for_host({"commands": {"power_off": ""}}, "power_off"), "x5h_off")

    def test_gen5_x5h_adapter_exposes_ownership_only_for_configured_board(self) -> None:
        adapter = registry.board_type_registry().adapter_for_type("gen5_x5h")
        config = {
            "active_board_host": "lab",
            "board_hosts": [
                {
                    "name": "lab",
                    "boards": [
                        {
                            "name": "ironhide-2",
                            "type": "gen5_x5h",
                            "commands": {
                                "ownership_acquire": "labgrid-client -p ironhide-2 acquire",
                                "ownership_release": "labgrid-client -p ironhide-2 release",
                                "ownership_status": "labctl --board ironhide-2 status",
                            },
                        }
                    ],
                }
            ],
            "active_board": "ironhide-2",
        }

        action_ids = [action.action_id for action in adapter.actions(config)]

        self.assertEqual(
            action_ids[1:3],
            ["ownership_acquire", "ownership_release"],
        )
        self.assertNotIn("ownership_status", action_ids)
        incomplete_config = {
            "active_board_host": "lab",
            "board_hosts": [
                {
                    "name": "lab",
                    "commands": {"ownership_acquire": "acquire", "ownership_release": ""},
                }
            ],
        }
        self.assertNotIn(
            "ownership_acquire",
            [action.action_id for action in adapter.actions(incomplete_config)],
        )


if __name__ == "__main__":
    unittest.main()
