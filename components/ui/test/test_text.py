from __future__ import annotations

import unittest

from components.ui.api import text as ui_text


class TextBehaviorTests(unittest.TestCase):
    def test_fit_text_preserves_short_text(self) -> None:
        self.assertEqual(ui_text.fit_text("short", 10), "short")

    def test_fit_text_handles_zero_and_tiny_widths(self) -> None:
        self.assertEqual(ui_text.fit_text("abcdef", 0), "")
        self.assertEqual(ui_text.fit_text("abcdef", 2), "ab")
        self.assertEqual(ui_text.fit_text("abcdef", 3), "abc")

    def test_fit_text_truncates_middle_for_wide_values(self) -> None:
        self.assertEqual(ui_text.fit_text("abcdefghijkl", 7), "ab...kl")
        self.assertEqual(ui_text.fit_text("abcdefghijkl", 8), "ab...jkl")

    def test_wrap_text_lines_matches_current_draw_wrapped_algorithm(self) -> None:
        self.assertEqual(
            ui_text.wrap_text_lines("alpha beta gamma delta", 12, 4),
            ["alpha beta", "gamma delta"],
        )
        self.assertEqual(
            ui_text.wrap_text_lines("superlongword beta", 6, 4),
            ["superl", "beta"],
        )
        self.assertEqual(ui_text.wrap_text_lines("alpha beta gamma", 8, 1), ["alpha"])


if __name__ == "__main__":
    unittest.main()
