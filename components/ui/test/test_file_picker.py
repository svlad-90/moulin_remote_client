from __future__ import annotations

import curses
import tempfile
import unittest
from pathlib import Path
from typing import Any

from components.ui.api.file_picker import local_file_entries, select_local_file


class FakeScreen:
    def timeout(self, _value: int) -> None:
        return None

    def erase(self) -> None:
        return None

    def getmaxyx(self) -> tuple[int, int]:
        return (24, 100)

    def refresh(self) -> None:
        return None


class FakePort:
    def __init__(self, keys: list[int]) -> None:
        self.screen = FakeScreen()
        self.keys = keys

    def add(self, *_args: Any) -> None:
        return None

    def accent_attr(self) -> int:
        return 0

    def warn_attr(self) -> int:
        return 0

    def read_key(self) -> int:
        return self.keys.pop(0)


class LocalFilePickerTests(unittest.TestCase):
    def test_entries_sort_directories_before_files_and_mark_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "z-dir").mkdir()
            (root / "a-dir").mkdir()
            (root / "image.txt").write_text("wrong", encoding="utf-8")
            (root / "full_ufs.img.gz").write_text("image", encoding="utf-8")

            entries = local_file_entries(root, lambda path: path.name.endswith(".img.gz"))

        visible = entries[1:]
        self.assertEqual(["a-dir", "z-dir", "full_ufs.img.gz", "image.txt"], [entry.path.name for entry in visible])
        self.assertEqual([False, False, True, False], [entry.selectable for entry in visible])

    def test_select_file_descends_into_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact_dir = root / "download"
            artifact_dir.mkdir()
            artifact = artifact_dir / "full_ufs.img.gz"
            artifact.write_bytes(b"image")
            port = FakePort([curses.KEY_DOWN, 10, curses.KEY_DOWN, 10])

            selected = select_local_file(
                port,
                title="Select UFS image",
                accept_file=lambda path: path.name.endswith(".img.gz"),
                initial_directory=root,
            )

        self.assertEqual(selected, artifact)


if __name__ == "__main__":
    unittest.main()
