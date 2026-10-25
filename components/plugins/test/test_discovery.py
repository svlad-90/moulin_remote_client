from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from components.plugins.src.discovery import PluginDiscovery


class PluginDiscoveryTests(unittest.TestCase):
    def test_discovers_manifest_settings_actions_and_views(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "plugins" / "diagnostics"
            root.mkdir(parents=True)
            (root / "helper.py").write_text("VALUE = 'loaded'\n", encoding="utf-8")
            (root / "plugin.py").write_text(
                "from .helper import VALUE\n\ndef run(context):\n    return VALUE\n",
                encoding="utf-8",
            )
            (root / "plugin.yaml").write_text(
                """api_version: 1
id: diagnostics
name: Board diagnostics
settings:
  timeout:
    type: integer
    label: Timeout
    default: 10
    minimum: 1
tabs:
  - id: checks
    label: Checks
    actions:
      - id: run
        label: Run checks
        description: Check every board.
        handler: run
        job_slot: board
views:
  - id: matrix
    label: Board matrix
    factory: create_matrix
""",
                encoding="utf-8",
            )

            definitions = PluginDiscovery(Path(tmp) / "plugins").discover()

            self.assertEqual(len(definitions), 1)
            definition = definitions[0]
            self.assertEqual(definition.plugin_id, "diagnostics")
            self.assertEqual(definition.settings[0].default, 10)
            self.assertEqual(definition.actions[0].job_slot, "board")
            self.assertEqual(definition.actions[0].tab_label, "Checks")
            self.assertEqual(definition.views["matrix"].factory, "create_matrix")
            self.assertFalse(definition.error)
            self.assertEqual(PluginDiscovery(Path(tmp) / "plugins").load_module(definition).VALUE, "loaded")

    def test_invalid_plugin_is_reported_without_stopping_other_plugins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugins = Path(tmp) / "plugins"
            invalid = plugins / "invalid"
            valid = plugins / "valid"
            invalid.mkdir(parents=True)
            valid.mkdir(parents=True)
            (invalid / "plugin.yaml").write_text("api_version: 99\nid: invalid\n", encoding="utf-8")
            (valid / "plugin.py").write_text("def run(context):\n    pass\n", encoding="utf-8")
            (valid / "plugin.yaml").write_text(
                "api_version: 1\nid: valid\nentrypoint: plugin.py\n",
                encoding="utf-8",
            )

            definitions = PluginDiscovery(plugins).discover()

            self.assertEqual([item.plugin_id for item in definitions], ["invalid", "valid"])
            self.assertIn("unsupported api_version", definitions[0].error)
            self.assertFalse(definitions[1].error)


if __name__ == "__main__":
    unittest.main()
