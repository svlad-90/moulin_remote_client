#!/usr/bin/env python3
"""Flash a single IPL image to UFS from U-Boot.

Example:
  ./ipl_ufs_flash.py --port /dev/ttyUSB0 --config x5h_bootloaders.yaml \
      --name u-boot-elf-ironhide.srec [--file out/u-boot-elf.srec]
"""
import argparse
import math
import pathlib
import re
import sys
from string import printable

import serial
import yaml

UFS_DEVICE: int = 0
BLOCK_SIZE: int = 4096
PROMPT: str = '=>'
DEFAULT_BAUD_RATE: int = 1843200
DEFAULT_LOAD_ADDRESS: str = '0x50000000'
TIMEOUT: int = 20


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--port', required=True, help='U-Boot serial console, e.g. /dev/ttyUSB0')
    p.add_argument('--config', required=True, type=pathlib.Path, help='yaml with image addresses')
    p.add_argument('--name', required=True, help='image name in the yaml (selects flash_addr)')
    p.add_argument('--check', action='store_true', help='validate the image without touching the board')
    p.add_argument('--file', type=pathlib.Path,
                   help='file to flash (default: the --name file)')
    p.add_argument('--format', choices=('srec', 'bin'), default='srec',
                   help='file format (default: srec)')
    p.add_argument('--baud', type=int, default=DEFAULT_BAUD_RATE)
    p.add_argument('--tftp', type=pathlib.Path, default=pathlib.Path('/srv/tftp'), help='TFTP root')
    p.add_argument('--tftp-prefix', default='', help='TFTP path prefix for the staging directory')
    p.add_argument('--loadaddr', default=DEFAULT_LOAD_ADDRESS, help='U-Boot RAM address for the image')
    return p.parse_args()


def load_entry(config, name):
    with open(config) as f:
        images = yaml.safe_load(f)['images']
    entry = next((e for e in images if e['name'] == name), None)
    if entry is None:
        sys.exit(f'{name}: not found in {config}')
    if str(entry.get('target', '')).upper() != 'UFS':
        sys.exit(f'{name}: target is "{entry.get("target")}", only UFS can be flashed')

    return int(entry['flash_addr'], 16)


def srec_to_bin(path):
    data = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if len(line) < 4 or line[0] != 'S' or line[1] not in '123':
                continue
            raw = bytes.fromhex(line[2:])
            if sum(raw) & 0xFF != 0xFF:
                sys.exit(f'{path}: bad checksum in "{line}"')
            alen = int(line[1]) + 1
            addr = int.from_bytes(raw[1:1 + alen], 'big')
            data[addr] = raw[1 + alen:-1]
    if not data:
        sys.exit(f'{path}: no data records')

    start = min(data)
    end = max(a + len(d) for a, d in data.items())
    out = bytearray(end - start)
    for a, d in data.items():
        out[a - start:a - start + len(d)] = d
    return bytes(out)


def uboot_wait_for(conn, expect):
    buf = ''
    while not any(x in buf for x in expect):
        c = conn.read(1)
        if not c:
            raise TimeoutError(f'timeout waiting for {expect}')
        ch = chr(c[0])
        if ch in printable:
            sys.stdout.write(ch)
            sys.stdout.flush()
        buf += ch
    return buf


def uboot_cmd_run(conn, cmd, ok=None):
    conn.write(f'{cmd}\r'.encode('ascii'))
    out = uboot_wait_for(conn, [PROMPT])
    if ok and ok not in out:
        raise RuntimeError(f'"{cmd}" failed (expected "{ok}")')
    return out


def main():
    args = parse_args()
    name = args.name
    flash_addr = load_entry(args.config, name)
    if args.file is None:
        args.file = next((f for f in (pathlib.Path(name), args.config.parent / name)
                          if f.is_file()), pathlib.Path(name))
    if not args.file.is_file():
        sys.exit(f'{args.file}: file not found')
    fmt = args.format
    try:
        image = srec_to_bin(args.file) if fmt == 'srec' else args.file.read_bytes()
    except (UnicodeDecodeError, ValueError):
        sys.exit(f'{args.file}: not a valid srec file (use --format bin for binaries)')
    if not image:
        sys.exit(f'{args.file}: empty image')
    if flash_addr < 0 or flash_addr % BLOCK_SIZE:
        sys.exit(f'{name}: UFS flash address must be nonnegative and block-aligned')
    # U-Boot writes whole blocks; do not copy stale RAM after the image tail.
    image += bytes((-len(image)) % BLOCK_SIZE)

    tftp_name = f'ipl-flash-{pathlib.Path(name).stem}.bin'
    tftp_path = args.tftp / tftp_name
    loadaddr = int(args.loadaddr, 16)
    remote_name = '/'.join(part for part in (args.tftp_prefix, tftp_name) if part)
    if not re.fullmatch(r'[A-Za-z0-9_./-]+', remote_name):
        sys.exit('TFTP path must contain only letters, digits, slash, dot, underscore or hyphen')

    if args.check:
        return
    conn = serial.serial_for_url(args.port, args.baud, timeout=TIMEOUT)
    try:
        print('[Waiting for U-Boot prompt...]')
        conn.write(b'\r')
        uboot_wait_for(conn, [PROMPT, 'Hit any key to stop autoboot'])
        conn.write(b'\r')
        uboot_wait_for(conn, [PROMPT])

        start = flash_addr // BLOCK_SIZE
        count = math.ceil(len(image) / BLOCK_SIZE)

        print(f'\n\n[{args.file} ({fmt}) as {name}: {len(image)} bytes -> UFS dev {UFS_DEVICE}, '
              f'addr 0x{flash_addr:X}, block 0x{start:X}, count 0x{count:X}]')

        tftp_path.write_bytes(image)
        tftp_path.chmod(0o644)
        uboot_cmd_run(conn, 'scsi scan')
        uboot_cmd_run(conn, f'tftp 0x{loadaddr:X} {remote_name}', f'Bytes transferred = {len(image)}')
        uboot_cmd_run(conn, f'scsi dev {UFS_DEVICE}', 'is now current device')
        uboot_cmd_run(conn, f'scsi write 0x{loadaddr:X} 0x{start:X} 0x{count:X}', f'{count} blocks written: OK')
        print(f'\n\n[{name} flashed]')
    finally:
        tftp_path.unlink(missing_ok=True)
        conn.close()


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, TimeoutError, OSError) as e:
        sys.exit(f'\nError: {e}')
