"""Command display formatting service."""

from __future__ import annotations

import re
import os
import shlex


class SyncCommandDisplayService:
    """Format command argv vectors for human-readable logs."""

    def display_command(self, argv: list[str]) -> str:
        safe = [arg.replace("\n", "\\n").replace("\r", "\\r") for arg in argv]
        return shlex.join(safe)

    def display_command_lines(self, argv: list[str]) -> list[str]:
        if os.environ.get("MOULIN_TUI_SHOW_COMMANDS", "").strip().lower() not in {"1", "true", "yes", "on"}:
            return []
        if not any("\n" in arg or "\r" in arg for arg in argv):
            return [f"command: {self.display_command(argv)}"]
        script_index = next((index for index, arg in enumerate(argv) if "\n" in arg or "\r" in arg), len(argv) - 1)
        script = argv[script_index].replace("\r\n", "\n").replace("\r", "\n")
        if script.startswith("printf '%s\\n' ") and "\nexit " in script:
            return ["command: <log message>"]
        prefix_argv = argv[:script_index] + ["<script>"]
        try:
            nested = shlex.split(script)
        except ValueError:
            nested = []
        if len(nested) == 3 and nested[:2] == ["bash", "-lic"] and "\n" in nested[2]:
            prefix_argv = argv[:script_index] + ["bash", "-lic", "<script>"]
            script = nested[2].replace("\r\n", "\n").replace("\r", "\n")
        prefix = self.display_command(prefix_argv)
        lines = [f"command: {prefix}", "script:"]
        for line in script.split("\n"):
            if not line:
                lines.append("")
                continue
            remaining = line
            first = True
            while len(remaining) > 112:
                lines.append(f"  {remaining[:112]}" if first else f"    {remaining[:112]}")
                remaining = remaining[112:]
                first = False
            lines.append(f"  {remaining}" if first else f"    {remaining}")
        return lines

    def sanitize_log_line(self, line: str) -> str:
        line = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line)
        return "".join(char if char == "\t" or ord(char) >= 32 else " " for char in line)


def sync_command_display_service() -> SyncCommandDisplayService:
    return SyncCommandDisplayService()
