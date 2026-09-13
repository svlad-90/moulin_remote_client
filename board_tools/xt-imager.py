#!/usr/bin/env python3
import os
import sys
import pathlib
import re
import argparse
from typing import BinaryIO, List, Optional, Tuple, Union
from string import printable
import gzip
import logging
import serial
import shutil
import struct
import queue
import threading
import subprocess
import time


# UFS device 0 contains IPL boot data required to start the board. It must
# never be selected by this script. The main UFS storage is SCSI device 1.
UFS_DEVICE: int = 1

DEFAULT_SERIAL_DEVICE: str = '/dev/ttyUSB0'
DEFAULT_BAUD_RATE: int = 921600
DEFAULT_TFTP_ROOT: pathlib.Path = pathlib.Path('/srv/tftp')
DEFAULT_LOAD_ADDRESS: str = '0x50000000'
DEFAULT_MMC_DEVICE: int = 0
DEFAULT_BUFFER_SIZE: int = 512 * 1024 * 1024

# Rotate two TFTP files so the host can prepare the next chunk while U-Boot
# writes the current chunk to the target device.
CHUNK_NAMES: Tuple[str, str] = ('chunk0.bin.gz', 'chunk1.bin.gz')

# Level 1 favours preparation speed over a smaller transferred file.
COMPRESS_LEVEL: int = 1

# pigz is optional; Python gzip remains the single-threaded fallback.
COMPRESS_TOOLS: Tuple[str, ...] = ('pigz',)

ChunkResult = Tuple[int, int, int, int, int]
QueueItem = Union[ChunkResult, BaseException, None]

LOGGER = logging.getLogger(__name__)


def main() -> None:
    """Parse command-line arguments and start flashing."""

    logging.basicConfig(level=logging.INFO, format='%(message)s')
    args = parse_args()

    LOGGER.info('[Use %s as a TFTP root]', args.tftp)
    LOGGER.info('[Reading data from STDIN]')
    do_flash_image(args, args.tftp)


