from __future__ import annotations

import unittest

from components.product_types.api.base import ProductCapability, ProductComponent, ProductDomain
from components.product_types.api.registry import product_type_registry


class ProductTypeRegistryTests(unittest.TestCase):
    def test_gen5_xen_android_domains_follow_android_component_builders(self) -> None:
        adapter = product_type_registry().adapter_for_type("gen5_xen_android")

        self.assertEqual(
            adapter.domains(
                (
                    ProductComponent("dom0", "yocto"),
                    ProductComponent("passenger", "android"),
                    ProductComponent("cluster", "android"),
                )
            ),
            (ProductDomain("passenger", "android"), ProductDomain("cluster", "android")),
        )

    def test_gen5_xen_android_publishes_adb_only_with_an_android_domain(self) -> None:
        adapter = product_type_registry().adapter_for_type("gen5_xen_android")

        self.assertEqual(adapter.capabilities((ProductComponent("domu", "yocto"),)), frozenset())
        self.assertEqual(
            adapter.capabilities((ProductComponent("any-name", "android"),)),
            frozenset({ProductCapability.ANDROID_ADB}),
        )

    def test_gen5_xen_android_resolves_domd_address_by_board_mac(self) -> None:
        adapter = product_type_registry().adapter_for_type("gen5_xen_android")

        plan = adapter.android_adb_resolver({"mac_address": "AA:BB:CC:DD:EE:FF"})

        self.assertIsNotNone(plan)
        self.assertIn("ip neigh show", plan.command)
        self.assertIn("aa:bb:cc:dd:ee:ff", plan.command)
        self.assertIn(":5555", plan.command)

    def test_gen5_xen_android_prefers_domd_serial_console_resolver(self) -> None:
        adapter = product_type_registry().adapter_for_type("gen5_xen_android")

        plan = adapter.android_adb_resolver(
            {
                "console_device": "/dev/GEN5_CONSOLE2",
                "mac_address": "AA:BB:CC:DD:EE:FF",
            }
        )

        self.assertIsNotNone(plan)
        self.assertIn("/dev/GEN5_CONSOLE2", plan.command)
        self.assertIn('send(b"\\r\\r\\r",', plan.command)
        self.assertIn('send(b"\\x1d\\r\\r\\r",', plan.command)
        self.assertIn("login_root(15, refresh_login=True)", plan.command)
        self.assertIn('send(b"xl console DomD\\r",', plan.command)
        self.assertIn("login_root(20, refresh_login=True)", plan.command)
        self.assertIn("ip -4 route get 1.1.1.1", plan.command)
        self.assertEqual(plan.timeout_seconds, 90)

    def test_gen5_xen_android_uses_board_ip_without_a_mac(self) -> None:
        adapter = product_type_registry().adapter_for_type("gen5_xen_android")

        plan = adapter.android_adb_resolver({"board_ip": "192.0.2.30"})

        self.assertIsNotNone(plan)
        self.assertIn("192.0.2.30:5555", plan.command)

    def test_gen5_xen_android_auto_detects_first_console_device(self) -> None:
        adapter = product_type_registry().adapter_for_type("gen5_xen_android")

        plan = adapter.android_adb_resolver({})

        self.assertIsNotNone(plan)
        self.assertIn("ls -1 /dev/GEN5_CONSOLE*", plan.command)
        self.assertIn("python3 -c", plan.command)
        self.assertIn('"$console"', plan.command)
        self.assertEqual(plan.timeout_seconds, 90)

    def test_registry_uses_gen5_xen_android_as_the_default(self) -> None:
        registry = product_type_registry()

        self.assertEqual(registry.default_type_id(), "gen5_xen_android")
        self.assertEqual(registry.adapter_for_type("").type_id, "gen5_xen_android")
        self.assertEqual(registry.adapter_for_type("unknown").type_id, "gen5_xen_android")


if __name__ == "__main__":
    unittest.main()
