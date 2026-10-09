#!/usr/bin/env python3
"""Render README screenshots through the real TUI renderers."""

from __future__ import annotations

import curses
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:  # pragma: no cover - developer utility guard
    raise SystemExit("Pillow is required to render README screenshots") from exc


APP_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = APP_DIR / "docs" / "screenshots"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
BOLD_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
WIDTH = 140
HEIGHT = 38
FONT_SIZE = 16

sys.path.insert(0, str(APP_DIR))

from components.host_config.api import fields as host_fields_api  # noqa: E402
from components.host_config_ui.api import board_screen_renderer as board_screen_renderer_api  # noqa: E402
from components.host_config_ui.api import board_screen_state as board_screen_state_api  # noqa: E402
from components.host_config_ui.api import remote_screen_renderer as remote_screen_renderer_api  # noqa: E402
from components.host_config_ui.api import remote_screen_state as remote_screen_state_api  # noqa: E402
from components.project_config_ui.api import project_screen as project_screen_api  # noqa: E402
from components.project_config_ui.api import project_screen_renderer as project_screen_renderer_api  # noqa: E402
from components.project_config_ui.api import project_screen_state as project_screen_state_api  # noqa: E402
from components.sync.api import screen as sync_screen_api  # noqa: E402
from components.sync.api import screen_workflow as sync_screen_workflow_api  # noqa: E402
import moulin_remote_client  # noqa: E402


BG = "#0f1416"
FG = "#e7eef2"
DIM = "#9aa4a9"
CYAN = "#5fd3df"
GREEN = "#64d18a"
ORANGE = "#f0a45a"
BLUE = "#67c7d0"
BLACK = "#061012"


class FakeScreen:
    def __init__(self, *, height: int = HEIGHT, width: int = WIDTH) -> None:
        self.height = height
        self.width = width
        self.cells: list[list[tuple[str, int]]] = [
            [(" ", 0) for _column in range(width)] for _row in range(height)
        ]

    def getmaxyx(self) -> tuple[int, int]:
        return self.height, self.width

    def erase(self) -> None:
        for row in range(self.height):
            for column in range(self.width):
                self.cells[row][column] = (" ", 0)

    clear = erase

    def refresh(self) -> None:
        return None

    def timeout(self, _value: int) -> None:
        return None

    def addstr(self, y: int, x: int, text: str, attr: int = 0) -> None:
        if y < 0 or y >= self.height:
            return
        for offset, char in enumerate(str(text)):
            column = x + offset
            if 0 <= column < self.width:
                self.cells[y][column] = (char, attr)


