from __future__ import annotations

import unittest

from components.config.api.entities import core_profile_contributor
from components.config.api.store import DeletionRestrictedError, EntityRef, config_store
from plugins.cts_vts.config_entities import config_contributor


def root_config():
    return {
        "remotes": [
            {"id": "host-a", "name": "host-a"},
            {"id": "host-b", "name": "host-b"},
        ],
        "active_remote": "host-a",
        "board_hosts": [
            {
                "id": "board-host-a",
                "name": "board-host-a",
                "boards": [
                    {
                        "id": "board-a",
                        "board_host_id": "board-host-a",
                        "name": "board-a",
                    }
                ],
            }
        ],
        "active_board_host": "board-host-a",
        "active_board": "board-a",
        "projects": [
            {"id": "project-a", "name": "project-a"},
            {"id": "project-b", "name": "project-b"},
        ],
        "active_project": "project-a",
        "plugins": {
            "cts-vts": {
                "enabled": True,
                "config": {
                    "runners": [{"id": "runner-a", "name": "runner-a"}],
                    "board_profiles": [
                        {
                            "id": "boards-a",
                            "name": "boards-a",
                            "devices": [{"board_id": "board-a"}],
                        }
                    ],
                    "test_profiles": [{"id": "tests-a", "name": "tests-a"}],
                    "product_profiles": [
                        {
                            "id": "product-a",
                            "name": "product-a",
                            "build_host": "host-a",
                            "project": "project-a",
                        }
                    ],
                    "runs": [
                        {
                            "id": "run-a",
                            "name": "run-a",
                            "runner_profile": "runner-a",
                            "board_profile": "boards-a",
                            "test_profile": "tests-a",
                            "product_profile": "product-a",
                        }
                    ],
                },
            }
        },
    }


