from __future__ import annotations

import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from components.board_types.src.builtin.gen5_x5h import Gen5X5hBoardAdapter


class Gen5LocalArtifactTests(unittest.TestCase):
    def test_reads_only_present_ufs_images_in_yaml_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "boot-artifacts.tar.bz2"
            config = (
                b"images:\n"
                b"- {name: first.srec, target: UFS, flash_addr: '0x1000'}\n"
                b"- {name: ignored.bin, target: QSPI, flash_addr: '0x2000'}\n"
                b"- {name: missing.srec, target: UFS, flash_addr: '0x3000'}\n"
            )
            with tarfile.open(archive_path, "w:bz2") as archive:
                for name, data in (("x5h_bootloaders.yaml", config), ("first.srec", b"SREC")):
                    info = tarfile.TarInfo(
                        "release/yocto/build-domd/tmp/deploy/images/ironhide/ipls/" + name
                    )
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))

            progress: list[tuple[int, int]] = []
            archive_size = archive_path.stat().st_size
            parts = Gen5X5hBoardAdapter().local_artifact_parts(
                "flash_single_ipl", archive_path, lambda current, total: progress.append((current, total))
            )

        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].part_id, "first.srec")
        self.assertEqual(parts[0].detail, "UFS 0x1000")
        self.assertTrue(progress)
        self.assertEqual([current for current, _total in progress], sorted(current for current, _total in progress))
        self.assertEqual(progress[-1], (archive_size, archive_size))

    def test_rejects_multiple_bootloader_configs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "boot-artifacts.tar.bz2"
            config = b"images: []\n"
            with tarfile.open(archive_path, "w:bz2") as archive:
                for variant in ("first", "second"):
                    info = tarfile.TarInfo(
                        f"release/build-domd/{variant}/ipls/x5h_bootloaders.yaml"
                    )
                    info.size = len(config)
                    archive.addfile(info, io.BytesIO(config))

            with self.assertRaisesRegex(ValueError, "Expected one build-domd"):
                Gen5X5hBoardAdapter().local_artifact_parts(
                    "flash_single_ipl", archive_path
                )


if __name__ == "__main__":
    unittest.main()
