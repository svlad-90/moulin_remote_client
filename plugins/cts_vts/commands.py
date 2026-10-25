"""Shell command construction for CTS and VTS workflows."""

from __future__ import annotations

import base64
import json
import shlex
from pathlib import PurePosixPath
from typing import Any, Mapping


def run_dir(root: str, name: str) -> str:
    return str(PurePosixPath(root) / name)


def deploy_agent_command(root: str, name: str, source: bytes) -> str:
    target = str(PurePosixPath(run_dir(root, name)) / "runner_agent.py")
    payload = base64.b64encode(source).decode("ascii")
    return (
        f"mkdir -p {shlex.quote(run_dir(root, name))} && "
        f"printf %s {shlex.quote(payload)} | base64 -d > {shlex.quote(target)} && "
        f"chmod 700 {shlex.quote(target)}"
    )


def write_plan_command(root: str, name: str, plan: dict[str, Any]) -> str:
    target = str(PurePosixPath(run_dir(root, name)) / "plan.json")
    payload = base64.b64encode(json.dumps(plan, indent=2, sort_keys=True).encode()).decode("ascii")
    return f"printf %s {shlex.quote(payload)} | base64 -d > {shlex.quote(target)}"


def agent_command(root: str, name: str, action: str, *args: str) -> str:
    directory = run_dir(root, name)
    suffix = " ".join(shlex.quote(arg) for arg in args)
    return f"python3 {shlex.quote(str(PurePosixPath(directory) / 'runner_agent.py'))} {shlex.quote(action)} {suffix}".rstrip()


def agent_status_command(root: str, name: str) -> str:
    directory = run_dir(root, name)
    agent = str(PurePosixPath(directory) / "runner_agent.py")
    missing = json.dumps({"status": "not-prepared"}, sort_keys=True)
    return (
        f"if test -f {shlex.quote(agent)}; then "
        f"{agent_command(root, name, 'status')}; "
        f"else printf '%s\\n' {shlex.quote(missing)}; fi"
    )


def adb_probe_command(devices: list[dict[str, Any]]) -> str:
    serials = [str(device.get("serial") or "") for device in devices]
    script = (
        "import json,subprocess,sys; out={}; "
        "exec(\"for s in sys.argv[1:]:\\n"
        " subprocess.run(['adb','connect',s],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\\n"
        " state=subprocess.run(['adb','-s',s,'get-state'],capture_output=True,text=True)\\n"
        " if state.returncode or state.stdout.strip()!='device': out[s]='waiting-for-adb'; continue\\n"
        " boot=subprocess.run(['adb','-s',s,'shell','getprop','sys.boot_completed'],capture_output=True,text=True)\\n"
        " out[s]='ready' if boot.returncode==0 and boot.stdout.strip()=='1' else 'booting'\"); "
        "print(json.dumps(out,sort_keys=True))"
    )
    return "python3 -c " + shlex.quote(script) + " " + " ".join(shlex.quote(serial) for serial in serials)


def adb_inventory_command(devices: list[dict[str, Any]]) -> str:
    payload = base64.b64encode(
        json.dumps(
            [
                {
                    "board_profile": str(device.get("board_profile") or ""),
                    "board_id": str(device.get("board_id") or ""),
                    "serial": str(device.get("serial") or ""),
                }
                for device in devices
            ]
        ).encode()
    ).decode("ascii")
    script = """
import base64
import json
import subprocess
import sys

devices = json.loads(base64.b64decode(sys.argv[1]).decode())
results = []
for device in devices:
    serial = device["serial"]
    connect = subprocess.run(["adb", "connect", serial], capture_output=True, text=True)
    state = subprocess.run(["adb", "-s", serial, "get-state"], capture_output=True, text=True)
    connected = state.returncode == 0 and state.stdout.strip() == "device"
    boot_completed = ""
    if connected:
        boot = subprocess.run(
            ["adb", "-s", serial, "shell", "getprop", "sys.boot_completed"],
            capture_output=True,
            text=True,
        )
        if boot.returncode == 0:
            boot_completed = boot.stdout.strip()
    adb_state = "ready" if boot_completed == "1" else "booting" if connected else "waiting-for-adb"
    available = adb_state == "ready"
    row = {
        "board_profile": device["board_profile"],
        "board_id": device["board_id"],
        "serial": serial,
        "available": available,
        "state": adb_state,
        "adb_state": adb_state,
        "android_serial": "",
        "build_id": "",
        "build_incremental": "",
        "build_fingerprint": "",
        "error": "",
    }
    if available:
        properties = {
            "android_serial": "ro.serialno",
            "build_id": "ro.build.id",
            "build_incremental": "ro.build.version.incremental",
            "build_fingerprint": "ro.build.fingerprint",
        }
        for key, prop in properties.items():
            value = subprocess.run(
                ["adb", "-s", serial, "shell", "getprop", prop],
                capture_output=True,
                text=True,
            )
            if value.returncode == 0:
                row[key] = value.stdout.strip()
    results.append(row)
print(json.dumps(results, sort_keys=True))
""".strip()
    return "python3 -c " + shlex.quote(script) + " " + shlex.quote(payload)


def product_dir(projects_dir: str, project_dir: str) -> str:
    if project_dir.startswith("/"):
        return project_dir.rstrip("/")
    return str(PurePosixPath(projects_dir) / project_dir).rstrip("/")


def product_build_command(directory: str, targets: list[str]) -> str:
    quoted_targets = " ".join(shlex.quote(target) for target in targets)
    return f"cd {shlex.quote(directory)} && ninja {quoted_targets}"


def vts_build_command(
    build_dir: str,
    environment: Mapping[str, str],
    setup_commands: tuple[str, ...],
) -> str:
    steps = [f"cd {shlex.quote(build_dir)}"]
    if environment:
        assignments = " ".join(
            f"{key}={shlex.quote(value)}" for key, value in environment.items()
        )
        steps.append(f"export {assignments}")
    steps.extend(setup_commands)
    steps.append("make vts -j")
    return " && ".join(steps)
