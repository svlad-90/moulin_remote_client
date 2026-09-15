from __future__ import annotations

import unittest

from components.ui.api import dialogs


class DialogBehaviorTests(unittest.TestCase):
    def test_action_confirm_content_matches_current_run_text(self) -> None:
        content = dialogs.action_confirm_content("Run product build", "Build product.")

        self.assertEqual(content.title, "Confirm")
        self.assertEqual(content.warning, "This action can change local or remote build state.")
        self.assertEqual(content.subject, "Run product build")
        self.assertEqual(content.details, "Build product.")
        self.assertEqual(content.footer, "Enter/y: run | n/q/Esc: cancel")

    def test_action_confirm_content_matches_current_stop_text(self) -> None:
        content = dialogs.action_confirm_content("Stop board command", "Ignored.")

        self.assertEqual(content.warning, "Stop the active command?")
        self.assertEqual(
            content.details,
            "SIGTERM is sent first; if the process does not exit, SIGKILL is sent after a short timeout.",
        )
        self.assertEqual(content.footer, "Enter/y: stop | n/q/Esc: cancel")

    def test_exit_and_disconnect_content_match_current_text(self) -> None:
        exit_content = dialogs.exit_confirm_content()
        self.assertEqual(exit_content.title, "Exit")
        self.assertEqual(exit_content.warning, "Leave the Moulin client?")
        self.assertEqual(exit_content.footer, "Enter/y: exit | n/q/Esc: stay")

        disconnect = dialogs.disconnect_confirm_content("Disconnect board host", "Board  user@host")
        self.assertEqual(disconnect.title, "Disconnect board host")
        self.assertEqual(disconnect.warning, "Disconnect the active host profile?")
        self.assertEqual(disconnect.subject, "Board  user@host")
        self.assertEqual(disconnect.footer, "Enter/y: disconnect | n/q/Esc: cancel")

    def test_confirm_layout_matches_current_geometry(self) -> None:
        layout = dialogs.confirm_layout(40, 120)

        self.assertEqual(layout.width, 64)
        self.assertEqual(layout.height, 10)
        self.assertEqual(layout.top, 15)
        self.assertEqual(layout.left, 28)
        self.assertEqual(layout.inner_width, 60)
        self.assertEqual(layout.content_x, 30)
        self.assertEqual(layout.content_y, 17)

        narrow = dialogs.confirm_layout(20, 50)
        self.assertEqual(narrow.width, 46)
        self.assertEqual(narrow.left, 2)

    def test_confirm_key_result_matches_current_accept_cancel_keys(self) -> None:
        self.assertTrue(dialogs.confirm_key_result("y", ord("y")))
        self.assertTrue(dialogs.confirm_key_result("н", ord("н")))
        self.assertTrue(dialogs.confirm_key_result("", 10))
        self.assertTrue(dialogs.confirm_key_result("", 13))
        self.assertFalse(dialogs.confirm_key_result("n", ord("n")))
        self.assertFalse(dialogs.confirm_key_result("q", ord("q")))
        self.assertFalse(dialogs.confirm_key_result("т", ord("т")))
        self.assertFalse(dialogs.confirm_key_result("й", ord("й")))
        self.assertFalse(dialogs.confirm_key_result("", 27))
        self.assertFalse(dialogs.confirm_key_result("", 3))
        self.assertIsNone(dialogs.confirm_key_result("x", ord("x")))

    def test_close_confirm_flags_match_current_dirty_state_policy(self) -> None:
        self.assertEqual(
            dialogs.close_confirm_flags(),
            {
                "main_full_redraw": True,
                "menu_dirty": True,
                "logs_dirty": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
