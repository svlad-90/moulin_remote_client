"""Preflight output parsing and formatting."""

from __future__ import annotations

from components.ui.src.status_segments import preflight_part_ok


def parse_preflight_values(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def format_preflight_values(values: dict[str, str]) -> str:
    if not values:
        return "failed"
    if "ssh" in values and "project" not in values:
        parts = [f"ssh {values.get('ssh', '?')}"]
        if values.get("cwd"):
            parts.append(f"cwd {values['cwd']}")
        return " | ".join(parts)
    parts = [
        f"project {values.get('project', '?')}",
        f"disk {values.get('disk', '?')}",
        f"git {values.get('git', '?')}",
        f"docker {values.get('docker', '?')}",
        f"origin {values.get('origin', '?')}",
        f"ref {values.get('ref', '?')}",
    ]
    return " | ".join(parts)


def format_preflight(output: str) -> tuple[str, dict[str, str]]:
    values = parse_preflight_values(output)
    return format_preflight_values(values), values


def prepare_remote_project_needed(values: dict[str, str], project_git_url: str) -> bool:
    project = values.get("project", "")
    origin = values.get("origin", "")
    if project in {"missing", "not-git", "not-directory", "inaccessible"}:
        return True
    if origin == "missing" and project_git_url:
        return True
    return origin.startswith("mismatch:")


def checkout_git_ref_needed(values: dict[str, str], project_git_ref: str) -> bool:
    if not project_git_ref:
        return False
    ref = values.get("ref", "")
    return ref == "missing" or ref.startswith("mismatch:")


def project_action_requirements(
    values: dict[str, str],
    *,
    project_git_url: str,
    project_git_ref: str,
) -> dict[str, bool]:
    return {
        "prepare_remote_project": prepare_remote_project_needed(values, project_git_url),
        "checkout_git_ref": checkout_git_ref_needed(values, project_git_ref),
    }
