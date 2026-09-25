from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from components.config.api import profiles
from components.project.test import mapping_adapter as project_mappings


def sample_config() -> dict[str, object]:
    config: dict[str, object] = {
        "remotes": [{"name": "build", "user": "u", "host": "h"}],
        "active_remote": "build",
        "projects": [{"name": "prod", "project_dir": "meta-product"}],
        "active_project": "prod",
        "local": {"project_dir": "overlay"},
        "inventory": {"mapping_selection": "selected-mappings.txt"},
    }
    profiles.normalize_remote_profiles(config)
    profiles.normalize_project_profiles(config)
    return config


class ProjectMappingBehaviorTests(unittest.TestCase):
    def test_project_mappings_override_legacy_top_level_mappings(self) -> None:
        config = sample_config()
        project = profiles.active_project(config)
        config["mappings"] = [
            {
                "name": "legacy",
                "remote": "legacy/path",
                "local": "legacy/path",
                "kind": "directory",
            }
        ]
        project["mappings"] = [
            {
                "name": "project",
                "remote": "project/path",
                "local": "project/path",
                "kind": "file",
                "push": False,
            }
        ]

        self.assertEqual(
            project_mappings.mappings_for_config(config),
            [
                {
                    "name": "project",
                    "role": "",
                    "remote": "project/path",
                    "local": "project/path",
                    "kind": "file",
                    "push": False,
                }
            ],
        )

    def test_project_mapping_source_falls_back_to_legacy_mappings(self) -> None:
        self.assertEqual(
            project_mappings.mappings_from_project_config(
                {"name": "prod"},
                [{"name": "legacy", "remote": "legacy/path"}],
            ),
            [
                {
                    "name": "legacy",
                    "role": "",
                    "remote": "legacy/path",
                    "local": "legacy/path",
                    "kind": "directory",
                    "push": True,
                }
            ],
        )

    def test_active_mapping_selection_prefers_project_property(self) -> None:
        config = sample_config()
        project = profiles.active_project(config)
        project["active_mappings"] = [" project-path ", "", "other"]

        self.assertEqual(
            project_mappings.read_mapping_selection_for_config(config, Path("/tmp/unused-selection.txt"), required=False),
            ["project-path", "other"],
        )

    def test_active_mapping_state_reports_no_selection_without_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = sample_config()

            self.assertEqual(
                project_mappings.active_mapping_state_for_config(config, Path(tmpdir) / "missing.txt"),
                ([], [], None),
            )

    def test_active_mapping_state_selects_configured_mappings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = sample_config()
            project = profiles.active_project(config)
            project["mappings"] = [
                {"name": "one", "remote": "one"},
                {"name": "two", "remote": "two"},
            ]
            project["active_mappings"] = ["two"]

            self.assertEqual(
                project_mappings.active_mapping_state_for_config(config, Path(tmpdir) / "unused.txt"),
                (
                    ["two"],
                    [
                        {
                            "name": "two",
                            "role": "",
                            "remote": "two",
                            "local": "two",
                            "kind": "directory",
                            "push": True,
                        }
                    ],
                    None,
                ),
            )

    def test_active_mapping_state_returns_selection_error_as_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = sample_config()
            project = profiles.active_project(config)
            project["mappings"] = [{"name": "one", "remote": "one"}]
            project["active_mappings"] = ["missing"]

            self.assertEqual(
                project_mappings.active_mapping_state_for_config(config, Path(tmpdir) / "unused.txt"),
                (["missing"], [], "unknown mapping(s): missing"),
            )

    def test_write_mapping_selection_updates_project_and_legacy_file(self) -> None:
        config = sample_config()
        with tempfile.TemporaryDirectory() as tmpdir:
            selection = Path(tmpdir) / "selected-mappings.txt"
            config["__config_path"] = str(Path(tmpdir) / "config.json")
            config["inventory"]["mapping_selection"] = str(selection)

            project_mappings.write_mapping_selection_for_config(config, selection, ["one", "two"])

            self.assertEqual(profiles.active_project(config)["active_mappings"], ["one", "two"])
            self.assertEqual(selection.read_text(encoding="utf-8"), "one\ntwo\n")

    def test_add_mapping_to_active_project_validates_and_appends_current_shape(self) -> None:
        config = sample_config()

        mapping = project_mappings.add_mapping_to_active_project(
            config,
            name="new",
            role="",
            remote="./layers/meta-new/",
            local="overlay/meta-new",
            kind="directory",
            push=True,
        )

        self.assertEqual(
            mapping,
            {
                "name": "new",
                "role": "new",
                "remote": "layers/meta-new",
                "local": "overlay/meta-new",
                "kind": "directory",
                "push": True,
            },
        )
        self.assertEqual(profiles.active_project(config)["mappings"][-1], mapping)
        with self.assertRaisesRegex(ValueError, "already exists"):
            project_mappings.add_mapping_to_active_project(
                config,
                name="new",
                role="new",
                remote="layers/meta-new",
                local="overlay/meta-new",
                kind="directory",
                push=True,
            )
        with self.assertRaisesRegex(ValueError, "kind must be file or directory"):
            project_mappings.add_mapping_to_active_project(
                config,
                name="bad-kind",
                role="bad-kind",
                remote="layers/bad",
                local="layers/bad",
                kind="symlink",
                push=True,
            )

    def test_remove_mapping_from_active_project_by_name_or_remote_path(self) -> None:
        config = sample_config()
        project = profiles.active_project(config)
        project["mappings"] = [
            {"name": "one", "remote": "layers/one", "local": "layers/one"},
            {"name": "two", "remote": "./layers/two/", "local": "layers/two"},
        ]

        self.assertTrue(project_mappings.remove_mapping_from_active_project_by_name(config, "one"))
        self.assertEqual([mapping["name"] for mapping in project["mappings"]], ["two"])
        self.assertFalse(project_mappings.remove_mapping_from_active_project_by_name(config, "missing"))

        self.assertEqual(project_mappings.remove_mapping_from_active_project_by_remote_path(config, "layers/two"), ["two"])
        self.assertEqual(project["mappings"], [])
        self.assertEqual(project_mappings.remove_mapping_from_active_project_by_remote_path(config, "missing"), [])

    def test_mapping_path_mark_shows_partial_states(self) -> None:
        selected = {"layers/meta-xt-domd-gen5/recipes-core"}
        mapped = {"yocto/meta-xt-common", "layers/meta-xt-domu-gen5"}

        self.assertEqual(project_mappings.mapping_path_mark("layers", selected, mapped), "s")
        self.assertEqual(
            project_mappings.mapping_path_mark(
                "layers/meta-xt-domd-gen5/recipes-core", selected, mapped
            ),
            "S",
        )
        self.assertEqual(project_mappings.mapping_path_mark("yocto", selected, mapped), "+")
        self.assertEqual(project_mappings.mapping_path_mark("yocto/meta-xt-common", selected, mapped), "*")
        self.assertEqual(project_mappings.mapping_path_mark("doc", selected, mapped), " ")

    def test_mapping_browser_helpers_match_current_tree_display_policy(self) -> None:
        entries = [{"path": "src/backend", "kind": "directory"}, {"path": "README.md", "kind": "file"}]

        self.assertEqual(project_mappings.listing_with_parent_entry(".", entries), entries)
        self.assertEqual(
            project_mappings.listing_with_parent_entry("src/backend", entries),
            [{"path": "src", "kind": "parent"}] + entries,
        )
        self.assertEqual(project_mappings.mapping_browser_current_entry([], 5), {"path": "", "kind": "directory"})
        self.assertEqual(project_mappings.mapping_browser_current_entry(entries, 99), entries[1])
        self.assertEqual(project_mappings.mapping_browser_entry_name({"path": "src", "kind": "parent"}), "../")
        self.assertEqual(project_mappings.mapping_browser_entry_kind({"path": "src", "kind": "parent"}), "directory")
        self.assertEqual(
            project_mappings.mapping_browser_entry_label(
                {"path": "src/backend", "kind": "directory"},
                selected_paths={"src/backend"},
                mapped_paths={"README.md"},
            ),
            "S [d] backend/",
        )
        self.assertEqual(
            project_mappings.mapping_browser_entry_label(
                {"path": "README.md", "kind": "file"},
                selected_paths={"src/backend"},
                mapped_paths={"README.md"},
            ),
            "* [f] README.md",
        )

    def test_mapping_browser_key_action_matches_current_screen_policy(self) -> None:
        self.assertEqual(
            project_mappings.mapping_browser_key_action(entries_exist=True, current_kind="directory", up=True),
            {"action": "move", "delta": -1},
        )
        self.assertEqual(
            project_mappings.mapping_browser_key_action(entries_exist=True, current_kind="directory", down=True),
            {"action": "move", "delta": 1},
        )
        self.assertEqual(
            project_mappings.mapping_browser_key_action(entries_exist=True, current_kind="directory", enter=True),
            {"action": "open"},
        )
        self.assertEqual(
            project_mappings.mapping_browser_key_action(entries_exist=True, current_kind="file", enter=True),
            {"action": "status", "status": "Space toggles the selected file mapping"},
        )
        self.assertEqual(
            project_mappings.mapping_browser_key_action(entries_exist=True, current_kind="file", toggle=True),
            {"action": "toggle"},
        )
        self.assertEqual(
            project_mappings.mapping_browser_key_action(entries_exist=True, current_kind="file", edit_name=True),
            {"action": "edit_name"},
        )
        self.assertEqual(
            project_mappings.mapping_browser_key_action(entries_exist=False, current_kind="file", edit_name=True),
            {"action": "noop"},
        )
        self.assertEqual(
            project_mappings.mapping_browser_key_action(entries_exist=False, current_kind="file", quit_key=True),
            {"action": "quit"},
        )

    def test_mapping_browser_draft_helpers_match_current_defaults(self) -> None:
        entry = {"path": "layers/meta_xt/domd", "kind": "directory"}

        draft = project_mappings.mapping_draft_for_entry(entry)

        self.assertEqual(
            draft,
            {
                "path": "layers/meta_xt/domd",
                "name": "layers-meta-xt-domd",
                "local": "layers/meta_xt/domd",
                "role": "layers-meta-xt-domd",
                "push": True,
            },
        )
        self.assertIs(project_mappings.refresh_mapping_draft_for_entry(draft, entry), draft)
        self.assertEqual(project_mappings.mapping_name_from_path(""), "mapping")
        self.assertEqual(project_mappings.mapping_name_from_path("/a_b/c/"), "a-b-c")

        refreshed = project_mappings.refresh_mapping_draft_for_entry(draft, {"path": "doc", "kind": "directory"})
        self.assertEqual(refreshed["name"], "doc")
        self.assertEqual(refreshed["local"], "doc")

    def test_mapping_path_sets_and_state_label_match_browser_status(self) -> None:
        raw = [
            {"name": "selected", "remote": "layers/meta/recipes"},
            {"name": "mapped", "remote": "yocto/meta"},
            {"name": "bad", "remote": ""},
        ]

        mapped_paths, selected_paths = project_mappings.mapping_path_sets(raw, {"selected"})

        self.assertEqual(mapped_paths, {"layers/meta/recipes", "yocto/meta"})
        self.assertEqual(selected_paths, {"layers/meta/recipes"})
        self.assertEqual(project_mappings.mapping_state_label("layers/meta/recipes", selected_paths, mapped_paths), "selected")
        self.assertEqual(project_mappings.mapping_state_label("layers/meta", selected_paths, mapped_paths), "selected children")
        self.assertEqual(project_mappings.mapping_state_label("yocto/meta", selected_paths, mapped_paths), "yes")
        self.assertEqual(project_mappings.mapping_state_label("yocto", selected_paths, mapped_paths), "mapped children")
        self.assertEqual(project_mappings.mapping_state_label("doc", selected_paths, mapped_paths), "no")

    def test_mapping_path_validation_rejects_root_absolute_and_parent_paths(self) -> None:
        with self.assertRaises(ValueError):
            project_mappings.normalize_relpath(".")
        with self.assertRaises(ValueError):
            project_mappings.normalize_relpath("/absolute")
        with self.assertRaises(ValueError):
            project_mappings.normalize_relpath("../outside")

    def test_parse_ranges_accepts_commas_ranges_and_deduplicates(self) -> None:
        self.assertEqual(project_mappings.parse_ranges("3, 1 2-4 3", 5), [1, 2, 3, 4])

    def test_parse_ranges_rejects_out_of_range_selection(self) -> None:
        with self.assertRaisesRegex(ValueError, "selection index out of range: 6"):
            project_mappings.parse_ranges("1 6", 5)

    def test_read_selection_file_ignores_comments_and_normalizes_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            selection = Path(tmpdir) / "selection.txt"
            selection.write_text(" ./layers/meta/ # comment\n\nrecipes/foo\n", encoding="utf-8")

            self.assertEqual(project_mappings.read_selection_file(selection), ["layers/meta", "recipes/foo"])

    def test_inventory_text_formatting_and_selection_match_cli_shape(self) -> None:
        paths = project_mappings.parse_inventory_text("\n layers/meta \n\nrecipes/foo\n")

        self.assertEqual(paths, ["layers/meta", "recipes/foo"])
        self.assertEqual(project_mappings.format_inventory_choices(paths), ["   1  layers/meta", "   2  recipes/foo"])
        self.assertEqual(project_mappings.selected_paths_from_inventory_input("2 1", paths), ["layers/meta", "recipes/foo"])

    def test_run_inventory_fetch_writes_output_and_status_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "inventory.txt"
            lines: list[str] = []

            project_mappings.run_inventory_fetch(
                output,
                fetch_inventory_text=lambda: "layers/meta\nrecipes/foo\n",
                write_line=lines.append,
            )

            self.assertEqual(output.read_text(encoding="utf-8"), "layers/meta\nrecipes/foo\n")
            self.assertEqual(lines, [f"inventory: {output}", "directories: 2"])

    def test_run_inventory_choose_reads_inventory_and_writes_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            inventory = Path(tmpdir) / "inventory.txt"
            selection = Path(tmpdir) / "selection.txt"
            inventory.write_text("layers/meta\nrecipes/foo\n", encoding="utf-8")
            lines: list[str] = []

            project_mappings.run_inventory_choose(
                inventory,
                selection,
                read_input=lambda prompt: "2 1",
                write_line=lines.append,
            )

            self.assertEqual(selection.read_text(encoding="utf-8"), "layers/meta\nrecipes/foo\n")
            self.assertEqual(lines, ["   1  layers/meta", "   2  recipes/foo", f"selection: {selection}"])

    def test_local_mapping_issues_match_current_overlay_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            local_base = Path(tmpdir)
            layer = local_base / "layers/meta"
            layer.mkdir(parents=True)
            manifest = local_base / "prod.yaml"
            manifest.write_text("manifest\n", encoding="utf-8")

            self.assertIn(
                "local directory is empty",
                project_mappings.local_mapping_issue(
                    local_base,
                    {"name": "layer", "local": "layers/meta", "kind": "directory"},
                )
                or "",
            )
            (layer / "recipe.bb").write_text("x\n", encoding="utf-8")
            self.assertEqual(
                project_mappings.local_mapping_issues(
                    local_base,
                    [
                        {"name": "layer", "local": "layers/meta", "kind": "directory"},
                        {"name": "manifest", "local": "prod.yaml", "kind": "file"},
                    ],
                ),
                [],
            )

    def test_read_selection_file_reports_missing_or_empty_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            selection = Path(tmpdir) / "selection.txt"
            with self.assertRaises(SystemExit):
                project_mappings.read_selection_file(selection)
            selection.write_text("# only comments\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                project_mappings.read_selection_file(selection)

    def test_mapping_selection_prefers_project_and_falls_back_to_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            selection = Path(tmpdir) / "selected-mappings.txt"
            selection.write_text("from-file\n# comment\nother\n", encoding="utf-8")

            self.assertEqual(
                project_mappings.read_mapping_selection_from({"active_mappings": [" from-project "]}, selection, required=True),
                ["from-project"],
            )
            self.assertEqual(
                project_mappings.read_mapping_selection_from({"active_mappings": []}, selection, required=True),
                ["from-file", "other"],
            )

    def test_write_mapping_selection_file_preserves_empty_selection_as_empty_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            selection = Path(tmpdir) / "selected-mappings.txt"

            project_mappings.write_mapping_selection_file(selection, [])

            self.assertEqual(selection.read_text(encoding="utf-8"), "")

    def test_store_mapping_selection_for_config_updates_project_file_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            selection = Path(tmpdir) / "selected-mappings.txt"
            config = sample_config()
            saved: list[dict[str, object]] = []
            lines: list[str] = []

            project_mappings.store_mapping_selection_for_config(
                config,
                selection,
                ["one", "two"],
                save_config=saved.append,
                write_line=lines.append,
            )

            self.assertEqual(profiles.active_project(config)["active_mappings"], ["one", "two"])
            self.assertEqual(selection.read_text(encoding="utf-8"), "one\ntwo\n")
            self.assertEqual(saved, [config])
            self.assertEqual(lines, [f"mapping selection: {selection}"])

    def test_store_mapping_for_config_adds_mapping_and_selects_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            selection = Path(tmpdir) / "selected-mappings.txt"
            config = sample_config()
            saved: list[dict[str, object]] = []

            mapping = project_mappings.store_mapping_for_config(
                config,
                selection,
                name="backend-extra",
                role="",
                remote="services/scmi",
                local="services/scmi",
                kind="directory",
                push=True,
                save_config=saved.append,
            )

            self.assertEqual(mapping["name"], "backend-extra")
            self.assertEqual(mapping["role"], "backend-extra")
            self.assertIn("backend-extra", profiles.active_project(config)["active_mappings"])
            self.assertEqual(selection.read_text(encoding="utf-8"), "backend-extra\n")
            self.assertEqual(saved, [config, config])

    def test_remove_mapping_by_remote_path_for_config_removes_mapping_and_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            selection = Path(tmpdir) / "selected-mappings.txt"
            config = sample_config()
            profiles.active_project(config)["mappings"] = [
                {
                    "name": "backend",
                    "role": "backend",
                    "remote": "src/backend",
                    "local": "src/backend",
                    "kind": "directory",
                    "push": True,
                },
                {
                    "name": "backend-extra",
                    "role": "backend-extra",
                    "remote": "services/scmi",
                    "local": "services/scmi",
                    "kind": "directory",
                    "push": True,
                },
            ]
            profiles.active_project(config)["active_mappings"] = ["backend", "backend-extra"]
            saved: list[dict[str, object]] = []

            removed = project_mappings.remove_mapping_by_remote_path_for_config(
                config,
                selection,
                "services/scmi",
                save_config=saved.append,
            )

            self.assertEqual(removed, ["backend-extra"])
            self.assertEqual(
                [mapping["name"] for mapping in profiles.active_project(config)["mappings"]],
                ["backend"],
            )
            self.assertEqual(profiles.active_project(config)["active_mappings"], ["backend"])
            self.assertEqual(selection.read_text(encoding="utf-8"), "backend\n")
            self.assertEqual(saved, [config, config])

    def test_project_mapping_service_owns_add_select_and_remove_use_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            selection = Path(tmpdir) / "selected-mappings.txt"
            config = sample_config()
            saved: list[dict[str, object]] = []
            service = project_mappings.project_mapping_service()

            mapping = service.store_mapping_for_config(
                config,
                selection,
                name="domain",
                role="",
                remote="layers/domain",
                local="overlay/domain",
                kind="directory",
                push=True,
                save_config=saved.append,
            )

            self.assertEqual(mapping["name"], "domain")
            self.assertEqual(service.read_mapping_selection_for_config(config, selection, required=False), ["domain"])
            self.assertEqual(
                service.active_mapping_state_for_config(config, selection),
                (["domain"], [mapping], None),
            )

            removed = service.remove_mapping_by_remote_path_for_config(
                config,
                selection,
                "layers/domain",
                save_config=saved.append,
            )

            self.assertEqual(removed, ["domain"])
            self.assertEqual(service.mappings_for_config(config), [])
            self.assertEqual(service.read_mapping_selection_for_config(config, selection, required=False), [])
            self.assertEqual(saved, [config, config, config, config])

    def test_store_mapping_action_for_config_returns_current_tui_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            selection = Path(tmpdir) / "selected-mappings.txt"
            config = sample_config()
            saved: list[dict[str, object]] = []

            self.assertEqual(
                project_mappings.store_mapping_action_for_config(
                    config,
                    selection,
                    name="",
                    role="",
                    remote="services/scmi",
                    local="services/scmi",
                    kind="directory",
                    push=True,
                    save_config=saved.append,
                ),
                {"ok": False, "status": "Mapping add cancelled: empty name"},
            )

            added = project_mappings.store_mapping_from_tree_entry_action_for_config(
                config,
                selection,
                {"path": "services/scmi", "kind": "parent"},
                name="backend-extra",
                local="services/scmi",
                role="",
                push=True,
                save_config=saved.append,
            )
            self.assertTrue(added["ok"])
            self.assertEqual(added["status"], "Mapping added: backend-extra")
            self.assertEqual(added["mapping"]["kind"], "directory")

            duplicate = project_mappings.store_mapping_action_for_config(
                config,
                selection,
                name="backend-extra",
                role="",
                remote="services/scmi",
                local="services/scmi",
                kind="directory",
                push=True,
                save_config=saved.append,
            )
            self.assertEqual(duplicate, {"ok": False, "status": "Mapping already exists: backend-extra"})

    def test_remove_mapping_by_remote_path_action_for_config_returns_current_tui_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            selection = Path(tmpdir) / "selected-mappings.txt"
            config = sample_config()
            profiles.active_project(config)["mappings"] = [
                {
                    "name": "backend-extra",
                    "role": "backend-extra",
                    "remote": "services/scmi",
                    "local": "services/scmi",
                    "kind": "directory",
                    "push": True,
                },
            ]
            profiles.active_project(config)["active_mappings"] = ["backend-extra"]
            saved: list[dict[str, object]] = []

            removed = project_mappings.remove_mapping_by_remote_path_action_for_config(
                config,
                selection,
                "services/scmi",
                save_config=saved.append,
            )
            self.assertEqual(
                removed,
                {
                    "ok": True,
                    "status": "Mapping removed: backend-extra",
                    "removed_names": ["backend-extra"],
                },
            )
            self.assertEqual(
                project_mappings.remove_mapping_by_remote_path_action_for_config(
                    config,
                    selection,
                    "services/scmi",
                    save_config=saved.append,
                ),
                {"ok": False, "status": "Mapping not found: services/scmi"},
            )

    def test_mapping_browser_path_state_and_toggle_action_match_current_screen_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            selection = Path(tmpdir) / "selected-mappings.txt"
            config = sample_config()
            profiles.active_project(config)["mappings"] = [
                {
                    "name": "backend",
                    "role": "backend",
                    "remote": "src/backend",
                    "local": "src/backend",
                    "kind": "directory",
                    "push": True,
                },
            ]
            profiles.active_project(config)["active_mappings"] = ["backend"]
            saved: list[dict[str, object]] = []

            state = project_mappings.mapping_browser_path_state(config, selection)

            self.assertEqual(state["mapped_paths"], {"src/backend"})
            self.assertEqual(state["selected_paths"], {"src/backend"})
            removed = project_mappings.mapping_browser_toggle_action_for_config(
                config,
                selection,
                {"path": "src/backend", "kind": "directory"},
                {},
                mapped_paths=state["mapped_paths"],
                save_config=saved.append,
            )
            self.assertEqual(removed["status"], "Mapping removed: backend")

            added = project_mappings.mapping_browser_toggle_action_for_config(
                config,
                selection,
                {"path": "src/ui", "kind": "directory"},
                {"name": "ui", "local": "src/ui", "role": "ui", "push": True},
                mapped_paths=set(),
                save_config=saved.append,
            )
            self.assertEqual(added["status"], "Mapping added: ui")

    def test_project_browser_workflow_service_owns_tree_toggle_use_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            selection = Path(tmpdir) / "selected-mappings.txt"
            config = sample_config()
            profiles.active_project(config)["mappings"] = [
                {
                    "name": "backend",
                    "role": "backend",
                    "remote": "src/backend",
                    "local": "src/backend",
                    "kind": "directory",
                    "push": True,
                },
            ]
            profiles.active_project(config)["active_mappings"] = ["backend"]
            saved: list[dict[str, object]] = []
            service = project_mappings.project_browser_workflow_service()

            state = service.path_state(config, selection)
            self.assertEqual(state["mapped_paths"], {"src/backend"})
            self.assertEqual(service.current_entry([], 5), {"path": "", "kind": "directory"})
            self.assertEqual(
                service.key_action(entries_exist=True, current_kind="directory", enter=True),
                {"action": "open"},
            )

            removed = service.toggle_action_for_config(
                config,
                selection,
                {"path": "src/backend", "kind": "directory"},
                {},
                mapped_paths=state["mapped_paths"],
                save_config=saved.append,
            )
            added = service.toggle_action_for_config(
                config,
                selection,
                {"path": "src/ui", "kind": "directory"},
                {"name": "ui", "local": "src/ui", "role": "ui", "push": True},
                mapped_paths=set(),
                save_config=saved.append,
            )

            self.assertEqual(removed["status"], "Mapping removed: backend")
            self.assertEqual(added["status"], "Mapping added: ui")

    def test_mapping_selection_screen_helpers_match_current_tui_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            selection = Path(tmpdir) / "selected-mappings.txt"
            config = sample_config()
            profiles.active_project(config)["mappings"] = [
                {
                    "name": "backend",
                    "role": "backend role",
                    "remote": "src/backend",
                    "local": "src/backend",
                    "kind": "directory",
                    "push": True,
                },
                {
                    "name": "manifest",
                    "role": "manifest role",
                    "remote": "prod.yaml",
                    "local": "prod.yaml",
                    "kind": "file",
                    "push": False,
                },
            ]
            profiles.active_project(config)["active_mappings"] = ["backend"]
            state = project_mappings.mapping_selection_screen_state_for_config(config, selection)

            self.assertEqual([mapping["name"] for mapping in state["all_mappings"]], ["backend", "manifest"])
            self.assertEqual(state["selected"], {"backend"})
            self.assertEqual(
                project_mappings.mapping_selection_row_label(state["all_mappings"][0], state["selected"]),
                "[*] backend (directory, push)",
            )
            self.assertEqual(
                project_mappings.mapping_selection_row_label(state["all_mappings"][1], state["selected"]),
                "[ ] manifest (file, pull-only)",
            )
            self.assertEqual(
                project_mappings.mapping_selection_detail_for_config(
                    config,
                    Path(tmpdir),
                    state["all_mappings"][0],
                    selected_count=1,
                    total_count=2,
                ),
                {
                    "name": "backend",
                    "role": "backend role",
                    "kind": "directory",
                    "push": "yes",
                    "remote": "src/backend",
                    "local": str(Path(tmpdir) / "overlay" / "src/backend"),
                    "selected": "1/2",
                },
            )

    def test_mapping_selection_actions_update_project_selection_in_display_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            selection = Path(tmpdir) / "selected-mappings.txt"
            config = sample_config()
            profiles.active_project(config)["mappings"] = [
                {"name": "one", "remote": "one", "local": "one", "kind": "directory", "push": True},
                {"name": "two", "remote": "two", "local": "two", "kind": "directory", "push": True},
            ]
            profiles.active_project(config)["active_mappings"] = ["one"]
            saved: list[dict[str, object]] = []
            all_mappings = project_mappings.mappings_for_config(config)

            toggled = project_mappings.toggle_mapping_selection_for_config(
                config,
                selection,
                all_mappings,
                {"one"},
                1,
                save_config=saved.append,
            )
            self.assertEqual(toggled["selected"], {"one", "two"})
            self.assertEqual(toggled["status"], "Mapping activated: two")
            self.assertEqual(selection.read_text(encoding="utf-8"), "one\ntwo\n")

            cleared = project_mappings.clear_mapping_selection_for_config(
                config,
                selection,
                save_config=saved.append,
            )
            self.assertEqual(cleared, {"selected": set(), "status": "All mappings deactivated"})

            selected_all = project_mappings.select_all_mappings_for_config(
                config,
                selection,
                all_mappings,
                save_config=saved.append,
            )
            self.assertEqual(selected_all["selected"], {"one", "two"})
            self.assertEqual(selected_all["status"], "All mappings activated")

            deleted = project_mappings.delete_mapping_selection_action_for_config(
                config,
                selection,
                "one",
                save_config=saved.append,
            )
            self.assertTrue(deleted["ok"])
            self.assertEqual(deleted["status"], "Mapping deleted: one")
            self.assertEqual([mapping["name"] for mapping in deleted["all_mappings"]], ["two"])
            self.assertEqual(deleted["selected"], {"two"})

    def test_mapping_selection_key_action_matches_current_screen_policy(self) -> None:
        self.assertEqual(
            project_mappings.mapping_selection_key_action(mappings_exist=True, up=True),
            {"action": "move", "delta": -1},
        )
        self.assertEqual(
            project_mappings.mapping_selection_key_action(mappings_exist=True, down=True),
            {"action": "move", "delta": 1},
        )
        self.assertEqual(
            project_mappings.mapping_selection_key_action(mappings_exist=True, toggle=True),
            {"action": "toggle"},
        )
        self.assertEqual(
            project_mappings.mapping_selection_key_action(mappings_exist=True, delete=True),
            {"action": "delete"},
        )
        self.assertEqual(
            project_mappings.mapping_selection_key_action(mappings_exist=True, all_key=True),
            {"action": "all"},
        )
        self.assertEqual(
            project_mappings.mapping_selection_key_action(mappings_exist=True, none_key=True),
            {"action": "none"},
        )
        self.assertEqual(
            project_mappings.mapping_selection_key_action(mappings_exist=False, add_key=True),
            {"action": "add"},
        )
        self.assertEqual(
            project_mappings.mapping_selection_key_action(mappings_exist=False, toggle=True),
            {"action": "noop"},
        )

    def test_mapping_listing_for_config_matches_cli_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            selection = app_dir / "selected-mappings.txt"
            config = {
                "local": {"project_dir": str(app_dir / "overlay")},
                "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
                "active_remote": "build",
                "projects": [
                    {
                        "name": "prod",
                        "project_dir": "meta-product",
                        "active_mappings": ["meta"],
                        "mappings": [
                            {
                                "name": "meta",
                                "role": "source layer",
                                "remote": "layers/meta",
                                "local": "layers/meta",
                                "kind": "directory",
                                "push": True,
                            },
                            {
                                "name": "manifest",
                                "role": "",
                                "remote": "prod.yaml",
                                "kind": "file",
                                "push": False,
                            },
                        ],
                    }
                ],
                "active_project": "prod",
            }

            self.assertEqual(
                project_mappings.format_mapping_listing_for_config(config, selection, app_dir),
                [
                    f"local overlay: {app_dir / 'overlay'}",
                    "remote project: builder@10.0.0.1:/mnt/projects/meta-product",
                    "",
                    "* meta [directory, push]",
                    "  role:   source layer",
                    "  remote: layers/meta",
                    "  local:  layers/meta",
                    "",
                    "  manifest [file, pull-only]",
                    "  role:   ",
                    "  remote: prod.yaml",
                    "  local:  prod.yaml",
                ],
            )

    def test_mapping_selection_prompt_and_input_parser_match_cli_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            selection = app_dir / "selected-mappings.txt"
            mappings = [
                {"name": "one", "role": "first", "remote": "one", "local": "one", "kind": "directory", "push": True},
                {"name": "two", "role": "second", "remote": "two", "local": "two", "kind": "directory", "push": True},
            ]
            config = {
                "local": {"project_dir": str(app_dir / "overlay")},
                "remotes": [{"name": "build", "user": "builder", "host": "10.0.0.1", "projects_dir": "/mnt/projects"}],
                "active_remote": "build",
                "projects": [{"name": "prod", "project_dir": "meta-product", "active_mappings": ["two"], "mappings": mappings}],
                "active_project": "prod",
            }

            self.assertEqual(
                project_mappings.format_mapping_selection_prompt_for_config(config, selection, app_dir),
                [
                    f"local overlay: {app_dir / 'overlay'}",
                    "remote project: builder@10.0.0.1:/mnt/projects/meta-product",
                    "",
                    "Mapping areas:",
                    "  1. [ ] one",
                    "     first",
                    "     remote: one",
                    "     local:  one",
                    "  2. [*] two",
                    "     second",
                    "     remote: two",
                    "     local:  two",
                    "",
                    "Input numbers/ranges, for example: 1 3-4",
                    "Input 'all' to select all, 'none' to clear, or Enter to keep current.",
                ],
            )
            self.assertIsNone(project_mappings.mapping_names_from_selection_input("", mappings))
            self.assertEqual(project_mappings.mapping_names_from_selection_input("all", mappings), ["one", "two"])
            self.assertEqual(project_mappings.mapping_names_from_selection_input("none", mappings), [])
            self.assertEqual(project_mappings.mapping_names_from_selection_input("2,1", mappings), ["one", "two"])

    def test_run_mapping_listing_for_config_writes_joined_listing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            lines: list[str] = []
            config = sample_config()

            project_mappings.run_mapping_listing_for_config(
                config,
                app_dir / "selected-mappings.txt",
                app_dir,
                write_line=lines.append,
            )

            self.assertEqual(len(lines), 1)
            self.assertIn("local overlay:", lines[0])
            self.assertIn("remote project:", lines[0])

    def test_run_project_status_for_config_runs_du_and_remote_probe_when_overlay_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_dir = app_dir / "overlay"
            local_dir.mkdir()
            lines: list[str] = []
            local_runs: list[list[str]] = []
            remote_runs: list[list[str]] = []
            config = sample_config()
            config["local"] = {"project_dir": str(local_dir)}
            profiles.active_project(config)["mappings"] = [{"name": "one", "remote": "one"}]

            project_mappings.run_project_status_for_config(
                config,
                app_dir,
                remote_probe_command=["ssh", "remote", "status"],
                local_runner=local_runs.append,
                remote_runner=remote_runs.append,
                write_line=lines.append,
            )

            self.assertEqual(lines[0], f"local overlay: {local_dir}")
            self.assertEqual(lines[2], "mapped areas: 1")
            self.assertEqual(local_runs, [["du", "-sh", str(local_dir)]])
            self.assertEqual(remote_runs, [["ssh", "remote", "status"]])

    def test_run_project_status_for_config_reports_missing_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            lines: list[str] = []
            local_runs: list[list[str]] = []
            remote_runs: list[list[str]] = []
            config = sample_config()
            config["local"] = {"project_dir": str(app_dir / "missing")}

            project_mappings.run_project_status_for_config(
                config,
                app_dir,
                remote_probe_command=["ssh", "remote", "status"],
                local_runner=local_runs.append,
                remote_runner=remote_runs.append,
                write_line=lines.append,
            )

            self.assertIn("local overlay does not exist yet", lines)
            self.assertEqual(local_runs, [])
            self.assertEqual(remote_runs, [["ssh", "remote", "status"]])

    def test_run_mapping_selection_for_config_updates_config_and_selection_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            selection = app_dir / "selected-mappings.txt"
            saved: list[dict[str, object]] = []
            lines: list[str] = []
            config = sample_config()
            profiles.active_project(config)["mappings"] = [
                {"name": "one", "remote": "one"},
                {"name": "two", "remote": "two"},
            ]

            project_mappings.run_mapping_selection_for_config(
                config,
                selection,
                app_dir,
                read_input=lambda prompt: "2",
                write_line=lines.append,
                save_config=saved.append,
            )

            self.assertEqual(profiles.active_project(config)["active_mappings"], ["two"])
            self.assertEqual(selection.read_text(encoding="utf-8"), "two\n")
            self.assertEqual(saved, [config])
            self.assertEqual(lines[-1], f"mapping selection: {selection}")

    def test_run_cli_project_command_for_config_routes_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            local_dir = app_dir / "overlay"
            local_dir.mkdir()
            lines: list[str] = []
            local_runs: list[list[str]] = []
            remote_runs: list[list[str]] = []
            config = sample_config()
            config["local"] = {"project_dir": str(local_dir)}

            project_mappings.run_cli_project_command_for_config(
                config,
                "status",
                app_dir=app_dir,
                docker_image="prod-image",
                structured_script=lambda _steps: "status-script",
                capture_command=lambda _argv: "",
                local_runner=local_runs.append,
                remote_runner=remote_runs.append,
                read_input=lambda _prompt: "",
                write_line=lines.append,
                save_config=lambda _config: None,
            )

            self.assertEqual(lines[0], f"local overlay: {local_dir}")
            self.assertEqual(local_runs, [["du", "-sh", str(local_dir)]])
            self.assertEqual(remote_runs[0][0], "ssh")
            self.assertIn("u@h", remote_runs[0])
            self.assertIn("cd meta-product", remote_runs[0][-1])
            self.assertIn("status-script", remote_runs[0][-1])

    def test_run_cli_project_command_for_config_routes_inventory_and_choose_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            inventory = app_dir / "inventory.txt"
            selection = app_dir / "selection.txt"
            lines: list[str] = []
            config = sample_config()
            config["inventory"] = {
                "output": str(inventory),
                "selection": str(selection),
                "mapping_selection": str(app_dir / "selected-mappings.txt"),
            }

            project_mappings.run_cli_project_command_for_config(
                config,
                "inventory",
                app_dir=app_dir,
                docker_image="",
                structured_script=lambda _steps: "",
                capture_command=lambda _argv: "prod.yaml\nlayers/meta\n",
                local_runner=lambda _argv: None,
                remote_runner=lambda _argv: None,
                read_input=lambda _prompt: "",
                write_line=lines.append,
                save_config=lambda _config: None,
            )
            project_mappings.run_cli_project_command_for_config(
                config,
                "choose",
                app_dir=app_dir,
                docker_image="",
                structured_script=lambda _steps: "",
                capture_command=lambda _argv: "",
                local_runner=lambda _argv: None,
                remote_runner=lambda _argv: None,
                read_input=lambda _prompt: "2",
                write_line=lines.append,
                save_config=lambda _config: None,
            )

            self.assertEqual(inventory.read_text(encoding="utf-8"), "prod.yaml\nlayers/meta\n")
            self.assertEqual(selection.read_text(encoding="utf-8"), "layers/meta\n")

    def test_project_cli_workflow_service_routes_select_mappings_use_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            selection = app_dir / "selected-mappings.txt"
            saved: list[dict[str, object]] = []
            lines: list[str] = []
            config = sample_config()
            config["inventory"] = {"mapping_selection": str(selection)}
            profiles.active_project(config)["mappings"] = [
                {"name": "one", "remote": "one"},
                {"name": "two", "remote": "two"},
            ]
            service = project_mappings.project_cli_workflow_service()

            service.run_cli_project_command_for_config(
                config,
                "select-mappings",
                app_dir=app_dir,
                docker_image="",
                structured_script=lambda _steps: "",
                capture_command=lambda _argv: "",
                local_runner=lambda _argv: None,
                remote_runner=lambda _argv: None,
                read_input=lambda _prompt: "all",
                write_line=lines.append,
                save_config=saved.append,
            )

            self.assertEqual(profiles.active_project(config)["active_mappings"], ["one", "two"])
            self.assertEqual(selection.read_text(encoding="utf-8"), "one\ntwo\n")
            self.assertEqual(saved, [config])
            self.assertEqual(lines[-1], f"mapping selection: {selection}")


if __name__ == "__main__":
    unittest.main()
