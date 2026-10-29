"""Main menu command item service."""

from __future__ import annotations

import curses
import json
from pathlib import Path
from pathlib import PurePosixPath
import shlex
from typing import Any, Callable

from components.board.api import workflow as board_workflow_api
from components.board_types.api import base as board_type_base_api
from components.build_runtime.api import runtime as config_runtime_api
from components.config.api import accessors as config_accessors
from components.moulin.api import manifest as moulin_manifest_api
from components.project.api import selection as project_selection_api
from components.remote.api import transport
from components.remote.api import workflow as remote_workflow_api
from components.sync.api import workflow as sync_workflow_api
from components.ui.api import dialogs as ui_dialog_api
from components.ui.api import file_picker as ui_file_picker_api
from components.ui.api import input as ui_input_api
from components.ui.api import menu as ui_menu_api
from components.ui.api import progress as ui_progress_api
from components.ui.api import session as ui_session_api
from components.ui.api import text as ui_text_api
from components.ui.api.menu import MenuItem


CLEAN_COMPONENT_BACK = object()
LOCAL_ARTIFACT_BACK = object()


class MainMenuCommandItemsService:
    """Build command-oriented main menu items and handlers."""

    def __init__(
        self,
        *,
        remote_command_workflow: remote_workflow_api.RemoteCommandWorkflowService,
        sync_command_workflow: sync_workflow_api.SyncCommandWorkflowService,
        board_command_workflow: board_workflow_api.BoardCommandWorkflowService,
        app_dir: Path,
        default_moulin_manifest: str,
        remote_read_project_file: Callable[[dict[str, Any], str], str],
        manifest_cache: dict[tuple[str, ...], dict[str, Any]],
    ) -> None:
        self.remote_command_workflow = remote_command_workflow
        self.sync_command_workflow = sync_command_workflow
        self.board_command_workflow = board_command_workflow
        self.app_dir = app_dir
        self.default_moulin_manifest = default_moulin_manifest
        self.remote_read_project_file = remote_read_project_file
        self.manifest_cache = manifest_cache
        self.mapping_selection_service = project_selection_api.project_mapping_selection_service()
        self.component_clean_action_index = 0
        self.component_clean_dry_run = True
        self.moulin_target_clean_index = 0
        self.artifact_source_index = 0

    def build_items(self, app: Any) -> list[MenuItem]:
        items = [
            MenuItem(
                "Open build host shell",
                "build / build host",
                "Open SSH shell in the remote product directory on the build host; exit returns to this TUI.",
                lambda app: shlex.join(self.remote_command_workflow.interactive_shell_command(app.config)),
                lambda app: app.terminal_session_controller().open_remote_shell(app),
                requires_remote=True,
                requires_project=True,
                allow_during_job=True,
            ),
            MenuItem(
                "Open build host git repo",
                "build / build host",
                "Open SSH shell in a Git repository that contains an active mapped path on the build host.",
                lambda app: "Discover Git repositories from active mappings in one build-host SSH session.",
                lambda app: self.open_build_host_git_repo(app),
                requires_remote=True,
                requires_project=True,
                allow_during_job=True,
            ),
            *self.docker_menu_items(app),
            MenuItem(
                "Select build targets",
                "build / configuration",
                "Choose the Ninja targets used by product and incremental builds.",
                lambda app: f"Current build targets: {app.build_targets or '<not set>'}",
                lambda app: app.config_workflow_controller().select_build_targets(app),
                requires_project=True,
            ),
            MenuItem(
                "Copy mapped files to build host",
                "build / commands",
                "Push selected local mapped files to the configured build host.",
                lambda app: ui_menu_api.command_preview(
                    self.sync_command_workflow.mapped_files_push_sequence(app.config)
                ),
                lambda app: self.run_sync_mapping_push(app),
                requires_remote=True,
                requires_project=True,
            ),
            MenuItem(
                "Clean-up BitBake server",
                "build / commands",
                "Kill build containers for the configured Docker image and remove BitBake server locks.",
                lambda app: shlex.join(
                    self.remote_command_workflow.bitbake_cleanup_command(
                        app.config,
                        docker_image=app.docker_image,
                        components=self.incremental_components(app),
                    )
                ),
                lambda app: self.run_bitbake_cleanup(app),
                requires_remote=True,
                requires_project=True,
            ),
            MenuItem(
                "Regenerate Moulin/Ninja",
                "build / commands",
                "Run Moulin on the remote target and refresh Ninja files.",
                lambda app: shlex.join(
                    self.remote_command_workflow.moulin_regen_command(
                        app.config,
                        docker_image=app.docker_image,
                        build_params=app.build_params,
                    )
                ),
                lambda app: self.run_build_command(
                    app,
                    "Regenerate Moulin/Ninja",
                    self.remote_command_workflow.moulin_regen_command(
                        app.config,
                        docker_image=app.docker_image,
                        build_params=app.build_params,
                    ),
                ),
                confirm=True,
                requires_remote=True,
                requires_project=True,
            ),
            MenuItem(
                "Run product build",
                "build / commands",
                "Run configured Ninja targets on the remote target.",
                lambda app: shlex.join(
                    self.remote_command_workflow.product_build_command(
                        app.config,
                        docker_image=app.docker_image,
                        targets=app.build_targets,
                    )
                ),
                lambda app: self.run_product_build(app),
                confirm=True,
                requires_remote=True,
                requires_project=True,
            ),
            MenuItem(
                "Incremental rebuild",
                "build / commands",
                "Rebuild selected Moulin components and optionally invalidate selected final image targets first.",
                lambda app: ui_menu_api.command_preview(
                    self.incremental_product_build_commands(app, clean_yocto=False)
                ),
                lambda app: self.run_incremental_build(app, clean_yocto=False),
                requires_remote=True,
                requires_project=True,
            ),
            MenuItem(
                "Clean incremental build",
                "build / commands",
                "Clean impacted Yocto recipes only, regenerate Moulin/Ninja, then rebuild selected components.",
                lambda app: ui_menu_api.command_preview(
                    self.incremental_product_build_commands(app, clean_yocto=True)
                ),
                lambda app: self.run_incremental_build(app, clean_yocto=True),
                requires_remote=True,
                requires_project=True,
            ),
            MenuItem(
                "Reset incremental build state",
                "build / commands",
                "Rebuild the mapped-file baseline and queue current local workspace changes for the next incremental build.",
                lambda app: shlex.join(self.reset_incremental_build_state_command(app)),
                lambda app: self.run_reset_incremental_build_state(app),
                confirm=True,
                requires_project=True,
            ),
            MenuItem(
                "Clean Moulin components",
                "build / commands",
                "Choose a cleanup mode, then select Moulin components to clean.",
                lambda _app: "Opens cleanup mode selection: component directory, Moulin artifacts, build output, or Yocto component clean.",
                lambda app: self.run_component_clean_menu(app),
                requires_remote=True,
                requires_project=True,
            ),
            MenuItem(
                "Clean project folder",
                "build / commands",
                "Delete the configured project directory on the build host.",
                lambda app: shlex.join(self.remote_command_workflow.clean_project_folder_command(app.config)),
                lambda app: app.command_workflow_service().run_commands(
                    app,
                    "Clean project folder",
                    [self.remote_command_workflow.clean_project_folder_command(app.config)],
                ),
                confirm=True,
                requires_remote=True,
            ),
            MenuItem(
                "Stop running command",
                "build / commands",
                "Gracefully stop the currently running build or sync command, then force-kill it if it does not exit.",
                lambda app: app.stop_running_preview("build"),
                lambda app: app.stop_running_command("build"),
                confirm=True,
                allow_during_job=True,
            ),
            MenuItem(
                "Open build host shell",
                "flashing / hosts",
                "Open SSH shell in the remote product workspace on the build host; exit returns to this TUI.",
                lambda app: shlex.join(self.remote_command_workflow.interactive_shell_command(app.config)),
                lambda app: app.terminal_session_controller().open_remote_shell(app),
                requires_remote=True,
                requires_project=True,
                allow_during_job=True,
            ),
            MenuItem(
                "Connect board host",
                "sessions / board host",
                "Check SSH access to the configured board host or mark it disconnected.",
                lambda app: ui_session_api.board_host_connection_preview(
                    app.board_connection_state,
                    self.board_command_workflow.connect_command(app.config),
                ),
                lambda app: app.connection_workflow_service().toggle_board_host(app),
                allow_during_job=True,
            ),
            MenuItem(
                "Open board host shell",
                "sessions / board host",
                "Open SSH shell on the board host; exit returns to this TUI.",
                lambda app: shlex.join(self.board_command_workflow.interactive_shell_command(app.config)),
                lambda app: app.terminal_session_controller().open_board_shell(app),
                allow_during_job=True,
            ),
        ]
        board_items = self.board_action_items(app)
        board_host_items = [item for item in board_items if item.group == "flashing / hosts"]
        board_other_items = [item for item in board_items if item.group != "flashing / hosts"]
        items.extend(board_host_items)
        items.append(self.configure_copied_artifacts_item())
        items.extend(board_other_items)
        items.extend([
            MenuItem(
                "Stop current board command",
                "flashing / commands",
                "Gracefully stop the currently running board command, then force-kill it if it does not exit.",
                lambda app: app.stop_running_preview("board"),
                lambda app: app.stop_running_command("board"),
                confirm=True,
                allow_during_job=True,
            ),
            MenuItem(
                "Stop current board command",
                "tftp/nfs / board control",
                "Gracefully stop the currently running board command, then force-kill it if it does not exit.",
                lambda app: app.stop_running_preview("board"),
                lambda app: app.stop_running_command("board"),
                confirm=True,
                allow_during_job=True,
            ),
            MenuItem(
                "Sync mapped files",
                "build / files mapping",
                "Pull or push the configured local/remote source mappings used for patch development.",
                lambda app: "Open the sync workflow for configured mappings.",
                lambda app: app.sync_screen(),
                requires_remote=True,
                requires_project=True,
            ),
            MenuItem(
                "Open mapped workspace",
                "build / files mapping",
                "Open a local shell in the mapped-file workspace after mappings have been pulled.",
                lambda app: shlex.join(
                    self.local_directory_shell_command(
                        config_accessors.local_project_dir_for_config(app.config, self.app_dir)
                    )
                ),
                lambda app: app.terminal_session_controller().open_local_directory_shell(
                    app,
                    "Open mapped workspace",
                    config_accessors.local_project_dir_for_config(app.config, self.app_dir),
                ),
                requires_project=True,
                allow_during_job=True,
            ),
            MenuItem(
                "Open remote TFTP root",
                "tftp/nfs / open remote roots",
                "Open a board-host shell in the configured TFTP project directory.",
                lambda app: shlex.join(
                    self.board_host_directory_shell_command(
                        app.config,
                        config_accessors.board_tftp_project_dir_for_config(app.config),
                    )
                ),
                lambda app: app.terminal_session_controller().open_board_host_directory_shell(
                    app,
                    "Open remote TFTP root",
                    config_accessors.board_tftp_project_dir_for_config(app.config),
                ),
                requires_project=True,
                allow_during_job=True,
            ),
            MenuItem(
                "Open remote NFS root",
                "tftp/nfs / open remote roots",
                "Open a board-host shell in the configured NFS project directory.",
                lambda app: shlex.join(
                    self.board_host_directory_shell_command(
                        app.config,
                        config_accessors.board_nfs_project_dir_for_config(app.config),
                    )
                ),
                lambda app: app.terminal_session_controller().open_board_host_directory_shell(
                    app,
                    "Open remote NFS root",
                    config_accessors.board_nfs_project_dir_for_config(app.config),
                ),
                requires_project=True,
                allow_during_job=True,
            ),
            MenuItem(
                "Open local TFTP workspace",
                "tftp/nfs / tftp/nfs workspace",
                "Open a local shell in the pulled TFTP workspace.",
                lambda app: shlex.join(
                    self.local_directory_shell_command(
                        config_accessors.local_board_network_dir(app.config, self.app_dir, "tftp")
                    )
                ),
                lambda app: app.terminal_session_controller().open_local_directory_shell(
                    app,
                    "Open local TFTP workspace",
                    config_accessors.local_board_network_dir(app.config, self.app_dir, "tftp"),
                ),
                requires_project=True,
                allow_during_job=True,
            ),
            MenuItem(
                "Open local NFS workspace",
                "tftp/nfs / tftp/nfs workspace",
                "Open a local shell in the pulled NFS workspace.",
                lambda app: shlex.join(
                    self.local_directory_shell_command(
                        config_accessors.local_board_network_dir(app.config, self.app_dir, "nfs")
                    )
                ),
                lambda app: app.terminal_session_controller().open_local_directory_shell(
                    app,
                    "Open local NFS workspace",
                    config_accessors.local_board_network_dir(app.config, self.app_dir, "nfs"),
                ),
                requires_project=True,
                allow_during_job=True,
            ),
            MenuItem(
                "Open local Dom0 initramfs workspace",
                "tftp/nfs / dom0 initramfs workspace",
                "Open a local shell in the unpacked Dom0 initramfs workspace.",
                lambda app: shlex.join(
                    self.local_directory_shell_command(
                        config_accessors.local_board_network_dir(app.config, self.app_dir, "dom0-initramfs") / "rootfs"
                    )
                ),
                lambda app: app.terminal_session_controller().open_local_directory_shell(
                    app,
                    "Open local Dom0 initramfs workspace",
                    config_accessors.local_board_network_dir(app.config, self.app_dir, "dom0-initramfs") / "rootfs",
                ),
                requires_project=True,
                allow_during_job=True,
            ),
        ])
        return self.order_items(items)

    def docker_menu_items(self, app: Any) -> list[MenuItem]:
        state = str(getattr(app, "preflight_values", {}).get("docker", "") or "unknown")
        if state == "ok":
            return [
                self.open_docker_shell_item(),
                self.rebuild_docker_item(),
            ]
        return [self.build_docker_item()]

    def build_docker_item(self) -> MenuItem:
        return MenuItem(
            "Build Docker image",
            "build / docker",
            "Build the configured Docker image on the build host.",
            lambda app: shlex.join(
                self.remote_command_workflow.docker_image_command(
                    app.config,
                    docker_image=app.docker_image,
                )
            ),
            lambda app: self.run_build_command(
                app,
                "Build Docker image",
                self.remote_command_workflow.docker_image_command(
                    app.config,
                    docker_image=app.docker_image,
                ),
            ),
            confirm=True,
            requires_remote=True,
            requires_project=True,
        )

    def rebuild_docker_item(self) -> MenuItem:
        return MenuItem(
            "Rebuild Docker image",
            "build / docker",
            "Rebuild the configured Docker image on the build host.",
            lambda app: shlex.join(
                self.remote_command_workflow.docker_image_command(
                    app.config,
                    docker_image=app.docker_image,
                )
            ),
            lambda app: self.run_build_command(
                app,
                "Rebuild Docker image",
                self.remote_command_workflow.docker_image_command(
                    app.config,
                    docker_image=app.docker_image,
                ),
            ),
            confirm=True,
            requires_remote=True,
            requires_project=True,
        )

    def open_docker_shell_item(self) -> MenuItem:
        return MenuItem(
            "Open Docker image shell",
            "build / docker",
            "Open an interactive shell inside the configured Docker image; exit stops the container and returns to this TUI.",
            lambda app: shlex.join(
                self.remote_command_workflow.docker_shell_command(
                    app.config,
                    docker_image=app.docker_image,
                )
            ),
            lambda app: app.terminal_session_controller().open_command_shell(
                app,
                "Open Docker image shell",
                [
                    f"build host: {config_accessors.remote_spec_for_config(app.config)}",
                    f"docker image: {app.docker_image or '<not set>'}",
                ],
                self.remote_command_workflow.docker_shell_command(
                    app.config,
                    docker_image=app.docker_image,
                ),
            ),
            requires_remote=True,
            requires_project=True,
            allow_during_job=True,
        )

    def order_items(self, items: list[MenuItem]) -> list[MenuItem]:
        tftp_group_order = {
            "deploy artifacts": 0,
            "tftp/nfs workspace": 1,
            "dom0 initramfs workspace": 2,
            "board setup": 3,
            "board control": 4,
            "open remote roots": 5,
        }
        tftp_items = [(index, item) for index, item in enumerate(items) if self.item_parent_group(item) == "tftp/nfs"]
        if not tftp_items:
            return items

        ordered_tftp_items = [
            item
            for _index, item in sorted(
                tftp_items,
                key=lambda pair: (
                    tftp_group_order.get(self.item_child_group(pair[1]), len(tftp_group_order)),
                    pair[0],
                ),
            )
        ]
        tftp_item_ids = {id(item) for _index, item in tftp_items}
        ordered_items: list[MenuItem] = []
        inserted_tftp_items = False
        for item in items:
            if id(item) in tftp_item_ids:
                if not inserted_tftp_items:
                    ordered_items.extend(ordered_tftp_items)
                    inserted_tftp_items = True
                continue
            ordered_items.append(item)
        return ordered_items

    def configure_copied_artifacts_item(self) -> MenuItem:
        return MenuItem(
            "Configure copied artifacts",
            "flashing / configuration",
            "Choose which build artifacts are copied to the board host artifacts directory.",
            lambda app: f"Current copied artifacts: {getattr(app, 'board_artifacts', '') or app.build_targets or '<not set>'}",
            lambda app: app.config_workflow_controller().select_board_artifacts(app),
            requires_project=True,
        )

    def item_parent_group(self, item: MenuItem) -> str:
        return item.group.split(" / ", 1)[0]

    def item_child_group(self, item: MenuItem) -> str:
        parts = item.group.split(" / ", 1)
        if len(parts) == 1:
            return ""
        return parts[1]

    def local_directory_shell_command(self, path: Path) -> list[str]:
        script = (
            f"dir={shlex.quote(str(path))}\n"
            "[ -d \"$dir\" ] || { echo \"directory not found: $dir\"; echo 'Pull or create the workspace first.'; exit 2; }\n"
            "cd \"$dir\" && exec bash -l\n"
        )
        return ["bash", "-lc", script]

    def board_host_directory_shell_command(self, config: dict[str, Any], path: str) -> list[str]:
        return transport.ssh_command(
            config_accessors.board_host_spec_for_config(config),
            f"cd {shlex.quote(path)} && exec bash -l",
            tty="-t",
        )

    def run_incremental_build(self, app: Any, *, clean_yocto: bool) -> Any:
        title = "Clean incremental build" if clean_yocto else "Incremental rebuild"
        app.reload_config_from_disk()
        components = self.incremental_components(app)
        scope = self.incremental_build_scope(app, components)
        selected_names = self.select_incremental_component_names(app, scope)
        if selected_names is None:
            app.status = f"{title} cancelled"
            return None
        if not selected_names:
            app.status = f"{title} cancelled: nothing selected"
            return None
        component_names = [name for name in selected_names if not name.startswith("moulin-target:")]
        moulin_targets = [name.removeprefix("moulin-target:") for name in selected_names if name.startswith("moulin-target:")]
        if clean_yocto and not self.confirm_incremental_build_clean(app, selected_names=component_names):
            app.status = f"{title} cancelled"
            return None
        if moulin_targets and not self.confirm_moulin_target_clean(app, moulin_targets):
            app.status = f"{title} cancelled"
            return None
        config_runtime_api.save_runtime_incremental_components(app.config, self.app_dir, selected_names)
        return app.command_workflow_service().run_commands(
            app,
            title,
            self.incremental_product_build_commands(
                app,
                selected_names=component_names,
                moulin_targets=moulin_targets,
                clean_yocto=clean_yocto,
            ),
        )

    def run_bitbake_cleanup(self, app: Any) -> int:
        app.reload_config_from_disk()
        components = self.incremental_components(app)
        if not self.confirm_bitbake_cleanup(app, components=components):
            app.status = "Clean-up BitBake server cancelled"
            return 0
        return app.command_workflow_service().run_build_command(
            app,
            "Clean-up BitBake server",
            self.remote_command_workflow.bitbake_cleanup_command(
                app.config,
                docker_image=app.docker_image,
                components=components,
            ),
            config=app.config,
            parameters=app.build_params,
            targets=app.build_targets,
            docker_image=app.docker_image,
            build_command_sequence=self.sync_command_workflow.build_command_sequence,
        )

    def confirm_bitbake_cleanup(self, app: Any, *, components: list[dict[str, Any]]) -> bool:
        build_dirs = [
            str(component.get("build_dir", "")).strip()
            for component in components
            if str(component.get("builder_type", "")) == "yocto" and str(component.get("build_dir", "")).strip()
        ]
        details = "BitBake build dirs: " + (", ".join(build_dirs) if build_dirs else "none detected")
        return app.dialog_workflow_controller().run_confirm_dialog(
            app,
            ui_dialog_api.ConfirmContent(
                title="Confirm",
                warning="This action can kill remote build containers and remove BitBake locks.",
                subject="Clean-up BitBake server",
                details=details,
                footer="Enter/y: clean | n/q/Esc: back",
            ),
            redraw_background=False,
        )

    def confirm_incremental_build_clean(self, app: Any, *, selected_names: list[str]) -> bool:
        components = {
            str(component.get("name", "")): component
            for component in self.incremental_components(app)
        }
        selected = [components[name] for name in selected_names if name in components]
        yocto_targets = [
            str(component.get("target", "")).strip()
            for component in selected
            if str(component.get("builder_type", "")) == "yocto" and str(component.get("target", "")).strip()
        ]
        if not yocto_targets:
            return True
        selected_components = ", ".join(selected_names)
        yocto_target_text = ", ".join(yocto_targets)
        return app.dialog_workflow_controller().run_confirm_dialog(
            app,
            ui_dialog_api.ConfirmContent(
                title="Confirm",
                warning="Clean incremental build will clean impacted Yocto recipes only before rebuilding.",
                subject="Clean impacted Yocto recipes",
                details=f"Selected components: {selected_components}. Yocto targets: {yocto_target_text}",
                footer="Enter/y: clean and build | n/q/Esc: back",
            ),
            redraw_background=False,
        )

    def mark_incremental_mapping_build_applied_command(
        self,
        app: Any,
        *,
        applied_files: list[str] | None = None,
    ) -> list[str]:
        config_json = json.dumps(app.config, sort_keys=True)
        mappings_json = json.dumps(self.push_enabled_active_mappings(app), sort_keys=True)
        files_json = json.dumps(applied_files, sort_keys=True) if applied_files is not None else "null"
        script = "\n".join(
            [
                "import json",
                "import sys",
                "from pathlib import Path",
                f"sys.path.insert(0, {str(self.app_dir)!r})",
                "from components.build_runtime.api import runtime",
                f"config = json.loads({config_json!r})",
                f"mappings = json.loads({mappings_json!r})",
                f"applied_files = json.loads({files_json!r})",
                f"runtime.mark_runtime_mapping_build_applied(config, Path({str(self.app_dir)!r}), mappings, applied_files)",
                "print('Incremental build: marked mapped-file changes as applied by build')",
            ]
        )
        return ["python3", "-c", script]

    def reset_incremental_build_state_command(self, app: Any) -> list[str]:
        config_json = json.dumps(app.config, sort_keys=True)
        mappings_json = json.dumps(self.push_enabled_active_mappings(app), sort_keys=True)
        script = "\n".join(
            [
                "import json",
                "import sys",
                "from pathlib import Path",
                f"sys.path.insert(0, {str(self.app_dir)!r})",
                "from components.build_runtime.api import runtime",
                f"config = json.loads({config_json!r})",
                f"mappings = json.loads({mappings_json!r})",
                f"runtime.reset_runtime_mapping_state(config, Path({str(self.app_dir)!r}), mappings)",
                "pending_mappings, pending_files = runtime.load_runtime_mapping_pending_changes(config, Path(%r))" % str(self.app_dir),
                "print('Reset incremental build state: rebuilt baseline and queued local workspace changes')",
                "print('pending mappings: ' + (', '.join(pending_mappings) if pending_mappings else 'none'))",
                "print('pending files: ' + str(len(pending_files)))",
            ]
        )
        return ["python3", "-c", script]

    def run_reset_incremental_build_state(self, app: Any) -> int:
        app.reload_config_from_disk()
        return app.command_workflow_service().run_commands(
            app,
            "Reset incremental build state",
            [self.reset_incremental_build_state_command(app)],
        )

    def run_product_build(self, app: Any) -> int:
        app.reload_config_from_disk()
        product_build = self.remote_command_workflow.product_build_command(
            app.config,
            docker_image=app.docker_image,
            targets=app.build_targets,
        )
        commands = self.sync_command_workflow.build_command_sequence(
            app.config,
            product_build,
            parameters=app.build_params,
            targets=app.build_targets,
            docker_image=app.docker_image,
        )
        commands.append(self.mark_incremental_mapping_build_applied_command(app))
        return app.command_workflow_service().run_commands(app, "Run product build", commands)

    def incremental_product_build_commands(
        self,
        app: Any,
        selected_names: list[str] | None = None,
        *,
        moulin_targets: list[str] | None = None,
        clean_yocto: bool = False,
    ) -> list[list[str]]:
        components = self.incremental_components(app)
        selected_name_set = set(selected_names or [])
        selected = [component for component in components if component["name"] in selected_name_set]
        if selected_names is None:
            selected = [component for component in components if component["supported"]]
        selected_moulin_targets = list(dict.fromkeys(moulin_targets or []))

        yocto_recipes = [
            str(component["target"])
            for component in selected
            if component["builder_type"] == "yocto" and str(component["target"]).strip()
        ]
        yocto_build_dirs = [
            build_dir
            for component in selected
            if component["builder_type"] == "yocto"
            for build_dir in [self.yocto_incremental_build_dir(component)]
            if build_dir
        ]
        invalidated_components = [
            component for component in selected if component["builder_type"] in {"bazel", "android"}
        ]
        bazel_config_targets = self.bazel_config_targets_for_components(selected)
        product_targets = list(dict.fromkeys([
            *(str(component["name"]) for component in selected),
            *selected_moulin_targets,
        ]))
        selected_product_targets = " ".join(product_targets)
        changed_files = self.changed_incremental_files(app)
        applied_files = self.applied_incremental_files(app, selected, changed_files)

        commands: list[list[str]] = []
        if clean_yocto and changed_files and yocto_recipes:
            for component in selected:
                if component["builder_type"] != "yocto" or not str(component["target"]).strip():
                    continue
                build_dir = self.yocto_incremental_build_dir(component)
                commands.append(
                    self.remote_command_workflow.yocto_impact_command(
                        app.config,
                        docker_image=app.docker_image,
                        targets=str(component["target"]),
                        action="clean",
                        image_recipes=[str(component["target"])],
                        build_dirs=[build_dir] if build_dir else [],
                        allow_empty=True,
                        changed_files=changed_files,
                    )
                )
        elif clean_yocto and yocto_recipes:
            commands.append(
                self.remote_command_workflow.yocto_impact_command(
                    app.config,
                    docker_image=app.docker_image,
                    targets=" ".join(yocto_recipes),
                    action="clean",
                    image_recipes=[],
                    build_dirs=yocto_build_dirs,
                    allow_empty=True,
                    changed_files=changed_files,
                )
            )
        commands.append(
            self.remote_command_workflow.moulin_regen_command(
                app.config,
                docker_image=app.docker_image,
                build_params=app.build_params,
            )
        )
        if selected_moulin_targets:
            commands.append(
                self.remote_command_workflow.target_output_clean_command(
                    app.config,
                    docker_image=app.docker_image,
                    targets=selected_moulin_targets,
                )
            )
        if bazel_config_targets:
            commands.append(
                self.remote_command_workflow.bazel_config_command(
                    app.config,
                    docker_image=app.docker_image,
                    targets=" ".join(bazel_config_targets),
                )
            )
        if invalidated_components:
            commands.append(
                self.remote_command_workflow.incremental_build_command(
                    app.config,
                    docker_image=app.docker_image,
                    targets=selected_product_targets,
                    invalidate_components=invalidated_components,
                )
            )
        else:
            commands.append(
                self.remote_command_workflow.product_build_command(
                    app.config,
                    docker_image=app.docker_image,
                    targets=selected_product_targets,
                )
            )
        commands.append(self.mark_incremental_mapping_build_applied_command(app, applied_files=applied_files))
        return commands

    def incremental_build_scope(
        self,
        app: Any,
        components: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        component_names = {str(component["name"]) for component in components}
        component_items = [
            {
                **component,
                "selection_kind": "component",
                "display_name": str(component["name"]),
                "default_selected": True,
            }
            for component in components
        ]
        target_items = [
            {
                "name": f"moulin-target:{target['target']}",
                "display_name": target["target"],
                "builder_type": "Moulin output",
                "supported": True,
                "selection_kind": "moulin_target",
                "default_selected": False,
                "description": target["desc"] or target["source"],
            }
            for target in self.cleanable_moulin_targets(app)
            if target["target"] not in component_names
        ]
        return [*component_items, *target_items]

    def run_component_clean_menu(self, app: Any) -> Any:
        while True:
            action = self.select_component_clean_action(app)
            if action is None:
                app.status = "Component cleanup cancelled"
                return None
            result = self.run_component_clean(
                app,
                mode=str(action["mode"]),
                dry_run=bool(action["dry_run"]),
            )
            if result is CLEAN_COMPONENT_BACK:
                continue
            return result

    def run_moulin_target_clean(self, app: Any) -> Any:
        app.reload_config_from_disk()
        targets = self.cleanable_moulin_targets(app)
        if not targets:
            app.status = "No Moulin targets are available to clean"
            return None
        selected_targets = self.select_moulin_clean_targets(app, targets)
        if selected_targets is None:
            app.status = "Moulin target cleanup cancelled"
            return None
        if not selected_targets:
            app.status = "Moulin target cleanup cancelled: no targets selected"
            return None
        if not self.confirm_moulin_target_clean(app, selected_targets):
            app.status = "Moulin target cleanup cancelled"
            return None
        return app.command_workflow_service().run_commands(
            app,
            "Clean Moulin targets",
            [
                self.remote_command_workflow.target_output_clean_command(
                    app.config,
                    docker_image=app.docker_image,
                    targets=selected_targets,
                )
            ],
        )

    def cleanable_moulin_targets(self, app: Any) -> list[dict[str, str]]:
        try:
            candidates = moulin_manifest_api.target_candidates_for_config(
                app.config,
                app_dir=self.app_dir,
                remote_read_project_file=self.remote_read_project_file,
                cache=self.manifest_cache,
                default_moulin_manifest=self.default_moulin_manifest,
                build_params=app.build_params,
            )
        except Exception as exc:
            app.status = f"Moulin target discovery failed: {exc}"
            candidates = []
        by_target = {
            str(candidate.get("target", "")).strip(): {
                "target": str(candidate.get("target", "")).strip(),
                "source": str(candidate.get("source", "manifest")),
                "desc": str(candidate.get("desc", "")),
            }
            for candidate in candidates
            if self.safe_relative_path(str(candidate.get("target", "")))
        }
        for target in shlex.split(app.build_targets):
            if not self.safe_relative_path(target):
                continue
            by_target.setdefault(
                target,
                {"target": target, "source": "project selection", "desc": "Configured build target"},
            )
        return [by_target[target] for target in sorted(by_target)]

    def select_moulin_clean_targets(
        self,
        app: Any,
        targets: list[dict[str, str]],
    ) -> list[str] | None:
        selected: set[str] = set()
        index = ui_menu_api.clamp_index(self.moulin_target_clean_index, len(targets))
        app.screen.timeout(-1)
        try:
            while True:
                app.screen.erase()
                height, width = app.screen.getmaxyx()
                if height < 14 or width < 72:
                    app.add(0, 0, "Terminal is too small. Need at least 72x14.", app.warn_attr())
                    app.screen.refresh()
                    ch = app.read_key()
                    if ui_input_api.key_code_matches(ch, "q") or ch == 27:
                        return None
                    continue

                index = ui_menu_api.clamp_index(index, len(targets))
                self.moulin_target_clean_index = index
                app.draw_box(0, 0, height - 2, width, "Clean Moulin Targets")
                app.add(1, 2, "Select final target outputs to invalidate; dependencies are kept.", app.accent_attr())
                selected_text = "Selected: " + (" ".join(sorted(selected)) if selected else "none")
                app.add(2, 2, ui_text_api.fit_text(selected_text, width - 4))
                top = 4
                visible = max(1, height - top - 5)
                start = min(max(0, index - visible + 1), max(0, len(targets) - visible))
                for row_offset, target_index in enumerate(range(start, min(len(targets), start + visible))):
                    target = targets[target_index]
                    name = target["target"]
                    mark = "[x]" if name in selected else "[ ]"
                    label = f"{mark} {name}"
                    attr = app.selected_attr() if target_index == index else 0
                    app.add(top + row_offset, 2, ui_text_api.fit_text(label, width - 4).ljust(width - 4), attr)

                current = targets[index]
                details = current["source"]
                if current["desc"]:
                    details += f": {current['desc']}"
                app.add(height - 4, 2, ui_text_api.fit_text(details, width - 4))
                footer = "Up/Down: select | Space: toggle | Enter: clean | q/Esc: back"
                app.add(height - 2, 0, footer[:width], app.accent_attr())
                app.add(height - 1, 0, app.status[:width].ljust(width), curses.A_REVERSE)
                app.screen.refresh()
                ch = app.read_key()
                if ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k"):
                    index = ui_menu_api.move_index(index, len(targets), -1)
                elif ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j"):
                    index = ui_menu_api.move_index(index, len(targets), 1)
                elif ch == ord(" "):
                    name = targets[index]["target"]
                    if name in selected:
                        selected.remove(name)
                        app.status = f"Disabled {name}"
                    else:
                        selected.add(name)
                        app.status = f"Enabled {name}"
                elif ch in (10, 13):
                    return [target["target"] for target in targets if target["target"] in selected]
                elif ui_input_api.key_code_matches(ch, "q") or ch == 27:
                    return None
        finally:
            self.moulin_target_clean_index = index
            app.screen.timeout(250)

    def confirm_moulin_target_clean(self, app: Any, targets: list[str]) -> bool:
        return app.dialog_workflow_controller().run_confirm_dialog(
            app,
            ui_dialog_api.ConfirmContent(
                title="Confirm",
                warning="Stop other builds first. Only final outputs are removed; dependencies are kept.",
                subject=f"Clean Moulin targets: {', '.join(targets)}",
                details="For a compressed image, both .img.gz and its adjacent .img output are invalidated.",
                footer="Enter/y: clean | n/q/Esc: back",
            ),
            redraw_background=False,
        )

    def select_component_clean_action(self, app: Any) -> dict[str, object] | None:
        actions: list[dict[str, object]] = [
            {
                "label": "Component directory",
                "mode": "directory",
                "description": "Delete the manifest build-dir directory for selected components.",
            },
            {
                "label": "Moulin artifacts",
                "mode": "artifacts",
                "description": "Delete manifest-declared artifact outputs for selected components.",
            },
            {
                "label": "Build output",
                "mode": "build_output",
                "description": "Delete build outputs while keeping fetched sources and configuration.",
            },
            {
                "label": "Yocto component clean",
                "mode": "yocto_component_clean",
                "description": "Run BitBake clean for each selected Yocto component build target.",
            },
            {
                "label": "Yocto component sstate",
                "mode": "yocto_component_sstate",
                "description": "Run BitBake cleansstate for each selected Yocto component build target.",
            },
            {
                "label": "Clean bitbake cache",
                "mode": "bitbake_cache",
                "description": "Clean local sstate and outputs for selected Yocto components and their dependencies.",
            },
        ]
        index = self.component_clean_action_index
        dry_run = self.component_clean_dry_run
        app.screen.timeout(-1)
        try:
            while True:
                app.screen.erase()
                height, width = app.screen.getmaxyx()
                if height < 12 or width < 72:
                    app.add(0, 0, "Terminal is too small. Need at least 72x12.", app.warn_attr())
                    app.screen.refresh()
                    ch = app.read_key()
                    if ui_input_api.key_code_matches(ch, "q") or ch == 27:
                        return None
                    continue

                index = ui_menu_api.clamp_index(index, len(actions))
                app.draw_box(0, 0, height - 2, width, "Clean Moulin Components")
                app.add(1, 2, "Select cleanup mode. Press Space to toggle dry-run.", app.accent_attr())
                dry_run_text = "Dry-run: on" if dry_run else "Dry-run: off"
                dry_run_attr = app.accent_attr() if dry_run else app.warn_attr()
                app.add(3, 2, dry_run_text, dry_run_attr)
                top = 5
                for offset, action in enumerate(actions):
                    row = top + offset
                    label = str(action["label"])
                    attr = app.selected_attr() if offset == index else 0
                    app.add(row, 2, ui_text_api.fit_text(label, width - 4).ljust(width - 4), attr)

                current = actions[index]
                app.add(height - 4, 2, ui_text_api.fit_text(str(current["description"]), width - 4))
                footer = "Up/Down: select | Space: toggle dry-run | Enter: continue | q/Esc: back"
                app.add(height - 2, 0, footer[:width], app.accent_attr())
                app.add(height - 1, 0, app.status[:width].ljust(width), curses.A_REVERSE)
                app.screen.refresh()
                ch = app.read_key()
                if ch == ord(" "):
                    dry_run = not dry_run
                    self.component_clean_dry_run = dry_run
                    app.status = "Dry-run enabled" if dry_run else "Dry-run disabled"
                elif ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k"):
                    index = ui_menu_api.move_index(index, len(actions), -1)
                    self.component_clean_action_index = index
                elif ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j"):
                    index = ui_menu_api.move_index(index, len(actions), 1)
                    self.component_clean_action_index = index
                elif ch in (10, 13):
                    self.component_clean_action_index = index
                    self.component_clean_dry_run = dry_run
                    return {**actions[index], "dry_run": dry_run}
                elif ui_input_api.key_code_matches(ch, "q") or ch == 27:
                    self.component_clean_action_index = index
                    self.component_clean_dry_run = dry_run
                    return None
        finally:
            app.screen.timeout(250)

    def run_component_clean(self, app: Any, *, mode: str, dry_run: bool) -> Any:
        app.reload_config_from_disk()
        components = self.cleanable_components(app, mode=mode)
        while True:
            selected_names = self.select_incremental_component_names(
                app,
                components,
                title="Clean Moulin Components",
                prompt=f"Select Moulin components to clean ({mode}), then press Enter.",
                supported_description=f"Cleanup mode {mode} is supported for {{builder_type}}.",
                unsupported_description=f"Cleanup mode {mode} is not supported for {{builder_type}}.",
                use_stored_selection=False,
                use_auto_selection=False,
            )
            if selected_names is None:
                app.status = "Back to cleanup mode selection"
                return CLEAN_COMPONENT_BACK
            if not selected_names:
                app.status = "Back to cleanup mode selection: no components selected"
                return CLEAN_COMPONENT_BACK
            if not self.confirm_component_clean(app, selected_names=selected_names, mode=mode, dry_run=dry_run):
                app.status = "Back to component selection"
                continue
            label = "Dry-run clean components" if dry_run else f"Clean components ({mode})"
            result = app.command_workflow_service().run_commands(
                app,
                label,
                self.component_clean_commands(app, selected_names=selected_names, mode=mode, dry_run=dry_run),
            )
            return result

    def confirm_component_clean(
        self,
        app: Any,
        *,
        selected_names: list[str],
        mode: str,
        dry_run: bool,
    ) -> bool:
        if dry_run:
            return True
        components = ", ".join(selected_names)
        return app.dialog_workflow_controller().run_confirm_dialog(
            app,
            ui_dialog_api.ConfirmContent(
                title="Confirm",
                warning=(
                    "Stop other builds first. Shared sstate may also be used by other domains."
                    if mode == "bitbake_cache" else "This action can change remote build state."
                ),
                subject=f"Clean Moulin components: {components}",
                details=(
                    f"Mode: {mode}. "
                    "The cleanup command will run only for the selected Moulin components."
                ),
                footer="Enter/y: clean | n/q/Esc: back",
            ),
            redraw_background=False,
        )

    def component_clean_commands(
        self,
        app: Any,
        *,
        selected_names: list[str] | None = None,
        mode: str,
        dry_run: bool,
    ) -> list[list[str]]:
        components = self.cleanable_components(app, mode=mode)
        selected_name_set = set(selected_names or [])
        selected = [component for component in components if component["name"] in selected_name_set]
        if not selected:
            selected = [component for component in components if component["supported"]]
        return [
            self.remote_command_workflow.component_clean_command(
                app.config,
                docker_image=app.docker_image,
                components=selected,
                mode=mode,
                dry_run=dry_run,
            )
        ]

    def cleanable_components(self, app: Any, *, mode: str) -> list[dict[str, Any]]:
        components = self.manifest_components(app)
        existing_dirs = self.existing_component_directory_names(app, components) if mode == "directory" else None
        if existing_dirs is not None:
            components = [
                component
                for component in components
                if str(component.get("name", "")) in existing_dirs
            ]
        for component in components:
            builder_type = str(component.get("builder_type", ""))
            target = str(component.get("target", ""))
            build_dir = str(component.get("build_dir", "")).strip()
            work_dir = str(component.get("work_dir", "")).strip()
            has_artifacts = bool(component.get("target_images")) or bool(target)
            component["supported"] = (
                mode == "artifacts" and has_artifacts
            ) or (
                mode == "directory" and bool(build_dir)
            ) or (
                mode == "build_output" and (
                    builder_type == "android" and bool(build_dir)
                    or builder_type == "yocto" and bool(target)
                )
            ) or (
                mode in {"yocto_component_clean", "yocto_component_sstate", "bitbake_cache", "all"} and builder_type == "yocto"
            )
        return components

    def existing_component_directory_names(self, app: Any, components: list[dict[str, Any]]) -> set[str] | None:
        capture = self.remote_capture_command(app)
        if capture is None:
            return None
        paths = [
            (str(component.get("name", "")), path)
            for component in components
            for path in [self.component_directory_path(component)]
            if component.get("name") and path
        ]
        if not paths:
            return set()
        checks = "; ".join(
            f"if [ -d {shlex.quote(path)} ]; then printf '%s\\n' {shlex.quote(name)}; fi"
            for name, path in paths
        )
        script = f"cd {shlex.quote(config_accessors.remote_project_dir_for_config(app.config))} && {checks}"
        try:
            output = capture(transport.ssh_command(config_accessors.remote_spec_for_config(app.config), script))
        except Exception as exc:
            app.status = f"Directory probe failed: {exc}"
            return None
        return {line.strip() for line in output.splitlines() if line.strip()}

    @staticmethod
    def remote_capture_command(app: Any) -> Callable[[list[str]], str] | None:
        direct = getattr(app, "remote_capture_command", None)
        if callable(direct):
            return direct
        services = getattr(app, "services", None)
        process_execution = getattr(services, "process_execution", None)
        capture = getattr(process_execution, "capture_command", None)
        if not callable(capture):
            return None
        return lambda argv: capture(argv, echo=False, timeout=15)

    @classmethod
    def component_directory_path(cls, component: dict[str, Any]) -> str:
        build_dir = cls.safe_relative_path(str(component.get("build_dir", "")))
        if not build_dir:
            return ""
        if component.get("builder_type") != "yocto":
            return build_dir
        work_dir = cls.safe_relative_path(str(component.get("work_dir", "")))
        if work_dir:
            return str(PurePosixPath(build_dir or "yocto") / work_dir)
        build_path = PurePosixPath(build_dir)
        if build_path.name.startswith("build-"):
            return build_dir
        name = cls.safe_relative_path(str(component.get("name", "")))
        return str(build_path / f"build-{name}") if name else ""

    @staticmethod
    def safe_relative_path(raw: str) -> str:
        text = raw.strip()
        if not text or text.startswith("/") or text.startswith("~"):
            return ""
        path = PurePosixPath(text)
        if any(part in {"", ".", ".."} for part in path.parts):
            return ""
        return str(path)

    def manifest_components(self, app: Any) -> list[dict[str, Any]]:
        return moulin_manifest_api.component_builders_for_config(
            app.config,
            app_dir=self.app_dir,
            remote_read_project_file=self.remote_read_project_file,
            cache=self.manifest_cache,
            default_moulin_manifest=self.default_moulin_manifest,
            build_params=getattr(app, "build_params", None),
            include_disabled=True,
        )

    @staticmethod
    def clamp_supported_component_index(components: list[dict[str, Any]], index: int) -> int:
        if not components:
            return 0
        index = ui_menu_api.clamp_index(index, len(components))
        supported = [offset for offset, component in enumerate(components) if component["supported"]]
        if not supported or index in supported:
            return index
        return next((offset for offset in supported if offset > index), supported[0])

    @staticmethod
    def move_supported_component_index(components: list[dict[str, Any]], index: int, delta: int) -> int:
        if not components:
            return 0
        supported = [offset for offset, component in enumerate(components) if component["supported"]]
        if not supported:
            return ui_menu_api.move_index(index, len(components), delta)
        current = MainMenuCommandItemsService.clamp_supported_component_index(components, index)
        position = supported.index(current)
        return supported[(position + delta) % len(supported)]

    def bazel_config_targets_for_components(self, selected_components: list[dict[str, Any]]) -> list[str]:
        bazel_targets = [
            self.bazel_config_target_for_component(component)
            for component in selected_components
            if component["builder_type"] == "bazel"
        ]
        return [target for target in bazel_targets if target]

    @staticmethod
    def bazel_config_target_for_component(component: dict[str, Any]) -> str:
        target = str(component.get("target", "")).strip()
        if not target.startswith("//"):
            return ""
        if target.endswith("/.config"):
            return target
        if target.endswith("_dist"):
            target = target[: -len("_dist")]
        return f"{target}/.config"

    @classmethod
    def yocto_incremental_build_dir(cls, component: dict[str, Any]) -> str:
        build_dir = cls.safe_relative_path(str(component.get("build_dir", ""))) or "yocto"
        work_dir = cls.safe_relative_path(str(component.get("work_dir", "")))
        if work_dir:
            return str(PurePosixPath(build_dir) / work_dir)
        build_path = PurePosixPath(build_dir)
        if build_path.name.startswith("build-"):
            return str(build_path)
        name = cls.safe_relative_path(str(component.get("name", "")))
        return str(build_path / f"build-{name}") if name else ""

    def incremental_components(self, app: Any) -> list[dict[str, Any]]:
        components = moulin_manifest_api.component_builders_for_config(
            app.config,
            app_dir=self.app_dir,
            remote_read_project_file=self.remote_read_project_file,
            cache=self.manifest_cache,
            default_moulin_manifest=self.default_moulin_manifest,
            build_params=app.build_params,
        )
        supported_types = {"yocto", "bazel", "android", "custom_script"}
        return [
            {
                **component,
                "supported": str(component.get("builder_type", "")) in supported_types,
            }
            for component in components
        ]

    def active_mappings(self, app: Any) -> list[dict[str, Any]]:
        names = self.mapping_selection_service.read_mapping_selection_for_config(
            app.config,
            self.sync_command_workflow.mapping_selection_path(app.config),
            required=False,
        )
        if not names:
            return []
        try:
            return self.mapping_selection_service.select_mappings_for_config(app.config, names)
        except SystemExit:
            return []

    def active_incremental_mappings(self, app: Any) -> list[dict[str, Any]]:
        return self.active_mappings(app)

    def open_build_host_git_repo(self, app: Any) -> None:
        repos = self.discover_build_host_git_repos(app)
        if not repos:
            app.status = "No Git repositories found for active mappings"
            return
        selected = self.select_build_host_git_repo(app, repos)
        if selected is None:
            app.status = "Open build host git repo cancelled"
            return
        app.terminal_session_controller().open_build_host_directory_shell(
            app,
            "Open build host git repo",
            selected["root"],
        )

    def discover_build_host_git_repos(self, app: Any) -> list[dict[str, object]]:
        capture = self.remote_capture_command(app)
        if capture is None:
            app.status = "Git repo discovery unavailable: no capture command"
            return []
        command = self.build_host_git_repo_discovery_command(
            config_accessors.remote_project_dir_for_config(app.config),
            self.active_mappings(app),
        )
        try:
            output = capture(transport.ssh_command(config_accessors.remote_spec_for_config(app.config), command))
        except Exception as exc:
            app.status = f"Git repo discovery failed: {exc}"
            return []
        repos: list[dict[str, object]] = []
        seen: set[str] = set()
        for raw in output.splitlines():
            line = raw.strip()
            if "\t" in line:
                status, root = line.split("\t", 1)
                dirty = status == "dirty"
            else:
                root = line
                dirty = False
            if root and root not in seen:
                seen.add(root)
                repos.append({"root": root, "dirty": dirty})
        return repos

    def build_host_git_repo_discovery_command(self, project_dir: str, mappings: list[dict[str, Any]]) -> str:
        mapping_lines = self.build_host_git_repo_mapping_lines(mappings)
        script = f"""set -u
project_dir={shlex.quote(project_dir)}
[ -d "$project_dir" ] || exit 0
{{
    while IFS=$'\\t' read -r kind rel; do
        [ -n "$rel" ] || continue
        if [ "$rel" = "." ]; then
            candidate="$project_dir"
        else
            candidate="$project_dir/$rel"
        fi
        if [ "$kind" = "file" ]; then
            candidate="${{candidate%/*}}"
        fi
        while [ "$candidate" != "$project_dir" ] && [ ! -e "$candidate" ]; do
            next="${{candidate%/*}}"
            [ "$next" = "$candidate" ] && break
            candidate="$next"
        done
        [ -f "$candidate" ] && candidate="${{candidate%/*}}"
        git -C "$candidate" rev-parse --show-toplevel 2>/dev/null || true
    done <<'MRC_MAPPINGS'
{mapping_lines}
MRC_MAPPINGS
}} | awk '!seen[$0]++' | while IFS= read -r root; do
    [ -n "$root" ] || continue
    if command -v timeout >/dev/null 2>&1; then
        status_output="$(timeout 3s git -C "$root" status --porcelain --untracked-files=no 2>/dev/null || true)"
    else
        status_output="$(git -C "$root" status --porcelain --untracked-files=no 2>/dev/null || true)"
    fi
    if [ -n "$status_output" ]; then
        printf 'dirty\\t%s\\n' "$root"
    else
        printf 'clean\\t%s\\n' "$root"
    fi
done
"""
        return "bash -lc " + shlex.quote(script)

    def build_host_git_repo_mapping_lines(self, mappings: list[dict[str, Any]]) -> str:
        entries = mappings or [{"kind": "directory", "remote": "."}]
        lines = []
        for mapping in entries:
            kind = str(mapping.get("kind", "directory")).strip()
            if kind not in {"directory", "file"}:
                kind = "directory"
            remote = str(mapping.get("remote", "")).strip().strip("/")
            if not remote:
                remote = "."
            remote = remote.replace("\n", "").replace("\t", " ")
            lines.append(f"{kind}\t{remote}")
        return "\n".join(lines)

    def select_build_host_git_repo(self, app: Any, repos: list[dict[str, object]]) -> dict[str, object] | None:
        index = 0
        app.screen.timeout(-1)
        try:
            while True:
                app.screen.erase()
                height, width = app.screen.getmaxyx()
                if height < 10 or width < 72:
                    app.add(0, 0, "Terminal is too small. Need at least 72x10.", app.warn_attr())
                    app.screen.refresh()
                    ch = app.read_key()
                    if ui_input_api.key_code_matches(ch, "q") or ch == 27:
                        return None
                    continue

                index = ui_menu_api.clamp_index(index, len(repos))
                app.draw_box(0, 0, height - 2, width, "Build Host Git Repositories")
                app.add(1, 2, "Select repository to open on the build host.", app.accent_attr())
                visible_rows = max(1, height - 6)
                start = max(0, min(index - visible_rows + 1, len(repos) - visible_rows))
                for visible, repo in enumerate(repos[start : start + visible_rows]):
                    row = 3 + visible
                    item_index = start + visible
                    root = str(repo["root"])
                    dirty = bool(repo.get("dirty"))
                    marker = " *" if dirty else "  "
                    label = f"{item_index + 1}.{marker} {root}"
                    if item_index == index:
                        selected_dirty_attr = getattr(app, "selected_warn_attr", app.selected_attr)
                        attr = selected_dirty_attr() if dirty else app.selected_attr()
                    else:
                        attr = app.warn_attr() if dirty else 0
                    app.add(row, 2, ui_text_api.fit_text(label, width - 4).ljust(width - 4), attr)
                footer = "* changed | Up/Down: select | Enter: open shell | q/Esc: back"
                app.add(height - 2, 0, footer[:width], app.accent_attr())
                app.add(height - 1, 0, app.status[:width].ljust(width), curses.A_REVERSE)
                app.screen.refresh()
                ch = app.read_key()
                if ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k"):
                    index = ui_menu_api.move_index(index, len(repos), -1)
                elif ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j") or ch == ord("\t"):
                    index = ui_menu_api.move_index(index, len(repos), 1)
                elif ch in (curses.KEY_ENTER, 10, 13):
                    return repos[index]
                elif ui_input_api.key_code_matches(ch, "q") or ch == 27:
                    return None
        finally:
            app.screen.timeout(1000)

    def auto_incremental_component_names(
        self,
        components: list[dict[str, Any]],
        changed_mappings: list[dict[str, Any]],
    ) -> list[str]:
        supported = [component for component in components if component["supported"]]
        by_name = {str(component["name"]): component for component in supported}
        selected: set[str] = set()
        for mapping in changed_mappings:
            text = " ".join(str(mapping.get(key, "")) for key in ("name", "role", "local", "remote")).lower()
            if text.endswith(".yaml") or "prod-devel" in text or "manifest" in text:
                selected.update(by_name)
                continue
            for name in by_name:
                if name.lower() in text:
                    selected.add(name)
            if "dom0" in text:
                selected.update(name for name in by_name if name == "dom0")
            if "domd" in text:
                selected.update(name for name in by_name if name == "domd")
            if "domu" in text:
                selected.update(name for name in by_name if name == "domu")
            if "android_kernel" in text or "kernel" in text:
                selected.update(
                    name
                    for name, component in by_name.items()
                    if "kernel" in name.lower() or component["builder_type"] == "bazel"
                )
            if "android" in text and "kernel" not in text:
                selected.update(
                    name
                    for name, component in by_name.items()
                    if component["builder_type"] == "android"
                )
        if "boot_artifacts" in by_name and selected.intersection({"dom0", "domd"}):
            selected.add("boot_artifacts")
        return [str(component["name"]) for component in supported if str(component["name"]) in selected]

    def incremental_change_state(self, app: Any, components: list[dict[str, Any]]) -> dict[str, list[str]]:
        changed = self.changed_incremental_mappings(app)
        return {
            "mappings": [str(mapping["name"]) for mapping in changed],
            "components": self.auto_incremental_component_names(components, changed),
        }

    def changed_incremental_mappings(self, app: Any) -> list[dict[str, Any]]:
        mappings = self.push_enabled_active_mappings(app)
        changed_names = config_runtime_api.changed_runtime_mappings(app.config, self.app_dir, mappings) if mappings else []
        return [mapping for mapping in mappings if str(mapping.get("name", "")) in set(changed_names)]

    def changed_incremental_files(self, app: Any) -> list[str]:
        mappings = self.push_enabled_active_mappings(app)
        return config_runtime_api.changed_runtime_mapping_files(app.config, self.app_dir, mappings) if mappings else []

    def mapping_contains_file(self, mapping: dict[str, Any], path: str) -> bool:
        local = str(mapping.get("local", "")).strip().strip("/")
        if not local or local == ".":
            return True
        return path == local or path.startswith(local + "/")

    def applied_incremental_files(
        self,
        app: Any,
        selected_components: list[dict[str, Any]],
        changed_files: list[str],
    ) -> list[str]:
        selected_names = {str(component["name"]) for component in selected_components}
        if not selected_names:
            return []
        all_components = self.incremental_components(app)
        applied_mappings = [
            mapping
            for mapping in self.push_enabled_active_mappings(app)
            if selected_names.intersection(self.auto_incremental_component_names(all_components, [mapping]))
        ]
        return sorted(
            {
                path
                for path in changed_files
                if any(self.mapping_contains_file(mapping, path) for mapping in applied_mappings)
            }
        )

    def clear_incremental_mapping_changes_command(self, app: Any) -> list[str]:
        config_json = json.dumps(app.config, sort_keys=True)
        script = "\n".join(
            [
                "import json",
                "import sys",
                "from pathlib import Path",
                f"sys.path.insert(0, {str(self.app_dir)!r})",
                "from components.build_runtime.api import runtime",
                f"config = json.loads({config_json!r})",
                f"runtime.clear_runtime_mapping_pending_changes(config, Path({str(self.app_dir)!r}))",
                "print('Incremental build: cleared consumed mapped-file changes')",
            ]
        )
        return ["python3", "-c", script]

    def select_incremental_component_names(
        self,
        app: Any,
        components: list[dict[str, Any]],
        *,
        title: str = "Incremental Build",
        prompt: str = "Select components and optional Moulin outputs to rebuild, then press Enter.",
        supported_description: str = "Incremental rebuild is supported for {builder_type}.",
        unsupported_description: str = "Incremental rebuild is not supported for {builder_type} yet.",
        use_stored_selection: bool = True,
        use_auto_selection: bool = True,
    ) -> list[str] | None:
        supported = [component for component in components if component["supported"]]
        supported_names = {str(component["name"]) for component in supported}
        manifest_components = [
            component for component in components if component.get("selection_kind", "component") == "component"
        ]
        change_state = self.incremental_change_state(app, manifest_components)
        auto_names = (
            [name for name in change_state["components"] if name in supported_names]
            if use_auto_selection
            else []
        )
        stored_names = (
            config_runtime_api.load_runtime_incremental_components(app.config, self.app_dir)
            if use_stored_selection
            else []
        )
        stored_supported_names = [name for name in stored_names or [] if name in supported_names]
        fallback_names = {
            str(component["name"])
            for component in supported
            if component.get("default_selected", True)
        } if use_stored_selection or use_auto_selection else set()
        selected = set(stored_supported_names or auto_names or fallback_names)
        index = 0
        app.screen.timeout(-1)
        try:
            while True:
                app.screen.erase()
                height, width = app.screen.getmaxyx()
                if height < 18 or width < 80:
                    app.add(0, 0, "Terminal is too small. Need at least 80x18.", app.warn_attr())
                    app.screen.refresh()
                    ch = app.read_key()
                    if ui_input_api.key_code_matches(ch, "q") or ch == 27:
                        return None
                    continue

                index = self.clamp_supported_component_index(components, index)
                app.draw_box(0, 0, height - 2, width, title)
                app.add(1, 2, prompt, app.accent_attr())
                app.add(2, 2, ui_text_api.fit_text(f"Final targets: {app.build_targets}", width - 4))
                app.add(3, 2, ui_text_api.fit_text("Selected: " + " ".join(name for name in selected if name), width - 4))

                changed_text = "Changed for incremental build: " + (
                    ", ".join(change_state["mappings"]) if change_state["mappings"] else "none"
                )
                selected_text = "Auto-selected: " + (", ".join(auto_names) if auto_names else "none")
                app.add(4, 2, ui_text_api.fit_text(changed_text, width - 4))
                app.add(5, 2, ui_text_api.fit_text(selected_text, width - 4))
                top = 7
                visible = max(1, height - top - 6)
                if not components:
                    app.add(top, 2, "No Moulin components found in manifest.", app.warn_attr())
                for offset, component in enumerate(components[:visible]):
                    row = top + offset
                    enabled = bool(component["supported"])
                    name = str(component["name"])
                    display_name = str(component.get("display_name", name))
                    mark = "[x]" if name in selected else "[ ]"
                    if not enabled:
                        mark = "[-]"
                    label = f"{mark} {display_name} ({component['builder_type']})"
                    attr = app.disabled_attr() if not enabled else app.selected_attr() if offset == index else 0
                    app.add(row, 2, ui_text_api.fit_text(label, width - 4).ljust(width - 4), attr)

                if components:
                    current = components[index]
                    if current.get("selection_kind") == "moulin_target":
                        desc = "Invalidate this final output, then rebuild it: " + str(current.get("description", ""))
                    else:
                        desc = (
                            supported_description.format(builder_type=current["builder_type"])
                            if current["supported"]
                            else unsupported_description.format(builder_type=current["builder_type"])
                        )
                    app.add(height - 4, 2, ui_text_api.fit_text(desc, width - 4))
                footer = "Up/Down: select | Space: toggle supported | Enter: run | q/Esc: cancel"
                app.add(height - 2, 0, footer[:width], app.accent_attr())
                app.add(height - 1, 0, app.status[:width].ljust(width), curses.A_REVERSE)
                app.screen.refresh()
                ch = app.read_key()
                if (ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k")) and components:
                    index = self.move_supported_component_index(components, index, -1)
                elif (ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j")) and components:
                    index = self.move_supported_component_index(components, index, 1)
                elif ch == ord(" ") and components:
                    component = components[index]
                    if not component["supported"]:
                        app.status = f"{component['builder_type']} incremental build is not supported"
                        continue
                    name = str(component["name"])
                    if name in selected:
                        selected.remove(name)
                        app.status = f"Disabled {name}"
                    else:
                        selected.add(name)
                        app.status = f"Enabled {name}"
                elif ch in (10, 13):
                    return [str(component["name"]) for component in components if str(component["name"]) in selected and component["supported"]]
                elif ui_input_api.key_code_matches(ch, "q") or ch == 27:
                    return None
        finally:
            app.screen.timeout(250)

    def run_build_command(self, app: Any, title: str, command: list[str]) -> int:
        app.reload_config_from_disk()
        return app.command_workflow_service().run_build_command(
            app,
            title,
            command,
            config=app.config,
            parameters=app.build_params,
            targets=app.build_targets,
            docker_image=app.docker_image,
            build_command_sequence=self.sync_command_workflow.build_command_sequence,
        )

    def yocto_incremental_product_build_commands(self, app: Any) -> list[list[str]]:
        image_recipes = self.yocto_image_recipes(app)
        product_build = self.remote_command_workflow.product_build_command(
            app.config,
            docker_image=app.docker_image,
            targets=app.build_targets,
        )
        moulin_regen = self.remote_command_workflow.moulin_regen_command(
            app.config,
            docker_image=app.docker_image,
            build_params=app.build_params,
        )
        return [
            self.remote_command_workflow.yocto_impact_command(
                app.config,
                docker_image=app.docker_image,
                targets=app.build_targets,
                action="clean",
                image_recipes=image_recipes,
            ),
            moulin_regen,
            self.remote_command_workflow.yocto_impact_command(
                app.config,
                docker_image=app.docker_image,
                targets=app.build_targets,
                action="rebuild",
                image_recipes=image_recipes,
            ),
            *self.sync_command_workflow.build_command_sequence(
                app.config,
                product_build,
                parameters=app.build_params,
                targets=app.build_targets,
                docker_image=app.docker_image,
            ),
        ]

    def yocto_image_recipes(self, app: Any) -> list[str]:
        configured = config_accessors.yocto_image_recipes_for_config(app.config)
        if configured:
            return configured
        return moulin_manifest_api.yocto_image_recipes_for_config(
            app.config,
            app_dir=self.app_dir,
            remote_read_project_file=self.remote_read_project_file,
            cache=self.manifest_cache,
            default_moulin_manifest=self.default_moulin_manifest,
            build_params=app.build_params,
        )

    def run_sync_mapping_push(self, app: Any) -> int:
        app.reload_config_from_disk()
        mapping_names = self.push_enabled_active_mapping_names(app)
        if not mapping_names:
            app.status = "Copy mapped files cancelled: no push-enabled active mappings"
            return 0
        if not self.confirm_mapping_push(app, mapping_names=mapping_names):
            app.status = "Copy mapped files cancelled"
            return 0
        return app.command_workflow_service().run_commands(
            app,
            "Copy mapped files to build host",
            self.sync_command_workflow.mapped_files_push_sequence(app.config, names=mapping_names),
        )

    def confirm_mapping_push(
        self,
        app: Any,
        *,
        mapping_names: list[str],
    ) -> bool:
        return app.dialog_workflow_controller().run_confirm_dialog(
            app,
            ui_dialog_api.ConfirmContent(
                title="Confirm",
                warning="This action can change local or remote mapped files.",
                subject="Copy mapped files",
                details="Mappings: " + ", ".join(mapping_names),
                footer="Enter/y: copy | n/q/Esc: back",
            ),
            redraw_background=False,
        )

    def push_enabled_active_mapping_names(self, app: Any) -> list[str]:
        return [str(mapping["name"]) for mapping in self.push_enabled_active_mappings(app)]

    def push_enabled_active_mappings(self, app: Any) -> list[dict[str, Any]]:
        return [mapping for mapping in self.active_incremental_mappings(app) if mapping.get("push", True)]

    def copy_build_artifacts_commands(self, app: Any) -> list[list[str]]:
        return self.board_command_workflow.copy_build_artifacts_commands(
            app.config,
            artifact_targets=getattr(app, "board_artifacts", "") or app.build_targets,
            build_params=app.build_params,
        )

    def board_action_items(self, app: Any) -> list[MenuItem]:
        actions = self.board_command_workflow.board_actions(
            app.config,
            build_params=getattr(app, "build_params", {}),
            allow_remote_manifest=False,
        )
        items: list[MenuItem] = []
        ownership_state = str(getattr(app, "board_ownership_status", {}).get("state") or "unknown")
        for action in actions:
            if action.action_id == "ownership_acquire" and ownership_state != "free":
                continue
            if action.action_id == "ownership_release" and ownership_state != "owned":
                continue
            if action.local_artifact is not None:
                items.append(self.artifact_source_flash_item(action))
                continue
            items.append(MenuItem(
                action.label,
                self.board_action_group(action.action_id),
                action.description,
                lambda app, action_id=action.action_id: ui_menu_api.command_preview(
                    self.board_action_commands(app, action_id)
                ),
                lambda app, action_id=action.action_id, interactive=action.interactive, label=action.label: (
                    self.run_interactive_board_action(app, action_id, label)
                    if interactive
                    else self.run_board_action(app, action_id)
                ),
                confirm=action.confirm,
                requires_remote=action.requires_remote,
                requires_project=action.requires_project,
                allow_during_job=action.allow_during_job,
                availability=(
                    lambda app, action_id=action.action_id: self.ownership_action_availability(app, action_id)
                ) if action.action_id in {"ownership_acquire", "ownership_release"} else None,
            ))
        return items

    def ownership_action_availability(self, app: Any, action_id: str) -> tuple[bool, str]:
        status = getattr(app, "board_ownership_status", {})
        state = str(status.get("state") or "unknown")
        if action_id == "ownership_acquire":
            if state == "free":
                return True, ""
            if state == "owned":
                return False, "board is already acquired by you"
            if state == "busy":
                return False, str(status.get("text") or "board is acquired by another user")
            return False, str(status.get("text") or "ownership status is unknown")
        if action_id == "ownership_release":
            if state == "owned":
                return True, ""
            if state == "free":
                return False, "board is not acquired"
            if state == "busy":
                return False, str(status.get("text") or "board is acquired by another user")
            return False, str(status.get("text") or "ownership status is unknown")
        return True, ""

    def artifact_source_flash_item(self, action: Any) -> MenuItem:
        label = action.label.removesuffix(" from build host")
        return MenuItem(
            label,
            self.board_action_group(action.action_id),
            f"Select whether the target artifact comes from the build host or a local file. {action.description}",
            lambda _app, label=label: f"{label}: select Build host or Local file as the artifact source.",
            lambda app, action_id=action.action_id, label=label: self.run_artifact_source_flash(
                app, action_id, label
            ),
            confirm=False,
            requires_remote=action.requires_remote,
            requires_project=action.requires_project,
            allow_during_job=action.allow_during_job,
        )

    def run_artifact_source_flash(self, app: Any, action_id: str, label: str) -> Any:
        while True:
            source = self.select_artifact_source(app, title=label)
            if source is None:
                app.status = f"{label}: source selection cancelled"
                return None
            if source == "local_file":
                result = self.run_local_artifact_flash(app, action_id)
                if result is LOCAL_ARTIFACT_BACK:
                    continue
                return result
            action = next(
                action for action in self.board_command_workflow.board_actions(
                    app.config,
                    build_params=getattr(app, "build_params", {}),
                    allow_remote_manifest=False,
                )
                if action.action_id == action_id
            )
            if action.confirm and not app.dialog_workflow_controller().run_confirm_dialog(
                app,
                ui_dialog_api.action_confirm_content(action.label, action.description),
                redraw_background=False,
            ):
                app.status = f"Cancelled: {label}"
                return None
            result = self.run_board_action(app, action_id)
            if result is LOCAL_ARTIFACT_BACK:
                continue
            return result

    def select_artifact_source(self, app: Any, *, title: str) -> str | None:
        choices = [
            ("build_host", "Build host", "Use artifacts previously copied from the configured build host."),
            ("local_file", "Local file", "Browse the local filesystem and upload the selected artifact."),
        ]
        index = self.artifact_source_index
        app.screen.timeout(-1)
        try:
            while True:
                app.screen.erase()
                height, width = app.screen.getmaxyx()
                if height >= 14 and width >= 80:
                    board_label = config_accessors.board_host_label_for_config(app.config)
                    panel_top = 4
                    panel_height = height - panel_top - 2
                    left_width = max(32, min(width // 2, 48))
                    right_left = left_width
                    right_width = width - right_left
                    app.add(0, 0, f"Board | {title}"[:width], curses.A_BOLD)
                    app.add(1, 0, f"Active board: {board_label}"[:width])
                    app.add(2, 0, "Focus: artifact source"[:width], app.accent_attr())
                    app.draw_box(panel_top, 0, panel_height, left_width, "Artifact sources")
                    app.draw_box(panel_top, right_left, panel_height, right_width, "Details")
                    app.add(panel_top + 2, 2, "  Source", app.accent_attr())
                    for offset, (_source, choice_label, _description) in enumerate(choices):
                        attr = app.selected_attr() if offset == index else 0
                        marker = ">" if offset == index else " "
                        item_row = f"{marker} {offset + 1}. {choice_label}"
                        text = ui_text_api.fit_text(item_row, left_width - 4).ljust(left_width - 4)
                        app.add(panel_top + 3 + offset, 2, text, attr)

                    source_id, choice_label, description = choices[index]
                    detail_x = right_left + 2
                    detail_width = right_width - 4
                    row = panel_top + 2
                    app.add(row, detail_x, choice_label[:detail_width], curses.A_BOLD)
                    row += 2
                    for line in ui_text_api.wrap_text_lines(description, detail_width, 3):
                        app.add(row, detail_x, line)
                        row += 1
                    row += 1
                    if source_id == "build_host":
                        detail_lines = [
                            ("Build host", config_accessors.remote_label_for_config(app.config)),
                            ("SSH", config_accessors.remote_spec_for_config(app.config)),
                            ("Board staging", config_accessors.board_artifacts_dir_for_config(app.config)),
                        ]
                    else:
                        ui_config = app.config.get("ui", {})
                        remembered = (
                            Path(str(ui_config.get("local_artifact_directory"))).expanduser()
                            if isinstance(ui_config, dict) and ui_config.get("local_artifact_directory")
                            else None
                        )
                        default_dir = Path.home() / "Downloads"
                        start_dir = remembered or (default_dir if default_dir.is_dir() else Path.home())
                        detail_lines = [
                            ("Start directory", str(start_dir)),
                            ("Destination", config_accessors.board_artifacts_dir_for_config(app.config)),
                        ]
                    for field, value in detail_lines:
                        app.add(row, detail_x, ui_text_api.fit_text(f"{field}:", detail_width), app.accent_attr())
                        row += 1
                        app.add(row, detail_x + 2, ui_text_api.fit_text(value, max(1, detail_width - 2)))
                        row += 2
                    footer = "Up/Down: select | Enter: continue | q/Esc: back"
                    app.add(height - 2, 0, footer[:width].ljust(width), app.accent_attr())
                    status = str(getattr(app, "status", ""))
                    app.add(height - 1, 0, status[:width].ljust(width), curses.A_REVERSE)
                else:
                    app.add(0, 0, "Terminal is too small. Need at least 80x14.", app.warn_attr())
                app.screen.refresh()
                ch = app.read_key()
                if ui_input_api.key_code_matches(ch, "q") or ch == 27:
                    return None
                if height < 14 or width < 80:
                    continue
                if ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k"):
                    index = ui_menu_api.move_index(index, len(choices), -1)
                    self.artifact_source_index = index
                elif ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j"):
                    index = ui_menu_api.move_index(index, len(choices), 1)
                    self.artifact_source_index = index
                elif ch in (curses.KEY_ENTER, 10, 13):
                    self.artifact_source_index = index
                    return choices[index][0]
        finally:
            app.screen.timeout(1000)

    def run_local_artifact_flash(self, app: Any, action_id: str) -> Any:
        action = next(
            action for action in self.board_command_workflow.board_actions(
                app.config,
                build_params=getattr(app, "build_params", {}),
                allow_remote_manifest=False,
            )
            if action.action_id == action_id
        )
        spec = action.local_artifact
        if spec is None:
            raise ValueError(f"board action does not accept local artifacts: {action_id}")
        downloads = Path.home() / "Downloads"
        default_directory = downloads if downloads.is_dir() else Path.home()
        ui_config = app.config.get("ui", {})
        configured_directory = (
            Path(str(ui_config.get("local_artifact_directory", ""))).expanduser()
            if isinstance(ui_config, dict) and ui_config.get("local_artifact_directory")
            else None
        )
        initial_directory = configured_directory or default_directory
        if not initial_directory.is_dir():
            initial_directory = default_directory
        selected_parts: tuple[board_type_base_api.BoardArtifactPart, ...] = ()
        while True:
            source = ui_file_picker_api.select_local_file(
                app,
                title=spec.picker_title,
                accept_file=lambda path: path.name.endswith(spec.accepted_suffixes),
                initial_directory=initial_directory,
                file_hint=spec.picker_hint,
            )
            if source is None:
                app.status = "Back to artifact source selection"
                return LOCAL_ARTIFACT_BACK
            selected_directory = str(source.parent)
            app.config_store.update_config(
                lambda staged: staged.setdefault("ui", {}).__setitem__(
                    "local_artifact_directory", selected_directory
                )
            )
            initial_directory = source.parent
            if not spec.selection_title:
                break
            try:
                parts = ui_progress_api.run_modal_task(
                    app,
                    title="Inspect local artifact",
                    detail=source.name,
                    task=lambda report: self.board_command_workflow.local_artifact_parts(
                        app.config, action_id, source, report
                    ),
                )
            except ui_progress_api.ModalTaskCancelled:
                app.status = "Artifact inspection cancelled"
                continue
            except (OSError, ValueError) as exc:
                self.show_ipl_discovery_error(app, str(exc), title="Cannot read local artifact")
                continue
            selection = self.select_artifact_parts(app, spec, parts)
            if selection is None:
                app.status = "Back to local artifact selection"
                continue
            if not selection:
                app.status = "No artifact parts selected"
                continue
            selected_parts = tuple(selection)
            break
        destination_name, remove_patterns = self.board_command_workflow.local_artifact_destination(
            app.config, action_id, source
        )
        warning = self.board_command_workflow.local_artifact_warning(app.config, action_id)
        if not app.dialog_workflow_controller().run_confirm_dialog(
            app,
            ui_dialog_api.ConfirmContent(
                title="Confirm local artifact flash",
                warning=warning + " Close the serial console first.",
                subject=source.name,
                details=(
                    f"Local file: {source} | Size: {source.stat().st_size} bytes"
                    + (
                        " | Parts: " + ", ".join(part.label for part in selected_parts)
                        if selected_parts
                        else ""
                    )
                ),
                footer="Enter/y: copy and flash | n/q/Esc: back",
            ),
            redraw_background=False,
        ):
            app.status = "Local artifact flash cancelled"
            return None
        commands = self.board_command_workflow.copy_local_artifact_commands(
            app.config,
            source=source,
            destination_name=destination_name,
            remove_patterns=remove_patterns,
        )
        local_params = self.board_command_workflow.local_artifact_build_params(
            app.config, action_id, selected_parts
        )
        commands.extend(self.board_command_workflow.board_action_commands(
            app.config,
            action_id,
            build_params={**app.build_params, **local_params},
        ))
        label = action.label.removesuffix(" from build host") + " from local file"
        return app.command_workflow_service().run_commands(app, label, commands)

    def board_action_group(self, action_id: str) -> str:
        if action_id in {"ownership_acquire", "ownership_release", "ownership_status"}:
            return "flashing / ownership"
        if action_id in {
            "deploy_network_boot",
            "deploy_network_domd_rootfs",
            "deploy_network_domu_rootfs",
            "deploy_network_android",
            "unpack_network_android",
            "deploy_network_full",
        }:
            return "tftp/nfs / deploy artifacts"
        if action_id in {
            "pull_network_workspace",
            "push_network_workspace",
        }:
            return "tftp/nfs / tftp/nfs workspace"
        if action_id in {
            "pull_dom0_initramfs_workspace",
            "push_dom0_initramfs_workspace",
        }:
            return "tftp/nfs / dom0 initramfs workspace"
        if action_id in {
            "apply_uboot_network_env",
            "apply_uboot_ufs_env",
            "inject_invasive_uboot_parameters",
            "install_nfs_deploy_helper",
        }:
            return "tftp/nfs / board setup"
        if action_id in {"copy_build_artifacts", "flash_bootloaders", "flash_single_ipl", "flash_ufs_image"}:
            return "flashing / commands"
        if action_id == "open_board_host_shell":
            return "flashing / hosts"
        if action_id in {
            "restart_board",
            "turn_off_board",
            "open_board_serial_console",
            "open_uboot_console",
        }:
            return "flashing / board host"
        return "build"

    def board_action_commands(self, app: Any, action_id: str) -> list[list[str]]:
        return self.board_command_workflow.board_action_commands(
            app.config,
            action_id,
            artifact_targets=getattr(app, "board_artifacts", "") or app.build_targets,
            build_params=app.build_params,
        )

    def run_board_action(self, app: Any, action_id: str) -> Any:
        if action_id == "flash_single_ipl":
            return self.run_single_ipl_menu(app)
        return self.board_command_workflow.run_board_action(
            app.config,
            action_id,
            artifact_targets=getattr(app, "board_artifacts", "") or app.build_targets,
            build_params=app.build_params,
            runner=lambda title, commands: app.command_workflow_service().run_commands(app, title, commands),
        )

    def run_single_ipl_menu(self, app: Any) -> Any:
        capture = self.remote_capture_command(app)
        if capture is None:
            self.show_ipl_discovery_error(app, "IPL discovery unavailable: no capture command")
            return
        try:
            app.status = "Reading prepared IPL list from board host..."
            output = ""
            for command in self.board_action_commands(app, "flash_single_ipl"):
                output = capture(command)
            listing = json.loads(output)
            images = listing["images"]
            if not images:
                self.show_ipl_discovery_error(app, "No UFS IPL files found. Run Copy build artifacts with boot_artifacts selected.")
                return
        except Exception as exc:
            detail = getattr(exc, "stderr", "") or str(exc)
            self.show_ipl_discovery_error(app, detail)
            return
        selected = self.select_ipl_image(app, images)
        if selected is None:
            app.status = "Back to artifact source selection"
            return LOCAL_ARTIFACT_BACK
        if not selected:
            app.status = "IPL flash cancelled: no images selected"
            return LOCAL_ARTIFACT_BACK
        try:
            commands = self.board_command_workflow.board_action_commands(
                app.config, "flash_single_ipl",
                build_params={**app.build_params, "_ipl_names": json.dumps([image["name"] for image in selected]),
                              "_ipl_snapshot": listing["ipls_dir"]},
            )
        except ValueError as exc:
            self.show_ipl_discovery_error(app, str(exc), title="Cannot prepare IPL flash")
            return
        if not app.dialog_workflow_controller().run_confirm_dialog(
            app,
            ui_dialog_api.ConfirmContent(
                title="Flash bootloaders",
                warning="Power-cycles once and overwrites selected UFS bootloaders. Stops on failure; earlier writes are not rolled back. Close the serial console first.",
                subject=", ".join(image["name"] for image in selected),
                details=" | ".join(f"{image['name']}: UFS 0, {image['flash_addr']}" for image in selected) + f" | {listing['archive']}",
                footer="Enter/y: flash | n/q/Esc: back",
            ),
            redraw_background=False,
        ):
            app.status = "IPL flash cancelled"
            return
        app.command_workflow_service().run_commands(app, f"Flash {len(selected)} IPLs", commands)

    def show_ipl_discovery_error(self, app: Any, detail: str, *, title: str = "Cannot open IPL selection") -> None:
        lines = detail.strip().splitlines()[-8:]
        app.status = title
        app.dialog_workflow_controller().show_message(app, title, lines)

    def select_ipl_image(self, app: Any, images: list[dict[str, str]]) -> list[dict[str, str]] | None:
        index = 0
        selected = {image['name'] for image in images}
        app.screen.timeout(-1)
        try:
            while True:
                app.screen.erase()
                height, width = app.screen.getmaxyx()
                if height >= 10 and width >= 72:
                    app.draw_box(0, 0, height - 2, width, "Flash Bootloaders")
                    rows = max(1, height - 6)
                    start = max(0, min(index - rows + 1, len(images) - rows))
                    for offset, image in enumerate(images[start:start + rows]):
                        mark = '[x]' if image['name'] in selected else '[ ]'
                        label = f"{mark} {image['name']}  (UFS {image['flash_addr']})"
                        app.add(2 + offset, 2, ui_text_api.fit_text(label, width - 4),
                                app.selected_attr() if start + offset == index else 0)
                    app.add(height - 2, 0, "Space: toggle | a: all | n: none | Enter: flash | q/Esc: back"[:width], app.accent_attr())
                else:
                    app.add(0, 0, "Terminal is too small. Need at least 72x10.", app.warn_attr())
                app.screen.refresh()
                ch = app.read_key()
                if ui_input_api.key_code_matches(ch, "q") or ch == 27:
                    return None
                if height < 10 or width < 72:
                    continue
                if ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k"):
                    index = ui_menu_api.move_index(index, len(images), -1)
                elif ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j"):
                    index = ui_menu_api.move_index(index, len(images), 1)
                elif ch == ord(' ') and images:
                    name = images[index]['name']
                    if name in selected:
                        selected.remove(name)
                    else:
                        selected.add(name)
                elif ui_input_api.key_code_matches(ch, 'a'):
                    selected = {image['name'] for image in images}
                elif ui_input_api.key_code_matches(ch, 'n'):
                    selected.clear()
                elif ch in (curses.KEY_ENTER, 10, 13):
                    return [image for image in images if image['name'] in selected]
        finally:
            app.screen.timeout(1000)

    def select_artifact_parts(
        self,
        app: Any,
        spec: board_type_base_api.BoardLocalArtifactSpec,
        parts: list[board_type_base_api.BoardArtifactPart],
    ) -> list[board_type_base_api.BoardArtifactPart] | None:
        """Render a board-type-defined local artifact part selection."""
        index = 0
        selected = {part.part_id for part in parts}
        app.screen.timeout(-1)
        try:
            while True:
                app.screen.erase()
                height, width = app.screen.getmaxyx()
                if height >= 10 and width >= 72:
                    app.draw_box(0, 0, height - 2, width, spec.selection_title)
                    rows = max(1, height - 6)
                    start = max(0, min(index - rows + 1, len(parts) - rows))
                    for offset, part in enumerate(parts[start:start + rows]):
                        mark = "[x]" if part.part_id in selected else "[ ]"
                        suffix = f"  ({part.detail})" if part.detail else ""
                        label = f"{mark} {part.label}{suffix}"
                        app.add(
                            2 + offset,
                            2,
                            ui_text_api.fit_text(label, width - 4),
                            app.selected_attr() if start + offset == index else 0,
                        )
                    app.add(height - 2, 0, spec.selection_footer[:width], app.accent_attr())
                else:
                    app.add(0, 0, "Terminal is too small. Need at least 72x10.", app.warn_attr())
                app.screen.refresh()
                ch = app.read_key()
                if ui_input_api.key_code_matches(ch, "q") or ch == 27:
                    return None
                if height < 10 or width < 72:
                    continue
                if ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k"):
                    index = ui_menu_api.move_index(index, len(parts), -1)
                elif ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j"):
                    index = ui_menu_api.move_index(index, len(parts), 1)
                elif ch == ord(" ") and parts:
                    part_id = parts[index].part_id
                    if part_id in selected:
                        selected.remove(part_id)
                    else:
                        selected.add(part_id)
                elif ui_input_api.key_code_matches(ch, "a"):
                    selected = {part.part_id for part in parts}
                elif ui_input_api.key_code_matches(ch, "n"):
                    selected.clear()
                elif ch in (curses.KEY_ENTER, 10, 13):
                    return [part for part in parts if part.part_id in selected]
        finally:
            app.screen.timeout(1000)

    def run_interactive_board_action(self, app: Any, action_id: str, title: str) -> None:
        if action_id == "open_board_host_shell":
            app.terminal_session_controller().open_board_shell(app)
            return
        commands = self.board_action_commands(app, action_id)
        if not commands:
            return
        app.terminal_session_controller().open_command_shell(
            app,
            title,
            [
                "Interactive board-host setup.",
                "sudo may ask for the board-host password once.",
            ],
            commands[-1],
        )


def main_menu_command_items_service(
    *,
    remote_command_workflow: remote_workflow_api.RemoteCommandWorkflowService,
    sync_command_workflow: sync_workflow_api.SyncCommandWorkflowService,
    board_command_workflow: board_workflow_api.BoardCommandWorkflowService,
    app_dir: Path,
    default_moulin_manifest: str,
    remote_read_project_file: Callable[[dict[str, Any], str], str],
    manifest_cache: dict[tuple[str, ...], dict[str, Any]],
) -> MainMenuCommandItemsService:
    return MainMenuCommandItemsService(
        remote_command_workflow=remote_command_workflow,
        sync_command_workflow=sync_command_workflow,
        board_command_workflow=board_command_workflow,
        app_dir=app_dir,
        default_moulin_manifest=default_moulin_manifest,
        remote_read_project_file=remote_read_project_file,
        manifest_cache=manifest_cache,
    )
