"""GEN5 Xen product model."""

from __future__ import annotations

import shlex
import textwrap
from typing import Any, Iterable, Mapping

from components.product_types.src.base import (
    ProductComponent,
    ProductDomain,
    ProductTargetResolverPlan,
    ProductTypeAdapter,
)


def _serial_adb_resolver_command(console_device: str) -> str:
    script = textwrap.dedent(
        r"""
        import json
        import re
        import serial
        import sys
        import time

        port = sys.argv[1]
        status = {
            "board": None,
            "serial": False,
            "dom0": None,
            "dom0_login": None,
            "domd": None,
            "domd_login": None,
            "adb": None,
            "adb_serial": "",
            "console_tail": "",
            "error": "",
        }
        connection = None
        transcript = bytearray()

        def publish():
            print("__MRC_BOARD_PROGRESS__" + json.dumps(status, sort_keys=True), flush=True)

        def publish_log(message):
            print("__MRC_BOARD_LOG__" + json.dumps({"message": message}), flush=True)

        def clean_console(value):
            value = re.sub(rb"\x1b\[[0-?]*[ -/]*[@-~]", b"", value)
            value = bytes(byte for byte in value if byte in (9, 10, 13) or 32 <= byte < 127)
            lines = [line.strip() for line in value.decode("ascii", "replace").replace("\r", "\n").splitlines()]
            return " | ".join(line for line in lines if line)

        def record_output(chunk):
            transcript.extend(chunk)
            del transcript[:-8192]
            output = clean_console(chunk)
            if output:
                publish_log("console: " + output)

        def send(value, description=""):
            if description:
                publish_log("send: " + description)
            connection.write(value)
            connection.flush()

        def wait_for_output(timeout):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                chunk = connection.read(4096)
                if chunk:
                    record_output(chunk)
                    return chunk
            return b""

        def wait_for_match(pattern, timeout, description):
            deadline = time.monotonic() + timeout
            output = bytearray()
            while time.monotonic() < deadline:
                chunk = connection.read(4096)
                if chunk:
                    output.extend(chunk)
                    record_output(chunk)
                    match = re.search(pattern, bytes(output))
                    if match:
                        return match, bytes(output)
            raise RuntimeError("timed out waiting for " + description)

        def wait_for_prompt(timeout):
            pattern = rb"(?im)(login:\s*$|password:\s*$|[^\r\n]*[#$]\s*$)"
            match, output = wait_for_match(pattern, timeout, "console prompt")
            value = match.group(1).lower().lstrip()
            if value.startswith(b"login:"):
                return "login", output
            if value.startswith(b"password:"):
                return "password", output
            return "shell", output

        def login_root(timeout, refresh_login=False):
            prompt, _output = wait_for_prompt(timeout)
            if prompt == "shell":
                return False
            if refresh_login:
                # Discard a partial username left while the guest console was attaching.
                for _attempt in range(3):
                    send(b"\r", "empty input to obtain a clean login prompt")
                    prompt, _output = wait_for_prompt(timeout)
                    if prompt == "login":
                        break
                    if prompt == "shell":
                        return False
                else:
                    raise RuntimeError("could not obtain a clean login prompt")
            elif prompt == "password":
                raise RuntimeError("unexpected password prompt")
            send(b"root\r", "login as root")
            prompt, _output = wait_for_prompt(timeout)
            if prompt == "password":
                raise RuntimeError("root login requires a password")
            if prompt != "shell":
                raise RuntimeError("root login did not reach a shell prompt")
            return True

        def console_tail():
            return clean_console(bytes(transcript))[-1000:]

        try:
            exclusive = {} if "://" in port else {"exclusive": True}
            publish_log("opening serial console " + port)
            connection = serial.serial_for_url(
                port,
                baudrate=1843200,
                timeout=0.1,
                write_timeout=2,
                **exclusive,
            )
            status["serial"] = True
            publish()
            send(b"\r\r\r", "three Enter characters to probe console responsiveness")
            initial_output = wait_for_output(3)
            if not initial_output:
                # The serial console may still be attached to an unresponsive Xen guest.
                send(b"\x1d\r\r\r", "Ctrl-] and three Enter characters to request Dom0")
                initial_output = wait_for_output(3)
            if not initial_output:
                status["board"] = False
                publish()
                raise RuntimeError("board did not answer on the serial console")
            status["board"] = True
            publish()

            # Ctrl-] detaches a stale xl console session and returns to Dom0.
            send(b"\x1d\r\r\r", "Ctrl-] and three Enter characters for a fresh Dom0 prompt")
            status["dom0"] = False
            status["dom0_login"] = login_root(15, refresh_login=True)
            status["dom0"] = True
            publish()
            status["domd"] = False
            send(
                b"xl list DomD >/dev/null 2>&1; printf '__MRC_DOMD__%s\\n' \"$?\"\r",
                "check whether DomD is running",
            )
            match, _output = wait_for_match(rb"__MRC_DOMD__([0-9]+)", 10, "DomD status")
            if match.group(1) != b"0":
                raise RuntimeError("DomD is not running")
            status["domd"] = True
            publish()

            send(b"xl console DomD\r", "enter DomD console")
            send(b"\r\r\r", "three Enter characters for the DomD login prompt")
            status["domd_login"] = login_root(20, refresh_login=True)
            status["adb"] = False
            send(
                b"ip=$(ip -4 route get 1.1.1.1 2>/dev/null | "
                b"awk '{for(i=1;i<=NF;i++) if($i==\"src\"){print $(i+1); exit}}'); "
                b"printf '__MRC_ADB_IP__%s\\n' \"$ip\"\r",
                "resolve the DomD IPv4 address for ADB",
            )
            match, _output = wait_for_match(
                rb"__MRC_ADB_IP__(\d{1,3}(?:\.\d{1,3}){3})",
                15,
                "DomD IPv4 address",
            )
            status["adb_serial"] = match.group(1).decode() + ":5555"
            status["adb"] = True
            publish()
        except Exception as error:
            status["error"] = str(error)
        finally:
            status["console_tail"] = console_tail()
            publish()
            if connection is not None:
                try:
                    send(b"\x1d", "leave the active guest console")
                finally:
                    connection.close()

        print("__MRC_BOARD_STATUS__" + json.dumps(status, sort_keys=True))
        if status["adb_serial"]:
            print(status["adb_serial"])
        if status["error"]:
            print("DomD ADB resolver: " + status["error"], file=sys.stderr)
            raise SystemExit(1)
        """
    ).strip()
    return (
        f"console={shlex.quote(console_device)}; "
        "if [ -z \"$console\" ]; then "
        "console=$(ls -1 /dev/GEN5_CONSOLE* 2>/dev/null | head -n 1 || true); "
        "fi; "
        "if [ -z \"$console\" ]; then "
        "echo 'GEN5 console device not found under /dev/GEN5_CONSOLE*' >&2; exit 2; "
        "fi; "
        f"python3 -c {shlex.quote(script)} \"$console\""
    )


