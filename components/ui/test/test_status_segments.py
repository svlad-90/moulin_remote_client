from __future__ import annotations

import unittest

from components.ui.api import status_segments


class StatusSegmentBehaviorTests(unittest.TestCase):
    def test_build_param_segments_preserve_current_text_and_roles(self) -> None:
        self.assertEqual(
            status_segments.build_param_segments({"ENABLE_DOMU": "no", "ENABLE_ANDROID": "yes"}),
            [
                ("Params: ", "accent"),
                ("ANDROID=", "normal"),
                ("yes", "ok"),
                ("  ", "normal"),
                ("DOMU=", "normal"),
                ("no", "warn"),
            ],
        )

    def test_preflight_segments_preserve_current_roles(self) -> None:
        self.assertEqual(status_segments.preflight_segments("", connected=True), [("not run", "disabled")])
        self.assertEqual(
            status_segments.preflight_segments("ssh ok | cwd /work", connected=False),
            [("ssh ok | cwd /work", "disabled")],
        )
        self.assertEqual(
            status_segments.preflight_segments("project ok | docker missing", connected=True),
            [("project ok", "ok"), (" | ", "normal"), ("docker missing", "error")],
        )

    def test_mapping_status_role_matches_current_attr_policy(self) -> None:
        self.assertEqual(status_segments.mapping_status_role([], None, []), "disabled")
        self.assertEqual(status_segments.mapping_status_role(["layer"], "bad", []), "warn")
        self.assertEqual(status_segments.mapping_status_role(["layer"], None, ["missing"]), "warn")
        self.assertEqual(status_segments.mapping_status_role(["layer"], None, []), "ok")

    def test_main_footer_text_matches_current_draw_policy(self) -> None:
        self.assertEqual(
            status_segments.main_footer_text(active_job=True, focus_panel="logs"),
            "Running | Left/Right tabs | Up/Down actions | f full | s settings | q quit",
        )
        self.assertEqual(
            status_segments.main_footer_text(active_job=True, focus_panel="actions"),
            "Running | Left/Right tabs | Up/Down actions | f full | s settings | q quit",
        )
        self.assertEqual(
            status_segments.main_footer_text(active_job=True, focus_panel="actions", menu_focus="tabs"),
            "Running | Left/Right tabs | Up/Down items | f full | s settings | q quit",
        )
        self.assertEqual(
            status_segments.main_footer_text(active_job=False, focus_panel="actions"),
            "Left/Right tabs | Up/Down select | Enter/r run | f full logs | s settings | q quit | Esc exit",
        )
        self.assertEqual(
            status_segments.main_footer_text(active_job=False, focus_panel="actions", menu_focus="tabs"),
            "Left/Right tabs | Up/Down items | f full logs | s settings | q quit | Esc exit",
        )
        self.assertEqual(
            status_segments.main_footer_text(active_job=False, focus_panel="logs"),
            "Left/Right tabs | Up/Down select | f full logs | Enter/r run | s settings | q quit | Esc exit",
        )


if __name__ == "__main__":
    unittest.main()
