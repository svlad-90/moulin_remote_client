"""Host-owned runtime for plugin actions, capabilities, and custom views."""

from __future__ import annotations

import curses
import queue
import shlex
import subprocess
import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable

from components.board.api import workflow as board_workflow_api
from components.board_types.api import base as board_type_base_api
from components.board_types.api import registry as board_type_registry_api
from components.product_types.api import registry as product_type_registry_api
from components.product_types.api import base as product_type_base_api
from components.config.api import accessors as config_accessors
from components.config.api import profiles as config_profiles
from components.jobs.api import jobs as job_api
from components.moulin.api import manifest as moulin_manifest_api
from components.plugins.src.discovery import PluginDiscovery
from components.plugins.src.model import (
    BoardProfile,
    BuildHostProfile,
    PluginDefinition,
    PluginTextEdit,
    ProjectProfile,
    UiEvent,
    plugin_config,
    plugin_enabled,
    set_plugin_enabled,
)
from components.remote.api import transport as remote_transport
from components.remote.api import build as remote_build
from components.remote.api import project as remote_project
from components.ui.api import dialogs as ui_dialog_api
from components.ui.api import input as ui_input_api
from components.ui.api.menu import MenuItem


class PluginCommands:
    def __init__(self, app: Any) -> None:
        self._app = app
        self._build_service = remote_build.remote_build_command_service()
        self._project_service = remote_project.remote_project_maintenance_service()

    def run(self, title: str, commands: list[list[str]]) -> int:
        return self._app.command_workflow_service().run_commands(self._app, title, commands)

    def run_build_host(self, title: str, commands: list[str]) -> int:
        remote = config_accessors.remote_spec_for_config(self._app.config)
        if not remote:
            raise RuntimeError("build host is not configured")
        return self.run(title, [remote_transport.ssh_command(remote, command) for command in commands])

    def run_host(self, remote: str, title: str, commands: list[str]) -> int:
        if not remote:
            raise RuntimeError("SSH host is not configured")
        return self.run(title, [remote_transport.ssh_command(remote, command) for command in commands])

    def capture_host(self, remote: str, command: str, *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        if not remote:
            raise RuntimeError("SSH host is not configured")
        try:
            return subprocess.run(
                remote_transport.ssh_command(remote, command),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"SSH command timed out after {timeout} seconds") from exc

    def capture_host_stream(
        self,
        remote: str,
        command: str,
        on_stdout_line: Callable[[str], None],
        *,
        timeout: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        if not remote:
            raise RuntimeError("SSH host is not configured")
        argv = remote_transport.ssh_command(remote, command)
        process = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        events: queue.SimpleQueue[tuple[str, str | None]] = queue.SimpleQueue()

        def read_stream(name: str, stream: Any) -> None:
            try:
                for line in stream:
                    events.put((name, line))
            finally:
                events.put((name, None))

        readers = (
            threading.Thread(target=read_stream, args=("stdout", process.stdout), daemon=True),
            threading.Thread(target=read_stream, args=("stderr", process.stderr), daemon=True),
        )
        for reader in readers:
            reader.start()

        stdout: list[str] = []
        stderr: list[str] = []
        finished_streams = 0
        deadline = time.monotonic() + timeout
        try:
            while finished_streams < len(readers):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(argv, timeout)
                try:
                    name, line = events.get(timeout=min(0.1, remaining))
                except queue.Empty:
                    continue
                if line is None:
                    finished_streams += 1
                elif name == "stdout":
                    stdout.append(line)
                    on_stdout_line(line.rstrip("\r\n"))
                else:
                    stderr.append(line)
            returncode = process.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            raise RuntimeError(f"SSH command timed out after {timeout} seconds") from exc
        except Exception:
            process.kill()
            process.wait()
            raise
        finally:
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
            for reader in readers:
                reader.join(timeout=0.1)
        return subprocess.CompletedProcess(argv, returncode, "".join(stdout), "".join(stderr))

    def run_build_host_profile(self, host_id: str, title: str, commands: list[str]) -> int:
        host = self._build_host(host_id)
        return self.run_host(host.remote, title, commands)

    def host_command(self, remote: str, command: str) -> list[str]:
        if not remote:
            raise RuntimeError("SSH host is not configured")
        return remote_transport.ssh_command(remote, command)

    def build_host_command(self, host_id: str, command: str) -> list[str]:
        return self.host_command(self._build_host(host_id).remote, command)

    def board_command(self, board_id: str, command: str) -> list[str]:
        return self.host_command(self._board(board_id).remote, command)

    def board_capabilities(self, board_id: str) -> frozenset[board_type_base_api.BoardCapability]:
        board = self._board(board_id)
        adapter = board_type_registry_api.board_type_registry().adapter_for_type(board.board_type)
        return adapter.capabilities(dict(board.values))

    def board_operation_plan(
        self,
        board_id: str,
        host_id: str,
        project_id: str,
        capability: board_type_base_api.BoardCapability,
        *,
        build_params: dict[str, str],
    ) -> board_type_base_api.BoardOperationPlan:
        config_profiles.normalize_board_host_profiles(self._app.config)
        config = deepcopy(self._app.config)
        board_host = config_profiles.board_host_for_board(config, board_id)
        config["active_board_host"] = str(board_host.get("id") or "")
        config["active_board"] = board_id
        config["active_remote"] = host_id
        config["active_project"] = project_id
        config_profiles.sync_active_board_host(config)
        config_profiles.sync_active_remote(config)
        config_profiles.sync_active_project(config)
        workflow = board_workflow_api.board_command_workflow_service(
            app_dir=self._app.dependencies.app_dir,
            default_moulin_manifest=self._app.dependencies.default_moulin_manifest,
            flash_bootloaders_tool=self._app.dependencies.flash_bootloaders_tool,
            xt_imager_tool=self._app.dependencies.xt_imager_tool,
            remote_read_project_file=self._app.dependencies.remote_read_project_file,
            manifest_cache=self._app.dependencies.manifest_cache,
        )
        plan = workflow.board_operation_plan(config, capability, build_params=build_params)
        if plan is None:
            raise ValueError(f"board type does not provide {capability.value}: {board_id}")
        return plan

    def product_capabilities(
        self,
        project_id: str,
        host_id: str = "",
        *,
        build_params: dict[str, str] | None = None,
    ) -> frozenset[product_type_base_api.ProductCapability]:
        project = self._project(project_id)
        adapter = product_type_registry_api.product_type_registry().adapter_for_type(project.product_type)
        return adapter.capabilities(self._effective_product_components(project, host_id, build_params))

    def product_domains(
        self,
        project_id: str,
        host_id: str = "",
        *,
        build_params: dict[str, str] | None = None,
    ) -> tuple[product_type_base_api.ProductDomain, ...]:
        project = self._project(project_id)
        adapter = product_type_registry_api.product_type_registry().adapter_for_type(project.product_type)
        return adapter.domains(self._effective_product_components(project, host_id, build_params))

    def product_target_candidates(
        self,
        project_id: str,
        host_id: str,
        *,
        build_params: dict[str, str] | None = None,
    ) -> tuple[str, ...]:
        project = self._project(project_id)
        self._build_host(host_id)
        dependencies = self._app.dependencies
        if not all(
            hasattr(dependencies, name)
            for name in ("app_dir", "default_moulin_manifest", "remote_read_project_file", "manifest_cache")
        ):
            return project.build_targets
        config = deepcopy(self._app.config)
        config["active_remote"] = host_id
        config["active_project"] = project.project_id
        config_profiles.sync_active_remote(config)
        config_profiles.sync_active_project(config)
        parameters = moulin_manifest_api.default_parameters_for_config(
            config,
            app_dir=dependencies.app_dir,
            remote_read_project_file=dependencies.remote_read_project_file,
            cache=dependencies.manifest_cache,
            default_moulin_manifest=dependencies.default_moulin_manifest,
        )
        parameters.update(project.parameters)
        parameters.update(build_params or {})
        candidates = moulin_manifest_api.target_candidates_for_config(
            config,
            app_dir=dependencies.app_dir,
            remote_read_project_file=dependencies.remote_read_project_file,
            cache=dependencies.manifest_cache,
            default_moulin_manifest=dependencies.default_moulin_manifest,
            build_params=parameters,
        )
        return tuple(
            str(candidate.get("target") or "")
            for candidate in candidates
            if str(candidate.get("target") or "")
        )

    def product_android_build_context(
        self,
        project_id: str,
        host_id: str,
        *,
        build_params: dict[str, str] | None = None,
    ) -> moulin_manifest_api.AndroidBuildContext:
        project = self._project(project_id)
        builders, parameters = self._effective_product_builders(project, host_id, build_params)
        return moulin_manifest_api.android_build_context_from_builders(builders, parameters)

    def product_adb_resolver(
        self,
        project_id: str,
        board_id: str,
    ) -> product_type_base_api.ProductTargetResolverPlan:
        project = self._project(project_id)
        board = self._board(board_id)
        adapter = product_type_registry_api.product_type_registry().adapter_for_type(project.product_type)
        plan = adapter.android_adb_resolver(board.values)
        if plan is None:
            raise ValueError(
                f"product type {adapter.type_id} cannot resolve ADB for {board_id}; "
                "configure the board serial console, set the DomD MAC address, or "
                "configure an ADB serial override in the CTS/VTS board profile"
            )
        return plan

    def _effective_product_components(
        self,
        project: ProjectProfile,
        host_id: str,
        build_params: dict[str, str] | None,
    ) -> tuple[product_type_base_api.ProductComponent, ...]:
        builders, _parameters = self._effective_product_builders(project, host_id, build_params)
        return tuple(
            product_type_base_api.ProductComponent(
                name=str(builder.get("name") or ""),
                builder_type=str(builder.get("builder_type") or ""),
            )
            for builder in builders
            if str(builder.get("name") or "") and str(builder.get("builder_type") or "")
        )

    def _effective_product_builders(
        self,
        project: ProjectProfile,
        host_id: str,
        build_params: dict[str, str] | None,
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        dependencies = self._app.dependencies
        if not host_id or not all(
            hasattr(dependencies, name)
            for name in ("app_dir", "default_moulin_manifest", "remote_read_project_file", "manifest_cache")
        ):
            return [], dict(project.parameters)
        config = deepcopy(self._app.config)
        config["active_remote"] = host_id
        config["active_project"] = project.project_id
        config_profiles.sync_active_remote(config)
        config_profiles.sync_active_project(config)
        parameters = moulin_manifest_api.default_parameters_for_config(
            config,
            app_dir=dependencies.app_dir,
            remote_read_project_file=dependencies.remote_read_project_file,
            cache=dependencies.manifest_cache,
            default_moulin_manifest=dependencies.default_moulin_manifest,
        )
        parameters.update(project.parameters)
        parameters.update(build_params or {})
        builders = moulin_manifest_api.component_builders_for_config(
            config,
            app_dir=dependencies.app_dir,
            remote_read_project_file=dependencies.remote_read_project_file,
            cache=dependencies.manifest_cache,
            default_moulin_manifest=dependencies.default_moulin_manifest,
            build_params=parameters,
        )
        return builders, parameters

    def prepare_product_command(self, host_id: str, project_id: str) -> list[str]:
        host = self._build_host(host_id)
        project = self._project(project_id)
        directory = config_accessors.remote_project_dir(dict(host.values), dict(project.values))
        return self._project_service.prepare_project_command(
            host.remote,
            directory,
            project.git_url or str(host.values.get("git_url") or ""),
            project.git_ref,
        )

    def checkout_product_command(self, host_id: str, project_id: str) -> list[str] | None:
        host = self._build_host(host_id)
        project = self._project(project_id)
        if not project.git_ref:
            return None
        directory = config_accessors.remote_project_dir(dict(host.values), dict(project.values))
        return self._project_service.checkout_git_ref_command(host.remote, directory, project.git_ref)

    def ensure_product_graph_command(self, host_id: str, project_id: str) -> list[str]:
        host = self._build_host(host_id)
        project = self._project(project_id)
        directory = config_accessors.remote_project_dir(dict(host.values), dict(project.values))
        params = " ".join(
            f"--{shlex.quote(name)} {shlex.quote(value)}" for name, value in sorted(project.parameters.items())
        )
        inner = f"moulin {shlex.quote(project.moulin_manifest)}" + (f" {params}" if params else "")
        docker = self._build_service.product_docker_command(directory, project.docker_image, inner)
        command = f"cd {shlex.quote(directory)} && if [ ! -f build.ninja ]; then {docker}; fi"
        return self.host_command(host.remote, command)

    def product_build_command(self, host_id: str, project_id: str, targets: list[str]) -> list[str]:
        host = self._build_host(host_id)
        project = self._project(project_id)
        directory = config_accessors.remote_project_dir(dict(host.values), dict(project.values))
        return self._build_service.build_command(host.remote, directory, project.docker_image, shlex.join(targets))

    def product_inner_command(self, host_id: str, project_id: str, inner_command: str) -> list[str]:
        host = self._build_host(host_id)
        project = self._project(project_id)
        directory = config_accessors.remote_project_dir(dict(host.values), dict(project.values))
        command = self._build_service.product_docker_command(directory, project.docker_image, inner_command)
        return self.host_command(host.remote, f"cd {shlex.quote(directory)} && {command}")

    def run_board(self, board_id: str, title: str, commands: list[str]) -> int:
        board = self._board(board_id)
        if not board.remote:
            raise RuntimeError(f"board host is not configured: {board_id}")
        return self.run(title, [remote_transport.ssh_command(board.remote, command) for command in commands])

    def run_boards(self, title: str, commands_by_board: dict[str, list[str]]) -> int:
        commands: list[list[str]] = []
        for board_id, remote_commands in commands_by_board.items():
            board = self._board(board_id)
            if not board.remote:
                raise RuntimeError(f"board host is not configured: {board_id}")
            commands.extend(remote_transport.ssh_command(board.remote, command) for command in remote_commands)
        return self.run(title, commands)

    def _board(self, board_id: str) -> BoardProfile:
        for board in board_profiles(self._app.config):
            if board_id in {board.board_id, str(board.values.get("name") or "")}:
                return board
        raise KeyError(f"unknown board host: {board_id}")

    def _build_host(self, host_id: str) -> BuildHostProfile:
        for host in build_host_profiles(self._app.config):
            if host_id in {host.host_id, str(host.values.get("name") or "")}:
                return host
        raise KeyError(f"unknown build host: {host_id}")

    def _project(self, project_id: str) -> ProjectProfile:
        for project in project_profiles(self._app.config):
            if project_id in {project.project_id, str(project.values.get("name") or "")}:
                return project
        raise KeyError(f"unknown project: {project_id}")


class PluginDialogs:
    def __init__(self, app: Any) -> None:
        self._app = app

    def confirm(self, title: str, message: str, *, warning: str = "Confirm plugin action.") -> bool:
        return self._app.dialog_workflow_controller().run_confirm_dialog(
            self._app,
            ui_dialog_api.ConfirmContent(
                title=title,
                warning=warning,
                subject=title,
                details=message,
                footer="Enter/y: run | n/q/Esc: cancel",
            ),
        )

    def message(self, title: str, lines: list[str]) -> None:
        self._app.show_message(title, lines)

    def prompt(self, label: str, current: str = "") -> str:
        return self._app.prompt(label, current)

    @property
    def prompt_cancelled(self) -> bool:
        return bool(getattr(self._app, "prompt_cancelled", False))


class PluginContext:
    """Capabilities available to plugin handlers and views."""

    def __init__(self, app: Any, definition: PluginDefinition, runtime: "PluginRuntime") -> None:
        self._app = app
        self._definition = definition
        self._runtime = runtime
        self.commands = PluginCommands(app)
        self.dialogs = PluginDialogs(app)

    @property
    def plugin_id(self) -> str:
        return self._definition.plugin_id

    @property
    def config(self) -> dict[str, Any]:
        values = plugin_config(self._app.config, self.plugin_id)
        for setting in self._definition.settings:
            values.setdefault(setting.key, setting.default)
        return values

    @property
    def config_store(self) -> Any:
        """Shared store used by built-in components and plugins alike."""

        return self._app.config_store

    @property
    def runtime_state(self) -> dict[str, Any]:
        return self._runtime.state_for_plugin(self.plugin_id)

    @property
    def boards(self) -> tuple[BoardProfile, ...]:
        return board_profiles(self._app.config)

    @property
    def build_hosts(self) -> tuple[BuildHostProfile, ...]:
        return build_host_profiles(self._app.config)

    @property
    def projects(self) -> tuple[ProjectProfile, ...]:
        return project_profiles(self._app.config)

    @property
    def active_board_id(self) -> str:
        return str(self._app.config.get("active_board") or "")

    @property
    def active_project_id(self) -> str:
        return str(self._app.config.get("active_project") or "")

    @property
    def active_build_host_id(self) -> str:
        return str(self._app.config.get("active_remote") or "")

    def open_view(self, view_id: str) -> None:
        self._runtime.open_view(self._app, self._definition, view_id)

    def close_view(self) -> None:
        self._runtime.close_view(self._app)

    def request_redraw(self) -> None:
        self._app.main_full_redraw = True

    def inline_edit(self, event: UiEvent, value: str, cursor: int) -> PluginTextEdit:
        edit = ui_input_api.inline_edit_key_action(value, cursor, event.code, event.text)
        if edit.action == "noop":
            edit = ui_input_api.inline_edit_key_action(
                value,
                cursor,
                event.code,
                self._app.read_queued_text(event.code),
            )
        return PluginTextEdit(edit.value, edit.cursor, edit.action)


class PluginCanvas:
    """Coordinate-safe drawing surface owned and refreshed by the host."""

    def __init__(self, app: Any, *, top: int, left: int, height: int, width: int) -> None:
        self._app = app
        self._top = top
        self._left = left
        self.height = max(0, height)
        self.width = max(0, width)
        self._cursor: tuple[int, int] | None = None

    def text(self, row: int, column: int, text: str, *, style: str = "normal") -> None:
        if not self._inside(row, column):
            return
        available = max(0, self.width - column)
        self._app.add(self._top + row, self._left + column, text[:available], self._attr(style))

    def box(self, row: int, column: int, height: int, width: int, title: str = "", *, style: str = "normal") -> None:
        if not self._inside(row, column):
            return
        clipped_height = min(height, self.height - row)
        clipped_width = min(width, self.width - column)
        if clipped_height >= 2 and clipped_width >= 2:
            self._app.draw_box(
                self._top + row,
                self._left + column,
                clipped_height,
                clipped_width,
                title,
                self._attr(style),
            )

    def wrapped_text(self, row: int, column: int, width: int, text: str, *, style: str = "normal", max_lines: int = 4) -> int:
        if not self._inside(row, column):
            return 0
        return self._app.draw_wrapped(
            self._top + row,
            self._left + column,
            min(width, self.width - column),
            text,
            self._attr(style),
            max_lines,
        )

    def scrollbar(self, row: int, column: int, height: int, total: int, visible: int, scroll: int) -> None:
        if self._inside(row, column):
            self._app.draw_scrollbar(
                self._top + row,
                self._left + column,
                min(height, self.height - row),
                total,
                visible,
                scroll,
            )

    def cursor(self, row: int, column: int) -> None:
        if not self._inside(row, column):
            return
        self._cursor = (self._top + row, self._left + column)

    def _apply_cursor(self) -> None:
        if self._cursor is None:
            self._app.set_cursor(False)
            return
        self._app.set_cursor(True)
        try:
            self._app.screen.move(*self._cursor)
        except curses.error:
            pass

    def _inside(self, row: int, column: int) -> bool:
        return 0 <= row < self.height and 0 <= column < self.width

    def _attr(self, style: str) -> int:
        if style == "title":
            return curses.A_BOLD
        if style == "accent":
            return self._app.accent_attr()
        if style == "warning":
            return self._app.warn_attr()
        if style == "error":
            return self._app.error_attr()
        if style == "ok":
            return self._app.ok_attr()
        if style == "selected":
            return self._app.selected_attr()
        if style == "selected-active":
            return self._app.selected_active_attr()
        if style == "active":
            return self._app.active_row_attr()
        if style == "editing":
            return self._app.editing_attr()
        return 0


class PluginLogPanel:
    """Host-styled scrolling log panel for custom plugin views."""

    def __init__(self) -> None:
        self.expanded = False
        self.follow = True
        self.scroll = 0
        self._visible = 1
        self._inner_width = 1

    def reset(self) -> None:
        self.follow = True
        self.scroll = 0

    def handle_event(self, event: UiEvent, lines: list[str]) -> bool:
        if ui_input_api.key_code_matches(event.code, "f"):
            self.expanded = not self.expanded
            self.reset()
            return True
        if not self.expanded:
            return False
        if event.code == 27:
            self.expanded = False
            self.reset()
            return True
        delta = 0
        if event.code == curses.KEY_UP or ui_input_api.key_code_matches(event.code, "k"):
            delta = -1
        elif event.code == curses.KEY_DOWN or ui_input_api.key_code_matches(event.code, "j"):
            delta = 1
        elif event.code == curses.KEY_PPAGE:
            delta = -10
        elif event.code == curses.KEY_NPAGE:
            delta = 10
        if not delta:
            return False
        plan = job_api.log_scroll_plan(
            {"output": lines},
            self._visible,
            follow=self.follow,
            scroll=self.scroll,
            delta=delta,
            width=self._inner_width,
        )
        self.scroll = int(plan.get("log_scroll", self.scroll))
        self.follow = bool(plan.get("log_follow", self.follow))
        return True

    def draw(
        self,
        ui: PluginCanvas,
        *,
        top: int,
        left: int,
        height: int,
        width: int,
        owner: str,
        lines: list[str],
        running: bool,
    ) -> None:
        ui.box(top, left, height, width, "Logs")
        inner = max(1, width - 4)
        row = top + 2
        state = "RUNNING" if running else "DONE"
        ui.text(row, left + 2, f"{owner} [{state}]", style="active" if running else "accent")
        row += 2
        visible = max(1, top + height - 2 - row)
        self._visible = visible
        self._inner_width = inner
        job = {"output": lines}
        output = job_api.wrapped_job_output_lines(job, inner)
        if not output:
            ui.text(row, left + 2, "No log for this board yet.", style="warning")
            self.scroll = 0
            self.follow = True
            return
        self.scroll, self.follow = job_api.clamp_log_scroll(
            job,
            visible,
            follow=self.follow,
            scroll=self.scroll,
            width=inner,
        )
        shown = output[self.scroll : self.scroll + visible]
        first = min(len(output), self.scroll + 1)
        last = min(len(output), self.scroll + len(shown))
        follow = " follow" if self.follow else ""
        counter = f"lines {first}-{last}/{len(output)}{follow}"
        ui.text(top, max(left + 2, left + width - len(counter) - 2), counter, style="accent")
        for line in shown:
            ui.text(row, left + 2, line)
            row += 1


@dataclass
class ActivePluginView:
    definition: PluginDefinition
    view_id: str
    label: str
    view: Any


class PluginRuntime:
    """Bridge plugin declarations to the host menu and event loop."""

    def __init__(self, plugins_dir: Path) -> None:
        self.discovery = PluginDiscovery(plugins_dir)
        self._plugin_state: dict[str, dict[str, Any]] = {}

    def state_for_plugin(self, plugin_id: str) -> dict[str, Any]:
        return self._plugin_state.setdefault(plugin_id, {})

    def definitions(self, *, refresh: bool = False) -> list[PluginDefinition]:
        return self.discovery.discover(refresh=refresh)

    def migrate_loaded_config(self, config: dict[str, Any]) -> bool:
        """Run configured plugin migrations once, before store initialization."""

        configured = config.get("plugins", {})
        if not isinstance(configured, dict):
            return False
        changed = False
        for definition in self.definitions():
            if definition.error or definition.plugin_id not in configured:
                continue
            try:
                migrate = getattr(self.discovery.load_module(definition), "migrate_config", None)
                if callable(migrate):
                    changed = bool(migrate(config)) or changed
            except Exception as exc:
                definition.error = str(exc)
                raise RuntimeError(
                    f"plugin {definition.plugin_id} configuration migration failed: {exc}"
                ) from exc
        return changed

    def build_items(self, app: Any) -> list[MenuItem]:
        items: list[MenuItem] = []
        for definition in self.definitions():
            if definition.error or not plugin_enabled(app.config, definition.plugin_id):
                continue
            try:
                self.discovery.load_module(definition)
                items.extend(self._definition_items(app, definition))
            except Exception as exc:
                definition.error = str(exc)
        return items

    def config_contributors(self, app: Any) -> tuple[Any, ...]:
        """Return generic config contributors for every plugin with persisted state."""

        result = []
        configured = app.config.get("plugins", {})
        for definition in self.definitions():
            if definition.error or not isinstance(configured, dict) or definition.plugin_id not in configured:
                continue
            try:
                factory = getattr(self.discovery.load_module(definition), "config_contributor", None)
                if callable(factory):
                    result.append(factory())
            except Exception as exc:
                definition.error = str(exc)
        return tuple(result)

    def set_enabled(self, app: Any, definition: PluginDefinition, enabled: bool) -> None:
        if enabled and not definition.error:
            try:
                self.discovery.load_module(definition)
            except Exception as exc:
                definition.error = str(exc)
                enabled = False
        app.config_store.update_config(
            lambda config: set_plugin_enabled(config, definition.plugin_id, enabled)
        )
        rebuild_store = getattr(app, "rebuild_config_store", None)
        if callable(rebuild_store):
            rebuild_store()
        if definition.error:
            app.status = f"Plugin {definition.name}: {definition.error}"
        else:
            app.status = f"Plugin {definition.name}: {'enabled' if enabled else 'disabled'}"
        tab_prefix = f"plugin:{definition.plugin_id}:"
        if plugin_enabled(app.config, definition.plugin_id) and definition.actions:
            app.active_menu_tab = f"{tab_prefix}{definition.actions[0].tab_id}"
        elif str(getattr(app, "active_menu_tab", "")).startswith(tab_prefix):
            app.active_menu_tab = ""
        app.menu_dirty = True
        app.main_full_redraw = True

    def open_view(self, app: Any, definition: PluginDefinition, view_id: str) -> None:
        view_definition = definition.views.get(view_id)
        if view_definition is None:
            raise KeyError(f"plugin {definition.plugin_id} has no view {view_id}")
        factory = self.discovery.resolve(definition, view_definition.factory)
        context = PluginContext(app, definition, self)
        view = factory(context)
        app.active_plugin_view = ActivePluginView(definition, view_id, view_definition.label, view)
        callback = getattr(view, "on_enter", None)
        if callable(callback):
            callback(context)
        app.main_full_redraw = True

    def close_view(self, app: Any) -> None:
        active = getattr(app, "active_plugin_view", None)
        if active is None:
            return
        context = PluginContext(app, active.definition, self)
        callback = getattr(active.view, "on_leave", None)
        try:
            if callable(callback):
                callback(context)
        except Exception as exc:
            app.status = f"Plugin {active.definition.name} view cleanup failed: {exc}"
        finally:
            app.active_plugin_view = None
        app.main_full_redraw = True
        app.render_cache.clear()

    def draw_view(self, app: Any) -> bool:
        active = getattr(app, "active_plugin_view", None)
        if active is None:
            return False
        app.setup_colors()
        height, width = app.screen.getmaxyx()
        app.screen.erase()
        app.add(0, 0, f"{active.definition.name} | {active.label}"[:width], curses.A_BOLD)
        canvas = PluginCanvas(app, top=1, left=0, height=max(0, height - 3), width=width)
        context = PluginContext(app, active.definition, self)
        try:
            app.set_cursor(False)
            active.view.render(canvas, context)
        except Exception as exc:
            self._abort_view(app, active, exc)
            return False
        footer = "q/Esc: back"
        app.add(height - 2, 0, footer[:width].ljust(width), app.accent_attr())
        app.add(height - 1, 0, app.status[:width].ljust(width), curses.A_REVERSE)
        canvas._apply_cursor()
        app.screen.refresh()
        app.main_full_redraw = False
        return True

    def handle_view_key(self, app: Any, code: int) -> bool:
        active = getattr(app, "active_plugin_view", None)
        if active is None:
            return False
        context = PluginContext(app, active.definition, self)
        callback = getattr(active.view, "handle_event", None)
        try:
            result = callback(UiEvent(code, ui_input_api.key_code_to_text(code)), context) if callable(callback) else None
        except Exception as exc:
            self._abort_view(app, active, exc)
            return True
        if result == "close" or (result is None and (code == 27 or ui_input_api.key_code_matches(code, "q"))):
            self.close_view(app)
        else:
            app.main_full_redraw = True
        return True

    def poll_view(self, app: Any) -> None:
        active = getattr(app, "active_plugin_view", None)
        if active is None:
            return
        callback = getattr(active.view, "on_tick", None)
        try:
            if callable(callback):
                callback(PluginContext(app, active.definition, self))
        except Exception as exc:
            self._abort_view(app, active, exc)

    def _abort_view(self, app: Any, active: ActivePluginView, exc: Exception) -> None:
        app.active_plugin_view = None
        app.status = f"Plugin {active.definition.name} view failed: {exc}"
        app.main_full_redraw = True
        app.render_cache.clear()

    def _definition_items(self, app: Any, definition: PluginDefinition) -> list[MenuItem]:
        result: list[MenuItem] = []
        for action in definition.actions:
            result.append(
                MenuItem(
                    action.label,
                    f"{action.tab_id} / {action.group}",
                    action.description,
                    self._preview(definition, action.preview, action.description),
                    self._handler(definition, action.handler, action.view),
                    confirm=action.confirm,
                    job_slot=action.job_slot,
                    tab_id=f"plugin:{definition.plugin_id}:{action.tab_id}",
                    tab_label=action.tab_label,
                    availability=self._availability(definition, action.availability),
                )
            )
        return result

    def _availability(self, definition: PluginDefinition, reference: str) -> Any:
        if not reference:
            return None

        def availability(app: Any) -> tuple[bool, str]:
            callback = self.discovery.resolve(definition, reference)
            result = callback(PluginContext(app, definition, self))
            if isinstance(result, tuple) and len(result) == 2:
                return bool(result[0]), str(result[1])
            return bool(result), "plugin action is unavailable"

        return availability

    def _preview(self, definition: PluginDefinition, reference: str, fallback: str) -> Any:
        if not reference:
            return lambda _app: fallback

        def preview(app: Any) -> str:
            callback = self.discovery.resolve(definition, reference)
            return str(callback(PluginContext(app, definition, self)))

        return preview

    def _handler(self, definition: PluginDefinition, reference: str, view_id: str) -> Any:
        def handler(app: Any) -> None:
            if view_id:
                self.open_view(app, definition, view_id)
                return
            callback = self.discovery.resolve(definition, reference)
            callback(PluginContext(app, definition, self))

        return handler


def board_profiles(config: dict[str, Any]) -> tuple[BoardProfile, ...]:
    config_profiles.normalize_board_host_profiles(config)
    result: list[BoardProfile] = []
    for host in config.get("board_hosts", []):
        if not isinstance(host, dict):
            continue
        for raw in host.get("boards", []):
            if not isinstance(raw, dict):
                continue
            board_id = str(raw.get("id") or "")
            if not board_id:
                continue
            result.append(
                BoardProfile(
                    board_id=board_id,
                    label=str(raw.get("label") or raw.get("name") or board_id),
                    user=str(host.get("user") or ""),
                    host=str(host.get("host") or ""),
                    board_type=str(raw.get("type") or ""),
                    values=MappingProxyType(config_profiles.board_target(config, board_id)),
                )
            )
    return tuple(result)


def build_host_profiles(config: dict[str, Any]) -> tuple[BuildHostProfile, ...]:
    config_profiles.normalize_remote_profiles(config)
    result: list[BuildHostProfile] = []
    for raw in config.get("remotes", []):
        if not isinstance(raw, dict):
            continue
        host_id = config_profiles.ensure_profile_id(raw)
        if not host_id:
            continue
        result.append(
            BuildHostProfile(
                host_id=host_id,
                label=str(raw.get("label") or raw.get("name") or host_id),
                user=str(raw.get("user") or ""),
                host=str(raw.get("host") or ""),
                projects_dir=config_accessors.build_host_projects_dir(raw),
                values=MappingProxyType(deepcopy(raw)),
            )
        )
    return tuple(result)


def project_profiles(config: dict[str, Any]) -> tuple[ProjectProfile, ...]:
    result: list[ProjectProfile] = []
    for raw in config.get("projects", []):
        if not isinstance(raw, dict):
            continue
        project_id = config_profiles.ensure_profile_id(raw)
        if not project_id:
            continue
        targets = raw.get("targets", [])
        if isinstance(targets, str):
            targets = targets.split()
        parameters = raw.get("parameters", {})
        if not isinstance(parameters, dict):
            parameters = {}
        result.append(
            ProjectProfile(
                project_id=project_id,
                label=str(raw.get("label") or raw.get("name") or project_id),
                product_type=str(raw.get("product_type") or "gen5_xen_android"),
                project_dir=str(raw.get("project_dir") or ""),
                moulin_manifest=str(raw.get("moulin_manifest") or ""),
                docker_image=str(raw.get("docker_image") or ""),
                build_targets=tuple(str(target) for target in targets if str(target)),
                git_url=config_accessors.project_git_url(raw, {}),
                git_ref=config_accessors.project_git_ref(raw),
                parameters=MappingProxyType({str(key): str(value) for key, value in parameters.items()}),
                values=MappingProxyType(deepcopy(raw)),
            )
        )
    return tuple(result)


def plugin_runtime(plugins_dir: Path) -> PluginRuntime:
    return PluginRuntime(plugins_dir)
