"""Header/status segment helpers."""

from __future__ import annotations


Segment = tuple[str, str]


def build_param_segments(build_params: dict[str, str]) -> list[Segment]:
    segments: list[Segment] = [("Params: ", "accent")]
    for index, (name, value) in enumerate(sorted(build_params.items())):
        if index:
            segments.append(("  ", "normal"))
        segments.append((f"{name.removeprefix('ENABLE_')}=", "normal"))
        segments.append((value, "ok" if value == "yes" else "warn"))
    return segments


def preflight_segments(preflight: str, *, connected: bool) -> list[Segment]:
    if not preflight:
        return [("not run", "disabled")]
    if not connected:
        return [(preflight, "disabled")]
    segments: list[Segment] = []
    for index, part in enumerate(preflight.split(" | ")):
        if index:
            segments.append((" | ", "normal"))
        segments.append((part, "ok" if preflight_part_ok(part) else "error"))
    return segments


def preflight_part_ok(part: str) -> bool:
    lowered = part.lower()
    if any(token in lowered for token in ("fail", "missing", "timeout", "failed", "mismatch", "?")):
        return False
    return (
        "ok" in lowered
        or part.startswith("cwd ")
        or part.startswith("disk ")
        or part.startswith("git ##")
        or part.startswith("origin ")
    )


def mapping_status_role(names: list[str], error: str | None, issues: list[str]) -> str:
    if not names:
        return "disabled"
    if error is not None or issues:
        return "warn"
    return "ok"


def main_footer_text(*, active_job: bool, focus_panel: str) -> str:
    if active_job and focus_panel == "logs":
        return "Running | Left actions | Up/Down logs | f full | s settings | q quit"
    if active_job:
        return "Running | Right logs | f full | Up/Down actions | s settings | q quit"
    return "Left/Right panel | Up/Down select/scroll | f full logs | Enter/r run | s settings | q quit | Esc exit"
