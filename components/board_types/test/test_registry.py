from __future__ import annotations

import unittest

from components.board_types.api import registry


class BoardTypeRegistryTests(unittest.TestCase):
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
            [(action.action_id, action.label) for action in adapter.actions({})],
            [
                ("copy_build_artifacts", "Copy build artifacts"),
                ("flash_bootloaders", "Flash bootloaders"),
                ("flash_ufs_image", "Flash UFS image"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