class RenderPort:
    def __init__(self, app: Any | None = None, *, height: int = HEIGHT, width: int = WIDTH) -> None:
        self.screen = FakeScreen(height=height, width=width)
        self.status = "Ready"
        self.connection_state = "connected"
        self.board_connection_state = "connected"
        self.config = demo_config()
        if app is not None:
            self.__dict__.update(app.__dict__)
            self.screen = app.screen

    def setup_colors(self) -> None:
        return None

    def add(self, y: int, x: int, text: str, attr: int = 0) -> None:
        self.screen.addstr(y, x, text, attr)

    def add_segments(self, y: int, x: int, max_width: int, segments: list[tuple[str, int]]) -> None:
        pos = x
        remaining = max_width
        for text, attr in segments:
            if remaining <= 0:
                return
            chunk = text[:remaining]
            self.add(y, pos, chunk, attr)
            pos += len(chunk)
            remaining -= len(chunk)

    def draw_box(self, top: int, left: int, height: int, width: int, title: str = "", attr: int = 0) -> None:
        if height < 2 or width < 2:
            return
        self.add(top, left, "+" + "-" * max(0, width - 2) + "+", attr)
        for row in range(top + 1, top + height - 1):
            self.add(row, left, "|", attr)
            self.add(row, left + 1, " " * max(0, width - 2))
            self.add(row, left + width - 1, "|", attr)
        self.add(top + height - 1, left, "+" + "-" * max(0, width - 2) + "+", attr)
        if title:
            self.add(top, left + 2, f" {title} "[: max(0, width - 4)], attr or self.accent_attr())

    def draw_wrapped(self, y: int, x: int, width: int, text: str, attr: int = 0, max_lines: int = 4) -> int:
        from components.ui.api import text as ui_text_api

        row = y
        for line in ui_text_api.wrap_text_lines(text, width, max_lines):
            self.add(row, x, line, attr)
            row += 1
        return row

    def draw_label_value_wrapped(self, row: int, x: int, width: int, label: str, value: str, *, max_lines: int = 3) -> int:
        from components.ui.api import layout as ui_layout_api

        layout = ui_layout_api.label_value_layout(x, width, label)
        self.add(row, x, layout.label_text.ljust(layout.label_width)[:width], self.accent_attr())
        return self.draw_wrapped(row, layout.value_x, layout.value_width, value or "<not set>", max_lines=max_lines)

    def draw_scrollbar(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def read_key(self) -> int:
        return ord("q")

    def selected_attr(self) -> int:
        return curses.A_REVERSE | curses.A_BOLD

    def selected_disabled_attr(self) -> int:
        return curses.A_REVERSE | curses.A_DIM

    def active_row_attr(self) -> int:
        return curses.A_BOLD

    def selected_active_attr(self) -> int:
        return curses.A_REVERSE | curses.A_BOLD

    def editing_attr(self) -> int:
        return curses.A_REVERSE | curses.A_BOLD

    def accent_attr(self) -> int:
        return curses.A_BOLD

    def warn_attr(self) -> int:
        return curses.A_BOLD

    def running_attr(self) -> int:
        return curses.A_BOLD

    def group_attr(self) -> int:
        return curses.A_BOLD

    def disabled_attr(self) -> int:
        return curses.A_DIM

    def ok_attr(self) -> int:
        return curses.A_BOLD

    def error_attr(self) -> int:
        return curses.A_BOLD

    def role_attr(self, role: str) -> int:
        return curses.A_BOLD if role in {"accent", "ok", "warn", "error"} else 0


def demo_config() -> dict[str, Any]:
    return {
        "ui": {"title": "Moulin Remote Client"},
        "active_remote": "gen5-build",
        "remotes": [
            {
                "name": "gen5-build",
                "label": "GEN5 build",
                "user": "builder",
                "host": "build-host",
                "projects_dir": "/mnt/projects",
            }
        ],
        "active_board_host": "x5h-board",
        "board_hosts": [
            {
                "name": "x5h-board",
                "label": "X5H board",
                "type": "gen5_x5h",
                "user": "board",
                "host": "x5h-host",
                "work_dir": "~/moulin-board-work",
                "console_device": "/dev/GEN5_CONSOLE0",
                "ufs_loadaddr": "0x48000000",
                "ufs_buffersize": "",
                "tftp_root": "/srv/tftp",
                "nfs_root": "/srv/nfs",
                "deploy_subdir": "vgon/artifacts",
                "server_ip": "192.0.2.10",
                "board_ip": "192.0.2.20",
                "direct_copy": "no",
            }
        ],
        "active_project": "gen5",
        "projects": [
            {
                "name": "gen5",
                "label": "GEN5 product",
                "project_dir": "meta-xt-prod-devel-rcar-gen5",
                "local_project_dir": "/home/user/work/project-overlay",
                "git_url": "git@gitbud.epam.com:rec-aaos/meta-xt-prod-devel-rcar-gen5.git",
                "git_ref": "virtio-scmi",
                "moulin_manifest": "prod-devel-rcar-gen5.yaml",
                "dockerfile": "doc/Dockerfile",
                "docker_image": "vgonch_gen5",
                "parameters": {"ENABLE_DOMU": "yes", "ENABLE_ANDROID": "no"},
                "targets": "boot_artifacts dom0 domd domu full.img.gz full_ufs.img.gz",
                "board_artifacts": "boot_artifacts dom0 domd domu full.img.gz full_ufs.img.gz",
                "mappings": [
                    {"name": "layers", "remote": "layers", "local": "layers"},
                    {"name": "android", "remote": "android", "local": "android"},
                    {"name": "shared", "remote": "shared", "local": "shared"},
                ],
                "active_mappings": ["layers", "shared"],
            }
        ],
        "local": {"project_dir": "workspace/project-overlay"},
        "moulin": {"manifest": "prod-devel-rcar-gen5.yaml"},
        "docker": {"image": "vgonch_gen5", "dockerfile": "doc/Dockerfile"},
        "state": {"build_settings": "workspace/moulin-build-settings.json"},
        "inventory": {
            "mapping_selection": "workspace/readme-selected-mappings.txt",
            "selection": "workspace/readme-selected-paths.txt",
            "output": "workspace/readme-remote-inventory.txt",
            "max_depth": 5,
            "mapping_depth": 3,
        },
        "mappings": [],
        "exclude": [".git/", ".repo/", "out/", "build/", "tmp/"],
    }


def fake_remote_read(_config: dict[str, Any], path: str) -> str:
    if path.endswith("prod-devel-rcar-gen5.yaml"):
        return """
parameters:
  ENABLE_DOMU:
    default: yes
  ENABLE_ANDROID:
    default: no
components:
  dom0:
  domd:
  domu:
images:
  boot_artifacts:
  full.img.gz:
  full_ufs.img.gz:
"""
    return ""


def make_app(
    *,
    preflight: str = "project ok | disk 230G free | git ## virtio-scmi...origin/virtio-scmi | docker ok",
    preflight_values: dict[str, str] | None = None,
    connection_state: str = "connected",
    board_connection_state: str = "connected",
    status: str = "Ready",
) -> Any:
    screen = FakeScreen()
    app = moulin_remote_client.ClientApp(screen, demo_config())
    app.connection_state = connection_state
    app.board_connection_state = board_connection_state
    app.preflight = preflight
    app.preflight_values = preflight_values or {
        "project": "ok",
        "disk": "230G free",
        "git": "## virtio-scmi...origin/virtio-scmi",
        "docker": "ok",
        "origin": "ok",
        "ref": "ok",
    }
    app.mapping_selection_cache = ["layers", "shared"]
    app.build_params = {"ENABLE_DOMU": "yes", "ENABLE_ANDROID": "no"}
    app.docker_image = "vgonch_gen5"
    app.build_targets = "boot_artifacts dom0 domd domu full.img.gz full_ufs.img.gz"
    app.board_artifacts = app.build_targets
    app.status = status
    app.menu_dirty = True
    app.main_full_redraw = True
    return app


def select_item(app: Any, label: str) -> None:
    app.items = app.build_items()
    for index, item in enumerate(app.items):
        if item.label == label:
            app.selected = index
            app.active_menu_tab = ""
            app.menu_dirty = False
            app.main_full_redraw = True
            return
    raise SystemExit(f"Unable to find menu item {label!r}")


def render_main(path: str, selected: str, **app_kwargs: Any) -> None:
    app = make_app(**app_kwargs)
    select_item(app, selected)
    with patch("curses.has_colors", return_value=False):
        app.draw()
    save_screen(path, app.screen)


def render_build_host_config(path: str) -> None:
    port = RenderPort()
    state = remote_screen_state_api.RemoteScreenStateController(port.config)
    renderer = remote_screen_renderer_api.RemoteScreenRenderer(
        port.config,
        remote_fields_factory=host_fields_api.remote_fields,
    )
    with patch("curses.has_colors", return_value=False):
        renderer.render(port, height=HEIGHT, width=WIDTH, screen_state=state)
    save_screen(path, port.screen)


def render_board_host_config(path: str) -> None:
    port = RenderPort()
    state = board_screen_state_api.BoardScreenStateController(port.config)
    renderer = board_screen_renderer_api.BoardScreenRenderer(
        port.config,
        board_host_fields_factory=host_fields_api.board_host_fields,
    )
    with patch("curses.has_colors", return_value=False):
        renderer.render(port, height=HEIGHT, width=WIDTH, screen_state=state)
    save_screen(path, port.screen)


def render_project_config(path: str) -> None:
    port = RenderPort()
    port.project_config_source = "Git remote"
    state = project_screen_state_api.ProjectScreenStateController(port.config)
    state.state.focus = "fields"
    state.state.field_index = 6
    renderer = project_screen_renderer_api.ProjectScreenRenderer(
        port.config,
        app_dir=APP_DIR,
        project_fields_factory=project_screen_api.project_fields,
    )
    params = [
        {"name": "ENABLE_DOMU", "default": "yes"},
        {"name": "ENABLE_ANDROID", "default": "no"},
    ]
    with patch("curses.has_colors", return_value=False):
        renderer.render(port, height=HEIGHT, width=WIDTH, params=params, screen_state=state)
    save_screen(path, port.screen)


def render_sync(path: str) -> None:
    port = RenderPort()
    port.config["projects"][0]["active_mappings"] = ["layers", "shared"]
    with patch("curses.has_colors", return_value=False):
        with patch("components.project.api.selection.project_mapping_selection_service") as selection_factory:
            selection = selection_factory.return_value
            selection.read_mapping_selection_for_config.return_value = ["layers", "shared"]
            sync_screen_api.run_sync_screen(
                port,
                port.config,
                APP_DIR,
                connected=lambda: True,
                action_controller=object(),
                screen_workflow=OneShotSyncWorkflow(),
            )
    save_screen(path, port.screen)


class OneShotSyncWorkflow:
    def __init__(self) -> None:
        self._delegate = sync_screen_workflow_api.sync_screen_workflow_service()

    def actions(self) -> list[dict[str, Any]]:
        return self._delegate.actions()

    def action_enabled(self, action: dict[str, Any], *, connected: bool) -> bool:
        return self._delegate.action_enabled(action, connected=connected)

    def disabled_status(self, action: dict[str, Any], *, connected: bool) -> str:
        return self._delegate.disabled_status(action, connected=connected)

    def mapping_detail_rows(self, mappings: list[dict[str, Any]], selected_names: list[str], *, limit: int) -> list[str]:
        return self._delegate.mapping_detail_rows(mappings, selected_names, limit=limit)

    def action_result_for_config(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("not used by screenshot renderer")


def save_screen(path: str, screen: FakeScreen) -> None:
    font = ImageFont.truetype(FONT, FONT_SIZE)
    bold = ImageFont.truetype(BOLD_FONT, FONT_SIZE)
    line_height = int(FONT_SIZE * 1.22)
    char_width = int(ImageDraw.Draw(Image.new("RGBA", (1, 1))).textlength("M", font=font))
    image = Image.new("RGBA", (screen.width * char_width + 16, screen.height * line_height + 16), BG)
    draw = ImageDraw.Draw(image)
    for row, cells in enumerate(screen.cells):
        x = 8
        y = 8 + row * line_height
        for char, attr in cells:
            selected = bool(attr & curses.A_REVERSE)
            dim = bool(attr & curses.A_DIM)
            bold_attr = bool(attr & curses.A_BOLD)
            if selected:
                draw.rectangle((x, y, x + char_width, y + line_height), fill=BLUE)
                fill = BLACK
                face = bold
            elif dim:
                fill = DIM
                face = font
            elif bold_attr:
                fill = GREEN if char not in "+-|[]" else CYAN
                face = bold
            else:
                fill = FG
                face = font
            draw.text((x, y), char, fill=fill, font=face)
            x += char_width
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    image.save(OUT_DIR / path)


def main() -> int:
    with patch.object(moulin_remote_client.BOOTSTRAP, "remote_project_file_reader", fake_remote_read):
        render_main("main-menu.png", "Run product build")
        render_main(
            "prepare-remote-project.png",
            "Prepare remote project",
            preflight="project missing | disk 230G free | git ? | origin missing | ref missing",
            preflight_values={
                "project": "missing",
                "disk": "230G free",
                "git": "?",
                "docker": "ok",
                "origin": "missing",
                "ref": "missing",
            },
            status="Remote checkout needs preparation",
        )
        render_main(
            "checkout-git-ref.png",
            "Checkout project Git ref",
            preflight="project ok | disk 230G free | git ## mirror | origin ok | ref mismatch:mirror",
            preflight_values={
                "project": "ok",
                "disk": "230G free",
                "git": "## mirror",
                "docker": "ok",
                "origin": "ok",
                "ref": "mismatch:mirror",
            },
            status="Remote checkout is on a different ref",
        )
        render_build_host_config("build-host-configuration.png")
        render_board_host_config("board-host-configuration.png")
        render_project_config("project-configurations.png")
        render_sync("sync-mapped-files.png")
        render_main("board-commands.png", "Flash UFS image")
        render_main("tftp-nfs-commands.png", "Deploy full TFTP/NFS set")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
