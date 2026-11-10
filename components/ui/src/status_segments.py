"""Header/status segment helpers."""

from __future__ import annotations


Segment = tuple[str, str]


def build_param_segments(build_params: dict[str, str]) -> list[Segment]:
    segments: list[Segment] = [("Params: ", "accent")]
    for index, (name, value) in enumerate(sorted(build_params.items())):
        if index:
            segments.append((" | ", "section"))
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
            segments.append((" | ", "section"))
        role = "ok" if preflight_part_ok(part) else "error"
        if (
            part.startswith("git ")
            and "dirty " not in part
            and any(state in part for state in ("ahead ", "behind ", "diverged "))
        ):
            role = "warn"
        segments.append((part, role))
    return segments


def compact_header_preflight(preflight: str, *, narrow: bool = False) -> str:
    """Remove healthy ref details already represented by Product ref."""
    parts = []
    for part in preflight.split(" | "):
        if part.startswith("ref ") or part == "origin ok":
            continue
        parts.append(part)
    return " | ".join(parts)


def product_ref_segments(
    selected_ref: str,
    values: dict[str, str],
    *,
    narrow: bool = False,
) -> list[Segment]:
    """Render a compact configured, remote-tip, and checkout summary."""
    remote_ref = values.get("remote_ref", "not-fetched")
    synced_ref = values.get("synced_ref", "unknown")
    unavailable_remote = {"missing", "not-fetched", "not-configured"}
    checkout_synced = (
        values.get("ref") == "ok"
        and remote_ref not in unavailable_remote
        and remote_ref == synced_ref
    )

    def compact_ref(ref: str) -> str:
        prefix = f"{selected_ref}@"
        return ref[len(prefix):] if selected_ref and ref.startswith(prefix) else ref

    checkout = "synced" if checkout_synced else compact_ref(synced_ref)
    if narrow:
        remote_tip = compact_ref(remote_ref)
        ref_summary = (
            f"{selected_ref}@{remote_tip}"
            if selected_ref and remote_ref not in unavailable_remote
            else selected_ref or "<not configured>"
        )
        return [
            ("Ref: ", "accent"),
            (ref_summary, "normal" if selected_ref else "warn"),
            (" | ", "section"),
            ("HEAD: ", "accent"),
            (checkout, "ok" if checkout_synced else "warn"),
        ]
    return [
        ("Product ref: ", "accent"),
        (selected_ref or "<not configured>", "normal" if selected_ref else "warn"),
        (" | ", "section"),
        ("Cached tip: ", "accent"),
        (compact_ref(remote_ref), "normal" if remote_ref not in unavailable_remote else "warn"),
        (" | ", "section"),
        ("HEAD: ", "accent"),
        (checkout, "ok" if checkout_synced else "warn"),
    ]


def preflight_part_ok(part: str) -> bool:
    lowered = part.lower()
    if any(token in lowered for token in ("error", "fail", "missing", "timeout", "failed", "mismatch", "?")):
        return False
    return (
        "ok" in lowered
        or part.startswith("cwd ")
        or part.startswith("disk ")
        or part.startswith("git ##")
        or part == "git clean"
        or part.startswith("origin ")
    )


def mapping_status_role(names: list[str], error: str | None, issues: list[str]) -> str:
    if not names:
        return "disabled"
    if error is not None or issues:
        return "warn"
    return "ok"


def main_footer_text(
    *,
    active_job: bool,
    focus_panel: str,
    menu_focus: str = "items",
    selected_action_running: bool = False,
) -> str:
    if selected_action_running and focus_panel == "actions" and menu_focus == "items":
        return "Enter/r again stops selected action | Up/Down actions | f full | s settings | q quit"
    if active_job:
        if focus_panel == "actions" and menu_focus == "tabs":
            return "Running | Left/Right tabs | Up/Down items | f full | s settings | q quit"
        return "Running | Left/Right tabs | Up/Down actions | f full | s settings | q quit"
    if focus_panel == "actions" and menu_focus == "tabs":
        return "Left/Right tabs | Up/Down items | f full logs | s settings | q quit | Esc exit"
    if focus_panel == "actions":
        return "Left/Right tabs | Up/Down select | Enter/r run | f full logs | s settings | q quit | Esc exit"
    return "Left/Right tabs | Up/Down select | f full logs | Enter/r run | s settings | q quit | Esc exit"