class CtsVtsConfigContributorTests(unittest.TestCase):
    def store(self, config):
        store = config_store(config)
        issues = store.initialize([core_profile_contributor(), config_contributor()])
        self.assertEqual(issues, ())
        return store

    def test_build_host_delete_clears_product_profile_reference(self) -> None:
        config = root_config()
        store = self.store(config)

        plan = store.prepare_delete(EntityRef("build_host", "host-a"))
        store.execute_delete(plan)

        product = config["plugins"]["cts-vts"]["config"]["product_profiles"][0]
        self.assertEqual(product["build_host"], "")
        self.assertEqual([item["id"] for item in config["remotes"]], ["host-b"])

    def test_board_host_delete_detaches_references_to_owned_boards(self) -> None:
        config = root_config()
        store = self.store(config)

        plan = store.prepare_delete(EntityRef("board_host", "board-host-a"))

        self.assertIn(EntityRef("board", "board-a"), plan.affected_targets)
        store.execute_delete(plan)
        board_profile = config["plugins"]["cts-vts"]["config"]["board_profiles"][0]
        self.assertEqual(board_profile["devices"], [])

    def test_referenced_cts_profile_delete_is_restricted(self) -> None:
        config = root_config()
        store = self.store(config)
        plan = store.prepare_delete(EntityRef("cts_vts.runner", "runner-a"))

        with self.assertRaises(DeletionRestrictedError):
            store.execute_delete(plan)

        self.assertEqual(config["plugins"]["cts-vts"]["config"]["runners"][0]["id"], "runner-a")

    def test_reference_updates_use_registered_writers(self) -> None:
        config = root_config()
        config["plugins"]["cts-vts"]["config"]["active_runner"] = "runner-a"
        store = self.store(config)

        store.replace_references(
            "cts_vts.product_profile.project",
            EntityRef("cts_vts.product_profile", "product-a"),
            (EntityRef("project", "project-b"),),
        )
        store.replace_references(
            "cts_vts.active_runner",
            EntityRef("cts_vts.selection", "active"),
            (),
        )

        plugin = config["plugins"]["cts-vts"]["config"]
        self.assertEqual(plugin["product_profiles"][0]["project"], "project-b")
        self.assertEqual(plugin["active_runner"], "")

    def test_store_creates_all_cts_vts_entity_types(self) -> None:
        config = root_config()
        store = self.store(config)

        runner = store.create_entity(
            "cts_vts.runner",
            {"name": "runner-b", "label": "Runner B"},
        ).reference
        boards = store.create_entity(
            "cts_vts.board_profile",
            {"name": "boards-b", "devices": [{"board_id": "board-a"}]},
        ).reference
        tests = store.create_entity(
            "cts_vts.test_profile",
            {"name": "tests-b", "suites": ["vts"]},
        ).reference
        product = store.create_entity(
            "cts_vts.product_profile",
            {"name": "product-b", "build_host": "host-b", "project": "project-b"},
        ).reference
        run = store.create_entity(
            "cts_vts.run",
            {
                "name": "run-b",
                "runner_profile": runner.entity_id,
                "board_profile": boards.entity_id,
                "test_profile": tests.entity_id,
                "product_profile": product.entity_id,
            },
        ).reference

        plugin = config["plugins"]["cts-vts"]["config"]
        self.assertEqual(plugin["active_runner"], runner.entity_id)
        self.assertEqual(plugin["active_run"], run.entity_id)
        self.assertEqual(store.entity(run)["runner_profile"], runner.entity_id)
        self.assertEqual(store.audit(), ())

    def test_store_updates_all_cts_vts_entity_types_transactionally(self) -> None:
        config = root_config()
        store = self.store(config)

        store.update_entity(EntityRef("cts_vts.runner", "runner-a"), {"host": "runner.example"})
        store.update_entity(
            EntityRef("cts_vts.board_profile", "boards-a"),
            {
                "device_update": {
                    "board_id": "board-a",
                    "field": "serial",
                    "value": "10.0.0.2:5555",
                }
            },
        )
        store.update_entity(
            EntityRef("cts_vts.test_profile", "tests-a"),
            {"suites": ["cts", "vts"], "no_progress_runs": 3},
        )
        store.update_entity(EntityRef("cts_vts.product_profile", "product-a"), {"name": "product-new"})
        store.update_entity(EntityRef("cts_vts.run", "run-a"), {"name": "run-new"})

        plugin = config["plugins"]["cts-vts"]["config"]
        self.assertEqual(plugin["runners"][0]["host"], "runner.example")
        self.assertEqual(plugin["board_profiles"][0]["devices"][0]["serial"], "10.0.0.2:5555")
        self.assertEqual(plugin["test_profiles"][0]["suites"], ["cts", "vts"])
        self.assertEqual(plugin["product_profiles"][0]["name"], "product-new")
        self.assertEqual(plugin["runs"][0]["name"], "run-new")
        self.assertEqual(plugin["runs"][0]["product_profile"], "product-a")
        self.assertEqual(store.audit(), ())

    def test_entity_update_cannot_bypass_reference_adapter(self) -> None:
        config = root_config()
        store = self.store(config)

        with self.assertRaisesRegex(ValueError, "reference API"):
            store.update_entity(
                EntityRef("cts_vts.product_profile", "product-a"),
                {"build_host": "host-b"},
            )

        product = config["plugins"]["cts-vts"]["config"]["product_profiles"][0]
        self.assertEqual(product["build_host"], "host-a")

    def test_owner_validation_rejects_invalid_cts_fields_without_saving(self) -> None:
        config = root_config()
        saved = []
        store = config_store(config, save=lambda value: saved.append(value.copy()))
        issues = store.initialize([core_profile_contributor(), config_contributor()])
        self.assertEqual(issues, ())

        invalid_updates = (
            (EntityRef("cts_vts.runner", "runner-a"), {"workspace_dir": "~/runs"}, "workspace"),
            (EntityRef("cts_vts.test_profile", "tests-a"), {"suites": ["gts"]}, "suites"),
            (
                EntityRef("cts_vts.test_profile", "tests-a"),
                {"extra_args": ["--serial", "device"]},
                "managed by the plugin",
            ),
            (
                EntityRef("cts_vts.test_profile", "tests-a"),
                {"adb_loss_timeout_minutes": 0},
                "positive integer",
            ),
            (
                EntityRef("cts_vts.board_profile", "boards-a"),
                {
                    "device_update": {
                        "board_id": "board-a",
                        "field": "serial",
                        "value": "bad serial",
                    }
                },
                "whitespace",
            ),
        )
        for reference, changes, message in invalid_updates:
            with self.subTest(reference=reference, changes=changes):
                with self.assertRaisesRegex(ValueError, message):
                    store.update_entity(reference, changes)

        self.assertEqual(saved, [])
        plugin = config["plugins"]["cts-vts"]["config"]
        self.assertNotIn("workspace_dir", plugin["runners"][0])
        self.assertNotIn("suites", plugin["test_profiles"][0])
        self.assertNotIn("serial", plugin["board_profiles"][0]["devices"][0])

    def test_owner_validation_rejects_invalid_cts_create_payload(self) -> None:
        config = root_config()
        store = self.store(config)

        with self.assertRaisesRegex(ValueError, "workspace"):
            store.create_entity(
                "cts_vts.runner",
                {
                    "name": "runner-b",
                    "label": "Runner B",
                    "user": "tester",
                    "host": "runner.example",
                    "workspace_dir": "",
                },
            )

        self.assertIsNone(store.entity(EntityRef("cts_vts.runner", "runner-b")))

    def test_audit_reports_external_reference_that_disappeared_outside_store(self) -> None:
        config = root_config()
        config["projects"] = [config["projects"][1]]
        store = config_store(config)

        issues = store.initialize([core_profile_contributor(), config_contributor()])

        self.assertEqual(len(issues), 2)
        self.assertEqual(
            {issue.link.target for issue in issues},
            {EntityRef("project", "project-a")},
        )
        self.assertEqual(
            {issue.adapter_name for issue in issues},
            {"core.active_project", "cts_vts.product_profile.project"},
        )

    def test_audit_preserves_and_reports_missing_internal_reference(self) -> None:
        config = root_config()
        plugin_config = config["plugins"]["cts-vts"]["config"]
        plugin_config["runners"] = []
        store = config_store(config)

        issues = store.initialize([core_profile_contributor(), config_contributor()])

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].link.target, EntityRef("cts_vts.runner", "runner-a"))
        self.assertEqual(plugin_config["runs"][0]["runner_profile"], "runner-a")


if __name__ == "__main__":
    unittest.main()
