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
                (" | ", "section"),
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
            [("project ok", "ok"), (" | ", "section"), ("docker missing", "error")],
        )
        self.assertEqual(
            status_segments.preflight_segments(
                "git clean | git behind 2 | git dirty 1, ahead 1",
                connected=True,
            ),
            [
                ("git clean", "ok"),
                (" | ", "section"),
                ("git behind 2", "warn"),
                (" | ", "section"),
                ("git dirty 1, ahead 1", "error"),
            ],
        )

    def test_compact_header_preflight_removes_ref_and_healthy_origin(self) -> None:
        self.assertEqual(
            status_segments.compact_header_preflight(
                "project ok | origin ok | ref ok"
            ),
            "project ok",
        )
        self.assertEqual(
            status_segments.compact_header_preflight(
                "project ok | origin mismatch:old | ref mismatch:main"
            ),
            "project ok | origin mismatch:old",
        )
    def test_product_ref_segments_show_selected_remote_and_synced_states(self) -> None:
        self.assertEqual(
            status_segments.product_ref_segments(
                "topic",
                {"remote_ref": "topic@abc1234", "synced_ref": "topic@abc1234", "ref": "ok"},
            ),
            [
                ("Product ref: ", "accent"),
                ("topic", "normal"),
                (" | ", "section"),
                ("Cached tip: ", "accent"),
                ("abc1234", "normal"),
                (" | ", "section"),
                ("HEAD: ", "accent"),
                ("synced", "ok"),
            ],
        )
        self.assertEqual(
            status_segments.product_ref_segments(
                "topic",
                {"remote_ref": "topic@abc1234", "synced_ref": "topic@abc1234", "ref": "ok"},
                narrow=True,
            ),
            [
                ("Ref: ", "accent"),
                ("topic@abc1234", "normal"),
                (" | ", "section"),
                ("HEAD: ", "accent"),
                ("synced", "ok"),
            ],
        )

    def test_product_ref_segments_warn_for_unavailable_or_mismatched_states(self) -> None:
        segments = status_segments.product_ref_segments(
            "topic",
            {"remote_ref": "not-fetched", "synced_ref": "main@def5678", "ref": "mismatch:main"},
        )

        self.assertEqual(segments[4], ("not-fetched", "warn"))
        self.assertEqual(segments[7], ("main@def5678", "warn"))

        behind_segments = status_segments.product_ref_segments(
            "topic",
            {"remote_ref": "topic@abc1234", "synced_ref": "topic@def5678", "ref": "ok"},
        )
        self.assertEqual(behind_segments[4], ("abc1234", "normal"))
        self.assertEqual(behind_segments[7], ("def5678", "warn"))

    def test_mapping_status_role_matches_current_attr_policy(self) -> None:
        self.assertEqual(status_segments.mapping_status_role([], None, []), "disabled")
        self.assertEqual(status_segments.mapping_status_role(["layer"], "bad", []), "warn")
        self.assertEqual(status_segments.mapping_status_role(["layer"], None, ["missing"]), "warn")
        self.assertEqual(status_segments.mapping_status_role(["layer"], None, []), "ok")

    def test_main_footer_text_matches_current_draw_policy(self) -> None:
        self.assertEqual(
            status_segments.main_footer_text(
                active_job=True,
                focus_panel="actions",
                selected_action_running=True,
            ),
            "Enter/r again stops selected action | Up/Down actions | f full | s settings | q quit",
        )
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
