"""Remote project maintenance command service."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from components.config.api import accessors as config_accessors
from components.remote.src import session as remote_session
from components.remote.src import transport


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
                f"elif [ -d {shlex.quote(project_dir)} ] && [ -z \"$(find {shlex.quote(project_dir)} -mindepth 1 -maxdepth 1 -print -quit)\" ]; then "
                f"cd {shlex.quote(parent)} && git clone {shlex.quote(git_url)} {shlex.quote(name)}{checkout_ref}; "
                f"elif [ -e {shlex.quote(project_dir)} ]; then "
                f"printf 'target exists but is not a git checkout: %s\\n' {shlex.quote(project_dir)} >&2; "
                f"printf 'remove or clean the non-empty project directory, then run Prepare remote project again\\n' >&2; exit 2; "
                f"else mkdir -p {shlex.quote(parent)} && cd {shlex.quote(parent)} && "
                f"git clone {shlex.quote(git_url)} {shlex.quote(name)}{checkout_ref}; fi"
            )
        else:
            script = (
                f"if [ -d {shlex.quote(project_dir + '/.git')} ]; then "
                f"cd {shlex.quote(project_dir)} && git remote -v; "
                "else printf 'project Git URL is required to prepare a missing project checkout\\n' >&2; exit 2; fi"
            )
        return transport.ssh_command(remote, script, tty="-tt")

    def prepare_project_command_for_config(self, config: dict[str, Any]) -> list[str]:
        return self.prepare_project_command(
            config_accessors.remote_spec_for_config(config),
            config_accessors.remote_project_dir_for_config(config),
            config_accessors.project_git_url_for_config(config),
            config_accessors.project_git_ref_for_config(config),
        )

    def clean_project_folder_command(self, remote: str, project_dir: str) -> list[str]:
        if not project_dir:
            raise SystemExit("Remote project directory is not configured")
        quoted_dir = shlex.quote(project_dir)
        script = (
            f"project_dir={quoted_dir}; "
            "if [ -z \"$project_dir\" ] || [ \"$project_dir\" = / ]; then "
            "printf 'refusing to remove unsafe project directory: %s\\n' \"$project_dir\" >&2; exit 2; fi; "
            "home_dir=${HOME:-}; "
            "if [ -n \"$home_dir\" ] && [ \"$project_dir\" = \"$home_dir\" ]; then "
            "printf 'refusing to remove HOME as project directory: %s\\n' \"$project_dir\" >&2; exit 2; fi; "
            "parent=$(dirname -- \"$project_dir\"); "
            "name=$(basename -- \"$project_dir\"); "
            "if [ -z \"$name\" ] || [ \"$name\" = . ] || [ \"$name\" = .. ]; then "
            "printf 'refusing to remove unsafe project directory basename: %s\\n' \"$name\" >&2; exit 2; fi; "
            "if [ ! -e \"$project_dir\" ]; then printf 'project directory already absent: %s\\n' \"$project_dir\"; exit 0; fi; "
            "if [ ! -d \"$project_dir\" ]; then printf 'project path is not a directory: %s\\n' \"$project_dir\" >&2; exit 2; fi; "
            "printf 'Clean project folder: %s\\n' \"$project_dir\"; "
            "cd \"$parent\" || exit 2; "
            "rm -rf -- \"$name\"; "
            "printf 'removed project directory: %s\\n' \"$project_dir\""
        )
        return transport.ssh_command(remote, script, tty="-tt")

    def clean_project_folder_command_for_config(self, config: dict[str, Any]) -> list[str]:
        return self.clean_project_folder_command(
            config_accessors.remote_spec_for_config(config),
            config_accessors.remote_project_dir_for_config(config),
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
            f"selected_ref={quoted_ref}; "
            "git fetch origin --prune || exit $?; "
            "if git show-ref --verify --quiet \"refs/remotes/origin/$selected_ref\"; then "
            "if git show-ref --verify --quiet \"refs/heads/$selected_ref\"; then "
            "git checkout \"$selected_ref\" || exit $?; "
            "else git checkout --track -b \"$selected_ref\" \"origin/$selected_ref\" || exit $?; fi; "
            "git merge --ff-only \"origin/$selected_ref\" || exit $?; "
            "else git checkout \"$selected_ref\" || exit $?; fi; "
            "git status --short --branch"
        )
        return transport.ssh_command(remote, script, tty="-tt")

    def stash_and_checkout_git_ref_command(self, remote: str, project_dir: str, git_ref: str) -> list[str]:
        if not git_ref:
            raise SystemExit("Git branch/ref is not configured")
        quoted_dir = shlex.quote(project_dir)
        quoted_ref = shlex.quote(git_ref)
        stash_message = shlex.quote("remote client checkout backup before " + git_ref)
        script = (
            f"cd {quoted_dir} || exit 2; "
            "if [ ! -d .git ]; then printf 'target is not a git checkout\\n' >&2; exit 2; fi; "
            "git add -A || exit $?; "
            "if ! git diff --cached --quiet; then "
            f"git stash push -m {stash_message} -- .; "
            "else printf 'no local changes to stash\\n'; fi; "
            f"selected_ref={quoted_ref}; "
            "git fetch origin --prune || exit $?; "
            "if git show-ref --verify --quiet \"refs/remotes/origin/$selected_ref\"; then "
            "if git show-ref --verify --quiet \"refs/heads/$selected_ref\"; then "
            "git checkout \"$selected_ref\" || exit $?; "
            "else git checkout --track -b \"$selected_ref\" \"origin/$selected_ref\" || exit $?; fi; "
            "git merge --ff-only \"origin/$selected_ref\" || exit $?; "
            "else git checkout \"$selected_ref\" || exit $?; fi; "
            "git status --short --branch"
        )
        return transport.ssh_command(remote, script, tty="-tt")

    def repair_and_checkout_git_ref_command(self, remote: str, project_dir: str, git_ref: str) -> list[str]:
        if not git_ref:
            raise SystemExit("Git branch/ref is not configured")
        quoted_dir = shlex.quote(project_dir)
        quoted_ref = shlex.quote(git_ref)
        stash_message = shlex.quote("remote client checkout backup before " + git_ref)
        script = (
            f"cd {quoted_dir} || exit 2; "
            "if [ ! -d .git ]; then printf 'target is not a git checkout\\n' >&2; exit 2; fi; "
            "lock=.git/index.lock; "
            "if [ -e \"$lock\" ]; then "
            "if command -v fuser >/dev/null 2>&1 && fuser \"$lock\" >/dev/null 2>&1; then "
            "printf 'Git index lock is held by a running process; refusing to remove it\\n' >&2; "
            "fuser -v \"$lock\" >&2 || true; "
            "exit 2; "
            "fi; "
            "printf 'removing stale Git index lock: %s\\n' \"$lock\"; "
            "rm -f \"$lock\"; "
            "else printf 'no Git index lock present\\n'; fi; "
            "stash_before=$(git rev-parse -q --verify refs/stash || true); "
            "git add -A || exit $?; "
            "if ! git diff --cached --quiet; then "
            "stash_rc=0; "
            f"git stash push --include-untracked -m {stash_message} -- . || stash_rc=$?; "
            "stash_after=$(git rev-parse -q --verify refs/stash || true); "
            "if [ \"$stash_after\" = \"$stash_before\" ]; then "
            "printf 'git stash did not create a backup; refusing checkout\\n' >&2; "
            "exit \"${stash_rc:-1}\"; "
            "fi; "
            "if [ -n \"$(git status --porcelain)\" ]; then "
            "printf 'stash backup was created but working tree is still dirty; cleaning backed-up state\\n' >&2; "
            "git reset --hard || exit $?; "
            "git clean -fd || exit $?; "
            "fi; "
            "else printf 'no local changes to stash\\n'; fi; "
            f"selected_ref={quoted_ref}; "
            "git fetch origin --prune || exit $?; "
            "if git show-ref --verify --quiet \"refs/remotes/origin/$selected_ref\"; then "
            "if git show-ref --verify --quiet \"refs/heads/$selected_ref\"; then "
            "git checkout \"$selected_ref\" || exit $?; "
            "else git checkout --track -b \"$selected_ref\" \"origin/$selected_ref\" || exit $?; fi; "
            "git merge --ff-only \"origin/$selected_ref\" || exit $?; "
            "else git checkout \"$selected_ref\" || exit $?; fi; "
            "git status --short --branch"
        )
        return transport.ssh_command(remote, script, tty="-tt")

    def clear_git_index_lock_command(self, remote: str, project_dir: str) -> list[str]:
        quoted_dir = shlex.quote(project_dir)
        script = (
            f"cd {quoted_dir} || exit 2; "
            "if [ ! -d .git ]; then printf 'target is not a git checkout\\n' >&2; exit 2; fi; "
            "lock=.git/index.lock; "
            "if [ ! -e \"$lock\" ]; then printf 'no Git index lock present\\n'; exit 0; fi; "
            "if command -v fuser >/dev/null 2>&1 && fuser \"$lock\" >/dev/null 2>&1; then "
            "printf 'Git index lock is held by a running process; refusing to remove it\\n' >&2; "
            "fuser -v \"$lock\" >&2 || true; "
            "exit 2; "
            "fi; "
            "printf 'removing stale Git index lock: %s\\n' \"$lock\"; "
            "rm -f \"$lock\"; "
            "git status --short --branch"
        )
        return transport.ssh_command(remote, script)

    def checkout_git_ref_command_for_config(self, config: dict[str, Any]) -> list[str]:
        return self.checkout_git_ref_command(
            config_accessors.remote_spec_for_config(config),
            config_accessors.remote_project_dir_for_config(config),
            config_accessors.project_git_ref_for_config(config),
        )

    def stash_and_checkout_git_ref_command_for_config(self, config: dict[str, Any]) -> list[str]:
        return self.stash_and_checkout_git_ref_command(
            config_accessors.remote_spec_for_config(config),
            config_accessors.remote_project_dir_for_config(config),
            config_accessors.project_git_ref_for_config(config),
        )

    def repair_and_checkout_git_ref_command_for_config(self, config: dict[str, Any]) -> list[str]:
        return self.repair_and_checkout_git_ref_command(
            config_accessors.remote_spec_for_config(config),
            config_accessors.remote_project_dir_for_config(config),
            config_accessors.project_git_ref_for_config(config),
        )

    def clear_git_index_lock_command_for_config(self, config: dict[str, Any]) -> list[str]:
        return self.clear_git_index_lock_command(
            config_accessors.remote_spec_for_config(config),
            config_accessors.remote_project_dir_for_config(config),
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
        current_ref_state = (
            "current_ref=$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true); "
            "current_head=$(git rev-parse --verify HEAD 2>/dev/null || true); "
            "current_short=$(git rev-parse --short HEAD 2>/dev/null || true); "
            "synced_name=${current_ref:-detached}; "
            "if [ -n \"$current_short\" ]; then printf 'synced_ref=%s@%s\\n' \"$synced_name\" \"$current_short\"; "
            "else printf 'synced_ref=missing\\n'; fi; "
        )
        ref_check = (
            f"selected_ref={shlex.quote(expected_ref)}; "
            "remote_head=$(git rev-parse --verify --short \"refs/remotes/origin/$selected_ref\" 2>/dev/null || true); "
            "if [ -n \"$remote_head\" ]; then printf 'remote_ref=%s@%s\\n' \"$selected_ref\" \"$remote_head\"; "
            "else printf 'remote_ref=not-fetched\\n'; fi; "
            f"if [ \"$current_ref\" = {shlex.quote(expected_ref)} ] || [ \"$current_head\" = {shlex.quote(expected_ref)} ]; then printf 'ref=ok\\n'; "
            "elif [ -n \"$current_ref\" ]; then printf 'ref=mismatch:%s\\n' \"$current_ref\"; "
            "elif [ -n \"$current_head\" ]; then printf 'ref=mismatch:%s\\n' \"$current_head\"; "
            "else printf 'ref=missing\\n'; fi; "
            if expected_ref
            else "printf 'remote_ref=not-configured\\n'; "
            "if [ -n \"$current_ref\" ]; then printf 'ref=%s\\n' \"$current_ref\"; "
            "elif [ -n \"$current_short\" ]; then printf 'ref=%s\\n' \"$current_short\"; "
            "else printf 'ref=missing\\n'; fi; "
        )
        quoted_project_dir = shlex.quote(project_dir)
        git_status_check = (
            "git_status=$(git status --short --branch 2>&1); git_status_rc=$?; "
            "if [ \"$git_status_rc\" -ne 0 ]; then "
            "git_error=$(printf '%s' \"$git_status\" | tr '\\n' ' '); "
            "printf 'git=error:%s\\n' \"${git_error:-unknown failure}\"; "
            "else "
            "git_header=$(printf '%s\\n' \"$git_status\" | sed -n '1p'); "
            "git_dirty=$(printf '%s\\n' \"$git_status\" | sed '1d;/^$/d' | wc -l | tr -d ' '); "
            "git_ahead=$(printf '%s\\n' \"$git_header\" | sed -n 's/.*ahead \\([0-9][0-9]*\\).*/\\1/p'); "
            "git_behind=$(printf '%s\\n' \"$git_header\" | sed -n 's/.*behind \\([0-9][0-9]*\\).*/\\1/p'); "
            "git_summary=; "
            "if [ \"${git_dirty:-0}\" -gt 0 ]; then git_summary=\"dirty $git_dirty\"; fi; "
            "git_relation=; "
            "if [ -n \"$git_ahead\" ] && [ -n \"$git_behind\" ]; then "
            "git_relation=\"diverged +$git_ahead/-$git_behind\"; "
            "elif [ -n \"$git_ahead\" ]; then git_relation=\"ahead $git_ahead\"; "
            "elif [ -n \"$git_behind\" ]; then git_relation=\"behind $git_behind\"; fi; "
            "if [ -n \"$git_relation\" ]; then "
            "if [ -n \"$git_summary\" ]; then git_summary=\"$git_summary, $git_relation\"; "
            "else git_summary=$git_relation; fi; fi; "
            "if [ -z \"$git_summary\" ]; then git_summary=clean; fi; "
            "printf 'git=%s\\n' \"$git_summary\"; "
            "fi; "
        )
        script = (
            f"project_dir={quoted_project_dir}; "
            "if [ ! -e \"$project_dir\" ]; then printf 'project=missing\\n'; exit 0; fi; "
            "if [ ! -d \"$project_dir\" ]; then printf 'project=not-directory\\n'; exit 0; fi; "
            "cd \"$project_dir\" || { printf 'project=inaccessible\\n'; exit 0; }; "
            "df -h . | awk 'NR==2 {print \"disk=\"$4\" free, \"$5\" used\"}'; "
            + docker_check
            + "if [ -d .git ]; then "
            "printf 'project=ok\\n'; "
            + git_status_check
            + origin_check
            + current_ref_state
            + ref_check
            + "else printf 'project=not-git\\n'; printf 'git=not-git\\n'; printf 'origin=missing\\n'; "
            "printf 'synced_ref=missing\\n'; printf 'remote_ref=missing\\n'; printf 'ref=missing\\n'; fi"
        )
        return transport.ssh_command(remote, script)

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
