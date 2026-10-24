from __future__ import annotations

import unittest
from dataclasses import dataclass

from components.config.api.store import (
    ConfigRegistrar,
    ConfigStoreError,
    DeletePolicy,
    DeletionRestrictedError,
    EntityAdapter,
    EntityRef,
    ReferenceAdapter,
    ReferenceLink,
    StaleDeletionPlanError,
    UnsupportedEntityOperationError,
    config_store,
)


def records(key):
    return lambda config: config[key]


def delete_record(key):
    def apply(config, entity_id):
        config[key] = [item for item in config[key] if item["id"] != entity_id]

    return apply


def create_record(key):
    def apply(config, entity_id, values):
        config[key].append({**values, "id": entity_id})

    return apply


def update_record(key):
    def apply(config, entity_id, changes):
        next(item for item in config[key] if item["id"] == entity_id).update(changes)

    return apply


@dataclass(frozen=True)
class Contributor:
    policy: DeletePolicy = DeletePolicy.DETACH

    def contribute_config(self, registrar: ConfigRegistrar) -> None:
        registrar.register_entity(
            EntityAdapter(
                "target",
                records("targets"),
                delete_record("targets"),
                create=create_record("targets"),
                update=update_record("targets"),
            )
        )
        registrar.register_entity(
            EntityAdapter(
                "source",
                records("sources"),
                delete_record("sources"),
                create=create_record("sources"),
                update=update_record("sources"),
            )
        )
        registrar.register_reference(
            ReferenceAdapter(
                name="source.target",
                source_kind="source",
                target_kind="target",
                policy=self.policy,
                links=lambda config: (
                    ReferenceLink(
                        EntityRef("source", item["id"]),
                        EntityRef("target", item["target"]),
                        f"source {item['id']} will be updated",
                    )
                    for item in config["sources"]
                    if item.get("target")
                ),
                detach=lambda config, link: next(
                    item for item in config["sources"] if item["id"] == link.source.entity_id
                ).update(target=""),
                replace=lambda config, source, targets: next(
                    item for item in config["sources"] if item["id"] == source.entity_id
                ).update(target=targets[0].entity_id if targets else ""),
            )
        )


