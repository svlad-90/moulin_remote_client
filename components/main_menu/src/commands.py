"""Main menu command item service."""

from __future__ import annotations

import curses
from pathlib import Path
import shlex
from typing import Any, Callable

from components.board.api import workflow as board_workflow_api
from components.build_runtime.api import runtime as config_runtime_api
from components.config.api import accessors as config_accessors
from components.moulin.api import manifest as moulin_manifest_api
from components.project.api import selection as project_selection_api
from components.remote.api import workflow as remote_workflow_api
from components.sync.api import workflow as sync_workflow_api
from components.ui.api import input as ui_input_api
from components.ui.api import menu as ui_menu_api
from components.ui.api import session as ui_session_api
from components.ui.api import text as ui_text_api
from components.ui.api.menu import MenuItem


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
        manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
    ) -> None:
        self.remote_command_workflow = remote_command_workflow
        self.sync_command_workflow = sync_command_workflow
        self.board_command_workflow = board_command_workflow
        self.app_dir = app_dir
        self.default_moulin_manifest = default_moulin_manifest
        self.remote_read_project_file = remote_read_project_file
        self.manifest_cache = manifest_cache
        self.mapping_selection_service = project_selection_api.project_mapping_selection_service()

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
                "Select build targets",
                "build / configuration",
                "Choose the Ninja targets used by product and incremental builds.",
                lambda app: f"Current build targets: {app.build_targets or '<not set>'}",
                lambda app: app.config_workflow_controller().select_build_targets(app),
                requires_project=True,
            ),
            MenuItem(
                "Build Docker image",
                "build / commands",
                "Rebuild the configured Docker image on the remote target.",
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
                lambda app: self.run_build_command(
                    app,
                    "Run product build",
                    self.remote_command_workflow.product_build_command(
                        app.config,
                        docker_image=app.docker_image,
                        targets=app.build_targets,
                    ),
                ),
                confirm=True,
                requires_remote=True,
                requires_project=True,
            ),
            MenuItem(
                "Incremental build",
                "build / commands",
                "Rebuild configured Moulin components incrementally, regenerate Moulin/Ninja, then run configured Ninja targets.",
                lambda app: ui_menu_api.command_preview(
                    self.incremental_product_build_commands(app)
                ),
                lambda app: self.run_incremental_build(app),
                requires_remote=True,
                requires_project=True,
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
                "Open build directory",
                "build / workspace",
                "Open a build-host shell in the active remote project directory.",
                lambda app: shlex.join(
                    self.build_host_directory_shell_command(
                        app.config,
                        config_accessors.remote_project_dir_for_config(app.config),
                    )
                ),
                lambda app: app.terminal_session_controller().open_build_host_directory_shell(
                    app,
                    "Open build directory",
                    config_accessors.remote_project_dir_for_config(app.config),
                ),
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
        items.extend(self.board_action_items(app))
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
                "Copy mapped files to build host",
                "build / files mapping",
                "Push selected local mapped files to the configured build host.",
                lambda app: ui_menu_api.command_preview(
                    self.sync_command_workflow.mapped_files_push_sequence(app.config)
                ),
                lambda app: self.run_sync_mapping_push(app),
                confirm=True,
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

    def build_host_directory_shell_command(self, config: dict[str, Any], path: str) -> list[str]:
        return ["ssh", "-t", config_accessors.remote_spec_for_config(config), f"cd {shlex.quote(path)} && exec bash -l"]

    def board_host_directory_shell_command(self, config: dict[str, Any], path: str) -> list[str]:
        return ["ssh", "-t", config_accessors.board_host_spec_for_config(config), f"cd {shlex.quote(path)} && exec bash -l"]

    def run_incremental_build(self, app: Any) -> Any:
        app.reload_config_from_disk()
        components = self.incremental_components(app)
        selected_names = self.select_incremental_component_names(app, components)
        if selected_names is None:
            app.status = "Incremental build cancelled"
            return None
        if not selected_names:
            app.status = "Incremental build cancelled: no components selected"
            return None
        config_runtime_api.save_runtime_incremental_components(app.config, self.app_dir, selected_names)
        return app.command_workflow_service().run_commands(
            app,
            "Incremental build",
            self.incremental_product_build_commands(app, selected_names=selected_names),
        )

    def incremental_product_build_commands(self, app: Any, selected_names: list[str] | None = None) -> list[list[str]]:
        components = self.incremental_components(app)
        selected_name_set = set(selected_names or [])
        selected = [component for component in components if component["name"] in selected_name_set]
        if not selected:
            selected = [component for component in components if component["supported"]]

        yocto_recipes = [
            str(component["target"])
            for component in selected
            if component["builder_type"] == "yocto" and str(component["target"]).strip()
        ]
        ninja_components = [
            str(component["name"])
            for component in selected
            if component["builder_type"] in {"bazel", "android"}
        ]
        bazel_components = [component for component in selected if component["builder_type"] == "bazel"]
        bazel_config_targets = self.bazel_config_targets_for_components(selected)

        commands: list[list[str]] = []
        commands.append(
            self.remote_command_workflow.yocto_impact_command(
                app.config,
                docker_image=app.docker_image,
                targets=app.build_targets,
                action="clean",
                image_recipes=yocto_recipes,
                allow_empty=True,
            )
        )
        commands.append(
            self.remote_command_workflow.moulin_regen_command(
                app.config,
                docker_image=app.docker_image,
                build_params=app.build_params,
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
        for component in bazel_components:
            commands.append(
                self.remote_command_workflow.bazel_component_command(
                    app.config,
                    docker_image=app.docker_image,
                    component=component,
                )
            )
        if ninja_components:
            commands.append(
                self.remote_command_workflow.product_build_command(
                    app.config,
                    docker_image=app.docker_image,
                    targets=" ".join(ninja_components),
                )
            )
        commands.append(
            self.remote_command_workflow.product_build_command(
                app.config,
                docker_image=app.docker_image,
                targets=app.build_targets,
            )
        )
        return commands

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

    def incremental_components(self, app: Any) -> list[dict[str, Any]]:
        components = moulin_manifest_api.component_builders_for_config(
            app.config,
            app_dir=self.app_dir,
            remote_read_project_file=self.remote_read_project_file,
            cache=self.manifest_cache,
            default_moulin_manifest=self.default_moulin_manifest,
            build_params=app.build_params,
        )
        supported_types = {"yocto", "bazel", "android"}
        return [
            {
                **component,
                "supported": str(component.get("builder_type", "")) in supported_types,
            }
            for component in components
        ]

    def active_incremental_mappings(self, app: Any) -> list[dict[str, Any]]:
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
        return [str(component["name"]) for component in supported if str(component["name"]) in selected]

    def incremental_change_state(self, app: Any, components: list[dict[str, Any]]) -> dict[str, list[str]]:
        changed = self.changed_incremental_mappings(app)
        return {
            "mappings": [str(mapping["name"]) for mapping in changed],
            "components": self.auto_incremental_component_names(components, changed),
        }

    def changed_incremental_mappings(self, app: Any) -> list[dict[str, Any]]:
        mappings = self.active_incremental_mappings(app)
        changed_names = config_runtime_api.changed_runtime_mappings(app.config, self.app_dir, mappings) if mappings else []
        return [mapping for mapping in mappings if str(mapping.get("name", "")) in set(changed_names)]

    def select_incremental_component_names(self, app: Any, components: list[dict[str, Any]]) -> list[str] | None:
        supported = [component for component in components if component["supported"]]
        supported_names = {str(component["name"]) for component in supported}
        change_state = self.incremental_change_state(app, components)
        auto_names = [name for name in change_state["components"] if name in supported_names]
        stored_names = config_runtime_api.load_runtime_incremental_components(app.config, self.app_dir)
        selected = set(auto_names or stored_names or supported_names) & supported_names
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

                index = ui_menu_api.clamp_index(index, len(components))
                app.draw_box(0, 0, height - 2, width, "Incremental Build")
                app.add(1, 2, "Select Moulin components to rebuild, then press Enter.", app.accent_attr())
                app.add(2, 2, ui_text_api.fit_text(f"Final targets: {app.build_targets}", width - 4))
                app.add(3, 2, ui_text_api.fit_text("Selected: " + " ".join(name for name in selected if name), width - 4))

                changed_text = "Changed since last copy: " + (
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
                    mark = "[x]" if name in selected else "[ ]"
                    if not enabled:
                        mark = "[-]"
                    label = f"{mark} {name} ({component['builder_type']})"
                    attr = app.disabled_attr() if not enabled else app.selected_attr() if offset == index else 0
                    app.add(row, 2, ui_text_api.fit_text(label, width - 4).ljust(width - 4), attr)

                if components:
                    current = components[index]
                    desc = (
                        f"Incremental rebuild is supported for {current['builder_type']}."
                        if current["supported"]
                        else f"Incremental rebuild is not supported for {current['builder_type']} yet."
                    )
                    app.add(height - 4, 2, ui_text_api.fit_text(desc, width - 4))
                footer = "Up/Down: select | Space: toggle supported | Enter: run | q/Esc: cancel"
                app.add(height - 2, 0, footer[:width], app.accent_attr())
                app.add(height - 1, 0, app.status[:width].ljust(width), curses.A_REVERSE)
                app.screen.refresh()
                ch = app.read_key()
                if (ch == curses.KEY_UP or ui_input_api.key_code_matches(ch, "k")) and components:
                    index = ui_menu_api.move_index(index, len(components), -1)
                elif (ch == curses.KEY_DOWN or ui_input_api.key_code_matches(ch, "j")) and components:
                    index = ui_menu_api.move_index(index, len(components), 1)
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
        return app.command_workflow_service().run_commands(
            app,
            "Copy mapped files to build host",
            self.sync_command_workflow.mapped_files_push_sequence(app.config),
        )

    def copy_build_artifacts_commands(self, app: Any) -> list[list[str]]:
        return self.board_command_workflow.copy_build_artifacts_commands(
            app.config,
            artifact_targets=getattr(app, "board_artifacts", "") or app.build_targets,
            build_params=app.build_params,
        )

    def board_action_items(self, app: Any) -> list[MenuItem]:
        return [
            MenuItem(
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
            )
            for action in self.board_command_workflow.board_actions(app.config)
        ]

    def board_action_group(self, action_id: str) -> str:
        if action_id in {
            "deploy_network_boot",
            "deploy_network_domd_rootfs",
            "deploy_network_android",
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
            "install_nfs_deploy_helper",
        }:
            return "tftp/nfs / board setup"
        if action_id in {"copy_build_artifacts", "flash_bootloaders", "flash_ufs_image"}:
            return "flashing / commands"
        if action_id in {
            "open_board_host_shell",
            "restart_board",
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
        return self.board_command_workflow.run_board_action(
            app.config,
            action_id,
            artifact_targets=getattr(app, "board_artifacts", "") or app.build_targets,
            build_params=app.build_params,
            runner=lambda title, commands: app.command_workflow_service().run_commands(app, title, commands),
        )

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
    manifest_cache: dict[tuple[str, str, str], dict[str, Any]],
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