class Gen5XenAndroidProductAdapter(ProductTypeAdapter):
    """Domains assembled by the GEN5 Xen Moulin product."""

    type_id = "gen5_xen_android"
    label = "GEN5 Xen Android"
    description = "GEN5 Xen product with one or more Android guest domains."

    def domains(self, components: Iterable[ProductComponent]) -> tuple[ProductDomain, ...]:
        return tuple(
            ProductDomain(component.name, "android")
            for component in components
            if component.builder_type == "android"
        )

    def android_adb_resolver(self, board: Mapping[str, Any]) -> ProductTargetResolverPlan | None:
        console_device = str(board.get("console_device") or "").strip()
        if console_device:
            return ProductTargetResolverPlan(
                _serial_adb_resolver_command(console_device),
                timeout_seconds=90,
            )
        mac_address = str(board.get("mac_address") or "").strip().lower()
        if mac_address:
            command = (
                "ip neigh show | "
                f"awk -v mac={shlex.quote(mac_address)} "
                "'tolower($5) == mac && $1 ~ /^[0-9.]+$/ "
                "{ print $1 \":5555\"; found=1; exit } END { if (!found) exit 1 }'"
            )
            return ProductTargetResolverPlan(command)
        board_ip = str(board.get("board_ip") or "").strip()
        if board_ip:
            return ProductTargetResolverPlan(f"printf '%s\\n' {shlex.quote(board_ip + ':5555')}")
        return ProductTargetResolverPlan(
            _serial_adb_resolver_command(""),
            timeout_seconds=90,
        )
