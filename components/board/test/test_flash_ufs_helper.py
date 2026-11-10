from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[3]


def load_helper():
    path = ROOT / "board_tools" / "gen5_x5h_flash_ufs.py"
    spec = importlib.util.spec_from_file_location("gen5_x5h_flash_ufs", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FlashUfsHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.helper = load_helper()

    def test_ready_file_is_created_only_after_serial_open_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ready_file = Path(directory) / "ready"
            connection = object()
            serial_for_url = Mock(return_value=connection)
            vendor = SimpleNamespace(
                conn_wait_for_any=Mock(return_value="=>"),
                serial=SimpleNamespace(serial_for_url=serial_for_url),
                confirm_ufs_flash=Mock(),
            )

            self.helper.patch_xt_imager(vendor, ready_file=str(ready_file))

            self.assertFalse(ready_file.exists())
            self.assertIs(vendor.serial.serial_for_url("console"), connection)
            self.assertTrue(ready_file.exists())

    def test_ready_file_is_not_created_when_serial_open_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ready_file = Path(directory) / "ready"
            vendor = SimpleNamespace(
                conn_wait_for_any=Mock(return_value="=>"),
                serial=SimpleNamespace(
                    serial_for_url=Mock(side_effect=OSError("serial unavailable"))
                ),
                confirm_ufs_flash=Mock(),
            )

            self.helper.patch_xt_imager(vendor, ready_file=str(ready_file))

            with self.assertRaisesRegex(OSError, "serial unavailable"):
                vendor.serial.serial_for_url("console")
            self.assertFalse(ready_file.exists())

    @unittest.skipUnless(shutil.which("setsid"), "setsid is required")
    def test_setsid_wait_preserves_exit_status_and_reports_actual_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pgid_file = Path(directory) / "pgid"
            command = """
set -m
setsid --wait sh -c 'echo "$$" > "$1"; shift; exec "$@"' \
    sh "$1" sh -c 'exit 7' &
launcher_pid=$!
if wait "$launcher_pid"; then exit 0; else exit "$?"; fi
"""

            result = subprocess.run(
                ["bash", "-c", command, "bash", str(pgid_file)],
                check=False,
            )

            self.assertEqual(result.returncode, 7)
            self.assertRegex(pgid_file.read_text().strip(), r"^[0-9]+$")


if __name__ == "__main__":
    unittest.main()
