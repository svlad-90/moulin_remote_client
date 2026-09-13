#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
flash_bootloaders.by

Python port of the TeraTerm TTL workflow with:
- Single reader thread (SerialTap) that prints ALL target output and buffers it for prompt matching
- Step-by-step logging
- SREC sending in RAW or ASCII (CRLF) mode
- Progress printing while sending ASCII SREC (every 5%)
- All configuration (flash writer, baud rates, modes, images, prompts) read from YAML

Usage:
  python flash_bootloaders.by --port /dev/ttyUSB0 --config x5h_bootloaders.yaml --mode all
  python flash_bootloaders.by --port /dev/ttyUSB0 --config x5h_bootloaders.yaml --mode select --image <name>
"""

import argparse
import os
import sys
import time
import threading
import serial
import yaml

# -----------------------------
# Serial + tap (single reader)
# -----------------------------
class SerialTap:
    """Single reader that tees device output to stdout and into a buffer for prompt matching."""
    def __init__(self, ser: serial.Serial, buf_limit: int = 1024 * 1024):
        self.ser = ser
        self.buf = bytearray()
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.buf_limit = buf_limit

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        try:
            self.thread.join(timeout=1.0)
        except Exception:
            pass

    def clear_buffer(self):
        with self.lock:
            self.buf.clear()

    def wait_for(self, needle: str, timeout_s: float) -> bool:
        end = time.time() + timeout_s
        needle_b = needle.encode('latin1')
        while time.time() < end:
            with self.lock:
                if needle_b in self.buf:
                    return True
            time.sleep(0.01)
        return False

    def _run(self):
        while not self.stop_event.is_set():
            try:
                data = self.ser.read(1024)
                if data:
                    # print live
                    sys.stdout.write(data.decode('latin1', errors='replace'))
                    sys.stdout.flush()
                    # buffer for waits
                    with self.lock:
                        self.buf += data
                        # trim buffer if too big
                        if len(self.buf) > self.buf_limit:
                            cut = len(self.buf) - self.buf_limit
                            del self.buf[:cut]
            except Exception:
                break

def open_port(port: str, baud: int, rtscts: bool, xonxoff: bool, timeout: float = 0.2) -> serial.Serial:
    print(f"[INFO] Opening serial port {port} at {baud} baud (RTS/CTS={'on' if rtscts else 'off'}, XON/XOFF={'on' if xonxoff else 'off'})")
    ser = serial.Serial(
        port=port,
        baudrate=baud,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=timeout,
        write_timeout=timeout,
        rtscts=rtscts,
        xonxoff=xonxoff,
    )
    return ser

def send_line(ser: serial.Serial, line: str) -> None:
    print(f"[TX] {line}")
    ser.write((line + '\r\n').encode('ascii'))
    ser.flush()

def send_file_raw(ser: serial.Serial, path: str, label: str) -> None:
    with open(path, 'rb') as f:
        data = f.read()
    print(f"[TX] Sending {len(data)} bytes ({label})")
    ser.write(data)
    ser.flush()

def send_text_file_ascii(ser: serial.Serial, path: str, label: str) -> None:
    """
    Send a text file line-by-line with CRLF endings.
    NO delay here. Progress printed every 5%.
    Also: ensure final ser.flush() happens BEFORE the final 'completed' print (as requested).
    """
    # First pass: count total lines for progress
    try:
        with open(path, 'rt', encoding='latin1', errors='ignore') as f:
            total_lines = sum(1 for _ in f)
    except Exception as e:
        print(f"[ERROR] Failed to count lines in {path}: {e}", file=sys.stderr)
        total_lines = 0

    print(f"[TX] ASCII send '{path}' with CRLF (no delay). Total lines: {total_lines}")
    next_pct = 5
    lines_sent = 0
    with open(path, 'rt', encoding='latin1', errors='ignore') as f:
        for line in f:
            line = line.rstrip('\r\n')
            out = (line + '\r\n').encode('ascii', errors='replace')
            ser.write(out)
            lines_sent += 1
            if total_lines > 0:
                pct = (lines_sent * 100) // total_lines
                if pct >= next_pct:
                    print(f"[TX] {label}: {pct}% ({lines_sent}/{total_lines} lines)")
                    next_pct = min(100, next_pct + 5)
    # >>> ensure flush BEFORE completion print <<<
    ser.flush()
    if total_lines > 0:
        print(f"[TX] {label}: 100% ({lines_sent}/{total_lines} lines)")
    else:
        print(f"[TX] {label}: completed (unknown line count)")

def require_prompt(tap: SerialTap, needle: str, timeout_s: float, context: str):
    print(f"[WAIT] Waiting for prompt '{needle}' ({context})")
    if not tap.wait_for(needle, timeout_s):
        raise RuntimeError(f"Timed out waiting for '{needle}' during: {context}")
    print(f"[INFO] Prompt '{needle}' detected ({context})")

# -----------------------------
# File helpers
# -----------------------------
def fail(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)
    sys.exit(1)

def ensure_exists(path: str) -> None:
    if not os.path.isfile(path):
        fail(f'File "{path}" not found')
    print(f"[INFO] Found file: {path}")

def srec_find_start_address_s3(path: str) -> str:
    print(f"[INFO] Parsing SREC for start address: {path}")
    with open(path, 'rt', encoding='latin1', errors='ignore') as f:
        for line in f:
            line = line.strip()
            if len(line) < 2:
                continue
            if line[:2] == 'S3':
                addr = line[4:12]
                print(f"[INFO] Found S3 start address: {addr}")
                return addr.upper()
            if line[:2] == 'S7':
                fail(f'File "{path}" S7 found before S3 (S3 not found)')
    fail(f'File "{path}" S3 record not found')

def file_size_hex(path: str) -> str:
    st = os.stat(path)
    size_hex = f"{st.st_size:X}"
    print(f"[INFO] File size of {path}: {st.st_size} bytes (0x{size_hex})")
    return size_hex

# -----------------------------
# Flows (use YAML config)
# -----------------------------
def load_flashwriter(ser: serial.Serial, tap: SerialTap, images_dir: str, conf: dict) -> None:
    fw = conf['flashwriter']
    fw_path = os.path.join(images_dir, fw['file'])
    print("[STEP] Loading FlashWriter")
    ensure_exists(fw_path)

    baud = int(fw.get('baud', conf['device'].get('baud', 115200)))
    print(f"[INFO] Setting baudrate to {baud} for FlashWriter")
    ser.baudrate = baud

    tap.clear_buffer()
    mode = fw.get('mode', 'ascii')
    if mode == 'ascii':
        send_text_file_ascii(ser, fw_path, label="flashwriter-ascii")
    else:
        send_file_raw(ser, fw_path, label="flashwriter-raw")

    ready_prompt = conf['prompts'].get('ready', '>')
    timeout = float(conf['timeouts'].get('flashwriter_ready', 15.0))
    require_prompt(tap, ready_prompt, timeout, 'loading FlashWriter')
    print("[DONE] FlashWriter loaded")

def load_image_hyper_srec(ser: serial.Serial, tap: SerialTap, images_dir: str, conf: dict,
                          img_name: str, img_addr: str, flash_addr: str) -> None:
    print(f"[STEP] Loading SREC to HyperFlash: {img_name}")
    time.sleep(0.02)
    tap.clear_buffer()
    send_line(ser, conf['commands']['hyper_write_srec'])

    prompt_input = conf['prompts']['input_data']         # 'Input data : 0x'
    prompt_send_srec = conf['prompts']['send_srec']      # 'please send ! (Motorola S-record)'
    ready_prompt = conf['prompts']['ready']              # '>'

    require_prompt(tap, prompt_input, conf['timeouts']['short'], 'hyper_write_srec start addr')
    send_line(ser, img_addr)
    require_prompt(tap, prompt_input, conf['timeouts']['short'], 'hyper_write_srec flash addr')
    send_line(ser, flash_addr)
    require_prompt(tap, prompt_send_srec, conf['timeouts']['short'], 'hyper_write_srec send prompt')

    time.sleep(0.4)
    path = os.path.join(images_dir, img_name)
    tap.clear_buffer()
    srec_mode = conf['srec'].get('mode', 'ascii')
    if srec_mode == 'ascii':
        send_text_file_ascii(ser, path, label="srec-ascii")
    else:
        send_file_raw(ser, path, label="srec-raw")

    require_prompt(tap, ready_prompt, conf['timeouts']['long'], 'hyper_write_srec completion')
    print(f"[DONE] Image {img_name} written to HyperFlash")

def load_image_ufs_srec(ser: serial.Serial, tap: SerialTap, images_dir: str, conf: dict,
                        img_name: str, img_addr: str, flash_addr: str) -> None:
    print(f"[STEP] Loading SREC to UFS: {img_name}")
    time.sleep(0.02)
    tap.clear_buffer()
    send_line(ser, conf['commands']['ufs_write_srec'])

    prompt_input = conf['prompts']['input_data']
    prompt_send_srec = conf['prompts']['send_srec']
    ready_prompt = conf['prompts']['ready']

    require_prompt(tap, prompt_input, conf['timeouts']['short'], 'ufs_write_srec start addr')
    send_line(ser, img_addr)
    require_prompt(tap, prompt_input, conf['timeouts']['short'], 'ufs_write_srec flash addr')
    send_line(ser, flash_addr)
    require_prompt(tap, prompt_send_srec, conf['timeouts']['short'], 'ufs_write_srec send prompt')

    time.sleep(0.4)
    path = os.path.join(images_dir, img_name)
    tap.clear_buffer()
    srec_mode = conf['srec'].get('mode', 'ascii')
    if srec_mode == 'ascii':
        send_text_file_ascii(ser, path, label="srec-ascii")
    else:
        send_file_raw(ser, path, label="srec-raw")

    require_prompt(tap, ready_prompt, conf['timeouts']['long'], 'ufs_write_srec completion')
    print(f"[DONE] Image {img_name} written to UFS")

def load_image_binary(ser: serial.Serial, tap: SerialTap, images_dir: str, conf: dict,
                      img_name: str, flash_addr: str) -> None:
    print(f"[STEP] Loading BIN to HyperFlash: {img_name}")
    time.sleep(0.02)
    tap.clear_buffer()
    send_line(ser, conf['commands']['hyper_write_bin'])

    prompt_size = conf['prompts']['ask_size']   # 'Please Input : H'
    prompt_bin  = conf['prompts']['send_bin']   # 'please send ! (binary)'
    ready_prompt = conf['prompts']['ready']

    require_prompt(tap, prompt_size, conf['timeouts']['short'], 'hyper_write_bin ask size')

    size_hex = file_size_hex(os.path.join(images_dir, img_name))
    send_line(ser, size_hex)
    require_prompt(tap, prompt_size, conf['timeouts']['short'], 'hyper_write_bin ask flash addr')

    send_line(ser, flash_addr)
    require_prompt(tap, prompt_bin, conf['timeouts']['short'], 'hyper_write_bin send prompt')

    tap.clear_buffer()
    send_file_raw(ser, os.path.join(images_dir, img_name), label="binary")
    require_prompt(tap, ready_prompt, conf['timeouts']['long'], 'hyper_write_bin completion')
    print(f"[DONE] Image {img_name} written in binary mode")

def process_image_entry(ser: serial.Serial, tap: SerialTap, images_dir: str, conf: dict, entry: dict) -> None:
    img = entry['name']
    target = entry['target']
    flash_addr = entry['flash_addr']
    start_addr = entry.get('start_addr', '')

    print(f"[STEP] Preparing image {img} (target={target}, flash_addr=0x{flash_addr})")
    path = os.path.join(images_dir, img)
    ensure_exists(path)

    if img.lower().endswith('.srec'):
        if not start_addr:
            start_addr = srec_find_start_address_s3(path)
        if target == 'Flash':
            load_image_hyper_srec(ser, tap, images_dir, conf, img, start_addr, flash_addr)
        elif target == 'UFS':
            load_image_ufs_srec(ser, tap, images_dir, conf, img, start_addr, flash_addr)
        else:
            fail(f'Unknown target "{target}" for image "{img}"')
    elif img.lower().endswith('.bin'):
        load_image_binary(ser, tap, images_dir, conf, img, flash_addr)
    else:
        print(f"[WARN] Skipping unsupported extension: {img}")

# -----------------------------
# Main
# -----------------------------
def main():
    ap = argparse.ArgumentParser(description="Flash bootloaders using YAML configuration")
    ap.add_argument('--port', required=True, help='Serial port, e.g., /dev/ttyUSB0')
    ap.add_argument('--config', default='x5h_bootloaders.yaml', help='Path to YAML config')
    ap.add_argument('--mode', choices=['all', 'select'], default='all', help='Write all images or selected one')
    ap.add_argument('--image', help='Image filename to write when --mode select')
    args = ap.parse_args()

    # Load YAML
    if not os.path.isfile(args.config):
        fail(f'Config file "{args.config}" not found')
    with open(args.config, 'rt', encoding='utf-8') as f:
        conf = yaml.safe_load(f)

    images_dir = os.path.abspath(conf.get('images_dir', '.'))
    if not os.path.isdir(images_dir):
        fail(f'Directory "{images_dir}" not found')

    dev_conf = conf.get('device', {})
    fw_conf = conf.get('flashwriter', {})
    flow = dev_conf.get('flow_control', {})
    initial_wait = float(dev_conf.get('initial_wait_s', 2.0))

    ser = open_port(
        args.port,
        int(dev_conf.get('baud', 115200)),  # initial open; FlashWriter function may change
        rtscts=bool(flow.get('rtscts', False)),
        xonxoff=bool(flow.get('xonxoff', False))
    )
    tap = SerialTap(ser)
    tap.start()

    try:
        print(f"[INFO] Waiting {initial_wait}s before starting...")
        time.sleep(initial_wait)

        # Load FlashWriter (sets baud from YAML flashwriter.baud)
        load_flashwriter(ser, tap, images_dir, conf)

        # After FlashWriter is running, switch to device baud (YAML)
        device_baud = int(dev_conf.get('baud', fw_conf.get('baud', 115200)))
        if ser.baudrate != device_baud:
            print(f"[INFO] Switching baudrate to {device_baud}")
            ser.baudrate = device_baud
            time.sleep(0.1)

        # Process images
        if args.mode == 'all':
            print("[STEP] Writing ALL images")
            for entry in conf.get('images', []):
                # pre-check existence
                ensure_exists(os.path.join(images_dir, entry['name']))
            for entry in conf.get('images', []):
                process_image_entry(ser, tap, images_dir, conf, entry)
            print("[DONE] All images written successfully.")
        else:
            if not args.image:
                fail("--mode select requires --image <filename>")

            # Try to match by name in YAML
            images = conf.get('images', [])
            matched = next((e for e in images if e['name'] == args.image), None)
            if matched is not None:
                process_image_entry(ser, tap, images_dir, conf, matched)
                print(f'[DONE] Image "{matched["name"]}" written.')
            else:
                # Standalone (not in YAML): assume Flash @ 0x00000000
                img_path = os.path.join(images_dir, args.image)
                ensure_exists(img_path)
                if args.image.lower().endswith('.srec'):
                    img_addr = srec_find_start_address_s3(img_path)
                    process_image_entry(ser, tap, images_dir, conf, {
                        'name': args.image, 'target': 'Flash', 'flash_addr': '00000000', 'start_addr': img_addr
                    })
                elif args.image.lower().endswith('.bin'):
                    process_image_entry(ser, tap, images_dir, conf, {
                        'name': args.image, 'target': 'Flash', 'flash_addr': '00000000'
                    })
                else:
                    fail(f"Unsupported extension for {args.image}")
                print(f'[DONE] Image "{args.image}" written (standalone mode).')
    finally:
        tap.stop()
        try:
            ser.close()
        except Exception:
            pass

if __name__ == '__main__':
    main()

