from __future__ import annotations

import unittest
from pathlib import Path

from components.cli.api import arguments


class CliArgumentBehaviorTests(unittest.TestCase):
    def test_parse_simple_command_uses_default_config(self) -> None:
        args = arguments.parse_args(["status"], description="desc", default_config=Path("config.json"))

        self.assertEqual(args.command, "status")
        self.assertEqual(args.config, Path("config.json"))

    def test_parse_config_override_and_mapping_names(self) -> None:
        args = arguments.parse_args(
            ["--config", "custom.json", "pull-map", "one", "two"],
            description=None,
            default_config=Path("config.json"),
        )

        self.assertEqual(args.config, Path("custom.json"))
        self.assertEqual(args.command, "pull-map")
        self.assertEqual(args.names, ["one", "two"])


if __name__ == "__main__":
    unittest.main()
