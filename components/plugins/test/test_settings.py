from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from components.config.api.store import config_store
from components.plugins.src import settings
from components.plugins.src.model import PluginDefinition, PluginSetting, plugin_config


class FakeApp:
    def __init__(self) -> None:
        self.config: dict[str, object] = {}
        self.dependencies = SimpleNamespace(save_config=Mock())
        self.config_store = config_store(self.config, save=self.dependencies.save_config)
        self.status = ""
        self.prompt_cancelled = False
        self.prompt = Mock(return_value="12")


class PluginSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.definition = PluginDefinition("demo", "Demo", Path("."), Path("plugin.py"))
        self.app = FakeApp()

    def test_boolean_choice_and_integer_settings_are_edited_and_saved(self) -> None:
        enabled = PluginSetting("enabled", "Enabled", kind="boolean", default=False)
        mode = PluginSetting("mode", "Mode", kind="choice", default="quick", choices=("quick", "full"))
        timeout = PluginSetting("timeout", "Timeout", kind="integer", default=5, minimum=1, maximum=20)

        settings._edit_setting(self.app, self.definition, enabled)
        settings._edit_setting(self.app, self.definition, mode)
        settings._edit_setting(self.app, self.definition, timeout)

        values = plugin_config(self.app.config, "demo")
        self.assertEqual(values, {"enabled": True, "mode": "full", "timeout": 12})
        self.assertEqual(self.app.dependencies.save_config.call_count, 3)

    def test_invalid_integer_is_not_saved(self) -> None:
        timeout = PluginSetting("timeout", "Timeout", kind="integer", default=5, minimum=1)
        self.app.prompt.return_value = "not-a-number"

        settings._edit_setting(self.app, self.definition, timeout)

        self.assertNotIn("timeout", plugin_config(self.app.config, "demo"))
        self.app.dependencies.save_config.assert_not_called()
        self.assertIn("expected an integer", self.app.status)


if __name__ == "__main__":
    unittest.main()
