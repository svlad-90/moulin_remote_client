from __future__ import annotations

import unittest

from components.config.api.entities import core_profile_contributor
from components.config.api.store import EntityRef, config_store


class CoreProfileContributorTests(unittest.TestCase):
    def config(self):
        return {
            "remotes": [{"id": "host-a", "name": "host-a"}],
            "active_remote": "host-a",
            "board_hosts": [
                {"id": "board-host-a", "name": "board-host-a", "boards": []}
            ],
            "active_board_host": "board-host-a",
            "active_board": "",
            "projects": [{"id": "project-a", "name": "project-a", "label": "project-a"}],
            "active_project": "project-a",
        }

    def test_store_creates_all_core_profile_types(self) -> None:
        config = self.config()
        saved = []
        store = config_store(config, save=lambda value: saved.append(value.copy()))
        store.initialize([core_profile_contributor()])

        build_host = store.create_entity("build_host", {"name": "host-b"}).reference
        board_host = store.create_entity("board_host", {"name": "board-host-b"}).reference
        board = store.create_entity(
            "board",
            {"name": "board-b", "board_host_id": board_host.entity_id},
        ).reference
        project = store.create_entity(
            "project",
            {
                "name": "project-b",
                "parameters": {"ENABLE_DOMA": "yes"},
                "targets": ["doma", "full.img.gz"],
                "board_artifacts": ["boot_artifacts"],
                "docker_image": "builder",
            },
        ).reference

        self.assertEqual(store.entity(build_host)["name"], "host-b")
        self.assertEqual(store.entity(board_host)["name"], "board-host-b")
        self.assertEqual(store.entity(board)["board_host_id"], board_host.entity_id)
        self.assertEqual(store.entity(project)["parameters"], {"ENABLE_DOMA": "yes"})
        self.assertEqual(store.entity(project)["targets"], "doma full.img.gz")
        self.assertEqual(store.entity(project)["board_artifacts"], "boot_artifacts")
        self.assertEqual(config["active_board"], board.entity_id)
        self.assertEqual(config["active_project"], project.entity_id)
        self.assertEqual(len(saved), 4)
        self.assertEqual(store.audit(), ())

    def test_board_creation_requires_registered_parent_host(self) -> None:
        config = self.config()
        store = config_store(config)
        store.initialize([core_profile_contributor()])

        with self.assertRaisesRegex(ValueError, "Unknown board host"):
            store.create_entity(
                "board",
                {"name": "board-b", "board_host_id": "missing"},
            )

        self.assertIsNone(store.entity(EntityRef("board", "missing")))

    def test_store_updates_all_core_profile_types_transactionally(self) -> None:
        config = self.config()
        config["board_hosts"][0]["boards"] = [
            {
                "id": "board-a",
                "board_host_id": "board-host-a",
                "name": "board-a",
            }
        ]
        config["active_board"] = "board-a"
        saved = []
        store = config_store(config, save=lambda value: saved.append(value.copy()))
        store.initialize([core_profile_contributor()])

        store.update_entity(EntityRef("build_host", "host-a"), {"host": "10.0.0.1"})
        store.update_entity(EntityRef("board_host", "board-host-a"), {"work_dir": "/srv/tftp"})
        store.update_entity(EntityRef("board", "board-a"), {"commands": {"power_on": "x5h_on"}})
        store.update_entity(EntityRef("project", "project-a"), {"docker_image": "builder:new"})

        self.assertEqual(store.entity(EntityRef("build_host", "host-a"))["host"], "10.0.0.1")
        self.assertEqual(store.entity(EntityRef("board_host", "board-host-a"))["work_dir"], "/srv/tftp")
        self.assertEqual(
            store.entity(EntityRef("board", "board-a"))["commands"],
            {"power_on": "x5h_on"},
        )
        self.assertEqual(store.entity(EntityRef("project", "project-a"))["docker_image"], "builder:new")
        self.assertEqual(len(saved), 4)
        self.assertEqual(store.audit(), ())

    def test_board_update_rejects_ownership_change(self) -> None:
        config = self.config()
        config["board_hosts"][0]["boards"] = [
            {
                "id": "board-a",
                "board_host_id": "board-host-a",
                "name": "board-a",
            }
        ]
        config["active_board"] = "board-a"
        store = config_store(config)
        store.initialize([core_profile_contributor()])

        with self.assertRaisesRegex(ValueError, "ownership"):
            store.update_entity(
                EntityRef("board", "board-a"),
                {"board_host_id": "another-host"},
            )

        self.assertEqual(store.entity(EntityRef("board", "board-a"))["board_host_id"], "board-host-a")

    def test_owner_validation_rejects_invalid_core_fields_without_saving(self) -> None:
        config = self.config()
        config["board_hosts"][0]["boards"] = [
            {
                "id": "board-a",
                "board_host_id": "board-host-a",
                "name": "board-a",
                "type": "gen5_x5h",
            }
        ]
        saved = []
        store = config_store(config, save=lambda value: saved.append(value.copy()))
        store.initialize([core_profile_contributor()])

        invalid_updates = (
            (EntityRef("build_host", "host-a"), {"unknown": "value"}, "unsupported"),
            (EntityRef("board_host", "board-host-a"), {"direct_copy": "maybe"}, "yes or no"),
            (EntityRef("board", "board-a"), {"type": "missing-board-type"}, "unknown board type"),
            (EntityRef("project", "project-a"), {"product_type": "missing-product-type"}, "unknown product type"),
        )
        for reference, changes, message in invalid_updates:
            with self.subTest(reference=reference, changes=changes):
                with self.assertRaisesRegex(ValueError, message):
                    store.update_entity(reference, changes)

        self.assertEqual(saved, [])
        self.assertEqual(store.entity(EntityRef("board_host", "board-host-a")).get("direct_copy"), None)
        self.assertEqual(store.entity(EntityRef("board", "board-a"))["type"], "gen5_x5h")

    def test_owner_validation_rejects_invalid_core_create_payload(self) -> None:
        config = self.config()
        store = config_store(config)
        store.initialize([core_profile_contributor()])

        with self.assertRaisesRegex(ValueError, "parameters must be a string mapping"):
            store.create_entity(
                "project",
                {"name": "project-b", "parameters": {"ENABLE_DOMA": True}},
            )

        self.assertIsNone(store.entity(EntityRef("project", "project-b")))


if __name__ == "__main__":
    unittest.main()
