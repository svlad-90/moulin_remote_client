#!/usr/bin/env python3
"""Prepare a GEN5 board and execute an action at the U-Boot prompt."""

import argparse
import glob
import ipaddress
import re
import subprocess
import sys
import time

import serial


def wait_uboot_prompt(conn, *, interrupt=False, timeout=45.0):
    deadline = time.monotonic() + timeout
    next_key = 0.0
    output = ''
    while time.monotonic() < deadline:
        data = conn.read(4096)
        if data:
            text = data.decode('utf-8', errors='replace')
            print(text, end='', flush=True)
            output = (output + text)[-16384:]
            if re.search(r'(?:^|[\r\n])(?:=>|U-Boot>)\s*$', output):
                return output
        now = time.monotonic()
        if interrupt and now >= next_key:
            conn.write(b'\r')
            conn.flush()
            next_key = now + 0.2
    raise TimeoutError('Timed out waiting for U-Boot prompt')


def send_command(conn, command, *, wait=True):
    conn.reset_input_buffer()
    print(f'\nU-Boot: {command}', flush=True)
    conn.write((command + '\r').encode('ascii'))
    conn.flush()
    return wait_uboot_prompt(conn, timeout=10.0) if wait else ''


def require_variable(conn, name):
    output = send_command(conn, f'printenv {name}')
    if not any(line.strip().startswith(name + '=') for line in output.splitlines()):
        raise RuntimeError(f'U-Boot variable {name} not found. Apply U-Boot network env or Apply U-Boot UFS env first.')


def prepare_uboot(args):
    environment = []
    for name in ('ipaddr', 'serverip'):
        value = getattr(args, name, None)
        if value:
            environment.append((name, str(ipaddress.IPv4Address(value))))
    port = args.port
    if not port:
        devices = sorted(glob.glob('/dev/GEN5_CONSOLE*'))
        if not devices:
            raise RuntimeError('GEN5 console device not found')
        port = devices[0]
    # Own the console before power-on so even a short autoboot window is caught.
    with serial.Serial(port, 1843200, timeout=0.1, exclusive=True) as conn:
        for command in (args.power_off_command, args.boot_mode_command):
            print(f'Board preparation: {command}', flush=True)
            subprocess.run(['bash', '-lic', 'set -euo pipefail\n' + command], check=True)
            time.sleep(1)
        conn.reset_input_buffer()
        print(f'Board preparation: {args.power_on_command}', flush=True)
        subprocess.run(['bash', '-lic', 'set -euo pipefail\n' + args.power_on_command], check=True)
        wait_uboot_prompt(conn, interrupt=True)
        for name, value in environment:
            send_command(conn, f'setenv {name} {value}')
            output = send_command(conn, f'printenv {name}')
            if f'{name}={value}' not in [line.strip() for line in output.splitlines()]:
                raise RuntimeError(f'U-Boot did not accept {name}={value}')
        if getattr(args, 'require_variable', None):
            require_variable(conn, args.require_variable)
        for command in getattr(args, 'command', []):
            send_command(conn, command)
        if getattr(args, 'verify_variable', None):
            require_variable(conn, args.verify_variable)
        if getattr(args, 'verify_command', None):
            send_command(conn, args.verify_command)
        if getattr(args, 'boot_command', None):
            send_command(conn, args.boot_command, wait=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='')
    parser.add_argument('--power-off-command', required=True)
    parser.add_argument('--boot-mode-command', required=True)
    parser.add_argument('--power-on-command', required=True)
    parser.add_argument('--ipaddr')
    parser.add_argument('--serverip')
    parser.add_argument('--command', action='append', default=[])
    parser.add_argument('--require-variable')
    parser.add_argument('--verify-variable')
    parser.add_argument('--verify-command')
    parser.add_argument('--boot-command')
    prepare_uboot(parser.parse_args())


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        sys.exit(f'Error: {exc}')