def parse_args() -> argparse.Namespace:
    """Parse and validate command-line arguments."""

    description = (
        'Flash an uncompressed image stream to eMMC or UFS through '
        'U-Boot and TFTP.\n\n'
        'The image must be supplied through a pipe. Use cat for a raw image '
        'or zcat for a gzip-compressed image.')
    epilog = (
        'examples for Gen5:\n'
        '  Raw image to UFS:\n'
        '    cat full.img | ./xt-imager.py --target ufs '
        '-s /dev/GEN5_CONSOLE3 -b 1843200\n\n'
        '  Raw image to eMMC:\n'
        '    cat full.img | ./xt-imager.py --target emmc '
        '-s /dev/GEN5_CONSOLE3 -b 1843200\n\n'
        '  Gzip image to UFS:\n'
        '    zcat full.img.gz | ./xt-imager.py --target ufs '
        '-s /dev/GEN5_CONSOLE3 -b 1843200\n\n'
        '  Gzip image to eMMC:\n'
        '    zcat full.img.gz | ./xt-imager.py --target emmc '
        '-s /dev/GEN5_CONSOLE3 -b 1843200\n\n'
        'operation:\n'
        '  The host reads the uncompressed stream in two alternating chunks. '
        'While\n'
        '  U-Boot writes one chunk, the host prepares the next one. Each '
        'prepared\n'
        '  chunk is gzip-compressed, downloaded by U-Boot over TFTP, and '
        'written with\n'
        '  gzwrite. Installing pigz on the host enables parallel chunk '
        'compression.\n\n'
        'UFS safety:\n'
        '  UFS device 0 contains IPL boot data and is never written. UFS '
        'flashing is\n'
        '  fixed to SCSI device 1 and requires typing an explicit '
        'confirmation.\n')
    parser = argparse.ArgumentParser(
        description=description,
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument(
        '--target',
        required=True,
        choices=('emmc', 'ufs'),
        help='Destination storage: eMMC or protected UFS data device 1')

    parser.add_argument(
        '-s',
        '--serial',
        default=DEFAULT_SERIAL_DEVICE,
        metavar='DEVICE',
        help=(
            'Serial console connected to U-Boot '
            f'(default: {DEFAULT_SERIAL_DEVICE})'))

    parser.add_argument(
        '-b',
        '--baud',
        type=int,
        default=DEFAULT_BAUD_RATE,
        metavar='RATE',
        help=f'Serial-console baud rate (default: {DEFAULT_BAUD_RATE})')

    parser.add_argument(
        '-t',
        '--tftp',
        type=pathlib.Path,
        default=DEFAULT_TFTP_ROOT,
        metavar='DIRECTORY',
        help=f'TFTP root for temporary chunks (default: {DEFAULT_TFTP_ROOT})')

    parser.add_argument(
        '--loadaddr',
        default=DEFAULT_LOAD_ADDRESS,
        metavar='ADDRESS',
        help=f'U-Boot TFTP load address (default: {DEFAULT_LOAD_ADDRESS})')

    parser.add_argument(
        '--mmcdev',
        type=int,
        default=DEFAULT_MMC_DEVICE,
        metavar='NUMBER',
        help=(
            'MMC device used with --target emmc '
            f'(default: {DEFAULT_MMC_DEVICE})'))

    parser.add_argument(
        '--buffersize',
        type=int,
        default=DEFAULT_BUFFER_SIZE,
        metavar='BYTES',
        help=f'Uncompressed chunk size (default: {DEFAULT_BUFFER_SIZE})')

    parser.add_argument(
        '--serverip',
        metavar='IP',
        help='Temporarily set the TFTP server IP in U-Boot')

    parser.add_argument(
        '--ipaddr',
        metavar='IP',
        help='Temporarily set the board IP in U-Boot')
    args = parser.parse_args()

    # A positive, 512-byte-aligned chunk works for normal eMMC writes. UFS is
    # checked again later against the block size reported by the actual device.
    if args.buffersize <= 0 or args.buffersize % 512 != 0:
        parser.error('--buffersize must be a positive, 512-byte aligned value')

    # Without a pipe, reading sys.stdin.buffer would wait indefinitely. Reject
    # this early and show the user how the image must be supplied.
    if sys.stdin.isatty():
        parser.error(
            'image data must be piped through stdin; use cat or zcat '
            'as shown in --help')

    if not args.tftp.is_dir():
        parser.error(f'TFTP root is not a directory: {args.tftp}')

    return args


def build_write_command(args: argparse.Namespace, offset: int) -> str:
    """Build u-boot command to write a chunk to the selected device"""

    # eMMC is selected by the user-configurable U-Boot MMC device number.

    if args.target == 'emmc':
        return (
            f'gzwrite mmc {args.mmcdev} '
            f'${{loadaddr}} ${{filesize}} 400000 {offset:X}\r')

    # UFS always uses protected data device 1; device 0 is never accepted.

    if args.target == 'ufs':
        return (
            f'gzwrite scsi {UFS_DEVICE} '
            f'${{loadaddr}} ${{filesize}} 400000 {offset:X}\r')

    raise ValueError(f'Unsupported flashing target: {args.target}')


def find_tool(candidates: Tuple[str, ...]) -> Optional[str]:
    """Find the first installed tool from a priority-ordered list.

    Each candidate is searched in the host PATH. Return its full executable
    path when found, or None when none of the candidates are installed.
    """

    # shutil.which() resolves an executable using the host PATH.

    for name in candidates:
        path = shutil.which(name)
        if path:
            return path
    return None


def build_compress_command(tool: str) -> List[str]:
    """Build command arguments for parallel pigz chunk compression.

    Use the configured fast compression level, write the gzip stream to stdout,
    and request one worker per logical CPU. If Python cannot detect the CPU
    count, use four workers as a conservative fallback.
    """

    return [tool, f'-{COMPRESS_LEVEL}', '-c', '-p',
            str(os.cpu_count() or 4)]


def compress_chunk(data: bytes, out_path: Union[str, pathlib.Path],
                   command: Optional[List[str]]) -> Tuple[int, int]:
    """Compress one chunk and return its gzip CRC and packed size."""
    # Create or replace the selected temporary file in the TFTP root.

    with open(out_path, 'wb') as f_out:
        # Prefer pigz because it can compress a chunk on multiple CPU cores.

        if command is not None:
            proc = subprocess.Popen(
                command, stdin=subprocess.PIPE,
                stdout=f_out)
            proc.communicate(data)
            if proc.returncode != 0:
                raise RuntimeError(
                    f'Compressor exited with code {proc.returncode}')
        # If pigz is unavailable, use the compatible single-threaded Python
        # gzip implementation. U-Boot receives the same gzip file format.

        else:
            f_out.write(gzip.compress(data, compresslevel=COMPRESS_LEVEL))
    # U-Boot reports the number of bytes downloaded by TFTP. Record the exact
    # compressed size so the main thread can validate that report.

    packed_size = os.path.getsize(out_path)
    # A gzip trailer ends with CRC32 and the uncompressed size. Reading the
    # stored CRC avoids calculating it in a separate pass over the raw chunk.

    with open(out_path, 'rb') as f_in:
        f_in.seek(-8, os.SEEK_END)
        crc = struct.unpack('<I', f_in.read(4))[0]
    return crc, packed_size


def put_until_aborted(
        destination: queue.Queue, item: QueueItem,
        abort: threading.Event) -> bool:
    """Put an item into a bounded queue while allowing cancellation."""

    while not abort.is_set():
        try:
            destination.put(item, timeout=0.5)
            return True
        except queue.Full:
            continue
    return False


def get_until_aborted(
        source: queue.Queue, abort: threading.Event) -> Optional[int]:
    """Get an item from a queue while allowing cancellation."""

    while not abort.is_set():
        try:
            return source.get(timeout=0.5)
        except queue.Empty:
            continue
    return None


def validate_chunk(offset: int, length: int, block_size: Optional[int],
                   capacity_bytes: Optional[int]) -> None:
    """Validate one chunk against target geometry and capacity."""

    if block_size and length % block_size != 0:
        raise ValueError(
            f"Chunk at offset {offset} has size {length}, "
            f"which is not aligned to the device block size {block_size}")

    if capacity_bytes and offset + length > capacity_bytes:
        raise ValueError(
            f"Image does not fit the device: at least "
            f"{(offset + length) / 1024**3:.2f} GiB required, "
            f"device capacity is {capacity_bytes / 1024**3:.2f} GiB")


def prepare_chunks(
        args: argparse.Namespace, input_stream: BinaryIO,
        tftp_root: pathlib.Path, free_slots: queue.Queue,
        results: queue.Queue, abort: threading.Event,
        block_size: Optional[int], capacity_bytes: Optional[int],
        compress_command: Optional[List[str]]) -> None:
    """Read, validate and compress chunks ahead of U-Boot writes."""

    offset = 0
    try:
        while not abort.is_set():
            # Wait for a reusable TFTP filename before reading another chunk.
            slot = get_until_aborted(free_slots, abort)
            if slot is None:
                return

            data = input_stream.read(args.buffersize)
            if not data:
                free_slots.put(slot)
                break

            length = len(data)
            validate_chunk(offset, length, block_size, capacity_bytes)
            crc, packed_size = compress_chunk(
                data,
                os.path.join(tftp_root, CHUNK_NAMES[slot]),
                compress_command)
            del data

            item = (offset, length, slot, crc, packed_size)
            if not put_until_aborted(results, item, abort):
                return
            offset += length

        if abort.is_set():
            return
        put_until_aborted(results, None, abort)
    except BaseException as error:
        # Forward preparation failures so flashing cannot report success.
        put_until_aborted(results, error, abort)


# Require explicit confirmation before the destructive UFS operation
def confirm_ufs_flash(capacity_bytes: int) -> None:
    """Ask the terminal user to confirm destructive UFS flashing."""

    # Requiring the exact device number makes accidental confirmation harder.

    confirmation_text = f'FLASH UFS {UFS_DEVICE}'
    LOGGER.info('')
    LOGGER.info('[WARNING: destructive UFS flashing operation]')
    LOGGER.info(
        '[UFS device 0 is reserved for IPL booting and will not be modified.]')
    LOGGER.info(
        '[Target: SCSI/UFS device %d, %.2f GiB]',
        UFS_DEVICE, capacity_bytes / 1024**3)
    LOGGER.info(
        '[All existing data on UFS device %d may be destroyed.]', UFS_DEVICE)
    LOGGER.info('[To continue, type exactly: %s]', confirmation_text)

    try:
        sys.stdout.write('> ')
        sys.stdout.flush()
        # stdin carries binary image data, so confirmation must be read from
        # the controlling terminal rather than with input().

        with open('/dev/tty', 'r', encoding='utf-8') as terminal:
            answer = terminal.readline()
        if not answer:
            raise EOFError
        answer = answer.rstrip('\r\n')
    except (EOFError, KeyboardInterrupt, OSError) as error:
        raise RuntimeError(
            'UFS flashing confirmation requires an interactive terminal '
            'and was cancelled') from error

    if answer != confirmation_text:
        raise RuntimeError(
            'UFS flashing confirmation did not match; '
            'flashing was not started')


# Parse UFS capacity information from the u-boot SCSI output
def get_scsi_device_capacity(
        output: str, device: int) -> Optional[Tuple[int, int]]:
    """Get block count and block size for a SCSI device"""

    # Isolate only the section belonging to the requested SCSI device. This
    # prevents the capacity of device 0 from being mistaken for device 1.

    device_pattern = (
        rf'(?ms)^[ \t]*Device\s+{device}:'
        rf'.*?'
        rf'(?=^[ \t]*Device\s+\d+:|\Z)')

    device_match = re.search(device_pattern, output)

    if not device_match:
        return None

    # U-Boot prints capacity as '(block count x block size)'. These integer
    # values are more reliable for validation than the rounded MB/GB text.

    capacity_match = re.search(
        r'Capacity:.*?\((\d+)\s+x\s+(\d+)\)',
        device_match.group(0),
        re.DOTALL)

    if not capacity_match:
        return None

    return int(capacity_match.group(1)), int(capacity_match.group(2))


# Scan, validate and select the UFS device before flashing
def prepare_ufs_target(
        conn: serial.Serial, uboot_prompt: str) -> Tuple[int, int]:
    """Detect and select the protected UFS data device."""

    # Ask U-Boot to enumerate all UFS logical units and print their geometry.

    conn_send(conn, 'scsi scan\r')
    scan_output = conn_wait_for_any(conn, [uboot_prompt])
    capacity = get_scsi_device_capacity(scan_output, UFS_DEVICE)
    if capacity is None:
        raise RuntimeError(
            f'Could not determine capacity of UFS device {UFS_DEVICE}')

    # Convert device geometry into an exact byte capacity for incremental
    # bounds checking while the stdin stream is consumed.

    block_count, block_size = capacity
    capacity_bytes = block_count * block_size
    # Reject unfamiliar geometry instead of risking writes with bad alignment.

    if block_size not in (512, 4096):
        raise RuntimeError(
            f'Refusing to use UFS device {UFS_DEVICE}: '
            f'unexpected block size {block_size}')

    # Make device 1 current so the following gzwrite scsi commands target it.

    conn_send(conn, f'scsi device {UFS_DEVICE}\r')
    select_output = conn_wait_for_any(conn, [uboot_prompt])
    # Do not trust the command alone: require U-Boot to confirm the selection.

    selection_succeeded = (
        f'Device {UFS_DEVICE}:' in select_output and
        'is now current device' in select_output)
    if not selection_succeeded:
        raise RuntimeError(
            f'Could not confirm selection of UFS device {UFS_DEVICE}')

    LOGGER.info(
        '[Selected UFS device %d: %.2f GiB, block size %d]',
        UFS_DEVICE, capacity_bytes / 1024**3, block_size)
    return block_count, block_size


def do_flash_image(
        args: argparse.Namespace, tftp_root: pathlib.Path) -> None:
    """Flash stdin data to the selected storage device."""

    # Locate the optional host-side accelerator before opening the serial port.

    compress_tool = find_tool(COMPRESS_TOOLS)
    compress_command = (
        build_compress_command(compress_tool)
        if compress_tool is not None
        else None)
    compressor_name = compress_tool or 'python gzip'
    LOGGER.info('[Compressor: %s]', compressor_name)
    if compress_tool is None:
        LOGGER.info(
            '[TIP: install pigz on the host to speed up flashing; otherwise '
            'single-threaded Python gzip will be used.]')

    # Open the board console. The timeout is also used by response waits so a
    # silent or disconnected board produces an error instead of hanging.

    conn = serial.Serial(port=args.serial, baudrate=args.baud, timeout=20)
    # Use the binary stdin stream; text decoding would corrupt image bytes.

    input_stream = sys.stdin.buffer
    producer = None
    # The event lets the main and producer threads request cooperative stop.

    abort = threading.Event()
    # Prepared chunk metadata flows to the main thread through results. Slot
    # numbers flow back through free_slots when a TFTP file can be overwritten.

    results: queue.Queue = queue.Queue(
        maxsize=len(CHUNK_NAMES))
    free_slots: queue.Queue = queue.Queue()

    try:
        # Wake an existing U-Boot prompt or interrupt autoboot if it is
        # starting.

        uboot_prompt = '=>'
        LOGGER.info('[Waiting for u-boot prompt...]')
        conn_send(conn, '\r')
        conn_wait_for_any(
            conn, [uboot_prompt, 'Hit any key to stop autoboot:'])
        conn_send(conn, '\r')
        conn_wait_for_any(conn, [uboot_prompt])
        LOGGER.info('\n[Connected to u-boot]')

        # eMMC does not require SCSI discovery. UFS fills both values below.

        block_size = None
        capacity_bytes = None
        # UFS requires discovery, alignment validation, and explicit approval.

        if args.target == 'ufs':
            block_count, block_size = prepare_ufs_target(conn, uboot_prompt)
            capacity_bytes = block_count * block_size
            if args.buffersize % block_size != 0:
                raise ValueError(
                    f'Buffer size {args.buffersize} is not aligned '
                    f'to UFS block size {block_size}')
            confirm_ufs_flash(capacity_bytes)

        # Change network variables only for this U-Boot session; env save is
        # not
        # called, so persistent board configuration is left untouched.

        if args.serverip:
            conn_send(conn, f'env set serverip {args.serverip}\r')
            conn_wait_for_any(conn, [uboot_prompt])
        if args.ipaddr:
            conn_send(conn, f'env set ipaddr {args.ipaddr}\r')
            conn_wait_for_any(conn, [uboot_prompt])
        # Tell U-Boot which RAM address will hold each downloaded gzip chunk.

        conn_send(conn, f'env set loadaddr {args.loadaddr}\r')
        conn_wait_for_any(conn, [uboot_prompt])
        LOGGER.info('')

        # Initially both rotating TFTP filenames are free for the producer.

        for slot in range(len(CHUNK_NAMES)):
            free_slots.put(slot)

        # A monotonic clock cannot jump if the host wall clock is corrected.

        flash_started_at = time.monotonic()
        # Start host-side preparation in parallel with U-Boot transfers/writes.

        producer = threading.Thread(
            target=prepare_chunks,
            args=(args, input_stream, tftp_root, free_slots, results, abort,
                  block_size, capacity_bytes, compress_command),
            daemon=True)
        producer.start()
        bytes_sent = 0

        # Consume prepared chunks in image order and write them synchronously.

        while True:
            # Blocking here is expected when compression is slower than U-Boot.

            item = results.get()
            # None means that the producer reached normal end-of-stream.

            if item is None:
                break
            # Re-raise producer errors in the main thread to trigger cleanup.

            if isinstance(item, BaseException):
                raise item

            # Unpack everything needed to transfer and verify this chunk.

            offset, length, slot, crc, packed_size = item
            chunk_name = CHUNK_NAMES[slot]
            # Download the complete compressed file into U-Boot RAM.

            conn_send(conn, f'tftp ${{loadaddr}} {chunk_name}\r')
            conn_wait_for_any(conn, [f'Bytes transferred = {packed_size}'])
            conn_wait_for_any(conn, [uboot_prompt])

            # U-Boot copied this chunk into RAM. Its TFTP file may now be
            # reused while gzwrite writes the RAM contents to storage.
            free_slots.put(slot)
            # Decompress the RAM buffer and write raw bytes at the image
            # offset.

            conn_send(conn, build_write_command(args, offset))
            conn_wait_for_any(conn, [f'{length} bytes, crc 0x{crc:08x}'])
            LOGGER.info('  [CRC is OK]')
            conn_wait_for_any(conn, [uboot_prompt])
            # Progress reports committed uncompressed bytes, not TFTP bytes.

            bytes_sent += length
            LOGGER.info('\n[Progress: %s]', f'{bytes_sent:_}')
    # Cleanup runs after success, serial/TFTP failure, or producer failure.

    finally:
        # Stop further chunk production before releasing shared resources.

        abort.set()
        if producer is not None:
            if producer.is_alive():
                input_stream.close()
            producer.join(timeout=10)
        # Temporary chunks must not remain in the TFTP root after this run.

        for name in CHUNK_NAMES:
            path = os.path.join(tftp_root, name)
            if os.path.exists(path):
                os.remove(path)
        conn.close()

    if producer is not None and producer.is_alive():
        raise RuntimeError('Chunk preparation thread did not stop cleanly')

    # Report elapsed wall time only after the producer stopped cleanly.

    elapsed = time.monotonic() - flash_started_at
    LOGGER.info('[Total time: %.1fs]', elapsed)
    LOGGER.info('[Image was flashed successfully]')


def conn_wait_for_any(conn: serial.Serial, expect: List[str]) -> str:
    """ Wait for any of the expected response from u-boot"""

    # Accumulate printable and non-printable serial data for substring
    # matching.

    rcv_str = ''
    # stay in the read loop until any of expected string is received
    # in other words - all expected substrings are not in received buffer
    while all([x not in rcv_str for x in expect]):
        # Read one byte at a time because U-Boot responses have no fixed
        # length.

        data = conn.read(1)

        # pyserial returns empty bytes when its configured timeout expires.

        if not data:
            raise TimeoutError(
                f'Timeout waiting for {expect} from the device')

        # Convert the byte for display and expected-text matching.

        rcv_char = chr(data[0])

        # Echo readable console output while retaining all bytes in rcv_str.

        if (rcv_char in printable or rcv_char == '\b'):
            sys.stdout.write(rcv_char)
            sys.stdout.flush()

        rcv_str += rcv_char

    # Return captured output for parsing SCSI device information
    return rcv_str


def conn_send(conn: serial.Serial, data: str) -> None:
    """ Send the string to the u-boot"""

    # U-Boot commands are ASCII and include their terminating carriage return.

    conn.write(data.encode('ascii'))


# Execute the CLI only when launched as a program, not when imported by tests.

if __name__ == '__main__':
    main()
