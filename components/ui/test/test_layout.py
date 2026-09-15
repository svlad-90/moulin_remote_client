from __future__ import annotations

import unittest

from components.ui.api import layout


class LayoutBehaviorTests(unittest.TestCase):
    def test_main_layout_matches_current_draw_formula(self) -> None:
        metrics = layout.main_layout(40, 120)

        self.assertEqual(metrics.left_width, 40)
        self.assertEqual(metrics.right_left, 41)
        self.assertEqual(metrics.right_width, 79)
        self.assertEqual(metrics.panel_top, 11)
        self.assertEqual(metrics.panel_height, 27)
        self.assertEqual(metrics.details_height, 13)
        self.assertEqual(metrics.logs_height, 13)
        self.assertEqual(metrics.logs_top, 25)
        self.assertEqual(metrics.signature(), (40, 120, 40, 41, 79, 11, 27, 13, 13, 25))

    def test_main_layout_clamps_left_width_like_current_draw_formula(self) -> None:
        self.assertEqual(layout.main_layout(30, 80).left_width, 34)
        self.assertEqual(layout.main_layout(60, 300).left_width, 46)

    def test_scrollbar_thumb_matches_current_formula(self) -> None:
        self.assertIsNone(layout.scrollbar_thumb(2, 0, 100, 10, 0))
        self.assertIsNone(layout.scrollbar_thumb(2, 10, 10, 10, 0))
        self.assertEqual(layout.scrollbar_thumb(2, 10, 100, 20, 40), (6, 2))

    def test_label_value_layout_matches_current_formula(self) -> None:
        short = layout.label_value_layout(4, 40, "Name")
        self.assertEqual(short.label_text, "Name:")
        self.assertEqual(short.label_width, 8)
        self.assertEqual(short.value_x, 12)
        self.assertEqual(short.value_width, 32)

        long = layout.label_value_layout(2, 10, "Very long label")
        self.assertEqual(long.label_width, 14)
        self.assertEqual(long.value_x, 16)
        self.assertEqual(long.value_width, 1)


if __name__ == "__main__":
    unittest.main()
