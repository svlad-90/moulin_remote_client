#!/usr/bin/env python3
"""Expose a serial console as a byte stream on stdin and stdout."""

from __future__ import annotations

import argparse
import glob
import os
import select
import sys
import termios
import tty

import serial


ESCAPE_BYTE = 0x01  # Ctrl-A
EXIT_BYTE = 0x18  # Ctrl-X


def resolve_device(value: str) -> str:
    if value and value != "auto":
        return value
    devices = sorted(glob.glob("/dev/GEN5_CONSOLE*"))
    if not devices:
        raise RuntimeError("GEN5 console device not found")
    return devices[0]


def filter_input(data: bytes, escape_pending: bool) -> tuple[bytes, bool, bool]:
    """Consume the picocom-compatible Ctrl-A Ctrl-X exit sequence."""
    output = bytearray()
    for value in data:
        if escape_pending:
            if value == EXIT_BYTE:
                return bytes(output), False, True
            if value == ESCAPE_BYTE:
                output.append(ESCAPE_BYTE)
            else:
                output.extend((ESCAPE_BYTE, value))
            escape_pending = False
        elif value == ESCAPE_BYTE:
            escape_pending = True
        else:
            output.append(value)
    return bytes(output), escape_pending, False


def bridge(device: str, baud: int) -> None:
    input_fd = sys.stdin.fileno()
    output_fd = sys.stdout.fileno()
    saved_termios = termios.tcgetattr(input_fd) if os.isatty(input_fd) else None
    if saved_termios is not None:
        tty.setraw(input_fd)
    escape_pending = False
    try:
        options = {"exclusive": True} if "://" not in device else {}
        with serial.serial_for_url(device, baud, timeout=0, **options) as console:
            print("Exit console with Ctrl-A Ctrl-X.", file=sys.stderr, flush=True)
            while True:
                readable, _writable, _exceptional = select.select(
                    [input_fd, console.fileno()], [], [], 0.25
                )
                if input_fd in readable:
                    data = os.read(input_fd, 4096)
                    if not data:
                        return
                    data, escape_pending, should_exit = filter_input(data, escape_pending)
                    if data:
                        console.write(data)
                        console.flush()
                    if should_exit:
                        return
                if console.fileno() in readable:
                    data = console.read(4096)
                    if data:
                        os.write(output_fd, data)
    finally:
        if saved_termios is not None:
            termios.tcsetattr(input_fd, termios.TCSADRAIN, saved_termios)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--baud", type=int, default=1843200)
    args = parser.parse_args()
    bridge(resolve_device(args.device), args.baud)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, serial.SerialException) as exc:
        raise SystemExit(f"Error: {exc}") from exc
