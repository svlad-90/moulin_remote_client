from __future__ import annotations

import unittest

from components.project_config.api import project_settings_service


class Harness:
    def __init__(self) -> None:
        self.service = project_settings_service.ProjectSettingsService()


class ProjectSettingsServiceTests(unittest.TestCase):
    def test_cycle_parameter_updates_build_params_and_returns_status(self) -> None:
        harness = Harness()
        params = {"ENABLE_ANDROID": "yes"}

        status = harness.service.cycle_parameter(
            params,
            {"name": "ENABLE_ANDROID", "default": "no", "choices": ["no", "yes"]},
        )

        self.assertEqual(params["ENABLE_ANDROID"], "no")
        self.assertEqual(status, "ENABLE_ANDROID=no")

    def test_cycle_parameter_keeps_state_when_choices_are_empty(self) -> None:
        harness = Harness()
        params = {"ENABLE_ANDROID": "yes"}

        status = harness.service.cycle_parameter(
            params,
            {"name": "ENABLE_ANDROID", "default": "no", "choices": []},
        )

        self.assertEqual(params["ENABLE_ANDROID"], "yes")
        self.assertIsNone(status)


if __name__ == "__main__":
    unittest.main()
