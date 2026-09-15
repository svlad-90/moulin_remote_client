from __future__ import annotations

import curses
import unittest

from components.ui.api import input as ui_input


class InputBehaviorTests(unittest.TestCase):
    def test_key_matches_text_accepts_latin_russian_and_ukrainian_aliases(self) -> None:
        self.assertTrue(ui_input.key_matches_text("s", "s"))
        self.assertTrue(ui_input.key_matches_text("ы", "s"))
        self.assertTrue(ui_input.key_matches_text("і", "s"))
        self.assertTrue(ui_input.key_matches_text("ф", "a"))
        self.assertTrue(ui_input.key_matches_text("й", "q"))

    def test_key_matches_text_rejects_empty_or_unrelated_text(self) -> None:
        self.assertFalse(ui_input.key_matches_text("", "q"))
        self.assertFalse(ui_input.key_matches_text("x", "q"))

    def test_key_code_matches_decodes_before_matching_aliases(self) -> None:
        self.assertTrue(ui_input.key_code_matches(ord("q"), "q"))
        self.assertTrue(ui_input.key_code_matches(ui_input.TEXT_KEY_OFFSET + ord("й"), "q"))
        self.assertFalse(ui_input.key_code_matches(10, "q"))

    def test_key_code_to_text_preserves_current_client_decoding(self) -> None:
        encoded = ui_input.TEXT_KEY_OFFSET + ord("ф")

        self.assertEqual(ui_input.key_code_to_text(ord("x")), "x")
        self.assertEqual(ui_input.key_code_to_text(encoded), "ф")
        self.assertEqual(ui_input.key_code_to_text(-1), "")
        self.assertEqual(ui_input.key_code_to_text(10), "")
        self.assertEqual(ui_input.decode_text_key(encoded), "ф")
        self.assertEqual(ui_input.decode_text_key(ord("x")), "")

    def test_encode_text_key_matches_current_client_encoding(self) -> None:
        self.assertEqual(ui_input.encode_text_key(""), -1)
        self.assertEqual(ui_input.encode_text_key("x"), ord("x"))
        self.assertEqual(ui_input.encode_text_key("ф"), ui_input.TEXT_KEY_OFFSET + ord("ф"))

    def test_prompt_render_matches_current_prompt_layout(self) -> None:
        render = ui_input.prompt_render("Field", "value", 12)

        self.assertEqual(render.prompt, "Field [value]: ")
        self.assertEqual(render.visible_prompt, "Field [valu")
        self.assertEqual(render.clear_text, " " * 11)
        self.assertEqual(render.input_x, 10)

        narrow = ui_input.prompt_render("Field", "value", 1)
        self.assertEqual(narrow.visible_prompt, "")
        self.assertEqual(narrow.clear_text, "")
        self.assertEqual(narrow.input_x, -1)

    def test_prompt_value_or_current_matches_current_empty_fallback(self) -> None:
        self.assertEqual(ui_input.prompt_value_or_current(" next ", "current"), "next")
        self.assertEqual(ui_input.prompt_value_or_current("   ", "current"), "current")

    def test_prompt_was_cancelled_reads_port_flag(self) -> None:
        class Port:
            prompt_cancelled = True

        self.assertTrue(ui_input.prompt_was_cancelled(Port()))
        self.assertFalse(ui_input.prompt_was_cancelled(object()))

    def test_inline_edit_key_action_handles_save_cancel_and_cursor_keys(self) -> None:
        self.assertEqual(ui_input.inline_edit_key_action("abc", 2, 10).action, "save")
        self.assertEqual(ui_input.inline_edit_key_action("abc", 2, 27).action, "cancel")
        self.assertEqual(ui_input.inline_edit_key_action("abc", 0, curses.KEY_LEFT), ui_input.InlineEditResult("abc", 0, "edit"))
        self.assertEqual(ui_input.inline_edit_key_action("abc", 2, curses.KEY_LEFT), ui_input.InlineEditResult("abc", 1, "edit"))
        self.assertEqual(ui_input.inline_edit_key_action("abc", 2, curses.KEY_RIGHT), ui_input.InlineEditResult("abc", 3, "edit"))
        self.assertEqual(ui_input.inline_edit_key_action("abc", 2, curses.KEY_HOME), ui_input.InlineEditResult("abc", 0, "edit"))
        self.assertEqual(ui_input.inline_edit_key_action("abc", 2, curses.KEY_END), ui_input.InlineEditResult("abc", 3, "edit"))

    def test_inline_edit_key_action_handles_delete_backspace_and_text_insert(self) -> None:
        self.assertEqual(ui_input.inline_edit_key_action("abc", 2, curses.KEY_BACKSPACE), ui_input.InlineEditResult("ac", 1, "edit"))
        self.assertEqual(ui_input.inline_edit_key_action("abc", 0, curses.KEY_BACKSPACE), ui_input.InlineEditResult("abc", 0, "edit"))
        self.assertEqual(ui_input.inline_edit_key_action("abc", 1, curses.KEY_DC), ui_input.InlineEditResult("ac", 1, "edit"))
        self.assertEqual(ui_input.inline_edit_key_action("abc", 3, curses.KEY_DC), ui_input.InlineEditResult("abc", 3, "edit"))
        self.assertEqual(ui_input.inline_edit_key_action("ac", 1, -1, "b"), ui_input.InlineEditResult("abc", 2, "edit"))
        self.assertEqual(ui_input.inline_edit_key_action("abc", 99, -1, "!"), ui_input.InlineEditResult("abc!", 4, "edit"))
        self.assertEqual(ui_input.inline_edit_key_action("abc", -5, -1), ui_input.InlineEditResult("abc", 0, "noop"))


if __name__ == "__main__":
    unittest.main()
