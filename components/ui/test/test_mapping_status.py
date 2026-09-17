from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from components.ui.api import mapping_status


class MappingStatusBehaviorTests(unittest.TestCase):
    def test_local_mapping_issue_reports_missing_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            issue = mapping_status.local_mapping_issue(
                Path(tmpdir),
                {"name": "layer", "local": "layers/meta", "kind": "directory"},
            )

            self.assertIn("layer: local path missing:", issue or "")

    def test_local_mapping_issue_reports_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            local = Path(tmpdir) / "layers/meta"
            local.mkdir(parents=True)

            self.assertIn(
                "local directory is empty",
                mapping_status.local_mapping_issue(
                    Path(tmpdir),
                    {"name": "layer", "local": "layers/meta", "kind": "directory"},
                )
                or "",
            )

    def test_local_mapping_issue_accepts_non_empty_directory_and_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            local_base = Path(tmpdir)
            layer = local_base / "layers/meta"
            layer.mkdir(parents=True)
            (layer / "recipe.bb").write_text("x\n", encoding="utf-8")
            manifest = local_base / "prod.yaml"
            manifest.write_text("manifest\n", encoding="utf-8")

            self.assertIsNone(
                mapping_status.local_mapping_issue(
                    local_base,
                    {"name": "layer", "local": "layers/meta", "kind": "directory"},
                )
            )
            self.assertIsNone(
                mapping_status.local_mapping_issue(
                    local_base,
                    {"name": "manifest", "local": "prod.yaml", "kind": "file"},
                )
            )

    def test_mapping_status_text_matches_current_states(self) -> None:
        self.assertEqual(mapping_status.mapping_status_text([], [], None, []), "0 active | copy no")
        self.assertEqual(
            mapping_status.mapping_status_text(["one", "two"], [], "bad selection", []),
            "2 selected | invalid selection",
        )
        self.assertEqual(
            mapping_status.mapping_status_text(["one"], [{"name": "one"}], None, ["missing"]),
            "1 active | needs pull before copy",
        )
        self.assertEqual(
            mapping_status.mapping_status_text(["one"], [{"name": "one"}], None, []),
            "1 active | copy ready",
        )

    def test_mapping_status_snapshot_matches_current_text_and_role_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            local_base = Path(tmpdir)
            layer = local_base / "layers/meta"
            layer.mkdir(parents=True)
            (layer / "recipe.bb").write_text("x\n", encoding="utf-8")

            self.assertEqual(
                mapping_status.mapping_status_snapshot([], [], None, local_base=local_base),
                {"text": "0 active | copy no", "role": "disabled"},
            )
            self.assertEqual(
                mapping_status.mapping_status_snapshot(["one"], [], "bad selection", local_base=local_base),
                {"text": "1 selected | invalid selection", "role": "warn"},
            )
            self.assertEqual(
                mapping_status.mapping_status_snapshot(
                    ["one"],
                    [{"name": "one", "local": "missing", "kind": "directory"}],
                    None,
                    local_base=local_base,
                ),
                {"text": "1 active | needs pull before copy", "role": "warn"},
            )
            self.assertEqual(
                mapping_status.mapping_status_snapshot(
                    ["one"],
                    [{"name": "one", "local": "layers/meta", "kind": "directory"}],
                    None,
                    local_base=local_base,
                ),
                {"text": "1 active | copy ready", "role": "ok"},
            )


if __name__ == "__main__":
    unittest.main()
