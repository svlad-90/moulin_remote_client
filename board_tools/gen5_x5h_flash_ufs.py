#!/usr/bin/env python3
"""Run GEN5/X5H UFS flashing through the vendored xt-imager helper."""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import time
from types import ModuleType
from typing import BinaryIO, TextIO, cast


UFS_DEVICE = 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Path to full_ufs.img.gz on the board host.")
    parser.add_argument("--console", required=True, help="Serial console device, for example /dev/GEN5_CONSOLE.")
    parser.add_argument("--tool", required=True, help="Path to vendored xt-imager.py on the board host.")
    parser.add_argument("--baudrate", default="1843200", help="Serial baudrate passed to xt-imager.")
    parser.add_argument("--loadaddr", default="", help="Optional xt-imager --loadaddr value.")
    parser.add_argument("--buffersize", default="", help="Optional xt-imager --buffersize value.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    extra_args: list[str] = []
    if args.loadaddr:
        extra_args.extend(["--loadaddr", args.loadaddr])
    if args.buffersize:
        extra_args.extend(["--buffersize", args.buffersize])
    return run_xt_imager(
        image=args.image,
        console=args.console,
        tool=args.tool,
        baudrate=args.baudrate,
        extra_args=extra_args,
    )


def run_xt_imager(
    *,
    image: str,
    console: str,
    tool: str,
    baudrate: str,
    extra_args: list[str],
) -> int:
    module = load_xt_imager(tool)
    patch_xt_imager(module)
    argv = [
        tool,
        "--target",
        "ufs",
        "-s",
        console,
        "-b",
        baudrate,
        *extra_args,
    ]
    zcat = subprocess.Popen(
        ["zcat", image],
        stdout=subprocess.PIPE,
    )
    assert zcat.stdout is not None
    old_argv = sys.argv
    old_stdin = sys.stdin
    sys.argv = argv
    sys.stdin = cast(TextIO, BinaryInputStdin(zcat.stdout))
    try:
        module.main()
        return wait_for_zcat(zcat)
    finally:
        sys.argv = old_argv
        sys.stdin = old_stdin
        if zcat.poll() is None:
            zcat.terminate()
            zcat.wait(timeout=10)


class BinaryInputStdin:
    """Minimal sys.stdin replacement exposing .buffer for xt-imager."""

    def __init__(self, buffer: BinaryIO) -> None:
        self.buffer = buffer

    def isatty(self) -> bool:
        return False


def load_xt_imager(tool: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location("xt_imager_vendor", tool)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def patch_xt_imager(module: ModuleType) -> None:
    original_wait = module.conn_wait_for_any

    def conn_wait_for_any(conn: object, expect: list[str]) -> str:
        result = original_wait(conn, expect)
        if "=>" in expect:
            drain_serial_tail(conn)
        return result

    module.conn_wait_for_any = conn_wait_for_any
    module.confirm_ufs_flash = auto_confirm_ufs_flash


def drain_serial_tail(conn: object, duration: float = 0.08) -> None:
    old_timeout = conn.timeout
    conn.timeout = 0.01
    deadline = time.monotonic() + duration
    try:
        while time.monotonic() < deadline:
            if not conn.read(4096):
                break
    finally:
        conn.timeout = old_timeout


def auto_confirm_ufs_flash(capacity_bytes: int) -> None:
    logger = logging_getter()
    logger.info("")
    logger.info("[WARNING: destructive UFS flashing operation]")
    logger.info("[UFS device 0 is reserved for IPL booting and will not be modified.]")
    logger.info("[Target: SCSI/UFS device %d, %.2f GiB]", UFS_DEVICE, capacity_bytes / 1024**3)
    logger.info("[All existing data on UFS device %d may be destroyed.]", UFS_DEVICE)
    logger.info("[Auto-confirmed by Moulin board helper: FLASH UFS %d]", UFS_DEVICE)


def logging_getter() -> object:
    import logging

    return logging.getLogger("xt_imager_vendor")


def wait_for_zcat(process: subprocess.Popen[bytes]) -> int:
    return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
