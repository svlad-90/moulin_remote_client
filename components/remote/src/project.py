"""Remote project maintenance command service."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from components.config.api import accessors as config_accessors
from components.remote.src import session as remote_session


class RemoteProjectMaintenanceService:
    """Own remote project prepare, checkout, and preflight command use cases."""

    def __init__(self) -> None:
        self.session_service = remote_session.remote_session_command_service()

    def prepare_project_command(self, remote: str, project_dir: str, git_url: str, git_ref: str) -> list[str]:
        parent = str(Path(project_dir).parent)
        name = Path(project_dir).name
        checkout_ref = f" && cd {shlex.quote(name)} && git checkout {shlex.quote(git_ref)}" if git_ref else ""
        if git_url:
            script = (
                f"if [ -d {shlex.quote(project_dir + '/.git')} ]; then "
                f"cd {shlex.quote(project_dir)} && git remote -v; "
                f"elif [ -e {shlex.quote(project_dir)} ]; then "
                f"printf 'target exists but is not a git checkout: %s\\n' {shlex.quote(project_dir)} >&2; exit 2; "
                f"else mkdir -p {shlex.quote(parent)} && cd {shlex.quote(parent)} && "
                f"git clone {shlex.quote(git_url)} {shlex.quote(name)}{checkout_ref}; fi"
            )
        else:
            script = (
                f"if [ -d {shlex.quote(project_dir + '/.git')} ]; then "
                f"cd {shlex.quote(project_dir)} && git remote -v; "
                "else printf 'project Git URL is required to prepare a missing project checkout\\n' >&2; exit 2; fi"
            )
        return ["ssh", remote, script]

    def prepare_project_command_for_config(self, config: dict[str, Any]) -> list[str]:
        return self.prepare_project_command(
            config_accessors.remote_spec_for_config(config),
            config_accessors.remote_project_dir_for_config(config),
            config_accessors.project_git_url_for_config(config),
            config_accessors.project_git_ref_for_config(config),
        )

    def checkout_git_ref_command(self, remote: str, project_dir: str, git_ref: str) -> list[str]:
        if not git_ref:
            raise SystemExit("Git branch/ref is not configured")
        quoted_dir = shlex.quote(project_dir)
        quoted_ref = shlex.quote(git_ref)
        script = (
            f"cd {quoted_dir} || exit 2; "
            "if [ ! -d .git ]; then printf 'target is not a git checkout\\n' >&2; exit 2; fi; "
            "if [ -n \"$(git status --porcelain --untracked-files=no)\" ]; then "
            "printf 'tracked local changes present; refusing to switch ref\\n' >&2; exit 2; fi; "
            "git fetch origin --prune && "
            f"git checkout {quoted_ref} && "
            "git status --short --branch"
        )
        return ["ssh", remote, script]

    def checkout_git_ref_command_for_config(self, config: dict[str, Any]) -> list[str]:
        return self.checkout_git_ref_command(
            config_accessors.remote_spec_for_config(config),
            config_accessors.remote_project_dir_for_config(config),
            config_accessors.project_git_ref_for_config(config),
        )

    def preflight_command(
        self,
        remote: str,
        project_dir: str,
        docker_image: str,
        expected_origin: str,
        expected_ref: str,
    ) -> list[str]:
        if not project_dir:
            return self.session_service.connect_command(remote)
        image = shlex.quote(f"{docker_image}:latest") if docker_image else ""
        docker_check = (
            f"docker image inspect {image} >/dev/null 2>&1 && printf 'docker=ok\\n' || printf 'docker=missing\\n'; "
            if image
            else "printf 'docker=not-configured\\n'; "
        )
        origin_check = (
            "origin=$(git config --get remote.origin.url 2>/dev/null || true); "
            f"if [ \"$origin\" = {shlex.quote(expected_origin)} ]; then printf 'origin=ok\\n'; "
            "elif [ -n \"$origin\" ]; then printf 'origin=mismatch:%s\\n' \"$origin\"; "
            "else printf 'origin=missing\\n'; fi; "
            if expected_origin
            else "origin=$(git config --get remote.origin.url 2>/dev/null || true); "
            "if [ -n \"$origin\" ]; then printf 'origin=%s\\n' \"$origin\"; else printf 'origin=missing\\n'; fi; "
        )
        ref_check = (
            "current_ref=$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true); "
            "current_head=$(git rev-parse --verify HEAD 2>/dev/null || true); "
            f"if [ \"$current_ref\" = {shlex.quote(expected_ref)} ] || [ \"$current_head\" = {shlex.quote(expected_ref)} ]; then printf 'ref=ok\\n'; "
            "elif [ -n \"$current_ref\" ]; then printf 'ref=mismatch:%s\\n' \"$current_ref\"; "
            "elif [ -n \"$current_head\" ]; then printf 'ref=mismatch:%s\\n' \"$current_head\"; "
            "else printf 'ref=missing\\n'; fi; "
            if expected_ref
            else "current_ref=$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true); "
            "if [ -n \"$current_ref\" ]; then printf 'ref=%s\\n' \"$current_ref\"; "
            "else git rev-parse --short HEAD 2>/dev/null | sed 's/^/ref=/'; fi; "
        )
        quoted_project_dir = shlex.quote(project_dir)
        script = (
            f"project_dir={quoted_project_dir}; "
            "if [ ! -e \"$project_dir\" ]; then printf 'project=missing\\n'; exit 0; fi; "
            "if [ ! -d \"$project_dir\" ]; then printf 'project=not-directory\\n'; exit 0; fi; "
            "cd \"$project_dir\" || { printf 'project=inaccessible\\n'; exit 0; }; "
            "df -h . | awk 'NR==2 {print \"disk=\"$4\" free, \"$5\" used\"}'; "
            + docker_check
            + "if [ -d .git ]; then "
            "printf 'project=ok\\n'; "
            "git status --short --branch | sed -n '1s/^/git=/p'; "
            + origin_check
            + ref_check
            + "else printf 'project=not-git\\n'; printf 'git=not-git\\n'; printf 'origin=missing\\n'; printf 'ref=missing\\n'; fi"
        )
        return ["ssh", remote, script]

    def preflight_command_for_config(self, config: dict[str, Any], docker_image: str) -> list[str]:
        project_dir = config_accessors.remote_project_dir_for_config(config)
        return self.preflight_command(
            config_accessors.remote_spec_for_config(config),
            project_dir if project_dir else "",
            docker_image,
            config_accessors.project_git_url_for_config(config),
            config_accessors.project_git_ref_for_config(config),
        )


def remote_project_maintenance_service() -> RemoteProjectMaintenanceService:
    return RemoteProjectMaintenanceService()
