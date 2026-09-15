from __future__ import annotations

import unittest

from components.ui.api import preflight


class PreflightBehaviorTests(unittest.TestCase):
    def test_parse_preflight_values_ignores_non_key_value_lines(self) -> None:
        output = "noise\nproject=ok\n git = ## mirror...origin/mirror \n"

        self.assertEqual(
            preflight.parse_preflight_values(output),
            {"project": "ok", "git": "## mirror...origin/mirror"},
        )

    def test_format_ssh_only_preflight_matches_current_behavior(self) -> None:
        text, values = preflight.format_preflight("ssh=ok\ncwd=/home/user\n")

        self.assertEqual(values, {"ssh": "ok", "cwd": "/home/user"})
        self.assertEqual(text, "ssh ok | cwd /home/user")

    def test_format_full_preflight_matches_current_behavior(self) -> None:
        output = "\n".join(
            [
                "project=ok",
                "disk=48G free, 10% used",
                "git=## mirror...origin/mirror",
                "docker=ok",
                "origin=ok",
                "ref=ok",
            ]
        )

        text, values = preflight.format_preflight(output)

        self.assertEqual(values["project"], "ok")
        self.assertEqual(
            text,
            "project ok | disk 48G free, 10% used | git ## mirror...origin/mirror | docker ok | origin ok | ref ok",
        )

    def test_preflight_part_ok_matches_client_logic(self) -> None:
        self.assertTrue(preflight.preflight_part_ok("project ok"))
        self.assertTrue(preflight.preflight_part_ok("disk 48G free"))
        self.assertTrue(preflight.preflight_part_ok("git ## mirror"))
        self.assertTrue(preflight.preflight_part_ok("origin https://example"))
        self.assertTrue(preflight.preflight_part_ok("ref ok"))
        self.assertFalse(preflight.preflight_part_ok("docker missing"))
        self.assertFalse(preflight.preflight_part_ok("origin mismatch:https://example"))

    def test_prepare_remote_project_needed_matches_current_policy(self) -> None:
        for project in ("missing", "not-git", "not-directory", "inaccessible"):
            self.assertTrue(preflight.prepare_remote_project_needed({"project": project}, "git@example:repo"))
        self.assertTrue(preflight.prepare_remote_project_needed({"project": "ok", "origin": "missing"}, "git@example:repo"))
        self.assertFalse(preflight.prepare_remote_project_needed({"project": "ok", "origin": "missing"}, ""))
        self.assertTrue(preflight.prepare_remote_project_needed({"project": "ok", "origin": "mismatch:old"}, ""))
        self.assertFalse(preflight.prepare_remote_project_needed({"project": "ok", "origin": "ok"}, "git@example:repo"))

    def test_checkout_git_ref_needed_matches_current_policy(self) -> None:
        self.assertFalse(preflight.checkout_git_ref_needed({"ref": "missing"}, ""))
        self.assertTrue(preflight.checkout_git_ref_needed({"ref": "missing"}, "mirror"))
        self.assertTrue(preflight.checkout_git_ref_needed({"ref": "mismatch:main"}, "mirror"))
        self.assertFalse(preflight.checkout_git_ref_needed({"ref": "ok"}, "mirror"))

    def test_project_action_requirements_combines_prepare_and_checkout_flags(self) -> None:
        self.assertEqual(
            preflight.project_action_requirements(
                {"project": "missing", "ref": "mismatch:main"},
                project_git_url="git@example:repo",
                project_git_ref="mirror",
            ),
            {"prepare_remote_project": True, "checkout_git_ref": True},
        )
        self.assertEqual(
            preflight.project_action_requirements(
                {"project": "ok", "origin": "ok", "ref": "ok"},
                project_git_url="git@example:repo",
                project_git_ref="mirror",
            ),
            {"prepare_remote_project": False, "checkout_git_ref": False},
        )


if __name__ == "__main__":
    unittest.main()
