"""Local shell script construction service."""

from __future__ import annotations

import shlex


class ProcessScriptService:
    """Own local diagnostic shell command construction."""

    def local_log_command(self, *lines: str, exit_code: int = 0) -> list[str]:
        script = "".join(f"printf '%s\\n' {shlex.quote(line)}\n" for line in lines)
        script += f"exit {int(exit_code)}\n"
        return ["bash", "-lc", script]


def process_script_service() -> ProcessScriptService:
    return ProcessScriptService()