class ConfigStoreTests(unittest.TestCase):
    def config(self):
        return {
            "targets": [{"id": "target-a", "name": "Target A"}],
            "sources": [{"id": "source-a", "name": "Source A", "target": "target-a"}],
        }

    def test_audit_reports_missing_target(self) -> None:
        config = self.config()
        config["sources"][0]["target"] = "missing"
        store = config_store(config)

        issues = store.initialize([Contributor()])

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].link.target, EntityRef("target", "missing"))

    def test_contributor_is_notified_about_issues_in_its_entities(self) -> None:
        class NotifiedContributor:
            def __init__(self) -> None:
                self.issues = None

            def contribute_config(self, registrar: ConfigRegistrar) -> None:
                Contributor().contribute_config(registrar)

            def on_reference_issues(self, issues) -> None:
                self.issues = issues

        config = self.config()
        config["sources"][0]["target"] = "missing"
        contributor = NotifiedContributor()
        store = config_store(config)

        issues = store.initialize([contributor])

        self.assertEqual(contributor.issues, issues)

    def test_delete_detaches_reference_and_saves_once(self) -> None:
        config = self.config()
        saved = []
        events = []
        store = config_store(config, save=lambda value: saved.append(value.copy()))
        store.initialize([Contributor()])
        store.subscribe(events.append)

        plan = store.prepare_delete(EntityRef("target", "target-a"))
        event = store.execute_delete(plan)

        self.assertEqual(config["targets"], [])
        self.assertEqual(config["sources"][0]["target"], "")
        self.assertEqual(len(saved), 1)
        self.assertEqual(event.updated, (EntityRef("source", "source-a"),))
        self.assertEqual(events, [event])

    def test_restrict_blocks_delete_without_mutating_config(self) -> None:
        config = self.config()
        store = config_store(config)
        store.initialize([Contributor(DeletePolicy.RESTRICT)])
        plan = store.prepare_delete(EntityRef("target", "target-a"))

        with self.assertRaises(DeletionRestrictedError):
            store.execute_delete(plan)

        self.assertEqual(config, self.config())

    def test_create_entity_assigns_immutable_id_and_saves_once(self) -> None:
        config = self.config()
        saved = []
        events = []
        store = config_store(config, save=lambda value: saved.append(value.copy()))
        store.initialize([Contributor()])
        store.subscribe(events.append)

        result = store.create_entity("target", {"name": "Target B"})

        self.assertEqual(store.entity(result.reference)["name"], "Target B")
        self.assertEqual(result.reference.entity_id, store.entity(result.reference)["id"])
        self.assertEqual(result.change.created, (result.reference,))
        self.assertEqual(result.change.updated, ())
        self.assertEqual(events, [result.change])
        self.assertEqual(len(saved), 1)

    def test_create_entity_rejects_caller_supplied_id(self) -> None:
        config = self.config()
        store = config_store(config)
        store.initialize([Contributor()])

        with self.assertRaisesRegex(Exception, "id is assigned"):
            store.create_entity("target", {"id": "chosen", "name": "Target B"})

        self.assertEqual(config, self.config())

    def test_update_entity_preserves_id_and_saves_once(self) -> None:
        config = self.config()
        config["targets"].append({"id": "target-b", "name": "Target B"})
        saved = []
        store = config_store(config, save=lambda value: saved.append(value.copy()))
        store.initialize([Contributor()])
        source = EntityRef("source", "source-a")

        event = store.update_entity(source, {"name": "Renamed", "target": "target-b"})

        self.assertEqual(store.entity(source)["name"], "Renamed")
        self.assertEqual(store.entity(source)["target"], "target-b")
        self.assertEqual(event.updated, (source,))
        self.assertEqual(len(saved), 1)

    def test_update_entity_rejects_new_broken_reference(self) -> None:
        config = self.config()
        store = config_store(config)
        store.initialize([Contributor()])

        with self.assertRaisesRegex(Exception, "entity update would create invalid references"):
            store.update_entity(EntityRef("source", "source-a"), {"target": "missing"})

        self.assertEqual(config, self.config())

    def test_entity_adapter_operations_are_explicitly_optional(self) -> None:
        config = self.config()
        store = config_store(config)
        registrar_only = EntityAdapter("target", records("targets"), delete_record("targets"))

        class ReadOnlyContributor:
            def contribute_config(self, registrar):
                registrar.register_entity(registrar_only)

        store.initialize([ReadOnlyContributor()])

        with self.assertRaises(UnsupportedEntityOperationError):
            store.create_entity("target", {"name": "Target B"})
        with self.assertRaises(UnsupportedEntityOperationError):
            store.update_entity(EntityRef("target", "target-a"), {"name": "Renamed"})

    def test_replace_reference_validates_and_saves_once(self) -> None:
        config = self.config()
        config["targets"].append({"id": "target-b", "name": "Target B"})
        saved = []
        store = config_store(config, save=lambda value: saved.append(value.copy()))
        store.initialize([Contributor()])

        event = store.replace_references(
            "source.target",
            EntityRef("source", "source-a"),
            (EntityRef("target", "target-b"),),
        )

        self.assertEqual(config["sources"][0]["target"], "target-b")
        self.assertEqual(len(saved), 1)
        self.assertEqual(event.updated, (EntityRef("source", "source-a"),))

    def test_replace_reference_rejects_unknown_target_without_mutation(self) -> None:
        config = self.config()
        store = config_store(config)
        store.initialize([Contributor()])

        with self.assertRaisesRegex(Exception, "unknown configuration entity"):
            store.replace_references(
                "source.target",
                EntityRef("source", "source-a"),
                (EntityRef("target", "missing"),),
            )

        self.assertEqual(config, self.config())

    def test_stale_plan_is_rejected(self) -> None:
        config = self.config()
        store = config_store(config)
        store.initialize([Contributor()])
        plan = store.prepare_delete(EntityRef("target", "target-a"))
        config["sources"].append({"id": "source-b", "name": "Source B", "target": "target-a"})

        with self.assertRaises(StaleDeletionPlanError):
            store.execute_delete(plan)

    def test_failed_delete_rolls_back_detach(self) -> None:
        config = self.config()
        store = config_store(config)

        @dataclass(frozen=True)
        class FailingContributor(Contributor):
            def contribute_config(self, registrar: ConfigRegistrar) -> None:
                super().contribute_config(registrar)
                original = registrar.entities["target"]
                registrar.entities["target"] = EntityAdapter(
                    original.kind,
                    original.records,
                    lambda _config, _entity_id: (_ for _ in ()).throw(RuntimeError("delete failed")),
                )

        store.initialize([FailingContributor()])
        plan = store.prepare_delete(EntityRef("target", "target-a"))

        with self.assertRaisesRegex(RuntimeError, "delete failed"):
            store.execute_delete(plan)

        self.assertEqual(config, self.config())

    def test_failed_save_rolls_back_committed_configuration(self) -> None:
        config = self.config()
        store = config_store(
            config,
            save=lambda _config: (_ for _ in ()).throw(OSError("save failed")),
        )
        store.initialize([Contributor()])
        plan = store.prepare_delete(EntityRef("target", "target-a"))

        with self.assertRaisesRegex(OSError, "save failed"):
            store.execute_delete(plan)

        self.assertEqual(config, self.config())
        self.assertEqual(store.revision, 0)

    def test_non_entity_setting_update_is_transactional(self) -> None:
        config = self.config()
        saved = []
        store = config_store(config, save=lambda value: saved.append(value.copy()))
        store.initialize([Contributor()])

        event = store.update_config(
            lambda staged: staged.setdefault("ui", {}).__setitem__("show_commands", True)
        )

        self.assertEqual(config["ui"], {"show_commands": True})
        self.assertEqual(len(saved), 1)
        self.assertEqual(event.revision, 1)

    def test_non_entity_setting_update_rejects_new_reference_issue(self) -> None:
        config = self.config()
        store = config_store(config)
        store.initialize([Contributor()])

        with self.assertRaisesRegex(ConfigStoreError, "configuration update"):
            store.update_config(
                lambda staged: staged["sources"][0].__setitem__("target", "missing")
            )

        self.assertEqual(config, self.config())


if __name__ == "__main__":
    unittest.main()
