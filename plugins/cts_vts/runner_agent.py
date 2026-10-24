#!/usr/bin/env python3
"""Detached CTS/VTS run supervisor deployed to the test runner."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PLAN_PATH = ROOT / "plan.json"
STATE_PATH = ROOT / "state.json"
STOP_PATH = ROOT / "stop.requested"
LOGS_DIR = ROOT / "logs"
SESSION = "mrc-" + re.sub(r"[^A-Za-z0-9_.-]", "-", ROOT.name)
RESULT_ROW = re.compile(
    r"^\s*(?P<session>\d+)\s+\d+\s+\d+\s+"
    r"(?P<complete>\d+)\s+of\s+(?P<total>\d+)\s+",
    re.MULTILINE,
)
MODULE_PATTERNS = (
    re.compile(r"(?:Starting|Running)\s+(?:module\s+)?['\"]?([A-Za-z0-9_.:+-]+)"),
    re.compile(r"module(?:Name)?[=: ]+['\"]?([A-Za-z0-9_.:+-]+)", re.IGNORECASE),
)


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_state(state: dict[str, Any]) -> None:
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(STATE_PATH)


def initial_state() -> dict[str, Any]:
    return {
        "status": "idle",
        "active_suite": "",
        "head_session": None,
        "completed_modules": 0,
        "total_modules": 0,
        "no_progress_runs": 0,
        "reboots": 0,
        "reflashes": 0,
        "skip_cycles": 0,
        "excluded_modules": [],
        "completed_suites": [],
        "history": [],
        "error": "",
    }


def adb_state(serial: str) -> str:
    subprocess.run(["adb", "connect", serial], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    result = subprocess.run(["adb", "-s", serial, "get-state"], capture_output=True, text=True, check=False)
    if result.returncode != 0 or result.stdout.strip() != "device":
        return "waiting-for-adb"
    boot = subprocess.run(
        ["adb", "-s", serial, "shell", "getprop", "sys.boot_completed"],
        capture_output=True,
        text=True,
        check=False,
    )
    return "ready" if boot.returncode == 0 and boot.stdout.strip() == "1" else "booting"


def device_statuses(plan: dict[str, Any]) -> dict[str, str]:
    return {str(device["serial"]): adb_state(str(device["serial"])) for device in plan.get("devices", [])}


def wait_for_devices(plan: dict[str, Any], serials: set[str] | None = None) -> bool:
    expected = serials or {str(device.get("serial") or "") for device in plan.get("devices", [])}
    if not expected:
        return True
    deadline = time.monotonic() + int(plan["test_profile"].get("adb_loss_timeout_minutes", 5)) * 60
    while True:
        statuses = device_statuses(plan)
        pending = {serial: statuses.get(serial, "waiting-for-adb") for serial in expected}
        if pending and all(state == "ready" for state in pending.values()):
            return True
        print(json.dumps(pending, sort_keys=True), flush=True)
        if time.monotonic() >= deadline:
            return False
        time.sleep(10)


def run_argv_hooks(commands: object, *, serial: str, timeout_seconds: int) -> int:
    if not isinstance(commands, list) or not commands:
        return 1
    for command in commands:
        if not isinstance(command, list) or not command:
            return 1
        rendered = [str(argument).replace("{serial}", serial) for argument in command]
        try:
            result = subprocess.run(rendered, timeout=timeout_seconds, check=False)
        except subprocess.TimeoutExpired:
            return 124
        if result.returncode != 0:
            return result.returncode
    return 0


def recover_devices(plan: dict[str, Any], action: str, serials: set[str] | None = None) -> bool:
    ok = True
    post_execute_delay = 0
    for device in plan.get("devices", []):
        serial = str(device.get("serial") or "")
        if serials is not None and serial not in serials:
            continue
        operation = device.get(action) if isinstance(device.get(action), dict) else {}
        commands = operation.get("commands", [])
        timeout_seconds = int(operation.get("execute_timeout_seconds", 1800))
        post_execute_delay = max(post_execute_delay, int(operation.get("post_execute_delay_seconds", 10)))
        ok = run_argv_hooks(commands, serial=serial, timeout_seconds=timeout_seconds) == 0 and ok
    if not ok:
        return False
    time.sleep(post_execute_delay)
    return wait_for_devices(plan, serials)


def tradefed_path(plan: dict[str, Any], suite: str) -> Path:
    directory = Path(str(plan["suite_dirs"][suite])).expanduser()
    return directory / "tools" / f"{suite}-tradefed"


def list_results(plan: dict[str, Any], suite: str) -> tuple[int | None, int, int, str]:
    result = subprocess.run(
        [str(tradefed_path(plan, suite)), "list", "results"],
        cwd=tradefed_path(plan, suite).parent.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    session, complete, total = parse_result_listing(output)
    return session, complete, total, output


def parse_result_listing(output: str) -> tuple[int | None, int, int]:
    rows = list(RESULT_ROW.finditer(output))
    if not rows:
        return None, 0, 0
    row = rows[-1]
    return int(row["session"]), int(row["complete"]), int(row["total"])


def head_module(log_path: Path) -> str:
    try:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-2_000_000:]
    except OSError:
        return ""
    found = ""
    for pattern in MODULE_PATTERNS:
        matches = pattern.findall(tail)
        if matches:
            found = matches[-1]
    return found


def invocation(plan: dict[str, Any], state: dict[str, Any], suite: str) -> list[str]:
    profile = plan["test_profile"]
    session = state.get("head_session") if state.get("active_suite") == suite else None
    if session is None:
        command = [str(tradefed_path(plan, suite)), "run", suite]
        serials = [str(device["serial"]) for device in plan.get("devices", [])]
        if len(serials) > 1:
            command += ["--shard-count", str(len(serials))]
        for serial in serials:
            command += ["-s", serial]
    else:
        command = [
            str(tradefed_path(plan, suite)),
            "run",
            "retry",
            "--retry",
            str(session),
            "--retry-type",
            "NOT_EXECUTED",
        ]
    for module in state.get("excluded_modules", []):
        command += ["--exclude-filter", str(module)]
    command += [str(value) for value in profile.get("extra_args", [])]
    return command


def wait_invocation(process: subprocess.Popen[Any], plan: dict[str, Any], state: dict[str, Any]) -> set[str]:
    timeout = int(plan["test_profile"].get("adb_loss_timeout_minutes", 5)) * 60
    unavailable_since: dict[str, float] = {}
    timed_out: set[str] = set()
    while process.poll() is None and not STOP_PATH.exists():
        now = time.monotonic()
        for serial, device_state in device_statuses(plan).items():
            if device_state == "ready":
                unavailable_since.pop(serial, None)
                continue
            unavailable_since.setdefault(serial, now)
            if now - unavailable_since[serial] >= timeout:
                timed_out.add(serial)
        if timed_out:
            process.send_signal(signal.SIGTERM)
            break
        time.sleep(10)
    if STOP_PATH.exists() and process.poll() is None:
        process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    return timed_out


def record_attempt(state: dict[str, Any], suite: str, returncode: int, log_path: Path) -> None:
    state["history"].append(
        {
            "suite": suite,
            "session": state.get("head_session"),
            "completed_modules": state.get("completed_modules", 0),
            "total_modules": state.get("total_modules", 0),
            "returncode": returncode,
            "log": str(log_path),
            "timestamp": int(time.time()),
        }
    )


def apply_no_progress_recovery(plan: dict[str, Any], state: dict[str, Any], log_path: Path) -> bool:
    profile = plan["test_profile"]
    if state["no_progress_runs"] < int(profile.get("no_progress_runs", 3)):
        return True
    state["no_progress_runs"] = 0
    if state["reboots"] < int(profile.get("max_reboots", 2)):
        state["reboots"] += 1
        return recover_devices(plan, "reboot")
    if state["reflashes"] < int(profile.get("max_reflashes", 1)):
        state["reflashes"] += 1
        return recover_devices(plan, "reflash")
    module = head_module(log_path)
    if module and module not in state["excluded_modules"]:
        state["excluded_modules"].append(module)
        state["skip_cycles"] += 1
        state["reboots"] = 0
        state["reflashes"] = 0
        return state["skip_cycles"] <= int(profile.get("max_skip_cycles", 1))
    return False


def supervise() -> int:
    plan = load_json(PLAN_PATH, {})
    state = load_json(STATE_PATH, initial_state())
    if not state.get("excluded_modules"):
        state["excluded_modules"] = list(plan.get("test_profile", {}).get("skipped_modules", []))
    LOGS_DIR.mkdir(exist_ok=True)
    STOP_PATH.unlink(missing_ok=True)
    state.update({"status": "running", "error": ""})
    save_state(state)
    for suite in plan.get("suites", []):
        if suite in state.get("completed_suites", []):
            continue
        if state.get("active_suite") != suite:
            state["active_suite"] = suite
            state["head_session"] = None
            state["completed_modules"] = 0
            state["total_modules"] = 0
        while not STOP_PATH.exists():
            log_path = LOGS_DIR / f"{suite}-{int(time.time())}.log"
            command = invocation(plan, state, suite)
            with log_path.open("ab", buffering=0) as output:
                output.write(("$ " + shlex.join(command) + "\n").encode())
                process = subprocess.Popen(command, cwd=tradefed_path(plan, suite).parent.parent, stdout=output, stderr=subprocess.STDOUT)
                unavailable = wait_invocation(process, plan, state)
            if unavailable:
                recover_devices(plan, "reboot", unavailable)
            previous = int(state.get("completed_modules", 0))
            session, complete, total, listing = list_results(plan, suite)
            (LOGS_DIR / f"{suite}-results.log").write_text(listing, encoding="utf-8")
            state["head_session"] = session
            state["completed_modules"] = complete
            state["total_modules"] = total
            state["no_progress_runs"] = 0 if complete > previous else int(state.get("no_progress_runs", 0)) + 1
            record_attempt(state, suite, process.returncode, log_path)
            save_state(state)
            if total and complete >= total:
                state.setdefault("completed_suites", []).append(suite)
                save_state(state)
                break
            if not apply_no_progress_recovery(plan, state, log_path):
                state.update({"status": "failed", "error": "no module progress after configured recovery"})
                save_state(state)
                return 1
            save_state(state)
    state["status"] = "stopped" if STOP_PATH.exists() else "completed"
    save_state(state)
    return 0


def start() -> int:
    if not PLAN_PATH.is_file():
        raise SystemExit("plan.json is missing; prepare the run first")
    plan = load_json(PLAN_PATH, {})
    state = load_json(STATE_PATH, initial_state())
    state.update({"status": "waiting-for-devices", "error": ""})
    save_state(state)
    if not wait_for_devices(plan):
        state.update(
            {
                "status": "blocked",
                "error": "Android devices did not become ready before the configured ADB timeout",
                "device_states": device_statuses(plan),
            }
        )
        save_state(state)
        return 2
    subprocess.run(["tmux", "kill-session", "-t", SESSION], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    STOP_PATH.unlink(missing_ok=True)
    command = ["tmux", "new-session", "-d", "-s", SESSION, sys.executable, str(Path(__file__).resolve()), "supervise"]
    result = subprocess.run(command, check=False)
    return result.returncode


def stop() -> int:
    STOP_PATH.touch()
    subprocess.run(["tmux", "kill-session", "-t", SESSION], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    state = load_json(STATE_PATH, initial_state())
    state["status"] = "stopped"
    save_state(state)
    return 0


def reset(scope: str) -> int:
    stop()
    if scope == "all":
        for child in ROOT.iterdir():
            if child.name == Path(__file__).name:
                continue
            shutil.rmtree(child) if child.is_dir() else child.unlink(missing_ok=True)
    else:
        shutil.rmtree(LOGS_DIR, ignore_errors=True)
        STATE_PATH.unlink(missing_ok=True)
        STOP_PATH.unlink(missing_ok=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("probe", "start", "supervise", "stop", "status", "reset"))
    parser.add_argument("scope", nargs="?", choices=("results", "all"), default="results")
    args = parser.parse_args()
    if args.action == "probe":
        statuses = device_statuses(load_json(PLAN_PATH, {}))
        print(json.dumps(statuses, sort_keys=True))
        return 0 if all(state == "ready" for state in statuses.values()) else 2
    if args.action == "start":
        return start()
    if args.action == "supervise":
        return supervise()
    if args.action == "stop":
        return stop()
    if args.action == "reset":
        return reset(args.scope)
    print(json.dumps(load_json(STATE_PATH, initial_state()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
