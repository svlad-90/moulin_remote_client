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


def main_footer_text(*, active_job: bool, focus_panel: str, menu_focus: str = "items") -> str:
    if active_job:
        if focus_panel == "actions" and menu_focus == "tabs":
            return "Running | Left/Right tabs | Up/Down items | f full | s settings | q quit"
        return "Running | Left/Right tabs | Up/Down actions | f full | s settings | q quit"
    if focus_panel == "actions" and menu_focus == "tabs":
        return "Left/Right tabs | Up/Down items | f full logs | s settings | q quit | Esc exit"
    if focus_panel == "actions":
        return "Left/Right tabs | Up/Down select | Enter/r run | f full logs | s settings | q quit | Esc exit"
    return "Left/Right tabs | Up/Down select | f full logs | Enter/r run | s settings | q quit | Esc exit"
